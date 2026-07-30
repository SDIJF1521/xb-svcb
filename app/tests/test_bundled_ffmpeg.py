from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from infrastructure.ffmpeg_tool import FfmpegTool


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


def test_mix_brings_vocal_forward_and_limits_true_peak_headroom(
    tmp_path: Path, monkeypatch
) -> None:
    tool = FfmpegTool()
    tool.ffmpeg = "ffmpeg"
    vocals = tmp_path / "vocals.wav"
    instrumental = tmp_path / "instrumental.wav"
    output = tmp_path / "output.wav"
    vocals.write_bytes(b"vocal")
    instrumental.write_bytes(b"music")
    captured: list[str] = []

    def fake_run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        captured.extend(command)
        output.write_bytes(b"mixed")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("infrastructure.ffmpeg_tool.subprocess.run", fake_run)

    assert tool.mix(vocals, instrumental, output)
    filter_graph = captured[captured.index("-filter_complex") + 1]
    assert "volume=1.230269[v]" in filter_graph
    assert "volume=0.922571[m]" in filter_graph
    assert "amix=inputs=2:duration=longest:normalize=0" in filter_graph
    assert "alimiter=limit=0.841395" in filter_graph
    assert "level=false" in filter_graph


def test_adaptive_mix_profile_places_enhanced_vocal_under_music(
    tmp_path: Path, monkeypatch
) -> None:
    tool = FfmpegTool()
    tool.ffmpeg = "ffmpeg"
    vocals = tmp_path / "vocals.wav"
    instrumental = tmp_path / "instrumental.wav"
    vocals.write_bytes(b"vocal")
    instrumental.write_bytes(b"music")

    def fake_run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        measured = "-13.91" if str(vocals) in command else "-12.89"
        payload = f'{{"input_i": "{measured}", "input_tp": "-1.0"}}'
        return subprocess.CompletedProcess(command, 0, "", payload)

    monkeypatch.setattr("infrastructure.ffmpeg_tool.subprocess.run", fake_run)

    profile = tool.adaptive_mix_profile(vocals, instrumental)

    assert profile["adaptive"] is True
    assert profile["vocal_lufs"] == -13.91
    assert profile["instrumental_lufs"] == -12.89
    assert profile["vocal_gain_db"] == pytest.approx(-1.5532)
    assert profile["instrumental_gain_db"] == pytest.approx(-0.0732)


def test_adaptive_mix_profile_uses_quiet_fallback_when_measurement_fails(
    tmp_path: Path, monkeypatch
) -> None:
    tool = FfmpegTool()
    tool.ffmpeg = "ffmpeg"
    vocals = tmp_path / "vocals.wav"
    instrumental = tmp_path / "instrumental.wav"
    vocals.write_bytes(b"vocal")
    instrumental.write_bytes(b"music")
    monkeypatch.setattr(
        "infrastructure.ffmpeg_tool.subprocess.run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 1, "", "failed"),
    )

    profile = tool.adaptive_mix_profile(vocals, instrumental)

    assert profile["adaptive"] is False
    assert profile["vocal_gain_db"] == -1.0
    assert profile["instrumental_gain_db"] == 0.0


def test_mix_can_apply_light_parallel_glue(tmp_path: Path, monkeypatch) -> None:
    tool = FfmpegTool()
    tool.ffmpeg = "ffmpeg"
    vocals = tmp_path / "vocals.wav"
    instrumental = tmp_path / "instrumental.wav"
    output = tmp_path / "output.wav"
    vocals.write_bytes(b"vocal")
    instrumental.write_bytes(b"music")
    captured: list[str] = []

    def fake_run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        captured.extend(command)
        output.write_bytes(b"mixed")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("infrastructure.ffmpeg_tool.subprocess.run", fake_run)

    assert tool.mix(
        vocals,
        instrumental,
        output,
        vocal_gain_db=-1.55,
        instrumental_gain_db=-0.07,
        glue=True,
    )
    filter_graph = captured[captured.index("-filter_complex") + 1]
    assert "volume=0.836566[v]" in filter_graph
    assert "volume=0.991973[m]" in filter_graph
    assert "acompressor=threshold=0.251189:ratio=1.180" in filter_graph
    assert "detection=rms:mix=0.55[glue]" in filter_graph
    assert "[glue]alimiter=limit=0.841395" in filter_graph
