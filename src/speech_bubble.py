import ctypes

from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QColor, QPainterPath, QFont

_GWL_EXSTYLE      = -20
_WS_EX_TRANSPARENT = 0x00000020

MAX_WIDTH = 360
PAD       = 14
AUTO_HIDE_MS_DEFAULT = 6000


class SpeechBubble(QWidget):
    """Click-through, always-on-top rounded text bubble near the cursor."""

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

        self._label = QLabel("", self)
        self._label.setWordWrap(True)
        self._label.setFont(QFont("Segoe UI", 10))
        self._label.setStyleSheet("color: #1a1a1a;")
        self._label.setMaximumWidth(MAX_WIDTH - 2 * PAD)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAD, PAD, PAD, PAD)
        layout.addWidget(self._label)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0.0, 0.0, float(self.width()), float(self.height()), 12.0, 12.0)
        p.fillPath(path, QColor(255, 248, 220, 240))     # warm cream
        p.setPen(QColor(200, 160, 40, 220))
        p.drawPath(path)

    def showEvent(self, event):
        super().showEvent(event)
        try:
            hwnd = int(self.winId())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, style | _WS_EX_TRANSPARENT)
        except Exception:
            pass

    def show_text(self, x: int, y: int, text: str, auto_hide_ms: int = AUTO_HIDE_MS_DEFAULT):
        """Show bubble near (x, y) with text. Auto-hides after auto_hide_ms; 0 disables."""
        self._label.setText(text or "")
        self._label.adjustSize()
        self.adjustSize()

        # Anchor bubble below-right of cursor, but keep on-screen
        screen = self.screen().geometry() if self.screen() else None
        bw, bh = self.width(), self.height()
        nx = x + 24
        ny = y + 24
        if screen is not None:
            nx = max(screen.left() + 4, min(nx, screen.right() - bw - 4))
            ny = max(screen.top() + 4, min(ny, screen.bottom() - bh - 4))
        self.move(nx, ny)

        self.show()
        self.raise_()
        self._timer.stop()
        if auto_hide_ms and auto_hide_ms > 0:
            self._timer.start(auto_hide_ms)

    def hide(self):
        self._timer.stop()
        super().hide()
