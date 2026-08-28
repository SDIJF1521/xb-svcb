"""作品服务：创建翻唱任务、查询 / 删除 / 重试作品。"""

from __future__ import annotations

import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import config
from domain import JobStatus, Work
from infrastructure import paths
from infrastructure.storage import ListRepository, SettingsStore

from .conversion_service import (
    ConversionService,
    default_steps,
    default_steps_ai_enhancement,
    default_steps_multi,
)
from .model_service import ModelService


class WorkService:
    _WORKFLOWS = {
        "auto_mix",
        "auto_vocal_merge",
        "manual_vocal_merge",
        "auto_then_editor",
        "full_manual_editor",
        "ai_enhancement",
    }
    _VOCAL_MERGE_WORKFLOWS = {"auto_vocal_merge", "manual_vocal_merge"}

    def __init__(
        self,
        repo: ListRepository,
        conversion: ConversionService,
        models: ModelService,
        settings: SettingsStore,
    ) -> None:
        self._repo = repo
        self._conversion = conversion
        self._models = models
        self._settings = settings
        self._realtime_lock = threading.Lock()

    def list(self) -> list[dict[str, Any]]:
        self._cleanup_orphan_work_dirs()
        self._cleanup_orphan_temp_files()
        return [self._view(w) for w in self._repo.all()]

    def register_realtime_output(self, status: dict[str, Any]) -> dict[str, Any] | None:
        """Archive a completed realtime session as a normal playable work.

        The realtime pipeline writes into TEMP_DIR while it is streaming. Once the
        final file exists, copy the complete session directory into the work store
        so the regular player, editor, export and deletion paths can own it.
        """
        if str(status.get("status") or "") != JobStatus.DONE.value:
            return None
        existing_id = str(status.get("work_id") or "").strip()
        if existing_id:
            existing = self._repo.get(existing_id)
            if existing:
                return self._view(existing)
        output = Path(str(status.get("output_path") or ""))
        try:
            output = output.resolve()
            temp_base = (config.TEMP_DIR / "realtime-covers").resolve()
        except OSError:
            return None
        if not output.is_file() or temp_base not in output.parents:
            return None
        session_dir = output.parent
        if session_dir.parent != temp_base:
            return None
        realtime_session_id = str(status.get("id") or session_dir.name).strip()

        with self._realtime_lock:
            existing_id = str(status.get("work_id") or "").strip()
            if existing_id:
                existing = self._repo.get(existing_id)
                if existing:
                    return self._view(existing)
            work_id = paths.new_id("wrk_")
            work_dir = config.WORKS_DIR / work_id
            artifact_dir = work_dir / "realtime"
            try:
                work_dir.mkdir(parents=True, exist_ok=False)
                shutil.copytree(session_dir, artifact_dir)
            except OSError:
                shutil.rmtree(work_dir, ignore_errors=True)
                return None

            archived_output = artifact_dir / output.name
            if not archived_output.is_file():
                shutil.rmtree(work_dir, ignore_errors=True)
                return None
            names = [str(item).strip() for item in (status.get("model_names") or []) if str(item).strip()]
            model_label = "、".join(names) if names else "实时翻唱"
            seconds = self._duration_seconds(status.get("duration"))
            record = {
                "id": work_id,
                "title": f"{str(status.get('title') or '实时翻唱').strip() or '实时翻唱'} (实时翻唱)",
                "model": model_label,
                "model_id": str((status.get("model_ids") or [""])[0] or ""),
                "status": JobStatus.DONE.value,
                "progress": 100,
                "duration": self._format_duration(seconds),
                "format": archived_output.suffix.lstrip(".").upper() or "WAV",
                "size": paths.file_size_label(archived_output),
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "source_path": status.get("source_path"),
                "output_path": str(archived_output),
                "realtime_session_id": realtime_session_id,
                "error": None,
                "params": {},
                "steps": [{"key": "realtime", "label": "实时翻唱", "status": "done"}],
                "workflow": "realtime_cover",
                "mode": "multi" if status.get("mode") == "multi" else "single",
                "segments": list(status.get("segments") or []),
                "log_path": str(artifact_dir / "realtime.log") if (artifact_dir / "realtime.log").is_file() else None,
            }
            stems_dir = artifact_dir / "stems"
            for key, names_to_try in {
                "vocals_path": ("vocals.wav", "vocals.flac"),
                "instrumental_path": ("instrumental.wav", "instrumental.flac"),
            }.items():
                candidate = next((stems_dir / name for name in names_to_try if (stems_dir / name).is_file()), None)
                if candidate:
                    record[key] = str(candidate)
            self._repo.add(record)
            return self._view(record)

    @staticmethod
    def _duration_seconds(value: Any) -> float:
        try:
            return max(0.0, float(value or 0.0))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _format_duration(seconds: float) -> str:
        total = max(0, int(round(seconds)))
        return f"{total // 60:02d}:{total % 60:02d}"

    def _cleanup_orphan_work_dirs(self) -> None:
        """Remove generated work directories whose database record was deleted."""
        try:
            base = config.WORKS_DIR.resolve()
            known = {str(item.get("id") or "") for item in self._repo.all()}
            if not base.exists():
                return
            for child in base.iterdir():
                if child.is_dir() and child.name.startswith("wrk_") and child.name not in known:
                    shutil.rmtree(child, ignore_errors=True)
        except OSError:
            return

    def _cleanup_orphan_temp_files(self) -> None:
        """清理已无作品记录的试听缓存和失去所有者的旧实时会话。"""
        try:
            temp_root = config.TEMP_DIR.resolve()
            if not temp_root.exists():
                return
            works = self._repo.all()
            known_work_ids = {str(item.get("id") or "") for item in works}
            known_session_ids = {
                str(item.get("realtime_session_id") or "")
                for item in works
                if item.get("realtime_session_id")
            }
            cache_suffixes = ("_output.mp3", "_instrumental.mp3", "_vocals.mp3")
            for candidate in temp_root.iterdir():
                if not candidate.is_file():
                    continue
                suffix = next((item for item in cache_suffixes if candidate.name.endswith(item)), "")
                if not suffix:
                    continue
                work_id = candidate.name[: -len(suffix)]
                if work_id.startswith("wrk_") and work_id not in known_work_ids:
                    candidate.unlink(missing_ok=True)

            realtime_root = temp_root / "realtime-covers"
            if not realtime_root.is_dir():
                return
            stale_before = time.time() - 6 * 60 * 60
            for session_dir in realtime_root.iterdir():
                if (
                    not session_dir.is_dir()
                    or not session_dir.name.startswith("live_")
                    or session_dir.name in known_session_ids
                ):
                    continue
                # 未归档的实时任务没有作品记录；只清理长期未更新的目录，保护活跃会话。
                if session_dir.stat().st_mtime < stale_before:
                    shutil.rmtree(session_dir, ignore_errors=True)
        except (OSError, RuntimeError):
            return

    def get(self, work_id: str) -> dict[str, Any] | None:
        work = self._repo.get(work_id)
        return self._view(work) if work else None

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        """根据前端配置创建翻唱任务并启动后台处理。"""
        if str((payload or {}).get("workflow") or "") == "ai_enhancement":
            return self._create_ai_enhancement(payload or {})
        if (payload or {}).get("mode") == "multi":
            return self._create_multi(payload or {})
        return self._create_single(payload or {})

    def create_batch(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """批量创建单模型翻唱任务，任务会进入串行推理队列。"""
        sources = payload.get("source_paths") or []
        created: list[dict[str, Any]] = []
        for raw in sources:
            if not raw:
                continue
            item = dict(payload)
            item.pop("source_paths", None)
            item["source_path"] = raw
            if not item.get("title"):
                item["title"] = Path(str(raw)).stem
            created.append(self.create(item))
        return created

    def queue_status(self) -> dict[str, Any]:
        return self._conversion.queue_status()

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for work in self._repo.all():
            for item in work.get("history") or []:
                rows.append(
                    {
                        **item,
                        "work_id": work.get("id"),
                        "title": work.get("title", ""),
                        "model": work.get("model", ""),
                        "workflow": work.get("workflow", "auto_mix"),
                    }
                )
        rows.sort(key=lambda x: str(x.get("finished_at") or ""), reverse=True)
        return rows[: max(1, int(limit or 50))]

    def list_presets(self) -> list[dict[str, Any]]:
        return list(self._settings.get("inference_presets", []) or [])

    def save_preset(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        presets = self.list_presets()
        preset = {
            "id": paths.new_id("pre_"),
            "name": (name or "未命名预设").strip() or "未命名预设",
            "params": params or {},
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        presets = [p for p in presets if p.get("name") != preset["name"]]
        presets.insert(0, preset)
        self._settings.set("inference_presets", presets[:30])
        return preset

    def delete_preset(self, preset_id: str) -> bool:
        presets = self.list_presets()
        next_presets = [p for p in presets if p.get("id") != preset_id]
        self._settings.set("inference_presets", next_presets)
        return len(next_presets) != len(presets)

    def _create_single(self, payload: dict[str, Any]) -> dict[str, Any]:
        model_id = payload.get("model_id") or self._models.default_id()
        model = self._models.get(model_id) if model_id else None
        source_path = payload.get("source_path")
        workflow = self._workflow(payload, mode="single")
        vocal_enhancement = self._vocal_enhancement(payload, workflow)
        preprocess = self._preprocess(payload)

        title = payload.get("title")
        if not title:
            if source_path:
                title = Path(source_path).stem
            else:
                title = "未命名翻唱"

        work = Work(
            id=paths.new_id("wrk_"),
            title=f"{title} (AI 翻唱)",
            model=model["name"] if model else "默认模型",
            model_id=model_id or "",
            status=JobStatus.QUEUE.value,
            progress=0,
            duration="—",
            format="—",
            size="—",
            created_at=datetime.now().isoformat(timespec="seconds"),
            source_path=source_path,
            params=payload.get("params", {}) or {},
            steps=default_steps(
                vocal_enhancement["enabled"],
                preprocess["enabled"],
                preprocess["harmony_removal_enabled"],
            ),
            workflow=workflow,
            vocal_enhancement=vocal_enhancement,
            preprocess=preprocess,
        )
        record = work.to_dict()
        record.update(self._resolve_model_paths(model))
        self._repo.add(record)
        self._conversion.start(work.id)
        return self._view(record)

    def _create_ai_enhancement(self, payload: dict[str, Any]) -> dict[str, Any]:
        parent_id = str(payload.get("target_work_id") or payload.get("parent_work_id") or "").strip()
        parent = self._repo.get(parent_id) if parent_id else None
        target_audio = str(payload.get("target_audio_path") or payload.get("cover_audio_path") or "").strip()
        if parent and parent.get("status") != JobStatus.DONE.value:
            raise ValueError("请选择一个已完成的翻唱作品")
        if parent:
            target_output = Path(str(parent.get("output_path") or ""))
        else:
            target_output = Path(target_audio)
            if not target_audio:
                raise ValueError("请选择已完成翻唱作品或导入待增强音频")
        if not target_output.is_file():
            raise ValueError("待增强的翻唱音频不存在")
        original = Path(str(payload.get("original_audio_path") or payload.get("source_path") or ""))
        if not original.is_file():
            raise ValueError("请选择与翻唱作品对应的原始歌曲音频")

        settings = self._vocal_enhancement(payload, "ai_enhancement")
        settings["enabled"] = True
        title = str(payload.get("title") or (parent or {}).get("title") or target_output.stem).strip()
        work = Work(
            id=paths.new_id("wrk_"),
            title=f"{title} (AI 增强)",
            model=f"{(parent or {}).get('model') or '导入音频'} · AI 增强",
            model_id=str((parent or {}).get("model_id") or ""),
            status=JobStatus.QUEUE.value,
            progress=0,
            duration=str((parent or {}).get("duration") or "—"),
            format="—",
            size="—",
            created_at=datetime.now().isoformat(timespec="seconds"),
            source_path=str(original),
            params=payload.get("params", {}) or {},
            steps=default_steps_ai_enhancement(),
            workflow="ai_enhancement",
            vocal_enhancement=settings,
            mode=str((parent or {}).get("mode") or "single"),
        )
        record = work.to_dict()
        record.update(
            {
                "parent_work_id": parent_id or None,
                "original_audio_path": str(original),
                "target_output_path": str(target_output),
                "target_vocal_path": str(
                    (parent or {}).get("ai_merged_vocal_path")
                    or (parent or {}).get("converted_path")
                    or ""
                ),
                "target_instrumental_path": str((parent or {}).get("instrumental_path") or ""),
            }
        )
        self._repo.add(record)
        self._conversion.start(work.id)
        return self._view(record)

    def _create_multi(self, payload: dict[str, Any]) -> dict[str, Any]:
        """创建多模型混合翻唱任务：每句歌词指派给不同模型。"""
        source_path = payload.get("source_path")
        title = payload.get("title") or (
            Path(source_path).stem if source_path else "未命名翻唱"
        )

        # 收集本次用到的模型及其各自参数（解析为可推理的本地路径）
        workflow = self._workflow(payload, mode="multi")
        vocal_enhancement = self._vocal_enhancement(payload, workflow)
        preprocess = self._preprocess(payload)
        seg_models: dict[str, Any] = {}
        for entry in payload.get("models", []) or []:
            mid = entry.get("model_id")
            if not mid or mid in seg_models:
                continue
            model = self._models.get(mid)
            if not model:
                continue
            seg_models[mid] = {
                "name": model.get("name", mid),
                "params": entry.get("params", {}) or {},
                **self._resolve_model_paths(model),
            }

        # 仅保留指派给有效模型的演唱句。每句支持「合唱」：可指派多个模型
        # （model_ids 数组）。兼容旧的单模型字段 model_id。
        segments: list[dict[str, Any]] = []
        for s in payload.get("segments", []) or []:
            try:
                start = float(s.get("start", 0.0))
                end = float(s.get("end", 0.0))
            except (TypeError, ValueError):
                continue
            if end <= start:
                continue
            raw_ids = s.get("model_ids")
            if not raw_ids:
                single = s.get("model_id")
                raw_ids = [single] if single else []
            # 去重并仅保留有效模型，保持指派顺序
            ids: list[str] = []
            for mid in raw_ids:
                if mid in seg_models and mid not in ids:
                    ids.append(mid)
            if not ids:
                continue
            segments.append(
                {"start": start, "end": end, "model_id": ids[0], "model_ids": ids}
            )

        # 展示用：主模型名取首个模型；基础参数（分离设备/UVR 模型）取首个模型参数
        first = next(iter(seg_models.values()), None)
        base_params = first["params"] if first else {}
        model_label = (
            "多模型混合（{} 个）".format(len(seg_models)) if seg_models else "多模型混合"
        )

        work = Work(
            id=paths.new_id("wrk_"),
            title=f"{title} (混合翻唱)",
            model=model_label,
            model_id=next(iter(seg_models), ""),
            status=JobStatus.QUEUE.value,
            progress=0,
            duration="—",
            format="—",
            size="—",
            created_at=datetime.now().isoformat(timespec="seconds"),
            source_path=source_path,
            params=base_params,
            steps=default_steps_multi(
                vocal_enhancement["enabled"],
                preprocess["enabled"],
                preprocess["harmony_removal_enabled"],
            ),
            workflow=workflow,
            vocal_enhancement=vocal_enhancement,
            preprocess=preprocess,
            mode="multi",
            segments=segments,
        )
        record = work.to_dict()
        record["seg_models"] = seg_models
        self._repo.add(record)
        self._conversion.start(work.id)
        return self._view(record)

    @classmethod
    def _workflow(cls, payload: dict[str, Any], mode: str = "single") -> str:
        value = str((payload or {}).get("workflow") or "auto_mix")
        if value not in cls._WORKFLOWS:
            return "auto_mix"
        if mode != "multi" and value in cls._VOCAL_MERGE_WORKFLOWS:
            return "auto_mix"
        return value

    @staticmethod
    def _vocal_enhancement(
        payload: dict[str, Any], workflow: str
    ) -> dict[str, Any]:
        raw = (payload or {}).get("vocal_enhancement") or {}
        if not isinstance(raw, dict):
            raw = {}
        level = str(raw.get("level") or "basic").strip().lower()
        if level not in {"basic", "advanced"}:
            level = "basic"

        def strength(key: str, default: float) -> float:
            try:
                value = float(raw.get(key, default))
            except (TypeError, ValueError):
                value = default
            if value != value:
                value = default
            return max(0.0, min(1.0, value))

        # 手动人声合并没有自动生成的整轨 AI 人声，增强应在编辑器导出后进行。
        enabled = bool(raw.get("enabled")) and workflow != "manual_vocal_merge"
        return {
            "enabled": enabled,
            "level": level,
            "pitch_correction": strength("pitch_correction", 0.45),
            "timing_alignment": strength("timing_alignment", 0.45),
            "timbre_focus": strength("timbre_focus", 0.60),
            "ai_eq": strength("ai_eq", 0.55),
            "ai_compressor": strength("ai_compressor", 0.45),
            "ai_exciter": strength("ai_exciter", 0.25),
            "stereo_width": strength("stereo_width", 0.30),
            "loudness_envelope": strength("loudness_envelope", 0.58),
        }

    @staticmethod
    def _preprocess(payload: dict[str, Any] | None) -> dict[str, Any]:
        raw = (payload or {}).get("preprocess") or {}
        if not isinstance(raw, dict):
            raw = {}
        enabled = raw.get("enabled", True) is not False
        engine = str(raw.get("engine") or "uvr").strip().lower()
        if engine not in {"uvr", "pymss"}:
            engine = "uvr"
        model = str(raw.get("pymss_model") or config.PYMSS_DEFAULT_MODEL).strip()
        harmony_enabled = bool(enabled and raw.get("harmony_removal_enabled"))
        harmony_model = str(
            raw.get("harmony_model") or config.PYMSS_DEFAULT_HARMONY_MODEL
        ).strip()
        return {
            "enabled": bool(enabled),
            "engine": engine,
            "pymss_model": model,
            "harmony_removal_enabled": harmony_enabled,
            "harmony_model": harmony_model,
        }

    @staticmethod
    def _resolve_model_paths(model: dict[str, Any] | None) -> dict[str, str]:
        """从模型记录提取推理所需的文件路径与框架标识。

        返回含 ``framework``（路由引擎用）、so-vits / SeedVC 的 main/config 路径、
        RVC 的 ``index_path``；推理引擎按 ``framework`` 各取所需。
        """
        if not model:
            return {
                "framework": config.MODELHUB_DEFAULT_FRAMEWORK,
                "main_model_path": "",
                "main_config_path": "",
                "diffusion_model_path": "",
                "diffusion_config_path": "",
                "index_path": "",
            }
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

    def retry(self, work_id: str) -> bool:
        work = self._repo.get(work_id)
        if not work:
            return False
        # 实时翻唱的归档记录没有普通转换任务所需的推理参数，不能按常规任务重跑。
        if work.get("workflow") == "realtime_cover":
            return False
        work["status"] = JobStatus.QUEUE.value
        work["progress"] = 0
        work["error"] = None
        enhancement_enabled = bool(
            (work.get("vocal_enhancement") or {}).get("enabled")
        )
        preprocess_record = work.get("preprocess") or {}
        preprocess_enabled = bool(preprocess_record.get("enabled", True))
        harmony_enabled = bool(
            preprocess_enabled and preprocess_record.get("harmony_removal_enabled")
        )
        if work.get("workflow") == "ai_enhancement":
            work["steps"] = default_steps_ai_enhancement()
        else:
            work["steps"] = (
                default_steps_multi(enhancement_enabled, preprocess_enabled, harmony_enabled)
                if work.get("mode") == "multi"
                else default_steps(enhancement_enabled, preprocess_enabled, harmony_enabled)
            )
        self._repo.update(work_id, work)
        self._conversion.start(work_id)
        return True

    def recover_stale(self) -> int:
        """把上次会话残留的 running/queue 任务标记为失败（其线程已随进程退出）。"""
        count = 0
        for work in self._repo.all():
            if work.get("status") in (JobStatus.RUNNING.value, JobStatus.QUEUE.value):
                work["status"] = JobStatus.FAILED.value
                work["error"] = "上次任务因程序退出而中断，请重试"
                for step in work.get("steps", []):
                    if step.get("status") == "active":
                        step["status"] = "failed"
                self._repo.update(work["id"], work)
                count += 1
        return count

    def rename(self, work_id: str, title: str) -> bool:
        """重命名作品（标题用于展示与导出文件名）。"""
        work = self._repo.get(work_id)
        if not work:
            return False
        new_title = (title or "").strip()
        if not new_title:
            return False
        work["title"] = new_title[:120]
        self._repo.update(work_id, work)
        return True

    def remove(self, work_id: str) -> bool:
        """删除作品：移除记录的同时真正删除该作品在本地生成的所有文件。

        作品的全部产物（人声分离结果、F0、推理/混音音频、日志等）都集中在
        ``config.WORKS_DIR/<work_id>`` 目录内，整目录删除即可彻底清理。
        用户自备的源音频（source_path，可能在音乐库或任意位置）不在此删除范围。
        """
        if not self._repo.get(work_id):
            return False
        work = self._repo.get(work_id) or {}
        self._repo.remove(work_id)
        self._purge_work_dir(work_id)
        self._purge_work_cache(work_id, work)
        return True

    @staticmethod
    def _purge_work_dir(work_id: str) -> None:
        """删除作品目录（校验其确实位于 WORKS_DIR 内，避免误删任意路径）。"""
        if not work_id:
            return
        try:
            base = config.WORKS_DIR.resolve()
            target = (config.WORKS_DIR / work_id).resolve()
        except OSError:
            return
        # 仅允许删除 WORKS_DIR 下的子目录，防止 work_id 含 .. 等导致越界
        if target.parent != base or not target.exists():
            return
        shutil.rmtree(target, ignore_errors=True)

    @staticmethod
    def _purge_work_cache(work_id: str, work: dict[str, Any] | None = None) -> None:
        """删除作品关联的试听缓存和实时会话目录，不触碰用户导出的文件。"""
        if not work_id:
            return
        try:
            temp_dir = config.TEMP_DIR.resolve()
        except OSError:
            return
        for kind in ("output", "instrumental", "vocals"):
            target = temp_dir / f"{work_id}_{kind}.mp3"
            try:
                if target.parent == temp_dir and target.is_file():
                    target.unlink()
            except OSError:
                continue
        session_id = str((work or {}).get("realtime_session_id") or "").strip()
        if not session_id or Path(session_id).name != session_id:
            return
        realtime_base = temp_dir / "realtime-covers"
        session_dir = realtime_base / session_id
        try:
            if session_dir.parent == realtime_base and session_dir.is_dir():
                shutil.rmtree(session_dir, ignore_errors=True)
        except OSError:
            return

    @staticmethod
    def _view(work: dict[str, Any]) -> dict[str, Any]:
        """对外视图：补充展示用的相对时间字段，隐藏内部路径无需特别处理。"""
        view = dict(work)
        view["time"] = WorkService._relative_time(work.get("created_at", ""))
        view["output"] = work.get("output_path")
        return view

    @staticmethod
    def _relative_time(iso: str) -> str:
        if not iso:
            return "—"
        try:
            created = datetime.fromisoformat(iso)
        except ValueError:
            return iso
        delta = datetime.now() - created
        secs = int(delta.total_seconds())
        if secs < 60:
            return "刚刚"
        if secs < 3600:
            return f"{secs // 60} 分钟前"
        if secs < 86400:
            return f"{secs // 3600} 小时前"
        if secs < 172800:
            return "昨天"
        return created.strftime("%m-%d %H:%M")
