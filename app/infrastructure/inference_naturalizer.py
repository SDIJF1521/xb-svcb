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


def _keep_short_regions(mask: Any, max_frames: int) -> Any:
    """Keep only bounded true runs so sustained tonal content is untouched."""
    import numpy as np

    source = np.asarray(mask, dtype=bool)
    kept = np.zeros(len(source), dtype=bool)
    index = 0
    max_frames = max(1, int(max_frames))
    while index < len(source):
        if not source[index]:
            index += 1
            continue
        start = index
        while index < len(source) and source[index]:
            index += 1
        if index - start <= max_frames:
            kept[start:index] = True
    return kept


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


def _source_guided_high_band_repair(
    source: Any,
    output: Any,
    sample_rate: int,
    source_rate: int,
    engine: str,
) -> tuple[Any, dict[str, float]]:
    """Attenuate only short HF bursts unsupported by the input vocal.

    The same conservative detector is used for every offline model engine. It
    does not copy source samples: the source only supplies a broad
    high-band-to-body envelope used to identify model-generated bursts.
    """
    import numpy as np

    data = np.asarray(output, dtype=np.float32)
    if (
        engine not in _PROFILES
        or sample_rate < 16000
        or len(data) < 256
        or not len(source)
    ):
        return data, {
            "guarded_frames": 0.0,
            "reduction_db": 0.0,
            "transient_guarded_frames": 0.0,
            "transient_reduction_db": 0.0,
        }
    try:
        from scipy.ndimage import gaussian_filter1d, uniform_filter1d
        from scipy.signal import butter, sosfiltfilt
    except ImportError:
        return data, {
            "guarded_frames": 0.0,
            "reduction_db": 0.0,
            "transient_guarded_frames": 0.0,
            "transient_reduction_db": 0.0,
        }

    source_mono = _source_on_output_timeline(source, len(data))
    output_mono = np.mean(data, axis=1, dtype=np.float64)
    nyquist = sample_rate * 0.5
    high_cutoff = min(5600.0, nyquist * 0.72)
    body_high = min(4800.0, nyquist * 0.58)
    if body_high <= 700.0:
        return data, {
            "guarded_frames": 0.0,
            "reduction_db": 0.0,
            "transient_guarded_frames": 0.0,
            "transient_reduction_db": 0.0,
        }
    high_sos = butter(4, high_cutoff, btype="highpass", fs=sample_rate, output="sos")
    scrape_sos = butter(
        4,
        [3500.0, high_cutoff],
        btype="bandpass",
        fs=sample_rate,
        output="sos",
    )
    body_sos = butter(
        4,
        [180.0, body_high],
        btype="bandpass",
        fs=sample_rate,
        output="sos",
    )
    source_high = sosfiltfilt(high_sos, source_mono)
    output_high = sosfiltfilt(high_sos, output_mono)
    source_scrape = sosfiltfilt(scrape_sos, source_mono)
    output_scrape = sosfiltfilt(scrape_sos, output_mono)
    source_body = sosfiltfilt(body_sos, source_mono)
    output_body = sosfiltfilt(body_sos, output_mono)
    frame_size = max(64, int(round(sample_rate * 0.020)))
    source_high_rms = _frame_rms(source_high, frame_size)
    output_high_rms = _frame_rms(output_high, frame_size)
    source_scrape_rms = _frame_rms(source_scrape, frame_size)
    output_scrape_rms = _frame_rms(output_scrape, frame_size)
    source_body_rms = _frame_rms(source_body, frame_size)
    output_body_rms = _frame_rms(output_body, frame_size)
    frames = min(
        len(source_high_rms),
        len(output_high_rms),
        len(source_scrape_rms),
        len(output_scrape_rms),
        len(source_body_rms),
        len(output_body_rms),
    )
    if frames < 3:
        return data, {
            "guarded_frames": 0.0,
            "reduction_db": 0.0,
            "transient_guarded_frames": 0.0,
            "transient_reduction_db": 0.0,
        }
    source_high_rms = source_high_rms[:frames]
    output_high_rms = output_high_rms[:frames]
    source_scrape_rms = source_scrape_rms[:frames]
    output_scrape_rms = output_scrape_rms[:frames]
    source_body_rms = source_body_rms[:frames]
    output_body_rms = output_body_rms[:frames]
    source_ratio = 20.0 * np.log10(
        (source_high_rms + 1e-7) / (source_body_rms + 1e-7)
    )
    output_ratio = 20.0 * np.log10(
        (output_high_rms + 1e-7) / (output_body_rms + 1e-7)
    )
    excess = output_ratio - source_ratio
    source_active = source_body_rms >= max(
        float(np.percentile(source_body_rms, 65)) * 0.03,
        1e-5,
    )
    output_high_db = 20.0 * np.log10(output_high_rms + 1e-7)
    suspicious = source_active & (output_high_db > -58.0) & (excess > 10.0)
    anomaly = np.clip((excess - 10.0) / 8.0, 0.0, 1.0)
    anomaly *= np.clip((output_high_db + 58.0) / 12.0, 0.0, 1.0)
    anomaly[~suspicious] = 0.0
    anomaly = gaussian_filter1d(anomaly, sigma=1.0, mode="nearest")

    # A model can produce a very short, sharp HF scrape while its average
    # high/body ratio remains close to the source.  Compare the local attack
    # against a 200 ms baseline so sustained high notes are left untouched.
    local_window = max(5, int(round(0.220 * sample_rate / frame_size)))
    if local_window % 2 == 0:
        local_window += 1
    source_high_db = 20.0 * np.log10(source_high_rms + 1e-7)
    source_local_db = uniform_filter1d(
        source_high_db,
        size=local_window,
        mode="nearest",
    )
    output_local_db = uniform_filter1d(
        output_high_db,
        size=local_window,
        mode="nearest",
    )
    source_attack = source_high_db - source_local_db
    output_attack = output_high_db - output_local_db
    attack_mismatch = output_attack - source_attack
    absolute_high_excess = output_high_db - source_high_db
    source_scrape_db = 20.0 * np.log10(source_scrape_rms + 1e-7)
    output_scrape_db = 20.0 * np.log10(output_scrape_rms + 1e-7)
    scrape_excess = output_scrape_db - source_scrape_db
    attack_seed = (
        source_active
        & (output_high_db > -52.0)
        & (output_attack > 6.0)
        & (attack_mismatch > 8.0)
        & (absolute_high_excess > 3.0)
    )
    # A supported consonant can still be rendered much too bright.  Keep this
    # fallback deliberately strict and shorter than a sung syllable.
    bright_sibilant_seed = _keep_short_regions(
        source_active
        & (output_high_db > -50.0)
        & (source_ratio > -15.0)
        & (output_ratio > -15.0)
        & (absolute_high_excess > 11.0),
        max_frames=max(2, int(round(0.100 * sample_rate / frame_size))),
    )
    # Some short scrapes raise the high/body ratio without a large absolute
    # HF jump.  Treat these as a separate, gentler candidate so a brief body
    # dip cannot trigger the stronger unsupported-HF guard across a phrase.
    ratio_sibilant_seed = _keep_short_regions(
        source_active
        & (output_high_db > -50.0)
        & (source_ratio > -20.0)
        & (output_ratio > -12.0)
        & (excess > 8.0),
        max_frames=max(2, int(round(0.120 * sample_rate / frame_size))),
    )

    # Some model renders produce a short, record-scratch-like burst in the
    # upper presence band (3.5-5.6 kHz) instead of above the high-band
    # crossover. Compare its local attack with the source before attenuating:
    # a supported consonant rises in both signals, while a generated scrape
    # rises only in the render. Keep this path short and conservative so it
    # cannot flatten a sustained bright vowel.
    scrape_local_window = max(5, int(round(0.180 * sample_rate / frame_size)))
    if scrape_local_window % 2 == 0:
        scrape_local_window += 1
    source_scrape_local_db = uniform_filter1d(
        source_scrape_db,
        size=scrape_local_window,
        mode="nearest",
    )
    output_scrape_local_db = uniform_filter1d(
        output_scrape_db,
        size=scrape_local_window,
        mode="nearest",
    )
    source_scrape_attack = source_scrape_db - source_scrape_local_db
    output_scrape_attack = output_scrape_db - output_scrape_local_db
    scrape_attack_mismatch = output_scrape_attack - source_scrape_attack
    scrape_transient_seed = _keep_short_regions(
        source_active
        & (output_scrape_db > -26.0)
        & (scrape_excess > 4.5)
        & (output_scrape_attack > 4.5)
        & (scrape_attack_mismatch > 2.0),
        max_frames=max(2, int(round(0.120 * sample_rate / frame_size))),
    )

    # A whistle is often narrow-band: it has a low spectral flatness and one
    # dominant HF bin, even when its total high-band energy is not much louder
    # than the dry vocal.  Detect only short attacks unsupported by the source.
    # FFT frames are intentionally the same 20 ms grid as the envelope curves.
    fft_size = 1 << int(np.ceil(np.log2(min(frame_size, 2048))))

    def _hf_shape(signal: "np.ndarray") -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        frame_count = int(np.ceil(len(signal) / frame_size))
        padded = np.pad(signal, (0, frame_count * frame_size - len(signal)))
        frames_fft = padded.reshape(frame_count, frame_size)
        if frames_fft.shape[1] < fft_size:
            frames_fft = np.pad(
                frames_fft,
                ((0, 0), (0, fft_size - frames_fft.shape[1])),
            )
        else:
            frames_fft = frames_fft[:, :fft_size]
        spectrum = np.abs(
            np.fft.rfft(frames_fft * np.hanning(fft_size), axis=1)
        ) ** 2
        frequencies = np.fft.rfftfreq(fft_size, 1.0 / sample_rate)
        mask = (frequencies >= high_cutoff) & (
            frequencies <= min(16000.0, nyquist * 0.96)
        )
        high_spectrum = np.maximum(spectrum[:, mask], 1e-14)
        high_power = np.sum(high_spectrum, axis=1)
        flatness = np.exp(np.mean(np.log(high_spectrum), axis=1)) / np.maximum(
            np.mean(high_spectrum, axis=1), 1e-14
        )
        peak_share = np.max(high_spectrum, axis=1) / np.maximum(
            high_power, 1e-14
        )
        high_db = 10.0 * np.log10(high_power + 1e-20)
        return high_db, flatness, peak_share

    source_fft_db, source_flatness, source_peak_share = _hf_shape(source_mono)
    output_fft_db, output_flatness, output_peak_share = _hf_shape(output_mono)
    fft_frames = min(
        frames,
        len(source_fft_db),
        len(output_fft_db),
        len(source_flatness),
        len(output_flatness),
        len(source_peak_share),
        len(output_peak_share),
    )
    source_fft_db = source_fft_db[:fft_frames]
    output_fft_db = output_fft_db[:fft_frames]
    source_flatness = source_flatness[:fft_frames]
    output_flatness = output_flatness[:fft_frames]
    source_peak_share = source_peak_share[:fft_frames]
    output_peak_share = output_peak_share[:fft_frames]
    if fft_frames < frames:
        source_fft_db = np.pad(source_fft_db, (0, frames - fft_frames), mode="edge")
        output_fft_db = np.pad(output_fft_db, (0, frames - fft_frames), mode="edge")
        source_flatness = np.pad(source_flatness, (0, frames - fft_frames), mode="edge")
        output_flatness = np.pad(output_flatness, (0, frames - fft_frames), mode="edge")
        source_peak_share = np.pad(source_peak_share, (0, frames - fft_frames), mode="edge")
        output_peak_share = np.pad(output_peak_share, (0, frames - fft_frames), mode="edge")
    whistle_seed = _keep_short_regions(
        source_active
        & (output_high_db > -52.0)
        & (absolute_high_excess > 3.0)
        & (output_attack > 5.0)
        & ((output_fft_db - source_fft_db) > 2.5)
        & (output_flatness < 0.16)
        & (output_peak_share > np.maximum(0.07, source_peak_share * 1.35)),
        max_frames=max(2, int(round(0.160 * sample_rate / frame_size))),
    )
    # Keep the seed strict, then include the quieter shoulders of that same
    # burst.  Without this step only the loudest 20 ms is reduced and the
    # remaining 40-100 ms is still heard as a scrape.
    transient_support = (
        source_active
        & (output_high_db > -55.0)
        & (absolute_high_excess > 5.0)
        & ((excess > 4.0) | (attack_mismatch > 2.0))
    )
    cluster_radius = max(1, int(round(0.040 * sample_rate / frame_size)))
    attack_cluster = _protect_region(
        attack_seed,
        cluster_radius,
        cluster_radius,
    ) & transient_support
    attack_cluster, _ = _bridge_short_gaps(attack_cluster, 1)
    transient_suspicious = (
        attack_cluster
        | bright_sibilant_seed
        | ratio_sibilant_seed
        | scrape_transient_seed
        | whistle_seed
    )
    context_confidence = np.maximum(
        np.clip((excess - 2.5) / 7.5, 0.0, 1.0),
        np.clip((attack_mismatch - 1.5) / 6.5, 0.0, 1.0),
    )
    transient_reduction_db = np.clip(absolute_high_excess - 4.0, 0.0, 7.0)
    transient_reduction_db *= 0.35 + 0.65 * context_confidence
    transient_reduction_db *= attack_cluster | bright_sibilant_seed
    bright_sibilant_reduction_db = np.clip(
        absolute_high_excess - 7.0,
        0.0,
        4.0,
    )
    ratio_sibilant_reduction_db = np.clip(
        absolute_high_excess - 2.5,
        0.0,
        3.0,
    )
    ratio_sibilant_reduction_db *= 0.35 + 0.65 * np.clip(
        (excess - 6.0) / 5.0,
        0.0,
        1.0,
    )
    scrape_transient_reduction_db = np.clip(
        scrape_excess - 2.5,
        0.0,
        3.5,
    )
    scrape_transient_reduction_db *= 0.35 + 0.65 * np.clip(
        (scrape_attack_mismatch - 1.5) / 4.0,
        0.0,
        1.0,
    )
    whistle_reduction_db = np.clip(absolute_high_excess - 2.0, 0.0, 4.0)
    whistle_reduction_db *= whistle_seed
    transient_reduction_db = np.maximum(
        transient_reduction_db,
        bright_sibilant_reduction_db * bright_sibilant_seed,
    )
    transient_reduction_db = np.maximum(
        transient_reduction_db,
        ratio_sibilant_reduction_db * ratio_sibilant_seed,
    )
    transient_reduction_db = np.maximum(
        transient_reduction_db,
        scrape_transient_reduction_db * scrape_transient_seed,
    )
    transient_reduction_db = np.maximum(
        transient_reduction_db,
        whistle_reduction_db,
    )
    transient_reduction_db[~transient_suspicious] = 0.0
    transient_gain = np.power(10.0, -transient_reduction_db / 20.0)
    transient_gain = gaussian_filter1d(
        transient_gain,
        sigma=0.7,
        mode="nearest",
    )
    # Do not stack both detectors.  The stronger of the hard unsupported-HF
    # guard and short-cluster guard is enough for a given frame.
    frame_gain = np.minimum(1.0 - 0.85 * anomaly, transient_gain)
    frame_gain = np.clip(frame_gain, 0.15, 1.0)
    centres = np.minimum(
        len(data) - 1,
        np.arange(frames, dtype=np.float64) * frame_size + frame_size * 0.5,
    )
    gain = np.interp(
        np.arange(len(data), dtype=np.float64),
        centres,
        frame_gain,
        left=float(frame_gain[0]),
        right=float(frame_gain[-1]),
    )
    repaired = data.astype(np.float64, copy=True)
    high_channels = sosfiltfilt(high_sos, repaired, axis=0)
    repaired = repaired - high_channels + high_channels * gain[:, np.newaxis]
    # The audible peak of a scrape can sit just below the HF crossover.  Only
    # trim 3.5-5.6 kHz when that band also exceeds the source during one of the
    # short anomaly regions above.
    scrape_reduction_db = np.clip(scrape_excess - 2.0, 0.0, 3.0)
    scrape_reduction_db *= transient_suspicious
    scrape_gain_frames = np.power(10.0, -scrape_reduction_db / 20.0)
    scrape_gain_frames = gaussian_filter1d(
        scrape_gain_frames,
        sigma=0.7,
        mode="nearest",
    )
    scrape_gain = np.interp(
        np.arange(len(data), dtype=np.float64),
        centres,
        scrape_gain_frames,
        left=float(scrape_gain_frames[0]),
        right=float(scrape_gain_frames[-1]),
    )
    scrape_channels = sosfiltfilt(scrape_sos, repaired, axis=0)
    repaired = (
        repaired
        - scrape_channels
        + scrape_channels * scrape_gain[:, np.newaxis]
    )
    peak = float(np.max(np.abs(repaired))) if repaired.size else 0.0
    if peak > 0.999:
        repaired *= 0.999 / peak
    guarded = float(np.count_nonzero(suspicious))
    reduction = float(np.min(20.0 * np.log10(frame_gain[suspicious] + 1e-7))) if guarded else 0.0
    return repaired.astype(np.float32), {
        "guarded_frames": guarded,
        "reduction_db": reduction,
        "transient_guarded_frames": float(np.count_nonzero(transient_suspicious)),
        "transient_reduction_db": (
            float(np.min(20.0 * np.log10(frame_gain[transient_suspicious] + 1e-7)))
            if np.any(transient_suspicious)
            else 0.0
        ),
    }


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

    output, high_band_stats = _source_guided_high_band_repair(
        source,
        output,
        sample_rate,
        source_rate,
        engine,
    )

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
        "high_band_guarded_frames": high_band_stats["guarded_frames"],
        "high_band_reduction_db": high_band_stats["reduction_db"],
        "high_band_transient_guarded_frames": high_band_stats.get(
            "transient_guarded_frames", 0.0
        ),
        "high_band_transient_reduction_db": high_band_stats.get(
            "transient_reduction_db", 0.0
        ),
        "duration_adjustment_ms": duration_adjustment_ms,
    }


def format_naturalizer_stats(stats: dict[str, float]) -> str:
    return (
        f"short_gaps={int(stats['short_gaps'])} "
        f"silence=-{stats['silence_reduction_db']:.0f}dB "
        f"dynamics={stats['dynamic_min_db']:+.2f}..{stats['dynamic_max_db']:+.2f}dB "
        f"exact_silence={stats['exact_silence_seconds']:.2f}s "
        f"hf_guard={int(stats.get('high_band_guarded_frames', 0.0))}frames "
        f"hf_transient={int(stats.get('high_band_transient_guarded_frames', 0.0))}frames "
        f"duration={stats['duration_adjustment_ms']:+.1f}ms "
        f"peak={stats['peak']:.4f}"
    )
