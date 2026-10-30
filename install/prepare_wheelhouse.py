"""运行时安装程序在两个运行时需要不兼容的 PyTorch 版本时，
会使用共享的 ``assets/wheels/<py tag>/<stack>`` 文件夹，
以及组件文件夹（如 ``assets/wheels/rvc/py312/cpu`` 或
``assets/wheels/pymss/py312/cu126``）。
此脚本在发布构建器上运行，下载或构建每种支持的 Python/GPU
组合对应的 Windows 轮子，并生成一个清单文件，与模型一起打包到 Inno Setup 中。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import zipfile
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
STACKS = ("cpu", "rocm10", "directml", "cu126", "cu128")


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
    no_build_isolation: bool = False


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
            extra_deny=installer.DIRECTML_EXTRA_DENY,
            overrides=installer.PYTHON312_REQ_OVERRIDES,
        ),
        "svc-directml": _copy_filtered_req(
            installer,
            svc_req,
            "svc-directml",
            extra_deny=installer.DIRECTML_EXTRA_DENY,
            overrides=installer.PYTHON312_REQ_OVERRIDES,
        ),
        "svc-cu128": _copy_filtered_req(
            installer,
            svc_req,
            "svc-cu128",
            extra_deny=installer.BLACKWELL_EXTRA_DENY,
            overrides=installer.SVC_SHARED_REQ_OVERRIDES,
        ),
        "svc-cu126": _copy_filtered_req(
            installer,
            svc_req,
            "svc-cu126",
            extra_deny=installer.BLACKWELL_EXTRA_DENY,
            overrides=installer.SVC_SHARED_REQ_OVERRIDES,
        ),
        "svc-rocm10": _copy_filtered_req(
            installer, svc_req, "svc-rocm10",
            extra_deny=installer.BLACKWELL_EXTRA_DENY,
            overrides=installer.SVC_SHARED_REQ_OVERRIDES,
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
        "ddsp-legacy": _copy_filtered_req(
            installer, ddsp_req, "ddsp-legacy",
            extra_deny=installer.DDSP_REQ_DENY,
            overrides={**installer.PYTHON312_REQ_OVERRIDES, **installer.DDSP_REQ_OVERRIDES},
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
    if stack == installer.ROCM_STACK:
        return tuple(installer._modern_torch_specs(stack, include_vision=True)), installer.TORCH_ROCM_INDEX
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
        "numpy==1.26.4",
        "scipy<1.15",
        "librosa==0.10.2",
        "matplotlib<3.9",
        "torchlibrosa==0.1.0",
        "PyYAML",
        "packaging==23.2",
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
    elif stack == installer.ROCM_STACK:
        runtime_stack = installer.ROCM_STACK
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
    if stack == installer.ROCM_STACK:
        constraints = _constraints(extra=installer._rocm_constraints())
    return [
        DownloadBatch(
            f"pymss {stack} py312 setuptools",
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


def _vocal_deepfilterlib_batch(dest: Path, py: str, constraints: tuple[str, ...]) -> DownloadBatch:
    """Build DeepFilterLib for the exact CPython ABI used by Vocal.

    DeepFilterLib 0.5.6 publishes Windows wheels only through CPython 3.11;
    CPython 3.12 must use its bundled Rust/maturin source build. Keeping this
    as a separate no-deps batch places the generated wheel in the same local
    directory before pip resolves deepfilternet's runtime dependencies.
    """
    return DownloadBatch(
        "vocal deepfilterlib",
        dest,
        py,
        ("deepfilterlib==0.5.6",),
        build_source=True,
        no_deps=True,
        constraints=constraints,
    )


def _base_batches(root: Path, installer) -> list[DownloadBatch]:
    return [
        DownloadBatch(
            "bootstrap uv",
            root / "assets" / "wheels" / "bootstrap",
            installer.PYTHON_FOR_ENGINES,
            ("uv",),
        )
    ]


def _py312_batches(root: Path, installer, reqs: dict[str, Path], stack: str) -> list[DownloadBatch]:
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
            boot("directml py312 setuptools", dest, dml_constraints),
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
                ("fairseq-fixed==0.12.3.1",),
                build_source=True,
                no_deps=True,
                constraints=dml_constraints,
                no_build_isolation=True,
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
                ("matplotlib==3.8.4", "soundfile"),
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
                ("rvc-python==0.1.5+xb312",),
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
            boot("ddsp directml py312 setuptools", ddsp_dest, dml_constraints),
            DownloadBatch(
                "ddsp directml runtime",
                ddsp_dest,
                py,
                _directml_runtime(installer),
                constraints=dml_constraints,
            ),
            DownloadBatch(
                "ddsp directml requirements",
                ddsp_dest,
                py,
                requirements=reqs["ddsp-directml"],
                build_source=True,
                constraints=dml_constraints,
            ),
            boot("vocal directml py312 setuptools", vocal_dest, cpu_constraints),
            DownloadBatch(
                "vocal directml cpu torch",
                vocal_dest,
                py,
                _torch_specs(installer, "cpu", "2.5.1")[0],
                index=installer.TORCH_CPU_INDEX,
                constraints=cpu_constraints,
            ),
            _vocal_deepfilterlib_batch(vocal_dest, py, cpu_constraints),
            DownloadBatch("vocal directml deps", vocal_dest, py, _vocal_deps(), constraints=cpu_constraints),
            boot("hub directml py312 setuptools", hub_dest, common_constraints),
            DownloadBatch("hub directml deps", hub_dest, py, ("modelscope", "requests", "tqdm"), constraints=common_constraints),
        ]
        return batches

    if stack in {"cu126", "cu128", installer.ROCM_STACK}:
        torch_version = installer.TORCH_BLACKWELL_VER
    else:
        torch_version = "2.5.1"
    torch_packages, torch_index = _torch_specs(installer, stack, torch_version)
    torch_constraints = _torch_constraints(stack, torch_version)
    if stack == installer.ROCM_STACK:
        torch_constraints = _constraints(extra=installer._rocm_constraints())
    audio_extra = "gpu" if stack in {"cu126", "cu128"} else "cpu"
    dest = shared_dest
    batches += [
        boot(f"{stack} py312 setuptools", dest, torch_constraints),
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
    if stack in {"cu126", "cu128", installer.ROCM_STACK}:
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
                ("omegaconf==2.3.0",),
                build_source=True,
                constraints=torch_constraints,
            ),
            DownloadBatch(
                f"svc {stack} fairseq",
                dest,
                py,
                ("fairseq-fixed==0.12.3.1",),
                build_source=True,
                no_deps=True,
                constraints=torch_constraints,
                no_build_isolation=True,
            ),
            DownloadBatch(f"rvc {stack} torch", dest, py, torch_packages, index=torch_index, constraints=torch_constraints),
            DownloadBatch(f"rvc {stack}", dest, py, ("rvc-python==0.1.5+xb312",), build_source=True, constraints=torch_constraints),
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
        _vocal_deepfilterlib_batch(dest, py, torch_constraints),
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
    rvc_torch, rvc_index = _torch_specs(installer, stack, "2.5.1")
    svc_constraints = _torch_constraints(stack, "2.5.1")
    rvc_constraints = _torch_constraints(stack, "2.5.1")
    return [
        DownloadBatch(f"svc {stack} {py_tag} setuptools", svc_dest, py, ("setuptools<81", "wheel"), constraints=svc_constraints),
        DownloadBatch(f"svc {py_tag} torch", svc_dest, py, svc_torch, index=svc_index, constraints=svc_constraints),
        DownloadBatch(
            f"svc {py_tag} source wheels",
            svc_dest,
            py,
            ("pyworld==0.3.5", "fairseq-fixed==0.12.3.1"),
            build_source=True,
            no_deps=True,
            constraints=svc_constraints,
            no_build_isolation=True,
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
            ("matplotlib==3.8.4",),
            no_deps=True,
            constraints=svc_constraints,
        ),
        DownloadBatch(f"rvc {stack} {py_tag} setuptools", rvc_dest, py, ("setuptools<81", "wheel"), constraints=rvc_constraints),
        DownloadBatch(f"rvc {py_tag} torch", rvc_dest, py, rvc_torch, index=rvc_index, constraints=rvc_constraints),
        DownloadBatch(
            f"rvc {py_tag} fairseq",
            rvc_dest,
            py,
            ("fairseq-fixed==0.12.3.1",),
            build_source=True,
            no_deps=True,
            constraints=rvc_constraints,
            no_build_isolation=True,
        ),
        DownloadBatch(f"rvc {py_tag}", rvc_dest, py, ("rvc-python==0.1.5+xb312",), build_source=True, constraints=rvc_constraints),
    ]


def build_plan(root: Path, stacks: set[str] | None = None) -> list[DownloadBatch]:
    installer = _load_installer(root)
    reqs = _reqs(installer)
    requested = stacks or {"cpu", "rocm10", "directml", "cu126", "cu128"}
    batches = _base_batches(root, installer)
    for stack in ("cpu", "rocm10", "directml", "cu126", "cu128"):
        if stack in requested:
            batches += _py312_batches(root, installer, reqs, stack)
            # PyMSS 2.0.x requires Torch 2.7.1, while torch-directml pins
            # Torch 2.4.1. DirectML packages therefore carry the isolated CPU
            # PyMSS runtime instead of omitting PyMSS or mixing incompatible
            # Torch providers in one environment.
            if stack == "directml" and "cpu" not in requested:
                batches += _pymss_batches(root, installer, "cpu")
            if stack == "directml" and "cpu" in requested:
                continue
            legacy_stack = "cpu" if stack == "directml" else stack
            dest = _component_wheelhouse_dir(root, "ddsp-legacy", installer.PYTHON_FOR_ENGINES, legacy_stack)
            version = "2.5.1" if legacy_stack == "cpu" else "2.7.1"
            packages, index = _torch_specs(installer, legacy_stack, version)
            constraints = ("setuptools<81", *installer._rocm_constraints()) if legacy_stack == installer.ROCM_STACK else _torch_constraints(legacy_stack, version)
            batches += [
                DownloadBatch(f"ddsp legacy {stack} torch", dest, installer.PYTHON_FOR_ENGINES, packages, index=index, constraints=constraints),
                DownloadBatch(f"ddsp legacy {stack} requirements", dest, installer.PYTHON_FOR_ENGINES,
                              ("setuptools<81", "wheel", "fairseq-fixed==0.12.3.1", "einops", "local-attention"),
                              requirements=reqs["ddsp-legacy"], build_source=True, constraints=constraints),
            ]
            # Keep CPU compatibility components with the CPU stack. A later
            # GPU-stack failure must not leave an apparently complete CPU
            # wheelhouse without its required SVC/RVC groups.
            if stack == "cpu":
                batches += _cpu_compat_batches(root, installer, reqs, stack)
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
    """Keep setuptools/distutils compatible with the bundled Python 3.12."""
    env = os.environ.copy()
    env["SETUPTOOLS_USE_DISTUTILS"] = "local"
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    env.setdefault("PIP_NO_INPUT", "1")
    return env


def _run(cmd: list[str]) -> None:
    print("$ " + " ".join(str(part) for part in cmd))
    subprocess.run(cmd, check=True, env=_subprocess_env())


def _package_name(spec: str) -> str:
    name = spec.split(";", 1)[0].strip()
    for marker in ("[", "=", "<", ">", "!", "~", "@"):
        name = name.split(marker, 1)[0]
    return name.strip().lower().replace("_", "-")


def _exact_wheel_present(directory: Path, spec: str) -> bool:
    requirement = spec.split(";", 1)[0].strip()
    if "==" not in requirement:
        return False
    version = requirement.split("==", 1)[1].strip().lower().replace("-", "_")
    prefix = _package_name(requirement).replace("-", "_") + "-" + version + "-"
    return any(wheel.name.lower().startswith(prefix) for wheel in directory.glob("*.whl"))


def _is_rocm_torch_batch(batch: DownloadBatch) -> bool:
    names = {_package_name(spec) for spec in batch.packages}
    return bool(names) and names <= {"torch", "torchaudio", "torchvision"}


def _reuse_shared_rocm_wheels(root: Path, batch: DownloadBatch) -> int:
    """Hardlink the completed shared ROCm runtime into component caches."""
    if "rocm10" not in batch.dest.parts:
        return 0
    shared = _wheelhouse_dir(root, batch.python_version, "rocm10")
    if batch.dest.resolve() == shared.resolve() or not shared.is_dir():
        return 0

    sources = sorted(shared.glob("*.whl"))
    if not sources:
        return 0
    batch.dest.mkdir(parents=True, exist_ok=True)
    linked = 0
    for source in sources:
        destination = batch.dest / source.name
        try:
            if destination.exists() and os.path.samefile(source, destination):
                continue
        except OSError:
            pass

        temporary = batch.dest / f".{source.name}.shared.tmp"
        temporary.unlink(missing_ok=True)
        try:
            os.link(source, temporary)
        except OSError:
            shutil.copy2(source, temporary)
        os.replace(temporary, destination)
        linked += 1
    return linked


def _has_module(py: Path, module: str) -> bool:
    try:
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
    except OSError:
        return False


def _python_works(py: Path) -> bool:
    if not py.exists():
        return False
    try:
        return (
            subprocess.run(
                [str(py), "-c", "import sys; raise SystemExit(0)"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                env=_subprocess_env(),
            ).returncode
            == 0
        )
    except OSError:
        return False


def _build_toolchain_ready(py: Path) -> bool:
    check = """
from importlib.metadata import version
from packaging.version import Version
raise SystemExit(0 if (
    Version(version('pip')) == Version('24.0')
    and Version(version('setuptools')) < Version('81')
    and Version(version('Cython')) < Version('3')
    and Version(version('numpy')) == Version('1.26.4')
    and bool(version('wheel'))
) else 1)
"""
    try:
        return subprocess.run(
            [str(py), "-c", check],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            env=_subprocess_env(),
        ).returncode == 0
    except OSError:
        return False


def _remove_broken_temp_venv(root: Path, venv: Path, label: str) -> None:
    if not venv.exists():
        return
    temp_root = (root / ".tmp").resolve()
    resolved = venv.resolve()
    if resolved == temp_root or not resolved.is_relative_to(temp_root):
        raise RuntimeError(f"Refusing to remove {label} outside {temp_root}: {resolved}")
    print(f"[wheelhouse] Recreating stale {label}: {venv}")
    shutil.rmtree(venv)


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
    constraints = list(batch.constraints)
    stack = next((part for part in batch.dest.parts if part in {"cu126", "cu128"}), None)
    torch_pin = next((line.removeprefix("torch==") for line in constraints if line.startswith("torch==")), None)
    if stack and torch_pin:
        py_tag = f"cp{_py_digits(batch.python_version)}"
        local_torch = (
            _wheelhouse_dir(root, batch.python_version, stack)
            / f"torch-{torch_pin}+{stack}-{py_tag}-{py_tag}-{PLATFORM}.whl"
        )
        if local_torch.is_file():
            expected_tag = f"{py_tag}-{py_tag}-{PLATFORM}"
            try:
                with zipfile.ZipFile(local_torch) as archive:
                    wheel_metadata = archive.read(
                        f"torch-{torch_pin}+{stack}.dist-info/WHEEL"
                    ).decode("utf-8")
                    extension = f"torch/_C.{py_tag}-{PLATFORM}.pyd"
                    valid = (
                        f"Tag: {expected_tag}" in wheel_metadata.splitlines()
                        and extension in archive.namelist()
                    )
            except (KeyError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
                raise RuntimeError(f"Invalid local CUDA Torch wheel: {local_torch}") from exc
            if not valid:
                raise RuntimeError(
                    f"Local CUDA Torch wheel has the wrong Python ABI: {local_torch}"
                )
            # An explicit local reference wins over an index wheel with the same version.
            constraints.append(f"torch @ {local_torch.resolve().as_uri()}")
    path.write_text("\n".join(constraints) + "\n", encoding="utf-8")
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
    if _TOOL_PYTHON and _python_works(_TOOL_PYTHON):
        return _TOOL_PYTHON
    _TOOL_PYTHON = None
    venv = root / ".tmp" / "wheelhouse-tools"
    py = _venv_python(venv)
    if venv.exists() and not _python_works(py):
        _remove_broken_temp_venv(root, venv, "wheelhouse tool environment")
    if not _python_works(py):
        venv.parent.mkdir(parents=True, exist_ok=True)
        _run([sys.executable, "-m", "venv", str(venv)])
    if not _python_works(py):
        raise RuntimeError(f"Wheelhouse tool Python could not be created: {py}")
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
    if cached and _python_works(cached):
        return cached
    _BUILD_PYTHONS.pop(python_version, None)
    venv = root / ".tmp" / "wheelhouse-build-envs" / f"py{_py_digits(python_version)}"
    py = _venv_python(venv)
    if venv.exists() and not _python_works(py):
        _remove_broken_temp_venv(root, venv, f"Python {python_version} wheel build environment")
    if not _python_works(py):
        venv.parent.mkdir(parents=True, exist_ok=True)
        current_version = f"{sys.version_info.major}.{sys.version_info.minor}"
        if current_version == python_version:
            _run([sys.executable, "-m", "venv", str(venv)])
        else:
            uv = _ensure_uv(root, installer)
            _run([uv, "venv", "--python", python_version, str(venv)])
    if not _python_works(py):
        raise RuntimeError(f"Python {python_version} wheel build environment could not be created: {py}")
    _ensure_pip(py)
    if not _build_toolchain_ready(py):
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
                "numpy==1.26.4",
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
    if batch.no_build_isolation:
        # pyworld 0.3.0 and fairseq 0.12.2 declare unconstrained NumPy/Cython
        # build requirements. Reuse the pinned toolchain installed above so
        # pip does not create an isolated environment and build a newer NumPy.
        cmd.append("--no-build-isolation")
    if batch.no_deps:
        cmd.append("--no-deps")
    if batch.requirements is not None:
        cmd += ["-r", str(batch.requirements)]
    cmd += list(batch.packages)
    _run(cmd)


def _download_batch(root: Path, installer, batch: DownloadBatch) -> None:
    if not batch.packages and batch.requirements is None:
        return
    reused = _reuse_shared_rocm_wheels(root, batch)
    if reused:
        print(f"[wheelhouse] Reused {reused} shared ROCm wheels in {batch.dest}")
    # Only the Torch runtime itself needs AMD's index. Other ROCm batches use
    # the normal PyPI mirrors and resolve the pinned runtime from --find-links.
    if "rocm10" in batch.dest.parts and batch.index is None and _is_rocm_torch_batch(batch):
        from dataclasses import replace
        batch = replace(batch, index=installer.TORCH_ROCM_INDEX)
    shared_rocm = _wheelhouse_dir(root, batch.python_version, "rocm10")
    if (
        _is_rocm_torch_batch(batch)
        and batch.dest.resolve() != shared_rocm.resolve()
        and all(_exact_wheel_present(batch.dest, spec) for spec in batch.packages)
    ):
        print(f"\n==== {batch.label} ====")
        print("[wheelhouse] Reusing the completed shared ROCm Torch runtime.")
        return
    # AMD publishes ``rocm==10.0.0`` as an sdist-only metadata package.  The
    # ROCm Torch wheels depend on it, but the cross-platform download below is
    # intentionally binary-only and therefore cannot resolve that sdist. Build
    # the tiny pure-Python metadata wheel into each ROCm group before resolving
    # its Torch/dependent packages; subsequent downloads then consume it via
    # --find-links without relaxing the binary-only policy for the rest.
    if "rocm10" in batch.dest.parts and any(
        package.lower().startswith(("torch", "torchaudio", "torchvision"))
        for package in batch.packages
    ):
        rocm_wheel = next(batch.dest.glob("rocm-10.0.0-*.whl"), None)
        if rocm_wheel is None:
            _build_wheels(
                root,
                installer,
                DownloadBatch(
                    "rocm10 runtime metadata",
                    batch.dest,
                    batch.python_version,
                    ("rocm==10.0.0",),
                    index=installer.TORCH_ROCM_INDEX,
                    no_deps=True,
                    build_source=True,
                ),
            )
    if "rvc-python==0.1.5+xb312" in batch.packages:
        spec = importlib.util.spec_from_file_location("xb_rvc_compat_build", Path(__file__).with_name("build_rvc_compat.py"))
        if spec is None or spec.loader is None:
            raise RuntimeError("无法加载 RVC 兼容构建模块")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        indexes = [
            value
            for value in (
                installer.PYPI_MIRROR,
                installer.PYPI_FALLBACK_INDEX,
                PYPI_OFFICIAL_INDEX,
            )
            if value
        ]
        module.prepare(
            batch.dest,
            [batch.dest],
            python=_ensure_tool_python(root, installer),
            index_urls=indexes,
        )
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


def _batch_signature(root: Path, batch: DownloadBatch) -> dict[str, object]:
    requirement: dict[str, str] | None = None
    if batch.requirements is not None:
        requirement = {
            "path": batch.requirements.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(batch.requirements.read_bytes()).hexdigest(),
        }
    return {
        "label": batch.label,
        "dest": batch.dest.relative_to(root).as_posix(),
        "python": batch.python_version,
        "packages": list(batch.packages),
        "requirements": requirement,
        "index": batch.index,
        "build_source": batch.build_source,
        "no_deps": batch.no_deps,
        "binary_only": batch.binary_only,
        "constraints": list(batch.constraints),
        "no_build_isolation": batch.no_build_isolation,
    }


def _plan_signature(root: Path, batches: list[DownloadBatch]) -> str:
    payload = [_batch_signature(root, batch) for batch in batches]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _profile_snapshot(root: Path, stack: str, batches: list[DownloadBatch]) -> dict[str, object]:
    wheel_root = root / "assets" / "wheels"
    groups = sorted({batch.dest.relative_to(wheel_root).as_posix() for batch in batches})
    empty = [group for group in groups if not any((wheel_root / group).glob("*.whl"))]
    if empty:
        raise RuntimeError(f"Wheelhouse groups are empty for {stack}: {', '.join(empty)}")

    wheels: dict[str, int] = {}
    for group in groups:
        for wheel in (wheel_root / group).glob("*.whl"):
            wheels[wheel.relative_to(wheel_root).as_posix()] = wheel.stat().st_size
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "plan_signature": _plan_signature(root, batches),
        "groups": groups,
        "wheel_count": len(wheels),
        "wheel_bytes": sum(wheels.values()),
        "wheels": [
            {"path": path, "size": size}
            for path, size in sorted(wheels.items())
        ],
    }


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
        "schema": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "platform": PLATFORM,
        "layout": (
            "assets/wheels/<py tag>/<stack>/*.whl, component overrides under "
            "assets/wheels/<component>/<py tag>/<stack>/*.whl, and bootstrap/*.whl"
        ),
        "groups": sorted(groups.values(), key=lambda item: item["path"]),
        "profiles": {},
    }


def _read_profiles(manifest_path: Path) -> dict[str, object]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    profiles = manifest.get("profiles") if manifest.get("schema") == 2 else None
    return dict(profiles) if isinstance(profiles, dict) else {}


def _write_manifest(
    root: Path,
    batches: list[DownloadBatch],
    profile_plans: dict[str, list[DownloadBatch]],
) -> None:
    manifest = _summarize(root, batches)
    manifest_path = root / "assets" / "wheels" / "wheelhouse.json"
    profiles = _read_profiles(manifest_path)
    for stack, plan in profile_plans.items():
        profiles[stack] = _profile_snapshot(root, stack, plan)
    manifest["profiles"] = profiles
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, manifest_path)
    empty = [group["path"] for group in manifest["groups"] if group["wheel_count"] <= 0]
    if empty:
        raise RuntimeError(f"Wheelhouse groups are empty: {', '.join(empty)}")
    print(f"\nWheelhouse manifest written: {manifest_path}")


def validate_wheelhouse_profiles(
    root: Path,
    profile_plans: dict[str, list[DownloadBatch]],
) -> list[str]:
    manifest_path = root / "assets" / "wheels" / "wheelhouse.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [f"wheelhouse manifest not found: {manifest_path}"]
    except (json.JSONDecodeError, OSError) as exc:
        return [f"wheelhouse manifest is unreadable: {manifest_path}: {exc}"]
    if manifest.get("schema") != 2 or not isinstance(manifest.get("profiles"), dict):
        return ["wheelhouse manifest has no per-stack completion profiles; rebuild the selected stack"]

    wheel_root = root / "assets" / "wheels"
    errors: list[str] = []
    profiles = manifest["profiles"]
    for stack, plan in profile_plans.items():
        profile = profiles.get(stack)
        if not isinstance(profile, dict):
            errors.append(f"{stack}: completion profile is missing")
            continue
        if profile.get("plan_signature") != _plan_signature(root, plan):
            errors.append(f"{stack}: dependency plan changed after the wheelhouse was prepared")
            continue
        planned_groups = sorted({batch.dest.relative_to(wheel_root).as_posix() for batch in plan})
        if profile.get("groups") != planned_groups:
            errors.append(f"{stack}: recorded wheel groups do not match the current dependency plan")
            continue
        wheels = profile.get("wheels")
        if not isinstance(wheels, list) or not wheels:
            errors.append(f"{stack}: completion profile contains no wheels")
            continue
        for item in wheels:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("size"), int):
                errors.append(f"{stack}: completion profile contains an invalid wheel record")
                break
            relative = Path(item["path"])
            if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".whl":
                errors.append(f"{stack}: completion profile contains an unsafe wheel path: {relative}")
                break
            wheel = wheel_root / relative
            try:
                size = wheel.stat().st_size
            except OSError:
                errors.append(f"{stack}: recorded wheel is missing: {relative.as_posix()}")
                break
            if size != item["size"]:
                errors.append(
                    f"{stack}: recorded wheel size changed: {relative.as_posix()} "
                    f"({size} bytes, expected {item['size']})"
                )
                break
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare XB-SVCB bundled wheels")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root")
    parser.add_argument(
        "--stack",
        action="append",
        choices=("cpu", "rocm10", "directml", "cu126", "cu128"),
        help="prepare only selected stack(s); default prepares all",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the plan without downloading")
    parser.add_argument("--check", action="store_true", help="validate selected stack completion profiles")
    parser.add_argument("--clean", action="store_true", help="remove assets/wheels before downloading")
    parser.add_argument(
        "--from-batch",
        metavar="LABEL",
        help="resume at the exact batch label (for example: 'vocal deps')",
    )
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

    requested_stacks = set(args.stack or STACKS)
    installer = _load_installer(root)
    batches = build_plan(root, requested_stacks)
    if len(requested_stacks) == 1:
        profile_plans = {next(iter(requested_stacks)): batches}
    else:
        profile_plans = {
            stack: build_plan(root, {stack})
            for stack in STACKS
            if stack in requested_stacks
        }
    if args.check:
        errors = validate_wheelhouse_profiles(root, profile_plans)
        if errors:
            for error in errors:
                print(f"[wheelhouse] {error}", file=sys.stderr)
            return 1
        print("Wheelhouse completion profiles are valid: " + ", ".join(sorted(requested_stacks)))
        return 0
    manifest_batches = batches
    if args.from_batch:
        labels = [batch.label for batch in batches]
        if args.from_batch not in labels:
            raise SystemExit(
                f"Unknown --from-batch label {args.from_batch!r}. Available labels: "
                + ", ".join(labels)
            )
        start = labels.index(args.from_batch)
        batches = batches[start:]
        print(f"Resuming wheelhouse at batch: {args.from_batch}")
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
                "no_build_isolation": batch.no_build_isolation,
            }
            for batch in batches
        ]
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    wheelhouse = root / "assets" / "wheels"
    wheelhouse.mkdir(parents=True, exist_ok=True)
    for batch in batches:
        _download_batch(root, installer, batch)
    _write_manifest(root, manifest_batches, profile_plans)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
