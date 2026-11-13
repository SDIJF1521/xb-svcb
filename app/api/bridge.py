"""pywebview JS API 桥接（表现层）。

``Api`` 的所有公有方法都会被 pywebview 暴露为 ``window.pywebview.api.<method>``，
前端通过 Promise 调用。本层只做参数转换、原生对话框与用例编排，
不含业务规则，也不 import ``infrastructure``：所有依赖由组合根
``app/composition.py`` 注入（见 ``docs/ddd-architecture.md``）。
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, cast

import config
from api import dialog_text
from application import (
    AudioEditorService,
    AudioImportService,
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
from application.ports import (
    ItemRepository,
    PymssGateway,
    SettingsRepository,
)


def _safe_filename(name: str) -> str:
    """清洗为合法文件名（去除非法字符并限长），用于导出默认名。"""
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name or "").strip().strip(".")
    return cleaned[:120] or "翻唱作品"


# 前端当前界面语言：原生对话框由后端弹出，需要它才能本地化标题与文件类型。
_UI_LOCALE = "zh-CN"


class Api:
    def __init__(
        self,
        system: SystemService,
        models: ModelService,
        works: WorkService,
        music: MusicService,
        hub: ModelHubService,
        editor: AudioEditorService,
        models_repo: ItemRepository,
        works_repo: ItemRepository,
        editor_repo: ItemRepository,
        settings: SettingsRepository,
        plugins: PluginService,
        realtime_cover: RealtimeCoverService,
        media: MediaService,
        theme_media: ThemeMediaService,
        audio_import: AudioImportService,
        pymss: PymssGateway,
        data_maintenance: DataMaintenanceService,
        cleanup_temp: Callable[[], Any] | None = None,
        window_theme: Callable[[str, str], bool] | None = None,
    ) -> None:
        self._system = system
        self._models = models
        self._works = works
        self._music = music
        self._hub = hub
        self._editor = editor
        self._models_repo = models_repo
        self._works_repo = works_repo
        self._editor_repo = editor_repo
        self._settings = settings
        self._plugins = plugins
        self._realtime_cover = realtime_cover
        self._media = media
        self._theme_media = theme_media
        self._audio_import = audio_import
        self._pymss = pymss
        self._data_maintenance = data_maintenance
        # 进程级清理与原生窗口主题由组合根注入，表现层不直接依赖基础设施。
        self._cleanup_temp = cleanup_temp or (lambda: None)
        self._apply_window_theme_callable = window_theme or (lambda _title, _theme: False)
        self._window = None
        # FastAPI 默认关闭。这里只创建控制器，不监听端口；必须由用户在界面手动启动。
        from .http_server import HttpApiServer

        self._http_api = HttpApiServer(self, settings)

    def set_window(self, window) -> None:  # noqa: ANN001
        """由入口在创建窗口后注入，用于打开原生文件对话框。"""
        self._window = window

    # ---- 系统 ----
    def set_ui_locale(self, locale: str) -> bool:
        """记录前端当前界面语言，供原生打开/保存对话框本地化标题与文件名。"""
        global _UI_LOCALE
        _UI_LOCALE = dialog_text.normalize_locale(locale)
        # 编辑器自动生成的音轨 / 工程名也按这个语言落库
        editor = getattr(self, "_editor", None)
        if editor is not None:
            editor.set_ui_locale(_UI_LOCALE)
        return True

    def get_system_status(self) -> dict[str, Any]:
        return self._system.status()

    def get_http_api_status(self) -> dict[str, Any]:
        return self._http_api.status()

    def configure_http_api(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._http_api.configure(payload or {})

    def regenerate_http_api_key(self) -> dict[str, Any]:
        return self._http_api.regenerate_key()

    def list_http_api_keys(self) -> dict[str, Any]:
        return self._http_api.list_keys()

    def create_http_api_key(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._http_api.create_key(payload or {})

    def update_http_api_key(self, key_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._http_api.update_key(key_id, payload or {})

    def delete_http_api_key(self, key_id: str) -> dict[str, Any]:
        return self._http_api.delete_key(key_id)

    def start_http_api(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._http_api.start(payload or {})

    def stop_http_api(self) -> dict[str, Any]:
        return self._http_api.stop()

    def test_http_api(self) -> dict[str, Any]:
        return self._http_api.test()

    def open_http_api_docs(self, kind: str = "docs") -> bool:
        return self._http_api.open_docs(kind)

    def shutdown(self) -> None:
        """释放桌面进程内的后台服务。"""
        self._realtime_cover.shutdown()
        self._http_api.shutdown()
        # 清理所有应用生成的临时音频、UVR 中间文件和编辑器缓存；保留
        # data/temp 目录本身，便于下次启动直接复用。
        self._cleanup_temp()

    # ---- 实时翻唱工程 ----
    def start_realtime_cover(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._realtime_cover.start(payload or {})

    def list_system_audio_devices(self) -> list[dict[str, Any]]:
        return self._realtime_cover.list_system_audio_devices()

    def start_system_audio_realtime(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._realtime_cover.start_system(payload or {})

    def get_realtime_cover_status(self, session_id: str) -> dict[str, Any]:
        return self._ensure_realtime_work(session_id)

    def get_realtime_cover_chunk(self, session_id: str, index: int) -> dict[str, Any]:
        return self._realtime_cover.chunk(session_id, int(index))

    def stop_realtime_cover(self, session_id: str) -> dict[str, Any]:
        status = self._realtime_cover.stop(session_id)
        if status.get("input_mode") == "system":
            return status
        if status.get("status") == "done" and not status.get("work_id"):
            return self._ensure_realtime_work(session_id)
        return status

    def cleanup_realtime_cover(self, session_id: str) -> bool:
        return self._realtime_cover.cleanup(session_id)

    def export_realtime_cover(self, session_id: str) -> str:
        status = self._ensure_realtime_work(session_id)
        work_id = str(status.get("work_id") or "")
        if work_id:
            return self.export_work(work_id)
        source = Path(str(status.get("output_path") or ""))
        if not source.is_file():
            return ""
        destination = self._save_dialog(
            "导出实时翻唱", "实时翻唱.wav", ("音频文件 (*.wav)",)
        )
        if not destination:
            return ""
        target = Path(destination)
        if target.suffix.lower() != ".wav":
            target = target.with_suffix(".wav")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            return str(target)
        except OSError:
            return ""

    def _ensure_realtime_work(self, session_id: str) -> dict[str, Any]:
        """Persist a completed realtime session before exposing its status."""
        status = self._realtime_cover.status(session_id)
        if status.get("input_mode") == "system":
            return status
        if status.get("status") == "done" and not status.get("work_id"):
            work = self._works.register_realtime_output(status)
            if work:
                self._realtime_cover.attach_work_id(session_id, str(work.get("id") or ""))
                status = self._realtime_cover.status(session_id)
        return status

    def toggle_window_fullscreen(self) -> dict[str, Any]:
        """切换软件主窗口全屏，供插件自定义页面通过宿主 Bridge 调用。"""
        if self._window is None:
            return {"ok": False, "error": "宿主窗口尚未就绪。"}
        toggle = getattr(self._window, "toggle_fullscreen", None)
        if not callable(toggle):
            return {"ok": False, "error": "当前窗口运行时不支持软件全屏。"}
        try:
            toggle()
        except Exception as exc:  # noqa: BLE001 - pywebview backend boundary
            return {"ok": False, "error": f"切换软件全屏失败：{exc}"}
        return {"ok": True}
    def apply_window_theme(self, theme: str) -> bool:
        """让原生窗口标题栏/边框跟随前端主题（cyber / anime）。

        前端在挂载及切换主题时调用；非 Windows 平台静默返回 False。
        """
        name = theme if theme in ("cyber", "anime") else "cyber"
        return self._apply_window_theme_callable(config.APP_TITLE, name)

    def pick_theme_media_file(self) -> dict[str, Any]:
        """选择自定义主题背景媒体，并复制到数据目录以便重启后继续使用。"""
        result = self._open_dialog(
            "选择主题背景图片或 MP4 动态壁纸",
            multiple=False,
            file_types=(
                "背景媒体 (*.jpg;*.jpeg;*.png;*.webp;*.gif;*.avif;*.heic;*.heif;*.mp4)",
                "图片 (*.jpg;*.jpeg;*.png;*.webp;*.gif;*.avif;*.heic;*.heif)",
                "MP4 视频 (*.mp4)",
                "所有文件 (*.*)",
            ),
        )
        if not result:
            return {"ok": False, "cancelled": True}
        return self._theme_media.save(result[0])

    def get_theme_media_data(self, media_path: str) -> str:
        """返回已保存主题媒体的 data URI，供背景图/视频播放。"""
        return self._theme_media.data_uri(media_path)

    def delete_theme_media_file(self, media_path: str) -> bool:
        """删除由应用保存的主题媒体；外部路径与 data URI 一律不处理。"""
        return self._theme_media.delete(media_path)

    def get_data_storage_status(self) -> dict[str, Any]:
        """返回用户数据目录、占用和所在磁盘剩余空间。"""
        return self._data_maintenance.storage_status()

    def pick_data_dir(self) -> str:
        """选择新的用户数据目录。"""
        result = self._folder_dialog("选择 XB-SVCB 用户数据目录")
        return result or ""

    def set_data_dir(self, target_dir: str) -> dict[str, Any]:
        """直接切换到用户选择的数据目录，不复制当前数据。"""
        return self._data_maintenance.set_data_dir(target_dir)

    def start_data_migration(self, target_dir: str) -> dict[str, Any]:
        """启动后台数据目录迁移任务，前端轮询 get_data_migration_status。"""
        return self._data_maintenance.start_migration(target_dir)

    def get_data_migration_status(self) -> dict[str, Any]:
        """返回最近一次数据迁移任务状态。"""
        return self._data_maintenance.migration_status()

    def migrate_data_dir(self, target_dir: str) -> dict[str, Any]:
        """兼容旧前端的同步迁移入口。"""
        return self._data_maintenance.migrate(target_dir)

    # ---- 模型 ----
    def list_models(self) -> list[dict[str, Any]]:
        return self._models.list()

    def get_model_library_overview(self) -> dict[str, Any]:
        return self._models.overview()

    def get_default_model(self) -> str | None:
        return self._models.default_id()

    def pick_model_file(self) -> str | None:
        """选择单个模型权重文件（主模型 / 扩散模型通用）。"""
        result = self._open_dialog(
            "选择模型权重文件",
            multiple=False,
            file_types=("模型权重 (*.pth;*.pt;*.onnx;*.ckpt)", "所有文件 (*.*)"),
        )
        return result[0] if result else None

    def pick_config_file(self) -> str | None:
        """选择单个模型配置文件（.json / .yaml）。"""
        result = self._open_dialog(
            "选择模型配置文件",
            multiple=False,
            file_types=("配置文件 (*.json;*.yaml;*.yml)", "所有文件 (*.*)"),
        )
        return result[0] if result else None

    def pick_index_file(self) -> str | None:
        """选择 RVC 检索特征文件（.index）。"""
        result = self._open_dialog(
            "选择 RVC 检索特征文件",
            multiple=False,
            file_types=("RVC 检索特征 (*.index)", "所有文件 (*.*)"),
        )
        return result[0] if result else None

    def pick_modelhub_preview_audio_file(self) -> str | None:
        """选择模型站展示用试听音频。"""
        result = self._open_dialog(
            "选择模型试听音频",
            multiple=False,
            file_types=(
                "音频文件 (*.mp3;*.wav;*.flac;*.m4a;*.ogg;*.aac)",
                "所有文件 (*.*)",
            ),
        )
        return result[0] if result else None

    def pick_modelhub_screenshot_files(self) -> list[str]:
        """选择模型站展示截图，可多选。"""
        return self._open_dialog(
            "选择模型截图",
            multiple=True,
            file_types=(
                "图片 (*.jpg;*.jpeg;*.png;*.webp;*.gif)",
                "所有文件 (*.*)",
            ),
        )

    def import_model(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """导入一组模型，按 framework 分支处理 so-vits / RVC / SeedVC 文件角色。"""
        return self._models.import_model(payload or {})

    def set_default_model(self, model_id: str) -> bool:
        return self._models.set_default(model_id)

    def delete_model(self, model_id: str) -> bool:
        return self._models.remove(model_id)

    def inspect_model(self, model_id: str, repair: bool = False) -> dict[str, Any]:
        return self._models.inspect(model_id, bool(repair))

    def toggle_model_favorite(self, model_id: str) -> dict[str, Any] | None:
        return self._models.toggle_favorite(model_id)

    def rename_model(self, model_id: str, name: str) -> bool:
        return self._models.rename(model_id, name) is not None

    # ---- 模型站（ModelScope 魔搭社区）----
    def get_modelscope_token(self) -> str:
        return self._hub.get_token()

    def set_modelscope_token(self, token: str) -> bool:
        return self._hub.set_token(token)

    def verify_modelscope_token(self, token: str | None = None) -> dict[str, Any]:
        """校验 ModelScope 访问令牌，返回 {ok, username, email}。"""
        return self._hub.verify_token(token)

    def modelhub_upload_ready(self) -> bool:
        """上传组件（.venv-hub + modelscope）是否就绪。"""
        return self._hub.upload_ready()

    def list_model_frameworks(self) -> list[dict[str, str]]:
        """可选的模型架构标签（so-vits-svc / rvc …）。"""
        return self._hub.list_frameworks()

    # ---- PyMSS 前期分离模型 ----
    def pymss_status(self, model: str = "") -> dict[str, Any]:
        tool = self._pymss
        selected = str(model or "").strip()
        ready = config.pymss_any_model_ready() if not selected else config.pymss_model_ready(selected)
        return {
            "ok": bool(tool.available and ready),
            "environment": bool(tool.available),
            "model": selected or "*",
            "status": tool.status(selected),
            "version": tool.version(),
        }

    def pymss_models(self, purpose: str = "", include_all: bool = False) -> list[dict[str, Any]]:
        tool = self._pymss
        return tool.list_models(purpose=purpose, include_all=bool(include_all))

    def pymss_download_model(self, model: str = "") -> dict[str, Any]:
        tool = self._pymss
        return tool.start_download_model(model)

    def delete_pymss_model(self, model: str = "") -> bool:
        tool = self._pymss
        return tool.delete_model(model)

    def pymss_download_progress(self, key: str = "") -> dict[str, Any]:
        tool = self._pymss
        return tool.download_progress(key)

    def pymss_download_jobs(self) -> list[dict[str, Any]]:
        tool = self._pymss
        return tool.download_jobs()

    def hub_search_models(
        self,
        query: str = "",
        page: int = 1,
        framework: str | None = None,
        page_size: int = 12,
    ) -> dict[str, Any]:
        """搜索模型站中由本软件上传的翻唱模型（可按架构筛选、分页）。"""
        return self._hub.search(query or "", int(page or 1), framework, int(page_size or 12))

    def hub_download_model(self, repo_id: str) -> dict[str, Any]:
        """下载模型站中的模型并导入本地模型库。"""
        return self._hub.download(repo_id)

    def hub_upload_model(
        self,
        model_id: str,
        name: str | None = None,
        framework: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """把本地模型上传到模型站（用户自己的 ModelScope 命名空间），并标注模型架构。"""
        return self._hub.upload(model_id, name, framework, metadata or {})

    def hub_model_detail(self, repo_id: str) -> dict[str, Any]:
        """读取模型详情、版本、依赖与展示素材索引。"""
        return self._hub.model_detail(repo_id)

    def hub_asset_data(self, repo_id: str, file_path: str) -> dict[str, Any]:
        """读取模型清单声明过的截图/试听素材，返回 data URI 或远端 URL。"""
        return self._hub.asset_data(repo_id, file_path)

    def hub_check_updates(self) -> dict[str, Any]:
        """检查本地下载模型是否有远端新版本。"""
        return self._hub.check_updates()

    def hub_start_upgrade(self, model_id: str) -> dict[str, Any]:
        """从来源仓库一键拉取最新版本并导入。"""
        return self._hub.start_upgrade(model_id)

    def hub_progress(self, key: str) -> dict[str, Any]:
        """轮询上传/下载进度。key 形如 'dl:<repo_id>' 或 'ul:<model_id>'。"""
        return self._hub.get_progress(key or "")

    def hub_start_download(self, repo_id: str) -> dict[str, Any]:
        """后台下载并导入模型，立即返回 {ok, key}，不阻塞前端。"""
        return self._hub.start_download(repo_id)

    def hub_start_upload(
        self,
        model_id: str,
        name: str | None = None,
        framework: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """后台上传本地模型到模型站，立即返回 {ok, key}，不阻塞前端。"""
        return self._hub.start_upload(model_id, name, framework, metadata or {})

    def hub_list_jobs(self) -> list[dict[str, Any]]:
        """列出全部上传/下载后台任务（含实时进度）。"""
        jobs = list(self._hub.list_jobs())
        # 统一把 PyMSS 模型下载投影到传输中心，确保切换页面后仍能看到进度。
        for item in self._pymss.download_jobs():
            jobs.append(
                {
                    "key": item.get("key", ""),
                    "kind": "download",
                    "title": f"PyMSS · {item.get('model', '模型')}",
                    "status": item.get("status", "failed"),
                    "error": item.get("error"),
                    "result": item.get("result"),
                    "created_at": item.get("created_at"),
                    "pct": item.get("pct", 0),
                    "msg": item.get("message", ""),
                    "phase": "pymss-download",
                }
            )
        # 音乐曲库下载同样纳入传输中心，避免下载大文件时界面没有反馈。
        jobs.extend(self._music.download_jobs())
        return jobs

    def hub_clear_job(self, key: str) -> bool:
        """清理一条已完成/失败的传输任务记录。"""
        if str(key or "").startswith("pymss:"):
            return self._pymss.clear_download_job(key)
        if str(key or "").startswith("music:"):
            return self._music.clear_download_job(key)
        return self._hub.clear_job(key or "")

    # ---- 作品 / 翻唱 ----
    def pick_audio_file(self) -> str | None:
        result = self._open_dialog(
            "选择歌曲音频",
            multiple=False,
            file_types=(
                "音频文件 (*.mp3;*.wav;*.flac;*.m4a;*.ogg;*.aac)",
                "所有文件 (*.*)",
            ),
        )
        return result[0] if result else None

    def pick_audio_files(self) -> list[str]:
        result = self._open_dialog(
            "选择多个歌曲音频",
            multiple=True,
            file_types=(
                "音频文件 (*.mp3;*.wav;*.flac;*.m4a;*.ogg;*.aac)",
                "所有文件 (*.*)",
            ),
        )
        return list(result or [])

    def import_audio_data(self, name: str, data: str) -> str | None:
        """Persist a browser/drag-and-drop audio payload for a pending work."""
        return self._audio_import.save_data(name, data)

    def start_audio_import(self, name: str) -> str | None:
        """Start a streamed browser audio import and return its opaque token."""
        return self._audio_import.start(name)

    def append_audio_import(self, token: str, data: str) -> bool:
        """Append one Base64 chunk to a streamed browser audio import."""
        return self._audio_import.append(token, data)

    def finish_audio_import(self, token: str) -> str | None:
        """Complete a streamed import and return the final local file path."""
        return self._audio_import.finish(token)

    def cancel_audio_import(self, token: str) -> bool:
        """Cancel a streamed import and remove its partial file."""
        return self._audio_import.cancel(token)

    def pick_lyrics_file(self) -> dict[str, Any]:
        result = self._open_dialog(
            "选择歌词文件",
            multiple=False,
            file_types=(
                "歌词文件 (*.lrc;*.txt)",
                "所有文件 (*.*)",
            ),
        )
        if not result:
            return {"ok": False, "cancelled": True}
        path = Path(result[0])
        if not path.exists() or not path.is_file():
            return {"ok": False, "error": "歌词文件不存在"}
        try:
            if path.stat().st_size > 2 * 1024 * 1024:
                return {"ok": False, "error": "歌词文件过大"}
        except OSError:
            return {"ok": False, "error": "无法读取歌词文件"}
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                text = path.read_text(encoding=encoding)
                return {
                    "ok": True,
                    "path": str(path),
                    "name": path.name,
                    "text": text,
                }
            except UnicodeDecodeError:
                continue
            except OSError:
                return {"ok": False, "error": "无法读取歌词文件"}
        return {"ok": False, "error": "歌词文件编码不支持"}

    def pick_effect_plugin_file(self) -> str | None:
        """选择由 JUCE VST3 Host 承载的本地效果器插件。"""
        result = self._open_dialog(
            "选择效果器插件",
            multiple=False,
            file_types=(
                "VST3 效果器插件 (*.vst3)",
                "效果器插件 (*.vst3;*.dll;*.component)",
                "所有文件 (*.*)",
            ),
        )
        return result[0] if result else None

    def pick_effect_plugin_directory(self) -> str | None:
        """Choose a directory to recursively scan for VST3 bundles."""
        return self._folder_dialog("选择 VST3 插件目录") or None

    def scan_effect_plugin_directory(self, directory: str) -> list[dict[str, str]]:
        """Recursively discover VST3 bundles from an explicitly selected directory."""
        return self._plugins.scan_effect_plugin_directory(directory)

    def auto_scan_effect_plugins(self) -> list[dict[str, str]]:
        """Scan conventional VST3 locations without requiring manual setup."""
        return self._plugins.auto_scan_effect_plugins()

    def list_works(self) -> list[dict[str, Any]]:
        return self._works.list()

    def get_work(self, work_id: str) -> dict[str, Any] | None:
        return self._works.get(work_id)

    def create_work(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._works.create(self._plugins.apply_before_create(payload or {}))

    # ---- 扩展插件（声明式 UI + 受限工作流钩子） ----
    def get_plugin_status(self) -> dict[str, Any]:
        return self._plugins.status()

    def configure_plugins(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._plugins.configure(payload or {})

    def list_plugins(self) -> list[dict[str, Any]]:
        return self._plugins.list()

    def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> bool:
        return self._plugins.set_enabled(plugin_id, bool(enabled))

    def pick_plugin_bundle(self) -> str | None:
        result = self._open_dialog(
            "选择 XB-SVCB 插件包",
            multiple=False,
            file_types=("XB-SVCB 插件包 (*.xbplugin;*.zip)", "所有文件 (*.*)"),
        )
        return result[0] if result else None

    def install_plugin_bundle(self, path: str) -> dict[str, Any]:
        return self._plugins.install_bundle(path)

    def install_plugin_bundle_data(self, name: str, data: str) -> dict[str, Any]:
        raw = str(data or "")
        if raw.startswith("data:") and "," in raw:
            raw = raw.split(",", 1)[1]
        try:
            content = base64.b64decode(raw, validate=True)
        except Exception:
            return {"ok": False, "error": "插件包数据无效。"}
        return self._plugins.install_bundle_bytes(str(name or "plugin.xbplugin"), content)

    def install_plugin_from_market(self, url: str) -> dict[str, Any]:
        return self._plugins.install_from_market(url)

    def uninstall_plugin(self, plugin_id: str) -> bool:
        return self._plugins.uninstall(plugin_id)

    def fetch_plugin_market(self) -> dict[str, Any]:
        return self._plugins.fetch_market()

    def run_plugin_action(
        self, plugin_id: str, action_id: str, values: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return self._plugins.run_action(plugin_id, action_id, values or {})

    def get_plugin_frontend_document(self, plugin_id: str) -> dict[str, Any]:
        return self._plugins.frontend_document(plugin_id)

    def get_plugin_frontend_asset_data(self, plugin_id: str, asset_path: str) -> dict[str, Any]:
        return self._plugins.frontend_asset_data(plugin_id, asset_path)

    def create_batch_work(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw = payload or {}
        # 批量任务也必须走同一插件工作流钩子；逐条创建时由 WorkService 分配源文件。
        return self._works.create_batch(self._plugins.apply_before_create(raw))

    def get_inference_queue(self) -> dict[str, Any]:
        return self._works.queue_status()

    def list_inference_history(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._works.history(int(limit or 50))

    def list_inference_presets(self) -> list[dict[str, Any]]:
        return self._works.list_presets()

    def save_inference_preset(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        return self._works.save_preset(name, params or {})

    def delete_inference_preset(self, preset_id: str) -> bool:
        return self._works.delete_preset(preset_id)

    # ---- 自定义翻唱工作流 ----
    def list_cover_workflows(self) -> list[dict[str, Any]]:
        return self._works.list_workflows()

    def save_cover_workflow(self, name: str, graph: dict[str, Any]) -> dict[str, Any]:
        return self._works.save_workflow(name, graph or {})

    def delete_cover_workflow(self, workflow_id: str) -> bool:
        return self._works.delete_workflow(workflow_id)

    def export_cover_workflow_file(
        self, graph: dict[str, Any], dialog_title: str = ""
    ) -> dict[str, Any]:
        """把当前工作流导出成可分享的 JSON 文件。"""
        graph = graph or {}
        payload = self._works.workflow_file_payload(graph)
        default_name = f"{_safe_filename(str(payload.get('name') or 'cover-workflow'))}.xbworkflow.json"
        destination = self._save_dialog(
            dialog_title or "导出工作流文件",
            default_name,
            ("工作流文件 (*.json)",),
        )
        if not destination:
            return {"ok": False, "cancelled": True}
        target = Path(destination)
        if target.suffix.lower() != ".json":
            target = target.with_suffix(".json")
        try:
            target.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            return {"ok": False, "error": str(exc) or "工作流导出失败"}
        return {"ok": True, "path": str(target)}

    def import_cover_workflow_file(
        self,
        dialog_title: str = "",
        file_label: str = "",
        all_files_label: str = "",
    ) -> dict[str, Any]:
        """从 JSON 文件导入工作流（不覆盖已保存列表，载入到画布另存）。

        原生对话框的标题与文件类型由前端传入当前语言的文案。
        """
        selected = self._open_dialog(
            dialog_title or "导入工作流文件",
            multiple=False,
            file_types=(
                f"{file_label or '工作流文件'} (*.json)",
                f"{all_files_label or '所有文件'} (*.*)",
            ),
        )
        if not selected:
            return {"ok": False, "cancelled": True}
        path = Path(selected[0])
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            return {"ok": False, "error": f"读取工作流文件失败：{exc}"}
        try:
            graph = self._works.parse_workflow_file(data)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "path": str(path), "graph": graph}

    def retry_work(self, work_id: str) -> bool:
        return self._works.retry(work_id)

    def rename_work(self, work_id: str, title: str) -> bool:
        """重命名作品；新标题同时作为导出文件的默认名。"""
        return self._works.rename(work_id, title)

    def delete_work(self, work_id: str) -> bool:
        return self._works.remove(work_id)

    # ---- 用例服务的只读访问（供 FastAPI 层复用，避免访问私有成员）----
    @property
    def models(self) -> ModelService:
        return self._models

    @property
    def editor(self) -> AudioEditorService:
        return self._editor

    def work_stem_path(self, work_id: str, kind: str) -> Path | None:
        """作品音轨路径（经路径校验后的安全路径）。"""
        return self._media.stem_path(work_id, kind)

    def validate_work_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """严格校验并归一化任务创建请求（HTTP 层使用，规则位于用例层）。"""
        return self._works.validate_request(payload)

    def get_work_audio(self, work_id: str) -> str:
        """返回成品音频的 data URI（base64），供前端 <audio> 直接播放。"""
        return self.get_stem_audio(work_id, "output")

    def get_stem_audio(self, work_id: str, kind: str) -> str:
        """返回指定音轨的 data URI，供前端试听。

        kind 取值：output（成品）/ instrumental（背景音乐）/ vocals（去混响干声）。
        """
        return self._media.data_uri(work_id, kind)

    def export_work(self, work_id: str, fmt: str = "wav") -> str:
        """按指定格式导出翻唱成品，返回用户选择的保存路径。"""
        src = self._media.stem_path(work_id, "output")
        if src is None:
            return ""
        work = self._works.get(work_id) or {}
        title = (work.get("title") or src.stem).strip()
        output_format = str(fmt or "wav").strip().lower().lstrip(".")
        if output_format not in {"wav", "mp3", "flac", "m4a"}:
            output_format = "wav"
        ext = f".{output_format}"
        filename = f"{_safe_filename(title)}{ext}"
        dest = self._save_dialog(
            f"导出翻唱作品 · {output_format.upper()}",
            filename,
            (f"音频文件 (*.{output_format})",),
        )
        if not dest:
            return ""
        return self._media.export(work_id, dest, output_format)

    # ---- 音乐资源获取 ----
    def get_music_api_key(self) -> str:
        return self._music.get_api_key()

    def set_music_api_key(self, key: str) -> bool:
        return self._music.set_api_key(key)

    def list_music_sources(self) -> list[dict[str, Any]]:
        return self._music.list_sources()

    def get_music_source(self) -> str:
        return self._music.get_source()

    def set_music_source(self, source: str) -> bool:
        return self._music.set_source(source)

    def get_music_cookie(self) -> str:
        return self._music.get_cookie()

    def set_music_cookie(self, cookie: str) -> bool:
        return self._music.set_cookie(cookie)

    def search_music(
        self, msg: str, page: int = 1, page_size: int = 15, source: str | None = None
    ) -> dict[str, Any]:
        return self._music.search(msg, int(page or 1), int(page_size or 15), source)

    def get_music_song(
        self,
        msg: str,
        n: int,
        source: str | None = None,
        song_id: str | None = None,
    ) -> dict[str, Any]:
        return self._music.get_song(msg, n, source, song_id)

    def download_music(
        self,
        msg: str,
        n: int,
        source: str | None = None,
        song_id: str | None = None,
    ) -> dict[str, Any]:
        return self._music.download(msg, n, source, song_id)

    def preview_music(
        self,
        msg: str,
        n: int,
        source: str | None = None,
        song_id: str | None = None,
    ) -> dict[str, Any]:
        """获取在线试听地址；酷我经后端代理为 data URI。"""
        return self._music.preview(msg, n, source, song_id)

    def get_music_lyrics(
        self,
        msg: str,
        n: int,
        source: str | None = None,
        song_id: str | None = None,
    ) -> dict[str, Any]:
        """按歌名+索引获取带时间轴的歌词（多模型混合翻唱用）。"""
        return self._music.get_lyrics(msg, n, source, song_id)

    def get_audio_duration(self, path: str) -> float:
        """探测本地音频时长（秒），失败返回 0。用于歌词/文件时长匹配校验。"""
        return self._media.duration(path)

    def list_music(self) -> list[dict[str, Any]]:
        return self._music.list_downloaded()

    def delete_music(self, path: str) -> bool:
        return self._music.delete_downloaded(path)

    def _stem_path(self, work_id: str, kind: str) -> Path | None:
        """解析作品某条音轨的真实路径，并校验其位于数据目录内。"""
        return self._media.stem_path(work_id, kind)

    def open_work_log(self, work_id: str) -> bool:
        """在系统文件管理器中打开该任务的日志所在文件夹。"""
        target = self._works.log_path(work_id)
        if target is None:
            return False
        folder = target.parent if target.suffix else target
        return self._reveal(folder)

    def get_work_log(self, work_id: str, tail: int = 300) -> str:
        """读取任务运行日志的末尾若干行，供前端实时显示执行流程。"""
        return self._works.read_log(work_id, tail)

    def open_path(self, path: str) -> bool:
        """用系统默认方式打开指定文件或文件夹。"""
        if not path:
            return False
        return self._reveal(Path(path))

    # ---- 音频编辑器 ----
    def list_editor_projects(self) -> list[dict[str, Any]]:
        return self._editor.list()

    def get_editor_project(self, project_id: str) -> dict[str, Any] | None:
        return self._editor.get(project_id)

    def delete_editor_project(self, project_id: str) -> bool:
        return self._editor.remove(project_id)

    def create_editor_project_from_audio(
        self, path: str, title: str | None = None
    ) -> dict[str, Any] | None:
        return self._editor.create_from_audio(path, title, _UI_LOCALE)

    def create_editor_project_from_work(self, work_id: str) -> dict[str, Any] | None:
        return self._editor.create_from_work(work_id, _UI_LOCALE)

    def create_editor_project_blank(self, title: str | None = None) -> dict[str, Any] | None:
        return self._editor.create_blank(title, _UI_LOCALE)

    def export_editor_project_bundle(self, project_id: str) -> dict[str, Any]:
        project = self._editor.get(project_id)
        if not project:
            return {"ok": False, "error": "工程不存在"}
        title = str(project.get("title") or self._dialog_text("音频编辑工程")).strip()
        destination = self._save_dialog(
            "导出音频编辑工程",
            f"{_safe_filename(title)}.xbproject",
            ("音频编辑工程 (*.xbproject)",),
        )
        if not destination:
            return {"ok": False, "cancelled": True}
        target = Path(destination)
        if target.suffix.lower() != ".xbproject":
            target = target.with_suffix(".xbproject")
        try:
            exported = self._editor.export_bundle(project_id, target)
            return {"ok": True, "path": str(exported)}
        except Exception as exc:  # noqa: BLE001 - 将打包错误返回给桌面端界面
            return {"ok": False, "error": str(exc) or "工程导出失败"}

    def import_editor_project_bundle(self) -> dict[str, Any]:
        selected = self._open_dialog(
            "导入音频编辑工程",
            multiple=False,
            file_types=(
                "音频编辑工程 (*.xbproject)",
                "所有文件 (*.*)",
            ),
        )
        if not selected:
            return {"ok": False, "cancelled": True}
        try:
            project = self._editor.import_bundle(Path(selected[0]))
            return {"ok": True, "path": selected[0], "project": project}
        except Exception as exc:  # noqa: BLE001 - 将损坏包等读取错误返回给桌面端界面
            return {"ok": False, "error": str(exc) or "工程导入失败"}

    def add_editor_track(
        self, project_id: str, name: str | None = None, kind: str = "audio"
    ) -> dict[str, Any]:
        return self._editor.add_track(project_id, name, kind)

    def delete_editor_track(self, project_id: str, track_id: str) -> dict[str, Any]:
        return self._editor.delete_track(project_id, track_id)

    def import_audio_to_editor_track(
        self,
        project_id: str,
        path: str,
        track_id: str | None = None,
        start: float = 0.0,
    ) -> dict[str, Any]:
        return self._editor.import_audio_to_track(project_id, path, track_id, float(start or 0.0))

    def paste_audio_to_editor_track(
        self,
        project_id: str,
        track_id: str | None = None,
        start: float = 0.0,
    ) -> dict[str, Any]:
        return self._editor.paste_clipboard_audio_to_track(
            project_id,
            track_id,
            float(start or 0.0),
        )

    def save_editor_project(self, project: dict[str, Any]) -> dict[str, Any] | None:
        return self._editor.save(project or {}, push_history=True)

    def undo_editor_project(self, project_id: str) -> dict[str, Any] | None:
        return self._editor.undo(project_id)

    def redo_editor_project(self, project_id: str) -> dict[str, Any] | None:
        return self._editor.redo(project_id)

    def get_editor_clip_audio(self, project_id: str, clip_id: str) -> str:
        return self._editor.clip_audio(project_id, clip_id)

    def get_editor_plugin_host_status(self) -> dict[str, Any]:
        return self._editor.plugin_host_status()

    def inspect_editor_effect_plugin(self, path: str) -> dict[str, Any]:
        return self._editor.inspect_effect_plugin(path)

    def open_editor_effect_plugin(
        self,
        project_id: str,
        track_id: str,
        clip_id: str,
        effect_id: str,
        parent_window: str = "",
        effect_scope: str = "clip",
        role_id: str = "",
    ) -> dict[str, Any]:
        return self._editor.open_effect_plugin_editor(
            project_id,
            track_id,
            clip_id,
            effect_id,
            parent_window,
            effect_scope,
            role_id,
        )

    def close_editor_effect_plugin(self, session_id: str) -> dict[str, Any]:
        return self._editor.close_effect_plugin_editor(session_id)

    def sync_editor_effect_plugin(
        self,
        session_id: str,
        transport: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._editor.sync_effect_plugin_editor(session_id, transport or {})

    def copy_editor_clip_audio(
        self,
        project_id: str,
        clip_id: str,
        fmt: str = "wav",
    ) -> dict[str, Any]:
        return self._editor.copy_clip_audio(project_id, clip_id, fmt)

    def copy_editor_track_audio(
        self,
        project_id: str,
        track_id: str,
        fmt: str = "wav",
    ) -> dict[str, Any]:
        return self._editor.copy_track_audio(project_id, track_id, fmt)

    def merge_editor_clips(
        self,
        project_id: str,
        track_id: str,
        clip_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return self._editor.merge_clips(project_id, track_id, clip_ids or [])

    def render_editor_preview(self, project_id: str) -> str:
        return self._editor.render_preview(project_id)

    def render_editor_project(self, project_id: str, fmt: str = "wav") -> str:
        path = self._editor.render(project_id, fmt)
        return str(path) if path else ""

    def export_editor_project(self, project_id: str, fmt: str = "wav") -> str:
        src = self._editor.render(project_id, fmt)
        if src is None:
            return ""
        project = self._editor.get(project_id) or {}
        title = (project.get("title") or src.stem).strip()
        ext = "." + self._editor._normalize_format(fmt)
        filename = f"{_safe_filename(title)}{ext}"
        metadata = project.get("metadata") or {}
        dialog_title = (
            "导出编辑器人声"
            if metadata.get("export_mode") == "vocal"
            else "导出编辑器混音"
        )
        dest = self._save_dialog(dialog_title, filename, (f"音频文件 (*.{ext.lstrip('.')})",))
        if not dest:
            return ""
        dest_path = Path(dest)
        if dest_path.suffix.lower() != ext:
            dest_path = dest_path.with_suffix(ext)
        try:
            shutil.copyfile(src, dest_path)
            return str(dest_path)
        except OSError:
            return ""

    def export_editor_track(self, project_id: str, track_id: str, fmt: str = "wav") -> str:
        """导出单条音轨的音频文件（只渲染该轨的片段与效果）。"""
        project = self._editor.get(project_id) or {}
        track = next(
            (
                item
                for item in project.get("tracks") or []
                if str(item.get("id") or "") == str(track_id or "")
            ),
            None,
        )
        src = self._editor.render_track(project_id, track_id, fmt)
        if src is None:
            return ""
        ext = "." + self._editor._normalize_format(fmt)
        title = str(project.get("title") or self._dialog_text("音频编辑")).strip()
        track_name = str((track or {}).get("name") or self._dialog_text("音轨")).strip()
        filename = f"{_safe_filename(title)}_{_safe_filename(track_name)}{ext}"
        dest = self._save_dialog("导出音轨音频", filename, (f"音频文件 (*.{ext.lstrip('.')})",))
        if not dest:
            return ""
        dest_path = Path(dest)
        if dest_path.suffix.lower() != ext:
            dest_path = dest_path.with_suffix(ext)
        try:
            shutil.copyfile(src, dest_path)
            return str(dest_path)
        except OSError:
            return ""

    def get_editor_waveform(
        self, project_id: str, clip_id: str, bins: int = 160
    ) -> dict[str, Any]:
        return self._editor.waveform(project_id, clip_id, int(bins or 160))

    def preload_editor_waveforms(self, project_id: str, bins: int = 160) -> bool:
        return self._editor.preload_waveforms(project_id, int(bins or 160))

    def split_editor_clip_by_silence(
        self,
        project_id: str,
        track_id: str,
        clip_id: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._editor.split_clip_by_silence(
            project_id, track_id, clip_id, options or {}
        )

    def separate_editor_clip_vocals(
        self,
        project_id: str,
        track_id: str,
        clip_id: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._editor.separate_clip_vocals(project_id, track_id, clip_id, options or {})

    def split_editor_clip_by_lyrics(
        self,
        project_id: str,
        track_id: str,
        clip_id: str,
        lyrics: Any,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._editor.split_clip_by_lyrics(
            project_id, track_id, clip_id, lyrics, options or {}
        )

    def rerun_editor_clip(
        self,
        project_id: str,
        track_id: str,
        clip_id: str,
        model_id: str,
        params: dict[str, Any] | None = None,
        enhance: dict[str, Any] | None = None,
        locale: str = "",
    ) -> dict[str, Any]:
        return self._editor.rerun_clip(
            project_id,
            track_id,
            clip_id,
            model_id,
            params or {},
            enhance or {},
            locale or _UI_LOCALE,
        )

    def get_editor_rerun_status(self, job_id: str) -> dict[str, Any] | None:
        return self._editor.rerun_status(job_id)

    def get_editor_rerun_log(self, job_id: str) -> str | None:
        return self._editor.rerun_log(job_id)

    def enhance_editor_clip(
        self,
        project_id: str,
        track_id: str,
        clip_id: str,
        reference_path: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._editor.enhance_clip(
            project_id,
            track_id,
            clip_id,
            reference_path,
            options or {},
        )

    # ---- MIDI 子编辑器 ----

    def get_editor_clip_midi(
        self,
        project_id: str,
        clip_id: str,
        refresh: bool = False,
    ) -> dict[str, Any]:
        return self._editor.clip_midi(project_id, clip_id, refresh=bool(refresh))

    def save_editor_clip_midi(
        self,
        project_id: str,
        clip_id: str,
        notes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return self._editor.save_clip_midi(project_id, clip_id, notes or [])

    def apply_editor_clip_midi(
        self,
        project_id: str,
        clip_id: str,
        notes: list[dict[str, Any]] | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._editor.apply_clip_midi(project_id, clip_id, notes, options or {})

    def preview_editor_clip_midi(
        self,
        project_id: str,
        clip_id: str,
        notes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """试听：按当前音符重绘片段音频，返回可直接播放的 audio data URI。"""
        return self._editor.preview_clip_midi(project_id, clip_id, notes)

    def get_editor_track_midi(
        self,
        project_id: str,
        track_id: str,
        refresh: bool = False,
    ) -> dict[str, Any]:
        return self._editor.track_midi(project_id, track_id, refresh=bool(refresh))

    def save_editor_track_midi(
        self,
        project_id: str,
        track_id: str,
        notes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return self._editor.save_track_midi(project_id, track_id, notes or [])

    def apply_editor_track_midi(
        self,
        project_id: str,
        track_id: str,
        notes: list[dict[str, Any]] | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._editor.apply_track_midi(project_id, track_id, notes, options or {})

    # ---- MIDI 编曲（多乐器音序器） ----

    def get_editor_midi_session(
        self,
        project_id: str,
        track_id: str = "",
        clip_id: str = "",
    ) -> dict[str, Any]:
        return self._editor.midi_session(project_id, track_id, clip_id)

    def save_editor_midi_session(
        self,
        project_id: str,
        track_id: str,
        session: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._editor.save_midi_session(project_id, track_id, session or {})

    def render_editor_midi_session(
        self,
        project_id: str,
        track_id: str,
        session: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._editor.render_midi_session(project_id, track_id, session, options or {})

    def start_editor_midi_render(
        self,
        project_id: str,
        track_id: str,
        session: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """后台渲染 MIDI 编曲；立即返回 job_id，前端用 editor_midi_render_status 轮询。"""
        return self._editor.start_midi_render(project_id, track_id, session, options or {})

    def editor_midi_render_status(self, job_id: str = "") -> dict[str, Any]:
        state = self._editor.midi_render_status(job_id)
        if not state:
            return {"ok": False, "error": "渲染任务不存在或已过期"}
        return {"ok": True, **state}

    def preview_editor_midi_session(
        self,
        project_id: str,
        track_id: str,
        session: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._editor.preview_midi_session(project_id, track_id, session)

    def export_editor_midi_session(
        self,
        project_id: str,
        track_id: str,
        session: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """导出 .mid 到工程目录（不弹对话框，供 HTTP / 自动化调用）。"""
        return self._editor.export_midi_session(project_id, track_id, session)

    def export_editor_midi_file(
        self,
        project_id: str,
        track_id: str,
        session: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """导出 .mid：先在工程里生成，再让用户选保存位置。"""
        result = self._editor.export_midi_session(project_id, track_id, session)
        if not result.get("ok"):
            return result
        source = Path(str(result.get("path") or ""))
        if not source.is_file():
            return {"ok": False, "error": "MIDI 文件生成失败"}
        project = self._editor.get(project_id) or {}
        title = str(project.get("title") or "MIDI").strip()
        destination = self._save_dialog(
            "导出 MIDI 文件",
            f"{_safe_filename(title)}_MIDI.mid",
            ("MIDI 文件 (*.mid;*.midi)",),
        )
        if not destination:
            return {**result, "cancelled": True}
        target = Path(destination)
        if target.suffix.lower() not in (".mid", ".midi"):
            target = target.with_suffix(".mid")
        try:
            shutil.copyfile(source, target)
        except OSError as exc:
            return {"ok": False, "error": f"MIDI 保存失败：{exc}"}
        return {**result, "path": str(target)}

    def import_editor_midi_file(
        self,
        project_id: str,
        track_id: str,
    ) -> dict[str, Any]:
        """导入 .mid：选择文件后解析成多声部编曲会话。"""
        paths = self._open_dialog(
            "导入 MIDI 文件", False, ("MIDI 文件 (*.mid;*.midi)", "全部文件 (*.*)")
        )
        if not paths:
            return {"ok": False, "cancelled": True, "error": ""}
        return self._editor.import_midi_session(project_id, track_id, paths[0])

    def import_midi_tracks(self) -> dict[str, Any]:
        """导入 .mid 到某个声部：选择文件后解析各轨音符返回给前端。"""
        paths = self._open_dialog(
            "导入 MIDI 到声部", False, ("MIDI 文件 (*.mid;*.midi)", "全部文件 (*.*)")
        )
        if not paths:
            return {"ok": False, "cancelled": True, "error": ""}
        return self._editor.parse_midi_tracks(paths[0])

    @staticmethod
    def _reveal(path: Path) -> bool:
        """跨平台打开文件/文件夹。"""
        try:
            if not path.exists():
                # 文件不存在时退回打开其父目录
                path = path.parent
            if not path.exists():
                return False
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
            return True
        except OSError:
            return False

    # ---- 内部：文件对话框 ----
    def _dialog_text(self, text: str) -> str:
        """按前端当前界面语言翻译对话框标题 / 默认文件名。"""
        return dialog_text.translate_dialog_text(text, _UI_LOCALE)

    @staticmethod
    def _dialog_file_types(file_types: tuple[str, ...]) -> tuple[str, ...]:
        """翻译 ``名称 (*.ext)`` 中的名称，保留扩展名筛选语法。"""
        return tuple(dialog_text.translate_file_type(item, _UI_LOCALE) for item in file_types)

    def _open_dialog(self, title: str, multiple: bool, file_types: tuple[str, ...]) -> list[str]:
        # pywebview 不接收标题，但保留翻译以便将来支持；文件类型是用户可见的筛选名。
        title = self._dialog_text(title)
        file_types = self._dialog_file_types(file_types)
        try:
            import webview

            window = self._window or webview.active_window()
            if window is None and webview.windows:
                window = webview.windows[0]
            if window is None:
                return []
            result = window.create_file_dialog(
                cast(int, webview.OPEN_DIALOG),
                allow_multiple=multiple,
                file_types=file_types,
            )
            if not result:
                return []
            return [str(p) for p in result]
        except Exception:  # noqa: BLE001 - 无 GUI 环境时静默返回
            return []

    def _save_dialog(
        self,
        title: str,
        filename: str,
        file_types: tuple[str, ...] = (),
    ) -> str:
        # 保存对话框里用户最先看到的是默认文件名与类型筛选，都要跟随界面语言。
        title = self._dialog_text(title)
        filename = self._dialog_text(filename)
        file_types = self._dialog_file_types(file_types)
        try:
            import webview

            window = self._window or webview.active_window()
            if window is None and webview.windows:
                window = webview.windows[0]
            if window is None:
                return ""
            result = window.create_file_dialog(
                cast(int, webview.SAVE_DIALOG),
                save_filename=filename,
                file_types=file_types,
            )
            if not result:
                return ""
            return result if isinstance(result, str) else str(result[0])
        except Exception:  # noqa: BLE001 - 无 GUI 环境时静默返回
            return ""

    def _folder_dialog(self, title: str) -> str:
        title = self._dialog_text(title)
        try:
            import webview

            window = self._window or webview.active_window()
            if window is None and webview.windows:
                window = webview.windows[0]
            if window is None:
                return ""
            result = window.create_file_dialog(cast(int, webview.FOLDER_DIALOG))
            if not result:
                return ""
            return result if isinstance(result, str) else str(result[0])
        except Exception:  # noqa: BLE001 - 无 GUI 环境时静默返回
            return ""
