from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location("xb_" + name, ROOT / "install" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_checked_in_profile_is_portable_and_pins_all_versions():
    recipe = load("core_recipe")
    profile, pins = recipe.load_profile()
    assert len(pins) == 147
    assert pins["torch"] == "2.7.1+cu128"
    assert pins["numpy"] == "2.2.6"
    assert pins["protobuf"] == "7.36.0"
    assert profile["optional_packages"] == ["hf-xet"]
    assert not profile["rollback_is_known_healthy"]
    assert not profile["full_model_inference_validated"]
    for artifact in profile["artifacts"]:
        assert not Path(artifact["path"]).is_absolute()
        assert ".tmp" not in artifact["path"]


def test_recipe_rejects_lock_tampering(tmp_path):
    recipe = load("core_recipe")
    profile, _ = recipe.load_profile()
    (tmp_path / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
    (tmp_path / "requirements.lock").write_text("torch==0.1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="lock hash mismatch"):
        recipe.load_profile(tmp_path)


def test_artifacts_are_checked_before_use(tmp_path):
    recipe = load("core_recipe")
    artifact = tmp_path / "local.whl"
    artifact.write_bytes(b"original")
    profile = {"artifacts": [{"path": "local.whl", "group": "compat", "bytes": 8,
                              "sha256": recipe.sha256(artifact)}]}
    assert recipe.verify_artifacts(tmp_path, profile) == [artifact]
    artifact.write_bytes(b"modified")
    with pytest.raises(ValueError, match="hash/size mismatch"):
        recipe.verify_artifacts(tmp_path, profile)
    artifact.unlink()
    with pytest.raises(ValueError, match="Missing local"):
        recipe.verify_artifacts(tmp_path, profile)


def test_recipe_rejects_escaping_paths(tmp_path):
    with pytest.raises(ValueError, match="escapes"):
        load("core_recipe").contained(tmp_path, "../elsewhere")


def test_resolution_drift_is_not_silently_adopted(tmp_path):
    recipe = load("core_recipe")
    lock = tmp_path / "compiled.txt"
    lock.write_text("numpy==2.2.6\ndescript-audiotools @ file:///local.whl\n", encoding="utf-8")
    pins = {"numpy": "2.2.6", "descript-audiotools": "0.7.2+xb1"}
    recipe.verify_resolution(lock, pins)
    with pytest.raises(ValueError, match="drifted"):
        recipe.verify_resolution(lock, {**pins, "numpy": "1.26.4"})


def test_environment_check_reports_optional_transport_and_real_drift(monkeypatch):
    recipe = load("core_recipe")
    actual = {"python": "3.10.21", "system": "win32", "machine": "AMD64", "packages": {"numpy": "2.2.6"}}
    monkeypatch.setattr(recipe.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=json.dumps(actual)))
    profile = {"optional_packages": ["hf-xet"]}
    pins = {"numpy": "2.2.6", "hf-xet": "1.6.0"}
    report = recipe.check_environment(Path("python"), profile, pins)
    assert report["ok"] and report["missing_optional"] == ["hf-xet"]
    actual["packages"]["numpy"] = "1.26.4"
    assert not recipe.check_environment(Path("python"), profile, pins)["ok"]
    actual["packages"] = {"hf-xet": "1.6.0"}
    assert recipe.check_environment(Path("python"), profile, pins)["missing"] == ["numpy"]


def test_profile_preflight_uses_every_pin_and_package_specific_torch_source(tmp_path, monkeypatch):
    installer = load("install")
    installer._derive_paths(tmp_path)
    installer.CONSOLIDATED_RUNTIME = True
    installer.CORE_PROFILE = {"id": "core-cu128"}
    installer.CORE_PROFILE_PINS = {"numpy": "2.2.6", "torch": "2.7.1+cu128"}
    installer.CORE_COMPAT_WHEEL = tmp_path / "compat.whl"
    monkeypatch.setattr(installer, "_validate_core_compat_wheel", lambda p: None)
    monkeypatch.setattr(installer, "_wheelhouse_dirs", lambda **kw: [])
    for source in (installer.SEEDVC_DIR, installer.DDSP_DIR):
        source.mkdir(parents=True)
        (source / "requirements.txt").write_text("numpy==1.26.4\n", encoding="utf-8")

    def compile_only(command):
        assert command[1:3] == ["pip", "compile"]
        assert command[command.index("--torch-backend") + 1] == "cu128"
        assert installer.TORCH_BLACKWELL_INDEX not in command
        assert "--no-build" in command and "--no-python-downloads" in command
        inputs = Path(command[3]).read_text(encoding="utf-8")
        assert "numpy==2.2.6" in inputs and "torch==2.7.1+cu128" in inputs
        Path(command[command.index("--output-file") + 1]).write_text("numpy==2.2.6\ntorch==2.7.1+cu128\n")

    monkeypatch.setattr(installer, "run", compile_only)
    installer._preflight_consolidated_runtime("uv", {"uvr", "seedvc", "ddsp"}, "cu128")
    assert installer.CORE_CONSTRAINTS.is_file()
    assert not installer.RUNTIME_MANIFEST.exists()


def test_profile_pip_uses_same_torch_routing_and_lock(tmp_path, monkeypatch):
    installer = load("install")
    installer.CONSOLIDATED_RUNTIME = True
    installer.CORE_PROFILE = {"id": "core-cu128"}
    installer.CORE_CONSTRAINTS = tmp_path / "locked.txt"
    installer.CORE_CONSTRAINTS.write_text("torch==2.7.1+cu128\n")
    installer.CORE_COMPAT_WHEEL = tmp_path / "compat.whl"
    monkeypatch.setattr(installer, "_wheelhouse_args", lambda **kw: [])
    calls = []
    monkeypatch.setattr(installer, "run", calls.append)
    installer.uv_pip_install("uv", "python", "torch==2.7.1", component="uvr", index=installer.TORCH_BLACKWELL_INDEX)
    assert len(calls) == 1
    assert str(installer.CORE_CONSTRAINTS) in calls[0]
    assert "--torch-backend" in calls[0] and "--reinstall" not in calls[0]
    assert installer.TORCH_BLACKWELL_INDEX not in calls[0]


def test_recipe_files_are_packaged():
    source = (ROOT / "installer/xb-svcb.iss").read_text(encoding="utf-8")
    assert 'Source: "..\\install\\core_recipe.py"' in source
    assert 'Source: "..\\install\\runtime_profiles\\*"' in source
    assert 'Source: "..\\assets\\runtime\\*"' in source


def test_installer_loads_recipe_without_repository_on_sys_path(monkeypatch):
    installer = load("install")
    monkeypatch.setattr(installer.sys, "path", [p for p in installer.sys.path
                                               if p and not Path(p).resolve().is_relative_to(ROOT)])
    recipe = installer._recipe_module()
    assert Path(recipe.__file__).resolve() == ROOT / "install/core_recipe.py"
    assert recipe.load_profile()[1]["torch"] == "2.7.1+cu128"
