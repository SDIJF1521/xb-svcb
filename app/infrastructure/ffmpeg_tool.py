"""ffmpeg / ffprobe 封装：音频时长探测与格式转换。

若系统未安装 ffmpeg，相关方法将降级（返回 None 或回退到标准库实现）。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Optional


class FfmpegTool:
    def __init__(self) -> None:
        self.ffmpeg = shutil.which("ffmpeg")
        self.ffprobe = shutil.which("ffprobe")

    @property
    def available(self) -> bool:
        return self.ffmpeg is not None

    def version(self) -> Optional[str]:
        if not self.ffmpeg:
            return None
        try:
            out = subprocess.run(
                [self.ffmpeg, "-version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
            )
            first = (out.stdout or "").splitlines()[0] if out.stdout else ""
            m = re.search(r"ffmpeg version (\S+)", first)
            return m.group(1) if m else first or None
        except (OSError, subprocess.SubprocessError):
            return None

    def probe_duration(self, src: Path) -> Optional[float]:
        """返回音频时长（秒）。优先用 ffprobe，回退到 wave。"""
        if self.ffprobe:
            try:
                out = subprocess.run(
                    [
                        self.ffprobe,
                        "-v",
                        "error",
                        "-show_entries",
                        "format=duration",
                        "-of",
                        "default=noprint_wrappers=1:nokey=1",
                        str(src),
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=15,
                )
                value = (out.stdout or "").strip()
                if value:
                    return float(value)
            except (OSError, subprocess.SubprocessError, ValueError):
                pass
        return self._wave_duration(src)

    @staticmethod
    def _wave_duration(src: Path) -> Optional[float]:
        try:
            with wave.open(str(src), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                return frames / float(rate) if rate else None
        except (wave.Error, OSError, EOFError):
            return None

    def convert(self, src: Path, dst: Path, sample_rate: int = 44100) -> bool:
        """转码到目标文件。成功返回 True。"""
        if not self.ffmpeg:
            return False
        try:
            res = subprocess.run(
                [
                    self.ffmpeg,
                    "-y",
                    "-i",
                    str(src),
                    "-ar",
                    str(sample_rate),
                    str(dst),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
            )
            return res.returncode == 0 and dst.exists()
        except (OSError, subprocess.SubprocessError):
            return False

    def mix(
        self, vocals: Path, instrumental: Path, dst: Path, sample_rate: int = 44100
    ) -> bool:
        """把人声与伴奏混合为成品。成功返回 True。"""
        if not self.ffmpeg:
            return False
        try:
            # 先把人声与伴奏统一为同采样率的立体声，避免单声道/立体声不匹配
            # 导致 amix 失败（失败会让上层回退成"仅干声"，表现为没有伴奏）。
            filt = (
                f"[0:a]aresample={sample_rate},aformat=channel_layouts=stereo[v];"
                f"[1:a]aresample={sample_rate},aformat=channel_layouts=stereo[m];"
                "[v][m]amix=inputs=2:duration=longest:normalize=0[a]"
            )
            res = subprocess.run(
                [
                    self.ffmpeg,
                    "-y",
                    "-i",
                    str(vocals),
                    "-i",
                    str(instrumental),
                    "-filter_complex",
                    filt,
                    "-map",
                    "[a]",
                    "-ar",
                    str(sample_rate),
                    str(dst),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
            )
            return res.returncode == 0 and dst.exists()
        except (OSError, subprocess.SubprocessError):
            return False
