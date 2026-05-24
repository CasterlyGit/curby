"""api_key backend — direct HTTPS to api.anthropic.com via the official
anthropic SDK. Sub-2 s round-trips on Haiku.

Requires an API key in one of:
- `ANTHROPIC_API_KEY` env var
- `api_key` field in ~/.curby/config.json

This is the recommended fast-path for curby: cheap (Haiku is ~$1-3/month
at typical voice-Q&A volumes) and clean (no TOS grey areas, no future
breakage risk).
"""
import json
import os
import time
from pathlib import Path


_MODEL_MAP = {
    "haiku":  "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-6",
    "opus":   "claude-opus-4-7",
}


def _resolve_api_key() -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    cfg_path = Path(os.path.expanduser("~/.curby/config.json"))
    try:
        return json.loads(cfg_path.read_text()).get("api_key")
    except Exception:
        return None


def ask(prompt: str, system: str, model: str = "haiku", *,
        history: list[dict] | None = None) -> tuple[str, int]:
    key = _resolve_api_key()
    if not key:
        raise RuntimeError(
            "api_key backend selected but no ANTHROPIC_API_KEY found in env or "
            "in ~/.curby/config.json (key: 'api_key')."
        )
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic SDK not installed (pip install anthropic)")

    model_id = _MODEL_MAP.get(model, model)
    client = anthropic.Anthropic(api_key=key)
    messages = list(history or []) + [{"role": "user", "content": prompt}]
    started = time.monotonic()
    msg = client.messages.create(
        model=model_id,
        max_tokens=200,
        system=system,
        messages=messages,
    )
    latency_ms = int((time.monotonic() - started) * 1000)
    text = ""
    for block in msg.content:
        if getattr(block, "type", None) == "text":
            text += getattr(block, "text", "")
    text = text.strip()
    if not text:
        raise RuntimeError("anthropic API returned no text")
    return text, latency_ms
