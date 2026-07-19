from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure import rvc_worker
from infrastructure import rvc_engine


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
