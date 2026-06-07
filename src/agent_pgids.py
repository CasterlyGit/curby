"""Orphan-agent reaper — pgid sidecar.

When curby is force-killed (SIGKILL), agents spawned with
``start_new_session=True`` survive as orphan process groups; they keep
running indefinitely consuming CPU/tokens.

This module provides two complementary halves:

  register(slug, pgid)  — called by AgentRunner on each spawn; persists
                          the pgid to ~/.curby/agent-pgids.json keyed by
                          a task slug so the next boot can find them.

  reap_previous()       — called once at curby startup; SIGTERMs every
                          process group from the previous boot whose pgid
                          is still alive, then clears the file.

Agents that exit cleanly are not in the file (they remove themselves via
``deregister``).  The reap step is *startup-only*: we never auto-reap
agents from the current boot so a live amend flow isn't disrupted.
"""
from __future__ import annotations

import json
import os
import signal
from pathlib import Path

_PGIDS_PATH = Path(os.path.expanduser("~/.curby/agent-pgids.json"))


def _load() -> dict[str, int]:
    try:
        return json.loads(_PGIDS_PATH.read_text())
    except Exception:
        return {}


def _save(data: dict[str, int]) -> None:
    try:
        _PGIDS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PGIDS_PATH.write_text(json.dumps(data))
    except Exception as e:
        print(f"[agent-pgids] save failed: {e}")


def _pgid_alive(pgid: int) -> bool:
    """Return True if the process group pgid has at least one live member."""
    if pgid <= 0:
        return False
    try:
        os.killpg(pgid, 0)   # signal 0 = no-op probe; raises if group gone
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except Exception:
        return False


def register(slug: str, pgid: int) -> None:
    """Record that agent *slug* is running in process group *pgid*."""
    data = _load()
    data[slug] = pgid
    _save(data)


def deregister(slug: str) -> None:
    """Remove *slug* from the registry (call when agent exits cleanly)."""
    data = _load()
    if slug in data:
        del data[slug]
        _save(data)


def reap_previous() -> list[str]:
    """Terminate orphaned process groups from a previous curby run.

    Reads the pgid registry, SIGTERMs every group still alive, then
    clears the file.  Returns a list of slugs that were reaped.
    """
    data = _load()
    if not data:
        return []

    reaped: list[str] = []
    for slug, pgid in data.items():
        if _pgid_alive(pgid):
            try:
                os.killpg(pgid, signal.SIGTERM)
                reaped.append(slug)
                print(f"[agent-pgids] reaped orphan pgid {pgid} ({slug})", flush=True)
            except Exception as e:
                print(f"[agent-pgids] SIGTERM pgid {pgid} ({slug}) failed: {e}", flush=True)

    # Always clear the file — dead entries are useless on the next boot too.
    try:
        _PGIDS_PATH.unlink()
    except Exception:
        pass

    return reaped
