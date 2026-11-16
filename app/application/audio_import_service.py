"""浏览器音频导入用例：一次性负载与分块流式落盘。

表现层把前端传来的 Base64 数据交给本服务即可，不再自己处理临时文件、
令牌生命周期与半成品清理。
"""

from __future__ import annotations

from .adapters import audio_import_store
from .ports import AudioImportStorePort


class AudioImportService:
    """拖拽 / 流式音频导入的用例服务。"""

    def __init__(self, store: AudioImportStorePort | None = None) -> None:
        self._store = store or audio_import_store()

    def save_data(self, name: str, data: str) -> str | None:
        """保存一次性音频负载并返回本地路径。"""
        return self._store.save_payload(name, data)

    def start(self, name: str) -> str | None:
        """开始流式导入并返回令牌。"""
        return self._store.start(name)

    def append(self, token: str, data: str) -> bool:
        """追加一个 Base64 分块。"""
        return self._store.append(token, data)

    def finish(self, token: str) -> str | None:
        """完成流式导入并返回本地路径。"""
        return self._store.finish(token)

    def cancel(self, token: str) -> bool:
        """取消流式导入。"""
        return self._store.cancel(token)
