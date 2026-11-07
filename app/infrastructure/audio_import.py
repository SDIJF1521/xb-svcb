"""浏览器拖拽 / 流式音频导入的本地落盘。

原实现位于 ``api/bridge.py``：分块接收 Base64 数据并写入 ``temp/dropped-audio``。
这属于文件摄取能力，移到基础设施层；用例编排见 ``AudioImportService``。
"""

from __future__ import annotations

import base64
import threading
from pathlib import Path

import config
from domain.identity import new_id

AUDIO_SUFFIXES = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".opus", ".wma"}


def audio_suffix(name: str) -> str:
    """把上传文件名规范为受支持的音频后缀；不支持时返回空串。"""
    suffix = Path(str(name or "audio.wav")).suffix.lower()
    return suffix if suffix in AUDIO_SUFFIXES else ""


def decode_audio_data(data: str) -> bytes | None:
    """解码 data URI 或裸 Base64 音频分块。"""
    raw = str(data or "")
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        return base64.b64decode(raw, validate=True)
    except Exception:  # noqa: BLE001 - 非法 Base64 一律按失败处理
        return None


class AudioImportStore:
    """管理一次性音频导入令牌与对应的临时文件。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._imports: dict[str, Path] = {}

    @staticmethod
    def _target_dir() -> Path:
        return config.TEMP_DIR / "dropped-audio"

    def save_payload(self, name: str, data: str) -> str | None:
        """一次性写入完整音频负载，返回落盘路径。"""
        content = decode_audio_data(data)
        suffix = audio_suffix(name)
        if not content or not suffix:
            return None
        target_dir = self._target_dir()
        target = target_dir / f"{new_id('drop_')}{suffix}"
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        except OSError:
            return None
        return str(target)

    def start(self, name: str) -> str | None:
        """开始分块导入并返回不透明令牌。"""
        suffix = audio_suffix(name)
        if not suffix:
            return None
        target_dir = self._target_dir()
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            token = new_id("drop_")
            partial = target_dir / f"{token}{suffix}.part"
            partial.touch(exist_ok=False)
        except OSError:
            return None
        with self._lock:
            self._imports[token] = partial
        return token

    def append(self, token: str, data: str) -> bool:
        """追加一个 Base64 分块。"""
        with self._lock:
            partial = self._imports.get(str(token or ""))
        content = decode_audio_data(data)
        if partial is None or not content:
            return False
        try:
            with partial.open("ab") as stream:
                stream.write(content)
        except OSError:
            self.cancel(token)
            return False
        return True

    def finish(self, token: str) -> str | None:
        """完成分块导入，返回最终本地路径。"""
        with self._lock:
            partial = self._imports.pop(str(token or ""), None)
        if partial is None:
            return None
        try:
            if not partial.is_file() or partial.stat().st_size <= 0:
                partial.unlink(missing_ok=True)
                return None
            target = Path(str(partial)[:-len(".part")])
            partial.replace(target)
            return str(target)
        except OSError:
            partial.unlink(missing_ok=True)
            return None

    def cancel(self, token: str) -> bool:
        """取消分块导入并删除半成品文件。"""
        with self._lock:
            partial = self._imports.pop(str(token or ""), None)
        if partial is None:
            return False
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            return False
        return True
