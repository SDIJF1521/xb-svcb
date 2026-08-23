"""数据目录管理与通用文件工具。"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path

import config


def ensure_dirs() -> None:
    """确保所有数据目录存在。"""
    config.cleanup_pending_migration()
    for d in (
        config.DATA_DIR,
        config.MODELS_DIR,
        config.WORKS_DIR,
        config.TEMP_DIR,
        config.MUSIC_DIR,
        config.MODELHUB_DIR,
        config.EDITOR_DIR,
        config.EDITOR_CACHE_DIR,
        config.THEME_MEDIA_DIR,
        config.API_UPLOADS_DIR,
        config.PLUGINS_DIR,
        config.PLUGIN_DATA_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)
    marker = config.DATA_DIR / config.DATA_MARKER_FILE
    if not marker.exists():
        marker.write_text(
            json.dumps(
                {"app": config.APP_NAME, "version": config.APP_VERSION},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


def clear_temp_directory(*, retries: int = 3, retry_delay: float = 0.15) -> bool:
    """Remove all generated files below the current data ``temp`` directory.

    The directory itself is kept so callers can continue writing to it after a
    restart. The parent check prevents a misconfigured path from turning this
    shutdown cleanup into a broad deletion.
    """
    try:
        data_root = config.DATA_DIR.resolve()
        temp_root = config.TEMP_DIR.resolve()
    except OSError:
        return False
    if temp_root.parent != data_root or temp_root == data_root:
        return False
    try:
        temp_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False

    attempts = max(1, int(retries))
    for attempt in range(attempts):
        try:
            for entry in list(temp_root.iterdir()):
                if entry.is_symlink() or not entry.is_dir():
                    entry.unlink(missing_ok=True)
                else:
                    shutil.rmtree(entry)
            return not any(temp_root.iterdir())
        except OSError:
            if attempt + 1 < attempts:
                time.sleep(max(0.0, float(retry_delay)))
    return False


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
