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
import platform
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

_CLAUDE = os.environ.get("CLAUDE_CLI") or shutil.which("claude") or "claude"

LOG_PATH = Path(os.path.expanduser("~/.curby/quick-ask-log.jsonl"))
SESSION_PATH = Path(os.path.expanduser("~/.curby/quick-ask-session.json"))

# Conversational follow-up window. A Ctrl+/ within this many seconds of the
# last reply reuses prior context via `claude -p --continue`. After the
# window, the next quick-ask starts a fresh session.
FOLLOWUP_WINDOW_SECONDS = 60.0

# First-principles tutor mode. The user is learning, not skimming. One moderate
# spoken line, grounded in the underlying mechanism, then stop — they will ask
# the follow-up if they want more.
_SYSTEM = (
    "You are a first-principles tutor speaking aloud. The user is learning, not skimming. "
    "Answer in ONE moderate spoken line (about 15-25 words, ~3 seconds of speech). "
    "Ground the answer in the underlying mechanism — what is actually happening — not a watered-down summary. "
    "Then STOP. Do not list, do not enumerate, do not say 'in summary.' "
    "Assume the user will ask a natural follow-up like 'but what does that mean?' or 'why?' if they want more. "
    "No markdown, no code blocks, no bullets — this is spoken."
)


def _now() -> float:
    return time.time()


def _load_session() -> dict:
    try:
        return json.loads(SESSION_PATH.read_text())
    except Exception:
        return {}


def _save_session(workdir: str, last_used: float) -> None:
    try:
        SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
        SESSION_PATH.write_text(json.dumps({"workdir": workdir, "last_used": last_used}))
    except Exception as e:
        print(f"[quick-ask] session save failed: {e}")


def _clear_session() -> None:
    try: SESSION_PATH.unlink()
    except Exception: pass


def _resolve_session(now: float) -> tuple[str, bool]:
    """Returns (workdir, is_followup). If a saved session is within the
    follow-up window, reuse its workdir with --continue. Otherwise spin a
    fresh per-call workdir."""
    sess = _load_session()
    workdir = sess.get("workdir")
    last = sess.get("last_used", 0.0)
    if workdir and (now - last) <= FOLLOWUP_WINDOW_SECONDS and Path(workdir).is_dir():
        return workdir, True
    # Fresh workdir for a brand-new conversation.
    fresh = Path(os.path.expanduser("~/.curby/sessions")) / f"qa-{int(now)}"
    fresh.mkdir(parents=True, exist_ok=True)
    return str(fresh), False


def run_quick_ask(prompt: str, *, timeout: float = 30.0, claude_cli: str | None = None,
                  model: str = "haiku") -> tuple[str, int, bool]:
    """Run `claude -p` with a one-shot quick-ask wrapper. Returns (reply, latency_ms, was_followup).

    Uses Haiku by default for speed (~3-4s vs ~7s on Sonnet). Reuses prior
    context via --continue when the previous quick-ask was within
    FOLLOWUP_WINDOW_SECONDS. Raises RuntimeError on subprocess failure,
    timeout, or empty reply.
    """
    cli = claude_cli or _CLAUDE
    now = _now()
    workdir, is_followup = _resolve_session(now)

    if is_followup:
        # Continuing a conversation — don't re-send the system prompt, the
        # prior turn established it. Just send the user's new question.
        cmd = [cli, "-p", "--continue", "--model", model, prompt]
    else:
        wrapped = f"{_SYSTEM}\n\nQuestion: {prompt}"
        cmd = [cli, "-p", "--model", model, wrapped]

    started = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=workdir,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"claude timed out after {timeout}s")
    except FileNotFoundError:
        raise RuntimeError(f"claude CLI not found at {cli!r}")

    latency_ms = int((time.monotonic() - started) * 1000)

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()[:200]
        # If --continue failed (e.g. session expired), clear and signal upstream.
        if is_followup:
            _clear_session()
        raise RuntimeError(f"claude exited {result.returncode}: {stderr}")

    reply = (result.stdout or "").strip()
    if not reply:
        raise RuntimeError("claude returned no output")

    # Save session for the next call's follow-up window.
    _save_session(workdir, _now())
    return reply, latency_ms, is_followup


def speak_reply(text: str) -> None:
    """Speak the reply, preferring macOS `say` (reliable subprocess) over
    pyttsx3 (which can deadlock when invoked from non-main threads on macOS).

    Falls back to voice_io.speak on non-macOS or if `say` is unavailable.
    """
    if platform.system() == "Darwin" and shutil.which("say"):
        try:
            subprocess.run(["say", text], check=False, timeout=60)
            return
        except Exception as e:
            print(f"[quick-ask] say failed, falling back to pyttsx3: {e}")
    # Non-Darwin or `say` missing — fall back.
    try:
        from src.voice_io import speak
        speak(text, block=True)
    except Exception as e:
        print(f"[quick-ask] speak fallback failed: {e}")


def log_quick_ask(prompt: str, reply: str, latency_ms: int, *,
                  was_followup: bool = False, log_path: Path | None = None) -> None:
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
            "was_followup": was_followup,
        }
        with path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"[quick-ask] log write failed: {e}")
