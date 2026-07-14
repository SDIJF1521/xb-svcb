import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from application.model_service import ModelService
from infrastructure.storage import ListRepository, SettingsStore


class ModelServiceDownloadedModelTests(unittest.TestCase):
    def test_downloaded_model_is_immediately_listed_with_source_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            source.mkdir()
            model_file = source / "voice.pth"
            index_file = source / "voice.index"
            model_file.write_bytes(b"model")
            index_file.write_bytes(b"index")

            repo = ListRepository(root / "models.json")
            settings = SettingsStore(root / "settings.json")
            service = ModelService(repo, settings)
            with patch.object(config, "MODELS_DIR", root / "models"):
                created = service.import_model(
                    {
                        "name": "Downloaded voice",
                        "framework": "rvc",
                        "main_model": str(model_file),
                        "index_file": str(index_file),
                        "source_repo_id": "owner/xb-svcb-downloaded",
                    }
                )
                listed = service.list()

            self.assertIsNotNone(created)
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["id"], created["id"])
            self.assertEqual(listed[0]["framework"], "rvc")
            self.assertEqual(
                listed[0]["metadata"]["source_repo_id"],
                "owner/xb-svcb-downloaded",
            )
            self.assertTrue(Path(listed[0]["main_model"]["path"]).is_file())


if __name__ == "__main__":
    unittest.main()
