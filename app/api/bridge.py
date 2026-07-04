"""pywebview JS API 桥接。

``Api`` 的所有公有方法都会被 pywebview 暴露为 ``window.pywebview.api.<method>``，
前端通过 Promise 调用。这里只做参数转换与服务编排，不含具体业务逻辑。

``build_api`` 是组合根（composition root）：装配基础设施、仓储与应用服务。
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
from typing import Any

import config
from application import (
    AudioEditorService,
    ConversionService,
    ModelHubService,
    ModelService,
    MusicService,
    SystemService,
    WorkService,
)
from infrastructure import paths
from infrastructure.engine import EngineRegistry
from infrastructure.ffmpeg_tool import FfmpegTool
from infrastructure.rvc_engine import RvcEngine
from infrastructure.storage import ListRepository, SettingsStore
from infrastructure.svc_engine import SvcEngine
from infrastructure.uvr_tool import UvrTool


def _safe_filename(name: str) -> str:
    """清洗为合法文件名（去除非法字符并限长），用于导出默认名。"""
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name or "").strip().strip(".")
    return cleaned[:120] or "翻唱作品"


class Api:
    def __init__(
        self,
        system: SystemService,
        models: ModelService,
        works: WorkService,
        music: MusicService,
        hub: ModelHubService,
        editor: AudioEditorService,
    ) -> None:
        self._system = system
        self._models = models
        self._works = works
        self._music = music
        self._hub = hub
        self._editor = editor
        self._window = None

    def set_window(self, window) -> None:  # noqa: ANN001
        """由入口在创建窗口后注入，用于打开原生文件对话框。"""
        self._window = window

    # ---- 系统 ----
    def get_system_status(self) -> dict[str, Any]:
        return self._system.status()

    def apply_window_theme(self, theme: str) -> bool:
        """让原生窗口标题栏/边框跟随前端主题（cyber / anime）。

        前端在挂载及切换主题时调用；非 Windows 平台静默返回 False。
        """
        from infrastructure.window_theme import apply as _apply_window_theme

        name = theme if theme in ("cyber", "anime") else "cyber"
        return _apply_window_theme(config.APP_TITLE, name)

    def get_data_storage_status(self) -> dict[str, Any]:
        """返回用户数据目录、占用和所在磁盘剩余空间。"""
        return self._data_storage_payload()

    def pick_data_dir(self) -> str:
        """选择新的用户数据目录。"""
        result = self._folder_dialog("选择 XB-SVCB 用户数据目录")
        return result or ""

    def migrate_data_dir(self, target_dir: str) -> dict[str, Any]:
        """把用户数据目录复制到新位置，并写入下次启动使用的新目录。"""
        queue = self._works.queue_status()
        if queue.get("running") or queue.get("size"):
            return {
                "ok": False,
                "error": "当前有推理任务正在运行或排队，请等待任务结束后再迁移数据目录。",
                **self._data_storage_payload(),
            }
        try:
            src = config.DATA_DIR.resolve()
            target = Path(target_dir or "").expanduser().resolve()
        except OSError:
            return {"ok": False, "error": "目标目录无效。", **self._data_storage_payload()}
        if not target:
            return {"ok": False, "error": "请选择目标目录。", **self._data_storage_payload()}
        if target == src:
            return {"ok": False, "error": "目标目录与当前目录相同。", **self._data_storage_payload()}
        if target.parent == target:
            return {"ok": False, "error": "目标目录不能直接使用磁盘根目录。", **self._data_storage_payload()}
        if target.exists() and not target.is_dir():
            return {"ok": False, "error": "目标路径不是文件夹。", **self._data_storage_payload()}
        if self._is_relative_path(target, src) or self._is_relative_path(src, target):
            return {
                "ok": False,
                "error": "目标目录不能位于当前数据目录内部，也不能包含当前数据目录。",
                **self._data_storage_payload(),
            }
        if target.exists() and any(target.iterdir()):
            marker = target / config.DATA_MARKER_FILE
            if not marker.exists():
                return {
                    "ok": False,
                    "error": "目标目录不是空目录。请选择空目录，或选择已有 XB-SVCB 数据目录。",
                    **self._data_storage_payload(),
                }

        required = self._dir_size(src)
        try:
            target.mkdir(parents=True, exist_ok=True)
            usage = shutil.disk_usage(target)
        except OSError:
            return {"ok": False, "error": "无法访问目标目录或磁盘。", **self._data_storage_payload()}
        safety = max(512 * 1024 * 1024, int(required * 0.08))
        if usage.free < required + safety:
            return {
                "ok": False,
                "error": (
                    f"目标磁盘空间不足：需要至少 {paths.human_size(required + safety)}，"
                    f"当前可用 {paths.human_size(usage.free)}。"
                ),
                **self._data_storage_payload(),
            }
        if not self._test_writable(target):
            return {"ok": False, "error": "目标目录不可写。", **self._data_storage_payload()}

        staging = target.with_name(target.name + ".migrating")
        try:
            if staging.exists():
                shutil.rmtree(staging)
            if target.exists() and any(target.iterdir()):
                # 已有 XB-SVCB 数据目录：先不覆盖，直接切换指针。
                staging = target
            else:
                shutil.copytree(src, staging, ignore=shutil.ignore_patterns("*.tmp"))
                if target.exists():
                    target.rmdir()
                staging.replace(target)
            (target / config.DATA_MARKER_FILE).write_text(
                json.dumps(
                    {
                        "app": config.APP_NAME,
                        "migrated_from": str(src),
                        "version": config.APP_VERSION,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (src / config.DATA_MIGRATION_MARKER).write_text(
                json.dumps({"target": str(target)}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if not config.write_data_home(target, pending_delete=src):
                return {
                    "ok": False,
                    "error": "数据已复制，但写入数据目录指针失败。",
                    **self._data_storage_payload(),
                }
            next_usage = shutil.disk_usage(target)
            return {
                "ok": True,
                "restart_required": True,
                "message": "数据目录已迁移。请重启软件，重启后将使用新目录并自动清理旧目录。",
                "data_dir": str(target),
                "old_data_dir": str(src),
                "used_bytes": required,
                "used": paths.human_size(required),
                "free_bytes": next_usage.free,
                "free": paths.human_size(next_usage.free),
            }
        except OSError as exc:
            try:
                if staging.exists() and staging != target:
                    shutil.rmtree(staging)
            except OSError:
                pass
            return {
                "ok": False,
                "error": f"迁移失败：{exc}",
                **self._data_storage_payload(),
            }

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

    def import_model(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """导入一组模型，按 framework 分支：so-vits（主模型+配置+可选扩散）/ rvc（主模型+可选 index）。"""
        return self._models.import_model(payload or {})

    def set_default_model(self, model_id: str) -> bool:
        return self._models.set_default(model_id)

    def delete_model(self, model_id: str) -> bool:
        return self._models.remove(model_id)

    def inspect_model(self, model_id: str, repair: bool = False) -> dict[str, Any]:
        return self._models.inspect(model_id, bool(repair))

    def toggle_model_favorite(self, model_id: str) -> dict[str, Any] | None:
        return self._models.toggle_favorite(model_id)

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
        self, model_id: str, name: str | None = None, framework: str | None = None
    ) -> dict[str, Any]:
        """把本地模型上传到模型站（用户自己的 ModelScope 命名空间），并标注模型架构。"""
        return self._hub.upload(model_id, name, framework)

    def hub_progress(self, key: str) -> dict[str, Any]:
        """轮询上传/下载进度。key 形如 'dl:<repo_id>' 或 'ul:<model_id>'。"""
        return self._hub.get_progress(key or "")

    def hub_start_download(self, repo_id: str) -> dict[str, Any]:
        """后台下载并导入模型，立即返回 {ok, key}，不阻塞前端。"""
        return self._hub.start_download(repo_id)

    def hub_start_upload(
        self, model_id: str, name: str | None = None, framework: str | None = None
    ) -> dict[str, Any]:
        """后台上传本地模型到模型站，立即返回 {ok, key}，不阻塞前端。"""
        return self._hub.start_upload(model_id, name, framework)

    def hub_list_jobs(self) -> list[dict[str, Any]]:
        """列出全部上传/下载后台任务（含实时进度）。"""
        return self._hub.list_jobs()

    def hub_clear_job(self, key: str) -> bool:
        """清理一条已完成/失败的传输任务记录。"""
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

    def list_works(self) -> list[dict[str, Any]]:
        return self._works.list()

    def get_work(self, work_id: str) -> dict[str, Any] | None:
        return self._works.get(work_id)

    def create_work(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._works.create(payload or {})

    def create_batch_work(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return self._works.create_batch(payload or {})

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

    def retry_work(self, work_id: str) -> bool:
        return self._works.retry(work_id)

    def rename_work(self, work_id: str, title: str) -> bool:
        """重命名作品；新标题同时作为导出文件的默认名。"""
        return self._works.rename(work_id, title)

    def delete_work(self, work_id: str) -> bool:
        return self._works.remove(work_id)

    def get_work_audio(self, work_id: str) -> str:
        """返回成品音频的 data URI（base64），供前端 <audio> 直接播放。"""
        return self.get_stem_audio(work_id, "output")

    def get_stem_audio(self, work_id: str, kind: str) -> str:
        """返回指定音轨的 data URI，供前端试听。

        kind 取值：output（成品）/ instrumental（背景音乐）/ vocals（去混响干声）。
        有 ffmpeg 时转成体积更小的 mp3 再传输；否则直接回传 wav。
        """
        src = self._stem_path(work_id, kind)
        if src is None:
            return ""
        data: bytes | None = None
        mime = "audio/wav"
        ffmpeg = FfmpegTool()
        if ffmpeg.available:
            try:
                config.TEMP_DIR.mkdir(parents=True, exist_ok=True)
                mp3 = config.TEMP_DIR / f"{work_id}_{kind}.mp3"
                if ffmpeg.convert(src, mp3):
                    data = mp3.read_bytes()
                    mime = "audio/mpeg"
            except OSError:
                data = None
        if data is None:
            try:
                data = src.read_bytes()
            except OSError:
                return ""
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{b64}"

    def export_work(self, work_id: str) -> str:
        """弹出保存对话框，把成品音频另存到用户选择的位置，返回保存路径。

        默认文件名取作品标题（与重命名后的名称保持一致），后缀沿用成品格式。
        """
        src = self._stem_path(work_id, "output")
        if src is None:
            return ""
        work = self._works.get(work_id) or {}
        title = (work.get("title") or src.stem).strip()
        ext = src.suffix or ".wav"
        filename = f"{_safe_filename(title)}{ext}"
        dest = self._save_dialog("导出翻唱作品", filename)
        if not dest:
            return ""
        try:
            shutil.copyfile(src, dest)
            return dest
        except OSError:
            return ""

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

    def get_music_song(self, msg: str, n: int, source: str | None = None) -> dict[str, Any]:
        return self._music.get_song(msg, n, source)

    def download_music(self, msg: str, n: int, source: str | None = None) -> dict[str, Any]:
        return self._music.download(msg, n, source)

    def get_music_lyrics(self, msg: str, n: int, source: str | None = None) -> dict[str, Any]:
        """按歌名+索引获取带时间轴的歌词（多模型混合翻唱用）。"""
        return self._music.get_lyrics(msg, n, source)

    def get_audio_duration(self, path: str) -> float:
        """探测本地音频时长（秒），失败返回 0。用于歌词/文件时长匹配校验。"""
        if not path:
            return 0.0
        dur = FfmpegTool().probe_duration(Path(path))
        return float(dur or 0.0)

    def list_music(self) -> list[dict[str, Any]]:
        return self._music.list_downloaded()

    def delete_music(self, path: str) -> bool:
        return self._music.delete_downloaded(path)

    def _stem_path(self, work_id: str, kind: str) -> Path | None:
        """解析作品某条音轨的真实路径，并校验其位于数据目录内。"""
        work = self._works.get(work_id) or {}
        key = {
            "output": "output_path",
            "instrumental": "instrumental_path",
            "vocals": "vocals_path",
        }.get(kind)
        if not key:
            return None
        raw = work.get(key) or (work.get("output") if kind == "output" else None)
        if not raw:
            return None
        try:
            path = Path(raw).resolve()
            allowed = config.WORKS_DIR.resolve()
        except OSError:
            return None
        # 仅允许读取数据目录内的文件，避免任意路径读取
        if allowed not in path.parents:
            return None
        return path if path.exists() else None

    def open_work_log(self, work_id: str) -> bool:
        """在系统文件管理器中打开该任务的日志所在文件夹。"""
        work = self._works.get(work_id)
        log_path = (work or {}).get("log_path")
        target = Path(log_path) if log_path else (config.WORKS_DIR / work_id)
        folder = target.parent if target.suffix else target
        return self._reveal(folder)

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
        return self._editor.create_from_audio(path, title)

    def create_editor_project_from_work(self, work_id: str) -> dict[str, Any] | None:
        return self._editor.create_from_work(work_id)

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

    def save_editor_project(self, project: dict[str, Any]) -> dict[str, Any] | None:
        return self._editor.save(project or {}, push_history=True)

    def undo_editor_project(self, project_id: str) -> dict[str, Any] | None:
        return self._editor.undo(project_id)

    def redo_editor_project(self, project_id: str) -> dict[str, Any] | None:
        return self._editor.redo(project_id)

    def get_editor_clip_audio(self, project_id: str, clip_id: str) -> str:
        return self._editor.clip_audio(project_id, clip_id)

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
        dest = self._save_dialog(dialog_title, filename)
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
    ) -> dict[str, Any]:
        return self._editor.rerun_clip(project_id, track_id, clip_id, model_id, params or {})

    @staticmethod
    def _dir_size(root: Path) -> int:
        total = 0
        if not root.exists():
            return 0
        for item in root.rglob("*"):
            try:
                if item.is_file():
                    total += item.stat().st_size
            except OSError:
                pass
        return total

    @staticmethod
    def _is_relative_path(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False

    @staticmethod
    def _test_writable(path: Path) -> bool:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".xb_xvcb_write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return True
        except OSError:
            return False

    def _data_storage_payload(self) -> dict[str, Any]:
        data_dir = config.DATA_DIR
        used = self._dir_size(data_dir)
        try:
            usage = shutil.disk_usage(data_dir if data_dir.exists() else data_dir.parent)
            free = usage.free
            total = usage.total
        except OSError:
            free = 0
            total = 0
        return {
            "data_dir": str(data_dir),
            "used_bytes": used,
            "used": paths.human_size(used),
            "free_bytes": free,
            "free": paths.human_size(free),
            "total_bytes": total,
            "total": paths.human_size(total),
            "pointer_file": str(config.DATA_HOME_FILE),
        }

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
    def _open_dialog(self, title: str, multiple: bool, file_types: tuple[str, ...]) -> list[str]:
        try:
            import webview

            window = self._window or webview.active_window()
            if window is None and webview.windows:
                window = webview.windows[0]
            if window is None:
                return []
            result = window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=multiple,
                file_types=file_types,
            )
            if not result:
                return []
            return [str(p) for p in result]
        except Exception:  # noqa: BLE001 - 无 GUI 环境时静默返回
            return []

    def _save_dialog(self, title: str, filename: str) -> str:
        try:
            import webview

            window = self._window or webview.active_window()
            if window is None and webview.windows:
                window = webview.windows[0]
            if window is None:
                return ""
            result = window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=filename,
            )
            if not result:
                return ""
            return result if isinstance(result, str) else str(result[0])
        except Exception:  # noqa: BLE001 - 无 GUI 环境时静默返回
            return ""

    def _folder_dialog(self, title: str) -> str:
        try:
            import webview

            window = self._window or webview.active_window()
            if window is None and webview.windows:
                window = webview.windows[0]
            if window is None:
                return ""
            result = window.create_file_dialog(webview.FOLDER_DIALOG)
            if not result:
                return ""
            return result if isinstance(result, str) else str(result[0])
        except Exception:  # noqa: BLE001 - 无 GUI 环境时静默返回
            return ""


def build_api() -> Api:
    """组合根：装配所有依赖并返回 Api 实例。"""
    paths.ensure_dirs()

    # 基础设施
    ffmpeg = FfmpegTool()
    uvr = UvrTool()
    svc = SvcEngine()
    rvc = RvcEngine()
    # 引擎注册表：按模型 framework 路由推理引擎（缺省回退 so-vits-svc）
    engines = EngineRegistry([svc, rvc])

    models_repo = ListRepository(config.MODELS_DB)
    works_repo = ListRepository(config.WORKS_DB)
    editor_repo = ListRepository(config.EDITOR_PROJECTS_DB)
    settings = SettingsStore(config.SETTINGS_DB)

    # 应用服务
    system_service = SystemService(ffmpeg, uvr, svc, rvc)
    model_service = ModelService(models_repo, settings)
    conversion_service = ConversionService(works_repo, ffmpeg, uvr, engines)
    work_service = WorkService(works_repo, conversion_service, model_service, settings)
    music_service = MusicService(settings)
    hub_service = ModelHubService(settings, model_service)
    editor_service = AudioEditorService(
        editor_repo, works_repo, model_service, ffmpeg, uvr, engines
    )

    # 启动时回收上次会话残留的"处理中"任务（其后台线程已随进程退出而终止）
    work_service.recover_stale()

    return Api(
        system_service,
        model_service,
        work_service,
        music_service,
        hub_service,
        editor_service,
    )
