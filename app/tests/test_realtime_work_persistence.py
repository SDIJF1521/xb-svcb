import os
import time
from pathlib import Path

import config
from application.work_service import WorkService
from infrastructure.storage import ListRepository, SettingsStore


class _UnusedConversion:
    pass


class _UnusedModels:
    pass


def _service(tmp_path: Path, monkeypatch) -> WorkService:  # noqa: ANN001
    data = tmp_path / "data"
    monkeypatch.setattr(config, "WORKS_DIR", data / "works")
    monkeypatch.setattr(config, "TEMP_DIR", data / "temp")
    monkeypatch.setattr(config, "WORKS_DB", data / "works.json")
    monkeypatch.setattr(config, "SETTINGS_DB", data / "settings.json")
    return WorkService(
        ListRepository(config.WORKS_DB),
        _UnusedConversion(),
        _UnusedModels(),
        SettingsStore(config.SETTINGS_DB),
    )


def test_realtime_output_is_archived_as_playable_work(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    session_dir = config.TEMP_DIR / "realtime-covers" / "live_123"
    stems = session_dir / "stems"
    stems.mkdir(parents=True)
    (session_dir / "realtime-cover.wav").write_bytes(b"RIFF-real-time")
    (session_dir / "chunk_00000.wav").write_bytes(b"chunk")
    (session_dir / "realtime.log").write_text("done", encoding="utf-8")
    (stems / "vocals.wav").write_bytes(b"vocals")

    work = service.register_realtime_output(
        {
            "status": "done",
            "title": "测试歌曲",
            "source_path": "C:/music/source.wav",
            "output_path": str(session_dir / "realtime-cover.wav"),
            "duration": 125.4,
            "mode": "multi",
            "model_ids": ["rvc-a", "seed-b"],
            "model_names": ["RVC A", "Seed B"],
            "segments": [{"start": 0, "end": 5, "model_ids": ["rvc-a", "seed-b"]}],
        }
    )

    assert work is not None
    assert work["status"] == "done"
    assert work["duration"] == "02:05"
    output = Path(work["output_path"])
    assert output.is_file()
    assert Path(work["log_path"]).is_file()
    assert work["mode"] == "multi"
    assert work["realtime_session_id"] == "live_123"
    assert service.get(work["id"])["output_path"] == str(output)

    cache = config.TEMP_DIR / f"{work['id']}_output.mp3"
    cache.write_bytes(b"cached preview")

    assert service.remove(work["id"]) is True
    assert not output.parent.parent.exists()
    assert not session_dir.exists()
    assert not cache.exists()


def test_realtime_work_cannot_be_retried(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    session_dir = config.TEMP_DIR / "realtime-covers" / "live_retry"
    session_dir.mkdir(parents=True)
    output = session_dir / "realtime-cover.wav"
    output.write_bytes(b"RIFF-real-time")
    work = service.register_realtime_output(
        {
            "status": "done",
            "output_path": str(output),
            "duration": 1,
        }
    )

    assert work is not None
    assert service.retry(work["id"]) is False


def test_list_removes_orphan_realtime_work_directories(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    orphan = config.WORKS_DIR / "wrk_orphan"
    orphan.mkdir(parents=True)
    (orphan / "output.wav").write_bytes(b"orphan")

    assert service.list() == []
    assert not orphan.exists()


def test_list_removes_orphan_temp_cache_and_stale_realtime_session(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    config.TEMP_DIR.mkdir(parents=True)
    orphan_cache = config.TEMP_DIR / "wrk_deleted_output.mp3"
    orphan_cache.write_bytes(b"orphan preview")
    stale_session = config.TEMP_DIR / "realtime-covers" / "live_deleted"
    stale_session.mkdir(parents=True)
    (stale_session / "realtime-cover.wav").write_bytes(b"stale")
    old = time.time() - 7 * 60 * 60
    os.utime(stale_session, (old, old))

    assert service.list() == []
    assert not orphan_cache.exists()
    assert not stale_session.exists()


def test_list_preserves_recent_unarchived_realtime_session(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    active_session = config.TEMP_DIR / "realtime-covers" / "live_active"
    active_session.mkdir(parents=True)
    (active_session / "chunk_00000.wav").write_bytes(b"active")

    assert service.list() == []
    assert active_session.exists()


def test_list_preserves_temp_files_referenced_by_existing_work(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    service._repo.add(
        {
            "id": "wrk_keep",
            "title": "保留作品",
            "created_at": "2026-01-01T00:00:00",
            "realtime_session_id": "live_keep",
        }
    )
    config.TEMP_DIR.mkdir(parents=True)
    cache = config.TEMP_DIR / "wrk_keep_output.mp3"
    cache.write_bytes(b"referenced preview")
    session = config.TEMP_DIR / "realtime-covers" / "live_keep"
    session.mkdir(parents=True)
    (session / "realtime-cover.wav").write_bytes(b"referenced session")
    old = time.time() - 7 * 60 * 60
    os.utime(session, (old, old))

    assert [item["id"] for item in service.list()] == ["wrk_keep"]
    assert cache.exists()
    assert session.exists()
