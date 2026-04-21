import ctypes

from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QGraphicsDropShadowEffect
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QColor, QPainterPath, QFont, QPolygonF
from PyQt6.QtCore import QPointF

_GWL_EXSTYLE       = -20
_WS_EX_TRANSPARENT = 0x00000020

MAX_WIDTH = 380
PAD       = 16
SHADOW    = 18           # shadow blur radius; widget reserves this much margin
ANCHOR_OFFSET = 42       # px away from anchor point so bubble floats clear of target
AUTO_HIDE_MS_DEFAULT = 6000


class SpeechBubble(QWidget):
    """Click-through, always-on-top floating rounded text bubble near the cursor.
    Uses a drop shadow and offset anchor so it reads as a floating callout and
    never overlaps the exact target the ghost is pointing at."""

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
        self._label.setFont(QFont("Segoe UI", 11))
        self._label.setStyleSheet("color: #1a1a1a;")
        self._label.setMaximumWidth(MAX_WIDTH - 2 * PAD)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

        # Reserve margin around the content so the shadow has room
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAD + SHADOW, PAD + SHADOW, PAD + SHADOW, PAD + SHADOW)
        layout.addWidget(self._label)

        # Apply drop shadow for the floating look
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(SHADOW * 1.6)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 100))
        self._label.setGraphicsEffect(shadow)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

        # Remember anchor so paintEvent can draw a tail pointing at it
        self._anchor_dx = 0   # anchor offset relative to bubble top-left
        self._anchor_dy = 0
        self._has_anchor = False

    # ── Painting ──────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Body rect sits inside the shadow margin
        left   = SHADOW
        top    = SHADOW
        right  = self.width() - SHADOW
        bottom = self.height() - SHADOW

        body = QPainterPath()
        body.addRoundedRect(float(left), float(top),
                            float(right - left), float(bottom - top),
                            14.0, 14.0)

        # Soft drop shadow (painted manually behind body for extra lift)
        for i in range(6, 0, -1):
            p.setBrush(QColor(0, 0, 0, 10))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(left - i, top - i + 3,
                              (right - left) + 2 * i, (bottom - top) + 2 * i,
                              14 + i, 14 + i)

        # Fill body
        p.fillPath(body, QColor(255, 249, 225, 248))   # warm cream, nearly opaque
        p.setPen(QColor(200, 160, 40, 200))
        p.drawPath(body)

        # Draw tail pointing at anchor, if known
        if self._has_anchor:
            self._draw_tail(p, left, top, right, bottom)

    def _draw_tail(self, p: QPainter, left: int, top: int, right: int, bottom: int):
        # Anchor point relative to widget
        ax, ay = self._anchor_dx, self._anchor_dy
        # Pick the bubble edge midpoint closest to the anchor
        cx = (left + right) / 2
        cy = (top + bottom) / 2
        dx = ax - cx
        dy = ay - cy

        # Snap tail to the nearest edge
        if abs(dx) > abs(dy):
            # left/right edge
            if dx > 0:
                base_x = right
                base_y = cy
                tip_x = min(ax, right + 30)
                tip_y = ay
                p1 = QPointF(base_x, base_y - 10)
                p2 = QPointF(base_x, base_y + 10)
            else:
                base_x = left
                base_y = cy
                tip_x = max(ax, left - 30)
                tip_y = ay
                p1 = QPointF(base_x, base_y - 10)
                p2 = QPointF(base_x, base_y + 10)
        else:
            if dy > 0:
                base_x = cx
                base_y = bottom
                tip_x = ax
                tip_y = min(ay, bottom + 30)
                p1 = QPointF(base_x - 10, base_y)
                p2 = QPointF(base_x + 10, base_y)
            else:
                base_x = cx
                base_y = top
                tip_x = ax
                tip_y = max(ay, top - 30)
                p1 = QPointF(base_x - 10, base_y)
                p2 = QPointF(base_x + 10, base_y)

        tail = QPolygonF([p1, QPointF(tip_x, tip_y), p2])
        p.setBrush(QColor(255, 249, 225, 248))
        p.setPen(QColor(200, 160, 40, 200))
        p.drawPolygon(tail)

    # ── Click-through ─────────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        try:
            hwnd = int(self.winId())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, style | _WS_EX_TRANSPARENT)
        except Exception:
            pass

    # ── API ───────────────────────────────────────────────────────────────────

    def show_text(self, anchor_x: int, anchor_y: int, text: str,
                  auto_hide_ms: int = AUTO_HIDE_MS_DEFAULT):
        """Show bubble floating near (anchor_x, anchor_y). Bubble is offset so it
        doesn't cover the target; a tail points back at the anchor."""
        self._label.setText(text or "")
        self._label.adjustSize()
        self.adjustSize()

        bw, bh = self.width(), self.height()

        # Choose placement: prefer below-right, but flip to stay on-screen
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

        # Compute anchor in widget-local coords for tail drawing
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
