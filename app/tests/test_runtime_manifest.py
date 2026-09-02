from __future__ import annotations

import json
from pathlib import Path

import pytest

import config


@pytest.fixture
def manifest_root(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNTIME_MANIFEST_FILE", tmp_path / "runtime.json")
    monkeypatch.setattr(config, "_RUNTIME_MANIFEST", {})
    return tmp_path


@pytest.mark.parametrize("payload", [[], {"version": 2}, {"python": {}}, None])
def test_unsupported_manifests_are_ignored(manifest_root, payload):
    config.RUNTIME_MANIFEST_FILE.write_text(json.dumps(payload), encoding="utf-8")
    assert config._load_runtime_manifest() == {}


def test_bom_and_invalid_json(manifest_root):
    payload = {"version": 1, "python": {"uvr": "core/python.exe"}}
    config.RUNTIME_MANIFEST_FILE.write_text(json.dumps(payload), encoding="utf-8-sig")
    assert config._load_runtime_manifest() == payload
    config.RUNTIME_MANIFEST_FILE.write_bytes(b"\xff\xfe\xff")
    assert config._load_runtime_manifest() == {}


@pytest.mark.parametrize("raw", [False, 42, [], {}, "", "missing/python.exe", "\x00"])
def test_invalid_interpreters_do_not_break_startup(manifest_root, monkeypatch, raw):
    monkeypatch.setattr(config, "_RUNTIME_MANIFEST", {"version": 1, "python": {"uvr": raw}})
    assert config._manifest_python("uvr") is None


def test_relative_path_is_anchored_to_manifest_not_cwd(manifest_root, monkeypatch):
    python = manifest_root / "core" / "python.exe"
    python.parent.mkdir()
    python.touch()
    monkeypatch.setattr(config, "ROOT_DIR", manifest_root / "another-checkout")
    monkeypatch.setattr(config, "_RUNTIME_MANIFEST", {
        "version": 1, "python": {"uvr": "core/python.exe"},
    })
    assert config._manifest_python("uvr") == python
    assert config._manifest_python("rvc") is None


@pytest.mark.parametrize("component, detector, variable", [
    ("uvr", "_detect_uvr_python", "XB_UVR_PYTHON"),
    ("seedvc", "_detect_seedvc_python", "XB_SEEDVC_PYTHON"),
    ("ddsp", "_detect_ddsp_python", "XB_DDSP_PYTHON"),
    ("svc", "_detect_svc_python", "XB_SVC_PYTHON"),
    ("rvc", "_detect_rvc_python", "XB_RVC_PYTHON"),
])
def test_explicit_then_manifest_priority(manifest_root, monkeypatch, component, detector, variable):
    shared = manifest_root / "shared.exe"
    explicit = manifest_root / "explicit.exe"
    shared.touch()
    explicit.touch()
    monkeypatch.setattr(config, "_RUNTIME_MANIFEST", {
        "version": 1, "python": {component: str(shared)},
    })
    monkeypatch.setenv(variable, str(explicit))
    assert getattr(config, detector)() == explicit
    monkeypatch.setenv(variable, str(manifest_root / "stale.exe"))
    assert getattr(config, detector)() == shared


def test_missing_manifest_interpreter_uses_legacy(manifest_root, monkeypatch):
    legacy = manifest_root / ".venv-uvr"
    python = config._venv_python(legacy)
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.delenv("XB_UVR_PYTHON", raising=False)
    monkeypatch.setattr(config, "UVR_VENV_DIR", legacy)
    monkeypatch.setattr(config, "_RUNTIME_MANIFEST", {
        "version": 1, "python": {"uvr": "missing.exe"},
    })
    assert config._detect_uvr_python() == python
