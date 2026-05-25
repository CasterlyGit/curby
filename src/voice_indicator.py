"""Curby's voice indicator — a small waveform glyph that follows the cursor.

States:
  idle       — curby is running but not listening; bars are short, dim, static.
  listening  — key is held; bars are bright; height reacts to mic input level.
  processing — between mic-stop and task-spawn; gentle left→right sweep (orange).
  thinking   — quick-ask is waiting on Claude; loading-dots wave in violet.
  speaking   — Claude is replying via TTS; rolling sine wave in mint green.

The widget is anchored to the cursor (offset slightly so it doesn't sit on top
of clicks) via CursorTracker. It does not steal focus or block clicks.

A small neon cursor glyph sits to the LEFT of the bars — same shape as the
task-puck cursor, scaled down and tinted to match the current state accent.
"""
import math
import time

from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPainterPath, QLinearGradient, QRadialGradient,
)
from PyQt6.QtWidgets import QWidget


# ── Layout ──────────────────────────────────────────────────────────────────
GLYPH_W   = 18                # neon cursor glyph slot
GLYPH_GAP = 4
BARS_W    = 62                # bars slot
SIZE_W    = GLYPH_W + GLYPH_GAP + BARS_W   # total pill width
SIZE_H    = 30
RADIUS    = 15

NUM_BARS  = 5
BAR_WIDTH = 3
BAR_GAP   = 4

# Offset from cursor — pill sits just below+right of the tip
OFFSET_X  = 18
OFFSET_Y  = 14

# Smoothing
LEVEL_DECAY = 0.78        # last-level → current per frame; lower = snappier

# ── Palette ─────────────────────────────────────────────────────────────────
BG          = QColor(14, 16, 24, 235)
EDGE        = QColor(255, 255, 255, 35)

DIM_BAR     = QColor(125, 211, 252, 200)   # idle: visible — clearly shows curby is on
ACTIVE_BAR  = QColor(  0, 217, 255, 255)   # listening: bright neon cyan
SPEAK_BAR   = QColor(244,  63,  94, 255)   # listening @ high level: rose
PROC_BAR    = QColor(217, 119,   6, 230)   # processing: orange
THINK_BAR   = QColor(167, 139, 250, 255)   # thinking: violet
ANSWER_BAR  = QColor( 52, 211, 153, 255)   # speaking: mint


class VoiceIndicator(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self.resize(SIZE_W, SIZE_H)

        self._state = "idle"
        self._level = 0.0
        self._smoothed_level = 0.0
        # Per-bar phase offsets so bars don't move in lockstep
        self._phases = [i * 0.4 for i in range(NUM_BARS)]
        self._t0 = time.time()

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start(33)              # 30fps — smooth enough, easy on cpu

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_state(self, state: str):
        """state ∈ {idle, listening, processing, thinking, speaking, error}"""
        self._state = state
        if state != "listening":
            self._level = 0.0
        self.update()

    def set_level(self, level_0_to_1: float):
        """Latest mic input level, normalized to 0..1."""
        self._level = max(0.0, min(1.0, level_0_to_1))

    def follow(self, cursor_x: int, cursor_y: int):
        """Move the widget so its top-left sits at cursor + offset."""
        self.move(cursor_x + OFFSET_X, cursor_y + OFFSET_Y)
        if not self.isVisible():
            self.show()
            self.raise_()

    # ── Tick / paint ──────────────────────────────────────────────────────────

    def _on_tick(self):
        self._smoothed_level = (LEVEL_DECAY * self._smoothed_level
                                + (1 - LEVEL_DECAY) * self._level)
        self.update()

    def _state_accent(self) -> QColor:
        if self._state == "listening":
            return SPEAK_BAR if self._smoothed_level > 0.45 else ACTIVE_BAR
        if self._state == "processing": return PROC_BAR
        if self._state == "thinking":   return THINK_BAR
        if self._state == "speaking":   return ANSWER_BAR
        if self._state == "error":      return QColor(248, 113, 113)
        return DIM_BAR

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Pill background
        rect = QRectF(0, 0, self.width(), self.height()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, RADIUS, RADIUS)
        p.fillPath(path, BG)
        p.setPen(QPen(EDGE, 1))
        p.drawPath(path)

        accent = self._state_accent()
        self._paint_glyph(p, accent)
        self._paint_bars(p, accent)

    # ── Neon cursor glyph (left slot) ─────────────────────────────────────────

    def _paint_glyph(self, p: QPainter, accent: QColor):
        """Tiny neon cursor — same shape family as the task pucks, sized to
        sit comfortably in the left slot of the pill. Has a soft glow halo
        whose intensity depends on state."""
        cx = GLYPH_W / 2 + 2
        cy = self.height() / 2

        # Glow halo behind the glyph — pulses faster in active states.
        elapsed = time.time() - self._t0
        if self._state in ("listening", "thinking", "speaking"):
            pulse = 0.55 + 0.35 * math.sin(elapsed * 5.0)
        elif self._state == "processing":
            pulse = 0.55 + 0.25 * math.sin(elapsed * 3.5)
        else:
            pulse = 0.35
        radius = 11
        grad = QRadialGradient(QPointF(cx, cy), radius)
        c0 = QColor(accent); c0.setAlpha(int(130 * pulse))
        c1 = QColor(accent); c1.setAlpha(0)
        grad.setColorAt(0.0, c0)
        grad.setColorAt(1.0, c1)
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), radius, radius)

        # Cursor path — same shape as dock_widget's cursor, scaled down.
        # Bbox roughly 16x26 in source units; we want ~14px tall here.
        scale = 14.0 / 26.0
        path = QPainterPath()
        path.moveTo(0.0,  0.0)
        path.cubicTo(0.0, 1.6, 0.4, 2.0, 0.6, 2.5)
        path.lineTo(0.6, 20.5)
        path.cubicTo(0.6, 22.4, 2.0, 22.8, 3.2, 21.6)
        path.lineTo(6.6, 17.4)
        path.cubicTo(7.0, 17.0, 7.6, 17.0, 7.9, 17.7)
        path.lineTo(11.0, 25.7)
        path.cubicTo(11.3, 26.5, 12.1, 26.8, 12.9, 26.4)
        path.lineTo(13.6, 26.1)
        path.cubicTo(14.4, 25.7, 14.6, 24.8, 14.2, 24.0)
        path.lineTo(11.1, 16.0)
        path.lineTo(15.2, 15.1)
        path.cubicTo(16.4, 14.8, 16.6, 13.6, 15.6, 12.8)
        path.lineTo(0.6, 0.0)
        path.closeSubpath()

        p.save()
        p.translate(cx, cy)
        p.scale(scale, scale)
        p.translate(-8.0, -13.0)

        # Body gradient
        grad = QLinearGradient(0, 0, 0, 26)
        top = QColor(accent).lighter(135)
        bot = QColor(accent)
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bot)
        p.setBrush(QBrush(grad))
        outer = QColor(accent).lighter(180); outer.setAlpha(220)
        p.setPen(QPen(outer, 1.0))
        p.drawPath(path)

        # Glassy highlight along the leading edge.
        hi = QPainterPath()
        hi.moveTo(1.4, 1.6); hi.lineTo(1.4, 16.0)
        hi.lineTo(2.6, 17.0); hi.lineTo(2.6, 2.4)
        hi.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 80))
        p.drawPath(hi)
        p.restore()

    # ── Bars (right slot) ─────────────────────────────────────────────────────

    def _paint_bars(self, p: QPainter, accent: QColor):
        elapsed = time.time() - self._t0
        bars_x0 = GLYPH_W + GLYPH_GAP
        bars_cx = bars_x0 + BARS_W / 2  # noqa: F841
        bars_cy = self.height() / 2

        # Heights per state — each state has its OWN distinct motion shape so
        # the user can read what's happening at a glance.
        if self._state == "idle":
            # Gentle sin bob — confirms "curby is alive" without being noisy.
            heights = [0.32 + 0.14 * math.sin(elapsed * 1.6 + ph) for ph in self._phases]

        elif self._state == "listening":
            level = self._smoothed_level
            heights = []
            for i, ph in enumerate(self._phases):
                wobble = 0.18 * math.sin(elapsed * 7.2 + ph * 1.7)
                h = 0.22 + 0.85 * level + wobble * (0.4 + level)
                heights.append(max(0.18, min(1.0, h)))

        elif self._state == "processing":
            # Sweep — single tall bar that travels left → right.
            sweep = (elapsed * 1.4) % 1.0
            heights = []
            for i in range(NUM_BARS):
                d = abs((i + 0.5) / NUM_BARS - sweep)
                heights.append(0.25 + 0.65 * max(0.0, 1.0 - d * 4))

        elif self._state == "thinking":
            # Loading-dots wave — one bar at a time pulses tall, cycling
            # through the bars. Distinct from "processing" which is a
            # continuous sweep — this is discrete, pulse-by-pulse, like
            # a thoughtful "...hmm".
            phase = (elapsed * 2.2) % NUM_BARS
            heights = []
            for i in range(NUM_BARS):
                # Distance in cycle space, wrapping at NUM_BARS
                d = min(abs(i - phase), NUM_BARS - abs(i - phase))
                pulse = max(0.0, 1.0 - d * 1.2)
                heights.append(0.30 + 0.70 * pulse)

        elif self._state == "speaking":
            # Rolling traveling wave — a sine wave that travels through
            # all bars together, mid-amplitude. Reads as "she's talking
            # now" — different from idle (low-amp synchronized bob) and
            # different from listening (audio-reactive jitter).
            heights = []
            for i in range(NUM_BARS):
                # Phase per bar offset so the wave appears to flow rightward
                phase = elapsed * 6.0 - i * 0.9
                wave = (math.sin(phase) + 1) * 0.5  # 0..1
                heights.append(0.30 + 0.55 * wave)

        elif self._state == "error":
            # Flat, dim, with a slow throb — something's wrong.
            throb = 0.25 + 0.05 * math.sin(elapsed * 3.0)
            heights = [throb] * NUM_BARS

        else:
            heights = [0.3] * NUM_BARS

        max_bar_h = self.height() - 8
        for i, h_norm in enumerate(heights):
            bx = bars_x0 + 4 + i * (BAR_WIDTH + BAR_GAP)
            bh = max_bar_h * h_norm
            by = bars_cy - bh / 2
            bar_rect = QRectF(bx, by, BAR_WIDTH, bh)
            br_path = QPainterPath()
            br_path.addRoundedRect(bar_rect, BAR_WIDTH / 2, BAR_WIDTH / 2)
            p.fillPath(br_path, accent)
