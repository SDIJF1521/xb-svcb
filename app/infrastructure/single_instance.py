"""桌面端单实例守护与窗口置前。"""

from __future__ import annotations

import ctypes
import os
import socket
import threading
from collections.abc import Callable
from ctypes import wintypes


_ERROR_ALREADY_EXISTS = 183
_SW_RESTORE = 9
_SW_SHOW = 5


class SingleInstance:
    """Windows 单实例控制器。

    第一实例持有命名 Mutex，并启动本机 IPC 监听；后续实例检测到 Mutex 已存在时，
    发送 ``focus`` 消息给第一实例后退出。
    """

    def __init__(
        self,
        app_name: str,
        window_title: str,
        *,
        port: int = 49217,
    ) -> None:
        self.app_name = app_name
        self.window_title = window_title
        self.port = port
        self._mutex = None
        self._server: socket.socket | None = None

    def acquire(self) -> bool:
        if os.name != "nt":
            return True

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.GetLastError.restype = wintypes.DWORD

        self._mutex = kernel32.CreateMutexW(None, False, f"Local\\{self.app_name}-SingleInstance")
        if not self._mutex:
            return True
        return int(kernel32.GetLastError()) != _ERROR_ALREADY_EXISTS

    def notify_existing(self) -> bool:
        if os.name != "nt":
            return False
        ok = False
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=0.7) as sock:
                sock.sendall(b"focus\n")
                ok = True
        except OSError:
            ok = False
        return focus_window(self.window_title) or ok

    def start_listener(self, on_focus: Callable[[], None]) -> None:
        if os.name != "nt":
            return
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("127.0.0.1", self.port))
            server.listen(4)
            server.settimeout(0.5)
        except OSError:
            return
        self._server = server

        def run() -> None:
            while self._server is server:
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                with conn:
                    try:
                        data = conn.recv(64)
                    except OSError:
                        data = b""
                    if data.strip().lower().startswith(b"focus"):
                        on_focus()

        threading.Thread(target=run, name="xb-single-instance-ipc", daemon=True).start()

    def close(self) -> None:
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
            self._server = None
        if os.name == "nt" and self._mutex:
            try:
                ctypes.windll.kernel32.CloseHandle(self._mutex)
            except OSError:
                pass
            self._mutex = None


def focus_window(title: str) -> bool:
    """把标题为 ``title`` 的 Windows 窗口恢复并置前。"""
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.FindWindowW.restype = wintypes.HWND
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.BringWindowToTop.restype = wintypes.BOOL
        user32.IsIconic.argtypes = [wintypes.HWND]
        user32.IsIconic.restype = wintypes.BOOL
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, wintypes.LPDWORD]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        user32.AttachThreadInput.restype = wintypes.BOOL
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        hwnd = user32.FindWindowW(None, title)
        if not hwnd:
            return False

        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, _SW_RESTORE)
        else:
            user32.ShowWindow(hwnd, _SW_SHOW)

        current_thread = kernel32.GetCurrentThreadId()
        foreground = user32.GetForegroundWindow()
        foreground_thread = (
            user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
        )
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)
        attached_threads: list[int] = []
        if foreground_thread and foreground_thread != current_thread:
            if user32.AttachThreadInput(current_thread, foreground_thread, True):
                attached_threads.append(foreground_thread)
        if target_thread and target_thread != current_thread and target_thread not in attached_threads:
            if user32.AttachThreadInput(current_thread, target_thread, True):
                attached_threads.append(target_thread)
        try:
            user32.BringWindowToTop(hwnd)
            return bool(user32.SetForegroundWindow(hwnd))
        finally:
            for thread_id in attached_threads:
                user32.AttachThreadInput(current_thread, thread_id, False)
    except Exception:  # noqa: BLE001 - 置前失败不应阻断进程退出
        return False
