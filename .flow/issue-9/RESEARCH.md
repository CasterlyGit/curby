---
name: Research — curby (issue #9)
description: Resolved questions + audit findings for the agentic flow
type: stage-artifact
---

# Research — check the whole agentic flow of the curby puck

> Reads: EXPLORE.md
> Generated: 2026-04-26
> Issue: [#9](https://github.com/CasterlyGit/curby/issues/9)

## Resolved

- **Q: What does "check" mean — tests, runtime trace, or audit doc?**
  A: All three, but with a clear primary: **add a deterministic, headless test harness that pins the agentic flow so future regressions are caught**, and fix the discrete bugs the audit surfaces while we're here. The label is `feature`, the issue is empty, and `inbox/check the whole agentic flow of the curby puck.md` only says "user voice is registered then what? flow is:" — that reads as "I want this end-to-end pipeline to be verifiable, not just hand-traced." A static audit doc alone wouldn't be a "feature."

- **Q: Reproducible bug being chased, or clean audit?**
  A: Clean audit. No log fragment, no failing-test artifact, no bug-report inbox file. The audit nonetheless surfaced two real correctness bugs (see "Audit findings" below) that the deliverable should fix in-scope.

- **Q: Scope — visual puck only, or full puck-as-task lifecycle?**
  A: Full lifecycle. The inbox file's "user voice is registered then what?" rules out a UI-only scope. Coverage spans `PTTListener` → `record_until_stop` → `TaskManager.spawn` → `AgentRunner._read_loop` (incl. pause/resume/cancel/amend) → `DockedTaskPuck` state transitions.

- **Q: Is `AgentRunner.amend()` after the task is `done` honored?**
  A: **No — silent bug.** `_read_loop` only drains `_pending_amends` at the bottom of one execution of itself (`agent_runner.py:117–125`). After the subprocess exits and `on_done(rc)` fires, no thread is left to drain the queue. A subsequent `amend("…")` appends to `_pending_amends` and never re-spawns. The README explicitly promises amend works in `done / error` states ("only **amend** + **dismiss** remain") and `dock_widget.py:_layout_expanded` exposes the amend button in those states, so the contract is broken. Evidence: `agent_runner.py:117–125`, `agent_runner.py:201–209`, `README.md:53–58`, `dock_widget.py:_layout_expanded` ordering for non-running states.

- **Q: Does the voice indicator transition correctly when recording self-terminates at `MAX_SECONDS`?**
  A: **No — UX bug.** `_stop_recording` (which sets `voice.set_state("processing")`) is only invoked from `_on_ptt_toggled` and `_on_amend_stop` (`app.py:139–142`, `app.py:154–156`). When `record_until_stop` exits because it hit `MAX_SECONDS = 30` (`voice_io.py:30`), the recording thread proceeds straight to transcription, leaving the indicator stuck in `listening` for the duration of Google STT round-trip. Then `_on_transcription` flips it to `idle`. User sees no "processing" sweep on the timeout path.

- **Q: Concurrency — is the `AgentRunner` amend / cancel ordering safe?**
  A: Yes. `cancel()` takes `_lock`, sets `_cancelled = True`, and clears `_pending_amends` (`agent_runner.py:171–174`). `_read_loop` pops under the same lock, then checks `not self._cancelled` before re-spawning (`agent_runner.py:117–123`). Worst case is "popped prompt is dropped after concurrent cancel" — that's the correct semantics for "user cancelled."

- **Q: Concurrency — is `_record_target` safe to read across threads without a lock?**
  A: Yes, by invariant. `_start_recording` early-returns if a recording thread is already alive (`app.py:96–101`), so `_record_target` only changes when no recorder thread exists. The recorder thread reads it once at the bottom (`app.py:121`); no concurrent writer.

- **Q: PTT toggle re-arm — any way to wedge "stuck on" or "won't fire"?**
  A: No, the chord-subset model is robust. `_armed` flips false on first full-chord press and only flips true again when the chord is no longer fully held (`ptt_listener.py:_handle_release`). Tested mentally for: tap-tap, hold-mash, release-one-then-other. All re-arm correctly.

- **Q: What happens if user taps the global PTT chord during a per-task amend recording?**
  A: Nothing. `_on_ptt_toggled` early-returns when `_record_target is not None` (`app.py:137–140`). The amend recording continues; user must use the puck's "send" button (or wait for `MAX_SECONDS`) to terminate it. Reasonable; undocumented.

- **Q: Failure-mode visibility — mic-denied, `claude` not on PATH, STT offline, subprocess pre-stream crash, `MAX_SECONDS` timeout.**
  A: Mixed.
  - **Mic denied** during global PTT: console-only (`[ptt] mic unavailable: …`); voice indicator falls back to `idle`. No visual surface.
  - **Mic denied** during amend: status text on the puck (`amend cancelled: …`); good.
  - **`claude` not on PATH**: caught at `Popen` (`agent_runner.py:108–111`), surfaces as `claude not found: …` in the puck status; pip turns red. Good.
  - **STT offline**: `RuntimeError(f"speech service unreachable: {e}")` → console-only for global PTT, puck status for amend. Same gap as mic-denied for global PTT.
  - **Subprocess crashes before first stream-json line**: `_read_loop` exits, `on_done(rc)` fires, state → `error`. Status stays at `"starting…"`. Pip turns red. User sees state but not why.
  - **`MAX_SECONDS` timeout** (no user-stop): see prior question — visual stays in `listening` until STT returns. Minor.

- **Q: Does the `Quartz` screen-recording preflight in `main.py` reflect the active flow?**
  A: No. The active flow never grabs the screen; `mss` / `screen_capture.py` are imported only by the dormant guidance pipeline (`ghost_cursor.py`, etc.). The preflight + the README's "Screen Recording permission required" line are leftover from the pre-pivot era.

- **Q: Does the README's "How to use" / "How to talk to it" match the code?**
  A: Mostly yes. Discrepancies: (a) the README implies tap-tap-toggle is the only path, but `Ctrl+.` text input exists too (it IS documented further down — fine); (b) the Screen Recording permission claim above; (c) README says PTT chord is `Ctrl+Space` (matches `ptt_listener.py`'s default trigger); (d) `app.py`'s top-of-file docstring says "Hold Ctrl+Shift+Space" — **stale docstring** from a prior trigger; the actual default is `Ctrl+Space`. Worth fixing in this pass.

## Audit findings (for design to act on)

**Bugs — fix in this iteration:**
- **B1.** `AgentRunner.amend()` after `on_done` is a silent no-op. The amend queue is only drained at the bottom of a `_read_loop` iteration, so a `done / error / cancelled` task can never honor an amend. Fix: detect "no live `_read_loop`" at amend time and start a fresh `_spawn(prompt, resume=True)` directly. Guard against double-spawn by reusing the existing `_lock`.
- **B2.** Voice indicator stuck in `listening` on `MAX_SECONDS` self-termination. Fix: have `voice_io.record_until_stop` (or its caller) signal "processing started" when it exits the recording loop, regardless of cause. Cleanest: a `on_recording_stopped` callback into `record_until_stop` that fires once before STT runs, wired in `app.py._start_recording` to `voice.set_state("processing")` on the main thread.

**UX gaps — fix in this iteration:**
- **U1.** Global-PTT mic / STT errors are console-only. Surface them on the voice indicator (e.g. brief red flash + revert to idle), or at minimum a stderr-only warning is fine if we add a regression test that asserts the error is at least raised through the bridge. Minimal fix: add a transient `error` state to `VoiceIndicator` that auto-reverts to `idle` after ~1.5 s, and route `transcription_error` for the global-PTT case through it.
- **U2.** `main.py` preflights Screen Recording for a flow that never captures the screen. Drop the preflight and remove the README claim.

**Stale doc — fix in this iteration:**
- **D1.** `app.py` top-of-file docstring still says "Hold Ctrl+Shift+Space"; the active default is `Ctrl+Space`. Update.
- **D2.** README "Prereqs" claims Screen Recording permission is required. Remove; keep Accessibility (pynput needs it) and Microphone.

**Verified safe — no action needed:**
- Amend / cancel ordering in `AgentRunner`.
- `_record_target` cross-thread visibility.
- PTT re-arm under all tap patterns.
- Per-task amend during pause: queue is honored on resume → exit → drain.

**Test gap — primary deliverable:**
- **T1.** Zero existing tests cover the agentic flow. The deliverable should add a headless `pytest` module that pins:
  - `_status_from_event` mapping table (table test, no I/O).
  - `AgentRunner` lifecycle with a fake `claude` subprocess (echo a known stream-json sequence, verify `on_status` / `on_done` order).
  - `AgentRunner.amend()` after `on_done` re-spawns (the B1 fix).
  - `AgentRunner.cancel()` while amend queued discards the queue and SIGTERMs.
  - `PTTListener` toggle re-arm via simulated key events (or refactor `_handle_press/_release` to be directly callable so we don't need a real `pynput.Listener`).

  Skip Qt-widget rendering tests; the existing harness is `pytest-qt` but the puck visuals aren't the audit target. Skip `voice_io` mic/STT integration — that's an external dependency.

## Constraints to honor

- **Subprocess contract:** must keep `claude -p --dangerously-skip-permissions --output-format stream-json --verbose <prompt>` (and `--continue` on resume) and the `start_new_session=True` Popen flag (process-group SIGSTOP/SIGCONT/SIGTERM all depend on it). Don't change the workdir layout `~/curby-tasks/<ts>-<slug>/` — users may already have task dirs they expect.
- **Bridge pattern:** all reader-thread → Qt main-thread crossings must stay `pyqtSignal`-based. New callbacks added to `record_until_stop` must marshal through `app._Bridge`.
- **Public surface of `AgentRunner`:** `start / pause / resume / cancel / amend / is_running / is_paused / workdir / on_event / on_status / on_done`. Tests should pin these names; new methods are fine, renames are not.
- **Hotkey defaults:** keep `Ctrl+Space` for PTT and `Ctrl+.` for type-popup. Both are documented; users have muscle memory.
- **No new top-level deps.** Tests can use `pytest` + `pytest-qt` (already in `requirements.txt`); the fake-claude harness should be a Python script written into a tempdir, not a new dep.
- **`make_always_visible` no-op on non-darwin** must remain — tests run on macOS dev machines and CI Linux containers identically.

## Prior art in this repo

- **Bridge / signal marshalling:** `task_manager._TaskBridge` (`task_manager.py:18–22`) is the cleanest precedent. Mirror its pattern for any new background-thread → Qt crossings.
- **Subprocess management:** the fake-claude script for tests can mirror the structure of the real one — emit `{"type":"system","subtype":"init"}`, then `{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"ls"}}]}}`, then `{"type":"result","subtype":"success","result":"done"}`. `_status_from_event` already covers each branch (`agent_runner.py:215–250`).
- **Toggle hotkey unit-testability:** `PTTListener._handle_press` and `_handle_release` already take a `key` arg directly — they're trivially callable from tests without a real listener. No refactor needed.
- **Tests live in `tests/`** with `pytest` + the `sys.path.insert` shim at the top (`tests/test_integration.py:8`). New file `tests/test_agentic_flow.py` should follow the same pattern.

## External references

None needed. All constraints answered from local code; no API surface changes to research.

## Remaining unknowns (for design to handle)

- **U1 visual treatment:** should the voice indicator gain a transient `error` state, or is a console-only error acceptable for the global-PTT mic/STT failure path? Gut call: add the state — the cost is ~15 lines in `voice_indicator.py` and it closes the visibility gap. Design can decide.
- **B1 contract:** when amend is invoked on a `cancelled` task, should it re-spawn anyway? Strictly speaking the queue-clear in `cancel()` is a "throw away pending work" signal, not "refuse all future work." Two options: (A) re-spawn — treat amend-after-cancel as "user changed their mind, continue from where it left off"; (B) refuse — emit a status like `"cancelled — start a new task"` and drop the amend. Gut call: (A), since the workdir is intact and `--continue` will work; matches the README's "amend always available." Design picks.
- **Test isolation:** the fake-claude script needs to exec from `_CLAUDE` resolution. Cleanest is to set `CLAUDE_CLI=/tmp/curby_fake_claude.py` via env in the test fixture (the constant `_CLAUDE` already honors `CLAUDE_CLI`, `agent_runner.py:30`). Confirm in design.
