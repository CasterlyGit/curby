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
from PyQt6.QtCore import Qt, QPoint, QRectF, QTimer
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
        # Click-through: the panel is read-only — it must never intercept
        # clicks bound for apps underneath. Drag-to-move and click-to-collapse
        # used to live here but blocked the entire top-right of the screen.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._text = ""
        self._latency_ms: int | None = None
        self._collapsed = False
        # Drag state — None means not dragging.
        self._drag_origin: QPoint | None = None
        self._drag_moved = False

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

    # Mouse events are intentionally absent — the panel is click-through
    # (see WA_TransparentForMouseEvents in __init__). Drag-to-move and
    # click-to-collapse were removed because they made the entire top-right
    # of the screen unusable for clicking on apps underneath.

    # ── Paint ──────────────────────────────────────────────────────────────────

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._collapsed:
            self._paint_dot(p)
        else:
            self._paint_panel(p)

    def _paint_dot(self, p: QPainter) -> None:
        rect = QRectF(0, 0, self.width(), self.height()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addEllipse(rect)
        p.fillPath(path, ACCENT)
        p.setPen(QPen(BG_BORDER, 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

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
        p.drawText(
            int(PANEL_PADDING), int(PANEL_PADDING),
            int(self.width() - 2 * PANEL_PADDING), 20,
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
            int(self.width() - 2 * PANEL_PADDING), int(self.height() - body_y - PANEL_PADDING),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
            body,
        )
