from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from domain import InferenceParams
from infrastructure.ddsp_engine import DdspSvcEngine
from infrastructure.rvc_engine import RvcEngine
from infrastructure.seedvc_engine import SeedVcEngine
from infrastructure.svc_engine import SvcEngine
from infrastructure.svc_worker import (
    _diffusion_k_step_limit,
    _resolve_diffusion_k_step,
    _upstream_svc_device,
)


def test_sovits_cuda_auto_preserves_v021_native_device_selection() -> None:
    cuda = SimpleNamespace(backend="cuda", device="cuda:0")
    assert _upstream_svc_device("auto", cuda) is None
    assert _upstream_svc_device("", cuda) is None
    assert _upstream_svc_device("cuda", cuda) == "cuda:0"


def test_sovits_directml_auto_receives_explicit_private_device() -> None:
    directml = SimpleNamespace(backend="directml", device="privateuseone:1")
    assert _upstream_svc_device("auto", directml) == "privateuseone:1"


def test_sovits_nonzero_diffusion_k_step_max_caps_inference_depth() -> None:
    svc = SimpleNamespace(
        diffusion_model=SimpleNamespace(k_step_max=80),
        diffusion_args=SimpleNamespace(
            model=SimpleNamespace(k_step_max=80, timesteps=1000)
        ),
    )

    assert _diffusion_k_step_limit(svc) == 80
    assert _resolve_diffusion_k_step(svc, 200) == (80, 80)
    assert _resolve_diffusion_k_step(svc, 40) == (40, 80)
    assert _resolve_diffusion_k_step(svc, 200, 0.5) == (40, 80)
    assert _resolve_diffusion_k_step(svc, 200, 1.0) == (80, 80)


def test_sovits_zero_diffusion_k_step_max_uses_all_trained_timesteps() -> None:
    svc = SimpleNamespace(
        diffusion_model=SimpleNamespace(),
        diffusion_args=SimpleNamespace(
            model=SimpleNamespace(k_step_max=0, timesteps=1000)
        ),
    )

    assert _diffusion_k_step_limit(svc) == 1000
    assert _resolve_diffusion_k_step(svc, 200) == (200, 1000)
    assert _resolve_diffusion_k_step(svc, 100, 0.5) == (100, 1000)


def test_sovits_loaded_diffusion_limit_takes_precedence_over_stale_config() -> None:
    svc = SimpleNamespace(
        diffusion_model=SimpleNamespace(
            k_step_max=120, decoder=SimpleNamespace(k_step=120)
        ),
        diffusion_args=SimpleNamespace(
            model=SimpleNamespace(k_step_max=0, timesteps=1000)
        ),
    )

    assert _resolve_diffusion_k_step(svc, 160) == (120, 120)


def test_sovits_fork_k_step_config_is_supported() -> None:
    svc = SimpleNamespace(
        diffusion_model=SimpleNamespace(decoder=SimpleNamespace(k_step=300)),
        diffusion_args=SimpleNamespace(
            model=SimpleNamespace(k_step=300, timesteps=1000)
        ),
    )

    assert _diffusion_k_step_limit(svc) == 300
    assert _resolve_diffusion_k_step(svc, 200, 1.0) == (300, 300)


@pytest.mark.parametrize(
    ("engine", "model", "params", "message"),
    [
        (
            SvcEngine(),
            {"main_model_path": "missing.pth", "main_config_path": "missing.json"},
            InferenceParams(),
            "主模型不存在",
        ),
        (
            RvcEngine(),
            {"main_model_path": "missing.pth"},
            InferenceParams(),
            "RVC 模型不存在",
        ),
        (
            SeedVcEngine(),
            {"main_model_path": "missing.pth", "main_config_path": "missing.yml"},
            InferenceParams(reference_audio="missing.wav"),
            "SeedVC 模型不存在",
        ),
        (
            DdspSvcEngine(),
            {"main_model_path": "missing.pt", "main_config_path": "missing.yaml"},
            InferenceParams(),
            "DDSP-SVC 模型不存在",
        ),
    ],
)
def test_missing_real_model_never_generates_single_tone_placeholder(
    tmp_path: Path, engine, model: dict, params: InferenceParams, message: str
) -> None:
    vocals = tmp_path / "vocals.wav"
    vocals.write_bytes(b"wave")
    output = tmp_path / "converted.wav"

    with patch.object(type(engine), "available", new_callable=lambda: property(lambda _self: True)):
        with pytest.raises(RuntimeError, match=message):
            engine.infer(model, vocals, output, params, 136.0)

    assert not output.exists()
