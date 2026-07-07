"""SVC 推理引擎封装：调用用户本地的 so-vits-svc 4.1 环境进行真实歌声转换。

真实推理通过子进程在 ``config.SVC_PYTHON``（用户的 so-vits-svc conda 环境）中运行
``svc_worker.py``，加载主模型 + 浅扩散模型完成转换。

当推理环境不可用（仓库/解释器缺失）时，降级为标准库 ``wave`` 生成占位音频，
保证未配置推理环境时整条链路仍可演示。
"""

from __future__ import annotations

import math
import os
import struct
import subprocess
import wave
from pathlib import Path
from typing import Optional

import config
from domain import InferenceParams


class SvcEngine:
    # 框架标识：供 EngineRegistry 按模型 framework 路由
    framework = "so-vits-svc"

    @property
    def available(self) -> bool:
        """是否具备真实推理能力（仓库 + worker + 解释器齐备）。"""
        return config.svc_engine_ready()

    def device(self) -> str:
        return "cuda (so-vits-svc env)" if self.available else "cpu (simulated)"

    def version(self) -> Optional[str]:
        if not self.available:
            return None
        repo = config.SOVITS_REPO
        return f"so-vits-svc @ {repo.name}" if repo else "so-vits-svc"

    # 强制切片时长（秒）：长音频按此切段逐段推理，控制显存峰值，避免 8GB 显存 OOM
    _CLIP_SECONDS = 30.0

    @staticmethod
    def _ratio_to_kstep(diffusion_ratio: float) -> int:
        """扩散占比 (0~1) 映射到浅扩散步数 k_step；0.5 对应 so-vits 默认 100。"""
        ratio = max(0.0, min(1.0, diffusion_ratio))
        return max(1, round(ratio * 200))

    def infer(
        self,
        model: dict,
        vocals: Path,
        out_path: Path,
        params: InferenceParams,
        duration: float,
        log_file: Optional[Path] = None,
    ) -> Path:
        """执行歌声转换推理，主模型 + 浅扩散模型共同作用，输出转换后人声 WAV。

        ``model`` 为已解析的文件角色字典，包含 ``main_model_path`` / ``main_config_path``
        / ``diffusion_model_path`` / ``diffusion_config_path``。
        环境就绪时调子进程跑真实推理；否则降级为占位音频。真实推理失败会抛出异常，
        以便上层把任务标记为失败并展示错误信息。
        """
        main_model = (model or {}).get("main_model_path", "") or ""
        main_config = (model or {}).get("main_config_path", "") or ""
        diffusion_model = (model or {}).get("diffusion_model_path", "") or ""
        diffusion_config = (model or {}).get("diffusion_config_path", "") or ""
        out_path.parent.mkdir(parents=True, exist_ok=True)
        self._clear_output(out_path)

        ready = (
            self.available
            and bool(main_model)
            and Path(main_model).exists()
            and bool(main_config)
            and Path(main_config).exists()
            and Path(vocals).exists()
        )
        if not ready:
            # 降级：环境/模型缺失时生成占位音频，保证链路可跑通
            self._write_tone_wav(
                out_path, max(duration, 1.0), params.pitch, max(0.0, min(1.0, params.diffusion_ratio))
            )
            return out_path

        self._run_worker(
            main_model=main_model,
            main_config=main_config,
            diffusion_model=diffusion_model,
            diffusion_config=diffusion_config,
            vocals=Path(vocals),
            out_path=out_path,
            params=params,
            log_file=log_file,
        )
        return out_path

    def extract_f0(
        self,
        vocals: Path,
        out_npy: Path,
        main_config: str,
        params: InferenceParams,
        log_file: Optional[Path] = None,
    ) -> Optional[dict]:
        """在干净人声上真实提取 F0，返回统计信息字典；环境/配置缺失时返回 None。

        统计字段：voiced_ratio（浊音占比）、median_hz（基频中位数）、note（音名）、npy（曲线路径）。
        F0 提取属于辅助/校验步骤，失败不抛异常，仅返回 None 由上层记录并继续。
        """
        if not self.available or not main_config or not Path(main_config).exists():
            return None
        if not Path(vocals).exists():
            return None
        out_npy.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            str(config.SVC_PYTHON),
            str(config.F0_WORKER),
            "--repo",
            str(config.SOVITS_REPO),
            "--config",
            str(main_config),
            "--input",
            str(vocals),
            "--out-npy",
            str(out_npy),
            "--f0",
            params.f0_method or "rmvpe",
            "--device",
            params.device or "auto",
        ]
        f0_env = os.environ.copy()
        f0_env["PYTHONIOENCODING"] = "utf-8"
        f0_env["PYTHONUTF8"] = "1"
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(config.SOVITS_REPO),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=f0_env,
                timeout=900,
                **config.subprocess_no_window(),
            )
        except (OSError, subprocess.SubprocessError):
            return None

        if log_file is not None:
            try:
                with log_file.open("a", encoding="utf-8") as f:
                    f.write("\n----- F0 提取输出 -----\n")
                    f.write("$ " + " ".join(cmd) + "\n")
                    f.write((proc.stdout or "") + "\n")
                    if proc.stderr:
                        f.write("----- stderr -----\n" + proc.stderr + "\n")
            except OSError:
                pass

        for line in (proc.stdout or "").splitlines():
            if line.startswith("F0_OK"):
                parts = line.split("\t")
                if len(parts) >= 5:
                    try:
                        return {
                            "voiced_ratio": float(parts[1]),
                            "median_hz": float(parts[2]),
                            "note": parts[3],
                            "npy": parts[4],
                        }
                    except ValueError:
                        return None
        return None

    def _run_worker(
        self,
        main_model: str,
        main_config: str,
        diffusion_model: str,
        diffusion_config: str,
        vocals: Path,
        out_path: Path,
        params: InferenceParams,
        log_file: Optional[Path] = None,
    ) -> None:
        repo = config.SOVITS_REPO
        cmd = [
            str(config.SVC_PYTHON),
            str(config.SVC_WORKER),
            "--repo",
            str(repo),
            "--main-model",
            str(main_model),
            "--main-config",
            str(main_config),
            "--input",
            str(vocals),
            "--output",
            str(out_path),
            "--tran",
            str(int(params.pitch)),
            "--device",
            params.device or "auto",
            "--f0",
            params.f0_method or "rmvpe",
            "--k-step",
            str(self._ratio_to_kstep(params.diffusion_ratio)),
            "--clip",
            str(self._CLIP_SECONDS),
        ]
        if params.speaker:
            cmd += ["--speaker", params.speaker]

        use_diffusion = (
            bool(diffusion_model)
            and Path(diffusion_model).exists()
            and bool(diffusion_config)
            and Path(diffusion_config).exists()
        )
        if use_diffusion:
            cmd += [
                "--diffusion-model",
                str(diffusion_model),
                "--diffusion-config",
                str(diffusion_config),
            ]

        # 缓解显存碎片，降低长音频推理 OOM 概率
        env = os.environ.copy()
        env["PYTORCH_CUDA_ALLOC_CONF"] = "max_split_size_mb:128"
        # 强制子进程以 UTF-8 输出，避免中文报错（如"模型加载失败"）在管道里变成乱码
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(repo),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=3600,
                **config.subprocess_no_window(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"推理子进程启动失败: {exc}") from exc

        # 把子进程完整输出写入作品日志，便于排查
        if log_file is not None:
            try:
                with log_file.open("a", encoding="utf-8") as f:
                    f.write("\n----- so-vits-svc 推理输出 -----\n")
                    f.write("$ " + " ".join(cmd) + "\n")
                    f.write((proc.stdout or "") + "\n")
                    if proc.stderr:
                        f.write("----- stderr -----\n" + proc.stderr + "\n")
            except OSError:
                pass

        if proc.returncode != 0 or not out_path.exists():
            tail = self._error_tail(proc.stdout, proc.stderr)
            raise RuntimeError(f"so-vits-svc 推理失败: {tail}")

    @staticmethod
    def _error_tail(stdout: str | None, stderr: str | None) -> str:
        """提取子进程输出的关键错误信息（优先 SVC_ERR 行，否则取末尾几行）。"""
        text = ((stdout or "") + "\n" + (stderr or "")).strip()
        for line in text.splitlines():
            if line.startswith("SVC_ERR"):
                return line[len("SVC_ERR") :].strip()
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return " | ".join(lines[-3:]) if lines else "未知错误"

    # ---- 降级占位音频 ----
    # 最长生成秒数（避免为长歌曲逐样本生成造成卡顿）
    _PREVIEW_MAX_SECONDS = 15.0

    @classmethod
    def _write_tone_wav(
        cls, out_path: Path, seconds: float, pitch: int, diffusion_ratio: float
    ) -> None:
        """生成占位正弦波（仅在推理环境缺失时使用，用于演示链路）。"""
        sample_rate = 44100
        base_freq = 220.0 * (2 ** (pitch / 12.0))
        n_samples = int(min(seconds, cls._PREVIEW_MAX_SECONDS) * sample_rate)
        amplitude = 8000
        fade = 2000  # 缓入缓出样本数，避免爆音
        main_w = 1.0 - diffusion_ratio
        diff_w = diffusion_ratio
        step = 2 * math.pi * base_freq / sample_rate
        values = []
        for i in range(n_samples):
            env = min(1.0, i / fade, (n_samples - i) / fade)
            main_tone = math.sin(step * i)
            diff_tone = math.sin(step * 1.5 * i)
            mixed = main_w * main_tone + diff_w * diff_tone
            values.append(int(amplitude * env * mixed))
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(struct.pack("<%dh" % n_samples, *values))

    @staticmethod
    def _clear_output(out_path: Path) -> None:
        try:
            out_path.unlink(missing_ok=True)
        except OSError as exc:
            raise RuntimeError(f"无法清理旧推理输出: {out_path}") from exc
