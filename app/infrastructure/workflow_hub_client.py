"""工作流商城的 ModelScope 适配器。

把「网络请求 / 子进程上传 / 暂存目录」等基础设施细节收敛在这里，实现
``application.ports.WorkflowHubGateway``。应用层不再直接 import httpx 或
subprocess，也不负责写暂存文件。
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


class _AsyncRateLimiter:
    """异步最小间隔限流器：保证每秒不超过 ``rate_per_sec`` 次请求。"""

    def __init__(self, rate_per_sec: float) -> None:
        self._min_interval = 1.0 / max(rate_per_sec, 1)
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            loop = asyncio.get_event_loop()
            delay = self._last + self._min_interval - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            self._last = loop.time()


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
        self._limiter = _AsyncRateLimiter(config.MODELSCOPE_QPS)

    # ---- 能力检查 ----
    def upload_ready(self) -> bool:
        return config.modelhub_upload_ready()

    # ---- HTTP 基础 ----
    def _headers(self, token: str | None) -> dict[str, str]:
        headers = {"User-Agent": "XB-SVCB", "Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
            headers["Cookie"] = f"m_session_id={token}"
        return headers

    async def verify_token(self, token: str) -> dict[str, Any]:
        try:
            import httpx
        except ImportError:
            return {"ok": False, "error": "缺少 httpx 依赖，请重新安装运行环境"}
        value = (token or "").strip()
        if not value:
            return {"ok": False, "error": "未填写 ModelScope 访问令牌"}
        url = f"{config.MODELSCOPE_ENDPOINT}/api/v1/login"
        await self._limiter.wait()
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                response = await client.post(url, json={"AccessToken": value})
                data = response.json()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"校验失败：{exc}"}
        payload = data.get("Data") if isinstance(data, dict) else None
        if not isinstance(payload, dict):
            message = (data or {}).get("Message") if isinstance(data, dict) else None
            return {"ok": False, "error": message or "令牌无效或网络异常"}
        username = _first(payload, "Username", "Name", "username", "name") or ""
        email = _first(payload, "Email", "email") or ""
        if not username:
            return {"ok": False, "error": "未能从令牌解析到用户名"}
        return {"ok": True, "username": str(username), "email": str(email)}

    async def _query_models(self, body: dict[str, Any], token: str) -> tuple[list[Any], int | None]:
        try:
            import httpx
        except ImportError:
            return [], None
        url = f"{config.MODELSCOPE_ENDPOINT}/api/v1/models/"
        await self._limiter.wait()
        try:
            async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
                response = await client.put(url, json=body, headers=self._headers(token))
                data = response.json()
        except Exception:  # noqa: BLE001
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
        return (raw if isinstance(raw, list) else []), total

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
        for page_index in range(1, max_pages + 1):
            rows, total = await self._query_models(
                {"Path": viewer, "PageNumber": page_index, "PageSize": 100}, token
            )
            entries.extend([row for row in rows if isinstance(row, dict)])
            if len(rows) < 100:
                break
            if total is not None and len(entries) >= total:
                break
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
        try:
            import httpx  # noqa: F401
        except ImportError:
            return {"ok": False, "error": "缺少 httpx 依赖，请重新安装运行环境"}
        page = max(1, page)
        page_size = max(1, min(48, page_size))
        keyword = (query or "").strip()
        prefix = config.WORKFLOWHUB_REPO_PREFIX

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
            candidates: list[dict[str, Any]] = []
            for entry in page_entries:
                repo_id = self._extract_repo_id(entry)
                if not repo_id:
                    continue
                manifest = await self.fetch_manifest(repo_id, token)
                if isinstance(manifest, dict):
                    candidates.append({"repo_id": repo_id, "manifest": manifest})
            return {
                "ok": True,
                "candidates": candidates,
                "total": total_hint,
                "page": page,
                "page_size": page_size,
                "page_source_count": len(page_entries),
            }

        raw_entries: list[Any] = []
        total_hint: int | None = None
        page_source_count = 0
        marker, marker_total = await self._query_models(
            {
                "Name": prefix,
                "PageNumber": page,
                "PageSize": page_size,
            },
            token,
        )
        raw_entries.extend(marker)
        page_source_count = len(marker)
        total_hint = marker_total
        # 自己的命名空间只作为第 1 页的兜底来源（防止前缀搜索漏召回自己的仓库）。
        if page == 1 and viewer:
            own, _ = await self._query_models(
                {"Path": viewer, "PageNumber": 1, "PageSize": 100}, token
            )
            raw_entries.extend(own)
        if keyword:
            keyword_raw, keyword_total = await self._query_models(
                {"Name": keyword, "PageNumber": page, "PageSize": page_size}, token
            )
            raw_entries.extend(keyword_raw)
            if total_hint is None:
                total_hint = keyword_total

        seen: set[str] = set()
        candidates = []
        for entry in raw_entries:
            if not isinstance(entry, dict):
                continue
            repo_id = self._extract_repo_id(entry)
            if not repo_id or repo_id in seen:
                continue
            seen.add(repo_id)
            if not repo_id.split("/", 1)[-1].startswith(prefix):
                continue
            manifest = await self.fetch_manifest(repo_id, token)
            if isinstance(manifest, dict):
                candidates.append({"repo_id": repo_id, "manifest": manifest})
        return {
            "ok": True,
            "candidates": candidates,
            "total": total_hint,
            "page": page,
            "page_size": page_size,
            "page_source_count": page_source_count,
        }

    async def _get_raw(self, repo_id: str, file_path: str, token: str) -> bytes | None:
        try:
            import httpx
        except ImportError:
            return None
        url = f"{config.MODELSCOPE_ENDPOINT}/api/v1/models/{repo_id}/repo"
        params = {"FilePath": file_path, "Revision": "master"}
        await self._limiter.wait()
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(
                    url, params=params, headers=self._headers(token)
                )
                if response.status_code != 200:
                    return None
                content = response.content
        except Exception:  # noqa: BLE001
            return None
        if len(content) > config.WORKFLOWHUB_MAX_MANIFEST_BYTES:
            return None
        return content

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
            return self._run_upload_worker(
                token, repo_id, str(stage), display_name, on_progress
            )
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
