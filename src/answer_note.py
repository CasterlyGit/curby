"""Floating answer note — a small draggable panel showing the latest
quick-ask reply as readable text.

Built on the shared `CollapsibleFloater` base (same pattern as
claude-meter). Always interactive — drag-to-move, click the minimize
icon to collapse, click the dot to expand. No click-through dance.

When collapsed, the dot pulses in the current voice-state color so the
user always knows curby is alive and what it's doing.
"""
import math
import time

from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer
from PyQt6.QtGui import QPainter, QColor, QPen, QPainterPath, QFont, QFontMetrics
from PyQt6.QtWidgets import QApplication

from src.collapsible_floater import CollapsibleFloater


# ── Visual constants ─────────────────────────────────────────────────────────

PANEL_W              = 340
PANEL_MIN_H          = 80
PANEL_MAX_H          = 260
PANEL_PADDING        = 16
PANEL_RADIUS         = 14

DOT_SIZE             = 22
EDGE_MARGIN          = 18

COLLAPSE_BTN_SIZE    = 20
COLLAPSE_BTN_MARGIN  = 8

# Palette — soft electric blue accent on a deep matte background.
BG                   = QColor(14,  16,  26, 246)
BG_BORDER            = QColor(96, 165, 250,  80)
ACCENT               = QColor(96, 165, 250, 255)
TEXT                 = QColor(232, 234, 245)
TEXT_DIM             = QColor(140, 148, 168)
LABEL                = QColor(96, 165, 250, 200)


# State → (dot accent, pulse-Hz, base-alpha, alpha-range)
_DOT_STATE = {
    "idle":      (ACCENT,                 1.8, 170, 50),
    "listening": (QColor(236,  72, 153),  4.5, 220, 35),
    "thinking":  (QColor(167, 139, 250),  5.5, 200, 55),
    "speaking":  (QColor( 52, 211, 153),  4.0, 220, 35),
    "error":     (QColor(248, 113, 113),  3.5, 200, 55),
}


class AnswerNote(CollapsibleFloater):
    EXPANDED_SIZE = (PANEL_W, PANEL_MIN_H)
    COLLAPSED_SIZE = DOT_SIZE

    def __init__(self):
        super().__init__()
        self._text = ""
        self._latency_ms: int | None = None
        self._voice_state = "idle"
        self._t0 = time.time()

        self._font = QFont()
        self._font.setPointSize(13)
        self._font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        self._label_font = QFont()
        self._label_font.setPointSize(9)
        self._label_font.setBold(True)
        self._label_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)

        # Pulse timer for the collapsed dot. Only triggers repaints while
        # collapsed (saves CPU when expanded).
        self._pulse = QTimer(self)
        self._pulse.timeout.connect(self._on_pulse_tick)
        self._pulse.start(50)

        self._position_top_right()

    # ── Public API ─────────────────────────────────────────────────────────

    def set_reply(self, text: str, latency_ms: int | None = None) -> None:
        self._text = (text or "").strip()
        self._latency_ms = latency_ms
        if self.is_collapsed:
            self.set_collapsed(False)
        self._resize_expanded()
        self.update()
        if not self.isVisible():
            self.show()
            self.raise_()

    def show_initial(self) -> None:
        self._text = ""
        self._resize_expanded()
        self.show()
        self.raise_()

    def set_voice_state(self, state: str) -> None:
        self._voice_state = state if state in _DOT_STATE else "idle"
        if self.is_collapsed:
            self.update()

    # ── Layout ─────────────────────────────────────────────────────────────

    def _position_top_right(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.right() - PANEL_W - EDGE_MARGIN
        y = geo.top() + EDGE_MARGIN
        self.move(x, y)

    def compute_expanded_size(self) -> tuple[int, int]:
        fm = QFontMetrics(self._font)
        usable_w = PANEL_W - 2 * PANEL_PADDING
        if not self._text:
            text_h = fm.height()
        else:
            rect = fm.boundingRect(
                0, 0, usable_w, 10_000,
                Qt.TextFlag.TextWordWrap, self._text,
            )
            text_h = rect.height()
        label_h = QFontMetrics(self._label_font).height() + 8
        h = max(PANEL_MIN_H, min(PANEL_MAX_H, text_h + label_h + 2 * PANEL_PADDING))
        return (PANEL_W, int(h))

    # ── Collapse hot-zone ──────────────────────────────────────────────────

    def _collapse_btn_rect(self) -> QRectF:
        return QRectF(
            self.width() - COLLAPSE_BTN_MARGIN - COLLAPSE_BTN_SIZE,
            COLLAPSE_BTN_MARGIN,
            COLLAPSE_BTN_SIZE,
            COLLAPSE_BTN_SIZE,
        )

    def collapse_hit(self, local_pt) -> bool:
        return self._collapse_btn_rect().contains(local_pt.x(), local_pt.y())

    # ── Tick ───────────────────────────────────────────────────────────────

    def _on_pulse_tick(self) -> None:
        if self.is_collapsed:
            self.update()

    # ── Paint ──────────────────────────────────────────────────────────────

    def paint_expanded(self, p: QPainter) -> None:
        rect = QRectF(0, 0, self.width(), self.height()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, PANEL_RADIUS, PANEL_RADIUS)
        p.fillPath(path, BG)
        p.setPen(QPen(BG_BORDER, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # Accent stripe on the left.
        stripe = QRectF(0, PANEL_PADDING, 3, self.height() - 2 * PANEL_PADDING)
        sp = QPainterPath()
        sp.addRoundedRect(stripe, 1.5, 1.5)
        p.fillPath(sp, ACCENT)

        # Header.
        p.setFont(self._label_font)
        p.setPen(QPen(LABEL))
        label_text = "CURBY"
        if self._latency_ms is not None:
            label_text += f"   ·   {self._latency_ms} ms"
        header_w = int(self.width() - 2 * PANEL_PADDING - COLLAPSE_BTN_SIZE - 8)
        p.drawText(
            int(PANEL_PADDING), int(PANEL_PADDING),
            header_w, 20,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
            label_text,
        )

        # Body text.
        p.setFont(self._font)
        text_color = TEXT if self._text else TEXT_DIM
        p.setPen(QPen(text_color))
        body = self._text or "Tap Ctrl+Space to ask Claude anything."
        body_y = PANEL_PADDING + 22
        p.drawText(
            int(PANEL_PADDING), int(body_y),
            int(self.width() - 2 * PANEL_PADDING),
            int(self.height() - body_y - PANEL_PADDING),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
            body,
        )

        # Minimize "—" button, top-right.
        btn = self._collapse_btn_rect()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 35))
        p.drawEllipse(btn)
        p.setPen(QPen(QColor(232, 234, 245, 230), 1.8))
        inset = 5
        mid_y = btn.center().y()
        p.drawLine(
            int(btn.left() + inset), int(mid_y),
            int(btn.right() - inset), int(mid_y),
        )

    def paint_collapsed(self, p: QPainter) -> None:
        """Pulsing dot — alive even when minimized; color + speed reflect state."""
        accent, speed, base_a, range_a = _DOT_STATE.get(self._voice_state, _DOT_STATE["idle"])
        elapsed = time.time() - self._t0
        breathe = (math.sin(elapsed * speed) + 1) * 0.5  # 0..1

        cx = self.width() / 2
        cy = self.height() / 2

        # Outer halo
        glow = QColor(accent); glow.setAlpha(int(40 + 50 * breathe))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(cx, cy), self.width() / 2 + 2, self.height() / 2 + 2)

        # Inner dot
        fill = QColor(accent); fill.setAlpha(int(base_a + range_a * breathe))
        p.setBrush(fill)
        p.drawEllipse(QPointF(cx, cy), self.width() / 2 - 3, self.height() / 2 - 3)

        # Rim
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 80), 1.0))
        p.drawEllipse(QPointF(cx, cy), self.width() / 2 - 3, self.height() / 2 - 3)
