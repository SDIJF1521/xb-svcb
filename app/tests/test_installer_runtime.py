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


def _load_install_module():
    script = ROOT / "install" / "install.py"
    spec = importlib.util.spec_from_file_location("xb_install", script)
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


def test_python_detector_does_not_trust_a_stale_exported_path(tmp_path: Path) -> None:
    wrapper = tmp_path / "run_detector_stale.bat"
    wrapper.write_text(
        "@echo off\n"
        "chcp 65001 >nul\n"
        f'call "{DETECTOR}"\n'
        'set "DETECT_RC=%ERRORLEVEL%"\n'
        'echo EXE=%XB_PYTHON_EXE%\n'
        'exit /b %DETECT_RC%\n',
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    env["LOCALAPPDATA"] = str(tmp_path / "empty-local-app-data")
    env["XB_PYTHON_EXE"] = str(tmp_path / "old" / "python.exe")
    env["XB_PYTHON_DIR"] = str(Path(sys.executable).resolve().parent)

    result = subprocess.run(
        ["cmd.exe", "/d", "/c", str(wrapper)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"EXE={Path(sys.executable).resolve()}" in result.stdout


def test_ffmpeg_bin_is_added_to_user_path_once() -> None:
    current = r"C:\Windows\System32;C:\Tools"
    ffmpeg_bin = r"C:\Apps\XB-SVCB\tools\ffmpeg\bin"

    merged, added, existing = merge_user_path(current, [ffmpeg_bin, ffmpeg_bin + "\\"])

    assert merged == current + ";" + ffmpeg_bin
    assert added == [ffmpeg_bin]
    assert existing == [ffmpeg_bin + "\\"]


def test_installer_explicitly_packages_and_validates_python_detector() -> None:
    script = INSTALLER_SCRIPT.read_text(encoding="utf-8")
    prereqs = (ROOT / "install_prereqs.bat").read_text(encoding="utf-8")

    assert 'Source: "..\\install\\detect_python.bat"' in script
    assert "install\\detect_python.bat')) then" in script
    assert "function PythonPathCommandAvailable" in script
    assert "\\windowsapps\\" in script
    assert ".venv-plugins Python 不可运行" in script
    assert ".venv-uvr Python 不可运行" in script
    assert 'if defined XB_PYTHON_DIR if exist "%XB_PYTHON_DIR%\\python.exe" set "XB_PYTHON_EXE=' not in prereqs


def test_installer_detects_vbcable_and_provides_manual_official_download() -> None:
    script = INSTALLER_SCRIPT.read_text(encoding="utf-8")
    prereqs = (ROOT / "install_prereqs.bat").read_text(encoding="utf-8")

    assert "function VbCableAvailable(): Boolean;" in script
    assert "CABLE Input" in script
    assert "CABLE Output" in script
    assert "https://vb-audio.com/Cable/" in script
    assert "VbCableDownloadButton" in script
    assert ":CHECK_VBCABLE" in prereqs
    assert "https://vb-audio.com/Cable/" in prereqs
    assert "XB_VBCABLE_READY" in prereqs


def test_installer_entrypoints_suppress_uv_cross_drive_hardlink_warning() -> None:
    setup_env = (ROOT / "setup_env.bat").read_text(encoding="utf-8")
    prereqs = (ROOT / "install_prereqs.bat").read_text(encoding="utf-8")
    script = INSTALLER_SCRIPT.read_text(encoding="utf-8")

    assert 'set "UV_LINK_MODE=copy"' in setup_env
    assert 'set "UV_LINK_MODE=copy"' in prereqs
    assert 'set "UV_LINK_MODE=copy"' in script


def test_pyinstaller_packages_python_plugin_worker_and_sdk() -> None:
    spec = (ROOT / "installer" / "xb-svcb-app.spec").read_text(encoding="utf-8")
    installer = INSTALLER_SCRIPT.read_text(encoding="utf-8")
    setup = (ROOT / "install" / "install.py").read_text(encoding="utf-8")

    assert '"plugin_sdk_python/xb_svcb_plugin"' in spec
    assert '"plugin_worker.py"' in spec
    assert 'PLUGIN_VENV = ROOT / ".venv-plugins"' in setup
    assert '"plugins": lambda uv, stack: step_plugins(uv)' in setup
    assert "function ValidatePluginRuntime(): Boolean;" in installer
    assert ".venv-plugins\\Scripts\\python.exe" in installer


def test_ffmpeg_file_check_does_not_expand_app_before_directory_initialization() -> None:
    script = INSTALLER_SCRIPT.read_text(encoding="utf-8")
    start = script.index("function SystemFfmpegAvailable(): Boolean;")
    end = script.index("function CommandOutput(", start)
    function = script[start:end]

    assert "CommandSucceeds('ffmpeg -version')" in function
    assert "CommandSucceeds('ffprobe -version')" in function
    assert "{app}" not in function


def test_setup_env_exports_verified_python310_for_runtime_venvs() -> None:
    setup_env = (ROOT / "setup_env.bat").read_text(encoding="utf-8")

    assert 'set "XB_PYTHON_310_EXE=%XB_PYTHON_EXE%"' in setup_env


def test_installer_batch_entrypoints_use_windows_line_endings() -> None:
    for relative in ("setup_env.bat", "install_prereqs.bat", "install/detect_python.bat"):
        data = (ROOT / relative).read_bytes()
        assert data.count(b"\n") == data.count(b"\r\n"), relative


def test_install_py_prefers_verified_python310_over_uv_managed_cache(
    tmp_path: Path, monkeypatch
) -> None:
    installer = _load_install_module()
    py310 = tmp_path / "Python310" / "python.exe"
    py314 = tmp_path / "Python314" / "python.exe"
    py310.parent.mkdir()
    py314.parent.mkdir()
    py310.write_text("", encoding="ascii")
    py314.write_text("", encoding="ascii")

    monkeypatch.setenv("XB_PYTHON_310_EXE", str(py310))
    monkeypatch.setenv("XB_PYTHON_EXE", str(py314))

    def fake_minor(path: Path) -> str | None:
        if path == py310:
            return "3.10"
        if path == py314:
            return "3.14"
        return None

    monkeypatch.setattr(installer, "_python_minor_version", fake_minor)

    assert installer.python_spec_for_venv("3.10") == str(py310)
    assert installer.python_spec_for_venv("3.9") == "3.9"


def test_install_py_rejects_non310_verified_python_for_py310_venvs(
    tmp_path: Path, monkeypatch
) -> None:
    installer = _load_install_module()
    py314 = tmp_path / "Python314" / "python.exe"
    py314.parent.mkdir()
    py314.write_text("", encoding="ascii")

    monkeypatch.delenv("XB_PYTHON_310_EXE", raising=False)
    monkeypatch.setenv("XB_PYTHON_EXE", str(py314))
    monkeypatch.setattr(installer, "_python_minor_version", lambda path: "3.14")

    assert installer.python_spec_for_venv("3.10") == "3.10"


def test_ensure_venv_rebuilds_an_unreadable_existing_environment(
    tmp_path: Path, monkeypatch
) -> None:
    installer = _load_install_module()
    venv_dir = tmp_path / ".venv-vocal"
    venv_python = installer.venv_python(venv_dir)
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="ascii")
    commands: list[list[str]] = []

    monkeypatch.setattr(installer, "_python_minor_version", lambda path: None)
    monkeypatch.setattr(
        installer,
        "python_spec_for_venv",
        lambda version: r"C:\Python310\python.exe",
    )
    monkeypatch.setattr(installer, "run", lambda cmd: commands.append(cmd))

    installer.ensure_venv("uv.exe", venv_dir, "3.10")

    assert not venv_dir.exists()
    assert commands == [
        [
            "uv.exe",
            "venv",
            "--python",
            r"C:\Python310\python.exe",
            str(venv_dir),
        ]
    ]


def test_installer_env_batch_escape_handles_percent_and_caret() -> None:
    script = INSTALLER_SCRIPT.read_text(encoding="utf-8")

    assert "StringChangeEx(Result, '^', '^^', True);" in script
    assert "StringChangeEx(Result, '%', '%%', True);" in script


def test_setup_env_uses_install_py_as_the_single_progress_source() -> None:
    setup_env = (ROOT / "setup_env.bat").read_text(encoding="utf-8")
    script = INSTALLER_SCRIPT.read_text(encoding="utf-8")

    assert "[XB-PROGRESS] 3 正在查找 Python 运行时" not in setup_env
    assert "[XB-PROGRESS] 10 已找到 Python，准备创建隔离环境" not in setup_env
    assert "[XB-PROGRESS] 18 正在执行运行环境安装脚本" not in setup_env
    assert "if Target < EnvProgressCurrent then" in script


def test_vocal_runtime_avoids_wheel_packaging_conflict() -> None:
    source = (ROOT / "install" / "install.py").read_text(encoding="utf-8")
    vocal = source[source.index("def step_vocal"):source.index("def step_hub")]

    assert "deepfilternet==0.5.6 requires packaging<24" in vocal
    assert 'pip("setuptools<81")' in vocal
    assert 'pip("setuptools<81", "wheel")' not in vocal
    assert 'pip("setuptools<81", "wheel")' in source


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


def test_wheelhouse_tool_python_only_bootstraps_pip(
    tmp_path: Path, monkeypatch
) -> None:
    wheelhouse = _load_wheelhouse_module()
    tool_py = tmp_path / ".tmp" / "wheelhouse-tools" / "Scripts" / "python.exe"
    tool_py.parent.mkdir(parents=True, exist_ok=True)
    tool_py.write_bytes(b"")
    ensured: list[Path] = []
    commands: list[list[str]] = []

    class Installer:
        PYPI_MIRROR = ""
        PYPI_FALLBACK_INDEX = "https://example.invalid/simple"

    monkeypatch.setattr(wheelhouse, "_TOOL_PYTHON", None)
    monkeypatch.setattr(wheelhouse, "_ensure_pip", lambda py: ensured.append(py))
    monkeypatch.setattr(wheelhouse, "_run", lambda cmd: commands.append(cmd))

    result = wheelhouse._ensure_tool_python(tmp_path, Installer)

    assert result == tool_py
    assert ensured == [tool_py]
    assert commands == []


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


def test_wheelhouse_requirements_always_use_wheel_builder(
    tmp_path: Path, monkeypatch
) -> None:
    wheelhouse = _load_wheelhouse_module()
    requirements = tmp_path / "seedvc.txt"
    requirements.write_text("funasr==1.1.5\n", encoding="utf-8")
    built: list[object] = []

    monkeypatch.setattr(
        wheelhouse,
        "_build_wheels",
        lambda root, installer, batch: built.append(batch),
    )

    def unexpected_binary_download(root, installer):
        raise AssertionError("requirements used binary-only download")

    monkeypatch.setattr(
        wheelhouse,
        "_ensure_tool_python",
        unexpected_binary_download,
    )

    batch = wheelhouse.DownloadBatch(
        "seedvc requirements",
        tmp_path / "assets" / "wheels" / "py310" / "cpu",
        "3.10",
        requirements=requirements,
    )
    wheelhouse._download_batch(tmp_path, object(), batch)

    assert built == [batch]


def test_wheelhouse_clean_runs_before_generating_requirements(
    tmp_path: Path, monkeypatch
) -> None:
    wheelhouse = _load_wheelhouse_module()
    old_wheel = tmp_path / "assets" / "wheels" / "old.whl"
    old_wheel.parent.mkdir(parents=True)
    old_wheel.write_bytes(b"stale")
    old_requirements = tmp_path / ".tmp" / "wheelhouse-requirements" / "seedvc.txt"
    old_requirements.parent.mkdir(parents=True)
    old_requirements.write_text("stale\n", encoding="utf-8")

    fresh_requirements = old_requirements

    def fake_build_plan(root, stacks):
        fresh_requirements.parent.mkdir(parents=True, exist_ok=True)
        fresh_requirements.write_text("fresh\n", encoding="utf-8")
        return []

    monkeypatch.setattr(wheelhouse, "_load_installer", lambda root: object())
    monkeypatch.setattr(wheelhouse, "build_plan", fake_build_plan)
    monkeypatch.setattr(wheelhouse, "_write_manifest", lambda root, batches: None)
    monkeypatch.setattr(
        wheelhouse.sys,
        "argv",
        ["prepare_wheelhouse.py", "--root", str(tmp_path), "--clean"],
    )

    assert wheelhouse.main() == 0
    assert not old_wheel.exists()
    assert fresh_requirements.read_text(encoding="utf-8") == "fresh\n"


def test_pymss_wheelhouse_is_isolated_with_a_compatible_torch_pair() -> None:
    installer = _load_install_module()
    wheelhouse = _load_wheelhouse_module()
    expected_constraints = (
        "setuptools<81",
        "torch==2.7.1",
        "torchaudio==2.7.1",
    )

    for stack in ("cpu", "directml", "cu121", "cu126", "cu128"):
        plan = wheelhouse.build_plan(ROOT, {stack})
        expected_stack = "cu126" if stack in {"cu121", "cu126"} else stack
        dest = ROOT / "assets" / "wheels" / "pymss" / "py310" / expected_stack
        package = next(batch for batch in plan if batch.label == f"pymss {expected_stack} package")
        torch = next(batch for batch in plan if batch.label == f"pymss {expected_stack} torch")

        assert package.dest == dest
        assert package.packages == ("pymss==2.0.18",)
        assert package.constraints == expected_constraints
        assert torch.dest == dest
        assert torch.packages == ("torch==2.7.1", "torchaudio==2.7.1")
        expected_index = (
            installer.TORCH_BLACKWELL_INDEX
            if expected_stack == "cu128"
            else installer.TORCH_PYMSS_CUDA_INDEX
            if expected_stack == "cu126"
            else installer.TORCH_CPU_INDEX
        )
        assert torch.index == expected_index


def test_pymss_installer_uses_the_same_isolated_runtime(
    tmp_path: Path, monkeypatch
) -> None:
    installer = _load_install_module()
    pip_calls: list[tuple[tuple[str, ...], str | None]] = []
    make_pip_calls: list[dict[str, str]] = []

    def fake_pip(*packages: str, index: str | None = None) -> None:
        pip_calls.append((packages, index))

    def fake_make_pip(uv: str, py: str, **kwargs: str):
        make_pip_calls.append(kwargs)
        return fake_pip

    monkeypatch.setattr(installer, "PYMSS_VENV", tmp_path / ".venv-pymss")
    monkeypatch.setattr(installer, "ensure_venv", lambda *args, **kwargs: None)
    monkeypatch.setattr(installer, "venv_python", lambda path: path / "Scripts" / "python.exe")
    monkeypatch.setattr(installer, "make_pip", fake_make_pip)
    monkeypatch.setattr(installer, "hr", lambda message: None)

    for stack in ("cpu", "directml", "cu121", "cu126", "cu128"):
        pip_calls.clear()
        make_pip_calls.clear()
        installer.step_pymss("uv", stack)

        expected_pymss_stack = "cu126" if stack in {"cu121", "cu126"} else stack
        assert make_pip_calls == [
            {
                "component": "pymss",
                "gpu_stack": expected_pymss_stack,
                "python_version": "3.10",
            }
        ]
        expected_index = (
            installer.TORCH_BLACKWELL_INDEX
            if expected_pymss_stack == "cu128"
            else installer.TORCH_PYMSS_CUDA_INDEX
            if expected_pymss_stack == "cu126"
            else installer.TORCH_CPU_INDEX
        )
        assert pip_calls == [
            (("torch==2.7.1", "torchaudio==2.7.1"), expected_index),
            (("pymss==2.0.18",), None),
        ]


def test_install_gpu_detection_distinguishes_blackwell_from_older_nvidia(monkeypatch) -> None:
    installer = _load_install_module()
    outputs = iter(("6.1\n", "12.0\n"))

    monkeypatch.setattr(installer, "find_nvidia_smi", lambda: "nvidia-smi")

    def fake_run(cmd, **kwargs):
        if cmd == ["nvidia-smi"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if cmd == ["nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=next(outputs), stderr="")
        raise AssertionError(f"unexpected command: {cmd!r}")

    monkeypatch.setattr(installer.subprocess, "run", fake_run)

    assert installer.detect_gpu_stack() == "cu121"
    assert installer.detect_gpu_stack() == "cu128"


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
    expected_matplotlib_support = (
        "contourpy==1.2.1",
        "cycler>=0.10",
        "fonttools>=4.22.0",
        "kiwisolver>=1.0.1",
        "packaging>=20.0",
        "pillow>=6.2.0",
        "pyparsing>=2.3.1",
        "python-dateutil>=2.7",
        "importlib-resources>=3.2.0",
    )
    assert any(
        batch.label == "svc py39 matplotlib support"
        and batch.dest == ROOT / "assets" / "wheels" / "svc" / "py39" / "cpu"
        and batch.no_deps
        and batch.packages == expected_matplotlib_support
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
