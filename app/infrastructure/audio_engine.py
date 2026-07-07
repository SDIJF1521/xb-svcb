"""音频编辑器专用 FFmpeg 封装。"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

import config
from infrastructure.audio_effects import AudioEffectsProcessor
from infrastructure.ffmpeg_tool import FfmpegTool


class FFmpegEngine:
    """Timeline Engine 使用的音频处理封装。

    这里集中提供 trim / concat / fade / volume / render_timeline，避免业务层拼
    shell 字符串，也为渲染缓存留下稳定的 hash 输入。
    """

    def __init__(self, tool: FfmpegTool | None = None) -> None:
        self._tool = tool or FfmpegTool()
        self.ffmpeg = self._tool.ffmpeg
        self._effects = AudioEffectsProcessor(self._tool)

    @property
    def available(self) -> bool:
        return self.ffmpeg is not None

    def trim(
        self,
        src: Path,
        start: float,
        end: float,
        dst: Path,
        sample_rate: int = 44100,
    ) -> bool:
        return self._tool.slice(src, start, end, dst, sample_rate=sample_rate)

    def concat(self, parts: list[Path], dst: Path, sample_rate: int = 44100) -> bool:
        return self._tool.concat(parts, dst, sample_rate=sample_rate)

    def volume(self, src: Path, gain: float, dst: Path, sample_rate: int = 44100) -> bool:
        if not self.ffmpeg:
            return False
        dst.parent.mkdir(parents=True, exist_ok=True)
        gain = max(0.0, float(gain))
        return self._run(
            [
                self.ffmpeg,
                "-y",
                "-i",
                str(src),
                "-af",
                f"aresample={sample_rate},volume={gain:.4f}",
                "-ar",
                str(sample_rate),
                "-ac",
                "2",
                str(dst),
            ],
            timeout=300,
        )

    def fade(
        self,
        src: Path,
        fade_in: float,
        fade_out: float,
        dst: Path,
        duration: float | None = None,
        sample_rate: int = 44100,
    ) -> bool:
        if not self.ffmpeg:
            return False
        dst.parent.mkdir(parents=True, exist_ok=True)
        dur = duration if duration is not None else self._tool.probe_duration(src)
        dur = max(0.0, float(dur or 0.0))
        filters = [f"aresample={sample_rate}"]
        fin = max(0.0, min(float(fade_in or 0.0), dur / 2 if dur else 0.0))
        fout = max(0.0, min(float(fade_out or 0.0), dur / 2 if dur else 0.0))
        if fin > 0:
            filters.append(f"afade=t=in:st=0:d={fin:.3f}")
        if fout > 0 and dur > 0:
            filters.append(f"afade=t=out:st={max(0.0, dur - fout):.3f}:d={fout:.3f}")
        return self._run(
            [
                self.ffmpeg,
                "-y",
                "-i",
                str(src),
                "-af",
                ",".join(filters),
                "-ar",
                str(sample_rate),
                "-ac",
                "2",
                str(dst),
            ],
            timeout=300,
        )

    def silence(self, dst: Path, duration: float, sample_rate: int = 44100) -> bool:
        if not self.ffmpeg:
            return False
        dst.parent.mkdir(parents=True, exist_ok=True)
        return self._run(
            [
                self.ffmpeg,
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=r={sample_rate}:cl=stereo",
                "-t",
                f"{max(0.05, float(duration)):.3f}",
                "-ar",
                str(sample_rate),
                "-ac",
                "2",
                str(dst),
            ],
            timeout=120,
        )

    def render_timeline(
        self,
        project: dict[str, Any],
        dst: Path,
        cache_dir: Path,
        output_format: str = "wav",
    ) -> bool:
        """把可序列化 Project 渲染为混音文件。"""
        if not self.ffmpeg:
            return False
        dst.parent.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)
        sample_rate = int(project.get("sample_rate") or 44100)
        duration = max(0.05, float(project.get("duration") or 0.05))
        inputs: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
        for track in project.get("tracks", []) or []:
            if track.get("mute"):
                continue
            for clip in track.get("clips", []) or []:
                if clip.get("mute"):
                    continue
                path = Path(str(clip.get("file") or ""))
                if not path.exists():
                    continue
                if float(clip.get("end") or 0) <= float(clip.get("start") or 0):
                    continue
                meta = {"path": path, "prepared": False}
                if self._effects.clip_requires_processing(clip):
                    key = self._effects.cache_key(path, clip, sample_rate)
                    prepared = cache_dir / f"fx_{key}.wav"
                    if prepared.exists() or self._effects.render_clip(
                        path,
                        clip,
                        prepared,
                        cache_dir,
                        sample_rate,
                    ):
                        meta = {"path": prepared, "prepared": True}
                inputs.append((track, clip, meta))

        if not inputs:
            return self.silence(dst, duration, sample_rate=sample_rate)

        cmd: list[str] = [self.ffmpeg, "-y"]
        for _, _, meta in inputs:
            cmd += ["-i", str(meta["path"])]

        filters: list[str] = []
        labels = ""
        for idx, (track, clip, meta) in enumerate(inputs):
            start = max(0.0, float(clip.get("start") or 0.0))
            end = max(start, float(clip.get("end") or start))
            length = max(0.01, end - start)
            offset = 0.0 if meta.get("prepared") else max(0.0, float(clip.get("offset") or 0.0))
            gain = max(0.0, float(track.get("volume", 1.0)) * float(clip.get("volume", 1.0)))
            fade_in = max(0.0, min(float(clip.get("fade_in") or 0.0), length / 2.0))
            fade_out = max(0.0, min(float(clip.get("fade_out") or 0.0), length / 2.0))
            channel = str(clip.get("channel") or "stereo").strip().lower()
            delay_ms = max(0, int(round(start * 1000)))
            chain = (
                f"[{idx}:a]atrim=start={offset:.3f}:duration={length:.3f},"
                "asetpts=PTS-STARTPTS,"
                f"aresample={sample_rate},"
                "aformat=sample_fmts=s16:channel_layouts=stereo,"
                f"volume={gain:.4f}"
            )
            envelope = self._volume_envelope_filter(clip.get("volume_envelope"), length)
            if envelope:
                chain += f",{envelope}"
            if fade_in > 0:
                chain += f",afade=t=in:st=0:d={fade_in:.3f}"
            if fade_out > 0:
                chain += f",afade=t=out:st={max(0.0, length - fade_out):.3f}:d={fade_out:.3f}"
            if not meta.get("prepared") and channel == "left":
                chain += ",pan=stereo|c0=0.5*c0+0.5*c1|c1=0*c0"
            elif not meta.get("prepared") and channel == "right":
                chain += ",pan=stereo|c0=0*c0|c1=0.5*c0+0.5*c1"
            chain += f",adelay={delay_ms}|{delay_ms}[a{idx}]"
            filters.append(chain)
            labels += f"[a{idx}]"

        filters.append(
            f"{labels}amix=inputs={len(inputs)}:duration=longest:normalize=0,"
            "alimiter=limit=0.97[out]"
        )
        ext = output_format.lower().lstrip(".")
        codec: list[str] = []
        if ext == "mp3":
            codec = ["-codec:a", "libmp3lame", "-q:a", "2", "-joint_stereo", "0"]
        elif ext == "flac":
            codec = ["-codec:a", "flac"]
        elif ext == "wav":
            codec = ["-codec:a", "pcm_s16le"]
        cmd += [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[out]",
            "-t",
            f"{duration:.3f}",
            "-ar",
            str(sample_rate),
            "-ac",
            "2",
            *codec,
            str(dst),
        ]
        return self._run(cmd, timeout=900)

    @staticmethod
    def cache_key(payload: Any) -> str:
        data = repr(payload).encode("utf-8", errors="replace")
        return hashlib.sha256(data).hexdigest()[:24]

    @classmethod
    def _volume_envelope_filter(cls, raw: Any, duration: float) -> str:
        points = cls._volume_envelope_points(raw, duration)
        if len(points) < 2:
            return ""
        if all(abs(point[1] - 1.0) < 0.0001 for point in points):
            return ""

        expr = f"{points[-1][1]:.6f}"
        for idx in range(len(points) - 2, -1, -1):
            t0, v0 = points[idx]
            t1, v1 = points[idx + 1]
            span = max(0.001, t1 - t0)
            line = f"{v0:.6f}+({v1:.6f}-{v0:.6f})*(t-{t0:.6f})/{span:.6f}"
            expr = f"if(lte(t\\,{t1:.6f})\\,{line}\\,{expr})"
        return f"volume='{expr}':eval=frame"

    @staticmethod
    def _volume_envelope_points(raw: Any, duration: float) -> list[tuple[float, float]]:
        if not isinstance(raw, list):
            return []
        points: list[tuple[float, float]] = []
        dur = max(0.01, float(duration or 0.01))
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                t = float(item.get("time", item.get("t", 0.0)) or 0.0)
                v = float(item.get("volume", item.get("value", 1.0)) or 0.0)
            except (TypeError, ValueError):
                continue
            points.append((max(0.0, min(dur, t)), max(0.0, min(2.5, v))))
        if not points:
            return []

        by_time: dict[float, float] = {}
        for t, v in sorted(points, key=lambda point: point[0]):
            by_time[round(t, 3)] = v
        normalized = [(t, by_time[t]) for t in sorted(by_time)]
        if normalized[0][0] > 0.0:
            normalized.insert(0, (0.0, normalized[0][1]))
        if normalized[-1][0] < dur:
            normalized.append((dur, normalized[-1][1]))
        return normalized

    def _run(self, cmd: list[str], timeout: int) -> bool:
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                **config.subprocess_no_window(),
            )
            out = Path(cmd[-1])
            return res.returncode == 0 and out.exists()
        except (OSError, subprocess.SubprocessError):
            return False
