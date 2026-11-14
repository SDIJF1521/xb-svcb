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
    # 只有权重文件名与 catalog 名完全一致，或权重放在以模型名命名的子目录里，
    # 才算同一个模型。以前用子串匹配，`..._vocals_v2` 会命中
    # `..._vocals_v2_gabox` 的 yaml，界面就会显示另一个模型的音轨。
    for path in index.values():
        if path.parent.name.casefold() == key:
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


def _looks_vocal(name: str) -> bool:
    norm = str(name or "").casefold().replace("_", " ").replace("-", " ")
    if any(token in norm for token in ("no vocal", "instrument", "accompan", "karaoke")):
        return False
    return any(token in norm for token in ("vocal", "voice", "singing", "lead"))


def _looks_instrumental(name: str) -> bool:
    norm = str(name or "").casefold().replace("_", " ").replace("-", " ")
    return any(
        token in norm
        for token in (
            "instrument",
            "accompan",
            "karaoke",
            "music",
            "background",
            "bgm",
            "minus",
        )
    )


def parse_training_meta(text: str) -> dict[str, Any]:
    """解析模型 yaml 的训练段：音轨列表、目标音轨与 stem 数量。"""
    instruments = parse_instruments(text)
    target = ""
    # 只匹配同一行；用 [ \t] 而不是 \s，否则空值会把下一行当成值。
    match = re.search(
        r"(?m)^[ \t]*target_instrument[ \t]*:[ \t]*(.*?)[ \t]*$", str(text or "")
    )
    if match:
        value = match.group(1).strip().strip("'\"")
        if value.casefold() not in {"", "null", "none", "~"}:
            target = value
    num_stems = 0
    match = re.search(
        r"(?m)^[ \t]*num_stems[ \t]*:[ \t]*(\d+)[ \t]*$", str(text or "")
    )
    if match:
        try:
            num_stems = int(match.group(1))
        except ValueError:
            num_stems = 0
    return {
        "instruments": instruments,
        "target_instrument": target,
        "num_stems": num_stems,
    }


def resolve_output_stems(
    instruments: list[str] | tuple[str, ...],
    target_instrument: str,
) -> tuple[list[str], str]:
    """按 PyMSS 的真实输出语义解析端口名。

    ``target_instrument`` 模型只训练一个目标音轨；PyMSS 还会返回
    ``mix - target`` 作为残差，残差名来自 ``instruments`` 里的另一项。
    因此：
      - 目标是人声 → 输出 ``vocals`` + ``instrumental``（残差就是伴奏）；
      - 目标是伴奏 → 输出 ``instrumental`` + ``other``（残差不是人声分离结果）。
    这样伴奏/无人声模型就不会再显示一个并不存在的「人声」端口。
    """
    cleaned = _clean_items(instruments or [])
    if not cleaned:
        return [], ""
    target = str(target_instrument or "").strip()
    if not target:
        return cleaned, ""
    target_entry = next(
        (stem for stem in cleaned if stem.casefold() == target.casefold()), target
    )
    if _looks_vocal(target_entry):
        primary = "vocals"
    elif _looks_instrumental(target_entry):
        primary = "instrumental"
    else:
        primary = target_entry
    stems = [primary]
    if any(stem.casefold() != target.casefold() for stem in cleaned):
        residual = "instrumental" if primary == "vocals" else "other"
        if residual not in stems:
            stems.append(residual)
    return stems, primary


def descriptor_for_weight(weight: Path | None) -> dict[str, Any]:
    """读取模型的输出音轨描述；无配置时返回空描述。"""
    empty: dict[str, Any] = {
        "stems": [],
        "primary_stem": "",
        "instruments": [],
        "target_instrument": "",
        "num_stems": 0,
    }
    if not weight or not Path(weight).is_file():
        return empty
    config_path = _config_for(Path(weight))
    if not config_path:
        return empty
    try:
        stat = config_path.stat()
    except OSError:
        return empty
    key = (str(config_path), float(stat.st_mtime))
    cached = _cache.get(key)
    if cached is not None:
        return cached
    try:
        text = config_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return empty
    meta = parse_training_meta(text)
    stems, primary = resolve_output_stems(
        meta["instruments"], meta["target_instrument"]
    )
    descriptor = {
        "stems": stems,
        # 只有 yaml 的 target_instrument 才能确定训练目标；多轨模型保持为空，
        # 由 catalog 的 target_stem 或声明顺序决定主音轨。
        "primary_stem": primary,
        "instruments": meta["instruments"],
        "target_instrument": meta["target_instrument"],
        "num_stems": meta["num_stems"],
    }
    _cache[key] = descriptor
    return descriptor


def stems_for_weight(weight: Path | None) -> list[str]:
    """某个权重对应模型的输出端口名（target 模型已按 PyMSS 语义归一）。"""
    return list(descriptor_for_weight(weight).get("stems") or [])


def model_stems(model: str, model_dir: Path | None) -> list[str]:
    """按 catalog 名称读取模型的输出端口名。"""
    return stems_for_weight(_resolve_weight(str(model or ""), _weight_index(model_dir)))


def model_descriptor(model: str, model_dir: Path | None) -> dict[str, Any]:
    """按 catalog 名称读取完整输出描述。"""
    return descriptor_for_weight(_resolve_weight(str(model or ""), _weight_index(model_dir)))


def split_target_stems(value: str) -> list[str]:
    """把 catalog 的 ``target_stem`` 拆成音轨名列表。

    很多模型的 target_stem 是多音轨写法（``instrumental/vocals``、
    ``drums/bass/other/vocals/guitar/piano``）。未下载模型只能靠它推断端口，
    不拆分就会把 ``vocals`` 丢掉。
    """
    tokens = [
        part.strip().strip("'\"")
        for part in re.split(r"[/+,;|]", str(value or ""))
        if part.strip()
    ]
    result: list[str] = []
    for token in tokens:
        if token.casefold() not in {item.casefold() for item in result}:
            result.append(token)
    return result


def attach_model_stems(rows: list[dict[str, Any]], model_dir: Path | None) -> list[dict[str, Any]]:
    """给 catalog 行补充 ``stems`` / ``primary_stem`` / ``target_stems`` 字段。"""
    if not rows:
        return rows
    index = _weight_index(model_dir)
    for row in rows:
        if not isinstance(row, dict):
            continue
        existing = row.get("stems")
        if isinstance(existing, list) and existing:
            stems = _clean_items(existing)
            primary = ""
        else:
            descriptor = descriptor_for_weight(
                _resolve_weight(str(row.get("name") or ""), index)
            )
            stems = list(descriptor.get("stems") or [])
            primary = str(descriptor.get("primary_stem") or "")
        row["stems"] = stems
        target = str(row.get("target_stem") or "").strip()
        target_tokens = split_target_stems(target)
        row["target_stems"] = target_tokens
        if not primary and target:
            # catalog 的 target_stem 可能是多音轨写法，逐个匹配。
            primary = next(
                (
                    stem
                    for token in target_tokens or [target]
                    for stem in stems
                    if stem.casefold() == token.casefold()
                ),
                "",
            )
        if not primary:
            primary = stems[0] if stems else (target_tokens[0] if target_tokens else target)
        row["primary_stem"] = primary
    return rows
