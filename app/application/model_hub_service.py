"""模型站服务：基于 ModelScope（魔搭社区）的翻唱模型上传 / 搜索 / 下载。

方案要点（与用户确认的「每人自有令牌 + 标记防污染」一致）：
- 用户在「模型站」填写自己的 ModelScope 访问令牌（个人中心->访问令牌），持久化于 SettingsRepository。
- 上传：把本地模型目录（G_*.pth + config.json + 可选扩散）打包，写入清单文件
  ``xb-svcb-model.json``（含 magic / schema / 文件角色），创建到「<用户名>/xb-svcb-<slug>-<id>」
  公开仓库。上传需要 modelscope SDK，放在独立 .venv-hub，经子进程 hub_worker 完成。
- 搜索：用固定标记关键词全局搜索 ModelScope 模型库，仅保留「仓库名带前缀且清单校验通过」
  的条目，避免被无关模型污染（软校验：他人理论上可伪造标记）。
- 下载：读清单 → 拉取各文件到暂存目录 → 复用 ModelService.import_model 导入本地模型库。

搜索 / 下载 / 校验令牌均经 ``ModelHubGateway`` 端口（实现见
``infrastructure/model_hub_client.py``）；仅模型上传使用 .venv-hub。
所有对外方法返回带 ``ok`` 字段的字典，便于前端统一处理。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any

import config
from .adapters import ensure_data_dirs
from .ports import ModelHubGateway, SettingsRepository

MODELHUB_ASSET_MIMES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".aac": "audio/aac",
}
MODELHUB_PREVIEW_AUDIO_MAX_BYTES = 1024 * 1024 * 1024

# 搜索时补充的框架别名：用户常在模型名后加「模型」或写 sovits / ddsp。
_MODELHUB_FRAMEWORK_ALIASES: dict[str, tuple[str, ...]] = {
    "so-vits-svc": ("so-vits", "sovits", "svc"),
    "rvc": ("rvc",),
    "seed-vc": ("seed-vc", "seedvc"),
    "ddsp-svc": ("ddsp", "ddsp-svc", "浅扩散"),
    "other": (),
}
# 「ddsp模型」「rvc 模型」里的通用后缀不参与匹配，否则会把结果滤空。
_MODELHUB_SEARCH_STOPWORDS = {
    "模型",
    "声音",
    "声音模型",
    "翻唱",
    "音色",
    "语音",
    "的",
}


def _search_tokens(query: str) -> list[str]:
    """把搜索词拆成小写 tokens，并去掉「模型」这类通用后缀。

    ``ddsp模型`` -> ``["ddsp"]``；``纳西妲 模型`` -> ``["纳西妲"]``；
    ``芙芙`` 保持 ``["芙芙"]``。这样既支持框架词，也支持中文名 + 「模型」后缀。
    """
    tokens: list[str] = []
    for part in (query or "").lower().split():
        pieces = re.findall(r"[a-z0-9][a-z0-9._+-]*|[\u4e00-\u9fff]+", part)
        for piece in pieces:
            token = piece
            for suffix in ("声音模型", "模型", "音色", "翻唱", "语音"):
                if token.endswith(suffix) and len(token) > len(suffix):
                    token = token[: -len(suffix)]
                    break
            if not token or token in _MODELHUB_SEARCH_STOPWORDS:
                continue
            if token not in tokens:
                tokens.append(token)
    return tokens


class _AsyncRateLimiter:
    """兼容旧引用的空壳（真正的限流在 infrastructure/http_async.py）。"""

    def __init__(self, rate_per_sec: float) -> None:
        self._rate = rate_per_sec

    async def wait(self) -> None:
        return None


async def _gather_bounded(items: list[Any], worker: Any, limit: int) -> list[Any]:
    """有界并发执行，失败项返回 None（保持与 items 的顺序对应）。"""
    if not items:
        return []
    semaphore = asyncio.Semaphore(max(1, int(limit)))

    async def run(item: Any) -> Any:
        async with semaphore:
            try:
                return await worker(item)
            except Exception:  # noqa: BLE001 - 单个仓库失败不应拖垮搜索
                return None

    return await asyncio.gather(*(run(item) for item in items))


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


def _trim_text(value: Any, max_len: int) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]+", " ", str(value or "")).strip()
    return text[:max_len]


def _file_size(path: Path) -> int:
    return path.stat().st_size


def _audio_signature_matches(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            head = fh.read(64)
    except OSError:
        return False
    if len(head) < 4:
        return False
    if head.startswith(b"ID3"):
        return True
    if head[:2] == b"\xff\xfb" or (head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return True
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return True
    if head.startswith(b"fLaC") or head.startswith(b"OggS"):
        return True
    if head[4:8] == b"ftyp":
        return True
    if head[0] == 0xFF and (head[1] & 0xF0) == 0xF0:
        return True
    return False


def _ffprobe_audio_ok(path: Path) -> bool | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
            **config.subprocess_no_window(),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and "audio" in result.stdout.lower()


def _ensure_preview_audio_file(path: Path) -> None:
    size = _file_size(path)
    if size > MODELHUB_PREVIEW_AUDIO_MAX_BYTES:
        raise OSError("试听音频不能大于 1GB")
    probe_ok = _ffprobe_audio_ok(path)
    if probe_ok is False:
        raise OSError(f"试听音频不是可解析的音频文件：{path.name}")
    if probe_ok is None and not _audio_signature_matches(path):
        raise OSError(f"试听音频格式校验失败：{path.name}")


def _normalize_tags(value: Any) -> list[str]:
    raw: list[Any]
    if isinstance(value, list):
        raw = value
    else:
        raw = re.split(r"[,，;；\s]+", str(value or ""))
    tags: list[str] = []
    for item in raw:
        tag = _trim_text(item, 24).strip("#")
        if tag and tag not in tags:
            tags.append(tag)
    return tags[:12]


def _version_key(value: Any) -> tuple[int, int, int, int, str]:
    text = str(value or "").strip()
    nums = [int(x) for x in re.findall(r"\d+", text)[:4]]
    nums += [0] * (4 - len(nums))
    return nums[0], nums[1], nums[2], nums[3], text.lower()


def _is_remote_newer(
    remote_version: Any,
    local_version: Any,
    remote_time: Any = "",
    local_time: Any = "",
) -> bool:
    rv = str(remote_version or "").strip()
    lv = str(local_version or "").strip()
    if rv and lv and _version_key(rv) != _version_key(lv):
        return _version_key(rv) > _version_key(lv)
    rt = str(remote_time or "")
    lt = str(local_time or "")
    return bool(rt and lt and rt > lt)


class ModelHubService:
    """ModelScope 模型站：上传 / 搜索 / 下载本软件生态内的翻唱模型。"""

    def __init__(
        self,
        settings: SettingsRepository,
        models: Any,
        gateway: ModelHubGateway | None = None,
    ) -> None:
        self._settings = settings
        self._models = models  # ModelService：下载后复用其 import_model
        self._gateway = gateway
        # 搜索缓存：清单 / 令牌校验 / 搜索结果都带短 TTL。所有搜索协程都在
        # 本服务的专用 loop 上执行，字典访问不需要跨线程锁。
        self._manifest_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
        self._search_cache: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
        self._viewer_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        # 进度表：key -> {phase, pct, msg, done, total}；供前端轮询展示进度条。
        # 下载 key 形如 "dl:<repo_id>"，上传 key 形如 "ul:<model_id>"。
        self._progress: dict[str, dict[str, Any]] = {}
        # 任务表：key -> {key, kind, title, status, result, error, created_at}。
        # 用于「后台传输」：上传/下载挂后台、前端全局轮询查看，不阻塞操作。
        self._jobs: dict[str, dict[str, Any]] = {}
        self._progress_lock = threading.Lock()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="modelhub-loop"
        )
        self._thread.start()

    def _run_loop(self) -> None:
        # 在 loop 启动前排入预热协程；协程真正执行时 running loop 已就绪。
        try:
            self._loop.create_task(self._warm_gateway_async())
        except Exception:  # noqa: BLE001 - 预热失败不影响主流程
            pass
        self._loop.run_forever()

    async def _warm_gateway_async(self) -> None:
        self._warm_gateway()

    def _warm_gateway(self) -> None:
        gateway = getattr(self, "_gateway", None)
        prepare = getattr(gateway, "prepare", None)
        if callable(prepare):
            try:
                prepare()
            except Exception:  # noqa: BLE001 - 预热失败不影响按需创建
                pass

    def _gw(self) -> ModelHubGateway:
        """取注入的网关；单独构造服务（脚本 / 单测）时走默认适配器接缝。"""
        gateway = getattr(self, "_gateway", None)
        if gateway is None:
            from .adapters import model_hub_gateway

            gateway = model_hub_gateway()
            self._gateway = gateway
        return gateway

    def _ensure_caches(self) -> None:
        """兼容脚本 / 单测用 object.__new__ 构造、未走 __init__ 的场景。"""
        if not hasattr(self, "_manifest_cache"):
            self._manifest_cache = {}
        if not hasattr(self, "_search_cache"):
            self._search_cache = {}
        if not hasattr(self, "_viewer_cache"):
            self._viewer_cache = {}
        if not hasattr(self, "_local_hash_cache"):
            self._local_hash_cache = {}
            self._load_local_hash_cache()

    @staticmethod
    def _local_hash_cache_path() -> Path:
        return config.MODELHUB_DIR / "local-model-hashes.json"

    def _load_local_hash_cache(self) -> None:
        try:
            raw = json.loads(self._local_hash_cache_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(raw, dict):
            self._local_hash_cache = {
                str(key): str(value)
                for key, value in raw.items()
                if isinstance(value, str) and value
            }

    def _save_local_hash_cache(self) -> None:
        path = self._local_hash_cache_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_text(
                json.dumps(self._local_hash_cache, ensure_ascii=False),
                encoding="utf-8",
            )
            temporary.replace(path)
        except OSError:
            pass

    @staticmethod
    def _hash_local_file_sync(path: Path) -> str | None:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
        except OSError:
            return None
        return digest.hexdigest()

    async def _local_file_sha256(self, path: str) -> str | None:
        """本地文件 SHA-256（按路径+大小+mtime 缓存，线程内计算）。"""
        self._ensure_caches()
        target = Path(path)
        try:
            stat = target.stat()
        except OSError:
            return None
        cache_key = (
            f"{target.resolve()}|{int(stat.st_size)}|{int(stat.st_mtime_ns)}"
        )
        cached = self._local_hash_cache.get(cache_key)
        if isinstance(cached, str):
            return cached
        value = await asyncio.to_thread(self._hash_local_file_sync, target)
        if value:
            if len(self._local_hash_cache) >= 512:
                self._local_hash_cache.pop(next(iter(self._local_hash_cache)), None)
            self._local_hash_cache[cache_key] = value
            self._save_local_hash_cache()
        return value

    async def _file_digests(self, repo_id: str) -> dict[str, tuple[int, str]]:
        try:
            return await self._gw().file_digests(self.get_token(), repo_id)
        except Exception:  # noqa: BLE001 - 摘要不可用时退回元数据匹配
            return {}

    @staticmethod
    def _remote_main_digest(
        manifest: dict[str, Any], digests: dict[str, tuple[int, str]]
    ) -> tuple[int, str] | None:
        files = manifest.get("files")
        if not isinstance(files, dict):
            return None
        main_name = str(files.get("main_model") or "").strip().replace("\\", "/")
        if not main_name or not digests:
            return None
        main_name = main_name.lstrip("./")
        record = digests.get(main_name) or digests.get(Path(main_name).name)
        if not record:
            return None
        size, sha256 = record
        try:
            size_value = int(size)
        except (TypeError, ValueError):
            size_value = 0
        sha256 = str(sha256 or "").lower()
        if size_value <= 0 or not sha256:
            return None
        return size_value, sha256

    @staticmethod
    def _local_main_path(model: dict[str, Any]) -> Path | None:
        main = model.get("main_model")
        if not isinstance(main, dict):
            return None
        raw = str(main.get("path") or "").strip()
        if not raw:
            return None
        path = Path(raw)
        return path if path.is_file() else None

    @staticmethod
    def _model_framework(model: dict[str, Any]) -> str:
        framework = str(model.get("framework") or "").strip()
        if framework:
            return config.modelhub_normalize_framework(framework)
        return config.modelhub_guess_framework(str(model.get("type") or ""))

    async def _hash_match_local_model(
        self,
        repo_id: str,
        manifest: dict[str, Any],
        local_models: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """用主模型文件 SHA-256 匹配本地模型（不依赖 source_repo_id）。"""
        if not local_models:
            return None
        remote_framework = config.modelhub_normalize_framework(
            manifest.get("framework")
        )
        digests = await self._file_digests(repo_id)
        remote = self._remote_main_digest(manifest, digests)
        if not remote:
            return None
        remote_size, remote_sha = remote
        for model in local_models:
            meta = model.get("metadata") or {}
            source_repo = (
                str(meta.get("source_repo_id") or "").strip().strip("/")
            )
            # 已经绑定来源仓库的本地模型走 source_repo_id 快速路径；不要让它
            # 通过相同权重去“顶替”另一个仓库（例如两个仓库共用同一份 pth），
            # 否则删除其中一个模型后，另一个仍会让它显示「查看本地」。
            if source_repo:
                continue
            if self._model_framework(model) != remote_framework:
                continue
            path = self._local_main_path(model)
            if path is None:
                continue
            try:
                if path.stat().st_size != remote_size:
                    continue
            except OSError:
                continue
            local_sha = await self._local_file_sha256(str(path))
            if local_sha and local_sha.lower() == remote_sha:
                return model
        return None

    async def _resolve_hash_matches(
        self,
        candidates: list[tuple[str, dict[str, Any], dict[str, Any]]],
        local_models: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        if not candidates or not local_models:
            return {}
        source_repo_ids = {
            str((model.get("metadata") or {}).get("source_repo_id") or "")
            .strip()
            .strip("/")
            for model in local_models
            if self._local_main_path(model) is not None
        }
        needs_hash = [
            (repo_id, manifest)
            for repo_id, manifest, _entry in candidates
            if repo_id not in source_repo_ids
        ]
        if not needs_hash:
            return {}

        async def match_one(item: tuple[str, dict[str, Any]]) -> tuple[str, dict[str, Any] | None]:
            repo_id, manifest = item
            return repo_id, await self._hash_match_local_model(
                repo_id, manifest, local_models
            )

        results = await _gather_bounded(needs_hash, match_one, 4)
        matches: dict[str, dict[str, Any]] = {}
        for item in results:
            if not item:
                continue
            repo_id, model = item
            if model:
                matches[repo_id] = model
        return matches

    def _cache_get(
        self, cache: dict[Any, Any], key: Any, default: Any = None
    ) -> Any:
        item = cache.get(key)
        if item is None:
            return default
        expires, value = item
        if expires <= time.monotonic():
            cache.pop(key, None)
            return default
        return value

    def _cache_set(
        self,
        cache: dict[Any, Any],
        key: Any,
        value: Any,
        ttl: float,
        *,
        max_entries: int = 512,
    ) -> None:
        if len(cache) >= max_entries and key not in cache:
            cache.pop(next(iter(cache)), None)
        cache[key] = (time.monotonic() + max(0.1, ttl), value)

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
        self,
        model_id: str,
        name: str | None = None,
        framework: str | None = None,
        metadata: dict[str, Any] | None = None,
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
        self._spawn(key, self._upload(model_id, name, framework, metadata or {}))
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
        self._viewer_cache.clear()
        self._search_cache.clear()
        getattr(self, "_manifest_cache", {}).clear()
        try:
            self._gw().invalidate_token_cache()
        except Exception:  # noqa: BLE001 - 缓存清理失败不应阻断保存令牌
            pass
        return True

    def invalidate_cache(self) -> None:
        """本地模型库变化（删除 / 导入）后让下一次搜索重新计算安装状态。"""
        self._ensure_caches()
        self._manifest_cache.clear()
        self._search_cache.clear()
        self._viewer_cache.clear()
        try:
            self._gw().invalidate_cache()
        except Exception:  # noqa: BLE001
            pass

    def upload_ready(self) -> bool:
        """上传组件（.venv-hub + modelscope）是否就绪。"""
        return config.modelhub_upload_ready()

    def list_frameworks(self) -> list[dict[str, str]]:
        """可选的模型架构标签列表（so-vits-svc / rvc …）。"""
        return [
            {"id": fid, "name": name}
            for fid, name in config.MODELHUB_FRAMEWORKS.items()
        ]

    # ---- 阶段四：模型生态元数据 / 更新 ----

    @staticmethod
    def _dependency_specs(framework: str, files: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        fw = config.modelhub_normalize_framework(framework)
        files = files or {}
        specs: list[dict[str, Any]] = [
            {
                "id": "ffmpeg",
                "name": "ffmpeg",
                "required": True,
                "kind": "runtime",
            },
            {
                "id": "uvr",
                "name": "UVR 人声分离",
                "required": True,
                "kind": "runtime",
            },
        ]
        if fw == "rvc":
            specs.append(
                {
                    "id": "rvc",
                    "name": "RVC 推理环境",
                    "required": True,
                    "kind": "runtime",
                }
            )
            specs.append(
                {
                    "id": "index_file",
                    "name": "RVC index 检索文件",
                    "required": False,
                    "kind": "model_file",
                    "present": bool(files.get("index_file")),
                }
            )
        elif fw == "seed-vc":
            specs.append(
                {
                    "id": "seedvc",
                    "name": "SeedVC 推理环境",
                    "required": True,
                    "kind": "runtime",
                }
            )
            specs.append(
                {
                    "id": "reference_audio",
                    "name": "推理参考音频",
                    "required": True,
                    "kind": "runtime_input",
                }
            )
        elif fw == "ddsp-svc":
            specs.append(
                {
                    "id": "ddsp",
                    "name": "DDSP-SVC 推理环境",
                    "required": True,
                    "kind": "runtime",
                }
            )
        else:
            specs.append(
                {
                    "id": "svc",
                    "name": "So-VITS-SVC 推理环境",
                    "required": True,
                    "kind": "runtime",
                }
            )
            specs.append(
                {
                    "id": "diffusion_model",
                    "name": "扩散模型",
                    "required": False,
                    "kind": "model_file",
                    "present": bool(files.get("diffusion_model")),
                }
            )
        return specs

    @staticmethod
    def _dependency_ok(dep_id: str, present: bool | None = None) -> bool:
        if dep_id == "ffmpeg":
            return shutil.which("ffmpeg") is not None
        if dep_id == "uvr":
            return config.uvr_ready()
        if dep_id == "svc":
            return config.svc_engine_ready()
        if dep_id == "rvc":
            return config.rvc_engine_ready()
        if dep_id == "seedvc":
            return config.seedvc_engine_ready()
        if dep_id == "ddsp":
            return config.ddsp_engine_ready()
        if present is not None:
            return bool(present)
        return True

    def _dependency_status(
        self, framework: str, files: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for spec in self._dependency_specs(framework, files):
            ok = self._dependency_ok(spec["id"], spec.get("present"))
            if spec.get("kind") == "runtime_input":
                ok = True
            message = "已就绪" if ok else ("缺失" if spec.get("required") else "未提供")
            if spec.get("kind") == "runtime_input":
                message = "推理时选择"
            out.append({**spec, "ok": ok, "message": message})
        return out

    def _assets_from_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        raw = manifest.get("assets")
        if not isinstance(raw, dict):
            raw = {}
        screenshots = []
        raw_screenshots = raw.get("screenshots") or manifest.get("screenshots") or []
        if not isinstance(raw_screenshots, list):
            raw_screenshots = []
        for item in raw_screenshots:
            path = str(item.get("path") if isinstance(item, dict) else item or "").strip()
            if path:
                screenshots.append(
                    {
                        "path": path,
                        "name": Path(path).name,
                        "kind": "image",
                        "mime": MODELHUB_ASSET_MIMES.get(Path(path).suffix.lower(), "image/png"),
                    }
                )
        preview = raw.get("preview_audio") or manifest.get("preview_audio")
        if isinstance(preview, dict):
            preview = preview.get("path")
        preview_path = str(preview or "").strip()
        return {
            "screenshots": screenshots[:8],
            "preview_audio": {
                "path": preview_path,
                "name": Path(preview_path).name,
                "kind": "audio",
                "mime": MODELHUB_ASSET_MIMES.get(Path(preview_path).suffix.lower(), "audio/mpeg"),
            }
            if preview_path
            else None,
        }

    def _installed_info(
        self,
        repo_id: str,
        manifest: dict[str, Any] | None = None,
        local_models: list[dict[str, Any]] | None = None,
        hash_match: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        latest_version = str((manifest or {}).get("version") or "1.0.0")
        latest_time = str((manifest or {}).get("uploaded_at") or "")
        matches: list[dict[str, Any]] = []
        # 搜索结果有多条时由调用方传入一次快照，避免每条都重新扫描本地模型库
        # （ModelService.list 会读取配置 / 声线信息，重复调用很浪费）。
        source = local_models if local_models is not None else self._models.list()
        for model in source:
            meta = model.get("metadata") or {}
            if meta.get("source_repo_id") != repo_id:
                continue
            if self._local_main_path(model) is None:
                # 元数据说有来源，但本地文件已经不在了：不能算已安装。
                continue
            installed_version = str(meta.get("source_version") or "")
            installed_time = str(meta.get("source_uploaded_at") or "")
            matches.append(
                {
                    "model_id": model.get("id", ""),
                    "model_name": model.get("name", ""),
                    "installed_version": installed_version,
                    "installed_at": model.get("imported_at", ""),
                    "source_uploaded_at": installed_time,
                    "matched_by": "repo",
                }
            )
        matched_by_hash = False
        if not matches and hash_match:
            meta = hash_match.get("metadata") or {}
            matches.append(
                {
                    "model_id": hash_match.get("id", ""),
                    "model_name": hash_match.get("name", ""),
                    "installed_version": str(meta.get("source_version") or ""),
                    "installed_at": hash_match.get("imported_at", ""),
                    "source_uploaded_at": str(meta.get("source_uploaded_at") or ""),
                    "matched_by": "sha256",
                }
            )
            matched_by_hash = True
        current = matches[0] if matches else {}
        return {
            "installed": bool(matches),
            "installed_by_hash": matched_by_hash,
            "installed_models": matches,
            "model_id": current.get("model_id", ""),
            "model_name": current.get("model_name", ""),
            "installed_version": current.get("installed_version", ""),
            "latest_version": latest_version,
            "available": bool(
                matches
                and not matched_by_hash
                and _is_remote_newer(
                    latest_version,
                    current.get("installed_version"),
                    latest_time,
                    current.get("source_uploaded_at"),
                )
            ),
        }

    def _build_item(
        self,
        repo_id: str,
        manifest: dict[str, Any],
        *,
        detail: bool = False,
        local_models: list[dict[str, Any]] | None = None,
        hash_match: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        fw = config.modelhub_normalize_framework(manifest.get("framework"))
        raw_files = manifest.get("files")
        files = raw_files if isinstance(raw_files, dict) else {}
        assets = self._assets_from_manifest(manifest)
        deps = self._dependency_status(fw, files)
        required_deps_ok = all(d.get("ok") for d in deps if d.get("required"))
        version = str(manifest.get("version") or "1.0.0")
        uploaded_at = str(manifest.get("uploaded_at") or "")
        item = {
            "repo_id": repo_id,
            "name": manifest.get("name") or repo_id.split("/", 1)[-1],
            "type": manifest.get("type", ""),
            "framework": fw,
            "framework_label": config.MODELHUB_FRAMEWORKS.get(fw, fw),
            "sample_rate": manifest.get("sample_rate", ""),
            "author": repo_id.split("/", 1)[0],
            "has_diffusion": bool(files.get("diffusion_model")),
            "url": f"{config.MODELSCOPE_ENDPOINT}/models/{repo_id}",
            "description": _trim_text(manifest.get("description"), 1000),
            "tags": _normalize_tags(manifest.get("tags")),
            "version": version,
            "uploaded_at": uploaded_at,
            "screenshots": assets["screenshots"],
            "preview_audio": assets["preview_audio"],
            "dependency_ok": required_deps_ok,
            "dependencies": deps if detail else [],
            "versions": manifest.get("versions")
            if isinstance(manifest.get("versions"), list)
            else [
                {
                    "version": version,
                    "uploaded_at": uploaded_at,
                    "repo_id": repo_id,
                    "current": True,
                }
            ],
            "update": self._installed_info(repo_id, manifest, local_models, hash_match),
        }
        item["score"] = round(
            (8 if item.get("preview_audio") else 0)
            + min(8, len(item.get("screenshots") or []) * 2)
            + (6 if item.get("dependency_ok") else 0),
            2,
        )
        return item

    def model_detail(self, repo_id: str) -> dict[str, Any]:
        return self._submit(self._model_detail(repo_id))

    def asset_data(self, repo_id: str, file_path: str) -> dict[str, Any]:
        return self._submit(self._asset_data(repo_id, file_path))

    def check_updates(self) -> dict[str, Any]:
        return self._submit(self._check_updates())

    def start_upgrade(self, model_id: str) -> dict[str, Any]:
        model_id = (model_id or "").strip()
        model = self._models.get(model_id)
        if not model:
            return {"ok": False, "error": "本地模型不存在"}
        repo_id = str((model.get("metadata") or {}).get("source_repo_id") or "").strip()
        if "/" not in repo_id:
            return {"ok": False, "error": "该模型没有来源仓库，无法一键升级"}
        return self.start_download(repo_id)

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
        self,
        model_id: str,
        name: str | None = None,
        framework: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._submit(self._upload(model_id, name, framework, metadata or {}))

    # ---- 网关封装（网络 / 限流 / 缓存都在 infrastructure）----
    async def _verify_token(self, token: str | None) -> dict[str, Any]:
        self._ensure_caches()
        value = (token if token is not None else self.get_token()).strip()
        if not value:
            return {"ok": False, "error": "未填写 ModelScope 访问令牌"}
        cached = self._cache_get(self._viewer_cache, value)
        if isinstance(cached, dict):
            return dict(cached)
        try:
            result = await self._gw().verify_token(value)
        except Exception as exc:  # noqa: BLE001 - 与旧实现一致：校验失败返回错误字典
            return {"ok": False, "error": f"校验失败：{exc}"}
        if isinstance(result, dict):
            self._cache_set(
                self._viewer_cache,
                value,
                result,
                config.MODELSCOPE_TOKEN_TTL if result.get("ok") else 15.0,
                max_entries=8,
            )
        return result

    async def _query_models_page(
        self, body: dict[str, Any]
    ) -> tuple[list[Any], int | None]:
        """同 ``_query_models``，但保留服务端总数提示（分页组件需要）。"""
        try:
            raw, total = await self._gw().query_models(self.get_token(), body)
        except Exception:  # noqa: BLE001 - 搜索失败退化为空结果
            return [], None
        return (raw if isinstance(raw, list) else []), total

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
        raw, _total = await self._query_models_page(body)
        return raw

    async def _query_models_all(
        self,
        body: dict[str, Any],
        *,
        page_size: int = 100,
        max_pages: int = 10,
    ) -> list[Any]:
        """按 100 条/页拉全某个查询的所有条目（用于稳定的客户端分页）。

        模型站只收录本软件上传的模型，总量很小；分页要保证「每页条数绝不超」
        且跨页不重不漏，就不能每页只拉一部分再合并多个来源。这里一次拉全候选
        列表（有上限保护），再按页取清单，页面边界才稳定。
        """
        first_body = dict(body)
        first_body["PageNumber"] = 1
        first_body["PageSize"] = page_size
        entries, total = await self._query_models_page(first_body)
        collected = list(entries)
        if not collected:
            return collected
        if total is not None:
            effective = len(entries) if len(entries) < page_size else page_size
            effective = max(1, effective)
            page_count = min(max_pages, max(1, (int(total) + effective - 1) // effective))
        else:
            page_count = max_pages if len(entries) >= page_size else 1
        if page_count <= 1:
            return collected

        async def fetch_page(page_number: int) -> list[Any]:
            page_body = dict(body)
            page_body["PageNumber"] = page_number
            page_body["PageSize"] = page_size
            page_entries, _page_total = await self._query_models_page(page_body)
            return page_entries

        rest = await _gather_bounded(list(range(2, page_count + 1)), fetch_page, 4)
        for page_entries in rest:
            if page_entries:
                collected.extend(page_entries)
        return collected

    async def _search(
        self,
        query: str,
        page: int,
        framework: str | None = None,
        page_size: int = 12,
    ) -> dict[str, Any]:
        self._ensure_caches()
        page = max(1, page)
        page_size = max(1, min(50, int(page_size or 12)))
        q = (query or "").strip()
        fw_filter = (framework or "").strip().lower()
        if fw_filter not in config.MODELHUB_FRAMEWORKS:
            fw_filter = ""
        token = self.get_token()

        cache_key = (q, page, page_size, fw_filter, token)
        cached = self._cache_get(self._search_cache, cache_key)
        if isinstance(cached, dict):
            return dict(cached)

        # 分页不能在「每页只拉一部分」的基础上合并多个来源，否则第 1 页会
        # 同时出现 marker + 关键词 + 自己命名空间的多批条目，条数超过 page_size。
        # 这里先拉全候选列表（模型站总量很小，且有列表缓存），再按页切：
        # 页大小严格 <= page_size，跨页不重不漏。
        prefix = config.MODELHUB_REPO_PREFIX
        sources: dict[str, Any] = {
            "marker": self._query_models_all(
                {"Name": prefix}, page_size=100, max_pages=10
            )
        }
        if q:
            # 关键词结果只作为「优先展示」来源（一页 100 条足够），最终仍按
            # 仓库前缀 + 清单校验过滤，不会把无关模型混进分页。
            sources["keyword"] = self._query_models_page(
                {"Name": q, "PageNumber": 1, "PageSize": 100}
            )
        if token:
            sources["verify"] = self._verify_token(None)

        keys = list(sources)
        values = await asyncio.gather(*(sources[key] for key in keys))
        results = dict(zip(keys, values))
        marker_raw = results.get("marker") or []
        keyword_raw, _keyword_total = results.get("keyword") or ([], None)
        me = results.get("verify") or {}
        viewer = ""
        if isinstance(me, dict) and me.get("ok") and me.get("username"):
            viewer = _trim_text(me.get("username"), 40)

        # 自己的命名空间也纳入同一份候选列表（每页都取同一份，保证页码稳定）；
        # 它依赖令牌校验结果，因此放在并发批次之后。
        own_raw: list[Any] = []
        if viewer:
            own_raw = await self._query_models_all(
                {"Path": viewer}, page_size=100, max_pages=2
            )

        # 顺序：自己命名空间 -> 关键词命中 -> 全站标记搜索。去重后作为稳定列表。
        raw_entries: list[Any] = own_raw + keyword_raw + marker_raw
        # 模糊匹配：拆分为多个关键词（兼容「ddsp模型」这种框架词 + 通用后缀）
        tokens = _search_tokens(q)

        pending: list[tuple[str, dict[str, Any]]] = []
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
            pending.append((repo_id, entry))

        start = (page - 1) * page_size
        filter_active = bool(tokens or fw_filter)

        def manifest_matches(repo_id: str, manifest: dict[str, Any]) -> bool:
            name_part = repo_id.split("/", 1)[-1]
            display = manifest.get("name") or name_part
            fw = config.modelhub_normalize_framework(manifest.get("framework"))
            # 搜索桶要包含框架名：用户搜「ddsp」时应能命中 framework=ddsp-svc
            # 的模型，即使它的显示名是「芙芙」、仓库名也不含 ddsp。
            haystack = " ".join(
                [
                    str(display),
                    repo_id,
                    fw,
                    str(config.MODELHUB_FRAMEWORKS.get(fw, "")),
                    " ".join(_MODELHUB_FRAMEWORK_ALIASES.get(fw, ())),
                    str(manifest.get("type") or ""),
                    " ".join(_normalize_tags(manifest.get("tags"))),
                ]
            ).lower()
            if tokens and not all(token in haystack for token in tokens):
                return False
            if fw_filter and fw != fw_filter:
                return False
            return True

        if filter_active:
            # 有关键词 / 框架筛选时必须扫描全部候选清单，否则匹配项在后面的
            # 仓库时会「搜不到」（旧实现只过滤当前页）。清单有 90s 缓存，
            # 扫描上限见 MODELSCOPE_SEARCH_SCAN_LIMIT。
            scan_limit = max(page_size, int(config.MODELSCOPE_SEARCH_SCAN_LIMIT))
            scan_pending = pending[:scan_limit]
            manifests = await _gather_bounded(
                [repo_id for repo_id, _entry in scan_pending],
                self._fetch_manifest,
                config.MODELSCOPE_MANIFEST_CONCURRENCY,
            )
            filtered: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
            for (repo_id, entry), manifest in zip(scan_pending, manifests):
                if not manifest or not manifest_matches(repo_id, manifest):
                    continue
                filtered.append((repo_id, manifest, entry))
            total = len(filtered)
            page_candidates = filtered[start:start + page_size]
        else:
            # 无筛选时按页读取清单，翻页更快；每页条数仍严格 <= page_size。
            total = len(pending)
            page_pending = pending[start:start + page_size]
            manifests = await _gather_bounded(
                [repo_id for repo_id, _entry in page_pending],
                self._fetch_manifest,
                config.MODELSCOPE_MANIFEST_CONCURRENCY,
            )
            page_candidates = [
                (repo_id, manifest, entry)
                for (repo_id, entry), manifest in zip(page_pending, manifests)
                if manifest
            ]
        has_more = page * page_size < total

        local_models = self._models.list() if page_candidates else []
        hash_matches = (
            await self._resolve_hash_matches(page_candidates, local_models)
            if local_models
            else {}
        )
        items = [
            self._build_item(
                repo_id,
                manifest,
                detail=False,
                local_models=local_models,
                hash_match=hash_matches.get(repo_id),
            )
            for repo_id, manifest, _entry in page_candidates
        ]
        payload = {
            "ok": True,
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": has_more,
        }
        self._cache_set(
            self._search_cache,
            cache_key,
            payload,
            config.MODELSCOPE_SEARCH_TTL,
            max_entries=64,
        )
        return payload

    async def _model_detail(self, repo_id: str) -> dict[str, Any]:
        repo_id = (repo_id or "").strip().strip("/")
        if "/" not in repo_id:
            return {"ok": False, "error": "无效的模型仓库标识"}
        manifest = await self._fetch_manifest(repo_id)
        if not manifest:
            return {"ok": False, "error": "该模型不是本软件上传或清单校验失败"}
        local_models = self._models.list()
        hash_matches = await self._resolve_hash_matches(
            [(repo_id, manifest, {})], local_models
        )
        return {
            "ok": True,
            "item": self._build_item(
                repo_id,
                manifest,
                detail=True,
                local_models=local_models,
                hash_match=hash_matches.get(repo_id),
            ),
        }

    def _asset_allowed(self, manifest: dict[str, Any], file_path: str) -> bool:
        assets = self._assets_from_manifest(manifest)
        allowed = {x.get("path") for x in assets.get("screenshots") or []}
        preview = assets.get("preview_audio")
        if preview:
            allowed.add(preview.get("path"))
        clean = file_path.replace("\\", "/").lstrip("./")
        return clean in {str(x).replace("\\", "/").lstrip("./") for x in allowed if x}

    def _raw_file_url(self, repo_id: str, file_path: str) -> str:
        repo = urllib.parse.quote(repo_id.strip("/"), safe="/")
        query = urllib.parse.urlencode({"FilePath": file_path, "Revision": "master"})
        return f"{config.MODELSCOPE_ENDPOINT}/api/v1/models/{repo}/repo?{query}"

    async def _asset_data(self, repo_id: str, file_path: str) -> dict[str, Any]:
        repo_id = (repo_id or "").strip().strip("/")
        file_path = str(file_path or "").strip()
        if "/" not in repo_id or not file_path:
            return {"ok": False, "error": "缺少模型仓库或素材路径"}
        manifest = await self._fetch_manifest(repo_id)
        if not manifest:
            return {"ok": False, "error": "清单校验失败"}
        if not self._asset_allowed(manifest, file_path):
            return {"ok": False, "error": "该文件不是模型清单中的展示素材"}
        ext = Path(file_path).suffix.lower()
        mime = MODELHUB_ASSET_MIMES.get(ext, "application/octet-stream")
        if mime.startswith("audio/"):
            return {
                "ok": True,
                "name": Path(file_path).name,
                "mime": mime,
                "url": self._raw_file_url(repo_id, file_path),
            }
        raw = await self._get_raw(repo_id, file_path)
        if not raw:
            return {"ok": False, "error": "读取展示素材失败"}
        if len(raw) > 8 * 1024 * 1024:
            return {"ok": False, "error": "展示素材过大，无法内联预览"}
        data = base64.b64encode(raw).decode("ascii")
        return {
            "ok": True,
            "name": Path(file_path).name,
            "mime": mime,
            "data": f"data:{mime};base64,{data}",
        }

    async def _check_updates(self) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        rows: list[tuple[dict[str, Any], str]] = []
        seen: set[str] = set()
        for model in self._models.list():
            meta = model.get("metadata") or {}
            repo_id = str(meta.get("source_repo_id") or "").strip().strip("/")
            if "/" not in repo_id or repo_id in seen:
                continue
            seen.add(repo_id)
            rows.append((model, repo_id))
        # 本地模型可能很多：并发读取清单，避免「检查更新」按钮串行等 N 个 RTT。
        manifests = await _gather_bounded(
            [repo_id for _model, repo_id in rows],
            self._fetch_manifest,
            config.MODELSCOPE_MANIFEST_CONCURRENCY,
        )
        for (model, repo_id), manifest in zip(rows, manifests):
            if not manifest:
                continue
            meta = model.get("metadata") or {}
            installed_version = str(meta.get("source_version") or "")
            latest_version = str(manifest.get("version") or "1.0.0")
            installed_time = str(meta.get("source_uploaded_at") or "")
            latest_time = str(manifest.get("uploaded_at") or "")
            available = _is_remote_newer(
                latest_version,
                installed_version,
                latest_time,
                installed_time,
            )
            if available:
                items.append(
                    {
                        "model_id": model.get("id", ""),
                        "model_name": model.get("name", ""),
                        "repo_id": repo_id,
                        "installed_version": installed_version,
                        "latest_version": latest_version,
                        "uploaded_at": latest_time,
                        "framework": config.modelhub_normalize_framework(manifest.get("framework")),
                    }
                )
        return {"ok": True, "items": items}

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
        """读取仓库中某个文件的原始内容（带连接复用与小文件 TTL 缓存）。"""
        try:
            return await self._gw().fetch_raw(self.get_token(), repo_id, file_path)
        except Exception:  # noqa: BLE001 - 单个文件读取失败按 None 处理
            return None

    async def _list_files(self, repo_id: str) -> dict[str, int]:
        """获取仓库文件列表及大小（完整路径及唯一文件名 -> 字节数）。"""
        try:
            return await self._gw().list_files(self.get_token(), repo_id)
        except Exception:  # noqa: BLE001
            return {}

    async def _download_to(
        self,
        repo_id: str,
        file_path: str,
        dst: Path,
        cb: Any,
        expected_size: int = 0,
    ) -> bool:
        """下载单文件；大文件由网关做分片并行 + 断点续传。"""
        try:
            return await self._gw().download_to(
                self.get_token(), repo_id, file_path, dst, cb, expected_size
            )
        except Exception:  # noqa: BLE001 - 失败保留 .part 供下次续传
            return False

    async def _fetch_manifest(self, repo_id: str) -> dict[str, Any] | None:
        repo_id = (repo_id or "").strip().strip("/")
        if not repo_id:
            return None
        cache = getattr(self, "_manifest_cache", None)
        if cache is None:
            cache = {}
            self._manifest_cache = cache
        now = time.monotonic()
        cached = cache.get(repo_id)
        if cached is not None and cached[0] > now:
            return cached[1]
        raw = await self._get_raw(repo_id, config.MODELHUB_MANIFEST)
        manifest = self._parse_manifest(raw)
        ttl = (
            config.MODELSCOPE_MANIFEST_TTL
            if manifest
            else config.MODELSCOPE_MANIFEST_NEGATIVE_TTL
        )
        if len(cache) >= 512 and repo_id not in cache:
            cache.pop(next(iter(cache)), None)
        cache[repo_id] = (now + ttl, manifest)
        return manifest

    @staticmethod
    def _parse_manifest(raw: bytes | None) -> dict[str, Any] | None:
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
        ensure_data_dirs()
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
            "source_version": str(manifest.get("version") or "1.0.0"),
            "source_uploaded_at": str(manifest.get("uploaded_at") or ""),
            "source_lineage_id": str(manifest.get("lineage_id") or repo_id),
            "source_tags": _normalize_tags(manifest.get("tags")),
        }
        imported = self._models.import_model(payload)
        if not imported:
            self._set_progress(key, "error", 0, "导入失败")
            return {"ok": False, "error": "导入到本地模型库失败"}
        # 本地安装状态变了：让下一次搜索重新计算「已安装 / 可更新」。
        getattr(self, "_search_cache", {}).clear()
        shutil.rmtree(stage, ignore_errors=True)  # 导入成功后才清理断点文件
        self._set_progress(key, "done", 100, "完成")
        return {"ok": True, "model": imported}

    # ---- 上传 ----
    async def _upload(
        self,
        model_id: str,
        name: str | None,
        framework: str | None = None,
        metadata: dict[str, Any] | None = None,
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
        ensure_data_dirs()
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

        meta = metadata if isinstance(metadata, dict) else {}
        version = _trim_text(meta.get("version"), 32) or "1.0.0"
        description = _trim_text(meta.get("description"), 1000)
        tags = _normalize_tags(meta.get("tags") or model.get("tags"))

        def _copy_asset(
            raw: Any,
            prefix: str,
            allowed_exts: tuple[str, ...],
            max_bytes: int,
            *,
            validate_audio: bool = False,
        ) -> str | None:
            src_raw = _trim_text(raw, 1000)
            if not src_raw:
                return None
            src = Path(src_raw)
            if not src.exists() or not src.is_file():
                raise OSError(f"展示素材不存在：{src_raw}")
            ext = src.suffix.lower()
            if ext not in allowed_exts:
                raise OSError(f"展示素材格式不支持：{src.name}")
            if validate_audio:
                _ensure_preview_audio_file(src)
            elif src.stat().st_size > max_bytes:
                raise OSError(f"展示素材过大：{src.name}")
            safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", src.stem).strip("._")
            safe_stem = safe_stem[:42] or prefix.strip("_")
            dst_name = f"{prefix}{safe_stem}{ext}"
            dst = stage / dst_name
            shutil.copy2(src, dst)
            return dst_name

        assets: dict[str, Any] = {"screenshots": []}
        try:
            preview_name = _copy_asset(
                meta.get("preview_audio"),
                "preview_",
                tuple(config.AUDIO_EXTS),
                MODELHUB_PREVIEW_AUDIO_MAX_BYTES,
                validate_audio=True,
            )
            if preview_name:
                assets["preview_audio"] = preview_name
            raw_shots = meta.get("screenshots")
            screenshots = raw_shots if isinstance(raw_shots, list) else []
            for idx, raw in enumerate(screenshots[:8], start=1):
                shot_name = _copy_asset(
                    raw,
                    f"screenshot_{idx}_",
                    (".jpg", ".jpeg", ".png", ".webp", ".gif"),
                    8 * 1024 * 1024,
                )
                if shot_name:
                    assets["screenshots"].append(shot_name)
        except OSError as exc:
            shutil.rmtree(stage, ignore_errors=True)
            return {"ok": False, "error": str(exc)}

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
            "version": version,
            "lineage_id": str((model.get("metadata") or {}).get("source_lineage_id") or repo_id),
            "description": description,
            "tags": tags,
            "assets": assets,
            "dependencies": self._dependency_specs(fw, roles),
            "uploaded_by": username,
            "uploaded_at": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            (stage / config.MODELHUB_MANIFEST).write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            readme = (
                f"# {display}\n\n"
                f"XB-SVCB 翻唱声音模型 · 架构：{fw_label}（{fw}）。\n\n"
                f"版本：{version}\n\n"
                + (f"{description}\n\n" if description else "")
                + (f"标签：{', '.join(tags)}\n\n" if tags else "")
                + f"> 标记: {config.MODELSCOPE_MARKER}\n\n"
                + "由「XB-SVCB AI 翻唱工具」上传。下载请在软件内「模型站」搜索使用。\n"
            )
            (stage / "README.md").write_text(readme, encoding="utf-8")
        except OSError as exc:
            shutil.rmtree(stage, ignore_errors=True)
            return {"ok": False, "error": f"准备上传文件失败：{exc}"}

        result = await asyncio.get_event_loop().run_in_executor(
            None, self._run_upload_worker, self.get_token(), repo_id, str(stage), display, key
        )
        shutil.rmtree(stage, ignore_errors=True)
        if result.get("ok"):
            # 刚上传/更新的仓库立刻可被搜索到：清掉清单与搜索结果缓存。
            getattr(self, "_manifest_cache", {}).clear()
            getattr(self, "_search_cache", {}).clear()
            try:
                self._gw().invalidate_cache()
            except Exception:  # noqa: BLE001
                pass
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
