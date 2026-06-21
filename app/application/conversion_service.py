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
from infrastructure.ffmpeg_tool import FfmpegTool
from infrastructure.storage import ListRepository
from infrastructure.svc_engine import SvcEngine
from infrastructure.uvr_tool import UvrTool


def default_steps() -> list[dict[str, Any]]:
    return [
        {"key": "separate", "label": "人声分离", "status": StepStatus.WAIT.value},
        {"key": "f0", "label": "F0 提取", "status": StepStatus.WAIT.value},
        {"key": "infer", "label": "SVC 推理", "status": StepStatus.WAIT.value},
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
        svc: SvcEngine,
    ) -> None:
        self._repo = repo
        self._ffmpeg = ffmpeg
        self._uvr = uvr
        self._svc = svc
        # 串行执行：单 GPU 上一次只跑一个任务，避免并发推理叠加导致显存 OOM
        self._gpu_lock = threading.Lock()

    def start(self, work_id: str) -> None:
        """在后台线程启动转换。"""
        thread = threading.Thread(target=self._run, args=(work_id,), daemon=True)
        thread.start()

    # ---- 内部 ----
    def _save(self, work: dict[str, Any]) -> None:
        self._repo.update(work["id"], work)

    def _set_step(self, work: dict[str, Any], key: str, status: str) -> None:
        for step in work["steps"]:
            if step["key"] == key:
                step["status"] = status
                break

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
        # 等待 GPU 空闲（串行），期间任务保持排队状态
        with self._gpu_lock:
            work = self._repo.get(work_id)
            if work and work.get("mode") == "multi":
                self._run_multi(work_id)
            else:
                self._run_locked(work_id)

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
                sep_model = params.uvr_model or config.UVR_SEP_MODEL
                sep = self._uvr.separate(source, work_dir, sep_model, params.device)
                vocals = sep.vocals
                instrumental = sep.instrumental
                if sep.simulated:
                    self._log(log_file, "  分离降级：直接使用源音频作为人声（无伴奏）")
                else:
                    self._log(log_file, f"  分离模型: {sep_model}")
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
            # 真实 F0 提取（rmvpe 等），保存曲线并校验是否检测到人声
            f0_stats = self._svc.extract_f0(
                infer_input,
                work_dir / "f0.npy",
                work.get("main_config_path", ""),
                params,
                log_file,
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

            # 3) SVC 推理（主模型 + 浅扩散，子进程调用 so-vits-svc）
            self._set_step(work, "infer", StepStatus.ACTIVE.value)
            self._save(work)
            self._log(
                log_file,
                f"[3/4] SVC 推理开始（引擎 {'可用' if self._svc.available else '降级模式'}）",
            )
            converted = work_dir / "converted.wav"
            self._svc.infer(
                main_model=work.get("main_model_path", ""),
                main_config=work.get("main_config_path", ""),
                diffusion_model=work.get("diffusion_model_path", ""),
                diffusion_config=work.get("diffusion_config_path", ""),
                vocals=infer_input,
                out_path=converted,
                params=params,
                duration=duration,
                log_file=log_file,
            )
            self._set_step(work, "infer", StepStatus.DONE.value)
            work["progress"] = 75
            self._save(work)
            self._log(log_file, "  SVC 推理完成")

            # 4) 混音合成：转换后人声 + 原伴奏 → 完整翻唱；无伴奏则仅输出干声
            self._set_step(work, "mix", StepStatus.ACTIVE.value)
            self._save(work)
            output = work_dir / "output.wav"
            mixed = False
            if (
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
            work["format"] = output.suffix.lstrip(".").upper() or "WAV"
            work["size"] = paths.file_size_label(output)
            work["duration"] = self._format_duration(duration)
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
            self._save(work)

    # ---- 多模型混合翻唱 ----
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
            if end > start:
                cleaned.append({"start": start, "end": end, "model_id": s.get("model_id")})
        cleaned.sort(key=lambda x: x["start"])

        timeline: list[dict[str, Any]] = []
        cursor = 0.0
        for s in cleaned:
            start = max(s["start"], cursor)
            end = s["end"]
            if end <= start:
                continue
            if start > cursor + 0.05:
                timeline.append({"start": cursor, "end": start, "model_id": None})
            timeline.append({"start": start, "end": end, "model_id": s["model_id"]})
            cursor = end
        if cursor < duration - 0.05:
            timeline.append({"start": cursor, "end": duration, "model_id": None})
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
                sep_model = base_params.uvr_model or config.UVR_SEP_MODEL
                sep = self._uvr.separate(source, work_dir, sep_model, base_params.device)
                vocals = sep.vocals
                instrumental = sep.instrumental
                if sep.simulated:
                    self._log(log_file, "  分离降级：直接使用源音频作为人声（无伴奏）")
                else:
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

            # 2) 歌词分割：把人声统一为 wav，再按时间轴逐句切片
            self._set_step(work, "split", StepStatus.ACTIVE.value)
            self._save(work)
            infer_input = Path(vocals)
            if infer_input.exists() and self._ffmpeg.available:
                wav_input = work_dir / "infer_input.wav"
                if self._ffmpeg.convert(infer_input, wav_input):
                    infer_input = wav_input
            timeline = self._build_timeline(segments_in, duration)
            seg_dir = work_dir / "segments"
            seg_dir.mkdir(parents=True, exist_ok=True)
            sliced: list[dict[str, Any]] = []
            for i, seg in enumerate(timeline):
                seg_in = seg_dir / f"seg_{i:03d}_in.wav"
                ok = (
                    self._ffmpeg.slice(infer_input, seg["start"], seg["end"], seg_in)
                    if self._ffmpeg.available and infer_input.exists()
                    else False
                )
                sliced.append({"i": i, "in": seg_in if ok else None, **seg})
            sung = sum(1 for s in timeline if s["model_id"])
            self._log(
                log_file,
                f"[2/5] 歌词分割完成：共 {len(timeline)} 段（演唱 {sung} 段，间奏 {len(timeline) - sung} 段）",
            )
            self._set_step(work, "split", StepStatus.DONE.value)
            work["progress"] = 40
            self._save(work)

            # 3) 逐段推理：演唱段送对应模型，间奏/未指派段保留原始人声
            self._set_step(work, "infer", StepStatus.ACTIVE.value)
            self._save(work)
            self._log(
                log_file,
                f"[3/5] 逐段推理（引擎 {'可用' if self._svc.available else '降级模式'}）",
            )
            outputs: list[Path] = []
            total = len(sliced)
            for item in sliced:
                idx = item["i"]
                seg_in = item["in"]
                model_id = item.get("model_id")
                if not seg_in or not Path(seg_in).exists():
                    continue
                seg_dur = max(0.05, item["end"] - item["start"])
                seg_out = seg_dir / f"seg_{idx:03d}_out.wav"
                model = seg_models.get(model_id) if model_id else None
                produced = Path(seg_in)
                if model:
                    seg_params = InferenceParams.from_dict(model.get("params", {}))
                    self._log(
                        log_file,
                        f"  [{idx + 1}/{total}] {item['start']:.2f}-{item['end']:.2f}s "
                        f"→ {model.get('name', model_id)}",
                    )
                    try:
                        self._svc.infer(
                            main_model=model.get("main_model_path", ""),
                            main_config=model.get("main_config_path", ""),
                            diffusion_model=model.get("diffusion_model_path", ""),
                            diffusion_config=model.get("diffusion_config_path", ""),
                            vocals=Path(seg_in),
                            out_path=seg_out,
                            params=seg_params,
                            duration=seg_dur,
                            log_file=log_file,
                        )
                        produced = seg_out if seg_out.exists() else Path(seg_in)
                    except Exception as exc:  # noqa: BLE001 - 单段失败回退原声，不中断整曲
                        self._log(log_file, f"    片段推理失败，回退原始人声：{exc}")
                        produced = Path(seg_in)
                # 锁定每段到其原始切片时长：避免推理输出微小长短差异累计成
                # 人声/伴奏错位，并消除采样率不一致带来的变速。失败则退回原段。
                if self._ffmpeg.available:
                    seg_fix = seg_dir / f"seg_{idx:03d}_fix.wav"
                    if self._ffmpeg.pad_or_trim(produced, seg_fix, seg_dur):
                        produced = seg_fix
                outputs.append(produced)
                work["progress"] = 40 + int(35 * (idx + 1) / max(total, 1))
                self._save(work)
            self._set_step(work, "infer", StepStatus.DONE.value)
            work["progress"] = 75
            self._save(work)

            # 4) 人声合并：按顺序拼接所有片段为完整人声
            self._set_step(work, "merge", StepStatus.ACTIVE.value)
            self._save(work)
            full_vocal = work_dir / "converted.wav"
            merged = (
                self._ffmpeg.concat(outputs, full_vocal)
                if self._ffmpeg.available and outputs
                else False
            )
            if not merged:
                if outputs and Path(outputs[0]).exists():
                    full_vocal = Path(outputs[0])
                else:
                    full_vocal = infer_input
                self._log(log_file, "  人声合并失败/降级：使用首段或整段人声")
            else:
                self._log(log_file, f"[4/5] 人声合并完成：{full_vocal}")
            self._set_step(work, "merge", StepStatus.DONE.value)
            work["progress"] = 88
            self._save(work)

            # 5) 混音合成：完整人声 + 原伴奏
            self._set_step(work, "mix", StepStatus.ACTIVE.value)
            self._save(work)
            output = work_dir / "output.wav"
            mixed = False
            if (
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
            self._save(work)

    @staticmethod
    def _format_duration(seconds: float) -> str:
        total = int(seconds)
        return f"{total // 60:02d}:{total % 60:02d}"
