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
from src.ghost_cursor import GhostCursor
from src.system_cursor import SystemCursorHider

HOTKEY_TYPE = "<ctrl>+."     # alternate input: type the prompt instead of speaking
HOTKEY_QUICK = "<ctrl>+<space>"      # quick-ask: voice in → short Claude answer → voice out (PRIMARY)
HOTKEY_SPAWN_TRIGGER = "ctrl+shift+space"  # agent-spawn moved here; consumed by PTTListener
HOTKEY_QUIT = "<esc>"        # hard stop

# Sentinel used as the recording "target" for a quick-ask. Anything not a Task
# and not None routes the transcribed text away from spawn/amend.
QUICK_ASK_TARGET = "__quick_ask__"


class _Bridge(QObject):
    """Marshal background-thread events onto the Qt main thread."""
    cursor_moved        = pyqtSignal(int, int)
    ptt_toggled         = pyqtSignal()
    audio_level         = pyqtSignal(float)
    recording_stopped   = pyqtSignal()              # mic loop exited (any cause)
    transcription_ready = pyqtSignal(str, object)   # text, target_task (None = new task)
    transcription_error = pyqtSignal(str)
    type_hotkey_fired   = pyqtSignal()
    quick_hotkey_fired  = pyqtSignal()
    quit_hotkey_fired   = pyqtSignal()
    voice_state_change  = pyqtSignal(str)  # marshaled from worker threads to flip the indicator
    answer_ready        = pyqtSignal(str, int)   # reply text, latency_ms — drives the floating note


class CurbyApp:
    def __init__(self):
        self._qt = QApplication.instance() or QApplication(sys.argv)
        self._bridge = _Bridge()

        self._voice = GhostCursor()
        self._tasks = TaskManager()
        self._tasks.task_amend_start.connect(self._on_amend_start)
        self._tasks.task_amend_stop.connect(self._on_amend_stop)

        self._text_popup = TextInputPopup()
        self._text_popup.submitted.connect(self._on_text_submitted)

        # Persistent claude worker is currently disabled — see #20. It made
        # round-trips SLOWER (12-24s vs 7s) because each turn re-processed
        # an ever-growing in-session context, and its stop() can deadlock
        # the quit path when a turn is in flight. Code stays in tree;
        # re-enable when #20 is properly fixed.
        self._claude_worker = None

        # Floating answer note (top-right, draggable, click-to-collapse).
        from src.answer_note import AnswerNote
        self._answer_note = AnswerNote()

        # System cursor stays visible — the feather is a companion next to
        # it, not a replacement. (Tried single-cursor mode but the feather's
        # bobbing motion was unusable for actual pointing.)
        self._cursor_hider = SystemCursorHider()  # kept for future use; not started

        self._cx = 0
        self._cy = 0
        self._cursor = CursorTracker(on_move=self._on_cursor_move)

        # Recording state. Only one recording at a time; the target tells us
        # where the transcribed text goes (None = spawn a new task).
        self._record_lock = threading.Lock()
        self._record_stop = threading.Event()
        self._record_thread: threading.Thread | None = None
        # None = spawn a new agent task; Task instance = amend that task;
        # QUICK_ASK_TARGET sentinel = route to quick-ask flow.
        self._record_target: Task | str | None = None

        # Hotkeys — toggle: tap chord to start, tap again to send.
        # Agent-spawn moved to Ctrl+Shift+Space; Ctrl+Space is now quick-ask (primary).
        from pynput import keyboard
        self._ptt = PTTListener(
            on_toggle=self._bridge.ptt_toggled.emit,
            trigger=(keyboard.Key.ctrl, keyboard.Key.shift, keyboard.Key.space),
        )
        self._other_hotkeys = keyboard.GlobalHotKeys({
            HOTKEY_TYPE: self._bridge.type_hotkey_fired.emit,
            HOTKEY_QUICK: self._bridge.quick_hotkey_fired.emit,
            HOTKEY_QUIT: self._bridge.quit_hotkey_fired.emit,
        })

        # Wiring
        # NOTE: the feather is DECOUPLED from the system cursor — it lives at
        # a fixed position next to the answer note. Per-frame move() calls
        # following the cursor caused real input lag on macOS.
        # AnswerNote uses cursor position to flip click-through on/off
        # (interactive only while hovered, click-through everywhere else).
        self._bridge.cursor_moved.connect(self._tasks.check_hover)
        self._bridge.cursor_moved.connect(self._answer_note.check_hover)
        self._bridge.ptt_toggled.connect(self._on_ptt_toggled)
        self._bridge.audio_level.connect(self._voice.set_level)
        self._bridge.recording_stopped.connect(self._on_recording_stopped)
        self._bridge.transcription_ready.connect(self._on_transcription)
        self._bridge.transcription_error.connect(self._on_transcription_error)
        self._bridge.type_hotkey_fired.connect(self._on_type_hotkey)
        self._bridge.quick_hotkey_fired.connect(self._on_quick_hotkey)
        self._bridge.quit_hotkey_fired.connect(self._quit)
        self._bridge.voice_state_change.connect(self._voice.set_state)
        self._bridge.answer_ready.connect(self._answer_note.set_reply)
        # Feather visibility tracks the answer-note's collapse state — the
        # two read as one paired cluster.
        self._answer_note.collapse_changed.connect(self._on_note_collapse_changed)

    # ── Collapse coupling ─────────────────────────────────────────────────────

    def _on_note_collapse_changed(self, collapsed: bool):
        """When the answer note collapses to a dot, hide the feather too,
        so the whole curby cluster reads as one collapsed unit. Expanding
        the note brings the feather back."""
        if collapsed:
            self._voice.hide()
        else:
            self._voice.show()
            self._voice.raise_()

    # ── Cursor follow ─────────────────────────────────────────────────────────

    def _on_cursor_move(self, x: int, y: int):
        # Called from the pynput listener thread — marshal via signal.
        self._cx, self._cy = x, y
        self._bridge.cursor_moved.emit(x, y)

    # ── Recording ──────────────────────────────────────────────────────────────

    def _start_recording(self, target: Task | str | None):
        with self._record_lock:
            if self._record_thread is not None and self._record_thread.is_alive():
                print("[ptt] already recording — ignoring new start")
                return False
            self._record_stop.clear()
            self._record_target = target

        self._voice.set_state("listening")

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

    # ── Quick-ask (Ctrl+/) ────────────────────────────────────────────────────

    def _on_quick_hotkey(self):
        recording = self._record_thread is not None and self._record_thread.is_alive()
        if recording:
            # Toggle off only if THIS is the quick-ask recording we own.
            if self._record_target == QUICK_ASK_TARGET:
                print("[quick-ask] toggle off — sending", flush=True)
                self._stop_recording()
            else:
                print("[quick-ask] another recording in progress — ignoring")
        else:
            print("[quick-ask] toggle on — listening", flush=True)
            self._start_recording(target=QUICK_ASK_TARGET)

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
        print(f"[heard] {text!r}")
        if isinstance(target, Task):
            self._voice.set_state("idle")
            print(f"[amend] queueing on {target.prompt[:40]!r}")
            self._tasks.amend(target, text)
        elif target == QUICK_ASK_TARGET:
            # Keep the indicator alive in a "thinking" pulse until the reply
            # lands — the worker thread flips it through speaking → idle.
            self._voice.set_state("thinking")
            self._run_quick_ask(text)
        else:
            self._voice.set_state("idle")
            try:
                t = self._tasks.spawn(text)
                print(f"[spawn] task in {t.runner.workdir}")
            except Exception as e:
                print(f"[spawn] failed: {e}")

    def _run_quick_ask(self, prompt: str):
        """Run the quick-ask in a background thread so the Qt loop stays responsive.

        The indicator state is driven via bridge signals (Qt-thread-safe):
        thinking (already set by caller) → speaking (just before TTS) → idle.

        If the model returns a PREFERENCE_UPDATE: directive (style instruction
        the user said via voice — see src/preferences.py), we capture it and
        speak a short ack instead of speaking the directive itself.
        """
        worker = self._claude_worker
        bridge = self._bridge
        def _work():
            from src.quick_ask import run_quick_ask, log_quick_ask, speak_reply
            from src import preferences
            addendum = preferences.as_system_addendum()
            try:
                reply, latency_ms, was_followup = run_quick_ask(
                    prompt, worker=worker, system_addendum=addendum,
                )
            except Exception as e:
                msg = f"quick-ask failed: {e}"
                print(f"[quick-ask] {msg}", flush=True)
                bridge.voice_state_change.emit("error")
                try: speak_reply("sorry, something went wrong.")
                except Exception: pass
                bridge.voice_state_change.emit("idle")
                return

            is_pref, payload = preferences.parse_reply(reply)
            if is_pref:
                if payload.strip().upper() == "RESET":
                    preferences.clear()
                    ack = "okay, back to normal."
                    print(f"[prefs] reset", flush=True)
                else:
                    preferences.append(payload)
                    ack = "got it."
                    print(f"[prefs] added: {payload!r}", flush=True)
                log_quick_ask(prompt, f"[PREF] {payload}", latency_ms, was_followup=was_followup)
                bridge.answer_ready.emit(f"⚙ preference: {payload}", latency_ms)
                bridge.voice_state_change.emit("speaking")
                speak_reply(ack)
                bridge.voice_state_change.emit("idle")
                return

            tag = "follow-up" if was_followup else "new"
            print(f"[quick-ask] {tag} reply ({latency_ms} ms): {reply!r}", flush=True)
            log_quick_ask(prompt, reply, latency_ms, was_followup=was_followup)
            bridge.answer_ready.emit(reply, latency_ms)
            bridge.voice_state_change.emit("speaking")
            speak_reply(reply)  # blocks until TTS completes (subprocess wait)
            bridge.voice_state_change.emit("idle")
        threading.Thread(target=_work, daemon=True).start()

    def _on_transcription_error(self, msg: str):
        target = self._record_target
        self._voice.set_state("idle")
        if isinstance(target, Task):
            target.puck.set_amending(False)
            target.puck.set_status(f"amend cancelled: {msg}")
        elif target == QUICK_ASK_TARGET:
            print(f"[quick-ask] {msg}")
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
        try: self._cursor_hider.restore()
        except Exception: pass
        self._stop_recording()
        if self._claude_worker is not None:
            try: self._claude_worker.stop()
            except Exception: pass
        # Explicitly close all our overlay widgets so nothing lingers if
        # the Qt event loop is slow to tear down.
        for w in (getattr(self, "_voice", None),
                  getattr(self, "_answer_note", None),
                  getattr(self, "_text_popup", None)):
            try:
                if w is not None:
                    w.hide()
                    w.close()
            except Exception: pass
        self._tasks.shutdown()
        self._cursor.stop()
        try:
            from src import pidfile
            pidfile.clear()
        except Exception: pass
        self._qt.quit()

    def run(self):
        from PyQt6.QtGui import QCursor
        from PyQt6.QtWidgets import QApplication
        from src import pidfile

        # Kill any leftover curby from a previous run (e.g. force-killed,
        # so its overlays never cleaned up). Then claim the pidfile.
        killed = pidfile.kill_previous()
        if killed:
            print(f"[pidfile] killed stale curby pid {killed}", flush=True)
        pidfile.write_self()

        pos = QCursor.pos()
        self._cx, self._cy = pos.x(), pos.y()

        # Show the answer note top-right.
        self._answer_note.show_initial()
        make_always_visible(self._answer_note)

        # Pin the feather to a FIXED position next to the answer note.
        # Decoupled from the cursor entirely — see #29. The feather is a
        # state indicator paired with the answer note, not a cursor companion.
        self._voice.set_state("idle")
        screen = QApplication.primaryScreen()
        if screen is not None:
            geom = screen.availableGeometry()
            # Just below the answer note's top-right anchor: 18px from the
            # right edge, and beneath the note's visible footprint so the
            # two read as a paired widget cluster.
            note_h = self._answer_note.height()
            x = geom.right() - 18 - 120          # GhostCursor SIZE = 120
            y = geom.top() + 18 + note_h + 8
            self._voice.pin_at(x, y)
        self._voice.show()
        self._voice.raise_()
        make_always_visible(self._voice)

        self._cursor.start()
        self._ptt.start()
        self._other_hotkeys.start()

        if self._claude_worker is not None:
            threading.Thread(target=self._claude_worker.start, daemon=True).start()

        # One-time tip if we don't have a Premium voice installed.
        try:
            from src.voice_config import resolve_voice, install_hint
            voice, _, is_premium = resolve_voice()
            if not is_premium:
                picked = voice or "(system default)"
                print(f"[voice] using {picked}")
                print(install_hint())
            else:
                print(f"[voice] using {voice}")
        except Exception as e:
            print(f"[voice] config check failed: {e}")

        print("Curby ready.")
        print(f"  Tap Ctrl+Space         — quick-ask: voice question → spoken Claude answer.")
        print(f"  Tap Ctrl+Shift+Space   — spawn an agent task (the old Ctrl+Space).")
        print(f"  {HOTKEY_TYPE}               — type a prompt to spawn an agent task instead of speaking.")
        print(f"  Hover a task puck      — pause / cancel / amend that task.")
        print(f"  {HOTKEY_QUIT}                  — quit curby.")
        rc = self._qt.exec()
        self._ptt.stop()
        self._other_hotkeys.stop()
        self._cursor.stop()
        return rc
