"""作品工作目录与运行日志的文件访问（``WorkFilesPort`` 的基础设施实现）。

用例层的 ``WorkService`` 只保留“什么时候清理、清理什么、返回什么”的策略，
真正落到磁盘的动作（目录路径拼装、目录复制/删除、日志尾部读取、目录列举）
集中在这里，避免用例层直接做文件 I/O。

本适配器刻意做得很薄：不做缓存、不记录状态、不判断业务含义，除了实际的
文件系统调用之外没有副作用。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import config


class WorkFiles:
    """``WorkService`` 的工作目录 / 运行日志文件系统适配器。"""

    def work_dir(self, work_id: str) -> Path:
        """作品的工作目录：``WORKS_DIR/<work_id>``。"""
        return config.WORKS_DIR / work_id

    def log_path(self, work_id: str, recorded: str | None = None) -> Path:
        """运行日志路径：优先使用记录中的路径，否则回落到工作目录下的 ``run.log``。"""
        if recorded:
            return Path(recorded)
        return config.WORKS_DIR / work_id / "run.log"

    def read_text_tail(self, path: Path, lines: int) -> str:
        """读取文本文件末尾 ``lines`` 行；文件不可读时返回空字符串。"""
        try:
            if not path.is_file():
                return ""
            content = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        count = max(0, int(lines))
        if not count:
            return ""
        return "\n".join(content[-count:])

    def copy_tree(self, source: Path, destination: Path) -> bool:
        """整目录复制；失败（``OSError``）时返回 ``False``。"""
        try:
            shutil.copytree(source, destination)
        except OSError:
            return False
        return True

    def remove_tree(self, path: Path) -> None:
        """整目录删除，忽略不存在的路径与部分失败。"""
        shutil.rmtree(path, ignore_errors=True)

    def list_entries(self, path: Path) -> list[Path]:
        """列举目录的直接子项；不是目录或不可读时返回空列表。"""
        try:
            if not path.is_dir():
                return []
            return list(path.iterdir())
        except OSError:
            return []
