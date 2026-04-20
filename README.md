# Curby — the cursor buddy

A desktop AI assistant that lives near your mouse cursor. Press a hotkey, ask a question, get an answer grounded in what's on your screen right now. Works in **voice mode** (speak / hear) or **voiceless mode** (type / read) — same brain, pick whichever fits the room.

For the full architecture, see [`design.md`](./design.md).

---

## Requirements

- Windows 10 / 11
- Python 3.14
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-code) on PATH (`claude.exe`)
- Microphone + speakers (voice mode only)

Install dependencies:
```powershell
pip install -r requirements.txt
```

## Run

```powershell
$env:PATH += ';C:\Users\tarun\.local\bin'
cd C:\Users\tarun\dev\cursor_buddy
python main.py
```

You'll hear "curby ready" and a small grey dot will appear near your cursor — that's Curby waiting for a hotkey.

---

## How to try voice mode

**Hotkey:** `Ctrl+/`

1. Press `Ctrl+/` — the dot turns orange (listening).
2. Speak a question, e.g. _"what's in this window?"_
3. Stop talking — Claude replies out loud.

### Try a guided request
Ask Curby to walk you through a UI task:

> _"how do I bold text in this app"_

- The ghost cursor animates to the first target and speaks the step.
- Do the step yourself.
- Press `Ctrl+/` again to advance — Curby re-screenshots and guides you to the next element.
- Repeat until done.

### Example voice prompts
- _"what does this button do?"_
- _"summarize what's on screen"_
- _"how do I create a new file here?"_
- _"where do I click to add a breakpoint?"_

---

## How to try voiceless mode

For libraries, meetings, or shared spaces. **No mic, no speakers needed.**

**Hotkey:** `Ctrl+.`

1. Press `Ctrl+.` — a small text box pops up near your cursor.
2. Type your question, press `Enter`.
3. A speech bubble appears near the cursor with Claude's reply. It auto-dismisses after ~6 seconds, or press `Ctrl+.` again to dismiss early.
4. Press `Esc` in the text box to cancel without sending.

### Guided voiceless
Type a "how do I…" question and Enter:

> _"how do I open settings"_

- The ghost cursor animates to the target.
- A speech bubble appears **next to the ghost** with the written instruction (no auto-dismiss — it waits for you).
- Do the step yourself.
- Press `Ctrl+.` to advance to the next step. The bubble updates with the next instruction.

### Example voiceless prompts
(Same as voice — same brain.)
- _"what is this dialog asking?"_
- _"where do I click to add a breakpoint?"_
- _"explain this error"_
- _"walk me through adding a new file"_

---

## Cancel / restart

- **Press either hotkey while Curby is busy** (thinking, speaking, or showing a bubble) → cancels the current session and returns to idle.
- For voice mode, pressing `Ctrl+/` during a busy session also auto-starts a fresh voice session.

---

## Architecture at a glance

```
Hotkey → _Bridge signal → CurbyApp._activate_voice / _voiceless
              ↓
      AssistantWorker (QThread)
         mode = "voice" | "voiceless"
              ↓
   listen_once  OR  typed_text  (input)
              ↓
   grab_monitor_at / grab_region
              ↓
   ask_stream  OR  ask_guided_step  (Claude CLI subprocess, streaming)
              ↓
   speak()  OR  bubble.show_text()  (output)
```

Both modes share 95% of the code — only the input acquisition and output rendering differ at the edges. See [`design.md`](./design.md) for the full state diagram and per-module notes.

---

## Roadmap
- [x] Multi-turn conversation history
- [x] Guided cursor (Clicky-style adaptive per-screenshot loop)
- [x] Voiceless mode
- [ ] UIA-tree element resolution (stable across DPI / window moves)
- [ ] MPLAB / IDE context injection
