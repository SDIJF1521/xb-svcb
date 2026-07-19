"""SeedVC 推理引擎封装：调用独立 ``.venv-seedvc`` 中的官方 Seed-VC。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Optional

import config
from domain import InferenceParams
from infrastructure.inference_device import environment_device_label


class SeedVcEngine:
    # 框架标识：供 EngineRegistry 按模型 framework 路由
    framework = "seed-vc"

    @property
    def available(self) -> bool:
        """是否具备真实 SeedVC 推理能力（repo + .venv-seedvc + worker 齐备）。"""
        return config.seedvc_engine_ready()

    def device(self) -> str:
        return (
            environment_device_label(config.SEEDVC_PYTHON, "seed-vc env")
            if self.available
            else "CPU (simulated)"
        )

    def version(self) -> Optional[str]:
        if not self.available:
            return None
        repo = config.SEEDVC_REPO
        return f"Seed-VC @ {repo.name}" if repo else "Seed-VC"

    @staticmethod
    def _diffusion_steps(ratio: float) -> int:
        """复用现有 0~1 参数，映射到 SeedVC 推荐的 10~50 扩散步数范围。"""
        value = max(0.0, min(1.0, float(ratio)))
        return max(1, round(10 + value * 40))

    def infer(
        self,
        model: dict[str, Any],
        vocals: Path,
        out_path: Path,
        params: InferenceParams,
        duration: float,
        log_file: Optional[Path] = None,
    ) -> Path:
        """执行 SeedVC 歌声转换；条件不完整时明确失败。"""
        out_path.parent.mkdir(parents=True, exist_ok=True)
        self._clear_output(out_path)
        main_model = (model or {}).get("main_model_path", "") or ""
        main_config = (model or {}).get("main_config_path", "") or ""
        reference_audio = params.reference_audio or ""

        ready = (
            self.available
            and bool(main_model)
            and Path(main_model).exists()
            and bool(main_config)
            and Path(main_config).exists()
            and bool(reference_audio)
            and Path(reference_audio).exists()
            and Path(vocals).exists()
        )
        if not ready:
            missing = []
            if not self.available:
                missing.append("SeedVC 推理环境未就绪")
            if not main_model or not Path(main_model).is_file():
                missing.append(f"SeedVC 模型不存在: {main_model or '未配置'}")
            if not main_config or not Path(main_config).is_file():
                missing.append(f"SeedVC 配置不存在: {main_config or '未配置'}")
            if not reference_audio or not Path(reference_audio).is_file():
                missing.append(f"参考音频不存在: {reference_audio or '未配置'}")
            if not Path(vocals).is_file():
                missing.append(f"输入人声不存在: {vocals}")
            raise RuntimeError("；".join(missing) or "SeedVC 推理条件不完整")

        self._run_worker(
            main_model,
            main_config,
            reference_audio,
            Path(vocals),
            out_path,
            params,
            log_file,
        )
        return out_path

    def _run_worker(
        self,
        main_model: str,
        main_config: str,
        reference_audio: str,
        vocals: Path,
        out_path: Path,
        params: InferenceParams,
        log_file: Optional[Path] = None,
    ) -> None:
        cmd = [
            str(config.SEEDVC_PYTHON),
            str(config.SEEDVC_WORKER),
            "--repo",
            str(config.SEEDVC_REPO),
            "--checkpoint",
            str(main_model),
            "--config",
            str(main_config),
            "--reference",
            str(reference_audio),
            "--input",
            str(vocals),
            "--output",
            str(out_path),
            "--device",
            params.device or "auto",
            "--pitch",
            str(int(params.pitch)),
            "--diffusion-steps",
            str(self._diffusion_steps(params.diffusion_ratio)),
            "--length-adjust",
            "1.0",
            "--cfg-rate",
            "0.7",
            "--fp16",
            "False" if (params.device or "").lower() == "cpu" else "True",
        ]
        env = os.environ.copy()
        env["PYTORCH_CUDA_ALLOC_CONF"] = "max_split_size_mb:128"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        hf_mirror = (
            env.get("XB_HF_MIRROR")
            or env.get("HF_ENDPOINT")
            or "https://hf-mirror.com"
        ).strip().rstrip("/")
        env.setdefault("XB_HF_MIRROR", hf_mirror)
        env.setdefault("HF_ENDPOINT", hf_mirror)
        env.setdefault("HUGGINGFACE_HUB_ENDPOINT", hf_mirror)

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(config.SEEDVC_REPO),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=3600,
                **config.subprocess_no_window(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"SeedVC 推理子进程启动失败: {exc}") from exc

        if log_file is not None:
            try:
                with log_file.open("a", encoding="utf-8") as f:
                    f.write("\n----- SeedVC 推理输出 -----\n")
                    f.write("$ " + " ".join(cmd) + "\n")
                    f.write((proc.stdout or "") + "\n")
                    if proc.stderr:
                        f.write("----- stderr -----\n" + proc.stderr + "\n")
            except OSError:
                pass

        if proc.returncode != 0 or not out_path.exists():
            tail = self._error_tail(proc.stdout, proc.stderr)
            raise RuntimeError(f"SeedVC 推理失败: {tail}")

    @staticmethod
    def _error_tail(stdout: str | None, stderr: str | None) -> str:
        text = ((stdout or "") + "\n" + (stderr or "")).strip()
        if "cuda error: out of memory" in text.lower() or "torch.cuda.outofmemoryerror" in text.lower():
            return "CUDA 显存不足：请关闭占用显卡的软件后重试；仍失败时改用 CPU 或降低扩散步数。"
        for line in text.splitlines():
            if line.startswith("SEEDVC_ERR"):
                return line[len("SEEDVC_ERR") :].strip()
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return " | ".join(lines[-3:]) if lines else "未知错误"

    @staticmethod
    def _clear_output(out_path: Path) -> None:
        try:
            out_path.unlink(missing_ok=True)
        except OSError as exc:
            raise RuntimeError(f"无法清理旧推理输出: {out_path}") from exc
