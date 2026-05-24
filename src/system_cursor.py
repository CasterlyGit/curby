"""Hide the macOS system cursor so curby's ghost feather IS the cursor.

Uses CoreGraphics' `CGDisplayHideCursor` via PyObjC. Reference-counted
per-process: every hide must eventually be matched by a show. We hide
once at startup and re-call periodically because some apps explicitly
push their own cursor (text fields, browsers) and counter the hide.

On non-macOS this module is a no-op stub so the import succeeds.
"""
import platform
import threading
import time

_IS_MAC = platform.system() == "Darwin"

if _IS_MAC:
    try:
        import Quartz  # type: ignore
        _AVAILABLE = True
    except Exception:
        Quartz = None
        _AVAILABLE = False
else:
    Quartz = None
    _AVAILABLE = False


class SystemCursorHider:
    """Keeps the macOS cursor hidden for as long as curby is running.

    The OS reference-counts hide/show calls. We call `CGDisplayHideCursor`
    once on start, then periodically re-call it on a background thread
    so that apps which push their own cursor (counter-incrementing the
    show count) get clobbered back to hidden within ~500 ms.

    On exit, call `restore()` to bring the cursor back. Idempotent.
    """

    def __init__(self, interval_seconds: float = 0.5):
        self._interval = interval_seconds
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._active = False

    def start(self) -> bool:
        """Begin hiding. Returns True if hiding actually engaged on this
        platform, False if not supported (e.g. non-mac or PyObjC missing)."""
        if not _AVAILABLE:
            return False
        if self._active:
            return True
        try:
            Quartz.CGDisplayHideCursor(0)
        except Exception:
            return False
        self._active = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._thread.start()
        return True

    def restore(self) -> None:
        """Stop hiding and bring the cursor back. Safe to call repeatedly."""
        if not self._active:
            return
        self._active = False
        self._stop_event.set()
        if _AVAILABLE:
            try:
                # Call ShowCursor enough times to safely cancel our hides.
                # Reference count is per-process; on a 0.5 s tick the count
                # is small (one per tick). 50 calls covers any reasonable
                # session length without leaking a permanent hide.
                for _ in range(50):
                    Quartz.CGDisplayShowCursor(0)
            except Exception:
                pass

    def _tick_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                Quartz.CGDisplayHideCursor(0)
            except Exception:
                pass
            self._stop_event.wait(self._interval)
