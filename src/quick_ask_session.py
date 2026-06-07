"""QuickAskSession — in-memory conversation history for quick-ask follow-ups.

Extracted from CurbyApp so the conversation-state logic is testable without
any Qt dependency. The session holds the rolling message list and the
timestamp of the last turn; `take_snapshot()` ages-out stale history
automatically.

No Qt imports; no filesystem I/O. Pure coordinator, safe to unit-test.
"""
from __future__ import annotations

import time


class QuickAskSession:
    """Rolling conversation history for multi-turn quick-ask exchanges.

    Usage::

        session = QuickAskSession()
        history = session.take_snapshot()   # empty on first call
        # ... run_quick_ask(prompt, history=history) ...
        session.record_turn(user_text, assistant_text)

    `take_snapshot()` returns the live history if the last turn was within
    FOLLOWUP_WINDOW_SECONDS; otherwise it clears the history first and
    returns []. Call it at the *start* of each turn so every call sees a
    coherent, non-stale snapshot.
    """

    #: Maximum number of (user + assistant) *pairs* to keep in the rolling
    #: window. Keeps token cost bounded.
    MAX_HISTORY_TURNS: int = 8

    def __init__(self, followup_window_seconds: float | None = None):
        self._history: list[dict] = []
        self._last_turn_at: float = 0.0
        # Allow the window to be injected so callers that already read it
        # from quick_ask.FOLLOWUP_WINDOW_SECONDS don't import it here.
        self._followup_window: float | None = followup_window_seconds

    # ── Public interface ──────────────────────────────────────────────────────

    def take_snapshot(self) -> list[dict]:
        """Return a copy of the current history, clearing it first if stale.

        "Stale" means more than FOLLOWUP_WINDOW_SECONDS have elapsed since the
        last recorded turn. The window is read lazily from
        ``quick_ask.FOLLOWUP_WINDOW_SECONDS`` on first use (to avoid a
        circular import if someone imports this module early).
        """
        window = self._get_window()
        if (time.time() - self._last_turn_at) > window:
            self._history = []
        return list(self._history)

    def record_turn(self, user_text: str, assistant_text: str) -> None:
        """Append a completed turn and update the last-turn timestamp."""
        self._history.append({"role": "user", "content": user_text})
        self._history.append({"role": "assistant", "content": assistant_text})
        # Cap at the most recent N entries (FIFO trim).
        max_entries = self.MAX_HISTORY_TURNS * 2
        if len(self._history) > max_entries:
            self._history = self._history[-max_entries:]
        self._last_turn_at = time.time()

    def clear(self) -> None:
        """Reset the history and timestamp (e.g. on preference RESET)."""
        self._history = []
        self._last_turn_at = 0.0

    @property
    def is_active(self) -> bool:
        """True if the session has at least one recorded turn and is not stale."""
        if not self._history:
            return False
        window = self._get_window()
        return (time.time() - self._last_turn_at) <= window

    # ── Internals ─────────────────────────────────────────────────────────────

    def _get_window(self) -> float:
        if self._followup_window is not None:
            return self._followup_window
        try:
            from src.quick_ask import FOLLOWUP_WINDOW_SECONDS
            return FOLLOWUP_WINDOW_SECONDS
        except Exception:
            return 60.0
