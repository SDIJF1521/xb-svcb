"""应用层默认适配器接缝（default adapter seam）。

正常的运行路径是**组合根注入**：``app/composition.py`` 创建基础设施适配器，
再显式传给用例服务。本模块只服务两种场景：

* 用例服务被单独构造（脚本、单元测试）时，提供一个可用的默认实现；
* 需要「默认值」但不想把 ``infrastructure`` 变成应用层的模块级依赖。

因此这里的实现全部使用**函数内延迟导入**。``app/tests/test_architecture.py``
只允许本文件在函数体内引用 ``infrastructure``，其它应用层模块一律禁止。
新增用例服务时应优先通过构造函数注入，不要继续往这里堆新入口。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .ports import (
    AudioEnginePort,
    AudioImportStorePort,
    DataTransferPort,
    EditorProjectStorePort,
    WorkFilesPort,
    EngineRegistryPort,
    FfmpegGateway,
    HighNoteVocoderPort,
    PymssGateway,
    PluginHostPort,
    SeparationGateway,
    SystemAudioReaderPort,
    SystemAudioWriterPort,
    ThemeMediaStorePort,
    VocalEnhancementPort,
)


# ---- 工具与引擎 ----

def ffmpeg_tool() -> FfmpegGateway:
    from infrastructure.ffmpeg_tool import FfmpegTool

    return FfmpegTool()


def uvr_tool() -> SeparationGateway:
    from infrastructure.uvr_tool import UvrTool

    return UvrTool()


def pymss_tool() -> PymssGateway:
    from infrastructure.pymss_tool import PymssTool

    return PymssTool()


def audio_engine(ffmpeg: FfmpegGateway | None = None) -> AudioEnginePort:
    from infrastructure.audio_engine import FFmpegEngine

    return FFmpegEngine(ffmpeg)  # type: ignore[arg-type]


def plugin_host() -> PluginHostPort:
    from infrastructure.juce_vst3_host import JuceVst3Host

    return JuceVst3Host()


def vocal_enhancement() -> VocalEnhancementPort:
    from infrastructure.vocal_enhancement import VocalEnhancementProcessor

    return VocalEnhancementProcessor()


def high_note_vocoder() -> HighNoteVocoderPort:
    from infrastructure.high_note_vocoder import HighNoteVocoderProcessor

    return HighNoteVocoderProcessor()


def engine_registry(engines: list[Any]) -> EngineRegistryPort:
    from infrastructure.engine import EngineRegistry

    return EngineRegistry(engines)


def ffmpeg_cache_key(payload: Any) -> str:
    """渲染缓存键：与 ``FFmpegEngine.cache_key`` 保持同一算法。"""
    from infrastructure.audio_engine import FFmpegEngine

    return FFmpegEngine.cache_key(payload)


# ---- 环境探测 ----

def device_capabilities() -> dict[str, Any]:
    from infrastructure.inference_device import inference_device_capabilities

    return inference_device_capabilities()


def runtime_device_label(runtime: dict[str, Any], fallback: str = "") -> str:
    from infrastructure.inference_device import runtime_device_label as _impl

    return _impl(runtime, fallback)


def engine_asset_status(
    root: Path,
    engine: str,
    *,
    location: str = "",
) -> dict[str, Any]:
    from infrastructure.model_assets import engine_asset_status as _impl

    return _impl(root, engine, location=location)


# ---- 系统能力 ----

def audio_files_from_clipboard() -> list[Path]:
    from infrastructure.clipboard import audio_files_from_clipboard as _impl

    return _impl()


def copy_file_to_clipboard(path: Path) -> bool:
    from infrastructure.clipboard import copy_file_to_clipboard as _impl

    return _impl(path)


def list_system_audio_devices() -> list[dict[str, Any]]:
    from infrastructure.system_audio import list_devices

    return list_devices()


def system_audio_reader(
    device_name: str,
    sample_rate: int,
    channels: int = 2,
) -> SystemAudioReaderPort:
    from infrastructure.system_audio import SystemAudioReader

    return SystemAudioReader(device_name, sample_rate, channels)


def system_audio_writer(
    device_name: str,
    sample_rate: int,
    channels: int = 2,
    prebuffer_blocks: int = 0,
    crossfade_frames: int = 0,
) -> SystemAudioWriterPort:
    from infrastructure.system_audio import SystemAudioWriter

    return SystemAudioWriter(
        device_name,
        sample_rate,
        channels,
        prebuffer_blocks=prebuffer_blocks,
        crossfade_frames=crossfade_frames,
    )


# ---- 应用生命周期 ----

def work_files() -> WorkFilesPort:
    from infrastructure.work_files import WorkFiles

    return WorkFiles()


def editor_project_store() -> EditorProjectStorePort:
    from infrastructure.editor_project_store import EditorProjectStore
    from infrastructure.ffmpeg_tool import FfmpegTool

    return EditorProjectStore(FfmpegTool())

def data_transfer() -> DataTransferPort:
    from infrastructure.data_transfer import DataTransfer

    return DataTransfer()

def theme_media_store() -> ThemeMediaStorePort:
    from infrastructure.theme_media import ThemeMediaStore

    return ThemeMediaStore()


def audio_import_store() -> AudioImportStorePort:
    from infrastructure.audio_import import AudioImportStore

    return AudioImportStore()


def ensure_data_dirs() -> None:
    from infrastructure import paths

    paths.ensure_dirs()


def clear_temp_directory() -> bool:
    from infrastructure import paths

    return paths.clear_temp_directory()


def apply_window_theme(title: str, theme: str) -> bool:
    from infrastructure.window_theme import apply

    return apply(title, theme)
