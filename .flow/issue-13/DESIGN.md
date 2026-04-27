# Design — Dock puck hover stability, focus-independent hover, collapse-all, and task completion indicator

> Reads: REQUIREMENTS.md (acceptance criteria are the contract)
> Generated: 2026-04-27

## Approach

Drive hover entirely from the existing pynput global listener (`CursorTracker` → `bridge.cursor_moved`) rather than from Qt `enterEvent`/`leaveEvent`, which only fire when the Qt app holds OS focus. A new `TaskManager.check_hover(x, y)` slot hit-tests each puck's (and expanded panel's) `frameGeometry()` on every cursor-move signal and calls the existing `HoverDebouncer.on_enter()` / `on_leave()` — leaving all debounce, timer, and flicker-prevention logic untouched. The stdout-hang fix uses a companion thread that calls `proc.wait()` and then `proc.stdout.close()` to force EOF in the reader loop once the top-level process exits, with a `threading.Event` guard to prevent double `on_done`. The collapse-all button is a new minimal `QWidget` subclass pinned above the puck stack via `make_always_visible`.

Alternatives not taken: `acceptsMouseMovedEvents_(True)` in `make_always_visible` (focus-dependent and risks double-fire through `HoverDebouncer`; pynput is sufficient); `os.killpg(SIGTERM)` for stdout-hang cleanup (kills grandchildren the user may want running; close-only is sufficient).

## Components touched

| File / module | Change |
|---|---|
| `src/task_manager.py` | Add `check_hover(x, y)` Qt slot; connect `bridge.cursor_moved` to it in `__init__`; add `_all_collapsed: bool` flag; add `_toggle_collapse_all()` method; instantiate and wire `CollapseAllButton`; update `_relayout` to position button and skip hidden pucks |
| `src/dock_widget.py` | Add `CollapseAllButton` QWidget subclass; add `DockedTaskPuck.set_completion_state()` slot that stops the spinner timer and sets pip to "done" visual; add `PUCK_PIP_DONE_COLOR` constant |
| `src/agent_runner.py` | Add `_wait_thread` companion thread: `proc.wait()` → `proc.stdout.close()`; add `_done_event: threading.Event` to guard against double `on_done` call; catch `ValueError`/`OSError` on close of already-closed pipe |
| `src/app.py` | Connect `bridge.cursor_moved` to `task_manager.check_hover` (currently wired to nothing downstream in task_manager) |

## New files

None. `CollapseAllButton` is ~50 lines and lives in `src/dock_widget.py` alongside all other puck UI.

## Data / state

**`TaskManager` new state**
- `_all_collapsed: bool = False` — whether all pucks are currently hidden by collapse-all
- `_collapse_btn: CollapseAllButton` — the floating arrow button widget

**`DockedTaskPuck` pip states** (existing `_state` string, extended)
- `"running"` — spinning arc, existing behavior
- `"done"` — static filled circle, `PUCK_PIP_DONE_COLOR = "#6BCB77"` (green)
- `"error"` — existing (if present), unchanged

**`AgentRunner` new state**
- `_done_event: threading.Event` — set when `on_done` is first called; companion thread checks before calling after forced-close

**`CollapseAllButton` state**
- `_collapsed: bool` — mirrors `TaskManager._all_collapsed`; controls which arrow glyph is painted (▼ = pucks visible, ▲ = pucks hidden)

## Public API / surface

**New slots/methods**
```
TaskManager.check_hover(x: int, y: int)   # Qt slot, connected to bridge.cursor_moved
TaskManager._toggle_collapse_all()         # internal, triggered by CollapseAllButton.clicked
DockedTaskPuck.set_completion_state()      # Qt slot, invoked via _TaskBridge on task done
```

**`CollapseAllButton`**
```
CollapseAllButton(parent=None)
  .set_collapsed(state: bool)   # called by TaskManager to flip arrow glyph
  .clicked → signal             # connected to TaskManager._toggle_collapse_all
```

**`check_hover` hit-test logic (pseudocode)**
```
for task in self._tasks:
    puck = task.puck
    if not puck.isVisible(): continue
    puck_rect  = puck.frameGeometry()
    panel_rect = puck.panel_global_rect()  # expanded panel rect in global coords; empty if collapsed
    inside = puck_rect.contains(QPoint(x, y)) or panel_rect.contains(QPoint(x, y))
    if inside:
        task._hover.on_enter()
    else:
        task._hover.on_leave()
```

`panel_global_rect()` returns an empty `QRect` when the panel is not expanded, so the `contains` check is always false for collapsed pucks — no change to collapse logic.

**`_relayout` additions (pseudocode)**
```
# after placing all visible pucks, reposition collapse button:
top_y = position of topmost visible puck (or screen top if all collapsed)
btn_rect = QRect(right_edge - COLLAPSED_W, top_y - BUTTON_H - 4, COLLAPSED_W, BUTTON_H)
self._collapse_btn.setGeometry(btn_rect)
self._collapse_btn.setVisible(len(self._tasks) > 0)
```

**`_toggle_collapse_all` logic (pseudocode)**
```
if not _all_collapsed:
    for task in _tasks:
        task._hover.force_collapse()   # flush any pending expand timer
        task.puck.hide()
    _all_collapsed = True
else:
    for task in _tasks:
        task.puck.show()
    _all_collapsed = False
_collapse_btn.set_collapsed(_all_collapsed)
_relayout()
```

**`AgentRunner` companion thread (pseudocode)**
```
def _wait_and_close():
    rc = proc.wait()           # blocks until top-level process exits
    if not _done_event.is_set():
        try: proc.stdout.close()
        except (ValueError, OSError): pass
        # reader thread will get IOError/StopIteration → on_done fires there

# start alongside _read_loop thread in start()
threading.Thread(target=_wait_and_close, daemon=True).start()

# in _read_loop, after loop exits:
if not _done_event.is_set():
    _done_event.set()
    on_done(proc.returncode or 0)
```

## Failure modes

| Failure | How we detect | What we do |
|---|---|---|
| `check_hover` receives stale geometry for a not-yet-shown puck | `puck.isVisible()` returns False | Skip that puck in the loop |
| `proc.stdout.close()` called after reader already exited cleanly | `_done_event` already set | Companion thread skips the close entirely; no double `on_done` |
| `proc.stdout.close()` raises on already-closed fd | `ValueError` / `OSError` | Catch and ignore; reader loop has already exited |
| Collapse-all pressed while puck is mid hover-expand | Expand timer fires after `hide()` | Call `force_collapse()` before `hide()` so debouncer flushes its pending timer |
| `_relayout` called while `_all_collapsed = True` | Pucks are hidden; loop skips them | `_relayout` only positions visible pucks; button repositions to top of screen edge |
| Collapse button overlaps topmost puck on relayout | Button Y = `top_y - BUTTON_H - 4` | `_relayout` always places button above topmost puck; `make_always_visible` keeps it on screen |
| `set_completion_state()` called before puck is visible | Slot fires on Qt thread via bridge | Harmless — timer stops and pip repaints whenever the widget next paints |

## Alternatives considered

- **`acceptsMouseMovedEvents_(True)` in `mac_window.py`**: Would let Qt `enterEvent`/`leaveEvent` fire app-unfocused, but (a) still focus-adjacent on some macOS versions, (b) risks double-fire through `HoverDebouncer` since Qt and pynput would both fire enter/leave near boundary crossings. pynput is already running and sufficient — don't add this.
- **`os.killpg(pgid, SIGTERM)` for stdout-hang**: Terminates the entire process group, which is aggressive and could kill grandchildren the user started intentionally. `proc.stdout.close()` forces the reader loop to exit without terminating anything.
- **Separate `CollapseAllButton` module**: Only ~50 lines; not worth a new file. Colocating with `DockedTaskPuck` in `dock_widget.py` keeps all puck-related UI in one place.
- **New pip state as a separate widget layer**: Simpler to extend the existing `paintEvent` state machine (`"running"` → `"done"`) than to composite a second widget on top of the pip.

## Risks / known unknowns

- **pynput signal queue depth on fast mouse moves**: pynput can fire hundreds of events/sec; each queued `check_hover` call is O(n) `QRect.contains` — acceptable for typical puck counts (≤20), but if signals back up, hover latency increases. Qt `QueuedConnection` (default for cross-thread signals) already serializes delivery; no explicit throttle needed at current scale.
- **`frameGeometry()` vs `geometry()` for global coords**: `frameGeometry()` includes the window frame in global screen coordinates; pynput gives global screen coordinates. Verify in implementation that `puck.frameGeometry()` matches pynput coordinates on Retina displays (device-pixel vs. logical-pixel). If there is a DPR mismatch, use `QScreen.logicalDotsPerInch()` to scale.
- **Button position on screen with dynamic puck count**: If a new task is spawned while `_all_collapsed = True`, its puck should remain hidden until the user restores. `TaskManager.spawn()` must check `_all_collapsed` and call `puck.hide()` immediately after creation if the flag is set.
- **Completed pip color contrast**: `#6BCB77` against the dark overlay background should be sufficient; verify in implementation against the actual background color used in `DockedTaskPuck.paintEvent`.
