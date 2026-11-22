"""工作流商城的 ModelScope 适配器。

把「网络请求 / 子进程上传 / 暂存目录」等基础设施细节收敛在这里，实现
``application.ports.WorkflowHubGateway``。应用层不再直接 import httpx 或
subprocess，也不负责写暂存文件。

性能要点与模型站一致：

* 一个事件循环共用一个 ``httpx.AsyncClient``（keep-alive / TLS 复用）；
* 标记搜索、关键词搜索、自己的命名空间查询并发发出；
* 候选仓库清单并发读取（有界 + TTL 缓存），不再 N 个 RTT 串行等待；
* 搜索结果 / 令牌校验短 TTL 缓存，翻页与重复搜索几乎零延迟；
* 429 时全局退避，避免被服务端限流后越等越慢。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
from typing import Any, Callable

import config

from .http_async import (
    AsyncTokenBucket,
    TTLCache,
    backoff_seconds,
    gather_bounded,
    get_async_client,
)


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _safe_stage_name(repo_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", repo_id.strip("/"))[:120] or "workflow"


class WorkflowHubClient:
    """基于 ModelScope（魔搭社区）的工作流市场网关实现。"""

    def __init__(self) -> None:
        self._limiter = AsyncTokenBucket(
            config.MODELSCOPE_READ_QPS, config.MODELSCOPE_READ_BURST
        )
        self._raw_cache = TTLCache(config.MODELSCOPE_MANIFEST_TTL, max_entries=256)
        self._list_cache = TTLCache(config.MODELSCOPE_LIST_TTL, max_entries=128)
        self._negative_cache = TTLCache(
            config.MODELSCOPE_MANIFEST_NEGATIVE_TTL, max_entries=256
        )
        self._token_cache = TTLCache(config.MODELSCOPE_TOKEN_TTL, max_entries=8)
        self._search_cache = TTLCache(config.MODELSCOPE_SEARCH_TTL, max_entries=64)

    # ---- 能力检查 ----
    def upload_ready(self) -> bool:
        return config.modelhub_upload_ready()

    def prepare(self) -> None:
        """在事件循环线程里预创建共享 HTTP 客户端。"""
        try:
            get_async_client()
        except Exception:  # noqa: BLE001 - 预热失败不影响后续按需创建
            pass

    def invalidate_cache(self) -> None:
        self._raw_cache.clear()
        self._list_cache.clear()
        self._negative_cache.clear()
        self._token_cache.clear()
        self._search_cache.clear()

    # ---- HTTP 基础 ----
    def _headers(self, token: str | None, *, json_content: bool = False) -> dict[str, str]:
        headers = {"User-Agent": "XB-SVCB"}
        if json_content:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
            headers["Cookie"] = f"m_session_id={token}"
        return headers

    async def verify_token(self, token: str) -> dict[str, Any]:
        value = (token or "").strip()
        if not value:
            return {"ok": False, "error": "未填写 ModelScope 访问令牌"}
        cache_key = ("token", value)
        cached = self._token_cache.get(cache_key)
        if isinstance(cached, dict):
            return dict(cached)
        url = f"{config.MODELSCOPE_ENDPOINT}/api/v1/login"
        for attempt in range(2):
            await self._limiter.acquire()
            try:
                response = await get_async_client().post(
                    url,
                    json={"AccessToken": value},
                    headers=self._headers(None, json_content=True),
                    timeout=20.0,
                )
            except Exception as exc:  # noqa: BLE001
                if attempt == 0:
                    await asyncio.sleep(0.4)
                    continue
                return {"ok": False, "error": f"校验失败：{exc}"}
            if response.status_code == 429:
                self._limiter.penalize(backoff_seconds(response))
                if attempt == 0:
                    continue
                return {"ok": False, "error": "令牌校验被限流，请稍后重试"}
            try:
                data = response.json()
            except ValueError:
                return {"ok": False, "error": "令牌校验返回了非 JSON 响应"}
            payload = data.get("Data") if isinstance(data, dict) else None
            if not isinstance(payload, dict):
                message = (data or {}).get("Message") if isinstance(data, dict) else None
                return {"ok": False, "error": message or "令牌无效或网络异常"}
            username = _first(payload, "Username", "Name", "username", "name") or ""
            email = _first(payload, "Email", "email") or ""
            if not username:
                return {"ok": False, "error": "未能从令牌解析到用户名"}
            result = {"ok": True, "username": str(username), "email": str(email)}
            self._token_cache.set(cache_key, result)
            return dict(result)
        return {"ok": False, "error": "令牌校验失败"}

    async def _query_models(
        self, body: dict[str, Any], token: str
    ) -> tuple[list[Any], int | None]:
        cache_key = (
            config.MODELSCOPE_ENDPOINT,
            token,
            tuple(sorted(body.items())),
        )
        cached = self._list_cache.get(cache_key)
        if isinstance(cached, tuple):
            return cached
        url = f"{config.MODELSCOPE_ENDPOINT}/api/v1/models/"
        for attempt in range(2):
            await self._limiter.acquire()
            try:
                response = await get_async_client().put(
                    url,
                    json=body,
                    headers=self._headers(token, json_content=True),
                    timeout=25.0,
                )
            except Exception:  # noqa: BLE001
                if attempt == 0:
                    await asyncio.sleep(0.4)
                    continue
                return [], None
            if response.status_code == 429:
                self._limiter.penalize(backoff_seconds(response))
                if attempt == 0:
                    continue
                return [], None
            if response.status_code >= 500 and attempt == 0:
                self._limiter.penalize(1.0)
                continue
            try:
                data = response.json()
            except ValueError:
                return [], None
            payload = data.get("Data") if isinstance(data, dict) else None
            raw: Any = []
            total: int | None = None
            if isinstance(payload, dict):
                raw = _first(payload, "Models", "models", "Model", "List", "Data") or []
                total_raw = _first(payload, "TotalCount", "TotalNum", "Total", "Count")
                if total_raw is not None:
                    try:
                        value = int(total_raw)
                        total = value if value > 0 else None
                    except (TypeError, ValueError):
                        total = None
            elif isinstance(payload, list):
                raw = payload
            result = (raw if isinstance(raw, list) else []), total
            self._list_cache.set(cache_key, result)
            return result
        return [], None

    @staticmethod
    def _extract_repo_id(entry: dict[str, Any]) -> str | None:
        for key in ("Path", "ModelPath", "Id", "ModelId", "FullName"):
            value = entry.get(key)
            if isinstance(value, str) and "/" in value:
                return value.strip("/")
        name = _first(entry, "Name", "ModelName", "name")
        owner = _first(
            entry, "Path", "Owner", "Organization", "Namespace", "CreatedBy", "Creator"
        )
        if isinstance(owner, dict):
            owner = _first(owner, "Name", "name", "Login")
        if name and owner and "/" not in str(name):
            return f"{owner}/{name}"
        return None

    async def _scan_namespace(
        self, token: str, viewer: str, *, max_pages: int = 10
    ) -> list[dict[str, Any]]:
        """扫描自己的命名空间，返回所有仓库条目（最多 1000 个）。

        不能直接用 ``Path`` 查询返回的 TotalCount 当工作流总数：自己的命名空间里
        还有声音模型仓库，会把「我上传的」数量算多。这里先按仓库名筛出工作流前缀，
        再按页读取清单。
        """
        entries: list[dict[str, Any]] = []
        rows, total = await self._query_models(
            {"Path": viewer, "PageNumber": 1, "PageSize": 100}, token
        )
        entries.extend([row for row in rows if isinstance(row, dict)])
        if len(rows) < 100:
            return entries
        # 第一页满 100：按 total 计算剩余页并并发拉取，避免 10 页串行。
        page_count = (
            min(max_pages, max(1, (int(total) + 99) // 100))
            if total is not None
            else max_pages
        )
        if page_count <= 1:
            return entries

        async def fetch_page(page_index: int) -> list[dict[str, Any]]:
            page_rows, _page_total = await self._query_models(
                {"Path": viewer, "PageNumber": page_index, "PageSize": 100}, token
            )
            return [row for row in page_rows if isinstance(row, dict)]

        rest = await gather_bounded(
            range(2, page_count + 1), fetch_page, 4, default=[]
        )
        for page_entries in rest:
            if page_entries:
                entries.extend(page_entries)
        return entries

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
        """查询 ModelScope 并读取候选仓库清单；过滤 / 校验由用例层完成。"""
        page = max(1, page)
        page_size = max(1, min(48, page_size))
        keyword = (query or "").strip()
        prefix = config.WORKFLOWHUB_REPO_PREFIX

        cache_key = (token, keyword, page, page_size, viewer, mine_only)
        cached = self._search_cache.get(cache_key)
        if isinstance(cached, dict):
            return dict(cached)

        if mine_only:
            # 「我上传的」只统计工作流仓库：先扫描命名空间并按仓库名前缀过滤，
            # 避免把声音模型也算进分页总数（截图里 1 个工作流却显示 31 条）。
            own_entries = await self._scan_namespace(token, viewer)
            workflow_entries: list[dict[str, Any]] = []
            seen_own: set[str] = set()
            for entry in own_entries:
                repo_id = self._extract_repo_id(entry)
                if not repo_id or repo_id in seen_own:
                    continue
                seen_own.add(repo_id)
                if repo_id.split("/", 1)[-1].startswith(prefix):
                    workflow_entries.append(entry)
            total_hint = len(workflow_entries)
            start = (page - 1) * page_size
            page_entries = workflow_entries[start:start + page_size]
            manifests = await gather_bounded(
                page_entries,
                lambda entry: self._manifest_for(entry, token),
                config.MODELSCOPE_MANIFEST_CONCURRENCY,
            )
            candidates = []
            for item in manifests:
                if not item:
                    continue
                repo_id, manifest = item
                if repo_id and isinstance(manifest, dict):
                    candidates.append({"repo_id": repo_id, "manifest": manifest})
            result = {
                "ok": True,
                "candidates": candidates,
                "total": total_hint,
                "page": page,
                "page_size": page_size,
                "page_source_count": len(page_entries),
            }
            self._search_cache.set(cache_key, result)
            return dict(result)

        # 三个独立来源并发发出：标记前缀、自己的命名空间、关键词。
        sources: dict[str, Any] = {
            "marker": self._query_models(
                {"Name": prefix, "PageNumber": page, "PageSize": page_size}, token
            )
        }
        if page == 1 and viewer:
            sources["own"] = self._query_models(
                {"Path": viewer, "PageNumber": 1, "PageSize": 100}, token
            )
        if keyword:
            sources["keyword"] = self._query_models(
                {"Name": keyword, "PageNumber": page, "PageSize": page_size}, token
            )
        keys = list(sources)
        values = await asyncio.gather(*(sources[key] for key in keys))
        results = dict(zip(keys, values))
        marker, marker_total = results.get("marker") or ([], None)
        own, _own_total = results.get("own") or ([], None)
        keyword_raw, keyword_total = results.get("keyword") or ([], None)
        total_hint = marker_total if marker_total is not None else keyword_total
        page_source_count = len(marker)

        raw_entries: list[Any] = list(own) + list(marker) + list(keyword_raw)
        seen: set[str] = set()
        pending: list[tuple[str, dict[str, Any]]] = []
        for entry in raw_entries:
            if not isinstance(entry, dict):
                continue
            repo_id = self._extract_repo_id(entry)
            if not repo_id or repo_id in seen:
                continue
            seen.add(repo_id)
            if not repo_id.split("/", 1)[-1].startswith(prefix):
                continue
            pending.append((repo_id, entry))

        manifests = await gather_bounded(
            pending,
            lambda item: self._manifest_for_id(item[0], token),
            config.MODELSCOPE_MANIFEST_CONCURRENCY,
        )
        candidates = [
            {"repo_id": repo_id, "manifest": manifest}
            for (repo_id, _entry), manifest in zip(pending, manifests)
            if isinstance(manifest, dict)
        ]
        result = {
            "ok": True,
            "candidates": candidates,
            "total": total_hint,
            "page": page,
            "page_size": page_size,
            "page_source_count": page_source_count,
        }
        self._search_cache.set(cache_key, result)
        return dict(result)

    async def _manifest_for(
        self, entry: dict[str, Any], token: str
    ) -> tuple[str, dict[str, Any] | None]:
        repo_id = self._extract_repo_id(entry)
        if not repo_id:
            return "", None
        return repo_id, await self.fetch_manifest(repo_id, token)

    async def _manifest_for_id(
        self, repo_id: str, token: str
    ) -> dict[str, Any] | None:
        return await self.fetch_manifest(repo_id, token)

    async def _get_raw(
        self, repo_id: str, file_path: str, token: str
    ) -> bytes | None:
        repo_id = (repo_id or "").strip().strip("/")
        file_path = str(file_path or "").strip()
        if "/" not in repo_id or not file_path:
            return None
        cache_key = (config.MODELSCOPE_ENDPOINT, repo_id, file_path)
        cached = self._raw_cache.get(cache_key)
        if isinstance(cached, (bytes, bytearray)):
            return bytes(cached)
        if self._negative_cache.contains(cache_key):
            return None
        url = f"{config.MODELSCOPE_ENDPOINT}/api/v1/models/{repo_id}/repo"
        params = {"FilePath": file_path, "Revision": "master"}
        for attempt in range(2):
            await self._limiter.acquire()
            try:
                response = await get_async_client().get(
                    url, params=params, headers=self._headers(token), timeout=30.0
                )
            except Exception:  # noqa: BLE001
                if attempt == 0:
                    await asyncio.sleep(0.4)
                    continue
                return None
            if response.status_code == 429:
                self._limiter.penalize(backoff_seconds(response))
                if attempt == 0:
                    continue
                return None
            if response.status_code >= 500 and attempt == 0:
                self._limiter.penalize(1.0)
                continue
            if response.status_code != 200:
                self._negative_cache.set(cache_key, True, ttl=15.0)
                return None
            content = response.content
            if len(content) > config.WORKFLOWHUB_MAX_MANIFEST_BYTES:
                return None
            if len(content) <= config.MODELSCOPE_RAW_CACHE_MAX_BYTES:
                self._raw_cache.set(cache_key, content)
            return content
        return None

    async def fetch_manifest(
        self, repo_id: str, token: str
    ) -> dict[str, Any] | None:
        repo_id = (repo_id or "").strip().strip("/")
        if "/" not in repo_id:
            return None
        raw = await self._get_raw(repo_id, config.WORKFLOWHUB_MANIFEST, token)
        if not raw:
            return None
        try:
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except (ValueError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    # ---- 上传 ----
    def upload_manifest(
        self,
        *,
        token: str,
        repo_id: str,
        manifest: dict[str, Any],
        readme: str,
        display_name: str,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> dict[str, Any]:
        if not self.upload_ready():
            return {
                "ok": False,
                "error": "上传组件未安装（.venv-hub）。请在「搭建/修复运行环境」中安装模型上传组件后重试。",
            }
        stage = config.WORKFLOWHUB_DIR / "upload" / _safe_stage_name(repo_id)
        try:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)
            stage.mkdir(parents=True, exist_ok=True)
            (stage / config.WORKFLOWHUB_MANIFEST).write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (stage / "README.md").write_text(readme, encoding="utf-8")
        except OSError as exc:
            shutil.rmtree(stage, ignore_errors=True)
            return {"ok": False, "error": f"准备上传文件失败：{exc}"}
        try:
            result = self._run_upload_worker(
                token, repo_id, str(stage), display_name, on_progress
            )
            if result.get("ok"):
                self.invalidate_cache()
            return result
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def _run_upload_worker(
        self,
        token: str,
        repo_id: str,
        folder: str,
        display_name: str,
        on_progress: Callable[[int, int, str], None] | None,
    ) -> dict[str, Any]:
        if not config.HUB_PYTHON or not config.HUB_PYTHON.exists():
            return {"ok": False, "error": "未找到上传组件解释器（.venv-hub）"}
        cmd = [
            str(config.HUB_PYTHON),
            str(config.HUB_WORKER),
            "--action",
            "upload",
            "--token",
            token,
            "--model-id",
            repo_id,
            "--dir",
            folder,
            "--chinese-name",
            display_name,
            "--visibility",
            "5",
        ]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                **config.subprocess_no_window(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "error": f"上传子进程启动失败：{exc}"}

        result: dict[str, Any] | None = None
        tail: list[str] = []
        assert process.stdout is not None
        for raw in process.stdout:
            line = raw.strip()
            if not line:
                continue
            tail.append(line)
            tail[:] = tail[-5:]
            if line.startswith("HUB_PROGRESS "):
                parts = line[len("HUB_PROGRESS "):].split(" ", 2)
                try:
                    done = int(parts[0])
                    total = int(parts[1])
                except (ValueError, IndexError):
                    continue
                name = parts[2] if len(parts) > 2 else ""
                if on_progress is not None:
                    on_progress(done, total, name)
            elif line.startswith("HUB_OK "):
                try:
                    payload = json.loads(line[len("HUB_OK "):])
                except ValueError:
                    payload = {}
                result = {
                    "ok": True,
                    "url": payload.get("url", ""),
                    "repo_id": payload.get("model_id", repo_id),
                }
            elif line.startswith("HUB_ERR "):
                result = {"ok": False, "error": line[len("HUB_ERR "):].strip()}
        process.wait()
        if result is not None:
            return result
        return {"ok": False, "error": " | ".join(tail[-3:]) or "上传失败（无输出）"}
