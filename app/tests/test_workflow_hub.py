"""工作流商城用例编排测试：分页搜索、下载入库、PyMSS 同步与上传清单。

网络 / 子进程由假网关替代，文件目录使用工作区临时目录，
因此这些用例不依赖 ModelScope、不下载真实模型。
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any
from unittest import mock

import config

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from application.work_service import WorkService
from application.workflow_hub_service import WorkflowHubService
from domain.workflow_manifest import WORKFLOW_MANIFEST_MAGIC, parse_workflow_manifest
from infrastructure.storage import ListRepository, SettingsStore
from infrastructure.workflow_hub_client import WorkflowHubClient

REPO_ID = "demo/xb-cover-workflow-demo-abc123"


def _graph() -> dict[str, Any]:
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


def _manifest(**overrides: Any) -> dict[str, Any]:
    data = {
        "magic": WORKFLOW_MANIFEST_MAGIC,
        "schema": 1,
        "name": "社区测试工作流",
        "description": "用于单元测试",
        "version": "1.2.0",
        "tags": ["测试", "女声"],
        "graph": {"nodes": _graph()["nodes"], "edges": _graph()["edges"]},
        "pymss_models": [
            {
                "name": "model_a.ckpt",
                "purpose": "vocal_separation",
                "purpose_label": "人声分离",
            },
            {
                "name": "model_b.pth",
                "purpose": "dereverb",
                "purpose_label": "去混响 / 人声净化",
            },
        ],
        "uploaded_by": "demo",
        "uploaded_at": "2026-11-20T10:00:00",
        "lineage_id": REPO_ID,
    }
    data.update(overrides)
    return data


class _FakePymss:
    def __init__(self, catalog: list[dict[str, Any]] | None = None) -> None:
        self.catalog = catalog or []
        self.started: list[tuple[str, str]] = []
        self.status = "done"

    def list_models(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self.catalog)

    def downloaded_model_stems(self) -> set[str]:
        return set(config.pymss_downloaded_model_stems())

    def start_download_model(self, model: str, purpose: str = "") -> dict[str, Any]:
        self.started.append((model, purpose))
        return {"ok": True, "key": f"pymss:{model}"}

    def download_progress(self, key: str = "") -> dict[str, Any]:
        return {
            "key": key,
            "status": self.status,
            "pct": 100 if self.status == "done" else 40,
            "message": "完成" if self.status == "done" else "下载中",
            "error": None if self.status == "done" else "网络错误",
        }


class _FakeGateway:
    def __init__(self, manifest: dict[str, Any], *, total: int = 1) -> None:
        self.manifest = manifest
        self.total = total
        self.uploaded: dict[str, Any] | None = None

    def upload_ready(self) -> bool:
        return True

    async def verify_token(self, token: str) -> dict[str, Any]:
        return {"ok": True, "username": "demo", "email": "demo@example.com"}

    async def search(
        self,
        *,
        token: str,
        query: str,
        page: int,
        page_size: int,
        viewer: str,
        mine_only: bool,
    ) -> dict[str, Any]:
        start = (page - 1) * page_size
        count = max(0, min(page_size, self.total - start))
        candidates = [
            {
                "repo_id": f"demo/xb-cover-workflow-demo-{index}",
                "manifest": self.manifest,
            }
            for index in range(start, start + count)
        ]
        return {
            "ok": True,
            "candidates": candidates,
            "total": self.total,
            "page": page,
            "page_size": page_size,
            "page_source_count": count,
        }

    async def fetch_manifest(self, repo_id: str, token: str) -> dict[str, Any] | None:
        return self.manifest

    def upload_manifest(
        self,
        *,
        token: str,
        repo_id: str,
        manifest: dict[str, Any],
        readme: str,
        display_name: str,
        on_progress: Any = None,
    ) -> dict[str, Any]:
        self.uploaded = {
            "token": token,
            "repo_id": repo_id,
            "manifest": manifest,
            "readme": readme,
            "display_name": display_name,
        }
        if on_progress is not None:
            on_progress(1, 2, "manifest")
            on_progress(2, 2, "README")
        return {"ok": True, "repo_id": repo_id, "url": "#"}


def _tmp_root() -> Path:
    return Path(__file__).resolve().parent / "_tmp_workflow_hub" / uuid.uuid4().hex


class _Env:
    def __init__(self, total: int = 1) -> None:
        self.root = _tmp_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings = SettingsStore(self.root / "settings.json")
        self.works = WorkService(
            ListRepository(self.root / "works.json"),
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            self.settings,
            files=object(),  # type: ignore[arg-type]
        )
        self.pymss = _FakePymss(
            [
                {
                    "name": "model_a.ckpt",
                    "purpose": "vocal_separation",
                    "purpose_label": "人声分离",
                    "architecture": "bs_roformer",
                    "category_label": "人声 / 人声提取",
                    "size_bytes": 1024,
                }
            ]
        )
        self.gateway = _FakeGateway(_manifest(), total=total)
        self.hub = WorkflowHubService(
            self.settings, self.works, self.pymss, self.gateway  # type: ignore[arg-type]
        )

    def close(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def test_pymss_requirements_from_graph_dedupe_and_metadata() -> None:
    env = _Env()
    try:
        nodes = _graph()["nodes"] + [
            {"id": "u", "type": "separate", "x": 0, "y": 0, "params": {"engine": "uvr", "model": "MDX-Net"}},
            {"id": "s3", "type": "separate", "x": 0, "y": 0, "params": {"engine": "PYMSS", "model": "model_a.ckpt"}},
        ]
        requirements = env.hub._pymss_requirements_for_manifest(nodes)
        assert [item["name"] for item in requirements] == ["model_a.ckpt", "model_b.pth"]
        first = requirements[0]
        assert first["architecture"] == "bs_roformer"
        assert first["size_bytes"] == 1024
        assert first["purpose"] == "vocal_separation"
        assert requirements[1]["purpose"] == "dereverb"
    finally:
        env.close()


def test_download_saves_workflow_and_syncs_missing_pymss() -> None:
    env = _Env()
    pymss_dir = env.root / "pymss"
    pymss_dir.mkdir()
    (pymss_dir / "model_b.pth").write_bytes(b"stub")
    try:
        with mock.patch.object(config, "PYMSS_MODEL_DIR", pymss_dir):
            result = asyncio.run(env.hub._download(REPO_ID))
        assert result["ok"], result
        assert result["workflow"]["name"] == "社区测试工作流"
        workflows = env.works.list_workflows()
        assert len(workflows) == 1
        assert workflows[0]["source"]["repo_id"] == REPO_ID
        assert workflows[0]["source"]["origin"] == "downloaded"
        assert len(workflows[0]["nodes"]) == 6
        # model_b 已存在 → 只下载 model_a，并按清单里的 purpose 传递。
        assert env.pymss.started == [("model_a.ckpt", "vocal_separation")]
        assert result["pymss_downloaded"] == ["model_a.ckpt"]
        assert env.hub.get_progress(f"wfdl:{REPO_ID}")["phase"] == "done"
    finally:
        env.close()


def test_download_twice_updates_same_local_workflow() -> None:
    env = _Env()
    pymss_dir = env.root / "pymss"
    pymss_dir.mkdir()
    try:
        with mock.patch.object(config, "PYMSS_MODEL_DIR", pymss_dir):
            first = asyncio.run(env.hub._download(REPO_ID))
            second = asyncio.run(env.hub._download(REPO_ID))
        assert first["ok"] and second["ok"]
        workflows = env.works.list_workflows()
        assert len(workflows) == 1
        assert workflows[0]["id"] == first["workflow"]["id"]
        assert workflows[0]["source"]["version"] == "1.2.0"
    finally:
        env.close()


def test_search_uses_page_number_and_returns_total() -> None:
    env = _Env(total=25)
    try:
        first = asyncio.run(env.hub._search("", 1, 10))
        assert first["ok"] is True
        assert len(first["items"]) == 10
        assert first["total"] == 25
        assert first["has_more"] is True
        last = asyncio.run(env.hub._search("", 3, 10))
        assert len(last["items"]) == 5
        assert last["has_more"] is False
        matched = asyncio.run(env.hub._search("测试", 1, 10))
        assert matched["ok"] is True
        assert len(matched["items"]) == 10
        # 未配置令牌时「我上传的」返回空列表而不是报错。
        mine = asyncio.run(env.hub._search("", 1, 10, mine_only=True))
        assert mine["ok"] is True and mine["items"] == [] and mine["total"] == 0
    finally:
        env.close()


def test_upload_builds_manifest_and_marks_shared() -> None:
    env = _Env()
    try:
        workflow = env.works.save_workflow("测试工作流", _graph())
        result = asyncio.run(
            env.hub._upload(
                workflow["id"],
                {
                    "name": "社区版工作流",
                    "version": "2.0.0",
                    "description": "适合流行",
                    "tags": ["女声", "流行"],
                },
            )
        )
        assert result["ok"], result
        assert env.gateway.uploaded is not None
        manifest = env.gateway.uploaded["manifest"]
        assert manifest["magic"] == WORKFLOW_MANIFEST_MAGIC
        assert manifest["name"] == "社区版工作流"
        assert manifest["version"] == "2.0.0"
        assert manifest["node_count"] == 6
        assert [item["name"] for item in manifest["pymss_models"]] == [
            "model_a.ckpt",
            "model_b.pth",
        ]
        assert "工作流商城" in env.gateway.uploaded["readme"]
        updated = env.works.get_workflow(workflow["id"])
        assert updated is not None
        assert updated["source"]["origin"] == "uploaded"
        assert updated["source"]["repo_id"].startswith("demo/xb-cover-workflow-")
        assert env.hub.get_progress(f"wful:{workflow['id']}")["phase"] == "done"
    finally:
        env.close()


class _MineScanClient(WorkflowHubClient):
    """模拟自己的命名空间：31 个仓库里只有 1 个工作流，其余都是声音模型。"""

    async def _query_models(self, body: dict[str, Any], token: str):  # type: ignore[override]
        if body.get("Path"):
            rows = [{"Path": "demo", "Name": "xb-cover-workflow-mine-demo"}]
            rows += [
                {"Path": "demo", "Name": f"xb-svcb-voice-model-{index}"}
                for index in range(30)
            ]
            return rows, len(rows)
        return [], None

    async def fetch_manifest(self, repo_id: str, token: str) -> dict[str, Any] | None:
        return _manifest(name="我的工作流")


def test_mine_only_counts_workflows_not_voice_models() -> None:
    client = _MineScanClient()
    result = asyncio.run(
        client.search(
            token="demo-token",
            query="",
            page=1,
            page_size=12,
            viewer="demo",
            mine_only=True,
        )
    )
    assert result["ok"] is True
    assert result["total"] == 1
    assert result["page_source_count"] == 1
    assert [item["repo_id"] for item in result["candidates"]] == [
        "demo/xb-cover-workflow-mine-demo"
    ]


def test_work_service_respects_renamed_workflow_on_redownload() -> None:
    env = _Env()
    try:
        source = {
            "origin": "downloaded",
            "repo_id": REPO_ID,
            "version": "1.0.0",
            "remote_name": "原名工作流",
        }
        saved = env.works.save_imported_workflow("原名工作流", _graph(), source)
        assert saved["name"] == "原名工作流"
        settings_data = env.works.list_workflows()
        settings_data[0]["name"] = "我的改名"
        env.settings.set("cover_workflows", settings_data)
        updated = env.works.save_imported_workflow(
            "作者的新名称",
            _graph(),
            {**source, "version": "1.1.0", "remote_name": "作者的新名称"},
        )
        assert updated["name"] == "我的改名"
        assert updated["source"]["version"] == "1.1.0"
        assert len(env.works.list_workflows()) == 1
    finally:
        env.close()


def test_manifest_item_preview_is_compact() -> None:
    env = _Env()
    try:
        item = env.hub._build_item(
            REPO_ID,
            parse_workflow_manifest(_manifest()) or {},
            detail=False,
            source_map={},
            stems=set(),
        )
        assert item is not None
        assert item["node_count"] == 6
        assert "graph" not in item
        assert "params" not in item["preview_graph"]["nodes"][0]
        assert json.dumps(item, ensure_ascii=False)
    finally:
        env.close()
