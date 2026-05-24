# Curby

**Status:** v0.3 — quick-ask voice loop, mystical feather indicator, floating answer note, OAuth fast backend, voice meta-commands.

**[▶ Live demo](https://casterlygit.github.io/curby/)** — interactive walkthrough: simulated macOS desktop, hit Ctrl+Space, watch a task puck spawn and stream through running → done states.

A voice-driven desktop companion for Claude. Two modes share one app:

- **Quick-ask** — `Ctrl+Space`, speak a question, hear a short answer in ~1 second. Conversational follow-ups, voice-set style preferences ("be shorter", "more detail"), Ava (Premium) TTS at 220 WPM. A floating note shows the answer text + latency in the top-right.
- **Agent dispatch** — `Ctrl+Shift+Space`, speak a task, watch an autonomous Claude Code agent run it in a sandbox with a live status puck on the desktop.

A small mystical feather (the "ghost cursor") sits next to the answer note as a state indicator — its color shifts violet → pink → gold → mint through idle / listening / thinking / speaking, with a soft aura that ripples into the background.

Cross-platform under the hood, currently tuned for macOS.

---

## Highlights

- **Quick-ask in ~1-1.5s.** `Ctrl+Space` → speak → spoken Claude reply via Ava (Premium). Pluggable backends: `claude_cli` (slow default, works on any Max plan with no setup), `api_key` (fast, needs $5 in API credits), or a custom Python file you drop at any path in your config.
- **Conversational follow-ups.** A 60-second window keeps prior turns in context — say "what are websockets" → "but what does full-duplex mean" → and the model sees the prior exchange.
- **Voice meta-commands.** Say *"be shorter"*, *"more detail"*, *"explain like I'm five"*, *"go back to normal"* — Claude semantically recognises these as style instructions (no keyword matching) and applies them to all future answers.
- **Interrupt mid-speech.** Tap `Ctrl+Space` while Ava is still talking — TTS is killed and curby starts listening immediately.
- **Mystical feather indicator.** Constantly-animated companion that shows curby's state via color (violet/pink/gold/mint/red) and a soft pulsing aura. Lives next to the answer note in the top-right; not coupled to your cursor (avoids input lag).
- **Floating answer note.** Top-right blue panel that shows the latest reply + latency. Drag it anywhere, click the `—` icon to collapse to a pulsing dot; the dot's pulse color reflects what curby is doing even when minimized.
- **Agent dispatch on `Ctrl+Shift+Space`.** Same voice-to-agent flow as v0.1 — sandboxed `claude -p` per task, neon-cursor puck on the right edge with pause / cancel / amend controls.
- **Pre-warmed startup.** First Ctrl+Space avoids cold-path costs (module import, keychain read, TCP+TLS handshake) — backend is warmed in the background as curby launches.
- **Pidfile lifecycle.** Stale curby instances are killed on startup; overlays never linger after a force-kill.

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

Recommended one-time setup for the best feel:

1. **Install Ava (Premium)** — System Settings → Accessibility → Spoken Content → System Voice → click (i) → download "Ava (Premium)" (~100 MB). Vastly more natural than the default.
2. **Pick a fast backend** — drop a config at `~/.curby/config.json`:
   ```json
   {
     "voice": "Ava (Premium)",
     "rate": 220,
     "backend": "api_key",
     "api_key": "sk-ant-..."
   }
   ```
   Without `backend`, quick-ask uses `claude_cli` (~7s per turn). With `api_key` (or any custom backend file you point at), expect ~1-2s.

### Auto-start at login

```bash
./scripts/install-autostart.sh
```

Installs `com.casterly.curby` as a LaunchAgent so curby launches every time you log in. Logs at `/tmp/curby.log`. Uninstall via `launchctl unload ~/Library/LaunchAgents/com.casterly.curby.plist && rm ~/Library/LaunchAgents/com.casterly.curby.plist`.

---

## How to use

### Talk to it

| Key | What it does |
|---|---|
| **`Ctrl+Space`** (toggle) | **quick-ask** — voice question → short spoken Claude answer in the answer note. First tap opens mic, second tap sends. Mid-speech tap interrupts + starts new question. |
| **`Ctrl+Shift+Space`** (toggle) | spawn an agent task — voice → sandboxed Claude Code agent with a status puck. |
| `Ctrl+.` | type a prompt instead of speaking (agent only) |
| `Esc` | quit |

### Quick-ask in practice

- Tap `Ctrl+Space`, ask *"what are WebSockets?"* → hear a short analogy-led answer (~1-2s).
- Tap again (within 60s), ask *"but what does full-duplex mean?"* → Claude sees the prior turn, gives a contextual follow-up.
- At any point, say one of:
  - *"be shorter"* → all future replies under 10 words
  - *"more detail"* → 2-3 sentence answers
  - *"more technical"* → engineering-tier vocabulary
  - *"explain like I'm five"* → fully simplified
  - *"go back to normal"* → reset both style + conversation
- Tap the `—` button on the answer note to collapse it to a pulsing dot. Color + speed mirror state (blue idle, pink listening, violet thinking, mint speaking). Click the dot to expand.
- Every quick-ask is logged to `~/.curby/quick-ask-log.jsonl` with prompt / reply / latency / `was_followup` for cost analysis.

### Agent dispatch

Same as before. `Ctrl+Shift+Space`, speak a task, a sandboxed agent picks it up in `~/curby-tasks/<timestamp>-<slug>/`. Hover the puck for pause / cancel / amend.

---

## Architecture overview

See [design.md](design.md) for the full breakdown. The short version:

- **`PTTListener`** — pynput chord watcher.
- **`voice_io.record_until_stop`** — sounddevice + scipy + Google STT, streams per-chunk RMS as audio level callbacks.
- **`GhostCursor`** — the mystical feather. Frameless Qt widget with state-driven color + soft aura. Pinned next to the answer note (decoupled from system cursor to avoid macOS input lag).
- **`AnswerNote` + `CollapsibleFloater`** — top-right text panel showing the latest quick-ask reply. Inherits the claude-meter-style collapsible-floater pattern.
- **`quick_ask` + `quick_ask_backends/`** — pluggable backend system (`claude_cli`, `api_key`, custom-file). Conversation history + system prompt addendum support.
- **`preferences`** — semantic style preferences detected via the model itself (no keyword matching).
- **`AgentRunner`** — wraps one `claude` subprocess per agent task with stream-json parsing, SIGSTOP/SIGCONT pause, SIGTERM/SIGKILL cancel, `--continue` queueing.
- **`pidfile`** — kills stale curby instances on startup; prevents orphan overlays after force-kills.
- **`mac_window.make_always_visible`** — PyObjC shim that pins overlays at NSStatusWindowLevel + `canJoinAllSpaces`.

---

## Roadmap

Shipped:
- [x] v0.1 — voice → agent dispatch with task pucks
- [x] v0.2 — Premium voice picker, claude-meter-style collapsible answer note
- [x] v0.3 — quick-ask voice loop, conversational follow-ups, voice meta-commands, OAuth fast backend, ghost-cursor feather indicator, interrupt mid-speech

Open:
- [ ] Persistent claude subprocess that doesn't accumulate context (#20)
- [ ] Configurable TTS voice + rate UI (currently config-file only) (#16)
- [ ] Visual animations alongside spoken answers (concept library)

---

## License

MIT.
