"""
Claude Typer — MCP Server

A local MCP server that gives Claude the ability to type text into any
active Windows application with human-like typing behavior and
configurable writing style.

Communicates with Claude Desktop via stdio transport.
"""

import json
import logging
import os
import sys
import threading
import time
from collections import deque
from typing import Optional

from mcp.server.fastmcp import FastMCP

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from typing_engine import TypingEngine
from style_engine import StyleEngine
from calibration import CalibrationSession
from window_manager import (
    get_active_window, focus_window, list_windows,
    verify_window_focused, check_dependencies as check_window_deps,
)
from answer_queue import AnswerQueue
from hotkey_manager import HotkeyManager, HOTKEY_LABELS

# ------------------------------------------------------------------ #
#  Logging                                                             #
# ------------------------------------------------------------------ #

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claude_typer.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
logger = logging.getLogger("claude-typer.server")

# ------------------------------------------------------------------ #
#  Configuration                                                       #
# ------------------------------------------------------------------ #

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# Default config structure — used for migration when keys are missing
DEFAULT_CONFIG = {
    "typing": {"wpm": 80, "consistency": 0.7, "human_mode": True},
    "style": {"preset": None, "grade_level": None, "active_profile": None},
    "approval": {"require_approval": True},
}


def load_config() -> dict:
    """Load config from disk, migrating missing keys from defaults."""
    cfg = {}
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r') as f:
                cfg = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("Failed to load config, using defaults: %s", e)

    # Migrate: fill in any missing top-level sections or keys
    changed = False
    for section, defaults in DEFAULT_CONFIG.items():
        if section not in cfg:
            cfg[section] = dict(defaults)
            changed = True
        elif isinstance(defaults, dict):
            for key, val in defaults.items():
                if key not in cfg[section]:
                    cfg[section][key] = val
                    changed = True

    if changed:
        save_config(cfg)
        logger.info("Config migrated with missing defaults")

    return cfg


def save_config(settings: dict):
    """Persist config to disk."""
    try:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(settings, f, indent=2)
    except IOError as e:
        logger.error("Failed to save config: %s", e)


# ------------------------------------------------------------------ #
#  Initialize components                                               #
# ------------------------------------------------------------------ #

config = load_config()

typer = TypingEngine(
    wpm=config["typing"]["wpm"],
    consistency=config["typing"]["consistency"],
    human_mode=config["typing"]["human_mode"],
)

style = StyleEngine()
if config["style"].get("preset"):
    try:
        style.set_preset(config["style"]["preset"])
    except ValueError as e:
        logger.warning("Invalid preset in config: %s", e)

if config["style"].get("grade_level"):
    style.set_grade_level(config["style"]["grade_level"])

if config["style"].get("active_profile"):
    try:
        style.set_active_profile(config["style"]["active_profile"])
    except ValueError as e:
        logger.warning("Invalid profile in config: %s", e)

# Active calibration session (one at a time)
calibration_session: Optional[CalibrationSession] = None

# GUI reference (launched in separate thread if available)
gui_instance = None

# ------------------------------------------------------------------ #
#  Answer queue & hotkeys                                              #
# ------------------------------------------------------------------ #

def _on_queue_status_change(status: dict):
    """Callback when queue state changes — update GUI."""
    if gui_instance:
        try:
            gui_instance.update_queue_display(status)
        except Exception:
            pass

    # Log meaningful state changes
    if status.get("queue_complete") and status.get("total", 0) > 0:
        _log_action(f"Queue complete! {status['completed']} typed, {status['skipped']} skipped")


answer_queue = AnswerQueue(
    typing_engine=typer,
    on_status_change=_on_queue_status_change,
)

hotkey_mgr = HotkeyManager()


def _wait_for_keys_released():
    """Wait for modifier keys to be released before typing.
    
    When a hotkey like Ctrl+Alt+N fires, those keys are still
    physically held down. If we start typing immediately, pyautogui
    sends characters while Ctrl+Alt are pressed, which causes
    mangled input (e.g. Ctrl+Alt+h instead of 'h').
    """
    try:
        import time as _time
        from pynput import keyboard as _kb

        # Wait up to 1 second for modifiers to be released
        for _ in range(20):
            _time.sleep(0.05)
            # Snapshot the set to avoid race with pynput listener thread
            pressed = set(hotkey_mgr._pressed_keys)
            has_modifiers = any(
                k in pressed for k in [
                    _kb.Key.ctrl_l, _kb.Key.ctrl_r,
                    _kb.Key.shift, _kb.Key.shift_r,
                    _kb.Key.alt_l, _kb.Key.alt_r, _kb.Key.alt_gr,
                ]
            )
            if not has_modifiers:
                # Small extra delay for OS key state to fully settle
                _time.sleep(0.05)
                return
        # Timeout — type anyway, user might still be holding keys
        logger.warning("Modifier keys still held after 1s — typing anyway")
    except Exception:
        # Fallback: just wait a fixed amount
        import time as _time
        _time.sleep(0.3)


def _hotkey_next_answer():
    """Hotkey callback: type next answer."""
    _wait_for_keys_released()
    result = answer_queue.type_next()
    if result.get("error"):
        _log_action(f"Queue: {result['error']}")
    elif result.get("typed_answer"):
        remaining = result.get("remaining", 0)
        _log_action(f"Typed answer {result['typed_answer']} "
                     f"({result['chars']} chars) — {remaining} remaining")


def _hotkey_skip():
    """Hotkey callback: skip current answer."""
    result = answer_queue.skip_current()
    if result.get("skipped_answer"):
        _log_action(f"Skipped answer {result['skipped_answer']} — "
                     f"{result['remaining']} remaining")
    else:
        _log_action(f"Skip: {result.get('error', 'nothing to skip')}")


def _hotkey_stop_clear():
    """Hotkey callback: stop typing or clear queue."""
    if typer.is_typing:
        typer.stop()
        _log_action("Hotkey stop: typing cancelled")
    else:
        result = answer_queue.clear()
        _log_action(f"Hotkey clear: {result.get('cleared', 0)} items removed")


def _hotkey_undo():
    """Hotkey callback: undo last typed answer."""
    _wait_for_keys_released()
    result = answer_queue.undo_last()
    if result.get("undone_answer"):
        _log_action(f"Undid answer {result['undone_answer']} "
                     f"({result['chars_deleted']} chars deleted)")
    else:
        _log_action(f"Undo: {result.get('error', 'nothing to undo')}")


# Register all hotkey callbacks
hotkey_mgr.register("next_answer", _hotkey_next_answer)
hotkey_mgr.register("skip_answer", _hotkey_skip)
hotkey_mgr.register("stop_clear", _hotkey_stop_clear)
hotkey_mgr.register("undo_last", _hotkey_undo)

# ------------------------------------------------------------------ #
#  Approval mode state                                                 #
# ------------------------------------------------------------------ #

_pending_text: Optional[str] = None
_pending_mode: Optional[str] = None  # "type" or "paste"
_pending_id: int = 0

def _is_approval_required() -> bool:
    cfg = load_config()
    return cfg.get("approval", {}).get("require_approval", True)

# ------------------------------------------------------------------ #
#  Action log                                                          #
# ------------------------------------------------------------------ #

_action_log: deque = deque(maxlen=50)


def _log_action(text: str):
    """Log an action to the rolling history and update GUI."""
    timestamp = time.strftime("%H:%M:%S")
    entry = f"[{timestamp}] {text}"
    _action_log.append(entry)
    logger.info(text)

    global gui_instance
    if gui_instance:
        try:
            gui_instance.set_action(text)
        except Exception:
            pass


# ------------------------------------------------------------------ #
#  MCP Server                                                          #
# ------------------------------------------------------------------ #

mcp = FastMCP("Claude Typer")


# ======================== TYPING TOOLS ======================== #

@mcp.tool()
def type_text(text: str) -> dict:
    """
    Type text character-by-character into the currently active window.

    If approval mode is ON (default), this stages the text for preview.
    The user must approve it before typing begins. If approval mode is
    OFF, text is typed immediately.

    IMPORTANT: When approval mode is on, always show the user the
    'preview' text from the response and ask them to confirm before
    calling approve_pending().

    Args:
        text: The text to type into the active window.

    Returns:
        If approval required: preview of text and pending_id to approve.
        If no approval needed: summary with chars typed and elapsed time.
    """
    global _pending_text, _pending_mode, _pending_id

    if not text or not text.strip():
        return {"error": "No text provided to type."}

    if _is_approval_required():
        _pending_text = text
        _pending_mode = "type"
        _pending_id += 1
        _log_action(f"Staged {len(text)} chars for approval (type mode)")
        return {
            "status": "pending_approval",
            "pending_id": _pending_id,
            "mode": "type",
            "preview": text,
            "char_count": len(text),
            "message": "Text is staged for typing. Show the preview to the user and call approve_pending() after they confirm, or reject_pending() to cancel.",
        }

    # Direct typing (approval off)
    window = get_active_window()
    _log_action(f"Typing {len(text)} chars into '{window.get('title', 'unknown')}'...")
    result = typer.type_text(text)

    if result.get("error"):
        _log_action(f"Typing error: {result['error']}")
    else:
        _log_action(f"Typed {result['typed']}/{result['total']} chars in {result['elapsed_s']}s")

    result["window"] = window.get("title", "unknown")
    return result


@mcp.tool()
def paste_text(text: str) -> dict:
    """
    Instantly paste text into the active window via clipboard (Ctrl+V).

    If approval mode is ON (default), this stages the text for preview.
    The user must approve it before pasting. If approval mode is OFF,
    text is pasted immediately.

    Args:
        text: The text to paste.

    Returns:
        If approval required: preview of text and pending_id to approve.
        If no approval needed: summary with paste status and text length.
    """
    global _pending_text, _pending_mode, _pending_id

    if not text:
        return {"error": "No text provided to paste."}

    if _is_approval_required():
        _pending_text = text
        _pending_mode = "paste"
        _pending_id += 1
        _log_action(f"Staged {len(text)} chars for approval (paste mode)")
        return {
            "status": "pending_approval",
            "pending_id": _pending_id,
            "mode": "paste",
            "preview": text,
            "char_count": len(text),
            "message": "Text is staged for pasting. Show the preview to the user and call approve_pending() after they confirm, or reject_pending() to cancel.",
        }

    window = get_active_window()
    _log_action(f"Pasting {len(text)} chars into '{window.get('title', 'unknown')}'...")
    result = typer.paste_text(text)

    if result.get("error"):
        _log_action(f"Paste error: {result['error']}")
    else:
        _log_action("Paste complete")

    result["window"] = window.get("title", "unknown")
    return result


@mcp.tool()
def approve_pending(pending_id: Optional[int] = None) -> dict:
    """
    Approve and execute the pending text (type or paste).

    Call this ONLY after showing the user the preview text and receiving
    their explicit confirmation. If they want changes, call reject_pending()
    and generate new text instead.

    Args:
        pending_id: The pending_id from the staged text (optional verification).

    Returns:
        Typing/pasting result summary.
    """
    global _pending_text, _pending_mode

    if _pending_text is None:
        return {"error": "Nothing pending. Stage text with type_text() or paste_text() first."}

    if pending_id is not None and pending_id != _pending_id:
        return {"error": f"Stale pending_id {pending_id}. Current is {_pending_id}. "
                         f"The text may have been re-staged. Check with get_settings()."}

    text = _pending_text
    mode = _pending_mode
    _pending_text = None
    _pending_mode = None

    window = get_active_window()
    window_title = window.get("title", "unknown")

    if mode == "paste":
        _log_action(f"Approved — pasting {len(text)} chars into '{window_title}'...")
        result = typer.paste_text(text)
        if result.get("error"):
            _log_action(f"Paste error: {result['error']}")
        else:
            _log_action("Paste complete")
    else:
        _log_action(f"Approved — typing {len(text)} chars into '{window_title}'...")
        result = typer.type_text(text)
        if result.get("error"):
            _log_action(f"Typing error: {result['error']}")
        else:
            _log_action(f"Typed {result['typed']}/{result['total']} chars in {result['elapsed_s']}s")

    result["window"] = window_title
    return result


@mcp.tool()
def reject_pending() -> dict:
    """
    Cancel the pending text without typing or pasting it.

    Use when the user wants changes to the previewed text.

    Returns:
        Confirmation that pending text was cleared.
    """
    global _pending_text, _pending_mode

    if _pending_text is None:
        return {"message": "Nothing was pending."}

    char_count = len(_pending_text)
    _pending_text = None
    _pending_mode = None
    _log_action(f"Rejected pending text ({char_count} chars)")
    return {"message": f"Rejected {char_count} chars. Pending text cleared."}


@mcp.tool()
def stop_typing() -> dict:
    """
    Emergency stop — cancel typing that is currently in progress.

    If the typing engine is actively typing into a window, this will
    stop it immediately. Characters already typed remain in the document.

    Returns:
        Whether a stop was triggered.
    """
    if typer.is_typing:
        typer.stop()
        _log_action("Emergency stop triggered")
        return {"stopped": True, "message": "Typing stopped. Characters already typed remain."}
    return {"stopped": False, "message": "No typing in progress."}


@mcp.tool()
def press_keys(keys: str) -> dict:
    """
    Send a keyboard shortcut to the active window.

    Use for formatting and navigation in apps like Google Docs, Word, etc.

    Examples:
        - "ctrl+b" — Bold
        - "ctrl+i" — Italic
        - "ctrl+shift+7" — Numbered list (Google Docs)
        - "ctrl+shift+8" — Bullet list (Google Docs)
        - "enter" — New line
        - "tab" — Tab
        - "ctrl+a" — Select all

    Args:
        keys: Key combination string (e.g. "ctrl+b", "enter", "ctrl+shift+7").

    Returns:
        Result with the keys pressed and success status.
    """
    _log_action(f"Pressing {keys}")
    result = typer.press_keys(keys)
    if result.get("error"):
        _log_action(f"Key press error: {result['error']}")
    return result


# ======================== CONFIGURATION TOOLS ======================== #

@mcp.tool()
def configure_typing(
    wpm: Optional[int] = None,
    consistency: Optional[float] = None,
    human_mode: Optional[bool] = None,
) -> dict:
    """
    Adjust typing behavior settings.

    Args:
        wpm: Typing speed in words per minute (30-150). Default is 80.
        consistency: How uniform the timing is (0.0 = erratic, 1.0 = uniform).
        human_mode: Enable/disable advanced human-like typing simulation
                    (digraph acceleration, thinking pauses, speed drift).

    Returns:
        The updated typing settings.
    """
    typer.update_settings(wpm=wpm, consistency=consistency, human_mode=human_mode)

    updated = {
        "wpm": typer.wpm,
        "consistency": typer.consistency,
        "human_mode": typer.human_mode,
    }

    cfg = load_config()
    cfg["typing"] = updated
    save_config(cfg)

    _log_action(f"Typing config: WPM={updated['wpm']}, "
                f"consistency={updated['consistency']}, "
                f"human_mode={updated['human_mode']}")
    return {"message": "Typing settings updated", "settings": updated}


@mcp.tool()
def configure_style(
    preset: Optional[str] = None,
    grade_level: Optional[int] = None,
    profile: Optional[str] = None,
) -> dict:
    """
    Set the active writing style for text generation.

    Available presets: intellectual, smart, concise, basic, casual, professional, verbose.

    Args:
        preset: Style preset name, or null/empty to clear.
        grade_level: Target reading level 1-16 (1st grade to postgrad), or null to clear.
        profile: Name of a custom style profile to activate, or null to clear.

    Returns:
        Updated style settings.
    """
    try:
        style.set_preset(preset if preset else None)
        style.set_grade_level(grade_level)
        style.set_active_profile(profile if profile else None)
    except ValueError as e:
        _log_action(f"Style config error: {e}")
        return {"error": str(e)}

    settings = style.get_settings()

    cfg = load_config()
    cfg["style"] = {
        "preset": style.preset,
        "grade_level": style.grade_level,
        "active_profile": style.active_profile,
    }
    save_config(cfg)

    _log_action(f"Style: preset={style.preset}, grade={style.grade_level}, "
                f"profile={style.active_profile}")
    return {"message": "Style settings updated", "settings": settings}


@mcp.tool()
def configure_approval(require_approval: bool) -> dict:
    """
    Toggle approval mode on or off.

    When ON (default): type_text and paste_text stage text for preview.
    The user must approve before anything is typed.
    When OFF: text is typed/pasted immediately without preview.

    Args:
        require_approval: True to require approval, False for immediate typing.

    Returns:
        Updated approval setting.
    """
    cfg = load_config()
    cfg["approval"]["require_approval"] = require_approval
    save_config(cfg)
    _log_action(f"Approval mode: {'ON' if require_approval else 'OFF'}")
    return {
        "message": f"Approval mode {'enabled' if require_approval else 'disabled'}.",
        "require_approval": require_approval,
    }


@mcp.tool()
def get_settings() -> dict:
    """
    Return the current typing behavior and writing style configuration,
    approval status, and any pending text info.
    """
    return {
        "typing": {
            "wpm": typer.wpm,
            "consistency": typer.consistency,
            "human_mode": typer.human_mode,
            "is_typing": typer.is_typing,
        },
        "style": style.get_settings(),
        "style_prompt": style.build_style_prompt(),
        "approval": {
            "require_approval": _is_approval_required(),
            "has_pending": _pending_text is not None,
            "pending_mode": _pending_mode,
            "pending_id": _pending_id if _pending_text else None,
            "pending_preview": (_pending_text[:200] + "...") if _pending_text and len(_pending_text) > 200 else _pending_text,
        },
        "active_window": get_active_window(),
    }


# ======================== WINDOW MANAGEMENT TOOLS ======================== #

@mcp.tool()
def get_active_window_info() -> dict:
    """
    Return the title and handle of the currently focused window.

    Useful for confirming which application will receive typed text.
    """
    return get_active_window()


@mcp.tool()
def focus_window_by_title(title: str) -> dict:
    """
    Find and focus a window whose title contains the given text (case-insensitive).

    Use this to target a specific application before typing. For example,
    focus_window_by_title("Google Docs") or focus_window_by_title("Notepad").

    Args:
        title: Partial window title to search for.

    Returns:
        Result with success status and matched window title.
    """
    result = focus_window(title)
    if result.get("success"):
        _log_action(f"Focused: {result.get('title', title)}")
    else:
        _log_action(f"Focus failed: {result.get('error', 'unknown error')}")
    return result


@mcp.tool()
def list_open_windows() -> dict:
    """
    List all visible windows with titles. Useful for finding the right
    window to focus before typing.
    """
    windows = list_windows()
    return {"count": len(windows), "windows": windows}


@mcp.tool()
def check_window(expected_title: Optional[str] = None) -> dict:
    """
    Verify which window is currently focused, optionally checking if it
    matches an expected title.

    Useful before typing to make sure the right app will receive input.

    Args:
        expected_title: Optional partial title to check against.

    Returns:
        Current window info and whether it matches the expected title.
    """
    if expected_title:
        return verify_window_focused(expected_title)
    return {"current_window": get_active_window()}


# ======================== STYLE PROFILE TOOLS ======================== #

@mcp.tool()
def start_calibration() -> dict:
    """
    Begin the style cloning questionnaire to create a custom writing profile.

    This starts an interactive calibration session. After calling this,
    use submit_calibration_answer() to respond to each question. After
    all questions are answered, a custom style profile will be generated.

    Returns:
        The first calibration question and progress indicator.
    """
    global calibration_session
    calibration_session = CalibrationSession()
    q = calibration_session.current_question
    _log_action("Calibration started")
    return {
        "message": "Calibration started! Answer each question by writing naturally in your own style.",
        "question": q["prompt"],
        "progress": calibration_session.progress,
    }


@mcp.tool()
def submit_calibration_answer(answer: str, profile_name: Optional[str] = None) -> dict:
    """
    Submit an answer to the current calibration question.

    Keep answering until calibration is complete. When the last question
    is answered, provide a profile_name to save the generated profile.

    Args:
        answer: Your written response to the current calibration prompt.
        profile_name: Name for the profile (only needed on the final question).

    Returns:
        Next question and progress, or the completed profile analysis.
    """
    global calibration_session

    if calibration_session is None:
        return {"error": "No calibration in progress. Call start_calibration() first."}

    if not answer or not answer.strip():
        return {"error": "Please provide a written answer."}

    next_q = calibration_session.submit_answer(answer)

    if not calibration_session.is_complete:
        _log_action(f"Calibration: answered {calibration_session.progress}")
        return {
            "question": next_q["prompt"],
            "progress": calibration_session.progress,
        }

    # Calibration complete — analyze and save
    try:
        analysis = calibration_session.analyze()
    except Exception as e:
        logger.error("Calibration analysis failed: %s", e)
        calibration_session = None
        return {"error": f"Analysis failed: {e}. Please try calibration again."}

    name = profile_name or "my_style"
    name = name.replace(" ", "_").lower()

    try:
        style.save_profile(name, analysis)
    except Exception as e:
        logger.error("Failed to save profile '%s': %s", name, e)
        return {"error": f"Profile analysis succeeded but save failed: {e}",
                "attributes": analysis["attributes"]}

    calibration_session = None
    _log_action(f"Profile '{name}' created from calibration")

    # Refresh GUI profiles if available
    if gui_instance:
        try:
            gui_instance.refresh_profiles()
        except Exception:
            pass

    return {
        "message": f"Calibration complete! Profile '{name}' saved.",
        "profile_name": name,
        "attributes": analysis["attributes"],
        "style_prompt_preview": analysis["style_prompt"][:300] + "...",
    }


@mcp.tool()
def list_style_profiles() -> dict:
    """List all saved custom writing style profiles."""
    profiles = style.list_profiles()
    return {"profiles": profiles, "count": len(profiles)}


@mcp.tool()
def delete_style_profile(name: str) -> dict:
    """
    Delete a saved style profile by name.

    Args:
        name: Name of the profile to delete.
    """
    if style.delete_profile(name):
        _log_action(f"Profile '{name}' deleted")
        if gui_instance:
            try:
                gui_instance.refresh_profiles()
            except Exception:
                pass
        return {"message": f"Profile '{name}' deleted.", "deleted": True}
    return {"message": f"Profile '{name}' not found.", "deleted": False}


# ======================== ANSWER QUEUE TOOLS ======================== #

@mcp.tool()
def load_answer_queue(answers: list[dict], use_paste: Optional[bool] = None) -> dict:
    """
    Load a set of answers into the typing queue for document filling.

    After loading, the user switches to their document (e.g. Google Docs)
    and uses hotkeys to type each answer at their cursor position:

        Ctrl+Alt+N  — Type next answer
        Ctrl+Alt+S  — Skip current answer
        Ctrl+Alt+X  — Stop typing / clear queue
        Ctrl+Alt+Z  — Undo last answer (delete what was typed)

    WORKFLOW:
    1. User sends you a screenshot/PDF of their assignment
    2. You read the questions and generate answers
    3. You call load_answer_queue() with the question/answer pairs
    4. User switches to their document
    5. User clicks where answer 1 should go, presses Ctrl+Shift+Space
    6. User clicks where answer 2 should go, presses Ctrl+Shift+Space
    7. Repeat until done

    Args:
        answers: List of dicts, each with 'question' (str) and 'answer' (str).
                 Example: [{"question": "What is 2+2?", "answer": "4"},
                           {"question": "Capital of France?", "answer": "Paris"}]
        use_paste: If True, use clipboard paste instead of character-by-character
                   typing. Faster but no human-like simulation. Default: False.

    Returns:
        Queue summary with count and instructions.
    """
    if not answers:
        return {"error": "No answers provided."}

    # Validate structure
    valid_answers = []
    for i, item in enumerate(answers):
        if not isinstance(item, dict):
            return {"error": f"Answer {i + 1} is not a dict. Each item needs 'question' and 'answer' keys."}
        answer_text = item.get("answer", "").strip()
        if not answer_text:
            continue  # Skip empty answers
        valid_answers.append(item)

    if not valid_answers:
        return {"error": "All answers were empty."}

    result = answer_queue.load(valid_answers, use_paste=use_paste or False)

    # Start hotkey listener if not already running
    if not hotkey_mgr.is_running:
        hotkey_mgr.start()
        result["hotkeys_started"] = True

    result["hotkeys"] = HOTKEY_LABELS
    _log_action(f"Queue loaded: {result['loaded']} answers")
    return result


@mcp.tool()
def queue_next_answer() -> dict:
    """
    Type the next answer from the queue at the current cursor position.

    This is the tool-call equivalent of pressing Ctrl+Shift+Space.
    The user can also use the hotkey directly from their document.

    Returns:
        Result with answer info and remaining count.
    """
    result = answer_queue.type_next()
    if result.get("typed_answer"):
        _log_action(f"Typed answer {result['typed_answer']} — "
                     f"{result['remaining']} remaining")
    return result


@mcp.tool()
def queue_skip_answer() -> dict:
    """
    Skip the current answer in the queue without typing it.

    Tool-call equivalent of pressing Ctrl+Shift+S.

    Returns:
        Info about what was skipped and what's next.
    """
    result = answer_queue.skip_current()
    if result.get("skipped_answer"):
        _log_action(f"Skipped answer {result['skipped_answer']}")
    return result


@mcp.tool()
def queue_undo_last() -> dict:
    """
    Undo the last typed answer by selecting and deleting it.

    Tool-call equivalent of pressing Ctrl+Shift+Z.

    Returns:
        Undo result.
    """
    result = answer_queue.undo_last()
    if result.get("undone_answer"):
        _log_action(f"Undid answer {result['undone_answer']}")
    return result


@mcp.tool()
def clear_answer_queue() -> dict:
    """
    Clear the answer queue entirely.

    Returns:
        How many items were cleared.
    """
    result = answer_queue.clear()
    _log_action(f"Queue cleared: {result.get('cleared', 0)} items")
    return result


@mcp.tool()
def get_queue_status() -> dict:
    """
    Get the current status of the answer queue.

    Shows total answers, how many have been typed, skipped, and
    what's coming next. Also shows all items with their status.

    Returns:
        Full queue status including per-item breakdown.
    """
    return answer_queue.get_status()


# ======================== DIAGNOSTICS ======================== #

@mcp.tool()
def health_check() -> dict:
    """
    Run a health check on all Claude Typer components.

    Checks dependency availability, clipboard access, display access,
    window management, and config status. Useful for troubleshooting
    when something isn't working.

    Returns:
        Health status for each component and any issues found.
    """
    typing_health = TypingEngine.check_dependencies()
    window_health = check_window_deps()
    hotkey_health = HotkeyManager.check_dependencies()

    active_window = get_active_window()

    all_issues = (typing_health["issues"] +
                  window_health["issues"] +
                  hotkey_health["issues"])

    overall = "healthy" if not all_issues else "degraded"

    _log_action(f"Health check: {overall} ({len(all_issues)} issues)")

    return {
        "status": overall,
        "typing_engine": typing_health,
        "window_manager": window_health,
        "hotkey_manager": {
            **hotkey_health,
            "listener_running": hotkey_mgr.is_running,
        },
        "answer_queue": answer_queue.get_status(),
        "active_window": active_window,
        "config_path": CONFIG_PATH,
        "log_path": LOG_PATH,
        "issues": all_issues,
        "hotkeys": HOTKEY_LABELS,
    }


@mcp.tool()
def get_action_log(count: Optional[int] = None) -> dict:
    """
    Get the recent action log — a rolling history of what Claude Typer
    has done. Useful for reviewing what happened.

    Args:
        count: Number of recent entries to return (default: all, max 50).

    Returns:
        List of recent action log entries with timestamps.
    """
    entries = list(_action_log)
    if count and count > 0:
        entries = entries[-count:]
    return {"entries": entries, "total": len(_action_log)}


# ------------------------------------------------------------------ #
#  GUI integration                                                     #
# ------------------------------------------------------------------ #

def _gui_settings_changed(settings: dict):
    """Callback when GUI sliders/toggles change."""
    t = settings.get("typing", {})
    typer.update_settings(
        wpm=t.get("wpm"),
        consistency=t.get("consistency"),
        human_mode=t.get("human_mode"),
    )
    s = settings.get("style", {})
    try:
        style.set_preset(s.get("preset"))
        style.set_grade_level(s.get("grade_level"))
        style.set_active_profile(s.get("active_profile"))
    except ValueError:
        pass

    # Persist approval setting from GUI
    a = settings.get("approval", {})
    if "require_approval" in a:
        cfg = load_config()
        cfg["approval"]["require_approval"] = a["require_approval"]
        save_config(cfg)


def launch_gui_thread():
    """Launch the settings GUI in a separate thread."""
    global gui_instance
    try:
        from gui import SettingsGUI
        gui_instance = SettingsGUI(
            on_settings_change=_gui_settings_changed,
            get_profiles=style.list_profiles,
        )
        gui_instance.refresh_profiles()

        # Show startup health in GUI
        health = TypingEngine.check_dependencies()
        if health["healthy"]:
            gui_instance.set_status("MCP server running — all systems OK", "#4ecca3")
        else:
            gui_instance.set_status(
                f"Running with issues: {', '.join(health['issues'][:2])}", "#ffaa00"
            )

        gui_instance.run()
    except ImportError:
        logger.info("tkinter not available — GUI disabled")
    except Exception as e:
        logger.error("GUI failed to start: %s", e)


# ------------------------------------------------------------------ #
#  Entry point                                                         #
# ------------------------------------------------------------------ #

def main():
    """Start the MCP server with optional GUI."""
    logger.info("Claude Typer starting...")

    # Run startup health check
    health = TypingEngine.check_dependencies()
    window_health = check_window_deps()
    hotkey_health = HotkeyManager.check_dependencies()
    all_issues = health["issues"] + window_health["issues"] + hotkey_health["issues"]
    if all_issues:
        for issue in all_issues:
            logger.warning("Startup issue: %s", issue)
    else:
        logger.info("All dependencies OK")

    # Start global hotkey listener
    if hotkey_mgr.start():
        logger.info("Hotkey listener active")
    else:
        logger.warning("Hotkey listener failed to start")

    # Launch GUI in background thread
    gui_thread = threading.Thread(target=launch_gui_thread, daemon=True)
    gui_thread.start()

    _log_action("Server started")

    # Run MCP server (stdio transport, blocks)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
