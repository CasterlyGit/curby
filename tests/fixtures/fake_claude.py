#!/usr/bin/env python3
"""Test double for the `claude` CLI.

Reads `FAKE_CLAUDE_MODE` and emits a canned sequence of stream-json lines that
match the shapes `agent_runner._status_from_event` knows how to parse, then
exits with `FAKE_CLAUDE_RC` (default depends on mode).

Modes:
  success      init → tool_use Bash → tool_result → tool_use Read → text → result/success
  error        init → result/error_during_execution
  crash_early  init → exit 1 (no result line)
  slow         init → sleep FAKE_CLAUDE_SLEEP (default 0.5) → result/success

The script appends its argv to `<cwd>/argv.log` so tests can verify whether
`--continue` was passed on a re-spawn.
"""
import json
import os
import sys
import time
from pathlib import Path


def _emit(obj):
    print(json.dumps(obj), flush=True)


def main():
    Path("argv.log").open("a").write(" ".join(sys.argv[1:]) + "\n")

    mode = os.environ.get("FAKE_CLAUDE_MODE", "success")
    rc_override = os.environ.get("FAKE_CLAUDE_RC")

    _emit({"type": "system", "subtype": "init"})

    if mode == "crash_early":
        sys.exit(int(rc_override) if rc_override else 1)

    if mode == "error":
        _emit({"type": "result", "subtype": "error_during_execution"})
        sys.exit(int(rc_override) if rc_override else 1)

    if mode == "slow":
        time.sleep(float(os.environ.get("FAKE_CLAUDE_SLEEP", "0.5")))
        _emit({"type": "result", "subtype": "success", "result": "slow done"})
        sys.exit(int(rc_override) if rc_override else 0)

    _emit({
        "type": "assistant",
        "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "echo hi"}}
        ]},
    })
    _emit({
        "type": "user",
        "message": {"content": [
            {"type": "tool_result", "content": "hi"}
        ]},
    })
    _emit({
        "type": "assistant",
        "message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/tmp/x.py"}}
        ]},
    })
    _emit({
        "type": "assistant",
        "message": {"content": [
            {"type": "text", "text": "all done"}
        ]},
    })
    _emit({"type": "result", "subtype": "success", "result": "all done"})
    sys.exit(int(rc_override) if rc_override else 0)


if __name__ == "__main__":
    main()
