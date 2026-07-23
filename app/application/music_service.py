"""音乐资源获取服务：调用妖狐音乐 API 搜索 / 获取 / 下载歌曲。

设计要点：
- 使用 httpx 的 **异步** 客户端发起请求；所有协程都在本服务持有的独立事件循环
  线程中执行，桥接层只需同步调用。
- 严格遵守接口 10 QPS 限制：用一个异步「最小间隔」限流器串行化所有出站请求。
- API Key 由用户在前端「资源获取」页填写，持久化于 SettingsStore。
- 支持多个曲库（source）：wy=网易云、qq=QQ音乐、kuwo=酷我音乐；QQ音乐可额外配置会员 Cookie
  以获取高品质音频。曲库随每次调用传入，Cookie 持久化于 SettingsStore。
- 下载的歌曲落地到 ``config.MUSIC_DIR``，可在「AI 翻唱」页直接选用。

所有对外方法都返回带 ``ok`` 字段的字典，便于前端统一处理成功/失败与错误提示。
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
from typing import Any
from urllib.parse import urlparse

import config
from infrastructure import paths
from infrastructure.storage import SettingsStore

# settings.json 中保存用户 API Key 的键名
_API_KEY_SETTING = "music_api_key"
# settings.json 中保存用户上次选择曲库的键名
_SOURCE_SETTING = "music_source"
# settings.json 中保存 QQ音乐会员 Cookie 的键名
_QQ_COOKIE_SETTING = "music_qq_cookie"
_KUWO_DEFAULT_SIZE = "lossless"
_KUWO_DOWNLOAD_SIZES = ("lossless", "exhigh", "SQ", "standard", "Standard")
_KUWO_RANGE_PROBE_BYTES = 4096
_KUWO_RANGE_CHUNK_BYTES = 2 * 1024 * 1024
_DOWNLOAD_CANDIDATE_MAX_SECONDS = 120.0
_LYRIC_SOURCE_TYPES = {"qq": "qq", "wy": "wy"}
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


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


# Content-Type → 音频扩展名映射（用于纠正下载文件的真实格式）
_CTYPE_EXT = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/m4a": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".m4a",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
    "audio/ogg": ".ogg",
    "application/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
}


def _ext_from_url(url: str) -> str | None:
    """从 URL 路径（忽略查询串）推断音频扩展名。"""
    path = re.sub(r"[?#].*$", "", url or "")
    m = re.search(r"\.([A-Za-z0-9]{1,5})$", path)
    if not m:
        return None
    ext = "." + m.group(1).lower()
    return ext if ext in config.AUDIO_EXTS else None


def _content_range_total(value: str) -> int:
    """解析 ``Content-Range: bytes 0-4095/33618441`` 中的总大小。"""
    m = re.search(r"/(\d+)\s*$", value or "")
    if not m:
        return 0
    try:
        return max(0, int(m.group(1)))
    except ValueError:
        return 0


def _sniff_audio_ext(head: bytes) -> str | None:
    """根据文件头魔数判断真实音频格式；非音频（HTML/JSON 等）返回 None。

    下载接口有时会把 ``.m4a`` / ``.flac`` 当成 ``.mp3`` 下发，或在 VIP / 失效时
    返回一段 HTML/JSON 错误体。靠扩展名判断会让后续解码器（如 mp3 专用解码器）
    读到「junk」而报错，这里改用文件头精确识别真实容器格式。
    """
    if not head:
        return None
    if head[:3] == b"ID3" or (len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return ".mp3"
    if head[:4] == b"fLaC":
        return ".flac"
    if head[:4] == b"OggS":
        return ".ogg"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return ".wav"
    # ISO BMFF（mp4 / m4a / aac 容器）：第 4-8 字节为 'ftyp'
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return ".m4a"
    return None


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


def _lyric_candidates(data: dict[str, Any]) -> list[str]:
    """按妖狐音乐接口的正式响应结构提取歌词候选。"""
    music = data.get("music")
    nested = music if isinstance(music, dict) else {}
    lyric = data.get("lyric")
    nested_lyric = lyric if isinstance(lyric, dict) else {}
    values = (
        data.get("lrctxt"),
        data.get("lrc"),
        # 酷我单曲接口会返回 data.lyric.lrc / data.lyric.lrclist。
        nested_lyric.get("lrctxt"),
        nested_lyric.get("lrc"),
        nested_lyric.get("lrcurl"),
        nested_lyric.get("viplrc"),
        nested.get("lrcurl"),
        nested.get("lrc"),
        # 部分历史响应曾将 lrcurl 放在 data 顶层，保留兼容。
        data.get("lrcurl"),
        data.get("viplrc"),
        lyric if isinstance(lyric, str) else "",
    )
    return [value.strip() for value in values if isinstance(value, str) and value.strip()]


def _lines_from_kuwo_lrclist(data: dict[str, Any]) -> list[dict[str, Any]]:
    """把酷我 data.lyric.lrclist 转成前端统一使用的 ``[{time, text}]``。"""
    lyric = data.get("lyric")
    nested_lyric = lyric if isinstance(lyric, dict) else {}
    lrclist = nested_lyric.get("lrclist") or data.get("lrclist")
    if not isinstance(lrclist, list):
        return []

    lines: list[dict[str, Any]] = []
    for item in lrclist:
        if not isinstance(item, dict):
            continue
        text = str(item.get("lineLyric") or item.get("text") or "").strip()
        if not text:
            continue
        try:
            seconds = float(item.get("time") or item.get("startTime") or 0)
        except (TypeError, ValueError):
            continue
        lines.append({"time": round(max(0.0, seconds), 3), "text": text})
    lines.sort(key=lambda x: x["time"])
    return lines


def _song_mid(data: dict[str, Any]) -> str:
    """从妖狐歌曲详情中提取聚合歌词接口所需的歌曲 ID。"""
    music = data.get("music")
    nested = music if isinstance(music, dict) else {}
    for value in (
        data.get("mid"),
        data.get("songmid"),
        data.get("rid"),
        nested.get("mid"),
        nested.get("rid"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()

    for raw in (data.get("html"), data.get("picture"), data.get("url")):
        if not isinstance(raw, str) or not raw.strip():
            continue
        parsed = urlparse(raw.strip())
        parts = [part for part in parsed.path.split("/") if part]
        try:
            index = parts.index("songDetail")
        except ValueError:
            index = -1
        if index >= 0 and index + 1 < len(parts):
            return parts[index + 1]
        m = re.search(r"(?:^|[?&])rid=([^&#]+)", parsed.query)
        if m:
            return m.group(1)
    return ""


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

    def search(
        self,
        msg: str,
        page: int = 1,
        page_size: int = 15,
        source: str | None = None,
    ) -> dict[str, Any]:
        return self._submit(
            self._search(
                msg, int(page or 1), int(page_size or 15), self._normalize_source(source)
            )
        )

    def get_song(
        self,
        msg: str,
        n: int,
        source: str | None = None,
        song_id: str | None = None,
    ) -> dict[str, Any]:
        return self._submit(
            self._get_song(msg, n, self._normalize_source(source), song_id=song_id)
        )

    def download(
        self,
        msg: str,
        n: int,
        source: str | None = None,
        song_id: str | None = None,
    ) -> dict[str, Any]:
        return self._submit(
            self._download(msg, n, self._normalize_source(source), song_id=song_id)
        )

    def preview(
        self,
        msg: str,
        n: int,
        source: str | None = None,
        song_id: str | None = None,
    ) -> dict[str, Any]:
        """获取在线试听地址；酷我经后端代理为 data URI。"""
        return self._submit(
            self._preview(msg, n, self._normalize_source(source), song_id=song_id)
        )

    def get_lyrics(
        self,
        msg: str,
        n: int,
        source: str | None = None,
        song_id: str | None = None,
    ) -> dict[str, Any]:
        return self._submit(
            self._get_lyrics(msg, n, self._normalize_source(source), song_id=song_id)
        )

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

    async def _search(
        self, msg: str, page: int, page_size: int, source: str
    ) -> dict[str, Any]:
        if not (msg or "").strip():
            return {"ok": False, "error": "请输入搜索关键词"}
        params: dict[str, Any] = {"msg": msg}
        # QQ 音乐当前不接收 g；网易云与酷我可用 g 控制搜索数量。
        if source in {"wy", "kuwo"}:
            params["g"] = max(1, min(50, int(page_size or 15)))
        res = await self._request(params, source)
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
                # 酷我返回 rid，可用于聚合歌词接口（type=kw）。
                "rid": s.get("rid", ""),
                "subtitle": s.get("subtitle", ""),
            }
            for s in songs
            if isinstance(s, dict) and s.get("n") is not None
        ]
        return {
            "ok": True,
            "songs": items,
            "keyword": msg,
            "source": source,
            "page": 1,
            "page_size": len(items),
            "has_more": False,
        }

    async def _get_song(
        self,
        msg: str,
        n: int,
        source: str,
        song_id: str | None = None,
        size: str | None = None,
    ) -> dict[str, Any]:
        # 酷我音频直链在 msg+n 单曲响应的 data.vipmusic.url；action=song 常拿不到 URL。
        if source == "kuwo":
            params: dict[str, Any] = {
                "msg": msg,
                "n": int(n),
                "size": size or _KUWO_DEFAULT_SIZE,
            }
        else:
            params = {"msg": msg, "n": int(n)}
        res = await self._request(params, source)
        if not res["ok"]:
            return res
        d = res["data"]
        vipmusic = d.get("vipmusic") if isinstance(d.get("vipmusic"), dict) else {}
        vip_url = str(vipmusic.get("url") or "").strip()
        song = {
            "name": d.get("name", ""),
            # 免费接口使用 songname，QQ Plus 使用 singer。
            "singer": d.get("songname") or d.get("singer") or "",
            "album": d.get("album", ""),
            "title": d.get("songtitle", ""),
            "picture": d.get("picture", ""),
            "url": d.get("url") or vip_url,
            "musicurl": d.get("musicurl") or vip_url,
            "vipmusicurl": d.get("vipmusicurl") or vip_url,
            "lrc": next(iter(_lyric_candidates(d)), ""),
            "rid": _song_mid(d) or str(song_id or "").strip(),
            "format": d.get("format") or vipmusic.get("format", ""),
            "quality": vipmusic.get("leveltext") or vipmusic.get("level", ""),
        }
        return {"ok": True, "song": song}

    async def _fetch_text(self, url: str) -> str:
        """抓取歌词 URL 返回的文本或 JSON 内容。"""
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
                        if isinstance(d, dict):
                            candidates = _lyric_candidates(d)
                            if candidates:
                                return candidates[0]
                            text = d.get("text")
                            if isinstance(text, str) and text.strip():
                                return text.strip()
                    return ""
                return resp.text or ""
        except Exception:  # noqa: BLE001 - 歌词抓取失败不影响主流程
            return ""

    async def _resolve_lyric_candidate(self, candidate: str) -> str:
        """解析内联歌词或最多三次歌词 URL 跳转。"""
        raw = candidate.strip()
        visited: set[str] = set()
        for _ in range(3):
            if not raw.startswith(("http://", "https://")):
                return raw
            if raw in visited:
                return ""
            visited.add(raw)
            raw = (await self._fetch_text(raw)).strip()
        return "" if raw.startswith(("http://", "https://")) else raw

    async def _fetch_aggregate_lyrics(self, mid: str, source: str) -> str:
        """调用妖狐聚合歌词接口，供不直接返回歌词的曲库使用。"""
        lyric_type = _LYRIC_SOURCE_TYPES.get(source)
        if not mid or not lyric_type:
            return ""
        try:
            import httpx
        except ImportError:
            return ""

        await self._limiter.wait()
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.get(
                    f"{config.MUSIC_API_BASE}/lrc",
                    params={"key": self.get_api_key(), "mid": mid, "type": lyric_type},
                )
                payload = resp.json()
        except Exception:  # noqa: BLE001 - 聚合歌词失败后仍可返回统一的无歌词提示
            return ""
        if not isinstance(payload, dict) or payload.get("code") != 200:
            return ""
        data = payload.get("data")
        if not isinstance(data, dict):
            return ""
        candidates = _lyric_candidates(data)
        return candidates[0] if candidates else ""

    async def _resolve_kuwo_rid_from_search(self, msg: str, n: int) -> str:
        """酷我单曲响应有时不回传 rid；需要时回查搜索列表获取。"""
        try:
            limit = max(1, min(50, int(n or 1)))
        except (TypeError, ValueError):
            limit = 1
        res = await self._request({"msg": msg, "g": max(13, limit)}, "kuwo")
        if not res.get("ok"):
            return ""
        songs = (res.get("data") or {}).get("songs") or []
        for item in songs:
            if not isinstance(item, dict):
                continue
            try:
                same_index = int(item.get("n") or 0) == int(n)
            except (TypeError, ValueError):
                same_index = False
            if same_index and str(item.get("rid") or "").strip():
                return str(item.get("rid")).strip()
        try:
            fallback = songs[int(n) - 1]
        except (IndexError, TypeError, ValueError):
            return ""
        return str(fallback.get("rid") or "").strip() if isinstance(fallback, dict) else ""

    async def _parse_lyric_lines_from_data(
        self,
        data: dict[str, Any],
        *,
        resolve_urls: bool = True,
    ) -> list[dict[str, Any]]:
        """从单曲/歌词响应中解析时间轴歌词。"""
        seen: set[str] = set()
        for candidate in _lyric_candidates(data):
            if candidate in seen:
                continue
            seen.add(candidate)
            text = candidate
            if resolve_urls:
                text = await self._resolve_lyric_candidate(candidate)
            elif text.startswith(("http://", "https://")):
                # 酷我歌词在单曲响应里直接给出，若偶发返回 URL，不在这里按 QQ/网易云方式追链。
                continue
            lines = parse_lrc(text)
            if lines:
                return lines
        return _lines_from_kuwo_lrclist(data)

    def _lyrics_result(
        self,
        data: dict[str, Any],
        lines: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "lines": lines,
            "name": data.get("name", ""),
            "singer": data.get("songname") or data.get("singer") or "",
        }

    async def _get_kuwo_lyrics(
        self,
        msg: str,
        n: int,
        song_id: str | None = None,
    ) -> dict[str, Any]:
        """酷我歌词直接来自单曲响应 data.lyric，不走 /lrc 聚合歌词接口。"""
        rid = str(song_id or "").strip()

        if rid:
            res = await self._request(
                {"action": "song", "id": rid, "size": _KUWO_DEFAULT_SIZE},
                "kuwo",
            )
            if not res["ok"]:
                return res
            data = res["data"]
            lines = await self._parse_lyric_lines_from_data(data, resolve_urls=False)
            if lines:
                return self._lyrics_result(data, lines)
            return {"ok": False, "error": "酷我接口未返回可用的 lyric.lrc / lyric.lrclist 歌词"}

        res = await self._request(
            {"msg": msg, "n": int(n), "size": _KUWO_DEFAULT_SIZE},
            "kuwo",
        )
        if not res["ok"]:
            return res
        data = res["data"]
        lines = await self._parse_lyric_lines_from_data(data, resolve_urls=False)
        if lines:
            return self._lyrics_result(data, lines)

        rid = _song_mid(data) or await self._resolve_kuwo_rid_from_search(msg, n)
        if rid:
            res = await self._request(
                {"action": "song", "id": rid, "size": _KUWO_DEFAULT_SIZE},
                "kuwo",
            )
            if res["ok"]:
                data = res["data"]
                lines = await self._parse_lyric_lines_from_data(
                    data, resolve_urls=False
                )
                if lines:
                    return self._lyrics_result(data, lines)

        return {"ok": False, "error": "酷我接口未返回可用的 lyric.lrc / lyric.lrclist 歌词"}

    async def _get_lyrics(
        self,
        msg: str,
        n: int,
        source: str,
        song_id: str | None = None,
    ) -> dict[str, Any]:
        """按歌名+索引获取带时间轴的歌词（解析为句子列表）。"""
        if source == "kuwo":
            return await self._get_kuwo_lyrics(msg, n, song_id=song_id)

        res = await self._request({"msg": msg, "n": int(n)}, source)
        if not res["ok"]:
            return res
        d = res["data"]
        # 网易响应提供 data.lrctxt/data.lrc，并可能在 data.music.lrcurl 放备用地址。
        # QQ 免费接口不直接返回歌词，下面会再通过歌曲 mid 调用官方聚合歌词接口。
        lines = await self._parse_lyric_lines_from_data(d)
        if not lines:
            mid = str(song_id or "").strip() or _song_mid(d)
            aggregate = await self._fetch_aggregate_lyrics(mid, source)
            if aggregate:
                lines = parse_lrc(await self._resolve_lyric_candidate(aggregate))
        if not lines:
            return {"ok": False, "error": "未获取到带时间轴的歌词（可能为纯音乐或无歌词）"}
        return self._lyrics_result(d, lines)

    async def _download(
        self,
        msg: str,
        n: int,
        source: str,
        song_id: str | None = None,
    ) -> dict[str, Any]:
        # 酷我按 msg+n 返回的单曲响应里，真实音频直链在 data.vipmusic.url。
        # 这里首选 lossless/default，避免先请求其它音质拿不到 URL 后提前失败。
        initial_size = _KUWO_DEFAULT_SIZE if source == "kuwo" else None
        detail = await self._get_song(
            msg, n, source, song_id=song_id, size=initial_size
        )
        if not detail.get("ok"):
            return detail
        song = detail["song"]
        urls = self._song_audio_urls(song)
        if not urls and source != "kuwo":
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

        # 真实扩展名按「文件头魔数 > Content-Type > URL 后缀 > .mp3」优先级判定，
        # 避免把 m4a/flac 误存成 .mp3 导致后续 mp3 专用解码器读到 junk 而失败。
        tmp = config.MUSIC_DIR / f".{base}.part"

        last_error = ""
        success: dict[str, Any] | None = None
        tested_urls: set[str] = set()
        timeout = httpx.Timeout(60.0, connect=20.0, read=30.0, write=20.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            for url in urls:
                tested_urls.add(url)
                result = await self._download_candidate(client, url, tmp, source)
                if result.get("ok"):
                    success = result
                    break
                last_error = str(result.get("error") or last_error)
            if not success and source == "kuwo":
                # 酷我音频直链在 data.vipmusic.url；若当前响应没有 URL，或直链下载失败，
                # 再依次换音质重新取单曲响应，继续读取 vipmusic.url。
                for size in _KUWO_DOWNLOAD_SIZES:
                    detail = await self._get_song(
                        msg,
                        n,
                        source,
                        song_id=song_id or song.get("rid"),
                        size=size,
                    )
                    if not detail.get("ok"):
                        last_error = str(detail.get("error") or last_error)
                        continue
                    for url in self._song_audio_urls(detail.get("song") or {}):
                        if url in tested_urls:
                            continue
                        tested_urls.add(url)
                        result = await self._download_candidate(client, url, tmp, source)
                        if result.get("ok"):
                            success = result
                            song = detail["song"]
                            base = song.get("name", "") or base
                            if song.get("singer"):
                                base = f"{base} - {song['singer']}"
                            base = _sanitize_filename(base)
                            break
                        last_error = str(result.get("error") or last_error)
                    if success:
                        break

        if not success:
            if len(urls) > 1:
                return {
                    "ok": False,
                    "error": last_error or "两个音频地址均不可播放，不能下载",
                }
            return {
                "ok": False,
                "error": last_error or "该资源无法播放，不能下载",
            }

        ext = str(success.get("ext") or ".mp3")

        dest = config.MUSIC_DIR / f"{base}{ext}"
        idx = 1
        while dest.exists():
            dest = config.MUSIC_DIR / f"{base} ({idx}){ext}"
            idx += 1
        try:
            tmp.replace(dest)
        except OSError as exc:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return {"ok": False, "error": f"保存文件失败：{exc}"}

        return {
            "ok": True,
            "path": str(dest),
            "name": dest.stem,
            "size": paths.file_size_label(dest),
        }

    async def _preview(
        self,
        msg: str,
        n: int,
        source: str,
        song_id: str | None = None,
    ) -> dict[str, Any]:
        """获取在线试听地址。

        酷我 CDN 需 ``Referer`` 等请求头且不支持跨域，浏览器 ``<audio>`` 无法
        直连，因此后端下载后转码为短时低码率 mp3，以 data URI 返回；其它曲库
        的直链可由浏览器直接播放，无需代理。
        """
        if source != "kuwo":
            detail = await self._get_song(msg, n, source, song_id=song_id)
            if not detail.get("ok"):
                return detail
            urls = self._song_audio_urls(detail.get("song") or {})
            if not urls:
                return {"ok": False, "error": "无法获取试听地址（可能为 VIP / 无版权歌曲）"}
            return {"ok": True, "src": urls[0]}

        return await self._preview_kuwo(msg, n, song_id)

    async def _preview_kuwo(
        self,
        msg: str,
        n: int,
        song_id: str | None = None,
    ) -> dict[str, Any]:
        """酷我试听：用 ffmpeg 直接从音频 URL 截取前 45 秒转码为 mp3 data URI。

        酷我 CDN 需 ``Referer`` 等请求头且不支持跨域，浏览器 ``<audio>`` 无法
        直连。这里用 ffmpeg 自带 HTTP 选项（``-headers``）带上所需请求头，直接
        从网络流截取前 45 秒并转码为 128kbps mp3——无需下载完整无损文件，试听
        响应只需几秒。ffmpeg 不可用时回退到 httpx 下载 + 原文件 base64。
        """
        # 试听优先请求较低音质（文件小、下载快），拿不到 URL 再回退其它音质。
        urls: list[str] = []
        seen_sizes: set[str] = set()
        for size in ("exhigh", *_KUWO_DOWNLOAD_SIZES):
            if size in seen_sizes:
                continue
            seen_sizes.add(size)
            detail = await self._get_song(
                msg, n, "kuwo", song_id=song_id, size=size
            )
            if not detail.get("ok"):
                continue
            urls = self._song_audio_urls(detail.get("song") or {})
            if urls:
                break
        if not urls:
            return {"ok": False, "error": "无法获取试听地址（可能为 VIP / 无版权歌曲）"}

        # 首选：ffmpeg 直接从 URL 截取前 45 秒，避免下载完整文件。
        for url in urls:
            src = await self._ffmpeg_url_to_data_uri(url, "kuwo")
            if src:
                return {"ok": True, "src": src}

        # 回退：httpx 下载完整文件后转码 / base64。
        return await self._preview_kuwo_fallback(urls)

    async def _preview_kuwo_fallback(
        self, urls: list[str]
    ) -> dict[str, Any]:
        """ffmpeg 直连失败时的回退：httpx 下载完整文件再转码。"""
        import tempfile
        from pathlib import Path

        try:
            import httpx
        except ImportError:
            return {"ok": False, "error": "缺少 httpx 依赖，请重新安装运行环境"}

        fd, tmp_name = tempfile.mkstemp(prefix="xb-preview-", suffix=".part")
        try:
            os.close(fd)
        except OSError:
            pass
        tmp = Path(tmp_name)
        timeout = httpx.Timeout(60.0, connect=20.0, read=30.0, write=20.0, pool=10.0)
        last_error = ""
        downloaded = False
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            for url in urls:
                result = await self._download_candidate(client, url, tmp, "kuwo")
                if result.get("ok"):
                    downloaded = True
                    break
                last_error = str(result.get("error") or last_error)

        if not downloaded:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return {
                "ok": False,
                "error": last_error or "试听文件下载失败，可能为 VIP / 无版权 / 链接失效",
            }

        src = await asyncio.to_thread(self._audio_file_to_data_uri, tmp)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        if not src:
            return {"ok": False, "error": "试听转码失败，请确认已安装 ffmpeg"}
        return {"ok": True, "src": src}

    async def _ffmpeg_url_to_data_uri(self, url: str, source: str = "") -> str:
        """用 ffmpeg 直接从 URL 截取前 45 秒转码为 128kbps mp3 data URI。

        通过 ``-headers`` 带上酷我 CDN 所需的 Referer / UA 等请求头，ffmpeg
        自行处理 HTTP 下载与解码，只取前 45 秒——无需下载完整文件。subprocess
        在线程池中执行，避免阻塞事件循环。
        """
        return await asyncio.to_thread(self._ffmpeg_url_to_data_uri_sync, url, source)

    @staticmethod
    def _ffmpeg_url_to_data_uri_sync(url: str, source: str = "") -> str:
        """``_ffmpeg_url_to_data_uri`` 的同步实现（在线程池中调用）。"""
        import base64
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return ""

        headers = MusicService._download_headers(url, source)
        # ffmpeg -headers 需要每行一个 header，用 \r\n 分隔
        header_str = "".join(f"{k}: {v}\r\n" for k, v in headers.items())

        out_fd, out_name = tempfile.mkstemp(prefix="xb-preview-", suffix=".mp3")
        try:
            os.close(out_fd)
        except OSError:
            pass
        out = Path(out_name)
        try:
            res = subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-headers",
                    header_str,
                    "-reconnect",
                    "1",
                    "-reconnect_streamed",
                    "1",
                    "-reconnect_at_eof",
                    "1",
                    "-reconnect_delay_max",
                    "5",
                    "-i",
                    url,
                    "-t",
                    "45",
                    "-b:a",
                    "128k",
                    "-ac",
                    "2",
                    "-ar",
                    "44100",
                    "-f",
                    "mp3",
                    str(out),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                **config.subprocess_no_window(),
            )
            if res.returncode == 0 and out.exists() and out.stat().st_size > 0:
                data = out.read_bytes()
                if data:
                    return "data:audio/mpeg;base64," + base64.b64encode(data).decode(
                        "ascii"
                    )
        except (OSError, subprocess.SubprocessError):
            pass
        finally:
            try:
                out.unlink(missing_ok=True)
            except OSError:
                pass
        return ""

    @staticmethod
    def _audio_file_to_data_uri(src_path: Any) -> str:
        """将本地音频文件转码为 45 秒 128kbps mp3 data URI；失败返回空串。

        无 ffmpeg 时，若源文件不超过 4MB 则直接 base64 编码原文件，否则放弃
        （data URI 过大会拖慢甚至撑爆 pywebview 桥接）。
        """
        import base64
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path

        src = Path(src_path)
        if not src.exists():
            return ""

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            out_fd, out_name = tempfile.mkstemp(prefix="xb-preview-", suffix=".mp3")
            try:
                os.close(out_fd)
            except OSError:
                pass
            out = Path(out_name)
            try:
                res = subprocess.run(
                    [
                        ffmpeg,
                        "-y",
                        "-t",
                        "45",
                        "-i",
                        str(src),
                        "-b:a",
                        "128k",
                        "-ac",
                        "2",
                        "-ar",
                        "44100",
                        "-f",
                        "mp3",
                        str(out),
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=60,
                    **config.subprocess_no_window(),
                )
                if res.returncode == 0 and out.exists() and out.stat().st_size > 0:
                    data = out.read_bytes()
                    if data:
                        return "data:audio/mpeg;base64," + base64.b64encode(data).decode(
                            "ascii"
                        )
            except (OSError, subprocess.SubprocessError):
                pass
            finally:
                try:
                    out.unlink(missing_ok=True)
                except OSError:
                    pass

        # 无 ffmpeg：仅小文件直接 base64
        try:
            size = src.stat().st_size
        except OSError:
            return ""
        if size > 4 * 1024 * 1024:
            return ""
        try:
            data = src.read_bytes()
        except OSError:
            return ""
        mime = {
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".aac": "audio/aac",
            ".flac": "audio/flac",
            ".ogg": "audio/ogg",
            ".wav": "audio/wav",
        }.get(src.suffix.lower(), "audio/mpeg")
        return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")

    async def _download_candidate(
        self,
        client: Any,
        url: str,
        tmp,
        source: str = "",
    ) -> dict[str, Any]:
        """尝试下载并校验一个候选播放地址。失败时清理半成品并返回原因。"""

        def fail(message: str) -> dict[str, Any]:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return {"ok": False, "error": message}

        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            return {"ok": False, "error": "无法清理上一次下载临时文件"}

        url_ext = _ext_from_url(url)
        await self._limiter.wait()
        try:
            start = asyncio.get_running_loop().time()
            if self._use_range_download(url, source):
                ranged = await self._download_by_ranges(client, url, tmp, source, start)
                if ranged.get("ok"):
                    ctype = str(ranged.get("ctype") or "")
                    head = bytes(ranged.get("head") or b"")
                elif ranged.get("fallback"):
                    try:
                        tmp.unlink(missing_ok=True)
                    except OSError:
                        pass
                    ctype, head = await self._stream_download(
                        client, url, tmp, source, start
                    )
                else:
                    return fail(str(ranged.get("error") or "下载失败"))
            else:
                ctype, head = await self._stream_download(client, url, tmp, source, start)
        except Exception as exc:  # noqa: BLE001 - 候选地址失败后继续测试下一个地址
            return fail(f"下载失败：{exc}")

        # 校验确实是「可以听」的音频：
        # 1) 文件头魔数 / Content-Type 必须指向音频（HTML/JSON 错误体一律拒绝；
        #    URL 后缀不可单独采信——失效链接也常是 .mp3 结尾却返回错误页）；
        # 2) 文件体量过小基本是错误响应；
        # 3) 有 ffprobe 时进一步探测可解码且时长>0，确认确实能播放。
        sniff_ext = _sniff_audio_ext(head)
        ctype_ext = _CTYPE_EXT.get(ctype)
        size = tmp.stat().st_size if tmp.exists() else 0

        if sniff_ext is None and ctype_ext is None:
            return fail("该资源无法播放，不能下载（可能为 VIP / 无版权 / 链接失效）")
        if size < 16 * 1024:
            return fail("该资源无法播放，不能下载（返回内容过小，疑似失效链接）")

        if not self._probe_playable(tmp):
            return fail("该资源无法播放，不能下载（音频无法解码）")

        return {"ok": True, "url": url, "ext": sniff_ext or ctype_ext or url_ext or ".mp3"}

    @staticmethod
    def _use_range_download(url: str, source: str = "") -> bool:
        """酷我 CDN 对浏览器音频常用 Range 请求；分段下载比长连接更稳。"""
        host = urlparse(url or "").netloc.lower()
        return source == "kuwo" or "kuwo.cn" in host or "kwcdn" in host

    @staticmethod
    def _check_download_deadline(start: float) -> None:
        if asyncio.get_running_loop().time() - start > _DOWNLOAD_CANDIDATE_MAX_SECONDS:
            raise TimeoutError("下载超时，已切换其它音质或返回失败")

    async def _stream_download(
        self,
        client: Any,
        url: str,
        tmp,
        source: str,
        start: float,
    ) -> tuple[str, bytes]:
        """普通整文件流式下载，作为非酷我和不支持 Range 的兜底路径。"""
        async with client.stream(
            "GET",
            url,
            headers=self._download_headers(url, source),
        ) as resp:
            resp.raise_for_status()
            ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
            head = b""
            written = 0
            with tmp.open("wb") as f:
                async for chunk in resp.aiter_bytes(65536):
                    if not chunk:
                        continue
                    if len(head) < 16:
                        head += chunk[: 16 - len(head)]
                    f.write(chunk)
                    written += len(chunk)
                    self._check_download_deadline(start)
        if written <= 0:
            raise RuntimeError("未收到音频数据")
        return ctype, head

    async def _download_by_ranges(
        self,
        client: Any,
        url: str,
        tmp,
        source: str,
        start: float,
    ) -> dict[str, Any]:
        """酷我专用 Range 分段下载；不支持 Range 时让上层回退普通下载。"""
        headers = self._download_headers(url, source)
        probe_headers = {
            **headers,
            "Range": f"bytes=0-{_KUWO_RANGE_PROBE_BYTES - 1}",
        }
        try:
            async with client.stream("GET", url, headers=probe_headers) as resp:
                if resp.status_code != 206:
                    return {"ok": False, "fallback": True}
                resp.raise_for_status()
                ctype = (
                    (resp.headers.get("content-type") or "")
                    .split(";")[0]
                    .strip()
                    .lower()
                )
                total = _content_range_total(resp.headers.get("content-range") or "")
                if total <= 0:
                    return {"ok": False, "fallback": True}
                head = b""
                written = 0
                with tmp.open("wb") as f:
                    async for chunk in resp.aiter_bytes(65536):
                        if not chunk:
                            continue
                        if len(head) < 16:
                            head += chunk[: 16 - len(head)]
                        f.write(chunk)
                        written += len(chunk)
                        self._check_download_deadline(start)

            if written <= 0:
                return {"ok": False, "error": "酷我 CDN 未返回音频数据"}

            offset = written
            while offset < total:
                end = min(offset + _KUWO_RANGE_CHUNK_BYTES - 1, total - 1)
                chunk_headers = {**headers, "Range": f"bytes={offset}-{end}"}
                piece = 0
                async with client.stream("GET", url, headers=chunk_headers) as resp:
                    if resp.status_code != 206:
                        return {
                            "ok": False,
                            "error": "酷我 CDN 中断了分段下载，请换一首或稍后重试",
                        }
                    resp.raise_for_status()
                    range_total = _content_range_total(
                        resp.headers.get("content-range") or ""
                    )
                    if range_total and range_total != total:
                        return {"ok": False, "error": "酷我 CDN 返回的文件大小不一致"}
                    with tmp.open("ab") as f:
                        async for chunk in resp.aiter_bytes(65536):
                            if not chunk:
                                continue
                            f.write(chunk)
                            piece += len(chunk)
                            self._check_download_deadline(start)
                if piece <= 0:
                    return {"ok": False, "error": "酷我 CDN 分段下载无数据"}
                offset += piece

            if tmp.stat().st_size != total:
                return {"ok": False, "error": "酷我 CDN 分段文件大小不完整"}
            return {"ok": True, "ctype": ctype, "head": head}
        except Exception as exc:  # noqa: BLE001 - 上层会继续尝试其它音质
            return {"ok": False, "error": f"下载失败：{exc}"}

    @staticmethod
    def _download_headers(url: str, source: str = "") -> dict[str, str]:
        headers = {
            "User-Agent": _BROWSER_UA,
            "Accept": "audio/*,*/*;q=0.8",
        }
        if source == "kuwo" or "kuwo" in url.lower():
            headers.update(
                {
                    "Referer": "https://www.kuwo.cn/",
                    "Sec-Fetch-Dest": "audio",
                    "Sec-Fetch-Mode": "no-cors",
                    "Sec-Fetch-Site": "cross-site",
                }
            )
        return headers

    @staticmethod
    def _song_audio_urls(song: dict[str, Any]) -> list[str]:
        urls: list[str] = []
        for key in ("vipmusicurl", "musicurl", "url"):
            value = str(song.get(key) or "").strip()
            if value and value not in urls:
                urls.append(value)
        return urls

    @staticmethod
    def _probe_playable(path) -> bool:
        """用 ffprobe 探测音频是否可解码且时长>0；拿不到 ffprobe 则视为通过。"""
        import shutil
        import subprocess

        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return True  # 无 ffprobe 时不阻断（魔数/Content-Type 已过滤非音频）
        try:
            out = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                **config.subprocess_no_window(),
            )
            val = (out.stdout or "").strip()
            return bool(val) and float(val) > 0.1
        except (OSError, subprocess.SubprocessError, ValueError):
            return False
