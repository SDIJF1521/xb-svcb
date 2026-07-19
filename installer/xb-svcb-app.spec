# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包规格：把 XB-SVCB 桌面壳（app/main.py）打成单个 onedir 应用。

产物：dist/XB-SVCB/XB-SVCB.exe（+ _internal/）。其中：
  - 前端 web/dist 内置进 _internal/web/dist，应用自带界面、无需外置；
  - worker 脚本（svc/f0/uvr/rvc/seedvc/ddsp/hub）以「真实磁盘文件」形式放进
    _internal/infrastructure，供外部 .venv-* 的 Python 以子进程读取执行；
  - 重负载 AI 环境（torch/so-vits-svc/RVC/audio-separator/SeedVC/DDSP-SVC）不进 exe，由安装器在
    安装目录旁单独搭建（engines/.venv-svc/.venv-rvc/.venv-uvr/.venv-seedvc/.venv-ddsp/models）。
编译：在仓库根执行  pyinstaller installer/xb-svcb-app.spec  （用 app/.venv 的 Python）。
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent          # 仓库根（spec 位于 installer/）
APP = ROOT / "app"

# 应用图标（嵌入 exe；快捷方式会继承）
ICON = ROOT / "assets" / "icon" / "xb-svcb.ico"
ICON_PATH = str(ICON) if ICON.exists() else None
VERSION_INFO = str(ROOT / "installer" / "xb-svcb-version.txt")

# 调试开关：设环境变量 XB_BUILD_CONSOLE=1 时构建带控制台版本以便看报错。
XB_CONSOLE = os.environ.get("XB_BUILD_CONSOLE") == "1"

datas = []
binaries = []
hiddenimports = [
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "clr",
    # 音乐资源服务的 httpx 在函数内惰性 import，PyInstaller 静态分析会漏掉，
    # 这里显式声明 httpx 及其传递依赖，确保打包进 exe（否则在线曲库报缺依赖）。
    "httpx",
    "httpcore",
    "h11",
    "anyio",
    "sniffio",
    "idna",
    "certifi",
]

# pywebview（Windows EdgeChromium 后端）+ 其 http server 依赖一并收集；
# httpx / certifi 一并 collect_all，确保模块与 certifi 的 CA 证书数据都打进 exe。
for pkg in ("webview", "clr_loader", "pythonnet", "bottle", "proxy_tools", "httpx", "certifi"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# 内置前端构建产物
datas += [(str(APP.parent / "web" / "dist"), "web/dist")]

# worker 脚本：必须是磁盘上的真实 .py，供外部环境的 Python 读取执行
for w in ("inference_device.py", "svc_worker.py", "f0_worker.py", "uvr_worker.py", "hub_worker.py", "rvc_worker.py", "seedvc_worker.py", "ddsp_worker.py"):
    datas += [(str(APP / "infrastructure" / w), "infrastructure")]


a = Analysis(
    [str(APP / "main.py")],
    pathex=[str(APP)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["torch", "librosa", "numpy", "audio_separator", "fairseq"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="XB-SVCB",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=XB_CONSOLE,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_PATH,
    version=VERSION_INFO,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="XB-SVCB",
)
