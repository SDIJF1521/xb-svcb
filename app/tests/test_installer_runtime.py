from __future__ import annotations

import os
import importlib.util
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from install.configure_user_env import merge_user_path


DETECTOR = ROOT / "install" / "detect_python.bat"
INSTALLER_SCRIPT = ROOT / "installer" / "xb-svcb.iss"


def _load_wheelhouse_module():
    script = ROOT / "install" / "prepare_wheelhouse.py"
    spec = importlib.util.spec_from_file_location("xb_prepare_wheelhouse", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run_detector(tmp_path: Path, candidate: Path) -> subprocess.CompletedProcess[str]:
    wrapper = tmp_path / "run_detector.bat"
    wrapper.write_text(
        "@echo off\n"
        "chcp 65001 >nul\n"
        f'call "{DETECTOR}"\n'
        'set "DETECT_RC=%ERRORLEVEL%"\n'
        'echo EXE=%XB_PYTHON_EXE%\n'
        'echo DIR=%XB_PYTHON_DIR%\n'
        'exit /b %DETECT_RC%\n',
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    env["LOCALAPPDATA"] = str(tmp_path / "empty-local-app-data")
    env["XB_PYTHON_EXE"] = str(candidate)
    env["XB_PYTHON_DIR"] = ""
    return subprocess.run(
        ["cmd.exe", "/d", "/c", str(wrapper)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )


def test_python_detector_accepts_runnable_python_310_or_newer(tmp_path: Path) -> None:
    result = _run_detector(tmp_path, Path(sys.executable))

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"EXE={Path(sys.executable).resolve()}" in result.stdout
    assert f"DIR={Path(sys.executable).resolve().parent}" in result.stdout


def test_python_detector_rejects_an_executable_that_is_not_python(
    tmp_path: Path,
) -> None:
    not_python = Path(os.environ["SystemRoot"]) / "System32" / "where.exe"

    result = _run_detector(tmp_path, not_python)

    assert result.returncode == 1
    assert "EXE=" in result.stdout
    assert str(not_python) not in result.stdout


def test_ffmpeg_bin_is_added_to_user_path_once() -> None:
    current = r"C:\Windows\System32;C:\Tools"
    ffmpeg_bin = r"C:\Apps\XB-SVCB\tools\ffmpeg\bin"

    merged, added, existing = merge_user_path(current, [ffmpeg_bin, ffmpeg_bin + "\\"])

    assert merged == current + ";" + ffmpeg_bin
    assert added == [ffmpeg_bin]
    assert existing == [ffmpeg_bin + "\\"]


def test_installer_explicitly_packages_and_validates_python_detector() -> None:
    script = INSTALLER_SCRIPT.read_text(encoding="utf-8")

    assert 'Source: "..\\install\\detect_python.bat"' in script
    assert "install\\detect_python.bat')) then" in script


def test_installer_entrypoints_suppress_uv_cross_drive_hardlink_warning() -> None:
    setup_env = (ROOT / "setup_env.bat").read_text(encoding="utf-8")
    prereqs = (ROOT / "install_prereqs.bat").read_text(encoding="utf-8")
    script = INSTALLER_SCRIPT.read_text(encoding="utf-8")

    assert 'set "UV_LINK_MODE=copy"' in setup_env
    assert 'set "UV_LINK_MODE=copy"' in prereqs
    assert 'set "UV_LINK_MODE=copy"' in script


def test_setup_env_uses_install_py_as_the_single_progress_source() -> None:
    setup_env = (ROOT / "setup_env.bat").read_text(encoding="utf-8")
    script = INSTALLER_SCRIPT.read_text(encoding="utf-8")

    assert "[XB-PROGRESS] 3 正在查找 Python 运行时" not in setup_env
    assert "[XB-PROGRESS] 10 已找到 Python，准备创建隔离环境" not in setup_env
    assert "[XB-PROGRESS] 18 正在执行运行环境安装脚本" not in setup_env
    assert "if Target < EnvProgressCurrent then" in script


def test_installer_packages_and_uses_bundled_wheelhouse() -> None:
    setup_env = (ROOT / "setup_env.bat").read_text(encoding="utf-8")
    prereqs = (ROOT / "install_prereqs.bat").read_text(encoding="utf-8")
    script = INSTALLER_SCRIPT.read_text(encoding="utf-8")
    build = (ROOT / "installer" / "build.ps1").read_text(encoding="utf-8")

    assert 'Source: "..\\assets\\wheels\\*"' in script
    assert "assets\\wheels\\wheelhouse.json" in script
    assert 'set "XB_WHEELHOUSE=' in script
    assert 'set "XB_WHEELHOUSE_STRICT=1"' in script
    assert 'set "XB_WHEELHOUSE=%~dp0assets\\wheels"' in setup_env
    assert 'set "XB_WHEELHOUSE=%~dp0assets\\wheels"' in prereqs
    assert "--no-index --find-links" in prereqs
    assert "install\\prepare_wheelhouse.py" in build
    assert "--clean" in build
    assert "assets\\wheels\\wheelhouse.json" in build


def test_wheelhouse_binary_download_uses_managed_tool_python(
    tmp_path: Path, monkeypatch
) -> None:
    wheelhouse = _load_wheelhouse_module()
    tool_py = tmp_path / "tools" / "Scripts" / "python.exe"
    commands: list[list[str]] = []

    class Installer:
        PYPI_MIRROR = ""
        PYPI_FALLBACK_INDEX = "https://example.invalid/simple"

    monkeypatch.setattr(wheelhouse, "_ensure_tool_python", lambda root, installer: tool_py)
    monkeypatch.setattr(wheelhouse, "_run", lambda cmd: commands.append(cmd))

    batch = wheelhouse.DownloadBatch(
        "bootstrap uv",
        tmp_path / "assets" / "wheels" / "bootstrap",
        "3.10",
        ("uv",),
    )
    wheelhouse._download_batch(tmp_path, Installer, batch)

    assert commands
    assert commands[0][:4] == [str(tool_py), "-m", "pip", "download"]


def test_wheelhouse_download_can_skip_dependency_resolution(tmp_path: Path, monkeypatch) -> None:
    wheelhouse = _load_wheelhouse_module()
    tool_py = tmp_path / "tools" / "Scripts" / "python.exe"
    commands: list[list[str]] = []

    class Installer:
        PYPI_MIRROR = ""
        PYPI_FALLBACK_INDEX = "https://example.invalid/simple"

    monkeypatch.setattr(wheelhouse, "_ensure_tool_python", lambda root, installer: tool_py)
    monkeypatch.setattr(wheelhouse, "_run", lambda cmd: commands.append(cmd))

    batch = wheelhouse.DownloadBatch(
        "matplotlib",
        tmp_path / "assets" / "wheels" / "svc" / "py39" / "cpu",
        "3.9",
        ("matplotlib==3.7.5",),
        no_deps=True,
    )
    wheelhouse._download_batch(tmp_path, Installer, batch)

    assert commands
    assert "--no-deps" in commands[0]


def test_wheelhouse_plan_builds_source_only_packages_and_splits_conflicting_torch() -> None:
    wheelhouse = _load_wheelhouse_module()

    cpu = wheelhouse.build_plan(ROOT, {"cpu"})
    directml = wheelhouse.build_plan(ROOT, {"directml"})
    cu128 = wheelhouse.build_plan(ROOT, {"cu128"})

    assert any(
        batch.dest == ROOT / "assets" / "wheels" / "svc" / "py39" / "cpu"
        and batch.build_source
        and "fairseq==0.12.2" in batch.packages
        for batch in cpu
    )
    assert any(
        batch.label == "svc py39 matplotlib support"
        and batch.dest == ROOT / "assets" / "wheels" / "svc" / "py39" / "cpu"
        and "importlib-resources>=3.2.0" in batch.packages
        for batch in cpu
    )
    assert any(
        batch.label == "svc py39 matplotlib"
        and batch.dest == ROOT / "assets" / "wheels" / "svc" / "py39" / "cpu"
        and batch.no_deps
        and batch.packages == ("matplotlib==3.7.5",)
        for batch in cpu
    )
    assert any(
        batch.dest == ROOT / "assets" / "wheels" / "rvc" / "py39" / "cpu"
        and batch.build_source
        and "fairseq==0.12.2" in batch.packages
        for batch in cpu
    )
    assert any(
        batch.dest == ROOT / "assets" / "wheels" / "ddsp" / "py310" / "directml"
        and "torch==2.5.1" in batch.constraints
        for batch in directml
    )
    assert any(
        batch.label == "seedvc cpu source wheels"
        and batch.dest == ROOT / "assets" / "wheels" / "py310" / "cpu"
        and batch.build_source
        and batch.no_deps
        and "argbind>=0.3.7" in batch.packages
        for batch in cpu
    )
    assert any(
        batch.label == "seedvc requirements"
        and batch.dest == ROOT / "assets" / "wheels" / "py310" / "cpu"
        and batch.build_source
        for batch in cpu
    )
    assert any(
        batch.label == "seedvc directml source wheels"
        and batch.dest == ROOT / "assets" / "wheels" / "py310" / "directml"
        and batch.build_source
        and batch.no_deps
        and "argbind>=0.3.7" in batch.packages
        for batch in directml
    )
    assert any(
        batch.label == "seedvc requirements"
        and batch.dest == ROOT / "assets" / "wheels" / "py310" / "directml"
        and batch.build_source
        for batch in directml
    )
    assert any(
        batch.dest == ROOT / "assets" / "wheels" / "py310" / "directml"
        and "torch==2.4.1" in batch.constraints
        for batch in directml
    )
    assert any(
        batch.label == "svc cu128 requirements"
        and batch.dest == ROOT / "assets" / "wheels" / "py310" / "cu128"
        and batch.build_source
        for batch in cu128
    )
    expected_fcpe = ("einops==0.8.2", "local-attention==1.10.0")
    assert any(
        batch.label == "svc cpu py39 fcpe runtime"
        and batch.packages == expected_fcpe
        for batch in cpu
    )
    assert any(
        batch.label == "svc directml fcpe runtime"
        and batch.packages == expected_fcpe
        for batch in directml
    )
    assert any(
        batch.label == "svc cu128 fcpe runtime"
        and batch.packages == expected_fcpe
        for batch in cu128
    )
    svc_requirement_batches = [
        batch
        for batch in (*cpu, *directml, *cu128)
        if batch.label in {
            "svc py39 requirements",
            "svc directml requirements",
            "svc cu128 requirements",
        }
    ]
    assert svc_requirement_batches
    for batch in svc_requirement_batches:
        requirement_text = batch.requirements.read_text(encoding="utf-8")
        assert "einops==0.8.2" in requirement_text
        assert "local-attention==1.10.0" in requirement_text
    assert any(
        batch.label == "ddsp requirements"
        and batch.dest == ROOT / "assets" / "wheels" / "py310" / "cpu"
        and batch.build_source
        for batch in cpu
    )
    assert any(
        batch.label == "ddsp directml requirements"
        and batch.dest == ROOT / "assets" / "wheels" / "ddsp" / "py310" / "directml"
        and batch.build_source
        for batch in directml
    )
