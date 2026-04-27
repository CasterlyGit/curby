# Explore — curby

## Stack
- Python 3.12, PyQt6 (widgets + signals), pynput (global keyboard/mouse), PyObjC (macOS NSWindow shims)
- Package manager: pip + `.venv`; test runner: `pytest` + `pytest-qt`
- macOS-primary desktop overlay app (runs as NSApp accessory so it never steals focus)

## Layout
- `src/` — all application modules (no sub-packages)
- `tests/` — pytest suite: `test_agentic_flow.py` (headless, fake-claude), `test_integration.py` (screen capture + cursor)
- `tests/fixtures/fake_claude.py` — stub `claude` CLI used by agentic tests

## Entry points
- run: `python main.py`
- test: `python -m pytest tests/ -v`
- build: none (dev-run only)

## Conventions
- PyQt6 signals/slots for cross-thread marshalling; Qt timer callbacks for animation
- `WA_ShowWithoutActivating` + `WindowDoesNotAcceptFocus` on all overlay windows
- macOS pinning via `src/mac_window.py::make_always_visible` (PyObjC, called after `show()`)

## Recent activity
- branch: `auto/13-dock-puck-hover-stability`
- last commits:
  - `002a146` integration-test: issue-13 agent-generated artifact
  - `8cabe2d` test-plan: issue-13 agent-generated artifact
  - `0efc216` design: issue-13 agent-generated artifact
  - `bd1172d` implement: issue-13 implementation log
  - `2d340c8` requirements: issue-13 agent-generated artifact
- uncommitted: yes — `.flow/issue-13/` pipeline docs deleted from index, `inbox/` untracked

## Files relevant to this target

- `src/dock_widget.py` — **primary target**: `DockedTaskPuck` (hover expand/collapse, state pip paint) + `HoverDebouncer` (enter/leave debounce state machine). All four ACs live here.
- `src/task_manager.py` — `TaskManager.spawn()` calls `make_always_visible(puck)` and owns `_relayout`; `Task._on_runner_done` → `QTimer.singleShot(0, _handle_done)` is the path that should flip the puck to "done".
- `src/mac_window.py` — `make_always_visible` sets `setLevel_(25)`, `setCollectionBehavior_(canJoinAllSpaces|stationary)`, `setHidesOnDeactivate_(False)`. Does **not** call `acceptsMouseMovedEvents_(True)` or set up an `NSTrackingArea` — this is the likely root cause of hover failing when Python is not the frontmost app.
- `src/cursor_tracker.py` — `CursorTracker` wraps `pynput.mouse.Listener` for **global** mouse position. Already instantiated in `app.py` and emitting coordinates, but currently unused by puck hover logic.
- `src/app.py` — top-level wiring; `_on_cursor_move` receives global coords from pynput and emits `bridge.cursor_moved` — not yet connected to any puck hover path.
- `src/agent_runner.py` — `_read_loop` blocks on `proc.stdout`; calls `on_done(rc)` only after stdout EOF. If the claude subprocess or a child holds stdout open, `set_state("done")` never fires and the spinner loops forever.

## Open questions for the next stage

1. **Hover with app unfocused**: Qt `enterEvent`/`leaveEvent` only fire when Qt receives mouse events. `make_always_visible` does not call `nswindow.setAcceptsMouseMovedEvents_(True)` — is that the missing piece, or does the NSWindow level already grant that? Alternatively, should hover be driven entirely by the pynput `CursorTracker` (geometry hit-test on each move event) instead of Qt events?
2. **Stdout-hang on task completion**: Does the claude CLI ever spawn subprocesses that inherit the stdout pipe, keeping it open after the top-level process exits? Would switching `stdout=subprocess.PIPE, close_fds=True` or using `start_new_session=True` (already set) + explicit pipe close be enough?
3. **`_BEHAVIOR_STATIONARY` interaction**: Does the `NSWindowCollectionBehaviorStationary` flag affect whether the NSWindow receives mouse-moved events from other apps' spaces?
4. **Relayout during expand**: `_relayout` in `TaskManager` skips pucks whose width ≠ `COLLAPSED_W` — correct when expanded, but could cause drift if a puck is mid-expand during a relayout. Worth verifying this doesn't produce geometry glitches.
5. **Dropdown/collapse-all feature** (user request): No current mechanism; would need a new control on the dock or a hotkey to hide/minimize all pucks.
