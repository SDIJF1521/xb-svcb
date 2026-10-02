from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
import zipfile


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


def _cuda_torch_wheel(root: Path, relative: str, tag: str = "cp312") -> None:
    path = root / "assets" / "wheels" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "torch-2.7.1+cu128.dist-info/WHEEL",
            f"Tag: {tag}-{tag}-win_amd64\n",
        )
        archive.writestr(f"torch/_C.{tag}-win_amd64.pyd", b"")


def test_stage_wheelhouse_keeps_only_selected_stack(tmp_path: Path) -> None:
    stager = _load_stager()
    wheel_root = tmp_path / "assets" / "wheels"
    wheel_root.mkdir(parents=True)
    (wheel_root / "wheelhouse.json").write_text("{}", encoding="utf-8")
    _wheel(tmp_path, "bootstrap/uv.whl")
    _wheel(tmp_path, "common/metadata.whl")
    _wheel(tmp_path, "py312/cpu/torch-cpu.whl")
    _wheel(tmp_path, "py312/directml/torch-directml.whl")
    _wheel(tmp_path, "py312/cu126/torch-cu126.whl")
    _cuda_torch_wheel(tmp_path, "py312/cu128/torch-2.7.1+cu128-cp312-cp312-win_amd64.whl")
    _wheel(tmp_path, "pymss/py312/cu128/pymss-cu128.whl")
    _wheel(tmp_path, "ddsp-legacy/py312/cu128/fairseq-fixed.whl")
    _wheel(tmp_path, "pymss/py312/cu126/pymss-cu126.whl")
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
        "py312/cu128/torch-2.7.1+cu128-cp312-cp312-win_amd64.whl",
        "pymss/py312/cu128/pymss-cu128.whl",
        "ddsp-legacy/py312/cu128/fairseq-fixed.whl",
    }
    assert result["wheel_count"] == 5
    manifest = json.loads((output / "wheelhouse.json").read_text(encoding="utf-8"))
    assert manifest["package_stack"] == "cu128"
    assert sum(group["wheel_count"] for group in manifest["groups"]) == 5


def test_cuda_staging_rejects_retagged_python310_torch(tmp_path: Path) -> None:
    stager = _load_stager()
    wheel_root = tmp_path / "assets" / "wheels"
    wheel_root.mkdir(parents=True)
    (wheel_root / "wheelhouse.json").write_text("{}", encoding="utf-8")
    _wheel(tmp_path, "bootstrap/uv.whl")
    _cuda_torch_wheel(
        tmp_path,
        "py312/cu128/torch-2.7.1+cu128-cp312-cp312-win_amd64.whl",
        tag="cp310",
    )

    output = tmp_path / ".tmp" / "installer-wheelhouse"
    try:
        stager.stage_wheelhouse(tmp_path, "cu128", output)
    except RuntimeError as exc:
        assert "wrong Python ABI" in str(exc)
    else:
        raise AssertionError("retagged Python 3.10 CUDA Torch wheel was accepted")


def test_cpu_staging_requires_python312_component_groups(tmp_path: Path) -> None:
    stager = _load_stager()
    wheel_root = tmp_path / "assets" / "wheels"
    wheel_root.mkdir(parents=True)
    (wheel_root / "wheelhouse.json").write_text("{}", encoding="utf-8")
    _wheel(tmp_path, "bootstrap/uv.whl")
    _wheel(tmp_path, "py312/cpu/torch-cpu.whl")
    _wheel(tmp_path, "svc/py39/cpu/obsolete-svc.whl")
    _wheel(tmp_path, "rvc/py39/cpu/obsolete-rvc.whl")

    output = tmp_path / ".tmp" / "installer-wheelhouse"
    try:
        stager.stage_wheelhouse(tmp_path, "cpu", output)
    except RuntimeError as exc:
        assert "rebuild the wheelhouse" in str(exc)
        assert str(output / "svc" / "py312" / "cpu") in str(exc)
    else:
        raise AssertionError("stale Python 3.9 CPU wheelhouse was accepted")


def test_directml_staging_keeps_cpu_legacy_without_other_stack_wheels(tmp_path: Path) -> None:
    stager = _load_stager()
    wheel_root = tmp_path / "assets" / "wheels"
    wheel_root.mkdir(parents=True)
    (wheel_root / "wheelhouse.json").write_text("{}", encoding="utf-8")
    expected = {
        "bootstrap/uv.whl",
        "common/metadata.whl",
        "py312/directml/torch_directml-0.2.5.whl",
        "ddsp/py312/directml/torch-cpu.whl",
        "vocal/py312/directml/torch-cpu.whl",
        "hub/py312/directml/modelscope.whl",
        "ddsp-legacy/py312/cpu/torch-cpu.whl",
    }
    for path in expected | {
        "py312/cpu/torch-cpu.whl",
        "py312/rocm10/torch-rocm.whl",
        "py312/cu128/torch-cuda.whl",
        "pymss/py312/directml/pymss.whl",
        "svc/py312/cpu/other.whl",
    }:
        _wheel(tmp_path, path)

    output = tmp_path / ".tmp" / "installer-wheelhouse"
    result = stager.stage_wheelhouse(tmp_path, "directml", output)

    staged = {path.relative_to(output).as_posix() for path in output.rglob("*.whl")}
    assert staged == expected
    assert result["wheel_count"] == len(expected)


def test_directml_staging_requires_cpu_legacy_group(tmp_path: Path) -> None:
    stager = _load_stager()
    wheel_root = tmp_path / "assets" / "wheels"
    wheel_root.mkdir(parents=True)
    (wheel_root / "wheelhouse.json").write_text("{}", encoding="utf-8")
    for path in (
        "bootstrap/uv.whl",
        "py312/directml/torch_directml-0.2.5.whl",
        "ddsp/py312/directml/torch-cpu.whl",
        "vocal/py312/directml/torch-cpu.whl",
        "hub/py312/directml/modelscope.whl",
    ):
        _wheel(tmp_path, path)

    output = tmp_path / ".tmp" / "installer-wheelhouse"
    try:
        stager.stage_wheelhouse(tmp_path, "directml", output)
    except RuntimeError as exc:
        assert str(output / "ddsp-legacy" / "py312" / "cpu") in str(exc)
    else:
        raise AssertionError("DirectML wheelhouse without DDSP legacy CPU wheels was accepted")


def test_directml_staging_requires_directml_torch_wheel(tmp_path: Path) -> None:
    stager = _load_stager()
    wheel_root = tmp_path / "assets" / "wheels"
    wheel_root.mkdir(parents=True)
    (wheel_root / "wheelhouse.json").write_text("{}", encoding="utf-8")
    _wheel(tmp_path, "bootstrap/uv.whl")
    _wheel(tmp_path, "py312/directml/other.whl")

    output = tmp_path / ".tmp" / "installer-wheelhouse"
    try:
        stager.stage_wheelhouse(tmp_path, "directml", output)
    except RuntimeError as exc:
        assert "DirectML Torch wheel missing" in str(exc)
    else:
        raise AssertionError("DirectML wheelhouse without its Torch backend was accepted")


def test_stage_wheelhouse_rejects_output_outside_repo_tmp(tmp_path: Path) -> None:
    stager = _load_stager()
    wheel_root = tmp_path / "assets" / "wheels"
    wheel_root.mkdir(parents=True)
    (wheel_root / "wheelhouse.json").write_text("{}", encoding="utf-8")
    _wheel(tmp_path, "bootstrap/uv.whl")
    _wheel(tmp_path, "py312/cpu/torch-cpu.whl")

    try:
        stager.stage_wheelhouse(tmp_path, "cpu", tmp_path / "unsafe-output")
    except ValueError as exc:
        assert "must be a child" in str(exc)
    else:
        raise AssertionError("unsafe staging output was accepted")
