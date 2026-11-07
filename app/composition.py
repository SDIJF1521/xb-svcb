"""组合根（composition root）。

**唯一**允许同时依赖 ``infrastructure``、``application`` 与 ``api`` 的地方：
在这里创建具体适配器、仓储、用例服务，再把它们注入表现层 ``Api``。

依赖方向（详见 ``docs/ddd-architecture.md``）：

    api -> application -> domain        （模块级 import 只允许这个方向）
    infrastructure -> domain            （实现端口）
    composition -> 全部                 （装配）

因此本文件不属于任何一层，入口 ``main.py`` 只调用 ``build_api()``，
表现层内部不再 import 基础设施，用例服务也不再 import 具体实现。
"""

from __future__ import annotations

import config
from api.bridge import Api
from application import (
    AudioEditorService,
    AudioImportService,
    ConversionService,
    DataMaintenanceService,
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
from infrastructure import paths
from infrastructure.ddsp_engine import DdspSvcEngine
from infrastructure.engine import EngineRegistry
from infrastructure.ffmpeg_tool import FfmpegTool
from infrastructure.high_note_vocoder import HighNoteVocoderProcessor
from infrastructure.pymss_tool import PymssTool
from infrastructure.rvc_engine import RvcEngine
from infrastructure.seedvc_engine import SeedVcEngine
from infrastructure.storage import ListRepository, SettingsStore
from infrastructure.svc_engine import SvcEngine
from infrastructure.theme_media import ThemeMediaStore
from infrastructure.uvr_tool import UvrTool
from infrastructure.vocal_enhancement import VocalEnhancementProcessor
from infrastructure.audio_import import AudioImportStore
from infrastructure.editor_project_store import EditorProjectStore
from infrastructure.work_files import WorkFiles
from infrastructure.data_transfer import DataTransfer
from infrastructure.window_theme import apply as apply_window_theme


def build_api() -> Api:
    """装配基础设施、仓储与应用服务，返回桌面桥接门面。"""
    paths.ensure_dirs()

    # ---- 基础设施适配器 ----
    ffmpeg = FfmpegTool()
    uvr = UvrTool()
    pymss = PymssTool()
    svc = SvcEngine()
    rvc = RvcEngine()
    seedvc = SeedVcEngine()
    ddsp = DdspSvcEngine()
    vocal_enhancement = VocalEnhancementProcessor()
    high_note_vocoder = HighNoteVocoderProcessor()
    # 引擎注册表：按模型 framework 路由推理引擎（缺省回退 so-vits-svc）
    engines = EngineRegistry([svc, rvc, seedvc, ddsp])

    # ---- 仓储 ----
    models_repo = ListRepository(config.MODELS_DB)
    works_repo = ListRepository(config.WORKS_DB)
    editor_repo = ListRepository(config.EDITOR_PROJECTS_DB)
    settings = SettingsStore(config.SETTINGS_DB)

    # ---- 应用服务 ----
    system_service = SystemService(
        ffmpeg, uvr, svc, rvc, seedvc, ddsp, vocal_enhancement, pymss
    )
    model_service = ModelService(models_repo, settings)
    conversion_service = ConversionService(
        works_repo,
        ffmpeg,
        uvr,
        engines,
        vocal_enhancement,
        pymss,
        high_note_vocoder,
    )
    work_files = WorkFiles()
    work_service = WorkService(
        works_repo, conversion_service, model_service, settings, files=work_files
    )
    music_service = MusicService(settings)
    hub_service = ModelHubService(settings, model_service)
    editor_service = AudioEditorService(
        editor_repo,
        works_repo,
        model_service,
        ffmpeg,
        uvr,
        engines,
        vocal_enhancement,
        pymss,
        store=EditorProjectStore(ffmpeg),
        high_note_vocoder=high_note_vocoder,
    )
    plugin_service = PluginService(settings)
    realtime_cover_service = RealtimeCoverService(model_service, ffmpeg, uvr, engines)
    media_service = MediaService(works_repo, ffmpeg)
    theme_media_service = ThemeMediaService(ThemeMediaStore())
    audio_import_service = AudioImportService(AudioImportStore())
    data_maintenance_service = DataMaintenanceService(
        models_repo,
        works_repo,
        editor_repo,
        settings,
        queue_status=work_service.queue_status,
        transfer=DataTransfer(),
    )

    # 启动时回收上次会话残留的"处理中"任务（其后台线程已随进程退出而终止）
    work_service.recover_stale()

    api = Api(
        system_service,
        model_service,
        work_service,
        music_service,
        hub_service,
        editor_service,
        models_repo,
        works_repo,
        editor_repo,
        settings,
        plugin_service,
        realtime_cover_service,
        media_service,
        theme_media_service,
        audio_import_service,
        pymss,
        data_maintenance_service,
        cleanup_temp=paths.clear_temp_directory,
        window_theme=apply_window_theme,
    )
    # HTTP 服务归属表现层，创建门面之后再把「是否在运行」交给用例层查询。
    data_maintenance_service.set_api_running_provider(
        lambda: bool(api.get_http_api_status().get("running"))
    )
    return api
