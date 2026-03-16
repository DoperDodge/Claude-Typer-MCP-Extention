# Claude Typer

A Windows MCP extension for Claude Desktop that lets Claude type text directly into any active application (Google Docs, Word, Notepad, browser, etc.) with human-like typing behavior and configurable writing style.

## Features

- **Human-like typing** — Simulates realistic keystroke timing with digraph acceleration, thinking pauses, speed drift, and natural variance
- **Configurable speed** — WPM slider (30–150) and consistency control
- **Clipboard paste** — Instant paste mode for large blocks of text
- **Keyboard shortcuts** — Send formatting commands (Ctrl+B, Ctrl+I, etc.) to any app
- **Writing style presets** — Intellectual, smart, concise, casual, professional, and more
- **Grade-level targeting** — Adjust output complexity from 1st grade to postgraduate
- **Style cloning** — Calibration questionnaire that learns your writing style
- **Settings GUI** — Live control panel with sliders, toggles, and profile management
- **Window targeting** — Find and focus specific application windows

## Quick Start

### 1. Install Python dependencies

```bash
cd claude-typer
pip install -r requirements.txt
```

### 2. Register with Claude Desktop

Add this to your Claude Desktop config file.

**Standard location:** `%APPDATA%\Claude\claude_desktop_config.json`

**Microsoft Store version:** Check under `%LOCALAPPDATA%\Packages\AnthropicPBC.claude_*\LocalCache\Roaming\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "claude-typer": {
      "command": "python",
      "args": ["C:\\full\\path\\to\\claude-typer\\server.py"]
    }
  }
}
```

> **Tip:** Use the full absolute path to `server.py`. Replace backslashes with double backslashes in JSON.

### 3. Restart Claude Desktop

Close and reopen Claude Desktop. You should see "Claude Typer" listed in the MCP tools menu (hammer icon). The settings GUI window will also appear.

## Usage Examples

Once connected, you can ask Claude things like:

- *"Type 'Hello, world!' into my Notepad window"*
- *"Focus Google Docs and type a paragraph about climate change"*
- *"Set typing speed to 60 WPM with high consistency"*
- *"Switch to the concise writing preset"*
- *"Start a style calibration session"*
- *"Paste this code block into VS Code"*
- *"Press Ctrl+B to toggle bold, then type 'Important'"*

## MCP Tools Reference

### Typing

| Tool | Description |
|------|-------------|
| `type_text(text)` | Type text character-by-character with current speed settings |
| `paste_text(text)` | Instant clipboard paste (Ctrl+V) |
| `press_keys(keys)` | Send keyboard shortcuts like `ctrl+b`, `enter`, `ctrl+shift+7` |

### Configuration

| Tool | Description |
|------|-------------|
| `configure_typing(wpm, consistency, human_mode)` | Adjust typing behavior |
| `configure_style(preset, grade_level, profile)` | Set writing style |
| `get_settings()` | View current configuration |

### Window Management

| Tool | Description |
|------|-------------|
| `get_active_window_info()` | See which window is focused |
| `focus_window_by_title(title)` | Focus a window by partial title match |
| `list_open_windows()` | List all visible windows |

### Style Profiles

| Tool | Description |
|------|-------------|
| `start_calibration()` | Begin style cloning questionnaire |
| `submit_calibration_answer(answer)` | Answer a calibration question |
| `list_style_profiles()` | List saved profiles |
| `delete_style_profile(name)` | Delete a profile |

## Settings GUI

The settings window launches automatically alongside the MCP server. It provides:

- **WPM slider** (30–150)
- **Consistency slider** (0.0–1.0)
- **Human-Like Mode toggle**
- **Style preset dropdown**
- **Grade level slider** (1–16)
- **Profile selector**
- **Status indicators**

Changes in the GUI are applied immediately and persisted to `config.json`.

## Human-Like Typing Mode

When enabled, the typing engine simulates realistic human behavior:

- **Digraph acceleration** — Common letter pairs (th, er, in, etc.) are typed faster
- **Word boundary pauses** — Small hesitation at the start of new words
- **Thinking pauses** — Occasional longer pauses mid-sentence
- **Sentence boundary pauses** — Natural pauses after periods and question marks
- **Speed drift** — WPM gradually fluctuates ±15% over time
- **Log-normal distribution** — Occasional longer pauses, rarely faster-than-normal bursts

## File Structure

```
claude-typer/
├── server.py              # MCP server entry point
├── typing_engine.py       # Keystroke simulation and timing
├── style_engine.py        # Writing style presets and profiles
├── calibration.py         # Style cloning questionnaire
├── gui.py                 # Settings GUI (tkinter)
├── window_manager.py      # Window detection and focusing
├── config.json            # Persisted settings
├── profiles/              # Custom style profiles
├── requirements.txt       # Python dependencies
└── README.md              # This file
```

## Troubleshooting

**Claude Desktop doesn't see the tools:**
- Verify the path in `claude_desktop_config.json` is correct and uses double backslashes
- Make sure Python is on your PATH, or use the full path to `python.exe`
- Restart Claude Desktop completely (check system tray)

**Typing goes to the wrong window:**
- Use `get_active_window_info()` to check which window is focused
- Use `focus_window_by_title()` to target the correct app before typing

**GUI doesn't appear:**
- The GUI runs in a background thread; it may take a moment to appear
- Check the console for error messages
- Ensure tkinter is installed (comes with standard Python)

**Microsoft Store version of Claude Desktop:**
- The config file path differs from the standard install
- Look in `%LOCALAPPDATA%\Packages\AnthropicPBC.claude_*\LocalCache\Roaming\Claude\`

## License

MIT
