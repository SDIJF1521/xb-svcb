import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config


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


if __name__ == "__main__":
    unittest.main()
