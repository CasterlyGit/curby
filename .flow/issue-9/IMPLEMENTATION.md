2026-04-26T15:10 3d3c45a implement: issue-9 add headless tests + fake-claude fixture (failing pre-fix)
2026-04-26T15:14 NOTE — committed tests first (TDD); 5/22 failed as expected, including expected B1 (amend-after-done), expected B2 (record_until_stop kwarg), plus two tests that needed test-side fixes after seeing the actual contract (queued amend produces 1 final on_done, not 2).
2026-04-26T15:21 cade6e1 fix(agent_runner): amend after on_done re-spawns; cancel still drops queue
2026-04-26T15:21 NOTE — held _lock across _spawn() in amend()'s direct path; safe because Popen + on_status are external/fast and don't take _lock. _read_loop now sets self._reader = None inside _lock when finalizing, closing the race where a concurrent amend would queue onto a thread about to exit.
2026-04-26T15:24 06eb3b7 fix(voice): voice indicator transitions to processing on every record exit
2026-04-26T15:24 NOTE — DESIGN.md kept the kwarg-only addition shape; added a `_fire_stopped()` inner helper to fire on both the exception path (mic unavailable) and the normal exit path. Also added `_on_recording_stopped` slot in CurbyApp; left the existing set_state("processing") call in `_stop_recording` since the second call is a no-op.
2026-04-26T15:27 d3aa9cd docs: drop dead Screen Recording prereq; sync flow docs with reality
2026-04-26T15:27 NOTE — Also rewrote main.py's top-of-file docstring (it described the legacy Snap/Ask UI). README "Prereqs" line + design.md "macOS specifics" + app.py top-of-file docstring all updated. Original `Quartz` import block removed entirely from main.py — the active flow has no caller for screen capture.
2026-04-26T15:30 5969878 test: refactor _Recorder for multi-done counting; tune MAX_SECONDS test
2026-04-26T15:30 NOTE — Single threading.Event couldn't distinguish "1 done at end of chain" from "2 dones across re-spawn." Replaced with done-count list + wait_for_dones helper. MAX_SECONDS test value bumped from 0.05 → 0.2 so max_chunks ≥ 1 (otherwise `np.concatenate(frames)` fails on empty list, masking the on_recording_stopped signal as a different kind of failure).

Final test run: 22/22 pass in tests/test_agentic_flow.py (3.35 s headless, no key/binary/mic). Full suite: 25 passed, 2 skipped (legacy Anthropic-API tests; no key set).
