"""Speaker + SpeechHandle protocols — uniform TTS abstraction.

Eliminates the ``hasattr(handle, "stopSpeakingAtBoundary_")`` duck-type
that was scattered across app.py.  Callers work against a single
``SpeechHandle.stop()`` surface regardless of whether the live impl is
AVSpeechSynthesizer, a ``say`` subprocess, or pyttsx3.
"""
from __future__ import annotations

import subprocess
from typing import Protocol, runtime_checkable


@runtime_checkable
class SpeechHandle(Protocol):
    """Returned by Speaker.speak(); lets the caller interrupt the utterance."""

    def stop(self) -> None:
        """Cancel the current utterance immediately."""
        ...


class AVSpeechHandle:
    """SpeechHandle backed by an AVSpeechSynthesizer in-process synth."""

    def __init__(self, synth) -> None:
        # synth is an AVSpeechSynthesizer ObjC object; we keep a reference
        # so it isn't GC'd while we might want to stop it.
        self._synth = synth

    def stop(self) -> None:
        try:
            from src import voice_av
            voice_av.stop()
        except Exception:
            pass


class SubprocessSpeechHandle:
    """SpeechHandle backed by a ``say`` (or similar) subprocess.Popen."""

    def __init__(self, proc: subprocess.Popen) -> None:
        self._proc = proc

    def stop(self) -> None:
        try:
            self._proc.kill()
        except Exception:
            pass


class NullSpeechHandle:
    """No-op handle returned when no TTS backend is active."""

    def stop(self) -> None:
        pass
