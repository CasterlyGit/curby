import ctypes

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QPoint, QPropertyAnimation, QEasingCurve, pyqtSignal, QTimer
from PyQt6.QtGui import QPainter, QColor, QRadialGradient, QPen

SIZE = 44   # widget dimensions; cursor tip is at the center

_GWL_EXSTYLE      = -20
_WS_EX_TRANSPARENT = 0x00000020


class GhostCursor(QWidget):
    arrived = pyqtSignal()  # emitted when each animation step completes

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

        self._pulse = 0.0
        self._pulse_dir = 1
        self._anim: QPropertyAnimation | None = None

        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(16)

    def _tick(self):
        self._pulse += 0.05 * self._pulse_dir
        if self._pulse >= 1.0:
            self._pulse = 1.0
            self._pulse_dir = -1
        elif self._pulse <= 0.0:
            self._pulse = 0.0
            self._pulse_dir = 1
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = cy = SIZE // 2
        t = max(0.0, min(1.0, self._pulse))

        # Outer glow
        grad = QRadialGradient(cx, cy, SIZE // 2)
        grad.setColorAt(0.0, QColor(255, 210, 0, int(60 + 80 * t)))
        grad.setColorAt(0.5, QColor(255, 180, 0, int(40 + 60 * t)))
        grad.setColorAt(1.0, QColor(255, 180, 0, 0))
        p.setBrush(grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(0, 0, SIZE, SIZE)

        # Crosshair
        inner = int(6 + 3 * t)
        pen = QPen(QColor(255, 220, 30, 200), 1.5)
        p.setPen(pen)
        p.drawLine(cx, 4,          cx, cy - inner)
        p.drawLine(cx, cy + inner, cx, SIZE - 4)
        p.drawLine(4,          cy, cx - inner, cy)
        p.drawLine(cx + inner, cy, SIZE - 4,   cy)

        # Center dot
        p.setBrush(QColor(255, 230, 50, 230))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(cx - inner // 2, cy - inner // 2, inner, inner)

    def showEvent(self, event):
        super().showEvent(event)
        # WA_TransparentForMouseEvents alone is not enough on Windows;
        # we need the OS-level WS_EX_TRANSPARENT extended style.
        try:
            hwnd = int(self.winId())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, style | _WS_EX_TRANSPARENT)
        except Exception:
            pass

    def show_at(self, x: int, y: int):
        """Place cursor center at screen position (x, y) and show."""
        print(f"[ghost] show_at ({x},{y})")
        self.move(x - SIZE // 2, y - SIZE // 2)
        self.show()

    def animate_to(self, x: int, y: int, ms: int = 1000):
        """Smoothly move cursor center to screen position (x, y); emits arrived once when done."""
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
        anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        anim.finished.connect(self.arrived)
        self._anim = anim
        anim.start()
