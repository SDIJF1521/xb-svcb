from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.packaging


def _load_module(name):
    spec = importlib.util.spec_from_file_location("xb_" + name, ROOT / "install" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_install_module():
    return _load_module("install")


@pytest.fixture
def wheelhouse_plan(tmp_path, monkeypatch):
    wheelhouse = _load_module("prepare_wheelhouse")
    installer = _load_install_module()
    installer._derive_paths(tmp_path)
    inputs = {
        "so-vits-svc": "numpy==1.23.5\neinops==0.8.2\nlocal-attention==1.10.0\n",
        "seed-vc": "numpy==1.26.4\n",
        "ddsp-svc": "numpy==1.26.4\ntransformers\n",
    }
    for engine, requirements in inputs.items():
        path = tmp_path / "engines" / engine / "requirements.txt"
        path.parent.mkdir(parents=True)
        path.write_text(requirements, encoding="utf-8")
    monkeypatch.setattr(wheelhouse, "_load_installer", lambda root: installer)
    return wheelhouse, tmp_path


def test_pymss_wheelhouse_is_isolated_with_a_compatible_torch_pair(wheelhouse_plan) -> None:
    wheelhouse, root = wheelhouse_plan
    installer = _load_install_module()
    expected_constraints = (
        "setuptools<81",
        "torch==2.7.1",
        "torchaudio==2.7.1",
    )

    for stack in ("cpu", "directml", "cu126", "cu128"):
        plan = wheelhouse.build_plan(root, {stack})
        expected_stack = stack
        dest = root / "assets" / "wheels" / "pymss" / "py310" / expected_stack
        package = next(batch for batch in plan if batch.label == f"pymss {expected_stack} package")
        torch = next(batch for batch in plan if batch.label == f"pymss {expected_stack} torch")

        assert package.dest == dest
        assert package.packages == ("pymss==2.0.18",)
        assert package.constraints == expected_constraints
        assert torch.dest == dest
        assert torch.packages == ("torch==2.7.1", "torchaudio==2.7.1")
        expected_index = (
            installer.TORCH_BLACKWELL_INDEX
            if expected_stack == "cu128"
            else installer.TORCH_PYMSS_CUDA_INDEX
            if expected_stack == "cu126"
            else installer.TORCH_CPU_INDEX
        )
        assert torch.index == expected_index


def test_wheelhouse_plan_builds_source_only_packages_and_splits_conflicting_torch(wheelhouse_plan) -> None:
    wheelhouse, root = wheelhouse_plan

    cpu = wheelhouse.build_plan(root, {"cpu"})
    directml = wheelhouse.build_plan(root, {"directml"})
    cu128 = wheelhouse.build_plan(root, {"cu128"})

    assert any(
        batch.dest == root / "assets" / "wheels" / "svc" / "py310" / "cpu"
        and batch.build_source
        and "fairseq==0.12.2" in batch.packages
        for batch in cpu
    )
    expected_matplotlib_support = (
        "contourpy==1.2.1",
        "cycler>=0.10",
        "fonttools>=4.22.0",
        "kiwisolver>=1.0.1",
        "packaging>=20.0",
        "pillow>=6.2.0",
        "pyparsing>=2.3.1",
        "python-dateutil>=2.7",
        "importlib-resources>=3.2.0",
    )
    assert any(
        batch.label == "svc py310 matplotlib support"
        and batch.dest == root / "assets" / "wheels" / "svc" / "py310" / "cpu"
        and batch.no_deps
        and batch.packages == expected_matplotlib_support
        for batch in cpu
    )
    assert any(
        batch.label == "svc py310 matplotlib"
        and batch.dest == root / "assets" / "wheels" / "svc" / "py310" / "cpu"
        and batch.no_deps
        and batch.packages == ("matplotlib==3.7.5",)
        for batch in cpu
    )
    assert any(
        batch.dest == root / "assets" / "wheels" / "rvc" / "py310" / "cpu"
        and batch.build_source
        and "fairseq==0.12.2" in batch.packages
        for batch in cpu
    )
    assert any(
        batch.dest == root / "assets" / "wheels" / "ddsp" / "py310" / "directml"
        and "torch==2.5.1" in batch.constraints
        for batch in directml
    )
    assert any(
        batch.label == "seedvc cpu source wheels"
        and batch.dest == root / "assets" / "wheels" / "py310" / "cpu"
        and batch.build_source
        and batch.no_deps
        and "argbind>=0.3.7" in batch.packages
        for batch in cpu
    )
    assert any(
        batch.label == "seedvc requirements"
        and batch.dest == root / "assets" / "wheels" / "py310" / "cpu"
        and batch.build_source
        for batch in cpu
    )
    assert any(
        batch.label == "seedvc directml source wheels"
        and batch.dest == root / "assets" / "wheels" / "py310" / "directml"
        and batch.build_source
        and batch.no_deps
        and "argbind>=0.3.7" in batch.packages
        for batch in directml
    )
    assert any(
        batch.label == "seedvc requirements"
        and batch.dest == root / "assets" / "wheels" / "py310" / "directml"
        and batch.build_source
        for batch in directml
    )
    assert any(
        batch.dest == root / "assets" / "wheels" / "py310" / "directml"
        and "torch==2.4.1" in batch.constraints
        for batch in directml
    )
    assert any(
        batch.label == "svc cu128 requirements"
        and batch.dest == root / "assets" / "wheels" / "py310" / "cu128"
        and batch.build_source
        for batch in cu128
    )
    expected_fcpe = ("einops==0.8.2", "local-attention==1.10.0")
    assert any(
        batch.label == "svc cpu py310 fcpe runtime"
        and batch.packages == expected_fcpe
        for batch in cpu
    )
    assert any(
        batch.label == "svc directml fcpe runtime"
        and batch.packages == expected_fcpe
        for batch in directml
    )
    assert any(
        batch.label == "svc cu128 fcpe runtime"
        and batch.packages == expected_fcpe
        for batch in cu128
    )
    svc_requirement_batches = [
        batch
        for batch in (*cpu, *directml, *cu128)
        if batch.label in {
            "svc py310 requirements",
            "svc directml requirements",
            "svc cu128 requirements",
        }
    ]
    assert svc_requirement_batches
    for batch in svc_requirement_batches:
        requirement_text = batch.requirements.read_text(encoding="utf-8")
        assert "einops==0.8.2" in requirement_text
        assert "local-attention==1.10.0" in requirement_text
    assert any(
        batch.label == "ddsp requirements"
        and batch.dest == root / "assets" / "wheels" / "py310" / "cpu"
        and batch.build_source
        for batch in cpu
    )
    assert any(
        batch.label == "ddsp directml requirements"
        and batch.dest == root / "assets" / "wheels" / "ddsp" / "py310" / "directml"
        and batch.build_source
        for batch in directml
    )

def test_plan_does_not_rewrite_upstream_requirements(wheelhouse_plan):
    wheelhouse, root = wheelhouse_plan
    sources = list((root / "engines").rglob("requirements.txt"))
    before = {p: p.read_bytes() for p in sources}
    plan = wheelhouse.build_plan(root, {"cpu"})
    assert plan
    assert all(p.read_bytes() == content for p, content in before.items())
    assert not list((root / "engines").rglob("requirements_xb*"))
    assert all(batch.requirements.is_relative_to(root / ".tmp")
               for batch in plan if batch.requirements)


def test_missing_packaging_sources_are_identified(tmp_path):
    wheelhouse = _load_module("prepare_wheelhouse")
    assert set(wheelhouse.missing_engine_requirements(tmp_path)) == {"so-vits-svc", "seed-vc", "ddsp-svc"}
    invalid = tmp_path / "engines/so-vits-svc/requirements.txt"
    invalid.mkdir(parents=True)
    assert "so-vits-svc" in wheelhouse.missing_engine_requirements(tmp_path)


@pytest.mark.packaging_integration
def test_staged_engine_requirements_support_wheelhouse_plan(request):
    wheelhouse = _load_module("prepare_wheelhouse")
    missing = wheelhouse.missing_engine_requirements(ROOT)
    if missing:
        details = "; ".join(f"{name}: " + " or ".join(str(p) for p in paths)
                            for name, paths in missing.items())
        reason = "Packaging inputs not staged (not a runtime failure): " + details
        if request.config.getoption("--require-packaging-inputs"):
            pytest.fail(reason)
        pytest.skip(reason)
    assert wheelhouse.build_plan(ROOT, {"cpu", "directml", "cu126", "cu128"})
