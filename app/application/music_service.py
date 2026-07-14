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

    async def _search(
        self, msg: str, page: int, page_size: int, source: str
    ) -> dict[str, Any]:
        if not (msg or "").strip():
            return {"ok": False, "error": "请输入搜索关键词"}
        # V2.1.3.8 起上游取消了 g 参数，传入未声明参数会直接返回 400。
        # 搜索数量改由上游决定，本地保留分页入参只为兼容现有桥接协议。
        res = await self._request({"msg": msg}, source)
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
            "vipmusicurl": d.get("vipmusicurl", ""),
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
        # 歌词字段可能是内联 LRC，也可能直接是歌词地址。
        raw = ""
        for key in ("lrctxt", "lrc", "lyric"):
            val = d.get(key)
            if isinstance(val, str) and val.strip():
                candidate = val.strip()
                raw = (
                    await self._fetch_text(candidate)
                    if candidate.startswith(("http://", "https://"))
                    else candidate
                )
                if raw:
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
        urls = self._song_audio_urls(song)
        if not urls:
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
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            for url in urls:
                result = await self._download_candidate(client, url, tmp)
                if result.get("ok"):
                    success = result
                    break
                last_error = str(result.get("error") or last_error)

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

    async def _download_candidate(self, client: Any, url: str, tmp) -> dict[str, Any]:
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
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
                head = b""
                with tmp.open("wb") as f:
                    async for chunk in resp.aiter_bytes(65536):
                        if len(head) < 16:
                            head += chunk[: 16 - len(head)]
                        f.write(chunk)
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
