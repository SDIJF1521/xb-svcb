"""AI 歌声增强封装：在独立环境中运行 DeepFilterNet 与 Pedalboard。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import config


class VocalEnhancementProcessor:
    """把模型推理后的人声送入可选的两层增强流水线。"""

    LEVEL_BASIC = "basic"
    LEVEL_ADVANCED = "advanced"
    LEVELS = {LEVEL_BASIC, LEVEL_ADVANCED}

    @property
    def available(self) -> bool:
        return config.vocal_enhancement_ready()

    def version(self) -> str | None:
        return "DeepFilterNet + Pedalboard（精细母带）" if self.available else None

    def enhance(
        self,
        source: Path,
        output: Path,
        *,
        level: str = LEVEL_BASIC,
        device: str = "auto",
        log_file: Path | None = None,
        reference: Path | None = None,
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

        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            output.unlink(missing_ok=True)
        except OSError as exc:
            raise RuntimeError(f"无法清理旧的歌声增强输出: {output}") from exc

        cmd = [
            str(config.VOCAL_ENHANCEMENT_PYTHON),
            str(config.VOCAL_ENHANCEMENT_WORKER),
            "--input",
            str(source),
            "--output",
            str(output),
            "--level",
            normalized_level,
            "--device",
            str(device or "auto"),
        ]
        if reference is not None:
            cmd.extend(["--reference", str(reference)])
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

        self._append_log(log_file, cmd, proc)
        if proc.returncode != 0 or not output.is_file():
            detail = self._error_tail(proc.stdout, proc.stderr)
            raise RuntimeError(
                f"AI 歌声增强失败（子进程退出码 {proc.returncode}）: {detail}"
            )
        return output

    @staticmethod
    def _append_log(
        log_file: Path | None,
        cmd: list[str],
        proc: subprocess.CompletedProcess[str],
    ) -> None:
        if log_file is None:
            return
        try:
            with log_file.open("a", encoding="utf-8") as handle:
                handle.write("\n----- AI 歌声增强输出 -----\n")
                handle.write("$ " + " ".join(cmd) + "\n")
                handle.write((proc.stdout or "") + "\n")
                if proc.stderr:
                    handle.write("----- stderr -----\n" + proc.stderr + "\n")
                handle.write(f"----- 子进程退出码 -----\n{proc.returncode}\n")
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
