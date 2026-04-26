# Test plan — Dock puck hover stability

> Reads: REQUIREMENTS.md (AC list), DESIGN.md (failure modes + decision table)
> Generated: 2026-04-26

Frameworks already in use (per EXPLORE.md > Conventions): `pytest` with
`@pytest.mark.parametrize` for pure-logic tables, and raw `QApplication` +
`QTest.qWait` for widget tests (no `pytest-qt`, no Qt mocking, no new deps).
Pure-logic tests go in `tests/test_agentic_flow.py`; widget-level tests go in
`tests/test_integration.py`, alongside `test_buddy_window_positioning`.

## Coverage matrix

| AC | Test type | Test |
|---|---|---|
| AC-1 | integration | `test_dock_puck_hover_expands_within_budget` |
| AC-2 | integration | `test_dock_puck_stays_expanded_when_cursor_on_child` |
| AC-3 | integration | `test_dock_puck_collapses_after_leave_window` |
| AC-3 (cancel) | unit | `test_hover_debouncer_reenter_cancels_collapse` (parametrized table case) |
| AC-4 | unit + manual | `test_hover_debouncer_boundary_sweep_single_transition` + manual edge-sweep eyeball |
| AC-5 | unit + integration | `test_hover_debouncer_force_expand_bypasses_enter_timer` + `test_dock_puck_set_amending_opens_immediately_and_holds` |
| AC-6 | integration | `test_dock_puck_auto_dismiss_fires_once_per_committed_collapse` |
| AC-7 | meta | satisfied by the existence of both the pure-logic table test (`test_hover_debouncer_decision_table`) and the `QApplication`-level `test_dock_puck_*` tests above |
| Regression | unit | `test_relayout_skips_expanded_pucks` (pins the `t.puck.width() == COLLAPSED_W` guard at `src/task_manager.py:157`) |

## Unit tests

Location: `tests/test_agentic_flow.py`. All pure-logic; no `QApplication`.
The `HoverDebouncer` is exercised through a thin shim that lets the test
substitute manual `tick()` for the QTimer (per DESIGN.md "AC-7 mechanism").

- `test_hover_debouncer_decision_table` — `@pytest.mark.parametrize` over the
  14-row decision table from DESIGN.md (`Event × _committed × pending_timer
  → action`). Each row asserts the post-call `_committed` value and which
  callback (`on_expand` / `on_collapse`) was invoked.
- `test_hover_debouncer_enter_commits_after_enter_ms` — `on_enter()`, then
  `tick(enter_ms - 1)` → no expand; `tick(enter_ms)` → expand committed once.
- `test_hover_debouncer_leave_commits_after_leave_ms` — from committed-True,
  `on_leave()` → `tick(leave_ms - 1)` no-op; `tick(leave_ms)` collapse once.
- `test_hover_debouncer_reenter_cancels_collapse` (AC-3) — committed-True,
  `on_leave()`, `tick(leave_ms - 50)`, `on_enter()` → no collapse fires; the
  leave timer is stopped.
- `test_hover_debouncer_flyby_cancels_pending_expand` — `on_enter()`,
  `on_leave()` before `enter_ms` elapses → no expand committed (fly-by
  filtering at the icon).
- `test_hover_debouncer_force_expand_bypasses_enter_timer` (AC-5) —
  `force_expand()` → `_committed` flips True synchronously; both timers
  stopped; subsequent `on_leave()` arms leave timer normally.
- `test_hover_debouncer_force_collapse_cancels_both_timers` — from any
  state, `force_collapse()` → `on_collapse` called once if previously
  committed, both timers stopped.
- `test_hover_debouncer_cancel_pending_preserves_committed_state` — used by
  `set_amending(False)`: stops both timers without flipping `_committed`.
- `test_hover_debouncer_boundary_sweep_single_transition` (AC-4) — drive
  `[on_enter, on_leave, on_enter, on_leave, on_enter]` interleaved with
  `tick(< debounce)` advances simulating a 2 s edge sweep; assert
  `on_expand`/`on_collapse` together fire ≤ 1 time in each direction.
- `test_relayout_skips_expanded_pucks` — instantiate `TaskManager`, place
  one collapsed and one expanded puck, call `_relayout()`, assert the
  expanded puck's `pos()` is unchanged. Pins the existing guard so the
  hover fix can't regress it. No Qt event loop required (positions are set
  synchronously by `move()`).

## Integration tests

Location: `tests/test_integration.py`. Pattern matches
`test_buddy_window_positioning` (`tests/test_integration.py:35-54`):
`QApplication.instance() or QApplication(sys.argv)`, instantiate the real
widget, drive events directly, advance time with `QTest.qWait`. `QCursor.pos()`
is monkeypatched per-test (returns a chosen `QPoint`) so the geometry
self-check is deterministic without moving the actual mouse.

Allow ±100 ms slack on time assertions (DESIGN.md "Test determinism") because
`QTest.qWait` is wall-clock.

- `test_dock_puck_hover_expands_within_budget` (AC-1) — show puck;
  monkeypatch `QCursor.pos()` to a point inside `puck.geometry()`; call
  `puck.enterEvent(None)`; `QTest.qWait(200)`; assert `puck._expanded is
  True` and `puck.width() > COLLAPSED_W`. Bounds: total wait ≤ 200 ms
  satisfies the AC-1 budget given `enter_ms = 80`.
- `test_dock_puck_stays_expanded_when_cursor_on_child` (AC-2) — show puck,
  `enterEvent(None)`, wait for expand, then monkeypatch `QCursor.pos()` to
  return a point inside `puck._pause_btn.geometry()` mapped to global
  coords; call `puck.leaveEvent(None)` (simulating Qt firing parent leave
  when the cursor crosses into a child). Assert `puck._expanded is True`
  immediately and after `QTest.qWait(400)` (longer than `leave_ms`) — the
  geometry self-check ignored the leave; the rearmed leave timer also
  ignored once it re-checked. Repeat the assertion with `QCursor.pos()`
  inside `puck._title_label.geometry()` to confirm `WA_TransparentForMouseEvents`
  prevents the parent-leave from firing at all.
- `test_dock_puck_collapses_after_leave_window` (AC-3) — show puck,
  `enterEvent(None)`, wait for expand. Monkeypatch `QCursor.pos()` to a
  point clearly outside `puck.geometry()`; call `puck.leaveEvent(None)`;
  `QTest.qWait(180)` → assert still expanded; `QTest.qWait(200)` (cumulative
  ~380 ms ≥ `leave_ms = 280` + slack) → assert `puck._expanded is False`.
- `test_dock_puck_set_amending_opens_immediately_and_holds` (AC-5) —
  fresh puck (collapsed); call `puck.set_amending(True)`; assert
  `puck._expanded is True` *synchronously* (no `qWait`). Then with
  `QCursor.pos()` outside the geometry, call `leaveEvent(None)` and
  `QTest.qWait(500)`; assert still expanded (the `_is_amending` early-return
  short-circuited the debouncer). Call `set_amending(False)`; assert
  `puck._expanded is True` (no force-collapse) and a subsequent
  `leaveEvent(None)` then commits collapse after `leave_ms + slack`.
- `test_dock_puck_auto_dismiss_fires_once_per_committed_collapse` (AC-6) —
  set `puck._state = "done"`; connect a counter slot to
  `puck.auto_dismiss`; `enterEvent(None)`, wait for expand. Drive a
  rapid leave→reenter→leave→reenter→leave sequence (each separated by
  `QTest.qWait(50)`, all under `leave_ms`), then settle outside and
  `QTest.qWait(500)`. Assert the counter == 1 after the `auto_dismiss`
  delay (120 ms). Confirms emission is bound to the *committed* collapse,
  not raw `leaveEvent` calls or cancelled timers.

## Manual checks

Visual / first-hover behavior on a real macOS display — these can't be
asserted headlessly (per DESIGN.md Risks).

- [ ] First hover after launch on macOS: with the dock empty, dispatch one
      task, wait for the puck to appear, then hover the icon for ~500 ms.
      Panel should expand within ~200 ms of cursor settling. (Validates the
      `NSStatusWindowLevel` + `WA_TranslucentBackground` first-enter risk
      called out in DESIGN.md.)
- [ ] Edge sweep: with the puck expanded, slowly move the cursor along the
      panel's left edge for ~2 s (in and out by a few px). Eyeball: no
      flicker, no open/close storm. (AC-4 visual confirmation; the unit
      sweep test pins the logic, but the rendered behavior needs an eye.)
- [ ] Icon → button traversal: with the puck expanded, glide the cursor
      from the collapsed icon area onto each chrome button (`pause`, `amend`,
      `cancel`, `dismiss`) and pause briefly on each. Panel must not collapse
      mid-traversal. (AC-2 visual.)
- [ ] Amend: trigger `set_amending(True)` (start an amend recording on a
      running puck). Panel opens immediately; move the cursor far away and
      hold for several seconds. Panel must stay open until amend ends.
      (AC-5 visual.)
- [ ] Done puck: let a task finish; hover the resulting "done" puck; leave.
      The puck should auto-dismiss exactly once. Then dispatch another task
      and repeat — no stuck pucks, no double-dismiss. (AC-6 visual.)
- [ ] `_relayout` under hover: dispatch two tasks so the dock has two pucks;
      let one finish so it auto-dismisses while the other is being hovered.
      The hovered (expanded) puck must not be moved by `_relayout`. (Pins
      the `t.puck.width() == COLLAPSED_W` invariant visually.)

## What we are NOT testing (and why)

- **macOS-only first-hover under translucent always-on-top windows.**
  Headless tests can't reproduce the `NSStatusWindowLevel` quirk; covered
  by the manual check above. The `CursorTracker` fallback is explicitly
  out of scope for this change (DESIGN.md Risks) — no test for it.
- **Multi-monitor / cross-screen hover.** Out of scope per REQUIREMENTS.md;
  `_relayout` anchors to the primary screen.
- **Touch / tablet input.** Curby has no touch path today; enter/leave
  semantics are mouse-only (DESIGN.md Risks).
- **Animation / easing curves.** Out of scope per REQUIREMENTS.md;
  `_set_expanded` paints synchronously, no animation under test.
- **Click-to-pin.** Future ticket; not in this AC set.
- **`QTimer` precision under heavy paint load.** The two added single-shot
  timers are negligible vs. the existing 50 ms glow tick; integration tests
  use ±100 ms slack rather than asserting tight timer precision.
- **`pytest-qt` migration.** Existing tests use raw `QApplication`
  (`tests/test_integration.py:35-54`); staying consistent. No `qtbot`.
