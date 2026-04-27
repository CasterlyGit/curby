# Explore — curby

## Stack
- Language: Python 3, PyQt6 (UI), pynput (global mouse/keyboard), pyobjc (macOS NSWindow shims)
- Package manager: pip / requirements.txt
- Test runner: pytest + pytest-qt

## Layout
- `src/dock_widget.py` — `HoverDebouncer` state machine + `DockedTaskPuck` widget (the puck + panel)
- `src/task_manager.py` — `TaskManager` (owns all pucks, lays them out, routes hover) + `Task` (pairs runner ↔ puck)
- `src/agent_runner.py` — subprocess wrapper for `claude`; emits `on_status` / `on_done` callbacks
- `src/cursor_tracker.py` — wraps `pynput.mouse.Listener`; fires `on_move(x, y)` on every mouse move
- `src/mac_window.py` — `make_always_visible`: elevates NSWindow to status-bar level, sets `setHidesOnDeactivate_(False)`, joins all spaces
- `src/app.py` — top-level wiring; `_Bridge.cursor_moved` signal connects `CursorTracker → TaskManager.check_hover`
- `tests/test_agentic_flow.py` — existing HoverDebouncer decision-table tests (issue-13 section at line 366)

## Entry points
- run: `python main.py`
- test: `pytest tests/`
- build: n/a (no build step)

## Conventions
- PyQt6 signals for cross-thread marshaling (pynput thread → Qt main thread via `QMetaObject` / signal emit)
- `WA_ShowWithoutActivating` + `WindowDoesNotAcceptFocus` on every overlay widget
- `make_always_visible` called after `show()` for each overlay

## Recent activity
- Branch: `auto/13-dock-puck-hover-stability`
- Last commits:
  - `dd59d0f` wire(app): connect bridge.cursor_moved to task_manager.check_hover
  - `7de516c` feat(task_manager): focus-independent hover, collapse-all, updated layout
  - `5e80f66` feat(dock_widget): add CollapseAllButton, panel_global_rect, set_completion_state
  - `259a620` fix(agent_runner): companion thread closes stdout when grandchild outlives parent
- Uncommitted: yes — `src/agent_runner.py` and `tests/test_agentic_flow.py` modified

## Files relevant to this target

### AC-1 / AC-2 / AC-4 (hover reliability, no flicker)
- `src/dock_widget.py:86` — `HoverDebouncer`: enter_ms=80, leave_ms=280; `_fire_leave` re-arms if `_should_commit_collapse()` returns False; `_cursor_outside_self` backstop uses `self.rect().contains(mapFromGlobal(QCursor.pos()))` — checks puck widget rect only (not panel area), so a cursor in the panel during `_fire_leave` could still commit a collapse
- `src/task_manager.py:186` — `check_hover`: hit-tests `puck.frameGeometry()` OR `puck.panel_global_rect()` and calls `on_enter`/`on_leave`; correctly covers both regions

### AC-3 (collapse after cursor leaves both regions)
- `src/dock_widget.py:306` — `_cursor_outside_self`: only checks puck widget, not panel; used as the backstop inside `_fire_leave`; if cursor is in panel but leaveEvent fires on the puck, the backstop wrongly returns True and collapses

### Focus-independent hover (new AC from user comment)
- `src/cursor_tracker.py` — uses `pynput.mouse.Listener`; should be global but requires macOS Accessibility permission; if permission is denied pynput fires only while Python is active
- `src/mac_window.py:24` — `make_always_visible` sets `setHidesOnDeactivate_(False)` so pucks stay visible, but does NOT set `ignoresMouseEvents_(False)` — click-through is managed via Qt flags, not NSWindow

### Completion indicator bug (loading circle doesn't stop)
- `src/task_manager.py:88` — `_on_runner_done` emits `state_changed("done"/"error")` → calls `puck.set_state()` which updates color/paint but does **not** stop `_tick` timer
- `src/dock_widget.py:257` — `set_completion_state()` stops `_tick` and calls `set_state("done")` — but this method is **never called** from `task_manager.py`; only `set_state` is wired via the bridge signal
- Result: the spinning arc animation keeps running after task completes because `_tick` (50 ms, 20fps) is never stopped

### Collapse-all / collapse-one button (user request)
- `src/task_manager.py:117` — `CollapseAllButton` already exists, connected to `_toggle_collapse_all`; hides/shows all pucks
- `src/dock_widget.py:366` — `_set_expanded` handles geometry/chrome; no per-puck "minimize" affordance yet

## Open questions for the next stage

1. **`_cursor_outside_self` scope bug**: should it check the full expanded widget rect (icon + panel) or just the icon? Currently uses `self.rect()` which is the full `QWidget` geometry — need to verify if `self.rect()` expands when the puck is in expanded state (it should, since `_set_expanded` calls `setGeometry` to resize). If so, this is fine. If not, the backstop fires too early.
2. **pynput + macOS focus**: does pynput `mouse.Listener` require Accessibility permission to fire globally? If permission is missing or revoked the fallback is Qt `mouseMoveEvent` which only fires when Python has focus. Is there a permission check on startup?
3. **`set_completion_state` never called**: is the fix simply wiring `on_done → puck.set_completion_state()` instead of `bridge.state_changed.emit("done")`? Need to confirm nothing else depends on the bridge signal path for "done".
4. **Collapse-arrow UX**: user wants a per-puck collapse arrow, not just collapse-all. Needs a new button in the icon area that's always visible (even collapsed), separate from the panel chrome.
