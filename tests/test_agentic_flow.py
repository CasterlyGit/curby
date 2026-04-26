"""Headless coverage of curby's agentic flow.

Pins the contracts the live pipeline depends on:

  - `_status_from_event` mapping (table-driven, no I/O).
  - `PTTListener` toggle re-arm under tap/hold/mash sequences (no real listener).
  - `AgentRunner` lifecycle, amend-after-done, and cancel-drops-queue against
    a fake `claude` script (`tests/fixtures/fake_claude.py`).
  - `voice_io.record_until_stop`'s `on_recording_stopped` callback fires on
    every exit path (user-stop AND MAX_SECONDS cap).

No microphone, no display, no network, no real `claude` binary.
"""
import json
import pathlib
import sys
import threading
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from src import agent_runner
from src.agent_runner import AgentRunner, _status_from_event
from src.ptt_listener import PTTListener


FAKE_CLAUDE = pathlib.Path(__file__).parent / "fixtures" / "fake_claude.py"


# ── _status_from_event table (AC-4) ──────────────────────────────────────────

@pytest.mark.parametrize("event,expected", [
    ({"type": "system", "subtype": "init"}, "thinking…"),
    ({"type": "system", "subtype": "other"}, None),
    (
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls -la"}}
        ]}},
        "using Bash · ls -la",
    ),
    (
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/tmp/x.py"}}
        ]}},
        "using Read · x.py",
    ),
    (
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Grep", "input": {"pattern": "foo"}}
        ]}},
        "using Grep · 'foo'",
    ),
    (
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "line one\nline two"}
        ]}},
        "line one",
    ),
    (
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "content": "ok"}
        ]}},
        "got result",
    ),
    ({"type": "result", "subtype": "success", "result": "all done"}, "all done"),
    ({"type": "result", "subtype": "success", "result": ""}, "done"),
    ({"type": "result", "subtype": "error_during_execution"}, "error: error_during_execution"),
    ({"type": "unknown_type"}, None),
])
def test_status_from_event_table(event, expected):
    assert _status_from_event(event) == expected


# ── PTTListener (AC-5) ───────────────────────────────────────────────────────

def _ptt_with_counter():
    from pynput import keyboard
    fires = []
    listener = PTTListener(on_toggle=lambda: fires.append(time.time()))
    return listener, fires, keyboard.Key


def test_ptt_listener_single_tap_fires_once():
    listener, fires, K = _ptt_with_counter()
    listener._handle_press(K.ctrl)
    listener._handle_press(K.space)
    listener._handle_release(K.space)
    listener._handle_release(K.ctrl)
    assert len(fires) == 1


def test_ptt_listener_tap_tap_fires_twice():
    listener, fires, K = _ptt_with_counter()
    for _ in range(2):
        listener._handle_press(K.ctrl)
        listener._handle_press(K.space)
        listener._handle_release(K.space)
        listener._handle_release(K.ctrl)
    assert len(fires) == 2


def test_ptt_listener_hold_ctrl_tap_space_twice():
    """Holding ctrl across two space taps should fire twice — re-arm on space release."""
    listener, fires, K = _ptt_with_counter()
    listener._handle_press(K.ctrl)
    listener._handle_press(K.space)
    listener._handle_release(K.space)
    listener._handle_press(K.space)
    listener._handle_release(K.space)
    listener._handle_release(K.ctrl)
    assert len(fires) == 2


def test_ptt_listener_out_of_order_chord_build():
    """Pressing space before ctrl should still fire once when chord becomes full."""
    listener, fires, K = _ptt_with_counter()
    listener._handle_press(K.space)
    listener._handle_press(K.ctrl)
    listener._handle_release(K.ctrl)
    listener._handle_release(K.space)
    assert len(fires) == 1


def test_ptt_listener_collapses_left_right_modifiers():
    """ctrl_l and ctrl_r should canonicalize to the same key — no double-fire."""
    listener, fires, K = _ptt_with_counter()
    listener._handle_press(K.ctrl_l)
    listener._handle_press(K.space)
    listener._handle_press(K.ctrl_r)
    assert len(fires) == 1
    listener._handle_release(K.space)
    listener._handle_release(K.ctrl_r)
    listener._handle_release(K.ctrl_l)
    assert len(fires) == 1


# ── AgentRunner lifecycle via fake-claude ────────────────────────────────────

class _Recorder:
    """Collects on_event/on_status/on_done callbacks for assertion."""

    def __init__(self):
        self.events: list[dict] = []
        self.statuses: list[str] = []
        self.dones: list[int] = []
        self._lock = threading.Lock()

    def on_event(self, e):
        self.events.append(e)

    def on_status(self, s):
        self.statuses.append(s)

    def on_done(self, rc):
        with self._lock:
            self.dones.append(rc)

    @property
    def done_count(self) -> int:
        with self._lock:
            return len(self.dones)

    def wait_for_dones(self, n: int, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.done_count >= n:
                return True
            time.sleep(0.02)
        return self.done_count >= n


@pytest.fixture
def fake_claude_runner(monkeypatch, tmp_path):
    """Returns a factory that builds an AgentRunner wired to fake-claude.

    Isolates TASKS_ROOT into tmp_path so we don't pollute ~/curby-tasks.
    """
    monkeypatch.setattr(agent_runner, "_CLAUDE", str(FAKE_CLAUDE))
    monkeypatch.setattr(agent_runner, "TASKS_ROOT", tmp_path / "tasks")

    def _make(prompt="do a thing", mode="success", **env):
        monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
        for k, v in env.items():
            monkeypatch.setenv(k, str(v))
        rec = _Recorder()
        runner = AgentRunner(
            prompt,
            on_event=rec.on_event,
            on_status=rec.on_status,
            on_done=rec.on_done,
        )
        return runner, rec

    return _make


def test_agent_runner_lifecycle_success(fake_claude_runner):
    runner, rec = fake_claude_runner()
    runner.start()
    assert rec.wait_for_dones(1, timeout=5.0), f"timed out; statuses={rec.statuses}"
    assert rec.dones[0] == 0
    s = rec.statuses
    assert s[0] == "starting…"
    assert "thinking…" in s
    assert any(x.startswith("using Bash") for x in s)
    assert "got result" in s
    assert any(x.startswith("using Read") for x in s)
    assert s[-1] in ("all done", "done")
    assert runner.workdir is not None
    assert runner.workdir.exists()


def test_agent_runner_amend_after_done_respawns(fake_claude_runner):
    """AC-1: amend after on_done fires must re-spawn with --continue."""
    runner, rec = fake_claude_runner()
    runner.start()
    assert rec.wait_for_dones(1, timeout=5.0), f"first done timed out; statuses={rec.statuses}"
    assert rec.dones[0] == 0

    runner.amend("more please")
    assert rec.wait_for_dones(2, timeout=3.0), f"amend re-spawn never finished; statuses={rec.statuses}"
    assert rec.dones[1] == 0

    argv_log = (runner.workdir / "argv.log").read_text().strip().splitlines()
    assert len(argv_log) == 2, f"expected 2 invocations, got {argv_log}"
    assert "--continue" not in argv_log[0].split(), f"first invocation should not have --continue: {argv_log[0]}"
    assert "--continue" in argv_log[1].split(), f"second invocation lacks --continue: {argv_log[1]}"
    assert "amending…" in rec.statuses


def test_agent_runner_cancel_drops_queue(fake_claude_runner):
    """AC-2: cancel kills the queue and prevents further amend-driven spawns."""
    runner, rec = fake_claude_runner(mode="slow", FAKE_CLAUDE_SLEEP=2.0)
    runner.start()
    time.sleep(0.1)
    runner.amend("a")
    runner.amend("b")
    runner.cancel()

    assert rec.wait_for_dones(1, timeout=3.0), f"cancel didn't terminate; statuses={rec.statuses}"
    assert rec.dones[0] != 0
    assert "cancelled" in rec.statuses
    assert "amending…" not in rec.statuses

    pre_len = len(rec.statuses)
    runner.amend("c")
    time.sleep(0.5)
    assert len(rec.statuses) == pre_len, f"amend after cancel produced new statuses: {rec.statuses[pre_len:]}"
    assert rec.done_count == 1, "no further on_done should fire after cancel"


def test_agent_runner_amend_during_running_uses_queue(fake_claude_runner):
    """Regression guard: amend while alive must queue and re-spawn from _read_loop drain."""
    runner, rec = fake_claude_runner(mode="slow", FAKE_CLAUDE_SLEEP=1.0)
    runner.start()
    time.sleep(0.1)
    assert runner.is_running
    runner.amend("queued")
    # Contract: no double-spawn while live; the amend must be in the queue.
    assert runner._pending_amends == ["queued"]
    # Both the original and the queued amend should complete: 2 on_done calls total.
    assert rec.wait_for_dones(2, timeout=8.0), f"second spawn never fired; statuses={rec.statuses}"
    argv_log = (runner.workdir / "argv.log").read_text().strip().splitlines()
    assert len(argv_log) == 2
    assert "--continue" in argv_log[1].split()


# ── voice_io.record_until_stop on_recording_stopped (AC-3) ──────────────────

class _SilentStream:
    """Context-manager stub that mimics sounddevice.InputStream."""

    def __init__(self, *a, **kw):
        import numpy as np
        self._np = np

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, chunk):
        # Return silent int16 frames matching the requested chunk size
        return self._np.zeros((chunk, 1), dtype="int16"), False


def _patch_voice_io(monkeypatch):
    from src import voice_io
    monkeypatch.setattr(voice_io.sd, "InputStream", _SilentStream)

    class _FakeRecognizer:
        def record(self, source):
            return "audio"

        def recognize_google(self, audio):
            return "hello"

    monkeypatch.setattr(voice_io.sr, "Recognizer", _FakeRecognizer)

    class _FakeAudioFile:
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(voice_io.sr, "AudioFile", _FakeAudioFile)
    return voice_io


def test_record_until_stop_fires_on_recording_stopped_user_stop(monkeypatch):
    """AC-3 (user-stop path): the callback must fire exactly once."""
    voice_io = _patch_voice_io(monkeypatch)

    stop = threading.Event()
    fires = []

    def runner():
        return voice_io.record_until_stop(
            stop,
            on_recording_stopped=lambda: fires.append(time.time()),
        )

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    time.sleep(0.2)
    stop.set()
    t.join(timeout=3.0)
    assert not t.is_alive(), "record_until_stop never returned"
    assert len(fires) == 1


def test_record_until_stop_fires_on_recording_stopped_max_seconds(monkeypatch):
    """AC-3 (timeout path): the callback must fire when MAX_SECONDS hits."""
    voice_io = _patch_voice_io(monkeypatch)
    monkeypatch.setattr(voice_io, "MAX_SECONDS", 0.05)

    stop = threading.Event()  # never set
    fires = []

    text = voice_io.record_until_stop(
        stop,
        on_recording_stopped=lambda: fires.append(time.time()),
    )
    assert text == "hello"
    assert len(fires) == 1
