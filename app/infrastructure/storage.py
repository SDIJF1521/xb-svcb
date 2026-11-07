"""线程安全的 JSON 文件存储。

提供一个简单的本地持久化层：
- JsonStore：底层读写。
- ListRepository：以 ``id`` 为主键的列表型仓储（模型 / 作品）。
- SettingsStore：键值配置。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

# Windows 上浏览器/杀毒软件或其他线程可能短暂占用目标文件，替换失败时重试几次。
_REPLACE_RETRIES = 5
_REPLACE_RETRY_DELAY = 0.02


class JsonStore:
    def __init__(self, path: Path, default: Any) -> None:
        self._path = path
        self._default = default
        self._lock = threading.RLock()
        self._ensure_file()

    def set_path(self, path: Path) -> None:
        with self._lock:
            self._path = path
            self._ensure_file()

    def read(self) -> Any:
        with self._lock:
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None

    def write(self, data: Any) -> None:
        with self._lock:
            self._write(data)

    def _write(self, data: Any) -> None:
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        for attempt in range(_REPLACE_RETRIES):
            try:
                tmp.replace(self._path)
                return
            except PermissionError:
                if attempt + 1 >= _REPLACE_RETRIES:
                    raise
                time.sleep(_REPLACE_RETRY_DELAY)

    def _ensure_file(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._write(self._default)


class ListRepository:
    """以 id 为主键的列表仓储。"""

    def __init__(self, path: Path) -> None:
        self._store = JsonStore(path, [])
        self._lock = threading.RLock()

    def set_path(self, path: Path) -> None:
        with self._lock:
            self._store.set_path(path)

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._store.read() or [])

    def get(self, item_id: str) -> dict[str, Any] | None:
        return next((it for it in self.all() if it.get("id") == item_id), None)

    def add(self, item: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            items = self.all()
            items.insert(0, item)
            self._store.write(items)
            return item

    def update(self, item_id: str, item: dict[str, Any]) -> None:
        with self._lock:
            items = self.all()
            for i, it in enumerate(items):
                if it.get("id") == item_id:
                    items[i] = item
                    break
            self._store.write(items)

    def remove(self, item_id: str) -> None:
        with self._lock:
            items = [it for it in self.all() if it.get("id") != item_id]
            self._store.write(items)


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self._store = JsonStore(path, {})

    def set_path(self, path: Path) -> None:
        self._store.set_path(path)

    def get(self, key: str, default: Any = None) -> Any:
        data = self._store.read() or {}
        return data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        data = self._store.read() or {}
        data[key] = value
        self._store.write(data)
