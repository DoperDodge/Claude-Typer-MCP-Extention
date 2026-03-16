"""
Calibration — Style cloning questionnaire and analysis.

Walks the user through writing prompts, collects their samples,
analyzes style attributes, and generates a style profile.
"""

import re
from typing import Optional

CALIBRATION_QUESTIONS = [
    {
        "id": "daily",
        "prompt": "Write a few sentences about how your day has been (or a typical day). Just write naturally.",
    },
    {
        "id": "explain",
        "prompt": "How would you explain what a black hole is to a friend in casual conversation?",
    },
    {
        "id": "email_decline",
        "prompt": "Write a short email politely declining a meeting invitation you can't attend.",
    },
    {
        "id": "favorite_place",
        "prompt": "Describe your favorite place — could be a room, a city, a spot in nature. A few sentences is fine.",
    },
    {
        "id": "casual_reply",
        "prompt": 'Respond casually to this message from a coworker: "Hey, did you see the announcement about the new project? Thoughts?"',
    },
    {
        "id": "opinion",
        "prompt": "Write a short opinion on whether remote work is better than in-office work.",
    },
    {
        "id": "freewrite",
        "prompt": "Write anything you want — a paragraph about whatever's on your mind. This is just to capture your natural flow.",
    },
]


class CalibrationSession:
    """Manages a single calibration session."""

    def __init__(self):
        self.answers: dict[str, str] = {}
        self._current_index = 0

    @property
    def is_complete(self) -> bool:
        return self._current_index >= len(CALIBRATION_QUESTIONS)

    @property
    def current_question(self) -> Optional[dict]:
        if self.is_complete:
            return None
        return CALIBRATION_QUESTIONS[self._current_index]

    @property
    def progress(self) -> str:
        return f"{self._current_index + 1}/{len(CALIBRATION_QUESTIONS)}"

    def submit_answer(self, answer: str) -> Optional[dict]:
        """
        Record an answer to the current question.
        Returns the next question, or None if calibration is complete.
        """
        q = self.current_question
        if q is None:
            return None

        self.answers[q["id"]] = answer.strip()
        self._current_index += 1

        return self.current_question

    def analyze(self) -> dict:
        """
        Analyze collected writing samples and extract style attributes.
        Returns a dict of style metrics and a generated style prompt.
        """
        all_text = " ".join(self.answers.values())
        sentences = _split_sentences(all_text)
        words = all_text.split()

        # --- Metrics ---
        avg_sentence_len = len(words) / max(len(sentences), 1)

        # Contraction frequency
        contraction_pattern = r"\b\w+'\w+\b"  # e.g. don't, it's, we're
        contractions = len(re.findall(contraction_pattern, all_text))
        contraction_rate = contractions / max(len(words), 1)

        # Vocabulary complexity (rough: avg word length as proxy)
        avg_word_len = sum(len(w.strip(".,!?;:\"'()")) for w in words) / max(len(words), 1)

        # Punctuation style
        em_dashes = all_text.count('—') + all_text.count('--')
        parentheticals = all_text.count('(')
        semicolons = all_text.count(';')
        exclamations = all_text.count('!')

        # Starts with conjunctions
        conjunction_starts = sum(
            1 for s in sentences
            if s.strip().split()[0].lower() in ('and', 'but', 'so', 'or', 'yet')
        ) if sentences else 0
        conjunction_rate = conjunction_starts / max(len(sentences), 1)

        # Rhetorical questions
        questions = sum(1 for s in sentences if s.strip().endswith('?'))
        question_rate = questions / max(len(sentences), 1)

        # Formality score (0 = very casual, 1 = very formal)
        formality = _estimate_formality(all_text, contraction_rate, avg_word_len)

        # Paragraph length (from freewrite and longer answers)
        long_answers = [a for a in self.answers.values() if len(a.split()) > 20]
        avg_para_words = (
            sum(len(a.split()) for a in long_answers) / max(len(long_answers), 1)
        )

        attributes = {
            "avg_sentence_length": round(avg_sentence_len, 1),
            "avg_word_length": round(avg_word_len, 1),
            "contraction_rate": round(contraction_rate, 3),
            "formality": round(formality, 2),
            "em_dashes_per_100w": round(em_dashes / max(len(words), 1) * 100, 2),
            "parentheticals_per_100w": round(parentheticals / max(len(words), 1) * 100, 2),
            "semicolons_per_100w": round(semicolons / max(len(words), 1) * 100, 2),
            "exclamation_rate": round(exclamations / max(len(sentences), 1), 3),
            "conjunction_start_rate": round(conjunction_rate, 3),
            "rhetorical_question_rate": round(question_rate, 3),
            "avg_paragraph_words": round(avg_para_words, 1),
        }

        # Generate the style prompt
        style_prompt = _build_style_prompt(attributes)

        return {
            "attributes": attributes,
            "style_prompt": style_prompt,
            "samples": self.answers,
        }


# ------------------------------------------------------------------ #
#  Analysis helpers                                                    #
# ------------------------------------------------------------------ #

def _split_sentences(text: str) -> list[str]:
    """Rough sentence splitting."""
    # Split on sentence-ending punctuation followed by space or end
    parts = re.split(r'(?<=[.!?])\s+', text)
    return [p.strip() for p in parts if p.strip()]


def _estimate_formality(text: str, contraction_rate: float, avg_word_len: float) -> float:
    """
    Rough formality score from 0 (very casual) to 1 (very formal).
    """
    score = 0.5  # Start neutral

    # Contractions reduce formality
    score -= contraction_rate * 3.0  # Heavy contractions = casual

    # Longer words = more formal
    if avg_word_len > 5.5:
        score += 0.15
    elif avg_word_len < 4.0:
        score -= 0.15

    # Exclamation marks reduce formality
    excl_rate = text.count('!') / max(len(text.split()), 1)
    score -= excl_rate * 2.0

    # Slang/casual markers
    casual_markers = ['lol', 'haha', 'gonna', 'wanna', 'kinda', 'tbh', 'imo', 'ngl']
    text_lower = text.lower()
    for marker in casual_markers:
        if marker in text_lower:
            score -= 0.05

    return max(0.0, min(1.0, score))


def _build_style_prompt(attrs: dict) -> str:
    """Generate a natural-language style prompt from extracted attributes."""
    parts = ["Mimic the following writing style closely:"]

    # Sentence length
    sl = attrs["avg_sentence_length"]
    if sl < 10:
        parts.append("- Use short, punchy sentences (averaging under 10 words).")
    elif sl < 16:
        parts.append("- Use moderate sentence lengths (around 12-16 words on average).")
    else:
        parts.append("- Use longer, more complex sentences (averaging 16+ words).")

    # Formality
    f = attrs["formality"]
    if f < 0.3:
        parts.append("- Tone is casual and informal. Write like you're talking to a friend.")
    elif f < 0.6:
        parts.append("- Tone is balanced — conversational but not sloppy.")
    else:
        parts.append("- Tone is formal and polished. Avoid casual phrasing.")

    # Contractions
    cr = attrs["contraction_rate"]
    if cr > 0.04:
        parts.append("- Use contractions freely (don't, it's, we're, etc.).")
    elif cr > 0.01:
        parts.append("- Use contractions occasionally but not excessively.")
    else:
        parts.append("- Avoid contractions. Write out 'do not', 'it is', etc.")

    # Vocabulary
    wl = attrs["avg_word_length"]
    if wl > 5.5:
        parts.append("- Use sophisticated, precise vocabulary.")
    elif wl < 4.2:
        parts.append("- Keep vocabulary simple and everyday.")
    else:
        parts.append("- Use clear, accessible vocabulary without dumbing things down.")

    # Punctuation style
    if attrs["em_dashes_per_100w"] > 1.0:
        parts.append("- Use em-dashes for asides and emphasis.")
    if attrs["parentheticals_per_100w"] > 1.0:
        parts.append("- Use parenthetical asides when adding context.")
    if attrs["semicolons_per_100w"] > 0.5:
        parts.append("- Use semicolons to connect related thoughts.")

    # Sentence starters
    if attrs["conjunction_start_rate"] > 0.15:
        parts.append("- Occasionally start sentences with 'And', 'But', or 'So'.")

    # Rhetorical questions
    if attrs["rhetorical_question_rate"] > 0.1:
        parts.append("- Sprinkle in rhetorical questions for engagement.")

    # Exclamation
    if attrs["exclamation_rate"] > 0.15:
        parts.append("- Use exclamation marks for emphasis and energy.")
    elif attrs["exclamation_rate"] < 0.03:
        parts.append("- Rarely use exclamation marks.")

    return "\n".join(parts)
