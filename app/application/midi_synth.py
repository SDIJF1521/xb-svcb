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
from pathlib import Path
from typing import Any, Iterable

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

    rising = np.clip(index / attack, 0.0, 1.0)
    falling = 1.0 - (1.0 - sustain) * np.clip((index - attack) / decay, 0.0, 1.0)
    body = np.minimum(rising, falling)
    tail_index = index - float(max(0, gate_samples))
    tail = np.clip(1.0 - tail_index / release, 0.0, 1.0)
    envelope = body * np.where(tail_index >= 0.0, tail, 1.0)
    return np.clip(envelope, 0.0, 1.0).astype(np.float32)


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
    if vibrato:
        rate, depth = vibrato
        ramp = np.clip(time / 0.18, 0.0, 1.0)
        mod = 1.0 + float(depth) * ramp * np.sin(2.0 * math.pi * float(rate) * time)
    else:
        mod = None

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
            phase = 2.0 * math.pi * partial * time
            if mod is not None:
                phase = phase * mod
            tone = np.sin(phase, dtype=np.float32)
            if brightness > 0.0:
                tone *= np.exp(-brightness * (float(harmonic) - 1.0) * time, dtype=np.float32)
            signal += (float(amp) / weight / len(ratios)) * tone

    noise_amount = float(params.get("noise") or 0.0)
    if noise_amount > 0.0:
        rng = np.random.default_rng(int(abs(freq) * 31) + n)
        noise = rng.standard_normal(n, dtype=np.float32)
        # 一阶差分做高通，让气声落在高频，避免糊住低音。
        noise = np.diff(noise, prepend=np.float32(0.0))
        signal += noise_amount * noise * 0.5
    return signal * (0.28 + 0.72 * velocity)


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


def _render_part_events(
    part: dict[str, Any],
    *,
    sample_rate: int,
    start_offset: float,
    length: int,
    gain: float,
    pan: float,
    out: Any,
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

    for begin, finish, pitch, velocity in events:
        # 音符自身的长度（不是绝对结束时间）决定按住的采样数，
        # 否则越靠后的音符就会渲染出越长的缓冲（指数级变慢）。
        gate = max(1, int(round((finish - begin) * sample_rate)))
        if drum:
            # 架子鼓是「一击」：音符很短，但镲片/开镲要能自然响完，
            # 所以尾巴按鼓件衰减速度给，而不是按音符长度。
            info = midi_drums.piece(pitch)
            ring_seconds = max(0.08, min(2.0, 3.2 / max(0.6, float(info["decay"] or 12.0))))
            tail = int(round(ring_seconds * sample_rate))
        else:
            tail = int(round(max(release, 0.05) * sample_rate))
        total = gate + tail
        first = int(round(begin * sample_rate))
        if first >= length or total <= 0:
            continue
        count = min(total, length - first)
        if count <= 0:
            continue
        if drum:
            signal = _drum_voice(pitch, count, sample_rate, velocity / 127.0)
        else:
            signal = _oscillators(
                _hz(pitch),
                count,
                sample_rate,
                params,
                velocity=velocity / 127.0,
            )
            signal *= _envelope(count, sample_rate, params, gate)
        stereo_left = math.cos((float(pan) + 1.0) * math.pi / 4.0)
        stereo_right = math.sin((float(pan) + 1.0) * math.pi / 4.0)
        scale = float(gain) * float(_MASTER_GAIN)
        out[first : first + count, 0] += signal * (scale * stereo_left)
        out[first : first + count, 1] += signal * (scale * stereo_right)


def _apply_reverb(samples: Any, sample_rate: int, mix: float = 0.16) -> Any:
    import numpy as np

    if mix <= 0.0:
        return samples
    wet = np.zeros_like(samples)
    total = samples.shape[0]
    taps = ((0.031, 0.34), (0.047, 0.27), (0.073, 0.21), (0.109, 0.15))
    for delay_seconds, feedback in taps:
        delay = max(1, int(sample_rate * delay_seconds))
        for channel in range(samples.shape[1]):
            buffer = np.zeros(total, dtype=np.float32)
            for start in range(0, total, delay):
                stop = min(total, start + delay)
                previous = buffer[start - delay : stop - delay] if start >= delay else None
                if previous is None:
                    buffer[start:stop] = samples[start:stop, channel]
                else:
                    buffer[start:stop] = samples[start:stop, channel] + feedback * previous
            wet[:, channel] += buffer
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
    length = max(1, min(length, sample_rate * midi_session.MAX_SESSION_SECONDS))
    out = np.zeros((length, 2), dtype=np.float32)
    for part in selected:
        _render_part_events(
            part,
            sample_rate=sample_rate,
            start_offset=start_offset,
            length=length,
            gain=float(part.get("volume", 1.0) or 1.0),
            pan=float(part.get("pan", 0.0) or 0.0),
            out=out,
        )
    out = _apply_reverb(out, sample_rate, mix=float(reverb))
    return _finalise(out)


def render_part(
    session: dict[str, Any],
    part: dict[str, Any],
    *,
    sample_rate: int = 44100,
    window: tuple[float, float] | None = None,
    tail: float = 0.45,
    reverb: float = 0.16,
) -> Any:
    """单独渲染一个声部（分乐器渲染成各自音轨时用）。"""
    return render_session(
        session,
        parts=[part],
        sample_rate=sample_rate,
        window=window,
        tail=tail,
        reverb=reverb,
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
