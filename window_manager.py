"""
Window Manager — Detect and focus application windows on Windows.

Uses pygetwindow for cross-platform-ish window enumeration,
with win32gui fallback for more reliable focusing on Windows.
"""

import time
import logging
from typing import Optional

logger = logging.getLogger("claude-typer.window")

try:
    import pygetwindow as gw
    HAS_PYGETWINDOW = True
except ImportError:
    gw = None
    HAS_PYGETWINDOW = False
    logger.warning("pygetwindow not installed — window listing limited")

try:
    import win32gui
    import win32con
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False
    logger.info("win32gui not available — using pygetwindow fallback")


def get_active_window() -> dict:
    """Return info about the currently focused window."""
    if HAS_WIN32:
        try:
            hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd)
            return {"title": title, "hwnd": hwnd}
        except Exception as e:
            logger.error("win32gui.GetForegroundWindow failed: %s", e)

    if gw is not None:
        try:
            win = gw.getActiveWindow()
            if win:
                return {"title": win.title, "hwnd": getattr(win, '_hWnd', None)}
        except Exception as e:
            logger.error("pygetwindow.getActiveWindow failed: %s", e)

    return {"title": "unknown", "hwnd": None}


def verify_window_focused(expected_title: str) -> dict:
    """
    Check whether the currently focused window matches the expected title.
    Returns match status and the actual focused window info.
    Useful for confirming the right window will receive keystrokes.
    """
    current = get_active_window()
    current_title = current.get("title", "")

    if not expected_title:
        return {"matched": True, "current_window": current,
                "message": "No specific window expected"}

    matched = expected_title.lower() in current_title.lower()

    if matched:
        return {"matched": True, "current_window": current}
    else:
        return {
            "matched": False,
            "current_window": current,
            "expected": expected_title,
            "message": f"Expected '{expected_title}' but '{current_title}' is focused. "
                       f"Use focus_window_by_title() to switch, or type anyway if this is correct.",
        }


def focus_window(title: str) -> dict:
    """
    Find and focus a window whose title contains the given string (case-insensitive).
    Returns info about the focused window, or an error if not found.
    """
    if not title or not title.strip():
        return {"success": False, "error": "No window title specified"}

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

    # Neither library found a match — give a helpful error
    available = list_windows()
    window_titles = [w["title"] for w in available]
    suggestion = ""
    for wt in window_titles:
        if any(word in wt.lower() for word in title_lower.split()):
            suggestion = f" Did you mean '{wt}'?"
            break

    return {"success": False,
            "error": f"No window found matching '{title}'.{suggestion}",
            "available_count": len(available)}


def list_windows() -> list[dict]:
    """List all visible windows with titles."""
    windows = []

    if HAS_WIN32:
        def _enum_callback(hwnd, results):
            try:
                if win32gui.IsWindowVisible(hwnd):
                    wt = win32gui.GetWindowText(hwnd)
                    if wt.strip():
                        results.append({"title": wt, "hwnd": hwnd})
            except Exception:
                pass  # Skip windows we can't query
        try:
            win32gui.EnumWindows(_enum_callback, windows)
        except Exception as e:
            logger.error("EnumWindows failed: %s", e)
        return windows

    if gw is not None:
        try:
            for win in gw.getAllWindows():
                if win.title.strip() and win.visible:
                    windows.append({"title": win.title,
                                    "hwnd": getattr(win, '_hWnd', None)})
        except Exception as e:
            logger.error("getAllWindows failed: %s", e)
        return windows

    return []


def check_dependencies() -> dict:
    """Check window management library availability."""
    issues = []

    if not HAS_WIN32 and not HAS_PYGETWINDOW:
        issues.append("Neither win32gui nor pygetwindow installed — "
                       "window management unavailable")

    return {
        "healthy": len(issues) == 0,
        "win32gui": HAS_WIN32,
        "pygetwindow": HAS_PYGETWINDOW,
        "issues": issues,
    }


# ------------------------------------------------------------------ #
#  Internal helpers                                                    #
# ------------------------------------------------------------------ #

def _focus_win32(title_lower: str) -> Optional[dict]:
    """Focus a window using win32gui."""
    matches = []

    def _enum(hwnd, _):
        try:
            if win32gui.IsWindowVisible(hwnd):
                wt = win32gui.GetWindowText(hwnd)
                if title_lower in wt.lower():
                    matches.append((hwnd, wt))
        except Exception:
            pass

    try:
        win32gui.EnumWindows(_enum, None)
    except Exception as e:
        logger.error("EnumWindows failed during focus: %s", e)
        return None

    if not matches:
        return None

    hwnd, wt = matches[0]
    try:
        # Restore if minimized
        placement = win32gui.GetWindowPlacement(hwnd)
        if placement[1] == win32con.SW_SHOWMINIMIZED:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.15)
        logger.info("Focused window: %s (hwnd=%s)", wt, hwnd)
        return {"success": True, "title": wt, "hwnd": hwnd}
    except Exception as e:
        logger.error("SetForegroundWindow failed for '%s': %s", wt, e)
        return {"success": False, "error": str(e), "title": wt}


def _focus_pygetwindow(title_lower: str) -> Optional[dict]:
    """Focus a window using pygetwindow."""
    try:
        for win in gw.getAllWindows():
            if title_lower in win.title.lower() and win.title.strip():
                try:
                    win.activate()
                    time.sleep(0.15)
                    logger.info("Focused window: %s", win.title)
                    return {"success": True, "title": win.title}
                except Exception as e:
                    logger.error("activate() failed for '%s': %s", win.title, e)
                    return {"success": False, "error": str(e), "title": win.title}
    except Exception as e:
        logger.error("getAllWindows failed during focus: %s", e)
    return None
