# Design — dock puck hover stability + cross-app hover, dock collapse, completion indicator

> Reads: REQUIREMENTS.md (acceptance criteria are the contract)
> Generated: 2026-04-26

## Approach

Three small, mostly-orthogonal changes layered onto the existing puck:

1. **Cross-app hover (AC-5)**: stop relying on Qt's `enterEvent` / `leaveEvent` exclusively. Add a global cursor router on `TaskManager` that consumes positions from the existing `CursorTracker` and dispatches per-puck enter/leave to each puck's `HoverDebouncer` — Qt's events stay as a redundant in-process source. Belt-and-braces with a one-line macOS shim (`setAcceptsMouseMovedEvents_(True)`) so the NSWindow is also willing to deliver tracking events when the python app isn't foreground.
2. **Dock collapse / restore (AC-6)**: a single small chevron widget owned by `TaskManager`, pinned just above the top puck. Click flips `TaskManager._collapsed_all`; the manager hides/shows the puck list. Spawning a new task auto-restores (no "where did my new task go").
3. **Completion indicator (AC-7)**: emit terminal state from the `result` stream-json event the moment it arrives, instead of waiting for the subprocess to exit. The pip already renders distinct visuals per state — the bug is that state stays `"running"` until `proc.wait()` returns, which can lag the visible "done" message by seconds.

Hover stability for AC-1..AC-4 is **already implemented on this branch** (`HoverDebouncer` + `_cursor_outside_self` predicate + `WA_TransparentForMouseEvents` on labels in `src/dock_widget.py`). This design preserves that work; it does not redo it. New tests (per TEST_PLAN, next stage) will lock the behavior in.

Alternatives considered: splitting the puck into two windows for proper hover bounds (rejected by RESEARCH for NSWindow surface multiplication); per-puck chevron (rejected — clutter, semantics don't fit per-puck); a header "control puck" reusing `DockedTaskPuck` shape (rejected — too much code reuse for too little gain, and the chevron's interaction model is different).

## Components touched

| File / module | Change |
|---|---|
| `src/dock_widget.py` | Buttons gain mouse-leave-pass-through behavior. The `_cursor_outside_self` predicate is already in place; a new public method `update_hover_from_global(x, y)` lets the global router drive enter/leave without touching Qt's event path. The chrome buttons get an event filter so a Leave delivered to the parent while the cursor is on a child button no longer collapses (parent geometry-checks; the existing `should_commit_collapse` already swallows the false leave). No paint changes for AC-7 — the pip's `done`/`error`/`cancelled` paths already exist; the bug is upstream. |
| `src/task_manager.py` | New `set_cursor(x, y)` slot consumes global cursor and dispatches per-puck enter/leave edge transitions (track per-puck `inside: bool`). New `toggle_collapsed_all()` + `_collapsed_all: bool`. New `_chevron: DockChevron` instance, created in `__init__`, positioned in `_relayout`, hidden if no tasks. Spawning a task auto-clears `_collapsed_all`. The `t.puck.width() == COLLAPSED_W` guard on `_relayout` is preserved. |
| `src/agent_runner.py` | New required callback `on_state: Callable[[str], None]`. In `_read_loop`, derive terminal state from the same event we already inspect for status (a new `_state_from_event(obj)` mapper) and emit immediately when seen. `_handle_done` keeps emitting based on `rc` as the final source of truth, but no longer races the visible spinner. New helper guards: don't override `cancelled` from rc-based fallback. |
| `src/app.py` | Wire `CursorTracker.on_move` to also call `TaskManager.set_cursor` (in addition to the existing voice indicator follow). One added line in `_on_cursor_move`. |
| `src/mac_window.py` | One-line addition: `nswindow.setAcceptsMouseMovedEvents_(True)` so NSWindow tracking areas deliver enter/leave events even when the python app is not the active app. Defense-in-depth alongside the global router. |
| `src/task_manager.py` (Task class) | `Task.__init__` wires `runner = AgentRunner(..., on_state=self.bridge.state_changed.emit, ...)`. `_handle_done` adds an early-return when `runner._cancelled` is True so the cancel path's "cancelled" status is not stomped by an "error" derived from rc. |

## New files

- `src/dock_chevron.py` — `DockChevron(QWidget)`: small (~32×20 px) frameless, translucent, always-on-top button-like widget. Renders a chevron glyph (down arrow when expanded, up arrow when collapsed). Emits `clicked` on press. Same overlay flags + `make_always_visible` treatment as `DockedTaskPuck`. No state of its own beyond visual orientation; `TaskManager` owns the `collapsed_all` truth.
- `tests/test_dock_hover.py` — covered by TEST_PLAN; listed here so design and test plan agree on the location.

## Data / state

- **`HoverDebouncer`** (already implemented): `enter_ms=80`, `leave_ms=280`, single-shot `QTimer`s, `_committed: bool`, optional `should_commit_collapse: () -> bool` re-check predicate, `force_expand` / `force_collapse` / `cancel_pending` for programmatic overrides (used by `set_amending`). No persisted state.
- **`TaskManager._collapsed_all: bool`** — runtime only, default `False`. Not persisted across restarts (out of scope per REQUIREMENTS).
- **`TaskManager._cursor_inside: dict[Task, bool]`** — per-puck cursor-edge tracking for the global router. Keyed by task identity; cleaned up when a task is removed in `_on_task_finished`.
- **`AgentRunner._terminal_state_emitted: bool`** — guards against re-emission from rc-based fallback when the event-driven path already fired. Internal only.
- No new env vars, no new files written to disk, no schema changes.

## Public API / surface

- `HoverDebouncer.on_enter()` / `on_leave()` / `force_expand()` / `force_collapse()` / `cancel_pending()` — already present; preserved.
- `DockedTaskPuck.update_hover_from_global(x, y)` — new. Computes `self.frameGeometry().contains(QPoint(x, y))`, compares to last state, calls `self._hover.on_enter()` or `self._hover.on_leave()` on edges. Idempotent across repeated calls with the cursor stationary inside or outside.
- `TaskManager.set_cursor(x: int, y: int)` — new slot. Iterates tasks, drives `update_hover_from_global` for each. Cheap (n ≤ ~5 pucks in practice).
- `TaskManager.toggle_collapsed_all()` — new. Flips `_collapsed_all`; hides/shows pucks accordingly; updates chevron orientation; preserves stacking order on restore (uses `_relayout`).
- `AgentRunner(..., on_state: Callable[[str], None])` — new required ctor arg. State strings are the same union the puck already understands: `"running" | "paused" | "done" | "error" | "cancelled"`.
- `_state_from_event(obj: dict) -> Optional[str]` — new pure helper next to `_status_from_event`. Returns `"done"` for `result.success`, `"error"` for any other `result` subtype, `None` otherwise. Tested table-driven alongside `_status_from_event`.
- No new hotkeys, no new CLI flags. The chevron click is the only new user-facing interaction.

## Failure modes

| Failure | How we detect | What we do |
|---|---|---|
| `pynput` cursor listener fails to start (e.g., macOS accessibility permission revoked) | `CursorTracker.start()` raises or silently never delivers events | Fall back to Qt's enter/leave (still wired). Cross-app hover degrades but in-app hover keeps working. Log once on startup if the listener thread isn't alive after 1s. |
| Global cursor reports stale coords during heavy load | Per-puck edge state lags by one tick | Acceptable: 50–100 ms lag is well under AC-1's 200 ms budget; HoverDebouncer's enter timer (80 ms) absorbs jitter. |
| Both Qt enter/leave AND global router fire on the same edge | `HoverDebouncer.on_enter` would re-arm enter timer | The state-machine guards (`if self._committed: return`) make repeated `on_enter` calls cheap; the second call just restarts an 80 ms timer that completes the same expand. No flicker. The integration test in TEST_PLAN counts `_set_expanded` transitions to verify ≤ 2 per cycle. |
| Result event arrives but proc never exits (rare hang in Claude CLI) | Visible: spinner stops, status reads result text, but `_on_runner_done` never fires | State transitions correctly via on_state. The puck shows "done" / "error" exactly as the user expects. Cleanup happens whenever proc.wait eventually returns; no UI dependency on it. |
| Result event never arrives but proc exits cleanly with rc=0 | `_terminal_state_emitted` is False; `_handle_done` emits state based on rc | Existing behavior preserved — same as today. |
| User clicks chevron mid-spawn | `toggle_collapsed_all` runs while a `spawn` is in flight; race on `_collapsed_all` | All toggling is on the Qt main thread (chevron click is a Qt signal; `spawn` is called from the main thread from voice/text submit handlers). No race. |
| Chevron position collides with the voice indicator | Visual overlap | Anchor chevron to top-of-stack at `right_x - chevron_w, top_y - chevron_h - 4`. Voice indicator follows the cursor; collision is transient and the chevron's `WindowStaysOnTopHint` keeps it visible. Acceptable. |
| `setAcceptsMouseMovedEvents_` not available on PyObjC binding (very unlikely) | `AttributeError` in the existing try/except in `make_always_visible` | Logged, swallowed; global router still works. |
| Collapsed puck is `_is_amending` when user toggles collapse-all | Hiding an amending puck would orphan the recording | `toggle_collapsed_all` skips pucks where `_is_amending` is True (defense — extremely narrow window since amend is push-to-talk). |

## Alternatives considered

- **Two windows per puck (icon + panel) for proper hit-testing.** Rejected by research: doubles NSWindow surface, multiplies `make_always_visible` calls, introduces edge/DPI snapping bugs. Single resized widget + child-leave swallowing is sufficient.
- **Polling-only hover (drop Qt enter/leave entirely).** Simpler in some ways, but pynput accessibility permission failures would silently break hover. Keeping Qt enter/leave as a fallback is one boolean check; cost is near-zero.
- **`auto_dismiss` folded into the leave debounce as a single 400 ms timer.** Rejected: research called this out; keeping the two timers separate keeps semantics clear (leave-debounce gates the *collapse*, auto-dismiss gates the *self-removal*). The branch's existing `_commit_collapse` already structures it this way.
- **Per-puck chevron** for AC-6. Rejected: collapse-all is a stack-level operation, not a per-task one. Semantics don't fit.
- **Header "control puck"** that reuses `DockedTaskPuck` chrome. Rejected: the chevron's visual is a glyph, not a task icon; reusing the puck class would mean carrying around running/paused/done state that doesn't apply.
- **Adding `state` to `_status_from_event` return signature.** Rejected: muddies a well-tested pure mapper. A separate `_state_from_event` keeps each helper single-purpose.
- **Animating the spinner-to-check transition.** Out of scope per REQUIREMENTS ("animation polish beyond fixing the flicker").

## Risks / known unknowns

- **macOS cross-app mouse delivery without `setAcceptsMouseMovedEvents_`.** RESEARCH flagged this as unverifiable headlessly. The global router (pynput-based) does not depend on it, so AC-5 is met regardless. The NSWindow flag is defense-in-depth; if it's a no-op on this Qt/PyObjC combination, behavior is unchanged.
- **`pynput` accessibility permission**. Already a dependency of the voice indicator; if the user has granted permission once (which they must to use curby at all), the global cursor stream is available. If permission is revoked at runtime, hover degrades to in-app-only — same as today.
- **Open-question: auto-restore on new spawn vs persistent collapse.** Picked auto-restore (avoids "where did my new task go"). If users complain, flipping to "stay collapsed; chevron pulses" is a small follow-up, not a rewrite.
- **Tracking-area resize lag**. When `_set_expanded` resizes the widget, Qt recomputes its tracking areas. On a fast cursor sweep across the boundary, the global router covers the gap; Qt's lag is invisible.
- **Multi-monitor**. Out of scope per REQUIREMENTS — `_relayout` anchors to primary screen; chevron sits there too.
- **Test coverage for cross-app hover (AC-5)**. Headless tests can't simulate "another app is foreground." Verification is the global-router unit test plus a manual test step in TEST_PLAN ("focus Chrome, hover puck"). The deterministic part — that a global cursor sample at puck-coords drives the same expand path — is fully unit-testable.
