"""claude_cli backend — shells out to `claude -p`. Works on Max plan with
no extra setup; pays ~5-6 s of CLI bootstrap per call."""
import os
import shutil
import subprocess
import time

_CLAUDE = os.environ.get("CLAUDE_CLI") or shutil.which("claude") or "claude"


def ask(prompt: str, system: str, model: str = "haiku", *, timeout: float = 30.0) -> tuple[str, int]:
    wrapped = f"{system}\n\nQuestion: {prompt}"
    cmd = [_CLAUDE, "-p", "--model", model, wrapped]
    started = time.monotonic()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"claude timed out after {timeout}s")
    except FileNotFoundError:
        raise RuntimeError(f"claude CLI not found at {_CLAUDE!r}")
    latency_ms = int((time.monotonic() - started) * 1000)
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()[:200]
        raise RuntimeError(f"claude exited {result.returncode}: {stderr}")
    reply = (result.stdout or "").strip()
    if not reply:
        raise RuntimeError("claude returned no output")
    return reply, latency_ms
