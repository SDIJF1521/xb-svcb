from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


def load_helper(name):
    path = Path(__file__).resolve().parents[2] / "install" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dependency_audit_detects_conflicts_but_ignores_unused_extras(monkeypatch):
    audit = load_helper("audit_runtime")
    distributions = [
        SimpleNamespace(metadata={"Name": "numpy"}, version="1.26.4", requires=[]),
        SimpleNamespace(metadata={"Name": "uvr"}, version="1", requires=[
            "numpy>=2", "missing>=1", "optional; extra == 'training'",
        ]),
    ]
    monkeypatch.setattr(audit.metadata, "distributions", lambda: distributions)
    issues = audit.dependency_issues()
    assert len(issues) == 2
    assert any("numpy>=2" in issue for issue in issues)
    assert any("MISSING" in issue for issue in issues)
    assert all("optional" not in issue for issue in issues)


def test_import_audit_is_offline_and_failure_is_reported(tmp_path, monkeypatch):
    audit = load_helper("audit_runtime")

    def fake_run(command, **kwargs):
        assert "socket.connect" in command[-1]
        assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        assert kwargs["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
        assert kwargs["timeout"] == 12
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="ImportError")

    monkeypatch.setattr(audit.subprocess, "run", fake_run)
    result = audit.probe("uvr", "import onnx", tmp_path, 12)
    assert not result["ok"]
    assert result["stderr"] == "ImportError"


def test_import_audit_handles_timeout(tmp_path, monkeypatch):
    audit = load_helper("audit_runtime")

    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(audit.subprocess, "run", timeout)
    result = audit.probe("seedvc", "import inference", tmp_path, 1)
    assert not result["ok"]
    assert result["timed_out"] is True
    assert result["timeout_seconds"] == 1
    assert result["error"] == "Import audit exceeded 1 seconds"


def test_ddsp_import_uses_its_longer_cold_start_timeout(tmp_path, monkeypatch):
    audit = load_helper("audit_runtime")
    seen: list[tuple[str, int]] = []

    def fake_probe(name, code, cwd, timeout):
        seen.append((name, timeout))
        return {"name": name, "ok": True}

    monkeypatch.setattr(audit, "probe", fake_probe)
    monkeypatch.setattr(audit, "dependency_issues", lambda: [])
    monkeypatch.setattr(
        audit.metadata,
        "version",
        lambda _name: (_ for _ in ()).throw(audit.metadata.PackageNotFoundError),
    )

    report = audit.audit(tmp_path, timeout=90, ddsp_timeout=180)

    assert report["ok"] is True
    assert seen == [
        ("torch", 90),
        ("uvr_mdx", 90),
        ("uvr_vr", 90),
        ("seedvc", 90),
        ("ddsp", 180),
    ]


@pytest.mark.parametrize("payload", [[], {"version": 2}, {"version": 1, "python": []},
                                     {"version": 1, "python": {"uvr": "missing.exe"}}])
def test_installer_manifest_invalid_or_missing_paths_fall_back(tmp_path, monkeypatch, payload):
    resolver = load_helper("runtime_manifest")
    monkeypatch.delenv("XB_UVR_PYTHON", raising=False)
    monkeypatch.delenv("XB_RUNTIME_MANIFEST", raising=False)
    (tmp_path / "runtime.json").write_text(json.dumps(payload), encoding="utf-8")
    assert resolver.resolve_python(tmp_path, "uvr", "legacy.exe") == tmp_path / "legacy.exe"


def test_installer_manifest_priority_and_external_relative_paths(tmp_path, monkeypatch):
    resolver = load_helper("runtime_manifest")
    directory = tmp_path / "external"
    directory.mkdir()
    shared = directory / "shared.exe"
    explicit = tmp_path / "explicit.exe"
    shared.touch()
    explicit.touch()
    manifest = directory / "runtime.json"
    manifest.write_text(json.dumps({"version": 1, "python": {"uvr": "shared.exe"}}), encoding="utf-8-sig")
    monkeypatch.setenv("XB_RUNTIME_MANIFEST", str(manifest))
    monkeypatch.setenv("XB_UVR_PYTHON", str(explicit))
    assert resolver.resolve_python(tmp_path, "uvr", "legacy.exe") == explicit
    monkeypatch.setenv("XB_UVR_PYTHON", str(tmp_path / "stale.exe"))
    assert resolver.resolve_python(tmp_path, "uvr", "legacy.exe") == shared
