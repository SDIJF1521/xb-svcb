"""音乐资源获取服务：调用妖狐音乐 API 搜索 / 获取 / 下载歌曲。

设计要点：
- 使用 httpx 的 **异步** 客户端发起请求；所有协程都在本服务持有的独立事件循环
  线程中执行，桥接层只需同步调用。
- 严格遵守接口 10 QPS 限制：用一个异步「最小间隔」限流器串行化所有出站请求。
- API Key 由用户在前端「资源获取」页填写，持久化于 SettingsStore。
- 支持多个曲库（source）：wy=网易云、qq=QQ音乐；QQ音乐可额外配置会员 Cookie
  以获取高品质音频。曲库随每次调用传入，Cookie 持久化于 SettingsStore。
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
# settings.json 中保存用户上次选择曲库的键名
_SOURCE_SETTING = "music_source"
# settings.json 中保存 QQ音乐会员 Cookie 的键名
_QQ_COOKIE_SETTING = "music_qq_cookie"


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


# LRC 时间标签：[mm:ss.xx] / [mm:ss.xxx] / [mm:ss]
_LRC_TAG = re.compile(r"\[(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?\]")


def parse_lrc(text: str) -> list[dict[str, Any]]:
    """解析 LRC 歌词文本为按时间排序的句子列表 ``[{time, text}]``。

    - 支持一行多个时间标签（同词多时间）。
    - 跳过纯元信息行（[ti:][ar:][by:] 等无正文）与空白行。
    - time 为秒（float）。
    """
    lines: list[dict[str, Any]] = []
    for raw in (text or "").replace("\\n", "\n").splitlines():
        tags = list(_LRC_TAG.finditer(raw))
        if not tags:
            continue
        content = _LRC_TAG.sub("", raw).strip()
        if not content:
            continue
        for m in tags:
            minutes = int(m.group(1))
            seconds = int(m.group(2))
            frac_raw = m.group(3) or "0"
            # 毫秒位数不定：两位按百分秒、三位按毫秒
            frac = int(frac_raw) / (1000.0 if len(frac_raw) == 3 else 100.0)
            t = minutes * 60 + seconds + frac
            lines.append({"time": round(t, 3), "text": content})
    lines.sort(key=lambda x: x["time"])
    return lines


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

    # ---- 曲库（source）----
    def list_sources(self) -> list[dict[str, Any]]:
        """返回可选曲库列表，并标注是否支持 Cookie 配置。"""
        return [
            {
                "id": sid,
                "name": name,
                "cookie": sid in config.MUSIC_COOKIE_SOURCES,
            }
            for sid, name in config.MUSIC_SOURCES.items()
        ]

    def get_source(self) -> str:
        src = str(self._settings.get(_SOURCE_SETTING, "") or "")
        return src if src in config.MUSIC_SOURCES else config.MUSIC_API_DEFAULT_SOURCE

    def set_source(self, source: str) -> bool:
        self._settings.set(_SOURCE_SETTING, self._normalize_source(source))
        return True

    @staticmethod
    def _normalize_source(source: str | None) -> str:
        src = (source or "").strip()
        return src if src in config.MUSIC_SOURCES else config.MUSIC_API_DEFAULT_SOURCE

    # ---- QQ音乐会员 Cookie ----
    def get_cookie(self) -> str:
        return str(self._settings.get(_QQ_COOKIE_SETTING, "") or "")

    def set_cookie(self, cookie: str) -> bool:
        self._settings.set(_QQ_COOKIE_SETTING, (cookie or "").strip())
        return True

    # ---- 同步入口（供桥接调用）：把协程投递到事件循环线程并等待结果 ----
    def _submit(self, coro: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def search(self, msg: str, g: int = 13, source: str | None = None) -> dict[str, Any]:
        return self._submit(self._search(msg, g, self._normalize_source(source)))

    def get_song(self, msg: str, n: int, source: str | None = None) -> dict[str, Any]:
        return self._submit(self._get_song(msg, n, self._normalize_source(source)))

    def download(self, msg: str, n: int, source: str | None = None) -> dict[str, Any]:
        return self._submit(self._download(msg, n, self._normalize_source(source)))

    def get_lyrics(self, msg: str, n: int, source: str | None = None) -> dict[str, Any]:
        return self._submit(self._get_lyrics(msg, n, self._normalize_source(source)))

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
    async def _request(self, params: dict[str, Any], source: str) -> dict[str, Any]:
        try:
            import httpx
        except ImportError:
            return {"ok": False, "error": "缺少 httpx 依赖，请重新安装运行环境"}

        key = self.get_api_key()
        if not key:
            return {"ok": False, "error": "未配置 API Key，请先在「API 设置」中填写"}

        query: dict[str, Any] = {"key": key, **params}
        # QQ音乐：附带会员 Cookie 以获取高品质音频（其它曲库忽略该参数）
        if source in config.MUSIC_COOKIE_SOURCES:
            cookie = self.get_cookie()
            if cookie:
                query["cookie"] = cookie

        await self._limiter.wait()
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.get(config.music_api_url(source), params=query)
                data = resp.json()
        except Exception as exc:  # noqa: BLE001 - 网络异常统一转为错误提示
            return {"ok": False, "error": f"请求失败：{exc}"}

        if not isinstance(data, dict) or data.get("code") != 200:
            msg = data.get("msg") if isinstance(data, dict) else "返回数据异常"
            return {"ok": False, "error": msg or "请求失败"}
        return {"ok": True, "data": data.get("data") or {}}

    async def _search(self, msg: str, g: int, source: str) -> dict[str, Any]:
        if not (msg or "").strip():
            return {"ok": False, "error": "请输入搜索关键词"}
        res = await self._request({"msg": msg, "g": int(g or 13)}, source)
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
                # QQ音乐返回 pay 字段标记收费曲目（如 "[收费]"），其它曲库为空
                "pay": s.get("pay", ""),
            }
            for s in songs
            if s.get("n") is not None
        ]
        return {"ok": True, "songs": items, "keyword": msg, "source": source}

    async def _get_song(self, msg: str, n: int, source: str) -> dict[str, Any]:
        res = await self._request({"msg": msg, "n": int(n)}, source)
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

    async def _fetch_text(self, url: str) -> str:
        """抓取一个 URL 的文本内容（用于 QQ音乐 viplrc 歌词地址）。"""
        try:
            import httpx
        except ImportError:
            return ""
        await self._limiter.wait()
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.get(url)
                # 可能直接返回 lrc 文本，也可能是 {code,data:{lrc/lyric}} 形式的 JSON
                ctype = resp.headers.get("content-type", "")
                if "json" in ctype:
                    data = resp.json()
                    if isinstance(data, dict):
                        d = data.get("data") if isinstance(data.get("data"), dict) else data
                        for key in ("lrc", "lyric", "lrctxt", "text"):
                            val = d.get(key) if isinstance(d, dict) else None
                            if isinstance(val, str) and val.strip():
                                return val
                    return ""
                return resp.text or ""
        except Exception:  # noqa: BLE001 - 歌词抓取失败不影响主流程
            return ""

    async def _get_lyrics(self, msg: str, n: int, source: str) -> dict[str, Any]:
        """按歌名+索引获取带时间轴的歌词（解析为句子列表）。"""
        res = await self._request({"msg": msg, "n": int(n)}, source)
        if not res["ok"]:
            return res
        d = res["data"]
        # 优先取内联歌词字段；QQ音乐通常仅给 viplrc 地址，需再抓一次
        raw = ""
        for key in ("lrctxt", "lrc", "lyric"):
            val = d.get(key)
            if isinstance(val, str) and val.strip():
                raw = val
                break
        if not raw:
            viplrc = d.get("viplrc")
            if isinstance(viplrc, str) and viplrc.startswith("http"):
                raw = await self._fetch_text(viplrc)
        lines = parse_lrc(raw)
        if not lines:
            return {"ok": False, "error": "未获取到带时间轴的歌词（可能为纯音乐或无歌词）"}
        return {
            "ok": True,
            "lines": lines,
            "name": d.get("name", ""),
            "singer": d.get("songname", ""),
        }

    async def _download(self, msg: str, n: int, source: str) -> dict[str, Any]:
        detail = await self._get_song(msg, n, source)
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
