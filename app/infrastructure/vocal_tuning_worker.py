"""Reference-guided timing alignment and natural pitch correction using Praat PSOLA.

The converted vocal is aligned toward the original performance before its pitch is
corrected toward the guide and a slowly estimated note centre. Conservative duration
tiers preserve pitch/formants while fast deviations such as vibrato and slides remain.
"""

from __future__ import annotations

import argparse
import math
import shutil
import sys
import traceback
from pathlib import Path


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
    """Return a conservative corrected F0 curve for Praat PitchTier points."""
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

    # Process each voiced phrase separately so medians never bridge an unvoiced gap.
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
        # Large disagreements are usually octave/F0 tracking errors. Let the reference
        # performance guide the converted voice, but do not force it onto every detected
        # semitone; that hard note-centre pull is the main source of an Auto-Tune edge.
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
            # Fade correction at voiced phrase edges so PSOLA never enters or leaves a
            # correction abruptly on an onset, consonant, breath, or note release.
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
    """Estimate reference-to-source lag from 20 ms RMS envelopes."""
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


def _alignment_feature(
    audio: "np.ndarray",
    sample_rate: int,
) -> tuple["np.ndarray", "np.ndarray", float]:
    """Return a compact energy/onset feature sampled at roughly 100 Hz."""
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
    """Return speaker-normalized cepstral features for acoustic phoneme matching."""
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
    """Split active vocal frames at sentence-like pauses while retaining word gaps."""
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
    """Monotonically pair sentence spans using position and duration consistency."""
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
    """Return a monotonic, slope-constrained DTW path and per-anchor similarity."""
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
    """Build high-confidence source/reference anchors from phrase and phoneme matches."""
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
    """Estimate a bounded source-to-reference timing map from local vocal events.

    The returned factors are suitable for a Praat DurationTier. Endpoints are fixed so
    that the aligned vocal keeps the source duration and remains mix-aligned.
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
    # Smooth only among nearby anchors so a pause never carries the previous vowel's
    # timing offset into the next phrase.
    lag_values = raw_lags.copy()
    for anchor_index, anchor_time in enumerate(anchor_times):
        neighborhood = np.abs(anchor_times - anchor_time) <= 0.90
        if int(neighborhood.sum()) >= 3:
            lag_values[anchor_index] = float(np.median(raw_lags[neighborhood]))

    # Keep a dense, smooth phoneme map for the later F0 lookup even when the audio itself
    # is not time-stretched. This preserves the previous version's useful local pitch
    # correspondence without imposing a continuously moving DurationTier on vowels.
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

    # Micro-warping is more audible than a tiny timing error on a sustained vowel. Keep
    # all matches for diagnostics, but create a DurationTier only for a continuous run
    # of meaningful offsets: >25 ms raw and >=8 ms after the user's strength is applied.
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
    max_stretch = 0.025 + 0.045 * amount
    factors = np.clip(desired_factors, 1.0 - max_stretch, 1.0 + max_stretch)

    # Preserve the full duration after clipping. Distribute the residual only across
    # intervals that still have headroom so the advertised stretch bound remains strict.
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
    """Attach the bounded local timing curve to a Praat Manipulation object."""
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


def _resynthesis_region_curve(
    original: "np.ndarray",
    sample_rate: int,
) -> "np.ndarray":
    """Keep PSOLA inside continuous vocal regions and preserve original silence."""
    import numpy as np
    from scipy.ndimage import gaussian_filter1d

    audio = np.asarray(original, dtype=np.float64)
    if audio.ndim == 1:
        audio = audio[np.newaxis, :]
    total_frames = audio.shape[-1]
    if total_frames == 0:
        return np.zeros(0, dtype=np.float64)

    frame_size = max(32, int(round(sample_rate * 0.020)))
    frame_count = int(np.ceil(total_frames / frame_size))
    sample_power = np.mean(audio * audio, axis=0)
    padded = np.pad(sample_power, (0, frame_count * frame_size - total_frames))
    frame_rms = np.sqrt(
        np.mean(padded.reshape(frame_count, frame_size), axis=1) + 1e-12
    )
    levels = 20.0 * np.log10(frame_rms + 1e-10)
    active_threshold = max(-52.0, float(np.percentile(levels, 90)) - 32.0)
    active = levels >= active_threshold
    if not bool(active.any()):
        return np.zeros(total_frames, dtype=np.float64)

    # A short consonant or intra-phrase rest must not switch PSOLA on and off. Bridge
    # gaps up to 450 ms, then protect 100 ms before and 300 ms after each vocal region.
    bridge_frames = max(1, int(round(0.45 * sample_rate / frame_size)))
    inactive = np.flatnonzero(~active)
    if len(inactive):
        run_starts = np.r_[0, np.flatnonzero(np.diff(inactive) > 1) + 1]
        run_ends = np.r_[run_starts[1:], len(inactive)]
        for run_start, run_end in zip(run_starts, run_ends):
            run = inactive[run_start:run_end]
            if (
                len(run) <= bridge_frames
                and run[0] > 0
                and run[-1] < frame_count - 1
                and active[run[0] - 1]
                and active[run[-1] + 1]
            ):
                active[run] = True

    protected = np.zeros(frame_count, dtype=np.float64)
    pre_frames = max(1, int(round(0.10 * sample_rate / frame_size)))
    post_frames = max(1, int(round(0.30 * sample_rate / frame_size)))
    for index in np.flatnonzero(active):
        protected[
            max(0, index - pre_frames) : min(frame_count, index + post_frames + 1)
        ] = 1.0
    protected = gaussian_filter1d(
        protected,
        sigma=max(1.0, 0.050 * sample_rate / frame_size),
        mode="nearest",
    )
    protected[protected < 1e-5] = 0.0
    protected[protected > 1.0 - 1e-5] = 1.0
    centres = np.minimum(
        total_frames - 1,
        np.arange(frame_count, dtype=np.float64) * frame_size + frame_size * 0.5,
    )
    return np.interp(
        np.arange(total_frames, dtype=np.float64),
        centres,
        protected,
        left=float(protected[0]),
        right=float(protected[-1]),
    )


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
        1100.0,
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
        1100.0,
    )
    source_tier = call(source_manipulation, "Extract pitch tier")
    reference_tier = call(reference_manipulation, "Extract pitch tier")
    source_times, source_frequencies = _tier_points(source_tier, call)
    reference_times, reference_frequencies = _tier_points(reference_tier, call)
    if alignment_stats["guide_points"] >= 3:
        # PitchTier lives in source time. Invert the source-to-reference timing map so
        # each reference F0 point guides the source event that will land at that time.
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
    original = np.asarray(source_sound.values, dtype=np.float64)
    expected_frames = original.shape[-1]
    if tuned.shape[-1] > expected_frames:
        tuned = tuned[..., :expected_frames]
    elif tuned.shape[-1] < expected_frames:
        tuned = np.pad(tuned, ((0, 0), (0, expected_frames - tuned.shape[-1])))

    active = np.max(np.abs(original), axis=0) > 10.0 ** (-55.0 / 20.0)
    if bool(active.any()):
        original_rms = float(np.sqrt(np.mean(original[:, active] ** 2) + 1e-12))
        tuned_rms = float(np.sqrt(np.mean(tuned[:, active] ** 2) + 1e-12))
        if tuned_rms > 1e-7:
            tuned *= float(np.clip(original_rms / tuned_rms, 0.85, 1.15))
    resynthesis_mix = _resynthesis_region_curve(original, sample_rate)
    tuned = original + (tuned - original) * resynthesis_mix[np.newaxis, :]
    stats["resynthesis_percent"] = float(np.mean(resynthesis_mix) * 100.0)
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
            f"lag={stats['lag_ms']:+.0f}ms corr={stats['correlation']:.2f}",
            flush=True,
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - concise subprocess boundary
        print(f"VOCAL_TUNE_ERR {exc}", flush=True)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
