# Test plan — dock puck hover stability + cross-app hover, dock collapse, completion indicator

> Reads: REQUIREMENTS.md (every AC must be covered), DESIGN.md (failure modes)
> Framework: `pytest` + `pytest-qt` (per EXPLORE.md > Conventions). Pure logic
> tests live in `tests/test_agentic_flow.py`; widget-level tests live in
> `tests/test_integration.py`. New tests follow the existing style: real
> `QApplication`, `QTest.qWait` for timer-driven assertions, `monkeypatch` to
> fake the global cursor module.

## Coverage matrix

| AC | Test type | Test |
|---|---|---|
| AC-1 | integration (existing) | `test_dock_puck_hover_expands_within_budget` |
| AC-2 | integration (existing) | `test_dock_puck_stays_expanded_when_cursor_on_child` |
| AC-3 | integration (existing) | `test_dock_puck_collapses_after_leave_window` |
| AC-3 (auto_dismiss leg) | integration (existing) | `test_dock_puck_auto_dismiss_fires_once_per_committed_collapse` |
| AC-4 | integration (new) | `test_dock_puck_boundary_wiggle_bounded_transitions` |
| AC-5 (deterministic) | unit (new) | `test_update_hover_from_global_drives_enter_leave_on_edges` |
| AC-5 (router) | integration (new) | `test_task_manager_set_cursor_dispatches_to_pucks` |
| AC-5 (cross-app) | manual | "focus Chrome, hover puck" |
| AC-6 (toggle) | integration (new) | `test_task_manager_toggle_collapsed_all_hides_and_restores_pucks` |
| AC-6 (auto-restore) | integration (new) | `test_task_manager_spawn_auto_restores_collapsed_dock` |
| AC-6 (chevron) | unit (new) | `test_dock_chevron_emits_clicked_and_flips_glyph` |
| AC-7 (mapper) | unit (new) | `test_state_from_event_table` |
| AC-7 (early emit) | integration (new) | `test_agent_runner_emits_terminal_state_on_result_event` |
| AC-7 (rc fallback) | integration (new) | `test_agent_runner_rc_fallback_does_not_overstamp_event_state` |

## Unit tests

Location: `tests/test_agentic_flow.py` (extends the existing `_status_from_event`
table style).

- `test_state_from_event_table` — `@pytest.mark.parametrize` over the
  `_state_from_event(obj)` mapping. Asserts:
  - `{"type": "result", "subtype": "success"}` → `"done"`
  - `{"type": "result", "subtype": "error_during_execution"}` → `"error"`
  - `{"type": "result", "subtype": "error_max_turns"}` → `"error"`
  - `{"type": "system", "subtype": "init"}` → `None`
  - `{"type": "assistant", ...}` → `None`
  - `{"type": "user", ...}` → `None`
  - `{}` → `None`
  Locks the helper as a single-purpose pure mapper alongside
  `_status_from_event`.

- `test_update_hover_from_global_drives_enter_leave_on_edges` — instantiate a
  real `DockedTaskPuck`, place it at known geometry, then call
  `update_hover_from_global(x, y)` repeatedly with a sequence
  `[outside, outside, inside, inside, outside]`. Assert the puck's
  `HoverDebouncer.on_enter` / `on_leave` are invoked exactly on the edges
  (one enter, one leave; not on idempotent same-state calls). Use a spy on
  `puck._hover.on_enter` / `on_leave` — does not need timer waits because
  the debouncer's own behavior is already covered by the existing
  `HoverDebouncer` tests.

- `test_dock_chevron_emits_clicked_and_flips_glyph` — instantiate
  `DockChevron`, connect a slot to its `clicked` signal, simulate a mouse
  press via `QTest.mousePress`. Assert the slot fired once. Toggle the
  chevron's `expanded` flag and assert its rendered orientation flips
  (cheap proxy: a paint-state attribute or `update()` call count — pick
  whichever the implementation exposes; do not hash pixels).

## Integration tests

Location: `tests/test_integration.py` (alongside the existing
`test_dock_puck_*` cluster).

- `test_dock_puck_boundary_wiggle_bounded_transitions` — **AC-4**. Reuses
  `_make_puck` + `_fake_cursor_module`. Wraps `puck._set_expanded` with a
  spy that counts `True`/`False` transitions. Sequence: enter → wait 150 ms
  → wiggle the fake cursor across the icon↔panel boundary (5 alternating
  positions, 30 ms apart, all inside the union of icon + panel rect) →
  final leave outside → wait 500 ms. Assert: `expand_count + collapse_count
  ≤ 2` for the whole cycle. Locks "no flicker storm at the boundary."

- `test_task_manager_set_cursor_dispatches_to_pucks` — **AC-5**. Construct
  a `TaskManager` (or a thin harness that exposes `set_cursor`) with two
  fake `Task` objects, each with a real `DockedTaskPuck` at distinct
  geometry. Call `manager.set_cursor(x, y)` with coordinates inside puck
  A's rect → assert puck A's `HoverDebouncer.on_enter` fired and puck B's
  did not. Move to puck B's rect → assert the inverse. Move to neutral
  space → assert both received `on_leave`. Verifies the per-puck `inside`
  edge tracking and that the dispatcher does not double-fire.

- `test_task_manager_toggle_collapsed_all_hides_and_restores_pucks` —
  **AC-6**. Construct a `TaskManager` with three pucks. Call
  `toggle_collapsed_all()`; assert all three pucks are hidden and the
  chevron's expanded flag is `False`. Call `toggle_collapsed_all()` again;
  assert all three are visible again (and `_relayout` re-anchored them to
  the right edge — `puck.x()` matches the pre-collapse value). Locks the
  state-restoration contract.

- `test_task_manager_spawn_auto_restores_collapsed_dock` — **AC-6
  (auto-restore)**. Collapse the dock, then call `manager.spawn(...)` (or
  the equivalent path that adds a Task). Assert `_collapsed_all` flips
  back to `False` and the new puck is visible. Locks "no 'where did my new
  task go'."

- `test_agent_runner_emits_terminal_state_on_result_event` — **AC-7
  (early emit)**. Use the existing `tests/fixtures/fake_claude.py` harness
  configured to emit a `{"type":"result","subtype":"success"}` event and
  then sleep before exiting. Wire `AgentRunner(on_state=spy.append, ...)`.
  Assert that `spy` receives `"done"` *before* the subprocess exits
  (poll up to ~500 ms). Confirms the indicator stops spinning at event
  time, not at proc-exit time. Symmetric variant: a `result` event with
  subtype `error_during_execution` produces `"error"` in `spy` first.

- `test_agent_runner_rc_fallback_does_not_overstamp_event_state` — **AC-7
  (idempotency / cancel-path)**. Two sub-cases:
  1. `result` event arrives with subtype `success`; subprocess then exits
     `rc=0`. Assert `spy == ["done"]` — `_handle_done` does not re-emit
     because `_terminal_state_emitted` is True.
  2. User cancels mid-flight; no `result` event; subprocess exits with
     non-zero rc. Assert the final state is `"cancelled"` — the cancel
     path is not overwritten by an rc-derived `"error"`. (Locks the
     `_handle_done` early-return added in DESIGN.md.)

## Manual checks

- [ ] **AC-5 cross-app**: launch curby, spawn one task, focus Chrome (or
  any non-curby app), move the cursor onto the puck without clicking the
  curby window first. The panel must expand. Then move off; it must
  collapse. Repeat with the terminal focused. (Headless tests can't fake
  "another app is foreground" — this is the only way to verify the
  NSWindow + global-router combo on a real machine.)
- [ ] **AC-6 visual**: chevron renders above the top puck, glyph flips
  on click, no z-order glitch with the voice indicator while it's bobbing.
- [ ] **AC-7 visual**: complete a real task; verify the puck's pip stops
  spinning the moment the result event arrives (i.e. the moment the
  result text appears), not seconds later when the process winds down.
  Also trigger an error path (e.g. cancel a task) and verify the pip
  reflects the correct terminal state.
- [ ] **AC-1..AC-4 sanity**: hover a puck for ≥ 200 ms — panel opens.
  Slide the cursor onto a chrome button — panel stays open. Leave —
  collapses within ~300 ms. No flicker at the icon↔panel seam.

## What we are NOT testing (and why)

- **Animation polish / paint quality** — out of scope per REQUIREMENTS.
  We assert state, not pixels.
- **`pynput` permission-revoked path** — degrades to in-app-only hover
  (same as today). Failure mode is documented in DESIGN.md; reproducing
  it in a headless test would require mocking `CursorTracker.start`'s
  failure mode and re-asserting the existing in-app path, which the AC-1
  test already covers.
- **Multi-monitor puck migration** — explicitly out of scope per
  REQUIREMENTS. `_relayout` continues to anchor to the primary screen.
- **Persisting dock-collapsed state across restarts** — out of scope per
  REQUIREMENTS.
- **Click-to-pin** — explicitly out of scope (future ticket).
- **`setAcceptsMouseMovedEvents_` fallback path on PyObjC versions that
  lack it** — design treats it as defense-in-depth wrapped in the
  existing try/except in `make_always_visible`. The global router is the
  primary mechanism and is already covered.
- **End-to-end "user moves cursor across screens with another app
  focused"** — covered manually only; PyQt headless can't simulate the
  foreground-app axis.
