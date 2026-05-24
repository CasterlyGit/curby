"""Live style preferences for quick-ask, driven by voice meta-commands.

When the user says something like "be shorter", "more detail", or
"explain it simpler", Claude itself recognises the utterance as a
preference update (via the system prompt instruction) and returns a
PREFERENCE_UPDATE: directive instead of an answer. We capture that
directive here and prepend it to the system prompt of every future
turn — so the new preference shapes all subsequent replies until
overridden or reset.

Preferences accumulate in chronological order, capped at MAX_KEPT so
the system prompt doesn't grow unbounded. A "RESET" directive clears
them. Persisted to ~/.curby/preferences.json so they survive curby
restarts (the user's voice came from them — feels rude to forget).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

PREFS_PATH = Path(os.path.expanduser("~/.curby/preferences.json"))
MAX_KEPT = 4

# Marker the system prompt tells Claude to emit when classifying an
# utterance as a preference update. Case-sensitive, exact prefix.
PREFERENCE_TOKEN = "PREFERENCE_UPDATE:"


def load() -> list[str]:
    """Return the active preference directives in chronological order
    (oldest first). Empty list if none stored."""
    try:
        data = json.loads(PREFS_PATH.read_text())
        prefs = data.get("directives", [])
        return [str(d) for d in prefs if isinstance(d, str) and d.strip()]
    except Exception:
        return []


def save(directives: list[str]) -> None:
    try:
        PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        PREFS_PATH.write_text(json.dumps({"directives": directives}, indent=2))
    except Exception as e:
        print(f"[prefs] save failed: {e}")


def clear() -> None:
    save([])


def append(directive: str) -> list[str]:
    """Append a new directive, capped at MAX_KEPT (FIFO). Returns the new list."""
    directive = directive.strip()
    if not directive:
        return load()
    prefs = load()
    prefs.append(directive)
    if len(prefs) > MAX_KEPT:
        prefs = prefs[-MAX_KEPT:]
    save(prefs)
    return prefs


def as_system_addendum() -> str:
    """Render current preferences as a system-prompt addendum. Empty
    string if there are none — caller should treat that as 'no
    addendum' and pass nothing extra to the model."""
    prefs = load()
    if not prefs:
        return ""
    lines = ["The user has set these active style preferences (most recent last). "
             "Follow them strictly on top of your other rules:"]
    for i, p in enumerate(prefs, 1):
        lines.append(f"  {i}. {p}")
    return "\n".join(lines)


# ── Reply parsing ──────────────────────────────────────────────────────────

def parse_reply(reply: str) -> tuple[bool, str]:
    """Inspect a model reply for a PREFERENCE_UPDATE: directive.

    Returns (is_preference_update, payload). If is_preference_update is
    True, payload is the directive text (stripped of the marker) — or
    the literal string 'RESET' if the user asked to clear preferences.
    If False, payload is the original reply unchanged.
    """
    stripped = reply.strip()
    if not stripped.startswith(PREFERENCE_TOKEN):
        return False, reply
    payload = stripped[len(PREFERENCE_TOKEN):].strip()
    return True, payload
