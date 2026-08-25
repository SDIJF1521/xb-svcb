"""Formant-preserving pitch shifting with Praat PSOLA.

This worker runs in the isolated vocal environment so the main application does
not need to import Praat or its native dependencies. Only the pitch tier is
changed; the spectral envelope/formants remain in the source sound.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def _pitch_points(tier, call) -> list[tuple[float, float]]:  # noqa: ANN001
    points: list[tuple[float, float]] = []
    count = int(call(tier, "Get number of points"))
    for index in range(1, count + 1):
        try:
            points.append(
                (
                    float(call(tier, "Get time from index", index)),
                    float(call(tier, "Get value at index", index)),
                )
            )
        except (TypeError, ValueError):
            continue
    return points


def _high_intervals(points: list[tuple[float, float]], threshold: float, xmin: float, xmax: float) -> list[tuple[float, float]]:
    """Turn high voiced pitch points into gently expanded time regions."""
    intervals: list[list[float]] = []
    padding = 0.045
    for time, frequency in points:
        if frequency < threshold:
            continue
        start = max(xmin, time - padding)
        end = min(xmax, time + padding)
        if intervals and start <= intervals[-1][1] + 0.01:
            intervals[-1][1] = max(intervals[-1][1], end)
        else:
            intervals.append([start, end])
    return [(start, end) for start, end in intervals]


def _restore_region_loudness(
    source: object,
    rendered: object,
    intervals: list[tuple[float, float]],
    sample_rate: float,
) -> object:
    """Match PSOLA RMS only inside high-note regions with smooth edges."""
    import numpy as np

    source_audio = np.asarray(source, dtype=np.float64).reshape(-1)
    output_audio = np.asarray(rendered, dtype=np.float64).reshape(-1)
    if not intervals or not source_audio.size or not output_audio.size:
        return output_audio
    count = min(source_audio.size, output_audio.size)
    mask = np.zeros(count, dtype=np.float64)
    fade = max(1, int(round(sample_rate * 0.035)))
    for start, end in intervals:
        left = max(0, int(round(start * sample_rate)))
        right = min(count, int(round(end * sample_rate)))
        if right <= left:
            continue
        mask[left:right] = 1.0
        left_edge = max(0, left - fade)
        if left > left_edge:
            phase = np.linspace(0.0, np.pi / 2.0, left - left_edge, endpoint=False)
            mask[left_edge:left] = np.maximum(mask[left_edge:left], np.sin(phase) ** 2)
        right_edge = min(count, right + fade)
        if right_edge > right:
            phase = np.linspace(np.pi / 2.0, 0.0, right_edge - right, endpoint=False)
            mask[right:right_edge] = np.maximum(mask[right:right_edge], np.sin(phase) ** 2)
    active = mask > 0.5
    if not np.any(active):
        return output_audio
    source_rms = float(np.sqrt(np.mean(np.square(source_audio[:count][active]))))
    output_rms = float(np.sqrt(np.mean(np.square(output_audio[:count][active]))))
    if source_rms < 1e-4 or output_rms < 1e-5:
        return output_audio
    gain = max(0.85, min(3.0, source_rms / output_rms))
    output_audio[:count] *= 1.0 + mask * (gain - 1.0)
    return output_audio


def shift(
    source: Path,
    destination: Path,
    semitones: float,
    high_threshold: float = 800.0,
    mask_source: Path | None = None,
    loudness_source: Path | None = None,
) -> None:
    import numpy as np
    import parselmouth
    import soundfile as sf
    from parselmouth.praat import call

    sound = parselmouth.Sound(str(source))
    values = np.asarray(sound.values, dtype=np.float64)
    if values.ndim == 1:
        values = values[None, :]
    mono = np.mean(values, axis=0)
    mono_sound = parselmouth.Sound(mono, sampling_frequency=sound.sampling_frequency)
    manipulation = call(mono_sound, "To Manipulation", 0.005, 55.0, 4000.0)
    tier = call(manipulation, "Extract pitch tier")
    ratio = 2.0 ** (float(semitones) / 12.0)
    source_tier = tier
    if mask_source and mask_source.is_file():
        mask_sound = parselmouth.Sound(str(mask_source))
        mask_values = np.asarray(mask_sound.values, dtype=np.float64)
        if mask_values.ndim > 1:
            mask_values = np.mean(mask_values, axis=0)
        mask_mono = parselmouth.Sound(mask_values, sampling_frequency=mask_sound.sampling_frequency)
        mask_manipulation = call(mask_mono, "To Manipulation", 0.005, 55.0, 4000.0)
        source_tier = call(mask_manipulation, "Extract pitch tier")
    intervals = _high_intervals(
        _pitch_points(source_tier, call),
        max(100.0, float(high_threshold)),
        sound.xmin,
        sound.xmax,
    )
    loudness_reference = mono
    if loudness_source and loudness_source.is_file():
        reference_sound = parselmouth.Sound(str(loudness_source))
        reference_values = np.asarray(reference_sound.values, dtype=np.float64)
        if reference_values.ndim > 1:
            reference_values = np.mean(reference_values, axis=0)
        loudness_reference = reference_values
    if intervals:
        selective = call("Create PitchTier", "Selective high pitch", sound.xmin, sound.xmax)
        for point_time, frequency in _pitch_points(tier, call):
            active = any(start <= point_time <= end for start, end in intervals)
            call(selective, "Add point", point_time, frequency * ratio if active else frequency)
        call([selective, manipulation], "Replace pitch tier")
    else:
        # No high notes in this block: preserve the original pitch tier exactly.
        call([tier, manipulation], "Replace pitch tier")
    rendered = call(manipulation, "Get resynthesis (overlap-add)")
    output = np.asarray(rendered.values, dtype=np.float64)
    if output.ndim == 1:
        output = output[None, :]
    expected = values.shape[1]
    if output.shape[1] > expected:
        output = output[:, :expected]
    elif output.shape[1] < expected:
        output = np.pad(output, ((0, 0), (0, expected - output.shape[1])))
    output = _restore_region_loudness(
        loudness_reference,
        output[0],
        intervals,
        sound.sampling_frequency,
    )
    output = np.repeat(output[None, :], values.shape[0], axis=0).T
    destination.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(destination), output, int(round(sound.sampling_frequency)), subtype="PCM_16")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--semitones", required=True, type=float)
    parser.add_argument("--high-threshold", type=float, default=800.0)
    parser.add_argument("--mask-source", default="")
    parser.add_argument("--loudness-source", default="")
    args = parser.parse_args()
    source = Path(args.input)
    destination = Path(args.output)
    try:
        shift(
            source,
            destination,
            args.semitones,
            high_threshold=args.high_threshold,
            mask_source=Path(args.mask_source) if args.mask_source else None,
            loudness_source=Path(args.loudness_source) if args.loudness_source else None,
        )
        print(f"FORMANT_PITCH_OK\t{destination}", flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 - report worker errors to the caller
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            pass
        print(f"FORMANT_PITCH_ERR\t{exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
