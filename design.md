# Curby — design

A single-process Python desktop app. PyQt6 draws the UI, pynput handles global hotkeys and mouse tracking, mss grabs screenshots, Claude (via CLI or direct API) reads the screen and produces each guidance step. Speech is captured continuously via sounddevice + Google Web Speech, synthesized via SAPI5 pyttsx3. All on-screen overlays are frameless, always-on-top, and click-through.

---

## Architecture at a glance

```
                   ┌───────────────────────────────────────────┐
                   │                  CurbyApp                 │
                   │     (QApplication + signal _Bridge)       │
                   └──┬────────────────────────────────────────┘
                      │  Qt signals
   ┌──────────────────┼──────────────────┬──────────────────┬───────────────────┐
   │                  │                  │                  │                   │
   ▼                  ▼                  ▼                  ▼                   ▼
CursorTracker    GlobalHotKeys     ContinuousListener   AssistantWorker   TextInputPopup
(pynput bg)      (pynput bg)       (QThread, mic on)    (QThread)         (voiceless only)
   │                  │                  │                  │
   │cursor_moved      │hotkey_fired      │utterance          │ step text + TTS
   ▼                  ▼                  │ speech_start      │
 GhostCursor ◄──── app.py routes ────────┘ waiting            │
 GuidePath                                listen_error        │
 ActionHighlight                                              │
 SpeechBubble ◄───────────────────────────────────────────────┘
 StatusWindow
```

Six visual widgets, all frameless + translucent + click-through (except the text input popup, which has focus briefly):

| Widget | Role |
|---|---|
| **GhostCursor** (`src/ghost_cursor.py`) | The fairy. Always visible. Follow mode floats beside the cursor with ambient bob; pointing mode anchors to a guidance target. |
| **GuidePath** (`src/guide_path.py`) | A tight dotted bezier from the user's cursor to the current target. 44 dots light up sequentially as the fairy moves along the path. |
| **ActionHighlight** (`src/action_highlight.py`) | Rounded-rectangle reticle around the element to act on — corner brackets + pulsing glow + action badge (CLICK / TYPE / CLOSE / …). |
| **SpeechBubble** (`src/speech_bubble.py`) | Floating dark bubble with gradient border carrying the instruction text. Tail points at the target. |
| **StatusWindow** (`src/status_window.py`) | Movable semi-transparent chat log in the top-right. State dot + rolling transcript of what the user said and what curby said. |
| **TextInputPopup** (`src/text_input_popup.py`) | Only for voiceless mode (`Ctrl+.`). The only widget that takes keyboard focus, and only while accepting a prompt. |

---

## Conversation model — always-listening

The mic is open from the moment `main.py` starts. No wake word, no hotkey gate. `ContinuousListener` runs as a QThread that loops:

```
listen_once(on_speech_start=…) ────┐
  ├─ RMS under threshold for 10s   │ loop silently (normal)
  ├─ RMS crossed threshold         ├── emit speech_start
  ├─ silence after speech          ├── transcribe via Google
  └─ failure                       └── emit listen_error
                                    ↓
                          emit utterance(text)
                                    ↓
            app decides: advance-phrase? or new query?
```

**Voice-advance phrases** (`"next"`, `"got it"`, `"done"`, `"ok"`, `"continue"`, `"what's next"`, `"keep going"`, `"i did it"`, etc.) are pattern-matched by `_is_advance_phrase()`. If a session is parked on a guided step waiting for the user to act, the phrase sets `step_event` — same behavior as `Ctrl+M`.

**Anything longer / not an advance phrase** is treated as a new query. Curby cancels the in-flight worker (if any), starts a fresh `AssistantWorker` with `heard_text=…`, and the new intent takes over.

**The listener never auto-pauses after emitting**. It stays open through thinking / speaking / pointing animations so the user can interrupt at any point. The only time the mic is muted is during actual TTS playback: `voice_io.speak()` fires `on_speak_start` (pause) and `on_speak_end` (resume) callbacks so curby never hears its own voice.

---

## State & modes

Two orthogonal axes drive every visual:

**Mode** — where the fairy is anchored.
- `follow` — tracks the cursor with spring damping + ambient bob. Pink body (fairy identity).
- `pointing` — anchored to a guidance target; cool-blue body; gentle lean.

**State** — what curby is doing internally. Each state has ONE dominant hue so the fairy's color tells the story at a glance:
- `listening` → pink-hot `#EC4899` (mic open)
- `thinking` → gold `#FDE047` (asking Claude)
- `speaking` → mint `#34D399` (TTS playing)
- `error` → red `#EF4444`
- `idle` → violet `#A78BFA` (mic off / before start)

`listening` is the default state whenever the listener is running — that's why the fairy stays pink through almost every moment of interaction.

**Special overlays that layer on top** without changing the body color:
- Gold shimmer running along the swoosh during `thinking`
- Concentric pink ripples from the tip during `listening + follow`
- Small pink mini-ripple + bead at the tip during `listening + pointing` (the mid-animation listening underscore)
- White expanding flash on any mode change

---

## Hotkey semantics

| Key | Rule |
|---|---|
| `Ctrl+/` | **reset** — cancel current worker, clear all overlays, keep listener alive. Does NOT quit curby. |
| `Ctrl+.` | open the text input popup (only used when speaking isn't possible) |
| `Ctrl+M` | advance the current guided step (same as a voice-advance phrase) |
| `Esc` | hard close — stop listener, cancel worker, `QApplication.quit()` |

---

## Component contracts

### `CurbyApp` — `src/app.py`

Owns the Qt application, the signal bridge, all widgets, the cursor tracker, the global-hotkey listener, the continuous listener, and the worker lifecycle. Single point that wires everything together.

Key handlers:
- `_on_listener_utterance(text)` — fired whenever the listener returns transcribed text. Pushes the text to status, flips state to `thinking`. Checks `_is_advance_phrase()` → if a guided session is waiting, sets `step_event` and returns. Otherwise cancels any in-flight worker and starts a fresh one with `heard_text=text`.
- `_activate_voice()` (Ctrl+/) — reset semantics. Cancel worker, clear overlays, keep listener running.
- `_activate_voiceless()` (Ctrl+.) — open the text popup.
- `_advance_step()` (Ctrl+M or advance phrase) — set `step_event` if a guided step is waiting.
- `_quit_app()` (Esc) — clean shutdown.

### `AssistantWorker` — `src/app.py`

QThread per query. Accepts input via one of three paths:
- `heard_text` — pretranscribed from the continuous listener
- `typed_text` — from the voiceless popup
- live `listen_once()` — legacy one-shot voice mode (not used in the always-listening flow)

Routes to either the conversational path (single reply, TTS) or the guided path (multi-step loop), based on `_is_guided(text)`. The guided path is preferred — `_is_guided` only falls through to conversation for obvious chit-chat (`"hi"`, `"thanks"`, `"joke"`, etc.).

Emits `sentence_heard(str)` per sentence immediately before TTS plays, so the status chat updates live instead of only at the end.

### AI dispatch — `src/ai_client.py`

One entry point: `ask_guided_step(task, image, steps_done) → (text, x, y, box, action)`.

Picks automatically between:
- **API path** (`src/ai_client_api.py`) — direct Anthropic SDK call with `tools=[{"type": "computer_20250124"}]` and the `anthropic-beta: computer-use-2025-01-24` header. Screenshot is resized to an aspect-matched Computer Use resolution (1280×800 / 1366×768 / 1024×768). Claude's `tool_use` block is parsed for the pixel coordinate, then scaled back to screen coords.
- **CLI path** — pipes image + prompt to `claude.exe -p --input-format stream-json --output-format stream-json`. System prompt constrains output to a single-line trailing-tag format: `… [POINT:x,y:label] [BOX:x1,y1,x2,y2] [ACTION:click|type|close|select|drag|open]`.

Returns `[POINT:none]` / `None` coords when the task is already complete or the next step isn't on the current screen. The conversational narrative is still returned in that case and spoken aloud.

### `GhostCursor` — `src/ghost_cursor.py`

Paints the fairy every 16 ms. Public API:
```python
follow(x, y)        # cursor moved — drift toward (x + offset, y + offset)
set_state(state)    # idle | listening | thinking | speaking | error
show_at(x, y)       # hard place at (x, y); enter pointing mode
animate_to(x, y)    # snap to user's real cursor, then ease to (x, y)
release()           # return to follow mode; stay visible
```

Every `animate_to` starts from the user's **real cursor** position (tracked in `_real_user_x/_y`), not from wherever the ghost last landed — so each guided step reads as a consistent "from here to there" sweep.

Per-screen clamping via `QApplication.screenAt(cursor)` keeps the widget on whichever monitor the user is on.

### `ContinuousListener` — `src/continuous_listener.py`

QThread running the always-listening loop. Emits:
- `waiting` — mic is open, listening for speech
- `speech_start` — RMS crossed the speaking threshold
- `utterance(text)` — transcribed text after silence
- `listen_error(msg)` — mic unavailable, STT service unreachable, etc.

Supports `pause()` / `resume()`, called by `voice_io.speak()` callbacks to silence the mic during TTS playback only.

### `StatusWindow` — `src/status_window.py`

Movable, frameless, semi-transparent. Drag the header to move, double-click to collapse. Auto-scrolls a rolling transcript capped at 12 lines. State dot matches the unified palette.

---

## Palette

One coherent accent system across every widget.

| Token | Hex | Use |
|---|---|---|
| pink-hot | `#EC4899` | listening — fairy ripples, state dot, halo |
| pink-soft | `#F472B6` | fairy body, sparkles, listening palette cycle |
| rose | `#FB7185` | body end-stop, listening palette |
| fuchsia | `#D946EF` | listening palette |
| violet | `#A78BFA` | idle rings, status idle dot |
| sky-300 | `#7DD3FC` | pointing body start, footstep trail |
| blue-500 | `#3B82F6` | pointing body mid |
| indigo-600 | `#4F46E5` | pointing body end, path beacon |
| mint | `#34D399` | speaking rings, drag/open action |
| gold | `#FDE047` | thinking shimmer, thinking rings |
| amber | `#FBBF24` | secondary thinking accent |
| red | `#EF4444` | close action, error |
| white-hot | `#FFFFFF` | tip glow, path dot cores, corner brackets |

---

## File layout

```
src/
├── app.py                  CurbyApp + AssistantWorker + _Bridge + hotkey wiring
├── ai_client.py            CLI dispatch, guided system prompt, tag parser
├── ai_client_api.py        Anthropic SDK + Computer Use path
├── ghost_cursor.py         The fairy widget
├── guide_path.py           Dotted path overlay
├── action_highlight.py     Target reticle overlay
├── speech_bubble.py        Instruction bubble widget
├── text_input_popup.py     Voiceless text input widget
├── status_window.py        Floating transcript / state window
├── continuous_listener.py  Always-on mic QThread
├── screen_capture.py       mss-based region / monitor captures
├── cursor_tracker.py       pynput cursor listener → Qt signal
├── voice_io.py             Mic capture, STT (Google), TTS (SAPI5), speak callbacks
└── buddy_icon.py           (retired — not imported)
```

---

## Thread model

| Thread | Owner | Purpose |
|---|---|---|
| Main (Qt) | `CurbyApp` | widget painting, signal dispatch |
| Cursor tracker | pynput background | mouse position → `cursor_moved` signal |
| Hotkey tracker | pynput background | global hotkeys → Qt signals |
| `ContinuousListener` | QThread | `listen_once` loop, transcription, emit utterances |
| `AssistantWorker` | QThread per query | screen capture, Claude call, TTS, guided loop |
| TTS playback | daemon thread (inside `voice_io.speak`) | pyttsx3 engine run |

Rules:
- Worker threads never touch widgets directly. Every cross-thread update goes through `_Bridge` pyqtSignals, queued to the main thread.
- Cancel is a `threading.Event` checked in every worker loop iteration.
- Advance is a separate `threading.Event` set by either the hotkey handler or the voice-advance path.
- The continuous listener is the only source of live audio; TTS pauses it via callbacks so curby never feeds back into itself.
