"""全局配置：应用元信息与数据目录。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

APP_NAME = "XB-SVCB"
APP_TITLE = "XB-SVCB"
APP_BG = "#05060d"

# 项目根目录（app/ 的上一级）
ROOT_DIR = Path(__file__).resolve().parent.parent

# 前端构建产物
DIST_INDEX = ROOT_DIR / "web" / "dist" / "index.html"


# ---- so-vits-svc 4.1 推理引擎 ----
# 复用用户本地已配置好的 so-vits-svc 仓库与其 conda 环境（无需在本项目内重装依赖）。
# 均可通过环境变量覆盖，未配置时回退到下方默认候选路径，找不到则推理降级为占位音频。


def _first_existing(candidates: list[Path]) -> Path | None:
    for c in candidates:
        if c.exists():
            return c
    return None


def _detect_sovits_repo() -> Path | None:
    env = os.environ.get("XB_SOVITS_REPO")
    if env:
        return Path(env)
    return _first_existing(
        [
            Path(r"C:\Users\Lkpap\Desktop\AI唱歌\nxd\so-vits-svc-4.1-Stable"),
            ROOT_DIR / "engines" / "so-vits-svc",
        ]
    )


def _detect_svc_python() -> Path | None:
    env = os.environ.get("XB_SVC_PYTHON")
    if env:
        return Path(env)
    found = _first_existing(
        [
            Path(r"C:\anaconda3\envs\svc\python.exe"),
            Path.home() / "anaconda3" / "envs" / "svc" / "python.exe",
            Path.home() / "miniconda3" / "envs" / "svc" / "python.exe",
        ]
    )
    if found:
        return found
    which = shutil.which("python")
    return Path(which) if which else None


# 推理仓库根目录（含 inference/infer_tool.py 与 pretrain/）
SOVITS_REPO = _detect_sovits_repo()
# 运行推理用的 Python 解释器（需装有 torch + fairseq 等 so-vits-svc 依赖）
SVC_PYTHON = _detect_svc_python()
# 子进程内执行的 worker 脚本
SVC_WORKER = Path(__file__).resolve().parent / "infrastructure" / "svc_worker.py"
# F0 提取 worker（同样在 so-vits-svc 环境中运行）
F0_WORKER = Path(__file__).resolve().parent / "infrastructure" / "f0_worker.py"


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
    return _first_existing(
        [
            ROOT_DIR / ".venv-uvr" / "Scripts" / "python.exe",
            ROOT_DIR / ".venv-uvr" / "bin" / "python",
        ]
    )


def _detect_uvr_model_dir() -> Path | None:
    env = os.environ.get("XB_UVR_MODEL_DIR")
    if env:
        return Path(env)
    return _first_existing(
        [
            # 优先 VR 模型目录（含 5_HP-Karaoke / DeEcho-DeReverb 等去混响模型）
            Path(r"C:\Ultimate Vocal Remover\models\VR_Models"),
            Path(r"C:\Ultimate Vocal Remover\models\MDX_Net_Models"),
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
# 子进程内执行的分离 worker 脚本
UVR_WORKER = Path(__file__).resolve().parent / "infrastructure" / "uvr_worker.py"


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

MODELS_DB = DATA_DIR / "models.json"
WORKS_DB = DATA_DIR / "works.json"
SETTINGS_DB = DATA_DIR / "settings.json"

# 支持的音频与模型扩展名
AUDIO_EXTS = (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac")
MODEL_EXTS = (".pth", ".onnx", ".pt", ".ckpt")
