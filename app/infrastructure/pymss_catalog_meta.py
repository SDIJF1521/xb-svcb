"""从 PyMSS 模型目录读取模型「声明的输出音轨」。

PyMSS 的每个模型权重旁都有同名 yaml 配置，其中 ``training.instruments``
列出了该模型能分离出的音轨名（vocals / instrumental / male / female …）。
自定义工作流的分离节点需要按这些真实音轨生成输出端口，才能和
PyMSS Studio 一样做到「选什么模型就有什么输出」。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

_MODEL_SUFFIXES = {".ckpt", ".th", ".pth", ".chpt", ".safetensors", ".pt"}
_STATE_SUFFIX = ".pymss_state_dict.pt"

# 解析结果缓存：key = (配置文件路径, mtime)
_cache: dict[tuple[str, float], list[str]] = {}


def _clean_items(items: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for item in items:
        value = str(item or "").strip().strip("'\"").strip()
        if not value or value.lower() in {"null", "none", "~"}:
            continue
        if value not in result:
            result.append(value)
    return result


def parse_instruments(text: str) -> list[str]:
    """解析 yaml 文本里的 ``instruments``（支持行内列表与缩进列表）。"""
    lines = str(text or "").splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^\s*(instruments|stems)\s*:\s*(.*)$", line, re.IGNORECASE)
        if not match:
            continue
        inline = match.group(2).strip()
        if inline.startswith("["):
            inner = inline.strip().lstrip("[").rstrip("]")
            return _clean_items(part for part in inner.split(","))
        indent = len(line) - len(line.lstrip())
        items: list[str] = []
        for follow in lines[index + 1 :]:
            if not follow.strip():
                continue
            bullet = re.match(r"^\s*-\s*(.+?)\s*$", follow)
            if bullet:
                items.append(bullet.group(1))
                continue
            body = follow.strip()
            if body.startswith("#"):
                continue
            if len(follow) - len(follow.lstrip()) <= indent:
                break
        return _clean_items(items)
    return []


def _weight_index(model_dir: Path | None) -> dict[str, Path]:
    """一次遍历建立「权重文件名 stem（小写）→ 路径」索引。"""
    index: dict[str, Path] = {}
    root = Path(model_dir) if model_dir else None
    if not root or not root.is_dir():
        return index
    try:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            name = path.name.lower()
            if name.endswith(_STATE_SUFFIX) or path.suffix.lower() not in _MODEL_SUFFIXES:
                continue
            index.setdefault(path.stem.lower(), path)
    except OSError:
        return index
    return index


def _resolve_weight(model: str, index: dict[str, Path]) -> Path | None:
    key = Path(str(model or "").strip()).stem.lower()
    if not key:
        return None
    if key in index:
        return index[key]
    # catalog 名称可能带模型子目录前缀，退化为包含匹配
    for stem, path in index.items():
        if key in stem:
            return path
    return None


def _config_for(weight: Path) -> Path | None:
    """权重同名的 yaml 优先，其次同目录下任意含 instruments 的 yaml。"""
    same_stem = weight.with_suffix(".yaml")
    if same_stem.is_file():
        return same_stem
    candidates: list[Path] = []
    try:
        candidates = sorted(weight.parent.glob("*.yaml"))
    except OSError:
        return None
    for candidate in candidates:
        try:
            if "instruments" in candidate.read_text(encoding="utf-8", errors="replace"):
                return candidate
        except OSError:
            continue
    return candidates[0] if candidates else None


def stems_for_weight(weight: Path | None) -> list[str]:
    """读取某个权重对应模型声明的输出音轨。"""
    if not weight or not Path(weight).is_file():
        return []
    config = _config_for(Path(weight))
    if not config:
        return []
    try:
        stat = config.stat()
    except OSError:
        return []
    key = (str(config), float(stat.st_mtime))
    cached = _cache.get(key)
    if cached is not None:
        return cached
    try:
        text = config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    stems = parse_instruments(text)
    _cache[key] = stems
    return stems


def model_stems(model: str, model_dir: Path | None) -> list[str]:
    """按 catalog 名称直接读取模型声明的输出音轨。"""
    return stems_for_weight(_resolve_weight(str(model or ""), _weight_index(model_dir)))


def attach_model_stems(rows: list[dict[str, Any]], model_dir: Path | None) -> list[dict[str, Any]]:
    """给 catalog 行补充 ``stems`` / ``primary_stem`` 字段。"""
    if not rows:
        return rows
    index = _weight_index(model_dir)
    for row in rows:
        if not isinstance(row, dict):
            continue
        existing = row.get("stems")
        if isinstance(existing, list) and existing:
            stems = _clean_items(existing)
        else:
            stems = stems_for_weight(_resolve_weight(str(row.get("name") or ""), index))
        row["stems"] = stems
        target = str(row.get("target_stem") or "").strip()
        primary = ""
        if target:
            primary = next((stem for stem in stems if stem.casefold() == target.casefold()), "")
        if not primary:
            primary = stems[0] if stems else target
        row["primary_stem"] = primary
    return rows
