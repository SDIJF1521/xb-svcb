"""把 MIDI 音符应用到音频：逐音符移调 + Praat PSOLA（保共振峰）。

MIDI 子编辑器里的音符最终要落到音频上，而不是用 MIDI 音源直接播放。这里的做法是：

* 每个音符算出它与该区间实际基频中位数的差值（半音），只处理差值超过阈值的音符；
* 用 Praat Manipulation 把音高层按「音符内常量移调 + 25ms 过渡」重写后重新合成，
  PSOLA 保留原来的共振峰与音色，不会变成合成器；
* 只在被修改的音符区间内与原始音频交叉淡化混合，其余采样点原样保留；
* 多声道输入按中置重合成恢复侧声道，避免把立体声压成单声道。

未修改的音符（差值小于阈值）不做任何处理，所以「提取 → 应用」不会把歌手的自然
音准洗成电音；只有真正被拖动的音符才会被压到目标音高。
"""

from __future__ import annotations

import argparse
import json
import math
import traceback
from pathlib import Path

_DEFAULT_MIN_OFFSET_CENTS = 25.0
_DEFAULT_MAX_SEMITONES = 12.0
_FADE_SECONDS = 0.025
_RAMP_SECONDS = 0.030
_MIN_NOTE_SECONDS = 0.05
_MIN_VOICED_RATIO = 0.30
_PRAAT_FLOOR_HZ = 55.0
_PRAAT_CEILING_HZ = 2000.0
_F0_FRAME = 1024
_F0_HOP = 256


def _tier_points(tier, praat_call):  # noqa: ANN001, ANN202
    import numpy as np

    count = int(praat_call(tier, "Get number of points"))
    times: list[float] = []
    values: list[float] = []
    for index in range(1, count + 1):
        try:
            times.append(float(praat_call(tier, "Get time from index", index)))
            values.append(float(praat_call(tier, "Get value at index", index)))
        except (TypeError, ValueError):
            continue
    return np.asarray(times, dtype=np.float64), np.asarray(values, dtype=np.float64)


def _estimate_f0(mono, rate: int):  # noqa: ANN001, ANN202
    """归一化自相关基频探针（与高音保护共用同一套参数）。"""
    import numpy as np

    audio = np.asarray(mono, dtype=np.float64).reshape(-1)
    if audio.size < _F0_FRAME:
        return np.zeros(0, dtype=np.float64), np.zeros(0, dtype=np.float64)
    frame, hop = _F0_FRAME, _F0_HOP
    count = 1 + (audio.size - frame) // hop
    index = np.arange(frame)[None, :] + hop * np.arange(count)[:, None]
    frames = audio[index]
    frames = frames - frames.mean(axis=1, keepdims=True)
    energy = np.sqrt(np.mean(frames * frames, axis=1))
    peak = float(np.max(energy)) if energy.size else 0.0
    usable = energy >= max(1e-6, peak * 0.03)
    min_lag = max(2, int(round(rate / 1800.0)))
    max_lag = min(frame - 2, int(round(rate / 55.0)))
    if max_lag <= min_lag + 2:
        return np.zeros(count, dtype=np.float64), np.zeros(count, dtype=np.float64)
    window = np.hanning(frame)
    spectra = np.fft.rfft(frames * window, n=2 * frame, axis=1)
    correlation = np.fft.irfft(spectra * np.conj(spectra), axis=1)
    baseline = np.maximum(correlation[:, :1], 1e-12)
    normalized = correlation / baseline
    lags = np.arange(min_lag, max_lag + 1)
    band = normalized[:, lags]
    best = np.argmax(band, axis=1)
    clarity = np.clip(band[np.arange(count), best], 0.0, 1.0)
    f0 = np.zeros(count, dtype=np.float64)
    voiced = usable & (clarity >= 0.30)
    f0[voiced] = rate / lags[best[voiced]].astype(np.float64)
    return f0, clarity


def _hz_to_midi(frequency: float) -> float:
    value = float(frequency)
    if value <= 0.0:
        return 0.0
    return 69.0 + 12.0 * math.log2(value / 440.0)


def _midi_to_hz(pitch: float) -> float:
    return 440.0 * (2.0 ** ((float(pitch) - 69.0) / 12.0))


def note_offsets(
    notes: list[dict],
    times,  # noqa: ANN001 - numpy array
    f0,  # noqa: ANN001 - numpy array
    *,
    min_offset_cents: float = _DEFAULT_MIN_OFFSET_CENTS,
    max_semitones: float = _DEFAULT_MAX_SEMITONES,
) -> list[dict]:
    """计算每个音符需要移动的半音数（纯计算，便于单测）。"""
    import numpy as np

    timeline = np.asarray(times, dtype=np.float64).reshape(-1)
    values = np.asarray(f0, dtype=np.float64).reshape(-1)
    count = min(timeline.size, values.size)
    timeline = timeline[:count]
    values = values[:count]
    results: list[dict] = []
    limit = float(max_semitones)
    for note in notes or []:
        if not isinstance(note, dict):
            continue
        try:
            start = float(note.get("start", 0.0) or 0.0)
            end = float(note.get("end", 0.0) or 0.0)
            pitch = float(note.get("pitch", 60.0) or 60.0)
            detune = float(note.get("detune", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if end - start < _MIN_NOTE_SECONDS:
            results.append({"note": note, "applied": False, "reason": "音符过短"})
            continue
        start_index = int(np.searchsorted(timeline, start, side="left"))
        end_index = int(np.searchsorted(timeline, end, side="right"))
        if end_index <= start_index:
            results.append({"note": note, "applied": False, "reason": "区间内没有分析帧"})
            continue
        segment = values[start_index:end_index]
        voiced = segment[np.isfinite(segment) & (segment > 0.0)]
        ratio = voiced.size / max(1, segment.size)
        if voiced.size < 3 or ratio < _MIN_VOICED_RATIO:
            results.append(
                {"note": note, "applied": False, "reason": "音符区间内没有稳定浊音"}
            )
            continue
        median_midi = _hz_to_midi(float(np.median(voiced)))
        target = pitch + detune / 100.0
        offset = max(-limit, min(limit, target - median_midi))
        cents = offset * 100.0
        results.append(
            {
                "note": note,
                "applied": abs(cents) >= float(min_offset_cents),
                "reason": "" if abs(cents) >= float(min_offset_cents) else "音高几乎没有变化",
                "offset_semitones": round(offset, 3),
                "source_midi": round(median_midi, 3),
                "target_midi": round(target, 3),
                "voiced_ratio": round(float(ratio), 3),
            }
        )
    return results


def _ratio_at(seconds, spans, ramp: float):  # noqa: ANN001, ANN202
    """返回某时刻的移调倍率；音符外为 1，边缘按 ``ramp`` 过渡。"""
    import numpy as np

    times = np.asarray(seconds, dtype=np.float64).reshape(-1)
    ratios = np.ones(times.shape, dtype=np.float64)
    for start, end, ratio in spans:
        inner = (times >= start) & (times <= end)
        ratios[inner] = ratio
        if ramp <= 0.0:
            continue
        lead = (times >= start - ramp) & (times < start)
        if bool(lead.any()):
            phase = (times[lead] - (start - ramp)) / ramp
            ratios[lead] = 1.0 + (ratio - 1.0) * (phase ** 2)
        tail = (times > end) & (times <= end + ramp)
        if bool(tail.any()):
            phase = (times[tail] - end) / ramp
            ratios[tail] = ratio + (1.0 - ratio) * (phase ** 2)
    return ratios


def _restore_channels(original, tuned):  # noqa: ANN001, ANN202
    """把 Praat 的单声道重合成恢复到源声道布局，保留侧声道内容。"""
    import numpy as np

    dry = np.asarray(original, dtype=np.float64)
    wet = np.asarray(tuned, dtype=np.float64)
    if dry.ndim == 1:
        dry = dry[np.newaxis, :]
    if wet.ndim == 1:
        wet = wet[np.newaxis, :]
    if dry.shape[0] == wet.shape[0]:
        return wet
    if wet.shape[0] == 1:
        dry_mid = np.mean(dry, axis=0, keepdims=True)
        return wet + (dry - dry_mid)
    if dry.shape[0] == 1:
        return np.mean(wet, axis=0, keepdims=True)
    return wet


def _blend_spans(original, tuned, spans, rate: int):  # noqa: ANN001, ANN202
    """只在修改区间内交叉淡化重合成结果，并按区间做响度对齐。"""
    import numpy as np

    dry = np.asarray(original, dtype=np.float64)
    wet = np.asarray(tuned, dtype=np.float64)
    if dry.ndim == 1:
        dry = dry[np.newaxis, :]
    if wet.ndim == 1:
        wet = wet[np.newaxis, :]
    length = min(dry.shape[-1], wet.shape[-1])
    dry = dry[:, :length]
    wet = wet[:, :length]
    mask = np.zeros(length, dtype=np.float64)
    fade = max(1, int(round(rate * _FADE_SECONDS)))
    for start, end in spans:
        left = max(0, min(length, int(round(start * rate))))
        right = max(left, min(length, int(round(end * rate))))
        if right <= left:
            continue
        segment = wet[:, left:right]
        reference = dry[:, left:right]
        dry_rms = float(np.sqrt(np.mean(reference * reference) + 1e-12))
        wet_rms = float(np.sqrt(np.mean(segment * segment) + 1e-12))
        if wet_rms > 1e-7 and dry_rms > 1e-7:
            gain = float(np.clip(dry_rms / wet_rms, 0.7, 1.4))
            wet[:, left:right] = segment * gain
        mask[left:right] = 1.0
        left_edge = max(0, left - fade)
        if left > left_edge:
            phase = np.linspace(0.0, np.pi / 2.0, left - left_edge, endpoint=False)
            mask[left_edge:left] = np.maximum(mask[left_edge:left], np.sin(phase) ** 2)
        right_edge = min(length, right + fade)
        if right_edge > right:
            phase = np.linspace(np.pi / 2.0, 0.0, right_edge - right, endpoint=False)
            mask[right:right_edge] = np.maximum(mask[right:right_edge], np.sin(phase) ** 2)
    return dry * (1.0 - mask) + wet * mask


def apply_notes(
    source: Path,
    output: Path,
    notes: list[dict],
    *,
    f0_curve: Path | None = None,
    min_offset_cents: float = _DEFAULT_MIN_OFFSET_CENTS,
    max_semitones: float = _DEFAULT_MAX_SEMITONES,
    ramp_seconds: float = _RAMP_SECONDS,
) -> dict:
    """执行音频重绘；没有任何音符需要修改时复制原文件并返回 applied=False。"""
    try:
        import numpy as np
        import parselmouth
        import soundfile as sf
        from parselmouth.praat import call
    except ImportError as exc:  # pragma: no cover - 环境缺失时由调用方处理
        raise RuntimeError("Praat/Parselmouth 未安装，请修复 vocal 运行时") from exc

    sound = parselmouth.Sound(str(source))
    rate = int(round(float(sound.sampling_frequency)))
    duration = float(sound.xmax)
    original = np.asarray(sound.values, dtype=np.float64)
    if original.ndim == 1:
        original = original[np.newaxis, :]
    mono = np.mean(original, axis=0)
    frames = max(1, int(round(duration / (_F0_HOP / float(rate)))))
    times = np.linspace(0.0, duration, frames)

    if f0_curve is not None and Path(f0_curve).is_file():
        curve = np.asarray(np.load(str(f0_curve), allow_pickle=False), dtype=np.float64).reshape(-1)
        if curve.size >= 8:
            times = np.linspace(0.0, duration, curve.size)
            f0 = curve
        else:
            f0, _clarity = _estimate_f0(mono, rate)
            times = np.linspace(0.0, duration, max(1, f0.size))
    else:
        f0, _clarity = _estimate_f0(mono, rate)
        times = np.linspace(0.0, duration, max(1, f0.size))

    computed = note_offsets(
        notes,
        times,
        f0,
        min_offset_cents=min_offset_cents,
        max_semitones=max_semitones,
    )
    spans: list[tuple[float, float, float]] = []
    applied: list[dict] = []
    for item in computed:
        if not item.get("applied"):
            continue
        note = item["note"]
        start = float(note.get("start", 0.0) or 0.0)
        end = float(note.get("end", 0.0) or 0.0)
        if end <= start:
            continue
        offset = float(item.get("offset_semitones") or 0.0)
        spans.append((start, end, 2.0 ** (offset / 12.0)))
        applied.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "pitch": round(float(item["target_midi"]), 3),
                "offset_semitones": round(offset, 3),
            }
        )

    report: dict = {
        "applied": bool(spans),
        "note_count": len(notes or []),
        "applied_notes": len(spans),
        "applied_seconds": round(sum(end - start for start, end, _ in spans), 3),
        "notes": applied,
        "skipped": [
            {
                "start": round(float(item["note"].get("start", 0.0) or 0.0), 3),
                "reason": item.get("reason") or "",
            }
            for item in computed
            if not item.get("applied")
        ],
        "f0_source": "sidecar" if f0_curve is not None and Path(f0_curve).is_file() else "probe",
    }
    if not spans:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(Path(source).read_bytes())
        report["reason"] = "没有音符需要修改"
        return report

    manipulation = call(
        sound,
        "To Manipulation",
        0.01,
        _PRAAT_FLOOR_HZ,
        _PRAAT_CEILING_HZ,
    )
    source_tier = call(manipulation, "Extract pitch tier")
    tier_times, tier_values = _tier_points(source_tier, call)
    if tier_times.size < 2:
        raise RuntimeError("Praat 没有取到可用的音高曲线")
    ratios = _ratio_at(tier_times, spans, float(ramp_seconds))
    modified_tier = call(
        "Create PitchTier",
        "xb-midi-pitch",
        float(sound.xmin),
        float(sound.xmax),
    )
    for time_value, frequency, ratio in zip(tier_times, tier_values, ratios):
        if not math.isfinite(float(frequency)) or frequency <= 0.0:
            continue
        call(
            modified_tier,
            "Add point",
            float(time_value),
            float(frequency) * float(ratio),
        )
    call([modified_tier, manipulation], "Replace pitch tier")
    tuned_sound = call(manipulation, "Get resynthesis (overlap-add)")
    tuned = np.asarray(tuned_sound.values, dtype=np.float64)
    expected = original.shape[-1]
    if tuned.shape[-1] > expected:
        tuned = tuned[..., :expected]
    elif tuned.shape[-1] < expected:
        tuned = np.pad(tuned, ((0, 0), (0, expected - tuned.shape[-1])))

    tuned = _restore_channels(original, tuned)
    blended = _blend_spans(original, tuned, [(start, end) for start, end, _ in spans], rate)
    peak = float(np.max(np.abs(blended))) if blended.size else 0.0
    if peak > 0.99:
        blended *= 0.99 / peak
    if not bool(np.isfinite(blended).all()):
        raise RuntimeError("MIDI 重绘产生了非有限音频样本")
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output), blended.T.astype(np.float32), rate, subtype="PCM_16")
    report["reason"] = ""
    return report


def _load_notes(path: Path) -> list[dict]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    if isinstance(payload, dict):
        payload = payload.get("notes") or []
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def main() -> int:
    parser = argparse.ArgumentParser(description="把 MIDI 音符应用到音频（Praat PSOLA）")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--notes-json", required=True)
    parser.add_argument("--f0-npy", default="")
    parser.add_argument("--report-json", default="")
    parser.add_argument("--min-offset-cents", type=float, default=_DEFAULT_MIN_OFFSET_CENTS)
    parser.add_argument("--max-semitones", type=float, default=_DEFAULT_MAX_SEMITONES)
    args = parser.parse_args()

    source = Path(args.input)
    output = Path(args.output)
    report_path = Path(args.report_json) if args.report_json else None
    report: dict = {"applied": False, "reason": "未执行", "notes": [], "skipped": []}
    try:
        if not source.is_file():
            raise RuntimeError(f"输入不存在：{source}")
        notes = _load_notes(Path(args.notes_json))
        report = apply_notes(
            source,
            output,
            notes,
            f0_curve=Path(args.f0_npy) if args.f0_npy else None,
            min_offset_cents=float(args.min_offset_cents),
            max_semitones=float(args.max_semitones),
        )
    except Exception as exc:  # noqa: BLE001 - 结果以报告返回，调用方需要能回退
        try:
            output.unlink(missing_ok=True)
        except OSError:
            pass
        report = {"applied": False, "reason": f"{type(exc).__name__}: {exc}", "notes": [], "skipped": []}
        print(f"MIDI_PITCH_ERR\t{exc}", flush=True)
        traceback.print_exc()

    if report_path is not None:
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            print(f"MIDI_PITCH_WARN\t报告写入失败: {exc}", flush=True)
    print(
        "MIDI_PITCH\t"
        f"{'ok' if report.get('applied') else 'skip'}\t"
        f"{report.get('applied_notes', 0)}/{report.get('note_count', 0)}\t"
        f"{report.get('applied_seconds', 0.0)}s\t"
        f"{report.get('reason') or ''}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
