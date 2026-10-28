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

    def render_plugin_monitor_input(
        self,
        src: Path,
        clip: dict[str, Any],
        effects: list[dict[str, Any]],
        dst: Path,
        cache_dir: Path,
        sample_rate: int = 44100,
    ) -> bool:
        return self._effects.render_monitor_input(
            src,
            clip,
            effects,
            dst,
            cache_dir,
            sample_rate,
        )

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
        """Render clip, role and track effect scopes through separate buses."""
        roles = {
            str(role.get("id") or ""): role
            for role in (project.get("roles") or [])
            if isinstance(role, dict) and str(role.get("id") or "")
        }
        has_bus_effects = any(
            self._has_enabled_effects(track.get("effects"))
            for track in (project.get("tracks") or [])
            if isinstance(track, dict)
        ) or any(self._has_enabled_effects(role.get("effects")) for role in roles.values())
        if not has_bus_effects:
            return self._render_flat_timeline(project, dst, cache_dir, output_format)
        return self._render_scoped_timeline(project, roles, dst, cache_dir, output_format)

    def _render_scoped_timeline(
        self,
        project: dict[str, Any],
        roles: dict[str, dict[str, Any]],
        dst: Path,
        cache_dir: Path,
        output_format: str,
    ) -> bool:
        cache_dir.mkdir(parents=True, exist_ok=True)
        sample_rate = int(project.get("sample_rate") or 44100)
        duration = max(0.05, float(project.get("duration") or 0.05))
        track_buses: list[Path] = []

        for track_index, track in enumerate(project.get("tracks", []) or []):
            if not isinstance(track, dict) or track.get("mute"):
                continue
            groups: dict[str, list[dict[str, Any]]] = {}
            raw_track_metadata = track.get("metadata")
            track_metadata = (
                raw_track_metadata if isinstance(raw_track_metadata, dict) else {}
            )
            track_role_id = str(track_metadata.get("role_id") or "")
            for clip in track.get("clips", []) or []:
                if not isinstance(clip, dict) or clip.get("mute"):
                    continue
                raw_metadata = clip.get("metadata")
                metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
                role_id = str(metadata.get("role_id") or track_role_id)
                role = roles.get(role_id)
                group_key = role_id if role and self._has_enabled_effects(role.get("effects")) else "__dry__"
                groups.setdefault(group_key, []).append(clip)
            if not groups:
                continue

            role_buses: list[Path] = []
            for group_index, (group_key, clips) in enumerate(groups.items()):
                group_project = {
                    "sample_rate": sample_rate,
                    "duration": duration,
                    "tracks": [{**track, "effects": [], "clips": clips, "mute": False, "volume": 1.0}],
                }
                group_hash = self.cache_key(
                    {"scope": "role", "track": track.get("id"), "role": group_key, "project": group_project}
                )
                dry_bus = cache_dir / f"bus_role_{track_index:03d}_{group_index:03d}_{group_hash}.wav"
                if not dry_bus.exists() and not self._render_flat_timeline(group_project, dry_bus, cache_dir, "wav"):
                    return False
                role = roles.get(group_key)
                role_effects = self._effect_list(role.get("effects") if role else None)
                if self._has_enabled_effects(role_effects):
                    fx_hash = self.cache_key({"input": group_hash, "effects": role_effects})
                    wet_bus = cache_dir / f"bus_role_fx_{fx_hash}.wav"
                    if not wet_bus.exists():
                        self._effects.render_file(
                            dry_bus,
                            role_effects,
                            wet_bus,
                            cache_dir,
                            sample_rate,
                        )
                    role_buses.append(wet_bus if wet_bus.exists() else dry_bus)
                else:
                    role_buses.append(dry_bus)

            track_hash = self.cache_key(
                {
                    "scope": "track",
                    "track": track.get("id"),
                    "volume": track.get("volume", 1.0),
                    "inputs": [str(path) for path in role_buses],
                }
            )
            dry_track = cache_dir / f"bus_track_{track_index:03d}_{track_hash}.wav"
            track_bus_project = self._bus_project(role_buses, duration, sample_rate)
            for bus_track in track_bus_project["tracks"]:
                bus_track["volume"] = track.get("volume", 1.0)
            if not dry_track.exists() and not self._render_flat_timeline(
                track_bus_project,
                dry_track,
                cache_dir,
                "wav",
            ):
                return False

            track_effects = self._effect_list(track.get("effects"))
            if self._has_enabled_effects(track_effects):
                fx_hash = self.cache_key({"input": track_hash, "effects": track_effects})
                wet_track = cache_dir / f"bus_track_fx_{fx_hash}.wav"
                if not wet_track.exists():
                    self._effects.render_file(
                        dry_track,
                        track_effects,
                        wet_track,
                        cache_dir,
                        sample_rate,
                    )
                track_buses.append(wet_track if wet_track.exists() else dry_track)
            else:
                track_buses.append(dry_track)

        if not track_buses:
            return self.silence(dst, duration, sample_rate=sample_rate)
        return self._render_flat_timeline(
            self._bus_project(track_buses, duration, sample_rate),
            dst,
            cache_dir,
            output_format,
        )

    @staticmethod
    def _effect_list(raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, dict)]

    @staticmethod
    def _has_enabled_effects(raw: Any) -> bool:
        return isinstance(raw, list) and any(
            isinstance(effect, dict)
            and str(effect.get("type") or "").strip()
            and effect.get("enabled", True) is not False
            for effect in raw
        )

    @staticmethod
    def _bus_project(paths: list[Path], duration: float, sample_rate: int) -> dict[str, Any]:
        return {
            "sample_rate": sample_rate,
            "duration": duration,
            "tracks": [
                {
                    "id": f"bus-track-{index}",
                    "volume": 1.0,
                    "mute": False,
                    "effects": [],
                    "clips": [
                        {
                            "id": f"bus-clip-{index}",
                            "file": str(path),
                            "start": 0.0,
                            "end": duration,
                            "offset": 0.0,
                            "volume": 1.0,
                            "mute": False,
                            "effects": [],
                            "fade_in": 0.0,
                            "fade_out": 0.0,
                            "channel": "stereo",
                            "time_stretch": 1.0,
                            "metadata": {},
                        }
                    ],
                }
                for index, path in enumerate(paths)
            ],
        }

    def _render_flat_timeline(
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
            try:
                stretch = max(0.25, min(4.0, float(clip.get("time_stretch", 1.0) or 1.0)))
            except (TypeError, ValueError):
                stretch = 1.0
            speed = 1.0 / stretch
            source_length = length * speed
            offset = 0.0 if meta.get("prepared") else max(0.0, float(clip.get("offset") or 0.0))
            if meta.get("prepared"):
                source_length = length
            gain = max(0.0, float(track.get("volume", 1.0)) * float(clip.get("volume", 1.0)))
            fade_in = max(0.0, min(float(clip.get("fade_in") or 0.0), length / 2.0))
            fade_out = max(0.0, min(float(clip.get("fade_out") or 0.0), length / 2.0))
            channel = str(clip.get("channel") or "stereo").strip().lower()
            delay_ms = max(0, int(round(start * 1000)))
            chain = (
                f"[{idx}:a]atrim=start={offset:.3f}:duration={source_length:.3f},"
                "asetpts=PTS-STARTPTS,"
                f"aresample={sample_rate},"
                "aformat=sample_fmts=s16:channel_layouts=stereo,"
                f"volume={gain:.4f}"
            )
            if not meta.get("prepared") and abs(stretch - 1.0) > 0.0001:
                chain += "," + ",".join(self._atempo_filters(speed))
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
    def _atempo_filters(speed: float) -> list[str]:
        value = max(0.25, min(4.0, float(speed or 1.0)))
        filters: list[str] = []
        while value < 0.5:
            filters.append("atempo=0.5")
            value /= 0.5
        while value > 2.0:
            filters.append("atempo=2.0")
            value /= 2.0
        if abs(value - 1.0) > 0.0001:
            filters.append(f"atempo={value:.6f}")
        return filters

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
