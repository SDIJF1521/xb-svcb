"""全局配置：应用元信息与数据目录。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

APP_NAME = "XB-SVCB"
APP_TITLE = "XB-SVCB"
APP_VERSION = "0.0.3"
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
#              engines/.venv-svc/.venv-uvr/models）；源码运行时为项目根。
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


def _venv_python(venv_dir: Path) -> Path:
    """返回 venv 内 Python 解释器路径（兼容 Windows / *nix）。"""
    win = venv_dir / "Scripts" / "python.exe"
    nix = venv_dir / "bin" / "python"
    return win if os.name == "nt" else nix


# 项目内引擎与环境的约定位置（由安装器创建）
ENGINES_DIR = ROOT_DIR / "engines"
SOVITS_REPO_DIR = ENGINES_DIR / "so-vits-svc"
SVC_VENV_DIR = ROOT_DIR / ".venv-svc"
UVR_VENV_DIR = ROOT_DIR / ".venv-uvr"


def _detect_sovits_repo() -> Path | None:
    env = os.environ.get("XB_SOVITS_REPO")
    if env:
        return Path(env)
    return _first_existing([SOVITS_REPO_DIR])


def _detect_svc_python() -> Path | None:
    env = os.environ.get("XB_SVC_PYTHON")
    if env:
        return Path(env)
    # 优先项目内安装器创建的 .venv-svc；其次常见 conda 环境名 svc（开发便利）
    return _first_existing(
        [
            _venv_python(SVC_VENV_DIR),
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


def svc_engine_ready() -> bool:
    """推理环境是否齐备：仓库存在、worker 存在、解释器存在。"""
    return bool(
        SOVITS_REPO
        and SOVITS_REPO.exists()
        and (SOVITS_REPO / "inference" / "infer_tool.py").exists()
        and SVC_WORKER.exists()
        and SVC_PYTHON
        and SVC_PYTHON.exists()
    )


# ---- UVR 人声分离引擎（audio-separator + 复用本地 UVR 模型）----
# 在独立 venv 中运行 audio-separator，复用已安装的 Ultimate Vocal Remover 模型权重。


def _detect_uvr_python() -> Path | None:
    env = os.environ.get("XB_UVR_PYTHON")
    if env:
        return Path(env)
    return _first_existing([_venv_python(UVR_VENV_DIR)])


# UVR 模型默认下载/存放目录（安装器创建）
UVR_MODEL_DIR_DEFAULT = ROOT_DIR / "models" / "uvr"


def _detect_uvr_model_dir() -> Path | None:
    env = os.environ.get("XB_UVR_MODEL_DIR")
    if env:
        return Path(env)
    return _first_existing(
        [
            # 优先项目内安装器下载的 UVR 模型目录
            UVR_MODEL_DIR_DEFAULT,
            # 其次复用本机常见的 Ultimate Vocal Remover 安装目录（开发便利）
            Path(r"C:\Ultimate Vocal Remover\models\VR_Models"),
        ]
    )


# 运行 audio-separator 的 Python 解释器
UVR_PYTHON = _detect_uvr_python()
# UVR 模型目录（复用本地 Ultimate Vocal Remover 的模型权重；默认 VR_Models）
UVR_MODEL_DIR = _detect_uvr_model_dir()
# 人声/伴奏分离模型：5_HP-Karaoke-UVR（人声更干净、伴奏完整保留）
UVR_SEP_MODEL = os.environ.get("XB_UVR_SEP_MODEL", "5_HP-Karaoke-UVR.pth")
# 人声去混响/去回声模型：去掉混响后再送 SVC，可显著缓解"电音/机械音"
UVR_DEREVERB_MODEL = os.environ.get("XB_UVR_DEREVERB_MODEL", "UVR-DeEcho-DeReverb.pth")
# 兼容旧引用：默认分离模型
UVR_MODEL = UVR_SEP_MODEL
# 子进程内执行的分离 worker 脚本（由外部 venv 的 Python 读取，需为磁盘上的真实文件）
UVR_WORKER = BUNDLE_DIR / "infrastructure" / "uvr_worker.py"


def uvr_ready() -> bool:
    """人声分离环境是否齐备：venv 解释器、worker、模型目录与分离模型文件都在。"""
    return bool(
        UVR_PYTHON
        and UVR_PYTHON.exists()
        and UVR_WORKER.exists()
        and UVR_MODEL_DIR
        and UVR_MODEL_DIR.exists()
        and (UVR_MODEL_DIR / UVR_SEP_MODEL).exists()
    )


def uvr_dereverb_ready() -> bool:
    """去混响模型是否可用。"""
    return bool(UVR_MODEL_DIR and (UVR_MODEL_DIR / UVR_DEREVERB_MODEL).exists())

# 用户数据目录（模型 / 作品 / 缓存 / 配置均保存在本地）
DATA_DIR = Path.home() / ".xb-svcb"
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

# ---- 在线音乐资源 API（妖狐 API，网易云源）----
# 用户需在「资源获取」页填写自己的 API Key（控制台->密钥管理）。
MUSIC_API_URL = "https://api.yaohud.cn/api/music/wy"
# 接口限制 10 QPS，客户端侧统一限流，避免触发风控。
MUSIC_API_QPS = 10

# 支持的音频与模型扩展名
AUDIO_EXTS = (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac")
MODEL_EXTS = (".pth", ".onnx", ".pt", ".ckpt")
