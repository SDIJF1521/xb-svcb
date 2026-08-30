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


def _high_intervals(
    points: list[tuple[float, float]],
    threshold: float,
    xmin: float,
    xmax: float,
) -> list[tuple[float, float]]:
    """Turn *stable* high voiced pitch points into expanded time regions.

    A single Praat pitch point is often an octave error or a consonant
    transient.  Shifting such a point creates a short PSOLA blip that sounds
    like vibrato/electronic noise, so require two nearby high points before
    enabling a region.
    """
    high_points = sorted(
        (float(time), float(frequency))
        for time, frequency in points
        if frequency >= threshold and xmin <= time <= xmax
    )
    if len(high_points) < 2:
        return []
    groups: list[list[tuple[float, float]]] = [[high_points[0]]]
    for point in high_points[1:]:
        if point[0] - groups[-1][-1][0] <= 0.08:
            groups[-1].append(point)
        else:
            groups.append([point])
    padding = 0.035
    intervals: list[tuple[float, float]] = []
    for group in groups:
        if len(group) < 2:
            continue
        start = max(xmin, group[0][0] - padding)
        end = min(xmax, group[-1][0] + padding)
        if intervals and start <= intervals[-1][1] + 0.01:
            intervals[-1] = (intervals[-1][0], max(intervals[-1][1], end))
        else:
            intervals.append((start, end))
    return intervals


def _region_mask(
    intervals: list[tuple[float, float]],
    sample_rate: float,
    count: int,
) -> object:
    import numpy as np

    mask = np.zeros(max(0, count), dtype=np.float64)
    if not intervals or count <= 0:
        return mask
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
    return mask


def _blend_regions(
    source: object,
    rendered: object,
    intervals: list[tuple[float, float]],
    sample_rate: float,
) -> object:
    """Keep the source untouched outside selected high-note regions."""
    import numpy as np

    source_audio = np.asarray(source, dtype=np.float64).reshape(-1)
    output_audio = np.asarray(rendered, dtype=np.float64).reshape(-1)
    if not source_audio.size or not output_audio.size:
        return output_audio
    count = min(source_audio.size, output_audio.size)
    mask = _region_mask(intervals, sample_rate, count)
    output_audio[:count] = source_audio[:count] * (1.0 - mask) + output_audio[:count] * mask
    return output_audio


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
    mask = _region_mask(intervals, sample_rate, count)
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
    ratio = 2.0 ** (float(semitones) / 12.0)
    mask_tier = call(
        call(mono_sound, "To Manipulation", 0.005, 55.0, 4000.0),
        "Extract pitch tier",
    )
    source_tier = mask_tier
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

    # Do not run an unnecessary PSOLA resynthesis when the output has no
    # corresponding high-note region (for example, a model may have dropped a
    # note entirely).  Writing the original samples here avoids adding Praat's
    # phase/noise floor to otherwise clean audio.
    if not intervals:
        destination.parent.mkdir(parents=True, exist_ok=True)
        safe_values = np.clip(
            np.nan_to_num(values.T, nan=0.0, posinf=0.0, neginf=0.0),
            -1.0,
            1.0,
        )
        sf.write(
            str(destination),
            safe_values,
            int(round(sound.sampling_frequency)),
            subtype="PCM_16",
        )
        return

    loudness_reference = mono
    if loudness_source and loudness_source.is_file():
        reference_sound = parselmouth.Sound(str(loudness_source))
        reference_values = np.asarray(reference_sound.values, dtype=np.float64)
        if reference_values.ndim > 1:
            reference_values = np.mean(reference_values, axis=0)
        loudness_reference = reference_values
    rendered_channels: list[np.ndarray] = []
    expected = values.shape[1]
    for channel in values:
        channel_sound = parselmouth.Sound(
            channel,
            sampling_frequency=sound.sampling_frequency,
        )
        manipulation = call(channel_sound, "To Manipulation", 0.005, 55.0, 4000.0)
        tier = call(manipulation, "Extract pitch tier")
        channel_points = _pitch_points(tier, call)
        if not channel_points:
            # A silent/phase-cancelled side channel has no valid tier.  Keep it
            # untouched instead of asking Praat to replace an empty tier.
            rendered_channels.append(channel.copy())
            continue
        selective = call(
            "Create PitchTier",
            "Selective high pitch",
            channel_sound.xmin,
            channel_sound.xmax,
        )
        for point_time, frequency in channel_points:
            active = any(start <= point_time <= end for start, end in intervals)
            call(
                selective,
                "Add point",
                point_time,
                frequency * ratio if active else frequency,
            )
        call([selective, manipulation], "Replace pitch tier")
        rendered = call(manipulation, "Get resynthesis (overlap-add)")
        channel_output = np.asarray(rendered.values, dtype=np.float64).reshape(-1)
        if channel_output.size > expected:
            channel_output = channel_output[:expected]
        elif channel_output.size < expected:
            channel_output = np.pad(channel_output, (0, expected - channel_output.size))
        rendered_channels.append(channel_output)
    # Blend only the selected regions; outside them the source remains bitwise
    # unchanged, avoiding full-track PSOLA artifacts in consonants and lows.
    output = np.vstack(
        [
            _restore_region_loudness(
                loudness_reference,
                _blend_regions(source_channel, channel, intervals, sound.sampling_frequency),
                intervals,
                sound.sampling_frequency,
            )
            for source_channel, channel in zip(values, rendered_channels)
        ]
    )
    output = np.clip(
        np.nan_to_num(output.T, nan=0.0, posinf=0.0, neginf=0.0),
        -1.0,
        1.0,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(destination), output, int(round(sound.sampling_frequency)), subtype="PCM_16")


def _validate_render(source: Path, destination: Path) -> tuple[bool, str]:
    """Reject renders that are empty, malformed, clipped, or energy-collapsed.

    This check runs inside the worker so 0.0.30 installations (whose frozen
    caller predates the newer validation) still fall back to the source file
    when Praat produces an unsafe result.
    """
    import numpy as np
    import soundfile as sf

    if not destination.is_file() or destination.stat().st_size <= 44:
        return False, "输出文件为空"
    source_audio, source_rate = sf.read(str(source), always_2d=True, dtype="float32")
    output_audio, output_rate = sf.read(str(destination), always_2d=True, dtype="float32")
    if source_rate != output_rate:
        return False, "采样率发生变化"
    if source_audio.shape[0] == 0 or output_audio.shape[0] == 0:
        return False, "音频没有采样帧"
    if source_audio.shape[1] != output_audio.shape[1]:
        return False, "声道数发生变化"
    duration_limit = max(int(round(source_rate * 0.12)), int(source_audio.shape[0] * 0.04))
    if abs(int(output_audio.shape[0]) - int(source_audio.shape[0])) > duration_limit:
        return False, "输出时长异常"
    if not np.isfinite(output_audio).all():
        return False, "输出包含非法数值"
    source_rms = float(np.sqrt(np.mean(np.square(source_audio), dtype=np.float64)))
    output_rms = float(np.sqrt(np.mean(np.square(output_audio), dtype=np.float64)))
    if source_rms > 1.0e-4 and output_rms < source_rms * 0.05:
        return False, "输出能量异常衰减"
    if source_rms <= 1.0e-4 and output_rms > 0.02:
        return False, "静音输入产生了明显输出"
    if output_rms > max(0.95, source_rms * 4.0):
        return False, "输出能量异常增大"
    return True, "ok"


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
        quality_ok, quality_reason = _validate_render(source, destination)
        if not quality_ok:
            destination.unlink(missing_ok=True)
            raise RuntimeError(f"质量检查失败：{quality_reason}")
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
