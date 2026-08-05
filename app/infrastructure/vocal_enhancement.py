"""AI 歌声增强封装：在独立环境中运行 DeepFilterNet 与 Pedalboard。"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import config


class VocalEnhancementProcessor:
    """运行人声分析、DeepFilterNet3 修复与可选歌声增强。"""

    LEVEL_BASIC = "basic"
    LEVEL_ADVANCED = "advanced"
    LEVELS = {LEVEL_BASIC, LEVEL_ADVANCED}
    DEFAULT_PITCH_CORRECTION = 0.45
    DEFAULT_TIMING_ALIGNMENT = 0.45
    DEFAULT_TIMBRE_FOCUS = 0.60
    DEFAULT_AI_EQ = 0.55
    DEFAULT_AI_COMPRESSOR = 0.45
    DEFAULT_AI_EXCITER = 0.25
    DEFAULT_STEREO_WIDTH = 0.30
    DEFAULT_LOUDNESS_ENVELOPE = 0.58

    @property
    def available(self) -> bool:
        return config.vocal_enhancement_ready()

    def version(self) -> str | None:
        return (
            "Praat AI 对齐/自然修音 + DeepFilterNet + AI EQ/Compressor/Exciter/Stereo/响度包络"
            if self.available
            else None
        )

    def enhance(
        self,
        source: Path,
        output: Path,
        *,
        level: str = LEVEL_BASIC,
        device: str = "auto",
        log_file: Path | None = None,
        reference: Path | None = None,
        pitch_correction: float = DEFAULT_PITCH_CORRECTION,
        timing_alignment: float = DEFAULT_TIMING_ALIGNMENT,
        timbre_focus: float = DEFAULT_TIMBRE_FOCUS,
        ai_eq: float = DEFAULT_AI_EQ,
        ai_compressor: float = DEFAULT_AI_COMPRESSOR,
        ai_exciter: float = DEFAULT_AI_EXCITER,
        stereo_width: float = DEFAULT_STEREO_WIDTH,
        loudness_envelope: float = DEFAULT_LOUDNESS_ENVELOPE,
        skip_repair: bool = False,
    ) -> Path:
        normalized_level = str(level or self.LEVEL_BASIC).strip().lower()
        if normalized_level not in self.LEVELS:
            raise ValueError(f"未知歌声增强层级: {level}")
        if not source.is_file():
            raise RuntimeError(f"歌声增强输入不存在: {source}")
        if not self.available:
            raise RuntimeError(
                "AI 歌声增强环境未就绪，请运行 setup_env.bat --only vocal 后重试"
            )

        pitch_amount = self.normalize_strength(
            pitch_correction, self.DEFAULT_PITCH_CORRECTION
        )
        alignment_amount = self.normalize_strength(
            timing_alignment, self.DEFAULT_TIMING_ALIGNMENT
        )
        timbre_amount = self.normalize_strength(
            timbre_focus, self.DEFAULT_TIMBRE_FOCUS
        )
        eq_amount = self.normalize_strength(ai_eq, self.DEFAULT_AI_EQ)
        compressor_amount = self.normalize_strength(
            ai_compressor, self.DEFAULT_AI_COMPRESSOR
        )
        exciter_amount = self.normalize_strength(
            ai_exciter, self.DEFAULT_AI_EXCITER
        )
        stereo_amount = self.normalize_strength(
            stereo_width, self.DEFAULT_STEREO_WIDTH
        )
        loudness_amount = self.normalize_strength(
            loudness_envelope, self.DEFAULT_LOUDNESS_ENVELOPE
        )

        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            output.unlink(missing_ok=True)
        except OSError as exc:
            raise RuntimeError(f"无法清理旧的歌声增强输出: {output}") from exc

        env = self._worker_environment()

        with tempfile.TemporaryDirectory(
            prefix="xb-vocal-tune-",
            dir=str(output.parent),
        ) as raw_temp:
            enhancement_source = source
            if (
                (pitch_amount > 0.0 or alignment_amount > 0.0)
                and reference is not None
                and reference.is_file()
            ):
                tuned = Path(raw_temp) / "tuned.wav"
                if self._try_natural_tuning(
                    source,
                    reference,
                    tuned,
                    pitch_amount,
                    alignment_amount,
                    log_file,
                    env,
                ):
                    enhancement_source = tuned

            cmd = [
                str(config.VOCAL_ENHANCEMENT_PYTHON),
                str(config.VOCAL_ENHANCEMENT_WORKER),
                "--input",
                str(enhancement_source),
                "--output",
                str(output),
                "--mode",
                "enhance",
                "--level",
                normalized_level,
                "--device",
                str(device or "auto"),
                "--timbre-focus",
                f"{timbre_amount:.4f}",
                "--ai-eq",
                f"{eq_amount:.4f}",
                "--ai-compressor",
                f"{compressor_amount:.4f}",
                "--ai-exciter",
                f"{exciter_amount:.4f}",
                "--stereo-width",
                f"{stereo_amount:.4f}",
                "--loudness-envelope",
                f"{loudness_amount:.4f}",
            ]
            if reference is not None:
                cmd.extend(["--reference", str(reference)])
            if skip_repair:
                cmd.append("--skip-deepfilter")

            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                    timeout=3600,
                    **config.subprocess_no_window(),
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise RuntimeError(f"AI 歌声增强子进程启动失败: {exc}") from exc

            self._append_log(log_file, cmd, proc, "AI 歌声增强")
            if proc.returncode != 0 or not output.is_file():
                detail = self._error_tail(proc.stdout, proc.stderr)
                raise RuntimeError(
                    f"AI 歌声增强失败（子进程退出码 {proc.returncode}）: {detail}"
                )
        return output

    def analyze(
        self,
        source: Path,
        *,
        log_file: Path | None = None,
    ) -> dict[str, float | bool]:
        """Analyze high-band energy and singing range in the isolated model env."""
        if not source.is_file():
            raise RuntimeError(f"音频分析输入不存在: {source}")
        if not self.available:
            raise RuntimeError("AI 人声修复环境未就绪")
        with tempfile.TemporaryDirectory(prefix="xb-vocal-analysis-") as raw_temp:
            result_file = Path(raw_temp) / "profile.json"
            cmd = [
                str(config.VOCAL_ENHANCEMENT_PYTHON),
                str(config.VOCAL_ENHANCEMENT_WORKER),
                "--input",
                str(source),
                "--mode",
                "analyze",
                "--analysis-output",
                str(result_file),
            ]
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=self._worker_environment(),
                    timeout=900,
                    **config.subprocess_no_window(),
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise RuntimeError(f"音频频谱/音域分析启动失败: {exc}") from exc
            self._append_log(log_file, cmd, proc, "音频频谱/音域分析")
            if proc.returncode != 0 or not result_file.is_file():
                detail = self._error_tail(proc.stdout, proc.stderr)
                raise RuntimeError(f"音频频谱/音域分析失败: {detail}")
            try:
                raw = json.loads(result_file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise RuntimeError("音频频谱/音域分析结果损坏") from exc
        return {
            str(key): value
            for key, value in raw.items()
            if isinstance(value, (int, float, bool))
        }

    def repair(
        self,
        source: Path,
        output: Path,
        *,
        stage: str = "separated",
        device: str = "auto",
        log_file: Path | None = None,
        profile: dict[str, float | bool] | None = None,
    ) -> Path:
        """Repair UVR/model vocals with the bundled DeepFilterNet3 model."""
        normalized_stage = "output" if str(stage).lower() == "output" else "separated"
        if not source.is_file():
            raise RuntimeError(f"人声修复输入不存在: {source}")
        if not self.available:
            raise RuntimeError(
                "AI 人声修复环境未就绪，请运行 setup_env.bat --only vocal 后重试"
            )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.unlink(missing_ok=True)
        cmd = [
            str(config.VOCAL_ENHANCEMENT_PYTHON),
            str(config.VOCAL_ENHANCEMENT_WORKER),
            "--input",
            str(source),
            "--output",
            str(output),
            "--mode",
            "repair",
            "--repair-stage",
            normalized_stage,
            "--device",
            str(device or "auto"),
        ]
        if profile:
            cmd.extend(
                [
                    "--analysis-json",
                    json.dumps(profile, ensure_ascii=False, separators=(",", ":")),
                ]
            )
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self._worker_environment(),
                timeout=3600,
                **config.subprocess_no_window(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"AI 人声修复子进程启动失败: {exc}") from exc
        self._append_log(log_file, cmd, proc, "DeepFilterNet3 AI 人声修复")
        if proc.returncode != 0 or not output.is_file():
            detail = self._error_tail(proc.stdout, proc.stderr)
            raise RuntimeError(
                f"AI 人声修复失败（子进程退出码 {proc.returncode}）: {detail}"
            )
        return output

    @staticmethod
    def _worker_environment() -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env.setdefault("PYTORCH_CUDA_ALLOC_CONF", "max_split_size_mb:128")
        cache_home = config.VOCAL_ENHANCEMENT_MODEL_DIR
        cache_home.mkdir(parents=True, exist_ok=True)
        env["HOME"] = str(cache_home)
        env["USERPROFILE"] = str(cache_home)
        env["XDG_CACHE_HOME"] = str(cache_home / ".cache")
        env["LOCALAPPDATA"] = str(cache_home / ".local")
        env["XB_DEEPFILTER_MODEL_DIR"] = str(cache_home / "DeepFilterNet3")
        return env

    @staticmethod
    def normalize_strength(value: float, fallback: float) -> float:
        try:
            amount = float(value)
        except (TypeError, ValueError):
            amount = fallback
        if amount != amount:
            amount = fallback
        return max(0.0, min(1.0, amount))

    def _try_natural_tuning(
        self,
        source: Path,
        reference: Path,
        output: Path,
        strength: float,
        alignment_strength: float,
        log_file: Path | None,
        env: dict[str, str],
    ) -> bool:
        python = config.VOCAL_ENHANCEMENT_PYTHON
        worker = config.VOCAL_TUNING_WORKER
        if not python or not python.exists() or not worker.exists():
            self._append_message(log_file, "AI 对齐/自然修音跳过：美声/Praat 环境不可用")
            return False
        cmd = [
            str(python),
            str(worker),
            "--input",
            str(source),
            "--reference",
            str(reference),
            "--output",
            str(output),
            "--strength",
            f"{strength:.4f}",
            "--alignment-strength",
            f"{alignment_strength:.4f}",
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=3600,
                **config.subprocess_no_window(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self._append_message(log_file, f"AI 对齐/自然修音跳过：{exc}")
            return False
        self._append_log(log_file, cmd, proc, "Praat AI 对齐/自然修音")
        if proc.returncode == 0 and output.is_file():
            return True
        detail = self._error_tail(proc.stdout, proc.stderr)
        self._append_message(log_file, f"AI 对齐/自然修音失败，继续原始增强：{detail}")
        return False

    @staticmethod
    def _append_log(
        log_file: Path | None,
        cmd: list[str],
        proc: subprocess.CompletedProcess[str],
        title: str = "AI 歌声增强",
    ) -> None:
        if log_file is None:
            return
        try:
            with log_file.open("a", encoding="utf-8") as handle:
                handle.write(f"\n----- {title}输出 -----\n")
                handle.write("$ " + " ".join(cmd) + "\n")
                handle.write((proc.stdout or "") + "\n")
                if proc.stderr:
                    handle.write("----- stderr -----\n" + proc.stderr + "\n")
                handle.write(f"----- 子进程退出码 -----\n{proc.returncode}\n")
        except OSError:
            pass

    @staticmethod
    def _append_message(log_file: Path | None, message: str) -> None:
        if log_file is None:
            return
        try:
            with log_file.open("a", encoding="utf-8") as handle:
                handle.write(f"\n{message}\n")
        except OSError:
            pass

    @staticmethod
    def _error_tail(stdout: str | None, stderr: str | None) -> str:
        combined = ((stdout or "") + "\n" + (stderr or "")).strip()
        for line in combined.splitlines():
            if line.startswith("VOCAL_ENHANCE_ERR"):
                return line[len("VOCAL_ENHANCE_ERR") :].strip()
        lines = [line.strip() for line in combined.splitlines() if line.strip()]
        return " | ".join(lines[-4:]) if lines else "未知错误"
