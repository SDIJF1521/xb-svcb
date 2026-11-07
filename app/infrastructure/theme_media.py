"""主题背景媒体的本地存储（图片 / MP4 动态壁纸）。

原实现位于 ``api/bridge.py``，属于文件存储与转码能力，不应留在表现层。
这里只负责“把用户选择的媒体复制到数据目录并生成可回传的 data URI”，
由应用层 ``ThemeMediaService`` 编排。
"""

from __future__ import annotations

import base64
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import config
from infrastructure import paths

# 支持的图片容器与其扩展名 / MIME 映射。
IMAGE_FORMATS: dict[str, tuple[str, str]] = {
    "jpeg": (".jpg", "image/jpeg"),
    "png": (".png", "image/png"),
    "webp": (".webp", "image/webp"),
    "gif": (".gif", "image/gif"),
    "avif": (".avif", "image/avif"),
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".heic", ".heif"}

# Data URI 需要经过 pywebview JS 桥传输，管理的高清背景图需要保持紧凑。
IMAGE_OPTIMIZE_THRESHOLD = 2 * 1024 * 1024
MAX_VIDEO_BYTES = 200 * 1024 * 1024

MIME_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".avif": "image/avif",
    ".mp4": "video/mp4",
}


def sniff_image_format(path: Path) -> str:
    """按文件内容而不是后缀识别图片容器。"""
    try:
        with path.open("rb") as stream:
            head = stream.read(64)
    except OSError:
        return ""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if len(head) >= 12 and head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "webp"
    if len(head) >= 16 and head[4:8] == b"ftyp":
        brands = {head[index:index + 4].lower() for index in range(8, min(len(head) - 3, 36), 4)}
        if brands & {b"avif", b"avis"}:
            return "avif"
        if brands & {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}:
            return "heif"
    return ""


def _transcode_image(src: Path, dst: Path) -> bool:
    """把超大 / 非常规图片压成 1080p WebP。"""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(src),
                "-frames:v",
                "1",
                "-vf",
                "scale='min(1920,iw)':'min(1080,ih)':force_original_aspect_ratio=decrease",
                "-map_metadata",
                "-1",
                "-c:v",
                "libwebp",
                "-quality",
                "82",
                "-compression_level",
                "5",
                str(dst),
            ],
            capture_output=True,
            timeout=120,
            check=False,
            **config.subprocess_no_window(),
        )
    except (OSError, subprocess.SubprocessError):
        dst.unlink(missing_ok=True)
        return False
    if result.returncode == 0 and dst.is_file() and dst.stat().st_size > 0:
        return True
    dst.unlink(missing_ok=True)
    return False


class ThemeMediaStore:
    """数据目录内的主题媒体文件存储。"""

    def save(self, source: Path) -> dict[str, Any]:
        """把外部媒体文件保存到数据目录，返回前端所需的元数据。"""
        if not source.exists() or not source.is_file():
            return {"ok": False, "error": "媒体文件不存在"}
        ext = source.suffix.lower()
        if ext == ".mp4":
            kind = "video"
            mime = "video/mp4"
            max_bytes: int | None = MAX_VIDEO_BYTES
        elif ext in IMAGE_EXTENSIONS:
            kind = "image"
            mime = ""
            max_bytes = None
        else:
            return {"ok": False, "error": "仅支持图片或 MP4 视频"}
        try:
            source_size = source.stat().st_size
            if max_bytes is not None and source_size > max_bytes:
                return {"ok": False, "error": "媒体文件过大，请选择不超过 200MB 的文件"}
        except OSError:
            return {"ok": False, "error": "无法读取媒体文件"}

        paths.ensure_dirs()
        safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", source.stem).strip("._") or "theme_media"
        detected_format = sniff_image_format(source) if kind == "image" else ""
        converted = kind == "image" and (
            detected_format not in IMAGE_FORMATS
            or source_size > IMAGE_OPTIMIZE_THRESHOLD
        )
        if converted:
            target_ext, mime = ".webp", "image/webp"
        elif kind == "image" and detected_format in IMAGE_FORMATS:
            target_ext, mime = IMAGE_FORMATS[detected_format]
        else:
            target_ext = ext
        dst = config.THEME_MEDIA_DIR / f"{time.time_ns()}_{safe_stem}{target_ext}"
        try:
            if converted:
                if not _transcode_image(source, dst):
                    return {
                        "ok": False,
                        "error": "图片自动优化失败；请确认 FFmpeg 可用或尝试转换为 JPG/WebP",
                    }
            else:
                shutil.copy2(source, dst)
        except OSError as exc:
            return {"ok": False, "error": f"复制背景媒体失败：{exc}"}
        return {
            "ok": True,
            "path": dst.name,
            "kind": kind,
            "mime": mime,
            "name": source.name,
            "converted": converted,
        }

    def data_uri(self, media_path: str) -> str:
        """返回已保存主题媒体的 data URI，供背景图 / 视频播放。"""
        raw = str(media_path or "").strip()
        if not raw:
            return ""
        try:
            candidate = Path(raw)
            if candidate.is_absolute():
                path = candidate.expanduser().resolve()
            else:
                if candidate.name != raw or candidate.name in {"", ".", ".."}:
                    return ""
                path = (config.THEME_MEDIA_DIR / candidate.name).resolve()
            media_root = config.THEME_MEDIA_DIR.resolve()
            if path != media_root and media_root not in path.parents:
                return ""
            if not path.exists() or not path.is_file():
                return ""
            mime = MIME_BY_SUFFIX.get(path.suffix.lower())
            if not mime:
                return ""
            data = path.read_bytes()
        except OSError:
            return ""
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{b64}"

    def delete(self, media_path: str) -> bool:
        """删除由应用保存的主题媒体；外部路径与 data URI 一律不处理。"""
        raw = str(media_path or "").strip()
        if not raw or raw.lower().startswith(("data:", "http://", "https://")):
            return False
        try:
            media_root = config.THEME_MEDIA_DIR.resolve()
            candidate = Path(raw)
            if candidate.is_absolute():
                path = candidate.expanduser().resolve()
            else:
                if candidate.name != raw or candidate.name in {"", ".", ".."}:
                    return False
                path = (media_root / candidate.name).resolve()
            if path.parent != media_root:
                return False
            if not path.exists():
                return True
            if not path.is_file():
                return False
            path.unlink()
        except (OSError, RuntimeError, ValueError):
            return False
        return True
