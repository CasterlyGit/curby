# Research — Dock puck hover stability, focus-independent hover, and task completion indicator

> Reads: EXPLORE.md
> Generated: 2026-04-27

## Resolved

- **Q1: Hover with app unfocused — missing piece in `make_always_visible`?**
  A: Confirmed missing. `make_always_visible` (`src/mac_window.py:46-54`) sets level + collection behavior + `setHidesOnDeactivate_(False)` but never calls `nswindow.setAcceptsMouseMovedEvents_(True)`. Without that call, NSWindow only delivers mouse-moved events (and therefore Qt `enterEvent`/`leaveEvent`) when the Qt app is the frontmost application. Adding that call would help, but the more robust fix is to drive hover entirely from the **pynput global listener** already running in `src/cursor_tracker.py`. A geometry hit-test in `TaskManager._on_cursor_move` (global coords → `puck.frameGeometry().contains(pt)`) fires regardless of which app is focused, and bypasses NSWindow event routing entirely. `app.py:_on_cursor_move` already receives global coords from `CursorTracker` and emits `bridge.cursor_moved`, but that signal is never connected to any puck hover path. Wiring it to `TaskManager` is the primary fix. Evidence: `src/mac_window.py:46-54`, `src/app.py`, `src/cursor_tracker.py`.

- **Q2: Stdout-hang on task completion**
  A: The `_read_loop` in `src/agent_runner.py:116-150` blocks on `for raw in proc.stdout`, which only exits on pipe EOF. `start_new_session=True` isolates the new process group for signal delivery but does NOT close the write end of the stdout pipe for grandchild processes (bash scripts, npm runs, etc.) spawned by the claude CLI before they exec. Those grandchildren inherit the write end; if they outlive the top-level `claude` process, `EOF` never arrives and `on_done` is never called. Fix: add a companion monitor thread that calls `proc.wait()` and, once the top-level process has exited, calls `proc.stdout.close()` to force EOF in the reader thread. Alternatively, use `os.killpg(pgid, SIGTERM)` after `proc.wait()` to reap any orphaned group members. Evidence: `src/agent_runner.py:96-133`.

- **Q3: Does `_BEHAVIOR_STATIONARY` block mouse events?**
  A: No. `NSWindowCollectionBehaviorStationary` (bit 4, `src/mac_window.py:21`) only suppresses window movement during Mission Control/Expose transitions. It has no effect on whether the window receives mouse-moved events from other apps' spaces. The hover failure is entirely attributable to the missing `acceptsMouseMovedEvents_` call (see Q1).

- **Q4: Relayout drift during expand**
  A: Not a real concern. `_set_expanded` (`src/dock_widget.py:348-362`) calls `setGeometry` atomically — the puck jumps directly to `EXPANDED_W`; there is no incremental animation width. So `t.puck.width()` is always exactly `COLLAPSED_W` or `EXPANDED_W` when `_relayout` reads it. The guard `t.puck.width() == COLLAPSED_W` (`src/task_manager.py:157`) is correct and safe. Evidence: `src/dock_widget.py:348-362`, `src/task_manager.py:147-158`.

- **Q5: Dropdown/collapse-all mechanism**
  A: No current mechanism exists. The lowest-risk path is a new small persistent floating widget (a tiny arrow button pinned above the puck stack, also passed through `make_always_visible`) that sets a `_all_hidden: bool` flag on `TaskManager` and calls `puck.hide()` / `puck.show()` on all tasks. No changes to `AgentRunner` or `HoverDebouncer` needed; the pucks resume normal behavior when restored. This is a net-new feature, not a hover-stability fix.

## Constraints to honor

- `WA_ShowWithoutActivating` + `WindowDoesNotAcceptFocus` must remain on all pucks — pucks must never steal focus from the user's foreground app.
- `make_always_visible` must be called after `puck.show()` so the NSWindow handle exists (`src/task_manager.py:131-134`).
- All puck state mutations must cross the `_TaskBridge` signal boundary (`src/task_manager.py:44-45`) — never touch puck from the runner thread directly.
- `HoverDebouncer` is the committed state machine; any pynput-driven hover path must call `_hover.on_enter()` / `_hover.on_leave()` (or `force_expand`/`force_collapse`) rather than bypassing it, so existing debounce timers and the `_should_commit_collapse` backstop remain in play.

## Prior art in this repo

- `src/cursor_tracker.py` — `CursorTracker` wraps `pynput.mouse.Listener`; already instantiated and connected to `app.py:_on_cursor_move`. We can extend `TaskManager` with a `check_hover(x, y)` slot and connect `bridge.cursor_moved` there. No new dependency; just wiring.
- `src/dock_widget.py:83` (`HoverDebouncer`) — existing debounce state machine with injectable timer factory; the design already anticipates an external enter/leave source via `on_enter()` / `on_leave()`.
- `src/dock_widget.py:288` (`_cursor_outside_self`) — geometry backstop already used as `should_commit_collapse`; the same `QCursor.pos()` technique can serve as a secondary check after pynput fires.

## External references

- None needed. All behavior is explainable from the local source.

## Remaining unknowns (for design to handle)

- **pynput event rate vs. Qt timer rate**: pynput mouse events can fire at hundreds of Hz; the `TaskManager.check_hover` handler must be cheap (a simple `QRect.contains` per puck). If there are many pucks, this is still O(n) and fine, but design should note the threading boundary (pynput listener runs on its own thread; `check_hover` must be invoked via Qt signal, not called directly).
- **`acceptsMouseMovedEvents_` + pynput: use one or both?**: pynput is sufficient and cross-platform-safe; adding `acceptsMouseMovedEvents_(True)` in `make_always_visible` is a belt-and-suspenders improvement but may cause double-fire of enter/leave if Qt events also start arriving. Design should pick one primary path (pynput recommended) and document whether the Qt events are disabled or left as harmless no-ops (since `HoverDebouncer.on_enter` is idempotent when already committed).
- **Collapse-all button placement**: if implemented, where to place the control so it does not overlap the topmost puck when it slides in. Design should specify the offset or anchor.
