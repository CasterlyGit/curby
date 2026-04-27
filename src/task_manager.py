"""Owns the list of in-flight curby tasks and the dock pucks that visualize them.

Each Task pairs an AgentRunner with a DockedTaskPuck and a small bridge that
re-emits the runner's reader-thread callbacks as Qt signals on the main thread.
"""
import threading
from collections.abc import Callable

from PyQt6.QtCore import QObject, QPoint, pyqtSignal
from PyQt6.QtWidgets import QApplication

from src.agent_runner import AgentRunner
from src.dock_widget import (
    DockedTaskPuck, CollapseAllButton, BUTTON_H,
    COLLAPSED_W, COLLAPSED_H, EXPANDED_W,
    EDGE_MARGIN, TOP_MARGIN, GAP, TASK_PALETTE,
)
from src.mac_window import make_always_visible


class _TaskBridge(QObject):
    """Marshal AgentRunner callbacks (reader thread) onto the Qt main thread."""
    status_changed = pyqtSignal(str)
    state_changed  = pyqtSignal(str)


class Task(QObject):
    """One curby task — its runner, its puck, and the wiring between them."""

    finished = pyqtSignal(object)        # emits self when the runner finishes

    def __init__(self, prompt: str, accent):
        super().__init__()
        self.prompt = prompt
        self.bridge = _TaskBridge()

        self.puck = DockedTaskPuck(title=prompt, accent=accent)
        self.puck.pause_clicked.connect(self._on_pause)
        self.puck.resume_clicked.connect(self._on_resume)
        self.puck.cancel_clicked.connect(self._on_cancel)
        self.puck.dismiss_clicked.connect(self._on_dismiss)
        self.puck.auto_dismiss.connect(self._on_dismiss)
        self.puck.amend_toggled.connect(self._on_amend_toggled)

        self.bridge.status_changed.connect(self.puck.set_status)
        self.bridge.state_changed.connect(self.puck.set_state)
        self.bridge.status_changed.connect(self._log_status)

        self.runner = AgentRunner(
            prompt,
            on_event=lambda _e: None,                       # ignore raw events for now
            on_status=self.bridge.status_changed.emit,
            on_done=self._on_runner_done,
        )

        self._dismissed = False
        # Amend hook — the TaskManager wires this to whatever input source
        # collects the amend text (mic, text input, etc.).
        self.start_amend: Callable[[Task], None] | None = None
        self.stop_amend: Callable[[Task], None] | None = None

    def start(self):
        self.runner.start()
        self.bridge.state_changed.emit("running")

    def _on_pause(self):
        self.runner.pause()
        self.bridge.state_changed.emit("paused")

    def _on_resume(self):
        self.runner.resume()
        self.bridge.state_changed.emit("running")

    def _on_cancel(self):
        self.runner.cancel()
        self.bridge.state_changed.emit("cancelled")

    def _on_dismiss(self):
        self._dismissed = True
        self.puck.hide()
        self.finished.emit(self)

    def _on_runner_done(self, rc: int):
        # Emit via the bridge signal so Qt queues delivery to the main thread.
        # QTimer.singleShot from a non-GUI thread is unreliable in PyQt6.
        state = "done" if rc == 0 else "error"
        print(f"[task] done rc={rc} prompt={self.prompt[:60]!r}")
        self.bridge.state_changed.emit(state)

    def _log_status(self, msg: str):
        print(f"[task:{self.prompt[:30]!r}] {msg}")

    def _on_amend_toggled(self, start_recording: bool):
        if start_recording:
            if self.start_amend is not None:
                self.start_amend(self)
        else:
            if self.stop_amend is not None:
                self.stop_amend(self)


class TaskManager(QObject):
    """Holds active tasks and lays out their pucks down the right edge."""

    task_amend_start = pyqtSignal(object)   # Task — UI requests we start recording amend
    task_amend_stop  = pyqtSignal(object)   # Task — UI requests we stop recording + send

    def __init__(self):
        super().__init__()
        self._tasks: list[Task] = []
        self._spawn_counter = 0
        self._all_collapsed = False

        self._collapse_btn = CollapseAllButton()
        self._collapse_btn.clicked.connect(self._toggle_collapse_all)
        # Show to obtain a native window handle for make_always_visible, then
        # hide until there are tasks.
        self._collapse_btn.show()
        make_always_visible(self._collapse_btn)
        self._collapse_btn.hide()

    @property
    def active_tasks(self) -> list[Task]:
        return [t for t in self._tasks if t.runner.is_running]

    def spawn(self, prompt: str) -> Task:
        prompt = (prompt or "").strip()
        if not prompt:
            raise ValueError("empty prompt")
        accent = TASK_PALETTE[self._spawn_counter % len(TASK_PALETTE)]
        self._spawn_counter += 1
        task = Task(prompt, accent=accent)
        task.start_amend = self.task_amend_start.emit
        task.stop_amend  = self.task_amend_stop.emit
        task.finished.connect(self._on_task_finished)
        self._tasks.append(task)
        self._relayout()
        task.puck.show()
        # Pin the puck so it floats above all apps even when curby isn't
        # focused — must be called after show() so the NSWindow exists.
        make_always_visible(task.puck)
        # Respect collapse-all state: hide immediately if user collapsed.
        if self._all_collapsed:
            task.puck.hide()
        task.start()
        return task

    def amend(self, task: Task, text: str):
        task.runner.amend(text)
        task.puck.set_amending(False)

    def _on_task_finished(self, task: Task):
        if task in self._tasks:
            self._tasks.remove(task)
        self._relayout()

    def _relayout(self):
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geom = screen.availableGeometry()
        right = geom.right() - EDGE_MARGIN
        btn_x = right - COLLAPSED_W

        # Position only visible pucks (hidden in collapse-all mode are skipped).
        visible_idx = 0
        first_visible_y = geom.top() + TOP_MARGIN
        for t in self._tasks:
            if not t.puck.isVisible():
                continue
            x = btn_x
            y = geom.top() + TOP_MARGIN + visible_idx * (COLLAPSED_H + GAP)
            if visible_idx == 0:
                first_visible_y = y
            if t.puck.width() == COLLAPSED_W:
                t.puck.setGeometry(x, y, COLLAPSED_W, COLLAPSED_H)
            visible_idx += 1

        btn_y = first_visible_y - BUTTON_H - 4
        self._collapse_btn.setGeometry(btn_x, btn_y, COLLAPSED_W, BUTTON_H)
        self._collapse_btn.setVisible(len(self._tasks) > 0)

    def check_hover(self, x: int, y: int):
        """Hit-test global cursor position against every visible puck and its panel.

        Called on every pynput cursor-move event so hover works regardless of
        which application currently holds OS focus (AC-1).
        """
        pt = QPoint(x, y)
        for t in self._tasks:
            puck = t.puck
            if not puck.isVisible():
                continue
            if puck._is_amending:
                # Keep expanded during amend regardless of cursor position.
                puck._hover.on_enter()
                continue
            puck_rect  = puck.frameGeometry()
            panel_rect = puck.panel_global_rect()
            inside = puck_rect.contains(pt) or panel_rect.contains(pt)
            if inside:
                puck._hover.on_enter()
            else:
                puck._hover.on_leave()

    def _toggle_collapse_all(self):
        if not self._all_collapsed:
            for t in self._tasks:
                t.puck._hover.force_collapse()
                t.puck.hide()
            self._all_collapsed = True
        else:
            for t in self._tasks:
                t.puck.show()
            self._all_collapsed = False
        self._collapse_btn.set_collapsed(self._all_collapsed)
        self._relayout()

    def shutdown(self):
        for t in list(self._tasks):
            t.runner.cancel()
            t.puck.hide()
        self._tasks.clear()
