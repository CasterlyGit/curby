from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QColor, QBrush

SIZE = 22
OFFSET_X = 20
OFFSET_Y = 20

COLORS = {
    "idle":      QColor(80,  80, 100, 160),
    "listening": QColor(240, 120,  60, 255),
    "thinking":  QColor(100, 160, 255, 255),
    "speaking":  QColor(100, 220, 130, 220),
    "error":     QColor(240, 100, 100, 220),
}


class BuddyIcon(QWidget):
    def __init__(self):
        super().__init__()
        self._state = "idle"
        self._pulse = 0.0
        self._pulse_dir = 1
        self._setup()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def _setup(self):
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(SIZE + 8 + 4, SIZE + 8 + 4)

    def set_state(self, state: str):
        self._state = state
        self.update()

    def _tick(self):
        if self._state in ("thinking", "listening", "speaking"):
            self._pulse += 0.08 * self._pulse_dir
            if self._pulse >= 1.0:
                self._pulse_dir = -1
            elif self._pulse <= 0.0:
                self._pulse_dir = 1
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(COLORS.get(self._state, COLORS["idle"]))
        if self._state in ("thinking", "listening", "speaking"):
            color.setAlpha(int(120 + 135 * max(0.0, min(1.0, self._pulse))))
        # outer glow ring
        glow = QColor(color)
        glow.setAlpha(40)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(0, 0, SIZE + 8, SIZE + 8)
        # solid dot
        p.setBrush(QBrush(color))
        p.drawEllipse(4, 4, SIZE, SIZE)

    def move_near_cursor(self, x: int, y: int):
        self.move(x + OFFSET_X, y + OFFSET_Y)
