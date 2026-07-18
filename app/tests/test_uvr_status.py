import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from infrastructure.uvr_tool import UvrTool


class UvrStatusTests(unittest.TestCase):
    def test_stale_env_override_falls_back_to_installed_uvr_python(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fallback_py = root / ".venv-uvr" / "Scripts" / "python.exe"
            fallback_py.parent.mkdir(parents=True, exist_ok=True)
            fallback_py.write_text("placeholder", encoding="utf-8")

            with patch.dict(
                "os.environ",
                {"XB_UVR_PYTHON": str(root / "old-missing" / "python.exe")},
            ), patch.object(config, "UVR_VENV_DIR", root / ".venv-uvr"):
                self.assertEqual(config._detect_uvr_python(), fallback_py)

    def test_stale_model_dir_override_falls_back_to_installed_model_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            model_dir = root / "models" / "uvr"
            model_dir.mkdir(parents=True, exist_ok=True)
            (model_dir / "5_HP-Karaoke-UVR.pth").write_bytes(b"placeholder")

            with patch.dict(
                "os.environ",
                {"XB_UVR_MODEL_DIR": str(root / "old-missing" / "uvr")},
            ), patch.object(config, "UVR_MODEL_DIR_DEFAULT", model_dir):
                self.assertEqual(config._detect_uvr_model_dir(), model_dir)

    def test_existing_env_model_dir_without_model_falls_back_to_installed_model_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old_dir = root / "old-uvr"
            old_dir.mkdir(parents=True, exist_ok=True)
            model_dir = root / "models" / "uvr"
            model_dir.mkdir(parents=True, exist_ok=True)
            (model_dir / "5_HP-Karaoke-UVR.pth").write_bytes(b"placeholder")

            with patch.dict(
                "os.environ",
                {"XB_UVR_MODEL_DIR": str(old_dir)},
            ), patch.object(config, "UVR_MODEL_DIR_DEFAULT", model_dir):
                self.assertEqual(config._detect_uvr_model_dir(), model_dir)

    def test_environment_ready_without_model_is_not_full_ready(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            venv_dir = root / ".venv-uvr"
            py = venv_dir / "Scripts" / "python.exe"
            py.parent.mkdir(parents=True, exist_ok=True)
            py.write_text("placeholder", encoding="utf-8")

            worker = root / "infrastructure" / "uvr_worker.py"
            worker.parent.mkdir(parents=True, exist_ok=True)
            worker.write_text("print('worker')", encoding="utf-8")

            model_dir = root / "models" / "uvr"
            model_dir.mkdir(parents=True, exist_ok=True)

            with patch.object(config, "UVR_PYTHON", py), patch.object(
                config, "UVR_WORKER", worker
            ), patch.object(config, "UVR_MODEL_DIR", model_dir), patch.object(
                config, "UVR_SEP_MODEL", "5_HP-Karaoke-UVR.pth"
            ):
                self.assertTrue(config.uvr_environment_ready())
                self.assertFalse(config.uvr_model_ready())
                self.assertFalse(config.uvr_ready())
                self.assertEqual(config.uvr_status(), "模型未就绪")

    def test_cuda_selection_is_forwarded_and_actual_device_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "input.wav"
            vocals = root / "vocals.wav"
            instrumental = root / "instrumental.wav"
            model_dir = root / "models"
            src.write_bytes(b"input")
            vocals.write_bytes(b"vocals")
            instrumental.write_bytes(b"instrumental")
            model_dir.mkdir()
            (model_dir / "model.pth").write_bytes(b"model")
            stdout = f"UVR_DEVICE cuda\nUVR_OK\t{vocals}\t{instrumental}\n"

            with (
                patch.object(config, "uvr_ready", return_value=True),
                patch.object(config, "UVR_MODEL_DIR", model_dir),
                patch.object(config, "UVR_MODEL", "model.pth"),
                patch.object(config, "UVR_PYTHON", root / "python.exe"),
                patch.object(config, "UVR_WORKER", root / "uvr_worker.py"),
                patch("infrastructure.uvr_tool.subprocess.run") as run,
            ):
                run.return_value = SimpleNamespace(returncode=0, stdout=stdout, stderr="")
                result = UvrTool().separate(src, root / "out", "model.pth", "cuda")

            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--device") + 1], "cuda")
            self.assertEqual(result.device, "cuda")
            self.assertFalse(result.simulated)

    def test_explicit_cuda_failure_does_not_silently_fall_back_to_cpu(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "input.wav"
            model_dir = root / "models"
            src.write_bytes(b"input")
            model_dir.mkdir()
            (model_dir / "model.pth").write_bytes(b"model")

            with (
                patch.object(config, "uvr_ready", return_value=True),
                patch.object(config, "UVR_MODEL_DIR", model_dir),
                patch.object(config, "UVR_MODEL", "model.pth"),
                patch.object(config, "UVR_PYTHON", root / "python.exe"),
                patch.object(config, "UVR_WORKER", root / "uvr_worker.py"),
                patch("infrastructure.uvr_tool.subprocess.run") as run,
            ):
                run.return_value = SimpleNamespace(
                    returncode=6,
                    stdout="UVR_ERR 已选择 CUDA，但 UVR 环境没有可用的 CUDA Torch\n",
                    stderr="",
                )
                with self.assertRaisesRegex(RuntimeError, "没有可用的 CUDA Torch"):
                    UvrTool().separate(src, root / "out", "model.pth", "cuda")

    def test_directml_selection_is_forwarded_and_actual_device_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "input.wav"
            vocals = root / "vocals.wav"
            model_dir = root / "models"
            src.write_bytes(b"input")
            vocals.write_bytes(b"vocals")
            model_dir.mkdir()
            (model_dir / "model.pth").write_bytes(b"model")

            with (
                patch.object(config, "uvr_ready", return_value=True),
                patch.object(config, "UVR_MODEL_DIR", model_dir),
                patch.object(config, "UVR_MODEL", "model.pth"),
                patch.object(config, "UVR_PYTHON", root / "python.exe"),
                patch.object(config, "UVR_WORKER", root / "uvr_worker.py"),
                patch("infrastructure.uvr_tool.subprocess.run") as run,
            ):
                run.return_value = SimpleNamespace(
                    returncode=0,
                    stdout=f"UVR_DEVICE directml\nUVR_OK\t{vocals}\t\n",
                    stderr="",
                )
                result = UvrTool().separate(src, root / "out", "model.pth", "directml")

            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--device") + 1], "directml")
            self.assertEqual(result.device, "directml")

    def test_explicit_directml_failure_does_not_silently_fall_back_to_cpu(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "input.wav"
            model_dir = root / "models"
            src.write_bytes(b"input")
            model_dir.mkdir()
            (model_dir / "model.pth").write_bytes(b"model")

            with (
                patch.object(config, "uvr_ready", return_value=True),
                patch.object(config, "UVR_MODEL_DIR", model_dir),
                patch.object(config, "UVR_MODEL", "model.pth"),
                patch.object(config, "UVR_PYTHON", root / "python.exe"),
                patch.object(config, "UVR_WORKER", root / "uvr_worker.py"),
                patch("infrastructure.uvr_tool.subprocess.run") as run,
            ):
                run.return_value = SimpleNamespace(
                    returncode=6,
                    stdout="UVR_ERR 已选择 DirectML，但 UVR 环境不可用\n",
                    stderr="",
                )
                with self.assertRaisesRegex(RuntimeError, "DirectML.*不可用"):
                    UvrTool().separate(src, root / "out", "model.pth", "directml")


if __name__ == "__main__":
    unittest.main()
