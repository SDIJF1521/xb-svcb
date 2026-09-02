from __future__ import annotations

import importlib.util
import subprocess
import zipfile
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


def test_uv_pip_install_prefers_matching_bundled_wheelhouse(monkeypatch, tmp_path: Path) -> None:
    installer = _load_installer_module()
    wheel_dir = tmp_path / "wheels" / "py310" / "cu126"
    wheel_dir.mkdir(parents=True)
    (wheel_dir / "torch-2.5.1+cu126-cp310-cp310-win_amd64.whl").write_bytes(b"wheel")
    calls: list[list[str]] = []

    monkeypatch.setenv("XB_WHEELHOUSE", str(tmp_path / "wheels"))
    monkeypatch.setenv("XB_WHEELHOUSE_STRICT", "1")
    monkeypatch.setattr(installer, "run", lambda command, **_kwargs: calls.append(command))

    installer.uv_pip_install(
        "uv",
        "python.exe",
        "torch==2.5.1",
        component="uvr",
        gpu_stack="cu126",
        python_version="3.10",
    )

    assert len(calls) == 1
    assert "--no-index" in calls[0]
    assert "--find-links" in calls[0]
    assert str(wheel_dir) in calls[0]
    assert installer.PYPI_FALLBACK_INDEX not in calls[0]


def test_uv_pip_install_can_fallback_online_when_wheelhouse_is_non_strict(
    monkeypatch,
    tmp_path: Path,
) -> None:
    installer = _load_installer_module()
    wheel_dir = tmp_path / "wheels" / "py310" / "cpu"
    wheel_dir.mkdir(parents=True)
    (wheel_dir / "numpy-1.23.5-cp310-cp310-win_amd64.whl").write_bytes(b"wheel")
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs) -> None:
        calls.append(command)
        if "--no-index" in command:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setenv("XB_WHEELHOUSE", str(tmp_path / "wheels"))
    monkeypatch.setenv("XB_WHEELHOUSE_STRICT", "0")
    monkeypatch.setattr(installer, "PYPI_MIRROR", "https://mirror.example/simple")
    monkeypatch.setattr(installer, "run", fake_run)

    installer.uv_pip_install(
        "uv",
        "python.exe",
        "numpy==1.23.5",
        component="vocal",
        gpu_stack="cpu",
        python_version="3.10",
    )

    assert len(calls) == 3
    assert "--no-index" in calls[0]
    assert "--reinstall" in calls[1]
    assert "--no-index" in calls[1]
    assert "https://mirror.example/simple" in calls[2]


def test_repair_broken_wheel_metadata_from_matching_wheelhouse(
    monkeypatch, tmp_path: Path
) -> None:
    installer = _load_installer_module()
    wheel_root = tmp_path / "wheels"
    wheel_dir = wheel_root / "py310" / "cu126"
    wheel_dir.mkdir(parents=True)
    wheel = wheel_dir / "torch-2.5.1+cu126-cp310-cp310-win_amd64.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "torch-2.5.1+cu126.dist-info/METADATA",
            "Name: torch\nVersion: 2.5.1+cu126\n",
        )
        archive.writestr(
            "torch-2.5.1+cu126.dist-info/WHEEL",
            "Wheel-Version: 1.0\n",
        )
        archive.writestr("torch-2.5.1+cu126.dist-info/RECORD", "")
        archive.writestr("torch-2.5.1+cu126.dist-info/INSTALLER", "uv\n")

    venv = tmp_path / ".venv-uvr"
    dist_info = venv / "Lib" / "site-packages" / "torch-2.5.1+cu126.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "WHEEL").write_text("Wheel-Version: 1.0\n", encoding="utf-8")
    monkeypatch.setenv("XB_WHEELHOUSE", str(wheel_root))

    repaired = installer._repair_broken_wheel_metadata(
        venv,
        ("torch",),
        component="uvr",
        gpu_stack="cu126",
        python_version="3.10",
    )

    assert repaired == ["torch"]
    assert "Version: 2.5.1+cu126" in (dist_info / "METADATA").read_text(encoding="utf-8")
    assert (dist_info / "RECORD").exists()


def test_repair_broken_wheel_metadata_removes_orphan_without_wheel(
    monkeypatch, tmp_path: Path
) -> None:
    installer = _load_installer_module()
    wheel_root = tmp_path / "wheels"
    (wheel_root / "py310" / "cu126").mkdir(parents=True)
    venv = tmp_path / ".venv-uvr"
    dist_info = venv / "Lib" / "site-packages" / "torch-2.5.1+cu126.dist-info"
    dist_info.mkdir(parents=True)
    monkeypatch.setenv("XB_WHEELHOUSE", str(wheel_root))

    repaired = installer._repair_broken_wheel_metadata(
        venv,
        ("torch",),
        component="uvr",
        gpu_stack="cu126",
        python_version="3.10",
    )

    assert repaired == []
    assert not dist_info.exists()
