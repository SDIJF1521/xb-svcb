"""由歌唱推理工作者共享的源导向自然性保护。
该源仅用作时间与响度包络的参考。
转换后的语音中未混合任何源样本或频谱内容，
因此目标扬声器的身份完全由模型生成。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


_PROFILES = {
    "so-vits-svc": {"strength": 0.36, "silence_db": 14.0},
    "rvc": {"strength": 0.42, "silence_db": 15.0},
    "seed-vc": {"strength": 0.32, "silence_db": 12.0},
    "ddsp-svc": {"strength": 0.46, "silence_db": 16.0},
}


def _frame_rms(signal: Any, frame_size: int) -> Any:
    import numpy as np

    mono = np.asarray(signal, dtype=np.float32).reshape(-1)
    if not len(mono):
        return np.zeros(0, dtype=np.float64)
    count = int(np.ceil(len(mono) / frame_size))
    padded = np.pad(mono * mono, (0, count * frame_size - len(mono)))
    return np.sqrt(
        np.mean(padded.reshape(count, frame_size), axis=1, dtype=np.float64) + 1e-16
    )


def _smooth_curve(values: Any, radius: int) -> Any:
    import numpy as np

    curve = np.asarray(values, dtype=np.float64)
    radius = max(0, int(radius))
    if radius == 0 or len(curve) < 2:
        return curve.copy()
    kernel = np.ones(radius * 2 + 1, dtype=np.float64) / (radius * 2 + 1)
    padded = np.pad(curve, (radius, radius), mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def _bridge_short_gaps(mask: Any, max_gap: int) -> tuple[Any, int]:
    import numpy as np

    bridged = np.asarray(mask, dtype=bool).copy()
    count = 0
    index = 0
    while index < len(bridged):
        if bridged[index]:
            index += 1
            continue
        start = index
        while index < len(bridged) and not bridged[index]:
            index += 1
        if start > 0 and index < len(bridged) and index - start <= max_gap:
            bridged[start:index] = True
            count += 1
    return bridged, count


def _protect_region(mask: Any, pre_frames: int, post_frames: int) -> Any:
    import numpy as np

    source = np.asarray(mask, dtype=bool)
    protected = source.copy()
    for index in np.flatnonzero(source):
        protected[max(0, index - pre_frames) : min(len(source), index + post_frames + 1)] = True
    return protected


def _exact_silence_keep_curve(
    exact_silence: Any,
    minimum_frames: int,
    fade_frames: int,
) -> tuple[Any, int]:
    """返回一个帧率曲线，精确地恢复长时间的数字沉默。"""
    import numpy as np

    silent = np.asarray(exact_silence, dtype=bool)
    keep = np.ones(len(silent), dtype=np.float64)
    restored = 0
    index = 0
    while index < len(silent):
        if not silent[index]:
            index += 1
            continue
        start = index
        while index < len(silent) and silent[index]:
            index += 1
        end = index
        if end - start < minimum_frames:
            continue
        restored += end - start
        fade = min(fade_frames, max(0, (end - start - 1) // 2))
        keep[start:end] = 0.0
        if fade:
            phase = np.linspace(0.0, 1.0, fade, endpoint=False)
            keep[start : start + fade] = np.cos(phase * np.pi * 0.5) ** 2
            keep[end - fade : end] = np.sin(phase * np.pi * 0.5) ** 2
    return keep, restored


def _apply_frame_gain(audio: Any, values: Any, frame_size: int) -> tuple[Any, float]:
    """在块中应用帧率增益曲线以绑定整首歌RAM使用。"""
    import numpy as np

    curve = np.asarray(values, dtype=np.float64)
    processed = np.asarray(audio, dtype=np.float32).copy()
    sample_count = len(processed)
    if sample_count <= 0:
        return processed, 0.0
    if not len(curve):
        peak = float(np.max(np.abs(processed))) if processed.size else 0.0
        return processed, peak
    centres = np.minimum(
        sample_count - 1,
        np.arange(len(curve), dtype=np.float64) * frame_size + frame_size * 0.5,
    )
    peak = 0.0
    block_size = 1_000_000
    for start in range(0, sample_count, block_size):
        end = min(sample_count, start + block_size)
        positions = np.arange(start, end, dtype=np.float64)
        block_gain = np.interp(
            positions,
            centres,
            curve,
            left=float(curve[0]),
            right=float(curve[-1]),
        ).astype(np.float32)
        processed[start:end] *= block_gain[:, np.newaxis]
        peak = max(peak, float(np.max(np.abs(processed[start:end]))))
    return processed, peak


def _source_on_output_timeline(source: Any, output_frames: int) -> Any:
    import numpy as np

    data = np.asarray(source, dtype=np.float32)
    if data.ndim == 1:
        data = data[:, np.newaxis]
    mono = (
        np.mean(data, axis=1, dtype=np.float32)
        if len(data)
        else np.zeros(0, dtype=np.float32)
    )
    if output_frames <= 0:
        return np.zeros(0, dtype=np.float64)
    if not len(mono):
        return np.zeros(output_frames, dtype=np.float64)
    if len(mono) == output_frames:
        return mono
    result = np.empty(output_frames, dtype=np.float32)
    scale = (len(mono) - 1) / max(1, output_frames - 1)
    block_size = 1_000_000
    for start in range(0, output_frames, block_size):
        end = min(output_frames, start + block_size)
        positions = np.arange(start, end, dtype=np.float64) * scale
        left = np.floor(positions).astype(np.int64)
        right = np.minimum(left + 1, len(mono) - 1)
        fraction = (positions - left).astype(np.float32)
        result[start:end] = mono[left] * (1.0 - fraction) + mono[right] * fraction
    return result


def naturalize_inference_output(
    source_path: str | Path,
    output_path: str | Path,
    engine: str,
    duration_ratio: float = 1.0,
) -> dict[str, float]:
    """恢复自然停顿和微动力学没有借用源音色"""
    import numpy as np
    import soundfile as sf

    source_path = Path(source_path)
    output_path = Path(output_path)
    profile = _PROFILES.get(engine, _PROFILES["so-vits-svc"])

    source, source_rate = sf.read(str(source_path), dtype="float32", always_2d=True)
    output, sample_rate = sf.read(str(output_path), dtype="float32", always_2d=True)
    info = sf.info(str(output_path))
    if not len(output):
        raise RuntimeError("推理输出为空，无法执行自然度保护")
    if not bool(np.isfinite(output).all()):
        raise RuntimeError("推理输出包含非有限样本")

    ratio = max(0.25, min(4.0, float(duration_ratio)))
    expected_frames = max(1, int(round(len(source) * sample_rate / source_rate * ratio)))
    duration_adjustment_ms = (expected_frames - len(output)) * 1000.0 / sample_rate
    if len(output) > expected_frames:
        output = output[:expected_frames]
    elif len(output) < expected_frames:
        output = np.pad(output, ((0, expected_frames - len(output)), (0, 0)))

    frame_size = max(32, int(round(sample_rate * 0.010)))
    source_mono = _source_on_output_timeline(source, len(output))
    output_mono = np.mean(output, axis=1, dtype=np.float32)
    source_rms = _frame_rms(source_mono, frame_size)
    output_rms = _frame_rms(output_mono, frame_size)
    frame_count = min(len(source_rms), len(output_rms))
    source_rms = source_rms[:frame_count]
    output_rms = output_rms[:frame_count]

    source_db = 20.0 * np.log10(source_rms + 1e-10)
    output_db = 20.0 * np.log10(output_rms + 1e-10)
    finite_source = source_db[np.isfinite(source_db)]
    active_db = float(np.percentile(finite_source, 92)) if len(finite_source) else -60.0
    floor_db = max(-64.0, active_db - 40.0)
    normalized = np.clip((source_db - floor_db) / 12.0, 0.0, 1.0)
    confidence = normalized * normalized * (3.0 - 2.0 * normalized)

    active_mask = confidence >= 0.12
    active_mask, short_gaps = _bridge_short_gaps(
        active_mask,
        max_gap=max(1, int(round(0.380 * sample_rate / frame_size))),
    )
    protected = _protect_region(
        active_mask,
        pre_frames=max(1, int(round(0.070 * sample_rate / frame_size))),
        post_frames=max(1, int(round(0.240 * sample_rate / frame_size))),
    )
    protected_curve = _smooth_curve(
        protected.astype(np.float64),
        radius=max(1, int(round(0.050 * sample_rate / frame_size))),
    )

    silence_db = float(profile["silence_db"])
    gate_db = -silence_db * np.square(1.0 - np.clip(protected_curve, 0.0, 1.0))

    voiced = confidence >= 0.25
    correction_db = np.zeros(frame_count, dtype=np.float64)
    if int(np.count_nonzero(voiced)) >= 8:
        source_reference = float(np.percentile(source_db[voiced], 65))
        output_reference = float(np.percentile(output_db[voiced], 65))
        relative_source = source_db - source_reference
        relative_output = output_db - output_reference
        correction_db = np.clip(relative_source - relative_output, -3.0, 2.0)
        correction_db *= confidence * float(profile["strength"])
        correction_db = _smooth_curve(
            correction_db,
            radius=max(1, int(round(0.080 * sample_rate / frame_size))),
        )

    exact_keep, exact_frames = _exact_silence_keep_curve(
        source_rms <= 1e-8,
        minimum_frames=max(1, int(round(0.500 * sample_rate / frame_size))),
        fade_frames=max(1, int(round(0.060 * sample_rate / frame_size))),
    )
    gain = np.power(10.0, (gate_db + correction_db) / 20.0) * exact_keep
    processed, peak = _apply_frame_gain(output, gain, frame_size)
    peak_guard = 1.0
    if peak > 0.999:
        peak_guard = 0.999 / peak
        processed *= peak_guard
        peak = 0.999
    if not bool(np.isfinite(processed).all()):
        raise RuntimeError("推理自然度处理产生了非有限样本")

    subtype = info.subtype if info.subtype in {"PCM_16", "PCM_24", "PCM_32", "FLOAT", "DOUBLE"} else "FLOAT"
    sf.write(
        str(output_path),
        processed.astype(np.float32),
        sample_rate,
        format="WAV",
        subtype=subtype,
    )
    return {
        "active_db": active_db,
        "floor_db": floor_db,
        "short_gaps": float(short_gaps),
        "silence_reduction_db": silence_db,
        "dynamic_min_db": float(np.min(correction_db)) if len(correction_db) else 0.0,
        "dynamic_max_db": float(np.max(correction_db)) if len(correction_db) else 0.0,
        "exact_silence_seconds": exact_frames * frame_size / sample_rate,
        "peak": peak,
        "peak_guard": peak_guard,
        "duration_adjustment_ms": duration_adjustment_ms,
    }


def format_naturalizer_stats(stats: dict[str, float]) -> str:
    return (
        f"short_gaps={int(stats['short_gaps'])} "
        f"silence=-{stats['silence_reduction_db']:.0f}dB "
        f"dynamics={stats['dynamic_min_db']:+.2f}..{stats['dynamic_max_db']:+.2f}dB "
        f"exact_silence={stats['exact_silence_seconds']:.2f}s "
        f"duration={stats['duration_adjustment_ms']:+.1f}ms "
        f"peak={stats['peak']:.4f}"
    )
