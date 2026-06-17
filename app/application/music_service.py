"""音乐资源获取服务：调用妖狐音乐 API 搜索 / 获取 / 下载歌曲。

设计要点：
- 使用 httpx 的 **异步** 客户端发起请求；所有协程都在本服务持有的独立事件循环
  线程中执行，桥接层只需同步调用。
- 严格遵守接口 10 QPS 限制：用一个异步「最小间隔」限流器串行化所有出站请求。
- API Key 由用户在前端「资源获取」页填写，持久化于 SettingsStore。
- 下载的歌曲落地到 ``config.MUSIC_DIR``，可在「AI 翻唱」页直接选用。

所有对外方法都返回带 ``ok`` 字段的字典，便于前端统一处理成功/失败与错误提示。
"""

from __future__ import annotations

import asyncio
import re
import threading
from typing import Any

import config
from infrastructure import paths
from infrastructure.storage import SettingsStore

# settings.json 中保存用户 API Key 的键名
_API_KEY_SETTING = "music_api_key"


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


def _sanitize_filename(name: str) -> str:
    """清洗为合法文件名（去除非法字符并限长）。"""
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name or "").strip().strip(".")
    return cleaned[:120] or "music"


class MusicService:
    """封装妖狐音乐 API 的搜索、单曲详情与下载。"""

    def __init__(self, settings: SettingsStore) -> None:
        self._settings = settings
        self._limiter = _AsyncRateLimiter(config.MUSIC_API_QPS)
        # 独立事件循环线程：让同步的 pywebview 桥接方法可以驱动 httpx 异步请求
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name="music-loop"
        )
        self._thread.start()

    # ---- API Key ----
    def get_api_key(self) -> str:
        return str(self._settings.get(_API_KEY_SETTING, "") or "")

    def set_api_key(self, key: str) -> bool:
        self._settings.set(_API_KEY_SETTING, (key or "").strip())
        return True

    def configured(self) -> bool:
        return bool(self.get_api_key())

    # ---- 同步入口（供桥接调用）：把协程投递到事件循环线程并等待结果 ----
    def _submit(self, coro: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def search(self, msg: str, g: int = 13) -> dict[str, Any]:
        return self._submit(self._search(msg, g))

    def get_song(self, msg: str, n: int) -> dict[str, Any]:
        return self._submit(self._get_song(msg, n))

    def download(self, msg: str, n: int) -> dict[str, Any]:
        return self._submit(self._download(msg, n))

    def list_downloaded(self) -> list[dict[str, Any]]:
        paths.ensure_dirs()
        items: list[dict[str, Any]] = []
        try:
            files = [p for p in config.MUSIC_DIR.iterdir() if p.is_file()]
        except OSError:
            return []
        for p in sorted(files, key=lambda x: x.stat().st_mtime, reverse=True):
            if p.suffix.lower() in config.AUDIO_EXTS:
                items.append(
                    {"name": p.stem, "path": str(p), "size": paths.file_size_label(p)}
                )
        return items

    def delete_downloaded(self, path: str) -> bool:
        """删除一首已下载歌曲（限定在音乐目录内，避免任意路径删除）。"""
        from pathlib import Path

        if not path:
            return False
        try:
            target = Path(path).resolve()
            allowed = config.MUSIC_DIR.resolve()
        except OSError:
            return False
        if allowed != target.parent or not target.exists():
            return False
        try:
            target.unlink()
            return True
        except OSError:
            return False

    # ---- 异步实现 ----
    async def _request(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            import httpx
        except ImportError:
            return {"ok": False, "error": "缺少 httpx 依赖，请重新安装运行环境"}

        key = self.get_api_key()
        if not key:
            return {"ok": False, "error": "未配置 API Key，请先在「API 设置」中填写"}

        query = {"key": key, **params}
        await self._limiter.wait()
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.get(config.MUSIC_API_URL, params=query)
                data = resp.json()
        except Exception as exc:  # noqa: BLE001 - 网络异常统一转为错误提示
            return {"ok": False, "error": f"请求失败：{exc}"}

        if not isinstance(data, dict) or data.get("code") != 200:
            msg = data.get("msg") if isinstance(data, dict) else "返回数据异常"
            return {"ok": False, "error": msg or "请求失败"}
        return {"ok": True, "data": data.get("data") or {}}

    async def _search(self, msg: str, g: int) -> dict[str, Any]:
        if not (msg or "").strip():
            return {"ok": False, "error": "请输入搜索关键词"}
        res = await self._request({"msg": msg, "g": int(g or 13)})
        if not res["ok"]:
            return res
        data = res["data"]
        songs = data.get("songs") or []
        items = [
            {
                "n": s.get("n"),
                "name": s.get("name", ""),
                "singer": s.get("singer", ""),
                "album": s.get("album", ""),
            }
            for s in songs
            if s.get("n") is not None
        ]
        return {"ok": True, "songs": items, "keyword": msg}

    async def _get_song(self, msg: str, n: int) -> dict[str, Any]:
        res = await self._request({"msg": msg, "n": int(n)})
        if not res["ok"]:
            return res
        d = res["data"]
        song = {
            "name": d.get("name", ""),
            # 单曲详情里歌手字段为 songname（接口约定）
            "singer": d.get("songname", ""),
            "album": d.get("album", ""),
            "title": d.get("songtitle", ""),
            "picture": d.get("picture", ""),
            "url": d.get("url", ""),
            "musicurl": d.get("musicurl", ""),
            "lrc": d.get("lrctxt") or "",
        }
        return {"ok": True, "song": song}

    async def _download(self, msg: str, n: int) -> dict[str, Any]:
        detail = await self._get_song(msg, n)
        if not detail.get("ok"):
            return detail
        song = detail["song"]
        url = song.get("musicurl") or song.get("url")
        if not url:
            return {"ok": False, "error": "无法获取下载地址（可能为 VIP / 无版权歌曲）"}

        try:
            import httpx
        except ImportError:
            return {"ok": False, "error": "缺少 httpx 依赖，请重新安装运行环境"}

        paths.ensure_dirs()
        base = song.get("name", "") or "music"
        if song.get("singer"):
            base = f"{base} - {song['singer']}"
        base = _sanitize_filename(base)
        dest = config.MUSIC_DIR / f"{base}.mp3"
        idx = 1
        while dest.exists():
            dest = config.MUSIC_DIR / f"{base} ({idx}).mp3"
            idx += 1

        await self._limiter.wait()
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    with dest.open("wb") as f:
                        async for chunk in resp.aiter_bytes(65536):
                            f.write(chunk)
        except Exception as exc:  # noqa: BLE001 - 下载失败需清理半成品文件
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
            return {"ok": False, "error": f"下载失败：{exc}"}

        return {
            "ok": True,
            "path": str(dest),
            "name": dest.stem,
            "size": paths.file_size_label(dest),
        }
