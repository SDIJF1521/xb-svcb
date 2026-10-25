import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from application.model_service import ModelService
from infrastructure.rvc_worker import _rvc_checkpoint_version
from infrastructure.storage import ListRepository, SettingsStore


def test_rvc_checkpoint_prefers_declared_version() -> None:
    version, source = _rvc_checkpoint_version(
        {
            "version": "v1",
            "weight": {
                "enc_p.emb_phone.weight": SimpleNamespace(shape=(192, 768)),
            },
        }
    )

    assert version == "v1"
    assert source == "checkpoint.version"


def test_rvc_checkpoint_detects_phone_encoder_width() -> None:
    v1, source_v1 = _rvc_checkpoint_version(
        {"weight": {"enc_p.emb_phone.weight": SimpleNamespace(shape=(192, 256))}}
    )
    v2, source_v2 = _rvc_checkpoint_version(
        {"weight": {"module.enc_p.emb_phone.weight": SimpleNamespace(shape=(192, 768))}}
    )

    assert (v1, source_v1) == ("v1", "weight.enc_p.emb_phone.weight[256]")
    assert (v2, source_v2) == ("v2", "weight.module.enc_p.emb_phone.weight[768]")


def test_imported_rvc_persists_detected_version() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        source = root / "voice.pth"
        source.write_bytes(b"checkpoint")
        service = ModelService(
            ListRepository(root / "models.json"),
            SettingsStore(root / "settings.json"),
        )

        with (
            patch.object(config, "MODELS_DIR", root / "models"),
            patch.object(
                service,
                "_inspect_rvc_checkpoint",
                return_value={
                    "rvc_version": "v1",
                    "rvc_version_detection": "detected",
                    "rvc_version_source": "checkpoint.version",
                },
            ),
        ):
            created = service.import_model(
                {"framework": "rvc", "main_model": str(source)}
            )

        assert created is not None
        assert created["metadata"]["rvc_version"] == "v1"
        assert created["metadata"]["rvc_version_detection"] == "detected"


def test_detected_rvc_version_overrides_user_choice_only_for_rvc() -> None:
    params = ModelService.apply_detected_rvc_version(
        {"framework": "rvc", "metadata": {"rvc_version": "v1"}},
        {"rvc_version": "v2", "pitch": 3},
    )
    other = ModelService.apply_detected_rvc_version(
        {"framework": "seed-vc", "metadata": {"rvc_version": "v1"}},
        {"rvc_version": "v2"},
    )

    assert params == {"rvc_version": "v1", "pitch": 3}
    assert other == {"rvc_version": "v2"}


def test_legacy_rvc_is_detected_and_persisted_on_first_list() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        model_path = root / "legacy.pth"
        model_path.write_bytes(b"checkpoint")
        repo = ListRepository(root / "models.json")
        repo.add(
            {
                "id": "legacy-rvc",
                "name": "Legacy RVC",
                "framework": "rvc",
                "main_model": {"name": model_path.name, "path": str(model_path)},
                "main_config": {"name": "", "path": ""},
            }
        )
        service = ModelService(repo, SettingsStore(root / "settings.json"))

        with patch.object(
            service,
            "_inspect_rvc_checkpoint",
            return_value={
                "rvc_version": "v2",
                "rvc_version_detection": "detected",
                "rvc_version_source": "weight.enc_p.emb_phone.weight[768]",
            },
        ):
            listed = service.list()

        assert listed[0]["metadata"]["rvc_version"] == "v2"
        assert repo.get("legacy-rvc")["metadata"]["rvc_version"] == "v2"
