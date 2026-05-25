# Curby — Architecture & Design

Technical companion to the README. Covers both modes, why things are the way they are, where the latency goes, and what breaks how.

---

## Architecture at a glance

### Quick-ask (Ctrl+Space)

```
 Ctrl+Space ──► PTTListener ──► CurbyApp (recording state)
                                     │
                          ┌──────────▼──────────┐
                          │  record thread       │
                          │  sounddevice → WAV   │
                          │  → Google STT        │
                          └──────────┬──────────┘
                                     │ transcribed text
                                     ▼
                              quick_ask.run_quick_ask()
                                     │
                     ┌───────────────┼─────────────────┐
                     ▼               ▼                  ▼
               api_key backend   claude_cli      custom .py file
               (Anthropic API)   backend           (config path)
                     └───────────────┬─────────────────┘
                                     │ (reply, latency_ms)
                                     ▼
                              quick_ask.speak_reply()
                                     │
                         ┌───────────┴───────────┐
                         ▼                       ▼
                  AVSpeechSynthesizer      `say` subprocess
                  (in-process, fast)       (fallback)
                         └───────────┬───────────┘
                                     ▼
                              AnswerNote overlay
                              (reply text + latency)
```

### Agent dispatch (Ctrl+Shift+Space)

```
 Ctrl+Shift+Space ──► PTTListener ──► CurbyApp
                                           │
                                  ┌────────▼────────┐
                                  │  record thread   │
                                  │  sounddevice     │
                                  │  → Google STT    │
                                  └────────┬────────┘
                                           │ transcribed text
                                           ▼
                                    TaskManager.spawn()
                                           │
                                    AgentRunner.start()
                                           │
                          ┌────────────────▼────────────────┐
                          │  claude -p --dangerously-skip-   │
                          │  permissions --output-format     │
                          │  stream-json <prompt>            │
                          │  cwd: ~/curby-tasks/<ts>-<slug>  │
                          └────────────────┬────────────────┘
                                           │ stdout: JSON events
                                    ┌──────▼──────┐
                                    │ reader thread│
                                    │ parse events │
                                    └──────┬──────┘
                                           │ Qt signals (via _Bridge)
                                           ▼
                                    DockedTaskPuck
                                    (live status + controls)
```

---

## Latency breakdown — quick-ask

**Target: ~1–1.5 s with `api_key` backend on M-series Mac**

| Phase | Typical cost | Notes |
|---|---|---|
| Mic open + first chunk | ~30 ms | sounddevice opens the default input device |
| Speech capture | variable | ends when user taps Ctrl+Space again |
| Google STT | ~200–400 ms | network round-trip to Google speech endpoint |
| Pre-warm overhead | ~0 ms | backend module + TLS primed at startup |
| Anthropic API (haiku) | ~300–600 ms | TTFT ~200 ms + ~10 tok/reply |
| `speak_reply` → AVSynth | ~100–150 ms | voice engine stays loaded in-process |
| **Total (API backend)** | **~700–1200 ms** | wall-clock from tap-to-first-syllable |
| `claude_cli` backend | ~6–8 s | adds CLI bootstrap: hooks, plugin sync, harness |

**Why we pre-warm:** `CurbyApp.run()` fires `_prewarm()` in a background thread. It imports the backend module, reads the API key from keychain, and opens the TCP+TLS connection. Without pre-warm the first Ctrl+Space pays ~200 ms of import + ~300 ms of TLS setup on top of the numbers above.

**Why AVSpeechSynthesizer over `say`:** `say` spawns a new process each time, paying ~200–400 ms of cold-load cost. `AVSpeechSynthesizer` is loaded in-process at first use and stays resident, so subsequent calls pay near-zero startup.

---

## Key design decisions

### Pluggable backends (`claude_cli` / `api_key` / custom file)

**Why:** The default `claude_cli` backend requires no API key — it works on any Claude Max plan with `claude` on PATH. But it's slow (~7 s) because every call starts a new `claude -p` process that boots the full CLI harness. The `api_key` backend bypasses the harness entirely and calls the Anthropic API directly, cutting latency to ~1 s. A custom file path lets you swap in any function with the signature `ask(prompt, system, model) -> (str, int)` — no config schema to update.

**Fallback contract:** If the configured backend raises, `run_quick_ask` falls back to `claude_cli` so the user always gets an answer, just slower.

### Tkinter → Qt (why PyQt6)

The original v0.1 used Tkinter for pucks and overlays. Two problems: Tkinter windows can't be pinned above all Spaces without undocumented hacks, and the puck expand/collapse animation requires sub-frame repaints that Tkinter can't do smoothly. PyQt6 gives us `QTimer` for animation, `QPainter` for custom glyph rendering, and the NSPanel-level hooks we need via winId(). Cost: +~80 MB on disk.

### Pidfile lifecycle (`src/pidfile.py`)

macOS LaunchAgent restarts curby on crash. Without a pidfile check, a second instance starts while the first is still running (or its zombie overlays are still visible). On startup, `pidfile.take_over()` reads the saved PID, sends SIGTERM to any matching process, waits for it to exit, then writes its own PID. This means two clean rules: "at most one curby" and "overlays never linger after force-kill".

### GhostCursor pinned near AnswerNote (not tracking the system cursor)

Tracking `QCursor.pos()` and moving a window to it every 16 ms causes macOS to queue input events, creating perceivable lag on pointer moves. The ghost cursor lives next to the AnswerNote (top-right corner) and doesn't track the system cursor at all. State changes (idle → listening → thinking → speaking → error) are communicated via color + pulse, not position.

### Conversation history via session JSON (not subprocess `--continue`)

`--continue` works by re-entering the same workdir. But agent dispatch tasks each have their own workdir, and quick-ask now uses the direct API path where there's no workdir. Instead, quick-ask tracks history in memory (within the 60 s follow-up window) and passes it directly to the Anthropic API as `messages`. This is cleaner, faster, and doesn't depend on Claude CLI's session storage.

---

## Failure modes

| Failure | Symptom | Recovery |
|---|---|---|
| No Accessibility permission | pynput logs "process is not trusted" | works on most setups; if not, user grants permission in System Settings → Privacy |
| No microphone permission | `sounddevice` open fails | logged to stderr; curby stays up, quick-ask shows error state in ghost cursor |
| Google STT network error | `UnknownValueError` / timeout | `on_transcription_error` signal fires; ghost cursor → red error state; user can retry |
| `api_key` backend error | `anthropic.APIError` | falls back to `claude_cli`; log line written |
| `claude_cli` subprocess not found | `FileNotFoundError` | caught, shown in AnswerNote as "claude not found — is it on PATH?" |
| AVSpeechSynthesizer unavailable | import error (not macOS) | falls back to `say` subprocess; then pyttsx3 as last resort |
| Stale pidfile (previous crash) | curby starts while orphan overlays exist | `pidfile.take_over()` sends SIGTERM to old PID on startup |
| AgentRunner reader thread crash | puck stuck in "thinking…" | `on_done(-1)` fires; puck moves to `error` state; user can dismiss |
| `claude` subprocess exits non-zero | reader gets EOF | `on_done(rc)` fires; status set to `error (rc=N)` |
| Mid-speech Ctrl+Space interrupt | two recording sessions could overlap | `_record_stop.set()` is called before the new session starts; recorder thread joins before new mic open |

---

## Observability

Every quick-ask appends a JSONL entry to `~/.curby/curby.log` (structured logging added in v0.4):

```json
{
  "ts": "2026-05-25T10:03:12.441Z",
  "event": "quick_ask",
  "backend": "api_key",
  "ttft_ms": 210,
  "total_ms": 890,
  "tts_ms": 140,
  "was_followup": false,
  "error": null
}
```

Agent dispatch events are logged similarly with `"event": "agent_dispatch"`.

Tail the log with color:

```bash
curby log
```

(Requires `rich` — `pip install rich`.)

---

## Thread model

| Thread | Owner | Blocked on |
|---|---|---|
| Qt main thread | `CurbyApp.run()` → `QApplication.exec()` | Qt event loop |
| CursorTracker | pynput mouse listener | OS cursor events |
| PTTListener | pynput keyboard listener | OS key events |
| Recording thread | `CurbyApp._start_recording()` | mic chunks → Google STT |
| AgentRunner reader (×N) | each `AgentRunner.start()` | subprocess stdout |
| Pre-warm thread | `CurbyApp._prewarm()` | network (API key + TLS) |

All cross-thread signal delivery into Qt widgets is via `pyqtSignal` / `_Bridge`, ensuring handlers run on the main thread.

---

## Configuration

`~/.curby/config.json` — all keys optional:

```json
{
  "backend": "api_key",
  "api_key": "sk-ant-...",
  "voice": "Ava (Premium)",
  "rate": 220
}
```

| Key | Default | Effect |
|---|---|---|
| `backend` | `"claude_cli"` | `"api_key"`, `"claude_cli"`, or absolute path to a custom `.py` file |
| `api_key` | `""` | Anthropic API key; also read from `ANTHROPIC_API_KEY` env var |
| `voice` | `"Ava (Premium)"` | Any AVSpeechSynthesizer voice name; falls through to `say -v` |
| `rate` | `220` | Words per minute |

Environment overrides:

| Var | Effect |
|---|---|
| `CLAUDE_CLI` | Override the resolved `claude` binary path |
| `ANTHROPIC_API_KEY` | API key (takes precedence over config file if set) |
| `CURBY_CI=1` | Disables microphone + display-dependent code paths in tests |
