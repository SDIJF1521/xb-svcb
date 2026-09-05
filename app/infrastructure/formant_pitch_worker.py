"""Formant-preserving pitch shifting with Praat PSOLA.

This worker runs in the isolated vocal environment so the main application does
not need to import Praat or its native dependencies. Only the pitch tier is
changed; the spectral envelope/formants remain in the source sound.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


_REGION_FADE_SECONDS = 0.08
_HIGH_POINT_GROUP_GAP_SECONDS = 0.12
_HIGH_NOTE_PADDING_SECONDS = 0.05


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
    allowed_regions: list[tuple[float, float]] | None = None,
) -> list[tuple[float, float]]:
    """Turn reliable high-pitch points into smooth, local processing regions.

    Outside a confirmed dropout scope, two nearby high points are still
    required so an octave tracker spike cannot activate PSOLA. Inside a scope
    that was independently confirmed by the model-dropout detector, one
    high/near-high point is enough to recover a short note whose pitch tier
    contains only one usable frame.
    """
    import math

    threshold = max(100.0, float(threshold))
    hysteresis = max(35.0, threshold * 0.08)
    scoped_regions = sorted(
        (max(float(start), xmin), min(float(end), xmax))
        for start, end in (allowed_regions or [])
        if math.isfinite(float(start))
        and math.isfinite(float(end))
        and float(end) > float(start)
        and min(float(end), xmax) > max(float(start), xmin)
    )
    clean_points = sorted(
        (float(time), float(frequency))
        for time, frequency in points
        if math.isfinite(float(time))
        and math.isfinite(float(frequency))
        and xmin <= float(time) <= xmax
        and float(frequency) >= 100.0
    )
    if not clean_points:
        return []

    # Group neighboring voiced points first. This lets a note briefly dip below
    # the hard threshold without splitting its protection region.
    near_threshold = max(100.0, threshold - hysteresis)
    near_points = [
        point
        for point in clean_points
        if point[1] >= near_threshold
    ]
    if not near_points:
        return []
    groups: list[list[tuple[float, float]]] = [[near_points[0]]]
    for point in near_points[1:]:
        if point[0] - groups[-1][-1][0] <= _HIGH_POINT_GROUP_GAP_SECONDS:
            groups[-1].append(point)
        else:
            groups.append([point])

    def candidates_for(
        anchor_threshold: float,
        *,
        allow_single: bool,
        scope: tuple[float, float] | None = None,
    ) -> list[tuple[float, float]]:
        candidates: list[tuple[float, float]] = []
        for group in groups:
            anchors = [
                point
                for point in group
                if point[1] >= anchor_threshold
            ]
            if scope is not None:
                scope_start, scope_end = scope
                anchors = [
                    point
                    for point in anchors
                    if scope_start <= point[0] <= scope_end
                ]
            if len(anchors) < (1 if allow_single else 2):
                continue
            # A confirmed scope identifies *which* note needs recovery; it is
            # not the note boundary. Keep the whole connected pitch group so
            # its attack and release are lowered, inferred and restored as one
            # unit. The caller still merges only groups intersecting a verified
            # dropout, so neighboring healthy notes remain untouched.
            group_start = group[0][0]
            group_end = group[-1][0]
            if group_end < group_start:
                continue
            start = max(xmin, group_start - _HIGH_NOTE_PADDING_SECONDS)
            end = min(xmax, group_end + _HIGH_NOTE_PADDING_SECONDS)
            if end <= start:
                continue
            candidates.append((start, end))
        return candidates

    # Without confirmed failure evidence, stay conservative and ignore a
    # one-frame pitch spike.
    strict_intervals = candidates_for(threshold, allow_single=False)
    if not scoped_regions:
        return strict_intervals

    # A confirmed dropout can be below the initial protection boundary after
    # pitch conversion. Resolve each scope independently so one real high note
    # cannot suppress the fallback for a neighboring short note.
    relaxed_threshold = max(100.0, threshold - max(110.0, hysteresis))
    scoped: list[tuple[float, float]] = []
    for scope_start, scope_end in scoped_regions:
        scope = (scope_start, scope_end)
        candidates = candidates_for(
            threshold,
            allow_single=False,
            scope=scope,
        )
        if not candidates:
            candidates = candidates_for(
                relaxed_threshold,
                allow_single=True,
                scope=scope,
            )
        for start, end in candidates:
            # The sample mask and pitch tier both apply the single shared fade
            # around this interval. Do not expand it a second time here.
            left = max(xmin, start)
            right = min(xmax, end)
            if scoped and left < scoped[-1][1] - 1e-6:
                scoped[-1] = (scoped[-1][0], max(scoped[-1][1], right))
            else:
                scoped.append((left, right))
    return scoped


def _region_mask(
    intervals: list[tuple[float, float]],
    sample_rate: float,
    count: int,
) -> object:
    import numpy as np

    mask = np.zeros(max(0, count), dtype=np.float64)
    if not intervals or count <= 0:
        return mask
    fade = max(1, int(round(sample_rate * _REGION_FADE_SECONDS)))
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


def _region_weight_at(
    time: float,
    intervals: list[tuple[float, float]],
    fade: float = _REGION_FADE_SECONDS,
) -> float:
    """Return a smooth 0..1 pitch-shift amount at one pitch-tier point.

    The audio blend already fades at the same boundary.  Applying that fade to
    the pitch tier as well avoids an instantaneous frequency jump inside Praat
    PSOLA, which otherwise sounds like a dropped frame at every high-note edge.
    """
    point = float(time)
    edge = max(0.01, float(fade))
    weight = 0.0
    for start, end in intervals:
        start = float(start)
        end = float(end)
        if start <= point <= end:
            weight = max(weight, 1.0)
            continue
        if start - edge < point < start:
            phase = (point - (start - edge)) / edge
            weight = max(weight, math.sin(phase * math.pi / 2.0) ** 2)
        elif end < point < end + edge:
            phase = (point - end) / edge
            weight = max(weight, math.cos(phase * math.pi / 2.0) ** 2)
    return min(1.0, max(0.0, weight))


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
    # PSOLA can make an unvoiced/breathy high-note fragment look quieter than
    # the source even though its high-band noise is already prominent. A large
    # loudness correction then amplifies that air and produces the familiar
    # "唱不上去" hiss. Keep the correction close to unity: valid high notes
    # retain their dynamics, while breath is never allowed to grow several dB.
    gain = max(0.92, min(1.18, source_rms / output_rms))
    output_audio[:count] *= 1.0 + mask * (gain - 1.0)
    return output_audio


def _processing_chunks(
    intervals: list[tuple[float, float]],
    duration: float,
    context: float,
) -> list[tuple[float, float]]:
    """Group nearby guarded regions into short PSOLA processing windows."""
    expanded: list[tuple[float, float]] = []
    for start, end in intervals:
        left = max(0.0, float(start) - context)
        right = min(float(duration), float(end) + context)
        if right <= left:
            continue
        if expanded and left <= expanded[-1][1]:
            expanded[-1] = (expanded[-1][0], max(expanded[-1][1], right))
        else:
            expanded.append((left, right))
    return expanded


def _selective_mono_psola(
    mono: object,
    sample_rate: float,
    source_points: list[tuple[float, float]],
    intervals: list[tuple[float, float]],
    ratio: float,
) -> object:
    """Render only guarded windows and leave every other sample untouched.

    Running Praat over a multi-minute track can add a phase/noise floor to
    unrelated material even when the pitch tier is unchanged.  Short windows
    keep the expensive PSOLA operation inside the selected high-note regions;
    the resulting mono delta is reused for every channel to preserve stereo
    phase.
    """
    import numpy as np
    import parselmouth
    from parselmouth.praat import call

    source_audio = np.asarray(mono, dtype=np.float64).reshape(-1)
    rendered_audio = source_audio.copy()
    if not source_audio.size or not intervals or sample_rate <= 0:
        return rendered_audio
    total_duration = source_audio.size / float(sample_rate)
    mask = _region_mask(intervals, sample_rate, source_audio.size)
    context = _REGION_FADE_SECONDS + 0.08
    chunks = _processing_chunks(intervals, total_duration, context)
    for chunk_start, chunk_end in chunks:
        left = max(0, int(round(chunk_start * sample_rate)))
        right = min(source_audio.size, int(round(chunk_end * sample_rate)))
        if right - left < max(256, int(sample_rate * 0.08)):
            continue
        segment = source_audio[left:right]
        segment_sound = parselmouth.Sound(segment, sampling_frequency=sample_rate)
        manipulation = call(segment_sound, "To Manipulation", 0.005, 55.0, 4000.0)
        segment_xmin = left / float(sample_rate)
        points = [
            (float(time) - segment_xmin, float(frequency))
            for time, frequency in source_points
            if segment_xmin <= float(time) <= right / float(sample_rate)
            and float(frequency) > 0.0
        ]
        if not points:
            # A malformed/empty tier must never replace the original segment.
            continue
        # Add synthetic boundary anchors when Praat's pitch tier has no sample
        # exactly at the region edge. Without them, the first/last available
        # point can make the selective pitch amount jump inside the fade.
        tier_points = list(points)
        absolute_points = [
            (float(time), float(frequency))
            for time, frequency in source_points
            if float(frequency) > 0.0
        ]
        if len(absolute_points) >= 2:
            absolute_times = np.asarray(
                [item[0] for item in absolute_points],
                dtype=np.float64,
            )
            absolute_frequencies = np.asarray(
                [item[1] for item in absolute_points],
                dtype=np.float64,
            )
            for boundary in (
                float(value)
                for interval in intervals
                for value in interval
                if chunk_start <= float(value) <= chunk_end
            ):
                local_boundary = boundary - segment_xmin
                if not (segment_sound.xmin <= local_boundary <= segment_sound.xmax):
                    continue
                if any(abs(item[0] - local_boundary) < 0.008 for item in tier_points):
                    continue
                if float(np.min(np.abs(absolute_times - boundary))) > 0.18:
                    continue
                frequency = float(
                    np.interp(
                        boundary,
                        absolute_times,
                        absolute_frequencies,
                    )
                )
                if frequency <= 0.0:
                    continue
                tier_points.append((local_boundary, frequency))
        tier_points.sort(key=lambda item: item[0])
        selective = call(
            "Create PitchTier",
            "Selective high pitch window",
            segment_sound.xmin,
            segment_sound.xmax,
        )
        for local_time, frequency in tier_points:
            blend = _region_weight_at(local_time + segment_xmin, intervals)
            shifted_frequency = frequency * (1.0 + blend * (ratio - 1.0))
            call(selective, "Add point", local_time, shifted_frequency)
        call([selective, manipulation], "Replace pitch tier")
        rendered = call(manipulation, "Get resynthesis (overlap-add)")
        segment_output = np.asarray(rendered.values, dtype=np.float64).reshape(-1)
        expected = right - left
        if segment_output.size > expected:
            segment_output = segment_output[:expected]
        elif segment_output.size < expected:
            segment_output = np.pad(segment_output, (0, expected - segment_output.size))
        segment_mask = mask[left:right]
        rendered_audio[left:right] = (
            segment * (1.0 - segment_mask) + segment_output * segment_mask
        )
    return rendered_audio


def shift(
    source: Path,
    destination: Path,
    semitones: float,
    high_threshold: float = 800.0,
    mask_source: Path | None = None,
    loudness_source: Path | None = None,
    allowed_regions: list[tuple[float, float]] | None = None,
) -> list[tuple[float, float]]:
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
    pitch_tier = call(
        call(mono_sound, "To Manipulation", 0.005, 55.0, 4000.0),
        "Extract pitch tier",
    )
    mask_tier = pitch_tier
    if mask_source and mask_source.is_file():
        mask_sound = parselmouth.Sound(str(mask_source))
        mask_values = np.asarray(mask_sound.values, dtype=np.float64)
        if mask_values.ndim > 1:
            mask_values = np.mean(mask_values, axis=0)
        mask_mono = parselmouth.Sound(mask_values, sampling_frequency=mask_sound.sampling_frequency)
        mask_manipulation = call(mask_mono, "To Manipulation", 0.005, 55.0, 4000.0)
        mask_tier = call(mask_manipulation, "Extract pitch tier")
    # The source audio owns the pitch contour being shifted.  ``mask_source``
    # only supplies region boundaries; using its tier here during restoration
    # would shift the original F0 a second time and overshoot the model output.
    source_points = _pitch_points(pitch_tier, call)
    mask_points = _pitch_points(mask_tier, call)
    intervals = _high_intervals(
        mask_points,
        max(100.0, float(high_threshold)),
        sound.xmin,
        sound.xmax,
        allowed_regions=allowed_regions,
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
        return []

    loudness_reference = mono
    if loudness_source and loudness_source.is_file():
        reference_sound = parselmouth.Sound(str(loudness_source))
        reference_values = np.asarray(reference_sound.values, dtype=np.float64)
        if reference_values.ndim > 1:
            reference_values = np.mean(reference_values, axis=0)
        loudness_reference = reference_values
    # Render a single mono delta in short windows.  Reusing that delta for both
    # channels prevents stereo phase drift and guarantees non-high regions are
    # copied from the original input.
    rendered_mono = _selective_mono_psola(
        mono,
        float(sound.sampling_frequency),
        source_points,
        intervals,
        ratio,
    )
    mono_delta = np.asarray(rendered_mono, dtype=np.float64) - mono
    output = np.vstack(
        [
            _restore_region_loudness(
                loudness_reference,
                np.asarray(source_channel, dtype=np.float64) + mono_delta,
                intervals,
                sound.sampling_frequency,
            )
            for source_channel in values
        ]
    )
    output = np.clip(
        np.nan_to_num(output.T, nan=0.0, posinf=0.0, neginf=0.0),
        -1.0,
        1.0,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(destination), output, int(round(sound.sampling_frequency)), subtype="PCM_16")
    return intervals


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
    parser.add_argument(
        "--regions-json",
        default="",
        help="仅处理 JSON 中列出的已确认失配区间",
    )
    parser.add_argument(
        "--report-json",
        default="",
        help="可选：将实际处理的高音区间写入 JSON",
    )
    args = parser.parse_args()
    source = Path(args.input)
    destination = Path(args.output)
    try:
        allowed_regions: list[tuple[float, float]] | None = None
        if args.regions_json:
            raw_regions = json.loads(Path(args.regions_json).read_text(encoding="utf-8"))
            if isinstance(raw_regions, list):
                parsed_regions: list[tuple[float, float]] = []
                for item in raw_regions:
                    if isinstance(item, dict):
                        start, end = item.get("start"), item.get("end")
                    elif isinstance(item, (list, tuple)) and len(item) >= 2:
                        start, end = item[0], item[1]
                    else:
                        continue
                    try:
                        left, right = float(start), float(end)
                    except (TypeError, ValueError):
                        continue
                    if right > left:
                        parsed_regions.append((left, right))
                allowed_regions = parsed_regions or None
        intervals = shift(
            source,
            destination,
            args.semitones,
            high_threshold=args.high_threshold,
            mask_source=Path(args.mask_source) if args.mask_source else None,
            loudness_source=Path(args.loudness_source) if args.loudness_source else None,
            allowed_regions=allowed_regions,
        )
        if args.report_json:
            report_path = Path(args.report_json)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(
                    {
                        "threshold_hz": float(args.high_threshold),
                        "semitones": float(args.semitones),
                        "region_count": len(intervals),
                        "processed_seconds": round(
                            sum(end - start for start, end in intervals), 3
                        ),
                        "regions": [
                            {
                                "start": round(start, 3),
                                "end": round(end, 3),
                                "duration": round(end - start, 3),
                            }
                            for start, end in intervals
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        preview = ",".join(
            f"{start:.2f}-{end:.2f}s" for start, end in intervals[:8]
        )
        if len(intervals) > 8:
            preview += ",..."
        print(
            f"FORMANT_PITCH_REGIONS\t{len(intervals)}\t"
            f"{sum(end - start for start, end in intervals):.3f}s\t{preview}",
            flush=True,
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
