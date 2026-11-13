"""原生打开 / 保存对话框的多语言支持。"""
from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api import bridge, dialog_text
from api.bridge import Api


class _FakeEditor:
    """记录界面语言是否同步给了编辑器服务。"""

    def __init__(self) -> None:
        self.locales: list[str] = []

    def set_ui_locale(self, locale: str) -> None:
        self.locales.append(locale)


class _FakeWindow:
    """记录 pywebview 对话框收到的参数。"""

    def __init__(self, result="C:/out.wav") -> None:
        self.calls: list[tuple[int, dict]] = []
        self._result = result

    def create_file_dialog(self, dialog_type, **kwargs):  # noqa: ANN001, ANN003
        self.calls.append((dialog_type, kwargs))
        return self._result


def _fake_webview() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        OPEN_DIALOG=10,
        SAVE_DIALOG=11,
        FOLDER_DIALOG=12,
        windows=[],
        active_window=lambda: None,
    )


def _reset_locale() -> None:
    bridge._UI_LOCALE = "zh-CN"


def test_normalize_locale_falls_back_to_chinese() -> None:
    assert dialog_text.normalize_locale("en-US") == "en-US"
    assert dialog_text.normalize_locale("ja-JP") == "ja-JP"
    assert dialog_text.normalize_locale("fr-FR") == "zh-CN"
    assert dialog_text.normalize_locale(None) == "zh-CN"


def test_translate_dialog_text_covers_titles_and_default_names() -> None:
    assert dialog_text.translate_dialog_text("选择歌曲音频", "en-US") == "Choose song audio"
    assert dialog_text.translate_dialog_text("实时翻唱.wav", "en-US") == "Realtime cover.wav"
    assert dialog_text.translate_dialog_text("导出翻唱作品 · WAV", "en-US") == "Export cover · WAV"
    assert (
        dialog_text.translate_dialog_text("导出翻唱作品 · WAV", "ja-JP")
        == "カバー作品を書き出し · WAV"
    )
    # 用户数据（作品名 / 路径）不能被改写
    assert dialog_text.translate_dialog_text("我的歌", "en-US") == "我的歌"


def test_translate_file_type_keeps_extension_spec() -> None:
    assert (
        dialog_text.translate_file_type(
            "音频文件 (*.mp3;*.wav;*.flac;*.m4a;*.ogg;*.aac)", "en-US"
        )
        == "Audio files (*.mp3;*.wav;*.flac;*.m4a;*.ogg;*.aac)"
    )
    assert dialog_text.translate_file_type("所有文件 (*.*)", "ja-JP") == "すべてのファイル (*.*)"
    assert dialog_text.translate_file_type("我的格式 (*.abc)", "en-US") == "我的格式 (*.abc)"


def test_api_set_ui_locale_drives_dialog_text() -> None:
    api = object.__new__(Api)
    api._editor = _FakeEditor()
    try:
        assert api.set_ui_locale("en-US") is True
        assert api._dialog_text("选择歌词文件") == "Choose a lyrics file"
        assert api._dialog_file_types(("歌词文件 (*.lrc;*.txt)", "所有文件 (*.*)")) == (
            "Lyrics files (*.lrc;*.txt)",
            "All files (*.*)",
        )
        # 语言同时同步给编辑器，自动生成的音轨名才会本地化
        assert api._editor.locales == ["en-US"]

        assert api.set_ui_locale("ja-JP") is True
        assert api._dialog_text("选择歌词文件") == "歌詞ファイルを選択"

        # 非法语言回到简体中文
        assert api.set_ui_locale("xx-YY") is True
        assert api._dialog_text("选择歌词文件") == "选择歌词文件"
        assert api._editor.locales == ["en-US", "ja-JP", "zh-CN"]
    finally:
        _reset_locale()


def test_set_ui_locale_without_editor_does_not_raise() -> None:
    """回归：缺少 _editor（例如精简构造的实例）时不能抛出。"""
    api = object.__new__(Api)
    try:
        assert api.set_ui_locale("en-US") is True
        assert api._dialog_text("选择歌词文件") == "Choose a lyrics file"
    finally:
        _reset_locale()


def test_save_dialog_localizes_default_name_and_filter(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setitem(sys.modules, "webview", _fake_webview())
    window = _FakeWindow()
    api = object.__new__(Api)
    api._window = window
    try:
        api.set_ui_locale("en-US")
        assert api._save_dialog("导出实时翻唱", "实时翻唱.wav", ("音频文件 (*.wav)",))
        _, kwargs = window.calls[0]
        assert kwargs["save_filename"] == "Realtime cover.wav"
        assert kwargs["file_types"] == ("Audio files (*.wav)",)

        api.set_ui_locale("ja-JP")
        window.calls.clear()
        assert api._save_dialog("导出音频编辑工程", "我的歌.xbproject", ("音频编辑工程 (*.xbproject)",))
        _, kwargs = window.calls[0]
        # 用户的作品名不能被改写
        assert kwargs["save_filename"] == "我的歌.xbproject"
        assert kwargs["file_types"] == ("音声編集プロジェクト (*.xbproject)",)
    finally:
        _reset_locale()


def test_open_dialog_localizes_file_type_names(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setitem(sys.modules, "webview", _fake_webview())
    window = _FakeWindow(result=("C:/song.mp3",))
    api = object.__new__(Api)
    api._window = window
    try:
        api.set_ui_locale("en-US")
        paths = api._open_dialog(
            "选择歌曲音频",
            False,
            ("音频文件 (*.mp3;*.wav)", "所有文件 (*.*)"),
        )
        assert paths == ["C:/song.mp3"]
        _, kwargs = window.calls[0]
        assert kwargs["file_types"] == (
            "Audio files (*.mp3;*.wav)",
            "All files (*.*)",
        )
    finally:
        _reset_locale()
