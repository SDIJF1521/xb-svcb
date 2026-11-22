"""模型站 / 工作流商城的并发与缓存回归测试。

这些用例不访问真实 ModelScope：网关用带延迟的 fake 替代，下载用本机
``ThreadingHTTPServer`` 提供 Range 响应，因此可稳定验证：

* 搜索时多个仓库清单是并发读取的（而不是 N 个 RTT 串行）；
* 重复搜索 / 翻页命中 TTL 缓存；
* 工作流依赖的多个 PyMSS 模型并发安装；
* 大文件分片并行下载完成后内容与源文件一致。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

import config

APP_DIR = Path(__file__).resolve().parents[1]
import sys

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from application.model_hub_service import ModelHubService
from application.workflow_hub_service import WorkflowHubService
from infrastructure.http_async import _safe_proxy_environ, close_async_clients
from infrastructure.model_hub_client import ModelHubClient
from infrastructure.storage import SettingsStore
from infrastructure.workflow_hub_client import WorkflowHubClient


def test_bracketed_ipv6_no_proxy_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = "localhost,127.0.0.1,[::1]"
    monkeypatch.setenv("NO_PROXY", raw)
    monkeypatch.setenv("no_proxy", raw)
    with _safe_proxy_environ():
        assert "[" not in os.environ["no_proxy"]
        assert "::1" in os.environ["no_proxy"]
    # 退出上下文后必须原样恢复，不能污染应用其它模块。
    assert os.environ["no_proxy"] == raw


class _Models:
    def __init__(self, items: list[dict[str, Any]] | None = None) -> None:
        self._items = list(items or [])

    def list(self) -> list[dict[str, Any]]:
        return list(self._items)

    def get(self, model_id: str) -> dict[str, Any] | None:
        return next(
            (item for item in self._items if item.get("id") == model_id), None
        )

    def import_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"id": "imported", **payload}


def _manifest(name: str = "demo", framework: str = "rvc") -> bytes:
    return json.dumps(
        {
            "magic": config.MODELHUB_MAGIC,
            "name": name,
            "framework": framework,
            "files": {
                "main_model": "voice.pth",
                **({"main_config": "config.yaml"} if framework != "rvc" else {}),
            },
            "version": "1.0.0",
            "uploaded_at": "2026-11-20T10:00:00",
        },
        ensure_ascii=False,
    ).encode("utf-8")


class _SlowModelGateway:
    def __init__(self, count: int = 8) -> None:
        self.count = count
        self.raw_calls = 0
        self.query_calls = 0

    async def verify_token(self, token: str) -> dict[str, Any]:
        return {"ok": True, "username": "demo", "email": ""}

    async def query_models(
        self, token: str, body: dict[str, Any]
    ) -> tuple[list[Any], int | None]:
        self.query_calls += 1
        if "Path" in body:
            return [], None
        return [
            {"Path": "demo", "Name": f"xb-svcb-model-{index}"}
            for index in range(self.count)
        ], None

    async def fetch_raw(
        self, token: str, repo_id: str, file_path: str
    ) -> bytes | None:
        self.raw_calls += 1
        await asyncio.sleep(0.15)
        return _manifest(repo_id)

    async def list_files(self, token: str, repo_id: str) -> dict[str, int]:
        return {}

    async def file_digests(
        self, token: str, repo_id: str
    ) -> dict[str, tuple[int, str]]:
        return {}

    async def download_to(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def invalidate_cache(self) -> None:
        pass

    def invalidate_token_cache(self) -> None:
        pass


def _model_service(
    gateway: _SlowModelGateway,
    root: Path,
    models: _Models | None = None,
) -> ModelHubService:
    service = object.__new__(ModelHubService)
    service._settings = SettingsStore(root / "settings.json")
    service._models = models or _Models()
    service._gateway = gateway
    return service


def test_model_search_reads_manifests_concurrently_and_caches(
    tmp_path: Path,
) -> None:
    gateway = _SlowModelGateway(count=8)
    service = _model_service(gateway, tmp_path)

    started = time.perf_counter()
    result = asyncio.run(service._search("", 1, None, 8))
    first_elapsed = time.perf_counter() - started

    assert result["ok"] is True
    assert len(result["items"]) == 8
    assert gateway.raw_calls == 8
    # 串行 8 * 0.15s = 1.2s；并发应明显低于这个值。
    assert first_elapsed < 0.9, first_elapsed

    started = time.perf_counter()
    again = asyncio.run(service._search("", 1, None, 8))
    cached_elapsed = time.perf_counter() - started

    assert again == result
    assert gateway.raw_calls == 8  # 命中缓存，不再发请求
    assert cached_elapsed < 0.2, cached_elapsed


def test_model_search_returns_total_for_pagination(tmp_path: Path) -> None:
    class _TotalGateway(_SlowModelGateway):
        async def query_models(
            self, token: str, body: dict[str, Any]
        ) -> tuple[list[Any], int | None]:
            page_number = int(body.get("PageNumber") or 1)
            size = int(body.get("PageSize") or 12)
            start = (page_number - 1) * size
            rows = [
                {"Path": "demo", "Name": f"xb-svcb-model-{index}"}
                for index in range(start, min(36, start + size))
            ]
            return rows, 36

    gateway = _TotalGateway()
    service = _model_service(gateway, tmp_path)
    result = asyncio.run(service._search("", 1, None, 5))

    assert result["ok"] is True
    assert result["total"] == 36
    assert result["has_more"] is True
    assert result["page_size"] == 5
    assert len(result["items"]) == 5


def test_model_search_matches_framework_keyword(tmp_path: Path) -> None:
    class _DdspGateway(_SlowModelGateway):
        async def fetch_raw(
            self, token: str, repo_id: str, file_path: str
        ) -> bytes | None:
            return _manifest("芙芙", "ddsp-svc")

    service = _model_service(_DdspGateway(count=1), tmp_path)

    by_keyword = asyncio.run(service._search("ddsp", 1, None, 12))
    assert len(by_keyword["items"]) == 1
    assert by_keyword["items"][0]["framework"] == "ddsp-svc"

    by_suffix = asyncio.run(service._search("ddsp模型", 1, None, 12))
    assert len(by_suffix["items"]) == 1
    assert by_suffix["items"][0]["framework"] == "ddsp-svc"

    by_filter = asyncio.run(service._search("", 1, "ddsp-svc", 12))
    assert len(by_filter["items"]) == 1
    assert by_filter["items"][0]["name"] == "芙芙"


def test_model_search_matches_local_model_by_sha256(tmp_path: Path) -> None:
    payload = b"local-ddsp-model-bytes" * 64
    local_file = tmp_path / "model.pt"
    local_file.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    class _HashGateway(_SlowModelGateway):
        async def fetch_raw(
            self, token: str, repo_id: str, file_path: str
        ) -> bytes | None:
            return _manifest("芙芙", "ddsp-svc")

        async def file_digests(
            self, token: str, repo_id: str
        ) -> dict[str, tuple[int, str]]:
            return {"voice.pth": (len(payload), digest)}

    local_model = {
        "id": "mdl_local",
        "name": "我本地的芙芙",
        "framework": "ddsp-svc",
        "main_model": {"name": "model.pt", "path": str(local_file)},
        "imported_at": "2026-11-01",
        "metadata": {},
    }
    service = _model_service(
        _HashGateway(count=1), tmp_path, models=_Models([local_model])
    )

    with mock.patch.object(config, "MODELHUB_DIR", tmp_path / "modelhub"):
        result = asyncio.run(service._search("ddsp", 1, None, 12))

    assert len(result["items"]) == 1
    update = result["items"][0]["update"]
    assert update["installed"] is True
    assert update["installed_by_hash"] is True
    assert update["model_id"] == "mdl_local"
    assert update["model_name"] == "我本地的芙芙"
    assert update["available"] is False


def test_hash_match_does_not_cross_source_repo(tmp_path: Path) -> None:
    payload = b"shared-hash-model" * 32
    local_file = tmp_path / "shared.pth"
    local_file.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    class _HashGateway(_SlowModelGateway):
        async def fetch_raw(
            self, token: str, repo_id: str, file_path: str
        ) -> bytes | None:
            return _manifest("目标模型", "rvc")

        async def file_digests(
            self, token: str, repo_id: str
        ) -> dict[str, tuple[int, str]]:
            return {"voice.pth": (len(payload), digest)}

    local_model = {
        "id": "mdl_other",
        "name": "另一个仓库的模型",
        "framework": "rvc",
        "main_model": {"name": "shared.pth", "path": str(local_file)},
        "metadata": {"source_repo_id": "other/xb-svcb-other"},
    }
    service = _model_service(
        _HashGateway(count=1), tmp_path, models=_Models([local_model])
    )
    result = asyncio.run(service._search("", 1, None, 12))

    # 内容相同但已绑定其它仓库，不能顶替当前仓库，否则删除其中一个后仍显示已安装。
    assert result["items"][0]["update"]["installed"] is False


def test_model_search_finds_match_beyond_first_page(tmp_path: Path) -> None:
    class _LateDdspGateway(_SlowModelGateway):
        async def query_models(
            self, token: str, body: dict[str, Any]
        ) -> tuple[list[Any], int | None]:
            rows = [
                {"Path": "demo", "Name": f"xb-svcb-model-{index}"}
                for index in range(25)
            ]
            return rows, len(rows)

        async def fetch_raw(
            self, token: str, repo_id: str, file_path: str
        ) -> bytes | None:
            if repo_id.endswith("24"):
                return _manifest("芙芙", "ddsp-svc")
            return _manifest("普通模型", "rvc")

    service = _model_service(_LateDdspGateway(), tmp_path)
    result = asyncio.run(service._search("ddsp", 1, None, 12))

    # 第 25 个候选才是 DDSP 模型：筛选搜索必须扫描全部候选，不能只看第 1 页。
    assert result["total"] == 1
    assert result["has_more"] is False
    assert len(result["items"]) == 1
    assert result["items"][0]["framework"] == "ddsp-svc"


class _SlowWorkflowClient(WorkflowHubClient):
    def __init__(self, count: int = 8) -> None:
        super().__init__()
        self.count = count
        self.query_calls = 0
        self.manifest_calls = 0

    async def _query_models(
        self, body: dict[str, Any], token: str
    ) -> tuple[list[Any], int | None]:
        self.query_calls += 1
        await asyncio.sleep(0.1)
        if body.get("Path"):
            return [], 0
        return [
            {"Path": "demo", "Name": f"xb-cover-workflow-demo-{index}"}
            for index in range(self.count)
        ], self.count

    async def fetch_manifest(
        self, repo_id: str, token: str
    ) -> dict[str, Any] | None:
        self.manifest_calls += 1
        await asyncio.sleep(0.12)
        return {"name": repo_id, "graph": {"nodes": [], "edges": []}}


def test_workflow_search_reads_manifests_concurrently_and_caches() -> None:
    client = _SlowWorkflowClient(count=8)

    async def run() -> dict[str, Any]:
        return await client.search(
            token="",
            query="",
            page=1,
            page_size=8,
            viewer="",
            mine_only=False,
        )

    started = time.perf_counter()
    result = asyncio.run(run())
    first_elapsed = time.perf_counter() - started
    assert result["ok"] is True
    assert len(result["candidates"]) == 8
    assert client.manifest_calls == 8
    # 串行：0.1s 查询 + 8 * 0.12s 清单 ≈ 1.06s；并发应更低。
    assert first_elapsed < 0.7, first_elapsed

    started = time.perf_counter()
    again = asyncio.run(run())
    assert again == result
    assert client.manifest_calls == 8
    assert time.perf_counter() - started < 0.1


class _SlowPymss:
    def __init__(self) -> None:
        self.started_at: dict[str, float] = {}
        self.started: list[str] = []
        self.finished: dict[str, float] = {}

    def downloaded_model_stems(self) -> set[str]:
        return set()

    def start_download_model(self, model: str, purpose: str = "") -> dict[str, Any]:
        self.started.append(model)
        self.started_at[model] = time.monotonic()
        return {"ok": True, "key": f"pymss:{model}"}

    def download_progress(self, key: str = "") -> dict[str, Any]:
        name = key.split(":", 1)[-1]
        elapsed = time.monotonic() - self.started_at.get(name, 0.0)
        if elapsed < 0.2:
            return {"status": "running", "pct": 40, "message": "下载中", "error": None}
        self.finished[name] = time.monotonic()
        return {"status": "done", "pct": 100, "message": "完成", "error": None}


def test_workflow_syncs_pymss_models_concurrently() -> None:
    service = object.__new__(WorkflowHubService)
    service._pymss = _SlowPymss()
    service._progress = {}
    service._progress_lock = threading.Lock()
    requirements = [
        {"name": f"model_{index}.ckpt", "purpose": "vocal_separation", "size_bytes": 100}
        for index in range(3)
    ]
    with mock.patch.object(config, "WORKFLOWHUB_PYMSS_POLL_SECONDS", 0.05):
        started = time.perf_counter()
        result = asyncio.run(
            service._sync_pymss_models("wfdl:demo", requirements, set(), 20.0, 96.0)
        )
        elapsed = time.perf_counter() - started

    assert sorted(result["downloaded"]) == [
        "model_0.ckpt",
        "model_1.ckpt",
        "model_2.ckpt",
    ]
    assert result["failed"] == []
    # 串行至少 3 * 0.2s = 0.6s；并发应在 ~0.2s 附近完成。
    assert elapsed < 0.5, elapsed
    progress = service.get_progress("wfdl:demo")
    assert progress["phase"] == "pymss"
    assert progress["done"] == 3


class _RangeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    payload = b""

    def do_GET(self) -> None:  # noqa: N802 - http.server 约定
        data = self.payload
        header = self.headers.get("Range") or ""
        if header.startswith("bytes="):
            raw = header[len("bytes="):]
            start_text, _, end_text = raw.partition("-")
            start = int(start_text or 0)
            end = int(end_text) if end_text else len(data) - 1
            end = min(end, len(data) - 1)
            body = data[start:end + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
        else:
            body = data
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: Any) -> None:
        return


def test_model_download_uses_parallel_ranges(tmp_path: Path) -> None:
    size = 3 * 1024 * 1024
    payload = bytes(range(256)) * (size // 256)
    _RangeHandler.payload = payload
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RangeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    dst = tmp_path / "voice.pth"
    chunks: list[int] = []

    try:
        with (
            mock.patch.object(config, "MODELSCOPE_ENDPOINT", endpoint),
            mock.patch.object(config, "MODELHUB_DOWNLOAD_CONNECTIONS", 4),
            mock.patch.object(config, "MODELHUB_DOWNLOAD_CHUNK_BYTES", 256 * 1024),
            mock.patch.object(config, "MODELHUB_DOWNLOAD_PARALLEL_MIN_BYTES", 1),
        ):
            client = ModelHubClient()
            ok = asyncio.run(
                client.download_to(
                    "",
                    "owner/repo",
                    "voice.pth",
                    dst,
                    chunks.append,
                    expected_size=len(payload),
                )
            )
    finally:
        server.shutdown()
        server.server_close()
        close_async_clients()

    assert ok is True
    assert dst.read_bytes() == payload
    assert sum(chunks) == len(payload)
    assert not dst.with_name(dst.name + ".part").exists()
    assert not dst.with_name(dst.name + ".part.json").exists()
