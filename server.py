"""
Claude Typer — MCP Server

A local MCP server that gives Claude the ability to type text into any
active Windows application with human-like typing behavior and
configurable writing style.

Communicates with Claude Desktop via stdio transport.
"""

import asyncio
import json
import os
import sys
import threading
from typing import Optional

from mcp.server.fastmcp import FastMCP

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from typing_engine import TypingEngine
from style_engine import StyleEngine
from calibration import CalibrationSession
from window_manager import get_active_window, focus_window, list_windows

# ------------------------------------------------------------------ #
#  Initialize components                                               #
# ------------------------------------------------------------------ #

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

def load_config() -> dict:
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "typing": {"wpm": 80, "consistency": 0.7, "human_mode": True},
        "style": {"preset": None, "grade_level": None, "active_profile": None},
    }

def save_config(settings: dict):
    try:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(settings, f, indent=2)
    except IOError:
        pass

# Load config and initialize engines
config = load_config()

typer = TypingEngine(
    wpm=config["typing"]["wpm"],
    consistency=config["typing"]["consistency"],
    human_mode=config["typing"]["human_mode"],
)

style = StyleEngine()
if config["style"].get("preset"):
    style.set_preset(config["style"]["preset"])
if config["style"].get("grade_level"):
    style.set_grade_level(config["style"]["grade_level"])
if config["style"].get("active_profile"):
    try:
        style.set_active_profile(config["style"]["active_profile"])
    except ValueError:
        pass

# Active calibration session (one at a time)
calibration_session: Optional[CalibrationSession] = None

# GUI reference (launched in separate thread if available)
gui_instance = None

# ------------------------------------------------------------------ #
#  MCP Server                                                          #
# ------------------------------------------------------------------ #

mcp = FastMCP("Claude Typer")

# ======================== TYPING TOOLS ======================== #

@mcp.tool()
def type_text(text: str) -> dict:
    """
    Type text character-by-character into the currently active window.

    Uses the configured typing speed (WPM), consistency, and human-like
    mode settings to simulate realistic typing. Make sure the target
    application window is focused before calling this.

    Args:
        text: The text to type into the active window.

    Returns:
        Summary with chars typed, total, and elapsed time.
    """
    _update_gui_action(f"Typing {len(text)} chars...")
    result = typer.type_text(text)
    _update_gui_action(f"Typed {result['typed']} chars in {result['elapsed_s']}s")
    return result


@mcp.tool()
def paste_text(text: str) -> dict:
    """
    Instantly paste text into the active window via clipboard (Ctrl+V).

    This is much faster than character-by-character typing. Use for large
    blocks of text where human-like simulation isn't needed. The original
    clipboard contents are preserved and restored afterward.

    Args:
        text: The text to paste.

    Returns:
        Summary with paste status and text length.
    """
    _update_gui_action(f"Pasting {len(text)} chars...")
    result = typer.paste_text(text)
    _update_gui_action("Paste complete")
    return result


@mcp.tool()
def press_keys(keys: str) -> dict:
    """
    Send a keyboard shortcut to the active window.

    Use for formatting and navigation in apps like Google Docs, Word, etc.
    Keys are specified as '+' separated modifiers and key names.

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
    _update_gui_action(f"Pressing {keys}")
    result = typer.press_keys(keys)
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

    # Persist
    cfg = load_config()
    cfg["typing"] = updated
    save_config(cfg)

    _update_gui_action(f"Typing config updated: {updated}")
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
        return {"error": str(e)}

    settings = style.get_settings()

    # Persist
    cfg = load_config()
    cfg["style"] = {
        "preset": style.preset,
        "grade_level": style.grade_level,
        "active_profile": style.active_profile,
    }
    save_config(cfg)

    _update_gui_action(f"Style updated: {settings}")
    return {"message": "Style settings updated", "settings": settings}


@mcp.tool()
def get_settings() -> dict:
    """
    Return the current typing behavior and writing style configuration.
    """
    return {
        "typing": {
            "wpm": typer.wpm,
            "consistency": typer.consistency,
            "human_mode": typer.human_mode,
        },
        "style": style.get_settings(),
        "style_prompt": style.build_style_prompt(),
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
        _update_gui_action(f"Focused: {result.get('title', title)}")
    return result


@mcp.tool()
def list_open_windows() -> dict:
    """
    List all visible windows with titles. Useful for finding the right
    window to focus before typing.
    """
    windows = list_windows()
    return {"count": len(windows), "windows": windows}


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

    next_q = calibration_session.submit_answer(answer)

    if not calibration_session.is_complete:
        return {
            "question": next_q["prompt"],
            "progress": calibration_session.progress,
        }

    # Calibration complete — analyze and save
    analysis = calibration_session.analyze()

    name = profile_name or "my_style"
    name = name.replace(" ", "_").lower()
    style.save_profile(name, analysis)

    calibration_session = None
    _update_gui_action(f"Profile '{name}' created")

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
        return {"message": f"Profile '{name}' deleted.", "deleted": True}
    return {"message": f"Profile '{name}' not found.", "deleted": False}


# ------------------------------------------------------------------ #
#  GUI integration                                                     #
# ------------------------------------------------------------------ #

def _update_gui_action(text: str):
    """Safely update GUI action label if GUI is running."""
    global gui_instance
    if gui_instance:
        try:
            gui_instance.set_action(text)
        except Exception:
            pass


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
        gui_instance.run()
    except Exception as e:
        print(f"[Claude Typer] GUI failed to start: {e}", file=sys.stderr)


# ------------------------------------------------------------------ #
#  Entry point                                                         #
# ------------------------------------------------------------------ #

def main():
    """Start the MCP server with optional GUI."""
    # Launch GUI in background thread
    gui_thread = threading.Thread(target=launch_gui_thread, daemon=True)
    gui_thread.start()

    # Run MCP server (stdio transport, blocks)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
