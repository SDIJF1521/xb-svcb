"""翻唱工作流商城：清单（manifest）的纯领域规则。

本模块不读文件、不发网络请求、不依赖 ``config``，只负责：

- 商城清单的 magic / schema / 大小与节点数量上限；
- 节点图的安全收敛与校验；
- 清单 → 可展示数据、PyMSS 依赖、预览图的纯变换；
- 已保存工作流的来源信息规整。

网络、进程与落盘由 ``infrastructure/workflow_hub_client.py`` 实现，
用例层 ``application/workflow_hub_service.py`` 只负责编排。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from .workflow_graph import NODE_TYPES, validate_graph

# 清单格式标记：下载 / 搜索时据此确认确实是本软件上传的工作流。
WORKFLOW_MANIFEST_MAGIC = "XB-SVCB-COVER-WORKFLOW"
WORKFLOW_MANIFEST_SCHEMA = 1
WORKFLOW_MANIFEST_KIND = "cover-workflow"
WORKFLOW_MANIFEST_MAX_BYTES = 2 * 1024 * 1024
WORKFLOW_MANIFEST_MAX_NODES = 300
WORKFLOW_MANIFEST_MAX_EDGES = 1200
WORKFLOW_MANIFEST_MAX_PYMSS_MODELS = 24

# 需要 PyMSS 的声音前处理节点；UVR 节点不进入商城依赖清单。
PYMSS_SEPARATOR_NODE_TYPES = frozenset({"separate", "dereverb"})
PYMSS_DEFAULT_NODE_PURPOSE = {
    "separate": "vocal_separation",
    "dereverb": "dereverb",
}

# 与 config.PYMSS_ALLOWED_MODEL_CATEGORIES 的用途 id 保持一致；
# 领域层不 import config，因此这里用字面量并通过应用层传入校验收敛。
PYMSS_PURPOSE_IDS = frozenset({"vocal_separation", "dereverb", "harmony_removal"})

_ORIGIN_DOWNLOADED = "downloaded"
_ORIGIN_UPLOADED = "uploaded"


def trim_text(value: Any, max_len: int) -> str:
    """清理控制字符、压缩空白并截断（清单与标签共用）。"""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]+", " ", str(value or "")).strip()
    return text[: max(0, max_len)]


def normalize_tags(value: Any, *, limit: int = 8, tag_len: int = 24) -> list[str]:
    raw = value if isinstance(value, (list, tuple)) else str(value or "").split(",")
    tags: list[str] = []
    for item in raw:
        tag = trim_text(item, tag_len)
        if tag and tag not in tags:
            tags.append(tag)
    return tags[:limit]


def normalize_version(value: Any) -> str:
    text = trim_text(value, 32)
    text = re.sub(r"[^0-9A-Za-z._-]+", "", text)
    # 界面统一显示为 v<version>，避免用户输入 v1.0 后出现 vv1.0。
    text = re.sub(r"^[vV](?=\d)", "", text)
    return text or "1.0.0"


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def sanitize_graph(graph: Any) -> dict[str, Any] | None:
    """把外部节点图收敛成纯 JSON 结构并校验，非法时返回 None。

    约束与 ``domain.workflow_graph.validate_graph`` 保持一致；额外的收敛包括：
    未知节点类型丢弃、坐标非法归零、参数做一次 JSON 往返、数量上限。
    """
    if not isinstance(graph, dict):
        return None
    raw_nodes = graph.get("nodes")
    raw_edges = graph.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        return None
    nodes: list[dict[str, Any]] = []
    for raw in raw_nodes[:WORKFLOW_MANIFEST_MAX_NODES]:
        if not isinstance(raw, dict):
            continue
        node_type = str(raw.get("type") or "").strip()
        node_id = trim_text(raw.get("id"), 64)
        if not node_id or node_type not in NODE_TYPES:
            continue
        params = raw.get("params")
        if not isinstance(params, dict):
            params = {}
        try:
            params = json.loads(json.dumps(params, ensure_ascii=False, default=str))
        except (TypeError, ValueError):
            params = {}
        nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "x": _as_float(raw.get("x")),
                "y": _as_float(raw.get("y")),
                "params": params,
            }
        )
    edges: list[dict[str, Any]] = []
    seen_edge_ids: set[str] = set()
    for raw in raw_edges[:WORKFLOW_MANIFEST_MAX_EDGES]:
        if not isinstance(raw, dict):
            continue
        source_raw = raw.get("from")
        target_raw = raw.get("to")
        source = source_raw if isinstance(source_raw, dict) else {}
        target = target_raw if isinstance(target_raw, dict) else {}
        source_node = trim_text(source.get("node"), 64)
        target_node = trim_text(target.get("node"), 64)
        if not source_node or not target_node:
            continue
        # 边 ID 必须唯一：Vue 用 key 复用连线节点，重复 ID 会让画布把两条线
        # 画成同一条 / 连到错误端点。旧工作流缺 ID 时生成稳定兜底值。
        edge_id = trim_text(raw.get("id"), 64)
        if not edge_id or edge_id in seen_edge_ids:
            base = f"e_{len(edges) + 1}"
            edge_id = base
            suffix = 2
            while edge_id in seen_edge_ids:
                edge_id = f"{base}_{suffix}"
                suffix += 1
        seen_edge_ids.add(edge_id)
        edges.append(
            {
                "id": edge_id,
                "from": {
                    "node": source_node,
                    "port": trim_text(source.get("port"), 64),
                },
                "to": {
                    "node": target_node,
                    "port": trim_text(target.get("port"), 64),
                },
            }
        )
    cleaned = {"id": "", "name": "", "updated_at": "", "nodes": nodes, "edges": edges}
    if validate_graph(cleaned):
        return None
    return cleaned


def workflow_graph_fingerprint(graph: Any) -> str | None:
    """工作流的语义指纹（SHA-256），用于识别本地是否已有同一工作流。

    只纳入节点 ``id/type/params`` 与边的起止端口，**不包含**画布坐标、工作流
    名称、版本、来源仓库等展示字段。因此：

    * 用户拖动节点布局、重命名工作流，仍然能识别为同一内容；
    * 修改节点参数或连线，指纹会变化，不会误判为已下载。

    Python 侧只做几十 KB 的 JSON 规范化 + ``hashlib``（C 实现），比模型权重
    哈希轻量得多；调用方仍会按 ``(工作流 id, updated_at)`` 缓存结果。
    """
    cleaned = sanitize_graph(graph)
    if not cleaned or not cleaned.get("nodes"):
        return None
    nodes = sorted(
        (
            {
                "id": node.get("id", ""),
                "type": node.get("type", ""),
                "params": node.get("params") or {},
            }
            for node in cleaned["nodes"]
        ),
        key=lambda node: str(node["id"]),
    )
    edges = sorted(
        (
            {
                "from": {
                    "node": (edge.get("from") or {}).get("node", ""),
                    "port": (edge.get("from") or {}).get("port", ""),
                },
                "to": {
                    "node": (edge.get("to") or {}).get("node", ""),
                    "port": (edge.get("to") or {}).get("port", ""),
                },
            }
            for edge in cleaned["edges"]
        ),
        key=lambda edge: (
            str(edge["from"]["node"]),
            str(edge["from"]["port"]),
            str(edge["to"]["node"]),
            str(edge["to"]["port"]),
        ),
    )
    payload = json.dumps(
        {"nodes": nodes, "edges": edges},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_workflow_manifest(data: Any) -> bool:
    """只做结构判断（不抛异常），供搜索 / 下载快速过滤。"""
    if not isinstance(data, dict):
        return False
    if data.get("magic") != WORKFLOW_MANIFEST_MAGIC:
        return False
    graph = data.get("graph")
    if not isinstance(graph, dict):
        return False
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not nodes or not isinstance(edges, list):
        return False
    if len(nodes) > WORKFLOW_MANIFEST_MAX_NODES:
        return False
    if len(edges) > WORKFLOW_MANIFEST_MAX_EDGES:
        return False
    return bool(trim_text(data.get("name"), 120))


def parse_workflow_manifest(data: Any) -> dict[str, Any] | None:
    """校验并规整商城清单；非法时返回 None。"""
    if not is_workflow_manifest(data):
        return None
    return {
        "name": trim_text(data.get("name"), 120),
        "description": trim_text(data.get("description"), 1200),
        "version": normalize_version(data.get("version")),
        "tags": normalize_tags(data.get("tags")),
        "graph": {
            "nodes": list((data.get("graph") or {}).get("nodes") or []),
            "edges": list((data.get("graph") or {}).get("edges") or []),
        },
        "pymss_models": normalize_pymss_requirements(data.get("pymss_models")),
        "uploaded_by": trim_text(data.get("uploaded_by") or data.get("author"), 80),
        "uploaded_at": trim_text(data.get("uploaded_at"), 40),
        "lineage_id": trim_text(data.get("lineage_id"), 200),
    }


def graph_from_manifest(manifest: dict[str, Any]) -> dict[str, Any] | None:
    graph = manifest.get("graph") if isinstance(manifest, dict) else None
    cleaned = sanitize_graph(graph)
    if cleaned is not None:
        cleaned["name"] = trim_text(manifest.get("name"), 120)
    return cleaned


def build_workflow_manifest(
    *,
    name: str,
    graph: dict[str, Any],
    version: str,
    description: str = "",
    tags: Any = None,
    pymss_models: Any = None,
    uploaded_by: str = "",
    uploaded_at: str = "",
    lineage_id: str = "",
    app_name: str,
    marker: str,
) -> dict[str, Any]:
    """构造可上传的商城清单（节点图经安全收敛）。"""
    cleaned = sanitize_graph(graph)
    if cleaned is None:
        raise ValueError("工作流节点图无效")
    display = trim_text(name, 120) or "工作流"
    return {
        "magic": WORKFLOW_MANIFEST_MAGIC,
        "schema": WORKFLOW_MANIFEST_SCHEMA,
        "app": trim_text(app_name, 40),
        "marker": trim_text(marker, 80),
        "kind": WORKFLOW_MANIFEST_KIND,
        "name": display,
        "description": trim_text(description, 1200),
        "version": normalize_version(version),
        "tags": normalize_tags(tags),
        "graph": {"nodes": cleaned["nodes"], "edges": cleaned["edges"]},
        "node_count": len(cleaned["nodes"]),
        "edge_count": len(cleaned["edges"]),
        "pymss_models": normalize_pymss_requirements(pymss_models),
        "lineage_id": trim_text(lineage_id, 200),
        "uploaded_by": trim_text(uploaded_by, 80),
        "uploaded_at": trim_text(uploaded_at, 40),
    }


def preview_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """列表缩略图只需要坐标与端口，去掉参数以减小搜索响应体积。"""
    nodes = [
        {
            "id": node.get("id", ""),
            "type": node.get("type", ""),
            "x": node.get("x", 0),
            "y": node.get("y", 0),
        }
        for node in graph.get("nodes") or []
        if isinstance(node, dict)
    ]
    edges = [
        {"id": edge.get("id", ""), "from": edge.get("from"), "to": edge.get("to")}
        for edge in graph.get("edges") or []
        if isinstance(edge, dict)
    ]
    return {"nodes": nodes, "edges": edges}


def pymss_model_names(nodes: Any) -> list[str]:
    """按出现顺序提取工作流引用的 PyMSS 模型名（去重）。"""
    names: list[str] = []
    for node in nodes or []:
        if not isinstance(node, dict) or node.get("type") not in PYMSS_SEPARATOR_NODE_TYPES:
            continue
        params_raw = node.get("params")
        params = params_raw if isinstance(params_raw, dict) else {}
        if str(params.get("engine") or "").strip().lower() != "pymss":
            continue
        name = trim_text(params.get("model"), 160)
        if name and name not in names:
            names.append(name)
    return names


def pymss_node_default_purpose(nodes: Any) -> dict[str, str]:
    """模型目录缺失时的用途推断：分离节点→人声分离，去混响节点→去混响。"""
    purposes: dict[str, str] = {}
    for node in nodes or []:
        if not isinstance(node, dict) or node.get("type") not in PYMSS_SEPARATOR_NODE_TYPES:
            continue
        params_raw = node.get("params")
        params = params_raw if isinstance(params_raw, dict) else {}
        if str(params.get("engine") or "").strip().lower() != "pymss":
            continue
        name = trim_text(params.get("model"), 160)
        if name:
            purposes.setdefault(
                name,
                PYMSS_DEFAULT_NODE_PURPOSE.get(str(node.get("type")), ""),
            )
    return purposes


def normalize_pymss_requirements(rows: Any) -> list[dict[str, Any]]:
    """规整清单里的 PyMSS 依赖项，限制数量并去重。"""
    if not isinstance(rows, list):
        return []
    requirements: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows[:WORKFLOW_MANIFEST_MAX_PYMSS_MODELS]:
        if not isinstance(row, dict):
            continue
        name = trim_text(row.get("name"), 160)
        if not name or name in seen:
            continue
        seen.add(name)
        purpose = trim_text(row.get("purpose"), 40)
        requirements.append(
            {
                "name": name,
                "purpose": purpose if purpose in PYMSS_PURPOSE_IDS else "",
                "purpose_label": trim_text(row.get("purpose_label"), 40),
                "architecture": trim_text(row.get("architecture"), 60),
                "category_label": trim_text(row.get("category_label"), 120),
                "target_stem": trim_text(row.get("target_stem"), 60),
                "size_bytes": max(0, _as_int(row.get("size_bytes"))),
            }
        )
    return requirements


def pymss_model_stem_key(name: str) -> str:
    """PyMSS 模型按文件名 stem 比较（扩展名可能因目录版本不同）。"""
    return Path(str(name or "")).stem.lower()


def normalize_workflow_source(source: Any) -> dict[str, Any]:
    """规整「已保存工作流」的来源信息（下载 / 上传）。"""
    if not isinstance(source, dict):
        return {}

    def text(key: str, limit: int) -> str:
        return trim_text(source.get(key), limit)

    origin = _ORIGIN_DOWNLOADED if source.get("origin") == _ORIGIN_DOWNLOADED else (
        _ORIGIN_UPLOADED if source.get("origin") == _ORIGIN_UPLOADED else ""
    )
    clean = {
        "origin": origin,
        "repo_id": text("repo_id", 200),
        "version": text("version", 40),
        "uploaded_at": text("uploaded_at", 40),
        "author": text("author", 80),
        "lineage_id": text("lineage_id", 200),
        "remote_name": text("remote_name", 120),
    }
    return {key: value for key, value in clean.items() if value}
