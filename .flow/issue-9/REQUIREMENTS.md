# Requirements — check the whole agentic flow of the curby puck

> Source: https://github.com/CasterlyGit/curby/issues/9
> Generated: 2026-04-26

## Problem

The agentic flow — voice → transcription → spawned `claude` subprocess → docked puck with live status and pause/cancel/amend controls — is the product. It has zero automated coverage and two real correctness bugs the audit just surfaced (amend-after-done is a silent no-op; the voice indicator gets stuck in `listening` when recording self-terminates after 30 s). The user's note in `inbox/` ("user voice is registered then what? flow is:") signals they want the pipeline pinned down — verifiable, not just hand-traced. This iteration adds a headless test harness that locks in the contract, fixes the two bugs in scope, and corrects the small docs/UX gaps the audit found so the README/`design.md` match reality.

## Users & contexts

- **Primary user**: the developer (project owner) running curby on macOS. They speak a prompt, watch a puck spawn, and expect amend / cancel to behave as the README promises. They also expect future PRs not to regress the pipeline silently — that's why automated coverage matters here.
- **Other affected**: contributors reading `design.md` and the active-flow modules. Outdated docstrings (the `Ctrl+Shift+Space` line in `app.py`) and the spurious Screen Recording prereq in `README.md` mislead anyone trying to understand or extend the flow.

## Acceptance criteria

- [ ] **AC-1: Amend-after-done re-spawns the agent.** When `AgentRunner.amend("...")` is called after `on_done(rc)` has already fired (task in `done` / `error` / non-cancelled state), the runner spawns a fresh `claude -p --continue ...` in the same workdir within 1 s, and the puck returns to the `running` state with status updates flowing again. Cancelled tasks are explicitly excluded — see AC-2.

- [ ] **AC-2: Cancel kills the queue.** When `AgentRunner.cancel()` is called, all currently-queued and any subsequently-submitted amends are dropped (no re-spawn), the live subprocess (if any) receives SIGTERM with a 2 s SIGKILL grace, and the puck transitions to `cancelled` and stays there.

- [ ] **AC-3: Voice indicator transitions on every recording exit path.** When `record_until_stop` returns — whether because the user toggled PTT off, hit the puck's "send", or hit the internal `MAX_SECONDS` cap — the voice indicator transitions from `listening` to `processing` exactly once before the indicator settles back to `idle` on transcription completion or error. The "stuck on listening" path observed at the 30 s timeout no longer occurs.

- [ ] **AC-4: Stream-json events map to user-visible status.** Given a known sequence of `claude` stream-json events (`system/init`, `assistant/tool_use[Bash]`, `assistant/tool_use[Read]`, `assistant/text`, `result/success`, `result/error`), `AgentRunner` emits the corresponding short status strings via `on_status` in order, ending with `on_done(rc)` exactly once. The mapping is pinned by a table-driven test of `_status_from_event`.

- [ ] **AC-5: PTT toggle re-arm holds under tap, hold, mash.** Simulating press / release sequences against `PTTListener` (tap-tap, hold-tap, release-mid-chord, release-out-of-order) fires `on_toggle` exactly once per fully-held activation of the trigger chord and re-arms only after the chord is no longer fully held.

- [ ] **AC-6: Headless test suite passes on developer machine.** `python -m pytest tests/test_agentic_flow.py -v` runs to completion in under 30 s, requires no `ANTHROPIC_API_KEY`, no real `claude` binary, no microphone, no display server, and exits 0. The fake `claude` is a Python script written into a tempdir and selected via the existing `CLAUDE_CLI` env override.

- [ ] **AC-7: Docs match the active flow.** `README.md` no longer claims Screen Recording permission is required for the active flow (Accessibility + Microphone remain). The top-of-file docstring in `src/app.py` no longer references `Ctrl+Shift+Space` (the active default is `Ctrl+Space`). `design.md`'s component list still describes only what's actually wired into `app.py`.

- [ ] **AC-8: `main.py` does not preflight Screen Recording.** The dead `Quartz.CGPreflightScreenCaptureAccess` block tied to the dormant guidance pipeline is removed; running `python main.py` no longer prompts the OS for screen-recording access. Microphone and Accessibility prompts still fire (those are still load-bearing).

## Out of scope

- **Visual error feedback on the voice indicator (research item U1).** A dedicated transient `error` state on `VoiceIndicator` is a nice-to-have but not required for the audit-fix scope. Console + puck-status surfaces are sufficient for this iteration. Filed as a follow-up consideration.
- **Reviving the legacy guidance pipeline** (`ghost_cursor.py`, `guide_path.py`, `action_highlight.py`, `ai_client*.py`, the screen-capture path). Not touched here.
- **Qt-widget / `DockedTaskPuck` rendering tests.** Visuals are not the audit target and `pytest-qt` headless coverage of the puck is a separate effort.
- **`voice_io.record_until_stop` integration with a real microphone** or with Google STT. External services + hardware. Tests stub or skip.
- **Hotkey rebinding.** Defaults stay `Ctrl+Space` and `Ctrl+.`.
- **Multi-task scheduling / concurrency limits.** TaskManager already supports parallel pucks; no change in this iteration.
- **Refactoring the legacy modules out of the repo.** They stay on disk per the README's stated future plan.

## Open questions

- **Q1 (for design): On `cancelled`, does amend re-spawn or not?** Research's gut call was "yes, re-spawn — workdir is intact, `--continue` works, matches README's 'amend always available'." AC-2 above currently locks this as **no, re-spawn does not happen on cancelled** (because `cancel()` clears the queue and sets `_cancelled`). Design must confirm and document the rationale; if we flip to "re-spawn after cancel," AC-1 wording widens and AC-2 narrows to "subsequently-submitted amends are dropped" only.
- **Q2 (for design): What's the smallest viable contract for the new `record_until_stop` "recording-stopped" callback** that fixes B2 without bloating the signature? Options: (a) add an `on_stopped` kwarg fired once before STT runs; (b) emit a sentinel level via the existing `on_level` callback; (c) move the `set_state("processing")` transition entirely into the recording thread via a bridge signal. (a) is the obvious choice; design confirms.
- **Q3 (for design): Where does the fake-`claude` script live?** Two reasonable spots: `tests/fixtures/fake_claude.py` (committed, pytest fixture writes its path to env) or generated at test time into `tmp_path`. Committed is easier to debug; generated is hermetic. Pick one in design.
