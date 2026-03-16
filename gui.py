"""
Settings GUI — Tkinter-based control panel for Claude Typer.

Runs alongside the MCP server and provides real-time control over
typing behavior, writing style, and profile management.
"""

import json
import os
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable, Optional

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


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
        self.root.geometry("420x620")
        self.root.resizable(False, False)
        self.root.configure(bg="#1a1a2e")

        # Load persisted settings
        self._settings = self._load_config()

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

        main = ttk.Frame(self.root, padding=20)
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
        self.human_check.pack(anchor="w", pady=(0, 15))

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

        self.grade_var = tk.IntVar(value=0)  # 0 = off
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

        self.status_label = ttk.Label(main, text="MCP server running", foreground="#4ecca3")
        self.status_label.pack(anchor="w")

        self.action_label = ttk.Label(main, text="Ready", foreground="#888888")
        self.action_label.pack(anchor="w")

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
            }
        }

    def set_status(self, text: str, color: str = "#4ecca3"):
        """Update the status label from another thread."""
        self.root.after(0, lambda: self.status_label.configure(text=text, foreground=color))

    def set_action(self, text: str):
        """Update the last-action label from another thread."""
        self.root.after(0, lambda: self.action_label.configure(text=text))

    def refresh_profiles(self):
        """Reload profile list from disk."""
        profiles = ["(none)"] + self._get_profiles()
        current = self.profile_var.get()
        self.profile_combo.configure(values=profiles)
        if current not in profiles:
            self.profile_var.set("(none)")

    def run(self):
        """Start the GUI event loop (blocks)."""
        self.root.mainloop()

    def run_nonblocking(self):
        """Run one iteration of the event loop (call from async loop)."""
        try:
            self.root.update()
        except tk.TclError:
            pass  # Window was closed

    # ------------------------------------------------------------------ #
    #  Config persistence                                                 #
    # ------------------------------------------------------------------ #

    def _load_config(self) -> dict:
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

        self.wpm_var.set(t.get("wpm", 80))
        self.wpm_label.configure(text=str(t.get("wpm", 80)))

        self.cons_var.set(t.get("consistency", 0.7))
        self.cons_label.configure(text=f"{t.get('consistency', 0.7):.2f}")

        self.human_var.set(t.get("human_mode", True))

        preset = s.get("preset")
        self.preset_var.set(preset if preset else "(none)")

        grade = s.get("grade_level")
        self.grade_var.set(grade if grade else 0)
        self._on_grade_change(grade if grade else 0)

        profile = s.get("active_profile")
        self.profile_var.set(profile if profile else "(none)")
