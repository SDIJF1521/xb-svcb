from __future__ import annotations

import csv
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import zipfile

import pytest
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

from infrastructure import inference_device, pymss_worker


def load(relative: str):
    spec = importlib.util.spec_from_file_location("xb_test_" + Path(relative).stem, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def torch_stub(hip=None, available=True, rocm=None):
    return SimpleNamespace(
        version=SimpleNamespace(hip=hip, rocm=rocm),
        __version__="2.13.0+rocm10.0.0",
        cuda=SimpleNamespace(is_available=lambda: available, get_device_name=lambda _: "AMD Radeon"),
        device=lambda name: name,
    )


@pytest.mark.parametrize("requested", ["auto", "gpu", "rocm", "rocm10", "amd", "hip"])
def test_pymss_hip_uses_cuda_interface_but_reports_rocm(monkeypatch, requested):
    monkeypatch.setitem(sys.modules, "torch", torch_stub("10.0"))
    assert pymss_worker._resolve_device(requested) == ("cuda", "rocm")


@pytest.mark.parametrize("requested,hip,available", [
    ("rocm", None, True), ("rocm", "10.0", False),
    ("cuda", "10.0", True), ("directml", "10.0", True),
])
def test_pymss_explicit_backend_never_silently_switches(monkeypatch, requested, hip, available):
    monkeypatch.setitem(sys.modules, "torch", torch_stub(hip, available))
    with pytest.raises(RuntimeError):
        pymss_worker._resolve_device(requested)


def test_pymss_auto_and_cpu_preserve_cpu_fallback(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", torch_stub("10.0", False))
    assert pymss_worker._resolve_device("auto") == ("cpu", "cpu")
    assert pymss_worker._resolve_device("cpu") == ("cpu", "cpu")


def test_amd_alias_selects_hip_on_windows():
    device = inference_device.resolve_torch_device("amd", torch_stub("10.0"))
    assert device.backend == "rocm"
    assert device.device == "cuda:0"


@pytest.mark.parametrize("backend", ["rocm", "directml"])
def test_pymss_capability_uses_its_own_runtime(tmp_path, monkeypatch, backend):
    import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "PYMSS_PYTHON", Path("pymss.exe"))

    def probe(python):
        selected = backend if python == config.PYMSS_PYTHON else "cpu"
        return {
            "ok": True, "backends": list(dict.fromkeys([selected, "cpu"])),
            "preferred": selected, "devices": [{"backend": selected, "name": "test device"}],
        }

    monkeypatch.setattr(inference_device, "probe_python_environment", probe)
    result = inference_device.inference_device_capabilities()
    pymss = result["frameworks"]["pymss"]
    if backend == "rocm":
        assert pymss["preferred"] == "rocm"
        assert next(option for option in result["options"] if option["value"] == "rocm")["frameworks"] == ["pymss"]
    else:
        assert pymss["backends"] == ["cpu"]
        assert pymss["preferred"] == "cpu"
        assert not any(option["value"] == "directml" for option in result["options"])


@pytest.mark.parametrize("hip,rocm,accepted", [
    (None, "10.0.0", False), ("7.2.1", "7.2.1", False),
    ("10.0.0", None, False), ("7.15.26333", "10.0.0", True),
])
def test_rocm_packaging_checks_actual_rocm_and_hip_markers(tmp_path, hip, rocm, accepted):
    stager = load("installer/stage_wheelhouse.py")
    wheel = tmp_path / "torch-2.9.1-cp312-cp312-win_amd64.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("torch/version.py", f"hip: str | None = {hip!r}\nrocm: str | None = {rocm!r}\n")
    if accepted:
        stager.validate_rocm_wheels(tmp_path)
    else:
        with pytest.raises(RuntimeError, match="Invalid ROCm 10 Torch wheel"):
            stager.validate_rocm_wheels(tmp_path)


def test_pymss_rocm_installer_selects_vendor_source_and_verifies(tmp_path, monkeypatch):
    monkeypatch.setenv("XB_TORCH_ROCM_INDEX", "https://vendor.example/rocm10/simple")
    monkeypatch.setenv("XB_ROCM_TORCH_VERSION", "2.9.1+rocm10.0")
    monkeypatch.setenv("XB_ROCM_TORCHAUDIO_VERSION", "2.8.0+rocm10.0")
    monkeypatch.setenv("XB_ROCM_TORCHVISION_VERSION", "0.24.1+rocm10.0")
    installer = load("install/install.py")
    installer._derive_paths(tmp_path)
    installs = []
    checks = []
    versions = []
    monkeypatch.setattr(installer, "ensure_venv", lambda uv, path, version: versions.append(version))
    monkeypatch.setattr(installer, "uv_pip_install", lambda *args, **kw: installs.append((args, kw)))
    monkeypatch.setattr(installer, "run", lambda *a, **kw: None)
    monkeypatch.setattr(installer, "_verify_rocm_torch", lambda py, component: checks.append(component))
    installer.step_pymss("uv", "rocm10")
    assert versions == ["3.12"]
    assert checks == ["pymss"]
    torch_installs = [(args, kw) for args, kw in installs if "torch[device-all]==2.9.1+rocm10.0" in args]
    assert torch_installs
    assert all(kw["index"] == "https://vendor.example/rocm10/simple" for args, kw in torch_installs)
    assert all(kw["gpu_stack"] == "rocm10" for args, kw in installs)
    assert all("torchaudio==2.8.0+rocm10.0" in args for args, kw in torch_installs)
    assert all("torchvision[device-all]==0.24.1+rocm10.0" in args for args, kw in torch_installs)
    assert next(i for i, (args, _) in enumerate(installs) if "torch[device-all]==2.9.1+rocm10.0" in args) < next(
        i for i, (args, _) in enumerate(installs) if "pymss==2.0.18" in args
    )
    assert any("--reinstall-package" in args for args, kw in torch_installs)
    with pytest.raises(RuntimeError, match="ROCm"):
        installer.step_pymss("uv", "directml")


@pytest.mark.parametrize("hip,rocm,available", [(None, "10.0", True), ("7.2.1", "7.2.1", True), ("7.15.26333", "10.0", False)])
def test_rocm_installation_probe_rejects_wrong_runtime(monkeypatch, hip, rocm, available):
    installer = load("install/install.py")
    monkeypatch.setitem(sys.modules, "torch", torch_stub(hip, available, rocm))

    def run(command):
        try:
            exec(command[2], {})
        except AssertionError:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(installer, "run", run)
    with pytest.raises(RuntimeError, match="ROCm 10"):
        installer._verify_rocm_torch("python", "PyMSS")


def test_rocm_probe_accepts_official_rocm10_with_hip7(monkeypatch):
    installer = load("install/install.py")
    torch = torch_stub("7.15.26333", True, "10.0.0")
    class Tensor:
        def __add__(self, other): return self
        def sum(self): return self
        def cpu(self): return self
        def item(self): return 8
    calls = []
    def ones(count, device):
        calls.append((count, device))
        return Tensor()
    torch.ones = ones
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setattr(installer, "run", lambda command: exec(command[2], {}))
    installer._verify_rocm_torch("python", "PyMSS")
    assert calls == [(4, "cuda")]


def test_rocm_wheelhouse_routes_all_engines_to_hip(tmp_path, monkeypatch):
    planner = load("install/prepare_wheelhouse.py")
    installer = load("install/install.py")
    installer._derive_paths(tmp_path)
    for name in ("so-vits-svc", "seed-vc", "ddsp-svc"):
        req = tmp_path / "engines" / name / "requirements.txt"
        req.parent.mkdir(parents=True)
        req.write_text("numpy==1.26.4\n", encoding="utf-8")
    monkeypatch.setattr(planner, "_load_installer", lambda _: installer)
    batches = planner.build_plan(tmp_path, {"rocm10"})
    torch_batches = [
        b for b in batches
        if any(Requirement(p).name in {"torch", "torchaudio", "torchvision"} for p in b.packages)
    ]
    assert len(torch_batches) >= 7
    assert all(b.index == installer.TORCH_ROCM_INDEX for b in torch_batches)
    assert all(b.python_version == "3.12" for b in batches)
    assert any(b.dest == tmp_path / "assets/wheels/pymss/py312/rocm10" for b in batches)
    assert not any("torch-directml" in p for b in batches for p in b.packages)
    assert all(not Requirement(c).extras for b in batches for c in b.constraints)
    assert len([b for b in batches if b.label == "pymss rocm10 torch"]) == 1
    legacy = next(b for b in batches if b.label == "ddsp legacy requirements")
    assert legacy.dest == tmp_path / "assets/wheels/ddsp-legacy/py312/rocm10"
    assert "fairseq-fixed==0.12.3.1" in legacy.packages
    assert "local-attention" in legacy.packages
    assert "numba==0.60.0" in legacy.requirements.read_text()


def test_rocm_defaults_match_amd_official_release(monkeypatch):
    for name in ("XB_TORCH_ROCM_INDEX", "XB_ROCM_TORCH_VERSION", "XB_ROCM_TORCHAUDIO_VERSION", "XB_ROCM_TORCHVISION_VERSION"):
        monkeypatch.delenv(name, raising=False)
    installer = load("install/install.py")
    assert installer.TORCH_ROCM_INDEX.rstrip("/") == "https://stable.repo.amd.com/rocm/whl-next"
    assert installer._modern_torch_specs("rocm10", include_vision=True) == [
        "torch[device-all]==2.13.0+rocm10.0.0", "torchaudio==2.11.0.2+rocm10.0.0",
        "torchvision[device-all]==0.28.0+rocm10.0.0",
    ]


def test_uvr_installer_pins_audio_separator_runtime_contract(tmp_path, monkeypatch):
    installer = load("install/install.py")
    installer._derive_paths(tmp_path)
    installs = []
    monkeypatch.setattr(installer, "ensure_venv", lambda *args, **kwargs: None)
    monkeypatch.setattr(installer, "_repair_broken_wheel_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(installer, "uv_pip_install", lambda *args, **kwargs: installs.append((args, kwargs)))
    monkeypatch.setattr(installer, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(installer, "_reaffirm_rocm_runtime", lambda *args, **kwargs: None)

    installer.step_uvr("uv", "rocm10")

    compatibility_installs = [
        args for args, _ in installs
        if "audioread>=3.0,<4" in args or "librosa==0.10.2" in args
    ]
    assert compatibility_installs == [
        ("uv", str(installer.venv_python(installer.UVR_VENV)), "audioread>=3.0,<4", "librosa==0.10.2")
    ]


def test_rocm_dependency_installs_keep_vendor_versions(tmp_path, monkeypatch):
    installer = load("install/install.py")
    installer._derive_paths(tmp_path)
    calls = []
    monkeypatch.setattr(installer, "run", lambda command: calls.append(command))
    installer.uv_pip_install("uv", "python", "pymss==2.0.18", gpu_stack="rocm10")
    command = calls[0]
    constraints = Path(command[command.index("-c") + 1])
    assert constraints.read_text().splitlines() == list(installer._rocm_constraints())
    assert installer.TORCH_ROCM_INDEX in command


def test_rvc_wheel_keeps_code_and_validates_record(tmp_path):
    builder = load("install/build_rvc_compat.py")
    original = "rvc_python-0.1.5.dist-info"
    metadata = "Metadata-Version: 2.1\nName: rvc-python\nVersion: 0.1.5\nRequires-Python: >=3.9\n"
    metadata += "".join(f"Requires-Dist: {req}\n" for req in builder.REPLACEMENTS)
    payload = {original + "/METADATA": metadata.encode(), "rvc_python/infer.py": b"# upstream code\n"}
    rows = io.StringIO()
    writer = csv.writer(rows, lineterminator="\n")
    for name, data in payload.items():
        writer.writerow((name, "sha256=" + builder.digest(data), len(data)))
    writer.writerow((original + "/RECORD", "", ""))
    payload[original + "/RECORD"] = rows.getvalue().encode()
    source = tmp_path / "source.whl"
    with zipfile.ZipFile(source, "w") as wheel:
        for name, data in payload.items():
            wheel.writestr(name, data)
    result = builder.build(source, tmp_path / "out")
    with zipfile.ZipFile(result) as wheel:
        assert wheel.read("rvc_python/infer.py") == payload["rvc_python/infer.py"]
        metadata = wheel.read(f"rvc_python-{builder.VERSION}.dist-info/METADATA").decode()
        assert "fairseq-fixed==0.12.3.1" in metadata
        assert "Requires-Python: >=3.12,<3.13" in metadata
        assert "numpy<=1.23.5" not in metadata
    payload["rvc_python/infer.py"] = b"changed"
    with zipfile.ZipFile(source, "w") as wheel:
        for name, data in payload.items():
            wheel.writestr(name, data)
    with pytest.raises(ValueError, match="RECORD mismatch"):
        builder.build(source, tmp_path / "bad")
