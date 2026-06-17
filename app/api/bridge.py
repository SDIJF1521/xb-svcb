"""pywebview JS API 桥接。

``Api`` 的所有公有方法都会被 pywebview 暴露为 ``window.pywebview.api.<method>``，
前端通过 Promise 调用。这里只做参数转换与服务编排，不含具体业务逻辑。

``build_api`` 是组合根（composition root）：装配基础设施、仓储与应用服务。
"""

from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import config
from application import (
    ConversionService,
    ModelService,
    MusicService,
    SystemService,
    WorkService,
)
from infrastructure import paths
from infrastructure.ffmpeg_tool import FfmpegTool
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
    ) -> None:
        self._system = system
        self._models = models
        self._works = works
        self._music = music
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

    # ---- 模型 ----
    def list_models(self) -> list[dict[str, Any]]:
        return self._models.list()

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

    def import_model(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """导入一组模型（主模型 + 主配置 + 扩散模型 + 扩散配置）。"""
        return self._models.import_model(payload or {})

    def set_default_model(self, model_id: str) -> bool:
        return self._models.set_default(model_id)

    def delete_model(self, model_id: str) -> bool:
        return self._models.remove(model_id)

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

    def list_works(self) -> list[dict[str, Any]]:
        return self._works.list()

    def get_work(self, work_id: str) -> dict[str, Any] | None:
        return self._works.get(work_id)

    def create_work(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._works.create(payload or {})

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

    def search_music(self, msg: str, g: int = 13) -> dict[str, Any]:
        return self._music.search(msg, g)

    def get_music_song(self, msg: str, n: int) -> dict[str, Any]:
        return self._music.get_song(msg, n)

    def download_music(self, msg: str, n: int) -> dict[str, Any]:
        return self._music.download(msg, n)

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


def build_api() -> Api:
    """组合根：装配所有依赖并返回 Api 实例。"""
    paths.ensure_dirs()

    # 基础设施
    ffmpeg = FfmpegTool()
    uvr = UvrTool()
    svc = SvcEngine()

    models_repo = ListRepository(config.MODELS_DB)
    works_repo = ListRepository(config.WORKS_DB)
    settings = SettingsStore(config.SETTINGS_DB)

    # 应用服务
    system_service = SystemService(ffmpeg, uvr, svc)
    model_service = ModelService(models_repo, settings)
    conversion_service = ConversionService(works_repo, ffmpeg, uvr, svc)
    work_service = WorkService(works_repo, conversion_service, model_service)
    music_service = MusicService(settings)

    # 启动时回收上次会话残留的"处理中"任务（其后台线程已随进程退出而终止）
    work_service.recover_stale()

    return Api(system_service, model_service, work_service, music_service)
