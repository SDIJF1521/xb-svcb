from __future__ import annotations

import os
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


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


@pytest.mark.skipif(os.name != "nt", reason="Windows cmd.exe detector")
def test_python_detector_accepts_runnable_python_310_or_newer(tmp_path: Path) -> None:
    result = _run_detector(tmp_path, Path(sys.executable))

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"EXE={Path(sys.executable).resolve()}" in result.stdout
    assert f"DIR={Path(sys.executable).resolve().parent}" in result.stdout


@pytest.mark.skipif(os.name != "nt", reason="Windows cmd.exe detector")
def test_python_detector_rejects_an_executable_that_is_not_python(
    tmp_path: Path,
) -> None:
    not_python = Path(os.environ["SystemRoot"]) / "System32" / "where.exe"

    result = _run_detector(tmp_path, not_python)

    assert result.returncode == 1
    assert "EXE=" in result.stdout
    assert str(not_python) not in result.stdout


@pytest.mark.skipif(os.name != "nt", reason="Windows cmd.exe detector")
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


@pytest.mark.skipif(os.name != "nt", reason="Windows cmd.exe detector")
def test_python_detector_rejects_directory_named_python_exe(tmp_path: Path) -> None:
    candidate = tmp_path / "python.exe"
    candidate.mkdir()
    result = _run_detector(tmp_path, candidate)
    assert result.returncode == 1
    assert "EXE=\n" in result.stdout


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
    assert "UVR Python 不可运行" in script
    assert 'if defined XB_PYTHON_DIR if exist "%XB_PYTHON_DIR%\\python.exe" set "XB_PYTHON_EXE=' not in prereqs


def test_installer_detects_and_locks_an_external_python310() -> None:
    script = INSTALLER_SCRIPT.read_text(encoding="utf-8")
    build = (ROOT / "installer" / "build.ps1").read_text(encoding="utf-8")
    build_all = (ROOT / "installer" / "build-all-packages.ps1").read_text(encoding="utf-8")
    detector = DETECTOR.read_text(encoding="utf-8")

    assert 'Source: "..\\assets\\tools\\python310\\*"' not in script
    assert "PythonPathPage := CreateInputFilePage(" in script
    assert "PythonPathPage.Values[0] := DetectPython310Executable();" in script
    assert "sys.version_info[:2] == (3, 10)" in script
    assert "BatchEscape(SelectedPython)" in script
    assert "PathJoin(AppDir, 'tools\\python310\\python.exe')" not in script
    assert "[string]$Python" in build
    assert "Resolve-BuildPython310 $Python" in build
    assert "[string]$Python" in build_all
    assert "py.exe may exist without a registered 3.10 runtime" in build
    assert "& $BuildScript -Python $BuildPython @buildArgs" in build_all
    assert "py -3.10" in detector
    assert "sys.version_info[:2] == (3, 10)" in detector


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


def test_cuda_installer_repairs_keep_the_shared_runtime_layout() -> None:
    setup_env = (ROOT / "setup_env.bat").read_text(encoding="utf-8")
    inno = INSTALLER_SCRIPT.read_text(encoding="utf-8")

    assert 'set "XB_RUNTIME_LAYOUT=' in inno
    assert "RuntimeLayout := 'shared'" in inno
    assert 'if /I "%XB_RUNTIME_LAYOUT%"=="shared"' in setup_env
    assert 'set "XB_RUNTIME_STACK_ARG=--cu126"' in setup_env
    assert 'set "XB_RUNTIME_STACK_ARG=--cu128"' in setup_env
    assert "%XB_RUNTIME_STACK_ARG% %*" in setup_env


def test_default_single_package_build_is_cuda128_shared() -> None:
    build = (ROOT / "installer" / "build.ps1").read_text(encoding="utf-8")
    inno = INSTALLER_SCRIPT.read_text(encoding="utf-8")

    assert "@('cu128')" in build
    assert '#define XB_PACKAGE_STACK "cu128"' in inno
    assert '#define XB_OUTPUT_BASENAME "XB-SVCB-Setup-CUDA128"' in inno


def test_installer_batch_entrypoints_use_windows_line_endings() -> None:
    for relative in (
        "setup_env.bat",
        "setup_shared_env.bat",
        "install_prereqs.bat",
        "install/detect_python.bat",
    ):
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

    assert installer.python_spec_for_venv("uv", "3.10") == str(py310)
    assert installer.python_spec_for_venv("uv", "3.9") == "3.9"


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

    assert installer.python_spec_for_venv("uv", "3.10") == "3.10"


def test_all_release_stacks_use_the_locked_python310_interpreter() -> None:
    installer = _load_install_module()

    for stack in ("cpu", "directml", "cu126", "cu128"):
        assert installer._svc_python_for_stack(stack) == "3.10"
        assert installer._rvc_python_for_stack(stack) == "3.10"


def test_consolidated_runtime_layout_uses_two_shared_environments(tmp_path: Path, monkeypatch) -> None:
    installer = _load_install_module()
    monkeypatch.setattr(installer, "ROOT", tmp_path)
    monkeypatch.setattr(installer, "RUNTIMES_DIR", tmp_path / "runtimes")
    monkeypatch.setattr(installer, "RUNTIME_MANIFEST", tmp_path / "runtime.json")
    monkeypatch.setattr(installer, "UVR_VENV", tmp_path / ".venv-uvr")
    installer._configure_runtime_layout(consolidated=True, gpu_stack="cu126")

    core = tmp_path / "runtimes" / "core-cu126"
    svc = tmp_path / "runtimes" / "svc-cu126"
    assert installer.runtime_venv("uvr", tmp_path / ".venv-uvr") == core
    assert installer.runtime_venv("seedvc", tmp_path / ".venv-seedvc") == core
    assert installer.runtime_venv("ddsp", tmp_path / ".venv-ddsp") == core
    assert installer.runtime_venv("vocal", tmp_path / ".venv-vocal") == svc
    assert installer.runtime_venv("rvc", tmp_path / ".venv-rvc") == svc

    core_python = core / "Scripts" / "python.exe"
    core_python.parent.mkdir(parents=True)
    core_python.write_text("", encoding="ascii")
    installer.write_runtime_manifest("cu126", {"uvr", "seedvc", "ddsp"})
    payload = (tmp_path / "runtime.json").read_text(encoding="utf-8")
    assert "runtimes/core-cu126" in payload


def test_consolidated_runtime_is_disabled_for_directml() -> None:
    installer = _load_install_module()
    installer._configure_runtime_layout(consolidated=True, gpu_stack="directml")
    assert installer.CONSOLIDATED_RUNTIME is False


def test_cu128_nonconsolidated_mode_keeps_legacy_engine_environments(tmp_path: Path) -> None:
    installer = _load_install_module()
    installer._derive_paths(tmp_path)

    installer._configure_runtime_layout(consolidated=False, gpu_stack="cu128")

    assert installer.SVC_VENV == tmp_path / ".venv-svc"
    assert installer.RVC_VENV == tmp_path / ".venv-rvc"
    assert installer.VOCAL_VENV == tmp_path / ".venv-vocal"
    assert installer.SVC_VENV != installer.CORE_VENV
    assert installer.RVC_VENV != installer.CORE_VENV


def test_isolated_route_merge_preserves_core_routes(tmp_path: Path) -> None:
    installer = _load_install_module()
    installer._derive_paths(tmp_path)
    core = tmp_path / "runtimes" / "core-cu128" / "Scripts" / "python.exe"
    svc = tmp_path / "runtimes" / "svc-cu128" / "Scripts" / "python.exe"
    core.parent.mkdir(parents=True)
    svc.parent.mkdir(parents=True)
    core.touch()
    svc.touch()
    installer.RUNTIME_MANIFEST.write_text(json.dumps({
        "version": 1,
        "layout": "consolidated",
        "stack": "cu128",
        "python": {"seedvc": "runtimes/core-cu128/Scripts/python.exe"},
    }), encoding="utf-8")

    installer.update_runtime_manifest_routes("cu128", {"svc": svc})

    payload = json.loads(installer.RUNTIME_MANIFEST.read_text(encoding="utf-8"))
    assert payload["layout"] == "consolidated"
    assert payload["python"]["seedvc"] == "runtimes/core-cu128/Scripts/python.exe"
    assert payload["python"]["svc"] == "runtimes/svc-cu128/Scripts/python.exe"


def test_fetch_sovits_preserves_pretrain_when_source_is_missing(tmp_path: Path, monkeypatch) -> None:
    installer = _load_install_module()
    installer._derive_paths(tmp_path)
    model = installer.PRETRAIN_DIR / "keep.pt"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"model")

    monkeypatch.setattr(installer, "have", lambda name: name == "git")

    def fake_run(command, cwd=None, env=None):
        staging = Path(command[-1])
        marker = staging / "inference" / "infer_tool.py"
        marker.parent.mkdir(parents=True)
        marker.write_text("# source", encoding="utf-8")

    monkeypatch.setattr(installer, "run", fake_run)
    installer.fetch_sovits()

    assert model.read_bytes() == b"model"
    assert (installer.SOVITS_DIR / "inference" / "infer_tool.py").is_file()


def test_consolidated_runtime_selects_py310_uvr_as_candidate(tmp_path: Path, monkeypatch) -> None:
    installer = _load_install_module()
    uvr = tmp_path / ".venv-uvr"
    python = uvr / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="ascii")
    monkeypatch.setattr(installer, "UVR_VENV", uvr)
    monkeypatch.setattr(installer, "_python_minor_version", lambda path: "3.10")

    installer._configure_runtime_layout(consolidated=True, gpu_stack="cu128")

    assert installer.CORE_VENV == uvr
    assert installer.CORE_VENV_REUSED is True


def _shared_fixture(tmp_path, monkeypatch):
    installer = _load_install_module()
    installer._derive_paths(tmp_path)
    installer._configure_runtime_layout(consolidated=True, gpu_stack="cu128")
    for directory in (installer.SEEDVC_DIR, installer.DDSP_DIR):
        directory.mkdir(parents=True)
        (directory / "requirements.txt").write_text("numpy==1.26.4\n", encoding="utf-8")
    monkeypatch.setattr(installer, "_wheelhouse_dirs", lambda **kwargs: [])
    return installer


def test_shared_manifest_partial_install_does_not_activate(tmp_path, monkeypatch):
    installer = _shared_fixture(tmp_path, monkeypatch)
    installer.write_runtime_manifest("cu128", {"uvr"})
    assert not installer.RUNTIME_MANIFEST.exists()


def test_shared_manifest_preserves_other_components_and_invalid_files(tmp_path, monkeypatch):
    installer = _shared_fixture(tmp_path, monkeypatch)
    python = installer.venv_python(installer.CORE_VENV)
    python.parent.mkdir(parents=True)
    python.touch()
    installer.RUNTIME_MANIFEST.write_text(json.dumps({
        "version": 1, "custom": "keep", "python": {"plugins": "plugins/python.exe"},
    }), encoding="utf-8")
    installer.write_runtime_manifest("cu128", installer.CORE_COMPONENTS)
    payload = json.loads(installer.RUNTIME_MANIFEST.read_text(encoding="utf-8"))
    assert payload["custom"] == "keep"
    assert payload["python"]["plugins"] == "plugins/python.exe"
    assert payload["python"]["uvr"] == "runtimes/core-cu128/Scripts/python.exe"
    installer.RUNTIME_MANIFEST.write_text("[]", encoding="utf-8")
    with pytest.raises(RuntimeError):
        installer.write_runtime_manifest("cu128", installer.CORE_COMPONENTS)
    assert installer.RUNTIME_MANIFEST.read_text(encoding="utf-8") == "[]"


def test_shared_preflight_only_compiles_and_preserves_source_requirements(tmp_path, monkeypatch):
    installer = _shared_fixture(tmp_path, monkeypatch)
    commands = []

    def fake_run(command):
        commands.append(command)
        assert command[1:3] == ["pip", "compile"]
        combined = Path(command[3]).read_text(encoding="utf-8")
        assert "audio-separator[gpu]==0.44.2" in combined
        assert "torch==2.7.1+cu128" in combined
        assert "torchvision==0.22.1+cu128" in combined
        assert "numpy==1.26.4" in combined
        Path(command[command.index("--output-file") + 1]).write_text("numpy==1.26.4\n")

    monkeypatch.setattr(installer, "run", fake_run)
    installer._preflight_consolidated_runtime("uv", installer.CORE_COMPONENTS, "cu128")
    assert len(commands) == 1
    assert installer.CORE_CONSTRAINTS.is_file()
    assert not installer.RUNTIME_MANIFEST.exists()
    assert not installer.CORE_VENV.exists()
    assert not (installer.SEEDVC_DIR / "requirements_xb.txt").exists()


def test_shared_preflight_rejects_partial_groups(tmp_path, monkeypatch):
    installer = _shared_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(installer, "run", lambda cmd: pytest.fail("unexpected install"))
    with pytest.raises(RuntimeError, match="一起验证"):
        installer._preflight_consolidated_runtime("uv", {"uvr"}, "cu128")


def test_main_stops_before_install_on_shared_resolution_failure(tmp_path, monkeypatch):
    installer = _shared_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(installer.sys, "argv", ["install.py", "--cpu", "--consolidated", "--only", "uvr", "seedvc", "ddsp"])
    monkeypatch.setattr(installer, "ensure_uv", lambda: "uv")
    monkeypatch.setattr(installer, "STEPS", {name: lambda *args: pytest.fail("environment mutated")
                                            for name in installer.ORDER})

    def fail_compile(command):
        assert command[1:3] == ["pip", "compile"]
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(installer, "run", fail_compile)
    assert installer.main() == 1
    assert not installer.CORE_VENV.exists()
    assert installer.CORE_CONSTRAINTS is None
    assert not installer.RUNTIME_MANIFEST.exists()


def test_legacy_repair_cannot_modify_shared_uvr(tmp_path, monkeypatch):
    installer = _shared_fixture(tmp_path, monkeypatch)
    installer._configure_runtime_layout(consolidated=False, gpu_stack="cu128")
    installer.RUNTIME_MANIFEST.write_text(json.dumps({"version": 1, "python": {
        name: ".venv-uvr/Scripts/python.exe" for name in installer.CORE_COMPONENTS
    }}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="不能单独修复"):
        installer._guard_shared_runtime_repair({"uvr"})
    with pytest.raises(RuntimeError, match="不能单独修复"):
        installer._guard_shared_runtime_repair({"seedvc"})
    with pytest.raises(RuntimeError, match="不能单独修复"):
        installer._guard_shared_runtime_repair({"ddsp"})
    installer._guard_shared_runtime_repair({"models"})


def test_correct_importable_torch_is_not_reinstalled(monkeypatch):
    installer = _load_install_module()
    monkeypatch.setattr(installer, "_torch_runtime_matches", lambda *args: True)
    monkeypatch.setattr(installer, "uv_pip_install", lambda *args, **kwargs: pytest.fail("Torch reinstalled"))
    installer._reaffirm_torch_wheels("uv", "python", ["torch==2.7.1", "torchaudio==2.7.1"],
                                    installer.TORCH_BLACKWELL_INDEX, "cu128",
                                    component="uvr", gpu_stack="cu128", python_version="3.10")


def test_torch_import_check_requires_exact_cuda_build(monkeypatch):
    installer = _load_install_module()

    def fake_run(command, **kwargs):
        assert json.loads(command[-1]) == {"torch": "2.7.1+cu128", "torchaudio": "2.7.1+cu128"}
        assert "import_module" in command[2]
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(installer.subprocess, "run", fake_run)
    assert installer._torch_runtime_matches("python", ["torch==2.7.1", "torchaudio==2.7.1+cu128"], "cu128")


def test_shared_install_retries_keep_constraints_without_reinstall(tmp_path, monkeypatch):
    installer = _shared_fixture(tmp_path, monkeypatch)
    lock = tmp_path / "core.txt"
    lock.write_text("torch==2.7.1+cu128\n")
    installer.CORE_CONSTRAINTS = lock
    monkeypatch.setattr(installer, "_wheelhouse_args", lambda **kwargs: [])
    calls = []

    def fail(command):
        calls.append(command)
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(installer, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        installer.uv_pip_install("uv", "python", "numpy", component="seedvc", gpu_stack="cu128", python_version="3.10")
    assert calls
    assert len(calls) <= 2
    for command in calls:
        assert "--reinstall" not in command
        assert command[command.index("-c") + 1] == str(lock)


def test_inno_routes_by_manifest_not_leftover_core_directory():
    script = INSTALLER_SCRIPT.read_text(encoding="utf-8")
    function = script[script.index("function RuntimePython("):script.index("function ValidateUvrRuntime(")]
    assert "runtime_manifest.py" in function
    assert "GpuStackName()" not in function
    assert "runtimes\\core-" not in function


def test_large_bundled_model_reuses_same_volume_storage(tmp_path: Path, monkeypatch) -> None:
    installer = _load_install_module()
    assets = tmp_path / "assets"
    source = assets / "pretrain" / "large.pt"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"x" * (32 * 1024 * 1024))
    monkeypatch.setattr(installer, "ASSETS_MODELS_DIR", assets)

    destination = tmp_path / "runtime" / "large.pt"
    assert installer.copy_bundled("pretrain/large.pt", destination)
    assert destination.is_file()
    assert source.samefile(destination)


def test_same_size_different_model_is_preserved(tmp_path, monkeypatch):
    installer = _load_install_module()
    monkeypatch.setattr(installer, "ASSETS_MODELS_DIR", tmp_path / "assets")
    monkeypatch.setattr(installer, "_is_large_model_file", lambda path: True)
    source = installer.ASSETS_MODELS_DIR / "model.pt"
    source.parent.mkdir()
    source.write_bytes(b"original")
    destination = tmp_path / "model.pt"
    destination.write_bytes(b"modified")
    assert installer.copy_bundled("model.pt", destination)
    assert destination.read_bytes() == b"modified"
    assert not source.samefile(destination)


def test_directory_redeployment_detaches_existing_hardlink(tmp_path, monkeypatch):
    installer = _load_install_module()
    monkeypatch.setattr(installer, "ASSETS_MODELS_DIR", tmp_path / "assets")
    source = installer.ASSETS_MODELS_DIR / "group" / "model.pt"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"new bundled data")
    destination = tmp_path / "deployed"
    destination.mkdir()
    original = tmp_path / "old-payload.pt"
    original.write_bytes(b"old")
    os.link(original, destination / "model.pt")
    assert installer.copy_bundled("group", destination)
    assert original.read_bytes() == b"old"
    assert (destination / "model.pt").read_bytes() == source.read_bytes()
    assert not original.samefile(destination / "model.pt")


def test_model_hardlink_failure_falls_back_to_copy(tmp_path, monkeypatch):
    installer = _load_install_module()
    source = tmp_path / "source.pt"
    destination = tmp_path / "target.pt"
    source.write_bytes(b"weights")

    def cannot_link(*args):
        raise OSError("Cross-device link")

    monkeypatch.setattr(installer.os, "link", cannot_link)
    installer._link_or_copy_model(source, destination)
    assert destination.read_bytes() == b"weights"
    assert not source.samefile(destination)
    assert not list(tmp_path.glob(".xb-model-*"))


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
        lambda uv, version: r"C:\Python310\python.exe",
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

    assert 'Source: "..\\.tmp\\installer-wheelhouse\\*"' in script
    assert "assets\\wheels\\wheelhouse.json" in script
    assert 'set "XB_WHEELHOUSE=' in script
    assert 'set "XB_WHEELHOUSE_STRICT=1"' in script
    assert 'set "XB_WHEELHOUSE=%~dp0assets\\wheels"' in setup_env
    assert 'set "XB_WHEELHOUSE=%~dp0assets\\wheels"' in prereqs
    assert "--no-index --find-links" in prereqs
    assert "install\\prepare_wheelhouse.py" in build
    assert "installer\\stage_wheelhouse.py" in build
    assert '"/DXB_PACKAGE_STACK=$packageStack"' in build
    assert '[string]($selectedStacks[0])' in build
    assert '[string]$selectedStacks[0]' not in build
    assert '[string]($outputBaseNames[$packageStack])' in build
    assert '[string]($outputBaseNames[$validateStack])' in build
    assert '[string]$outputBaseNames[' not in build
    assert "--clean" in build
    assert "assets\\wheels\\wheelhouse.json" in build
    assert "CleanupBundledWheelhouse();" in script
    assert "if DelTree(WheelhouseDir, True, True, True) then" in script
    assert 'set "XB_WHEELHOUSE="' in setup_env
    assert 'set "XB_WHEELHOUSE_STRICT=0"' in setup_env


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
    monkeypatch.setattr(wheelhouse, "_python_works", lambda py: py == tool_py)
    monkeypatch.setattr(wheelhouse, "_ensure_pip", lambda py: ensured.append(py))
    monkeypatch.setattr(wheelhouse, "_run", lambda cmd: commands.append(cmd))

    result = wheelhouse._ensure_tool_python(tmp_path, Installer)

    assert result == tool_py
    assert ensured == [tool_py]
    assert commands == []


def test_wheelhouse_tool_python_recreates_stale_venv(
    tmp_path: Path, monkeypatch
) -> None:
    wheelhouse = _load_wheelhouse_module()
    venv = tmp_path / ".tmp" / "wheelhouse-tools"
    tool_py = venv / "Scripts" / "python.exe"
    tool_py.parent.mkdir(parents=True)
    tool_py.write_bytes(b"stale")
    (venv / "pyvenv.cfg").write_text(
        "home = C:\\removed\\python310\nversion = 3.10.21\n",
        encoding="utf-8",
    )
    commands: list[list[str]] = []
    ensured: list[Path] = []

    def python_works(py: Path) -> bool:
        return py == tool_py and py.exists() and py.read_bytes() == b"recreated"

    def run(command: list[str]) -> None:
        commands.append(command)
        if command[:3] == [sys.executable, "-m", "venv"]:
            tool_py.parent.mkdir(parents=True)
            tool_py.write_bytes(b"recreated")

    monkeypatch.setattr(wheelhouse, "_TOOL_PYTHON", None)
    monkeypatch.setattr(wheelhouse, "_python_works", python_works)
    monkeypatch.setattr(wheelhouse, "_ensure_pip", lambda py: ensured.append(py))
    monkeypatch.setattr(wheelhouse, "_run", run)

    result = wheelhouse._ensure_tool_python(tmp_path, object())

    assert result == tool_py
    assert commands == [[sys.executable, "-m", "venv", str(venv)]]
    assert ensured == [tool_py]
    assert not (venv / "pyvenv.cfg").exists()


def test_wheelhouse_build_python_recreates_stale_matching_version(
    tmp_path: Path, monkeypatch
) -> None:
    wheelhouse = _load_wheelhouse_module()
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    venv = tmp_path / ".tmp" / "wheelhouse-build-envs" / f"py{version.replace('.', '')}"
    build_py = venv / "Scripts" / "python.exe"
    build_py.parent.mkdir(parents=True)
    build_py.write_bytes(b"stale")
    commands: list[list[str]] = []

    def python_works(py: Path) -> bool:
        return py == build_py and py.exists() and py.read_bytes() == b"recreated"

    def run(command: list[str]) -> None:
        commands.append(command)
        if command[:3] == [sys.executable, "-m", "venv"]:
            build_py.parent.mkdir(parents=True)
            build_py.write_bytes(b"recreated")

    monkeypatch.setattr(wheelhouse, "_BUILD_PYTHONS", {})
    monkeypatch.setattr(wheelhouse, "_python_works", python_works)
    monkeypatch.setattr(wheelhouse, "_ensure_pip", lambda _py: None)
    monkeypatch.setattr(wheelhouse, "_run", run)

    class Installer:
        PYPI_MIRROR = ""
        PYPI_FALLBACK_INDEX = "https://example.invalid/simple"

    result = wheelhouse._ensure_build_python(tmp_path, Installer, version)

    assert result == build_py
    assert commands[0] == [sys.executable, "-m", "venv", str(venv)]
    assert commands[1][:6] == [str(build_py), "-m", "pip", "install", "--upgrade", "pip==24.0"]


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
        tmp_path / "assets" / "wheels" / "svc" / "py310" / "cpu",
        "3.10",
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

    for stack in ("cpu", "directml", "cu126", "cu128"):
        pip_calls.clear()
        make_pip_calls.clear()
        installer.step_pymss("uv", stack)

        expected_pymss_stack = stack
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
    caps = iter(("6.1\n", "12.0\n"))
    names = iter(("NVIDIA GeForce RTX 4090\n", "NVIDIA GeForce RTX 5060 Ti\n"))

    monkeypatch.setattr(installer, "find_nvidia_smi", lambda: "nvidia-smi")

    def fake_run(cmd, **kwargs):
        if cmd == ["nvidia-smi"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if cmd == ["nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=next(caps), stderr="")
        if cmd == ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=next(names), stderr="")
        raise AssertionError(f"unexpected command: {cmd!r}")

    monkeypatch.setattr(installer.subprocess, "run", fake_run)

    assert installer.detect_gpu_stack() == "cu126"
    assert installer.detect_gpu_stack() == "cu128"
