# Integration — dock puck hover stability + cross-app hover, dock collapse, completion indicator

> Stage 7. Reads: REQUIREMENTS.md (ACs), TEST_PLAN.md, DESIGN.md, IMPLEMENTATION.log.
> Verified: 2026-04-26.

## Test runs

- `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q` — **55 passed, 2 skipped** in 14.89 s.
  - 2 skips are the existing `ANTHROPIC_API_KEY`-gated end-to-end tests
    (`test_anthropic_chat_basic`, etc.) — unrelated to this issue.
  - No xfails, no warnings beyond the pre-existing `mss.mss` deprecation
    (out-of-scope module).

## Scope reconciliation

The branch's implementation pre-dates the inbox addendum that grew the issue
from AC-1..AC-4 (hover stability) into AC-1..AC-7 (adds cross-app hover,
collapse-all chevron, completion-indicator emit). REQUIREMENTS.md /
DESIGN.md / TEST_PLAN.md were regenerated to cover the larger scope; the
code was not. Per `IMPLEMENTATION.log` line 5, the implementer flagged
AC-5/AC-6/AC-7 as **out of scope for this stage; follow-up issue**.
This report verifies what was implemented and surfaces the deferred ACs as
Outstanding.

## AC verification

- [x] **AC-1** — *hover ≥ 200 ms expands.* Verified by
      `tests/test_integration.py::test_dock_puck_hover_expands_within_budget`.
      `HoverDebouncer.enter_ms = 80 ms`; the test asserts `_expanded is True`
      and `width() > COLLAPSED_W` after a 200 ms wait.
      Implementation: `src/dock_widget.py:259` (`enterEvent` →
      `HoverDebouncer.on_enter` → `_fire_enter` → `_commit_expand`).
- [x] **AC-2** — *cursor inside puck ∪ panel keeps it open.* Verified by
      `tests/test_integration.py::test_dock_puck_stays_expanded_when_cursor_on_child`.
      Two mechanisms locked:
      (a) static labels carry `WA_TransparentForMouseEvents` so they don't
      generate parent-leave events (`src/dock_widget.py:298`, `:304`);
      (b) `HoverDebouncer._fire_leave` re-arms when
      `should_commit_collapse=puck._cursor_outside_self` returns False
      (`src/dock_widget.py:167`). Cursor-lag/child-stolen-leave handling
      additionally pinned at the unit level by
      `tests/test_agentic_flow.py::test_hover_debouncer_fire_leave_rearms_when_predicate_blocks`.
- [x] **AC-3** — *cursor outside both regions collapses within ~300 ms.*
      Verified by
      `tests/test_integration.py::test_dock_puck_collapses_after_leave_window`
      (`leave_ms = 280 ms`; assertion at 180 ms says still expanded, at
      ~400 ms says collapsed). The `auto_dismiss` 120 ms follow-up "fires
      exactly once per real leave" leg is locked by
      `tests/test_integration.py::test_dock_puck_auto_dismiss_fires_once_per_committed_collapse`.
      `set_amending` interaction (force-expand survives leave; subsequent
      natural leave still collapses normally) covered by
      `tests/test_integration.py::test_dock_puck_set_amending_opens_immediately_and_holds`.
- [x] **AC-4** — *no flicker / open-close storm at the boundary.* Verified
      at the unit level by
      `tests/test_agentic_flow.py::test_hover_debouncer_boundary_sweep_single_transition`
      (canonical sweep `[enter, leave, enter, leave, enter]` produces zero
      `_on_expand` / `_on_collapse` calls until the final committed
      transition; the sweep itself yields 0 transitions, the final commit
      yields 1 — well within the "≤ 2 per cycle" bound). The full decision
      table for the state machine is exhaustively pinned by
      `tests/test_agentic_flow.py::test_hover_debouncer_decision_table`
      (parametrized; covers all on_enter / on_leave / fire_enter /
      fire_leave / force_* edges).
      *Note*: TEST_PLAN.md called for an additional integration-level
      wiggle test
      (`test_dock_puck_boundary_wiggle_bounded_transitions`); it was not
      added. The unit-level boundary-sweep test plus the four integration
      tests above provide equivalent coverage of the contract — the
      additional integration test would be a defense-in-depth duplicate.
      Listed under Outstanding for completeness.
- [ ] **AC-5** — *hover works when another app is foreground.* **Not
      implemented.** No global cursor router on `TaskManager`, no
      `update_hover_from_global` on `DockedTaskPuck`, no
      `setAcceptsMouseMovedEvents_(True)` shim in `src/mac_window.py`
      (grep confirms zero matches across `src/` and `tests/`). The bug
      reproduces today: hover only works when the Python/Qt process is
      foreground.
- [ ] **AC-6** — *dock-collapse chevron.* **Not implemented.** No
      `src/dock_chevron.py`, no `TaskManager.toggle_collapsed_all` /
      `_collapsed_all` (grep confirms zero matches). User cannot collapse
      the puck stack.
- [ ] **AC-7** — *terminal-state pip updates on result event.* **Not
      implemented.** No `AgentRunner(on_state=...)` callback, no
      `_state_from_event` helper (grep confirms zero matches in
      `src/agent_runner.py`). The pip continues to spin until
      `proc.wait()` returns; the bug reported in the inbox addendum
      remains.

## Failure-mode walk (DESIGN.md)

Of the nine failure modes enumerated in DESIGN.md, only the ones tied to
the implemented surface are exercisable today:

| Failure mode | Status |
|---|---|
| Cursor-lag / child-stolen leave (mode 3 — "Both Qt enter/leave AND global router fire") | ✅ HoverDebouncer's `_committed` guard makes `on_enter` idempotent; `_fire_leave` predicate re-arms (`tests/test_agentic_flow.py:615`). |
| `pynput` permission revoked (mode 1) | ⚠️ N/A — global router not implemented; no degradation path because there is no fallback to degrade from. |
| Stale global cursor coords (mode 2) | ⚠️ N/A — global router not implemented. |
| Result event arrives, proc never exits (mode 4) | ❌ Not handled — `on_state` plumbing absent. |
| Result event missing, proc exits rc=0 (mode 5) | ❌ Not handled — `_terminal_state_emitted` guard absent. |
| Chevron toggle race / position collision (modes 6, 7) | ❌ N/A — chevron not implemented. |
| `setAcceptsMouseMovedEvents_` not on PyObjC (mode 8) | ❌ N/A — shim not added. |
| Collapse-all while amending (mode 9) | ❌ N/A — collapse-all not implemented. |

## Outstanding issues

1. **AC-5 / AC-6 / AC-7 not implemented.** Inbox addendum to issue-13
   added three follow-up bugs/features after DESIGN.md was written. The
   implementation log explicitly defers them. Recommend filing a
   follow-up issue (`issue-13-followup`) covering: (a) global cursor
   router + `setAcceptsMouseMovedEvents_(True)` for cross-app hover;
   (b) `DockChevron` + `TaskManager.toggle_collapsed_all`;
   (c) `AgentRunner.on_state` callback driven from `_state_from_event`.
2. **Design/test-plan / implementation drift.** REQUIREMENTS.md and
   DESIGN.md describe ACs 5/6/7 in detail; the code does not implement
   them. If the follow-up is filed, regenerate REQUIREMENTS / DESIGN /
   TEST_PLAN there rather than carrying the drift on this branch.
3. **`test_dock_puck_boundary_wiggle_bounded_transitions` (AC-4
   integration variant) not added.** TEST_PLAN.md called for it; the
   unit-level boundary-sweep test plus the existing AC-1..AC-3
   integration tests cover the contract equivalently. Optional add-on,
   not blocking.
4. **DESIGN.md → implementation deviation already noted in
   `IMPLEMENTATION.log`** (2026-04-26T22:53): the geometry self-check
   landed in `HoverDebouncer._fire_leave` via the
   `should_commit_collapse` predicate rather than in `leaveEvent`
   synthesizing a re-enter. Behavior is equivalent for AC-2 / AC-3 /
   AC-4 and is independently tested. Not a regression; informational
   only.
5. **Pre-existing `mss.mss` `DeprecationWarning`** in
   `src/screen_capture.py:30` — out of scope for issue-13.

## Decision

⚠️ **Ready with caveats.**

The original issue scope (AC-1..AC-4 — hover stability, the actual flicker
and "panel doesn't open / collapses while inside" bugs the user filed) is
implemented, all five integration tests for the dock puck pass, and the
underlying `HoverDebouncer` state machine is exhaustively pinned by a
parametrized decision-table test. The full suite is green
(55 passed / 2 skipped, 14.9 s).

The inbox addendum (AC-5 cross-app hover, AC-6 collapse chevron, AC-7
completion-indicator emit) is **not** implemented; per
`IMPLEMENTATION.log` it is explicitly out of scope for this stage and
should be a follow-up issue. The orchestrator should merge AC-1..AC-4
under issue-13 and open a new issue for the addendum work, rather than
returning this branch to design/implementation for the deferred ACs.
