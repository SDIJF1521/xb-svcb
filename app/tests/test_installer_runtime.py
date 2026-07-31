from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from install.configure_user_env import merge_user_path


DETECTOR = ROOT / "install" / "detect_python.bat"
INSTALLER_SCRIPT = ROOT / "installer" / "xb-svcb.iss"


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
