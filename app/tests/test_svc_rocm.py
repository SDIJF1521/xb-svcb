import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure.svc_worker import (
    _configure_rocm_miopen,
    _disable_missing_volume_embedding,
    _validate_svc_audio,
    _validate_svc_generator,
)


def test_svc_rocm_disables_gfx12_miopen_asm_by_default() -> None:
    names = (
        "MIOPEN_DEBUG_GCN_ASM_KERNELS",
        "MIOPEN_DEBUG_CONV_DIRECT_ASM_3X3U",
        "MIOPEN_DEBUG_CONV_DIRECT_ASM_1X1U",
        "MIOPEN_DEBUG_CONV_IMPLICIT_GEMM_ASM_FWD_V4R1",
        "MIOPEN_DEBUG_CONV_IMPLICIT_GEMM_ASM_FWD_GTC_XDLOPS",
        "MIOPEN_FIND_MODE",
    )
    with patch.dict(os.environ, {}, clear=True):
        _configure_rocm_miopen()
        assert os.environ["MIOPEN_DEBUG_GCN_ASM_KERNELS"] == "0"
        assert os.environ["MIOPEN_FIND_MODE"] == "FAST"
        assert all(os.environ[name] == "0" for name in names[:-1])


def test_svc_rocm_keeps_explicit_miopen_override() -> None:
    with patch.dict(os.environ, {"MIOPEN_FIND_MODE": "NORMAL"}, clear=True):
        _configure_rocm_miopen()
        assert os.environ["MIOPEN_FIND_MODE"] == "NORMAL"
        assert os.environ["MIOPEN_DEBUG_GCN_ASM_KERNELS"] == "0"


def test_svc_uses_checkpoint_as_authority_for_optional_volume_embedding(tmp_path) -> None:
    import torch

    checkpoint = tmp_path / "model.pth"
    torch.save({"model": {"pre.weight": torch.ones(1)}}, checkpoint)
    network = SimpleNamespace(vol_embedding=True)
    svc = SimpleNamespace(vol_embedding=True, net_g_ms=network)

    assert _disable_missing_volume_embedding(svc, str(checkpoint), torch) is True
    assert svc.vol_embedding is False
    assert network.vol_embedding is False


def test_svc_rejects_nan_checkpoint_weights() -> None:
    import torch

    network = torch.nn.Linear(2, 2)
    with torch.no_grad():
        network.weight[0, 0] = float("nan")
    with pytest.raises(RuntimeError, match="NaN/Inf"):
        _validate_svc_generator(SimpleNamespace(net_g_ms=network), torch)


def test_svc_rejects_nonfinite_audio_and_dc_output(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"source")
    monkeypatch.setitem(
        sys.modules,
        "soundfile",
        SimpleNamespace(read=lambda *_args, **_kwargs: (np.ones((4000, 1), dtype=np.float32), 16000)),
    )
    with pytest.raises(RuntimeError, match="NaN/Inf"):
        _validate_svc_audio(np.array([np.nan], dtype=np.float32), str(source), np)
    with pytest.raises(RuntimeError, match="直流"):
        _validate_svc_audio(np.full(4000, -0.9, dtype=np.float32), str(source), np)
