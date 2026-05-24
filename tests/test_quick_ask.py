"""Headless coverage of the quick-ask module — mocks the `claude` subprocess
and a temp log path so we never hit the real CLI or the user's home dir."""
import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from src import quick_ask


def test_run_quick_ask_returns_reply_and_latency(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        assert cmd[0]  # the cli path
        assert cmd[1] == "-p"
        assert "Question: what are websockets" in cmd[2]
        return subprocess.CompletedProcess(cmd, 0, stdout="WebSockets are persistent full-duplex connections.\n", stderr="")
    monkeypatch.setattr(quick_ask.subprocess, "run", fake_run)

    reply, latency_ms = quick_ask.run_quick_ask("what are websockets", claude_cli="/usr/bin/claude")
    assert reply == "WebSockets are persistent full-duplex connections."
    assert latency_ms >= 0


def test_run_quick_ask_raises_on_nonzero_exit(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")
    monkeypatch.setattr(quick_ask.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="claude exited 1"):
        quick_ask.run_quick_ask("hi", claude_cli="/usr/bin/claude")


def test_run_quick_ask_raises_on_empty_output(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        return subprocess.CompletedProcess(cmd, 0, stdout="   \n", stderr="")
    monkeypatch.setattr(quick_ask.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="no output"):
        quick_ask.run_quick_ask("hi", claude_cli="/usr/bin/claude")


def test_run_quick_ask_raises_on_timeout(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)
    monkeypatch.setattr(quick_ask.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="timed out"):
        quick_ask.run_quick_ask("hi", claude_cli="/usr/bin/claude", timeout=1.0)


def test_run_quick_ask_raises_when_cli_missing(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        raise FileNotFoundError(cmd[0])
    monkeypatch.setattr(quick_ask.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="claude CLI not found"):
        quick_ask.run_quick_ask("hi", claude_cli="/nope/claude")


def test_log_quick_ask_writes_jsonl_entry(tmp_path):
    log = tmp_path / "quick-ask-log.jsonl"
    quick_ask.log_quick_ask("hello", "hi there", 142, log_path=log)
    quick_ask.log_quick_ask("again", "yep", 88, log_path=log)

    lines = log.read_text().strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["prompt_text"] == "hello"
    assert first["prompt_chars"] == 5
    assert first["response_text"] == "hi there"
    assert first["response_chars"] == 8
    assert first["latency_ms"] == 142
    assert "timestamp" in first
    second = json.loads(lines[1])
    assert second["prompt_text"] == "again"


def test_log_quick_ask_swallows_write_errors(tmp_path, capsys):
    # Point at a path whose parent cannot be created (a file, not a dir).
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    bad = blocker / "nested" / "log.jsonl"
    quick_ask.log_quick_ask("p", "r", 1, log_path=bad)  # must not raise
    assert "log write failed" in capsys.readouterr().out
