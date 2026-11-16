"""高音声码器补偿（worker + 适配器 + 保护钩子）的单元测试。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

import config
from application.conversion_service import ConversionService
from domain import InferenceParams
from infrastructure import high_note_vocoder
from infrastructure import high_note_vocoder_worker as worker


SR = 44100


# ---------------------------------------------------------------- worker 工具


def test_parse_regions_merges_and_clips_to_duration(tmp_path: Path) -> None:
    path = tmp_path / "regions.json"
    path.write_text(
        json.dumps(
            [
                {"start": 0.5, "end": 1.0},
                {"start": 1.005, "end": 2.0},
                {"start": 2.5, "end": 9.0},
                [3.0, 4.0],
            ]
        ),
        encoding="utf-8",
    )

    regions = worker._parse_regions(path, 3.5)

    assert regions[0] == pytest.approx((0.5, 2.0))
    assert regions[1] == pytest.approx((2.5, 3.5))


def test_parse_regions_accepts_report_payload_and_missing_file(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps({"regions": [{"start": 0.2, "end": 0.4}]}), encoding="utf-8"
    )
    assert worker._parse_regions(report, 5.0) == [pytest.approx((0.2, 0.4))]
    assert worker._parse_regions(tmp_path / "absent.json", 5.0) == []
    assert worker._parse_regions(None, 5.0) == []


def test_pick_f0_uses_fallback_and_corrects_octave_errors() -> None:
    primary = np.array([0.0, 1600.0, 3200.0, 50.0])
    clarity = np.array([0.0, 0.9, 0.9, 0.9])
    secondary = np.array([800.0, 800.0, 800.0, 800.0])
    secondary_clarity = np.array([0.8, 0.8, 0.8, 0.8])

    filled, _clarity = worker._pick_f0(
        primary,
        clarity,
        secondary,
        secondary_clarity,
        fmin=800.0,
        fmax=2000.0,
    )

    assert filled[0] == pytest.approx(800.0)  # 成品缺失帧取干声兜底
    assert filled[1] == pytest.approx(1600.0)  # 带内保留
    assert filled[2] == pytest.approx(1600.0)  # 3200Hz 高八度折回
    assert filled[3] == pytest.approx(800.0)  # 过低频率按八度补到带内


def test_hold_unvoiced_fills_gaps_from_neighbouring_notes() -> None:
    f0 = np.array([0.0, 900.0, 0.0, 950.0, 0.0])
    clarity = np.array([0.0, 0.9, 0.0, 0.9, 0.0])

    filled = worker._hold_unvoiced(f0, clarity)

    assert np.all(filled > 0.0)
    assert filled[2] == pytest.approx(900.0)


def test_gain_curve_matches_loudness_without_pumping() -> None:
    reference = np.full(4096, 0.2)
    synth = np.full(4096, 0.1)

    curve = worker._gain_curve(reference, synth, 1024, 256)
    spread = worker._spread(curve, reference.size)

    assert curve.size >= 2
    assert np.all(curve <= 2.5 + 1e-9)
    assert spread.size == reference.size
    assert float(np.median(spread)) == pytest.approx(2.0, rel=0.05)


def test_band_metrics_separates_harmonics_from_noise() -> None:
    t = np.arange(8192) / SR
    harmonic = sum(np.sin(2 * np.pi * freq * t) for freq in (7000.0, 8000.0, 9000.0))
    noise = np.random.default_rng(3).standard_normal(t.size)

    tonal = worker._band_metrics(harmonic * 0.05, SR, 6000.0)
    noisy = worker._band_metrics(noise * 0.05, SR, 6000.0)

    assert tonal["flatness"] < noisy["flatness"]
    assert tonal["prominence"] > 1.0


def test_accept_region_rejects_level_collapse_and_air_noise() -> None:
    t = np.arange(8192) / SR
    reference = (0.05 * np.sin(2 * np.pi * 7000.0 * t)).astype(np.float64)

    accepted, reason, _metrics = worker._accept_region(
        reference, reference * 0.9, SR, 6000.0
    )
    assert accepted and reason == "ok"

    accepted, reason, metrics = worker._accept_region(
        reference, reference * 40.0, SR, 6000.0
    )
    assert not accepted and "电平" in reason
    assert metrics["level_delta_db"] > 12.0

    rng = np.random.default_rng(5)
    accepted, reason, _metrics = worker._accept_region(
        reference, rng.standard_normal(reference.size) * 0.05, SR, 6000.0
    )
    assert not accepted

    accepted, reason, _metrics = worker._accept_region(
        np.zeros(reference.size), reference, SR, 6000.0
    )
    assert not accepted and "静音" in reason


def test_accept_region_rejects_isolated_whistle_but_keeps_harmonic_comb() -> None:
    rng = np.random.default_rng(9)
    t = np.arange(16384) / SR
    # 参考：噪声样高频带（平坦度高、无明显窄峰）
    reference = (rng.standard_normal(t.size) * 0.01).astype(np.float64)
    # 哨音：单个 9 kHz 窄峰
    whistle = (0.05 * np.sin(2 * np.pi * 9000.0 * t)).astype(np.float64)
    # 谐波列：780 Hz 的多个高频谐波
    comb = np.zeros_like(t)
    for harmonic in range(8, 21):
        comb += (0.02 / harmonic) * np.sin(2 * np.pi * 780.0 * harmonic * t)

    accepted, reason, metrics = worker._accept_region(reference, whistle, SR, 6000.0)
    assert not accepted and "窄带高频峰" in reason
    assert metrics["synth"]["peak_count"] < 4

    accepted, _reason, metrics = worker._accept_region(reference, comb, SR, 6000.0)
    assert metrics["synth"]["peak_count"] >= 4


def test_architecture_detection_and_hparams() -> None:
    assert worker._looks_snake({"snakes.0.prelu.weight": 1, "ups.0.weight": 2})
    assert worker._looks_snake({"snake_post.alpha": 1})
    assert not worker._looks_snake({"conv_pre.weight": 1, "ups.0.weight": 2})

    hps = worker._generator_hparams({"num_mels": 128, "sampling_rate": 44100})
    assert hps.inter_channels == 128
    assert hps.hop_size == 512
    assert hps.fmin == 40
    assert hps.fmax == 16000
    assert hps.gin_channels == 0

    with pytest.raises(RuntimeError):
        worker._generator_hparams({"sampling_rate": 44100})


def test_refine_without_regions_or_weights_is_a_quiet_noop(tmp_path: Path) -> None:
    rendered = tmp_path / "rendered.wav"
    rendered.write_bytes(b"placeholder")

    no_regions = worker.refine(
        rendered=rendered,
        dry=None,
        regions=[],
        output=tmp_path / "out.wav",
        weights_dir=tmp_path / "weights",
    )
    assert no_regions["applied"] is False
    assert "高音区" in no_regions["reason"]

    no_weights = worker.refine(
        rendered=rendered,
        dry=None,
        regions=[(0.2, 0.6)],
        output=tmp_path / "out.wav",
        weights_dir=None,
    )
    assert no_weights["applied"] is False
    assert "权重" in no_weights["reason"]


# ---------------------------------------------------------------- 适配器


def _patch_runtime(monkeypatch, tmp_path: Path) -> tuple[Path, Path, Path]:
    python = tmp_path / "python.exe"
    worker_script = tmp_path / "high_note_vocoder_worker.py"
    weights = tmp_path / "weights"
    for item in (python, worker_script):
        item.write_bytes(b"")
    weights.mkdir()
    (weights / "config.json").write_text("{}", encoding="utf-8")
    (weights / "model").write_bytes(b"")
    monkeypatch.setattr(config, "VOCAL_ENHANCEMENT_PYTHON", python)
    monkeypatch.setattr(config, "HIGH_NOTE_VOCODER_WORKER", worker_script)
    monkeypatch.setattr(config, "HIGH_NOTE_VOCODER_BAND_HZ", 6000.0)
    monkeypatch.setattr(config, "HIGH_NOTE_VOCODER_WET", 0.7)
    monkeypatch.setattr(
        config, "high_note_vocoder_weight_dir", lambda: weights, raising=True
    )
    monkeypatch.setattr(
        config, "high_note_vocoder_repos", lambda: [tmp_path / "so-vits-svc"]
    )
    return python, worker_script, weights


def test_processor_reports_unavailable_without_worker(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "VOCAL_ENHANCEMENT_PYTHON", None)
    processor = high_note_vocoder.HighNoteVocoderProcessor()

    assert processor.available is False
    result = processor.refine(
        rendered=tmp_path / "rendered.wav",
        dry=None,
        regions=[(0.1, 0.5)],
        destination=tmp_path / "vocoded.wav",
    )
    assert result["applied"] is False
    assert "不可用" in result["reason"]


def test_processor_builds_command_and_accepts_applied_report(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_runtime(monkeypatch, tmp_path)
    rendered = tmp_path / "restored.wav"
    dry = tmp_path / "dry.wav"
    rendered.write_bytes(b"audio")
    dry.write_bytes(b"audio")
    destination = tmp_path / "restored_vocoded.wav"
    captured: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        captured.append(command)
        report_path = Path(command[command.index("--report-json") + 1])
        report_path.write_text(
            json.dumps(
                {
                    "applied": True,
                    "architecture": "snake-hifigan",
                    "weights": "w/model",
                    "applied_seconds": 1.25,
                    "regions": [
                        {"start": 0.1, "end": 0.5, "status": "applied"}
                    ],
                }
            ),
            encoding="utf-8",
        )
        Path(command[command.index("--output") + 1]).write_bytes(b"vocoded")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("infrastructure.high_note_vocoder.subprocess.run", fake_run)

    result = high_note_vocoder.HighNoteVocoderProcessor().refine(
        rendered=rendered,
        dry=dry,
        regions=[(0.1, 0.5)],
        destination=destination,
        threshold=800.0,
    )

    assert result["applied"] is True
    assert Path(result["output"]) == destination
    assert result["architecture"] == "snake-hifigan"
    command = captured[0]
    assert command[0].endswith("python.exe")
    assert command[command.index("--dry-source") + 1] == str(dry)
    assert command[command.index("--band-hz") + 1] == "6000.0"
    assert command[command.index("--wet") + 1] == "0.700"
    assert float(command[command.index("--min-f0") + 1]) == pytest.approx(680.0)
    scope = json.loads(
        Path(command[command.index("--regions-json") + 1]).read_text(encoding="utf-8")
    )
    assert scope == [{"start": 0.1, "end": 0.5}]


def test_processor_ignores_output_when_worker_reports_no_apply(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_runtime(monkeypatch, tmp_path)
    rendered = tmp_path / "restored.wav"
    rendered.write_bytes(b"audio")
    destination = tmp_path / "restored_vocoded.wav"

    def fake_run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        report_path = Path(command[command.index("--report-json") + 1])
        report_path.write_text(
            json.dumps(
                {
                    "applied": False,
                    "reason": "所有区段均未通过验收，保留升调结果",
                    "regions": [{"start": 0.1, "end": 0.5, "status": "rejected"}],
                }
            ),
            encoding="utf-8",
        )
        destination.write_bytes(b"unused")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("infrastructure.high_note_vocoder.subprocess.run", fake_run)

    result = high_note_vocoder.HighNoteVocoderProcessor().refine(
        rendered=rendered,
        dry=None,
        regions=[(0.1, 0.5)],
        destination=destination,
        threshold=800.0,
    )

    assert result["applied"] is False
    assert "未通过验收" in result["reason"]


def test_processor_reports_missing_report(tmp_path: Path, monkeypatch) -> None:
    _patch_runtime(monkeypatch, tmp_path)
    rendered = tmp_path / "restored.wav"
    rendered.write_bytes(b"audio")

    def fake_run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "boom")

    monkeypatch.setattr("infrastructure.high_note_vocoder.subprocess.run", fake_run)

    result = high_note_vocoder.HighNoteVocoderProcessor().refine(
        rendered=rendered,
        dry=None,
        regions=[(0.1, 0.5)],
        destination=tmp_path / "vocoded.wav",
    )

    assert result["applied"] is False
    assert "未返回报告" in result["reason"]


# ---------------------------------------------------------------- 保护钩子


class _FakeFfmpeg:
    def __init__(self, report: dict) -> None:
        self._report = report
        self.calls: list[dict] = []

    def pitch_shift(self, _source: Path, target: Path, _semitones: int, **kwargs):
        self.calls.append(kwargs)
        target.write_bytes(b"restored")
        report_path = kwargs.get("report_path")
        if report_path is not None:
            Path(report_path).write_text(
                json.dumps(self._report), encoding="utf-8"
            )
        return True


class _FakeVocoder:
    def __init__(self, result: dict | None = None) -> None:
        self.available = True
        self.calls: list[dict] = []
        self._result = result or {}

    def refine(self, **kwargs):
        self.calls.append(kwargs)
        destination = Path(kwargs["destination"])
        if self._result.get("applied"):
            destination.write_bytes(b"vocoded")
        return {**self._result, "output": destination}


def _service(tmp_path: Path, report: dict, vocoder=None) -> ConversionService:
    service = ConversionService.__new__(ConversionService)
    service._ffmpeg = _FakeFfmpeg(report)
    service._log = lambda *_args: None
    service._high_note_vocoder = vocoder
    return service


def test_restore_guard_returns_vocoded_band_when_accepted(tmp_path: Path) -> None:
    report = {"region_count": 1, "regions": [{"start": 0.4, "end": 0.9}]}
    vocoder = _FakeVocoder(
        {"applied": True, "architecture": "snake-hifigan", "applied_seconds": 0.5}
    )
    service = _service(tmp_path, report, vocoder)
    rendered = tmp_path / "restored_retry1.wav"
    rendered.write_bytes(b"restored")
    destination = tmp_path / "restored_out.wav"

    result = service._restore_high_pitch_guard(
        tmp_path / "raw.wav",
        destination,
        tmp_path / "dry.wav",
        InferenceParams(auto_high_pitch_guard=True),
        tmp_path / "run.log",
        threshold=800.0,
    )

    assert Path(result).name == "restored_out_vocoded.wav"
    assert vocoder.calls[0]["regions"] == [(0.4, 0.9)]
    assert vocoder.calls[0]["threshold"] == pytest.approx(800.0)


def test_restore_guard_keeps_psola_result_when_vocoder_skips(tmp_path: Path) -> None:
    report = {"region_count": 1, "regions": [{"start": 0.4, "end": 0.9}]}
    vocoder = _FakeVocoder({"applied": False, "reason": "所有区段均未通过验收"})
    service = _service(tmp_path, report, vocoder)
    destination = tmp_path / "restored_out.wav"

    result = service._restore_high_pitch_guard(
        tmp_path / "raw.wav",
        destination,
        tmp_path / "dry.wav",
        InferenceParams(auto_high_pitch_guard=True),
        tmp_path / "run.log",
        threshold=800.0,
    )

    assert Path(result) == destination
    assert vocoder.calls


def test_restore_guard_scope_filters_regions_outside_confirmed_core(
    tmp_path: Path,
) -> None:
    report = {"region_count": 1, "regions": [{"start": 3.0, "end": 3.5}]}
    vocoder = _FakeVocoder({"applied": True})
    service = _service(tmp_path, report, vocoder)
    destination = tmp_path / "restored_out.wav"

    result = service._restore_high_pitch_guard(
        tmp_path / "raw.wav",
        destination,
        tmp_path / "dry.wav",
        InferenceParams(auto_high_pitch_guard=True),
        tmp_path / "run.log",
        threshold=800.0,
        only_regions=[(0.2, 0.6)],
    )

    assert Path(result) == destination
    assert vocoder.calls == []


def test_restore_guard_skips_vocoder_when_port_unavailable(tmp_path: Path) -> None:
    report = {"region_count": 1, "regions": [{"start": 0.4, "end": 0.9}]}
    vocoder = _FakeVocoder({"applied": True})
    vocoder.available = False
    service = _service(tmp_path, report, vocoder)
    destination = tmp_path / "restored_out.wav"

    result = service._restore_high_pitch_guard(
        tmp_path / "raw.wav",
        destination,
        tmp_path / "dry.wav",
        InferenceParams(auto_high_pitch_guard=True),
        tmp_path / "run.log",
        threshold=800.0,
    )

    assert Path(result) == destination
    assert vocoder.calls == []


def test_restore_guard_ignores_vocoder_failure(tmp_path: Path) -> None:
    report = {"region_count": 1, "regions": [{"start": 0.4, "end": 0.9}]}

    class _Exploding(_FakeVocoder):
        def refine(self, **kwargs):
            raise RuntimeError("声码器炸了")

    service = _service(tmp_path, report, _Exploding())
    destination = tmp_path / "restored_out.wav"

    result = service._restore_high_pitch_guard(
        tmp_path / "raw.wav",
        destination,
        tmp_path / "dry.wav",
        InferenceParams(auto_high_pitch_guard=True),
        tmp_path / "run.log",
        threshold=800.0,
    )

    assert Path(result) == destination


def test_editor_restore_guard_also_refines_high_band(tmp_path: Path) -> None:
    from application.audio_editor_service import AudioEditorService

    report = {"region_count": 1, "regions": [{"start": 0.4, "end": 0.9}]}
    service = AudioEditorService.__new__(AudioEditorService)
    service._ffmpeg = _FakeFfmpeg(report)
    service._high_note_vocoder = _FakeVocoder(
        {"applied": True, "architecture": "snake-hifigan", "applied_seconds": 0.5}
    )
    service._model_high_pitch_threshold = lambda *_args, **_kwargs: 800.0
    destination = tmp_path / "clip_restored.wav"

    result = service._restore_high_pitch_guard(
        tmp_path / "raw.wav",
        destination,
        tmp_path / "dry.wav",
        InferenceParams(auto_high_pitch_guard=True),
    )

    assert Path(result).name == "clip_restored_vocoded.wav"
    assert service._high_note_vocoder.calls[0]["regions"] == [(0.4, 0.9)]
