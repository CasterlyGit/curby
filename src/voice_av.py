"""In-process Apple TTS via AVSpeechSynthesizer.

Avoids the multi-second subprocess startup cost of `say` by keeping
the synthesizer alive in-process for curby's lifetime. The voice
engine stays loaded; first audio sample reaches the speaker in tens
of ms after `speak()` instead of the 1-2s gap a fresh `say` spawn
incurs.

Public surface mirrors the one we need at the call site:

    voice_av.available()            -> True iff AVFoundation imports
    voice_av.prewarm(voice_name)    -> non-blocking warmup; idempotent
    voice_av.speak(text, voice, rate_wpm, register_handle)
                                    -> blocks until utterance ends or
                                       voice_av.stop() is called
    voice_av.stop()                 -> cancel current speech immediately

`register_handle(handle_or_None)` lets the caller track the live
synthesizer so an external interrupt (mid-speech Ctrl+Space) can stop
it; the handle is the synth itself, so callers can also check
`hasattr(handle, "stopSpeakingAtBoundary_")` to distinguish it from
the subprocess fallback path.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

try:
    from AVFoundation import (
        AVSpeechSynthesizer,
        AVSpeechUtterance,
        AVSpeechSynthesisVoice,
        AVSpeechBoundaryImmediate,
    )
    from Foundation import NSObject
    import objc
    _AVAILABLE = True
    # AVSpeechSynthesisVoiceQuality enum (PyObjC doesn't always export it).
    _Q_DEFAULT = 1
    _Q_ENHANCED = 2
    _Q_PREMIUM = 3
except Exception:
    _AVAILABLE = False

# Volume cap on the utterance (0.0–1.0). Premium voices (Ava in particular)
# can clip the output at full volume on built-in laptop speakers — peg this
# below 1.0 to keep peaks under control.
_UTTERANCE_VOLUME = 0.75


_synth = None
_delegate = None
_lock = threading.Lock()


def available() -> bool:
    return _AVAILABLE


if _AVAILABLE:
    class _SpeechDelegate(NSObject):
        def init(self):
            self = objc.super(_SpeechDelegate, self).init()
            if self is not None:
                self._done_event = None
            return self

        def setDoneEvent_(self, ev):
            self._done_event = ev

        def speechSynthesizer_didFinishSpeechUtterance_(self, synth, utt):
            ev = self._done_event
            if ev is not None:
                ev.set()

        def speechSynthesizer_didCancelSpeechUtterance_(self, synth, utt):
            ev = self._done_event
            if ev is not None:
                ev.set()


def _ensure_synth():
    """Lazily create the singleton synth + delegate. Called under _lock."""
    global _synth, _delegate
    if _synth is None:
        _synth = AVSpeechSynthesizer.alloc().init()
        _delegate = _SpeechDelegate.alloc().init()
        _synth.setDelegate_(_delegate)
    return _synth, _delegate


def _find_voice(name: Optional[str]):
    """Match a voice by name (e.g. "Ava (Premium)"). Returns the
    AVSpeechSynthesisVoice instance, or None to use the system default.

    AVFoundation's `name()` is the bare voice name ("Ava") with quality
    exposed separately via `quality()`. If the config tag carries
    "(Premium)" or "(Enhanced)", we honor that quality — otherwise the
    default-quality Ava can win the match and the user's premium pick
    silently reverts across restarts."""
    if not name:
        return None
    voices = AVSpeechSynthesisVoice.speechVoices()
    raw = name.strip()
    lower = raw.lower()

    want_quality = None
    if "(premium)" in lower:
        want_quality = _Q_PREMIUM
    elif "(enhanced)" in lower:
        want_quality = _Q_ENHANCED

    # Strip the "(Premium)" / "(Enhanced)" tag so we match against the
    # bare AVFoundation name().
    bare = lower.split(" (", 1)[0].strip()

    def _quality(v) -> int:
        try:
            return int(v.quality())
        except Exception:
            return _Q_DEFAULT

    # 1. Exact bare-name match with matching quality (the strict win).
    if want_quality is not None:
        for v in voices:
            if str(v.name()).lower() == bare and _quality(v) == want_quality:
                return v

    # 2. Exact bare-name match, any quality (prefer highest available).
    name_matches = [v for v in voices if str(v.name()).lower() == bare]
    if name_matches:
        return max(name_matches, key=_quality)

    # 3. Original exact display-name match (for callers that pass weird tags).
    for v in voices:
        if str(v.name()).lower() == lower:
            return v

    # 4. Substring fallback on the bare name.
    for v in voices:
        if bare in str(v.name()).lower():
            return v
    return None


def prewarm(voice_name: Optional[str] = None) -> None:
    """Create the synth + resolve the voice + force the voices list to
    load. Does NOT speak. Safe to call from any thread; no-op if
    AVFoundation isn't available."""
    if not _AVAILABLE:
        return
    try:
        with _lock:
            _ensure_synth()
        # Touching speechVoices() materializes the voice catalog. Then
        # constructing one utterance forces the voice unit to attach to
        # the audio engine — that's the cold-load we want to pay now.
        _find_voice(voice_name)
        _ = AVSpeechUtterance.speechUtteranceWithString_(".")
    except Exception as e:
        print(f"[voice_av] prewarm non-fatal: {e}", flush=True)


def speak(
    text: str,
    *,
    voice_name: Optional[str] = None,
    rate_wpm: int = 220,
    register_handle: Optional[Callable] = None,
) -> bool:
    """Speak `text` via the in-process synthesizer. BLOCKS until the
    utterance finishes OR `stop()` is called externally.

    Returns True on success, False if AVFoundation isn't available or
    something went wrong (caller should fall back to `say`).
    """
    if not _AVAILABLE:
        return False
    try:
        with _lock:
            synth, delegate = _ensure_synth()
            utt = AVSpeechUtterance.speechUtteranceWithString_(text)
            voice = _find_voice(voice_name)
            if voice is not None:
                utt.setVoice_(voice)
            # AVSpeechUtterance.rate is on a 0..1 scale where the default
            # is roughly natural-speed for the chosen voice. Empirically
            # 0.5 maps to ~175 wpm; scale linearly and clamp.
            rate = max(0.0, min(1.0, 0.5 * (rate_wpm / 175.0)))
            utt.setRate_(rate)
            try:
                utt.setVolume_(_UTTERANCE_VOLUME)
            except Exception:
                pass

            done = threading.Event()
            delegate.setDoneEvent_(done)

            if register_handle is not None:
                try:
                    register_handle(synth)
                except Exception:
                    pass

            synth.speakUtterance_(utt)

        # Released the lock before waiting so concurrent stop() can proceed.
        finished = done.wait(timeout=120)

        if register_handle is not None:
            try:
                register_handle(None)
            except Exception:
                pass
        if not finished:
            # Belt-and-suspenders: hung past 2 min, force-stop.
            stop()
        return True
    except Exception as e:
        print(f"[voice_av] speak failed: {e}", flush=True)
        return False


def stop() -> None:
    """Cancel any in-progress utterance immediately."""
    if not _AVAILABLE or _synth is None:
        return
    try:
        _synth.stopSpeakingAtBoundary_(AVSpeechBoundaryImmediate)
    except Exception:
        pass
