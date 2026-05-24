"""Pidfile management — ensures only one curby instance is running.

On startup, if ~/.curby/curby.pid exists and points at a live process,
kill it. Then write our own PID. On clean quit, remove the file.

This prevents the "old curby still showing overlays" failure mode that
happens when a previous run was force-killed (SIGKILL skips Qt's quit
path, so any always-on-top windows can linger if the OS doesn't clean
them up). Even when Qt does shut down cleanly, a stale instance from
a different terminal can stack with a new one — pidfile catches that
too.
"""
from __future__ import annotations

import os
import signal
import time
from pathlib import Path

PID_PATH = Path(os.path.expanduser("~/.curby/curby.pid"))


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        # signal 0 = no-op probe; raises if process doesn't exist
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except Exception:
        return False


def kill_previous() -> int:
    """If a previous curby is running per the pidfile, kill it. Returns
    the killed PID (or 0 if there was nothing to kill)."""
    try:
        raw = PID_PATH.read_text().strip()
        prev_pid = int(raw)
    except Exception:
        return 0
    if prev_pid == os.getpid() or not _pid_alive(prev_pid):
        return 0
    try:
        os.kill(prev_pid, signal.SIGTERM)
        # Give it ~1s to exit cleanly; force kill if still alive.
        for _ in range(10):
            time.sleep(0.1)
            if not _pid_alive(prev_pid):
                return prev_pid
        os.kill(prev_pid, signal.SIGKILL)
        return prev_pid
    except Exception as e:
        print(f"[pidfile] couldn't kill previous pid {prev_pid}: {e}")
        return 0


def write_self() -> None:
    try:
        PID_PATH.parent.mkdir(parents=True, exist_ok=True)
        PID_PATH.write_text(str(os.getpid()))
    except Exception as e:
        print(f"[pidfile] write failed: {e}")


def clear() -> None:
    try:
        if PID_PATH.exists():
            # Only remove if it's still our PID (avoid clobbering a freshly
            # written file from a concurrent start).
            try:
                raw = PID_PATH.read_text().strip()
                if int(raw) == os.getpid():
                    PID_PATH.unlink()
            except Exception:
                PID_PATH.unlink()
    except Exception as e:
        print(f"[pidfile] cleanup failed: {e}")
