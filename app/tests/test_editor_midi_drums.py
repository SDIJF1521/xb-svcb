"""架子鼓（GM 打击乐）支持：鼓件表、鼓件合成、导出通道、用例层渲染。"""

from __future__ import annotations

import json
import types
import wave
from pathlib import Path

import numpy as np
import pytest

from application import midi_synth
from application.audio_editor_service import AudioEditorService
from domain import midi_drums, midi_file, midi_session
from infrastructure.storage import ListRepository

PROJECT_ID = "prj_drums"
TRACK_ID = "trk_drums"


# ---------------------------------------------------------------- 鼓件表


def test_drum_map_covers_gm_percussion() -> None:
    pieces = midi_drums.pieces()
    assert len(pieces) == 47
    assert midi_drums.DRUM_PITCH_MIN == 35
    assert midi_drums.DRUM_PITCH_MAX == 81
    pitches = [piece["pitch"] for piece in pieces]
    assert pitches == list(range(35, 82)), "鼓件音高必须连续覆盖 35~81"
    names = [piece["name_zh"] for piece in pieces]
    assert len(set(names)) == len(names), "鼓件名不能重复"
    assert all(len(name) >= 2 for name in names)


def test_drum_piece_names_are_specific() -> None:
    assert midi_drums.name_zh(35) == "底鼓 2"
    assert midi_drums.name_zh(36) == "底鼓 1"
    assert midi_drums.name_zh(38) == "军鼓 1"
    assert midi_drums.name_zh(42) == "闭合踩镲"
    assert midi_drums.name_zh(46) == "开音踩镲"
    assert midi_drums.name_zh(49) == "吊镲 1"
    assert midi_drums.name_zh(51) == "叮叮镲 1"
    assert midi_drums.name_zh(55) == "水镲"
    assert midi_drums.name_zh(56) == "牛铃"
    assert midi_drums.name_zh(70) == "沙铃"
    assert midi_drums.group_of(36) == "kick"
    assert midi_drums.group_of(49) == "crash"
    assert midi_drums.group_of(46) == "hat_open"


def test_drum_map_snaps_to_nearest_piece() -> None:
    assert midi_drums.nearest_pitch(36) == 36
    assert midi_drums.nearest_pitch(36.4) == 36
    assert midi_drums.nearest_pitch(36.9) == 37
    assert midi_drums.nearest_pitch(0) == 35
    assert midi_drums.nearest_pitch(127) == 81
    assert midi_drums.has_pitch(38) is True
    assert midi_drums.has_pitch(100) is False


def test_drum_notes_are_snapped_by_session_cleaning() -> None:
    session = midi_session.clean_session(
        {
            "parts": [
                {
                    "id": "drums",
                    "name": "架子鼓",
                    "drum": True,
                    "notes": [
                        {"start": 0.0, "end": 0.2, "pitch": 60, "velocity": 100},
                        {"start": 0.25, "end": 0.45, "pitch": 36.6, "velocity": 100},
                        {"start": 0.5, "end": 0.7, "pitch": 90, "velocity": 100},
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
    # 60 本身就是邦戈鼓（高）；36.6 → 37（军鼓边击）；90 越界 → 81（三角铁·开）
    assert pitches == [60, 37, 81]
    assert all(midi_drums.has_pitch(pitch) for pitch in pitches)
    assert midi_drums.name_zh(pitches[0]) == "邦戈鼓（高）"


# ---------------------------------------------------------------- 鼓件合成


def _drum_session(notes: list[dict], *, duration: float = 4.0) -> dict:
    return midi_session.clean_session(
        {"tempo": 120, "parts": [{"id": "drums", "drum": True, "notes": notes}]},
        duration,
    )


@pytest.mark.parametrize(
    ("pitch", "label"),
    [
        (36, "底鼓"),
        (38, "军鼓"),
        (42, "闭合踩镲"),
        (46, "开音踩镲"),
        (49, "吊镲"),
        (50, "通鼓"),
        (56, "牛铃"),
        (70, "沙铃"),
    ],
)
def test_every_kit_piece_produces_sound(pitch: int, label: str) -> None:
    session = _drum_session([{"start": 0.0, "end": 0.25, "pitch": pitch, "velocity": 110}])
    samples = midi_synth.render_session(session, sample_rate=22050)
    assert samples.shape[0] > 0, label
    peak = float(np.max(np.abs(samples)))
    assert peak > 0.02, f"{label} 渲染没有声音"
    assert not bool(np.isnan(samples).any())


def test_velocity_changes_drum_level() -> None:
    soft = midi_synth.render_session(
        _drum_session([{"start": 0.0, "end": 0.2, "pitch": 38, "velocity": 30}]),
        sample_rate=22050,
    )
    loud = midi_synth.render_session(
        _drum_session([{"start": 0.0, "end": 0.2, "pitch": 38, "velocity": 120}]),
        sample_rate=22050,
    )
    assert float(np.max(np.abs(loud))) > float(np.max(np.abs(soft))) * 1.2


def test_open_hat_is_choked_by_closed_hat() -> None:
    session = _drum_session(
        [
            {"start": 0.0, "end": 1.0, "pitch": 46, "velocity": 110},
            {"start": 0.5, "end": 0.6, "pitch": 42, "velocity": 90},
        ]
    )
    samples = midi_synth.render_session(session, sample_rate=22050, reverb=0.0)
    sr = 22050
    before = float(np.max(np.abs(samples[int(0.1 * sr) : int(0.45 * sr)])))
    after = float(np.max(np.abs(samples[int(0.62 * sr) : int(0.95 * sr)])))
    assert before > 0.02
    assert after < before * 0.5, "闭合踩镲应当把开镲掐断"


def test_cymbal_rings_out_past_the_note_length() -> None:
    """架子鼓是「一击」：短音符的镲片也必须能自然响完，不能被音符长度切断。"""
    session = _drum_session([{"start": 0.0, "end": 0.1, "pitch": 49, "velocity": 110}])
    samples = midi_synth.render_session(session, sample_rate=22050, reverb=0.0)
    sr = 22050
    early = float(np.max(np.abs(samples[int(0.02 * sr) : int(0.09 * sr)])))
    late = float(np.max(np.abs(samples[int(0.3 * sr) : int(0.6 * sr)])))
    assert early > 0.02
    assert late > 0.005, "吊镲在音符结束 0.3s 后仍应有余音"


def test_drum_part_renders_next_to_melodic_parts() -> None:
    session = midi_session.clean_session(
        {
            "tempo": 120,
            "parts": [
                {
                    "id": "bass",
                    "name": "贝斯",
                    "instrument": 33,
                    "notes": [{"start": 0.0, "end": 1.0, "pitch": 36, "velocity": 100}],
                },
                {
                    "id": "drums",
                    "name": "架子鼓",
                    "drum": True,
                    "notes": [
                        {"start": 0.0, "end": 0.2, "pitch": 36, "velocity": 118},
                        {"start": 0.5, "end": 0.7, "pitch": 38, "velocity": 104},
                    ],
                },
            ],
        },
        4.0,
    )
    samples = midi_synth.render_session(session, sample_rate=22050)
    assert samples.shape[0] > 0
    assert float(np.max(np.abs(samples))) > 0.1


def test_drum_window_render_only_keeps_the_requested_span() -> None:
    """分乐器渲染时只渲染该声部的时间窗（末尾再留鼓的余音）。"""
    session = _drum_session(
        [
            {"start": 0.0, "end": 0.2, "pitch": 36, "velocity": 110},
            {"start": 2.0, "end": 2.2, "pitch": 38, "velocity": 110},
        ],
        duration=4.0,
    )
    samples = midi_synth.render_part(
        session, session["parts"][0], sample_rate=22050, window=(1.9, 2.3)
    )
    seconds = samples.shape[0] / 22050
    # 0.4 秒窗口 + 鼓组固定的 1.2 秒余音
    assert 1.3 < seconds < 2.0
    assert float(np.max(np.abs(samples))) > 0.02


# ---------------------------------------------------------------- 导出 / 导入


def test_drum_part_exports_on_channel_10() -> None:
    session = _drum_session(
        [
            {"start": 0.0, "end": 0.2, "pitch": 36, "velocity": 118},
            {"start": 0.5, "end": 0.7, "pitch": 42, "velocity": 90},
        ]
    )
    payload = midi_file.build_smf(session)
    parsed = midi_file.parse_smf(payload)
    assert len(parsed["tracks"]) == 1
    track = parsed["tracks"][0]
    assert track["drum"] is True
    assert track["channel"] == midi_session.DRUM_CHANNEL
    assert [note["pitch"] for note in track["notes"]] == [36, 42]

    restored = midi_session.clean_session(midi_file.session_payload(parsed), 4.0)
    assert restored["parts"][0]["drum"] is True
    assert restored["parts"][0]["channel"] == midi_session.DRUM_CHANNEL
    assert all(midi_drums.has_pitch(note["pitch"]) for note in restored["parts"][0]["notes"])


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
        "title": "鼓组测试",
        "sample_rate": 44100,
        "duration": 30.0,
        "waveform_cache": {},
        "tracks": [
            {"id": TRACK_ID, "name": "架子鼓", "type": "audio", "clips": [], "metadata": {}},
        ],
    }


def _service(tmp_path: Path) -> AudioEditorService:
    repo = ListRepository(tmp_path / "editor.json")
    repo.add(_empty_project())
    service = AudioEditorService.__new__(AudioEditorService)
    service._repo = repo
    service.__dict__["_editor_store"] = _FakeStore(tmp_path)
    service.__dict__["_render_service"] = _FakeRenderService()
    service._models = _FakeModels()
    service._midi_pitch = _FakeMidiPitch()
    service._ffmpeg = _FakeFfmpeg()
    return service


def test_midi_session_exposes_drum_kit(tmp_path: Path) -> None:
    service = _service(tmp_path)
    result = service.midi_session(PROJECT_ID, TRACK_ID)
    assert result["ok"] is True
    drums = result["drums"]
    assert len(drums) == 47
    assert drums[1]["pitch"] == 36
    assert drums[1]["name_zh"] == "底鼓 1"
    assert drums[1]["group"] == "kick"
    assert any(piece["name_zh"] == "闭合踩镲" for piece in drums)


def test_render_drum_part_creates_drum_audio_track(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _drum_session(
        [
            {"start": 0.0, "end": 0.2, "pitch": 36, "velocity": 118},
            {"start": 0.5, "end": 0.7, "pitch": 38, "velocity": 104},
            {"start": 0.25, "end": 0.4, "pitch": 42, "velocity": 88},
        ],
        duration=30.0,
    )

    result = service.render_midi_session(PROJECT_ID, TRACK_ID, session, {"mode": "tracks"})

    assert result["ok"] is True, result.get("error")
    created = [
        track
        for track in result["project"]["tracks"]
        if (track.get("metadata") or {}).get("midi_render_source") == TRACK_ID
    ]
    assert len(created) == 1
    assert "架子鼓" in created[0]["name"]
    clip = created[0]["clips"][0]
    assert Path(clip["file"]).is_file()
    assert clip["end"] > clip["start"]
    with wave.open(str(clip["file"]), "rb") as handle:
        assert handle.getframerate() == 44100


def test_save_drum_session_keeps_pitches_on_kit(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = midi_session.clean_session(
        {
            "parts": [
                {
                    "id": "drums",
                    "name": "架子鼓",
                    "drum": True,
                    "notes": [
                        {"start": 0.0, "end": 0.2, "pitch": 36, "velocity": 110},
                        {"start": 0.5, "end": 0.7, "pitch": 41.4, "velocity": 90},
                    ],
                }
            ]
        },
        30.0,
    )
    result = service.save_midi_session(PROJECT_ID, TRACK_ID, session)
    assert result["ok"] is True
    stored = json.loads(
        service._midi_session_path(PROJECT_ID, TRACK_ID).read_text(encoding="utf-8")
    )
    pitches = [note["pitch"] for note in stored["session"]["parts"][0]["notes"]]
    assert pitches == [36, 41], "41.4 应吸附到最接近的鼓件 41（落地嗵鼓·低）"
    assert stored["session"]["parts"][0]["drum"] is True
