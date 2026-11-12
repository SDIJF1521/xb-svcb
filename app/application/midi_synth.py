"""把 MIDI 编曲会话离线渲染成音频。

编辑器里的 MIDI 编曲是「用乐器写歌」，所以必须能出声、能导出：这里实现一个
零第三方依赖（只用 numpy）的多乐器合成器，按 GM 音色族切换音色，支持力度、
声像、独奏/静音、鼓组，以及一点混响让试听不至于干瘪。

设计取舍：

* 只用加法合成 + 噪声 + 简单包络，够用且完全可复现（同一份音符渲染结果一致）；
* 每个音符独立生成再叠加，工程量小、易测试；
* 结尾固定留一点尾巴（release + 混响），避免尾音被硬切。
"""

from __future__ import annotations

import math
import threading
from pathlib import Path
from typing import Any, Callable, Iterable

from domain import midi_drums, midi_instruments, midi_session

# 每个音色族的合成参数。
# harmonics: (谐波编号, 相对振幅)；hdecay: 高次谐波衰减速度（越大越闷）
# attack/decay/release: 秒；sustain: 持续电平；vibrato: (速率Hz, 深度比例)
# detune: 双振荡器失谐（音分，做合唱）；noise: 气声/噪声比例
_VOICE_PARAMS: dict[str, dict[str, Any]] = {
    "piano": {
        "harmonics": ((1, 1.0), (2, 0.46), (3, 0.24), (4, 0.12), (5, 0.06), (6, 0.03)),
        "hdecay": 2.4,
        "attack": 0.004,
        "decay": 1.1,
        "sustain": 0.22,
        "release": 0.28,
        "vibrato": None,
        "detune": 2.0,
        "noise": 0.0,
    },
    "chromatic": {
        "harmonics": ((1, 1.0), (2, 0.28), (3, 0.1), (4.02, 0.05)),
        "hdecay": 1.4,
        "attack": 0.002,
        "decay": 1.6,
        "sustain": 0.12,
        "release": 0.5,
        "vibrato": None,
        "detune": 0.0,
        "noise": 0.0,
    },
    "organ": {
        "harmonics": ((1, 1.0), (2, 0.62), (3, 0.34), (4, 0.22), (5, 0.12), (6, 0.08)),
        "hdecay": 0.25,
        "attack": 0.012,
        "decay": 0.3,
        "sustain": 0.82,
        "release": 0.12,
        "vibrato": (5.6, 0.004),
        "detune": 0.0,
        "noise": 0.0,
    },
    "guitar": {
        "harmonics": ((1, 1.0), (2, 0.5), (3, 0.26), (4, 0.14), (5, 0.07)),
        "hdecay": 3.0,
        "attack": 0.003,
        "decay": 0.75,
        "sustain": 0.18,
        "release": 0.22,
        "vibrato": None,
        "detune": 3.0,
        "noise": 0.02,
    },
    "bass": {
        "harmonics": ((1, 1.0), (2, 0.42), (3, 0.18), (4, 0.08)),
        "hdecay": 2.2,
        "attack": 0.006,
        "decay": 0.5,
        "sustain": 0.42,
        "release": 0.16,
        "vibrato": None,
        "detune": 1.0,
        "noise": 0.0,
    },
    "strings": {
        "harmonics": ((1, 1.0), (2, 0.52), (3, 0.32), (4, 0.2), (5, 0.12), (6, 0.07)),
        "hdecay": 1.2,
        "attack": 0.11,
        "decay": 0.4,
        "sustain": 0.72,
        "release": 0.32,
        "vibrato": (5.2, 0.009),
        "detune": 6.0,
        "noise": 0.006,
    },
    "ensemble": {
        "harmonics": ((1, 1.0), (2, 0.45), (3, 0.24), (4, 0.14), (5, 0.08)),
        "hdecay": 1.0,
        "attack": 0.16,
        "decay": 0.5,
        "sustain": 0.76,
        "release": 0.4,
        "vibrato": (4.6, 0.006),
        "detune": 8.0,
        "noise": 0.008,
    },
    "brass": {
        "harmonics": ((1, 1.0), (2, 0.66), (3, 0.44), (4, 0.3), (5, 0.2), (6, 0.12)),
        "hdecay": 0.9,
        "attack": 0.045,
        "decay": 0.28,
        "sustain": 0.74,
        "release": 0.16,
        "vibrato": (5.0, 0.005),
        "detune": 3.0,
        "noise": 0.01,
    },
    "reed": {
        "harmonics": ((1, 1.0), (2, 0.34), (3, 0.36), (4, 0.14), (5, 0.18)),
        "hdecay": 1.1,
        "attack": 0.03,
        "decay": 0.24,
        "sustain": 0.7,
        "release": 0.14,
        "vibrato": (5.4, 0.007),
        "detune": 1.5,
        "noise": 0.02,
    },
    "pipe": {
        "harmonics": ((1, 1.0), (2, 0.2), (3, 0.08), (4, 0.04)),
        "hdecay": 1.6,
        "attack": 0.055,
        "decay": 0.22,
        "sustain": 0.66,
        "release": 0.18,
        "vibrato": (5.8, 0.008),
        "detune": 0.8,
        "noise": 0.05,
    },
    "lead": {
        "harmonics": ((1, 1.0), (2, 0.5), (3, 0.34), (4, 0.26), (5, 0.18), (6, 0.12), (7, 0.08)),
        "hdecay": 0.7,
        "attack": 0.012,
        "decay": 0.3,
        "sustain": 0.66,
        "release": 0.14,
        "vibrato": (5.6, 0.006),
        "detune": 4.0,
        "noise": 0.0,
    },
    "pad": {
        "harmonics": ((1, 1.0), (2, 0.56), (3, 0.38), (4, 0.28), (5, 0.2), (6, 0.14), (7, 0.1)),
        "hdecay": 0.5,
        "attack": 0.34,
        "decay": 0.6,
        "sustain": 0.8,
        "release": 0.7,
        "vibrato": (4.2, 0.005),
        "detune": 10.0,
        "noise": 0.01,
    },
    "fx": {
        "harmonics": ((1, 1.0), (2.4, 0.4), (3.7, 0.24), (5.1, 0.14)),
        "hdecay": 0.4,
        "attack": 0.22,
        "decay": 1.4,
        "sustain": 0.5,
        "release": 0.9,
        "vibrato": (3.4, 0.02),
        "detune": 14.0,
        "noise": 0.06,
    },
    "ethnic": {
        "harmonics": ((1, 1.0), (2, 0.44), (3, 0.3), (4, 0.16), (5, 0.1)),
        "hdecay": 2.2,
        "attack": 0.006,
        "decay": 0.7,
        "sustain": 0.25,
        "release": 0.26,
        "vibrato": None,
        "detune": 3.5,
        "noise": 0.02,
    },
    "percussive": {
        "harmonics": ((1, 1.0), (2, 0.3), (3, 0.14), (4.3, 0.08)),
        "hdecay": 4.0,
        "attack": 0.002,
        "decay": 0.4,
        "sustain": 0.05,
        "release": 0.3,
        "vibrato": None,
        "detune": 1.0,
        "noise": 0.03,
    },
    "sfx": {
        "harmonics": ((1, 1.0), (1.5, 0.5), (2.3, 0.3)),
        "hdecay": 0.5,
        "attack": 0.05,
        "decay": 0.9,
        "sustain": 0.3,
        "release": 0.6,
        "vibrato": (2.0, 0.03),
        "detune": 18.0,
        "noise": 0.3,
    },
}

# 鼓组映射统一由 ``domain.midi_drums`` 提供（合成 / 导出 / UI 共用一张表）。

_MASTER_GAIN = 0.85
_PEAK_TARGET = 0.94

# gm.dls 采样是 16bit 全幅度，但经过力度缩放 + 主增益 + 声像后整体偏小，
# 这里补一点增益让鼓组和「直接打开 .mid」的响度接近（保持各鼓件之间比例不变）。
_DRUM_SAMPLE_GAIN = 1.4

# 只有镲片类鼓件需要「循环余音」：gm.dls 给吊镲/叮叮镲/开镲的采样带了循环点，
# 直接播放会只剩很短的一下。通鼓等本身是自然衰减的，不要循环（否则会变成嗡鸣）。
# 余音时长跟「单个音符的长短」挂钩：音符持续多久就多响多久，上面这个只是上限。
_CYMBAL_RING_MAX: dict[str, float] = {
    "crash": 4.0,
    "ride": 3.0,
    "hat_open": 1.0,
}

# 鼓组优先用 Windows 自带的 GM 波表（gm.dls）真实采样，和「直接打开 .mid」听到的一致。
_cached_gm_drums: Any = None

# 同一鼓件在整首曲子会重复触发成百上千次；gm.dls 采样是固定的，
# 重采样结果按 (pitch, 源采样率, 目标采样率, 音高系数) 缓存，避免每次重算。
_gm_resample_cache: dict[tuple[int, int, int, int], Any] = {}


def _gm_drum_samples() -> dict[int, tuple[int, Any, float, int, int]] | None:
    """惰性加载 gm.dls 鼓组采样；不可用时返回 None（退回加法合成）。"""
    global _cached_gm_drums
    if _cached_gm_drums is None:
        try:
            from .adapters import gm_drum_samples

            loaded = gm_drum_samples()
            _cached_gm_drums = loaded if loaded else {}
        except Exception:
            _cached_gm_drums = {}
    return _cached_gm_drums if _cached_gm_drums else None


def _resample_mono(data: Any, src_rate: int, dst_rate: int, pitch: float = 1.0) -> Any:
    """把单声道采样从 src_rate 线性插值到 dst_rate，并按 pitch 比例移调（>1 升调变短）。"""
    import numpy as np
    if data is None or len(data) == 0:
        return data
    n = len(data)
    factor = max(0.05, min(20.0, float(pitch or 1.0)))
    target = max(1, int(round(n * dst_rate / src_rate / factor)))
    if target == n:
        return data
    src_x = np.arange(n, dtype=np.float64)
    dst_x = np.linspace(0.0, float(n - 1), target, dtype=np.float64)
    return np.interp(dst_x, src_x, np.asarray(data, dtype=np.float64)).astype(np.float32)


def _hz(pitch: float) -> float:
    return 440.0 * (2.0 ** ((float(pitch) - 69.0) / 12.0))


def voice_params(program: Any, *, drum: bool = False) -> dict[str, Any]:
    """音色 → 合成参数；鼓组用打击乐参数。"""
    if drum:
        return _VOICE_PARAMS["percussive"]
    return _VOICE_PARAMS[midi_instruments.family_of(program)]


def _envelope(n: int, sr: int, params: dict[str, Any], gate_samples: int) -> Any:
    import numpy as np

    index = np.arange(n, dtype=np.float32)
    attack = max(1.0, float(params["attack"]) * sr)
    decay = max(1.0, float(params["decay"]) * sr)
    sustain = float(params["sustain"])
    release = max(1.0, float(params["release"]) * sr)

    # np.minimum/np.maximum are markedly faster than np.clip on float32
    # arrays; every note builds this envelope, so it dominates render time.
    rising = np.minimum(index / attack, np.float32(1.0))
    falling = np.float32(1.0) - np.float32(1.0 - sustain) * np.minimum(
        np.maximum((index - attack) / decay, np.float32(0.0)), np.float32(1.0)
    )
    body = np.minimum(rising, falling)
    tail_index = index - float(max(0, gate_samples))
    tail = np.minimum(
        np.maximum(np.float32(1.0) - tail_index / release, np.float32(0.0)),
        np.float32(1.0),
    )
    envelope = body * np.where(tail_index >= 0.0, tail, np.float32(1.0))
    return envelope.astype(np.float32)


_NOISE_TABLE: Any = None
_NOISE_HIGHPASS: Any = None

# 同一首歌里相同音高/时值/力度的音符会反复出现（和弦、循环、鼓点），
# 合成结果只依赖这些参数，缓存后重复音符只需一次数组加法。
_NOTE_CACHE: dict[tuple[int, int, int, int, int, int], Any] = {}
_NOTE_CACHE_BYTES = 0
_NOTE_CACHE_LIMIT = 96 * 1024 * 1024
_NOTE_CACHE_LOCK = threading.Lock()


def _noise_highpass(n: int, seed: int) -> Any:
    """Slice a cached high-passed noise table instead of generating noise per note."""
    import numpy as np

    global _NOISE_TABLE, _NOISE_HIGHPASS
    size = max(n, 48000 * 8)
    if _NOISE_HIGHPASS is None or _NOISE_TABLE is None or _NOISE_TABLE.size < size:
        rng = np.random.default_rng(20240501)
        table = rng.standard_normal(max(size, 48000 * 16), dtype=np.float32)
        _NOISE_TABLE = table
        _NOISE_HIGHPASS = np.diff(table, prepend=np.float32(0.0))
    span = int(_NOISE_HIGHPASS.size) - int(n)
    offset = int(seed) % max(1, span) if span > 0 else 0
    return _NOISE_HIGHPASS[offset : offset + n]


def _oscillators(
    freq: float,
    n: int,
    sr: int,
    params: dict[str, Any],
    *,
    velocity: float,
) -> Any:
    import numpy as np

    time = np.arange(n, dtype=np.float32) / float(sr)
    vibrato = params.get("vibrato")
    mod = None
    if vibrato:
        rate, depth = vibrato
        ramp = np.minimum(time / np.float32(0.18), np.float32(1.0))
        mod = 1.0 + float(depth) * ramp * np.sin(
            np.float32(2.0 * math.pi * float(rate)) * time
        )

    detune = float(params.get("detune") or 0.0)
    ratios = (1.0,) if detune <= 0.0 else (1.0, 2.0 ** (detune / 1200.0))
    signal = np.zeros(n, dtype=np.float32)
    weight = float(sum(abs(amp) for _index, amp in params["harmonics"])) or 1.0
    brightness = float(params.get("hdecay") or 0.0)
    for ratio in ratios:
        base = float(freq) * ratio
        for harmonic, amp in params["harmonics"]:
            partial = base * float(harmonic)
            if partial >= sr * 0.47:
                continue
            phase = np.float32(2.0 * math.pi * partial) * time
            if mod is not None:
                phase = phase * mod
            tone = np.sin(phase, dtype=np.float32)
            if brightness > 0.0:
                tone *= np.exp(
                    np.float32(-brightness * (float(harmonic) - 1.0)) * time,
                    dtype=np.float32,
                )
            signal += np.float32(float(amp) / weight / len(ratios)) * tone

    noise_amount = float(params.get("noise") or 0.0)
    if noise_amount > 0.0:
        # 一阶差分做高通，让气声落在高频，避免糊住低音。
        noise = _noise_highpass(n, int(abs(freq) * 31) + n)
        signal += noise_amount * noise * np.float32(0.5)
    return signal * (0.28 + 0.72 * velocity)


def _note_signal(
    pitch: int,
    gate: int,
    tail: int,
    sample_rate: int,
    params: dict[str, Any],
    velocity: int,
) -> Any:
    """合成一个旋律音符（含包络），结果按参数缓存给重复音符复用。"""
    import numpy as np

    key = (int(pitch), int(gate), int(tail), int(sample_rate), int(velocity), id(params))
    with _NOTE_CACHE_LOCK:
        cached = _NOTE_CACHE.get(key)
    if cached is not None:
        return cached
    n = gate + tail
    signal = _oscillators(
        _hz(pitch), n, sample_rate, params, velocity=velocity / 127.0
    )
    signal *= _envelope(n, sample_rate, params, gate)
    signal = signal.astype(np.float32, copy=False)

    global _NOTE_CACHE_BYTES
    size = int(getattr(signal, "nbytes", 0))
    if size and size <= _NOTE_CACHE_LIMIT:
        with _NOTE_CACHE_LOCK:
            if key not in _NOTE_CACHE:
                while _NOTE_CACHE and _NOTE_CACHE_BYTES + size > _NOTE_CACHE_LIMIT:
                    oldest_key, oldest = next(iter(_NOTE_CACHE.items()))
                    del _NOTE_CACHE[oldest_key]
                    _NOTE_CACHE_BYTES -= int(getattr(oldest, "nbytes", 0))
                _NOTE_CACHE[key] = signal
                _NOTE_CACHE_BYTES += size
    return signal


def _drum_voice(
    pitch: int,
    n: int,
    sr: int,
    velocity: float,
) -> Any:
    """架子鼓单件发声：按 GM 鼓件表（``domain.midi_drums``）合成。

    每件鼓的差别集中在三件事：基频（是否有音高感）、衰减速度、噪声/金属比例。
    底鼓有音高下扫、军鼓是噪声 + 鼓腔基音、踩镲/吊镲是高频金属噪声、
    通鼓靠音高区分、小打（铃鼓/木鱼/牛铃）用短促的基音 + 噪声。
    """
    import numpy as np

    info = midi_drums.piece(pitch)
    group = str(info["group"])
    tone_hz = float(info["tone"] or 0.0)
    decay = max(0.6, float(info["decay"] or 12.0))
    noise_mix = max(0.0, float(info["noise"] or 0.0))
    metallic = max(0.0, float(info["metallic"] or 0.0))
    time = np.arange(n, dtype=np.float32) / float(sr)
    rng = np.random.default_rng(int(pitch) * 977 + n)
    signal = np.zeros(n, dtype=np.float32)

    # 1) 有音高感的鼓件（底鼓/通鼓/小打）：指数衰减的正弦，底鼓加音高下扫。
    if tone_hz > 0.0:
        if group == "kick":
            freq = tone_hz * (0.55 + 1.15 * np.exp(-time * 26.0))
        elif group == "tom":
            freq = tone_hz * (0.82 + 0.42 * np.exp(-time * 16.0))
        elif group == "snare":
            freq = tone_hz * (0.95 + 0.1 * np.exp(-time * 30.0))
        else:
            freq = tone_hz * (0.98 + 0.06 * np.exp(-time * 22.0))
        phase = 2.0 * math.pi * np.cumsum(freq) / float(sr)
        body = np.sin(phase, dtype=np.float32) * np.exp(-time * decay, dtype=np.float32)
        signal += body * (0.9 if group != "snare" else 0.45)

    # 2) 噪声成分：底鼓只留一点击槌声，军鼓满噪声，镲片走高频。
    if noise_mix > 0.0:
        noise = rng.standard_normal(n, dtype=np.float32)
        if group in ("kick",):
            noise *= np.exp(-time * 90.0, dtype=np.float32)
        elif group in ("snare", "rim", "clap"):
            noise = np.diff(noise, prepend=np.float32(0.0))
        elif group in ("hat", "hat_open", "crash", "ride"):
            # 二阶差分 → 只剩高频，镲片才不会糊成一片「沙沙」低频。
            noise = np.diff(
                np.diff(noise, prepend=np.float32(0.0)),
                prepend=np.float32(0.0),
            )
        noise_decay = decay if group not in ("crash", "ride") else decay
        signal += noise_mix * noise * np.exp(-time * noise_decay, dtype=np.float32)

    # 3) 金属泛音：镲片用一组不成谐波比例的正弦叠出「叮」的金属感。
    if metallic > 0.0:
        ratios = (1.0, 1.4471, 1.8312, 2.2761, 2.7183, 3.3177) if group in (
            "hat",
            "hat_open",
            "crash",
            "ride",
        ) else (1.0, 2.41, 3.77)
        base = 410.0 if group in ("hat", "hat_open", "crash", "ride") else max(180.0, tone_hz)
        shimmer = np.zeros(n, dtype=np.float32)
        for ratio in ratios:
            partial = base * ratio
            if partial >= sr * 0.45:
                continue
            shimmer += np.sin(2.0 * math.pi * partial * time, dtype=np.float32)
        signal += metallic * 0.22 * shimmer / len(ratios) * np.exp(
            -time * (decay * 0.7 + 1.0), dtype=np.float32
        )

    # 4) 拍手：几个极短的噪声群叠在一起，模拟多只手同时拍。
    if group == "clap":
        gate = np.ones(n, dtype=np.float32)
        for offset in (0.0, 0.011, 0.023, 0.036):
            gate *= np.where(time < offset, 0.22, 1.0)
        signal *= gate

    signal *= 0.55
    return signal * (0.22 + 0.78 * float(velocity))


def _drum_event_gates(
    notes: list[dict[str, Any]],
) -> list[tuple[float, float, int, int]]:
    """整理鼓组事件：按时间排序，并按「互斥组」截断开镲等长尾音。"""
    events: list[list[Any]] = []
    for note in notes:
        try:
            begin = max(0.0, float(note.get("start") or 0.0))
            finish = max(begin, float(note.get("end") or 0.0))
            pitch = int(note.get("pitch") or 38)
            velocity = max(1, min(127, int(note.get("velocity") or 100)))
        except (TypeError, ValueError):
            continue
        info = midi_drums.piece(pitch)
        events.append([begin, finish, int(info["pitch"]), velocity, int(info["choke"] or 0)])
    events.sort(key=lambda item: (item[0], item[2]))

    # 同一互斥组里，后一件鼓件开始时前一件就被掐断（踩镲闭/开互斥）。
    for index, event in enumerate(events):
        choke = event[4]
        if not choke:
            continue
        for other in events[index + 1 :]:
            if other[0] >= event[1]:
                break
            if other[4] == choke:
                event[1] = other[0]
                break
    return [
        (float(item[0]), max(float(item[0]) + 0.01, float(item[1])), int(item[2]), int(item[3]))
        for item in events
    ]


def _loop_ring(
    signal: Any,
    loop_start: int,
    loop_end: int,
    ring_seconds: float,
    sample_rate: int,
) -> Any:
    """把带循环点的镲片采样循环延展到 ring_seconds，并加指数衰减。"""
    import numpy as np

    n = len(signal)
    if loop_end <= loop_start or loop_end > n:
        return signal
    want = max(n, int(round(ring_seconds * sample_rate)))
    if want <= n:
        return signal
    body = np.array(signal[loop_start:loop_end], dtype=np.float32)
    body_len = len(body)
    if body_len <= 0:
        return signal
    # 循环点两端幅度略有差异，交叉淡化抹平，避免每次循环边界「突突」跳变。
    xfade = min(body_len // 3, max(1, int(round(0.01 * sample_rate))))
    if xfade > 0:
        ramp = np.linspace(0.0, 1.0, xfade, dtype=np.float32)
        body[:xfade] = body[:xfade] * ramp + body[-xfade:] * (1.0 - ramp)
    tail_len = want - loop_end
    reps = int(np.ceil(tail_len / body_len))
    tail = np.tile(body, reps)[:tail_len].astype(np.float32)
    time = np.arange(tail_len, dtype=np.float32) / float(sample_rate)
    decay_rate = 4.5 / max(0.3, float(ring_seconds))
    tail = tail * np.exp(-time * decay_rate, dtype=np.float32)
    return np.concatenate([signal[:loop_end], tail]).astype(np.float32)


def _drum_signal(pitch: int, velocity: int, sample_rate: int, note_duration: float = 0.0) -> Any:
    """鼓件出声：优先用 gm.dls 真实采样，失败再退回加法合成。

    镲片类鼓件按音符持续时间循环余音：长音多响、短音少响（至少采样自身长度）。
    """
    import numpy as np

    gm = _gm_drum_samples()
    if gm:
        entry = gm.get(pitch)
        if entry is not None:
            src_rate, samples, pitch_factor, loop_start, loop_end = entry
            cache_key = (
                int(pitch),
                int(src_rate),
                int(sample_rate),
                int(round(float(pitch_factor) * 1_000_000)),
            )
            signal = _gm_resample_cache.get(cache_key)
            if signal is None:
                signal = _resample_mono(
                    samples, int(src_rate), int(sample_rate), pitch=float(pitch_factor)
                )
                _gm_resample_cache[cache_key] = signal
            if signal is not None and signal.size:
                info = midi_drums.piece(pitch)
                ring_max = _CYMBAL_RING_MAX.get(str(info["group"]))
                if ring_max is not None and loop_end > loop_start:
                    scale = signal.size / max(1, len(samples))
                    loop_s = int(round(loop_start * scale))
                    loop_e = int(round(loop_end * scale))
                    ring_seconds = min(float(ring_max), max(0.0, float(note_duration)))
                    signal = _loop_ring(signal, loop_s, loop_e, ring_seconds, sample_rate)
                return signal * (_DRUM_SAMPLE_GAIN * velocity / 127.0)
    info = midi_drums.piece(pitch)
    ring_seconds = max(0.08, min(2.0, 3.2 / max(0.6, float(info["decay"] or 12.0))))
    n = max(1, int(round(ring_seconds * sample_rate)))
    return _drum_voice(pitch, n, sample_rate, velocity / 127.0)


def _render_part_events(
    part: dict[str, Any],
    *,
    sample_rate: int,
    start_offset: float,
    length: int,
    gain: float,
    pan: float,
    out: Any,
    progress: Callable[[float], None] | None = None,
) -> None:
    """把一个声部的音符累加进立体声缓冲（鼓组走专用的鼓件渲染）。"""
    import numpy as np

    drum = bool(part.get("drum"))
    program = part.get("instrument", 0)
    params = voice_params(program, drum=drum)
    # 鼓件的衰减完全由鼓本身决定，尾部不需要长 release。
    release = 0.06 if drum else float(params.get("release") or 0.2)
    if drum:
        raw = _drum_event_gates(list(part.get("notes") or []))
        events = [
            (max(0.0, begin - start_offset), max(0.0, finish - start_offset), pitch, velocity)
            for begin, finish, pitch, velocity in raw
        ]
    else:
        events = []
        for note in part.get("notes") or []:
            try:
                begin = max(0.0, float(note.get("start") or 0.0) - start_offset)
                finish = max(begin, float(note.get("end") or 0.0) - start_offset)
                pitch = int(note.get("pitch") or 60)
                velocity = max(
                    1, min(127, int(note.get("velocity") or midi_session.DEFAULT_VELOCITY))
                )
            except (TypeError, ValueError):
                continue
            events.append((begin, finish, pitch, velocity))

    event_total = len(events)
    report_every = max(1, event_total // 100) if progress else 0
    stereo_left = math.cos((float(pan) + 1.0) * math.pi / 4.0)
    stereo_right = math.sin((float(pan) + 1.0) * math.pi / 4.0)
    scale = float(gain) * float(_MASTER_GAIN) * stereo_left
    scale_right = float(gain) * float(_MASTER_GAIN) * stereo_right
    for event_index, (begin, finish, pitch, velocity) in enumerate(events):
        if progress and event_total and (event_index % report_every == 0):
            progress((event_index + 1) / float(event_total))
        first = int(round(begin * sample_rate))
        if first >= length:
            continue
        if drum:
            signal = _drum_signal(pitch, velocity, sample_rate, note_duration=max(0.0, finish - begin))
        else:
            # 音符自身的长度（不是绝对结束时间）决定按住的采样数，
            # 否则越靠后的音符就会渲染出越长的缓冲（指数级变慢）。
            gate = max(1, int(round((finish - begin) * sample_rate)))
            tail = int(round(max(release, 0.05) * sample_rate))
            signal = _note_signal(pitch, gate, tail, sample_rate, params, velocity)
        total = int(len(signal))
        if total <= 0:
            continue
        count = min(total, length - first)
        if count <= 0:
            continue
        out[first : first + count, 0] += signal[:count] * scale
        out[first : first + count, 1] += signal[:count] * scale_right


def _apply_reverb(samples: Any, sample_rate: int, mix: float = 0.16) -> Any:
    import numpy as np

    if mix <= 0.0:
        return samples
    wet = np.zeros_like(samples)
    total = samples.shape[0]
    taps = ((0.031, 0.34), (0.047, 0.27), (0.073, 0.21), (0.109, 0.15))
    for delay_seconds, feedback in taps:
        delay = max(1, int(sample_rate * delay_seconds))
        buffer = np.zeros_like(samples)
        # Process both channels in one block loop: half the Python overhead of
        # the per-channel comb filter, with identical output.
        for start in range(0, total, delay):
            stop = min(total, start + delay)
            if start >= delay:
                buffer[start:stop] = (
                    samples[start:stop] + feedback * buffer[start - delay : stop - delay]
                )
            else:
                buffer[start:stop] = samples[start:stop]
        wet += buffer
    return samples * (1.0 - mix) + wet * (mix / float(len(taps)))


def _finalise(samples: Any) -> Any:
    import numpy as np

    data = np.asarray(samples, dtype=np.float32)
    if data.size == 0:
        return data.reshape(0, 2)
    # 去直流，避免低频堆积导致峰值虚高。
    data = data - data.mean(axis=0, keepdims=True)
    data = np.tanh(data * 1.05).astype(np.float32)
    peak = float(np.max(np.abs(data)) or 0.0)
    if peak > _PEAK_TARGET:
        data = (data * (_PEAK_TARGET / peak)).astype(np.float32)
    return data


def render_session(
    session: dict[str, Any],
    *,
    sample_rate: int = 44100,
    window: tuple[float, float] | None = None,
    tail: float = 0.45,
    parts: Iterable[dict[str, Any]] | None = None,
    reverb: float = 0.16,
    progress: Callable[[float], None] | None = None,
) -> Any:
    """渲染会话（或指定声部集合）为 float32 立体声（n, 2）。"""
    import numpy as np

    sample_rate = int(sample_rate) if sample_rate and sample_rate > 0 else 44100
    selected = list(parts) if parts is not None else midi_session.audible_parts(session)
    selected = [part for part in selected if part.get("notes")]
    if not selected:
        return np.zeros((0, 2), dtype=np.float32)

    if window is not None:
        start_offset = max(0.0, float(window[0]))
        end_limit = max(start_offset, float(window[1]))
    else:
        start_offset = 0.0
        end_limit = midi_session.session_duration({"parts": selected})
    if end_limit - start_offset <= 0.0:
        return np.zeros((0, 2), dtype=np.float32)

    # 鼓组的镲片/开镲尾巴比旋律长，缓冲末尾多留一点，避免最后一击被切掉。
    tail_seconds = max(0.05, float(tail))
    if any(part.get("drum") for part in selected):
        tail_seconds = max(tail_seconds, 1.2)
    length = int(round((end_limit - start_offset + tail_seconds) * sample_rate))
    length = max(1, min(length, int(sample_rate * midi_session.MAX_SESSION_SECONDS)))
    out = np.zeros((length, 2), dtype=np.float32)
    note_counts = [max(1, len(part.get("notes") or [])) for part in selected]
    total_notes = float(sum(note_counts))
    done_notes = 0.0
    for part, note_count in zip(selected, note_counts):
        if progress:
            base = done_notes

            def _part_progress(fraction: float, _base: float = base, _count: float = note_count) -> None:
                progress((_base + fraction * _count) / total_notes * 0.90)

            part_progress: Callable[[float], None] | None = _part_progress
        else:
            part_progress = None
        _render_part_events(
            part,
            sample_rate=sample_rate,
            start_offset=start_offset,
            length=length,
            gain=float(part.get("volume", 1.0) or 1.0),
            pan=float(part.get("pan", 0.0) or 0.0),
            out=out,
            progress=part_progress,
        )
        done_notes += note_count
    if progress:
        progress(0.92)
    out = _apply_reverb(out, sample_rate, mix=float(reverb))
    if progress:
        progress(0.97)
    final = _finalise(out)
    if progress:
        progress(1.0)
    return final


def render_part(
    session: dict[str, Any],
    part: dict[str, Any],
    *,
    sample_rate: int = 44100,
    window: tuple[float, float] | None = None,
    tail: float = 0.45,
    reverb: float = 0.16,
    progress: Callable[[float], None] | None = None,
) -> Any:
    """单独渲染一个声部（分乐器渲染成各自音轨时用）。"""
    return render_session(
        session,
        parts=[part],
        sample_rate=sample_rate,
        window=window,
        tail=tail,
        reverb=reverb,
        progress=progress,
    )


def samples_to_wav_bytes(samples: Any, sample_rate: int = 44100) -> bytes:
    """float32 立体声 → 16bit PCM WAV 字节。"""
    import io
    import wave

    import numpy as np

    data = np.asarray(samples, dtype=np.float32)
    if data.ndim == 1:
        data = np.column_stack([data, data])
    clipped = np.clip(data, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(int(sample_rate))
        handle.writeframes(pcm.tobytes())
    return buffer.getvalue()


def write_wav(path: Path, samples: Any, sample_rate: int = 44100) -> bool:
    """把渲染结果写成 WAV 文件；失败返回 False。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(samples_to_wav_bytes(samples, sample_rate))
    except (OSError, ValueError):
        return False
    return path.is_file() and path.stat().st_size > 44


def estimate_seconds(session: dict[str, Any]) -> float:
    return midi_session.session_duration(session)
