"""Ultimate Vocal Remover (UVR) 封装：人声 / 伴奏分离。

通过独立 venv 子进程运行 ``audio-separator``（UVR 的库版本），复用本地 UVR 的
MDX 模型权重，将歌曲分离为人声与伴奏两轨。

若分离环境未就绪，则进入降级模式：直接把原始音频作为"人声"返回（无伴奏），
保证流水线可端到端跑通。
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import config


@dataclass
class SeparationResult:
    """分离结果：人声轨 + 可选伴奏轨。"""

    vocals: Path
    instrumental: Optional[Path] = None
    simulated: bool = False


class UvrTool:
    @property
    def available(self) -> bool:
        """是否具备真实分离能力（venv + worker + 模型齐备）。"""
        return config.uvr_ready()

    def version(self) -> Optional[str]:
        if not self.available:
            return None
        return f"audio-separator · {config.UVR_MODEL}"

    def separate(
        self, src: Path, out_dir: Path, model: str = "", device: str = "auto"
    ) -> SeparationResult:
        """分离人声/伴奏。环境就绪时调子进程真实分离；否则降级返回原音频。"""
        out_dir.mkdir(parents=True, exist_ok=True)
        if not self.available or not src or not Path(src).exists():
            return SeparationResult(vocals=Path(src), instrumental=None, simulated=True)

        model_name = model if model and (config.UVR_MODEL_DIR / model).exists() else config.UVR_MODEL
        cmd = [
            str(config.UVR_PYTHON),
            str(config.UVR_WORKER),
            "--model-dir",
            str(config.UVR_MODEL_DIR),
            "--model",
            model_name,
            "--input",
            str(src),
            "--out-dir",
            str(out_dir),
            "--device",
            device or "auto",
        ]
        # 强制子进程以 UTF-8 读写，避免中文路径在管道里被 GBK/UTF-8 编码错位损坏
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=1800,
                **config.subprocess_no_window(),
            )
        except (OSError, subprocess.SubprocessError):
            return SeparationResult(vocals=Path(src), instrumental=None, simulated=True)

        # 把分离子进程输出写入日志，便于排查
        try:
            with (out_dir / "uvr.log").open("a", encoding="utf-8") as f:
                f.write("$ " + " ".join(cmd) + "\n")
                f.write((proc.stdout or "") + "\n")
                if proc.stderr:
                    f.write("----- stderr -----\n" + proc.stderr + "\n")
        except OSError:
            pass

        # 优先读取 UTF-8 JSON 结果文件（不受 stdout 管道编码影响），回退到解析 stdout
        result = self._read_result_json(out_dir) or self._parse_output(proc.stdout)
        if result is None or not result.vocals.exists():
            # 分离失败时降级，保证后续推理仍可进行
            return SeparationResult(vocals=Path(src), instrumental=None, simulated=True)
        return result

    @staticmethod
    def _read_result_json(out_dir: Path) -> Optional[SeparationResult]:
        f = out_dir / "uvr_result.json"
        if not f.exists():
            return None
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        vocals = data.get("vocals")
        if not vocals:
            return None
        inst = data.get("instrumental")
        return SeparationResult(
            vocals=Path(vocals),
            instrumental=Path(inst) if inst else None,
        )

    @staticmethod
    def _parse_output(stdout: str | None) -> Optional[SeparationResult]:
        for line in (stdout or "").splitlines():
            if line.startswith("UVR_OK"):
                parts = line.split("\t")
                vocals = Path(parts[1]) if len(parts) > 1 and parts[1] else None
                instrumental = Path(parts[2]) if len(parts) > 2 and parts[2] else None
                if vocals:
                    return SeparationResult(vocals=vocals, instrumental=instrumental)
        return None
