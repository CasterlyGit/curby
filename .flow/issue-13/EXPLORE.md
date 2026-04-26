# Explore — curby

## Stack
- **Language:** Python 3.12+ (single language; no JS/TS)
- **GUI:** PyQt6 (`PyQt6>=6.7.0`) — frameless, always-on-top overlays
- **Mac shim:** PyObjC (`AppKit`) via `src/mac_window.py` to elevate Qt overlays to NSStatusWindowLevel
- **Concurrency:** stdlib `threading` + Qt signals/slots (cross-thread marshalling via `QObject` bridges)
- **Other deps:** `anthropic`, `mss`, `pynput`, `Pillow`, `sounddevice`, `numpy`, `scipy`, `SpeechRecognition`, `pyttsx3`
- **Tests:** `pytest>=8.0.0` + `pytest-qt>=4.4.0`
- **Package manager:** `pip` + `requirements.txt` (no Poetry / uv); virtualenv at `.venv/`
- **No type-checker config** (no `mypy.ini`, no `pyproject.toml`), **no linter config** (no ruff/flake8/black configs)

## Layout
- `main.py` — entry point; flips macOS to accessory activation policy, then runs `CurbyApp`
- `src/` — flat module layout; one file per concern (no sub-packages)
  - `app.py` — top-level `CurbyApp` orchestrator (PTT, cursor follow, recording, transcription routing)
  - `dock_widget.py` — **`DockedTaskPuck`** — the floating right-edge task puck. **Primary suspect for issue #13.**
  - `task_manager.py` — `TaskManager` + `Task` (pairs `AgentRunner` with `DockedTaskPuck`, handles right-edge stacking)
  - `agent_runner.py` — wraps one `claude -p` subprocess per task; pause/cancel/amend
  - `voice_indicator.py` — Qt overlay that bobs at the cursor while idle/listening/processing
  - `cursor_tracker.py` — global mouse position via `pynput.mouse.Listener` (used for the voice indicator, **not** the puck)
  - `mac_window.py` — PyObjC bridge: `make_always_visible(qt_widget)` raises NSWindow level + canJoinAllSpaces
  - `ptt_listener.py`, `voice_io.py`, `text_input_popup.py`, etc. — supporting widgets/services
  - **Legacy / dormant** (per README): `ghost_cursor.py`, `guide_path.py`, `action_highlight.py`, `chat_panel.py`, `speech_bubble.py`, `status_window.py`, `buddy_icon.py`, `buddy_window.py`, `ai_client.py`, `ai_client_api.py`, `screen_capture.py`
- `tests/` — `pytest` suite, headless
  - `test_agentic_flow.py` — `_status_from_event` table, PTT toggle re-arm, AgentRunner lifecycle (uses `tests/fixtures/fake_claude.py`)
  - `test_integration.py` — screen capture, cursor tracker, `BuddyWindow` positioning (legacy), one AI test gated on `ANTHROPIC_API_KEY`
- `.flow/` — pipeline artifacts (this directory)
- `inbox/` — local scratch (untracked)
- `design.md` — project-level design notes
- `phase1_test.py`, `test_run.py` — older root-level test scripts (not part of the `pytest` suite)

## Entry points
- run: `python main.py`
- test: `python -m pytest tests/ -v`
- build: _none_ — no packaging step; runs from source

## Conventions
- **No type-checker / linter config in repo.** Code uses type hints inconsistently but PEP 604 unions (`Task | None`) are common — Python 3.10+ syntax.
- **Cross-thread Qt marshalling pattern:** background callbacks → `pyqtSignal` on a `QObject` bridge → main-thread slot. Concrete examples: `src/task_manager.py:20-23` (`_TaskBridge`), `src/app.py:29-38` (`_Bridge`).
- **Hover behavior is currently driven by Qt's built-in `enterEvent` / `leaveEvent`** — see `src/dock_widget.py:148-162`. No debounce, no global-cursor polling. The class docstring at `src/dock_widget.py:1-11` and the README still describe a "TaskManager polls the global cursor" model that is no longer in the code (stale docs).
- **Frameless overlay pattern:** `WindowFlags = FramelessWindowHint | WindowStaysOnTopHint | Tool | WindowDoesNotAcceptFocus` + `WA_TranslucentBackground` + `WA_ShowWithoutActivating`, then `make_always_visible(self)` post-`show()` to elevate the NSWindow. Examples: `src/dock_widget.py:92-99`, `src/voice_indicator.py`, `src/text_input_popup.py`.
- **State machine on the puck** is a string field (`self._state ∈ {"running","paused","done","error","cancelled"}`); button rows and pip rendering branch on it (`src/dock_widget.py:200-213`, `src/dock_widget.py:345-399`).
- **Test style:** pure-logic units are table-driven (`@pytest.mark.parametrize`); side-effecting flows use a fake `claude` subprocess (`tests/fixtures/fake_claude.py`). No mocking of Qt widgets — tests instantiate a real `QApplication`.

## Recent activity
- branch: `auto/13-dock-puck-hover-stability` (just created off `main`)
- last 5 commits on `main`:
  - `5935867` Pin agentic flow with headless tests; fix amend-after-done & indicator-stuck-on-timeout (#11)
  - `53a1ed4` Merge pull request #1 from CasterlyGit/chore/issue-templates
  - `ea947f0` chore: add standard issue templates from workspace kit
  - `a2e8cc2` Pivot: voice-driven agent dispatcher with neon task pucks
  - `e5f7b1c` macOS support: push-to-talk + cross-platform fixes + overlay perf
- uncommitted: yes — pre-existing untracked `.flow/Untitled.md` and `inbox/` (not ours; ignore). New `.flow/issue-13/` will be ours.

## Files relevant to this target
- `src/dock_widget.py` — **prime mover**. `enterEvent`/`leaveEvent` at lines 148-162 fire `_set_expanded(True/False)` immediately with no debounce. `_set_expanded` (lines 219-233) **resizes the widget while the cursor is over it** — extending left from `right_x` by `PANEL_W`. On collapse, the same resize shrinks the widget back, which can move the widget out from under the cursor and trigger a `leaveEvent` mid-expand → flicker. This is the most plausible root cause of AC-1, AC-2, AC-4 issues. The amend-mode early-return in `leaveEvent` (lines 155-156) is the only existing "stickiness" carve-out.
- `src/task_manager.py` — owns the puck, sets `start_amend`/`stop_amend`. `_relayout` (lines 147-158) only moves *collapsed* pucks, which is correct, but worth re-reading when designing.
- `src/mac_window.py` — the NSWindow level shim. On macOS, NSStatusWindowLevel + `WA_TranslucentBackground` can interact oddly with Qt mouse-tracking; need to confirm enter/leave still fire on translucent regions. (Open question for research.)
- `src/app.py` — wires `CursorTracker` to the **voice indicator** only; the puck does not currently consume global cursor events. If the fix wants global-cursor-based hover stickiness (cursor inside puck *or* panel rect), this is where wiring would happen — or `task_manager.py` could grow its own polling timer.
- `tests/test_agentic_flow.py` + `tests/fixtures/fake_claude.py` — where new puck-hover unit tests will go (pure-logic + `pytest-qt`).
- `tests/test_integration.py` — where any new Qt-widget integration test for the puck (e.g. simulated enter/leave sequences) would slot in alongside the existing `BuddyWindow` positioning test.

## Open questions for the next stage
1. **Why does hovering "sometimes" not show the panel?** Is it a tracking-region issue on macOS (NSStatusWindowLevel + translucent), an `enterEvent`-not-firing issue when the cursor lands on the icon as it's just been moved by `_relayout`, or simply that the user moves through the icon faster than the resize/repaint? Determines whether the fix is debounce, hit-test enlargement, or global-cursor polling.
2. **AC-1's 200 ms threshold** — does the issue mean "panel appears within 200 ms of hover" (a *budget*) or "must hover ≥ 200 ms before it appears" (intentional debounce)? The latter is unusual; I read it as the former but research should confirm.
3. **Should the panel rect be a separate transparent region, a child widget that consumes mouse events, or remain a single resized widget?** Current single-widget design means crossing the icon→panel boundary internal to the same widget never triggers leave, but the widget shrinks on collapse and that *does* race with cursor position.
4. **What's the AC-3 collapse delay (~300 ms)?** Implies a timer on leave; is that the only debounce required, or do we also need an enter-debounce? AC-4 ("no flicker / open-close storms near the boundary") usually means symmetric debounce.
5. **Multi-monitor / DPI behavior** — the puck stacks on the primary screen; does the hover bug reproduce when the cursor crosses screens, or only on the primary? Probably out-of-scope but worth a one-line check.
6. **`pytest-qt` vs. raw `QApplication` for new tests** — existing tests use raw `QApplication`. Stick with that or introduce `qtbot`? Decide in design.
7. **Is a click-pin needed inside this issue?** The "Out of scope" section explicitly excludes it, so no — keep the design focused on hover stickiness only.
