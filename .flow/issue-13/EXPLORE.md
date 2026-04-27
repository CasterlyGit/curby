# Explore — curby

## Stack
- Python 3.12+, PyQt6 (GUI + signals), pynput (global keyboard/mouse), Anthropic Claude CLI
- Package manager: pip / requirements.txt
- Test runner: pytest + pytest-qt; headless tests in `tests/test_agentic_flow.py`

## Layout
- `src/` — all application modules (no sub-packages)
- `tests/` — pytest suite + `fixtures/fake_claude.py` (fake subprocess for CI)
- `main.py` — entry point (`CurbyApp().run()`)
- `.flow/` — pipeline artifacts (not shipped)

## Entry points
- run: `python main.py`
- test: `pytest tests/`
- build: n/a (no build step)

## Conventions
- PyQt6 signals for cross-thread marshalling; `_Bridge` in `app.py` is the pattern
- Snake-case everywhere; widget internals prefixed with `_`
- Type hints used throughout (`src/dock_widget.py`, `src/task_manager.py`)
- No linter config on disk; code style is PEP 8 + PyQt naming

## Recent activity
- branch: `auto/13-dock-puck-hover-stability`
- last commits:
  - `dd59d0f` wire(app): connect bridge.cursor_moved to task_manager.check_hover
  - `7de516c` feat(task_manager): focus-independent hover, collapse-all, updated layout
  - `5e80f66` feat(dock_widget): add CollapseAllButton, panel_global_rect, set_completion_state
  - `259a620` fix(agent_runner): companion thread closes stdout when grandchild outlives parent
- uncommitted: `tests/test_agentic_flow.py` modified; `.flow/issue-13/` files deleted (stale artifacts)

## Files relevant to this target

- `src/dock_widget.py` — `DockedTaskPuck` (puck widget, expand/collapse, pip painting) and `HoverDebouncer` (enter/leave timer state machine). The pip in `_paint_state_pip` checks `self._state`; for "running" it draws a spinning arc, for "done" a green dot+checkmark. `set_completion_state()` stops the tick timer but **is never called** — `Task` routes done through `bridge.state_changed` → `puck.set_state()` only. `CollapseAllButton` is also here.
- `src/task_manager.py` — `TaskManager.check_hover()` hit-tests global cursor against `puck.frameGeometry()` + `puck.panel_global_rect()` and calls `_hover.on_enter/on_leave`. `Task._handle_done()` emits `state_changed("done"|"error")` via `QTimer.singleShot(0, ...)`. Focus-independence is the stated goal: `check_hover` is fed by the pynput global listener, not Qt enter/leave events.
- `src/cursor_tracker.py` — `CursorTracker` wraps `pynput.mouse.Listener`; fires `on_move` callback (then marshalled via `bridge.cursor_moved` signal). Global — fires regardless of which app has focus. The signal emit crosses threads into the Qt event loop.
- `src/app.py` — wires `CursorTracker._on_cursor_move` → `bridge.cursor_moved.emit` → `task_manager.check_hover`. Also hosts `_Bridge` for all cross-thread signals.
- `src/agent_runner.py` — `is_running` property (`proc.poll() is None`); `on_done(rc)` fires from reader thread. Recent fix (259a620) closes stdout when a grandchild outlives the parent — relevant to whether `on_done` fires reliably.
- `tests/test_agentic_flow.py` — existing `HoverDebouncer` test suite (lines 366–640) and `test_relayout_skips_expanded_pucks` regression. New ACs will need tests here.

## Open questions for the next stage

1. **Focus-independence gap**: pynput fires globally, but does Qt process the queued `cursor_moved` signal while another macOS app is frontmost? Does `WindowDoesNotAcceptFocus` + `WA_ShowWithoutActivating` prevent the Qt event loop from draining the queue?
2. **Completion pip not updating**: `set_completion_state()` exists on the puck but `Task._handle_done` never calls it — only `set_state()`. If the pip still shows "running" after done, is this a missing call, or does `is_running` on the runner not return `False` quickly enough to prevent some re-rendering path from overwriting the state?
3. **`panel_global_rect()` correctness**: returns `frameGeometry()` when expanded. After `_set_expanded(True)` the puck widget is repositioned left; does `frameGeometry` always reflect the new position before `check_hover` is called on the next move event?
4. **`_cursor_outside_self` in `HoverDebouncer`**: uses `QCursor.pos()` polled at leave-timer fire time — but `check_hover` bypasses Qt events and calls `on_enter/on_leave` directly. Are both paths consistent, or can one arm the timer while the other already knows the cursor is inside?
5. **Collapse-all + completion**: when `_all_collapsed` is True, newly-done tasks are hidden — does that hide them before the user sees the completion pip?
