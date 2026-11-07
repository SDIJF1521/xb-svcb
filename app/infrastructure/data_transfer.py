"""数据目录探测与迁移搬运（文件系统能力）。

原实现位于 ``api/bridge.py``：目标目录规范化、空间与可写性检查、带进度的大文件复制、
迁移标记写入。这些属于基础设施能力，用例编排见 ``DataMaintenanceService``。
"""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable

import config

# 迁移时跳过的大目录（临时文件与 WebView 缓存，迁移后由应用重新生成）。
VOLATILE_TOP_LEVEL = ("temp", "webview")

_CHUNK_SIZE = 8 * 1024 * 1024


def is_relative_path(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def should_skip_migration_path(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return False
    return bool(parts) and parts[0] in VOLATILE_TOP_LEVEL


def is_volatile_migration_path(path: Path, root: Path) -> bool:
    try:
        top = path.relative_to(root).parts[0]
    except (ValueError, IndexError):
        return False
    return top in VOLATILE_TOP_LEVEL


def dir_size(root: Path, ignore_tmp: bool = False, skip_volatile: bool = False) -> int:
    total = 0
    if not root.exists():
        return 0
    for item in root.rglob("*"):
        if ignore_tmp and any(fnmatch.fnmatch(part, "*.tmp") for part in item.parts):
            continue
        if skip_volatile and should_skip_migration_path(item, root):
            continue
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            pass
    return total


def test_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".xb_svcb_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def looks_like_data_dir(path: Path) -> bool:
    if (path / config.DATA_MARKER_FILE).exists():
        return True
    if any((path / name).exists() for name in config.LEGACY_DATA_MARKER_FILES):
        return True
    core_files = ("models.json", "works.json", "settings.json", "editor_projects.json")
    if any((path / name).exists() for name in core_files):
        return True
    core_dirs = ("models", "works", "music", "editor", "modelhub")
    return sum(1 for name in core_dirs if (path / name).exists()) >= 2


def write_data_dir_marker(
    target: Path,
    *,
    migrated_from: str | None = None,
    selected_from: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "app": config.APP_NAME,
        "version": config.APP_VERSION,
    }
    if migrated_from:
        payload["migrated_from"] = migrated_from
    if selected_from:
        payload["selected_from"] = selected_from
    (target / config.DATA_MARKER_FILE).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def disk_usage(path: Path) -> tuple[int, int]:
    """返回 (可用字节, 总字节)；无法访问时返回 (0, 0)。"""
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return 0, 0
    return int(usage.free), int(usage.total)


def resolve_data_dir_target(raw_target: str, current: Path) -> tuple[Path | None, str | None]:
    """把用户选择的目录规范成真正的数据目录。

    用户可能选择磁盘根目录或一个普通文件夹；这时在其中创建 ``DATA_DIR_NAME``
    子目录作为实际数据目录。若选择的是已有 XB-SVCB 数据目录，则直接使用。
    """
    if not str(raw_target or "").strip():
        return None, "请选择目标目录。"
    try:
        selected = Path(raw_target).expanduser().resolve()
    except OSError:
        return None, "目标目录无效。"

    try:
        selected_exists = selected.exists()
        if selected_exists and not selected.is_dir():
            return None, "目标路径不是文件夹。"
        selected_is_data_dir = selected_exists and looks_like_data_dir(selected)
        selected_has_entries = selected_exists and any(selected.iterdir())
    except OSError:
        return None, "无法访问目标目录。"

    target = selected
    if selected.parent == selected or (selected_has_entries and not selected_is_data_dir):
        target = selected / config.DATA_DIR_NAME

    try:
        target = target.expanduser().resolve()
        target_exists = target.exists()
        if target_exists and not target.is_dir():
            return None, "目标路径不是文件夹。"
        target_is_data_dir = target_exists and looks_like_data_dir(target)
        target_has_entries = target_exists and any(target.iterdir())
    except OSError:
        return None, "无法访问目标目录。"

    if target.parent == target:
        return None, "目标目录不能直接使用磁盘根目录。"
    if target != current and (
        is_relative_path(target, current) or is_relative_path(current, target)
    ):
        return None, "目标目录不能位于当前数据目录内部，也不能包含当前数据目录。"
    if target_has_entries and not target_is_data_dir:
        return (
            None,
            f"目标数据目录不是空目录：{target}。请选择空目录，或选择已有 XB-SVCB 数据目录。",
        )
    return target, None


def resolve_migration_target(raw_target: str, src: Path) -> tuple[Path | None, str | None]:
    target, error = resolve_data_dir_target(raw_target, src)
    if error or target is None:
        return target, error
    if target == src:
        return None, "目标目录与当前目录相同。"
    return target, None


def copy_tree_with_progress(
    src: Path,
    dst: Path,
    total_bytes: int,
    on_progress: Callable[[int], None],
) -> None:
    """逐块复制目录并回报已复制字节数（跳过临时文件与易失目录）。"""
    copied = 0

    def report() -> None:
        on_progress(min(copied, total_bytes) if total_bytes > 0 else copied)

    for root_str, dirs, files in os.walk(src):
        root = Path(root_str)
        dirs[:] = [
            name
            for name in dirs
            if not fnmatch.fnmatch(name, "*.tmp")
            and not should_skip_migration_path(root / name, src)
        ]
        rel = root.relative_to(src)
        dst_root = dst if str(rel) == "." else dst / rel
        dst_root.mkdir(parents=True, exist_ok=True)
        for dirname in dirs:
            (dst_root / dirname).mkdir(exist_ok=True)
        for filename in files:
            if fnmatch.fnmatch(filename, "*.tmp"):
                continue
            src_file = root / filename
            if should_skip_migration_path(src_file, src):
                continue
            if not src_file.is_file():
                continue
            dst_file = dst_root / filename
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                file_size = src_file.stat().st_size
                with src_file.open("rb") as rf, dst_file.open("wb") as wf:
                    while True:
                        chunk = rf.read(_CHUNK_SIZE)
                        if not chunk:
                            break
                        wf.write(chunk)
                        copied += len(chunk)
                        report()
                shutil.copystat(src_file, dst_file)
            except OSError:
                if is_volatile_migration_path(src_file, src):
                    continue
                raise
            if file_size == 0:
                report()
    report()


class DataTransfer:
    """`DataTransferPort` 的默认实现：转发模块级文件系统能力。"""

    resolve_data_dir_target = staticmethod(resolve_data_dir_target)
    resolve_migration_target = staticmethod(resolve_migration_target)
    looks_like_data_dir = staticmethod(looks_like_data_dir)
    dir_size = staticmethod(dir_size)
    test_writable = staticmethod(test_writable)
    write_marker = staticmethod(write_data_dir_marker)
    disk_usage = staticmethod(disk_usage)
    copy_tree = staticmethod(copy_tree_with_progress)
