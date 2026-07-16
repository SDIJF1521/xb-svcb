"""用于编辑器时间轴的音频效果渲染辅助工具。"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

import config
from infrastructure.ffmpeg_tool import FfmpegTool
from infrastructure.juce_vst3_host import JuceVst3Host


class AudioEffectsProcessor:
    """渲染本地剪辑效果。
内置效果通过 FFmpeg 过滤器渲染。
外部插件效果则被路由至原生的 C++ JUCE VST3 主机，
该主机负责插件加载和插件 GUI 兼容性。
    """

    def __init__(
        self,
        tool: FfmpegTool | None = None,
        juce_host: JuceVst3Host | None = None,
    ) -> None:
        self._tool = tool or FfmpegTool()
        self.ffmpeg = self._tool.ffmpeg
        self._juce_host = juce_host or JuceVst3Host()

    def clip_requires_processing(self, clip: dict[str, Any]) -> bool:
        return bool(self._enabled_effects(clip))

    def render_clip(
        self,
        src: Path,
        clip: dict[str, Any],
        dst: Path,
        cache_dir: Path,
        sample_rate: int,
    ) -> Path | None:
        """将源剪辑通过其效果链渲染到“dst”中。"""
        effects = self._enabled_effects(clip)
        if not self.ffmpeg or not src.exists() or not effects:
            return None

        try:
            start = max(0.0, float(clip.get("start") or 0.0))
            end = max(start, float(clip.get("end") or start))
            length = max(0.01, end - start)
            offset = max(0.0, float(clip.get("offset") or 0.0))
        except (TypeError, ValueError):
            return None

        cache_dir.mkdir(parents=True, exist_ok=True)
        stem = dst.stem
        dry = cache_dir / f"{stem}_dry.wav"
        if not dry.exists() and not self._extract_clip(src, dry, offset, length, clip, sample_rate):
            return None

        current = dry
        changed = False
        for idx, effect in enumerate(effects):
            effect_type = self._effect_type(effect)
            next_path = cache_dir / f"{stem}_fx{idx:02d}.wav"
            ok = False
            if effect_type == "plugin":
                ok = self._juce_host.render_plugin(current, next_path, effect, sample_rate)
            else:
                ffmpeg_filter = self._ffmpeg_filter(effect)
                if ffmpeg_filter:
                    ok = self._apply_ffmpeg_filter(current, next_path, ffmpeg_filter, sample_rate)
            if ok and next_path.exists():
                current = next_path
                changed = True

        if not changed:
            return None
        if current != dst:
            try:
                shutil.copyfile(current, dst)
            except OSError:
                return None
        return dst if dst.exists() else None

    def render_monitor_input(
        self,
        src: Path,
        clip: dict[str, Any],
        effects: list[dict[str, Any]],
        dst: Path,
        cache_dir: Path,
        sample_rate: int,
    ) -> bool:
        """Render the signal immediately before a selected plugin in the effect chain."""
        if not self.ffmpeg or not src.exists():
            return False
        monitor_clip = dict(clip)
        monitor_clip["effects"] = effects
        enabled = self._enabled_effects(monitor_clip)
        if enabled:
            rendered = self.render_clip(src, monitor_clip, dst, cache_dir, sample_rate)
            if rendered and rendered.exists():
                return True
        try:
            start = max(0.0, float(clip.get("start") or 0.0))
            end = max(start, float(clip.get("end") or start))
            offset = max(0.0, float(clip.get("offset") or 0.0))
        except (TypeError, ValueError):
            return False
        return self._extract_clip(
            src,
            dst,
            offset,
            max(0.01, end - start),
            monitor_clip,
            sample_rate,
        )

    def cache_key(
        self,
        src: Path,
        clip: dict[str, Any],
        sample_rate: int,
    ) -> str:
        try:
            stat = src.stat()
            source = (str(src), stat.st_size, int(stat.st_mtime))
        except OSError:
            source = (str(src), 0, 0)
        payload = {
            "effect_cache_version": 2,
            "source": source,
            "offset": clip.get("offset"),
            "start": clip.get("start"),
            "end": clip.get("end"),
            "channel": clip.get("channel"),
            "effects": clip.get("effects"),
            "sample_rate": sample_rate,
            "plugin_host": self._juce_host.status(),
        }
        return hashlib.sha256(repr(payload).encode("utf-8", errors="replace")).hexdigest()[:24]

    def _extract_clip(
        self,
        src: Path,
        dst: Path,
        offset: float,
        length: float,
        clip: dict[str, Any],
        sample_rate: int,
    ) -> bool:
        channel = str(clip.get("channel") or "stereo").strip().lower()
        filters = [
            f"atrim=start={offset:.3f}:duration={length:.3f}",
            "asetpts=PTS-STARTPTS",
            f"aresample={sample_rate}",
            "aformat=sample_fmts=s16:channel_layouts=stereo",
        ]
        if channel == "left":
            filters.append("pan=stereo|c0=0.5*c0+0.5*c1|c1=0*c0")
        elif channel == "right":
            filters.append("pan=stereo|c0=0*c0|c1=0.5*c0+0.5*c1")
        return self._run(
            [
                str(self.ffmpeg),
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

    def _apply_ffmpeg_filter(
        self,
        src: Path,
        dst: Path,
        effect_filter: str,
        sample_rate: int,
    ) -> bool:
        return self._run(
            [
                str(self.ffmpeg),
                "-y",
                "-i",
                str(src),
                "-af",
                f"aresample={sample_rate},aformat=sample_fmts=s16:channel_layouts=stereo,{effect_filter}",
                "-ar",
                str(sample_rate),
                "-ac",
                "2",
                str(dst),
            ],
            timeout=300,
        )

    def _ffmpeg_filter(self, effect: dict[str, Any]) -> str:
        effect_type = self._effect_type(effect)
        params = self._params(effect)
        if effect_type == "denoise":
            noise_floor = self._number(params, "noise_floor_db", -35.0, -80.0, -20.0)
            reduction = self._number(params, "reduction_db", 12.0, 0.01, 48.0)
            return f"afftdn=nf={noise_floor:.1f}:nr={reduction:.1f}"
        if effect_type == "gain":
            gain = self._number(params, "gain_db", 0.0, -36.0, 36.0)
            return f"volume={gain:.3f}dB"
        if effect_type == "highpass":
            freq = self._number(params, "cutoff_frequency_hz", 80.0, 10.0, 20000.0)
            return f"highpass=f={freq:.1f}"
        if effect_type == "lowpass":
            freq = self._number(params, "cutoff_frequency_hz", 16000.0, 10.0, 22000.0)
            return f"lowpass=f={freq:.1f}"
        if effect_type == "eq":
            freq = self._number(params, "frequency_hz", 1200.0, 20.0, 20000.0)
            gain = self._number(params, "gain_db", 0.0, -24.0, 24.0)
            q = self._number(params, "q", 1.0, 0.1, 12.0)
            return f"equalizer=f={freq:.1f}:t=q:w={q:.3f}:g={gain:.3f}"
        if effect_type == "limiter":
            threshold_db = self._number(params, "threshold_db", -1.0, -30.0, 0.0)
            limit = 10 ** (threshold_db / 20.0)
            return f"alimiter=limit={limit:.4f}"
        if effect_type == "compressor":
            threshold_db = self._number(params, "threshold_db", -18.0, -60.0, 0.0)
            threshold = 10 ** (threshold_db / 20.0)
            ratio = self._number(params, "ratio", 2.5, 1.0, 20.0)
            attack = self._number(params, "attack_ms", 8.0, 0.1, 200.0)
            release = self._number(params, "release_ms", 120.0, 1.0, 1000.0)
            return (
                f"acompressor=threshold={threshold:.5f}:ratio={ratio:.3f}:"
                f"attack={attack:.3f}:release={release:.3f}"
            )
        if effect_type == "noise_gate":
            threshold_db = self._number(params, "threshold_db", -42.0, -96.0, 0.0)
            threshold = 10 ** (threshold_db / 20.0)
            ratio = self._number(params, "ratio", 2.5, 1.0, 20.0)
            return f"agate=threshold={threshold:.5f}:ratio={ratio:.3f}"
        if effect_type == "reverb":
            wet = self._number(params, "wet_level", 0.18, 0.0, 1.0)
            delay = self._number(params, "delay_ms", 52.0, 1.0, 250.0)
            decay = self._number(params, "decay", 0.35, 0.0, 0.95)
            return f"aecho=0.8:{0.8 + wet * 0.18:.3f}:{delay:.1f}:{decay:.3f}"
        if effect_type == "delay":
            delay = self._number(params, "delay_seconds", 0.18, 0.0, 3.0) * 1000.0
            feedback = self._number(params, "feedback", 0.18, 0.0, 0.95)
            mix = self._number(params, "mix", 0.18, 0.0, 1.0)
            return f"aecho=1.0:{0.75 + mix * 0.2:.3f}:{delay:.1f}:{feedback:.3f}"
        if effect_type == "chorus":
            return "chorus=0.7:0.9:55:0.4:0.25:2"
        if effect_type == "distortion":
            drive = self._number(params, "drive_db", 6.0, 0.0, 36.0)
            return f"acrusher=level_in={10 ** (drive / 20.0):.4f}:level_out=0.8"
        return ""

    @staticmethod
    def _enabled_effects(clip: dict[str, Any]) -> list[dict[str, Any]]:
        effects = clip.get("effects") or []
        if not isinstance(effects, list):
            return []
        return [
            item
            for item in effects
            if isinstance(item, dict)
            and str(item.get("type") or "").strip()
            and item.get("enabled", True) is not False
        ]

    @staticmethod
    def _effect_type(effect: dict[str, Any]) -> str:
        raw = str(effect.get("type") or "").strip().lower().replace("-", "_")
        aliases = {
            "gate": "noise_gate",
            "noisegate": "noise_gate",
            "noise_reduce": "denoise",
            "noise_reduction": "denoise",
            "de_noise": "denoise",
            "hp": "highpass",
            "high_pass": "highpass",
            "lp": "lowpass",
            "low_pass": "lowpass",
            "equalizer": "eq",
            "peak": "eq",
            "peak_filter": "eq",
            "vst": "plugin",
            "vst3": "plugin",
            "external": "plugin",
            "external_plugin": "plugin",
            "juce": "plugin",
            "juce_vst3": "plugin",
        }
        return aliases.get(raw, raw)

    @staticmethod
    def _params(effect: dict[str, Any]) -> dict[str, Any]:
        params = effect.get("params")
        merged = dict(params) if isinstance(params, dict) else {}
        for key, value in effect.items():
            if key not in {"id", "type", "enabled", "params", "name"}:
                merged.setdefault(key, value)
        return merged

    @staticmethod
    def _number(
        params: dict[str, Any],
        key: str,
        default: float,
        min_value: float,
        max_value: float,
    ) -> float:
        try:
            value = float(params.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(min_value, min(max_value, value))

    def _run(self, cmd: list[str], timeout: int) -> bool:
        try:
            dst = Path(cmd[-1])
            dst.parent.mkdir(parents=True, exist_ok=True)
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                **config.subprocess_no_window(),
            )
            return res.returncode == 0 and dst.exists()
        except (OSError, subprocess.SubprocessError):
            return False
