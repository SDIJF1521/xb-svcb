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

@pytest.mark.parametrize("label", ["background", "bgm", "no vocals", "music", "accompaniment"])
def test_pymss_server_stem_selection_finds_renamed_accompaniment(label: str) -> None:
    vocals = np.ones((16, 2), dtype=np.float32)
    accompaniment = np.zeros((16, 2), dtype=np.float32)

    selected, picked = _pick_server_stems(
        {"vocals": vocals, label: accompaniment},
        "vocal_separation",
        "vocals",
    )

    assert selected is vocals
    assert picked is accompaniment


def test_pymss_server_stem_selection_handles_single_stem_instrumental_model() -> None:
    instrumental = np.ones((8, 2), dtype=np.float32)

    selected, accompaniment = _pick_server_stems(
        {"instrumental": instrumental},
        "vocal_separation",
        "instrumental",
    )

    assert selected is instrumental
    assert accompaniment is None


def test_pymss_accompaniment_picker_recognizes_background_labels(tmp_path: Path) -> None:
    from infrastructure.pymss_worker import _pick_accompaniment

    vocal = tmp_path / "song_(Vocals).wav"
    background = tmp_path / "song_(Background).wav"
    vocal.write_bytes(b"v")
    background.write_bytes(b"b")

    assert _pick_accompaniment(tmp_path, vocal, "vocal_separation") == background


def test_pymss_accompaniment_picker_uses_elision_for_two_stems(tmp_path: Path) -> None:
    from infrastructure.pymss_worker import _pick_accompaniment

    vocal = tmp_path / "song_(Vocals).wav"
    remainder = tmp_path / "song_(Remainder).wav"
    vocal.write_bytes(b"v")
    remainder.write_bytes(b"r")

    assert _pick_accompaniment(tmp_path, vocal, "vocal_separation") == remainder
    # Dereverb stems are dry/wet rather than vocal/accompaniment.
    assert _pick_accompaniment(tmp_path, vocal, "dereverb") is None
