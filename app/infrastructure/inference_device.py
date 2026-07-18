"""
统一的 PyTorch 加速器检测，适用于孤立的推理环境。
应用程序在各自的虚拟环境中启动每个模型家族。这个
模块既被工作进程导入，又由主进程作为小型探针执行，
因此用户界面功能始终描述的是实际安装的软件包，
而不仅仅是物理显示适配器。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


DEVICE_PROBE_MARKER = "XB_DEVICE_PROBE "
_AMD_TOKENS = ("amd", "radeon")
_PROBE_TTL_SECONDS = 300.0
_probe_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_probe_lock = threading.Lock()


@dataclass(frozen=True)
class ResolvedDevice:
    device: Any
    backend: str
    name: str
    index: int = 0

    @property
    def accelerated(self) -> bool:
        return self.backend != "cpu"

    @property
    def torch_device_type(self) -> str:
        return str(getattr(self.device, "type", str(self.device).split(":", 1)[0]))


class _DirectMLComplexTensor:
    """CPU complex tensor whose real-valued views return to DirectML."""

    def __init__(self, tensor: Any, target_device: Any) -> None:
        self.tensor = tensor
        self.target_device = target_device

    @property
    def real(self) -> Any:
        return self.tensor.real.to(self.target_device)

    @property
    def imag(self) -> Any:
        return self.tensor.imag.to(self.target_device)

    @property
    def shape(self) -> Any:
        return self.tensor.shape

    def size(self, *args: Any) -> Any:
        return self.tensor.size(*args)

    def abs(self) -> Any:
        return self.tensor.abs().to(self.target_device)


def _is_directml_tensor(value: Any) -> bool:
    return str(getattr(value, "device", "")).startswith("privateuseone")


def _cpu_tensor(value: Any) -> Any:
    return value.cpu() if _is_directml_tensor(value) else value


def patch_directml_audio_ops(torch: Any) -> None:
    """Run unsupported complex FFT operators on CPU and return real data to DML.

    DirectML 0.2.5 terminates the process when a ComplexFloat tensor is created
    on the private backend. Voice models only need the real/imaginary views or
    the reconstructed waveform, so the complex intermediate can safely remain
    on CPU while the neural network stays on the GPU.
    """
    if getattr(torch, "_xb_directml_audio_patch", False):
        return

    original_stft = torch.stft
    original_istft = torch.istft
    original_complex = torch.complex
    original_view_as_real = torch.view_as_real

    def cpu_args(values: tuple[Any, ...]) -> tuple[Any, ...]:
        return tuple(_cpu_tensor(value) for value in values)

    def cpu_kwargs(values: dict[str, Any]) -> dict[str, Any]:
        return {key: _cpu_tensor(value) for key, value in values.items()}

    def stft_compat(input_tensor: Any, *args: Any, **kwargs: Any) -> Any:
        if not _is_directml_tensor(input_tensor):
            return original_stft(input_tensor, *args, **kwargs)
        target = input_tensor.device
        result = original_stft(
            input_tensor.cpu(),
            *cpu_args(args),
            **cpu_kwargs(kwargs),
        )
        if getattr(result, "is_complex", lambda: False)():
            return _DirectMLComplexTensor(result, target)
        return result.to(target)

    def view_as_real_compat(input_tensor: Any) -> Any:
        if isinstance(input_tensor, _DirectMLComplexTensor):
            return original_view_as_real(input_tensor.tensor).to(input_tensor.target_device)
        return original_view_as_real(input_tensor)

    def complex_compat(real: Any, imag: Any, *args: Any, **kwargs: Any) -> Any:
        if _is_directml_tensor(real) or _is_directml_tensor(imag):
            target = real.device if _is_directml_tensor(real) else imag.device
            result = original_complex(_cpu_tensor(real), _cpu_tensor(imag), *args, **kwargs)
            return _DirectMLComplexTensor(result, target)
        return original_complex(real, imag, *args, **kwargs)

    def istft_compat(input_tensor: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(input_tensor, _DirectMLComplexTensor):
            result = original_istft(
                input_tensor.tensor,
                *cpu_args(args),
                **cpu_kwargs(kwargs),
            )
            return result.to(input_tensor.target_device)
        return original_istft(input_tensor, *args, **kwargs)

    torch.stft = stft_compat
    torch.view_as_real = view_as_real_compat
    torch.complex = complex_compat
    torch.istft = istft_compat
    torch._xb_directml_audio_patch = True


def normalize_device(value: str) -> str:
    requested = str(value or "auto").strip().lower()
    aliases = {
        "gpu": "auto",
        "amd": "directml" if os.name == "nt" else "rocm",
        "dml": "directml",
        "hip": "rocm",
        "cpu:0": "cpu",
    }
    requested = aliases.get(requested, requested)
    if requested.startswith("cuda"):
        return "cuda"
    if requested.startswith("privateuseone"):
        return "directml"
    return requested


def _cuda_device(torch: Any, requested: str) -> Optional[ResolvedDevice]:
    try:
        if not torch.cuda.is_available():
            return None
        raw = str(requested or "cuda")
        index = int(raw.split(":", 1)[1]) if ":" in raw else 0
        device = torch.device(f"cuda:{index}")
        name = str(torch.cuda.get_device_name(index) or f"GPU {index}")
        backend = "rocm" if getattr(torch.version, "hip", None) else "cuda"
        return ResolvedDevice(device=device, backend=backend, name=name, index=index)
    except Exception:
        return None


def _directml_device(torch: Any) -> Optional[ResolvedDevice]:
    try:
        import torch_directml  # type: ignore

        if not torch_directml.is_available():
            return None
        count = int(torch_directml.device_count())
        if count <= 0:
            return None
        configured = os.environ.get("XB_DIRECTML_DEVICE", "").strip()
        if configured.isdigit() and int(configured) < count:
            index = int(configured)
        else:
            names = [str(torch_directml.device_name(i) or "") for i in range(count)]
            index = next(
                (i for i, name in enumerate(names) if any(token in name.lower() for token in _AMD_TOKENS)),
                int(torch_directml.default_device()),
            )
        device = torch_directml.device(index)
        # A real allocation catches missing/outdated DirectX drivers early.
        torch.zeros(1, dtype=torch.float32, device=device).cpu()
        name = str(torch_directml.device_name(index) or f"DirectML GPU {index}")
        return ResolvedDevice(device=device, backend="directml", name=name, index=index)
    except Exception:
        return None


def resolve_torch_device(requested: str = "auto", torch_module: Any = None) -> ResolvedDevice:
    torch = torch_module
    if torch is None:
        import torch as torch_module_imported

        torch = torch_module_imported

    normalized = normalize_device(requested)
    if normalized == "cpu":
        return ResolvedDevice(torch.device("cpu"), "cpu", "CPU")

    if normalized in {"cuda", "rocm"}:
        resolved = _cuda_device(torch, requested)
        if resolved is None:
            raise RuntimeError(f"已选择 {normalized.upper()}，但当前推理环境没有可用设备")
        if normalized == "rocm" and resolved.backend != "rocm":
            raise RuntimeError("已选择 AMD ROCm，但当前推理环境安装的是 NVIDIA CUDA")
        if normalized == "cuda" and resolved.backend == "rocm":
            return resolved
        return resolved

    if normalized == "directml":
        resolved = _directml_device(torch)
        if resolved is None:
            raise RuntimeError("已选择 AMD DirectML，但当前推理环境未安装 torch-directml 或驱动不可用")
        return resolved

    if normalized not in {"", "auto"}:
        raise RuntimeError(f"不支持的推理设备: {requested}")

    resolved = _cuda_device(torch, "cuda:0")
    if resolved is not None:
        return resolved
    resolved = _directml_device(torch)
    if resolved is not None:
        return resolved
    return ResolvedDevice(torch.device("cpu"), "cpu", "CPU")


def patch_directml_float32(torch: Any) -> None:
    """Disable half/autocast paths that are not stable on DirectML voice models."""
    patch_directml_audio_ops(torch)
    if getattr(torch, "_xb_directml_float32_patch", False):
        return

    original_autocast = torch.autocast

    def autocast_compat(device_type: str, *args: Any, **kwargs: Any):
        if str(device_type).lower() == "privateuseone":
            return nullcontext()
        return original_autocast(device_type, *args, **kwargs)

    torch.autocast = autocast_compat
    torch._xb_directml_float32_patch = True


def patch_directml_no_half(torch: Any) -> None:
    """Make legacy unconditional ``half()`` calls use fp32 for DirectML."""
    patch_directml_float32(torch)
    if getattr(torch, "_xb_directml_no_half_patch", False):
        return

    def tensor_half(self: Any, *args: Any, **kwargs: Any):
        return self.float()

    def module_half(self: Any):
        return self.float()

    torch.Tensor.half = tensor_half
    torch.nn.Module.half = module_half
    torch._xb_directml_no_half_patch = True


def runtime_probe() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "torch_version": "",
        "backends": ["cpu"],
        "devices": [],
        "preferred": "cpu",
    }
    try:
        import torch

        payload["torch_version"] = str(torch.__version__)
        cuda = _cuda_device(torch, "cuda:0")
        directml = _directml_device(torch)
        devices: list[dict[str, Any]] = []
        backends = ["cpu"]
        if cuda is not None:
            backends.insert(0, cuda.backend)
            devices.append(
                {"backend": cuda.backend, "name": cuda.name, "index": cuda.index}
            )
        if directml is not None:
            backends.insert(0 if cuda is None else 1, "directml")
            devices.append(
                {"backend": "directml", "name": directml.name, "index": directml.index}
            )
        payload.update(
            ok=True,
            backends=backends,
            devices=devices,
            preferred=(cuda.backend if cuda is not None else "directml" if directml is not None else "cpu"),
        )
    except Exception as exc:
        payload["error"] = str(exc)
    return payload


def probe_python_environment(python: Optional[Path]) -> dict[str, Any]:
    if not python or not python.exists():
        return {
            "ok": False,
            "torch_version": "",
            "backends": ["cpu"],
            "devices": [],
            "preferred": "cpu",
            "error": "推理环境未安装",
        }
    key = str(python.resolve())
    now = time.monotonic()
    with _probe_lock:
        cached = _probe_cache.get(key)
        if cached and now - cached[0] < _PROBE_TTL_SECONDS:
            return dict(cached[1])
    try:
        proc = subprocess.run(
            [str(python), str(Path(__file__).resolve()), "--probe"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        line = next(
            (row[len(DEVICE_PROBE_MARKER) :] for row in proc.stdout.splitlines() if row.startswith(DEVICE_PROBE_MARKER)),
            "",
        )
        payload = json.loads(line) if line else {
            "ok": False,
            "torch_version": "",
            "backends": ["cpu"],
            "devices": [],
            "preferred": "cpu",
            "error": (proc.stderr or proc.stdout or "设备探测失败").strip().splitlines()[-1],
        }
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, IndexError) as exc:
        payload = {
            "ok": False,
            "torch_version": "",
            "backends": ["cpu"],
            "devices": [],
            "preferred": "cpu",
            "error": str(exc),
        }
    with _probe_lock:
        _probe_cache[key] = (now, dict(payload))
    return payload


def inference_device_capabilities() -> dict[str, Any]:
    import config

    environments = {
        "uvr": config.UVR_PYTHON,
        "so-vits-svc": config.SVC_PYTHON,
        "rvc": config.RVC_PYTHON,
        "seed-vc": config.SEEDVC_PYTHON,
        "ddsp-svc": config.DDSP_PYTHON,
    }
    with ThreadPoolExecutor(max_workers=len(environments)) as pool:
        futures = {
            framework: pool.submit(probe_python_environment, python)
            for framework, python in environments.items()
        }
        frameworks = {framework: future.result() for framework, future in futures.items()}

    labels = {
        "cuda": "NVIDIA GPU (CUDA)",
        "rocm": "AMD GPU (ROCm)",
        "directml": "AMD GPU (DirectML)",
        "cpu": "CPU",
    }
    options = [
        {
            "value": "auto",
            "label": "自动选择",
            "backend": "auto",
            "frameworks": list(environments),
        }
    ]
    for backend in ("cuda", "rocm", "directml"):
        supported = [
            framework
            for framework, runtime in frameworks.items()
            if backend in runtime.get("backends", [])
        ]
        if not supported:
            continue
        names = []
        for framework in supported:
            for item in frameworks[framework].get("devices", []):
                if item.get("backend") == backend and item.get("name") not in names:
                    names.append(str(item.get("name")))
        options.append(
            {
                "value": backend,
                "label": labels[backend],
                "backend": backend,
                "name": names[0] if names else labels[backend],
                "frameworks": supported,
            }
        )
    options.append(
        {
            "value": "cpu",
            "label": "CPU",
            "backend": "cpu",
            "frameworks": list(environments),
        }
    )
    preferred = next(
        (
            backend
            for backend in ("cuda", "rocm", "directml")
            if any(runtime.get("preferred") == backend for runtime in frameworks.values())
        ),
        "cpu",
    )
    return {"preferred": preferred, "options": options, "frameworks": frameworks}


def environment_device_label(python: Optional[Path], environment_name: str) -> str:
    runtime = probe_python_environment(python)
    backend = str(runtime.get("preferred") or "cpu")
    names = [
        str(item.get("name"))
        for item in runtime.get("devices", [])
        if item.get("backend") == backend and item.get("name")
    ]
    labels = {"cuda": "CUDA", "rocm": "ROCm", "directml": "DirectML", "cpu": "CPU"}
    suffix = f" · {names[0]}" if names else ""
    return f"{labels.get(backend, backend)}{suffix} ({environment_name})"


def _main() -> int:
    if "--probe" not in sys.argv:
        return 2
    print(DEVICE_PROBE_MARKER + json.dumps(runtime_probe(), ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
