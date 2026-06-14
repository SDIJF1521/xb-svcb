"""原生窗口标题栏 / 边框着色（Windows DWM）。

让 pywebview 的原生窗口边框、标题栏随前端主题切换。
依赖 Windows 11（build 22000+）的 DWM 属性：标题栏颜色 / 边框颜色 / 标题文字颜色。
在 Windows 10 上仅「沉浸式深色模式」生效，其余属性会被系统忽略（静默失败）。
非 Windows 平台为 no-op。
"""

from __future__ import annotations

import sys

# DWM window attributes
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20  # Win10 2004+
_DWMWA_BORDER_COLOR = 34             # Win11 22000+
_DWMWA_CAPTION_COLOR = 35            # Win11 22000+
_DWMWA_TEXT_COLOR = 36               # Win11 22000+


def _colorref(r: int, g: int, b: int) -> int:
    """打包成 COLORREF（0x00BBGGRR）。"""
    return (r & 0xFF) | ((g & 0xFF) << 8) | ((b & 0xFF) << 16)


# 与前端 App.vue 的两套主题保持一致
_THEMES: dict[str, dict[str, int]] = {
    "cyber": {
        "dark": 1,
        "caption": _colorref(0x05, 0x06, 0x0D),
        "text": _colorref(0xE6, 0xF5, 0xFF),
        "border": _colorref(0x00, 0xC8, 0xE6),
    },
    "anime": {
        "dark": 0,
        "caption": _colorref(0xFD, 0xF3, 0xFB),
        "text": _colorref(0x4A, 0x3A, 0x63),
        "border": _colorref(0xFF, 0x84, 0xBD),
    },
}


def apply(title: str, theme: str) -> bool:
    """按主题给标题为 ``title`` 的原生窗口着色。成功返回 True。"""
    if not sys.platform.startswith("win"):
        return False

    conf = _THEMES.get(theme, _THEMES["cyber"])
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        # 显式声明返回/参数类型，避免在 64 位上句柄被截断为 32 位
        user32.FindWindowW.restype = wintypes.HWND
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        hwnd = user32.FindWindowW(None, title)
        if not hwnd:
            return False

        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute.restype = ctypes.c_long
        dwm.DwmSetWindowAttribute.argtypes = [
            wintypes.HWND,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]

        def _set(attr: int, value: int) -> None:
            val = wintypes.DWORD(value)
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))

        _set(_DWMWA_USE_IMMERSIVE_DARK_MODE, conf["dark"])
        _set(_DWMWA_CAPTION_COLOR, conf["caption"])
        _set(_DWMWA_TEXT_COLOR, conf["text"])
        _set(_DWMWA_BORDER_COLOR, conf["border"])
        return True
    except Exception:  # noqa: BLE001 - 任意异常都不应影响主流程
        return False
