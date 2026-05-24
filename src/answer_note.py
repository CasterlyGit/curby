"""Floating answer note — a cloud-shaped panel showing the latest
quick-ask reply as readable text.

Silhouette is a soft twilight cloud (rounded base + four overlapping
puffs on top) in curby's pink/violet palette. When collapsed, shrinks
to a tiny three-puff cloud that pulses in the current voice-state
color so the user always knows curby is alive and what it's doing.

Built on the shared `CollapsibleFloater` base (same drag + click model
as claude-meter).
"""
import math
import time

from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QPainterPath, QFont, QFontMetrics,
    QLinearGradient, QRadialGradient,
)
from PyQt6.QtWidgets import QApplication

from src.collapsible_floater import CollapsibleFloater


# ── Visual constants ─────────────────────────────────────────────────────────

PANEL_W              = 340
PANEL_MIN_H          = 110
PANEL_MAX_H          = 280
PANEL_PADDING_X      = 22
PANEL_PADDING_TOP    = 30      # extra room at the top for cloud puffs
PANEL_PADDING_BOT    = 22

PUFF_OVERHANG        = 22      # how far the topmost puff rises above the base rect

COLLAPSED_W          = 44
COLLAPSED_H          = 30
EDGE_MARGIN          = 18

COLLAPSE_BTN_SIZE    = 20
COLLAPSE_BTN_MARGIN  = 12

# Curby palette — soft twilight cloud (matches the feather's pink/violet hues).
PINK_HOT             = QColor(236,  72, 153)
PINK_SOFT            = QColor(244, 114, 182)
VIOLET               = QColor(167, 139, 250)
MINT                 = QColor( 52, 211, 153)
GOLD                 = QColor(253, 224,  71)
RED                  = QColor(248, 113, 113)

# Cloud body — deep dusky violet that fades to a brighter pink-violet at the top.
CLOUD_TOP            = QColor( 78,  52,  96, 238)
CLOUD_BOT            = QColor( 28,  20,  42, 244)
CLOUD_RIM            = QColor(244, 114, 182, 130)
ACCENT               = PINK_HOT
TEXT                 = QColor(248, 240, 252)
TEXT_DIM             = QColor(186, 168, 200)
LABEL                = QColor(244, 114, 182, 220)


# State → (puff accent, pulse-Hz, base-alpha, alpha-range)
_DOT_STATE = {
    "idle":      (PINK_SOFT, 1.6, 170, 50),
    "listening": (PINK_HOT,  4.0, 220, 35),
    "thinking":  (VIOLET,    5.0, 200, 55),
    "speaking":  (MINT,      3.6, 220, 35),
    "error":     (RED,       3.2, 200, 55),
}


def _cloud_path(w: float, h: float) -> QPainterPath:
    """Build a soft cloud silhouette filling a (w, h) box.

    Geometry: a rounded base rect on the bottom half + four overlapping
    ellipse "puffs" along the top edge. Painted with WindingFill so the
    overlaps union cleanly into a single silhouette."""
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)

    base_top    = h * 0.38
    base_bot    = h - 2
    base_left   = w * 0.03
    base_right  = w * 0.97
    base_radius = (base_bot - base_top) * 0.45
    path.addRoundedRect(
        QRectF(base_left, base_top, base_right - base_left, base_bot - base_top),
        base_radius, base_radius,
    )

    # Four puffs along the top. Heights vary so the silhouette reads as a
    # real cloud (irregular) rather than a row of equal bumps.
    puffs = [
        (w * 0.18, h * 0.40, w * 0.14, h * 0.34),  # left
        (w * 0.40, h * 0.26, w * 0.17, h * 0.44),  # tallest
        (w * 0.62, h * 0.30, w * 0.16, h * 0.40),
        (w * 0.84, h * 0.42, w * 0.14, h * 0.32),  # right
    ]
    for cx, cy, rx, ry in puffs:
        path.addEllipse(QPointF(cx, cy), rx, ry)
    return path


def _mini_cloud_path(w: float, h: float) -> QPainterPath:
    """Tiny three-puff cloud for the collapsed state."""
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    base_top    = h * 0.48
    base_bot    = h - 1
    base_left   = w * 0.08
    base_right  = w * 0.92
    base_radius = (base_bot - base_top) * 0.5
    path.addRoundedRect(
        QRectF(base_left, base_top, base_right - base_left, base_bot - base_top),
        base_radius, base_radius,
    )
    puffs = [
        (w * 0.26, h * 0.46, w * 0.20, h * 0.40),
        (w * 0.54, h * 0.34, w * 0.22, h * 0.52),
        (w * 0.78, h * 0.46, w * 0.18, h * 0.40),
    ]
    for cx, cy, rx, ry in puffs:
        path.addEllipse(QPointF(cx, cy), rx, ry)
    return path


class AnswerNote(CollapsibleFloater):
    EXPANDED_SIZE = (PANEL_W, PANEL_MIN_H)
    # Base class only supports square collapsed sizing; we override
    # set_collapsed() below to set a wide cloud rect instead.
    COLLAPSED_SIZE = COLLAPSED_H

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

        # Pulse timer for the collapsed cloud's alive-state breath. Only
        # triggers repaints while collapsed (saves CPU when expanded).
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
        usable_w = PANEL_W - 2 * PANEL_PADDING_X
        if not self._text:
            text_h = fm.height()
        else:
            rect = fm.boundingRect(
                0, 0, usable_w, 10_000,
                Qt.TextFlag.TextWordWrap, self._text,
            )
            text_h = rect.height()
        label_h = QFontMetrics(self._label_font).height() + 8
        h = max(
            PANEL_MIN_H,
            min(PANEL_MAX_H, text_h + label_h + PANEL_PADDING_TOP + PANEL_PADDING_BOT),
        )
        return (PANEL_W, int(h))

    # ── Override collapsed sizing to be a wide cloud rect ─────────────────

    def set_collapsed(self, collapsed: bool, *, animate: bool = False) -> None:
        if collapsed == self.is_collapsed:
            return
        if collapsed:
            self._collapsed = True
            self.setFixedSize(COLLAPSED_W, COLLAPSED_H)
            self.update()
            self.collapse_changed.emit(True)
        else:
            self._collapsed = False
            self._resize_expanded()
            self.update()
            self.collapse_changed.emit(False)

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
        w, h = self.width(), self.height()
        path = _cloud_path(w, h)

        # Soft outer glow — gives the cloud a halo without ringing.
        glow = QRadialGradient(w / 2, h / 2, max(w, h) / 1.6)
        g_in = QColor(CLOUD_RIM); g_in.setAlpha(70)
        g_out = QColor(CLOUD_RIM); g_out.setAlpha(0)
        glow.setColorAt(0.0, g_in)
        glow.setColorAt(1.0, g_out)
        p.setBrush(glow)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path)

        # Body fill — vertical gradient from lighter top to deep bottom.
        body = QLinearGradient(0, 0, 0, h)
        body.setColorAt(0.0, CLOUD_TOP)
        body.setColorAt(1.0, CLOUD_BOT)
        p.setBrush(body)
        p.setPen(QPen(CLOUD_RIM, 1.2))
        p.drawPath(path)

        # Pink accent stripe on the left, hugging the cloud's solid base.
        stripe_top = h * 0.45
        stripe_bot = h - PANEL_PADDING_BOT - 4
        stripe_x   = PANEL_PADDING_X - 8
        stripe_rect = QRectF(stripe_x, stripe_top, 3, stripe_bot - stripe_top)
        sp = QPainterPath()
        sp.addRoundedRect(stripe_rect, 1.5, 1.5)
        p.fillPath(sp, ACCENT)

        # Header.
        p.setFont(self._label_font)
        p.setPen(QPen(LABEL))
        label_text = "CURBY"
        if self._latency_ms is not None:
            label_text += f"   ·   {self._latency_ms} ms"
        header_y = PANEL_PADDING_TOP
        header_w = int(w - 2 * PANEL_PADDING_X - COLLAPSE_BTN_SIZE - 8)
        p.drawText(
            int(PANEL_PADDING_X), int(header_y),
            header_w, 20,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
            label_text,
        )

        # Body text.
        p.setFont(self._font)
        text_color = TEXT if self._text else TEXT_DIM
        p.setPen(QPen(text_color))
        body_msg = self._text or "Tap Ctrl+Space to ask Claude anything."
        body_y = header_y + 22
        p.drawText(
            int(PANEL_PADDING_X), int(body_y),
            int(w - 2 * PANEL_PADDING_X),
            int(h - body_y - PANEL_PADDING_BOT),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
            body_msg,
        )

        # Minimize "—" button, top-right. Sits inside the rightmost puff so
        # it visually belongs to the cloud silhouette.
        btn = self._collapse_btn_rect()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 38))
        p.drawEllipse(btn)
        p.setPen(QPen(QColor(248, 240, 252, 230), 1.8))
        inset = 5
        mid_y = btn.center().y()
        p.drawLine(
            int(btn.left() + inset), int(mid_y),
            int(btn.right() - inset), int(mid_y),
        )

    def paint_collapsed(self, p: QPainter) -> None:
        """Tiny cloud puff — alive even when minimized; color + speed
        reflect voice state."""
        accent, speed, base_a, range_a = _DOT_STATE.get(self._voice_state, _DOT_STATE["idle"])
        elapsed = time.time() - self._t0
        breathe = (math.sin(elapsed * speed) + 1) * 0.5  # 0..1

        w, h = self.width(), self.height()
        path = _mini_cloud_path(w, h)

        # Outer halo — pulses with state.
        glow = QRadialGradient(w / 2, h / 2, max(w, h))
        g_in = QColor(accent); g_in.setAlpha(int(40 + 50 * breathe))
        g_out = QColor(accent); g_out.setAlpha(0)
        glow.setColorAt(0.0, g_in)
        glow.setColorAt(1.0, g_out)
        p.setBrush(glow)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path)

        # Cloud body fill — state accent at modulated alpha.
        fill = QColor(accent); fill.setAlpha(int(base_a + range_a * breathe))
        p.setBrush(fill)
        p.setPen(QPen(QColor(255, 255, 255, 110), 1.0))
        p.drawPath(path)
