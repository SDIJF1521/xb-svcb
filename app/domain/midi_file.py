"""标准 MIDI 文件（SMF，``.mid``）的读写。

编曲子编辑器要能「生成音乐文件」，其中最通用的一步就是导出多轨 MIDI：
一个声部一条 MTrk，带音色（Program Change）、声部名、音量/声像与力度。

这里只依赖标准库：读取时支持 format 0/1、running status、tempo map；
写入时按 format 1 生成（第 1 轨放速度与拍号，之后每个声部一轨）。
"""

from __future__ import annotations

import struct
from typing import Any

from . import midi_instruments, midi_session

DEFAULT_TICKS_PER_QUARTER = 480
_MAX_DATA_LEN = 0x0FFFFFFF


# --------------------------------------------------------------------- 写入


def _varlen(value: int) -> bytes:
    value = max(0, int(value))
    buffer = [value & 0x7F]
    value >>= 7
    while value:
        buffer.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(buffer))


def _meta(kind: int, payload: bytes) -> bytes:
    return bytes([0xFF, kind]) + _varlen(len(payload)) + payload


def _track_chunk(events: list[tuple[int, bytes]]) -> bytes:
    events = sorted(events, key=lambda item: item[0])
    body = bytearray()
    previous_tick = 0
    for tick, data in events:
        body += _varlen(max(0, tick - previous_tick))
        body += data
        previous_tick = max(previous_tick, tick)
    body += _varlen(0) + _meta(0x2F, b"")
    return b"MTrk" + struct.pack(">I", len(body)) + bytes(body)


def _seconds_per_tick(tempo: float, ticks_per_quarter: int) -> float:
    return 60.0 / max(midi_session.MIN_TEMPO, tempo) / max(1, ticks_per_quarter)


def build_smf(
    session: dict[str, Any],
    *,
    ticks_per_quarter: int = DEFAULT_TICKS_PER_QUARTER,
    include_muted: bool = False,
) -> bytes:
    """把编曲会话写成 SMF（format 1）。"""
    tempo = midi_session.clamp_tempo(session.get("tempo"))
    numerator, denominator = midi_session.clamp_time_signature(session.get("time_signature"))
    tpq = max(24, min(9600, int(ticks_per_quarter or DEFAULT_TICKS_PER_QUARTER)))
    seconds_per_tick = _seconds_per_tick(tempo, tpq)
    parts = (
        [part for part in session.get("parts") or [] if part.get("notes")]
        if include_muted
        else midi_session.audible_parts(session)
    )

    def to_ticks(seconds: float) -> int:
        return max(0, int(round(float(seconds) / seconds_per_tick)))

    # 第 1 轨：速度与拍号。
    conductor: list[tuple[int, bytes]] = [
        (0, _meta(0x03, "Tempo / Time Signature".encode("utf-8"))),
        (
            0,
            _meta(
                0x51,
                int(round(60_000_000.0 / tempo)).to_bytes(3, "big"),
            ),
        ),
        (0, _meta(0x58, bytes([numerator, _denominator_power(denominator), 24, 8]))),
    ]
    tracks = [_track_chunk(conductor)]

    for index, part in enumerate(parts):
        channel = midi_session.clamp_channel(
            part.get("channel", index % 16), drum=bool(part.get("drum"))
        )
        program = midi_instruments.clamp_program(part.get("instrument", 0))
        name = str(part.get("name") or f"Part {index + 1}")
        events: list[tuple[int, bytes]] = [
            (0, _meta(0x03, name.encode("utf-8")[:127])),
            (0, bytes([0xC0 | channel, program])),
            (
                0,
                bytes(
                    [
                        0xB0 | channel,
                        7,
                        int(max(0, min(127, round(float(part.get("volume", 1.0) or 1.0) * 100)))),
                    ]
                ),
            ),
            (
                0,
                bytes(
                    [
                        0xB0 | channel,
                        10,
                        int(max(0, min(127, round((float(part.get("pan", 0.0) or 0.0) + 1.0) * 63.5)))),
                    ]
                ),
            ),
        ]
        for note in part.get("notes") or []:
            start = to_ticks(note.get("start", 0.0))
            end = max(start + 1, to_ticks(note.get("end", 0.0)))
            pitch = midi_session.clamp_pitch(note.get("pitch", 60))
            velocity = midi_session.clamp_velocity(note.get("velocity", midi_session.DEFAULT_VELOCITY))
            events.append((start, bytes([0x90 | channel, pitch, velocity])))
            events.append((end, bytes([0x80 | channel, pitch, 0x40])))
        tracks.append(_track_chunk(events))

    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), tpq)
    data = header + b"".join(tracks)
    if len(data) > _MAX_DATA_LEN:
        raise ValueError("MIDI 数据过大")
    return data


def _denominator_power(denominator: int) -> int:
    power = 0
    value = max(1, int(denominator))
    while value > 1 and power < 8:
        value //= 2
        power += 1
    return power


# --------------------------------------------------------------------- 读取


class MidiFileError(ValueError):
    """无法识别的 MIDI 文件。"""


def _read_varlen(data: bytes, index: int) -> tuple[int, int]:
    value = 0
    for _ in range(4):
        if index >= len(data):
            raise MidiFileError("MIDI 数据在变长整数处提前结束")
        byte = data[index]
        index += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, index
    raise MidiFileError("MIDI 变长整数过长")


def parse_smf(data: bytes) -> dict[str, Any]:
    """解析 SMF，返回速度、拍号与各轨音符（秒为单位）。"""
    if len(data) < 14 or data[:4] != b"MThd":
        raise MidiFileError("不是标准 MIDI 文件（缺少 MThd）")
    header_length = struct.unpack(">I", data[4:8])[0]
    _fmt, track_count, division = struct.unpack(">HHH", data[8:14])
    ticks_per_quarter = division if division and division < 0x8000 else DEFAULT_TICKS_PER_QUARTER
    index = 8 + header_length

    raw_tracks: list[dict[str, Any]] = []
    tempo_changes: list[tuple[int, float]] = []
    time_signature: tuple[int, int] = (4, 4)

    while index + 8 <= len(data) and len(raw_tracks) < max(1, track_count):
        chunk_type = data[index : index + 4]
        chunk_length = struct.unpack(">I", data[index + 4 : index + 8])[0]
        start = index + 8
        end = min(len(data), start + chunk_length)
        index = end
        if chunk_type != b"MTrk":
            continue
        track, tempos, signature = _parse_track(data[start:end])
        raw_tracks.append(track)
        tempo_changes.extend(tempos)
        if signature is not None:
            time_signature = signature

    tempo_changes.sort(key=lambda item: item[0])
    tempo = tempo_changes[0][1] if tempo_changes else midi_session.DEFAULT_TEMPO
    seconds_per_tick_map = _tick_to_seconds_map(tempo_changes, ticks_per_quarter)

    parsed_tracks: list[dict[str, Any]] = []
    for track in raw_tracks:
        notes = []
        for note in track["notes"]:
            begin = _tick_to_seconds(seconds_per_tick_map, note["start_tick"], ticks_per_quarter)
            finish = _tick_to_seconds(seconds_per_tick_map, note["end_tick"], ticks_per_quarter)
            if finish - begin < midi_session.MIN_NOTE_SECONDS:
                continue
            notes.append(
                {
                    "start": round(begin, 3),
                    "end": round(finish, 3),
                    "pitch": note["pitch"],
                    "velocity": note["velocity"],
                }
            )
        if not notes:
            continue
        notes.sort(key=lambda item: (item["start"], item["pitch"]))
        parsed_tracks.append(
            {
                "name": track["name"],
                "program": midi_instruments.clamp_program(track["program"]),
                "channel": track["channel"],
                "drum": track["channel"] == midi_session.DRUM_CHANNEL,
                "notes": notes,
            }
        )

    return {
        "ticks_per_quarter": ticks_per_quarter,
        "tempo": round(tempo, 2),
        "time_signature": [int(time_signature[0]), int(time_signature[1])],
        "tracks": parsed_tracks,
    }


def _tick_to_seconds_map(
    tempo_changes: list[tuple[int, float]], ticks_per_quarter: int
) -> list[tuple[int, float, float]]:
    """(tick, tempo, 该点累计秒数) 映射表，用于 tempo map 换算。"""
    mapping: list[tuple[int, float, float]] = [(0, midi_session.DEFAULT_TEMPO, 0.0)]
    for tick, tempo in tempo_changes:
        previous_tick, previous_tempo, previous_seconds = mapping[-1]
        if tick <= previous_tick:
            mapping[-1] = (previous_tick, tempo, previous_seconds)
            continue
        elapsed = (tick - previous_tick) * 60.0 / previous_tempo / max(1, ticks_per_quarter)
        mapping.append((tick, tempo, previous_seconds + elapsed))
    return mapping


def _tick_to_seconds(
    mapping: list[tuple[int, float, float]], tick: int, ticks_per_quarter: int
) -> float:
    current = mapping[0]
    for entry in mapping:
        if entry[0] <= tick:
            current = entry
        else:
            break
    base_tick, tempo, base_seconds = current
    return base_seconds + (tick - base_tick) * 60.0 / max(midi_session.MIN_TEMPO, tempo) / max(
        1, ticks_per_quarter
    )


def _parse_track(
    data: bytes,
) -> tuple[dict[str, Any], list[tuple[int, float]], tuple[int, int] | None]:
    notes: list[dict[str, int]] = []
    open_notes: dict[tuple[int, int], list[tuple[int, int]]] = {}
    program = 0
    channel = 0
    name = ""
    tempos: list[tuple[int, float]] = []
    signature: tuple[int, int] | None = None
    tick = 0
    index = 0
    running_status = 0

    while index < len(data):
        delta, index = _read_varlen(data, index)
        tick += delta
        if index >= len(data):
            break
        status = data[index]
        if status & 0x80:
            index += 1
            if status < 0xF0:
                running_status = status
        else:
            status = running_status
            if not status:
                break

        if status == 0xFF:
            if index >= len(data):
                break
            kind = data[index]
            index += 1
            length, index = _read_varlen(data, index)
            payload = data[index : index + length]
            index += length
            if kind == 0x03 and payload and not name:
                name = payload.decode("utf-8", errors="replace").strip("\x00").strip()
            elif kind == 0x51 and len(payload) >= 3:
                micros = int.from_bytes(payload[:3], "big")
                if micros > 0:
                    tempos.append((tick, round(60_000_000.0 / micros, 2)))
            elif kind == 0x58 and len(payload) >= 2:
                numerator = max(1, payload[0])
                denominator = 2 ** min(8, payload[1])
                signature = (numerator, denominator)
            elif kind == 0x2F:
                break
            continue

        if status in (0xF0, 0xF7):
            length, index = _read_varlen(data, index)
            index += length
            continue

        kind = status & 0xF0
        event_channel = status & 0x0F
        data_length = 1 if kind in (0xC0, 0xD0) else 2
        values = data[index : index + data_length]
        index += data_length
        if len(values) < data_length:
            break
        first = values[0]
        second = values[1] if data_length > 1 else 0

        if kind == 0x90 and second > 0:
            channel = event_channel
            open_notes.setdefault((event_channel, first), []).append((tick, int(second)))
        elif kind in (0x80,) or (kind == 0x90 and second == 0):
            channel = event_channel
            stack = open_notes.get((event_channel, first))
            if stack:
                start_tick, velocity = stack.pop(0)
                notes.append(
                    {
                        "start_tick": start_tick,
                        "end_tick": tick,
                        "pitch": int(first),
                        "velocity": velocity,
                    }
                )
        elif kind == 0xC0:
            program = int(first)
            if not notes:
                channel = event_channel
    # 没有配对 note-off 的音符按最后一个 tick 收尾，避免整轨丢失。
    for (event_channel, pitch), stack in open_notes.items():
        for start_tick, velocity in stack:
            notes.append(
                {
                    "start_tick": start_tick,
                    "end_tick": max(start_tick + 1, tick),
                    "pitch": int(pitch),
                    "velocity": velocity,
                }
            )
        if stack:
            channel = event_channel
    return (
        {
            "name": name,
            "program": program,
            "channel": channel,
            "notes": notes,
        },
        tempos,
        signature,
    )


def session_payload(parsed: dict[str, Any], *, duration: float | None = None) -> dict[str, Any]:
    """解析结果 → 会话原始结构（交给 ``midi_session.clean_session`` 归一化）。"""
    limit = midi_session.MAX_SESSION_SECONDS
    tracks = list(parsed.get("tracks") or [])
    if duration is not None:
        limit = min(limit, max(midi_session.MIN_SESSION_SECONDS, float(duration)))
    else:
        end = 0.0
        for track in tracks:
            for note in track.get("notes") or []:
                end = max(end, float(note.get("end") or 0.0))
        limit = min(limit, max(midi_session.MIN_SESSION_SECONDS, end))
    parts = []
    for index, track in enumerate(tracks[: midi_session.MAX_PARTS]):
        notes = [
            {
                "start": min(limit, float(note.get("start") or 0.0)),
                "end": min(limit, float(note.get("end") or 0.0)),
                "pitch": note.get("pitch"),
                "velocity": note.get("velocity", midi_session.DEFAULT_VELOCITY),
            }
            for note in track.get("notes") or []
        ]
        parts.append(
            {
                "name": str(track.get("name") or "").strip()
                or midi_instruments.name_of(track.get("program", 0)),
                "instrument": track.get("program", 0),
                "channel": track.get("channel", index),
                "drum": bool(track.get("drum")),
                "notes": notes,
            }
        )
    return {
        "tempo": parsed.get("tempo", midi_session.DEFAULT_TEMPO),
        "time_signature": parsed.get("time_signature", [4, 4]),
        "parts": parts,
    }
