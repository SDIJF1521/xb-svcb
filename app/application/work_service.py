"""作品服务：创建翻唱任务、查询 / 删除 / 重试作品。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from domain import JobStatus, Work
from infrastructure import paths
from infrastructure.storage import ListRepository

from .conversion_service import ConversionService, default_steps
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
        record["main_model_path"] = (
            (model.get("main_model") or {}).get("path", "") if model else ""
        )
        record["main_config_path"] = (
            (model.get("main_config") or {}).get("path", "") if model else ""
        )
        record["diffusion_model_path"] = (
            (model.get("diffusion_model") or {}).get("path", "") if model else ""
        )
        record["diffusion_config_path"] = (
            (model.get("diffusion_config") or {}).get("path", "") if model else ""
        )
        self._repo.add(record)
        self._conversion.start(work.id)
        return self._view(record)

    def retry(self, work_id: str) -> bool:
        work = self._repo.get(work_id)
        if not work:
            return False
        work["status"] = JobStatus.QUEUE.value
        work["progress"] = 0
        work["error"] = None
        work["steps"] = default_steps()
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
        if not self._repo.get(work_id):
            return False
        self._repo.remove(work_id)
        return True

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
