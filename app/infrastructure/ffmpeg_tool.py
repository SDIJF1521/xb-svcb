"""ffmpeg / ffprobe 封装：音频时长探测与格式转换。

若系统未安装 ffmpeg，相关方法将降级（返回 None 或回退到标准库实现）。
"""

from __future__ import annotations

import math
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

    def detect_silences(
        self,
        src: Path,
        start: float = 0.0,
        end: float | None = None,
        noise_db: float = -40.0,
        min_duration: float = 0.35,
    ) -> list[dict[str, float]]:
        """Return silence intervals relative to the requested audio window."""
        if not self.ffmpeg:
            return []
        try:
            start = max(0.0, float(start or 0.0))
            source_duration = self.probe_duration(src)
            absolute_end = float(end) if end is not None else float(source_duration or 0.0)
            absolute_end = max(start, absolute_end)
            duration = absolute_end - start
            noise_db = min(-1.0, max(-90.0, float(noise_db)))
            min_duration = max(0.05, min(10.0, float(min_duration)))
        except (TypeError, ValueError):
            return []
        if duration <= 0.0:
            return []

        af = (
            f"atrim=start={start:.3f}:duration={duration:.3f},"
            "asetpts=PTS-STARTPTS,"
            f"silencedetect=noise={noise_db:.1f}dB:d={min_duration:.3f}"
        )
        try:
            res = subprocess.run(
                [
                    self.ffmpeg,
                    "-hide_banner",
                    "-v",
                    "info",
                    "-i",
                    str(src),
                    "-af",
                    af,
                    "-f",
                    "null",
                    "-",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(60, min(900, int(duration * 2 + 30))),
                **config.subprocess_no_window(),
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if res.returncode != 0:
            return []

        num = r"([-+]?\d+(?:\.\d+)?)"
        start_re = re.compile(r"silence_start:\s*" + num)
        end_re = re.compile(r"silence_end:\s*" + num + r"\s*\|\s*silence_duration:\s*" + num)
        intervals: list[dict[str, float]] = []
        current_start: float | None = None

        def add_interval(raw_start: float, raw_end: float) -> None:
            s = max(0.0, min(duration, raw_start))
            e = max(0.0, min(duration, raw_end))
            if e - s >= min_duration:
                intervals.append(
                    {
                        "start": round(s, 3),
                        "end": round(e, 3),
                        "duration": round(e - s, 3),
                    }
                )

        for line in f"{res.stdout or ''}\n{res.stderr or ''}".splitlines():
            start_match = start_re.search(line)
            if start_match:
                try:
                    current_start = float(start_match.group(1))
                except ValueError:
                    current_start = None
            end_match = end_re.search(line)
            if not end_match:
                continue
            try:
                silence_end = float(end_match.group(1))
                silence_duration = float(end_match.group(2))
            except ValueError:
                continue
            silence_start = (
                current_start
                if current_start is not None
                else silence_end - silence_duration
            )
            add_interval(silence_start, silence_end)
            current_start = None
        if current_start is not None:
            add_interval(current_start, duration)

        merged: list[dict[str, float]] = []
        for item in sorted(intervals, key=lambda x: x["start"]):
            if not merged or item["start"] > merged[-1]["end"] + 0.005:
                merged.append(dict(item))
                continue
            merged[-1]["end"] = max(merged[-1]["end"], item["end"])
            merged[-1]["duration"] = round(merged[-1]["end"] - merged[-1]["start"], 3)
        return merged

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
        fade: float = 0.0,
    ) -> bool:
        """从 ``src`` 精确截取 [start, end] 区间为统一格式 WAV（多模型分句用）。

        采用「-ss 前置（输入定位）+ -t 限长」的方式：输入定位会把片段时间戳
        归零，保证各句时长精确、拼接后总时长不漂移（源为 WAV/PCM，定位为样本级精确）。

        ``fade`` > 0 时在片段两端各加一段时长 ``fade`` 秒的淡入/淡出，使片段
        首尾归零——拼接处不再出现因波形跳变产生的「咔哒声 / 卡顿」，且不改变
        片段时长（淡变发生在片段内部），整曲与伴奏仍精确对齐。

        注意：淡变 ``afade`` 的 ``st`` 以片段内部时间（从 0 计）为基准，因此
        必须用输入定位让时间戳归零；若用输出定位（-i 后置 -ss）会保留绝对时间戳，
        导致 fade-out 立即触发把整段变静音（表现为「成品只剩伴奏」）。
        """
        if not self.ffmpeg:
            return False
        start = max(0.0, float(start))
        end = max(start, float(end))
        dur = max(0.0, end - start)
        dst.parent.mkdir(parents=True, exist_ok=True)
        af = f"aresample={sample_rate}"
        f = min(float(fade), dur / 2.0) if (fade and dur > 0) else 0.0
        if f > 0.0:
            af += (
                f",afade=t=in:st=0:d={f:.3f}"
                f",afade=t=out:st={max(0.0, dur - f):.3f}:d={f:.3f}"
            )
        try:
            res = subprocess.run(
                [
                    self.ffmpeg,
                    "-y",
                    "-ss",
                    f"{start:.3f}",
                    "-i",
                    str(src),
                    "-t",
                    f"{dur:.3f}",
                    "-af",
                    af,
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

    def concat_crossfade(
        self,
        parts: list[Path],
        dst: Path,
        xf: float = 0.03,
        sample_rate: int = 44100,
    ) -> bool:
        """按顺序用「交叉淡化」拼接多个片段（多模型换人处用）。

        相比 concat 的硬拼接，``acrossfade`` 让相邻片段在边界处重叠混合，既消除
        波形跳变产生的咔哒声/卡顿，又不会像「淡出到静音再淡入」那样在每个边界
        留下音量塌陷。各片段除最后一段外都向后多借 ``xf`` 秒素材，使交叉淡化
        消耗的重叠量被补回，拼接后总时长保持不变、人声与伴奏精确对齐。

        要求各片段时长 ≥ ``xf``（调用方按整句/整段切片，远大于 xf）。成功返回 True。
        """
        if not self.ffmpeg:
            return False
        usable = [p for p in parts if p and Path(p).exists()]
        if not usable:
            return False
        dst.parent.mkdir(parents=True, exist_ok=True)
        if len(usable) == 1:
            return self.convert(usable[0], dst, sample_rate)
        cmd: list[str] = [self.ffmpeg, "-y"]
        for p in usable:
            cmd += ["-i", str(p)]
        filt = ""
        for i in range(len(usable)):
            filt += (
                f"[{i}:a]aresample={sample_rate},"
                f"aformat=sample_fmts=s16:channel_layouts=stereo[a{i}];"
            )
        prev = "[a0]"
        last = len(usable) - 1
        for i in range(1, len(usable)):
            out = "[out]" if i == last else f"[x{i}]"
            filt += f"{prev}[a{i}]acrossfade=d={xf:.3f}:c1=tri:c2=tri{out};"
            prev = out
        filt = filt.rstrip(";")
        cmd += [
            "-filter_complex",
            filt,
            "-map",
            "[out]",
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

    def mix_vocals(
        self, inputs: list[Path], dst: Path, sample_rate: int = 44100
    ) -> bool:
        """把多路人声（同一句、不同模型）叠加为「合唱」人声。成功返回 True。

        若只是把多路同音高人声直接相加，它们高度相干、相互掩盖，听感上会糊成
        「一个更响的声音」而非「多人合唱」。为让每个声部都清晰可辨，这里对每一
        路做去相关处理：

        1. **恒功率声像分布** —— 把 N 个声部沿立体声场均匀铺开（左→右），
           人耳能从不同方位分辨出不同声部；
        2. **微失谐（detune）** —— 给每路 ±几音分的轻微变调（``asetrate``+``atempo``
           保持时长不变），破坏「同音高完全重合」，形成自然的合唱团厚度；
        3. **微延迟去相关（Haas）** —— 每路加几毫秒不等延迟，破坏相位对齐、进一步
           拉宽声场（仍被感知为同一句、不串拍）；
        4. **等响度增益补偿** —— 去相关后按略高于 ``1/sqrt(N)`` 压低再 ``amix`` 求和
           （``normalize=0``），最后软限幅 ``alimiter`` 防破音，使合唱句与独唱句
           整体响度大体一致。
        """
        if not self.ffmpeg:
            return False
        srcs = [p for p in inputs if p and Path(p).exists()]
        if not srcs:
            return False
        if len(srcs) == 1:
            return self.convert(srcs[0], dst, sample_rate)
        try:
            n = len(srcs)
            # 去相关后更接近能量相加，给 1/sqrt(N) 一点回补避免合唱句偏轻
            gain = 1.0 / (n ** 0.5) * 1.12
            spread = 0.85  # 声像展开范围（1.0=完全左右，过宽会听感分离失衡）
            # 每路微失谐（音分）/ 微延迟（ms）模板：首路居中不动，其余左右展开
            cents_tbl = [0.0, 9.0, -9.0, 6.0, -6.0, 12.0, -12.0, 4.0]
            delay_tbl = [0, 13, 21, 8, 26, 17, 5, 30]
            parts: list[str] = []
            labels = ""
            for i in range(n):
                # 声像位置 pos ∈ [-spread, spread]，单声部居中
                pos = 0.0 if n == 1 else (-1.0 + 2.0 * i / (n - 1)) * spread
                ang = (pos + 1.0) * 0.5 * (math.pi / 2.0)  # 恒功率声像
                gl = math.cos(ang)
                gr = math.sin(ang)
                cents = cents_tbl[i % len(cents_tbl)]
                delay = delay_tbl[i % len(delay_tbl)]
                chain = (
                    f"[{i}:a]aresample={sample_rate},"
                    "aformat=channel_layouts=mono"
                )
                if abs(cents) > 0.01:
                    ratio = 2.0 ** (cents / 1200.0)
                    # asetrate 升调缩时 → aresample 回采样率 → atempo 还原时长（保音高）
                    chain += (
                        f",asetrate={int(sample_rate * ratio)},"
                        f"aresample={sample_rate},atempo={1.0 / ratio:.6f}"
                    )
                if delay > 0:
                    chain += f",adelay={delay}"
                chain += (
                    f",volume={gain:.4f}[d{i}];"
                    f"[d{i}]pan=stereo|c0={gl:.4f}*c0|c1={gr:.4f}*c0[a{i}];"
                )
                parts.append(chain)
                labels += f"[a{i}]"
            filt = (
                "".join(parts)
                + f"{labels}amix=inputs={n}:duration=longest:normalize=0[mx];"
                "[mx]alimiter=limit=0.97[a]"
            )
            cmd = [self.ffmpeg, "-y"]
            for p in srcs:
                cmd += ["-i", str(p)]
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
            res = subprocess.run(
                cmd,
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
