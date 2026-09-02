"""系统服务：汇报集成工具（UVR / ffmpeg / SVC 引擎）的运行状态。"""

from __future__ import annotations

from typing import Any

import config
from infrastructure.ffmpeg_tool import FfmpegTool
from infrastructure.inference_device import (
    inference_device_capabilities,
    runtime_device_label,
)
from infrastructure.model_assets import engine_asset_status
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
        vocal_enhancement: Any | None = None,
        pymss: Any | None = None,
    ) -> None:
        self._ffmpeg = ffmpeg
        self._uvr = uvr
        self._svc = svc
        self._rvc = rvc
        self._seedvc = seedvc
        self._ddsp = ddsp
        self._vocal_enhancement = vocal_enhancement
        self._pymss = pymss

    def status(self) -> dict[str, Any]:
        inference_devices = inference_device_capabilities()
        frameworks = inference_devices.get("frameworks", {})

        def runtime_status(
            framework: str,
            available: bool,
            missing_status: str = "未安装",
        ) -> tuple[bool, str]:
            runtime = frameworks.get(framework, {})
            ready = bool(available and runtime.get("ok"))
            if ready:
                return True, runtime_device_label(runtime, "")
            if available:
                error = str(runtime.get("error") or "运行时探测失败").strip()
                return False, f"环境异常 · {error[:120]}"
            return False, missing_status

        uvr_available = bool(self._uvr.available)
        svc_available = bool(self._svc.available)
        uvr_ok, uvr_status = runtime_status(
            "uvr", uvr_available, self._uvr.status() or "未安装"
        )
        svc_ok, svc_status = runtime_status("so-vits-svc", svc_available)

        def bundled_assets(engine: str) -> dict[str, Any]:
            try:
                return engine_asset_status(config.ROOT_DIR, engine, location="runtime")
            except (OSError, TypeError, ValueError):
                # 模型清单属于增强诊断信息，不能阻塞基础系统状态接口。
                return {"ok": False, "engine": engine, "assets": [], "required": 0, "ready": 0}

        uvr_assets = bundled_assets("uvr")
        tools = [
            {
                "key": "uvr",
                "name": "Ultimate Vocal Remover",
                "desc": "人声 / 伴奏分离引擎，自动提取翻唱所需干声",
                "version": self._uvr.version() or "未安装",
                "status": uvr_status,
                "ok": uvr_ok,
                "required": False,
                "role": "optional",
                "model_status": "已就绪" if uvr_assets["ok"] else "自带模型不完整",
                "model_assets": uvr_assets,
            },
            {
                "key": "ffmpeg",
                "name": "ffmpeg",
                "desc": "音频转码 / 重采样 / 剪辑，统一格式与采样率",
                "version": self._ffmpeg.version() or "未安装",
                "status": "已就绪" if self._ffmpeg.available else "未安装",
                "ok": bool(self._ffmpeg.available),
                "required": True,
                "role": "core",
            },
            {
                "key": "svc",
                "name": "So-VITS-SVC 推理引擎",
                "desc": "加载用户 So-VITS-SVC 模型进行歌声转换推理",
                "version": self._svc.version() or "未安装",
                "status": svc_status,
                "ok": svc_ok,
                "required": False,
                "role": "engine",
            },
        ]
        if self._pymss is not None:
            pymss_status = self._pymss.status()
            pymss_ok = pymss_status == "已就绪"
            if pymss_status == "模型未下载":
                pymss_status = "环境已就绪 · 模型未下载（请在模型管理页下载）"
            tools.append(
                {
                    "key": "pymss",
                    "name": "PyMSS 人声分离",
                    "desc": "可选的 PyMSS 音乐源分离引擎，模型可从 PyMSS 模型站下载",
                    "version": self._pymss.version() or "未安装",
                    "status": pymss_status,
                    "ok": pymss_ok,
                    "required": False,
                    "role": "optional",
                }
            )
        if self._rvc is not None:
            rvc_available = bool(self._rvc.available)
            rvc_ok, rvc_status = runtime_status("rvc", rvc_available)
            tools.append(
                {
                    "key": "rvc",
                    "name": "RVC 推理引擎",
                    "desc": "加载用户 RVC 模型（.pth + 可选 .index）进行歌声转换推理",
                    "version": self._rvc.version() or "未安装",
                    "status": rvc_status,
                    "ok": rvc_ok,
                    "required": False,
                    "role": "engine",
                }
            )
        if self._seedvc is not None:
            seedvc_available = bool(self._seedvc.available)
            seedvc_ok, seedvc_status = runtime_status("seed-vc", seedvc_available)
            seedvc_assets = bundled_assets("seedvc")
            tools.append(
                {
                    "key": "seedvc",
                    "name": "SeedVC 推理引擎",
                    "desc": "加载 SeedVC checkpoint + 目标参考音频进行 zero-shot 歌声转换",
                    "version": self._seedvc.version() or "未安装",
                    "status": seedvc_status,
                    "ok": seedvc_ok,
                    "required": False,
                    "role": "engine",
                    "model_status": "已就绪" if seedvc_assets["ok"] else "自带模型不完整",
                    "model_assets": seedvc_assets,
                }
            )
        if self._ddsp is not None:
            ddsp_available = bool(self._ddsp.available)
            ddsp_ok, ddsp_status = runtime_status("ddsp-svc", ddsp_available)
            ddsp_assets = bundled_assets("ddsp")
            tools.append(
                {
                    "key": "ddsp",
                    "name": "DDSP-SVC 推理引擎",
                    "desc": "加载 DDSP-SVC Rectified Flow 模型进行歌声转换",
                    "version": self._ddsp.version() or "未安装",
                    "status": ddsp_status,
                    "ok": ddsp_ok,
                    "required": False,
                    "role": "engine",
                    "model_status": "已就绪" if ddsp_assets["ok"] else "自带模型不完整",
                    "model_assets": ddsp_assets,
                }
            )
        if self._vocal_enhancement is not None:
            enhancement_ok = bool(self._vocal_enhancement.available)
            tools.append(
                {
                    "key": "vocal-enhancement",
                    "name": "AI Vocal Enhancement",
                    "desc": "分离/输出双阶段修复、高音域自适应、自然修音与细节保护",
                    "version": self._vocal_enhancement.version() or "未安装",
                    "status": "已就绪" if enhancement_ok else "未安装 · 请修复 vocal 环境",
                    "ok": enhancement_ok,
                    "required": False,
                    "role": "optional",
                }
            )
        core_ready = any(
            bool(tool.get("ok")) and tool.get("role") == "core" for tool in tools
        )
        conversion_ready = any(
            bool(tool.get("ok")) and tool.get("role") == "engine" for tool in tools
        )
        return {
            # A usable app needs FFmpeg and at least one real conversion engine.
            # UVR/PyMSS/vocal enhancement remain optional because the pipeline
            # has explicit fallbacks and feature-level guards for them.
            "ready": core_ready and conversion_ready,
            "tools": tools,
            "inference_devices": inference_devices,
        }
