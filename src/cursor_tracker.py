import threading
from pynput import mouse


class CursorTracker:
    """Tracks mouse cursor position and fires a callback on every move."""

    def __init__(self, on_move):
        self._on_move = on_move
        self._x = 0
        self._y = 0
        self._listener = None
        self._lock = threading.Lock()

    @property
    def position(self):
        with self._lock:
            return (self._x, self._y)

    def _handle_move(self, x, y):
        with self._lock:
            self._x = x
            self._y = y
        self._on_move(x, y)

    def start(self):
        self._listener = mouse.Listener(on_move=self._handle_move)
        self._listener.start()

    def stop(self):
        if self._listener:
            self._listener.stop()
            self._listener = None
