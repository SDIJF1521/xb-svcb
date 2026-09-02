"""运行时安装程序在两个运行时需要不兼容的 PyTorch 版本时，
会使用共享的 ``assets/wheels/<py tag>/<stack>`` 文件夹，
以及组件文件夹（如 ``assets/wheels/rvc/py310/cpu`` 或
``assets/wheels/pymss/py310/cu126``）。
此脚本在发布构建器上运行，下载或构建每种支持的 Python/GPU
组合对应的 Windows 轮子，并生成一个清单文件，与模型一起打包到 Inno Setup 中。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import sysconfig
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WHEELHOUSE = ROOT / "assets" / "wheels"
TMP_REQS = ROOT / ".tmp" / "wheelhouse-requirements"
PLATFORM = "win_amd64"
IMPLEMENTATION = "cp"
PYPI_OFFICIAL_INDEX = "https://pypi.org/simple"
BUILD_VENVS = ROOT / ".tmp" / "wheelhouse-build-envs"


@dataclass(frozen=True)
class DownloadBatch:
    label: str
    dest: Path
    python_version: str
    packages: tuple[str, ...] = ()
    requirements: Path | None = None
    index: str | None = None
    build_source: bool = False
    no_deps: bool = False
    binary_only: bool = False
    constraints: tuple[str, ...] = ()


def _load_installer(root: Path):
    installer_path = root / "install" / "install.py"
    spec = importlib.util.spec_from_file_location("xb_runtime_installer", installer_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load installer module: {installer_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._derive_paths(root)  # noqa: SLF001 - reuse the release install plan.
    return module


def _py_digits(python_version: str) -> str:
    return python_version.replace(".", "")


def _wheelhouse_dir(root: Path, python_version: str, stack: str) -> Path:
    return root / "assets" / "wheels" / f"py{_py_digits(python_version)}" / stack


def _component_wheelhouse_dir(root: Path, component: str, python_version: str, stack: str) -> Path:
    return root / "assets" / "wheels" / component / f"py{_py_digits(python_version)}" / stack


def _copy_filtered_req(installer, source: Path, name: str, **kwargs) -> Path:
    # Keep planning isolated from both upstream sources and other build roots.
    destination = installer.ROOT / ".tmp" / "wheelhouse-requirements" / f"{name}.txt"
    destination.parent.mkdir(parents=True, exist_ok=True)
    return installer._filter_requirements(source, output=destination, **kwargs)  # noqa: SLF001


def missing_engine_requirements(root: Path) -> dict[str, tuple[Path, ...]]:
    candidates = {
        "so-vits-svc": (root / "engines/so-vits-svc/requirements_win.txt",
                        root / "engines/so-vits-svc/requirements.txt"),
        "seed-vc": (root / "engines/seed-vc/requirements.txt",),
        "ddsp-svc": (root / "engines/ddsp-svc/requirements.txt",),
    }
    return {name: paths for name, paths in candidates.items() if not any(p.is_file() for p in paths)}


def _existing_req(installer, *candidates: Path) -> Path:
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError(
        "Missing engine requirements file. Stage bundled engine sources before preparing wheels. "
        "Searched: " + ", ".join(str(path) for path in candidates)
    )


def _reqs(installer) -> dict[str, Path]:
    svc_req = _existing_req(
        installer,
        installer.SOVITS_DIR / "requirements_win.txt",
        installer.SOVITS_DIR / "requirements.txt",
    )
    seedvc_req = _existing_req(installer, installer.SEEDVC_DIR / "requirements.txt")
    ddsp_req = _existing_req(installer, installer.DDSP_DIR / "requirements.txt")
    return {
        "svc-cpu": _copy_filtered_req(
            installer,
            svc_req,
            "svc-cpu",
            overrides=installer.PYTHON310_REQ_OVERRIDES,
        ),
        "svc-directml": _copy_filtered_req(
            installer,
            svc_req,
            "svc-directml",
            extra_deny=installer.DIRECTML_EXTRA_DENY,
            overrides=installer.PYTHON310_REQ_OVERRIDES,
        ),
        "svc-cu128": _copy_filtered_req(
            installer,
            svc_req,
            "svc-cu128",
            extra_deny=installer.BLACKWELL_EXTRA_DENY,
            overrides=installer.PYTHON310_REQ_OVERRIDES,
        ),
        "svc-cu126": _copy_filtered_req(
            installer,
            svc_req,
            "svc-cu126",
            extra_deny=installer.BLACKWELL_EXTRA_DENY,
            overrides=installer.PYTHON310_REQ_OVERRIDES,
        ),
        "seedvc": _copy_filtered_req(
            installer,
            seedvc_req,
            "seedvc",
            extra_deny=installer.SEEDVC_REQ_DENY,
        ),
        "ddsp": _copy_filtered_req(
            installer,
            ddsp_req,
            "ddsp",
            extra_deny=installer.DDSP_REQ_DENY,
            overrides=installer.DDSP_REQ_OVERRIDES,
        ),
        "ddsp-directml": _copy_filtered_req(
            installer,
            ddsp_req,
            "ddsp-directml",
            extra_deny=installer.DDSP_REQ_DENY | installer.DIRECTML_EXTRA_DENY,
            overrides=installer.DDSP_REQ_OVERRIDES,
        ),
    }


def _core_profile_download_requirements(installer) -> Path:
    """Create the public-index portion of the fixed cu128 core lock."""
    recipe = installer._recipe_module()  # noqa: SLF001
    profile, pins = recipe.load_profile()
    provided = {"torch", "torchaudio", "torchvision"}
    for artifact in profile["artifacts"]:
        if artifact["group"] not in {"candidate", "compat"}:
            continue
        filename = Path(artifact["path"]).name.lower()
        matches = [
            name
            for name, version in pins.items()
            if filename.startswith(f"{name.replace('-', '_')}-{version}".lower())
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Cannot map profile artifact to one locked distribution: {artifact['path']}"
            )
        provided.add(matches[0])

    lock = recipe.contained(recipe.PROFILE_DIR, profile["lock"])
    lines: list[str] = []
    for raw in lock.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            lines.append(raw)
            continue
        name = installer._normalized_dist_name(stripped.split("==", 1)[0])  # noqa: SLF001
        if name not in provided:
            lines.append(stripped)
    destination = (
        installer.ROOT
        / ".tmp"
        / "wheelhouse-requirements"
        / "core-cu128-profile.txt"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination


def _torch_specs(installer, stack: str, version: str) -> tuple[tuple[str, ...], str]:
    packages = (f"torch=={version}", f"torchaudio=={version}")
    if stack == "cu128":
        return packages, installer.TORCH_BLACKWELL_INDEX
    if stack == "cu126":
        return packages, installer.TORCH_PYMSS_CUDA_INDEX
    return packages, installer.TORCH_CPU_INDEX


def _directml_runtime(installer) -> tuple[str, ...]:
    return (
        f"torch-directml=={installer.TORCH_DIRECTML_VER}",
        f"torchaudio=={installer.TORCHAUDIO_DIRECTML_VER}",
    )


def _vocal_deps() -> tuple[str, ...]:
    return (
        "numpy==1.23.5",
        "scipy<1.15",
        "librosa==0.9.2",
        "matplotlib<3.9",
        "torchlibrosa==0.1.0",
        "PyYAML",
        "deepfilternet[soundfile]==0.5.6",
        "pedalboard==0.9.24",
        "praat-parselmouth==0.4.6",
    )


def _seedvc_source_wheels() -> tuple[str, ...]:
    return ("argbind>=0.3.7",)


def _constraints(
    *,
    torch: str | None = None,
    torchaudio: str | None = None,
    torchvision: str | None = None,
    extra: tuple[str, ...] = (),
) -> tuple[str, ...]:
    values = ["setuptools<81", *extra]
    if torch:
        values.append(f"torch=={torch}")
    if torchaudio:
        values.append(f"torchaudio=={torchaudio}")
    if torchvision:
        values.append(f"torchvision=={torchvision}")
    return tuple(values)


def _torch_constraints(stack: str, version: str) -> tuple[str, ...]:
    if version == "2.7.1":
        torchvision = "0.22.1"
    elif version == "2.4.1":
        torchvision = "0.19.1"
    elif version == "2.1.1":
        torchvision = "0.16.1"
    else:
        torchvision = "0.20.1"
    return _constraints(torch=version, torchaudio=version, torchvision=torchvision)


def _directml_constraints(installer) -> tuple[str, ...]:
    return _constraints(
        torch=installer.TORCH_DIRECTML_TORCH_VER,
        torchaudio=installer.TORCHAUDIO_DIRECTML_VER,
        torchvision="0.19.1",
        extra=(f"torch-directml=={installer.TORCH_DIRECTML_VER}",),
    )


def _pymss_batches(root: Path, installer, stack: str) -> list[DownloadBatch]:
    """Build PyMSS in a component wheelhouse with its compatible torch pair."""
    py = installer.PYTHON_FOR_ENGINES
    dest = _component_wheelhouse_dir(root, "pymss", py, stack)
    # PyMSS 2.0.x requires Torch 2.7.1. Pre-Blackwell NVIDIA uses cu126 and
    # Blackwell uses cu128; keep the wheelhouse aligned to the actual runtime
    # stack so offline installs stay deterministic.
    if stack == "cu128":
        runtime_stack = "cu128"
    elif stack == "cu126":
        runtime_stack = "cu126"
    else:
        runtime_stack = "cpu"
    constraints = _constraints(
        torch=installer.PYMSS_TORCH_VER,
        torchaudio=installer.PYMSS_TORCHAUDIO_VER,
    )
    torch_packages, torch_index = _torch_specs(
        installer,
        runtime_stack,
        installer.PYMSS_TORCH_VER,
    )
    return [
        DownloadBatch(
            f"pymss {stack} py310 setuptools",
            dest,
            py,
            ("setuptools<81", "wheel"),
            constraints=constraints,
        ),
        DownloadBatch(
            f"pymss {stack} torch",
            dest,
            py,
            torch_packages,
            index=torch_index,
            constraints=constraints,
        ),
        DownloadBatch(
            f"pymss {stack} package",
            dest,
            py,
            (f"pymss=={installer.PYMSS_VERSION}",),
            constraints=constraints,
        ),
    ]


def _base_batches(root: Path, installer) -> list[DownloadBatch]:
    return [
        DownloadBatch(
            "bootstrap uv",
            root / "assets" / "wheels" / "bootstrap",
            installer.PYTHON_FOR_ENGINES,
            ("uv",),
        )
    ]


def _py310_batches(root: Path, installer, reqs: dict[str, Path], stack: str) -> list[DownloadBatch]:
    py = installer.PYTHON_FOR_ENGINES
    shared_dest = _wheelhouse_dir(root, py, stack)
    common_constraints = _constraints()

    def boot(label: str, dest: Path, constraints: tuple[str, ...]) -> DownloadBatch:
        return DownloadBatch(label, dest, py, ("setuptools<81", "wheel"), constraints=constraints)

    batches: list[DownloadBatch] = []

    if stack == "directml":
        dest = shared_dest
        dml_constraints = _directml_constraints(installer)
        cpu_constraints = _torch_constraints("cpu", "2.5.1")
        ddsp_dest = _component_wheelhouse_dir(root, "ddsp", py, stack)
        vocal_dest = _component_wheelhouse_dir(root, "vocal", py, stack)
        hub_dest = _component_wheelhouse_dir(root, "hub", py, stack)
        batches += [
            boot("directml py310 setuptools", dest, dml_constraints),
            DownloadBatch(
                "uvr directml runtime",
                dest,
                py,
                _directml_runtime(installer),
                constraints=dml_constraints,
            ),
            DownloadBatch(
                "uvr audio-separator dml",
                dest,
                py,
                (f"audio-separator[dml]=={installer.AUDIO_SEPARATOR_VER}",),
                constraints=dml_constraints,
            ),
            DownloadBatch(
                "svc directml runtime",
                dest,
                py,
                _directml_runtime(installer),
                constraints=dml_constraints,
            ),
            DownloadBatch(
                "svc directml source wheels",
                dest,
                py,
                ("fairseq==0.12.2",),
                build_source=True,
                no_deps=True,
                constraints=dml_constraints,
            ),
            DownloadBatch(
                "svc directml requirements",
                dest,
                py,
                requirements=reqs["svc-directml"],
                build_source=True,
                constraints=dml_constraints,
            ),
            DownloadBatch(
                "svc directml extras",
                dest,
                py,
                ("matplotlib==3.7.5", "soundfile"),
                constraints=dml_constraints,
            ),
            DownloadBatch(
                "svc directml fcpe runtime",
                dest,
                py,
                installer.SVC_FCPE_RUNTIME_DEPS,
                constraints=dml_constraints,
            ),
            DownloadBatch(
                "rvc directml runtime",
                dest,
                py,
                _directml_runtime(installer),
                constraints=dml_constraints,
            ),
            DownloadBatch(
                "rvc directml",
                dest,
                py,
                ("rvc-python",),
                build_source=True,
                constraints=dml_constraints,
            ),
            DownloadBatch(
                "seedvc directml runtime",
                dest,
                py,
                _directml_runtime(installer),
                constraints=dml_constraints,
            ),
            DownloadBatch(
                "seedvc directml source wheels",
                dest,
                py,
                _seedvc_source_wheels(),
                build_source=True,
                no_deps=True,
                constraints=dml_constraints,
            ),
            DownloadBatch(
                "seedvc requirements",
                dest,
                py,
                requirements=reqs["seedvc"],
                build_source=True,
                constraints=dml_constraints,
            ),
            boot("ddsp directml py310 setuptools", ddsp_dest, cpu_constraints),
            DownloadBatch(
                "ddsp directml cpu torch",
                ddsp_dest,
                py,
                _torch_specs(installer, "cpu", "2.5.1")[0],
                index=installer.TORCH_CPU_INDEX,
                constraints=cpu_constraints,
            ),
            DownloadBatch(
                "ddsp directml requirements",
                ddsp_dest,
                py,
                requirements=reqs["ddsp-directml"],
                build_source=True,
                constraints=cpu_constraints,
            ),
            boot("vocal directml py310 setuptools", vocal_dest, cpu_constraints),
            DownloadBatch(
                "vocal directml cpu torch",
                vocal_dest,
                py,
                _torch_specs(installer, "cpu", "2.5.1")[0],
                index=installer.TORCH_CPU_INDEX,
                constraints=cpu_constraints,
            ),
            DownloadBatch("vocal directml deps", vocal_dest, py, _vocal_deps(), constraints=cpu_constraints),
            boot("hub directml py310 setuptools", hub_dest, common_constraints),
            DownloadBatch("hub directml deps", hub_dest, py, ("modelscope", "requests", "tqdm"), constraints=common_constraints),
        ]
        batches += _pymss_batches(root, installer, stack)
        return batches

    if stack in {"cu126", "cu128"}:
        torch_version = installer.TORCH_BLACKWELL_VER
    else:
        torch_version = "2.5.1"
    torch_packages, torch_index = _torch_specs(installer, stack, torch_version)
    torch_constraints = _torch_constraints(stack, torch_version)
    audio_extra = "gpu" if stack in {"cu126", "cu128"} else "cpu"
    dest = shared_dest
    batches += [
        boot(f"{stack} py310 setuptools", dest, torch_constraints),
        DownloadBatch("uvr torch", dest, py, torch_packages, index=torch_index, constraints=torch_constraints),
        DownloadBatch(
            f"uvr audio-separator {audio_extra}",
            dest,
            py,
            (f"audio-separator[{audio_extra}]=={installer.AUDIO_SEPARATOR_VER}",),
            index=torch_index if audio_extra == "gpu" else None,
            constraints=torch_constraints,
        ),
    ]
    batches += _pymss_batches(root, installer, stack)
    if stack in {"cu126", "cu128"}:
        batches += [
            DownloadBatch(f"svc {stack} torch", dest, py, torch_packages, index=torch_index, constraints=torch_constraints),
            DownloadBatch(
                f"svc {stack} requirements",
                dest,
                py,
                requirements=reqs[f"svc-{stack}"],
                build_source=True,
                constraints=torch_constraints,
            ),
            DownloadBatch(f"svc {stack} soundfile", dest, py, ("soundfile",), constraints=torch_constraints),
            DownloadBatch(f"svc {stack} matplotlib", dest, py, ("matplotlib==3.8.4",), constraints=torch_constraints),
            DownloadBatch(
                f"svc {stack} fcpe runtime",
                dest,
                py,
                installer.SVC_FCPE_RUNTIME_DEPS,
                constraints=torch_constraints,
            ),
            DownloadBatch(
                f"svc {stack} omegaconf",
                dest,
                py,
                ("omegaconf==2.0.6",),
                build_source=True,
                constraints=torch_constraints,
            ),
            DownloadBatch(
                f"svc {stack} fairseq",
                dest,
                py,
                ("fairseq==0.12.2",),
                build_source=True,
                no_deps=True,
                constraints=torch_constraints,
            ),
            DownloadBatch(f"rvc {stack} torch", dest, py, torch_packages, index=torch_index, constraints=torch_constraints),
            DownloadBatch(f"rvc {stack}", dest, py, ("rvc-python",), build_source=True, constraints=torch_constraints),
        ]
    batches += [
        DownloadBatch("seedvc torch", dest, py, torch_packages, index=torch_index, constraints=torch_constraints),
        DownloadBatch(
            f"seedvc {stack} source wheels",
            dest,
            py,
            _seedvc_source_wheels(),
            build_source=True,
            no_deps=True,
            constraints=torch_constraints,
        ),
        DownloadBatch(
            "seedvc requirements",
            dest,
            py,
            requirements=reqs["seedvc"],
            build_source=True,
            constraints=torch_constraints,
        ),
        DownloadBatch("ddsp torch", dest, py, torch_packages, index=torch_index, constraints=torch_constraints),
        DownloadBatch(
            "ddsp requirements",
            dest,
            py,
            requirements=reqs["ddsp"],
            build_source=True,
            constraints=torch_constraints,
        ),
        DownloadBatch("vocal torch", dest, py, torch_packages, index=torch_index, constraints=torch_constraints),
        DownloadBatch("vocal deps", dest, py, _vocal_deps(), constraints=torch_constraints),
        DownloadBatch("hub deps", dest, py, ("modelscope", "requests", "tqdm"), constraints=common_constraints),
    ]
    if stack == "cu128":
        batches.append(
            DownloadBatch(
                "core cu128 fixed profile",
                dest,
                py,
                requirements=_core_profile_download_requirements(installer),
                no_deps=True,
                binary_only=True,
            )
        )
    return batches


def _cpu_compat_batches(root: Path, installer, reqs: dict[str, Path], stack: str) -> list[DownloadBatch]:
    py = installer.PYTHON_FOR_SVC
    py_tag = f"py{_py_digits(py)}"
    svc_dest = _component_wheelhouse_dir(root, "svc", py, stack)
    rvc_dest = _component_wheelhouse_dir(root, "rvc", py, stack)
    svc_torch, svc_index = _torch_specs(installer, stack, "2.5.1")
    rvc_torch, rvc_index = _torch_specs(installer, stack, "2.1.1")
    svc_constraints = _torch_constraints(stack, "2.5.1")
    rvc_constraints = _torch_constraints(stack, "2.1.1")
    return [
        DownloadBatch(f"svc {stack} {py_tag} setuptools", svc_dest, py, ("setuptools<81", "wheel"), constraints=svc_constraints),
        DownloadBatch(f"svc {py_tag} torch", svc_dest, py, svc_torch, index=svc_index, constraints=svc_constraints),
        DownloadBatch(
            f"svc {py_tag} source wheels",
            svc_dest,
            py,
            ("pyworld==0.3.0", "fairseq==0.12.2"),
            build_source=True,
            no_deps=True,
            constraints=svc_constraints,
        ),
        DownloadBatch(
            f"svc {py_tag} requirements",
            svc_dest,
            py,
            requirements=reqs["svc-cpu"],
            build_source=True,
            constraints=svc_constraints,
        ),
        DownloadBatch(
            f"svc {stack} {py_tag} fcpe runtime",
            svc_dest,
            py,
            installer.SVC_FCPE_RUNTIME_DEPS,
            constraints=svc_constraints,
        ),
        # Keep Matplotlib's import-time dependencies separate because the
        # runtime installs matplotlib with --no-deps to preserve So-VITS'
        # validated NumPy pin.
        DownloadBatch(
            f"svc {py_tag} matplotlib support",
            svc_dest,
            py,
            installer.SVC_MATPLOTLIB_RUNTIME_DEPS,
            no_deps=True,
            constraints=svc_constraints,
        ),
        DownloadBatch(
            f"svc {py_tag} matplotlib",
            svc_dest,
            py,
            ("matplotlib==3.7.5",),
            no_deps=True,
            constraints=svc_constraints,
        ),
        DownloadBatch(f"rvc {stack} {py_tag} setuptools", rvc_dest, py, ("setuptools<81", "wheel"), constraints=rvc_constraints),
        DownloadBatch(f"rvc {py_tag} torch", rvc_dest, py, rvc_torch, index=rvc_index, constraints=rvc_constraints),
        DownloadBatch(
            f"rvc {py_tag} fairseq",
            rvc_dest,
            py,
            ("fairseq==0.12.2",),
            build_source=True,
            no_deps=True,
            constraints=rvc_constraints,
        ),
        DownloadBatch(f"rvc {py_tag}", rvc_dest, py, ("rvc-python",), build_source=True, constraints=rvc_constraints),
    ]


def build_plan(root: Path, stacks: set[str] | None = None) -> list[DownloadBatch]:
    installer = _load_installer(root)
    reqs = _reqs(installer)
    requested = stacks or {"cpu", "directml", "cu126", "cu128"}
    batches = _base_batches(root, installer)
    for stack in ("cpu", "directml", "cu126", "cu128"):
        if stack in requested:
            batches += _py310_batches(root, installer, reqs, stack)
    for stack in ("cpu",):
        if stack in requested:
            batches += _cpu_compat_batches(root, installer, reqs, stack)
    pymss_stacks: list[str] = []
    if "cpu" in requested:
        pymss_stacks.append("cpu")
    if "directml" in requested:
        pymss_stacks.append("directml")
    if "cu126" in requested:
        pymss_stacks.append("cu126")
    if "cu128" in requested:
        pymss_stacks.append("cu128")
    for stack in pymss_stacks:
        batches += _pymss_batches(root, installer, stack)
    return batches


def _pip_index_args(installer, index: str | None) -> list[str]:
    args: list[str] = []
    if index:
        args += ["--index-url", index]
        if installer.PYPI_MIRROR:
            args += ["--extra-index-url", installer.PYPI_MIRROR]
        args += ["--extra-index-url", installer.PYPI_FALLBACK_INDEX]
        args += ["--extra-index-url", PYPI_OFFICIAL_INDEX]
        return args
    if installer.PYPI_MIRROR:
        args += ["--index-url", installer.PYPI_MIRROR]
        args += ["--extra-index-url", installer.PYPI_FALLBACK_INDEX]
        args += ["--extra-index-url", PYPI_OFFICIAL_INDEX]
    else:
        args += ["--index-url", installer.PYPI_FALLBACK_INDEX]
        args += ["--extra-index-url", PYPI_OFFICIAL_INDEX]
    return args


_BUILD_PYTHONS: dict[str, Path] = {}
_TOOL_PYTHON: Path | None = None
_UV_EXE: str | None = None


def _subprocess_env() -> dict[str, str]:
    """Keep setuptools/distutils compatible with the bundled Python 3.10."""
    env = os.environ.copy()
    env.setdefault("SETUPTOOLS_USE_DISTUTILS", "stdlib")
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    env.setdefault("PIP_NO_INPUT", "1")
    return env


def _run(cmd: list[str]) -> None:
    print("$ " + " ".join(str(part) for part in cmd))
    subprocess.run(cmd, check=True, env=_subprocess_env())


def _has_module(py: Path, module: str) -> bool:
    return (
        subprocess.run(
            [str(py), "-c", f"import {module}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            env=_subprocess_env(),
        ).returncode
        == 0
    )


def _ensure_pip(py: Path) -> None:
    if _has_module(py, "pip"):
        return
    _run([str(py), "-m", "ensurepip", "--upgrade"])
    if not _has_module(py, "pip"):
        raise RuntimeError(f"pip is not available for {py}")


def _constraint_file(root: Path, batch: DownloadBatch) -> Path | None:
    if not batch.constraints:
        return None
    tmp_reqs = root / ".tmp" / "wheelhouse-requirements"
    tmp_reqs.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() else "-" for ch in batch.label.lower()).strip("-")
    path = tmp_reqs / f"constraints-{safe}.txt"
    path.write_text("\n".join(batch.constraints) + "\n", encoding="utf-8")
    return path


def _script_dirs() -> list[Path]:
    dirs = [Path(sys.executable).parent, Path(sys.executable).parent / "Scripts"]
    for scheme in ("nt_user", "posix_user", None):
        try:
            value = sysconfig.get_path("scripts", scheme=scheme) if scheme else sysconfig.get_path("scripts")
        except (KeyError, ValueError):
            continue
        if value:
            dirs.append(Path(value))
    unique: list[Path] = []
    for directory in dirs:
        if directory not in unique:
            unique.append(directory)
    return unique


def _find_uv() -> str | None:
    global _UV_EXE
    if _UV_EXE and Path(_UV_EXE).exists():
        return _UV_EXE
    found = shutil.which("uv")
    if found:
        return found
    exe_name = "uv.exe" if os.name == "nt" else "uv"
    for directory in _script_dirs():
        candidate = directory / exe_name
        if candidate.exists():
            return str(candidate)
    return None


def _venv_python(venv: Path) -> Path:
    return venv / "Scripts" / "python.exe" if os.name == "nt" else venv / "bin" / "python"


def _ensure_tool_python(root: Path, _installer) -> Path:
    global _TOOL_PYTHON
    if _TOOL_PYTHON and _TOOL_PYTHON.exists():
        return _TOOL_PYTHON
    venv = root / ".tmp" / "wheelhouse-tools"
    py = _venv_python(venv)
    if not py.exists():
        venv.parent.mkdir(parents=True, exist_ok=True)
        _run([sys.executable, "-m", "venv", str(venv)])
    _ensure_pip(py)
    # 工具环境只负责下载器 / uv 自举，不安装编译用大包，避免 wheelhouse
    # 准备阶段在这里重复下载和导入 numpy、Cython、wheel 等依赖。
    _TOOL_PYTHON = py
    return py


def _ensure_uv(root: Path, installer) -> str:
    global _UV_EXE
    found = _find_uv()
    if found:
        return found
    py = _ensure_tool_python(root, installer)
    _run(
        [
            str(py),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "uv",
            "--disable-pip-version-check",
            *_pip_index_args(installer, None),
        ]
    )
    exe_name = "uv.exe" if os.name == "nt" else "uv"
    candidate = py.parent / exe_name
    if candidate.exists():
        _UV_EXE = str(candidate)
        return _UV_EXE
    found = _find_uv()
    if found:
        _UV_EXE = found
        return found
    raise RuntimeError("uv was installed, but uv executable was not found in the wheelhouse tools environment")


def _ensure_build_python(root: Path, installer, python_version: str) -> Path:
    cached = _BUILD_PYTHONS.get(python_version)
    if cached and cached.exists():
        return cached
    venv = root / ".tmp" / "wheelhouse-build-envs" / f"py{_py_digits(python_version)}"
    py = _venv_python(venv)
    if not py.exists():
        uv = _ensure_uv(root, installer)
        venv.parent.mkdir(parents=True, exist_ok=True)
        _run([uv, "venv", "--python", python_version, str(venv)])
    _ensure_pip(py)
    _run(
        [
            str(py),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "pip==24.0",
            "setuptools<81",
            "wheel",
            "Cython<3",
            "numpy==1.23.5",
            "--disable-pip-version-check",
            *_pip_index_args(installer, None),
        ]
    )
    _BUILD_PYTHONS[python_version] = py
    return py


def _build_wheels(root: Path, installer, batch: DownloadBatch) -> None:
    py = _ensure_build_python(root, installer, batch.python_version)
    batch.dest.mkdir(parents=True, exist_ok=True)
    constraints = _constraint_file(root, batch)
    cmd = [
        str(py),
        "-m",
        "pip",
        "wheel",
        "--wheel-dir",
        str(batch.dest),
        "--prefer-binary",
        "--find-links",
        str(batch.dest),
        "--disable-pip-version-check",
        *_pip_index_args(installer, batch.index),
    ]
    if constraints is not None:
        cmd += ["-c", str(constraints)]
    if batch.no_deps:
        cmd.append("--no-deps")
    if batch.requirements is not None:
        cmd += ["-r", str(batch.requirements)]
    cmd += list(batch.packages)
    _run(cmd)


def _download_batch(root: Path, installer, batch: DownloadBatch) -> None:
    if not batch.packages and batch.requirements is None:
        return
    # Requirement sets default to the wheel builder because upstream engine
    # lists can contain source-only packages. A reviewed frozen lock may opt
    # into the platform-specific binary downloader explicitly.
    if batch.build_source or (batch.requirements is not None and not batch.binary_only):
        print(f"\n==== {batch.label} ====")
        _build_wheels(root, installer, batch)
        return
    py_digits = _py_digits(batch.python_version)
    batch.dest.mkdir(parents=True, exist_ok=True)
    constraints = _constraint_file(root, batch)
    download_py = _ensure_tool_python(root, installer)
    cmd = [
        str(download_py),
        "-m",
        "pip",
        "download",
        "--dest",
        str(batch.dest),
        "--only-binary=:all:",
        "--prefer-binary",
        "--platform",
        PLATFORM,
        "--implementation",
        IMPLEMENTATION,
        "--python-version",
        py_digits,
        "--abi",
        f"cp{py_digits}",
        "--find-links",
        str(batch.dest),
        *_pip_index_args(installer, batch.index),
    ]
    if constraints is not None:
        cmd += ["-c", str(constraints)]
    if batch.no_deps:
        cmd.append("--no-deps")
    if batch.requirements is not None:
        cmd += ["-r", str(batch.requirements)]
    cmd += list(batch.packages)
    print(f"\n==== {batch.label} ====")
    _run(cmd)


def _summarize(root: Path, batches: list[DownloadBatch]) -> dict:
    groups: dict[str, dict] = {}
    wheel_root = root / "assets" / "wheels"
    for batch in batches:
        rel = batch.dest.relative_to(wheel_root).as_posix()
        group = groups.setdefault(
            rel,
            {
                "path": rel,
                "python": batch.python_version,
                "batches": [],
                "wheel_count": 0,
            },
        )
        group["batches"].append(batch.label)
    for group in groups.values():
        path = wheel_root / group["path"]
        group["wheel_count"] = len(list(path.glob("*.whl"))) if path.exists() else 0
    return {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "platform": PLATFORM,
        "layout": (
            "assets/wheels/<py tag>/<stack>/*.whl, component overrides under "
            "assets/wheels/<component>/<py tag>/<stack>/*.whl, and bootstrap/*.whl"
        ),
        "groups": sorted(groups.values(), key=lambda item: item["path"]),
    }


def _write_manifest(root: Path, batches: list[DownloadBatch]) -> None:
    manifest = _summarize(root, batches)
    manifest_path = root / "assets" / "wheels" / "wheelhouse.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    empty = [group["path"] for group in manifest["groups"] if group["wheel_count"] <= 0]
    if empty:
        raise RuntimeError(f"Wheelhouse groups are empty: {', '.join(empty)}")
    print(f"\nWheelhouse manifest written: {manifest_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare XB-SVCB bundled wheels")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root")
    parser.add_argument(
        "--stack",
        action="append",
        choices=("cpu", "directml", "cu126", "cu128"),
        help="prepare only selected stack(s); default prepares all",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the plan without downloading")
    parser.add_argument("--clean", action="store_true", help="remove assets/wheels before downloading")
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    if args.clean and not args.dry_run:
        wheelhouse = root / "assets" / "wheels"
        if wheelhouse.exists():
            shutil.rmtree(wheelhouse)
        # Constraints are generated from the current component/runtime plan.
        # Remove stale files before build_plan creates the filtered requirements.
        stale_requirements = root / ".tmp" / "wheelhouse-requirements"
        if stale_requirements.exists():
            shutil.rmtree(stale_requirements)

    installer = _load_installer(root)
    batches = build_plan(root, set(args.stack or []))
    if args.dry_run:
        plan = [
            {
                "label": batch.label,
                "dest": str(batch.dest.relative_to(root)),
                "python": batch.python_version,
                "index": batch.index,
                "requirements": str(batch.requirements.relative_to(root)) if batch.requirements else None,
                "packages": list(batch.packages),
                "build_source": batch.build_source,
                "no_deps": batch.no_deps,
                "binary_only": batch.binary_only,
                "constraints": list(batch.constraints),
            }
            for batch in batches
        ]
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    wheelhouse = root / "assets" / "wheels"
    wheelhouse.mkdir(parents=True, exist_ok=True)
    for batch in batches:
        _download_batch(root, installer, batch)
    _write_manifest(root, batches)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
