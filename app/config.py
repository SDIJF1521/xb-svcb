"""全局配置：应用元信息与数据目录。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "XB-SVCB"
APP_TITLE = "XB-SVCB"
APP_VERSION = "0.0.30"
APP_BG = "#05060d"


# ---- 子进程窗口隐藏（Windows）----
# GUI（无控制台）程序用 subprocess 调用 ffmpeg / Python 等命令行工具时，Windows 会
# 为子进程新建一个控制台窗口，表现为「一闪而过的黑框」。统一加上 CREATE_NO_WINDOW
# 并隐藏 STARTUPINFO 窗口，彻底消除这些弹窗（其他平台无影响）。
def subprocess_no_window() -> dict:
    """返回隐藏子进程控制台窗口的 subprocess 关键字参数（仅 Windows 生效）。"""
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        "startupinfo": startupinfo,
    }

# ---- 运行基准目录（兼容源码运行与 PyInstaller 打包后的 exe）----
#   BASE_DIR   外部环境/数据的根：打包后为 exe 所在目录（= 安装目录，旁边就是
#              engines/runtimes/models）；源码运行时为项目根。
#   BUNDLE_DIR 随程序一起分发的只读资源根：打包后为 PyInstaller 解包目录
#              （_internal，内含 web/dist 与 worker 脚本）；源码运行时为 app/ 目录。
_FROZEN = bool(getattr(sys, "frozen", False))
if _FROZEN:
    BASE_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    BUNDLE_DIR = Path(__file__).resolve().parent

# 项目根目录（外部引擎/环境的定位基准）
ROOT_DIR = BASE_DIR

# Optional runtime layout emitted by the installer.  Older installations do
# not have this file and continue using the legacy .venv-* discovery below.
RUNTIME_MANIFEST_FILE = Path(
    os.environ.get("XB_RUNTIME_MANIFEST", str(ROOT_DIR / "runtime.json"))
).expanduser()
if not RUNTIME_MANIFEST_FILE.is_absolute():
    RUNTIME_MANIFEST_FILE = ROOT_DIR / RUNTIME_MANIFEST_FILE


def _load_runtime_manifest() -> dict:
    try:
        payload = json.loads(RUNTIME_MANIFEST_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return {}
    return payload


_RUNTIME_MANIFEST = _load_runtime_manifest()


def _manifest_python(component: str) -> Path | None:
    """Resolve a component interpreter from runtime.json, if it is usable."""
    mapping = _RUNTIME_MANIFEST.get("python")
    if not isinstance(mapping, dict):
        return None
    raw = mapping.get(component)
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = RUNTIME_MANIFEST_FILE.parent / candidate
        return candidate if candidate.is_file() else None
    except (OSError, ValueError, RuntimeError):
        return None

# ---- Python 插件运行时 ----
# 安装版优先使用专用环境；源码模式直接使用当前解释器。也可由用户/安装器显式覆盖。
PLUGIN_VENV_DIR = ROOT_DIR / ".venv-plugins"
PLUGIN_WORKER = BUNDLE_DIR / "infrastructure" / "plugin_worker.py"
PLUGIN_SDK_DIR = (
    BUNDLE_DIR / "plugin_sdk_python"
    if _FROZEN
    else ROOT_DIR / "plugin-sdk" / "python"
)


def _detect_plugin_python() -> Path | None:
    explicit = os.environ.get("XB_PLUGIN_PYTHON") or os.environ.get("XB_PYTHON_EXE")
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_file():
            return candidate
    dedicated = (
        PLUGIN_VENV_DIR / "Scripts" / "python.exe"
        if os.name == "nt"
        else PLUGIN_VENV_DIR / "bin" / "python"
    )
    if dedicated.is_file():
        return dedicated
    manifest = _manifest_python("plugins")
    if manifest:
        return manifest
    if not _FROZEN:
        return Path(sys.executable).resolve()
    # 安装器必备的 AI 子环境也都是标准 CPython，可承载零依赖插件 SDK。
    for environment in ("runtimes/core-cu128", ".venv-uvr", ".venv-svc", ".venv-rvc"):
        candidate = (
            ROOT_DIR / environment / "Scripts" / "python.exe"
            if os.name == "nt"
            else ROOT_DIR / environment / "bin" / "python"
        )
        if candidate.is_file():
            return candidate
    system = shutil.which("python")
    return Path(system).resolve() if system and Path(system).is_file() else None


PLUGIN_PYTHON = _detect_plugin_python()


def _activate_bundled_ffmpeg() -> Path | None:
    """Expose the packaged FFmpeg to this process when no system copy exists."""
    if shutil.which("ffmpeg"):
        return None
    candidates = [
        ROOT_DIR / "tools" / "ffmpeg" / "bin",
        ROOT_DIR / "tools" / "ffmpeg",
    ]
    for bin_dir in candidates:
        if (bin_dir / "ffmpeg.exe").exists():
            current_path = os.environ.get("PATH", "")
            os.environ["PATH"] = str(bin_dir) + (os.pathsep + current_path if current_path else "")
            os.environ.setdefault("XB_FFMPEG_DIR", str(bin_dir.parent if bin_dir.name == "bin" else bin_dir))
            os.environ.setdefault("FFMPEG_HOME", os.environ["XB_FFMPEG_DIR"])
            return bin_dir
    return None


BUNDLED_FFMPEG_BIN_DIR = _activate_bundled_ffmpeg()

# 前端构建产物：打包时内置于 exe 资源目录；源码运行取项目根 web/dist。
DIST_INDEX = (
    BUNDLE_DIR / "web" / "dist" / "index.html"
    if _FROZEN
    else ROOT_DIR / "web" / "dist" / "index.html"
)


# ---- so-vits-svc 4.1 推理引擎 ----
# 开箱即用：默认使用安装器在项目内搭建的引擎与独立环境（engines/、.venv-svc）。
# 所有路径均可通过环境变量覆盖；找不到时推理降级为占位音频。


def _first_existing(candidates: list[Path]) -> Path | None:
    for c in candidates:
        if c.exists():
            return c
    return None


def _first_file(candidates: list[Path]) -> Path | None:
    """Return the first regular file, ignoring stale environment paths."""
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _existing_env_path(name: str) -> Path | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.exists() else None


def _existing_env_file(name: str) -> Path | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    path = Path(raw).expanduser()
    try:
        return path if path.is_file() else None
    except OSError:
        return None


def _venv_python(venv_dir: Path) -> Path:
    """返回 venv 内 Python 解释器路径（兼容 Windows / *nix）。"""
    win = venv_dir / "Scripts" / "python.exe"
    nix = venv_dir / "bin" / "python"
    return win if os.name == "nt" else nix


def _external_install_roots() -> list[Path]:
    """Find an adjacent installed runtime when the app is run from a source checkout."""
    roots = [ROOT_DIR]
    explicit = os.environ.get("XB_APP_ROOT")
    if explicit:
        roots.insert(0, Path(explicit).expanduser())
    for marker in (BASE_DIR / "data_home.json", BASE_DIR.parent / "data_home.json"):
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
            data_dir = payload.get("data_dir") if isinstance(payload, dict) else None
            if data_dir:
                roots.append(Path(str(data_dir)).expanduser().parent)
        except (OSError, json.JSONDecodeError, TypeError):
            continue
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.resolve()).lower()
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


RUNTIME_ROOTS = _external_install_roots()


# 项目内引擎与环境的约定位置（由安装器创建）
ENGINES_DIR = ROOT_DIR / "engines"
SOVITS_REPO_DIR = ENGINES_DIR / "so-vits-svc"
SEEDVC_REPO_DIR = ENGINES_DIR / "seed-vc"
DDSP_REPO_DIR = ENGINES_DIR / "ddsp-svc"
SVC_VENV_DIR = ROOT_DIR / ".venv-svc"
# Current consolidated NVIDIA runtime. The manifest remains authoritative;
# this path is the fallback for older launchers or a missing/invalid manifest.
CORE_VENV_DIR = ROOT_DIR / "runtimes" / "core-cu128"
UVR_VENV_DIR = ROOT_DIR / ".venv-uvr"
# PyMSS 使用独立环境，避免与 audio-separator/UVR 的依赖互相覆盖。
PYMSS_VENV_DIR = ROOT_DIR / ".venv-pymss"


def _detect_sovits_repo() -> Path | None:
    env = _existing_env_path("XB_SOVITS_REPO")
    if env:
        return env
    return _first_existing([SOVITS_REPO_DIR])


def _detect_svc_python() -> Path | None:
    env = _existing_env_file("XB_SVC_PYTHON")
    manifest = _manifest_python("svc")
    # 优先项目内安装器创建的 .venv-svc；其次常见 conda 环境名 svc（开发便利）
    return _first_file(
        [
            *([env] if env else []),
            *([manifest] if manifest else []),
            *(_venv_python(root / ".venv-svc") for root in RUNTIME_ROOTS),
            Path.home() / "anaconda3" / "envs" / "svc" / "python.exe",
            Path.home() / "miniconda3" / "envs" / "svc" / "python.exe",
        ]
    )


# 推理仓库根目录（含 inference/infer_tool.py 与 pretrain/）
SOVITS_REPO = _detect_sovits_repo()
# 运行推理用的 Python 解释器（需装有 torch + fairseq 等 so-vits-svc 依赖）
SVC_PYTHON = _detect_svc_python()
# 子进程内执行的 worker 脚本（由外部 venv 的 Python 读取，需为磁盘上的真实文件）
SVC_WORKER = BUNDLE_DIR / "infrastructure" / "svc_worker.py"
# F0 提取 worker（同样在 so-vits-svc 环境中运行）
F0_WORKER = BUNDLE_DIR / "infrastructure" / "f0_worker.py"
# Praat/Parselmouth AI 对齐与自然修音 worker。由美声环境运行，覆盖全部推理框架。
VOCAL_TUNING_WORKER = BUNDLE_DIR / "infrastructure" / "vocal_tuning_worker.py"


def svc_engine_ready() -> bool:
    """推理环境是否齐备：仓库存在、worker 存在、解释器存在。"""
    return bool(
        SOVITS_REPO
        and SOVITS_REPO.exists()
        and (SOVITS_REPO / "inference" / "infer_tool.py").is_file()
        and SVC_WORKER.is_file()
        and SVC_PYTHON
        and SVC_PYTHON.is_file()
    )


# ---- RVC 推理引擎（rvc-python）----
# 在独立的 .venv-rvc 中运行 rvc-python（依赖与 so-vits-svc 环境隔离，避免 torch/numpy 冲突）。
# 缺失时 RvcEngine 自动降级为占位音频，整条链路仍可跑通。
RVC_VENV_DIR = ROOT_DIR / ".venv-rvc"


def _detect_rvc_python() -> Path | None:
    env = _existing_env_file("XB_RVC_PYTHON")
    candidates = [env] if env else []
    manifest = _manifest_python("rvc")
    if manifest:
        candidates.append(manifest)
    candidates.extend(_venv_python(root / ".venv-rvc") for root in RUNTIME_ROOTS)
    return _first_file(candidates)


# 运行 RVC 推理的 Python 解释器（需装有 rvc-python + torch）
RVC_PYTHON = _detect_rvc_python()
# RVC 推理子进程脚本（由 .venv-rvc 的 Python 读取，需为磁盘真实文件）
RVC_WORKER = BUNDLE_DIR / "infrastructure" / "rvc_worker.py"


def rvc_engine_ready() -> bool:
    """RVC 推理环境是否齐备：worker 存在、解释器存在。"""
    return bool(RVC_WORKER.is_file() and RVC_PYTHON and RVC_PYTHON.is_file())


# ---- SeedVC 推理引擎（Seed-VC）----
# 在独立 .venv-seedvc 中运行官方 Seed-VC inference.py。SeedVC 是 zero-shot /
# few-shot 风格，除 checkpoint + config 外，还需要一个目标音色参考音频。
SEEDVC_VENV_DIR = ROOT_DIR / ".venv-seedvc"


def _detect_seedvc_repo() -> Path | None:
    env = _existing_env_path("XB_SEEDVC_REPO")
    if env:
        return env
    return _first_existing([root / "engines" / "seed-vc" for root in RUNTIME_ROOTS])


def _detect_seedvc_python() -> Path | None:
    env = _existing_env_file("XB_SEEDVC_PYTHON")
    candidates = [env] if env else []
    manifest = _manifest_python("seedvc")
    if manifest:
        candidates.append(manifest)
    candidates.extend(_venv_python(root / ".venv-seedvc") for root in RUNTIME_ROOTS)
    candidates.append(_venv_python(ROOT_DIR / "runtimes" / "core-cu128"))
    return _first_file(candidates)


SEEDVC_REPO = _detect_seedvc_repo()
SEEDVC_PYTHON = _detect_seedvc_python()
SEEDVC_WORKER = BUNDLE_DIR / "infrastructure" / "seedvc_worker.py"


def seedvc_engine_ready() -> bool:
    """SeedVC 推理环境是否齐备：repo、worker、解释器都存在。"""
    return bool(
        SEEDVC_REPO
        and SEEDVC_REPO.exists()
        and (SEEDVC_REPO / "inference.py").is_file()
        and SEEDVC_WORKER.is_file()
        and SEEDVC_PYTHON
        and SEEDVC_PYTHON.is_file()
    )


# ---- DDSP-SVC 推理引擎（yxlllc/DDSP-SVC）----
DDSP_VENV_DIR = ROOT_DIR / ".venv-ddsp"


def _detect_ddsp_repo() -> Path | None:
    env = _existing_env_path("XB_DDSP_REPO")
    if env:
        return env
    return _first_existing([DDSP_REPO_DIR])


def _detect_ddsp_python() -> Path | None:
    env = _existing_env_file("XB_DDSP_PYTHON")
    candidates = [env] if env else []
    manifest = _manifest_python("ddsp")
    if manifest:
        candidates.append(manifest)
    candidates.append(_venv_python(DDSP_VENV_DIR))
    candidates.append(_venv_python(ROOT_DIR / "runtimes" / "core-cu128"))
    return _first_file(candidates)


DDSP_REPO = _detect_ddsp_repo()
DDSP_PYTHON = _detect_ddsp_python()
DDSP_WORKER = BUNDLE_DIR / "infrastructure" / "ddsp_worker.py"


def ddsp_engine_ready() -> bool:
    """DDSP-SVC 仓库、worker 与隔离环境是否齐备。"""
    return bool(
        DDSP_REPO
        and DDSP_REPO.exists()
        and (DDSP_REPO / "main_reflow.py").is_file()
        and DDSP_WORKER.is_file()
        and DDSP_PYTHON
        and DDSP_PYTHON.is_file()
    )


# ---- AI 歌声增强（DeepFilterNet + Pedalboard）----
# 与各 SVC 引擎一样使用隔离环境，避免 DeepFilterNet 的 Torch 依赖污染主程序。
VOCAL_ENHANCEMENT_VENV_DIR = ROOT_DIR / ".venv-vocal"


def _detect_vocal_enhancement_python() -> Path | None:
    env = _existing_env_file("XB_VOCAL_ENHANCEMENT_PYTHON")
    candidates = [env] if env else []
    manifest = _manifest_python("vocal")
    if manifest:
        candidates.append(manifest)
    candidates.append(_venv_python(VOCAL_ENHANCEMENT_VENV_DIR))
    return _first_file(candidates)


VOCAL_ENHANCEMENT_PYTHON = _detect_vocal_enhancement_python()
VOCAL_ENHANCEMENT_WORKER = BUNDLE_DIR / "infrastructure" / "vocal_enhancement_worker.py"
FORMANT_PITCH_WORKER = BUNDLE_DIR / "infrastructure" / "formant_pitch_worker.py"
VOCAL_ENHANCEMENT_MODEL_DIR = ROOT_DIR / "models" / "vocal-enhancement"
VOCAL_ENHANCEMENT_MARKER = VOCAL_ENHANCEMENT_MODEL_DIR / "runtime.ready"


def vocal_enhancement_ready() -> bool:
    return bool(
        VOCAL_ENHANCEMENT_PYTHON
        and VOCAL_ENHANCEMENT_PYTHON.is_file()
        and VOCAL_ENHANCEMENT_WORKER.is_file()
        and VOCAL_ENHANCEMENT_MARKER.is_file()
    )


# ---- JUCE VST3 Host（编辑器外部效果器插件）----
# VST3 插件 GUI 必须由原生 host 承载。Python/前端只负责业务状态与调度：
#   Python（业务逻辑、AI、界面） -> C++ JUCE VST3 Host -> VST3 Plugin GUI
JUCE_VST3_HOST_DIR = ENGINES_DIR / "juce-vst3-host"
JUCE_VST3_HOST_EXE = Path(
    os.environ.get(
        "XB_JUCE_VST3_HOST",
        str(JUCE_VST3_HOST_DIR / ("xb-juce-vst3-host.exe" if os.name == "nt" else "xb-juce-vst3-host")),
    )
)
JUCE_VST3_HOST_PROTOCOL = 1


def juce_vst3_host_ready() -> bool:
    """编辑器 VST3 插件 host 是否可用。"""
    return bool(JUCE_VST3_HOST_EXE and JUCE_VST3_HOST_EXE.exists())


# ---- UVR 人声分离引擎（audio-separator + 复用本地 UVR 模型）----
# 在独立 venv 中运行 audio-separator，复用已安装的 Ultimate Vocal Remover 模型权重。

# 人声/伴奏分离模型：5_HP-Karaoke-UVR（人声更干净、伴奏完整保留）
UVR_SEP_MODEL = os.environ.get("XB_UVR_SEP_MODEL", "5_HP-Karaoke-UVR.pth")
# 人声去混响/去回声模型：去掉混响后再送 SVC，可显著缓解"电音/机械音"
UVR_DEREVERB_MODEL = os.environ.get("XB_UVR_DEREVERB_MODEL", "UVR-DeEcho-DeReverb.pth")


def _detect_uvr_python() -> Path | None:
    env = _existing_env_file("XB_UVR_PYTHON")
    candidates = [env] if env else []
    manifest = _manifest_python("uvr")
    if manifest:
        candidates.append(manifest)
    candidates.append(_venv_python(UVR_VENV_DIR))
    candidates.append(_venv_python(ROOT_DIR / "runtimes" / "core-cu128"))
    return _first_file(candidates)


# UVR 模型默认下载/存放目录（安装器创建）
UVR_MODEL_DIR_DEFAULT = ROOT_DIR / "models" / "uvr"


def _detect_uvr_model_dir() -> Path | None:
    env = _existing_env_path("XB_UVR_MODEL_DIR")
    candidates = [env] if env else []
    candidates.extend(
        [
            # 优先项目内安装器下载的 UVR 模型目录
            UVR_MODEL_DIR_DEFAULT,
            # 其次复用本机常见的 Ultimate Vocal Remover 安装目录（开发便利）
            Path(r"C:\Ultimate Vocal Remover\models\VR_Models"),
        ]
    )
    existing = [c for c in candidates if c.exists()]
    for c in existing:
        if (c / UVR_SEP_MODEL).exists():
            return c
    return existing[0] if existing else None


# 运行 audio-separator 的 Python 解释器
UVR_PYTHON = _detect_uvr_python()
# UVR 模型目录（复用本地 Ultimate Vocal Remover 的模型权重；默认 VR_Models）
UVR_MODEL_DIR = _detect_uvr_model_dir()
# 兼容旧引用：默认分离模型
UVR_MODEL = UVR_SEP_MODEL
# 子进程内执行的分离 worker 脚本（由外部 venv 的 Python 读取，需为磁盘上的真实文件）
UVR_WORKER = BUNDLE_DIR / "infrastructure" / "uvr_worker.py"

# ---- PyMSS 人声分离引擎 ----
# PyMSS 的模型目录与 UVR 分开保存；模型名使用 PyMSS 官方 catalog 名称。
PYMSS_MODEL_DIR_DEFAULT = ROOT_DIR / "models" / "pymss"
PYMSS_DEFAULT_MODEL = os.environ.get(
    "XB_PYMSS_MODEL", "bs_roformer_voc_hyperacev2"
)
PYMSS_DEFAULT_HARMONY_MODEL = os.environ.get(
    "XB_PYMSS_DEREVERB_MODEL",
    os.environ.get("XB_PYMSS_HARMONY_MODEL", "UVR-DeEcho-DeReverb.pth"),
)
PYMSS_PURPOSE_VOCAL = "vocal_separation"
PYMSS_PURPOSE_DEREVERB = "dereverb"
# Compatibility name retained for stored projects and older plugin payloads.
PYMSS_PURPOSE_HARMONY = PYMSS_PURPOSE_DEREVERB
PYMSS_PURPOSE_HARMONY_LEGACY = "harmony_removal"
PYMSS_PURPOSE_LABELS = {
    PYMSS_PURPOSE_VOCAL: "人声分离",
    PYMSS_PURPOSE_DEREVERB: "去混响 / 人声净化",
    PYMSS_PURPOSE_HARMONY_LEGACY: "去混响 / 人声净化",
}
PYMSS_ALLOWED_MODEL_CATEGORIES = {
    PYMSS_PURPOSE_VOCAL: {("vocal", "vocal_extraction")},
    PYMSS_PURPOSE_DEREVERB: {
        ("legacy_vr", "vr_deecho"),
        ("legacy_vr", "vr_deecho_dereverb"),
        ("legacy_vr", "vr_dereverb"),
        ("reverb_echo_control", "dereverb"),
    },
}
PYMSS_WORKER = BUNDLE_DIR / "infrastructure" / "pymss_worker.py"


def _detect_pymss_python() -> Path | None:
    env = _existing_env_file("XB_PYMSS_PYTHON")
    candidates = [env] if env else []
    manifest = _manifest_python("pymss")
    if manifest:
        candidates.append(manifest)
    candidates.append(_venv_python(PYMSS_VENV_DIR))
    return _first_file(candidates)


def _detect_pymss_model_dir() -> Path | None:
    env = _existing_env_path("XB_PYMSS_MODEL_DIR")
    candidates = [env] if env else []
    candidates.extend([PYMSS_MODEL_DIR_DEFAULT, ROOT_DIR / "all_models"])
    existing = [c for c in candidates if c.exists()]
    return existing[0] if existing else PYMSS_MODEL_DIR_DEFAULT


PYMSS_PYTHON = _detect_pymss_python()
PYMSS_MODEL_DIR = _detect_pymss_model_dir()

_PYMSS_MODEL_SUFFIXES = {".ckpt", ".th", ".pth", ".chpt", ".safetensors", ".pt"}


def pymss_environment_ready() -> bool:
    """PyMSS worker 与 Python 环境是否已安装。"""
    return bool(PYMSS_PYTHON and PYMSS_PYTHON.is_file() and PYMSS_WORKER.is_file())


def pymss_model_ready(model: str = "") -> bool:
    """指定 PyMSS catalog 模型的权重是否已下载。"""
    if not PYMSS_MODEL_DIR or not PYMSS_MODEL_DIR.exists():
        return False
    name = str(model or "").strip()
    if not name:
        return pymss_any_model_ready()
    # PyMSS 目录结构由 catalog 决定，先按常见文件名快速检查；worker 会做最终校验。
    stem = Path(name).stem.lower()
    try:
        return any(
            p.is_file()
            and p.suffix.lower() in _PYMSS_MODEL_SUFFIXES
            and not p.name.lower().endswith(".pymss_state_dict.pt")
            and stem in p.stem.lower()
            for p in PYMSS_MODEL_DIR.rglob("*")
        )
    except OSError:
        return False


def pymss_any_model_ready() -> bool:
    """Return whether the PyMSS cache contains at least one downloaded model."""
    if not PYMSS_MODEL_DIR or not PYMSS_MODEL_DIR.exists():
        return False
    try:
        return any(
            path.is_file()
            and path.suffix.lower() in _PYMSS_MODEL_SUFFIXES
            and not path.name.lower().endswith(".pymss_state_dict.pt")
            for path in PYMSS_MODEL_DIR.rglob("*")
        )
    except OSError:
        return False


def pymss_ready(model: str = "") -> bool:
    return pymss_environment_ready() and pymss_model_ready(model)


def pymss_status(model: str = "") -> str:
    if not PYMSS_PYTHON or not PYMSS_PYTHON.is_file():
        return "未找到 .venv-pymss"
    if not PYMSS_WORKER.is_file():
        return "应用 worker 缺失"
    if not PYMSS_MODEL_DIR or not PYMSS_MODEL_DIR.exists():
        return "模型目录未就绪"
    if not pymss_model_ready(model):
        return "模型未下载"
    return "已就绪"


def uvr_environment_ready() -> bool:
    """UVR 运行环境是否已安装：解释器与 worker 可用。"""
    return bool(
        UVR_PYTHON
        and UVR_PYTHON.is_file()
        and UVR_WORKER.is_file()
        and UVR_MODEL_DIR
        and UVR_MODEL_DIR.exists()
    )


def uvr_model_ready() -> bool:
    """UVR 分离模型是否已就绪。"""
    return bool(UVR_MODEL_DIR and UVR_MODEL_DIR.exists() and (UVR_MODEL_DIR / UVR_SEP_MODEL).exists())


def uvr_ready() -> bool:
    """人声分离环境是否齐备：venv 解释器、worker、模型目录与分离模型文件都在。"""
    return uvr_environment_ready() and uvr_model_ready()


def uvr_status() -> str:
    """返回更细粒度的 UVR 状态，便于界面和日志区分“未安装 / 模型未就绪 / 已就绪”。"""
    if not UVR_PYTHON or not UVR_PYTHON.is_file():
        return "未找到共享/UVR 推理环境"
    if not UVR_WORKER.is_file():
        return "应用 worker 缺失"
    if not UVR_MODEL_DIR or not UVR_MODEL_DIR.exists():
        return "模型目录未就绪"
    if not (UVR_MODEL_DIR / UVR_SEP_MODEL).exists():
        return "模型未就绪"
    return "已就绪"


def uvr_dereverb_ready() -> bool:
    """去混响模型是否可用。"""
    return bool(UVR_MODEL_DIR and UVR_MODEL_DIR.exists() and (UVR_MODEL_DIR / UVR_DEREVERB_MODEL).exists())


# ---- 模型站（ModelScope 魔搭社区）上传组件 ----
# 上传需要 modelscope SDK，装在独立轻量环境 .venv-hub（由安装器创建）。
# 搜索 / 下载 / 校验 token 走纯 HTTP（httpx），不依赖该环境。
HUB_VENV_DIR = ROOT_DIR / ".venv-hub"


def _detect_hub_python() -> Path | None:
    env = _existing_env_file("XB_HUB_PYTHON")
    candidates = [env] if env else []
    manifest = _manifest_python("hub")
    if manifest:
        candidates.append(manifest)
    candidates.append(_venv_python(HUB_VENV_DIR))
    return _first_file(candidates)


# 运行 modelscope 上传的 Python 解释器（需装有 modelscope SDK）
HUB_PYTHON = _detect_hub_python()
# 子进程内执行的上传 worker 脚本（由 .venv-hub 的 Python 读取，需为磁盘真实文件）
HUB_WORKER = BUNDLE_DIR / "infrastructure" / "hub_worker.py"


def modelhub_upload_ready() -> bool:
    """模型上传组件是否就绪（.venv-hub 解释器 + worker 脚本都在）。

    仅「上传」需要；搜索与下载不依赖该组件。
    """
    return bool(HUB_PYTHON and HUB_PYTHON.is_file() and HUB_WORKER.is_file())

# 用户数据目录（模型 / 作品 / 缓存 / 配置均保存在本地）
# 优先级：
# 1. 环境变量 XB_DATA_DIR / XB_SVCB_DATA_DIR / XB_SB_SVCB_DATA_DIR / XB_XVCB_DATA_DIR（可用于自定义存储盘）
# 2. 安装器 / 应用内迁移写入的 data_home.json
# 3. 默认目录 .xb_svcb；旧版本目录仅用于兼容升级
# 4. 新安装时默认落在安装目录下，避免把数据写到系统盘 C 盘

DATA_DIR_NAME = ".xb_svcb"
PREVIOUS_DATA_DIR_NAME = ".sb-svcb"
DATA_HOME_FILE = BASE_DIR / "data_home.json"
USER_DATA_HOME_FILE = (
    Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    / APP_NAME
    / "data_home.json"
)
DATA_HOME_FILES = (USER_DATA_HOME_FILE, DATA_HOME_FILE)
DATA_MARKER_FILE = ".xb_svcb_data"
DATA_MIGRATION_MARKER = ".xb_svcb_migration_source"
LEGACY_DATA_MARKER_FILES = (
    ".sb-svcb_data",
    ".xb_xvcb_data",
    ".sv-xvcb_data",
)
LEGACY_DATA_DIR_NAMES = (
    PREVIOUS_DATA_DIR_NAME,
    ".xb_xvcb",
    ".sv-xvcb",
    ".xb-svcb",
)
LEGACY_DATA_MIGRATION_MARKERS = (
    ".sb-svcb_migration_source",
    ".xb_xvcb_migration_source",
    ".sv-xvcb_migration_source",
)


def data_dir_env_override() -> str | None:
    return (
        os.environ.get("XB_DATA_DIR")
        or os.environ.get("XB_SVCB_DATA_DIR")
        or os.environ.get("XB_SB_SVCB_DATA_DIR")
        or os.environ.get("XB_XVCB_DATA_DIR")
    )


def _read_data_home_file(path: Path) -> tuple[Path, dict[str, str], float] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    raw = data.get("data_dir") if isinstance(data, dict) else None
    if not raw:
        return None
    try:
        target = Path(str(raw)).expanduser().resolve()
        mtime = path.stat().st_mtime
    except OSError:
        return None
    payload = {str(k): str(v) for k, v in data.items() if isinstance(k, str)}
    return target, payload, mtime


def _read_data_home_rows() -> list[tuple[Path, Path, dict[str, str], float]]:
    rows: list[tuple[Path, Path, dict[str, str], float]] = []
    for path in DATA_HOME_FILES:
        row = _read_data_home_file(path)
        if row:
            rows.append((path, *row))
    return rows


def _active_data_home_row() -> tuple[Path, Path, dict[str, str], float] | None:
    rows = _read_data_home_rows()
    if not rows:
        return None
    return max(rows, key=lambda item: item[3])


def _read_data_home() -> Path | None:
    row = _active_data_home_row()
    return row[1] if row else None


def active_data_home_file() -> Path:
    row = _active_data_home_row()
    return row[0] if row else DATA_HOME_FILE


def active_data_home_payload() -> dict[str, str]:
    row = _active_data_home_row()
    return dict(row[2]) if row else {}


def _resolve_data_dir() -> Path:
    env = data_dir_env_override()
    if env:
        return Path(env).expanduser().resolve()

    configured = _read_data_home()
    if configured:
        return configured

    for base in (BASE_DIR, Path.home()):
        preferred = base / DATA_DIR_NAME
        if preferred.exists():
            return preferred
    for base in (BASE_DIR, Path.home()):
        for name in LEGACY_DATA_DIR_NAMES:
            legacy_dir = base / name
            if legacy_dir.exists():
                return legacy_dir

    return BASE_DIR / DATA_DIR_NAME


def write_data_home(data_dir: Path, pending_delete: Path | None = None) -> bool:
    """写入持久化数据目录指针。应用内迁移和安装器使用同一文件。"""
    try:
        target = data_dir.expanduser().resolve()
        pending = pending_delete.expanduser().resolve() if pending_delete else None
    except OSError:
        return False
    payload: dict[str, str] = {"data_dir": str(target)}
    if pending:
        payload["pending_delete"] = str(pending)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    ok = False
    for path in DATA_HOME_FILES:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(path)
            ok = True
        except OSError:
            continue
    return ok and _read_data_home() == target


def _rewrite_persisted_data_paths(data_dir: Path, old_root: Path, new_root: Path) -> bool:
    """Rewrite absolute paths stored in root-level JSON after a directory rename."""
    try:
        old_text = str(old_root.expanduser().resolve())
        new_text = str(new_root.expanduser().resolve())
    except OSError:
        return False
    if old_text.lower() == new_text.lower():
        return True

    old_lower = old_text.lower()
    old_key = old_lower.replace("/", "\\")

    def rewrite(value):  # noqa: ANN001, ANN202 - recursive JSON value
        if isinstance(value, str):
            lower = value.lower()
            key = lower.replace("/", "\\")
            if key == old_key:
                return new_text
            if key.startswith(old_key + "\\"):
                return str(Path(new_text + value[len(old_text) :]))
            return value
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if isinstance(value, dict):
            return {key: rewrite(item) for key, item in value.items()}
        return value

    originals: dict[Path, str] = {}
    updates: dict[Path, str] = {}
    try:
        for path in data_dir.glob("*.json"):
            original = path.read_text(encoding="utf-8")
            payload = json.loads(original)
            rewritten = rewrite(payload)
            if rewritten != payload:
                originals[path] = original
                updates[path] = json.dumps(rewritten, ensure_ascii=False, indent=2)
        for path, text in updates.items():
            temporary = path.with_suffix(path.suffix + ".path-migration.tmp")
            temporary.write_text(text, encoding="utf-8")
            temporary.replace(path)
        return True
    except (OSError, json.JSONDecodeError):
        for path, original in originals.items():
            try:
                path.write_text(original, encoding="utf-8")
            except OSError:
                pass
        return False
    finally:
        for path in updates:
            try:
                path.with_suffix(path.suffix + ".path-migration.tmp").unlink(missing_ok=True)
            except OSError:
                pass


def _upgrade_previous_default_data_dir(data_dir: Path) -> Path:
    """Rename the mistaken ``.sb-svcb`` default to ``.xb_svcb`` safely.

    This only runs when no explicit environment override is active. The rename
    stays on the same volume and is rolled back if the persistent data-home
    pointer cannot be updated. If both directories already exist, keep the
    configured one rather than merging or hiding either user's data.
    """
    try:
        source = data_dir.expanduser().resolve()
        if source.name.lower() == DATA_DIR_NAME.lower():
            previous = source.with_name(PREVIOUS_DATA_DIR_NAME)
            if source.exists():
                _rewrite_persisted_data_paths(source, previous, source)
            return source
        if source.name.lower() != PREVIOUS_DATA_DIR_NAME.lower():
            return source
        target = source.with_name(DATA_DIR_NAME)
        if target.exists():
            if not source.exists():
                _rewrite_persisted_data_paths(target, source, target)
                write_data_home(target)
                return target
            return source
        if not source.exists():
            return source
        source.replace(target)
        if _rewrite_persisted_data_paths(target, source, target) and write_data_home(target):
            return target
        _rewrite_persisted_data_paths(target, target, source)
        target.replace(source)
        write_data_home(source)
        return source
    except OSError:
        return data_dir


def refresh_data_dir_from_home() -> bool:
    """从最新有效指针重新同步当前进程的数据目录。"""
    configured = _read_data_home()
    if not configured:
        return False
    try:
        current = DATA_DIR.resolve()
    except OSError:
        return False
    if configured == current:
        return False
    _apply_data_dir(configured)
    return True


def cleanup_pending_migration() -> None:
    """启动到新数据目录后，清理上次迁移留下的旧目录。

    只有旧目录内存在迁移标记且标记指向当前 DATA_DIR 时才删除，避免误删用户
    手动指定的普通文件夹。
    """
    data = active_data_home_payload()
    if not isinstance(data, dict) or not data.get("pending_delete"):
        return
    try:
        old = Path(str(data["pending_delete"])).expanduser().resolve()
        current = DATA_DIR.resolve()
    except OSError:
        return
    if old == current or not old.exists() or old.parent == old:
        return
    marker = old / DATA_MIGRATION_MARKER
    if not marker.exists():
        for legacy_name in LEGACY_DATA_MIGRATION_MARKERS:
            legacy_marker = old / legacy_name
            if legacy_marker.exists():
                marker = legacy_marker
                break
    try:
        marker_payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(marker_payload, dict):
        return
    if str(marker_payload.get("target") or "") != str(current):
        return
    try:
        shutil.rmtree(old)
        write_data_home(current)
    except OSError:
        pass


def _apply_data_dir(data_dir: Path) -> None:
    """更新当前进程内的数据目录派生路径。"""
    global DATA_DIR, MODELS_DIR, WORKS_DIR, TEMP_DIR, MUSIC_DIR, WEBVIEW_DIR
    global MODELS_DB, WORKS_DB, SETTINGS_DB, MODELHUB_DIR, EDITOR_DIR
    global EDITOR_CACHE_DIR, EDITOR_PROJECTS_DB, THEME_MEDIA_DIR, API_UPLOADS_DIR, PLUGINS_DIR, PLUGIN_DATA_DIR

    DATA_DIR = data_dir.expanduser().resolve()
    MODELS_DIR = DATA_DIR / "models"
    WORKS_DIR = DATA_DIR / "works"
    TEMP_DIR = DATA_DIR / "temp"
    # 在线下载的歌曲存放目录（资源获取页下载的素材，可在翻唱页选用）
    MUSIC_DIR = DATA_DIR / "music"
    # WebView2 持久化目录：存放前端 localStorage / cookie，使主题、头像等设置跨重启记忆。
    # 必须配合 webview.start(private_mode=False, storage_path=WEBVIEW_DIR) 才会持久化。
    WEBVIEW_DIR = DATA_DIR / "webview"

    MODELS_DB = DATA_DIR / "models.json"
    WORKS_DB = DATA_DIR / "works.json"
    SETTINGS_DB = DATA_DIR / "settings.json"
    # 上传 / 下载暂存目录
    MODELHUB_DIR = DATA_DIR / "modelhub"
    # 轻量音频编辑器工程与缓存目录
    EDITOR_DIR = DATA_DIR / "editor"
    EDITOR_CACHE_DIR = EDITOR_DIR / "cache"
    EDITOR_PROJECTS_DB = DATA_DIR / "editor_projects.json"
    # 自定义主题背景媒体（图片 / MP4 动态壁纸）持久化目录
    THEME_MEDIA_DIR = DATA_DIR / "theme" / "media"
    # FastAPI 外部接入上传的源音频。服务默认关闭，仅在用户手动启动后写入。
    API_UPLOADS_DIR = DATA_DIR / "api" / "uploads"
    # 用户安装的声明式扩展插件。插件代码不会在桌面进程内执行。
    PLUGINS_DIR = DATA_DIR / "plugins"
    PLUGIN_DATA_DIR = DATA_DIR / "plugin-data"


def switch_data_dir(data_dir: Path) -> None:
    """迁移完成后让当前会话立刻使用新的用户数据目录。"""
    _apply_data_dir(data_dir)


_initial_data_dir = _resolve_data_dir()
if not data_dir_env_override():
    _initial_data_dir = _upgrade_previous_default_data_dir(_initial_data_dir)
_apply_data_dir(_initial_data_dir)

# ---- 在线音乐资源 API（妖狐 API）----
# 用户需在「资源获取」页填写自己的 API Key（控制台->密钥管理）。
# 接口形如 https://api.yaohud.cn/api/music/{source}，source 支持多个曲库。
MUSIC_API_BASE = "https://api.yaohud.cn/api/music"
# 可选曲库（source -> 显示名）。wy=网易云，qq=QQ音乐，kuwo=酷我音乐。
MUSIC_SOURCES: dict[str, str] = {
    "wy": "网易云音乐",
    "qq": "QQ音乐",
    "kuwo": "酷我音乐",
}
# 默认曲库
MUSIC_API_DEFAULT_SOURCE = "wy"
# 仅 QQ音乐支持的曲库（可填写会员 Cookie 以获取高品质音频）
MUSIC_COOKIE_SOURCES = ("qq",)


def music_api_url(source: str) -> str:
    """根据曲库标识拼接妖狐音乐 API 地址（非法标识回退默认源）。"""
    src = source if source in MUSIC_SOURCES else MUSIC_API_DEFAULT_SOURCE
    return f"{MUSIC_API_BASE}/{src}"


# 兼容旧引用：默认网易云源地址。
MUSIC_API_URL = music_api_url(MUSIC_API_DEFAULT_SOURCE)
# 接口限制 10 QPS，客户端侧统一限流，避免触发风控。
MUSIC_API_QPS = 10

# ---- 模型站（ModelScope 魔搭社区）----
# 用户在「模型站」填写自己的 ModelScope 访问令牌（个人中心->访问令牌）。
# 上传到自己命名空间下、名称带固定前缀并写入清单文件，下载侧据此筛选，避免被无关模型污染。
MODELSCOPE_ENDPOINT = "https://www.modelscope.cn"
# 本软件上传模型的统一标记关键词（用于全局搜索发现 + 防污染软校验）
MODELSCOPE_MARKER = "xb-svcb-voice-model"
# 上传仓库名前缀（owner/<前缀>-<slug>-<短id>）
MODELHUB_REPO_PREFIX = "xb-svcb"
# 写入仓库的清单文件名与 schema/magic（下载时校验，确认确为本软件上传）
MODELHUB_MANIFEST = "xb-svcb-model.json"
MODELHUB_SCHEMA = 1
MODELHUB_MAGIC = "XB-SVCB-VOICE-MODEL"
# 模型架构标签（上传时标注，便于兼容不同框架并按类型筛选）。
# id -> 显示名；id 写入清单的 framework 字段，下载/筛选据此识别。
MODELHUB_FRAMEWORKS: dict[str, str] = {
    "so-vits-svc": "So-VITS-SVC",
    "rvc": "RVC",
    "seed-vc": "SeedVC",
    "ddsp-svc": "DDSP-SVC",
    "other": "其他",
}
# 默认架构（当前推理引擎为 so-vits-svc）
MODELHUB_DEFAULT_FRAMEWORK = "so-vits-svc"


def modelhub_normalize_framework(framework: str | None) -> str:
    """把任意输入规整为合法的架构 id（非法回退默认）。"""
    fw = (framework or "").strip().lower()
    return fw if fw in MODELHUB_FRAMEWORKS else MODELHUB_DEFAULT_FRAMEWORK


def modelhub_guess_framework(model_type: str | None) -> str:
    """根据本地模型的 type（ModelType 值）推断默认架构 id。"""
    t = (model_type or "").strip().lower()
    if "seed" in t:
        return "seed-vc"
    if "rvc" in t:
        return "rvc"
    if "ddsp" in t:
        return "ddsp-svc"
    if "so-vits" in t or "sovits" in t or t == "svc":
        return "so-vits-svc"
    return MODELHUB_DEFAULT_FRAMEWORK


# 上传 / 下载暂存目录
MODELHUB_DIR = DATA_DIR / "modelhub"
# 轻量音频编辑器工程与缓存目录
EDITOR_DIR = DATA_DIR / "editor"
EDITOR_CACHE_DIR = EDITOR_DIR / "cache"
EDITOR_PROJECTS_DB = DATA_DIR / "editor_projects.json"
PLUGINS_DIR = DATA_DIR / "plugins"
PLUGIN_DATA_DIR = DATA_DIR / "plugin-data"
# ModelScope 接口限流（客户端侧保守值）
MODELSCOPE_QPS = 5
# settings.json 中保存 ModelScope 访问令牌的键名
MODELSCOPE_TOKEN_SETTING = "modelscope_token"

# 支持的音频与模型扩展名
AUDIO_EXTS = (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac")
MODEL_EXTS = (".pth", ".onnx", ".pt", ".ckpt")
