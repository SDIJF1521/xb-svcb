"""应用层端口（ports）：用例服务依赖的抽象契约。

分层契约（详见 ``docs/ddd-architecture.md``）：

    api / 表现层  ->  application / 用例层  ->  domain / 领域层
                                  ^                    ^
                                  |                    |
                         application.ports      domain 实体与规则
                                  ^
                                  |
                        infrastructure / 适配层（实现端口）

应用层只依赖这里的 ``Protocol``，不再 import ``infrastructure`` 中的具体类。
基础设施层提供结构化满足这些协议的实现（鸭子类型），由组合根
``app/composition.py`` 显式注入。协议全部标记 ``runtime_checkable``，
``app/tests/test_architecture.py`` 用它校验真实适配器是否满足契约。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from domain.vocal_enhancement import VocalEnhancementControls

__all__ = [
    "AudioEnginePort",
    "AudioImportStorePort",
    "DataTransferPort",
    "EditorProjectStorePort",
    "WorkFilesPort",
    "EngineRegistryPort",
    "FfmpegGateway",
    "HighNoteVocoderPort",
    "ItemRepository",
    "MidiPitchPort",
    "PymssGateway",
    "PluginHostPort",
    "SeparationGateway",
    "SettingsRepository",
    "StatusToolAdapter",
    "SystemAudioReaderPort",
    "SystemAudioWriterPort",
    "ThemeMediaStorePort",
    "ToolAdapter",
    "VocalEnhancementControls",
    "VocalEnhancementPort",
]


# ---- 仓储 ----

@runtime_checkable
class ItemRepository(Protocol):
    """以 ``id`` 为主键的聚合仓储（模型 / 作品 / 编辑工程）。"""

    def set_path(self, path: Path) -> None: ...

    def all(self) -> list[dict[str, Any]]: ...

    def get(self, item_id: str) -> dict[str, Any] | None: ...

    def add(self, item: dict[str, Any]) -> dict[str, Any]: ...

    def update(self, item_id: str, item: dict[str, Any]) -> None: ...

    def remove(self, item_id: str) -> None: ...


@runtime_checkable
class SettingsRepository(Protocol):
    """键值设置仓储。"""

    def set_path(self, path: Path) -> None: ...

    def get(self, key: str, default: Any = None) -> Any: ...

    def set(self, key: str, value: Any) -> None: ...


# ---- 工具与引擎 ----

@runtime_checkable
class ToolAdapter(Protocol):
    """外部工具/推理引擎的通用外观：可用性与版本。"""

    @property
    def available(self) -> bool: ...

    def version(self) -> str | None: ...


@runtime_checkable
class StatusToolAdapter(ToolAdapter, Protocol):
    """带可读状态描述的工具（UVR / PyMSS）。

    UVR 的状态与 PyMSS 的状态形状不同（前者按引擎整体，后者按模型），
    因此这里只约束「可查询状态」，具体返回类型由各自的实现决定。
    """

    def status(self, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class FfmpegGateway(ToolAdapter, Protocol):
    """音频转码与混音能力（FFmpeg）。

    方法签名与 ``infrastructure.ffmpeg_tool.FfmpegTool`` 保持一致：
    端口只描述用例层真正依赖的参数，默认值在实现里给出。
    """

    def probe_duration(self, src: Path) -> float | None: ...

    def detect_silences(
        self,
        src: Path,
        start: float = 0.0,
        end: float | None = None,
        noise_db: float = -40.0,
        min_duration: float = 0.35,
    ) -> list[dict[str, float]]: ...

    def convert(self, src: Path, dst: Path, sample_rate: int = 44100) -> bool: ...

    def slice(
        self,
        src: Path,
        start: float,
        end: float,
        dst: Path,
        sample_rate: int = 44100,
        fade: float = 0.0,
    ) -> bool: ...

    def concat(self, parts: list[Path], dst: Path, sample_rate: int = 44100) -> bool: ...

    def concat_crossfade(
        self,
        parts: list[Path],
        dst: Path,
        xf: float = 0.03,
        sample_rate: int = 44100,
    ) -> bool: ...

    def pad_or_trim(
        self, src: Path, dst: Path, seconds: float, sample_rate: int = 44100
    ) -> bool: ...

    def pitch_shift(
        self,
        src: Path,
        dst: Path,
        semitones: int,
        *,
        mask_source: Path | None = None,
        loudness_source: Path | None = None,
        high_threshold: float = 800.0,
        report_path: Path | None = None,
        regions: list[tuple[float, float]] | None = None,
        f0_curve: Path | None = None,
    ) -> bool: ...

    def mix(
        self,
        vocals: Path,
        instrumental: Path,
        dst: Path,
        sample_rate: int = 44100,
        vocal_gain_db: float = ...,
        instrumental_gain_db: float = ...,
        glue: bool = False,
    ) -> bool: ...

    def mix_vocals(
        self, inputs: list[Path], dst: Path, sample_rate: int = 44100
    ) -> bool: ...

    def merge_tracks(
        self, inputs: list[Path], dst: Path, sample_rate: int = 44100
    ) -> bool: ...

    def apply_effect(
        self,
        src: Path,
        dst: Path,
        effect_type: str,
        params: dict[str, Any],
        sample_rate: int = 44100,
    ) -> bool: ...

    def loudnorm(
        self, src: Path, dst: Path, target_lufs: float = -14.0, sample_rate: int = 44100
    ) -> bool: ...

    def tempo(
        self, src: Path, dst: Path, speed: float, sample_rate: int = 44100
    ) -> bool: ...

    def pitch(
        self, src: Path, dst: Path, semitones: int, sample_rate: int = 44100
    ) -> bool: ...

    def fade(
        self,
        src: Path,
        dst: Path,
        fade_in: float,
        fade_out: float,
        sample_rate: int = 44100,
    ) -> bool: ...

    def adaptive_mix_profile(
        self,
        vocals: Path,
        instrumental: Path,
    ) -> dict[str, float | bool | None]: ...


@runtime_checkable
class HighNoteVocoderPort(ToolAdapter, Protocol):
    """高音声码器补偿：重建已确认高音区的超高频带。

    实现在隔离环境里跑 F0 条件化声码器（Snake-HiFiGAN 优先，NSF-HiFiGAN 兜底），
    只替换交叉频点以上的频带；未通过验收时不产生输出文件，用例层沿用升调结果。
    """

    def refine(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...


@runtime_checkable
class MidiPitchPort(ToolAdapter, Protocol):
    """MIDI 子编辑器的音高重绘：把音符级编辑落到音频上。

    实现在隔离环境里用 Praat PSOLA 逐音符移调（保共振峰），只改写被编辑过的
    音符区间；没有音符需要修改时不产生新音频。
    """

    def apply(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...


@runtime_checkable
class SeparationGateway(StatusToolAdapter, Protocol):
    """人声分离能力（UVR / PyMSS 共用形状）。"""

    def separate(self, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class PymssGateway(SeparationGateway, Protocol):
    """PyMSS 分离引擎，包含模型目录管理能力。"""

    def declared_stems(self, model: str = "") -> list[str]: ...

    def list_models(self, *args: Any, **kwargs: Any) -> Any: ...

    def download_model(self, model: str, out_dir: Path | None = None, purpose: str = "") -> dict[str, Any]: ...

    def start_download_model(self, model: str, purpose: str = "") -> dict[str, Any]: ...

    def download_progress(self, key: str = "") -> dict[str, Any]: ...

    def download_jobs(self) -> list[dict[str, Any]]: ...

    def delete_model(self, model: str) -> bool: ...

    def clear_download_job(self, key: str) -> bool: ...


@runtime_checkable
class EngineRegistryPort(Protocol):
    """按模型框架路由推理引擎。"""

    def for_framework(self, framework: str | None) -> Any: ...

    def for_model(self, model: dict[str, Any] | None) -> Any: ...

    @property
    def sovits(self) -> Any: ...


@runtime_checkable
class AudioEnginePort(Protocol):
    """时间线渲染引擎（FFmpeg 之上的编辑器渲染层）。"""

    @property
    def available(self) -> bool: ...

    def trim(self, *args: Any, **kwargs: Any) -> Any: ...

    def concat(self, parts: list[Path], dst: Path, sample_rate: int = 44100) -> bool: ...

    def volume(self, src: Path, gain: float, dst: Path, sample_rate: int = 44100) -> bool: ...

    def fade(self, *args: Any, **kwargs: Any) -> Any: ...

    def silence(self, dst: Path, duration: float, sample_rate: int = 44100) -> bool: ...

    def render_timeline(self, *args: Any, **kwargs: Any) -> Any: ...

    def render_plugin_monitor_input(self, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class PluginHostPort(Protocol):
    """外部 VST3 插件宿主。"""

    def status(self) -> dict[str, Any]: ...

    def inspect_plugin(self, plugin_path: str) -> dict[str, Any]: ...

    def show_editor(self, *args: Any, **kwargs: Any) -> Any: ...

    def close_editor(self, session_id: str) -> dict[str, Any]: ...

    def sync_editor(self, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class VocalEnhancementPort(ToolAdapter, Protocol):
    """歌声增强（修音 / 音色美化 / 修复）能力。

    参数与 ``infrastructure.vocal_enhancement.VocalEnhancementProcessor`` 对齐：
    默认值只出现在实现里，端口声明 ``...`` 占位，便于实现按需调整默认值。
    """

    LEVEL_BASIC: str
    LEVEL_ADVANCED: str
    LEVELS: set[str]

    def enhance(
        self,
        source: Path,
        output: Path,
        *,
        level: str = ...,
        device: str = ...,
        log_file: Path | None = None,
        reference: Path | None = None,
        pitch_correction: float = ...,
        timing_alignment: float = ...,
        timbre_focus: float = ...,
        ai_eq: float = ...,
        ai_compressor: float = ...,
        ai_exciter: float = ...,
        stereo_width: float = ...,
        loudness_envelope: float = ...,
        skip_repair: bool = False,
        preserve_model_high_band: bool = False,
        progress_callback: Callable[[int], None] | None = None,
    ) -> Path: ...

    def analyze(
        self,
        source: Path,
        *,
        log_file: Path | None = None,
    ) -> dict[str, float | bool]: ...

    def repair(
        self,
        source: Path,
        output: Path,
        *,
        stage: str = ...,
        device: str = ...,
        log_file: Path | None = None,
        profile: dict[str, float | bool] | None = None,
        reference: Path | None = None,
    ) -> Path: ...

    def normalize_strength(self, value: float, fallback: float) -> float: ...


# ---- 系统与设备 ----

@runtime_checkable
class SystemAudioReaderPort(Protocol):
    def __enter__(self) -> "SystemAudioReaderPort": ...

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None: ...

    def read(self, frames: int) -> Any: ...


@runtime_checkable
class SystemAudioWriterPort(Protocol):
    def __enter__(self) -> "SystemAudioWriterPort": ...

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None: ...

    def write(self, audio: Any, *, overlap_frames: int = 0) -> None: ...


# ---- 本地媒体文件存储 ----

@runtime_checkable
class ThemeMediaStorePort(Protocol):
    """主题背景媒体的本地存储。"""

    def save(self, source: Path) -> dict[str, Any]: ...

    def data_uri(self, media_path: str) -> str: ...

    def delete(self, media_path: str) -> bool: ...


@runtime_checkable
class AudioImportStorePort(Protocol):
    """浏览器音频导入的本地落盘。"""

    def save_payload(self, name: str, data: str) -> str | None: ...

    def start(self, name: str) -> str | None: ...

    def append(self, token: str, data: str) -> bool: ...

    def finish(self, token: str) -> str | None: ...

    def cancel(self, token: str) -> bool: ...


@runtime_checkable
class DataTransferPort(Protocol):
    """用户数据目录的探测与搬运能力（数据目录迁移使用）。"""

    def resolve_data_dir_target(
        self, raw_target: str, current: Path
    ) -> tuple[Path | None, str | None]: ...

    def resolve_migration_target(
        self, raw_target: str, src: Path
    ) -> tuple[Path | None, str | None]: ...

    def looks_like_data_dir(self, path: Path) -> bool: ...

    def dir_size(
        self, root: Path, *, ignore_tmp: bool = False, skip_volatile: bool = False
    ) -> int: ...

    def test_writable(self, path: Path) -> bool: ...

    def write_marker(
        self,
        target: Path,
        *,
        migrated_from: str | None = None,
        selected_from: str | None = None,
    ) -> None: ...

    def disk_usage(self, path: Path) -> tuple[int, int]: ...

    def copy_tree(
        self,
        src: Path,
        dst: Path,
        total_bytes: int,
        on_progress: Any,
    ) -> None: ...

# ---- 本地文件访问（工作目录 / 编辑器工程） ----

@runtime_checkable
class WorkFilesPort(Protocol):
    """作品工作目录与运行日志的文件系统访问。

    用例层保留「什么时候清理、清理什么」的策略，实际的文件操作走这里。
    """

    def work_dir(self, work_id: str) -> Path: ...

    def log_path(self, work_id: str, recorded: str | None = None) -> Path: ...

    def read_text_tail(self, path: Path, lines: int) -> str: ...

    def copy_tree(self, source: Path, destination: Path) -> bool: ...

    def remove_tree(self, path: Path) -> None: ...

    def list_entries(self, path: Path) -> list[Path]: ...


@runtime_checkable
class EditorProjectStorePort(Protocol):
    """编辑器工程目录、渲染/波形缓存与工程包（zip）的文件访问。"""

    def project_dir(self, project_id: str) -> Path: ...

    def cache_path(self, name: str) -> Path: ...

    def audio_data_uri(self, source: Path, *, exact: bool = False) -> str: ...

    def read_bytes(self, path: Path) -> bytes | None: ...

    def write_bytes(self, path: Path, data: bytes) -> bool: ...

    def exists(self, path: Path) -> bool: ...

    def remove(self, path: Path) -> None: ...

    def export_zip(self, entries: Any, destination: Path) -> bool: ...

    def extract_zip(self, source: Path, destination: Path) -> list[str]: ...
