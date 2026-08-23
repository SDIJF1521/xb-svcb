from __future__ import annotations

from pathlib import Path

import config
from infrastructure import paths


def test_clear_temp_directory_removes_all_contents_but_keeps_directory(
    tmp_path: Path, monkeypatch
) -> None:
    data_root = tmp_path / "data"
    temp_root = data_root / "temp"
    (temp_root / "realtime-covers" / "session").mkdir(parents=True)
    (temp_root / "realtime-covers" / "session" / "chunk.wav").write_bytes(b"audio")
    (temp_root / "preview.mp3").write_bytes(b"preview")
    monkeypatch.setattr(config, "DATA_DIR", data_root)
    monkeypatch.setattr(config, "TEMP_DIR", temp_root)

    assert paths.clear_temp_directory() is True
    assert temp_root.is_dir()
    assert list(temp_root.iterdir()) == []


def test_clear_temp_directory_rejects_a_path_outside_data_root(
    tmp_path: Path, monkeypatch
) -> None:
    data_root = tmp_path / "data"
    unsafe = tmp_path / "temp"
    unsafe.mkdir()
    (unsafe / "keep.txt").write_text("keep", encoding="utf-8")
    monkeypatch.setattr(config, "DATA_DIR", data_root)
    monkeypatch.setattr(config, "TEMP_DIR", unsafe)

    assert paths.clear_temp_directory() is False
    assert (unsafe / "keep.txt").is_file()
