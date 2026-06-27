"""轻量音频编辑器服务。"""

from __future__ import annotations

import base64
import copy
import json
import shutil
import struct
import threading
import wave
from datetime import datetime
from pathlib import Path
from typing import Any

import config
from domain import EditorClip, EditorProject, EditorTrack, InferenceParams
from infrastructure import paths
from infrastructure.audio_engine import FFmpegEngine
from infrastructure.ffmpeg_tool import FfmpegTool
from infrastructure.storage import ListRepository

from .model_service import ModelService


class AudioEditorService:
    """Timeline Project 的应用层服务。"""

    _HISTORY_LIMIT = 60
    _MIN_RERUN_DURATION = 1.0

    def __init__(
        self,
        repo: ListRepository,
        works_repo: ListRepository,
        models: ModelService,
        ffmpeg: FfmpegTool,
        engines: Any,
    ) -> None:
        self._repo = repo
        self._works_repo = works_repo
        self._models = models
        self._ffmpeg = ffmpeg
        self._audio = FFmpegEngine(ffmpeg)
        self._engines = engines

    def list(self) -> list[dict[str, Any]]:
        projects = []
        for p in self._repo.all():
            projects.append(
                {
                    "id": p.get("id"),
                    "title": p.get("title", "未命名工程"),
                    "duration": p.get("duration", 0),
                    "tracks": len(p.get("tracks", []) or []),
                    "updated_at": p.get("updated_at", ""),
                }
            )
        return projects

    def get(self, project_id: str) -> dict[str, Any] | None:
        project = self._repo.get(project_id)
        return self._public(project) if project else None

    def remove(self, project_id: str) -> bool:
        if not self._repo.get(project_id):
            return False
        self._repo.remove(project_id)
        try:
            base = config.EDITOR_DIR.resolve()
            target = (config.EDITOR_DIR / project_id).resolve()
        except OSError:
            return True
        if target.parent == base and target.exists():
            shutil.rmtree(target, ignore_errors=True)
        return True

    def create_from_audio(self, path: str, title: str | None = None) -> dict[str, Any] | None:
        src = Path(path) if path else None
        if src is None or not src.exists():
            return None
        pid = paths.new_id("edt_")
        project_dir = self._project_dir(pid)
        media_dir = project_dir / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        dst = media_dir / src.name
        try:
            if src.resolve() != dst.resolve():
                shutil.copy2(src, dst)
        except OSError:
            return None

        duration = float(self._ffmpeg.probe_duration(dst) or 0.0)
        now = self._now()
        clip = EditorClip(
            id=paths.new_id("clp_"),
            name=dst.stem,
            start=0.0,
            end=max(duration, 0.05),
            offset=0.0,
            volume=1.0,
            mute=False,
            file=str(dst),
            metadata={"source": "manual"},
        ).to_dict()
        track = EditorTrack(
            id=paths.new_id("trk_"),
            name="原始音频",
            type="source",
            clips=[clip],
            locked=False,
        ).to_dict()
        project = EditorProject(
            id=pid,
            title=(title or src.stem or "音频工程")[:120],
            tracks=[track],
            duration=max(duration, 0.05),
            metadata={"source_path": str(src), "mode": "manual"},
            created_at=now,
            updated_at=now,
        ).to_dict()
        self._repo.add({**project, "history": [], "future": []})
        return self._public(project)

    def create_from_work(self, work_id: str) -> dict[str, Any] | None:
        work = self._works_repo.get(work_id)
        if not work:
            return None
        pid = paths.new_id("edt_")
        now = self._now()
        tracks: list[dict[str, Any]] = []
        known: set[str] = set()

        def add_track(
            name: str,
            kind: str,
            raw: str | None,
            locked: bool = False,
            mute: bool = False,
            metadata: dict[str, Any] | None = None,
        ) -> None:
            if not raw:
                return
            src = Path(raw)
            if not src.exists():
                return
            try:
                resolved = str(src.resolve())
            except OSError:
                return
            if resolved in known:
                return
            dur = float(self._ffmpeg.probe_duration(src) or 0.0)
            known.add(resolved)
            tracks.append(
                EditorTrack(
                    id=paths.new_id("trk_"),
                    name=name,
                    type=kind,
                    clips=[
                        EditorClip(
                            id=paths.new_id("clp_"),
                            name=src.stem,
                            start=0.0,
                            end=max(dur, 0.05),
                            offset=0.0,
                            volume=1.0,
                            mute=False,
                            file=str(src),
                            locked=locked,
                            metadata={"work_id": work_id, "stem": kind, **(metadata or {})},
                        ).to_dict()
                    ],
                    locked=locked,
                    mute=mute,
                ).to_dict()
            )

        def remember(raw: str | None) -> None:
            if not raw:
                return
            try:
                known.add(str(Path(raw).resolve()))
            except OSError:
                pass

        add_track("原始音频", "source", work.get("source_path"), locked=True, mute=True)
        add_track("原始人声", "vocal", work.get("vocals_path"), mute=True)
        add_track("BGM 轨", "bgm", work.get("instrumental_path"))
        remember(work.get("output_path"))

        work_dir = config.WORKS_DIR / work_id
        ai_merged = work.get("ai_merged_vocal_path") or work.get("converted_path")
        if not ai_merged:
            candidate = work_dir / "converted.wav"
            if candidate.exists():
                ai_merged = str(candidate)
        ai_paths = [
            str(p)
            for p in (work.get("ai_vocal_paths") or [])
            if p and Path(str(p)).exists()
        ]
        is_multi = work.get("mode") == "multi"
        if is_multi:
            add_track("AI 合并干声", "ai", ai_merged, metadata={"stem": "ai_merged"})
            seg_models = work.get("seg_models") or {}
            for idx, raw in enumerate(ai_paths, start=1):
                path = Path(raw)
                model_id = path.stem.removeprefix("full_").removesuffix("_fix")
                model_name = (seg_models.get(model_id) or {}).get("name") or model_id or str(idx)
                add_track(
                    f"AI 干声 · {model_name}",
                    "ai",
                    raw,
                    mute=True,
                    metadata={"stem": "ai_model", "model_id": model_id},
                )
        else:
            add_track("AI 翻唱干声", "ai", ai_merged or (ai_paths[0] if ai_paths else None))

        mid_clips: list[dict[str, Any]] = []
        if work_dir.exists():
            for p in sorted(work_dir.rglob("*")):
                if not p.is_file() or p.suffix.lower() not in config.AUDIO_EXTS + (".wav",):
                    continue
                try:
                    resolved = str(p.resolve())
                except OSError:
                    continue
                if resolved in known:
                    continue
                dur = float(self._ffmpeg.probe_duration(p) or 0.0)
                mid_clips.append(
                    EditorClip(
                        id=paths.new_id("clp_"),
                        name=p.stem,
                        start=0.0,
                        end=max(dur, 0.05),
                        offset=0.0,
                        volume=1.0,
                        mute=True,
                        file=str(p),
                        metadata={"work_id": work_id, "stem": "intermediate"},
                    ).to_dict()
                )
                if len(mid_clips) >= 12:
                    break
        if mid_clips:
            tracks.append(
                EditorTrack(
                    id=paths.new_id("trk_"),
                    name="中间片段",
                    type="effect",
                    clips=mid_clips,
                    mute=True,
                ).to_dict()
            )

        if not tracks:
            return None
        duration = self._project_duration({"tracks": tracks})
        project = EditorProject(
            id=pid,
            title=f"{work.get('title', '翻唱作品')} · 编辑",
            tracks=tracks,
            duration=max(duration, 0.05),
            metadata={"work_id": work_id, "mode": "from_work"},
            created_at=now,
            updated_at=now,
        ).to_dict()
        self._repo.add({**project, "history": [], "future": []})
        return self._public(project)

    def save(self, project: dict[str, Any], push_history: bool = True) -> dict[str, Any] | None:
        if not project or not project.get("id"):
            return None
        project_id = str(project["id"])
        current = self._repo.get(project_id)
        cleaned = self._clean(project)
        cleaned["updated_at"] = self._now()
        cleaned["duration"] = self._project_duration(cleaned)
        if current:
            history = list(current.get("history", []) or [])
            if push_history:
                history.append(self._snapshot(current))
                history = history[-self._HISTORY_LIMIT :]
            cleaned["history"] = history
            cleaned["future"] = [] if push_history else list(current.get("future", []) or [])
            self._repo.update(project_id, cleaned)
        else:
            now = cleaned.get("created_at") or self._now()
            cleaned["created_at"] = now
            cleaned["history"] = []
            cleaned["future"] = []
            self._repo.add(cleaned)
        return self._public(cleaned)

    def undo(self, project_id: str) -> dict[str, Any] | None:
        current = self._repo.get(project_id)
        if not current:
            return None
        history = list(current.get("history", []) or [])
        if not history:
            return self._public(current)
        prev = history.pop()
        future = list(current.get("future", []) or [])
        future.append(self._snapshot(current))
        next_record = {**prev, "history": history, "future": future, "updated_at": self._now()}
        self._repo.update(project_id, next_record)
        return self._public(next_record)

    def redo(self, project_id: str) -> dict[str, Any] | None:
        current = self._repo.get(project_id)
        if not current:
            return None
        future = list(current.get("future", []) or [])
        if not future:
            return self._public(current)
        nxt = future.pop()
        history = list(current.get("history", []) or [])
        history.append(self._snapshot(current))
        next_record = {**nxt, "history": history, "future": future, "updated_at": self._now()}
        self._repo.update(project_id, next_record)
        return self._public(next_record)

    def clip_audio(self, project_id: str, clip_id: str) -> str:
        project = self._repo.get(project_id)
        clip = self._find_clip(project, clip_id) if project else None
        if not clip:
            return ""
        return self._audio_data(Path(str(clip.get("file") or "")))

    def render_preview(self, project_id: str) -> str:
        path = self.render(project_id, "mp3")
        return self._audio_data(path) if path else ""

    def render(self, project_id: str, output_format: str = "wav") -> Path | None:
        project = self._repo.get(project_id)
        if not project:
            return None
        fmt = self._normalize_format(output_format)
        key = self._render_key(project, fmt)
        dst = config.EDITOR_CACHE_DIR / f"{project_id}_{key}.{fmt}"
        if dst.exists():
            return dst
        ok = self._audio.render_timeline(project, dst, config.EDITOR_CACHE_DIR, fmt)
        return dst if ok and dst.exists() else None

    def waveform(self, project_id: str, clip_id: str, bins: int = 160) -> dict[str, Any]:
        project = self._repo.get(project_id)
        clip = self._find_clip(project, clip_id) if project else None
        if not project or not clip:
            return {"ok": False, "peaks": []}
        cache_key = self._waveform_key(clip, bins)
        cache = dict(project.get("waveform_cache") or {})
        if cache_key in cache:
            return {"ok": True, **cache[cache_key]}
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
        peaks = self._compute_waveform(
            Path(str(clip.get("file") or "")),
            bins,
            offset=offset,
            duration=duration,
        )
        payload = {"clip_id": clip_id, "bins": bins, "peaks": peaks}
        cache[cache_key] = payload
        project["waveform_cache"] = cache
        self.save(project, push_history=False)
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

    def rerun_clip(
        self,
        project_id: str,
        track_id: str,
        clip_id: str,
        model_id: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project = self._repo.get(project_id)
        model = self._models.get(model_id) if model_id else None
        if not project or not model:
            return {"ok": False, "error": "工程或模型不存在"}
        track, idx, clip = self._find_clip_ref(project, track_id, clip_id)
        if not track or idx < 0 or not clip:
            return {"ok": False, "error": "片段不存在"}
        if track.get("locked") or clip.get("locked"):
            return {"ok": False, "error": "片段已锁定"}
        src = Path(str(clip.get("file") or ""))
        if not src.exists():
            return {"ok": False, "error": "片段音频不存在"}
        duration = float(clip.get("end") or 0) - float(clip.get("start") or 0)
        if duration < self._MIN_RERUN_DURATION:
            return {
                "ok": False,
                "error": f"片段过短：至少 {self._MIN_RERUN_DURATION:.2f} 秒才能重推理",
            }
        out_dir = self._project_dir(project_id) / "reruns"
        out_dir.mkdir(parents=True, exist_ok=True)
        dry = out_dir / f"{clip_id}_input.wav"
        out = out_dir / f"{clip_id}_{model_id}.wav"
        if not self._audio.trim(
            src,
            float(clip.get("offset") or 0.0),
            float(clip.get("offset") or 0.0) + duration,
            dry,
            sample_rate=int(project.get("sample_rate") or 44100),
        ):
            return {"ok": False, "error": "片段裁剪失败"}
        model_payload = self._model_payload(model)
        infer_params = InferenceParams.from_dict(params or {})
        engine = self._engines.for_model(model_payload)
        try:
            engine.infer(model_payload, dry, out, infer_params, duration)
        except Exception as exc:  # noqa: BLE001 - 需要把推理错误回传给前端
            return {"ok": False, "error": str(exc)}
        next_project = copy.deepcopy(project)
        next_track, next_idx, next_clip = self._find_clip_ref(next_project, track_id, clip_id)
        if not next_track or next_idx < 0 or not next_clip:
            return {"ok": False, "error": "片段替换失败"}
        next_clip = dict(next_clip)
        next_clip["file"] = str(out)
        next_clip["offset"] = 0.0
        next_clip["name"] = f"{next_clip.get('name') or 'clip'} · 重推理"
        meta = dict(next_clip.get("metadata") or {})
        meta.update({"rerun_model_id": model_id, "rerun_at": self._now()})
        next_clip["metadata"] = meta
        next_track["clips"][next_idx] = next_clip
        saved = self.save(next_project, push_history=True)
        return {"ok": True, "project": saved, "clip": next_clip}

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    @staticmethod
    def _public(project: dict[str, Any] | None) -> dict[str, Any] | None:
        if not project:
            return None
        view = dict(project)
        view.pop("history", None)
        view.pop("future", None)
        return view

    @staticmethod
    def _snapshot(project: dict[str, Any]) -> dict[str, Any]:
        snap = copy.deepcopy(project)
        snap.pop("history", None)
        snap.pop("future", None)
        return snap

    @staticmethod
    def _clean(project: dict[str, Any]) -> dict[str, Any]:
        cleaned = copy.deepcopy(project)
        cleaned.pop("history", None)
        cleaned.pop("future", None)
        cleaned.setdefault("waveform_cache", {})
        cleaned.setdefault("metadata", {})
        for track in cleaned.get("tracks", []) or []:
            for clip in track.get("clips", []) or []:
                channel = str(clip.get("channel") or "stereo").strip().lower()
                clip["channel"] = channel if channel in {"stereo", "left", "right"} else "stereo"
        return cleaned

    @staticmethod
    def _project_duration(project: dict[str, Any]) -> float:
        duration = 0.0
        for track in project.get("tracks", []) or []:
            for clip in track.get("clips", []) or []:
                try:
                    duration = max(duration, float(clip.get("end") or 0.0))
                except (TypeError, ValueError):
                    pass
        return max(duration, 0.05)

    @staticmethod
    def _normalize_format(fmt: str) -> str:
        value = (fmt or "wav").strip().lower().lstrip(".")
        return value if value in {"wav", "mp3", "flac"} else "wav"

    def _project_dir(self, project_id: str) -> Path:
        return config.EDITOR_DIR / project_id

    @staticmethod
    def _find_clip(project: dict[str, Any] | None, clip_id: str) -> dict[str, Any] | None:
        if not project:
            return None
        for track in project.get("tracks", []) or []:
            for clip in track.get("clips", []) or []:
                if clip.get("id") == clip_id:
                    return clip
        return None

    @staticmethod
    def _find_clip_ref(
        project: dict[str, Any], track_id: str, clip_id: str
    ) -> tuple[dict[str, Any] | None, int, dict[str, Any] | None]:
        for track in project.get("tracks", []) or []:
            if track.get("id") != track_id:
                continue
            for idx, clip in enumerate(track.get("clips", []) or []):
                if clip.get("id") == clip_id:
                    return track, idx, clip
        return None, -1, None

    def _audio_data(self, src: Path) -> str:
        if not src.exists():
            return ""
        data: bytes | None = None
        mime = "audio/wav"
        if self._ffmpeg.available:
            try:
                tmp = config.EDITOR_CACHE_DIR / f"aud_{FFmpegEngine.cache_key(str(src))}.mp3"
                if not tmp.exists():
                    self._ffmpeg.convert(src, tmp)
                if tmp.exists():
                    data = tmp.read_bytes()
                    mime = "audio/mpeg"
            except OSError:
                data = None
        if data is None:
            try:
                data = src.read_bytes()
            except OSError:
                return ""
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{b64}"

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
        return FFmpegEngine.cache_key({"project": payload, "stats": stats, "format": fmt})

    def _waveform_key(self, clip: dict[str, Any], bins: int) -> str:
        path = Path(str(clip.get("file") or ""))
        try:
            st = path.stat()
            stat = (str(path), st.st_size, int(st.st_mtime))
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
        return FFmpegEngine.cache_key(
            {
                "clip": clip.get("id"),
                "stat": stat,
                "offset": round(offset, 3),
                "duration": round(duration, 3),
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
        if self._ffmpeg.available:
            cached = config.EDITOR_CACHE_DIR / f"wf_{FFmpegEngine.cache_key(source_key)}.wav"
            cached.parent.mkdir(parents=True, exist_ok=True)
            if cached.exists() or self._ffmpeg.convert(src, cached, sample_rate=8000):
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
                target_bins = max(16, min(900, int(bins or 160), span))
                peaks: list[float] = []
                fmt = {1: "B", 2: "h", 4: "i"}[width]
                max_val = 128.0 if width == 1 else float((2 ** (width * 8 - 1)) - 1)
                current = start_frame
                wf.setpos(start_frame)
                for idx in range(target_bins):
                    end_frame = start_frame + round((idx + 1) * span / target_bins)
                    to_read = max(1, min(frames - current, end_frame - current))
                    raw = wf.readframes(to_read)
                    current += to_read
                    if not raw:
                        peaks.append(0.0)
                        break
                    count = len(raw) // width
                    if count <= 0:
                        peaks.append(0.0)
                        continue
                    samples = struct.unpack("<" + fmt * count, raw)
                    cur_peak = 0.0
                    for i in range(0, len(samples), channels):
                        if width == 1:
                            peak = max(abs(int(s) - 128) for s in samples[i : i + channels]) / max_val
                        else:
                            peak = max(abs(s) for s in samples[i : i + channels]) / max_val
                        cur_peak = max(cur_peak, min(1.0, peak))
                    peaks.append(round(cur_peak, 4))
                if len(peaks) < target_bins:
                    peaks.extend([0.0] * (target_bins - len(peaks)))
                return peaks[:target_bins]
        except (OSError, EOFError, wave.Error, struct.error):
            return []

    @staticmethod
    def _model_payload(model: dict[str, Any]) -> dict[str, str]:
        framework = config.modelhub_normalize_framework(
            model.get("framework") or config.modelhub_guess_framework(model.get("type"))
        )
        return {
            "framework": framework,
            "main_model_path": (model.get("main_model") or {}).get("path", ""),
            "main_config_path": (model.get("main_config") or {}).get("path", ""),
            "diffusion_model_path": (model.get("diffusion_model") or {}).get("path", ""),
            "diffusion_config_path": (model.get("diffusion_config") or {}).get("path", ""),
            "index_path": (model.get("index_file") or {}).get("path", ""),
        }
