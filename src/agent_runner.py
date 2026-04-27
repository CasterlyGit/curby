"""Spawn and supervise a Claude CLI agent for one curby task.

Each task lives in its own workdir under ~/curby-tasks/<timestamp>-<slug>/.
The agent gets full shell + filesystem via --dangerously-skip-permissions and
streams events as JSON which the dock widget renders into live status.

Lifecycle:
  start()           → spawn `claude -p ... <prompt>`
  pause()/resume()  → SIGSTOP/SIGCONT on the process group
  cancel()          → SIGTERM → SIGKILL on the process group
  amend(text)       → queue a follow-up; when the current run exits, a new
                      `claude -p --continue` is spawned in the same workdir so
                      the agent picks up where it left off.
"""
import json
import os
import re
import select
import shutil
import signal
import subprocess
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

_CLAUDE = os.environ.get("CLAUDE_CLI") or shutil.which("claude") or "claude"
TASKS_ROOT = Path.home() / "curby-tasks"


def _slugify(text: str, maxlen: int = 30) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower())
    s = s.strip("-")[:maxlen].rstrip("-")
    return s or "task"


class AgentRunner:
    """One Claude CLI subprocess + the queue of pending amends.

    Callbacks (`on_event`, `on_status`, `on_done`) fire from the reader thread.
    UI code that touches Qt should marshal them via signals.
    """

    def __init__(self,
                 prompt: str,
                 on_event: Callable[[dict], None],
                 on_status: Callable[[str], None],
                 on_done: Callable[[int], None]):
        self.prompt = prompt
        self.on_event = on_event
        self.on_status = on_status
        self.on_done = on_done

        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._workdir: Path | None = None
        self._paused = False
        self._cancelled = False
        self._pending_amends: list[str] = []
        self._lock = threading.Lock()
        self._created_at = datetime.now()
        self._done_event: threading.Event | None = None

    @property
    def workdir(self) -> Path | None:
        return self._workdir

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def is_paused(self) -> bool:
        return self._paused

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self):
        TASKS_ROOT.mkdir(exist_ok=True)
        ts = self._created_at.strftime("%Y%m%d-%H%M%S")
        self._workdir = TASKS_ROOT / f"{ts}-{_slugify(self.prompt)}"
        self._workdir.mkdir(parents=True, exist_ok=True)
        self._spawn(self.prompt, resume=False)

    def _spawn(self, prompt: str, *, resume: bool):
        cmd = [
            _CLAUDE, "-p",
            "--dangerously-skip-permissions",
            "--output-format", "stream-json",
            "--verbose",
        ]
        if resume:
            cmd.append("--continue")
        cmd.append(prompt)

        self.on_status("starting…" if not resume else "amending…")
        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(self._workdir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                start_new_session=True,    # new session + process group → killpg works
            )
        except FileNotFoundError as e:
            self.on_status(f"claude not found: {e}")
            self.on_done(127)
            return

        self._paused = False

        # Per-spawn event guards against double on_done in the race between
        # normal EOF and the companion thread forcing an early close.
        done_event = threading.Event()
        self._done_event = done_event

        self._reader = threading.Thread(
            target=lambda: self._read_loop(done_event), daemon=True
        )
        self._reader.start()

        # Companion thread: unblocks the reader when a grandchild process keeps
        # stdout open after the top-level claude process has already exited.
        proc = self._proc
        def _wait_and_close():
            proc.wait()
            if not done_event.is_set():
                try:
                    proc.stdout.close()
                except (ValueError, OSError):
                    pass
        threading.Thread(target=_wait_and_close, daemon=True).start()

    def _read_loop(self, done_event: threading.Event):
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        try:
            while True:
                # Poll with a 1 s timeout so that a grandchild holding the
                # write end of the pipe open can't block us forever after the
                # top-level process has already exited.  On normal exit the
                # pipe reaches EOF and select() returns instantly; the 1 s
                # delay only applies in the grandchild-keeps-stdout case.
                try:
                    ready = select.select([proc.stdout], [], [], 1.0)[0]
                except (ValueError, OSError):
                    break
                if not ready:
                    if proc.poll() is not None:
                        break   # process exited, no more output expected
                    continue
                raw = proc.stdout.readline()
                if not raw:
                    break       # EOF
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    self.on_event({"type": "raw", "text": line})
                    self.on_status(line[:120])
                    continue
                self.on_event(obj)
                status = _status_from_event(obj)
                if status:
                    self.on_status(status)
        except (ValueError, OSError):
            # Companion thread closed stdout (or other I/O error).
            pass
        rc = proc.wait()

        # Atomic transition: either drain the queue (and re-spawn) or finalize.
        # Marking _reader = None inside the lock signals "no live run" so a
        # concurrent amend() takes the direct-spawn path instead of queueing
        # onto a thread that's about to die.
        next_prompt: str | None = None
        with self._lock:
            if not self._cancelled and self._pending_amends:
                next_prompt = self._pending_amends.pop(0)
            else:
                self._reader = None

        if next_prompt is not None:
            self._spawn(next_prompt, resume=True)
            return

        if not done_event.is_set():
            done_event.set()
            self.on_done(rc)

    # ── Control ────────────────────────────────────────────────────────────────

    def pause(self):
        if not self.is_running or self._paused:
            return
        try:
            os.killpg(os.getpgid(self._proc.pid), signal.SIGSTOP)
            self._paused = True
            self.on_status("paused")
        except (OSError, ProcessLookupError) as e:
            print(f"[agent] pause failed: {e}")

    def resume(self):
        if not self._paused or self._proc is None:
            return
        try:
            os.killpg(os.getpgid(self._proc.pid), signal.SIGCONT)
            self._paused = False
            self.on_status("resumed")
        except (OSError, ProcessLookupError) as e:
            print(f"[agent] resume failed: {e}")

    def cancel(self):
        with self._lock:
            self._cancelled = True
            self._pending_amends.clear()
        if not self.is_running:
            return
        try:
            pgid = os.getpgid(self._proc.pid)
            if self._paused:
                os.killpg(pgid, signal.SIGCONT)
                self._paused = False
            os.killpg(pgid, signal.SIGTERM)
            try:
                self._proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                os.killpg(pgid, signal.SIGKILL)
        except (OSError, ProcessLookupError) as e:
            print(f"[agent] cancel failed: {e}")
        self.on_status("cancelled")

    def amend(self, text: str):
        """Queue an amend onto a live run, or re-spawn directly if the run finished.

        On a `cancelled` runner, drops silently — `cancel()` is "throw away
        pending work and stop accepting more." Held-lock through `_spawn` so
        concurrent amends from the UI thread can't race into a double-spawn.
        """
        text = (text or "").strip()
        if not text:
            return
        with self._lock:
            if self._cancelled:
                return
            if self._reader is not None and self._reader.is_alive():
                self._pending_amends.append(text)
                self.on_status(f"amend queued: {text[:60]}")
                return
            # No live reader — direct re-spawn with --continue in the same workdir.
            self._spawn(text, resume=True)


# ── Event → status string ────────────────────────────────────────────────────

def _status_from_event(obj: dict) -> str | None:
    """Map a stream-json event to a short human-readable status line."""
    t = obj.get("type")
    if t == "system":
        sub = obj.get("subtype")
        if sub == "init":
            return "thinking…"
        return None
    if t == "assistant":
        msg = obj.get("message", {})
        for block in msg.get("content", []):
            btype = block.get("type")
            if btype == "tool_use":
                name = block.get("name", "tool")
                inp = block.get("input") or {}
                hint = _tool_hint(name, inp)
                return f"using {name}{(' · ' + hint) if hint else ''}"
            if btype == "text":
                txt = (block.get("text") or "").strip()
                if txt:
                    return txt.splitlines()[0][:120]
        return None
    if t == "user":
        # tool result
        msg = obj.get("message", {})
        for block in msg.get("content", []):
            if block.get("type") == "tool_result":
                return "got result"
        return None
    if t == "result":
        sub = obj.get("subtype")
        result_text = (obj.get("result") or "").strip()
        if sub == "success":
            # Show the agent's final reply as the resting status — much more
            # useful than a generic "done" the user has to hover to see.
            return result_text or "done"
        return f"error: {sub}" if sub else "error"
    return None


def _tool_hint(name: str, inp: dict) -> str:
    """Tiny descriptor of what the tool is doing, for live status."""
    if name == "Bash":
        cmd = (inp.get("command") or "").strip().splitlines()[0]
        return cmd[:80]
    if name in ("Read", "Edit", "Write", "NotebookEdit"):
        return os.path.basename(inp.get("file_path") or "")
    if name == "Grep":
        return f"'{inp.get('pattern','')[:40]}'"
    if name == "Glob":
        return inp.get("pattern", "")[:40]
    if name in ("WebFetch", "WebSearch"):
        return inp.get("url") or inp.get("query") or ""
    return ""
