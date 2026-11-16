"""编辑器自动生成的音轨名 / 工程名要跟随界面语言。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from application.audio_editor_service import _TRACK_LABELS, _label


def test_known_labels_are_translated() -> None:
    assert _label("原始音频", "en-US") == "Original audio"
    assert _label("翻唱成品", "en-US") == "Cover mix"
    assert _label("素材", "en-US") == "Material"
    assert _label("人声", "en-US") == "Vocals"
    assert _label("音轨 1", "en-US") == "Track 1"
    assert _label("空白工程", "ja-JP") == "空のプロジェクト"


def test_chinese_locale_keeps_original_names() -> None:
    for name in _TRACK_LABELS["en-US"]:
        assert _label(name, "zh-CN") == name
        assert _label(name, "xx-YY") == name


def test_unknown_and_user_names_are_kept() -> None:
    # 用户自定义的音轨名不能被改写
    assert _label("主歌", "en-US") == "主歌"
    assert _label("My Track", "en-US") == "My Track"
    assert _label("", "en-US") == ""


def test_every_locale_covers_the_same_keys() -> None:
    assert set(_TRACK_LABELS["en-US"]) == set(_TRACK_LABELS["ja-JP"])
