"""RVC 推理引擎封装：在独立运行时中通过 ``rvc_worker`` 调用 rvc-python 转换歌声。

与 So-VITS 引擎同构：环境就绪时子进程跑真实推理，条件缺失时明确失败。
由 ``EngineRegistry`` 按模型 ``framework`` 选择。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Optional

import config
from domain import InferenceParams
from infrastructure.inference_device import environment_device_label, normalize_device
from infrastructure.persistent_worker import PersistentInferenceSession


class RvcEngine:
    # 框架标识：供 EngineRegistry 按模型 framework 路由
    framework = "rvc"

    @property
    def available(self) -> bool:
        """是否具备真实 RVC 推理能力（隔离解释器 + worker 齐备）。"""
        return bool(
            config.RVC_WORKER.is_file()
            and (config.RVC_PYTHON and config.RVC_PYTHON.is_file()
                 or config.RVC_DIRECTML_PYTHON and config.RVC_DIRECTML_PYTHON.is_file())
        )

    @staticmethod
    def _python_for_device(requested: str = "auto") -> Optional[Path]:
        """Select the runtime matching the requested backend.

        DirectML has a separate Torch build and cannot share the ROCm/CUDA
        interpreter. Keep the primary route for auto/ROCm/CUDA and switch only
        an explicit DirectML request to the independent runtime.
        """
        if normalize_device(requested) == "directml":
            return getattr(config, "RVC_DIRECTML_PYTHON", None)
        primary = getattr(config, "RVC_PYTHON", None)
        if primary and primary.is_file():
            return primary
        # A DirectML-only installation has no primary route. It remains usable
        # with auto rather than silently reporting that RVC is unavailable.
        return getattr(config, "RVC_DIRECTML_PYTHON", None)

    def device(self) -> str:
        python = self._python_for_device("auto")
        return (
            environment_device_label(python, "rvc env")
            if python and python.is_file() and config.RVC_WORKER.is_file()
            else "CPU (simulated)"
        )

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
        """执行 RVC 歌声转换；环境或模型缺失时明确失败。"""
        out_path.parent.mkdir(parents=True, exist_ok=True)
        self._clear_output(out_path)
        main_model = (model or {}).get("main_model_path", "") or ""
        index_path = (model or {}).get("index_path", "") or ""

        python = self._python_for_device(params.device)
        ready = (
            bool(python and python.is_file() and config.RVC_WORKER.is_file())
            and bool(main_model)
            and Path(main_model).exists()
            and Path(vocals).exists()
        )
        if not ready:
            missing = []
            if not python or not python.is_file() or not config.RVC_WORKER.is_file():
                missing.append("RVC 推理环境未就绪")
            if not main_model or not Path(main_model).is_file():
                missing.append(f"RVC 模型不存在: {main_model or '未配置'}")
            if not Path(vocals).is_file():
                missing.append(f"输入人声不存在: {vocals}")
            raise RuntimeError("；".join(missing) or "RVC 推理条件不完整")

        self._run_worker(
            main_model, index_path, Path(vocals), out_path, params, log_file,
            python_path=python,
        )
        return out_path

    def open_realtime_session(
        self,
        model: dict[str, Any],
        params: InferenceParams,
        log_file: Optional[Path] = None,
        low_latency: bool = False,
    ) -> PersistentInferenceSession:
        """Load one RVC model once and keep it alive for successive song blocks."""
        main_model = str((model or {}).get("main_model_path") or "")
        index_path = str((model or {}).get("index_path") or "")
        python = self._python_for_device(params.device)
        if not python or not python.is_file() or not config.RVC_WORKER.is_file() or not Path(main_model).is_file():
            raise RuntimeError("RVC 实时推理环境或模型未就绪")
        command = [
            str(python),
            str(config.RVC_WORKER),
            "--server",
            "--model", main_model,
            "--device", params.device or "auto",
            "--method", params.f0_method or "rmvpe",
            "--pitch", str(int(params.pitch)),
            "--index-rate", str(float(params.index_rate)),
            "--rms-mix", str(float(params.rms_mix)),
            "--protect", str(float(params.protect)),
            "--filter-radius", str(int(params.filter_radius)),
            "--version", params.rvc_version or "v2",
        ]
        if index_path and Path(index_path).is_file():
            command += ["--index", index_path]
        if low_latency:
            command.append("--low-latency")
        env = self._worker_env()
        return PersistentInferenceSession(
            command,
            ready_marker="RVC_SERVER_READY",
            result_marker="RVC_SERVER_RESULT\t",
            env=env,
            log_file=log_file,
        )

    def _run_worker(
        self,
        main_model: str,
        index_path: str,
        vocals: Path,
        out_path: Path,
        params: InferenceParams,
        log_file: Optional[Path] = None,
        *,
        python_path: Optional[Path] = None,
    ) -> None:
        python = python_path or self._python_for_device(params.device)
        if not python:
            raise RuntimeError(
                f"RVC {params.device or 'auto'} 独立运行环境未就绪"
            )
        cmd = [
            str(python),
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

        env = self._worker_env()

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
                    f.write(f"----- 子进程退出码 -----\n{proc.returncode}\n")
            except OSError:
                pass

        if proc.returncode != 0 or not out_path.exists():
            tail = self._error_tail(proc.stdout, proc.stderr)
            raise RuntimeError(f"RVC 推理失败（子进程退出码 {proc.returncode}）: {tail}")

    @staticmethod
    def _worker_env() -> dict[str, str]:
        env = os.environ.copy()
        env["PYTORCH_CUDA_ALLOC_CONF"] = "max_split_size_mb:128"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        # FAISS is OpenMP-parallel. Let BLAS use one inner thread so an RVC
        # .index lookup does not create an OpenBLAS pool in every FAISS worker.
        # rvc_worker applies the same defaults when invoked directly.
        try:
            blas_threads = max(1, int(env.get("XB_RVC_BLAS_THREADS", "1")))
        except (TypeError, ValueError):
            blas_threads = 1
        for name in (
            "OPENBLAS_NUM_THREADS",
            "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
            "VECLIB_MAXIMUM_THREADS",
        ):
            env[name] = str(blas_threads)
        hf_mirror = (
            env.get("XB_HF_MIRROR")
            or env.get("HF_ENDPOINT")
            or "https://hf-mirror.com"
        ).strip().rstrip("/")
        env.setdefault("XB_HF_MIRROR", hf_mirror)
        env.setdefault("HF_ENDPOINT", hf_mirror)
        env.setdefault("HUGGINGFACE_HUB_ENDPOINT", hf_mirror)
        return env

    @staticmethod
    def _error_tail(stdout: str | None, stderr: str | None) -> str:
        text = ((stdout or "") + "\n" + (stderr or "")).strip()
        if "MIOpen:" in text and "Invalid elapsed time" in text:
            return (
                "ROCm/MIOpen 首次卷积算法搜索失败（Invalid elapsed time）。"
                "可先设置 MIOPEN_FIND_MODE=FAST 后重试；新版 worker 已默认使用 FAST 搜索。"
            )
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
