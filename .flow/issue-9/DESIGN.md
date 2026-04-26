# Design — check the whole agentic flow of the curby puck

> Reads: REQUIREMENTS.md (acceptance criteria are the contract)
> Generated: 2026-04-26
> Issue: [#9](https://github.com/CasterlyGit/curby/issues/9)

## Approach

Pin the agentic flow with a small, deterministic pytest module that drives `AgentRunner` against a fake `claude` script (selected via the existing `CLAUDE_CLI` env var) and unit-tests `_status_from_event` and `PTTListener` directly — no Qt event loop, no mic, no network, no real subprocess agent. While here, fix the two correctness bugs the audit found (B1 amend-after-done, B2 indicator stuck on timeout), drop the dead Screen-Recording preflight, and correct the stale docs. Alternatives weighed: (a) end-to-end `pytest-qt` headless harness driving the real `CurbyApp` with a faked recording thread — rejected, too much surface for an audit pass; (b) BDD-style scenario file using a tape-replay format — rejected, premature for one module's worth of behavior.

## Components touched

| File / module | Change |
|---|---|
| `src/agent_runner.py` | **B1 fix:** `amend(text)` learns to detect "no live `_read_loop`" and call `_spawn(prompt, resume=True)` directly under `_lock`, with `_cancelled` honored as a hard stop. `is_running` already checks `_proc.poll()`; reuse it. The existing in-loop drain stays (don't double-spawn). Add a small `_spawn_lock` (or repurpose `_lock`) so concurrent amends from main + reader don't both spawn. Pseudocode: `amend(text): with _lock: if _cancelled: drop; if reader thread alive → append to queue (existing behavior); else → set next_prompt, _spawn(text, resume=True)`. |
| `src/voice_io.py` | **B2 fix:** add a new kwarg `on_recording_stopped: Callable[[], None] \| None = None` to `record_until_stop`. Fire it exactly once when the record loop exits — *before* WAV write / STT — regardless of cause (user toggle, max-seconds cap, exception path inside the `with` block). Caller wires it to `voice.set_state("processing")` via the existing bridge. |
| `src/app.py` | Wire the new `on_recording_stopped` kwarg through `_start_recording._run` → `self._bridge.recording_stopped.emit()`. Add `recording_stopped = pyqtSignal()` to `_Bridge`, connect to a tiny slot that calls `self._voice.set_state("processing")`. Update top-of-file docstring: `Ctrl+Shift+Space` → `Ctrl+Space`. |
| `main.py` | **AC-8:** delete the `Quartz.CGPreflightScreenCaptureAccess / CGRequestScreenCaptureAccess` block (the active flow never grabs the screen). Keep the macOS accessory-policy block — it's still load-bearing. |
| `README.md` | **AC-7:** drop "Screen Recording" from the Prereqs line. Keep "Microphone" and "Accessibility." Other content unchanged. |
| `design.md` | **AC-7:** remove the `CGPreflightScreenCaptureAccess` reference under "macOS specifics" (it's no longer accurate after `main.py` change). One-line note that "amend works in any non-`cancelled` state" under the AgentRunner section, to document B1's fix. |
| `tests/test_integration.py` | No change. |
| `requirements.txt` | No change (pytest + pytest-qt already present; pytest-qt unused by the new tests but no harm). |

## New files

- `tests/fixtures/__init__.py` — empty package marker so pytest discovers the fixture dir cleanly.
- `tests/fixtures/fake_claude.py` — a small Python script that prints a sequence of stream-json lines to stdout based on a mode env var (`FAKE_CLAUDE_MODE`), then exits with `FAKE_CLAUDE_RC` (default 0). Modes: `success` (init → tool_use Bash → tool_use Read → text → result/success), `error` (init → result/error), `crash_early` (init → exit 1 with no result line), `slow` (init → sleep 0.5 → result/success — for amend re-spawn timing). The script reads its own argv to support `--continue`: when `--continue` is present, prepend a `{"type":"user","message":...}` line so we can assert resume vs initial. **Committed**, not generated — easier to debug, matches Q3 in REQUIREMENTS.
- `tests/test_agentic_flow.py` — the new test module covering AC-1, AC-2, AC-3, AC-4, AC-5, AC-6. Layout (one class or top-level functions, pytest-style):
  - `test_status_from_event_table` — table-driven over each event shape `_status_from_event` handles, asserting the exact short status string (or `None`).
  - `test_ptt_listener_toggle_armcycle` — instantiate `PTTListener` with a fake `on_toggle`, drive its `_handle_press` / `_handle_release` directly with `keyboard.Key.ctrl` / `keyboard.Key.space` events, assert toggle fires exactly once per chord activation, re-arms on release, fires again on reactivation. Covers tap-tap, hold-tap-tap, release-mid-chord-then-press-again.
  - `test_agent_runner_lifecycle_success` — `CLAUDE_CLI` set to fake-claude-success path; `AgentRunner` started; collect statuses; assert ordered subset includes `"thinking…"`, a `"using Bash"` containing the fake command, a `"using Read"`, the assistant text, and the final `"done"` (mapped from result/success); assert `on_done(0)` fires exactly once.
  - `test_agent_runner_amend_after_done` — start with mode=`success`; wait for `on_done`; call `runner.amend("more please")`; assert a new `_spawn(resume=True)` happens within 1 s by observing a fresh `on_status("amending…")` and a second `on_done`. **Validates AC-1.**
  - `test_agent_runner_cancel_drops_queue` — mode=`slow`; queue two amends while running; call `runner.cancel()`; assert no second spawn occurs (no second `on_status("amending…")` within 1 s) and `on_status("cancelled")` fires once. **Validates AC-2.**
  - `test_record_until_stop_fires_on_recording_stopped` — monkeypatch `sounddevice.InputStream` and `speech_recognition.Recognizer` with stubs that yield silent chunks and a fixed transcription. Call `record_until_stop` in a thread with a stop event. Assert `on_recording_stopped` fires exactly once whether stop is via `stop_event.set()` or via the `MAX_SECONDS` cap (the test forces the cap by setting MAX_SECONDS to a tiny value via monkeypatch). **Validates AC-3.**

## Data / state

**Fake-claude protocol.** Stream-json lines, one per `print()`, flushed:

```jsonl
{"type":"system","subtype":"init"}
{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"echo hi"}}]}}
{"type":"user","message":{"content":[{"type":"tool_result","content":"hi"}]}}
{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read","input":{"file_path":"/tmp/x"}}]}}
{"type":"assistant","message":{"content":[{"type":"text","text":"all done"}]}}
{"type":"result","subtype":"success","result":"all done"}
```

**Env contract for fake-claude:**

| Var | Effect |
|---|---|
| `CLAUDE_CLI` | Already honored (`agent_runner.py:30`). Tests `monkeypatch.setenv("CLAUDE_CLI", str(fake_claude_path))` per-test. |
| `FAKE_CLAUDE_MODE` | `success` (default), `error`, `crash_early`, `slow` |
| `FAKE_CLAUDE_RC` | Override exit code (int). Default depends on mode. |
| `FAKE_CLAUDE_SLEEP` | Float seconds (default 0.5 in `slow`). |

**No persisted state changes.** `~/curby-tasks/` layout unchanged. No new env vars in production code paths. The fake-claude env vars only affect tests — production `claude` ignores them.

**`_Bridge` shape after change:**

```python
class _Bridge(QObject):
    cursor_moved        = pyqtSignal(int, int)
    ptt_toggled         = pyqtSignal()
    audio_level         = pyqtSignal(float)
    recording_stopped   = pyqtSignal()                  # NEW
    transcription_ready = pyqtSignal(str, object)
    transcription_error = pyqtSignal(str)
    type_hotkey_fired   = pyqtSignal()
    quit_hotkey_fired   = pyqtSignal()
```

## Public API / surface

**Changed:**

- `src.voice_io.record_until_stop(stop_event, on_speech_start=None, on_level=None, on_recording_stopped=None) -> str` — new optional kwarg. Existing callers continue to work (kwarg-only addition).
- `src.agent_runner.AgentRunner.amend(text: str)` — same signature, expanded behavior: post-`on_done` calls now re-spawn; cancelled tasks still drop. No new public method.

**Unchanged:**

- All other public surfaces of `AgentRunner`, `Task`, `TaskManager`, `PTTListener`, `VoiceIndicator`, `DockedTaskPuck`, `CurbyApp`.
- Hotkeys: `Ctrl+Space` (PTT), `Ctrl+.` (text input), `Esc` (quit).
- Subprocess command shape: `claude -p --dangerously-skip-permissions --output-format stream-json --verbose [--continue] <prompt>`. Unchanged.

**Internal:**

- `_Bridge.recording_stopped` signal: emitted from the recording thread, slotted on the Qt main thread to call `self._voice.set_state("processing")`.

## Failure modes

| Failure | How we detect | What we do |
|---|---|---|
| Amend on a `cancelled` task | `_cancelled` flag set inside `_lock` | Drop the amend silently. Status: unchanged (`cancelled`). Rationale: cancel cleared the queue and signalled "throw away pending work." Locked by AC-2. (Q1 in REQUIREMENTS resolved this way.) |
| Amend race: main thread amend + reader thread drain | Both paths take `_lock` before reading/writing `_pending_amends` and before deciding to spawn | Whoever wins the lock first drains; the other sees an empty queue and skips its spawn. Net result: exactly one `_spawn(resume=True)` per amend. |
| `_spawn(resume=True)` from amend on a still-running reader thread | `is_running` is True or `_reader is alive` | Append to `_pending_amends` and return — do NOT spawn directly. Existing behavior, preserved. |
| `record_until_stop` exception inside the `with sd.InputStream(...)` block | `try / except` around the loop already catches it | Currently `raise RuntimeError("mic unavailable: …")`. Add a `finally` that fires `on_recording_stopped` first so the indicator transitions to `processing` before the error surfaces. Then the existing error-handling path emits `transcription_error`. User: voice indicator briefly sweeps orange, then back to idle, console shows the error. |
| Fake-claude script can't find Python on PATH (test env) | `Popen` raises `FileNotFoundError` | Test fixture fails fast with a clear assert message; not a runtime concern. |
| `_status_from_event` table drifts from real `claude` event shapes | Table test asserts current mapping | If `claude` adds new event types upstream, the table test still passes (`None` fallthrough); no false alarm. We can extend the table later. |
| Test runs on a CI image without a display | All new tests are headless (no `QApplication`) | No-op; tests pass. `mac_window.make_always_visible` short-circuits on non-darwin already. |
| User on macOS with old `~/curby-tasks/` dirs | Workdir layout unchanged | No migration needed. |

## Alternatives considered

- **Full `pytest-qt` headless harness driving `CurbyApp`.** Would catch wiring bugs in `app.py` itself (e.g. signal-slot connections), but the surface is much larger, the test would need to fake mic + cursor + keyboard, and Qt event-loop pumping in pytest-qt is fiddly on CI. We get most of the value from unit-testing `AgentRunner`, `_status_from_event`, and `PTTListener` directly — those are where the actual logic lives.
- **Generate fake-claude into `tmp_path` per test.** Hermetic, but harder to debug when a test fails. Committed fixture is more transparent and the "global state" risk is minimal because tests `monkeypatch` the env per-test.
- **Refactor `_Bridge.recording_stopped` into a callback on `_record_thread` directly, without a bridge signal.** Simpler in isolation but skips the established main-thread marshaling pattern. Picked the bridge signal for consistency with how `audio_level` and `transcription_ready` already work.
- **Re-spawn on `cancel()` + amend (Q1 option A in research).** Considered: cancel might be "I changed my mind." Rejected: cancel already guarantees SIGTERM; users who want to continue a cancelled run are better served by spawning a fresh task with `--continue` *manually* — which is a future feature, not in scope. AC-2 locks the strict semantics.
- **Add a transient `error` state to `VoiceIndicator` (research U1).** Noted as out-of-scope in REQUIREMENTS. Easy to add later.

## Risks / known unknowns

- **Fake-claude flake on slow CI.** The amend-after-done test asserts a 1-s window for the second `_spawn`. If a busy macOS runner blocks Python startup, the bound is tight. Mitigation: bound to 3 s in the test, and use an `Event`-based wait instead of polling.
- **`_lock` reuse for amend serialization.** The lock currently guards `_pending_amends` and `_cancelled`. Wrapping `_spawn` calls in it would create a longer critical section that includes `subprocess.Popen`. Mitigation: hold the lock only across the queue/pop/cancelled-check decision, then release before calling `_spawn`. Re-acquire only to update `_pending_amends`. This matches the existing `_read_loop` ordering.
- **macOS Screen Recording removal might surprise users who already enabled it.** Removing the preflight only stops the *prompt*; pre-granted permission is harmless. README change is the user-facing signal. Acceptable.
- **`pytest-qt` import on a Linux container without Qt libs.** The new tests must avoid importing `PyQt6` at test-collection time. Solution: keep `from src.agent_runner import AgentRunner` at module top, but import any `PyQt6`-touching helpers (none, in our plan) inside test bodies if needed.
- **Event-shape drift in `claude` itself.** If Anthropic ships a new event type, the live status pipeline doesn't break (existing code returns `None` for unknown types), but our test table won't catch the new event. Acceptable known-unknown — the audit's purpose is to pin *current* behavior.
