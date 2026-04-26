"""Toggle-style global hotkey: tap the chord once → on. Tap again → off.

Trigger is a set of pynput keys that must all be held simultaneously when
the chord fires. Each fresh activation of the chord (after every key has
been released at least once) emits exactly one toggle event.
"""
from collections.abc import Callable, Iterable

from pynput import keyboard


def _canon(key):
    """Collapse left/right modifier variants to a single canonical key."""
    if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
        return keyboard.Key.ctrl
    if key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
        return keyboard.Key.shift
    if key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r):
        return keyboard.Key.alt
    if key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r):
        return keyboard.Key.cmd
    return key


class PTTListener:
    def __init__(self,
                 on_toggle: Callable[[], None],
                 trigger: Iterable = (keyboard.Key.ctrl, keyboard.Key.space)):
        self._on_toggle = on_toggle
        self._trigger = set(_canon(k) for k in trigger)
        self._held: set = set()
        self._armed = True            # ready to fire next time the chord becomes active
        self._listener: keyboard.Listener | None = None

    def start(self):
        if self._listener is not None:
            return
        self._listener = keyboard.Listener(
            on_press=self._handle_press,
            on_release=self._handle_release,
        )
        self._listener.start()

    def stop(self):
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    # ── Internals ──────────────────────────────────────────────────────────────

    def _handle_press(self, key):
        self._held.add(_canon(key))
        # Fire once when the chord first becomes fully held; re-arm only
        # after the chord has been released.
        if self._armed and self._trigger.issubset(self._held):
            self._armed = False
            try: self._on_toggle()
            except Exception as e: print(f"[ptt] on_toggle failed: {e}")

    def _handle_release(self, key):
        self._held.discard(_canon(key))
        if not self._trigger.issubset(self._held):
            self._armed = True
