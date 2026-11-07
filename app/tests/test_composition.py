"""组合根冒烟测试：用隔离的数据目录验证依赖装配是否完整。"""

from __future__ import annotations

import importlib
import sys
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
    )
    from application.ports import ItemRepository, PymssGateway, SettingsRepository

    api = wired_api
    assert isinstance(api._system, SystemService)
    assert isinstance(api._models, ModelService)
    assert isinstance(api._works, WorkService)
    assert isinstance(api._music, MusicService)
    assert isinstance(api._hub, ModelHubService)
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


def test_composition_is_the_only_assembler() -> None:
    """入口只通过组合根获取门面，表现层包不导出装配函数。"""
    import api
    import composition

    assert not hasattr(api, "build_api")
    assert callable(composition.build_api)
