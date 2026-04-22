import threading
import tempfile
import os
from collections.abc import Callable
import numpy as np
import sounddevice as sd
import scipy.io.wavfile as wav
import speech_recognition as sr
import pyttsx3

SAMPLE_RATE = 16000
SILENCE_THRESHOLD = 500       # RMS below this = silence
SILENCE_SECONDS = 1.0         # stop after this much silence
MAX_SECONDS = 15              # hard cap

_tts_lock = threading.Lock()

# Hooks so the continuous listener can pause/resume the mic during TTS playback
# (otherwise the listener hears curby's own voice and feedback-loops).
_on_speak_start: Callable[[], None] | None = None
_on_speak_end: Callable[[], None] | None = None


def set_speak_callbacks(on_start: Callable[[], None] | None = None,
                        on_end:   Callable[[], None] | None = None) -> None:
    global _on_speak_start, _on_speak_end
    _on_speak_start = on_start
    _on_speak_end = on_end


def listen_once(on_speech_start: Callable[[], None] | None = None,
                max_wait_seconds: float = 10.0) -> str:
    """Record from mic until the user stops talking. Returns transcribed text.

    - Calls on_speech_start the first time RMS crosses the speaking threshold.
    - Raises RuntimeError if no speech captured within max_wait_seconds, or if
      transcription fails. Caller loops on this.
    """
    chunk = int(SAMPLE_RATE * 0.1)    # 100ms chunks
    frames = []
    silent_chunks = 0
    required_silent = int(SILENCE_SECONDS / 0.1)
    max_chunks = int(max_wait_seconds / 0.1)
    spoken = False

    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16") as stream:
            for _ in range(max_chunks):
                data, _ = stream.read(chunk)
                frames.append(data.copy())
                rms = int(np.sqrt(np.mean(data.astype(np.float32) ** 2)))
                if rms > SILENCE_THRESHOLD:
                    if not spoken:
                        spoken = True
                        if on_speech_start:
                            try: on_speech_start()
                            except Exception: pass
                    silent_chunks = 0
                elif spoken:
                    silent_chunks += 1
                    if silent_chunks >= required_silent:
                        break
    except Exception as e:
        raise RuntimeError(f"mic unavailable: {e}")

    if not spoken:
        raise RuntimeError("silence")

    audio_data = np.concatenate(frames, axis=0)
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    wav.write(tmp.name, SAMPLE_RATE, audio_data)
    tmp.close()

    try:
        recognizer = sr.Recognizer()
        with sr.AudioFile(tmp.name) as source:
            audio = recognizer.record(source)
        try:
            return recognizer.recognize_google(audio)
        except sr.UnknownValueError:
            raise RuntimeError("couldn't understand that — say it again?")
        except sr.RequestError as e:
            raise RuntimeError(f"speech service unreachable: {e}")
    finally:
        try: os.unlink(tmp.name)
        except Exception: pass


def _sanitize(text: str) -> str:
    return text.encode("ascii", errors="ignore").decode("ascii")


def speak(text: str, block: bool = False) -> None:
    """Speak text via Windows SAPI5 TTS. Non-blocking by default; block=True waits.

    Pauses any registered continuous listener while speaking so the mic doesn't
    pick up curby's own voice.
    """
    clean = _sanitize(text)
    def _run():
        with _tts_lock:
            try:
                if _on_speak_start:
                    try: _on_speak_start()
                    except Exception: pass
                engine = pyttsx3.init()
                engine.setProperty("rate", 165)
                engine.setProperty("volume", 0.9)
                engine.say(clean)
                engine.runAndWait()
                engine.stop()
            finally:
                if _on_speak_end:
                    try: _on_speak_end()
                    except Exception: pass
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    if block:
        t.join()
