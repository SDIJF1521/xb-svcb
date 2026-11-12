"""Buffered real-time cover playback sessions.

The existing inference engines are file based.  This service turns them into a
progressive playback pipeline: separate once, convert bounded timeline blocks,
mix every converted block with the exact matching instrumental block, and make
completed blocks available to the WebAudio scheduler.
"""

from __future__ import annotations

import base64
import queue
import shutil
import threading
import time
import wave
from pathlib import Path
from typing import Any

import config
from domain import InferenceParams, ModelInfo
from domain.identity import new_id

from .adapters import (
    list_system_audio_devices,
    system_audio_reader,
    system_audio_writer,
)
from .ports import (
    EngineRegistryPort,
    FfmpegGateway,
    PymssGateway,
    SeparationGateway,
)
from .conversion_service import (
    ConversionService,
    _HighNoteQuality,
    _with_failed_regions,
)
from .model_service import ModelService


class RealtimeCoverService:
    """Manage progressive RVC / SeedVC song playback sessions."""

    _FRAMEWORKS = {"rvc", "seed-vc"}
    # Fallback used when an imported model does not declare a usable F0 range.
    # Model metadata still wins so the guard matches the selected voice model.
    _HIGH_PITCH_THRESHOLD = 720.0

    def __init__(
        self,
        models: ModelService,
        ffmpeg: FfmpegGateway,
        uvr: SeparationGateway,
        engines: EngineRegistryPort,
        pymss: PymssGateway | None = None,
    ) -> None:
        self._models = models
        self._ffmpeg = ffmpeg
        self._uvr = uvr
        self._engines = engines
        self._pymss = pymss
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        source = Path(str((payload or {}).get("source_path") or ""))
        if not source.is_file():
            raise ValueError("实时翻唱的源歌曲不存在")
        if not self._ffmpeg.available:
            raise RuntimeError("实时翻唱需要 FFmpeg")

        resolved_models = self._resolve_models(payload or {})
        if not resolved_models:
            raise ValueError("请至少选择一个 RVC 或 SeedVC 模型")
        if len(resolved_models) > 1:
            raise ValueError("实时翻唱只支持单个 RVC 或 SeedVC 模型")
        if (payload or {}).get("mode") == "multi" or (payload or {}).get("segments"):
            raise ValueError("实时翻唱不支持多模型混合或分段指派")
        for model in resolved_models:
            engine = self._engines.for_framework(model["framework"])
            if not engine or not getattr(engine, "available", False):
                raise RuntimeError(f"{model['name']} 的 {model['framework']} 实时推理环境未就绪")
            if not Path(str(model.get("main_model_path") or "")).is_file():
                raise ValueError(f"模型文件不存在：{model['name']}")
            if model["framework"] == "seed-vc":
                if not Path(str(model.get("main_config_path") or "")).is_file():
                    raise ValueError(f"SeedVC 配置不存在：{model['name']}")
                reference = str((model.get("params") or {}).get("reference_audio") or "")
                if not Path(reference).is_file():
                    raise ValueError(f"请为 {model['name']} 选择有效的参考音频")

        session_id = new_id("live_")
        session_dir = config.TEMP_DIR / "realtime-covers" / session_id
        duration = float(self._ffmpeg.probe_duration(source) or 0.0)
        if duration <= 0:
            raise ValueError("无法读取歌曲时长")
        params = (
            payload.get("params")
            if isinstance(payload.get("params"), dict)
            else {}
        )
        separator_engine = str(
            payload.get("separator_engine")
            or params.get("preprocess_engine")
            or "uvr"
        ).strip().lower()
        if separator_engine not in {"uvr", "pymss"}:
            separator_engine = "uvr"
        separator_device = str(params.get("device") or "auto").strip()
        if separator_engine == "pymss":
            if self._pymss is None or not self._pymss.available:
                raise RuntimeError(
                    "已选择 PyMSS 人声分离，但 PyMSS 环境未就绪；"
                    "请先安装 PyMSS 并下载模型"
                )
            separator_model = str(
                payload.get("pymss_model")
                or params.get("pymss_model")
                or config.PYMSS_DEFAULT_MODEL
            ).strip()
            if not config.pymss_model_ready(separator_model):
                raise RuntimeError(
                    f"PyMSS 模型未下载: {separator_model}，请先在模型站下载"
                )
            if separator_device.lower() in {"directml", "dml"}:
                separator_device = "auto"
        else:
            separator_model = str(
                payload.get("uvr_model")
                or params.get("uvr_model")
                or config.UVR_MODEL
            ).strip()
        chunk_seconds = self._bounded_float(payload.get("chunk_seconds"), 4.0, 12.0, 8.0)
        buffer_seconds = self._bounded_float(payload.get("buffer_seconds"), 8.0, 60.0, 20.0)
        session: dict[str, Any] = {
            "id": session_id,
            "status": "preparing",
            "input_mode": "file",
            "message": "正在分离人声与伴奏",
            "source_path": str(source),
            "title": str(payload.get("title") or source.stem),
            "model_ids": [item["model_id"] for item in resolved_models],
            "model_names": [item["name"] for item in resolved_models],
            "duration": round(duration, 3),
            "chunk_seconds": chunk_seconds,
            "buffer_seconds": buffer_seconds,
            "separator_engine": separator_engine,
            "separator_model": separator_model,
            "separator_device": separator_device,
            "ready_seconds": 0.0,
            "processed_seconds": 0.0,
            "realtime_factor": None,
            "input_silent": False,
            "ready_chunks": 0,
            "total_chunks": 0,
            "chunks": [],
            "models": resolved_models,
            "segments": [],
            "work_id": None,
            "mode": "single",
            "vocal_gain_db": self._bounded_float(payload.get("vocal_gain_db"), -12.0, 6.0, 0.0),
            "instrumental_gain_db": self._bounded_float(
                payload.get("instrumental_gain_db"), -12.0, 6.0, 0.0
            ),
            "directory": str(session_dir),
            "error": None,
            "output_path": None,
            "stop_event": threading.Event(),
        }
        with self._lock:
            self._sessions[session_id] = session
        thread = threading.Thread(
            target=self._run,
            args=(session_id,),
            name=f"realtime-cover-{session_id}",
            daemon=True,
        )
        session["thread"] = thread
        thread.start()
        return self.status(session_id)

    def list_system_audio_devices(self) -> list[dict[str, Any]]:
        return list_system_audio_devices()

    def start_system(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Start a streaming changer for a live WASAPI/VB-CABLE input.

        Two live profiles are supported:

        * ``separate`` keeps UVR in the loop so QQ Music style mixed audio
          retains its accompaniment.  UVR (especially MDX-Net) pays a fixed
          segment cost per call, so this profile uses ~1.5 s blocks.
        * ``direct`` expects a dry vocal/microphone signal and skips UVR.  This
          is the low-latency path used by live-stream RVC voice changers.

        Both profiles process blocks as they arrive instead of waiting for a
        long playback buffer; stale blocks are dropped when the model cannot
        keep up so latency never grows without bound.
        """
        input_device = str(payload.get("input_device") or "").strip()
        output_device = str(payload.get("output_device") or "").strip()
        if input_device and output_device and input_device == output_device:
            raise ValueError("人声输入和输出设备不能相同")
        if not input_device or not output_device:
            raise ValueError("请选择音频输入和输出设备")
        vocal_mode = str(payload.get("vocal_mode") or "separate").strip().lower()
        if vocal_mode not in {"separate", "direct"}:
            vocal_mode = "separate"
        separate_vocals = vocal_mode == "separate"
        params = (
            payload.get("params")
            if isinstance(payload.get("params"), dict)
            else {}
        )
        separator_engine = str(
            payload.get("separator_engine")
            or params.get("preprocess_engine")
            or "uvr"
        ).strip().lower()
        if separator_engine not in {"uvr", "pymss"}:
            separator_engine = "uvr"
        devices = list_system_audio_devices()
        if not devices:
            raise RuntimeError("未检测到系统音频设备，请安装 soundcard 并配置虚拟音频线")
        input_ids = {
            str(item.get("id") or "")
            for item in devices
            if item.get("kind") == "input"
        }
        system_input_ids = {
            str(item.get("id") or "")
            for item in devices
            if item.get("kind") == "input" and item.get("system_mix")
        }
        output_ids = {
            str(item.get("id") or "")
            for item in devices
            if item.get("kind") == "output"
        }
        if not input_ids:
            raise RuntimeError("未检测到音频输入设备，请连接麦克风或虚拟音频线后重试")
        if separate_vocals and not system_input_ids:
            raise RuntimeError("未检测到系统混合音频输入，请启用 WASAPI 回环、VB-CABLE 或 Voicemeeter")
        if input_device not in input_ids:
            raise ValueError("音频输入设备不存在，请刷新设备列表")
        if separate_vocals and input_device not in system_input_ids:
            raise ValueError(
                "所选设备不是系统混合音频输入，请改选回环/虚拟音频线，"
                "或切换到纯人声直播模式"
            )
        if output_ids and output_device not in output_ids:
            raise ValueError("系统音频输出设备不存在，请刷新设备列表")
        if payload.get("mode") == "multi" or payload.get("segments"):
            raise ValueError("系统音频变声不支持多模型混合或分段指派")
        resolved_models = self._resolve_models(payload or {})
        if len(resolved_models) != 1:
            raise ValueError("实时变声只支持单个 RVC 或 SeedVC 模型")
        model = resolved_models[0]
        self._validate_models(resolved_models)
        separator_model = ""
        separator_device = str(params.get("device") or "auto").strip()
        if separate_vocals:
            if separator_engine == "pymss":
                if self._pymss is None or not self._pymss.available:
                    raise RuntimeError(
                        "已选择 PyMSS 人声分离，但 PyMSS 环境未就绪；"
                        "请先安装 PyMSS 并下载模型"
                    )
                separator_model = str(
                    payload.get("pymss_model")
                    or params.get("pymss_model")
                    or config.PYMSS_DEFAULT_MODEL
                ).strip()
                if not config.pymss_model_ready(separator_model):
                    raise RuntimeError(
                        f"PyMSS 模型未下载: {separator_model}，请先在模型站下载"
                    )
                if separator_device.lower() in {"directml", "dml"}:
                    # PyMSS only supports ROCm for AMD acceleration. Keep the
                    # RVC device on DirectML while letting separation pick a
                    # supported backend instead of failing to start.
                    separator_device = "auto"
            else:
                if not self._uvr.available:
                    raise RuntimeError("系统混合音频变声需要 UVR 人声分离环境与模型")
                separator_model = str(
                    payload.get("uvr_model")
                    or params.get("uvr_model")
                    or config.UVR_MODEL
                ).strip()
        session_id = new_id("system_")
        session_dir = config.TEMP_DIR / "realtime-covers" / session_id
        profile = self._system_timing_profile(
            payload,
            str(model.get("framework") or ""),
            separate_vocals,
        )
        chunk_seconds = float(profile["chunk_seconds"])
        prebuffer_blocks = int(profile["prebuffer_blocks"])
        low_latency = bool(profile["low_latency"])
        sample_rate = int(self._bounded_float(payload.get("sample_rate"), 16000, 48000, 44100))
        session: dict[str, Any] = {
            "id": session_id,
            "input_mode": "system",
            "status": "preparing",
            "message": (
                "正在加载实时人声分离与变声模型"
                if separate_vocals
                else "正在加载实时变声模型（纯人声低延迟）"
            ),
            "title": "系统音频实时变声",
            "model_ids": [model["model_id"]],
            "model_names": [model["name"]],
            "models": [model],
            "mode": "single",
            "vocal_mode": "separate" if separate_vocals else "direct",
            "separate_vocals": separate_vocals,
            "separator_engine": separator_engine if separate_vocals else "none",
            "separator_model": separator_model,
            "separator_device": separator_device,
            "latency_mode": str(profile["latency_mode"]),
            "low_latency": low_latency,
            "duration": 0.0,
            "chunk_seconds": chunk_seconds,
            "prebuffer_blocks": prebuffer_blocks,
            "max_lag_blocks": int(profile["max_lag_blocks"]),
            "sample_rate": sample_rate,
            "crossfade_ms": self._bounded_float(payload.get("crossfade_ms"), 10.0, 120.0, 40.0),
            "buffer_seconds": round(chunk_seconds * prebuffer_blocks, 3),
            "vocal_gain_db": self._bounded_float(payload.get("vocal_gain_db"), -12.0, 6.0, 0.0),
            "instrumental_gain_db": self._bounded_float(payload.get("instrumental_gain_db"), -12.0, 6.0, 0.0),
            "input_device": input_device,
            "output_device": output_device,
            "ready_seconds": 0.0,
            "processed_seconds": 0.0,
            "realtime_factor": None,
            "latency_ms": 0,
            "block_ms": None,
            "infer_ms": None,
            "dropped_seconds": 0.0,
            "input_silent": False,
            "ready_chunks": 0,
            "total_chunks": 0,
            "chunks": [],
            "work_id": None,
            "directory": str(session_dir),
            "error": None,
            "output_path": None,
            "stop_event": threading.Event(),
        }
        with self._lock:
            self._sessions[session_id] = session
        thread = threading.Thread(
            target=self._run_system,
            args=(session_id,),
            name=f"realtime-system-{session_id}",
            daemon=True,
        )
        session["thread"] = thread
        thread.start()
        return self.status(session_id)

    def status(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return {"id": session_id, "status": "missing", "error": "实时会话不存在"}
            return self._public(session)

    def attach_work_id(self, session_id: str, work_id: str) -> bool:
        """Associate a completed realtime session with a persisted work record."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            session["work_id"] = work_id
            return True

    def chunk(self, session_id: str, index: int) -> dict[str, Any]:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return {"ok": False, "error": "实时会话不存在"}
            chunks = session.get("chunks") or []
            if index < 0 or index >= len(chunks):
                return {"ok": False, "pending": True}
            item = dict(chunks[index])
        path = Path(str(item.pop("path", "")))
        if not path.is_file():
            return {"ok": False, "pending": True}
        try:
            audio = base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, **item, "audio": f"data:audio/wav;base64,{audio}"}

    def stop(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return {"id": session_id, "status": "missing"}
            session["stop_event"].set()
            if session["status"] not in {"done", "failed"}:
                session["status"] = "stopped"
                session["message"] = "实时播放已停止"
            return self._public(session)

    def shutdown(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            session["stop_event"].set()
        for session in sessions:
            thread = session.get("thread")
            if isinstance(thread, threading.Thread) and thread is not threading.current_thread():
                # UVR/RVC worker shutdown can take a few seconds to release
                # audio files on Windows; wait long enough before temp cleanup.
                thread.join(timeout=15.0)

    def _run(self, session_id: str) -> None:
        session = self._sessions[session_id]
        directory = Path(session["directory"])
        worker_sessions: dict[str, Any] = {}
        try:
            directory.mkdir(parents=True, exist_ok=True)
            source = Path(session["source_path"])
            if session.get("separator_engine") == "pymss":
                if self._pymss is None:
                    raise RuntimeError("PyMSS 未接入实时变声服务")
                separation = self._pymss.separate(
                    source,
                    directory / "stems",
                    session.get("separator_model") or config.PYMSS_DEFAULT_MODEL,
                    session.get("separator_device") or "auto",
                    purpose=config.PYMSS_PURPOSE_VOCAL,
                )
            else:
                separation = self._uvr.separate(
                    source,
                    directory / "stems",
                    session.get("separator_model") or config.UVR_MODEL,
                    session.get("separator_device") or "auto",
                )
            if not separation.instrumental or not Path(separation.instrumental).is_file():
                raise RuntimeError("实时翻唱需要可用的 PyMSS/UVR 人声/伴奏分离环境")
            vocals = Path(separation.vocals)
            instrumental = Path(separation.instrumental) if separation.instrumental else None
            spans = self._build_spans(session)
            self._update(
                session,
                status="buffering",
                message="正在转换首批实时音频",
                total_chunks=len(spans),
            )
            model = session["models"][0]
            model_id = model["model_id"]
            engine = self._engines.for_framework(model["framework"])
            model_params = InferenceParams.from_dict(model.get("params") or {})
            opener = getattr(engine, "open_realtime_session", None)
            if callable(opener):
                self._update(
                    session,
                    message=f"正在加载常驻模型：{model.get('name', model_id)}",
                )
                worker_sessions[model_id] = opener(
                    model,
                    InferenceParams.from_dict(model.get("params") or {}),
                    directory / "realtime.log",
                )
            self._update(session, message="常驻模型已加载，正在生成播放缓冲")
            conversion_started = time.monotonic()

            for index, span in enumerate(spans):
                if session["stop_event"].is_set():
                    return
                start, end = span["start"], span["end"]
                length = end - start
                raw_vocal = directory / f"vocal_{index:05d}.wav"
                if not self._ffmpeg.slice(vocals, start, end, raw_vocal):
                    raise RuntimeError(f"无法截取第 {index + 1} 个实时人声块")

                raw_render = directory / f"render_{index:05d}_{model_id}.wav"
                persistent = worker_sessions.get(model_id)
                def infer_once(vocal: Path, destination: Path) -> None:
                    if persistent is not None:
                        persistent.infer(vocal, destination)
                    else:
                        engine.infer(
                            model=model,
                            vocals=vocal,
                            out_path=destination,
                            params=model_params,
                            duration=length,
                            log_file=directory / "realtime.log",
                        )

                raw_render, recovery_history = self._infer_with_dropout_recovery(
                    source=raw_vocal,
                    output=raw_render,
                    params=model_params,
                    model=model,
                    infer=infer_once,
                    log_file=directory / "realtime.log",
                )
                unresolved_dropout = bool(
                    recovery_history
                    and recovery_history[-1].get("issue")
                )
                if (
                    model_params.auto_high_pitch_guard
                    and unresolved_dropout
                    and self._is_nearly_silent(raw_render, raw_vocal)
                ):
                    self._append_realtime_log(
                        directory / "realtime.log",
                        "PITCH_GUARD_FALLBACK\t重试后整块仍接近静音，回退原始人声\n",
                    )
                    raw_render = raw_vocal
                fixed = directory / f"render_{index:05d}_{model_id}_fixed.wav"
                rendered = fixed if self._ffmpeg.pad_or_trim(raw_render, fixed, length) else raw_render
                vocal_mix = directory / f"converted_{index:05d}.wav"
                if not rendered.is_file() or not self._ffmpeg.convert(rendered, vocal_mix):
                    raise RuntimeError("无法规整实时人声块")

                faded_vocal = directory / f"converted_{index:05d}_faded.wav"
                edge_fade = getattr(self._ffmpeg, "edge_fade", None)
                if callable(edge_fade) and edge_fade(vocal_mix, faded_vocal, length):
                    vocal_mix = faded_vocal

                output = directory / f"chunk_{index:05d}.wav"
                if instrumental and instrumental.is_file():
                    music = directory / f"music_{index:05d}.wav"
                    if not self._ffmpeg.slice(instrumental, start, end, music):
                        raise RuntimeError("无法截取实时伴奏块")
                    if not self._ffmpeg.mix(
                        vocal_mix,
                        music,
                        output,
                        vocal_gain_db=session["vocal_gain_db"],
                        instrumental_gain_db=session["instrumental_gain_db"],
                    ):
                        raise RuntimeError("无法混合实时人声与伴奏")
                elif not self._ffmpeg.convert(vocal_mix, output):
                    raise RuntimeError("无法生成实时输出块")

                fixed_output = directory / f"chunk_{index:05d}_fixed.wav"
                if self._ffmpeg.pad_or_trim(output, fixed_output, length):
                    output = fixed_output
                chunk = {
                    "index": index,
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "duration": round(length, 3),
                    "model_ids": [model_id],
                    "path": str(output),
                }
                with self._lock:
                    session["chunks"].append(chunk)
                    session["ready_chunks"] = len(session["chunks"])
                    session["processed_seconds"] = round(end, 3)
                    session["ready_seconds"] = round(
                        sum(float(item["duration"]) for item in session["chunks"]), 3
                    )
                    elapsed = max(0.001, time.monotonic() - conversion_started)
                    session["realtime_factor"] = round(
                        elapsed / max(0.001, session["ready_seconds"]), 3
                    )
                    if (
                        session["status"] == "buffering"
                        and session["ready_seconds"] >= session["buffer_seconds"]
                        and session["realtime_factor"] <= 0.9
                    ):
                        session["status"] = "ready"
                        session["message"] = "缓冲完成，可以连续播放"
                    elif (
                        session["status"] == "buffering"
                        and session["ready_seconds"] >= session["buffer_seconds"]
                    ):
                        session["message"] = "转换速度低于播放速度，正在继续缓冲以避免中途断音"

            output = directory / "realtime-cover.wav"
            chunk_paths = [Path(item["path"]) for item in session["chunks"]]
            if chunk_paths and self._ffmpeg.concat(chunk_paths, output):
                session["output_path"] = str(output)
            self._update(session, status="done", message="整首实时音频已转换完成")
        except Exception as exc:  # noqa: BLE001 - report background failures to the UI
            if session["stop_event"].is_set():
                return
            self._update(session, status="failed", message="实时转换失败", error=str(exc))
        finally:
            for persistent in worker_sessions.values():
                try:
                    persistent.close()
                except Exception:  # noqa: BLE001 - session cleanup must not mask conversion result
                    pass

    def _run_system(self, session_id: str) -> None:
        session = self._sessions[session_id]
        directory = Path(session["directory"])
        worker: Any | None = None
        separator: Any | None = None
        try:
            import numpy as np

            directory.mkdir(parents=True, exist_ok=True)
            model = session["models"][0]
            model_params = InferenceParams.from_dict(model.get("params") or {})
            separate_vocals = bool(session.get("separate_vocals", True))
            if separate_vocals:
                if session.get("separator_engine") == "pymss":
                    if self._pymss is None:
                        raise RuntimeError("PyMSS 未接入实时变声服务")
                    separator_opener = getattr(
                        self._pymss, "open_realtime_session", None
                    )
                    if not callable(separator_opener):
                        raise RuntimeError("当前 PyMSS 环境不支持常驻实时分离")
                    separator = separator_opener(
                        session.get("separator_model") or config.PYMSS_DEFAULT_MODEL,
                        session.get("separator_device") or "auto",
                        directory / "pymss",
                        directory / "realtime-system.log",
                        purpose=config.PYMSS_PURPOSE_VOCAL,
                    )
                else:
                    separator_opener = getattr(self._uvr, "open_realtime_session", None)
                    if not callable(separator_opener):
                        raise RuntimeError("当前 UVR 分离环境不支持常驻实时处理")
                    separator = separator_opener(
                        session.get("separator_model") or config.UVR_MODEL,
                        session.get("separator_device") or "auto",
                        directory / "uvr",
                        directory / "realtime-system.log",
                    )
            engine = self._engines.for_framework(model["framework"])
            opener = getattr(engine, "open_realtime_session", None)
            if not callable(opener):
                raise RuntimeError("当前模型不支持常驻实时推理")
            worker = opener(
                model,
                model_params,
                directory / "realtime-system.log",
                low_latency=bool(session.get("low_latency", True)),
            )
            frames = max(1, round(session["sample_rate"] * session["chunk_seconds"]))
            if separate_vocals:
                # UVR and RVC each pay a fixed per-call cost. In the separated
                # profile a slightly longer block amortizes UVR's segment
                # padding while still staying far below the old 8 s + 2-block
                # playback buffer.
                frames = max(frames, round(session["sample_rate"] * 0.5))
            crossfade_frames = min(
                max(1, frames // 4),
                max(1, round(session["sample_rate"] * session["crossfade_ms"] / 1000.0)),
            )
            prebuffer_blocks = max(1, int(session.get("prebuffer_blocks") or 1))
            max_lag_blocks = max(1, int(session.get("max_lag_blocks") or 2))
            started = time.monotonic()
            self._update(
                session,
                status="ready",
                message=(
                    "混合音频分离与变声已就绪，开始低延迟流式输出"
                    if separate_vocals
                    else "纯人声变声已就绪，开始直播低延迟输出"
                ),
            )
            with (
                system_audio_reader(session["input_device"], session["sample_rate"], 2) as reader,
                # Playback runs on its own thread and starts as soon as the
                # first converted block is available. A prebuffer of one block
                # adds no extra delay; higher values trade latency for jitter
                # tolerance.
                system_audio_writer(
                    session["output_device"],
                    session["sample_rate"],
                    2,
                    prebuffer_blocks=prebuffer_blocks,
                    crossfade_frames=crossfade_frames,
                ) as writer,
            ):
                captured_queue: queue.Queue[Any] = queue.Queue(maxsize=max_lag_blocks)
                # Only one prepared block may wait for RVC. Any additional
                # backlog is stale for a live stream and is dropped at capture.
                separated_queue: queue.Queue[Any] = queue.Queue(maxsize=1)
                pipeline_stop = threading.Event()
                capture_done = threading.Event()
                separation_done = threading.Event()
                errors: list[Exception] = []
                log_file = directory / "realtime-system.log"

                def capture_loop() -> None:
                    index = 0
                    try:
                        while not session["stop_event"].is_set() and not pipeline_stop.is_set():
                            block = np.asarray(reader.read(frames), dtype=np.float32)
                            item = (index, block, time.monotonic(), False)
                            while True:
                                try:
                                    captured_queue.put_nowait(item)
                                    break
                                except queue.Full:
                                    # Processing is slower than capture.
                                    # Discard the whole stale backlog and feed
                                    # the freshest block, otherwise the next
                                    # queued block would still crossfade
                                    # against a non-adjacent tail.
                                    dropped_items: list[Any] = []
                                    while True:
                                        try:
                                            dropped_items.append(captured_queue.get_nowait())
                                        except queue.Empty:
                                            break
                                    if not dropped_items:
                                        continue
                                    item = (index, block, time.monotonic(), True)
                                    dropped_frames = sum(
                                        int(np.asarray(dropped[1]).shape[0])
                                        for dropped in dropped_items
                                    )
                                    with self._lock:
                                        session["dropped_seconds"] = round(
                                            float(session.get("dropped_seconds") or 0.0)
                                            + dropped_frames / max(1, int(session["sample_rate"])),
                                            3,
                                        )
                                    self._append_realtime_log(
                                        log_file,
                                        "LATENCY_DROP\t"
                                        f"blocks={len(dropped_items)}\t"
                                        f"frames={dropped_frames}\n",
                                    )
                            index += 1
                    except Exception as exc:  # noqa: BLE001
                        errors.append(exc)
                        pipeline_stop.set()
                    finally:
                        capture_done.set()

                def separation_loop() -> None:
                    previous_tail = None
                    try:
                        while not pipeline_stop.is_set():
                            try:
                                item = captured_queue.get(timeout=0.2)
                            except queue.Empty:
                                if capture_done.is_set():
                                    break
                                continue
                            index, captured, captured_at, discontinuity = item
                            current = np.asarray(captured, dtype=np.float32)
                            overlap_frames = 0
                            processing = current
                            if discontinuity:
                                previous_tail = None
                                self._append_realtime_log(
                                    log_file,
                                    f"LATENCY_RESET\tblock={index}\n",
                                )
                            if previous_tail is not None and previous_tail.shape[0]:
                                overlap_frames = int(previous_tail.shape[0])
                                processing = np.concatenate((previous_tail, current), axis=0)
                            previous_tail = current[-crossfade_frames:].copy()
                            prepared = self._prepare_system_block(
                                directory,
                                separator,
                                processing,
                                int(processing.shape[0]),
                                index,
                                session["sample_rate"],
                                output_frames=frames,
                                overlap_frames=overlap_frames,
                                discontinuity=discontinuity,
                            )
                            prepared["captured_at"] = captured_at
                            while not pipeline_stop.is_set():
                                try:
                                    separated_queue.put(prepared, timeout=0.2)
                                    break
                                except queue.Full:
                                    continue
                    except Exception as exc:  # noqa: BLE001
                        errors.append(exc)
                        pipeline_stop.set()
                    finally:
                        separation_done.set()

                def conversion_loop() -> None:
                    try:
                        while not pipeline_stop.is_set():
                            try:
                                prepared = separated_queue.get(timeout=0.2)
                            except queue.Empty:
                                if separation_done.is_set() and separated_queue.empty():
                                    break
                                continue
                            self._render_system_block(
                                session, worker, writer, prepared, started, np
                            )
                    except Exception as exc:  # noqa: BLE001
                        errors.append(exc)
                        pipeline_stop.set()

                threads = [
                    threading.Thread(target=capture_loop, name=f"realtime-system-capture-{session_id}", daemon=True),
                    threading.Thread(target=separation_loop, name=f"realtime-system-separate-{session_id}", daemon=True),
                    threading.Thread(target=conversion_loop, name=f"realtime-system-convert-{session_id}", daemon=True),
                ]
                for thread in threads:
                    thread.start()
                try:
                    while any(thread.is_alive() for thread in threads):
                        if session["stop_event"].is_set():
                            pipeline_stop.set()
                        if errors:
                            pipeline_stop.set()
                        time.sleep(0.05)
                finally:
                    pipeline_stop.set()
                    for thread in threads:
                        thread.join(timeout=2.0)
                if errors:
                    raise RuntimeError(str(errors[0])) from errors[0]
            self._update(session, status="stopped", message="系统混合音频变声已停止")
        except Exception as exc:  # noqa: BLE001
            # Stopping is an expected cancellation path. Do not overwrite the
            # stopped state with a cleanup/queue exception from a worker that
            # was already asked to exit.
            if session["stop_event"].is_set():
                self._update(
                    session,
                    status="stopped",
                    message="系统混合音频变声已停止",
                    error=None,
                )
            else:
                self._update(session, status="failed", message="系统混合音频变声失败", error=str(exc))
        finally:
            if worker is not None:
                try:
                    worker.close()
                except Exception:  # noqa: BLE001
                    pass
            if separator is not None:
                try:
                    separator.close()
                except Exception:  # noqa: BLE001
                    pass

    def _prepare_system_block(
        self,
        directory: Path,
        separator: Any | None,
        captured: Any,
        frames: int,
        index: int,
        sample_rate: int,
        *,
        output_frames: int | None = None,
        overlap_frames: int = 0,
        discontinuity: bool = False,
    ) -> dict[str, Any]:
        import numpy as np

        captured = np.asarray(captured, dtype=np.float32)
        if captured.size == 0:
            raise RuntimeError("系统音频输入返回空音频块")
        captured = self._fit_audio(captured, frames)
        overlap_frames = min(max(0, int(overlap_frames)), frames)
        output_frames = max(0, int(output_frames if output_frames is not None else frames - overlap_frames))
        current = captured[overlap_frames : overlap_frames + output_frames]
        length = output_frames / sample_rate
        # A stopped player still leaves the WASAPI loopback recorder alive and
        # returns zero-filled blocks. UVR cannot produce a vocal stem for a
        # silent block, so bypass the model pipeline and keep the stream clock
        # running with the original (silent) block.
        peak = float(np.max(np.abs(current))) if current.size else 0.0
        rms = float(np.sqrt(np.mean(np.square(current)))) if current.size else 0.0
        if peak < 1e-4 or rms < 2e-5:
            return {
                "index": index,
                "captured": captured,
                "frames": frames,
                "overlap_frames": overlap_frames,
                "length": length,
                "silent": True,
                "discontinuity": discontinuity,
            }
        raw = directory / f"system_input_{index:06d}.wav"
        self._write_pcm16(raw, captured, sample_rate)
        if separator is None:
            # Direct vocal profile: the captured signal is already the voice
            # to convert. Keeping UVR out of the loop removes its fixed
            # segment cost and is what makes sub-second live latency possible.
            return {
                "index": index,
                "captured": captured,
                "frames": frames,
                "overlap_frames": overlap_frames,
                "length": length,
                "raw": raw,
                "separated": raw,
                "rendered": directory / f"system_render_{index:06d}.wav",
                "direct": True,
                "discontinuity": discontinuity,
            }
        separated = directory / f"system_vocal_{index:06d}.wav"
        accompaniment = directory / f"system_music_{index:06d}.wav"
        separator.infer(
            raw,
            separated,
            timeout=max(30.0, length * 30.0),
            instrumental=str(accompaniment),
        )
        return {
            "index": index,
            "captured": captured,
            "frames": frames,
            "overlap_frames": overlap_frames,
            "length": length,
            "raw": raw,
            "separated": separated,
            "accompaniment": accompaniment,
            "rendered": directory / f"system_render_{index:06d}.wav",
            "direct": False,
            "discontinuity": discontinuity,
        }

    def _infer_with_dropout_recovery(
        self,
        *,
        source: Path,
        output: Path,
        params: InferenceParams,
        model: dict[str, Any],
        infer: Any,
        log_file: Path,
    ) -> tuple[Path, list[dict[str, Any]]]:
        """Retry a realtime block when the model mutes a voiced high-note span."""
        threshold = self._model_high_pitch_threshold(params, model)
        params.high_pitch_threshold = threshold
        guard_rounds = ConversionService._high_pitch_guard_rounds(params, realtime=True)
        attempts = 1 + guard_rounds if params.auto_high_pitch_guard else 1
        history: list[dict[str, Any]] = []
        rendered = output
        guard_regions: list[tuple[float, float]] | None = None
        merge_regions: list[tuple[float, float]] | None = None
        initial_failure_regions: list[tuple[float, float]] | None = None
        unresolved_failure_regions: list[tuple[float, float]] = []
        guard_semitones = ConversionService._HIGH_PITCH_GUARD_SEMITONES
        best_render = output
        best_bad_frames = float("inf")
        for attempt in range(attempts):
            raw_target = output if attempt == 0 else output.with_name(
                f"{output.stem}_dropout_retry{attempt}.wav"
            )
            if attempt == 0:
                guarded, guard_shift = source, 0
            else:
                guarded, guard_shift = self._prepare_pitch_guard(
                    source,
                    output.with_name(f"{output.stem}_guarded_retry{attempt}.wav"),
                    params,
                    self._duration(source),
                    model=model,
                    only_regions=guard_regions,
                    semitones=guard_semitones,
                )
            infer(guarded, raw_target)
            rendered = raw_target
            if guard_shift:
                restored = output.with_name(f"{output.stem}_restored_retry{attempt}.wav")
                if self._pitch_shift(
                    raw_target,
                    restored,
                    -guard_shift,
                    mask_source=source,
                    # The dry vocal can be much louder than a breathy model
                    # retry. Match the restored region to this model render so
                    # PSOLA does not amplify its air band into a whistle.
                    loudness_source=raw_target,
                    high_threshold=threshold,
                    only_regions=guard_regions,
                ):
                    rendered = restored
                    if merge_regions:
                        merged_target = output.with_name(
                            f"{output.stem}_guarded_merged_retry{attempt}.wav"
                        )
                        rendered = ConversionService._merge_guarded_regions(
                            output,
                            rendered,
                            merged_target,
                            restored.with_suffix(".regions.json"),
                            only_regions=merge_regions,
                        )
                else:
                    self._append_realtime_log(
                        log_file,
                        "PITCH_GUARD_RESTORE_FAILED\t保共振峰升调失败，保留首次推理结果\n",
                    )
                    rendered = output
            if (
                attempt > 0
                and rendered != output
                and ConversionService._guard_candidate_has_new_hf_peak(
                    source,
                    output,
                    rendered,
                    merge_regions,
                )
            ):
                self._append_realtime_log(
                    log_file,
                    "PITCH_GUARD_REJECTED\t保护结果出现新的窄带高频峰，保留首次推理结果\n",
                )
                rendered = output
            issue = (
                ConversionService._detect_model_dropout(
                    source,
                    rendered,
                    threshold,
                    int(getattr(params, "pitch", 0) or 0),
                )
                if params.auto_high_pitch_guard and guard_rounds > 0
                else None
            )
            entry: dict[str, Any] = {
                "attempt": attempt + 1,
                "threshold": round(threshold, 1),
                "issue": issue,
            }
            history.append(entry)
            if attempt == 0:
                if issue is None:
                    return rendered, history
                initial_failure_regions = ConversionService._dropout_core_regions(issue)
                unresolved_failure_regions = list(initial_failure_regions or [])
                merge_regions = initial_failure_regions
                guard_regions = ConversionService._confirmed_guard_regions(issue)
                best_bad_frames = float(issue.get("bad_frames") or float("inf"))
            else:
                quality: _HighNoteQuality = (
                    ConversionService._guard_candidate_high_note_quality(
                        source,
                        output,
                        rendered,
                        initial_failure_regions,
                        restored.with_suffix(".regions.json")
                        if guard_shift
                        else None,
                    )
                    if rendered != output
                    else _HighNoteQuality(available=False)
                )
                if quality.get("available"):
                    entry["quality"] = quality
                    accepted_keys = {
                        (round(float(start), 6), round(float(end), 6))
                        for start, end in (quality.get("accepted_regions") or [])
                    }
                    newly_accepted = [
                        (start, end)
                        for start, end in unresolved_failure_regions
                        if (round(float(start), 6), round(float(end), 6))
                        in accepted_keys
                    ]
                    if newly_accepted:
                        best_render = ConversionService._merge_guarded_regions(
                            best_render,
                            rendered,
                            output.with_name(
                                f"{output.stem}_accepted_retry{attempt}.wav"
                            ),
                            restored.with_suffix(".regions.json"),
                            only_regions=newly_accepted,
                        )
                        unresolved_failure_regions = [
                            (start, end)
                            for start, end in unresolved_failure_regions
                            if (round(float(start), 6), round(float(end), 6))
                            not in accepted_keys
                        ]
                    issue = ConversionService._quality_failure_issue(
                        _with_failed_regions(quality, unresolved_failure_regions),
                        issue,
                    )
                    entry["issue"] = issue
                    if issue is None:
                        return best_render, history
                    best_bad_frames = float(
                        issue.get("bad_frames") or float("inf")
                    )
                    guard_regions = ConversionService._confirmed_guard_regions(issue)
                    merge_regions = initial_failure_regions
                    next_threshold = ConversionService._next_dropout_threshold(
                        threshold,
                        issue,
                    )
                    entry["next_threshold"] = next_threshold
                    if (
                        next_threshold >= threshold - 10.0
                        or attempt >= attempts - 1
                    ):
                        self._append_realtime_log(
                            log_file,
                            "PITCH_DROPOUT_UNRESOLVED\t"
                            f"regions={len(unresolved_failure_regions)}\t"
                            "quality_gate=failed\n",
                        )
                        return best_render, history
                    guard_semitones = max(
                        guard_semitones,
                        ConversionService._guard_semitones_for_retry(
                            next_threshold,
                            issue,
                            source,
                            guard_regions,
                        ),
                    )
                    threshold = next_threshold
                    params.high_pitch_threshold = threshold
                    continue
                if issue is None:
                    return rendered, history
                candidate_bad_frames = float(
                    issue.get("bad_frames") or float("inf")
                )
                candidate_keeps_original_failure = (
                    ConversionService._dropout_regions_overlap(
                        issue,
                        initial_failure_regions,
                    )
                )
                candidate_improved = (
                    candidate_bad_frames < best_bad_frames
                    or (
                        best_render == output
                        and candidate_bad_frames == best_bad_frames
                        and not candidate_keeps_original_failure
                    )
                )
                if (
                    rendered != output
                    and candidate_improved
                    and not candidate_keeps_original_failure
                ):
                    best_render = rendered
                    best_bad_frames = candidate_bad_frames
                elif candidate_improved and candidate_keeps_original_failure:
                    self._append_realtime_log(
                        log_file,
                        "PITCH_GUARD_REJECTED\t保护结果仍包含首次失配区，保留更安全的结果\n",
                    )
                if guard_regions and issue.get("bad_regions"):
                    overlaps_scope = any(
                        float(item.get("end", 0.0)) > start
                        and float(item.get("start", 0.0)) < end
                        for item in (issue.get("bad_regions") or [])
                        if isinstance(item, dict)
                        for start, end in guard_regions
                    )
                    if not overlaps_scope:
                        return best_render, history
                    guard_regions = ConversionService._confirmed_guard_regions(
                        issue,
                        guard_regions,
                    )
            next_threshold = ConversionService._next_dropout_threshold(threshold, issue)
            entry["next_threshold"] = next_threshold
            if next_threshold >= threshold - 10.0 or attempt >= attempts - 1:
                self._append_realtime_log(
                    log_file,
                    "PITCH_DROPOUT_UNRESOLVED\t"
                    f"{issue['start']:.2f}-{issue['end']:.2f}s\t"
                    f"source_f0={issue['source_f0_hz']:.0f}\t"
                    f"threshold={threshold:.0f}\n",
                )
                return best_render, history
            self._append_realtime_log(
                log_file,
                "PITCH_DROPOUT_RETRY\t"
                f"{issue['start']:.2f}-{issue['end']:.2f}s\t"
                f"source_f0={issue['source_f0_hz']:.0f}\t"
                f"threshold={threshold:.0f}->{next_threshold:.0f}\n",
            )
            guard_semitones = max(
                guard_semitones,
                ConversionService._guard_semitones_for_retry(
                    next_threshold,
                    issue,
                    source,
                    guard_regions,
                ),
            )
            threshold = next_threshold
            params.high_pitch_threshold = threshold
        return best_render, history

    @staticmethod
    def _duration(source: Path) -> float:
        try:
            with wave.open(str(source), "rb") as handle:
                rate = int(handle.getframerate() or 0)
                return handle.getnframes() / float(rate) if rate else 0.0
        except (OSError, EOFError, ValueError, wave.Error):
            return 0.0

    def _render_system_block(
        self,
        session: dict[str, Any],
        worker: Any,
        writer: Any,
        prepared: dict[str, Any],
        _started: float,
        np: Any,
    ) -> None:
        block_started = time.monotonic()
        frame_count = int(prepared["frames"])
        overlap_frames = int(prepared.get("overlap_frames") or 0)
        discontinuity = bool(prepared.get("discontinuity"))
        direct = bool(prepared.get("direct"))
        chunk_ms = max(1.0, float(session.get("chunk_seconds") or 1.0) * 1000.0)
        captured_at = float(prepared.get("captured_at") or block_started)
        log_file = Path(session["directory"]) / "realtime-system.log"
        if prepared.get("silent"):
            # Keep the output clock continuous while the source player is
            # paused/stopped. No separator or voice-conversion inference is
            # needed for a zero block, and no UVR output error is possible.
            silent = np.zeros_like(self._fit_audio(prepared["captured"], frame_count))
            writer.write(
                silent,
                overlap_frames=overlap_frames,
                discontinuity=discontinuity,
            )
            self._record_system_block(
                session,
                prepared,
                block_started,
                captured_at,
                chunk_ms,
                infer_ms=0.0,
            )
            with self._lock:
                session["input_silent"] = True
                session["message"] = "未检测到系统音频，等待播放器继续播放"
            return
        separated = Path(prepared["separated"])
        accompaniment_stem = (
            Path(prepared["accompaniment"]) if prepared.get("accompaniment") else None
        )
        rendered = Path(prepared["rendered"])
        model_params = InferenceParams.from_dict(
            (session["models"][0].get("params") or {})
        )
        if (
            session.get("low_latency", True)
            and (
                session.get("vocal_mode") == "direct"
                or float(session.get("chunk_seconds") or 1.5) <= 0.75
            )
        ):
            # Per-block high-note recovery re-reads the block several times
            # and can multiply inference time. Sub-second live blocks keep the
            # first render; mixed-audio blocks still honor the user's guard
            # setting.
            model_params.auto_high_pitch_guard = False
        def infer_once(vocal: Path, destination: Path) -> None:
            worker.infer(
                vocal,
                destination,
                timeout=max(15.0, float(prepared["length"]) * 20.0),
            )

        infer_started = time.monotonic()
        rendered, recovery_history = self._infer_with_dropout_recovery(
            source=separated,
            output=rendered,
            params=model_params,
            model=session["models"][0],
            infer=infer_once,
            log_file=log_file,
        )
        infer_ms = (time.monotonic() - infer_started) * 1000.0
        unresolved_dropout = bool(
            recovery_history
            and recovery_history[-1].get("issue")
        )
        if (
            (model_params.auto_high_pitch_guard and unresolved_dropout)
            or not model_params.auto_high_pitch_guard
        ) and self._is_nearly_silent(rendered, separated):
            self._append_realtime_log(
                log_file,
                "MODEL_SILENCE_FALLBACK\t整块接近静音，回退原始人声\n",
            )
            rendered = separated
        output_audio = self._fit_audio(
            self._read_pcm16(rendered, session["sample_rate"], frame_count),
            frame_count,
        )
        if direct:
            # Dry-vocal profile: the converted voice is the whole output.
            accompaniment = np.zeros_like(output_audio)
        else:
            extracted = self._fit_audio(
                self._read_pcm16(separated, session["sample_rate"], frame_count),
                frame_count,
            )
            if accompaniment_stem is not None and accompaniment_stem.is_file():
                accompaniment = self._fit_audio(
                    self._read_pcm16(accompaniment_stem, session["sample_rate"], frame_count),
                    frame_count,
                )
            else:
                accompaniment = self._fit_audio(prepared["captured"], frame_count) - extracted
        output_audio *= 10.0 ** (float(session["vocal_gain_db"]) / 20.0)
        accompaniment *= 10.0 ** (float(session["instrumental_gain_db"]) / 20.0)
        mixed = output_audio + accompaniment
        peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
        if peak > 0.98:
            mixed *= 0.98 / peak
        writer.write(
            np.clip(mixed, -1.0, 1.0),
            overlap_frames=overlap_frames,
            discontinuity=discontinuity,
        )
        self._record_system_block(
            session,
            prepared,
            block_started,
            captured_at,
            chunk_ms,
            infer_ms=infer_ms,
        )
        with self._lock:
            session["input_silent"] = False
        index = int(prepared.get("index") or 0)
        load = float(session.get("realtime_factor") or 0.0)
        if index % 5 == 0 or load > 1.2:
            self._append_realtime_log(
                log_file,
                "REALTIME_BLOCK\t"
                f"index={index}\t"
                f"chunk_ms={chunk_ms:.0f}\t"
                f"infer_ms={infer_ms:.0f}\t"
                f"block_ms={float(session.get('block_ms') or 0.0):.0f}\t"
                f"latency_ms={int(session.get('latency_ms') or 0)}\t"
                f"dropped={float(session.get('dropped_seconds') or 0.0):.2f}\n",
            )
        cleanup_paths: set[Path] = {
            Path(str(prepared[key]))
            for key in ("raw", "separated", "accompaniment", "rendered")
            if prepared.get(key)
        }
        render_stem = Path(str(prepared["rendered"]))
        try:
            # Recovery creates sibling files with the render stem. They have
            # already been read into the output block, so remove them together
            # with the primary system block files.
            cleanup_paths.update(render_stem.parent.glob(f"{render_stem.stem}_*"))
        except OSError:
            pass
        cleanup_paths.add(Path(rendered))
        for path in cleanup_paths:
            if not path:
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def _record_system_block(
        self,
        session: dict[str, Any],
        prepared: dict[str, Any],
        block_started: float,
        captured_at: float,
        chunk_ms: float,
        *,
        infer_ms: float,
    ) -> None:
        """Publish live latency/load metrics for the UI and diagnostics."""
        finished_at = time.monotonic()
        block_ms = (finished_at - block_started) * 1000.0
        load = block_ms / max(1.0, chunk_ms)
        with self._lock:
            session["status"] = "live"
            session["ready_chunks"] += 1
            session["processed_seconds"] = round(
                float(session.get("processed_seconds") or 0.0)
                + float(prepared["length"]),
                3,
            )
            session["ready_seconds"] = session["processed_seconds"]
            previous = session.get("realtime_factor")
            session["realtime_factor"] = round(
                load if previous is None else float(previous) * 0.7 + load * 0.3,
                3,
            )
            session["block_ms"] = round(block_ms, 1)
            session["infer_ms"] = round(infer_ms, 1)
            session["latency_ms"] = int(
                max(0.0, (finished_at - captured_at) * 1000.0)
            )
            session["message"] = (
                "纯人声变声输出中"
                if prepared.get("direct")
                else "变声人声与伴奏已按块对齐输出"
            )

    @staticmethod
    def _append_realtime_log(path: Path, message: str) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(message)
        except OSError:
            pass

    def _pitch_shift(
        self,
        source: Path,
        destination: Path,
        semitones: int,
        *,
        mask_source: Path | None = None,
        loudness_source: Path | None = None,
        high_threshold: float | None = None,
        only_regions: list[tuple[float, float]] | None = None,
    ) -> bool:
        shift = getattr(self._ffmpeg, "pitch_shift", None)
        if not callable(shift):
            return False
        try:
            kwargs: dict[str, Any] = {
                "mask_source": mask_source,
                "loudness_source": loudness_source,
                "high_threshold": float(high_threshold or self._HIGH_PITCH_THRESHOLD),
            }
            if only_regions:
                kwargs["regions"] = only_regions
            return bool(shift(source, destination, int(semitones), **kwargs))
        except TypeError:
            if only_regions:
                return False
            # Keep compatibility with lightweight test doubles and older tools.
            return bool(shift(source, destination, int(semitones)))

    def _prepare_pitch_guard(
        self,
        source: Path,
        destination: Path,
        params: InferenceParams,
        duration: float,
        *,
        sample_rate: int = 44100,
        model: dict[str, Any] | None = None,
        only_regions: list[tuple[float, float]] | None = None,
        semitones: int | None = None,
    ) -> tuple[Path, int]:
        """Lower only detected extreme-high regions before model inference.

        The model still processes every block. A pitch tier mask leaves normal
        notes untouched, and a matching inverse shift restores only those high
        regions after inference.
        """
        if not params.auto_high_pitch_guard or duration < 0.12:
            return source, 0
        peak_f0 = self._estimate_peak_f0(source, sample_rate)
        high_threshold = self._model_high_pitch_threshold(params, model)
        if peak_f0 < high_threshold and not only_regions:
            return source, 0
        applied_semitones = int(
            semitones
            or ConversionService._guard_semitones_for_retry(
                high_threshold,
                {"source_f0_hz": peak_f0},
                source,
                only_regions,
            )
        )
        if not self._pitch_shift(
            source,
            destination,
            -applied_semitones,
            high_threshold=high_threshold,
            only_regions=only_regions,
        ):
            self._append_realtime_log(
                source.with_name("realtime.log"),
                f"PITCH_GUARD_PREP_FAILED\tpeak_f0={peak_f0:.1f}\n",
            )
            return source, 0
        self._append_realtime_log(
            source.with_name("realtime.log"),
            "PITCH_GUARD\t"
            f"peak_f0={peak_f0:.1f}\tsemitones=-{applied_semitones}\n",
        )
        return destination, -applied_semitones

    @staticmethod
    def _model_high_pitch_threshold(
        params: InferenceParams, model: dict[str, Any] | None = None
    ) -> float:
        framework = config.modelhub_normalize_framework(
            (model or {}).get("framework")
        )
        return ConversionService._model_high_pitch_threshold(
            params,
            model,
            framework,
            honor_model_metadata=True,
            fallback_threshold=RealtimeCoverService._HIGH_PITCH_THRESHOLD,
        )

    @staticmethod
    def _estimate_peak_f0(source: Path, sample_rate: int = 44100) -> float:
        """Reuse the conversion probe so realtime guard decisions stay consistent."""
        try:
            from application.conversion_service import ConversionService

            return float(ConversionService._estimate_peak_f0(source))
        except (OSError, EOFError, ValueError, wave.Error, ImportError):
            return 0.0

    @staticmethod
    def _is_nearly_silent(output: Path, source: Path) -> bool:
        """Detect model collapse without bypassing healthy converted blocks."""
        try:
            import numpy as np

            def rms(path: Path) -> float:
                with wave.open(str(path), "rb") as handle:
                    raw = handle.readframes(min(handle.getnframes(), handle.getframerate() * 8))
                if not raw:
                    return 0.0
                values = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                return float(np.sqrt(np.mean(values * values)))

            source_rms = rms(source)
            output_rms = rms(output)
            return source_rms > 0.002 and output_rms < max(0.001, source_rms * 0.08)
        except (OSError, ValueError, wave.Error, ImportError):
            return False

    @staticmethod
    def _write_pcm16(path: Path, audio, sample_rate: int) -> None:  # noqa: ANN001
        import numpy as np

        data = np.asarray(audio, dtype=np.float32)
        pcm = (np.clip(data, -1.0, 1.0) * 32767.0).astype(np.int16)
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(int(data.shape[1] if data.ndim > 1 else 1))
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm.tobytes())

    @staticmethod
    def _fit_audio(audio, frames: int):  # noqa: ANN001
        """Normalize a block to stereo PCM with an exact sample count."""
        import numpy as np

        data = np.asarray(audio, dtype=np.float32)
        if data.ndim == 1:
            data = data[:, None]
        if data.ndim != 2 or data.shape[1] == 0:
            data = np.zeros((0, 2), dtype=np.float32)
        elif data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        elif data.shape[1] > 2:
            data = data[:, :2]
        if data.shape[0] < frames:
            data = np.pad(data, ((0, frames - data.shape[0]), (0, 0)))
        return data[:frames]

    @staticmethod
    def _read_pcm16(path: Path, sample_rate: int, frames: int):
        import numpy as np

        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            source_rate = handle.getframerate()
            data = np.frombuffer(handle.readframes(frames), dtype=np.int16).astype(np.float32) / 32768.0
        data = data.reshape(-1, channels) if channels else data.reshape(-1, 1)
        if source_rate != sample_rate and len(data):
            positions = np.linspace(0, len(data) - 1, max(1, round(len(data) * sample_rate / source_rate)))
            base = np.arange(len(data))
            data = np.column_stack([np.interp(positions, base, data[:, channel]) for channel in range(data.shape[1])])
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        return data[:frames]

    def _resolve_models(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        entries = list(payload.get("models") or [])
        if not entries and payload.get("model_id"):
            entries = [{"model_id": payload["model_id"], "params": payload.get("params") or {}}]
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in entries:
            model_id = str(entry.get("model_id") or "")
            if not model_id or model_id in seen:
                continue
            record = self._models.get(model_id)
            if not record:
                continue
            framework = config.modelhub_normalize_framework(record.get("framework"))
            if framework not in self._FRAMEWORKS:
                continue
            seen.add(model_id)
            model_params = ModelService.apply_detected_rvc_version(
                record, dict(entry.get("params") or {})
            )
            result.append(
                {
                    "model_id": model_id,
                    "name": record.get("name") or model_id,
                    **ModelInfo.from_dict(record).engine_paths(),
                    "metadata": record.get("metadata") or {},
                    "params": model_params,
                }
            )
        return result

    def _validate_models(self, resolved_models: list[dict[str, Any]]) -> None:
        if not resolved_models:
            raise ValueError("请至少选择一个 RVC 或 SeedVC 模型")
        for model in resolved_models:
            engine = self._engines.for_framework(model["framework"])
            if not engine or not getattr(engine, "available", False):
                raise RuntimeError(f"{model['name']} 的 {model['framework']} 实时推理环境未就绪")
            if not Path(str(model.get("main_model_path") or "")).is_file():
                raise ValueError(f"模型文件不存在：{model['name']}")
            if model["framework"] == "seed-vc":
                if not Path(str(model.get("main_config_path") or "")).is_file():
                    raise ValueError(f"SeedVC 配置不存在：{model['name']}")
                reference = str((model.get("params") or {}).get("reference_audio") or "")
                if not Path(reference).is_file():
                    raise ValueError(f"请为 {model['name']} 选择有效的参考音频")

    def _build_spans(self, session: dict[str, Any]) -> list[dict[str, Any]]:
        duration = float(session["duration"])
        chunk = float(session["chunk_seconds"])
        model_ids = [session["models"][0]["model_id"]]
        spans: list[dict[str, Any]] = []
        start = 0.0
        while start < duration:
            end = min(duration, start + chunk)
            spans.append({"start": start, "end": end, "model_ids": model_ids})
            start = end
        return spans

    def _update(self, session: dict[str, Any], **values: Any) -> None:
        with self._lock:
            session.update(values)

    @staticmethod
    def _public(session: dict[str, Any]) -> dict[str, Any]:
        hidden = {"directory", "models", "stop_event", "thread", "chunks", "input_queue", "next_input_sequence"}
        return {key: value for key, value in session.items() if key not in hidden}

    @staticmethod
    def _bounded_float(value: Any, minimum: float, maximum: float, default: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = default
        return max(minimum, min(maximum, number))

    @classmethod
    def _system_timing_profile(
        cls,
        payload: dict[str, Any],
        framework: str,
        separate_vocals: bool,
    ) -> dict[str, Any]:
        """Resolve the live block/buffer profile for the system changer.

        The separated profile must pay UVR's fixed segment cost, so it uses
        longer blocks; the direct vocal profile can use the short blocks that
        live-stream voice changers use.
        """
        if separate_vocals:
            minimum, maximum = 0.5, 4.0
            default = 1.5 if framework == "rvc" else 2.0
        else:
            minimum, maximum = 0.25, 2.0
            default = 0.5 if framework == "rvc" else 1.0
        mode = str(payload.get("latency_mode") or "live").strip().lower()
        return {
            "chunk_seconds": cls._bounded_float(
                payload.get("chunk_seconds"), minimum, maximum, default
            ),
            # One block is the no-extra-delay value: the writer plays the
            # first completed block immediately.
            "prebuffer_blocks": int(
                cls._bounded_float(payload.get("prebuffer_blocks"), 1.0, 4.0, 1.0)
            ),
            # A small capture backlog absorbs scheduling jitter. When it
            # overflows, capture drops the oldest block instead of letting
            # latency grow without bound.
            "max_lag_blocks": int(
                cls._bounded_float(payload.get("max_lag_blocks"), 1.0, 6.0, 2.0)
            ),
            "latency_mode": "quality" if mode == "quality" else "live",
            "low_latency": mode != "quality",
        }

    def cleanup(self, session_id: str) -> bool:
        """Remove a stopped session's temporary files."""
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if not session:
            return False
        session["stop_event"].set()
        directory = Path(str(session.get("directory") or ""))
        if directory.is_dir() and directory.parent.name == "realtime-covers":
            shutil.rmtree(directory, ignore_errors=True)
        return True
