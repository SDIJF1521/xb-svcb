"""小型跨平台剪贴板助手。"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
from urllib.parse import unquote, urlparse


AUDIO_CLIPBOARD_EXTENSIONS = {
    ".aac",
    ".aif",
    ".aiff",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".wav",
    ".wma",
}


def copy_file_to_clipboard(path: Path) -> bool:
    """将文件引用复制到操作系统剪贴板。
    在 Windows 上，它使用 CF_HDROP，
    以便文件可以粘贴到资源管理器和许多音频应用程序中。
    其他平台则回退到复制路径文本的方式。
    """
    if not path.exists():
        return False
    if os.name == "nt":
        return _copy_windows_file(path) or copy_text_to_clipboard(str(path))
    return copy_text_to_clipboard(str(path))


def copy_text_to_clipboard(text: str) -> bool:
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return True
    except Exception:
        return False


def audio_files_from_clipboard(
    extensions: set[str] | frozenset[str] | None = None,
) -> list[Path]:
    """读取系统剪贴板里的音频文件引用。

    Windows 优先读取 CF_HDROP 文件列表；如果没有文件列表，
    再回退到文本路径 / file:// URI。其他平台使用文本回退。
    """
    allowed = {ext.lower() for ext in (extensions or AUDIO_CLIPBOARD_EXTENSIONS)}
    candidates: list[Path] = []
    if os.name == "nt":
        candidates.extend(_read_windows_file_clipboard())
        if not candidates:
            candidates.extend(_paths_from_clipboard_text(_read_windows_text_clipboard()))
    else:
        candidates.extend(_paths_from_clipboard_text(read_text_from_clipboard()))

    paths: list[Path] = []
    seen: set[str] = set()
    for item in candidates:
        try:
            resolved = item.expanduser().resolve()
        except OSError:
            continue
        key = str(resolved).casefold() if os.name == "nt" else str(resolved)
        if key in seen:
            continue
        if not resolved.is_file():
            continue
        if allowed and resolved.suffix.lower() not in allowed:
            continue
        seen.add(key)
        paths.append(resolved)
    return paths


def read_text_from_clipboard() -> str:
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        text = root.clipboard_get()
        root.destroy()
        return str(text or "")
    except Exception:
        return ""


def _copy_windows_file(path: Path) -> bool:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    GMEM_MOVEABLE = 0x0002
    CF_HDROP = 15
    CF_UNICODETEXT = 13

    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_bool
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.restype = ctypes.c_void_p
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool
    user32.EmptyClipboard.restype = ctypes.c_bool
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.CloseClipboard.restype = ctypes.c_bool

    absolute = str(path.resolve())
    hdrop = _global_mem_from_bytes(_dropfiles_payload(absolute), GMEM_MOVEABLE)
    htext = _global_mem_from_bytes((absolute + "\0").encode("utf-16le"), GMEM_MOVEABLE)
    if not hdrop and not htext:
        return False

    opened = bool(user32.OpenClipboard(None))
    if not opened:
        if hdrop:
            kernel32.GlobalFree(hdrop)
        if htext:
            kernel32.GlobalFree(htext)
        return False

    ok = False
    try:
        user32.EmptyClipboard()
        if hdrop and user32.SetClipboardData(CF_HDROP, hdrop):
            ok = True
            hdrop = None
        if htext and user32.SetClipboardData(CF_UNICODETEXT, htext):
            ok = True
            htext = None
    finally:
        user32.CloseClipboard()
        if hdrop:
            kernel32.GlobalFree(hdrop)
        if htext:
            kernel32.GlobalFree(htext)
    return ok


def _read_windows_file_clipboard() -> list[Path]:
    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32

    CF_HDROP = 15
    DRAG_QUERY_FILE_COUNT = 0xFFFFFFFF

    user32.IsClipboardFormatAvailable.argtypes = [ctypes.c_uint]
    user32.IsClipboardFormatAvailable.restype = ctypes.c_bool
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.CloseClipboard.restype = ctypes.c_bool
    shell32.DragQueryFileW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_wchar_p,
        ctypes.c_uint,
    ]
    shell32.DragQueryFileW.restype = ctypes.c_uint

    if not user32.IsClipboardFormatAvailable(CF_HDROP):
        return []
    if not user32.OpenClipboard(None):
        return []
    try:
        hdrop = user32.GetClipboardData(CF_HDROP)
        if not hdrop:
            return []
        count = shell32.DragQueryFileW(hdrop, DRAG_QUERY_FILE_COUNT, None, 0)
        paths: list[Path] = []
        for index in range(count):
            length = shell32.DragQueryFileW(hdrop, index, None, 0)
            if length <= 0:
                continue
            buffer = ctypes.create_unicode_buffer(length + 1)
            shell32.DragQueryFileW(hdrop, index, buffer, length + 1)
            if buffer.value:
                paths.append(Path(buffer.value))
        return paths
    finally:
        user32.CloseClipboard()


def _read_windows_text_clipboard() -> str:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    CF_UNICODETEXT = 13

    user32.IsClipboardFormatAvailable.argtypes = [ctypes.c_uint]
    user32.IsClipboardFormatAvailable.restype = ctypes.c_bool
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.CloseClipboard.restype = ctypes.c_bool
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_bool

    if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
        return ""
    if not user32.OpenClipboard(None):
        return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        locked = kernel32.GlobalLock(handle)
        if not locked:
            return ""
        try:
            return ctypes.wstring_at(locked)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def _paths_from_clipboard_text(text: str) -> list[Path]:
    paths: list[Path] = []
    for raw in str(text or "").replace("\r", "\n").split("\n"):
        item = raw.strip().strip('"').strip("'")
        if not item:
            continue
        parsed = urlparse(item)
        if parsed.scheme == "file":
            item = unquote(parsed.path)
            if parsed.netloc:
                item = f"//{parsed.netloc}{item}"
            if os.name == "nt" and item.startswith("/") and len(item) > 2 and item[2] == ":":
                item = item[1:]
        paths.append(Path(item))
    return paths


def _dropfiles_payload(path: str) -> bytes:
    # DROPFILES: DWORD pFiles, POINT x/y, BOOL fNC, BOOL fWide
    header = (
        (20).to_bytes(4, "little")
        + (0).to_bytes(4, "little", signed=True)
        + (0).to_bytes(4, "little", signed=True)
        + (0).to_bytes(4, "little")
        + (1).to_bytes(4, "little")
    )
    return header + (path + "\0\0").encode("utf-16le")


def _global_mem_from_bytes(data: bytes, flags: int) -> int | None:
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GlobalAlloc(flags, len(data))
    if not handle:
        return None
    locked = kernel32.GlobalLock(handle)
    if not locked:
        kernel32.GlobalFree(handle)
        return None
    ctypes.memmove(locked, data, len(data))
    kernel32.GlobalUnlock(handle)
    return handle
