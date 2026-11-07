"""编辑器工程的文件访问适配器（``EditorProjectStorePort`` 的实现）。

用例层（``application.audio_editor_service`` / ``application.editor_render_service``）
保留「校验什么、什么时候清理、什么算合法的工程包」这些策略；真正的磁盘与 zip
操作集中在这里，方便替换实现（例如测试用内存替身）而不改动用例。

端口契约见 ``application/ports.EditorProjectStorePort``。
"""

from __future__ import annotations

import base64
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import config
from infrastructure.audio_engine import FFmpegEngine

# 工程包内成员名的规范化：统一用 posix 分隔符判断安全性。
_BUNDLE_COPY_CHUNK = 1024 * 1024


class EditorProjectStore:
    """编辑器工程目录、渲染/波形缓存与工程包（zip）的文件访问。"""

    def __init__(self, ffmpeg: Any | None = None) -> None:
        # ffmpeg 是可选的 ``FfmpegTool`` 替身（``.available`` / ``.convert``）：
        # 仅在音频预览需要转 mp3 时用到，缺失时退化为直接读取源文件。
        self._ffmpeg = ffmpeg

    # ---- 目录与缓存路径 ----

    def project_dir(self, project_id: str) -> Path:
        """工程目录；每次调用都重新读取 ``config``，便于测试替换数据目录。"""
        return config.EDITOR_DIR / project_id

    def cache_path(self, name: str) -> Path:
        """渲染/波形/预览缓存文件；``name`` 为空时即缓存根目录。"""
        return config.EDITOR_CACHE_DIR / name

    # ---- 音频预览 ----

    def audio_data_uri(self, source: Path, *, exact: bool = False) -> str:
        """把音频文件转成 data URI（mp3 缓存 + base64），失败时返回空串。"""
        src = Path(source)
        if not src.exists():
            return ""
        data: bytes | None = None
        mime_by_ext = {
            ".flac": "audio/flac",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
        }
        mime = mime_by_ext.get(src.suffix.lower(), "audio/wav")
        if exact or src.suffix.lower() == ".mp3":
            try:
                data = src.read_bytes()
            except OSError:
                data = None
        if self._ffmpeg is not None and self._ffmpeg.available:
            try:
                tmp = self.cache_path(f"aud_{FFmpegEngine.cache_key(str(src))}.mp3")
                if data is None and not tmp.exists():
                    self._ffmpeg.convert(src, tmp)
                if data is None and tmp.exists():
                    data = tmp.read_bytes()
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

    # ---- 原始字节 ----

    def read_bytes(self, path: Path) -> bytes | None:
        try:
            return Path(path).read_bytes()
        except OSError:
            return None

    def write_bytes(self, path: Path, data: bytes) -> bool:
        target = Path(path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        except OSError:
            return False
        return True

    def exists(self, path: Path) -> bool:
        try:
            return Path(path).exists()
        except (OSError, RuntimeError):
            return False

    def remove(self, path: Path) -> None:
        """删除文件、符号链接或目录；不存在或删不掉都不抛异常。"""
        target = Path(path)
        try:
            if target.is_symlink() or target.is_file():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
        except (OSError, RuntimeError):
            return

    # ---- 工程包（zip） ----

    @staticmethod
    def _safe_member(arcname: Any) -> PurePosixPath | None:
        """规范化成员名：拒绝绝对路径、盘符与 ``..``（工程包穿越防护）。"""
        raw = str(arcname or "").replace("\\", "/").strip()
        if not raw:
            return None
        member = PurePosixPath(raw)
        parts = [part for part in member.parts if part not in {"", "."}]
        if not parts or member.is_absolute() or ".." in parts:
            return None
        # Windows 盘符（C:/x）在 PurePosixPath 里不是绝对路径，需要单独拒绝。
        if ":" in parts[0]:
            return None
        return PurePosixPath(*parts)

    def export_zip(self, entries: Iterable[tuple[Path, str]], destination: Path) -> bool:
        """把 ``(源文件, 成员名)`` 写成 zip；成员名不安全或 I/O 失败时返回 False。"""
        target = Path(destination)
        temporary = target.with_name(target.name + ".tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(
                temporary,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=1,
                allowZip64=True,
            ) as archive:
                for source, arcname in entries:
                    member = self._safe_member(arcname)
                    if member is None:
                        raise ValueError(f"无效的工程包条目：{arcname}")
                    archive.write(Path(source), member.as_posix())
            temporary.replace(target)
        except ValueError:
            self._discard(temporary)
            return False
        except (OSError, RuntimeError, zipfile.BadZipFile):
            self._discard(temporary)
            return False
        return True

    def extract_zip(self, source: Path, destination: Path) -> list[str]:
        """解压工程包到 ``destination`` 并返回成员名列表（posix 相对路径）。

        成员名不安全时抛 ``ValueError``（这是显式的安全拒绝，不是 I/O 失败）；
        其它 I/O 问题一律返回空列表，让用例层按“解包失败”处理。
        """
        root = Path(destination)
        extracted: list[str] = []
        try:
            with zipfile.ZipFile(source) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    member = self._safe_member(info.filename)
                    if member is None:
                        raise ValueError(f"无效的工程包条目：{info.filename}")
                    target = root.joinpath(*member.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as input_stream:
                        with target.open("wb") as output_stream:
                            shutil.copyfileobj(
                                input_stream, output_stream, length=_BUNDLE_COPY_CHUNK
                            )
                    extracted.append(member.as_posix())
        except ValueError:
            raise
        except (OSError, RuntimeError, zipfile.BadZipFile):
            return []
        return extracted

    @staticmethod
    def _discard(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except (OSError, RuntimeError):
            return
