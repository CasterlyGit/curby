---
name: Explore — curby (issue #9)
description: Repo map for "check the whole agentic flow of the curby puck"
type: stage-artifact
---

# Explore — curby

Issue: [#9](https://github.com/CasterlyGit/curby/issues/9) — _check the whole agentic flow of the curby puck_

The body is empty; the only context is `inbox/check the whole agentic flow of the curby puck.md`, which says:

> user voice is registered then what?
> flow is:

Read as: the user wants a verified end-to-end trace of the puck's agentic flow (voice → transcription → spawn → live status → controls → completion / amend). This is an audit, not a feature add.

## Stack
- **Language:** Python 3.12 (`.venv` is python3.12).
- **UI:** PyQt6 (frameless overlays, signals/slots).
- **Voice:** `sounddevice` (mic) + `scipy.io.wavfile` (WAV) + `SpeechRecognition` (Google STT) + `pyttsx3` (TTS, unused in active flow).
- **Hotkeys / cursor:** `pynput` (keyboard + mouse listeners).
- **Agent:** `claude` CLI as a subprocess, `--output-format stream-json`, parsed line-by-line.
- **macOS shim:** PyObjC (`AppKit`, `Quartz`) for screen-recording preflight + `NSStatusWindowLevel` overlay pinning.
- **Tests:** `pytest` + `pytest-qt`.
- **Manifest:** `requirements.txt` (no `pyproject.toml`, no lockfile).

## Layout
- `main.py` — entry point. Sets UTF-8 stdio, macOS accessory activation policy, screen-recording preflight, then `CurbyApp().run()`.
- `src/app.py` — `CurbyApp` glue: owns voice indicator, task manager, text popup, cursor tracker, PTT listener, and the single recording thread shared between global PTT and per-task amend.
- `src/ptt_listener.py` — toggle-style global hotkey (`Ctrl+Space`).
- `src/voice_io.py` — `record_until_stop` (mic → WAV → Google STT) + `speak`.
- `src/voice_indicator.py` — cursor-anchored bars; states `idle / listening / processing`.
- `src/cursor_tracker.py` — pynput mouse listener emitting `on_move(x, y)`.
- `src/text_input_popup.py` — alternate input via `Ctrl+.`.
- `src/agent_runner.py` — one `claude -p ...` subprocess per task; pause/resume via SIGSTOP/SIGCONT, cancel via SIGTERM/SIGKILL, amend via `--continue`.
- `src/task_manager.py` — `Task` (runner + puck + bridge) and `TaskManager` (list, palette rotation, dock layout, amend signal routing).
- `src/dock_widget.py` — `DockedTaskPuck` visuals, hover-expand panel, state pip, button rows.
- `src/mac_window.py` — `make_always_visible` PyObjC shim (NSStatusWindowLevel + canJoinAllSpaces + !hidesOnDeactivate).
- `src/ai_client.py`, `src/ai_client_api.py`, `src/ghost_cursor.py`, `src/guide_path.py`, `src/action_highlight.py`, `src/speech_bubble.py`, `src/buddy_window.py`, `src/buddy_icon.py`, `src/chat_panel.py`, `src/screen_capture.py`, `src/status_window.py` — **legacy guidance pipeline**, not imported by `app.py`. Per `design.md`, dormant pending an opt-in "show me how to…" mode.
- `tests/test_integration.py` — pytest covering screen capture, cursor tracker, buddy window positioning, optional Anthropic-API smoke. **All targeted at the legacy pipeline; nothing exercises the agentic flow.**
- `phase1_test.py`, `test_run.py` — ad-hoc top-level smoke harnesses for the legacy pipeline.
- `design.md` — authoritative architecture doc for the active flow. Already documents the high-level pipeline.
- `inbox/` — staging for raw issue notes; not committed historically.
- `.flow/` — pipeline working dir (this file's home), gitignored-style scratch.

## Entry points
- run: `python main.py` (after `pip install -r requirements.txt`)
- test: `python -m pytest tests/ -v`
- build: _none_ (script-style Python project; no packaging)
- ad-hoc smoke: `python phase1_test.py` and `CURBY_SAFE_MODE=1 CURBY_TEST_SECS=15 python test_run.py`

## Conventions
- Docstrings open every module with a 1-paragraph "what & why"; comments explain non-obvious behaviour (e.g. `voice_io.py` on why silence threshold is intentionally low; `app.py` on the shared recording target).
- Background-thread → Qt main-thread crossings always go through a `_Bridge(QObject)` with `pyqtSignal`s (e.g. `app._Bridge`, `task_manager._TaskBridge`).
- Per-callback dispatch on the agent: `on_event / on_status / on_done` shape (`agent_runner.AgentRunner`).
- Files are flat under `src/` — no submodules, no package boundaries.
- `_underscored` private methods inside classes; module-private helpers prefixed `_` (e.g. `_status_from_event`).
- No type-checker config; type hints are partial (mostly on public surface).
- No formatter / lint config files (no `ruff.toml`, `.flake8`, `pyproject.toml`).

## Recent activity
- branch: `auto/9-check-agentic-flow` (just created off `main`)
- last commits on `main`:
  - `53a1ed4` Merge pull request #1 from CasterlyGit/chore/issue-templates
  - `ea947f0` chore: add standard issue templates from workspace kit
  - `a2e8cc2` Pivot: voice-driven agent dispatcher with neon task pucks
  - `e5f7b1c` macOS support: push-to-talk + cross-platform fixes + overlay perf
  - `996af6d` Keep listener open during animations; state stays 'listening' between actions
- uncommitted on this branch: untracked `.flow/` (this artifact) and untracked `inbox/`. No tracked changes.

## Files relevant to this target

The "agentic flow" spans every link in the chain from key-down to subprocess exit. In likely-edit order if the audit surfaces issues:

- `src/app.py` — the orchestrator; most state-machine bugs (recording target swap, amend interleave, PTT re-arm) live here.
- `src/agent_runner.py` — subprocess lifecycle, signal handling, amend queue, stream-json parsing. Hot spot for races between `_read_loop` draining the amend queue and `cancel()` clearing it.
- `src/task_manager.py` — main-thread bridge for runner callbacks; `_handle_done` already trampolines through `QTimer.singleShot(0, …)` — verify that's consistent.
- `src/ptt_listener.py` — toggle re-arm semantics; misfire here causes "stuck listening" or "won't toggle off" symptoms.
- `src/voice_io.py` — mic stream lifecycle, stop-event responsiveness, transcription error surface.
- `src/dock_widget.py` — UI feedback that proves the flow worked (state pip, status text, amend toggle); only relevant if the audit finds the user can't tell what state they're in.
- `tests/test_integration.py` — currently has **zero coverage of the agentic flow**; almost certainly the place new tests land.
- `design.md` — already documents the intended flow; the audit will likely either confirm or amend it.
- `README.md` — the user-facing flow description; should match the audited reality.

## Open questions for the next stage

1. **What does "check" mean here — write tests, write a runtime trace, or just produce an audit doc?** The issue body is empty; `inbox/` says only "flow is:" (truncated). Research must decide the deliverable shape.
2. **Is there a reproducible bug being chased, or is this a clean audit?** No bug-report fragments, no failing-test artifact, no log excerpt. Likely the latter, but worth confirming before designing fixes.
3. **Scope of "the puck":** does this mean the visual puck only (`dock_widget.py` + state transitions), or the full puck-as-task lifecycle from voice in to subprocess out? Title says "the curby puck" but `inbox/` says "user voice is registered then what?" — strongly implies the whole pipeline.
4. **Race / concurrency hot spots to verify:**
   - `AgentRunner._read_loop` pops from `_pending_amends` under `_lock`, but `cancel()` clears the same list under `_lock` — does the existing ordering guarantee no amend leaks past a cancel? (Looks OK on inspection; worth a targeted test.)
   - `CurbyApp._record_target` is set/read across the recording thread and the Qt main thread without a lock; fine because the thread only reads at startup and writes only on the main thread, but let's confirm.
   - PTT toggle while a per-task amend is recording: `_on_ptt_toggled` early-returns without stopping if `_record_target` is not None — verify this matches the README's described behaviour ("only one recording at a time").
5. **Failure modes the user would notice:** mic permission denied, `claude` not on PATH, Google STT offline, subprocess crashes before first stream-json line, agent runs >30 s without speaking. Which of these surface a clear puck/voice-indicator state today, and which silently strand?
6. **No automated coverage today.** Should this iteration add a minimal headless harness for `AgentRunner` + a `_status_from_event` table-test, or is that out of scope for an audit-first issue?
