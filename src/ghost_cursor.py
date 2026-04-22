import ctypes
import math
import random
import time
from collections import deque

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import (
    Qt,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QEasingCurve,
    pyqtSignal,
    QTimer,
)
from PyQt6.QtGui import (
    QPainter,
    QColor,
    QRadialGradient,
    QLinearGradient,
    QPen,
    QPainterPath,
)

# ── Palette ──────────────────────────────────────────────────────────────────
PINK_HOT   = QColor(236,  72, 153)   # #EC4899
PINK_SOFT  = QColor(244, 114, 182)   # #F472B6
ROSE       = QColor(251, 113, 133)   # #FB7185
RED        = QColor(239,  68,  68)   # #EF4444
VIOLET     = QColor(167, 139, 250)   # #A78BFA
BLUE       = QColor( 96, 165, 250)   # #60A5FA
MINT       = QColor( 52, 211, 153)   # #34D399
AMBER      = QColor(251, 191,  36)   # #FBBF24
WHITE_HOT  = QColor(255, 255, 255)

# State-dependent ring colors (body stays pink/red)
_STATE_RINGS = {
    "idle":      (VIOLET, BLUE),
    "thinking":  (VIOLET, PINK_HOT),
    "listening": (PINK_HOT, ROSE),
    "speaking":  (MINT, BLUE),
    "error":     (RED, AMBER),
}

SIZE = 110
FOLLOW_OFFSET_X = 28
FOLLOW_OFFSET_Y = 24
SPRING = 0.14            # how fast ghost drifts toward the target
BOB_Y_AMP = 4.5          # vertical bob amplitude (px)
BOB_X_AMP = 2.8          # horizontal drift amplitude (px)
BOB_Y_FREQ = 2.6         # rad/s
BOB_X_FREQ = 1.9         # rad/s
TRAIL_MAX = 12           # how many previous positions we remember for the sparkle trail
SPARKLE_COUNT = 3        # ambient sparkles

_GWL_EXSTYLE       = -20
_WS_EX_TRANSPARENT = 0x00000020


class GhostCursor(QWidget):
    arrived = pyqtSignal()

    MODE_FOLLOW = "follow"
    MODE_POINTING = "pointing"

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
        self.resize(SIZE, SIZE)

        self._t0 = time.time()
        self._mode = self.MODE_FOLLOW
        self._state = "idle"

        self._target_x = 0.0
        self._target_y = 0.0
        self._smoothed_x = 0.0
        self._smoothed_y = 0.0

        self._trail: deque[tuple[float, float, float]] = deque(maxlen=TRAIL_MAX)
        self._sparkles = [_Sparkle() for _ in range(SPARKLE_COUNT)]

        self._anim: QPropertyAnimation | None = None

        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(16)

    # ── Follow mode ──────────────────────────────────────────────────────────

    def follow(self, x: int, y: int):
        """Tell the ghost where the user's real cursor is. In follow mode we drift
        toward (x + offset, y + offset) with spring damping + ambient bob."""
        self._target_x = float(x + FOLLOW_OFFSET_X)
        self._target_y = float(y + FOLLOW_OFFSET_Y)
        if not self.isVisible():
            self._smoothed_x = self._target_x
            self._smoothed_y = self._target_y
            self._place(self._smoothed_x, self._smoothed_y)
            self.show()

    def set_state(self, state: str):
        if state != self._state and state in _STATE_RINGS:
            self._state = state

    # ── Guidance mode ────────────────────────────────────────────────────────

    def show_at(self, x: int, y: int):
        self._mode = self.MODE_POINTING
        self._place(x, y)
        self._smoothed_x, self._smoothed_y = float(x), float(y)
        if not self.isVisible():
            self.show()

    def animate_to(self, x: int, y: int, ms: int = 900):
        self._mode = self.MODE_POINTING
        if not self.isVisible():
            self._place(x, y)
            self.show()
        if self._anim:
            try:
                self._anim.finished.disconnect()
            except Exception:
                pass
            self._anim.stop()
            self._anim.deleteLater()
            self._anim = None
        target = QPoint(int(x - SIZE / 2), int(y - SIZE / 2))
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(ms)
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutExpo)

        def _on_done():
            self._smoothed_x, self._smoothed_y = float(x), float(y)
            self.arrived.emit()

        anim.finished.connect(_on_done)
        self._anim = anim
        anim.start()

    def release(self):
        """Guidance ended — return to follow mode but stay visible."""
        if self._anim:
            try:
                self._anim.finished.disconnect()
            except Exception:
                pass
            self._anim.stop()
            self._anim.deleteLater()
            self._anim = None
        self._mode = self.MODE_FOLLOW

    # ── Tick ─────────────────────────────────────────────────────────────────

    def _tick(self):
        now = time.time()
        if self._mode == self.MODE_FOLLOW:
            # Spring toward target
            self._smoothed_x += (self._target_x - self._smoothed_x) * SPRING
            self._smoothed_y += (self._target_y - self._smoothed_y) * SPRING
            elapsed = now - self._t0
            bob_y = BOB_Y_AMP * math.sin(elapsed * BOB_Y_FREQ)
            bob_x = BOB_X_AMP * math.sin(elapsed * BOB_X_FREQ + 0.7)
            # A tiny secondary wobble for character
            wob_y = 1.3 * math.sin(elapsed * 5.5)
            px = self._smoothed_x + bob_x
            py = self._smoothed_y + bob_y + wob_y
            self._place(px, py)
            self._trail.append((px, py, now))
        else:
            # Pointing mode: we're anchored (either by animate_to or static)
            self._trail.append((self._smoothed_x, self._smoothed_y, now))

        # Update sparkles regardless of mode
        for s in self._sparkles:
            s.step()

        self.update()

    def _place(self, cx: float, cy: float):
        self.move(int(cx - SIZE / 2), int(cy - SIZE / 2))

    # ── Paint ────────────────────────────────────────────────────────────────

    def _swoosh_path(self, cx: float, cy: float) -> QPainterPath:
        path = QPainterPath()
        tip  = QPointF(cx, cy)
        tail = QPointF(cx - 28, cy - 18)
        path.moveTo(tail)
        path.cubicTo(QPointF(cx - 18, cy + 6), QPointF(cx - 4, cy + 10), tip)
        path.cubicTo(QPointF(cx - 6, cy - 2), QPointF(cx - 18, cy - 10), tail)
        path.closeSubpath()
        return path

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = cy = SIZE // 2
        elapsed = time.time() - self._t0

        ring_a, ring_b = _STATE_RINGS.get(self._state, _STATE_RINGS["idle"])
        idle = self._mode == self.MODE_FOLLOW and self._state == "idle"

        # Sparkle particles (ambient, subtle)
        for s in self._sparkles:
            s.paint(p, cx, cy)

        # Sonar rings — larger / more intense in pointing mode or active states
        ring_speed = 0.6 if idle else 0.9
        ring_max = 22 if idle else 34
        ring_base_r = 10 if idle else 16
        ring_alpha_peak = 110 if idle else 180
        for phase_offset, ring_color in ((0.0, ring_a), (0.5, ring_b)):
            phase = ((elapsed * ring_speed) + phase_offset) % 1.0
            r = ring_base_r + ring_max * phase
            alpha = int(ring_alpha_peak * (1.0 - phase) ** 1.4)
            c = QColor(ring_color); c.setAlpha(alpha)
            p.setPen(QPen(c, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r, r)

        # Soft warm halo beneath the swoosh
        halo = QRadialGradient(cx - 4, cy - 2, 42)
        h0 = QColor(PINK_HOT);  h0.setAlpha(130 if not idle else 80)
        h1 = QColor(ROSE);      h1.setAlpha(70 if not idle else 45)
        h2 = QColor(ROSE);      h2.setAlpha(0)
        halo.setColorAt(0.0, h0)
        halo.setColorAt(0.55, h1)
        halo.setColorAt(1.0, h2)
        p.setBrush(halo)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx - 4, cy - 2), 42, 42)

        # Swoosh body — pink/red gradient
        path = self._swoosh_path(cx, cy)
        body_grad = QLinearGradient(cx - 28, cy - 18, cx, cy)
        body_grad.setColorAt(0.0, PINK_SOFT)
        body_grad.setColorAt(0.55, PINK_HOT)
        body_grad.setColorAt(1.0, RED)
        p.setBrush(body_grad)

        rim_grad = QLinearGradient(cx - 28, cy - 18, cx, cy)
        rim_grad.setColorAt(0.0, QColor(255, 200, 220, 160))
        rim_grad.setColorAt(1.0, QColor(180, 20, 60, 200))
        rim_pen = QPen(); rim_pen.setBrush(rim_grad); rim_pen.setWidthF(1.2)
        p.setPen(rim_pen)
        p.drawPath(path)

        # Highlight sliver along the upper curve
        hl = QPainterPath()
        hl.moveTo(cx - 22, cy - 14)
        hl.cubicTo(
            QPointF(cx - 14, cy - 8),
            QPointF(cx - 6, cy - 5),
            QPointF(cx - 2, cy - 2),
        )
        # Shimmer: the highlight breathes
        shimmer = 120 + int(60 * (math.sin(elapsed * 3.0) + 1) / 2)
        hl_pen = QPen(QColor(255, 255, 255, shimmer), 1.3)
        p.setPen(hl_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(hl)

        # Tip glow (visible landing point when pointing)
        tip_glow = QRadialGradient(cx, cy, 7)
        tip_glow.setColorAt(0.0, WHITE_HOT)
        tip_glow.setColorAt(0.5, QColor(255, 200, 215, 230))
        tip_edge = QColor(PINK_HOT); tip_edge.setAlpha(0)
        tip_glow.setColorAt(1.0, tip_edge)
        p.setBrush(tip_glow)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), 5, 5)

    def showEvent(self, event):
        super().showEvent(event)
        try:
            hwnd = int(self.winId())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, style | _WS_EX_TRANSPARENT)
        except Exception:
            pass


class _Sparkle:
    """A tiny drifting star that orbits the cursor tip with random lifetimes.
    Gives the fairy some 'alive' flavor without being distracting."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.life = random.uniform(1.2, 2.6)
        self.age = random.uniform(0.0, self.life)
        # Polar drift from the tip
        self.angle = random.uniform(0, math.tau)
        self.radius = random.uniform(6, 26)
        self.angular_vel = random.uniform(-0.8, 0.8)
        self.radial_vel = random.uniform(8, 16)
        self.size = random.uniform(1.3, 2.4)
        self.hue = random.choice([PINK_SOFT, VIOLET, WHITE_HOT])

    def step(self):
        self.age += 0.016
        if self.age >= self.life:
            self.reset()
            self.age = 0.0
        self.angle += self.angular_vel * 0.016
        self.radius += self.radial_vel * 0.016

    def paint(self, p: QPainter, cx: float, cy: float):
        if self.age >= self.life:
            return
        t = self.age / self.life
        # fade in then fade out
        alpha_curve = 4 * t * (1 - t)
        x = cx + math.cos(self.angle) * self.radius
        y = cy + math.sin(self.angle) * self.radius
        c = QColor(self.hue)
        c.setAlpha(int(220 * alpha_curve))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        r = self.size * (0.6 + 0.4 * alpha_curve)
        p.drawEllipse(QPointF(x, y), r, r)
