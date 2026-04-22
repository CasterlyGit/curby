"""Always-on voice listener.

Emits four signals the UI can hook into:
  waiting       — listener has opened the mic and is waiting for the user to speak
  speech_start  — RMS crossed the speaking threshold; the user is talking now
  utterance     — clean transcribed text after the user stops speaking
  listen_error  — capture or transcription failed; includes a short error message

Supports pause() / resume() so the app can silence the mic during TTS playback.
"""
import threading
import time

from PyQt6.QtCore import QThread, pyqtSignal


class ContinuousListener(QThread):
    waiting       = pyqtSignal()
    speech_start  = pyqtSignal()
    utterance     = pyqtSignal(str)
    listen_error  = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._stop    = threading.Event()
        self._paused  = threading.Event()
        self._resumed = threading.Event()
        self._resumed.set()

    def stop(self):
        self._stop.set()
        self._paused.clear()
        self._resumed.set()

    def pause(self):
        self._paused.set()
        self._resumed.clear()

    def resume(self):
        self._paused.clear()
        self._resumed.set()

    def is_paused(self) -> bool:
        return self._paused.is_set()

    def run(self):
        from src.voice_io import listen_once
        while not self._stop.is_set():
            if self._paused.is_set():
                self._resumed.wait(timeout=0.5)
                continue

            try:
                self.waiting.emit()
                text = listen_once(on_speech_start=self.speech_start.emit,
                                   max_wait_seconds=10.0)
            except RuntimeError as e:
                msg = str(e).lower()
                if msg == "silence":
                    # Normal — no one spoke in the 10s window; just loop
                    continue
                if "mic unavailable" in msg:
                    self.listen_error.emit(str(e))
                    # Mic is stuck — wait longer before retrying
                    time.sleep(1.5)
                    continue
                # "couldn't understand" / "speech service unreachable" — show it
                self.listen_error.emit(str(e))
                time.sleep(0.3)
                continue
            except Exception as e:
                self.listen_error.emit(f"listener: {e}")
                time.sleep(0.5)
                continue

            if self._stop.is_set():
                return
            if self._paused.is_set():
                continue
            if text and text.strip():
                self.utterance.emit(text.strip())
                # No auto-pause — listener stays open so the user can interrupt
                # during a guided animation or say advance phrases while curby
                # is waiting. Mic is only silenced during active TTS playback
                # (via the voice_io on_speak_start / _end callbacks).
