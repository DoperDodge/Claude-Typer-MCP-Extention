"""
Style Engine — Writing style presets, grade-level targeting, and custom profiles.

Manages style configuration and generates system prompt modifiers that shape
how Claude writes text before it's typed.
"""

import json
import os
from typing import Optional

PROFILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")

# ------------------------------------------------------------------ #
#  Preset definitions                                                  #
# ------------------------------------------------------------------ #

PRESETS = {
    "intellectual": (
        "Write in a sophisticated, intellectual style. Use advanced vocabulary, "
        "complex sentence structures, and reference concepts, frameworks, and ideas. "
        "Assume the reader is well-read and appreciates nuance and depth."
    ),
    "smart": (
        "Write in a clear, articulate, well-reasoned style. Use precise language "
        "without being pretentious. Be thoughtful and structured, but accessible."
    ),
    "concise": (
        "Write with minimal words. Be direct. No filler, no fluff, no hedging. "
        "Every sentence should carry information. Prefer short sentences."
    ),
    "basic": (
        "Write with simple vocabulary and short sentences. Be straightforward "
        "and easy to understand. Avoid jargon or complex ideas."
    ),
    "casual": (
        "Write in a relaxed, conversational tone. Use contractions, informal "
        "phrasing, and a friendly voice. Write like you're texting a friend."
    ),
    "professional": (
        "Write in a formal but approachable professional tone. Business-appropriate "
        "language, well-structured, clear. Suitable for workplace communications."
    ),
    "verbose": (
        "Write in a detailed, thorough style. Elaborate on points, explore tangents, "
        "and provide rich context. Don't shy away from longer explanations."
    ),
}

GRADE_LABELS = {
    1: "1st grade", 2: "2nd grade", 3: "3rd grade", 4: "4th grade",
    5: "5th grade", 6: "6th grade", 7: "7th grade", 8: "8th grade",
    9: "9th grade (Freshman)", 10: "10th grade (Sophomore)",
    11: "11th grade (Junior)", 12: "12th grade (Senior)",
    13: "College Freshman", 14: "College Sophomore",
    15: "College Junior", 16: "College Senior / Postgraduate",
}


class StyleEngine:
    """Manages writing style configuration and prompt generation."""

    def __init__(self):
        self.preset: Optional[str] = None
        self.grade_level: Optional[int] = None
        self.active_profile: Optional[str] = None
        self._profiles_cache: dict = {}

        os.makedirs(PROFILES_DIR, exist_ok=True)

    # ------------------------------------------------------------------ #
    #  Configuration                                                      #
    # ------------------------------------------------------------------ #

    def set_preset(self, preset: Optional[str]):
        if preset and preset not in PRESETS:
            raise ValueError(f"Unknown preset '{preset}'. Available: {list(PRESETS.keys())}")
        self.preset = preset

    def set_grade_level(self, level: Optional[int]):
        if level is not None:
            level = max(1, min(16, level))
        self.grade_level = level

    def set_active_profile(self, name: Optional[str]):
        if name and not self.profile_exists(name):
            raise ValueError(f"Profile '{name}' not found.")
        self.active_profile = name

    def get_settings(self) -> dict:
        return {
            "preset": self.preset,
            "grade_level": self.grade_level,
            "grade_label": GRADE_LABELS.get(self.grade_level) if self.grade_level else None,
            "active_profile": self.active_profile,
            "available_presets": list(PRESETS.keys()),
        }

    # ------------------------------------------------------------------ #
    #  System prompt generation                                           #
    # ------------------------------------------------------------------ #

    def build_style_prompt(self) -> Optional[str]:
        """
        Build a system prompt modifier from the current style settings.
        Returns None if no style is configured.
        """
        parts = []

        # Custom profile takes priority for base style
        if self.active_profile:
            profile = self.load_profile(self.active_profile)
            if profile and "style_prompt" in profile:
                parts.append(profile["style_prompt"])

        # Preset (if no profile, or can layer on top)
        if self.preset and not self.active_profile:
            parts.append(PRESETS[self.preset])

        # Grade level modifier
        if self.grade_level:
            label = GRADE_LABELS.get(self.grade_level, f"grade {self.grade_level}")
            parts.append(
                f"Target a {label} reading level. Adjust vocabulary complexity, "
                f"sentence length, and concept sophistication accordingly."
            )

        if not parts:
            return None

        return "WRITING STYLE INSTRUCTIONS:\n" + "\n".join(parts)

    # ------------------------------------------------------------------ #
    #  Profile management                                                 #
    # ------------------------------------------------------------------ #

    def list_profiles(self) -> list[str]:
        """List names of all saved profiles."""
        profiles = []
        for fname in os.listdir(PROFILES_DIR):
            if fname.endswith(".json"):
                profiles.append(fname[:-5])  # Strip .json
        return sorted(profiles)

    def profile_exists(self, name: str) -> bool:
        return os.path.isfile(os.path.join(PROFILES_DIR, f"{name}.json"))

    def save_profile(self, name: str, data: dict):
        """Save a profile to disk."""
        path = os.path.join(PROFILES_DIR, f"{name}.json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self._profiles_cache[name] = data

    def load_profile(self, name: str) -> Optional[dict]:
        """Load a profile from disk."""
        if name in self._profiles_cache:
            return self._profiles_cache[name]

        path = os.path.join(PROFILES_DIR, f"{name}.json")
        if not os.path.isfile(path):
            return None

        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self._profiles_cache[name] = data
        return data

    def delete_profile(self, name: str) -> bool:
        """Delete a profile. Returns True if deleted."""
        path = os.path.join(PROFILES_DIR, f"{name}.json")
        if os.path.isfile(path):
            os.remove(path)
            self._profiles_cache.pop(name, None)
            if self.active_profile == name:
                self.active_profile = None
            return True
        return False

    def export_profile(self, name: str) -> Optional[str]:
        """Export a profile as a JSON string."""
        data = self.load_profile(name)
        if data:
            return json.dumps(data, indent=2, ensure_ascii=False)
        return None

    def import_profile(self, name: str, json_str: str):
        """Import a profile from a JSON string."""
        data = json.loads(json_str)
        self.save_profile(name, data)
