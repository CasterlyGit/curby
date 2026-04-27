# Requirements — dock puck hover stability + cross-app hover + completion indicator

> Source: GitHub issue #13 — "Hover on the dock puck doesn't reliably show the panel"
> Generated: 2026-04-26

## Problem

Hovering a `DockedTaskPuck` on the right edge does not reliably show the
expanded side panel: the panel sometimes fails to open, opens after a
visible delay, or collapses while the cursor is still inside the puck or
the panel area (flicker storm at the boundary). Two follow-up issues
were added in the most recent comment: (a) hover only works when the
Python/Qt process holds the foreground focus — if Chrome (or any other
app) is focused, hover over the puck does nothing until the user clicks
the Python window first; and (b) when a task finishes, the puck's
loading/spinner indicator does not change to a completed state, so the
user can't tell from the puck alone that the task ended.

## Users & contexts

- **Primary user**: the operator running curby with one or more active
  agent tasks docked on the right edge. They sweep the cursor onto a
  puck to peek at its title/status/buttons without leaving whatever app
  (Chrome, terminal, editor) currently has focus.
- **Other affected**: `TaskManager` (owns the puck list, calls
  `_relayout` and `auto_dismiss`); `set_amending` callers (must still
  force-open the panel without being throttled by hover debounce).

## Acceptance criteria

- [ ] **AC-1**: A deliberate hover on a `DockedTaskPuck` (cursor inside
  its screen rect for ≥ 200 ms) always results in the side panel being
  visible — i.e. `_set_expanded(True)` has committed and chrome buttons
  (`_pause_btn` / `_amend_btn` / `_cancel_btn` / `_dismiss_btn` as
  applicable) are shown. Total enter-to-shown latency stays ≤ 200 ms.
- [ ] **AC-2**: While the cursor is anywhere inside the union of the
  puck's icon region and its expanded panel region, the panel stays
  open. Crossing from the panel background onto a chrome button (which
  is a child widget of the puck) does **not** trigger a collapse — no
  `_set_expanded(False)` fires while the global cursor is still inside
  `self.geometry()`.
- [ ] **AC-3**: After the cursor leaves both regions, the panel
  collapses within ~300 ms (single committed transition, observable as
  one `_set_expanded(False)` call). For pucks in a terminal state
  (done / error / cancelled), the existing `auto_dismiss` 120 ms
  follow-up fires exactly once per real leave.
- [ ] **AC-4**: No flicker / open-close storm at the puck boundary. In
  the integration test that wiggles the cursor across the icon↔panel
  edge, the count of `_set_expanded` transitions is bounded (≤ 2 per
  user-perceived hover-then-leave cycle).
- [ ] **AC-5**: Hover works when another application (e.g. Chrome) is
  the foreground app. Moving the cursor onto a puck while the
  Python/Qt process is **not** focused must still expand the panel,
  without requiring a click on the Python window first. The puck's
  `WindowDoesNotAcceptFocus | WA_ShowWithoutActivating` setup must be
  preserved (no focus-stealing on hover).
- [ ] **AC-6**: A dock-collapse control (e.g. a chevron / dropdown
  arrow rendered on or alongside the dock) lets the user collapse all
  pucks into a single compact affordance. Clicking the same control
  restores the pucks to their normal docked layout. State persists
  while the app is running; no requirement to persist across restarts.
- [ ] **AC-7**: When a task transitions to a terminal state
  (`done` / `error` / `cancelled`), the puck's loading/glow indicator
  visibly updates to a completed state (spinner stops, glow / icon
  reflects success or failure) before any auto-dismiss timer runs.
  After the change, the indicator does not continue animating as if
  the task were still running.

## Out of scope

- Animation polish beyond fixing the flicker (carried over from issue
  body).
- Click-to-pin: the panel staying open after a click is explicitly a
  future ticket (carried over from issue body).
- Persisting the dock-collapsed state across app restarts.
- Multi-monitor / cross-screen puck migration —
  `TaskManager._relayout` already anchors to the primary screen and
  this issue does not change that.
- Replacing the single resized-widget approach with a separate panel
  window (research stage ruled this out).

## Open questions

- **AC-5 mechanism**: is a parent-child / debounce fix alone enough to
  make hover work cross-app on macOS, or is a global cursor-polling
  fallback (extending `CursorTracker` to feed `TaskManager`) required?
  Design must pick one and justify; the research doc flags this as
  unverifiable headlessly.
- **AC-6 placement and shape**: where does the collapse chevron live —
  as a child of each puck, as a separate small always-on-top widget
  managed by `TaskManager`, or as a single header puck above the
  stack? Issue comment is ambiguous ("a dropdow arrow which when
  clicks jsut duciksall tehse pucks"). Design stage to choose; surface
  the choice in the design doc.
- **AC-7 root cause**: is the spinner failing to stop because the
  terminal-state signal isn't reaching the puck, because the glow
  `QTimer` isn't being stopped on terminal transition, or because the
  visual asset for the completed state is missing? Design needs to
  locate the bug in `DockedTaskPuck` / `TaskManager` and decide
  whether the fix is a missing `stop()` call, a missing slot wiring,
  or a new completed-state visual.
- Should the ~300 ms leave debounce and the 120 ms `auto_dismiss`
  delay be merged or kept separate? Research recommends keeping them
  separate; design to confirm.
