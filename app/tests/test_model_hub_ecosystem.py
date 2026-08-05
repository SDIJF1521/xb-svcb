import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from application.model_hub_service import (
    MODELHUB_PREVIEW_AUDIO_MAX_BYTES,
    ModelHubService,
    _ensure_preview_audio_file,
    _is_remote_newer,
)
from infrastructure.storage import SettingsStore


class DummyModels:
    def __init__(self, items=None) -> None:
        self._items = items or []

    def list(self):
        return list(self._items)

    def get(self, model_id):
        return next((item for item in self._items if item.get("id") == model_id), None)


class ModelHubEcosystemTests(unittest.TestCase):
    def make_service(self, root: Path, models=None) -> ModelHubService:
        service = object.__new__(ModelHubService)
        service._settings = SettingsStore(root / "settings.json")
        service._models = DummyModels(models)
        return service

    def test_model_detail_combines_manifest_assets_and_update_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo_id = "owner/xb-svcb-demo"
            service = self.make_service(
                Path(td),
                [
                    {
                        "id": "mdl_old",
                        "name": "Demo local",
                        "imported_at": "2026-07-01",
                        "metadata": {
                            "source_repo_id": repo_id,
                            "source_version": "1.0.0",
                            "source_uploaded_at": "2026-07-01T00:00:00",
                        },
                    }
                ],
            )
            manifest = {
                "magic": config.MODELHUB_MAGIC,
                "name": "Demo voice",
                "framework": "rvc",
                "sample_rate": "48kHz",
                "files": {"main_model": "voice.pth", "index_file": "voice.index"},
                "version": "1.2.0",
                "uploaded_at": "2026-07-20T00:00:00",
                "tags": ["RVC", "女声"],
                "assets": {
                    "preview_audio": "preview.wav",
                    "screenshots": ["shot.png"],
                },
            }
            with (
                patch("application.model_hub_service.shutil.which", return_value="ffmpeg"),
                patch("application.model_hub_service.config.uvr_ready", return_value=True),
                patch("application.model_hub_service.config.rvc_engine_ready", return_value=True),
            ):
                item = service._build_item(
                    repo_id,
                    manifest,
                    detail=True,
            )

            self.assertEqual(item["version"], "1.2.0")
            self.assertEqual(item["download_count"], 0)
            self.assertTrue(item["dependency_ok"])
            self.assertTrue(item["update"]["available"])
            self.assertEqual(item["preview_audio"]["path"], "preview.wav")
            self.assertTrue(service._asset_allowed(manifest, "shot.png"))
            self.assertFalse(service._asset_allowed(manifest, "voice.pth"))

    def test_preview_audio_validation_rejects_non_audio_and_files_over_1gb(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            valid = root / "preview.mp3"
            invalid = root / "fake.mp3"
            valid.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00")
            invalid.write_bytes(b"not an audio file")

            with patch("application.model_hub_service.shutil.which", return_value=None):
                _ensure_preview_audio_file(valid)
                with self.assertRaises(OSError):
                    _ensure_preview_audio_file(invalid)
                with patch(
                    "application.model_hub_service._file_size",
                    return_value=MODELHUB_PREVIEW_AUDIO_MAX_BYTES + 1,
                ):
                    with self.assertRaises(OSError):
                        _ensure_preview_audio_file(valid)

    def test_audio_asset_data_returns_stream_url_without_inlining(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            service = self.make_service(Path(td))
            repo_id = "owner/xb-svcb-demo"
            manifest = {
                "magic": config.MODELHUB_MAGIC,
                "framework": "rvc",
                "files": {"main_model": "voice.pth"},
                "assets": {"preview_audio": "assets/preview.mp3"},
            }

            async def fake_fetch_manifest(_repo_id):
                return manifest

            async def fail_get_raw(_repo_id, _file_path):
                raise AssertionError("audio preview should not be downloaded inline")

            service._fetch_manifest = fake_fetch_manifest
            service._get_raw = fail_get_raw

            res = asyncio.run(service._asset_data(repo_id, "assets/preview.mp3"))

            self.assertTrue(res["ok"])
            self.assertEqual(res["mime"], "audio/mpeg")
            self.assertIn("url", res)
            self.assertNotIn("data", res)
            self.assertIn("FilePath=assets%2Fpreview.mp3", res["url"])

    def test_remote_version_comparison_uses_semver_then_timestamp(self) -> None:
        self.assertTrue(_is_remote_newer("1.2.0", "1.1.9"))
        self.assertFalse(_is_remote_newer("1.0.0", "1.0.1"))
        self.assertTrue(
            _is_remote_newer(
                "1.0.0",
                "1.0.0",
                "2026-07-02T00:00:00",
                "2026-07-01T00:00:00",
            )
        )


if __name__ == "__main__":
    unittest.main()
