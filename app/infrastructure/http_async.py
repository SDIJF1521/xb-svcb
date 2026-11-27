"""模型站 / 工作流商城共用的异步网络基础设施。

设计目标（针对「搜索慢、下载慢」）：

* **连接复用**：一个事件循环共用一个 ``httpx.AsyncClient``，保留 keep-alive
  连接与 TLS 会话，避免每次请求都重新握手（实测单次可省 0.3~1.5s）。
* **并发限流**：令牌桶允许短时突发，但长期不超过配置 QPS；与旧实现「持锁
  sleep」不同，等待令牌时不阻塞其它协程。
* **有界并发**：``gather_bounded`` 用信号量把「N 个清单一起来」限制在安全并发。
* **短 TTL 缓存**：清单 / 文件列表这类变化很慢的数据缓存几十秒，翻页与重复
  搜索直接命中；negative 结果也缓存，避免反复请求不存在的仓库。
* **429 退避**：服务端限流时全局暂停一小段时间，随后自动恢复。

关于 GIL：这里的瓶颈是网络 RTT，不是 CPU。``asyncio`` 的 socket / SSL 读写
会释放 GIL，单线程事件循环即可同时等待几十个连接；下载落盘用文件
``write``，同样在系统调用期间释放 GIL。因此不需要为了「多线程」再引入 C++
扩展。
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import threading
import time
import weakref
from typing import Any, Awaitable, Callable, Iterable, TypeVar

import httpx

import config

_T = TypeVar("_T")
_R = TypeVar("_R")

# 每个事件循环一个客户端：httpx 的连接池绑定 loop，跨 loop 复用会报错。
_CLIENTS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient]" = (
    weakref.WeakKeyDictionary()
)
_PROXY_ENV_LOCK = threading.Lock()


@contextlib.contextmanager
def _safe_proxy_environ():
    """临时移除 ``no_proxy`` 里的方括号 IPv6 条目。

    httpx 0.28 解析 ``no_proxy`` 时会把 ``[::1]`` 当成带端口的 URL，直接抛
    ``InvalidURL: Invalid port ':1]'``。Windows 上这类环境变量很常见，若不处理，
    整个模型站 / 工作流商城会在创建客户端时直接失败。去掉方括号后 ``::1``
    仍然有效，不影响本地回环直连。
    """

    keys = ("NO_PROXY", "no_proxy")
    saved = {key: os.environ.get(key) for key in keys}
    changed = False
    try:
        for key in keys:
            raw = saved.get(key)
            if not raw:
                continue
            parts = [part.strip() for part in raw.split(",") if part.strip()]
            cleaned: list[str] = []
            modified = False
            for part in parts:
                if part.startswith("[") and part.endswith("]"):
                    # ``[::1]`` -> ``::1``：去掉 URL 方括号后 httpx 即可正常解析。
                    inner = part[1:-1].strip()
                    if inner:
                        cleaned.append(inner)
                    modified = True
                else:
                    cleaned.append(part)
            if modified:
                os.environ[key] = ",".join(cleaned)
                changed = True
        yield
    finally:
        if changed:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def get_async_client() -> httpx.AsyncClient:
    """取当前事件循环共享的 HTTP 客户端（按 loop 隔离，自动重建）。"""
    loop = asyncio.get_running_loop()
    client = _CLIENTS.get(loop)
    if client is not None and not client.is_closed:
        return client
    limits = httpx.Limits(
        max_connections=max(4, int(config.MODELSCOPE_HTTP_MAX_CONNECTIONS)),
        max_keepalive_connections=max(4, int(config.MODELSCOPE_HTTP_MAX_CONNECTIONS)),
        keepalive_expiry=30.0,
    )
    kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(connect=20.0, read=120.0, write=30.0, pool=30.0),
        "limits": limits,
        "follow_redirects": True,
        "headers": {"User-Agent": "XB-SVCB"},
    }
    # 创建客户端会立即解析代理环境变量；加锁避免并发创建时互相看到被临时修改的值。
    with _PROXY_ENV_LOCK, _safe_proxy_environ():
        try:
            try:
                # httpx[http2] 已是项目依赖；缺少 h2 时退回 HTTP/1.1。
                client = httpx.AsyncClient(http2=True, **kwargs)
            except ImportError:
                client = httpx.AsyncClient(**kwargs)
        except httpx.InvalidURL:
            # 其它无法解析的 no_proxy 写法：宁可直连也不要让整个商城打不开。
            client = httpx.AsyncClient(trust_env=False, **kwargs)
    _CLIENTS[loop] = client
    return client


def close_async_clients() -> None:
    """关闭并清空所有缓存的客户端（进程退出 / 测试清理用）。"""
    for loop, client in list(_CLIENTS.items()):
        if client.is_closed or loop.is_closed():
            continue
        coroutine = client.aclose()
        try:
            loop.create_task(coroutine)
        except RuntimeError:
            # loop 已关闭：连接会随进程退出释放；关闭协程避免 "never awaited" 警告。
            coroutine.close()
    _CLIENTS.clear()


class AsyncTokenBucket:
    """协程友好的令牌桶（无锁，事件循环内单线程访问）。

    与「持锁 sleep」的旧限流器相比，等待令牌的协程不会阻塞其它协程，
    因此多个清单请求可以同时在途，只受平均 QPS 约束。
    """

    def __init__(self, rate_per_sec: float, burst: float | None = None) -> None:
        self._rate = max(0.1, float(rate_per_sec))
        self._capacity = max(1.0, float(burst if burst is not None else round(self._rate)))
        self._tokens = self._capacity
        self._updated: float | None = None
        self._paused_until = 0.0

    def _refill(self, now: float) -> None:
        if self._updated is None:
            self._updated = now
            return
        elapsed = max(0.0, now - self._updated)
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._updated = now

    async def acquire(self, amount: float = 1.0) -> None:
        """取一个令牌；必要时等待（不持有任何锁）。"""
        loop = asyncio.get_running_loop()
        need = max(0.001, float(amount))
        while True:
            now = loop.time()
            if now < self._paused_until:
                await asyncio.sleep(min(self._paused_until - now, 2.0))
                continue
            self._refill(now)
            if self._tokens >= need:
                self._tokens -= need
                return
            wait = (need - self._tokens) / self._rate
            await asyncio.sleep(max(0.01, min(wait, 1.0)))

    def penalize(self, seconds: float = 2.0) -> None:
        """服务端返回 429 / 5xx 时全局退避，避免继续撞墙。"""
        loop = asyncio.get_running_loop()
        self._paused_until = max(self._paused_until, loop.time() + max(0.0, seconds))
        self._tokens = 0.0


class TTLCache:
    """极简 TTL 缓存（事件循环内使用，不做跨线程加锁）。

    允许缓存 ``None``（negative cache）。超过 ``max_entries`` 时按插入顺序
    淘汰最旧的条目；对本场景（几十~几百个仓库）足够。
    """

    def __init__(self, ttl: float, max_entries: int = 512) -> None:
        self._ttl = max(0.1, float(ttl))
        self._max_entries = max(1, int(max_entries))
        self._data: dict[Any, tuple[float, Any]] = {}

    @staticmethod
    def _now() -> float:
        return time.monotonic()

    def get(self, key: Any, default: Any = None) -> Any:
        item = self._data.get(key)
        if item is None:
            return default
        expires, value = item
        if expires <= self._now():
            self._data.pop(key, None)
            return default
        return value

    def contains(self, key: Any) -> bool:
        item = self._data.get(key)
        if item is None:
            return False
        if item[0] <= self._now():
            self._data.pop(key, None)
            return False
        return True

    def set(self, key: Any, value: Any, ttl: float | None = None) -> None:
        if len(self._data) >= self._max_entries and key not in self._data:
            # 先清过期项；仍然满则丢掉最早插入的一项。
            now = self._now()
            for expired in [k for k, (exp, _) in self._data.items() if exp <= now]:
                self._data.pop(expired, None)
            if len(self._data) >= self._max_entries:
                self._data.pop(next(iter(self._data)), None)
        lifetime = self._ttl if ttl is None else max(0.1, float(ttl))
        self._data[key] = (self._now() + lifetime, value)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


async def gather_bounded(
    items: Iterable[_T],
    worker: Callable[[_T], Awaitable[_R]],
    limit: int,
    *,
    default: _R | None = None,
) -> list[_R | None]:
    """以不超过 ``limit`` 的并发度执行 ``worker``，失败项返回 ``default``。

    结果顺序与 ``items`` 一致（``asyncio.gather`` 语义），便于调用方把清单
    结果与原始候选按索引配对。
    """
    values = list(items)
    if not values:
        return []
    semaphore = asyncio.Semaphore(max(1, int(limit)))

    async def run(item: _T) -> _R | None:
        async with semaphore:
            try:
                return await worker(item)
            except Exception:  # noqa: BLE001 - 单个候选失败不应拖垮整次搜索
                return default

    return await asyncio.gather(*(run(item) for item in values))


def backoff_seconds(response: httpx.Response | None, default: float = 2.0) -> float:
    """解析 ``Retry-After``，拿不到就用默认退避秒数。"""
    if response is None:
        return default
    raw = response.headers.get("Retry-After")
    if not raw:
        return default
    try:
        return min(30.0, max(0.5, float(raw)))
    except (TypeError, ValueError):
        return default
