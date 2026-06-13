"""系统服务：汇报集成工具（UVR / ffmpeg / SVC 引擎）的运行状态。"""

from __future__ import annotations

from typing import Any

from infrastructure.ffmpeg_tool import FfmpegTool
from infrastructure.svc_engine import SvcEngine
from infrastructure.uvr_tool import UvrTool


class SystemService:
    def __init__(self, ffmpeg: FfmpegTool, uvr: UvrTool, svc: SvcEngine) -> None:
        self._ffmpeg = ffmpeg
        self._uvr = uvr
        self._svc = svc

    def status(self) -> dict[str, Any]:
        tools = [
            {
                "key": "uvr",
                "name": "Ultimate Vocal Remover",
                "desc": "人声 / 伴奏分离引擎，自动提取翻唱所需干声",
                "version": self._uvr.version() or "未安装",
                "status": "已就绪" if self._uvr.available else "降级模式",
                "ok": self._uvr.available,
            },
            {
                "key": "ffmpeg",
                "name": "ffmpeg",
                "desc": "音频转码 / 重采样 / 剪辑，统一格式与采样率",
                "version": self._ffmpeg.version() or "未安装",
                "status": "已就绪" if self._ffmpeg.available else "降级模式",
                "ok": self._ffmpeg.available,
            },
            {
                "key": "svc",
                "name": "SVC 推理引擎",
                "desc": "加载用户 SVC 模型进行歌声转换推理",
                "version": self._svc.version() or "未安装",
                "status": self._svc.device() if self._svc.available else "降级模式",
                "ok": self._svc.available,
            },
        ]
        return {
            "ready": True,
            "tools": tools,
        }
