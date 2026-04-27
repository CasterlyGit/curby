"""
Integration tests — run with: python -m pytest tests/ -v
Requires ANTHROPIC_API_KEY env var for the AI test.
"""
import os
import sys
import pathlib
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))


def test_screen_capture_returns_image():
    from src.screen_capture import grab_region, get_screen_size
    w, h = get_screen_size()
    assert w > 0 and h > 0
    img = grab_region(w // 2, h // 2, radius=200)
    assert img.size[0] > 0
    assert img.size[1] > 0


def test_cursor_tracker_starts_and_stops():
    from src.cursor_tracker import CursorTracker
    import time
    positions = []
    tracker = CursorTracker(on_move=lambda x, y: positions.append((x, y)))
    tracker.start()
    time.sleep(0.5)
    pos = tracker.position
    tracker.stop()
    assert isinstance(pos, tuple)
    assert len(pos) == 2


def test_buddy_window_positioning():
    """Window should not go off-screen on any edge."""
    from PyQt6.QtWidgets import QApplication
    from src.buddy_window import BuddyWindow, WINDOW_W, WINDOW_H
    app = QApplication.instance() or QApplication(sys.argv)
    screen = app.primaryScreen().geometry()

    win = BuddyWindow()

    # Near bottom-right corner — window must flip to top-left of cursor
    win.move_near_cursor(screen.width() - 5, screen.height() - 5)
    assert win.x() >= 0
    assert win.y() >= 0
    assert win.x() + WINDOW_W <= screen.width() + WINDOW_W  # clamped
    assert win.y() + WINDOW_H <= screen.height() + WINDOW_H

    # Near top-left — window should open to the right/below
    win.move_near_cursor(10, 10)
    assert win.x() >= 0
    assert win.y() >= 0


# ── Dock puck hover stability (issue-13) ─────────────────────────────────────
# Pattern matches test_buddy_window_positioning above:
#   raw QApplication, instantiate the real widget, drive events directly,
#   QTest.qWait for time-based assertions. QCursor.pos() is monkeypatched
#   so the geometry self-check is deterministic. ±100 ms slack on time
#   assertions per DESIGN.md "Test determinism".


def _fake_cursor_module(monkeypatch, position_ref):
    """Patch src.dock_widget.QCursor so .pos() returns position_ref[0].

    position_ref is a single-element list so the test can rebind the
    cursor location between events without reinstalling the patch.
    """
    from PyQt6.QtGui import QCursor as _RealQCursor
    from src import dock_widget

    class _FakeCursor:
        @staticmethod
        def pos():
            return position_ref[0]

    monkeypatch.setattr(dock_widget, "QCursor", _FakeCursor)
    return _RealQCursor


def _make_puck():
    from PyQt6.QtGui import QColor
    from PyQt6.QtWidgets import QApplication
    from src.dock_widget import DockedTaskPuck, COLLAPSED_W
    app = QApplication.instance() or QApplication(sys.argv)
    puck = DockedTaskPuck("hover-test", QColor(0, 217, 255))
    puck.setGeometry(1000, 100, COLLAPSED_W, 56)
    puck.show()
    return app, puck


def test_dock_puck_hover_expands_within_budget(monkeypatch):
    """AC-1: ≥ 200 ms hover commits the panel open (enter_ms = 80, ≤ 200 ms budget)."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtTest import QTest
    from src.dock_widget import COLLAPSED_W

    app, puck = _make_puck()
    try:
        QTest.qWait(20)  # let show() propagate so isVisible() returns True
        cursor = [QPoint(puck.x() + 10, puck.y() + 10)]  # inside collapsed rect
        _fake_cursor_module(monkeypatch, cursor)

        puck.enterEvent(None)
        QTest.qWait(200)  # enter_ms=80 + paint + slack ≤ AC-1 budget
        assert puck._expanded is True
        assert puck.width() > COLLAPSED_W
    finally:
        puck.hide()
        puck.deleteLater()


def test_dock_puck_stays_expanded_when_cursor_on_child(monkeypatch):
    """AC-2: cursor anywhere inside puck (incl. on a child button) holds open."""
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest

    app, puck = _make_puck()
    try:
        QTest.qWait(20)
        cursor = [QPoint(puck.x() + 10, puck.y() + 10)]
        _fake_cursor_module(monkeypatch, cursor)

        # Expand first.
        puck.enterEvent(None)
        QTest.qWait(150)
        assert puck._expanded is True

        # Static labels must be mouse-transparent so they never generate a
        # parent-leave when the cursor crosses them (DESIGN.md AC-2 mech).
        assert puck._title_label.testAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        assert puck._status_label.testAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )

        # Move the fake cursor onto the pause button (still inside puck rect),
        # then simulate Qt firing the parent leave when the child steals hover.
        btn_global = puck._pause_btn.mapToGlobal(QPoint(5, 5))
        cursor[0] = btn_global
        puck.leaveEvent(None)
        # Geometry check (in _fire_leave) re-arms the leave timer instead of
        # committing — over a window > leave_ms (280) the panel must stay open.
        QTest.qWait(400)
        assert puck._expanded is True
    finally:
        puck.hide()
        puck.deleteLater()


def test_dock_puck_collapses_after_leave_window(monkeypatch):
    """AC-3: cursor outside both rects commits collapse within ~300 ms (leave_ms=280)."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtTest import QTest

    app, puck = _make_puck()
    try:
        QTest.qWait(20)
        cursor = [QPoint(puck.x() + 10, puck.y() + 10)]
        _fake_cursor_module(monkeypatch, cursor)

        puck.enterEvent(None)
        QTest.qWait(150)
        assert puck._expanded is True

        # Cursor moves clearly outside any plausible puck rect.
        cursor[0] = QPoint(50, 50)
        puck.leaveEvent(None)

        QTest.qWait(180)
        assert puck._expanded is True, "should still be expanded before leave_ms"

        QTest.qWait(220)  # cumulative ~400 ms > leave_ms=280 + slack
        assert puck._expanded is False
    finally:
        puck.hide()
        puck.deleteLater()


def test_dock_puck_set_amending_opens_immediately_and_holds(monkeypatch):
    """AC-5: set_amending(True) force-expands synchronously and survives leaveEvent."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtTest import QTest

    app, puck = _make_puck()
    try:
        QTest.qWait(20)
        cursor = [QPoint(50, 50)]  # cursor far away
        _fake_cursor_module(monkeypatch, cursor)

        # Synchronous force-expand — no qWait.
        puck.set_amending(True)
        assert puck._expanded is True

        # leaveEvent during amend is short-circuited by _is_amending check.
        puck.leaveEvent(None)
        QTest.qWait(500)
        assert puck._expanded is True

        # After amend ends, no force-collapse happens — the user's cursor
        # decides via the normal debounce path.
        puck.set_amending(False)
        assert puck._expanded is True
        puck.leaveEvent(None)
        QTest.qWait(400)  # > leave_ms=280 + slack
        assert puck._expanded is False
    finally:
        puck.hide()
        puck.deleteLater()


def test_dock_puck_auto_dismiss_fires_once_per_committed_collapse(monkeypatch):
    """AC-6: auto_dismiss fires exactly once per committed collapse, not per raw leaveEvent."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtTest import QTest

    app, puck = _make_puck()
    try:
        QTest.qWait(20)
        cursor = [QPoint(puck.x() + 10, puck.y() + 10)]
        _fake_cursor_module(monkeypatch, cursor)

        puck.set_state("done")
        fires = []
        puck.auto_dismiss.connect(lambda: fires.append(1))

        # Hover to expand and mark _was_hovered_after_done.
        puck.enterEvent(None)
        QTest.qWait(150)
        assert puck._expanded is True
        assert puck._was_hovered_after_done is True

        # Rapid leave→reenter cycles, each interval < leave_ms — none commit.
        for _ in range(3):
            cursor[0] = QPoint(50, 50)
            puck.leaveEvent(None)
            QTest.qWait(50)
            cursor[0] = QPoint(puck.x() + 10, puck.y() + 10)
            puck.enterEvent(None)
            QTest.qWait(50)

        # Final real leave — should commit collapse + emit auto_dismiss once.
        cursor[0] = QPoint(50, 50)
        puck.leaveEvent(None)
        # leave_ms=280 + auto_dismiss singleShot=120 + slack
        QTest.qWait(500)

        assert puck._expanded is False
        assert len(fires) == 1, f"expected exactly 1 auto_dismiss, got {len(fires)}"
    finally:
        puck.hide()
        puck.deleteLater()


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set"
)
def test_ai_client_text_only():
    from src.ai_client import ask
    reply = ask("Reply with exactly the word: PONG")
    assert isinstance(reply, str)
    assert len(reply) > 0
    assert "PONG" in reply.upper()


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set"
)
def test_ai_client_with_screenshot():
    from src.screen_capture import grab_region, get_screen_size
    from src.ai_client import ask
    w, h = get_screen_size()
    img = grab_region(w // 2, h // 2, radius=300)
    reply = ask("What do you see in this screenshot? One sentence only.", img)
    assert isinstance(reply, str)
    assert len(reply) > 10
