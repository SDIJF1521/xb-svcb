from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from application.conversion_service import ConversionService, default_steps, default_steps_multi
from application.audio_editor_service import AudioEditorService
from application.work_service import WorkService
from domain import InferenceParams
from infrastructure.storage import ListRepository, SettingsStore
from infrastructure.vocal_enhancement import VocalEnhancementProcessor
from infrastructure import formant_pitch_worker, vocal_enhancement_worker, vocal_tuning_worker


def test_optional_pipeline_step_is_inserted_before_mix() -> None:
    assert [step["key"] for step in default_steps()] == [
        "separate",
        "repair_input",
        "f0",
        "infer",
        "repair_output",
        "mix",
    ]
    assert [step["key"] for step in default_steps(True)] == [
        "separate",
        "repair_input",
        "f0",
        "infer",
        "repair_output",
        "enhance",
        "mix",
    ]
    assert [step["key"] for step in default_steps_multi(True)] == [
        "separate",
        "repair_input",
        "split",
        "infer",
        "merge",
        "repair_output",
        "enhance",
        "mix",
    ]


def test_work_service_normalizes_levels_and_disables_manual_merge() -> None:
    assert WorkService._vocal_enhancement(
        {"vocal_enhancement": {"enabled": True, "level": "advanced"}},
        "auto_mix",
    ) == {
        "enabled": True,
        "level": "advanced",
        "pitch_correction": 0.45,
        "timing_alignment": 0.45,
        "timbre_focus": 0.60,
        "ai_eq": 0.55,
        "ai_compressor": 0.45,
        "ai_exciter": 0.25,
        "stereo_width": 0.30,
        "loudness_envelope": 0.58,
    }
    assert WorkService._vocal_enhancement(
        {"vocal_enhancement": {"enabled": True, "level": "unknown"}},
        "auto_mix",
    ) == {
        "enabled": True,
        "level": "basic",
        "pitch_correction": 0.45,
        "timing_alignment": 0.45,
        "timbre_focus": 0.60,
        "ai_eq": 0.55,
        "ai_compressor": 0.45,
        "ai_exciter": 0.25,
        "stereo_width": 0.30,
        "loudness_envelope": 0.58,
    }
    assert WorkService._vocal_enhancement(
        {
            "vocal_enhancement": {
                "enabled": True,
                "level": "advanced",
                "pitch_correction": 2.0,
                "timing_alignment": -1.0,
                "timbre_focus": -1.0,
                "ai_eq": 2.0,
                "ai_compressor": -1.0,
                "ai_exciter": "invalid",
                "stereo_width": float("nan"),
                "loudness_envelope": 2.0,
            }
        },
        "manual_vocal_merge",
    ) == {
        "enabled": False,
        "level": "advanced",
        "pitch_correction": 1.0,
        "timing_alignment": 0.0,
        "timbre_focus": 0.0,
        "ai_eq": 1.0,
        "ai_compressor": 0.0,
        "ai_exciter": 0.25,
        "stereo_width": 0.30,
        "loudness_envelope": 1.0,
    }


def test_multi_model_high_pitch_guard_is_carried_per_model(tmp_path: Path, monkeypatch) -> None:
    class _QueuedConversion:
        def start(self, _work_id: str) -> None:
            return

    class _Models:
        items = {
            "model_a": {"id": "model_a", "name": "A", "framework": "rvc"},
            "model_b": {"id": "model_b", "name": "B", "framework": "so-vits-svc"},
        }

        def get(self, model_id: str):
            return self.items.get(model_id)

    monkeypatch.setattr(config, "WORKS_DIR", tmp_path / "works")
    repo = ListRepository(tmp_path / "works.json")
    service = WorkService(
        repo,
        _QueuedConversion(),
        _Models(),
        SettingsStore(tmp_path / "settings.json"),
    )

    work = service.create(
        {
            "mode": "multi",
            "source_path": str(tmp_path / "song.wav"),
            "params": {"auto_high_pitch_guard": False},
            "models": [
                {"model_id": "model_a", "params": {"auto_high_pitch_guard": True}},
                {"model_id": "model_b", "params": {}},
            ],
            "segments": [
                {"start": 0, "end": 4, "model_ids": ["model_a", "model_b"]},
            ],
        }
    )

    assert work["seg_models"]["model_a"]["params"]["auto_high_pitch_guard"] is True
    # A model without its own switch inherits the legacy top-level value.
    assert work["seg_models"]["model_b"]["params"]["auto_high_pitch_guard"] is False
    assert (
        ConversionService._multi_model_params(
            {"params": {}}, {"auto_high_pitch_guard": False}
        ).auto_high_pitch_guard
        is False
    )
    assert ConversionService._multi_model_params({}).auto_high_pitch_guard is True


def test_conversion_service_reads_all_enhancement_controls() -> None:
    enabled, level, controls = ConversionService._enhancement_settings(
        {
            "vocal_enhancement": {
                "enabled": True,
                "level": "advanced",
                "pitch_correction": 0.31,
                "timing_alignment": 0.48,
                "timbre_focus": 0.62,
                "ai_eq": 0.53,
                "ai_compressor": 0.44,
                "ai_exciter": 0.21,
                "stereo_width": 0.35,
                "loudness_envelope": 0.64,
            }
        }
    )

    assert enabled is True
    assert level == "advanced"
    assert controls == {
        "pitch_correction": 0.31,
        "timing_alignment": 0.48,
        "timbre_focus": 0.62,
        "ai_eq": 0.53,
        "ai_compressor": 0.44,
        "ai_exciter": 0.21,
        "stereo_width": 0.35,
        "loudness_envelope": 0.64,
    }


def test_high_range_profile_adapts_f0_and_transient_protection(tmp_path: Path) -> None:
    params = InferenceParams(
        f0_method="harvest",
        protect=0.33,
        filter_radius=5,
        manual_params_enabled=True,
    )
    logger = types.SimpleNamespace(_log=lambda *_args: None)
    fcpe_model = tmp_path / "pretrain" / "fcpe.pt"
    fcpe_model.parent.mkdir(parents=True)
    fcpe_model.write_bytes(b"fcpe")

    with patch.object(config, "SOVITS_REPO", tmp_path):
        ConversionService._adapt_high_range(
            logger,
            params,
            {
                "high_pitch": True,
                "high_frequency": True,
                "p95_f0_hz": 980.0,
                "high_band_ratio": 0.12,
                "recommended_f0_max": 1480.0,
            },
            tmp_path / "run.log",
            "so-vits-svc",
        )

    assert params.f0_method == "fcpe"
    assert params.filter_radius == 2
    assert params.protect == 0.28
    assert getattr(params, "adaptive_f0_max") == 1480.0


def test_high_range_adaptation_is_noop_when_guard_disabled(tmp_path: Path) -> None:
    params = InferenceParams(
        f0_method="harvest",
        protect=0.33,
        filter_radius=5,
        auto_high_pitch_guard=False,
    )
    logger = types.SimpleNamespace(_log=lambda *_args: None)

    ConversionService._adapt_high_range(
        logger,
        params,
        {
            "high_pitch": True,
            "high_frequency": True,
            "p95_f0_hz": 980.0,
            "high_band_ratio": 0.12,
            "recommended_f0_max": 1480.0,
        },
        tmp_path / "run.log",
        "rvc",
    )

    assert params.f0_method == "harvest"
    assert params.filter_radius == 5
    assert params.protect == 0.33
    assert not hasattr(params, "adaptive_f0_max")


def test_default_mode_keeps_original_inference_defaults_on_high_pitch_input(tmp_path: Path) -> None:
    params = InferenceParams(f0_method="harvest", protect=0.33, filter_radius=5)
    logger = types.SimpleNamespace(_log=lambda *_args: None)

    ConversionService._adapt_high_range(
        logger,
        params,
        {
            "high_pitch": True,
            "high_frequency": True,
            "p95_f0_hz": 980.0,
            "high_band_ratio": 0.12,
            "recommended_f0_max": 1480.0,
        },
        tmp_path / "run.log",
        "rvc",
    )

    assert params.f0_method == "harvest"
    assert params.filter_radius == 5
    assert params.protect == 0.33
    assert not hasattr(params, "adaptive_f0_max")
    assert (
        ConversionService._model_high_pitch_threshold(
            params,
            {"metadata": {"f0_max_hz": 500.0}},
            "rvc",
        )
        == 800.0
    )


def test_peak_f0_probe_prefers_model_backed_sidecar(tmp_path: Path) -> None:
    import wave

    sample_rate = 16000
    time_axis = np.arange(sample_rate, dtype=np.float64) / sample_rate
    source = tmp_path / "infer_input.wav"
    pcm = np.asarray(0.2 * np.sin(2.0 * np.pi * 680.0 * time_axis) * 32767.0, dtype="<i2")
    with wave.open(str(source), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    np.save(tmp_path / "f0.npy", np.full(50, 680.0, dtype=np.float32))

    assert 675.0 < ConversionService._estimate_peak_f0(source) < 685.0


def test_peak_f0_probe_still_detects_sustained_high_note_without_sidecar(tmp_path: Path) -> None:
    import wave

    sample_rate = 16000
    time_axis = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    source = tmp_path / "vocal.wav"
    pcm = np.asarray(0.2 * np.sin(2.0 * np.pi * 920.0 * time_axis) * 32767.0, dtype="<i2")
    with wave.open(str(source), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())

    assert ConversionService._estimate_peak_f0(source) >= 800.0


def test_peak_f0_probe_detects_a_brief_high_note_next_to_low_notes(
    tmp_path: Path,
) -> None:
    import wave

    sample_rate = 16000
    time_axis = np.arange(sample_rate * 4, dtype=np.float64) / sample_rate
    audio = 0.20 * np.sin(2.0 * np.pi * 220.0 * time_axis)
    high_note = (time_axis >= 2.0) & (time_axis < 2.08)
    audio[high_note] = 0.20 * np.sin(
        2.0 * np.pi * 920.0 * time_axis[high_note]
    )
    source = tmp_path / "vocal.wav"
    pcm = np.asarray(np.clip(audio, -1.0, 1.0) * 32767.0, dtype="<i2")
    with wave.open(str(source), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())

    assert ConversionService._estimate_peak_f0(source) >= 800.0


def test_model_dropout_probe_finds_only_voiced_collapsed_high_note(tmp_path: Path) -> None:
    import wave

    sample_rate = 16000
    time_axis = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    source_audio = (0.24 * np.sin(2.0 * np.pi * 760.0 * time_axis)).astype(np.float32)
    output_audio = source_audio.copy()
    output_audio[(time_axis >= 0.80) & (time_axis < 1.20)] = 0.0

    def write_wav(path: Path, values: np.ndarray) -> None:
        pcm = np.asarray(np.clip(values, -1.0, 1.0) * 32767.0, dtype="<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm.tobytes())

    source = tmp_path / "source.wav"
    output = tmp_path / "output.wav"
    write_wav(source, source_audio)
    write_wav(output, output_audio)

    issue = ConversionService._detect_model_dropout(source, output, 760.0)
    assert issue is not None
    assert 0.70 < issue["start"] < 0.90
    assert 700.0 < issue["source_f0_hz"] < 820.0
    assert ConversionService._next_dropout_threshold(760.0, issue) < 760.0


def test_stable_high_pitch_mask_rejects_isolated_tracker_spike() -> None:
    # A single 2 kHz estimate surrounded by an ordinary 330 Hz phrase is an
    # autocorrelation/harmonic jump, not evidence that the singer reached a
    # sustained high note. A real five-frame high note must still pass.
    f0 = np.full(15, 330.0, dtype=np.float32)
    f0[4] = 2000.0
    f0[8:13] = 900.0
    strength = np.full(15, 0.9, dtype=np.float32)
    rms = np.full(15, 0.08, dtype=np.float32)

    mask = ConversionService._stable_high_pitch_mask(
        f0,
        strength,
        rms,
        760.0,
    )

    assert not bool(mask[4])
    assert bool(np.all(mask[8:13]))


def test_model_dropout_probe_ignores_normal_render_and_source_pause(tmp_path: Path) -> None:
    import wave

    sample_rate = 16000
    time_axis = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    source_audio = (0.24 * np.sin(2.0 * np.pi * 760.0 * time_axis)).astype(np.float32)
    source_audio[(time_axis >= 0.80) & (time_axis < 1.20)] = 0.0

    def write_wav(path: Path, values: np.ndarray) -> None:
        pcm = np.asarray(np.clip(values, -1.0, 1.0) * 32767.0, dtype="<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm.tobytes())

    source = tmp_path / "source.wav"
    output = tmp_path / "output.wav"
    write_wav(source, source_audio)
    write_wav(output, source_audio)

    assert ConversionService._detect_model_dropout(source, output, 760.0) is None

    # A model may produce a valid render with a lower global gain.  That is
    # not a local high-note dropout and must not trigger a guarded re-inference.
    write_wav(output, source_audio * 0.06)
    assert ConversionService._detect_model_dropout(source, output, 760.0) is None


def test_model_dropout_probe_ignores_loud_render_without_trackable_f0(tmp_path: Path) -> None:
    import wave

    sample_rate = 16000
    time_axis = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    source_audio = (0.24 * np.sin(2.0 * np.pi * 760.0 * time_axis)).astype(np.float32)
    # A loud harmonic/noise-like render can make the lightweight pitch probe
    # return F0=0 even though the syllable is not muted.
    output_audio = (0.24 * np.sin(2.0 * np.pi * 7000.0 * time_axis)).astype(np.float32)

    def write_wav(path: Path, values: np.ndarray) -> None:
        pcm = np.asarray(np.clip(values, -1.0, 1.0) * 32767.0, dtype="<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm.tobytes())

    source = tmp_path / "source.wav"
    output = tmp_path / "output.wav"
    write_wav(source, source_audio)
    write_wav(output, output_audio)

    assert ConversionService._detect_model_dropout(source, output, 760.0) is None


def test_model_dropout_probe_finds_intermittent_high_note_mutes(tmp_path: Path) -> None:
    import wave

    sample_rate = 16000
    time_axis = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    source_audio = (0.24 * np.sin(2.0 * np.pi * 760.0 * time_axis)).astype(np.float32)
    output_audio = source_audio.copy()
    # Simulate the reported failure: the same high note alternates between a
    # valid render and a short mute instead of staying silent continuously.
    affected = (time_axis >= 0.80) & (time_axis < 1.20)
    alternating_mute = affected & (((time_axis - 0.80) % 0.16) < 0.08)
    output_audio[alternating_mute] = 0.0

    def write_wav(path: Path, values: np.ndarray) -> None:
        pcm = np.asarray(np.clip(values, -1.0, 1.0) * 32767.0, dtype="<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm.tobytes())

    source = tmp_path / "source.wav"
    output = tmp_path / "output.wav"
    write_wav(source, source_audio)
    write_wav(output, output_audio)

    issue = ConversionService._detect_model_dropout(source, output, 760.0)
    assert issue is not None
    assert 0.70 < issue["start"] < 0.95
    assert issue["duration"] > 0.04


def test_model_dropout_probe_finds_breathy_high_note_with_f0_present(tmp_path: Path) -> None:
    import wave

    sample_rate = 16000
    time_axis = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    source_audio = (0.24 * np.sin(2.0 * np.pi * 760.0 * time_axis)).astype(np.float32)
    output_audio = source_audio.copy()
    output_audio[(time_axis >= 0.80) & (time_axis < 1.20)] *= 0.48

    def write_wav(path: Path, values: np.ndarray) -> None:
        pcm = np.asarray(np.clip(values, -1.0, 1.0) * 32767.0, dtype="<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm.tobytes())

    source = tmp_path / "source.wav"
    output = tmp_path / "output.wav"
    write_wav(source, source_audio)
    write_wav(output, output_audio)

    issue = ConversionService._detect_model_dropout(source, output, 760.0)
    assert issue is not None
    assert issue["duration"] > 0.04


def test_model_dropout_probe_requires_sustained_breathy_pitch_collapse(
    tmp_path: Path,
) -> None:
    import wave

    from scipy.signal import butter, sosfilt

    sample_rate = 16000
    time_axis = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    source_audio = (
        0.18 * np.sin(2.0 * np.pi * 900.0 * time_axis)
        + 0.07 * np.sin(2.0 * np.pi * 1800.0 * time_axis)
    ).astype(np.float32)
    rng = np.random.default_rng(71)
    air = sosfilt(
        butter(4, 3800.0, btype="highpass", fs=sample_rate, output="sos"),
        rng.normal(0.0, 1.0, len(time_axis)),
    )
    air /= max(float(np.std(air)), 1e-6)
    collapsed = (
        0.11 * np.sin(2.0 * np.pi * 380.0 * time_axis) + 0.07 * air
    ).astype(np.float32)

    def write_wav(path: Path, values: np.ndarray) -> None:
        pcm = np.asarray(np.clip(values, -1.0, 1.0) * 32767.0, dtype="<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm.tobytes())

    source = tmp_path / "source.wav"
    sustained = tmp_path / "sustained.wav"
    transient = tmp_path / "transient.wav"
    sustained_audio = source_audio.copy()
    sustained_mask = (time_axis >= 0.70) & (time_axis < 1.30)
    sustained_audio[sustained_mask] = collapsed[sustained_mask]
    transient_audio = source_audio.copy()
    transient_mask = (time_axis >= 0.70) & (time_axis < 0.76)
    transient_audio[transient_mask] = collapsed[transient_mask]
    write_wav(source, source_audio)
    write_wav(sustained, sustained_audio)
    write_wav(transient, transient_audio)

    issue = ConversionService._detect_model_dropout(source, sustained, 800.0)

    assert issue is not None
    assert 0.60 < issue["start"] < 0.90
    assert issue["output_f0_hz"] < issue["source_f0_hz"] * 0.70
    assert issue["output_periodicity"] < issue["source_periodicity"] * 0.75
    assert ConversionService._detect_model_dropout(source, transient, 800.0) is None


def test_model_dropout_probe_ignores_clean_supported_lower_partial(
    tmp_path: Path,
) -> None:
    import wave

    sample_rate = 16000
    time_axis = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    source_audio = (
        0.18 * np.sin(2.0 * np.pi * 900.0 * time_axis)
        + 0.07 * np.sin(2.0 * np.pi * 1800.0 * time_axis)
    ).astype(np.float32)
    output_audio = (
        0.15 * np.sin(2.0 * np.pi * 450.0 * time_axis)
        + 0.12 * np.sin(2.0 * np.pi * 900.0 * time_axis)
        + 0.05 * np.sin(2.0 * np.pi * 1800.0 * time_axis)
    ).astype(np.float32)

    def write_wav(path: Path, values: np.ndarray) -> None:
        pcm = np.asarray(np.clip(values, -1.0, 1.0) * 32767.0, dtype="<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm.tobytes())

    source = tmp_path / "source.wav"
    output = tmp_path / "output.wav"
    write_wav(source, source_audio)
    write_wav(output, output_audio)

    assert ConversionService._detect_model_dropout(source, output, 800.0) is None


def test_model_dropout_probe_finds_short_high_note_mute_below_guard_boundary(
    tmp_path: Path,
) -> None:
    import wave

    sample_rate = 16000
    time_axis = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    source_audio = (0.24 * np.sin(2.0 * np.pi * 760.0 * time_axis)).astype(np.float32)
    output_audio = source_audio.copy()
    output_audio[(time_axis >= 0.82) & (time_axis < 0.90)] = 0.0

    def write_wav(path: Path, values: np.ndarray) -> None:
        pcm = np.asarray(np.clip(values, -1.0, 1.0) * 32767.0, dtype="<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm.tobytes())

    source = tmp_path / "source.wav"
    output = tmp_path / "output.wav"
    write_wav(source, source_audio)
    write_wav(output, output_audio)

    # 760 Hz is just below the default 800 Hz boundary and represents the
    # short one-syllable dropout that the regular confirmation window misses.
    issue = ConversionService._detect_model_dropout(source, output, 800.0)
    assert issue is not None
    assert 0.72 < issue["start"] < 0.95
    assert issue["duration"] < 0.20


def test_finished_work_cache_cleanup_preserves_editor_materials(tmp_path: Path) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    editor_clip = work_dir / "editor_segments" / "model_a" / "seg_001.wav"
    editor_clip.parent.mkdir(parents=True)
    editor_clip.write_bytes(b"editor")
    kept_output = work_dir / "output.wav"
    kept_model = work_dir / "full_model_a_fix.wav"
    kept_input = work_dir / "infer_input.wav"
    for path in (kept_output, kept_model, kept_input):
        path.write_bytes(b"keep")
    retry = work_dir / "converted_raw_high_guarded_retry1.wav"
    retry.write_bytes(b"retry")
    (work_dir / "converted_raw_restored_retry1.regions.json").write_text("{}")
    (work_dir / "f0.npy").write_bytes(b"f0")
    (work_dir / "source.wav").write_bytes(b"normalized")
    selected_stem = work_dir / "dereverb" / "selected.wav"
    stale_stem = work_dir / "dereverb" / "stale.wav"
    selected_stem.parent.mkdir(parents=True)
    selected_stem.write_bytes(b"selected")
    stale_stem.write_bytes(b"stale")
    log_file = work_dir / "run.log"
    work = {
        "output_path": str(kept_output),
        "ai_vocal_paths": [str(kept_model)],
        "ai_segment_clips": [{"file": str(editor_clip)}],
        "vocals_path": str(selected_stem),
    }

    service = ConversionService.__new__(ConversionService)
    service._cleanup_finished_work_cache(work_dir, work, log_file)

    assert kept_output.exists()
    assert kept_model.exists()
    assert kept_input.exists()
    assert editor_clip.exists()
    assert not retry.exists()
    assert not (work_dir / "converted_raw_restored_retry1.regions.json").exists()
    assert not (work_dir / "f0.npy").exists()
    assert not (work_dir / "source.wav").exists()
    assert selected_stem.exists()
    assert not stale_stem.exists()


def test_model_dropout_probe_finds_high_note_pitch_collapse_from_f0_sidecar(
    tmp_path: Path,
) -> None:
    import wave

    sample_rate = 16000
    time_axis = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    source_audio = (0.24 * np.sin(2.0 * np.pi * 900.0 * time_axis)).astype(np.float32)
    output_audio = (0.24 * np.sin(2.0 * np.pi * 220.0 * time_axis)).astype(np.float32)

    def write_wav(path: Path, values: np.ndarray) -> None:
        pcm = np.asarray(np.clip(values, -1.0, 1.0) * 32767.0, dtype="<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm.tobytes())

    source = tmp_path / "infer_input.wav"
    output = tmp_path / "output.wav"
    write_wav(source, source_audio)
    write_wav(output, output_audio)
    np.save(tmp_path / "f0.npy", np.full(100, 900.0, dtype=np.float32))

    issue = ConversionService._detect_model_dropout(source, output, 800.0)

    assert issue is not None
    assert issue["source_f0_hz"] > 850.0
    assert issue["output_f0_hz"] < 300.0


def test_model_dropout_probe_rejects_upper_harmonic_sidecar_spike(
    tmp_path: Path,
) -> None:
    import wave

    sample_rate = 16000
    time_axis = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    # The waveform fundamental is low, while a stale/high-harmonic F0 curve
    # incorrectly claims a sustained 1.6 kHz note. This must not trigger guard
    # processing or replace a clean default render.
    source_audio = (0.24 * np.sin(2.0 * np.pi * 150.0 * time_axis)).astype(np.float32)

    def write_wav(path: Path, values: np.ndarray) -> None:
        pcm = np.asarray(np.clip(values, -1.0, 1.0) * 32767.0, dtype="<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm.tobytes())

    source = tmp_path / "infer_input.wav"
    output = tmp_path / "output.wav"
    write_wav(source, source_audio)
    write_wav(output, source_audio)
    np.save(tmp_path / "f0.npy", np.full(100, 1600.0, dtype=np.float32))

    assert ConversionService._detect_model_dropout(source, output, 700.0) is None


def test_model_dropout_probe_rejects_upper_harmonic_without_sidecar(
    tmp_path: Path,
) -> None:
    import wave

    sample_rate = 16000
    time_axis = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    # Bright separated vocals can make autocorrelation select the upper
    # harmonic. A supported low fundamental should win that ambiguity.
    source_audio = (
        0.20 * np.sin(2.0 * np.pi * 150.0 * time_axis)
        + 0.13 * np.sin(2.0 * np.pi * 1600.0 * time_axis)
    ).astype(np.float32)

    def write_wav(path: Path, values: np.ndarray) -> None:
        pcm = np.asarray(np.clip(values, -1.0, 1.0) * 32767.0, dtype="<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm.tobytes())

    source = tmp_path / "infer_input.wav"
    output = tmp_path / "output.wav"
    write_wav(source, source_audio)
    write_wav(output, source_audio)

    assert ConversionService._detect_model_dropout(source, output, 700.0) is None


def test_dropout_recovery_keeps_default_render_when_no_dropout(tmp_path: Path) -> None:
    service = ConversionService.__new__(ConversionService)
    source = tmp_path / "source.wav"
    output = tmp_path / "converted_raw.wav"
    source.write_bytes(b"source")
    calls: list[tuple[Path, Path]] = []

    def infer(vocals: Path, target: Path) -> None:
        calls.append((vocals, target))
        target.write_bytes(b"ordinary-render")

    service._log = lambda *_args: None
    service._detect_model_dropout = lambda *_args: None

    rendered, history, guard_applied = service._infer_with_dropout_recovery(
        engine=types.SimpleNamespace(),
        model={},
        source=source,
        output=output,
        params=InferenceParams(high_pitch_threshold=800.0),
        duration=2.0,
        log_file=tmp_path / "run.log",
        allow_recovery=True,
        infer=infer,
    )

    assert rendered == output
    assert output.read_bytes() == b"ordinary-render"
    assert calls == [(source, output)]
    assert history == [
        {
            "attempt": 1,
            "threshold": 800.0,
            "issue": None,
            "guard_applied": False,
            "input": "original",
        }
    ]
    assert guard_applied is False


def test_dropout_recovery_is_fully_disabled_when_high_pitch_guard_is_off(
    tmp_path: Path,
) -> None:
    service = ConversionService.__new__(ConversionService)
    source = tmp_path / "source.wav"
    output = tmp_path / "converted_raw.wav"
    source.write_bytes(b"source")
    calls: list[tuple[Path, Path]] = []
    detection_calls = 0

    def infer(vocals: Path, target: Path) -> None:
        calls.append((vocals, target))
        target.write_bytes(b"ordinary-render")

    def detect(*_args) -> dict[str, float]:
        nonlocal detection_calls
        detection_calls += 1
        return {"start": 0.5, "end": 0.8, "source_f0_hz": 920.0}

    service._log = lambda *_args: None
    service._detect_model_dropout = detect
    service._prepare_high_pitch_guard = lambda *_args: (_ for _ in ()).throw(
        AssertionError("high-pitch guard must not prepare input when disabled")
    )
    service._restore_high_pitch_guard = lambda *_args: (_ for _ in ()).throw(
        AssertionError("high-pitch guard must not restore output when disabled")
    )

    rendered, history, guard_applied = service._infer_with_dropout_recovery(
        engine=types.SimpleNamespace(),
        model={},
        source=source,
        output=output,
        params=InferenceParams(
            high_pitch_threshold=800.0,
            auto_high_pitch_guard=False,
            high_pitch_guard_rounds=8,
        ),
        duration=2.0,
        log_file=tmp_path / "run.log",
        allow_recovery=True,
        infer=infer,
    )

    assert rendered == output
    assert calls == [(source, output)]
    assert detection_calls == 0
    assert history == []
    assert guard_applied is False


def test_high_pitch_guard_rounds_are_opt_in_and_clamped() -> None:
    from domain import InferenceParams

    assert InferenceParams.from_dict({"high_pitch_guard_rounds": 99}).high_pitch_guard_rounds == 8
    assert InferenceParams.from_dict({"highPitchGuardRounds": -2}).high_pitch_guard_rounds == 0
    assert (
        ConversionService._high_pitch_guard_rounds(
            InferenceParams(manual_params_enabled=False, high_pitch_guard_rounds=0)
        )
        == ConversionService._DROPOUT_RECOVERY_MAX_ATTEMPTS - 1
    )
    assert (
        ConversionService._high_pitch_guard_rounds(
            InferenceParams(manual_params_enabled=True, high_pitch_guard_rounds=2)
        )
        == 2
    )


def test_guard_drop_escalates_only_after_high_note_retry_still_exceeds_range() -> None:
    assert ConversionService._guard_semitones_for_retry(
        730.0, {"source_f0_hz": 747.0}
    ) == 7
    assert ConversionService._guard_semitones_for_retry(
        670.0, {"source_f0_hz": 760.0}
    ) == 9
    assert ConversionService._guard_semitones_for_retry(
        620.0, {"source_f0_hz": 900.0}
    ) == 12
    # Extreme notes need more than one octave of preparation; otherwise an
    # RVC model can still render the lowered input in its low register and the
    # restored result becomes thin/breathy.
    assert ConversionService._guard_semitones_for_retry(
        700.0, {"source_f0_hz": 1600.0}
    ) == 15


def test_guard_candidate_rejects_new_air_band_whistle(tmp_path: Path) -> None:
    import wave

    sample_rate = 16000
    time_axis = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    source_audio = 0.16 * np.sin(2.0 * np.pi * 220.0 * time_axis)
    baseline_audio = source_audio.copy()
    candidate_audio = baseline_audio.copy()
    region = (time_axis >= 0.80) & (time_axis < 1.10)
    candidate_audio[region] += 0.20 * np.sin(
        2.0 * np.pi * 6500.0 * time_axis[region]
    )

    def write(path: Path, values: np.ndarray) -> None:
        pcm = np.asarray(np.clip(values, -1.0, 1.0) * 32767.0, dtype="<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm.tobytes())

    source = tmp_path / "source.wav"
    baseline = tmp_path / "baseline.wav"
    candidate = tmp_path / "candidate.wav"
    write(source, source_audio)
    write(baseline, baseline_audio)
    write(candidate, candidate_audio)

    assert ConversionService._guard_candidate_has_new_hf_peak(
        source,
        baseline,
        candidate,
        [(0.80, 1.10)],
    ) is True


def test_guard_candidate_allows_musical_high_note(tmp_path: Path) -> None:
    import wave

    sample_rate = 16000
    time_axis = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    source_audio = 0.16 * np.sin(2.0 * np.pi * 1000.0 * time_axis)
    baseline_audio = source_audio * 0.2
    candidate_audio = source_audio

    def write(path: Path, values: np.ndarray) -> None:
        pcm = np.asarray(np.clip(values, -1.0, 1.0) * 32767.0, dtype="<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm.tobytes())

    source = tmp_path / "source.wav"
    baseline = tmp_path / "baseline.wav"
    candidate = tmp_path / "candidate.wav"
    write(source, source_audio)
    write(baseline, baseline_audio)
    write(candidate, candidate_audio)

    assert ConversionService._guard_candidate_has_new_hf_peak(
        source,
        baseline,
        candidate,
        [(0.80, 1.10)],
    ) is False


def test_guard_candidate_partial_recovery_requires_more_body_not_more_air(
    tmp_path: Path,
) -> None:
    import wave

    from scipy.signal import butter, sosfilt

    sample_rate = 16000
    time_axis = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    note = (
        np.sin(2.0 * np.pi * 760.0 * time_axis)
        + 0.45 * np.sin(2.0 * np.pi * 1520.0 * time_axis)
    )
    rng = np.random.default_rng(37)
    air = sosfilt(
        butter(4, 4800.0, btype="highpass", fs=sample_rate, output="sos"),
        rng.normal(0.0, 1.0, len(time_axis)),
    )
    air /= max(float(np.std(air)), 1e-6)
    source_audio = 0.16 * note
    baseline_audio = 0.035 * note + 0.025 * air
    recovered_audio = 0.09 * note + 0.025 * air
    breathy_audio = 0.07 * note + 0.12 * air

    def write(path: Path, values: np.ndarray) -> None:
        pcm = np.asarray(np.clip(values, -1.0, 1.0) * 32767.0, dtype="<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm.tobytes())

    source = tmp_path / "source.wav"
    baseline = tmp_path / "baseline.wav"
    recovered = tmp_path / "recovered.wav"
    breathy = tmp_path / "breathy.wav"
    write(source, source_audio)
    write(baseline, baseline_audio)
    write(recovered, recovered_audio)
    write(breathy, breathy_audio)

    assert ConversionService._guard_candidate_restores_high_note_body(
        source,
        baseline,
        recovered,
        [(0.40, 1.60)],
    ) is True
    assert ConversionService._guard_candidate_restores_high_note_body(
        source,
        baseline,
        breathy,
        [(0.40, 1.60)],
    ) is False


def test_guard_candidate_accepts_tonal_recovery_without_loudness_increase(
    tmp_path: Path,
) -> None:
    import wave

    from scipy.signal import butter, sosfilt

    sample_rate = 16000
    time_axis = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    source_audio = (
        0.15 * np.sin(2.0 * np.pi * 900.0 * time_axis)
        + 0.06 * np.sin(2.0 * np.pi * 1800.0 * time_axis)
    )
    rng = np.random.default_rng(79)
    air = sosfilt(
        butter(4, 4800.0, btype="highpass", fs=sample_rate, output="sos"),
        rng.normal(0.0, 1.0, len(time_axis)),
    )
    air /= max(float(np.std(air)), 1e-6)
    rasp = sosfilt(
        butter(
            4,
            (500.0, 3600.0),
            btype="bandpass",
            fs=sample_rate,
            output="sos",
        ),
        rng.normal(0.0, 1.0, len(time_axis)),
    )
    rasp /= max(float(np.std(rasp)), 1e-6)
    baseline_audio = (
        0.08 * np.sin(2.0 * np.pi * 380.0 * time_axis)
        + 0.08 * rasp
        + 0.045 * air
    )
    recovered_audio = 0.14 * source_audio / 0.15 + 0.010 * air

    def write(path: Path, values: np.ndarray) -> None:
        pcm = np.asarray(np.clip(values, -1.0, 1.0) * 32767.0, dtype="<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm.tobytes())

    source = tmp_path / "source.wav"
    baseline = tmp_path / "baseline.wav"
    recovered = tmp_path / "recovered.wav"
    write(source, source_audio)
    write(baseline, baseline_audio)
    write(recovered, recovered_audio)

    assert ConversionService._guard_candidate_restores_high_note_body(
        source,
        baseline,
        recovered,
        [(0.40, 1.60)],
    ) is True


def test_guard_candidate_quality_rejects_whole_note_when_one_core_is_air(
    tmp_path: Path,
) -> None:
    import json
    import wave

    sample_rate = 16000
    time_axis = np.arange(sample_rate * 3, dtype=np.float64) / sample_rate
    source_audio = 0.16 * np.sin(2.0 * np.pi * 820.0 * time_axis)
    baseline_audio = 0.025 * np.sin(2.0 * np.pi * 300.0 * time_axis)
    candidate_audio = 0.12 * np.sin(2.0 * np.pi * 820.0 * time_axis)
    rng = np.random.default_rng(313)
    failed = (time_axis >= 0.90) & (time_axis <= 1.40)
    candidate_audio[failed] = rng.normal(0.0, 0.012, int(np.count_nonzero(failed)))

    def write(path: Path, values: np.ndarray) -> None:
        pcm = np.asarray(np.clip(values, -1.0, 1.0) * 32767.0, dtype="<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm.tobytes())

    source = tmp_path / "source.wav"
    baseline = tmp_path / "baseline.wav"
    candidate = tmp_path / "candidate.wav"
    report = tmp_path / "candidate.regions.json"
    write(source, source_audio)
    write(baseline, baseline_audio)
    write(candidate, candidate_audio)
    report.write_text(
        json.dumps(
            {
                "regions": [
                    {"start": 0.25, "end": 1.45},
                    {"start": 1.85, "end": 2.55},
                ]
            }
        ),
        encoding="utf-8",
    )
    cores = [(0.40, 0.70), (1.00, 1.30), (2.00, 2.40)]

    quality = ConversionService._guard_candidate_high_note_quality(
        source,
        baseline,
        candidate,
        cores,
        report,
    )

    assert quality["available"] is True
    assert [item["passed"] for item in quality["regions"]] == [True, False, True]
    assert quality["accepted_regions"] == [cores[2]]
    assert quality["failed_regions"] == cores[:2]
    assert quality["passed"] is False


def test_confirmed_guard_regions_keep_phrase_context_without_global_expansion() -> None:
    regions = ConversionService._confirmed_guard_regions(
        {"bad_regions": [{"start": 61.0, "end": 61.2}, {"start": 62.0, "end": 62.3}]}
    )
    assert regions is not None
    assert regions[0] == pytest.approx((60.76, 61.44))
    assert regions[1] == pytest.approx((61.76, 62.54))
    assert len(regions) == 2
    separated = ConversionService._confirmed_guard_regions(
        {"bad_regions": [{"start": 54.0, "end": 54.2}]},
        existing=[(60.0, 63.0)],
    )
    assert separated is not None
    assert separated[0][0] == pytest.approx(53.76)
    assert separated[0][1] == pytest.approx(54.44)
    assert separated[1] == pytest.approx((60.0, 63.0))


def test_dropout_core_regions_exclude_guard_context_from_final_merge() -> None:
    core = ConversionService._dropout_core_regions(
        {
            "bad_regions": [
                {"start": 27.18, "end": 27.26},
                {"start": 45.42, "end": 45.48},
            ]
        }
    )
    assert core == pytest.approx([(27.18, 27.26), (45.42, 45.48)])


def test_dropout_recovery_uses_guard_only_after_verified_failure_and_falls_back(
    tmp_path: Path,
) -> None:
    service = ConversionService.__new__(ConversionService)
    source = tmp_path / "source.wav"
    output = tmp_path / "converted_raw.wav"
    source.write_bytes(b"source")
    calls: list[tuple[Path, Path]] = []
    issue = {
        "start": 0.8,
        "end": 1.1,
        "source_f0_hz": 920.0,
        "source_rms": 0.2,
        "output_rms": 0.01,
        "duration": 0.3,
    }
    detections = iter([issue, issue, issue, issue])

    def infer(vocals: Path, target: Path) -> None:
        calls.append((vocals, target))
        target.write_bytes(b"guarded-render" if "dropout_retry" in target.name else b"ordinary-render")

    def prepare(
        src: Path,
        destination: Path,
        *_args,
    ) -> tuple[Path, bool]:
        destination.write_bytes(b"guarded-input")
        return destination, True

    def restore(
        _src: Path,
        destination: Path,
        *_args,
    ) -> Path:
        destination.write_bytes(b"restored-render")
        return destination

    service._log = lambda *_args: None
    service._detect_model_dropout = lambda *_args: next(detections)
    service._prepare_high_pitch_guard = prepare
    service._restore_high_pitch_guard = restore

    rendered, history, guard_applied = service._infer_with_dropout_recovery(
        engine=types.SimpleNamespace(),
        model={},
        source=source,
        output=output,
        params=InferenceParams(high_pitch_threshold=800.0),
        duration=2.0,
        log_file=tmp_path / "run.log",
        allow_recovery=True,
        infer=infer,
    )

    assert rendered == output
    assert output.read_bytes() == b"ordinary-render"
    assert calls[0] == (source, output)
    assert calls[1][0].name == "converted_raw_high_guarded_retry1.wav"
    assert history[0]["input"] == "original"
    assert history[-1]["issue"] is not None
    assert guard_applied is False


def test_dropout_recovery_rejects_detector_clear_when_initial_core_is_still_air(
    tmp_path: Path,
) -> None:
    service = ConversionService.__new__(ConversionService)
    source = tmp_path / "source.wav"
    output = tmp_path / "converted_raw.wav"
    source.write_bytes(b"source")
    core = (1.0, 1.2)
    first_issue = {
        "start": core[0],
        "end": core[1],
        "source_f0_hz": 900.0,
        "source_rms": 0.12,
        "output_rms": 0.01,
        "bad_frames": 10,
        "bad_regions": [{"start": core[0], "end": core[1]}],
    }
    detections = iter([first_issue, None])

    def infer(_vocals: Path, target: Path) -> None:
        target.write_bytes(b"baseline" if target == output else b"retry")

    def prepare(
        _source: Path,
        destination: Path,
        *_args,
    ) -> tuple[Path, bool]:
        destination.write_bytes(b"guarded")
        return destination, True

    def restore(_source: Path, destination: Path, *_args) -> Path:
        destination.write_bytes(b"restored-air")
        return destination

    service._log = lambda *_args: None
    service._detect_model_dropout = lambda *_args: next(detections)
    service._prepare_high_pitch_guard = prepare
    service._restore_high_pitch_guard = restore
    service._guard_candidate_high_note_quality = lambda *_args: {
        "available": True,
        "passed": False,
        "accepted_regions": [],
        "failed_regions": [core],
        "regions": [
            {
                "start": core[0],
                "end": core[1],
                "source_f0_hz": 900.0,
                "source_rms": 0.12,
                "candidate_f0_hz": 0.0,
                "candidate_rms": 0.01,
            }
        ],
    }

    rendered, history, guard_applied = service._infer_with_dropout_recovery(
        engine=types.SimpleNamespace(),
        model={},
        source=source,
        output=output,
        params=InferenceParams(
            high_pitch_threshold=800.0,
            manual_params_enabled=True,
            high_pitch_guard_rounds=1,
        ),
        duration=2.0,
        log_file=tmp_path / "run.log",
        allow_recovery=True,
        infer=infer,
    )

    assert rendered == output
    assert output.read_bytes() == b"baseline"
    assert history[-1]["issue"] is not None
    assert history[-1]["quality"]["passed"] is False
    assert guard_applied is False


def test_dropout_recovery_keeps_initial_cores_fixed_across_quality_retries(
    tmp_path: Path,
) -> None:
    service = ConversionService.__new__(ConversionService)
    source = tmp_path / "source.wav"
    output = tmp_path / "converted_raw.wav"
    source.write_bytes(b"source")
    cores = [(1.0, 1.2), (3.0, 3.2)]
    first_issue = {
        "start": 1.0,
        "end": 3.2,
        "source_f0_hz": 920.0,
        "source_rms": 0.12,
        "output_rms": 0.01,
        "bad_frames": 20,
        "bad_regions": [
            {"start": start, "end": end} for start, end in cores
        ],
    }
    detections = iter([first_issue, None, None])
    measured_regions: list[list[tuple[float, float]]] = []
    quality_results = iter(
        [
            {
                "available": True,
                "passed": False,
                "accepted_regions": [cores[0]],
                "failed_regions": [cores[1]],
                "regions": [],
            },
            {
                "available": True,
                "passed": True,
                "accepted_regions": cores,
                "failed_regions": [],
                "regions": [],
            },
        ]
    )

    def infer(_vocals: Path, target: Path) -> None:
        target.write_bytes(target.name.encode("ascii"))

    def prepare(
        _source: Path,
        destination: Path,
        *_args,
    ) -> tuple[Path, bool]:
        destination.write_bytes(b"guarded")
        return destination, True

    def restore(_source: Path, destination: Path, *_args) -> Path:
        destination.write_bytes(b"restored")
        return destination

    def merge(
        _baseline: Path,
        _candidate: Path,
        destination: Path,
        *_args,
        **_kwargs,
    ) -> Path:
        destination.write_bytes(b"merged")
        return destination

    def quality(
        _source: Path,
        _baseline: Path,
        _candidate: Path,
        regions: list[tuple[float, float]],
        _report: Path | None,
    ) -> dict[str, object]:
        measured_regions.append(list(regions))
        return next(quality_results)

    service._log = lambda *_args: None
    service._detect_model_dropout = lambda *_args: next(detections)
    service._prepare_high_pitch_guard = prepare
    service._restore_high_pitch_guard = restore
    service._merge_guarded_regions = merge
    service._guard_candidate_has_new_hf_peak = lambda *_args: False
    service._guard_candidate_high_note_quality = quality

    rendered, history, guard_applied = service._infer_with_dropout_recovery(
        engine=types.SimpleNamespace(),
        model={},
        source=source,
        output=output,
        params=InferenceParams(
            high_pitch_threshold=800.0,
            manual_params_enabled=True,
            high_pitch_guard_rounds=2,
        ),
        duration=4.0,
        log_file=tmp_path / "run.log",
        allow_recovery=True,
        infer=infer,
    )

    assert measured_regions == [cores, cores]
    assert history[1]["issue"]["bad_regions"] == [
        {"start": cores[1][0], "end": cores[1][1]}
    ]
    assert history[2]["issue"] is None
    assert rendered.name == "converted_raw_accepted_retry2.wav"
    assert guard_applied is True


def test_dropout_recovery_stops_when_retry_detects_failure_outside_guard_scope(
    tmp_path: Path,
) -> None:
    from domain import InferenceParams

    service = ConversionService.__new__(ConversionService)
    source = tmp_path / "source.wav"
    output = tmp_path / "converted_raw.wav"
    source.write_bytes(b"source")
    first_issue = {
        "start": 1.0,
        "end": 1.3,
        "source_f0_hz": 920.0,
        "source_rms": 0.2,
        "output_rms": 0.01,
        "bad_frames": 30,
        "bad_regions": [{"start": 1.0, "end": 1.3}],
    }
    outside_issue = {
        "start": 5.0,
        "end": 5.2,
        "source_f0_hz": 701.0,
        "source_rms": 0.2,
        "output_rms": 0.01,
        "bad_frames": 10,
        "bad_regions": [{"start": 5.0, "end": 5.2}],
    }
    detections = iter([first_issue, outside_issue])
    calls: list[tuple[Path, Path]] = []

    def infer(vocals: Path, target: Path) -> None:
        calls.append((vocals, target))
        target.write_bytes(b"render")

    def prepare(src: Path, destination: Path, *_args) -> tuple[Path, bool]:
        destination.write_bytes(b"guarded-input")
        return destination, True

    def restore(_src: Path, destination: Path, *_args) -> Path:
        destination.write_bytes(b"restored-render")
        return destination

    service._log = lambda *_args: None
    service._detect_model_dropout = lambda *_args: next(detections)
    service._prepare_high_pitch_guard = prepare
    service._restore_high_pitch_guard = restore

    rendered, history, guard_applied = service._infer_with_dropout_recovery(
        engine=types.SimpleNamespace(),
        model={},
        source=source,
        output=output,
        params=InferenceParams(high_pitch_threshold=800.0),
        duration=2.0,
        log_file=tmp_path / "run.log",
        allow_recovery=True,
        infer=infer,
    )

    assert rendered.name == "converted_raw_restored_retry1.wav"
    assert guard_applied is True
    assert len(history) == 2
    assert len(calls) == 2


def test_dropout_recovery_does_not_use_unresolved_candidate_as_residual_baseline(
    tmp_path: Path,
) -> None:
    service = ConversionService.__new__(ConversionService)
    source = tmp_path / "source.wav"
    output = tmp_path / "converted_raw.wav"
    source.write_bytes(b"source")
    calls: list[tuple[Path, Path]] = []
    first_issue = {
        "start": 1.0,
        "end": 1.3,
        "source_f0_hz": 920.0,
        "source_rms": 0.2,
        "output_rms": 0.01,
        "bad_frames": 40,
        "bad_regions": [{"start": 1.0, "end": 1.3}],
    }
    residual_issue = {
        "start": 1.1,
        "end": 1.2,
        "source_f0_hz": 900.0,
        "source_rms": 0.2,
        "output_rms": 0.02,
        "bad_frames": 8,
        "bad_regions": [{"start": 1.1, "end": 1.2}],
    }
    detections = iter([first_issue, residual_issue, None])

    def infer(vocals: Path, target: Path) -> None:
        calls.append((vocals, target))
        target.write_bytes(b"render")

    def prepare(src: Path, destination: Path, *_args) -> tuple[Path, bool]:
        destination.write_bytes(b"guarded-input")
        return destination, True

    def restore(_src: Path, destination: Path, *_args) -> Path:
        destination.write_bytes(b"restored-render")
        return destination

    def merge(_baseline: Path, _guarded: Path, destination: Path, *_args, **_kwargs) -> Path:
        destination.write_bytes(b"merged-render")
        return destination

    service._log = lambda *_args: None
    service._detect_model_dropout = lambda *_args: next(detections)
    service._prepare_high_pitch_guard = prepare
    service._restore_high_pitch_guard = restore
    service._merge_guarded_regions = merge

    rendered, history, guard_applied = service._infer_with_dropout_recovery(
        engine=types.SimpleNamespace(),
        model={},
        source=source,
        output=output,
        params=InferenceParams(
            high_pitch_threshold=800.0,
            manual_params_enabled=True,
            high_pitch_guard_rounds=1,
        ),
        duration=2.0,
        log_file=tmp_path / "run.log",
        allow_recovery=True,
        infer=infer,
    )

    assert rendered == output
    assert output.read_bytes() == b"render"
    assert len(calls) == 2
    assert history[-1]["issue"] is residual_issue
    assert guard_applied is False


def test_dropout_recovery_keeps_partial_candidate_after_body_quality_pass(
    tmp_path: Path,
) -> None:
    service = ConversionService.__new__(ConversionService)
    source = tmp_path / "source.wav"
    output = tmp_path / "converted_raw.wav"
    source.write_bytes(b"source")
    first_issue = {
        "start": 1.0,
        "end": 1.3,
        "source_f0_hz": 920.0,
        "source_rms": 0.2,
        "output_rms": 0.01,
        "bad_frames": 40,
        "bad_regions": [{"start": 1.0, "end": 1.3}],
    }
    residual_issue = {
        "start": 1.1,
        "end": 1.2,
        "source_f0_hz": 900.0,
        "source_rms": 0.2,
        "output_rms": 0.06,
        "bad_frames": 8,
        "bad_regions": [{"start": 1.1, "end": 1.2}],
    }
    detections = iter([first_issue, residual_issue])

    def infer(_vocals: Path, target: Path) -> None:
        target.write_bytes(b"baseline" if target == output else b"retry")

    def prepare(
        _source: Path,
        destination: Path,
        *_args,
    ) -> tuple[Path, bool]:
        destination.write_bytes(b"guarded-input")
        return destination, True

    def restore(
        _source: Path,
        destination: Path,
        *_args,
    ) -> Path:
        destination.write_bytes(b"restored")
        return destination

    def merge(
        _baseline: Path,
        _guarded: Path,
        destination: Path,
        *_args,
        **_kwargs,
    ) -> Path:
        destination.write_bytes(b"body-recovered")
        return destination

    service._log = lambda *_args: None
    service._detect_model_dropout = lambda *_args: next(detections)
    service._prepare_high_pitch_guard = prepare
    service._restore_high_pitch_guard = restore
    service._merge_guarded_regions = merge
    service._guard_candidate_has_new_hf_peak = lambda *_args: False
    service._guard_candidate_restores_high_note_body = lambda *_args: True
    service._run_residual_dropout_retry = lambda **kwargs: (
        kwargs["baseline"],
        kwargs["issue"],
        False,
    )

    rendered, history, guard_applied = service._infer_with_dropout_recovery(
        engine=types.SimpleNamespace(),
        model={},
        source=source,
        output=output,
        params=InferenceParams(
            high_pitch_threshold=800.0,
            manual_params_enabled=True,
            high_pitch_guard_rounds=1,
        ),
        duration=2.0,
        log_file=tmp_path / "run.log",
        allow_recovery=True,
        infer=infer,
    )

    assert rendered.name == "converted_raw_guarded_merged_retry1.wav"
    assert rendered.read_bytes() == b"body-recovered"
    assert history[-1]["body_recovered"] is True
    assert guard_applied is True


def test_editor_restore_uses_model_render_for_loudness_reference(tmp_path: Path) -> None:
    service = AudioEditorService.__new__(AudioEditorService)
    model_render = tmp_path / "model-render.wav"
    original = tmp_path / "original.wav"
    destination = tmp_path / "restored.wav"
    model_render.write_bytes(b"model-render")
    original.write_bytes(b"dry-vocal")
    calls: list[tuple[Path, Path, int, dict[str, object]]] = []

    class Ffmpeg:
        def pitch_shift(
            self,
            source: Path,
            target: Path,
            semitones: int,
            **kwargs: object,
        ) -> bool:
            calls.append((source, target, semitones, kwargs))
            target.write_bytes(b"restored")
            return True

    service._ffmpeg = Ffmpeg()
    restored = service._restore_high_pitch_guard(
        model_render,
        destination,
        original,
        InferenceParams(high_pitch_threshold=800.0),
    )

    assert restored == destination
    assert calls[0][0] == model_render
    assert calls[0][2] == AudioEditorService._HIGH_PITCH_GUARD_SEMITONES
    assert calls[0][3]["mask_source"] == original
    assert calls[0][3]["loudness_source"] == model_render


def test_editor_dropout_recovery_keeps_baseline_when_retry_is_unsafe(
    tmp_path: Path, monkeypatch
) -> None:
    service = AudioEditorService.__new__(AudioEditorService)
    source = tmp_path / "source.wav"
    output = tmp_path / "render.wav"
    source.write_bytes(b"source")
    issue = {
        "start": 0.5,
        "end": 0.9,
        "source_f0_hz": 920.0,
        "bad_frames": 20,
        "bad_regions": [{"start": 0.5, "end": 0.9}],
    }

    def infer(_model: object, _vocals: Path, target: Path, *_args: object) -> None:
        target.write_bytes(b"baseline" if target == output else b"unsafe-retry")

    def prepare(_source: Path, destination: Path, *_args: object) -> tuple[Path, bool]:
        destination.write_bytes(b"guarded-input")
        return destination, True

    def restore(_source: Path, destination: Path, *_args: object) -> Path:
        destination.write_bytes(b"restored")
        return destination

    monkeypatch.setattr(ConversionService, "_detect_model_dropout", lambda *_args: issue)
    monkeypatch.setattr(
        ConversionService,
        "_guard_candidate_has_new_hf_peak",
        lambda *_args: True,
    )
    monkeypatch.setattr(
        ConversionService,
        "_merge_guarded_regions",
        lambda _baseline, _guarded, destination, *_args, **_kwargs: destination,
    )
    service._prepare_high_pitch_guard = prepare
    service._restore_high_pitch_guard = restore

    rendered, history, guard_applied = service._infer_with_dropout_recovery(
        model={},
        engine=types.SimpleNamespace(infer=infer),
        source=source,
        output=output,
        params=InferenceParams(
            high_pitch_threshold=800.0,
            manual_params_enabled=True,
            high_pitch_guard_rounds=1,
        ),
        duration=2.0,
    )

    assert rendered == output
    assert output.read_bytes() == b"baseline"
    assert len(history) == 2
    assert guard_applied is False


def test_guarded_retry_merge_preserves_non_high_baseline_audio(tmp_path: Path) -> None:
    import json
    import wave

    sample_rate = 16000
    frames = sample_rate
    baseline = tmp_path / "baseline.wav"
    guarded = tmp_path / "guarded.wav"
    merged = tmp_path / "merged.wav"
    report = tmp_path / "regions.json"

    def write(path: Path, value: int) -> None:
        audio = np.full((frames, 2), value, dtype="<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(2)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(audio.tobytes())

    write(baseline, 1000)
    write(guarded, 2000)
    report.write_text(
        json.dumps(
            {
                "regions": [
                    {"start": 0.35, "end": 0.65},
                    {"start": 0.75, "end": 0.85},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert ConversionService._merge_guarded_regions(
        baseline,
        guarded,
        merged,
        report,
        only_regions=[(0.35, 0.65)],
    ) == merged
    with wave.open(str(merged), "rb") as handle:
        values = np.frombuffer(handle.readframes(frames), dtype="<i2").reshape(-1, 2)
    assert np.all(values[int(0.1 * sample_rate)] == 1000)
    assert np.all(values[int(0.40 * sample_rate)] == 2000)
    assert np.all(values[int(0.60 * sample_rate)] == 2000)
    assert np.all(values[int(0.8 * sample_rate)] == 1000)
    assert np.all(values[int(0.9 * sample_rate)] == 1000)


def test_guarded_retry_merge_does_not_use_failed_baseline_as_loudness_ceiling(
    tmp_path: Path,
) -> None:
    import json
    import wave

    sample_rate = 16000
    frames = sample_rate
    baseline = tmp_path / "baseline.wav"
    guarded = tmp_path / "guarded.wav"
    merged = tmp_path / "merged.wav"
    report = tmp_path / "regions.json"

    def write(path: Path, value: int) -> None:
        audio = np.full((frames, 1), value, dtype="<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(audio.tobytes())

    write(baseline, 1000)
    write(guarded, 6000)
    report.write_text(
        json.dumps({"regions": [{"start": 0.4, "end": 0.6}]}),
        encoding="utf-8",
    )

    assert ConversionService._merge_guarded_regions(
        baseline, guarded, merged, report, only_regions=[(0.35, 0.65)]
    ) == merged
    with wave.open(str(merged), "rb") as handle:
        values = np.frombuffer(handle.readframes(frames), dtype="<i2")
    # Candidate safety is decided by the per-region quality gate. The baseline
    # is a confirmed collapsed render, so clipping a valid recovered note to
    # 1.35x that level would make the high note inaudible again.
    assert int(values[int(0.5 * sample_rate)]) == 6000


def test_guarded_retry_merge_keeps_baseline_when_region_report_is_missing(
    tmp_path: Path,
) -> None:
    import wave

    sample_rate = 16000
    frames = sample_rate
    baseline = tmp_path / "baseline.wav"
    guarded = tmp_path / "guarded.wav"

    def write(path: Path, value: int) -> None:
        audio = np.full((frames, 1), value, dtype="<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(audio.tobytes())

    write(baseline, 1000)
    write(guarded, 2000)
    merged = tmp_path / "merged.wav"

    assert ConversionService._merge_guarded_regions(
        baseline,
        guarded,
        merged,
        tmp_path / "missing-regions.json",
        only_regions=[(0.49, 0.51)],
    ) == merged
    with wave.open(str(merged), "rb") as handle:
        values = np.frombuffer(handle.readframes(frames), dtype="<i2")
    assert int(values[int(0.1 * sample_rate)]) == 1000
    assert int(values[int(0.5 * sample_rate)]) == 2000


def test_residual_dropout_retry_rejects_new_high_frequency_peak(
    tmp_path: Path,
) -> None:
    service = ConversionService.__new__(ConversionService)
    source = tmp_path / "source.wav"
    output = tmp_path / "converted_raw.wav"
    baseline = tmp_path / "best.wav"
    source.write_bytes(b"source")
    baseline.write_bytes(b"best")
    issue = {
        "start": 1.0,
        "end": 1.2,
        "source_f0_hz": 920.0,
        "bad_frames": 8,
        "bad_regions": [{"start": 1.0, "end": 1.2}],
    }

    def infer(_vocals: Path, target: Path) -> None:
        target.write_bytes(b"render")

    def prepare(_source: Path, destination: Path, *_args) -> tuple[Path, bool]:
        destination.write_bytes(b"guarded-input")
        return destination, True

    def restore(_source: Path, destination: Path, *_args) -> Path:
        destination.write_bytes(b"restored-render")
        return destination

    def merge(
        _baseline: Path,
        _guarded: Path,
        destination: Path,
        *_args,
        **_kwargs,
    ) -> Path:
        destination.write_bytes(b"merged-render")
        return destination

    service._log = lambda *_args: None
    service._prepare_high_pitch_guard = prepare
    service._restore_high_pitch_guard = restore
    service._merge_guarded_regions = merge
    service._guard_candidate_has_new_hf_peak = lambda *_args: True
    service._detect_model_dropout = lambda *_args: (_ for _ in ()).throw(
        AssertionError("a rejected whistle candidate must not enter dropout scoring")
    )

    rendered, remaining_issue, attempted = service._run_residual_dropout_retry(
        run_inference=infer,
        source=source,
        output=output,
        baseline=baseline,
        params=InferenceParams(high_pitch_threshold=800.0),
        log_file=tmp_path / "run.log",
        issue=issue,
        threshold=700.0,
        semitones=9,
        pitch=0,
        attempt=2,
    )

    assert rendered == baseline
    assert remaining_issue is issue
    assert attempted is True


def test_formant_guard_bridges_short_high_note_boundary_dip() -> None:
    intervals = formant_pitch_worker._high_intervals(
        [(0.40, 830.0), (0.44, 780.0), (0.48, 835.0)],
        800.0,
        0.0,
        1.0,
    )

    assert intervals
    assert intervals[0][0] < 0.40 < intervals[0][1]
    assert intervals[0][1] > 0.48


def test_formant_guard_pitch_tier_uses_smooth_boundary_fades() -> None:
    intervals = [(1.0, 1.4)]
    before = formant_pitch_worker._region_weight_at(0.90, intervals)
    entering = formant_pitch_worker._region_weight_at(0.98, intervals)
    inside = formant_pitch_worker._region_weight_at(1.10, intervals)
    leaving = formant_pitch_worker._region_weight_at(1.44, intervals)

    assert before == 0.0
    assert 0.0 < entering < 1.0
    assert inside == 1.0
    assert 0.0 < leaving < 1.0


def test_realtime_high_pitch_guard_uses_model_range_and_honors_manual_value() -> None:
    from application.realtime_cover_service import RealtimeCoverService

    assert (
        RealtimeCoverService._model_high_pitch_threshold(
            InferenceParams(), {"framework": "seed-vc", "metadata": {"f0_max_hz": 1200}}
        )
        == 1200.0
    )
    assert (
        RealtimeCoverService._model_high_pitch_threshold(
            InferenceParams(high_pitch_threshold=610.0), {"framework": "rvc"}
        )
        == 610.0
    )


def test_audio_profile_detects_high_pitch_and_high_band() -> None:
    sample_rate = 24000
    time_axis = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    audio = (
        0.22 * np.sin(2.0 * np.pi * 1100.0 * time_axis)
        + 0.12 * np.sin(2.0 * np.pi * 8000.0 * time_axis)
    ).astype(np.float32)

    profile = vocal_enhancement_worker._audio_profile_array(audio, sample_rate)

    assert profile["high_pitch"] is True
    assert profile["high_frequency"] is True
    assert profile["high_band_noise"] is False
    assert float(profile["recommended_f0_max"]) > 1100.0


def test_audio_profile_does_not_classify_bright_high_note_as_noise() -> None:
    from scipy.signal import butter, sosfilt

    sample_rate = 24000
    time_axis = np.arange(sample_rate * 3, dtype=np.float64) / sample_rate
    rng = np.random.default_rng(321)
    air = sosfilt(
        butter(4, (5200.0, 11000.0), btype="bandpass", fs=sample_rate, output="sos"),
        rng.normal(0.0, 1.0, len(time_axis)),
    )
    # This mirrors the reported model output: a real high note whose broadband
    # air happens to put the whole-track high-band ratio near the noise cutoff.
    high_note = sum(
        np.sin(2.0 * np.pi * 890.0 * harmonic * time_axis) / harmonic
        for harmonic in range(1, 12)
        if 890.0 * harmonic < sample_rate * 0.48
    )
    audio = (0.20 * high_note + 0.10 * air).astype(np.float32)

    profile = vocal_enhancement_worker._audio_profile_array(audio, sample_rate)

    assert profile["high_pitch"] is True
    assert profile["high_frequency"] is True
    assert profile["high_band_noise"] is False


def test_audio_profile_separates_bright_residual_noise_from_high_notes() -> None:
    from scipy.signal import butter, sosfilt

    sample_rate = 24000
    time_axis = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    rng = np.random.default_rng(123)
    noise = sosfilt(
        butter(4, (5200.0, 11000.0), btype="bandpass", fs=sample_rate, output="sos"),
        rng.normal(0.0, 1.0, len(time_axis)),
    )
    audio = (
        0.22 * np.sin(2.0 * np.pi * 220.0 * time_axis)
        + 0.32 * noise
    ).astype(np.float32)

    profile = vocal_enhancement_worker._audio_profile_array(audio, sample_rate)

    assert profile["high_frequency"] is True
    assert profile["high_pitch"] is False
    assert profile["high_band_noise"] is True
    assert float(profile["high_band_flatness"]) >= 0.04


def test_quality_gate_rejects_dropouts_and_new_high_frequency_whistles(
    tmp_path: Path, monkeypatch
) -> None:
    import wave

    sample_rate = 16000
    time_axis = np.arange(sample_rate * 4, dtype=np.float64) / sample_rate
    source = 0.20 * np.sin(2.0 * np.pi * 220.0 * time_axis)
    candidate = source.copy()
    # A short, loud high-frequency tone models the whistle/scratch artifacts seen
    # after chained enhancement.  A separate dropout models a swallowed syllable.
    whistle = (time_axis >= 1.0) & (time_axis < 1.8)
    candidate[whistle] += 0.45 * np.sin(2.0 * np.pi * 6500.0 * time_axis[whistle])
    candidate[(time_axis >= 2.5) & (time_axis < 2.9)] = 0.0
    source_path = tmp_path / "source.wav"
    candidate_path = tmp_path / "candidate.wav"

    def write_wav(path: Path, values: np.ndarray) -> None:
        pcm = np.asarray(np.clip(values, -1.0, 1.0) * 32767.0, dtype="<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm.tobytes())

    def read_wav(path: str, always_2d: bool, dtype: str):
        with wave.open(path, "rb") as handle:
            channels = handle.getnchannels()
            rate = handle.getframerate()
            raw = handle.readframes(handle.getnframes())
        values = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        values = values.reshape(-1, channels) if always_2d else values
        return values.astype(dtype), rate

    monkeypatch.setitem(sys.modules, "soundfile", types.SimpleNamespace(read=read_wav))

    write_wav(source_path, source)
    write_wav(candidate_path, candidate)

    accepted = vocal_enhancement_worker._quality_gate_file(
        source_path,
        candidate_path,
        "test",
    )

    assert accepted is False
    with wave.open(str(candidate_path), "rb") as handle:
        restored = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2")
    with wave.open(str(source_path), "rb") as handle:
        original = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2")
    assert np.array_equal(restored, original)


def test_quality_gate_accepts_small_natural_level_change(
    tmp_path: Path, monkeypatch
) -> None:
    import wave

    sample_rate = 16000
    time_axis = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    source = 0.18 * np.sin(2.0 * np.pi * 220.0 * time_axis)
    candidate = source * 1.04
    source_path = tmp_path / "source.wav"
    candidate_path = tmp_path / "candidate.wav"

    def write_wav(path: Path, values: np.ndarray) -> None:
        pcm = np.asarray(np.clip(values, -1.0, 1.0) * 32767.0, dtype="<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm.tobytes())

    def read_wav(path: str, always_2d: bool, dtype: str):
        with wave.open(path, "rb") as handle:
            channels = handle.getnchannels()
            rate = handle.getframerate()
            raw = handle.readframes(handle.getnframes())
        values = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        values = values.reshape(-1, channels) if always_2d else values
        return values.astype(dtype), rate

    monkeypatch.setitem(sys.modules, "soundfile", types.SimpleNamespace(read=read_wav))

    write_wav(source_path, source)
    write_wav(candidate_path, candidate)

    assert vocal_enhancement_worker._quality_gate_file(
        source_path,
        candidate_path,
        "test",
    ) is True


def test_quality_gate_rejects_a_local_whistle_without_global_level_change(
    tmp_path: Path, monkeypatch
) -> None:
    import wave

    sample_rate = 16000
    time_axis = np.arange(sample_rate * 4, dtype=np.float64) / sample_rate
    source = 0.20 * np.sin(2.0 * np.pi * 220.0 * time_axis)
    candidate = source.copy()
    whistle = (time_axis >= 1.0) & (time_axis < 1.55)
    candidate[whistle] += 0.22 * np.sin(2.0 * np.pi * 6500.0 * time_axis[whistle])
    source_path = tmp_path / "source.wav"
    candidate_path = tmp_path / "candidate.wav"

    def write_wav(path: Path, values: np.ndarray) -> None:
        pcm = np.asarray(np.clip(values, -1.0, 1.0) * 32767.0, dtype="<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm.tobytes())

    def read_wav(path: str, always_2d: bool, dtype: str):
        with wave.open(path, "rb") as handle:
            channels = handle.getnchannels()
            rate = handle.getframerate()
            raw = handle.readframes(handle.getnframes())
        values = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        values = values.reshape(-1, channels) if always_2d else values
        return values.astype(dtype), rate

    monkeypatch.setitem(sys.modules, "soundfile", types.SimpleNamespace(read=read_wav))
    write_wav(source_path, source)
    write_wav(candidate_path, candidate)

    assert vocal_enhancement_worker._quality_gate_file(
        source_path,
        candidate_path,
        "test",
    ) is False


def test_short_high_band_spike_suppression_is_local_and_preserves_sustained_note(
    tmp_path: Path, monkeypatch
) -> None:
    import wave

    sample_rate = 44100
    time_axis = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    source = 0.12 * np.sin(2.0 * np.pi * 220.0 * time_axis)
    # The short burst models the repeated scratch-like artifacts reported in
    # model renders. The sustained high note is a valid musical component.
    burst = (time_axis >= 0.80) & (time_axis < 0.84)
    sustained = (time_axis >= 1.20) & (time_axis < 1.80)
    source[burst] += 0.28 * np.sin(2.0 * np.pi * 8500.0 * time_axis[burst])
    source[sustained] += 0.08 * np.sin(2.0 * np.pi * 8500.0 * time_axis[sustained])
    source_path = tmp_path / "source.wav"
    output_path = tmp_path / "cleaned.wav"

    def write_wav(path: Path, values: np.ndarray) -> None:
        pcm = np.asarray(np.clip(values, -1.0, 1.0) * 32767.0, dtype="<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm.tobytes())

    def read_wav(path: str, always_2d: bool, dtype: str):
        with wave.open(path, "rb") as handle:
            rate = handle.getframerate()
            values = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2")
        values = values.astype(np.float32) / 32768.0
        values = values.reshape(-1, 1) if always_2d else values
        return values.astype(dtype), rate

    monkeypatch.setitem(
        sys.modules,
        "soundfile",
        types.SimpleNamespace(read=read_wav, write=lambda path, data, rate, subtype=None: write_wav(Path(path), np.asarray(data).reshape(-1))),
    )
    write_wav(source_path, source)

    frames = vocal_enhancement_worker._suppress_short_high_band_spikes(
        source_path, output_path
    )

    assert frames > 0
    with wave.open(str(source_path), "rb") as handle:
        original = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2").astype(float)
    with wave.open(str(output_path), "rb") as handle:
        cleaned = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2").astype(float)
    burst_slice = slice(int(0.80 * sample_rate), int(0.84 * sample_rate))
    sustained_slice = slice(int(1.20 * sample_rate), int(1.80 * sample_rate))
    assert np.sqrt(np.mean(cleaned[burst_slice] ** 2)) < np.sqrt(np.mean(original[burst_slice] ** 2)) * 0.82
    assert np.sqrt(np.mean(cleaned[sustained_slice] ** 2)) > np.sqrt(np.mean(original[sustained_slice] ** 2)) * 0.92


def test_noise_like_high_band_suppression_is_bounded(tmp_path: Path, monkeypatch) -> None:
    import wave
    from scipy.signal import butter, sosfilt

    sample_rate = 44100
    time_axis = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    rng = np.random.default_rng(19)
    noise = sosfilt(
        butter(
            4,
            (6200.0, 12000.0),
            btype="bandpass",
            fs=sample_rate,
            output="sos",
        ),
        rng.normal(0.0, 1.0, len(time_axis)),
    )
    source = (
        0.16 * np.sin(2.0 * np.pi * 220.0 * time_axis)
        + 0.14 * noise
    ).astype(np.float32)
    source_path = tmp_path / "source.wav"
    output_path = tmp_path / "cleaned.wav"

    def write_wav(path: Path, values: np.ndarray) -> None:
        pcm = np.asarray(np.clip(values, -1.0, 1.0) * 32767.0, dtype="<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm.tobytes())

    def read_wav(path: str, always_2d: bool, dtype: str):
        with wave.open(path, "rb") as handle:
            rate = handle.getframerate()
            values = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2")
        values = values.astype(np.float32) / 32768.0
        values = values.reshape(-1, 1) if always_2d else values
        return values.astype(dtype), rate

    monkeypatch.setitem(
        sys.modules,
        "soundfile",
        types.SimpleNamespace(
            read=read_wav,
            write=lambda path, data, rate, subtype=None: write_wav(
                Path(path), np.asarray(data).reshape(-1)
            ),
        ),
    )
    write_wav(source_path, source)

    frames, attenuation = vocal_enhancement_worker._suppress_noise_like_high_band(
        source_path,
        output_path,
    )

    assert frames > 0
    assert 0.0 < attenuation <= 4.2
    from scipy.signal import butter, sosfiltfilt

    highpass = butter(4, 5600.0, btype="highpass", fs=sample_rate, output="sos")
    before = sosfiltfilt(highpass, source)
    with wave.open(str(output_path), "rb") as handle:
        cleaned = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2")
    cleaned = cleaned.astype(np.float32) / 32768.0
    after = sosfiltfilt(highpass, cleaned)
    assert np.sqrt(np.mean(after**2)) < np.sqrt(np.mean(before**2)) * 0.98


def test_noise_like_high_band_keeps_voiced_high_note(tmp_path: Path) -> None:
    """High harmonics are retained while broadband breath is reduced."""
    import soundfile as sf
    from scipy.signal import butter, sosfilt

    sample_rate = 44100
    time_axis = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    rng = np.random.default_rng(23)
    breath = sosfilt(
        butter(4, (6200.0, 12000.0), btype="bandpass", fs=sample_rate, output="sos"),
        rng.normal(0.0, 1.0, len(time_axis)),
    )
    high_note = sum(
        np.sin(2.0 * np.pi * 900.0 * harmonic * time_axis) / harmonic
        for harmonic in range(1, 10)
    )
    tonal = (0.12 * high_note + 0.12 * breath).astype(np.float32)
    breath_only = (0.16 * np.sin(2.0 * np.pi * 220.0 * time_axis) + 0.14 * breath).astype(
        np.float32
    )
    tonal_path = tmp_path / "tonal.wav"
    tonal_cleaned = tmp_path / "tonal-cleaned.wav"
    breath_path = tmp_path / "breath.wav"
    breath_cleaned = tmp_path / "breath-cleaned.wav"
    sf.write(str(tonal_path), tonal, sample_rate)
    sf.write(str(breath_path), breath_only, sample_rate)

    tonal_frames, _ = vocal_enhancement_worker._suppress_noise_like_high_band(
        tonal_path,
        tonal_cleaned,
        max_attenuation_db=5.5,
        cutoff_hz=3800.0,
        ratio_floor=0.085,
        flatness_floor=0.11,
    )
    breath_frames, _ = vocal_enhancement_worker._suppress_noise_like_high_band(
        breath_path,
        breath_cleaned,
        max_attenuation_db=5.5,
        cutoff_hz=3800.0,
        ratio_floor=0.085,
        flatness_floor=0.11,
    )
    assert tonal_frames == 0
    assert breath_frames > 0


def test_high_note_body_restore_raises_voiced_band_without_raising_air(
    tmp_path: Path,
) -> None:
    import soundfile as sf
    from scipy.signal import butter, sosfiltfilt

    sample_rate = 16000
    time_axis = np.arange(sample_rate * 3, dtype=np.float64) / sample_rate
    high_note = (time_axis >= 1.0) & (time_axis < 2.0)
    guide = 0.16 * np.sin(2.0 * np.pi * 320.0 * time_axis)
    guide[high_note] = 0.16 * np.sin(
        2.0 * np.pi * 760.0 * time_axis[high_note]
    )
    target = guide.copy()
    target[high_note] = (
        0.055 * np.sin(2.0 * np.pi * 760.0 * time_axis[high_note])
        + 0.04 * np.sin(2.0 * np.pi * 7000.0 * time_axis[high_note])
    )
    source_path = tmp_path / "weak-high-note.wav"
    guide_path = tmp_path / "guide.wav"
    output_path = tmp_path / "restored.wav"
    sf.write(str(source_path), target.astype(np.float32), sample_rate, subtype="FLOAT")
    sf.write(str(guide_path), guide.astype(np.float32), sample_rate, subtype="FLOAT")

    frames, boost_db = vocal_enhancement_worker._restore_high_note_body(
        source_path,
        guide_path,
        output_path,
    )

    restored, restored_rate = sf.read(str(output_path), dtype="float32")
    body_filter = butter(
        4,
        (220.0, 3800.0),
        btype="bandpass",
        fs=sample_rate,
        output="sos",
    )
    air_filter = butter(4, 5000.0, btype="highpass", fs=sample_rate, output="sos")
    body_before = sosfiltfilt(body_filter, target)
    body_after = sosfiltfilt(body_filter, restored)
    air_before = sosfiltfilt(air_filter, target)
    air_after = sosfiltfilt(air_filter, restored)
    high_slice = slice(int(1.15 * sample_rate), int(1.85 * sample_rate))
    normal_slice = slice(int(0.15 * sample_rate), int(0.85 * sample_rate))

    assert restored_rate == sample_rate
    assert frames > 0
    assert 2.0 <= boost_db <= 2.6
    assert np.sqrt(np.mean(body_after[high_slice] ** 2)) > (
        np.sqrt(np.mean(body_before[high_slice] ** 2)) * 1.20
    )
    assert np.sqrt(np.mean(body_after[normal_slice] ** 2)) == pytest.approx(
        np.sqrt(np.mean(body_before[normal_slice] ** 2)),
        rel=0.01,
    )
    assert np.sqrt(np.mean(air_after[high_slice] ** 2)) == pytest.approx(
        np.sqrt(np.mean(air_before[high_slice] ** 2)),
        rel=0.01,
    )


def test_formant_guard_ignores_isolated_pitch_tracker_spikes() -> None:
    assert formant_pitch_worker._high_intervals(
        [(0.50, 920.0)], 800.0, 0.0, 1.0
    ) == []
    intervals = formant_pitch_worker._high_intervals(
        [(0.50, 920.0), (0.54, 940.0)], 800.0, 0.0, 1.0
    )
    assert intervals
    assert intervals[0][0] < 0.50 < intervals[0][1]


def test_formant_guard_recovers_single_short_note_only_inside_confirmed_scope() -> None:
    assert formant_pitch_worker._high_intervals(
        [(0.51, 690.0)],
        720.0,
        0.0,
        1.0,
        allowed_regions=[(0.48, 0.56)],
    )
    assert formant_pitch_worker._high_intervals(
        [(0.51, 690.0)],
        720.0,
        0.0,
        1.0,
    ) == []


def test_formant_guard_scope_selects_but_does_not_clip_complete_note() -> None:
    intervals = formant_pitch_worker._high_intervals(
        [
            (0.30, 760.0),
            (0.36, 780.0),
            (0.42, 790.0),
            (0.48, 770.0),
        ],
        720.0,
        0.0,
        1.0,
        allowed_regions=[(0.39, 0.44)],
    )

    assert intervals == [pytest.approx((0.25, 0.53))]


def test_prepare_high_pitch_guard_honors_confirmed_short_region(
    tmp_path: Path,
) -> None:
    service = ConversionService.__new__(ConversionService)
    source = tmp_path / "source.wav"
    destination = tmp_path / "guarded.wav"
    report = destination.with_suffix(".regions.json")
    source.write_bytes(b"source")
    calls: list[dict[str, object]] = []

    class FakeFfmpeg:
        def pitch_shift(self, _source: Path, target: Path, _semitones: int, **kwargs):
            calls.append(kwargs)
            target.write_bytes(b"guarded")
            report.write_text(
                '{"region_count": 1, "processed_seconds": 0.12, '
                '"regions": [{"start": 0.48, "end": 0.56}]}',
                encoding="utf-8",
            )
            return True

    service._ffmpeg = FakeFfmpeg()
    service._estimate_peak_f0 = lambda _source: 420.0
    service._log = lambda *_args: None

    guarded, applied = service._prepare_high_pitch_guard(
        source,
        destination,
        InferenceParams(auto_high_pitch_guard=True),
        tmp_path / "run.log",
        threshold=720.0,
        only_regions=[(0.48, 0.56)],
    )

    assert applied is True
    assert guarded == destination
    assert calls[0]["regions"] == [(0.48, 0.56)]


def test_formant_guard_accepts_notes_in_detector_hysteresis_band() -> None:
    intervals = formant_pitch_worker._high_intervals(
        [(0.50, 670.0), (0.54, 690.0)],
        720.0,
        0.0,
        1.0,
        allowed_regions=[(0.45, 0.60)],
    )
    assert intervals


def test_formant_guard_keeps_hysteresis_notes_untouched_without_scope() -> None:
    assert formant_pitch_worker._high_intervals(
        [(0.50, 670.0), (0.54, 690.0)], 720.0, 0.0, 1.0
    ) == []


def test_formant_guard_applies_hysteresis_fallback_per_scope() -> None:
    intervals = formant_pitch_worker._high_intervals(
        [(0.50, 800.0), (0.54, 820.0), (0.80, 670.0), (0.84, 690.0)],
        720.0,
        0.0,
        1.0,
        allowed_regions=[(0.45, 0.60), (0.75, 0.90)],
    )
    assert len(intervals) == 2
    assert intervals[0][0] < 0.50 < intervals[0][1]
    assert intervals[1][0] < 0.80 < intervals[1][1]


def test_formant_guard_rejects_collapsed_render(tmp_path: Path, monkeypatch) -> None:
    import wave

    def write_wav(path: Path, values: np.ndarray) -> None:
        pcm = np.asarray(np.clip(values, -1.0, 1.0) * 32767.0, dtype="<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16000)
            handle.writeframes(pcm.tobytes())

    def read_wav(path: str, always_2d: bool, dtype: str):
        with wave.open(path, "rb") as handle:
            channels = handle.getnchannels()
            rate = handle.getframerate()
            raw = handle.readframes(handle.getnframes())
        values = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        values = values.reshape(-1, channels) if always_2d else values
        return values.astype(dtype), rate

    monkeypatch.setitem(sys.modules, "soundfile", types.SimpleNamespace(read=read_wav))

    source = tmp_path / "source.wav"
    rendered = tmp_path / "rendered.wav"
    signal = np.sin(np.linspace(0.0, np.pi * 8.0, 16000, dtype=np.float32)) * 0.4
    write_wav(source, signal)
    write_wav(rendered, np.zeros_like(signal))

    valid, reason = formant_pitch_worker._validate_render(source, rendered)

    assert valid is False
    assert "能量" in reason


def test_worker_basic_and_advanced_layers_use_expected_order(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"RIFF-source")
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"RIFF-ref")
    calls: list[str] = []

    def fake_silence(_source: Path, output: Path) -> None:
        calls.append("silence")
        output.write_bytes(b"RIFF-silenced")

    def fake_match(
        _source: Path,
        _ref: Path,
        output: Path,
        *,
        allow_high_band: bool = True,
    ) -> None:
        calls.append(f"match:{allow_high_band}")
        output.write_bytes(b"RIFF-matched")

    def fake_deepfilter(_source: Path, output: Path) -> None:
        calls.append("deepfilter")
        output.write_bytes(b"RIFF-filtered")

    def fake_restore(
        _source: Path,
        _ref: Path,
        output: Path,
        *,
        allow_high_band: bool = True,
    ) -> None:
        calls.append(f"detail:{allow_high_band}")
        output.write_bytes(b"RIFF-detailed")

    def fake_focus(_source: Path, output: Path, amount: float) -> None:
        calls.append(f"timbre:{amount:.2f}")
        output.write_bytes(_source.read_bytes())

    def fake_pedalboard_basic(_source: Path, output: Path) -> float:
        calls.append("pedalboard_basic")
        output.write_bytes(b"RIFF-dsp-basic")
        return 0.63

    def fake_pedalboard_mastering(_source: Path, output: Path) -> float:
        calls.append("pedalboard_mastering")
        output.write_bytes(b"RIFF-dsp-master")
        return 0.78

    def fake_parallel(_dry: Path, wet: Path, output: Path, amount: float) -> None:
        calls.append(f"parallel:{amount:.2f}")
        output.write_bytes(wet.read_bytes())

    def fake_ai_eq(_source: Path, output: Path, amount: float) -> None:
        calls.append(f"eq:{amount:.2f}")
        output.write_bytes(_source.read_bytes())

    def fake_ai_compressor(_source: Path, output: Path, amount: float) -> None:
        calls.append(f"compressor:{amount:.2f}")
        output.write_bytes(_source.read_bytes())

    def fake_ai_exciter(_source: Path, output: Path, amount: float) -> None:
        calls.append(f"exciter:{amount:.2f}")
        output.write_bytes(_source.read_bytes())

    def fake_stereo(_source: Path, output: Path, amount: float) -> None:
        calls.append(f"stereo:{amount:.2f}")
        output.write_bytes(_source.read_bytes())

    def fake_loudness(
        _control: Path, source_path: Path, output: Path, amount: float
    ) -> None:
        calls.append(f"loudness:{amount:.2f}")
        output.write_bytes(source_path.read_bytes())

    def fake_high_body(
        source_path: Path,
        _guide: Path,
        output: Path,
        **_kwargs,
    ) -> tuple[int, float]:
        calls.append("high_body")
        output.write_bytes(source_path.read_bytes())
        return 4, 1.2

    with (
        patch.object(
            vocal_enhancement_worker, "_silence_vocalfloor_file", fake_silence
        ),
        patch.object(vocal_enhancement_worker, "_match_reference", fake_match),
        patch.object(vocal_enhancement_worker, "_deepfilter", fake_deepfilter),
        patch.object(
            vocal_enhancement_worker, "_restore_reference_detail", fake_restore
        ),
        patch.object(vocal_enhancement_worker, "_focus_target_timbre", fake_focus),
        patch.object(
            vocal_enhancement_worker, "_pedalboard_basic", fake_pedalboard_basic
        ),
        patch.object(
            vocal_enhancement_worker,
            "_pedalboard_mastering",
            fake_pedalboard_mastering,
        ),
        patch.object(vocal_enhancement_worker, "_parallel_mix", fake_parallel),
        patch.object(vocal_enhancement_worker, "_ai_eq", fake_ai_eq),
        patch.object(
            vocal_enhancement_worker, "_ai_compressor", fake_ai_compressor
        ),
        patch.object(vocal_enhancement_worker, "_ai_exciter", fake_ai_exciter),
        patch.object(vocal_enhancement_worker, "_stereo_image", fake_stereo),
        patch.object(vocal_enhancement_worker, "_ai_loudness_envelope", fake_loudness),
        patch.object(vocal_enhancement_worker, "_restore_high_note_body", fake_high_body),
    ):
        # Basic 保持目标音色，即使有 reference 也不做参考匹配/细节迁移。
        basic = tmp_path / "basic.wav"
        vocal_enhancement_worker.run(source, basic, "basic", "cpu", reference)
        assert calls == [
            "silence",
            "deepfilter",
            "pedalboard_basic",
            "parallel:0.63",
            "timbre:0.60",
            "eq:0.55",
            "compressor:0.45",
            "exciter:0.25",
            "stereo:0.30",
            "loudness:0.58",
        ]
        assert basic.read_bytes() == b"RIFF-dsp-basic"

        calls.clear()
        # Advanced 才启用保守参考匹配与真实高频细节保护。
        advanced = tmp_path / "advanced.wav"
        vocal_enhancement_worker.run(source, advanced, "advanced", "auto", reference)
        assert calls == [
            "silence",
            "match:True",
            "deepfilter",
            "detail:True",
            "pedalboard_mastering",
            "parallel:0.78",
            "timbre:0.60",
            "eq:0.55",
            "compressor:0.45",
            "exciter:0.25",
            "stereo:0.30",
            "loudness:0.58",
        ]
        assert advanced.read_bytes() == b"RIFF-dsp-master"


def test_stereo_image_keeps_mono_source_phase_coherent() -> None:
    sample_rate = 48000
    time = np.arange(sample_rate, dtype=np.float64) / sample_rate
    mono = 0.18 * np.sin(2.0 * np.pi * 220.0 * time)
    mono += 0.05 * np.sin(2.0 * np.pi * 4200.0 * time)

    stereo = vocal_enhancement_worker._stereo_image_array(
        mono[:, np.newaxis], sample_rate, 0.65
    )

    assert stereo.shape == (sample_rate, 2)
    assert np.allclose(stereo.mean(axis=1), mono, atol=1e-7)
    assert np.array_equal(stereo[:, 0], stereo[:, 1])


def test_stereo_image_only_widens_an_existing_side_signal() -> None:
    sample_rate = 48000
    time = np.arange(sample_rate, dtype=np.float64) / sample_rate
    mid = 0.18 * np.sin(2.0 * np.pi * 220.0 * time)
    side = 0.03 * np.sin(2.0 * np.pi * 1700.0 * time)
    source = np.column_stack((mid + side, mid - side))

    stereo = vocal_enhancement_worker._stereo_image_array(
        source, sample_rate, 0.65
    )

    result_mid = stereo.mean(axis=1)
    result_side = (stereo[:, 0] - stereo[:, 1]) * 0.5
    assert np.allclose(result_mid, mid, atol=1e-7)
    assert float(np.sqrt(np.mean(result_side ** 2))) > float(
        np.sqrt(np.mean(side ** 2))
    )


def test_reference_detail_does_not_inject_reference_pitch(
    tmp_path: Path, monkeypatch
) -> None:
    sample_rate = 48000
    time = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    envelope = 0.55 + 0.45 * np.sin(2.0 * np.pi * 1.5 * time) ** 2
    source_audio = envelope * (
        0.18 * np.sin(2.0 * np.pi * 220.0 * time)
        + 0.004 * np.sin(2.0 * np.pi * 6000.0 * time)
    )
    reference_audio = envelope * (
        0.18 * np.sin(2.0 * np.pi * 220.0 * time)
        + 0.08 * np.sin(2.0 * np.pi * 7000.0 * time)
    )
    source = tmp_path / "source.wav"
    reference = tmp_path / "reference.wav"
    output = tmp_path / "detailed.wav"
    captured: dict[str, np.ndarray] = {}

    def fake_read(path: str, always_2d: bool):
        values = reference_audio if Path(path) == reference else source_audio
        return values[:, np.newaxis], sample_rate

    monkeypatch.setitem(
        sys.modules,
        "soundfile",
        types.SimpleNamespace(read=fake_read),
    )
    monkeypatch.setitem(
        sys.modules,
        "librosa",
        types.SimpleNamespace(resample=lambda values, **_kwargs: values),
    )
    monkeypatch.setattr(
        vocal_enhancement_worker,
        "_write_float_wav",
        lambda _path, audio, _sample_rate: captured.setdefault(
            "audio", np.asarray(audio).reshape(-1)
        ),
    )

    vocal_enhancement_worker._restore_reference_detail(
        source,
        reference,
        output,
    )

    result = captured["audio"]
    frequencies = np.fft.rfftfreq(len(result), 1.0 / sample_rate)
    spectrum = np.abs(np.fft.rfft(result * np.hanning(len(result))))
    source_spectrum = np.abs(
        np.fft.rfft(source_audio * np.hanning(len(source_audio)))
    )
    reference_spectrum = np.abs(
        np.fft.rfft(reference_audio * np.hanning(len(reference_audio)))
    )
    at_7000 = int(np.argmin(np.abs(frequencies - 7000.0)))

    assert spectrum[at_7000] <= source_spectrum[at_7000] * 1.20 + 1e-8
    assert spectrum[at_7000] < reference_spectrum[at_7000] * 0.02


def test_adaptive_beauty_activity_tracks_local_vocal_level() -> None:
    sample_rate = 16000
    time = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    audio = np.zeros_like(time)
    breath = (time >= 0.30) & (time < 0.70)
    voice = (time >= 1.00) & (time < 1.50)
    audio[breath] = 0.006 * np.sin(2.0 * np.pi * 220.0 * time[breath])
    audio[voice] = 0.20 * np.sin(2.0 * np.pi * 220.0 * time[voice])

    curve, stats = vocal_enhancement_worker._adaptive_activity_curve(
        audio[:, np.newaxis],
        sample_rate,
    )

    silence_amount = float(np.median(curve[: int(0.20 * sample_rate)]))
    breath_amount = float(
        np.median(curve[int(0.40 * sample_rate) : int(0.60 * sample_rate)])
    )
    voice_amount = float(
        np.median(curve[int(1.10 * sample_rate) : int(1.40 * sample_rate)])
    )
    assert silence_amount < 0.02
    assert silence_amount < breath_amount < voice_amount
    assert voice_amount > 0.90
    assert stats["dynamic_db"] > 20.0


def test_ai_loudness_envelope_restores_phrase_dynamics_without_raising_pauses() -> None:
    sample_rate = 8000
    time = np.arange(sample_rate * 4, dtype=np.float64) / sample_rate
    carrier = np.sin(2.0 * np.pi * 220.0 * time)
    quiet_phrase = (time >= 0.40) & (time < 1.40)
    loud_phrase = (time >= 2.20) & (time < 3.20)

    control = np.zeros_like(time)
    control[quiet_phrase] = 0.04 * carrier[quiet_phrase]
    control[loud_phrase] = 0.20 * carrier[loud_phrase]
    flattened = np.zeros_like(time)
    flattened[quiet_phrase | loud_phrase] = 0.10 * carrier[quiet_phrase | loud_phrase]

    restored, stats = vocal_enhancement_worker._ai_loudness_envelope_array(
        control[:, np.newaxis],
        flattened[:, np.newaxis],
        sample_rate,
        1.0,
    )

    def rms(values: np.ndarray, mask: np.ndarray) -> float:
        return float(np.sqrt(np.mean(values[mask] ** 2) + 1e-12))

    target_contrast = 20.0 * np.log10(rms(control, loud_phrase) / rms(control, quiet_phrase))
    before_contrast = 20.0 * np.log10(rms(flattened, loud_phrase) / rms(flattened, quiet_phrase))
    after_contrast = 20.0 * np.log10(
        rms(restored[:, 0], loud_phrase) / rms(restored[:, 0], quiet_phrase)
    )
    pause = (time >= 1.65) & (time < 1.95)

    assert restored.shape == (len(time), 1)
    assert abs(target_contrast - after_contrast) < abs(target_contrast - before_contrast)
    assert np.array_equal(restored[pause, 0], flattened[pause])
    assert stats["correction_db_min"] < -0.5
    assert stats["correction_db_max"] > 0.5

    identity, identity_stats = vocal_enhancement_worker._ai_loudness_envelope_array(
        control[:, np.newaxis],
        flattened[:, np.newaxis],
        sample_rate,
        0.0,
    )
    assert np.array_equal(identity[:, 0], flattened)
    assert identity_stats["correction_db_min"] == 0.0
    assert identity_stats["correction_db_max"] == 0.0


def test_adaptive_mastering_profile_changes_with_source_character() -> None:
    sample_rate = 24000
    time = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    steady = 0.14 * np.sin(2.0 * np.pi * 220.0 * time)
    steady += 0.04 * np.sin(2.0 * np.pi * 1200.0 * time)
    dynamic = steady.copy()
    dynamic[:sample_rate] *= 0.12
    harsh = steady + 0.13 * np.sin(2.0 * np.pi * 6000.0 * time)

    steady_profile = vocal_enhancement_worker._adaptive_mastering_profile(
        steady[:, np.newaxis], sample_rate, advanced=True
    )
    dynamic_profile = vocal_enhancement_worker._adaptive_mastering_profile(
        dynamic[:, np.newaxis], sample_rate, advanced=True
    )
    harsh_profile = vocal_enhancement_worker._adaptive_mastering_profile(
        harsh[:, np.newaxis], sample_rate, advanced=True
    )

    assert dynamic_profile["ratio"] > steady_profile["ratio"] + 0.15
    assert dynamic_profile["release_ms"] > steady_profile["release_ms"]
    assert harsh_profile["harsh_db"] < steady_profile["harsh_db"] - 0.40
    assert len(
        {
            round(steady_profile["wet_mix"], 3),
            round(dynamic_profile["wet_mix"], 3),
            round(harsh_profile["wet_mix"], 3),
        }
    ) >= 2


def test_dynamic_stereo_width_withdraws_during_high_frequency_dominance() -> None:
    sample_rate = 24000
    time = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    base = 0.20 * np.sin(2.0 * np.pi * 220.0 * time)
    sibilance = np.zeros_like(base)
    sibilance[sample_rate:] = 0.18 * np.sin(
        2.0 * np.pi * 6000.0 * time[sample_rate:]
    )
    audio = (base + sibilance)[:, np.newaxis]

    width, stats = vocal_enhancement_worker._adaptive_stereo_width_curve(
        audio,
        sample_rate,
        0.60,
    )

    normal_width = float(np.median(width[: sample_rate - 1000]))
    guarded_width = float(np.median(width[sample_rate + 1000 :]))
    assert normal_width > 0.50
    assert guarded_width < normal_width * 0.70
    assert stats["peak_guard"] > 0.80


def test_vocalfloor_expander_preserves_onsets_breaths_and_shape() -> None:
    sample_rate = 1000
    floor = 10.0 ** (-46.0 / 20.0)
    voice = 10.0 ** (-14.0 / 20.0)
    audio = np.full(sample_rate * 2, floor, dtype=np.float64)
    audio[sample_rate : sample_rate + 300] = voice
    stereo = np.vstack([audio, audio * 0.5])

    processed = vocal_enhancement_worker._silence_vocalfloor(stereo, sample_rate)

    assert processed.shape == stereo.shape
    # The 80 ms lookahead must fully open before the first sung sample.
    onset_ratio = processed[0, sample_rate : sample_rate + 20] / voice
    assert float(np.min(onset_ratio)) > 0.98
    # Isolated low-level material is reduced, never erased as in the old -75 dB gate.
    quiet_ratio = float(np.median(processed[0, 100:500] / floor))
    assert 10.0 ** (-6.0 / 20.0) <= quiet_ratio < 0.9
    # Both channels receive the same envelope, preserving the stereo image.
    assert np.allclose(processed[1], processed[0] * 0.5)


def test_vocalfloor_bridges_short_intra_phrase_pause() -> None:
    sample_rate = 1000
    floor = 10.0 ** (-46.0 / 20.0)
    voice = 10.0 ** (-14.0 / 20.0)
    audio = np.full(sample_rate * 2, floor, dtype=np.float64)
    audio[300:700] = voice
    audio[1000:1400] = voice

    processed = vocal_enhancement_worker._silence_vocalfloor(audio, sample_rate)

    pause_ratio = processed[760:940] / floor
    assert float(np.min(pause_ratio)) > 0.98


def test_psola_region_curve_is_zero_for_unchanged_voiced_audio() -> None:
    sample_rate = 2000
    original = np.zeros(sample_rate * 4, dtype=np.float64)
    time = np.arange(len(original), dtype=np.float64) / sample_rate
    original = 0.20 * np.sin(2.0 * np.pi * 180.0 * time)
    pitch_times = np.arange(0.20, 3.80, 0.01)
    frequencies = np.full_like(pitch_times, 220.0)

    curve = vocal_tuning_worker._resynthesis_region_curve(
        original[np.newaxis, :],
        sample_rate,
        pitch_times=pitch_times,
        source_frequencies=frequencies,
        corrected_frequencies=frequencies.copy(),
        duration_source_points=np.asarray([0.0, 2.0, 4.0]),
        duration_factors=np.asarray([1.0, 1.0]),
    )

    assert np.count_nonzero(curve) == 0
    artifact = original + 10.0 ** (-60.0 / 20.0)
    blended = original + (artifact - original) * curve
    assert np.array_equal(blended, original)


def test_psola_region_curve_ignores_weak_pitch_correction() -> None:
    sample_rate = 2000
    time = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    original = 0.20 * np.sin(2.0 * np.pi * 180.0 * time)
    pitch_times = np.arange(0.20, 1.80, 0.01)
    source_frequencies = np.full_like(pitch_times, 220.0)
    corrected_frequencies = source_frequencies * 2.0 ** (4.0 / 1200.0)

    curve = vocal_tuning_worker._resynthesis_region_curve(
        original,
        sample_rate,
        pitch_times=pitch_times,
        source_frequencies=source_frequencies,
        corrected_frequencies=corrected_frequencies,
        duration_source_points=np.asarray([0.0, 2.0]),
        duration_factors=np.asarray([1.0]),
    )

    assert np.count_nonzero(curve) == 0


def test_psola_region_curve_expands_stable_core_to_complete_correction_lobe() -> None:
    sample_rate = 2000
    time = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    original = 0.20 * np.sin(2.0 * np.pi * 180.0 * time)
    pitch_times = np.arange(0.20, 1.80, 0.01)
    source_frequencies = np.full_like(pitch_times, 220.0)
    correction_cents = np.zeros_like(pitch_times)
    shoulders = (pitch_times >= 0.60) & (pitch_times <= 1.40)
    stable_core = (pitch_times >= 0.80) & (pitch_times <= 1.20)
    correction_cents[shoulders] = 3.0
    correction_cents[stable_core] = 18.0
    strength = 0.50
    corrected_frequencies = source_frequencies * 2.0 ** (
        (correction_cents * strength) / 1200.0
    )

    curve = vocal_tuning_worker._resynthesis_region_curve(
        original,
        sample_rate,
        pitch_times=pitch_times,
        source_frequencies=source_frequencies,
        corrected_frequencies=corrected_frequencies,
        pitch_strength=strength,
        duration_source_points=np.asarray([0.0, 2.0]),
        duration_factors=np.asarray([1.0]),
    )
    stronger_curve = vocal_tuning_worker._resynthesis_region_curve(
        original,
        sample_rate,
        pitch_times=pitch_times,
        source_frequencies=source_frequencies,
        corrected_frequencies=source_frequencies
        * 2.0 ** (correction_cents / 1200.0),
        pitch_strength=1.0,
        duration_source_points=np.asarray([0.0, 2.0]),
        duration_factors=np.asarray([1.0]),
    )

    assert curve[int(0.70 * sample_rate)] == pytest.approx(1.0)
    assert curve[int(1.30 * sample_rate)] == pytest.approx(1.0)
    assert curve[int(0.40 * sample_rate)] == 0.0
    assert curve[int(1.60 * sample_rate)] == 0.0
    assert np.array_equal(curve > 0.0, stronger_curve > 0.0)


def test_psola_region_curve_covers_meaningful_pitch_and_timing_changes() -> None:
    sample_rate = 2000
    time = np.arange(sample_rate * 4, dtype=np.float64) / sample_rate
    original = 0.20 * np.sin(2.0 * np.pi * 180.0 * time)
    pitch_times = np.arange(0.20, 3.80, 0.01)
    source_frequencies = np.full_like(pitch_times, 220.0)
    corrected_frequencies = source_frequencies.copy()
    pitch_change = (pitch_times >= 0.90) & (pitch_times <= 1.10)
    corrected_frequencies[pitch_change] *= 2.0 ** (18.0 / 1200.0)

    curve = vocal_tuning_worker._resynthesis_region_curve(
        original[np.newaxis, :],
        sample_rate,
        pitch_times=pitch_times,
        source_frequencies=source_frequencies,
        corrected_frequencies=corrected_frequencies,
        duration_source_points=np.asarray([0.0, 2.0, 3.0, 4.0]),
        duration_factors=np.asarray([1.0, 1.01, 1.0]),
    )

    assert curve[int(1.00 * sample_rate)] == pytest.approx(1.0)
    assert curve[int(2.50 * sample_rate)] == pytest.approx(1.0)
    assert curve[int(0.50 * sample_rate)] == 0.0
    assert curve[int(1.50 * sample_rate)] == 0.0
    assert curve[int(3.50 * sample_rate)] == 0.0


def test_psola_region_curve_ignores_short_isolated_pitch_change() -> None:
    sample_rate = 2000
    time = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    original = 0.20 * np.sin(2.0 * np.pi * 180.0 * time)
    pitch_times = np.arange(0.20, 1.80, 0.01)
    source_frequencies = np.full_like(pitch_times, 220.0)
    corrected_frequencies = source_frequencies.copy()
    short_change = (pitch_times >= 0.90) & (pitch_times <= 1.01)
    corrected_frequencies[short_change] *= 2.0 ** (24.0 / 1200.0)

    curve = vocal_tuning_worker._resynthesis_region_curve(
        original,
        sample_rate,
        pitch_times=pitch_times,
        source_frequencies=source_frequencies,
        corrected_frequencies=corrected_frequencies,
        duration_source_points=np.asarray([0.0, 2.0]),
        duration_factors=np.asarray([1.0]),
    )

    assert np.count_nonzero(curve) == 0


def test_psola_region_curve_rejects_lobe_with_internal_pitch_gap() -> None:
    sample_rate = 2000
    time = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    original = 0.20 * np.sin(2.0 * np.pi * 180.0 * time)
    # Keep enough points on both sides to make the correction look substantial,
    # while leaving a 40 ms F0 hole in the middle of the candidate lobe.
    pitch_times = np.round(
        np.r_[np.arange(0.20, 0.91, 0.01), np.arange(0.95, 1.80, 0.01)],
        4,
    )
    source_frequencies = np.full_like(pitch_times, 220.0)
    corrected_frequencies = source_frequencies * 2.0 ** (18.0 / 1200.0)

    curve = vocal_tuning_worker._resynthesis_region_curve(
        original,
        sample_rate,
        pitch_times=pitch_times,
        source_frequencies=source_frequencies,
        corrected_frequencies=corrected_frequencies,
        duration_source_points=np.asarray([0.0, 2.0]),
        duration_factors=np.asarray([1.0]),
    )

    assert np.count_nonzero(curve) == 0


def test_psola_region_curve_rejects_pitch_glide() -> None:
    sample_rate = 2000
    time = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    original = 0.20 * np.sin(2.0 * np.pi * 180.0 * time)
    pitch_times = np.arange(0.20, 1.80, 0.01)
    source_midi = 60.0 + np.clip((pitch_times - 0.65) / 0.45, 0.0, 1.0) * 2.4
    source_frequencies = vocal_tuning_worker._midi_to_hz(source_midi)
    corrected_frequencies = source_frequencies * 2.0 ** (18.0 / 1200.0)

    curve = vocal_tuning_worker._resynthesis_region_curve(
        original,
        sample_rate,
        pitch_times=pitch_times,
        source_frequencies=source_frequencies,
        corrected_frequencies=corrected_frequencies,
        duration_source_points=np.asarray([0.0, 2.0]),
        duration_factors=np.asarray([1.0]),
    )

    assert np.count_nonzero(curve) == 0


def test_psola_region_curve_keeps_stable_long_note() -> None:
    sample_rate = 2000
    time = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    original = 0.20 * np.sin(2.0 * np.pi * 180.0 * time)
    pitch_times = np.arange(0.20, 1.80, 0.01)
    source_frequencies = np.full_like(pitch_times, 220.0)
    corrected_frequencies = source_frequencies * 2.0 ** (18.0 / 1200.0)

    curve = vocal_tuning_worker._resynthesis_region_curve(
        original,
        sample_rate,
        pitch_times=pitch_times,
        source_frequencies=source_frequencies,
        corrected_frequencies=corrected_frequencies,
        duration_source_points=np.asarray([0.0, 2.0]),
        duration_factors=np.asarray([1.0]),
    )

    assert curve[int(0.50 * sample_rate)] == pytest.approx(1.0)
    assert curve[int(1.50 * sample_rate)] == pytest.approx(1.0)


def test_psola_crossfade_compensates_phase_cancellation_without_leaking() -> None:
    sample_rate = 8000
    time = np.arange(sample_rate, dtype=np.float64) / sample_rate
    original = np.sin(2.0 * np.pi * 220.0 * time)
    resynthesized = np.sin(2.0 * np.pi * 220.0 * time + 2.6)
    curve = np.zeros(sample_rate, dtype=np.float64)
    fade = int(round(0.005 * sample_rate))
    start = int(round(0.30 * sample_rate))
    end = int(round(0.70 * sample_rate))
    curve[start:end] = 1.0
    curve[start - fade : start] = np.sin(
        np.linspace(0.0, np.pi / 2.0, fade, endpoint=False)
    ) ** 2
    curve[end : end + fade] = np.cos(
        np.linspace(0.0, np.pi / 2.0, fade, endpoint=False)
    ) ** 2

    ordinary = original + (resynthesized - original) * curve
    compensated = vocal_tuning_worker._blend_resynthesis(
        original,
        resynthesized,
        curve,
        sample_rate,
    )[0]
    transitions = np.r_[start - fade : start, end : end + fade]
    ordinary_rms = np.sqrt(np.mean(ordinary[transitions] ** 2))
    compensated_rms = np.sqrt(np.mean(compensated[transitions] ** 2))

    assert compensated_rms > ordinary_rms * 1.05
    assert np.array_equal(compensated[: start - fade], original[: start - fade])
    assert np.allclose(compensated[start:end], resynthesized[start:end])
    assert np.isfinite(compensated).all()


def test_reference_gap_cleanup_attenuates_model_only_short_burst() -> None:
    sample_rate = 2000
    time = np.arange(sample_rate * 3, dtype=np.float64) / sample_rate
    voiced = ((time >= 0.40) & (time < 1.20)) | (
        (time >= 1.24) & (time < 2.20)
    )
    reference = np.zeros_like(time)
    reference[voiced] = 0.20 * np.sin(2.0 * np.pi * 220.0 * time[voiced])
    source = reference.copy()
    model_burst = (time >= 1.20) & (time < 1.24)
    source[model_burst] = 0.08 * np.sin(2.0 * np.pi * 180.0 * time[model_burst])

    cleaned, stats = vocal_tuning_worker._suppress_reference_gap_residual(
        source[np.newaxis, :],
        reference[np.newaxis, :],
        sample_rate,
    )

    gap_start = int(1.205 * sample_rate)
    gap_end = int(1.235 * sample_rate)
    before_rms = np.sqrt(np.mean(source[gap_start:gap_end] ** 2))
    after_rms = np.sqrt(np.mean(cleaned[0, gap_start:gap_end] ** 2))
    assert stats["reference_gap_regions"] >= 1.0
    assert stats["reference_gap_max_attenuation_db"] >= 3.0
    assert after_rms < before_rms * 0.75
    assert np.allclose(cleaned[0, int(0.55 * sample_rate) : int(0.90 * sample_rate)], source[int(0.55 * sample_rate) : int(0.90 * sample_rate)])


def test_reference_gap_cleanup_leaves_matching_pause_untouched() -> None:
    sample_rate = 2000
    time = np.arange(sample_rate * 3, dtype=np.float64) / sample_rate
    voiced = ((time >= 0.40) & (time < 1.20)) | (
        (time >= 1.24) & (time < 2.20)
    )
    reference = np.zeros_like(time)
    reference[voiced] = 0.20 * np.sin(2.0 * np.pi * 220.0 * time[voiced])

    cleaned, stats = vocal_tuning_worker._suppress_reference_gap_residual(
        reference,
        reference,
        sample_rate,
    )

    assert stats["reference_gap_regions"] == 0.0
    assert np.array_equal(cleaned, reference)


def test_reference_gap_cleanup_ignores_long_pause() -> None:
    sample_rate = 2000
    time = np.arange(sample_rate * 3, dtype=np.float64) / sample_rate
    first = (time >= 0.40) & (time < 1.00)
    second = (time >= 1.50) & (time < 2.20)
    reference = np.zeros_like(time)
    reference[first | second] = 0.20 * np.sin(
        2.0 * np.pi * 220.0 * time[first | second]
    )
    source = reference.copy()
    long_burst = (time >= 1.00) & (time < 1.50)
    source[long_burst] = 0.08 * np.sin(2.0 * np.pi * 180.0 * time[long_burst])

    cleaned, stats = vocal_tuning_worker._suppress_reference_gap_residual(
        source,
        reference,
        sample_rate,
    )

    assert stats["reference_gap_regions"] == 0.0
    assert np.array_equal(cleaned, source)


def test_natural_pitch_curve_caps_correction_and_zero_strength_is_identity() -> None:
    times = np.arange(0.0, 1.0, 0.01)
    source_midi = np.full_like(times, 60.0)
    reference_midi = np.full_like(times, 61.0)
    source_hz = vocal_tuning_worker._midi_to_hz(source_midi)
    reference_hz = vocal_tuning_worker._midi_to_hz(reference_midi)

    unchanged, empty_stats = vocal_tuning_worker._natural_pitch_curve(
        times, source_hz, times, reference_hz, 0.0
    )
    corrected, stats = vocal_tuning_worker._natural_pitch_curve(
        times, source_hz, times, reference_hz, 1.0
    )

    assert np.allclose(unchanged, source_hz)
    assert empty_stats["points"] == 0.0
    correction_cents = (
        vocal_tuning_worker._hz_to_midi(corrected) - source_midi
    ) * 100.0
    assert float(np.max(np.abs(correction_cents))) <= 50.01
    assert stats["max_cents"] <= 50.01


def test_natural_pitch_curve_preserves_fast_vibrato() -> None:
    times = np.arange(0.0, 2.0, 0.01)
    vibrato = 0.22 * np.sin(2.0 * np.pi * 5.2 * times)
    reference_midi = 69.0 + vibrato
    source_midi = reference_midi - 0.24

    corrected_hz, _ = vocal_tuning_worker._natural_pitch_curve(
        times,
        vocal_tuning_worker._midi_to_hz(source_midi),
        times,
        vocal_tuning_worker._midi_to_hz(reference_midi),
        0.70,
    )
    corrected_midi = vocal_tuning_worker._hz_to_midi(corrected_hz)

    # Remove each curve's centre and compare modulation depth, not absolute tuning.
    source_modulation = source_midi - np.median(source_midi)
    corrected_modulation = corrected_midi - np.median(corrected_midi)
    assert float(np.std(corrected_modulation)) >= float(np.std(source_modulation)) * 0.75
    assert np.corrcoef(source_modulation, corrected_modulation)[0, 1] > 0.95


def test_envelope_alignment_finds_reference_delay() -> None:
    sample_rate = 2000
    rng = np.random.default_rng(42)
    envelope = np.repeat(rng.uniform(0.05, 1.0, 100), sample_rate // 50)
    carrier = np.sin(2.0 * np.pi * 113.0 * np.arange(len(envelope)) / sample_rate)
    source = envelope * carrier
    delay = int(0.05 * sample_rate)
    reference = np.pad(source[:-delay], (delay, 0))

    lag, correlation = vocal_tuning_worker._estimate_envelope_lag(
        source, reference, sample_rate
    )

    assert lag == pytest.approx(-0.05, abs=0.011)
    assert correlation > 0.90


def test_local_alignment_map_is_bounded_and_preserves_duration() -> None:
    sample_rate = 2000
    time = np.arange(sample_rate * 6, dtype=np.float64) / sample_rate
    carrier = np.sin(2.0 * np.pi * 113.0 * time)
    envelope = np.zeros_like(time)
    for start in (0.30, 0.95, 1.60, 2.25, 2.90, 3.55, 4.20, 4.85):
        active = (time >= start) & (time < start + 0.48)
        envelope[active] = np.sin(np.pi * (time[active] - start) / 0.48) ** 2
    reference = carrier * envelope
    warped_time = np.clip(
        time + 0.080 * np.sin(np.pi * time / time[-1]) ** 2,
        0.0,
        time[-1],
    )
    source = np.interp(warped_time, time, reference)

    (
        source_points,
        target_points,
        factors,
        guide_source_points,
        guide_target_points,
        stats,
    ) = (
        vocal_tuning_worker._local_alignment_map(
            source,
            reference,
            sample_rate,
            0.80,
        )
    )

    assert stats["alignment_points"] >= 3
    assert stats["alignment_correlation"] > 0.60
    assert stats["phrase_pairs"] >= 1
    assert stats["phoneme_points"] >= 3
    assert source_points[0] == target_points[0] == 0.0
    assert source_points[-1] == pytest.approx(target_points[-1], abs=1e-9)
    assert np.all(np.diff(target_points) > 0.0)
    assert np.all(np.diff(guide_source_points) > 0.0)
    assert np.all(np.diff(guide_target_points) > 0.0)
    assert float(np.max(np.abs(factors - 1.0))) <= 0.020001


def test_local_alignment_ignores_sub_perceptual_timing_differences() -> None:
    sample_rate = 2000
    rng = np.random.default_rng(7)
    envelope = np.repeat(rng.uniform(0.05, 1.0, 600), sample_rate // 100)
    carrier = np.sin(
        2.0 * np.pi * 127.0 * np.arange(len(envelope), dtype=np.float64) / sample_rate
    )
    reference = envelope * carrier
    delay = int(round(0.01 * sample_rate))
    source = np.pad(reference[:-delay], (delay, 0))

    (
        _source_points,
        _target_points,
        factors,
        guide_source_points,
        guide_target_points,
        stats,
    ) = (
        vocal_tuning_worker._local_alignment_map(
            source,
            reference,
            sample_rate,
            0.80,
        )
    )

    assert stats["alignment_points"] == 0.0
    assert stats["guide_points"] >= 3.0
    assert np.array_equal(factors, np.array([1.0]))
    assert np.all(np.diff(guide_source_points) > 0.0)
    assert np.all(np.diff(guide_target_points) > 0.0)

    half_strength = vocal_tuning_worker._local_alignment_map(
        source,
        reference,
        sample_rate,
        0.40,
    )
    half_source_points, half_target_points = half_strength[3:5]
    assert np.array_equal(half_source_points, guide_source_points)
    full_offsets = guide_source_points - guide_target_points
    half_offsets = half_source_points - half_target_points
    assert np.allclose(half_offsets, full_offsets * 0.5, atol=1e-9)


def test_phrase_matching_remains_monotonic_when_boundaries_shift() -> None:
    source_active = np.zeros(500, dtype=bool)
    reference_active = np.zeros(500, dtype=bool)
    for start, end in ((20, 85), (135, 220), (275, 345), (390, 465)):
        reference_active[start:end] = True
        source_active[start + 3 : end + 5] = True

    source_spans = vocal_tuning_worker._phrase_spans(source_active, 0.01)
    reference_spans = vocal_tuning_worker._phrase_spans(reference_active, 0.01)
    pairs = vocal_tuning_worker._match_phrase_spans(
        source_spans,
        reference_spans,
        0.01,
    )

    assert len(pairs) == 4
    source_starts = [source_span[0] for source_span, _reference_span in pairs]
    reference_starts = [reference_span[0] for _source_span, reference_span in pairs]
    assert source_starts == sorted(source_starts)
    assert reference_starts == sorted(reference_starts)


def test_banded_phonetic_dtw_tracks_a_smooth_local_warp() -> None:
    frame_count = 160
    positions = np.arange(frame_count, dtype=np.float64)
    base = np.column_stack(
        [
            np.sin(positions * 0.071),
            np.cos(positions * 0.093),
            np.sin(positions * 0.137 + 0.4),
            np.cos(positions * 0.173 - 0.2),
        ]
    )
    base /= np.maximum(np.linalg.norm(base, axis=1, keepdims=True), 1e-9)
    warped_positions = np.clip(
        positions + 5.0 * np.sin(2.0 * np.pi * positions / frame_count),
        0.0,
        frame_count - 1.0,
    )
    reference = np.column_stack(
        [np.interp(warped_positions, positions, base[:, column]) for column in range(base.shape[1])]
    )
    reference /= np.maximum(np.linalg.norm(reference, axis=1, keepdims=True), 1e-9)

    source_path, reference_path, similarity = (
        vocal_tuning_worker._banded_phonetic_dtw(base, reference, 12)
    )

    assert source_path[0] == reference_path[0] == 0
    assert source_path[-1] == reference_path[-1] == frame_count - 1
    assert np.all(np.diff(source_path) >= 0)
    assert np.all(np.diff(reference_path) >= 0)
    assert float(np.median(similarity)) > 0.90
    assert int(np.max(np.abs(source_path - reference_path))) >= 2


def test_deepfilter_uses_model_rate_then_restores_input_rate(
    tmp_path: Path, monkeypatch
) -> None:
    calls: dict[str, object] = {}

    class FakeState:
        @staticmethod
        def sr() -> int:
            return 48000

    class FakeTensor:
        def __init__(self, audio: np.ndarray) -> None:
            self.audio = audio

        @property
        def shape(self) -> tuple[int, ...]:
            return self.audio.shape

        def detach(self) -> "FakeTensor":
            return self

        def cpu(self) -> np.ndarray:
            return self.audio

    info = types.SimpleNamespace(sample_rate=44100, num_frames=44100)

    def fake_load(_path: str, *, sr: int):
        calls["load_sr"] = sr
        return FakeTensor(np.zeros((1, 48000), dtype=np.float32)), info

    def fake_enhance(_model, _state, audio, *, atten_lim_db: float):
        calls["attenuation"] = atten_lim_db
        return audio

    def fake_resample(_audio, source_rate: int, target_rate: int):
        calls["resample"] = (source_rate, target_rate)
        return FakeTensor(np.zeros((1, 44101), dtype=np.float32))

    model_dir = tmp_path / "DeepFilterNet3"

    def fake_init_df(path: str):
        calls["model_dir"] = path
        return object(), FakeState(), object()

    enhance_module = types.ModuleType("df.enhance")
    enhance_module.enhance = fake_enhance
    enhance_module.init_df = fake_init_df
    enhance_module.load_audio = fake_load
    df_module = types.ModuleType("df")
    df_module.enhance = enhance_module
    torchaudio_module = types.ModuleType("torchaudio")
    torchaudio_module.functional = types.SimpleNamespace(resample=fake_resample)
    monkeypatch.setitem(sys.modules, "df", df_module)
    monkeypatch.setitem(sys.modules, "df.enhance", enhance_module)
    monkeypatch.setitem(sys.modules, "torchaudio", torchaudio_module)
    monkeypatch.setenv("XB_DEEPFILTER_MODEL_DIR", str(model_dir))

    output = tmp_path / "filtered.wav"

    def fake_write(path: Path, audio: np.ndarray, sample_rate: int) -> None:
        calls["write"] = (audio.shape, sample_rate)
        path.write_bytes(b"RIFF-filtered")

    monkeypatch.setattr(vocal_enhancement_worker, "_write_float_wav", fake_write)
    vocal_enhancement_worker._deepfilter(tmp_path / "source.wav", output)

    assert calls == {
        "model_dir": str(model_dir),
        "load_sr": 48000,
        "attenuation": 3.0,
        "resample": (48000, 44100),
        "write": ((1, 44100), 44100),
    }


def test_float_writer_rejects_non_finite_audio(
    tmp_path: Path, monkeypatch
) -> None:
    soundfile_module = types.ModuleType("soundfile")
    soundfile_module.write = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "soundfile", soundfile_module)

    with pytest.raises(RuntimeError, match="非有限"):
        vocal_enhancement_worker._write_float_wav(
            tmp_path / "invalid.wav",
            np.array([0.0, np.nan], dtype=np.float32),
            44100,
        )


def test_clean_model_output_repair_is_sample_identical_and_skips_deepfilter(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "converted_raw.wav"
    output = tmp_path / "converted_repaired.wav"
    source.write_bytes(b"RIFF-clean-model-render")

    def fail_deepfilter(*_args, **_kwargs) -> None:
        raise AssertionError("clean model output must bypass DeepFilter")

    monkeypatch.setattr(vocal_enhancement_worker, "_deepfilter", fail_deepfilter)
    profile = {
        "high_pitch": True,
        "high_frequency": False,
        "high_band_noise": False,
        "high_band_flatness": 0.22,
    }

    returned = vocal_enhancement_worker.run_repair(
        source,
        output,
        stage="output",
        profile=profile,
    )

    assert returned == profile
    assert output.read_bytes() == source.read_bytes()


def test_noise_classified_model_output_still_enters_deepfilter(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "converted_raw.wav"
    output = tmp_path / "converted_repaired.wav"
    source.write_bytes(b"RIFF-noisy-model-render")
    calls: list[float] = []

    monkeypatch.setattr(
        vocal_enhancement_worker,
        "_suppress_short_high_band_spikes",
        lambda _source, target: (target.write_bytes(source.read_bytes()), 0)[1],
    )

    def fake_deepfilter(_source: Path, target: Path, *, atten_lim_db: float) -> None:
        calls.append(atten_lim_db)
        target.write_bytes(b"RIFF-filtered")

    monkeypatch.setattr(vocal_enhancement_worker, "_deepfilter", fake_deepfilter)
    monkeypatch.setattr(
        vocal_enhancement_worker,
        "_suppress_noise_like_high_band",
        lambda source_path, target, **_kwargs: (
            target.write_bytes(source_path.read_bytes()),
            0,
            0.0,
        )[1:],
    )
    monkeypatch.setattr(
        vocal_enhancement_worker,
        "_restore_high_note_body",
        lambda source_path, _guide, target, **_kwargs: (
            target.write_bytes(source_path.read_bytes()),
            0,
            0.0,
        )[1:],
    )
    monkeypatch.setattr(vocal_enhancement_worker, "_quality_gate_file", lambda *_args: True)
    monkeypatch.setattr(
        vocal_enhancement_worker,
        "_analyze_audio",
        lambda _path: {"high_band_ratio": 0.10},
    )

    vocal_enhancement_worker.run_repair(
        source,
        output,
        stage="output",
        profile={
            "high_pitch": False,
            "high_frequency": True,
            "high_band_noise": True,
            "high_band_flatness": 0.20,
            "high_band_ratio": 0.10,
        },
    )

    assert calls == [4.5]
    assert output.read_bytes() == b"RIFF-filtered"


def test_processor_invokes_isolated_worker_and_uses_project_cache(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    output = tmp_path / "enhanced.wav"
    python = tmp_path / "python.exe"
    worker = tmp_path / "worker.py"
    marker = tmp_path / "runtime.ready"
    cache_home = tmp_path / "cache"
    for path in (source, python, worker, marker):
        path.write_bytes(b"ready")

    def fake_run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        output.write_bytes(b"RIFF-enhanced")
        assert cmd[:2] == [str(python), str(worker)]
        assert cmd[cmd.index("--level") + 1] == "advanced"
        assert cmd[cmd.index("--timbre-focus") + 1] == "0.6000"
        assert cmd[cmd.index("--ai-eq") + 1] == "0.5500"
        assert cmd[cmd.index("--ai-compressor") + 1] == "0.4500"
        assert cmd[cmd.index("--ai-exciter") + 1] == "0.2500"
        assert cmd[cmd.index("--stereo-width") + 1] == "0.3000"
        assert cmd[cmd.index("--loudness-envelope") + 1] == "0.5800"
        assert kwargs["env"]["USERPROFILE"] == str(cache_home)
        assert kwargs["env"]["XB_DEEPFILTER_MODEL_DIR"] == str(
            cache_home / "DeepFilterNet3"
        )
        return subprocess.CompletedProcess(cmd, 0, "VOCAL_ENHANCE_OK", "")

    with (
        patch.object(config, "VOCAL_ENHANCEMENT_PYTHON", python),
        patch.object(config, "VOCAL_ENHANCEMENT_WORKER", worker),
        patch.object(config, "VOCAL_ENHANCEMENT_MARKER", marker),
        patch.object(config, "VOCAL_ENHANCEMENT_MODEL_DIR", cache_home),
        patch("infrastructure.vocal_enhancement.subprocess.run", side_effect=fake_run),
    ):
        result = VocalEnhancementProcessor().enhance(
            source,
            output,
            level="advanced",
            device="auto",
        )

    assert result == output
    assert output.read_bytes() == b"RIFF-enhanced"


def test_processor_invokes_dedicated_repair_mode_with_profile(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    output = tmp_path / "repaired.wav"
    python = tmp_path / "python.exe"
    worker = tmp_path / "worker.py"
    marker = tmp_path / "runtime.ready"
    cache_home = tmp_path / "cache"
    for path in (source, python, worker, marker):
        path.write_bytes(b"ready")

    def fake_run(cmd: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        assert cmd[cmd.index("--mode") + 1] == "repair"
        assert cmd[cmd.index("--repair-stage") + 1] == "output"
        assert '"high_pitch":true' in cmd[cmd.index("--analysis-json") + 1]
        output.write_bytes(b"RIFF-repaired")
        return subprocess.CompletedProcess(cmd, 0, "VOCAL_REPAIR_OK", "")

    with (
        patch.object(config, "VOCAL_ENHANCEMENT_PYTHON", python),
        patch.object(config, "VOCAL_ENHANCEMENT_WORKER", worker),
        patch.object(config, "VOCAL_ENHANCEMENT_MARKER", marker),
        patch.object(config, "VOCAL_ENHANCEMENT_MODEL_DIR", cache_home),
        patch("infrastructure.vocal_enhancement.subprocess.run", side_effect=fake_run),
    ):
        result = VocalEnhancementProcessor().repair(
            source,
            output,
            stage="output",
            profile={"high_pitch": True, "recommended_f0_max": 1450.0},
        )

    assert result == output
    assert output.read_bytes() == b"RIFF-repaired"


def test_processor_tunes_before_enhancement_and_passes_strengths(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    reference = tmp_path / "reference.wav"
    output = tmp_path / "enhanced.wav"
    vocal_python = tmp_path / "vocal-python.exe"
    vocal_worker = tmp_path / "vocal-worker.py"
    svc_python = tmp_path / "svc-python.exe"
    tuning_worker = tmp_path / "tuning-worker.py"
    marker = tmp_path / "runtime.ready"
    cache_home = tmp_path / "cache"
    for path in (
        source,
        reference,
        vocal_python,
        vocal_worker,
        svc_python,
        tuning_worker,
        marker,
    ):
        path.write_bytes(b"ready")
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        if cmd[1] == str(tuning_worker):
            assert cmd[cmd.index("--strength") + 1] == "0.3300"
            assert cmd[cmd.index("--alignment-strength") + 1] == "0.5800"
            assert cmd[0] == str(vocal_python)
            Path(cmd[cmd.index("--output") + 1]).write_bytes(b"RIFF-tuned")
            return subprocess.CompletedProcess(cmd, 0, "VOCAL_TUNE_OK", "")
        tuned_input = Path(cmd[cmd.index("--input") + 1])
        assert tuned_input != source
        assert tuned_input.read_bytes() == b"RIFF-tuned"
        assert cmd[cmd.index("--timbre-focus") + 1] == "0.7700"
        assert cmd[cmd.index("--ai-eq") + 1] == "0.6600"
        assert cmd[cmd.index("--ai-compressor") + 1] == "0.4400"
        assert cmd[cmd.index("--ai-exciter") + 1] == "0.2200"
        assert cmd[cmd.index("--stereo-width") + 1] == "0.3300"
        assert cmd[cmd.index("--loudness-envelope") + 1] == "0.6400"
        output.write_bytes(b"RIFF-enhanced")
        return subprocess.CompletedProcess(cmd, 0, "VOCAL_ENHANCE_OK", "")

    with (
        patch.object(config, "VOCAL_ENHANCEMENT_PYTHON", vocal_python),
        patch.object(config, "VOCAL_ENHANCEMENT_WORKER", vocal_worker),
        patch.object(config, "VOCAL_ENHANCEMENT_MARKER", marker),
        patch.object(config, "VOCAL_ENHANCEMENT_MODEL_DIR", cache_home),
        patch.object(config, "SVC_PYTHON", svc_python),
        patch.object(config, "VOCAL_TUNING_WORKER", tuning_worker),
        patch("infrastructure.vocal_enhancement.subprocess.run", side_effect=fake_run),
    ):
        result = VocalEnhancementProcessor().enhance(
            source,
            output,
            reference=reference,
            pitch_correction=0.33,
            timing_alignment=0.58,
            timbre_focus=0.77,
            ai_eq=0.66,
            ai_compressor=0.44,
            ai_exciter=0.22,
            stereo_width=0.33,
            loudness_envelope=0.64,
        )

    assert result == output
    assert len(commands) == 2


def test_processor_continues_when_natural_tuning_fails(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    reference = tmp_path / "reference.wav"
    output = tmp_path / "enhanced.wav"
    vocal_python = tmp_path / "vocal-python.exe"
    vocal_worker = tmp_path / "vocal-worker.py"
    svc_python = tmp_path / "svc-python.exe"
    tuning_worker = tmp_path / "tuning-worker.py"
    marker = tmp_path / "runtime.ready"
    cache_home = tmp_path / "cache"
    for path in (
        source,
        reference,
        vocal_python,
        vocal_worker,
        svc_python,
        tuning_worker,
        marker,
    ):
        path.write_bytes(b"ready")

    def fake_run(cmd: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        if cmd[1] == str(tuning_worker):
            return subprocess.CompletedProcess(cmd, 1, "VOCAL_TUNE_ERR failed", "")
        assert Path(cmd[cmd.index("--input") + 1]) == source
        output.write_bytes(b"RIFF-enhanced")
        return subprocess.CompletedProcess(cmd, 0, "VOCAL_ENHANCE_OK", "")

    with (
        patch.object(config, "VOCAL_ENHANCEMENT_PYTHON", vocal_python),
        patch.object(config, "VOCAL_ENHANCEMENT_WORKER", vocal_worker),
        patch.object(config, "VOCAL_ENHANCEMENT_MARKER", marker),
        patch.object(config, "VOCAL_ENHANCEMENT_MODEL_DIR", cache_home),
        patch.object(config, "SVC_PYTHON", svc_python),
        patch.object(config, "VOCAL_TUNING_WORKER", tuning_worker),
        patch("infrastructure.vocal_enhancement.subprocess.run", side_effect=fake_run),
    ):
        result = VocalEnhancementProcessor().enhance(
            source,
            output,
            reference=reference,
        )

    assert result == output


def test_processor_rejects_unstable_natural_tuning_result(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    reference = tmp_path / "reference.wav"
    output = tmp_path / "enhanced.wav"
    vocal_python = tmp_path / "vocal-python.exe"
    vocal_worker = tmp_path / "vocal-worker.py"
    tuning_worker = tmp_path / "tuning-worker.py"
    marker = tmp_path / "runtime.ready"
    cache_home = tmp_path / "cache"
    for path in (
        source,
        reference,
        vocal_python,
        vocal_worker,
        tuning_worker,
        marker,
    ):
        path.write_bytes(b"ready")

    def fake_run(cmd: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        if cmd[1] == str(tuning_worker):
            Path(cmd[cmd.index("--output") + 1]).write_bytes(b"RIFF-tuned")
            return subprocess.CompletedProcess(
                cmd,
                0,
                "VOCAL_TUNE_OK align_max=86ms psola=91%",
                "",
            )
        assert Path(cmd[cmd.index("--input") + 1]) == source
        output.write_bytes(b"RIFF-enhanced")
        return subprocess.CompletedProcess(cmd, 0, "VOCAL_ENHANCE_OK", "")

    with (
        patch.object(config, "VOCAL_ENHANCEMENT_PYTHON", vocal_python),
        patch.object(config, "VOCAL_ENHANCEMENT_WORKER", vocal_worker),
        patch.object(config, "VOCAL_ENHANCEMENT_MARKER", marker),
        patch.object(config, "VOCAL_ENHANCEMENT_MODEL_DIR", cache_home),
        patch.object(config, "VOCAL_TUNING_WORKER", tuning_worker),
        patch("infrastructure.vocal_enhancement.subprocess.run", side_effect=fake_run),
    ):
        result = VocalEnhancementProcessor().enhance(
            source,
            output,
            reference=reference,
        )

    assert result == output
    assert output.read_bytes() == b"RIFF-enhanced"


def test_processor_rejects_excessive_local_timing_stretch() -> None:
    accepted, reason = VocalEnhancementProcessor._accept_natural_tuning(
        "VOCAL_TUNE_OK align_max=13ms stretch=4.2% psola=5%"
    )

    assert accepted is False
    assert "拉伸" in reason


def test_processor_rejects_broad_psola_resynthesis() -> None:
    accepted, reason = VocalEnhancementProcessor._accept_natural_tuning(
        "VOCAL_TUNE_OK align_max=0ms stretch=0.0% psola=21%"
    )

    assert accepted is False
    assert "PSOLA" in reason
