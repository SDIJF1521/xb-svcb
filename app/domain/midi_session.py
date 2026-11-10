"""MIDI 编曲（多乐器音序器）的领域模型。

和 ``editor_midi``（片段音高重绘）不同，这里描述的是「从零写一首曲子」：

* 一个会话（session）有速度（BPM）、拍号，以及多个声部（part）；
* 每个声部就是一件乐器（GM program），有自己的音色、音量、声像、静音/独奏；
* 音符以秒为单位记录起止、音高与力度（velocity）。

领域层只做纯计算：归一化输入、算会话长度、把老版单轨音符迁移成单声部会话。
真正的合成与文件读写分别放在用例层与 ``midi_file``。
"""

from __future__ import annotations

import math
from typing import Any

from . import midi_drums, midi_instruments

SESSION_VERSION = 1

# 声部与音符上限：防止误导入超大 MIDI 撑爆工程。
MAX_PARTS = 24
MAX_NOTES_PER_PART = 20000
MAX_NOTES_TOTAL = 60000
# 会话时长上限：不设小时级限制（24 小时足够覆盖任何实际编曲），只兜底避免极端输入。
MAX_SESSION_SECONDS = 86400.0
MIN_SESSION_SECONDS = 0.05
MIN_NOTE_SECONDS = 0.02
DEFAULT_NOTE_SECONDS = 0.25
DEFAULT_VELOCITY = 100
MIN_VELOCITY = 1
MAX_VELOCITY = 127
MIN_TEMPO = 20.0
MAX_TEMPO = 400.0
DEFAULT_TEMPO = 120.0
MIN_PITCH = 0
MAX_PITCH = 127
# GM 的鼓组通道（0 起算的第 10 通道）。
DRUM_CHANNEL = 9
MAX_CHANNEL = 15
TIME_SIGNATURE_CHOICES: tuple[tuple[int, int], ...] = (
    (2, 4),
    (3, 4),
    (4, 4),
    (5, 4),
    (6, 8),
    (7, 8),
    (3, 8),
    (12, 8),
)

# 声部配色：深浅都能看清，且和编辑器主题（青蓝）不冲突。
PART_COLORS: tuple[str, ...] = (
    "#5ec2ff",
    "#ffb454",
    "#8ee36b",
    "#ff7a9c",
    "#b98cff",
    "#4fd8c8",
    "#ffd166",
    "#7fa6ff",
)

_DEFAULT_PART_NAMES: tuple[str, ...] = (
    "旋律",
    "和声",
    "贝斯",
    "节奏",
    "副旋律",
    "铺底",
    "打击",
    "点缀",
)


def _to_float(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) else fallback


def _round(value: float, digits: int = 3) -> float:
    return round(float(value), digits)


def clamp_tempo(value: Any) -> float:
    tempo = _to_float(value, DEFAULT_TEMPO)
    return _round(max(MIN_TEMPO, min(MAX_TEMPO, tempo)), 2)


def clamp_velocity(value: Any) -> int:
    velocity = _to_float(value, DEFAULT_VELOCITY)
    return int(max(MIN_VELOCITY, min(MAX_VELOCITY, round(velocity))))


def clamp_pitch(value: Any) -> int:
    pitch = _to_float(value, 60.0)
    return int(max(MIN_PITCH, min(MAX_PITCH, round(pitch))))


def clamp_channel(value: Any, *, drum: bool) -> int:
    if drum:
        return DRUM_CHANNEL
    channel = _to_float(value, 0.0)
    result = int(max(0, min(MAX_CHANNEL, round(channel))))
    # 旋律声部不能占用鼓组通道，否则渲染与导出都会变成打击乐。
    return 0 if result == DRUM_CHANNEL else result


def clamp_gain(value: Any) -> float:
    gain = _to_float(value, 1.0)
    return _round(max(0.0, min(2.0, gain)), 3)


def clamp_pan(value: Any) -> float:
    pan = _to_float(value, 0.0)
    return _round(max(-1.0, min(1.0, pan)), 3)


def clamp_time_signature(raw: Any) -> tuple[int, int]:
    """拍号只接受常见组合；其它输入回落到 4/4。"""
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        numerator = int(_to_float(raw[0], 4.0))
        denominator = int(_to_float(raw[1], 4.0))
    elif isinstance(raw, str) and "/" in raw:
        left, _, right = raw.partition("/")
        numerator = int(_to_float(left, 4.0))
        denominator = int(_to_float(right, 4.0))
    else:
        return (4, 4)
    pair = (numerator, denominator)
    return pair if pair in TIME_SIGNATURE_CHOICES else (4, 4)


def clean_note_for_part(
    raw: Any,
    duration: float,
    *,
    index: int = 0,
    part_id: str = "",
) -> dict[str, Any] | None:
    """归一化单个编曲音符；无法使用时返回 None。"""
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
    if end - start < MIN_NOTE_SECONDS:
        return None
    note_id = str(raw.get("id") or "").strip()
    prefix = part_id or "n"
    return {
        "id": note_id or f"{prefix}_{index + 1}",
        "start": _round(start),
        "end": _round(end),
        "pitch": clamp_pitch(raw.get("pitch", 60.0)),
        "velocity": clamp_velocity(raw.get("velocity", DEFAULT_VELOCITY)),
    }


def clean_notes_for_part(
    raw: Any,
    duration: float,
    *,
    part_id: str = "",
    limit: int = MAX_NOTES_PER_PART,
) -> list[dict[str, Any]]:
    """归一化一个声部的音符：裁剪、排序、去重 ID（允许同音重叠，不做截断）。"""
    if not isinstance(raw, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for index, item in enumerate(raw[: max(0, int(limit))]):
        note = clean_note_for_part(item, duration, index=index, part_id=part_id)
        if note is not None:
            cleaned.append(note)
    cleaned.sort(key=lambda note: (note["start"], note["pitch"]))
    seen: set[str] = set()
    for index, note in enumerate(cleaned):
        if note["id"] in seen:
            note["id"] = f"{part_id or 'n'}_{index + 1}"
        seen.add(note["id"])
    return cleaned


def _part_id(raw: Any, index: int, taken: set[str]) -> str:
    candidate = str(raw or "").strip()
    if not candidate or candidate in taken:
        candidate = f"part_{index + 1}"
        suffix = 2
        while candidate in taken:
            candidate = f"part_{index + 1}_{suffix}"
            suffix += 1
    taken.add(candidate)
    return candidate


def clean_part(
    raw: Any,
    duration: float,
    *,
    index: int = 0,
    taken_ids: set[str] | None = None,
    note_budget: int = MAX_NOTES_PER_PART,
) -> dict[str, Any]:
    """归一化单个声部（乐器 + 音符）。"""
    source = raw if isinstance(raw, dict) else {}
    taken = taken_ids if taken_ids is not None else set()
    part_id = _part_id(source.get("id"), index, taken)
    drum = bool(source.get("drum") or source.get("is_drum"))
    program = midi_instruments.clamp_program(source.get("instrument", 0))
    color = str(source.get("color") or "").strip()
    if not color.startswith("#") or len(color) not in (4, 7):
        color = PART_COLORS[index % len(PART_COLORS)]
    name = str(source.get("name") or "").strip()
    if not name:
        base = midi_instruments.name_of(program)
        name = "架子鼓" if drum else (base or _DEFAULT_PART_NAMES[index % len(_DEFAULT_PART_NAMES)])
    notes = clean_notes_for_part(
        source.get("notes"), duration, part_id=part_id, limit=note_budget
    )
    if drum:
        # 鼓组没有「音高」，只有鼓件：把音高吸附到 GM 打击乐表里的真实鼓件。
        notes = midi_drums.normalize_notes(notes)
    return {
        "id": part_id,
        "name": name[:48],
        "instrument": program,
        "drum": drum,
        "channel": clamp_channel(source.get("channel", index % 16), drum=drum),
        "volume": clamp_gain(source.get("volume", 1.0)),
        "pan": clamp_pan(source.get("pan", 0.0)),
        "mute": bool(source.get("mute")),
        "solo": bool(source.get("solo")),
        "color": color,
        "notes": notes,
    }


def clean_session(
    raw: Any,
    duration: float | None = None,
    *,
    default_tempo: float = DEFAULT_TEMPO,
) -> dict[str, Any]:
    """归一化整个会话；时长以传入值为上限（一般取轨道/工程长度）。"""
    source = raw if isinstance(raw, dict) else {}
    limit = max(
        MIN_SESSION_SECONDS,
        min(MAX_SESSION_SECONDS, _to_float(duration, 60.0)),
    )
    tempo = clamp_tempo(source.get("tempo", default_tempo))
    signature = clamp_time_signature(source.get("time_signature"))
    raw_parts = source.get("parts")
    parts_in = raw_parts if isinstance(raw_parts, list) else []
    parts: list[dict[str, Any]] = []
    taken: set[str] = set()
    budget = MAX_NOTES_PER_PART
    for index, item in enumerate(parts_in[:MAX_PARTS]):
        part = clean_part(item, limit, index=index, taken_ids=taken, note_budget=budget)
        parts.append(part)
    if not parts:
        parts = [new_part(0, index=0)]
    # 总音符数兜底：从后往前砍，保证前面的声部完整。
    total = 0
    for part in parts:
        if total + len(part["notes"]) > MAX_NOTES_TOTAL:
            keep = max(0, MAX_NOTES_TOTAL - total)
            part["notes"] = part["notes"][:keep]
        total += len(part["notes"])
    return {
        "version": SESSION_VERSION,
        "tempo": tempo,
        "time_signature": [signature[0], signature[1]],
        "parts": parts,
        "name": str(source.get("name") or "").strip()[:64],
        "loop": bool(source.get("loop")),
        "metronome": bool(source.get("metronome")),
    }


def new_part(program: Any = 0, *, index: int = 0, drum: bool = False) -> dict[str, Any]:
    """新建一个空声部（鼓组声部固定走第 10 通道，音色即 GM 鼓组）。"""
    resolved = DRUM_CHANNEL if drum else midi_instruments.clamp_program(program)
    return {
        "id": f"part_{index + 1}",
        "name": "架子鼓" if drum else midi_instruments.name_of(resolved),
        "instrument": resolved if not drum else 0,
        "drum": bool(drum),
        "channel": DRUM_CHANNEL if drum else (index % MAX_CHANNEL if index % MAX_CHANNEL != DRUM_CHANNEL else 0),
        "volume": 1.0,
        "pan": 0.0,
        "mute": False,
        "solo": False,
        "color": PART_COLORS[index % len(PART_COLORS)],
        "notes": [],
    }


def session_duration(session: dict[str, Any]) -> float:
    """会话实际用到的长度（最后一个音的结束时间）。"""
    end = 0.0
    for part in session.get("parts") or []:
        for note in part.get("notes") or []:
            try:
                end = max(end, float(note.get("end") or 0.0))
            except (TypeError, ValueError):
                continue
    return _round(end)


def session_note_count(session: dict[str, Any]) -> int:
    return sum(len(part.get("notes") or []) for part in session.get("parts") or [])


def part_note_bounds(part: dict[str, Any]) -> tuple[float, float] | None:
    """声部的时间范围；没有音符返回 None。"""
    notes = part.get("notes") or []
    if not notes:
        return None
    try:
        start = min(float(note.get("start") or 0.0) for note in notes)
        end = max(float(note.get("end") or 0.0) for note in notes)
    except (TypeError, ValueError):
        return None
    if end - start < MIN_NOTE_SECONDS:
        return None
    return (_round(start), _round(end))


def audible_parts(session: dict[str, Any], *, solo_only: bool = False) -> list[dict[str, Any]]:
    """实际会发声的声部：处理独奏/静音，并跳过没有音符的声部。"""
    parts = [part for part in session.get("parts") or [] if part.get("notes")]
    if not parts:
        return []
    soloed = [part for part in parts if part.get("solo")]
    if soloed:
        return soloed
    if solo_only:
        return []
    return [part for part in parts if not part.get("mute")]


def session_from_notes(
    notes: Any,
    *,
    duration: float,
    instrument: Any = 0,
    name: str = "旋律",
) -> dict[str, Any]:
    """把老版单轨音符（没有力度/声部）迁移成单声部会话。"""
    cleaned: list[dict[str, Any]] = []
    if isinstance(notes, list):
        for index, item in enumerate(notes):
            if not isinstance(item, dict):
                continue
            note = clean_note_for_part(
                {**item, "velocity": item.get("velocity", DEFAULT_VELOCITY)},
                duration,
                index=index,
                part_id="part_1",
            )
            if note is not None:
                cleaned.append(note)
    program = midi_instruments.clamp_program(instrument)
    part = {
        "id": "part_1",
        "name": str(name or "旋律")[:48],
        "instrument": program,
        "drum": False,
        "channel": 0,
        "volume": 1.0,
        "pan": 0.0,
        "mute": False,
        "solo": False,
        "color": PART_COLORS[0],
        "notes": cleaned,
    }
    return clean_session(
        {
            "version": SESSION_VERSION,
            "tempo": DEFAULT_TEMPO,
            "time_signature": [4, 4],
            "parts": [part],
        },
        duration,
    )


def session_summary(session: dict[str, Any]) -> dict[str, Any]:
    """工程元数据里记录的摘要（避免把整首音符塞进 metadata）。"""
    return {
        "tempo": session.get("tempo"),
        "time_signature": list(session.get("time_signature") or [4, 4]),
        "parts": len(session.get("parts") or []),
        "note_count": session_note_count(session),
        "duration": session_duration(session),
    }
