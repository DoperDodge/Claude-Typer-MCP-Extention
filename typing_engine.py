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
from typing import Optional

import pyautogui
import pyperclip

# Disable pyautogui's built-in pause and failsafe for smoother typing
pyautogui.PAUSE = 0
pyautogui.FAILSAFE = True  # Keep failsafe (move mouse to corner to abort)

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
        self.wpm = wpm
        self.consistency = consistency
        self.human_mode = human_mode

        # Speed drift state (for human-like mode)
        self._drift_phase = random.uniform(0, 2 * math.pi)
        self._drift_speed = random.uniform(0.05, 0.15)  # How fast WPM drifts
        self._char_count = 0

        # Stop flag for cancelling mid-type
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

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
        self._stop_event.clear()
        self._char_count = 0
        start = time.perf_counter()

        for i, char in enumerate(text):
            if self._stop_event.is_set():
                return {"typed": i, "total": len(text), "cancelled": True,
                        "elapsed_s": round(time.perf_counter() - start, 2)}

            # Calculate delay BEFORE this character
            delay = self._compute_delay(text, i)
            time.sleep(delay)

            # Type the character
            self._send_char(char)
            self._char_count += 1

        elapsed = time.perf_counter() - start
        return {"typed": len(text), "total": len(text), "cancelled": False,
                "elapsed_s": round(elapsed, 2)}

    def paste_text(self, text: str) -> dict:
        """Paste text via clipboard, preserving original clipboard contents."""
        original_clipboard = ""
        try:
            original_clipboard = pyperclip.paste()
        except Exception:
            pass  # Clipboard might be empty or inaccessible

        try:
            pyperclip.copy(text)
            time.sleep(0.05)  # Brief pause for clipboard to settle
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.1)  # Wait for paste to complete
            return {"pasted": True, "length": len(text)}
        finally:
            # Restore original clipboard after a short delay
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
        parts = [k.strip().lower() for k in keys.split('+')]
        try:
            pyautogui.hotkey(*parts)
            return {"pressed": keys, "success": True}
        except Exception as e:
            return {"pressed": keys, "success": False, "error": str(e)}

    def stop(self):
        """Cancel an in-progress type_text operation."""
        self._stop_event.set()

    # ------------------------------------------------------------------ #
    #  Delay computation                                                  #
    # ------------------------------------------------------------------ #

    def _compute_delay(self, text: str, index: int) -> float:
        """Compute the delay before typing text[index]."""
        effective_wpm = self.wpm

        # --- Human-like speed drift ---
        if self.human_mode:
            drift = math.sin(self._drift_phase + self._char_count * self._drift_speed)
            effective_wpm = self.wpm * (1.0 + 0.15 * drift)  # ±15%

        # Base delay: seconds per character (5 chars ≈ 1 word)
        base_delay = 60.0 / (effective_wpm * 5.0)

        if not self.human_mode:
            # --- Basic mode: Gaussian jitter ---
            variance = base_delay * (1.0 - self.consistency)
            delay = base_delay + random.gauss(0, variance)
            return max(0.01, delay)

        # --- Human-like mode ---
        char = text[index]
        prev_char = text[index - 1] if index > 0 else ''

        # Log-normal distribution (right-skewed: occasional long pauses, rarely super fast)
        sigma = 0.3 * (1.0 - self.consistency) + 0.05  # minimum jitter even at consistency=1
        delay = base_delay * random.lognormvariate(0, sigma)

        # Digraph acceleration
        if index > 0:
            digraph = (prev_char + char).lower()
            if digraph in FAST_DIGRAPHS:
                delay *= random.uniform(0.60, 0.80)

        # Trigraph / sequence acceleration
        if index >= 2:
            trigraph = text[index - 2:index + 1].lower()
            if trigraph in FAST_SEQUENCES:
                delay *= random.uniform(0.65, 0.85)

        # Word boundary pause (after space, at start of new word)
        if prev_char == ' ' and char != ' ':
            delay += random.uniform(0.03, 0.10)

        # Sentence boundary pause
        if prev_char in SENTENCE_ENDERS and char == ' ':
            delay += random.uniform(0.15, 0.40)

        # Comma / semicolon pause
        if prev_char in PAUSE_TRIGGERS and char == ' ':
            delay += random.uniform(0.04, 0.12)

        # Thinking pause (occasional mid-sentence hesitation)
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
