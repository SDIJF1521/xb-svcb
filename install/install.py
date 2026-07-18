"""XB-SVCB 一键安装器（核心编排）。

为「AI 翻唱工具」搭建开箱即用的运行环境，全部组件落在项目目录内、互不污染：

  app/.venv      —— 主程序环境（pywebview，桌面壳）
  .venv-uvr/     —— 人声分离环境（audio-separator）
  .venv-svc/     —— so-vits-svc 4.1 推理环境（torch + fairseq 等）
  .venv-rvc/     —— RVC 推理环境（rvc-python；40 系及以下 cu121，50 系 cu128，CPU 版）
  .venv-seedvc/  —— SeedVC 推理环境（官方 Seed-VC；推理时提供参考音频）
  .venv-ddsp/    —— DDSP-SVC 推理环境（yxlllc/DDSP-SVC Rectified Flow）
  .venv-hub/     —— 模型上传组件（modelscope）
  engines/so-vits-svc/         —— 自动克隆的 so-vits-svc 4.1 仓库
  engines/seed-vc/              —— 自动克隆的 Seed-VC 仓库
  engines/ddsp-svc/              —— 自动克隆的 DDSP-SVC 仓库
  engines/so-vits-svc/pretrain —— 底模（contentvec / nsf_hifigan / rmvpe）
  models/uvr/    —— UVR 分离模型（5_HP-Karaoke / DeEcho-DeReverb）
  web/dist/      —— 前端构建产物

底模与 UVR 模型「自带优先」：若 assets/models/ 内存在对应文件（随安装包分发），
直接本地复制到上述目录，免去缓慢的联网下载；缺失项才回退镜像下载。

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
  python install/install.py --only models  # 只跑某一步：app/web/uvr/svc/rvc/seedvc/ddsp/hub/models
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

DEFAULT_HF_MIRROR = "https://hf-mirror.com"
DEFAULT_PYPI_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
PYPI_FALLBACK_INDEX = "https://pypi.org/simple"


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
SVC_VENV = ROOT / ".venv-svc"
HUB_VENV = ROOT / ".venv-hub"
RVC_VENV = ROOT / ".venv-rvc"
SEEDVC_VENV = ROOT / ".venv-seedvc"
DDSP_VENV = ROOT / ".venv-ddsp"
UVR_MODELS_DIR = ROOT / "models" / "uvr"

# 随安装包一起分发的「自带模型」目录：安装时直接本地复制，免联网慢下载。
# 始终相对本脚本位置（assets/models 与 install/ 同级），不随 --root 改变。
ASSETS_MODELS_DIR = Path(__file__).resolve().parent.parent / "assets" / "models"


def _derive_paths(root: Path) -> None:
    """以 root 为基准重新计算所有产物路径（供 --root 覆盖）。"""
    global ROOT, APP_DIR, WEB_DIR, ENGINES_DIR, SOVITS_DIR, SEEDVC_DIR, DDSP_DIR, PRETRAIN_DIR
    global UVR_VENV, SVC_VENV, HUB_VENV, RVC_VENV, SEEDVC_VENV, DDSP_VENV, UVR_MODELS_DIR
    ROOT = root
    APP_DIR = root / "app"
    WEB_DIR = root / "web"
    ENGINES_DIR = root / "engines"
    SOVITS_DIR = ENGINES_DIR / "so-vits-svc"
    SEEDVC_DIR = ENGINES_DIR / "seed-vc"
    DDSP_DIR = ENGINES_DIR / "ddsp-svc"
    PRETRAIN_DIR = SOVITS_DIR / "pretrain"
    UVR_VENV = root / ".venv-uvr"
    SVC_VENV = root / ".venv-svc"
    HUB_VENV = root / ".venv-hub"
    RVC_VENV = root / ".venv-rvc"
    SEEDVC_VENV = root / ".venv-seedvc"
    DDSP_VENV = root / ".venv-ddsp"
    UVR_MODELS_DIR = root / "models" / "uvr"

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

# ---- AMD / Windows DirectML stack ----
# torch-directml 0.2.5 is the latest published Windows runtime and pins torch
# 2.4.1. Keep all isolated DirectML inference environments on this exact pair so a
# later dependency cannot silently replace the registered DirectML backend.
TORCH_DIRECTML_VER = "0.2.5.dev240914"
TORCH_DIRECTML_TORCH_VER = "2.4.1"
TORCHAUDIO_DIRECTML_VER = "2.4.1"
AUDIO_SEPARATOR_VER = "0.44.2"

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
# so-vits-svc 4.1 的依赖（numpy 1.19.5 / scipy 1.7.3 / pyworld 0.3.0 等）是为
# Python 3.8~3.9 钉的版本，这些版本只在 3.9 及更低有预编译 wheel；在 3.10 上会回退到
# 源码现场编译并失败（numpy 用到 3.10 改签名的 _Py_HashDouble；pyworld 的构建依赖又拉
# 旧 numpy）。因此 SVC 引擎固定用 Python 3.9，整套依赖直接装 wheel、零编译。
PYTHON_FOR_SVC = "3.9"
# RVC（rvc-python）依赖 fairseq==0.12.2 + numpy<=1.23.5，与 so-vits 同属老栈，
# 同样固定 Python 3.9 以最大化预编译 wheel 命中、规避 fairseq 现场编译失败。
PYTHON_FOR_RVC = "3.9"
# Blackwell（50 系）下改用 3.10：cu128 的 torch2.7.1 有 cp310 轮子，且 numpy 1.23.5 /
# pyworld 等在 3.10 也有可用 wheel；3.9 老栈在新 torch 上易出哑音。
PYTHON_FOR_SVC_BLACKWELL = "3.10"
PYTHON_FOR_RVC_BLACKWELL = "3.10"

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


def warn_pypi_fallback() -> None:
    print(c("y", f"    PyPI mirror failed; retrying with official PyPI: {PYPI_FALLBACK_INDEX}"))


def venv_python(venv_dir: Path) -> Path:
    return (
        venv_dir / "Scripts" / "python.exe"
        if os.name == "nt"
        else venv_dir / "bin" / "python"
    )


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
    """Return cpu, directml, cu121 or cu128 for the local Windows adapter."""
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


def ensure_uv() -> str:
    """确保 uv 可用；缺失时尝试用当前 Python 的 pip 安装并定位其可执行文件。"""
    if have("uv"):
        return "uv"
    print(c("y", "未检测到 uv，尝试通过 pip 安装 …"))
    try:
        run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-U",
                "uv",
                "-i",
                PYPI_MIRROR,
                "--extra-index-url",
                PYPI_FALLBACK_INDEX,
            ]
        )
    except subprocess.CalledProcessError:
        if PYPI_MIRROR == PYPI_FALLBACK_INDEX:
            raise
        warn_pypi_fallback()
        run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-U",
                "uv",
                "-i",
                PYPI_FALLBACK_INDEX,
            ]
        )
    if have("uv"):
        return "uv"
    # pip 装到 Scripts 目录但未加入 PATH 时，直接用绝对路径
    exe = Path(sys.executable).parent / ("uv.exe" if os.name == "nt" else "uv")
    if exe.exists():
        return str(exe)
    raise RuntimeError("uv 安装后仍不可用，请手动安装 uv 后重试：pip install uv")


def uv_cmd(uv: str, *args: str) -> list[str]:
    return [uv, *args]


def uv_pip_install(
    uv: str,
    py: str,
    *args: str,
    index: str | None = None,
) -> None:
    """`uv pip install`；失败时自动加 --reinstall 重试一次。

    用于自愈被中断的半成品安装：典型表现是 site-packages 里留下空的
    `*.dist-info` 目录（缺 METADATA），再次安装会报
    `failed to open file ... METADATA (os error 2)`。--reinstall 会强制
    重新下载并覆盖，绕过损坏的旧元数据。
    """
    def build(reinstall: bool, use_mirror: bool = True) -> list[str]:
        extra = ["--reinstall"] if reinstall else []
        cmd = uv_cmd(uv, "pip", "install", *extra, "--python", py, *args)
        cmd += pypi_index_args(index, use_mirror=use_mirror)
        return cmd

    try:
        run(build(reinstall=False))
    except subprocess.CalledProcessError:
        print(c("y", "    安装失败，尝试 --reinstall 重装以修复损坏/残缺的旧安装 …"))
        try:
            run(build(reinstall=True))
        except subprocess.CalledProcessError:
            if PYPI_MIRROR == PYPI_FALLBACK_INDEX:
                raise
            warn_pypi_fallback()
            try:
                run(build(reinstall=False, use_mirror=False))
            except subprocess.CalledProcessError:
                print(c("y", "    Official PyPI retry failed; trying --reinstall once..."))
                run(build(reinstall=True, use_mirror=False))


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
    """若自带模型目录里有该资源（文件或目录），就本地复制到 dest。

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
        shutil.copytree(src, dest, dirs_exist_ok=True)
        print(c("g", f"    复制完成：{dest.name}/"))
        return True
    # 文件：仅当目标已存在且大小与自带文件完全一致才跳过；大小不符（残缺/损坏）则重新复制覆盖。
    # 这能自愈旧安装器下载到的残缺底模（如 16.5MB 的 ContentVec 应为 1268MB）。
    if dest.exists() and dest.is_file() and dest.stat().st_size == src.stat().st_size:
        print(c("g", f"    已存在且完整，跳过：{dest.name}"))
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"    自带模型，本地复制 {src.name} …")
    shutil.copyfile(src, dest)
    print(c("g", f"    复制完成：{dest.name}"))
    return True


def _is_large_model_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= 32 * 1024 * 1024
    except OSError:
        return False


def _link_or_copy_model(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".xbtmp")
    tmp.unlink(missing_ok=True)
    try:
        os.link(src, tmp)
    except OSError:
        shutil.copy2(src, tmp)
    tmp.replace(dest)


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
    hr("1/9 主程序环境 app/.venv")
    uv_sync(uv, APP_DIR)
    print(c("g", "主程序环境就绪"))


def step_web() -> None:
    hr("2/9 前端构建 web/dist")
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
    hr("3/9 人声分离环境 .venv-uvr（audio-separator）")
    use_blackwell = gpu_stack == "cu128"
    use_cuda = gpu_stack in {"cu121", "cu128"}
    use_directml = gpu_stack == "directml"
    if not venv_python(UVR_VENV).exists():
        run(uv_cmd(uv, "venv", "--python", PYTHON_FOR_ENGINES, str(UVR_VENV)))
    py = str(venv_python(UVR_VENV))

    def pip(*args: str, index: str | None = None) -> None:
        uv_pip_install(uv, py, *args, index=index)

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
        ]
        torch_index = TORCH_BLACKWELL_INDEX
        torch_label = "cu128"
        pip(*torch_specs, index=torch_index)
    elif use_cuda:
        torch_specs = ["torch==2.5.1", "torchaudio==2.5.1"]
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
        pip(f"audio-separator[gpu]=={AUDIO_SEPARATOR_VER}", index=torch_index)
        _reaffirm_torch_wheels(uv, py, torch_specs, torch_index, torch_label)
        _verify_cuda_torch(py, "UVR")
    elif use_directml:
        pip(f"audio-separator[dml]=={AUDIO_SEPARATOR_VER}")
        _reaffirm_directml_runtime(uv, py)
        _verify_directml_torch(py, "UVR")
        _verify_uvr_directml(py)
    else:
        pip(f"audio-separator[cpu]=={AUDIO_SEPARATOR_VER}")
    print(c("g", "分离环境就绪"))


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
    try:
        out = subprocess.run(
            [str(py), "-c", "import sys;print('%d.%d'%sys.version_info[:2])"],
            capture_output=True, text=True, timeout=30,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def step_svc(uv: str, gpu_stack: str) -> None:
    hr("4/9 推理引擎 so-vits-svc + .venv-svc")
    fetch_sovits()

    use_blackwell = gpu_stack == "cu128"
    use_gpu = gpu_stack in {"cu121", "cu128"}
    use_directml = gpu_stack == "directml"

    # 目标 Python：Blackwell 用 3.10（cu128 轮子 + 3.10 兼容依赖），否则老栈 3.9。
    target_py = PYTHON_FOR_SVC_BLACKWELL if use_blackwell else PYTHON_FOR_SVC
    # 创建环境。若已存在但版本不符（含老卡/新卡切换），则重建，避免依赖错配。
    py_path = venv_python(SVC_VENV)
    if py_path.exists():
        ver = _venv_pyver(py_path)
        if ver != target_py:
            print(c("y", f"    现有 .venv-svc 为 Python {ver or '未知'}，需要 {target_py}，重建中 …"))
            shutil.rmtree(SVC_VENV, ignore_errors=True)
    if not venv_python(SVC_VENV).exists():
        run(uv_cmd(uv, "venv", "--python", target_py, str(SVC_VENV)))
    py = str(venv_python(SVC_VENV))

    def pip(*args: str, index: str | None = None) -> None:
        uv_pip_install(uv, py, *args, index=index)

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
            filtered = _filter_requirements(req_file, extra_deny=DIRECTML_EXTRA_DENY)
            pip("-r", str(filtered))
            pip("matplotlib==3.7.5", "soundfile")
        else:
            print(c("r", "    未找到 requirements，跳过依赖安装（请检查仓库）"))
        _reaffirm_directml_runtime(uv, py)
        _verify_directml_torch(py, "So-VITS-SVC")
        print(c("g", "推理环境就绪（AMD DirectML）"))
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
                overrides=BLACKWELL_REQ_OVERRIDES,
            )
            pip("-r", str(filtered))
            # 显式确保读写音频用的 soundfile 在位（svc_worker 的 torchaudio 垫片依赖它）
            pip("soundfile")
            # matplotlib 在 3.10 用较新版本（3.7.5 也可，但 3.10 下放宽到 3.8.x 更易装）
            pip("matplotlib==3.8.4")
            # fairseq 单独装（py3.10 无官方 wheel，单列以便定位失败）
            _install_fairseq_blackwell(pip)
            # 兜底：fairseq 可能把 cu128 torch 换成同号 CPU 版 → 强制校正回 cu128
            _reaffirm_blackwell_torch(uv, py)
            # 修复早期错误补丁（weights_only 误插进 torch.device）；weights_only 兼容由
            # svc_worker 运行时 monkey-patch torch.load 处理
            _patch_fairseq_weights_only(venv_python(SVC_VENV))
        else:
            print(c("r", "    未找到 requirements，跳过依赖安装（请检查仓库）"))
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
        pip("matplotlib==3.7.5")
    else:
        print(c("r", "    未找到 requirements，跳过依赖安装（请检查仓库）"))
    if use_gpu:
        _reaffirm_torch_wheels(uv, py, torch_specs, torch_index, "cu121")
    print(c("g", "推理环境就绪"))


def _filter_requirements(
    src: Path,
    extra_deny: set[str] | None = None,
    overrides: dict[str, str] | None = None,
) -> Path:
    """剔除推理用不到/装不上的包（见 REQ_DENYLIST），生成精简 requirements。

    extra_deny：额外剔除的包名（小写、连字符）；用于 Blackwell 下自行管理的 torch/fairseq 等。
    overrides：包名 -> 整行 requirement 覆盖（如 numpy 升到 3.10 兼容版本）；命中即替换原行，
               未在原文件出现的覆盖项会在末尾追加。
    """
    out = src.parent / "requirements_xb.txt"
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


# Blackwell（py3.10）下 so-vits / RVC 需要的、对新 torch 友好的依赖覆盖。
# numpy 1.23.5 仍有 cp310 轮子且兼容 so-vits 代码（未用 1.24 移除的 np.float 等别名）；
# pyworld 0.3.4 提供 cp310 轮子，避免 0.3.0 在 3.10 现场编译失败；
# scipy 1.10.1 提供 cp310 轮子且兼容 numpy 1.23.5（so-vits 原钉的旧 scipy 在 3.10
# 无轮子会现场编译失败 / 与 numpy 1.23 不匹配）。
BLACKWELL_REQ_OVERRIDES = {
    "numpy": "numpy==1.23.5",
    "pyworld": "pyworld==0.3.4",
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


def _reaffirm_directml_runtime(uv: str, py: str) -> None:
    uv_pip_install(
        uv,
        py,
        "--reinstall-package",
        "torch-directml",
        f"torch-directml=={TORCH_DIRECTML_VER}",
        f"torchaudio=={TORCHAUDIO_DIRECTML_VER}",
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
            f"{component} AMD 环境校验失败：DirectML 不可用，请更新 AMD 显卡驱动后重试"
        ) from exc


def _verify_uvr_directml(py: str) -> None:
    check = (
        "import onnxruntime as ort; "
        "from audio_separator.separator import Separator; "
        "assert 'DmlExecutionProvider' in ort.get_available_providers(), "
        "'DmlExecutionProvider unavailable'; "
        "s=Separator(info_only=True,use_directml=True); "
        "assert str(s.torch_device).startswith('privateuseone'), "
        "f'Unexpected UVR device: {s.torch_device}'; "
        "print('UVR DirectML',s.torch_device,ort.get_available_providers())"
    )
    try:
        run([py, "-c", check])
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "UVR AMD 环境校验失败：audio-separator 未启用 DirectML / DmlExecutionProvider"
        ) from exc


def _reaffirm_torch_wheels(
    uv: str,
    py: str,
    torch_specs: list[str],
    index: str,
    label: str,
) -> None:
    """兜底：强制把指定 PyTorch wheel 源里的 torch/torchaudio 重新装回来。

    audio-separator / fairseq / rvc-python 等依赖在解析时可能把 CUDA torch 换成
    PyPI 默认的「同版本号 CPU 版」，导致 torch.cuda.is_available()=False，
    推理时报 "Attempting to deserialize object on a CUDA device but
    torch.cuda.is_available() is False"。普通 install 因版本号相同会判定已满足而不覆盖，
    这里用 --reinstall-package 只强制重装 torch/torchaudio（不动其它包）。
    """
    cmd = uv_cmd(
        uv, "pip", "install",
        "--reinstall-package", "torch", "--reinstall-package", "torchaudio",
        "--python", py,
        *torch_specs,
        *pypi_index_args(index),
    )
    try:
        run(cmd)
        print(c("g", f"    已校正 {label} torch（防止被依赖替换成 CPU 版）"))
    except subprocess.CalledProcessError:
        print(c("y", f"    {label} torch 校正失败，请检查网络/驱动后重跑该步"))


def _reaffirm_blackwell_torch(uv: str, py: str) -> None:
    _reaffirm_torch_wheels(
        uv,
        py,
        [f"torch=={TORCH_BLACKWELL_VER}", f"torchaudio=={TORCHAUDIO_BLACKWELL_VER}"],
        TORCH_BLACKWELL_INDEX,
        "cu128",
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
    hr("5/9 RVC 推理环境 .venv-rvc（rvc-python）")
    use_blackwell = gpu_stack == "cu128"
    use_gpu = gpu_stack in {"cu121", "cu128"}
    use_directml = gpu_stack == "directml"
    # RVC 推理在独立环境运行（rvc-python），与 so-vits 栈隔离。
    # rvc-python 默认会在首次推理时下载 hubert / rmvpe；这里安装后立即预置，
    # 避免新用户运行 RVC 时因为 HuggingFace 连接失败而报 HTTPSConnectionPool。
    target_py = PYTHON_FOR_RVC_BLACKWELL if use_blackwell else PYTHON_FOR_RVC
    py_path = venv_python(RVC_VENV)
    if py_path.exists():
        ver = _venv_pyver(py_path)
        if ver != target_py:
            print(c("y", f"    现有 .venv-rvc 为 Python {ver or '未知'}，需要 {target_py}，重建中 …"))
            shutil.rmtree(RVC_VENV, ignore_errors=True)
    if not venv_python(RVC_VENV).exists():
        run(uv_cmd(uv, "venv", "--python", target_py, str(RVC_VENV)))
    py = str(venv_python(RVC_VENV))

    def pip(*args: str, index: str | None = None) -> None:
        uv_pip_install(uv, py, *args, index=index)

    # uv venv 默认不含 setuptools；fairseq/rvc 运行时可能用到 pkg_resources，先补齐
    pip("setuptools<81", "wheel")
    if use_directml:
        _install_directml_runtime(pip)
        pip("rvc-python")
        _reaffirm_directml_runtime(uv, py)
        seed_rvc_base_models(venv_python(RVC_VENV))
        _verify_directml_torch(py, "RVC")
        print(c("g", "RVC 推理环境就绪（AMD DirectML）"))
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
        _reaffirm_blackwell_torch(uv, py)
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
        _reaffirm_torch_wheels(uv, py, torch_specs, torch_index, "cu121")
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
}


def step_seedvc(uv: str, gpu_stack: str) -> None:
    hr("6/9 SeedVC 推理环境 engines/seed-vc + .venv-seedvc")
    fetch_seedvc()

    use_blackwell = gpu_stack == "cu128"
    use_gpu = gpu_stack in {"cu121", "cu128"}
    use_directml = gpu_stack == "directml"

    target_py = PYTHON_FOR_ENGINES
    py_path = venv_python(SEEDVC_VENV)
    if py_path.exists():
        ver = _venv_pyver(py_path)
        if ver != target_py:
            print(c("y", f"    现有 .venv-seedvc 为 Python {ver or '未知'}，需要 {target_py}，重建中 …"))
            shutil.rmtree(SEEDVC_VENV, ignore_errors=True)
    if not venv_python(SEEDVC_VENV).exists():
        run(uv_cmd(uv, "venv", "--python", target_py, str(SEEDVC_VENV)))
    py = str(venv_python(SEEDVC_VENV))

    def pip(*args: str, index: str | None = None) -> None:
        uv_pip_install(uv, py, *args, index=index)

    pip("setuptools<81", "wheel")
    if use_directml:
        torch_specs = []
        torch_index = ""
        _install_directml_runtime(pip)
    elif use_blackwell:
        torch_specs = [
            f"torch=={TORCH_BLACKWELL_VER}",
            f"torchaudio=={TORCHAUDIO_BLACKWELL_VER}",
        ]
        torch_index = TORCH_BLACKWELL_INDEX
    else:
        torch_specs = ["torch==2.5.1", "torchaudio==2.5.1"]
        torch_index = TORCH_CUDA_INDEX if use_gpu else TORCH_CPU_INDEX
    pip(*torch_specs, index=torch_index)

    req = SEEDVC_DIR / "requirements.txt"
    if req.exists():
        filtered = _filter_requirements(req, extra_deny=SEEDVC_REQ_DENY)
        pip("-r", str(filtered))
    else:
        print(c("r", "    未找到 SeedVC requirements.txt，跳过依赖安装（请检查仓库）"))

    seed_seedvc_base_models(venv_python(SEEDVC_VENV))

    if use_directml:
        _reaffirm_directml_runtime(uv, py)
        _verify_directml_torch(py, "SeedVC")
        print(c("g", "SeedVC 推理环境就绪（AMD DirectML）"))
    elif use_blackwell:
        _reaffirm_blackwell_torch(uv, py)
        print(c("g", "SeedVC 推理环境就绪（Blackwell/cu128）"))
    elif use_gpu:
        _reaffirm_torch_wheels(uv, py, torch_specs, torch_index, "cu121")
        print(c("g", "SeedVC 推理环境就绪（cu121）"))
    else:
        print(c("g", "SeedVC 推理环境就绪（CPU）"))


def step_ddsp(uv: str, gpu_stack: str) -> None:
    hr("7/9 DDSP-SVC 推理环境 engines/ddsp-svc + .venv-ddsp")
    fetch_ddsp()

    use_blackwell = gpu_stack == "cu128"
    use_gpu = gpu_stack in {"cu121", "cu128"}
    use_directml = gpu_stack == "directml"

    target_py = PYTHON_FOR_ENGINES
    py_path = venv_python(DDSP_VENV)
    if py_path.exists():
        ver = _venv_pyver(py_path)
        if ver != target_py:
            print(c("y", f"    现有 .venv-ddsp 为 Python {ver or '未知'}，需要 {target_py}，重建中 …"))
            shutil.rmtree(DDSP_VENV, ignore_errors=True)
    if not venv_python(DDSP_VENV).exists():
        run(uv_cmd(uv, "venv", "--python", target_py, str(DDSP_VENV)))
    py = str(venv_python(DDSP_VENV))

    def pip(*args: str, index: str | None = None) -> None:
        uv_pip_install(uv, py, *args, index=index)

    pip("setuptools<81", "wheel")
    if use_directml:
        torch_specs = []
        torch_index = ""
        _install_directml_runtime(pip)
    elif use_blackwell:
        torch_specs = [
            f"torch=={TORCH_BLACKWELL_VER}",
            f"torchaudio=={TORCHAUDIO_BLACKWELL_VER}",
        ]
        torch_index = TORCH_BLACKWELL_INDEX
    else:
        torch_specs = ["torch==2.5.1", "torchaudio==2.5.1"]
        torch_index = TORCH_CUDA_INDEX if use_gpu else TORCH_CPU_INDEX
    pip(*torch_specs, index=torch_index)

    requirements = DDSP_DIR / "requirements.txt"
    if requirements.exists():
        filtered = _filter_requirements(
            requirements,
            extra_deny=DDSP_REQ_DENY | (DIRECTML_EXTRA_DENY if use_directml else set()),
        )
        pip("-r", str(filtered))
    else:
        raise RuntimeError("未找到 DDSP-SVC requirements.txt")
    seed_ddsp_base_models()

    if use_directml:
        _reaffirm_directml_runtime(uv, py)
        _verify_directml_torch(py, "DDSP-SVC")
        print(c("g", "DDSP-SVC 推理环境就绪（AMD DirectML）"))
    elif use_blackwell:
        _reaffirm_blackwell_torch(uv, py)
        _verify_cuda_torch(py, "DDSP-SVC")
        print(c("g", "DDSP-SVC 推理环境就绪（Blackwell/cu128）"))
    elif use_gpu:
        _reaffirm_torch_wheels(uv, py, torch_specs, torch_index, "cu121")
        _verify_cuda_torch(py, "DDSP-SVC")
        print(c("g", "DDSP-SVC 推理环境就绪（cu121）"))
    else:
        print(c("g", "DDSP-SVC 推理环境就绪（CPU）"))


def step_hub(uv: str) -> None:
    hr("8/9 模型上传组件 .venv-hub（modelscope）")
    # 仅「分享到模型站（上传）」需要 modelscope SDK；搜索 / 下载走纯 HTTP，不依赖本环境。
    # 用 3.10（与 UVR 一致），装 modelscope hub 能力即可（上传用 upload_folder，无需本地 git）。
    if not venv_python(HUB_VENV).exists():
        run(uv_cmd(uv, "venv", "--python", PYTHON_FOR_ENGINES, str(HUB_VENV)))
    py = str(venv_python(HUB_VENV))

    def pip(*args: str, index: str | None = None) -> None:
        uv_pip_install(uv, py, *args, index=index)

    # uv venv 默认不含 setuptools，modelscope 运行时可能用到 pkg_resources，先补齐
    pip("setuptools<81", "wheel")
    # modelscope SDK（含 hub 上传能力）+ 依赖
    pip("modelscope", "requests", "tqdm")
    print(c("g", "模型上传组件就绪"))


def step_models(uv: str) -> None:
    hr("9/9 底模 + UVR 模型（自带优先，缺失才联网下载）")
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

    # 3b) FCPE（可选 F0 预测器；仅在自带目录里有时复制）
    if (ASSETS_MODELS_DIR / "pretrain" / "fcpe.pt").exists():
        print(c("b", "  · FCPE (可选)"))
        copy_bundled("pretrain/fcpe.pt", PRETRAIN_DIR / "fcpe.pt")

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
        uvr_py = venv_python(UVR_VENV)
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
            print(c("r", "    .venv-uvr 不存在且无自带模型，跳过（请先跑 uvr 步骤或放置自带模型）"))
    print(c("g", "模型就绪"))


STEPS = {
    "app": lambda uv, stack: step_app(uv),
    "web": lambda uv, stack: step_web(),
    "uvr": lambda uv, stack: step_uvr(uv, stack),
    "svc": lambda uv, stack: step_svc(uv, stack),
    "rvc": lambda uv, stack: step_rvc(uv, stack),
    "seedvc": lambda uv, stack: step_seedvc(uv, stack),
    "ddsp": lambda uv, stack: step_ddsp(uv, stack),
    "hub": lambda uv, stack: step_hub(uv),
    "models": lambda uv, stack: step_models(uv),
}
ORDER = ["app", "web", "uvr", "svc", "rvc", "seedvc", "ddsp", "hub", "models"]


def installer_progress(percent: int, message: str) -> None:
    """Emit progress markers consumed by the Inno installer."""
    if os.environ.get("XB_FROM_INSTALLER") != "1":
        return
    percent = max(0, min(100, int(percent)))
    print(f"[XB-PROGRESS] {percent} {message}", flush=True)


def main() -> int:
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
        "--only",
        choices=ORDER,
        nargs="+",
        help="只执行指定步骤（可多选）：app web uvr svc rvc seedvc ddsp hub models",
    )
    for s in ORDER:
        p.add_argument(f"--skip-{s}", action="store_true", help=f"跳过 {s} 步骤")
    args = p.parse_args()

    installer_progress(2, "Resolving runtime root")
    if args.root:
        _derive_paths(Path(args.root).expanduser().resolve())

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
    if args.cu128 and detected_stack == "cu121":
        print(c("y", "当前显卡不是 50 系，忽略 cu128 请求，改用 cu121 栈。"))
    if args.no_cu128 and detected_stack == "cu128":
        print(c("y", "检测到 50 系/Blackwell，忽略老 CUDA 栈请求，改用 cu128。"))
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
        print("（检测到 50 系/Blackwell，自动切换 cu128 栈）")

    installer_progress(12, "Preparing uv package manager")
    uv = ensure_uv()
    print(f"uv: {uv}")
    installer_progress(18, "uv package manager is ready")

    selected = args.only if args.only else [s for s in ORDER if not getattr(args, f"skip_{s}")]
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
        completed_count += 1
        installer_progress(18 + (completed_count * 76) // selected_count, f"Finished runtime step: {s}")

    hr("安装结果汇总")
    label = {"ok": c("g", "成功"), "fail": c("r", "失败"), "skip": c("y", "跳过")}
    for s, st in results:
        print(f"  {s:<8} {label[st]}")

    if any(st == "fail" for _, st in results):
        print(c("y", "\n有步骤失败。可单独重试，例如: python install/install.py --only svc"))
        print(c("y", "失败项的手动补救方式见 install/README 或项目根 README。"))
        installer_progress(100, "Runtime environment finished with errors")
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
