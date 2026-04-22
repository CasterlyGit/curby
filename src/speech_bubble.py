import ctypes

from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QGraphicsDropShadowEffect
from PyQt6.QtCore import Qt, QTimer, QPointF
from PyQt6.QtGui import (
    QPainter,
    QColor,
    QPainterPath,
    QFont,
    QPolygonF,
    QLinearGradient,
    QPen,
)

_GWL_EXSTYLE       = -20
_WS_EX_TRANSPARENT = 0x00000020

# ── Vista / Curby palette ─────────────────────────────────────────────────────
BG_NAVY      = QColor(17, 24, 39, 242)    # #111827 @ 95%
BG_NAVY_LT   = QColor(31, 41, 55, 242)    # #1F2937 gradient end
VIOLET       = QColor(167, 139, 250)      # #A78BFA
BLUE         = QColor( 96, 165, 250)      # #60A5FA
TEXT_COOL    = QColor(244, 244, 248)      # #F4F4F8 near-white cool

MAX_WIDTH    = 420
PAD          = 18
SHADOW       = 22           # shadow blur radius; widget reserves this margin
ANCHOR_OFFSET = 48          # px away from anchor point
AUTO_HIDE_MS_DEFAULT = 6000


class SpeechBubble(QWidget):
    """Click-through, always-on-top dark floating bubble with gradient border."""

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
        font = QFont("Segoe UI", 11)
        font.setWeight(QFont.Weight.Medium)
        self._label.setFont(font)
        self._label.setStyleSheet("color: #F4F4F8; letter-spacing: 0.1px;")
        self._label.setMaximumWidth(MAX_WIDTH - 2 * PAD)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAD + SHADOW, PAD + SHADOW, PAD + SHADOW, PAD + SHADOW)
        layout.addWidget(self._label)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(SHADOW * 1.8)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 180))
        self.setGraphicsEffect(shadow)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

        self._anchor_dx = 0
        self._anchor_dy = 0
        self._has_anchor = False

    # ── Painting ──────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        left, top    = SHADOW, SHADOW
        right        = self.width() - SHADOW
        bottom       = self.height() - SHADOW
        w, h         = right - left, bottom - top

        body = QPainterPath()
        body.addRoundedRect(float(left), float(top), float(w), float(h), 14.0, 14.0)

        # Dark body with subtle vertical gradient
        body_grad = QLinearGradient(left, top, left, bottom)
        body_grad.setColorAt(0.0, BG_NAVY)
        body_grad.setColorAt(1.0, BG_NAVY_LT)
        p.fillPath(body, body_grad)

        # Gradient border (violet → blue)
        border_grad = QLinearGradient(left, top, right, bottom)
        border_grad.setColorAt(0.0, VIOLET)
        border_grad.setColorAt(1.0, BLUE)
        border_pen = QPen()
        border_pen.setBrush(border_grad)
        border_pen.setWidthF(1.6)
        p.setPen(border_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(body)

        # Inner glow along top edge
        glow = QColor(VIOLET)
        glow.setAlpha(28)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawRoundedRect(left + 1, top + 1, w - 2, 20, 12, 12)

        if self._has_anchor:
            self._draw_tail(p, left, top, right, bottom)

    def _draw_tail(self, p: QPainter, left: int, top: int, right: int, bottom: int):
        ax, ay = self._anchor_dx, self._anchor_dy
        cx = (left + right) / 2
        cy = (top + bottom) / 2
        dx = ax - cx
        dy = ay - cy

        if abs(dx) > abs(dy):
            if dx > 0:
                base_x, base_y = right, cy
                tip_x, tip_y = min(ax, right + 30), ay
                p1 = QPointF(base_x, base_y - 9)
                p2 = QPointF(base_x, base_y + 9)
            else:
                base_x, base_y = left, cy
                tip_x, tip_y = max(ax, left - 30), ay
                p1 = QPointF(base_x, base_y - 9)
                p2 = QPointF(base_x, base_y + 9)
        else:
            if dy > 0:
                base_x, base_y = cx, bottom
                tip_x, tip_y = ax, min(ay, bottom + 30)
                p1 = QPointF(base_x - 9, base_y)
                p2 = QPointF(base_x + 9, base_y)
            else:
                base_x, base_y = cx, top
                tip_x, tip_y = ax, max(ay, top - 30)
                p1 = QPointF(base_x - 9, base_y)
                p2 = QPointF(base_x + 9, base_y)

        tail = QPolygonF([p1, QPointF(tip_x, tip_y), p2])

        # Gradient fill (same navy as body)
        tail_grad = QLinearGradient(p1, QPointF(tip_x, tip_y))
        tail_grad.setColorAt(0.0, BG_NAVY)
        tail_grad.setColorAt(1.0, BG_NAVY_LT)
        p.setBrush(tail_grad)

        # Matching gradient border
        border_grad = QLinearGradient(p1, p2)
        border_grad.setColorAt(0.0, VIOLET)
        border_grad.setColorAt(1.0, BLUE)
        pen = QPen()
        pen.setBrush(border_grad)
        pen.setWidthF(1.6)
        p.setPen(pen)
        p.drawPolygon(tail)

    def showEvent(self, event):
        super().showEvent(event)
        try:
            hwnd = int(self.winId())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, style | _WS_EX_TRANSPARENT)
        except Exception:
            pass

    def show_text(self, anchor_x: int, anchor_y: int, text: str,
                  auto_hide_ms: int = AUTO_HIDE_MS_DEFAULT):
        self._label.setText(text or "")
        self._label.adjustSize()
        self.adjustSize()

        bw, bh = self.width(), self.height()
        screen = self.screen().geometry() if self.screen() else None
        place_x = anchor_x + ANCHOR_OFFSET
        place_y = anchor_y + ANCHOR_OFFSET

        if screen is not None:
            if place_x + bw > screen.right() - 4:
                place_x = anchor_x - ANCHOR_OFFSET - bw
            if place_y + bh > screen.bottom() - 4:
                place_y = anchor_y - ANCHOR_OFFSET - bh
            place_x = max(screen.left() + 4, min(place_x, screen.right() - bw - 4))
            place_y = max(screen.top() + 4, min(place_y, screen.bottom() - bh - 4))

        self.move(place_x, place_y)

        self._anchor_dx = anchor_x - place_x
        self._anchor_dy = anchor_y - place_y
        self._has_anchor = True

        self.show()
        self.raise_()
        self._timer.stop()
        if auto_hide_ms and auto_hide_ms > 0:
            self._timer.start(auto_hide_ms)
        self.update()

    def hide(self):
        self._timer.stop()
        super().hide()
