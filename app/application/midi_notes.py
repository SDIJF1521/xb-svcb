"""把 F0 曲线切分成可编辑的 MIDI 音符。

MIDI 子编辑器打开时先做一次「分析」：把片段当前的基频曲线切成连音符，按半音
落到钢琴卷帘上，并把偏离半音中心的音分记在 ``detune`` 里。这样没被用户拖动过
的音符在应用时偏移为 0（不会把自然音准洗成电音），只有被改过的音符才真的移调。

规则偏保守：音符至少 0.06 秒、音高连续变化超过 0.6 个半音才切分、清音/辅音
间隙直接断句；结果仍交给领域层归一化。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from domain import editor_midi

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

# 输入曲线可能来自 np.linspace / np.load / 任意浮点数组，统一按「浮点数组」收，
# 函数内部再用 np.asarray(..., dtype=np.float64) 收敛精度。
NoteDict = dict[str, Any]

_MIN_NOTE_SECONDS = 0.06
_SPLIT_SEMITONES = 0.6
_SMOOTH_SECONDS = 0.09
_JOIN_GAP_SECONDS = 0.02


def _median_filter(values: "NDArray[np.floating[Any]]", size: int) -> "NDArray[np.float64]":
    import numpy as np

    data = np.asarray(values, dtype=np.float64).reshape(-1)
    if data.size < 3 or size <= 1:
        return data.copy()
    size = int(size) | 1  # 保持奇数窗口，避免相位偏移
    if size >= data.size:
        return np.full(data.size, float(np.nanmedian(data)), dtype=np.float64)
    padded = np.pad(data, (size // 2, size // 2), mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, size)
    return np.nanmedian(windows, axis=1)


def _frame_spacing(times: "NDArray[np.floating[Any]]") -> float:
    import numpy as np

    values = np.asarray(times, dtype=np.float64).reshape(-1)
    if values.size < 2:
        return 0.01
    spacing = float(np.median(np.diff(values)))
    if not np.isfinite(spacing) or spacing <= 0.0:
        return 0.01
    return spacing


def _voiced_runs(voiced: "NDArray[np.bool_]") -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, flag in enumerate(voiced):
        if flag and start is None:
            start = int(index)
        elif not flag and start is not None:
            runs.append((start, int(index)))
            start = None
    if start is not None:
        runs.append((start, int(voiced.size)))
    return runs


def notes_from_f0(
    times: "NDArray[np.floating[Any]]",
    f0: "NDArray[np.floating[Any]]",
    *,
    min_note_seconds: float = _MIN_NOTE_SECONDS,
    split_semitones: float = _SPLIT_SEMITONES,
    smooth_seconds: float = _SMOOTH_SECONDS,
    duration: float | None = None,
) -> list[NoteDict]:
    """把逐帧 F0 切成音符列表（片段内时间，秒）。"""
    import numpy as np

    values = np.asarray(f0, dtype=np.float64).reshape(-1)
    timeline = np.asarray(times, dtype=np.float64).reshape(-1)
    if values.size < 3:
        return []
    size = min(values.size, timeline.size)
    values = values[:size]
    timeline = timeline[:size]
    finite = np.isfinite(values) & (values > 0.0)
    if not bool(finite.any()):
        return []

    spacing = _frame_spacing(timeline)
    smoothed = _median_filter(np.where(finite, values, 0.0), 5)
    midi = np.full(values.shape, np.nan, dtype=np.float64)
    voiced_values = finite & (smoothed > 0.0)
    midi[voiced_values] = 69.0 + 12.0 * np.log2(smoothed[voiced_values] / 440.0)
    window = max(3, int(round(max(0.02, smooth_seconds) / max(spacing, 1e-4))) | 1)

    limit = float(duration) if duration else float(timeline[-1] + spacing)
    notes: list[NoteDict] = []

    def emit(run_start: int, run_end: int) -> None:
        if run_end - run_start < 3:
            return
        start_time = float(timeline[run_start])
        end_time = float(timeline[min(run_end, timeline.size - 1)] + spacing)
        if end_time - start_time < float(min_note_seconds):
            return
        segment = midi[run_start:run_end]
        segment = segment[np.isfinite(segment)]
        if segment.size < 3:
            return
        median = float(np.median(segment))
        pitch = int(round(median))
        detune = (median - pitch) * 100.0
        notes.append(
            {
                "start": max(0.0, min(limit, start_time)),
                "end": max(0.0, min(limit, end_time)),
                "pitch": float(pitch),
                "detune": round(
                    max(-editor_midi.MAX_DETUNE_CENTS, min(editor_midi.MAX_DETUNE_CENTS, detune)),
                    1,
                ),
            }
        )

    for run_start, run_end in _voiced_runs(voiced_values):
        if run_end - run_start < 3:
            continue
        track = _median_filter(midi[run_start:run_end], window)
        segment_start = 0
        reference = float(np.nanmedian(track[: min(track.size, window)]))
        for offset in range(1, track.size):
            value = track[offset]
            if not np.isfinite(value):
                continue
            if abs(value - reference) > float(split_semitones):
                emit(run_start + segment_start, run_start + offset)
                segment_start = offset
                reference = value
            else:
                # 慢速跟随，允许颤音但不把整句拆碎。
                reference = 0.88 * reference + 0.12 * value
        emit(run_start + segment_start, run_end)

    if not notes:
        return []
    notes.sort(key=lambda note: float(note["start"]))
    joined: list[NoteDict] = []
    for note in notes:
        if joined:
            previous = joined[-1]
            same_pitch = int(previous["pitch"]) == int(note["pitch"])
            close = float(note["start"]) - float(previous["end"]) <= _JOIN_GAP_SECONDS
            if same_pitch and close:
                previous["end"] = max(float(previous["end"]), float(note["end"]))
                continue
        joined.append(dict(note))
    return editor_midi.clean_notes(joined, duration=limit)
