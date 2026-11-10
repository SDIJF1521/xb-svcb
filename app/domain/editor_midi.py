"""MIDI 子编辑器的领域规则：音符归一化与音高换算。

编辑器的 MIDI 子编辑器只处理「音符级音高」：每个音符记录片段内的时间范围、
半音音高（MIDI 编号）以及相对音准偏移（``detune``，音分）。``detune`` 保留
原始演唱的自然音准；用户拖动音符时把它清零，音符就被压到半音格上。

这里只做纯计算，不读写文件、不认识 numpy 或音频格式，便于单元测试与前端对齐。
"""

from __future__ import annotations

import math
from typing import Any

# MIDI 编号范围：C-1(0) 到 G9(127)，编辑时限制在钢琴常用的 C1~C8。
PITCH_MIN = 24.0
PITCH_MAX = 108.0
# 允许的音准偏移（音分）。
MAX_DETUNE_CENTS = 99.0
# 新建 / 提取时的最短音符；更短的碎片会被丢弃。
MIN_NOTE_SECONDS = 0.03
DEFAULT_NOTE_SECONDS = 0.25
# 单片段音符数量上限，防止误粘贴超大 MIDI 撑爆工程。
MAX_NOTES = 20000

_NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def midi_to_hz(pitch: float) -> float:
    """MIDI 编号 → 频率（Hz），A4 = 69 = 440Hz。"""
    return 440.0 * (2.0 ** ((float(pitch) - 69.0) / 12.0))


def hz_to_midi(frequency: float) -> float:
    """频率 → MIDI 编号（可为分数，表示音分偏移）。"""
    value = float(frequency)
    if value <= 0.0:
        return 0.0
    return 69.0 + 12.0 * math.log2(value / 440.0)


def clamp_pitch(value: Any) -> float:
    try:
        pitch = float(value)
    except (TypeError, ValueError):
        return 60.0
    if not math.isfinite(pitch):
        return 60.0
    return round(max(PITCH_MIN, min(PITCH_MAX, pitch)), 3)


def note_name(pitch: float) -> str:
    """MIDI 编号 → 音名（如 60 → C4，61.4 → C#4）。"""
    index = int(round(float(pitch)))
    name = _NOTE_NAMES[index % 12]
    octave = index // 12 - 1
    return f"{name}{octave}"


def clamp_detune(value: Any) -> float:
    try:
        detune = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(detune):
        return 0.0
    return round(max(-MAX_DETUNE_CENTS, min(MAX_DETUNE_CENTS, detune)), 1)


def clean_note(
    raw: Any,
    duration: float,
    *,
    index: int = 0,
) -> dict[str, Any] | None:
    """归一化单个音符；无法使用时返回 None。"""
    if not isinstance(raw, dict):
        return None
    try:
        start = float(raw.get("start", 0.0) or 0.0)
        end = float(raw.get("end", 0.0) or 0.0)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(start) or not math.isfinite(end):
        return None
    limit = max(MIN_NOTE_SECONDS, float(duration or 0.0))
    start = max(0.0, min(limit, start))
    end = max(0.0, min(limit, end))
    if end <= start:
        return None
    if end - start < MIN_NOTE_SECONDS:
        return None
    note_id = str(raw.get("id") or "").strip()
    note = {
        "id": note_id or f"midi_{index + 1}",
        "start": round(start, 3),
        "end": round(end, 3),
        "pitch": clamp_pitch(raw.get("pitch", 60.0)),
        "detune": clamp_detune(raw.get("detune", 0.0)),
    }
    return note


def clean_notes(
    raw: Any,
    duration: float,
    *,
    limit: int = MAX_NOTES,
) -> list[dict[str, Any]]:
    """归一化整串音符：裁剪到片段内、按时间排序、去掉重叠、去重 ID。"""
    if not isinstance(raw, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for index, item in enumerate(raw[: max(0, int(limit))]):
        note = clean_note(item, duration, index=index)
        if note is not None:
            cleaned.append(note)
    cleaned.sort(key=lambda note: (note["start"], note["pitch"]))
    # 同一时刻的重复 ID 会让前端选中态错乱，这里统一补编号。
    seen: set[str] = set()
    for index, note in enumerate(cleaned):
        if note["id"] in seen:
            note["id"] = f"midi_{index + 1}"
        seen.add(note["id"])
    # 音符重叠时让后一个音开始处截断前一个，保证音高重绘只有一个目标。
    for index in range(len(cleaned) - 1):
        if cleaned[index]["end"] > cleaned[index + 1]["start"]:
            cleaned[index]["end"] = round(cleaned[index + 1]["start"], 3)
    return [
        note
        for note in cleaned
        if note["end"] - note["start"] >= MIN_NOTE_SECONDS
    ]


def note_span(note: dict[str, Any]) -> tuple[float, float]:
    try:
        start = float(note.get("start", 0.0) or 0.0)
        end = float(note.get("end", 0.0) or 0.0)
    except (TypeError, ValueError):
        return (0.0, 0.0)
    return (start, end) if end > start else (0.0, 0.0)


def target_midi(note: dict[str, Any]) -> float:
    """音符的目标音高（半音 + 音准偏移折算的半音）。"""
    try:
        detune = float(note.get("detune", 0.0) or 0.0)
    except (TypeError, ValueError):
        detune = 0.0
    return clamp_pitch(note.get("pitch", 60.0)) + detune / 100.0
