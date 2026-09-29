"""查找游戏 / 客户端窗口并取得客户区在屏幕上的物理像素坐标（Win32，只读）。"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from dataclasses import dataclass

GAME_CLASS = "RiotWindowClass"
GAME_TITLE = "League of Legends (TM) Client"
CLIENT_CLASS = "RCLIENT"

IS_WINDOWS = sys.platform == "win32"


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


def enable_dpi_awareness() -> None:
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _find(cls: str | None, title: str | None) -> int:
    if not IS_WINDOWS:
        return 0
    return ctypes.windll.user32.FindWindowW(cls, title) or 0


def find_game_window() -> int:
    return _find(GAME_CLASS, None) or _find(None, GAME_TITLE)


def find_client_window() -> int:
    return _find(CLIENT_CLASS, None)


def client_rect(hwnd: int) -> Rect | None:
    if not IS_WINDOWS or not hwnd:
        return None
    u = ctypes.windll.user32
    if u.IsIconic(hwnd) or not u.IsWindowVisible(hwnd):
        return None
    rc = wintypes.RECT()
    if not u.GetClientRect(hwnd, ctypes.byref(rc)):
        return None
    pt = wintypes.POINT(0, 0)
    u.ClientToScreen(hwnd, ctypes.byref(pt))
    w, h = rc.right - rc.left, rc.bottom - rc.top
    if w < 200 or h < 150:
        return None
    return Rect(pt.x, pt.y, w, h)


# 贴在客户端/游戏上的自己的悬浮小窗：点它时前台变成它，但画面上客户端还在，按客户端仍在前台算
_companions: set[int] = set()


def add_companion(hwnd: int) -> None:
    if hwnd:
        _companions.add(int(hwnd))


def is_foreground(hwnd: int) -> bool:
    if not IS_WINDOWS or not hwnd:
        return False
    fg = ctypes.windll.user32.GetForegroundWindow()
    return fg == hwnd or (fg in _companions and not ctypes.windll.user32.IsIconic(hwnd))


def exclude_from_capture(hwnd: int) -> None:
    """让自己的悬浮窗不出现在截图里，避免识别到自己画的字（Win10 2004+）。"""
    if os.environ.get("LOLHEX_DEBUG_CAPTURABLE"):  # 调试截图时让悬浮层可见
        return
    if IS_WINDOWS and hwnd:
        try:
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x11)  # WDA_EXCLUDEFROMCAPTURE
        except Exception:
            pass


def left_button_clicked() -> bool:
    """自上次调用以来左键是否按下过（GetAsyncKeyState 低位），只读输入状态。"""
    if not IS_WINDOWS:
        return False
    return bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x0001)


def cursor_pos() -> tuple[int, int]:
    if not IS_WINDOWS:
        return (0, 0)
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y
