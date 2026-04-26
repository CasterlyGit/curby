# Research — issue #13: dock puck hover stability

> Reads: EXPLORE.md
> Generated: 2026-04-26

## Resolved

- **Q1: Why does hovering "sometimes" not show the panel, and why does the panel collapse with the cursor still inside?**
  A: Two distinct mechanisms, both rooted in Qt's parent/child mouse-event propagation:

  1. **Parent gets `leaveEvent` when cursor moves onto a child button.** Qt sends `Leave` to the parent and `Enter` to the topmost child whenever a child widget is "under" the cursor. The puck's chrome buttons (`_pause_btn`, `_amend_btn`, etc.) are direct children of the puck and have no `WA_TransparentForMouseEvents`. So as soon as the user crosses from the panel background onto a button, `DockedTaskPuck.leaveEvent` fires → `_set_expanded(False)` → buttons hidden + widget shrunk → cursor now over the bare icon → `enterEvent` → expand again → cursor over a button → leave → … flicker storm. Evidence: `src/dock_widget.py:148-162` (no geometry check on leave), `src/dock_widget.py:177-189` (buttons created as direct children with no mouse-event-transparency), `src/dock_widget.py:208-212` (buttons re-shown on every expand). This is the dominant cause of AC-2 and AC-4 failures.
  2. **Resize races the cursor on collapse.** `_set_expanded` calls `setGeometry` synchronously and the widget grows/shrinks leftward from the icon (`src/dock_widget.py:223-226`). On collapse the new width is 56 px; if the cursor was anywhere in the panel area it is now outside the new widget bounds. Qt then delivers no further `enterEvent` until the cursor moves again, so a cursor that *was* hovering can end up "stuck outside" until the user wiggles. This is the main cause of "sometimes the panel doesn't reliably show" after a near-miss / re-entry.

  The `enterEvent` path itself is not broken — when the cursor genuinely lands on the icon for the first time the panel does open. Reports of "appears with a delay" are most likely the user's first cursor sample landing on a screen edge where Qt's hit-testing on a translucent frameless window is fuzzy; harder to confirm without instrumentation, see Remaining unknowns.

- **Q2: AC-1's 200 ms threshold — budget or intentional debounce?**
  A: **Latency budget**, not a hold time. Plain reading: a deliberate hover (anything ≥ 200 ms) must result in the panel showing. The implementation may include a small enter debounce (≤ ~50–100 ms) to filter accidental fly-overs, but it must not push total latency past 200 ms. This is consistent with macOS dock-style behavior and with AC-4's "no flicker near the boundary".

- **Q3: Single resized widget vs. separate panel widget vs. transparent region?**
  A: **Keep the single resized widget**, fix the symptoms with: (a) hover-state debounce timers on enter and leave, (b) on `leaveEvent`, verify against `QCursor.pos()` whether the cursor is still inside the widget's screen rect — if yes, ignore the leave and arm a re-check timer, (c) make the chrome buttons stop "stealing" leave events from the parent, either by setting `WA_TransparentForMouseEvents` on label children and treating button hover as still-inside (intercept the parent's leave when `childAt(pos)` is one of the chrome widgets), or by routing all hover decisions through a global-cursor-vs-`self.geometry()` check.

  Rationale for *not* splitting into two windows or polling globally:
  - Two Qt windows mean two separate NSWindows on macOS, two `make_always_visible` calls, more focus-stealing risk, and a brand-new bug surface for screen-edge / DPI snapping. The current single-widget shape works *visually* — only the hit-testing logic needs to change.
  - A global cursor-polling timer on the puck is feasible (mirrors the `VoiceIndicator` 30 fps tick) but is heavier than necessary. Use it only if the leave-checks-cursor approach proves insufficient on macOS.

- **Q4: AC-3 ~300 ms collapse delay — symmetric debounce required?**
  A: Yes, **symmetric but asymmetric in length**. Concretely:
  - Leave timer: **~250–300 ms** (single-shot `QTimer`, cancelled by re-entry). Satisfies AC-3.
  - Enter timer: **~50–100 ms** (single-shot, cancelled by leave). Filters fly-by enters without violating AC-1's 200 ms budget. Setting it any higher conflicts with AC-1.

  Both timers are member-scoped on the puck so they can be cancelled cleanly on hide/destroy and on the `_is_amending` early-return.

- **Q7: Click-pin in this issue?**
  A: No — explicitly listed as out of scope in the issue body. Do not implement; do not even thread the hooks for it.

## Constraints to honor

- **`_set_expanded(self, on, animate=True)` interface.** `set_amending(True)` calls `_set_expanded(True)` to force-open the panel when amend recording starts (`src/dock_widget.py:142-143`). The new debounce path must *not* delay or queue this programmatic expand — keep an immediate-open code path.
- **`leaveEvent` amend-mode early-return.** While `_is_amending` is True the puck must stay open regardless of cursor (`src/dock_widget.py:155-156`). Preserve this carve-out as the first check inside any new leave-handling logic.
- **`auto_dismiss` semantics.** A done/error/cancelled puck that the user has hovered then left must auto-dismiss 120 ms later (`src/dock_widget.py:158-161`). The new debounce design must still emit `auto_dismiss` exactly once per real leave (and not every time the leave timer is cancelled+rearmed). Tie it to the *committed* collapse, not the raw leave event.
- **`TaskManager._relayout` only moves collapsed pucks.** `t.puck.width() == COLLAPSED_W` guard at `src/task_manager.py:157`. Don't break this — moving an expanded puck while the user is hovering is itself a flicker source. Worth re-asserting in tests.
- **No new runtime deps, no Poetry/uv.** `requirements.txt` + `pip` only (per EXPLORE.md). `pytest-qt` is already declared but currently unused — using it for new tests is allowed; introducing anything else is not.
- **Frameless overlay flag set.** `WindowDoesNotAcceptFocus | Tool | FramelessWindowHint | WindowStaysOnTopHint` plus `WA_TranslucentBackground` and `WA_ShowWithoutActivating` (`src/dock_widget.py:92-99`). Mouse tracking on the puck currently relies on Qt's default enter/leave, which *does* work with these flags (the existing implementation does fire enter/leave — just unreliably under the boundary conditions above).
- **macOS NSStatusWindowLevel pinning.** `make_always_visible` is called *after* `show()` on every puck (`src/task_manager.py:131-134`). Any new child-widget tricks (e.g. an extra panel sub-window) would multiply this surface; keep it single-window.

## Prior art in this repo

- `src/voice_indicator.py:52` — uses `WA_TransparentForMouseEvents` so the indicator is fully click-through. The puck *can't* use this on the whole widget (it needs enter/leave), but it's the right attribute to set on the static label children (`_title_label`, `_status_label`) so they cannot trigger parent leaves. Buttons must remain clickable, so for them use a different approach (parent intercepts and verifies via `childAt(pos)` or global geometry check).
- `src/dock_widget.py:116-118` — existing 50 ms `QTimer` for the glow tick. Same `QTimer(self)` + `timeout.connect` + `start(ms)` pattern is the right shape for the hover debounce timers (use `singleShot`-style by `start()`+`stop()` on a non-repeating member timer, or `QTimer.singleShot` if no cancellation needed — but cancellation IS needed here).
- `src/task_manager.py:20-23` and `src/app.py:29-38` — `_TaskBridge` / `_Bridge` cross-thread marshalling. **Not relevant**: hover is fully main-thread; do not introduce a thread or a cursor-tracker subscription unless the global-polling fallback is needed.
- `tests/test_agentic_flow.py:34-71` — `@pytest.mark.parametrize` table style for pure-logic units. The new hover state machine (enter/leave + elapsed → expand/collapse decisions) is a perfect fit for this style. Lift the timer logic into a small pure class so it can be table-tested with synthetic timestamps — no `QApplication` needed for those cases.
- `tests/test_integration.py:35-54` — instantiates a real `QApplication` and calls widget methods directly. Same pattern works for a Qt-level puck test (instantiate `DockedTaskPuck`, call `enterEvent(None)` / `leaveEvent(None)`, then `QApplication.processEvents()` and `time.sleep` or `QTest.qWait` to advance timers). No `qtbot` needed unless we want `waitSignal` ergonomics.
- `tests/fixtures/fake_claude.py` — irrelevant to this issue (subprocess fixture). Mention only to confirm: no new fixtures are needed; the puck is in-process.

## External references

- None used. Qt's parent-child enter/leave behavior is documented (QEvent::Enter / QEvent::Leave: "the topmost widget under the cursor"), and we relied on local source inspection rather than fetching docs. If during design we want to confirm the macOS-specific NSStatusWindowLevel ↔ Qt mouse-tracking interaction, fetch Qt's QtMacExtras / cocoa-platform notes at that point — not needed for this stage.

## Remaining unknowns (for design to handle)

- **Does NSStatusWindowLevel + `WA_TranslucentBackground` actually drop enter/leave events on macOS?** Couldn't verify headlessly. Two-branch design recommendation: the primary fix is the parent-child / debounce work, which doesn't depend on this. If after that fix AC-1 still fails for "first hover" cases, fall back to a global-cursor polling timer driven off the existing `CursorTracker` (extend `app.py` to also feed `TaskManager`, which then dispatches to each puck).
- **Whether the chrome buttons can adopt `WA_TransparentForMouseEvents` selectively.** Setting it makes them visually present but unclickable — wrong for `pause`/`cancel`/`amend`/`dismiss`. So the fix on the button side is *not* attribute-based: it has to be either (a) parent intercepts `leaveEvent` and checks `self.rect().contains(self.mapFromGlobal(QCursor.pos()))` before committing, or (b) install an event filter that swallows the parent's Leave when the cursor is moving onto a known-child button. Pick one in design; (a) is simpler and almost certainly sufficient.
- **Should the `auto_dismiss` 120 ms delay be folded into the new ~300 ms leave debounce, or stay separate?** Simpler to keep separate: leave-debounce gates the *collapse*; once collapse commits, fire `auto_dismiss` 120 ms later as today. Design call.
- **`pytest-qt` (`qtbot`) vs raw `QApplication` for the new Qt-level test.** EXPLORE.md flagged this. Recommendation: pure-logic hover state machine → raw `pytest.mark.parametrize`, no Qt at all. Qt integration test for `DockedTaskPuck` itself → raw `QApplication` to match the existing `test_buddy_window_positioning` pattern. Reserve `qtbot` for if/when we need `waitSignal`. Final call: design.
- **Multi-monitor / DPI.** `TaskManager._relayout` anchors only to `QApplication.primaryScreen().availableGeometry()` (`src/task_manager.py:148-156`), so the puck never crosses screens. Cursor leaving the primary screen is just a normal `leaveEvent`. Treat as out of scope; one-line note in design that this is intentional.
