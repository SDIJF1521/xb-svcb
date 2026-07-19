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
_PERSISTENT_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60
_probe_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_probe_lock = threading.Lock()
_persistent_probe_path: Optional[Path] = None
_persistent_probe_entries: dict[str, dict[str, Any]] = {}
_persistent_probe_consumed: set[str] = set()


def _subprocess_no_window() -> dict[str, Any]:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        "startupinfo": startupinfo,
    }


def _environment_signature(python: Path) -> str:
    try:
        resolved = python.resolve()
        root = resolved.parent.parent
        parts = [str(resolved)]
        for marker in (resolved, root / "pyvenv.cfg", root / "Lib" / "site-packages"):
            if marker.exists():
                stat = marker.stat()
                parts.append(f"{marker.name}:{stat.st_size}:{stat.st_mtime_ns}")
        site_packages = root / "Lib" / "site-packages"
        if site_packages.exists():
            package_markers = []
            for pattern in ("torch*.dist-info", "onnxruntime*.dist-info"):
                package_markers.extend(site_packages.glob(pattern))
            for marker in sorted(package_markers, key=lambda item: item.name.lower()):
                stat = marker.stat()
                parts.append(f"{marker.name}:{stat.st_mtime_ns}")
        return "|".join(parts)
    except OSError:
        return ""


def _configure_persistent_probe_cache(path: Path) -> None:
    global _persistent_probe_path, _persistent_probe_entries
    resolved = path.resolve()
    with _probe_lock:
        if _persistent_probe_path == resolved:
            return
        _persistent_probe_path = resolved
        _persistent_probe_entries = {}
        _persistent_probe_consumed.clear()
        try:
            data = json.loads(resolved.read_text(encoding="utf-8"))
            if data.get("version") == 1 and isinstance(data.get("entries"), dict):
                _persistent_probe_entries = dict(data["entries"])
        except (OSError, ValueError, AttributeError):
            pass


def _persistent_probe_result(key: str, signature: str) -> Optional[dict[str, Any]]:
    with _probe_lock:
        if key in _persistent_probe_consumed:
            return None
        _persistent_probe_consumed.add(key)
        entry = _persistent_probe_entries.get(key)
        if not isinstance(entry, dict) or entry.get("signature") != signature:
            return None
        created = float(entry.get("created") or 0)
        payload = entry.get("payload")
        if time.time() - created > _PERSISTENT_CACHE_MAX_AGE_SECONDS:
            return None
        return dict(payload) if isinstance(payload, dict) and payload.get("ok") else None


def _store_persistent_probe_result(
    key: str, signature: str, payload: dict[str, Any]
) -> None:
    if not payload.get("ok"):
        return
    with _probe_lock:
        path = _persistent_probe_path
        if path is None:
            return
        _persistent_probe_entries[key] = {
            "signature": signature,
            "created": time.time(),
            "payload": dict(payload),
        }
        data = {"version": 1, "entries": _persistent_probe_entries}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = path.with_suffix(path.suffix + ".tmp")
            temp_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            temp_path.replace(path)
        except OSError:
            pass


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
    """Patch unsupported DirectML audio operators while models stay on GPU.

    DirectML 0.2.5 terminates the process when a ComplexFloat tensor is created
    on the private backend. Voice models only need the real/imaginary views or
    the reconstructed waveform, so the complex intermediate can safely remain
    on CPU while the neural network stays on the GPU. DirectML also rejects a
    single padding operation that mixes cropping (negative values) and padding
    (positive values), so that case is split into an equivalent slice followed
    by a non-negative padding operation on the same DirectML device.
    """
    if getattr(torch, "_xb_directml_audio_patch", False):
        return

    original_stft = torch.stft
    original_istft = torch.istft
    original_complex = torch.complex
    original_view_as_real = torch.view_as_real
    fft_module = getattr(torch, "fft", None)
    original_fft = getattr(fft_module, "fft", None)
    original_rfft = getattr(fft_module, "rfft", None)
    original_irfft = getattr(fft_module, "irfft", None)
    original_pad = torch.nn.functional.pad
    original_interpolate = torch.nn.functional.interpolate

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

    def complex_fft_compat(operation: Any, input_tensor: Any, *args: Any, **kwargs: Any) -> Any:
        if not _is_directml_tensor(input_tensor):
            return operation(input_tensor, *args, **kwargs)
        target = input_tensor.device
        result = operation(
            input_tensor.cpu(),
            *cpu_args(args),
            **cpu_kwargs(kwargs),
        )
        if getattr(result, "is_complex", lambda: False)():
            return _DirectMLComplexTensor(result, target)
        return result.to(target)

    def fft_compat(input_tensor: Any, *args: Any, **kwargs: Any) -> Any:
        return complex_fft_compat(original_fft, input_tensor, *args, **kwargs)

    def rfft_compat(input_tensor: Any, *args: Any, **kwargs: Any) -> Any:
        return complex_fft_compat(original_rfft, input_tensor, *args, **kwargs)

    def irfft_compat(input_tensor: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(input_tensor, _DirectMLComplexTensor):
            result = original_irfft(
                input_tensor.tensor,
                *cpu_args(args),
                **cpu_kwargs(kwargs),
            )
            return result.to(input_tensor.target_device)
        return original_irfft(input_tensor, *args, **kwargs)

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

    def pad_compat(
        input_tensor: Any,
        pad: Any,
        mode: str = "constant",
        value: Any = None,
    ) -> Any:
        padding = tuple(int(item) for item in pad)
        if not (
            _is_directml_tensor(input_tensor)
            and any(item < 0 for item in padding)
            and any(item > 0 for item in padding)
        ):
            return original_pad(input_tensor, padding, mode, value)

        # F.pad orders pairs from the last dimension backwards. Negative values
        # crop that edge; perform those crops explicitly before applying only
        # non-negative padding. This preserves the upstream padDiff/NSF result.
        slices = [slice(None)] * input_tensor.dim()
        for pair_index in range(len(padding) // 2):
            left = padding[pair_index * 2]
            right = padding[pair_index * 2 + 1]
            dimension = input_tensor.dim() - pair_index - 1
            start = max(-left, 0)
            stop = input_tensor.size(dimension) - max(-right, 0)
            slices[dimension] = slice(start, max(start, stop))
        cropped = input_tensor[tuple(slices)]
        positive_padding = tuple(max(item, 0) for item in padding)
        if not any(positive_padding):
            return cropped
        return original_pad(cropped, positive_padding, mode, value)

    def interpolate_compat(input_tensor: Any, *args: Any, **kwargs: Any) -> Any:
        if (
            _is_directml_tensor(input_tensor)
            and str(getattr(input_tensor, "dtype", "")) == "torch.bool"
        ):
            # DirectML nearest-neighbour interpolation has no Bool kernel. UV
            # masks are numeric 0/1 signals downstream, so fp32 preserves their
            # values and is the dtype the upstream source generators intended.
            input_tensor = input_tensor.float()
        return original_interpolate(input_tensor, *args, **kwargs)

    torch.stft = stft_compat
    torch.view_as_real = view_as_real_compat
    torch.complex = complex_compat
    torch.istft = istft_compat
    if original_fft is not None:
        torch.fft.fft = fft_compat
    if original_rfft is not None:
        torch.fft.rfft = rfft_compat
    if original_irfft is not None:
        torch.fft.irfft = irfft_compat
    torch.nn.functional.pad = pad_compat
    torch.nn.functional.interpolate = interpolate_compat
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
    """Keep unsupported fp16/fp64/autocast paths in DirectML-safe fp32."""
    patch_directml_audio_ops(torch)
    if getattr(torch, "_xb_directml_float32_patch", False):
        return

    original_autocast = torch.autocast
    original_tensor_double = torch.Tensor.double

    def autocast_compat(device_type: str, *args: Any, **kwargs: Any):
        if str(device_type).lower() == "privateuseone":
            return nullcontext()
        return original_autocast(device_type, *args, **kwargs)

    def tensor_double(self: Any, *args: Any, **kwargs: Any) -> Any:
        if _is_directml_tensor(self):
            return self.float()
        return original_tensor_double(self, *args, **kwargs)

    torch.autocast = autocast_compat
    torch.Tensor.double = tensor_double
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


def patch_directml_rmvpe_cpu(rmvpe_module: Any) -> None:
    """Keep RMVPE on CPU while the surrounding model remains on DirectML.

    The upstream RVC/SeedVC RMVPE implementation switches privateuseone to an
    ONNX Runtime DML session. On current Windows AMD stacks that session can
    terminate the process natively immediately after its node-assignment
    warnings, so Python never gets an exception to handle. The PyTorch CPU
    RMVPE path is stable and returns NumPy F0 data that the pipelines already
    move back to their selected accelerator.
    """
    if getattr(rmvpe_module, "_xb_directml_cpu_rmvpe", False):
        return
    original_rmvpe = rmvpe_module.RMVPE

    def cpu_rmvpe(*args: Any, **kwargs: Any) -> Any:
        device = kwargs.get("device")
        if device is None and len(args) >= 3:
            device = args[2]
        if str(device).startswith("privateuseone"):
            if len(args) >= 3:
                args = (*args[:2], "cpu", *args[3:])
            else:
                kwargs["device"] = "cpu"
        return original_rmvpe(*args, **kwargs)

    rmvpe_module.RMVPE = cpu_rmvpe
    rmvpe_module._xb_directml_cpu_rmvpe = True


def patch_directml_checkpoint_load(torch: Any) -> None:
    """Deserialize DirectML checkpoints on CPU before modules move to DML.

    torch-directml 0.2.5 registers a privateuseone deserializer whose device()
    helper expects an integer adapter index. PyTorch passes it a torch.device
    object for map_location=privateuseone, causing a TypeError before the model
    exists. Loading storage on CPU is equivalent and upstream immediately moves
    each initialized module to the selected DirectML device.
    """
    if getattr(torch, "_xb_directml_checkpoint_load_patch", False):
        return
    original_load = torch.load

    def load_compat(*args: Any, **kwargs: Any) -> Any:
        positional = list(args)
        if len(positional) >= 2 and str(positional[1]).startswith("privateuseone"):
            positional[1] = "cpu"
        if str(kwargs.get("map_location", "")).startswith("privateuseone"):
            kwargs["map_location"] = "cpu"
        return original_load(*positional, **kwargs)

    torch.load = load_compat
    torch._xb_directml_checkpoint_load_patch = True


def patch_directml_sovits_rmvpe_cpu(utils_module: Any) -> None:
    """Use CPU RMVPE inside so-vits-svc while keeping its models on DML."""
    if getattr(utils_module, "_xb_directml_cpu_rmvpe", False):
        return
    original_get_f0_predictor = utils_module.get_f0_predictor

    def get_f0_predictor(
        f0_predictor: Any, hop_length: Any, sampling_rate: Any, **kwargs: Any
    ) -> Any:
        if (
            str(f0_predictor).lower() == "rmvpe"
            and str(kwargs.get("device", "")).startswith("privateuseone")
        ):
            kwargs["device"] = "cpu"
        return original_get_f0_predictor(
            f0_predictor, hop_length, sampling_rate, **kwargs
        )

    utils_module.get_f0_predictor = get_f0_predictor
    utils_module._xb_directml_cpu_rmvpe = True


def patch_directml_sovits_f0_coarse(utils_module: Any) -> None:
    """Avoid the legacy uint8 ``< 256`` overflow on DirectML.

    Some torch-directml builds represent the result of ``Tensor.long()`` with
    an unsigned 8-bit kernel for this operation.  The upstream so-vits-svc
    implementation then compares that tensor with ``f0_bin == 256``; converting
    the scalar 256 to uint8 fails before the encoder can run.  Clamping the
    floating-point bins to 1..255 before converting to integer is equivalent for
    valid F0 input and never feeds an out-of-range scalar to the uint8 kernel.
    """
    if getattr(utils_module, "_xb_directml_f0_coarse_patch", False):
        return

    torch = utils_module.torch
    f0_bin = int(utils_module.f0_bin)
    f0_mel_min = float(utils_module.f0_mel_min)
    f0_mel_max = float(utils_module.f0_mel_max)

    def f0_to_coarse(f0: Any) -> Any:
        f0_mel = 1127 * (1 + f0 / 700).log()
        scale = (f0_bin - 2) / (f0_mel_max - f0_mel_min)
        offset = f0_mel_min * scale - 1.0
        f0_mel = torch.where(
            f0_mel > 0,
            f0_mel * scale - offset,
            f0_mel,
        )
        return torch.clamp(torch.round(f0_mel), min=1, max=f0_bin - 1).long()

    utils_module.f0_to_coarse = f0_to_coarse
    utils_module._xb_directml_f0_coarse_patch = True


def patch_directml_seedvc_f0_coarse(
    length_regulator_module: Any,
    target_device: Any = None,
) -> None:
    """Keep SeedVC's F0 binning away from integer scalar overflows on DML.

    SeedVC carries the same legacy binning expression as so-vits-svc, but its
    length regulator uses 512 bins and performs one final ``clamp(...).long()``
    after calling ``f0_to_coarse``. DirectML can fail on that integer conversion,
    so keep binning and the small F0 embedding lookup on CPU and return only the
    resulting floating-point embedding to the model device.
    """
    if getattr(length_regulator_module, "_xb_directml_f0_coarse_patch", False):
        return

    torch = length_regulator_module.torch
    f0_mel_min = float(length_regulator_module.f0_mel_min)
    f0_mel_max = float(length_regulator_module.f0_mel_max)

    def f0_to_coarse(f0: Any, f0_bin: Any) -> Any:
        bin_count = int(f0_bin)
        directml_target = (
            target_device
            if str(target_device or "").startswith("privateuseone")
            else None
        )
        stable_f0 = f0.cpu() if directml_target is not None else f0
        f0_mel = 1127 * (1 + stable_f0 / 700).log()
        scale = (bin_count - 2) / (f0_mel_max - f0_mel_min)
        offset = f0_mel_min * scale - 1.0
        f0_mel = torch.where(
            f0_mel > 0,
            f0_mel * scale - offset,
            f0_mel,
        )
        return torch.clamp(torch.round(f0_mel), min=1, max=bin_count - 1)

    original_regulator_init = length_regulator_module.InterpolateRegulator.__init__

    def regulator_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_regulator_init(self, *args, **kwargs)
        embedding = getattr(self, "f0_embedding", None)
        if embedding is None or getattr(embedding, "_xb_directml_cpu_lookup", False):
            return
        original_embedding_forward = embedding.forward

        def f0_embedding_forward(indices: Any) -> Any:
            weight = embedding.weight
            if not str(getattr(weight, "device", "")).startswith("privateuseone"):
                return original_embedding_forward(indices)
            device = weight.device
            result = torch.nn.functional.embedding(
                indices.cpu(),
                weight.cpu(),
                embedding.padding_idx,
                embedding.max_norm,
                embedding.norm_type,
                embedding.scale_grad_by_freq,
                embedding.sparse,
            )
            return result.to(device)

        embedding.forward = f0_embedding_forward
        embedding._xb_directml_cpu_lookup = True

    length_regulator_module.f0_to_coarse = f0_to_coarse
    length_regulator_module.InterpolateRegulator.__init__ = regulator_init
    length_regulator_module._xb_directml_f0_coarse_patch = True


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
    signature = _environment_signature(python)
    now = time.monotonic()
    with _probe_lock:
        cached = _probe_cache.get(key)
        if cached and now - cached[0] < _PROBE_TTL_SECONDS:
            return dict(cached[1])
    persistent = _persistent_probe_result(key, signature)
    if persistent is not None:
        with _probe_lock:
            _probe_cache[key] = (now, dict(persistent))
        return persistent
    try:
        proc = subprocess.run(
            [str(python), str(Path(__file__).resolve()), "--probe"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            **_subprocess_no_window(),
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
    _store_persistent_probe_result(key, signature, payload)
    return payload


def inference_device_capabilities() -> dict[str, Any]:
    import config

    _configure_persistent_probe_cache(config.DATA_DIR / "inference_devices.json")
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

    # DDSP's full DirectML graph can complete without an exception yet produce
    # electrical noise / near-silence. Do not advertise that backend as usable
    # until an end-to-end numerical validation exists; the isolated environment
    # still exposes a stable CPU path on AMD systems.
    ddsp_runtime = frameworks.get("ddsp-svc")
    if isinstance(ddsp_runtime, dict) and "directml" in ddsp_runtime.get("backends", []):
        ddsp_runtime = dict(ddsp_runtime)
        ddsp_runtime["backends"] = [
            backend for backend in ddsp_runtime.get("backends", []) if backend != "directml"
        ]
        if "cpu" not in ddsp_runtime["backends"]:
            ddsp_runtime["backends"].append("cpu")
        ddsp_runtime["devices"] = [
            device
            for device in ddsp_runtime.get("devices", [])
            if device.get("backend") != "directml"
        ]
        if ddsp_runtime.get("preferred") == "directml":
            ddsp_runtime["preferred"] = "cpu"
        ddsp_runtime["note"] = "AMD 环境使用 CPU 稳定路径，避免 DDSP DirectML 电流杂音"
        frameworks["ddsp-svc"] = ddsp_runtime

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


def runtime_device_label(runtime: dict[str, Any], environment_name: str) -> str:
    backend = str(runtime.get("preferred") or "cpu")
    names = [
        str(item.get("name"))
        for item in runtime.get("devices", [])
        if item.get("backend") == backend and item.get("name")
    ]
    labels = {"cuda": "CUDA", "rocm": "ROCm", "directml": "DirectML", "cpu": "CPU"}
    suffix = f" · {names[0]}" if names else ""
    environment = f" ({environment_name})" if environment_name else ""
    return f"{labels.get(backend, backend)}{suffix}{environment}"


def environment_device_label(python: Optional[Path], environment_name: str) -> str:
    return runtime_device_label(probe_python_environment(python), environment_name)


def _main() -> int:
    if "--probe" not in sys.argv:
        return 2
    print(DEVICE_PROBE_MARKER + json.dumps(runtime_probe(), ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
