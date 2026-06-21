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

import config


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
                **config.subprocess_no_window(),
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
                    **config.subprocess_no_window(),
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
                **config.subprocess_no_window(),
            )
            return res.returncode == 0 and dst.exists()
        except (OSError, subprocess.SubprocessError):
            return False

    def slice(
        self,
        src: Path,
        start: float,
        end: float,
        dst: Path,
        sample_rate: int = 44100,
    ) -> bool:
        """从 ``src`` 精确截取 [start, end] 区间为统一格式 WAV（多模型分句用）。

        采用「-i 后置 -ss」的精确定位（先解码再裁剪），保证各句边界对齐，
        拼接后总时长不漂移。成功返回 True。
        """
        if not self.ffmpeg:
            return False
        start = max(0.0, float(start))
        end = max(start, float(end))
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            res = subprocess.run(
                [
                    self.ffmpeg,
                    "-y",
                    "-i",
                    str(src),
                    "-ss",
                    f"{start:.3f}",
                    "-to",
                    f"{end:.3f}",
                    "-ar",
                    str(sample_rate),
                    "-ac",
                    "2",
                    str(dst),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                **config.subprocess_no_window(),
            )
            return res.returncode == 0 and dst.exists()
        except (OSError, subprocess.SubprocessError):
            return False

    def concat(self, parts: list[Path], dst: Path, sample_rate: int = 44100) -> bool:
        """按顺序拼接多个音频片段为一个完整文件（多模型人声合并用）。

        关键：必须用 concat **滤镜**而非 concat demuxer。各片段采样率可能不同
        （SVC 模型按自身 target_sample 写出，可能不是 44100；而切片是 44100），
        demuxer 会按首段采样率重放后续片段，表现为「忽快忽慢 / 整体加速」。
        滤镜会先按各文件自身头信息正确解码、逐个重采样到统一采样率再拼接。
        成功返回 True。
        """
        if not self.ffmpeg:
            return False
        usable = [p for p in parts if p and Path(p).exists()]
        if not usable:
            return False
        dst.parent.mkdir(parents=True, exist_ok=True)
        cmd: list[str] = [self.ffmpeg, "-y"]
        for p in usable:
            cmd += ["-i", str(p)]
        filt = ""
        labels = ""
        for i in range(len(usable)):
            filt += (
                f"[{i}:a]aresample={sample_rate},"
                f"aformat=sample_fmts=s16:channel_layouts=stereo[a{i}];"
            )
            labels += f"[a{i}]"
        filt += f"{labels}concat=n={len(usable)}:v=0:a=1[a]"
        cmd += [
            "-filter_complex",
            filt,
            "-map",
            "[a]",
            "-ar",
            str(sample_rate),
            "-ac",
            "2",
            str(dst),
        ]
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
                **config.subprocess_no_window(),
            )
            return res.returncode == 0 and dst.exists()
        except (OSError, subprocess.SubprocessError):
            return False

    def pad_or_trim(
        self, src: Path, dst: Path, seconds: float, sample_rate: int = 44100
    ) -> bool:
        """把片段规整为「恰好 seconds 秒」的统一格式 WAV（不足补静音、超出截断）。

        多模型逐段推理后，各段时长可能与原切片有微小出入；逐段锁定到原时长可
        避免累计漂移，保证合并后人声与伴奏始终对齐、总时长与原曲一致。
        """
        if not self.ffmpeg:
            return False
        seconds = max(0.05, float(seconds))
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            res = subprocess.run(
                [
                    self.ffmpeg,
                    "-y",
                    "-i",
                    str(src),
                    "-af",
                    f"aresample={sample_rate},apad",
                    "-t",
                    f"{seconds:.3f}",
                    "-ar",
                    str(sample_rate),
                    "-ac",
                    "2",
                    str(dst),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                **config.subprocess_no_window(),
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
                **config.subprocess_no_window(),
            )
            return res.returncode == 0 and dst.exists()
        except (OSError, subprocess.SubprocessError):
            return False
