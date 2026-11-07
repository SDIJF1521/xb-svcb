"""自定义翻唱工作流：节点图模型与校验。

工作流是一张有向无环图（DAG）。每个节点是一个音频处理步骤，
端口按 ``type`` 决定输入/输出。前端拖拽连线画布产出的 JSON 结构：

.. code-block:: json

    {
      "id": "wf_xxx",
      "name": "我的工作流",
      "updated_at": "2026-01-01T00:00:00",
      "nodes": [
        {"id": "n1", "type": "input", "x": 0, "y": 0, "params": {}},
        {"id": "n2", "type": "separate", "x": 200, "y": 0,
         "params": {"engine": "uvr", "model": "MDX-Net", "device": "auto"}}
      ],
      "edges": [
        {"id": "e1", "from": {"node": "n1", "port": "audio"},
         "to": {"node": "n2", "port": "audio"}}
      ]
    }

``blend``（人声合唱叠加）的输入端口允许多条连线；其余端口默认单输入。
"""

from __future__ import annotations

import re
from typing import Any


# 节点类型定义：inputs/outputs 为端口 id 列表，multi_inputs 为允许多连线的输入端口。
NODE_TYPES: dict[str, dict[str, Any]] = {
    "input": {"inputs": [], "outputs": ["audio"], "multi_inputs": set()},
    # 分离节点的输出随引擎 / 模型变化：
    #   vocals/instrumental —— 人声分离类模型（UVR 与 PyMSS 人声模型）
    #   audio               —— 单轨输出（去混响 / 修复类 PyMSS 模型只产出干声）
    #   other               —— 多轨模型的附加音轨（取第一路未映射的 stem）
    #   stem:<label>        —— 多轨模型的其余 stem，按模型输出的音轨名动态生成
    "separate": {
        "inputs": ["audio"],
        "outputs": ["vocals", "instrumental", "audio", "other"],
        "dynamic_outputs": ("stem:",),
        "multi_inputs": set(),
    },
    "dereverb": {"inputs": ["audio"], "outputs": ["audio"], "multi_inputs": set()},
    "repair": {"inputs": ["audio"], "outputs": ["audio"], "multi_inputs": set()},
    "convert": {"inputs": ["audio"], "outputs": ["audio"], "multi_inputs": set()},
    "blend": {"inputs": ["audio"], "outputs": ["audio"], "multi_inputs": {"audio"}},
    "enhance": {"inputs": ["audio"], "outputs": ["audio"], "multi_inputs": set()},
    "mix": {"inputs": ["vocals", "instrumental"], "outputs": ["audio"], "multi_inputs": set()},
    # 保存节点允许多路音轨接入（可同时保存人声/伴奏/混音等），也允许多个保存节点并存。
    "output": {"inputs": ["audio"], "outputs": [], "multi_inputs": {"audio"}},
}

# 端口中文名（节点卡片、运行日志与报错提示共用）。
PORT_LABELS: dict[str, str] = {
    "audio": "音频",
    "vocals": "人声",
    "instrumental": "伴奏",
    "other": "其他音轨",
}

# 音轨名与这些通用端口同名时直接占用通用端口，旧工作流的连线可无缝继续使用。
CANONICAL_STEM_PORTS = ("vocals", "instrumental", "other", "audio")


def stem_port_id(label: str, index: int = 0) -> str:
    """模型音轨名 → 端口 id：同名通用端口直用，否则 ``stem:<slug>``。

    例：vocals → ``vocals``；drums → ``stem:drums``；No Reverb →
    ``stem:no_reverb``。前端用同一套规则，保证连线端口一致。
    """
    slug = re.sub(r"[^0-9a-zA-Z_\u4e00-\u9fff]+", "_", str(label or "")).strip("_").lower()
    if slug in CANONICAL_STEM_PORTS:
        return slug
    return f"stem:{slug or f'stem{index + 1}'}"


def port_label(port: str) -> str:
    """端口的可读名称；``stem:xxx`` 这类动态端口回落为音轨名。"""
    key = str(port or "")
    if key in PORT_LABELS:
        return PORT_LABELS[key]
    if key.startswith("stem:"):
        return f"音轨 {key.split(':', 1)[1]}" if ":" in key else "音轨"
    return key


def output_port_allowed(node_type: str, port: str) -> bool:
    """判断某个输出端口是否可用（含分离节点按模型动态生成的 stem 端口）。"""
    definition = NODE_TYPES.get(str(node_type or ""))
    if not definition:
        return False
    key = str(port or "")
    if key in definition["outputs"]:
        return True
    for prefix in definition.get("dynamic_outputs") or ():
        if key.startswith(prefix) and len(key) > len(prefix):
            return True
    return False

# 节点中文显示名（前端画布与后端步骤标签共用）。
NODE_LABELS: dict[str, str] = {
    "input": "输入音频",
    "separate": "人声分离",
    "dereverb": "去混响净化",
    "repair": "人声修复",
    "convert": "歌声转换",
    "blend": "人声合唱叠加",
    "enhance": "AI 歌声增强",
    "mix": "混音合成",
    "output": "输出成品",
}

# 节点中文说明（前端画布节点卡片的副标题）。
NODE_DESCRIPTIONS: dict[str, str] = {
    "input": "整首歌曲源音频（翻唱入口）",
    "separate": "UVR / PyMSS 分离出人声与伴奏",
    "dereverb": "去除人声混响 / 回声净化",
    "repair": "DeepFilterNet3 修复分离伪影",
    "convert": "按所选模型进行歌声转换推理",
    "blend": "多路转换人声叠加为合唱",
    "enhance": "AI 自然修音 / 音色美化",
    "mix": "转换人声与伴奏重新混音",
    "output": "最终翻唱成品输出",
}


def node_definition(node_type: str) -> dict[str, Any] | None:
    return NODE_TYPES.get(node_type)


def validate_graph(graph: dict[str, Any]) -> str | None:
    """校验工作流图，返回错误信息；合法时返回 None。"""
    if not isinstance(graph, dict):
        return "工作流数据无效"
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    if not isinstance(nodes, list) or not nodes:
        return "工作流至少需要一个节点"
    if not isinstance(edges, list):
        return "工作流连线数据无效"

    ids: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            return "节点数据无效"
        nid = str(node.get("id") or "")
        ntype = str(node.get("type") or "")
        if not nid or nid in ids:
            return "节点 id 缺失或重复"
        if ntype not in NODE_TYPES:
            return f"未知节点类型：{ntype}"
        ids.add(nid)

    kinds = [str(n.get("type") or "") for n in nodes]
    if kinds.count("input") != 1:
        return "工作流必须包含且仅包含一个「输入音频」节点"
    if kinds.count("output") != 1:
        return "工作流必须包含且仅包含一个「保存」节点"

    for edge in edges:
        if not isinstance(edge, dict):
            return "连线数据无效"
        frm = edge.get("from") or {}
        to = edge.get("to") or {}
        fnode = str(frm.get("node") or "")
        fport = str(frm.get("port") or "")
        tnode = str(to.get("node") or "")
        tport = str(to.get("port") or "")
        if fnode not in ids or tnode not in ids:
            return "连线引用了不存在的节点"
        fdef = NODE_TYPES.get(str((_node_by_id(nodes, fnode) or {}).get("type") or ""))
        tdef = NODE_TYPES.get(str((_node_by_id(nodes, tnode) or {}).get("type") or ""))
        ftype = str((_node_by_id(nodes, fnode) or {}).get("type") or "")
        if not fdef or not output_port_allowed(ftype, fport):
            return f"节点 {fnode} 没有输出端口 {fport}"
        if not tdef or tport not in tdef["inputs"]:
            return f"节点 {tnode} 没有输入端口 {tport}"

    # 单输入端口不可被多条连线同时驱动（blend 的 audio 除外）。
    incoming: dict[tuple[str, str], list[str]] = {}
    for edge in edges:
        to = edge.get("to") or {}
        key = (str(to.get("node") or ""), str(to.get("port") or ""))
        incoming.setdefault(key, []).append(str(edge.get("id") or ""))
    for (tnode, tport), conns in incoming.items():
        node = _node_by_id(nodes, tnode)
        if not node:
            continue
        tdef = NODE_TYPES.get(str(node.get("type") or ""))
        if not tdef:
            continue
        if tport in tdef["multi_inputs"]:
            continue
        if len(conns) > 1:
            return f"节点 {tnode} 的输入端口 {tport} 只能连接一条线"

    if topological_order(nodes, edges) is None:
        return "工作流存在循环连线，请断开成环的连线"
    return None


def topological_order(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[str] | None:
    """按依赖关系返回节点的拓扑执行顺序；存在环时返回 None。"""
    ids = [str(n.get("id") or "") for n in nodes]
    in_degree: dict[str, int] = {i: 0 for i in ids}
    adj: dict[str, list[str]] = {i: [] for i in ids}
    for edge in edges:
        fnode = str((edge.get("from") or {}).get("node") or "")
        tnode = str((edge.get("to") or {}).get("node") or "")
        if fnode not in in_degree or tnode not in in_degree:
            continue
        adj[fnode].append(tnode)
        in_degree[tnode] += 1
    queue = [i for i in ids if in_degree[i] == 0]
    order: list[str] = []
    while queue:
        current = queue.pop(0)
        order.append(current)
        for nxt in adj[current]:
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)
    return order if len(order) == len(ids) else None


def _node_by_id(nodes: list[dict[str, Any]], node_id: str) -> dict[str, Any] | None:
    for node in nodes:
        if str(node.get("id") or "") == node_id:
            return node
    return None
