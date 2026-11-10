"""架子鼓（GM 打击乐）音高映射。

MIDI 的鼓组没有「音高」，只有**鼓件**：第 10 通道上每个音高对应一件打击乐器
（35 = 底鼓、38 = 军鼓、42 = 闭合踩镲……）。这套映射是 GM 标准，鼓组渲染、
导出 ``.mid``、钢琴卷帘左侧的键名、以及新建音符时的吸附都用同一张表。

domain 只放数据：每件鼓件的名称、分组、以及合成时需要的音色参数
（基频 / 衰减 / 噪声 / 金属感 / 互斥组）。合成与 UI 各自读同一份。
"""

from __future__ import annotations

from typing import Any

# 互斥组：踩镲之间会互相「掐断」（开镲遇到闭合踩镲会被截断）。
CHOKE_HATS = 1

# (pitch, 中文名, 英文名, 分组, 基频Hz, 衰减速度, 噪声比例, 金属感, 互斥组)
_RAW: tuple[tuple[int, str, str, str, float, float, float, float, int], ...] = (
    (35, "底鼓 2", "Acoustic Bass Drum", "kick", 52.0, 8.5, 0.22, 0.0, 0),
    (36, "底鼓 1", "Bass Drum 1", "kick", 58.0, 9.5, 0.22, 0.0, 0),
    (37, "军鼓边击", "Side Stick", "rim", 320.0, 55.0, 0.45, 0.15, 0),
    (38, "军鼓 1", "Acoustic Snare", "snare", 190.0, 15.0, 0.85, 0.0, 0),
    (39, "拍手", "Hand Clap", "clap", 0.0, 24.0, 1.0, 0.0, 0),
    (40, "军鼓 2", "Electric Snare", "snare", 212.0, 16.0, 0.9, 0.0, 0),
    (41, "落地嗵鼓（低）", "Low Floor Tom", "tom", 88.0, 8.0, 0.1, 0.0, 0),
    (42, "闭合踩镲", "Closed Hi-Hat", "hat", 0.0, 68.0, 1.0, 1.0, CHOKE_HATS),
    (43, "落地嗵鼓（高）", "High Floor Tom", "tom", 104.0, 8.0, 0.1, 0.0, 0),
    (44, "踩镲踏板", "Pedal Hi-Hat", "hat", 0.0, 58.0, 1.0, 1.0, CHOKE_HATS),
    (45, "低音通鼓", "Low Tom", "tom", 124.0, 7.5, 0.1, 0.0, 0),
    (46, "开音踩镲", "Open Hi-Hat", "hat_open", 0.0, 8.5, 1.0, 1.0, CHOKE_HATS),
    (47, "中低通鼓", "Low-Mid Tom", "tom", 148.0, 7.5, 0.1, 0.0, 0),
    (48, "中高通鼓", "Hi-Mid Tom", "tom", 176.0, 7.0, 0.1, 0.0, 0),
    (49, "吊镲 1", "Crash Cymbal 1", "crash", 0.0, 2.2, 1.0, 1.0, 0),
    (50, "高音通鼓", "High Tom", "tom", 208.0, 6.5, 0.1, 0.0, 0),
    (51, "叮叮镲 1", "Ride Cymbal 1", "ride", 0.0, 3.0, 1.0, 1.0, 0),
    (52, "中国镲", "Chinese Cymbal", "crash", 0.0, 1.9, 1.0, 1.0, 0),
    (53, "叮叮镲铃", "Ride Bell", "ride", 1180.0, 4.5, 0.35, 1.0, 0),
    (54, "铃鼓", "Tambourine", "perc", 0.0, 20.0, 1.0, 0.6, 0),
    (55, "水镲", "Splash Cymbal", "crash", 0.0, 4.0, 1.0, 1.0, 0),
    (56, "牛铃", "Cowbell", "perc", 540.0, 11.0, 0.08, 0.2, 0),
    (57, "吊镲 2", "Crash Cymbal 2", "crash", 0.0, 2.0, 1.0, 1.0, 0),
    (58, "颤音板", "Vibraslap", "perc", 420.0, 5.0, 0.5, 0.2, 0),
    (59, "叮叮镲 2", "Ride Cymbal 2", "ride", 0.0, 3.0, 1.0, 1.0, 0),
    (60, "邦戈鼓（高）", "Hi Bongo", "perc", 400.0, 18.0, 0.15, 0.0, 0),
    (61, "邦戈鼓（低）", "Low Bongo", "perc", 300.0, 18.0, 0.15, 0.0, 0),
    (62, "康加鼓（闷）", "Mute Hi Conga", "perc", 350.0, 20.0, 0.12, 0.0, 0),
    (63, "康加鼓（开）", "Open Hi Conga", "perc", 350.0, 12.0, 0.15, 0.0, 0),
    (64, "康加鼓（低）", "Low Conga", "perc", 240.0, 13.0, 0.15, 0.0, 0),
    (65, "天巴鼓（高）", "High Timbale", "perc", 360.0, 15.0, 0.2, 0.0, 0),
    (66, "天巴鼓（低）", "Low Timbale", "perc", 290.0, 15.0, 0.2, 0.0, 0),
    (67, "阿哥哥（高）", "High Agogo", "perc", 820.0, 12.0, 0.05, 0.3, 0),
    (68, "阿哥哥（低）", "Low Agogo", "perc", 620.0, 12.0, 0.05, 0.3, 0),
    (69, "沙锤（卡巴萨）", "Cabasa", "perc", 0.0, 34.0, 1.0, 0.5, 0),
    (70, "沙铃", "Maracas", "perc", 0.0, 38.0, 1.0, 0.4, 0),
    (71, "短哨", "Short Whistle", "perc", 2200.0, 6.0, 0.3, 0.0, 0),
    (72, "长哨", "Long Whistle", "perc", 2100.0, 2.4, 0.3, 0.0, 0),
    (73, "短刮胡", "Short Guiro", "perc", 0.0, 28.0, 1.0, 0.0, 0),
    (74, "长刮胡", "Long Guiro", "perc", 0.0, 12.0, 1.0, 0.0, 0),
    (75, "响木", "Claves", "perc", 2400.0, 40.0, 0.1, 0.2, 0),
    (76, "木鱼（高）", "Hi Wood Block", "perc", 1250.0, 32.0, 0.12, 0.0, 0),
    (77, "木鱼（低）", "Low Wood Block", "perc", 900.0, 32.0, 0.12, 0.0, 0),
    (78, "库伊卡（闷）", "Mute Cuica", "perc", 220.0, 9.0, 0.25, 0.0, 0),
    (79, "库伊卡（开）", "Open Cuica", "perc", 200.0, 6.0, 0.25, 0.0, 0),
    (80, "三角铁（闷）", "Mute Triangle", "perc", 3100.0, 9.0, 0.15, 1.0, 0),
    (81, "三角铁（开）", "Open Triangle", "perc", 3200.0, 5.0, 0.15, 1.0, 0),
)

_GROUP_LABELS: dict[str, str] = {
    "kick": "底鼓",
    "snare": "军鼓",
    "rim": "边击",
    "clap": "拍手",
    "hat": "踩镲",
    "hat_open": "开镲",
    "tom": "通鼓",
    "crash": "吊镲",
    "ride": "叮叮镲",
    "perc": "小打",
}

DRUM_PITCH_MIN = min(item[0] for item in _RAW)
DRUM_PITCH_MAX = max(item[0] for item in _RAW)

PIECES: tuple[dict[str, Any], ...] = tuple(
    {
        "pitch": pitch,
        "name_zh": name_zh,
        "name_en": name_en,
        "group": group,
        "group_zh": _GROUP_LABELS.get(group, "小打"),
        "tone": tone,
        "decay": decay,
        "noise": noise,
        "metallic": metallic,
        "choke": choke,
    }
    for pitch, name_zh, name_en, group, tone, decay, noise, metallic, choke in _RAW
)

_BY_PITCH: dict[int, dict[str, Any]] = {piece["pitch"]: piece for piece in PIECES}


def pieces() -> list[dict[str, Any]]:
    """全部鼓件（按音高排序），前端直接拿来画鼓组键位。"""
    return [dict(piece) for piece in PIECES]


def pitch_list() -> list[int]:
    return [piece["pitch"] for piece in PIECES]


def has_pitch(pitch: Any) -> bool:
    try:
        return int(round(float(pitch))) in _BY_PITCH
    except (TypeError, ValueError):
        return False


def piece(pitch: Any) -> dict[str, Any]:
    """音高 → 鼓件；不在鼓组表里的音高落到最接近的鼓件。"""
    return _BY_PITCH.get(_clamp_int(pitch)) or _BY_PITCH[nearest_pitch(pitch)]


def name_zh(pitch: Any) -> str:
    return str(piece(pitch)["name_zh"])


def group_of(pitch: Any) -> str:
    return str(piece(pitch)["group"])


def nearest_pitch(pitch: Any, *, lo: int | None = None, hi: int | None = None) -> int:
    """最接近的鼓件音高：新建/拖动鼓音符时吸附到真实鼓件上。"""
    target = _clamp_int(pitch)
    low = DRUM_PITCH_MIN if lo is None else max(DRUM_PITCH_MIN, int(lo))
    high = DRUM_PITCH_MAX if hi is None else min(DRUM_PITCH_MAX, int(hi))
    candidates = [value for value in _BY_PITCH if low <= value <= high]
    if not candidates:
        candidates = list(_BY_PITCH)
    return min(candidates, key=lambda value: (abs(value - target), value))


def _clamp_int(value: Any) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return 38
    return max(DRUM_PITCH_MIN, min(DRUM_PITCH_MAX, number))


def normalize_notes(notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把鼓组音符的音高吸附到真实鼓件上（导入/归一化时用）。"""
    snapped: list[dict[str, Any]] = []
    for note in notes:
        target = nearest_pitch(note.get("pitch", 38))
        snapped.append({**note, "pitch": target} if target != note.get("pitch") else note)
    return snapped
