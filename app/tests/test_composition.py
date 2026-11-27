"""组合根冒烟测试：用隔离的数据目录验证依赖装配是否完整。"""

from __future__ import annotations

import importlib
import sys
import wave
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


@pytest.fixture()
def wired_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """在隔离数据目录里跑一次组合根装配，结束后恢复全局配置。"""
    import config

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("XB_DATA_DIR", str(data_dir))
    importlib.reload(config)
    assert config.DATA_DIR == data_dir.resolve()

    import composition

    importlib.reload(composition)
    api = composition.build_api()
    try:
        yield api
    finally:
        api.shutdown()
        # 还原数据目录，避免污染同一次测试会话里的其它用例。
        monkeypatch.delenv("XB_DATA_DIR", raising=False)
        importlib.reload(config)


def test_build_api_wires_every_use_case(wired_api) -> None:  # noqa: ANN001
    """组合根应把仓储、用例服务与端口全部接上。"""
    from application import (
        AudioEditorService,
        AudioImportService,
        MediaService,
        ModelHubService,
        ModelService,
        MusicService,
        PluginService,
        RealtimeCoverService,
        SystemService,
        ThemeMediaService,
        WorkService,
        WorkflowHubService,
    )
    from application.ports import ItemRepository, PymssGateway, SettingsRepository

    api = wired_api
    assert isinstance(api._system, SystemService)
    assert isinstance(api._models, ModelService)
    assert isinstance(api._works, WorkService)
    assert isinstance(api._music, MusicService)
    assert isinstance(api._hub, ModelHubService)
    assert isinstance(api._workflow_hub, WorkflowHubService)
    assert isinstance(api._editor, AudioEditorService)
    assert isinstance(api._plugins, PluginService)
    assert isinstance(api._realtime_cover, RealtimeCoverService)
    assert isinstance(api._media, MediaService)
    assert isinstance(api._theme_media, ThemeMediaService)
    assert isinstance(api._audio_import, AudioImportService)
    # 表现层只持有端口协议，不持有具体基础设施类型
    assert isinstance(api._pymss, PymssGateway)
    assert isinstance(api._models_repo, ItemRepository)
    assert isinstance(api._settings, SettingsRepository)

    # 公开入口可用且返回空数据目录应有的结果
    assert api.list_models() == []
    assert api.list_works() == []
    assert api.list_editor_projects() == []
    assert api.get_theme_media_data("") == ""
    assert api.import_audio_data("song.mid", "QUJD") is None
    # 播放器直通：缺失音频时返回可读错误，而不是抛异常
    assert api.get_work_stream("missing")["ok"] is False
    assert api.get_music_stream("")["ok"] is False
    assert api.import_editor_project_to_works("missing")["ok"] is False


def test_editor_import_bridge_archives_a_render(
    wired_api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: ANN001
    """即使环境没有 FFmpeg，桥接层也应能把已有渲染归档为作品。"""
    source = tmp_path / "editor-source.wav"
    rendered = tmp_path / "editor-rendered.wav"
    for path in (source, rendered):
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(8000)
            handle.writeframes(b"\x00\x00" * 8000)

    project = wired_api.create_editor_project_from_audio(str(source), "编辑器测试")
    assert project is not None
    monkeypatch.setattr(wired_api._editor, "render", lambda *_args, **_kwargs: rendered)

    result = wired_api.import_editor_project_to_works(project["id"], "wav")
    assert result["ok"] is True, result
    work = result["work"]
    assert work["status"] == "done"
    assert work["workflow"] == "audio_editor"
    assert Path(work["output_path"]).is_file()


def test_editor_render_can_be_imported_into_works(wired_api, tmp_path: Path) -> None:  # noqa: ANN001
    """编辑器成品应能渲染、归档并出现在作品列表中。"""
    tools = wired_api.get_system_status().get("tools") or []
    if not any(tool.get("key") == "ffmpeg" and tool.get("ok") for tool in tools):
        pytest.skip("FFmpeg is required to render the editor timeline")

    source = tmp_path / "editor-source.wav"
    with wave.open(str(source), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 8000)

    project = wired_api.create_editor_project_from_audio(str(source), "编辑器测试")
    assert project is not None

    result = wired_api.import_editor_project_to_works(project["id"], "wav")
    assert result["ok"] is True, result
    work = result["work"]
    assert work["status"] == "done"
    assert work["workflow"] == "audio_editor"
    assert work["model"] == "音频编辑器"
    output = Path(work["output_path"])
    assert output.is_file()
    assert output.read_bytes() == source.read_bytes() or output.stat().st_size > 44
    assert any(item["id"] == work["id"] for item in wired_api.list_works())


def test_composition_is_the_only_assembler() -> None:
    """入口只通过组合根获取门面，表现层包不导出装配函数。"""
    import api
    import composition

    assert not hasattr(api, "build_api")
    assert callable(composition.build_api)
