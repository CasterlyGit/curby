"""Curby's voice indicator — a small waveform glyph that follows the cursor.

States:
  idle       — curby is running but not listening; bars are short, dim, static.
  listening  — key is held; bars are bright; height reacts to mic input level.
  processing — between mic-stop and task-spawn; gentle spinner-style sweep.

The widget is anchored to the cursor (offset slightly so it doesn't sit on top
of clicks) via CursorTracker. It does not steal focus or block clicks.
"""
import math
import time

from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath
from PyQt6.QtWidgets import QWidget


SIZE_W = 64
SIZE_H = 28
RADIUS = 14

NUM_BARS = 5
BAR_WIDTH = 3
BAR_GAP = 4

# Offset from cursor — bars sit just below+right of the tip
OFFSET_X = 18
OFFSET_Y = 14

# Smoothing constants
LEVEL_DECAY = 0.78        # last-level → current per frame; lower = snappier

# Palette
BG          = QColor(14, 16, 24, 235)
DIM_BAR     = QColor(125, 211, 252, 200)   # idle: visible — clearly shows curby is on
ACTIVE_BAR  = QColor(  0, 217, 255, 255)   # listening: bright neon cyan
SPEAK_BAR   = QColor(244,  63,  94, 255)   # speaking: rose (when level high)
PROC_BAR    = QColor(217, 119,   6, 230)   # processing: orange


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
        """state ∈ {idle, listening, processing}"""
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
        # Exponential smoothing toward target level
        self._smoothed_level = (LEVEL_DECAY * self._smoothed_level
                                + (1 - LEVEL_DECAY) * self._level)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Pill background
        rect = QRectF(0, 0, self.width(), self.height()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, RADIUS, RADIUS)
        p.fillPath(path, BG)
        p.setPen(QPen(QColor(255, 255, 255, 35), 1))
        p.drawPath(path)

        # Bars
        elapsed = time.time() - self._t0
        cx = self.width() / 2
        cy = self.height() / 2
        total_w = NUM_BARS * BAR_WIDTH + (NUM_BARS - 1) * BAR_GAP
        x0 = cx - total_w / 2

        # Decide bar color & target heights from state
        if self._state == "idle":
            base_color = DIM_BAR
            # Slightly bigger gentle bob so the indicator is clearly visible
            # at rest — confirms "curby is on" without being noisy.
            heights = [0.32 + 0.14 * math.sin(elapsed * 1.6 + ph)
                       for ph in self._phases]
        elif self._state == "processing":
            base_color = PROC_BAR
            # Sweep — single tall bar that travels left → right
            sweep = (elapsed * 1.4) % 1.0
            heights = []
            for i in range(NUM_BARS):
                d = abs((i + 0.5) / NUM_BARS - sweep)
                heights.append(0.25 + 0.65 * max(0.0, 1.0 - d * 4))
        else:  # listening
            level = self._smoothed_level
            base_color = SPEAK_BAR if level > 0.45 else ACTIVE_BAR
            # Each bar reacts to level + a per-bar wobble
            heights = []
            for i, ph in enumerate(self._phases):
                wobble = 0.18 * math.sin(elapsed * 7.2 + ph * 1.7)
                h = 0.22 + 0.85 * level + wobble * (0.4 + level)
                heights.append(max(0.18, min(1.0, h)))

        max_bar_h = self.height() - 8
        for i, h_norm in enumerate(heights):
            bx = x0 + i * (BAR_WIDTH + BAR_GAP)
            bh = max_bar_h * h_norm
            by = cy - bh / 2
            bar_rect = QRectF(bx, by, BAR_WIDTH, bh)
            br_path = QPainterPath()
            br_path.addRoundedRect(bar_rect, BAR_WIDTH / 2, BAR_WIDTH / 2)
            p.fillPath(br_path, base_color)
