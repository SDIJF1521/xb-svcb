import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from application.model_service import ModelService
from domain import InferenceParams
from infrastructure.ddsp_engine import DdspSvcEngine
from infrastructure.ddsp_worker import (
    _ddsp_output_levels,
    _effective_ddsp_infer_steps,
    _finalize_ddsp_output,
    _patch_ddsp_float_wav,
    _patch_directml_ddsp_rmvpe_cpu,
    _patch_directml_ddsp_sinusoidal_cpu,
    _patch_directml_ddsp_vocoder_cpu,
    _patch_torch_load,
)
from infrastructure.engine import EngineRegistry
from infrastructure.storage import ListRepository, SettingsStore


class _FakeEngine:
    def __init__(self, framework: str) -> None:
        self.framework = framework


class DdspRegistryTests(unittest.TestCase):
    def test_ddsp_framework_routes_to_dedicated_engine(self) -> None:
        sovits = _FakeEngine("so-vits-svc")
        ddsp = _FakeEngine("ddsp-svc")
        registry = EngineRegistry([sovits, ddsp])

        self.assertIs(registry.for_framework("ddsp-svc"), ddsp)


class DdspModelImportTests(unittest.TestCase):
    def test_ddsp_import_renames_config_and_marks_framework_supported(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            source.mkdir()
            checkpoint = source / "model_100000.pt"
            model_config = source / "reflow.yaml"
            checkpoint.write_bytes(b"checkpoint")
            model_config.write_text("data:\n  sampling_rate: 44100\n", encoding="utf-8")

            service = ModelService(
                ListRepository(root / "models.json"),
                SettingsStore(root / "settings.json"),
            )
            with patch.object(config, "MODELS_DIR", root / "models"):
                created = service.import_model(
                    {
                        "framework": "ddsp-svc",
                        "main_model": str(checkpoint),
                        "main_config": str(model_config),
                    }
                )
                overview = service.overview()

            self.assertIsNotNone(created)
            assert created is not None
            self.assertEqual(created["type"], "DDSP-SVC")
            self.assertEqual(created["framework"], "ddsp-svc")
            self.assertEqual(created["main_config"]["name"], "config.yaml")
            self.assertTrue(Path(created["main_config"]["path"]).is_file())
            ddsp_summary = next(
                item for item in overview["frameworks"] if item["id"] == "ddsp-svc"
            )
            self.assertTrue(ddsp_summary["supported"])


class DdspEngineCommandTests(unittest.TestCase):
    def test_default_ddsp_quality_uses_upstream_recommended_steps(self) -> None:
        self.assertEqual(InferenceParams().ddsp_infer_steps, 50)
        self.assertEqual(InferenceParams.from_dict({}).ddsp_infer_steps, 50)

    def test_worker_never_runs_below_model_recommended_steps(self) -> None:
        self.assertEqual(
            _effective_ddsp_infer_steps({"infer": {"infer_step": 50}}, 22),
            (50, 50),
        )
        self.assertEqual(
            _effective_ddsp_infer_steps({"infer": {"infer_step": 50}}, 80),
            (80, 50),
        )
        self.assertEqual(_effective_ddsp_infer_steps({}, 22), (50, 50))

    def test_inference_params_accept_and_clamp_formant_shift(self) -> None:
        self.assertEqual(
            InferenceParams.from_dict({"ddsp_formant_shift": 0.65}).ddsp_formant_shift,
            0.65,
        )
        self.assertEqual(
            InferenceParams.from_dict({"formant_shift_key": 8}).ddsp_formant_shift,
            2.0,
        )

    def test_worker_command_contains_ddsp_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            python = root / "python.exe"
            worker = root / "ddsp_worker.py"
            model = root / "model.pt"
            model_config = root / "config.yaml"
            vocals = root / "vocals.wav"
            output = root / "output.wav"
            for path in (python, worker, model, model_config, vocals, output):
                path.write_bytes(b"x")
            params = InferenceParams(
                pitch=5,
                f0_method="pm",
                device="cpu",
                speaker="2",
                ddsp_infer_steps=42,
                ddsp_formant_shift=0.65,
            )

            with (
                patch.object(config, "DDSP_PYTHON", python),
                patch.object(config, "DDSP_WORKER", worker),
                patch.object(config, "DDSP_REPO", repo),
                patch("infrastructure.ddsp_engine.subprocess.run") as run,
            ):
                run.return_value = SimpleNamespace(returncode=0, stdout="DDSP_OK", stderr="")
                DdspSvcEngine()._run_worker(
                    str(model),
                    str(model_config),
                    vocals,
                    output,
                    params,
                    None,
                )

            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--pitch") + 1], "5")
            self.assertEqual(command[command.index("--f0") + 1], "parselmouth")
            self.assertEqual(command[command.index("--infer-steps") + 1], "42")
            self.assertEqual(command[command.index("--formant-shift") + 1], "0.65")
            self.assertEqual(command[command.index("--speaker") + 1], "2")


class DdspDirectMlCheckpointTests(unittest.TestCase):
    def test_directml_loads_unmapped_cuda_checkpoint_on_cpu(self) -> None:
        calls: list[tuple[tuple, dict]] = []

        def load(*args, **kwargs):
            calls.append((args, kwargs))
            return "checkpoint"

        torch = SimpleNamespace(load=load)
        _patch_torch_load(True, torch)

        self.assertEqual(torch.load("rmvpe.pt"), "checkpoint")
        self.assertEqual(calls[-1][1]["map_location"], "cpu")
        self.assertFalse(calls[-1][1]["weights_only"] or False)

    def test_directml_overrides_keyword_and_positional_map_location(self) -> None:
        calls: list[tuple[tuple, dict]] = []

        def load(*args, **kwargs):
            calls.append((args, kwargs))
            return "checkpoint"

        torch = SimpleNamespace(load=load)
        _patch_torch_load(True, torch)

        torch.load("model.pt", map_location="privateuseone:0")
        self.assertEqual(calls[-1][1]["map_location"], "cpu")

        torch.load("model.pt", "cuda:0")
        self.assertEqual(calls[-1][0][1], "cpu")
        self.assertNotIn("map_location", calls[-1][1])

    def test_non_directml_keeps_checkpoint_location_unchanged(self) -> None:
        calls: list[tuple[tuple, dict]] = []

        def load(*args, **kwargs):
            calls.append((args, kwargs))
            return "checkpoint"

        torch = SimpleNamespace(load=load)
        _patch_torch_load(False, torch)
        torch.load("model.pt", map_location="cuda:0")

        self.assertEqual(calls[-1][1]["map_location"], "cuda:0")


class DdspDirectMlRmvpeTests(unittest.TestCase):
    def test_directml_rmvpe_runs_on_cpu_while_ddsp_device_is_unchanged(self) -> None:
        calls: list[tuple[tuple, dict]] = []

        class FakeRmvpe:
            def infer_from_audio(self, *args, **kwargs):
                calls.append((args, kwargs))
                return "f0"

        _patch_directml_ddsp_rmvpe_cpu(FakeRmvpe)
        model = FakeRmvpe()

        self.assertEqual(
            model.infer_from_audio(
                "audio",
                44100,
                device="privateuseone:0",
                thred=0.05,
            ),
            "f0",
        )
        self.assertEqual(calls[-1][0][:3], ("audio", 44100, "cpu"))
        self.assertEqual(calls[-1][1]["thred"], 0.05)

    def test_directml_rmvpe_patch_is_idempotent(self) -> None:
        class FakeRmvpe:
            def infer_from_audio(self, *args, **kwargs):
                return args, kwargs

        _patch_directml_ddsp_rmvpe_cpu(FakeRmvpe)
        patched = FakeRmvpe.infer_from_audio
        _patch_directml_ddsp_rmvpe_cpu(FakeRmvpe)

        self.assertIs(FakeRmvpe.infer_from_audio, patched)


class DdspDirectMlSinusoidalTests(unittest.TestCase):
    def test_directml_timestep_embedding_runs_on_cpu_then_returns_to_gpu(self) -> None:
        calls: list[tuple] = []

        class FakeResult:
            def to(self, device):
                calls.append(("to", device))
                return "directml-embedding"

        class FakeTensor:
            def __init__(self, device):
                self.device = device

            def float(self):
                calls.append(("float", self.device))
                return self

            def cpu(self):
                calls.append(("cpu", self.device))
                return FakeTensor("cpu")

        class FakeEmbedding:
            def forward(self, x):
                calls.append(("forward", x.device))
                return FakeResult()

        _patch_directml_ddsp_sinusoidal_cpu(FakeEmbedding)

        result = FakeEmbedding().forward(FakeTensor("privateuseone:0"))

        self.assertEqual(result, "directml-embedding")
        self.assertEqual(
            calls,
            [
                ("float", "privateuseone:0"),
                ("cpu", "privateuseone:0"),
                ("forward", "cpu"),
                ("to", "privateuseone:0"),
            ],
        )

    def test_non_directml_timestep_embedding_stays_on_original_device(self) -> None:
        calls: list[str] = []

        class FakeEmbedding:
            def forward(self, x):
                calls.append(x.device)
                return "original"

        _patch_directml_ddsp_sinusoidal_cpu(FakeEmbedding)
        result = FakeEmbedding().forward(SimpleNamespace(device="cuda:0"))

        self.assertEqual(result, "original")
        self.assertEqual(calls, ["cuda:0"])


class DdspDirectMlVocoderTests(unittest.TestCase):
    def test_directml_final_vocoder_decodes_on_cpu_and_returns_to_gpu(self) -> None:
        calls: list[tuple] = []

        class FakeTensor:
            def __init__(self, device):
                self.device = device

            def float(self):
                calls.append(("float", self.device))
                return self

            def cpu(self):
                calls.append(("cpu", self.device))
                return FakeTensor("cpu")

            def to(self, device):
                calls.append(("to", self.device, device))
                return "directml-audio"

        class FakeVocoder:
            def __init__(self):
                self.vocoder = SimpleNamespace(device="privateuseone:0", model=None)

            def infer(self, mel, f0):
                calls.append(("infer", mel.device, f0.device, self.vocoder.device))
                return FakeTensor("cpu")

        _patch_directml_ddsp_vocoder_cpu(FakeVocoder)
        result = FakeVocoder().infer(
            FakeTensor("privateuseone:0"),
            FakeTensor("privateuseone:0"),
        )

        self.assertEqual(result, "directml-audio")
        self.assertIn(("infer", "cpu", "cpu", "cpu"), calls)
        self.assertIn(("to", "cpu", "privateuseone:0"), calls)


class DdspOutputValidationTests(unittest.TestCase):
    def test_wav_writer_preserves_float_samples_by_default(self) -> None:
        calls: list[tuple[tuple, dict]] = []

        def write(*args, **kwargs):
            calls.append((args, kwargs))

        soundfile = SimpleNamespace(write=write)
        _patch_ddsp_float_wav(soundfile)
        soundfile.write("converted.wav", [0.00001], 44100)

        self.assertEqual(calls[-1][1]["subtype"], "FLOAT")

    def test_low_output_is_safely_gain_matched_to_input(self) -> None:
        import numpy as np

        phase = np.linspace(0, 20 * np.pi, 44100, dtype=np.float32)
        rendered, stats = _ddsp_output_levels(
            0.025 * np.sin(phase),
            0.2 * np.sin(phase),
        )

        self.assertGreater(stats["gain"], 1.0)
        self.assertGreater(stats["rms"], 0.1)
        self.assertLessEqual(stats["peak"], 0.98)
        self.assertTrue(np.isfinite(rendered).all())

    def test_near_silent_output_is_rejected(self) -> None:
        import numpy as np

        with self.assertRaisesRegex(RuntimeError, "近似静音"):
            _ddsp_output_levels(
                np.zeros(4410, dtype=np.float32),
                np.ones(4410, dtype=np.float32) * 0.1,
            )


if __name__ == "__main__":
    unittest.main()
