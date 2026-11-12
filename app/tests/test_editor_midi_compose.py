"""MIDI 编曲（多乐器音序器）的测试：会话归一化、SMF 读写、合成渲染、用例层。

这里覆盖「空轨道也能写歌 → 出音频 / 出 .mid」这条主链路，是用例层的护栏。
"""

from __future__ import annotations

import json
import time
import types
import wave
from pathlib import Path

import numpy as np
import config
import pytest

from application import midi_synth
from application import audio_editor_service as editor_service_module
from application.audio_editor_service import AudioEditorService
from domain import midi_file, midi_instruments, midi_session
from infrastructure.storage import ListRepository

PROJECT_ID = "prj_compose"
TRACK_ID = "trk_compose"


def _session(parts=None, *, tempo: float = 120.0) -> dict:
    return midi_session.clean_session(
        {
            "tempo": tempo,
            "time_signature": [4, 4],
            "parts": parts
            if parts is not None
            else [
                {
                    "id": "part_1",
                    "name": "钢琴",
                    "instrument": 0,
                    "notes": [
                        {"start": 0.0, "end": 0.5, "pitch": 60, "velocity": 100},
                        {"start": 0.5, "end": 1.0, "pitch": 64, "velocity": 80},
                    ],
                }
            ],
        },
        30.0,
    )


# ---------------------------------------------------------------- 领域层


def test_clean_session_clamps_tempo_and_signature() -> None:
    session = midi_session.clean_session(
        {"tempo": 9999, "time_signature": [13, 7], "parts": []}, 20.0
    )
    assert session["tempo"] == midi_session.MAX_TEMPO
    assert session["time_signature"] == [4, 4]
    assert len(session["parts"]) == 1, "没有声部时必须自动补一个空声部"


def test_clean_session_forces_drum_channel_and_clamps_notes() -> None:
    session = midi_session.clean_session(
        {
            "parts": [
                {
                    "id": "drums",
                    "drum": True,
                    "channel": 3,
                    "instrument": 33,
                    "notes": [
                        {"start": 1.0, "end": 40.0, "pitch": 200, "velocity": 999},
                        {"start": -5.0, "end": 0.5, "pitch": -3, "velocity": 0},
                        {"start": 2.0, "end": 2.001, "pitch": 36, "velocity": 90},
                    ],
                }
            ]
        },
        4.0,
    )
    part = session["parts"][0]
    assert part["drum"] is True
    assert part["channel"] == midi_session.DRUM_CHANNEL
    pitches = [note["pitch"] for note in part["notes"]]
    assert all(0 <= pitch <= 127 for pitch in pitches)
    assert all(1 <= note["velocity"] <= 127 for note in part["notes"])
    assert all(note["end"] <= 4.0 for note in part["notes"])
    # 0.001 秒的碎片被丢弃
    assert all(note["end"] - note["start"] >= midi_session.MIN_NOTE_SECONDS for note in part["notes"])


def test_clean_session_keeps_part_ids_unique_and_colors() -> None:
    session = midi_session.clean_session(
        {
            "parts": [
                {"id": "same", "instrument": 0, "notes": []},
                {"id": "same", "instrument": 48, "notes": []},
                {"instrument": 32, "notes": []},
            ]
        },
        10.0,
    )
    ids = [part["id"] for part in session["parts"]]
    assert len(set(ids)) == 3
    colors = [part["color"] for part in session["parts"]]
    assert all(color.startswith("#") for color in colors)
    assert len(set(colors)) == 3


def test_session_from_notes_migrates_legacy_notes() -> None:
    session = midi_session.session_from_notes(
        [
            {"start": 0.2, "end": 0.6, "pitch": 62.4, "detune": 20},
            {"start": 0.8, "end": 1.2, "pitch": 65},
        ],
        duration=4.0,
        instrument=48,
        name="主唱",
    )
    assert len(session["parts"]) == 1
    part = session["parts"][0]
    assert part["instrument"] == 48
    assert part["name"] == "主唱"
    assert len(part["notes"]) == 2
    assert part["notes"][0]["pitch"] == 62
    assert midi_session.session_duration(session) == pytest.approx(1.2)


def test_instrument_catalog_covers_gm_128() -> None:
    catalog = midi_instruments.catalog()
    assert len(catalog) == 128
    assert catalog[0]["name_zh"] == "原声大钢琴"
    assert catalog[47]["family"] == "strings"
    assert midi_instruments.instrument(999)["program"] == 127
    families = midi_instruments.families()
    assert len(families) == 16
    assert sum(len(family["programs"]) for family in families) == 128


# ---------------------------------------------------------------- SMF 文件


def test_smf_round_trip_keeps_parts_instruments_and_velocity() -> None:
    session = _session(
        [
            {
                "id": "p1",
                "name": "主奏",
                "instrument": 40,
                "channel": 1,
                "notes": [
                    {"start": 0.0, "end": 0.5, "pitch": 67, "velocity": 120},
                    {"start": 0.5, "end": 1.25, "pitch": 69, "velocity": 70},
                ],
            },
            {
                "id": "p2",
                "name": "鼓组",
                "drum": True,
                "notes": [{"start": 0.0, "end": 0.1, "pitch": 36, "velocity": 110}],
            },
        ]
    )
    payload = midi_file.build_smf(session)
    assert payload[:4] == b"MThd"

    parsed = midi_file.parse_smf(payload)
    assert parsed["tempo"] == pytest.approx(120.0)
    assert parsed["time_signature"] == [4, 4]
    assert [track["program"] for track in parsed["tracks"]] == [40, 0]
    assert parsed["tracks"][1]["drum"] is True
    assert parsed["tracks"][0]["notes"][0]["pitch"] == 67
    assert parsed["tracks"][0]["notes"][0]["velocity"] == 120
    assert parsed["tracks"][0]["notes"][1]["start"] == pytest.approx(0.5, abs=0.01)
    assert parsed["tracks"][0]["notes"][1]["end"] == pytest.approx(1.25, abs=0.01)

    restored = midi_session.clean_session(
        midi_file.session_payload(parsed), 30.0
    )
    assert midi_session.session_note_count(restored) == 3
    assert restored["parts"][0]["instrument"] == 40


def test_parse_smf_rejects_non_midi() -> None:
    with pytest.raises(midi_file.MidiFileError):
        midi_file.parse_smf(b"not a midi file at all")


# ---------------------------------------------------------------- 合成渲染


def test_render_session_produces_audio_of_expected_length() -> None:
    session = _session()
    samples = midi_synth.render_session(session, sample_rate=22050)
    assert samples.ndim == 2 and samples.shape[1] == 2
    seconds = samples.shape[0] / 22050.0
    assert 1.0 <= seconds <= 2.0, "渲染长度应覆盖最后一个音符并留一点尾巴"
    assert float(np.max(np.abs(samples))) > 0.05
    assert not bool(np.isnan(samples).any())


def test_render_session_reports_monotonic_progress() -> None:
    seen: list[float] = []
    midi_synth.render_session(_session(), sample_rate=22050, progress=seen.append)

    assert seen, "渲染应上报进度"
    assert seen[-1] == pytest.approx(1.0)
    assert all(later >= earlier for earlier, later in zip(seen, seen[1:]))


def test_render_session_is_deterministic_with_note_cache() -> None:
    session = _session()
    first = midi_synth.render_session(session, sample_rate=22050)
    second = midi_synth.render_session(session, sample_rate=22050)

    assert np.array_equal(first, second)


def test_render_session_handles_every_family_without_failure() -> None:
    notes = [{"start": 0.0, "end": 0.3, "pitch": 60, "velocity": 96}]
    parts = [
        {
            "id": f"p{index}",
            "instrument": index * 8,
            "notes": notes,
            "channel": index,
        }
        for index in range(16)
    ]
    session = _session(parts)
    samples = midi_synth.render_session(session, sample_rate=22050)
    assert samples.shape[0] > 0
    assert float(np.max(np.abs(samples))) > 0.05


def test_render_session_respects_mute_and_solo() -> None:
    parts = [
        {
            "id": "a",
            "instrument": 0,
            "notes": [{"start": 0.0, "end": 0.5, "pitch": 60, "velocity": 100}],
        },
        {
            "id": "b",
            "instrument": 0,
            "notes": [{"start": 0.0, "end": 0.5, "pitch": 72, "velocity": 100}],
            "mute": True,
        },
    ]
    session = _session(parts)
    muted_all = midi_synth.render_session(
        {**session, "parts": [session["parts"][1]]}, sample_rate=22050
    )
    assert muted_all.shape[0] == 0, "全部静音时不应产生音频"

    soloed = midi_session.audible_parts({**session, "parts": [session["parts"][0], session["parts"][1]]})
    assert [part["id"] for part in soloed] == ["a"]


def test_write_wav_creates_playable_file(tmp_path: Path) -> None:
    destination = tmp_path / "out" / "render.wav"
    samples = np.zeros((2205, 2), dtype=np.float32)
    samples[:, :] = 0.25
    assert midi_synth.write_wav(destination, samples, 22050) is True
    with wave.open(str(destination), "rb") as handle:
        assert handle.getnchannels() == 2
        assert handle.getframerate() == 22050
        assert handle.getnframes() == 2205


# ---------------------------------------------------------------- 用例层


class _FakeStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def project_dir(self, project_id: str) -> Path:
        folder = self._root / "projects" / project_id
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def cache_path(self, name: str) -> Path:
        folder = self._root / "cache"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / name

    def audio_data_uri(self, source: Path, *, exact: bool = False) -> str:
        return f"data:audio/wav;base64,{Path(source).name}"


class _FakeRenderService:
    def __init__(self) -> None:
        self._audio = types.SimpleNamespace()

    def _render_clip_file(self, *args, **kwargs):
        return None


class _FakeModels:
    def get(self, _model_id: str):
        return None


class _FakeMidiPitch:
    available = True

    def apply(self, **kwargs):
        return {"applied": False, "reason": "not used"}


class _FakeFfmpeg:
    def probe_duration(self, _path):
        return 30.0


def _empty_project() -> dict:
    return {
        "id": PROJECT_ID,
        "title": "编曲测试",
        "sample_rate": 44100,
        "duration": 30.0,
        "waveform_cache": {},
        "tracks": [
            {"id": TRACK_ID, "name": "合成器", "type": "audio", "clips": [], "metadata": {}},
        ],
    }


def _service(tmp_path: Path, project: dict | None = None) -> AudioEditorService:
    repo = ListRepository(tmp_path / "editor.json")
    repo.add(project or _empty_project())
    service = AudioEditorService.__new__(AudioEditorService)
    service._repo = repo
    service.__dict__["_editor_store"] = _FakeStore(tmp_path)
    service.__dict__["_render_service"] = _FakeRenderService()
    service._models = _FakeModels()
    service._midi_pitch = _FakeMidiPitch()
    service._ffmpeg = _FakeFfmpeg()
    return service


def test_preview_clip_midi_returns_audio_without_saving(tmp_path: Path, monkeypatch) -> None:
    clip_file = tmp_path / "clip.wav"
    clip_file.write_bytes(b"audio")
    project = {
        "id": PROJECT_ID,
        "title": "试听测试",
        "sample_rate": 44100,
        "duration": 10.0,
        "waveform_cache": {},
        "tracks": [
            {
                "id": TRACK_ID,
                "name": "人声",
                "type": "audio",
                "clips": [
                    {
                        "id": "clp_test",
                        "name": "片段",
                        "start": 0.0,
                        "end": 2.0,
                        "offset": 0.0,
                        "file": str(clip_file),
                    }
                ],
            }
        ],
    }
    service = _service(tmp_path, project)
    before = json.dumps(service._repo.get(PROJECT_ID), ensure_ascii=False, sort_keys=True)

    preview_file = tmp_path / "midi-preview.wav"
    preview_file.write_bytes(b"\0" * 128)

    def fake_apply(clip, notes, folder, **_kwargs):
        return {**clip, "file": str(preview_file)}, {"applied_notes": len(notes)}

    monkeypatch.setattr(service, "_apply_notes_to_clip", fake_apply)

    result = service.preview_clip_midi(
        PROJECT_ID,
        "clp_test",
        [{"start": 0.0, "end": 0.5, "pitch": 62, "velocity": 100}],
    )

    assert result["ok"] is True, result.get("error")
    assert str(result["audio"]).startswith("data:audio/")
    after = json.dumps(service._repo.get(PROJECT_ID), ensure_ascii=False, sort_keys=True)
    assert after == before


def test_midi_session_works_on_empty_track(tmp_path: Path) -> None:
    service = _service(tmp_path)

    result = service.midi_session(PROJECT_ID, TRACK_ID)

    assert result["ok"] is True
    assert result["has_audio"] is False
    assert result["duration"] >= 60.0
    assert len(result["session"]["parts"]) == 1
    assert result["session"]["parts"][0]["notes"] == []
    assert len(result["instruments"]) == 128
    assert result["clip_spans"] == []


def test_save_midi_session_persists_sidecar_and_metadata(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _session()

    result = service.save_midi_session(PROJECT_ID, TRACK_ID, session)

    assert result["ok"] is True
    assert result["summary"]["note_count"] == 2
    sidecar = service._midi_session_path(PROJECT_ID, TRACK_ID)
    assert sidecar.is_file()
    stored = json.loads(sidecar.read_text(encoding="utf-8"))
    assert stored["scope"] == "compose"
    assert len(stored["session"]["parts"][0]["notes"]) == 2
    project = service._repo.get(PROJECT_ID)
    assert project["tracks"][0]["metadata"]["midi_compose"]["note_count"] == 2

    reopened = service.midi_session(PROJECT_ID, TRACK_ID)
    assert midi_session.session_note_count(reopened["session"]) == 2


def test_render_midi_session_on_empty_track_creates_instrument_tracks(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _session(
        [
            {
                "id": "p1",
                "name": "钢琴",
                "instrument": 0,
                "notes": [{"start": 0.0, "end": 0.5, "pitch": 60, "velocity": 100}],
            },
            {
                "id": "p2",
                "name": "贝斯",
                "instrument": 33,
                "notes": [{"start": 0.0, "end": 1.0, "pitch": 36, "velocity": 90}],
            },
        ]
    )

    result = service.render_midi_session(PROJECT_ID, TRACK_ID, session, {"mode": "tracks"})

    assert result["ok"] is True, result.get("error")
    assert result["mode"] == "tracks"
    assert len(result["tracks"]) == 2
    project = result["project"]
    rendered_tracks = [
        track
        for track in project["tracks"]
        if (track.get("metadata") or {}).get("midi_render_source") == TRACK_ID
    ]
    assert len(rendered_tracks) == 2
    names = [track["name"] for track in rendered_tracks]
    assert any("钢琴" in name for name in names)
    assert any("贝斯" in name for name in names)
    for track in rendered_tracks:
        clip = track["clips"][0]
        assert Path(clip["file"]).is_file()
        assert clip["end"] > clip["start"]

    # 再渲染一次不应重复堆叠音轨
    again = service.render_midi_session(PROJECT_ID, TRACK_ID, session, {"mode": "tracks"})
    assert again["ok"] is True
    rerendered = [
        track
        for track in again["project"]["tracks"]
        if (track.get("metadata") or {}).get("midi_render_source") == TRACK_ID
    ]
    assert len(rerendered) == 2


def test_midi_f0_analysis_uses_the_svc_runtime(tmp_path: Path, monkeypatch) -> None:
    svc_python = tmp_path / "svc-python.exe"
    svc_python.write_bytes(b"")
    worker = tmp_path / "f0_worker.py"
    worker.write_bytes(b"")
    repo = tmp_path / "so-vits-svc"
    repo.mkdir()
    output = tmp_path / "f0.npy"
    captured: dict[str, list[str]] = {}

    def fake_run(cmd, **_kwargs):
        captured["cmd"] = list(cmd)
        output.write_bytes(b"\0" * 128)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(config, "SVC_PYTHON", svc_python)
    monkeypatch.setattr(config, "F0_WORKER", worker)
    monkeypatch.setattr(config, "SOVITS_REPO", repo)
    monkeypatch.setattr(editor_service_module.subprocess, "run", fake_run)

    service = AudioEditorService.__new__(AudioEditorService)
    assert service._run_f0_analysis(tmp_path / "in.wav", output, {}) is True
    assert captured["cmd"][0] == str(svc_python)
    assert "--repo" in captured["cmd"]


def test_midi_analysis_ready_requires_the_svc_runtime(monkeypatch) -> None:
    monkeypatch.setattr(config, "SVC_PYTHON", None)
    assert config.midi_analysis_ready() is False


def test_start_midi_render_reports_progress_and_result(tmp_path: Path) -> None:
    service = _service(tmp_path)
    started = service.start_midi_render(PROJECT_ID, TRACK_ID, _session(), {"mode": "mix"})

    assert started["ok"] is True
    job_id = started["job_id"]
    state: dict | None = None
    deadline = time.time() + 10.0
    while time.time() < deadline:
        state = service.midi_render_status(job_id)
        assert state is not None
        if state["status"] in {"done", "error"}:
            break
        time.sleep(0.02)

    assert state is not None
    assert state["status"] == "done", state.get("error")
    assert state["result"]["ok"] is True
    assert state["progress"] == 100
    assert state["message"]
    assert service.midi_render_status("missing") is None


def test_render_midi_session_mix_mode_replaces_previous_clip(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _session()

    first = service.render_midi_session(PROJECT_ID, TRACK_ID, session, {"mode": "mix"})
    assert first["ok"] is True, first.get("error")
    track = next(t for t in first["project"]["tracks"] if t["id"] == TRACK_ID)
    assert len(track["clips"]) == 1
    clip = track["clips"][0]
    assert Path(clip["file"]).is_file()
    assert clip["metadata"]["midi_render"]["mode"] == "mix"

    second = service.render_midi_session(PROJECT_ID, TRACK_ID, session, {"mode": "mix"})
    assert second["ok"] is True
    track = next(t for t in second["project"]["tracks"] if t["id"] == TRACK_ID)
    assert len(track["clips"]) == 1, "混合渲染应替换上一次生成的片段而不是叠加"


def test_render_midi_session_without_notes_explains(tmp_path: Path) -> None:
    service = _service(tmp_path)
    result = service.render_midi_session(PROJECT_ID, TRACK_ID, _session([]), {"mode": "tracks"})
    assert result["ok"] is False
    assert "音符" in str(result["error"])


def test_export_and_import_midi_session(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _session(
        [
            {
                "id": "p1",
                "name": "长笛",
                "instrument": 73,
                "notes": [{"start": 0.0, "end": 0.75, "pitch": 79, "velocity": 96}],
            }
        ],
        tempo=96.0,
    )

    exported = service.export_midi_session(PROJECT_ID, TRACK_ID, session)
    assert exported["ok"] is True, exported.get("error")
    path = Path(exported["path"])
    assert path.suffix == ".mid"
    assert path.is_file() and path.stat().st_size > 20

    imported = service.import_midi_session(PROJECT_ID, TRACK_ID, str(path))
    assert imported["ok"] is True, imported.get("error")
    assert imported["tempo"] == pytest.approx(96.0)
    parts = imported["session"]["parts"]
    assert len(parts) == 1
    assert parts[0]["instrument"] == 73
    assert parts[0]["notes"][0]["pitch"] == 79
    assert parts[0]["notes"][0]["velocity"] == 96


def test_import_midi_session_reports_missing_file(tmp_path: Path) -> None:
    service = _service(tmp_path)
    result = service.import_midi_session(PROJECT_ID, TRACK_ID, str(tmp_path / "nope.mid"))
    assert result["ok"] is False
    assert "不存在" in str(result["error"])


def test_preview_midi_session_returns_data_uri(tmp_path: Path) -> None:
    service = _service(tmp_path)
    result = service.preview_midi_session(PROJECT_ID, TRACK_ID, _session())
    assert result["ok"] is True, result.get("error")
    assert str(result["audio"]).startswith("data:audio/wav;base64,")
    assert result["duration"] > 0.0
