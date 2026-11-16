"""用户数据目录用例：查看占用、切换目录、后台迁移。

原实现位于 ``api/bridge.py``（约 500 行）。数据目录的判定、占用统计、空间校验、
带进度复制与指针写入属于用例编排，文件系统能力由 ``DataTransferPort`` 提供。
表现层只负责弹出目录选择对话框和转发结果。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

import config
from domain.formatting import human_size

from .adapters import data_transfer
from .ports import DataTransferPort, ItemRepository, SettingsRepository


class DataMaintenanceService:
    """数据目录查看、切换与迁移的用例服务。"""

    def __init__(
        self,
        models_repo: ItemRepository,
        works_repo: ItemRepository,
        editor_repo: ItemRepository,
        settings: SettingsRepository,
        queue_status: Callable[[], dict[str, Any]] | None = None,
        api_running: Callable[[], bool] | None = None,
        transfer: DataTransferPort | None = None,
    ) -> None:
        self._models_repo = models_repo
        self._works_repo = works_repo
        self._editor_repo = editor_repo
        self._settings = settings
        self._queue_status = queue_status or (lambda: {"running": False, "size": 0})
        self._api_running = api_running or (lambda: False)
        self._transfer = transfer or data_transfer()
        self._migration_lock = threading.Lock()
        self._migration = self._empty_migration_status()

    # ---- 查看 ----

    def set_api_running_provider(self, provider: Callable[[], bool] | None) -> None:
        """注入「HTTP 服务是否在运行」的查询（由组合根在门面创建后接线）。"""
        self._api_running = provider or (lambda: False)

    def storage_status(self) -> dict[str, Any]:
        """返回用户数据目录、占用和所在磁盘剩余空间。"""
        self.refresh_active_data_dir()
        return self._storage_payload()

    def refresh_active_data_dir(self) -> None:
        """按最新持久化指针修正当前会话的数据目录。"""
        if config.refresh_data_dir_from_home():
            self.retarget_data_stores()

    def retarget_data_stores(self) -> None:
        """根据 config 当前数据目录重建目录并重定向 JSON 仓储。"""
        for directory in (
            config.DATA_DIR,
            config.MODELS_DIR,
            config.WORKS_DIR,
            config.TEMP_DIR,
            config.MUSIC_DIR,
            config.MODELHUB_DIR,
            config.EDITOR_DIR,
            config.EDITOR_CACHE_DIR,
            config.THEME_MEDIA_DIR,
            config.API_UPLOADS_DIR,
            config.PLUGINS_DIR,
            config.PLUGIN_DATA_DIR,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self._models_repo.set_path(config.MODELS_DB)
        self._works_repo.set_path(config.WORKS_DB)
        self._editor_repo.set_path(config.EDITOR_PROJECTS_DB)
        self._settings.set_path(config.SETTINGS_DB)

    # ---- 切换（不复制数据）----

    def set_data_dir(self, target_dir: str) -> dict[str, Any]:
        """直接切换到用户选择的数据目录，不复制当前数据。"""
        with self._migration_lock:
            if self._migration.get("status") == "running":
                return {
                    "ok": False,
                    "error": "数据目录迁移正在进行中，请等待当前迁移完成。",
                    **self._storage_payload(),
                }

        blocker = self.data_dir_change_blocker()
        if blocker:
            return {"ok": False, "error": blocker, **self._storage_payload()}

        try:
            current = config.DATA_DIR.resolve()
            current.mkdir(parents=True, exist_ok=True)
        except OSError:
            return {"ok": False, "error": "当前数据目录无法访问。", **self._storage_payload()}

        target, target_error = self._transfer.resolve_data_dir_target(target_dir, current)
        if target_error:
            return {"ok": False, "error": target_error, **self._storage_payload()}
        if target is None:
            return {"ok": False, "error": "请选择目标目录。", **self._storage_payload()}
        if target == current:
            return {
                "ok": True,
                "restart_required": False,
                "message": "当前已经在使用这个数据目录。",
                **self._storage_payload(),
            }

        try:
            target.mkdir(parents=True, exist_ok=True)
            if not self._transfer.test_writable(target):
                return {"ok": False, "error": "目标目录不可写。", **self._storage_payload()}
            self._transfer.write_marker(target, selected_from=str(target_dir or ""))
        except OSError as exc:
            return {
                "ok": False,
                "error": f"无法准备目标数据目录：{exc}",
                **self._storage_payload(),
            }

        if not config.write_data_home(target):
            return {
                "ok": False,
                "error": "写入数据目录指针失败。",
                **self._storage_payload(),
            }

        self.switch_active_data_dir(target)
        return {
            "ok": True,
            "restart_required": True,
            "message": "数据目录已切换，后续文件将写入新目录。建议重启软件以刷新窗口缓存。",
            **self._storage_payload(),
        }

    def switch_active_data_dir(self, target: Path) -> None:
        """让当前进程的默认数据路径和 JSON 仓储立即切到目标目录。"""
        config.switch_data_dir(target)
        self.retarget_data_stores()

    # ---- 迁移（复制数据）----

    def start_migration(self, target_dir: str) -> dict[str, Any]:
        """启动后台迁移任务，前端通过 migration_status 轮询进度。"""
        with self._migration_lock:
            if self._migration.get("status") == "running":
                return {
                    "ok": False,
                    "error": "数据目录迁移正在进行中，请等待当前迁移完成。",
                    **self._migration,
                }
            blocker = self.data_dir_change_blocker()
            if blocker:
                return {
                    "ok": False,
                    "error": blocker,
                    **self._empty_migration_status(),
                }
            self._migration = {
                **self._empty_migration_status(),
                "status": "running",
                "phase": "preparing",
                "message": "正在准备迁移...",
                "target_dir": target_dir,
            }
        thread = threading.Thread(
            target=self._run_migration,
            args=(target_dir,),
            name="xb-data-migration",
            daemon=True,
        )
        thread.start()
        return {"ok": True, "started": True, **self.migration_status()}

    def migration_status(self) -> dict[str, Any]:
        """返回最近一次迁移任务状态。"""
        with self._migration_lock:
            status = dict(self._migration)
            if isinstance(status.get("result"), dict):
                status["result"] = dict(status["result"])
            return status

    def migrate(self, target_dir: str) -> dict[str, Any]:
        """兼容旧前端的同步迁移入口。新前端使用 start/migration_status 显示进度。"""
        started = self.start_migration(target_dir)
        if not started.get("ok"):
            return {
                "ok": False,
                "error": started.get("error") or "迁移启动失败。",
                **self._storage_payload(),
            }
        while True:
            status = self.migration_status()
            if status.get("status") == "done":
                result = status.get("result")
                if isinstance(result, dict):
                    return result
                return {
                    "ok": True,
                    "message": status.get("message") or "数据目录已迁移。",
                    **self._storage_payload(),
                }
            if status.get("status") == "failed":
                return {
                    "ok": False,
                    "error": status.get("error") or "迁移失败。",
                    **self._storage_payload(),
                }
            time.sleep(0.2)

    def data_dir_change_blocker(self) -> str | None:
        """数据目录不可更改的原因；可以更改时返回 None。"""
        env = config.data_dir_env_override()
        if env:
            return (
                "当前数据目录由环境变量指定，软件内无法更改。"
                f"请先移除环境变量后再操作：{env}"
            )
        queue = self._queue_status()
        if queue.get("running") or queue.get("size"):
            return "当前有推理任务正在运行或排队，请等待任务结束后再更改数据目录。"
        if self._api_running():
            return "API 服务正在运行，请先在 API 接入页停止服务再更改数据目录。"
        return None

    def _run_migration(self, target_dir: str) -> None:
        """后台执行迁移，并持续更新迁移状态。"""
        blocker = self.data_dir_change_blocker()
        if blocker:
            self._fail_migration(blocker)
            return
        try:
            src = config.DATA_DIR.resolve()
            src.mkdir(parents=True, exist_ok=True)
        except OSError:
            self._fail_migration("当前数据目录无法访问。")
            return

        target, target_error = self._transfer.resolve_migration_target(target_dir, src)
        if target_error:
            self._fail_migration(target_error)
            return
        if target is None:
            self._fail_migration("请选择目标目录。")
            return

        self._update_migration(
            phase="scanning",
            message="正在统计需要迁移的数据...",
            percent=2,
            target_dir=str(target),
        )
        required = self._transfer.dir_size(src, ignore_tmp=True, skip_volatile=True)
        self._update_migration(
            total_bytes=required,
            total=human_size(required),
            phase="checking",
            message="正在检查目标磁盘空间...",
            percent=5,
        )
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError:
            self._fail_migration("无法访问目标目录或磁盘。")
            return
        free, _total = self._transfer.disk_usage(target)
        if free <= 0 and _total <= 0:
            self._fail_migration("无法访问目标目录或磁盘。")
            return
        safety = max(512 * 1024 * 1024, int(required * 0.08))
        if free < required + safety:
            self._fail_migration(
                f"目标磁盘空间不足：需要至少 {human_size(required + safety)}，"
                f"当前可用 {human_size(free)}。"
            )
            return
        if not self._transfer.test_writable(target):
            self._fail_migration("目标目录不可写。")
            return

        staging = target.with_name(target.name + ".migrating")
        try:
            if staging.exists():
                self._remove_tree(staging)
            if target.exists() and any(target.iterdir()):
                # 已有 XB-SVCB 数据目录：先不覆盖，直接切换指针。
                staging = target
                self._update_migration(
                    phase="switching",
                    message="正在切换到已有 XB-SVCB 数据目录...",
                    copied_bytes=required,
                    copied=human_size(required),
                    percent=88,
                )
            else:
                self._update_migration(
                    phase="copying",
                    message="正在复制数据...",
                    copied_bytes=0,
                    copied=human_size(0),
                    percent=6,
                )
                self._transfer.copy_tree(src, staging, required, self._copy_progress)
                if target.exists():
                    target.rmdir()
                staging.replace(target)
            self._update_migration(
                phase="finalizing",
                message="正在写入迁移标记...",
                copied_bytes=required,
                copied=human_size(required),
                percent=94,
            )
            self._transfer.write_marker(target, migrated_from=str(src))
            (src / config.DATA_MIGRATION_MARKER).write_text(
                json.dumps({"target": str(target)}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if not config.write_data_home(target, pending_delete=src):
                self._fail_migration("数据已复制，但写入数据目录指针失败。")
                return
            self.switch_active_data_dir(target)
            active_payload = self._storage_payload()
            result = {
                "ok": True,
                "restart_required": True,
                "message": "数据目录已迁移，后续文件将写入新目录。建议重启软件以完成旧目录清理。",
                "old_data_dir": str(src),
                **active_payload,
            }
            self._update_migration(
                status="done",
                phase="done",
                message=result["message"],
                copied_bytes=required,
                copied=human_size(required),
                percent=100,
                result=result,
            )
        except OSError as exc:
            try:
                if staging.exists() and staging != target:
                    self._remove_tree(staging)
            except OSError:
                pass
            self._fail_migration(f"迁移失败：{exc}")

    # ---- 内部 ----

    def _copy_progress(self, copied_bytes: int) -> None:
        status = self.migration_status()
        total_bytes = int(status.get("total_bytes") or 0)
        if total_bytes > 0:
            percent = 6 + int(min(copied_bytes, total_bytes) * 82 / total_bytes)
        else:
            percent = 88
        self._update_migration(
            phase="copying",
            message="正在复制数据...",
            copied_bytes=min(copied_bytes, total_bytes) if total_bytes > 0 else copied_bytes,
            percent=percent,
        )

    @staticmethod
    def _remove_tree(path: Path) -> None:
        from shutil import rmtree

        rmtree(path)

    @staticmethod
    def _empty_migration_status() -> dict[str, Any]:
        return {
            "status": "idle",
            "phase": "idle",
            "message": "未开始迁移。",
            "target_dir": "",
            "copied_bytes": 0,
            "copied": human_size(0),
            "total_bytes": 0,
            "total": human_size(0),
            "percent": 0,
        }

    def _update_migration(self, **updates: Any) -> None:
        if "copied_bytes" in updates and "copied" not in updates:
            updates["copied"] = human_size(int(updates["copied_bytes"] or 0))
        if "total_bytes" in updates and "total" not in updates:
            updates["total"] = human_size(int(updates["total_bytes"] or 0))
        if "percent" in updates:
            updates["percent"] = max(0, min(100, int(updates["percent"] or 0)))
        with self._migration_lock:
            self._migration.update(updates)

    def _fail_migration(self, message: str) -> None:
        self._update_migration(
            status="failed",
            phase="failed",
            message=message,
            error=message,
        )

    def _storage_payload(self) -> dict[str, Any]:
        data_dir = config.DATA_DIR
        used = self._transfer.dir_size(data_dir)
        free, total = self._transfer.disk_usage(
            data_dir if data_dir.exists() else data_dir.parent
        )
        return {
            "data_dir": str(data_dir),
            "used_bytes": used,
            "used": human_size(used),
            "free_bytes": free,
            "free": human_size(free),
            "total_bytes": total,
            "total": human_size(total),
            "pointer_file": str(config.active_data_home_file()),
            "pointer_files": [str(path) for path in config.DATA_HOME_FILES],
        }
