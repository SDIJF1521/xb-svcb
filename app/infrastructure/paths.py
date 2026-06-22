"""数据目录管理与通用文件工具。"""

from __future__ import annotations

import uuid
from pathlib import Path

import config


def ensure_dirs() -> None:
    """确保所有数据目录存在。"""
    for d in (
        config.DATA_DIR,
        config.MODELS_DIR,
        config.WORKS_DIR,
        config.TEMP_DIR,
        config.MUSIC_DIR,
        config.MODELHUB_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)


def new_id(prefix: str = "") -> str:
    """生成短随机 ID。"""
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def human_size(num_bytes: int) -> str:
    """字节数转可读字符串。"""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def file_size_label(path: Path) -> str:
    try:
        return human_size(path.stat().st_size)
    except OSError:
        return "—"
