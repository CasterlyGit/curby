# Curby

A voice-driven agent dispatcher that lives on your desktop. Hold a key, talk,
and curby spawns an autonomous Claude Code agent in its own sandbox to do
the work — coding, file operations, scraping, app scaffolding, anything you
can describe. Each task gets a small neon-cursor puck that docks on the
right edge of your screen with live status and pause/cancel/amend controls.

Cross-platform under the hood, currently tuned for macOS.

---

## Highlights

- **Voice → autonomous agent in one keypress.** `Ctrl+Space` → speak → a sandboxed Claude Code agent picks up the task and runs it to completion.
- **Per-task neon-cursor pucks** dock on the screen edge with live status, pause / resume / cancel / amend controls, and persist across all macOS spaces and over every app.
- **Real process control** — pause via `SIGSTOP` to the agent's process group, cancel via `SIGTERM` → `SIGKILL`, amend via `claude --continue` queueing.
- **Cross-app overlays** built on a custom PyObjC shim that pins Qt windows at `NSStatusWindowLevel` with `canJoinAllSpaces`, so they survive Mission Control and Spaces switches.
- **Streaming everything** — STT chunks drive a reactive cursor indicator; agent stdout is parsed live as `stream-json` so the puck reflects what the agent is doing in real time.

---

## Quick start

**Prereqs** — Python 3.12+, [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed (`claude` on PATH), microphone with system permission, and on macOS: Accessibility permission for your terminal/Python (pynput needs it for the global hotkey listener).

```bash
git clone https://github.com/CasterlyGit/curby.git
cd curby
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

A small dark pill with reactive cyan bars appears next to your cursor — that's curby. Bars bob slowly when idle, light up when listening, sweep orange while transcribing.

---

## How to use

### Talk to it

1. Tap **`Ctrl+Space`** — bars brighten, mic opens.
2. Speak: _"clean up empty folders on my Desktop"_, _"make me an app that shows a high-protein Indian recipe each day"_, _"summarize the README in this folder"_.
3. Tap **`Ctrl+Space`** again — transcription runs, then a new task puck appears on the right edge.

### Watch a task

Each task gets its own dark puck with a neon cursor inside. The pip in the
bottom-right tells you its state at a glance:

| Pip | State | Cursor color |
|---|---|---|
| spinning arc | running | per-task accent (rotates through 8 neon colors) |
| pulsing pause bars | paused | amber |
| green dot + checkmark | done | mint |
| red X | error / cancelled | rose |

**Hover** the puck — it expands a side panel to the left with the task title, latest live status, and contextual buttons. Move your mouse away — it collapses, and "done" pucks auto-dismiss once you've glanced at them.

### Buttons

While the agent is **running**:
- **pause** — SIGSTOP the agent process group (it freezes immediately)
- **cancel** — SIGTERM, SIGKILL after 2s
- **amend** — tap to start recording an additional instruction. Tap **send** to queue it; the agent will continue with `claude --continue` once the current step finishes.

When **paused**: pause becomes resume.

When **done / error**: only **amend** + **dismiss** remain.

### Type instead of speak

`Ctrl+.` opens a borderless text prompt near the screen center.

### Quit

`Esc` quits curby and cleanly cancels every running agent.

---

## Hotkeys

| Key | What it does |
|---|---|
| `Ctrl+Space` (toggle) | listen / send — first tap opens mic, second tap transcribes and spawns an agent |
| `Ctrl+.` | type a prompt instead of speaking |
| `Esc` | quit |

---

## Where tasks run

Each task spawns `claude -p --dangerously-skip-permissions --output-format stream-json --verbose <prompt>` in a fresh per-task sandbox dir:

```
~/curby-tasks/<timestamp>-<slug>/
```

The agent has full shell + filesystem access from that working directory. It can `mkdir`, write files, run scripts, install dependencies, drive Playwright, etc. — anything Claude Code in agent mode can do.

⚠️ Because of `--dangerously-skip-permissions`, voice prompts that involve destructive operations should be reviewed via the puck's status before letting them run unattended. Use **cancel** if a misheard prompt sends the agent somewhere wrong.

---

## Visual elements

| Element | Where | Always on top? |
|---|---|---|
| **Voice indicator** | follows your cursor | yes — across all desktop spaces |
| **Task puck** | right edge of primary screen, stacked top-down by spawn order | yes — across all desktop spaces |
| **Text prompt popup** | center of primary screen on `Ctrl+.` | yes |

All overlays are pinned at NSWindow status-bar level on macOS so they remain visible no matter which app is focused. They're click-through where it makes sense (voice indicator) and click-receiving where it doesn't (puck buttons).

---

## Architecture overview

See [design.md](design.md) for the full breakdown. The short version:

- **`PTTListener`** — pynput chord watcher, fires a single toggle when `Ctrl+Space` becomes fully held.
- **`voice_io.record_until_stop`** — sounddevice + scipy + Google STT, streams per-chunk RMS as audio level callbacks.
- **`VoiceIndicator`** — Qt widget anchored to cursor, reactive bars driven by the level callback.
- **`AgentRunner`** — wraps one `claude` subprocess per task with stream-json parsing, process-group SIGSTOP/SIGCONT for pause, SIGTERM/SIGKILL for cancel, and amend-via-`--continue` queueing.
- **`DockedTaskPuck` + `TaskManager`** — per-task floating widget; manager handles stacking, accents, auto-dismiss.
- **`mac_window.make_always_visible`** — PyObjC shim that elevates Qt overlays to NSStatusWindowLevel and sets `canJoinAllSpaces` so they persist across spaces and over every app.

---

## A note on the legacy guidance pipeline

Earlier versions of curby were an on-screen guide that animated a fairy cursor, drew dotted paths, and walked the user through UI tasks step by step. That code (ghost cursor, guide path, action highlight, `ai_client.py`'s `ask_guided_step`, etc.) still lives in this repo but is no longer wired into the active flow. The plan is to bring it back behind a "show me how to..." trigger phrase as an opt-in mode. Not a priority right now.

---

## License

MIT.
