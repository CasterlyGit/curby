# Curby — design

This is the technical companion to the README. It walks through how voice
input becomes a running Claude Code agent, how the per-task UI is wired,
and the macOS-specific tricks that keep the overlays visible.

---

## High-level flow

```
microphone           Ctrl+Space toggle
   │                       │
   ▼                       ▼
voice_io.record_until_stop  PTTListener
   │                       │
   │ (audio level callback) │ (toggle event)
   ▼                       ▼
VoiceIndicator       CurbyApp recording state
                            │
                            ▼ (transcribed text)
                     TaskManager.spawn(prompt)
                            │
                            ▼
                     AgentRunner ── claude -p ... ──► claude subprocess
                            │                              │
                            │ stream-json events            │ stdout
                            ▼ ◄────────────────────────────┘
                     DockedTaskPuck ── live status + state
```

---

## Components

### `src/ptt_listener.py` — PTTListener

A `pynput.keyboard.Listener` wrapper. Tracks a canonical set of currently-held
keys (left/right modifier variants collapsed). When the configured trigger
chord first becomes fully held, fires `on_toggle()` once. Re-arms only after
all trigger keys have been released. Default trigger: `Ctrl + Space`.

### `src/voice_io.py` — `record_until_stop` + `speak`

`record_until_stop(stop_event, on_speech_start, on_level)` opens a 16 kHz
mono int16 input stream via `sounddevice`, reads in 100 ms chunks, calls
`on_level(rms / 4000.0)` per chunk for waveform animation, and stops when
`stop_event` is set or `MAX_SECONDS` (30 s) hits. Audio is written to a
tempfile WAV and run through `speech_recognition.recognize_google()`.

Silence threshold is intentionally low (60) so quiet mics still trigger;
transcription runs even on near-silent audio so Google can decide.

### `src/voice_indicator.py` — VoiceIndicator

A frameless 64×28 translucent Qt widget anchored to the cursor (offset so
it sits below+right of the tip). Five bars; in `idle` state they bob slowly
(visible at rest — that's curby's "I'm running" signal); in `listening`
state, bar heights track the smoothed audio level; `processing` is a
left-to-right sweep while transcription runs.

Always-visible across spaces and apps via `mac_window.make_always_visible`.

### `src/agent_runner.py` — AgentRunner

One Claude Code subprocess per task. Spawned with:

```
claude -p --dangerously-skip-permissions \
       --output-format stream-json --verbose \
       <prompt>
```

…in a fresh `~/curby-tasks/<timestamp>-<slug>/` working directory, with
`start_new_session=True` so the agent and any children it spawns share a
process group we can signal as a unit.

A reader thread parses each JSON line and routes it to:

- `on_event(obj)` — raw event for any future inspection (currently unused)
- `on_status(str)` — short human-readable status (mapped from event types in `_status_from_event`)
- `on_done(rc)` — fires when the subprocess exits

Controls:

- **pause** — `os.killpg(pgid, SIGSTOP)`; the whole tree freezes instantly
- **resume** — `os.killpg(pgid, SIGCONT)`
- **cancel** — `SIGTERM`, then `SIGKILL` after a 2 s grace
- **amend(text)** — appends to a queue. When the current run exits cleanly,
  `_read_loop` pops the next amend and re-spawns with `--continue` in the
  same workdir, so the agent picks up its prior conversation and files.

### `src/dock_widget.py` — DockedTaskPuck

A 56×56 dark rounded square containing a sleek neon-colored cursor glyph.
Per-task accent rotates through 8 neon colors (cyan, violet, orange, teal,
coral, amber, sky, fuchsia). State is rendered both via cursor color and
via a distinct **state pip** in the bottom-right corner:

| state | pip rendering |
|---|---|
| running | spinning arc segment |
| paused | two amber pause bars |
| done | bright green dot + halo + checkmark tick |
| error / cancelled | red dot + X |

Hover expands the puck leftward into a 280-px panel with title, latest
status, and buttons. Buttons by state:

- **running** → pause / cancel / amend
- **paused** → resume / cancel / amend
- **done / error / cancelled** → amend / dismiss

Done pucks the user has hovered then left auto-dismiss 120 ms after leaving
(emits `auto_dismiss`).

### `src/task_manager.py` — Task + TaskManager

`Task` pairs an `AgentRunner` with a `DockedTaskPuck` and a `_TaskBridge`
that re-emits the runner's reader-thread callbacks as Qt signals on the
main thread.

`TaskManager` owns the list of running tasks, places pucks newest-on-bottom
along the right edge, rotates the per-task accent palette, and pins each
new puck via `make_always_visible` after `show()`.

Amend recording is delegated up to the app: tasks emit `task_amend_start` /
`task_amend_stop` signals and the app shares its single recording machinery
between the global PTT and the per-task amend.

### `src/mac_window.py` — make_always_visible

PyObjC shim. After a Qt widget is shown, fetches its NSView via
`widget.winId()`, gets the NSWindow, and:

- `setLevel_(25)` — NSStatusWindowLevel, above all app windows
- `setCollectionBehavior_(canJoinAllSpaces | stationary)` — visible on every desktop space
- `setHidesOnDeactivate_(False)` — overrides the default NSPanel hide-on-deactivate that makes Tool windows vanish when the owning app loses focus

No-op on non-darwin or if PyObjC is missing.

### `src/app.py` — CurbyApp

The glue. Holds:

- `VoiceIndicator` (cursor-anchored)
- `TaskManager`
- `TextInputPopup` (alternate input via `Ctrl+.`)
- `CursorTracker` driving the voice indicator's `follow(x, y)`
- `PTTListener` driving the recording toggle
- A single `_record_thread` + `_record_stop` event shared between the global
  PTT (utterance → new task) and per-task amend (utterance → `runner.amend(text)`).
  Recording target is tracked in `_record_target`: `None` for new task,
  `Task` instance for amend.

---

## Threads

- **Qt main thread** — UI, event loop, Qt signal slot handlers
- **CursorTracker** — pynput mouse listener (its own thread)
- **PTTListener** — pynput keyboard listener (its own thread)
- **Recording thread** — short-lived, one per recording session; reads mic chunks, runs Google STT, emits result back via `transcription_ready` / `transcription_error` signals
- **AgentRunner reader threads** — one per running task, blocking-read from the claude subprocess stdout, dispatch JSON events as bridge signals

All cross-thread communication into Qt widgets goes through `pyqtSignal` to
ensure handlers run on the main thread.

---

## macOS specifics

- **Screen Recording permission** — preflighted via `Quartz.CGPreflightScreenCaptureAccess()` so failures show a clear hint instead of `mss` hanging.
- **pynput "process is not trusted" warning** — emitted on listener start when Accessibility is missing for the executing binary; pynput still works in most configurations, the warning is informational.
- **NSPanel hide-on-deactivate** — every overlay calls `make_always_visible` after `show()` to override this and lift the level to NSStatusWindowLevel.
- **Activation policy** — `setActivationPolicy_(2)` in `main.py` (no dock icon, no menu bar). The always-visible shim makes the app's own activation state irrelevant for overlay visibility.

---

## Legacy guidance pipeline (dormant)

The repository still contains the original on-screen guidance system:

- `src/ghost_cursor.py` — fairy cursor with palette states + sparkles + animation
- `src/guide_path.py` — dotted-footstep path overlay
- `src/action_highlight.py` — bounding-box + action-icon overlay
- `src/speech_bubble.py` — instruction bubble at the target
- `src/ai_client.py`'s `ask_guided_step` — vision-based step prompting via Claude CLI
- `src/ai_client_api.py` — Anthropic Computer Use beta API path

None of these are imported by the current `app.py`. The plan is to bring
them back behind a phrase trigger (e.g. _"show me how to…"_) as an opt-in
guided mode, separate from the agent dispatcher.

---

## Configuration knobs

- `CLAUDE_CLI` — override the resolved `claude` binary path
- `CURBY_SAFE_MODE=1` — recognized in legacy ghost-cursor code path; unused in the agent-dispatch flow
