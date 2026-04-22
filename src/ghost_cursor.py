import ctypes
import math
import time

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QPoint, QPointF, QPropertyAnimation, QEasingCurve, pyqtSignal, QTimer
from PyQt6.QtGui import QPainter, QColor, QRadialGradient, QPen

# ── Vista / Curby palette ────────────────────────────────────────────────────
VIOLET       = QColor(167, 139, 250)   # #A78BFA primary accent
BLUE         = QColor( 96, 165, 250)   # #60A5FA secondary accent
VIOLET_LIGHT = QColor(196, 181, 253)   # #C4B5FD highlight
WHITE_HOT    = QColor(255, 255, 255)   # bright core

SIZE = 96   # widget box (tip is at center)

_GWL_EXSTYLE      = -20
_WS_EX_TRANSPARENT = 0x00000020


class GhostCursor(QWidget):
    arrived = pyqtSignal()

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
        self._anim: QPropertyAnimation | None = None

        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self.update)
        self._tick_timer.start(16)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = cy = SIZE // 2

        elapsed = time.time() - self._t0

        # Two staggered sonar rings expanding outward
        for phase_offset in (0.0, 0.5):
            phase = ((elapsed * 0.9) + phase_offset) % 1.0
            r = 14 + 30 * phase
            alpha = int(180 * (1.0 - phase) ** 1.4)
            color = VIOLET if phase_offset == 0.0 else BLUE
            ring_color = QColor(color)
            ring_color.setAlpha(alpha)
            p.setPen(QPen(ring_color, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r, r)

        # Soft radial halo underneath
        halo = QRadialGradient(cx, cy, 30)
        halo_v = QColor(VIOLET); halo_v.setAlpha(110)
        halo_b = QColor(BLUE);   halo_b.setAlpha(60)
        halo_z = QColor(BLUE);   halo_z.setAlpha(0)
        halo.setColorAt(0.0, halo_v)
        halo.setColorAt(0.55, halo_b)
        halo.setColorAt(1.0, halo_z)
        p.setBrush(halo)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), 30, 30)

        # Pulsing outer ring (static radius, breathing opacity)
        breathe = (math.sin(elapsed * 3.2) + 1) * 0.5
        outer_ring = QColor(VIOLET_LIGHT)
        outer_ring.setAlpha(int(120 + 90 * breathe))
        p.setPen(QPen(outer_ring, 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), 12, 12)

        # Center bright core (gradient)
        core = QRadialGradient(cx, cy, 8)
        core.setColorAt(0.0, WHITE_HOT)
        core.setColorAt(0.45, QColor(VIOLET_LIGHT))
        core_edge = QColor(VIOLET); core_edge.setAlpha(0)
        core.setColorAt(1.0, core_edge)
        p.setBrush(core)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), 7, 7)

    def showEvent(self, event):
        super().showEvent(event)
        try:
            hwnd = int(self.winId())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, style | _WS_EX_TRANSPARENT)
        except Exception:
            pass

    def show_at(self, x: int, y: int):
        print(f"[ghost] show_at ({x},{y})")
        self.move(x - SIZE // 2, y - SIZE // 2)
        self.show()

    def animate_to(self, x: int, y: int, ms: int = 900):
        print(f"[ghost] animate_to ({x},{y}) visible={self.isVisible()}")
        if not self.isVisible():
            self.move(x - SIZE // 2, y - SIZE // 2)
            self.show()
        if self._anim:
            try:
                self._anim.finished.disconnect()
            except Exception:
                pass
            self._anim.stop()
            self._anim.deleteLater()
            self._anim = None
        target = QPoint(x - SIZE // 2, y - SIZE // 2)
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(ms)
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutExpo)
        anim.finished.connect(self.arrived)
        self._anim = anim
        anim.start()
