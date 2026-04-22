# Curby

A desktop AI companion that lives on your screen, watches what you're doing, and walks you through UI tasks one step at a time. A small glowing fairy floats beside your cursor. Tell it what you want to do — it animates across the screen and shows you exactly what to click next.

Always listening. Conversational. Works in any Windows app.

---

## Quick start

**Prereqs** — Windows 10 / 11, Python 3.14, [Claude CLI](https://docs.anthropic.com/en/docs/claude-code) installed (`claude.exe` on PATH).

```powershell
git clone https://github.com/CasterlyGit/curby---the-cursor-buddy.git
cd curby---the-cursor-buddy
pip install -r requirements.txt
python main.py
```

The fairy appears next to your cursor. Mic opens automatically — you'll hear "curby ready, listening." Just start talking.

---

## Hotkeys

| Key | What it does |
|---|---|
| **(nothing)** | curby auto-starts listening when you launch — talk any time |
| `Ctrl+/` | **reset** — cancel whatever curby is doing and keep listening |
| `Ctrl+.` | **type** a prompt instead of speaking |
| `Ctrl+M` | **advance** to the next guided step |
| `Esc` | **close** curby |

**Voice-advance also works.** While curby is parked on a step waiting for you, short phrases like `"next"`, `"got it"`, `"done"`, `"ok"`, `"continue"`, `"what's next"`, `"keep going"`, `"i did it"` move to the next step just like pressing `Ctrl+M`.

---

## How to use

Just talk. Curby's mic is open the moment it launches — no wake word, no hotkey needed.

### Ask a guided question

> _"how do I enable dark mode in vs code"_
> _"where do I add a breakpoint"_
> _"walk me through creating a new file"_

The fairy animates from your cursor to the first target element. A dotted path shows the route, a highlighted box marks the thing to touch, and a speech bubble tells you what to do and why. Curby also says the step out loud.

### After you do the step

Just say **"next"** or **"done"**, or press **`Ctrl+M`**. Curby re-reads the screen, figures out what's next, and animates to the new target.

You can **interrupt mid-animation too** — if you want to ask a clarification or change the task, just speak. Curby stops the current flow and responds.

### Ask for information

> _"what does this button do?"_
> _"summarize what's on screen"_
> _"explain this error"_

Curby sees the screen and replies out loud. Text appears in the status window as it speaks.

---

## What you see on screen

| Element | Color = what's happening |
|---|---|
| **Fairy** (glowing swoosh near cursor) | always visible |
| **Violet rings / halo** | idle / waiting |
| **Pink ripples + warm palette cycle** | listening (mic open, hearing you) |
| **Gold shimmer + breathing** | thinking (asking Claude) |
| **Mint rings** | speaking (TTS playing) |
| **Red rings** | error |
| **Cool blue-indigo body** | pointing — animating to a target |
| **Dotted path** | guiding — follow the route to the target |
| **Outlined box + action badge** | the exact element to act on (CLICK / TYPE / CLOSE / …) |
| **Speech bubble** | instruction text floating near the target |
| **Pink mini-ripple at tip (during pointing)** | curby is pointing AND still listening |
| **Status window (top-right)** | state dot + rolling chat of what you said and what curby said |

Nothing is clickable. Every overlay is click-through — your mouse goes straight to the app underneath.

---

## Status window

Top-right of your primary screen. Movable (drag the header), collapsible (double-click the header), semi-transparent. Shows:
- State dot matching the fairy (violet / pink / gold / mint / red)
- Rolling transcript: `you: <what you said>` and `curby: <what curby said>` — last 12 lines
- Auto-updates live as curby speaks, not only at the end

---

## Accuracy modes

Curby picks its brain automatically:

- **API + Computer Use** — if `ANTHROPIC_API_KEY` is set in your environment, curby calls Claude directly with the pixel-calibrated Computer Use tool. Coordinates land dead-center.
- **CLI fallback** — otherwise curby pipes screenshots and prompts to `claude.exe`. Coordinates are vision-estimated; accuracy depends on the app and Claude's read of the screen.

To switch on the accurate path:

```powershell
setx ANTHROPIC_API_KEY "sk-ant-…"   # opens new shells with it set
# …or for this shell only:
$env:ANTHROPIC_API_KEY = "sk-ant-…"
python main.py
```

Model selection (default `claude-sonnet-4-5`):

```powershell
$env:CURBY_MODEL = "claude-opus-4-5"
```

---

## Multi-monitor

Curby clamps the fairy to the screen your cursor is currently on — it can cross between monitors but won't drift into dead zones between mismatched displays. Guidance captures only the screen the cursor is on when you start a session.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Fairy doesn't appear | `claude.exe` not on PATH | `where claude` — install the Claude CLI and re-open the shell |
| Mic doesn't pick up | Windows privacy setting or another app holding the mic | Settings → Privacy → Microphone; check default input device |
| "speech service unreachable" | Google Web Speech API can't reach | curby's STT uses Google; needs internet. Swap to an offline STT is a follow-up. |
| Nothing happens on hotkey | another app grabbed `Ctrl+/`, `Ctrl+M`, or `Esc` | run curby from an elevated shell, or edit the constants at the top of `src/app.py` |
| "couldn't capture the screen" | Windows blocked screen access | System Settings → Privacy → Graphics → allow desktop apps |
| Pointer lands near but not on target | CLI path (vision-estimate) | set `ANTHROPIC_API_KEY` for pixel-exact Computer Use |

---

## Docs

- **[design.md](design.md)** — architecture, components, threading, visual pipeline, palette
- **[MANAGERS_GUIDE.md](MANAGERS_GUIDE.md)** — a professional one-pager for team leads: pitch, audience, visual walk-through, roadmap

---

## License

MIT.
