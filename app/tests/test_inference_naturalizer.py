from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure.inference_naturalizer import naturalize_inference_output
from infrastructure.inference_naturalizer import _source_guided_high_band_repair
from infrastructure.seedvc_engine import SeedVcEngine


@pytest.fixture
def audio_backend(monkeypatch: pytest.MonkeyPatch):
    files: dict[str, tuple[np.ndarray, int, str]] = {}

    def write(path, data, sample_rate, *, subtype="FLOAT", **_kwargs):
        array = np.asarray(data, dtype=np.float32)
        if array.ndim == 1:
            array = array[:, np.newaxis]
        files[str(path)] = (array.copy(), int(sample_rate), str(subtype))

    def read(path, *, always_2d=False, **_kwargs):
        data, sample_rate, _subtype = files[str(path)]
        result = data.copy()
        if not always_2d and result.shape[1] == 1:
            result = result[:, 0]
        return result, sample_rate

    def info(path):
        _data, _sample_rate, subtype = files[str(path)]
        return SimpleNamespace(subtype=subtype)

    backend = SimpleNamespace(write=write, read=read, info=info)
    monkeypatch.setitem(sys.modules, "soundfile", backend)
    return backend


def _tone(sample_rate: int, seconds: float, amplitude: float, frequency: float = 220.0) -> np.ndarray:
    time = np.arange(round(sample_rate * seconds), dtype=np.float64) / sample_rate
    return (amplitude * np.sin(2.0 * np.pi * frequency * time)).astype(np.float32)


def _rms(signal: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(signal.astype(np.float64))) + 1e-16))


def test_naturalizer_preserves_short_intra_phrase_pause(tmp_path: Path, audio_backend) -> None:
    sample_rate = 16000
    source = _tone(sample_rate, 1.4, 0.12)
    source[int(0.60 * sample_rate) : int(0.82 * sample_rate)] = 0.0
    converted = _tone(sample_rate, 1.4, 0.10)
    source_path = tmp_path / "source.wav"
    output_path = tmp_path / "converted.wav"
    audio_backend.write(source_path, source, sample_rate, subtype="FLOAT")
    audio_backend.write(output_path, converted, sample_rate, subtype="FLOAT")

    stats = naturalize_inference_output(source_path, output_path, "rvc")
    processed, _ = audio_backend.read(output_path)

    pause = processed[int(0.64 * sample_rate) : int(0.78 * sample_rate)]
    before = processed[int(0.40 * sample_rate) : int(0.54 * sample_rate)]
    assert stats["short_gaps"] >= 1
    assert _rms(pause) >= _rms(before) * 0.92


def test_naturalizer_restores_long_digital_silence(tmp_path: Path, audio_backend) -> None:
    sample_rate = 16000
    source = np.concatenate(
        [
            np.zeros(sample_rate, dtype=np.float32),
            _tone(sample_rate, 1.0, 0.12),
        ]
    )
    converted = np.concatenate(
        [
            _tone(sample_rate, 1.0, 0.0015, frequency=70.0),
            _tone(sample_rate, 1.0, 0.10),
        ]
    )
    source_path = tmp_path / "source.wav"
    output_path = tmp_path / "converted.wav"
    audio_backend.write(source_path, source, sample_rate, subtype="FLOAT")
    audio_backend.write(output_path, converted, sample_rate, subtype="FLOAT")

    stats = naturalize_inference_output(source_path, output_path, "ddsp-svc")
    processed, _ = audio_backend.read(output_path)

    assert stats["exact_silence_seconds"] >= 0.9
    assert np.count_nonzero(processed[int(0.15 * sample_rate) : int(0.75 * sample_rate)]) == 0
    assert _rms(processed[int(1.20 * sample_rate) : int(1.80 * sample_rate)]) > 0.05


def test_naturalizer_restores_bounded_source_microdynamics(tmp_path: Path, audio_backend) -> None:
    sample_rate = 16000
    source = np.concatenate(
        [
            _tone(sample_rate, 1.0, 0.04),
            _tone(sample_rate, 1.0, 0.16),
        ]
    )
    converted = np.concatenate(
        [
            _tone(sample_rate, 1.0, 0.10),
            _tone(sample_rate, 1.0, 0.10),
        ]
    )
    source_path = tmp_path / "source.wav"
    output_path = tmp_path / "converted.wav"
    audio_backend.write(source_path, source, sample_rate, subtype="FLOAT")
    audio_backend.write(output_path, converted[:-123], sample_rate, subtype="FLOAT")

    stats = naturalize_inference_output(source_path, output_path, "so-vits-svc")
    processed, output_rate = audio_backend.read(output_path, always_2d=True)

    quiet = _rms(processed[int(0.20 * sample_rate) : int(0.80 * sample_rate), 0])
    loud = _rms(processed[int(1.20 * sample_rate) : int(1.80 * sample_rate), 0])
    assert output_rate == sample_rate
    assert len(processed) == len(converted)
    assert stats["duration_adjustment_ms"] > 0.0
    assert loud > quiet * 1.10
    assert -1.3 <= stats["dynamic_min_db"] <= 0.0
    assert 0.0 <= stats["dynamic_max_db"] <= 0.8
    assert float(np.max(np.abs(processed))) <= 0.999


def test_seedvc_quality_range_avoids_low_step_artifacts() -> None:
    assert SeedVcEngine._diffusion_steps(0.0) == 20
    assert SeedVcEngine._diffusion_steps(0.5) == 35
    assert SeedVcEngine._diffusion_steps(1.0) == 50


def test_source_guided_high_band_repair_only_attenuates_unsupported_burst() -> None:
    sample_rate = 24000
    time = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    source = 0.16 * np.sin(2.0 * np.pi * 220.0 * time)
    output = source.copy()
    burst = (time >= 0.80) & (time < 0.90)
    output[burst] += 0.12 * np.sin(2.0 * np.pi * 8200.0 * time[burst])

    repaired, stats = _source_guided_high_band_repair(
        source[:, np.newaxis],
        output[:, np.newaxis],
        sample_rate,
        sample_rate,
        "so-vits-svc",
    )

    from scipy.signal import butter, sosfiltfilt

    highpass = butter(4, 5600.0, btype="highpass", fs=sample_rate, output="sos")
    core = (time >= 0.82) & (time < 0.88)
    before_high = sosfiltfilt(highpass, output)[core]
    after_high = sosfiltfilt(highpass, repaired[:, 0])[core]
    bodypass = butter(4, [180.0, 4800.0], btype="bandpass", fs=sample_rate, output="sos")
    before_body = sosfiltfilt(bodypass, output)[core]
    after_body = sosfiltfilt(bodypass, repaired[:, 0])[core]

    assert stats["guarded_frames"] > 0.0
    assert np.sqrt(np.mean(after_high**2)) < np.sqrt(np.mean(before_high**2)) * 0.40
    assert np.sqrt(np.mean(after_body**2)) > np.sqrt(np.mean(before_body**2)) * 0.85
