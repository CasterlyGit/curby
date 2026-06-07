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

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from src.cursor_tracker import CursorTracker
from src.mac_window import make_always_visible
from src.ptt_listener import PTTListener
from src.task_manager import TaskManager, Task
from src.text_input_popup import TextInputPopup
from src.ghost_cursor import GhostCursor
from src.recording_controller import RecordingController, RecordingRequest, RecordingTarget
from src.quick_ask_session import QuickAskSession

HOTKEY_TYPE = "<ctrl>+."     # alternate input: type the prompt instead of speaking
HOTKEY_QUICK = "<ctrl>+<space>"      # quick-ask: voice in → short Claude answer → voice out (PRIMARY)
HOTKEY_SPAWN_TRIGGER = "ctrl+shift+space"  # agent-spawn moved here; consumed by PTTListener
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

        # Floating answer note (top-right, draggable, click-to-collapse).
        from src.answer_note import AnswerNote
        self._answer_note = AnswerNote()

        # Feather IS the cursor — OS cursor is hidden so only the feather
        # shows. The bobbing that made the prior single-cursor attempt
        # unusable is now disabled in GhostCursor (offset/bob → 0), so the
        # feather tracks 1:1 and works as a real pointer replacement.

        self._cx = 0
        self._cy = 0
        self._cursor = CursorTracker(on_move=self._on_cursor_move)

        # Recording state delegated to RecordingController.
        self._recorder = RecordingController(self._bridge)

        # Conversation state for quick-ask follow-ups delegated to
        # QuickAskSession (no Qt, pure data, testable). Cleared on preference
        # RESET or automatically when the follow-up window expires.
        self._conv_session = QuickAskSession()

        # Active TTS handle. Tracked so Ctrl+Space mid-speech can stop it and
        # immediately listen for the next question. The SpeechHandle protocol
        # provides a uniform .stop() regardless of the underlying backend.
        self._active_tts_handle = None  # SpeechHandle | None

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
        # The feather follows the system cursor 1:1. Per-frame move() previously
        # caused noticeable input lag on macOS; the SPRING=1.0 path is now a
        # direct assignment with no easing math, which keeps it snappy.
        # AnswerNote is always-interactive (claude-meter pattern) and doesn't
        # need cursor-position wiring.
        self._bridge.cursor_moved.connect(self._tasks.check_hover)
        self._bridge.cursor_moved.connect(self._voice.follow)
        self._bridge.ptt_toggled.connect(self._on_ptt_toggled)
        self._bridge.audio_level.connect(self._voice.set_level)
        self._bridge.recording_stopped.connect(self._on_recording_stopped)
        self._bridge.transcription_ready.connect(self._on_transcription)
        self._bridge.transcription_error.connect(self._on_transcription_error)
        self._bridge.type_hotkey_fired.connect(self._on_type_hotkey)
        self._bridge.quick_hotkey_fired.connect(self._on_quick_hotkey)
        self._bridge.quit_hotkey_fired.connect(self._quit)
        self._bridge.voice_state_change.connect(self._voice.set_state)
        self._bridge.voice_state_change.connect(self._answer_note.set_voice_state)
        self._bridge.answer_ready.connect(self._answer_note.set_reply)
        # Feather visibility tracks the answer-note's collapse state — the
        # two read as one paired cluster.
        self._answer_note.collapse_changed.connect(self._on_note_collapse_changed)

    # ── Pre-warm ──────────────────────────────────────────────────────────────

    def _prewarm_backend(self):
        """Fire a tiny no-op request through the configured backend so the
        first user Ctrl+Space skips cold-path costs. Logs success/failure
        for debugging but never raises."""
        import time as _t
        try:
            from src.quick_ask import _resolve_backend_name
            from src.quick_ask_backends import load_backend
            name = _resolve_backend_name()
            backend = load_backend(name)
            # Prefer the backend's own prewarm() if it has one (e.g. OAuth
            # opens its keep-alive connection without spending a real turn).
            if hasattr(backend, "__module__"):
                import sys
                mod = sys.modules.get(backend.__module__)
                if mod is not None and hasattr(mod, "prewarm"):
                    t0 = _t.monotonic()
                    mod.prewarm()
                    print(f"[prewarm] {name} ready in {int((_t.monotonic()-t0)*1000)} ms", flush=True)
                    return
            # No native prewarm — just import has already happened via load_backend.
            print(f"[prewarm] {name} module loaded (no native prewarm)", flush=True)
        except Exception as e:
            print(f"[prewarm] non-fatal: {e}", flush=True)

    def _prewarm_tts(self):
        """Preload the TTS voice engine so the first real reply doesn't
        pay the cold-load before producing audio.

        Prefers the in-process AVSpeechSynthesizer (since that's also our
        primary speech path now). Silent — no audible audio is produced.
        Failures swallowed; the real speak_reply has its own fallback.
        """
        import time as _t
        try:
            from src.voice_config import resolve_voice
            voice, _rate, _ = resolve_voice()
        except Exception:
            voice = None
        try:
            from src import voice_av
            if voice_av.available():
                t0 = _t.monotonic()
                voice_av.prewarm(voice)
                print(f"[prewarm] av synth voice catalog warm in {int((_t.monotonic()-t0)*1000)} ms", flush=True)
                return
        except Exception as e:
            print(f"[prewarm] av synth non-fatal: {e}", flush=True)

    # ── Collapse coupling ─────────────────────────────────────────────────────

    def _on_note_collapse_changed(self, collapsed: bool):
        """Answer note collapse no longer touches the feather — the feather
        IS the cursor now, so hiding it would leave the user with nothing to
        point with. The minimized cloud puff carries the alive-state pulse
        on its own."""
        return

    # ── Cursor follow ─────────────────────────────────────────────────────────

    def _on_cursor_move(self, x: int, y: int):
        # Called from the pynput listener thread — marshal via signal.
        self._cx, self._cy = x, y
        self._bridge.cursor_moved.emit(x, y)

    # ── Recording ──────────────────────────────────────────────────────────────

    def _start_recording(self, request: RecordingRequest) -> bool:
        started = self._recorder.start(request)
        if started:
            self._voice.set_state("listening")
        return started

    def _stop_recording(self):
        # User-initiated stop. The voice-state transition to "processing" is
        # also driven by the recording-stopped signal once the mic loop exits,
        # which covers the MAX_SECONDS path; setting it here as well is harmless.
        self._recorder.stop()
        self._voice.set_state("processing")

    def _on_recording_stopped(self):
        # Fired from the recording thread via the bridge whenever the mic loop
        # exits — covers the MAX_SECONDS timeout path that has no upstream stop.
        self._voice.set_state("processing")

    # ── Global PTT (toggle on Ctrl+Shift+Space) ───────────────────────────────

    def _on_ptt_toggled(self):
        if self._recorder.is_recording():
            print("[ptt] toggle off — sending")
            # Only stop if WE started a global agent recording (no specific task).
            req = self._recorder.current_request
            if req is not None and req.target == RecordingTarget.AGENT and req.task is None:
                self._stop_recording()
        else:
            print("[ptt] toggle on — listening")
            self._start_recording(RecordingRequest(RecordingTarget.AGENT))

    # ── Quick-ask (Ctrl+/) ────────────────────────────────────────────────────

    def _on_quick_hotkey(self):
        if self._recorder.is_recording():
            # Toggle off only if THIS is the quick-ask recording we own.
            req = self._recorder.current_request
            if req is not None and req.target == RecordingTarget.QUICK_ASK:
                print("[quick-ask] toggle off — sending", flush=True)
                self._stop_recording()
            else:
                print("[quick-ask] another recording in progress — ignoring")
            return
        # Not currently recording. If curby is mid-speech (TTS playing), the
        # user wants to interrupt — stop the speech and start listening.
        # SpeechHandle.stop() abstracts over AV synth vs. subprocess; no
        # backend-specific duck-typing needed here.
        if self._active_tts_handle is not None:
            print("[quick-ask] interrupting speech — listening", flush=True)
            handle = self._active_tts_handle
            self._active_tts_handle = None
            try:
                handle.stop()
            except Exception: pass
        print("[quick-ask] toggle on — listening", flush=True)
        self._start_recording(RecordingRequest(RecordingTarget.QUICK_ASK))

    # ── Per-task amend ────────────────────────────────────────────────────────

    def _on_amend_start(self, task: Task):
        if self._recorder.is_recording():
            print("[amend] already recording — ignoring")
            task.puck.set_amending(False)
            return
        if self._start_recording(RecordingRequest(RecordingTarget.AGENT, task=task)):
            task.puck.set_amending(True)

    def _on_amend_stop(self, task: Task):
        req = self._recorder.current_request
        if (req is not None and req.task is task and self._recorder.is_recording()):
            self._stop_recording()

    # ── Transcription results ─────────────────────────────────────────────────

    def _on_transcription(self, text: str, request):
        print(f"[heard] {text!r}")
        if not isinstance(request, RecordingRequest):
            # Defensive: shouldn't happen, but don't crash the UI thread.
            print(f"[transcription] unexpected request type {type(request)!r}")
            self._voice.set_state("idle")
            return
        if request.target == RecordingTarget.AGENT and request.task is not None:
            self._voice.set_state("idle")
            print(f"[amend] queueing on {request.task.prompt[:40]!r}")
            self._tasks.amend(request.task, text)
        elif request.target == RecordingTarget.QUICK_ASK:
            # Keep the indicator alive in a "thinking" pulse until the reply
            # lands — the worker thread flips it through speaking → idle.
            self._voice.set_state("thinking")
            self._run_quick_ask(text)
        else:
            # AGENT target with task=None → spawn a new agent task.
            self._voice.set_state("idle")
            try:
                t = self._tasks.spawn(text)
                print(f"[spawn] task in {t.runner.workdir}")
            except Exception as e:
                print(f"[spawn] failed: {e}")

    def _run_quick_ask(self, prompt: str):
        """Run the quick-ask in a background thread so the Qt loop stays responsive.

        Maintains conversation history in self._conv_history so multi-turn
        questions ("but what about X?") work correctly — the model sees
        prior turns. History is cleared if more than FOLLOWUP_WINDOW seconds
        have passed since the last turn (per quick_ask.FOLLOWUP_WINDOW_SECONDS).

        Tracks the active TTS subprocess so Ctrl+Space mid-speech can kill
        it for instant interrupt.
        """
        bridge = self._bridge
        history = self._conv_session.take_snapshot()

        def _register_tts(handle):
            self._active_tts_handle = handle

        def _work():
            from src.quick_ask import run_quick_ask, log_quick_ask, speak_reply
            from src import preferences
            addendum = preferences.as_system_addendum()
            try:
                reply, latency_ms, was_followup = run_quick_ask(
                    prompt, system_addendum=addendum,
                    history=history,
                )
            except Exception as e:
                msg = f"quick-ask failed: {e}"
                print(f"[quick-ask] {msg}", flush=True)
                bridge.voice_state_change.emit("error")
                try: speak_reply("sorry, something went wrong.", register_handle=_register_tts)
                except Exception: pass
                bridge.voice_state_change.emit("idle")
                return

            is_pref, payload = preferences.parse_reply(reply)
            if is_pref:
                if payload.strip().upper() == "RESET":
                    preferences.clear()
                    # Also reset conversation history — "back to normal" should
                    # be a full reset, not just style.
                    self._conv_session.clear()
                    ack = "okay, back to normal."
                    print("[prefs] reset", flush=True)
                else:
                    preferences.append(payload)
                    ack = "got it."
                    print(f"[prefs] added: {payload!r}", flush=True)
                log_quick_ask(prompt, f"[PREF] {payload}", latency_ms, was_followup=was_followup)
                bridge.answer_ready.emit(f"⚙ preference: {payload}", latency_ms)
                bridge.voice_state_change.emit("speaking")
                speak_reply(ack, register_handle=_register_tts)
                bridge.voice_state_change.emit("idle")
                return

            tag = "follow-up" if was_followup else "new"
            print(f"[quick-ask] {tag} reply ({latency_ms} ms): {reply!r}", flush=True)
            log_quick_ask(prompt, reply, latency_ms, was_followup=was_followup)
            # Record this turn into conversation history so future "but what
            # about X" questions see the prior context.
            self._conv_session.record_turn(prompt, reply)
            bridge.answer_ready.emit(reply, latency_ms)
            bridge.voice_state_change.emit("speaking")
            speak_reply(reply, register_handle=_register_tts)
            bridge.voice_state_change.emit("idle")
        threading.Thread(target=_work, daemon=True).start()

    def _on_transcription_error(self, msg: str):
        request = self._recorder.current_request
        self._voice.set_state("idle")
        if request is not None and request.target == RecordingTarget.AGENT and request.task is not None:
            request.task.puck.set_amending(False)
            request.task.puck.set_status(f"amend cancelled: {msg}")
        elif request is not None and request.target == RecordingTarget.QUICK_ASK:
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
        self._stop_recording()
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
        from src import pidfile

        # Kill any leftover curby from a previous run (e.g. force-killed,
        # so its overlays never cleaned up). Then claim the pidfile.
        killed = pidfile.kill_previous()
        if killed:
            print(f"[pidfile] killed stale curby pid {killed}", flush=True)
        pidfile.write_self()

        # Reap orphan agent process groups from the previous boot. Agents are
        # spawned with start_new_session=True so they survive a curby SIGKILL;
        # the pgid sidecar records them on spawn and clears on clean exit.
        try:
            from src.agent_pgids import reap_previous
            reaped = reap_previous()
            if reaped:
                print(f"[agent-pgids] reaped {len(reaped)} orphan agent(s): {', '.join(reaped)}", flush=True)
        except Exception as e:
            print(f"[agent-pgids] reap non-fatal: {e}", flush=True)

        pos = QCursor.pos()
        self._cx, self._cy = pos.x(), pos.y()

        # Show the answer note top-right.
        self._answer_note.show_initial()
        make_always_visible(self._answer_note)

        # Feather rides the cursor — seed at the current mouse position so it
        # appears in the right place before the first move event fires.
        # click_through=True is CRITICAL: the feather sits at the cursor, so
        # without NSPanel-level click pass-through every click on the screen
        # would be eaten by the feather window.
        self._voice.set_state("idle")
        self._voice.follow(self._cx, self._cy)
        self._voice.show()
        self._voice.raise_()
        make_always_visible(self._voice, click_through=True)

        self._cursor.start()
        self._ptt.start()
        self._other_hotkeys.start()

        # Pre-warm the quick-ask backend AND the TTS voice engine in the
        # background so the first Ctrl+Space doesn't pay cold-path costs
        # (keychain read, TCP+TLS handshake, voice-engine load). Both fail
        # safely; the real first call retries on its own.
        threading.Thread(target=self._prewarm_backend, daemon=True).start()
        threading.Thread(target=self._prewarm_tts, daemon=True).start()

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
        print("  Tap Ctrl+Space         — quick-ask: voice question → spoken Claude answer.")
        print("  Tap Ctrl+Shift+Space   — spawn an agent task (the old Ctrl+Space).")
        print(f"  {HOTKEY_TYPE}               — type a prompt to spawn an agent task instead of speaking.")
        print("  Hover a task puck      — pause / cancel / amend that task.")
        print(f"  {HOTKEY_QUIT}                  — quit curby.")
        rc = self._qt.exec()
        self._ptt.stop()
        self._other_hotkeys.stop()
        self._cursor.stop()
        return rc
