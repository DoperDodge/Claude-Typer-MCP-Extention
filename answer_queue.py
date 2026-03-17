"""
Answer Queue — Ordered queue of answers for document filling.

Manages a list of question/answer pairs that can be typed into a document
one at a time using hotkeys. Supports next, skip, undo, and clear.
"""

import logging
import threading
import time
from typing import Optional, Callable

logger = logging.getLogger("claude-typer.queue")


class AnswerItem:
    """A single question/answer pair in the queue."""

    def __init__(self, question: str, answer: str, index: int):
        self.question = question
        self.answer = answer
        self.index = index  # 1-based position
        self.typed = False
        self.skipped = False
        self.typed_length = 0  # how many chars were actually typed


class AnswerQueue:
    """
    Manages an ordered queue of answers to be typed into a document.

    Works with the typing engine to type answers one at a time,
    controlled by hotkeys or tool calls.
    """

    def __init__(self, typing_engine, on_status_change: Optional[Callable] = None):
        """
        Args:
            typing_engine: TypingEngine instance for typing/pasting text.
            on_status_change: Optional callback(status_dict) fired when queue state changes.
        """
        self._typer = typing_engine
        self._on_status = on_status_change

        self._items: list[AnswerItem] = []
        self._current_index: int = 0  # index into _items
        self._lock = threading.RLock()

        # Track last typed answer for undo
        self._last_typed_text: Optional[str] = None
        self._last_typed_length: int = 0

        # Use paste mode for answers (faster, more reliable for long text)
        self.use_paste_mode: bool = False

    # ------------------------------------------------------------------ #
    #  Queue management                                                   #
    # ------------------------------------------------------------------ #

    def load(self, answers: list[dict], use_paste: bool = False) -> dict:
        """
        Load a new set of answers into the queue.

        Args:
            answers: List of dicts with 'question' and 'answer' keys.
            use_paste: If True, use clipboard paste instead of typing.

        Returns:
            Summary of loaded queue.
        """
        with self._lock:
            self._items = []
            for i, item in enumerate(answers):
                question = item.get("question", f"Question {i + 1}")
                answer = item.get("answer", "")
                if answer.strip():
                    self._items.append(AnswerItem(question, answer, i + 1))

            self._current_index = 0
            self._last_typed_text = None
            self._last_typed_length = 0
            self.use_paste_mode = use_paste

        self._notify_status()

        logger.info("Queue loaded: %d answers", len(self._items))
        return {
            "loaded": len(self._items),
            "total_chars": sum(len(item.answer) for item in self._items),
            "mode": "paste" if use_paste else "type",
            "message": f"Loaded {len(self._items)} answers. "
                       f"Switch to your document and press Ctrl+Shift+Space to type the first answer.",
        }

    def type_next(self) -> dict:
        """
        Type the next answer in the queue at the current cursor position.

        Returns:
            Result with answer info and typing status.
        """
        with self._lock:
            item = self._get_current()
            if item is None:
                return {"error": "Queue is empty or all answers have been typed.",
                        "queue_complete": True}

            answer_text = item.answer

        # Type or paste (outside lock so we don't block)
        logger.info("Typing answer %d/%d (%d chars)",
                     item.index, len(self._items), len(answer_text))

        if self.use_paste_mode:
            result = self._typer.paste_text(answer_text)
            success = result.get("pasted", False)
        else:
            result = self._typer.type_text(answer_text)
            success = not result.get("error") and not result.get("cancelled", False)

        with self._lock:
            if success:
                item.typed = True
                item.typed_length = len(answer_text)
                self._last_typed_text = answer_text
                self._last_typed_length = len(answer_text)
                self._current_index += 1

                remaining = len(self._items) - self._current_index
                next_item = self._get_current()

        # Notify and return OUTSIDE the lock to avoid deadlock
        # (_notify_status -> get_status also acquires self._lock)
        self._notify_status()

        if success:
            return {
                "typed_answer": item.index,
                "question": item.question,
                "chars": len(answer_text),
                "remaining": remaining,
                "queue_complete": remaining == 0,
                "next_question": next_item.question if next_item else None,
                "result": result,
            }
        else:
            return {
                "error": f"Failed to type answer {item.index}",
                "answer_index": item.index,
                "result": result,
            }

    def skip_current(self) -> dict:
        """
        Skip the current answer without typing it.

        Returns:
            Info about what was skipped and what's next.
        """
        with self._lock:
            item = self._get_current()
            if item is None:
                return {"error": "Nothing to skip — queue is empty or complete."}

            item.skipped = True
            self._current_index += 1

            remaining = len(self._items) - self._current_index
            next_item = self._get_current()

        self._notify_status()

        logger.info("Skipped answer %d/%d", item.index, len(self._items))
        return {
            "skipped_answer": item.index,
            "skipped_question": item.question,
            "remaining": remaining,
            "next_question": next_item.question if next_item else None,
            "queue_complete": remaining == 0,
        }

    def undo_last(self) -> dict:
        """
        Undo the last typed answer by selecting and deleting it.

        Uses Shift+Home to select the line, then Delete to remove it.
        This is a best-effort approach — works in most text editors.

        Returns:
            Undo result.
        """
        with self._lock:
            if self._last_typed_text is None or self._current_index == 0:
                return {"error": "Nothing to undo."}

            chars_to_undo = self._last_typed_length
            self._current_index -= 1
            item = self._items[self._current_index]
            item.typed = False

            self._last_typed_text = None
            self._last_typed_length = 0

        # Select and delete the text
        # We use Shift+Left arrow repeated, but for long text we use
        # a combination approach: select all text that was typed
        try:
            import pyautogui
            # Select backwards by the number of chars we typed
            # For efficiency, use Shift+Home for single-line or repeated Shift+Left
            if chars_to_undo <= 500:
                # Hold shift and press left arrow to select backwards
                for _ in range(chars_to_undo):
                    pyautogui.hotkey('shift', 'left')
                time.sleep(0.05)
                pyautogui.press('delete')
            else:
                # For very long text, try Ctrl+Shift+Home approach
                # This is less precise but handles large blocks
                for _ in range(chars_to_undo):
                    pyautogui.hotkey('shift', 'left')
                time.sleep(0.05)
                pyautogui.press('delete')

            self._notify_status()
            logger.info("Undid answer %d (%d chars)", item.index, chars_to_undo)
            return {
                "undone_answer": item.index,
                "chars_deleted": chars_to_undo,
                "message": f"Deleted answer {item.index}. Press Ctrl+Shift+Space to retype it.",
            }
        except Exception as e:
            logger.error("Undo failed: %s", e)
            self._notify_status()
            return {"error": f"Undo failed: {e}"}

    def clear(self) -> dict:
        """Clear the entire queue."""
        with self._lock:
            count = len(self._items)
            self._items = []
            self._current_index = 0
            self._last_typed_text = None
            self._last_typed_length = 0

        self._notify_status()
        logger.info("Queue cleared (%d items removed)", count)
        return {"cleared": count, "message": "Answer queue cleared."}

    # ------------------------------------------------------------------ #
    #  Status                                                              #
    # ------------------------------------------------------------------ #

    def get_status(self) -> dict:
        """Get current queue status."""
        with self._lock:
            if not self._items:
                return {
                    "loaded": False,
                    "total": 0,
                    "current": 0,
                    "remaining": 0,
                    "completed": 0,
                    "skipped": 0,
                }

            completed = sum(1 for item in self._items if item.typed)
            skipped = sum(1 for item in self._items if item.skipped)
            remaining = len(self._items) - self._current_index
            current_item = self._get_current()

            return {
                "loaded": True,
                "total": len(self._items),
                "current": self._current_index + 1 if current_item else len(self._items),
                "remaining": remaining,
                "completed": completed,
                "skipped": skipped,
                "current_question": current_item.question if current_item else None,
                "current_answer_preview": (
                    current_item.answer[:100] + "..."
                    if current_item and len(current_item.answer) > 100
                    else current_item.answer if current_item else None
                ),
                "queue_complete": remaining == 0,
                "mode": "paste" if self.use_paste_mode else "type",
                "items": [
                    {
                        "index": item.index,
                        "question": item.question,
                        "answer_preview": item.answer[:80] + ("..." if len(item.answer) > 80 else ""),
                        "status": "typed" if item.typed else ("skipped" if item.skipped else "pending"),
                    }
                    for item in self._items
                ],
            }

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _get_current(self) -> Optional[AnswerItem]:
        """Get the current item (must be called with lock held)."""
        if self._current_index >= len(self._items):
            return None
        return self._items[self._current_index]

    def _notify_status(self):
        """Fire status change callback if registered."""
        if self._on_status:
            try:
                self._on_status(self.get_status())
            except Exception:
                pass
