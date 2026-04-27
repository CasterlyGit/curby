# Requirements — Dock puck hover stability, focus-independent hover, collapse-all, and task completion indicator

> Source: issue-13 (inline + comments)
> Generated: 2026-04-27

## Problem

The dock task puck has three related reliability failures. First, hover-to-expand only works when the Python app is the OS-focused window; switching focus to another app (e.g. a browser) makes hover silently stop working. Second, even when the app is focused, the side panel can flicker, refuse to open, or collapse while the cursor is still inside it. Third, when an agent task finishes, the puck's loading circle never updates to reflect completion — it keeps spinning because the stdout pipe isn't closed when grandchild processes outlive the top-level `claude` process, so `on_done` is never called. The user also wants a one-click way to collapse all visible pucks out of the way and restore them.

## Users & contexts

- **Primary user**: Developer running `curby` while other apps (browser, IDE, terminal) hold OS focus; monitors background agent tasks from the dock without switching windows.
- **Other affected**: Anyone watching task state — the stuck loading circle means there's no reliable signal that a task has finished.

## Acceptance criteria

- [ ] AC-1: Hovering a task puck for ≥ 200 ms expands the side panel regardless of which application currently holds OS focus.
- [ ] AC-2: While the cursor is anywhere inside the puck OR the side panel, the panel stays open.
- [ ] AC-3: Moving the cursor outside both the puck and the panel collapses the panel within ~300 ms.
- [ ] AC-4: No panel flicker or open/close cycles occur when the cursor moves near the puck/panel boundary.
- [ ] AC-5: A persistent floating arrow button above the puck stack, when clicked, hides all visible pucks; clicking the same button again restores them to their previous state.
- [ ] AC-6: Within 2 seconds of a task's agent process exiting, the puck's loading circle updates to a visually distinct "completed" state (static indicator, e.g. filled ring or checkmark).
- [ ] AC-7: The completed state persists on the puck until the puck is dismissed or a new task is started on it.

## Out of scope

- Animation polish beyond eliminating flicker.
- Click-to-pin (panel stays open after a click) — future ticket.
- Puck visual redesign beyond the completed-state indicator.
- Per-puck collapse (collapse-all only for now).

## Open questions

- **pynput vs. `acceptsMouseMovedEvents_`**: Research recommends pynput as the primary hover path to avoid Qt's focus dependency. Design must decide whether to also call `acceptsMouseMovedEvents_(True)` in `make_always_visible` (belt-and-suspenders) or rely on pynput alone, and document whether double-fire is harmless via `HoverDebouncer` idempotency.
- **Collapse-all button placement**: exact anchor/offset above the topmost puck so the arrow button does not overlap the puck when it slides in. Design must specify.
- **Stdout-hang fix strategy**: use a companion `proc.wait()` thread that calls `proc.stdout.close()` on exit, or `os.killpg(pgid, SIGTERM)` to reap the entire process group? Design must pick one and handle the race between normal EOF and forced close.
- **Completed-state visual**: what does the loading circle look like in the completed state? Needs a short visual spec or reference before implementation.
