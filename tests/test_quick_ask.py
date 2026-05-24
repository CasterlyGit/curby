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
    monkeypatch.setattr(quick_ask, "SESSION_PATH", tmp_path / "session.json")
    monkeypatch.setenv("HOME", str(tmp_path))
    yield


# ── One-shot fallback path (no worker) ─────────────────────────────────────

def test_one_shot_returns_reply_latency_and_followup_flag(monkeypatch):
    captured = {}
    def fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="hello world.\n", stderr="")
    monkeypatch.setattr(quick_ask.subprocess, "run", fake_run)

    reply, latency_ms, was_followup = quick_ask.run_quick_ask("hi", claude_cli="/usr/bin/claude")
    assert reply == "hello world."
    assert latency_ms >= 0
    assert was_followup is False
    assert "--model" in captured["cmd"] and "haiku" in captured["cmd"]


def test_one_shot_raises_on_nonzero_exit(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")
    monkeypatch.setattr(quick_ask.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="claude exited 1"):
        quick_ask.run_quick_ask("hi", claude_cli="/usr/bin/claude")


def test_one_shot_raises_on_empty_output(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        return subprocess.CompletedProcess(cmd, 0, stdout="   \n", stderr="")
    monkeypatch.setattr(quick_ask.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="no output"):
        quick_ask.run_quick_ask("hi", claude_cli="/usr/bin/claude")


def test_one_shot_raises_on_timeout(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)
    monkeypatch.setattr(quick_ask.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="timed out"):
        quick_ask.run_quick_ask("hi", claude_cli="/usr/bin/claude", timeout=1.0)


def test_one_shot_raises_when_cli_missing(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        raise FileNotFoundError(cmd[0])
    monkeypatch.setattr(quick_ask.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="claude CLI not found"):
        quick_ask.run_quick_ask("hi", claude_cli="/nope/claude")


# ── Worker path ────────────────────────────────────────────────────────────

class _FakeWorker:
    """Stand-in for ClaudeWorker used in tests."""
    def __init__(self, replies=None, errors=None):
        self.replies = replies or ["worker reply"]
        self.errors = errors or []
        self.calls = []

    def ask(self, text, *, timeout=30.0):
        self.calls.append(text)
        if self.errors:
            err = self.errors.pop(0)
            if err:
                raise RuntimeError(err)
        return self.replies.pop(0), 1234


def test_worker_path_uses_worker_not_subprocess(monkeypatch):
    def fake_run(*a, **kw):
        raise AssertionError("subprocess.run should NOT be called when a worker is provided")
    monkeypatch.setattr(quick_ask.subprocess, "run", fake_run)

    worker = _FakeWorker(replies=["from the worker."])
    reply, latency_ms, was_followup = quick_ask.run_quick_ask("hi", worker=worker)
    assert reply == "from the worker."
    assert latency_ms == 1234
    assert was_followup is False
    assert worker.calls == ["hi"]


def test_worker_dead_falls_back_to_one_shot(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        return subprocess.CompletedProcess(cmd, 0, stdout="fallback ok.\n", stderr="")
    monkeypatch.setattr(quick_ask.subprocess, "run", fake_run)

    worker = _FakeWorker(errors=["worker died"], replies=[])
    reply, latency_ms, _ = quick_ask.run_quick_ask("hi", worker=worker, claude_cli="/usr/bin/claude")
    assert reply == "fallback ok."
    assert latency_ms >= 0


def test_followup_flag_flips_within_window(monkeypatch):
    monkeypatch.setattr(quick_ask.subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("shouldn't run")))
    worker = _FakeWorker(replies=["one", "two"])
    _, _, first = quick_ask.run_quick_ask("first", worker=worker)
    _, _, second = quick_ask.run_quick_ask("second", worker=worker)
    assert first is False
    assert second is True


def test_followup_flag_resets_after_window(monkeypatch):
    monkeypatch.setattr(quick_ask, "FOLLOWUP_WINDOW_SECONDS", 0.01)
    worker = _FakeWorker(replies=["one", "two"])
    _, _, first = quick_ask.run_quick_ask("first", worker=worker)
    time.sleep(0.05)
    _, _, second = quick_ask.run_quick_ask("second", worker=worker)
    assert first is False
    assert second is False


# ── Logging ────────────────────────────────────────────────────────────────

def test_log_quick_ask_writes_jsonl_entry(tmp_path):
    log = tmp_path / "quick-ask-log.jsonl"
    quick_ask.log_quick_ask("hello", "hi there", 142, log_path=log)
    quick_ask.log_quick_ask("again", "yep", 88, was_followup=True, log_path=log)

    lines = log.read_text().strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["prompt_text"] == "hello"
    assert first["was_followup"] is False
    second = json.loads(lines[1])
    assert second["was_followup"] is True


def test_log_quick_ask_swallows_write_errors(tmp_path, capsys):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    bad = blocker / "nested" / "log.jsonl"
    quick_ask.log_quick_ask("p", "r", 1, log_path=bad)
    assert "log write failed" in capsys.readouterr().out
