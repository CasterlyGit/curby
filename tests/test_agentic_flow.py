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
    """Regression guard: amend while alive must queue (not direct-spawn).

    Existing contract: the original run's on_done is suppressed when the
    queue drains into a re-spawn — only the final continuation calls on_done.
    This keeps the puck in "running" through the chain.
    """
    runner, rec = fake_claude_runner(mode="slow", FAKE_CLAUDE_SLEEP=0.3)
    runner.start()
    time.sleep(0.1)
    assert runner.is_running
    runner.amend("queued")
    assert runner._pending_amends == ["queued"]
    # Exactly one on_done fires when the chain (original + queued) finishes.
    assert rec.wait_for_dones(1, timeout=8.0), f"chain never finished; statuses={rec.statuses}"
    # Give the runtime a beat to ensure no spurious second on_done arrives.
    time.sleep(0.3)
    assert rec.done_count == 1, f"expected exactly 1 on_done for queued chain, got {rec.done_count}"
    argv_log = (runner.workdir / "argv.log").read_text().strip().splitlines()
    assert len(argv_log) == 2, f"expected 2 invocations, got {argv_log}"
    assert "--continue" not in argv_log[0].split()
    assert "--continue" in argv_log[1].split()
    assert "amending…" in rec.statuses


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
    # Need >= 0.1 so max_chunks >= 1 — loop captures at least one frame before exit.
    # Stub stream returns instantly, so wall-clock cost is microseconds.
    monkeypatch.setattr(voice_io, "MAX_SECONDS", 0.2)

    stop = threading.Event()  # never set
    fires = []

    text = voice_io.record_until_stop(
        stop,
        on_recording_stopped=lambda: fires.append(time.time()),
    )
    assert text == "hello"
    assert len(fires) == 1


# ── HoverDebouncer (issue-13) ────────────────────────────────────────────────

from src.dock_widget import HoverDebouncer


class _FakeSignal:
    def __init__(self):
        self._cb = None

    def connect(self, cb):
        self._cb = cb


class _FakeTimer:
    """Stand-in for QTimer. Records start/stop, exposes manual fire()."""

    def __init__(self, parent=None):
        self.active = False
        self.single_shot = False
        self.last_ms: int | None = None
        self.timeout = _FakeSignal()

    def setSingleShot(self, on: bool) -> None:
        self.single_shot = on

    def start(self, ms: int) -> None:
        self.active = True
        self.last_ms = ms

    def stop(self) -> None:
        self.active = False

    def isActive(self) -> bool:
        return self.active

    def fire(self) -> None:
        # Mirror Qt: a stopped single-shot timer never delivers its callback.
        if not self.active:
            return
        self.active = False
        if self.timeout._cb is not None:
            self.timeout._cb()


def _make_debouncer(enter_ms: int = 80, leave_ms: int = 280):
    expands: list[int] = []
    collapses: list[int] = []
    hd = HoverDebouncer(
        None,
        on_expand=lambda: expands.append(1),
        on_collapse=lambda: collapses.append(1),
        enter_ms=enter_ms,
        leave_ms=leave_ms,
        timer_factory=lambda parent: _FakeTimer(parent),
    )
    return hd, expands, collapses


# 14-row decision table from DESIGN.md "Public API / surface".
@pytest.mark.parametrize("setup,event,expected_committed,expected_calls,expected_enter_active,expected_leave_active", [
    # on_enter
    ("none",          "on_enter",      False, [],      True,  False),
    ("enter_armed",   "on_enter",      False, [],      True,  False),
    ("leave_armed",   "on_enter",      True,  [],      False, False),  # committed already True
    ("committed",     "on_enter",      True,  [],      False, False),
    ("committed_leave_armed", "on_enter", True, [],    False, False),
    # on_leave
    ("committed",     "on_leave",      True,  [],      False, True),
    ("committed_leave_armed", "on_leave", True, [],    False, True),
    ("none",          "on_leave",      False, [],      False, False),
    ("enter_armed",   "on_leave",      False, [],      False, False),
    # timer fires
    ("enter_armed",   "fire_enter",    True,  ["exp"], False, False),
    ("committed_leave_armed", "fire_leave", False, ["col"], False, False),
    # force_*
    ("none",          "force_expand",  True,  ["exp"], False, False),
    ("committed",     "force_collapse", False, ["col"], False, False),
    ("enter_armed",   "force_expand",  True,  ["exp"], False, False),
])
def test_hover_debouncer_decision_table(
    setup, event, expected_committed, expected_calls,
    expected_enter_active, expected_leave_active,
):
    hd, expands, collapses = _make_debouncer()
    # Set up the precondition.
    if setup == "none":
        pass
    elif setup == "enter_armed":
        hd.on_enter()
    elif setup == "leave_armed":
        # Treat as the impossible row: committed True with leave armed.
        hd.force_expand()
        # Drop the expand callback so we only track the event-under-test.
        expands.clear()
        hd.on_leave()
    elif setup == "committed":
        hd.force_expand(); expands.clear()
    elif setup == "committed_leave_armed":
        hd.force_expand(); expands.clear(); hd.on_leave()
    else:
        raise AssertionError(f"unknown setup: {setup}")

    # Apply the event.
    if event == "on_enter":
        hd.on_enter()
    elif event == "on_leave":
        hd.on_leave()
    elif event == "fire_enter":
        hd._enter_timer.fire()
    elif event == "fire_leave":
        hd._leave_timer.fire()
    elif event == "force_expand":
        hd.force_expand()
    elif event == "force_collapse":
        hd.force_collapse()
    else:
        raise AssertionError(f"unknown event: {event}")

    calls = ["exp"] * len(expands) + ["col"] * len(collapses)
    assert hd.committed is expected_committed, (setup, event, hd.committed)
    assert calls == expected_calls, (setup, event, calls)
    assert hd._enter_timer.isActive() is expected_enter_active
    assert hd._leave_timer.isActive() is expected_leave_active


def test_hover_debouncer_enter_commits_after_enter_ms():
    hd, expands, _ = _make_debouncer()
    hd.on_enter()
    assert hd._enter_timer.isActive() and hd._enter_timer.last_ms == 80
    assert hd.committed is False
    hd._enter_timer.fire()
    assert hd.committed is True
    assert expands == [1]


def test_hover_debouncer_leave_commits_after_leave_ms():
    hd, _, collapses = _make_debouncer()
    hd.force_expand()
    hd.on_leave()
    assert hd._leave_timer.isActive() and hd._leave_timer.last_ms == 280
    assert hd.committed is True
    hd._leave_timer.fire()
    assert hd.committed is False
    assert collapses == [1]


def test_hover_debouncer_reenter_cancels_collapse():
    """AC-3: re-entering the rect before the leave timer commits drops the collapse."""
    hd, _, collapses = _make_debouncer()
    hd.force_expand()
    hd.on_leave()
    assert hd._leave_timer.isActive()
    hd.on_enter()
    assert hd._leave_timer.isActive() is False
    # Even if the timer "fires" stale, _fire_leave is a no-op when committed
    # is True (which it still is, since the leave never committed).
    hd._leave_timer.fire()
    assert collapses == []
    assert hd.committed is True


def test_hover_debouncer_flyby_cancels_pending_expand():
    """on_enter then on_leave before enter_ms must NOT commit an expand.

    Real Qt won't deliver a stopped single-shot timer's callback, so the
    contract we pin at this layer is: after on_leave, the enter timer is
    stopped — and hd.committed is still False.
    """
    hd, expands, _ = _make_debouncer()
    hd.on_enter()
    assert hd._enter_timer.isActive()
    hd.on_leave()
    assert hd._enter_timer.isActive() is False
    assert hd.committed is False
    assert expands == []


def test_hover_debouncer_force_expand_bypasses_enter_timer():
    """AC-5: force_expand commits synchronously; both timers stopped."""
    hd, expands, _ = _make_debouncer()
    hd.on_enter()
    hd.force_expand()
    assert hd.committed is True
    assert expands == [1]
    assert hd._enter_timer.isActive() is False
    assert hd._leave_timer.isActive() is False
    # A subsequent on_leave then arms the leave timer normally.
    hd.on_leave()
    assert hd._leave_timer.isActive() and hd._leave_timer.last_ms == 280


def test_hover_debouncer_force_collapse_cancels_both_timers():
    hd, expands, collapses = _make_debouncer()
    hd.force_expand(); expands.clear()
    hd.on_leave()
    hd.force_collapse()
    assert hd.committed is False
    assert collapses == [1]
    assert hd._enter_timer.isActive() is False
    assert hd._leave_timer.isActive() is False
    # Idempotent if already collapsed.
    hd.force_collapse()
    assert collapses == [1]


def test_hover_debouncer_cancel_pending_preserves_committed_state():
    """set_amending(False)'s use case: drop in-flight enter without flipping state."""
    hd, expands, _ = _make_debouncer()
    hd.on_enter()
    hd.cancel_pending()
    assert hd.committed is False
    assert hd._enter_timer.isActive() is False
    assert expands == []
    # Same for committed=True with a queued leave.
    hd.force_expand(); expands.clear()
    hd.on_leave()
    hd.cancel_pending()
    assert hd.committed is True
    assert hd._leave_timer.isActive() is False


def test_hover_debouncer_boundary_sweep_single_transition():
    """AC-4: a 2 s edge sweep commits ≤ 1 transition in each direction.

    Drive the canonical sweep [enter, leave, enter, leave, enter] without
    letting any timer 'fire' (mimics the cursor never resting outside the
    debounce window). Both expand and collapse counts must stay 0.
    """
    hd, expands, collapses = _make_debouncer()
    for ev in ("enter", "leave", "enter", "leave", "enter"):
        if ev == "enter":
            hd.on_enter()
        else:
            hd.on_leave()
    assert expands == []
    assert collapses == []
    # Now let the final enter timer commit — that's the single allowed expand.
    hd._enter_timer.fire()
    assert expands == [1]
    assert collapses == []


def test_hover_debouncer_repeated_force_expand_idempotent():
    hd, expands, _ = _make_debouncer()
    hd.force_expand()
    hd.force_expand()
    assert expands == [1]


def test_hover_debouncer_fire_leave_rearms_when_predicate_blocks():
    """Cursor-lag backstop: _fire_leave re-arms instead of collapsing while
    the should_commit_collapse predicate returns False."""
    expands: list[int] = []
    collapses: list[int] = []
    cursor_outside = [False]
    hd = HoverDebouncer(
        None,
        on_expand=lambda: expands.append(1),
        on_collapse=lambda: collapses.append(1),
        should_commit_collapse=lambda: cursor_outside[0],
        timer_factory=lambda parent: _FakeTimer(parent),
    )
    hd.force_expand(); expands.clear()
    hd.on_leave()
    # Predicate says cursor still inside — fire should re-arm, not collapse.
    hd._leave_timer.fire()
    assert collapses == []
    assert hd.committed is True
    assert hd._leave_timer.isActive() is True
    # Cursor leaves for real — next fire should commit.
    cursor_outside[0] = True
    hd._leave_timer.fire()
    assert collapses == [1]
    assert hd.committed is False


def test_relayout_skips_expanded_pucks():
    """Pin the t.puck.width() == COLLAPSED_W guard at task_manager.py:_relayout.

    Spec Kit regression test: the hover fix MUST NOT regress the rule that
    _relayout never moves a puck whose panel is currently open.
    """
    from PyQt6.QtWidgets import QApplication
    from src.dock_widget import COLLAPSED_W, EXPANDED_W
    from src.task_manager import TaskManager

    app = QApplication.instance() or QApplication(sys.argv)

    tm = TaskManager()

    class _FakePuck:
        def __init__(self, w):
            self._w = w
            self._geom = (0, 0, w, 56)
            self._visible = True
        def width(self): return self._w
        def setGeometry(self, x, y, w, h): self._geom = (x, y, w, h)
        def show(self): self._visible = True
        def hide(self): self._visible = False
        def isVisible(self): return self._visible

    class _FakeTask:
        def __init__(self, w):
            self.puck = _FakePuck(w)

    expanded = _FakeTask(EXPANDED_W)
    collapsed = _FakeTask(COLLAPSED_W)
    expanded.puck._geom = (123, 456, EXPANDED_W, 56)  # arbitrary current pos
    tm._tasks = [expanded, collapsed]

    tm._relayout()

    # Expanded puck must be untouched.
    assert expanded.puck._geom == (123, 456, EXPANDED_W, 56)
    # Collapsed puck must have been repositioned.
    assert collapsed.puck._geom != (0, 0, COLLAPSED_W, 56)


# ── AgentRunner companion thread (issue-13) ──────────────────────────────────

def test_done_event_prevents_double_on_done(fake_claude_runner):
    """_done_event guard: on_done fires exactly once for a normal clean run."""
    runner, rec = fake_claude_runner()
    runner.start()
    assert rec.wait_for_dones(1, timeout=5.0), f"on_done timed out; statuses={rec.statuses}"
    # Give companion thread time to also reach its guard check.
    time.sleep(0.3)
    assert rec.done_count == 1, f"expected exactly 1 on_done, got {rec.done_count}"


def test_companion_thread_closes_hung_stdout(fake_claude_runner):
    """Companion thread unblocks the reader when a grandchild keeps stdout open.

    'hangs_stdout' mode: fake_claude spawns a sleeping child that inherits the
    stdout pipe fd, then exits. Without the companion thread the reader would
    block forever; the companion forces proc.stdout.close() so the reader exits.
    """
    runner, rec = fake_claude_runner(mode="hangs_stdout")
    runner.start()
    assert rec.wait_for_dones(1, timeout=5.0), (
        f"on_done timed out — companion thread may not be closing stdout; "
        f"statuses={rec.statuses}"
    )
    assert rec.dones[0] == 0


# ── TaskManager.check_hover (issue-13) ───────────────────────────────────────

def _make_hover_task(rect, *, visible=True, expanded=False):
    """Build a minimal fake Task whose puck supports check_hover's interface."""
    from PyQt6.QtCore import QRect

    enter_calls = []
    leave_calls = []

    class _FakeHover:
        def on_enter(self):
            enter_calls.append(1)

        def on_leave(self):
            leave_calls.append(1)

    class _FakePuckForHover:
        def __init__(self):
            self._is_amending = False
            self._hover = _FakeHover()

        def isVisible(self):
            return visible

        def frameGeometry(self):
            return rect

        def panel_global_rect(self):
            return rect if expanded else QRect()

    class _FakeTaskForHover:
        def __init__(self):
            self.puck = _FakePuckForHover()

    task = _FakeTaskForHover()
    return task, enter_calls, leave_calls


def test_check_hover_calls_on_enter_inside_puck():
    """AC-2: check_hover with point inside the puck rect calls on_enter."""
    from PyQt6.QtCore import QPoint, QRect
    from PyQt6.QtWidgets import QApplication
    from src.task_manager import TaskManager

    app = QApplication.instance() or QApplication(sys.argv)
    tm = TaskManager()

    rect = QRect(900, 100, 56, 56)
    task, enters, leaves = _make_hover_task(rect, visible=True)
    tm._tasks = [task]

    # Point inside the puck rect.
    tm.check_hover(920, 120)
    assert enters == [1]
    assert leaves == []


def test_check_hover_calls_on_leave_outside():
    """AC-3: check_hover with point outside puck and panel calls on_leave."""
    from PyQt6.QtCore import QPoint, QRect
    from PyQt6.QtWidgets import QApplication
    from src.task_manager import TaskManager

    app = QApplication.instance() or QApplication(sys.argv)
    tm = TaskManager()

    rect = QRect(900, 100, 56, 56)
    task, enters, leaves = _make_hover_task(rect, visible=True)
    tm._tasks = [task]

    # Point clearly outside.
    tm.check_hover(50, 50)
    assert leaves == [1]
    assert enters == []


def test_check_hover_skips_hidden_pucks():
    """check_hover must not call on_enter or on_leave for hidden pucks."""
    from PyQt6.QtCore import QRect
    from PyQt6.QtWidgets import QApplication
    from src.task_manager import TaskManager

    app = QApplication.instance() or QApplication(sys.argv)
    tm = TaskManager()

    rect = QRect(900, 100, 56, 56)
    task, enters, leaves = _make_hover_task(rect, visible=False)
    tm._tasks = [task]

    # Even with cursor inside the rect, hidden puck is skipped entirely.
    tm.check_hover(920, 120)
    assert enters == []
    assert leaves == []


def test_check_hover_calls_on_enter_inside_expanded_panel():
    """AC-2: cursor inside the expanded panel rect also calls on_enter."""
    from PyQt6.QtCore import QRect
    from PyQt6.QtWidgets import QApplication
    from src.task_manager import TaskManager

    app = QApplication.instance() or QApplication(sys.argv)
    tm = TaskManager()

    # When expanded, panel_global_rect() returns the same full rect as frameGeometry().
    # Use a wider rect to simulate expanded state.
    rect = QRect(636, 100, 336, 56)  # COLLAPSED_W + PANEL_W wide
    task, enters, leaves = _make_hover_task(rect, visible=True, expanded=True)
    tm._tasks = [task]

    # Point in the panel area (left side of expanded rect).
    tm.check_hover(650, 120)
    assert enters == [1]
    assert leaves == []
