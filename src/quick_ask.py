"""Quick-ask: voice in → short Claude answer → voice out.

A lightweight sibling to the agent-spawn flow. The Ctrl+Space path runs
an autonomous Claude Code agent in a sandbox. Ctrl+/ instead pipes the
transcribed prompt to `claude -p` with a 1-3 sentence instruction and
speaks the reply via TTS. No puck, no sandbox, no tools.

Every call is logged to ~/.curby/quick-ask-log.jsonl so we can later
compare cost vs the Anthropic API for the same usage pattern.
"""
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

_CLAUDE = os.environ.get("CLAUDE_CLI") or shutil.which("claude") or "claude"

LOG_PATH = Path(os.path.expanduser("~/.curby/quick-ask-log.jsonl"))

_SYSTEM = "Answer in 1-3 short sentences, conversational, for spoken playback. No markdown, no lists, no code blocks."


def run_quick_ask(prompt: str, *, timeout: float = 30.0, claude_cli: str | None = None) -> tuple[str, int]:
    """Run `claude -p` with a one-shot quick-ask wrapper. Returns (reply, latency_ms).

    Raises RuntimeError on subprocess failure, timeout, or empty reply.
    """
    cli = claude_cli or _CLAUDE
    wrapped = f"{_SYSTEM}\n\nQuestion: {prompt}"
    started = time.monotonic()
    try:
        result = subprocess.run(
            [cli, "-p", wrapped],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"claude timed out after {timeout}s")
    except FileNotFoundError:
        raise RuntimeError(f"claude CLI not found at {cli!r}")

    latency_ms = int((time.monotonic() - started) * 1000)

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()[:200]
        raise RuntimeError(f"claude exited {result.returncode}: {stderr}")

    reply = (result.stdout or "").strip()
    if not reply:
        raise RuntimeError("claude returned no output")
    return reply, latency_ms


def log_quick_ask(prompt: str, reply: str, latency_ms: int, *, log_path: Path | None = None) -> None:
    """Append one JSONL line capturing the call. Failures are swallowed — logging
    must never break the user-facing flow."""
    path = log_path or LOG_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prompt_text": prompt,
            "prompt_chars": len(prompt),
            "response_text": reply,
            "response_chars": len(reply),
            "latency_ms": latency_ms,
        }
        with path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"[quick-ask] log write failed: {e}")
