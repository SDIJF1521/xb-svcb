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


if __name__ == "__main__":
    unittest.main()
