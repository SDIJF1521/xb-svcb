from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location("test_" + name, ROOT / "install" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def missing(name="example", version="1.0"):
    return f"Failed to download `{name}=={version}` https://example.invalid/{name}-1.0-py3-none-any.whl"


@pytest.mark.parametrize("name", ["torch", "torchaudio", "torchvision", "triton", "onnxruntime-gpu", "nvidia-cublas-cu12"])
def test_large_runtime_download_denied_before_network(tmp_path, monkeypatch, name):
    validator = load("validate_core_install")
    monkeypatch.setattr(validator.urllib.request, "urlopen", lambda *a, **kw: pytest.fail("network called"))
    with pytest.raises(ValueError, match="reserved for user"):
        validator.small_missing_wheel(missing(name), tmp_path, 0)


def test_unidentified_failure_does_not_download(tmp_path, monkeypatch):
    validator = load("validate_core_install")
    monkeypatch.setattr(validator.urllib.request, "urlopen", lambda *a, **kw: pytest.fail("network called"))
    with pytest.raises(ValueError, match="not an identifiable"):
        validator.small_missing_wheel("Dependency conflict", tmp_path, 0)


@pytest.mark.parametrize("size,spent", [(65 * 1024**2, 0), (1024, 200 * 1024**2)])
def test_download_size_and_cumulative_budget(tmp_path, monkeypatch, size, spent):
    validator = load("validate_core_install")
    metadata = {"urls": [{"filename": "example-1.0-py3-none-any.whl", "size": size}]}

    def metadata_only(url, **kw):
        assert url.startswith("https://pypi.org/pypi/")
        return io.BytesIO(json.dumps(metadata).encode())

    monkeypatch.setattr(validator.urllib.request, "urlopen", metadata_only)
    with pytest.raises(ValueError, match="budget exceeded"):
        validator.small_missing_wheel(missing(), tmp_path, spent)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("valid_hash", [True, False])
def test_download_must_match_official_hash(tmp_path, monkeypatch, valid_hash):
    validator = load("validate_core_install")
    content = b"wheel contents"
    digest = validator.hashlib.sha256(content).hexdigest()
    metadata = {"urls": [{"filename": "example-1.0-py3-none-any.whl", "size": len(content),
                          "url": "https://files.pythonhosted.org/example.whl",
                          "digests": {"sha256": digest if valid_hash else "0" * 64}}]}
    monkeypatch.setattr(validator.urllib.request, "urlopen",
                        lambda url, **kw: io.BytesIO(json.dumps(metadata).encode() if "pypi.org/pypi" in url else content))
    if valid_hash:
        assert validator.small_missing_wheel(missing(), tmp_path, 0)["sha256"] == digest
    else:
        with pytest.raises(ValueError, match="SHA-256 mismatch"):
            validator.small_missing_wheel(missing(), tmp_path, 0)
        assert not list(tmp_path.glob("*.whl"))


def test_validator_refuses_live_environment(tmp_path, monkeypatch):
    validator = load("validate_core_install")
    monkeypatch.setenv("TEMP", str(tmp_path))
    with pytest.raises(ValueError, match="separately created"):
        validator.validate_sandbox(ROOT / ".venv-uvr")
    sandbox = tmp_path / "xb-core-install-check-test"
    python = sandbox / "venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    assert validator.validate_sandbox(sandbox) == python


@pytest.mark.parametrize("drift", [False, True])
def test_installer_activates_only_exact_profile(tmp_path, monkeypatch, drift):
    installer = load("install")
    installer._derive_paths(tmp_path)
    monkeypatch.setattr(installer.sys, "argv", ["install.py", "--consolidated", "--cu128", "--only", "uvr", "seedvc", "ddsp"])
    monkeypatch.setattr(installer, "detect_gpu_stack", lambda: "cu128")
    monkeypatch.setattr(installer, "_configure_core_profile", lambda *a: None)
    installer.CORE_PROFILE = {"id": "test"}
    installer.CORE_PROFILE_PINS = {"numpy": "2.2.6"}
    monkeypatch.setattr(installer, "_recipe_module", lambda: SimpleNamespace(
        check_environment=lambda *a: {"ok": not drift, "changed": {"numpy": "1.26.4"} if drift else {}}))
    monkeypatch.setattr(installer, "ensure_uv", lambda: "uv")
    monkeypatch.setattr(installer, "_preflight_consolidated_runtime", lambda *a: None)
    monkeypatch.setattr(installer, "run", lambda *a: None)
    monkeypatch.setattr(installer, "STEPS", {name: lambda *a: None for name in installer.ORDER})
    activated = []
    monkeypatch.setattr(installer, "write_runtime_manifest", lambda *a: activated.append(a))
    assert installer.main() == (1 if drift else 0)
    assert bool(activated) is not drift


def test_shared_step_failure_stops_remaining_components_and_activation(tmp_path, monkeypatch, capsys):
    installer = load("install")
    installer._derive_paths(tmp_path)
    monkeypatch.setattr(installer.sys, "argv", ["install.py", "--consolidated", "--cpu", "--only", "uvr", "seedvc", "ddsp"])
    monkeypatch.setattr(installer, "ensure_uv", lambda: "uv")
    monkeypatch.setattr(installer, "_preflight_consolidated_runtime", lambda *a: None)
    monkeypatch.setattr(installer, "run", lambda *a: pytest.fail("post-failure operation"))
    monkeypatch.setattr(installer, "write_runtime_manifest", lambda *a: pytest.fail("activated failed environment"))
    calls = []

    def fail_first(*a):
        calls.append("uvr")
        raise RuntimeError("simulated partial installation failure")

    monkeypatch.setattr(installer, "STEPS", {"uvr": fail_first, "seedvc": lambda *a: calls.append("seedvc"),
                                           "ddsp": lambda *a: calls.append("ddsp")})
    assert installer.main() == 1
    assert calls == ["uvr"]
    output = capsys.readouterr().out
    assert "不要单独修复组件" in output
    assert "--only svc" not in output


def test_storage_inventory_counts_hardlinks_with_real_file_identity(tmp_path):
    audit = load("audit_storage")
    folder = tmp_path / ".venv-uvr-demo"
    folder.mkdir()
    source = folder / "one.bin"
    source.write_bytes(b"a" * 100)
    os.link(source, folder / "two.bin")
    os.link(source, tmp_path / "outside.bin")
    skipped, errors = [], []
    entries = list(audit.files_under(folder, skipped, errors))
    assert not errors and not skipped
    records = [{"identity": audit.file_identity(path, info), "bytes": info.st_size,
                "links": info.st_nlink, "child": "files"} for path, info in entries]
    summary = audit.summarize(records)
    assert summary["logical_bytes"] == 200
    assert summary["unique_file_bytes"] == 100
    assert summary["hardlinked_file_bytes"] == 100
    assert summary["exclusive_file_bytes_upper_bound"] == 0  # outside link retains storage


def test_model_hashes_do_not_confuse_same_size_or_hardlinks(tmp_path):
    audit = load("audit_storage")
    source, duplicate, different, linked = [tmp_path / name for name in ("one", "two", "three", "four")]
    source.write_bytes(b"same")
    duplicate.write_bytes(b"same")
    different.write_bytes(b"diff")
    os.link(source, linked)
    # Size threshold is represented in records; small fixtures still exercise actual hashing.
    records = [{"group": "assets/models", "path": str(path), "identity": audit.file_identity(path, path.stat()),
                "bytes": 32 * 1024**2} for path in (source, duplicate, different, linked)]
    groups = audit.duplicate_models(records)
    assert len(groups) == 1
    assert groups[0]["distinct_files"] == 2
    assert groups[0]["duplicate_logical_bytes"] == 32 * 1024**2
    assert str(different) not in groups[0]["paths"]


def test_readonly_inventory_preserves_files_and_reports_missing_groups(tmp_path):
    audit = load("audit_storage")
    folder = tmp_path / ".tmp"
    folder.mkdir()
    original = folder / "keep.txt"
    original.write_bytes(b"do not delete")
    before = original.stat().st_mtime_ns
    report = audit.inventory(tmp_path)
    assert original.read_bytes() == b"do not delete"
    assert original.stat().st_mtime_ns == before
    group = next(row for row in report["groups"] if row["group"] == ".tmp")
    assert group["exclusive_file_bytes_upper_bound"] == len(b"do not delete")
    assert next(row for row in report["groups"] if row["group"] == ".venv-uvr")["missing"]
