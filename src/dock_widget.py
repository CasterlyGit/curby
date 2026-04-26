"""One floating puck per running task, stacked along the right edge of the screen.

Visual identity is a dark rounded square with a neon-glowing cursor arrow.
Collapsed: just the icon. Hover-expand reveals a side panel to the left with
title, latest status, and contextual buttons (pause/cancel/amend while
running; amend/dismiss after).

The puck is click-through except when the cursor is actually inside it
(so it never blocks clicks on the apps below). The TaskManager polls the
global cursor and toggles transparency + expansion accordingly.
"""
import math
import time

from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QFont, QPainterPath, QBrush, QRadialGradient,
    QLinearGradient,
)
from PyQt6.QtWidgets import QPushButton, QWidget, QLabel


# Visual constants
ICON_SIZE       = 56
COLLAPSED_W     = ICON_SIZE
COLLAPSED_H     = ICON_SIZE
PANEL_W         = 280
EXPANDED_W      = COLLAPSED_W + PANEL_W
EXPANDED_H      = ICON_SIZE
RADIUS          = 14
EDGE_MARGIN     = 16
TOP_MARGIN      = 80
GAP             = 12

# Palette — deep dark, neon accents
BG          = QColor(10,  12,  18, 235)
BG_PANEL    = QColor(14,  16,  24, 240)
EDGE        = QColor(255, 255, 255,  22)

TEXT        = QColor(232, 234, 240)
TEXT_DIM    = QColor(140, 148, 168)

# State accents (used for the pip and for non-running states; running state
# uses the per-task accent passed into the puck).
NEON_OK     = QColor( 57, 255,  20)
NEON_ERR    = QColor(255,  56, 100)
NEON_PAUS   = QColor(255, 176,  32)
NEON_AMD    = QColor(255,  72, 220)

# Per-task palette — pucks rotate through these so two parallel tasks don't
# look identical at a glance.
TASK_PALETTE = [
    QColor(  0, 217, 255),   # cyan
    QColor(167, 139, 250),   # violet
    QColor(255, 138,  76),   # orange
    QColor( 94, 234, 212),   # teal
    QColor(248, 113, 113),   # coral
    QColor(250, 204,  21),   # amber-yellow
    QColor( 96, 165, 250),   # sky-blue
    QColor(232, 121, 249),   # fuchsia
]


_BTN_QSS = """
QPushButton {
    background: rgba(255,255,255,12);
    color: #d6dae4;
    border: 1px solid rgba(255,255,255,28);
    border-radius: 6px;
    padding: 3px 9px;
    font-size: 11px;
    font-weight: 500;
}
QPushButton:hover  { background: rgba(255,255,255,28); }
QPushButton:pressed{ background: rgba(255,255,255,44); }
QPushButton[role="danger"]  { color: #ff7090; border-color: rgba(255,90,130,90); }
QPushButton[role="primary"] { color: #4ce0ff; border-color: rgba(0,217,255,100); }
QPushButton[role="amending"]{ color: #ff8eea; border-color: rgba(255,72,220,120); }
"""


class DockedTaskPuck(QWidget):
    pause_clicked   = pyqtSignal()
    resume_clicked  = pyqtSignal()
    cancel_clicked  = pyqtSignal()
    amend_toggled   = pyqtSignal(bool)
    dismiss_clicked = pyqtSignal()
    auto_dismiss    = pyqtSignal()             # done puck was hovered + then left

    def __init__(self, title: str, accent: QColor):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._title = (title or "task").strip()
        self._status = "starting…"
        self._state = "running"
        self._is_amending = False
        self._expanded = False
        self._was_hovered_after_done = False        # for auto-dismiss
        self._t0 = time.time()
        self._accent = accent

        self.setStyleSheet(_BTN_QSS)
        self.resize(COLLAPSED_W, COLLAPSED_H)

        self._build_panel_chrome()
        self._set_expanded(False, animate=False)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self.update)
        self._tick.start(50)              # 20fps glow animation

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_status(self, msg: str):
        self._status = (msg or "").strip()
        n = 200 if self._expanded else 60
        self._status_label.setText(self._truncate(self._status, n))
        self.update()

    def set_state(self, state: str):
        prev = self._state
        self._state = state
        if state in ("done", "error", "cancelled") and prev not in ("done", "error", "cancelled"):
            self._was_hovered_after_done = False
        self._refresh_buttons()
        self.update()

    def set_amending(self, on: bool):
        self._is_amending = on
        self._amend_btn.setText("send" if on else "amend")
        self._amend_btn.setProperty("role", "amending" if on else "primary")
        self._amend_btn.style().unpolish(self._amend_btn)
        self._amend_btn.style().polish(self._amend_btn)
        if on and not self._expanded:
            self._set_expanded(True)
        self.update()

    # ── Hover (Qt enterEvent / leaveEvent below) ──────────────────────────────

    def enterEvent(self, e):
        if self._state in ("done", "error", "cancelled"):
            self._was_hovered_after_done = True
        self._set_expanded(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self._is_amending:
            super().leaveEvent(e); return
        self._set_expanded(False)
        # Auto-dismiss "done" pucks the user has already glanced at.
        if (self._state in ("done", "error", "cancelled")
                and self._was_hovered_after_done):
            QTimer.singleShot(120, self.auto_dismiss.emit)
        super().leaveEvent(e)

    # ── Layout ─────────────────────────────────────────────────────────────────

    def _build_panel_chrome(self):
        self._title_label = QLabel(self._truncate(self._title, 36), self)
        f = QFont(); f.setPointSize(10); f.setBold(True)
        self._title_label.setFont(f)
        self._title_label.setStyleSheet("color: rgba(232,234,240,255); background: transparent;")

        self._status_label = QLabel(self._truncate(self._status, 60), self)
        sf = QFont(); sf.setPointSize(9)
        self._status_label.setFont(sf)
        self._status_label.setStyleSheet("color: rgba(140,148,168,255); background: transparent;")

        self._pause_btn  = QPushButton("pause",  self); self._pause_btn.clicked.connect(self.pause_clicked.emit)
        self._resume_btn = QPushButton("resume", self); self._resume_btn.clicked.connect(self.resume_clicked.emit)
        self._cancel_btn = QPushButton("cancel", self); self._cancel_btn.clicked.connect(self.cancel_clicked.emit)
        self._cancel_btn.setProperty("role", "danger")
        self._amend_btn  = QPushButton("amend",  self); self._amend_btn.clicked.connect(self._on_amend)
        self._amend_btn.setProperty("role", "primary")
        self._dismiss_btn= QPushButton("dismiss",self); self._dismiss_btn.clicked.connect(self.dismiss_clicked.emit)

        self._chrome = [
            self._title_label, self._status_label,
            self._pause_btn, self._resume_btn, self._cancel_btn,
            self._amend_btn, self._dismiss_btn,
        ]

    def _layout_expanded(self):
        panel_x = 12
        panel_w = PANEL_W - 16
        self._title_label.setGeometry(panel_x, 6, panel_w, 16)
        self._status_label.setGeometry(panel_x, 22, panel_w, 14)
        bw, bh = 60, 22
        bgap = 6
        y = ICON_SIZE - bh - 6
        x = panel_x
        # Buttons by state — pause/cancel only while running, paused gets
        # resume; once the task is over only amend + dismiss remain.
        if self._state == "running":
            order = [self._pause_btn, self._cancel_btn, self._amend_btn]
        elif self._state == "paused":
            order = [self._resume_btn, self._cancel_btn, self._amend_btn]
        else:
            order = [self._amend_btn, self._dismiss_btn]
        for btn in self._chrome[2:]:
            btn.hide()
        for btn in order:
            btn.setGeometry(x, y, bw, bh)
            btn.show()
            x += bw + bgap

    def _refresh_buttons(self):
        if self._expanded:
            self._layout_expanded()

    def _set_expanded(self, on: bool, animate: bool = True):
        if on == self._expanded:
            return
        self._expanded = on
        right_x = self.x() + self.width()
        new_w = EXPANDED_W if on else COLLAPSED_W
        new_x = right_x - new_w
        self.setGeometry(new_x, self.y(), new_w, ICON_SIZE)
        for w in self._chrome:
            w.setVisible(on)
        if on:
            self._title_label.setText(self._truncate(self._title, 36))
            self._status_label.setText(self._truncate(self._status, 200))
            self._layout_expanded()
        self.update()

    def _on_amend(self):
        self.amend_toggled.emit(not self._is_amending)

    # ── Paint ──────────────────────────────────────────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._expanded:
            panel_rect = QRectF(0, 0, PANEL_W, ICON_SIZE).adjusted(0.5, 0.5, -0.5, -0.5)
            panel_path = QPainterPath()
            panel_path.addRoundedRect(panel_rect, RADIUS, RADIUS)
            p.fillPath(panel_path, BG_PANEL)
            p.setPen(QPen(EDGE, 1))
            p.drawPath(panel_path)

        icon_x = self.width() - ICON_SIZE
        icon_rect = QRectF(icon_x, 0, ICON_SIZE, ICON_SIZE).adjusted(0.5, 0.5, -0.5, -0.5)
        icon_path = QPainterPath()
        icon_path.addRoundedRect(icon_rect, RADIUS, RADIUS)
        p.fillPath(icon_path, BG)
        p.setPen(QPen(EDGE, 1))
        p.drawPath(icon_path)

        cursor_color = self._cursor_accent()
        self._paint_glow(p, icon_x + ICON_SIZE / 2, ICON_SIZE / 2, cursor_color)
        self._paint_cursor(p, icon_x + ICON_SIZE / 2, ICON_SIZE / 2, cursor_color)

        # Progress / state pip — distinct rendering per state for fast glanceability
        self._paint_state_pip(p, icon_x, 0)

    def _cursor_accent(self) -> QColor:
        if self._is_amending: return NEON_AMD
        if self._state == "paused":    return NEON_PAUS
        if self._state == "done":      return NEON_OK
        if self._state in ("error", "cancelled"): return NEON_ERR
        return self._accent           # running → per-task color

    def _paint_glow(self, p: QPainter, cx: float, cy: float, color: QColor):
        elapsed = time.time() - self._t0
        if self._state == "running" and not self._is_amending:
            pulse = 0.55 + 0.25 * math.sin(elapsed * 2.4)
        elif self._is_amending:
            pulse = 0.7 + 0.3 * math.sin(elapsed * 5.0)
        elif self._state == "done":
            pulse = 0.6
        else:
            pulse = 0.45
        radius = 22
        grad = QRadialGradient(QPointF(cx, cy), radius)
        c0 = QColor(color); c0.setAlpha(int(140 * pulse))
        c1 = QColor(color); c1.setAlpha(0)
        grad.setColorAt(0.0, c0)
        grad.setColorAt(1.0, c1)
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), radius, radius)

    def _paint_cursor(self, p: QPainter, cx: float, cy: float, color: QColor):
        # Sleek modern cursor — slim, slightly tilted, soft curves on the
        # heel and tail, gradient body for depth, glassy highlight on the
        # leading edge.
        path = QPainterPath()
        path.moveTo(0.0,  0.0)                 # tip
        path.cubicTo(0.0, 1.6, 0.4, 2.0, 0.6, 2.5)
        path.lineTo(0.6, 20.5)                 # left side (slightly inset)
        path.cubicTo(0.6, 22.4, 2.0, 22.8, 3.2, 21.6)
        path.lineTo(6.6, 17.4)                 # heel inward curve
        path.cubicTo(7.0, 17.0, 7.6, 17.0, 7.9, 17.7)
        path.lineTo(11.0, 25.7)                # tail down-right
        path.cubicTo(11.3, 26.5, 12.1, 26.8, 12.9, 26.4)
        path.lineTo(13.6, 26.1)
        path.cubicTo(14.4, 25.7, 14.6, 24.8, 14.2, 24.0)
        path.lineTo(11.1, 16.0)
        path.lineTo(15.2, 15.1)                # right heel tip
        path.cubicTo(16.4, 14.8, 16.6, 13.6, 15.6, 12.8)
        path.lineTo(0.6, 0.0)
        path.closeSubpath()

        p.save()
        # Center: cursor's bbox is roughly 16x26 — translate so center is at (cx, cy)
        p.translate(cx - 8.0, cy - 13.0)

        # Body gradient: bright neon at top → slightly darker at bottom
        grad = QLinearGradient(0, 0, 0, 26)
        top = QColor(color).lighter(135)
        bot = QColor(color)
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bot)
        p.setBrush(QBrush(grad))

        # Outer stroke — same hue but lighter, thin
        outer = QColor(color).lighter(180); outer.setAlpha(220)
        p.setPen(QPen(outer, 1.0))
        p.drawPath(path)

        # Glassy highlight along the left edge — suggests a light source.
        hi = QPainterPath()
        hi.moveTo(1.4, 1.6)
        hi.lineTo(1.4, 16.0)
        hi.lineTo(2.6, 17.0)
        hi.lineTo(2.6, 2.4)
        hi.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 80))
        p.drawPath(hi)

        p.restore()

    def _paint_state_pip(self, p: QPainter, icon_x: float, _y: float):
        """Pip in the bottom-right corner. Distinct rendering per state so the
        user can read progress at a glance without hovering."""
        cx = icon_x + ICON_SIZE - 11
        cy = ICON_SIZE - 11
        elapsed = time.time() - self._t0

        if self._state == "running":
            # Spinning arc — clearly "in progress"
            p.setBrush(QColor(0, 0, 0, 140)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx, cy), 6, 6)
            p.setBrush(QColor(255, 255, 255, 35)); p.drawEllipse(QPointF(cx, cy), 5.2, 5.2)
            ang = (elapsed * 360 * 1.0) % 360
            pen = QPen(self._accent, 1.8)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
            arc_rect = QRectF(cx - 5.2, cy - 5.2, 10.4, 10.4)
            p.drawArc(arc_rect, int(-ang * 16), int(120 * 16))
        elif self._state == "paused":
            p.setBrush(QColor(0, 0, 0, 140)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx, cy), 6, 6)
            # Two thin vertical bars — pause glyph
            p.setBrush(NEON_PAUS)
            p.drawRoundedRect(QRectF(cx - 3.4, cy - 3.6, 1.8, 7.2), 0.9, 0.9)
            p.drawRoundedRect(QRectF(cx + 1.6, cy - 3.6, 1.8, 7.2), 0.9, 0.9)
        elif self._state == "done":
            # Solid bright dot with a subtle outer halo — "complete"
            halo = QRadialGradient(QPointF(cx, cy), 9)
            c0 = QColor(NEON_OK); c0.setAlpha(110)
            c1 = QColor(NEON_OK); c1.setAlpha(0)
            halo.setColorAt(0, c0); halo.setColorAt(1, c1)
            p.setBrush(QBrush(halo)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx, cy), 9, 9)
            p.setBrush(QColor(0, 0, 0, 160))
            p.drawEllipse(QPointF(cx, cy), 6, 6)
            p.setBrush(NEON_OK)
            p.drawEllipse(QPointF(cx, cy), 4.0, 4.0)
            # Tiny check tick
            pen = QPen(QColor(10, 14, 18, 220), 1.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(cx - 2.2, cy + 0.1),
                       QPointF(cx - 0.6, cy + 1.7))
            p.drawLine(QPointF(cx - 0.6, cy + 1.7),
                       QPointF(cx + 2.4, cy - 1.6))
        elif self._state in ("error", "cancelled"):
            p.setBrush(QColor(0, 0, 0, 160)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx, cy), 6, 6)
            p.setBrush(NEON_ERR)
            p.drawEllipse(QPointF(cx, cy), 4.0, 4.0)
            pen = QPen(QColor(10, 14, 18, 220), 1.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(cx - 1.8, cy - 1.8), QPointF(cx + 1.8, cy + 1.8))
            p.drawLine(QPointF(cx - 1.8, cy + 1.8), QPointF(cx + 1.8, cy - 1.8))

    # ── Utilities ──────────────────────────────────────────────────────────────

    @staticmethod
    def _truncate(text: str, n: int) -> str:
        text = (text or "").strip()
        if len(text) <= n: return text
        return text[: n - 1] + "…"
