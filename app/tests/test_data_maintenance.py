"""数据目录用例（DataMaintenanceService）的测试。

覆盖：占用统计、切换目录的前置校验与标记、迁移复制、迁移阻塞条件。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import config
from application.data_maintenance_service import DataMaintenanceService
from infrastructure.data_transfer import DataTransfer
from infrastructure.storage import ListRepository, SettingsStore


@pytest.fixture()
def data_root(tmp_path: Path) -> Path:
    src = tmp_path / "data"
    (src / "works").mkdir(parents=True)
    (src / "models.json").write_text("[]", encoding="utf-8")
    (src / "works" / "a.wav").write_bytes(b"x" * 128)
    (src / "temp").mkdir()
    (src / "temp" / "scratch.wav").write_bytes(b"y" * 64)
    return src


@pytest.fixture()
def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data_root: Path):
    monkeypatch.setattr(config, "DATA_DIR", data_root)
    monkeypatch.setattr(config, "refresh_data_dir_from_home", lambda: False)
    monkeypatch.setattr(
        config, "write_data_home", lambda target, pending_delete=None: True
    )
    switched: list[Path] = []
    monkeypatch.setattr(config, "switch_data_dir", lambda target: switched.append(target))
    queue = {"running": False, "size": 0}
    api = {"running": False}
    instance = DataMaintenanceService(
        ListRepository(tmp_path / "models.json"),
        ListRepository(tmp_path / "works.json"),
        ListRepository(tmp_path / "editor.json"),
        SettingsStore(tmp_path / "settings.json"),
        queue_status=lambda: dict(queue),
        api_running=lambda: api["running"],
        transfer=DataTransfer(),
    )
    # 仓储重定向会写真实数据目录，这里只验证编排，不实际搬指针。
    instance.retarget_data_stores = lambda: None  # type: ignore[method-assign]
    instance.queue = queue  # type: ignore[attr-defined]
    instance.api = api  # type: ignore[attr-defined]
    instance.switched = switched  # type: ignore[attr-defined]
    return instance


def test_storage_status_reports_used_bytes_and_free_space(service) -> None:
    status = service.storage_status()
    assert status["data_dir"] == str(config.DATA_DIR)
    assert status["used_bytes"] >= 192
    assert status["used"].endswith(("B", "KB", "MB", "GB", "TB"))
    assert status["pointer_files"]


def test_set_data_dir_is_blocked_while_tasks_are_running(service) -> None:
    service.queue["running"] = True  # type: ignore[attr-defined]
    result = service.set_data_dir(str(Path(config.DATA_DIR).parent / "other"))
    assert result["ok"] is False
    assert "推理任务" in result["error"]


def test_set_data_dir_is_blocked_while_http_api_runs(service) -> None:
    service.api["running"] = True  # type: ignore[attr-defined]
    result = service.set_data_dir(str(Path(config.DATA_DIR).parent / "other"))
    assert result["ok"] is False
    assert "API 服务" in result["error"]


def test_set_data_dir_writes_marker_and_requires_restart(service, tmp_path: Path) -> None:
    target = tmp_path / "new-data"
    target.mkdir()
    result = service.set_data_dir(str(target))

    assert result["ok"] is True
    assert result["restart_required"] is True
    marker = target / config.DATA_MARKER_FILE
    assert marker.is_file()
    assert "selected_from" in marker.read_text(encoding="utf-8")
    assert service.switched == [target.resolve()]  # type: ignore[attr-defined]


def test_set_data_dir_rejects_non_empty_plain_directory(service, tmp_path: Path) -> None:
    # 普通目录会追加数据目录名再使用；若该子目录已有无关内容则拒绝。
    target = tmp_path / "random-dir"
    (target / config.DATA_DIR_NAME).mkdir(parents=True)
    (target / config.DATA_DIR_NAME / "notes.txt").write_text("hello", encoding="utf-8")

    result = service.set_data_dir(str(target))
    assert result["ok"] is False
    assert "空目录" in result["error"]


def test_set_data_dir_uses_existing_data_dir_without_copy(service, tmp_path: Path) -> None:
    existing = tmp_path / "existing-data"
    existing.mkdir()
    (existing / config.DATA_MARKER_FILE).write_text("{}", encoding="utf-8")
    (existing / "works.json").write_text("[]", encoding="utf-8")

    result = service.set_data_dir(str(existing))
    assert result["ok"] is True
    assert result["restart_required"] is True


def test_set_data_dir_rejects_target_inside_current_data_dir(service, data_root: Path) -> None:
    nested = data_root / "nested"
    nested.mkdir()
    result = service.set_data_dir(str(nested))
    assert result["ok"] is False
    assert "不能位于当前数据目录内部" in result["error"]


def test_migration_copies_data_and_writes_pointer(service, tmp_path: Path, data_root: Path) -> None:
    target = tmp_path / "migrated"
    service._run_migration(str(target))  # noqa: SLF001

    status = service.migration_status()
    assert status["status"] == "done", status.get("error")
    assert status["percent"] == 100
    assert (target / "models.json").is_file()
    assert (target / "works" / "a.wav").is_file()
    # temp 属于易失目录，不参与迁移
    assert not (target / "temp").exists()
    marker = target / config.DATA_MARKER_FILE
    assert "migrated_from" in marker.read_text(encoding="utf-8")
    # 旧目录留下待清理标记，供下次启动处理
    assert (data_root / config.DATA_MIGRATION_MARKER).is_file()
    assert service.switched == [target.resolve()]  # type: ignore[attr-defined]


def test_migration_reports_failure_when_target_is_inside_source(service, data_root: Path) -> None:
    nested = data_root / "nested"
    nested.mkdir()
    service._run_migration(str(nested))  # noqa: SLF001

    status = service.migration_status()
    assert status["status"] == "failed"
    assert status["error"]


def test_start_migration_is_blocked_when_api_is_running(service, tmp_path: Path) -> None:
    service.api["running"] = True  # type: ignore[attr-defined]
    result = service.start_migration(str(tmp_path / "target"))
    assert result["ok"] is False
    assert "API 服务" in result["error"]
