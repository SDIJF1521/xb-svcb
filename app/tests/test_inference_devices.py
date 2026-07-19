from __future__ import annotations

import importlib.util
import json
import subprocess
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


def test_directml_checkpoint_load_maps_storage_to_cpu() -> None:
    calls: list[tuple[tuple, dict]] = []

    def load(*args, **kwargs):
        calls.append((args, kwargs))
        return "checkpoint"

    torch = SimpleNamespace(load=load)
    inference_device.patch_directml_checkpoint_load(torch)

    assert torch.load("model.pt", map_location="privateuseone:0") == "checkpoint"
    assert calls[-1][1]["map_location"] == "cpu"

    torch.load("model.pt", "privateuseone:1")
    assert calls[-1][0][1] == "cpu"


def test_checkpoint_load_patch_keeps_cuda_unchanged() -> None:
    calls: list[tuple[tuple, dict]] = []

    def load(*args, **kwargs):
        calls.append((args, kwargs))

    torch = SimpleNamespace(load=load)
    inference_device.patch_directml_checkpoint_load(torch)
    torch.load("model.pt", map_location="cuda:0")

    assert calls[-1][1]["map_location"] == "cuda:0"


@pytest.mark.parametrize(
    "padding",
    [
        (0, 0, -1, 1),
        (0, 0, 1, -1),
        (-2, 1),
        (2, -1),
    ],
)
def test_directml_mixed_padding_matches_pytorch(padding: tuple[int, ...], monkeypatch) -> None:
    torch = pytest.importorskip("torch")
    original_pad = torch.nn.functional.pad
    fake_functional = SimpleNamespace(
        pad=original_pad,
        interpolate=torch.nn.functional.interpolate,
    )
    fake_torch = SimpleNamespace(
        stft=torch.stft,
        istft=torch.istft,
        complex=torch.complex,
        view_as_real=torch.view_as_real,
        nn=SimpleNamespace(functional=fake_functional),
    )
    tensor = torch.arange(30, dtype=torch.float32).reshape(1, 5, 6)
    expected = original_pad(tensor, padding, "constant", 0)

    inference_device.patch_directml_audio_ops(fake_torch)
    monkeypatch.setattr(inference_device, "_is_directml_tensor", lambda value: True)
    actual = fake_torch.nn.functional.pad(tensor, padding, "constant", 0)

    assert torch.equal(actual, expected)


def test_non_directml_mixed_padding_uses_original_operation(monkeypatch) -> None:
    torch = pytest.importorskip("torch")
    calls: list[tuple] = []

    def original_pad(input_tensor, pad, mode="constant", value=None):
        calls.append((input_tensor, pad, mode, value))
        return "original"

    fake_torch = SimpleNamespace(
        stft=torch.stft,
        istft=torch.istft,
        complex=torch.complex,
        view_as_real=torch.view_as_real,
        nn=SimpleNamespace(
            functional=SimpleNamespace(
                pad=original_pad,
                interpolate=torch.nn.functional.interpolate,
            )
        ),
    )
    inference_device.patch_directml_audio_ops(fake_torch)
    monkeypatch.setattr(inference_device, "_is_directml_tensor", lambda value: False)

    tensor = torch.ones(1, 3, 2)
    assert fake_torch.nn.functional.pad(tensor, (0, 0, -1, 1)) == "original"
    assert calls == [(tensor, (0, 0, -1, 1), "constant", None)]


def test_directml_bool_nearest_interpolation_uses_float32(monkeypatch) -> None:
    torch = pytest.importorskip("torch")
    original_interpolate = torch.nn.functional.interpolate
    fake_functional = SimpleNamespace(
        pad=torch.nn.functional.pad,
        interpolate=original_interpolate,
    )
    fake_torch = SimpleNamespace(
        stft=torch.stft,
        istft=torch.istft,
        complex=torch.complex,
        view_as_real=torch.view_as_real,
        nn=SimpleNamespace(functional=fake_functional),
    )
    uv = torch.tensor([[[False, True, True, False]]])
    expected = original_interpolate(uv.float(), scale_factor=3, mode="nearest")

    inference_device.patch_directml_audio_ops(fake_torch)
    monkeypatch.setattr(inference_device, "_is_directml_tensor", lambda value: True)
    actual = fake_torch.nn.functional.interpolate(
        uv,
        scale_factor=3,
        mode="nearest",
    )

    assert actual.dtype == torch.float32
    assert torch.equal(actual, expected)


def test_directml_rfft_keeps_complex_intermediate_on_cpu(monkeypatch) -> None:
    torch = pytest.importorskip("torch")
    calls: list[object] = []
    original_rfft = torch.fft.rfft

    def rfft(input_tensor, *args, **kwargs):
        calls.append(input_tensor.device)
        return original_rfft(input_tensor, *args, **kwargs)

    fake_torch = SimpleNamespace(
        stft=torch.stft,
        istft=torch.istft,
        complex=torch.complex,
        view_as_real=torch.view_as_real,
        fft=SimpleNamespace(
            fft=torch.fft.fft,
            rfft=rfft,
            irfft=torch.fft.irfft,
        ),
        nn=SimpleNamespace(
            functional=SimpleNamespace(
                pad=torch.nn.functional.pad,
                interpolate=torch.nn.functional.interpolate,
            )
        ),
    )
    waveform = torch.tensor([[0.0, 1.0, 0.0, -1.0]], dtype=torch.float32)
    expected = original_rfft(waveform).abs()

    inference_device.patch_directml_audio_ops(fake_torch)
    monkeypatch.setattr(
        inference_device,
        "_is_directml_tensor",
        lambda value: value is waveform,
    )
    spectrum = fake_torch.fft.rfft(waveform)

    assert isinstance(spectrum, inference_device._DirectMLComplexTensor)
    assert calls == [torch.device("cpu")]
    assert torch.allclose(spectrum.abs(), expected)


def test_non_directml_rfft_uses_original_operation(monkeypatch) -> None:
    torch = pytest.importorskip("torch")
    calls: list[object] = []
    original_rfft = torch.fft.rfft

    def rfft(input_tensor, *args, **kwargs):
        calls.append(input_tensor)
        return original_rfft(input_tensor, *args, **kwargs)

    fake_torch = SimpleNamespace(
        stft=torch.stft,
        istft=torch.istft,
        complex=torch.complex,
        view_as_real=torch.view_as_real,
        fft=SimpleNamespace(
            fft=torch.fft.fft,
            rfft=rfft,
            irfft=torch.fft.irfft,
        ),
        nn=SimpleNamespace(
            functional=SimpleNamespace(
                pad=torch.nn.functional.pad,
                interpolate=torch.nn.functional.interpolate,
            )
        ),
    )
    waveform = torch.arange(8, dtype=torch.float32)

    inference_device.patch_directml_audio_ops(fake_torch)
    monkeypatch.setattr(inference_device, "_is_directml_tensor", lambda value: False)
    actual = fake_torch.fft.rfft(waveform)

    assert calls == [waveform]
    assert torch.equal(actual, original_rfft(waveform))


def test_directml_double_stays_float32_but_other_devices_keep_double(monkeypatch) -> None:
    calls: list[tuple] = []

    class FakeTensor:
        def __init__(self, device: str) -> None:
            self.device = device

        def float(self):
            calls.append(("float", self.device))
            return "float32"

        def double(self, *args, **kwargs):
            calls.append(("double", self.device, args, kwargs))
            return "float64"

    fake_torch = SimpleNamespace(
        Tensor=FakeTensor,
        autocast=lambda *args, **kwargs: (args, kwargs),
    )
    monkeypatch.setattr(inference_device, "patch_directml_audio_ops", lambda torch: None)

    inference_device.patch_directml_float32(fake_torch)

    assert FakeTensor("privateuseone:0").double() == "float32"
    assert FakeTensor("cuda:0").double(non_blocking=True) == "float64"
    assert FakeTensor("cpu").double() == "float64"
    assert calls == [
        ("float", "privateuseone:0"),
        ("double", "cuda:0", (), {"non_blocking": True}),
        ("double", "cpu", (), {}),
    ]


def test_sovits_directml_rmvpe_is_forced_to_cpu() -> None:
    calls: list[tuple[tuple, dict]] = []

    def get_f0_predictor(*args, **kwargs):
        calls.append((args, kwargs))
        return "predictor"

    utils = SimpleNamespace(get_f0_predictor=get_f0_predictor)
    inference_device.patch_directml_sovits_rmvpe_cpu(utils)

    assert (
        utils.get_f0_predictor(
            "rmvpe", 512, 44100, device="privateuseone:0", threshold=0.05
        )
        == "predictor"
    )
    assert calls[-1][1]["device"] == "cpu"

    utils.get_f0_predictor(
        "crepe", 512, 44100, device="privateuseone:0", threshold=0.05
    )
    assert calls[-1][1]["device"] == "privateuseone:0"

    utils.get_f0_predictor(
        "rmvpe", 512, 44100, device="cuda:0", threshold=0.05
    )
    assert calls[-1][1]["device"] == "cuda:0"


def test_sovits_directml_f0_coarse_clamps_before_integer_conversion() -> None:
    torch = pytest.importorskip("torch")
    utils = SimpleNamespace(
        torch=torch,
        f0_bin=256,
        f0_mel_min=1127 * torch.log(torch.tensor(1 + 50 / 700)).item(),
        f0_mel_max=1127 * torch.log(torch.tensor(1 + 1100 / 700)).item(),
        f0_to_coarse=lambda value: value,
    )

    inference_device.patch_directml_sovits_f0_coarse(utils)
    result = utils.f0_to_coarse(torch.tensor([0.0, 50.0, 440.0, 1100.0, 5000.0]))

    assert result.dtype == torch.int64
    assert result.tolist()[0] == 1
    assert min(result.tolist()) >= 1
    assert max(result.tolist()) <= 255
    assert result.tolist()[-1] == 255


def test_sovits_directml_f0_coarse_matches_upstream_for_normal_f0() -> None:
    torch = pytest.importorskip("torch")
    f0_bin = 256
    f0_mel_min = 1127 * torch.log(torch.tensor(1 + 50 / 700)).item()
    f0_mel_max = 1127 * torch.log(torch.tensor(1 + 1100 / 700)).item()
    utils = SimpleNamespace(
        torch=torch,
        f0_bin=f0_bin,
        f0_mel_min=f0_mel_min,
        f0_mel_max=f0_mel_max,
        f0_to_coarse=lambda value: value,
    )
    f0 = torch.tensor([0.0, 50.0, 100.0, 220.0, 440.0, 880.0, 1100.0])
    f0_mel = 1127 * (1 + f0 / 700).log()
    scale = (f0_bin - 2) / (f0_mel_max - f0_mel_min)
    offset = f0_mel_min * scale - 1.0
    f0_mel = torch.where(f0_mel > 0, f0_mel * scale - offset, f0_mel)
    expected = torch.round(f0_mel).long()
    expected = expected * (expected > 0)
    expected = expected + ((expected < 1) * 1)
    expected = expected * (expected < f0_bin)
    expected = expected + ((expected >= f0_bin) * (f0_bin - 1))

    inference_device.patch_directml_sovits_f0_coarse(utils)

    assert torch.equal(utils.f0_to_coarse(f0), expected)


def test_sovits_directml_f0_coarse_patch_is_idempotent() -> None:
    torch = pytest.importorskip("torch")
    utils = SimpleNamespace(
        torch=torch,
        f0_bin=256,
        f0_mel_min=1.0,
        f0_mel_max=2.0,
        f0_to_coarse=lambda value: value,
    )

    inference_device.patch_directml_sovits_f0_coarse(utils)
    patched = utils.f0_to_coarse
    inference_device.patch_directml_sovits_f0_coarse(utils)

    assert utils.f0_to_coarse is patched


def test_seedvc_directml_f0_coarse_stays_float_until_final_conversion() -> None:
    torch = pytest.importorskip("torch")
    length_regulator = SimpleNamespace(
        torch=torch,
        f0_mel_min=1127 * torch.log(torch.tensor(1 + 50 / 700)).item(),
        f0_mel_max=1127 * torch.log(torch.tensor(1 + 1100 / 700)).item(),
        f0_to_coarse=lambda value, bins: value,
        InterpolateRegulator=type("InterpolateRegulator", (), {"__init__": lambda self: None}),
    )

    inference_device.patch_directml_seedvc_f0_coarse(length_regulator)
    coarse = length_regulator.f0_to_coarse(
        torch.tensor([0.0, 50.0, 440.0, 1100.0, 5000.0]),
        512,
    )
    final_indices = coarse.clamp(0, 511).long()

    assert coarse.dtype.is_floating_point
    assert final_indices.dtype == torch.int64
    assert final_indices.tolist()[0] == 1
    assert min(final_indices.tolist()) >= 1
    assert max(final_indices.tolist()) <= 511
    assert final_indices.tolist()[-1] == 511


def test_seedvc_directml_f0_coarse_matches_upstream_for_normal_f0() -> None:
    torch = pytest.importorskip("torch")
    f0_mel_min = 1127 * torch.log(torch.tensor(1 + 50 / 700)).item()
    f0_mel_max = 1127 * torch.log(torch.tensor(1 + 1100 / 700)).item()
    length_regulator = SimpleNamespace(
        torch=torch,
        f0_mel_min=f0_mel_min,
        f0_mel_max=f0_mel_max,
        f0_to_coarse=lambda value, bins: value,
        InterpolateRegulator=type("InterpolateRegulator", (), {"__init__": lambda self: None}),
    )
    f0 = torch.tensor([0.0, 50.0, 100.0, 220.0, 440.0, 880.0, 1100.0])
    f0_bin = 512
    f0_mel = 1127 * (1 + f0 / 700).log()
    scale = (f0_bin - 2) / (f0_mel_max - f0_mel_min)
    offset = f0_mel_min * scale - 1.0
    f0_mel = torch.where(f0_mel > 0, f0_mel * scale - offset, f0_mel)
    expected = torch.round(f0_mel).long()
    expected = expected * (expected > 0)
    expected = expected + ((expected < 1) * 1)
    expected = expected * (expected < f0_bin)
    expected = expected + ((expected >= f0_bin) * (f0_bin - 1))

    inference_device.patch_directml_seedvc_f0_coarse(length_regulator)
    actual = length_regulator.f0_to_coarse(f0, f0_bin).clamp(0, f0_bin - 1).long()

    assert torch.equal(actual, expected)


def test_seedvc_directml_f0_integer_and_embedding_lookup_stay_on_cpu(monkeypatch) -> None:
    torch = pytest.importorskip("torch")
    calls: list[tuple] = []

    class FakeTensor:
        def __init__(self, device: str, label: str) -> None:
            self.device = device
            self.label = label

        def cpu(self):
            calls.append(("cpu", self.label))
            return FakeTensor("cpu", self.label + "-cpu")

        def to(self, device):
            calls.append(("to", self.label, device))
            return FakeTensor(str(device), self.label + "-gpu")

    class Embedding:
        def __init__(self) -> None:
            self.weight = FakeTensor("privateuseone:0", "weight")
            self.padding_idx = None
            self.max_norm = None
            self.norm_type = 2.0
            self.scale_grad_by_freq = False
            self.sparse = False

        def forward(self, indices):
            raise AssertionError("DirectML embedding path must not be called")

    class InterpolateRegulator:
        def __init__(self) -> None:
            self.f0_embedding = Embedding()

    module = SimpleNamespace(
        torch=torch,
        f0_mel_min=1.0,
        f0_mel_max=2.0,
        f0_to_coarse=lambda value, bins: value,
        InterpolateRegulator=InterpolateRegulator,
    )

    def embedding(indices, weight, *args):
        calls.append(("embedding", indices.device, weight.device, args))
        return FakeTensor("cpu", "embedding")

    monkeypatch.setattr(torch.nn.functional, "embedding", embedding)
    inference_device.patch_directml_seedvc_f0_coarse(
        module,
        target_device="privateuseone:0",
    )
    regulator = module.InterpolateRegulator()
    indices = FakeTensor("cpu", "indices")
    result = regulator.f0_embedding.forward(indices)

    assert result.device == "privateuseone:0"
    assert ("embedding", "cpu", "cpu", (None, None, 2.0, False, False)) in calls


def test_installer_detects_amd_as_directml_when_nvidia_is_absent() -> None:
    installer = _load_installer_module()
    completed = SimpleNamespace(stdout="AMD Radeon RX 7900 XTX\n", returncode=0)
    with patch.object(installer, "find_nvidia_smi", return_value=None), patch.object(
        installer.os, "name", "nt"
    ), patch.object(installer.subprocess, "run", return_value=completed):
        assert installer.detect_gpu_stack() == "directml"


def test_environment_probe_hides_windows_console(tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    python.write_bytes(b"placeholder")
    payload = {
        "ok": True,
        "torch_version": "2.5.1",
        "backends": ["cuda", "cpu"],
        "devices": [],
        "preferred": "cuda",
    }
    completed = SimpleNamespace(
        stdout=inference_device.DEVICE_PROBE_MARKER
        + json.dumps(payload)
        + "\n",
        stderr="",
    )

    with patch.object(inference_device.subprocess, "run", return_value=completed) as run:
        inference_device.probe_python_environment(python)

    if inference_device.os.name == "nt":
        assert run.call_args.kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW
        assert run.call_args.kwargs["startupinfo"].wShowWindow == subprocess.SW_HIDE


def test_environment_probe_reuses_persistent_cache(tmp_path: Path) -> None:
    python = tmp_path / "env" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"placeholder")
    cache_path = tmp_path / "data" / "inference_devices.json"
    payload = {
        "ok": True,
        "torch_version": "2.5.1",
        "backends": ["cuda", "cpu"],
        "devices": [{"backend": "cuda", "name": "NVIDIA Test GPU", "index": 0}],
        "preferred": "cuda",
    }
    completed = SimpleNamespace(
        stdout=inference_device.DEVICE_PROBE_MARKER + json.dumps(payload) + "\n",
        stderr="",
    )

    inference_device._configure_persistent_probe_cache(cache_path)
    with patch.object(inference_device.subprocess, "run", return_value=completed) as run:
        assert inference_device.probe_python_environment(python) == payload
    assert run.call_count == 1
    assert cache_path.is_file()

    with inference_device._probe_lock:
        inference_device._probe_cache.clear()
    inference_device._configure_persistent_probe_cache(tmp_path / "new-process.json")
    inference_device._configure_persistent_probe_cache(cache_path)

    with patch.object(
        inference_device.subprocess,
        "run",
        side_effect=AssertionError("persistent cache should avoid a subprocess probe"),
    ):
        assert inference_device.probe_python_environment(python) == payload


def test_ddsp_directml_is_not_advertised_as_usable(monkeypatch) -> None:
    directml = {
        "ok": True,
        "torch_version": "2.4.1",
        "backends": ["directml", "cpu"],
        "devices": [
            {"backend": "directml", "name": "AMD Radeon", "index": 0}
        ],
        "preferred": "directml",
    }
    cpu = {
        "ok": True,
        "torch_version": "2.5.1",
        "backends": ["cpu"],
        "devices": [],
        "preferred": "cpu",
    }
    config = SimpleNamespace(
        DATA_DIR=Path("cache"),
        UVR_PYTHON=Path("uvr.exe"),
        SVC_PYTHON=Path("svc.exe"),
        RVC_PYTHON=Path("rvc.exe"),
        SEEDVC_PYTHON=Path("seed.exe"),
        DDSP_PYTHON=Path("ddsp.exe"),
    )
    monkeypatch.setitem(sys.modules, "config", config)
    monkeypatch.setattr(
        inference_device,
        "probe_python_environment",
        lambda python: directml if str(python).endswith("ddsp.exe") else cpu,
    )
    monkeypatch.setattr(inference_device, "_configure_persistent_probe_cache", lambda path: None)

    capabilities = inference_device.inference_device_capabilities()
    ddsp = capabilities["frameworks"]["ddsp-svc"]

    assert ddsp["backends"] == ["cpu"]
    assert ddsp["preferred"] == "cpu"
    directml_option = next(
        (item for item in capabilities["options"] if item["value"] == "directml"),
        None,
    )
    assert directml_option is None or "ddsp-svc" not in directml_option["frameworks"]
