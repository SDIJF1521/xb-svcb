from __future__ import annotations

import os
import struct
import subprocess
import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from infrastructure.ffmpeg_tool import FfmpegTool


def _write_test_wav(path: Path, amplitude: int) -> None:
    samples = [int(amplitude)] * 8000
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


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


def test_mix_keeps_vocal_below_backing_and_limits_true_peak_headroom(
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
    # 默认人声低于伴奏（人声 -1.0 dB / 伴奏 -0.5 dB），避免窄带人声盖住全频段伴奏
    assert tool.DEFAULT_VOCAL_GAIN_DB < tool.DEFAULT_INSTRUMENTAL_GAIN_DB
    assert "volume=0.891251[v]" in filter_graph
    assert "volume=0.944061[m]" in filter_graph
    # 人声总线收敛：切次低频 + 轻微收敛 3 kHz 贴脸感
    assert "highpass=f=65" in filter_graph
    assert "equalizer=f=3000:t=q:w=1.2:g=-1" in filter_graph
    assert "amix=inputs=2:duration=longest:normalize=0" in filter_graph
    assert "alimiter=limit=0.841395" in filter_graph
    assert "level=false" in filter_graph


def test_adaptive_mix_profile_keeps_vocal_just_below_backing(
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
    assert profile["instrumental_gain_db"] == pytest.approx(-0.0732)
    # 混合后的人声响度应比伴奏低 1 LU（不盖过伴奏）
    vocal_after = float(profile["vocal_lufs"]) + float(profile["vocal_gain_db"])  # type: ignore[arg-type]
    music_after = float(profile["instrumental_lufs"]) + float(  # type: ignore[arg-type]
        profile["instrumental_gain_db"]
    )
    assert vocal_after - music_after == pytest.approx(
        FfmpegTool.ADAPTIVE_VOCAL_OVER_MUSIC_DB
    )
    assert vocal_after - music_after == pytest.approx(-1.0)


def test_adaptive_mix_profile_uses_balanced_fallback_when_measurement_fails(
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
    assert profile["vocal_gain_db"] == FfmpegTool.DEFAULT_VOCAL_GAIN_DB
    assert profile["instrumental_gain_db"] == FfmpegTool.DEFAULT_INSTRUMENTAL_GAIN_DB
    assert tool.DEFAULT_VOCAL_GAIN_DB < tool.DEFAULT_INSTRUMENTAL_GAIN_DB


@pytest.mark.parametrize(
    ("vocal_lufs", "music_lufs", "expected_gain"),
    [
        (-22.0, -12.0, 3.0),
        (-9.0, -14.0, -5.94),
    ],
)
def test_adaptive_mix_profile_bounds_extreme_vocal_gain(
    tmp_path: Path,
    monkeypatch,
    vocal_lufs: float,
    music_lufs: float,
    expected_gain: float,
) -> None:
    tool = FfmpegTool()
    tool.ffmpeg = "ffmpeg"
    vocals = tmp_path / "vocals.wav"
    instrumental = tmp_path / "instrumental.wav"
    vocals.write_bytes(b"vocal")
    instrumental.write_bytes(b"music")

    def fake_run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        measured = vocal_lufs if str(vocals) in command else music_lufs
        payload = f'{{"input_i": "{measured}", "input_tp": "-1.0"}}'
        return subprocess.CompletedProcess(command, 0, "", payload)

    monkeypatch.setattr("infrastructure.ffmpeg_tool.subprocess.run", fake_run)

    profile = tool.adaptive_mix_profile(vocals, instrumental)

    assert profile["vocal_gain_db"] == pytest.approx(expected_gain)


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


def test_mix_vocals_compensates_stereo_chorus_energy(
    tmp_path: Path, monkeypatch
) -> None:
    tool = FfmpegTool()
    tool.ffmpeg = "ffmpeg"
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    output = tmp_path / "chorus.wav"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    captured: list[str] = []

    def fake_run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        captured.extend(command)
        output.write_bytes(b"chorus")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("infrastructure.ffmpeg_tool.subprocess.run", fake_run)

    assert tool.mix_vocals([first, second], output)
    filter_graph = captured[captured.index("-filter_complex") + 1]
    assert "volume=1.1200[d0]" in filter_graph
    assert "volume=1.1200[d1]" in filter_graph
    assert "amix=inputs=2:duration=longest:normalize=0" in filter_graph
    assert "alimiter=limit=0.97" in filter_graph


def test_pitch_shift_rejects_collapsed_worker_output(
    tmp_path: Path, monkeypatch
) -> None:
    tool = FfmpegTool()
    source = tmp_path / "source.wav"
    output = tmp_path / "output.wav"
    worker_python = tmp_path / "python.exe"
    worker_script = tmp_path / "formant_pitch_worker.py"
    worker_python.write_bytes(b"")
    worker_script.write_bytes(b"")
    _write_test_wav(source, 12000)
    monkeypatch.setattr(config, "VOCAL_ENHANCEMENT_PYTHON", worker_python)
    monkeypatch.setattr(config, "FORMANT_PITCH_WORKER", worker_script)

    def fake_run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        target = Path(command[command.index("--output") + 1])
        _write_test_wav(target, 0)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("infrastructure.ffmpeg_tool.subprocess.run", fake_run)

    assert not tool.pitch_shift(source, output, -7)
