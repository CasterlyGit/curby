"""RecordingController — owns all recording state and lifecycle.

Extracted from app.py so CurbyApp doesn't have to manage raw threading
primitives. The controller is a pure coordinator: it holds the lock, stop
event, thread, and current target, and emits Qt signals (via the bridge)
from the recorder thread. CurbyApp wires the signals and calls the public
methods; no references back into CurbyApp live here.
"""
import enum
import threading
from dataclasses import dataclass

from src.task_manager import Task


class RecordingTarget(enum.Enum):
    QUICK_ASK = "quick_ask"
    AGENT = "agent"


@dataclass
class RecordingRequest:
    target: RecordingTarget
    task: Task | None = None  # populated only when target == AGENT


class RecordingController:
    """Manages the one-at-a-time voice recording lifecycle.

    Usage::

        ctrl = RecordingController(bridge)
        ctrl.start(RecordingRequest(RecordingTarget.QUICK_ASK))
        ctrl.stop()

    The bridge must expose these signals (same as the existing _Bridge):
        audio_level(float)
        recording_stopped()
        transcription_ready(str, object)
        transcription_error(str)
    """

    def __init__(self, bridge):
        self._bridge = bridge
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._request: RecordingRequest | None = None

    # ── Public interface ──────────────────────────────────────────────────────

    def start(self, request: RecordingRequest) -> bool:
        """Start recording for *request*. Returns False if already recording."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                print("[recording] already recording — ignoring new start")
                return False
            self._stop_event.clear()
            self._request = request

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        """Signal the current recording to stop (user-initiated)."""
        self._stop_event.set()

    def is_recording(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def current_request(self) -> RecordingRequest | None:
        return self._request

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run(self):
        from src.voice_io import record_until_stop

        # Snapshot the request before entering I/O — avoids a TOCTOU if
        # stop+restart happens in quick succession.
        request = self._request

        try:
            text = record_until_stop(
                self._stop_event,
                on_level=self._bridge.audio_level.emit,
                on_recording_stopped=self._bridge.recording_stopped.emit,
            )
        except RuntimeError as e:
            self._bridge.transcription_error.emit(str(e))
            return
        except Exception as e:
            self._bridge.transcription_error.emit(f"recorder: {e}")
            return

        stripped = (text or "").strip()
        if not stripped:
            self._bridge.transcription_error.emit("nothing heard.")
            return

        self._bridge.transcription_ready.emit(stripped, request)
