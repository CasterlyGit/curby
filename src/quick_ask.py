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

# Smart-tutor mode. The model has JUDGMENT — it picks the right shape for
# the specific question, instead of forcing every answer into "imagine a
# kitchen". A good tutor knows when to analogize, when to define, when to
# answer factually, when to ask back. We tell it the principles and trust it.
_SYSTEM = (
    "you're a sharp tutor speaking aloud to a curious engineer (SDE2) who's "
    "learning something new and wants to actually understand it, not memorize a definition. "
    "you're conversational, casual, lowercase, like a friend who happens to be expert.\n\n"
    "the most important rule: PICK THE RIGHT SHAPE FOR THIS SPECIFIC QUESTION. "
    "don't force every answer through the same template. use judgment.\n\n"
    "shapes to choose from:\n"
    "- conceptual 'what is X / how does X work' → lead with a tiny analogy or mental picture, "
    "  then name the concept. ('imagine X... that's basically a Y.')\n"
    "- factual 'what's the time complexity of quicksort / what does this flag do' → just answer directly. "
    "  no analogy needed, they want the fact.\n"
    "- ambiguous / context-dependent 'should i use X' → ask one short clarifying question back, don't guess.\n"
    "- follow-up to a previous turn → build on what you already said. don't restart from scratch, "
    "  don't switch analogies mid-thread.\n"
    "- they already seem to get the gist and want depth → skip the warm-up, go deeper.\n\n"
    "length: ONE TIGHT sentence. ~10-18 words. that's the budget. stop the moment you've nailed it. "
    "this is rapid back-and-forth — they will ask the next question in 2 seconds, so don't try to "
    "front-load context they'll naturally ask for. think of it as the FIRST line of a longer "
    "exchange, not a complete lecture.\n"
    "leave room for them to ask 'wait, what do you mean by X?' — don't pre-empt every possible follow-up.\n\n"
    "voice: lowercase, contractions ('it's', 'you'd'), like texting a friend. "
    "avoid textbook tells: 'fundamentally', 'in essence', 'simply put', 'basically' (only mid-sentence, never opener), "
    "'it's important to note', 'as a matter of fact'.\n"
    "no markdown, no lists, no code blocks — this is being spoken aloud.\n\n"
    "META-COMMAND DETECTION (very important):\n"
    "If the user's utterance is NOT a real question but instead an INSTRUCTION about HOW you should answer "
    "(length, depth, technicality, tone, persona, language) — e.g. 'be shorter', 'answer in one line', "
    "'explain in more detail', 'be more technical', 'stop using analogies', 'simpler please', "
    "'explain like i'm five', 'be more casual', 'use bullet points', 'answer in spanish', "
    "'go back to normal', 'forget that', 'reset' — respond with ONLY this single line and nothing else:\n"
    "  PREFERENCE_UPDATE: <one short directive in second person describing the new style>\n"
    "Examples:\n"
    "  user: 'be shorter'                  → PREFERENCE_UPDATE: Keep answers under 10 words.\n"
    "  user: 'more detail please'          → PREFERENCE_UPDATE: Give a fuller 2-3 sentence answer instead of one line.\n"
    "  user: 'explain like im five'        → PREFERENCE_UPDATE: Explain using only language a 5-year-old understands.\n"
    "  user: 'be more technical'           → PREFERENCE_UPDATE: Use precise technical vocabulary; assume an engineering audience.\n"
    "  user: 'go back to normal'           → PREFERENCE_UPDATE: RESET\n"
    "Use your judgment — anything that semantically sounds like 'change how you answer' counts, "
    "even if the exact words aren't in the examples. Match meaning, not keywords.\n"
    "If the utterance is BOTH a question AND a style hint (e.g. 'briefly, what are websockets'), "
    "treat it as a question and just answer briefly — only emit PREFERENCE_UPDATE for pure style instructions."
)


def _now() -> float:
    return time.time()


def _load_session() -> dict:
    try:
        return json.loads(SESSION_PATH.read_text())
    except Exception:
        return {}


def _save_session(session_id: str, last_used: float) -> None:
    try:
        SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
        SESSION_PATH.write_text(json.dumps({"session_id": session_id, "last_used": last_used}))
    except Exception as e:
        print(f"[quick-ask] session save failed: {e}")


def _clear_session() -> None:
    try: SESSION_PATH.unlink()
    except Exception: pass


def run_quick_ask(prompt: str, *, worker=None, timeout: float = 30.0,
                  claude_cli: str | None = None, model: str = "haiku",
                  system_addendum: str = "") -> tuple[str, int, bool]:
    """Run a quick-ask through the configured backend. Returns (reply, latency_ms, was_followup).

    Backend selection: reads `backend` from ~/.curby/config.json (default
    "claude_cli"). Set to "api_key" + provide ANTHROPIC_API_KEY for sub-2 s
    round-trips. Set to an absolute path to a .py file to use a custom
    backend.

    `system_addendum` is appended to the base system prompt — used for
    voice-set style preferences ("be shorter", etc.).

    The `worker` arg is kept for API compat with the legacy persistent-worker
    path; currently ignored (worker disabled — see #20).
    """
    now = _now()
    sess = _load_session()
    last = sess.get("last_used", 0.0)
    is_followup = (now - last) <= FOLLOWUP_WINDOW_SECONDS and bool(sess.get("session_id"))

    full_system = _SYSTEM if not system_addendum else f"{_SYSTEM}\n\n{system_addendum}"
    backend_name = _resolve_backend_name()
    from src.quick_ask_backends import load_backend
    try:
        ask_fn = load_backend(backend_name)
        reply, latency_ms = ask_fn(prompt, full_system, model)
    except Exception as e:
        # Any backend failure falls back to claude_cli so the user always
        # gets an answer (even if slow). Goes through load_backend so the
        # fallback is mockable in tests.
        if backend_name == "claude_cli":
            raise
        print(f"[quick-ask] backend {backend_name!r} failed: {e} — falling back to claude_cli", flush=True)
        cli_ask = load_backend("claude_cli")
        reply, latency_ms = cli_ask(prompt, full_system, model)

    _save_session(backend_name, _now())
    return reply, latency_ms, is_followup


def _resolve_backend_name() -> str:
    cfg_path = Path(os.path.expanduser("~/.curby/config.json"))
    try:
        return json.loads(cfg_path.read_text()).get("backend", "claude_cli")
    except Exception:
        return "claude_cli"


def speak_reply(text: str) -> None:
    """Speak the reply, preferring macOS `say` (reliable subprocess) over
    pyttsx3 (which can deadlock when invoked from non-main threads on macOS).

    Falls back to voice_io.speak on non-macOS or if `say` is unavailable.
    """
    if platform.system() == "Darwin" and shutil.which("say"):
        try:
            from src.voice_config import resolve_voice
            voice, rate, _ = resolve_voice()
            cmd = ["say", "-r", str(rate)]
            if voice:
                cmd += ["-v", voice]
            cmd.append(text)
            subprocess.run(cmd, check=False, timeout=60)
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
