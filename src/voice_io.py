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
SILENCE_THRESHOLD = 500       # RMS below this = silence (used only for speech_start signal)
MAX_SECONDS = 30              # hard cap on a single push-to-talk recording

_tts_lock = threading.Lock()


def record_until_stop(stop_event: threading.Event,
                      on_speech_start: Callable[[], None] | None = None) -> str:
    """Record from mic until stop_event is set or MAX_SECONDS elapses, then transcribe.

    Push-to-talk: caller taps a hotkey to start (spawning a thread that calls this),
    taps again to set stop_event. Returns transcribed text. Raises RuntimeError on
    mic failure, empty capture, or transcription failure.
    """
    chunk = int(SAMPLE_RATE * 0.1)        # 100ms chunks
    frames: list[np.ndarray] = []
    spoken = False
    max_chunks = int(MAX_SECONDS / 0.1)

    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16") as stream:
            for _ in range(max_chunks):
                if stop_event.is_set():
                    break
                data, _ = stream.read(chunk)
                frames.append(data.copy())
                if not spoken:
                    rms = int(np.sqrt(np.mean(data.astype(np.float32) ** 2)))
                    if rms > SILENCE_THRESHOLD:
                        spoken = True
                        if on_speech_start:
                            try: on_speech_start()
                            except Exception: pass
    except Exception as e:
        raise RuntimeError(f"mic unavailable: {e}")

    if not frames:
        raise RuntimeError("no audio captured")

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
    """Speak text via the platform TTS (SAPI5 on Windows, NSSpeechSynthesizer on macOS).
    Non-blocking by default; block=True waits."""
    clean = _sanitize(text)
    def _run():
        with _tts_lock:
            try:
                engine = pyttsx3.init()
                engine.setProperty("rate", 165)
                engine.setProperty("volume", 0.9)
                engine.say(clean)
                engine.runAndWait()
                engine.stop()
            except Exception as e:
                print(f"[tts error] {e}")
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    if block:
        t.join()
