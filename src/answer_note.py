"""Floating answer note — a small draggable panel that shows the latest
quick-ask reply as readable text.

Lives top-right of the primary screen by default; the user can drag it
anywhere and click to toggle between a full panel and a tiny dot. The
position survives drags but resets to top-right on each curby start
(intentional — keeps the screen tidy).

Visual identity is a soft blue rounded panel (vs claude-meter's green
ring), translucent dark background, single block of reply text. When
collapsed, just a small blue dot.

Pattern mirrors claude-meter/src/claude_meter/window.py:
- frameless top-level window, stays on top, click-through-able when idle
- mousePress→Move→Release with a small px threshold to distinguish
  click (toggle collapse) from drag (move the widget)
"""
from PyQt6.QtCore import Qt, QPoint, QPointF, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QPainterPath, QFont, QFontMetrics
from PyQt6.QtWidgets import QWidget, QApplication


# ── Visual constants ─────────────────────────────────────────────────────────

PANEL_W              = 340
PANEL_MIN_H          = 80
PANEL_MAX_H          = 260
PANEL_PADDING        = 16
PANEL_RADIUS         = 14

DOT_SIZE             = 22
EDGE_MARGIN          = 18
DRAG_THRESHOLD_PX    = 4
# Collapse icon in the top-right of the panel. Click inside this rect
# collapses the panel; clicks anywhere else are passthrough / drag.
COLLAPSE_BTN_SIZE    = 18
COLLAPSE_BTN_MARGIN  = 10

# Palette — soft electric blue accent on a deep matte background.
BG                   = QColor(14,  16,  26, 246)
BG_BORDER            = QColor(96, 165, 250,  80)   # blue-400 @ low alpha
ACCENT               = QColor(96, 165, 250, 255)   # blue-400
ACCENT_DIM           = QColor(96, 165, 250, 140)
TEXT                 = QColor(232, 234, 245)
TEXT_DIM             = QColor(140, 148, 168)
LABEL                = QColor(96, 165, 250, 200)


class AnswerNote(QWidget):
    """Floating panel showing the latest quick-ask reply."""

    # Emitted whenever the panel's collapsed state changes. Hosts can wire
    # this to hide/show the companion feather so the whole curby cluster
    # collapses as one unit.
    collapse_changed = pyqtSignal(bool)   # True if now collapsed

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        # Click-through BY DEFAULT — flipped to interactive only while the
        # cursor is hovering the panel (driven by app.py via check_hover).
        # This keeps the panel from eating clicks across the whole top-right
        # of the screen while still allowing drag-to-move and click-to-collapse.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._hover_interactive = False

        self._text = ""
        self._latency_ms: int | None = None
        self._collapsed = False
        self._voice_state = "idle"
        # Drag state — None means not dragging.
        self._drag_origin: QPoint | None = None
        self._drag_moved = False

        # Pulse timer for the collapsed dot. ~20 fps is plenty for a soft
        # breathing animation; cheap on CPU.
        import time as _t
        self._t0 = _t.time()
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._on_pulse_tick)
        self._pulse_timer.start(50)

        # The text font drives height computation. Use the system UI font at
        # a comfortable readable size, not Qt's tiny default.
        self._font = QFont()
        self._font.setPointSize(13)
        self._font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        self._label_font = QFont()
        self._label_font.setPointSize(9)
        self._label_font.setBold(True)
        self._label_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)

        self.resize(PANEL_W, PANEL_MIN_H)
        self._position_top_right()

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_reply(self, text: str, latency_ms: int | None = None) -> None:
        """Replace the visible reply. Expands the panel if it was collapsed
        so the user sees the new answer arrive."""
        self._text = (text or "").strip()
        self._latency_ms = latency_ms
        if self._collapsed:
            self._set_collapsed(False, keep_position=True)
        self._resize_to_fit()
        self.update()
        if not self.isVisible():
            self.show()
            self.raise_()

    def show_initial(self) -> None:
        """Called once at app start so the panel is visible from the get-go."""
        self._text = ""
        self._resize_to_fit()
        self.show()
        self.raise_()

    def set_voice_state(self, state: str) -> None:
        """Track curby's current state so the collapsed dot can reflect it
        (faster pulse + brighter color while thinking/speaking)."""
        self._voice_state = state
        # Only repaint while collapsed — the expanded panel doesn't render
        # state visually.
        if self._collapsed:
            self.update()

    def _on_pulse_tick(self) -> None:
        # Only repaint while collapsed — saves CPU when the panel is expanded.
        if self._collapsed:
            self.update()

    # ── Layout ─────────────────────────────────────────────────────────────────

    def _position_top_right(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.right() - PANEL_W - EDGE_MARGIN
        y = geo.top() + EDGE_MARGIN
        self.move(x, y)

    def _resize_to_fit(self) -> None:
        if self._collapsed:
            self.setFixedSize(DOT_SIZE, DOT_SIZE)
            return
        # Compute the height needed to display the current text, clamped
        # between PANEL_MIN_H and PANEL_MAX_H.
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
        self.setFixedSize(PANEL_W, h)

    def _set_collapsed(self, collapsed: bool, *, keep_position: bool = False) -> None:
        if collapsed == self._collapsed:
            return
        was_topleft = self.pos()
        self._collapsed = collapsed
        if collapsed:
            self.setFixedSize(DOT_SIZE, DOT_SIZE)
        else:
            self._resize_to_fit()
        if not keep_position:
            self.move(was_topleft)
        self.update()
        self.collapse_changed.emit(collapsed)

    def _collapse_btn_rect(self) -> QRectF:
        """Hit-rect for the top-right collapse icon (panel mode only)."""
        return QRectF(
            self.width() - COLLAPSE_BTN_MARGIN - COLLAPSE_BTN_SIZE,
            COLLAPSE_BTN_MARGIN,
            COLLAPSE_BTN_SIZE,
            COLLAPSE_BTN_SIZE,
        )

    # ── Hover-driven click-through toggle ────────────────────────────────────

    def check_hover(self, cursor_x: int, cursor_y: int) -> None:
        """Called from CurbyApp's cursor tracker. Flips WA_TransparentForMouseEvents
        based on whether the cursor is inside this widget's current geometry.
        Click-through everywhere else; interactive only while hovering."""
        inside = self.geometry().contains(cursor_x, cursor_y)
        if inside == self._hover_interactive:
            return
        self._hover_interactive = inside
        # Toggling WA_TransparentForMouseEvents lets us be click-through
        # most of the time but accept drag/click while hovered.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not inside)

    # ── Mouse: drag-to-move + click-to-toggle ─────────────────────────────────

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        # Collapsed dot: click anywhere on the dot expands it back.
        if self._collapsed:
            self._set_collapsed(False, keep_position=True)
            event.accept()
            return
        # Expanded panel: only the X icon collapses; everything else is drag.
        if self._collapse_btn_rect().contains(pos):
            self._set_collapsed(True, keep_position=True)
            event.accept()
            return
        self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        self._drag_moved = False
        event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_origin is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        new_global = event.globalPosition().toPoint()
        new_pos = new_global - self._drag_origin
        if not self._drag_moved:
            delta = (new_pos - self.pos()).manhattanLength()
            if delta > DRAG_THRESHOLD_PX:
                self._drag_moved = True
        if self._drag_moved:
            self.move(new_pos)
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._drag_origin is None:
            return
        self._drag_origin = None
        self._drag_moved = False
        event.accept()

    # ── Paint ──────────────────────────────────────────────────────────────────

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._collapsed:
            self._paint_dot(p)
        else:
            self._paint_panel(p)

    def _paint_dot(self, p: QPainter) -> None:
        """Collapsed-dot rendering. ALWAYS pulses gently so the user knows
        curby is alive even when minimized. Pulse speed + accent shift
        based on curby's current voice state, mirroring the feather's
        state language at miniature scale."""
        import math, time as _t
        elapsed = _t.time() - self._t0

        # Pulse rate per state — calm idle, faster while thinking/speaking
        # so the dot tells you what's happening even with the panel closed.
        if self._voice_state == "thinking":
            speed, base_a, range_a = 5.5, 200, 55
            accent = QColor(167, 139, 250)   # violet
        elif self._voice_state == "speaking":
            speed, base_a, range_a = 4.0, 220, 35
            accent = QColor( 52, 211, 153)   # mint
        elif self._voice_state == "listening":
            speed, base_a, range_a = 4.5, 220, 35
            accent = QColor(236,  72, 153)   # pink-hot
        elif self._voice_state == "error":
            speed, base_a, range_a = 3.5, 200, 55
            accent = QColor(248, 113, 113)   # red
        else:  # idle — slow, soft breath
            speed, base_a, range_a = 1.8, 170, 50
            accent = ACCENT                  # blue

        breathe = (math.sin(elapsed * speed) + 1) * 0.5    # 0..1
        alpha = int(base_a + range_a * breathe)
        fill = QColor(accent); fill.setAlpha(alpha)

        # Outer soft glow so the alive-pulse is visible even on light backgrounds.
        glow_r = self.width() * 0.55 + 2 * breathe
        glow_color = QColor(accent); glow_color.setAlpha(int(60 * breathe + 40))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow_color)
        cx = self.width() / 2
        cy = self.height() / 2
        p.drawEllipse(QPointF(cx, cy), glow_r, glow_r)

        # Inner solid dot.
        dot_r = self.width() / 2 - 2
        p.setBrush(fill)
        p.drawEllipse(QPointF(cx, cy), dot_r, dot_r)
        # Thin rim
        p.setBrush(Qt.BrushStyle.NoBrush)
        rim = QColor(255, 255, 255, 50)
        p.setPen(QPen(rim, 1.0))
        p.drawEllipse(QPointF(cx, cy), dot_r, dot_r)

    def _paint_panel(self, p: QPainter) -> None:
        rect = QRectF(0, 0, self.width(), self.height()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, PANEL_RADIUS, PANEL_RADIUS)
        p.fillPath(path, BG)
        p.setPen(QPen(BG_BORDER, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # Tiny accent stripe down the left edge — visual hook for "this is the
        # answer panel" without making it loud.
        stripe = QRectF(0, PANEL_PADDING, 3, self.height() - 2 * PANEL_PADDING)
        stripe_path = QPainterPath()
        stripe_path.addRoundedRect(stripe, 1.5, 1.5)
        p.fillPath(stripe_path, ACCENT)

        # Header label.
        p.setFont(self._label_font)
        p.setPen(QPen(LABEL))
        label_text = "CURBY"
        if self._latency_ms is not None:
            label_text += f"   ·   {self._latency_ms} ms"
        # Leave room for the collapse button on the right side.
        header_w = int(self.width() - 2 * PANEL_PADDING - COLLAPSE_BTN_SIZE - 8)
        p.drawText(
            int(PANEL_PADDING), int(PANEL_PADDING),
            header_w, 20,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
            label_text,
        )

        # Minimize "—" icon, top-right. NOT a close icon — clicking it
        # collapses to a dot (curby keeps running), it doesn't quit.
        btn = self._collapse_btn_rect()
        # Tinted circle background so the icon reads as a button.
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawEllipse(btn)
        # Single horizontal line — classic minimize affordance.
        p.setPen(QPen(QColor(232, 234, 245, 220), 1.6))
        inset = 4
        mid_y = btn.center().y() + 1   # +1 = sits more centered visually
        p.drawLine(
            int(btn.left() + inset), int(mid_y),
            int(btn.right() - inset), int(mid_y),
        )

        # Body text.
        p.setFont(self._font)
        text_color = TEXT if self._text else TEXT_DIM
        p.setPen(QPen(text_color))
        body = self._text or "Tap Ctrl+Space to ask Claude anything."
        body_y = PANEL_PADDING + 22
        p.drawText(
            int(PANEL_PADDING), int(body_y),
            int(self.width() - 2 * PANEL_PADDING), int(self.height() - body_y - PANEL_PADDING),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
            body,
        )
