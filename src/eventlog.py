"""Append-only JSONL event logs for curby.

Two streams:
- ~/.curby/curby.log — structured events from agent_runner + quick_ask runtime
  (timing, dispatch, errors). Read by src/stats.py for latency aggregates.
- ~/.curby/quick-ask-log.jsonl — per-call quick-ask prompt/reply/backend/latency.

Schema for curby.log entries:
  {"ts": <ISO8601 UTC>, "event": <str>, ...kwargs}

Schema for quick-ask-log.jsonl entries:
  whatever quick_ask.log_quick_ask wrote — preserve verbatim.

Never raises; log-write failures print to stderr.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_EVENT_LOG = Path.home() / ".curby" / "curby.log"
_QUICK_ASK_LOG = Path.home() / ".curby" / "quick-ask-log.jsonl"


def log_event(event: str, **kwargs) -> None:
    """Append one structured JSON line to ~/.curby/curby.log. Never raises."""
    try:
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **kwargs}
        _EVENT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _EVENT_LOG.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"[curby] log write failed: {e}", file=sys.stderr, flush=True)


def log_quick_ask(prompt: str, reply: str, latency_ms: int, *,
                  was_followup: bool = False, log_path: Path | None = None) -> None:
    """Append one JSONL line capturing the quick-ask call.

    Failures are swallowed — logging must never break the user-facing flow.
    """
    path = log_path or _QUICK_ASK_LOG
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prompt_text": prompt,
            "prompt_chars": len(prompt),
            "response_text": reply,
            "response_chars": len(reply),
            "latency_ms": latency_ms,
            "was_followup": was_followup,
        }
        with path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"[quick-ask] log write failed: {e}")
