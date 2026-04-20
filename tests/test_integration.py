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
