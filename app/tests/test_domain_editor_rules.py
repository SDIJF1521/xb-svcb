"""编辑器领域规则与歌词解析的单测（domain/audio_editor_rules.py、domain/lyrics.py）。"""

from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from domain.audio_editor_rules import (
    clean_effects,
    clean_project,
    clean_volume_envelope,
    clip_duration,
    clip_stretch,
    find_clip,
    find_clip_ref,
    find_effect,
    is_plugin_effect,
    normalize_channel,
    normalize_format,
    project_duration,
    should_render_waveform,
)
from domain.lyrics import (
    auto_time_lyric_lines,
    parse_lyric_lines,
    parse_plain_lyric_lines,
    speech_ranges_from_silence,
)


# ---- 效果链 / 包络 / 度量 ----


def test_clean_effects_normalizes_and_preserves_unknown_fields() -> None:
    effects = clean_effects(
        [
            {"type": "VST3", "params": {"mix": 0.5}, "plugin_path": "C:/p.vst3"},
            {"type": ""},
            "garbage",
            {"id": "fx_1", "type": "reverb", "enabled": False, "params": "bad"},
        ]
    )

    assert [effect["type"] for effect in effects] == ["vst3", "reverb"]
    # 插件路径等未知字段原样保留，缺失 id 时补一个
    assert effects[0]["plugin_path"] == "C:/p.vst3"
    assert effects[0]["id"].startswith("fx_")
    assert effects[1]["enabled"] is False
    assert effects[1]["params"] == {}
    assert effects[1]["name"] == "reverb"


def test_plugin_effect_detection_covers_alias_names() -> None:
    for effect_type in ("plugin", "VST", "vst3", "external_plugin", "juce_vst3"):
        assert is_plugin_effect({"type": effect_type}) is True
    assert is_plugin_effect({"type": "reverb"}) is False
    assert is_plugin_effect({}) is False


def test_clean_volume_envelope_clamps_and_sorts_points() -> None:
    envelope = clean_volume_envelope(
        [
            {"time": 4.0, "volume": 9.0},
            {"t": -1.0, "value": -2.0},
            {"time": 1.0, "volume": 0.5},
            {"time": 1.0, "volume": 0.7},
            {"time": "bad", "volume": 1.0},
        ],
        duration=3.0,
    )

    assert envelope == [
        {"time": 0.0, "volume": 0.0},
        {"time": 1.0, "volume": 0.7},
        {"time": 3.0, "volume": 2.5},
    ]


def test_clip_metrics_and_channel_normalization() -> None:
    clip = {"start": 2.0, "end": 6.5, "time_stretch": 9.0, "channel": "LEFT"}
    assert clip_duration(clip) == 4.5
    assert clip_stretch(clip) == 4.0
    assert normalize_channel(clip.get("channel")) == "left"
    assert normalize_channel("weird") == "stereo"
    assert normalize_format("MP3") == "mp3"
    assert normalize_format("ogg") == "wav"
    assert project_duration({"tracks": [{"clips": [{"end": 12.5}]}]}) == 12.5
    assert project_duration({}) == 0.05


def test_should_render_waveform_detects_processing() -> None:
    assert should_render_waveform({"time_stretch": 1.0, "volume": 1.0}) is False
    assert should_render_waveform({"time_stretch": 1.5}) is True
    assert should_render_waveform({"channel": "left"}) is True
    assert should_render_waveform({"effects": [{"type": "reverb"}]}) is True
    assert should_render_waveform({"volume_envelope": [{"time": 0, "volume": 1}]}) is True
    assert should_render_waveform({"fade_in": 0.4}) is True


def test_clean_project_normalizes_tracks_clips_and_drops_history() -> None:
    project = {
        "id": "edt_1",
        "tracks": [
            {
                "id": "trk_1",
                "clips": [
                    {
                        "id": "clp_1",
                        "start": 0.0,
                        "end": 2.0,
                        "channel": "weird",
                        "time_stretch": 0.1,
                        "effects": [{"type": "EQ"}],
                        "volume_envelope": [{"time": 5.0, "volume": 1.0}],
                    }
                ],
            }
        ],
        "roles": [{"id": "role_1", "effects": [{"type": "plugin"}]}],
        "history": [{"x": 1}],
        "future": [{"y": 2}],
    }

    cleaned = clean_project(project)

    assert "history" not in cleaned and "future" not in cleaned
    clip = cleaned["tracks"][0]["clips"][0]
    assert clip["channel"] == "stereo"
    assert clip["time_stretch"] == 0.25
    assert clip["effects"][0]["type"] == "eq"
    assert clip["volume_envelope"] == [{"time": 2.0, "volume": 1.0}]
    assert cleaned["roles"][0]["effects"][0]["type"] == "plugin"
    assert cleaned["waveform_cache"] == {}
    # 原工程不被就地修改
    assert project["tracks"][0]["clips"][0]["channel"] == "weird"


def test_lookup_helpers_find_clip_track_ref_and_effect() -> None:
    clip = {"id": "clp_1", "effects": [{"id": "fx_1", "type": "reverb"}]}
    project = {"tracks": [{"id": "trk_1", "clips": [clip]}]}

    assert find_clip(project, "clp_1") is clip
    assert find_clip(project, "missing") is None
    assert find_clip(None, "clp_1") is None

    track, index, found = find_clip_ref(project, "trk_1", "clp_1")
    assert track is project["tracks"][0]
    assert index == 0
    assert found is clip
    assert find_clip_ref(project, "other", "clp_1") == (None, -1, None)

    assert find_effect(clip, "fx_1") is clip["effects"][0]
    assert find_effect(clip, "fx_9") is None


# ---- 歌词解析 / 配时 ----


def test_parse_lrc_lines_reads_timestamps_and_sorting() -> None:
    lines = parse_lyric_lines("[00:12.50]第一句\n[01:02.345]第二句\n[00:05]第三句")
    assert lines == [
        {"time": 5.0, "text": "第三句"},
        {"time": 12.5, "text": "第一句"},
        {"time": 62.345, "text": "第二句"},
    ]


def test_parse_structured_lyrics_skips_invalid_entries() -> None:
    lines = parse_lyric_lines(
        [
            {"time": 2.0, "text": "b"},
            {"time": -1, "text": "bad"},
            {"start": 1.0, "text": "a"},
            "garbage",
        ]
    )
    assert lines == [{"time": 1.0, "text": "a"}, {"time": 2.0, "text": "b"}]


def test_parse_plain_lines_drops_metadata_and_splits_sentences() -> None:
    texts = parse_plain_lyric_lines("[ar:歌手]\n第一句。第二句！\n\n第三句")
    assert texts == ["第一句。", "第二句！", "第三句"]


def test_auto_time_lyric_lines_snaps_to_nearest_silence() -> None:
    lines = auto_time_lyric_lines(
        ["第一句", "第二句"],
        duration=10.0,
        silence_points=[4.6, 9.9],
        min_clip=0.5,
    )
    assert lines[0]["time"] == 0.0
    # 比例切点在 5.0s 附近，吸附到 4.6s 的静音点
    assert lines[1]["time"] == 4.6
    assert [line["text"] for line in lines] == ["第一句", "第二句"]


def test_auto_time_lyric_lines_handles_empty_input() -> None:
    assert auto_time_lyric_lines([], 10.0, [1.0], 0.5) == []
    assert auto_time_lyric_lines(["x"], 0.0, [], 0.5) == []


def test_speech_ranges_from_silence_merges_and_pads() -> None:
    ranges = speech_ranges_from_silence(
        duration=10.0,
        silences=[
            {"start": 3.0, "end": 3.6},
            {"start": 6.0, "end": 6.6},
        ],
        min_clip=0.5,
        padding=0.05,
        min_silence=0.2,
    )
    assert ranges == [(0.0, 3.05), (3.55, 6.05), (6.55, 10.0)]


def test_speech_ranges_ignores_short_silence_and_merges_gaps() -> None:
    ranges = speech_ranges_from_silence(
        duration=5.0,
        silences=[{"start": 2.0, "end": 2.1}],
        min_clip=0.5,
        padding=0.0,
        min_silence=0.3,
    )
    assert ranges == [(0.0, 5.0)]
