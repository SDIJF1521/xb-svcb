"""翻唱转换服务：编排「人声分离 → F0 提取 → SVC 推理 → 混音合成」流水线。

任务在后台线程执行，逐步更新作品在仓储中的进度与状态，前端通过轮询 get_work 获取进度。
"""

from __future__ import annotations

import threading
import traceback
import wave
import json
import re
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
from infrastructure.pymss_tool import PymssTool
from infrastructure.vocal_enhancement import VocalEnhancementProcessor

_VOCAL_OUTPUT_WORKFLOWS = {"auto_vocal_merge", "manual_vocal_merge"}


def _wants_vocal_output(work: dict[str, Any]) -> bool:
    return (
        work.get("mode") == "multi"
        and str(work.get("workflow") or "auto_mix") in _VOCAL_OUTPUT_WORKFLOWS
    )


def default_steps(
    enhancement: bool = False,
    preprocess: bool = True,
    harmony_removal: bool = False,
) -> list[dict[str, Any]]:
    steps = []
    if preprocess:
        steps.extend([
            {"key": "separate", "label": "前期人声分离", "status": StepStatus.WAIT.value},
            *([{"key": "harmony", "label": "可选去混响净化", "status": StepStatus.WAIT.value}] if harmony_removal else []),
            {"key": "repair_input", "label": "分离人声修复", "status": StepStatus.WAIT.value},
        ])
    steps.extend([
        {"key": "f0", "label": "F0 提取", "status": StepStatus.WAIT.value},
        {"key": "infer", "label": "模型推理", "status": StepStatus.WAIT.value},
        {"key": "repair_output", "label": "输出人声修复", "status": StepStatus.WAIT.value},
    ])
    if enhancement:
        steps.append(
            {"key": "enhance", "label": "AI 歌声增强", "status": StepStatus.WAIT.value}
        )
    steps.append(
        {"key": "mix", "label": "混音合成", "status": StepStatus.WAIT.value}
    )
    return steps


def default_steps_multi(
    enhancement: bool = False,
    preprocess: bool = True,
    harmony_removal: bool = False,
) -> list[dict[str, Any]]:
    """多模型混合翻唱的流水线步骤。"""
    steps = []
    if preprocess:
        steps.extend([
            {"key": "separate", "label": "前期人声分离", "status": StepStatus.WAIT.value},
            *([{"key": "harmony", "label": "可选去混响净化", "status": StepStatus.WAIT.value}] if harmony_removal else []),
            {"key": "repair_input", "label": "分离人声修复", "status": StepStatus.WAIT.value},
        ])
    steps.extend([
        {"key": "split", "label": "歌词分割", "status": StepStatus.WAIT.value},
        {"key": "infer", "label": "逐段推理", "status": StepStatus.WAIT.value},
        {"key": "merge", "label": "人声合并", "status": StepStatus.WAIT.value},
        {"key": "repair_output", "label": "输出人声修复", "status": StepStatus.WAIT.value},
    ])
    if enhancement:
        steps.append(
            {"key": "enhance", "label": "AI 歌声增强", "status": StepStatus.WAIT.value}
        )
    steps.append(
        {"key": "mix", "label": "混音合成", "status": StepStatus.WAIT.value}
    )
    return steps


def default_steps_ai_enhancement() -> list[dict[str, Any]]:
    """独立 AI 增强任务：原曲分析、翻唱人声准备、增强和重新混音。"""
    return [
        {"key": "reference", "label": "原曲人声与伴奏分析", "status": StepStatus.WAIT.value},
        {"key": "cover_vocal", "label": "翻唱人声准备", "status": StepStatus.WAIT.value},
        {"key": "enhance", "label": "AI 歌声增强", "status": StepStatus.WAIT.value},
        {"key": "mix", "label": "增强成品混音", "status": StepStatus.WAIT.value},
    ]


class ConversionService:
    _HIGH_PITCH_THRESHOLD = 800.0
    _HIGH_PITCH_GUARD_SEMITONES = 7
    _DROPOUT_RECOVERY_MAX_ATTEMPTS = 4
    # Offline full-track recovery can afford one extra pass after a real
    # regional detector result; realtime/editor keep the lower shared limit.
    _DROPOUT_RECOVERY_OFFLINE_MAX_ATTEMPTS = 5
    _DROPOUT_RECOVERY_MIN_THRESHOLD = 300.0
    _DROPOUT_RECOVERY_MIN_DURATION = 0.12
    _MAX_HIGH_PITCH_GUARD_ROUNDS = 8
    # Include the attack/release around a confirmed bad syllable. Keep this
    # close to the note boundary: a nearly one-second scope can pull healthy
    # neighboring syllables into the PSOLA pass and make the transition audible.
    _HIGH_PITCH_GUARD_CONTEXT_SECONDS = 0.24
    _HIGH_PITCH_GUARD_MERGE_GAP_SECONDS = 0.28
    # A final pass is allowed only for a handful of short, still-confirmed
    # dropouts.  Keeping this scope small prevents a late retry from
    # reprocessing an otherwise healthy high-note phrase.
    _DROPOUT_RESIDUAL_MAX_REGIONS = 8
    _DROPOUT_RESIDUAL_MAX_SECONDS = 4.0

    @classmethod
    def _high_pitch_guard_rounds(cls, params: InferenceParams) -> int:
        """Return the user-selected guarded retry count.

        The ordinary workflow deliberately ignores the stored advanced value
        and keeps the established three retry rounds. This prevents a preset
        saved with full parameters from changing default-mode rendering.
        """
        if not bool(getattr(params, "auto_high_pitch_guard", True)):
            return 0
        default_rounds = max(0, cls._DROPOUT_RECOVERY_MAX_ATTEMPTS - 1)
        if not bool(getattr(params, "manual_params_enabled", False)):
            return default_rounds
        try:
            configured = int(getattr(params, "high_pitch_guard_rounds", default_rounds))
        except (TypeError, ValueError):
            configured = default_rounds
        return max(0, min(cls._MAX_HIGH_PITCH_GUARD_ROUNDS, configured))

    @classmethod
    def _guard_semitones_for_retry(
        cls,
        threshold: float,
        issue: dict[str, Any] | None = None,
        source: Path | None = None,
        regions: list[tuple[float, float]] | None = None,
    ) -> int:
        """Increase the protective drop only when a retry still misses high notes."""
        source_f0 = float((issue or {}).get("source_f0_hz") or 0.0)
        if source and regions:
            try:
                import numpy as np

                sidecar = source.with_name("f0.npy")
                if sidecar.is_file() and sidecar.stat().st_mtime >= source.stat().st_mtime - 120.0:
                    curve = np.asarray(np.load(str(sidecar), allow_pickle=False)).reshape(-1)
                    if curve.size >= 4:
                        with wave.open(str(source), "rb") as handle:
                            duration = handle.getnframes() / float(handle.getframerate() or 1)
                        times = np.linspace(0.0, duration, curve.size)
                        peaks: list[float] = []
                        for start, end in regions:
                            values = curve[(times >= start) & (times <= end)]
                            values = values[np.isfinite(values) & (values > 0.0)]
                            if values.size:
                                peaks.append(float(np.max(values)))
                        if peaks:
                            source_f0 = max(source_f0, max(peaks))
            except (OSError, ValueError, TypeError, ImportError):
                pass
        excess = source_f0 - float(threshold or cls._HIGH_PITCH_THRESHOLD)
        # A C6-ish note can sit more than an octave above an RVC model's
        # comfortable range. One fixed octave drop leaves the model rendering
        # a second low register, which is then shifted back into a thin,
        # breathy high note. Use a slightly larger preparation shift for these
        # extreme notes; ordinary high notes retain the previous values.
        if source_f0 >= 1100.0 or excess >= 420.0:
            return 15
        if source_f0 >= 950.0 or excess >= 220.0:
            return 12
        if source_f0 >= 780.0 or excess >= 80.0:
            return 9
        return cls._HIGH_PITCH_GUARD_SEMITONES

    @classmethod
    def _confirmed_guard_regions(
        cls,
        issue: dict[str, Any] | None,
        existing: list[tuple[float, float]] | None = None,
    ) -> list[tuple[float, float]] | None:
        """Keep confirmed regions and add only local note attack/release context."""
        raw: list[tuple[float, float]] = list(existing or [])
        for item in (issue or {}).get("bad_regions") or []:
            if not isinstance(item, dict):
                continue
            try:
                start = float(item.get("start", 0.0))
                end = float(item.get("end", 0.0))
            except (TypeError, ValueError):
                continue
            if end > start:
                raw.append(
                    (
                        max(0.0, start - cls._HIGH_PITCH_GUARD_CONTEXT_SECONDS),
                        end + cls._HIGH_PITCH_GUARD_CONTEXT_SECONDS,
                    )
                )
        if not raw:
            return None
        merged: list[tuple[float, float]] = []
        for start, end in sorted(raw):
            if end <= start:
                continue
            if merged and start <= merged[-1][1] + cls._HIGH_PITCH_GUARD_MERGE_GAP_SECONDS:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return merged or None

    @staticmethod
    def _dropout_core_regions(
        issue: dict[str, Any] | None,
        existing: list[tuple[float, float]] | None = None,
    ) -> list[tuple[float, float]] | None:
        """Return only measured dropout spans, without PSOLA context padding.

        Guard rendering needs attack/release context, but merging that context
        back into the baseline can replace healthy neighboring syllables. Keep
        the two scopes separate so retries cannot make a song worse.
        """
        raw: list[tuple[float, float]] = list(existing or [])
        for item in (issue or {}).get("bad_regions") or []:
            if not isinstance(item, dict):
                continue
            try:
                start = float(item.get("start", 0.0))
                end = float(item.get("end", 0.0))
            except (TypeError, ValueError):
                continue
            if end > start:
                raw.append((max(0.0, start), end))
        if not raw:
            return None
        merged: list[tuple[float, float]] = []
        for start, end in sorted(raw):
            if merged and start <= merged[-1][1] + 0.04:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return merged or None

    @staticmethod
    def _dropout_regions_overlap(
        issue: dict[str, Any] | None,
        regions: list[tuple[float, float]] | None,
    ) -> bool:
        """Return whether a detector result still touches a known failure.

        A guarded retry is allowed to replace the baseline only after the
        original failed span is gone.  Counting fewer detector frames alone
        is not sufficient: a thin/breathy PSOLA result can score better while
        leaving the swallowed syllable in place.
        """
        if not issue or not regions:
            return False
        for item in issue.get("bad_regions") or []:
            if not isinstance(item, dict):
                continue
            try:
                start = float(item.get("start", 0.0))
                end = float(item.get("end", 0.0))
            except (TypeError, ValueError):
                continue
            if end <= start:
                continue
            if any(end > left and start < right for left, right in regions):
                return True
        return False

    @staticmethod
    def _stable_high_pitch_mask(
        f0: object,
        strength: object,
        rms: object,
        high_floor: float,
        *,
        minimum_strength: float = 0.35,
        minimum_run_frames: int = 3,
    ) -> object:
        """Keep only high-pitch frames supported by a coherent local note.

        The lightweight autocorrelation probe can report a single upper
        harmonic as a 1-2 kHz fundamental for one frame. Those tracker spikes
        must not open a guarded retry. A real high note has nearby voiced
        frames at a comparable F0, so require both local pitch coherence and
        at least three high frames in a 100 ms neighborhood.
        """
        import numpy as np

        values = np.asarray(f0, dtype=np.float32)
        strengths = np.asarray(strength, dtype=np.float32)
        levels = np.asarray(rms, dtype=np.float32)
        if values.size == 0:
            return np.zeros(0, dtype=bool)
        candidate = (
            np.isfinite(values)
            & (values >= float(high_floor))
            & (strengths >= float(minimum_strength))
            & (levels >= 0.012)
        )
        if not np.any(candidate):
            return np.zeros(values.shape, dtype=bool)

        # Compare each estimate with the local voiced median. This rejects a
        # one-frame octave/upper-harmonic jump while allowing normal vibrato.
        voiced = (
            np.isfinite(values)
            & (values > 0.0)
            & (strengths >= 0.35)
            & (levels >= 0.008)
        )
        local_median = np.zeros_like(values, dtype=np.float32)
        half_window = 2
        for index in np.flatnonzero(voiced):
            start = max(0, int(index) - half_window)
            end = min(values.size, int(index) + half_window + 1)
            neighbors = values[start:end][voiced[start:end]]
            if neighbors.size >= 2:
                local_median[index] = float(np.median(neighbors))
        coherent = (
            (local_median > 0.0)
            & (values >= local_median * 0.55)
            & (values <= local_median * 1.80)
        )
        candidate &= coherent

        # A five-frame (100 ms) support window requires at least three
        # neighboring high frames. Use a zero-padded convolution so short
        # isolated spikes cannot pass at track boundaries either.
        support = np.convolve(
            candidate.astype(np.float32),
            np.ones(5, dtype=np.float32),
            mode="same",
        )
        supported = candidate & (support >= 3.0)
        minimum_run_frames = max(1, int(minimum_run_frames))
        if minimum_run_frames <= 1:
            return supported
        kept = np.zeros_like(supported, dtype=bool)
        for index, value in enumerate(
            np.concatenate((supported, np.array([False], dtype=bool)))
        ):
            if value and not kept[index]:
                end = index + 1
                while end < supported.size and supported[end]:
                    end += 1
                if end - index >= minimum_run_frames:
                    kept[index:end] = True
        return kept

    def __init__(
        self,
        repo: ListRepository,
        ffmpeg: FfmpegTool,
        uvr: UvrTool,
        engines: EngineRegistry,
        vocal_enhancement: VocalEnhancementProcessor | None = None,
        pymss: PymssTool | None = None,
    ) -> None:
        self._repo = repo
        self._ffmpeg = ffmpeg
        self._uvr = uvr
        self._pymss = pymss or PymssTool()
        self._engines = engines
        self._vocal_enhancement = vocal_enhancement or VocalEnhancementProcessor()
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
    def _enhancement_settings(
        work: dict[str, Any],
    ) -> tuple[bool, str, dict[str, float]]:
        raw = work.get("vocal_enhancement") or {}
        if not isinstance(raw, dict):
            return False, "basic", {
                "pitch_correction": 0.45,
                "timing_alignment": 0.45,
                "timbre_focus": 0.60,
                "ai_eq": 0.55,
                "ai_compressor": 0.45,
                "ai_exciter": 0.25,
                "stereo_width": 0.30,
                "loudness_envelope": 0.58,
            }
        level = str(raw.get("level") or "basic").strip().lower()
        if level not in VocalEnhancementProcessor.LEVELS:
            level = VocalEnhancementProcessor.LEVEL_BASIC

        def strength(key: str, default: float) -> float:
            try:
                value = float(raw.get(key, default))
            except (TypeError, ValueError):
                value = default
            if value != value:
                value = default
            return max(0.0, min(1.0, value))

        controls = {
            "pitch_correction": strength("pitch_correction", 0.45),
            "timing_alignment": strength("timing_alignment", 0.45),
            "timbre_focus": strength("timbre_focus", 0.60),
            "ai_eq": strength("ai_eq", 0.55),
            "ai_compressor": strength("ai_compressor", 0.45),
            "ai_exciter": strength("ai_exciter", 0.25),
            "stereo_width": strength("stereo_width", 0.30),
            "loudness_envelope": strength("loudness_envelope", 0.58),
        }
        if work.get("high_pitch_guard_applied"):
            # 防护装置已恢复高谐波。音色塑造控制部分被有意调至更轻，以保持受保护的辅音自然清晰。
            controls["timbre_focus"] *= 0.68
            controls["ai_eq"] *= 0.78
            controls["ai_compressor"] *= 0.82
            controls["ai_exciter"] *= 0.45
        return bool(raw.get("enabled")), level, controls

    @staticmethod
    def _preprocess_settings(work: dict[str, Any]) -> tuple[bool, str, str, bool, str]:
        raw = work.get("preprocess")
        if not isinstance(raw, dict):
            # Legacy records predate the option and retain their UVR behavior.
            raw = {"enabled": True, "engine": "uvr", "pymss_model": ""}
        enabled = raw.get("enabled", True) is not False
        engine = str(raw.get("engine") or "uvr").strip().lower()
        if engine not in {"uvr", "pymss"}:
            engine = "uvr"
        model = str(raw.get("pymss_model") or config.PYMSS_DEFAULT_MODEL).strip()
        harmony_enabled = bool(enabled and raw.get("harmony_removal_enabled"))
        harmony_model = str(
            raw.get("harmony_model") or config.PYMSS_DEFAULT_HARMONY_MODEL
        ).strip()
        return bool(enabled), engine, model, harmony_enabled, harmony_model

    def _repair_vocal(
        self,
        work: dict[str, Any],
        source: Path,
        output: Path,
        device: str,
        log_file: Path,
        *,
        stage: str,
        progress: int,
        reference: Path | None = None,
    ) -> tuple[Path, dict[str, float | bool]]:
        step_key = "repair_output" if stage == "output" else "repair_input"
        self._set_step(work, step_key, StepStatus.ACTIVE.value)
        self._save(work)
        profile: dict[str, float | bool] = {}
        repaired = source
        if not source.is_file():
            self._log(log_file, f"  AI 人声修复跳过：输入不存在 {source}")
        elif not self._vocal_enhancement.available:
            self._log(
                log_file,
                "  AI 人声修复跳过：DeepFilterNet3 环境未就绪（请修复 vocal 环境）",
            )
        else:
            stage_label = "模型输出" if stage == "output" else "分离干声"
            self._log(
                log_file,
                f"  {stage_label}进入 DeepFilterNet3 修复，并保护高频辅音与高音泛音",
            )
            try:
                profile = self._vocal_enhancement.analyze(source, log_file=log_file)
                repaired = self._vocal_enhancement.repair(
                    source,
                    output,
                    stage=stage,
                    device=device,
                    log_file=log_file,
                    profile=profile,
                    reference=reference,
                )
                self._log(log_file, f"  {stage_label}修复完成: {repaired}")
            except (OSError, RuntimeError, ValueError) as exc:
                self._log(log_file, f"  {stage_label}修复失败，沿用未修复人声: {exc}")
        repair_results = work.get("vocal_repair")
        if not isinstance(repair_results, dict):
            repair_results = {}
            work["vocal_repair"] = repair_results
        repair_results[stage] = {
            "model": "DeepFilterNet3",
            "input_path": str(source),
            "output_path": str(repaired),
            "applied": repaired != source,
            "profile": profile,
        }
        self._set_step(work, step_key, StepStatus.DONE.value)
        work["progress"] = progress
        self._save(work)
        return repaired, profile

    def _adapt_high_range(
        self,
        params: InferenceParams,
        profile: dict[str, float | bool],
        log_file: Path,
        framework: str = "",
    ) -> None:
        # The guard switch is also the opt-out for every automatic high-range
        # adjustment.  Previously disabling the selective pitch pass still
        # switched F0 extractors and tightened RVC protection, which could
        # produce a metallic/vibrato result even though the guard was off.
        if not params.auto_high_pitch_guard:
            self._log(log_file, "  高音保护已关闭：保留手动 F0、滤波半径和辅音保护参数")
            return
        if not params.manual_params_enabled:
            # Default mode must keep the engine's established F0/protection
            # defaults.  Advanced adaptation is opt-in through full parameters;
            # verified model dropouts are handled separately by retry logic.
            self._log(log_file, "  普通模式：保留默认 F0、滤波半径和辅音保护参数")
            return
        high_pitch = bool(profile.get("high_pitch"))
        high_frequency = bool(profile.get("high_frequency"))
        source_recommended = max(
            1100.0,
            min(1800.0, float(profile.get("recommended_f0_max") or 1100.0)),
        )
        model_limit = float(getattr(params, "high_pitch_threshold", 0.0) or 0.0)
        if model_limit > 0:
            # A declared model ceiling is authoritative, even for models whose
            # usable range is below the generic 600 Hz safety floor.
            recommended = max(300.0, min(source_recommended, model_limit))
        else:
            recommended = max(600.0, source_recommended)
        setattr(params, "adaptive_f0_max", recommended)
        normalized_framework = config.modelhub_normalize_framework(framework)
        current_method = str(params.f0_method or "rmvpe").lower()
        adaptive_method = current_method
        if high_pitch and normalized_framework == "so-vits-svc":
            fcpe_model = (config.SOVITS_REPO or config.SOVITS_REPO_DIR) / "pretrain" / "fcpe.pt"
            adaptive_method = "fcpe" if fcpe_model.is_file() else "crepe"
        elif high_pitch and normalized_framework == "ddsp-svc":
            adaptive_method = "fcpe"
        elif high_pitch and normalized_framework == "rvc":
            adaptive_method = "crepe"
        elif high_pitch and current_method not in {"rmvpe", "crepe", "fcpe"}:
            adaptive_method = "rmvpe"
        if adaptive_method != current_method:
            old_method = params.f0_method
            params.f0_method = adaptive_method
            self._log(
                log_file,
                f"  检测到高音域，F0 提取器由 {old_method or '默认'} 自动切换为 {adaptive_method}",
            )
        if high_pitch or high_frequency:
            params.filter_radius = min(int(params.filter_radius), 2)
            params.protect = min(float(params.protect), 0.28)
        self._log(
            log_file,
            "  自适应音域分析："
            f"F0 P95={float(profile.get('p95_f0_hz') or 0.0):.1f}Hz，"
            f"高频占比={float(profile.get('high_band_ratio') or 0.0):.1%}，"
            f"推理上限={recommended:.0f}Hz，"
            f"高音={'是' if high_pitch else '否'} / 高频={'是' if high_frequency else '否'}",
        )

    @staticmethod
    def _model_high_pitch_threshold(
        params: InferenceParams,
        model: dict[str, Any] | None,
        framework: str,
        *,
        honor_model_metadata: bool = False,
        fallback_threshold: float | None = None,
    ) -> float:
        """Resolve the guard boundary from the selected model, not one global constant.

        Imported model metadata wins, then common f0_max config keys, followed by
        conservative framework-specific defaults. A user supplied parameter is
        treated as an explicit override (0 means automatic).
        """
        explicit = float(getattr(params, "high_pitch_threshold", 0.0) or 0.0)
        if explicit > 0:
            return max(300.0, min(2000.0, explicit))
        if (
            not bool(getattr(params, "manual_params_enabled", False))
            and not honor_model_metadata
        ):
            # Without a model-declared usable range, preserve the legacy default
            # path.  Dropout recovery can lower this boundary only after it has
            # verified a real voiced model collapse.
            return ConversionService._HIGH_PITCH_THRESHOLD
        model = model or {}
        metadata = model.get("metadata") or model.get("model_metadata") or {}
        profile = metadata.get("inference_profile") if isinstance(metadata, dict) else None
        candidates: list[Any] = []
        if isinstance(profile, dict):
            candidates.extend([profile.get("high_pitch_threshold"), profile.get("f0_max_hz"), profile.get("f0_max")])
        if isinstance(metadata, dict):
            candidates.extend([metadata.get("high_pitch_threshold"), metadata.get("f0_max_hz"), metadata.get("f0_max")])
        config_path = str(
            model.get("main_config_path")
            or (model.get("main_config") or {}).get("path")
            or ""
        )
        if config_path:
            try:
                raw = Path(config_path).read_text(encoding="utf-8")
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        def visit(value: Any) -> None:
                            if isinstance(value, dict):
                                for key, child in value.items():
                                    if str(key).lower() in {"f0_max", "f0_max_hz", "max_f0"}:
                                        candidates.append(child)
                                    visit(child)
                            elif isinstance(value, list):
                                for child in value:
                                    visit(child)
                        visit(parsed)
                except (TypeError, ValueError):
                    for key in ("f0_max", "f0_max_hz", "max_f0"):
                        match = re.search(rf"(?:^|\n)\s*{key}\s*:\s*([0-9]+(?:\.[0-9]+)?)", raw, re.I)
                        if match:
                            candidates.append(match.group(1))
            except OSError:
                pass
        for value in candidates:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if 300.0 <= number <= 2000.0:
                return number
        defaults = {
            "rvc": 760.0,
            "seed-vc": 980.0,
            "ddsp-svc": 1040.0,
            "so-vits-svc": 1120.0,
        }
        if fallback_threshold is not None:
            return max(300.0, min(2000.0, float(fallback_threshold)))
        return defaults.get(config.modelhub_normalize_framework(framework), 1000.0)

    def _prepare_high_pitch_guard(
        self,
        source: Path,
        destination: Path,
        params: InferenceParams,
        log_file: Path,
        threshold: float | None = None,
        only_regions: list[tuple[float, float]] | None = None,
        semitones: int | None = None,
    ) -> tuple[Path, bool]:
        """Prepare a selective high-note pitch guard for normal AI covers."""
        if not params.auto_high_pitch_guard or not source.is_file():
            return source, False
        peak_f0 = self._estimate_peak_f0(source)
        high_threshold = float(threshold or getattr(params, "high_pitch_threshold", 0.0) or self._HIGH_PITCH_THRESHOLD)
        if peak_f0 < high_threshold and not only_regions:
            return source, False
        report_path = destination.with_suffix(".regions.json")
        shift_semitones = int(semitones or self._HIGH_PITCH_GUARD_SEMITONES)
        try:
            guard_ok = self._ffmpeg.pitch_shift(
                source,
                destination,
                -shift_semitones,
                mask_source=source,
                loudness_source=source,
                high_threshold=high_threshold,
                report_path=report_path,
                regions=only_regions,
            )
        except TypeError:
            if only_regions:
                self._log(log_file, "  当前高音保护组件不支持失配区间限制，跳过本次保护以保留原始结果")
                return source, False
            # Keep compatibility with older in-process tool doubles and
            # installations whose frozen ffmpeg wrapper predates region reports.
            guard_ok = self._ffmpeg.pitch_shift(
                source,
                destination,
                -shift_semitones,
                mask_source=source,
                loudness_source=source,
                high_threshold=high_threshold,
            )
        if not guard_ok:
            self._log(log_file, f"  高音保护降调失败，沿用原始推理输入（峰值 F0={peak_f0:.1f}Hz）")
            return source, False
        region_count = 0
        processed_seconds = 0.0
        region_preview = ""
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            region_count = int(report.get("region_count") or 0)
            processed_seconds = float(report.get("processed_seconds") or 0.0)
            regions = report.get("regions") or []
            region_preview = ", ".join(
                f"{float(item['start']):.2f}-{float(item['end']):.2f}s"
                for item in regions[:6]
                if isinstance(item, dict)
            )
            if len(regions) > 6:
                region_preview += ", ..."
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
        if region_count <= 0:
            self._log(log_file, "  高音保护未找到稳定高音区：整轨原样保留")
            return source, False
        self._log(
            log_file,
            f"  高音保护已启用：仅处理 {region_count} 个高音区，共 {processed_seconds:.2f}s "
            f"（阈值 {high_threshold:.0f}Hz，降调 -{shift_semitones} 半音；"
            f"区间 {region_preview}）",
        )
        return destination, True

    def _restore_high_pitch_guard(
        self,
        source: Path,
        destination: Path,
        original: Path,
        params: InferenceParams,
        log_file: Path,
        threshold: float | None = None,
        only_regions: list[tuple[float, float]] | None = None,
        semitones: int | None = None,
    ) -> Path:
        if not params.auto_high_pitch_guard:
            return source
        restored = destination
        shift_semitones = int(semitones or self._HIGH_PITCH_GUARD_SEMITONES)
        try:
            restore_ok = self._ffmpeg.pitch_shift(
                source,
                destination,
                shift_semitones,
                mask_source=original,
                # Match the restored guard to the model render's local
                # loudness. Using the dry vocal here can amplify a breathy
                # retry by several dB and turn the PSOLA air band into a
                # whistle; the dry track is still used only for the pitch mask.
                loudness_source=source,
                high_threshold=float(threshold or getattr(params, "high_pitch_threshold", 0.0) or self._HIGH_PITCH_THRESHOLD),
                report_path=destination.with_suffix(".regions.json"),
                regions=only_regions,
            )
        except TypeError:
            if only_regions:
                self._log(log_file, "  当前高音恢复组件不支持失配区间限制，跳过恢复以保留模型输出")
                return source
            restore_ok = self._ffmpeg.pitch_shift(
                source,
                destination,
                shift_semitones,
                mask_source=original,
                loudness_source=source,
                high_threshold=float(threshold or getattr(params, "high_pitch_threshold", 0.0) or self._HIGH_PITCH_THRESHOLD),
            )
        if restore_ok:
            self._log(log_file, "  高音保护完成：仅对记录的高音区域升回原调并补偿响度")
            return restored
        self._log(log_file, "  高音保护升调失败，沿用模型输出")
        return source

    @staticmethod
    def _merge_guarded_regions(
        baseline: Path,
        guarded: Path,
        destination: Path,
        report_path: Path,
        only_regions: list[tuple[float, float]] | None = None,
    ) -> Path:
        """ 
        保留基础渲染，除已确认失败的高音区。
        """
        try:
            import numpy as np

            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                report = None
            regions = report.get("regions") if isinstance(report, dict) else None
            if not isinstance(regions, list) or not regions:
                # The caller's confirmed dropout scope is a valid fallback for
                # older workers that predate region reports. It still keeps the
                # merge local; without an explicit scope there is no safe way
                # to know which samples the guarded render changed.
                if only_regions:
                    regions = [
                        {"start": float(start), "end": float(end)}
                        for start, end in only_regions
                        if float(end) > float(start)
                    ]
                if not regions:
                    return guarded
            selected_regions: list[tuple[float, float]] = []
            for item in regions:
                if not isinstance(item, dict):
                    continue
                start = float(item.get("start", 0.0))
                end = float(item.get("end", start))
                if end <= start:
                    continue
                if only_regions:
                    # ``regions`` comes from the formant worker and describes
                    # the complete high note that was actually lowered and
                    # restored. ``only_regions`` contains detector cores, which
                    # are often just a few bad frames in the middle of that
                    # note. Clipping the merge to their intersection leaves the
                    # attack/release from the failed baseline in place and can
                    # turn a recovered note back into an audible breath seam.
                    if any(
                        end > bad_start and start < bad_end
                        for bad_start, bad_end in only_regions
                    ):
                        selected_regions.append((start, end))
                else:
                    selected_regions.append((start, end))
            merged_regions: list[tuple[float, float]] = []
            for start, end in sorted(selected_regions):
                if merged_regions and start <= merged_regions[-1][1] + 0.01:
                    merged_regions[-1] = (
                        merged_regions[-1][0],
                        max(merged_regions[-1][1], end),
                    )
                else:
                    merged_regions.append((start, end))
            selected_regions = merged_regions
            if not selected_regions:
                return baseline
            with wave.open(str(baseline), "rb") as base_wave:
                base_params = base_wave.getparams()
                base_raw = base_wave.readframes(base_wave.getnframes())
            with wave.open(str(guarded), "rb") as guarded_wave:
                guarded_params = guarded_wave.getparams()
                guarded_raw = guarded_wave.readframes(guarded_wave.getnframes())
            if (
                base_params.sampwidth != 2
                or guarded_params.sampwidth != 2
                or base_params.nchannels != guarded_params.nchannels
                or base_params.framerate != guarded_params.framerate
            ):
                return guarded
            channels = max(1, int(base_params.nchannels))
            base_values = np.frombuffer(base_raw, dtype="<i2").copy()
            guarded_values = np.frombuffer(guarded_raw, dtype="<i2").copy()
            base_frames = base_values.size // channels
            guarded_frames = guarded_values.size // channels
            if base_frames <= 0 or guarded_frames <= 0:
                return guarded
            count = min(base_frames, guarded_frames)
            base_values = base_values[: count * channels].reshape(count, channels).astype(np.float64)
            guarded_values = guarded_values[: count * channels].reshape(count, channels).astype(np.float64)
            rate = float(base_params.framerate)
            mask = np.zeros(count, dtype=np.float64)
            fade = max(1, int(round(rate * 0.08)))
            duration = count / rate
            for raw_start, raw_end in selected_regions:
                start = max(0.0, min(duration, raw_start))
                end = max(start, min(duration, raw_end))
                left = max(0, min(count, int(round(start * rate))))
                right = max(left, min(count, int(round(end * rate))))
                if right <= left:
                    continue
                mask[left:right] = 1.0
                left_edge = max(0, left - fade)
                if left > left_edge:
                    phase = np.linspace(0.0, np.pi / 2.0, left - left_edge, endpoint=False)
                    mask[left_edge:left] = np.maximum(mask[left_edge:left], np.sin(phase) ** 2)
                right_edge = min(count, right + fade)
                if right_edge > right:
                    phase = np.linspace(np.pi / 2.0, 0.0, right_edge - right, endpoint=False)
                    mask[right:right_edge] = np.maximum(mask[right:right_edge], np.sin(phase) ** 2)
            if not np.any(mask > 0.0):
                return guarded
            # The baseline is known to have collapsed in these regions, so it
            # is not a valid loudness ceiling for the recovered note. Candidate
            # air/whistle rejection happens before publication in the shared
            # per-region quality gate below.
            merged = base_values * (1.0 - mask[:, None]) + guarded_values * mask[:, None]
            merged = np.clip(np.rint(merged), -32768, 32767).astype("<i2")
            if guarded_frames < base_frames:
                # A truncated retry must never truncate the user's baseline.
                merged = np.concatenate(
                    (merged, np.frombuffer(base_raw, dtype="<i2")[count * channels : base_frames * channels].reshape(-1, channels)),
                    axis=0,
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(destination), "wb") as output_wave:
                output_wave.setparams(base_params)
                output_wave.writeframes(merged.reshape(-1).tobytes())
            return destination if destination.exists() else guarded
        except (
            OSError,
            EOFError,
            TypeError,
            ValueError,
            wave.Error,
            json.JSONDecodeError,
        ):
            return guarded

    @staticmethod
    def _read_mono_audio(source: Path, target_rate: int = 16000):
        """读取 PCM WAV 为单声道浮点数组，供模型输出质量探针使用。"""
        import numpy as np

        with wave.open(str(source), "rb") as handle:
            rate = int(handle.getframerate() or target_rate)
            channels = max(1, int(handle.getnchannels() or 1))
            width = int(handle.getsampwidth() or 2)
            raw = handle.readframes(handle.getnframes())
        if not raw or rate <= 0:
            return np.zeros(0, dtype=np.float32), target_rate
        if width == 1:
            audio = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
        elif width == 2:
            audio = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        elif width == 4:
            audio = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
        else:
            return np.zeros(0, dtype=np.float32), target_rate
        usable = (audio.size // channels) * channels
        if usable <= 0:
            return np.zeros(0, dtype=np.float32), target_rate
        audio = audio[:usable].reshape(-1, channels).mean(axis=1)
        if rate == target_rate:
            return audio.astype(np.float32, copy=False), target_rate
        count = max(1, round(audio.size * target_rate / rate))
        positions = np.linspace(0, audio.size - 1, count)
        return np.interp(positions, np.arange(audio.size), audio).astype(np.float32), target_rate

    @classmethod
    def _detect_model_dropout(
        cls,
        source: Path,
        output: Path,
        threshold: float,
        pitch: int = 0,
    ) -> dict[str, Any] | None:
        """当可用时，优先使用源侧F0边车，因为它传递给SVC的曲线与模型支持的曲线相同。除了输出被静音外，
            还应检测到一个高音源音符，其输出仍然具有能量，但失去了预期的基频；这是音符塌陷为低次谐波时常见的“哑音”故障模式。
        """
        try:
            import numpy as np

            source_audio, rate = cls._read_mono_audio(source)
            output_audio, output_rate = cls._read_mono_audio(output)
            if source_audio.size < 1024 or output_audio.size < 1024 or rate != output_rate:
                return None
            size = min(source_audio.size, output_audio.size)
            source_audio = source_audio[:size]
            output_audio = output_audio[:size]
            frame = max(512, int(rate * 0.04))
            hop = max(256, int(rate * 0.02))
            if size < frame:
                return None
            min_lag = max(2, int(rate / 2000.0))
            max_lag = min(frame - 2, int(rate / 60.0))
            if max_lag <= min_lag + 2:
                return None
            source_frames = np.lib.stride_tricks.sliding_window_view(source_audio, frame)[::hop]
            output_frames = np.lib.stride_tricks.sliding_window_view(output_audio, frame)[::hop]
            if source_frames.size == 0 or output_frames.size == 0:
                return None
            source_frames = source_frames[: len(output_frames)]
            output_frames = output_frames[: len(source_frames)]
            source_frames = source_frames - source_frames.mean(axis=1, keepdims=True)
            output_frames = output_frames - output_frames.mean(axis=1, keepdims=True)
            source_rms = np.sqrt(np.mean(source_frames * source_frames, axis=1))
            output_rms = np.sqrt(np.mean(output_frames * output_frames, axis=1))
            def estimate_pitch(
                frames: object,
                rms: object,
                indices: object,
            ) -> tuple[object, object]:
                pitch_values = np.zeros(len(rms), dtype=np.float32)
                pitch_strength = np.zeros(len(rms), dtype=np.float32)
                selected = np.asarray(indices, dtype=np.int64)
                selected = selected[np.asarray(rms)[selected] >= 0.008]
                if selected.size == 0:
                    return pitch_values, pitch_strength
                valid_frames = np.asarray(frames)[selected]
                fft_size = 1 << max(10, (2 * frame - 1).bit_length())
                spectrum = np.fft.rfft(valid_frames, n=fft_size, axis=1)
                autocorr = np.fft.irfft(spectrum * np.conj(spectrum), n=fft_size, axis=1)[:, : frame]
                bases = autocorr[:, 0]
                lag_window = autocorr[:, min_lag : max_lag + 1]
                lag_offsets = np.argmax(lag_window, axis=1)
                lags = lag_offsets + min_lag
                best = lag_window[np.arange(lag_window.shape[0]), lag_offsets]
                valid_base = bases > 0.0
                strengths = np.zeros_like(best, dtype=np.float32)
                strengths[valid_base] = best[valid_base] / bases[valid_base]
                # Autocorrelation can lock to a strong upper harmonic instead
                # of the singer's fundamental. This is especially common in a
                # separated vocal with bright consonants: a 150 Hz note may be
                # reported as 1.5-1.7 kHz. When a lower periodic candidate has
                # comparable support, prefer it for guard decisions. Restrict
                # this correction to very high, low-confidence candidates so
                # genuine 700-1100 Hz notes keep their measured F0.
                low_min_lag = max(min_lag, int(rate / 500.0))
                low_max_lag = min(max_lag, int(rate / 60.0))
                if low_max_lag > low_min_lag:
                    low_window = autocorr[:, low_min_lag : low_max_lag + 1]
                    low_offsets = np.argmax(low_window, axis=1)
                    low_lags = low_offsets + low_min_lag
                    low_best = low_window[
                        np.arange(low_window.shape[0]), low_offsets
                    ]
                    low_strengths = np.zeros_like(low_best, dtype=np.float32)
                    low_strengths[valid_base] = (
                        low_best[valid_base] / bases[valid_base]
                    )
                    high_frequencies = rate / np.maximum(lags, 1)
                    harmonic_candidate = (
                        (high_frequencies >= 1200.0)
                        & (strengths < 0.78)
                        & (low_strengths >= np.maximum(0.42, strengths * 0.70))
                        & (rate / np.maximum(low_lags, 1) <= 500.0)
                    )
                    lags[harmonic_candidate] = low_lags[harmonic_candidate]
                    strengths[harmonic_candidate] = low_strengths[
                        harmonic_candidate
                    ]
                f0_values = np.zeros_like(strengths, dtype=np.float32)
                reliable = (strengths >= 0.35) & (lags > 0)
                f0_values[reliable] = rate / lags[reliable].astype(np.float32)
                pitch_values[selected] = f0_values
                pitch_strength[selected] = strengths
                return pitch_values, pitch_strength

            all_indices = np.arange(source_frames.shape[0], dtype=np.int64)
            f0, strength = estimate_pitch(source_frames, source_rms, all_indices)
            # Keep the waveform-based estimate before applying the persisted F0
            # curve.  Some extractors lock onto a bright upper harmonic (for
            # example 1.6 kHz while the local fundamental is about 150 Hz).
            # That is not a singer high note and must not open the PSOLA guard.
            fallback_f0 = f0.copy()

            # F0 extraction already ran immediately before SVC and is more
            # reliable than a second lightweight autocorrelation pass on loud
            # high harmonics.  Interpolate its time-aligned values to detector
            # frames when this is one of the standard inference inputs.
            source_f0_sidecar_loaded = False
            source_uses_standard_f0_input = source.name.lower() in {
                "infer_input.wav",
                "vocals_repaired.wav",
            }
            if source_uses_standard_f0_input:
                sidecar = source.with_name("f0.npy")
                try:
                    if sidecar.stat().st_mtime >= source.stat().st_mtime - 120.0:
                        curve = np.asarray(np.load(str(sidecar), allow_pickle=False)).reshape(-1)
                        finite = np.isfinite(curve) & (curve > 0.0)
                        valid_curve = np.flatnonzero(finite)
                        if valid_curve.size >= 4:
                            curve_times = np.linspace(
                                0.0,
                                size / float(rate),
                                curve.size,
                            )
                            frame_times = (
                                np.arange(f0.size, dtype=np.float64) * hop
                                + frame * 0.5
                            ) / float(rate)
                            sidecar_f0 = np.interp(
                                frame_times,
                                curve_times[valid_curve],
                                curve[valid_curve],
                            )
                            sidecar_valid = (
                                (frame_times >= curve_times[valid_curve[0]])
                                & (frame_times <= curve_times[valid_curve[-1]])
                            )
                            # Accept a sidecar value when the local waveform
                            # agrees, or when autocorrelation has no usable
                            # estimate.  A large sidecar/fallback ratio is the
                            # characteristic upper-harmonic false positive;
                            # leaving the fallback value in place keeps the
                            # normal (unguarded) RVC render untouched.
                            fallback_valid = (
                                np.isfinite(fallback_f0) & (fallback_f0 > 0.0)
                            )
                            sidecar_outlier = fallback_valid & (
                                (sidecar_f0 > fallback_f0 * 2.60)
                                | (
                                    (sidecar_f0 >= 1200.0)
                                    & (fallback_f0 < 500.0)
                                )
                            )
                            sidecar_apply = sidecar_valid & ~sidecar_outlier
                            f0[sidecar_apply] = sidecar_f0[sidecar_apply]
                            strength[sidecar_apply] = np.maximum(
                                strength[sidecar_apply],
                                0.8,
                            )
                            source_f0_sidecar_loaded = bool(
                                np.count_nonzero(sidecar_apply) >= 4
                            )
                except (OSError, ValueError, TypeError):
                    pass

            # 也略微低于活跃防护边界。一个短音节可以刚好位于边界之下，但仍属于需要更低重试阈值的模型不匹配音符。
            active_threshold = float(threshold or 760.0)
            high_floor = max(
                cls._DROPOUT_RECOVERY_MIN_THRESHOLD,
                active_threshold - max(70.0, active_threshold * 0.08),
            )
            # If an old/cached work directory has no F0 sidecar, the fallback
            # autocorrelation is intentionally conservative: it is useful for
            # ordinary custom WAVs, but must not treat a repaired high-frequency
            # transient in infer_input.wav as a genuine singer note.
            source_min_strength = (
                0.35
                if not source_uses_standard_f0_input or source_f0_sidecar_loaded
                else 0.62
            )
            source_min_run_frames = (
                3
                if not source_uses_standard_f0_input or source_f0_sidecar_loaded
                else 4
            )
            high_voice = cls._stable_high_pitch_mask(
                f0,
                strength,
                source_rms,
                high_floor,
                minimum_strength=source_min_strength,
                minimum_run_frames=source_min_run_frames,
            )

            '''
            型渲染的增益不一定与分离的语音部分具有相同的全局增益。从发声帧估计出的增益，
            使得整体更安静（但其他方面仍然有效）的渲染结果不会被误认为是局部静音，
            并通过一个有害的保护重试机制发送。对于本地静音并经由破坏性守卫发送的重试
            '''
            voiced = (source_rms >= 0.008) & (strength >= 0.35)
            ratios = output_rms[voiced] / np.maximum(source_rms[voiced], 1e-5)
            ratios = ratios[np.isfinite(ratios) & (ratios > 0.0)]
            reference_gain = 1.0
            if ratios.size >= 8:
                reference_gain = float(np.median(ratios))
            dropout_ratio = max(0.04, min(1.0, reference_gain * 0.18))
            # A breathy high note can retain a trackable F0 while losing much
            # of its vocal support. Detect that local loss relative to the
            # song's normal gain, but keep the lower boundary well above
            # ordinary speech so normal quiet phrases are untouched.
            near_high_floor = max(
                cls._DROPOUT_RECOVERY_MIN_THRESHOLD,
                active_threshold - max(180.0, active_threshold * 0.18),
            )
            near_high_voice = cls._stable_high_pitch_mask(
                f0,
                strength,
                source_rms,
                near_high_floor,
                minimum_strength=source_min_strength,
                minimum_run_frames=source_min_run_frames,
            ) & (source_rms >= 0.025)
            soft_support_ratio = max(0.12, min(0.68, reference_gain * 0.62))
            soft_breathy = near_high_voice & (
                output_rms < source_rms * soft_support_ratio
            ) & (reference_gain >= 0.35)
            '''
            音调崩溃在失去高音时仍可能保持响亮。
            仅对源的高音帧估计输出F0，以限制内存和误报。
            '''
            high_indices = np.flatnonzero(high_voice)
            output_f0, output_strength = estimate_pitch(
                output_frames,
                output_rms,
                high_indices,
            )
            # A collapsed high note is often still loud enough to pass the
            # ordinary energy test.  In that case the output contains a weak
            # low partial plus broadband air, so a pitch-only test is too easy
            # to miss.  Measure the air band only on source-confirmed high
            # frames; this keeps unrelated accompaniment/transient energy out
            # of the decision and never copies that band into the render.
            output_high_ratio = np.zeros_like(output_rms, dtype=np.float32)
            output_high_flatness = np.zeros_like(output_rms, dtype=np.float32)
            if high_indices.size:
                selected_frames = np.asarray(output_frames)[high_indices]
                fft_size = 1 << max(10, (2 * frame - 1).bit_length())
                spectrum = np.abs(
                    np.fft.rfft(
                        selected_frames * np.hanning(frame)[np.newaxis, :],
                        n=fft_size,
                        axis=1,
                    )
                ) ** 2
                frequencies = np.fft.rfftfreq(fft_size, 1.0 / float(rate))
                total_bins = (frequencies >= 120.0) & (
                    frequencies <= min(float(rate) * 0.48, 7600.0)
                )
                air_bins = (frequencies >= 3800.0) & (
                    frequencies <= min(float(rate) * 0.48, 7600.0)
                )
                if bool(total_bins.any() and air_bins.any()):
                    total_power = np.sum(spectrum[:, total_bins], axis=1)
                    air_power = np.maximum(spectrum[:, air_bins], 1e-14)
                    output_high_ratio[high_indices] = (
                        np.sum(air_power, axis=1)
                        / np.maximum(total_power, 1e-12)
                    ).astype(np.float32)
                    output_high_flatness[high_indices] = (
                        np.exp(np.mean(np.log(air_power), axis=1))
                        / np.maximum(np.mean(air_power, axis=1), 1e-14)
                    ).astype(np.float32)
            expected_f0 = f0 * (2.0 ** (float(pitch or 0) / 12.0))
            # A zero F0 estimate is not sufficient evidence of a mute: Praat
            # can lose pitch tracking on a loud, breathy or harmonic-heavy
            # syllable while the rendered audio remains audible.  Require a
            # simultaneous local energy drop for the missing-F0 path, while
            # retaining non-zero but clearly wrong F0 as a real mismatch.
            pitch_missing = (output_strength < 0.25) | (output_f0 <= 0.0)
            pitch_missing_energy_limit = np.maximum(
                0.002,
                source_rms * max(dropout_ratio * 1.5, 0.12),
            )
            pitch_missing_with_mute = pitch_missing & (
                output_rms < pitch_missing_energy_limit
            )
            # The fallback autocorrelation probe is deliberately coarse on
            # RVC/legacy inputs without an F0 sidecar.  It commonly locks to
            # a lower harmonic (roughly 0.4x) even when the rendered note is
            # musical.  Treat only a clear collapse as a mismatch in that
            # mode; sidecar-backed curves retain the more sensitive boundary.
            lower_pitch_ratio = 0.45 if source_f0_sidecar_loaded else 0.32
            pitch_wrong = (output_f0 > 0.0) & (
                (output_f0 < expected_f0 * lower_pitch_ratio)
                | (output_f0 > expected_f0 * 2.20)
            )
            # This is the audible "唱不上去" failure mode: the output is not
            # muted, but its periodic support drops sharply and its measured
            # pitch either disappears or falls well below the source note.
            # Require two independent air/voicing clues so a clean lower
            # harmonic or a bright but tonal consonant is not retried.
            audible_limit = np.maximum(
                0.006,
                source_rms * max(0.18, reference_gain * 0.20),
            )
            audible_breathy = output_rms >= audible_limit
            weak_periodic_support = (
                (output_strength <= np.minimum(0.58, strength * 0.72))
                & (output_strength <= 0.52)
            )
            collapsed_pitch = (output_f0 <= 0.0) | (
                output_f0 < expected_f0 * 0.70
            )
            air_evidence = (
                (
                    (output_high_ratio >= 0.018)
                    & (output_high_flatness >= 0.08)
                )
                | (output_strength <= 0.34)
            )
            breathy_pitch_collapse = high_voice & (strength >= 0.58) & audible_breathy & (
                weak_periodic_support & collapsed_pitch & air_evidence
            )
            energy_dropout = output_rms < np.maximum(
                0.0015,
                source_rms * dropout_ratio,
            )

            '''
            高音部分可以在发声帧和静音帧之间交替。
            使用短滑动窗口以及连续的运行，以便这些短暂的中断仍能触发恢复，
            而无需将单个帧视为失败。
            '''
            min_frames = max(4, round(cls._DROPOUT_RECOVERY_MIN_DURATION / (hop / rate)))
            window_frames = max(min_frames, round(0.24 / (hop / rate)))

            def contiguous_runs(mask: object, minimum: int) -> list[tuple[int, int]]:
                values = np.asarray(mask, dtype=bool)
                runs: list[tuple[int, int]] = []
                begin: int | None = None
                for index, value in enumerate(
                    np.concatenate((values, np.array([False], dtype=bool)))
                ):
                    if value and begin is None:
                        begin = index
                    elif not value and begin is not None:
                        if index - begin >= minimum:
                            runs.append((begin, index))
                        begin = None
                return runs

            def bridge_short_gaps(mask: object, maximum_gap: int) -> object:
                values = np.asarray(mask, dtype=bool).copy()
                maximum_gap = max(0, int(maximum_gap))
                if maximum_gap <= 0 or values.size < 3:
                    return values
                false_runs = contiguous_runs(~values, 1)
                for start, end in false_runs:
                    if (
                        end - start <= maximum_gap
                        and start > 0
                        and end < values.size
                        and values[start - 1]
                        and values[end]
                    ):
                        values[start:end] = True
                return values

            # Bridge one unreliable 20 ms tracker frame, then require at least
            # 100 ms of simultaneous pitch and periodicity collapse. This keeps
            # consonants and isolated lower-harmonic estimates out of retries.
            breathy_min_frames = max(5, round(0.10 / (hop / rate)))
            breathy_pitch_confirmed = np.zeros_like(
                breathy_pitch_collapse,
                dtype=bool,
            )
            breathy_bridged = bridge_short_gaps(breathy_pitch_collapse, 1)
            for start, end in contiguous_runs(breathy_bridged, breathy_min_frames):
                breathy_pitch_confirmed[start:end] = True

            pitch_collapse = high_voice & (
                pitch_missing_with_mute | pitch_wrong | breathy_pitch_confirmed
            )
            core_bad = high_voice & (energy_dropout | pitch_collapse)

            # Require a sustained local support loss before treating an
            # audible, breathy phrase as a dropout. Very brief low-energy
            # consonants (such as the reported 54s span) stay untouched.
            soft_min_frames = max(4, round(0.16 / (hop / rate)))
            soft_breathy_confirmed = np.zeros_like(soft_breathy, dtype=bool)
            for start, end in contiguous_runs(soft_breathy, soft_min_frames):
                soft_breathy_confirmed[start:end] = True
            bad = core_bad | soft_breathy_confirmed

            candidates: list[tuple[int, int]] = []
            if high_voice.size >= window_frames:
                bad_windows = np.lib.stride_tricks.sliding_window_view(bad, window_frames).sum(axis=1)
                voice_windows = np.lib.stride_tricks.sliding_window_view(high_voice, window_frames).sum(axis=1)
                enough_voice = voice_windows >= min_frames
                enough_bad = bad_windows >= np.maximum(2, np.ceil(voice_windows * 0.25))
                starts = np.flatnonzero(enough_voice & enough_bad)
                for start in starts:
                    end = int(start + window_frames)
                    candidates.append((int(start), end))
            candidates.extend(contiguous_runs(soft_breathy_confirmed, min_frames))
            if not candidates:
                candidates = contiguous_runs(bad, min_frames)

            '''
           单个脱落音节通常比常规的120毫秒确认窗口更短。
           仅在接近无声的情况下接受此快速路径，并要求至少两个相邻的分析帧，
           以避免正常辅音间隙和颤音导致重试。
            '''
            short_ratio = max(0.025, min(0.12, reference_gain * 0.08))
            short_mute = high_voice & (
                output_rms < np.maximum(0.0008, source_rms * short_ratio)
            )
            short_min_frames = max(2, round(0.04 / (hop / rate)))
            short_candidates = contiguous_runs(short_mute, short_min_frames)
            candidates.extend(short_candidates)
            if not candidates:
                return None

            '''
           保留实际失败的帧用于区域合并。滑动窗口仅作为确认证据；使用其完整宽度会不必要地替换掉健康的相邻音节。
            '''
            confirmed_bad = np.zeros_like(bad, dtype=bool)
            for candidate_start, candidate_end in candidates:
                if (candidate_start, candidate_end) in short_candidates:
                    confirmed_bad[candidate_start:candidate_end] |= short_mute[
                        candidate_start:candidate_end
                    ]
                else:
                    confirmed_bad[candidate_start:candidate_end] |= bad[
                        candidate_start:candidate_end
                    ]
            confirmed_runs = contiguous_runs(confirmed_bad, 1)
            if not confirmed_runs:
                return None
            bad_regions: list[dict[str, float]] = []
            for candidate_start, candidate_end in confirmed_runs:
                region_start = max(0.0, candidate_start * hop / rate)
                region_end = min(
                    size / float(rate),
                    candidate_end * hop / rate + frame / rate,
                )
                if region_end <= region_start:
                    continue
                if bad_regions and region_start <= bad_regions[-1]["end"] + 0.12:
                    bad_regions[-1]["end"] = max(bad_regions[-1]["end"], region_end)
                else:
                    bad_regions.append({"start": region_start, "end": region_end})
            begin, end = confirmed_runs[0]
            f0_values = f0[begin:end]
            f0_values = f0_values[f0_values > 0]
            if f0_values.size == 0:
                return None
            output_f0_values = output_f0[begin:end]
            output_f0_values = output_f0_values[output_f0_values > 0]
            return {
                "start": round(begin * hop / rate, 3),
                "end": round(end * hop / rate + frame / rate, 3),
                "source_f0_hz": round(float(np.median(f0_values)), 1),
                "source_rms": round(float(np.median(source_rms[begin:end])), 5),
                "output_rms": round(float(np.median(output_rms[begin:end])), 5),
                "output_f0_hz": round(
                    float(np.median(output_f0_values))
                    if output_f0_values.size
                    else 0.0,
                    1,
                ),
                "output_high_ratio": round(
                    float(np.median(output_high_ratio[begin:end])),
                    4,
                ),
                "output_high_flatness": round(
                    float(np.median(output_high_flatness[begin:end])),
                    4,
                ),
                "source_periodicity": round(
                    float(np.median(strength[begin:end])),
                    4,
                ),
                "output_periodicity": round(
                    float(np.median(output_strength[begin:end])),
                    4,
                ),
                "bad_frames": float(np.sum(confirmed_bad)),
                "high_frames": float(np.sum(high_voice)),
                "bad_regions": bad_regions,
                "duration": round((end - begin) * hop / rate, 3),
            }
        except (OSError, ValueError, wave.Error, ImportError):
            return None

    @classmethod
    def _next_dropout_threshold(cls, current: float, issue: dict[str, float]) -> float:
        """Place the next guard boundary just below the failing note."""
        current = max(cls._DROPOUT_RECOVERY_MIN_THRESHOLD, float(current or 760.0))
        f0 = float(issue.get("source_f0_hz") or 0.0)
        step = max(35.0, current * 0.08)
        target = min(current - step, f0 - 20.0) if f0 > 0 else current - step
        target = max(cls._DROPOUT_RECOVERY_MIN_THRESHOLD, target)
        return round(target / 10.0) * 10.0

    @classmethod
    def _guard_candidate_has_new_hf_peak(
        cls,
        source: Path,
        baseline: Path,
        candidate: Path,
        regions: list[tuple[float, float]] | None,
    ) -> bool:
        """Reject a guarded retry that adds a narrow air-band whistle.

        High-note recovery is allowed to increase the musical fundamental and
        its harmonics.  A PSOLA failure, however, usually appears as a narrow
        5.6 kHz+ peak that is much louder than both the dry vocal and the
        unguarded render.  This inexpensive FFT check runs only on confirmed
        guard regions and leaves broad, supported high notes untouched.
        """
        try:
            import numpy as np

            if not regions:
                return False
            source_audio, rate = cls._read_mono_audio(source)
            baseline_audio, baseline_rate = cls._read_mono_audio(baseline)
            candidate_audio, candidate_rate = cls._read_mono_audio(candidate)
            if rate != baseline_rate or rate != candidate_rate or rate < 12000:
                return False
            count = min(len(source_audio), len(baseline_audio), len(candidate_audio))
            if count < 1024:
                return False
            source_audio = source_audio[:count]
            baseline_audio = baseline_audio[:count]
            candidate_audio = candidate_audio[:count]
            frame = max(256, int(round(rate * 0.020)))
            fft_size = 1 << max(10, (frame * 2 - 1).bit_length())
            frequencies = np.fft.rfftfreq(fft_size, 1.0 / float(rate))
            total_bins = (frequencies >= 120.0) & (frequencies <= rate * 0.48)
            air_bins = (frequencies >= 5600.0) & (
                frequencies <= min(10000.0, rate * 0.46)
            )
            if not bool(total_bins.any() and air_bins.any()):
                return False
            max_air_ratio = 0.0
            max_air_excess = 0.0
            whistle_frames = 0
            for raw_start, raw_end in regions:
                left = max(0, int(float(raw_start) * rate) - frame)
                right = min(count, int(float(raw_end) * rate) + frame)
                if right - left < frame:
                    continue
                for offset in range(left, right - frame + 1, frame):
                    window = np.hanning(frame)
                    def metrics(values: object) -> tuple[float, float, float]:
                        chunk = np.asarray(values, dtype=np.float64)
                        spectrum = np.abs(np.fft.rfft(chunk * window, n=fft_size)) ** 2
                        total = float(np.sum(spectrum[total_bins]) + 1e-12)
                        air = np.maximum(spectrum[air_bins], 1e-14)
                        air_power = float(np.sum(air))
                        flatness = float(
                            np.exp(np.mean(np.log(air))) / max(np.mean(air), 1e-14)
                        )
                        peak_share = float(np.max(air) / max(air_power, 1e-14))
                        return air_power / total, flatness, peak_share

                    source_ratio, _source_flatness, source_peak = metrics(
                        source_audio[offset : offset + frame]
                    )
                    baseline_ratio, _baseline_flatness, baseline_peak = metrics(
                        baseline_audio[offset : offset + frame]
                    )
                    candidate_ratio, candidate_flatness, candidate_peak = metrics(
                        candidate_audio[offset : offset + frame]
                    )
                    excess = candidate_ratio - max(source_ratio, baseline_ratio)
                    max_air_ratio = max(max_air_ratio, candidate_ratio)
                    max_air_excess = max(max_air_excess, excess)
                    if (
                        candidate_ratio >= 0.16
                        and excess >= 0.075
                        and candidate_flatness <= 0.12
                        and candidate_peak >= 0.16
                        and candidate_peak
                        >= max(0.16, max(source_peak, baseline_peak) * 1.35)
                    ):
                        whistle_frames += 1
            return bool(
                whistle_frames >= 2
                and max_air_ratio >= 0.19
                and max_air_excess >= 0.075
            )
        except (OSError, EOFError, ValueError, TypeError, wave.Error, ImportError):
            return False

    @classmethod
    def _guard_candidate_high_note_quality(
        cls,
        source: Path,
        baseline: Path,
        candidate: Path,
        regions: list[tuple[float, float]] | None,
        note_report_path: Path | None = None,
    ) -> dict[str, Any]:
        """Measure every original dropout independently.

        A track-wide median can hide one fully breathy syllable among many
        successful retries. Each detector core is therefore evaluated on its
        own. The worker report then groups those cores by complete musical note:
        one bad core rejects that whole note so attack/release are never taken
        from different RVC renders.
        """
        requested = [
            (max(0.0, float(start)), float(end))
            for start, end in (regions or [])
            if float(end) > max(0.0, float(start))
        ]
        result: dict[str, Any] = {
            "available": False,
            "passed": False,
            "regions": [],
            "accepted_regions": [],
            "failed_regions": requested,
        }
        if not requested:
            return result
        try:
            import numpy as np

            source_audio, rate = cls._read_mono_audio(source)
            baseline_audio, baseline_rate = cls._read_mono_audio(baseline)
            candidate_audio, candidate_rate = cls._read_mono_audio(candidate)
            if rate != baseline_rate or rate != candidate_rate or rate < 12000:
                return result
            count = min(len(source_audio), len(baseline_audio), len(candidate_audio))
            if count < 1024:
                return result
            source_audio = source_audio[:count]
            baseline_audio = baseline_audio[:count]
            candidate_audio = candidate_audio[:count]
            frame = max(512, int(round(rate * 0.040)))
            hop = max(256, frame // 2)
            fft_size = 1 << max(10, (frame * 2 - 1).bit_length())
            frequencies = np.fft.rfftfreq(fft_size, 1.0 / float(rate))
            body_bins = (frequencies >= 220.0) & (frequencies <= 3800.0)
            air_bins = (frequencies >= 4800.0) & (
                frequencies <= min(10000.0, rate * 0.46)
            )
            if not bool(body_bins.any() and air_bins.any()):
                return result
            lag_min = max(2, int(round(rate / 1800.0)))
            lag_max = min(frame - 2, int(round(rate / 90.0)))
            if lag_max <= lag_min + 2:
                return result
            window = np.hanning(frame)

            def metrics(
                values: object,
            ) -> tuple[float, float, float, float, float, float]:
                chunk = np.asarray(values, dtype=np.float64)
                chunk = chunk - float(np.mean(chunk))
                rms = float(np.sqrt(np.mean(np.square(chunk)) + 1e-12))
                spectrum = np.fft.rfft(chunk * window, n=fft_size)
                power = np.abs(spectrum) ** 2
                body = float(np.sum(power[body_bins]))
                air_values = np.maximum(power[air_bins], 1e-14)
                air = float(np.sum(air_values))
                air_flatness = float(
                    np.exp(np.mean(np.log(air_values)))
                    / max(np.mean(air_values), 1e-14)
                )
                autocorrelation = np.fft.irfft(power, n=fft_size)[:frame]
                base = max(float(autocorrelation[0]), 1e-12)
                lag_slice = np.maximum(
                    autocorrelation[lag_min : lag_max + 1],
                    0.0,
                )
                periodicity = float(np.max(lag_slice) / base)
                lag = lag_min + int(np.argmax(lag_slice))
                f0 = rate / float(max(1, lag)) if periodicity >= 0.25 else 0.0
                return body, air, periodicity, air_flatness, f0, rms

            region_results: list[dict[str, Any]] = []
            for raw_start, raw_end in requested:
                body_gains: list[float] = []
                body_support: list[float] = []
                baseline_periodicity: list[float] = []
                candidate_periodicity: list[float] = []
                source_f0: list[float] = []
                candidate_f0: list[float] = []
                baseline_air_share: list[float] = []
                candidate_air_share: list[float] = []
                source_air_share: list[float] = []
                candidate_air_flatness: list[float] = []
                source_rms_values: list[float] = []
                candidate_rms_values: list[float] = []
                rms_support: list[float] = []
                left = max(0, int(raw_start * rate) - frame // 2)
                right = min(count, int(raw_end * rate) + frame // 2)
                if right - left >= frame:
                    for offset in range(left, right - frame + 1, hop):
                        (
                            source_body,
                            source_air,
                            source_periodicity,
                            _,
                            source_pitch,
                            source_rms,
                        ) = metrics(source_audio[offset : offset + frame])
                        if source_body <= 1e-8 or source_periodicity < 0.25:
                            continue
                        (
                            base_body,
                            base_air,
                            base_periodicity,
                            _,
                            _,
                            _,
                        ) = metrics(baseline_audio[offset : offset + frame])
                        (
                            trial_body,
                            trial_air,
                            trial_periodicity,
                            trial_flatness,
                            trial_pitch,
                            trial_rms,
                        ) = metrics(candidate_audio[offset : offset + frame])
                        floor = max(source_body * 1e-7, 1e-12)
                        body_gains.append(
                            10.0
                            * np.log10(max(trial_body, floor) / max(base_body, floor))
                        )
                        body_support.append(
                            float(np.sqrt(max(trial_body, floor) / max(source_body, floor)))
                        )
                        baseline_periodicity.append(base_periodicity)
                        candidate_periodicity.append(trial_periodicity)
                        source_f0.append(source_pitch)
                        candidate_f0.append(trial_pitch)
                        source_air_share.append(
                            source_air / max(source_body + source_air, floor)
                        )
                        baseline_air_share.append(
                            base_air / max(base_body + base_air, floor)
                        )
                        candidate_air_share.append(
                            trial_air / max(trial_body + trial_air, floor)
                        )
                        candidate_air_flatness.append(trial_flatness)
                        source_rms_values.append(source_rms)
                        candidate_rms_values.append(trial_rms)
                        rms_support.append(trial_rms / max(source_rms, 1e-6))

                region_result: dict[str, Any] = {
                    "start": raw_start,
                    "end": raw_end,
                    "available": len(body_gains) >= 2,
                    "passed": False,
                }
                if len(body_gains) >= 2:
                    body_gain = np.asarray(body_gains, dtype=np.float64)
                    source_support = np.asarray(body_support, dtype=np.float64)
                    base_periodicity = np.asarray(
                        baseline_periodicity,
                        dtype=np.float64,
                    )
                    periodicity = np.asarray(candidate_periodicity, dtype=np.float64)
                    dry_pitch = np.asarray(source_f0, dtype=np.float64)
                    trial_pitch = np.asarray(candidate_f0, dtype=np.float64)
                    base_air = np.asarray(baseline_air_share, dtype=np.float64)
                    trial_air = np.asarray(candidate_air_share, dtype=np.float64)
                    dry_air = np.asarray(source_air_share, dtype=np.float64)
                    air_flatness = np.asarray(
                        candidate_air_flatness,
                        dtype=np.float64,
                    )
                    source_levels = np.asarray(source_rms_values, dtype=np.float64)
                    trial_levels = np.asarray(candidate_rms_values, dtype=np.float64)
                    level_support = np.asarray(rms_support, dtype=np.float64)
                    improved_fraction = float(np.mean(body_gain >= 0.75))
                    voiced_fraction = float(np.mean(periodicity >= 0.28))
                    median_base_air = float(np.median(base_air))
                    median_trial_air = float(np.median(trial_air))
                    median_dry_air = float(np.median(dry_air))
                    air_limit = max(
                        0.10,
                        median_base_air + 0.015,
                        median_dry_air + 0.025,
                    )
                    noisy_air = bool(
                        median_trial_air >= 0.14
                        and float(np.median(air_flatness)) >= 0.16
                        and median_trial_air > median_base_air + 0.01
                    )
                    pitch_comparable = (
                        (dry_pitch > 0.0)
                        & (trial_pitch > 0.0)
                        & (trial_pitch >= dry_pitch * 0.68)
                        & (trial_pitch <= dry_pitch * 1.45)
                    )
                    pitch_match_fraction = float(np.mean(pitch_comparable))
                    median_body_support = float(np.median(source_support))
                    median_level_support = float(np.median(level_support))
                    median_trial_level = float(np.median(trial_levels))
                    energy_floor = bool(
                        median_trial_level >= max(
                            0.0025,
                            float(np.median(source_levels)) * 0.14,
                        )
                        and median_level_support >= 0.14
                        and median_body_support >= 0.12
                    )
                    body_recovery = bool(
                        float(np.median(body_gain)) >= 0.90
                        and improved_fraction >= 0.45
                        and voiced_fraction >= 0.55
                        and pitch_match_fraction >= 0.35
                    )
                    periodicity_gain = periodicity - base_periodicity
                    tonal_recovery = bool(
                        float(np.median(body_gain)) >= -1.50
                        and float(np.mean(body_gain >= -3.0)) >= 0.65
                        and float(np.median(periodicity)) >= 0.62
                        and float(np.median(periodicity_gain)) >= 0.14
                        and float(np.mean(periodicity_gain >= 0.18)) >= 0.48
                        and pitch_match_fraction >= 0.52
                    )
                    # The failed baseline may contain a loud low partial or
                    # broadband rasp, so improvement relative to that file is
                    # not always meaningful. A candidate that independently
                    # has stable pitch, strong periodic support and a healthy
                    # fraction of the source note is already a real sung note.
                    # This path still rejects the reported pure-air tail: its
                    # periodicity and source-relative energy are both too low.
                    absolute_tonal_recovery = bool(
                        float(np.median(periodicity)) >= 0.72
                        and voiced_fraction >= 0.70
                        and pitch_match_fraction >= 0.52
                        and median_level_support >= 0.22
                        and median_body_support >= 0.22
                    )
                    passed = bool(
                        (
                            body_recovery
                            or tonal_recovery
                            or absolute_tonal_recovery
                        )
                        and energy_floor
                        and median_trial_air <= air_limit
                        and not noisy_air
                    )
                    region_result.update(
                        {
                            "passed": passed,
                            "body_gain_db": round(float(np.median(body_gain)), 3),
                            "body_support": round(median_body_support, 4),
                            "source_rms": round(float(np.median(source_levels)), 6),
                            "candidate_rms": round(median_trial_level, 6),
                            "rms_support": round(median_level_support, 4),
                            "baseline_periodicity": round(
                                float(np.median(base_periodicity)),
                                4,
                            ),
                            "candidate_periodicity": round(
                                float(np.median(periodicity)),
                                4,
                            ),
                            "source_f0_hz": round(float(np.median(dry_pitch)), 1),
                            "candidate_f0_hz": round(
                                float(np.median(trial_pitch[trial_pitch > 0.0]))
                                if bool(np.any(trial_pitch > 0.0))
                                else 0.0,
                                1,
                            ),
                            "pitch_match": round(pitch_match_fraction, 4),
                            "baseline_air_share": round(median_base_air, 5),
                            "candidate_air_share": round(median_trial_air, 5),
                            "air_limit": round(air_limit, 5),
                        }
                    )
                region_results.append(region_result)

            if not region_results or not all(
                bool(item.get("available")) for item in region_results
            ):
                result["regions"] = region_results
                return result

            note_regions: list[tuple[float, float]] = []
            if note_report_path is not None:
                try:
                    raw_report = json.loads(
                        note_report_path.read_text(encoding="utf-8")
                    )
                    for item in (
                        raw_report.get("regions", [])
                        if isinstance(raw_report, dict)
                        else []
                    ):
                        if not isinstance(item, dict):
                            continue
                        start = float(item.get("start", 0.0))
                        end = float(item.get("end", 0.0))
                        if end > start:
                            note_regions.append((start, end))
                except (OSError, TypeError, ValueError, json.JSONDecodeError):
                    pass
            if not note_regions:
                note_regions = list(requested)

            accepted_indices: set[int] = set()
            for note_start, note_end in note_regions:
                covered = [
                    index
                    for index, item in enumerate(region_results)
                    if float(item["end"]) > note_start
                    and float(item["start"]) < note_end
                ]
                if covered and all(
                    bool(region_results[index].get("passed")) for index in covered
                ):
                    accepted_indices.update(covered)
            accepted = [
                requested[index]
                for index in range(len(requested))
                if index in accepted_indices
            ]
            failed = [
                requested[index]
                for index in range(len(requested))
                if index not in accepted_indices
            ]
            result.update(
                {
                    "available": True,
                    "passed": not failed,
                    "regions": region_results,
                    "accepted_regions": accepted,
                    "failed_regions": failed,
                }
            )
            return result
        except (OSError, EOFError, ValueError, TypeError, wave.Error, ImportError):
            return result

    @classmethod
    def _guard_candidate_restores_high_note_body(
        cls,
        source: Path,
        baseline: Path,
        candidate: Path,
        regions: list[tuple[float, float]] | None,
    ) -> bool:
        """Backward-compatible boolean wrapper for the per-region quality gate."""
        quality = cls._guard_candidate_high_note_quality(
            source,
            baseline,
            candidate,
            regions,
        )
        return bool(quality.get("available") and quality.get("passed"))

    @staticmethod
    def _quality_failure_issue(
        quality: dict[str, Any],
        fallback: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Build retry evidence from immutable quality-gate failures."""
        failed = [
            (float(start), float(end))
            for start, end in (quality.get("failed_regions") or [])
            if float(end) > float(start)
        ]
        if not failed:
            return None
        metrics = [
            item
            for item in (quality.get("regions") or [])
            if isinstance(item, dict)
            and any(
                float(item.get("end", 0.0)) > start
                and float(item.get("start", 0.0)) < end
                for start, end in failed
            )
        ]
        issue = dict(fallback or {})
        source_f0 = [
            float(item.get("source_f0_hz") or 0.0)
            for item in metrics
            if float(item.get("source_f0_hz") or 0.0) > 0.0
        ]
        source_rms = [
            float(item.get("source_rms") or 0.0)
            for item in metrics
            if float(item.get("source_rms") or 0.0) > 0.0
        ]
        output_rms = [
            float(item.get("candidate_rms") or 0.0)
            for item in metrics
            if float(item.get("candidate_rms") or 0.0) > 0.0
        ]
        output_f0 = [
            float(item.get("candidate_f0_hz") or 0.0)
            for item in metrics
            if float(item.get("candidate_f0_hz") or 0.0) > 0.0
        ]
        issue.update(
            {
                "start": min(start for start, _ in failed),
                "end": max(end for _, end in failed),
                "bad_regions": [
                    {"start": start, "end": end} for start, end in failed
                ],
                "bad_frames": float(
                    sum(max(1, round((end - start) / 0.02)) for start, end in failed)
                ),
            }
        )
        if source_f0:
            issue["source_f0_hz"] = max(source_f0)
        if source_rms:
            issue["source_rms"] = sum(source_rms) / len(source_rms)
        if output_rms:
            issue["output_rms"] = sum(output_rms) / len(output_rms)
        if output_f0:
            issue["output_f0_hz"] = sum(output_f0) / len(output_f0)
        return issue

    def _run_residual_dropout_retry(
        self,
        *,
        run_inference: Any,
        source: Path,
        output: Path,
        baseline: Path,
        params: InferenceParams,
        log_file: Path,
        issue: dict[str, Any] | None,
        threshold: float,
        semitones: int,
        pitch: int,
        attempt: int,
    ) -> tuple[Path, dict[str, Any] | None, bool]:
        """Retry only the small residual regions left by the best render.

        A global retry can fix one high note while changing neighboring notes.
        At the end of the normal recovery ladder, use the detector's measured
        spans as a surgical scope and merge the result back into the best
        render.  The candidate is accepted only when it removes the residual
        detector result entirely; otherwise the previous best file is kept.
        """
        residual_regions = self._dropout_core_regions(issue)
        if not residual_regions:
            return baseline, issue, False
        total_seconds = sum(max(0.0, end - start) for start, end in residual_regions)
        if (
            len(residual_regions) > self._DROPOUT_RESIDUAL_MAX_REGIONS
            or total_seconds > self._DROPOUT_RESIDUAL_MAX_SECONDS
        ):
            return baseline, issue, False
        guard_regions = self._confirmed_guard_regions(issue)
        if not guard_regions:
            return baseline, issue, False

        residual_threshold = self._next_dropout_threshold(threshold, issue)
        residual_threshold = max(
            self._DROPOUT_RECOVERY_MIN_THRESHOLD,
            min(float(threshold), float(residual_threshold)),
        )
        residual_semitones = max(
            int(semitones or self._HIGH_PITCH_GUARD_SEMITONES),
            self._guard_semitones_for_retry(
                residual_threshold,
                issue,
                source,
                guard_regions,
            ),
        )
        raw_target = output.with_name(f"{output.stem}_dropout_retry{attempt}.wav")
        guarded_target = output.with_name(
            f"{output.stem}_high_guarded_retry{attempt}.wav"
        )
        guarded, guard_applied = self._prepare_high_pitch_guard(
            source,
            guarded_target,
            params,
            log_file,
            residual_threshold,
            guard_regions,
            residual_semitones,
        )
        if not guard_applied:
            return baseline, issue, False
        self._log(
            log_file,
            "  高音保护进入残留片段补偿：仅重试 "
            f"{len(residual_regions)} 个片段，共 {total_seconds:.2f}s "
            f"（阈值 {residual_threshold:.0f}Hz，降调 -{residual_semitones} 半音）",
        )
        run_inference(guarded, raw_target)
        restored_target = output.with_name(
            f"{output.stem}_restored_retry{attempt}.wav"
        )
        restored = self._restore_high_pitch_guard(
            raw_target,
            restored_target,
            source,
            params,
            log_file,
            residual_threshold,
            guard_regions,
            residual_semitones,
        )
        merged_target = output.with_name(
            f"{output.stem}_guarded_merged_retry{attempt}.wav"
        )
        candidate = self._merge_guarded_regions(
            baseline,
            restored,
            merged_target,
            restored_target.with_suffix(".regions.json"),
            only_regions=residual_regions,
        )
        if self._guard_candidate_has_new_hf_peak(
            source,
            baseline,
            candidate,
            residual_regions,
        ):
            self._log(
                log_file,
                "  残留高音片段补偿出现新的窄带高频峰，拒绝本轮结果并保留之前的最佳结果",
            )
            return baseline, issue, True
        candidate_issue = self._detect_model_dropout(
            source,
            candidate,
            threshold,
            pitch,
        )
        return candidate, candidate_issue, True

    def _infer_with_dropout_recovery(
        self,
        *,
        engine: Any,
        model: dict[str, Any],
        source: Path,
        output: Path,
        params: InferenceParams,
        duration: float,
        log_file: Path,
        allow_recovery: bool,
        infer: Any | None = None,
    ) -> tuple[Path, list[dict[str, Any]], bool]:
        """Run inference and retry only confirmed high-note model dropouts."""
        history: list[dict[str, Any]] = []
        rendered = output

        def run_inference(vocals: Path, target: Path) -> None:
            if infer is None:
                engine.infer(
                    model=model,
                    vocals=vocals,
                    out_path=target,
                    params=params,
                    duration=duration,
                    log_file=log_file,
                )
            else:
                infer(vocals, target)

        if not allow_recovery or not params.auto_high_pitch_guard:
            # Protection is an opt-in post-inference recovery path.  When it
            # is disabled, keep the original render path completely untouched
            # and do not emit a misleading recovery history entry.
            run_inference(source, output)
            return output, [], False

        threshold = max(self._DROPOUT_RECOVERY_MIN_THRESHOLD, float(params.high_pitch_threshold or 760.0))
        guard_rounds = self._high_pitch_guard_rounds(params)
        attempts = 1 + guard_rounds
        guard_applied_any = False
        guard_regions: list[tuple[float, float]] | None = None
        guard_semitones = self._HIGH_PITCH_GUARD_SEMITONES

        '''
        认路径必须与保护功能被禁用时完全一致。
        受保护的源代码会改变模型所看到的条件，
        因此将其应用于每首歌曲可能会降低整个渲染质量，
        即使不存在断音情况。请先运行普通输入，
        仅在确认高音部分已正确处理后，再支付防护/重试的代价。
        '''
        baseline_first = bool(allow_recovery and params.auto_high_pitch_guard)
        if baseline_first:
            run_inference(source, output)
            rendered = output
            issue = self._detect_model_dropout(
                source,
                rendered,
                threshold,
                int(getattr(params, "pitch", 0) or 0),
            )
            history.append(
                {
                    "attempt": 1,
                    "threshold": round(threshold, 1),
                    "issue": issue,
                    "guard_applied": False,
                    "input": "original",
                }
            )
            if issue is None:
                return rendered, history, False
            self._log(
                log_file,
                "  首次原始推理检测到模型失配哑音，启动局部高音保护重试："
                f"{issue['start']:.2f}-{issue['end']:.2f}s / "
                f"源 F0 {issue['source_f0_hz']:.0f}Hz / "
                f"输出 F0 {float(issue.get('output_f0_hz') or 0.0):.0f}Hz",
            )
            # The first confirmed failing note is already enough to lower the
            # next guard boundary.  Starting the first guarded retry at the
            # old boundary can leave a 700-800 Hz syllable unprotected.
            threshold = self._next_dropout_threshold(threshold, issue)
            params.high_pitch_threshold = threshold
            guard_regions = self._confirmed_guard_regions(issue)
            merge_regions = self._dropout_core_regions(issue)
            guard_semitones = self._guard_semitones_for_retry(
                threshold,
                issue,
                source,
                guard_regions,
            )
            if issue.get("bad_regions") and not params.manual_params_enabled:
                attempts = max(attempts, self._DROPOUT_RECOVERY_OFFLINE_MAX_ATTEMPTS)

        guard_attempts = max(0, attempts - 1) if baseline_first else attempts
        fallback = output if baseline_first else rendered
        best_render = fallback
        best_bad_frames = float("inf")
        best_guard_applied = False
        best_body_recovered = False
        best_issue: dict[str, Any] | None = None
        # Keep the first detector spans immutable for candidate selection. The
        # retry ladder may discover fewer spans, but it must not gradually
        # widen the replacement scope and then score that broader render as
        # the new baseline.
        initial_failure_regions = (
            self._dropout_core_regions(history[0].get("issue"))
            if baseline_first and history and history[0].get("issue")
            else None
        )
        unresolved_failure_regions = list(initial_failure_regions or [])
        if baseline_first and history and history[0].get("issue"):
            best_issue = history[0]["issue"]
            best_bad_frames = float(history[0]["issue"].get("bad_frames") or float("inf"))
        for guard_attempt in range(guard_attempts):
            attempt = guard_attempt + 1 if baseline_first else guard_attempt
            raw_target = (
                output.with_name(f"{output.stem}_dropout_retry{attempt}.wav")
            )
            guarded_target = output.with_name(f"{output.stem}_high_guarded_retry{attempt}.wav")
            guarded, guard_applied = self._prepare_high_pitch_guard(
                source,
                guarded_target,
                params,
                log_file,
                threshold,
                guard_regions,
                guard_semitones,
            )
            guard_applied_any = guard_applied_any or guard_applied
            run_inference(guarded, raw_target)
            rendered = raw_target
            if guard_applied:
                restored_target = output.with_name(f"{output.stem}_restored_retry{attempt}.wav")
                rendered = self._restore_high_pitch_guard(
                    raw_target,
                    restored_target,
                    source,
                    params,
                    log_file,
                    threshold,
                    guard_regions,
                    guard_semitones,
                )
                if baseline_first and rendered != output:
                    merged_target = output.with_name(f"{output.stem}_guarded_merged_retry{attempt}.wav")
                    merged = self._merge_guarded_regions(
                        output,
                        rendered,
                        merged_target,
                        restored_target.with_suffix(".regions.json"),
                        only_regions=merge_regions,
                    )
                    if merged != rendered:
                        rendered = merged
                        self._log(
                            log_file,
                            "  高音保护结果已按高音区合并：非高音区域沿用首次原始推理结果",
                        )
                    if self._guard_candidate_has_new_hf_peak(
                        source,
                        output,
                        rendered,
                        merge_regions,
                    ):
                        # Do not let a successful F0 detector result hide a
                        # new PSOLA air-band whistle. The following detector
                        # pass will keep the original dropout evidence and can
                        # try the next, less aggressive guarded round.
                        self._log(
                            log_file,
                            "  高音保护结果出现新的窄带高频峰，拒绝本轮保护并保留原始结果",
                        )
                        rendered = output
            issue = (
                self._detect_model_dropout(
                    source,
                    rendered,
                    threshold,
                    int(getattr(params, "pitch", 0) or 0),
                )
                if allow_recovery and params.auto_high_pitch_guard
                else None
            )
            entry: dict[str, Any] = {
                "attempt": len(history) + 1,
                "threshold": round(threshold, 1),
                "issue": issue,
                "guard_applied": guard_applied,
                "input": "high_guarded" if guard_applied else "original",
            }
            history.append(entry)
            quality = (
                self._guard_candidate_high_note_quality(
                    source,
                    fallback,
                    rendered,
                    initial_failure_regions,
                    restored_target.with_suffix(".regions.json")
                    if guard_applied
                    else None,
                )
                if baseline_first and rendered != fallback
                else {"available": False}
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
                    accepted_target = output.with_name(
                        f"{output.stem}_accepted_retry{attempt}.wav"
                    )
                    best_render = self._merge_guarded_regions(
                        best_render,
                        rendered,
                        accepted_target,
                        restored_target.with_suffix(".regions.json"),
                        only_regions=newly_accepted,
                    )
                    best_guard_applied = True
                    unresolved_failure_regions = [
                        (start, end)
                        for start, end in unresolved_failure_regions
                        if (round(float(start), 6), round(float(end), 6))
                        not in accepted_keys
                    ]
                    self._log(
                        log_file,
                        "  高音保护逐区验收通过 "
                        f"{len(newly_accepted)} 个初始失配区，已累计保留完整音符；"
                        f"仍需重试 {len(unresolved_failure_regions)} 个区",
                    )
                quality_issue = self._quality_failure_issue(
                    {
                        **quality,
                        "failed_regions": unresolved_failure_regions,
                    },
                    issue or best_issue,
                )
                entry["issue"] = quality_issue
                issue = quality_issue
                if issue is None:
                    self._log(
                        log_file,
                        "  高音保护逐区验收全部通过：每个初始失配区均恢复有声主体且未增加气声",
                    )
                    return best_render, history, best_guard_applied
                best_issue = issue
                best_bad_frames = float(issue.get("bad_frames") or float("inf"))
                best_body_recovered = False
                guard_regions = self._confirmed_guard_regions(issue)
                merge_regions = initial_failure_regions
                next_threshold = self._next_dropout_threshold(threshold, issue)
                entry["next_threshold"] = next_threshold
                if (
                    next_threshold >= threshold - 10.0
                    or guard_attempt >= guard_attempts - 1
                ):
                    self._log(
                        log_file,
                        "  高音保护逐区验收仍有 "
                        f"{len(unresolved_failure_regions)} 个区未通过；保留已验收音符，"
                        "未通过音符沿用首次原始推理结果",
                    )
                    return best_render, history, best_guard_applied
                self._log(
                    log_file,
                    "  高音保护逐区验收发现残留纯气声/弱主体："
                    f"{issue['start']:.2f}-{issue['end']:.2f}s，"
                    f"高音保护起点 {threshold:.0f}Hz → {next_threshold:.0f}Hz，"
                    "仅重试未通过音符",
                )
                guard_semitones = max(
                    guard_semitones,
                    self._guard_semitones_for_retry(
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
                return rendered, history, guard_applied_any
            if baseline_first:
                candidate_bad_frames = float(issue.get("bad_frames") or float("inf"))
                candidate_improved = candidate_bad_frames < best_bad_frames
                candidate_body_recovered = bool(
                    rendered != fallback
                    and self._guard_candidate_restores_high_note_body(
                        source,
                        fallback,
                        rendered,
                        initial_failure_regions,
                    )
                )
                entry["body_recovered"] = candidate_body_recovered
                # Keep the lowest-count candidate available as the input for a
                # later surgical residual retry.  It is not automatically the
                # final result: unresolved original spans are filtered below,
                # because a thinner/breathier render can score better while
                # leaving the swallowed syllable in place.
                candidate_keeps_original_failure = self._dropout_regions_overlap(
                    issue,
                    initial_failure_regions,
                )
                if candidate_improved and (
                    not candidate_keeps_original_failure or candidate_body_recovered
                ):
                    best_render = rendered
                    best_bad_frames = candidate_bad_frames
                    best_guard_applied = guard_applied
                    best_issue = issue
                    best_body_recovered = candidate_body_recovered
                if (
                    candidate_improved
                    and candidate_keeps_original_failure
                    and candidate_body_recovered
                ):
                    self._log(
                        log_file,
                        "  高音保护仍有少量残留检测帧，但有声主体已增强且未增加气声，保留为当前最佳结果",
                    )
                if (
                    candidate_improved
                    and candidate_keeps_original_failure
                    and not candidate_body_recovered
                ):
                    self._log(
                        log_file,
                        "  高音保护本轮仍触及原失配区，检测帧虽减少但音色可能变薄，拒绝替换原始结果",
                    )
                if guard_regions and issue.get("bad_regions"):
                    prior_guard_regions = guard_regions
                    overlaps_scope = any(
                        float(item.get("end", 0.0)) > start
                        and float(item.get("start", 0.0)) < end
                        for item in (issue.get("bad_regions") or [])
                        if isinstance(item, dict)
                        for start, end in prior_guard_regions
                    )
                    if not overlaps_scope:
                        self._log(
                            log_file,
                            "  新检测到的哑音位于本轮保护范围外，停止继续降低阈值并保留当前最佳结果",
                        )
                        return best_render, history, best_guard_applied
                    guard_regions = self._confirmed_guard_regions(
                        issue,
                        prior_guard_regions,
                    )
                    merge_regions = self._dropout_core_regions(
                        issue,
                        merge_regions,
                    )
            next_threshold = self._next_dropout_threshold(threshold, issue)
            entry["next_threshold"] = next_threshold
            if next_threshold >= threshold - 10.0 or guard_attempt >= guard_attempts - 1:
                if baseline_first:
                    if best_render != fallback and best_issue and best_issue.get("bad_regions"):
                        residual_render, residual_issue, residual_guard_applied = (
                            self._run_residual_dropout_retry(
                                run_inference=run_inference,
                                source=source,
                                output=output,
                                baseline=best_render,
                                params=params,
                                log_file=log_file,
                                issue=best_issue,
                                threshold=threshold,
                                semitones=guard_semitones,
                                pitch=int(getattr(params, "pitch", 0) or 0),
                                attempt=len(history),
                            )
                        )
                        if residual_guard_applied:
                            history.append(
                                {
                                    "attempt": len(history) + 1,
                                    "threshold": round(threshold, 1),
                                    "issue": residual_issue,
                                    "guard_applied": True,
                                    "input": "high_guarded_residual",
                                }
                            )
                            if residual_issue is None:
                                self._log(
                                    log_file,
                                    "  残留高音片段补偿成功：已保留其余区域的最佳推理结果",
                                )
                                return residual_render, history, True
                            residual_bad_frames = float(
                                residual_issue.get("bad_frames") or float("inf")
                            )
                            residual_failure_remains = self._dropout_regions_overlap(
                                residual_issue,
                                initial_failure_regions,
                            )
                            residual_body_recovered = bool(
                                residual_render != fallback
                                and self._guard_candidate_restores_high_note_body(
                                    source,
                                    fallback,
                                    residual_render,
                                    initial_failure_regions,
                                )
                            )
                            if residual_bad_frames < best_bad_frames and (
                                not residual_failure_remains
                                or residual_body_recovered
                            ):
                                best_render = residual_render
                                best_bad_frames = residual_bad_frames
                                best_guard_applied = True
                                best_issue = residual_issue
                                best_body_recovered = residual_body_recovered
                            else:
                                self._log(
                                    log_file,
                                    "  残留高音片段补偿未改善，继续使用之前的最佳结果",
                                )
                    best_failure_remains = self._dropout_regions_overlap(
                        best_issue,
                        initial_failure_regions,
                    )
                    if best_render != fallback and (
                        not best_failure_remains or best_body_recovered
                    ):
                        self._log(
                            log_file,
                            "  高音保护未完全消除哑音，但主体恢复通过质量检查，采用哑音帧更少的保护结果："
                            f"{best_bad_frames:.0f} 帧（首次 {float(history[0]['issue'].get('bad_frames') or 0.0):.0f} 帧）",
                        )
                        return best_render, history, best_guard_applied
                    if best_render != fallback and best_failure_remains:
                        self._log(
                            log_file,
                            "  高音保护候选仍包含首次失配区，放弃气声风险较高的候选并回退原始推理结果",
                        )
                    self._log(
                        log_file,
                        "  高音保护重试仍检测到模型失配哑音，回退到首次原始推理结果："
                        f"{issue['start']:.2f}-{issue['end']:.2f}s / "
                        f"源 F0 {issue['source_f0_hz']:.0f}Hz / "
                        f"输出 F0 {float(issue.get('output_f0_hz') or 0.0):.0f}Hz",
                    )
                    return fallback, history, False
                self._log(
                    log_file,
                    "  模型失配哑音仍未消除："
                    f"{issue['start']:.2f}-{issue['end']:.2f}s / "
                    f"源 F0 {issue['source_f0_hz']:.0f}Hz，保留最后一次推理结果",
                )
                return rendered, history, guard_applied_any
            self._log(
                log_file,
                "  检测到模型失配哑音："
                f"{issue['start']:.2f}-{issue['end']:.2f}s / "
                f"源 F0 {issue['source_f0_hz']:.0f}Hz / "
                f"输出 F0 {float(issue.get('output_f0_hz') or 0.0):.0f}Hz，"
                f"高音保护起点 {threshold:.0f}Hz → {next_threshold:.0f}Hz，重新推理",
            )
            guard_semitones = max(
                guard_semitones,
                self._guard_semitones_for_retry(
                    next_threshold,
                    issue,
                    source,
                    guard_regions,
                ),
            )
            threshold = next_threshold
            params.high_pitch_threshold = threshold
        return rendered, history, guard_applied_any

    @staticmethod
    def _estimate_peak_f0(source: Path) -> float:
        try:
            import numpy as np

            ''' 
            So-VITS-SVC 在守护程序运行前已立即生成基于模型的F0曲线。当可用时可重复使用：
            下方轻量级自相关探测器可能将强谐波误认为2 kHz基频，从而在普通语音上触发保护。
            '''
            if source.name.lower() in {"infer_input.wav", "vocals_repaired.wav"}:
                sidecar = source.with_name("f0.npy")
                try:
                    source_mtime = source.stat().st_mtime
                    sidecar_mtime = sidecar.stat().st_mtime
                    if sidecar_mtime >= source_mtime - 120.0:
                        curve = np.asarray(np.load(str(sidecar), allow_pickle=False)).reshape(-1)
                        voiced = curve[np.isfinite(curve) & (curve > 0.0)]
                        if voiced.size >= 4:
                            return float(np.max(voiced))
                except (OSError, ValueError, TypeError):
                    pass

            with wave.open(str(source), "rb") as handle:
                rate = int(handle.getframerate() or 44100)
                channels = int(handle.getnchannels() or 1)
                raw = handle.readframes(handle.getnframes())
            if not raw:
                return 0.0
            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
            audio = audio.reshape(-1, channels).mean(axis=1)
            target_rate = min(rate, 16000)
            if rate != target_rate:
                positions = np.linspace(0, len(audio) - 1, max(1, round(len(audio) * target_rate / rate)))
                audio = np.interp(positions, np.arange(len(audio)), audio)
            # Use a 40 ms analysis window. The previous 80 ms window could
            # average a brief high note together with the neighboring low
            # note, making the high note invisible to the guard entry check.
            frame = min(len(audio), max(512, int(target_rate * 0.04)))
            if frame < 256:
                return 0.0
            min_lag = max(2, int(target_rate / 2000.0))
            max_lag = min(frame - 1, int(target_rate / 60.0))
            estimates: list[tuple[float, float, float]] = []
            hop = max(1, frame // 2)
            for start in range(0, max(1, len(audio) - frame + 1), hop):
                chunk = audio[start : start + frame]
                if len(chunk) < frame:
                    chunk = np.pad(chunk, (0, frame - len(chunk)))
                chunk = chunk - float(np.mean(chunk))
                if float(np.sqrt(np.mean(chunk * chunk))) < 0.008:
                    continue
                corr = np.correlate(chunk, chunk, mode="full")[frame - 1:]
                if corr[0] <= 0:
                    continue
                corr = corr / corr[0]
                peaks = [
                    lag for lag in range(min_lag + 1, max_lag)
                    if corr[lag] >= corr[lag - 1]
                    and corr[lag] >= corr[lag + 1]
                    and corr[lag] >= 0.45
                ]
                lag = peaks[0] if peaks else min_lag + int(np.argmax(corr[min_lag:max_lag + 1]))
                if float(corr[lag]) >= 0.35:
                    estimates.append(
                        (
                            target_rate / float(lag),
                            float(corr[lag]),
                            start / float(target_rate),
                        )
                    )
            if not estimates:
                return 0.0
            values = np.asarray([item[0] for item in estimates], dtype=np.float32)
            baseline = float(np.percentile(values, 85.0))

            # Keep the robust whole-track estimate for ordinary material, but
            # also retain a short, internally consistent high-pitch run. This
            # is the case that matters for songs with a brief high syllable.
            candidate_floor = max(760.0, baseline + 180.0)
            candidate_indices = np.flatnonzero(values >= candidate_floor)
            if candidate_indices.size >= 2:
                runs: list[np.ndarray] = []
                run_start = 0
                for index in range(1, candidate_indices.size + 1):
                    separated = (
                        index == candidate_indices.size
                        or candidate_indices[index] - candidate_indices[index - 1] > 2
                    )
                    if separated:
                        runs.append(candidate_indices[run_start:index])
                        run_start = index
                supported_runs = [
                    run
                    for run in runs
                    if len(run) >= 2
                    and float(np.ptp(values[run])) <= max(90.0, float(np.median(values[run])) * 0.12)
                    and float(
                        np.median(
                            np.asarray(
                                [estimates[int(item)][1] for item in run],
                                dtype=np.float32,
                            )
                        )
                    ) >= 0.45
                ]
                if supported_runs:
                    strongest = max(
                        supported_runs,
                        key=lambda run: float(np.median(values[run])),
                    )
                    return float(np.median(values[strongest]))

            # Ignore isolated octave/upper-harmonic errors. The percentile
            # still captures sustained high notes without opening protection
            # for a single noisy frame.
            return baseline
        except (OSError, ValueError, wave.Error, ImportError):
            return 0.0

    def _enhance_vocal(
        self,
        work: dict[str, Any],
        source: Path,
        output: Path,
        device: str,
        log_file: Path,
        *,
        progress: int,
        reference: Path | None = None,
    ) -> Path:
        enabled, level, controls = self._enhancement_settings(work)
        if not enabled:
            return source
        self._set_step(work, "enhance", StepStatus.ACTIVE.value)
        self._save(work)
        layer = (
            "高级层 Natural Voice"
            if level == "advanced"
            else "基础层 Clean Voice"
        )
        chain = (
            "AI 对齐/自然修音 → 自然停顿扩展 → 宽带参考 → 已完成 DeepFilterNet3 修复 → 真实细节保护 → 轻母带 → 并行混合 → AI 角色共振峰 → AI EQ → AI Compressor → AI Exciter → Stereo → AI 响度包络"
            if level == "advanced"
            else "AI 对齐/自然修音 → 自然停顿扩展 → 已完成 DeepFilterNet3 修复 → 轻母带 → 并行混合 → AI 角色共振峰 → AI EQ → AI Compressor → AI Exciter → Stereo → AI 响度包络"
        )
        self._log(
            log_file,
            f"AI 歌声增强开始：{layer}（{chain}；AI 对齐 "
            f"{controls['timing_alignment']:.0%}；自然修音 {controls['pitch_correction']:.0%}；"
            f"AI 角色共振峰 {controls['timbre_focus']:.0%}；"
            f"AI EQ {controls['ai_eq']:.0%}；AI Compressor {controls['ai_compressor']:.0%}；"
            f"AI Exciter {controls['ai_exciter']:.0%}；Stereo {controls['stereo_width']:.0%}；"
            f"AI 响度包络 {controls['loudness_envelope']:.0%}）",
        )
        # Natural tuning writes a temporary file and can lower the measured
        # high-band ratio. Carry the model-output classification from the repair
        # step so the enhancement worker does not re-enable dry HF injection just
        # because the tuned intermediate looks slightly less bright.
        preserve_model_high_band = False
        repair_results = work.get("vocal_repair")
        if isinstance(repair_results, dict):
            output_repair = repair_results.get("output")
            if isinstance(output_repair, dict):
                output_profile = output_repair.get("profile")
                if isinstance(output_profile, dict):
                    preserve_model_high_band = bool(
                        output_profile.get("high_band_noise", False)
                    )
        enhanced = self._vocal_enhancement.enhance(
            source,
            output,
            level=level,
            device=device,
            log_file=log_file,
            reference=reference,
            skip_repair=True,
            preserve_model_high_band=preserve_model_high_band,
            **controls,
        )
        self._set_step(work, "enhance", StepStatus.DONE.value)
        work["progress"] = progress
        work["vocal_enhancement_result"] = {
            "level": level,
            **controls,
            "input_path": str(source),
            "output_path": str(enhanced),
        }
        self._save(work)
        self._log(log_file, f"  AI 歌声增强完成: {enhanced}")
        return enhanced

    def _mix_vocal_with_music(
        self,
        vocals: Path,
        instrumental: Path,
        output: Path,
        *,
        enhanced: bool,
        log_file: Path,
    ) -> bool:
        if not enhanced:
            return self._ffmpeg.mix(vocals, instrumental, output)

        profile = self._ffmpeg.adaptive_mix_profile(vocals, instrumental)
        vocal_gain = float(profile["vocal_gain_db"])
        music_gain = float(profile["instrumental_gain_db"])
        vocal_lufs = profile.get("vocal_lufs")
        music_lufs = profile.get("instrumental_lufs")
        measured = (
            f"输入人声 {float(vocal_lufs):.2f} LUFS / 伴奏 {float(music_lufs):.2f} LUFS"
            if vocal_lufs is not None and music_lufs is not None
            else "响度测量不可用，使用保守回退"
        )
        self._log(
            log_file,
            "  AI 动态混音平衡："
            f"人声 {vocal_gain:+.2f} dB / 伴奏 {music_gain:+.2f} dB；"
            f"{measured}；轻量并行总线融合",
        )
        return self._ffmpeg.mix(
            vocals,
            instrumental,
            output,
            vocal_gain_db=vocal_gain,
            instrumental_gain_db=music_gain,
            glue=True,
        )

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
        if work and work.get("workflow") == "ai_enhancement":
            self._run_ai_enhancement(work_id)
        elif work and work.get("mode") == "multi":
            self._run_multi(work_id)
        else:
            self._run_locked(work_id)

    def _run_ai_enhancement(self, work_id: str) -> None:
        work = self._repo.get(work_id)
        if not work:
            return
        work_dir = config.WORKS_DIR / work_id
        work_dir.mkdir(parents=True, exist_ok=True)
        log_file = work_dir / "run.log"
        try:
            log_file.write_text(
                f"=== {work.get('title', work_id)} ===\n"
                f"开始时间: {datetime.now().isoformat(timespec='seconds')}\n"
                f"原始歌曲: {work.get('original_audio_path', '')}\n"
                f"待增强作品: {work.get('parent_work_id', '')}\n",
                encoding="utf-8",
            )
        except OSError:
            pass
        work["status"] = JobStatus.RUNNING.value
        work["progress"] = 0
        work["log_path"] = str(log_file)
        work.pop("queue_position", None)
        self._save(work)

        try:
            if not self._vocal_enhancement.available:
                raise RuntimeError("AI 歌声增强环境未就绪，请先修复 vocal 环境")
            if not self._uvr.available:
                raise RuntimeError("AI 增强需要可用的 UVR 原曲分离环境")
            original = Path(str(work.get("original_audio_path") or ""))
            cover_output = Path(str(work.get("target_output_path") or ""))
            if not original.is_file():
                raise RuntimeError("原始歌曲文件不存在，请重新选择原始音频")
            if not cover_output.is_file():
                raise RuntimeError("待增强的翻唱成品不存在")
            params = InferenceParams.from_dict(work.get("params") or {})
            sep_model = params.uvr_model or config.UVR_SEP_MODEL

            self._set_step(work, "reference", StepStatus.ACTIVE.value)
            self._save(work)
            original_sep = self._uvr.separate(
                original,
                work_dir / "original_stems",
                sep_model,
                params.device,
            )
            reference_vocal = Path(original_sep.vocals)
            reference_instrumental = (
                Path(original_sep.instrumental) if original_sep.instrumental else None
            )
            if not reference_vocal.is_file():
                raise RuntimeError("无法从原始歌曲提取参考人声")
            if getattr(original_sep, "simulated", False):
                raise RuntimeError("原始歌曲分离未使用真实 UVR 结果，无法进行可靠增强")
            if config.uvr_dereverb_ready():
                self._log(
                    log_file,
                    f"原曲参考人声去混响中（{config.UVR_DEREVERB_MODEL}）…",
                )
                dereverb = self._uvr.separate(
                    reference_vocal,
                    work_dir / "reference_dereverb",
                    config.UVR_DEREVERB_MODEL,
                    params.device,
                )
                if not dereverb.simulated and dereverb.vocals.exists():
                    reference_vocal = Path(dereverb.vocals)
                    self._log(log_file, f"原曲去混响参考人声: {reference_vocal}")
                else:
                    self._log(log_file, "原曲参考去混响降级：沿用 UVR 分离人声")
            self._set_step(work, "reference", StepStatus.DONE.value)
            work["progress"] = 25
            work["reference_vocals_path"] = str(reference_vocal)
            if reference_instrumental and reference_instrumental.is_file():
                work["instrumental_path"] = str(reference_instrumental)
            else:
                fallback_instrumental = Path(str(work.get("target_instrumental_path") or ""))
                if fallback_instrumental.is_file():
                    reference_instrumental = fallback_instrumental
                    work["instrumental_path"] = str(fallback_instrumental)
            self._save(work)
            self._log(log_file, f"原曲参考人声: {reference_vocal}")

            self._set_step(work, "cover_vocal", StepStatus.ACTIVE.value)
            self._save(work)
            direct_vocal = Path(str(work.get("target_vocal_path") or ""))
            if direct_vocal.is_file():
                cover_vocal = direct_vocal
                self._log(log_file, f"复用翻唱作品干声: {cover_vocal}")
            else:
                cover_sep = self._uvr.separate(
                    cover_output,
                    work_dir / "cover_stems",
                    sep_model,
                    params.device,
                )
                cover_vocal = Path(cover_sep.vocals)
                if not cover_vocal.is_file():
                    raise RuntimeError("无法从翻唱成品提取待增强人声")
                self._log(log_file, f"从翻唱成品分离人声: {cover_vocal}")
            self._set_step(work, "cover_vocal", StepStatus.DONE.value)
            work["progress"] = 45
            work["enhancement_input_path"] = str(cover_vocal)
            self._save(work)

            enabled, level, controls = self._enhancement_settings(work)
            if not enabled:
                raise RuntimeError("AI 增强参数未启用")
            self._set_step(work, "enhance", StepStatus.ACTIVE.value)
            self._save(work)
            enhanced = self._vocal_enhancement.enhance(
                cover_vocal,
                work_dir / "enhanced_vocals.wav",
                level=level,
                device=params.device,
                log_file=log_file,
                reference=reference_vocal,
                **controls,
            )
            self._set_step(work, "enhance", StepStatus.DONE.value)
            work["progress"] = 80
            work["converted_path"] = str(enhanced)
            work["ai_vocal_paths"] = [str(enhanced)]
            work["vocal_enhancement_result"] = {
                "level": level,
                **controls,
                "reference_path": str(reference_vocal),
                "input_path": str(cover_vocal),
                "output_path": str(enhanced),
            }
            self._save(work)

            self._set_step(work, "mix", StepStatus.ACTIVE.value)
            self._save(work)
            output = work_dir / "output.wav"
            mixed = False
            if reference_instrumental and reference_instrumental.is_file():
                mixed = self._mix_vocal_with_music(
                    enhanced,
                    reference_instrumental,
                    output,
                    enhanced=True,
                    log_file=log_file,
                )
            if not mixed:
                if not self._ffmpeg.convert(enhanced, output):
                    output = enhanced
            self._set_step(work, "mix", StepStatus.DONE.value)
            duration = float(self._ffmpeg.probe_duration(output) or 0.0)
            work["progress"] = 100
            work["status"] = JobStatus.DONE.value
            work["output_path"] = str(output)
            work["format"] = output.suffix.lstrip(".").upper() or "WAV"
            work["size"] = paths.file_size_label(output)
            work["duration"] = self._format_duration(duration)
            self._record_history(work)
            self._save(work)
            self._cleanup_finished_work_cache(work_dir, work, log_file)
            self._log(log_file, f"AI 增强任务完成: {output}")
        except Exception as exc:  # noqa: BLE001 - 后台任务必须记录失败原因
            work["status"] = JobStatus.FAILED.value
            work["error"] = str(exc)
            for step in work.get("steps") or []:
                if step.get("status") == StepStatus.ACTIVE.value:
                    step["status"] = StepStatus.FAILED.value
            self._save(work)
            self._log(log_file, f"AI 增强任务失败: {exc}")
            self._log(log_file, traceback.format_exc())

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
            enhancement_enabled, _, _ = self._enhancement_settings(work)
            preprocess_enabled, preprocess_engine, pymss_model, harmony_enabled, harmony_model = self._preprocess_settings(work)
            pipeline_total = (7 if enhancement_enabled else 6) + int(harmony_enabled)
            framework = config.modelhub_normalize_framework(work.get("framework"))
            is_sovits = framework == "so-vits-svc"
            model_profile = {
                "framework": framework,
                "main_config_path": work.get("main_config_path", ""),
                "metadata": work.get("model_metadata") or {},
            }
            params.high_pitch_threshold = self._model_high_pitch_threshold(
                params, model_profile, framework
            )
            engine = self._engines.for_framework(framework)
            source = Path(work["source_path"]) if work.get("source_path") else None
            duration = (
                self._ffmpeg.probe_duration(source)
                if source and source.exists()
                else None
            ) or 180.0
            self._log(log_file, f"源文件: {source} | 时长: {duration:.1f}s | 设备: {params.device}")

            instrumental: Path | None = None
            if preprocess_enabled and source and source.exists():
                self._set_step(work, "separate", StepStatus.ACTIVE.value)
                self._save(work)
                if preprocess_engine == "pymss":
                    tool = self._pymss
                    available = tool.available
                    self._log(log_file, f"[1/{pipeline_total}] 人声分离开始（PyMSS {'可用' if available else '未就绪'}）")
                else:
                    tool = self._uvr
                    available = tool.available
                    self._log(log_file, f"[1/{pipeline_total}] 人声分离开始（UVR {'可用' if available else '降级模式'}）")
                # 先把源音频统一转码成标准 wav 再分离：在线下载的文件常把 m4a/flac
                # 误存成 .mp3，mp3 专用解码器会读到「junk」而失败导致分离降级。
                # ffmpeg 按内容（而非扩展名）解码，可一并纠正这类格式错配。
                sep_source = self._normalize_source(source, work_dir, log_file)
                if preprocess_engine == "pymss" and not available:
                    raise RuntimeError("已选择 PyMSS，但 PyMSS 环境未就绪，请先安装 PyMSS 并下载模型")
                sep_model = (
                    pymss_model if preprocess_engine == "pymss"
                    else (params.uvr_model or config.UVR_SEP_MODEL)
                )
                if preprocess_engine == "pymss" and not config.pymss_model_ready(sep_model):
                    raise RuntimeError(f"PyMSS 模型未下载: {sep_model}，请先在模型管理页下载")
                if preprocess_engine == "pymss":
                    sep = tool.separate(
                        sep_source,
                        work_dir,
                        sep_model,
                        params.device,
                        purpose=config.PYMSS_PURPOSE_VOCAL,
                    )
                else:
                    sep = tool.separate(sep_source, work_dir, sep_model, params.device)
                vocals = sep.vocals
                instrumental = sep.instrumental
                if sep.simulated:
                    self._log(log_file, "  分离降级：直接使用源音频作为人声（无伴奏）")
                else:
                    self._log(log_file, f"  分离引擎/模型: {preprocess_engine} / {sep_model}")
                    self._log(log_file, f"  分离设备: {sep.device or params.device}")
                    self._log(log_file, f"  人声: {vocals}")
                    self._log(log_file, f"  伴奏: {instrumental}")
                    # 1b) 人声去混响/去回声：去掉混响后再送 SVC，缓解"电音/机械音"
                    if preprocess_engine == "uvr" and config.uvr_dereverb_ready():
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
                if harmony_enabled:
                    self._set_step(work, "harmony", StepStatus.ACTIVE.value)
                    if not self._pymss.available:
                        raise RuntimeError("已启用去混响净化，但 PyMSS 环境未就绪")
                    if not config.pymss_model_ready(harmony_model):
                        raise RuntimeError(
                            f"去混响模型未下载: {harmony_model}，请先在模型管理页下载"
                        )
                    self._log(log_file, f"  去混响净化开始（PyMSS / {harmony_model}）")
                    harmony = self._pymss.separate(
                        Path(vocals),
                        work_dir / "harmony",
                        harmony_model,
                        params.device,
                        purpose=config.PYMSS_PURPOSE_HARMONY,
                    )
                    if harmony.vocals.exists():
                        vocals = harmony.vocals
                        self._log(log_file, f"  去混响净化后人声: {vocals}")
                    self._set_step(work, "harmony", StepStatus.DONE.value)
                self._set_step(work, "separate", StepStatus.DONE.value)
            elif source and source.exists():
                # 可选前期处理关闭时，保留原音频作为模型输入，不生成伴奏轨。
                vocals = self._normalize_source(source, work_dir, log_file)
                self._log(log_file, f"[1/{pipeline_total}] 跳过前期分离，直接使用源音频: {vocals}")
            else:
                vocals = work_dir / "placeholder.wav"
            # 保存原始分离结果，再用专用模型修复分离伪影。
            if instrumental and Path(instrumental).exists():
                work["instrumental_path"] = str(instrumental)
            if Path(vocals).exists():
                work["separated_vocals_path"] = str(vocals)
            work["progress"] = 16
            self._save(work)

            if preprocess_enabled:
                vocals, audio_profile = self._repair_vocal(
                    work,
                    Path(vocals),
                    work_dir / "vocals_repaired.wav",
                    params.device,
                    log_file,
                    stage="separated",
                    progress=32,
                    reference=Path(vocals),
                )
            else:
                audio_profile = {}
            if Path(vocals).exists():
                work["vocals_path"] = str(vocals)
            work["adaptive_audio_profile"] = audio_profile
            self._adapt_high_range(params, audio_profile, log_file, framework)
            self._save(work)

            # 3) F0 提取：先把人声统一为 wav，再用 SVC 环境的预测器真实提取基频曲线
            self._set_step(work, "f0", StepStatus.ACTIVE.value)
            self._save(work)
            infer_input = Path(vocals)
            if infer_input.exists() and self._ffmpeg.available:
                wav_input = work_dir / "infer_input.wav"
                if self._ffmpeg.convert(infer_input, wav_input):
                    infer_input = wav_input
            # Use the exact dry vocal that finished preprocessing and is sent to
            # the model. This keeps AI Vocal reference matching in the same
            # sample-rate/timing domain as inference, instead of using the
            # earlier DeepFilter output.
            if infer_input.is_file():
                work["reference_vocals_path"] = str(infer_input)
                self._log(log_file, f"AI Vocal 参考干声（前期处理完成）: {infer_input}")
            self._log(log_file, f"[3/{pipeline_total}] 推理输入已准备: {infer_input}")
            original_infer_input = infer_input
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
            work["progress"] = 48
            self._save(work)

            # 4) 推理（按模型框架路由引擎：so-vits-svc / rvc / …）
            self._set_step(work, "infer", StepStatus.ACTIVE.value)
            self._save(work)
            fw_label = config.MODELHUB_FRAMEWORKS.get(framework, framework)
            self._log(
                log_file,
                f"[4/{pipeline_total}] {fw_label} 推理开始（引擎 {'可用' if getattr(engine, 'available', False) else '降级模式'}）",
            )
            raw_converted = work_dir / "converted_raw.wav"
            model_payload = {
                "framework": framework,
                "main_model_path": work.get("main_model_path", ""),
                "main_config_path": work.get("main_config_path", ""),
                "diffusion_model_path": work.get("diffusion_model_path", ""),
                "diffusion_config_path": work.get("diffusion_config_path", ""),
                "index_path": work.get("index_path", ""),
            }
            raw_converted, recovery_history, guard_enabled = self._infer_with_dropout_recovery(
                engine=engine,
                model=model_payload,
                source=original_infer_input,
                output=raw_converted,
                params=params,
                duration=duration,
                log_file=log_file,
                allow_recovery=True,
            )
            work["high_pitch_guard_applied"] = bool(guard_enabled)
            work["inference_dropout_recovery"] = recovery_history
            self._save(work)
            self._set_step(work, "infer", StepStatus.DONE.value)
            work["progress"] = 68
            self._save(work)
            self._log(log_file, "  模型推理完成")

            repaired_converted, _ = self._repair_vocal(
                work,
                raw_converted,
                work_dir / (
                    "converted_repaired.wav" if enhancement_enabled else "converted.wav"
                ),
                params.device,
                log_file,
                stage="output",
                progress=82,
                reference=original_infer_input,
            )
            converted = self._enhance_vocal(
                work,
                repaired_converted,
                work_dir / "converted.wav",
                params.device,
                log_file,
                progress=90,
                reference=Path(
                    work.get("reference_vocals_path") or work["vocals_path"]
                ) if work.get("vocals_path") else None,
            )
            work["raw_converted_path"] = str(raw_converted)

            # 最后混音：转换/增强后人声 + 原伴奏 → 完整翻唱；无伴奏则仅输出干声
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
                mixed = self._mix_vocal_with_music(
                    converted,
                    instrumental,
                    output,
                    enhanced=enhancement_enabled,
                    log_file=log_file,
                )
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
                f"[{pipeline_total}/{pipeline_total}] 混音合成完成（"
                f"{('AI 动态平衡 / 轻量总线融合' if enhancement_enabled else '人声 +1.8 dB / 伴奏 -0.7 dB') if mixed else '仅干声'}）: {output}",
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
            self._cleanup_finished_work_cache(work_dir, work, log_file)
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

    def _cleanup_finished_work_cache(
        self,
        work_dir: Path,
        work: dict[str, Any],
        log_file: Path,
    ) -> None:
        """清理任务完成后的推理临时文件，同时保留编辑器会引用的素材。

        高音保护会为每次重试生成多份整轨 wav 和 regions 报告。它们只在当前
        推理期间使用；编辑器真正需要的是作品记录中的路径和 ``editor_segments``
        分段素材。清理采用白名单保护 + 明确临时文件模式，任何未知文件都不删除。
        """
        try:
            base = work_dir.resolve()
            if not base.is_dir():
                return
        except OSError:
            return

        protected: set[Path] = set()

        def remember(value: Any) -> None:
            if isinstance(value, dict):
                for child in value.values():
                    remember(child)
                return
            if isinstance(value, (list, tuple, set)):
                for child in value:
                    remember(child)
                return
            if not isinstance(value, str) or not value.strip():
                return
            try:
                candidate = Path(value)
                if not candidate.is_absolute():
                    candidate = base / candidate
                resolved = candidate.resolve()
                if resolved == base or base in resolved.parents:
                    protected.add(resolved)
            except (OSError, ValueError):
                return

        remember(work)
        # This is also protected when a task is in manual-vocal-merge mode and
        # its paths are only present in editor metadata created immediately next.
        editor_root = (base / "editor_segments").resolve()
        protected.add(editor_root)
        # Keep the normalized inference input as an optional muted editor track.
        infer_input = (base / "infer_input.wav").resolve()
        if infer_input.is_file():
            protected.add(infer_input)

        transient_patterns = (
            "*_dropout_retry*.wav",
            "*_high_guarded_retry*.wav",
            "*_restored_retry*.wav",
            "*_guarded_merged_retry*.wav",
            "*.regions.json",
            "f0.npy",
            "source.wav",
        )
        removed = 0
        released_bytes = 0
        seen: set[Path] = set()

        def remove_if_unprotected(candidate: Path) -> None:
            nonlocal removed, released_bytes
            try:
                resolved = candidate.resolve()
                if (
                    resolved in seen
                    or not resolved.is_file()
                    or resolved in protected
                    or resolved == editor_root
                    or editor_root in resolved.parents
                    or base not in resolved.parents
                ):
                    return
                seen.add(resolved)
                size = resolved.stat().st_size
                resolved.unlink()
                removed += 1
                released_bytes += size
            except (OSError, ValueError):
                return

        for pattern in transient_patterns:
            try:
                candidates = base.rglob(pattern)
            except OSError:
                continue
            for candidate in candidates:
                remove_if_unprotected(candidate)

        # Separation and optional vocal-cleanup tools also leave large working
        # trees.  Their selected output is protected through the work record;
        # only unreferenced files are removed, then empty cache directories are
        # pruned.  This keeps editor projects that point at a selected stem safe.
        for root_name in (
            "original_stems",
            "cover_stems",
            "reference_dereverb",
            "dereverb",
            "harmony",
        ):
            cache_root = base / root_name
            if not cache_root.is_dir():
                continue
            try:
                for candidate in cache_root.rglob("*"):
                    if candidate.is_file():
                        remove_if_unprotected(candidate)
                directories = sorted(
                    (item for item in cache_root.rglob("*") if item.is_dir()),
                    key=lambda item: len(item.parts),
                    reverse=True,
                )
                for directory in [*directories, cache_root]:
                    try:
                        directory.rmdir()
                    except OSError:
                        pass
            except OSError:
                continue
        if removed:
            self._log(
                log_file,
                f"  已清理推理临时缓存 {removed} 个，释放约 {released_bytes / (1024 * 1024):.1f} MB；编辑器素材已保留",
            )

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

    @staticmethod
    def _multi_model_params(
        model: dict[str, Any], fallback: dict[str, Any] | None = None
    ) -> InferenceParams:
        """Normalize one mixed-cover model's params, including the guard switch.

        Older records only stored a shared ``params`` object.  Preserve that
        value when a model-specific switch is absent, while keeping protection
        enabled by default for newly created or incomplete records.
        """
        raw = model.get("params")
        params = dict(raw) if isinstance(raw, dict) else {}
        if (
            "auto_high_pitch_guard" not in params
            and "autoHighPitchGuard" not in params
        ):
            shared = fallback if isinstance(fallback, dict) else {}
            guard = shared.get(
                "auto_high_pitch_guard",
                shared.get("autoHighPitchGuard", True),
            )
            params["auto_high_pitch_guard"] = guard
        if (
            "manual_params_enabled" not in params
            and "manualParamsEnabled" not in params
        ):
            shared = fallback if isinstance(fallback, dict) else {}
            params["manual_params_enabled"] = shared.get(
                "manual_params_enabled",
                shared.get("manualParamsEnabled", True),
            )
        if (
            "high_pitch_guard_rounds" not in params
            and "highPitchGuardRounds" not in params
        ):
            shared = fallback if isinstance(fallback, dict) else {}
            shared_rounds = shared.get(
                "high_pitch_guard_rounds",
                shared.get("highPitchGuardRounds"),
            )
            if shared_rounds is not None:
                params["high_pitch_guard_rounds"] = shared_rounds
        return InferenceParams.from_dict(params)

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
            enhancement_enabled, _, _ = self._enhancement_settings(work)
            preprocess_enabled, preprocess_engine, pymss_model, harmony_enabled, harmony_model = self._preprocess_settings(work)
            pipeline_total = (8 if enhancement_enabled else 7) + int(harmony_enabled)
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

            instrumental: Path | None = None
            if preprocess_enabled and source and source.exists():
                self._set_step(work, "separate", StepStatus.ACTIVE.value)
                self._save(work)
                tool = self._pymss if preprocess_engine == "pymss" else self._uvr
                if preprocess_engine == "pymss" and not tool.available:
                    raise RuntimeError("已选择 PyMSS，但 PyMSS 环境未就绪，请先安装 PyMSS 并下载模型")
                self._log(
                    log_file,
                    f"[1/{pipeline_total}] 人声分离（{preprocess_engine} {'可用' if tool.available else '降级模式'}）",
                )
                # 先统一转码成标准 wav（修正在线下载的格式错配，避免分离降级）
                sep_source = self._normalize_source(source, work_dir, log_file)
                sep_model = pymss_model if preprocess_engine == "pymss" else (base_params.uvr_model or config.UVR_SEP_MODEL)
                if preprocess_engine == "pymss" and not config.pymss_model_ready(sep_model):
                    raise RuntimeError(f"PyMSS 模型未下载: {sep_model}，请先在模型管理页下载")
                if preprocess_engine == "pymss":
                    sep = tool.separate(
                        sep_source,
                        work_dir,
                        sep_model,
                        base_params.device,
                        purpose=config.PYMSS_PURPOSE_VOCAL,
                    )
                else:
                    sep = tool.separate(sep_source, work_dir, sep_model, base_params.device)
                vocals = sep.vocals
                instrumental = sep.instrumental
                if sep.simulated:
                    self._log(log_file, "  分离降级：直接使用源音频作为人声（无伴奏）")
                else:
                    self._log(log_file, f"  分离设备: {sep.device or base_params.device}")
                    self._log(log_file, f"  人声: {vocals} | 伴奏: {instrumental}")
                    if preprocess_engine == "uvr" and config.uvr_dereverb_ready():
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
                if harmony_enabled:
                    self._set_step(work, "harmony", StepStatus.ACTIVE.value)
                    if not self._pymss.available:
                        raise RuntimeError("已启用去混响净化，但 PyMSS 环境未就绪")
                    if not config.pymss_model_ready(harmony_model):
                        raise RuntimeError(
                            f"去混响模型未下载: {harmony_model}，请先在模型管理页下载"
                        )
                    self._log(log_file, f"  去混响净化开始（PyMSS / {harmony_model}）")
                    harmony = self._pymss.separate(
                        Path(vocals),
                        work_dir / "harmony",
                        harmony_model,
                        base_params.device,
                        purpose=config.PYMSS_PURPOSE_HARMONY,
                    )
                    if harmony.vocals.exists():
                        vocals = harmony.vocals
                        self._log(log_file, f"  去混响净化后人声: {vocals}")
                    self._set_step(work, "harmony", StepStatus.DONE.value)
            elif source and source.exists():
                vocals = self._normalize_source(source, work_dir, log_file)
                self._log(log_file, f"[1/{pipeline_total}] 跳过前期分离，直接使用源音频")
            else:
                vocals = work_dir / "placeholder.wav"
            if instrumental and Path(instrumental).exists():
                work["instrumental_path"] = str(instrumental)
            if Path(vocals).exists():
                work["separated_vocals_path"] = str(vocals)
            work["progress"] = 14
            self._save(work)

            if preprocess_enabled:
                self._set_step(work, "separate", StepStatus.DONE.value)
                vocals, audio_profile = self._repair_vocal(
                    work,
                    Path(vocals),
                    work_dir / "vocals_repaired.wav",
                    base_params.device,
                    log_file,
                    stage="separated",
                    progress=27,
                    reference=Path(vocals),
                )
            else:
                audio_profile = {}
            if Path(vocals).exists():
                work["vocals_path"] = str(vocals)
            work["adaptive_audio_profile"] = audio_profile
            self._save(work)

            # 3) 歌词分割：把人声统一为 wav，并规划时间轴 / 参与模型
            self._set_step(work, "split", StepStatus.ACTIVE.value)
            self._save(work)
            infer_input = Path(vocals)
            if infer_input.exists() and self._ffmpeg.available:
                wav_input = work_dir / "infer_input.wav"
                if self._ffmpeg.convert(infer_input, wav_input):
                    infer_input = wav_input
            if infer_input.is_file():
                work["reference_vocals_path"] = str(infer_input)
                self._log(log_file, f"AI Vocal 参考干声（前期处理完成）: {infer_input}")
            original_infer_input = infer_input
            timeline = self._build_timeline(segments_in, duration)
            used_models: list[str] = []
            for s in timeline:
                for mid in s.get("model_ids") or []:
                    if mid and mid in seg_models and mid not in used_models:
                        used_models.append(mid)
            sung = sum(1 for s in timeline if s.get("model_ids"))
            self._log(
                log_file,
                f"[3/{pipeline_total}] 歌词分割完成：共 {len(timeline)} 段"
                f"（演唱 {sung} 段，间奏 {len(timeline) - sung} 段），"
                f"参与模型 {len(used_models)} 个",
            )
            self._set_step(work, "split", StepStatus.DONE.value)
            work["progress"] = 40
            self._save(work)

            # 4) 整轨逐模型推理：每个模型在「完整人声」上推理一次。
            #    关键修复：不再把人声切成碎片逐句送推——短碎片会产生句首/句尾
            #    电流声、咔哒声并拼出卡顿。整轨推理保证上下文连续、无边界伪声。
            self._set_step(work, "infer", StepStatus.ACTIVE.value)
            self._save(work)
            self._log(
                log_file,
                f"[4/{pipeline_total}] 整轨逐模型推理（按各模型框架路由引擎）",
            )
            full_renders: dict[str, Path] = {}
            high_pitch_guard_any = False
            recovery_history: dict[str, list[dict[str, Any]]] = {}
            for n, mid in enumerate(used_models):
                model = seg_models.get(mid) or {}
                seg_params = self._multi_model_params(model, work.get("params"))
                seg_framework = config.modelhub_normalize_framework(model.get("framework"))
                seg_params.high_pitch_threshold = self._model_high_pitch_threshold(
                    seg_params, model, seg_framework
                )
                self._adapt_high_range(
                    seg_params,
                    audio_profile,
                    log_file,
                    seg_framework,
                )
                seg_engine = self._engines.for_framework(seg_framework)
                full_raw = work_dir / f"full_{mid}.wav"
                fw_label = config.MODELHUB_FRAMEWORKS.get(seg_framework, seg_framework)
                self._log(
                    log_file,
                    f"  [{n + 1}/{len(used_models)}] 模型 {model.get('name', mid)} "
                    f"[{fw_label}] 整轨推理（引擎 {'可用' if getattr(seg_engine, 'available', False) else '降级模式'}）…",
                )
                try:
                    full_raw, model_recovery, guard_enabled = self._infer_with_dropout_recovery(
                        engine=seg_engine,
                        model={
                            "framework": seg_framework,
                            "main_model_path": model.get("main_model_path", ""),
                            "main_config_path": model.get("main_config_path", ""),
                            "diffusion_model_path": model.get("diffusion_model_path", ""),
                            "diffusion_config_path": model.get("diffusion_config_path", ""),
                            "index_path": model.get("index_path", ""),
                        },
                        source=original_infer_input,
                        output=full_raw,
                        params=seg_params,
                        duration=duration,
                        log_file=log_file,
                        allow_recovery=True,
                    )
                    recovery_history[mid] = model_recovery
                    high_pitch_guard_any = high_pitch_guard_any or guard_enabled
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
            work["inference_dropout_recovery"] = recovery_history
            self._save(work)

            manual_vocal_merge = (
                str(work.get("workflow") or "auto_mix") == "manual_vocal_merge"
            )
            if manual_vocal_merge:
                self._set_step(work, "repair_output", StepStatus.ACTIVE.value)
                self._save(work)
                repaired_renders: dict[str, Path] = {}
                for mid, rendered in full_renders.items():
                    repair_output = work_dir / f"full_{mid}_repaired.wav"
                    try:
                        repaired_renders[mid] = self._vocal_enhancement.repair(
                            Path(rendered),
                            repair_output,
                            stage="output",
                            device=base_params.device,
                            log_file=log_file,
                            reference=original_infer_input,
                        )
                    except (OSError, RuntimeError, ValueError) as exc:
                        repaired_renders[mid] = Path(rendered)
                        self._log(
                            log_file,
                            f"  模型 {mid} 输出修复失败，编辑器沿用原输出: {exc}",
                        )
                full_renders = repaired_renders
                work["vocal_repair"] = {
                    **(work.get("vocal_repair") or {}),
                    "output": {
                        "model": "DeepFilterNet3",
                        "applied": any(
                            path.name.endswith("_repaired.wav")
                            for path in full_renders.values()
                        ),
                        "outputs": [str(path) for path in full_renders.values()],
                    },
                }
                self._set_step(work, "repair_output", StepStatus.DONE.value)
                work["progress"] = 84
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

            if manual_vocal_merge:
                self._set_step(work, "merge", StepStatus.ACTIVE.value)
                self._save(work)
                self._log(
                    log_file,
                    f"[5/{pipeline_total}] 手动人声合并：跳过自动拼接，等待进入编辑器逐段合并",
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
                self._cleanup_finished_work_cache(work_dir, work, log_file)
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

            full_vocal = work_dir / "converted_raw.wav"
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
                    f"[5/{pipeline_total}] 人声合并完成（{len(timeline)} 句合并为 {len(pieces)} 段）：{full_vocal}",
                )
            self._set_step(work, "merge", StepStatus.DONE.value)
            work["progress"] = 76
            self._save(work)

            raw_full_vocal = Path(full_vocal)
            # _enhance_vocal reads this flag to reduce synthetic high-frequency
            # coloration when any segment used the selective pitch guard.
            work["high_pitch_guard_applied"] = high_pitch_guard_any
            self._save(work)
            repaired_full_vocal, _ = self._repair_vocal(
                work,
                raw_full_vocal,
                work_dir / (
                    "converted_repaired.wav" if enhancement_enabled else "converted.wav"
                ),
                base_params.device,
                log_file,
                stage="output",
                progress=86,
                reference=original_infer_input,
            )
            full_vocal = self._enhance_vocal(
                work,
                repaired_full_vocal,
                work_dir / "converted.wav",
                base_params.device,
                log_file,
                progress=90,
                reference=Path(
                    work.get("reference_vocals_path") or work["vocals_path"]
                ) if work.get("vocals_path") else None,
            )
            work["raw_converted_path"] = str(raw_full_vocal)
            work["converted_path"] = str(full_vocal)
            work["ai_vocal_paths"] = [str(p) for p in full_renders.values()]
            work["ai_merged_vocal_path"] = str(full_vocal)
            self._save(work)

            # 最后混音：完整人声 + 原伴奏
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
                mixed = self._mix_vocal_with_music(
                    Path(full_vocal),
                    Path(instrumental),
                    output,
                    enhanced=enhancement_enabled,
                    log_file=log_file,
                )
            if not mixed:
                if self._ffmpeg.available and Path(full_vocal).exists():
                    if not self._ffmpeg.convert(Path(full_vocal), output):
                        output = Path(full_vocal)
                else:
                    output = Path(full_vocal)
            self._set_step(work, "mix", StepStatus.DONE.value)
            self._log(
                log_file,
                f"[{pipeline_total}/{pipeline_total}] 混音合成完成（"
                f"{('AI 动态平衡 / 轻量总线融合' if enhancement_enabled else '人声 +1.8 dB / 伴奏 -0.7 dB') if mixed else '仅人声'}）: {output}",
            )

            work["progress"] = 100
            work["status"] = JobStatus.DONE.value
            work["output_path"] = str(output)
            work["format"] = output.suffix.lstrip(".").upper() or "WAV"
            work["size"] = paths.file_size_label(output)
            work["duration"] = self._format_duration(duration)
            self._record_history(work)
            self._save(work)
            self._cleanup_finished_work_cache(work_dir, work, log_file)
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
