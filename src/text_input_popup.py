from PyQt6.QtWidgets import QWidget, QLineEdit, QVBoxLayout
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPainterPath, QFont, QKeyEvent

WIDTH = 360
PAD = 10


class TextInputPopup(QWidget):
    """Borderless QLineEdit near the cursor. Enter submits, Esc cancels."""

    submitted = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._edit = QLineEdit(self)
        self._edit.setPlaceholderText("ask curby…  (Enter to send, Esc to cancel)")
        self._edit.setFont(QFont("Segoe UI", 11))
        self._edit.setStyleSheet(
            "QLineEdit {"
            "  background: rgba(28, 30, 40, 240);"
            "  color: #e8eaf0;"
            "  border: 1px solid rgba(255,255,255,40);"
            "  border-radius: 8px;"
            "  padding: 8px 10px;"
            "  selection-background-color: rgba(125,211,252,80);"
            "}"
        )
        self._edit.returnPressed.connect(self._on_submit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAD, PAD, PAD, PAD)
        layout.addWidget(self._edit)

        self.setFixedWidth(WIDTH + 2 * PAD)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0.0, 0.0, float(self.width()), float(self.height()), 12.0, 12.0)
        p.fillPath(path, QColor(22, 24, 32, 230))
        p.setPen(QColor(255, 255, 255, 50))
        p.drawPath(path)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self._on_cancel()
            return
        super().keyPressEvent(event)

    def _on_submit(self):
        text = self._edit.text().strip()
        self._edit.clear()
        self.hide()
        if text:
            self.submitted.emit(text)

    def _on_cancel(self):
        self._edit.clear()
        self.hide()
        self.cancelled.emit()

    def show_at(self, x: int, y: int):
        self.adjustSize()
        screen = self.screen().geometry() if self.screen() else None
        w, h = self.width(), self.height()
        nx = x + 20
        ny = y + 20
        if screen is not None:
            nx = max(screen.left() + 4, min(nx, screen.right() - w - 4))
            ny = max(screen.top() + 4, min(ny, screen.bottom() - h - 4))
        self.move(nx, ny)
        self.show()
        self.raise_()
        from src.mac_window import make_always_visible
        make_always_visible(self)
        self.activateWindow()
        self._edit.setFocus()
