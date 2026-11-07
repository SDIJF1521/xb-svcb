"""领域标识生成。

领域实体（作品、模型、工程、片段……）的 ID 由领域层统一生成，属于纯计算，
不依赖文件系统或运行时环境，因此放在领域层；基础设施层的 ``paths.new_id``
继续保留为同一实现的转发，避免外部调用方失效。
"""

from __future__ import annotations

import uuid

# 实体 ID 统一使用「前缀 + 12 位十六进制」，前缀用于区分聚合类型。
_ID_LENGTH = 12


def new_id(prefix: str = "") -> str:
    """生成短随机 ID（前缀 + 12 位十六进制）。"""
    return f"{prefix}{uuid.uuid4().hex[:_ID_LENGTH]}"
