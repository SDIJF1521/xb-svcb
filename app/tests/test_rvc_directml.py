from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure import rvc_worker
from infrastructure import rvc_engine
from domain import InferenceParams


def test_directml_crepe_checkpoint_is_deserialized_on_cpu() -> None:
    calls: list[tuple[tuple, dict]] = []

    class DirectMlDevice:
        def __str__(self) -> str:
            return "privateuseone:0"

    def load(*args, **kwargs):
        calls.append((args, kwargs))
        return "crepe-state"

    torch = SimpleNamespace(load=load)
    rvc_worker._configure_rvc_torch_load(torch, directml=True)

    assert (
        torch.load("torchcrepe/assets/full.pth", map_location=DirectMlDevice(), weights_only=True)
        == "crepe-state"
    )
    assert calls[-1][1]["map_location"] == "cpu"
    assert calls[-1][1]["weights_only"] is True


def test_rvc_torch_load_keeps_non_directml_location_and_legacy_default() -> None:
    calls: list[tuple[tuple, dict]] = []

    def load(*args, **kwargs):
        calls.append((args, kwargs))

    torch = SimpleNamespace(load=load)
    rvc_worker._configure_rvc_torch_load(torch, directml=False)
    torch.load("model.pth", map_location="cuda:0")

    assert calls[-1][1]["map_location"] == "cuda:0"
    assert calls[-1][1]["weights_only"] is False


def test_rvc_prepares_pytorch_models_and_keeps_onnx_optional(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    downloaded: list[str] = []

    monkeypatch.setattr(rvc_worker, "_copy_bundled_base_model", lambda *_a, **_k: False)
    monkeypatch.setattr(
        rvc_worker,
        "_download_base_model",
        lambda name, _dest: downloaded.append(name) or True,
    )

    rvc_worker._prepare_rvc_base_models(str(tmp_path))

    assert downloaded == ["hubert_base.pt", "rmvpe.pt"]


def test_directml_rmvpe_is_forced_to_cpu() -> None:
    calls: list[tuple[tuple, dict]] = []

    def original(*args, **kwargs):
        calls.append((args, kwargs))
        return "rmvpe"

    module = SimpleNamespace(RMVPE=original)
    rvc_worker.patch_directml_rmvpe_cpu(module)

    assert module.RMVPE("model.pt", False, "privateuseone:0") == "rmvpe"
    assert calls[-1][0][2] == "cpu"

    module.RMVPE("model.pt", False, device="privateuseone:1")
    assert calls[-1][1]["device"] == "cpu"


def test_rmvpe_cpu_patch_keeps_cuda_unchanged() -> None:
    calls: list[tuple[tuple, dict]] = []

    def original(*args, **kwargs):
        calls.append((args, kwargs))

    module = SimpleNamespace(RMVPE=original)
    rvc_worker.patch_directml_rmvpe_cpu(module)
    module.RMVPE("model.pt", False, device="cuda:0")

    assert calls[-1][1]["device"] == "cuda:0"


def test_rvc_device_report_exposes_selected_backend_and_model_devices() -> None:
    class Parameter:
        device = "cuda:0"

    class Module:
        def parameters(self):
            return iter((Parameter(),))

    rvc = SimpleNamespace(
        config=SimpleNamespace(device="cuda:0"),
        vc=SimpleNamespace(
            net_g=Module(),
            hubert_model=Module(),
            pipeline=SimpleNamespace(model_rmvpe=SimpleNamespace(model=Module())),
        ),
    )
    resolved = SimpleNamespace(
        backend="rocm",
        device="cuda:0",
        name="AMD Radeon",
    )
    torch_module = SimpleNamespace(
        __version__="2.13.0+rocm10.0.0",
        cuda=SimpleNamespace(is_available=lambda: True),
    )

    report = rvc_worker._rvc_device_report(rvc, resolved, torch_module)

    assert "backend=rocm" in report
    assert "target=cuda:0" in report
    assert "net_g=cuda:0" in report
    assert "hubert=cuda:0" in report
    assert "rmvpe=cuda:0" in report


def test_rocm_keeps_fp16_unless_explicitly_overridden() -> None:
    assert not rvc_worker._should_force_fp32("rocm", (2, 13))
    assert rvc_worker._should_force_fp32("rocm", (2, 13), rocm_fp32=True)
    assert rvc_worker._should_force_fp32("cuda", (2, 6))
    assert rvc_worker._should_force_fp32("directml", (2, 4))
    assert rvc_worker._should_force_fp32("cpu", (2, 13))


def test_rocm_uses_fast_miopen_search_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MIOPEN_FIND_MODE", raising=False)
    resolved = SimpleNamespace(backend="rocm")
    torch_module = SimpleNamespace()

    rvc_worker._configure_rocm_runtime(torch_module, resolved)

    assert os.environ["MIOPEN_FIND_MODE"] == "FAST"


def test_rocm_miopen_search_mode_remains_user_overridable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MIOPEN_FIND_MODE", "HYBRID")
    resolved = SimpleNamespace(backend="rocm")

    rvc_worker._configure_rocm_runtime(SimpleNamespace(), resolved)

    assert os.environ["MIOPEN_FIND_MODE"] == "HYBRID"


def test_faiss_runtime_uses_bounded_parallel_search_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("XB_RVC_FAISS_THREADS", raising=False)
    calls: list[int] = []
    faiss_module = SimpleNamespace(
        omp_set_num_threads=lambda value: calls.append(value),
    )

    threads = rvc_worker._configure_faiss_runtime(faiss_module)

    expected = max(1, min(8, (os.cpu_count() or 1) // 2))
    assert threads == expected
    assert calls == [expected]


def test_rvc_worker_env_disables_nested_blas_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "20")
    monkeypatch.delenv("XB_RVC_BLAS_THREADS", raising=False)

    env = rvc_engine.RvcEngine._worker_env()

    assert env["OPENBLAS_NUM_THREADS"] == "1"
    assert env["MKL_NUM_THREADS"] == "1"
    assert env["NUMEXPR_NUM_THREADS"] == "1"
    assert env["VECLIB_MAXIMUM_THREADS"] == "1"


def test_rvc_worker_env_allows_explicit_blas_thread_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XB_RVC_BLAS_THREADS", "2")

    env = rvc_engine.RvcEngine._worker_env()

    assert env["OPENBLAS_NUM_THREADS"] == "2"


def test_directml_request_selects_independent_runtime(monkeypatch, tmp_path: Path) -> None:
    rocm = tmp_path / "rocm-python.exe"
    directml = tmp_path / "directml-python.exe"
    rocm.touch()
    directml.touch()
    monkeypatch.setattr(rvc_engine.config, "RVC_PYTHON", rocm)
    monkeypatch.setattr(rvc_engine.config, "RVC_DIRECTML_PYTHON", directml)

    engine = rvc_engine.RvcEngine()

    assert engine._python_for_device("rocm") == rocm
    assert engine._python_for_device("auto") == rocm
    assert engine._python_for_device("directml") == directml


def test_directml_rvc_uses_shorter_windows_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "XB_RVC_DIRECTML_X_PAD",
        "XB_RVC_DIRECTML_X_QUERY",
        "XB_RVC_DIRECTML_X_CENTER",
        "XB_RVC_DIRECTML_X_MAX",
    ):
        monkeypatch.delenv(name, raising=False)
    rvc = SimpleNamespace(config=SimpleNamespace())

    result = rvc_worker._apply_rvc_directml_memory_profile(rvc)

    assert result == (1, 3, 12, 14)
    assert rvc.config.x_pad == 1
    assert rvc.config.x_query == 3
    assert rvc.config.x_center == 12
    assert rvc.config.x_max == 14


def test_directml_rvc_thread_limits_default_to_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "XB_RVC_DIRECTML_THREADS",
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        monkeypatch.delenv(name, raising=False)
    calls: list[tuple[str, int]] = []
    torch_module = SimpleNamespace(
        set_num_threads=lambda value: calls.append(("threads", value)),
        set_num_interop_threads=lambda value: calls.append(("interop", value)),
    )

    threads = rvc_worker._apply_rvc_directml_thread_limits(torch_module)

    assert threads == 1
    assert calls == [("threads", 1), ("interop", 1)]
    assert os.environ["OPENBLAS_NUM_THREADS"] == "1"


def test_rvc_native_failure_reports_and_logs_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "converted.wav"
    log = tmp_path / "task.log"
    completed = SimpleNamespace(
        returncode=-1073741819,
        stdout="",
        stderr="onnxruntime node assignment warning",
    )
    monkeypatch.setattr(rvc_engine.config, "RVC_PYTHON", tmp_path / "python.exe")
    monkeypatch.setattr(rvc_engine.config, "RVC_DIRECTML_PYTHON", tmp_path / "directml-python.exe")
    monkeypatch.setattr(rvc_engine.config, "RVC_WORKER", tmp_path / "rvc_worker.py")
    monkeypatch.setattr(rvc_engine.config, "subprocess_no_window", lambda: {})
    monkeypatch.setattr(rvc_engine.subprocess, "run", lambda *_a, **_k: completed)
    params = SimpleNamespace(
        device="directml",
        f0_method="rmvpe",
        pitch=0,
        index_rate=0.75,
        rms_mix=0.25,
        protect=0.33,
        filter_radius=3,
        rvc_version="v2",
    )

    with pytest.raises(RuntimeError, match="-1073741819"):
        rvc_engine.RvcEngine()._run_worker(
            "model.pth", "", tmp_path / "input.wav", output, params, log
        )

    assert "子进程退出码" in log.read_text(encoding="utf-8")
    assert "-1073741819" in log.read_text(encoding="utf-8")


def test_rvc_miopen_timer_failure_has_actionable_error() -> None:
    message = rvc_engine.RvcEngine._error_tail(
        "warning: xnack 'Off' was requested",
        "MIOpen: Error [EvaluateInvokers] Invalid elapsed time detected",
    )

    assert "ROCm/MIOpen" in message
    assert "FAST" in message


def test_realtime_rvc_session_passes_custom_parameters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    python = tmp_path / "python.exe"
    worker = tmp_path / "rvc_worker.py"
    model = tmp_path / "voice.pth"
    index = tmp_path / "voice.index"
    for path in (python, worker, model, index):
        path.write_bytes(b"test")
    captured: dict = {}

    class Session:
        def __init__(self, command, **kwargs):  # noqa: ANN001
            captured["command"] = command
            captured["kwargs"] = kwargs

    monkeypatch.setattr(rvc_engine.config, "RVC_PYTHON", python)
    monkeypatch.setattr(rvc_engine.config, "RVC_WORKER", worker)
    monkeypatch.setattr(rvc_engine.config, "rvc_engine_ready", lambda: True)
    monkeypatch.setattr(rvc_engine, "PersistentInferenceSession", Session)

    params = InferenceParams.from_dict(
        {
            "device": "cpu",
            "f0_method": "harvest",
            "pitch": -5,
            "index_rate": 0.42,
            "rms_mix": 0.61,
            "protect": 0.18,
            "filter_radius": 5,
            "rvc_version": "v1",
        }
    )
    rvc_engine.RvcEngine().open_realtime_session(
        {"main_model_path": str(model), "index_path": str(index)},
        params,
    )

    command = captured["command"]
    assert command[command.index("--device") + 1] == "cpu"
    assert command[command.index("--method") + 1] == "harvest"
    assert command[command.index("--pitch") + 1] == "-5"
    assert command[command.index("--index-rate") + 1] == "0.42"
    assert command[command.index("--rms-mix") + 1] == "0.61"
    assert command[command.index("--protect") + 1] == "0.18"
    assert command[command.index("--filter-radius") + 1] == "5"
    assert command[command.index("--version") + 1] == "v1"
    assert command[command.index("--index") + 1] == str(index)
