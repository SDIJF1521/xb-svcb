from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure import inference_device


class _Tensor:
    def cpu(self):
        return self


class _FakeTorch:
    float32 = "float32"

    def __init__(self, cuda: bool = False, hip: str | None = None) -> None:
        self.version = SimpleNamespace(hip=hip)
        self.cuda = SimpleNamespace(
            is_available=lambda: cuda,
            get_device_name=lambda index: "AMD Radeon ROCm" if hip else "NVIDIA Test GPU",
        )

    @staticmethod
    def device(value: str) -> str:
        return value

    @staticmethod
    def zeros(*_args, **_kwargs):
        return _Tensor()


def _load_installer_module():
    installer_path = Path(__file__).resolve().parents[2] / "install" / "install.py"
    spec = importlib.util.spec_from_file_location("xb_amd_installer", installer_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_directml_prefers_amd_adapter_over_runtime_default() -> None:
    directml = SimpleNamespace(
        is_available=lambda: True,
        device_count=lambda: 2,
        device_name=lambda index: ["Intel UHD Graphics", "AMD Radeon RX 7800 XT"][index],
        default_device=lambda: 0,
        device=lambda index: f"privateuseone:{index}",
    )
    with patch.dict(sys.modules, {"torch_directml": directml}):
        resolved = inference_device.resolve_torch_device("directml", _FakeTorch())

    assert resolved.backend == "directml"
    assert resolved.index == 1
    assert resolved.device == "privateuseone:1"
    assert resolved.name == "AMD Radeon RX 7800 XT"


def test_rocm_uses_pytorch_cuda_compatibility_device() -> None:
    resolved = inference_device.resolve_torch_device(
        "rocm",
        _FakeTorch(cuda=True, hip="6.2"),
    )

    assert resolved.backend == "rocm"
    assert resolved.device == "cuda:0"
    assert resolved.name == "AMD Radeon ROCm"


def test_explicit_directml_never_silently_falls_back_to_cpu() -> None:
    with patch.dict(sys.modules, {"torch_directml": None}):
        with pytest.raises(RuntimeError, match="DirectML"):
            inference_device.resolve_torch_device("directml", _FakeTorch())


def test_installer_detects_amd_as_directml_when_nvidia_is_absent() -> None:
    installer = _load_installer_module()
    completed = SimpleNamespace(stdout="AMD Radeon RX 7900 XTX\n", returncode=0)
    with patch.object(installer, "find_nvidia_smi", return_value=None), patch.object(
        installer.os, "name", "nt"
    ), patch.object(installer.subprocess, "run", return_value=completed):
        assert installer.detect_gpu_stack() == "directml"
