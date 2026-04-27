# Test plan — Dock puck hover stability, focus-independent hover, collapse-all, and task completion indicator

## Coverage matrix

| AC | Test type | Test |
|---|---|---|
| AC-1: hover expands panel regardless of OS focus | integration | `test_hover_expands_without_focus` |
| AC-2: panel stays open while cursor inside puck or panel | unit | `test_check_hover_stays_open_inside_panel` |
| AC-3: panel collapses ~300ms after cursor leaves | unit | `test_check_hover_collapses_on_leave` |
| AC-4: no flicker at puck/panel boundary | manual | Eyeball boundary crossing during PR review |
| AC-5: collapse-all hides pucks; second click restores | integration | `test_collapse_all_toggle` |
| AC-6: spinner updates to "done" within 2s of process exit | integration | `test_completion_indicator_fires_after_process_exit` |
| AC-7: completed state persists until dismissed | integration | `test_completion_state_persists` |

## Unit tests

Add to `tests/test_agentic_flow.py` (or a new `tests/test_hover.py`):

- `test_check_hover_stays_open_inside_panel` — synthesize two `check_hover(x, y)` calls with a point inside `puck.frameGeometry()` and a point inside the expanded `panel_global_rect()`; assert `HoverDebouncer.on_enter()` is called each time and `on_leave()` is never called.
- `test_check_hover_collapses_on_leave` — call `check_hover` with a point outside both rects; assert `on_leave()` is called. Advance the Qt event loop by ≥300 ms (via `qtbot.wait`) and assert the panel is collapsed.
- `test_check_hover_skips_hidden_pucks` — hide a puck before calling `check_hover` with a coordinate inside its geometry; assert neither `on_enter()` nor `on_leave()` is called for that puck.
- `test_done_event_prevents_double_on_done` — in `AgentRunner`, set `_done_event` before the companion thread runs; assert `on_done` is called exactly once even if the companion thread also reaches the close path.
- `test_stdout_close_exception_swallowed` — patch `proc.stdout.close()` to raise `ValueError`; assert `_wait_and_close` does not propagate the exception.

## Integration tests

Add to `tests/test_integration.py` or `tests/test_agentic_flow.py`:

- `test_hover_expands_without_focus` — spawn a task puck, emit `bridge.cursor_moved` with a coordinate inside the puck rect, advance the event loop by ≥200 ms; assert the side panel becomes visible. (Simulates pynput path without requiring OS focus; no actual focus change needed since pynput is mocked via `bridge`.)
- `test_collapse_all_toggle` — spawn two task pucks; click `CollapseAllButton`; assert both pucks are hidden and button glyph is ▲. Click again; assert both pucks are visible and glyph is ▼.
- `test_collapse_all_hides_new_spawn` — click collapse-all to collapse; spawn a new task; assert the new puck is immediately hidden (not shown) because `_all_collapsed = True`.
- `test_completion_indicator_fires_after_process_exit` — use `fake_claude.py` to run a task that exits immediately; within 2 s wall time (or advance timers via `qtbot.wait(2000)`), assert `DockedTaskPuck._state == "done"` and the spinner timer is stopped.
- `test_completion_state_persists` — after `_state` flips to `"done"`, emit several `bridge.cursor_moved` events and trigger a relayout; assert `_state` is still `"done"`.

## Manual checks

- [ ] Switch OS focus to a browser while curby is running; hover a task puck for ≥200 ms and confirm the side panel opens.
- [ ] Move the cursor slowly back and forth across the puck/panel boundary; confirm no flicker or rapid open/close cycles.
- [ ] Confirm `PUCK_PIP_DONE_COLOR` (`#6BCB77`) is visually distinct and readable against the actual dark overlay background in `DockedTaskPuck.paintEvent`.
- [ ] Confirm the collapse-all button does not overlap the topmost puck in its default (▼) state; verify it repositions correctly when a new task is added or removed.
- [ ] Run a task that invokes a long-lived grandchild process (e.g. a shell loop); confirm the puck transitions to "done" within 2 s of the top-level `claude` process exiting, even while the grandchild is still running.

## What we are NOT testing (and why)

- Retina DPR mismatch between `frameGeometry()` and pynput coordinates — flagged as a known unknown in DESIGN.md; verify empirically during manual testing rather than writing a brittle geometry test.
- pynput signal queue backpressure at high cursor velocity — acceptable at current puck counts (≤20); not worth a stress test in this iteration.
- Animation timing precision (expand/collapse durations) — out of scope per REQUIREMENTS.md ("animation polish beyond eliminating flicker").
- Per-puck collapse — explicitly out of scope.
