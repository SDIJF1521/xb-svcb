import json
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
                        "source_version": "1.2.0",
                        "source_uploaded_at": "2026-07-20T12:00:00",
                        "source_tags": ["RVC", "女声"],
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
            self.assertEqual(listed[0]["metadata"]["source_version"], "1.2.0")
            self.assertEqual(listed[0]["metadata"]["source_tags"], ["RVC", "女声"])
            self.assertTrue(Path(listed[0]["main_model"]["path"]).is_file())


class ModelSpeakerOptionsTests(unittest.TestCase):
    def test_model_list_reads_speakers_from_each_model_config(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sovits_config = root / "sovits.json"
            sovits_config.write_text(json.dumps({"spk": {"Alice": 0, "Bob": 1}}), encoding="utf-8")
            ddsp_config = root / "ddsp.yaml"
            ddsp_config.write_text("model:\n  n_spk: 3\n", encoding="utf-8")
            oversized_config = root / "oversized.yaml"
            oversized_config.write_text("model:\n  n_spk: 1000000000\n", encoding="utf-8")
            repo = ListRepository(root / "models.json")
            for model_id, framework, path in (
                ("sovits", "so-vits-svc", sovits_config),
                ("ddsp", "ddsp-svc", ddsp_config),
                ("oversized", "ddsp-svc", oversized_config),
                ("broken", "so-vits-svc", root / "missing.json"),
            ):
                repo.add({
                    "id": model_id,
                    "framework": framework,
                    "main_config": {"name": path.name, "path": str(path)},
                })

            service = ModelService(repo, SettingsStore(root / "settings.json"))
            speakers = {item["id"]: item["speakers"] for item in service.list()}

            self.assertEqual(speakers["sovits"], ["Alice", "Bob"])
            self.assertEqual(speakers["ddsp"], ["1", "2", "3"])
            self.assertEqual(speakers["oversized"], [])
            self.assertEqual(speakers["broken"], [])


if __name__ == "__main__":
    unittest.main()
