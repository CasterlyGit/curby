"""Pluggable backends for quick-ask.

Each backend exposes a single function:

    ask(prompt: str, system: str, model: str = "haiku", *,
        history: list[dict] | None = None) -> tuple[str, int]

…returning (reply_text, latency_ms). Raises RuntimeError on failure.

`history` is an optional conversation history — a list of
{"role": "user"|"assistant", "content": str} entries from prior turns.
Backends that support multi-turn (api_key, oauth) include it in the
messages array; backends that don't (claude_cli one-shot) ignore it.

Backends ship with curby:
- "claude_cli" — shells out to `claude -p`. Works on Max plan with no setup
  but pays ~5-6 s of CLI bootstrap per call.
- "api_key"   — direct HTTPS to api.anthropic.com via the official anthropic
  SDK. Requires ANTHROPIC_API_KEY in env or in ~/.curby/config.json.
  Sub-2 s round-trips on Haiku.

Users can also point `backend` in ~/.curby/config.json at a filesystem path
to load a custom backend module. The module must define an `ask` function
with the same signature. This keeps the public package free of any custom
auth strategies — they live in user-controlled files outside the repo.
"""
from __future__ import annotations

import importlib.util
import os
from collections.abc import Callable

BackendFn = Callable[..., tuple[str, int]]


def load_backend(name_or_path: str) -> BackendFn:
    """Resolve a backend identifier to a callable `ask` function.

    Accepts:
    - "claude_cli" / "api_key" — built-in backends
    - any absolute filesystem path to a .py file defining `ask(...)` —
      loaded as a user module at runtime
    """
    if name_or_path == "claude_cli":
        from src.quick_ask_backends.claude_cli import ask
        return ask
    if name_or_path == "api_key":
        from src.quick_ask_backends.api_key import ask
        return ask
    # Treat as a filesystem path.
    if not os.path.isabs(name_or_path) or not os.path.isfile(name_or_path):
        raise ValueError(
            f"Unknown backend {name_or_path!r}: not a built-in and not a "
            f"path to a .py file. Built-ins: claude_cli, api_key."
        )
    spec = importlib.util.spec_from_file_location("curby_user_backend", name_or_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load backend at {name_or_path!r}")
    mod = importlib.util.module_from_spec(spec)
    # Register in sys.modules BEFORE exec so the module is discoverable by
    # name (e.g. prewarm dispatch needs to find optional module-level hooks).
    import sys
    sys.modules["curby_user_backend"] = mod
    spec.loader.exec_module(mod)
    if not hasattr(mod, "ask"):
        raise RuntimeError(f"backend at {name_or_path!r} must define `ask(prompt, system, model)`")
    return mod.ask
