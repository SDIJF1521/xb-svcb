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
from infrastructure.svc_worker import _upstream_svc_device


def test_sovits_cuda_auto_preserves_v021_native_device_selection() -> None:
    cuda = SimpleNamespace(backend="cuda", device="cuda:0")
    assert _upstream_svc_device("auto", cuda) is None
    assert _upstream_svc_device("", cuda) is None
    assert _upstream_svc_device("cuda", cuda) == "cuda:0"


def test_sovits_directml_auto_receives_explicit_private_device() -> None:
    directml = SimpleNamespace(backend="directml", device="privateuseone:1")
    assert _upstream_svc_device("auto", directml) == "privateuseone:1"


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
