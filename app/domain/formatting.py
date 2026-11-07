"""领域展示值格式化。

这些函数是纯函数（无 I/O、无框架依赖），被应用层与表现层共同使用：
应用层用它填充 DTO 中的可读体积，表现层用它展示磁盘占用。
基础设施层的 ``paths.human_size`` 保留为同一实现的转发。
"""

from __future__ import annotations

from pathlib import Path


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
    """文件体积的可读字符串；无法读取时返回占位符。"""
    try:
        return human_size(path.stat().st_size)
    except OSError:
        return "—"
