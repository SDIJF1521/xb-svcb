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


# ---- 音高曲线（OpenUtau 风格滑音 / 颤音）----
# 控制点 ``{"t": 相对音符起点秒, "v": 相对音符音高的半音偏移}``；
# 少于两个点视为「没有曲线」，避免把用户没画过的音符也塞一堆点。
MAX_CURVE_POINTS = 256
CURVE_SEMITONE_LIMIT = 12.0


def clamp_curve(value: Any, span: float) -> list[dict[str, float]] | None:
    """归一化音高曲线：裁到音符时长内、限幅、排序、限点数。"""
    if not isinstance(value, list):
        return None
    try:
        length = max(0.0, float(span or 0.0))
    except (TypeError, ValueError):
        length = 0.0
    points: list[dict[str, float]] = []
    for item in value[:MAX_CURVE_POINTS]:
        if not isinstance(item, dict):
            continue
        try:
            t = float(item.get("t", 0.0))
            v = float(item.get("v", 0.0))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(t) or not math.isfinite(v):
            continue
        points.append(
            {
                "t": round(max(0.0, min(length, t)), 3),
                "v": round(max(-CURVE_SEMITONE_LIMIT, min(CURVE_SEMITONE_LIMIT, v)), 3),
            }
        )
    if len(points) < 2:
        return None
    points.sort(key=lambda point: point["t"])
    # 时间必须严格递增：同一时刻只保留最后一个，避免曲线上出现垂直跳变。
    deduped: list[dict[str, float]] = []
    for point in points:
        if deduped and abs(point["t"] - deduped[-1]["t"]) < 1e-6:
            deduped[-1] = point
        else:
            deduped.append(point)
    if len(deduped) < 2:
        return None
    return deduped


def shift_curve(value: Any, shift: float, span: float) -> list[dict[str, float]] | None:
    """把曲线平移到新起点并裁到 ``span`` 内（整轨按片段切分时用）。

    被片段边界裁掉的端点不丢弃，而是把时间夹到 0 / span，
    这样曲线的形状（滑音方向）还在，只是首尾被截平。
    """
    if not isinstance(value, list):
        return None
    length = max(0.0, float(span or 0.0))
    moved: list[dict[str, float]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            t = float(item.get("t", 0.0)) - float(shift)
            v = float(item.get("v", 0.0))
        except (TypeError, ValueError):
            continue
        moved.append({"t": max(0.0, min(length, t)), "v": v})
    return clamp_curve(moved, length)


def curve_value_at(curve: list[dict[str, float]] | None, t: float) -> float:
    """曲线在相对时刻 t 的偏移（半音）；线性插值，端点外取端点值。"""
    if not curve or len(curve) < 2:
        return 0.0
    if t <= curve[0]["t"]:
        return float(curve[0]["v"])
    if t >= curve[-1]["t"]:
        return float(curve[-1]["v"])
    for index in range(1, len(curve)):
        prev = curve[index - 1]
        nxt = curve[index]
        if t <= nxt["t"]:
            delta = nxt["t"] - prev["t"]
            if delta <= 1e-6:
                return float(nxt["v"])
            ratio = (t - prev["t"]) / delta
            return float(prev["v"]) + (float(nxt["v"]) - float(prev["v"])) * ratio
    return float(curve[-1]["v"])


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
    curve = clamp_curve(raw.get("curve"), end - start)
    if curve:
        note["curve"] = curve
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
