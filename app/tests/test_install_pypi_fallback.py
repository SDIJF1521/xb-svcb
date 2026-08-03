from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


def _load_installer_module():
    installer_path = Path(__file__).resolve().parents[2] / "install" / "install.py"
    spec = importlib.util.spec_from_file_location("xb_pypi_fallback_installer", installer_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_uv_pip_install_switches_to_fallback_mirror_before_reinstall(monkeypatch) -> None:
    installer = _load_installer_module()
    monkeypatch.setattr(installer, "PYPI_MIRROR", "https://mirror.example/simple")
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs) -> None:
        calls.append(command)
        if len(calls) == 1:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(installer, "run", fake_run)

    installer.uv_pip_install("uv", "python.exe", "numpy==1.22.4")

    assert len(calls) == 2
    assert installer.PYPI_FALLBACK_INDEX == "https://mirrors.cloud.tencent.com/pypi/simple"
    assert "https://mirror.example/simple" in calls[0]
    assert "--reinstall" not in calls[1]
    assert "https://mirror.example/simple" not in calls[1]
    assert installer.PYPI_FALLBACK_INDEX in calls[1]


def test_uv_pip_install_reinstalls_from_fallback_mirror_if_fallback_fails(monkeypatch) -> None:
    installer = _load_installer_module()
    monkeypatch.setattr(installer, "PYPI_MIRROR", "https://mirror.example/simple")
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs) -> None:
        calls.append(command)
        if len(calls) < 3:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(installer, "run", fake_run)

    installer.uv_pip_install("uv", "python.exe", "librosa==0.10.2")

    assert len(calls) == 3
    assert "https://mirror.example/simple" in calls[0]
    assert "https://mirror.example/simple" not in calls[1]
    assert "https://mirror.example/simple" not in calls[2]
    assert "--reinstall" in calls[2]
    assert installer.PYPI_FALLBACK_INDEX in calls[2]
