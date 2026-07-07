"""轻量音频编辑器服务。"""

from __future__ import annotations

import base64
import copy
import json
import re
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
from infrastructure.clipboard import audio_files_from_clipboard, copy_file_to_clipboard
from infrastructure.ffmpeg_tool import FfmpegTool
from infrastructure.juce_vst3_host import JuceVst3Host
from infrastructure.storage import ListRepository
from infrastructure.uvr_tool import UvrTool

from .model_service import ModelService


class AudioEditorService:
    """Timeline Project 的应用层服务。"""

    _HISTORY_LIMIT = 60
    _MIN_RERUN_DURATION = 1.0
    _RENDER_VERSION = "channel-route-v7-effects-envelope-juce"

    def __init__(
        self,
        repo: ListRepository,
        works_repo: ListRepository,
        models: ModelService,
        ffmpeg: FfmpegTool,
        uvr: UvrTool,
        engines: Any,
    ) -> None:
        self._repo = repo
        self._works_repo = works_repo
        self._models = models
        self._ffmpeg = ffmpeg
        self._uvr = uvr
        self._audio = FFmpegEngine(ffmpeg)
        self._plugin_host = JuceVst3Host()
        self._plugin_sessions: dict[str, dict[str, str]] = {}
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

    def add_track(
        self,
        project_id: str,
        name: str | None = None,
        kind: str = "audio",
    ) -> dict[str, Any]:
        project = self._repo.get(project_id)
        if not project:
            return {"ok": False, "error": "工程不存在"}
        track_kind = str(kind or "audio").strip().lower()
        if track_kind not in {"source", "vocal", "bgm", "ai", "effect", "audio"}:
            track_kind = "audio"
        next_project = copy.deepcopy(project)
        tracks = next_project.setdefault("tracks", [])
        track = EditorTrack(
            id=paths.new_id("trk_"),
            name=((name or "").strip() or f"音轨 {len(tracks) + 1}")[:80],
            type=track_kind,
            clips=[],
            locked=False,
            mute=False,
            volume=1.0,
        ).to_dict()
        tracks.append(track)
        next_project["waveform_cache"] = {}
        saved = self.save(next_project, push_history=True)
        return {"ok": True, "project": saved, "track": track}

    def delete_track(self, project_id: str, track_id: str) -> dict[str, Any]:
        project = self._repo.get(project_id)
        if not project:
            return {"ok": False, "error": "工程不存在"}
        tracks = list(project.get("tracks") or [])
        track = next((t for t in tracks if t.get("id") == track_id), None)
        if not track:
            return {"ok": False, "error": "音轨不存在"}
        if track.get("locked"):
            return {"ok": False, "error": "音轨已锁定，不能删除"}
        next_project = copy.deepcopy(project)
        next_project["tracks"] = [
            item for item in (next_project.get("tracks") or []) if item.get("id") != track_id
        ]
        next_project["waveform_cache"] = {}
        saved = self.save(next_project, push_history=True)
        return {"ok": True, "project": saved, "removed_track_id": track_id}

    def import_audio_to_track(
        self,
        project_id: str,
        path: str,
        track_id: str | None = None,
        start: float = 0.0,
    ) -> dict[str, Any]:
        project = self._repo.get(project_id)
        src = Path(path) if path else None
        if not project:
            return {"ok": False, "error": "工程不存在"}
        if src is None or not src.exists():
            return {"ok": False, "error": "音频文件不存在"}

        media_dir = self._project_dir(project_id) / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        dst = self._unique_path(media_dir / src.name)
        try:
            if src.resolve() != dst.resolve():
                shutil.copy2(src, dst)
            else:
                dst = src
        except OSError:
            return {"ok": False, "error": "导入音频失败"}

        duration = float(self._ffmpeg.probe_duration(dst) or 0.0)
        if duration <= 0:
            return {"ok": False, "error": "无法识别音频时长"}
        try:
            clip_start = max(0.0, float(start or 0.0))
        except (TypeError, ValueError):
            clip_start = 0.0

        next_project = copy.deepcopy(project)
        tracks = next_project.setdefault("tracks", [])
        track = next((t for t in tracks if t.get("id") == track_id), None) if track_id else None
        if track and track.get("locked"):
            return {"ok": False, "error": "目标音轨已锁定"}
        if track is None:
            track = EditorTrack(
                id=paths.new_id("trk_"),
                name=f"音轨 {len(tracks) + 1}",
                type="audio",
                clips=[],
            ).to_dict()
            tracks.append(track)

        clip = EditorClip(
            id=paths.new_id("clp_"),
            name=dst.stem[:80],
            start=round(clip_start, 3),
            end=round(clip_start + max(duration, 0.05), 3),
            offset=0.0,
            volume=1.0,
            mute=False,
            file=str(dst),
            metadata={"source": "import", "source_path": str(src)},
        ).to_dict()
        track.setdefault("clips", []).append(clip)
        track["clips"] = sorted(track.get("clips") or [], key=lambda c: float(c.get("start") or 0.0))
        next_project["waveform_cache"] = {}
        saved = self.save(next_project, push_history=True)
        return {"ok": True, "project": saved, "track": track, "clip": clip}

    def paste_clipboard_audio_to_track(
        self,
        project_id: str,
        track_id: str | None = None,
        start: float = 0.0,
    ) -> dict[str, Any]:
        project = self._repo.get(project_id)
        if not project:
            return {"ok": False, "error": "工程不存在"}

        audio_paths = audio_files_from_clipboard()
        if not audio_paths:
            return {"ok": False, "error": "剪贴板里没有可粘贴的音频文件"}

        try:
            cursor = max(0.0, float(start or 0.0))
        except (TypeError, ValueError):
            cursor = 0.0

        target_track_id = str(track_id or "").strip() or None
        latest_project: dict[str, Any] | None = None
        latest_track: dict[str, Any] | None = None
        clips: list[dict[str, Any]] = []

        for audio_path in audio_paths:
            result = self.import_audio_to_track(
                project_id,
                str(audio_path),
                target_track_id,
                cursor,
            )
            if not result.get("ok"):
                if clips:
                    return {
                        **result,
                        "project": latest_project,
                        "track": latest_track,
                        "clips": clips,
                        "paths": [str(p) for p in audio_paths],
                    }
                return result

            latest_project = result.get("project")
            latest_track = result.get("track")
            if latest_track:
                target_track_id = str(latest_track.get("id") or target_track_id or "")
            clip = result.get("clip")
            if isinstance(clip, dict):
                clips.append(clip)
                try:
                    cursor = max(cursor, float(clip.get("end") or cursor))
                except (TypeError, ValueError):
                    pass

        return {
            "ok": True,
            "project": latest_project,
            "track": latest_track,
            "clip": clips[-1] if clips else None,
            "clips": clips,
            "paths": [str(p) for p in audio_paths],
        }

    def separate_clip_vocals(
        self,
        project_id: str,
        track_id: str,
        clip_id: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project = self._repo.get(project_id)
        if not project:
            return {"ok": False, "error": "工程不存在"}
        track, idx, clip = self._find_clip_ref(project, track_id, clip_id)
        if not track or idx < 0 or not clip:
            return {"ok": False, "error": "片段不存在"}
        if track.get("locked") or clip.get("locked"):
            return {"ok": False, "error": "片段已锁定"}
        src = Path(str(clip.get("file") or ""))
        if not src.exists():
            return {"ok": False, "error": "片段音频不存在"}
        if not self._ffmpeg.available:
            return {"ok": False, "error": "未找到 ffmpeg，无法裁剪片段并分离人声"}

        try:
            start = float(clip.get("start") or 0.0)
            end = float(clip.get("end") or 0.0)
            offset = max(0.0, float(clip.get("offset") or 0.0))
        except (TypeError, ValueError):
            return {"ok": False, "error": "片段时间无效"}
        duration = max(0.0, end - start)
        if duration < 0.1:
            return {"ok": False, "error": "片段太短，无法分离人声"}

        opts = options if isinstance(options, dict) else {}
        model = str(opts.get("model") or config.UVR_SEP_MODEL)
        device = str(opts.get("device") or "auto")
        mute_source = opts.get("mute_source", True) is not False
        out_dir = self._project_dir(project_id) / "stems" / f"{clip_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        dry = out_dir / "input.wav"
        if not self._audio.trim(
            src,
            offset,
            offset + duration,
            dry,
            sample_rate=int(project.get("sample_rate") or 44100),
        ):
            return {"ok": False, "error": "片段裁剪失败"}

        sep = self._uvr.separate(dry, out_dir, model, device)
        vocals = Path(sep.vocals)
        instrumental = Path(sep.instrumental) if sep.instrumental else None
        if not vocals.exists():
            return {"ok": False, "error": "人声分离失败"}

        next_project = copy.deepcopy(project)
        next_track, next_idx, next_clip = self._find_clip_ref(next_project, track_id, clip_id)
        if not next_track or next_idx < 0 or not next_clip:
            return {"ok": False, "error": "写入分离结果失败"}
        if mute_source:
            next_clip["mute"] = True

        tracks = next_project.setdefault("tracks", [])
        insert_at = next((i for i, t in enumerate(tracks) if t.get("id") == track_id), len(tracks) - 1) + 1
        base_name = str(clip.get("name") or src.stem or "片段")[:80]

        def make_track(kind: str, label: str, file_path: Path) -> dict[str, Any]:
            stem_clip = EditorClip(
                id=paths.new_id("clp_"),
                name=f"{base_name} - {label}",
                start=round(start, 3),
                end=round(start + duration, 3),
                offset=0.0,
                volume=1.0,
                mute=False,
                file=str(file_path),
                fade_in=float(clip.get("fade_in") or 0.0),
                fade_out=float(clip.get("fade_out") or 0.0),
                channel=str(clip.get("channel") or "stereo"),
                metadata={
                    "source": "uvr_separation",
                    "source_clip_id": clip_id,
                    "source_track_id": track_id,
                    "stem": kind,
                    "uvr_model": model,
                    "simulated": bool(sep.simulated),
                },
            ).to_dict()
            return EditorTrack(
                id=paths.new_id("trk_"),
                name=f"{label} - {base_name}"[:80],
                type="vocal" if kind == "vocals" else "bgm",
                clips=[stem_clip],
                locked=False,
                mute=False,
                volume=1.0,
            ).to_dict()

        created_tracks = [make_track("vocals", "人声", vocals)]
        if instrumental and instrumental.exists():
            created_tracks.append(make_track("instrumental", "伴奏", instrumental))
        tracks[insert_at:insert_at] = created_tracks
        next_project["waveform_cache"] = {}
        saved = self.save(next_project, push_history=True)
        created_clips = [c for t in created_tracks for c in (t.get("clips") or [])]
        return {
            "ok": True,
            "project": saved,
            "tracks": created_tracks,
            "clips": created_clips,
            "simulated": bool(sep.simulated),
        }

    def split_clip_by_lyrics(
        self,
        project_id: str,
        track_id: str,
        clip_id: str,
        lyrics: Any,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project = self._repo.get(project_id)
        if not project:
            return {"ok": False, "error": "工程不存在"}
        track, idx, clip = self._find_clip_ref(project, track_id, clip_id)
        if not track or idx < 0 or not clip:
            return {"ok": False, "error": "片段不存在"}
        if track.get("locked") or clip.get("locked"):
            return {"ok": False, "error": "片段已锁定"}

        opts = options if isinstance(options, dict) else {}
        try:
            clip_start = float(clip.get("start") or 0.0)
            clip_end = float(clip.get("end") or 0.0)
            offset = max(0.0, float(clip.get("offset") or 0.0))
        except (TypeError, ValueError):
            return {"ok": False, "error": "片段时间无效"}
        duration = max(0.0, clip_end - clip_start)
        if duration < 0.1:
            return {"ok": False, "error": "片段太短，无法按歌词切分"}

        lines = self._parse_lyric_lines(lyrics)
        if not lines:
            return {"ok": False, "error": "没有识别到带时间戳的歌词"}

        def opt_float(name: str, default: float) -> float:
            try:
                return float(opts.get(name, default))
            except (TypeError, ValueError):
                return default

        time_mode = str(opts.get("time_mode") or "project").strip().lower()
        if time_mode not in {"project", "clip"}:
            time_mode = "project"
        padding = max(0.0, min(0.5, opt_float("padding", 0.04)))
        min_clip = max(0.05, min(10.0, opt_float("min_clip", 0.2)))
        ranges: list[dict[str, Any]] = []
        sorted_lines = sorted(lines, key=lambda x: float(x.get("time") or 0.0))
        for i, line in enumerate(sorted_lines):
            raw_start = float(line.get("time") or 0.0)
            raw_end = (
                float(sorted_lines[i + 1].get("time") or raw_start)
                if i + 1 < len(sorted_lines)
                else clip_end if time_mode != "clip" else duration
            )
            if time_mode == "clip":
                abs_start = clip_start + raw_start
                abs_end = clip_start + raw_end
            else:
                abs_start = raw_start
                abs_end = raw_end
            rel_start = max(0.0, min(duration, abs_start - clip_start - padding))
            rel_end = max(rel_start, min(duration, abs_end - clip_start + padding))
            if rel_end - rel_start < min_clip:
                continue
            ranges.append(
                {
                    "start": rel_start,
                    "end": rel_end,
                    "text": str(line.get("text") or "").strip(),
                    "source_time": raw_start,
                }
            )

        if len(ranges) <= 1:
            return {"ok": False, "error": "歌词时间点不足以切成多个片段", "lines": lines}

        next_project = copy.deepcopy(project)
        next_track, next_idx, original = self._find_clip_ref(next_project, track_id, clip_id)
        if not next_track or next_idx < 0 or not original:
            return {"ok": False, "error": "写入歌词切分结果失败"}

        original = copy.deepcopy(original)
        base_name = str(original.get("name") or Path(str(original.get("file") or "")).stem or "人声")
        new_clips: list[dict[str, Any]] = []
        total = len(ranges)
        for i, item_range in enumerate(ranges):
            rel_start = float(item_range["start"])
            rel_end = float(item_range["end"])
            text = str(item_range.get("text") or "").strip()
            item = copy.deepcopy(original)
            item["id"] = str(original.get("id")) if i == 0 else paths.new_id("clp_")
            item["name"] = f"{base_name} {i + 1:02d}/{total:02d}" + (f" {text[:18]}" if text else "")
            item["start"] = round(clip_start + rel_start, 3)
            item["end"] = round(clip_start + rel_end, 3)
            item["offset"] = round(offset + rel_start, 3)
            item["effects"] = copy.deepcopy(original.get("effects") or [])
            meta = dict(original.get("metadata") or {})
            meta.update(
                {
                    "lyric_split": True,
                    "lyric_split_at": self._now(),
                    "lyric_split_index": i + 1,
                    "lyric_split_total": total,
                    "lyric_text": text,
                    "lyric_time": item_range.get("source_time"),
                    "lyric_time_mode": time_mode,
                }
            )
            item["metadata"] = meta
            new_clips.append(item)

        clips = list(next_track.get("clips") or [])
        clips[next_idx : next_idx + 1] = new_clips
        next_track["clips"] = sorted(clips, key=lambda c: float(c.get("start") or 0.0))
        next_project["waveform_cache"] = {}
        saved = self.save(next_project, push_history=True)
        return {"ok": True, "project": saved, "clips": new_clips, "lines": lines}

    def create_from_work(self, work_id: str) -> dict[str, Any] | None:
        work = self._works_repo.get(work_id)
        if not work:
            return None
        pid = paths.new_id("edt_")
        now = self._now()
        tracks: list[dict[str, Any]] = []
        known: set[str] = set()
        workflow = str(work.get("workflow") or "auto_mix")
        vocal_export = workflow == "manual_vocal_merge"

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

        def model_id_from_path(raw: str) -> str:
            stem = Path(raw).stem
            if stem.startswith("full_"):
                stem = stem[5:]
            if stem.endswith("_fix"):
                stem = stem[:-4]
            return stem

        def add_model_timeline_tracks(ai_paths: list[str]) -> bool:
            seg_models = work.get("seg_models") or {}
            segments = work.get("segments") or []
            segment_clips = work.get("ai_segment_clips") or []
            if segment_clips:
                clips_by_model: dict[str, list[dict[str, Any]]] = {}
                names_by_model: dict[str, str] = {}
                for item in segment_clips:
                    model_id = str(item.get("model_id") or "").strip()
                    src = Path(str(item.get("file") or ""))
                    if not model_id or not src.exists():
                        continue
                    try:
                        start = max(0.0, float(item.get("start") or 0.0))
                        end = max(start, float(item.get("end") or 0.0))
                        offset = max(0.0, float(item.get("offset") or 0.0))
                        fade_in = max(0.0, float(item.get("fade_in") or 0.0))
                        fade_out = max(0.0, float(item.get("fade_out") or 0.0))
                    except (TypeError, ValueError):
                        continue
                    if end <= start:
                        continue
                    model_name = (
                        str(item.get("model_name") or "").strip()
                        or (seg_models.get(model_id) or {}).get("name")
                        or model_id
                    )
                    names_by_model[model_id] = model_name
                    clips_by_model.setdefault(model_id, []).append(
                        EditorClip(
                            id=paths.new_id("clp_"),
                            name=f"{model_name} {self._fmt_time(start)}",
                            start=start,
                            end=end,
                            offset=offset,
                            volume=1.0,
                            mute=False,
                            file=str(src),
                            fade_in=fade_in,
                            fade_out=fade_out,
                            metadata={
                                "work_id": work_id,
                                "stem": "ai_model_segment",
                                "model_id": model_id,
                                "source_start": item.get("source_start", start),
                                "source_end": item.get("source_end", end),
                            },
                        ).to_dict()
                    )
                    remember(str(src))
                for idx, (model_id, clips) in enumerate(clips_by_model.items(), start=1):
                    model_name = names_by_model.get(model_id) or model_id or str(idx)
                    tracks.append(
                        EditorTrack(
                            id=paths.new_id("trk_"),
                            name=f"AI · {model_name}",
                            type="ai",
                            clips=sorted(clips, key=lambda c: float(c.get("start") or 0.0)),
                        ).to_dict()
                    )
                return bool(clips_by_model)

            path_by_model = {model_id_from_path(raw): raw for raw in ai_paths}
            if not segments or not path_by_model:
                return False
            added = False
            for idx, (model_id, raw) in enumerate(path_by_model.items(), start=1):
                src = Path(raw)
                if not src.exists():
                    continue
                model_name = (seg_models.get(model_id) or {}).get("name") or model_id or str(idx)
                clips: list[dict[str, Any]] = []
                for seg in segments:
                    raw_ids = seg.get("model_ids") or (
                        [seg.get("model_id")] if seg.get("model_id") else []
                    )
                    mids = raw_ids if isinstance(raw_ids, list) else [raw_ids]
                    if model_id not in mids:
                        continue
                    try:
                        start = max(0.0, float(seg.get("start") or 0.0))
                        end = max(start, float(seg.get("end") or 0.0))
                    except (TypeError, ValueError):
                        continue
                    if end <= start:
                        continue
                    clips.append(
                        EditorClip(
                            id=paths.new_id("clp_"),
                            name=f"{model_name} {self._fmt_time(start)}",
                            start=start,
                            end=end,
                            offset=start,
                            volume=1.0,
                            mute=False,
                            file=str(src),
                            fade_in=0.03,
                            fade_out=0.03,
                            metadata={
                                "work_id": work_id,
                                "stem": "ai_model_segment",
                                "model_id": model_id,
                            },
                        ).to_dict()
                    )
                if not clips:
                    continue
                remember(raw)
                tracks.append(
                    EditorTrack(
                        id=paths.new_id("trk_"),
                        name=f"AI · {model_name}",
                        type="ai",
                        clips=clips,
                    ).to_dict()
                )
                added = True
            return added

        add_track("原始音频", "source", work.get("source_path"), locked=True, mute=True)
        add_track("原始人声", "vocal", work.get("vocals_path"), mute=True)
        add_track("BGM 轨", "bgm", work.get("instrumental_path"), mute=vocal_export)
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
            remember(ai_merged)
            if not add_model_timeline_tracks(ai_paths):
                seg_models = work.get("seg_models") or {}
                for idx, raw in enumerate(ai_paths, start=1):
                    model_id = model_id_from_path(raw)
                    model_name = (seg_models.get(model_id) or {}).get("name") or model_id or str(idx)
                    add_track(
                        f"AI · {model_name}",
                        "ai",
                        raw,
                        metadata={"stem": "ai_model", "model_id": model_id},
                    )
        else:
            add_track("AI 翻唱干声", "ai", ai_merged or (ai_paths[0] if ai_paths else None))

        mid_clips: list[dict[str, Any]] = []
        if work_dir.exists():
            candidates = [
                work_dir / "infer_input.wav",
                work_dir / "converted.wav",
                work_dir / "output.wav",
                work_dir / "vocals.wav",
                work_dir / "instrumental.wav",
            ]
            candidates.extend(sorted(work_dir.glob("full_*.wav"))[:6])
            candidates.extend(sorted((work_dir / "segments").glob("piece_*.wav"))[:4])
            for p in candidates:
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
            metadata={
                "work_id": work_id,
                "mode": "from_work",
                "workflow": workflow,
                "export_mode": "vocal" if vocal_export else "mix",
            },
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
        dst = self._render_clip_file(project_id, clip_id, "flac", cache=True)
        return self._audio_data(dst, exact=True) if dst and dst.exists() else ""

    def copy_clip_audio(
        self,
        project_id: str,
        clip_id: str,
        fmt: str = "wav",
    ) -> dict[str, Any]:
        dst = self._render_clip_file(project_id, clip_id, fmt, cache=False)
        return self._clipboard_payload(dst)

    def copy_track_audio(
        self,
        project_id: str,
        track_id: str,
        fmt: str = "wav",
    ) -> dict[str, Any]:
        dst = self._render_track_file(project_id, track_id, fmt)
        return self._clipboard_payload(dst)

    def plugin_host_status(self) -> dict[str, Any]:
        return self._plugin_host.status()

    def inspect_effect_plugin(self, path: str) -> dict[str, Any]:
        return self._plugin_host.inspect_plugin(path)

    def open_effect_plugin_editor(
        self,
        project_id: str,
        track_id: str,
        clip_id: str,
        effect_id: str,
        parent_window: str = "",
    ) -> dict[str, Any]:
        project = self._repo.get(project_id)
        if not project:
            return {"ok": False, "error": "工程不存在", **self._plugin_host.status()}
        track, _, clip = self._find_clip_ref(project, track_id, clip_id)
        if not track or not clip:
            return {"ok": False, "error": "片段不存在", **self._plugin_host.status()}
        effect = self._find_effect(clip, effect_id)
        if not effect:
            return {"ok": False, "error": "效果器不存在", **self._plugin_host.status()}
        result = self._plugin_host.show_editor(
            effect,
            project_id=project_id,
            clip_id=clip_id,
            effect_id=effect_id,
            parent_window=parent_window,
        )
        session_id = str(result.get("session_id") or "")
        if result.get("ok") and session_id:
            self._plugin_sessions[session_id] = {
                "project_id": project_id,
                "track_id": track_id,
                "clip_id": clip_id,
                "effect_id": effect_id,
            }
        return result

    def close_effect_plugin_editor(self, session_id: str) -> dict[str, Any]:
        result = self._plugin_host.close_editor(session_id)
        ref = self._plugin_sessions.pop(session_id or "", None)
        if result.get("ok") and ref:
            project = self._apply_plugin_state(ref, result.get("plugin"))
            if project:
                result["project"] = project
        return result

    def _apply_plugin_state(
        self,
        ref: dict[str, str],
        plugin: Any,
    ) -> dict[str, Any] | None:
        if not isinstance(plugin, dict):
            return None
        project = self._repo.get(ref.get("project_id", ""))
        if not project:
            return None
        _, _, clip = self._find_clip_ref(
            project,
            ref.get("track_id", ""),
            ref.get("clip_id", ""),
        )
        if not clip:
            return None
        effect = self._find_effect(clip, ref.get("effect_id", ""))
        if not effect:
            return None

        params = dict(effect.get("params") or {})
        state = plugin.get("state")
        if isinstance(state, str) and state:
            params["state"] = state
        values = plugin.get("parameter_values")
        if isinstance(values, dict):
            params["parameters"] = {
                str(key): value
                for key, value in values.items()
                if isinstance(value, (int, float))
            }
        name = plugin.get("name")
        if isinstance(name, str) and name:
            params["plugin_name"] = name
        effect["params"] = params
        project["updated_at"] = self._now()
        project["duration"] = self._project_duration(project)
        self._repo.update(str(project.get("id") or ""), project)
        return self._public(project)

    def render_preview(self, project_id: str) -> str:
        path = self.render(project_id, "flac")
        return self._audio_data(path, exact=True) if path else ""

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
            "tracks": [
                {
                    "id": track.get("id"),
                    "name": track.get("name", ""),
                    "type": track.get("type", "audio"),
                    "volume": track.get("volume", 1.0),
                    "mute": False,
                    "clips": [preview_clip],
                }
            ],
        }
        output_format = self._normalize_format(fmt)
        key = FFmpegEngine.cache_key(
            {
                "render_version": self._RENDER_VERSION,
                "project_id": project_id,
                "clip": preview_clip,
                "track_volume": track.get("volume", 1.0),
                "sample_rate": preview_project["sample_rate"],
                "format": output_format,
            }
        )
        if cache:
            dst = config.EDITOR_CACHE_DIR / f"{project_id}_{clip_id}_{key}.{output_format}"
        else:
            export_dir = self._project_dir(project_id) / "copied"
            export_dir.mkdir(parents=True, exist_ok=True)
            name = self._safe_stem(str(clip.get("name") or Path(str(clip.get("file") or "")).stem))
            dst = export_dir / f"{name}_{key}.{output_format}"
        if dst.exists():
            return dst
        ok = self._audio.render_timeline(preview_project, dst, config.EDITOR_CACHE_DIR, output_format)
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
        output_format = self._normalize_format(fmt)
        track_project = {
            "id": project_id,
            "duration": max(float(project.get("duration") or 0.05), self._project_duration({"tracks": [track]})),
            "sample_rate": project.get("sample_rate") or 44100,
            "tracks": [{**copy.deepcopy(track), "mute": False}],
        }
        key = FFmpegEngine.cache_key(
            {
                "render_version": self._RENDER_VERSION,
                "project_id": project_id,
                "track": track_project,
                "format": output_format,
            }
        )
        export_dir = self._project_dir(project_id) / "copied"
        export_dir.mkdir(parents=True, exist_ok=True)
        dst = export_dir / f"{self._safe_stem(str(track.get('name') or 'track'))}_{key}.{output_format}"
        if dst.exists():
            return dst
        ok = self._audio.render_timeline(track_project, dst, config.EDITOR_CACHE_DIR, output_format)
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

    def split_clip_by_silence(
        self,
        project_id: str,
        track_id: str,
        clip_id: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project = self._repo.get(project_id)
        if not project:
            return {"ok": False, "error": "工程不存在"}
        track, idx, clip = self._find_clip_ref(project, track_id, clip_id)
        if not track or idx < 0 or not clip:
            return {"ok": False, "error": "片段不存在"}
        if track.get("locked") or clip.get("locked"):
            return {"ok": False, "error": "片段已锁定"}
        src = Path(str(clip.get("file") or ""))
        if not src.exists():
            return {"ok": False, "error": "片段音频不存在"}
        if not self._ffmpeg.available:
            return {"ok": False, "error": "未找到 ffmpeg，无法进行静音检测"}

        opts = options if isinstance(options, dict) else {}

        def opt(name: str, default: float) -> float:
            try:
                return float(opts.get(name, default))
            except (TypeError, ValueError):
                return default

        noise_db = min(-1.0, max(-90.0, opt("threshold_db", opt("noise_db", -40.0))))
        min_silence = max(0.1, min(5.0, opt("min_silence", 0.35)))
        min_clip = max(0.05, min(30.0, opt("min_clip", 0.45)))
        crossfade = max(0.0, min(0.8, opt("crossfade", 0.06)))
        try:
            start = float(clip.get("start") or 0.0)
            end = float(clip.get("end") or 0.0)
            offset = max(0.0, float(clip.get("offset") or 0.0))
        except (TypeError, ValueError):
            return {"ok": False, "error": "片段时间无效"}
        duration = max(0.0, end - start)
        if duration < max(0.1, min_clip * 2):
            return {"ok": False, "error": "片段太短，无法按静音切句"}

        padding = max(0.0, min(0.5, opt("padding", opt("keep_silence", 0.08))))
        attempts: list[tuple[float, float]] = [(noise_db, min_silence)]
        if opts.get("adaptive", True) is not False:
            for retry_db in (noise_db + 4.0, noise_db + 8.0, noise_db - 4.0):
                retry_db = min(-1.0, max(-90.0, retry_db))
                if (retry_db, min_silence) not in attempts:
                    attempts.append((retry_db, min_silence))
            shorter = max(0.1, min_silence * 0.72)
            if shorter != min_silence:
                attempts.append((noise_db, shorter))

        best_silences: list[dict[str, float]] = []
        speech_ranges: list[tuple[float, float]] = []
        used_noise_db = noise_db
        used_min_silence = min_silence
        for candidate_db, candidate_silence in attempts:
            candidate_silences = self._ffmpeg.detect_silences(
                src,
                start=offset,
                end=offset + duration,
                noise_db=candidate_db,
                min_duration=candidate_silence,
            )
            candidate_ranges = self._speech_ranges_from_silence(
                duration,
                candidate_silences,
                min_clip=min_clip,
                padding=padding,
                min_silence=candidate_silence,
            )
            best_silences = candidate_silences
            speech_ranges = candidate_ranges
            used_noise_db = candidate_db
            used_min_silence = candidate_silence
            if len(candidate_ranges) > 1:
                break

        if len(speech_ranges) > 1:
            next_project = copy.deepcopy(project)
            next_track, next_idx, original = self._find_clip_ref(next_project, track_id, clip_id)
            if not next_track or next_idx < 0 or not original:
                return {"ok": False, "error": "片段切分失败"}
            original = copy.deepcopy(original)
            total = len(speech_ranges)
            base_name = str(original.get("name") or src.stem or "片段")
            new_clips: list[dict[str, Any]] = []
            for i, (rel_start, rel_end) in enumerate(speech_ranges):
                if rel_end - rel_start < 0.05:
                    continue
                fade = round(
                    min(crossfade, max(0.0, (rel_end - rel_start) / 2.0 - 0.001)),
                    3,
                )
                item = copy.deepcopy(original)
                item["id"] = str(original.get("id")) if i == 0 else paths.new_id("clp_")
                item["name"] = f"{base_name} {i + 1:02d}/{total:02d}"
                item["start"] = round(start + rel_start, 3)
                item["end"] = round(start + rel_end, 3)
                item["offset"] = round(offset + rel_start, 3)
                item["fade_in"] = float(original.get("fade_in") or 0.0) if i == 0 else fade
                item["fade_out"] = float(original.get("fade_out") or 0.0) if i == total - 1 else fade
                item["effects"] = copy.deepcopy(original.get("effects") or [])
                meta = dict(original.get("metadata") or {})
                meta.update(
                    {
                        "silence_split": True,
                        "silence_split_mode": "speech_range",
                        "silence_split_at": self._now(),
                        "silence_split_index": i + 1,
                        "silence_split_total": total,
                        "silence_split_source": original.get("id"),
                        "silence_split_range": [round(rel_start, 3), round(rel_end, 3)],
                        "silence_split_threshold_db": used_noise_db,
                        "silence_split_min_silence": used_min_silence,
                        "silence_split_padding": padding,
                    }
                )
                item["metadata"] = meta
                new_clips.append(item)
            if len(new_clips) > 1:
                clips = list(next_track.get("clips") or [])
                clips[next_idx : next_idx + 1] = new_clips
                next_track["clips"] = sorted(clips, key=lambda c: float(c.get("start") or 0.0))
                next_project["waveform_cache"] = {}
                saved = self.save(next_project, push_history=True)
                return {
                    "ok": True,
                    "project": saved,
                    "clips": new_clips,
                    "cuts": [round(start + rel_start, 3) for rel_start, _ in speech_ranges[1:]],
                    "relative_cuts": [round(rel_start, 3) for rel_start, _ in speech_ranges[1:]],
                    "silences": best_silences,
                }

        silences = self._ffmpeg.detect_silences(
            src,
            start=offset,
            end=offset + duration,
            noise_db=noise_db,
            min_duration=min_silence,
        )
        cuts: list[float] = []
        for silence in silences:
            try:
                silence_start = max(0.0, min(duration, float(silence.get("start") or 0.0)))
                silence_end = max(silence_start, min(duration, float(silence.get("end") or 0.0)))
            except (TypeError, ValueError):
                continue
            if silence_end - silence_start < min_silence:
                continue
            cut = round((silence_start + silence_end) / 2.0, 3)
            if cut <= min_clip or duration - cut < min_clip:
                continue
            if cuts and cut - cuts[-1] < min_clip:
                continue
            cuts.append(cut)

        if not cuts:
            error = (
                "没有检测到足够长的静音"
                if not silences
                else "检测到的静音点太靠近片段边缘"
            )
            return {"ok": False, "error": error, "silences": silences}

        next_project = copy.deepcopy(project)
        next_track, next_idx, original = self._find_clip_ref(next_project, track_id, clip_id)
        if not next_track or next_idx < 0 or not original:
            return {"ok": False, "error": "片段切分失败"}

        original = copy.deepcopy(original)
        total = len(cuts) + 1
        max_fade = max(0.0, min_clip / 2.0 - 0.001)
        fade = round(min(crossfade, max_fade), 3)
        half = fade / 2.0
        boundaries = [0.0, *cuts, duration]
        base_name = str(original.get("name") or src.stem or "片段")
        new_clips: list[dict[str, Any]] = []
        for i in range(total):
            base_start = boundaries[i]
            base_end = boundaries[i + 1]
            rel_start = max(0.0, base_start - (half if i > 0 else 0.0))
            rel_end = min(duration, base_end + (half if i < total - 1 else 0.0))
            if rel_end - rel_start < 0.05:
                continue
            item = copy.deepcopy(original)
            item["id"] = str(original.get("id")) if i == 0 else paths.new_id("clp_")
            item["name"] = f"{base_name} {i + 1:02d}/{total:02d}"
            item["start"] = round(start + rel_start, 3)
            item["end"] = round(start + rel_end, 3)
            item["offset"] = round(offset + rel_start, 3)
            item["fade_in"] = float(original.get("fade_in") or 0.0) if i == 0 else fade
            item["fade_out"] = float(original.get("fade_out") or 0.0) if i == total - 1 else fade
            item["effects"] = copy.deepcopy(original.get("effects") or [])
            meta = dict(original.get("metadata") or {})
            meta.update(
                {
                    "silence_split": True,
                    "silence_split_at": self._now(),
                    "silence_split_index": i + 1,
                    "silence_split_total": total,
                    "silence_split_source": original.get("id"),
                    "silence_split_range": [round(base_start, 3), round(base_end, 3)],
                    "silence_split_threshold_db": noise_db,
                    "silence_split_min_silence": min_silence,
                }
            )
            item["metadata"] = meta
            new_clips.append(item)

        if len(new_clips) <= 1:
            return {"ok": False, "error": "切分结果不足两段", "silences": silences}

        clips = list(next_track.get("clips") or [])
        clips[next_idx : next_idx + 1] = new_clips
        next_track["clips"] = sorted(clips, key=lambda c: float(c.get("start") or 0.0))
        next_project["waveform_cache"] = {}
        saved = self.save(next_project, push_history=True)
        return {
            "ok": True,
            "project": saved,
            "clips": new_clips,
            "cuts": [round(start + cut, 3) for cut in cuts],
            "relative_cuts": cuts,
            "silences": silences,
        }

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
        infer_params = InferenceParams.from_dict(params or {})
        used_params = infer_params.to_dict()
        rerun_key = self._rerun_key(src, clip, model_id, used_params)
        dry = out_dir / f"{clip_id}_{rerun_key}_input.wav"
        out = out_dir / f"{clip_id}_{model_id}_{rerun_key}.wav"
        for stale in (dry, out):
            try:
                stale.unlink(missing_ok=True)
            except OSError:
                return {"ok": False, "error": "无法清理上一次重推理缓存"}
        if not self._audio.trim(
            src,
            float(clip.get("offset") or 0.0),
            float(clip.get("offset") or 0.0) + duration,
            dry,
            sample_rate=int(project.get("sample_rate") or 44100),
        ):
            return {"ok": False, "error": "片段裁剪失败"}
        model_payload = self._model_payload(model)
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
        old_effects = self._clean_effects(next_clip.get("effects"))
        plugin_effects = [effect for effect in old_effects if self._is_plugin_effect(effect)]
        next_clip["effects"] = [
            effect for effect in old_effects if not self._is_plugin_effect(effect)
        ]
        meta = dict(next_clip.get("metadata") or {})
        meta.update(
            {
                "rerun_model_id": model_id,
                "rerun_params": used_params,
                "rerun_at": self._now(),
                "rerun_input": str(dry),
                "rerun_source_file": str(src),
                "rerun_dry_effects": True,
            }
        )
        if plugin_effects:
            meta["rerun_removed_plugin_effects"] = plugin_effects
        next_clip["metadata"] = meta
        next_track["clips"][next_idx] = next_clip
        next_project["waveform_cache"] = {}
        saved = self.save(next_project, push_history=True)
        return {"ok": True, "project": saved, "clip": next_clip}

    @staticmethod
    def _clipboard_payload(path: Path | None) -> dict[str, Any]:
        if path is None or not path.exists():
            return {"ok": False, "error": "音频渲染失败", "path": ""}
        copied = copy_file_to_clipboard(path)
        payload: dict[str, Any] = {
            "ok": True,
            "path": str(path),
            "clipboard": copied,
        }
        if not copied:
            payload["error"] = "音频已生成，但系统剪贴板不可用"
        return payload

    @staticmethod
    def _safe_stem(name: str) -> str:
        cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name or "").strip().strip(".")
        return (cleaned[:80] or "audio").strip()

    @staticmethod
    def _unique_path(path: Path) -> Path:
        if not path.exists():
            return path
        stem = path.stem
        suffix = path.suffix
        for idx in range(1, 1000):
            candidate = path.with_name(f"{stem}_{idx:02d}{suffix}")
            if not candidate.exists():
                return candidate
        return path.with_name(f"{stem}_{paths.new_id('')}{suffix}")

    @staticmethod
    def _parse_lyric_lines(lyrics: Any) -> list[dict[str, Any]]:
        lines: list[dict[str, Any]] = []
        if isinstance(lyrics, list):
            for item in lyrics:
                if not isinstance(item, dict):
                    continue
                try:
                    time_value = float(item.get("time") or item.get("start") or 0.0)
                except (TypeError, ValueError):
                    continue
                if time_value < 0:
                    continue
                lines.append({"time": round(time_value, 3), "text": str(item.get("text") or "")})
            return sorted(lines, key=lambda x: float(x["time"]))

        text = str(lyrics or "")
        stamp_re = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
        for raw in text.splitlines():
            matches = list(stamp_re.finditer(raw))
            if not matches:
                continue
            body = stamp_re.sub("", raw).strip()
            for match in matches:
                minute = int(match.group(1))
                second = int(match.group(2))
                fraction_raw = match.group(3) or "0"
                fraction = int(fraction_raw) / (10 ** len(fraction_raw))
                lines.append(
                    {
                        "time": round(minute * 60 + second + fraction, 3),
                        "text": body,
                    }
                )
        return sorted(lines, key=lambda x: float(x["time"]))

    @staticmethod
    def _speech_ranges_from_silence(
        duration: float,
        silences: list[dict[str, float]],
        min_clip: float,
        padding: float,
        min_silence: float,
    ) -> list[tuple[float, float]]:
        ranges: list[tuple[float, float]] = []
        cursor = 0.0
        for silence in sorted(silences, key=lambda x: float(x.get("start") or 0.0)):
            try:
                silence_start = max(0.0, min(duration, float(silence.get("start") or 0.0)))
                silence_end = max(silence_start, min(duration, float(silence.get("end") or 0.0)))
            except (TypeError, ValueError):
                continue
            if silence_end - silence_start < min_silence:
                continue
            if silence_start - cursor >= min_clip:
                ranges.append(
                    (
                        max(0.0, cursor - padding),
                        min(duration, silence_start + padding),
                    )
                )
            cursor = max(cursor, silence_end)
        if duration - cursor >= min_clip:
            ranges.append((max(0.0, cursor - padding), duration))

        merged: list[tuple[float, float]] = []
        for start, end in ranges:
            if end - start < min_clip:
                continue
            if merged and start <= merged[-1][1] + 0.01:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((round(start, 3), round(end, 3)))
        return merged

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        s = max(0, int(seconds or 0))
        return f"{s // 60:02d}:{s % 60:02d}"

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
            track.setdefault("metadata", {})
            for clip in track.get("clips", []) or []:
                channel = str(clip.get("channel") or "stereo").strip().lower()
                clip["channel"] = channel if channel in {"stereo", "left", "right"} else "stereo"
                clip["effects"] = AudioEditorService._clean_effects(clip.get("effects"))
                try:
                    clip_duration = max(
                        0.01,
                        float(clip.get("end") or 0.0) - float(clip.get("start") or 0.0),
                    )
                except (TypeError, ValueError):
                    clip_duration = 0.01
                clip["volume_envelope"] = AudioEditorService._clean_volume_envelope(
                    clip.get("volume_envelope"),
                    clip_duration,
                )
        return cleaned

    @staticmethod
    def _clean_effects(raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        cleaned: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            effect_type = str(item.get("type") or "").strip().lower().replace("-", "_")
            if not effect_type:
                continue
            params = item.get("params")
            effect = {
                "id": str(item.get("id") or paths.new_id("fx_")),
                "type": effect_type,
                "name": str(item.get("name") or effect_type),
                "enabled": item.get("enabled", True) is not False,
                "params": dict(params) if isinstance(params, dict) else {},
            }
            for key, value in item.items():
                if key not in effect and key not in {"params"}:
                    effect[key] = value
            cleaned.append(effect)
        return cleaned

    @staticmethod
    def _is_plugin_effect(effect: dict[str, Any]) -> bool:
        effect_type = str(effect.get("type") or "").strip().lower().replace("-", "_")
        return effect_type in {
            "plugin",
            "vst",
            "vst3",
            "external",
            "external_plugin",
            "juce",
            "juce_vst3",
        }

    @staticmethod
    def _clean_volume_envelope(raw: Any, duration: float) -> list[dict[str, float]]:
        if not isinstance(raw, list):
            return []
        points: list[tuple[float, float]] = []
        dur = max(0.01, float(duration or 0.01))
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                time_value = float(item.get("time", item.get("t", 0.0)) or 0.0)
                volume = float(item.get("volume", item.get("value", 1.0)) or 0.0)
            except (TypeError, ValueError):
                continue
            points.append((max(0.0, min(dur, time_value)), max(0.0, min(2.5, volume))))
        by_time: dict[float, float] = {}
        for time_value, volume in sorted(points, key=lambda point: point[0]):
            by_time[round(time_value, 3)] = round(volume, 4)
        return [{"time": time_value, "volume": by_time[time_value]} for time_value in sorted(by_time)]

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

    @staticmethod
    def _rerun_key(
        src: Path,
        clip: dict[str, Any],
        model_id: str,
        params: dict[str, Any],
    ) -> str:
        try:
            stat = src.stat()
            source = (str(src.resolve()), stat.st_size, int(stat.st_mtime_ns))
        except OSError:
            source = (str(src), 0, 0)
        return FFmpegEngine.cache_key(
            {
                "version": "editor-rerun-dry-v2",
                "source": source,
                "offset": clip.get("offset"),
                "start": clip.get("start"),
                "end": clip.get("end"),
                "channel": clip.get("channel"),
                "model_id": model_id,
                "params": params,
            }
        )

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

    @staticmethod
    def _find_effect(clip: dict[str, Any], effect_id: str) -> dict[str, Any] | None:
        for effect in clip.get("effects", []) or []:
            if isinstance(effect, dict) and str(effect.get("id") or "") == effect_id:
                return effect
        return None

    def _audio_data(self, src: Path, exact: bool = False) -> str:
        if not src.exists():
            return ""
        data: bytes | None = None
        mime_by_ext = {
            ".flac": "audio/flac",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
        }
        mime = mime_by_ext.get(src.suffix.lower(), "audio/wav")
        if exact or src.suffix.lower() == ".mp3":
            try:
                data = src.read_bytes()
            except OSError:
                data = None
        if self._ffmpeg.available:
            try:
                tmp = config.EDITOR_CACHE_DIR / f"aud_{FFmpegEngine.cache_key(str(src))}.mp3"
                if data is None and not tmp.exists():
                    self._ffmpeg.convert(src, tmp)
                if data is None and tmp.exists():
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
        return FFmpegEngine.cache_key(
            {
                "render_version": self._RENDER_VERSION,
                "project": payload,
                "stats": stats,
                "format": fmt,
            }
        )

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
