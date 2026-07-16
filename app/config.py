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
APP_VERSION = "0.0.20"
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


def _existing_env_path(name: str) -> Path | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.exists() else None


def _venv_python(venv_dir: Path) -> Path:
    """返回 venv 内 Python 解释器路径（兼容 Windows / *nix）。"""
    win = venv_dir / "Scripts" / "python.exe"
    nix = venv_dir / "bin" / "python"
    return win if os.name == "nt" else nix


# 项目内引擎与环境的约定位置（由安装器创建）
ENGINES_DIR = ROOT_DIR / "engines"
SOVITS_REPO_DIR = ENGINES_DIR / "so-vits-svc"
SEEDVC_REPO_DIR = ENGINES_DIR / "seed-vc"
DDSP_REPO_DIR = ENGINES_DIR / "ddsp-svc"
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


# ---- RVC 推理引擎（rvc-python）----
# 在独立的 .venv-rvc 中运行 rvc-python（依赖与 so-vits-svc 环境隔离，避免 torch/numpy 冲突）。
# 缺失时 RvcEngine 自动降级为占位音频，整条链路仍可跑通。
RVC_VENV_DIR = ROOT_DIR / ".venv-rvc"


def _detect_rvc_python() -> Path | None:
    env = os.environ.get("XB_RVC_PYTHON")
    if env:
        return Path(env)
    return _first_existing([_venv_python(RVC_VENV_DIR)])


# 运行 RVC 推理的 Python 解释器（需装有 rvc-python + torch）
RVC_PYTHON = _detect_rvc_python()
# RVC 推理子进程脚本（由 .venv-rvc 的 Python 读取，需为磁盘真实文件）
RVC_WORKER = BUNDLE_DIR / "infrastructure" / "rvc_worker.py"


def rvc_engine_ready() -> bool:
    """RVC 推理环境是否齐备：worker 存在、解释器存在。"""
    return bool(RVC_WORKER.exists() and RVC_PYTHON and RVC_PYTHON.exists())


# ---- SeedVC 推理引擎（Seed-VC）----
# 在独立 .venv-seedvc 中运行官方 Seed-VC inference.py。SeedVC 是 zero-shot /
# few-shot 风格，除 checkpoint + config 外，还需要一个目标音色参考音频。
SEEDVC_VENV_DIR = ROOT_DIR / ".venv-seedvc"


def _detect_seedvc_repo() -> Path | None:
    env = os.environ.get("XB_SEEDVC_REPO")
    if env:
        return Path(env)
    return _first_existing([SEEDVC_REPO_DIR])


def _detect_seedvc_python() -> Path | None:
    env = os.environ.get("XB_SEEDVC_PYTHON")
    if env:
        return Path(env)
    return _first_existing([_venv_python(SEEDVC_VENV_DIR)])


SEEDVC_REPO = _detect_seedvc_repo()
SEEDVC_PYTHON = _detect_seedvc_python()
SEEDVC_WORKER = BUNDLE_DIR / "infrastructure" / "seedvc_worker.py"


def seedvc_engine_ready() -> bool:
    """SeedVC 推理环境是否齐备：repo、worker、解释器都存在。"""
    return bool(
        SEEDVC_REPO
        and SEEDVC_REPO.exists()
        and (SEEDVC_REPO / "inference.py").exists()
        and SEEDVC_WORKER.exists()
        and SEEDVC_PYTHON
        and SEEDVC_PYTHON.exists()
    )


# ---- DDSP-SVC 推理引擎（yxlllc/DDSP-SVC）----
DDSP_VENV_DIR = ROOT_DIR / ".venv-ddsp"


def _detect_ddsp_repo() -> Path | None:
    env = os.environ.get("XB_DDSP_REPO")
    if env:
        return Path(env)
    return _first_existing([DDSP_REPO_DIR])


def _detect_ddsp_python() -> Path | None:
    env = os.environ.get("XB_DDSP_PYTHON")
    if env:
        return Path(env)
    return _first_existing([_venv_python(DDSP_VENV_DIR)])


DDSP_REPO = _detect_ddsp_repo()
DDSP_PYTHON = _detect_ddsp_python()
DDSP_WORKER = BUNDLE_DIR / "infrastructure" / "ddsp_worker.py"


def ddsp_engine_ready() -> bool:
    """DDSP-SVC 仓库、worker 与隔离环境是否齐备。"""
    return bool(
        DDSP_REPO
        and DDSP_REPO.exists()
        and (DDSP_REPO / "main_reflow.py").exists()
        and DDSP_WORKER.exists()
        and DDSP_PYTHON
        and DDSP_PYTHON.exists()
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
    env = _existing_env_path("XB_UVR_PYTHON")
    candidates = [env] if env else []
    candidates.append(_venv_python(UVR_VENV_DIR))
    return _first_existing(candidates)


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


def uvr_environment_ready() -> bool:
    """UVR 运行环境是否已安装：解释器与 worker 可用。"""
    return bool(
        UVR_PYTHON
        and UVR_PYTHON.exists()
        and UVR_WORKER.exists()
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
    if not UVR_PYTHON or not UVR_PYTHON.exists():
        return "未找到 .venv-uvr"
    if not UVR_WORKER.exists():
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
    env = os.environ.get("XB_HUB_PYTHON")
    if env:
        return Path(env)
    return _first_existing([_venv_python(HUB_VENV_DIR)])


# 运行 modelscope 上传的 Python 解释器（需装有 modelscope SDK）
HUB_PYTHON = _detect_hub_python()
# 子进程内执行的上传 worker 脚本（由 .venv-hub 的 Python 读取，需为磁盘真实文件）
HUB_WORKER = BUNDLE_DIR / "infrastructure" / "hub_worker.py"


def modelhub_upload_ready() -> bool:
    """模型上传组件是否就绪（.venv-hub 解释器 + worker 脚本都在）。

    仅「上传」需要；搜索与下载不依赖该组件。
    """
    return bool(HUB_PYTHON and HUB_PYTHON.exists() and HUB_WORKER.exists())

# 用户数据目录（模型 / 作品 / 缓存 / 配置均保存在本地）
# 优先级：
# 1. 环境变量 XB_DATA_DIR / XB_SVCB_DATA_DIR / XB_SB_SVCB_DATA_DIR / XB_XVCB_DATA_DIR（可用于自定义存储盘）
# 2. 安装器 / 应用内迁移写入的 data_home.json
# 3. 默认目录 .sb-svcb；旧版本 .xb_xvcb / .sv-xvcb / .xb-svcb / .xb_svcb 仅用于兼容升级
# 4. 新安装时默认落在安装目录下，避免把数据写到系统盘 C 盘

DATA_DIR_NAME = ".sb-svcb"
DATA_HOME_FILE = BASE_DIR / "data_home.json"
USER_DATA_HOME_FILE = (
    Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    / APP_NAME
    / "data_home.json"
)
DATA_HOME_FILES = (USER_DATA_HOME_FILE, DATA_HOME_FILE)
DATA_MARKER_FILE = ".sb-svcb_data"
DATA_MIGRATION_MARKER = ".sb-svcb_migration_source"
LEGACY_DATA_MARKER_FILES = (".xb_xvcb_data", ".sv-xvcb_data", ".xb_svcb_data")
LEGACY_DATA_DIR_NAMES = (".xb_xvcb", ".sv-xvcb", ".xb-svcb", ".xb_svcb")
LEGACY_DATA_MIGRATION_MARKERS = (
    ".xb_xvcb_migration_source",
    ".sv-xvcb_migration_source",
    ".xb_svcb_migration_source",
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
    global EDITOR_CACHE_DIR, EDITOR_PROJECTS_DB, THEME_MEDIA_DIR

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


def switch_data_dir(data_dir: Path) -> None:
    """迁移完成后让当前会话立刻使用新的用户数据目录。"""
    _apply_data_dir(data_dir)


_apply_data_dir(_resolve_data_dir())

# ---- 在线音乐资源 API（妖狐 API）----
# 用户需在「资源获取」页填写自己的 API Key（控制台->密钥管理）。
# 接口形如 https://api.yaohud.cn/api/music/{source}，source 支持多个曲库。
MUSIC_API_BASE = "https://api.yaohud.cn/api/music"
# 可选曲库（source -> 显示名）。wy=网易云，qq=QQ音乐。
MUSIC_SOURCES: dict[str, str] = {
    "wy": "网易云音乐",
    "qq": "QQ音乐",
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
# ModelScope 接口限流（客户端侧保守值）
MODELSCOPE_QPS = 5
# settings.json 中保存 ModelScope 访问令牌的键名
MODELSCOPE_TOKEN_SETTING = "modelscope_token"

# 支持的音频与模型扩展名
AUDIO_EXTS = (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac")
MODEL_EXTS = (".pth", ".onnx", ".pt", ".ckpt")
