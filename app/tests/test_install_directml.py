from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_installer_module():
    installer_path = Path(__file__).resolve().parents[2] / "install" / "install.py"
    spec = importlib.util.spec_from_file_location("xb_directml_installer", installer_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_directml_voice_environments_use_python_310() -> None:
    installer = _load_installer_module()

    assert installer._svc_python_for_stack("directml") == "3.10"
    assert installer._rvc_python_for_stack("directml") == "3.10"
    assert installer._svc_python_for_stack("cu121") == "3.9"
    assert installer._rvc_python_for_stack("cpu") == "3.9"


def test_directml_torch_install_never_invokes_empty_pip() -> None:
    installer = _load_installer_module()
    calls: list[tuple[tuple[str, ...], str | None]] = []

    def pip(*args: str, index: str | None = None) -> None:
        calls.append((args, index))

    installer._install_selected_torch_runtime(
        pip,
        use_directml=True,
        torch_specs=[],
        torch_index="",
    )

    assert len(calls) == 1
    assert calls[0][0] == (
        "torch-directml==0.2.5.dev240914",
        "torchaudio==2.4.1",
    )
    assert calls[0][1] is None


def test_empty_non_directml_torch_package_list_is_rejected() -> None:
    installer = _load_installer_module()

    with pytest.raises(RuntimeError, match="package list is empty"):
        installer._install_selected_torch_runtime(
            lambda *_args, **_kwargs: None,
            use_directml=False,
            torch_specs=[],
            torch_index="",
        )


def test_directml_svc_requirements_override_python39_builds(tmp_path: Path) -> None:
    installer = _load_installer_module()
    requirements = tmp_path / "requirements_win.txt"
    requirements.write_text(
        "numpy==1.19.5\npyworld==0.3.0\nscipy==1.7.3\ntorch==1.10.0\n",
        encoding="utf-8",
    )

    filtered = installer._filter_requirements(
        requirements,
        extra_deny=installer.DIRECTML_EXTRA_DENY,
        overrides=installer.PYTHON310_REQ_OVERRIDES,
    )
    result = filtered.read_text(encoding="utf-8")

    assert "numpy==1.23.5" in result
    assert "pyworld==0.3.5" in result
    assert "scipy==1.10.1" in result
    assert "numpy==1.19.5" not in result
    assert "pyworld==0.3.0" not in result
    assert "torch==1.10.0" not in result


def test_uvr_directml_validation_initializes_separator(monkeypatch) -> None:
    installer = _load_installer_module()
    calls: list[list[str]] = []
    monkeypatch.setattr(installer, "run", lambda command: calls.append(command))

    installer._verify_uvr_directml("uvr-python.exe")

    assert len(calls) == 1
    assert calls[0][:2] == ["uvr-python.exe", "-c"]
    check = calls[0][2]
    assert "info_only=True" not in check
    assert "Separator(model_file_dir=td.name,use_directml=True)" in check
    assert "s.onnx_execution_provider" in check


def test_ddsp_amd_stack_uses_cpu_torch(monkeypatch, tmp_path: Path) -> None:
    installer = _load_installer_module()
    calls: list[tuple[tuple[str, ...], str | None]] = []
    monkeypatch.setattr(installer, "fetch_ddsp", lambda: None)
    monkeypatch.setattr(installer, "DDSP_VENV", tmp_path / "venv")
    monkeypatch.setattr(installer, "DDSP_DIR", tmp_path / "ddsp")
    monkeypatch.setattr(installer, "seed_ddsp_base_models", lambda: None)
    monkeypatch.setattr(installer, "_verify_ddsp_hubert", lambda py: None)
    monkeypatch.setattr(installer, "run", lambda command, **kwargs: None)
    python = installer.venv_python(installer.DDSP_VENV)
    python.parent.mkdir(parents=True)
    python.write_bytes(b"python")
    requirements = installer.DDSP_DIR / "requirements.txt"
    requirements.parent.mkdir(parents=True)
    requirements.write_text("transformers\n", encoding="utf-8")
    monkeypatch.setattr(
        installer,
        "uv_pip_install",
        lambda uv, py, *args, index=None: calls.append((args, index)),
    )

    installer.step_ddsp("uv", "directml")

    assert any(
        args == ("torch==2.5.1", "torchaudio==2.5.1")
        and index == installer.TORCH_CPU_INDEX
        for args, index in calls
    )
    assert not any(any("torch-directml" in arg for arg in args) for args, _ in calls)
