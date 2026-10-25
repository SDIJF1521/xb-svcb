"""使用 Praat PSOLA 进行参考引导的时序对齐和自然音高修正。

转换后的主唱会先向原始演唱对齐，再向参考轨和缓慢估计的音符中心修正音高。保守的时长分层可以保留音高和共振峰，而快速变化，例如颤音和滑音，则继续保留。
"""

from __future__ import annotations

import argparse
import math
import shutil
import sys
import traceback
from pathlib import Path


_RESYNTHESIS_PITCH_SEED_CENTS = 12.0
_RESYNTHESIS_PITCH_SUPPORT_CENTS = 5.0
_RESYNTHESIS_PITCH_RELEASE_CENTS = 1.5
_MIN_APPLIED_RESYNTHESIS_PITCH_CENTS = 5.0
_RESYNTHESIS_PITCH_SMOOTH_SECONDS = 0.040
_MIN_RESYNTHESIS_PITCH_POINTS = 12
_MIN_RESYNTHESIS_PITCH_SECONDS = 0.150
# 校正叶片中的缺失 F0 帧通常意味着起音、释放或辅音。让 PSOLA 跨过它会在听众形容成咔嗒/卡顿的那个位置制造短暂相位跳变。
_RESYNTHESIS_MAX_INTERNAL_GAP_SECONDS = 0.025
# PSOLA 对持续音很可靠，但滑音或八度跟踪跳变需要单独的时变处理。把这些轮廓从局部重合成遮罩中排除，同时保留音高曲线本身供诊断和未来方法使用。
_RESYNTHESIS_MAX_SOURCE_PITCH_SPAN_SEMITONES = 1.75
_RESYNTHESIS_MAX_SOURCE_PITCH_SLOPE_SEMITONES_PER_SECOND = 6.0
_RESYNTHESIS_CROSSFADE_SECONDS = 0.005
_RESYNTHESIS_CROSSFADE_POWER_SECONDS = 0.006
_MAX_RESYNTHESIS_CROSSFADE_GAIN_DB = 3.0
_REFERENCE_GAP_FRAME_SECONDS = 0.020
_REFERENCE_GAP_HOP_SECONDS = 0.005
_REFERENCE_GAP_MIN_SECONDS = 0.025
_REFERENCE_GAP_MAX_SECONDS = 0.160
_REFERENCE_GAP_SUPPORT_SECONDS = 0.120
_REFERENCE_GAP_QUIET_DROP_DB = 18.0
_REFERENCE_GAP_MIN_EXCESS_DB = 7.0
_REFERENCE_GAP_MAX_ATTENUATION_DB = 8.0


def _hz_to_midi(frequency: "np.ndarray") -> "np.ndarray":
    import numpy as np

    return 69.0 + 12.0 * np.log2(np.maximum(frequency, 1e-6) / 440.0)


def _midi_to_hz(midi: "np.ndarray") -> "np.ndarray":
    import numpy as np

    return 440.0 * np.power(2.0, (midi - 69.0) / 12.0)


def _natural_pitch_curve(
    source_times: "np.ndarray",
    source_frequencies: "np.ndarray",
    reference_times: "np.ndarray",
    reference_frequencies: "np.ndarray",
    strength: float,
) -> tuple["np.ndarray", dict[str, float]]:
    """返回适用于 Praat PitchTier 点的保守修正 F0 曲线。"""
    import numpy as np
    from scipy.ndimage import gaussian_filter1d, median_filter

    corrected = np.asarray(source_frequencies, dtype=np.float64).copy()
    amount = float(np.clip(strength, 0.0, 1.0))
    if amount <= 0.0 or len(corrected) < 3 or len(reference_frequencies) < 3:
        return corrected, {"points": 0.0, "median_cents": 0.0, "max_cents": 0.0}

    src_times = np.asarray(source_times, dtype=np.float64)
    ref_times = np.asarray(reference_times, dtype=np.float64)
    src_midi = _hz_to_midi(np.asarray(source_frequencies, dtype=np.float64))
    ref_midi_points = _hz_to_midi(
        np.asarray(reference_frequencies, dtype=np.float64)
    )

    positions = np.searchsorted(ref_times, src_times)
    right = np.clip(positions, 0, len(ref_times) - 1)
    left = np.clip(positions - 1, 0, len(ref_times) - 1)
    left_distance = np.abs(src_times - ref_times[left])
    right_distance = np.abs(src_times - ref_times[right])
    nearest_distance = np.minimum(left_distance, right_distance)
    valid = nearest_distance <= 0.04
    ref_midi = np.interp(src_times, ref_times, ref_midi_points)

    correction = np.zeros_like(src_midi)
    valid_indices = np.flatnonzero(valid)
    if not valid_indices.size:
        return corrected, {"points": 0.0, "median_cents": 0.0, "max_cents": 0.0}

    # 分别处理每个有声音节段，避免中位数跨越无声间隙。
    split_at = np.flatnonzero(
        (np.diff(valid_indices) > 1)
        | (np.diff(src_times[valid_indices]) > 0.055)
    )
    starts = np.r_[0, split_at + 1]
    ends = np.r_[split_at + 1, len(valid_indices)]
    for start, end in zip(starts, ends):
        indices = valid_indices[start:end]
        if len(indices) < 3:
            continue
        spacing = float(np.median(np.diff(src_times[indices])))
        window = max(3, int(round(0.18 / max(spacing, 0.002))))
        if window % 2 == 0:
            window += 1
        window = min(window, len(indices) if len(indices) % 2 == 1 else len(indices) - 1)
        window = max(3, window)
        centre = median_filter(ref_midi[indices], size=window, mode="nearest")

        target_notes = np.empty_like(centre)
        current_note = round(float(centre[0]))
        for offset, value in enumerate(centre):
            if abs(float(value) - current_note) >= 0.62:
                current_note = round(float(value))
            target_notes[offset] = current_note

        raw_drift = ref_midi[indices] - src_midi[indices]
        # 大幅分歧通常是八度或 F0 跟踪错误。让参考演唱引导转换后的声音，但不要把它硬拉到每一个检测到的半音上；这种强行贴音符中心的做法正是 Auto-Tune 质感的主要来源。
        trustworthy = np.abs(raw_drift) <= 0.65
        drift = np.where(trustworthy, np.clip(raw_drift, -0.55, 0.55), 0.0)
        intonation = np.clip(target_notes - centre, -0.35, 0.35)
        phrase_correction = amount * (0.90 * drift + 0.18 * intonation)
        max_shift = 0.50 * amount
        phrase_correction = np.clip(phrase_correction, -max_shift, max_shift)
        if len(indices) >= 5:
            phrase_correction = median_filter(
                phrase_correction,
                size=5,
                mode="nearest",
            )
        if len(indices) >= 7:
            phrase_correction = gaussian_filter1d(
                phrase_correction,
                sigma=max(1.0, 0.025 / max(spacing, 0.002)),
                mode="nearest",
            )
            # 在有声音节段边缘淡出校正，避免 PSOLA 在起音、辅音、呼吸或音符释放处突然进入或退出校正。
            fade_points = min(
                len(indices) // 2,
                max(2, int(round(0.06 / max(spacing, 0.002)))),
            )
            if fade_points > 1:
                ramp = np.sin(np.linspace(0.0, np.pi / 2.0, fade_points)) ** 2
                phrase_correction[:fade_points] *= ramp
                phrase_correction[-fade_points:] *= ramp[::-1]
        correction[indices] = phrase_correction

    corrected = _midi_to_hz(src_midi + correction)
    changed = np.abs(correction) >= 0.001
    cents = np.abs(correction[changed]) * 100.0
    return corrected, {
        "points": float(changed.sum()),
        "median_cents": float(np.median(cents)) if cents.size else 0.0,
        "max_cents": float(np.max(cents)) if cents.size else 0.0,
    }


def _estimate_envelope_lag(
    source: "np.ndarray",
    reference: "np.ndarray",
    sample_rate: int,
) -> tuple[float, float]:
    """基于 20 毫秒 RMS 包络估计参考音轨相对于源音轨的时延。"""
    import numpy as np
    from scipy.ndimage import uniform_filter1d

    length = min(len(source), len(reference))
    if length < sample_rate // 2:
        return 0.0, -1.0
    window = max(1, int(sample_rate * 0.02))
    hop = max(1, int(sample_rate * 0.01))

    def envelope(audio: "np.ndarray") -> "np.ndarray":
        power = uniform_filter1d(
            np.asarray(audio[:length], dtype=np.float64) ** 2,
            size=window,
            mode="nearest",
        )
        values = 10.0 * np.log10(np.maximum(power[::hop], 1e-10))
        return np.clip(values, float(values.max()) - 50.0, None)

    src_envelope = envelope(source)
    ref_envelope = envelope(reference)
    max_lag = 8
    best_lag = 0
    best_correlation = -1.0
    for lag in range(-max_lag, max_lag + 1):
        if lag > 0:
            src_part, ref_part = src_envelope[lag:], ref_envelope[:-lag]
        elif lag < 0:
            src_part, ref_part = src_envelope[:lag], ref_envelope[-lag:]
        else:
            src_part, ref_part = src_envelope, ref_envelope
        if len(src_part) < 20 or float(np.std(src_part) * np.std(ref_part)) < 1e-6:
            continue
        correlation = float(np.corrcoef(src_part, ref_part)[0, 1])
        if np.isfinite(correlation) and correlation > best_correlation:
            best_lag = lag
            best_correlation = correlation
    return best_lag * hop / sample_rate, best_correlation


def _suppress_reference_gap_residual(
    audio: "np.ndarray",
    reference: "np.ndarray",
    sample_rate: int,
    lag_seconds: float = 0.0,
) -> tuple["np.ndarray", dict[str, float]]:
    """衰减参考人声空隙中的短暂模型独有爆发。

    转换后的渲染可能会在参考轨真实的辅音空隙里保留一小段有声/噪声孤岛。这与音高修正是分开的：参考轨只控制短时电平，而有界且平滑的衰减能保留呼吸和乐句边界。
    """
    import numpy as np
    from scipy.ndimage import gaussian_filter1d, uniform_filter1d

    empty_stats = {
        "reference_gap_regions": 0.0,
        "reference_gap_seconds": 0.0,
        "reference_gap_max_attenuation_db": 0.0,
    }
    raw_audio = np.asarray(audio, dtype=np.float64)
    raw_reference = np.asarray(reference, dtype=np.float64)
    was_mono = raw_audio.ndim == 1
    data = raw_audio[np.newaxis, :] if was_mono else raw_audio
    guide = (
        raw_reference[np.newaxis, :]
        if raw_reference.ndim == 1
        else raw_reference
    )
    if data.ndim != 2 or guide.ndim != 2 or not data.shape[-1]:
        return raw_audio.copy(), empty_stats

    total_frames = int(data.shape[-1])
    guide_frames = int(guide.shape[-1])
    length = min(total_frames, guide_frames)
    allowed_delta = max(
        int(round(sample_rate * 0.050)),
        int(round(total_frames * 0.002)),
    )
    if (
        length < int(round(sample_rate * 0.20))
        or abs(total_frames - guide_frames) > allowed_delta
    ):
        return raw_audio.copy(), empty_stats

    source = np.mean(data[:, :length], axis=0)
    aligned_guide = guide[:, :length].copy()
    sample_shift = int(round(float(lag_seconds) * sample_rate))
    if sample_shift > 0:
        shifted = np.zeros_like(aligned_guide)
        if sample_shift < length:
            shifted[:, sample_shift:] = aligned_guide[:, : length - sample_shift]
        aligned_guide = shifted
    elif sample_shift < 0:
        shift = -sample_shift
        shifted = np.zeros_like(aligned_guide)
        if shift < length:
            shifted[:, : length - shift] = aligned_guide[:, shift:]
        aligned_guide = shifted
    guide_mono = np.mean(aligned_guide, axis=0)

    frame_size = max(
        32,
        int(round(sample_rate * _REFERENCE_GAP_FRAME_SECONDS)),
    )
    hop_size = max(
        1,
        int(round(sample_rate * _REFERENCE_GAP_HOP_SECONDS)),
    )
    positions = np.arange(0, length, hop_size, dtype=np.int64)
    if len(positions) < 12:
        return raw_audio.copy(), empty_stats

    source_power = uniform_filter1d(
        source * source,
        size=frame_size,
        mode="nearest",
    )[positions]
    guide_power = uniform_filter1d(
        guide_mono * guide_mono,
        size=frame_size,
        mode="nearest",
    )[positions]
    source_db = 10.0 * np.log10(np.maximum(source_power, 1e-12))
    guide_db = 10.0 * np.log10(np.maximum(guide_power, 1e-12))
    finite = np.isfinite(source_db) & np.isfinite(guide_db)
    if int(np.count_nonzero(finite)) < 12:
        return raw_audio.copy(), empty_stats

    guide_peak = float(np.percentile(guide_db[finite], 90.0))
    source_peak = float(np.percentile(source_db[finite], 90.0))
    guide_loud = finite & (guide_db >= guide_peak - 12.0)
    source_present = finite & (source_db >= source_peak - 20.0)
    joint = guide_loud & source_present
    if int(np.count_nonzero(joint)) < 12:
        return raw_audio.copy(), empty_stats
    level_offset = float(np.median(source_db[joint] - guide_db[joint]))
    excess_db = source_db - guide_db - level_offset
    candidate = (
        finite
        & (guide_db <= guide_peak - _REFERENCE_GAP_QUIET_DROP_DB)
        & source_present
        & (excess_db >= _REFERENCE_GAP_MIN_EXCESS_DB)
    )

    # 可以跨过一两帧不稳定的分析帧，但绝不跨越长停顿。
    for _ in range(2):
        bridge = (
            ~candidate
            & np.r_[False, candidate[:-1]]
            & np.r_[candidate[1:], False]
        )
        candidate |= bridge

    candidate_indices = np.flatnonzero(candidate)
    if not candidate_indices.size:
        return raw_audio.copy(), empty_stats
    split_at = np.flatnonzero(np.diff(candidate_indices) > 1)
    starts = np.r_[0, split_at + 1]
    ends = np.r_[split_at + 1, len(candidate_indices)]
    accepted = np.zeros(len(positions), dtype=bool)
    region_seconds = 0.0
    region_count = 0
    support_frames = max(
        2,
        int(round(_REFERENCE_GAP_SUPPORT_SECONDS * sample_rate / hop_size)),
    )
    for start, end in zip(starts, ends):
        run = candidate_indices[start:end]
        duration = float(
            positions[run[-1]] - positions[run[0]] + frame_size
        ) / max(sample_rate, 1)
        if not (
            _REFERENCE_GAP_MIN_SECONDS
            <= duration
            <= _REFERENCE_GAP_MAX_SECONDS
        ):
            continue
        before = guide_loud[max(0, int(run[0]) - support_frames) : int(run[0])]
        after = guide_loud[
            int(run[-1]) + 1 : min(len(guide_loud), int(run[-1]) + support_frames + 1)
        ]
        if int(np.count_nonzero(before)) < 2 or int(np.count_nonzero(after)) < 2:
            continue
        if float(np.max(excess_db[run])) < _REFERENCE_GAP_MIN_EXCESS_DB + 3.0:
            continue
        accepted[run] = True
        region_seconds += duration
        region_count += 1

    if not bool(accepted.any()):
        return raw_audio.copy(), empty_stats

    attenuation_db = np.clip(
        (excess_db - (_REFERENCE_GAP_MIN_EXCESS_DB - 3.0)) * 0.65,
        0.0,
        _REFERENCE_GAP_MAX_ATTENUATION_DB,
    )
    attenuation_db *= accepted.astype(np.float64)
    attenuation_db = gaussian_filter1d(
        attenuation_db,
        sigma=max(1.0, 0.008 / _REFERENCE_GAP_HOP_SECONDS),
        mode="nearest",
    )
    attenuation_db = np.clip(attenuation_db, 0.0, _REFERENCE_GAP_MAX_ATTENUATION_DB)
    attenuation_db[attenuation_db < 0.05] = 0.0
    sample_attenuation = np.interp(
        np.arange(total_frames, dtype=np.float64),
        positions.astype(np.float64),
        attenuation_db,
        left=0.0,
        right=0.0,
    )
    gain = np.power(10.0, -sample_attenuation / 20.0)
    processed = data.copy()
    processed[:, :length] *= gain[:length][np.newaxis, :]
    stats = {
        "reference_gap_regions": float(region_count),
        "reference_gap_seconds": float(region_seconds),
        "reference_gap_max_attenuation_db": float(np.max(attenuation_db)),
    }
    return (processed[0] if was_mono else processed), stats


def _alignment_feature(
    audio: "np.ndarray",
    sample_rate: int,
) -> tuple["np.ndarray", "np.ndarray", float]:
    """返回一个按约 100 Hz 采样的紧凑能量/起音特征。"""
    import numpy as np
    from scipy.ndimage import uniform_filter1d
    from scipy.signal import resample_poly

    analysis_rate = min(sample_rate, 2000)
    values = np.asarray(audio, dtype=np.float64)
    if sample_rate != analysis_rate:
        divisor = math.gcd(sample_rate, analysis_rate)
        values = resample_poly(
            values,
            analysis_rate // divisor,
            sample_rate // divisor,
        )
    window = max(1, int(round(analysis_rate * 0.04)))
    hop = max(1, int(round(analysis_rate * 0.01)))
    power = uniform_filter1d(values * values, size=window, mode="nearest")[::hop]
    level = 10.0 * np.log10(np.maximum(power, 1e-10))
    if not level.size:
        return level, np.zeros(0, dtype=bool), hop / analysis_rate

    ceiling = float(np.percentile(level, 90))
    floor = max(-60.0, ceiling - 45.0)
    level = np.clip(level, floor, ceiling + 3.0)
    active = level >= max(-50.0, ceiling - 30.0)
    centred = level - float(np.median(level))
    scale = float(np.std(centred[active])) if bool(active.any()) else 0.0
    if scale < 1e-4:
        scale = max(float(np.std(centred)), 1.0)
    energy = centred / scale
    onset = np.maximum(np.diff(energy, prepend=energy[0]), 0.0)
    onset_scale = float(np.percentile(onset, 95)) if onset.size else 0.0
    if onset_scale > 1e-4:
        onset = onset / onset_scale
    feature = 0.72 * energy + 0.28 * onset
    return feature, active, hop / analysis_rate


def _phonetic_feature(
    audio: "np.ndarray",
    sample_rate: int,
) -> tuple["np.ndarray", "np.ndarray", float]:
    """返回用于声学音素匹配的说话人归一化倒谱特征。"""
    import numpy as np
    from scipy.fft import dct, rfft
    from scipy.signal import resample_poly

    analysis_rate = min(sample_rate, 16000)
    values = np.asarray(audio, dtype=np.float32)
    if sample_rate != analysis_rate:
        divisor = math.gcd(sample_rate, analysis_rate)
        values = resample_poly(
            values,
            analysis_rate // divisor,
            sample_rate // divisor,
        ).astype(np.float32, copy=False)
    frame_length = max(64, int(round(analysis_rate * 0.025)))
    hop = max(1, int(round(analysis_rate * 0.010)))
    if len(values) < frame_length:
        values = np.pad(values, (0, frame_length - len(values)))
    frames = np.lib.stride_tricks.sliding_window_view(values, frame_length)[::hop]
    if not len(frames):
        return np.empty((0, 26), dtype=np.float32), np.zeros(0, dtype=bool), hop / analysis_rate

    window = np.hanning(frame_length).astype(np.float32)
    spectrum = np.abs(rfft(frames * window, axis=1)).astype(np.float32)
    power = spectrum * spectrum
    frame_power = np.mean(power, axis=1) + 1e-10
    level = 10.0 * np.log10(frame_power)
    ceiling = float(np.percentile(level, 90))
    active = level >= max(-55.0, ceiling - 32.0)

    frequencies = np.fft.rfftfreq(frame_length, 1.0 / analysis_rate)
    upper = min(7600.0, analysis_rate * 0.48)
    edges = np.geomspace(80.0, max(160.0, upper), 33)
    bands = np.empty((len(frames), len(edges) - 1), dtype=np.float32)
    for band_index, (low, high) in enumerate(zip(edges[:-1], edges[1:])):
        mask = (frequencies >= low) & (frequencies < high)
        if bool(mask.any()):
            bands[:, band_index] = np.log(np.mean(power[:, mask], axis=1) + 1e-8)
        else:
            bands[:, band_index] = 0.0
    cepstra = dct(bands, type=2, axis=1, norm="ortho")[:, 1:13].astype(np.float32)
    delta = np.gradient(cepstra, axis=0).astype(np.float32)
    normalized_level = (level - float(np.median(level))) / max(float(np.std(level)), 1.0)
    onset = np.maximum(np.diff(normalized_level, prepend=normalized_level[0]), 0.0)
    features = np.column_stack(
        [
            cepstra,
            0.65 * delta,
            0.35 * normalized_level,
            0.45 * onset,
        ]
    ).astype(np.float32)

    normalizer_rows = active if int(active.sum()) >= 10 else np.ones(len(active), dtype=bool)
    centre = np.median(features[normalizer_rows], axis=0)
    spread = np.median(np.abs(features[normalizer_rows] - centre), axis=0) * 1.4826
    spread = np.maximum(spread, 0.08)
    features = (features - centre) / spread
    norms = np.linalg.norm(features, axis=1, keepdims=True)
    features = features / np.maximum(norms, 1e-6)
    return features.astype(np.float32), active, hop / analysis_rate


def _phrase_spans(
    active: "np.ndarray",
    hop_seconds: float,
) -> list[tuple[int, int]]:
    """在保留词间停顿的同时，按类似句子的停顿拆分活动人声帧。"""
    import numpy as np

    indices = np.flatnonzero(np.asarray(active, dtype=bool))
    if not indices.size:
        return []
    pause_frames = max(2, int(round(0.28 / max(hop_seconds, 1e-4))))
    minimum_frames = max(3, int(round(0.35 / max(hop_seconds, 1e-4))))
    padding = max(1, int(round(0.06 / max(hop_seconds, 1e-4))))
    split_at = np.flatnonzero(np.diff(indices) > pause_frames)
    starts = np.r_[0, split_at + 1]
    ends = np.r_[split_at + 1, len(indices)]
    spans: list[tuple[int, int]] = []
    for start_index, end_index in zip(starts, ends):
        start = max(0, int(indices[start_index]) - padding)
        end = min(len(active), int(indices[end_index - 1]) + padding + 1)
        if end - start >= minimum_frames:
            spans.append((start, end))
    return spans


def _match_phrase_spans(
    source_spans: list[tuple[int, int]],
    reference_spans: list[tuple[int, int]],
    hop_seconds: float,
) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """使用位置和时长一致性单调配对乐句片段。"""
    import math as _math

    pairs: list[tuple[tuple[int, int], tuple[int, int]]] = []
    next_source = 0
    for reference_span in reference_spans:
        ref_start, ref_end = reference_span
        ref_centre = (ref_start + ref_end) * 0.5
        ref_duration = max(1, ref_end - ref_start)
        best_index = -1
        best_score = float("inf")
        for source_index in range(next_source, min(len(source_spans), next_source + 4)):
            src_start, src_end = source_spans[source_index]
            src_centre = (src_start + src_end) * 0.5
            src_duration = max(1, src_end - src_start)
            centre_delta = abs(src_centre - ref_centre) * hop_seconds
            if centre_delta > max(0.9, ref_duration * hop_seconds * 0.35):
                continue
            duration_cost = abs(_math.log(src_duration / ref_duration))
            score = centre_delta / max(0.20, ref_duration * hop_seconds) + 0.45 * duration_cost
            if score < best_score:
                best_score = score
                best_index = source_index
        if best_index >= 0 and best_score <= 0.85:
            pairs.append((source_spans[best_index], reference_span))
            next_source = best_index + 1
    return pairs


def _banded_phonetic_dtw(
    source_features: "np.ndarray",
    reference_features: "np.ndarray",
    band_frames: int,
) -> tuple["np.ndarray", "np.ndarray", "np.ndarray"]:
    """返回带单调和斜率约束的 DTW 路径，以及每个锚点的相似度。"""
    import numpy as np

    source_count = len(source_features)
    reference_count = len(reference_features)
    if source_count < 3 or reference_count < 3:
        empty = np.zeros(0, dtype=np.int32)
        return empty, empty, np.zeros(0, dtype=np.float32)
    costs = np.full((source_count + 1, reference_count + 1), np.inf, dtype=np.float32)
    back = np.zeros((source_count + 1, reference_count + 1), dtype=np.uint8)
    costs[0, 0] = 0.0
    insertion_penalty = 0.035
    band = max(band_frames, abs(source_count - reference_count) + 3)

    for source_index in range(1, source_count + 1):
        expected = 1 + int(round((source_index - 1) * (reference_count - 1) / max(source_count - 1, 1)))
        low = max(1, expected - band)
        high = min(reference_count, expected + band)
        source_vector = source_features[source_index - 1]
        for reference_index in range(low, high + 1):
            similarity = float(np.dot(source_vector, reference_features[reference_index - 1]))
            local_cost = 1.0 - float(np.clip(similarity, -1.0, 1.0))
            options = (
                costs[source_index - 1, reference_index - 1],
                costs[source_index - 1, reference_index] + insertion_penalty,
                costs[source_index, reference_index - 1] + insertion_penalty,
            )
            direction = int(np.argmin(options))
            best = options[direction]
            if np.isfinite(best):
                costs[source_index, reference_index] = best + local_cost
                back[source_index, reference_index] = direction + 1

    if not np.isfinite(costs[source_count, reference_count]):
        empty = np.zeros(0, dtype=np.int32)
        return empty, empty, np.zeros(0, dtype=np.float32)
    source_path: list[int] = []
    reference_path: list[int] = []
    source_index = source_count
    reference_index = reference_count
    while source_index > 0 and reference_index > 0:
        source_path.append(source_index - 1)
        reference_path.append(reference_index - 1)
        direction = int(back[source_index, reference_index])
        if direction == 1:
            source_index -= 1
            reference_index -= 1
        elif direction == 2:
            source_index -= 1
        elif direction == 3:
            reference_index -= 1
        else:
            break
    source_indices = np.asarray(source_path[::-1], dtype=np.int32)
    reference_indices = np.asarray(reference_path[::-1], dtype=np.int32)
    if not len(source_indices):
        return source_indices, reference_indices, np.zeros(0, dtype=np.float32)
    similarities = np.sum(
        source_features[source_indices] * reference_features[reference_indices],
        axis=1,
    ).astype(np.float32)
    return source_indices, reference_indices, similarities


def _phonetic_alignment_anchors(
    source: "np.ndarray",
    reference: "np.ndarray",
    sample_rate: int,
) -> tuple[list[float], list[float], list[float], int]:
    """从乐句和音素匹配中构建高置信度的源/参考锚点。"""
    import numpy as np

    source_features, source_active, hop_seconds = _phonetic_feature(source, sample_rate)
    reference_features, reference_active, _ = _phonetic_feature(reference, sample_rate)
    frame_count = min(len(source_features), len(reference_features))
    if frame_count < 100:
        return [], [], [], 0
    source_features = source_features[:frame_count]
    reference_features = reference_features[:frame_count]
    source_active = source_active[:frame_count]
    reference_active = reference_active[:frame_count]
    phrase_pairs = _match_phrase_spans(
        _phrase_spans(source_active, hop_seconds),
        _phrase_spans(reference_active, hop_seconds),
        hop_seconds,
    )
    source_anchors: list[float] = []
    target_anchors: list[float] = []
    confidence: list[float] = []
    anchor_step = max(10, int(round(0.30 / hop_seconds)))
    band_frames = max(8, int(round(0.16 / hop_seconds)))

    for source_span, reference_span in phrase_pairs:
        source_start, source_end = source_span
        reference_start, reference_end = reference_span
        source_length = source_end - source_start
        reference_length = reference_end - reference_start
        chunk_count = max(1, int(math.ceil(max(source_length, reference_length) / 1200)))
        for chunk_index in range(chunk_count):
            src_low = source_start + int(round(source_length * chunk_index / chunk_count))
            src_high = source_start + int(round(source_length * (chunk_index + 1) / chunk_count))
            ref_low = reference_start + int(round(reference_length * chunk_index / chunk_count))
            ref_high = reference_start + int(round(reference_length * (chunk_index + 1) / chunk_count))
            src_path, ref_path, path_similarity = _banded_phonetic_dtw(
                source_features[src_low:src_high],
                reference_features[ref_low:ref_high],
                band_frames,
            )
            if len(src_path) < 5 or float(np.median(path_similarity)) < 0.20:
                continue
            mapping = np.full(src_high - src_low, np.nan, dtype=np.float64)
            similarity_map = np.full(src_high - src_low, -1.0, dtype=np.float64)
            for source_offset in np.unique(src_path):
                matched = ref_path[src_path == source_offset]
                matched_similarity = path_similarity[src_path == source_offset]
                mapping[source_offset] = float(np.median(matched))
                similarity_map[source_offset] = float(np.median(matched_similarity))
            valid_mapping = np.flatnonzero(np.isfinite(mapping))
            if len(valid_mapping) < 3:
                continue
            mapping = np.interp(np.arange(len(mapping)), valid_mapping, mapping[valid_mapping])
            valid_similarity = np.flatnonzero(similarity_map >= -0.99)
            similarity_map = np.interp(
                np.arange(len(similarity_map)),
                valid_similarity,
                similarity_map[valid_similarity],
            )
            for source_offset in range(anchor_step // 2, len(mapping), anchor_step):
                reference_offset = int(round(mapping[source_offset]))
                source_frame = src_low + source_offset
                reference_frame = ref_low + reference_offset
                if not (0 <= reference_frame < frame_count):
                    continue
                if not source_active[source_frame] or not reference_active[reference_frame]:
                    continue
                similarity = float(similarity_map[source_offset])
                if similarity < 0.25:
                    continue
                source_time = source_frame * hop_seconds
                reference_time = reference_frame * hop_seconds
                if abs(source_time - reference_time) > 0.25:
                    continue
                source_anchors.append(source_time)
                target_anchors.append(reference_time)
                confidence.append((similarity + 1.0) * 0.5)
    return source_anchors, target_anchors, confidence, len(phrase_pairs)


def _local_alignment_map(
    source: "np.ndarray",
    reference: "np.ndarray",
    sample_rate: int,
    strength: float,
) -> tuple[
    "np.ndarray",
    "np.ndarray",
    "np.ndarray",
    "np.ndarray",
    "np.ndarray",
    dict[str, float],
]:
    """基于局部人声事件估计一个受限的源到参考时序映射。

    返回的因子适合 Praat DurationTier。端点固定，以便对齐后的主唱保留源时长并保持与混音对齐。
    """
    import numpy as np

    amount = float(np.clip(strength, 0.0, 1.0))
    duration = len(source) / max(sample_rate, 1)
    empty_stats = {
        "alignment_points": 0.0,
        "median_alignment_ms": 0.0,
        "max_alignment_ms": 0.0,
        "alignment_correlation": -1.0,
        "max_stretch_percent": 0.0,
        "phrase_pairs": 0.0,
        "phoneme_points": 0.0,
        "guide_points": 0.0,
    }
    if amount <= 0.0 or duration < 1.0:
        return (
            np.asarray([0.0, duration]),
            np.asarray([0.0, duration]),
            np.asarray([1.0]),
            np.asarray([0.0, duration]),
            np.asarray([0.0, duration]),
            empty_stats,
        )

    source_anchors, target_anchors, correlations, phrase_pair_count = (
        _phonetic_alignment_anchors(source, reference, sample_rate)
    )
    phoneme_point_count = len(source_anchors)
    if len(source_anchors) < 3:
        src_feature, src_active, hop_seconds = _alignment_feature(source, sample_rate)
        ref_feature, ref_active, _ = _alignment_feature(reference, sample_rate)
        frame_count = min(len(src_feature), len(ref_feature))
        src_feature = src_feature[:frame_count]
        ref_feature = ref_feature[:frame_count]
        src_active = src_active[:frame_count]
        ref_active = ref_active[:frame_count]
        half_window = max(20, int(round(0.42 / hop_seconds)))
        search = max(4, int(round(0.12 / hop_seconds)))
        anchor_step = max(half_window, int(round(0.75 / hop_seconds)))
        centres = range(
            half_window + search,
            frame_count - half_window - search,
            anchor_step,
        )
        source_anchors = []
        target_anchors = []
        correlations = []
        for centre in centres:
            ref_slice = slice(centre - half_window, centre + half_window + 1)
            if float(np.mean(ref_active[ref_slice])) < 0.18:
                continue
            ref_part = ref_feature[ref_slice]
            best_lag = 0
            best_score = -1.0
            for lag_frames in range(-search, search + 1):
                src_start = centre - half_window + lag_frames
                src_stop = centre + half_window + lag_frames + 1
                src_part = src_feature[src_start:src_stop]
                src_voice = src_active[src_start:src_stop]
                if len(src_part) != len(ref_part) or float(np.mean(src_voice)) < 0.18:
                    continue
                if float(np.std(src_part) * np.std(ref_part)) < 1e-5:
                    continue
                score = float(np.corrcoef(src_part, ref_part)[0, 1])
                if np.isfinite(score) and score > best_score:
                    best_score = score
                    best_lag = lag_frames
            if best_score < 0.42:
                continue
            lag_seconds = best_lag * hop_seconds
            source_time = centre * hop_seconds + lag_seconds
            if source_time <= 0.0 or source_time >= duration:
                continue
            source_anchors.append(source_time)
            target_anchors.append(centre * hop_seconds)
            correlations.append(best_score)

    if len(source_anchors) < 3:
        return (
            np.asarray([0.0, duration]),
            np.asarray([0.0, duration]),
            np.asarray([1.0]),
            np.asarray([0.0, duration]),
            np.asarray([0.0, duration]),
            empty_stats,
        )

    anchor_times = np.asarray(source_anchors, dtype=np.float64)
    raw_lags = anchor_times - np.asarray(target_anchors, dtype=np.float64)
    # 只在相邻锚点之间平滑，避免停顿把前一个元音的时序偏移带到下一句。
    lag_values = raw_lags.copy()
    for anchor_index, anchor_time in enumerate(anchor_times):
        neighborhood = np.abs(anchor_times - anchor_time) <= 0.90
        if int(neighborhood.sum()) >= 3:
            lag_values[anchor_index] = float(np.median(raw_lags[neighborhood]))

    # 即使音频本身没有被拉伸，也保留一张稠密、平滑的音素映射供后续 F0 查找。这样能保留上一版有用的局部音高对应关系，而不会把持续移动的 DurationTier 强加给元音。
    guide_source_points = anchor_times.copy()
    guide_target_points = guide_source_points - amount * lag_values
    guide_order = np.argsort(guide_source_points)
    guide_source_points = guide_source_points[guide_order]
    guide_target_points = guide_target_points[guide_order]
    guide_keep = np.r_[True, np.diff(guide_source_points) >= 0.10]
    guide_source_points = np.r_[0.0, guide_source_points[guide_keep], duration]
    guide_target_points = np.r_[0.0, guide_target_points[guide_keep], duration]
    guide_target_points = np.clip(guide_target_points, 0.0, duration)
    guide_gap = min(0.005, duration / max(4.0 * (len(guide_target_points) - 1), 1.0))
    for guide_index in range(1, len(guide_target_points) - 1):
        guide_target_points[guide_index] = max(
            guide_target_points[guide_index],
            guide_target_points[guide_index - 1] + guide_gap,
        )
    for guide_index in range(len(guide_target_points) - 2, 0, -1):
        guide_target_points[guide_index] = min(
            guide_target_points[guide_index],
            guide_target_points[guide_index + 1] - guide_gap,
        )
    guide_target_points[0] = 0.0
    guide_target_points[-1] = duration
    empty_stats["guide_points"] = float(max(0, len(guide_source_points) - 2))

    # 在持续元音上，微小拉伸比一点点时序误差更容易被听出来。保留所有匹配用于诊断，但只为连续的、具有意义的偏移创建 DurationTier：原始偏移大于 25 毫秒，且在应用用户强度后至少达到 8 毫秒。
    lag_dead_zone = 0.025
    lag_values = np.sign(lag_values) * np.maximum(
        np.abs(lag_values) - lag_dead_zone,
        0.0,
    )
    applied_lags = amount * lag_values
    meaningful = np.abs(applied_lags) >= 0.008
    supported = np.zeros(len(lag_values), dtype=bool)
    for anchor_index, anchor_time in enumerate(anchor_times):
        if not meaningful[anchor_index]:
            continue
        neighborhood = np.abs(anchor_times - anchor_time) <= 1.80
        same_direction = np.sign(applied_lags) == np.sign(applied_lags[anchor_index])
        supported[anchor_index] = int(np.count_nonzero(neighborhood & meaningful & same_direction)) >= 3
    lag_values = np.where(supported, lag_values, 0.0)
    if int(supported.sum()) < 3:
        empty_stats["alignment_correlation"] = float(np.median(correlations))
        empty_stats["phrase_pairs"] = float(phrase_pair_count)
        empty_stats["phoneme_points"] = float(phoneme_point_count)
        return (
            np.asarray([0.0, duration]),
            np.asarray([0.0, duration]),
            np.asarray([1.0]),
            guide_source_points,
            guide_target_points,
            empty_stats,
        )
    source_points = np.asarray(source_anchors, dtype=np.float64)
    target_points = source_points - amount * lag_values
    source_points = np.r_[0.0, source_points, duration]
    target_points = np.r_[0.0, target_points, duration]

    order = np.argsort(source_points)
    source_points = source_points[order]
    target_points = target_points[order]
    keep = np.r_[True, np.diff(source_points) >= 0.10]
    source_points = source_points[keep]
    target_points = target_points[keep]
    source_delta = np.diff(source_points)
    desired_factors = np.diff(target_points) / np.maximum(source_delta, 1e-6)
    # 持续元音会把局部时序扭曲暴露成颤动/扇形伪影。保留参考映射用于音高对应，但把实际 DurationTier 限制在 2%，这样 SVC/RVC/SeedVC 渲染就能保持相位稳定并与混音对齐。
    max_stretch = 0.020
    factors = np.clip(desired_factors, 1.0 - max_stretch, 1.0 + max_stretch)

    # 在裁剪后保留完整时长。只在仍有余量的区间里分配残差，这样声明的拉伸上限仍然严格成立。
    weighted_mean = float(np.sum(factors * source_delta) / max(duration, 1e-6))
    if weighted_mean > 1e-6:
        factors = factors / weighted_mean
    factors = np.clip(factors, 1.0 - max_stretch, 1.0 + max_stretch)
    for _ in range(4):
        residual = duration - float(np.sum(factors * source_delta))
        if abs(residual) <= 1e-8:
            break
        if residual > 0.0:
            adjustable = factors < (1.0 + max_stretch - 1e-9)
        else:
            adjustable = factors > (1.0 - max_stretch + 1e-9)
        weight = float(np.sum(source_delta[adjustable]))
        if weight <= 1e-9:
            break
        factors[adjustable] += residual / weight
        factors = np.clip(factors, 1.0 - max_stretch, 1.0 + max_stretch)
    target_points = np.r_[0.0, np.cumsum(factors * source_delta)]
    target_points[-1] = duration

    applied_lag = source_points[1:-1] - target_points[1:-1]
    stats = {
        "alignment_points": float(len(source_points) - 2),
        "median_alignment_ms": float(np.median(np.abs(applied_lag)) * 1000.0),
        "max_alignment_ms": float(np.max(np.abs(applied_lag)) * 1000.0),
        "alignment_correlation": float(np.median(correlations)),
        "max_stretch_percent": float(np.max(np.abs(factors - 1.0)) * 100.0),
        "phrase_pairs": float(phrase_pair_count),
        "phoneme_points": float(phoneme_point_count),
        "guide_points": float(max(0, len(guide_source_points) - 2)),
    }
    return (
        source_points,
        target_points,
        factors,
        guide_source_points,
        guide_target_points,
        stats,
    )


def _replace_duration_tier(
    manipulation,
    source_points: "np.ndarray",
    factors: "np.ndarray",
    praat_call,
) -> None:
    """将受限的局部时序曲线附加到 Praat Manipulation 对象上。"""
    tier = praat_call(
        "Create DurationTier",
        "xb-ai-alignment",
        float(source_points[0]),
        float(source_points[-1]),
    )
    midpoints = (source_points[:-1] + source_points[1:]) * 0.5
    for time_value, factor in zip(midpoints, factors):
        praat_call(tier, "Add point", float(time_value), float(factor))
    praat_call([tier, manipulation], "Replace duration tier")


def _tier_points(tier, praat_call) -> tuple["np.ndarray", "np.ndarray"]:
    import numpy as np

    count = int(praat_call(tier, "Get number of points"))
    times = np.empty(count, dtype=np.float64)
    frequencies = np.empty(count, dtype=np.float64)
    for index in range(1, count + 1):
        times[index - 1] = float(praat_call(tier, "Get time from index", index))
        frequencies[index - 1] = float(
            praat_call(tier, "Get value at index", index)
        )
    return times, frequencies


def _stable_pitch_resynthesis_regions(
    pitch_times: "np.ndarray",
    source_frequencies: "np.ndarray",
    corrected_frequencies: "np.ndarray",
    strength: float,
) -> list[tuple[float, float]]:
    """选择完整、连贯的校正叶片，而不是短小的 PSOLA 孤岛。"""
    import numpy as np
    from scipy.ndimage import gaussian_filter1d, median_filter

    times = np.asarray(pitch_times, dtype=np.float64)
    source_hz = np.asarray(source_frequencies, dtype=np.float64)
    corrected_hz = np.asarray(corrected_frequencies, dtype=np.float64)
    amount = float(np.clip(strength, 0.0, 1.0))
    count = min(len(times), len(source_hz), len(corrected_hz))
    if amount <= 0.0 or count < _MIN_RESYNTHESIS_PITCH_POINTS:
        return []

    times = times[:count]
    source_hz = source_hz[:count]
    corrected_hz = corrected_hz[:count]
    valid = (
        np.isfinite(times)
        & np.isfinite(source_hz)
        & np.isfinite(corrected_hz)
        & (source_hz > 0.0)
        & (corrected_hz > 0.0)
    )
    applied_cents = np.zeros(count, dtype=np.float64)
    applied_cents[valid] = 1200.0 * np.log2(
        corrected_hz[valid] / source_hz[valid]
    )
    target_cents = applied_cents / amount

    valid_indices = np.flatnonzero(valid)
    if valid_indices.size < _MIN_RESYNTHESIS_PITCH_POINTS:
        return []
    phrase_splits = np.flatnonzero(
        (np.diff(valid_indices) > 1)
        | (np.diff(times[valid_indices]) > 0.055)
    )
    phrase_starts = np.r_[0, phrase_splits + 1]
    phrase_ends = np.r_[phrase_splits + 1, len(valid_indices)]

    regions: list[tuple[float, float]] = []
    for phrase_start, phrase_end in zip(phrase_starts, phrase_ends):
        phrase = valid_indices[phrase_start:phrase_end]
        if len(phrase) < _MIN_RESYNTHESIS_PITCH_POINTS:
            continue
        phrase_times = times[phrase]
        spacing_values = np.diff(phrase_times)
        spacing_values = spacing_values[spacing_values > 1e-6]
        if not spacing_values.size:
            continue
        spacing = float(np.median(spacing_values))
        smooth_sigma = max(
            1.0,
            _RESYNTHESIS_PITCH_SMOOTH_SECONDS / max(spacing, 0.002),
        )
        smoothed_target = gaussian_filter1d(
            target_cents[phrase],
            sigma=smooth_sigma,
            mode="nearest",
        )

        supported = np.flatnonzero(
            np.abs(smoothed_target) >= _RESYNTHESIS_PITCH_SUPPORT_CENTS
        )
        if not supported.size:
            continue
        support_splits = np.flatnonzero(
            (np.diff(supported) > 1)
            | (np.diff(phrase_times[supported]) > 0.055)
            | (
                np.sign(smoothed_target[supported][1:])
                != np.sign(smoothed_target[supported][:-1])
            )
        )
        support_starts = np.r_[0, support_splits + 1]
        support_ends = np.r_[support_splits + 1, len(supported)]
        for support_start, support_end in zip(support_starts, support_ends):
            lobe = supported[support_start:support_end]
            if (
                len(lobe) < _MIN_RESYNTHESIS_PITCH_POINTS
                or float(phrase_times[lobe[-1]] - phrase_times[lobe[0]])
                < _MIN_RESYNTHESIS_PITCH_SECONDS
            ):
                continue

            lobe_times = phrase_times[lobe]
            # 不要让重叠相加窗口跨过真实的 F0 空洞。上面的更宽松乐句拆分会为音高匹配有意容忍短词间隙，但这种容忍对局部 PSOLA 并不安全。
            if (
                len(lobe_times) > 1
                and float(np.max(np.diff(lobe_times)))
                > _RESYNTHESIS_MAX_INTERNAL_GAP_SECONDS
            ):
                continue

            # 在“请求的”差值上，一个校正叶片可能很长且连贯，但源音轨本身可能正在音符之间滑动。用单一局部遮罩去重合成这条轮廓，正是剩余的颤动/卡片状伪影来源。用短中值滤波忽略单帧跟踪尖峰，然后只拒绝大范围移动或持续斜坡。
            source_midi = _hz_to_midi(source_hz[phrase[lobe]])
            if len(source_midi) >= 3:
                filter_size = min(5, len(source_midi))
                if filter_size % 2 == 0:
                    filter_size -= 1
                stable_source_midi = median_filter(
                    source_midi,
                    size=max(3, filter_size),
                    mode="nearest",
                )
            else:
                stable_source_midi = source_midi
            robust_span = float(
                np.percentile(stable_source_midi, 95.0)
                - np.percentile(stable_source_midi, 5.0)
            )
            if robust_span > _RESYNTHESIS_MAX_SOURCE_PITCH_SPAN_SEMITONES:
                continue
            if len(lobe_times) >= 3:
                time_offset = lobe_times - float(lobe_times[0])
                time_centre = time_offset - float(np.mean(time_offset))
                denominator = float(np.dot(time_centre, time_centre))
                if denominator > 1e-9:
                    slope = float(
                        np.dot(
                            time_centre,
                            stable_source_midi
                            - float(np.mean(stable_source_midi)),
                        )
                        / denominator
                    )
                    if (
                        abs(slope)
                        > _RESYNTHESIS_MAX_SOURCE_PITCH_SLOPE_SEMITONES_PER_SECOND
                    ):
                        continue

            lobe_peak = float(np.max(np.abs(smoothed_target[lobe])))
            if (
                lobe_peak < _RESYNTHESIS_PITCH_SEED_CENTS
                or lobe_peak * amount < _MIN_APPLIED_RESYNTHESIS_PITCH_CENTS
            ):
                continue

            direction = float(np.sign(np.median(smoothed_target[lobe])))
            if direction == 0.0:
                continue
            raw_lobe = target_cents[phrase[lobe]]
            coherent = np.flatnonzero(
                raw_lobe * direction >= _RESYNTHESIS_PITCH_SUPPORT_CENTS
            )
            opposed = np.flatnonzero(
                raw_lobe * direction <= -_RESYNTHESIS_PITCH_SUPPORT_CENTS
            )
            if (
                len(coherent) < _MIN_RESYNTHESIS_PITCH_POINTS
                or float(
                    phrase_times[lobe[coherent[-1]]]
                    - phrase_times[lobe[coherent[0]]]
                )
                < _MIN_RESYNTHESIS_PITCH_SECONDS
                or len(opposed) > 0.20 * (len(coherent) + len(opposed))
            ):
                continue

            # 从可靠叶片向接近零交叉的位置扩展。这样 PSOLA 会在完整的校正叶片上进入和退出，而不是在持续元音中间反复交叉淡化。
            left = int(lobe[0])
            while (
                left > 0
                and float(phrase_times[left] - phrase_times[left - 1])
                <= _RESYNTHESIS_MAX_INTERNAL_GAP_SECONDS
                and smoothed_target[left - 1] * direction > 0.0
                and abs(float(smoothed_target[left - 1]))
                >= _RESYNTHESIS_PITCH_RELEASE_CENTS
            ):
                left -= 1
            right = int(lobe[-1])
            while (
                right + 1 < len(phrase)
                and float(phrase_times[right + 1] - phrase_times[right])
                <= _RESYNTHESIS_MAX_INTERNAL_GAP_SECONDS
                and smoothed_target[right + 1] * direction > 0.0
                and abs(float(smoothed_target[right + 1]))
                >= _RESYNTHESIS_PITCH_RELEASE_CENTS
            ):
                right += 1
            final_times = phrase_times[left : right + 1]
            if (
                len(final_times) > 1
                and float(np.max(np.diff(final_times)))
                > _RESYNTHESIS_MAX_INTERNAL_GAP_SECONDS
            ):
                continue
            regions.append(
                (
                    float(phrase_times[left]) - 0.010,
                    float(phrase_times[right]) + 0.010,
                )
            )
    return regions


def _resynthesis_region_curve(
    original: "np.ndarray",
    sample_rate: int,
    *,
    pitch_times: "np.ndarray | None" = None,
    source_frequencies: "np.ndarray | None" = None,
    corrected_frequencies: "np.ndarray | None" = None,
    pitch_strength: float = 1.0,
    duration_source_points: "np.ndarray | None" = None,
    duration_factors: "np.ndarray | None" = None,
) -> "np.ndarray":
    """只在请求了可感知的音高或时序变化的位置混合 PSOLA。

    Praat 重合成即使音高点不变也会改变相位。因此声活动遮罩会替换掉过多干净渲染。下面的遮罩完全由请求的音高差值和 DurationTier 因子驱动，并在边界处加上短淡入淡出。
    """
    import numpy as np

    audio = np.asarray(original, dtype=np.float64)
    if audio.ndim == 1:
        audio = audio[np.newaxis, :]
    total_frames = audio.shape[-1]
    if total_frames == 0:
        return np.zeros(0, dtype=np.float64)

    regions: list[tuple[float, float]] = []
    if (
        pitch_times is not None
        and source_frequencies is not None
        and corrected_frequencies is not None
    ):
        regions.extend(
            _stable_pitch_resynthesis_regions(
                pitch_times,
                source_frequencies,
                corrected_frequencies,
                pitch_strength,
            )
        )

    if duration_source_points is not None and duration_factors is not None:
        source_points = np.asarray(duration_source_points, dtype=np.float64)
        factors = np.asarray(duration_factors, dtype=np.float64)
        interval_count = min(len(factors), max(0, len(source_points) - 1))
        if interval_count:
            source_points = source_points[: interval_count + 1]
            factors = factors[:interval_count]
            changed = np.flatnonzero(
                np.isfinite(factors) & (np.abs(factors - 1.0) >= 0.005)
            )
            for index in changed:
                regions.append(
                    (
                        float(source_points[index]) - 0.015,
                        float(source_points[index + 1]) + 0.015,
                    )
                )

    sample_regions: list[tuple[int, int]] = []
    for start, end in regions:
        start_frame = max(0, min(total_frames, int(math.floor(start * sample_rate))))
        end_frame = max(0, min(total_frames, int(math.ceil(end * sample_rate))))
        if end_frame > start_frame:
            sample_regions.append((start_frame, end_frame))
    if not sample_regions:
        return np.zeros(total_frames, dtype=np.float64)

    sample_regions.sort()
    bridge = max(1, int(round(0.020 * sample_rate)))
    merged: list[list[int]] = []
    for start, end in sample_regions:
        if merged and start <= merged[-1][1] + bridge:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    curve = np.zeros(total_frames, dtype=np.float64)
    fade = max(1, int(round(_RESYNTHESIS_CROSSFADE_SECONDS * sample_rate)))
    for start, end in merged:
        curve[start:end] = 1.0
        left = max(0, start - fade)
        if start > left:
            curve[left:start] = np.maximum(
                curve[left:start],
                np.sin(np.linspace(0.0, np.pi / 2.0, start - left, endpoint=False))
                ** 2,
            )
        right = min(total_frames, end + fade)
        if right > end:
            curve[end:right] = np.maximum(
                curve[end:right],
                np.cos(np.linspace(0.0, np.pi / 2.0, right - end, endpoint=False))
                ** 2,
            )
    curve[curve < 1e-8] = 0.0
    return curve


def _blend_resynthesis(
    original: "np.ndarray",
    tuned: "np.ndarray",
    mix: "np.ndarray",
    sample_rate: int,
) -> "np.ndarray":
    """交叉淡化 PSOLA，同时避免相位抵消造成的短暂电平空洞。"""
    import numpy as np
    from scipy.ndimage import gaussian_filter1d, uniform_filter1d

    dry = np.asarray(original, dtype=np.float64)
    wet = np.asarray(tuned, dtype=np.float64)
    curve = np.clip(np.asarray(mix, dtype=np.float64).reshape(-1), 0.0, 1.0)
    if dry.ndim == 1:
        dry = dry[np.newaxis, :]
    if wet.ndim == 1:
        wet = wet[np.newaxis, :]
    if dry.shape != wet.shape or dry.shape[-1] != len(curve):
        raise ValueError("PSOLA 混合输入尺寸不一致")

    blended = dry + (wet - dry) * curve[np.newaxis, :]
    transition = np.flatnonzero((curve > 1e-8) & (curve < 1.0 - 1e-8))
    if not transition.size:
        return blended

    split_at = np.flatnonzero(np.diff(transition) > 1)
    starts = np.r_[0, split_at + 1]
    ends = np.r_[split_at + 1, len(transition)]
    power_window = max(
        8,
        int(round(_RESYNTHESIS_CROSSFADE_POWER_SECONDS * sample_rate)),
    )
    smooth_sigma = max(1.0, 0.0015 * sample_rate)
    pad = power_window + int(math.ceil(smooth_sigma * 4.0))
    max_gain = 10.0 ** (_MAX_RESYNTHESIS_CROSSFADE_GAIN_DB / 20.0)

    for run_start, run_end in zip(starts, ends):
        run = transition[run_start:run_end]
        start = int(run[0])
        end = int(run[-1]) + 1
        local_start = max(0, start - pad)
        local_end = min(len(curve), end + pad)
        local_curve = curve[local_start:local_end]
        local_dry = dry[:, local_start:local_end]
        local_wet = wet[:, local_start:local_end]
        local_blend = blended[:, local_start:local_end]
        dry_power = uniform_filter1d(
            np.mean(local_dry * local_dry, axis=0),
            size=power_window,
            mode="nearest",
        )
        wet_power = uniform_filter1d(
            np.mean(local_wet * local_wet, axis=0),
            size=power_window,
            mode="nearest",
        )
        blend_power = uniform_filter1d(
            np.mean(local_blend * local_blend, axis=0),
            size=power_window,
            mode="nearest",
        )
        target_power = (1.0 - local_curve) * dry_power + local_curve * wet_power
        gain = np.sqrt((target_power + 1e-12) / (blend_power + 1e-12))
        gain = np.clip(gain, 1.0, max_gain)
        gain = gaussian_filter1d(gain, sigma=smooth_sigma, mode="nearest")
        # 在两端以及完全湿润的区域内保持单位增益。
        gain = 1.0 + (gain - 1.0) * 4.0 * local_curve * (1.0 - local_curve)
        offset_start = start - local_start
        offset_end = end - local_start
        blended[:, start:end] *= gain[offset_start:offset_end][np.newaxis, :]
    return blended


def _restore_resynthesis_channels(
    original: "np.ndarray",
    tuned: "np.ndarray",
) -> "np.ndarray":
    """把 Praat 的单声道重合成恢复到源声道布局，同时保留侧声道。"""
    import numpy as np

    dry = np.asarray(original, dtype=np.float64)
    wet = np.asarray(tuned, dtype=np.float64)
    if dry.ndim == 1:
        dry = dry[np.newaxis, :]
    if wet.ndim == 1:
        wet = wet[np.newaxis, :]
    if dry.ndim != 2 or wet.ndim != 2 or dry.shape[-1] != wet.shape[-1]:
        raise ValueError("PSOLA 声道恢复输入尺寸不一致")
    if dry.shape[0] == wet.shape[0]:
        return wet
    if wet.shape[0] == 1:
        dry_mid = np.mean(dry, axis=0, keepdims=True)
        return wet + (dry - dry_mid)
    if dry.shape[0] == 1:
        return np.mean(wet, axis=0, keepdims=True)
    raise ValueError("PSOLA 重合成声道数不受支持")


def tune(
    source: Path,
    reference: Path,
    output: Path,
    strength: float,
    alignment_strength: float,
) -> dict[str, float]:
    try:
        import numpy as np
        import parselmouth
        import soundfile as sf
        from parselmouth.praat import call
    except ImportError as exc:
        raise RuntimeError("Praat/Parselmouth 未安装，请修复 SVC 环境") from exc

    if not source.is_file() or not reference.is_file():
        raise RuntimeError("自然修音输入或旋律参考不存在")
    output.parent.mkdir(parents=True, exist_ok=True)

    source_sound = parselmouth.Sound(str(source))
    reference_sound = parselmouth.Sound(str(reference))
    sample_rate = int(round(source_sound.sampling_frequency))
    if int(round(reference_sound.sampling_frequency)) != sample_rate:
        reference_sound = reference_sound.resample(sample_rate, 50)

    source_mono = np.mean(source_sound.values, axis=0)
    reference_mono = np.mean(reference_sound.values, axis=0)
    lag, correlation = _estimate_envelope_lag(
        source_mono,
        reference_mono,
        sample_rate,
    )
    if correlation < 0.25:
        shutil.copy2(source, output)
        return {
            "points": 0.0,
            "median_cents": 0.0,
            "max_cents": 0.0,
            "lag_ms": lag * 1000.0,
            "correlation": correlation,
            "alignment_points": 0.0,
            "median_alignment_ms": 0.0,
            "max_alignment_ms": 0.0,
            "alignment_correlation": correlation,
            "max_stretch_percent": 0.0,
            "phrase_pairs": 0.0,
            "phoneme_points": 0.0,
            "guide_points": 0.0,
        }

    source_manipulation = call(
        source_sound,
        "To Manipulation",
        0.01,
        55.0,
        1800.0,
    )
    (
        duration_source_points,
        _duration_target_points,
        duration_factors,
        guide_source_points,
        guide_target_points,
        alignment_stats,
    ) = _local_alignment_map(
        source_mono,
        reference_mono,
        sample_rate,
        alignment_strength,
    )
    if alignment_stats["alignment_points"] >= 3:
        _replace_duration_tier(
            source_manipulation,
            duration_source_points,
            duration_factors,
            call,
        )
    reference_manipulation = call(
        reference_sound,
        "To Manipulation",
        0.01,
        55.0,
        1800.0,
    )
    source_tier = call(source_manipulation, "Extract pitch tier")
    reference_tier = call(reference_manipulation, "Extract pitch tier")
    source_times, source_frequencies = _tier_points(source_tier, call)
    reference_times, reference_frequencies = _tier_points(reference_tier, call)
    if alignment_stats["guide_points"] >= 3:
        # PitchTier 处在源时间轴上。把源到参考的时序映射反过来，这样每个参考 F0 点都会引导那个会在该时刻落点的源事件。
        reference_times = np.interp(
            reference_times,
            guide_target_points,
            guide_source_points,
            left=guide_source_points[0],
            right=guide_source_points[-1],
        )
    else:
        reference_times = reference_times + lag

    corrected_frequencies, stats = _natural_pitch_curve(
        source_times,
        source_frequencies,
        reference_times,
        reference_frequencies,
        strength,
    )
    stats["lag_ms"] = lag * 1000.0
    stats["correlation"] = correlation
    stats.update(alignment_stats)
    if stats["points"] < 3 and alignment_stats["alignment_points"] < 3:
        shutil.copy2(source, output)
        return stats

    original = np.asarray(source_sound.values, dtype=np.float64)
    expected_frames = original.shape[-1]
    resynthesis_mix = _resynthesis_region_curve(
        np.asarray(source_sound.values, dtype=np.float64),
        sample_rate,
        pitch_times=source_times,
        source_frequencies=source_frequencies,
        corrected_frequencies=corrected_frequencies,
        pitch_strength=strength,
        duration_source_points=duration_source_points,
        duration_factors=duration_factors,
    )
    stats["resynthesis_percent"] = float(np.mean(resynthesis_mix) * 100.0)
    if not bool(np.any(resynthesis_mix)):
        cleaned, gap_stats = _suppress_reference_gap_residual(
            np.asarray(source_sound.values, dtype=np.float64),
            np.asarray(reference_sound.values, dtype=np.float64),
            sample_rate,
            lag_seconds=lag,
        )
        stats.update(gap_stats)
        if float(gap_stats["reference_gap_regions"]) > 0.0:
            sf.write(str(output), cleaned.T.astype(np.float32), sample_rate, subtype="FLOAT")
        else:
            shutil.copy2(source, output)
        return stats

    corrected_tier = call(
        "Create PitchTier",
        "xb-natural-tuning",
        source_sound.xmin,
        source_sound.xmax,
    )
    for time_value, frequency in zip(source_times, corrected_frequencies):
        if math.isfinite(float(frequency)) and frequency > 0.0:
            call(
                corrected_tier,
                "Add point",
                float(time_value),
                float(frequency),
            )
    call([corrected_tier, source_manipulation], "Replace pitch tier")
    tuned_sound = call(source_manipulation, "Get resynthesis (overlap-add)")
    tuned = np.asarray(tuned_sound.values, dtype=np.float64)
    if tuned.shape[-1] > expected_frames:
        tuned = tuned[..., :expected_frames]
    elif tuned.shape[-1] < expected_frames:
        tuned = np.pad(tuned, ((0, 0), (0, expected_frames - tuned.shape[-1])))

    # Praat Manipulation 对多声道 Sound 只返回一个重合成声道。先以原始
    # 中置声部做响度匹配，再恢复原始侧声道，避免把立体声输入整段降为单声道。
    level_reference = original
    if tuned.shape[0] == 1 and original.shape[0] > 1:
        level_reference = np.mean(original, axis=0, keepdims=True)
    elif original.shape[0] == 1 and tuned.shape[0] > 1:
        tuned = np.mean(tuned, axis=0, keepdims=True)
    active = np.max(np.abs(level_reference), axis=0) > 10.0 ** (-55.0 / 20.0)
    if bool(active.any()):
        original_rms = float(
            np.sqrt(np.mean(level_reference[:, active] ** 2) + 1e-12)
        )
        tuned_rms = float(np.sqrt(np.mean(tuned[:, active] ** 2) + 1e-12))
        if tuned_rms > 1e-7:
            tuned *= float(np.clip(original_rms / tuned_rms, 0.85, 1.15))
    tuned = _restore_resynthesis_channels(original, tuned)
    tuned = _blend_resynthesis(original, tuned, resynthesis_mix, sample_rate)
    tuned, gap_stats = _suppress_reference_gap_residual(
        tuned,
        np.asarray(reference_sound.values, dtype=np.float64),
        sample_rate,
        lag_seconds=lag,
    )
    stats.update(gap_stats)
    peak = float(np.max(np.abs(tuned))) if tuned.size else 0.0
    if peak > 0.99:
        tuned *= 0.99 / peak
    if not bool(np.isfinite(tuned).all()):
        raise RuntimeError("自然修音产生了非有限音频样本")
    sf.write(str(output), tuned.T.astype(np.float32), sample_rate, subtype="FLOAT")
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="XB-SVCB Praat 自然修音 worker")
    parser.add_argument("--input", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--strength", type=float, default=0.45)
    parser.add_argument("--alignment-strength", type=float, default=0.45)
    args = parser.parse_args()
    try:
        output = Path(args.output)
        output.unlink(missing_ok=True)
        stats = tune(
            Path(args.input),
            Path(args.reference),
            output,
            args.strength,
            args.alignment_strength,
        )
        if not output.is_file():
            raise RuntimeError("自然修音未生成输出文件")
        print(
            "VOCAL_TUNE_OK "
            f"{output} points={int(stats['points'])} "
            f"median={stats['median_cents']:.1f}c max={stats['max_cents']:.1f}c "
            f"align_points={int(stats['alignment_points'])} "
            f"phrases={int(stats['phrase_pairs'])} "
            f"phonemes={int(stats['phoneme_points'])} "
            f"guide={int(stats['guide_points'])} "
            f"align_median={stats['median_alignment_ms']:.0f}ms "
            f"align_max={stats['max_alignment_ms']:.0f}ms "
            f"stretch={stats['max_stretch_percent']:.1f}% "
            f"psola={stats.get('resynthesis_percent', 0.0):.0f}% "
            f"gap_gate={stats.get('reference_gap_seconds', 0.0):.2f}s "
            f"lag={stats['lag_ms']:+.0f}ms corr={stats['correlation']:.2f}",
            flush=True,
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - 保持子进程边界简洁
        print(f"VOCAL_TUNE_ERR {exc}", flush=True)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
