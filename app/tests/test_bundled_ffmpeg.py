from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config


def test_bundled_ffmpeg_is_added_when_system_command_is_missing(
    tmp_path: Path, monkeypatch
) -> None:
    bin_dir = tmp_path / "tools" / "ffmpeg" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "ffmpeg.exe").write_bytes(b"bundled")

    monkeypatch.setattr(config, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(config.shutil, "which", lambda _name: None)
    monkeypatch.setenv("PATH", r"C:\Windows\System32")
    monkeypatch.delenv("XB_FFMPEG_DIR", raising=False)
    monkeypatch.delenv("FFMPEG_HOME", raising=False)

    result = config._activate_bundled_ffmpeg()

    assert result == bin_dir
    assert os.environ["PATH"].split(os.pathsep)[0] == str(bin_dir)
    assert os.environ["XB_FFMPEG_DIR"] == str(bin_dir.parent)
    assert os.environ["FFMPEG_HOME"] == str(bin_dir.parent)


def test_system_ffmpeg_keeps_existing_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(config.shutil, "which", lambda _name: r"C:\Tools\ffmpeg.exe")
    monkeypatch.setenv("PATH", r"C:\Tools")

    assert config._activate_bundled_ffmpeg() is None
    assert os.environ["PATH"] == r"C:\Tools"
