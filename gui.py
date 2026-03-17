"""
Settings GUI — Tkinter-based control panel for Claude Typer.

Runs alongside the MCP server and provides real-time control over
typing behavior, writing style, and profile management.
"""

import json
import os
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from collections import deque
from typing import Callable, Optional

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULT_CONFIG = {
    "typing": {"wpm": 80, "consistency": 0.7, "human_mode": True},
    "style": {"preset": None, "grade_level": None, "active_profile": None},
    "approval": {"require_approval": True},
}


class SettingsGUI:
    """Tkinter settings window for Claude Typer."""

    def __init__(self, on_settings_change: Optional[Callable] = None,
                 get_profiles: Optional[Callable] = None):
        """
        Args:
            on_settings_change: Callback(settings_dict) when any setting changes.
            get_profiles: Callback() -> list[str] to get available profile names.
        """
        self._on_change = on_settings_change
        self._get_profiles = get_profiles or (lambda: [])

        self.root = tk.Tk()
        self.root.title("Claude Typer — Settings")
        self.root.geometry("440x850")
        self.root.resizable(True, True)
        self.root.minsize(420, 600)
        self.root.configure(bg="#1a1a2e")

        # Load persisted settings
        self._settings = self._load_config()

        # Action log
        self._action_log: deque = deque(maxlen=50)

        self._build_ui()
        self._apply_from_config()

    # ------------------------------------------------------------------ #
    #  UI construction                                                    #
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")

        # Color scheme
        bg = "#1a1a2e"
        fg = "#e0e0e0"
        accent = "#6c63ff"
        card_bg = "#16213e"

        style.configure("TFrame", background=bg)
        style.configure("Card.TFrame", background=card_bg)
        style.configure("TLabel", background=bg, foreground=fg, font=("Segoe UI", 10))
        style.configure("Header.TLabel", background=bg, foreground=accent,
                        font=("Segoe UI", 12, "bold"))
        style.configure("Value.TLabel", background=bg, foreground="#ffffff",
                        font=("Segoe UI", 11, "bold"))
        style.configure("TScale", background=bg, troughcolor=card_bg)
        style.configure("TCheckbutton", background=bg, foreground=fg,
                        font=("Segoe UI", 10))
        style.configure("TCombobox", font=("Segoe UI", 10))
        style.configure("Small.TLabel", background=bg, foreground="#888888",
                        font=("Segoe UI", 9))

        # Scrollable container
        canvas = tk.Canvas(self.root, bg=bg, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)

        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas_window = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Keep the inner frame width matched to the canvas width on resize
        def _on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind("<Configure>", _on_canvas_configure)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Enable mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        main = ttk.Frame(scroll_frame, padding=20)
        main.pack(fill="both", expand=True)

        # Title
        ttk.Label(main, text="⌨ Claude Typer", font=("Segoe UI", 16, "bold"),
                  foreground="#ffffff", background=bg).pack(pady=(0, 15))

        # ---- Typing Behavior ---- #
        ttk.Label(main, text="TYPING BEHAVIOR", style="Header.TLabel").pack(anchor="w")
        ttk.Separator(main, orient="horizontal").pack(fill="x", pady=(2, 8))

        # WPM
        wpm_frame = ttk.Frame(main)
        wpm_frame.pack(fill="x", pady=4)
        ttk.Label(wpm_frame, text="Speed (WPM)").pack(side="left")
        self.wpm_label = ttk.Label(wpm_frame, text="80", style="Value.TLabel")
        self.wpm_label.pack(side="right")

        self.wpm_var = tk.IntVar(value=80)
        self.wpm_slider = ttk.Scale(main, from_=30, to=150, variable=self.wpm_var,
                                     orient="horizontal", command=self._on_wpm_change)
        self.wpm_slider.pack(fill="x", pady=(0, 8))

        # Consistency
        cons_frame = ttk.Frame(main)
        cons_frame.pack(fill="x", pady=4)
        ttk.Label(cons_frame, text="Consistency").pack(side="left")
        self.cons_label = ttk.Label(cons_frame, text="0.70", style="Value.TLabel")
        self.cons_label.pack(side="right")

        self.cons_var = tk.DoubleVar(value=0.7)
        self.cons_slider = ttk.Scale(main, from_=0.0, to=1.0, variable=self.cons_var,
                                      orient="horizontal", command=self._on_cons_change)
        self.cons_slider.pack(fill="x", pady=(0, 8))

        # Human-like mode
        self.human_var = tk.BooleanVar(value=True)
        self.human_check = ttk.Checkbutton(
            main, text="Human-Like Mode", variable=self.human_var,
            command=self._on_setting_change
        )
        self.human_check.pack(anchor="w", pady=(0, 4))

        # Approval mode
        self.approval_var = tk.BooleanVar(value=True)
        self.approval_check = ttk.Checkbutton(
            main, text="Require Approval Before Typing", variable=self.approval_var,
            command=self._on_setting_change
        )
        self.approval_check.pack(anchor="w", pady=(0, 4))

        # Always on top
        self.ontop_var = tk.BooleanVar(value=False)
        self.ontop_check = ttk.Checkbutton(
            main, text="Always On Top", variable=self.ontop_var,
            command=self._on_topmost_change
        )
        self.ontop_check.pack(anchor="w", pady=(0, 15))

        # ---- Writing Style ---- #
        ttk.Label(main, text="WRITING STYLE", style="Header.TLabel").pack(anchor="w")
        ttk.Separator(main, orient="horizontal").pack(fill="x", pady=(2, 8))

        # Preset
        preset_frame = ttk.Frame(main)
        preset_frame.pack(fill="x", pady=4)
        ttk.Label(preset_frame, text="Preset").pack(side="left")

        presets = ["(none)", "intellectual", "smart", "concise", "basic",
                   "casual", "professional", "verbose"]
        self.preset_var = tk.StringVar(value="(none)")
        self.preset_combo = ttk.Combobox(preset_frame, textvariable=self.preset_var,
                                          values=presets, state="readonly", width=16)
        self.preset_combo.pack(side="right")
        self.preset_combo.bind("<<ComboboxSelected>>", lambda e: self._on_setting_change())

        # Grade Level
        grade_frame = ttk.Frame(main)
        grade_frame.pack(fill="x", pady=8)
        ttk.Label(grade_frame, text="Grade Level").pack(side="left")
        self.grade_label = ttk.Label(grade_frame, text="Off", style="Value.TLabel")
        self.grade_label.pack(side="right")

        self.grade_var = tk.IntVar(value=0)
        self.grade_slider = ttk.Scale(main, from_=0, to=16, variable=self.grade_var,
                                       orient="horizontal", command=self._on_grade_change)
        self.grade_slider.pack(fill="x", pady=(0, 8))

        # Profile
        profile_frame = ttk.Frame(main)
        profile_frame.pack(fill="x", pady=4)
        ttk.Label(profile_frame, text="Custom Profile").pack(side="left")

        self.profile_var = tk.StringVar(value="(none)")
        self.profile_combo = ttk.Combobox(profile_frame, textvariable=self.profile_var,
                                           values=["(none)"], state="readonly", width=16)
        self.profile_combo.pack(side="right")
        self.profile_combo.bind("<<ComboboxSelected>>", lambda e: self._on_setting_change())

        # ---- Status ---- #
        ttk.Label(main, text="STATUS", style="Header.TLabel").pack(anchor="w", pady=(15, 0))
        ttk.Separator(main, orient="horizontal").pack(fill="x", pady=(2, 8))

        self.status_label = ttk.Label(main, text="Starting...", foreground="#ffaa00")
        self.status_label.pack(anchor="w")

        self.window_label = ttk.Label(main, text="Active window: —", style="Small.TLabel")
        self.window_label.pack(anchor="w", pady=(4, 0))

        self.action_label = ttk.Label(main, text="Ready", foreground="#888888")
        self.action_label.pack(anchor="w", pady=(4, 0))

        # ---- Answer Queue ---- #
        ttk.Label(main, text="ANSWER QUEUE", style="Header.TLabel").pack(anchor="w", pady=(15, 0))
        ttk.Separator(main, orient="horizontal").pack(fill="x", pady=(2, 8))

        self.queue_status_label = ttk.Label(
            main, text="No queue loaded", foreground="#888888"
        )
        self.queue_status_label.pack(anchor="w")

        self.queue_progress_label = ttk.Label(
            main, text="", style="Small.TLabel"
        )
        self.queue_progress_label.pack(anchor="w", pady=(2, 0))

        self.queue_next_label = ttk.Label(
            main, text="", style="Small.TLabel"
        )
        self.queue_next_label.pack(anchor="w", pady=(2, 0))

        # Hotkey reference
        hotkey_frame = ttk.Frame(main)
        hotkey_frame.pack(fill="x", pady=(8, 0))

        ttk.Label(hotkey_frame, text="Hotkeys:", foreground="#6c63ff",
                  font=("Segoe UI", 9, "bold"),
                  background="#1a1a2e").pack(anchor="w")

        hotkey_ref = (
            "  Ctrl+Alt+N — Type next answer\n"
            "  Ctrl+Alt+S — Skip answer\n"
            "  Ctrl+Alt+X — Stop / Clear queue\n"
            "  Ctrl+Alt+Z — Undo last answer"
        )
        ttk.Label(hotkey_frame, text=hotkey_ref, style="Small.TLabel",
                  justify="left").pack(anchor="w")

        # ---- Action Log ---- #
        ttk.Label(main, text="ACTION LOG", style="Header.TLabel").pack(anchor="w", pady=(15, 0))
        ttk.Separator(main, orient="horizontal").pack(fill="x", pady=(2, 8))

        self.log_text = scrolledtext.ScrolledText(
            main, height=6, wrap=tk.WORD,
            bg="#0d1117", fg="#8b949e", insertbackground="#ffffff",
            font=("Consolas", 9), state="disabled",
            borderwidth=1, relief="solid",
        )
        self.log_text.pack(fill="x", pady=(0, 10))

        # ---- Window tracking ---- #
        self._update_window_label()

    # ------------------------------------------------------------------ #
    #  Event handlers                                                     #
    # ------------------------------------------------------------------ #

    def _on_wpm_change(self, val):
        v = int(float(val))
        self.wpm_label.configure(text=str(v))
        self._on_setting_change()

    def _on_cons_change(self, val):
        v = round(float(val), 2)
        self.cons_label.configure(text=f"{v:.2f}")
        self._on_setting_change()

    def _on_grade_change(self, val):
        v = int(float(val))
        if v == 0:
            self.grade_label.configure(text="Off")
        else:
            from style_engine import GRADE_LABELS
            self.grade_label.configure(text=GRADE_LABELS.get(v, f"Grade {v}"))
        self._on_setting_change()

    def _on_setting_change(self):
        """Collect all settings and persist + notify."""
        settings = self.get_settings()
        self._save_config(settings)
        if self._on_change:
            self._on_change(settings)

    def _on_topmost_change(self):
        """Toggle always-on-top."""
        self.root.attributes("-topmost", self.ontop_var.get())

    def _update_window_label(self):
        """Periodically poll the active window and update the label."""
        try:
            from window_manager import get_active_window
            win = get_active_window()
            title = win.get("title", "unknown")
            if title and title != self.root.title():
                display = title if len(title) <= 50 else title[:47] + "..."
                self.window_label.configure(text=f"Active window: {display}")
        except Exception:
            pass
        # Poll every 2 seconds
        self.root.after(2000, self._update_window_label)

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

    def get_settings(self) -> dict:
        preset = self.preset_var.get()
        profile = self.profile_var.get()
        grade = int(self.grade_var.get())

        return {
            "typing": {
                "wpm": int(self.wpm_var.get()),
                "consistency": round(float(self.cons_var.get()), 2),
                "human_mode": self.human_var.get(),
            },
            "style": {
                "preset": preset if preset != "(none)" else None,
                "grade_level": grade if grade > 0 else None,
                "active_profile": profile if profile != "(none)" else None,
            },
            "approval": {
                "require_approval": self.approval_var.get(),
            },
        }

    def set_status(self, text: str, color: str = "#4ecca3"):
        """Update the status label from another thread."""
        self.root.after(0, lambda: self.status_label.configure(text=text, foreground=color))

    def set_action(self, text: str):
        """Update the last-action label and append to log from another thread."""
        def _update():
            timestamp = time.strftime("%H:%M:%S")
            self.action_label.configure(text=text)

            # Append to log
            self.log_text.configure(state="normal")
            self.log_text.insert(tk.END, f"[{timestamp}] {text}\n")
            self.log_text.see(tk.END)
            self.log_text.configure(state="disabled")

        self.root.after(0, _update)

    def refresh_profiles(self):
        """Reload profile list from disk."""
        profiles = ["(none)"] + self._get_profiles()
        current = self.profile_var.get()
        self.profile_combo.configure(values=profiles)
        if current not in profiles:
            self.profile_var.set("(none)")

    def update_queue_display(self, status: dict):
        """Update the answer queue display from another thread."""
        def _update():
            if not status.get("loaded"):
                self.queue_status_label.configure(
                    text="No queue loaded", foreground="#888888"
                )
                self.queue_progress_label.configure(text="")
                self.queue_next_label.configure(text="")
                return

            total = status.get("total", 0)
            completed = status.get("completed", 0)
            skipped = status.get("skipped", 0)
            remaining = status.get("remaining", 0)

            if status.get("queue_complete"):
                self.queue_status_label.configure(
                    text=f"Complete! {completed} typed, {skipped} skipped",
                    foreground="#4ecca3"
                )
                self.queue_progress_label.configure(text="")
                self.queue_next_label.configure(text="")
            else:
                current = status.get("current", 1)
                self.queue_status_label.configure(
                    text=f"Answer {current} of {total} — {remaining} remaining",
                    foreground="#ffaa00"
                )

                mode = status.get("mode", "type")
                self.queue_progress_label.configure(
                    text=f"Mode: {mode} | Typed: {completed} | Skipped: {skipped}"
                )

                next_q = status.get("current_question", "")
                if next_q:
                    display_q = next_q if len(next_q) <= 55 else next_q[:52] + "..."
                    self.queue_next_label.configure(text=f"Next: {display_q}")
                else:
                    self.queue_next_label.configure(text="")

        self.root.after(0, _update)

    def run(self):
        """Start the GUI event loop (blocks)."""
        self.root.mainloop()

    def run_nonblocking(self):
        """Run one iteration of the event loop (call from async loop)."""
        try:
            self.root.update()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ #
    #  Config persistence                                                 #
    # ------------------------------------------------------------------ #

    def _load_config(self) -> dict:
        cfg = {}
        if os.path.isfile(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r') as f:
                    cfg = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        # Migrate missing keys
        for section, defaults in DEFAULT_CONFIG.items():
            if section not in cfg:
                cfg[section] = dict(defaults)
            elif isinstance(defaults, dict):
                for key, val in defaults.items():
                    if key not in cfg[section]:
                        cfg[section][key] = val

        return cfg

    def _save_config(self, settings: dict):
        try:
            with open(CONFIG_PATH, 'w') as f:
                json.dump(settings, f, indent=2)
        except IOError:
            pass

    def _apply_from_config(self):
        """Set GUI widgets from loaded config."""
        t = self._settings.get("typing", {})
        s = self._settings.get("style", {})
        a = self._settings.get("approval", {})

        self.wpm_var.set(t.get("wpm", 80))
        self.wpm_label.configure(text=str(t.get("wpm", 80)))

        self.cons_var.set(t.get("consistency", 0.7))
        self.cons_label.configure(text=f"{t.get('consistency', 0.7):.2f}")

        self.human_var.set(t.get("human_mode", True))

        self.approval_var.set(a.get("require_approval", True))

        preset = s.get("preset")
        self.preset_var.set(preset if preset else "(none)")

        grade = s.get("grade_level")
        self.grade_var.set(grade if grade else 0)
        self._on_grade_change(grade if grade else 0)

        profile = s.get("active_profile")
        self.profile_var.set(profile if profile else "(none)")
