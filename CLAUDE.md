# curby
Voice-driven desktop companion for Claude: quick-ask (Ctrl+Space → 1s spoken answer) + agent dispatch (Ctrl+Shift+Space → sandboxed Claude Code task with status puck). Status: v0.3, shipped + auto-starts via LaunchAgent.

## Key files
- `main.py` — entry point; sets NSApplicationActivationPolicyAccessory (no dock/focus steal); runs `CurbyApp`
- `src/app.py` — `CurbyApp`: Qt app orchestrator, `_Bridge` QObject for thread→Qt signal marshaling; hotkey routing; wires `GhostCursor`, `TaskManager`, `AnswerNote`, `PTTListener`
- `src/ptt_listener.py` — `PTTListener`: pynput chord watcher; fires signals for Ctrl+Space (quick-ask), Ctrl+Shift+Space (agent), Ctrl+. (type), Esc (quit)
- `src/quick_ask.py` — `ask()`: voice prompt → `claude -p` (or API backend) → short spoken reply; conversation history via `--continue` within 60s window; logs to `~/.curby/quick-ask-log.jsonl`
- `src/agent_runner.py` — `AgentRunner`: one `claude -p --dangerously-skip-permissions` subprocess per task in `~/curby-tasks/<ts>-<slug>/`; streams JSON events; SIGSTOP/SIGCONT pause; `--continue` amend queue
- `src/ghost_cursor.py` — `GhostCursor`: frameless PyQt6 feather widget; state-driven color (violet idle → pink listening → gold thinking → mint speaking → red error); soft pulsing aura; pinned near answer note (NOT tracking system cursor to avoid lag)
- `src/answer_note.py` — floating top-right panel showing latest quick-ask reply + latency; collapsible to pulsing dot (same `CollapsibleFloater` base as claude-meter)
- `src/voice_av.py` — `record_until_stop()`: sounddevice + scipy + Google STT; streams per-chunk RMS as audio level callbacks
- `src/ai_client_api.py` — Anthropic API Computer Use path (pixel-accurate); activates when `ANTHROPIC_API_KEY` set; `MODEL = claude-sonnet-4-5`
- `src/preferences.py` — semantic style preferences ("be shorter", "more detail") detected via Claude itself (no keyword matching); applied as system-prompt addendum
- `src/mac_window.py` — `make_always_visible()` PyObjC shim; NSStatusWindowLevel + canJoinAllSpaces
- `src/pidfile.py` — kills stale curby instances on startup; prevents orphan overlays after force-kill
- `src/task_manager.py` — manages list of `AgentRunner`s; renders right-edge task pucks
- `scripts/install-autostart.sh` — installs `com.casterly.curby` LaunchAgent; logs to `/tmp/curby.log`

## Architecture / patterns
- PyQt6 (not PyQt5 — curby migrated to Qt6, claude-meter is still Qt5; don't mix)
- All background work (voice recording, TTS, LLM calls) on threads; UI only via Qt signals through `_Bridge`
- Quick-ask has two backends: `claude_cli` (slow, ~7s, no API key needed) and `api_key` (fast, ~1-2s); config at `~/.curby/config.json`; custom backend: any Python file path in `backend` field
- `QUICK_ASK_TARGET = "__quick_ask__"` sentinel routes transcribed text away from agent spawn
- Conversation history: `~/.curby/quick-ask-session.json`; reused within 60s window via `claude -p --continue`
- TTS via `AVSpeechSynthesizer` in-process (perf: `3294e47`) — not `say` subprocess; Ava (Premium) at 220 WPM recommended
- Pre-warm on startup: backend module + keychain + TCP/TLS done in background so first Ctrl+Space is fast
- Agent workdirs: `~/curby-tasks/<timestamp>-<slug>/`; amend queues a follow-up `--continue` run in same dir
- Ghost cursor is decoupled from system cursor (no tracking) — avoids macOS input lag on pointer events

## Run / test
```bash
cd /Users/casterly/Documents/Dev/curby
source .venv/bin/activate
python main.py               # foreground run
# Auto-start:
./scripts/install-autostart.sh
tail -f /tmp/curby.log
```
Tests: `tests/` dir exists; `python test_run.py` for basic smoke test.

## Current state & active work
- Working: quick-ask + follow-ups, voice meta-commands, ghost cursor, answer note (collapse/expand), agent dispatch + pucks, interrupt mid-speech, pre-warm, LaunchAgent
- Open issues: persistent claude subprocess (no context accumulation, #20), TTS voice/rate UI (#16)
- `ai_client_api.py` is the Computer Use / pixel-guidance path — legacy from earlier "show me how to" mode; not wired into the main quick-ask flow
- Files in `src/` like `guide_path.py`, `action_highlight.py`, `system_cursor.py` are retired from the active path but kept on disk for future "show me how to..." mode — don't delete
- macOS Accessibility permission required for pynput global hotkeys
