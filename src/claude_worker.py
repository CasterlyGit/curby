"""Persistent `claude` subprocess for low-latency quick-ask.

Spawning a fresh `claude -p` per question costs ~6-8s — most of it is CLI
bootstrap (hooks, plugin sync, agent harness init, prompt-cache creation)
that doesn't change between calls. By keeping ONE process alive with
stream-json I/O, we pay that once at curby startup and each subsequent
question pays only model TTFT + generation.

The worker runs `claude` in non-interactive streaming mode:
    claude --print --input-format stream-json --output-format stream-json \
           --verbose --model <model> --system-prompt <prompt>

Each `ask(text)` call writes ONE user message line to stdin and reads
output events until a `result` event arrives, returning its `result` field.

Crashes / EOF / corrupt output → the worker is marked dead; the next
`ask()` respawns transparently. Concurrent calls are serialized by a
lock — at most one in-flight question at a time (matches the user's
hotkey UX: tap, speak, listen — no parallel quick-asks).
"""
import json
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

_CLAUDE = os.environ.get("CLAUDE_CLI") or shutil.which("claude") or "claude"


class ClaudeWorker:
    """A long-running `claude` subprocess that handles serial questions."""

    def __init__(self, system_prompt: str, *, model: str = "haiku",
                 claude_cli: str | None = None, cwd: str | None = None,
                 on_log: Callable[[str], None] | None = None):
        self._system_prompt = system_prompt
        self._model = model
        self._cli = claude_cli or _CLAUDE
        self._cwd = cwd or str(Path(os.path.expanduser("~/.curby/worker-cwd")))
        self._log = on_log or (lambda msg: print(f"[worker] {msg}", flush=True))
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()  # serializes ask() calls
        Path(self._cwd).mkdir(parents=True, exist_ok=True)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Spawn the persistent process. Idempotent."""
        with self._lock:
            if self._proc and self._proc.poll() is None:
                return
            self._spawn_locked()

    def _spawn_locked(self) -> None:
        cmd = [
            self._cli,
            "--print",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--model", self._model,
            "--system-prompt", self._system_prompt,
            "--no-session-persistence",
        ]
        self._log(f"spawning: model={self._model}")
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # line-buffered
            cwd=self._cwd,
        )
        # Drain any startup banner / hook events until we see init.
        while True:
            line = self._proc.stdout.readline()
            if not line:
                rc = self._proc.poll()
                self._log(f"died during init (rc={rc}); stderr={self._read_stderr_nowait()!r}")
                self._proc = None
                raise RuntimeError("claude worker died during init")
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") == "system" and obj.get("subtype") == "init":
                self._log("ready")
                return

    def stop(self) -> None:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                try:
                    self._proc.stdin.close()
                except Exception: pass
                try:
                    self._proc.terminate()
                    self._proc.wait(timeout=2)
                except Exception:
                    try: self._proc.kill()
                    except Exception: pass
            self._proc = None

    # ── Asking ───────────────────────────────────────────────────────────────

    def ask(self, text: str, *, timeout: float = 30.0) -> tuple[str, int]:
        """Send a user message, block until the assistant returns its result.
        Returns (reply_text, latency_ms). Raises RuntimeError on any failure."""
        with self._lock:
            if not self._proc or self._proc.poll() is not None:
                self._spawn_locked()
            assert self._proc is not None
            return self._ask_locked(text, timeout)

    def _ask_locked(self, text: str, timeout: float) -> tuple[str, int]:
        msg = {
            "type": "user",
            "message": {"role": "user", "content": text},
        }
        line = json.dumps(msg) + "\n"
        started = time.monotonic()
        try:
            self._proc.stdin.write(line)
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            self._log(f"stdin write failed: {e}; respawning")
            self._proc = None
            raise RuntimeError(f"worker write failed: {e}")

        deadline = started + timeout
        result_text: str | None = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._log("timeout — killing worker")
                self.stop()
                raise RuntimeError(f"claude worker timed out after {timeout}s")
            line = self._proc.stdout.readline()
            if not line:
                rc = self._proc.poll()
                stderr = self._read_stderr_nowait()
                self._log(f"stdout closed (rc={rc}); stderr={stderr!r}")
                self._proc = None
                raise RuntimeError(f"claude worker died mid-turn (rc={rc})")
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = obj.get("type")
            if t == "result":
                if obj.get("is_error"):
                    raise RuntimeError(f"claude returned error: {obj.get('result', 'unknown')}")
                result_text = (obj.get("result") or "").strip()
                break
            # Ignore other events (assistant deltas, system hook events, etc.)

        latency_ms = int((time.monotonic() - started) * 1000)
        if not result_text:
            raise RuntimeError("claude returned empty result")
        return result_text, latency_ms

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _read_stderr_nowait(self) -> str:
        if not self._proc or not self._proc.stderr:
            return ""
        try:
            # Non-blocking-ish drain. Best effort.
            import select
            chunks = []
            while True:
                r, _, _ = select.select([self._proc.stderr], [], [], 0.05)
                if not r:
                    break
                chunk = self._proc.stderr.read(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            return "".join(chunks)[:500]
        except Exception:
            return ""

    @property
    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None
