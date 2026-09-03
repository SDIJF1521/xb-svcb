from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from infrastructure.model_assets import inspect_manifest


def _manifest(root: Path, assets: list[dict]) -> None:
    path = root / "assets" / "models"
    path.mkdir(parents=True, exist_ok=True)
    (path / "model-manifest.json").write_text(
        json.dumps({"schema": "xb-svcb.models.v1", "assets": assets}),
        encoding="utf-8",
    )


def test_manifest_checks_size_and_hash(tmp_path: Path) -> None:
    source = tmp_path / "assets" / "models" / "voice.bin"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"voice-model")
    digest = hashlib.sha256(b"voice-model").hexdigest()
    _manifest(
        tmp_path,
        [{
            "id": "voice",
            "engine": "seedvc",
            "source": "assets/models/voice.bin",
            "required": True,
            "min_bytes": 4,
            "sha256": digest,
        }],
    )

    result = inspect_manifest(tmp_path, verify_hash=True)

    assert result["ok"] is True
    assert result["summary"]["ok"] == 1
    assert result["assets"][0]["files"][0]["sha256"] == digest


def test_required_missing_fails_but_optional_missing_does_not(tmp_path: Path) -> None:
    _manifest(
        tmp_path,
        [
            {"id": "required", "engine": "uvr", "source": "missing.pth", "required": True},
            {"id": "optional", "engine": "uvr", "source": "optional.pth", "required": False},
        ],
    )

    result = inspect_manifest(tmp_path)

    assert result["ok"] is False
    assert [row["status"] for row in result["assets"]] == ["missing", "optional_missing"]


def test_any_runtime_location_accepts_one_available_candidate(tmp_path: Path) -> None:
    runtime = tmp_path / "engines" / "seed-vc" / "checkpoints" / "model.pt"
    runtime.parent.mkdir(parents=True)
    runtime.write_bytes(b"runtime")
    _manifest(
        tmp_path,
        [{
            "id": "seed",
            "engine": "seedvc",
            "source": "source.pt",
            "runtime": ["engines/seed-vc/checkpoints/model.pt", "other/model.pt"],
            "runtime_mode": "any",
            "required": True,
        }],
    )

    result = inspect_manifest(tmp_path, location="runtime")

    assert result["ok"] is True
    assert result["assets"][0]["status"] == "ok"


def test_runtime_does_not_reuse_source_hash_for_transformed_asset(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    runtime = tmp_path / "runtime.bin"
    source.write_bytes(b"source")
    runtime.write_bytes(b"normalized-runtime")
    _manifest(
        tmp_path,
        [{
            "id": "normalized",
            "engine": "seedvc",
            "source": "source.bin",
            "runtime": "runtime.bin",
            "required": True,
            "sha256": hashlib.sha256(b"source").hexdigest(),
        }],
    )

    result = inspect_manifest(tmp_path, location="runtime", verify_hash=True)

    assert result["ok"] is True
    assert result["assets"][0]["status"] == "unverified"


def test_manifest_rejects_path_traversal(tmp_path: Path) -> None:
    _manifest(tmp_path, [{"id": "escape", "engine": "uvr", "source": "../outside.pth", "required": True}])

    result = inspect_manifest(tmp_path)

    assert result["ok"] is False
    assert result["assets"][0]["status"] == "invalid_path"


@pytest.mark.parametrize("location", ["source", "runtime", "both"])
def test_empty_manifest_is_safe(tmp_path: Path, location: str) -> None:
    _manifest(tmp_path, [])
    result = inspect_manifest(tmp_path, location=location)
    assert result["ok"] is False
