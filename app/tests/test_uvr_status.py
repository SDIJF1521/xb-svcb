import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from infrastructure.uvr_tool import UvrTool
from infrastructure.pymss_tool import PymssTool


class UvrStatusTests(unittest.TestCase):
    def test_pymss_catalog_is_limited_to_two_processing_purposes(self) -> None:
        self.assertEqual(
            PymssTool._purpose_for_categories("vocal", "vocal_extraction"),
            config.PYMSS_PURPOSE_VOCAL,
        )
        self.assertEqual(
            PymssTool._purpose_for_categories("legacy_vr", "vr_backing_vocal"),
            config.PYMSS_PURPOSE_HARMONY,
        )
        self.assertEqual(PymssTool._purpose_for_categories("karaoke", ""), "")

    def test_pymss_fallback_catalog_exposes_only_allowed_purposes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            model_dir = Path(td) / "models"
            model_dir.mkdir()
            with patch.object(config, "PYMSS_MODEL_DIR", model_dir), patch.object(
                config, "pymss_environment_ready", return_value=False
            ):
                models = PymssTool().list_models()
            self.assertEqual(
                {item["purpose"] for item in models},
                {config.PYMSS_PURPOSE_VOCAL, config.PYMSS_PURPOSE_HARMONY},
            )
            self.assertFalse(any("karaoke" in item["name"].lower() for item in models))

    def test_pymss_download_rejects_models_outside_allowed_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            python = root / "python.exe"
            worker = root / "pymss_worker.py"
            python.write_text("placeholder", encoding="utf-8")
            worker.write_text("placeholder", encoding="utf-8")
            tool = PymssTool()
            with patch.object(config, "PYMSS_PYTHON", python), patch.object(
                config, "PYMSS_WORKER", worker
            ), patch.object(tool, "list_models", return_value=tool._FALLBACK_CATALOG):
                result = tool.download_model("arbitrary_karaoke_model.pth")
        self.assertFalse(result["ok"])
        self.assertIn("受支持", result["error"])

    def test_pymss_download_runs_in_background_and_keeps_job_state(self) -> None:
        tool = PymssTool()
        with patch.object(type(tool), "available", new=property(lambda self: True)), patch.object(
            tool, "download_model", return_value={"ok": True, "model": "demo.ckpt"}
        ):
            started = tool.start_download_model("demo.ckpt")
            self.assertTrue(started["ok"])
            self.assertTrue(started.get("key"))
            deadline = time.monotonic() + 2
            job = tool.download_progress(started["key"])
            while job.get("status") == "running" and time.monotonic() < deadline:
                time.sleep(0.01)
                job = tool.download_progress(started["key"])
            self.assertEqual(job["status"], "done")
            self.assertEqual(tool.download_jobs()[0]["model"], "demo.ckpt")

    def test_pymss_download_accepts_unique_dereverb_prefix(self) -> None:
        tool = PymssTool()
        full_name = "dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt"
        with patch.object(type(tool), "available", new=property(lambda self: True)), patch.object(
            tool, "list_models", return_value=[{"name": full_name}]
        ), patch("infrastructure.pymss_tool.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")):
            result = tool.download_model("dereverb_mel_band_roformer_anvuew")
        self.assertTrue(result["ok"])
        self.assertEqual(result["model"], full_name)

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

    def test_stale_svc_env_override_falls_back_to_installed_python(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fallback_py = root / ".venv-svc" / "Scripts" / "python.exe"
            fallback_py.parent.mkdir(parents=True, exist_ok=True)
            fallback_py.write_text("placeholder", encoding="utf-8")

            with patch.dict(
                "os.environ",
                {"XB_SVC_PYTHON": str(root / "old-missing" / "python.exe")},
            ), patch.object(config, "RUNTIME_ROOTS", [root]):
                self.assertEqual(config._detect_svc_python(), fallback_py)

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

    def test_pymss_status_without_selected_model_accepts_any_downloaded_model(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pymss_python = root / ".venv-pymss" / "Scripts" / "python.exe"
            pymss_python.parent.mkdir(parents=True, exist_ok=True)
            pymss_python.write_text("placeholder", encoding="utf-8")
            worker = root / "infrastructure" / "pymss_worker.py"
            worker.parent.mkdir(parents=True, exist_ok=True)
            worker.write_text("print('worker')", encoding="utf-8")
            model_dir = root / "models" / "pymss"
            marker_dir = model_dir / ".xb-downloaded"
            marker_dir.mkdir(parents=True, exist_ok=True)
            (marker_dir / "other-model.json").write_text("{}", encoding="utf-8")
            (model_dir / "other-model.ckpt").write_bytes(b"weights")

            with patch.object(config, "PYMSS_PYTHON", pymss_python), patch.object(
                config, "PYMSS_WORKER", worker
            ), patch.object(config, "PYMSS_MODEL_DIR", model_dir):
                self.assertTrue(config.pymss_any_model_ready())
                self.assertEqual(config.pymss_status(), "已就绪")
                self.assertEqual(
                    config.pymss_status("bs_roformer_voc_hyperacev2"), "模型未下载"
                )

    def test_pymss_model_ready_ignores_matching_config_without_weights(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            model_dir = Path(td) / "models" / "pymss"
            model_dir.mkdir(parents=True, exist_ok=True)
            (model_dir / "bs_roformer_voc_hyperacev2.yaml").write_text(
                "config", encoding="utf-8"
            )
            with patch.object(config, "PYMSS_MODEL_DIR", model_dir):
                self.assertFalse(config.pymss_model_ready("bs_roformer_voc_hyperacev2"))

    def test_pymss_model_ready_ignores_auxiliary_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            model_dir = Path(td) / "models" / "pymss"
            model_dir.mkdir(parents=True, exist_ok=True)
            (model_dir / "bs_roformer_voc_hyperacev2.pymss_state_dict.pt").write_bytes(
                b"state"
            )
            with patch.object(config, "PYMSS_MODEL_DIR", model_dir):
                self.assertFalse(config.pymss_model_ready("bs_roformer_voc_hyperacev2"))

    def test_pymss_delete_model_removes_downloaded_files_and_marker(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            model_dir = Path(td) / "models" / "pymss"
            marker_dir = model_dir / ".xb-downloaded"
            nested_dir = model_dir / "nested"
            model_dir.mkdir(parents=True, exist_ok=True)
            marker_dir.mkdir(parents=True, exist_ok=True)
            nested_dir.mkdir(parents=True, exist_ok=True)
            target = model_dir / "bs_roformer_voc_hyperacev2.ckpt"
            nested = nested_dir / "bs_roformer_voc_hyperacev2.yaml"
            other = model_dir / "other-model.ckpt"
            target.write_bytes(b"weights")
            nested.write_text("config", encoding="utf-8")
            other.write_bytes(b"keep")
            (marker_dir / "bs_roformer_voc_hyperacev2.json").write_text(
                json.dumps(
                    {
                        "model": "bs_roformer_voc_hyperacev2.ckpt",
                        "source": "modelscope",
                        "files": [
                            "bs_roformer_voc_hyperacev2.ckpt",
                            "nested/bs_roformer_voc_hyperacev2.yaml",
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(config, "PYMSS_MODEL_DIR", model_dir):
                self.assertTrue(PymssTool().delete_model("bs_roformer_voc_hyperacev2.ckpt"))

            self.assertFalse(target.exists())
            self.assertFalse(nested.exists())
            self.assertTrue(other.exists())
            self.assertFalse((marker_dir / "bs_roformer_voc_hyperacev2.json").exists())

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
