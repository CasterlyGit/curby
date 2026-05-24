import math
import time

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QTimer, QPointF
from PyQt6.QtGui import QPainter, QColor, QRadialGradient

# ── Vista / Curby palette ────────────────────────────────────────────────────
# Cohesive with ghost_cursor + speech_bubble
VIOLET       = QColor(167, 139, 250)   # #A78BFA
BLUE         = QColor( 96, 165, 250)   # #60A5FA
VIOLET_LIGHT = QColor(196, 181, 253)   # #C4B5FD
PINK_HOT     = QColor(236,  72, 153)   # #EC4899 (listening — warm rose)
MINT         = QColor( 52, 211, 153)   # #34D399 (speaking)
RED          = QColor(248, 113, 113)   # #F87171 (error)
STEEL        = QColor( 71,  85, 105)   # #475569 (idle)

STATE_ACCENT = {
    "idle":      STEEL,
    "listening": PINK_HOT,
    "thinking":  VIOLET,
    "speaking":  MINT,
    "error":     RED,
}

SIZE        = 28          # core orb diameter
HALO        = 22          # halo extra radius beyond orb
WIDGET_SIZE = SIZE + HALO * 2
OFFSET_X    = 22
OFFSET_Y    = 22


class BuddyIcon(QWidget):
    def __init__(self):
        super().__init__()
        self._state = "idle"
        self._level = 0.0           # latest mic input level (0..1), used in listening state
        self._smoothed_level = 0.0
        self._t0 = time.time()
        self._setup()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(16)

    def _setup(self):
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(WIDGET_SIZE, WIDGET_SIZE)

    def set_state(self, state: str):
        if state != self._state:
            self._state = state
            if state != "listening":
                self._level = 0.0
            self.update()

    def set_level(self, level_0_to_1: float):
        """Latest mic input level, normalized to 0..1. Drives orb-scale pulse
        while in the listening state."""
        self._level = max(0.0, min(1.0, level_0_to_1))

    def _on_tick(self):
        # Exponential smoothing of the mic level so the pulse feels organic.
        self._smoothed_level = 0.78 * self._smoothed_level + 0.22 * self._level
        self.update()

    # Alias for the existing CurbyApp signal name.
    def follow(self, cursor_x: int, cursor_y: int):
        self.move_near_cursor(cursor_x, cursor_y)
        if not self.isVisible():
            self.show()
            self.raise_()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = cy = WIDGET_SIZE / 2
        accent = STATE_ACCENT.get(self._state, STEEL)
        active = self._state in ("thinking", "listening", "speaking")
        elapsed = time.time() - self._t0

        # Pulse rate depends on state. Thinking is a faster, more anxious-looking
        # pulse so you can tell something's still happening even when nothing
        # is audible. Listening is mic-level-driven.
        if self._state == "thinking":
            breathe = (math.sin(elapsed * 6.5) + 1) * 0.5
        elif self._state == "speaking":
            breathe = (math.sin(elapsed * 5.0) + 1) * 0.5
        elif active:
            breathe = (math.sin(elapsed * 4.0) + 1) * 0.5
        else:
            breathe = (math.sin(elapsed * 1.6) + 1) * 0.5

        # In listening state, the orb pulses with the mic input level so the
        # user gets the "I hear you" feedback the bars used to provide.
        orb_scale = 1.0
        if self._state == "listening":
            orb_scale = 1.0 + 0.18 * self._smoothed_level

        # Outer halo (soft radial)
        halo_radius = (HALO + SIZE / 2) * orb_scale
        halo = QRadialGradient(cx, cy, halo_radius)
        a0 = QColor(accent); a0.setAlpha(int((80 if active else 40) + 80 * breathe))
        a1 = QColor(accent); a1.setAlpha(int((40 if active else 20) + 30 * breathe))
        a2 = QColor(accent); a2.setAlpha(0)
        halo.setColorAt(0.0, a0)
        halo.setColorAt(0.45, a1)
        halo.setColorAt(1.0, a2)
        p.setBrush(halo)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), halo_radius, halo_radius)

        # Orb gradient fill (top-light to accent)
        orb_radius = (SIZE / 2) * orb_scale
        orb = QRadialGradient(cx - SIZE * 0.18, cy - SIZE * 0.2, SIZE * 0.9 * orb_scale)
        hi = QColor(255, 255, 255); hi.setAlpha(230)
        mid = QColor(accent); mid.setAlpha(240)
        base = QColor(accent); base.setAlpha(255)
        orb.setColorAt(0.0, hi)
        orb.setColorAt(0.35, mid)
        orb.setColorAt(1.0, base)
        p.setBrush(orb)
        p.drawEllipse(QPointF(cx, cy), orb_radius, orb_radius)

        # Thin inner rim (white @ low alpha)
        rim = QColor(255, 255, 255, 80)
        p.setPen(rim)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), orb_radius - 0.5, orb_radius - 0.5)

    def move_near_cursor(self, x: int, y: int):
        self.move(x + OFFSET_X, y + OFFSET_Y)
