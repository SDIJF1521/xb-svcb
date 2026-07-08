"""RVC 推理引擎封装：在独立 ``.venv-rvc`` 中通过 ``rvc_worker`` 调用 rvc-python 转换歌声。

与 ``SvcEngine`` 同构：环境就绪时子进程跑真实推理，否则降级为占位音频，
保证未配置 RVC 环境时整条链路仍可演示。由 ``EngineRegistry`` 按模型 ``framework`` 选择。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Optional

import config
from domain import InferenceParams
from infrastructure.svc_engine import SvcEngine


class RvcEngine:
    # 框架标识：供 EngineRegistry 按模型 framework 路由
    framework = "rvc"

    @property
    def available(self) -> bool:
        """是否具备真实 RVC 推理能力（.venv-rvc 解释器 + worker 齐备）。"""
        return config.rvc_engine_ready()

    def device(self) -> str:
        return "cuda (rvc env)" if self.available else "cpu (simulated)"

    def version(self) -> Optional[str]:
        return "rvc-python" if self.available else None

    def infer(
        self,
        model: dict[str, Any],
        vocals: Path,
        out_path: Path,
        params: InferenceParams,
        duration: float,
        log_file: Optional[Path] = None,
    ) -> Path:
        """执行 RVC 歌声转换；环境/模型缺失时降级为占位音频。"""
        out_path.parent.mkdir(parents=True, exist_ok=True)
        self._clear_output(out_path)
        main_model = (model or {}).get("main_model_path", "") or ""
        index_path = (model or {}).get("index_path", "") or ""

        ready = (
            self.available
            and bool(main_model)
            and Path(main_model).exists()
            and Path(vocals).exists()
        )
        if not ready:
            # 复用 so-vits 引擎的占位音频生成（RVC 无扩散，占比传 0）
            SvcEngine._write_tone_wav(out_path, max(duration, 1.0), params.pitch, 0.0)
            return out_path

        self._run_worker(main_model, index_path, Path(vocals), out_path, params, log_file)
        return out_path

    def _run_worker(
        self,
        main_model: str,
        index_path: str,
        vocals: Path,
        out_path: Path,
        params: InferenceParams,
        log_file: Optional[Path] = None,
    ) -> None:
        cmd = [
            str(config.RVC_PYTHON),
            str(config.RVC_WORKER),
            "--model",
            str(main_model),
            "--input",
            str(vocals),
            "--output",
            str(out_path),
            "--device",
            params.device or "auto",
            "--method",
            params.f0_method or "rmvpe",
            "--pitch",
            str(int(params.pitch)),
            "--index-rate",
            str(float(params.index_rate)),
            "--rms-mix",
            str(float(params.rms_mix)),
            "--protect",
            str(float(params.protect)),
            "--filter-radius",
            str(int(params.filter_radius)),
            "--version",
            params.rvc_version or "v2",
        ]
        if index_path and Path(index_path).exists():
            cmd += ["--index", str(index_path)]

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
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=3600,
                **config.subprocess_no_window(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"RVC 推理子进程启动失败: {exc}") from exc

        if log_file is not None:
            try:
                with log_file.open("a", encoding="utf-8") as f:
                    f.write("\n----- RVC 推理输出 -----\n")
                    f.write("$ " + " ".join(cmd) + "\n")
                    f.write((proc.stdout or "") + "\n")
                    if proc.stderr:
                        f.write("----- stderr -----\n" + proc.stderr + "\n")
            except OSError:
                pass

        if proc.returncode != 0 or not out_path.exists():
            tail = self._error_tail(proc.stdout, proc.stderr)
            raise RuntimeError(f"RVC 推理失败: {tail}")

    @staticmethod
    def _error_tail(stdout: str | None, stderr: str | None) -> str:
        text = ((stdout or "") + "\n" + (stderr or "")).strip()
        if "cuda error: out of memory" in text.lower() or "torch.cuda.outofmemoryerror" in text.lower():
            return (
                "CUDA 显存不足：请关闭占用显卡的软件后重试；仍失败时把 F0 算法改为 pm/harvest、"
                "把检索率调低或改用 CPU。"
            )
        for line in text.splitlines():
            if line.startswith("RVC_ERR"):
                return line[len("RVC_ERR") :].strip()
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return " | ".join(lines[-3:]) if lines else "未知错误"

    @staticmethod
    def _clear_output(out_path: Path) -> None:
        try:
            out_path.unlink(missing_ok=True)
        except OSError as exc:
            raise RuntimeError(f"无法清理旧推理输出: {out_path}") from exc
