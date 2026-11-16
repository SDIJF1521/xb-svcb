"""从 Windows 自带 GM 波表（``gm.dls``）里提取标准鼓组采样。

MIDI 第 10 通道的鼓组在「打开文件时」用的是操作系统 GM 音源（Windows 上就是
``%SystemRoot%\\System32\\drivers\\gm.dls``）。内置合成器（``midi_synth``）只能做加法
近似，音色对不上。这里解析 gm.dls 的 DLS（Downloadable Sounds）格式，把标准鼓组
（GM note 27~87）的真实采样读出来，渲染鼓组时优先用采样、失败再退回合成器。

只依赖标准库 + numpy，找不到 gm.dls（非 Windows）时返回 ``None``。
"""

from __future__ import annotations

import os
import struct
from typing import Any

_GM_DLS_CANDIDATES = (
    r"C:\Windows\System32\drivers\gm.dls",
    os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "drivers", "gm.dls"),
)

# 标准鼓组（GM 打击乐）在 gm.dls 里的标识：bank 高位是「这是鼓组」标志，program 0。
_DRUM_BANK = 0x80000000
_DRUM_PROGRAM = 0

# 只导出编曲编辑器会用的鼓件音高范围（GM 35~81），避免拖入无关采样。
_PITCH_MIN = 35
_PITCH_MAX = 81

_cache: dict[int, tuple[int, Any, float, int, int]] | None = None


def _chunks(data: bytes, start: int, end: int):
    """遍历 RIFF 子块，产出 (chunk_id, size, data_start, data_end)。"""
    offset = start
    while offset + 8 <= end:
        chunk_id = data[offset : offset + 4]
        size = struct.unpack("<I", data[offset + 4 : offset + 8])[0]
        data_start = offset + 8
        data_end = data_start + size
        yield chunk_id, size, data_start, data_end
        offset = data_end + (size & 1)


def _find_chunk(data: bytes, start: int, end: int, wanted: bytes):
    for chunk_id, _size, data_start, data_end in _chunks(data, start, end):
        if chunk_id == wanted:
            return data_start, data_end
    return None, None


def _find_list(data: bytes, start: int, end: int, form: bytes):
    for chunk_id, _size, data_start, data_end in _chunks(data, start, end):
        if chunk_id == b"LIST" and data_start + 4 <= data_end and data[data_start : data_start + 4] == form:
            return data_start + 4, data_end
    return None, None


def _decode_wave(fmt: tuple[int, ...], pcm: bytes) -> Any:
    """把 DLS wave 的 PCM 解码成 float32 单声道（[-1, 1]）。"""
    import numpy as np

    w_format_tag, channels, sample_rate, _avg, _block, bits = fmt
    if w_format_tag != 1:  # 只处理 PCM；gm.dls 都是 PCM
        return None
    if bits == 16:
        raw = np.frombuffer(pcm, dtype="<i2")
        samples = raw.astype(np.float32) / 32768.0
    elif bits == 8:
        raw = np.frombuffer(pcm, dtype="<u1")
        samples = (raw.astype(np.float32) - 128.0) / 128.0
    else:
        return None
    if channels == 2 and samples.size:
        samples = samples.reshape(-1, 2).mean(axis=1).astype(np.float32)
    elif channels != 1:
        return None
    return samples


def _parse_gm_dls(data: bytes) -> dict[int, tuple[int, Any]] | None:
    """解析 gm.dls，返回 {pitch: (sample_rate, float32_samples)}。"""
    import numpy as np

    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"DLS ":
        return None
    riff_end = len(data)

    # 1) 池表 ptbl：头部 (cbSize, cCues) + 每个 wave 一个 poolcue.ulOffset。
    ptbl_start, ptbl_end = _find_chunk(data, 12, riff_end, b"ptbl")
    if ptbl_start is None:
        return None
    cb_size, cue_count = struct.unpack("<II", data[ptbl_start : ptbl_start + 8])
    if cb_size != 8 or cue_count <= 0:
        return None
    cues = [
        struct.unpack("<I", data[ptbl_start + 8 + i * 4 : ptbl_start + 8 + i * 4 + 4])[0]
        for i in range(cue_count)
    ]

    # 2) 波表 wvpl：直接是一串 LIST wave。
    wvpl_start, wvpl_end = _find_list(data, 12, riff_end, b"wvpl")
    if wvpl_start is None:
        return None
    wave_base = wvpl_start
    waves: list[tuple[int, tuple[int, ...], bytes, int, int]] = []
    offset = wvpl_start
    while offset + 8 <= wvpl_end:
        chunk_id = data[offset : offset + 4]
        size = struct.unpack("<I", data[offset + 4 : offset + 8])[0]
        if chunk_id == b"LIST" and data[offset + 8 : offset + 12] == b"wave":
            rel = offset - wave_base
            fmt = None
            pcm = b""
            loop_start = 0
            loop_end = 0
            for c2, s2, d2, e2 in _chunks(data, offset + 12, offset + 8 + size):
                if c2 == b"fmt " and s2 >= 16:
                    fmt = struct.unpack("<HHIIHH", data[d2 : d2 + 16])
                elif c2 == b"data":
                    pcm = data[d2:e2]
                elif c2 == b"wsmp" and d2 + 20 <= e2:
                    c_sample_loops = struct.unpack("<I", data[d2 + 16 : d2 + 20])[0]
                    for loop_index in range(min(c_sample_loops, 1)):
                        loop_pos = d2 + 20 + loop_index * 16
                        if loop_pos + 16 <= e2:
                            _size, _kind, loop_start, loop_length = struct.unpack(
                                "<IIII", data[loop_pos : loop_pos + 16]
                            )
                            loop_end = loop_start + loop_length
            if fmt is not None and pcm:
                waves.append((rel, fmt, pcm, loop_start, loop_end))
        offset += 8 + size + (size & 1)

    rel_to_index = {rel: index for index, (rel, *_rest) in enumerate(waves)}

    # 3) 找到标准鼓组（bank=0x80000000, program=0）。
    lins_start, lins_end = _find_list(data, 12, riff_end, b"lins")
    if lins_start is None:
        return None
    drum_instrument = None
    offset = lins_start
    while offset + 8 <= lins_end:
        chunk_id = data[offset : offset + 4]
        size = struct.unpack("<I", data[offset + 4 : offset + 8])[0]
        if chunk_id == b"LIST" and data[offset + 8 : offset + 12] == b"ins ":
            insh_start, _ = _find_chunk(data, offset + 12, offset + 8 + size, b"insh")
            if insh_start is not None:
                _regions, bank, program = struct.unpack("<III", data[insh_start : insh_start + 12])
                if bank == _DRUM_BANK and program == _DRUM_PROGRAM:
                    drum_instrument = (offset + 12, offset + 8 + size)
                    break
        offset += 8 + size + (size & 1)

    if drum_instrument is None:
        return None
    lrgn_start, lrgn_end = _find_list(data, drum_instrument[0], drum_instrument[1], b"lrgn")
    if lrgn_start is None:
        return None

    # 4) 每个 region 记录 (key_low, key_high, table_index, unity_note, fine_tune)。
    #    通鼓/邦戈鼓等有音高的鼓件共用同一个采样，靠 unity note 做移调。
    regions: list[tuple[int, int, int, int, int]] = []
    offset = lrgn_start
    while offset + 8 <= lrgn_end:
        chunk_id = data[offset : offset + 4]
        size = struct.unpack("<I", data[offset + 4 : offset + 8])[0]
        if chunk_id == b"LIST" and data[offset + 8 : offset + 12] in (b"rgn ", b"rgn2"):
            key_low = key_high = table_index = -1
            unity_note = 60
            fine_tune = 0
            for c2, _s2, d2, _e2 in _chunks(data, offset + 12, offset + 8 + size):
                if c2 == b"rgnh":
                    key_low, key_high = struct.unpack("<HH", data[d2 : d2 + 4])
                elif c2 == b"wsmp" and d2 + 8 <= offset + 8 + size:
                    unity_note = struct.unpack("<H", data[d2 + 4 : d2 + 6])[0]
                    fine_tune = struct.unpack("<h", data[d2 + 6 : d2 + 8])[0]
                elif c2 == b"wlnk" and d2 + 12 <= offset + 8 + size:
                    table_index = struct.unpack("<I", data[d2 + 8 : d2 + 12])[0]
            if key_low >= 0 and table_index >= 0:
                regions.append((key_low, key_high, table_index, unity_note, fine_tune))
        offset += 8 + size + (size & 1)

    # 5) 解析出需要的音高，并按 unity note / 微调算出移调比例。
    result: dict[int, tuple[int, Any, float]] = {}
    for key_low, key_high, table_index, unity_note, fine_tune in regions:
        for pitch in range(max(_PITCH_MIN, key_low), min(_PITCH_MAX, key_high) + 1):
            if pitch in result:
                continue
            if table_index >= len(cues):
                continue
            rel = cues[table_index]
            wave_index = rel_to_index.get(rel)
            if wave_index is None:
                continue
            _rel, fmt, pcm, loop_start, loop_end = waves[wave_index]
            samples = _decode_wave(fmt, pcm)
            if samples is None or samples.size == 0:
                continue
            pitch_factor = 2.0 ** ((pitch - unity_note) / 12.0 + fine_tune / 1200.0)
            if loop_end <= loop_start or loop_end > len(samples):
                loop_start = loop_end = 0
            result[pitch] = (
                int(fmt[2]),
                np.asarray(samples, dtype=np.float32),
                float(pitch_factor),
                int(loop_start),
                int(loop_end),
            )
    return result or None


def load_gm_drums() -> dict[int, tuple[int, Any, float, int, int]] | None:
    """读取并缓存标准鼓组采样；失败返回 ``None``（调用方退回合成器）。"""
    global _cache
    if _cache is not None:
        return _cache or None
    _cache = None
    for candidate in _GM_DLS_CANDIDATES:
        try:
            if not os.path.isfile(candidate):
                continue
            with open(candidate, "rb") as handle:
                data = handle.read()
            parsed = _parse_gm_dls(data)
            if parsed:
                _cache = parsed
                break
        except (OSError, ValueError, struct.error):
            continue
    return _cache or None
