"""系统服务：汇报集成工具（UVR / ffmpeg / SVC 引擎）的运行状态。"""

from __future__ import annotations

from typing import Any

from infrastructure.ffmpeg_tool import FfmpegTool
from infrastructure.inference_device import (
    inference_device_capabilities,
    runtime_device_label,
)
from infrastructure.svc_engine import SvcEngine
from infrastructure.uvr_tool import UvrTool


class SystemService:
    def __init__(
        self,
        ffmpeg: FfmpegTool,
        uvr: UvrTool,
        svc: SvcEngine,
        rvc: Any | None = None,
        seedvc: Any | None = None,
        ddsp: Any | None = None,
    ) -> None:
        self._ffmpeg = ffmpeg
        self._uvr = uvr
        self._svc = svc
        self._rvc = rvc
        self._seedvc = seedvc
        self._ddsp = ddsp

    def status(self) -> dict[str, Any]:
        inference_devices = inference_device_capabilities()
        frameworks = inference_devices.get("frameworks", {})

        def runtime_status(framework: str, available: bool) -> tuple[bool, str]:
            runtime = frameworks.get(framework, {})
            ready = bool(available and runtime.get("ok"))
            if ready:
                return True, runtime_device_label(runtime, "")
            if available:
                return False, "环境异常 · 请运行环境修复"
            return False, "降级模式"

        uvr_ok, uvr_status = runtime_status("uvr", self._uvr.available)
        svc_ok, svc_status = runtime_status("so-vits-svc", self._svc.available)
        tools = [
            {
                "key": "uvr",
                "name": "Ultimate Vocal Remover",
                "desc": "人声 / 伴奏分离引擎，自动提取翻唱所需干声",
                "version": self._uvr.version() or "未安装",
                "status": uvr_status if self._uvr.available else self._uvr.status(),
                "ok": uvr_ok,
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
                "name": "So-VITS-SVC 推理引擎",
                "desc": "加载用户 So-VITS-SVC 模型进行歌声转换推理",
                "version": self._svc.version() or "未安装",
                "status": svc_status,
                "ok": svc_ok,
            },
        ]
        if self._rvc is not None:
            rvc_ok, rvc_status = runtime_status("rvc", self._rvc.available)
            tools.append(
                {
                    "key": "rvc",
                    "name": "RVC 推理引擎",
                    "desc": "加载用户 RVC 模型（.pth + 可选 .index）进行歌声转换推理",
                    "version": self._rvc.version() or "未安装",
                    "status": rvc_status,
                    "ok": rvc_ok,
                }
            )
        if self._seedvc is not None:
            seedvc_ok, seedvc_status = runtime_status("seed-vc", self._seedvc.available)
            tools.append(
                {
                    "key": "seedvc",
                    "name": "SeedVC 推理引擎",
                    "desc": "加载 SeedVC checkpoint + 目标参考音频进行 zero-shot 歌声转换",
                    "version": self._seedvc.version() or "未安装",
                    "status": seedvc_status,
                    "ok": seedvc_ok,
                }
            )
        if self._ddsp is not None:
            ddsp_ok, ddsp_status = runtime_status("ddsp-svc", self._ddsp.available)
            tools.append(
                {
                    "key": "ddsp",
                    "name": "DDSP-SVC 推理引擎",
                    "desc": "加载 DDSP-SVC Rectified Flow 模型进行歌声转换",
                    "version": self._ddsp.version() or "未安装",
                    "status": ddsp_status,
                    "ok": ddsp_ok,
                }
            )
        return {
            "ready": True,
            "tools": tools,
            "inference_devices": inference_devices,
        }
