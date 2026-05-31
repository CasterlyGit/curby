"""Floating answer note — a clean dark panel with purple accent.

Visual language tracks `docs/index.html`: deep card background, subtle
border, purple accent + glow, soft drop shadow. No cloud puffs. When
collapsed, shrinks to a small purple dot that pulses in the current
voice-state color so the user always knows curby is alive.

Built on the shared `CollapsibleFloater` base (drag + click model).
"""
import json
import math
import os
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QPainterPath, QFont, QFontMetrics,
    QLinearGradient, QRadialGradient,
)
from PyQt6.QtWidgets import QApplication

from src.collapsible_floater import CollapsibleFloater


_STATE_PATH = Path(os.path.expanduser("~/.curby/state.json"))


# ── Palette (matches docs/index.html) ────────────────────────────────────────

BG_CARD              = QColor( 26,  29,  39, 244)    # --bg-card 1a1d27
BG_ELEV              = QColor( 20,  22,  29, 244)    # --bg-elev 14161d
BORDER               = QColor( 35,  38,  49, 255)    # #232631
BORDER_GLOW          = QColor(176, 142, 255,  80)    # accent halo
ACCENT               = QColor(176, 142, 255, 255)    # --accent b08eff
ACCENT_DIM           = QColor(176, 142, 255, 160)
ACCENT_SOFT          = QColor(176, 142, 255,  30)
TEXT                 = QColor(241, 243, 245)         # --text f1f3f5
TEXT_DIM             = QColor(122, 129, 144)         # --text-dim 7a8190

# Secondary state colors (also from docs/index.html palette).
CYAN                 = QColor(  0, 228, 255)         # --cyan
MINT                 = QColor( 46, 229, 157)         # --mint
ROSE                 = QColor(255,  91, 138)         # --rose
AMBER                = QColor(255, 181,  71)         # --amber
ROSE_RED             = QColor(248, 113, 113)


# ── Geometry ─────────────────────────────────────────────────────────────────

PANEL_W              = 340
PANEL_MIN_H          = 92
PANEL_MAX_H          = 280
PANEL_PADDING_X      = 18
PANEL_PADDING_TOP    = 16
PANEL_PADDING_BOT    = 16
PANEL_RADIUS         = 14         # matches .desktop-wrap radius

COLLAPSED_SIZE       = 42         # small dot — matches claude-meter
EDGE_MARGIN          = 18

COLLAPSE_BTN_SIZE    = 18
COLLAPSE_BTN_MARGIN  = 10

ACCENT_STRIPE_W      = 3


# State → (dot accent, pulse-Hz, base-alpha, alpha-range)
_DOT_STATE = {
    "idle":      (ACCENT,    1.6, 170, 50),
    "listening": (ROSE,      4.0, 220, 35),
    "thinking":  (ACCENT,    5.0, 200, 55),
    "speaking":  (MINT,      3.6, 220, 35),
    "error":     (ROSE_RED,  3.2, 200, 55),
}


class AnswerNote(CollapsibleFloater):
    EXPANDED_SIZE = (PANEL_W, PANEL_MIN_H)
    COLLAPSED_SIZE = COLLAPSED_SIZE

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
        self._label_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.4)

        # Pulse timer for the collapsed dot. Only repaints while collapsed.
        self._pulse = QTimer(self)
        self._pulse.timeout.connect(self._on_pulse_tick)
        self._pulse.start(50)

        if not self._restore_saved_pos():
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

    def _restore_saved_pos(self) -> bool:
        """Move to the last user-dragged position. Returns False if no
        saved pos or it would land off any connected screen (e.g. the
        external monitor it was saved on is gone)."""
        try:
            data = json.loads(_STATE_PATH.read_text())
            x, y = data["answer_note_pos"]
            x, y = int(x), int(y)
        except Exception:
            return False
        # Validate the point lies within *some* connected screen's available
        # geometry — leaves a generous tolerance so the panel's full body
        # can still be (partially) on-screen.
        for screen in QApplication.screens():
            geo = screen.availableGeometry()
            if (geo.left() - 50 <= x <= geo.right() - 100
                    and geo.top() - 10 <= y <= geo.bottom() - 60):
                self.move(x, y)
                return True
        return False

    def _save_pos(self) -> None:
        try:
            _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            try:
                data = json.loads(_STATE_PATH.read_text())
                if not isinstance(data, dict):
                    data = {}
            except Exception:
                data = {}
            data["answer_note_pos"] = [self.x(), self.y()]
            _STATE_PATH.write_text(json.dumps(data, indent=2))
        except Exception as e:
            print(f"[answer_note] save pos failed: {e}", flush=True)

    def mouseReleaseEvent(self, event):  # noqa: N802
        was_drag = bool(getattr(self, "_drag_moved", False))
        super().mouseReleaseEvent(event)
        if was_drag:
            self._save_pos()

    def compute_expanded_size(self) -> tuple[int, int]:
        fm = QFontMetrics(self._font)
        usable_w = PANEL_W - 2 * PANEL_PADDING_X - ACCENT_STRIPE_W - 8
        if not self._text:
            text_h = fm.height()
        else:
            rect = fm.boundingRect(
                0, 0, usable_w, 10_000,
                Qt.TextFlag.TextWordWrap, self._text,
            )
            text_h = rect.height()
        label_h = QFontMetrics(self._label_font).height() + 6
        h = max(
            PANEL_MIN_H,
            min(PANEL_MAX_H, text_h + label_h + PANEL_PADDING_TOP + PANEL_PADDING_BOT),
        )
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
        w, h = self.width(), self.height()
        rect = QRectF(0, 0, w, h).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, PANEL_RADIUS, PANEL_RADIUS)

        # Outer purple glow — soft, no ringing edge.
        glow = QRadialGradient(w * 0.5, h * 0.5, max(w, h) * 0.8)
        g_in = QColor(BORDER_GLOW); g_in.setAlpha(50)
        g_out = QColor(BORDER_GLOW); g_out.setAlpha(0)
        glow.setColorAt(0.0, g_in)
        glow.setColorAt(1.0, g_out)
        p.setBrush(glow)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect.adjusted(-6, -6, 6, 6), PANEL_RADIUS + 6, PANEL_RADIUS + 6)

        # Body — vertical gradient from elev to card so it has depth.
        body = QLinearGradient(0, 0, 0, h)
        body.setColorAt(0.0, BG_CARD)
        body.setColorAt(1.0, BG_ELEV)
        p.setBrush(body)
        p.setPen(QPen(BORDER, 1.0))
        p.drawPath(path)

        # Purple accent stripe on the left edge.
        stripe = QRectF(
            PANEL_PADDING_X - ACCENT_STRIPE_W - 6,
            PANEL_PADDING_TOP + 2,
            ACCENT_STRIPE_W,
            h - PANEL_PADDING_TOP - PANEL_PADDING_BOT - 4,
        )
        sp = QPainterPath()
        sp.addRoundedRect(stripe, 1.5, 1.5)
        p.fillPath(sp, ACCENT)

        # Header label.
        p.setFont(self._label_font)
        p.setPen(QPen(ACCENT_DIM))
        label_text = "CURBY"
        if self._latency_ms is not None:
            label_text += f"   ·   {self._latency_ms} ms"
        header_w = int(w - 2 * PANEL_PADDING_X - COLLAPSE_BTN_SIZE - 8)
        p.drawText(
            int(PANEL_PADDING_X), int(PANEL_PADDING_TOP),
            header_w, 18,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
            label_text,
        )

        # Body text.
        p.setFont(self._font)
        text_color = TEXT if self._text else TEXT_DIM
        p.setPen(QPen(text_color))
        body_msg = self._text or "Tap Ctrl+Space to ask Claude anything."
        body_y = PANEL_PADDING_TOP + 20
        p.drawText(
            int(PANEL_PADDING_X), int(body_y),
            int(w - 2 * PANEL_PADDING_X),
            int(h - body_y - PANEL_PADDING_BOT),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
            body_msg,
        )

        # Minimize chevron button, top-right.
        btn = self._collapse_btn_rect()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ACCENT_SOFT)
        p.drawRoundedRect(btn, 5, 5)
        # Down-chevron glyph "˅" — feels softer than a minus dash and
        # matches the small-icon vocabulary used in the HTML repo cards.
        p.setPen(QPen(ACCENT, 1.6))
        cx, cy = btn.center().x(), btn.center().y()
        size = 4
        p.drawLine(int(cx - size), int(cy - 1), int(cx), int(cy + size - 1))
        p.drawLine(int(cx), int(cy + size - 1), int(cx + size), int(cy - 1))

    def paint_collapsed(self, p: QPainter) -> None:
        """Small purple dot — clean, pulses with voice state."""
        accent, speed, base_a, range_a = _DOT_STATE.get(self._voice_state, _DOT_STATE["idle"])
        elapsed = time.time() - self._t0
        breathe = (math.sin(elapsed * speed) + 1) * 0.5  # 0..1

        cx = self.width() / 2
        cy = self.height() / 2
        # Dot fills the widget, leaving a 1.5px inset for the border
        # stroke so it doesn't get clipped to a square at the widget edge.
        r = self.width() / 2 - 1.5

        fill = QColor(accent); fill.setAlpha(int(base_a + range_a * breathe))
        p.setBrush(fill)
        p.setPen(QPen(QColor(0, 0, 0, 200), 1.2))
        p.drawEllipse(QPointF(cx, cy), r, r)
