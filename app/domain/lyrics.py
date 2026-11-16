"""歌词解析与切句时序（领域层）。

LRC / 普通 TXT 歌词的解析、按比例自动配时、以及根据静音区间推导演唱范围。
全部是纯函数：不读写文件、不认识编辑器工程的存储格式。
"""

from __future__ import annotations

import re
from typing import Any

# [mm:ss.xxx] / [mm:ss:xxx] 时间戳；最多三位小数。
_STAMP_RE = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
# LRC 元信息行（[ar:…] 等）不是歌词正文。
_METADATA_RE = re.compile(r"^\[(?:ar|ti|al|by|offset|length|re|ve):", re.IGNORECASE)
# 句末标点：普通 TXT 歌词按句子切分。
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])\s*")
# 计算句子权重时剔除的标点与空白。
_WEIGHT_STRIP_RE = re.compile(r"[\s，。！？!?；;、,.]")

MAX_LINES = 500
MAX_LINE_LENGTH = 500


def parse_lyric_lines(lyrics: Any) -> list[dict[str, Any]]:
    """解析带时间轴的歌词，返回按时间排序的 ``{time, text}`` 列表。

    支持两种输入：已经结构化的 ``[{"time": …, "text": …}]``，以及 LRC 文本。
    """
    lines: list[dict[str, Any]] = []
    if isinstance(lyrics, list):
        for item in lyrics:
            if not isinstance(item, dict):
                continue
            try:
                time_value = float(item.get("time") or item.get("start") or 0.0)
            except (TypeError, ValueError):
                continue
            if time_value < 0:
                continue
            lines.append({"time": round(time_value, 3), "text": str(item.get("text") or "")})
        return sorted(lines, key=lambda x: float(x["time"]))

    text = str(lyrics or "")
    for raw in text.splitlines():
        matches = list(_STAMP_RE.finditer(raw))
        if not matches:
            continue
        body = _STAMP_RE.sub("", raw).strip()
        for match in matches:
            minute = int(match.group(1))
            second = int(match.group(2))
            fraction_raw = match.group(3) or "0"
            fraction = int(fraction_raw) / (10 ** len(fraction_raw))
            lines.append(
                {
                    "time": round(minute * 60 + second + fraction, 3),
                    "text": body,
                }
            )
    return sorted(lines, key=lambda x: float(x["time"]))


def parse_plain_lyric_lines(lyrics: Any) -> list[str]:
    """解析没有时间轴的 TXT 歌词，只切句、不臆造时间戳。"""
    if isinstance(lyrics, list):
        values = [str(item.get("text") or "") for item in lyrics if isinstance(item, dict)]
    else:
        values = str(lyrics or "").splitlines()
    sentences: list[str] = []
    for value in values:
        value = value.strip().lstrip("\ufeff")
        if not value or _METADATA_RE.match(value):
            continue
        for sentence in _SENTENCE_SPLIT_RE.split(value):
            sentence = sentence.strip()
            if sentence:
                sentences.append(sentence[:MAX_LINE_LENGTH])
    return sentences[:MAX_LINES]


def auto_time_lyric_lines(
    texts: list[str],
    duration: float,
    silence_points: list[float],
    min_clip: float,
) -> list[dict[str, Any]]:
    """把无时间戳的句子按长度比例分配时间，并吸附到附近的静音点。"""
    if not texts or duration <= 0:
        return []
    weights = [max(1, len(_WEIGHT_STRIP_RE.sub("", text))) for text in texts]
    total_weight = max(1, sum(weights))
    cumulative = 0
    targets: list[float] = []
    for weight in weights[:-1]:
        cumulative += weight
        targets.append(duration * cumulative / total_weight)

    points = sorted(
        {
            max(0.0, min(duration, float(point)))
            for point in silence_points
            if 0.0 < float(point) < duration
        }
    )
    boundaries = [0.0]
    for index, target in enumerate(targets):
        remaining = len(targets) - index
        lower = boundaries[-1] + min_clip
        upper = duration - remaining * min_clip
        if upper < lower:
            lower = upper = max(boundaries[-1], min(duration, target))
        eligible = [point for point in points if lower <= point <= upper]
        chosen = min(eligible, key=lambda point: abs(point - target)) if eligible else target
        boundaries.append(max(lower, min(upper, chosen)))

    return [
        {"time": round(boundaries[index], 3), "text": text}
        for index, text in enumerate(texts)
    ]


def speech_ranges_from_silence(
    duration: float,
    silences: list[dict[str, float]],
    min_clip: float,
    padding: float,
    min_silence: float,
) -> list[tuple[float, float]]:
    """根据静音区间推导非静音（演唱）范围，并合并过近的片段。"""
    ranges: list[tuple[float, float]] = []
    cursor = 0.0
    for silence in sorted(silences, key=lambda x: float(x.get("start") or 0.0)):
        try:
            silence_start = max(0.0, min(duration, float(silence.get("start") or 0.0)))
            silence_end = max(silence_start, min(duration, float(silence.get("end") or 0.0)))
        except (TypeError, ValueError):
            continue
        if silence_end - silence_start < min_silence:
            continue
        if silence_start - cursor >= min_clip:
            ranges.append(
                (
                    max(0.0, cursor - padding),
                    min(duration, silence_start + padding),
                )
            )
        cursor = max(cursor, silence_end)
    if duration - cursor >= min_clip:
        ranges.append((max(0.0, cursor - padding), duration))

    merged: list[tuple[float, float]] = []
    for start, end in ranges:
        if end - start < min_clip:
            continue
        if merged and start <= merged[-1][1] + 0.01:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((round(start, 3), round(end, 3)))
    return merged
