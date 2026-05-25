"""Reusable collapsible floating widget — the claude-meter pattern.

A frameless always-on-top widget that:
- Is always interactive (no click-through dance, no hover-toggle).
- Can be dragged anywhere by clicking + moving.
- Click-without-drag toggles between EXPANDED (full panel) and
  COLLAPSED (small dot). Drag threshold distinguishes the two.
- Lets subclasses define the expanded paint, the collapsed paint, and
  the expanded/collapsed sizes.

This is the exact pattern claude-meter uses for its meter widget. Pulled
into a shared module so any curby surface that wants the same behavior
(answer note, future settings panel, etc.) can inherit it instead of
copying the boilerplate.

Subclass contract:
    class MyFloater(CollapsibleFloater):
        EXPANDED_SIZE = (340, 120)   # (width, height) when expanded
        COLLAPSED_SIZE = 22          # dot diameter when collapsed

        def paint_expanded(self, p: QPainter): ...
        def paint_collapsed(self, p: QPainter): ...
        # Optional: override compute_expanded_size() for dynamic height.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QWidget


DRAG_THRESHOLD_PX = 4


class CollapsibleFloater(QWidget):
    """Base class for floating, draggable, collapsible top-level widgets."""

    # Emitted whenever collapse state changes; arg is True if now collapsed.
    collapse_changed = pyqtSignal(bool)

    # Subclasses MUST set these.
    EXPANDED_SIZE: tuple[int, int] = (300, 120)
    COLLAPSED_SIZE: int = 22

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

        self._collapsed = False
        self._drag_origin: QPoint | None = None
        self._drag_moved = False

        # Sized to expanded by default; subclass can call _resize_expanded()
        # later (e.g. once it knows its content height).
        self.setFixedSize(*self.EXPANDED_SIZE)

    # ── Public API ─────────────────────────────────────────────────────────

    def set_collapsed(self, collapsed: bool, *, animate: bool = False) -> None:
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        if collapsed:
            self.setFixedSize(self.COLLAPSED_SIZE, self.COLLAPSED_SIZE)
        else:
            self._resize_expanded()
        self.update()
        self.collapse_changed.emit(collapsed)

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    # ── Subclass hooks ─────────────────────────────────────────────────────

    def paint_expanded(self, p: QPainter) -> None:
        """Override to paint the full panel."""
        raise NotImplementedError

    def paint_collapsed(self, p: QPainter) -> None:
        """Override to paint the small dot."""
        raise NotImplementedError

    def compute_expanded_size(self) -> tuple[int, int]:
        """Override to compute the expanded size dynamically (e.g. based on
        wrapped text height). Default: returns EXPANDED_SIZE."""
        return self.EXPANDED_SIZE

    def collapse_hit(self, local_pt: QPoint) -> bool:
        """Override to define a hit-zone INSIDE the expanded panel that
        triggers collapse when clicked (e.g. a minimize button rect).
        Return True if local_pt is inside that zone. Default: False so the
        only collapse path is the click-without-drag everywhere."""
        return False

    # ── Internal helpers ───────────────────────────────────────────────────

    def _resize_expanded(self) -> None:
        w, h = self.compute_expanded_size()
        self.setFixedSize(int(w), int(h))

    # ── Paint dispatch ─────────────────────────────────────────────────────

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._collapsed:
            self.paint_collapsed(p)
        else:
            self.paint_expanded(p)

    # ── Mouse: drag-vs-click ──────────────────────────────────────────────

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        # In BOTH collapsed and expanded states, start a potential drag.
        # Click-vs-drag is decided on release: if the mouse never moved
        # past DRAG_THRESHOLD_PX, treat it as a click (collapsed dot →
        # expand; expanded panel → no-op unless collapse_hit).
        local = event.position().toPoint()
        if not self._collapsed and self.collapse_hit(local):
            self.set_collapsed(True)
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
        # Click without drag on a collapsed dot → expand. Drags just
        # settle wherever the user released.
        if self._collapsed and not self._drag_moved:
            self.set_collapsed(False)
        self._drag_origin = None
        self._drag_moved = False
        event.accept()
