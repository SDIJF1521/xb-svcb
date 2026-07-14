"""模型站服务：基于 ModelScope（魔搭社区）的翻唱模型上传 / 搜索 / 下载。

方案要点（与用户确认的「每人自有令牌 + 标记防污染」一致）：
- 用户在「模型站」填写自己的 ModelScope 访问令牌（个人中心->访问令牌），持久化于 SettingsStore。
- 上传：把本地模型目录（G_*.pth + config.json + 可选扩散）打包，写入清单文件
  ``xb-svcb-model.json``（含 magic / schema / 文件角色），创建到「<用户名>/xb-svcb-<slug>-<id>」
  公开仓库。上传需要 modelscope SDK，放在独立 .venv-hub，经子进程 hub_worker 完成。
- 搜索：用固定标记关键词全局搜索 ModelScope 模型库，仅保留「仓库名带前缀且清单校验通过」
  的条目，避免被无关模型污染（软校验：他人理论上可伪造标记）。
- 下载：读清单 → 拉取各文件到暂存目录 → 复用 ModelService.import_model 导入本地模型库。

搜索 / 下载 / 校验令牌均走纯 httpx（无需上传组件）；上传才用 .venv-hub。
所有对外方法返回带 ``ok`` 字段的字典，便于前端统一处理。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import config
from infrastructure import paths
from infrastructure.storage import SettingsStore


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


def _slugify(name: str) -> str:
    """把模型名转为 ModelScope 仓库名可用的 ascii slug（字母数字+短横线）。"""
    s = re.sub(r"[^A-Za-z0-9]+", "-", (name or "").strip()).strip("-").lower()
    return s[:40] or "model"


def _first(d: dict[str, Any], *keys: str) -> Any:
    """从 dict 中按顺序取第一个非空字段（兼容 ModelScope 大小写不定的返回）。"""
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


class ModelHubService:
    """ModelScope 模型站：上传 / 搜索 / 下载本软件生态内的翻唱模型。"""

    def __init__(self, settings: SettingsStore, models: Any) -> None:
        self._settings = settings
        self._models = models  # ModelService：下载后复用其 import_model
        self._limiter = _AsyncRateLimiter(config.MODELSCOPE_QPS)
        # 进度表：key -> {phase, pct, msg, done, total}；供前端轮询展示进度条。
        # 下载 key 形如 "dl:<repo_id>"，上传 key 形如 "ul:<model_id>"。
        self._progress: dict[str, dict[str, Any]] = {}
        # 任务表：key -> {key, kind, title, status, result, error, created_at}。
        # 用于「后台传输」：上传/下载挂后台、前端全局轮询查看，不阻塞操作。
        self._jobs: dict[str, dict[str, Any]] = {}
        self._progress_lock = threading.Lock()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name="modelhub-loop"
        )
        self._thread.start()

    # ---- 进度 ----
    def _set_progress(
        self, key: str, phase: str, pct: float, msg: str = "", done: int = 0, total: int = 0
    ) -> None:
        with self._progress_lock:
            self._progress[key] = {
                "phase": phase,
                "pct": round(max(0.0, min(100.0, pct)), 1),
                "msg": msg,
                "done": done,
                "total": total,
            }

    def get_progress(self, key: str) -> dict[str, Any]:
        """读取某个上传/下载操作的进度（同步，供桥接轮询）。"""
        with self._progress_lock:
            cur = self._progress.get(key)
            return dict(cur) if cur else {"phase": "", "pct": 0, "msg": "", "done": 0, "total": 0}

    # ---- 后台任务（上传 / 下载挂后台，不阻塞前端）----
    def _set_job(self, key: str, **fields: Any) -> None:
        with self._progress_lock:
            job = self._jobs.get(key) or {"key": key}
            job.update(fields)
            self._jobs[key] = job

    def _finish_job(self, key: str, ok: bool, res: Any) -> None:
        err = None
        if not ok:
            err = (res or {}).get("error") if isinstance(res, dict) else "操作失败"
        self._set_job(
            key,
            status="done" if ok else "failed",
            result=res if (ok and isinstance(res, dict)) else None,
            error=err,
        )
        # 兜底：协程异常未写终态进度时补一条，保证前端进度条收尾
        cur = self.get_progress(key)
        if ok and cur.get("phase") != "done":
            self._set_progress(key, "done", 100, "完成")
        elif not ok and cur.get("phase") != "error":
            self._set_progress(key, "error", float(cur.get("pct") or 0), err or "操作失败")

    def _spawn(self, key: str, coro: Any) -> None:
        """把一个上传/下载协程投递到事件循环后台执行（不等待结果）。"""

        async def _runner() -> None:
            try:
                res = await coro
                ok = bool(res.get("ok")) if isinstance(res, dict) else False
                self._finish_job(key, ok, res if isinstance(res, dict) else {"ok": ok})
            except Exception as exc:  # noqa: BLE001 - 后台任务异常需记录而非崩溃
                self._finish_job(key, False, {"ok": False, "error": str(exc)})

        asyncio.run_coroutine_threadsafe(_runner(), self._loop)

    def start_download(self, repo_id: str) -> dict[str, Any]:
        """后台下载并导入模型，立即返回任务 key（前端用 hub_progress 轮询）。"""
        repo_id = (repo_id or "").strip()
        if not repo_id:
            return {"ok": False, "error": "缺少模型仓库 ID"}
        key = f"dl:{repo_id}"
        with self._progress_lock:
            existing = self._jobs.get(key)
            if existing and existing.get("status") == "running":
                return {"ok": True, "key": key, "already": True}
        self._set_job(
            key,
            kind="download",
            title=repo_id,
            status="running",
            result=None,
            error=None,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        self._set_progress(key, "start", 0, "排队中…")
        self._spawn(key, self._download(repo_id))
        return {"ok": True, "key": key}

    def start_upload(
        self, model_id: str, name: str | None = None, framework: str | None = None
    ) -> dict[str, Any]:
        """后台上传本地模型到模型站，立即返回任务 key。"""
        model_id = (model_id or "").strip()
        if not model_id:
            return {"ok": False, "error": "缺少模型 ID"}
        key = f"ul:{model_id}"
        with self._progress_lock:
            existing = self._jobs.get(key)
            if existing and existing.get("status") == "running":
                return {"ok": True, "key": key, "already": True}
        title = name or (self._models.get(model_id) or {}).get("name") or model_id
        self._set_job(
            key,
            kind="upload",
            title=title,
            status="running",
            result=None,
            error=None,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        self._set_progress(key, "start", 0, "排队中…")
        self._spawn(key, self._upload(model_id, name, framework))
        return {"ok": True, "key": key}

    def list_jobs(self) -> list[dict[str, Any]]:
        """列出全部上传/下载任务（含实时进度），供前端任务中心展示。"""
        with self._progress_lock:
            jobs = [dict(j) for j in self._jobs.values()]
            prog = {k: dict(v) for k, v in self._progress.items()}
        out: list[dict[str, Any]] = []
        for j in jobs:
            p = prog.get(j["key"], {})
            out.append(
                {
                    **j,
                    "pct": p.get("pct", 0),
                    "msg": p.get("msg", ""),
                    "phase": p.get("phase", ""),
                }
            )
        out.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)
        return out

    def clear_job(self, key: str) -> bool:
        """从任务表移除一条记录（通常用于清理已完成/失败的任务）。"""
        with self._progress_lock:
            self._jobs.pop(key, None)
            self._progress.pop(key, None)
        return True

    # ---- 令牌 ----
    def get_token(self) -> str:
        return str(self._settings.get(config.MODELSCOPE_TOKEN_SETTING, "") or "")

    def set_token(self, token: str) -> bool:
        self._settings.set(config.MODELSCOPE_TOKEN_SETTING, (token or "").strip())
        return True

    def upload_ready(self) -> bool:
        """上传组件（.venv-hub + modelscope）是否就绪。"""
        return config.modelhub_upload_ready()

    def list_frameworks(self) -> list[dict[str, str]]:
        """可选的模型架构标签列表（so-vits-svc / rvc …）。"""
        return [
            {"id": fid, "name": name}
            for fid, name in config.MODELHUB_FRAMEWORKS.items()
        ]

    # ---- 同步入口（供桥接调用）----
    def _submit(self, coro: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def verify_token(self, token: str | None = None) -> dict[str, Any]:
        return self._submit(self._verify_token(token))

    def search(
        self,
        query: str = "",
        page: int = 1,
        framework: str | None = None,
        page_size: int = 12,
    ) -> dict[str, Any]:
        return self._submit(
            self._search(query or "", int(page or 1), framework, int(page_size or 12))
        )

    def download(self, repo_id: str) -> dict[str, Any]:
        return self._submit(self._download(repo_id))

    def upload(
        self, model_id: str, name: str | None = None, framework: str | None = None
    ) -> dict[str, Any]:
        return self._submit(self._upload(model_id, name, framework))

    # ---- HTTP 基础 ----
    def _headers(self, token: str | None) -> dict[str, str]:
        h = {"User-Agent": "XB-SVCB", "Content-Type": "application/json"}
        if token:
            h["Authorization"] = f"Bearer {token}"
            h["Cookie"] = f"m_session_id={token}"  # 兼容部分接口的会话校验
        return h

    async def _verify_token(self, token: str | None) -> dict[str, Any]:
        try:
            import httpx
        except ImportError:
            return {"ok": False, "error": "缺少 httpx 依赖，请重新安装运行环境"}
        token = (token if token is not None else self.get_token()).strip()
        if not token:
            return {"ok": False, "error": "未填写 ModelScope 访问令牌"}
        url = f"{config.MODELSCOPE_ENDPOINT}/api/v1/login"
        await self._limiter.wait()
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.post(url, json={"AccessToken": token})
                data = resp.json()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"校验失败：{exc}"}
        d = data.get("Data") if isinstance(data, dict) else None
        if not isinstance(d, dict):
            msg = (data or {}).get("Message") if isinstance(data, dict) else None
            return {"ok": False, "error": msg or "令牌无效或网络异常"}
        username = _first(d, "Username", "Name", "username", "name") or ""
        email = _first(d, "Email", "email") or ""
        if not username:
            return {"ok": False, "error": "未能从令牌解析到用户名"}
        return {"ok": True, "username": str(username), "email": str(email)}

    # ---- 搜索 ----
    async def _query_models(self, body: dict[str, Any]) -> list[Any]:
        """调用 ModelScope 模型列表/搜索接口（PUT /api/v1/models/），返回原始条目列表。

        ModelScope 接口约定（经实测，字段为 PascalCase）：
          - 按命名空间列出：{"Path": owner, "PageNumber": n, "PageSize": m}
          - 按关键词模糊搜索：{"Name": text, "PageNumber": n, "PageSize": m}
            注意：真正生效的搜索字段是「Name」（匹配仓库英文名/中文名）；早期用的
            "Search"、以及小写的 "search" / "page_size" 都会被服务端「静默忽略」，
            接口会改回「全站热门第一页」，这正是"只搜得到自己上传的"根因。
        失败时返回空列表，不抛出异常。
        """
        try:
            import httpx
        except ImportError:
            return []
        token = self.get_token()
        url = f"{config.MODELSCOPE_ENDPOINT}/api/v1/models/"
        await self._limiter.wait()
        try:
            async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
                resp = await client.put(url, json=body, headers=self._headers(token))
                data = resp.json()
        except Exception:  # noqa: BLE001
            return []
        d = data.get("Data") if isinstance(data, dict) else None
        raw = []
        if isinstance(d, dict):
            raw = _first(d, "Models", "models", "Model", "List", "Data") or []
        elif isinstance(d, list):
            raw = d
        return raw if isinstance(raw, list) else []

    async def _search(
        self,
        query: str,
        page: int,
        framework: str | None = None,
        page_size: int = 12,
    ) -> dict[str, Any]:
        try:
            import httpx  # noqa: F401
        except ImportError:
            return {"ok": False, "error": "缺少 httpx 依赖，请重新安装运行环境"}
        page = max(1, page)
        page_size = max(1, min(50, int(page_size or 12)))
        q = (query or "").strip()

        # 汇集多来源候选条目，保证既能看到自己上传的，也能发现他人分享的：
        raw_entries: list[Any] = []
        # 来源 1：当前用户自己的命名空间（仅第 1 页合并，避免翻页时重复堆叠）
        if page == 1:
            me = await self._verify_token(None)
            if me.get("ok") and me.get("username"):
                raw_entries += await self._query_models(
                    {"Path": me["username"], "PageNumber": 1, "PageSize": 100}
                )
        # 来源 2：全站按「仓库名前缀」搜索（发现所有人公开分享的本软件模型）。
        # 经实测：PUT /api/v1/models 真正生效的搜索字段是「Name」（帕斯卡），分页用
        # PageNumber/PageSize。早期用的 "Search"（及小写 search/page_size）会被服务端
        # 静默忽略 → 接口改回「全站热门第一页」，经前缀过滤后全被丢弃，于是看起来「只
        # 搜得到自己上传的」（自己那路靠 Path 命名空间过滤才幸存）。每个上传仓库英文名
        # 都是 xb-svcb-<slug>-<id>，按 Name=xb-svcb 即可命中所有人；真伪仍由后续的
        # 「前缀过滤 + 清单 magic 校验」把关，避免污染。
        marker_raw = await self._query_models(
            {"Name": config.MODELHUB_REPO_PREFIX, "PageNumber": page, "PageSize": page_size}
        )
        raw_entries += marker_raw
        # 来源 3：若用户输入了关键词，再按关键词全站搜一次（英文名/slug 命中补召回；
        # 中文名等仍由下方 tokens 客户端过滤兜底）
        keyword_raw: list[Any] = []
        if q:
            keyword_raw = await self._query_models(
                {"Name": q, "PageNumber": page, "PageSize": page_size}
            )
            raw_entries += keyword_raw
        # 是否还有下一页：以分页来源的原始条数是否「满页」作启发式判断
        has_more = len(marker_raw) >= page_size or (
            bool(q) and len(keyword_raw) >= page_size
        )

        prefix = config.MODELHUB_REPO_PREFIX
        fw_filter = (framework or "").strip().lower()
        if fw_filter not in config.MODELHUB_FRAMEWORKS:
            fw_filter = ""
        # 模糊匹配：拆分为多个关键词，全部命中（名称/仓库/作者拼接文本）才算匹配
        tokens = [t for t in q.lower().split() if t]

        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in raw_entries:
            if not isinstance(entry, dict):
                continue
            repo_id = self._extract_repo_id(entry)
            if not repo_id or repo_id in seen:
                continue
            seen.add(repo_id)
            name_part = repo_id.split("/", 1)[-1]
            if not name_part.startswith(prefix):
                continue  # 不带本软件前缀，跳过
            # 校验清单，确认确为本软件上传（防污染）
            manifest = await self._fetch_manifest(repo_id)
            if not manifest:
                continue
            display = manifest.get("name") or name_part
            haystack = f"{display} {repo_id}".lower()
            if tokens and not all(t in haystack for t in tokens):
                continue  # 模糊关键词未全部命中
            fw = config.modelhub_normalize_framework(manifest.get("framework"))
            if fw_filter and fw != fw_filter:
                continue
            items.append(
                {
                    "repo_id": repo_id,
                    "name": display,
                    "type": manifest.get("type", ""),
                    "framework": fw,
                    "framework_label": config.MODELHUB_FRAMEWORKS.get(fw, fw),
                    "sample_rate": manifest.get("sample_rate", ""),
                    "author": repo_id.split("/", 1)[0],
                    "has_diffusion": bool(
                        (manifest.get("files") or {}).get("diffusion_model")
                    ),
                    "url": f"{config.MODELSCOPE_ENDPOINT}/models/{repo_id}",
                }
            )
        return {
            "ok": True,
            "items": items,
            "page": page,
            "page_size": page_size,
            "has_more": has_more,
        }

    @staticmethod
    def _extract_repo_id(entry: dict[str, Any]) -> str | None:
        """从搜索结果条目中尽量稳健地解析出 owner/name。"""
        # 直接给了 owner/name 形式
        for k in ("Path", "ModelPath", "Id", "ModelId", "FullName"):
            v = entry.get(k)
            if isinstance(v, str) and "/" in v:
                return v.strip("/")
        name = _first(entry, "Name", "ModelName", "name")
        owner = _first(
            entry, "Path", "Owner", "Organization", "Namespace", "CreatedBy", "Creator"
        )
        if isinstance(owner, dict):
            owner = _first(owner, "Name", "name", "Login")
        if name and owner and "/" not in str(name):
            return f"{owner}/{name}"
        return None

    async def _get_raw(self, repo_id: str, file_path: str) -> "bytes | None":
        """读取仓库中某个文件的原始内容（GET .../repo?FilePath=...）。"""
        try:
            import httpx
        except ImportError:
            return None
        token = self.get_token()
        url = f"{config.MODELSCOPE_ENDPOINT}/api/v1/models/{repo_id}/repo"
        params = {"FilePath": file_path, "Revision": "master"}
        await self._limiter.wait()
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(url, params=params, headers=self._headers(token))
                if resp.status_code != 200:
                    return None
                return resp.content
        except Exception:  # noqa: BLE001
            return None

    async def _list_files(self, repo_id: str) -> dict[str, int]:
        """获取仓库文件列表及大小（完整路径及唯一文件名 -> 字节数）。"""
        try:
            import httpx
        except ImportError:
            return {}
        token = self.get_token()
        url = f"{config.MODELSCOPE_ENDPOINT}/api/v1/models/{repo_id}/repo/files"
        params = {"Recursive": "true", "Revision": "master"}
        await self._limiter.wait()
        try:
            async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
                resp = await client.get(url, params=params, headers=self._headers(token))
                data = resp.json()
        except Exception:  # noqa: BLE001
            return {}
        d = data.get("Data") if isinstance(data, dict) else None
        raw = []
        if isinstance(d, dict):
            raw = _first(d, "Files", "files", "Tree") or []
        elif isinstance(d, list):
            raw = d
        sizes: dict[str, int] = {}
        if isinstance(raw, list):
            for f in raw:
                if not isinstance(f, dict):
                    continue
                path = _first(f, "Path", "Name", "name", "path")
                size = _first(f, "Size", "size") or 0
                if path:
                    full_path = str(path).replace("\\", "/").lstrip("./")
                    name = full_path.split("/")[-1]
                    try:
                        value = int(size)
                    except (TypeError, ValueError):
                        value = 0
                    sizes[full_path] = value
                    sizes.setdefault(name, value)
        return sizes

    async def _download_to(
        self,
        repo_id: str,
        file_path: str,
        dst: Path,
        cb: Any,
        expected_size: int = 0,
    ) -> bool:
        """流式下载并断点续传；失败时保留 ``.part`` 供下次继续。"""
        try:
            import httpx
        except ImportError:
            return False
        token = self.get_token()
        url = f"{config.MODELSCOPE_ENDPOINT}/api/v1/models/{repo_id}/repo"
        params = {"FilePath": file_path, "Revision": "master"}
        dst.parent.mkdir(parents=True, exist_ok=True)
        partial = dst.with_name(dst.name + ".part")

        if dst.is_file():
            size = dst.stat().st_size
            if expected_size > 0 and size == expected_size:
                return True
            if not partial.exists() or partial.stat().st_size < size:
                partial.unlink(missing_ok=True)
                dst.replace(partial)
            else:
                dst.unlink(missing_ok=True)
        if partial.is_file() and expected_size > 0 and partial.stat().st_size > expected_size:
            partial.unlink(missing_ok=True)

        timeout = httpx.Timeout(connect=20, read=120, write=30, pool=30)
        for attempt in range(3):
            start = partial.stat().st_size if partial.is_file() else 0
            headers = self._headers(token)
            if start > 0:
                headers["Range"] = f"bytes={start}-"
            await self._limiter.wait()
            try:
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                    async with client.stream(
                        "GET", url, params=params, headers=headers
                    ) as resp:
                        if resp.status_code == 416 and start > 0:
                            content_range = str(resp.headers.get("Content-Range") or "")
                            match = re.search(r"/(\d+)\s*$", content_range)
                            remote_size = int(match.group(1)) if match else expected_size
                            if remote_size > 0 and start == remote_size:
                                partial.replace(dst)
                                return True
                        if resp.status_code not in (200, 206):
                            raise RuntimeError(f"HTTP {resp.status_code}")
                        append = resp.status_code == 206 and start > 0
                        mode = "ab" if append else "wb"
                        with partial.open(mode) as output:
                            async for chunk in resp.aiter_bytes(256 * 1024):
                                output.write(chunk)
                                if cb:
                                    cb(len(chunk))
                actual = partial.stat().st_size if partial.is_file() else 0
                if expected_size > 0 and actual != expected_size:
                    raise RuntimeError(
                        f"文件大小不完整：{actual}/{expected_size} bytes"
                    )
                partial.replace(dst)
                return True
            except Exception:  # noqa: BLE001 - retry while preserving partial file
                if attempt < 2:
                    await asyncio.sleep(1 + attempt * 2)
        return False

    async def _fetch_manifest(self, repo_id: str) -> dict[str, Any] | None:
        raw = await self._get_raw(repo_id, config.MODELHUB_MANIFEST)
        if not raw:
            return None
        try:
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except (ValueError, UnicodeDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        if data.get("magic") != config.MODELHUB_MAGIC:
            return None
        files = data.get("files")
        if not isinstance(files, dict) or not files.get("main_model"):
            return None
        # so-vits / SeedVC 需要主配置；RVC 无主配置（仅 .pth + 可选 .index）。
        fw = config.modelhub_normalize_framework(data.get("framework"))
        if fw != "rvc" and not files.get("main_config"):
            return None
        return data

    # ---- 下载 ----
    async def _download(self, repo_id: str) -> dict[str, Any]:
        repo_id = (repo_id or "").strip().strip("/")
        key = f"dl:{repo_id}"
        if "/" not in repo_id:
            return {"ok": False, "error": "无效的模型仓库标识"}
        self._set_progress(key, "start", 1, "校验模型清单…")
        manifest = await self._fetch_manifest(repo_id)
        if not manifest:
            self._set_progress(key, "error", 0, "清单校验失败")
            return {"ok": False, "error": "该模型不是本软件上传或清单校验失败，已跳过"}

        fw = config.modelhub_normalize_framework(manifest.get("framework"))
        is_rvc = fw == "rvc"
        files = manifest.get("files") or {}
        roles = {
            "main_model": files.get("main_model"),
            "main_config": files.get("main_config"),
            "diffusion_model": files.get("diffusion_model"),
            "diffusion_config": files.get("diffusion_config"),
            "index_file": files.get("index_file"),
        }
        to_dl = [(role, str(fn)) for role, fn in roles.items() if fn]
        paths.ensure_dirs()
        stage = config.MODELHUB_DIR / "download" / repo_id.replace("/", "__")
        stage.mkdir(parents=True, exist_ok=True)

        # 预取各文件大小作为进度总量（拿不到则退化为按文件个数计进度）
        sizes = await self._list_files(repo_id)
        total_bytes = sum(
            int(sizes.get(fn.replace("\\", "/").lstrip("./"), sizes.get(Path(fn).name, 0)))
            for _, fn in to_dl
        )
        done_bytes = 0
        self._set_progress(key, "download", 2, "开始下载…", 0, total_bytes)

        local_paths: dict[str, str] = {}
        n = len(to_dl)
        for idx, (role, fname) in enumerate(to_dl):
            base = Path(fname).name
            dst = stage / role / base
            legacy = stage / base
            if legacy.is_file() and not dst.exists() and not dst.with_name(dst.name + ".part").exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                legacy.replace(dst)
            expected_size = int(
                sizes.get(fname.replace("\\", "/").lstrip("./"), sizes.get(base, 0))
            )

            def _cb(chunk: int) -> None:
                nonlocal done_bytes
                done_bytes += chunk
                if total_bytes > 0:
                    pct = 2 + done_bytes / total_bytes * 86
                else:
                    pct = 2 + (idx / max(n, 1)) * 86
                self._set_progress(
                    key, "download", min(88.0, pct), f"下载 {base}", done_bytes, total_bytes
                )

            ok = await self._download_to(
                repo_id,
                fname,
                dst,
                _cb,
                expected_size,
            )
            if not ok:
                self._set_progress(key, "error", 0, f"下载失败：{base}")
                return {
                    "ok": False,
                    "error": f"下载文件失败：{fname}；再次点击下载可从断点继续",
                }
            local_paths[role] = str(dst)

        need_config = not is_rvc
        if "main_model" not in local_paths or (need_config and "main_config" not in local_paths):
            self._set_progress(key, "error", 0, "模型主文件缺失")
            return {"ok": False, "error": "模型主文件缺失，下载中止"}
        self._set_progress(key, "import", 92, "导入本地模型库…", done_bytes, total_bytes)
        payload = {
            "name": manifest.get("name") or repo_id.split("/", 1)[-1],
            "framework": fw,
            "sample_rate": manifest.get("sample_rate", "44.1kHz"),
            "main_model": local_paths.get("main_model"),
            "main_config": local_paths.get("main_config"),
            "diffusion_model": local_paths.get("diffusion_model"),
            "diffusion_config": local_paths.get("diffusion_config"),
            "index_file": local_paths.get("index_file"),
            "source_repo_id": repo_id,
        }
        imported = self._models.import_model(payload)
        if not imported:
            self._set_progress(key, "error", 0, "导入失败")
            return {"ok": False, "error": "导入到本地模型库失败"}
        shutil.rmtree(stage, ignore_errors=True)  # 导入成功后才清理断点文件
        self._set_progress(key, "done", 100, "完成")
        return {"ok": True, "model": imported}

    # ---- 上传 ----
    async def _upload(
        self, model_id: str, name: str | None, framework: str | None = None
    ) -> dict[str, Any]:
        if not config.modelhub_upload_ready():
            return {
                "ok": False,
                "error": "上传组件未安装（.venv-hub）。请在「搭建/修复运行环境」中安装模型上传组件后重试。",
            }
        key = f"ul:{model_id}"
        model = self._models.get(model_id)
        if not model:
            return {"ok": False, "error": "本地模型不存在"}

        # 架构标签：显式传入优先，否则按本地模型 type 猜测（默认 so-vits-svc）
        fw = (framework or "").strip().lower()
        if fw not in config.MODELHUB_FRAMEWORKS:
            fw = config.modelhub_guess_framework(model.get("type"))
        fw_label = config.MODELHUB_FRAMEWORKS.get(fw, fw)

        self._set_progress(key, "verify", 3, "校验访问令牌…")
        verify = await self._verify_token(None)
        if not verify.get("ok"):
            self._set_progress(key, "error", 0, "令牌校验失败")
            return verify
        username = verify["username"]
        self._set_progress(key, "prepare", 8, "准备上传文件…")

        display = (name or model.get("name") or "model").strip()
        slug = _slugify(display)
        short = str(model_id).split("_")[-1][:8] or "x"
        repo_name = f"{config.MODELHUB_REPO_PREFIX}-{slug}-{short}"
        repo_id = f"{username}/{repo_name}"

        # 暂存目录：复制模型文件 + 写清单 + README（含标记，利于全局搜索发现）
        paths.ensure_dirs()
        stage = config.MODELHUB_DIR / "upload" / str(model_id)
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True, exist_ok=True)

        def _copy_role(role: str) -> str | None:
            mf = model.get(role) or {}
            src = mf.get("path")
            if not src or not Path(src).exists():
                return None
            dst = stage / Path(src).name
            try:
                shutil.copy2(src, dst)
            except OSError:
                return None
            return Path(src).name

        roles = {
            "main_model": _copy_role("main_model"),
            "main_config": _copy_role("main_config"),
            "diffusion_model": _copy_role("diffusion_model"),
            "diffusion_config": _copy_role("diffusion_config"),
            "index_file": _copy_role("index_file"),
        }
        # 主模型必备；so-vits / SeedVC 还需主配置，RVC 则不需要。
        if not roles["main_model"] or (fw != "rvc" and not roles["main_config"]):
            shutil.rmtree(stage, ignore_errors=True)
            return {"ok": False, "error": "模型主文件缺失，无法上传"}

        manifest = {
            "magic": config.MODELHUB_MAGIC,
            "schema": config.MODELHUB_SCHEMA,
            "app": config.APP_NAME,
            "marker": config.MODELSCOPE_MARKER,
            "name": display,
            "type": model.get("type", ""),
            # 模型架构标签：用于兼容不同框架，并在模型站按类型筛选
            "framework": fw,
            "framework_label": fw_label,
            "sample_rate": model.get("sample_rate", "44.1kHz"),
            "files": roles,
            "uploaded_by": username,
            "uploaded_at": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            (stage / config.MODELHUB_MANIFEST).write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (stage / "README.md").write_text(
                f"# {display}\n\n"
                f"XB-SVCB 翻唱声音模型 · 架构：{fw_label}（{fw}）。\n\n"
                f"> 标记: {config.MODELSCOPE_MARKER}\n\n"
                "由「XB-SVCB AI 翻唱工具」上传。下载请在软件内「模型站」搜索使用。\n",
                encoding="utf-8",
            )
        except OSError as exc:
            shutil.rmtree(stage, ignore_errors=True)
            return {"ok": False, "error": f"准备上传文件失败：{exc}"}

        result = await asyncio.get_event_loop().run_in_executor(
            None, self._run_upload_worker, self.get_token(), repo_id, str(stage), display, key
        )
        shutil.rmtree(stage, ignore_errors=True)
        if result.get("ok"):
            self._set_progress(key, "done", 100, "完成")
        else:
            self._set_progress(key, "error", 0, result.get("error", "上传失败"))
        return result

    def _run_upload_worker(
        self, token: str, repo_id: str, folder: str, chinese_name: str, key: str
    ) -> dict[str, Any]:
        """以子进程调用 .venv-hub 中的 hub_worker 完成上传，实时解析进度。"""
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
            chinese_name,
            "--visibility",
            "5",
        ]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        try:
            proc = subprocess.Popen(
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
        assert proc.stdout is not None
        for raw in proc.stdout:
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
                # 上传阶段占进度 10% -> 99%
                pct = 10 + (done / total * 89) if total > 0 else 10
                self._set_progress(
                    key, "upload", pct, f"上传 {name}（{done}/{total}）", done, total
                )
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
        proc.wait()
        if result is not None:
            return result
        return {"ok": False, "error": " | ".join(tail[-3:]) or "上传失败（无输出）"}
