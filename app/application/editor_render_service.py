"""编辑器渲染与波形用例。

这些用例原先长在 ``AudioEditorService`` 里，但它们只依赖工程仓储、时间线渲染引擎
（``AudioEnginePort``）与文件访问端口，与编辑工程的增删改校验无关。拆出来之后
``AudioEditorService`` 只保留同名的单行委托，用例边界更清晰，渲染逻辑本身一行未改。

渲染版本、缓存键与波形算法保持原样：拆分前后的缓存命中与返回结果完全一致。
"""

from __future__ import annotations

import copy
import re
import struct
import threading
import wave
from pathlib import Path
from typing import Any, Callable

from domain.audio_editor_rules import (
    clip_stretch,
    find_clip,
    normalize_format,
    project_duration,
    should_render_waveform,
)

from .adapters import ffmpeg_cache_key
from .ports import AudioEnginePort, EditorProjectStorePort, FfmpegGateway, ItemRepository

# 渲染缓存版本：改动渲染管线（声道 / 效果 / 总线）时必须升级，避免旧缓存被复用。
RENDER_VERSION = "channel-route-v9-scoped-effects-buses"

__all__ = ["EditorRenderService", "RENDER_VERSION"]


class EditorRenderService:
    """编辑器工程的渲染、导出与波形缓存用例。"""

    def __init__(
        self,
        repo: ItemRepository,
        audio: AudioEnginePort | None,
        ffmpeg: FfmpegGateway | None,
        store: EditorProjectStorePort,
        *,
        save: Callable[..., Any] | None = None,
    ) -> None:
        self._repo = repo
        self._audio = audio
        self._ffmpeg = ffmpeg
        self._store = store
        # 波形结果要写回工程；保存策略（历史、时长、时间戳）仍由用例层的 ``save`` 决定。
        self._save = save

    # ---- 时间线渲染 ----

    def render_preview(self, project_id: str) -> str:
        # Preview is streamed as a data URI by the desktop bridge; MP3 keeps
        # first-play latency and bridge memory bounded for long projects.
        path = self.render(project_id, "mp3")
        return self._store.audio_data_uri(path, exact=True) if path else ""

    def render(self, project_id: str, output_format: str = "wav") -> Path | None:
        project = self._repo.get(project_id)
        if not project:
            return None
        fmt = normalize_format(output_format)
        key = self._render_key(project, fmt)
        dst = self._store.cache_path(f"{project_id}_{key}.{fmt}")
        if dst.exists():
            return dst
        ok = self._audio.render_timeline(project, dst, self._cache_dir(), fmt)
        return dst if ok and dst.exists() else None

    def render_track(
        self, project_id: str, track_id: str, output_format: str = "wav"
    ) -> Path | None:
        """把单条音轨（含该轨效果与片段）渲染成一个音频文件，用于导出单轨。"""
        return self._render_track_file(project_id, track_id, output_format)

    def render_clip(
        self,
        project_id: str,
        clip_id: str,
        output_format: str = "wav",
        *,
        cache: bool = False,
    ) -> Path | None:
        """把单个片段渲染成音频文件，用于导出与 HTTP 下载。"""
        return self._render_clip_file(project_id, clip_id, output_format, cache=cache)

    def _render_clip_file(
        self,
        project_id: str,
        clip_id: str,
        fmt: str = "wav",
        cache: bool = False,
    ) -> Path | None:
        project = self._repo.get(project_id)
        track: dict[str, Any] | None = None
        clip: dict[str, Any] | None = None
        if project:
            for item in project.get("tracks", []) or []:
                hit = next(
                    (c for c in item.get("clips", []) or [] if c.get("id") == clip_id),
                    None,
                )
                if hit:
                    track = item
                    clip = hit
                    break
        if not project or not track or not clip:
            return None
        try:
            length = max(0.01, float(clip.get("end") or 0.0) - float(clip.get("start") or 0.0))
        except (TypeError, ValueError):
            length = 0.01
        preview_clip = copy.deepcopy(clip)
        preview_clip["start"] = 0.0
        preview_clip["end"] = length
        preview_project = {
            "id": project_id,
            "duration": length,
            "sample_rate": project.get("sample_rate") or 44100,
            "roles": copy.deepcopy(project.get("roles") or []),
            "tracks": [
                {
                    "id": track.get("id"),
                    "name": track.get("name", ""),
                    "type": track.get("type", "audio"),
                    "volume": track.get("volume", 1.0),
                    "mute": False,
                    "effects": copy.deepcopy(track.get("effects") or []),
                    "metadata": copy.deepcopy(track.get("metadata") or {}),
                    "clips": [preview_clip],
                }
            ],
        }
        output_format = normalize_format(fmt)
        key = ffmpeg_cache_key(
            {
                "render_version": RENDER_VERSION,
                "project_id": project_id,
                "clip": preview_clip,
                "track_volume": track.get("volume", 1.0),
                "sample_rate": preview_project["sample_rate"],
                "format": output_format,
            }
        )
        if cache:
            dst = self._store.cache_path(f"{project_id}_{clip_id}_{key}.{output_format}")
        else:
            export_dir = self._store.project_dir(project_id) / "copied"
            export_dir.mkdir(parents=True, exist_ok=True)
            name = self._safe_stem(str(clip.get("name") or Path(str(clip.get("file") or "")).stem))
            dst = export_dir / f"{name}_{key}.{output_format}"
        if dst.exists():
            return dst
        ok = self._audio.render_timeline(preview_project, dst, self._cache_dir(), output_format)
        return dst if ok and dst.exists() else None

    def _render_track_file(
        self,
        project_id: str,
        track_id: str,
        fmt: str = "wav",
    ) -> Path | None:
        project = self._repo.get(project_id)
        if not project:
            return None
        track = next((t for t in project.get("tracks", []) or [] if t.get("id") == track_id), None)
        if not track:
            return None
        output_format = normalize_format(fmt)
        track_project = {
            "id": project_id,
            "duration": max(float(project.get("duration") or 0.05), project_duration({"tracks": [track]})),
            "sample_rate": project.get("sample_rate") or 44100,
            "roles": copy.deepcopy(project.get("roles") or []),
            "tracks": [{**copy.deepcopy(track), "mute": False}],
        }
        key = ffmpeg_cache_key(
            {
                "render_version": RENDER_VERSION,
                "project_id": project_id,
                "track": track_project,
                "format": output_format,
            }
        )
        export_dir = self._store.project_dir(project_id) / "copied"
        export_dir.mkdir(parents=True, exist_ok=True)
        dst = export_dir / f"{self._safe_stem(str(track.get('name') or 'track'))}_{key}.{output_format}"
        if dst.exists():
            return dst
        ok = self._audio.render_timeline(track_project, dst, self._cache_dir(), output_format)
        return dst if ok and dst.exists() else None

    def _render_key(self, project: dict[str, Any], fmt: str) -> str:
        payload = self._snapshot(project)
        payload.pop("waveform_cache", None)
        stats = []
        for track in payload.get("tracks", []) or []:
            for clip in track.get("clips", []) or []:
                path = Path(str(clip.get("file") or ""))
                try:
                    st = path.stat()
                    stats.append((str(path), st.st_size, int(st.st_mtime)))
                except OSError:
                    stats.append((str(path), 0, 0))
        return ffmpeg_cache_key(
            {
                "render_version": RENDER_VERSION,
                "project": payload,
                "stats": stats,
                "format": fmt,
            }
        )

    # ---- 波形 ----

    def waveform(self, project_id: str, clip_id: str, bins: int = 160) -> dict[str, Any]:
        project = self._repo.get(project_id)
        clip = find_clip(project, clip_id) if project else None
        if not project or not clip:
            return {"ok": False, "peaks": []}
        rendered = None
        if should_render_waveform(clip):
            rendered = self._render_clip_file(project_id, clip_id, "wav", cache=True)
        waveform_src = rendered if rendered and rendered.exists() else Path(str(clip.get("file") or ""))
        cache_key = self._waveform_key(clip, bins, waveform_src)
        cache = dict(project.get("waveform_cache") or {})
        if cache_key in cache:
            return {"ok": True, **cache[cache_key]}
        if rendered and rendered.exists():
            peaks = self._compute_waveform(rendered, bins)
        else:
            try:
                timeline_duration = max(
                    0.01,
                    float(clip.get("end") or 0.0) - float(clip.get("start") or 0.0),
                )
            except (TypeError, ValueError):
                timeline_duration = 0.01
            stretch = clip_stretch(clip)
            duration = timeline_duration / stretch
            try:
                offset = max(0.0, float(clip.get("offset") or 0.0))
            except (TypeError, ValueError):
                offset = 0.0
            peaks = self._compute_waveform(
                Path(str(clip.get("file") or "")),
                bins,
                offset=offset,
                duration=duration,
            )
        payload = {"clip_id": clip_id, "bins": bins, "peaks": peaks}
        cache[cache_key] = payload
        project["waveform_cache"] = cache
        self._save_project(project)
        return {"ok": True, **payload}

    def preload_waveforms(self, project_id: str, bins: int = 160) -> bool:
        project = self._repo.get(project_id)
        if not project:
            return False

        def worker() -> None:
            for track in project.get("tracks", []) or []:
                for clip in track.get("clips", []) or []:
                    self.waveform(project_id, str(clip.get("id")), bins)

        threading.Thread(target=worker, daemon=True).start()
        return True

    def _waveform_key(
        self,
        clip: dict[str, Any],
        bins: int,
        source: Path | None = None,
    ) -> str:
        path = source if source and source.exists() else Path(str(clip.get("file") or ""))
        try:
            st = path.stat()
            stat = (str(path), st.st_size, int(st.st_mtime_ns))
        except OSError:
            stat = (str(path), 0, 0)
        try:
            duration = max(
                0.01,
                float(clip.get("end") or 0.0) - float(clip.get("start") or 0.0),
            )
        except (TypeError, ValueError):
            duration = 0.01
        try:
            offset = max(0.0, float(clip.get("offset") or 0.0))
        except (TypeError, ValueError):
            offset = 0.0
        return ffmpeg_cache_key(
            {
                "clip": clip.get("id"),
                "stat": stat,
                "offset": round(offset, 3),
                "duration": round(duration, 3),
                "time_stretch": round(clip_stretch(clip), 4),
                "bins": bins,
            }
        )

    def _compute_waveform(
        self,
        src: Path,
        bins: int,
        offset: float = 0.0,
        duration: float | None = None,
    ) -> list[float]:
        if not src.exists():
            return []
        wav_path = src
        try:
            st = src.stat()
            source_key = (str(src), st.st_size, int(st.st_mtime))
        except OSError:
            source_key = (str(src), 0, 0)
        if self._ffmpeg is not None and self._ffmpeg.available:
            cached = self._store.cache_path(f"wf_{ffmpeg_cache_key(source_key)}.wav")
            cached.parent.mkdir(parents=True, exist_ok=True)
            # 8 kHz made transients and consonants visibly disappear in the editor.
            # Keep a full-band analysis source while reducing only the displayed bins.
            if cached.exists() or self._ffmpeg.convert(src, cached, sample_rate=44100):
                wav_path = cached
        elif src.suffix.lower() != ".wav":
            return []
        try:
            with wave.open(str(wav_path), "rb") as wf:
                frames = wf.getnframes()
                channels = max(1, wf.getnchannels())
                width = wf.getsampwidth()
                rate = max(1, wf.getframerate())
                if frames <= 0 or width not in (1, 2, 4):
                    return []
                start_frame = min(frames, max(0, int(float(offset or 0.0) * rate)))
                available = max(0, frames - start_frame)
                requested = (
                    available
                    if duration is None
                    else max(1, int(float(duration or 0.0) * rate))
                )
                span = max(1, min(available, requested))
                if available <= 0:
                    return []
                target_bins = max(16, min(4096, int(bins or 320), span))
                wf.setpos(start_frame)
                raw = wf.readframes(span)
                if not raw:
                    return []
                # NumPy is present in the application environment; keep a small
                # struct fallback for portable/headless test environments.
                try:
                    import numpy as np

                    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}[width]
                    samples = np.frombuffer(raw, dtype=dtype)
                    usable = (len(samples) // channels) * channels
                    samples = samples[:usable].reshape(-1, channels)
                    if width == 1:
                        frame_peaks = np.max(np.abs(samples.astype(np.int16) - 128), axis=1) / 128.0
                    else:
                        frame_peaks = np.max(np.abs(samples.astype(np.float32)), axis=1) / float(2 ** (width * 8 - 1) - 1)
                    edges = np.linspace(0, len(frame_peaks), target_bins + 1, dtype=np.int64)
                    peaks = [
                        round(float(np.max(frame_peaks[edges[index] : max(edges[index] + 1, edges[index + 1])])), 4)
                        if edges[index] < len(frame_peaks) else 0.0
                        for index in range(target_bins)
                    ]
                    return [max(0.0, min(1.0, value)) for value in peaks]
                except (ImportError, TypeError, ValueError):
                    fmt = {1: "B", 2: "h", 4: "i"}[width]
                    max_val = 128.0 if width == 1 else float((2 ** (width * 8 - 1)) - 1)
                    samples = struct.unpack("<" + fmt * (len(raw) // width), raw[: (len(raw) // width) * width])
                    peaks: list[float] = []
                    for idx in range(target_bins):
                        first = round(idx * len(samples) / target_bins)
                        last = max(first + channels, round((idx + 1) * len(samples) / target_bins))
                        frame = samples[first:last]
                        values = [abs(int(item) - 128) if width == 1 else abs(item) for item in frame]
                        peaks.append(round(min(1.0, max(values or [0]) / max_val), 4))
                    return peaks
        except (OSError, EOFError, wave.Error, struct.error):
            return []

    # ---- 内部小工具（纯计算，与 AudioEditorService 的同名封装保持一致） ----

    def _cache_dir(self) -> Path:
        """渲染/波形缓存根目录（与 ``cache_path`` 同源）。"""
        return self._store.cache_path("")

    def _save_project(self, project: dict[str, Any]) -> None:
        """波形缓存回写工程：保存策略由用例层的 ``save`` 承担。"""
        if self._save is not None:
            self._save(project, push_history=False)

    @staticmethod
    def _snapshot(project: dict[str, Any]) -> dict[str, Any]:
        snap = copy.deepcopy(project)
        snap.pop("history", None)
        snap.pop("future", None)
        return snap

    @staticmethod
    def _safe_stem(name: str) -> str:
        cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name or "").strip().strip(".")
        return (cleaned[:80] or "audio").strip()
