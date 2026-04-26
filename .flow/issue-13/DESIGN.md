# Design — Stabilize dock-puck hover with a debounced, geometry-checked state machine

> Reads: REQUIREMENTS.md (acceptance criteria are the contract)
> Generated: 2026-04-26

## Approach

Keep the single resized widget (no new windows, no global cursor polling) and fix
the two root causes from RESEARCH.md inside `DockedTaskPuck`:

1. **Lift the hover decision out of raw Qt enter/leave** into a small, pure
   `HoverDebouncer` helper that owns enter/leave timers and a current
   *intent* (`expanded` / `collapsed`). This is unit-testable with synthetic
   timestamps and has no Qt dependencies.
2. **In `leaveEvent`, verify the cursor against the widget's screen rect**
   before arming the leave timer (strategy (a) from REQUIREMENTS open
   questions). When a child button "steals" the leave, `QCursor.pos()` is
   still inside `self.geometry()` → ignore the leave entirely. This kills
   the flicker storm at the icon↔button boundary and at the panel↔button
   boundary.

Alternatives considered (and rejected): an event filter swallowing parent
`Leave` while `childAt(pos)` returns a chrome widget (more code, same
effect); splitting the panel into a second top-level window (multiplies
NSWindow surface; ruled out in RESEARCH.md); a global cursor-polling timer
on every puck (heavier than needed; reserved as a follow-up if macOS
`NSStatusWindowLevel` proves to drop initial enter events — see Risks).

## Components touched

| File / module | Change |
|---|---|
| `src/dock_widget.py` | Replace direct `_set_expanded` calls in `enterEvent`/`leaveEvent` with calls into a new `HoverDebouncer` member. Add a geometry self-check in `leaveEvent` that re-arms / ignores when `QCursor.pos()` is still inside `self.geometry()`. Make static label children mouse-transparent (`_title_label`, `_status_label` get `WA_TransparentForMouseEvents`). Buttons stay clickable; the geometry check covers them. Move `auto_dismiss` emission out of `leaveEvent` and into the *committed* collapse callback so it fires once per real leave (AC-6). Preserve the `_is_amending` early-return as the first check inside the debouncer's leave path and bypass the enter-debounce in `set_amending(True)` (AC-5). |
| `src/dock_widget.py` (new class in same file) | Add `HoverDebouncer` — a small QObject with two `QTimer` members (`_enter_timer`, `_leave_timer`), a current committed state (`_committed: bool`), and callbacks `on_expand`, `on_collapse`. Public methods: `on_enter()`, `on_leave()`, `force_expand()`, `force_collapse()`, `cancel_pending()`. |
| `src/task_manager.py` | No code change. Re-assert in tests that `_relayout` only moves collapsed pucks (existing `t.puck.width() == COLLAPSED_W` guard at `src/task_manager.py:157`). Out of scope: cross-screen behavior. |
| `tests/test_agentic_flow.py` | Add a parametrized table test for `HoverDebouncer` using a fake-clock + manual `tick(now_ms)` (no `QApplication`). Cases: enter→hold→commit-expand at ≥ enter_ms, leave→commit-collapse at ≥ leave_ms, leave-then-reenter cancels collapse, child-leave-while-cursor-inside ignored, force_expand bypasses debounce, force_collapse cancels both timers. |
| `tests/test_integration.py` | Add `test_dock_puck_hover_stability` — instantiate a real `DockedTaskPuck`, call `enterEvent(None)` / `leaveEvent(None)` with monkeypatched `QCursor.pos()` (or by passing the cursor location through a small seam — see Public API), advance time with `QTest.qWait`, assert AC-2 and AC-3 boundary behavior. Same `QApplication` pattern as `test_buddy_window_positioning` at `tests/test_integration.py:35-54`. |

## New files

- _None._ `HoverDebouncer` lives in `src/dock_widget.py` next to `DockedTaskPuck` so the hover logic stays colocated and the file remains the single import for "puck stuff." A separate file would split a tightly-coupled pair across modules for no test or reuse benefit.

## Data / state

New members on `DockedTaskPuck`:

| Member | Type | Purpose |
|---|---|---|
| `_hover` | `HoverDebouncer` | Owns enter/leave timers and committed-intent state. Replaces the implicit "intent = whatever the last enter/leave called" logic. |
| `_pending_auto_dismiss` | `bool` | Set on the *committed* collapse when `_state in {"done","error","cancelled"}` and `_was_hovered_after_done`; consumed by a 120 ms `QTimer.singleShot` to emit `auto_dismiss`. Splits "raw leave" from "real leave" so AC-6 holds even when timers cancel and re-arm. |

`HoverDebouncer` internal state:

| Field | Type | Purpose |
|---|---|---|
| `_committed` | `bool` | Last committed expansion state (mirrors `DockedTaskPuck._expanded` after `on_expand`/`on_collapse` runs). |
| `_enter_timer` | `QTimer` (single-shot, non-repeating, parent=widget) | Fires `on_expand` after `enter_ms` if not cancelled by a leave. |
| `_leave_timer` | `QTimer` (single-shot, non-repeating, parent=widget) | Fires `on_collapse` after `leave_ms` if not cancelled by a re-enter. |
| `enter_ms` | `int` constant | **80 ms.** ≤ 100 ms keeps total enter-to-visible latency ≤ ~120 ms (timer + paint), well inside the 200 ms AC-1 budget. |
| `leave_ms` | `int` constant | **280 ms.** Inside AC-3's 250–350 ms target window; closer to the upper end so quick re-entries near the boundary cancel reliably (AC-4). |

No persisted state, no env vars, no schemas. All hover state is in-process and per-puck.

## Public API / surface

`DockedTaskPuck` (existing public surface, unchanged signatures):
- `enterEvent(e)` — now calls `self._hover.on_enter()`. Sets `_was_hovered_after_done = True` for done/error/cancelled before delegating.
- `leaveEvent(e)` — now: (1) if `_is_amending` → super and return (preserves carve-out at `src/dock_widget.py:155-156`); (2) if `self.rect().contains(self.mapFromGlobal(QCursor.pos()))` → super and return (the cursor is on a child widget; ignore the parent leave); (3) otherwise `self._hover.on_leave()`.
- `set_amending(on)` — when `on=True`, calls `self._hover.force_expand()` instead of `_set_expanded(True)`. When `on=False`, no force-collapse — the user's cursor decides via the normal debounce path.
- All signals unchanged: `pause_clicked`, `resume_clicked`, `cancel_clicked`, `amend_toggled`, `dismiss_clicked`, `auto_dismiss`.

`HoverDebouncer` (new, internal — not imported elsewhere):
- `__init__(parent: QWidget, on_expand: Callable[[], None], on_collapse: Callable[[], None], enter_ms: int = 80, leave_ms: int = 280)`
- `on_enter() -> None` — cancel `_leave_timer`; if `_committed` already True, no-op; else (re)start `_enter_timer`.
- `on_leave() -> None` — cancel `_enter_timer`; if `_committed` already False, no-op; else (re)start `_leave_timer`.
- `force_expand() -> None` — cancel both timers; if not `_committed`, call `on_expand()` synchronously and set `_committed = True`.
- `force_collapse() -> None` — cancel both timers; if `_committed`, call `on_collapse()` synchronously and set `_committed = False`. (Used only on widget hide/destroy.)
- `cancel_pending() -> None` — stop both timers without changing committed state. (Used on `set_amending(False)` to drop any in-flight enter timer that might race.)

Pure-logic decision table (used by the unit test; the QTimer-backed implementation is a thin shim over this):

| Event | `_committed` | Pending timer | Action |
|---|---|---|---|
| `on_enter` | False | none | start enter timer |
| `on_enter` | False | enter armed | restart enter timer |
| `on_enter` | False | leave armed | stop leave timer; start enter timer |
| `on_enter` | True | none | no-op |
| `on_enter` | True | leave armed | stop leave timer (cursor returned) |
| `on_leave` | True | none | start leave timer |
| `on_leave` | True | leave armed | restart leave timer |
| `on_leave` | True | enter armed | _impossible_ (committed True ⟹ enter already fired); but if reached, stop enter timer + start leave timer |
| `on_leave` | False | none | no-op |
| `on_leave` | False | enter armed | stop enter timer (fly-by filtered) |
| `enter_timer fires` | False | — | call `on_expand`; set `_committed = True` |
| `leave_timer fires` | True | — | call `on_collapse`; set `_committed = False` |
| `force_expand` | False | any | cancel both; call `on_expand`; set `_committed = True` |
| `force_collapse` | True | any | cancel both; call `on_collapse`; set `_committed = False` |

AC mapping:

| AC | Mechanism |
|---|---|
| AC-1 (≥ 200 ms hover ⟹ visible, latency ≤ 200 ms) | `enter_ms = 80`; `_set_expanded(True)` paints synchronously inside the same Qt tick. Headroom ~120 ms. |
| AC-2 (cursor anywhere inside puck or panel keeps open) | `leaveEvent` geometry self-check (`QCursor.pos()` in `self.geometry()`) ignores child-button-stolen leaves; static labels get `WA_TransparentForMouseEvents` so they don't generate the parent-leave at all. |
| AC-3 (cursor outside both ⟹ collapses within ~300 ms) | `leave_ms = 280`. |
| AC-4 (no flicker / open-close storms on boundary) | Geometry self-check + symmetric debounce + cancel-on-reentry. Across a 2 s edge sweep the debouncer commits ≤ 1 transition in each direction by construction (a transition can only commit when the timer expires uninterrupted). |
| AC-5 (set_amending opens immediately, stays open) | `set_amending(True)` calls `force_expand()` (synchronous, bypasses enter timer). `_is_amending` early-return in `leaveEvent` short-circuits the debouncer entirely. |
| AC-6 (auto_dismiss exactly once per real leave) | `auto_dismiss` is emitted from the `on_collapse` callback (post-commit), not from `leaveEvent`. Cancelled+rearmed leave timers do not fire `on_collapse`. |
| AC-7 (deterministic tests) | Pure `HoverDebouncer` is timer-injection-friendly (the test substitutes a fake clock + manual `tick(now_ms)` by bypassing the QTimer shim and driving the table directly); integration test uses raw `QApplication` + `QTest.qWait`. |

## Failure modes

| Failure | How we detect | What we do |
|---|---|---|
| Enter timer fires after the puck is hidden / destroyed (e.g. task finished mid-hover) | `QTimer(self)` is parented to the widget, so it is destroyed with the widget. As belt-and-braces, `on_expand` checks `self.isVisible()` before resizing. | No-op the expand. |
| Leave timer races `set_amending(True)` | `force_expand()` cancels both timers before committing. | Amend wins; the queued collapse is dropped. |
| `QCursor.pos()` not yet updated when `leaveEvent` fires (Qt quirk on macOS) | If the geometry check says "still inside" but Qt then fires no further event, the panel would stick open. | Mitigation: when the geometry check ignores a leave, also (re)arm the leave timer — if the cursor really has left, the timer will commit collapse 280 ms later when no enter has cancelled it. |
| `auto_dismiss` double-fire (rapid hover-leave-hover-leave on a done puck) | `auto_dismiss` is emitted from `on_collapse`, which fires once per committed transition. | Naturally single-shot per real collapse. The 120 ms `QTimer.singleShot` is started in `on_collapse`, never in raw `leaveEvent`. |
| `_relayout` moves a puck out from under a hovering cursor | `TaskManager._relayout` already guards `t.puck.width() == COLLAPSED_W` (`src/task_manager.py:157`), so an expanded puck is never moved. | Add a regression test asserting this guard still holds; no production change. |
| macOS `NSStatusWindowLevel` + `WA_TranslucentBackground` drops the *first* enterEvent | Manual repro on macOS after the fix lands. If reproducible, AC-1 will fail intermittently for first-hovers. | **Out of scope for this change.** Documented in Risks. Follow-up: extend `CursorTracker` (`src/cursor_tracker.py`, currently feeds only `voice_indicator`) to dispatch positions to `TaskManager`, which would synthesize enter/leave per puck. |
| Hover during programmatic `set_amending(False)` leaves an enter timer in flight | `set_amending(False)` calls `self._hover.cancel_pending()` to drop any in-flight enter, then lets the next user enter/leave drive the state machine. | Clean rearm on next user gesture. |

## Alternatives considered

- **Event filter swallowing parent `Leave` when `childAt(pos)` is a chrome button.** Strictly equivalent to the geometry self-check for the AC set, but introduces a Qt event-filter install/remove pair on every puck and a list of "known children to ignore." Strategy (a) is one `if` and works for *any* future child without a list. Picked (a).
- **Split the panel into a second top-level window.** Cleanest visually but multiplies NSWindow surface (RESEARCH.md): two `make_always_visible` calls per puck, two NSWindows to keep aligned during `_relayout`, focus-stealing risk, screen-edge / DPI snapping bugs. Rejected.
- **Global cursor polling on every puck (mirror of `voice_indicator`'s 30 fps tick).** Heavier than necessary when Qt's enter/leave already work for the dominant case. Reserved as a fallback if AC-1 fails on macOS first-hovers — see Risks.
- **Higher enter debounce (e.g. 150 ms) to filter fly-bys more aggressively.** Pushes worst-case enter-to-visible latency past AC-1's 200 ms budget once paint is included. 80 ms keeps headroom.
- **Folding the 120 ms `auto_dismiss` delay into the leave debounce window.** Conflates two semantics: the leave debounce is "is this a real leave?" while the 120 ms is "let the user see the final state for a moment after they've left." Keeping them separate keeps each one explainable; same call as RESEARCH.md.
- **`pytest-qt` (`qtbot`) for the integration test.** Existing tests use raw `QApplication` (`tests/test_integration.py:35-54`). Hover doesn't need `waitSignal` ergonomics — `QTest.qWait` plus member inspection is enough. Stay consistent.

## Risks / known unknowns

- **macOS first-hover under `NSStatusWindowLevel` + `WA_TranslucentBackground`.** Couldn't verify headlessly. The fix is robust to *child*-stolen leaves and *re-entry* races, but if Qt drops the very first `enterEvent` on a translucent always-on-top window, AC-1 will fail intermittently for the first hover after `_relayout` moves a puck. Mitigation path is scoped (extend `CursorTracker` → `TaskManager` → per-puck synthetic enter/leave) but explicitly out of this change. Flag for human review after the fix lands.
- **Geometry self-check vs. cursor sampling lag.** The mitigation (rearm the leave timer when ignoring a leave) means a real leave is collapsed at most ~280 ms later than the raw event — same as the AC-3 budget. No additional risk.
- **Touch / tablet input.** Not exercised by curby today; enter/leave semantics are mouse-only. If a touch path is added later it will need its own commit/cancel rules.
- **`QTimer` precision under heavy paint load.** The 50 ms glow tick (`src/dock_widget.py:116-118`) is already running; adding two more single-shot timers per puck is negligible. Worst-case timer slop on macOS is ~10 ms, well inside AC margins.
- **Test determinism.** The integration test uses `QTest.qWait` which is wall-clock; allow a small slack (e.g. assert collapse fires within `[280, 400]` ms after the leave). The pure-logic test has no such slack — it drives the decision table directly.
