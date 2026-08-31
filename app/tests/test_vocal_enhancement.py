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
    params = InferenceParams(f0_method="harvest", protect=0.33, filter_radius=5)
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
    assert float(profile["recommended_f0_max"]) > 1100.0


def test_formant_guard_ignores_isolated_pitch_tracker_spikes() -> None:
    assert formant_pitch_worker._high_intervals(
        [(0.50, 920.0)], 800.0, 0.0, 1.0
    ) == []
    intervals = formant_pitch_worker._high_intervals(
        [(0.50, 920.0), (0.54, 940.0)], 800.0, 0.0, 1.0
    )
    assert intervals
    assert intervals[0][0] < 0.50 < intervals[0][1]


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

    def fake_match(_source: Path, _ref: Path, output: Path) -> None:
        calls.append("match")
        output.write_bytes(b"RIFF-matched")

    def fake_deepfilter(_source: Path, output: Path) -> None:
        calls.append("deepfilter")
        output.write_bytes(b"RIFF-filtered")

    def fake_restore(_source: Path, _ref: Path, output: Path) -> None:
        calls.append("detail")
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
            "match",
            "deepfilter",
            "detail",
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


def test_stereo_image_preserves_mono_sum_and_adds_width() -> None:
    sample_rate = 48000
    time = np.arange(sample_rate, dtype=np.float64) / sample_rate
    mono = 0.18 * np.sin(2.0 * np.pi * 220.0 * time)
    mono += 0.05 * np.sin(2.0 * np.pi * 4200.0 * time)

    stereo = vocal_enhancement_worker._stereo_image_array(
        mono[:, np.newaxis], sample_rate, 0.65
    )

    assert stereo.shape == (sample_rate, 2)
    assert np.allclose(stereo.mean(axis=1), mono, atol=1e-7)
    assert float(np.sqrt(np.mean((stereo[:, 0] - stereo[:, 1]) ** 2))) > 0.005


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


def test_psola_region_curve_preserves_long_silence_and_bridges_short_gap() -> None:
    sample_rate = 2000
    original = np.zeros(sample_rate * 4, dtype=np.float64)
    time = np.arange(len(original), dtype=np.float64) / sample_rate
    first_phrase = (time >= 0.80) & (time < 1.30)
    second_phrase = (time >= 1.60) & (time < 2.10)
    original[first_phrase | second_phrase] = 0.20 * np.sin(
        2.0 * np.pi * 180.0 * time[first_phrase | second_phrase]
    )

    curve = vocal_tuning_worker._resynthesis_region_curve(
        original[np.newaxis, :],
        sample_rate,
    )

    assert float(np.max(curve[: int(0.30 * sample_rate)])) == 0.0
    assert float(np.median(curve[int(0.90 * sample_rate) : int(2.00 * sample_rate)])) > 0.98
    assert float(np.max(curve[int(3.20 * sample_rate) :])) == 0.0
    artifact = original + 10.0 ** (-60.0 / 20.0)
    blended = original + (artifact - original) * curve
    assert np.array_equal(blended[: int(0.30 * sample_rate)], original[: int(0.30 * sample_rate)])


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
    assert float(np.max(np.abs(factors - 1.0))) <= 0.061


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
