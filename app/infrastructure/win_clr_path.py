"""Windows 非 ASCII 安装路径下的 pythonnet / pywebview 兼容处理。

.NET Framework 的 ``Assembly.LoadFrom`` 会把某些非 ASCII 路径下的程序集误判为
「来自网络位置」，导致 pythonnet 报::

    Failed to resolve Python.Runtime.Loader.Initialize

clr_loader / pythonnet 上游已有同类报告（pythonnet#2141、clr-loader#59）。
这里在启动 pywebview 之前，把 pythonnet 运行时和 pywebview 自带的 .NET 程序集
镜像到纯 ASCII 的应用缓存目录，并让加载器改从镜像读取；项目本身可以继续放在
中文目录里。路径本来就是 ASCII 时不做任何处理。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_MIRROR_NAME = "clr-mirror"


def _is_ascii(value: str) -> bool:
    return bool(value) and all(ord(char) < 128 for char in value)


def _short_ascii_path(path: Path) -> Path | None:
    """把已存在的路径转换为 8.3 短路径；用于用户名本身含中文的情况。"""
    try:
        import ctypes

        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, 32768):
            short = buffer.value
            if short and _is_ascii(short):
                return Path(short)
    except Exception:  # noqa: BLE001 - 短路径只是最佳努力
        return None
    return None


def _ascii_mirror_root() -> Path | None:
    override = os.environ.get("XB_CLR_MIRROR", "").strip()
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override))
    for key in ("LOCALAPPDATA", "TEMP", "TMP"):
        raw = os.environ.get(key, "").strip()
        if raw:
            candidates.append(Path(raw) / "XB-SVCB" / _MIRROR_NAME)
    candidates.append(Path.home() / "AppData" / "Local" / "XB-SVCB" / _MIRROR_NAME)

    for candidate in candidates:
        resolved = candidate
        if not _is_ascii(str(resolved)):
            # 找到已存在的祖先目录，先转短路径，再拼回相对部分。
            for parent in (resolved, *resolved.parents):
                if not parent.exists():
                    continue
                short = _short_ascii_path(parent)
                if short is None:
                    break
                relative = resolved.relative_to(parent)
                resolved = short / relative
                break
        if not _is_ascii(str(resolved)):
            continue
        try:
            resolved.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        if os.access(resolved, os.W_OK):
            return resolved
    return None


def _sync_tree(source: Path, target: Path, stamp_name: str) -> bool:
    if not source.is_dir():
        return False
    stamp_file = source / stamp_name
    try:
        stat = stamp_file.stat()
        stamp = f"{source}|{stat.st_size}|{stat.st_mtime_ns}"
    except OSError:
        return False
    marker = target / ".xb-mirror-stamp"
    try:
        if marker.is_file() and marker.read_text(encoding="utf-8") == stamp:
            return True
    except OSError:
        pass
    try:
        shutil.copytree(source, target, dirs_exist_ok=True)
        marker.write_text(stamp, encoding="utf-8")
    except OSError:
        # 缓存已经存在但当前进程无法刷新（例如只读/被占用）时，仍可继续使用
        # 旧镜像；比直接退回中文路径加载失败要好。
        return (target / stamp_name).is_file()
    return True


def install() -> bool:
    """在导入 pywebview 后端前调用；返回是否安装了路径兼容补丁。"""
    if os.name != "nt":
        return False
    runtime = os.environ.get("PYTHONNET_RUNTIME", "").strip().lower()
    if runtime and runtime != "netfx":
        # 用户显式选择了 CoreCLR / Mono 时不要干扰其配置。
        return False

    try:
        import clr_loader.netfx as netfx
        import pythonnet
        import webview
        import webview.util as webview_util
    except Exception:  # noqa: BLE001 - 非桌面环境或依赖缺失时保持原状
        return False

    pythonnet_runtime = Path(pythonnet.__file__).resolve().parent / "runtime"
    webview_lib = Path(webview.__file__).resolve().parent / "lib"
    if not pythonnet_runtime.is_dir() or not webview_lib.is_dir():
        return False
    if _is_ascii(str(pythonnet_runtime)) and _is_ascii(str(webview_lib)):
        return False

    mirror = _ascii_mirror_root()
    if mirror is None:
        return False
    netfx_mirror = mirror / "pythonnet-runtime"
    webview_mirror = mirror / "webview-lib"
    if not _sync_tree(pythonnet_runtime, netfx_mirror, "Python.Runtime.dll"):
        return False
    if not _sync_tree(webview_lib, webview_mirror, "Microsoft.Web.WebView2.Core.dll"):
        return False

    original_get_callable = netfx.NetFx._get_callable

    def patched_get_callable(self, assembly_path, typename: str, function: str):
        path = Path(assembly_path)
        if path.name == "Python.Runtime.dll" and not _is_ascii(str(path)):
            mirrored = netfx_mirror / path.name
            if mirrored.is_file():
                path = mirrored
        return original_get_callable(self, path, typename, function)

    netfx.NetFx._get_callable = patched_get_callable

    original_interop = webview_util.interop_dll_path

    def patched_interop(dll_name: str) -> str:
        raw = Path(original_interop(dll_name))
        try:
            relative = raw.relative_to(webview_lib)
        except ValueError:
            return str(raw)
        mirrored = webview_mirror / relative
        return str(mirrored) if mirrored.exists() else str(raw)

    webview_util.interop_dll_path = patched_interop
    return True
