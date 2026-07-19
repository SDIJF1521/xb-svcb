"""DDSP-SVC inference adapter using an isolated upstream runtime."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Optional

import config
from domain import InferenceParams
from infrastructure.inference_device import probe_python_environment, runtime_device_label
from infrastructure.svc_engine import SvcEngine


class DdspSvcEngine:
    framework = "ddsp-svc"

    @property
    def available(self) -> bool:
        return config.ddsp_engine_ready()

    def device(self) -> str:
        if not self.available:
            return "CPU (simulated)"
        runtime = probe_python_environment(config.DDSP_PYTHON)
        if runtime.get("preferred") == "directml":
            return "CPU 稳定路径（AMD DDSP）"
        return runtime_device_label(runtime, "ddsp-svc env")

    def version(self) -> Optional[str]:
        if not self.available:
            return None
        repo = config.DDSP_REPO
        return f"DDSP-SVC @ {repo.name}" if repo else "DDSP-SVC"

    def infer(
        self,
        model: dict[str, Any],
        vocals: Path,
        out_path: Path,
        params: InferenceParams,
        duration: float,
        log_file: Optional[Path] = None,
    ) -> Path:
        main_model = str((model or {}).get("main_model_path") or "")
        main_config = str((model or {}).get("main_config_path") or "")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        self._clear_output(out_path)

        ready = (
            self.available
            and bool(main_model)
            and Path(main_model).is_file()
            and bool(main_config)
            and Path(main_config).is_file()
            and Path(vocals).is_file()
        )
        if not ready:
            SvcEngine._write_tone_wav(out_path, max(duration, 1.0), params.pitch, 0.0)
            return out_path

        self._run_worker(main_model, main_config, vocals, out_path, params, log_file)
        return out_path

    def _run_worker(
        self,
        main_model: str,
        main_config: str,
        vocals: Path,
        out_path: Path,
        params: InferenceParams,
        log_file: Optional[Path],
    ) -> None:
        f0_method = (params.f0_method or "rmvpe").lower()
        if f0_method == "pm":
            f0_method = "parselmouth"
        cmd = [
            str(config.DDSP_PYTHON),
            str(config.DDSP_WORKER),
            "--repo",
            str(config.DDSP_REPO),
            "--model",
            main_model,
            "--config",
            main_config,
            "--input",
            str(vocals),
            "--output",
            str(out_path),
            "--device",
            params.device or "auto",
            "--pitch",
            str(int(params.pitch)),
            "--f0",
            f0_method,
            "--infer-steps",
            str(max(1, int(params.ddsp_infer_steps))),
            "--formant-shift",
            str(max(-2.0, min(2.0, float(params.ddsp_formant_shift)))),
            "--speaker",
            params.speaker or "1",
        ]
        env = os.environ.copy()
        env["PYTORCH_CUDA_ALLOC_CONF"] = "max_split_size_mb:128"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(config.DDSP_REPO),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=3600,
                **config.subprocess_no_window(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"DDSP-SVC 推理子进程启动失败: {exc}") from exc

        if log_file is not None:
            try:
                with log_file.open("a", encoding="utf-8") as stream:
                    stream.write("\n----- DDSP-SVC 推理输出 -----\n")
                    stream.write("$ " + " ".join(cmd) + "\n")
                    stream.write((proc.stdout or "") + "\n")
                    if proc.stderr:
                        stream.write("----- stderr -----\n" + proc.stderr + "\n")
            except OSError:
                pass

        if proc.returncode != 0 or not out_path.is_file():
            raise RuntimeError(f"DDSP-SVC 推理失败: {self._error_tail(proc.stdout, proc.stderr)}")

    @staticmethod
    def _error_tail(stdout: str | None, stderr: str | None) -> str:
        text = ((stdout or "") + "\n" + (stderr or "")).strip()
        lowered = text.lower()
        if "out of memory" in lowered:
            return "CUDA 显存不足：请关闭占用显卡的软件、降低采样步数或改用 CPU。"
        for line in text.splitlines():
            if line.startswith("DDSP_ERR"):
                return line[len("DDSP_ERR") :].strip()
        lines = [line for line in text.splitlines() if line.strip()]
        return " | ".join(lines[-3:]) if lines else "未知错误"

    @staticmethod
    def _clear_output(out_path: Path) -> None:
        try:
            out_path.unlink(missing_ok=True)
        except OSError as exc:
            raise RuntimeError(f"无法清理旧推理输出: {out_path}") from exc
