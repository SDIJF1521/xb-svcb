from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load_stager():
    script = ROOT / "installer" / "stage_wheelhouse.py"
    spec = importlib.util.spec_from_file_location("xb_stage_wheelhouse", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _wheel(root: Path, relative: str) -> None:
    path = root / "assets" / "wheels" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(relative.encode("ascii"))


def test_stage_wheelhouse_keeps_only_selected_stack(tmp_path: Path) -> None:
    stager = _load_stager()
    wheel_root = tmp_path / "assets" / "wheels"
    wheel_root.mkdir(parents=True)
    (wheel_root / "wheelhouse.json").write_text("{}", encoding="utf-8")
    _wheel(tmp_path, "bootstrap/uv.whl")
    _wheel(tmp_path, "common/metadata.whl")
    _wheel(tmp_path, "py310/cpu/torch-cpu.whl")
    _wheel(tmp_path, "py310/directml/torch-directml.whl")
    _wheel(tmp_path, "py310/cu126/torch-cu126.whl")
    _wheel(tmp_path, "py310/cu128/torch-cu128.whl")
    _wheel(tmp_path, "pymss/py310/cu128/pymss-cu128.whl")
    _wheel(tmp_path, "pymss/py310/cu126/pymss-cu126.whl")
    _wheel(tmp_path, "svc/py39/cu128/obsolete.whl")

    output = tmp_path / ".tmp" / "installer-wheelhouse"
    result = stager.stage_wheelhouse(tmp_path, "cu128", output)

    staged = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*.whl")
    }
    assert staged == {
        "bootstrap/uv.whl",
        "common/metadata.whl",
        "py310/cu128/torch-cu128.whl",
        "pymss/py310/cu128/pymss-cu128.whl",
    }
    assert result["wheel_count"] == 4
    manifest = json.loads((output / "wheelhouse.json").read_text(encoding="utf-8"))
    assert manifest["package_stack"] == "cu128"
    assert sum(group["wheel_count"] for group in manifest["groups"]) == 4


def test_cpu_staging_requires_python310_component_groups(tmp_path: Path) -> None:
    stager = _load_stager()
    wheel_root = tmp_path / "assets" / "wheels"
    wheel_root.mkdir(parents=True)
    (wheel_root / "wheelhouse.json").write_text("{}", encoding="utf-8")
    _wheel(tmp_path, "bootstrap/uv.whl")
    _wheel(tmp_path, "py310/cpu/torch-cpu.whl")
    _wheel(tmp_path, "svc/py39/cpu/obsolete-svc.whl")
    _wheel(tmp_path, "rvc/py39/cpu/obsolete-rvc.whl")

    output = tmp_path / ".tmp" / "installer-wheelhouse"
    try:
        stager.stage_wheelhouse(tmp_path, "cpu", output)
    except RuntimeError as exc:
        assert "rebuild the wheelhouse" in str(exc)
        assert str(output / "svc" / "py310" / "cpu") in str(exc)
    else:
        raise AssertionError("stale Python 3.9 CPU wheelhouse was accepted")


def test_stage_wheelhouse_rejects_output_outside_repo_tmp(tmp_path: Path) -> None:
    stager = _load_stager()
    wheel_root = tmp_path / "assets" / "wheels"
    wheel_root.mkdir(parents=True)
    (wheel_root / "wheelhouse.json").write_text("{}", encoding="utf-8")
    _wheel(tmp_path, "bootstrap/uv.whl")
    _wheel(tmp_path, "py310/cpu/torch-cpu.whl")

    try:
        stager.stage_wheelhouse(tmp_path, "cpu", tmp_path / "unsafe-output")
    except ValueError as exc:
        assert "must be a child" in str(exc)
    else:
        raise AssertionError("unsafe staging output was accepted")
