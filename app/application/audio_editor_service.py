"""轻量音频编辑器服务。"""

from __future__ import annotations

import copy
import json
import re
import shutil
import threading
import wave
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import config
from domain import EditorClip, EditorProject, EditorTrack, InferenceParams, ModelInfo
from domain.identity import new_id
from domain.audio_editor_rules import (
    clean_effects,
    clean_project,
    clean_volume_envelope,
    clip_stretch,
    find_clip,
    find_clip_ref,
    find_effect,
    is_plugin_effect,
    normalize_format,
    project_duration,
    should_render_waveform,
)
from domain.lyrics import (
    auto_time_lyric_lines,
    parse_lyric_lines,
    parse_plain_lyric_lines,
    speech_ranges_from_silence,
)
from domain.vocal_enhancement import VocalEnhancementControls

from .adapters import (
    audio_engine as create_audio_engine,
    audio_files_from_clipboard,
    copy_file_to_clipboard,
    editor_project_store as create_editor_project_store,
    ffmpeg_cache_key,
    plugin_host as create_plugin_host,
    pymss_tool as create_pymss_tool,
    vocal_enhancement as create_vocal_enhancement,
)
from .editor_render_service import RENDER_VERSION, EditorRenderService
from .ports import (
    AudioEnginePort,
    EditorProjectStorePort,
    EngineRegistryPort,
    FfmpegGateway,
    ItemRepository,
    PluginHostPort,
    PymssGateway,
    SeparationGateway,
    VocalEnhancementPort,
)
from .model_service import ModelService


def _bundle_path(root: Path, arcname: str) -> Path:
    """工程包成员名（posix 相对路径）→ 本地路径。"""
    return root.joinpath(*PurePosixPath(arcname).parts)


class AudioEditorService:
    """Timeline Project 的应用层服务。"""

    _HISTORY_LIMIT = 60
    _MIN_RERUN_DURATION = 1.0
    _RENDER_VERSION = RENDER_VERSION
    _HIGH_PITCH_THRESHOLD = 800.0
    _HIGH_PITCH_GUARD_SEMITONES = 7
    _PROJECT_BUNDLE_SCHEMA = "xb-audio-editor-project"
    _PROJECT_BUNDLE_VERSION = 1
    _PROJECT_BUNDLE_MAX_FILES = 4096
    _PROJECT_BUNDLE_MAX_BYTES = 64 * 1024 * 1024 * 1024
    _PROJECT_BUNDLE_MAX_MANIFEST_BYTES = 16 * 1024 * 1024

    def __init__(
        self,
        repo: ItemRepository,
        works_repo: ItemRepository,
        models: ModelService,
        ffmpeg: FfmpegGateway,
        uvr: SeparationGateway,
        engines: EngineRegistryPort,
        vocal_enhancement: VocalEnhancementPort | None = None,
        pymss: PymssGateway | None = None,
        audio: AudioEnginePort | None = None,
        plugin_host: PluginHostPort | None = None,
        store: EditorProjectStorePort | None = None,
    ) -> None:
        self._repo = repo
        self._works_repo = works_repo
        self._models = models
        self._ffmpeg = ffmpeg
        self._uvr = uvr
        self._pymss = pymss or create_pymss_tool()
        self._store = store if store is not None else create_editor_project_store()
        self._plugin_host = plugin_host or create_plugin_host()
        self._plugin_sessions: dict[str, dict[str, Any]] = {}
        self._engines = engines
        self._vocal_enhancement = vocal_enhancement or create_vocal_enhancement()
        self._rerun_jobs: dict[str, dict[str, Any]] = {}
        self._rerun_jobs_lock = threading.RLock()
        self._render = EditorRenderService(
            repo=repo,
            audio=audio or create_audio_engine(ffmpeg),
            ffmpeg=ffmpeg,
            store=self._store,
            save=self.save,
        )

    # ---- 端口与协作对象 ----

    @property
    def _store(self) -> EditorProjectStorePort:
        """编辑器工程的文件访问端口（未注入时回落到默认适配器）。"""
        store = self.__dict__.get("_editor_store")
        if store is None:
            store = create_editor_project_store()
            self.__dict__["_editor_store"] = store
        return store

    @_store.setter
    def _store(self, store: EditorProjectStorePort) -> None:
        self.__dict__["_editor_store"] = store

    @property
    def _render(self) -> EditorRenderService:
        """渲染/波形用例（懒创建，兼容不经 ``__init__`` 直接装配的调用方）。"""
        service = self.__dict__.get("_render_service")
        if service is None:
            service = EditorRenderService(
                repo=self._repo,
                audio=None,
                ffmpeg=self._ffmpeg,
                store=self._store,
                save=self.save,
            )
            self.__dict__["_render_service"] = service
        return service

    @_render.setter
    def _render(self, service: EditorRenderService) -> None:
        self.__dict__["_render_service"] = service

    @property
    def _audio(self) -> AudioEnginePort:
        """时间线渲染引擎：读写都落在渲染子服务上，既有装配点保持不变。"""
        return self._render._audio

    @_audio.setter
    def _audio(self, engine: AudioEnginePort) -> None:
        self._render._audio = engine

    @property
    def _compute_waveform(self) -> Callable[..., list[float]]:
        """波形采样实现（渲染子服务）；保留可替换入口以兼容既有调用方。"""
        return self._render._compute_waveform

    @_compute_waveform.setter
    def _compute_waveform(self, compute: Callable[..., list[float]]) -> None:
        self._render._compute_waveform = compute

    def _editor_root(self) -> Path:
        """编辑器工程根目录（与 ``project_dir`` 同源）。"""
        return self._store.project_dir("")

    def _cache_root(self) -> Path:
        """编辑器缓存根目录（与 ``cache_path`` 同源）。"""
        return self._store.cache_path("")

    def list(self) -> list[dict[str, Any]]:
        self._cleanup_orphan_project_dirs()
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
        project = self._repo.get(project_id)
        if not project:
            return False

        stored_id = str(project.get("id") or "")
        if not stored_id or stored_id != project_id:
            return False
        try:
            base = self._editor_root().resolve()
            cache_root = self._cache_root().resolve()
            project_path = self._project_dir(stored_id)
            target = project_path.resolve()
        except (OSError, RuntimeError):
            return False

        if (
            Path(stored_id).name != stored_id
            or stored_id in {".", ".."}
            or target.parent != base
            or target.name != stored_id
            or target == cache_root
        ):
            return False

        try:
            if project_path.exists():
                if project_path.is_symlink() or not project_path.is_dir():
                    return False
                shutil.rmtree(project_path)

            if cache_root.exists():
                cache_prefix = f"{stored_id}_"
                for candidate in cache_root.iterdir():
                    if not candidate.name.startswith(cache_prefix):
                        continue
                    if candidate.is_symlink():
                        candidate.unlink()
                        continue
                    resolved = candidate.resolve()
                    if resolved.parent != cache_root:
                        return False
                    if candidate.is_dir():
                        shutil.rmtree(candidate)
                    elif candidate.is_file():
                        candidate.unlink()
                    else:
                        return False
        except (OSError, RuntimeError):
            # 保留工程记录，用户下次仍可重试清理。
            return False

        try:
            self._repo.remove(stored_id)
        except OSError:
            return False
        self._cleanup_editor_cache_after_remove()
        return True

    def _cleanup_orphan_project_dirs(self) -> None:
        """清理数据库中已不存在的编辑工程目录，避免历史删除失败留下文件。"""
        try:
            base = self._editor_root().resolve()
            known = {str(item.get("id") or "") for item in self._repo.all()}
            if not base.exists():
                return
            for candidate in base.iterdir():
                if (
                    not candidate.is_dir()
                    or candidate.name == self._cache_root().name
                    or not candidate.name.startswith("edt_")
                    or candidate.name in known
                ):
                    continue
                resolved = candidate.resolve()
                if resolved.parent == base and resolved.name == candidate.name:
                    shutil.rmtree(candidate, ignore_errors=True)
        except (OSError, RuntimeError):
            return

    def _cleanup_editor_cache_after_remove(self) -> None:
        """删除无工程所有者的编辑器缓存；最后一个工程删除时清空整个缓存目录。"""
        try:
            cache_root = self._cache_root().resolve()
            if not cache_root.exists():
                return
            remaining = {str(item.get("id") or "") for item in self._repo.all()}
            for candidate in list(cache_root.iterdir()):
                # 带工程 ID 的渲染缓存可以在删除对应工程时安全识别。
                if any(candidate.name.startswith(f"{project_id}_") for project_id in remaining if project_id):
                    continue
                if remaining and not candidate.name.startswith("edt_"):
                    continue
                if not remaining and not candidate.name.startswith(
                    ("aud_", "wf_", "fx_", "plugin_", "juce_", "edt_")
                ):
                    continue
                resolved = candidate.resolve()
                if resolved.parent != cache_root:
                    continue
                if candidate.is_symlink() or candidate.is_file():
                    candidate.unlink()
                elif candidate.is_dir():
                    shutil.rmtree(candidate)
        except (OSError, RuntimeError):
            return

    def create_from_audio(self, path: str, title: str | None = None) -> dict[str, Any] | None:
        src = Path(path) if path else None
        if src is None or not src.exists():
            return None
        pid = new_id("edt_")
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
        sample_rate = self._detect_sample_rate(dst)
        now = self._now()
        clip = EditorClip(
            id=new_id("clp_"),
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
            id=new_id("trk_"),
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
            sample_rate=sample_rate,
            metadata={"source_path": str(src), "mode": "manual"},
            created_at=now,
            updated_at=now,
        ).to_dict()
        self._repo.add({**project, "history": [], "future": []})
        return self._public(project)

    @staticmethod
    def _detect_sample_rate(path: Path) -> int:
        """Keep the source rate for WAV imports; compressed sources use the project default."""
        try:
            with wave.open(str(path), "rb") as stream:
                rate = int(stream.getframerate() or 0)
                if rate >= 8000:
                    return rate
        except (OSError, EOFError, wave.Error):
            pass
        return 44100

    def export_bundle(self, project_id: str, destination: Path) -> Path:
        """Write a portable editor project containing its timeline and referenced media."""
        stored = self._repo.get(project_id)
        if not stored:
            raise ValueError("工程不存在")

        project = self._clean(self._public(stored) or {})
        project["waveform_cache"] = {}
        sources: dict[str, tuple[Path, str]] = {}
        for track in project.get("tracks", []) or []:
            for clip in track.get("clips", []) or []:
                source = Path(str(clip.get("file") or ""))
                if not source.is_file():
                    name = str(clip.get("name") or source.name or "未知片段")
                    raise ValueError(f"工程素材不存在：{name}")
                try:
                    source_key = str(source.resolve()).casefold()
                except OSError:
                    source_key = str(source.absolute()).casefold()
                bundled = sources.get(source_key)
                if bundled is None:
                    safe_name = re.sub(r'[^\w.()\-\u4e00-\u9fff]+', "_", source.name).strip("._")
                    safe_name = safe_name[:120] or f"audio{source.suffix.lower() or '.wav'}"
                    member = f"media/{len(sources) + 1:04d}_{safe_name}"
                    bundled = (source, member)
                    sources[source_key] = bundled
                clip["file"] = bundled[1]

        manifest = {
            "schema": self._PROJECT_BUNDLE_SCHEMA,
            "version": self._PROJECT_BUNDLE_VERSION,
            "exported_at": self._now(),
            "project": project,
        }
        # 工程描述先落成临时文件，再和素材一起交给文件访问适配层打包。
        manifest_path = destination.with_name(destination.name + ".manifest.tmp")
        if not self._store.write_bytes(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        ):
            raise ValueError("工程包写入失败")
        try:
            if not self._store.export_zip(
                [(manifest_path, "project.json"), *sources.values()],
                destination,
            ):
                raise ValueError("工程包写入失败")
        finally:
            self._store.remove(manifest_path)
        return destination

    def import_bundle(self, source: Path) -> dict[str, Any]:
        """Import a portable project into a new isolated editor directory."""
        if not source.is_file():
            raise ValueError("工程文件不存在")

        try:
            with zipfile.ZipFile(source) as archive:
                files = [item for item in archive.infolist() if not item.is_dir()]
                if not files or len(files) > self._PROJECT_BUNDLE_MAX_FILES:
                    raise ValueError("工程包文件数量异常")
                names = [item.filename.replace("\\", "/") for item in files]
                if len(names) != len(set(names)):
                    raise ValueError("工程包包含重复文件")
                total_size = sum(max(0, int(item.file_size)) for item in files)
                if total_size > self._PROJECT_BUNDLE_MAX_BYTES:
                    raise ValueError("工程包内容过大")
                info_by_name = dict(zip(names, files, strict=True))
                manifest_info = info_by_name.get("project.json")
                if not manifest_info or manifest_info.file_size > self._PROJECT_BUNDLE_MAX_MANIFEST_BYTES:
                    raise ValueError("工程包缺少有效的工程描述")
                try:
                    manifest = json.loads(archive.read(manifest_info).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError("工程描述已损坏") from exc
                if not isinstance(manifest, dict) or manifest.get("schema") != self._PROJECT_BUNDLE_SCHEMA:
                    raise ValueError("不是受支持的音频编辑工程")
                if int(manifest.get("version") or 0) != self._PROJECT_BUNDLE_VERSION:
                    raise ValueError("工程文件版本暂不支持")
                raw_project = manifest.get("project")
                if not isinstance(raw_project, dict) or not isinstance(raw_project.get("tracks"), list):
                    raise ValueError("工程结构无效")
                for raw_track in raw_project.get("tracks", []):
                    if not isinstance(raw_track, dict) or not isinstance(raw_track.get("clips", []), list):
                        raise ValueError("工程音轨结构无效")
                    if any(not isinstance(raw_clip, dict) for raw_clip in raw_track.get("clips", [])):
                        raise ValueError("工程片段结构无效")

                project = self._clean(raw_project)
                project_id = new_id("edt_")
                project_dir = self._project_dir(project_id)
                staging_dir = project_dir.with_name(f".{project_id}.importing")
                # 先按工程结构校验素材路径（策略），解包本身交给文件访问适配层。
                members: dict[str, str] = {}
                for track in project.get("tracks", []) or []:
                    track["id"] = new_id("trk_")
                    for clip in track.get("clips", []) or []:
                        member_name = str(clip.get("file") or "").replace("\\", "/")
                        member_path = PurePosixPath(member_name)
                        if (
                            member_path.is_absolute()
                            or ".." in member_path.parts
                            or len(member_path.parts) < 2
                            or member_path.parts[0] != "media"
                            or member_name not in info_by_name
                        ):
                            raise ValueError("工程包包含无效的素材路径")
                        members.setdefault(member_name, member_name)

                if self._store.exists(staging_dir):
                    raise ValueError("工程目录已存在")
                try:
                    extracted = self._store.extract_zip(source, staging_dir)
                    if not extracted:
                        raise ValueError("工程包解压失败")
                    extracted_names = set(extracted)
                    if any(name not in extracted_names for name in members):
                        raise ValueError("工程包包含无效的素材路径")
                    # 只保留工程引用的素材；工程描述等打包元数据不进入工程目录。
                    for name in extracted:
                        if name not in members:
                            self._store.remove(_bundle_path(staging_dir, name))

                    for track in project.get("tracks", []) or []:
                        for clip in track.get("clips", []) or []:
                            member_name = str(clip.get("file") or "").replace("\\", "/")
                            clip["id"] = new_id("clp_")
                            clip["file"] = str(_bundle_path(project_dir, member_name))
                            for effect in clip.get("effects", []) or []:
                                if isinstance(effect, dict):
                                    effect["id"] = new_id("fx_")
                        for effect in track.get("effects", []) or []:
                            if isinstance(effect, dict):
                                effect["id"] = new_id("fx_")

                    for role in project.get("roles", []) or []:
                        if not isinstance(role, dict):
                            continue
                        for effect in role.get("effects", []) or []:
                            if isinstance(effect, dict):
                                effect["id"] = new_id("fx_")

                    now = self._now()
                    metadata = dict(project.get("metadata") or {})
                    metadata.pop("work_id", None)
                    metadata.pop("source_path", None)
                    metadata.update(
                        {
                            "mode": "imported_bundle",
                            "imported_at": now,
                            "bundle_version": self._PROJECT_BUNDLE_VERSION,
                        }
                    )
                    project.update(
                        {
                            "id": project_id,
                            "metadata": metadata,
                            "waveform_cache": {},
                            "created_at": now,
                            "updated_at": now,
                            "duration": self._project_duration(project),
                            "history": [],
                            "future": [],
                        }
                    )
                    staging_dir.replace(project_dir)
                    try:
                        self._repo.add(project)
                    except Exception:
                        shutil.rmtree(project_dir, ignore_errors=True)
                        raise
                except Exception:
                    shutil.rmtree(staging_dir, ignore_errors=True)
                    raise
        except zipfile.BadZipFile as exc:
            raise ValueError("工程文件已损坏或格式不正确") from exc
        return self._public(project) or {}

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
            id=new_id("trk_"),
            name=((name or "").strip() or f"音轨 {len(tracks) + 1}")[:80],
            type=track_kind,
            clips=[],
            effects=[],
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
                id=new_id("trk_"),
                name=f"音轨 {len(tracks) + 1}",
                type="audio",
                clips=[],
            ).to_dict()
            tracks.append(track)

        clip = EditorClip(
            id=new_id("clp_"),
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
        engine = str(opts.get("engine") or "uvr").strip().lower()
        if engine not in {"uvr", "pymss"}:
            engine = "uvr"
        model = str(opts.get("model") or config.UVR_SEP_MODEL)
        pymss_model = str(
            opts.get("pymss_model") or opts.get("model") or config.PYMSS_DEFAULT_MODEL
        ).strip()
        pymss_purpose = str(opts.get("pymss_purpose") or config.PYMSS_PURPOSE_VOCAL).strip().lower()
        if pymss_purpose not in {
            config.PYMSS_PURPOSE_VOCAL,
            config.PYMSS_PURPOSE_DEREVERB,
            config.PYMSS_PURPOSE_HARMONY_LEGACY,
            "generic",
        }:
            pymss_purpose = "generic"
        harmony_enabled = bool(engine == "pymss" and opts.get("harmony_removal_enabled"))
        if pymss_purpose != config.PYMSS_PURPOSE_VOCAL:
            harmony_enabled = False
        harmony_model = str(
            opts.get("harmony_model") or config.PYMSS_DEFAULT_HARMONY_MODEL
        ).strip()
        device = str(opts.get("device") or "auto")
        mute_source = opts.get("mute_source", True) is not False
        if engine == "pymss":
            pymss = getattr(self, "_pymss", None) or create_pymss_tool()
            if not pymss.available:
                return {"ok": False, "error": "PyMSS 环境未就绪，请先安装 PyMSS 前置环境"}
            if not config.pymss_model_ready(pymss_model):
                return {"ok": False, "error": f"PyMSS 人声分离模型未下载: {pymss_model}"}
            if harmony_enabled and not config.pymss_model_ready(harmony_model):
                return {"ok": False, "error": f"PyMSS 去混响模型未下载: {harmony_model}"}
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

        try:
            if engine == "pymss":
                pymss = getattr(self, "_pymss", None) or create_pymss_tool()
                sep = pymss.separate(
                    dry,
                    out_dir,
                    pymss_model,
                    device,
                    purpose=pymss_purpose,
                )
            else:
                sep = self._uvr.separate(dry, out_dir, model, device)
        except Exception as exc:  # noqa: BLE001 - 将子进程错误转成编辑器可读提示
            return {"ok": False, "error": str(exc) or "人声分离失败"}
        vocals = Path(sep.vocals)
        instrumental = Path(sep.instrumental) if sep.instrumental else None
        if not vocals.exists():
            return {"ok": False, "error": "人声分离失败"}

        harmony_result = None
        if harmony_enabled:
            try:
                pymss = getattr(self, "_pymss", None) or create_pymss_tool()
                harmony_result = pymss.separate(
                    vocals,
                    out_dir / "harmony",
                    harmony_model,
                    device,
                    purpose=config.PYMSS_PURPOSE_HARMONY_LEGACY,
                )
            except Exception as exc:  # noqa: BLE001 - 可选阶段失败时明确阻止写入半成品
                return {"ok": False, "error": str(exc) or "和声去除失败"}
            harmony_vocals = Path(harmony_result.vocals)
            if not harmony_vocals.exists():
                return {"ok": False, "error": "和声去除未生成有效人声"}
            vocals = harmony_vocals

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
                id=new_id("clp_"),
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
                    "source": f"{engine}_separation",
                    "source_clip_id": clip_id,
                    "source_track_id": track_id,
                    "stem": kind,
                    "separation_engine": engine,
                    "uvr_model": model if engine == "uvr" else "",
                    "pymss_model": pymss_model if engine == "pymss" else "",
                    "pymss_purpose": pymss_purpose if engine == "pymss" else "",
                    "harmony_removal_enabled": harmony_enabled,
                    "harmony_model": harmony_model if harmony_enabled else "",
                    "simulated": bool(sep.simulated),
                },
            ).to_dict()
            return EditorTrack(
                id=new_id("trk_"),
                name=f"{label} - {base_name}"[:80],
                type="vocal" if kind == "vocals" else "bgm",
                clips=[stem_clip],
                locked=False,
                mute=False,
                volume=1.0,
            ).to_dict()

        vocal_label = "人声"
        if engine == "pymss":
            vocal_label += " · PyMSS"
        if harmony_enabled:
            vocal_label += " · 去和声"
        if engine == "pymss" and pymss_purpose == "generic" and sep.stems:
            created_tracks = []
            seen_paths: set[str] = set()
            for stem in sep.stems:
                if not isinstance(stem, dict):
                    continue
                stem_path = Path(str(stem.get("path") or ""))
                if not stem_path.exists():
                    continue
                path_key = str(stem_path.resolve(strict=False)).casefold()
                if path_key in seen_paths:
                    continue
                seen_paths.add(path_key)
                stem_name = str(stem.get("name") or "分离音轨").strip()[:48]
                kind = stem_name.casefold().replace(" ", "_") or "stem"
                created_tracks.append(make_track(kind, f"{stem_name} · PyMSS", stem_path))
            if not created_tracks:
                created_tracks = [make_track("stem", "分离音轨 · PyMSS", vocals)]
        else:
            created_tracks = [make_track("vocals", vocal_label, vocals)]
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
            "engine": engine,
            "harmony_removed": bool(harmony_result),
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
        lines = self._parse_lyric_lines(lyrics)
        timing = "timestamp"
        if not lines:
            plain_lines = self._parse_plain_lyric_lines(lyrics)
            if len(plain_lines) < 2:
                return {"ok": False, "error": "TXT 至少需要两句有效歌词才能自动切句"}
            silence_points: list[float] = []
            src = Path(str(clip.get("file") or ""))
            if (
                opts.get("auto_silence", True) is not False
                and src.exists()
                and self._ffmpeg.available
            ):
                noise_db = min(-1.0, max(-90.0, opt_float("threshold_db", -40.0)))
                min_silence = max(0.1, min(5.0, opt_float("min_silence", 0.3)))
                silences = self._ffmpeg.detect_silences(
                    src,
                    start=offset,
                    end=offset + duration,
                    noise_db=noise_db,
                    min_duration=min_silence,
                )
                silence_points = [
                    (float(item.get("start") or 0.0) + float(item.get("end") or 0.0))
                    / 2.0
                    for item in silences
                    if float(item.get("end") or 0.0) > float(item.get("start") or 0.0)
                ]
            lines = self._auto_time_lyric_lines(
                plain_lines,
                duration,
                silence_points,
                min_clip,
            )
            time_mode = "clip"
            timing = "auto"
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
            item["id"] = str(original.get("id")) if i == 0 else new_id("clp_")
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
                    "lyric_timing": timing,
                }
            )
            item["metadata"] = meta
            new_clips.append(item)

        clips = list(next_track.get("clips") or [])
        clips[next_idx : next_idx + 1] = new_clips
        next_track["clips"] = sorted(clips, key=lambda c: float(c.get("start") or 0.0))
        next_project["waveform_cache"] = {}
        saved = self.save(next_project, push_history=True)
        return {
            "ok": True,
            "project": saved,
            "clips": new_clips,
            "lines": lines,
            "timing": timing,
        }

    @staticmethod
    def _project_has_workflow_tracks(project: dict[str, Any], work: dict[str, Any]) -> bool:
        """判断已有工程是否已包含全部工作流保存音轨。"""
        files: set[str] = set()
        for item in work.get("workflow_outputs") or []:
            if not isinstance(item, dict):
                continue
            raw = str(item.get("path") or "").strip()
            if not raw:
                continue
            try:
                files.add(str(Path(raw).resolve()))
            except OSError:
                continue
        if not files:
            return True
        present: set[str] = set()
        for track in project.get("tracks") or []:
            for clip in track.get("clips") or []:
                raw = str((clip or {}).get("file") or "").strip()
                if not raw:
                    continue
                try:
                    present.add(str(Path(raw).resolve()))
                except OSError:
                    continue
        return files.issubset(present)

    def create_from_work(self, work_id: str) -> dict[str, Any] | None:
        work = self._works_repo.get(work_id)
        if not work:
            return None
        existing = [
            item
            for item in self._repo.all()
            if str((item.get("metadata") or {}).get("work_id") or "") == work_id
            and str((item.get("metadata") or {}).get("mode") or "") == "from_work"
            and item.get("tracks")
        ]
        if existing:
            latest = max(existing, key=lambda item: str(item.get("updated_at") or ""))
            if work.get("mode") != "workflow" or self._project_has_workflow_tracks(
                latest, work
            ):
                return self._public(latest)
            # 旧工程缺少工作流保存音轨时，重新创建一个包含全部音轨的工程。
        pid = new_id("edt_")
        now = self._now()
        tracks: list[dict[str, Any]] = []
        known: set[str] = set()
        workflow = str(work.get("workflow") or "auto_mix")
        vocal_export = workflow == "manual_vocal_merge"

        def stored_duration(value: Any) -> float:
            if isinstance(value, (int, float)):
                return max(0.0, float(value))
            text = str(value or "").strip()
            if not text or text == "—":
                return 0.0
            try:
                parts = [float(part) for part in text.split(":")]
            except (TypeError, ValueError):
                return 0.0
            if len(parts) == 2:
                return max(0.0, parts[0] * 60.0 + parts[1])
            if len(parts) == 3:
                return max(0.0, parts[0] * 3600.0 + parts[1] * 60.0 + parts[2])
            return max(0.0, parts[0]) if len(parts) == 1 else 0.0

        duration_hint = stored_duration(work.get("duration"))
        source_path = Path(str(work.get("source_path") or ""))
        if duration_hint <= 0.0 and source_path.is_file():
            duration_hint = float(self._ffmpeg.probe_duration(source_path) or 0.0)

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
            dur = duration_hint or float(self._ffmpeg.probe_duration(src) or 0.0)
            known.add(resolved)
            tracks.append(
                EditorTrack(
                    id=new_id("trk_"),
                    name=name,
                    type=kind,
                    clips=[
                        EditorClip(
                            id=new_id("clp_"),
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
                            id=new_id("clp_"),
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
                            id=new_id("trk_"),
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
                            id=new_id("clp_"),
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
                        id=new_id("trk_"),
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
        elif work.get("mode") == "workflow":
            # 自定义工作流：成品进入「翻唱成品」轨，其余保存音轨自动按角色导入到对应音轨。
            port_kind = {"vocals": "vocal", "instrumental": "bgm", "audio": "ai", "other": "ai"}
            port_name = {"vocals": "人声", "instrumental": "伴奏", "audio": "音频", "other": "其他音轨"}
            workflow_outputs = [
                item for item in (work.get("workflow_outputs") or []) if isinstance(item, dict)
            ]
            primary_item = next(
                (item for item in workflow_outputs if item.get("primary")), None
            )
            cover_path = (primary_item or {}).get("path") or ai_merged or work.get("output_path")
            add_track("翻唱成品", "ai", cover_path)
            for item in workflow_outputs:
                if item.get("primary"):
                    continue
                port = str(item.get("port") or "")
                label = str(item.get("label") or "").strip()
                fallback_name = port_name.get(port)
                if not fallback_name and port.startswith("stem:"):
                    fallback_name = f"音轨 {port.split(':', 1)[1]}"
                track_name = f"素材 · {label}" if label else f"素材 · {fallback_name or '音频'}"
                add_track(
                    track_name,
                    port_kind.get(port, "ai"),
                    item.get("path"),
                    metadata={
                        "work_id": work_id,
                        "stem": "workflow_output",
                        "port": port,
                        "primary": False,
                    },
                )
        else:
            add_track("AI 翻唱干声", "ai", ai_merged or (ai_paths[0] if ai_paths else None))

        # 成品音轨已加入后，再标记整轨成品路径，避免「中间片段」重复导入。
        remember(work.get("output_path"))

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
                dur = (
                    float(self._ffmpeg.probe_duration(p) or 0.0)
                    if p.name.startswith("piece_")
                    else duration_hint or float(self._ffmpeg.probe_duration(p) or 0.0)
                )
                mid_clips.append(
                    EditorClip(
                        id=new_id("clp_"),
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
                    id=new_id("trk_"),
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
                # 保留翻唱任务的前期处理配置，编辑器后续分离/重做时继续使用同一套设置。
                "preprocess": copy.deepcopy(work.get("preprocess") or {}),
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
        # WebView playback only needs a compact transport format. Keep lossless
        # WAV/FLAC available for copy/export, but avoid pushing large FLAC
        # payloads through the pywebview bridge for every clip audition.
        dst = self._render_clip_file(project_id, clip_id, "mp3", cache=True)
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

    def merge_clips(
        self,
        project_id: str,
        track_id: str,
        clip_ids: list[str] | None,
    ) -> dict[str, Any]:
        project = self._repo.get(project_id)
        if not project:
            return {"ok": False, "error": "工程不存在"}
        track = next(
            (item for item in project.get("tracks", []) or [] if item.get("id") == track_id),
            None,
        )
        if not track:
            return {"ok": False, "error": "音轨不存在"}
        if track.get("locked"):
            return {"ok": False, "error": "音轨已锁定，不能合并"}
        if not self._audio.available:
            return {"ok": False, "error": "未找到 ffmpeg，无法合并音频"}

        requested = [str(value or "") for value in (clip_ids or []) if str(value or "")]
        requested = list(dict.fromkeys(requested))
        if len(requested) < 2:
            return {"ok": False, "error": "至少选择两个片段才能合并"}
        requested_set = set(requested)
        timeline = sorted(
            list(track.get("clips") or []),
            key=lambda item: (float(item.get("start") or 0.0), str(item.get("id") or "")),
        )
        selected = [item for item in timeline if str(item.get("id") or "") in requested_set]
        if len(selected) != len(requested):
            return {"ok": False, "error": "待合并片段不存在或不在同一音轨"}
        selected_indexes = [timeline.index(item) for item in selected]
        if selected_indexes != list(range(selected_indexes[0], selected_indexes[-1] + 1)):
            return {"ok": False, "error": "只能合并时间线上连续的片段"}
        if any(item.get("locked") for item in selected):
            return {"ok": False, "error": "锁定片段不能合并"}
        if any(not Path(str(item.get("file") or "")).exists() for item in selected):
            return {"ok": False, "error": "待合并片段的音频文件不存在"}

        try:
            merge_start = min(float(item.get("start") or 0.0) for item in selected)
            merge_end = max(float(item.get("end") or 0.0) for item in selected)
        except (TypeError, ValueError):
            return {"ok": False, "error": "片段时间无效"}
        duration = merge_end - merge_start
        if duration < 0.05:
            return {"ok": False, "error": "待合并片段太短"}

        rendered_clips: list[dict[str, Any]] = []
        for item in selected:
            rendered = copy.deepcopy(item)
            rendered["start"] = round(float(item.get("start") or 0.0) - merge_start, 3)
            rendered["end"] = round(float(item.get("end") or 0.0) - merge_start, 3)
            rendered_clips.append(rendered)
        render_project = {
            "id": project_id,
            "duration": round(duration, 3),
            "sample_rate": int(project.get("sample_rate") or 44100),
            "tracks": [
                {
                    "id": track_id,
                    "name": str(track.get("name") or ""),
                    "type": str(track.get("type") or "audio"),
                    # Track gain remains on the destination track, so it must not be baked twice.
                    "volume": 1.0,
                    "mute": False,
                    "clips": rendered_clips,
                }
            ],
        }
        media_dir = self._project_dir(project_id) / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        base_name = " + ".join(str(item.get("name") or "片段") for item in selected)
        dst = self._unique_path(media_dir / f"{self._safe_stem(base_name)}_merged.wav")
        cache_dir = self._project_dir(project_id) / "cache"
        if not self._audio.render_timeline(render_project, dst, cache_dir, "wav"):
            return {"ok": False, "error": "音频合并渲染失败"}

        source_metadata = [
            {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "file": str(item.get("file") or ""),
                "start": float(item.get("start") or 0.0),
                "end": float(item.get("end") or 0.0),
            }
            for item in selected
        ]
        role_ids = [
            str((item.get("metadata") or {}).get("role_id") or "") for item in selected
        ]
        metadata = dict(selected[0].get("metadata") or {})
        if not role_ids[0] or any(role_id != role_ids[0] for role_id in role_ids[1:]):
            metadata.pop("role_id", None)
        metadata.update(
            {
                "source": "editor_merge",
                "merged_at": self._now(),
                "merged_clip_ids": requested,
                "merged_sources": source_metadata,
            }
        )
        merged_clip = EditorClip(
            id=new_id("clp_"),
            name=(base_name or "合并片段")[:80],
            start=round(merge_start, 3),
            end=round(merge_end, 3),
            offset=0.0,
            volume=1.0,
            mute=False,
            file=str(dst),
            effects=[],
            locked=False,
            fade_in=0.0,
            fade_out=0.0,
            channel="stereo",
            volume_envelope=[],
            metadata=metadata,
        ).to_dict()

        next_project = copy.deepcopy(project)
        next_track = next(
            (item for item in next_project.get("tracks", []) or [] if item.get("id") == track_id),
            None,
        )
        if not next_track:
            return {"ok": False, "error": "合并结果写入失败"}
        remaining = [
            item
            for item in next_track.get("clips", []) or []
            if str(item.get("id") or "") not in requested_set
        ]
        remaining.append(merged_clip)
        next_track["clips"] = sorted(
            remaining,
            key=lambda item: (float(item.get("start") or 0.0), str(item.get("id") or "")),
        )
        next_project["waveform_cache"] = {}
        saved = self.save(next_project, push_history=True)
        return {
            "ok": True,
            "project": saved,
            "clip": merged_clip,
            "merged_clip_ids": requested,
            "path": str(dst),
        }

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
        effect_scope: str = "clip",
        role_id: str = "",
    ) -> dict[str, Any]:
        project = self._repo.get(project_id)
        if not project:
            return {"ok": False, "error": "工程不存在", **self._plugin_host.status()}
        scope = str(effect_scope or "clip").strip().lower()
        if scope not in {"clip", "track", "role"}:
            scope = "clip"
        track = next(
            (item for item in project.get("tracks", []) or [] if item.get("id") == track_id),
            None,
        )
        clip = None
        target = None
        if scope == "role":
            target = next(
                (item for item in project.get("roles", []) or [] if item.get("id") == role_id),
                None,
            )
        elif scope == "track":
            target = track
        else:
            track, _, clip = self._find_clip_ref(project, track_id, clip_id)
            target = clip
        if not target or (scope != "role" and not track):
            label = "角色" if scope == "role" else "音轨" if scope == "track" else "片段"
            return {"ok": False, "error": f"{label}不存在", **self._plugin_host.status()}
        effect = self._find_effect(target, effect_id)
        if not effect:
            return {"ok": False, "error": "效果器不存在", **self._plugin_host.status()}
        if scope == "clip":
            if not isinstance(track, dict) or not isinstance(clip, dict):
                return {
                    "ok": False,
                    "error": "片段不存在",
                    **self._plugin_host.status(),
                }
            monitor = self._prepare_plugin_monitor(project, track, clip, effect_id)
        else:
            monitor = {}
        result = self._plugin_host.show_editor(
            effect,
            project_id=project_id,
            clip_id=clip_id if scope == "clip" else f"{scope}:{role_id or track_id}",
            effect_id=effect_id,
            parent_window=parent_window,
            monitor=monitor,
        )
        session_id = str(result.get("session_id") or "")
        if result.get("ok") and session_id:
            self._plugin_sessions[session_id] = {
                "project_id": project_id,
                "track_id": track_id,
                "clip_id": clip_id,
                "effect_id": effect_id,
                "effect_scope": scope,
                "role_id": role_id,
                "timeline_start": monitor.get("timeline_start", 0.0),
                "timeline_end": monitor.get("timeline_end", 0.0),
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

    def sync_effect_plugin_editor(
        self,
        session_id: str,
        transport: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ref = self._plugin_sessions.get(session_id or "")
        monitor_transport = dict(transport) if isinstance(transport, dict) else {}
        if ref:
            if ref.get("effect_scope", "clip") == "clip":
                if "timeline_start" not in ref or "timeline_end" not in ref:
                    current = self._repo.get(ref.get("project_id", ""))
                    _, _, clip = self._find_clip_ref(
                        current or {}, ref.get("track_id", ""), ref.get("clip_id", "")
                    )
                    if clip:
                        ref["timeline_start"] = float(clip.get("start") or 0.0)
                        ref["timeline_end"] = float(clip.get("end") or 0.0)
                monitor_transport["timeline_start"] = float(ref.get("timeline_start") or 0.0)
                monitor_transport["timeline_end"] = float(ref.get("timeline_end") or 0.0)
                monitor_transport["audible"] = (
                    monitor_transport.get("audible", True) is not False
                )
        result = self._plugin_host.sync_editor(session_id, monitor_transport)
        plugin_state = result.get("plugin")
        persistable_state = isinstance(plugin_state, dict) and (
            bool(plugin_state.get("state"))
            or isinstance(plugin_state.get("parameter_values"), dict)
        )
        if result.get("ok") and ref and persistable_state:
            project = self._apply_plugin_state(ref, plugin_state)
            if project:
                result["project"] = project
        if result.get("closed"):
            self._plugin_sessions.pop(session_id or "", None)
        return result

    def _prepare_plugin_monitor(
        self,
        project: dict[str, Any],
        track: dict[str, Any],
        clip: dict[str, Any],
        effect_id: str,
    ) -> dict[str, Any]:
        src = Path(str(clip.get("file") or ""))
        if not src.is_file() or not self._audio.available:
            return {}
        try:
            start = max(0.0, float(clip.get("start") or 0.0))
            end = max(start, float(clip.get("end") or start))
        except (TypeError, ValueError):
            return {}
        if end - start < 0.01:
            return {}
        effects = [item for item in (clip.get("effects") or []) if isinstance(item, dict)]
        target_index = next(
            (idx for idx, item in enumerate(effects) if str(item.get("id") or "") == effect_id),
            -1,
        )
        if target_index < 0:
            return {}
        prefix = copy.deepcopy(effects[:target_index])
        sample_rate = int(project.get("sample_rate") or 44100)
        try:
            stat = src.stat()
            source_signature = (str(src.resolve()), stat.st_size, int(stat.st_mtime_ns))
        except OSError:
            source_signature = (str(src), 0, 0)
        key = ffmpeg_cache_key(
            {
                "version": "plugin-monitor-v1",
                "source": source_signature,
                "offset": clip.get("offset"),
                "start": clip.get("start"),
                "end": clip.get("end"),
                "channel": clip.get("channel"),
                "prefix_effects": prefix,
                "sample_rate": sample_rate,
            }
        )
        raw_dst = self._store.cache_path(f"plugin_monitor_raw_{key}.wav")
        if not raw_dst.exists() and not self._audio.render_plugin_monitor_input(
            src,
            clip,
            prefix,
            raw_dst,
            self._cache_root(),
            sample_rate,
        ):
            return {}

        # Bake timeline-level gain, envelope and fades into the target signal. The
        # selected VST3 itself remains unrendered and is processed by JUCE on the
        # sound-card callback, so its GUI changes are audible on the next block.
        length = end - start
        target_project = {
            "sample_rate": sample_rate,
            "duration": length,
            "tracks": [
                {
                    "id": "realtime-target-track",
                    "volume": track.get("volume", 1.0),
                    "mute": track.get("mute", False),
                    "clips": [
                        {
                            **copy.deepcopy(clip),
                            "id": "realtime-target-clip",
                            "file": str(raw_dst),
                            "start": 0.0,
                            "end": length,
                            "offset": 0.0,
                            "channel": "stereo",
                            "effects": [],
                        }
                    ],
                }
            ],
        }
        target_key = ffmpeg_cache_key(
            {
                "version": "plugin-realtime-target-v1",
                "monitor": key,
                "track_volume": track.get("volume"),
                "clip_volume": clip.get("volume"),
                "clip_mute": clip.get("mute"),
                "track_mute": track.get("mute"),
                "fade_in": clip.get("fade_in"),
                "fade_out": clip.get("fade_out"),
                "volume_envelope": clip.get("volume_envelope"),
            }
        )
        target_dst = self._store.cache_path(f"plugin_target_{target_key}.wav")
        render_timeline = getattr(self._audio, "render_timeline", None)
        if callable(render_timeline) and not target_dst.exists():
            render_timeline(
                target_project,
                target_dst,
                self._cache_root(),
                "wav",
            )
        if not target_dst.exists():
            target_dst = raw_dst

        bed_project = copy.deepcopy(project)
        for bed_track in bed_project.get("tracks", []) or []:
            bed_track["clips"] = [
                item
                for item in (bed_track.get("clips") or [])
                if str(item.get("id") or "") != str(clip.get("id") or "")
            ]
        bed_key = ffmpeg_cache_key(
            {
                "version": "plugin-realtime-bed-v2",
                "project": bed_project,
                "target_clip": clip.get("id"),
            }
        )
        bed_dst = self._store.cache_path(f"plugin_bed_{bed_key}.wav")
        if callable(render_timeline) and not bed_dst.exists():
            render_timeline(
                bed_project,
                bed_dst,
                self._cache_root(),
                "wav",
            )
        return {
            "input": str(target_dst),
            "bed_input": str(bed_dst) if bed_dst.exists() else "",
            "timeline_start": start,
            "timeline_end": end,
            "project_duration": max(0.05, float(project.get("duration") or end)),
            "sample_rate": sample_rate,
            "block_size": 128,
        }

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
        scope = ref.get("effect_scope", "clip")
        target = None
        if scope == "role":
            target = next(
                (item for item in project.get("roles", []) or [] if item.get("id") == ref.get("role_id", "")),
                None,
            )
        elif scope == "track":
            target = next(
                (item for item in project.get("tracks", []) or [] if item.get("id") == ref.get("track_id", "")),
                None,
            )
        else:
            _, _, target = self._find_clip_ref(
                project,
                ref.get("track_id", ""),
                ref.get("clip_id", ""),
            )
        if not target:
            return None
        effect = self._find_effect(target, ref.get("effect_id", ""))
        if not effect:
            return None

        previous_params = dict(effect.get("params") or {})
        params = dict(previous_params)
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
        if params == previous_params:
            return None
        effect["params"] = params
        project["updated_at"] = self._now()
        project["duration"] = self._project_duration(project)
        self._repo.update(str(project.get("id") or ""), project)
        return self._public(project)

    # ---- 渲染与波形（实现见 application/editor_render_service.py） ----

    def render_preview(self, project_id: str) -> str:
        return self._render.render_preview(project_id)

    def render(self, project_id: str, output_format: str = "wav") -> Path | None:
        return self._render.render(project_id, output_format)

    def render_track(
        self, project_id: str, track_id: str, output_format: str = "wav"
    ) -> Path | None:
        """把单条音轨（含该轨效果与片段）渲染成一个音频文件，用于导出单轨。"""
        return self._render.render_track(project_id, track_id, output_format)

    def render_clip(
        self,
        project_id: str,
        clip_id: str,
        output_format: str = "wav",
        *,
        cache: bool = False,
    ) -> Path | None:
        """把单个片段渲染成音频文件，用于导出与 HTTP 下载。"""
        return self._render.render_clip(project_id, clip_id, output_format, cache=cache)

    def _render_clip_file(
        self,
        project_id: str,
        clip_id: str,
        fmt: str = "wav",
        cache: bool = False,
    ) -> Path | None:
        return self._render._render_clip_file(project_id, clip_id, fmt, cache=cache)

    def _render_track_file(
        self,
        project_id: str,
        track_id: str,
        fmt: str = "wav",
    ) -> Path | None:
        return self._render._render_track_file(project_id, track_id, fmt)

    def _render_key(self, project: dict[str, Any], fmt: str) -> str:
        return self._render._render_key(project, fmt)

    def waveform(self, project_id: str, clip_id: str, bins: int = 160) -> dict[str, Any]:
        return self._render.waveform(project_id, clip_id, bins)

    def preload_waveforms(self, project_id: str, bins: int = 160) -> bool:
        return self._render.preload_waveforms(project_id, bins)

    def _waveform_key(
        self,
        clip: dict[str, Any],
        bins: int,
        source: Path | None = None,
    ) -> str:
        return self._render._waveform_key(clip, bins, source)

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
                item["id"] = str(original.get("id")) if i == 0 else new_id("clp_")
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
            item["id"] = str(original.get("id")) if i == 0 else new_id("clp_")
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

    @staticmethod
    def _estimate_peak_f0(source: Path) -> float:
        """Reuse the conversion pipeline's pitch probe without constructing it."""
        try:
            from application.conversion_service import ConversionService

            return float(ConversionService._estimate_peak_f0(source))
        except (ImportError, OSError, ValueError, wave.Error):
            return 0.0

    def _prepare_high_pitch_guard(
        self,
        source: Path,
        destination: Path,
        params: InferenceParams,
        model: dict[str, Any] | None = None,
        only_regions: list[tuple[float, float]] | None = None,
        semitones: int | None = None,
    ) -> tuple[Path, bool]:
        if not params.auto_high_pitch_guard or not source.is_file():
            return source, False
        peak_f0 = self._estimate_peak_f0(source)
        high_threshold = self._model_high_pitch_threshold(params, model)
        if peak_f0 < high_threshold and not only_regions:
            return source, False
        pitch_shift = getattr(self._ffmpeg, "pitch_shift", None)
        if not callable(pitch_shift):
            return source, False
        try:
            kwargs: dict[str, Any] = {
                "mask_source": source,
                "loudness_source": source,
                "high_threshold": high_threshold,
            }
            if only_regions:
                kwargs["regions"] = only_regions
            shift_semitones = int(semitones or self._HIGH_PITCH_GUARD_SEMITONES)
            ok = pitch_shift(source, destination, -shift_semitones, **kwargs)
        except TypeError:
            if only_regions:
                return source, False
            ok = pitch_shift(source, destination, -int(semitones or self._HIGH_PITCH_GUARD_SEMITONES))
        return (destination, True) if ok and destination.is_file() else (source, False)

    def _restore_high_pitch_guard(
        self,
        source: Path,
        destination: Path,
        original: Path,
        params: InferenceParams,
        model: dict[str, Any] | None = None,
        only_regions: list[tuple[float, float]] | None = None,
        semitones: int | None = None,
    ) -> Path:
        if not params.auto_high_pitch_guard:
            return source
        pitch_shift = getattr(self._ffmpeg, "pitch_shift", None)
        if not callable(pitch_shift):
            return source
        try:
            kwargs = {
                "mask_source": original,
                # Restore against the model render's local dynamics. Using the
                # dry vocal can make a breathy retry several dB louder and
                # turn the upper band into a whistle.
                "loudness_source": source,
                "high_threshold": self._model_high_pitch_threshold(params, model),
            }
            if only_regions:
                kwargs["regions"] = only_regions
            shift_semitones = int(semitones or self._HIGH_PITCH_GUARD_SEMITONES)
            ok = pitch_shift(source, destination, shift_semitones, **kwargs)
        except TypeError:
            if only_regions:
                return source
            ok = pitch_shift(source, destination, int(semitones or self._HIGH_PITCH_GUARD_SEMITONES))
        return destination if ok and destination.is_file() else source

    def _infer_with_dropout_recovery(
        self,
        *,
        model: dict[str, Any],
        profile_model: dict[str, Any] | None = None,
        engine: Any,
        source: Path,
        output: Path,
        params: InferenceParams,
        duration: float,
    ) -> tuple[Path, list[dict[str, Any]], bool]:
        """Retry an editor clip only when the converted high note collapses."""
        from application.conversion_service import ConversionService

        profile = profile_model or model
        threshold = self._model_high_pitch_threshold(params, profile)
        params.high_pitch_threshold = threshold
        guard_rounds = ConversionService._high_pitch_guard_rounds(params)
        attempts = 1 + guard_rounds if params.auto_high_pitch_guard else 1
        history: list[dict[str, Any]] = []
        guard_applied_any = False
        rendered = output
        guard_regions: list[tuple[float, float]] | None = None
        merge_regions: list[tuple[float, float]] | None = None
        initial_failure_regions: list[tuple[float, float]] | None = None
        unresolved_failure_regions: list[tuple[float, float]] = []
        guard_semitones = self._HIGH_PITCH_GUARD_SEMITONES
        best_render = output
        best_bad_frames = float("inf")
        for attempt in range(attempts):
            raw_target = output if attempt == 0 else output.with_name(
                f"{output.stem}_dropout_retry{attempt}.wav"
            )
            if attempt == 0:
                guarded, guard_applied = source, False
            else:
                guarded, guard_applied = self._prepare_high_pitch_guard(
                    source,
                    output.with_name(f"{output.stem}_guarded_retry{attempt}.wav"),
                    params,
                    profile,
                    guard_regions,
                    guard_semitones,
                )
            guard_applied_any = guard_applied_any or guard_applied
            engine.infer(model, guarded, raw_target, params, duration)
            rendered = raw_target
            if guard_applied:
                restored = output.with_name(f"{output.stem}_restored_retry{attempt}.wav")
                candidate = self._restore_high_pitch_guard(
                    raw_target,
                    restored,
                    source,
                    params,
                    profile,
                    guard_regions,
                    guard_semitones,
                )
                if candidate != raw_target:
                    rendered = candidate
                    if merge_regions:
                        merged_target = output.with_name(
                            f"{output.stem}_guarded_merged_retry{attempt}.wav"
                        )
                        rendered = ConversionService._merge_guarded_regions(
                            output,
                            rendered,
                            merged_target,
                            restored.with_suffix(".regions.json"),
                            only_regions=merge_regions,
                        )
                else:
                    # Do not publish a model render that is still in the
                    # lowered preparation register when inverse PSOLA fails.
                    rendered = output
            if (
                attempt > 0
                and rendered != output
                and ConversionService._guard_candidate_has_new_hf_peak(
                    source,
                    output,
                    rendered,
                    merge_regions,
                )
            ):
                rendered = output
            issue = (
                ConversionService._detect_model_dropout(
                    source,
                    rendered,
                    threshold,
                    int(getattr(params, "pitch", 0) or 0),
                )
                if params.auto_high_pitch_guard and guard_rounds > 0
                else None
            )
            entry: dict[str, Any] = {
                "attempt": attempt + 1,
                "threshold": round(threshold, 1),
                "issue": issue,
            }
            history.append(entry)
            if attempt == 0:
                if issue is None:
                    return rendered, history, False
                initial_failure_regions = ConversionService._dropout_core_regions(issue)
                unresolved_failure_regions = list(initial_failure_regions or [])
                merge_regions = initial_failure_regions
                guard_regions = ConversionService._confirmed_guard_regions(issue)
                best_bad_frames = float(issue.get("bad_frames") or float("inf"))
                guard_semitones = max(
                    guard_semitones,
                    ConversionService._guard_semitones_for_retry(
                        threshold,
                        issue,
                        source,
                        guard_regions,
                    ),
                )
            else:
                quality = (
                    ConversionService._guard_candidate_high_note_quality(
                        source,
                        output,
                        rendered,
                        initial_failure_regions,
                        restored.with_suffix(".regions.json")
                        if guard_applied
                        else None,
                    )
                    if rendered != output
                    else {"available": False}
                )
                if quality.get("available"):
                    entry["quality"] = quality
                    accepted_keys = {
                        (round(float(start), 6), round(float(end), 6))
                        for start, end in (quality.get("accepted_regions") or [])
                    }
                    newly_accepted = [
                        (start, end)
                        for start, end in unresolved_failure_regions
                        if (round(float(start), 6), round(float(end), 6))
                        in accepted_keys
                    ]
                    if newly_accepted:
                        best_render = ConversionService._merge_guarded_regions(
                            best_render,
                            rendered,
                            output.with_name(
                                f"{output.stem}_accepted_retry{attempt}.wav"
                            ),
                            restored.with_suffix(".regions.json"),
                            only_regions=newly_accepted,
                        )
                        unresolved_failure_regions = [
                            (start, end)
                            for start, end in unresolved_failure_regions
                            if (round(float(start), 6), round(float(end), 6))
                            not in accepted_keys
                        ]
                    issue = ConversionService._quality_failure_issue(
                        {
                            **quality,
                            "failed_regions": unresolved_failure_regions,
                        },
                        issue,
                    )
                    entry["issue"] = issue
                    if issue is None:
                        return best_render, history, bool(best_render != output)
                    best_bad_frames = float(
                        issue.get("bad_frames") or float("inf")
                    )
                    guard_regions = ConversionService._confirmed_guard_regions(issue)
                    merge_regions = initial_failure_regions
                    next_threshold = ConversionService._next_dropout_threshold(
                        threshold,
                        issue,
                    )
                    entry["next_threshold"] = next_threshold
                    if (
                        next_threshold >= threshold - 10.0
                        or attempt >= attempts - 1
                    ):
                        return best_render, history, bool(best_render != output)
                    guard_semitones = max(
                        guard_semitones,
                        ConversionService._guard_semitones_for_retry(
                            next_threshold,
                            issue,
                            source,
                            guard_regions,
                        ),
                    )
                    threshold = next_threshold
                    params.high_pitch_threshold = threshold
                    continue
                if issue is None:
                    return rendered, history, bool(
                        guard_applied_any and rendered != output
                    )
                candidate_bad_frames = float(
                    issue.get("bad_frames") or float("inf")
                )
                candidate_keeps_original_failure = (
                    ConversionService._dropout_regions_overlap(
                        issue,
                        initial_failure_regions,
                    )
                )
                candidate_improved = (
                    candidate_bad_frames < best_bad_frames
                    or (
                        best_render == output
                        and candidate_bad_frames == best_bad_frames
                        and not candidate_keeps_original_failure
                    )
                )
                if (
                    rendered != output
                    and candidate_improved
                    and not candidate_keeps_original_failure
                ):
                    best_render = rendered
                    best_bad_frames = candidate_bad_frames
                if guard_regions and issue.get("bad_regions"):
                    overlaps_scope = any(
                        float(item.get("end", 0.0)) > start
                        and float(item.get("start", 0.0)) < end
                        for item in (issue.get("bad_regions") or [])
                        if isinstance(item, dict)
                        for start, end in guard_regions
                    )
                    if not overlaps_scope:
                        return best_render, history, bool(best_render != output)
                    guard_regions = ConversionService._confirmed_guard_regions(
                        issue,
                        guard_regions,
                    )
            next_threshold = ConversionService._next_dropout_threshold(threshold, issue)
            entry["next_threshold"] = next_threshold
            if next_threshold >= threshold - 10.0 or attempt >= attempts - 1:
                return best_render, history, bool(best_render != output)
            guard_semitones = max(
                guard_semitones,
                ConversionService._guard_semitones_for_retry(
                    next_threshold,
                    issue,
                    source,
                    guard_regions,
                ),
            )
            threshold = next_threshold
            params.high_pitch_threshold = threshold
        return best_render, history, bool(best_render != output)

    @staticmethod
    def _model_high_pitch_threshold(
        params: InferenceParams, model: dict[str, Any] | None = None
    ) -> float:
        explicit = float(getattr(params, "high_pitch_threshold", 0.0) or 0.0)
        if explicit > 0:
            return max(300.0, min(2000.0, explicit))
        if not bool(getattr(params, "manual_params_enabled", False)):
            return AudioEditorService._HIGH_PITCH_THRESHOLD
        model = model or {}
        metadata = model.get("metadata") or model.get("model_metadata") or {}
        profile = metadata.get("inference_profile") if isinstance(metadata, dict) else None
        values = []
        for source in (metadata, profile if isinstance(profile, dict) else {}):
            values.extend([source.get("high_pitch_threshold"), source.get("f0_max_hz"), source.get("f0_max")])
        config_path = str((model.get("main_config") or {}).get("path") or model.get("main_config_path") or "")
        if config_path:
            try:
                raw = Path(config_path).read_text(encoding="utf-8")
                try:
                    parsed = json.loads(raw)
                    def visit(value: Any) -> None:
                        if isinstance(value, dict):
                            for key, child in value.items():
                                if str(key).lower() in {"f0_max", "f0_max_hz", "max_f0"}:
                                    values.append(child)
                                visit(child)
                        elif isinstance(value, list):
                            for child in value:
                                visit(child)
                    visit(parsed)
                except (TypeError, ValueError):
                    for key in ("f0_max", "f0_max_hz", "max_f0"):
                        match = re.search(rf"(?:^|\n)\s*{key}\s*:\s*([0-9]+(?:\.[0-9]+)?)", raw, re.I)
                        if match: values.append(match.group(1))
            except OSError:
                pass
        for value in values:
            try: number = float(value)
            except (TypeError, ValueError): continue
            if 300.0 <= number <= 2000.0: return number
        framework = config.modelhub_normalize_framework(model.get("framework"))
        return {"rvc": 760.0, "seed-vc": 980.0, "ddsp-svc": 1040.0, "so-vits-svc": 1120.0}.get(framework, 1000.0)

    def _execute_rerun_clip(
        self,
        project_id: str,
        track_id: str,
        clip_id: str,
        model_id: str,
        params: dict[str, Any] | None = None,
        enhance: dict[str, Any] | None = None,
        progress: Any = None,
        log: Any = None,
    ) -> dict[str, Any]:
        def report(value: int, message: str) -> None:
            if progress:
                progress(value, message)
            if log:
                log(message)

        report(5, "开始校验片段与模型")
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
        report(12, "正在准备局部音频")
        infer_params = InferenceParams.from_dict(
            ModelService.apply_detected_rvc_version(model, params or {})
        )
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
        report(25, "片段裁剪完成，开始模型推理")
        model_payload = self._model_payload(model)
        engine = self._engines.for_model(model_payload)
        try:
            out, dropout_recovery, guard_applied = self._infer_with_dropout_recovery(
                model=model_payload,
                profile_model=model,
                engine=engine,
                source=dry,
                output=out,
                params=infer_params,
                duration=duration,
            )
        except Exception as exc:  # noqa: BLE001 - 需要把推理错误回传给前端
            return {"ok": False, "error": str(exc)}
        report(70, "模型推理完成")

        # 可选增强：以裁剪出的原始干声保护高级层的辅音、呼吸和宽带平衡。
        enhance_used = False
        enhance_level = ""
        enhance_error = ""
        enhance_cfg = enhance or {}
        if enhance_cfg.get("enabled") and self._vocal_enhancement.available:
            report(74, "正在执行 AI 歌声增强")
            enhance_level = "advanced" if str(enhance_cfg.get("level") or "basic").lower() == "advanced" else "basic"
            pitch_correction = self._vocal_enhancement.normalize_strength(
                enhance_cfg.get("pitch_correction", 0.45), 0.45
            )
            timing_alignment = self._vocal_enhancement.normalize_strength(
                enhance_cfg.get("timing_alignment", 0.45), 0.45
            )
            timbre_focus = self._vocal_enhancement.normalize_strength(
                enhance_cfg.get("timbre_focus", 0.60), 0.60
            )
            ai_eq = self._vocal_enhancement.normalize_strength(
                enhance_cfg.get("ai_eq", 0.55), 0.55
            )
            ai_compressor = self._vocal_enhancement.normalize_strength(
                enhance_cfg.get("ai_compressor", 0.45), 0.45
            )
            ai_exciter = self._vocal_enhancement.normalize_strength(
                enhance_cfg.get("ai_exciter", 0.25), 0.25
            )
            stereo_width = self._vocal_enhancement.normalize_strength(
                enhance_cfg.get("stereo_width", 0.30), 0.30
            )
            loudness_envelope = self._vocal_enhancement.normalize_strength(
                enhance_cfg.get("loudness_envelope", 0.58), 0.58
            )
            if guard_applied:
                # High-note restoration already protects upper harmonics. Keep
                # the optional beauty pass conservative to avoid synthetic sheen.
                timbre_focus *= 0.68
                ai_eq *= 0.78
                ai_compressor *= 0.82
                ai_exciter *= 0.45
            enhanced_out = out_dir / f"{clip_id}_{model_id}_{rerun_key}_enhanced.wav"
            try:
                enhanced_out.unlink(missing_ok=True)
            except OSError:
                enhanced_out = out
            try:
                self._vocal_enhancement.enhance(
                    out,
                    enhanced_out,
                    level=enhance_level,
                    device=str(enhance_cfg.get("device") or "auto"),
                    reference=dry,
                    pitch_correction=pitch_correction,
                    timing_alignment=timing_alignment,
                    timbre_focus=timbre_focus,
                    ai_eq=ai_eq,
                    ai_compressor=ai_compressor,
                    ai_exciter=ai_exciter,
                    stereo_width=stereo_width,
                    loudness_envelope=loudness_envelope,
                    progress_callback=lambda value: report(value, "正在执行 AI 歌声增强"),
                )
                if enhanced_out.is_file():
                    out = enhanced_out
                    enhance_used = True
            except Exception as exc:  # noqa: BLE001 - 美声失败不应阻塞重推理
                enhance_error = str(exc)
            report(88, "AI 歌声增强处理完成")

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
                "rerun_enhanced": enhance_used,
                "rerun_high_pitch_guard": guard_applied,
                "rerun_dropout_recovery": dropout_recovery,
                "rerun_beauty_compensation": guard_applied and enhance_used,
                "rerun_enhance_level": enhance_level if enhance_used else "",
                "rerun_pitch_correction": pitch_correction if enhance_used else 0.0,
                "rerun_timing_alignment": timing_alignment if enhance_used else 0.0,
                "rerun_timbre_focus": timbre_focus if enhance_used else 0.0,
                "rerun_ai_eq": ai_eq if enhance_used else 0.0,
                "rerun_ai_compressor": ai_compressor if enhance_used else 0.0,
                "rerun_ai_exciter": ai_exciter if enhance_used else 0.0,
                "rerun_stereo_width": stereo_width if enhance_used else 0.0,
                "rerun_loudness_envelope": loudness_envelope if enhance_used else 0.0,
            }
        )
        if enhance_error:
            meta["rerun_enhance_error"] = enhance_error
        if plugin_effects:
            meta["rerun_removed_plugin_effects"] = plugin_effects
        next_clip["metadata"] = meta
        next_track["clips"][next_idx] = next_clip
        next_project["waveform_cache"] = {}
        saved = self.save(next_project, push_history=True)
        report(100, "片段替换完成，工程已保存")
        return {"ok": True, "project": saved, "clip": next_clip}

    def rerun_clip(
        self,
        project_id: str,
        track_id: str,
        clip_id: str,
        model_id: str,
        params: dict[str, Any] | None = None,
        enhance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Queue a local rerun so the editor can show progress and logs."""
        job_id = f"rerun_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        log_path = self._project_dir(project_id) / "reruns" / f"{job_id}.log"
        state: dict[str, Any] = {
            "id": job_id,
            "project_id": project_id,
            "status": "queued",
            "progress": 0,
            "message": "等待开始",
            "log_path": str(log_path),
            "project": None,
            "clip": None,
            "error": None,
        }
        with self._rerun_jobs_lock:
            self._rerun_jobs[job_id] = state

        def write_log(message: str) -> None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"[{datetime.now().strftime('%H:%M:%S')}] {message}\n")

        def update(value: int, message: str) -> None:
            with self._rerun_jobs_lock:
                state["progress"] = max(0, min(100, int(value)))
                state["message"] = message

        def worker() -> None:
            update(1, "开始重推理")
            write_log("=== 编辑器局部重推理开始 ===")
            try:
                result = self._execute_rerun_clip(
                    project_id, track_id, clip_id, model_id, params, enhance,
                    progress=update, log=write_log,
                )
                with self._rerun_jobs_lock:
                    state.update(result)
                    state["status"] = "done" if result.get("ok") else "failed"
                    state["error"] = result.get("error")
                write_log("=== 重推理成功 ===" if result.get("ok") else f"=== 重推理失败：{result.get('error')} ===")
            except Exception as exc:  # noqa: BLE001
                with self._rerun_jobs_lock:
                    state.update(status="failed", error=str(exc), message="重推理失败")
                write_log(f"=== 重推理异常：{exc} ===")

        threading.Thread(target=worker, name=f"editor-rerun-{job_id}", daemon=True).start()
        return {"ok": True, "job_id": job_id, "status": "queued", "progress": 0, "message": "等待开始", "log_path": str(log_path)}

    def rerun_status(self, job_id: str) -> dict[str, Any] | None:
        with self._rerun_jobs_lock:
            state = self._rerun_jobs.get(job_id)
            return copy.deepcopy(state) if state else None

    def rerun_log(self, job_id: str) -> str | None:
        state = self.rerun_status(job_id)
        if not state:
            return None
        path = Path(str(state.get("log_path") or ""))
        try:
            return path.read_text(encoding="utf-8") if path.is_file() else ""
        except OSError:
            return ""

    def enhance_clip(
        self,
        project_id: str,
        track_id: str,
        clip_id: str,
        reference_path: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Apply AI enhancement to an existing editor clip without rerunning VC."""
        project = self._repo.get(project_id)
        if not project:
            return {"ok": False, "error": "工程不存在"}
        track, idx, clip = self._find_clip_ref(project, track_id, clip_id)
        if not track or idx < 0 or not clip:
            return {"ok": False, "error": "片段不存在"}
        if track.get("locked") or clip.get("locked"):
            return {"ok": False, "error": "片段已锁定"}
        source = Path(str(clip.get("file") or ""))
        reference = Path(str(reference_path or ""))
        if not source.is_file():
            return {"ok": False, "error": "片段音频不存在"}
        if not reference.is_file():
            return {"ok": False, "error": "请选择与片段对应的原始歌曲"}
        if not self._vocal_enhancement.available:
            return {"ok": False, "error": "AI 歌声增强环境未就绪"}

        start = float(clip.get("start") or 0.0)
        end = float(clip.get("end") or 0.0)
        duration = end - start
        if duration < self._MIN_RERUN_DURATION:
            return {
                "ok": False,
                "error": f"片段过短：至少 {self._MIN_RERUN_DURATION:.2f} 秒才能增强",
            }
        sample_rate = int(project.get("sample_rate") or 44100)
        out_dir = self._project_dir(project_id) / "enhancements"
        out_dir.mkdir(parents=True, exist_ok=True)
        key = self._rerun_key(source, clip, "ai-enhancement", options or {})
        target_input = out_dir / f"{clip_id}_{key}_input.wav"
        reference_input = out_dir / f"{clip_id}_{key}_reference.wav"
        output = out_dir / f"{clip_id}_{key}_enhanced.wav"
        if not self._audio.trim(
            source,
            float(clip.get("offset") or 0.0),
            float(clip.get("offset") or 0.0) + duration,
            target_input,
            sample_rate=sample_rate,
        ):
            return {"ok": False, "error": "无法读取待增强片段"}
        if not self._audio.trim(reference, start, end, reference_input, sample_rate=sample_rate):
            return {"ok": False, "error": "原始歌曲未覆盖当前片段的时间范围"}

        cfg = options or {}
        level = "advanced" if str(cfg.get("level") or "advanced").lower() == "advanced" else "basic"
        strengths: VocalEnhancementControls = {
            "pitch_correction": self._vocal_enhancement.normalize_strength(
                cfg.get("pitch_correction", 0.45), 0.45
            ),
            "timing_alignment": self._vocal_enhancement.normalize_strength(
                cfg.get("timing_alignment", 0.45), 0.45
            ),
            "timbre_focus": self._vocal_enhancement.normalize_strength(
                cfg.get("timbre_focus", 0.60), 0.60
            ),
            "ai_eq": self._vocal_enhancement.normalize_strength(cfg.get("ai_eq", 0.55), 0.55),
            "ai_compressor": self._vocal_enhancement.normalize_strength(
                cfg.get("ai_compressor", 0.45), 0.45
            ),
            "ai_exciter": self._vocal_enhancement.normalize_strength(
                cfg.get("ai_exciter", 0.25), 0.25
            ),
            "stereo_width": self._vocal_enhancement.normalize_strength(
                cfg.get("stereo_width", 0.30), 0.30
            ),
            "loudness_envelope": self._vocal_enhancement.normalize_strength(
                cfg.get("loudness_envelope", 0.58), 0.58
            ),
        }
        try:
            self._vocal_enhancement.enhance(
                target_input,
                output,
                level=level,
                device=str(cfg.get("device") or "auto"),
                reference=reference_input,
                **strengths,
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        if not output.is_file():
            return {"ok": False, "error": "AI 增强没有生成输出文件"}

        next_project = copy.deepcopy(project)
        next_track, next_idx, next_clip = self._find_clip_ref(next_project, track_id, clip_id)
        if not next_track or next_idx < 0 or not next_clip:
            return {"ok": False, "error": "片段替换失败"}
        next_clip = dict(next_clip)
        next_clip["file"] = str(output)
        next_clip["offset"] = 0.0
        next_clip["name"] = f"{next_clip.get('name') or '片段'} · AI 增强"
        metadata = dict(next_clip.get("metadata") or {})
        metadata.update(
            {
                "ai_enhanced": True,
                "ai_enhancement_level": level,
                "ai_enhancement_reference": str(reference),
                "ai_enhancement_source": str(source),
                "ai_enhancement_at": self._now(),
                **{f"ai_enhancement_{key}": value for key, value in strengths.items()},
            }
        )
        next_clip["metadata"] = metadata
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
        return path.with_name(f"{stem}_{new_id('')}{suffix}")

    @staticmethod
    def _parse_lyric_lines(lyrics: Any) -> list[dict[str, Any]]:
        return parse_lyric_lines(lyrics)

    @staticmethod
    def _parse_plain_lyric_lines(lyrics: Any) -> list[str]:
        return parse_plain_lyric_lines(lyrics)

    @staticmethod
    def _auto_time_lyric_lines(
        texts: list[str],
        duration: float,
        silence_points: list[float],
        min_clip: float,
    ) -> list[dict[str, Any]]:
        return auto_time_lyric_lines(texts, duration, silence_points, min_clip)

    @staticmethod
    def _speech_ranges_from_silence(
        duration: float,
        silences: list[dict[str, float]],
        min_clip: float,
        padding: float,
        min_silence: float,
    ) -> list[tuple[float, float]]:
        return speech_ranges_from_silence(duration, silences, min_clip, padding, min_silence)

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
        return clean_project(project)

    @staticmethod
    def _clean_effects(raw: Any) -> list[dict[str, Any]]:
        return clean_effects(raw)

    @staticmethod
    def _is_plugin_effect(effect: dict[str, Any]) -> bool:
        return is_plugin_effect(effect)

    @staticmethod
    def _clean_volume_envelope(raw: Any, duration: float) -> list[dict[str, float]]:
        return clean_volume_envelope(raw, duration)

    @staticmethod
    def _project_duration(project: dict[str, Any]) -> float:
        return project_duration(project)

    @staticmethod
    def _normalize_format(fmt: str) -> str:
        return normalize_format(fmt)

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
        return ffmpeg_cache_key(
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
        return self._store.project_dir(project_id)

    @staticmethod
    def _find_clip(project: dict[str, Any] | None, clip_id: str) -> dict[str, Any] | None:
        return find_clip(project, clip_id)

    @staticmethod
    def _find_clip_ref(
        project: dict[str, Any], track_id: str, clip_id: str
    ) -> tuple[dict[str, Any] | None, int, dict[str, Any] | None]:
        return find_clip_ref(project, track_id, clip_id)

    @staticmethod
    def _find_effect(clip: dict[str, Any], effect_id: str) -> dict[str, Any] | None:
        return find_effect(clip, effect_id)

    def _audio_data(self, src: Path, exact: bool = False) -> str:
        """音频文件 → data URI；mp3 缓存与 mime 表由文件访问适配层实现。"""
        return self._store.audio_data_uri(src, exact=exact)

    def _waveform_should_render(self, clip: dict[str, Any]) -> bool:
        return should_render_waveform(clip)

    @staticmethod
    def _clip_stretch(clip: dict[str, Any]) -> float:
        return clip_stretch(clip)

    @staticmethod
    def _model_payload(model: dict[str, Any]) -> dict[str, Any]:
        """模型记录 → 重推理载荷；路径映射统一由 ``ModelInfo.engine_paths`` 提供。"""
        info = ModelInfo.from_dict(model)
        return {**info.engine_paths(), "metadata": model.get("metadata") or {}}
