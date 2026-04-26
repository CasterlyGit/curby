"""Curby — voice-driven agent dispatcher.

Tap Ctrl+Space → mic records, voice indicator at the cursor lights up
and reacts to your audio level. Tap again → utterance is transcribed and a new
Claude CLI agent is spawned in its own sandbox dir. Tasks dock on the right
edge with hover-expand controls (pause / cancel / amend).

The old animation / on-screen guidance pipeline is retired from this active
path; the files (ghost_cursor / guide_path / action_highlight / etc.) stay
on disk for a future "show me how to..." mode.
"""
import sys
import threading

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication

from src.cursor_tracker import CursorTracker
from src.mac_window import make_always_visible
from src.ptt_listener import PTTListener
from src.task_manager import TaskManager, Task
from src.text_input_popup import TextInputPopup
from src.voice_indicator import VoiceIndicator

HOTKEY_TYPE = "<ctrl>+."     # alternate input: type the prompt instead of speaking
HOTKEY_QUIT = "<esc>"        # hard stop


class _Bridge(QObject):
    """Marshal background-thread events onto the Qt main thread."""
    cursor_moved        = pyqtSignal(int, int)
    ptt_toggled         = pyqtSignal()
    audio_level         = pyqtSignal(float)
    recording_stopped   = pyqtSignal()              # mic loop exited (any cause)
    transcription_ready = pyqtSignal(str, object)   # text, target_task (None = new task)
    transcription_error = pyqtSignal(str)
    type_hotkey_fired   = pyqtSignal()
    quit_hotkey_fired   = pyqtSignal()


class CurbyApp:
    def __init__(self):
        self._qt = QApplication.instance() or QApplication(sys.argv)
        self._bridge = _Bridge()

        self._voice = VoiceIndicator()
        self._tasks = TaskManager()
        self._tasks.task_amend_start.connect(self._on_amend_start)
        self._tasks.task_amend_stop.connect(self._on_amend_stop)

        self._text_popup = TextInputPopup()
        self._text_popup.submitted.connect(self._on_text_submitted)

        self._cx = 0
        self._cy = 0
        self._cursor = CursorTracker(on_move=self._on_cursor_move)

        # Recording state. Only one recording at a time; the target tells us
        # where the transcribed text goes (None = spawn a new task).
        self._record_lock = threading.Lock()
        self._record_stop = threading.Event()
        self._record_thread: threading.Thread | None = None
        self._record_target: Task | None = None

        # Hotkeys — toggle: tap chord to start, tap again to send.
        self._ptt = PTTListener(on_toggle=self._bridge.ptt_toggled.emit)
        from pynput import keyboard
        self._other_hotkeys = keyboard.GlobalHotKeys({
            HOTKEY_TYPE: self._bridge.type_hotkey_fired.emit,
            HOTKEY_QUIT: self._bridge.quit_hotkey_fired.emit,
        })

        # Wiring
        self._bridge.cursor_moved.connect(self._voice.follow)
        self._bridge.ptt_toggled.connect(self._on_ptt_toggled)
        self._bridge.audio_level.connect(self._voice.set_level)
        self._bridge.recording_stopped.connect(self._on_recording_stopped)
        self._bridge.transcription_ready.connect(self._on_transcription)
        self._bridge.transcription_error.connect(self._on_transcription_error)
        self._bridge.type_hotkey_fired.connect(self._on_type_hotkey)
        self._bridge.quit_hotkey_fired.connect(self._quit)

    # ── Cursor follow ─────────────────────────────────────────────────────────

    def _on_cursor_move(self, x: int, y: int):
        # Called from the pynput listener thread — marshal via signal.
        self._cx, self._cy = x, y
        self._bridge.cursor_moved.emit(x, y)

    # ── Recording ──────────────────────────────────────────────────────────────

    def _start_recording(self, target: Task | None):
        with self._record_lock:
            if self._record_thread is not None and self._record_thread.is_alive():
                print("[ptt] already recording — ignoring new start")
                return False
            self._record_stop.clear()
            self._record_target = target

        self._voice.set_state("listening")
        self._voice.follow(self._cx, self._cy)

        def _run():
            from src.voice_io import record_until_stop
            try:
                text = record_until_stop(
                    self._record_stop,
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
            self._bridge.transcription_ready.emit(stripped, self._record_target)

        self._record_thread = threading.Thread(target=_run, daemon=True)
        self._record_thread.start()
        return True

    def _stop_recording(self):
        # User-initiated stop. The voice-state transition to "processing" is
        # also driven by the recording-stopped signal once the mic loop exits,
        # which covers the MAX_SECONDS path; setting it here as well is harmless.
        self._record_stop.set()
        self._voice.set_state("processing")

    def _on_recording_stopped(self):
        # Fired from the recording thread via the bridge whenever the mic loop
        # exits — covers the MAX_SECONDS timeout path that has no upstream stop.
        self._voice.set_state("processing")

    # ── Global PTT (toggle on Ctrl+Shift+Space) ───────────────────────────────

    def _on_ptt_toggled(self):
        recording = self._record_thread is not None and self._record_thread.is_alive()
        if recording:
            print("[ptt] toggle off — sending")
            # Only stop if WE started a global recording (target=None).
            if self._record_target is None:
                self._stop_recording()
        else:
            print("[ptt] toggle on — listening")
            self._start_recording(target=None)

    # ── Per-task amend ────────────────────────────────────────────────────────

    def _on_amend_start(self, task: Task):
        if self._record_thread is not None and self._record_thread.is_alive():
            print("[amend] already recording — ignoring")
            task.puck.set_amending(False)
            return
        if self._start_recording(target=task):
            task.puck.set_amending(True)

    def _on_amend_stop(self, task: Task):
        if self._record_target is task and self._record_thread is not None and self._record_thread.is_alive():
            self._stop_recording()

    # ── Transcription results ─────────────────────────────────────────────────

    def _on_transcription(self, text: str, target):
        self._voice.set_state("idle")
        print(f"[heard] {text!r}")
        if isinstance(target, Task):
            print(f"[amend] queueing on {target.prompt[:40]!r}")
            self._tasks.amend(target, text)
        else:
            try:
                t = self._tasks.spawn(text)
                print(f"[spawn] task in {t.runner.workdir}")
            except Exception as e:
                print(f"[spawn] failed: {e}")

    def _on_transcription_error(self, msg: str):
        target = self._record_target
        self._voice.set_state("idle")
        if isinstance(target, Task):
            target.puck.set_amending(False)
            target.puck.set_status(f"amend cancelled: {msg}")
        else:
            print(f"[ptt] {msg}")

    # ── Type-a-prompt fallback (Ctrl+.) ───────────────────────────────────────

    def _on_type_hotkey(self):
        scr = QApplication.primaryScreen()
        if scr is not None:
            geom = scr.availableGeometry()
            self._text_popup.show_at(geom.center().x(), geom.center().y())

    def _on_text_submitted(self, text: str):
        text = (text or "").strip()
        if not text:
            return
        try:
            self._tasks.spawn(text)
        except Exception as e:
            print(f"[spawn] failed: {e}")

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def _quit(self):
        print("closing curby…")
        self._stop_recording()
        self._tasks.shutdown()
        self._cursor.stop()
        self._qt.quit()

    def run(self):
        # Place the indicator at the current cursor before showing it.
        from PyQt6.QtGui import QCursor
        pos = QCursor.pos()
        self._cx, self._cy = pos.x(), pos.y()
        self._voice.set_state("idle")
        self._voice.follow(self._cx, self._cy)
        self._voice.show()
        self._voice.raise_()
        make_always_visible(self._voice)

        self._cursor.start()
        self._ptt.start()
        self._other_hotkeys.start()

        print("Curby ready.")
        print(f"  Tap Ctrl+Space         — start listening; tap again to send the task.")
        print(f"  {HOTKEY_TYPE}               — type a prompt instead of speaking.")
        print(f"  Hover a task puck      — pause / cancel / amend that task.")
        print(f"  {HOTKEY_QUIT}                  — quit curby.")
        rc = self._qt.exec()
        self._ptt.stop()
        self._other_hotkeys.stop()
        self._cursor.stop()
        return rc
