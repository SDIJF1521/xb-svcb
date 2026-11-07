"""作品媒体文件用例：试听 data URI、异步导出、时长探测。

表现层只负责弹出保存对话框，文件读取、转码与路径校验由本服务完成。
"""

from __future__ import annotations

import base64
import shutil
from pathlib import Path

import config

from .adapters import ffmpeg_tool
from .ports import FfmpegGateway, ItemRepository

SUPPORTED_EXPORT_FORMATS = ("wav", "mp3", "flac", "m4a")

# 作品记录中的音轨字段，key 为对外的音轨类型。
_STEM_FIELDS = {
    "output": "output_path",
    "instrumental": "instrumental_path",
    "vocals": "vocals_path",
}


class MediaService:
    """作品成品的读取、导出与时长探测。"""

    def __init__(
        self,
        repo: ItemRepository,
        ffmpeg: FfmpegGateway | None = None,
    ) -> None:
        self._repo = repo
        self._ffmpeg = ffmpeg or ffmpeg_tool()

    def stem_path(self, work_id: str, kind: str) -> Path | None:
        """解析作品某条音轨的真实路径，并校验其位于数据目录内。"""
        work = self._repo.get(work_id) or {}
        key = _STEM_FIELDS.get(kind)
        if not key:
            return None
        raw = work.get(key) or (work.get("output") if kind == "output" else None)
        if not raw:
            return None
        try:
            path = Path(raw).resolve()
            allowed = config.WORKS_DIR.resolve()
        except OSError:
            return None
        # 仅允许读取数据目录内的文件，避免任意路径读取
        if allowed not in path.parents:
            return None
        return path if path.exists() else None

    def data_uri(self, work_id: str, kind: str) -> str:
        """返回指定音轨的 data URI；有 ffmpeg 时先转 mp3 减小体积。"""
        src = self.stem_path(work_id, kind)
        if src is None:
            return ""
        data: bytes | None = None
        mime = "audio/wav"
        if self._ffmpeg.available:
            try:
                config.TEMP_DIR.mkdir(parents=True, exist_ok=True)
                mp3 = config.TEMP_DIR / f"{work_id}_{kind}.mp3"
                if self._ffmpeg.convert(src, mp3):
                    data = mp3.read_bytes()
                    mime = "audio/mpeg"
            except OSError:
                data = None
        if data is None:
            try:
                data = src.read_bytes()
            except OSError:
                return ""
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{b64}"

    def export(self, work_id: str, destination: str | Path, fmt: str = "wav") -> str:
        """把成品导出到目标路径；返回最终路径，失败时返回空串。"""
        output_format = str(fmt or "wav").strip().lower().lstrip(".")
        if output_format not in SUPPORTED_EXPORT_FORMATS:
            output_format = "wav"
        ext = f".{output_format}"
        src = self.stem_path(work_id, "output")
        if src is None:
            return ""
        dest_path = Path(destination)
        if dest_path.suffix.lower() != ext:
            dest_path = dest_path.with_suffix(ext)
        try:
            if src.resolve() == dest_path.resolve():
                return str(dest_path) if src.suffix.lower() == ext else ""
            if src.suffix.lower() == ext:
                shutil.copyfile(src, dest_path)
                return str(dest_path)
            if self._ffmpeg.convert(src, dest_path):
                return str(dest_path)
            dest_path.unlink(missing_ok=True)
            return ""
        except OSError:
            return ""

    def duration(self, path: str) -> float:
        """探测本地音频时长（秒），失败返回 0。"""
        if not path:
            return 0.0
        try:
            src = Path(path)
        except (OSError, ValueError):
            return 0.0
        dur = self._ffmpeg.probe_duration(src)
        return float(dur or 0.0)
