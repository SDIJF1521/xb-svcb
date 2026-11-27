"""本机音频流服务单元测试：Range、鉴权与 CORS。"""

from __future__ import annotations

import threading
import urllib.error
import urllib.request
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from infrastructure.audio_streamer import LocalAudioStreamer, _parse_range


class _Repo:
    def __init__(self, path: Path) -> None:
        self._path = path

    def get(self, item_id: str):
        if item_id != "wrk_test":
            return None
        return {"output_path": str(self._path), "output": str(self._path)}


class _Ffmpeg:
    available = False

    def probe_audio(self, src: Path):
        return {
            "format": "wav",
            "codec": "pcm_s16le",
            "sample_rate": 8000,
            "channels": 1,
            "bit_depth": 16,
            "duration": 0.1,
        }

    def probe_duration(self, src: Path):
        return 0.1


def _write_wav(path: Path, frames: int = 800) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(bytes(range(256)) * (frames // 128))


def test_parse_range() -> None:
    assert _parse_range("bytes=0-99", 1000) == (0, 99)
    assert _parse_range("bytes=100-", 1000) == (100, 999)
    assert _parse_range("bytes=-100", 1000) == (900, 999)
    assert _parse_range("bytes=990-2000", 1000) == (990, 999)
    assert _parse_range("", 1000) is None
    assert _parse_range("bytes=1000-", 1000) is None
    assert _parse_range("bytes=abc-def", 1000) is None


def test_publish_file_serves_range_and_requires_token(tmp_path: Path) -> None:
    wav = tmp_path / "sample.wav"
    _write_wav(wav)
    expected = wav.read_bytes()

    streamer = LocalAudioStreamer()
    try:
        url = streamer.publish_file(wav)
        assert url.startswith("http://127.0.0.1:")
        assert "token=" in url

        with urllib.request.urlopen(url) as response:
            assert response.status == 200
            assert response.headers["Content-Type"] == "audio/wav"
            assert response.headers["Access-Control-Allow-Origin"] == "*"
            assert response.headers["Accept-Ranges"] == "bytes"
            assert response.read() == expected

        request = urllib.request.Request(url, headers={"Range": "bytes=10-19"})
        with urllib.request.urlopen(request) as response:
            assert response.status == 206
            assert response.read() == expected[10:20]
            assert response.headers["Content-Range"] == f"bytes 10-19/{len(expected)}"

        head = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(head) as response:
            assert response.status == 200
            assert response.headers["Content-Length"] == str(len(expected))

        with pytest.raises(urllib.error.HTTPError) as forbidden:
            urllib.request.urlopen(url.replace("token=", "token=wrong"))
        assert forbidden.value.code == 403

        missing = url.split("/audio/")[0] + "/audio/not-registered?token=" + url.split("token=")[1]
        with pytest.raises(urllib.error.HTTPError) as not_found:
            urllib.request.urlopen(missing)
        assert not_found.value.code == 404
    finally:
        streamer.stop()
        streamer.stop()  # 可重复关闭


def test_publish_missing_file_returns_empty(tmp_path: Path) -> None:
    streamer = LocalAudioStreamer()
    try:
        assert streamer.publish_file(tmp_path / "missing.wav") == ""
        assert streamer.publish_remote([], {}) == ""
    finally:
        streamer.stop()


def test_media_service_publishes_work_with_audio_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import config
    from application.media_service import MediaService

    monkeypatch.setattr(config, "WORKS_DIR", tmp_path)
    wav = tmp_path / "work.wav"
    _write_wav(wav)
    streamer = LocalAudioStreamer()
    service = MediaService(_Repo(wav), _Ffmpeg(), streamer=streamer)
    try:
        info = service.stream_work("wrk_test")
        assert info["ok"] is True
        assert info["format"] == "wav"
        assert info["sample_rate"] == 8000
        assert info["channels"] == 1
        assert info["bit_depth"] == 16
        assert info["lossless"] is True
        assert info["duration"] == 0.1
        with urllib.request.urlopen(info["url"]) as response:
            assert response.read() == wav.read_bytes()

        # 音乐目录之外的路径不能被当作已下载歌曲播放。
        assert service.stream_music(str(wav))["ok"] is False
    finally:
        service.shutdown()


def test_remote_proxy_forwards_range_and_headers() -> None:
    payload = b"0123456789"
    received: dict[str, str | None] = {}

    class _Upstream(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            received["range"] = self.headers.get("Range")
            received["referer"] = self.headers.get("Referer")
            start, end = 0, len(payload) - 1
            header = self.headers.get("Range") or ""
            if header.startswith("bytes="):
                left, _, right = header[6:].partition("-")
                start = int(left or 0)
                end = int(right) if right else end
            body = payload[start : end + 1]
            self.send_response(206 if header else 200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Accept-Ranges", "bytes")
            if header:
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(payload)}")
            self.end_headers()
            self.wfile.write(body)

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    source_url = f"http://127.0.0.1:{upstream.server_address[1]}/song.wav"

    streamer = LocalAudioStreamer()
    try:
        url = streamer.publish_remote([source_url], {"Referer": "https://example.test/"})
        assert url.startswith("http://127.0.0.1:")

        request = urllib.request.Request(url, headers={"Range": "bytes=2-5"})
        with urllib.request.urlopen(request) as response:
            assert response.status == 206
            assert response.read() == b"2345"
            assert response.headers["Content-Range"] == "bytes 2-5/10"
        assert received["range"] == "bytes=2-5"
        assert received["referer"] == "https://example.test/"
    finally:
        streamer.stop()
        upstream.shutdown()
        upstream.server_close()


