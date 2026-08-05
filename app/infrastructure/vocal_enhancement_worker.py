"""独立歌声增强 worker，重点保留歌声的自然包络和微动态。

后处理无法重新生成 vocoder 已经丢失的细节，因此这里不靠堆叠效果掩盖
AI 痕迹。基础层使用自然停顿扩展、限量神经降噪和轻母带；高级层额外借用
原始人声中与音色身份关系较弱的高频辅音/呼吸细节，并只校正宽带频谱倾斜。
最终使用并行干湿混合保住起音、尾音和原始动态。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path


def _write_float_wav(output: Path, audio: "np.ndarray", sample_rate: int) -> None:
    """Write channel-first audio without repeated PCM16 quantization."""
    import numpy as np
    import soundfile as sf

    data = np.asarray(audio, dtype=np.float32)
    if data.ndim == 1:
        data = data[np.newaxis, :]
    if not bool(np.isfinite(data).all()):
        raise RuntimeError("歌声增强产生了非有限音频样本")
    sf.write(str(output), data.T, sample_rate, subtype="FLOAT")


def _sample_frame_curve(
    values: "np.ndarray",
    total_frames: int,
    frame_size: int,
) -> "np.ndarray":
    """Interpolate a short frame-rate control signal to the audio sample rate."""
    import numpy as np

    curve = np.asarray(values, dtype=np.float64)
    if total_frames <= 0:
        return np.zeros(0, dtype=np.float64)
    if not len(curve):
        return np.zeros(total_frames, dtype=np.float64)
    centres = np.minimum(
        total_frames - 1,
        np.arange(len(curve), dtype=np.float64) * frame_size + frame_size * 0.5,
    )
    return np.interp(
        np.arange(total_frames, dtype=np.float64),
        centres,
        curve,
        left=float(curve[0]),
        right=float(curve[-1]),
    )


def _adaptive_activity_curve(
    audio: "np.ndarray",
    sample_rate: int,
) -> tuple["np.ndarray", dict[str, float]]:
    """Return a smoothed 0..1 voice-confidence curve from local 20 ms energy."""
    import numpy as np
    from scipy.ndimage import gaussian_filter1d

    data = np.asarray(audio, dtype=np.float64)
    if data.ndim == 1:
        data = data[:, np.newaxis]
    total_frames = len(data)
    if total_frames == 0:
        return np.zeros(0, dtype=np.float64), {
            "active_db": -120.0,
            "floor_db": -120.0,
            "dynamic_db": 0.0,
        }

    frame_size = max(32, int(round(sample_rate * 0.020)))
    frame_count = int(np.ceil(total_frames / frame_size))
    padded = np.pad(
        np.mean(data * data, axis=1),
        (0, frame_count * frame_size - total_frames),
    )
    frame_rms = np.sqrt(
        np.mean(padded.reshape(frame_count, frame_size), axis=1) + 1e-12
    )
    levels = 20.0 * np.log10(frame_rms + 1e-10)
    active_db = float(np.percentile(levels, 90))
    floor_db = max(-58.0, active_db - 34.0)
    normalized = np.clip((levels - floor_db) / 14.0, 0.0, 1.0)
    confidence = normalized * normalized * (3.0 - 2.0 * normalized)
    confidence = gaussian_filter1d(
        confidence,
        sigma=max(1.0, 0.055 * sample_rate / frame_size),
        mode="nearest",
    )
    active_levels = levels[levels >= floor_db]
    dynamic_db = (
        float(np.percentile(active_levels, 90) - np.percentile(active_levels, 20))
        if len(active_levels) >= 3
        else 0.0
    )
    return _sample_frame_curve(confidence, total_frames, frame_size), {
        "active_db": active_db,
        "floor_db": floor_db,
        "dynamic_db": dynamic_db,
    }


def _adaptive_high_guard_curve(
    audio: "np.ndarray",
    high_band: "np.ndarray",
    sample_rate: int,
) -> tuple["np.ndarray", dict[str, float]]:
    """Estimate local sibilance/high-frequency dominance without changing audio."""
    import numpy as np
    from scipy.ndimage import gaussian_filter1d

    data = np.asarray(audio, dtype=np.float64)
    high = np.asarray(high_band, dtype=np.float64)
    if data.ndim == 1:
        data = data[:, np.newaxis]
    if high.ndim == 1:
        high = high[:, np.newaxis]
    total_frames = min(len(data), len(high))
    if total_frames == 0:
        return np.zeros(0, dtype=np.float64), {
            "median_high_ratio": 0.0,
            "peak_guard": 0.0,
        }

    data = data[:total_frames]
    high = high[:total_frames]
    frame_size = max(32, int(round(sample_rate * 0.020)))
    frame_count = int(np.ceil(total_frames / frame_size))
    padding = frame_count * frame_size - total_frames
    total_power = np.pad(np.mean(data * data, axis=1), (0, padding))
    high_power = np.pad(np.mean(high * high, axis=1), (0, padding))
    total_power = np.mean(total_power.reshape(frame_count, frame_size), axis=1)
    high_power = np.mean(high_power.reshape(frame_count, frame_size), axis=1)
    ratio = np.sqrt(high_power / np.maximum(total_power, 1e-12))
    guard = np.clip((ratio - 0.30) / 0.24, 0.0, 1.0)
    guard = gaussian_filter1d(
        guard,
        sigma=max(1.0, 0.035 * sample_rate / frame_size),
        mode="nearest",
    )
    active_ratio = ratio[total_power >= max(float(np.percentile(total_power, 70)) * 0.01, 1e-10)]
    return _sample_frame_curve(guard, total_frames, frame_size), {
        "median_high_ratio": float(np.median(active_ratio)) if len(active_ratio) else 0.0,
        "peak_guard": float(np.max(guard)) if len(guard) else 0.0,
    }


def _adaptive_mastering_profile(
    audio: "np.ndarray",
    sample_rate: int,
    advanced: bool,
) -> dict[str, float]:
    """Analyze this vocal and derive bounded mastering parameters for the track."""
    import numpy as np
    from scipy.signal import welch

    data = np.asarray(audio, dtype=np.float64)
    if data.ndim == 1:
        data = data[:, np.newaxis]
    mono = np.mean(data, axis=1)
    _, activity_stats = _adaptive_activity_curve(data, sample_rate)
    defaults = {
        "highpass_hz": 42.0 if advanced else 45.0,
        "body_db": 0.0,
        "harsh_db": 0.0,
        "presence_db": 0.0,
        "air_db": 0.0,
        "threshold_db": float(np.clip(activity_stats["active_db"] - 5.0, -26.0, -11.0)),
        "ratio": 1.15,
        "attack_ms": 38.0,
        "release_ms": 210.0,
        "wet_mix": 0.72 if advanced else 0.60,
        "dynamic_db": activity_stats["dynamic_db"],
    }
    if len(mono) < 512 or sample_rate < 8000:
        return defaults

    frequencies, power = welch(
        mono,
        fs=sample_rate,
        nperseg=min(4096, len(mono)),
        noverlap=min(2048, max(0, len(mono) // 2 - 1)),
        average="median",
    )
    def band(low: float, high: float) -> float | None:
        mask = (frequencies >= low) & (
            frequencies <= min(high, sample_rate * 0.48)
        )
        if not bool(mask.any()):
            return None
        return float(10.0 * np.log10(np.mean(power[mask]) + 1e-12))

    core = band(700.0, 2200.0)
    if core is None:
        return defaults

    def relative(low: float, high: float, fallback: float) -> float:
        measured = band(low, high)
        return measured - core if measured is not None else fallback

    body_relative = relative(150.0, 330.0, 3.0)
    harsh_relative = relative(5200.0, 7600.0, -8.0)
    presence_relative = relative(2800.0, 5000.0, -3.0)
    air_relative = relative(8500.0, 14000.0, -12.0)
    rumble_relative = relative(25.0, 85.0, -24.0) - body_relative

    body_db = float(np.clip((3.0 - body_relative) * 0.065, -0.45, 0.55))
    harsh_db = float(np.clip((-8.0 - harsh_relative) * 0.10, -0.80, 0.0))
    presence_db = float(np.clip((-3.0 - presence_relative) * 0.060, -0.35, 0.40))
    air_db = float(np.clip((-12.0 - air_relative) * 0.040, -0.25, 0.30))
    dynamic_db = activity_stats["dynamic_db"]
    ratio = float(
        np.clip(1.08 + max(0.0, dynamic_db - 5.0) * 0.018 + (0.03 if advanced else 0.0), 1.10, 1.36)
    )
    threshold = float(np.clip(activity_stats["active_db"] - 5.5, -28.0, -11.0))
    need = float(
        np.clip(
            (
                abs(body_db) / 0.55
                + abs(harsh_db) / 0.80
                + abs(presence_db) / 0.40
                + abs(air_db) / 0.30
            )
            / 4.0,
            0.0,
            1.0,
        )
    )
    wet_base = 0.69 if advanced else 0.57
    wet_mix = float(np.clip(wet_base + 0.11 * need + 0.002 * max(0.0, dynamic_db - 8.0), 0.54, 0.84 if advanced else 0.72))
    return {
        "highpass_hz": float(np.clip(38.0 + max(0.0, rumble_relative + 22.0) * 0.9, 38.0, 55.0)),
        "body_db": body_db,
        "harsh_db": harsh_db,
        "presence_db": presence_db,
        "air_db": air_db,
        "threshold_db": threshold,
        "ratio": ratio,
        "attack_ms": float(np.clip(45.0 - dynamic_db * 0.55, 28.0, 42.0)),
        "release_ms": float(np.clip(180.0 + dynamic_db * 4.0, 180.0, 250.0)),
        "wet_mix": wet_mix,
        "dynamic_db": dynamic_db,
    }


def _silence_vocalfloor_file(source: Path, output: Path) -> None:
    """文件级包装：读取源音频，做 vocalfloor 软衰减，写出到 output。

    使用 soundfile 读写（Pedalboard 的依赖，已在 .venv-vocal 中），
    保持原始采样率与声道数。
    """
    try:
        import numpy as np
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError("soundfile/numpy 未安装，请修复 vocal 增强环境") from exc

    audio, sample_rate = sf.read(str(source), always_2d=True)
    audio = audio.T  # soundfile 返回 (frames, channels)，转为 (channels, frames)
    processed = _silence_vocalfloor(audio, sample_rate)
    _write_float_wav(output, processed, sample_rate)
    if not output.is_file():
        raise RuntimeError("vocalfloor 软衰减未生成输出文件")


def _match_reference(source: Path, reference: Path, output: Path) -> None:
    """仅保守匹配参考信号的宽谱倾斜。
        匹配源歌手的完整声像包也会影响其共振峰，
        从而可能抵消目标声音。比较稳健的主动帧频谱，
        去除响度，并对两个宽频带进行最多1.25分贝的调整。
    """
    try:
        import numpy as np
        import soundfile as sf
        import librosa
        from pedalboard import HighShelfFilter, LowShelfFilter, Pedalboard
    except ImportError as exc:
        raise RuntimeError("librosa/pedalboard 未安装，请修复 vocal 增强环境") from exc

    src_audio, src_sr = sf.read(str(source), always_2d=True)
    ref_audio, ref_sr = sf.read(str(reference), always_2d=True)
    src_mono = src_audio.mean(axis=1)
    ref_mono = ref_audio.mean(axis=1)
    if ref_sr != src_sr:
        ref_mono = librosa.resample(ref_mono, orig_sr=ref_sr, target_sr=src_sr)

    # Only three broad bands are needed; non-overlapping 2048-sample frames keep long
    # songs from allocating hundreds of megabytes for analysis.
    n_fft = 2048
    hop = 2048

    def robust_log_spectrum(audio: "np.ndarray") -> "np.ndarray | None":
        magnitude = np.abs(librosa.stft(audio, n_fft=n_fft, hop_length=hop))
        frame_rms = np.sqrt(np.mean(magnitude ** 2, axis=0) + 1e-12)
        frame_db = 20.0 * np.log10(frame_rms + 1e-10)
        active = frame_db >= max(-55.0, float(np.percentile(frame_db, 90)) - 24.0)
        if int(active.sum()) < 2:
            return None
        return np.median(20.0 * np.log10(magnitude[:, active] + 1e-7), axis=1)

    src_spectrum = robust_log_spectrum(src_mono)
    ref_spectrum = robust_log_spectrum(ref_mono)
    if src_spectrum is None or ref_spectrum is None:
        shutil.copy2(source, output)
        return

    freqs = np.fft.rfftfreq(n_fft, 1.0 / src_sr)

    def band_median(values: "np.ndarray", low: float, high: float) -> float:
        mask = (freqs >= low) & (freqs <= min(high, src_sr / 2.0))
        return float(np.median(values[mask])) if bool(mask.any()) else 0.0

    # Remove global level before comparing low/mid/high balance.
    vocal_band = (freqs >= 180.0) & (freqs <= min(12000.0, src_sr / 2.0))
    src_spectrum = src_spectrum - np.median(src_spectrum[vocal_band])
    ref_spectrum = ref_spectrum - np.median(ref_spectrum[vocal_band])
    difference = ref_spectrum - src_spectrum
    mid = band_median(difference, 700.0, 3500.0)
    low_gain = float(np.clip((band_median(difference, 180.0, 500.0) - mid) * 0.3, -1.25, 1.25))
    high_gain = float(np.clip((band_median(difference, 5000.0, 12000.0) - mid) * 0.3, -1.25, 1.25))
    print(
        f"  宽带参考校正(dB): low={low_gain:+.2f}, high={high_gain:+.2f}",
        flush=True,
    )

    filters = []
    if abs(low_gain) >= 0.2:
        filters.append(LowShelfFilter(cutoff_frequency_hz=350.0, gain_db=low_gain, q=0.6))
    if abs(high_gain) >= 0.2 and src_sr / 2.0 > 5500.0:
        filters.append(HighShelfFilter(cutoff_frequency_hz=5500.0, gain_db=high_gain, q=0.6))
    if not filters:
        shutil.copy2(source, output)
        return

    processed = Pedalboard(filters)(src_audio.T.astype(np.float32), sample_rate=src_sr, reset=True)
    _write_float_wav(output, processed, src_sr)
    if not output.is_file():
        raise RuntimeError("频谱匹配未生成输出文件")


def _restore_reference_detail(source: Path, reference: Path, output: Path) -> None:
    """从原始人声中恢复少量对齐的无声细节。
        扬声器身份在5.5 kHz分频点以下集中。在此以上，
        当参考信号以高频为主时，自适应的8%最大平滑过渡可恢复真实的塞音和呼吸声。
        对于未对齐的文件，此功能被有意跳过。
    """
    try:
        import librosa
        import numpy as np
        import soundfile as sf
        from scipy.ndimage import gaussian_filter1d, uniform_filter1d
        from scipy.signal import butter, sosfiltfilt
    except ImportError as exc:
        raise RuntimeError("librosa/scipy 未安装，请修复 vocal 增强环境") from exc

    src_audio, src_sr = sf.read(str(source), always_2d=True)
    ref_audio, ref_sr = sf.read(str(reference), always_2d=True)
    if ref_sr != src_sr:
        ref_audio = np.column_stack(
            [
                librosa.resample(channel, orig_sr=ref_sr, target_sr=src_sr)
                for channel in ref_audio.T
            ]
        )

    if src_audio.shape[1] != ref_audio.shape[1]:
        if src_audio.shape[1] == 1:
            ref_audio = ref_audio.mean(axis=1, keepdims=True)
        elif ref_audio.shape[1] == 1:
            ref_audio = np.repeat(ref_audio, src_audio.shape[1], axis=1)
        else:
            ref_audio = np.repeat(
                ref_audio.mean(axis=1, keepdims=True),
                src_audio.shape[1],
                axis=1,
            )

    length_delta = abs(len(src_audio) - len(ref_audio))
    if (
        src_sr < 16000
        or min(len(src_audio), len(ref_audio)) < 128
        or length_delta > max(int(src_sr * 0.05), int(len(src_audio) * 0.002))
    ):
        shutil.copy2(source, output)
        print("  跳过真实细节保护（参考音频未对齐）", flush=True)
        return

    if len(ref_audio) < len(src_audio):
        ref_audio = np.pad(ref_audio, ((0, len(src_audio) - len(ref_audio)), (0, 0)))
    else:
        ref_audio = ref_audio[: len(src_audio)]

    # 转移类似噪声的辅音之前，对振幅包络线进行对齐。长度相等
    # 单独使用是不够的，因为某些推理引擎仍存在较小的全局延迟。
    envelope_window = max(1, int(src_sr * 0.02))
    envelope_hop = max(1, int(src_sr * 0.01))
    src_envelope = np.sqrt(
        uniform_filter1d(
            np.mean(src_audio ** 2, axis=1),
            size=envelope_window,
            mode="nearest",
        )
        + 1e-10
    )[::envelope_hop]
    ref_envelope = np.sqrt(
        uniform_filter1d(
            np.mean(ref_audio ** 2, axis=1),
            size=envelope_window,
            mode="nearest",
        )
        + 1e-10
    )[::envelope_hop]
    src_envelope = np.clip(
        20.0 * np.log10(src_envelope),
        float(20.0 * np.log10(src_envelope).max()) - 50.0,
        None,
    )
    ref_envelope = np.clip(
        20.0 * np.log10(ref_envelope),
        float(20.0 * np.log10(ref_envelope).max()) - 50.0,
        None,
    )
    max_lag = max(1, int(round(0.08 * src_sr / envelope_hop)))
    best_lag = 0
    best_correlation = -1.0
    for lag in range(-max_lag, max_lag + 1):
        if lag > 0:
            src_part, ref_part = src_envelope[lag:], ref_envelope[:-lag]
        elif lag < 0:
            src_part, ref_part = src_envelope[:lag], ref_envelope[-lag:]
        else:
            src_part, ref_part = src_envelope, ref_envelope
        if len(src_part) < 8 or float(np.std(src_part) * np.std(ref_part)) < 1e-6:
            continue
        correlation = float(np.corrcoef(src_part, ref_part)[0, 1])
        if np.isfinite(correlation) and correlation > best_correlation:
            best_lag = lag
            best_correlation = correlation

    if best_correlation < 0.25:
        shutil.copy2(source, output)
        print("  跳过真实细节保护（参考内容相关性不足）", flush=True)
        return
    sample_lag = best_lag * envelope_hop
    if sample_lag > 0:
        ref_audio = np.pad(ref_audio, ((sample_lag, 0), (0, 0)))[
            : len(src_audio)
        ]
    elif sample_lag < 0:
        shift = -sample_lag
        ref_audio = np.pad(ref_audio[shift:], ((0, shift), (0, 0)))
    print(
        f"  参考细节对齐: lag={sample_lag * 1000 / src_sr:+.0f}ms, "
        f"corr={best_correlation:.2f}",
        flush=True,
    )

    sos = butter(4, 5500.0, btype="highpass", fs=src_sr, output="sos")
    src_high = sosfiltfilt(sos, src_audio, axis=0)
    ref_high = sosfiltfilt(sos, ref_audio, axis=0)

    src_rms = float(np.sqrt(np.mean(src_audio ** 2) + 1e-12))
    ref_rms = float(np.sqrt(np.mean(ref_audio ** 2) + 1e-12))
    if src_rms < 1e-6 or ref_rms < 1e-6:
        shutil.copy2(source, output)
        return
    ref_scale = float(np.clip(src_rms / ref_rms, 0.5, 2.0))

    window = max(1, int(src_sr * 0.02))
    ref_power = uniform_filter1d(
        np.mean((ref_audio * ref_scale) ** 2, axis=1),
        size=window,
        mode="nearest",
    )
    high_power = uniform_filter1d(
        np.mean((ref_high * ref_scale) ** 2, axis=1),
        size=window,
        mode="nearest",
    )
    # 递归均匀滤波器在长信号下可能因几个微小的单位量化误差（ULP）而低于平方信号。
    # 在开平方根之前对数值噪声进行钳位，以防止其污染输出结果。
    ref_power = np.maximum(ref_power, 0.0)
    high_power = np.maximum(high_power, 0.0)
    high_ratio = np.sqrt(high_power / np.maximum(ref_power, 1e-10))
    detail_activity = np.clip((high_ratio - 0.08) / 0.22, 0.0, 1.0)
    level_db = 10.0 * np.log10(ref_power + 1e-10)
    audible = np.clip((level_db + 55.0) / 18.0, 0.0, 1.0)
    src_power = uniform_filter1d(
        np.mean(src_audio ** 2, axis=1),
        size=window,
        mode="nearest",
    )
    src_level_db = 10.0 * np.log10(np.maximum(src_power, 1e-10))
    source_present = np.clip((src_level_db + 60.0) / 20.0, 0.0, 1.0)
    detail_mix = 0.08 * detail_activity * audible * np.sqrt(source_present)
    detail_mix = gaussian_filter1d(
        detail_mix,
        sigma=max(1.0, src_sr * 0.008),
        mode="nearest",
    )

    restored = src_audio + detail_mix[:, np.newaxis] * (
        ref_high * ref_scale - src_high
    )
    peak = float(np.max(np.abs(restored))) if restored.size else 0.0
    if peak > 0.99:
        restored *= 0.99 / peak
    _write_float_wav(output, restored.T, src_sr)
    print(
        f"  真实辅音/呼吸细节保护: peak mix={float(detail_mix.max()) * 100:.1f}%",
        flush=True,
    )


def _parallel_mix(dry: Path, wet: Path, output: Path, wet_mix: float) -> None:
    """Blend toward the wet master with a smoothed, phrase-local amount."""
    try:
        import librosa
        import numpy as np
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError("soundfile/librosa 未安装，请修复 vocal 增强环境") from exc

    dry_audio, dry_sr = sf.read(str(dry), always_2d=True)
    wet_audio, wet_sr = sf.read(str(wet), always_2d=True)
    if wet_sr != dry_sr:
        wet_audio = np.column_stack(
            [
                librosa.resample(channel, orig_sr=wet_sr, target_sr=dry_sr)
                for channel in wet_audio.T
            ]
        )

    if dry_audio.shape[1] != wet_audio.shape[1]:
        if dry_audio.shape[1] == 1:
            wet_audio = wet_audio.mean(axis=1, keepdims=True)
        elif wet_audio.shape[1] == 1:
            wet_audio = np.repeat(wet_audio, dry_audio.shape[1], axis=1)
        else:
            wet_audio = np.repeat(
                wet_audio.mean(axis=1, keepdims=True),
                dry_audio.shape[1],
                axis=1,
            )

    aligned = np.zeros_like(dry_audio)
    frames = min(len(dry_audio), len(wet_audio))
    aligned[:frames] = wet_audio[:frames]
    activity, activity_stats = _adaptive_activity_curve(dry_audio, dry_sr)
    active = activity >= 0.10
    if bool(active.any()):
        dry_rms = float(np.sqrt(np.mean(dry_audio[active] ** 2) + 1e-12))
        wet_rms = float(np.sqrt(np.mean(aligned[active] ** 2) + 1e-12))
        if wet_rms > 1e-7:
            aligned *= float(np.clip(dry_rms / wet_rms, 0.75, 1.25))

    amount = float(np.clip(wet_mix, 0.0, 1.0))
    # The requested wet value is an upper bound. Quiet breaths and transitions retain
    # more of the dry render, while steady voiced frames approach the analyzed ceiling.
    local_amount = amount * np.where(
        activity >= 0.015,
        0.28 + 0.72 * np.sqrt(activity),
        0.0,
    )
    mixed = dry_audio + (aligned - dry_audio) * local_amount[:, np.newaxis]
    peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
    if peak > 0.99:
        mixed *= 0.99 / peak
    _write_float_wav(output, mixed.T, dry_sr)
    active_amount = local_amount[active]
    dynamic_min = float(np.percentile(active_amount, 10)) if len(active_amount) else 0.0
    dynamic_max = float(np.percentile(active_amount, 90)) if len(active_amount) else 0.0
    print(
        "  动态并行母带: "
        f"wet={dynamic_min:.0%}-{dynamic_max:.0%}, "
        f"local range={activity_stats['dynamic_db']:.1f}dB",
        flush=True,
    )


def _ai_loudness_envelope_array(
    control: "np.ndarray",
    processed: "np.ndarray",
    sample_rate: int,
    strength: float,
) -> tuple["np.ndarray", dict[str, float]]:
    """
    使用有界增益曲线恢复AI人声的局部响度轮廓。
    控制信号是增强前的AI渲染结果。仅使用其短期能量，
    因此此阶段无法复制原始音色或波形细节。
    轮廓处理特意比压缩检测器慢，并通过人声活动进行门控，
    以避免出现停顿、呼吸声或残留的降噪噪声。
    """
    import numpy as np
    from scipy.ndimage import gaussian_filter1d, uniform_filter1d

    target = np.asarray(control, dtype=np.float64)
    wet = np.asarray(processed, dtype=np.float64)
    if target.ndim == 1:
        target = target[:, np.newaxis]
    if wet.ndim == 1:
        wet = wet[:, np.newaxis]
    amount = float(np.clip(strength, 0.0, 1.0))
    if amount <= 0.0 or not len(target) or not len(wet):
        return wet.copy(), {"correction_db_min": 0.0, "correction_db_max": 0.0, "active_db": 0.0}

    total = len(target)
    channels = max(target.shape[1], wet.shape[1])
    if target.shape[1] != channels:
        target = np.repeat(target.mean(axis=1, keepdims=True), channels, axis=1)
    if wet.shape[1] != channels:
        wet = np.repeat(wet.mean(axis=1, keepdims=True), channels, axis=1)
    if len(wet) < total:
        wet = np.pad(wet, ((0, total - len(wet)), (0, 0)))
    else:
        wet = wet[:total]

    mono_target = target.mean(axis=1)
    mono_wet = wet.mean(axis=1)
    frame_size = max(32, int(round(sample_rate * 0.020)))
    hop = max(16, int(round(sample_rate * 0.010)))
    centres = np.arange(0, total, hop, dtype=np.int64)
    if not len(centres):
        return wet.copy(), {"correction_db_min": 0.0, "correction_db_max": 0.0, "active_db": 0.0}

    target_power = uniform_filter1d(mono_target * mono_target, frame_size, mode="nearest")
    wet_power = uniform_filter1d(mono_wet * mono_wet, frame_size, mode="nearest")
    target_db = 20.0 * np.log10(np.sqrt(np.maximum(target_power[centres], 1e-12)) + 1e-10)
    wet_db = 20.0 * np.log10(np.sqrt(np.maximum(wet_power[centres], 1e-12)) + 1e-10)

    # Use a 70 ms contour so individual consonants do not turn into audible gain
    # pumping. The source AI envelope remains the only loudness reference.
    contour_sigma = max(1.0, 0.070 / 0.010)
    target_contour = gaussian_filter1d(target_db, sigma=contour_sigma, mode="nearest")
    wet_contour = gaussian_filter1d(wet_db, sigma=contour_sigma, mode="nearest")
    correction_db = np.clip(target_contour - wet_contour, -3.0, 3.0)

    activity, activity_stats = _adaptive_activity_curve(target, sample_rate)
    frame_activity = activity[centres]
    gate = np.clip((frame_activity - 0.08) / 0.42, 0.0, 1.0)
    gate = gaussian_filter1d(gate, sigma=max(1.0, 0.035 / 0.010), mode="nearest")
    correction_db *= amount * gate

    correction_samples = np.interp(
        np.arange(total, dtype=np.float64),
        centres.astype(np.float64),
        correction_db,
        left=float(correction_db[0]),
        right=float(correction_db[-1]),
    )
    correction_samples = gaussian_filter1d(
        correction_samples,
        sigma=max(1.0, 0.012 * sample_rate),
        mode="nearest",
    )
    gain = 10.0 ** (correction_samples / 20.0)
    restored = wet * gain[:, np.newaxis]
    peak = float(np.max(np.abs(restored))) if restored.size else 0.0
    if peak > 0.99:
        restored *= 0.99 / peak

    active = frame_activity >= 0.10
    active_correction = correction_db[active]
    return restored, {
        "correction_db_min": float(np.percentile(active_correction, 10)) if len(active_correction) else 0.0,
        "correction_db_max": float(np.percentile(active_correction, 90)) if len(active_correction) else 0.0,
        "active_db": float(activity_stats["active_db"]),
    }


def _ai_loudness_envelope(
    control_source: Path,
    source: Path,
    output: Path,
    strength: float,
) -> None:
    """Apply the AI loudness envelope to a rendered enhancement output."""
    try:
        import librosa
        import numpy as np
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError("soundfile/librosa/scipy 未安装，请修复 vocal 增强环境") from exc

    control, control_sr = sf.read(str(control_source), always_2d=True)
    processed, processed_sr = sf.read(str(source), always_2d=True)
    if processed_sr != control_sr:
        processed = np.column_stack(
            [
                librosa.resample(channel, orig_sr=processed_sr, target_sr=control_sr)
                for channel in processed.T
            ]
        )
    restored, stats = _ai_loudness_envelope_array(
        control,
        processed,
        control_sr,
        strength,
    )
    _write_float_wav(output, restored.T, control_sr)
    print(
        "  AI 响度包络: "
        f"active={stats['active_db']:.1f}dB, "
        f"correction={stats['correction_db_min']:+.2f}~{stats['correction_db_max']:+.2f}dB",
        flush=True,
    )


def _deepfilter(
    source: Path,
    output: Path,
    atten_lim_db: float = 3.0,
) -> None:
    """以原生速率运行 DeepFilterNet，然后恢复输入速率。
        DeepFilterNet3 是一个 48 kHz 模型。
        将 44.1 kHz 的采样信号直接输入其 STFT，
        会改变每个分析频带，并添加金属质感色彩。同时，
        3 dB 的衰减限制可防止该语音降噪器过度覆盖干净的歌唱音频。
    """
    try:
        from df.enhance import enhance, init_df, load_audio
    except ImportError as exc:
        raise RuntimeError("DeepFilterNet 未安装，请修复 vocal 增强环境") from exc

    import numpy as np
    import torchaudio

    model_dir = os.environ.get("XB_DEEPFILTER_MODEL_DIR")
    model, state, _ = init_df(model_dir) if model_dir else init_df()
    model_sr = int(state.sr())
    audio, info = load_audio(str(source), sr=model_sr)
    enhanced = enhance(
        model,
        state,
        audio,
        atten_lim_db=float(max(1.5, min(12.0, atten_lim_db))),
    )

    orig_sr = int(info.sample_rate)
    if model_sr != orig_sr:
        enhanced = torchaudio.functional.resample(enhanced, model_sr, orig_sr)

    # 重采样器可能相差一个样本。
    enhanced_audio = np.asarray(enhanced.detach().cpu(), dtype=np.float32)
    expected_frames = int(info.num_frames)
    if enhanced_audio.shape[-1] > expected_frames:
        enhanced_audio = enhanced_audio[..., :expected_frames]
    elif enhanced_audio.shape[-1] < expected_frames:
        enhanced_audio = np.pad(
            enhanced_audio,
            ((0, 0), (0, expected_frames - enhanced_audio.shape[-1])),
        )

    _write_float_wav(output, enhanced_audio, orig_sr)
    if not output.is_file():
        raise RuntimeError("DeepFilterNet 未生成输出文件")


def _audio_profile_array(
    audio: "np.ndarray",
    sample_rate: int,
) -> dict[str, float | bool]:
    """Measure high-band energy and the usable singing range of a vocal."""
    import numpy as np
    from scipy.signal import find_peaks, spectrogram, welch

    data = np.asarray(audio, dtype=np.float32)
    if data.ndim == 2:
        mono = np.mean(data, axis=1)
    else:
        mono = data.reshape(-1)
    mono = np.nan_to_num(mono, copy=False)
    if sample_rate < 4000 or len(mono) < 512:
        return {
            "sample_rate": float(sample_rate),
            "spectral_centroid_hz": 0.0,
            "high_band_ratio": 0.0,
            "median_f0_hz": 0.0,
            "p95_f0_hz": 0.0,
            "max_f0_hz": 0.0,
            "high_frequency": False,
            "high_pitch": False,
            "recommended_f0_max": 1100.0,
        }

    # Bound analysis cost for long songs while retaining a representative opening.
    analysis_frames = min(len(mono), int(sample_rate * 120.0))
    mono = mono[:analysis_frames]
    frequencies, power = welch(
        mono,
        fs=sample_rate,
        nperseg=min(8192, len(mono)),
        noverlap=min(4096, max(0, len(mono) // 2 - 1)),
        average="median",
    )
    audible = (frequencies >= 120.0) & (
        frequencies <= min(16000.0, sample_rate * 0.48)
    )
    high = (frequencies >= 6000.0) & (
        frequencies <= min(16000.0, sample_rate * 0.48)
    )
    audible_power = float(np.sum(power[audible])) if bool(audible.any()) else 0.0
    high_power = float(np.sum(power[high])) if bool(high.any()) else 0.0
    high_ratio = high_power / max(audible_power, 1e-12)
    centroid = float(
        np.sum(frequencies[audible] * power[audible])
        / max(float(np.sum(power[audible])), 1e-12)
    ) if bool(audible.any()) else 0.0

    frame_length = min(4096 if sample_rate >= 32000 else 2048, len(mono))
    hop_length = max(128, int(round(sample_rate * 0.020)))
    frame_overlap = max(0, frame_length - hop_length)
    f0_frequencies, _, frame_power = spectrogram(
        mono,
        fs=sample_rate,
        window="hann",
        nperseg=frame_length,
        noverlap=frame_overlap,
        detrend=False,
        scaling="spectrum",
        mode="psd",
    )
    f0_band = (f0_frequencies >= 55.0) & (
        f0_frequencies <= min(1600.0, sample_rate * 0.45)
    )
    frame_levels = np.sum(frame_power, axis=0)
    active_threshold = max(
        1e-10,
        float(np.percentile(frame_levels, 75)) * 0.015
        if len(frame_levels)
        else 1e-10,
    )
    voiced_values: list[float] = []
    band_frequencies = f0_frequencies[f0_band]
    for frame_index in np.flatnonzero(frame_levels >= active_threshold):
        spectrum = frame_power[f0_band, frame_index]
        if not len(spectrum) or float(np.max(spectrum)) <= 1e-12:
            continue
        peaks, _ = find_peaks(spectrum)
        if not len(peaks):
            peaks = np.asarray([int(np.argmax(spectrum))])
        strong = peaks[spectrum[peaks] >= float(np.max(spectrum)) * 0.06]
        if len(strong):
            voiced_values.append(float(band_frequencies[int(strong[0])]))
    voiced_f0 = np.asarray(voiced_values, dtype=np.float32)
    median_f0 = float(np.median(voiced_f0)) if len(voiced_f0) else 0.0
    p95_f0 = float(np.percentile(voiced_f0, 95)) if len(voiced_f0) else 0.0
    max_f0 = float(np.percentile(voiced_f0, 99.5)) if len(voiced_f0) else 0.0
    high_pitch = p95_f0 >= 700.0 or max_f0 >= 880.0
    high_frequency = high_ratio >= 0.075 or centroid >= 3600.0
    recommended_f0_max = float(
        np.clip(max(1100.0, p95_f0 * 1.35, max_f0 * 1.15), 1100.0, 1800.0)
    )
    return {
        "sample_rate": float(sample_rate),
        "spectral_centroid_hz": centroid,
        "high_band_ratio": float(high_ratio),
        "median_f0_hz": median_f0,
        "p95_f0_hz": p95_f0,
        "max_f0_hz": max_f0,
        "high_frequency": bool(high_frequency),
        "high_pitch": bool(high_pitch),
        "recommended_f0_max": recommended_f0_max,
    }


def _analyze_audio(source: Path) -> dict[str, float | bool]:
    import soundfile as sf

    audio, sample_rate = sf.read(str(source), always_2d=True, dtype="float32")
    return _audio_profile_array(audio, int(sample_rate))


def _restore_repair_high_band(
    dry_source: Path,
    repaired_source: Path,
    output: Path,
    *,
    stage: str,
) -> None:
    """Restore only guarded high-band transients after neural repair."""
    import librosa
    import numpy as np
    import soundfile as sf
    from scipy.signal import butter, sosfiltfilt

    dry, sample_rate = sf.read(str(dry_source), always_2d=True, dtype="float32")
    repaired, repaired_rate = sf.read(
        str(repaired_source), always_2d=True, dtype="float32"
    )
    if repaired_rate != sample_rate:
        repaired = np.column_stack(
            [
                librosa.resample(channel, orig_sr=repaired_rate, target_sr=sample_rate)
                for channel in repaired.T
            ]
        )
    frames = min(len(dry), len(repaired))
    channels = min(dry.shape[1], repaired.shape[1])
    dry = dry[:frames, :channels]
    repaired = repaired[:frames, :channels]
    if frames < 64 or sample_rate < 16000:
        _write_float_wav(output, repaired.T, sample_rate)
        return

    cutoff = min(6500.0, sample_rate * 0.38)
    sos = butter(4, cutoff, btype="highpass", fs=sample_rate, output="sos")
    dry_high = sosfiltfilt(sos, dry, axis=0)
    repaired_high = sosfiltfilt(sos, repaired, axis=0)
    activity, _ = _adaptive_activity_curve(dry, sample_rate)
    guard, stats = _adaptive_high_guard_curve(dry, dry_high, sample_rate)
    blend = 0.46 if stage == "separated" else 0.34
    control = (activity * guard * blend)[:, np.newaxis]
    restored = repaired + (dry_high - repaired_high) * control
    dry_peak = float(np.max(np.abs(dry))) if dry.size else 0.0
    restored_peak = float(np.max(np.abs(restored))) if restored.size else 0.0
    peak_limit = max(0.98, dry_peak * 1.02)
    if restored_peak > peak_limit:
        restored *= peak_limit / restored_peak
    _write_float_wav(output, restored.T, sample_rate)
    print(
        "  高频保护: "
        f"guard={stats['peak_guard']:.0%}, dry blend max={blend:.0%}",
        flush=True,
    )


def run_repair(
    source: Path,
    output: Path,
    stage: str = "separated",
    profile: dict[str, float | bool] | None = None,
) -> dict[str, float | bool]:
    """Repair separated/model vocals with DeepFilterNet3 and guarded HF recovery."""
    if not source.is_file():
        raise RuntimeError(f"输入文件不存在: {source}")
    normalized_stage = "output" if stage == "output" else "separated"
    output.parent.mkdir(parents=True, exist_ok=True)
    profile = profile or _analyze_audio(source)
    high_guard = bool(profile["high_frequency"] or profile["high_pitch"])
    base_attenuation = 6.0 if normalized_stage == "separated" else 4.5
    attenuation = base_attenuation - (1.5 if high_guard else 0.0)
    attenuation = max(2.5, attenuation)
    print(
        "[1/2] DeepFilterNet3 专用人声修复 "
        f"(stage={normalized_stage}, attenuation={attenuation:.1f}dB)",
        flush=True,
    )
    with tempfile.TemporaryDirectory(prefix="xb-vocal-repair-") as raw_temp:
        repaired = Path(raw_temp) / "deepfilter.wav"
        _deepfilter(source, repaired, atten_lim_db=attenuation)
        print("[2/2] 高频辅音与高音泛音保护", flush=True)
        _restore_repair_high_band(
            source,
            repaired,
            output,
            stage=normalized_stage,
        )
    return profile


def _target_timbre_peaks(
    audio: "np.ndarray",
    sample_rate: int,
) -> list[tuple[float, float]]:
    """在转换后的目标语音中寻找宽广且稳定的共振峰。"""
    import librosa
    import numpy as np
    from scipy.ndimage import gaussian_filter1d
    from scipy.signal import find_peaks

    data = np.asarray(audio, dtype=np.float32)
    mono = data.mean(axis=1) if data.ndim == 2 else data
    if len(mono) < max(512, sample_rate // 4) or sample_rate < 4000:
        return []

    n_fft = 4096 if sample_rate >= 16000 else 2048
    magnitude = np.abs(
        librosa.stft(mono, n_fft=n_fft, hop_length=n_fft, center=True)
    )
    frame_rms = np.sqrt(np.mean(magnitude ** 2, axis=0) + 1e-12)
    frame_db = 20.0 * np.log10(frame_rms + 1e-10)
    active = frame_db >= max(-55.0, float(np.percentile(frame_db, 90)) - 24.0)
    if int(active.sum()) < 4:
        return []

    active_magnitude = magnitude[:, active]
    if active_magnitude.shape[1] > 1600:
        positions = np.linspace(0, active_magnitude.shape[1] - 1, 1600).astype(int)
        active_magnitude = active_magnitude[:, positions]
    spectrum_db = 20.0 * np.log10(active_magnitude + 1e-7)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sample_rate)
    low, high = 250.0, min(4500.0, sample_rate / 2.0 * 0.92)
    vocal_bins = (freqs >= low) & (freqs <= high)
    if int(vocal_bins.sum()) < 20:
        return []

    # Remove frame level before the median so loud notes cannot dominate the identity
    # estimate. Interpolation to log frequency gives each octave equal importance.
    spectrum_db = spectrum_db - np.median(
        spectrum_db[vocal_bins], axis=0, keepdims=True
    )
    ltas = np.median(spectrum_db, axis=1)
    log_freqs = np.geomspace(low, high, 320)
    log_ltas = np.interp(log_freqs, freqs, ltas)
    profile = gaussian_filter1d(log_ltas, sigma=4.0, mode="nearest")
    baseline = gaussian_filter1d(log_ltas, sigma=30.0, mode="nearest")
    residual = profile - baseline
    candidates, properties = find_peaks(
        residual,
        prominence=0.35,
        distance=34,
    )
    if not len(candidates):
        return []

    ranked: list[tuple[float, float, float]] = []
    prominences = properties.get("prominences", np.zeros(len(candidates)))
    for position, prominence in zip(candidates, prominences):
        frequency = float(log_freqs[position])
        centre = (freqs >= frequency / (2.0 ** 0.07)) & (
            freqs <= frequency * (2.0 ** 0.07)
        )
        sides = (
            ((freqs >= frequency / (2.0 ** 0.32)) & (freqs < frequency / (2.0 ** 0.14)))
            | ((freqs > frequency * (2.0 ** 0.14)) & (freqs <= frequency * (2.0 ** 0.32)))
        )
        if not bool(centre.any()) or int(sides.sum()) < 2:
            continue
        contrast = np.median(spectrum_db[centre], axis=0) - np.median(
            spectrum_db[sides], axis=0
        )
        stability = float(np.mean(contrast >= 0.2))
        height = float(residual[position])
        if stability < 0.52 or height < 0.35:
            continue
        # 全量增强上限为 1.6 dB；默认 60% 时不超过约 1 dB，避免鼻音和箱体感。
        gain = float(np.clip((height + float(prominence)) * 0.22, 0.45, 1.6))
        score = height * (0.5 + stability) + float(prominence) * 0.35
        ranked.append((score, frequency, gain))

    selected = sorted(ranked, reverse=True)[:3]
    if len(selected) < 2:
        return []
    return sorted(
        [(frequency, gain) for _, frequency, gain in selected],
        key=lambda item: item[0],
    )


def _focus_target_timbre(source: Path, output: Path, strength: float) -> None:
    """温和地强化已转换目标语音中现有的声调"""
    try:
        import numpy as np
        import soundfile as sf
        from pedalboard import PeakFilter, Pedalboard
    except ImportError as exc:
        raise RuntimeError("librosa/scipy/pedalboard 未安装，请修复 vocal 增强环境") from exc

    amount = float(np.clip(strength, 0.0, 1.0))
    if amount <= 0.0:
        shutil.copy2(source, output)
        return
    audio, sample_rate = sf.read(str(source), always_2d=True)
    peaks = _target_timbre_peaks(audio, sample_rate)
    filters = [
        PeakFilter(
            cutoff_frequency_hz=frequency,
            gain_db=gain * amount,
            q=0.85,
        )
        for frequency, gain in peaks
        if gain * amount >= 0.12
    ]
    if not filters:
        shutil.copy2(source, output)
        print("  角色音色聚焦跳过（未找到足够稳定的宽带共振峰）", flush=True)
        return

    wet = Pedalboard(filters)(
        audio.T.astype(np.float32),
        sample_rate=sample_rate,
        reset=True,
    ).T
    activity, _ = _adaptive_activity_curve(audio, sample_rate)
    local_amount = np.where(
        activity >= 0.015,
        0.20 + 0.80 * activity,
        0.0,
    )
    processed = audio + (wet - audio) * local_amount[:, np.newaxis]
    _write_float_wav(output, processed.T, sample_rate)
    summary = ", ".join(
        f"{frequency:.0f}Hz/{gain * amount:+.2f}dB"
        for frequency, gain in peaks
    )
    active_amount = local_amount[activity >= 0.10]
    dynamic_summary = (
        f", dynamic={float(np.percentile(active_amount, 10)):.0%}-"
        f"{float(np.percentile(active_amount, 90)):.0%}"
        if len(active_amount)
        else ", dynamic=0%"
    )
    print(f"  目标角色共振峰: {summary}{dynamic_summary}", flush=True)


def _ai_eq(source: Path, output: Path, strength: float) -> None:
    """Analyze broad vocal bands and apply bounded corrective EQ."""
    try:
        import numpy as np
        import soundfile as sf
        from pedalboard import HighShelfFilter, LowShelfFilter, PeakFilter, Pedalboard
        from scipy.signal import welch
    except ImportError as exc:
        raise RuntimeError("AI EQ 依赖缺失，请修复 vocal 增强环境") from exc

    amount = float(np.clip(strength, 0.0, 1.0))
    if amount <= 0.0:
        shutil.copy2(source, output)
        return
    audio, sample_rate = sf.read(str(source), always_2d=True)
    mono = audio.mean(axis=1).astype(np.float32)
    if len(mono) < 512 or sample_rate < 8000:
        shutil.copy2(source, output)
        return

    nperseg = min(4096, len(mono))
    frequencies, power = welch(
        mono,
        fs=sample_rate,
        nperseg=nperseg,
        noverlap=nperseg // 2,
        average="median",
    )
    spectrum = 10.0 * np.log10(np.maximum(power, 1e-12))

    def band(low: float, high: float) -> float | None:
        mask = (frequencies >= low) & (
            frequencies <= min(high, sample_rate / 2.0 * 0.96)
        )
        return float(np.median(spectrum[mask])) if bool(mask.any()) else None

    core = band(700.0, 2200.0)
    body = band(160.0, 320.0)
    mud = band(320.0, 650.0)
    presence = band(2800.0, 5200.0)
    air = band(8000.0, 14000.0)
    if core is None:
        shutil.copy2(source, output)
        return

    def correction(measured: float | None, target: float, scale: float, limit: float) -> float:
        if measured is None:
            return 0.0
        relative = measured - core
        return float(np.clip((target - relative) * scale, -limit, limit) * amount)

    body_gain = correction(body, 3.0, 0.16, 1.20)
    mud_gain = correction(mud, 0.5, 0.14, 1.00)
    presence_gain = correction(presence, -3.0, 0.16, 1.40)
    air_gain = correction(air, -11.0, 0.10, 1.00)
    filters = []
    if abs(body_gain) >= 0.08:
        filters.append(LowShelfFilter(cutoff_frequency_hz=180.0, gain_db=body_gain, q=0.65))
    if abs(mud_gain) >= 0.08:
        filters.append(PeakFilter(cutoff_frequency_hz=430.0, gain_db=mud_gain, q=0.75))
    if abs(presence_gain) >= 0.08:
        filters.append(PeakFilter(cutoff_frequency_hz=3600.0, gain_db=presence_gain, q=0.70))
    if abs(air_gain) >= 0.08 and sample_rate / 2.0 > 9000.0:
        filters.append(HighShelfFilter(cutoff_frequency_hz=8500.0, gain_db=air_gain, q=0.60))
    if not filters:
        shutil.copy2(source, output)
        return

    wet = Pedalboard(filters)(
        audio.T.astype(np.float32),
        sample_rate=sample_rate,
        reset=True,
    ).T
    activity, _ = _adaptive_activity_curve(audio, sample_rate)
    local_amount = np.where(
        activity >= 0.015,
        0.24 + 0.76 * activity,
        0.0,
    )
    processed = audio + (wet - audio) * local_amount[:, np.newaxis]
    _write_float_wav(output, processed.T, sample_rate)
    active_amount = local_amount[activity >= 0.10]
    dynamic_min = float(np.percentile(active_amount, 10)) if len(active_amount) else 0.0
    dynamic_max = float(np.percentile(active_amount, 90)) if len(active_amount) else 0.0
    print(
        "  AI EQ(dB): "
        f"body={body_gain:+.2f}, mud={mud_gain:+.2f}, "
        f"presence={presence_gain:+.2f}, air={air_gain:+.2f}, "
        f"dynamic={dynamic_min:.0%}-{dynamic_max:.0%}",
        flush=True,
    )


def _ai_compressor(source: Path, output: Path, strength: float) -> None:
    """Set compression from active-vocal dynamics and restore perceived level."""
    try:
        import numpy as np
        import soundfile as sf
        from pedalboard import Compressor, Pedalboard
        from scipy.ndimage import uniform_filter1d
    except ImportError as exc:
        raise RuntimeError("AI Compressor 依赖缺失，请修复 vocal 增强环境") from exc

    amount = float(np.clip(strength, 0.0, 1.0))
    if amount <= 0.0:
        shutil.copy2(source, output)
        return
    audio, sample_rate = sf.read(str(source), always_2d=True)
    mono = audio.mean(axis=1)
    frame_size = max(64, int(sample_rate * 0.02))
    frame_count = len(mono) // frame_size
    if frame_count < 3:
        shutil.copy2(source, output)
        return
    framed = mono[: frame_count * frame_size].reshape(frame_count, frame_size)
    levels = 20.0 * np.log10(np.sqrt(np.mean(framed ** 2, axis=1) + 1e-12))
    active = levels >= max(-52.0, float(np.percentile(levels, 90)) - 30.0)
    active_levels = levels[active]
    if len(active_levels) < 3:
        shutil.copy2(source, output)
        return

    dynamic_range = float(np.percentile(active_levels, 90) - np.percentile(active_levels, 20))
    threshold = float(np.clip(np.percentile(active_levels, 68) - 1.5, -26.0, -11.0))
    ratio = 1.0 + amount * float(np.clip(0.75 + dynamic_range / 14.0, 1.0, 1.8))
    attack_ms = 38.0 - 14.0 * amount
    release_ms = 230.0 - 55.0 * amount
    wet = Pedalboard(
        [
            Compressor(
                threshold_db=threshold,
                ratio=ratio,
                attack_ms=attack_ms,
                release_ms=release_ms,
            )
        ]
    )(audio.T.astype(np.float32), sample_rate=sample_rate, reset=True).T

    activity_curve, _ = _adaptive_activity_curve(audio, sample_rate)
    local_power = uniform_filter1d(
        np.mean(audio * audio, axis=1),
        size=max(32, int(round(sample_rate * 0.020))),
        mode="nearest",
    )
    local_level = 10.0 * np.log10(np.maximum(local_power, 1e-12))
    above_threshold = np.clip((local_level - threshold + 3.0) / 12.0, 0.0, 1.0)
    local_amount = activity_curve * (0.20 + 0.80 * above_threshold)
    processed = audio + (wet - audio) * local_amount[:, np.newaxis]

    sample_active = np.repeat(active, frame_size)
    if len(sample_active) < len(audio):
        sample_active = np.pad(sample_active, (0, len(audio) - len(sample_active)), constant_values=False)
    sample_active = sample_active[: len(audio)]
    if bool(sample_active.any()):
        before = float(np.sqrt(np.mean(audio[sample_active] ** 2) + 1e-12))
        after = float(np.sqrt(np.mean(processed[sample_active] ** 2) + 1e-12))
        if after > 1e-7:
            compensation_db = float(
                np.clip(20.0 * np.log10(before / after) + 0.65 * amount, 0.0, 3.0)
            )
            processed *= 10.0 ** (compensation_db / 20.0)
        else:
            compensation_db = 0.0
    else:
        compensation_db = 0.0
    peak = float(np.max(np.abs(processed))) if processed.size else 0.0
    if peak > 0.99:
        processed *= 0.99 / peak
    _write_float_wav(output, processed.T, sample_rate)
    active_amount = local_amount[sample_active]
    dynamic_min = float(np.percentile(active_amount, 10)) if len(active_amount) else 0.0
    dynamic_max = float(np.percentile(active_amount, 90)) if len(active_amount) else 0.0
    print(
        f"  AI Compressor: threshold={threshold:.1f}dB, ratio={ratio:.2f}:1, "
        f"range={dynamic_range:.1f}dB, makeup={compensation_db:+.2f}dB, "
        f"dynamic={dynamic_min:.0%}-{dynamic_max:.0%}",
        flush=True,
    )


def _ai_exciter(source: Path, output: Path, strength: float) -> None:
    """Add a small, sibilance-aware high-band harmonic residual."""
    try:
        import numpy as np
        import soundfile as sf
        from scipy.signal import butter, sosfiltfilt
    except ImportError as exc:
        raise RuntimeError("AI Exciter 依赖缺失，请修复 vocal 增强环境") from exc

    amount = float(np.clip(strength, 0.0, 1.0))
    audio, sample_rate = sf.read(str(source), always_2d=True)
    if amount <= 0.0 or sample_rate < 12000 or len(audio) < 128:
        shutil.copy2(source, output)
        return
    cutoff = min(4200.0, sample_rate * 0.20)
    sos = butter(3, cutoff, btype="highpass", fs=sample_rate, output="sos")
    high = sosfiltfilt(sos, audio, axis=0)
    total_rms = float(np.sqrt(np.mean(audio ** 2) + 1e-12))
    high_rms = float(np.sqrt(np.mean(high ** 2) + 1e-12))
    if total_rms < 1e-7 or high_rms < 1e-8:
        shutil.copy2(source, output)
        return
    activity, _ = _adaptive_activity_curve(audio, sample_rate)
    high_guard, high_stats = _adaptive_high_guard_curve(audio, high, sample_rate)
    dynamic_amount = amount * activity * (1.0 - 0.88 * high_guard)
    drive = 1.8 + 1.2 * amount
    harmonic = np.tanh(high * drive) / drive - high
    harmonic = sosfiltfilt(sos, harmonic, axis=0)
    harmonic_rms = float(np.sqrt(np.mean(harmonic ** 2) + 1e-12))
    target_rms = high_rms * 0.16
    if harmonic_rms > 1e-9:
        harmonic *= min(2.0, target_rms / harmonic_rms)
    processed = audio + harmonic * dynamic_amount[:, np.newaxis]
    peak = float(np.max(np.abs(processed))) if processed.size else 0.0
    if peak > 0.99:
        processed *= 0.99 / peak
    _write_float_wav(output, processed.T, sample_rate)
    active_amount = dynamic_amount[activity >= 0.10]
    dynamic_min = float(np.percentile(active_amount, 10)) if len(active_amount) else 0.0
    dynamic_max = float(np.percentile(active_amount, 90)) if len(active_amount) else 0.0
    print(
        f"  AI Exciter: high={high_stats['median_high_ratio']:.2f}, "
        f"peak guard={high_stats['peak_guard']:.0%}, "
        f"dynamic={dynamic_min:.0%}-{dynamic_max:.0%}",
        flush=True,
    )


def _adaptive_stereo_width_curve(
    audio: "np.ndarray",
    sample_rate: int,
    strength: float,
) -> tuple["np.ndarray", dict[str, float]]:
    import numpy as np
    from scipy.signal import butter, sosfiltfilt

    data = np.asarray(audio, dtype=np.float64)
    if data.ndim == 1:
        data = data[:, np.newaxis]
    amount = float(np.clip(strength, 0.0, 1.0))
    activity, _ = _adaptive_activity_curve(data, sample_rate)
    if amount <= 0.0 or not len(data):
        return np.zeros(len(data), dtype=np.float64), {
            "median_high_ratio": 0.0,
            "peak_guard": 0.0,
        }
    mid = np.mean(data[:, : min(2, data.shape[1])], axis=1)
    if sample_rate >= 12000 and len(mid) >= 128:
        cutoff = min(4200.0, sample_rate * 0.20)
        high_sos = butter(3, cutoff, btype="highpass", fs=sample_rate, output="sos")
        high = sosfiltfilt(high_sos, mid)[:, np.newaxis]
        guard, stats = _adaptive_high_guard_curve(
            mid[:, np.newaxis],
            high,
            sample_rate,
        )
    else:
        guard = np.zeros(len(mid), dtype=np.float64)
        stats = {"median_high_ratio": 0.0, "peak_guard": 0.0}
    return amount * activity * (1.0 - 0.72 * guard), stats


def _stereo_image_array(
    audio: "np.ndarray",
    sample_rate: int,
    strength: float,
) -> "np.ndarray":
    """Create a high-band side signal while keeping the mono sum unchanged."""
    import numpy as np
    from scipy.signal import butter, sosfiltfilt

    data = np.asarray(audio, dtype=np.float64)
    if data.ndim == 1:
        data = data[:, np.newaxis]
    amount = float(np.clip(strength, 0.0, 1.0))
    if amount <= 0.0:
        return data
    width_curve, _ = _adaptive_stereo_width_curve(data, sample_rate, amount)
    if data.shape[1] >= 2:
        mid = (data[:, 0] + data[:, 1]) * 0.5
        original_side = (data[:, 0] - data[:, 1]) * 0.5
        side = original_side * (1.0 + 0.35 * width_curve)
    else:
        mid = data[:, 0]
        side = np.zeros_like(mid)
    if sample_rate >= 8000 and len(mid) >= 128:
        delay = max(1, int(round(sample_rate * 0.009)))
        delayed = np.pad(mid[:-delay], (delay, 0)) if delay < len(mid) else np.zeros_like(mid)
        decorrelated = mid - delayed
        sos = butter(2, 700.0, btype="highpass", fs=sample_rate, output="sos")
        decorrelated = sosfiltfilt(sos, decorrelated)
        mid_rms = float(np.sqrt(np.mean(mid ** 2) + 1e-12))
        decorrelated_rms = float(np.sqrt(np.mean(decorrelated ** 2) + 1e-12))
        if decorrelated_rms > 1e-8:
            decorrelated *= mid_rms / decorrelated_rms
            side += decorrelated * (0.055 * width_curve)
    stereo = np.column_stack((mid + side, mid - side))
    peak = float(np.max(np.abs(stereo))) if stereo.size else 0.0
    if peak > 0.99:
        stereo *= 0.99 / peak
    return stereo


def _stereo_image(source: Path, output: Path, strength: float) -> None:
    try:
        import numpy as np
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError("Stereo 处理依赖缺失，请修复 vocal 增强环境") from exc

    amount = max(0.0, min(1.0, float(strength)))
    if amount <= 0.0:
        shutil.copy2(source, output)
        return
    audio, sample_rate = sf.read(str(source), always_2d=True)
    processed = _stereo_image_array(audio, sample_rate, amount)
    _write_float_wav(output, processed.T, sample_rate)
    width_curve, high_stats = _adaptive_stereo_width_curve(audio, sample_rate, amount)
    active_width = width_curve[width_curve >= 0.01]
    dynamic_min = float(np.percentile(active_width, 10)) if len(active_width) else 0.0
    dynamic_max = float(np.percentile(active_width, 90)) if len(active_width) else 0.0
    print(
        f"  Stereo: dynamic width={dynamic_min:.0%}-{dynamic_max:.0%}, "
        f"peak guard={high_stats['peak_guard']:.0%}, mono-compatible mid/side",
        flush=True,
    )


def _pedalboard_basic(source: Path, output: Path) -> float:
    """Apply a track-adaptive light master and return its wet ceiling."""
    try:
        from pedalboard import (
            Compressor,
            HighpassFilter,
            HighShelfFilter,
            Limiter,
            LowShelfFilter,
            PeakFilter,
            Pedalboard,
        )
        from pedalboard.io import AudioFile
    except ImportError as exc:
        raise RuntimeError("Pedalboard 未安装，请修复 vocal 增强环境") from exc

    with AudioFile(str(source), "r") as audio_file:
        sample_rate = audio_file.samplerate
        audio = audio_file.read(audio_file.frames)

    profile = _adaptive_mastering_profile(audio.T, sample_rate, advanced=False)

    board = Pedalboard(
        [
            HighpassFilter(cutoff_frequency_hz=profile["highpass_hz"]),
            LowShelfFilter(
                cutoff_frequency_hz=170.0,
                gain_db=profile["body_db"],
            ),
            Compressor(
                threshold_db=profile["threshold_db"],
                ratio=profile["ratio"],
                attack_ms=profile["attack_ms"],
                release_ms=profile["release_ms"],
            ),
            PeakFilter(
                cutoff_frequency_hz=6500.0,
                gain_db=profile["harsh_db"],
                q=1.0,
            ),
            PeakFilter(
                cutoff_frequency_hz=3400.0,
                gain_db=profile["presence_db"],
                q=0.7,
            ),
            HighShelfFilter(
                cutoff_frequency_hz=8500.0,
                gain_db=profile["air_db"],
                q=0.6,
            ),
            Limiter(threshold_db=-1.0, release_ms=80.0),
        ]
    )
    processed = board(audio, sample_rate=sample_rate, reset=True)
    _write_float_wav(output, processed, sample_rate)
    if not output.is_file():
        raise RuntimeError("Pedalboard 未生成输出文件")
    print(
        "  动态基础母带: "
        f"HP={profile['highpass_hz']:.0f}Hz, body={profile['body_db']:+.2f}dB, "
        f"harsh={profile['harsh_db']:+.2f}dB, presence={profile['presence_db']:+.2f}dB, "
        f"air={profile['air_db']:+.2f}dB, threshold={profile['threshold_db']:.1f}dB, "
        f"ratio={profile['ratio']:.2f}:1, wet max={profile['wet_mix']:.0%}",
        flush=True,
    )
    return profile["wet_mix"]


def _silence_vocalfloor(audio: "np.ndarray", sample_rate: int) -> "np.ndarray":
    """轻柔地延长停顿，不切断呼吸、辅音或混响尾。
        之前的二进制-30 dB检测器将静音材料乘以0.0002，
        并在开启和关闭时使用相同的慢时间常数。
        这消除了低级别的人类线索，并逐渐淡入每个新音节。
        该扩展器采用16 dB的软膝点，最大减小量为6 dB，
        桥接句内短停顿，在活动前打开，并通过自然尾部保持稳定。
    """
    import numpy as np

    was_mono = audio.ndim == 1
    working = audio[np.newaxis, :] if was_mono else np.asarray(audio)
    _, total = working.shape
    win = max(1, int(sample_rate * 0.02))
    n_windows = int(np.ceil(total / win))
    if n_windows < 2 or total == 0:
        return audio

    rms_per_win = np.zeros(n_windows, dtype=np.float64)
    for i in range(n_windows):
        seg = working[:, i * win : min(total, (i + 1) * win)]
        rms_per_win[i] = float(np.sqrt(np.mean(seg ** 2)))

    db_per_win = 20.0 * np.log10(rms_per_win + 1e-10)
    # Quiet files must not be mistaken for noise. For normalised renders this remains -32 dB.
    active_level = float(np.percentile(db_per_win, 95))
    knee_top_db = min(-32.0, active_level - 12.0)
    knee_bottom_db = knee_top_db - 16.0
    depth = np.clip(
        (knee_top_db - db_per_win) / (knee_top_db - knee_bottom_db),
        0.0,
        1.0,
    )
    target_gain = 10.0 ** (-(6.0 * depth) / 20.0)

    active_mask = db_per_win >= knee_top_db
    # Bridge natural intra-phrase gaps. Closing the expander for a 200-500 ms rest is
    # perceived as an artificial breath or hard edit even when the waveform is clean.
    max_bridge = max(1, int(round(0.50 * sample_rate / win)))
    inactive = np.flatnonzero(~active_mask)
    if len(inactive):
        run_starts = np.r_[0, np.flatnonzero(np.diff(inactive) > 1) + 1]
        run_ends = np.r_[run_starts[1:], len(inactive)]
        for run_start, run_end in zip(run_starts, run_ends):
            run = inactive[run_start:run_end]
            if (
                len(run) <= max_bridge
                and run[0] > 0
                and run[-1] < n_windows - 1
                and active_mask[run[0] - 1]
                and active_mask[run[-1] + 1]
            ):
                active_mask[run] = True

    # Open early and hold through consonants, breaths and note releases.
    active = np.flatnonzero(active_mask)
    lookahead = max(1, int(round(0.08 * sample_rate / win)))
    hold = max(1, int(round(0.32 * sample_rate / win)))
    for index in active:
        target_gain[max(0, index - lookahead) : min(n_windows, index + hold + 1)] = 1.0

    frame_seconds = win / sample_rate
    attack_alpha = float(np.exp(-frame_seconds / 0.008))
    release_alpha = float(np.exp(-frame_seconds / 0.38))
    smoothed = np.empty_like(target_gain)
    smoothed[0] = target_gain[0]
    for i in range(1, n_windows):
        alpha = attack_alpha if target_gain[i] > smoothed[i - 1] else release_alpha
        smoothed[i] = alpha * smoothed[i - 1] + (1 - alpha) * target_gain[i]

    gain = np.interp(
        np.arange(total),
        np.minimum(total - 1, np.arange(n_windows) * win + win // 2),
        smoothed,
    )
    processed = working * gain[np.newaxis, :]
    return processed[0] if was_mono else processed


def _pedalboard_mastering(source: Path, output: Path) -> float:
    """Apply an analyzed advanced master and return its wet ceiling."""
    try:
        from pedalboard import (
            Compressor,
            HighpassFilter,
            HighShelfFilter,
            Limiter,
            LowShelfFilter,
            PeakFilter,
            Pedalboard,
        )
        from pedalboard.io import AudioFile
    except ImportError as exc:
        raise RuntimeError("Pedalboard 未安装，请修复 vocal 增强环境") from exc

    with AudioFile(str(source), "r") as audio_file:
        sample_rate = audio_file.samplerate
        audio = audio_file.read(audio_file.frames)

    profile = _adaptive_mastering_profile(audio.T, sample_rate, advanced=True)

    board = Pedalboard(
        [
            HighpassFilter(cutoff_frequency_hz=profile["highpass_hz"]),
            LowShelfFilter(
                cutoff_frequency_hz=170.0,
                gain_db=profile["body_db"],
                q=0.65,
            ),
            PeakFilter(
                cutoff_frequency_hz=6500.0,
                gain_db=profile["harsh_db"],
                q=1.1,
            ),
            Compressor(
                threshold_db=profile["threshold_db"],
                ratio=profile["ratio"],
                attack_ms=profile["attack_ms"],
                release_ms=profile["release_ms"],
            ),
            PeakFilter(
                cutoff_frequency_hz=3500.0,
                gain_db=profile["presence_db"],
                q=0.7,
            ),
            HighShelfFilter(
                cutoff_frequency_hz=9000.0,
                gain_db=profile["air_db"],
                q=0.6,
            ),
            Limiter(threshold_db=-1.0, release_ms=100.0),
        ]
    )
    processed = board(audio, sample_rate=sample_rate, reset=True)
    _write_float_wav(output, processed, sample_rate)
    if not output.is_file():
        raise RuntimeError("Pedalboard 未生成输出文件")
    print(
        "  动态高级母带: "
        f"HP={profile['highpass_hz']:.0f}Hz, body={profile['body_db']:+.2f}dB, "
        f"harsh={profile['harsh_db']:+.2f}dB, presence={profile['presence_db']:+.2f}dB, "
        f"air={profile['air_db']:+.2f}dB, threshold={profile['threshold_db']:.1f}dB, "
        f"ratio={profile['ratio']:.2f}:1, wet max={profile['wet_mix']:.0%}",
        flush=True,
    )
    return profile["wet_mix"]


def run(
    source: Path,
    output: Path,
    level: str,
    device: str,
    reference: Path | None = None,
    timbre_focus: float = 0.60,
    ai_eq: float = 0.55,
    ai_compressor: float = 0.45,
    ai_exciter: float = 0.25,
    stereo_width: float = 0.30,
    loudness_envelope: float = 0.58,
    skip_deepfilter: bool = False,
) -> None:
    if not source.is_file():
        raise RuntimeError(f"输入文件不存在: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="xb-vocal-enhance-") as raw_temp:
        temp = Path(raw_temp)
        silenced = temp / "00_silenced.wav"
        print("[1/12] 自然停顿扩展（保留起音、呼吸与尾音）", flush=True)
        _silence_vocalfloor_file(source, silenced)
        current = silenced

        use_reference = (
            level == "advanced" and reference is not None and reference.is_file()
        )
        if use_reference:
            matched = temp / "01_matched.wav"
            print(f"[2/12] 宽带频谱参考（{reference.name}）", flush=True)
            _match_reference(current, reference, matched)
            current = matched
        else:
            print("[2/12] 跳过宽带频谱参考（仅高级模式且需要原始人声）", flush=True)

        if skip_deepfilter:
            print("[3/12] 已完成专用修复，跳过重复 DeepFilterNet", flush=True)
        else:
            filtered = temp / "02_deepfilter.wav"
            print("[3/12] DeepFilterNet 原生采样率限量降噪", flush=True)
            _deepfilter(current, filtered)
            current = filtered

        if use_reference:
            detailed = temp / "03_human_detail.wav"
            print("[4/12] 真实辅音与呼吸细节保护", flush=True)
            _restore_reference_detail(current, reference, detailed)
            current = detailed
        else:
            print("[4/12] 跳过真实细节保护", flush=True)

        if level == "advanced":
            print("[5/12] 动态自然度母带（按素材分析 + 去金属感）", flush=True)
            dsp_output = temp / "04_mastering.wav"
            wet_mix = _pedalboard_mastering(current, dsp_output)
            if wet_mix is None:
                wet_mix = 0.82
        else:
            print("[5/12] 动态基础轻母带（按素材分析）", flush=True)
            dsp_output = temp / "04_basic.wav"
            wet_mix = _pedalboard_basic(current, dsp_output)
            if wet_mix is None:
                wet_mix = 0.68

        natural = temp / "05_natural_mix.wav"
        print(f"[6/12] 动态并行自然度混合（wet 上限={wet_mix:.0%}）", flush=True)
        _parallel_mix(silenced, dsp_output, natural, wet_mix)

        focused = temp / "06_timbre.wav"
        print(f"[7/12] AI 角色共振峰（{float(timbre_focus):.0%}）", flush=True)
        _focus_target_timbre(natural, focused, timbre_focus)

        equalized = temp / "07_ai_eq.wav"
        print(f"[8/12] AI EQ（{float(ai_eq):.0%}）", flush=True)
        _ai_eq(focused, equalized, ai_eq)

        compressed = temp / "08_ai_compressor.wav"
        print(f"[9/12] AI Compressor（{float(ai_compressor):.0%}）", flush=True)
        _ai_compressor(equalized, compressed, ai_compressor)

        excited = temp / "09_ai_exciter.wav"
        print(f"[10/12] AI Exciter（{float(ai_exciter):.0%}）", flush=True)
        _ai_exciter(compressed, excited, ai_exciter)

        stereo = temp / "10_stereo.wav"
        print(f"[11/12] Stereo（{float(stereo_width):.0%}）", flush=True)
        _stereo_image(excited, stereo, stereo_width)

        print(
            f"[12/12] AI 响度包络（{float(loudness_envelope):.0%}）",
            flush=True,
        )
        _ai_loudness_envelope(silenced, stereo, output, loudness_envelope)


def main() -> int:
    parser = argparse.ArgumentParser(description="XB-SVCB AI 歌声增强 worker")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="")
    parser.add_argument(
        "--mode", choices=("enhance", "repair", "analyze"), default="enhance"
    )
    parser.add_argument(
        "--repair-stage", choices=("separated", "output"), default="separated"
    )
    parser.add_argument("--analysis-output", default="")
    parser.add_argument("--analysis-json", default="")
    parser.add_argument("--skip-deepfilter", action="store_true")
    parser.add_argument("--level", choices=("basic", "advanced"), default="basic")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--reference", default=None, help="原始人声参考文件路径（用于频谱包络匹配）")
    parser.add_argument("--timbre-focus", type=float, default=0.60)
    parser.add_argument("--ai-eq", type=float, default=0.55)
    parser.add_argument("--ai-compressor", type=float, default=0.45)
    parser.add_argument("--ai-exciter", type=float, default=0.25)
    parser.add_argument("--stereo-width", type=float, default=0.30)
    parser.add_argument("--loudness-envelope", type=float, default=0.58)
    args = parser.parse_args()
    try:
        source = Path(args.input)
        if args.mode == "analyze":
            if not args.analysis_output:
                raise RuntimeError("分析模式缺少 --analysis-output")
            analysis_output = Path(args.analysis_output)
            analysis_output.parent.mkdir(parents=True, exist_ok=True)
            profile = _analyze_audio(source)
            analysis_output.write_text(
                json.dumps(profile, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"VOCAL_ANALYZE_OK {analysis_output}", flush=True)
            return 0
        if not args.output:
            raise RuntimeError(f"{args.mode} 模式缺少 --output")
        output = Path(args.output)
        output.unlink(missing_ok=True)
        if args.mode == "repair":
            supplied_profile = None
            if args.analysis_json:
                decoded_profile = json.loads(args.analysis_json)
                if isinstance(decoded_profile, dict):
                    supplied_profile = decoded_profile
            profile = run_repair(
                source,
                output,
                args.repair_stage,
                supplied_profile,
            )
            print(
                "VOCAL_REPAIR_PROFILE "
                + json.dumps(profile, ensure_ascii=False, separators=(",", ":")),
                flush=True,
            )
            print(f"VOCAL_REPAIR_OK {output}", flush=True)
            return 0
        reference = Path(args.reference) if args.reference else None
        run(
            source,
            output,
            args.level,
            args.device,
            reference,
            args.timbre_focus,
            args.ai_eq,
            args.ai_compressor,
            args.ai_exciter,
            args.stereo_width,
            args.loudness_envelope,
            args.skip_deepfilter,
        )
        print(f"VOCAL_ENHANCE_OK {output}", flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 - worker must return a concise boundary error
        print(f"VOCAL_ENHANCE_ERR {exc}", flush=True)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
