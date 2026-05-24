"""Headless coverage of the quick-ask module — mocks the `claude` subprocess
and a temp log path so we never hit the real CLI or the user's home dir."""
import json
import pathlib
import subprocess
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from src import quick_ask


@pytest.fixture(autouse=True)
def _isolate_session(tmp_path, monkeypatch):
    """Every test gets its own session file + sessions root, so no test
    leaks state into another."""
    monkeypatch.setattr(quick_ask, "SESSION_PATH", tmp_path / "session.json")
    monkeypatch.setenv("HOME", str(tmp_path))  # for _resolve_session's fresh-workdir path
    yield


def test_run_quick_ask_returns_reply_latency_and_followup_flag(monkeypatch):
    captured = {}
    def fake_run(cmd, capture_output, text, timeout, cwd):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return subprocess.CompletedProcess(cmd, 0, stdout="WebSockets are persistent full-duplex connections.\n", stderr="")
    monkeypatch.setattr(quick_ask.subprocess, "run", fake_run)

    reply, latency_ms, was_followup = quick_ask.run_quick_ask("what are websockets", claude_cli="/usr/bin/claude")
    assert reply == "WebSockets are persistent full-duplex connections."
    assert latency_ms >= 0
    assert was_followup is False
    # First call uses --model haiku and embeds the system prompt
    assert "--model" in captured["cmd"]
    assert "haiku" in captured["cmd"]
    assert "Question: what are websockets" in captured["cmd"][-1]
    assert "--continue" not in captured["cmd"]


def test_second_call_within_window_uses_continue(monkeypatch):
    cmds = []
    def fake_run(cmd, capture_output, text, timeout, cwd):
        cmds.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="reply\n", stderr="")
    monkeypatch.setattr(quick_ask.subprocess, "run", fake_run)

    _, _, first_followup = quick_ask.run_quick_ask("first", claude_cli="/usr/bin/claude")
    _, _, second_followup = quick_ask.run_quick_ask("second", claude_cli="/usr/bin/claude")

    assert first_followup is False
    assert second_followup is True
    # Second call should include --continue and send the raw question (no system prompt)
    assert "--continue" in cmds[1]
    assert cmds[1][-1] == "second"
    # And the cwd of the second call should equal the cwd of the first (session reuse)
    # (we don't capture cwd in this fixture's fake_run; verified by behavior — was_followup=True)


def test_second_call_after_window_starts_fresh(monkeypatch):
    cmds = []
    def fake_run(cmd, capture_output, text, timeout, cwd):
        cmds.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="reply\n", stderr="")
    monkeypatch.setattr(quick_ask.subprocess, "run", fake_run)
    monkeypatch.setattr(quick_ask, "FOLLOWUP_WINDOW_SECONDS", 0.01)  # expire immediately

    quick_ask.run_quick_ask("first", claude_cli="/usr/bin/claude")
    time.sleep(0.05)
    _, _, was_followup = quick_ask.run_quick_ask("second", claude_cli="/usr/bin/claude")

    assert was_followup is False
    assert "--continue" not in cmds[1]


def test_run_quick_ask_raises_on_nonzero_exit(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout, cwd):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")
    monkeypatch.setattr(quick_ask.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="claude exited 1"):
        quick_ask.run_quick_ask("hi", claude_cli="/usr/bin/claude")


def test_run_quick_ask_raises_on_empty_output(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout, cwd):
        return subprocess.CompletedProcess(cmd, 0, stdout="   \n", stderr="")
    monkeypatch.setattr(quick_ask.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="no output"):
        quick_ask.run_quick_ask("hi", claude_cli="/usr/bin/claude")


def test_run_quick_ask_raises_on_timeout(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout, cwd):
        raise subprocess.TimeoutExpired(cmd, timeout)
    monkeypatch.setattr(quick_ask.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="timed out"):
        quick_ask.run_quick_ask("hi", claude_cli="/usr/bin/claude", timeout=1.0)


def test_run_quick_ask_raises_when_cli_missing(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout, cwd):
        raise FileNotFoundError(cmd[0])
    monkeypatch.setattr(quick_ask.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="claude CLI not found"):
        quick_ask.run_quick_ask("hi", claude_cli="/nope/claude")


def test_failed_continue_clears_session(monkeypatch):
    calls = {"n": 0}
    def fake_run(cmd, capture_output, text, timeout, cwd):
        calls["n"] += 1
        if "--continue" in cmd:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no session")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")
    monkeypatch.setattr(quick_ask.subprocess, "run", fake_run)

    # First call seeds a session.
    quick_ask.run_quick_ask("first", claude_cli="/usr/bin/claude")
    assert quick_ask.SESSION_PATH.exists()
    # Second call uses --continue but the (fake) claude rejects it — session cleared.
    with pytest.raises(RuntimeError):
        quick_ask.run_quick_ask("second", claude_cli="/usr/bin/claude")
    assert not quick_ask.SESSION_PATH.exists()


def test_log_quick_ask_writes_jsonl_entry(tmp_path):
    log = tmp_path / "quick-ask-log.jsonl"
    quick_ask.log_quick_ask("hello", "hi there", 142, log_path=log)
    quick_ask.log_quick_ask("again", "yep", 88, was_followup=True, log_path=log)

    lines = log.read_text().strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["prompt_text"] == "hello"
    assert first["prompt_chars"] == 5
    assert first["response_text"] == "hi there"
    assert first["response_chars"] == 8
    assert first["latency_ms"] == 142
    assert first["was_followup"] is False
    assert "timestamp" in first
    second = json.loads(lines[1])
    assert second["was_followup"] is True


def test_log_quick_ask_swallows_write_errors(tmp_path, capsys):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    bad = blocker / "nested" / "log.jsonl"
    quick_ask.log_quick_ask("p", "r", 1, log_path=bad)  # must not raise
    assert "log write failed" in capsys.readouterr().out
