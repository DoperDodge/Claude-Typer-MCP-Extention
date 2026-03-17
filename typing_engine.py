"""
Typing Engine — Keystroke simulation with human-like timing.

Handles all input simulation: character-by-character typing with configurable
speed/consistency, human-like mode with digraph acceleration and thinking pauses,
clipboard paste, and key combo sending.
"""

import time
import math
import random
import threading
import logging
from typing import Optional

logger = logging.getLogger("claude-typer.typing")

try:
    import pyautogui
    pyautogui.PAUSE = 0
    pyautogui.FAILSAFE = True  # move mouse to corner to abort
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False
    logger.warning("pyautogui not installed — typing simulation unavailable")

try:
    import pyperclip
    HAS_PYPERCLIP = True
except ImportError:
    HAS_PYPERCLIP = False
    logger.warning("pyperclip not installed — clipboard paste unavailable")


# Common digraphs that typists hit faster due to muscle memory
FAST_DIGRAPHS = {
    "th", "he", "in", "er", "an", "re", "on", "en", "at", "es",
    "ed", "te", "ti", "or", "st", "ar", "nd", "to", "nt", "is",
    "of", "it", "al", "as", "ha", "ng", "co", "se", "me", "de",
    "io", "ou", "le", "ve", "ro", "ri", "ne", "ea", "ra", "ce",
}

# Extended sequences typed fast
FAST_SEQUENCES = {"ing", "tion", "ment", "ness", "the", "and", "ght"}

SENTENCE_ENDERS = {'.', '!', '?'}
PAUSE_TRIGGERS = {',', ';', ':'}


class TypingEngine:
    """Simulates human-like keyboard input."""

    def __init__(self, wpm: int = 80, consistency: float = 0.7, human_mode: bool = True):
        self.wpm = max(30, min(150, wpm))
        self.consistency = max(0.0, min(1.0, consistency))
        self.human_mode = human_mode

        # Speed drift state (for human-like mode)
        self._drift_phase = random.uniform(0, 2 * math.pi)
        self._drift_speed = random.uniform(0.05, 0.15)
        self._char_count = 0

        # Stop flag for cancelling mid-type
        self._stop_event = threading.Event()

        # Lock to prevent concurrent type operations
        self._typing_lock = threading.Lock()

        # Track whether we're actively typing
        self._is_typing = False

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

    @property
    def is_typing(self) -> bool:
        """Whether a type_text operation is currently in progress."""
        return self._is_typing

    def update_settings(self, wpm: Optional[int] = None,
                        consistency: Optional[float] = None,
                        human_mode: Optional[bool] = None):
        """Update typing parameters on the fly."""
        if wpm is not None:
            self.wpm = max(30, min(150, wpm))
        if consistency is not None:
            self.consistency = max(0.0, min(1.0, consistency))
        if human_mode is not None:
            self.human_mode = human_mode

    def type_text(self, text: str) -> dict:
        """
        Type text character-by-character into the active window.
        Returns a summary dict with chars typed and elapsed time.
        """
        if not HAS_PYAUTOGUI:
            return {"typed": 0, "total": len(text), "cancelled": False,
                    "error": "pyautogui not installed — cannot simulate typing",
                    "elapsed_s": 0}

        if not text:
            return {"typed": 0, "total": 0, "cancelled": False, "elapsed_s": 0}

        if not self._typing_lock.acquire(blocking=False):
            return {"typed": 0, "total": len(text), "cancelled": False,
                    "error": "Another typing operation is already in progress",
                    "elapsed_s": 0}

        try:
            self._stop_event.clear()
            self._is_typing = True
            self._char_count = 0
            start = time.perf_counter()

            for i, char in enumerate(text):
                if self._stop_event.is_set():
                    elapsed = time.perf_counter() - start
                    logger.info("Typing cancelled at char %d/%d", i, len(text))
                    return {"typed": i, "total": len(text), "cancelled": True,
                            "elapsed_s": round(elapsed, 2)}

                delay = self._compute_delay(text, i)
                time.sleep(delay)

                try:
                    self._send_char(char)
                except Exception as e:
                    elapsed = time.perf_counter() - start
                    logger.error("Failed to send char %d: %s", i, e)
                    return {"typed": i, "total": len(text), "cancelled": False,
                            "error": f"Keystroke failed at char {i}: {e}",
                            "elapsed_s": round(elapsed, 2)}

                self._char_count += 1

            elapsed = time.perf_counter() - start
            logger.info("Typed %d chars in %.2fs", len(text), elapsed)
            return {"typed": len(text), "total": len(text), "cancelled": False,
                    "elapsed_s": round(elapsed, 2)}

        except pyautogui.FailSafeException:
            elapsed = time.perf_counter() - start
            logger.warning("Failsafe triggered — mouse moved to corner")
            return {"typed": self._char_count, "total": len(text), "cancelled": True,
                    "error": "Failsafe triggered (mouse moved to screen corner)",
                    "elapsed_s": round(elapsed, 2)}
        except Exception as e:
            elapsed = time.perf_counter() - start
            logger.error("Unexpected typing error: %s", e)
            return {"typed": self._char_count, "total": len(text), "cancelled": False,
                    "error": f"Unexpected error: {e}",
                    "elapsed_s": round(elapsed, 2)}
        finally:
            self._is_typing = False
            self._typing_lock.release()

    def paste_text(self, text: str) -> dict:
        """Paste text via clipboard, preserving original clipboard contents."""
        if not HAS_PYAUTOGUI:
            return {"pasted": False, "length": len(text),
                    "error": "pyautogui not installed — cannot paste"}

        if not HAS_PYPERCLIP:
            return {"pasted": False, "length": len(text),
                    "error": "pyperclip not installed — cannot access clipboard"}

        if not text:
            return {"pasted": False, "length": 0, "error": "No text to paste"}

        original_clipboard = ""
        try:
            original_clipboard = pyperclip.paste()
        except Exception:
            pass

        try:
            pyperclip.copy(text)
            time.sleep(0.05)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.1)
            logger.info("Pasted %d chars", len(text))
            return {"pasted": True, "length": len(text)}
        except pyautogui.FailSafeException:
            logger.warning("Failsafe triggered during paste")
            return {"pasted": False, "length": len(text),
                    "error": "Failsafe triggered (mouse moved to screen corner)"}
        except Exception as e:
            logger.error("Paste failed: %s", e)
            return {"pasted": False, "length": len(text), "error": f"Paste failed: {e}"}
        finally:
            time.sleep(0.2)
            try:
                pyperclip.copy(original_clipboard)
            except Exception:
                pass

    def press_keys(self, keys: str) -> dict:
        """
        Send a keyboard shortcut.

        Accepts formats like:
          "ctrl+b", "ctrl+shift+7", "enter", "tab", "alt+f4"
        """
        if not HAS_PYAUTOGUI:
            return {"pressed": keys, "success": False,
                    "error": "pyautogui not installed — cannot send keys"}

        if not keys or not keys.strip():
            return {"pressed": keys, "success": False, "error": "No keys specified"}

        parts = [k.strip().lower() for k in keys.split('+')]
        try:
            pyautogui.hotkey(*parts)
            logger.info("Pressed keys: %s", keys)
            return {"pressed": keys, "success": True}
        except pyautogui.FailSafeException:
            return {"pressed": keys, "success": False,
                    "error": "Failsafe triggered (mouse moved to screen corner)"}
        except Exception as e:
            logger.error("Key press failed: %s", e)
            return {"pressed": keys, "success": False, "error": str(e)}

    def stop(self):
        """Cancel an in-progress type_text operation."""
        if self._is_typing:
            self._stop_event.set()
            logger.info("Stop requested")
            return True
        return False

    # ------------------------------------------------------------------ #
    #  Health check                                                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def check_dependencies() -> dict:
        """Check that required libraries are available and functional."""
        issues = []

        if not HAS_PYAUTOGUI:
            issues.append("pyautogui not installed (pip install pyautogui)")
        if not HAS_PYPERCLIP:
            issues.append("pyperclip not installed (pip install pyperclip)")

        if HAS_PYAUTOGUI:
            try:
                pyautogui.size()
            except Exception as e:
                issues.append(f"pyautogui cannot access display: {e}")

        if HAS_PYPERCLIP:
            try:
                pyperclip.paste()
            except Exception as e:
                issues.append(f"Clipboard not accessible: {e}")

        return {
            "healthy": len(issues) == 0,
            "pyautogui": HAS_PYAUTOGUI,
            "pyperclip": HAS_PYPERCLIP,
            "issues": issues,
        }

    # ------------------------------------------------------------------ #
    #  Delay computation                                                  #
    # ------------------------------------------------------------------ #

    def _compute_delay(self, text: str, index: int) -> float:
        """Compute the delay before typing text[index]."""
        effective_wpm = self.wpm

        if self.human_mode:
            drift = math.sin(self._drift_phase + self._char_count * self._drift_speed)
            effective_wpm = self.wpm * (1.0 + 0.15 * drift)

        base_delay = 60.0 / (effective_wpm * 5.0)

        if not self.human_mode:
            variance = base_delay * (1.0 - self.consistency)
            delay = base_delay + random.gauss(0, variance)
            return max(0.01, delay)

        char = text[index]
        prev_char = text[index - 1] if index > 0 else ''

        sigma = 0.3 * (1.0 - self.consistency) + 0.05
        delay = base_delay * random.lognormvariate(0, sigma)

        if index > 0:
            digraph = (prev_char + char).lower()
            if digraph in FAST_DIGRAPHS:
                delay *= random.uniform(0.60, 0.80)

        if index >= 2:
            trigraph = text[index - 2:index + 1].lower()
            if trigraph in FAST_SEQUENCES:
                delay *= random.uniform(0.65, 0.85)

        if prev_char == ' ' and char != ' ':
            delay += random.uniform(0.03, 0.10)

        if prev_char in SENTENCE_ENDERS and char == ' ':
            delay += random.uniform(0.15, 0.40)

        if prev_char in PAUSE_TRIGGERS and char == ' ':
            delay += random.uniform(0.04, 0.12)

        if (self._char_count > 0 and
                self._char_count % random.randint(20, 50) == 0 and
                char.isalpha()):
            delay += random.uniform(0.25, 0.65)

        return max(0.01, delay)

    # ------------------------------------------------------------------ #
    #  Character sending                                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _send_char(char: str):
        """Send a single character to the active window."""
        if char == '\n':
            pyautogui.press('enter')
        elif char == '\t':
            pyautogui.press('tab')
        else:
            pyautogui.write(char, interval=0)
