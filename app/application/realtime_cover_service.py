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
from domain import InferenceParams
from infrastructure import paths
from infrastructure.engine import EngineRegistry
from infrastructure.ffmpeg_tool import FfmpegTool
from infrastructure.uvr_tool import UvrTool
from infrastructure.system_audio import SystemAudioReader, SystemAudioWriter, list_devices

from .model_service import ModelService


class RealtimeCoverService:
    """Manage progressive RVC / SeedVC song playback sessions."""

    _FRAMEWORKS = {"rvc", "seed-vc"}
    _HIGH_PITCH_THRESHOLD = 800.0

    def __init__(
        self,
        models: ModelService,
        ffmpeg: FfmpegTool,
        uvr: UvrTool,
        engines: EngineRegistry,
    ) -> None:
        self._models = models
        self._ffmpeg = ffmpeg
        self._uvr = uvr
        self._engines = engines
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

        session_id = paths.new_id("live_")
        session_dir = config.TEMP_DIR / "realtime-covers" / session_id
        duration = float(self._ffmpeg.probe_duration(source) or 0.0)
        if duration <= 0:
            raise ValueError("无法读取歌曲时长")
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
        return list_devices()

    def start_system(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Start a streaming changer for a mixed WASAPI loopback input.

        QQ Music and similar players expose one mixed signal. UVR is therefore
        kept resident and extracts the vocal stem per block before RVC/SeedVC
        inference. The residual of that same block is the accompaniment, so
        both streams keep the original clock and no second capture is needed.
        """
        input_device = str(payload.get("input_device") or "").strip()
        output_device = str(payload.get("output_device") or "").strip()
        if input_device and output_device and input_device == output_device:
            raise ValueError("人声输入和输出设备不能相同")
        if not input_device or not output_device:
            raise ValueError("请选择系统混合音频回环输入和输出设备")
        devices = list_devices()
        if not devices:
            raise RuntimeError("未检测到系统音频设备，请安装 soundcard 并配置虚拟音频线")
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
        if not system_input_ids:
            raise RuntimeError("未检测到系统混合音频输入，请启用 WASAPI 回环、VB-CABLE 或 Voicemeeter")
        if input_device not in system_input_ids:
            raise ValueError("所选设备不是系统混合音频输入，请改选回环或虚拟音频线设备")
        if output_ids and output_device not in output_ids:
            raise ValueError("系统音频输出设备不存在，请刷新设备列表")
        if payload.get("mode") == "multi" or payload.get("segments"):
            raise ValueError("系统音频变声不支持多模型混合或分段指派")
        resolved_models = self._resolve_models(payload or {})
        if len(resolved_models) != 1:
            raise ValueError("实时变声只支持单个 RVC 或 SeedVC 模型")
        if not self._uvr.available:
            raise RuntimeError("系统混合音频变声需要 UVR 人声分离环境与模型")
        model = resolved_models[0]
        self._validate_models(resolved_models)
        session_id = paths.new_id("system_")
        session_dir = config.TEMP_DIR / "realtime-covers" / session_id
        # UVR + RVC each have a fixed per-request cost. Four-second blocks
        # amortize model/file overhead and avoid the repeated short-block
        # underruns that make playback sound like dropped packets.
        chunk_seconds = self._bounded_float(payload.get("chunk_seconds"), 4.0, 12.0, 8.0)
        sample_rate = int(self._bounded_float(payload.get("sample_rate"), 16000, 48000, 44100))
        session: dict[str, Any] = {
            "id": session_id,
            "input_mode": "system",
            "status": "preparing",
            "message": "正在加载实时人声分离与变声模型",
            "title": "系统音频实时变声",
            "model_ids": [model["model_id"]],
            "model_names": [model["name"]],
            "models": [model],
            "mode": "single",
            "duration": 0.0,
            "chunk_seconds": chunk_seconds,
            "sample_rate": sample_rate,
            "crossfade_ms": self._bounded_float(payload.get("crossfade_ms"), 10.0, 120.0, 40.0),
            "buffer_seconds": self._bounded_float(payload.get("buffer_seconds"), 0.5, 8.0, 1.0),
            "vocal_gain_db": self._bounded_float(payload.get("vocal_gain_db"), -12.0, 6.0, 0.0),
            "instrumental_gain_db": self._bounded_float(payload.get("instrumental_gain_db"), -12.0, 6.0, 0.0),
            "input_device": input_device,
            "output_device": output_device,
            "ready_seconds": 0.0,
            "processed_seconds": 0.0,
            "realtime_factor": None,
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
            separation = self._uvr.separate(
                source,
                directory / "stems",
                str((session["models"][0].get("params") or {}).get("uvr_model") or ""),
                str((session["models"][0].get("params") or {}).get("device") or "auto"),
            )
            if not separation.instrumental or not Path(separation.instrumental).is_file():
                raise RuntimeError("实时翻唱需要可用的 UVR 人声/伴奏分离环境")
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

                guarded_vocal, guard_shift = self._prepare_pitch_guard(
                    raw_vocal,
                    directory / f"vocal_{index:05d}_guarded.wav",
                    model_params,
                    length,
                )
                raw_render = directory / f"render_{index:05d}_{model_id}.wav"
                persistent = worker_sessions.get(model_id)
                if persistent is not None:
                    persistent.infer(guarded_vocal, raw_render)
                else:
                    engine.infer(
                        model=model,
                        vocals=guarded_vocal,
                        out_path=raw_render,
                        params=model_params,
                        duration=length,
                        log_file=directory / "realtime.log",
                    )
                if guard_shift:
                    restored = directory / f"render_{index:05d}_{model_id}_restored.wav"
                    if self._pitch_shift(
                        raw_render,
                        restored,
                        -guard_shift,
                        mask_source=raw_vocal,
                        loudness_source=raw_vocal,
                    ):
                        raw_render = restored
                    else:
                        self._append_realtime_log(
                            directory / "realtime.log",
                            "PITCH_GUARD_RESTORE_FAILED\t保共振峰升调失败，保留模型输出\n",
                        )
                if model_params.auto_high_pitch_guard and self._is_nearly_silent(raw_render, guarded_vocal):
                    self._append_realtime_log(
                        directory / "realtime.log",
                        "PITCH_GUARD_FALLBACK\t模型输出接近静音，回退原始人声\n",
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
        worker = None
        separator = None
        try:
            import numpy as np

            directory.mkdir(parents=True, exist_ok=True)
            model = session["models"][0]
            model_params = InferenceParams.from_dict(model.get("params") or {})
            separator_opener = getattr(self._uvr, "open_realtime_session", None)
            if not callable(separator_opener):
                raise RuntimeError("当前 UVR 分离环境不支持常驻实时处理")
            separator = separator_opener(
                str((model.get("params") or {}).get("uvr_model") or config.UVR_MODEL),
                str((model.get("params") or {}).get("device") or "auto"),
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
                low_latency=True,
            )
            frames = max(1, round(session["sample_rate"] * session["chunk_seconds"]))
            crossfade_frames = min(
                max(1, frames // 4),
                max(1, round(session["sample_rate"] * session["crossfade_ms"] / 1000.0)),
            )
            started = time.monotonic()
            self._update(session, status="ready", message="混合音频分离与变声已就绪，开始流式输出")
            with (
                SystemAudioReader(session["input_device"], session["sample_rate"], 2) as reader,
                # Playback runs on its own thread and starts after two blocks;
                # this prevents player.play() from stalling the conversion
                # pipeline at every block boundary.
                SystemAudioWriter(
                    session["output_device"],
                    session["sample_rate"],
                    2,
                    prebuffer_blocks=2,
                    crossfade_frames=crossfade_frames,
                ) as writer,
            ):
                captured_queue: queue.Queue[Any] = queue.Queue(maxsize=8)
                separated_queue: queue.Queue[Any] = queue.Queue(maxsize=4)
                pipeline_stop = threading.Event()
                capture_done = threading.Event()
                separation_done = threading.Event()
                errors: list[Exception] = []

                def capture_loop() -> None:
                    index = 0
                    try:
                        while not session["stop_event"].is_set() and not pipeline_stop.is_set():
                            block = np.asarray(reader.read(frames), dtype=np.float32)
                            captured_queue.put((index, block))
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
                            index, captured = item
                            current = np.asarray(captured, dtype=np.float32)
                            overlap_frames = 0
                            processing = current
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
                            )
                            separated_queue.put(prepared)
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
        separator: Any,
        captured: Any,
        frames: int,
        index: int,
        sample_rate: int,
        *,
        output_frames: int | None = None,
        overlap_frames: int = 0,
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
            }
        raw = directory / f"system_input_{index:06d}.wav"
        separated = directory / f"system_vocal_{index:06d}.wav"
        accompaniment = directory / f"system_music_{index:06d}.wav"
        self._write_pcm16(raw, captured, sample_rate)
        separator.infer(
            raw,
            separated,
            timeout=max(120.0, length * 20.0),
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
        }

    def _render_system_block(
        self,
        session: dict[str, Any],
        worker: Any,
        writer: Any,
        prepared: dict[str, Any],
        started: float,
        np: Any,
    ) -> None:
        frame_count = int(prepared["frames"])
        overlap_frames = int(prepared.get("overlap_frames") or 0)
        if prepared.get("silent"):
            # Keep the output clock continuous while the source player is
            # paused/stopped. No separator or voice-conversion inference is
            # needed for a zero block, and no UVR output error is possible.
            silent = np.zeros_like(self._fit_audio(prepared["captured"], frame_count))
            writer.write(silent, overlap_frames=overlap_frames)
            with self._lock:
                session["status"] = "live"
                session["input_silent"] = True
                session["ready_chunks"] += 1
                session["processed_seconds"] = round(
                    session["processed_seconds"] + float(prepared["length"]), 3
                )
                session["ready_seconds"] = session["processed_seconds"]
                session["realtime_factor"] = round(
                    (time.monotonic() - started) / max(0.001, session["processed_seconds"]),
                    3,
                )
                session["message"] = "未检测到系统音频，等待播放器继续播放"
            return
        separated = Path(prepared["separated"])
        accompaniment_stem = Path(prepared["accompaniment"])
        rendered = Path(prepared["rendered"])
        model_params = InferenceParams.from_dict(
            (session["models"][0].get("params") or {})
        )
        guarded, guard_shift = self._prepare_pitch_guard(
            separated,
            separated.with_name(separated.stem + "_guarded.wav"),
            model_params,
            float(prepared["length"]),
            sample_rate=int(session["sample_rate"]),
        )
        worker.infer(
            guarded,
            rendered,
            timeout=max(120.0, float(prepared["length"]) * 20.0),
        )
        if guard_shift:
            restored = rendered.with_name(rendered.stem + "_restored.wav")
            if self._pitch_shift(
                rendered,
                restored,
                -guard_shift,
                mask_source=separated,
                loudness_source=separated,
            ):
                rendered = restored
            else:
                self._append_realtime_log(
                    Path(session["directory"]) / "realtime-system.log",
                    "PITCH_GUARD_RESTORE_FAILED\t保共振峰升调失败，保留模型输出\n",
                )
        if model_params.auto_high_pitch_guard and self._is_nearly_silent(rendered, guarded):
            self._append_realtime_log(
                Path(session["directory"]) / "realtime-system.log",
                "PITCH_GUARD_FALLBACK\t模型输出接近静音，回退原始人声\n",
            )
            rendered = separated
        extracted = self._fit_audio(
            self._read_pcm16(separated, session["sample_rate"], frame_count),
            frame_count,
        )
        if accompaniment_stem.is_file():
            accompaniment = self._fit_audio(
                self._read_pcm16(accompaniment_stem, session["sample_rate"], frame_count),
                frame_count,
            )
        else:
            accompaniment = self._fit_audio(prepared["captured"], frame_count) - extracted
        output_audio = self._fit_audio(
            self._read_pcm16(rendered, session["sample_rate"], frame_count),
            frame_count,
        )
        output_audio *= 10.0 ** (float(session["vocal_gain_db"]) / 20.0)
        accompaniment *= 10.0 ** (float(session["instrumental_gain_db"]) / 20.0)
        mixed = output_audio + accompaniment
        peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
        if peak > 0.98:
            mixed *= 0.98 / peak
        writer.write(np.clip(mixed, -1.0, 1.0), overlap_frames=overlap_frames)
        with self._lock:
            session["status"] = "live"
            session["input_silent"] = False
            session["ready_chunks"] += 1
            session["processed_seconds"] = round(
                session["processed_seconds"] + float(prepared["length"]), 3
            )
            session["ready_seconds"] = session["processed_seconds"]
            session["realtime_factor"] = round(
                (time.monotonic() - started) / max(0.001, session["processed_seconds"]),
                3,
            )
            session["message"] = "变声人声与伴奏已按块对齐输出"
        for path in (
            prepared["raw"],
            prepared["separated"],
            prepared["accompaniment"],
            prepared["rendered"],
            guarded,
            rendered if rendered != Path(prepared["rendered"]) else None,
        ):
            if not path:
                continue
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass

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
    ) -> bool:
        shift = getattr(self._ffmpeg, "pitch_shift", None)
        if not callable(shift):
            return False
        try:
            return bool(
                shift(
                    source,
                    destination,
                    int(semitones),
                    mask_source=mask_source,
                    loudness_source=loudness_source,
                    high_threshold=self._HIGH_PITCH_THRESHOLD,
                )
            )
        except TypeError:
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
    ) -> tuple[Path, int]:
        """Lower only detected extreme-high regions before model inference.

        The model still processes every block. A pitch tier mask leaves normal
        notes untouched, and a matching inverse shift restores only those high
        regions after inference.
        """
        if not params.auto_high_pitch_guard or duration < 0.12:
            return source, 0
        peak_f0 = self._estimate_peak_f0(source, sample_rate)
        if peak_f0 < self._HIGH_PITCH_THRESHOLD:
            return source, 0
        if not self._pitch_shift(source, destination, -12):
            self._append_realtime_log(
                source.with_name("realtime.log"),
                f"PITCH_GUARD_PREP_FAILED\tpeak_f0={peak_f0:.1f}\n",
            )
            return source, 0
        self._append_realtime_log(
            source.with_name("realtime.log"),
            f"PITCH_GUARD\tpeak_f0={peak_f0:.1f}\tsemitones=-12\n",
        )
        return destination, -12

    @staticmethod
    def _estimate_peak_f0(source: Path, sample_rate: int = 44100) -> float:
        """Estimate the highest reliable voiced fundamental in a short block."""
        try:
            import numpy as np

            with wave.open(str(source), "rb") as handle:
                rate = int(handle.getframerate() or sample_rate)
                channels = int(handle.getnchannels() or 1)
                frames = handle.readframes(handle.getnframes())
            if not frames:
                return 0.0
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
            audio = audio.reshape(-1, channels).mean(axis=1)
            target_rate = min(rate, 16000)
            if rate != target_rate and audio.size:
                positions = np.linspace(0, audio.size - 1, max(1, round(audio.size * target_rate / rate)))
                audio = np.interp(positions, np.arange(audio.size), audio)
            if audio.size < max(256, int(target_rate * 0.08)):
                return 0.0
            frame = min(audio.size, max(1024, int(target_rate * 0.08)))
            hop = max(1, frame // 2)
            min_lag = max(2, int(target_rate / 2000.0))
            max_lag = min(frame - 1, int(target_rate / 60.0))
            highest = 0.0
            for start in range(0, max(1, audio.size - frame + 1), hop):
                chunk = audio[start : start + frame]
                if chunk.size < frame:
                    chunk = np.pad(chunk, (0, frame - chunk.size))
                chunk = chunk - float(np.mean(chunk))
                energy = float(np.sqrt(np.mean(chunk * chunk)))
                if energy < 0.008:
                    continue
                corr = np.correlate(chunk, chunk, mode="full")[frame - 1 :]
                base = float(corr[0])
                if base <= 0.0:
                    continue
                corr = corr / base
                candidates = [
                    lag
                    for lag in range(min_lag + 1, max_lag)
                    if corr[lag] >= corr[lag - 1]
                    and corr[lag] >= corr[lag + 1]
                    and corr[lag] >= 0.45
                ]
                lag = candidates[0] if candidates else min_lag + int(np.argmax(corr[min_lag : max_lag + 1]))
                strength = float(corr[lag])
                if strength >= 0.35:
                    highest = max(highest, target_rate / float(lag))
            return float(highest)
        except (OSError, ValueError, wave.Error, ImportError):
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
            result.append(
                {
                    "model_id": model_id,
                    "name": record.get("name") or model_id,
                    "framework": framework,
                    "main_model_path": (record.get("main_model") or {}).get("path", ""),
                    "main_config_path": (record.get("main_config") or {}).get("path", ""),
                    "index_path": (record.get("index_file") or {}).get("path", ""),
                    "params": dict(entry.get("params") or {}),
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
