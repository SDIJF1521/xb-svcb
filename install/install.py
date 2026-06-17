"""XB-SVCB 一键安装器（核心编排）。

为「AI 翻唱工具」搭建开箱即用的运行环境，全部组件落在项目目录内、互不污染：

  app/.venv      —— 主程序环境（pywebview，桌面壳）
  .venv-uvr/     —— 人声分离环境（audio-separator）
  .venv-svc/     —— so-vits-svc 4.1 推理环境（torch + fairseq 等）
  engines/so-vits-svc/         —— 自动克隆的 so-vits-svc 4.1 仓库
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
  python install/install.py --only models  # 只跑某一步：app/web/uvr/svc/models
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

# 所有产物（引擎/虚拟环境/模型）都落在 ROOT 下。默认取本脚本上级目录；
# 安装器会用 --root 显式指定为用户选择的安装目录，确保依赖装进该目录。
ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"
WEB_DIR = ROOT / "web"
ENGINES_DIR = ROOT / "engines"
SOVITS_DIR = ENGINES_DIR / "so-vits-svc"
PRETRAIN_DIR = SOVITS_DIR / "pretrain"
UVR_VENV = ROOT / ".venv-uvr"
SVC_VENV = ROOT / ".venv-svc"
UVR_MODELS_DIR = ROOT / "models" / "uvr"

# 随安装包一起分发的「自带模型」目录：安装时直接本地复制，免联网慢下载。
# 始终相对本脚本位置（assets/models 与 install/ 同级），不随 --root 改变。
ASSETS_MODELS_DIR = Path(__file__).resolve().parent.parent / "assets" / "models"


def _derive_paths(root: Path) -> None:
    """以 root 为基准重新计算所有产物路径（供 --root 覆盖）。"""
    global ROOT, APP_DIR, WEB_DIR, ENGINES_DIR, SOVITS_DIR, PRETRAIN_DIR
    global UVR_VENV, SVC_VENV, UVR_MODELS_DIR
    ROOT = root
    APP_DIR = root / "app"
    WEB_DIR = root / "web"
    ENGINES_DIR = root / "engines"
    SOVITS_DIR = ENGINES_DIR / "so-vits-svc"
    PRETRAIN_DIR = SOVITS_DIR / "pretrain"
    UVR_VENV = root / ".venv-uvr"
    SVC_VENV = root / ".venv-svc"
    UVR_MODELS_DIR = root / "models" / "uvr"

SOVITS_REPO_URL = "https://github.com/svc-develop-team/so-vits-svc.git"
SOVITS_BRANCH = "4.1-Stable"
# 无 git 时改用 GitHub 分支 ZIP（codeload 直链），免 git 也能获取仓库
SOVITS_ZIP_URL = (
    "https://github.com/svc-develop-team/so-vits-svc/archive/refs/heads/4.1-Stable.zip"
)

# CUDA wheel 源（cu121 兼容 30/40 系显卡）；CPU 用官方默认源
TORCH_CUDA_INDEX = "https://download.pytorch.org/whl/cu121"
TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"

# 底模下载清单（见 README 与 so-vits-svc 官方说明）
# HuggingFace 在国内常连不上，统一走「镜像优先 + 官方回退」。
HF_PATH_CONTENTVEC = "/lj1995/VoiceConversionWebUI/resolve/main/hubert_base.pt"
# GitHub Release 直链（在国内也常超时，故附带 ghproxy 镜像回退）
NSF_HIFIGAN_GH = (
    "https://github.com/openvpi/vocoders/releases/download/"
    "nsf-hifigan-v1/nsf_hifigan_20221211.zip"
)
RMVPE_GH = "https://github.com/yxlllc/RMVPE/releases/download/230917/rmvpe.zip"

# 镜像主机（按顺序尝试；可用 XB_HF_MIRROR / XB_GH_MIRROR 环境变量覆盖）
HF_HOSTS = [
    os.environ.get("XB_HF_MIRROR", "https://hf-mirror.com").rstrip("/"),
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


def c(tag: str, text: str) -> str:
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


def venv_python(venv_dir: Path) -> Path:
    return (
        venv_dir / "Scripts" / "python.exe"
        if os.name == "nt"
        else venv_dir / "bin" / "python"
    )


# ---------- 环境/前置检查 ----------
def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def detect_gpu() -> bool:
    """通过 nvidia-smi 粗略判断是否有 NVIDIA 显卡。"""
    if not have("nvidia-smi"):
        return False
    try:
        subprocess.run(
            ["nvidia-smi"], capture_output=True, check=True, timeout=15
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def ensure_uv() -> str:
    """确保 uv 可用；缺失时尝试用当前 Python 的 pip 安装并定位其可执行文件。"""
    if have("uv"):
        return "uv"
    print(c("y", "未检测到 uv，尝试通过 pip 安装 …"))
    run([sys.executable, "-m", "pip", "install", "-U", "uv"])
    if have("uv"):
        return "uv"
    # pip 装到 Scripts 目录但未加入 PATH 时，直接用绝对路径
    exe = Path(sys.executable).parent / ("uv.exe" if os.name == "nt" else "uv")
    if exe.exists():
        return str(exe)
    raise RuntimeError("uv 安装后仍不可用，请手动安装 uv 后重试：pip install uv")


def uv_cmd(uv: str, *args: str) -> list[str]:
    return [uv, *args]


def uv_pip_install(uv: str, py: str, *args: str, index: str | None = None) -> None:
    """`uv pip install`；失败时自动加 --reinstall 重试一次。

    用于自愈被中断的半成品安装：典型表现是 site-packages 里留下空的
    `*.dist-info` 目录（缺 METADATA），再次安装会报
    `failed to open file ... METADATA (os error 2)`。--reinstall 会强制
    重新下载并覆盖，绕过损坏的旧元数据。
    """
    def build(reinstall: bool) -> list[str]:
        extra = ["--reinstall"] if reinstall else []
        cmd = uv_cmd(uv, "pip", "install", *extra, "--python", py, *args)
        if index:
            cmd += ["--index-url", index]
        return cmd

    try:
        run(build(reinstall=False))
    except subprocess.CalledProcessError:
        print(c("y", "    安装失败，尝试 --reinstall 重装以修复损坏/残缺的旧安装 …"))
        run(build(reinstall=True))


# ---------- 下载工具 ----------
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


# ---------- 各安装步骤 ----------
def step_app(uv: str) -> None:
    hr("1/5 主程序环境 app/.venv")
    run(uv_cmd(uv, "sync"), cwd=APP_DIR)
    print(c("g", "主程序环境就绪"))


def step_web() -> None:
    hr("2/5 前端构建 web/dist")
    if not have("npm"):
        raise RuntimeError("未检测到 npm，请先安装 Node.js LTS 后重试（或 --skip-web）")
    # 优先 npm ci（依赖 lock）；无 lock 时回退 npm install
    if (WEB_DIR / "package-lock.json").exists():
        run(["npm", "ci"], cwd=WEB_DIR)
    else:
        run(["npm", "install"], cwd=WEB_DIR)
    run(["npm", "run", "build"], cwd=WEB_DIR)
    print(c("g", "前端构建完成"))


def step_uvr(uv: str, use_gpu: bool) -> None:
    hr("3/5 人声分离环境 .venv-uvr（audio-separator）")
    if not venv_python(UVR_VENV).exists():
        run(uv_cmd(uv, "venv", "--python", PYTHON_FOR_ENGINES, str(UVR_VENV)))
    py = str(venv_python(UVR_VENV))

    def pip(*args: str, index: str | None = None) -> None:
        uv_pip_install(uv, py, *args, index=index)

    # uv venv 默认不含 setuptools，部分库运行时需要 pkg_resources，先补齐
    # （setuptools 81+ 已移除 pkg_resources，钉 <81）
    pip("setuptools<81", "wheel")
    # VR 模型走 torch；GPU 时装 CUDA 版，CPU 时装 CPU 版
    pip("torch", "torchaudio", index=TORCH_CUDA_INDEX if use_gpu else TORCH_CPU_INDEX)
    # audio-separator：gpu 额外组件含 onnxruntime-gpu
    pip("audio-separator[gpu]" if use_gpu else "audio-separator[cpu]")
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


def step_svc(uv: str, use_gpu: bool) -> None:
    hr("4/5 推理引擎 so-vits-svc + .venv-svc")
    fetch_sovits()

    # 创建环境（强制 Python 3.9）。若已存在但版本不符，则重建，避免旧依赖在 3.10 现场编译失败。
    py_path = venv_python(SVC_VENV)
    if py_path.exists():
        ver = _venv_pyver(py_path)
        if ver != PYTHON_FOR_SVC:
            print(c("y", f"    现有 .venv-svc 为 Python {ver or '未知'}，需要 {PYTHON_FOR_SVC}，重建中 …"))
            shutil.rmtree(SVC_VENV, ignore_errors=True)
    if not venv_python(SVC_VENV).exists():
        run(uv_cmd(uv, "venv", "--python", PYTHON_FOR_SVC, str(SVC_VENV)))
    py = str(venv_python(SVC_VENV))

    def pip(*args: str, index: str | None = None) -> None:
        uv_pip_install(uv, py, *args, index=index)

    # uv venv 默认不含 setuptools/pip，而 librosa 运行时要 `from pkg_resources import ...`
    # （pkg_resources 属于 setuptools），缺失会导致推理一加载 librosa 就 ModuleNotFoundError。
    # 注意：setuptools 81+ 已移除 pkg_resources，必须钉 <81 才仍带该模块。
    pip("setuptools<81", "wheel")
    # 先装 torch（决定 CUDA/CPU），再装仓库其余依赖。
    # 钉 <2.6：torch>=2.6 起 torch.load 默认 weights_only=True，会拒绝反序列化
    # so-vits checkpoint 里的非张量对象（argparse.Namespace / numpy 标量），导致
    # 加载模型时报 "Weights only load failed"。2.5.1 是支持 py3.9 且仍默认
    # weights_only=False 的稳定版，避免新装用户拉到不兼容的最新版。
    pip("torch==2.5.1", "torchaudio==2.5.1", index=TORCH_CUDA_INDEX if use_gpu else TORCH_CPU_INDEX)
    # 优先 requirements_win.txt（仓库为 Windows 提供的更易装版本）
    req_win = SOVITS_DIR / "requirements_win.txt"
    req = SOVITS_DIR / "requirements.txt"
    req_file = req_win if req_win.exists() else req
    if req_file.exists():
        filtered = _filter_requirements(req_file)
        pip("-r", str(filtered))
    # so-vits-svc 的 vdecoder 代码里 `import matplotlib`，但官方 requirements 漏列了它，
    # 不补会在推理加载模型时报 No module named 'matplotlib'。钉 3.7.5 以兼容 numpy 1.22 / py3.9，
    # 避免最新 matplotlib(3.9+) 强行把 numpy 升到 >=1.23 而破坏 so-vits-svc 依赖。
        pip("matplotlib==3.7.5")
    else:
        print(c("r", "    未找到 requirements，跳过依赖安装（请检查仓库）"))
    print(c("g", "推理环境就绪"))


def _filter_requirements(src: Path) -> Path:
    """剔除推理用不到/装不上的包（见 REQ_DENYLIST），生成精简 requirements。"""
    out = src.parent / "requirements_xb.txt"
    kept: list[str] = []
    for raw in src.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            kept.append(raw)
            continue
        name = re.split(r"[<>=!~;\[\s]", line, maxsplit=1)[0].strip().lower()
        name = name.replace("_", "-")
        if name in REQ_DENYLIST:
            print(c("y", f"    跳过不需要的包：{line}"))
            continue
        kept.append(raw)
    out.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return out


def step_models(uv: str) -> None:
    hr("5/5 底模 + UVR 模型（自带优先，缺失才联网下载）")
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
    "app": lambda uv, gpu: step_app(uv),
    "web": lambda uv, gpu: step_web(),
    "uvr": lambda uv, gpu: step_uvr(uv, gpu),
    "svc": lambda uv, gpu: step_svc(uv, gpu),
    "models": lambda uv, gpu: step_models(uv),
}
ORDER = ["app", "web", "uvr", "svc", "models"]


def main() -> int:
    p = argparse.ArgumentParser(description="XB-SVCB 一键安装器")
    p.add_argument(
        "--root",
        default=None,
        help="安装根目录（引擎/虚拟环境/模型都装到此处）；默认取脚本上级目录",
    )
    p.add_argument("--cpu", action="store_true", help="强制安装 CPU 版")
    p.add_argument("--gpu", action="store_true", help="强制安装 CUDA 版")
    p.add_argument(
        "--only",
        choices=ORDER,
        nargs="+",
        help="只执行指定步骤（可多选）：app web uvr svc models",
    )
    for s in ORDER:
        p.add_argument(f"--skip-{s}", action="store_true", help=f"跳过 {s} 步骤")
    args = p.parse_args()

    if args.root:
        _derive_paths(Path(args.root).expanduser().resolve())

    hr("XB-SVCB 安装器")
    print(f"安装根目录: {ROOT}")

    if args.gpu and args.cpu:
        print(c("r", "--gpu 与 --cpu 不能同时使用"))
        return 2
    use_gpu = True if args.gpu else False if args.cpu else detect_gpu()
    print(f"安装模式: {c('g', 'CUDA(GPU)') if use_gpu else c('y', 'CPU')}")
    if use_gpu and not args.gpu:
        print("（检测到 NVIDIA 显卡，自动选择 CUDA；如需 CPU 请加 --cpu）")

    uv = ensure_uv()
    print(f"uv: {uv}")

    selected = args.only if args.only else [s for s in ORDER if not getattr(args, f"skip_{s}")]

    results: list[tuple[str, str]] = []
    for s in ORDER:
        if s not in selected:
            results.append((s, "skip"))
            continue
        try:
            STEPS[s](uv, use_gpu)
            results.append((s, "ok"))
        except Exception as exc:  # noqa: BLE001 - 单步失败不阻断其余步骤
            print(c("r", f"[{s}] 失败: {exc}"))
            results.append((s, "fail"))

    hr("安装结果汇总")
    label = {"ok": c("g", "成功"), "fail": c("r", "失败"), "skip": c("y", "跳过")}
    for s, st in results:
        print(f"  {s:<8} {label[st]}")

    if any(st == "fail" for _, st in results):
        print(c("y", "\n有步骤失败。可单独重试，例如: python install/install.py --only svc"))
        print(c("y", "失败项的手动补救方式见 install/README 或项目根 README。"))
        return 1

    hr("全部完成 ✅")
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
