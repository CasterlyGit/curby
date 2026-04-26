# Requirements — Dock puck hover reliably shows and holds the side panel

> Source: https://github.com/CasterlyGit/curby/issues/13
> Generated: 2026-04-26

## Problem

Hovering on a `DockedTaskPuck` on the right edge of the screen does not reliably expand the side panel: the panel sometimes fails to appear, appears with extra latency, or collapses while the cursor is still inside the puck or its expanded chrome. The root cause (per RESEARCH.md) is Qt parent/child mouse-event propagation — the puck's child buttons steal `Leave` events from the parent — combined with a synchronous resize on collapse that races the cursor. The user-visible result is a puck that flickers near boundaries and that can leave the cursor "stuck outside" until they wiggle it.

## Users & contexts

- **Primary user**: the developer running curby locally, hovering the right-edge dock to inspect a running agentic-flow task (pause / amend / cancel / dismiss). They expect hover to be a deliberate, frictionless gesture.
- **Other affected**:
  - The `set_amending(True)` path (`src/dock_widget.py:142-143`), which programmatically forces the panel open during amend recording — must not be slowed or blocked by new debounce logic.
  - The `auto_dismiss` flow for done/error/cancelled pucks (`src/dock_widget.py:158-161`) — must still fire exactly once per real leave.
  - `TaskManager._relayout` (`src/task_manager.py:157`), which only repositions collapsed pucks — its invariant must hold during the fix.

## Acceptance criteria

- [ ] AC-1: A deliberate hover on a `DockedTaskPuck` (cursor held over the collapsed icon for ≥ 200 ms) results in `_set_expanded(True)` being committed and the side panel visible. Total enter-to-visible latency ≤ 200 ms.
- [ ] AC-2: While `QCursor.pos()` is anywhere inside the puck's current screen geometry — including over any chrome child widget (`_pause_btn`, `_amend_btn`, `_cancel_btn`, `_dismiss_btn`, `_title_label`, `_status_label`) or the expanded panel background — the puck remains expanded. A child-widget `Enter`/parent `Leave` pair on its own MUST NOT cause `_set_expanded(False)`.
- [ ] AC-3: When the cursor leaves both the puck rect and the side panel rect and stays outside, `_set_expanded(False)` commits within ~300 ms (target window: 250–350 ms). Re-entering the rect before commit cancels the pending collapse.
- [ ] AC-4: No flicker or open/close storms when the cursor moves along the puck/panel boundary or transitions between the icon and a chrome button: across a 2-second sweep along any edge, `_set_expanded` transitions ≤ 1 in each direction.
- [ ] AC-5: `set_amending(True)` opens the panel immediately (no enter-debounce delay) and the panel stays open for the full duration `_is_amending` is True regardless of cursor position, preserving the early-return at `src/dock_widget.py:155-156`.
- [ ] AC-6: For done/error/cancelled pucks, `auto_dismiss` is emitted exactly once per real user-initiated leave — tied to the *committed* collapse, not to raw `leaveEvent` calls or to cancelled+rearmed debounce timers (`src/dock_widget.py:158-161`).
- [ ] AC-7: Hover state-machine logic is covered by deterministic tests: a pure-logic table test (no `QApplication`) for the enter/leave + elapsed-time → expand/collapse decisions, and at least one `QApplication`-level integration test on `DockedTaskPuck` driving `enterEvent` / `leaveEvent` and asserting AC-2 and AC-3 with `QTest.qWait` (matches the `tests/test_integration.py:35-54` pattern; no new runtime deps).

## Out of scope

- Animation polish beyond removing the boundary flicker (no new easing curves, no fade-in/out tuning).
- Click-to-pin: panel staying open after a click is a future ticket.
- Splitting the puck into two top-level windows or adding a separate panel `NSWindow` — RESEARCH.md ruled this out.
- Multi-monitor / cross-screen hover behavior — `TaskManager._relayout` already anchors to the primary screen.
- Refactoring `_set_expanded` away from a single resized widget; folding `auto_dismiss` into the leave debounce timer (intentionally kept separate per RESEARCH.md).
- Introducing new runtime dependencies, Poetry, or uv (must remain `requirements.txt` + pip).

## Open questions

- Which of the two interception strategies should design pick: (a) parent `leaveEvent` verifies `self.rect().contains(self.mapFromGlobal(QCursor.pos()))` before committing collapse, or (b) an event filter that swallows parent `Leave` when the cursor is moving onto a known child? RESEARCH.md leans (a) as simpler and likely sufficient.
- Final debounce constants: enter timer in [50, 100] ms and leave timer in [250, 300] ms — design must pick concrete values that satisfy AC-1 (≤ 200 ms total) and AC-3 (~300 ms collapse).
- If after the parent-child fix AC-1 still fails on macOS for the *first* hover (NSStatusWindowLevel + `WA_TranslucentBackground` possibly dropping initial enter events), do we extend the existing `CursorTracker` in `app.py` to feed per-puck global cursor checks as a fallback? Decide whether this fallback ships in the same change or is gated behind a follow-up.
- `pytest-qt` (`qtbot`) vs raw `QApplication` for the integration test — RESEARCH.md recommends raw `QApplication`; design should confirm and document.
