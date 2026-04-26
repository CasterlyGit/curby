# Test plan — check the whole agentic flow of the curby puck

> Reads: REQUIREMENTS.md (each AC must be covered) + DESIGN.md (failure modes)
> Generated: 2026-04-26
> Issue: [#9](https://github.com/CasterlyGit/curby/issues/9)

Framework: `pytest` (already in `requirements.txt`). All new tests live in `tests/test_agentic_flow.py` and target the headless surfaces — no `QApplication`, no `pynput.Listener`, no real `claude`, no microphone. Tests written first (TDD shape) for B1 and B2 fixes; the AC-7 / AC-8 doc and `main.py` changes are validated manually.

## Coverage matrix

| AC | Test type | Test |
|---|---|---|
| AC-1: amend after `on_done` re-spawns | integration (subprocess via fake-claude) | `test_agent_runner_amend_after_done` |
| AC-2: cancel kills the queue | integration (subprocess via fake-claude) | `test_agent_runner_cancel_drops_queue` |
| AC-3: voice indicator transitions on every recording exit | unit (monkeypatched mic + STT) | `test_record_until_stop_fires_on_recording_stopped` × 2 (user-stop and max-seconds paths) |
| AC-4: stream-json events map to status | unit (table-driven) | `test_status_from_event_table` |
| AC-5: PTT toggle re-arm | unit (direct `_handle_press`/`_handle_release` calls) | `test_ptt_listener_toggle_armcycle` |
| AC-6: headless suite passes <30 s with no key/binary/mic | integration (CI-shaped run) | `pytest tests/test_agentic_flow.py -v` exits 0 in <30 s |
| AC-7: docs match the active flow | manual | review `README.md`, `src/app.py` docstring, `design.md` diff |
| AC-8: `main.py` does not preflight Screen Recording | manual | `python main.py` does not produce the `[mac] screen recording …` line; macOS does not prompt for screen recording on first run |

## Unit tests

- `test_status_from_event_table` — drive `agent_runner._status_from_event` with each canonical event shape and assert the exact returned string (or `None`):
  - `{"type":"system","subtype":"init"}` → `"thinking…"`
  - `{"type":"system","subtype":"other"}` → `None`
  - `{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"ls -la"}}]}}` → `"using Bash · ls -la"`
  - `{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read","input":{"file_path":"/tmp/x.py"}}]}}` → `"using Read · x.py"`
  - `{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Grep","input":{"pattern":"foo"}}]}}` → `"using Grep · 'foo'"`
  - `{"type":"assistant","message":{"content":[{"type":"text","text":"line one\nline two"}]}}` → `"line one"`
  - `{"type":"user","message":{"content":[{"type":"tool_result","content":"ok"}]}}` → `"got result"`
  - `{"type":"result","subtype":"success","result":"all done"}` → `"all done"`
  - `{"type":"result","subtype":"success","result":""}` → `"done"`
  - `{"type":"result","subtype":"error_during_execution"}` → `"error: error_during_execution"`
  - `{"type":"unknown_type"}` → `None`

- `test_ptt_listener_toggle_armcycle` — instantiate `PTTListener(on_toggle=fake)` without calling `.start()` (so no real `keyboard.Listener`); drive `_handle_press` / `_handle_release` directly with `pynput.keyboard.Key.ctrl` / `keyboard.Key.space`. Assert:
  - tap (press ctrl, press space, release space, release ctrl) → fake called once
  - tap-tap (repeat) → fake called twice total
  - hold-then-tap-space-twice (press ctrl, press space, release space, press space, release space, release ctrl) → fake called twice total (re-arms after each space release because chord no longer subset)
  - press space first, then ctrl (out-of-order chord build) → fake called once
  - mash (press ctrl, press space, press ctrl_l) → fake called exactly once (canonicalization collapses ctrl variants; no double-fire)

- `test_record_until_stop_fires_on_recording_stopped` (user-stop path) — monkeypatch `voice_io.sd.InputStream` with a context manager whose `read(chunk)` returns silent int16 frames; monkeypatch `voice_io.sr.Recognizer.recognize_google` to return `"hello"`. Run `record_until_stop` in a thread; set `stop_event` after a single chunk. Assert `on_recording_stopped` called exactly once and *before* the function returns its transcription.

- `test_record_until_stop_fires_on_recording_stopped_max_seconds` (timeout path) — same monkeypatching, but additionally `monkeypatch.setattr(voice_io, "MAX_SECONDS", 0.05)` so the loop exits via the cap. Stop event is never set. Assert `on_recording_stopped` called exactly once.

## Integration tests

These exercise real subprocess + JSON parsing against the committed `tests/fixtures/fake_claude.py` script. Fixture: `monkeypatch.setenv("CLAUDE_CLI", str(fake_claude_path))`; `agent_runner._CLAUDE` is module-level so we re-import or set it directly via `monkeypatch.setattr(agent_runner, "_CLAUDE", str(fake_claude_path))`.

- `test_agent_runner_lifecycle_success` — fake-claude in mode `success`. Spawn an `AgentRunner`, collect `on_status` strings into a list and `on_done` rc into an `Event`. Wait up to 5 s for done. Assert:
  - `on_status` list contains, in order, `"starting…"`, `"thinking…"`, a string starting with `"using Bash"`, `"got result"`, a string starting with `"using Read"`, the assistant text, and the final `"all done"` (or `"done"`).
  - `on_done` fires exactly once with rc=0.
  - `runner.workdir.exists()` is true under `~/curby-tasks/`. (Test uses a `tmp_path`-scoped `TASKS_ROOT` via `monkeypatch.setattr(agent_runner, "TASKS_ROOT", tmp_path / "tasks")` to avoid polluting the real dir.)

- `test_agent_runner_amend_after_done` (validates AC-1) — fake-claude mode `success`. Start runner, wait for first `on_done`, then call `runner.amend("more please")`. Wait up to 3 s for a second `on_done`. Assert:
  - `on_status` records `"amending…"` after the first `"all done"` / `"done"`.
  - A second `on_done` with rc=0 fires.
  - The second `claude` invocation receives `--continue` (verify by writing fake-claude's argv to `<workdir>/argv.log` and reading it).

- `test_agent_runner_cancel_drops_queue` (validates AC-2) — fake-claude mode `slow` (sleeps 0.5 s before result). Start runner, queue two amends with `runner.amend("a")` / `runner.amend("b")`, wait 0.1 s, call `runner.cancel()`. Wait up to 2 s. Assert:
  - `on_status` contains `"cancelled"` exactly once.
  - No `"amending…"` status fires.
  - Only one `on_done` fires (the original spawn's, with non-zero rc from SIGTERM).
  - A subsequent `runner.amend("c")` after cancel does NOT trigger a new spawn (assert no further `"amending…"` within 0.5 s).

- `test_agent_runner_amend_during_running_uses_queue` — guard against regression: while the original spawn is still alive, `amend("x")` must append to the queue (not direct-spawn). fake-claude mode `slow`. Start runner; assert `is_running` is true; call `amend("x")`; immediately after, assert `_pending_amends == ["x"]` (private-state check is acceptable here — the contract is that we don't double-spawn). Wait for done; assert second `on_done` fires from the queued amend.

## Manual checks

- [ ] `python main.py` on macOS does **not** print `[mac] screen recording …` (AC-8) and macOS Settings → Privacy → Screen Recording does not show a fresh prompt for Python.
- [ ] `Ctrl+Space` still toggles listening; `Ctrl+.` still opens the text popup; `Esc` still quits. (AC-7 docstring change shouldn't affect runtime behavior, but eyeball it.)
- [ ] `README.md` "Prereqs" line no longer mentions Screen Recording. (AC-7)
- [ ] `src/app.py` top-of-file docstring mentions `Ctrl+Space`, not `Ctrl+Shift+Space`. (AC-7)
- [ ] `design.md` "macOS specifics" section no longer claims `CGPreflightScreenCaptureAccess` is wired. (AC-7)
- [ ] **Smoke the real flow once:** start curby, speak a quick prompt ("list files in /tmp"), watch the puck spawn, run, and report `done`. Then click `amend`, speak "and count them", confirm a second run kicks off and reports a count. (Manual sanity for AC-1 against the real `claude` CLI — the fake-claude tests only prove our wiring; they can't prove the real binary still honors `--continue`.)
- [ ] Speak nothing for 30 s with mic active; confirm voice indicator sweeps `processing` (orange) once before going back to `idle`. (Manual sanity for AC-3 against the real `MAX_SECONDS` path.)

## What we are NOT testing (and why)

- **`DockedTaskPuck` rendering / hover-expand / button layout.** Visual surface; out of scope per REQUIREMENTS. The pucks already work in production; no changes touch them.
- **`make_always_visible` PyObjC behavior.** OS-level shim; cannot be unit-tested without a real NSWindow. Already no-ops on non-darwin.
- **`voice_io.speak` (TTS).** Not wired into the active flow; legacy. No new dependency on it.
- **Real `claude` subprocess.** The fake-claude script faithfully replays the documented stream-json event shapes; testing against the real binary requires `ANTHROPIC_API_KEY` and is environment-flaky. The committed manual smoke test above covers it during PR review.
- **Real microphone / Google STT.** External I/O; tests monkeypatch the relevant module surface.
- **`CursorTracker` mouse-listener thread behavior.** Already exercised by the legacy `tests/test_integration.py::test_cursor_tracker_starts_and_stops`. No code changes here.
- **`TaskManager._relayout` arithmetic.** Pure pixel layout against `QApplication.primaryScreen()` — would require a Qt event loop; not the audit target.
- **Multi-task interactions (parallel pucks, palette rotation).** Already in production; no logic touched.
- **Legacy guidance pipeline modules** (`ghost_cursor.py`, `guide_path.py`, `action_highlight.py`, `ai_client*.py`, `screen_capture.py`, `buddy_window.py`, `chat_panel.py`, `speech_bubble.py`, `status_window.py`). Dormant; the existing `tests/test_integration.py` covers what little of them is exercised.
