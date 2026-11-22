"""模型站 ModelScope 适配器（实现 ``application.ports.ModelHubGateway``）。

把 HTTP、重试、限流、缓存与断点续传收敛在基础设施层；用例层只负责清单
校验、导入与 DTO 组装。

性能要点：

* 所有请求复用 ``http_async.get_async_client()`` 的连接池；
* 令牌桶允许并发在途，不再把每个清单请求串行成 200ms；
* 清单 / 文件列表短 TTL 缓存，翻页与重复搜索直接命中；
* 大文件按 ``Range`` 分片、多连接并行写入，并用 ``.part.json`` 记录已完成
  分片，断点续传只补缺失分片；服务端不支持 Range 时自动退回单连接流式。
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Callable

import httpx

import config

from .http_async import (
    AsyncTokenBucket,
    TTLCache,
    backoff_seconds,
    get_async_client,
)

_DEFAULT_TIMEOUT = httpx.Timeout(connect=20.0, read=120.0, write=30.0, pool=30.0)


class _RangeUnsupported(Exception):
    """服务端忽略 Range（返回 200）时用于从分片下载退回单流下载。"""


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


class ModelHubClient:
    """ModelScope 模型仓库的异步客户端。"""

    def __init__(self) -> None:
        self._limiter = AsyncTokenBucket(
            config.MODELSCOPE_READ_QPS, config.MODELSCOPE_READ_BURST
        )
        self._raw_cache = TTLCache(config.MODELSCOPE_MANIFEST_TTL, max_entries=256)
        self._file_meta_cache = TTLCache(config.MODELSCOPE_FILES_TTL, max_entries=64)
        self._list_cache = TTLCache(config.MODELSCOPE_LIST_TTL, max_entries=128)
        self._token_cache = TTLCache(config.MODELSCOPE_TOKEN_TTL, max_entries=8)
        self._negative_cache = TTLCache(
            config.MODELSCOPE_MANIFEST_NEGATIVE_TTL, max_entries=256
        )

    # ---- 缓存 ----
    def prepare(self) -> None:
        """在事件循环线程里预创建共享 HTTP 客户端（避免首次搜索承担建连开销）。"""
        try:
            get_async_client()
        except Exception:  # noqa: BLE001 - 预热失败不影响后续按需创建
            pass

    def invalidate_cache(self) -> None:
        self._raw_cache.clear()
        self._file_meta_cache.clear()
        self._list_cache.clear()
        self._negative_cache.clear()

    def invalidate_token_cache(self) -> None:
        self._token_cache.clear()

    @staticmethod
    def _headers(token: str | None, *, json_content: bool = False) -> dict[str, str]:
        headers = {"User-Agent": "XB-SVCB"}
        if json_content:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
            headers["Cookie"] = f"m_session_id={token}"  # 兼容部分接口的会话校验
        return headers

    # ---- 令牌 ----
    async def verify_token(self, token: str) -> dict[str, Any]:
        value = (token or "").strip()
        if not value:
            return {"ok": False, "error": "未填写 ModelScope 访问令牌"}
        cache_key = ("token", value)
        cached = self._token_cache.get(cache_key)
        if isinstance(cached, dict):
            return dict(cached)
        url = f"{config.MODELSCOPE_ENDPOINT}/api/v1/login"
        last_error = ""
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
                last_error = f"校验失败：{exc}"
                if attempt == 0:
                    await asyncio.sleep(0.4)
                    continue
                return {"ok": False, "error": last_error}
            if response.status_code == 429:
                self._limiter.penalize(backoff_seconds(response))
                last_error = "令牌校验被限流，请稍后重试"
                if attempt == 0:
                    continue
                return {"ok": False, "error": last_error}
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
        return {"ok": False, "error": last_error or "令牌校验失败"}

    # ---- 模型列表 / 搜索 ----
    async def query_models(
        self, token: str, body: dict[str, Any]
    ) -> tuple[list[Any], int | None]:
        """调用 ``PUT /api/v1/models/``，返回 (原始条目, 服务端总数提示)。"""
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
            except Exception:  # noqa: BLE001 - 搜索失败退化为空结果
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

    # ---- 单文件读取 ----
    async def fetch_raw(
        self, token: str, repo_id: str, file_path: str
    ) -> bytes | None:
        """读取仓库内单个文件（清单 / 截图等小文件，带 TTL 缓存）。"""
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
                    url,
                    params=params,
                    headers=self._headers(token),
                    timeout=30.0,
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
            if len(content) <= config.MODELSCOPE_RAW_CACHE_MAX_BYTES:
                self._raw_cache.set(cache_key, content)
            return content
        return None

    async def _file_meta(self, token: str, repo_id: str) -> dict[str, dict[str, Any]]:
        """仓库文件元数据：路径/文件名 -> {size, sha256}（带 TTL 缓存）。

        ModelScope 的 ``/repo/files`` 会同时返回 ``Sha256`` 与 ``IsLFS``；实测
        该值就是文件内容的 SHA-256，可用于本地模型哈希比对。
        """
        repo_id = (repo_id or "").strip().strip("/")
        if "/" not in repo_id:
            return {}
        cache_key = (config.MODELSCOPE_ENDPOINT, repo_id)
        cached = self._file_meta_cache.get(cache_key)
        if isinstance(cached, dict):
            return cached
        url = f"{config.MODELSCOPE_ENDPOINT}/api/v1/models/{repo_id}/repo/files"
        params = {"Recursive": "true", "Revision": "master"}
        for attempt in range(2):
            await self._limiter.acquire()
            try:
                response = await get_async_client().get(
                    url,
                    params=params,
                    headers=self._headers(token),
                    timeout=25.0,
                )
            except Exception:  # noqa: BLE001
                if attempt == 0:
                    await asyncio.sleep(0.4)
                    continue
                return {}
            if response.status_code == 429:
                self._limiter.penalize(backoff_seconds(response))
                if attempt == 0:
                    continue
                return {}
            try:
                data = response.json()
            except ValueError:
                return {}
            payload = data.get("Data") if isinstance(data, dict) else None
            raw: Any = []
            if isinstance(payload, dict):
                raw = _first(payload, "Files", "files", "Tree") or []
            elif isinstance(payload, list):
                raw = payload
            meta: dict[str, dict[str, Any]] = {}
            if isinstance(raw, list):
                for item in raw:
                    if not isinstance(item, dict):
                        continue
                    path = _first(item, "Path", "Name", "name", "path")
                    if not path:
                        continue
                    full_path = str(path).replace("\\", "/").lstrip("./")
                    name = full_path.split("/")[-1]
                    try:
                        size = int(_first(item, "Size", "size") or 0)
                    except (TypeError, ValueError):
                        size = 0
                    sha256 = str(_first(item, "Sha256", "SHA256", "sha256") or "").lower()
                    record = {"size": size, "sha256": sha256}
                    meta[full_path] = record
                    meta.setdefault(name, record)
            self._file_meta_cache.set(cache_key, meta)
            return meta
        return {}

    async def list_files(self, token: str, repo_id: str) -> dict[str, int]:
        """获取仓库文件列表：完整路径 / 唯一文件名 -> 字节数（带缓存）。"""
        meta = await self._file_meta(token, repo_id)
        return {key: int(record.get("size") or 0) for key, record in meta.items()}

    async def file_digests(
        self, token: str, repo_id: str
    ) -> dict[str, tuple[int, str]]:
        """仓库文件摘要：完整路径 / 唯一文件名 -> (size, sha256)。"""
        meta = await self._file_meta(token, repo_id)
        return {
            key: (int(record.get("size") or 0), str(record.get("sha256") or ""))
            for key, record in meta.items()
        }

    # ---- 下载 ----
    async def download_to(
        self,
        token: str,
        repo_id: str,
        file_path: str,
        dst: Path,
        cb: Callable[[int], None] | None = None,
        expected_size: int = 0,
    ) -> bool:
        """下载单个文件到 ``dst``；失败保留 ``.part`` 供下次断点续传。

        文件达到 ``MODELHUB_DOWNLOAD_PARALLEL_MIN_BYTES`` 且开启多连接时，
        先尝试 Range 分片并行；服务端不支持 Range 则自动退回单连接流式。
        """
        repo_id = (repo_id or "").strip().strip("/")
        file_path = str(file_path or "").strip()
        if "/" not in repo_id or not file_path:
            return False
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

        connections = max(1, int(config.MODELHUB_DOWNLOAD_CONNECTIONS))
        parallel = (
            connections > 1
            and expected_size >= int(config.MODELHUB_DOWNLOAD_PARALLEL_MIN_BYTES)
        )
        if parallel and partial.is_file():
            # 升级前留下的单流 .part（无位图）继续单流续传，避免把旧进度当成
            # 分片位图或重新下载整份文件。
            meta_path = partial.with_name(partial.name + ".json")
            size = partial.stat().st_size
            if 0 < size < expected_size and not meta_path.is_file():
                parallel = False
        if parallel:
            result = await self._download_ranged(
                token, repo_id, file_path, dst, partial, cb, expected_size, connections
            )
            if result == "ok":
                return True
            if result == "failed":
                return False
            # "unsupported"：服务端不支持 Range，走下面的单连接流式。
        return await self._download_single(
            token, repo_id, file_path, dst, partial, cb, expected_size
        )

    async def _download_single(
        self,
        token: str,
        repo_id: str,
        file_path: str,
        dst: Path,
        partial: Path,
        cb: Callable[[int], None] | None,
        expected_size: int,
    ) -> bool:
        url = f"{config.MODELSCOPE_ENDPOINT}/api/v1/models/{repo_id}/repo"
        params = {"FilePath": file_path, "Revision": "master"}
        meta_path = partial.with_name(partial.name + ".json")
        if meta_path.exists():
            # 分片模式留下的 .part 是「预分配大小 + 完成位图」；退回单连接时
            # 不能把它当成已下完的文件，直接丢弃重下。
            partial.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
        for attempt in range(3):
            start = partial.stat().st_size if partial.is_file() else 0
            headers = self._headers(token)
            if start > 0:
                headers["Range"] = f"bytes={start}-"
            await self._limiter.acquire()
            try:
                async with get_async_client().stream(
                    "GET", url, params=params, headers=headers, timeout=_DEFAULT_TIMEOUT
                ) as response:
                    if response.status_code == 416 and start > 0:
                        content_range = str(response.headers.get("Content-Range") or "")
                        match = re.search(r"/(\d+)\s*$", content_range)
                        remote_size = int(match.group(1)) if match else expected_size
                        if remote_size > 0 and start == remote_size:
                            partial.replace(dst)
                            return True
                    if response.status_code == 429:
                        self._limiter.penalize(backoff_seconds(response))
                        raise RuntimeError("HTTP 429")
                    if response.status_code not in (200, 206):
                        raise RuntimeError(f"HTTP {response.status_code}")
                    append = response.status_code == 206 and start > 0
                    mode = "ab" if append else "wb"
                    with partial.open(mode) as output:
                        async for chunk in response.aiter_bytes(1024 * 1024):
                            output.write(chunk)
                            if cb:
                                try:
                                    cb(len(chunk))
                                except Exception:  # noqa: BLE001 - 进度回调不影响下载
                                    pass
                actual = partial.stat().st_size if partial.is_file() else 0
                if expected_size > 0 and actual != expected_size:
                    raise RuntimeError(f"文件大小不完整：{actual}/{expected_size} bytes")
                partial.replace(dst)
                return True
            except Exception:  # noqa: BLE001 - 保留 .part 供下次续传
                if attempt < 2:
                    await asyncio.sleep(1 + attempt * 2)
        return False

    async def _download_ranged(
        self,
        token: str,
        repo_id: str,
        file_path: str,
        dst: Path,
        partial: Path,
        cb: Callable[[int], None] | None,
        total: int,
        connections: int,
    ) -> str:
        """分片并行下载；返回 ``ok`` / ``unsupported`` / ``failed``。"""
        chunk = max(256 * 1024, int(config.MODELHUB_DOWNLOAD_CHUNK_BYTES))
        count = (total + chunk - 1) // chunk
        meta_path = partial.with_name(partial.name + ".json")
        done: set[int] = set()
        if (
            meta_path.is_file()
            and partial.is_file()
            and partial.stat().st_size == total
        ):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {}
            if (
                isinstance(meta, dict)
                and int(meta.get("total") or 0) == total
                and int(meta.get("chunk") or 0) == chunk
            ):
                done = {
                    int(value)
                    for value in meta.get("done") or []
                    if isinstance(value, int) or str(value).isdigit()
                }
                done = {index for index in done if 0 <= index < count}
        try:
            handle = partial.open("r+b" if partial.exists() else "w+b", buffering=0)
        except OSError:
            return "failed"

        def save_meta() -> None:
            try:
                payload = {"total": total, "chunk": chunk, "done": sorted(done)}
                temporary = meta_path.with_name(meta_path.name + ".tmp")
                temporary.write_text(json.dumps(payload), encoding="utf-8")
                temporary.replace(meta_path)
            except OSError:
                pass

        try:
            handle.truncate(total)
        except OSError:
            handle.close()
            return "failed"

        async def download_chunk(index: int) -> str:
            start = index * chunk
            end = min(start + chunk, total) - 1
            headers = self._headers(token)
            headers["Range"] = f"bytes={start}-{end}"
            url = f"{config.MODELSCOPE_ENDPOINT}/api/v1/models/{repo_id}/repo"
            params = {"FilePath": file_path, "Revision": "master"}
            for attempt in range(2):
                try:
                    async with get_async_client().stream(
                        "GET",
                        url,
                        params=params,
                        headers=headers,
                        timeout=_DEFAULT_TIMEOUT,
                    ) as response:
                        if response.status_code == 200:
                            raise _RangeUnsupported()
                        if response.status_code == 429:
                            self._limiter.penalize(backoff_seconds(response))
                            raise RuntimeError("HTTP 429")
                        if response.status_code != 206:
                            raise RuntimeError(f"HTTP {response.status_code}")
                        content_range = str(response.headers.get("Content-Range") or "")
                        match = re.match(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", content_range)
                        if match:
                            range_start = int(match.group(1))
                            range_end = int(match.group(2))
                            range_total = match.group(3)
                            if range_start != start or range_end != end:
                                raise RuntimeError("服务端返回了错误的 Range")
                            if range_total != "*" and int(range_total) != total:
                                raise RuntimeError("远端文件大小已变化")
                        offset = start
                        async for piece in response.aiter_bytes(1024 * 1024):
                            remaining = end + 1 - offset
                            if remaining <= 0:
                                break
                            view = memoryview(piece[:remaining])
                            while view:
                                handle.seek(offset)
                                written = handle.write(view)
                                if written <= 0:
                                    raise OSError("写入下载分片失败")
                                offset += written
                                view = view[written:]
                            if cb:
                                try:
                                    cb(min(len(piece), remaining))
                                except Exception:  # noqa: BLE001
                                    pass
                        if offset != end + 1:
                            raise RuntimeError("分片未下载完整")
                    done.add(index)
                    save_meta()
                    return "ok"
                except _RangeUnsupported:
                    return "unsupported"
                except Exception:  # noqa: BLE001 - 重试一次，仍失败则保留已完成分片
                    if attempt == 0:
                        await asyncio.sleep(1.0)
            return "failed"

        semaphore = asyncio.Semaphore(connections)

        pending = [index for index in range(count) if index not in done]

        async def guarded(index: int) -> str:
            async with semaphore:
                return await download_chunk(index)

        results = await asyncio.gather(*(guarded(index) for index in pending))
        try:
            handle.flush()
        except OSError:
            pass
        handle.close()
        if "unsupported" in results:
            # 服务端忽略 Range：删掉预分配文件，交给单连接流式重新下载，
            # 避免把「全 0 的完整大小文件」误判成已下完。
            meta_path.unlink(missing_ok=True)
            partial.unlink(missing_ok=True)
            return "unsupported"
        if any(result != "ok" for result in results):
            return "failed"
        try:
            if partial.stat().st_size != total:
                return "failed"
            partial.replace(dst)
            meta_path.unlink(missing_ok=True)
            return "ok"
        except OSError:
            return "failed"
