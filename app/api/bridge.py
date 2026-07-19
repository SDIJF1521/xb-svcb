"""pywebview JS API 桥接。

``Api`` 的所有公有方法都会被 pywebview 暴露为 ``window.pywebview.api.<method>``，
前端通过 Promise 调用。这里只做参数转换与服务编排，不含具体业务逻辑。

``build_api`` 是组合根（composition root）：装配基础设施、仓储与应用服务。
"""

from __future__ import annotations

import base64
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
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
from infrastructure.ddsp_engine import DdspSvcEngine
from infrastructure.ffmpeg_tool import FfmpegTool
from infrastructure.rvc_engine import RvcEngine
from infrastructure.seedvc_engine import SeedVcEngine
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
        models_repo: ListRepository,
        works_repo: ListRepository,
        editor_repo: ListRepository,
        settings: SettingsStore,
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
        self._window = None
        self._migration_lock = threading.Lock()
        self._migration = self._empty_migration_status()

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

    def pick_theme_media_file(self) -> dict[str, Any]:
        """选择自定义主题背景媒体，并复制到数据目录以便重启后继续使用。"""
        result = self._open_dialog(
            "选择主题背景图片或 MP4 动态壁纸",
            multiple=False,
            file_types=(
                "背景媒体 (*.jpg;*.jpeg;*.png;*.webp;*.gif;*.mp4)",
                "图片 (*.jpg;*.jpeg;*.png;*.webp;*.gif)",
                "MP4 视频 (*.mp4)",
                "所有文件 (*.*)",
            ),
        )
        if not result:
            return {"ok": False, "cancelled": True}
        src = Path(result[0])
        if not src.exists() or not src.is_file():
            return {"ok": False, "error": "媒体文件不存在"}
        ext = src.suffix.lower()
        image_mimes = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }
        if ext == ".mp4":
            kind = "video"
            mime = "video/mp4"
            max_bytes = 200 * 1024 * 1024
        elif ext in image_mimes:
            kind = "image"
            mime = image_mimes[ext]
            max_bytes = 50 * 1024 * 1024
        else:
            return {"ok": False, "error": "仅支持图片或 MP4 视频"}
        try:
            if src.stat().st_size > max_bytes:
                limit = "200MB" if kind == "video" else "50MB"
                return {"ok": False, "error": f"媒体文件过大，请选择不超过 {limit} 的文件"}
        except OSError:
            return {"ok": False, "error": "无法读取媒体文件"}

        paths.ensure_dirs()
        safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", src.stem).strip("._") or "theme_media"
        dst = config.THEME_MEDIA_DIR / f"{time.time_ns()}_{safe_stem}{ext}"
        try:
            shutil.copy2(src, dst)
        except OSError as exc:
            return {"ok": False, "error": f"复制背景媒体失败：{exc}"}
        return {"ok": True, "path": dst.name, "kind": kind, "mime": mime, "name": src.name}

    def get_theme_media_data(self, media_path: str) -> str:
        """返回已保存主题媒体的 data URI，供背景图/视频播放。"""
        raw = str(media_path or "").strip()
        if not raw:
            return ""
        try:
            candidate = Path(raw)
            if candidate.is_absolute():
                path = candidate.expanduser().resolve()
            else:
                if candidate.name != raw or candidate.name in {"", ".", ".."}:
                    return ""
                path = (config.THEME_MEDIA_DIR / candidate.name).resolve()
            media_root = config.THEME_MEDIA_DIR.resolve()
            if path != media_root and media_root not in path.parents:
                return ""
            if not path.exists() or not path.is_file():
                return ""
            ext = path.suffix.lower()
            mime_by_ext = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".webp": "image/webp",
                ".gif": "image/gif",
                ".mp4": "video/mp4",
            }
            mime = mime_by_ext.get(ext)
            if not mime:
                return ""
            data = path.read_bytes()
        except OSError:
            return ""
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{b64}"

    def get_data_storage_status(self) -> dict[str, Any]:
        """返回用户数据目录、占用和所在磁盘剩余空间。"""
        self._refresh_active_data_dir_from_home()
        return self._data_storage_payload()

    def pick_data_dir(self) -> str:
        """选择新的用户数据目录。"""
        result = self._folder_dialog("选择 XB-SVCB 用户数据目录")
        return result or ""

    def set_data_dir(self, target_dir: str) -> dict[str, Any]:
        """直接切换到用户选择的数据目录，不复制当前数据。"""
        with self._migration_lock:
            if self._migration.get("status") == "running":
                return {
                    "ok": False,
                    "error": "数据目录迁移正在进行中，请等待当前迁移完成。",
                    **self._data_storage_payload(),
                }

        blocker = self._data_dir_change_blocker()
        if blocker:
            return {"ok": False, "error": blocker, **self._data_storage_payload()}

        try:
            current = config.DATA_DIR.resolve()
            current.mkdir(parents=True, exist_ok=True)
        except OSError:
            return {"ok": False, "error": "当前数据目录无法访问。", **self._data_storage_payload()}

        target, target_error = self._resolve_data_dir_target(target_dir, current)
        if target_error:
            return {"ok": False, "error": target_error, **self._data_storage_payload()}
        if target is None:
            return {"ok": False, "error": "请选择目标目录。", **self._data_storage_payload()}
        if target == current:
            return {
                "ok": True,
                "restart_required": False,
                "message": "当前已经在使用这个数据目录。",
                **self._data_storage_payload(),
            }

        try:
            target.mkdir(parents=True, exist_ok=True)
            if not self._test_writable(target):
                return {"ok": False, "error": "目标目录不可写。", **self._data_storage_payload()}
            self._write_data_dir_marker(target, selected_from=str(target_dir or ""))
        except OSError as exc:
            return {
                "ok": False,
                "error": f"无法准备目标数据目录：{exc}",
                **self._data_storage_payload(),
            }

        if not config.write_data_home(target):
            return {
                "ok": False,
                "error": "写入数据目录指针失败。",
                **self._data_storage_payload(),
            }

        self._switch_active_data_dir(target)
        return {
            "ok": True,
            "restart_required": True,
            "message": "数据目录已切换，后续文件将写入新目录。建议重启软件以刷新窗口缓存。",
            **self._data_storage_payload(),
        }

    def start_data_migration(self, target_dir: str) -> dict[str, Any]:
        """启动后台数据目录迁移任务，前端通过 get_data_migration_status 轮询进度。"""
        with self._migration_lock:
            if self._migration.get("status") == "running":
                return {
                    "ok": False,
                    "error": "数据目录迁移正在进行中，请等待当前迁移完成。",
                    **self._migration,
                }
            blocker = self._data_dir_change_blocker()
            if blocker:
                return {
                    "ok": False,
                    "error": blocker,
                    **self._empty_migration_status(),
                }
            self._migration = {
                **self._empty_migration_status(),
                "status": "running",
                "phase": "preparing",
                "message": "正在准备迁移...",
                "target_dir": target_dir,
            }
        thread = threading.Thread(
            target=self._run_data_migration,
            args=(target_dir,),
            name="xb-data-migration",
            daemon=True,
        )
        thread.start()
        return {"ok": True, "started": True, **self.get_data_migration_status()}

    def get_data_migration_status(self) -> dict[str, Any]:
        """返回最近一次数据迁移任务状态。"""
        with self._migration_lock:
            status = dict(self._migration)
            if isinstance(status.get("result"), dict):
                status["result"] = dict(status["result"])
            return status

    def migrate_data_dir(self, target_dir: str) -> dict[str, Any]:
        """兼容旧前端的同步迁移入口。新前端使用 start/get status 显示进度。"""
        started = self.start_data_migration(target_dir)
        if not started.get("ok"):
            return {
                "ok": False,
                "error": started.get("error") or "迁移启动失败。",
                **self._data_storage_payload(),
            }
        while True:
            status = self.get_data_migration_status()
            if status.get("status") == "done":
                result = status.get("result")
                if isinstance(result, dict):
                    return result
                return {
                    "ok": True,
                    "message": status.get("message") or "数据目录已迁移。",
                    **self._data_storage_payload(),
                }
            if status.get("status") == "failed":
                return {
                    "ok": False,
                    "error": status.get("error") or "迁移失败。",
                    **self._data_storage_payload(),
                }
            time.sleep(0.2)

    def _run_data_migration(self, target_dir: str) -> None:
        """后台执行迁移，并持续更新 self._migration。"""
        blocker = self._data_dir_change_blocker()
        if blocker:
            self._fail_data_migration(blocker)
            return
        try:
            src = config.DATA_DIR.resolve()
            src.mkdir(parents=True, exist_ok=True)
        except OSError:
            self._fail_data_migration("当前数据目录无法访问。")
            return

        target, target_error = self._resolve_data_migration_target(target_dir, src)
        if target_error:
            self._fail_data_migration(target_error)
            return
        if target is None:
            self._fail_data_migration("请选择目标目录。")
            return

        self._update_data_migration(
            phase="scanning",
            message="正在统计需要迁移的数据...",
            percent=2,
            target_dir=str(target),
        )
        required = self._dir_size(src, ignore_tmp=True, skip_volatile=True)
        self._update_data_migration(
            total_bytes=required,
            total=paths.human_size(required),
            phase="checking",
            message="正在检查目标磁盘空间...",
            percent=5,
        )
        try:
            target.mkdir(parents=True, exist_ok=True)
            usage = shutil.disk_usage(target)
        except OSError:
            self._fail_data_migration("无法访问目标目录或磁盘。")
            return
        safety = max(512 * 1024 * 1024, int(required * 0.08))
        if usage.free < required + safety:
            self._fail_data_migration(
                f"目标磁盘空间不足：需要至少 {paths.human_size(required + safety)}，"
                f"当前可用 {paths.human_size(usage.free)}。"
            )
            return
        if not self._test_writable(target):
            self._fail_data_migration("目标目录不可写。")
            return

        staging = target.with_name(target.name + ".migrating")
        try:
            if staging.exists():
                shutil.rmtree(staging)
            if target.exists() and any(target.iterdir()):
                # 已有 XB-SVCB 数据目录：先不覆盖，直接切换指针。
                staging = target
                self._update_data_migration(
                    phase="switching",
                    message="正在切换到已有 XB-SVCB 数据目录...",
                    copied_bytes=required,
                    copied=paths.human_size(required),
                    percent=88,
                )
            else:
                self._update_data_migration(
                    phase="copying",
                    message="正在复制数据...",
                    copied_bytes=0,
                    copied=paths.human_size(0),
                    percent=6,
                )
                self._copytree_with_progress(src, staging, required)
                if target.exists():
                    target.rmdir()
                staging.replace(target)
            self._update_data_migration(
                phase="finalizing",
                message="正在写入迁移标记...",
                copied_bytes=required,
                copied=paths.human_size(required),
                percent=94,
            )
            self._write_data_dir_marker(target, migrated_from=str(src))
            (src / config.DATA_MIGRATION_MARKER).write_text(
                json.dumps({"target": str(target)}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if not config.write_data_home(target, pending_delete=src):
                self._fail_data_migration("数据已复制，但写入数据目录指针失败。")
                return
            self._switch_active_data_dir(target)
            active_payload = self._data_storage_payload()
            result = {
                "ok": True,
                "restart_required": True,
                "message": "数据目录已迁移，后续文件将写入新目录。建议重启软件以完成旧目录清理。",
                "old_data_dir": str(src),
                **active_payload,
            }
            self._update_data_migration(
                status="done",
                phase="done",
                message=result["message"],
                copied_bytes=required,
                copied=paths.human_size(required),
                percent=100,
                result=result,
            )
        except OSError as exc:
            try:
                if staging.exists() and staging != target:
                    shutil.rmtree(staging)
            except OSError:
                pass
            self._fail_data_migration(f"迁移失败：{exc}")

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
    ) -> dict[str, Any]:
        return self._editor.open_effect_plugin_editor(
            project_id,
            track_id,
            clip_id,
            effect_id,
            parent_window,
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
    def _empty_migration_status() -> dict[str, Any]:
        return {
            "status": "idle",
            "phase": "idle",
            "message": "未开始迁移。",
            "target_dir": "",
            "copied_bytes": 0,
            "copied": paths.human_size(0),
            "total_bytes": 0,
            "total": paths.human_size(0),
            "percent": 0,
        }

    def _update_data_migration(self, **updates: Any) -> None:
        if "copied_bytes" in updates and "copied" not in updates:
            updates["copied"] = paths.human_size(int(updates["copied_bytes"] or 0))
        if "total_bytes" in updates and "total" not in updates:
            updates["total"] = paths.human_size(int(updates["total_bytes"] or 0))
        if "percent" in updates:
            updates["percent"] = max(0, min(100, int(updates["percent"] or 0)))
        with self._migration_lock:
            self._migration.update(updates)

    def _fail_data_migration(self, message: str) -> None:
        self._update_data_migration(
            status="failed",
            phase="failed",
            message=message,
            error=message,
        )

    def _data_dir_change_blocker(self) -> str | None:
        env = config.data_dir_env_override()
        if env:
            return (
                "当前数据目录由环境变量指定，软件内无法更改。"
                f"请先移除环境变量后再操作：{env}"
            )
        queue = self._works.queue_status()
        if queue.get("running") or queue.get("size"):
            return "当前有推理任务正在运行或排队，请等待任务结束后再更改数据目录。"
        return None

    def _switch_active_data_dir(self, target: Path) -> None:
        """让当前进程的默认数据路径和 JSON 仓储立即切到迁移后的目录。"""
        config.switch_data_dir(target)
        self._retarget_data_stores()

    def _refresh_active_data_dir_from_home(self) -> None:
        """按最新持久化指针修正当前会话的数据目录。"""
        if config.refresh_data_dir_from_home():
            self._retarget_data_stores()

    def _retarget_data_stores(self) -> None:
        """根据 config 当前数据目录重建目录并重定向 JSON 仓储。"""
        for directory in (
            config.DATA_DIR,
            config.MODELS_DIR,
            config.WORKS_DIR,
            config.TEMP_DIR,
            config.MUSIC_DIR,
            config.MODELHUB_DIR,
            config.EDITOR_DIR,
            config.EDITOR_CACHE_DIR,
            config.THEME_MEDIA_DIR,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self._models_repo.set_path(config.MODELS_DB)
        self._works_repo.set_path(config.WORKS_DB)
        self._editor_repo.set_path(config.EDITOR_PROJECTS_DB)
        self._settings.set_path(config.SETTINGS_DB)

    @staticmethod
    def _write_data_dir_marker(
        target: Path,
        *,
        migrated_from: str | None = None,
        selected_from: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "app": config.APP_NAME,
            "version": config.APP_VERSION,
        }
        if migrated_from:
            payload["migrated_from"] = migrated_from
        if selected_from:
            payload["selected_from"] = selected_from
        (target / config.DATA_MARKER_FILE).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _copytree_with_progress(self, src: Path, dst: Path, total_bytes: int) -> None:
        copied = 0
        chunk_size = 8 * 1024 * 1024

        def update_progress() -> None:
            if total_bytes > 0:
                percent = 6 + int(min(copied, total_bytes) * 82 / total_bytes)
            else:
                percent = 88
            self._update_data_migration(
                phase="copying",
                message="正在复制数据...",
                copied_bytes=min(copied, total_bytes) if total_bytes > 0 else copied,
                percent=percent,
            )

        for root_str, dirs, files in os.walk(src):
            root = Path(root_str)
            dirs[:] = [
                name
                for name in dirs
                if not fnmatch.fnmatch(name, "*.tmp")
                and not self._should_skip_migration_path(root / name, src)
            ]
            rel = root.relative_to(src)
            dst_root = dst if str(rel) == "." else dst / rel
            dst_root.mkdir(parents=True, exist_ok=True)
            for dirname in dirs:
                (dst_root / dirname).mkdir(exist_ok=True)
            for filename in files:
                if fnmatch.fnmatch(filename, "*.tmp"):
                    continue
                src_file = root / filename
                if self._should_skip_migration_path(src_file, src):
                    continue
                if not src_file.is_file():
                    continue
                dst_file = dst_root / filename
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                try:
                    file_size = src_file.stat().st_size
                    with src_file.open("rb") as rf, dst_file.open("wb") as wf:
                        while True:
                            chunk = rf.read(chunk_size)
                            if not chunk:
                                break
                            wf.write(chunk)
                            copied += len(chunk)
                            update_progress()
                    shutil.copystat(src_file, dst_file)
                except OSError:
                    if self._is_volatile_migration_path(src_file, src):
                        continue
                    raise
                if file_size == 0:
                    update_progress()
        update_progress()

    @staticmethod
    def _is_volatile_migration_path(path: Path, root: Path) -> bool:
        try:
            top = path.relative_to(root).parts[0]
        except (ValueError, IndexError):
            return False
        return top in {"temp", "webview"}

    @staticmethod
    def _should_skip_migration_path(path: Path, root: Path) -> bool:
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            return False
        return bool(parts) and parts[0] in {"temp", "webview"}

    @staticmethod
    def _dir_size(root: Path, ignore_tmp: bool = False, skip_volatile: bool = False) -> int:
        total = 0
        if not root.exists():
            return 0
        for item in root.rglob("*"):
            if ignore_tmp and any(fnmatch.fnmatch(part, "*.tmp") for part in item.parts):
                continue
            if skip_volatile and Api._should_skip_migration_path(item, root):
                continue
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

    def _resolve_data_migration_target(
        self, raw_target: str, src: Path
    ) -> tuple[Path | None, str | None]:
        target, error = self._resolve_data_dir_target(raw_target, src)
        if error or target is None:
            return target, error
        if target == src:
            return None, "目标目录与当前目录相同。"
        return target, None

    def _resolve_data_dir_target(
        self, raw_target: str, current: Path
    ) -> tuple[Path | None, str | None]:
        """把用户选择的目录规范成真正的数据目录。

        用户可能选择磁盘根目录或一个普通文件夹；这时在其中创建 .xb_svcb
        子目录作为实际数据目录。若选择的是已有 XB-SVCB 数据目录，则直接使用。
        """
        if not str(raw_target or "").strip():
            return None, "请选择目标目录。"
        try:
            selected = Path(raw_target).expanduser().resolve()
        except OSError:
            return None, "目标目录无效。"

        try:
            selected_exists = selected.exists()
            if selected_exists and not selected.is_dir():
                return None, "目标路径不是文件夹。"
            selected_is_data_dir = selected_exists and self._looks_like_data_dir(selected)
            selected_has_entries = selected_exists and any(selected.iterdir())
        except OSError:
            return None, "无法访问目标目录。"

        target = selected
        if selected.parent == selected or (selected_has_entries and not selected_is_data_dir):
            target = selected / config.DATA_DIR_NAME

        try:
            target = target.expanduser().resolve()
            target_exists = target.exists()
            if target_exists and not target.is_dir():
                return None, "目标路径不是文件夹。"
            target_is_data_dir = target_exists and self._looks_like_data_dir(target)
            target_has_entries = target_exists and any(target.iterdir())
        except OSError:
            return None, "无法访问目标目录。"

        if target.parent == target:
            return None, "目标目录不能直接使用磁盘根目录。"
        if target != current and (
            self._is_relative_path(target, current) or self._is_relative_path(current, target)
        ):
            return None, "目标目录不能位于当前数据目录内部，也不能包含当前数据目录。"
        if target_has_entries and not target_is_data_dir:
            return (
                None,
                f"目标数据目录不是空目录：{target}。请选择空目录，或选择已有 XB-SVCB 数据目录。",
            )
        return target, None

    @staticmethod
    def _looks_like_data_dir(path: Path) -> bool:
        if (path / config.DATA_MARKER_FILE).exists():
            return True
        if any((path / name).exists() for name in config.LEGACY_DATA_MARKER_FILES):
            return True
        core_files = ("models.json", "works.json", "settings.json", "editor_projects.json")
        if any((path / name).exists() for name in core_files):
            return True
        core_dirs = ("models", "works", "music", "editor", "modelhub")
        return sum(1 for name in core_dirs if (path / name).exists()) >= 2

    @staticmethod
    def _test_writable(path: Path) -> bool:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".xb_svcb_write_test"
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
            "pointer_file": str(config.active_data_home_file()),
            "pointer_files": [str(path) for path in config.DATA_HOME_FILES],
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
    seedvc = SeedVcEngine()
    ddsp = DdspSvcEngine()
    # 引擎注册表：按模型 framework 路由推理引擎（缺省回退 so-vits-svc）
    engines = EngineRegistry([svc, rvc, seedvc, ddsp])

    models_repo = ListRepository(config.MODELS_DB)
    works_repo = ListRepository(config.WORKS_DB)
    editor_repo = ListRepository(config.EDITOR_PROJECTS_DB)
    settings = SettingsStore(config.SETTINGS_DB)

    # 应用服务
    system_service = SystemService(ffmpeg, uvr, svc, rvc, seedvc, ddsp)
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
        models_repo,
        works_repo,
        editor_repo,
        settings,
    )
