"""翻唱转换服务：编排「人声分离 → F0 提取 → SVC 推理 → 混音合成」流水线。

任务在后台线程执行，逐步更新作品在仓储中的进度与状态，前端通过轮询 get_work 获取进度。
"""

from __future__ import annotations

import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import config
from domain import InferenceParams, JobStatus, StepStatus
from infrastructure import paths
from infrastructure.engine import EngineRegistry
from infrastructure.ffmpeg_tool import FfmpegTool
from infrastructure.storage import ListRepository
from infrastructure.uvr_tool import UvrTool

_VOCAL_OUTPUT_WORKFLOWS = {"auto_vocal_merge", "manual_vocal_merge"}


def _wants_vocal_output(work: dict[str, Any]) -> bool:
    return (
        work.get("mode") == "multi"
        and str(work.get("workflow") or "auto_mix") in _VOCAL_OUTPUT_WORKFLOWS
    )


def default_steps() -> list[dict[str, Any]]:
    return [
        {"key": "separate", "label": "人声分离", "status": StepStatus.WAIT.value},
        {"key": "f0", "label": "F0 提取", "status": StepStatus.WAIT.value},
        {"key": "infer", "label": "模型推理", "status": StepStatus.WAIT.value},
        {"key": "mix", "label": "混音合成", "status": StepStatus.WAIT.value},
    ]


def default_steps_multi() -> list[dict[str, Any]]:
    """多模型混合翻唱的流水线步骤。"""
    return [
        {"key": "separate", "label": "人声分离", "status": StepStatus.WAIT.value},
        {"key": "split", "label": "歌词分割", "status": StepStatus.WAIT.value},
        {"key": "infer", "label": "逐段推理", "status": StepStatus.WAIT.value},
        {"key": "merge", "label": "人声合并", "status": StepStatus.WAIT.value},
        {"key": "mix", "label": "混音合成", "status": StepStatus.WAIT.value},
    ]


class ConversionService:
    def __init__(
        self,
        repo: ListRepository,
        ffmpeg: FfmpegTool,
        uvr: UvrTool,
        engines: EngineRegistry,
    ) -> None:
        self._repo = repo
        self._ffmpeg = ffmpeg
        self._uvr = uvr
        self._engines = engines
        # so-vits 引擎引用：供 F0 探针（仅 so-vits 有意义）使用
        self._svc = engines.sovits
        # 串行任务队列：单 GPU 上一次只跑一个任务，避免并发推理叠加导致显存 OOM
        self._queue: list[str] = []
        self._queue_lock = threading.RLock()
        self._worker_running = False

    def start(self, work_id: str) -> None:
        """把转换任务加入后台队列。"""
        with self._queue_lock:
            if work_id not in self._queue:
                self._queue.append(work_id)
                work = self._repo.get(work_id)
                if work:
                    work["queue_position"] = len(self._queue)
                    work["queued_at"] = datetime.now().isoformat(timespec="seconds")
                    self._repo.update(work_id, work)
            if self._worker_running:
                return
            self._worker_running = True
        threading.Thread(target=self._queue_worker, daemon=True).start()

    def queue_status(self) -> dict[str, Any]:
        with self._queue_lock:
            return {
                "running": self._worker_running,
                "pending": list(self._queue),
                "size": len(self._queue),
            }

    # ---- 内部 ----
    def _save(self, work: dict[str, Any]) -> None:
        self._repo.update(work["id"], work)

    def _set_step(self, work: dict[str, Any], key: str, status: str) -> None:
        for step in work["steps"]:
            if step["key"] == key:
                step["status"] = status
                break

    @staticmethod
    def _record_history(work: dict[str, Any]) -> None:
        history = list(work.get("history") or [])
        history.append(
            {
                "status": work.get("status"),
                "progress": work.get("progress", 0),
                "output_path": work.get("output_path"),
                "error": work.get("error"),
                "finished_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        work["history"] = history[-20:]

    @staticmethod
    def _log(log_file: Path, msg: str) -> None:
        """向作品日志追加一行带时间戳的记录（失败不抛出）。"""
        try:
            stamp = datetime.now().strftime("%H:%M:%S")
            with log_file.open("a", encoding="utf-8") as f:
                f.write(f"[{stamp}] {msg}\n")
        except OSError:
            pass

    def _run(self, work_id: str) -> None:
        work = self._repo.get(work_id)
        if work and work.get("mode") == "multi":
            self._run_multi(work_id)
        else:
            self._run_locked(work_id)

    def _queue_worker(self) -> None:
        try:
            while True:
                with self._queue_lock:
                    if not self._queue:
                        self._worker_running = False
                        return
                    work_id = self._queue.pop(0)
                    for pos, queued_id in enumerate(self._queue, start=1):
                        queued = self._repo.get(queued_id)
                        if queued:
                            queued["queue_position"] = pos
                            self._repo.update(queued_id, queued)
                self._run(work_id)
        finally:
            with self._queue_lock:
                if not self._queue:
                    self._worker_running = False

    def _run_locked(self, work_id: str) -> None:
        work = self._repo.get(work_id)
        if not work:
            return

        work_dir = config.WORKS_DIR / work_id
        work_dir.mkdir(parents=True, exist_ok=True)
        log_file = work_dir / "run.log"
        # 每次运行重写日志头，记录路径供前端展示与打开
        try:
            log_file.write_text(
                f"=== {work.get('title', work_id)} ===\n"
                f"开始时间: {datetime.now().isoformat(timespec='seconds')}\n"
                f"参数: {work.get('params', {})}\n",
                encoding="utf-8",
            )
        except OSError:
            pass

        work["status"] = JobStatus.RUNNING.value
        work["progress"] = 0
        work["log_path"] = str(log_file)
        self._save(work)

        try:
            params = InferenceParams.from_dict(work.get("params", {}))
            framework = config.modelhub_normalize_framework(work.get("framework"))
            is_sovits = framework == "so-vits-svc"
            engine = self._engines.for_framework(framework)
            source = Path(work["source_path"]) if work.get("source_path") else None
            duration = (
                self._ffmpeg.probe_duration(source)
                if source and source.exists()
                else None
            ) or 180.0
            self._log(log_file, f"源文件: {source} | 时长: {duration:.1f}s | 设备: {params.device}")

            # 1) 人声分离（UVR 真实分离出人声 + 伴奏；不可用时降级为原音频）
            self._set_step(work, "separate", StepStatus.ACTIVE.value)
            self._save(work)
            self._log(
                log_file,
                f"[1/4] 人声分离开始（UVR {'可用' if self._uvr.available else '降级模式'}）",
            )
            instrumental: Path | None = None
            if source and source.exists():
                # 先把源音频统一转码成标准 wav 再分离：在线下载的文件常把 m4a/flac
                # 误存成 .mp3，mp3 专用解码器会读到「junk」而失败导致分离降级。
                # ffmpeg 按内容（而非扩展名）解码，可一并纠正这类格式错配。
                sep_source = self._normalize_source(source, work_dir, log_file)
                sep_model = params.uvr_model or config.UVR_SEP_MODEL
                sep = self._uvr.separate(sep_source, work_dir, sep_model, params.device)
                vocals = sep.vocals
                instrumental = sep.instrumental
                if sep.simulated:
                    self._log(log_file, "  分离降级：直接使用源音频作为人声（无伴奏）")
                else:
                    self._log(log_file, f"  分离模型: {sep_model}")
                    self._log(log_file, f"  分离设备: {sep.device or params.device}")
                    self._log(log_file, f"  人声: {vocals}")
                    self._log(log_file, f"  伴奏: {instrumental}")
                    # 1b) 人声去混响/去回声：去掉混响后再送 SVC，缓解"电音/机械音"
                    if config.uvr_dereverb_ready():
                        self._log(
                            log_file,
                            f"  去混响中（{config.UVR_DEREVERB_MODEL}）…",
                        )
                        dr = self._uvr.separate(
                            vocals,
                            work_dir / "dereverb",
                            config.UVR_DEREVERB_MODEL,
                            params.device,
                        )
                        if not dr.simulated and dr.vocals.exists():
                            vocals = dr.vocals
                            self._log(log_file, f"  去混响设备: {dr.device or params.device}")
                            self._log(log_file, f"  去混响后人声: {vocals}")
                        else:
                            self._log(log_file, "  去混响降级：沿用原始人声")
                    else:
                        self._log(log_file, "  跳过去混响：未找到去混响模型")
            else:
                vocals = work_dir / "placeholder.wav"
            # 保存分离结果路径，供前端展示与试听（背景音乐 / 干声）
            if instrumental and Path(instrumental).exists():
                work["instrumental_path"] = str(instrumental)
            if Path(vocals).exists():
                work["vocals_path"] = str(vocals)
            self._set_step(work, "separate", StepStatus.DONE.value)
            work["progress"] = 25
            self._save(work)

            # 2) F0 提取：先把人声统一为 wav，再用 SVC 环境的预测器真实提取基频曲线
            self._set_step(work, "f0", StepStatus.ACTIVE.value)
            self._save(work)
            infer_input = Path(vocals)
            if infer_input.exists() and self._ffmpeg.available:
                wav_input = work_dir / "infer_input.wav"
                if self._ffmpeg.convert(infer_input, wav_input):
                    infer_input = wav_input
            self._log(log_file, f"[2/4] 推理输入已准备: {infer_input}")
            # 真实 F0 提取（rmvpe 等），保存曲线并校验是否检测到人声。
            # F0 探针为 so-vits 专属；其它框架（如 RVC 内部自行处理 F0）跳过该步。
            f0_stats = None
            if is_sovits and self._svc is not None:
                f0_stats = self._svc.extract_f0(
                    infer_input,
                    work_dir / "f0.npy",
                    work.get("main_config_path", ""),
                    params,
                    log_file,
                )
            elif not is_sovits:
                self._log(
                    log_file,
                    f"  F0 探针跳过（{config.MODELHUB_FRAMEWORKS.get(framework, framework)} 框架推理内部自行处理基频）",
                )
            if f0_stats:
                self._log(
                    log_file,
                    "  F0 提取完成（{f0}）: 浊音占比 {vr:.1%} | 中位基频 {hz:.1f}Hz ({note})".format(
                        f0=params.f0_method or "rmvpe",
                        vr=f0_stats["voiced_ratio"],
                        hz=f0_stats["median_hz"],
                        note=f0_stats["note"],
                    ),
                )
                if f0_stats["voiced_ratio"] < 0.02:
                    self._log(
                        log_file,
                        "  ⚠ 几乎未检测到有效人声，结果可能异常（请检查分离/去混响是否过度）",
                    )
            else:
                self._log(log_file, "  F0 提取跳过/失败（不影响后续推理，推理内部会再算一次）")
            self._set_step(work, "f0", StepStatus.DONE.value)
            work["progress"] = 50
            self._save(work)

            # 3) 推理（按模型框架路由引擎：so-vits-svc / rvc / …）
            self._set_step(work, "infer", StepStatus.ACTIVE.value)
            self._save(work)
            fw_label = config.MODELHUB_FRAMEWORKS.get(framework, framework)
            self._log(
                log_file,
                f"[3/4] {fw_label} 推理开始（引擎 {'可用' if getattr(engine, 'available', False) else '降级模式'}）",
            )
            converted = work_dir / "converted.wav"
            engine.infer(
                model={
                    "framework": framework,
                    "main_model_path": work.get("main_model_path", ""),
                    "main_config_path": work.get("main_config_path", ""),
                    "diffusion_model_path": work.get("diffusion_model_path", ""),
                    "diffusion_config_path": work.get("diffusion_config_path", ""),
                    "index_path": work.get("index_path", ""),
                },
                vocals=infer_input,
                out_path=converted,
                params=params,
                duration=duration,
                log_file=log_file,
            )
            self._set_step(work, "infer", StepStatus.DONE.value)
            work["progress"] = 75
            self._save(work)
            self._log(log_file, "  模型推理完成")

            # 4) 混音合成：转换后人声 + 原伴奏 → 完整翻唱；无伴奏则仅输出干声
            self._set_step(work, "mix", StepStatus.ACTIVE.value)
            self._save(work)
            output = work_dir / "output.wav"
            mixed = False
            vocal_output = _wants_vocal_output(work)
            if vocal_output:
                self._log(log_file, "  人声合并流程：跳过伴奏混音，输出转换后人声")
            elif (
                instrumental
                and instrumental.exists()
                and converted.exists()
                and self._ffmpeg.available
            ):
                mixed = self._ffmpeg.mix(converted, instrumental, output)
                if not mixed:
                    self._log(log_file, "  混音失败：ffmpeg 合并人声+伴奏未成功，回退为仅干声")
            elif not instrumental or not (instrumental and instrumental.exists()):
                self._log(log_file, "  无可用伴奏，输出仅干声")
            if not mixed:
                if self._ffmpeg.available and converted.exists():
                    if not self._ffmpeg.convert(converted, output):
                        output = converted
                else:
                    output = converted
            self._set_step(work, "mix", StepStatus.DONE.value)
            self._log(
                log_file,
                f"[4/4] 混音合成完成（{'人声+伴奏' if mixed else '仅干声'}）: {output}",
            )

            work["progress"] = 100
            work["status"] = JobStatus.DONE.value
            work["output_path"] = str(output)
            work["converted_path"] = str(converted)
            work["ai_vocal_paths"] = [str(converted)]
            work["format"] = output.suffix.lstrip(".").upper() or "WAV"
            work["size"] = paths.file_size_label(output)
            work["duration"] = self._format_duration(duration)
            self._record_history(work)
            self._save(work)
            self._log(log_file, "任务完成 ✅")
        except Exception as exc:  # noqa: BLE001 - 任务失败需记录而非崩溃
            work["status"] = JobStatus.FAILED.value
            work["error"] = str(exc)
            self._log(log_file, f"任务失败 ❌: {exc}")
            self._log(log_file, traceback.format_exc())
            for step in work["steps"]:
                if step["status"] == StepStatus.ACTIVE.value:
                    step["status"] = StepStatus.FAILED.value
            self._record_history(work)
            self._save(work)

    # ---- 多模型混合翻唱 ----
    def _normalize_source(self, source: Path, work_dir: Path, log_file: Path) -> Path:
        """把源音频统一转码为标准 wav 后返回；转码失败/无 ffmpeg 时回退原文件。

        在线下载的素材常把 m4a/flac 误存成 .mp3，按扩展名选解码器会失败；ffmpeg
        按文件内容解码，能纠正这类错配，使分离 / F0 / 推理拿到干净一致的 wav。
        """
        try:
            if self._ffmpeg.available and source.exists():
                norm = work_dir / "source.wav"
                if self._ffmpeg.convert(source, norm) and norm.exists():
                    self._log(log_file, f"  源音频已统一转码: {norm.name}")
                    return norm
        except (OSError, ValueError):
            pass
        return source

    @staticmethod
    def _build_timeline(
        segments: list[dict[str, Any]], duration: float
    ) -> list[dict[str, Any]]:
        """把「已指派模型的演唱句」补全为覆盖整首歌的时间轴。

        未被任何句覆盖的空隙（前奏/间奏/尾奏）以 ``model_id=None`` 的片段填充，
        保证按顺序拼接后总时长与原曲一致，且间奏处保留原始（近静音）人声。
        """
        cleaned: list[dict[str, Any]] = []
        for s in segments:
            try:
                start = max(0.0, float(s.get("start", 0.0)))
                end = min(float(duration), float(s.get("end", 0.0)))
            except (TypeError, ValueError):
                continue
            # 兼容合唱（model_ids 数组）与旧单模型（model_id）
            ids = s.get("model_ids")
            if not ids:
                single = s.get("model_id")
                ids = [single] if single else []
            if end > start:
                cleaned.append({"start": start, "end": end, "model_ids": list(ids)})
        cleaned.sort(key=lambda x: x["start"])

        timeline: list[dict[str, Any]] = []
        cursor = 0.0
        for s in cleaned:
            start = max(s["start"], cursor)
            end = s["end"]
            if end <= start:
                continue
            if start > cursor + 0.05:
                timeline.append({"start": cursor, "end": start, "model_ids": []})
            timeline.append({"start": start, "end": end, "model_ids": s["model_ids"]})
            cursor = end
        if cursor < duration - 0.05:
            timeline.append({"start": cursor, "end": duration, "model_ids": []})
        return timeline

    def _run_multi(self, work_id: str) -> None:
        work = self._repo.get(work_id)
        if not work:
            return

        work_dir = config.WORKS_DIR / work_id
        work_dir.mkdir(parents=True, exist_ok=True)
        log_file = work_dir / "run.log"
        try:
            log_file.write_text(
                f"=== {work.get('title', work_id)} (多模型混合) ===\n"
                f"开始时间: {datetime.now().isoformat(timespec='seconds')}\n",
                encoding="utf-8",
            )
        except OSError:
            pass

        work["status"] = JobStatus.RUNNING.value
        work["progress"] = 0
        work["log_path"] = str(log_file)
        self._save(work)

        try:
            base_params = InferenceParams.from_dict(work.get("params", {}))
            source = Path(work["source_path"]) if work.get("source_path") else None
            duration = (
                self._ffmpeg.probe_duration(source)
                if source and source.exists()
                else None
            ) or 180.0
            segments_in = work.get("segments") or []
            seg_models = work.get("seg_models") or {}
            self._log(
                log_file,
                f"源文件: {source} | 时长: {duration:.1f}s | "
                f"演唱句: {len(segments_in)} | 模型: {len(seg_models)}",
            )

            # 1) 人声分离（与单模型一致）
            self._set_step(work, "separate", StepStatus.ACTIVE.value)
            self._save(work)
            self._log(
                log_file,
                f"[1/5] 人声分离（UVR {'可用' if self._uvr.available else '降级模式'}）",
            )
            instrumental: Path | None = None
            if source and source.exists():
                # 先统一转码成标准 wav（修正在线下载的格式错配，避免分离降级）
                sep_source = self._normalize_source(source, work_dir, log_file)
                sep_model = base_params.uvr_model or config.UVR_SEP_MODEL
                sep = self._uvr.separate(sep_source, work_dir, sep_model, base_params.device)
                vocals = sep.vocals
                instrumental = sep.instrumental
                if sep.simulated:
                    self._log(log_file, "  分离降级：直接使用源音频作为人声（无伴奏）")
                else:
                    self._log(log_file, f"  分离设备: {sep.device or base_params.device}")
                    self._log(log_file, f"  人声: {vocals} | 伴奏: {instrumental}")
                    if config.uvr_dereverb_ready():
                        dr = self._uvr.separate(
                            vocals,
                            work_dir / "dereverb",
                            config.UVR_DEREVERB_MODEL,
                            base_params.device,
                        )
                        if not dr.simulated and dr.vocals.exists():
                            vocals = dr.vocals
                            self._log(
                                log_file,
                                f"  去混响设备: {dr.device or base_params.device}",
                            )
                            self._log(log_file, f"  去混响后人声: {vocals}")
            else:
                vocals = work_dir / "placeholder.wav"
            if instrumental and Path(instrumental).exists():
                work["instrumental_path"] = str(instrumental)
            if Path(vocals).exists():
                work["vocals_path"] = str(vocals)
            self._set_step(work, "separate", StepStatus.DONE.value)
            work["progress"] = 20
            self._save(work)

            # 2) 歌词分割：把人声统一为 wav，并规划时间轴 / 参与模型
            self._set_step(work, "split", StepStatus.ACTIVE.value)
            self._save(work)
            infer_input = Path(vocals)
            if infer_input.exists() and self._ffmpeg.available:
                wav_input = work_dir / "infer_input.wav"
                if self._ffmpeg.convert(infer_input, wav_input):
                    infer_input = wav_input
            timeline = self._build_timeline(segments_in, duration)
            used_models: list[str] = []
            for s in timeline:
                for mid in s.get("model_ids") or []:
                    if mid and mid in seg_models and mid not in used_models:
                        used_models.append(mid)
            sung = sum(1 for s in timeline if s.get("model_ids"))
            self._log(
                log_file,
                f"[2/5] 歌词分割完成：共 {len(timeline)} 段"
                f"（演唱 {sung} 段，间奏 {len(timeline) - sung} 段），"
                f"参与模型 {len(used_models)} 个",
            )
            self._set_step(work, "split", StepStatus.DONE.value)
            work["progress"] = 35
            self._save(work)

            # 3) 整轨逐模型推理：每个模型在「完整人声」上推理一次。
            #    关键修复：不再把人声切成碎片逐句送推——短碎片会产生句首/句尾
            #    电流声、咔哒声并拼出卡顿。整轨推理保证上下文连续、无边界伪声。
            self._set_step(work, "infer", StepStatus.ACTIVE.value)
            self._save(work)
            self._log(log_file, "[3/5] 整轨逐模型推理（按各模型框架路由引擎）")
            full_renders: dict[str, Path] = {}
            for n, mid in enumerate(used_models):
                model = seg_models.get(mid) or {}
                seg_params = InferenceParams.from_dict(model.get("params", {}))
                seg_framework = config.modelhub_normalize_framework(model.get("framework"))
                seg_engine = self._engines.for_framework(seg_framework)
                full_raw = work_dir / f"full_{mid}.wav"
                fw_label = config.MODELHUB_FRAMEWORKS.get(seg_framework, seg_framework)
                self._log(
                    log_file,
                    f"  [{n + 1}/{len(used_models)}] 模型 {model.get('name', mid)} "
                    f"[{fw_label}] 整轨推理（引擎 {'可用' if getattr(seg_engine, 'available', False) else '降级模式'}）…",
                )
                try:
                    seg_engine.infer(
                        model={
                            "framework": seg_framework,
                            "main_model_path": model.get("main_model_path", ""),
                            "main_config_path": model.get("main_config_path", ""),
                            "diffusion_model_path": model.get("diffusion_model_path", ""),
                            "diffusion_config_path": model.get("diffusion_config_path", ""),
                            "index_path": model.get("index_path", ""),
                        },
                        vocals=infer_input,
                        out_path=full_raw,
                        params=seg_params,
                        duration=duration,
                        log_file=log_file,
                    )
                    # 规整到 44100Hz 且锁定为整曲时长：保证逐句切片与原伴奏精确对齐
                    full_fix = work_dir / f"full_{mid}_fix.wav"
                    if self._ffmpeg.available and self._ffmpeg.pad_or_trim(
                        full_raw, full_fix, duration
                    ):
                        full_renders[mid] = full_fix
                    elif full_raw.exists():
                        full_renders[mid] = full_raw
                except Exception as exc:  # noqa: BLE001 - 单模型失败回退原声，不中断整曲
                    self._log(log_file, f"    模型整轨推理失败，相关句回退原始人声：{exc}")
                work["progress"] = 35 + int(40 * (n + 1) / max(len(used_models), 1))
                self._save(work)
            self._set_step(work, "infer", StepStatus.DONE.value)
            work["progress"] = 75
            self._save(work)

            # 给编辑器准备真正的“按模型、按句段”素材。
            # full_renders 仍是为了整轨推理的连续上下文，但编辑器不直接使用整轨；
            # 每个 clip 文件只包含该模型在该句负责的声音。
            editor_seg_dir = work_dir / "editor_segments"
            editor_seg_dir.mkdir(parents=True, exist_ok=True)
            editor_clips: list[dict[str, Any]] = []
            editor_xf = 0.06
            editor_half_xf = editor_xf / 2.0

            def _has_rendered_voice(seg: dict[str, Any] | None) -> bool:
                if not seg:
                    return False
                return any(mid in full_renders for mid in (seg.get("model_ids") or []))

            for i, seg in enumerate(timeline):
                try:
                    start = max(0.0, float(seg.get("start") or 0.0))
                    end = min(duration, max(start, float(seg.get("end") or start)))
                except (TypeError, ValueError):
                    continue
                if end <= start:
                    continue
                ids: list[str] = []
                for mid in seg.get("model_ids") or []:
                    if mid in full_renders and mid not in ids:
                        ids.append(mid)
                for mid in ids:
                    src = full_renders.get(mid)
                    if not src or not Path(src).exists() or not self._ffmpeg.available:
                        continue
                    clip_dir = editor_seg_dir / mid
                    prev_seg = timeline[i - 1] if i > 0 else None
                    next_seg = timeline[i + 1] if i + 1 < len(timeline) else None
                    pad_before = editor_half_xf if _has_rendered_voice(prev_seg) else 0.0
                    pad_after = editor_half_xf if _has_rendered_voice(next_seg) else 0.0
                    clip_start = max(0.0, start - pad_before)
                    clip_end = min(duration, end + pad_after)
                    fade_in = min(editor_xf, max(0.0, clip_end - clip_start) / 2.0) if pad_before else 0.0
                    fade_out = min(editor_xf, max(0.0, clip_end - clip_start) / 2.0) if pad_after else 0.0
                    clip = clip_dir / (
                        f"seg_{i:03d}_{int(clip_start * 1000):08d}_"
                        f"{int(clip_end * 1000):08d}.wav"
                    )
                    if self._ffmpeg.slice(Path(src), clip_start, clip_end, clip):
                        model_name = (seg_models.get(mid) or {}).get("name") or mid
                        editor_clips.append(
                            {
                                "model_id": mid,
                                "model_name": model_name,
                                "start": clip_start,
                                "end": clip_end,
                                "offset": 0.0,
                                "fade_in": fade_in,
                                "fade_out": fade_out,
                                "source_start": start,
                                "source_end": end,
                                "file": str(clip),
                            }
                        )
            work["ai_segment_clips"] = editor_clips
            self._log(
                log_file,
                f"  已生成编辑器分段素材：{len(editor_clips)} 段"
                f"（每段仅含对应 AI 声音）",
            )

            if str(work.get("workflow") or "auto_mix") == "manual_vocal_merge":
                self._set_step(work, "merge", StepStatus.ACTIVE.value)
                self._save(work)
                self._log(
                    log_file,
                    "[4/5] 手动人声合并：跳过自动拼接，等待进入编辑器逐段合并",
                )
                work["converted_path"] = ""
                work["ai_vocal_paths"] = []
                work["ai_merged_vocal_path"] = ""
                self._set_step(work, "merge", StepStatus.DONE.value)
                self._set_step(work, "mix", StepStatus.DONE.value)
                work["progress"] = 100
                work["status"] = JobStatus.DONE.value
                work["output_path"] = ""
                work["format"] = "EDITOR"
                work["size"] = f"{len(editor_clips)} 段"
                work["duration"] = self._format_duration(duration)
                self._record_history(work)
                self._save(work)
                self._log(log_file, "=== 完成：可编辑人声片段已准备 ===")
                return

            # 4) 人声合并：先把「相邻且用同一来源」的句子并成连续段，避免在同
            #    一歌手连唱处反复切割造成卡顿；再仅在真正换人处用交叉淡化平滑衔接。
            self._set_step(work, "merge", StepStatus.ACTIVE.value)
            self._save(work)
            seg_dir = work_dir / "segments"
            seg_dir.mkdir(parents=True, exist_ok=True)

            def _src_key(seg: dict[str, Any]) -> tuple[str, ...]:
                """该句的「来源指纹」：参与且推理成功的模型集合（有序去重）。

                空元组表示间奏 / 未指派 / 全部推理失败 → 用原始人声占位。
                单元素=独唱；多元素=合唱（同句多模型叠加）。
                """
                ids = [m for m in (seg.get("model_ids") or []) if m in full_renders]
                # 顺序去重，作为分组键
                uniq: list[str] = []
                for m in ids:
                    if m not in uniq:
                        uniq.append(m)
                return tuple(uniq)

            runs: list[dict[str, Any]] = []
            for seg in timeline:
                key = _src_key(seg)
                if runs and runs[-1]["key"] == key:
                    runs[-1]["end"] = seg["end"]
                else:
                    runs.append(
                        {"key": key, "start": seg["start"], "end": seg["end"]}
                    )

            xf = 0.03
            pieces: list[Path] = []
            n_runs = len(runs)
            for i, r in enumerate(runs):
                key: tuple[str, ...] = r["key"]
                start = r["start"]
                end = r["end"]
                if i < n_runs - 1:
                    end = min(duration, end + xf)  # 多借 xf 秒供交叉淡化、保长度
                piece = seg_dir / f"piece_{i:03d}.wav"
                if not key:
                    # 间奏 / 未指派 / 推理失败 → 原始人声
                    ok = (
                        self._ffmpeg.slice(infer_input, start, end, piece)
                        if self._ffmpeg.available and infer_input.exists()
                        else False
                    )
                elif len(key) == 1:
                    src = full_renders[key[0]]
                    ok = (
                        self._ffmpeg.slice(Path(src), start, end, piece)
                        if self._ffmpeg.available and Path(src).exists()
                        else False
                    )
                else:
                    # 合唱：每个模型的整轨结果各切一段，再叠加为一句合唱
                    parts: list[Path] = []
                    for j, mid in enumerate(key):
                        src = full_renders.get(mid)
                        cut = seg_dir / f"piece_{i:03d}_v{j}.wav"
                        if (
                            src
                            and self._ffmpeg.available
                            and Path(src).exists()
                            and self._ffmpeg.slice(Path(src), start, end, cut)
                        ):
                            parts.append(cut)
                    ok = (
                        self._ffmpeg.mix_vocals(parts, piece)
                        if self._ffmpeg.available and parts
                        else False
                    )
                    if ok:
                        self._log(
                            log_file,
                            f"  合唱句（{len(key)} 个模型同唱）: {start:.1f}-{end:.1f}s",
                        )
                if ok:
                    pieces.append(piece)

            full_vocal = work_dir / "converted.wav"
            merged = (
                self._ffmpeg.concat_crossfade(pieces, full_vocal, xf=xf)
                if self._ffmpeg.available and pieces
                else False
            )
            if not merged and self._ffmpeg.available and pieces:
                merged = self._ffmpeg.concat(pieces, full_vocal)  # 退回硬拼接
                if merged:
                    self._log(log_file, "  交叉淡化失败，退回硬拼接")
            if not merged:
                if full_renders:
                    full_vocal = next(iter(full_renders.values()))
                else:
                    full_vocal = infer_input
                self._log(log_file, "  人声合并失败/降级：使用整轨结果或原始人声")
            else:
                self._log(
                    log_file,
                    f"[4/5] 人声合并完成（{len(timeline)} 句合并为 {len(pieces)} 段）：{full_vocal}",
                )
            work["converted_path"] = str(full_vocal)
            work["ai_vocal_paths"] = [str(p) for p in full_renders.values()]
            work["ai_merged_vocal_path"] = str(full_vocal)
            self._set_step(work, "merge", StepStatus.DONE.value)
            work["progress"] = 88
            self._save(work)

            # 5) 混音合成：完整人声 + 原伴奏
            self._set_step(work, "mix", StepStatus.ACTIVE.value)
            self._save(work)
            output = work_dir / "output.wav"
            mixed = False
            vocal_output = _wants_vocal_output(work)
            if vocal_output:
                self._log(log_file, "  人声合并流程：跳过伴奏混音，输出合并后人声")
            elif (
                instrumental
                and Path(instrumental).exists()
                and Path(full_vocal).exists()
                and self._ffmpeg.available
            ):
                mixed = self._ffmpeg.mix(Path(full_vocal), Path(instrumental), output)
            if not mixed:
                if self._ffmpeg.available and Path(full_vocal).exists():
                    if not self._ffmpeg.convert(Path(full_vocal), output):
                        output = Path(full_vocal)
                else:
                    output = Path(full_vocal)
            self._set_step(work, "mix", StepStatus.DONE.value)
            self._log(
                log_file,
                f"[5/5] 混音合成完成（{'人声+伴奏' if mixed else '仅人声'}）: {output}",
            )

            work["progress"] = 100
            work["status"] = JobStatus.DONE.value
            work["output_path"] = str(output)
            work["format"] = output.suffix.lstrip(".").upper() or "WAV"
            work["size"] = paths.file_size_label(output)
            work["duration"] = self._format_duration(duration)
            self._record_history(work)
            self._save(work)
            self._log(log_file, "任务完成 ✅")
        except Exception as exc:  # noqa: BLE001 - 任务失败需记录而非崩溃
            work["status"] = JobStatus.FAILED.value
            work["error"] = str(exc)
            self._log(log_file, f"任务失败 ❌: {exc}")
            self._log(log_file, traceback.format_exc())
            for step in work["steps"]:
                if step["status"] == StepStatus.ACTIVE.value:
                    step["status"] = StepStatus.FAILED.value
            self._record_history(work)
            self._save(work)

    @staticmethod
    def _format_duration(seconds: float) -> str:
        total = int(seconds)
        return f"{total // 60:02d}:{total % 60:02d}"
