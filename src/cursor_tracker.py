"""Cursor tracker — emits a callback on every mouse move.

Implementation: polls `QCursor.pos()` on a QTimer at ~60Hz. Earlier
versions used `pynput.mouse.Listener`, but on macOS that requires the
**Input Monitoring** permission (separate from Accessibility — granting
Accessibility is enough for keyboard hotkeys but NOT for mouse-move
events). Polling via Qt sidesteps that: `QCursor.pos()` is the OS
public API for cursor location and needs no special grant.

The contract (`__init__(on_move)`, `start()`, `stop()`, `position`
property, callback fires on every detectable move) is unchanged so
callers (`app.CurbyApp`, tests) don't need updating.
"""
from __future__ import annotations

import threading

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtGui import QCursor


_POLL_INTERVAL_MS = 16   # ~60Hz; matches the GhostCursor tick rate


class CursorTracker(QObject):
    """Polls the system cursor position and fires `on_move(x, y)` on every change.

    Lives on the Qt main thread; the callback fires synchronously on that
    thread, so subscribers can update widgets directly without marshaling.
    """

    def __init__(self, on_move):
        super().__init__()
        self._on_move = on_move
        self._x = 0
        self._y = 0
        self._lock = threading.Lock()
        self._timer: QTimer | None = None

    @property
    def position(self) -> tuple[int, int]:
        with self._lock:
            return (self._x, self._y)

    def _poll(self) -> None:
        pos = QCursor.pos()
        x, y = int(pos.x()), int(pos.y())
        moved = False
        with self._lock:
            if x != self._x or y != self._y:
                self._x = x
                self._y = y
                moved = True
        if moved:
            try:
                self._on_move(x, y)
            except Exception:
                # Subscribers crashing should never kill the tracker loop.
                pass

    def start(self) -> None:
        if self._timer is not None:
            return
        # Seed the cached position so the first real move event always fires.
        pos = QCursor.pos()
        with self._lock:
            self._x = int(pos.x())
            self._y = int(pos.y())
        self._timer = QTimer()
        self._timer.timeout.connect(self._poll)
        self._timer.start(_POLL_INTERVAL_MS)

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None
