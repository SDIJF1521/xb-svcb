from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import config
from infrastructure.pymss_tool import PymssTool
from infrastructure.pymss_worker import _pick_server_stems


class FakeSession:
    def __init__(self, command: list[str], **kwargs) -> None:  # noqa: ANN003
        self.command = command
        self.kwargs = kwargs


def test_pymss_realtime_session_builds_persistent_server_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    python = tmp_path / "python.exe"
    worker = tmp_path / "pymss_worker.py"
    model_dir = tmp_path / "models"
    python.write_bytes(b"python")
    worker.write_bytes(b"worker")
    model_dir.mkdir()
    monkeypatch.setattr(config, "PYMSS_PYTHON", python)
    monkeypatch.setattr(config, "PYMSS_WORKER", worker)
    monkeypatch.setattr(config, "PYMSS_MODEL_DIR", model_dir)
    monkeypatch.setattr(config, "pymss_environment_ready", lambda: True)
    monkeypatch.setattr(config, "pymss_model_ready", lambda _model: True)
    monkeypatch.setattr(
        PymssTool,
        "_resolve_model",
        lambda self, model, purpose: (  # noqa: ARG005, ANN001
            "demo.ckpt",
            {"target_stem": "vocals"},
            config.PYMSS_PURPOSE_VOCAL,
        ),
    )
    monkeypatch.setattr(
        "infrastructure.pymss_tool.PersistentInferenceSession",
        FakeSession,
    )

    session = PymssTool().open_realtime_session(
        "demo.ckpt",
        "rocm",
        tmp_path / "out",
        purpose=config.PYMSS_PURPOSE_VOCAL,
    )

    assert "--server" in session.command
    assert session.command[session.command.index("--model") + 1] == "demo.ckpt"
    assert session.command[session.command.index("--device") + 1] == "rocm"
    assert session.command[session.command.index("--target-stem") + 1] == "vocals"
    assert session.kwargs["ready_marker"] == "PYMSS_SERVER_READY"
    assert session.kwargs["result_marker"] == "PYMSS_SERVER_RESULT\t"


def test_pymss_realtime_session_rejects_directml(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(config, "PYMSS_MODEL_DIR", tmp_path)
    monkeypatch.setattr(config, "pymss_environment_ready", lambda: True)
    monkeypatch.setattr(config, "pymss_model_ready", lambda _model: True)
    monkeypatch.setattr(
        PymssTool,
        "_resolve_model",
        lambda self, model, purpose: (  # noqa: ARG005, ANN001
            "demo.ckpt",
            {},
            config.PYMSS_PURPOSE_VOCAL,
        ),
    )
    with pytest.raises(RuntimeError, match="DirectML"):
        PymssTool().open_realtime_session("demo.ckpt", "directml")


def test_pymss_server_stem_selection_prefers_vocals_and_keeps_instrumental() -> None:
    vocals = np.ones((16, 2), dtype=np.float32)
    instrumental = np.zeros((16, 2), dtype=np.float32)
    selected, accompaniment = _pick_server_stems(
        {"vocals": vocals, "instrumental": instrumental},
        "vocal_separation",
        "vocals",
    )

    assert selected is vocals
    assert accompaniment is instrumental


def test_pymss_server_stem_selection_uses_dry_dereverb_stem() -> None:
    clean = np.ones((16, 2), dtype=np.float32)
    selected, accompaniment = _pick_server_stems(
        {"No Reverb": clean, "Reverb": np.zeros((16, 2), dtype=np.float32)},
        "dereverb",
        "",
    )

    assert selected is clean
    assert accompaniment is None
