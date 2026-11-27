"""本地音频流服务（播放器直通输出）。

``<audio>`` 需要一个可随机读取的地址：拖动进度依赖 HTTP Range，而整首 WAV
编码成 data URI 既占内存也拖慢切换。本模块在回环地址上启动一个只读的
HTTP 服务，把「已登记」的本地文件或远程音频代理成带鉴权 token 的地址。

设计要点：

- 只监听 ``127.0.0.1``，端口随机；地址带不可猜测的 token。
- 本地文件按路径 + 大小 + mtime 去重，登记表只接受确实存在的文件。
- 远程音频（在线曲库）按需透传 Range，避免先把整首无损歌曲下载到磁盘。
- 响应带 CORS 头，使前端 Web Audio（均衡器 / 电平）可以读取同一路音频。
- 服务惰性启动，桌面进程退出时由 ``stop()`` 关闭。
"""

from __future__ import annotations

import hashlib
import hmac
import mimetypes
import secrets
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

_CHUNK_BYTES = 256 * 1024

# 浏览器对 WAV 的 MIME 比较挑剔：部分 ffmpeg 产物会被识别成
# application/octet-stream 而无法播放，这里显式补一份常见音频映射。
_MIME_BY_SUFFIX = {
    ".wav": "audio/wav",
    ".wave": "audio/wav",
    ".flac": "audio/flac",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".wma": "audio/x-ms-wma",
    ".aif": "audio/aiff",
    ".aiff": "audio/aiff",
}


def mime_for(path: Path) -> str:
    return _MIME_BY_SUFFIX.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _parse_range(header: str, size: int) -> tuple[int, int] | None:
    """解析单段 ``Range``，返回闭区间 ``(start, end)``；不合法返回 None。

    多段 Range 不在播放器场景内，按第一段处理。
    """
    raw = str(header or "").strip()
    if not raw.lower().startswith("bytes=") or size <= 0:
        return None
    spec = raw[6:].split(",", 1)[0].strip()
    if "-" not in spec:
        return None
    left, right = spec.split("-", 1)
    try:
        if left == "":
            length = int(right)
            if length <= 0:
                return None
            start = max(0, size - length)
            return start, size - 1
        start = int(left)
        end = int(right) if right else size - 1
    except ValueError:
        return None
    if start < 0 or start >= size or end < start:
        return None
    return start, min(end, size - 1)


class _AudioHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class LocalAudioStreamer:
    """把音频登记成 ``http://127.0.0.1:<port>/audio/<id>?token=...``。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._token = secrets.token_urlsafe(24)
        self._files: dict[str, Path] = {}
        self._remotes: dict[str, dict[str, Any]] = {}
        self._server: _AudioHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._port = 0

    # ---- 对外接口 ----
    def publish_file(self, path: Path, *, content_type: str = "") -> str:
        """登记本地音频并返回播放地址；文件不存在时返回空串。"""
        try:
            target = Path(path).resolve()
            stat = target.stat()
        except (OSError, ValueError):
            return ""
        if not target.is_file():
            return ""
        digest = hashlib.sha1(
            f"{str(target).lower()}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8")
        ).hexdigest()[:24]
        with self._lock:
            self._files[digest] = target
            self._remotes.pop(digest, None)
        return self._url(digest)

    def publish_remote(
        self,
        urls: list[str],
        headers: dict[str, str],
        *,
        content_type: str = "",
    ) -> str:
        """登记一组候选远程地址，由本机服务透传（含 Range）。"""
        candidates = [str(url).strip() for url in urls if str(url or "").strip()]
        if not candidates:
            return ""
        ident = uuid.uuid4().hex
        with self._lock:
            self._remotes[ident] = {
                "urls": candidates,
                "headers": {str(k): str(v) for k, v in (headers or {}).items()},
                "mime": content_type,
            }
            self._files.pop(ident, None)
        return self._url(ident)

    def stop(self) -> None:
        """关闭本地服务；可重复调用。"""
        with self._lock:
            server = self._server
            self._server = None
            self._thread = None
            self._files.clear()
            self._remotes.clear()
        if server is None:
            return
        try:
            server.shutdown()
        except OSError:
            pass
        try:
            server.server_close()
        except OSError:
            pass

    # ---- 内部 ----
    def _url(self, ident: str) -> str:
        self._ensure_server()
        with self._lock:
            port = self._port
        if not port:
            return ""
        return f"http://127.0.0.1:{port}/audio/{ident}?token={quote(self._token)}"

    def _ensure_server(self) -> None:
        with self._lock:
            if self._server is not None:
                return
            try:
                server = _AudioHTTPServer(("127.0.0.1", 0), _make_handler(self))
            except OSError:
                return
            server.daemon_threads = True
            thread = threading.Thread(
                target=server.serve_forever,
                name="xb-audio-stream",
                daemon=True,
            )
            thread.start()
            self._server = server
            self._thread = thread
            self._port = int(server.server_address[1])

    def _lookup(self, ident: str) -> tuple[str, Any]:
        with self._lock:
            path = self._files.get(ident)
            if path is not None:
                return "file", path
            remote = self._remotes.get(ident)
            if remote is not None:
                return "remote", dict(remote)
        return "", None

    def _token_ok(self, value: str) -> bool:
        try:
            return hmac.compare_digest(str(value or ""), self._token)
        except TypeError:
            return False


def _make_handler(owner: LocalAudioStreamer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "XBAudio/1.0"
        protocol_version = "HTTP/1.0"

        def log_message(self, *_args: Any) -> None:  # noqa: D401 - quiet server
            return

        def do_OPTIONS(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            self.send_response(204)
            self._send_cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_HEAD(self) -> None:  # noqa: N802
            self._serve(head_only=True)

        def do_GET(self) -> None:  # noqa: N802
            self._serve(head_only=False)

        # ---- 响应辅助 ----
        def _send_cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Range, Content-Type")
            self.send_header(
                "Access-Control-Expose-Headers",
                "Content-Length, Content-Range, Accept-Ranges, Content-Type",
            )
            self.send_header("Cross-Origin-Resource-Policy", "cross-origin")

        def _send_error_text(self, status: int, message: str) -> None:
            body = message.encode("utf-8")
            self.send_response(status)
            self._send_cors()
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

        def _serve(self, *, head_only: bool) -> None:
            parsed = urlparse(self.path)
            if parsed.path in ("/", "/health"):
                self._send_error_text(200, "ok")
                return
            if not parsed.path.startswith("/audio/"):
                self._send_error_text(404, "not found")
                return
            token = (parse_qs(parsed.query).get("token") or [""])[0]
            if not owner._token_ok(token):
                self._send_error_text(403, "forbidden")
                return
            ident = parsed.path[len("/audio/") :]
            kind, entry = owner._lookup(ident)
            if kind == "file":
                self._serve_file(Path(entry), head_only=head_only)
            elif kind == "remote":
                self._serve_remote(entry, head_only=head_only)
            else:
                self._send_error_text(404, "not found")

        def _serve_file(self, path: Path, *, head_only: bool) -> None:
            try:
                size = path.stat().st_size
                handle = path.open("rb")
            except OSError:
                self._send_error_text(404, "not found")
                return
            with handle:
                start, end = 0, max(0, size - 1)
                ranged = False
                header = self.headers.get("Range") or ""
                if header:
                    parsed = _parse_range(header, size)
                    if parsed is None:
                        self.send_response(416)
                        self._send_cors()
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    start, end = parsed
                    ranged = True
                length = max(0, end - start + 1)
                self.send_response(206 if ranged else 200)
                self._send_cors()
                self.send_header("Content-Type", mime_for(path))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(length))
                self.send_header("Cache-Control", "no-store")
                if ranged:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.end_headers()
                if head_only or length <= 0:
                    return
                handle.seek(start)
                remaining = length
                try:
                    while remaining > 0:
                        chunk = handle.read(min(_CHUNK_BYTES, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return

        def _serve_remote(self, entry: dict[str, Any], *, head_only: bool) -> None:
            try:
                import httpx
            except ImportError:
                self._send_error_text(503, "httpx unavailable")
                return

            urls: list[str] = list(entry.get("urls") or [])
            base_headers: dict[str, str] = dict(entry.get("headers") or {})
            range_header = self.headers.get("Range") or ""
            timeout = httpx.Timeout(30.0, connect=15.0, read=30.0, write=20.0)
            last_error = ""
            started = False
            client = None
            try:
                # 优先沿用系统代理设置；部分环境的 no_proxy 含 IPv6 写法会让
                # 旧版 httpx 解析失败，此时退回不读取代理环境的本机直连。
                client = httpx.Client(timeout=timeout, follow_redirects=True)
            except Exception:  # noqa: BLE001 - 代理环境解析失败时退化为直连
                try:
                    client = httpx.Client(
                        timeout=timeout, follow_redirects=True, trust_env=False
                    )
                except Exception as exc:  # noqa: BLE001
                    self._send_error_text(503, f"audio proxy unavailable: {exc}")
                    return
            with client:
                for url in urls:
                    headers = dict(base_headers)
                    if range_header:
                        headers["Range"] = range_header
                    try:
                        with client.stream("GET", url, headers=headers) as response:
                            if response.status_code >= 400:
                                last_error = f"HTTP {response.status_code}"
                                continue
                            status = 206 if response.status_code == 206 else 200
                            content_type = (
                                response.headers.get("content-type")
                                or str(entry.get("mime") or "")
                                or "application/octet-stream"
                            )
                            length = response.headers.get("content-length")
                            content_range = response.headers.get("content-range")
                            accept_ranges = response.headers.get("accept-ranges") or (
                                "bytes" if status == 206 else ""
                            )
                            self.send_response(status)
                            self._send_cors()
                            self.send_header("Content-Type", content_type)
                            if length:
                                self.send_header("Content-Length", length)
                            if content_range:
                                self.send_header("Content-Range", content_range)
                            if accept_ranges:
                                self.send_header("Accept-Ranges", accept_ranges)
                            self.send_header("Cache-Control", "no-store")
                            self.end_headers()
                            started = True
                            if head_only:
                                return
                            for chunk in response.iter_bytes(_CHUNK_BYTES):
                                self.wfile.write(chunk)
                            return
                    except (httpx.HTTPError, OSError) as exc:
                        last_error = str(exc) or exc.__class__.__name__
                        if started:
                            return
                        continue
            if not started:
                self._send_error_text(502, f"upstream unavailable: {last_error or 'unknown'}")

    return Handler
