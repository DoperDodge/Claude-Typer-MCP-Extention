"""
Window Manager — Detect and focus application windows on Windows.

Uses pygetwindow for cross-platform-ish window enumeration,
with win32gui fallback for more reliable focusing on Windows.
"""

import time
from typing import Optional

try:
    import pygetwindow as gw
except ImportError:
    gw = None

try:
    import win32gui
    import win32con
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False


def get_active_window() -> dict:
    """Return info about the currently focused window."""
    if HAS_WIN32:
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd)
        return {"title": title, "hwnd": hwnd}

    if gw is not None:
        try:
            win = gw.getActiveWindow()
            if win:
                return {"title": win.title, "hwnd": getattr(win, '_hWnd', None)}
        except Exception:
            pass

    return {"title": "unknown", "hwnd": None}


def focus_window(title: str) -> dict:
    """
    Find and focus a window whose title contains the given string (case-insensitive).
    Returns info about the focused window, or an error if not found.
    """
    title_lower = title.lower()

    # Try win32gui first (more reliable on Windows)
    if HAS_WIN32:
        result = _focus_win32(title_lower)
        if result:
            return result

    # Fallback to pygetwindow
    if gw is not None:
        result = _focus_pygetwindow(title_lower)
        if result:
            return result

    return {"success": False, "error": f"No window found matching '{title}'"}


def list_windows() -> list[dict]:
    """List all visible windows with titles."""
    windows = []

    if HAS_WIN32:
        def _enum_callback(hwnd, results):
            if win32gui.IsWindowVisible(hwnd):
                wt = win32gui.GetWindowText(hwnd)
                if wt.strip():
                    results.append({"title": wt, "hwnd": hwnd})
        win32gui.EnumWindows(_enum_callback, windows)
        return windows

    if gw is not None:
        for win in gw.getAllWindows():
            if win.title.strip() and win.visible:
                windows.append({"title": win.title, "hwnd": getattr(win, '_hWnd', None)})
        return windows

    return []


# ------------------------------------------------------------------ #
#  Internal helpers                                                    #
# ------------------------------------------------------------------ #

def _focus_win32(title_lower: str) -> Optional[dict]:
    """Focus a window using win32gui."""
    matches = []

    def _enum(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            wt = win32gui.GetWindowText(hwnd)
            if title_lower in wt.lower():
                matches.append((hwnd, wt))

    win32gui.EnumWindows(_enum, None)

    if not matches:
        return None

    hwnd, wt = matches[0]  # First match
    try:
        # Restore if minimized
        placement = win32gui.GetWindowPlacement(hwnd)
        if placement[1] == win32con.SW_SHOWMINIMIZED:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.15)  # Let Windows finish the focus switch
        return {"success": True, "title": wt, "hwnd": hwnd}
    except Exception as e:
        return {"success": False, "error": str(e), "title": wt}


def _focus_pygetwindow(title_lower: str) -> Optional[dict]:
    """Focus a window using pygetwindow."""
    for win in gw.getAllWindows():
        if title_lower in win.title.lower() and win.title.strip():
            try:
                win.activate()
                time.sleep(0.15)
                return {"success": True, "title": win.title}
            except Exception as e:
                return {"success": False, "error": str(e), "title": win.title}
    return None
