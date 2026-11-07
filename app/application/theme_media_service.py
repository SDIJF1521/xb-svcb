"""主题媒体用例：保存 / 读取 / 删除自定义背景媒体。

表现层（pywebview Bridge）只负责弹出文件对话框，实际的复制、转码与
data URI 生成由本服务编排，具体存储能力由 ``ThemeMediaStorePort`` 适配器提供。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .adapters import theme_media_store
from .ports import ThemeMediaStorePort


class ThemeMediaService:
    """自定义主题背景媒体的用例服务。"""

    def __init__(self, store: ThemeMediaStorePort | None = None) -> None:
        self._store = store or theme_media_store()

    def save(self, source_path: str) -> dict[str, Any]:
        """保存用户选中的背景媒体。"""
        if not source_path:
            return {"ok": False, "cancelled": True}
        try:
            source = Path(source_path)
        except (OSError, ValueError):
            return {"ok": False, "error": "媒体文件不存在"}
        return self._store.save(source)

    def data_uri(self, media_path: str) -> str:
        """读取已保存的媒体为 data URI。"""
        return self._store.data_uri(media_path)

    def delete(self, media_path: str) -> bool:
        """删除已保存的媒体文件。"""
        return self._store.delete(media_path)
