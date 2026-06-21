"""作品服务：创建翻唱任务、查询 / 删除 / 重试作品。"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import config
from domain import JobStatus, Work
from infrastructure import paths
from infrastructure.storage import ListRepository

from .conversion_service import ConversionService, default_steps, default_steps_multi
from .model_service import ModelService


class WorkService:
    def __init__(
        self,
        repo: ListRepository,
        conversion: ConversionService,
        models: ModelService,
    ) -> None:
        self._repo = repo
        self._conversion = conversion
        self._models = models

    def list(self) -> list[dict[str, Any]]:
        return [self._view(w) for w in self._repo.all()]

    def get(self, work_id: str) -> dict[str, Any] | None:
        work = self._repo.get(work_id)
        return self._view(work) if work else None

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        """根据前端配置创建翻唱任务并启动后台处理。"""
        if (payload or {}).get("mode") == "multi":
            return self._create_multi(payload or {})
        return self._create_single(payload or {})

    def _create_single(self, payload: dict[str, Any]) -> dict[str, Any]:
        model_id = payload.get("model_id") or self._models.default_id()
        model = self._models.get(model_id) if model_id else None
        source_path = payload.get("source_path")

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
            steps=default_steps(),
        )
        record = work.to_dict()
        record.update(self._resolve_model_paths(model))
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

        # 仅保留指派给有效模型的演唱句
        segments = [
            {
                "start": float(s.get("start", 0.0)),
                "end": float(s.get("end", 0.0)),
                "model_id": s.get("model_id"),
            }
            for s in (payload.get("segments", []) or [])
            if s.get("model_id") in seg_models
            and float(s.get("end", 0.0)) > float(s.get("start", 0.0))
        ]

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
            steps=default_steps_multi(),
            mode="multi",
            segments=segments,
        )
        record = work.to_dict()
        record["seg_models"] = seg_models
        self._repo.add(record)
        self._conversion.start(work.id)
        return self._view(record)

    @staticmethod
    def _resolve_model_paths(model: dict[str, Any] | None) -> dict[str, str]:
        """从模型记录提取推理所需的四个本地文件路径。"""
        if not model:
            return {
                "main_model_path": "",
                "main_config_path": "",
                "diffusion_model_path": "",
                "diffusion_config_path": "",
            }
        return {
            "main_model_path": (model.get("main_model") or {}).get("path", ""),
            "main_config_path": (model.get("main_config") or {}).get("path", ""),
            "diffusion_model_path": (model.get("diffusion_model") or {}).get("path", ""),
            "diffusion_config_path": (model.get("diffusion_config") or {}).get("path", ""),
        }

    def retry(self, work_id: str) -> bool:
        work = self._repo.get(work_id)
        if not work:
            return False
        work["status"] = JobStatus.QUEUE.value
        work["progress"] = 0
        work["error"] = None
        work["steps"] = (
            default_steps_multi() if work.get("mode") == "multi" else default_steps()
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
        self._repo.remove(work_id)
        self._purge_work_dir(work_id)
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
