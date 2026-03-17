"""
Hotkey Manager — Global keyboard shortcut listener.

Runs a background listener using pynput that captures hotkey combos
even when other windows are focused. Used primarily for answer queue
navigation so the user never has to leave their document.

Default hotkeys (chosen to avoid conflicts with Google Docs, browsers, etc.):
    Ctrl+Alt+N  — Type next answer in queue
    Ctrl+Alt+S  — Skip current answer
    Ctrl+Alt+X  — Stop typing / clear queue
    Ctrl+Alt+Z  — Undo last typed answer (select all + delete)
"""

import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger("claude-typer.hotkeys")

try:
    from pynput import keyboard
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False
    logger.warning("pynput not installed — global hotkeys unavailable")


# Default hotkey definitions
# Each hotkey is a frozenset of normalized pynput Key/KeyCode objects.
# IMPORTANT: Use keyboard.Key.* for special keys (space, enter, etc.)
# and keyboard.KeyCode.from_char() for printable characters.
if HAS_PYNPUT:
    DEFAULT_HOTKEYS = {
        "next_answer": {keyboard.Key.ctrl_l, keyboard.Key.alt_l, keyboard.KeyCode.from_char('n')},
        "skip_answer": {keyboard.Key.ctrl_l, keyboard.Key.alt_l, keyboard.KeyCode.from_char('s')},
        "stop_clear":  {keyboard.Key.ctrl_l, keyboard.Key.alt_l, keyboard.KeyCode.from_char('x')},
        "undo_last":   {keyboard.Key.ctrl_l, keyboard.Key.alt_l, keyboard.KeyCode.from_char('z')},
    }
else:
    DEFAULT_HOTKEYS = {
        "next_answer": set(),
        "skip_answer": set(),
        "stop_clear": set(),
        "undo_last": set(),
    }

# Human-readable labels for display
HOTKEY_LABELS = {
    "next_answer": "Ctrl+Alt+N",
    "skip_answer": "Ctrl+Alt+S",
    "stop_clear": "Ctrl+Alt+X",
    "undo_last": "Ctrl+Alt+Z",
}


class HotkeyManager:
    """
    Global hotkey listener that runs in a background thread.

    Listens for key combinations and fires callbacks even when
    the Claude Desktop window is not focused.
    """

    def __init__(self):
        self._callbacks: dict[str, Optional[Callable]] = {
            "next_answer": None,
            "skip_answer": None,
            "stop_clear": None,
            "undo_last": None,
        }

        self._pressed_keys: set = set()
        self._listener: Optional[object] = None
        self._running = False

        # Debounce: prevent same hotkey firing multiple times per press
        self._last_trigger: dict[str, float] = {}
        self._debounce_s = 0.4

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

    def register(self, action: str, callback: Callable):
        """
        Register a callback for a hotkey action.

        Args:
            action: One of 'next_answer', 'skip_answer', 'stop_clear', 'undo_last'.
            callback: Function to call when the hotkey is pressed (no arguments).
        """
        if action not in self._callbacks:
            raise ValueError(f"Unknown action '{action}'. "
                             f"Available: {list(self._callbacks.keys())}")
        self._callbacks[action] = callback
        logger.info("Registered hotkey: %s → %s", HOTKEY_LABELS.get(action, action), action)

    def start(self):
        """Start listening for global hotkeys in a background thread."""
        if not HAS_PYNPUT:
            logger.warning("Cannot start hotkey listener — pynput not installed")
            return False

        if self._running:
            logger.info("Hotkey listener already running")
            return True

        self._running = True
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.daemon = True
        self._listener.start()
        logger.info("Global hotkey listener started")
        return True

    def stop(self):
        """Stop the hotkey listener."""
        self._running = False
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
        self._pressed_keys.clear()
        logger.info("Global hotkey listener stopped")

    @property
    def is_running(self) -> bool:
        return self._running and self._listener is not None

    @staticmethod
    def check_dependencies() -> dict:
        """Check if pynput is available."""
        issues = []
        if not HAS_PYNPUT:
            issues.append("pynput not installed (pip install pynput)")
        return {
            "healthy": len(issues) == 0,
            "pynput": HAS_PYNPUT,
            "issues": issues,
        }

    # ------------------------------------------------------------------ #
    #  Internal key tracking                                              #
    # ------------------------------------------------------------------ #

    def _on_press(self, key):
        """Called on every key press."""
        if not self._running:
            return

        # Normalize key representation
        normalized = self._normalize_key(key)
        if normalized:
            self._pressed_keys.add(normalized)

        # Check each hotkey
        for action, hotkey_set in DEFAULT_HOTKEYS.items():
            if not hotkey_set:
                continue
            if self._match_hotkey(hotkey_set):
                self._fire_action(action)

    def _on_release(self, key):
        """Called on every key release."""
        normalized = self._normalize_key(key)
        if normalized:
            self._pressed_keys.discard(normalized)

    def _normalize_key(self, key) -> Optional[object]:
        """
        Normalize a key to a consistent representation.

        Handles several pynput quirks on Windows:
        - Right-side modifiers (ctrl_r, shift_r, alt_r) → left-side equivalents
        - AltGr → alt_l (Windows reports Ctrl+Alt as AltGr on some layouts)
        - KeyCode with char=None but valid vk → rebuild from virtual key code
          (happens when Ctrl+Alt is held — OS swallows the char)
        """
        if not HAS_PYNPUT:
            return None

        # Map right-side modifiers to left-side for matching
        modifier_map = {
            keyboard.Key.ctrl_r: keyboard.Key.ctrl_l,
            keyboard.Key.shift_r: keyboard.Key.shift,
            keyboard.Key.alt_r: keyboard.Key.alt_l,
            keyboard.Key.alt_gr: keyboard.Key.alt_l,
        }

        if key in modifier_map:
            return modifier_map[key]

        # For regular keys, normalize to lowercase KeyCode.
        # On Windows with Ctrl+Alt held, pynput may report the char as None
        # because the OS interprets Ctrl+Alt as AltGr. In that case, fall
        # back to the vk (virtual key code) to build a proper KeyCode.
        if isinstance(key, keyboard.KeyCode):
            if key.char:
                return keyboard.KeyCode.from_char(key.char.lower())
            elif key.vk is not None:
                # Map virtual key codes for a-z (0x41-0x5A) to lowercase chars
                if 0x41 <= key.vk <= 0x5A:
                    return keyboard.KeyCode.from_char(chr(key.vk + 32))
                # Map virtual key codes for 0-9 (0x30-0x39)
                if 0x30 <= key.vk <= 0x39:
                    return keyboard.KeyCode.from_char(chr(key.vk))
            return key

        return key

    def _match_hotkey(self, hotkey_set: set) -> bool:
        """Check if the currently pressed keys match a hotkey set."""
        for k in hotkey_set:
            if k not in self._pressed_keys:
                return False
        return True

    def _fire_action(self, action: str):
        """Fire a hotkey callback with debounce protection."""
        now = time.monotonic()
        last = self._last_trigger.get(action, 0)

        if now - last < self._debounce_s:
            return  # Too soon, skip

        self._last_trigger[action] = now

        # Remove only the non-modifier trigger key (e.g. 'n' from Ctrl+Alt+N).
        # We must NOT clear modifier keys here — _wait_for_keys_released()
        # needs them in the set so it can detect when the user physically
        # lets go. The _on_release handler will remove modifiers naturally.
        if HAS_PYNPUT:
            modifier_keys = {
                keyboard.Key.ctrl_l, keyboard.Key.ctrl_r,
                keyboard.Key.shift, keyboard.Key.shift_r,
                keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr,
            }
            non_modifiers = [k for k in self._pressed_keys if k not in modifier_keys]
            for k in non_modifiers:
                self._pressed_keys.discard(k)
        else:
            self._pressed_keys.clear()

        callback = self._callbacks.get(action)
        if callback:
            logger.info("Hotkey triggered: %s (%s)", action, HOTKEY_LABELS.get(action, ""))
            try:
                # Run callback in a separate thread to avoid blocking the listener
                threading.Thread(target=callback, daemon=True).start()
            except Exception as e:
                logger.error("Hotkey callback failed for %s: %s", action, e)
        else:
            logger.debug("Hotkey %s pressed but no callback registered", action)
