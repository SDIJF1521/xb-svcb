"""编辑器 MIDI 子编辑器（音符规则 / F0 切分 / 音高重绘 / 用例）单元测试。"""

from __future__ import annotations

import json
import subprocess
import types
import wave
from pathlib import Path

import numpy as np
import pytest

import config
from application import midi_notes
from application.audio_editor_service import AudioEditorService
from domain import editor_midi
from infrastructure import midi_pitch
from infrastructure.midi_pitch_worker import _ratio_at, note_offsets
from infrastructure.storage import ListRepository

CLIP_ID = "clip_midi_1"
TRACK_ID = "trk_midi_1"
PROJECT_ID = "prj_midi_1"


# ---------------------------------------------------------------- 领域规则


def test_pitch_helpers_round_trip() -> None:
    assert editor_midi.midi_to_hz(69) == pytest.approx(440.0)
    assert editor_midi.hz_to_midi(440.0) == pytest.approx(69.0)
    assert editor_midi.hz_to_midi(0.0) == 0.0
    assert editor_midi.note_name(60) == "C4"
    assert editor_midi.note_name(57) == "A3"
    assert editor_midi.note_name(61.4) == "C#4"


def test_clean_notes_trims_overlaps_and_clamps() -> None:
    notes = editor_midi.clean_notes(
        [
            {"start": 0.0, "end": 2.0, "pitch": 60},
            {"start": 1.5, "end": 3.0, "pitch": 62},
            {"start": 3.5, "end": 9.0, "pitch": 64, "detune": 300},
            {"start": 3.99, "end": 4.0, "pitch": 66},
        ],
        4.0,
    )

    assert [note["id"] for note in notes][0].startswith("midi_")
    assert notes[0]["end"] == pytest.approx(1.5)  # 被后一个音截断
    assert notes[1]["end"] == pytest.approx(3.0)
    assert notes[2]["end"] == pytest.approx(4.0)  # 裁剪到片段时长
    assert notes[2]["detune"] == pytest.approx(99.0)  # 音分上限
    assert len(notes) == 3  # 过短的碎片被丢弃


def test_clean_notes_keeps_explicit_ids_and_limits_duplicates() -> None:
    notes = editor_midi.clean_notes(
        [
            {"id": "same", "start": 0.0, "end": 0.5, "pitch": 60},
            {"id": "same", "start": 0.6, "end": 1.0, "pitch": 61},
        ],
        2.0,
    )
    assert notes[0]["id"] == "same"
    assert notes[1]["id"] != "same"


def test_target_midi_applies_detune_cents() -> None:
    assert editor_midi.target_midi({"pitch": 60, "detune": 50}) == pytest.approx(60.5)
    assert editor_midi.target_midi({"pitch": 60}) == pytest.approx(60.0)


# ---------------------------------------------------------------- F0 → 音符


def _frames(duration: float, rate: float = 100.0) -> np.ndarray:
    return np.arange(0.0, duration, 1.0 / rate)


def test_notes_from_f0_splits_two_sustained_notes() -> None:
    times = _frames(4.0)
    f0 = np.where(times < 2.0, 220.0, 261.6256).astype(np.float32)

    notes = midi_notes.notes_from_f0(times, f0, duration=4.0)

    assert len(notes) == 2
    assert notes[0]["pitch"] == pytest.approx(57.0)
    assert notes[1]["pitch"] == pytest.approx(60.0)
    assert notes[0]["end"] <= 2.05
    assert notes[1]["end"] <= 4.02
    assert all(abs(note["detune"]) <= 99 for note in notes)


def test_notes_from_f0_keeps_vibrato_as_one_note() -> None:
    times = _frames(2.0)
    f0 = 220.0 * (2.0 ** (0.3 / 12.0 * np.sin(2 * np.pi * 5.5 * times)))

    notes = midi_notes.notes_from_f0(times, f0.astype(np.float32), duration=2.0)

    assert len(notes) == 1
    assert notes[0]["pitch"] == pytest.approx(57.0)


def test_notes_from_f0_returns_nothing_for_silence() -> None:
    times = _frames(2.0)
    f0 = np.zeros(times.shape, dtype=np.float32)
    assert midi_notes.notes_from_f0(times, f0, duration=2.0) == []


def test_notes_from_f0_splits_on_unvoiced_gap() -> None:
    times = _frames(4.0)
    f0 = np.full(times.shape, 220.0, dtype=np.float32)
    f0[(times >= 1.8) & (times <= 2.2)] = 0.0

    notes = midi_notes.notes_from_f0(times, f0, duration=4.0)

    assert len(notes) == 2
    assert notes[0]["end"] <= 1.9
    assert notes[1]["start"] >= 2.1


# ---------------------------------------------------------------- 音高重绘计算


def test_note_offsets_only_moves_edited_notes() -> None:
    times = _frames(4.0)
    f0 = np.full(times.shape, 220.0)
    notes = [
        {"start": 0.0, "end": 2.0, "pitch": 57.0, "detune": 0.0},
        {"start": 2.0, "end": 4.0, "pitch": 60.0, "detune": 0.0},
    ]

    results = note_offsets(notes, times, f0)

    assert results[0]["applied"] is False
    assert results[1]["applied"] is True
    assert results[1]["offset_semitones"] == pytest.approx(3.0, abs=0.05)
    assert results[1]["source_midi"] == pytest.approx(57.0, abs=0.05)


def test_note_offsets_clamps_and_skips_unvoiced_spans() -> None:
    times = _frames(2.0)
    f0 = np.full(times.shape, 220.0)
    f0[times >= 1.0] = 0.0
    notes = [
        {"start": 0.0, "end": 1.0, "pitch": 90.0, "detune": 0.0},
        {"start": 1.0, "end": 2.0, "pitch": 60.0, "detune": 0.0},
    ]

    results = note_offsets(notes, times, f0, max_semitones=12.0)

    assert results[0]["applied"] is True
    assert results[0]["offset_semitones"] == pytest.approx(12.0)
    assert results[1]["applied"] is False
    assert "浊音" in results[1]["reason"]


def test_clean_f0_drops_octave_spikes_and_keeps_real_pitch() -> None:
    """原始音高清理：单帧跳八度/爆音被丢掉，正常音高与清音标记保留。"""
    values = np.full(20, 220.0)
    values[10] = 440.0  # 整帧跳八度
    values[12] = 0.0  # 清音
    values[15] = 660.0  # 爆音（约 +9 半音）
    cleaned = AudioEditorService._clean_f0(values)

    assert cleaned[0] == pytest.approx(220.0)
    assert cleaned[10] == 0.0
    assert cleaned[12] == 0.0
    assert cleaned[15] == 0.0


def test_f0_points_downsample_and_skip_unvoiced(tmp_path: Path) -> None:
    """原始音高曲线：清音帧要跳过、点数受限、时间落在片段内、Hz 正确转成 MIDI。"""
    path = tmp_path / "clip_f0.npy"
    values = np.full(200, 220.0, dtype=np.float32)
    values[:40] = 0.0  # 清音
    np.save(str(path), values)

    points = AudioEditorService._f0_points(path, 2.0, max_points=50)

    assert points
    assert len(points) <= 50
    assert all(0.0 <= time <= 2.0 for time, _ in points)
    assert all(abs(midi - 57.0) < 0.01 for _, midi in points)  # 220Hz = A3


def test_curve_helpers_clamp_shift_and_interpolate() -> None:
    curve = editor_midi.clamp_curve(
        [
            {"t": -1.0, "v": 0.0},
            {"t": 0.5, "v": 1.0},
            {"t": 99.0, "v": 99.0},
            {"t": 0.5, "v": 2.0},
        ],
        1.0,
    )
    assert curve is not None
    # 同一时刻只保留最后一个点（去重后时间严格递增），避免垂直跳变
    assert [point["t"] for point in curve] == pytest.approx([0.0, 0.5, 1.0])
    assert curve[1]["v"] == pytest.approx(2.0)
    assert curve[-1]["v"] == pytest.approx(editor_midi.CURVE_SEMITONE_LIMIT)

    # 少于两个点不算曲线
    assert editor_midi.clamp_curve([{"t": 0.0, "v": 1.0}], 1.0) is None

    simple = [{"t": 0.0, "v": 0.0}, {"t": 1.0, "v": 2.0}]
    assert editor_midi.curve_value_at(simple, 0.5) == pytest.approx(1.0)
    assert editor_midi.curve_value_at(simple, -1.0) == pytest.approx(0.0)
    assert editor_midi.curve_value_at(simple, 9.0) == pytest.approx(2.0)

    shifted = editor_midi.shift_curve(simple, 0.25, 0.75)
    assert shifted is not None
    assert shifted[0]["t"] == pytest.approx(0.0)
    assert shifted[-1]["t"] == pytest.approx(0.75)
    assert shifted[-1]["v"] == pytest.approx(2.0)


def test_note_offsets_applies_curve_only_notes() -> None:
    """整体没偏移、但画了音高曲线的音符也要重绘（否则滑音/颤音被跳过）。"""
    times = _frames(2.0)
    f0 = np.full(times.shape, 220.0)
    notes = [
        {
            "start": 0.0,
            "end": 1.5,
            "pitch": 57.0,
            "detune": 0.0,
            "curve": [{"t": 0.0, "v": 0.0}, {"t": 1.5, "v": 2.0}],
        },
        {"start": 0.0, "end": 1.5, "pitch": 57.0, "detune": 0.0},
    ]

    results = note_offsets(notes, times, f0)

    assert results[0]["applied"] is True
    assert results[0]["curve"] is True
    assert results[0]["offset_semitones"] == pytest.approx(0.0, abs=0.05)
    assert results[1]["applied"] is False


def test_clean_note_keeps_curve_and_clamps_it() -> None:
    note = editor_midi.clean_note(
        {
            "start": 1.0,
            "end": 2.0,
            "pitch": 60,
            "detune": 0,
            "curve": [{"t": 0.0, "v": 0.0}, {"t": 5.0, "v": 3.0}],
        },
        4.0,
    )
    assert note is not None
    assert note["curve"] == [{"t": 0.0, "v": 0.0}, {"t": 1.0, "v": 3.0}]


def test_ratio_at_follows_curve_within_note() -> None:
    """有曲线时按「绝对目标音高 / 实际音高」算倍率，音符外保持 1。

    这里故意让原唱保持在 220Hz（A3=57），曲线从 0 升到 +12 半音，
    期望倍率依次是 1 / √2 / 2 —— 不会把原唱自身的偏差再叠加一次。
    """
    times = np.array([0.0, 0.5, 1.0, 1.5, 2.0, 2.5], dtype=np.float64)
    tier_hz = np.full(times.shape, 220.0, dtype=np.float64)
    spans = [(1.0, 2.0, 0.0, [{"t": 0.0, "v": 0.0}, {"t": 1.0, "v": 12.0}], 57.0)]

    ratios = _ratio_at(times, spans, 0.0, tier_hz)

    assert ratios[0] == pytest.approx(1.0)
    assert ratios[1] == pytest.approx(1.0)  # 音符之前
    assert ratios[2] == pytest.approx(1.0)  # 音符起点：曲线 0
    assert ratios[3] == pytest.approx(2 ** (6 / 12))  # 中点：曲线 +6 半音
    assert ratios[4] == pytest.approx(2.0)  # 终点：曲线 +12 半音
    assert ratios[5] == pytest.approx(1.0)  # 音符之后


def test_ratio_at_without_curve_keeps_flat_offset() -> None:
    """没有曲线时只整体平移，不凭空改变音高轮廓（保留原唱自身的颤音）。"""
    times = np.array([0.0, 1.0, 2.0], dtype=np.float64)
    tier_hz = np.array([220.0, 220.0, 220.0], dtype=np.float64)
    spans = [(0.0, 2.0, 2.0, None, 57.0)]

    ratios = _ratio_at(times, spans, 0.0, tier_hz)

    assert ratios.tolist() == pytest.approx([2 ** (2 / 12)] * 3)


# ---------------------------------------------------------------- 适配器


def test_processor_unavailable_without_runtime(monkeypatch) -> None:
    monkeypatch.setattr(config, "VOCAL_ENHANCEMENT_PYTHON", None)
    processor = midi_pitch.MidiPitchProcessor()

    assert processor.available is False
    result = processor.apply(
        source=Path("in.wav"),
        notes=[{"start": 0, "end": 1, "pitch": 60}],
        destination=Path("out.wav"),
    )
    assert result["applied"] is False
    assert "未就绪" in result["reason"]


def test_processor_builds_command_and_parses_report(
    tmp_path: Path, monkeypatch
) -> None:
    python = tmp_path / "python.exe"
    worker = tmp_path / "midi_pitch_worker.py"
    python.write_bytes(b"")
    worker.write_bytes(b"")
    monkeypatch.setattr(config, "VOCAL_ENHANCEMENT_PYTHON", python)
    monkeypatch.setattr(config, "MIDI_PITCH_WORKER", worker)
    source = tmp_path / "in.wav"
    source.write_bytes(b"audio")
    destination = tmp_path / "out.wav"
    f0_curve = tmp_path / "f0.npy"
    f0_curve.write_bytes(b"npy")
    captured: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        captured.append(command)
        Path(command[command.index("--output") + 1]).write_bytes(b"rendered")
        Path(command[command.index("--report-json") + 1]).write_text(
            json.dumps(
                {
                    "applied": True,
                    "applied_notes": 1,
                    "applied_seconds": 0.5,
                    "notes": [{"start": 0.0, "end": 0.5, "pitch": 60.0}],
                    "skipped": [],
                    "reason": "",
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("infrastructure.midi_pitch.subprocess.run", fake_run)

    result = midi_pitch.MidiPitchProcessor().apply(
        source=source,
        notes=[{"start": 0.0, "end": 0.5, "pitch": 60.0, "detune": 0.0}],
        destination=destination,
        f0_curve=f0_curve,
    )

    assert result["applied"] is True
    assert result["applied_notes"] == 1
    command = captured[0]
    assert command[command.index("--f0-npy") + 1] == str(f0_curve)
    notes_path = Path(command[command.index("--notes-json") + 1])
    assert json.loads(notes_path.read_text(encoding="utf-8"))[0]["pitch"] == 60.0


# ---------------------------------------------------------------- 用例层


class _FakeStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def project_dir(self, project_id: str) -> Path:
        folder = self._root / "projects" / project_id
        folder.mkdir(parents=True, exist_ok=True)
        return folder


class _FakeAudio:
    def __init__(self) -> None:
        self.trim_calls: list[tuple[Path, float, float]] = []

    def trim(self, src: Path, start: float, end: float, dst: Path, **kwargs) -> bool:
        self.trim_calls.append((src, start, end))
        dst.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(dst), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(44100)
            handle.writeframes(np.zeros(int(44100 * max(0.01, end - start)), dtype="<i2").tobytes())
        return True


class _FakeModels:
    def get(self, _model_id: str):
        return None


class _FakeMidiPitch:
    def __init__(self, result: dict | None = None, available: bool = True) -> None:
        self.available = available
        self.calls: list[dict] = []
        self._result = result or {}

    def apply(self, **kwargs):
        self.calls.append(kwargs)
        destination = Path(kwargs["destination"])
        if self._result.get("applied"):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"rendered")
        return {**self._result, "output": destination if self._result.get("applied") else None}


def _write_audio(path: Path, seconds: float = 4.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(44100)
        handle.writeframes(np.zeros(int(44100 * seconds), dtype="<i2").tobytes())


def _project(audio: Path, *, duration: float = 4.0) -> dict:
    return {
        "id": PROJECT_ID,
        "title": "MIDI",
        "sample_rate": 44100,
        "duration": duration,
        "waveform_cache": {},
        "tracks": [
            {
                "id": TRACK_ID,
                "name": "人声",
                "type": "audio",
                "clips": [
                    {
                        "id": CLIP_ID,
                        "start": 0.0,
                        "end": duration,
                        "offset": 0.0,
                        "volume": 1.0,
                        "mute": False,
                        "file": str(audio),
                        "name": "主唱",
                        "effects": [],
                        "metadata": {},
                    }
                ],
            }
        ],
    }


def _service(tmp_path: Path, project: dict, *, midi=None) -> AudioEditorService:
    repo = ListRepository(tmp_path / "editor.json")
    repo.add(project)
    service = AudioEditorService.__new__(AudioEditorService)
    service._repo = repo
    service.__dict__["_editor_store"] = _FakeStore(tmp_path)
    service.__dict__["_render_service"] = types.SimpleNamespace(_audio=_FakeAudio())
    service._models = _FakeModels()
    service._midi_pitch = midi or _FakeMidiPitch({"applied": True, "applied_notes": 1})
    return service


def test_clip_midi_reuses_fresh_sidecar(tmp_path: Path) -> None:
    audio = tmp_path / "clip.wav"
    _write_audio(audio)
    service = _service(tmp_path, _project(audio))
    midi_path = service._midi_path(PROJECT_ID, CLIP_ID)
    midi_path.write_text(
        json.dumps(
            {
                **service._audio_signature(audio),
                "clip_id": CLIP_ID,
                "duration": 4.0,
                "notes": [{"start": 0.25, "end": 0.75, "pitch": 60.0, "detune": 0.0}],
                "analysis": {"voiced_ratio": 0.9, "median_hz": 260.0},
            }
        ),
        encoding="utf-8",
    )

    result = service.clip_midi(PROJECT_ID, CLIP_ID)

    assert result["ok"] is True
    assert result["cached"] is True
    assert len(result["notes"]) == 1
    assert result["notes"][0]["pitch"] == pytest.approx(60.0)


def test_clip_midi_analyses_and_caches(tmp_path: Path, monkeypatch) -> None:
    audio = tmp_path / "clip.wav"
    _write_audio(audio)
    service = _service(tmp_path, _project(audio))

    def fake_analyse(self, project_id, clip_id, source, clip, duration):
        return {
            "ok": True,
            "notes": [{"start": 0.1, "end": 0.6, "pitch": 62.0, "detune": 12.0}],
            "analysis": {"voiced_ratio": 0.8, "note_count": 1},
        }

    monkeypatch.setattr(AudioEditorService, "_analyse_clip_notes", fake_analyse)

    result = service.clip_midi(PROJECT_ID, CLIP_ID)

    assert result["ok"] is True
    assert result["cached"] is False
    assert result["notes"][0]["detune"] == pytest.approx(12.0)
    sidecar = json.loads(
        (service._midi_path(PROJECT_ID, CLIP_ID)).read_text(encoding="utf-8")
    )
    assert sidecar["notes"][0]["pitch"] == pytest.approx(62.0)


def test_save_clip_midi_writes_sidecar_and_metadata(tmp_path: Path) -> None:
    audio = tmp_path / "clip.wav"
    _write_audio(audio)
    service = _service(tmp_path, _project(audio))

    result = service.save_clip_midi(
        PROJECT_ID,
        CLIP_ID,
        [
            {"start": 0.0, "end": 0.5, "pitch": 60.0, "detune": 0.0},
            {"start": 0.6, "end": 1.2, "pitch": 64.0, "detune": 0.0},
        ],
    )

    assert result["ok"] is True
    assert result["meta"]["note_count"] == 2
    sidecar = json.loads(
        service._midi_path(PROJECT_ID, CLIP_ID).read_text(encoding="utf-8")
    )
    assert len(sidecar["notes"]) == 2
    saved = service._repo.get(PROJECT_ID)
    clip = saved["tracks"][0]["clips"][0]
    assert clip["metadata"]["midi"]["note_count"] == 2
    assert saved["history"], "保存 MIDI 应推入一次撤销历史"


def test_apply_clip_midi_replaces_clip_audio(tmp_path: Path) -> None:
    audio = tmp_path / "clip.wav"
    _write_audio(audio)
    midi = _FakeMidiPitch({"applied": True, "applied_notes": 1, "applied_seconds": 0.5})
    service = _service(tmp_path, _project(audio), midi=midi)

    result = service.apply_clip_midi(
        PROJECT_ID,
        CLIP_ID,
        [{"start": 0.0, "end": 0.5, "pitch": 64.0, "detune": 0.0}],
    )

    assert result["ok"] is True, result
    assert midi.calls, "没有调用音高重绘"
    assert midi.calls[0]["notes"][0]["pitch"] == pytest.approx(64.0)
    clip = result["clip"]
    assert str(clip["file"]).endswith(".wav")
    assert clip["offset"] == pytest.approx(0.0)
    assert "MIDI" in clip["name"]
    assert clip["metadata"]["midi"]["applied_notes"] == 1
    assert result["report"]["applied_seconds"] == pytest.approx(0.5)
    sidecar = json.loads(
        service._midi_path(PROJECT_ID, CLIP_ID).read_text(encoding="utf-8")
    )
    assert sidecar["audio"] == str(clip["file"])


def test_apply_clip_midi_reports_when_nothing_changes(tmp_path: Path) -> None:
    audio = tmp_path / "clip.wav"
    _write_audio(audio)
    midi = _FakeMidiPitch({"applied": False, "reason": "没有音符需要修改"})
    service = _service(tmp_path, _project(audio), midi=midi)

    result = service.apply_clip_midi(
        PROJECT_ID,
        CLIP_ID,
        [{"start": 0.0, "end": 0.5, "pitch": 60.0, "detune": 0.0}],
    )

    assert result["ok"] is False
    assert "没有音符需要修改" in result["error"]


def test_apply_clip_midi_rejects_missing_notes(tmp_path: Path) -> None:
    audio = tmp_path / "clip.wav"
    _write_audio(audio)
    service = _service(tmp_path, _project(audio))

    result = service.apply_clip_midi(PROJECT_ID, CLIP_ID, [])

    assert result["ok"] is False
    assert "没有 MIDI 音符" in result["error"]


# ---------------------------------------------------------------- 轨道范围


def _track_project(tmp_path: Path, *, empty: bool = False) -> dict:
    """两段片段的音轨：0-2s 与 3-5s；empty=True 时是空白音轨。"""
    first = tmp_path / "one.wav"
    second = tmp_path / "two.wav"
    _write_audio(first, 2.0)
    _write_audio(second, 2.0)
    clips = []
    if not empty:
        clips = [
            {
                "id": "clip_a",
                "start": 0.0,
                "end": 2.0,
                "offset": 0.0,
                "volume": 1.0,
                "mute": False,
                "file": str(first),
                "name": "A",
                "effects": [],
                "metadata": {},
            },
            {
                "id": "clip_b",
                "start": 3.0,
                "end": 5.0,
                "offset": 0.0,
                "volume": 1.0,
                "mute": False,
                "file": str(second),
                "name": "B",
                "effects": [],
                "metadata": {},
            },
        ]
    return {
        "id": PROJECT_ID,
        "title": "track",
        "sample_rate": 44100,
        "duration": 5.0,
        "waveform_cache": {},
        "tracks": [
            {
                "id": TRACK_ID,
                "name": "人声",
                "type": "audio",
                "clips": clips,
                "metadata": {},
            }
        ],
    }


def test_track_midi_returns_editable_grid_for_empty_track(tmp_path: Path) -> None:
    service = _service(tmp_path, _track_project(tmp_path, empty=True))

    result = service.track_midi(PROJECT_ID, TRACK_ID)

    assert result["ok"] is True
    assert result["scope"] == "track"
    assert result["notes"] == []
    assert result["clip_spans"] == []
    assert result["duration"] >= 0.3


def test_track_midi_merges_clip_notes_into_absolute_time(
    tmp_path: Path, monkeypatch
) -> None:
    service = _service(tmp_path, _track_project(tmp_path))

    def fake_analyse(self, project_id, clip_id, source, clip, duration):
        base = 60.0 if clip_id == "clip_a" else 64.0
        return {
            "ok": True,
            "notes": [{"start": 0.1, "end": 0.6, "pitch": base, "detune": 0.0}],
            "analysis": {"note_count": 1},
        }

    monkeypatch.setattr(AudioEditorService, "_analyse_clip_notes", fake_analyse)

    result = service.track_midi(PROJECT_ID, TRACK_ID)

    assert result["ok"] is True
    assert [note["pitch"] for note in result["notes"]] == [60.0, 64.0]
    assert result["notes"][0]["start"] == pytest.approx(0.1)
    assert result["notes"][1]["start"] == pytest.approx(3.1)
    assert result["notes"][1]["end"] == pytest.approx(3.6)
    assert len(result["clip_spans"]) == 2


def test_save_track_midi_records_track_metadata(tmp_path: Path) -> None:
    service = _service(tmp_path, _track_project(tmp_path))

    result = service.save_track_midi(
        PROJECT_ID,
        TRACK_ID,
        [
            {"start": 0.5, "end": 1.0, "pitch": 62.0, "detune": 0.0},
            {"start": 3.2, "end": 3.8, "pitch": 65.0, "detune": 0.0},
        ],
    )

    assert result["ok"] is True
    assert result["meta"]["scope"] == "track"
    assert result["meta"]["note_count"] == 2
    sidecar = json.loads(
        service._midi_path(PROJECT_ID, TRACK_ID).read_text(encoding="utf-8")
    )
    assert len(sidecar["notes"]) == 2
    saved = service._repo.get(PROJECT_ID)
    assert saved["tracks"][0]["metadata"]["midi"]["note_count"] == 2
    assert saved["history"], "保存轨道 MIDI 应推入一次撤销历史"


def test_apply_track_midi_renders_each_clip(tmp_path: Path) -> None:
    midi = _FakeMidiPitch({"applied": True, "applied_notes": 1, "applied_seconds": 0.5})
    service = _service(tmp_path, _track_project(tmp_path), midi=midi)

    result = service.apply_track_midi(
        PROJECT_ID,
        TRACK_ID,
        [
            {"start": 0.2, "end": 0.8, "pitch": 62.0, "detune": 0.0},
            {"start": 3.2, "end": 3.8, "pitch": 66.0, "detune": 0.0},
        ],
    )

    assert result["ok"] is True, result
    assert len(midi.calls) == 2, "每个片段应各自重绘一次"
    assert [call["notes"][0]["start"] for call in midi.calls] == pytest.approx([0.2, 0.2])
    assert len(result["clips"]) == 2
    saved = service._repo.get(PROJECT_ID)
    assert len(saved["history"]) == 1, "整轨应用只推入一次撤销历史"
    assert saved["tracks"][0]["metadata"]["midi"]["applied_notes"] == 2
    sidecar = json.loads(
        service._midi_path(PROJECT_ID, TRACK_ID).read_text(encoding="utf-8")
    )
    assert sidecar["scope"] == "track"
    assert len(sidecar["notes"]) == 2


def test_apply_track_midi_without_clips_explains(tmp_path: Path) -> None:
    service = _service(tmp_path, _track_project(tmp_path, empty=True))

    result = service.apply_track_midi(
        PROJECT_ID,
        TRACK_ID,
        [{"start": 0.2, "end": 0.8, "pitch": 62.0, "detune": 0.0}],
    )

    assert result["ok"] is False
    assert "没有可用片段" in result["error"]


def test_apply_track_midi_without_overlap_explains(tmp_path: Path) -> None:
    service = _service(tmp_path, _track_project(tmp_path))

    result = service.apply_track_midi(
        PROJECT_ID,
        TRACK_ID,
        [{"start": 2.2, "end": 2.8, "pitch": 62.0, "detune": 0.0}],
    )

    assert result["ok"] is False
    assert "没有音符落在" in result["error"]
