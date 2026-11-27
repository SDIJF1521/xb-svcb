"""工作流商城清单的领域规则单元测试（无 I/O、无网络、无 config 依赖）。"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from domain.workflow_manifest import (
    WORKFLOW_MANIFEST_MAGIC,
    WORKFLOW_MANIFEST_MAX_NODES,
    build_workflow_manifest,
    graph_from_manifest,
    is_workflow_manifest,
    normalize_pymss_requirements,
    normalize_workflow_source,
    parse_workflow_manifest,
    pymss_model_names,
    pymss_node_default_purpose,
    preview_graph,
    sanitize_graph,
    workflow_graph_fingerprint,
)


def _graph() -> dict:
    nodes = [
        {"id": "i", "type": "input", "x": 0, "y": 0, "params": {}},
        {
            "id": "s",
            "type": "separate",
            "x": 220,
            "y": 0,
            "params": {"engine": "pymss", "model": "model_a.ckpt", "device": "auto"},
        },
        {
            "id": "d",
            "type": "dereverb",
            "x": 220,
            "y": 180,
            "params": {"engine": "pymss", "model": "model_b.pth", "device": "auto"},
        },
        {
            "id": "c",
            "type": "convert",
            "x": 480,
            "y": 0,
            "params": {"model_id": "", "device": "auto"},
        },
        {"id": "m", "type": "mix", "x": 720, "y": 0, "params": {"enhanced": False}},
        {"id": "o", "type": "output", "x": 960, "y": 0, "params": {"file_template": "%filename%"}},
    ]
    edges = [
        {"id": "e1", "from": {"node": "i", "port": "audio"}, "to": {"node": "s", "port": "audio"}},
        {"id": "e2", "from": {"node": "s", "port": "vocals"}, "to": {"node": "d", "port": "audio"}},
        {"id": "e3", "from": {"node": "d", "port": "audio"}, "to": {"node": "c", "port": "audio"}},
        {"id": "e4", "from": {"node": "s", "port": "instrumental"}, "to": {"node": "m", "port": "instrumental"}},
        {"id": "e5", "from": {"node": "c", "port": "audio"}, "to": {"node": "m", "port": "vocals"}},
        {"id": "e6", "from": {"node": "m", "port": "audio"}, "to": {"node": "o", "port": "audio"}},
    ]
    return {"id": "", "name": "测试工作流", "updated_at": "", "nodes": nodes, "edges": edges}


def _manifest(**overrides) -> dict:
    data = {
        "magic": WORKFLOW_MANIFEST_MAGIC,
        "schema": 1,
        "name": "社区测试工作流",
        "description": "用于单元测试",
        "version": "v1.2.0",
        "tags": ["测试", "女声", "测试"],
        "graph": {"nodes": _graph()["nodes"], "edges": _graph()["edges"]},
        "pymss_models": [
            {
                "name": "model_a.ckpt",
                "purpose": "vocal_separation",
                "purpose_label": "人声分离",
            },
            {"name": "model_b.pth", "purpose": "dereverb"},
            {"name": "model_a.ckpt", "purpose": "dereverb"},
        ],
        "uploaded_by": "demo",
        "uploaded_at": "2026-11-20T10:00:00",
        "lineage_id": "demo/xb-cover-workflow-demo",
    }
    data.update(overrides)
    return data


def test_manifest_validation_and_normalization() -> None:
    assert is_workflow_manifest(_manifest())
    parsed = parse_workflow_manifest(_manifest())
    assert parsed is not None
    assert parsed["name"] == "社区测试工作流"
    assert parsed["version"] == "1.2.0"
    assert parsed["tags"] == ["测试", "女声"]
    assert [item["name"] for item in parsed["pymss_models"]] == ["model_a.ckpt", "model_b.pth"]

    assert not is_workflow_manifest({**_manifest(), "magic": "OTHER"})
    assert not is_workflow_manifest({**_manifest(), "name": "  "})
    assert parse_workflow_manifest({**_manifest(), "graph": {"nodes": [], "edges": []}}) is None


def test_graph_sanitizing_limits_and_fallbacks() -> None:
    graph = _graph()
    graph["nodes"][0]["params"] = None
    graph["nodes"][0]["x"] = "not-a-number"
    cleaned = sanitize_graph(graph)
    assert cleaned is not None
    assert cleaned["nodes"][0]["params"] == {}
    assert cleaned["nodes"][0]["x"] == 0

    # 重复 / 缺失的连线 ID 会被补成唯一值，避免画布按 key 复用导致连线错乱。
    duplicate_graph = _graph()
    duplicate_graph["edges"][0]["id"] = "same"
    duplicate_graph["edges"][1]["id"] = "same"
    duplicate_graph["edges"][2].pop("id", None)
    cleaned_edges = sanitize_graph(duplicate_graph)
    assert cleaned_edges is not None
    ids = [edge["id"] for edge in cleaned_edges["edges"]]
    assert len(ids) == len(set(ids))
    assert all(ids)

    # 未知节点类型会被丢弃；只剩非法节点时整张图不可用。
    unknown = {
        "nodes": [{"id": "x", "type": "nope"}],
        "edges": [],
    }
    assert sanitize_graph(unknown) is None

    too_many = {
        "nodes": [
            {"id": f"n{i}", "type": "input", "x": 0, "y": 0, "params": {}}
            for i in range(WORKFLOW_MANIFEST_MAX_NODES + 20)
        ],
        "edges": [],
    }
    assert sanitize_graph(too_many) is None


def test_build_manifest_and_preview() -> None:
    manifest = build_workflow_manifest(
        name="  新工作流  ",
        graph=_graph(),
        version="2.0.0",
        description=" 简介 ",
        tags="女声, 流行",
        pymss_models=[{"name": "model_a.ckpt", "purpose": "generic"}],
        uploaded_by="demo",
        uploaded_at="2026-11-20T10:00:00",
        lineage_id="demo/xb-cover-workflow-demo",
        app_name="XB-SVCB",
        marker="xb-svcb-cover-workflow",
    )
    assert manifest["magic"] == WORKFLOW_MANIFEST_MAGIC
    assert manifest["name"] == "新工作流"
    assert manifest["tags"] == ["女声", "流行"]
    assert manifest["node_count"] == 6
    assert manifest["pymss_models"][0]["purpose"] == ""  # 非受支持用途被收敛
    assert parse_workflow_manifest(manifest) is not None

    cleaned = graph_from_manifest(parse_workflow_manifest(manifest) or {})
    assert cleaned is not None
    preview = preview_graph(cleaned)
    assert preview["nodes"] and "params" not in preview["nodes"][0]

    try:
        build_workflow_manifest(
            name="坏工作流",
            graph={"nodes": [], "edges": []},
            version="1.0.0",
            app_name="XB-SVCB",
            marker="x",
        )
    except ValueError:
        pass
    else:  # pragma: no cover - 只用于明确失败语义
        raise AssertionError("空节点图应构造失败")


def test_pymss_dependency_extraction() -> None:
    nodes = _graph()["nodes"] + [
        {"id": "u", "type": "separate", "x": 0, "y": 0, "params": {"engine": "uvr", "model": "MDX"}},
        {"id": "s2", "type": "separate", "x": 0, "y": 0, "params": {"engine": "PYMSS", "model": "model_a.ckpt"}},
    ]
    assert pymss_model_names(nodes) == ["model_a.ckpt", "model_b.pth"]
    assert pymss_node_default_purpose(nodes) == {
        "model_a.ckpt": "vocal_separation",
        "model_b.pth": "dereverb",
    }
    normalized = normalize_pymss_requirements(
        [
            {"name": "a", "purpose": "bad", "size_bytes": "12"},
            {"name": "a", "purpose": "dereverb"},
            {"name": "", "purpose": "dereverb"},
        ]
    )
    assert normalized == [
        {
            "name": "a",
            "purpose": "",
            "purpose_label": "",
            "architecture": "",
            "category_label": "",
            "target_stem": "",
            "size_bytes": 12,
        }
    ]


def test_workflow_source_normalization() -> None:
    source = normalize_workflow_source(
        {
            "origin": "downloaded",
            "repo_id": " demo/xb-cover-workflow-demo ",
            "version": "1.0.0",
            "author": "demo",
            "unknown": "ignored",
        }
    )
    assert source["origin"] == "downloaded"
    assert source["repo_id"] == "demo/xb-cover-workflow-demo"
    assert "unknown" not in source
    assert normalize_workflow_source(None) == {}
    assert normalize_workflow_source({"origin": "weird"}) == {}


def test_workflow_graph_fingerprint_is_semantic() -> None:
    first = _graph()
    second = copy.deepcopy(first)
    # 拖动布局、改工作流名称、改连线 ID 都不应影响「同一工作流」判断。
    second["name"] = "本地改过名的工作流"
    second["nodes"][1]["x"] = 999
    second["nodes"][1]["y"] = 888
    for index, edge in enumerate(second["edges"]):
        edge["id"] = f"local-{index}"
    assert workflow_graph_fingerprint(first) == workflow_graph_fingerprint(second)

    # 改节点参数 / 连线则必须产生不同指纹。
    changed = copy.deepcopy(first)
    changed["nodes"][1]["params"]["model"] = "another.ckpt"
    assert workflow_graph_fingerprint(changed) != workflow_graph_fingerprint(first)

    # 非法 / 空图没有指纹。
    assert workflow_graph_fingerprint({"nodes": [], "edges": []}) is None
    assert workflow_graph_fingerprint(None) is None
