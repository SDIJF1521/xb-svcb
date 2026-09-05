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


def _quality_features(audio: "np.ndarray", sample_rate: int) -> dict[str, object]:
    """Extract inexpensive frame metrics used to reject harmful post-processing.

    The model render is the authority for timing and dynamics.  Enhancement stages may
    improve it, but must not create dropouts, loud noise during pauses, or a new
    high-frequency whistle.  Features are deliberately frame based so a short bad
    syllable is not hidden by a whole-song RMS/FFT average.
    """
    import numpy as np

    data = np.asarray(audio, dtype=np.float64)
    if data.ndim == 1:
        data = data[:, np.newaxis]
    mono = np.mean(data, axis=1) if len(data) else np.zeros(0, dtype=np.float64)
    if not len(mono):
        return {
            "sample_rate": int(sample_rate),
            "frames": 0,
            "peak": 0.0,
            "frame_rms": np.zeros(0, dtype=np.float64),
            "high_ratio": np.zeros(0, dtype=np.float64),
        }

    frame_size = max(256, int(round(sample_rate * 0.020)))
    frame_count = int(np.ceil(len(mono) / frame_size))
    padded = np.pad(mono, (0, frame_count * frame_size - len(mono)))
    frames = padded.reshape(frame_count, frame_size)
    frame_rms = np.sqrt(np.mean(frames * frames, axis=1) + 1e-12)

    # A small FFT is sufficient for detecting an added whistle or broadband hiss.
    fft_size = 1 << max(8, min(11, int(np.ceil(np.log2(min(frame_size, 2048))))))
    fft_frames = frames[:, :fft_size]
    if fft_frames.shape[1] < fft_size:
        fft_frames = np.pad(fft_frames, ((0, 0), (0, fft_size - fft_frames.shape[1])))
    window = np.hanning(fft_size)
    power = np.abs(np.fft.rfft(fft_frames * window[np.newaxis, :], axis=1)) ** 2
    frequencies = np.fft.rfftfreq(fft_size, 1.0 / max(int(sample_rate), 1))
    audible = (frequencies >= 120.0) & (frequencies <= sample_rate * 0.48)
    high = (frequencies >= min(5600.0, sample_rate * 0.42)) & audible
    total_power = np.sum(power[:, audible], axis=1) if bool(audible.any()) else np.zeros(frame_count)
    high_power = np.sum(power[:, high], axis=1) if bool(high.any()) else np.zeros(frame_count)
    high_ratio = high_power / np.maximum(total_power, 1e-12)
    return {
        "sample_rate": int(sample_rate),
        "frames": int(frame_count),
        "peak": float(np.max(np.abs(data))) if data.size else 0.0,
        "frame_rms": frame_rms,
        "high_ratio": high_ratio,
    }


def _quality_gate_file(previous: Path, candidate: Path, stage: str) -> bool:
    """Keep a stage result only when it remains a valid, vocal-like render.

    A gate failure is a normal quality fallback, not a task failure.  This is applied
    to every AI Vocal stage and therefore works equally for SVC, RVC, SeedVC and
    third-party engines without making assumptions about their model configuration.
    """
    try:
        import numpy as np
        import soundfile as sf
    except ImportError:
        # Compatibility for source-only test/development environments.  Production
        # vocal workers always include soundfile and therefore always run the gate.
        return True

    try:
        before, before_sr = sf.read(str(previous), always_2d=True, dtype="float32")
    except Exception:
        return True
    try:
        after, after_sr = sf.read(str(candidate), always_2d=True, dtype="float32")
    except Exception as exc:
        shutil.copy2(previous, candidate)
        print(f"  质量门控回退[{stage}]：输出无法读取（{exc}）", flush=True)
        return False


    try:
        if not bool(np.isfinite(before).all()) or not bool(np.isfinite(after).all()):
            raise ValueError("非有限音频样本")
        if int(before_sr) != int(after_sr):
            raise ValueError(f"采样率错位 {before_sr}Hz -> {after_sr}Hz")

        base = _quality_features(before, int(before_sr))
        trial = _quality_features(after, int(after_sr))
        base_rms = np.asarray(base["frame_rms"], dtype=np.float64)
        trial_rms = np.asarray(trial["frame_rms"], dtype=np.float64)
        frame_count = min(len(base_rms), len(trial_rms))
        if frame_count < 2:
            return True
        base_rms = base_rms[:frame_count]
        trial_rms = trial_rms[:frame_count]
        base_threshold = max(1e-5, float(np.percentile(base_rms, 75)) * 0.02)
        active = base_rms >= base_threshold
        reasons: list[str] = []

        duration_delta = abs(len(before) - len(after)) / max(len(before), 1)
        if duration_delta > 0.003:
            reasons.append(f"时长变化 {duration_delta:.2%}")

        before_db = 20.0 * np.log10(np.maximum(base_rms[active], 1e-8))
        after_db = 20.0 * np.log10(np.maximum(trial_rms[active], 1e-8))
        if len(before_db):
            rms_delta = float(np.median(after_db - before_db))
            if abs(rms_delta) > 5.5:
                reasons.append(f"活动能量变化 {rms_delta:+.1f}dB")
            dropout_ratio = float(np.mean(after_db < before_db - 18.0))
            if dropout_ratio > 0.18:
                reasons.append(f"局部能量掉坑 {dropout_ratio:.1%}")

        inactive = ~active
        if bool(inactive.any()):
            noise_ratio = float(np.mean(trial_rms[inactive] > base_threshold * 1.8))
            if noise_ratio > 0.10:
                reasons.append(f"静音段抬噪 {noise_ratio:.1%}")

        base_high = np.asarray(base["high_ratio"], dtype=np.float64)[:frame_count]
        trial_high = np.asarray(trial["high_ratio"], dtype=np.float64)[:frame_count]
        if bool(active.any()):
            base_high_active = base_high[active]
            trial_high_active = trial_high[active]
            base_p95 = float(np.percentile(base_high_active, 95))
            trial_p95 = float(np.percentile(trial_high_active, 95))
            # Permit normal brightness changes, but reject a new high-band whistle/hiss.
            if (
                trial_p95 > max(0.24, base_p95 * 2.8 + 0.04)
                and trial_p95 - base_p95 > 0.10
            ):
                reasons.append(f"高频能量异常 {base_p95:.2f}->{trial_p95:.2f}")
            high_spike = active & (
                (trial_high > np.maximum(0.26, base_high * 3.0 + 0.08))
                & ((trial_high - base_high) > 0.12)
            )
            if float(np.mean(high_spike)) > 0.025:
                reasons.append(f"局部高频突增 {float(np.mean(high_spike)):.1%}")

        if float(trial["peak"]) > max(1.02, float(base["peak"]) * 1.35):
            reasons.append(f"峰值异常 {float(trial['peak']):.3f}")

        if reasons:
            shutil.copy2(previous, candidate)
            print(
                f"  质量门控回退[{stage}]：" + "；".join(reasons),
                flush=True,
            )
            return False
        return True
    except Exception as exc:  # noqa: BLE001 - conservative production fallback
        shutil.copy2(previous, candidate)
        print(f"  质量门控回退[{stage}]：无法分析音频（{exc}）", flush=True)
        return False


def _suppress_short_high_band_spikes(source: Path, output: Path) -> int:
    """Attenuate isolated, scratch-like HF bursts without changing timing.

    Model renders from different engines can contain a handful of very short
    whistle/scrape bursts before any post-processing runs. This detector only
    acts on runs shorter than 180 ms whose high-band energy jumps above its local
    baseline and is concentrated in a narrow spectral region. Sustained notes,
    normal sibilance and the vocal body are left untouched.
    """
    try:
        if source.resolve() == output.resolve():
            return 0
    except OSError:
        pass
    try:
        import numpy as np
        import soundfile as sf
        from scipy.ndimage import binary_dilation, uniform_filter1d
        from scipy.signal import butter, sosfiltfilt
    except ImportError:
        shutil.copy2(source, output)
        return 0

    try:
        audio, sample_rate = sf.read(str(source), always_2d=True, dtype="float32")
    except Exception:
        shutil.copy2(source, output)
        return 0
    data = np.asarray(audio, dtype=np.float64)
    if data.ndim != 2 or len(data) < max(2048, int(sample_rate * 0.12)):
        shutil.copy2(source, output)
        return 0
    if sample_rate < 16000:
        shutil.copy2(source, output)
        return 0

    try:
        cutoff = min(5600.0, sample_rate * 0.42)
        high_sos = butter(4, cutoff, btype="highpass", fs=sample_rate, output="sos")
        high = sosfiltfilt(high_sos, data, axis=0)
        mono = np.mean(data, axis=1)
        high_mono = np.mean(high, axis=1)

        frame_size = max(128, int(round(sample_rate * 0.010)))
        frame_count = int(np.ceil(len(mono) / frame_size))
        padded = np.pad(mono, (0, frame_count * frame_size - len(mono)))
        high_padded = np.pad(
            high_mono, (0, frame_count * frame_size - len(high_mono))
        )
        frames = padded.reshape(frame_count, frame_size)
        high_frames = high_padded.reshape(frame_count, frame_size)
        total_rms = np.sqrt(np.mean(frames * frames, axis=1) + 1e-12)
        high_rms = np.sqrt(np.mean(high_frames * high_frames, axis=1) + 1e-12)
        total_db = 20.0 * np.log10(total_rms + 1e-10)
        high_db = 20.0 * np.log10(high_rms + 1e-10)

        n_fft = 1 << max(10, min(12, int(np.ceil(np.log2(frame_size * 2)))))
        fft_frames = np.pad(
            frames,
            ((0, 0), (0, max(0, n_fft - frames.shape[1]))),
        )[:, :n_fft]
        power = np.abs(
            np.fft.rfft(fft_frames * np.hanning(n_fft), axis=1)
        ) ** 2
        frequencies = np.fft.rfftfreq(n_fft, 1.0 / float(sample_rate))
        audible = (frequencies >= 120.0) & (frequencies <= sample_rate * 0.48)
        high_bins = (frequencies >= cutoff * 0.90) & audible
        if not bool(high_bins.any()):
            shutil.copy2(source, output)
            return 0
        total_power = np.sum(power[:, audible], axis=1)
        high_power = np.sum(power[:, high_bins], axis=1)
        high_ratio = high_power / np.maximum(total_power, 1e-12)
        high_spectrum = power[:, high_bins] + 1e-14
        flatness = np.exp(np.mean(np.log(high_spectrum), axis=1)) / np.maximum(
            np.mean(high_spectrum, axis=1), 1e-14
        )
        peak_share = np.max(high_spectrum, axis=1) / np.maximum(
            np.sum(high_spectrum, axis=1), 1e-14
        )
        baseline_db = uniform_filter1d(high_db, size=21, mode="nearest")
        baseline_ratio = uniform_filter1d(high_ratio, size=21, mode="nearest")
        attack = high_db - baseline_db
        active = total_db >= max(-58.0, float(np.percentile(total_db, 25)) - 8.0)
        # Narrow, short bursts are the reliable signature of the scratch/whistle
        # artifact. The ratio and attack guards avoid touching ordinary high notes.
        candidate = (
            active
            & (high_db >= -55.0)
            & (attack >= 8.0)
            & (high_ratio >= np.maximum(0.075, baseline_ratio + 0.022))
            & (flatness <= 0.24)
            & (peak_share >= 0.035)
        )
        max_run = max(1, int(round(0.180 / 0.010)))
        selected = np.zeros(frame_count, dtype=bool)
        index = 0
        while index < frame_count:
            if not candidate[index]:
                index += 1
                continue
            end = index
            while end < frame_count and candidate[end]:
                end += 1
            if end - index <= max_run:
                selected[index:end] = True
            index = end
        if not bool(selected.any()):
            shutil.copy2(source, output)
            return 0
        selected = binary_dilation(selected, iterations=1)
        frame_amount = np.clip((attack - 7.0) / 12.0, 0.0, 1.0)
        frame_amount = np.where(selected, 0.24 + 0.38 * frame_amount, 0.0)
        centres = np.minimum(
            len(data) - 1,
            np.arange(frame_count, dtype=np.float64) * frame_size + frame_size * 0.5,
        )
        sample_amount = np.interp(
            np.arange(len(data), dtype=np.float64),
            centres,
            frame_amount,
            left=float(frame_amount[0]),
            right=float(frame_amount[-1]),
        )
        processed = data - high * sample_amount[:, np.newaxis]
        _write_float_wav(output, processed.T, int(sample_rate))
        print(
            "  通用短时高频瞬态保护: "
            f"{int(selected.sum())} 帧，最大衰减 {float(np.max(frame_amount)):.0%}",
            flush=True,
        )
        return int(selected.sum())
    except Exception:
        shutil.copy2(source, output)
        return 0


def _suppress_noise_like_high_band(
    source: Path,
    output: Path,
    *,
    max_attenuation_db: float = 4.2,
    cutoff_hz: float = 5600.0,
    ratio_floor: float = 0.095,
    flatness_floor: float = 0.075,
) -> tuple[int, float]:
    """Lower a sustained noise-like air band while keeping the vocal body.

    This is intentionally separate from the short-spike detector.  A model
    render can have a continuous fan-like bed whose individual 10 ms frames do
    not look like isolated whistles.  Only frames with both a high-band energy
    ratio and broadband high-band flatness are touched; tonal high notes do not
    pass this gate.
    """
    try:
        import numpy as np
        import soundfile as sf
        from scipy.ndimage import gaussian_filter1d
        from scipy.signal import butter, sosfiltfilt
    except ImportError:
        shutil.copy2(source, output)
        return 0, 0.0

    try:
        audio, sample_rate = sf.read(str(source), always_2d=True, dtype="float32")
        data = np.asarray(audio, dtype=np.float64)
        if data.ndim != 2 or len(data) < max(2048, int(sample_rate * 0.12)):
            shutil.copy2(source, output)
            return 0, 0.0
        if sample_rate < 16000:
            shutil.copy2(source, output)
            return 0, 0.0

        cutoff = min(max(1800.0, float(cutoff_hz)), float(sample_rate) * 0.42)
        high_sos = butter(4, cutoff, btype="highpass", fs=sample_rate, output="sos")
        high = sosfiltfilt(high_sos, data, axis=0)
        mono = np.mean(data, axis=1)
        high_mono = np.mean(high, axis=1)
        frame_size = max(256, int(round(sample_rate * 0.020)))
        frame_count = int(np.ceil(len(mono) / frame_size))
        padding = frame_count * frame_size - len(mono)
        frames = np.pad(mono, (0, padding)).reshape(frame_count, frame_size)
        high_frames = np.pad(high_mono, (0, padding)).reshape(frame_count, frame_size)
        total_rms = np.sqrt(np.mean(frames * frames, axis=1) + 1e-12)
        high_rms = np.sqrt(np.mean(high_frames * high_frames, axis=1) + 1e-12)
        high_ratio = np.square(high_rms) / np.maximum(np.square(total_rms), 1e-12)

        n_fft = 1 << max(10, min(12, int(np.ceil(np.log2(frame_size * 2)))))
        fft_frames = np.pad(
            frames,
            ((0, 0), (0, max(0, n_fft - frame_size))),
        )[:, :n_fft]
        spectrum = np.abs(
            np.fft.rfft(fft_frames * np.hanning(n_fft), axis=1)
        ) ** 2
        frequencies = np.fft.rfftfreq(n_fft, 1.0 / float(sample_rate))
        high_bins = (frequencies >= cutoff) & (
            frequencies <= min(16000.0, sample_rate * 0.48)
        )
        if not bool(high_bins.any()):
            shutil.copy2(source, output)
            return 0, 0.0
        high_spectrum = np.maximum(spectrum[:, high_bins], 1e-14)
        flatness = np.exp(np.mean(np.log(high_spectrum), axis=1)) / np.maximum(
            np.mean(high_spectrum, axis=1), 1e-14
        )
        # Broadband breath has weak short-time periodicity, while a voiced
        # high note has a strong autocorrelation peak even when upper
        # harmonics sit in this high band. Keep the voiced component intact.
        autocorrelation = np.fft.irfft(spectrum, n=n_fft, axis=1)
        lag_min = max(1, int(round(float(sample_rate) / 1400.0)))
        lag_max = min(frame_size - 1, int(round(float(sample_rate) / 70.0)))
        if lag_max > lag_min:
            periodicity = np.max(
                np.maximum(autocorrelation[:, lag_min : lag_max + 1], 0.0),
                axis=1,
            ) / np.maximum(autocorrelation[:, 0], 1e-12)
        else:
            periodicity = np.zeros(frame_count, dtype=np.float64)
        active_floor = max(0.008, float(np.percentile(total_rms, 25)) * 0.65)
        active = total_rms >= active_floor
        ratio_floor = float(np.clip(ratio_floor, 0.02, 0.35))
        flatness_floor = float(np.clip(flatness_floor, 0.02, 0.35))
        ratio_score = np.clip((high_ratio - ratio_floor) / 0.11, 0.0, 1.0)
        flatness_score = np.clip((flatness - flatness_floor) / 0.22, 0.0, 1.0)
        periodicity_guard = np.clip((periodicity - 0.28) / 0.32, 0.0, 1.0)
        noise_score = ratio_score * flatness_score * (1.0 - 0.90 * periodicity_guard)
        noise_score[~active] = 0.0
        selected = (noise_score >= 0.18) & (periodicity < 0.62)
        if not bool(selected.any()):
            shutil.copy2(source, output)
            return 0, 0.0
        # Smooth the reduction so the air band does not pump at frame edges.
        noise_score = gaussian_filter1d(noise_score, sigma=2.0, mode="nearest")
        attenuation = np.clip(noise_score, 0.0, 1.0) * float(max_attenuation_db)
        gain = np.power(10.0, -attenuation / 20.0)
        centres = np.minimum(
            len(data) - 1,
            np.arange(frame_count, dtype=np.float64) * frame_size + frame_size * 0.5,
        )
        sample_gain = np.interp(
            np.arange(len(data), dtype=np.float64),
            centres,
            gain,
            left=float(gain[0]),
            right=float(gain[-1]),
        )
        processed = data - high * (1.0 - sample_gain[:, np.newaxis])
        _write_float_wav(output, processed.T, int(sample_rate))
        return int(np.count_nonzero(selected)), float(np.max(attenuation))
    except Exception:
        shutil.copy2(source, output)
        return 0, 0.0


def _restore_high_note_body(
    source: Path,
    guide: Path,
    output: Path,
    *,
    max_boost_db: float = 2.6,
    low_hz: float = 220.0,
    high_hz: float = 3800.0,
) -> tuple[int, float]:
    """Recover weak voiced high-note body without copying dry timbre.

    The model and DeepFilter stages can leave a high note with a usable pitch
    but too little periodic energy.  This pass uses the guide only for local
    voicing and relative level; it adds gain to the current render's
    220--3800 Hz band and never transfers the guide waveform or its air band.
    """
    try:
        import librosa
        import numpy as np
        import soundfile as sf
        from scipy.ndimage import gaussian_filter1d
        from scipy.signal import butter, sosfiltfilt
    except ImportError:
        shutil.copy2(source, output)
        return 0, 0.0

    try:
        if not source.is_file() or not guide.is_file():
            shutil.copy2(source, output)
            return 0, 0.0
        if source.resolve() == output.resolve():
            return 0, 0.0
    except OSError:
        pass

    try:
        source_audio, sample_rate = sf.read(
            str(source), always_2d=True, dtype="float32"
        )
        guide_audio, guide_rate = sf.read(
            str(guide), always_2d=True, dtype="float32"
        )
        target = np.asarray(source_audio, dtype=np.float64)
        reference = np.asarray(guide_audio, dtype=np.float64)
        if target.ndim != 2 or reference.ndim != 2 or len(target) < 2048:
            shutil.copy2(source, output)
            return 0, 0.0
        if int(guide_rate) != int(sample_rate):
            reference = np.column_stack(
                [
                    librosa.resample(
                        channel.astype(np.float32),
                        orig_sr=int(guide_rate),
                        target_sr=int(sample_rate),
                    )
                    for channel in reference.T
                ]
            ).astype(np.float64, copy=False)

        frames = min(len(target), len(reference))
        if frames < max(2048, int(sample_rate * 0.12)):
            shutil.copy2(source, output)
            return 0, 0.0
        target = target[:frames]
        reference = reference[:frames]
        target_mono = np.mean(target, axis=1)
        reference_mono = np.mean(reference, axis=1)

        frame_size = max(512, int(round(sample_rate * 0.040)))
        frame_count = int(np.ceil(frames / frame_size))
        padding = frame_count * frame_size - frames
        reference_frames = np.pad(reference_mono, (0, padding)).reshape(
            frame_count, frame_size
        )

        body_high = min(float(high_hz), float(sample_rate) * 0.45)
        body_low = min(max(80.0, float(low_hz)), body_high * 0.65)
        if body_high <= body_low + 80.0:
            shutil.copy2(source, output)
            return 0, 0.0
        body_sos = butter(
            4,
            [body_low, body_high],
            btype="bandpass",
            fs=sample_rate,
            output="sos",
        )
        target_body = sosfiltfilt(body_sos, target_mono)
        reference_body = sosfiltfilt(body_sos, reference_mono)
        target_body_frames = np.pad(target_body, (0, padding)).reshape(
            frame_count, frame_size
        )
        reference_body_frames = np.pad(reference_body, (0, padding)).reshape(
            frame_count, frame_size
        )
        target_rms = np.sqrt(
            np.mean(target_body_frames * target_body_frames, axis=1) + 1e-12
        )
        reference_rms = np.sqrt(
            np.mean(reference_body_frames * reference_body_frames, axis=1) + 1e-12
        )

        # Estimate a local F0 from the guide.  A 40 ms frame is long enough to
        # distinguish a genuine high note from a single bright consonant.
        centered = reference_frames - np.mean(reference_frames, axis=1, keepdims=True)
        fft_size = 1 << max(11, (frame_size * 2 - 1).bit_length())
        window = np.hanning(frame_size)
        spectrum = np.fft.rfft(
            centered * window[np.newaxis, :], n=fft_size, axis=1
        )
        autocorrelation = np.fft.irfft(
            np.abs(spectrum) ** 2, n=fft_size, axis=1
        )[:, :frame_size]
        lag_min = max(2, int(round(sample_rate / 1700.0)))
        lag_max = min(frame_size - 2, int(round(sample_rate / 480.0)))
        if lag_max <= lag_min + 2:
            shutil.copy2(source, output)
            return 0, 0.0
        lag_window = autocorrelation[:, lag_min : lag_max + 1]
        lag_offsets = np.argmax(lag_window, axis=1)
        lags = lag_offsets + lag_min
        peaks = lag_window[np.arange(frame_count), lag_offsets]
        periodicity = peaks / np.maximum(autocorrelation[:, 0], 1e-12)
        f0 = sample_rate / np.maximum(lags, 1)

        reference_floor = max(
            0.008,
            float(np.percentile(reference_rms, 25)) * 0.65,
        )
        target_floor = max(
            0.004,
            float(np.percentile(target_rms, 25)) * 0.45,
        )
        voiced = (
            (reference_rms >= reference_floor)
            & (target_rms >= target_floor)
            & (f0 >= 560.0)
            & (periodicity >= 0.28)
        )
        if not bool(voiced.any()):
            shutil.copy2(source, output)
            return 0, 0.0

        # Require neighboring support and soften both ends of each note. This
        # prevents a tracker spike or a consonant from opening a gain jump.
        support = np.convolve(
            voiced.astype(np.float64),
            np.ones(3, dtype=np.float64),
            mode="same",
        )
        high_note = voiced & (support >= 2.0)
        high_note = gaussian_filter1d(
            high_note.astype(np.float64), sigma=1.15, mode="nearest"
        )
        high_note = np.clip(high_note, 0.0, 1.0)
        if not bool(np.any(high_note >= 0.25)):
            shutil.copy2(source, output)
            return 0, 0.0

        target_db = 20.0 * np.log10(target_rms + 1e-10)
        reference_db = 20.0 * np.log10(reference_rms + 1e-10)
        active = (reference_rms >= reference_floor) & (target_rms >= target_floor)
        # Estimate the ordinary model-to-guide level difference from non-high
        # frames, then apply only the local high-note deficit. This avoids
        # interpreting a globally quieter render as a series of high-note faults.
        normal = active & (high_note < 0.20)
        if int(np.count_nonzero(normal)) < 8:
            normal = active
        if not bool(normal.any()):
            shutil.copy2(source, output)
            return 0, 0.0
        level_offset = float(np.median(reference_db[normal] - target_db[normal]))
        deficit = (reference_db - target_db) - level_offset
        boost_db = np.clip(deficit * 0.70, 0.0, float(max(0.0, max_boost_db)))
        boost_db *= high_note
        boost_db = gaussian_filter1d(boost_db, sigma=1.0, mode="nearest")
        boost_db = np.clip(boost_db, 0.0, float(max(0.0, max_boost_db)))
        if not bool(np.any(boost_db >= 0.25)):
            shutil.copy2(source, output)
            return 0, 0.0

        centres = np.minimum(
            frames - 1,
            np.arange(frame_count, dtype=np.float64) * frame_size + frame_size * 0.5,
        )
        sample_boost = np.interp(
            np.arange(frames, dtype=np.float64),
            centres,
            boost_db,
            left=float(boost_db[0]),
            right=float(boost_db[-1]),
        )
        gain = np.power(10.0, sample_boost / 20.0)
        body = sosfiltfilt(body_sos, target, axis=0)
        processed = target + body * (gain[:, np.newaxis] - 1.0)
        peak = float(np.max(np.abs(processed))) if processed.size else 0.0
        if peak > 0.99:
            processed *= 0.99 / peak
        _write_float_wav(output, processed.T, int(sample_rate))
        selected = int(np.count_nonzero(boost_db >= 0.25))
        return selected, float(np.max(boost_db))
    except Exception:
        shutil.copy2(source, output)
        return 0, 0.0


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


def _match_reference(
    source: Path,
    reference: Path,
    output: Path,
    *,
    allow_high_band: bool = True,
) -> None:
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
    # The dry reference is useful for broad tone balance, but must not be used
    # to boost a model render that already has a broadband HF residual.  This
    # keeps the model's character while preventing a short whistle from being
    # made louder by the advanced enhancement pass.
    source_profile = _audio_profile_array(src_audio, src_sr)
    if (
        not allow_high_band
        or bool(source_profile.get("high_band_noise", False))
    ) and high_gain > 0.0:
        high_gain = 0.0
        print("  模型高频残留疑似噪声，跳过参考高频提升", flush=True)
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


def _restore_reference_detail(
    source: Path,
    reference: Path,
    output: Path,
    *,
    allow_high_band: bool = True,
) -> None:
    """Use the reference envelope to lift phase-coherent model detail.

    The reference is only a level guide. Mixing its waveform into a converted
    high note combines two unrelated harmonic phases and can create audible
    beating. Boosting the model render's own high band retains consonant detail
    without introducing a second carrier.
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
    if not allow_high_band:
        # The model render remains the authority when its high band was already
        # classified as residual noise.  Do not re-inject dry 5.5 kHz+ detail
        # after a preceding broad-spectrum match has lowered that profile below
        # the classifier threshold.
        shutil.copy2(source, output)
        print("  模型高频残留疑似噪声，跳过干声高频细节混合", flush=True)
        return
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
    src_high_power = uniform_filter1d(
        np.mean(src_high ** 2, axis=1),
        size=window,
        mode="nearest",
    )
    # 递归均匀滤波器在长信号下可能因几个微小的单位量化误差（ULP）而低于平方信号。
    # 在开平方根之前对数值噪声进行钳位，以防止其污染输出结果。
    ref_power = np.maximum(ref_power, 0.0)
    high_power = np.maximum(high_power, 0.0)
    src_high_power = np.maximum(src_high_power, 0.0)
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
    reference_high_rms = np.sqrt(high_power)
    source_high_rms = np.sqrt(src_high_power)
    missing_detail = np.clip(
        (reference_high_rms - source_high_rms)
        / np.maximum(reference_high_rms, 1e-6),
        0.0,
        1.0,
    )
    detail_boost = (
        0.12
        * detail_activity
        * audible
        * np.sqrt(source_present)
        * missing_detail
    )
    detail_boost = gaussian_filter1d(
        detail_boost,
        sigma=max(1.0, src_sr * 0.008),
        mode="nearest",
    )

    restored = src_audio + detail_boost[:, np.newaxis] * src_high
    peak = float(np.max(np.abs(restored))) if restored.size else 0.0
    if peak > 0.99:
        restored *= 0.99 / peak
    _write_float_wav(output, restored.T, src_sr)
    print(
        "  同相辅音/呼吸细节保护: "
        f"peak boost={float(detail_boost.max()) * 100:.1f}%",
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
            "high_band_noise": False,
            "high_band_flatness": 0.0,
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
    high_frame_mask = (f0_frequencies >= 6000.0) & (
        f0_frequencies <= min(16000.0, sample_rate * 0.48)
    )
    high_flatness = 0.0
    if bool(high_frame_mask.any()):
        high_spectrum = np.maximum(frame_power[high_frame_mask], 1e-14)
        high_active = high_spectrum[:, frame_levels >= active_threshold]
        if high_active.shape[1]:
            geometric = np.exp(np.mean(np.log(high_active), axis=0))
            arithmetic = np.mean(high_active, axis=0)
            flatness_values = geometric / np.maximum(arithmetic, 1e-14)
            high_flatness = float(np.median(flatness_values))
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
    # A very bright signal with an ordinary singing range is usually UVR/model
    # residual noise, not a high note.  Treat it separately so "high protection"
    # cannot feed a whistle back into the repaired vocal.
    # Model renders can contain a broad, whistle-like residual without pushing
    # the whole-song centroid above 3.8 kHz.  The combination of high-band
    # energy, high spectral flatness and an ordinary singing range is a stronger
    # signal than centroid alone.  Keep the ratio threshold conservative so
    # bright but tonal high notes continue through the normal protection path.
    high_band_noise = bool(
        not high_pitch
        and high_ratio >= 0.14
        and centroid >= 3200.0
        and high_flatness >= 0.08
    )
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
        "high_band_noise": high_band_noise,
        "high_band_flatness": high_flatness,
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
    reference: Path | None = None,
) -> dict[str, float | bool]:
    """Repair separated/model vocals with DeepFilterNet3 and guarded HF recovery."""
    if not source.is_file():
        raise RuntimeError(f"输入文件不存在: {source}")
    normalized_stage = "output" if stage == "output" else "separated"
    output.parent.mkdir(parents=True, exist_ok=True)
    profile = dict(profile or _analyze_audio(source))
    # Older callers may pass an analysis JSON generated before the residual-noise
    # fields were added.  Fill only missing fields from the current source so the
    # repair policy is deterministic across single/multi-model workflows.
    if "high_band_noise" not in profile or "high_band_flatness" not in profile:
        current_profile = _analyze_audio(source)
        for key in ("high_band_noise", "high_band_flatness"):
            if key not in profile:
                profile[key] = current_profile[key]
    high_guard = bool(
        profile.get("high_frequency", False) or profile.get("high_pitch", False)
    )
    high_band_noise = bool(profile.get("high_band_noise", False))
    if normalized_stage == "output" and not high_band_noise:
        # A model render has no room tone to remove. DeepFilter and the broad
        # recovery passes only discard consonant/presence detail when its high
        # band is already tonal and clean.
        print(
            "[1/2] 模型输出未检出噪声型高频，保留原始模型人声",
            flush=True,
        )
        if source.resolve() != output.resolve():
            shutil.copy2(source, output)
        return profile
    base_attenuation = 6.0 if normalized_stage == "separated" else 4.5
    attenuation = base_attenuation - (1.5 if high_guard and not high_band_noise else 0.0)
    attenuation = max(2.5, attenuation)
    print(
        "[1/2] DeepFilterNet3 专用人声修复 "
        f"(stage={normalized_stage}, attenuation={attenuation:.1f}dB)",
        flush=True,
    )
    with tempfile.TemporaryDirectory(prefix="xb-vocal-repair-") as raw_temp:
        repair_source = source
        spike_cleaned = Path(raw_temp) / "short_hf_cleaned.wav"
        spike_frames = _suppress_short_high_band_spikes(source, spike_cleaned)
        if spike_frames:
            # The detector is intentionally guarded by the same stage gate as
            # every other enhancement operation. If it changes timing/energy in
            # an implausible way, DeepFilter receives the untouched model render.
            if _quality_gate_file(source, spike_cleaned, f"短时高频瞬态-{normalized_stage}"):
                repair_source = spike_cleaned
            else:
                spike_cleaned.unlink(missing_ok=True)
        repaired = Path(raw_temp) / "deepfilter.wav"
        _deepfilter(repair_source, repaired, atten_lim_db=attenuation)
        repair_result = repaired
        if high_band_noise:
            noise_cleaned = Path(raw_temp) / "noise_band_cleaned.wav"
            noise_frames, noise_attenuation = _suppress_noise_like_high_band(
                repaired,
                noise_cleaned,
            )
            if noise_frames and _quality_gate_file(
                repaired,
                noise_cleaned,
                "模型高频残留",
            ):
                repair_result = noise_cleaned
                print(
                    "  模型高频残留抑制："
                    f"{noise_frames} 帧，最大衰减 {noise_attenuation:.1f}dB",
                    flush=True,
                )
        if high_band_noise:
            print("[2/2] 高频残留判定为噪声，跳过原始高频回填", flush=True)
            shutil.copy2(repair_result, output)
        else:
            print("[2/2] 高频辅音与高音泛音保护", flush=True)
            _restore_repair_high_band(
                repair_source,
                repaired,
                output,
                stage=normalized_stage,
            )
        # Local breath can be missed by the whole-track high-band classifier,
        # especially when only one high note is affected. Remove only the
        # flat, broadband component above 3.8 kHz; periodic high-note harmonics
        # remain untouched. This runs after dry high-band restoration so that
        # the restoration cannot put the breath back immediately.
        breath_cleaned = Path(raw_temp) / "breathy_high_band_cleaned.wav"
        breath_frames, breath_attenuation = _suppress_noise_like_high_band(
            output,
            breath_cleaned,
            max_attenuation_db=5.5 if normalized_stage == "output" else 6.0,
            cutoff_hz=3800.0,
            ratio_floor=0.085,
            flatness_floor=0.11,
        )
        if breath_frames and _quality_gate_file(
            output,
            breath_cleaned,
            f"局部高音气声-{normalized_stage}",
        ):
            shutil.copy2(breath_cleaned, output)
            print(
                "  局部高音气声抑制："
                f"{breath_frames} 帧，最大衰减 {breath_attenuation:.1f}dB",
                flush=True,
            )
        # DeepFilter and the preceding pitch guard can preserve F0 while
        # reducing the periodic body of a high note. Recover that body from
        # the same pre-repair input, using it only as a voicing/level guide.
        # The guide's waveform and 3.8 kHz+ air band are never copied.
        body_guide = (
            reference
            if reference is not None and reference.is_file()
            else repair_source
        )
        body_source = Path(raw_temp) / "high_note_body.wav"
        body_frames, body_boost = _restore_high_note_body(
            output,
            body_guide,
            body_source,
            max_boost_db=2.8 if normalized_stage == "output" else 2.6,
        )
        if body_frames and _quality_gate_file(
            output,
            body_source,
            f"高音主体恢复-{normalized_stage}",
        ):
            shutil.copy2(body_source, output)
            print(
                "  高音主体恢复："
                f"{body_frames} 帧，最大提升 {body_boost:.1f}dB",
                flush=True,
            )
        _quality_gate_file(source, output, f"DeepFilter-{normalized_stage}")
        if high_band_noise and output.is_file():
            # DeepFilter can raise the 5.6 kHz residual on model renders even
            # when its frame-level gate sees no new isolated spike.  For a
            # noise-like model profile, keep the model render as the authority
            # unless the repaired result stays within a small HF-energy budget.
            repaired_profile = _analyze_audio(output)
            source_ratio = float(profile.get("high_band_ratio", 0.0))
            repaired_ratio = float(repaired_profile.get("high_band_ratio", 0.0))
            allowed_ratio = source_ratio * 1.04 + 0.004
            if repaired_ratio > allowed_ratio:
                shutil.copy2(source, output)
                print(
                    "  高频残留预算超限，回退 DeepFilter 输出 "
                    f"({source_ratio:.3f}->{repaired_ratio:.3f})",
                    flush=True,
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
    """Widen existing stereo ambience without synthesizing a delayed copy."""
    import numpy as np

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
    preserve_model_high_band: bool = False,
    model_profile_source: Path | None = None,
) -> None:
    if not source.is_file():
        raise RuntimeError(f"输入文件不存在: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        source_profile = _analyze_audio(model_profile_source or source)
    except (OSError, RuntimeError, ValueError, ImportError):
        # Source-only tests and recovery environments may not have the optional
        # analysis stack.  The enhancement chain remains usable; production
        # installs always provide soundfile/scipy here.
        source_profile = {}
    model_high_band_noise = bool(
        preserve_model_high_band or source_profile.get("high_band_noise", False)
    )

    with tempfile.TemporaryDirectory(prefix="xb-vocal-enhance-") as raw_temp:
        temp = Path(raw_temp)
        silenced = temp / "00_silenced.wav"
        print("[1/12] 自然停顿扩展（保留起音、呼吸与尾音）", flush=True)
        _silence_vocalfloor_file(source, silenced)
        _quality_gate_file(source, silenced, "自然停顿")
        current = silenced

        use_reference = (
            level == "advanced" and reference is not None and reference.is_file()
        )
        if use_reference:
            matched = temp / "01_matched.wav"
            print(f"[2/12] 宽带频谱参考（{reference.name}）", flush=True)
            if model_high_band_noise:
                _match_reference(
                    current,
                    reference,
                    matched,
                    allow_high_band=False,
                )
            else:
                _match_reference(current, reference, matched)
            _quality_gate_file(current, matched, "参考频谱")
            current = matched
        else:
            print("[2/12] 跳过宽带频谱参考（仅高级模式且需要原始人声）", flush=True)

        if skip_deepfilter:
            print("[3/12] 已完成专用修复，跳过重复 DeepFilterNet", flush=True)
        else:
            filtered = temp / "02_deepfilter.wav"
            print("[3/12] DeepFilterNet 原生采样率限量降噪", flush=True)
            _deepfilter(current, filtered)
            _quality_gate_file(current, filtered, "DeepFilter")
            current = filtered

        if use_reference:
            detailed = temp / "03_human_detail.wav"
            print("[4/12] 真实辅音与呼吸细节保护", flush=True)
            if model_high_band_noise:
                _restore_reference_detail(
                    current,
                    reference,
                    detailed,
                    allow_high_band=False,
                )
            else:
                _restore_reference_detail(current, reference, detailed)
            _quality_gate_file(current, detailed, "参考细节")
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

        _quality_gate_file(current, dsp_output, "母带")

        natural = temp / "05_natural_mix.wav"
        print(f"[6/12] 动态并行自然度混合（wet 上限={wet_mix:.0%}）", flush=True)
        _parallel_mix(silenced, dsp_output, natural, wet_mix)
        _quality_gate_file(current, natural, "并行混合")
        current = natural

        focused = temp / "06_timbre.wav"
        print(f"[7/12] AI 角色共振峰（{float(timbre_focus):.0%}）", flush=True)
        _focus_target_timbre(current, focused, timbre_focus)
        _quality_gate_file(current, focused, "角色共振峰")
        current = focused

        equalized = temp / "07_ai_eq.wav"
        print(f"[8/12] AI EQ（{float(ai_eq):.0%}）", flush=True)
        _ai_eq(current, equalized, ai_eq)
        _quality_gate_file(current, equalized, "AI EQ")
        current = equalized

        compressed = temp / "08_ai_compressor.wav"
        print(f"[9/12] AI Compressor（{float(ai_compressor):.0%}）", flush=True)
        _ai_compressor(current, compressed, ai_compressor)
        _quality_gate_file(current, compressed, "AI Compressor")
        current = compressed

        excited = temp / "09_ai_exciter.wav"
        print(f"[10/12] AI Exciter（{float(ai_exciter):.0%}）", flush=True)
        _ai_exciter(current, excited, ai_exciter)
        _quality_gate_file(current, excited, "AI Exciter")
        current = excited

        stereo = temp / "10_stereo.wav"
        print(f"[11/12] Stereo（{float(stereo_width):.0%}）", flush=True)
        _stereo_image(current, stereo, stereo_width)
        _quality_gate_file(current, stereo, "Stereo")
        current = stereo

        print(
            f"[12/12] AI 响度包络（{float(loudness_envelope):.0%}）",
            flush=True,
        )
        _ai_loudness_envelope(silenced, current, output, loudness_envelope)
        if model_high_band_noise:
            # Cleanup at the chain boundary is reserved for a model render that
            # was positively classified as noise-like. On clean renders these
            # broad detectors mistake high notes and consonants for artifacts.
            final_hf_cleaned = temp / "12_short_hf_cleaned.wav"
            final_hf_frames = _suppress_short_high_band_spikes(
                output, final_hf_cleaned
            )
            if final_hf_frames and _quality_gate_file(
                output, final_hf_cleaned, "收尾短时高频瞬态"
            ):
                shutil.copy2(final_hf_cleaned, output)

            final_breath_cleaned = temp / "12_breathy_high_band_cleaned.wav"
            final_breath_frames, final_breath_attenuation = (
                _suppress_noise_like_high_band(
                    output,
                    final_breath_cleaned,
                    max_attenuation_db=5.0,
                    cutoff_hz=3800.0,
                    ratio_floor=0.085,
                    flatness_floor=0.11,
                )
            )
            if final_breath_frames and _quality_gate_file(
                output,
                final_breath_cleaned,
                "收尾局部高音气声",
            ):
                shutil.copy2(final_breath_cleaned, output)
                print(
                    "  收尾局部高音气声抑制："
                    f"{final_breath_frames} 帧，最大衰减 "
                    f"{final_breath_attenuation:.1f}dB",
                    flush=True,
                )

            final_noise_cleaned = temp / "12_noise_band_cleaned.wav"
            noise_frames, noise_attenuation = _suppress_noise_like_high_band(
                output,
                final_noise_cleaned,
                max_attenuation_db=4.2,
            )
            if noise_frames and _quality_gate_file(
                output,
                final_noise_cleaned,
                "收尾模型高频残留",
            ):
                shutil.copy2(final_noise_cleaned, output)
                print(
                    "  收尾模型高频残留抑制："
                    f"{noise_frames} 帧，最大衰减 {noise_attenuation:.1f}dB",
                    flush=True,
                )

            final_body_guide = (
                reference
                if reference is not None and reference.is_file()
                else source
            )
            final_body_source = temp / "12_high_note_body.wav"
            final_body_frames, final_body_boost = _restore_high_note_body(
                output,
                final_body_guide,
                final_body_source,
                max_boost_db=2.2,
            )
            if final_body_frames and _quality_gate_file(
                output,
                final_body_source,
                "收尾高音主体恢复",
            ):
                shutil.copy2(final_body_source, output)
                print(
                    "  收尾高音主体恢复："
                    f"{final_body_frames} 帧，最大提升 {final_body_boost:.1f}dB",
                    flush=True,
                )
        else:
            print("  模型高频干净，跳过收尾高频/气声/高音主体修复", flush=True)
        _quality_gate_file(current, output, "响度包络")


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
    parser.add_argument(
        "--preserve-model-high-band",
        action="store_true",
        help="模型高频已在推理阶段判定为残留噪声时，增强阶段不回填干声高频",
    )
    parser.add_argument(
        "--model-profile-source",
        default=None,
        help="增强前模型输出，用于跨自然修音临时文件保留高频残留判定",
    )
    parser.add_argument("--level", choices=("basic", "advanced"), default="basic")
    parser.add_argument("--device", default="auto")
    parser.add_argument(
        "--reference",
        default=None,
        help="原始人声参考文件路径（高级频谱匹配；同时用于恢复高音主体）",
    )
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
                Path(args.reference) if args.reference else None,
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
            args.preserve_model_high_band,
            Path(args.model_profile_source) if args.model_profile_source else None,
        )
        print(f"VOCAL_ENHANCE_OK {output}", flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 - worker must return a concise boundary error
        print(f"VOCAL_ENHANCE_ERR {exc}", flush=True)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
