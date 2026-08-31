"""XB-SVCB 一键安装器（核心编排）。

为「AI 翻唱工具」搭建开箱即用的运行环境，全部组件落在项目目录内、互不污染：

  app/.venv      —— 主程序环境（pywebview，桌面壳）
  .venv-plugins/ —— Python 插件轻量运行环境（插件依赖随插件包携带）
  .venv-uvr/     —— 人声分离环境（audio-separator）
  .venv-pymss/   —— 可选 PyMSS 人声分离环境
  .venv-svc/     —— so-vits-svc 4.1 推理环境（torch + fairseq 等）
  .venv-rvc/     —— RVC 推理环境（rvc-python；40 系及以下 cu121，50 系 cu128，CPU 版）
  .venv-seedvc/  —— SeedVC 推理环境（官方 Seed-VC；推理时提供参考音频）
  .venv-ddsp/    —— DDSP-SVC 推理环境（yxlllc/DDSP-SVC Rectified Flow）
  .venv-vocal/   —— AI 歌声增强环境（DeepFilterNet + Pedalboard）
  .venv-hub/     —— 模型上传组件（modelscope）
  engines/so-vits-svc/          —— 安装分卷自带的 so-vits-svc 4.1 仓库
  engines/seed-vc/              —— 安装分卷自带的 Seed-VC 仓库
  engines/ddsp-svc/             —— 安装分卷自带的 DDSP-SVC 仓库
  engines/so-vits-svc/pretrain —— 底模（contentvec / nsf_hifigan / rmvpe）
  models/uvr/    —— UVR 分离模型（5_HP-Karaoke / DeEcho-DeReverb）
  web/dist/      —— 前端构建产物

图形安装包会自带三个歌声引擎源码、底模与 UVR 模型：检测到 engines/ 中的完整
源码时跳过仓库获取，assets/models/ 中的模型直接本地复制；仅源码安装缺失时才回退联网。

设计原则：
  - 幂等：每步都会先检测已完成的产物，可重复运行、可单步重试；
  - 解耦：不依赖用户机器上的任何绝对路径；
  - 健壮：单步失败不会中断整体，最后汇总结果并给出手动补救指引。

用法（建议用 install.ps1 一键调用，下面是直接调用方式）：
  python install/install.py                # 全自动（检测显卡决定 CUDA/CPU）
  python install/install.py --cpu          # 强制 CPU
  python install/install.py --gpu          # 强制 CUDA
  python install/install.py --skip-svc     # 跳过 so-vits-svc（仅装壳+分离+前端）
  python install/install.py --only rvc     # 只装 RVC 推理环境（.venv-rvc）
  python install/install.py --only seedvc  # 只装 SeedVC 推理环境（.venv-seedvc）
  python install/install.py --only ddsp    # 只装 DDSP-SVC 推理环境（.venv-ddsp）
  python install/install.py --only vocal   # 只装 AI 歌声增强环境（.venv-vocal）
  python install/install.py --consolidated # 实验性合并预检，当前依赖冲突会停止
  python install/install.py --only models  # 只跑某一步：app/plugins/web/uvr/pymss/svc/rvc/seedvc/ddsp/vocal/hub/models
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import urllib.request
import zipfile
from pathlib import Path

DEFAULT_HF_MIRROR = "https://hf-mirror.com"
DEFAULT_PYPI_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
PYPI_FALLBACK_INDEX = "https://mirrors.cloud.tencent.com/pypi/simple"


def _normalize_url(raw: str | None, default: str = "") -> str:
    val = (raw or "").strip().rstrip("/")
    return val or default


HF_MIRROR = _normalize_url(
    os.environ.get("XB_HF_MIRROR") or os.environ.get("HF_ENDPOINT"),
    DEFAULT_HF_MIRROR,
)
PYPI_MIRROR = _normalize_url(
    os.environ.get("XB_PYPI_MIRROR")
    or os.environ.get("UV_DEFAULT_INDEX")
    or os.environ.get("PIP_INDEX_URL"),
    DEFAULT_PYPI_MIRROR,
)
os.environ.setdefault("XB_HF_MIRROR", HF_MIRROR)
os.environ.setdefault("HF_ENDPOINT", HF_MIRROR)
os.environ.setdefault("HUGGINGFACE_HUB_ENDPOINT", HF_MIRROR)
os.environ.setdefault("XB_PYPI_MIRROR", PYPI_MIRROR)
os.environ.setdefault("PIP_INDEX_URL", PYPI_MIRROR)
os.environ.setdefault("UV_DEFAULT_INDEX", PYPI_MIRROR)
os.environ.setdefault("UV_LINK_MODE", "copy")
os.environ.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(errors="replace")

# 所有产物（引擎/虚拟环境/模型）都落在 ROOT 下。默认取本脚本上级目录；
# 安装器会用 --root 显式指定为用户选择的安装目录，确保依赖装进该目录。
ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"
WEB_DIR = ROOT / "web"
ENGINES_DIR = ROOT / "engines"
SOVITS_DIR = ENGINES_DIR / "so-vits-svc"
SEEDVC_DIR = ENGINES_DIR / "seed-vc"
DDSP_DIR = ENGINES_DIR / "ddsp-svc"
PRETRAIN_DIR = SOVITS_DIR / "pretrain"
UVR_VENV = ROOT / ".venv-uvr"
PLUGIN_VENV = ROOT / ".venv-plugins"
PYMSS_VENV = ROOT / ".venv-pymss"
SVC_VENV = ROOT / ".venv-svc"
HUB_VENV = ROOT / ".venv-hub"
RVC_VENV = ROOT / ".venv-rvc"
SEEDVC_VENV = ROOT / ".venv-seedvc"
DDSP_VENV = ROOT / ".venv-ddsp"
VOCAL_VENV = ROOT / ".venv-vocal"
RUNTIMES_DIR = ROOT / "runtimes"
# Current consolidated NVIDIA runtime. The stack-specific path is selected by
# _configure_runtime_layout; this default keeps imported helpers meaningful.
CORE_VENV = RUNTIMES_DIR / "core-cu128"
RUNTIME_MANIFEST = ROOT / "runtime.json"
UVR_MODELS_DIR = ROOT / "models" / "uvr"
VOCAL_MODELS_DIR = ROOT / "models" / "vocal-enhancement"

# 随安装包一起分发的离线载荷：安装时直接本地复制/安装，免用户机器联网慢下载。
# 始终相对本脚本位置（assets/* 与 install/ 同级），不随 --root 改变。
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
ASSETS_MODELS_DIR = ASSETS_DIR / "models"
ASSETS_WHEELS_DIR = ASSETS_DIR / "wheels"


def _derive_paths(root: Path) -> None:
    """以 root 为基准重新计算所有产物路径（供 --root 覆盖）。"""
    global ROOT, APP_DIR, WEB_DIR, ENGINES_DIR, SOVITS_DIR, SEEDVC_DIR, DDSP_DIR, PRETRAIN_DIR
    global UVR_VENV, PLUGIN_VENV, PYMSS_VENV, SVC_VENV, HUB_VENV, RVC_VENV, SEEDVC_VENV, DDSP_VENV, VOCAL_VENV
    global RUNTIMES_DIR, CORE_VENV, RUNTIME_MANIFEST
    global UVR_MODELS_DIR, VOCAL_MODELS_DIR
    ROOT = root
    APP_DIR = root / "app"
    WEB_DIR = root / "web"
    ENGINES_DIR = root / "engines"
    SOVITS_DIR = ENGINES_DIR / "so-vits-svc"
    SEEDVC_DIR = ENGINES_DIR / "seed-vc"
    DDSP_DIR = ENGINES_DIR / "ddsp-svc"
    PRETRAIN_DIR = SOVITS_DIR / "pretrain"
    UVR_VENV = root / ".venv-uvr"
    PLUGIN_VENV = root / ".venv-plugins"
    PYMSS_VENV = root / ".venv-pymss"
    SVC_VENV = root / ".venv-svc"
    HUB_VENV = root / ".venv-hub"
    RVC_VENV = root / ".venv-rvc"
    SEEDVC_VENV = root / ".venv-seedvc"
    DDSP_VENV = root / ".venv-ddsp"
    VOCAL_VENV = root / ".venv-vocal"
    RUNTIMES_DIR = root / "runtimes"
    CORE_VENV = RUNTIMES_DIR / "core-cu128"
    RUNTIME_MANIFEST = root / "runtime.json"
    UVR_MODELS_DIR = root / "models" / "uvr"
    VOCAL_MODELS_DIR = root / "models" / "vocal-enhancement"

SOVITS_REPO_URL = "https://github.com/svc-develop-team/so-vits-svc.git"
SOVITS_BRANCH = "4.1-Stable"
# 无 git 时改用 GitHub 分支 ZIP（codeload 直链），免 git 也能获取仓库
SOVITS_ZIP_URL = (
    "https://github.com/svc-develop-team/so-vits-svc/archive/refs/heads/4.1-Stable.zip"
)
SEEDVC_REPO_URL = "https://github.com/Plachtaa/seed-vc.git"
SEEDVC_ZIP_URL = "https://github.com/Plachtaa/seed-vc/archive/refs/heads/main.zip"
DDSP_REPO_URL = "https://github.com/yxlllc/DDSP-SVC.git"
DDSP_BRANCH = "6.3"
DDSP_ZIP_URL = "https://github.com/yxlllc/DDSP-SVC/archive/refs/heads/6.3.zip"
DDSP_CONTENTVEC_HF = "/lengyue233/content-vec-best/resolve/main/pytorch_model.bin"
DDSP_NSF_HIFIGAN_GH = (
    "https://github.com/openvpi/vocoders/releases/download/"
    "pc-nsf-hifigan-44.1k-hop512-128bin-2025.02/"
    "pc_nsf_hifigan_44.1k_hop512_128bin_2025.02.zip"
)

# CUDA wheel 源（cu121 兼容 40 系及以下 NVIDIA 显卡）；CPU 用官方默认源
TORCH_CUDA_INDEX = "https://download.pytorch.org/whl/cu121"
TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"
# RVC 旧栈仍固定 torch 2.1.1，但 CUDA wheel 与其它环境统一走 cu121。
TORCH_RVC_CUDA_INDEX = TORCH_CUDA_INDEX

# ---- 50 系（Blackwell, sm_120）专用栈 ----
# 50 系必须用 cu128 + torch>=2.7（cu121 无 sm_120 内核，会"无可用内核"或哑音）。
# 仅升级 torch/cuda 不够：旧 3.9 + 老 numpy/fairseq/torchaudio 在新 torch 上能加载却出哑音，
# 因此 Blackwell 走独立的 py3.10 + 新依赖栈（torchaudio I/O 改用 soundfile，fairseq 重装）。
TORCH_BLACKWELL_INDEX = "https://download.pytorch.org/whl/cu128"
TORCH_BLACKWELL_VER = "2.7.1"  # cp39/cp310 均有 win 轮子；统一钉此版本以求确定性
TORCHAUDIO_BLACKWELL_VER = "2.7.1"
TORCHVISION_BLACKWELL_VER = "0.22.1"
# PyMSS 2.0.x requires Torch 2.7.1. PyTorch publishes that pair on cu126 for
# pre-Blackwell NVIDIA cards and on cu128 for Blackwell, so keep the isolated
# PyMSS wheelhouse aligned to the actual runtime stack.
TORCH_PYMSS_CUDA_INDEX = "https://download.pytorch.org/whl/cu126"

# PyMSS 2.0.x requires torch>=2.7.1. Keep its runtime pinned and isolated from
# the older torch stacks used by UVR/RVC/SVC. NVIDIA cards use cu126 for
# pre-Blackwell and cu128 for Blackwell; DirectML remains CPU because
# torch-directml pins 2.4.1.
PYMSS_VERSION = "2.0.18"
PYMSS_TORCH_VER = "2.7.1"
PYMSS_TORCHAUDIO_VER = "2.7.1"

# ---- AMD / Windows DirectML stack ----
# torch-directml 0.2.5 is the latest published Windows runtime and pins torch
# 2.4.1. Keep all isolated DirectML inference environments on this exact pair so a
# later dependency cannot silently replace the registered DirectML backend.
TORCH_DIRECTML_VER = "0.2.5.dev240914"
TORCH_DIRECTML_TORCH_VER = "2.4.1"
TORCHAUDIO_DIRECTML_VER = "2.4.1"
AUDIO_SEPARATOR_VER = "0.44.2"
# FCPE imports both modules at predictor startup. Pin local-attention before
# 1.11, whose hyper-connections dependency requires torch>=2.5 and conflicts
# with the validated DirectML torch 2.4.1 stack.
SVC_FCPE_RUNTIME_DEPS = (
    "einops==0.8.2",
    "local-attention==1.10.0",
)
# So-VITS-SVC imports matplotlib while loading its vocoder. The py39 stack
# installs matplotlib with --no-deps to preserve its validated NumPy pin, so
# keep matplotlib's remaining import-time dependencies explicit.
SVC_MATPLOTLIB_RUNTIME_DEPS = (
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

# 底模下载清单（见 README 与 so-vits-svc 官方说明）
# HuggingFace 在国内常连不上，统一走「镜像优先 + 官方回退」。
HF_PATH_CONTENTVEC = "/lj1995/VoiceConversionWebUI/resolve/main/hubert_base.pt"
# GitHub Release 直链（在国内也常超时，故附带 ghproxy 镜像回退）
NSF_HIFIGAN_GH = (
    "https://github.com/openvpi/vocoders/releases/download/"
    "nsf-hifigan-v1/nsf_hifigan_20221211.zip"
)
RMVPE_GH = "https://github.com/yxlllc/RMVPE/releases/download/230917/rmvpe.zip"

# 镜像主机（按顺序尝试；可用 XB_HF_MIRROR / HF_ENDPOINT / XB_GH_MIRROR 覆盖）
HF_HOSTS = [
    HF_MIRROR,
    "https://huggingface.co",
]
GH_PROXIES = [
    "",  # 直连优先
    os.environ.get("XB_GH_MIRROR", "https://ghfast.top").rstrip("/") + "/",
    "https://mirror.ghproxy.com/",
]

UVR_MODEL_NAMES = ["5_HP-Karaoke-UVR.pth", "UVR-DeEcho-DeReverb.pth"]

# audio-separator 启动加载模型前会联网拉取这几个 JSON（模型清单与按哈希匹配的参数表），
# 国内访问 raw.githubusercontent.com 常超时。预先放进模型目录即可完全离线
# （audio-separator 的 download_file_if_not_exists 检测到本地已存在就跳过下载）。
UVR_SUPPORT_FILES = [
    "download_checks.json",
    "vr_model_data.json",
    "mdx_model_data.json",
]
# 这些 JSON 在 GitHub 上的相对路径（自带缺失时回退联网下载，走镜像优先）
UVR_SUPPORT_GH = {
    "download_checks.json": "filelists/download_checks.json",
    "vr_model_data.json": "vr_model_data/model_data_new.json",
    "mdx_model_data.json": "mdx_model_data/model_data_new.json",
}
UVR_DATA_RAW_PREFIX = "https://raw.githubusercontent.com/TRvlvr/application_data/main/"

# UVR（audio-separator）是现代库，用 3.10。
PYTHON_FOR_ENGINES = "3.10"
# so-vits-svc 4.1 的 CUDA/CPU 依赖以 Python 3.9 为稳定栈；DirectML 必须使用
# Python 3.10，避免 torch-directml 0.2.5 在 3.9 导入时触发 staticmethod 错误。
PYTHON_FOR_SVC = "3.9"
# RVC 的 CUDA/CPU 老栈继续使用 Python 3.9；DirectML 与 Blackwell 使用 3.10。
PYTHON_FOR_RVC = "3.9"
# Blackwell（50 系）下改用 3.10：cu128 的 torch2.7.1 有 cp310 轮子，且 numpy 1.23.5 /
# pyworld 等在 3.10 也有可用 wheel；3.9 老栈在新 torch 上易出哑音。
PYTHON_FOR_SVC_BLACKWELL = "3.10"
PYTHON_FOR_RVC_BLACKWELL = "3.10"

# Consolidated runtime is deliberately opt-in for the first migration pass.
# Matching Python/Torch is necessary but NOT sufficient: all upstream
# requirements must resolve together before touching an existing environment.
# The currently pinned UVR and SeedVC/DDSP NumPy/protobuf sets conflict.
CONSOLIDATED_RUNTIME = False
CONSOLIDATED_STACK = ""
CORE_COMPONENTS = {"uvr", "seedvc", "ddsp"}
CORE_VENV_REUSED = False
CORE_CONSTRAINTS: Path | None = None
CORE_COMPAT_WHEEL: Path | None = None
CORE_PROFILE: dict | None = None
CORE_PROFILE_PINS: dict[str, str] = {}
# Experimental, locally tested candidate. Never applied to isolated runtimes.
CORE_COMPAT_PACKAGES = (
    "numpy==2.2.6", "protobuf==7.36.0", "tensorboardX==2.6.5",
    "tensorboard==2.20.0", "onnx-weekly==1.23.0.dev20260824",
)


def _core_requirement_overrides(component: str) -> dict[str, str]:
    overrides = dict(DDSP_REQ_OVERRIDES) if component == "ddsp" else {}
    if CONSOLIDATED_RUNTIME and CORE_COMPAT_WHEEL is not None:
        overrides["numpy"] = "numpy==2.2.6"
    return overrides


def _recipe_module():
    # Load the sibling file even when embedded/imported outside the repo root.
    # Do not rely on another test or caller having modified sys.path.
    spec = importlib.util.spec_from_file_location("xb_installer_core_recipe", Path(__file__).with_name("core_recipe.py"))
    recipe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(recipe)
    return recipe


def _configure_core_profile(name: str | None) -> None:
    global CORE_PROFILE, CORE_PROFILE_PINS, CORE_COMPAT_WHEEL
    CORE_PROFILE, CORE_PROFILE_PINS = None, {}
    if name is None:
        return
    recipe = _recipe_module()
    profile, pins = recipe.load_profile()
    if name != profile["id"]:
        raise ValueError("Unknown core profile")
    recipe.verify_artifacts(ROOT, profile, {"compat"})
    CORE_COMPAT_WHEEL = recipe.contained(ROOT, profile["compatibility_wheel"])
    CORE_PROFILE, CORE_PROFILE_PINS = profile, pins


def _validate_core_compat_wheel(path: Path) -> None:
    from email.parser import Parser

    with zipfile.ZipFile(path) as wheel:
        metadata = Parser().parsestr(wheel.read(
            "descript_audiotools-0.7.2+xb1.dist-info/METADATA").decode("utf-8"))
    required = metadata.get_all("Requires-Dist", [])
    if (metadata.get("Name") != "descript-audiotools" or metadata.get("Version") != "0.7.2+xb1"
            or "protobuf ==7.36.0" not in required or "tensorboard ==2.20.0" not in required):
        raise ValueError("AudioTools 兼容 wheel 不匹配已验证的实验配方")


def _configure_runtime_layout(*, consolidated: bool, gpu_stack: str) -> None:
    """Select the environment layout used by installation steps."""
    global CONSOLIDATED_RUNTIME, CONSOLIDATED_STACK, CORE_VENV, CORE_VENV_REUSED
    CONSOLIDATED_RUNTIME = bool(consolidated and gpu_stack in {"cpu", "cu121", "cu128"})
    CONSOLIDATED_STACK = gpu_stack if CONSOLIDATED_RUNTIME else ""
    CORE_VENV_REUSED = False
    if CONSOLIDATED_RUNTIME:
        # Candidate only: the preflight and post-install checks below must pass
        # before this directory can be advertised as a shared runtime.
        existing_uvr = venv_python(UVR_VENV)
        if _path_exists(existing_uvr) and _python_minor_version(existing_uvr) == PYTHON_FOR_ENGINES:
            CORE_VENV = UVR_VENV
            CORE_VENV_REUSED = True
        else:
            CORE_VENV = RUNTIMES_DIR / f"core-{gpu_stack}"


def runtime_venv(component: str, legacy: Path) -> Path:
    """Return the selected venv path for an installer component."""
    if CONSOLIDATED_RUNTIME and component in CORE_COMPONENTS:
        return CORE_VENV
    return legacy


def write_runtime_manifest(gpu_stack: str, installed: set[str]) -> None:
    """Persist relative interpreter paths so the app can discover shared envs."""
    if not CONSOLIDATED_RUNTIME or not CORE_COMPONENTS.issubset(installed):
        return
    py = str(venv_python(CORE_VENV))
    # Never activate a half-installed or incompatible shared environment.
    if not Path(py).is_file():
        raise RuntimeError("共享运行时缺少 Python，未更新 runtime.json")
    payload = {}
    if RUNTIME_MANIFEST.exists():
        payload = json.loads(RUNTIME_MANIFEST.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("python", {}), dict):
            raise RuntimeError("runtime.json 格式无效，拒绝覆盖")
    components = {
        component: venv_python(runtime_venv(component, Path(f".venv-{component}")))
        for component in sorted(CORE_COMPONENTS)
    }
    # Keep paths portable across install locations; config resolves them from ROOT_DIR.
    payload.update({
        "version": 1,
        "layout": "consolidated",
        "stack": gpu_stack,
        "python": {
            **payload.get("python", {}),
            **{component: str(path.relative_to(ROOT)).replace("\\", "/")
               for component, path in components.items()},
        },
    })
    if CORE_COMPAT_WHEEL is not None:
        payload["compatibility"] = {"experimental": True, "profile": "numpy2-protobuf7-xb1"}
    if CORE_PROFILE is not None:
        payload["compatibility"].update({"profile": CORE_PROFILE["id"],
                                         "lock_sha256": CORE_PROFILE["lock_sha256"]})
    RUNTIME_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=RUNTIME_MANIFEST.parent,
                                     prefix="runtime-", suffix=".json.tmp", delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    try:
        temporary.replace(RUNTIME_MANIFEST)
    finally:
        temporary.unlink(missing_ok=True)


def _shared_torch_specs(gpu_stack: str) -> list[str]:
    if gpu_stack == "cu128":
        versions = (TORCH_BLACKWELL_VER, TORCHAUDIO_BLACKWELL_VER, TORCHVISION_BLACKWELL_VER)
    elif gpu_stack in {"cpu", "cu121"}:
        versions = ("2.5.1", "2.5.1", "0.20.1")
    else:
        raise RuntimeError("共享环境暂不支持此设备栈")
    return [f"{name}=={version}+{gpu_stack}" for name, version in
            zip(("torch", "torchaudio", "torchvision"), versions)]


def _preflight_consolidated_runtime(uv: str, selected: set[str], gpu_stack: str) -> None:
    """Resolve the entire group without installing anything or fetching models."""
    global CORE_CONSTRAINTS
    CORE_CONSTRAINTS = None
    if not CONSOLIDATED_RUNTIME or not selected.intersection(CORE_COMPONENTS):
        return
    if not CORE_COMPONENTS.issubset(selected):
        raise RuntimeError("共享环境必须一起验证：--only uvr seedvc ddsp；不允许部分安装后切换路由")
    sources = (SEEDVC_DIR / "requirements.txt", DDSP_DIR / "requirements.txt")
    if any(not source.is_file() for source in sources):
        raise RuntimeError("缺少 SeedVC/DDSP 源码 requirements；先准备源码，预检不会下载或删除引擎目录")
    compatibility = []
    if CORE_COMPAT_WHEEL is not None:
        if gpu_stack != "cu128":
            raise RuntimeError("NumPy 2/protobuf 7 实验配方目前仅验证 cu128，不自动应用到 CPU/cu121/DirectML")
        _validate_core_compat_wheel(CORE_COMPAT_WHEEL)
        compatibility = [*CORE_COMPAT_PACKAGES, f"descript-audiotools @ {CORE_COMPAT_WHEEL.resolve().as_uri()}"]
    scratch = ROOT / ".tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    # Stage inputs separately and adopt only a successfully compiled lock.
    with tempfile.TemporaryDirectory(prefix="core-preflight-", dir=scratch) as work:
        stage = Path(work)
        seed_req = _filter_requirements(sources[0], extra_deny=SEEDVC_REQ_DENY,
                                       overrides=_core_requirement_overrides("seedvc"),
                                       output=stage / "seedvc.txt")
        ddsp_req = _filter_requirements(sources[1], extra_deny=DDSP_REQ_DENY,
                                       overrides=_core_requirement_overrides("ddsp"), output=stage / "ddsp.txt")
        extra = "cpu" if gpu_stack == "cpu" else "gpu"
        requirements = stage / "core.in"
        requirements.write_text("\n".join([
            f"audio-separator[{extra}]=={AUDIO_SEPARATOR_VER}",
            "setuptools<81", "wheel", *_shared_torch_specs(gpu_stack),
            *compatibility,
            *[f"{name}=={version}" for name, version in CORE_PROFILE_PINS.items()
              if name != "descript-audiotools"],
            seed_req.read_text(encoding="utf-8"), ddsp_req.read_text(encoding="utf-8"),
        ]) + "\n", encoding="utf-8")
        locked = stage / "core.txt"
        index = {"cpu": TORCH_CPU_INDEX, "cu121": TORCH_CUDA_INDEX, "cu128": TORCH_BLACKWELL_INDEX}[gpu_stack]
        directories = []
        for component in sorted(CORE_COMPONENTS):
            directories.extend(_wheelhouse_dirs(component=component, gpu_stack=gpu_stack, python_version="3.10"))
        # Do not let the Torch index shadow unrelated PyPI packages (e.g.
        # setuptools/packaging). uv's backend routing is package-specific.
        indices = (pypi_index_args(use_mirror=False) + ["--torch-backend", "cu128"]
                   if CORE_PROFILE is not None else pypi_index_args(index, use_mirror=False))
        if directories and _wheelhouse_strict():
            indices = ["--no-index"]
            for directory in dict.fromkeys(directories):
                indices.extend(["--find-links", str(directory)])
        if CORE_COMPAT_WHEEL is not None:
            # Source-only packages (argbind/randomname/etc.) can be staged
            # beside the compatibility wheel without allowing source builds
            # or build-time downloads into this preflight.
            indices.extend(["--find-links", str(CORE_COMPAT_WHEEL.parent)])
        command = uv_cmd(uv, "pip", "compile", str(requirements), "--python-version", "3.10",
                         "--python-platform", "windows", "--no-python-downloads", "--no-build",
                         "--output-file", str(locked), *indices)
        # Compilation may retrieve package metadata, but never installs into
        # the venv. Do not retry resolution failures using --reinstall.
        try:
            run(command)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError("共享依赖整体解析失败，未安装任何包，请查看上方解析/网络错误；不会通过重装或忽略约束继续") from exc
        if CORE_PROFILE is not None:
            _recipe_module().verify_resolution(locked, CORE_PROFILE_PINS)
        destination = scratch / f"core-{gpu_stack}.constraints.txt"
        shutil.copyfile(locked, destination)
        CORE_CONSTRAINTS = destination


def _guard_shared_runtime_repair(selected: set[str]) -> None:
    """Don't repair one legacy path that currently hosts several components."""
    if CONSOLIDATED_RUNTIME or not selected.intersection(CORE_COMPONENTS) or not RUNTIME_MANIFEST.exists():
        return
    payload = json.loads(RUNTIME_MANIFEST.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise RuntimeError("runtime.json 格式无效，拒绝修改运行时")
    mapping = payload.get("python", {})
    if not isinstance(mapping, dict):
        raise RuntimeError("runtime.json 格式无效，拒绝修改运行时")
    targets: dict[Path, set[str]] = {}
    for component, raw in mapping.items():
        if not isinstance(raw, str):
            continue
        path = Path(raw)
        path = path if path.is_absolute() else ROOT / path
        targets.setdefault(path.resolve(), set()).add(component)
    for component in selected.intersection(CORE_COMPONENTS):
        path = venv_python(ROOT / f".venv-{component}").resolve()
        shares_route = any(component in components and len(components) > 1
                           for components in targets.values())
        if shares_route or len(targets.get(path, set())) > 1:
            raise RuntimeError(f"{component} 的解释器路由与其他组件共用；不能单独修复 {component}，请先检查/拆分 runtime.json 路由")


def _svc_python_for_stack(gpu_stack: str) -> str:
    if gpu_stack == "directml":
        return PYTHON_FOR_ENGINES
    if gpu_stack == "cu128":
        return PYTHON_FOR_SVC_BLACKWELL
    return PYTHON_FOR_SVC


def _rvc_python_for_stack(gpu_stack: str) -> str:
    if gpu_stack == "directml":
        return PYTHON_FOR_ENGINES
    if gpu_stack == "cu128":
        return PYTHON_FOR_RVC_BLACKWELL
    return PYTHON_FOR_RVC

# so-vits-svc requirements 里只服务 WebUI / 实时变声 / ONNX 导出、推理用不到，
# 且在 Windows 上常因缺少预编译包而现场编译失败的包，安装时一并剔除：
#   playsound 1.3.0 ── 新版 pip 构建取不到源码而失败（仅播放用）
#   gradio          ── 自带 WebUI，本应用有自己的界面
#   pyaudio/sounddevice ── 实时麦克风/扬声器 I/O，文件翻唱用不到，且常需 PortAudio 编译
#   onnxsim/onnxoptimizer ── 仅 ONNX 模型导出用，需 C++ 编译
REQ_DENYLIST = {
    "playsound",
    "gradio",
    "pyaudio",
    "sounddevice",
    "onnxsim",
    "onnxoptimizer",
}

# ---- 终端着色（Windows 终端默认支持 ANSI）----
_C = {"g": "\033[32m", "y": "\033[33m", "r": "\033[31m", "b": "\033[36m", "0": "\033[0m"}
_COLOR_ENABLED = os.environ.get("XB_FROM_INSTALLER") != "1" and os.environ.get("NO_COLOR") is None


def c(tag: str, text: str) -> str:
    if not _COLOR_ENABLED:
        return text
    return f"{_C.get(tag, '')}{text}{_C['0']}"


def hr(title: str) -> None:
    print("\n" + c("b", "=" * 64))
    print(c("b", f"  {title}"))
    print(c("b", "=" * 64))


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> None:
    """执行子命令并把输出实时打印；失败抛出 CalledProcessError。"""
    print(c("y", "$ " + " ".join(str(x) for x in cmd)))
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=full_env, check=True)


def pypi_index_args(
    index: str | None = None,
    *,
    use_mirror: bool = True,
) -> list[str]:
    """Return uv index args. Torch installs pass their own PyTorch index."""
    args: list[str] = []
    if index:
        args += ["--index", index]
    if use_mirror and PYPI_MIRROR and PYPI_MIRROR != PYPI_FALLBACK_INDEX:
        args += ["--index", PYPI_MIRROR]
    args += ["--default-index", PYPI_FALLBACK_INDEX]
    return args


def _truthy_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"", "0", "false", "no", "off"}


def _wheelhouse_root() -> Path | None:
    raw = os.environ.get("XB_WHEELHOUSE")
    root = Path(raw).expanduser() if raw else ASSETS_WHEELS_DIR
    return root if root.exists() else None


def _dir_has_wheels(path: Path) -> bool:
    try:
        return path.is_dir() and any(path.glob("*.whl"))
    except OSError:
        return False


def _wheel_py_tag(python_version: str | None) -> str | None:
    if not python_version:
        return None
    m = re.match(r"^\s*(\d+)\.(\d+)", python_version)
    if not m:
        return None
    return f"py{m.group(1)}{m.group(2)}"


def _wheelhouse_strict() -> bool:
    # 安装包内已有 wheelhouse 时默认走离线 whl；源码开发环境未准备 wheelhouse 时仍可联网。
    return _truthy_env("XB_WHEELHOUSE_STRICT", default=True)


def _wheelhouse_dirs(
    *,
    component: str | None = None,
    gpu_stack: str | None = None,
    python_version: str | None = None,
) -> list[Path]:
    root = _wheelhouse_root()
    py_tag = _wheel_py_tag(python_version)
    stack = (gpu_stack or "").strip().lower()
    comp = (component or "").strip().lower()
    if root is None:
        return []

    candidates: list[Path] = []
    if comp:
        candidates += [root / comp / "common"]
        if py_tag:
            candidates += [root / comp / py_tag / "common"]
            if stack:
                candidates.append(root / comp / py_tag / stack)
        if stack:
            candidates.append(root / comp / stack)
            if py_tag:
                candidates.append(root / comp / stack / py_tag)
        if py_tag:
            candidates.append(root / comp / py_tag)
        candidates.append(root / comp)
    if py_tag:
        candidates += [root / py_tag / "common"]
        if stack:
            candidates.append(root / py_tag / stack)
    if stack:
        candidates.append(root / stack)
    candidates.append(root / "common")

    found: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen or not _dir_has_wheels(path):
            continue
        seen.add(resolved)
        found.append(path)
    return found


def _wheelhouse_args(
    *,
    component: str | None = None,
    gpu_stack: str | None = None,
    python_version: str | None = None,
) -> list[str]:
    dirs = _wheelhouse_dirs(
        component=component,
        gpu_stack=gpu_stack,
        python_version=python_version,
    )
    if not dirs:
        return []
    args = ["--no-index", "--no-build"]
    for directory in dirs:
        args += ["--find-links", str(directory)]
    return args


def _normalized_dist_name(name: str) -> str:
    """Normalize a distribution name as specified by the wheel metadata rules."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _find_wheel_for_package(package: str, directories: list[Path]) -> Path | None:
    normalized = _normalized_dist_name(package)
    for directory in directories:
        try:
            wheels = sorted(directory.glob("*.whl"), key=lambda item: item.name.lower())
        except OSError:
            continue
        for wheel in wheels:
            prefix = wheel.name.split("-", 1)[0]
            if _normalized_dist_name(prefix) == normalized:
                return wheel
    return None


def _repair_broken_wheel_metadata(
    venv_dir: Path,
    packages: tuple[str, ...],
    *,
    component: str,
    gpu_stack: str,
    python_version: str,
) -> list[str]:
    """Restore interrupted wheel installs without replacing locked binaries.

    uv reads every installed ``*.dist-info/METADATA`` before resolving a new
    request. An interrupted install can leave the package files intact while
    that metadata file is absent, causing uv to enter a reinstall path which
    may fail to replace a DLL still loaded by the running application.
    """
    site_packages = venv_dir / "Lib" / "site-packages"
    if not site_packages.is_dir():
        candidates = sorted(venv_dir.glob("lib/python*/site-packages"))
        site_packages = candidates[0] if candidates else site_packages
    if not site_packages.is_dir():
        return []

    directories = _wheelhouse_dirs(
        component=component,
        gpu_stack=gpu_stack,
        python_version=python_version,
    )
    repaired: list[str] = []
    for package in packages:
        normalized = _normalized_dist_name(package)
        try:
            dist_infos = sorted(
                (
                    path
                    for path in site_packages.glob("*.dist-info")
                    if _normalized_dist_name(
                        path.name.removesuffix(".dist-info").rsplit("-", 1)[0]
                    )
                    == normalized
                ),
                key=lambda item: item.name.lower(),
            )
        except OSError:
            continue
        for dist_info in dist_infos:
            try:
                missing = []
                for filename in ("METADATA", "WHEEL", "RECORD"):
                    target = dist_info / filename
                    if not target.is_file() or target.stat().st_size == 0:
                        missing.append(filename)
                if not missing:
                    continue
            except OSError:
                continue

            wheel = _find_wheel_for_package(package, directories)
            if wheel is None:
                print(c("y", f"    {package} 元数据损坏且 wheelhouse 中无匹配轮子，将重新安装 …"))
                shutil.rmtree(dist_info, ignore_errors=True)
                continue

            try:
                with zipfile.ZipFile(wheel) as archive:
                    members = {
                        Path(member).name.upper(): member
                        for member in archive.namelist()
                        if ".dist-info/" in member
                    }
                    for filename in ("METADATA", "WHEEL", "RECORD", "INSTALLER"):
                        target = dist_info / filename
                        if (
                            filename not in members
                            or (target.is_file() and target.stat().st_size > 0)
                        ):
                            continue
                        target.write_bytes(archive.read(members[filename]))
            except (OSError, KeyError, zipfile.BadZipFile) as exc:
                print(c("y", f"    {package} wheel 元数据修复失败：{exc}"))
                continue

            metadata = dist_info / "METADATA"
            if metadata.is_file() and metadata.stat().st_size > 0:
                repaired.append(package)
                print(c("y", f"    已修复 {package} 的中断安装元数据，跳过 DLL 重装"))
    return repaired


def _uv_bootstrap_wheelhouse_args() -> list[str]:
    root = _wheelhouse_root()
    if root is None:
        return []
    dirs = [root / "bootstrap", root / "common"]
    found = [path for path in dirs if _dir_has_wheels(path)]
    if not found:
        return []
    args = ["--no-index"]
    for directory in found:
        args += ["--find-links", str(directory)]
    return args


def warn_pypi_fallback() -> None:
    print(c("y", f"    PyPI mirror failed; retrying with fallback PyPI mirror: {PYPI_FALLBACK_INDEX}"))


def venv_python(venv_dir: Path) -> Path:
    return (
        venv_dir / "Scripts" / "python.exe"
        if os.name == "nt"
        else venv_dir / "bin" / "python"
    )


def _python_minor_version(py: Path) -> str | None:
    """Return a Python executable's major.minor version, or None if unusable."""
    try:
        out = subprocess.run(
            [str(py), "-c", "import sys;print('%d.%d'%sys.version_info[:2])"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    ver = out.stdout.strip()
    return ver if re.match(r"^\d+\.\d+$", ver) else None


def _path_is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _python_launcher_path(python_version: str) -> str | None:
    if os.name != "nt":
        return None
    try:
        out = subprocess.run(
            [
                "py",
                f"-{python_version}",
                "-c",
                "import sys;print(sys.executable)",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def _where_python_paths() -> list[str]:
    try:
        found = shutil.which("python")
        out = subprocess.run(
            ["where", "python"] if os.name == "nt" else ["which", "-a", "python"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return [found] if found else []
    values = out.stdout.splitlines() if out.returncode == 0 else []
    if found:
        values.insert(0, found)
    return values


def _candidate_python_paths(python_version: str | None = None) -> list[Path]:
    launcher = _python_launcher_path(python_version) if python_version else None
    raw_candidates = [
        os.environ.get("XB_PYTHON_310_EXE"),
        os.environ.get("XB_PYTHON_EXE"),
        (
            str(Path(os.environ["XB_PYTHON_DIR"]) / "python.exe")
            if os.environ.get("XB_PYTHON_DIR")
            else None
        ),
        launcher,
        os.environ.get("LocalAppData") and str(
            Path(os.environ["LocalAppData"]) / "Programs" / "Python" / "Python310" / "python.exe"
        ),
        sys.executable,
        *_where_python_paths(),
    ]
    paths: list[Path] = []
    seen: set[str] = set()
    for raw in raw_candidates:
        if not raw:
            continue
        path = Path(raw).expanduser()
        key = os.path.normcase(str(path))
        if key in seen:
            continue
        seen.add(key)
        paths.append(path)
    return paths


def python_spec_for_venv(python_version: str) -> str:
    """Prefer the verified local CPython 3.10 over uv's managed interpreter cache."""
    requested = _wheel_py_tag(python_version)
    if requested != "py310":
        return python_version
    for path in _candidate_python_paths(python_version):
        if _path_is_file(path) and _python_minor_version(path) == "3.10":
            return str(path)
    return python_version


def ensure_venv(uv: str, venv_dir: Path, python_version: str) -> None:
    """Create a venv, rebuilding stale or unreadable environments."""
    py_path = venv_python(venv_dir)
    if _path_exists(py_path):
        ver = _python_minor_version(py_path)
        if ver == python_version:
            return
        print(
            c(
                "y",
                f"    现有 {venv_dir.name} 为 Python {ver or '不可运行/未知'}，需要 {python_version}，重建中 …",
            )
        )
        shutil.rmtree(venv_dir, ignore_errors=True)
    elif _path_exists(venv_dir):
        print(c("y", f"    现有 {venv_dir.name} 不完整，重建中 …"))
        shutil.rmtree(venv_dir, ignore_errors=True)

    spec = python_spec_for_venv(python_version)
    if spec != python_version:
        print(c("g", f"    使用已验证 Python {python_version}: {spec}"))
    run(uv_cmd(uv, "venv", "--python", spec, str(venv_dir)))


# ---------- 环境/前置检查 ----------
def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def find_nvidia_smi() -> str | None:
    """Locate nvidia-smi even when it is not exposed through PATH."""
    found = shutil.which("nvidia-smi")
    if found:
        return found

    candidates: list[Path] = []
    windir = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
    if windir:
        win = Path(windir)
        candidates += [
            win / "System32" / "nvidia-smi.exe",
            win / "Sysnative" / "nvidia-smi.exe",
        ]
    for root in {os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432")}:
        if root:
            candidates.append(Path(root) / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe")

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def detect_gpu_stack() -> str:
    """Return cpu, directml, cu121 or cu128 based on the detected GPU."""
    smi = find_nvidia_smi()
    caps: list[float] = []
    if smi:
        try:
            subprocess.run([smi], capture_output=True, check=True, timeout=15)
            out = subprocess.run(
                [smi, "--query-gpu=compute_cap", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            for line in out.stdout.splitlines():
                try:
                    caps.append(float(line.strip()))
                except ValueError:
                    continue
            if any(cap >= 12.0 for cap in caps):
                return "cu128"
            if any(cap >= 5.0 for cap in caps):
                return "cu121"
        except (OSError, subprocess.SubprocessError):
            pass

        if not caps:
            try:
                out = subprocess.run(
                    [smi, "--query-gpu=name", "--format=csv,noheader"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                names = out.stdout.strip()
                if re.search(r"RTX\s*50\d0", names, flags=re.IGNORECASE):
                    return "cu128"
                if names:
                    return "cu121"
            except (OSError, subprocess.SubprocessError):
                pass

    if os.name == "nt":
        try:
            out = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
            if re.search(r"\bAMD\b|Radeon", out.stdout, flags=re.IGNORECASE):
                return "directml"
        except (OSError, subprocess.SubprocessError):
            pass
    return "cpu"


def detect_gpu() -> bool:
    return detect_gpu_stack() != "cpu"


def detect_blackwell() -> bool:
    return detect_gpu_stack() == "cu128"


def _uv_exe_name() -> str:
    return "uv.exe" if os.name == "nt" else "uv"


def _python_script_dirs() -> list[Path]:
    """Return likely script dirs for the Python running this installer."""
    dirs: list[Path] = []
    candidates = [
        Path(sys.executable).parent,
        Path(sys.executable).parent / "Scripts",
    ]
    for scheme in ("nt_user", "posix_user", None):
        try:
            value = sysconfig.get_path("scripts", scheme=scheme) if scheme else sysconfig.get_path("scripts")
        except (KeyError, ValueError):
            continue
        if value:
            candidates.append(Path(value))
    for path in candidates:
        if path not in dirs:
            dirs.append(path)
    return dirs


def _find_local_uv() -> Path | None:
    for scripts in _python_script_dirs():
        exe = scripts / _uv_exe_name()
        if exe.exists():
            return exe
    return None


def _pip_install_uv(use_mirror: bool = True) -> None:
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--user",
        "--upgrade",
        "uv",
        "--disable-pip-version-check",
    ]
    local_args = _uv_bootstrap_wheelhouse_args()
    if local_args:
        try:
            run(cmd + local_args)
            return
        except subprocess.CalledProcessError:
            if _wheelhouse_strict():
                raise
            print(c("y", "    自带 uv wheel 安装失败，回退在线 PyPI 安装 …"))
    if use_mirror and PYPI_MIRROR:
        cmd += ["--index-url", PYPI_MIRROR]
    elif not use_mirror:
        cmd += ["--index-url", PYPI_FALLBACK_INDEX]
    run(cmd)


def ensure_uv() -> str:
    """确保 uv 可用；Python 已安装时自动把 uv 装到用户 Scripts 目录。"""
    found = shutil.which("uv")
    if found:
        return found
    local = _find_local_uv()
    if local:
        os.environ["PATH"] = str(local.parent) + os.pathsep + os.environ.get("PATH", "")
        return str(local)

    print(c("y", "    未检测到 uv，正在通过当前 Python 自动安装到用户目录 …"))
    try:
        run([sys.executable, "-m", "ensurepip", "--upgrade"])
    except subprocess.CalledProcessError:
        print(c("y", "    ensurepip 未完成，继续尝试使用现有 pip 安装 uv …"))
    try:
        _pip_install_uv(use_mirror=True)
    except subprocess.CalledProcessError:
        if _uv_bootstrap_wheelhouse_args() and _wheelhouse_strict():
            raise
        warn_pypi_fallback()
        _pip_install_uv(use_mirror=False)

    local = _find_local_uv()
    if local:
        os.environ["PATH"] = str(local.parent) + os.pathsep + os.environ.get("PATH", "")
        return str(local)
    found = shutil.which("uv")
    if found:
        return found
    raise RuntimeError("uv 已尝试自动安装，但没有找到 uv 可执行文件。请查看上方 pip 输出并重试。")


def uv_cmd(uv: str, *args: str) -> list[str]:
    return [uv, *args]


def uv_pip_install(
    uv: str,
    py: str,
    *args: str,
    index: str | None = None,
    component: str | None = None,
    gpu_stack: str | None = None,
    python_version: str | None = None,
) -> None:
    """`uv pip install`；失败时自动换源/加 --reinstall 重试。

    用于自愈被中断的半成品安装：典型表现是 site-packages 里留下空的
    `*.dist-info` 目录（缺 METADATA），再次安装会报
    `failed to open file ... METADATA (os error 2)`。--reinstall 会强制
    重新下载并覆盖，绕过损坏的旧元数据。国内镜像偶发 403/残缺 wheel 时
    先切官方 PyPI，避免重复撞同一个失效镜像。
    """
    shared = CONSOLIDATED_RUNTIME and component in CORE_COMPONENTS
    if shared:
        if CORE_CONSTRAINTS is None or not CORE_CONSTRAINTS.is_file():
            raise RuntimeError("共享依赖尚未通过整体解析，拒绝修改环境")
        args = ("-c", str(CORE_CONSTRAINTS), *args)
    local_args = _wheelhouse_args(
        component=component,
        gpu_stack=gpu_stack,
        python_version=python_version,
    )

    def build(
        reinstall: bool,
        use_mirror: bool = True,
        use_wheelhouse: bool = False,
    ) -> list[str]:
        extra = ["--reinstall"] if reinstall else []
        cmd = uv_cmd(uv, "pip", "install", *extra, "--python", py)
        if use_wheelhouse:
            cmd += local_args
        cmd += list(args)
        if not use_wheelhouse:
            if shared and CORE_PROFILE is not None:
                cmd += pypi_index_args(use_mirror=use_mirror) + ["--torch-backend", "cu128"]
            else:
                cmd += pypi_index_args(index, use_mirror=use_mirror)
        if shared and CORE_COMPAT_WHEEL is not None:
            cmd += ["--find-links", str(CORE_COMPAT_WHEEL.parent)]
        return cmd

    if local_args:
        try:
            run(build(reinstall=False, use_wheelhouse=True))
            return
        except subprocess.CalledProcessError as exc:
            if shared:
                raise
            print(c("y", "    自带 whl 安装失败，尝试 --reinstall 修复旧环境 …"))
            try:
                run(build(reinstall=True, use_wheelhouse=True))
                return
            except subprocess.CalledProcessError as reinstall_exc:
                exc = reinstall_exc
            if _wheelhouse_strict():
                raise exc
            print(c("y", "    自带 whl 安装失败，回退在线 PyPI 安装 …"))

    try:
        run(build(reinstall=False))
    except subprocess.CalledProcessError:
        if shared:
            # A conflict is not fixed by replacing the entire environment.
            # Retry the same locked set on the fallback index only once.
            if PYPI_MIRROR == PYPI_FALLBACK_INDEX:
                raise
            warn_pypi_fallback()
            run(build(reinstall=False, use_mirror=False))
            return
        if PYPI_MIRROR != PYPI_FALLBACK_INDEX:
            warn_pypi_fallback()
            try:
                run(build(reinstall=False, use_mirror=False))
                return
            except subprocess.CalledProcessError:
                print(c("y", "    Fallback PyPI mirror retry failed; trying --reinstall once..."))
                run(build(reinstall=True, use_mirror=False))
                return
        print(c("y", "    安装失败，尝试 --reinstall 重装以修复损坏/残缺的旧安装 …"))
        run(build(reinstall=True))


def make_pip(
    uv: str,
    py: str,
    *,
    component: str,
    gpu_stack: str,
    python_version: str,
):
    def pip(*args: str, index: str | None = None) -> None:
        uv_pip_install(
            uv,
            py,
            *args,
            index=index,
            component=component,
            gpu_stack=gpu_stack,
            python_version=python_version,
        )

    return pip


# ---------- 下载工具 ----------
def uv_sync(uv: str, cwd: Path) -> None:
    try:
        run(uv_cmd(uv, "sync", *pypi_index_args()), cwd=cwd)
    except subprocess.CalledProcessError:
        if PYPI_MIRROR == PYPI_FALLBACK_INDEX:
            raise
        warn_pypi_fallback()
        run(uv_cmd(uv, "sync", *pypi_index_args(use_mirror=False)), cwd=cwd)


def _progress(blocks: int, bs: int, total: int) -> None:
    if total <= 0:
        return
    done = min(blocks * bs, total)
    pct = done * 100 // total
    bar = "#" * (pct // 4)
    print(f"\r    [{bar:<25}] {pct:3d}%  {done // 1048576}/{total // 1048576} MB", end="")


def hf_urls(path: str) -> list[str]:
    """HuggingFace 资源的镜像 URL 列表（镜像优先）。path 以 / 开头。"""
    return [host + path for host in HF_HOSTS]


def gh_urls(url: str) -> list[str]:
    """GitHub Release 资源的镜像 URL 列表（直连优先，再走 ghproxy）。"""
    return [prefix + url for prefix in GH_PROXIES]


def _download_one(url: str, tmp: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp, open(tmp, "wb") as f:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
            downloaded += len(chunk)
            _progress(downloaded // (1024 * 256), 1024 * 256, total)
    print()


def download(urls: "str | list[str]", dest: Path) -> None:
    """从一个或多个候选 URL 下载（逐个回退），任一成功即可。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        print(c("g", f"    已存在，跳过：{dest.name}"))
        return
    candidates = [urls] if isinstance(urls, str) else list(urls)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last_err: Exception | None = None
    for i, url in enumerate(candidates, 1):
        tag = "" if len(candidates) == 1 else f"[源 {i}/{len(candidates)}] "
        print(f"    {tag}下载 {url}")
        try:
            _download_one(url, tmp)
            tmp.replace(dest)
            return
        except Exception as exc:  # noqa: BLE001 - 换下一个镜像继续
            last_err = exc
            print(c("y", f"    此源失败（{exc}），尝试下一个镜像 …"))
            tmp.unlink(missing_ok=True)
    raise RuntimeError(f"所有下载源均失败：{last_err}")


def extract_zip(zip_path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(dest_dir)


def copy_bundled(rel: str, dest: Path) -> bool:
    """若自带模型目录里有该资源（文件或目录），就部署到 dest。

    复制成功返回 True；自带目录缺失该资源返回 False（交由调用方回退联网下载）。
    """
    src = ASSETS_MODELS_DIR / rel
    if not src.exists():
        return False
    if src.is_dir():
        # 目录：始终合并复制（dirs_exist_ok）。不能因为目标目录已存在就跳过——
        # so-vits-svc 仓库克隆后 pretrain/nsf_hifigan 已存在但只含占位文件，
        # 若跳过会导致真正的 model/config.json 不被放入，推理时报 FileNotFoundError。
        dest.mkdir(parents=True, exist_ok=True)
        print(f"    自带模型，本地复制目录 {src.name}/ …")
        # Use the same atomic file deployment below. copytree overwrites files
        # in place, which would also modify the source of an existing hardlink.
        for child in src.iterdir():
            copy_bundled(str(Path(rel) / child.name), dest / child.name)
        print(c("g", f"    复制完成：{dest.name}/"))
        return True
    # 文件：大小相同时先保留；只有内容也一致的大权重才允许去重。
    # 这能自愈旧安装器下载到的残缺底模（如 16.5MB 的 ContentVec 应为 1268MB）。
    if dest.exists() and dest.is_file() and dest.stat().st_size == src.stat().st_size:
        if _is_large_model_file(src):
            try:
                already_linked = os.path.samefile(src, dest)
            except OSError:
                already_linked = False
            if not already_linked:
                if _file_sha256(src) != _file_sha256(dest):
                    print(c("y", f"    同名权重内容不同，保留现有文件且不去重：{dest.name}"))
                    return True
                _link_or_copy_model(src, dest)
                print(c("g", f"    已复用自带权重存储：{dest.name}"))
                return True
        print(c("g", f"    已存在且大小一致，跳过：{dest.name}"))
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"    自带模型，本地部署 {src.name} …")
    # Large immutable weights can share storage with the installer payload on
    # the same volume.  Fall back to a normal copy for cross-volume installs.
    if _is_large_model_file(src):
        _link_or_copy_model(src, dest)
    else:
        _atomic_copy_model(src, dest)
    print(c("g", f"    部署完成：{dest.name}"))
    return True


def _is_large_model_file(path: Path) -> bool:
    try:
        return (path.suffix.lower() in {".pt", ".pth", ".ckpt", ".onnx", ".safetensors", ".bin"}
                and path.is_file() and path.stat().st_size >= 32 * 1024 * 1024)
    except OSError:
        return False


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_copy_model(src: Path, dest: Path, *, link: bool = False) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".xb-model-", dir=dest.parent) as work:
        temporary = Path(work) / "payload"
        if link:
            try:
                os.link(src, temporary)
            except OSError:
                shutil.copy2(src, temporary)
        else:
            shutil.copy2(src, temporary)
        temporary.replace(dest)


def _link_or_copy_model(src: Path, dest: Path) -> None:
    _atomic_copy_model(src, dest, link=True)


def _normalize_rvc_rmvpe_checkpoint(py: Path, src: Path, dest: Path) -> bool:
    script = r"""
import pathlib
import sys

import torch

src = pathlib.Path(sys.argv[1])
dest = pathlib.Path(sys.argv[2])

def load_checkpoint(path):
    try:
        return torch.load(path, map_location="cpu", weights_only=False)
    except TypeError:
        return torch.load(path, map_location="cpu")

obj = load_checkpoint(src)
wrapped = False
state = obj.get("model") if isinstance(obj, dict) else None
if isinstance(state, dict):
    obj = state
    wrapped = True
if isinstance(obj, dict):
    cleaned = {key: val for key, val in obj.items() if not key.startswith("unet.tf.")}
    if len(cleaned) != len(obj):
        obj = cleaned
        wrapped = True
expected = ("unet.encoder.bn.weight", "cnn.weight", "fc.1.bias")
if not isinstance(obj, dict) or not any(key in obj for key in expected):
    raise SystemExit("incompatible RMVPE checkpoint")
if src.resolve() == dest.resolve() and not wrapped:
    raise SystemExit(0)
dest.parent.mkdir(parents=True, exist_ok=True)
tmp = dest.with_name(dest.name + ".xbtmp")
torch.save(obj, tmp)
tmp.replace(dest)
"""
    try:
        out = subprocess.run(
            [str(py), "-c", script, str(src), str(dest)],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(c("y", f"    RMVPE 底模格式修复失败：{exc}"))
        return False
    if out.returncode == 0:
        return True
    tail = (out.stderr or out.stdout or "").strip().splitlines()[-1:]
    print(c("y", f"    RMVPE 底模格式不兼容，跳过：{src} {' '.join(tail)}"))
    return False


def _find_rvc_base_source(*rels: str) -> Path | None:
    roots = [ASSETS_MODELS_DIR, PRETRAIN_DIR]
    for root in roots:
        for rel in rels:
            rel_path = Path(rel)
            for candidate in (root / rel_path, root / rel_path.name):
                if _is_large_model_file(candidate):
                    return candidate
    return None


def seed_rvc_base_models(py: Path) -> None:
    """把自带底模预置到 rvc-python 包内，避免首次推理再连 HuggingFace。"""
    try:
        out = subprocess.run(
            [
                str(py),
                "-c",
                "import pathlib,rvc_python;print(pathlib.Path(rvc_python.__file__).resolve().parent)",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(c("y", f"    定位 rvc-python 失败，跳过 RVC 底模预置：{exc}"))
        return
    if out.returncode != 0 or not out.stdout.strip():
        tail = (out.stderr or out.stdout or "").strip().splitlines()[-1:]
        print(c("y", f"    rvc-python 尚不可导入，跳过 RVC 底模预置：{' '.join(tail)}"))
        return

    base_dir = Path(out.stdout.strip()) / "base_model"
    base_dir.mkdir(parents=True, exist_ok=True)
    mapping = {
        "hubert_base.pt": (
            "rvc/hubert_base.pt",
            "pretrain/hubert_base.pt",
            "pretrain/checkpoint_best_legacy_500.pt",
            "checkpoint_best_legacy_500.pt",
        ),
        "rmvpe.pt": (
            "rvc/rmvpe.pt",
            "pretrain/rmvpe.pt",
            "rmvpe.pt",
        ),
        "rmvpe.onnx": (
            "rvc/rmvpe.onnx",
            "pretrain/rmvpe.onnx",
            "rmvpe.onnx",
        ),
    }
    for name, rels in mapping.items():
        dest = base_dir / name
        src = _find_rvc_base_source(*rels)
        if name == "rmvpe.pt":
            if _is_large_model_file(dest) and _normalize_rvc_rmvpe_checkpoint(py, dest, dest):
                print(c("g", f"    RVC 底模已存在/已修复：{name}"))
                continue
            if src is None:
                print(c("y", f"    未找到自带 RVC 底模 {name}，运行时将尝试镜像下载"))
                continue
            if _normalize_rvc_rmvpe_checkpoint(py, src, dest):
                print(c("g", f"    RVC 底模已预置：{name}"))
            continue
        if _is_large_model_file(dest):
            try:
                if src is None or dest.stat().st_size == src.stat().st_size:
                    print(c("g", f"    RVC 底模已存在，跳过：{name}"))
                    continue
            except OSError:
                pass
        if src is None:
            if name != "rmvpe.onnx":
                print(c("y", f"    未找到自带 RVC 底模 {name}，运行时将尝试镜像下载"))
            continue
        _link_or_copy_model(src, dest)
        print(c("g", f"    RVC 底模已预置：{name}"))


# ---------- 各安装步骤 ----------
def step_app(uv: str) -> None:
    hr("1/12 主程序环境 app/.venv")
    uv_sync(uv, APP_DIR)
    print(c("g", "主程序环境就绪"))


def step_plugins(uv: str) -> None:
    """Create the small, dependency-free runtime used by Python plugins.

    Third-party packages are bundled into each plugin's ``vendor`` directory
    by the SDK. Keeping a dedicated interpreter avoids depending on whichever
    AI environment happens to be installed on the target machine.
    """
    hr("2/12 Python 插件运行环境 .venv-plugins")
    ensure_venv(uv, PLUGIN_VENV, PYTHON_FOR_ENGINES)
    py = venv_python(PLUGIN_VENV)
    if not py.exists():
        raise RuntimeError(f"插件 Python 环境创建失败：{py}")
    print(c("g", "Python 插件运行环境就绪"))


def step_web() -> None:
    hr("3/12 前端构建 web/dist")
    if not have("npm"):
        raise RuntimeError("未检测到 npm，请先安装 Node.js LTS 后重试（或 --skip-web）")
    # 优先 npm ci（依赖 lock）；无 lock 时回退 npm install
    if (WEB_DIR / "package-lock.json").exists():
        run(["npm", "ci"], cwd=WEB_DIR)
    else:
        run(["npm", "install"], cwd=WEB_DIR)
    run(["npm", "run", "build"], cwd=WEB_DIR)
    print(c("g", "前端构建完成"))


def step_uvr(uv: str, gpu_stack: str) -> None:
    hr("4/12 共享人声分离环境 runtimes/core-*（audio-separator）")
    use_blackwell = gpu_stack == "cu128"
    use_cuda = gpu_stack in {"cu121", "cu128"}
    use_directml = gpu_stack == "directml"
    venv = runtime_venv("uvr", UVR_VENV)
    ensure_venv(uv, venv, PYTHON_FOR_ENGINES)
    py = str(venv_python(venv))
    pip = make_pip(
        uv,
        py,
        component="uvr",
        gpu_stack=gpu_stack,
        python_version=PYTHON_FOR_ENGINES,
    )
    _repair_broken_wheel_metadata(
        venv,
        ("torch", "torchaudio", "torchvision", "torch-directml"),
        component="uvr",
        gpu_stack=gpu_stack,
        python_version=PYTHON_FOR_ENGINES,
    )

    # uv venv 默认不含 setuptools，部分库运行时需要 pkg_resources，先补齐
    # （setuptools 81+ 已移除 pkg_resources，钉 <81）
    pip("setuptools<81", "wheel")
    if not use_directml:
        # Switching an existing installation back to CUDA/CPU must also remove
        # the old provider; otherwise auto detection would keep selecting DML.
        run(uv_cmd(uv, "pip", "uninstall", "--python", py, "torch-directml"))
    # UVR 严格跟随全局推理栈：NVIDIA 用 CUDA，Windows AMD 用
    # torch-directml + ONNX Runtime DirectML，其余环境使用 CPU。
    if use_blackwell:
        torch_specs = [
            f"torch=={TORCH_BLACKWELL_VER}",
            f"torchaudio=={TORCHAUDIO_BLACKWELL_VER}",
            f"torchvision=={TORCHVISION_BLACKWELL_VER}",
        ]
        torch_index = TORCH_BLACKWELL_INDEX
        torch_label = "cu128"
        pip(*torch_specs, index=torch_index)
    elif use_cuda:
        torch_specs = ["torch==2.5.1", "torchaudio==2.5.1", "torchvision==0.20.1"]
        torch_index = TORCH_CUDA_INDEX
        torch_label = "cu121"
        pip(*torch_specs, index=torch_index)
    elif use_directml:
        torch_specs = []
        torch_index = None
        torch_label = "DirectML"
        _install_directml_runtime(pip)
    else:
        torch_specs = ["torch", "torchaudio"]
        torch_index = TORCH_CPU_INDEX
        torch_label = "CPU"
        pip(*torch_specs, index=torch_index)
    # ORT 的不同发行包共享同一个 onnxruntime 命名空间。切换显卡栈时先移除
    # 冲突发行包，避免旧 CUDA/CPU provider 覆盖 DirectML provider（反之亦然）。
    if use_directml:
        run(uv_cmd(uv, "pip", "uninstall", "--python", py, "onnxruntime", "onnxruntime-gpu"))
    elif use_cuda:
        run(uv_cmd(uv, "pip", "uninstall", "--python", py, "onnxruntime", "onnxruntime-directml"))
    else:
        run(uv_cmd(uv, "pip", "uninstall", "--python", py, "onnxruntime-gpu", "onnxruntime-directml"))

    # audio-separator 的不同 extra 分别部署 CUDA / DirectML / CPU provider。
    if use_cuda:
        # 安装 audio-separator 时也带上 PyTorch wheel 源，避免依赖解析把 CUDA torch 换成 PyPI CPU 版。
        # onnx2torch-py313 declares a broad torchvision range; without constraints
        # uv may select a newer torchvision whose metadata forces a newer,
        # multi-gigabyte Torch download. Pin the already validated local wheels.
        constraint_file = ROOT / ".tmp" / f"uvr-torch-{gpu_stack}.constraints.txt"
        constraint_file.parent.mkdir(parents=True, exist_ok=True)
        local_suffix = "+cu128" if use_blackwell else "+cu121"
        constraint_file.write_text(
            "\n".join(
                (
                    f"torch=={TORCH_BLACKWELL_VER}{local_suffix}" if use_blackwell else "torch==2.5.1+cu121",
                    f"torchaudio=={TORCHAUDIO_BLACKWELL_VER}{local_suffix}" if use_blackwell else "torchaudio==2.5.1+cu121",
                    f"torchvision=={TORCHVISION_BLACKWELL_VER}{local_suffix}" if use_blackwell else "torchvision==0.20.1+cu121",
                )
            )
            + "\n",
            encoding="ascii",
        )
        try:
            pip(
                "-c",
                str(constraint_file),
                f"audio-separator[gpu]=={AUDIO_SEPARATOR_VER}",
                index=torch_index,
            )
        finally:
            constraint_file.unlink(missing_ok=True)
        _reaffirm_torch_wheels(
            uv,
            py,
            torch_specs,
            torch_index,
            torch_label,
            component="uvr",
            gpu_stack=gpu_stack,
            python_version=PYTHON_FOR_ENGINES,
        )
        _verify_cuda_torch(py, "UVR")
    elif use_directml:
        pip(f"audio-separator[dml]=={AUDIO_SEPARATOR_VER}")
        _reaffirm_directml_runtime(
            uv,
            py,
            component="uvr",
            python_version=PYTHON_FOR_ENGINES,
        )
        _verify_directml_torch(py, "UVR")
        _verify_uvr_directml(py)
    else:
        pip(f"audio-separator[cpu]=={AUDIO_SEPARATOR_VER}")
    print(c("g", "分离环境就绪"))


def step_pymss(uv: str, gpu_stack: str) -> None:
    """Install optional PyMSS in its own environment.

    PyMSS models are intentionally downloaded later from the model page so the
    user can choose a catalog model instead of consuming disk space up front.
    """
    hr("5/12 可选 PyMSS 分离环境 .venv-pymss")
    ensure_venv(uv, PYMSS_VENV, PYTHON_FOR_ENGINES)
    py = str(venv_python(PYMSS_VENV))
    # PyMSS 2.0.x requires Torch 2.7.1. Pre-Blackwell NVIDIA uses cu126 and
    # Blackwell uses cu128; keep the component wheelhouse aligned with the
    # actual runtime stack so offline installs stay deterministic.
    if gpu_stack == "cu128":
        pymss_stack = "cu128"
    elif gpu_stack in {"cu121", "cu126"}:
        pymss_stack = "cu126"
    else:
        pymss_stack = gpu_stack
    pip = make_pip(
        uv,
        py,
        component="pymss",
        gpu_stack=pymss_stack,
        python_version=PYTHON_FOR_ENGINES,
    )
    if pymss_stack == "cu128":
        torch_index = TORCH_BLACKWELL_INDEX
    elif pymss_stack == "cu126":
        torch_index = TORCH_PYMSS_CUDA_INDEX
    else:
        torch_index = TORCH_CPU_INDEX
    # A CPU build with the same Torch version satisfies ``torch==...`` in uv
    # and would otherwise be kept when switching an existing PyMSS venv to CUDA.
    # Remove the provider first so the selected cu126/cu128 wheel is installed.
    if Path(py).is_file():
        run(uv_cmd(uv, "pip", "uninstall", "--python", py, "torch", "torchaudio", "torchvision"))
    pip(
        f"torch=={PYMSS_TORCH_VER}",
        f"torchaudio=={PYMSS_TORCHAUDIO_VER}",
        index=torch_index,
    )
    pip(f"pymss=={PYMSS_VERSION}")
    print(c("g", "PyMSS 环境就绪；请在模型管理页选择并下载分离模型"))


def fetch_sovits() -> None:
    """获取 so-vits-svc 4.1 仓库：优先 git clone，无 git 时下载分支 ZIP 解压。"""
    if (SOVITS_DIR / "inference" / "infer_tool.py").exists():
        print(c("g", "    so-vits-svc 仓库已存在，跳过获取"))
        return
    ENGINES_DIR.mkdir(parents=True, exist_ok=True)
    if SOVITS_DIR.exists():
        shutil.rmtree(SOVITS_DIR, ignore_errors=True)

    if have("git"):
        run(
            [
                "git", "clone", "--depth", "1", "-b", SOVITS_BRANCH,
                SOVITS_REPO_URL, str(SOVITS_DIR),
            ]
        )
        return

    # 没有 git：下载 GitHub 分支 ZIP 解压（无需安装任何额外工具）
    print(c("y", "    未检测到 git，改用下载 ZIP 方式获取仓库 …"))
    with tempfile.TemporaryDirectory() as td:
        zp = Path(td) / "so-vits-svc.zip"
        download(gh_urls(SOVITS_ZIP_URL), zp)
        extract_zip(zp, Path(td))
        # ZIP 解压出形如 so-vits-svc-4.1-Stable/ 的顶层目录
        marker = next(Path(td).rglob("inference/infer_tool.py"), None)
        if marker is None:
            raise RuntimeError("下载的 so-vits-svc 压缩包结构异常，未找到 inference/infer_tool.py")
        repo_root = marker.parent.parent
        shutil.move(str(repo_root), str(SOVITS_DIR))


def fetch_seedvc() -> None:
    """获取 Seed-VC 仓库：优先 git clone，无 git 时下载 main 分支 ZIP。"""
    if (SEEDVC_DIR / "inference.py").exists():
        print(c("g", "    Seed-VC 仓库已存在，跳过获取"))
        return
    ENGINES_DIR.mkdir(parents=True, exist_ok=True)
    if SEEDVC_DIR.exists():
        shutil.rmtree(SEEDVC_DIR, ignore_errors=True)

    if have("git"):
        run(["git", "clone", "--depth", "1", SEEDVC_REPO_URL, str(SEEDVC_DIR)])
        return

    print(c("y", "    未检测到 git，改用下载 ZIP 方式获取 Seed-VC 仓库 …"))
    with tempfile.TemporaryDirectory() as td:
        zp = Path(td) / "seed-vc.zip"
        download(gh_urls(SEEDVC_ZIP_URL), zp)
        extract_zip(zp, Path(td))
        marker = next(Path(td).rglob("inference.py"), None)
        if marker is None:
            raise RuntimeError("下载的 Seed-VC 压缩包结构异常，未找到 inference.py")
        repo_root = marker.parent
        shutil.move(str(repo_root), str(SEEDVC_DIR))


def fetch_ddsp() -> None:
    """获取 DDSP-SVC 6.3 仓库：优先 git clone，无 git 时下载分支 ZIP。"""
    if (DDSP_DIR / "main_reflow.py").exists():
        print(c("g", "    DDSP-SVC 仓库已存在，跳过获取"))
        return
    ENGINES_DIR.mkdir(parents=True, exist_ok=True)
    if DDSP_DIR.exists():
        shutil.rmtree(DDSP_DIR, ignore_errors=True)
    if have("git"):
        try:
            run(["git", "clone", "--depth", "1", "-b", DDSP_BRANCH, DDSP_REPO_URL, str(DDSP_DIR)])
            return
        except subprocess.CalledProcessError:
            print(c("y", "    git clone 失败，改用分支 ZIP 下载 …"))
            shutil.rmtree(DDSP_DIR, ignore_errors=True)

    print(c("y", "    正在用 ZIP 方式获取 DDSP-SVC 仓库 …"))
    with tempfile.TemporaryDirectory() as td:
        archive = Path(td) / "ddsp-svc.zip"
        download(gh_urls(DDSP_ZIP_URL), archive)
        extract_zip(archive, Path(td))
        marker = next(Path(td).rglob("main_reflow.py"), None)
        if marker is None:
            raise RuntimeError("下载的 DDSP-SVC 压缩包结构异常，未找到 main_reflow.py")
        shutil.move(str(marker.parent), str(DDSP_DIR))


def seed_ddsp_base_models() -> None:
    """部署 DDSP-SVC 推理需要的 ContentVec、RMVPE 与 NSF-HiFiGAN。"""
    contentvec = DDSP_DIR / "pretrain" / "contentvec" / "pytorch_model.bin"
    if not _is_large_model_file(contentvec):
        contentvec.unlink(missing_ok=True)
        download(hf_urls(DDSP_CONTENTVEC_HF), contentvec)

    rmvpe = DDSP_DIR / "pretrain" / "rmvpe" / "model.pt"
    bundled_rmvpe = ASSETS_MODELS_DIR / "pretrain" / "rmvpe.pt"
    if _is_large_model_file(bundled_rmvpe):
        if not _is_large_model_file(rmvpe) or rmvpe.stat().st_size != bundled_rmvpe.stat().st_size:
            _link_or_copy_model(bundled_rmvpe, rmvpe)
            print(c("g", "    DDSP-SVC RMVPE 已预置"))
    else:
        print(c("y", "    未找到完整的 RMVPE 自带模型，请改用 harvest/dio 或手动部署"))

    vocoder = DDSP_DIR / "pretrain" / "nsf_hifigan"

    def pc_vocoder_ready(path: Path) -> bool:
        try:
            cfg = json.loads((path / "config.json").read_text(encoding="utf-8"))
            return bool(cfg.get("pc_aug")) and _is_large_model_file(path / "model")
        except (OSError, json.JSONDecodeError):
            return False

    if pc_vocoder_ready(vocoder):
        print(c("g", "    DDSP-SVC PC-NSF-HiFiGAN 已预置"))
        return

    bundled_vocoder = ASSETS_MODELS_DIR / "pretrain" / "pc_nsf_hifigan"
    bundled_vocoder_config = bundled_vocoder / "config.json"
    bundled_vocoder_model = bundled_vocoder / "model.ckpt"
    try:
        bundled_config = json.loads(bundled_vocoder_config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        bundled_config = {}
    if bool(bundled_config.get("pc_aug")) and _is_large_model_file(bundled_vocoder_model):
        vocoder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundled_vocoder_config, vocoder / "config.json")
        _link_or_copy_model(bundled_vocoder_model, vocoder / "model")
        for notice_name in ("NOTICE.txt", "NOTICE.zh-CN.txt", "STATEMENTS.txt"):
            notice = bundled_vocoder / notice_name
            if notice.is_file():
                shutil.copy2(notice, vocoder / notice_name)
        print(c("g", "    DDSP-SVC PC-NSF-HiFiGAN 2025.02 已从安装包部署"))
        return

    try:
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "pc-nsf-hifigan.zip"
            unpacked = Path(td) / "unpacked"
            download(gh_urls(DDSP_NSF_HIFIGAN_GH), archive)
            extract_zip(archive, unpacked)
            config_file = next(
                (
                    item
                    for item in unpacked.rglob("config.json")
                    if json.loads(item.read_text(encoding="utf-8")).get("pc_aug")
                ),
                None,
            )
            if config_file is None:
                raise RuntimeError("PC-NSF-HiFiGAN 压缩包缺少有效 config.json")
            weights = next(
                (
                    item
                    for item in config_file.parent.iterdir()
                    if item.is_file()
                    and item.name != "config.json"
                    and item.stat().st_size >= 32 * 1024 * 1024
                ),
                None,
            )
            if weights is None:
                raise RuntimeError("PC-NSF-HiFiGAN 压缩包缺少模型权重")
            vocoder.mkdir(parents=True, exist_ok=True)
            shutil.copy2(config_file, vocoder / "config.json")
            _link_or_copy_model(weights, vocoder / "model")
            print(c("g", "    DDSP-SVC PC-NSF-HiFiGAN 2025.02 已预置"))
    except Exception as exc:  # noqa: BLE001 - offline installer keeps a compatible fallback
        print(c("y", f"    PC-NSF-HiFiGAN 下载失败（{exc}），回退到自带 NSF-HiFiGAN"))
        if not copy_bundled("pretrain/nsf_hifigan", vocoder):
            raise RuntimeError("DDSP-SVC 缺少 NSF-HiFiGAN model/config.json") from exc


def seed_seedvc_base_models(py: Path) -> None:
    """Prestage SeedVC checkpoints and verify the bundled offline snapshots."""
    checkpoints = SEEDVC_DIR / "checkpoints"
    checkpoints.mkdir(parents=True, exist_ok=True)
    rmvpe_src = ASSETS_MODELS_DIR / "pretrain" / "rmvpe.pt"
    rmvpe_dest = checkpoints / "rmvpe.pt"
    rmvpe_marker = rmvpe_dest.with_name(rmvpe_dest.name + ".xb-normalized")
    if not _is_large_model_file(rmvpe_src):
        print(c("y", "    未找到完整的 SeedVC RMVPE 自带模型，运行时将尝试联网下载"))
    elif _is_large_model_file(rmvpe_dest) and rmvpe_marker.is_file():
        print(c("g", "    SeedVC RMVPE 已预置，跳过"))
    elif _normalize_rvc_rmvpe_checkpoint(py, rmvpe_src, rmvpe_dest):
        rmvpe_marker.write_text("xb-svcb seedvc rmvpe v1\n", encoding="ascii")
        print(c("g", "    SeedVC RMVPE 已转换并预置"))

    campplus_src = ASSETS_MODELS_DIR / "seedvc" / "campplus_cn_common.bin"
    campplus_dest = checkpoints / "campplus_cn_common.bin"
    if not campplus_src.is_file() or campplus_src.stat().st_size < 20 * 1024 * 1024:
        print(c("y", "    未找到完整的 SeedVC CampPlus 自带模型，运行时将尝试联网下载"))
    elif campplus_dest.is_file() and campplus_dest.stat().st_size == campplus_src.stat().st_size:
        print(c("g", "    SeedVC CampPlus 已预置，跳过"))
    else:
        _link_or_copy_model(campplus_src, campplus_dest)
        print(c("g", "    SeedVC CampPlus 已预置"))

    snapshots = (
        (
            ASSETS_MODELS_DIR / "seedvc" / "whisper-small",
            ("config.json", "preprocessor_config.json", "model.safetensors"),
            "Whisper Small",
        ),
        (
            ASSETS_MODELS_DIR / "seedvc" / "bigvgan_v2_44khz_128band_512x",
            ("config.json", "bigvgan_generator.pt"),
            "BigVGAN",
        ),
    )
    for folder, required, label in snapshots:
        missing = [name for name in required if not (folder / name).is_file()]
        if missing:
            print(c("y", f"    SeedVC {label} 本地快照不完整（缺少 {', '.join(missing)}），运行时将尝试联网下载"))
        else:
            print(c("g", f"    SeedVC {label} 本地快照就绪"))


def _venv_pyver(py: Path) -> str | None:
    """返回 venv 内 Python 的 '主.次' 版本号（如 '3.9'）；失败返回 None。"""
    return _python_minor_version(py)


def step_svc(uv: str, gpu_stack: str) -> None:
    hr("6/12 推理引擎 so-vits-svc + .venv-svc")
    fetch_sovits()

    use_blackwell = gpu_stack == "cu128"
    use_gpu = gpu_stack in {"cu121", "cu128"}
    use_directml = gpu_stack == "directml"

    # torch-directml 0.2.5 imports only on Python 3.10+; CUDA/CPU keep their
    # established versions to avoid changing already-validated dependency sets.
    target_py = _svc_python_for_stack(gpu_stack)
    ensure_venv(uv, SVC_VENV, target_py)
    py = str(venv_python(SVC_VENV))
    pip = make_pip(
        uv,
        py,
        component="svc",
        gpu_stack=gpu_stack,
        python_version=target_py,
    )

    # uv venv 默认不含 setuptools/pip，而 librosa 运行时要 `from pkg_resources import ...`
    # （pkg_resources 属于 setuptools），缺失会导致推理一加载 librosa 就 ModuleNotFoundError。
    # 注意：setuptools 81+ 已移除 pkg_resources，必须钉 <81 才仍带该模块。
    pip("setuptools<81", "wheel")
    req_win = SOVITS_DIR / "requirements_win.txt"
    req = SOVITS_DIR / "requirements.txt"
    req_file = req_win if req_win.exists() else req

    if use_directml:
        _install_directml_runtime(pip)
        if req_file.exists():
            filtered = _filter_requirements(
                req_file,
                extra_deny=DIRECTML_EXTRA_DENY,
                overrides=PYTHON310_REQ_OVERRIDES,
            )
            pip("-r", str(filtered))
            pip("matplotlib==3.7.5", "soundfile")
            pip(*SVC_FCPE_RUNTIME_DEPS)
        else:
            print(c("r", "    未找到 requirements，跳过依赖安装（请检查仓库）"))
        _reaffirm_directml_runtime(
            uv,
            py,
            component="svc",
            python_version=target_py,
        )
        _verify_directml_torch(py, "So-VITS-SVC")
        _verify_svc_fcpe_runtime(py)
        _verify_svc_matplotlib_runtime(py)
        print(
            c(
                "g",
                "推理环境就绪（AMD DirectML；checkpoint 先在 CPU 加载，RMVPE 使用 CPU 稳定路径）",
            )
        )
        return

    if use_blackwell:
        # 50 系：cu128 + torch2.7.1。torch.load 的 weights_only 由 svc_worker 在导入前还原；
        # torchaudio I/O 在 2.7 改走 torchcodec，svc_worker 用 soundfile 垫片规避哑音。
        pip(
            f"torch=={TORCH_BLACKWELL_VER}",
            f"torchaudio=={TORCHAUDIO_BLACKWELL_VER}",
            index=TORCH_BLACKWELL_INDEX,
        )
        if req_file.exists():
            # 自管 torch/torchaudio/torchvision/fairseq；numpy/pyworld 覆盖到 3.10 兼容版
            filtered = _filter_requirements(
                req_file,
                extra_deny=BLACKWELL_EXTRA_DENY,
                overrides=PYTHON310_REQ_OVERRIDES,
            )
            pip("-r", str(filtered))
            # 显式确保读写音频用的 soundfile 在位（svc_worker 的 torchaudio 垫片依赖它）
            pip("soundfile")
            pip(*SVC_FCPE_RUNTIME_DEPS)
            # matplotlib 在 3.10 用较新版本（3.7.5 也可，但 3.10 下放宽到 3.8.x 更易装）
            pip("matplotlib==3.8.4")
            # fairseq 单独装（py3.10 无官方 wheel，单列以便定位失败）
            _install_fairseq_blackwell(pip)
            # 兜底：fairseq 可能把 cu128 torch 换成同号 CPU 版 → 强制校正回 cu128
            _reaffirm_blackwell_torch(
                uv,
                py,
                component="svc",
                python_version=target_py,
            )
            # 修复早期错误补丁（weights_only 误插进 torch.device）；weights_only 兼容由
            # svc_worker 运行时 monkey-patch torch.load 处理
            _patch_fairseq_weights_only(venv_python(SVC_VENV))
        else:
            print(c("r", "    未找到 requirements，跳过依赖安装（请检查仓库）"))
        _verify_svc_fcpe_runtime(py)
        _verify_svc_matplotlib_runtime(py)
        print(c("g", "推理环境就绪（Blackwell/cu128）"))
        return

    # 老栈（40 系及以下 / CPU）：保持原有已验证组合不变
    # 先装 torch（决定 CUDA/CPU），再装仓库其余依赖。
    # 钉 <2.6：torch>=2.6 起 torch.load 默认 weights_only=True，会拒绝反序列化
    # so-vits checkpoint 里的非张量对象（argparse.Namespace / numpy 标量），导致
    # 加载模型时报 "Weights only load failed"。2.5.1 是支持 py3.9 且仍默认
    # weights_only=False 的稳定版，避免新装用户拉到不兼容的最新版。
    torch_specs = ["torch==2.5.1", "torchaudio==2.5.1"]
    torch_index = TORCH_CUDA_INDEX if use_gpu else TORCH_CPU_INDEX
    pip(*torch_specs, index=torch_index)
    # 优先 requirements_win.txt（仓库为 Windows 提供的更易装版本）
    if req_file.exists():
        filtered = _filter_requirements(req_file)
        pip("-r", str(filtered))
    # so-vits-svc 的 vdecoder 代码里 `import matplotlib`，但官方 requirements 漏列了它，
    # 不补会在推理加载模型时报 No module named 'matplotlib'。钉 3.7.5 以兼容 numpy 1.22 / py3.9，
    # 避免最新 matplotlib(3.9+) 强行把 numpy 升到 >=1.23 而破坏 so-vits-svc 依赖。
        # 仍使用 --no-deps 防止修复旧环境时升级 NumPy，但显式补齐 Matplotlib
        # 的其余导入依赖（尤其 pyparsing；缺失时扩散模型加载会直接失败）。
        pip("--no-deps", *SVC_MATPLOTLIB_RUNTIME_DEPS)
        pip("--no-deps", "matplotlib==3.7.5")
        pip(*SVC_FCPE_RUNTIME_DEPS)
    else:
        print(c("r", "    未找到 requirements，跳过依赖安装（请检查仓库）"))
    if use_gpu:
        _reaffirm_torch_wheels(
            uv,
            py,
            torch_specs,
            torch_index,
            "cu121",
            component="svc",
            gpu_stack=gpu_stack,
            python_version=target_py,
        )
    _verify_svc_fcpe_runtime(py)
    _verify_svc_matplotlib_runtime(py)
    print(c("g", "推理环境就绪"))


def _filter_requirements(
    src: Path,
    extra_deny: set[str] | None = None,
    overrides: dict[str, str] | None = None,
    *,
    output: Path | None = None,
) -> Path:
    """剔除推理用不到/装不上的包（见 REQ_DENYLIST），生成精简 requirements。

    extra_deny：额外剔除的包名（小写、连字符）；用于 Blackwell 下自行管理的 torch/fairseq 等。
    overrides：包名 -> 整行 requirement 覆盖（如 numpy 升到 3.10 兼容版本）；命中即替换原行，
               未在原文件出现的覆盖项会在末尾追加。
    """
    out = output if output is not None else src.parent / "requirements_xb.txt"
    deny = set(REQ_DENYLIST)
    if extra_deny:
        deny |= {d.replace("_", "-").lower() for d in extra_deny}
    ov = {k.replace("_", "-").lower(): v for k, v in (overrides or {}).items()}
    seen_ov: set[str] = set()
    kept: list[str] = []
    for raw in src.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            kept.append(raw)
            continue
        name = re.split(r"[<>=!~;\[\s]", line, maxsplit=1)[0].strip().lower()
        name = name.replace("_", "-")
        if name in deny:
            print(c("y", f"    跳过不需要的包：{line}"))
            continue
        if name in ov:
            print(c("y", f"    覆盖版本：{line} -> {ov[name]}"))
            kept.append(ov[name])
            seen_ov.add(name)
            continue
        kept.append(raw)
    for name, spec in ov.items():
        if name not in seen_ov:
            print(c("y", f"    追加依赖：{spec}"))
            kept.append(spec)
    out.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return out


# Python 3.10 下 so-vits / RVC 需要的、对新 torch 友好的依赖覆盖。
# numpy 1.23.5 仍有 cp310 轮子且兼容 so-vits 代码（未用 1.24 移除的 np.float 等别名）；
# pyworld 0.3.5 提供 cp310 轮子，避免 0.3.0 在 3.10 拉取 numpy 1.19.5 并现场编译失败；
# scipy 1.10.1 提供 cp310 轮子且兼容 numpy 1.23.5（so-vits 原钉的旧 scipy 在 3.10
# 无轮子会现场编译失败 / 与 numpy 1.23 不匹配）。
PYTHON310_REQ_OVERRIDES = {
    "numpy": "numpy==1.23.5",
    "pyworld": "pyworld==0.3.5",
    "scipy": "scipy==1.10.1",
}
# Blackwell 下由我们自行装的包：不让 requirements 里的旧钉死把它们覆盖回去。
BLACKWELL_EXTRA_DENY = {"torch", "torchaudio", "torchvision", "fairseq"}
DIRECTML_EXTRA_DENY = {"torch", "torchaudio", "torchvision"}


def _install_directml_runtime(pip) -> None:  # noqa: ANN001
    pip(
        f"torch-directml=={TORCH_DIRECTML_VER}",
        f"torchaudio=={TORCHAUDIO_DIRECTML_VER}",
    )


def _install_selected_torch_runtime(
    pip,  # noqa: ANN001
    *,
    use_directml: bool,
    torch_specs: list[str],
    torch_index: str,
) -> None:
    if use_directml:
        _install_directml_runtime(pip)
        return
    if not torch_specs:
        raise RuntimeError("Torch package list is empty for the selected runtime")
    pip(*torch_specs, index=torch_index)


def _reaffirm_directml_runtime(
    uv: str,
    py: str,
    *,
    component: str,
    python_version: str,
) -> None:
    uv_pip_install(
        uv,
        py,
        "--reinstall-package",
        "torch-directml",
        f"torch-directml=={TORCH_DIRECTML_VER}",
        f"torchaudio=={TORCHAUDIO_DIRECTML_VER}",
        component=component,
        gpu_stack="directml",
        python_version=python_version,
    )


def _verify_directml_torch(py: str, component: str) -> None:
    check = (
        "import torch,torch_directml; "
        "assert torch_directml.is_available(), 'DirectML unavailable'; "
        "d=torch_directml.device(); "
        "x=torch.ones(1,device=d); "
        "print(torch.__version__,torch_directml.device_name(torch_directml.default_device()),x.cpu().item())"
    )
    try:
        run([py, "-c", check])
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"{component} AMD 环境校验失败：DirectML 导入、设备初始化或张量执行失败；"
            "请查看上方原始错误并检查 Python 3.10、Torch/DirectML 版本与 AMD 驱动"
        ) from exc


def _verify_uvr_directml(py: str) -> None:
    check = (
        "import tempfile,onnxruntime as ort; "
        "from audio_separator.separator import Separator; "
        "assert 'DmlExecutionProvider' in ort.get_available_providers(), "
        "'DmlExecutionProvider unavailable'; "
        "td=tempfile.TemporaryDirectory(prefix='xb-uvr-dml-'); "
        "s=Separator(model_file_dir=td.name,use_directml=True); "
        "assert str(s.torch_device).startswith('privateuseone'), "
        "f'Unexpected UVR device: {s.torch_device}'; "
        "assert 'DmlExecutionProvider' in (s.onnx_execution_provider or []), "
        "f'Unexpected UVR provider: {s.onnx_execution_provider}'; "
        "print('UVR DirectML',s.torch_device,s.onnx_execution_provider); "
        "td.cleanup()"
    )
    try:
        run([py, "-c", check])
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "UVR AMD 环境校验失败：audio-separator 无法初始化 DirectML 设备或 DmlExecutionProvider"
        ) from exc


def _verify_svc_fcpe_runtime(py: str) -> None:
    """Fail environment setup when FCPE's Python runtime is incomplete."""
    check = (
        "import einops,local_attention; "
        "from modules.F0Predictor.fcpe.pcmer import PCmer; "
        "print('FCPE runtime',einops.__version__,local_attention.__name__,PCmer.__name__)"
    )
    try:
        run([py, "-c", check], cwd=SOVITS_DIR)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "So-VITS-SVC FCPE 依赖校验失败：einops/local-attention 或 FCPE 模块无法导入"
        ) from exc


def _verify_svc_matplotlib_runtime(py: str) -> None:
    """Verify the vocoder's matplotlib import chain before marking SVC ready."""
    check = (
        "import matplotlib,contourpy,cycler,fontTools,kiwisolver,packaging,PIL,pyparsing; "
        "print('Matplotlib runtime',matplotlib.__version__,pyparsing.__version__)"
    )
    try:
        run([py, "-c", check])
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "So-VITS-SVC Matplotlib 依赖校验失败："
            "contourpy/cycler/fonttools/kiwisolver/packaging/Pillow/pyparsing 未完整安装"
        ) from exc


def _verify_ddsp_hubert(py: str) -> None:
    """Verify the exact Transformers entry point used by DDSP inference."""
    check = (
        "import transformers; "
        "from transformers import HubertModel,HubertConfig,Wav2Vec2FeatureExtractor; "
        "print('DDSP Transformers',transformers.__version__,"
        "HubertModel.__name__,HubertConfig.__name__,Wav2Vec2FeatureExtractor.__name__)"
    )
    try:
        run([py, "-c", check])
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "DDSP-SVC 依赖校验失败：Transformers/HuBERT 无法与当前 Torch 一起导入；"
            "请确认已安装 transformers==4.46.3"
        ) from exc


def _torch_runtime_matches(py: str, torch_specs: list[str], label: str) -> bool:
    """Check imported binary versions, not just dist-info, without reinstalling."""
    expected = {}
    for spec in torch_specs:
        name, separator, version = spec.partition("==")
        if not separator or name not in {"torch", "torchaudio", "torchvision"}:
            return False
        expected[name] = version if "+" in version else f"{version}+{label}"
    if not expected:
        return False
    code = (
        "import importlib,json,sys; expected=json.loads(sys.argv[1]); "
        "actual={name:importlib.import_module(name).__version__ for name in expected}; "
        "assert actual == expected, (actual,expected)"
    )
    try:
        proc = subprocess.run([py, "-c", code, json.dumps(expected)],
                              capture_output=True, timeout=45,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _reaffirm_torch_wheels(
    uv: str,
    py: str,
    torch_specs: list[str],
    index: str,
    label: str,
    *,
    component: str,
    gpu_stack: str,
    python_version: str,
) -> None:
    """保留可导入且匹配的 PyTorch；仅修复损坏或错误构建。

    audio-separator / fairseq / rvc-python 等依赖在解析时可能把 CUDA torch 换成
    PyPI 默认的「同版本号 CPU 版」，导致 torch.cuda.is_available()=False，
    推理时报 "Attempting to deserialize object on a CUDA device but
    torch.cuda.is_available() is False"。普通 install 因版本号相同会判定已满足而不覆盖，
    这里用 --reinstall-package 只强制重装 torch/torchaudio（不动其它包）。
    """
    if _torch_runtime_matches(py, torch_specs, label):
        print(c("g", f"    {label} Torch 版本匹配且可导入，跳过重装"))
        return
    # Include the local CUDA version: public-version equality also accepts CPU
    # wheels and is not sufficient for deterministic provider selection.
    exact_specs = [spec if "+" in spec else f"{spec}+{label}" for spec in torch_specs]
    try:
        uv_pip_install(
            uv,
            py,
            "--reinstall-package", "torch", "--reinstall-package", "torchaudio",
            *exact_specs,
            index=index,
            component=component,
            gpu_stack=gpu_stack,
            python_version=python_version,
        )
        print(c("g", f"    已校正 {label} torch（防止被依赖替换成 CPU 版）"))
    except subprocess.CalledProcessError:
        print(c("y", f"    {label} torch 校正失败，请检查网络/驱动后重跑该步"))
        raise


def _reaffirm_blackwell_torch(
    uv: str,
    py: str,
    *,
    component: str,
    python_version: str,
) -> None:
    _reaffirm_torch_wheels(
        uv,
        py,
        [f"torch=={TORCH_BLACKWELL_VER}", f"torchaudio=={TORCHAUDIO_BLACKWELL_VER}"],
        TORCH_BLACKWELL_INDEX,
        "cu128",
        component=component,
        gpu_stack="cu128",
        python_version=python_version,
    )


def _verify_cuda_torch(py: str, component: str) -> None:
    """Fail installation instead of leaving a requested GPU runtime on CPU Torch."""
    check = (
        "import torch; "
        "assert torch.cuda.is_available(), "
        "f'CUDA unavailable in torch {torch.__version__}'; "
        "print(torch.__version__, torch.cuda.get_device_name(0))"
    )
    try:
        run([py, "-c", check])
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"{component} GPU 环境校验失败：CUDA Torch 不可用，请检查驱动或重新安装"
        ) from exc


def _install_fairseq_blackwell(pip) -> None:  # noqa: ANN001
    """在 Blackwell（py3.10）环境安装 fairseq。

    fairseq 0.12.2 在 py3.10 无官方 win 轮子、且与新 setuptools/torch 冲突。这里优先尝试
    PyPI（命中预编译/可构建即可），失败则回退 GitHub 源码安装（需 VS C++ Build Tools）。
    这一步是 50 系适配最易出问题处，失败时请把日志贴出以便定位。
    """
    # omegaconf 2.0.6 是 fairseq 0.12.2 的运行期依赖，提前钉好避免被拉到不兼容的新版本
    try:
        pip("omegaconf==2.0.6")
    except subprocess.CalledProcessError:
        print(c("y", "    omegaconf 2.0.6 安装失败，继续尝试 fairseq（可能用新版 omegaconf）"))
    try:
        pip("fairseq==0.12.2")
        return
    except subprocess.CalledProcessError:
        print(c("y", "    PyPI fairseq==0.12.2 安装失败，回退 GitHub 源码安装 …"))
    pip("git+https://github.com/facebookresearch/fairseq.git")


def _patch_fairseq_weights_only(py: Path) -> None:
    """修复 fairseq 的 checkpoint_utils.py（仅在 Blackwell/新 torch 下调用）。

    torch>=2.6 默认 weights_only=True 会让 fairseq 加载 hubert/字典等 checkpoint 失败。
    该兼容现已统一由 worker 在「导入前 monkey-patch torch.load 设 weights_only=False」处理
    （见 rvc_worker / svc_worker），不再改写源码里的 torch.load。

    本函数只负责「修复」早期版本的错误补丁：当时用的正则无法处理嵌套括号，会把
    weights_only=False 误插进 torch.device(...)，得到
        torch.load(f, map_location=torch.device("cpu", weights_only=False))
    在 torch.device() 阶段即抛 TypeError，连带 hubert 加载失败、RVC 报
    'tuple' object has no attribute 'dtype'。这里把它还原回 torch.device("cpu")。
    幂等：无损坏时不改动。
    """
    try:
        out = subprocess.run(
            [str(py), "-c", "import os,fairseq;print(os.path.dirname(fairseq.__file__))"],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(c("y", f"    定位 fairseq 失败，跳过修复：{exc}"))
        return
    base = out.stdout.strip()
    if not base:
        print(c("y", "    未找到 fairseq 安装路径，跳过修复"))
        return
    cu = Path(base) / "checkpoint_utils.py"
    if not cu.exists():
        print(c("y", f"    未找到 {cu}，跳过修复"))
        return
    text = cu.read_text(encoding="utf-8", errors="replace")
    # 还原早期错误补丁：把误插进 torch.device(...) 的 weights_only 去掉（兼容单双引号/空格）
    fixed = re.sub(
        r"""torch\.device\(\s*(['"])cpu\1\s*,\s*weights_only\s*=\s*False\s*\)""",
        lambda m: f"torch.device({m.group(1)}cpu{m.group(1)})",
        text,
    )
    if fixed != text:
        cu.write_text(fixed, encoding="utf-8")
        print(c("g", "    已修复 fairseq checkpoint_utils 的 torch.device 误插补丁"))
    else:
        print(c("g", "    fairseq checkpoint_utils 无需修复（weights_only 由 worker 运行时处理）"))


def step_rvc(uv: str, gpu_stack: str) -> None:
    hr("7/12 RVC 推理环境 .venv-rvc（rvc-python）")
    use_blackwell = gpu_stack == "cu128"
    use_gpu = gpu_stack in {"cu121", "cu128"}
    use_directml = gpu_stack == "directml"
    # RVC 推理在独立环境运行（rvc-python），与 so-vits 栈隔离。
    # rvc-python 默认会在首次推理时下载 hubert / rmvpe；这里安装后立即预置，
    # 避免新用户运行 RVC 时因为 HuggingFace 连接失败而报 HTTPSConnectionPool。
    target_py = _rvc_python_for_stack(gpu_stack)
    ensure_venv(uv, RVC_VENV, target_py)
    py = str(venv_python(RVC_VENV))
    pip = make_pip(
        uv,
        py,
        component="rvc",
        gpu_stack=gpu_stack,
        python_version=target_py,
    )

    # uv venv 默认不含 setuptools；fairseq/rvc 运行时可能用到 pkg_resources，先补齐
    pip("setuptools<81", "wheel")
    if use_directml:
        _install_directml_runtime(pip)
        pip("rvc-python")
        _reaffirm_directml_runtime(
            uv,
            py,
            component="rvc",
            python_version=target_py,
        )
        seed_rvc_base_models(venv_python(RVC_VENV))
        _verify_directml_torch(py, "RVC")
        print(c("g", "RVC 推理环境就绪（AMD DirectML；RMVPE 使用 CPU 稳定路径）"))
        return
    if use_blackwell:
        # 50 系：cu128 + torch2.7.1。rvc-python 会带回 fairseq，装完再就地打 weights_only 补丁，
        # 否则新 torch 加载 hubert/字典会报 "Weights only load failed"。
        pip(
            f"torch=={TORCH_BLACKWELL_VER}",
            f"torchaudio=={TORCHAUDIO_BLACKWELL_VER}",
            index=TORCH_BLACKWELL_INDEX,
        )
        pip("rvc-python")
        seed_rvc_base_models(venv_python(RVC_VENV))
        # 兜底：rvc-python/fairseq 可能把 cu128 torch 换成同号 CPU 版 → 强制校正回 cu128
        _reaffirm_blackwell_torch(
            uv,
            py,
            component="rvc",
            python_version=target_py,
        )
        _patch_fairseq_weights_only(venv_python(RVC_VENV))
        print(c("g", "RVC 推理环境就绪（Blackwell/cu128）"))
        return

    # 老栈：RVC 固定 torch 2.1.1；40 系及以下 NVIDIA 用 cu121，CPU/非 NVIDIA 用 CPU torch。
    torch_specs = ["torch==2.1.1", "torchaudio==2.1.1"]
    torch_index = TORCH_RVC_CUDA_INDEX if use_gpu else TORCH_CPU_INDEX
    pip(*torch_specs, index=torch_index)
    # rvc-python（含 fairseq / faiss 等推理依赖）
    pip("rvc-python")
    if use_gpu:
        _reaffirm_torch_wheels(
            uv,
            py,
            torch_specs,
            torch_index,
            "cu121",
            component="rvc",
            gpu_stack=gpu_stack,
            python_version=target_py,
        )
    seed_rvc_base_models(venv_python(RVC_VENV))
    print(c("g", "RVC 推理环境就绪"))


SEEDVC_REQ_DENY = {
    "torch",
    "torchvision",
    "torchaudio",
    "gradio",
    "sounddevice",
    "freesimplegui",
    # resemblyzer is only imported by Seed-VC's eval.py. Its unmaintained
    # webrtcvad dependency has no Windows cp310 wheel and otherwise forces a
    # local MSVC build, which is unnecessary for XB-SVCB file inference.
    "resemblyzer",
    "webrtcvad",
}

DDSP_REQ_DENY = {
    "freesimplegui",
    "sounddevice",
    # Upstream lists both `gin` and `gin_config`. The `gin` project on PyPI is
    # unrelated and only publishes legacy, non-PEP 625 source archives; the
    # required `import gin` module is provided by the retained gin_config line.
    "gin",
}

# DDSP 6.3 leaves Transformers unpinned. Transformers 5.x imports the public
# torch.distributed.tensor.DTensor API during every HuBERT import, but the
# torch 2.4.1 runtime required by torch-directml does not export that API.
# SeedVC already validates 4.46.3 with the same HuBERT/Whisper generation, so
# keep DDSP on that compatible 4.x release across all accelerator stacks.
DDSP_REQ_OVERRIDES = {
    "transformers": "transformers==4.46.3",
}

# The bundled DeepFilterNet3 checkpoint is intentionally much smaller than
# the SVC base models checked by _is_large_model_file().
DEEPFILTER_CHECKPOINT_MIN_BYTES = 8 * 1024 * 1024


def step_seedvc(uv: str, gpu_stack: str) -> None:
    hr("8/12 SeedVC 推理环境 engines/seed-vc + .venv-seedvc")
    fetch_seedvc()

    use_blackwell = gpu_stack == "cu128"
    use_gpu = gpu_stack in {"cu121", "cu128"}
    use_directml = gpu_stack == "directml"

    target_py = PYTHON_FOR_ENGINES
    venv = runtime_venv("seedvc", SEEDVC_VENV)
    ensure_venv(uv, venv, target_py)
    py = str(venv_python(venv))
    pip = make_pip(
        uv,
        py,
        component="seedvc",
        gpu_stack=gpu_stack,
        python_version=target_py,
    )

    pip("setuptools<81", "wheel")
    if use_directml:
        torch_specs: list[str] = []
        torch_index = ""
    elif use_blackwell:
        torch_specs = [
            f"torch=={TORCH_BLACKWELL_VER}",
            f"torchaudio=={TORCHAUDIO_BLACKWELL_VER}",
        ]
        torch_index = TORCH_BLACKWELL_INDEX
    else:
        torch_specs = ["torch==2.5.1", "torchaudio==2.5.1"]
        torch_index = TORCH_CUDA_INDEX if use_gpu else TORCH_CPU_INDEX
    _install_selected_torch_runtime(
        pip,
        use_directml=use_directml,
        torch_specs=torch_specs,
        torch_index=torch_index,
    )

    req = SEEDVC_DIR / "requirements.txt"
    if req.exists():
        filtered = _filter_requirements(req, extra_deny=SEEDVC_REQ_DENY,
                                        overrides=_core_requirement_overrides("seedvc"))
        pip("-r", str(filtered))
    else:
        print(c("r", "    未找到 SeedVC requirements.txt，跳过依赖安装（请检查仓库）"))

    seed_seedvc_base_models(venv_python(venv))

    if use_directml:
        _reaffirm_directml_runtime(
            uv,
            py,
            component="seedvc",
            python_version=target_py,
        )
        _verify_directml_torch(py, "SeedVC")
        print(c("g", "SeedVC 推理环境就绪（AMD DirectML；RMVPE 使用 CPU 稳定路径）"))
    elif use_blackwell:
        _reaffirm_blackwell_torch(
            uv,
            py,
            component="seedvc",
            python_version=target_py,
        )
        print(c("g", "SeedVC 推理环境就绪（Blackwell/cu128）"))
    elif use_gpu:
        _reaffirm_torch_wheels(
            uv,
            py,
            torch_specs,
            torch_index,
            "cu121",
            component="seedvc",
            gpu_stack=gpu_stack,
            python_version=target_py,
        )
        print(c("g", "SeedVC 推理环境就绪（cu121）"))
    else:
        print(c("g", "SeedVC 推理环境就绪（CPU）"))


def step_ddsp(uv: str, gpu_stack: str) -> None:
    hr("9/12 DDSP-SVC 推理环境 engines/ddsp-svc + .venv-ddsp")
    fetch_ddsp()

    use_blackwell = gpu_stack == "cu128"
    use_gpu = gpu_stack in {"cu121", "cu128"}
    # The DDSP/Rectified-Flow graph can finish on DirectML while silently
    # producing electrical noise or near-silence. AMD installations therefore
    # use a CPU Torch runtime for DDSP only; UVR and other model environments
    # keep their DirectML acceleration.
    amd_cpu_stable = gpu_stack == "directml"

    target_py = PYTHON_FOR_ENGINES
    venv = runtime_venv("ddsp", DDSP_VENV)
    ensure_venv(uv, venv, target_py)
    py = str(venv_python(venv))
    pip = make_pip(
        uv,
        py,
        component="ddsp",
        gpu_stack=gpu_stack,
        python_version=target_py,
    )

    pip("setuptools<81", "wheel")
    if use_blackwell:
        torch_specs = [
            f"torch=={TORCH_BLACKWELL_VER}",
            f"torchaudio=={TORCHAUDIO_BLACKWELL_VER}",
        ]
        torch_index = TORCH_BLACKWELL_INDEX
    else:
        torch_specs = ["torch==2.5.1", "torchaudio==2.5.1"]
        torch_index = TORCH_CUDA_INDEX if use_gpu else TORCH_CPU_INDEX
    _install_selected_torch_runtime(
        pip,
        use_directml=False,
        torch_specs=torch_specs,
        torch_index=torch_index,
    )
    if amd_cpu_stable:
        try:
            run(uv_cmd(uv, "pip", "uninstall", "--python", py, "torch-directml"))
        except subprocess.CalledProcessError:
            pass

    requirements = DDSP_DIR / "requirements.txt"
    if requirements.exists():
        filtered = _filter_requirements(
            requirements,
            extra_deny=DDSP_REQ_DENY | (DIRECTML_EXTRA_DENY if amd_cpu_stable else set()),
            overrides=_core_requirement_overrides("ddsp"),
        )
        pip("-r", str(filtered))
    else:
        raise RuntimeError("未找到 DDSP-SVC requirements.txt")
    seed_ddsp_base_models()

    if amd_cpu_stable:
        _verify_ddsp_hubert(py)
        print(c("g", "DDSP-SVC 推理环境就绪（AMD 机器使用 CPU 稳定路径，避免 DirectML 电流杂音）"))
    elif use_blackwell:
        _reaffirm_blackwell_torch(
            uv,
            py,
            component="ddsp",
            python_version=target_py,
        )
        _verify_cuda_torch(py, "DDSP-SVC")
        _verify_ddsp_hubert(py)
        print(c("g", "DDSP-SVC 推理环境就绪（Blackwell/cu128）"))
    elif use_gpu:
        _reaffirm_torch_wheels(
            uv,
            py,
            torch_specs,
            torch_index,
            "cu121",
            component="ddsp",
            gpu_stack=gpu_stack,
            python_version=target_py,
        )
        _verify_cuda_torch(py, "DDSP-SVC")
        _verify_ddsp_hubert(py)
        print(c("g", "DDSP-SVC 推理环境就绪（cu121）"))
    else:
        _verify_ddsp_hubert(py)
        print(c("g", "DDSP-SVC 推理环境就绪（CPU）"))


def _prepare_vocal_deepfilter_model(py: str) -> Path:
    """Deploy and validate the bundled model without consulting the user cache."""
    model_dir = VOCAL_MODELS_DIR / "DeepFilterNet3"
    bundled_rel = (
        "vocal-enhancement/DeepFilterNet/DeepFilterNet/Cache/DeepFilterNet3"
    )
    if not copy_bundled(bundled_rel, model_dir):
        raise RuntimeError("安装包缺少 DeepFilterNet3 自带模型")

    config_file = model_dir / "config.ini"
    checkpoint = model_dir / "checkpoints" / "model_120.ckpt.best"
    try:
        checkpoint_ready = (
            checkpoint.is_file()
            and checkpoint.stat().st_size >= DEEPFILTER_CHECKPOINT_MIN_BYTES
        )
    except OSError:
        checkpoint_ready = False
    if not config_file.is_file() or not checkpoint_ready:
        raise RuntimeError(
            "DeepFilterNet3 自带模型不完整：需要 config.ini 与完整的 model_120.ckpt.best"
        )

    # appdirs uses the Windows known-folder API and ignores a LOCALAPPDATA
    # override. Passing the model directory explicitly keeps install and runtime
    # fully offline and independent of the current user's cache.
    check = "import sys; from df.enhance import init_df; init_df(sys.argv[1])"
    run([py, "-c", check, str(model_dir)])
    return model_dir


def step_vocal(uv: str, gpu_stack: str) -> None:
    hr("10/12 AI 歌声增强环境 .venv-vocal")
    venv = runtime_venv("vocal", VOCAL_VENV)
    ensure_venv(uv, venv, PYTHON_FOR_ENGINES)
    py = str(venv_python(venv))
    pip = make_pip(
        uv,
        py,
        component="vocal",
        gpu_stack=gpu_stack,
        python_version=PYTHON_FOR_ENGINES,
    )

    # Vocal's deepfilternet==0.5.6 requires packaging<24, while wheel>=0.47
    # requires packaging>=24. Vocal installs only prebuilt wheels, so it does
    # not need wheel at runtime; keeping it out avoids an impossible resolver.
    pip("setuptools<81")
    if gpu_stack == "cu128":
        torch_specs = [
            f"torch=={TORCH_BLACKWELL_VER}",
            f"torchaudio=={TORCHAUDIO_BLACKWELL_VER}",
        ]
        torch_index = TORCH_BLACKWELL_INDEX
    elif gpu_stack == "cu121":
        torch_specs = ["torch==2.5.1", "torchaudio==2.5.1"]
        torch_index = TORCH_CUDA_INDEX
    else:
        # AMD 与无独显机器使用稳定的 CPU Torch。
        torch_specs = ["torch==2.5.1", "torchaudio==2.5.1"]
        torch_index = TORCH_CPU_INDEX
    pip(*torch_specs, index=torch_index)
    pip(
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
    if gpu_stack in {"cu121", "cu128"}:
        _reaffirm_torch_wheels(
            uv,
            py,
            torch_specs,
            torch_index,
            gpu_stack,
            component="vocal",
            gpu_stack=gpu_stack,
            python_version=PYTHON_FOR_ENGINES,
        )

    _prepare_vocal_deepfilter_model(py)
    (VOCAL_MODELS_DIR / "runtime.ready").write_text(
        "deepfilternet=0.5.6\npedalboard=0.9.24\npraat-parselmouth=0.4.6\n",
        encoding="ascii",
    )
    print(c("g", "AI 歌声增强环境与模型就绪"))


def step_hub(uv: str, gpu_stack: str) -> None:
    hr("11/12 模型上传组件 .venv-hub（modelscope）")
    # 仅「分享到模型站（上传）」需要 modelscope SDK；搜索 / 下载走纯 HTTP，不依赖本环境。
    # 用 3.10（与 UVR 一致），装 modelscope hub 能力即可（上传用 upload_folder，无需本地 git）。
    ensure_venv(uv, HUB_VENV, PYTHON_FOR_ENGINES)
    py = str(venv_python(HUB_VENV))
    pip = make_pip(
        uv,
        py,
        component="hub",
        gpu_stack=gpu_stack,
        python_version=PYTHON_FOR_ENGINES,
    )

    # uv venv 默认不含 setuptools，modelscope 运行时可能用到 pkg_resources，先补齐
    pip("setuptools<81", "wheel")
    # modelscope SDK（含 hub 上传能力）+ 依赖
    pip("modelscope", "requests", "tqdm")
    print(c("g", "模型上传组件就绪"))


def step_models(uv: str) -> None:
    hr("12/12 底模 + UVR 模型（自带优先，缺失才联网下载）")
    PRETRAIN_DIR.mkdir(parents=True, exist_ok=True)
    if ASSETS_MODELS_DIR.exists():
        print(c("g", f"  检测到自带模型目录：{ASSETS_MODELS_DIR}"))
    else:
        print(c("y", "  未发现自带模型目录，全部走联网下载"))

    # 1) ContentVec —— so-vits-svc 4.1 默认语音编码器（vec768l12）所需的真正模型
    print(c("b", "  · ContentVec (checkpoint_best_legacy_500.pt)"))
    cv_dest = PRETRAIN_DIR / "checkpoint_best_legacy_500.pt"
    if not copy_bundled("pretrain/checkpoint_best_legacy_500.pt", cv_dest):
        download(hf_urls(HF_PATH_CONTENTVEC), cv_dest)

    # 2) NSF-HiFiGAN（pretrain/nsf_hifigan 目录）
    print(c("b", "  · NSF-HiFiGAN"))
    nsf_dest = PRETRAIN_DIR / "nsf_hifigan"
    if not (nsf_dest / "model").exists():
        if not copy_bundled("pretrain/nsf_hifigan", nsf_dest):
            with tempfile.TemporaryDirectory() as td:
                zp = Path(td) / "nsf_hifigan.zip"
                download(gh_urls(NSF_HIFIGAN_GH), zp)
                extract_zip(zp, PRETRAIN_DIR)  # 压缩包内含 nsf_hifigan/ 目录
            if not nsf_dest.exists():
                print(c("r", "    解压后未见 nsf_hifigan 目录，请手动检查"))
    else:
        print(c("g", "    已存在，跳过"))

    # 3) RMVPE（F0 预测器）
    print(c("b", "  · RMVPE"))
    rmvpe_dest = PRETRAIN_DIR / "rmvpe.pt"
    if not rmvpe_dest.exists():
        if not copy_bundled("pretrain/rmvpe.pt", rmvpe_dest):
            with tempfile.TemporaryDirectory() as td:
                zp = Path(td) / "rmvpe.zip"
                download(gh_urls(RMVPE_GH), zp)
                extract_zip(zp, Path(td))
                found = next(Path(td).rglob("model.pt"), None) or next(
                    Path(td).rglob("rmvpe.pt"), None
                )
                if found:
                    shutil.copyfile(found, rmvpe_dest)
                else:
                    print(c("r", "    解压后未找到 model.pt，请手动放置 rmvpe.pt"))
    else:
        print(c("g", "    已存在，跳过"))

    # 3b) FCPE：高音域素材自动切换，发布安装包必须离线携带。
    print(c("b", "  · FCPE（高音域自适应）"))
    if not copy_bundled("pretrain/fcpe.pt", PRETRAIN_DIR / "fcpe.pt"):
        raise RuntimeError("安装包缺少高音域 FCPE 模型：assets/models/pretrain/fcpe.pt")

    # 4) UVR 分离模型：自带优先，缺失再用 audio-separator 联网下载
    print(c("b", "  · UVR 分离模型（5_HP-Karaoke / DeEcho-DeReverb）"))
    UVR_MODELS_DIR.mkdir(parents=True, exist_ok=True)

    # 4a) audio-separator 模型数据 JSON（清单 + 参数表）：放进模型目录即可离线，
    #     避免运行时去 raw.githubusercontent.com 拉取而超时报错。
    print(c("b", "  · UVR 模型数据（download_checks / vr / mdx）"))
    for name in UVR_SUPPORT_FILES:
        dest = UVR_MODELS_DIR / name
        if dest.exists() and dest.stat().st_size > 0:
            print(c("g", f"    已存在，跳过：{name}"))
            continue
        if copy_bundled(f"uvr/{name}", dest):
            continue
        try:
            download(gh_urls(UVR_DATA_RAW_PREFIX + UVR_SUPPORT_GH[name]), dest)
        except Exception as exc:  # noqa: BLE001 - 非致命：运行时仍会尝试联网拉取
            print(c("y", f"    {name} 下载失败（{exc}）；首次分离时将尝试联网获取"))

    missing: list[str] = []
    for name in UVR_MODEL_NAMES:
        if not copy_bundled(f"uvr/{name}", UVR_MODELS_DIR / name):
            missing.append(name)

    if missing:
        uvr_py = venv_python(runtime_venv("uvr", UVR_VENV))
        if uvr_py.exists():
            print(c("y", f"    以下模型无自带，联网下载：{', '.join(missing)}"))
            dl = (
                "from audio_separator.separator import Separator;"
                "import sys;"
                "s=Separator(model_file_dir=sys.argv[1]);"
                "[s.download_model_files(m) for m in sys.argv[2:]]"
            )
            try:
                run([str(uvr_py), "-c", dl, str(UVR_MODELS_DIR), *missing])
            except subprocess.CalledProcessError:
                # 旧版本无 download_model_files，则用 load_model 触发下载
                dl2 = (
                    "from audio_separator.separator import Separator;"
                    "import sys;"
                    "s=Separator(model_file_dir=sys.argv[1]);"
                    "[s.load_model(model_filename=m) for m in sys.argv[2:]]"
                )
                run([str(uvr_py), "-c", dl2, str(UVR_MODELS_DIR), *missing])
        else:
            print(c("r", "    共享 UVR 环境不存在且无自带模型，跳过（请先跑 uvr 步骤或放置自带模型）"))
    print(c("g", "模型就绪"))


STEPS = {
    "app": lambda uv, stack: step_app(uv),
    "plugins": lambda uv, stack: step_plugins(uv),
    "web": lambda uv, stack: step_web(),
    "uvr": lambda uv, stack: step_uvr(uv, stack),
    "pymss": lambda uv, stack: step_pymss(uv, stack),
    "svc": lambda uv, stack: step_svc(uv, stack),
    "rvc": lambda uv, stack: step_rvc(uv, stack),
    "seedvc": lambda uv, stack: step_seedvc(uv, stack),
    "ddsp": lambda uv, stack: step_ddsp(uv, stack),
    "vocal": lambda uv, stack: step_vocal(uv, stack),
    "hub": lambda uv, stack: step_hub(uv, stack),
    "models": lambda uv, stack: step_models(uv),
}
ORDER = ["app", "plugins", "web", "uvr", "pymss", "svc", "rvc", "seedvc", "ddsp", "vocal", "hub", "models"]


def installer_progress(percent: int, message: str) -> None:
    """Emit progress markers consumed by the Inno installer."""
    if os.environ.get("XB_FROM_INSTALLER") != "1":
        return
    percent = max(0, min(100, int(percent)))
    print(f"[XB-PROGRESS] {percent} {message}", flush=True)


def main() -> int:
    global CORE_COMPAT_WHEEL
    p = argparse.ArgumentParser(description="XB-SVCB 一键安装器")
    p.add_argument(
        "--root",
        default=None,
        help="安装根目录（引擎/虚拟环境/模型都装到此处）；默认取脚本上级目录",
    )
    p.add_argument("--cpu", action="store_true", help="安装 CPU 版")
    p.add_argument("--gpu", action="store_true", help="请求安装 GPU 版；自动选择 NVIDIA CUDA 或 AMD DirectML")
    p.add_argument("--directml", action="store_true", help="强制安装 AMD/Windows DirectML 推理环境")
    p.add_argument(
        "--cu128",
        action="store_true",
        help="请求按 50 系（Blackwell, cu128 + torch2.7）安装；会复核实际显卡",
    )
    p.add_argument(
        "--no-cu128",
        dest="no_cu128",
        action="store_true",
        help="请求使用 40 系及以下的 cu121 老栈；50 系会被复核并改回 cu128",
    )
    p.add_argument(
        "--consolidated",
        action="store_true",
        help="实验性共享运行时；先整体解析 UVR/SeedVC/DDSP 依赖，当前版本存在冲突会停止",
    )
    p.add_argument("--core-compat-wheel", type=Path,
                   help="实验性 NumPy 2/protobuf 7 配方使用的本地 AudioTools 0.7.2+xb1 wheel；必须与 --consolidated 一起使用")
    p.add_argument("--core-profile", choices=["core-cu128"],
                   help="使用已固定版本和本地 wheel 哈希的实验配方；与 --core-compat-wheel 互斥")
    p.add_argument("--preflight-only", action="store_true",
                   help="仅解析共享依赖并生成约束，不安装包/模型或更新路由；可用 UV_OFFLINE=1 禁止联网")
    p.add_argument(
        "--only",
        choices=ORDER,
        nargs="+",
        help="只执行指定步骤（可多选）：app plugins web uvr pymss svc rvc seedvc ddsp vocal hub models",
    )
    for s in ORDER:
        p.add_argument(f"--skip-{s}", action="store_true", help=f"跳过 {s} 步骤")
    args = p.parse_args()
    if (args.core_compat_wheel or args.core_profile or args.preflight_only) and not args.consolidated:
        p.error("--core-compat-wheel / --core-profile / --preflight-only 必须与 --consolidated 一起使用")
    if args.core_profile and args.core_compat_wheel:
        p.error("--core-profile 与 --core-compat-wheel 不能同时使用")
    CORE_COMPAT_WHEEL = args.core_compat_wheel.expanduser().resolve() if args.core_compat_wheel else None
    selected = args.only if args.only else [s for s in ORDER if not getattr(args, f"skip_{s}")]

    installer_progress(2, "Resolving runtime root")
    if args.root:
        _derive_paths(Path(args.root).expanduser().resolve())
    try:
        _configure_core_profile(args.core_profile)
    except (OSError, ValueError, KeyError) as exc:
        print(c("r", str(exc)))
        return 1

    hr("XB-SVCB 安装器")
    print(f"安装根目录: {ROOT}")

    if args.cpu and (args.gpu or args.directml):
        print(c("r", "--cpu 不能与 --gpu/--directml 同时使用"))
        return 2
    if args.directml and (args.cu128 or args.no_cu128):
        print(c("r", "--directml 不能与 CUDA 栈参数同时使用"))
        return 2
    if args.cu128 and args.no_cu128:
        print(c("r", "--cu128 与 --no-cu128 不能同时使用"))
        return 2
    detected_stack = "cpu" if args.cpu else "directml" if args.directml else detect_gpu_stack()
    if args.gpu and detected_stack == "cpu":
        print(c("y", "未检测到兼容 NVIDIA/AMD 显卡，已改用 CPU 版 torch。"))
    if args.no_cu128 and detected_stack == "cu128":
        print(c("y", "检测到 NVIDIA 显卡，忽略旧 CUDA 栈请求，统一改用 cu128。"))
    installer_progress(8, "Checking GPU runtime")
    if detected_stack == "cu128":
        mode = c("g", "CUDA · Blackwell/50系 (cu128 + torch" + TORCH_BLACKWELL_VER + ")")
    elif detected_stack == "cu121":
        mode = c("g", "CUDA · 40系及以下 (cu121)")
    elif detected_stack == "directml":
        mode = c("g", "AMD · DirectML (torch " + TORCH_DIRECTML_TORCH_VER + ")")
    else:
        mode = c("y", "CPU")
    print(f"安装模式: {mode}")
    if detected_stack == "directml" and not args.directml:
        print("（检测到 AMD Radeon，自动选择 DirectML；如需 CPU 请加 --cpu）")
    elif detected_stack in {"cu121", "cu128"} and not args.gpu:
        print("（检测到 NVIDIA 显卡，自动选择 CUDA；如需 CPU 请加 --cpu）")
    if detected_stack == "cu128" and not args.cu128:
        print("（检测到 NVIDIA 显卡，自动使用统一 cu128 栈）")
    _configure_runtime_layout(consolidated=args.consolidated, gpu_stack=detected_stack)
    if args.consolidated and not CONSOLIDATED_RUNTIME:
        print(c("r", "DirectML 不支持此共享运行时；未修改环境。"))
        return 2
    elif CONSOLIDATED_RUNTIME:
        if CORE_VENV_REUSED:
            print(c("y", f"待验证的共享运行时候选（现有 UVR）：{CORE_VENV}"))
        else:
            print(c("y", f"待验证的共享运行时候选：{CORE_VENV}"))
    wheelhouse = _wheelhouse_root()
    if wheelhouse:
        print(c("g", f"自带 whl 目录: {wheelhouse}"))
    else:
        print(c("y", "未检测到自带 whl 目录，依赖安装将使用在线 PyPI/torch 源。"))

    try:
        _guard_shared_runtime_repair(set(selected))
    except (OSError, ValueError, RuntimeError) as exc:
        print(c("r", str(exc)))
        return 1
    installer_progress(12, "Preparing uv package manager")
    uv = ensure_uv()
    print(f"uv: {uv}")
    installer_progress(18, "uv package manager is ready")

    try:
        _preflight_consolidated_runtime(uv, set(selected), detected_stack)
    except (OSError, ValueError, RuntimeError, KeyError, zipfile.BadZipFile) as exc:
        print(c("r", str(exc)))
        installer_progress(100, "Shared runtime preflight failed; environment unchanged")
        return 1
    if args.preflight_only:
        if CORE_CONSTRAINTS is None:
            print(c("r", "未选择共享组件，未执行共享依赖预检"))
            return 2
        print(c("g", f"共享依赖预检通过；未安装环境、下载模型或更新路由。约束：{CORE_CONSTRAINTS}"))
        return 0
    selected_count = max(1, len(selected))
    completed_count = 0

    results: list[tuple[str, str]] = []
    for s in ORDER:
        if s not in selected:
            results.append((s, "skip"))
            continue
        installer_progress(18 + (completed_count * 76) // selected_count, f"Running runtime step: {s}")
        try:
            STEPS[s](uv, detected_stack)
            results.append((s, "ok"))
        except Exception as exc:  # noqa: BLE001 - 单步失败不阻断其余步骤
            print(c("r", f"[{s}] 失败: {exc}"))
            results.append((s, "fail"))
            if CONSOLIDATED_RUNTIME and s in CORE_COMPONENTS:
                # One failure can affect every component sharing this venv.
                break
        completed_count += 1
        installer_progress(18 + (completed_count * 76) // selected_count, f"Finished runtime step: {s}")

    hr("安装结果汇总")
    label = {"ok": c("g", "成功"), "fail": c("r", "失败"), "skip": c("y", "跳过")}
    for s, st in results:
        print(f"  {s:<8} {label[st]}")

    if any(st == "fail" for _, st in results):
        if CONSOLIDATED_RUNTIME and CORE_COMPONENTS.intersection(selected):
            print(c("y", "\n共享环境可能已部分修改；不要单独修复组件。请用原 GPU 参数、同一配方一起重试 UVR/SeedVC/DDSP。"))
        else:
            print(c("y", "\n有步骤失败。可单独重试，例如: python install/install.py --only svc"))
        print(c("y", "失败项的手动补救方式见 install/README 或项目根 README。"))
        installer_progress(100, "Runtime environment finished with errors")
        return 1

    if CONSOLIDATED_RUNTIME and CORE_COMPONENTS.intersection(selected):
        try:
            run(uv_cmd(uv, "pip", "check", "--python", str(venv_python(CORE_VENV))))
            if CORE_PROFILE is not None:
                recipe_check = _recipe_module().check_environment(
                    venv_python(CORE_VENV), CORE_PROFILE, CORE_PROFILE_PINS)
                if not recipe_check["ok"]:
                    raise RuntimeError("共享环境偏离固定配方：" + json.dumps(recipe_check, ensure_ascii=False))
            run([str(venv_python(CORE_VENV)), str(Path(__file__).with_name("audit_runtime.py")),
                 "--root", str(ROOT), *(["--require-cuda"] if detected_stack != "cpu" else [])])
            if CORE_COMPAT_WHEEL is not None:
                run([str(venv_python(CORE_VENV)), str(Path(__file__).with_name("probe_core_compat.py")),
                     "--root", str(ROOT), "--output", str(ROOT / ".tmp" / "core-compat-installed-probes.json")])
            write_runtime_manifest(detected_stack, {name for name, status in results if status == "ok"})
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            print(c("r", f"共享运行时最终校验失败，未更新 runtime.json：{exc}"))
            installer_progress(100, "Shared runtime validation failed")
            return 1

    installer_progress(100, "Runtime environment complete")
    hr("全部完成")
    app_exe = ROOT / "XB-SVCB.exe"
    if app_exe.exists():
        # 安装版：应用本体为打包好的 exe
        print("启动应用：双击 " + c("g", str(app_exe)) + " 或使用开始菜单/桌面快捷方式。")
    else:
        # 源码版：用 app/.venv 运行 main.py
        print("启动应用：")
        print(c("g", f'  {venv_python(APP_DIR / ".venv")} {APP_DIR / "main.py"}'))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
