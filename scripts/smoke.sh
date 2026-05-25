#!/usr/bin/env bash
# curby smoke test — CI-runnable wiring proof
# Usage: cd ~/Documents/Dev/curby && bash scripts/smoke.sh
# Exit 0 = all PASS; Exit 1 = at least one FAIL
#
# Tests the import chain and key functions directly from Python.
# Does NOT require a mic, display, or real API key.
# Set CURBY_CI=1 to skip display-dependent code paths (already set here).

set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
export CURBY_CI=1
export PYTHONPATH="$REPO"

PASS=0
FAIL=0
FAILURES=()

ok()   { echo "  PASS  $1"; PASS=$((PASS+1)); }
fail() { echo "  FAIL  $1"; FAIL=$((FAIL+1)); FAILURES+=("$1"); }

run_py() {
    # Run a python snippet; return its exit code
    python3 -c "$1" 2>&1
}

echo ""
echo "curby smoke tests"
echo "─────────────────────────────────────"

# 1. Import quick_ask
if run_py "import sys; sys.path.insert(0, '$REPO'); from src import quick_ask; print('import ok')" | grep -q "import ok"; then
    ok "src.quick_ask import"
else
    fail "src.quick_ask import"
fi

# 2. Import backend loader
if run_py "import sys; sys.path.insert(0, '$REPO'); from src.quick_ask_backends import load_backend; fn = load_backend('claude_cli'); assert callable(fn); print('ok')" | grep -q "ok"; then
    ok "backend loader (claude_cli)"
else
    fail "backend loader (claude_cli)"
fi

# 3. Import api_key backend (no key required — just verify importable)
if run_py "import sys; sys.path.insert(0, '$REPO'); from src.quick_ask_backends import load_backend; fn = load_backend('api_key'); assert callable(fn); print('ok')" | grep -q "ok"; then
    ok "backend loader (api_key)"
else
    fail "backend loader (api_key)"
fi

# 4. Stats computation with mock log file
if run_py "
import sys, json, tempfile, pathlib
sys.path.insert(0, '$REPO')
from src.stats import _load_events, compute_stats, print_stats

with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
    for i in range(5):
        f.write(json.dumps({
            'ts': '2026-05-25T10:00:00+00:00',
            'event': 'quick_ask',
            'backend': 'api_key',
            'ttft_ms': 200 + i*50,
            'total_ms': 800 + i*50,
            'was_followup': i > 2,
        }) + '\n')
    log = pathlib.Path(f.name)

events = _load_events(log_path=log, days=365)
assert len(events) == 5, f'expected 5, got {len(events)}'
stats = compute_stats(events)
assert stats['quick_asks'] == 5
assert stats['ttft_p50'] is not None
assert stats['backend_counts']['api_key'] == 5
print('ok')
" | grep -q "ok"; then
    ok "stats computation (mock log)"
else
    fail "stats computation (mock log)"
fi

# 5. Backend prewarm doesn't crash with bogus API key
if run_py "
import sys, os
sys.path.insert(0, '$REPO')
os.environ['ANTHROPIC_API_KEY'] = 'sk-ant-BOGUS-KEY-FOR-TEST'
from src.quick_ask_backends.api_key import _resolve_api_key
key = _resolve_api_key()
assert key == 'sk-ant-BOGUS-KEY-FOR-TEST', f'got {key!r}'
# Verify load_backend returns a callable without error
from src.quick_ask_backends import load_backend
fn = load_backend('api_key')
assert callable(fn)
print('ok')
" | grep -q "ok"; then
    ok "prewarm code path (bogus key)"
else
    fail "prewarm code path (bogus key)"
fi

# 6. voice_av available() doesn't crash
if run_py "
import sys
sys.path.insert(0, '$REPO')
from src import voice_av
result = voice_av.available()
assert isinstance(result, bool)
print('ok')
" | grep -q "ok"; then
    ok "voice_av.available()"
else
    fail "voice_av.available()"
fi

# 7. pidfile module importable and safe
if run_py "
import sys
sys.path.insert(0, '$REPO')
from src import pidfile
assert hasattr(pidfile, 'write_self') or hasattr(pidfile, 'kill_previous')
print('ok')
" | grep -q "ok"; then
    ok "pidfile import"
else
    fail "pidfile import"
fi

# 8. curby CLI: 'stats' command with mock data runs without crash
if run_py "
import sys, json, tempfile, pathlib, os
sys.path.insert(0, '$REPO')
from src.stats import run as stats_run

# Point log at a temp file
from src import stats as stats_mod
with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
    for i in range(3):
        f.write(json.dumps({
            'ts': '2026-05-25T10:00:00+00:00',
            'event': 'quick_ask',
            'backend': 'api_key',
            'ttft_ms': 200,
            'total_ms': 900,
            'was_followup': False,
        }) + '\n')
    log = pathlib.Path(f.name)

stats_mod.LOG_PATH = log
stats_mod.STATS_PATH = pathlib.Path(tempfile.mktemp(suffix='.jsonl'))
stats_run([])
print('ok')
" | grep -q "ok"; then
    ok "curby stats CLI end-to-end"
else
    fail "curby stats CLI end-to-end"
fi

echo "─────────────────────────────────────"
echo "  $PASS passed / $FAIL failed"
echo ""

if [ "$FAIL" -gt 0 ]; then
    echo "FAILED tests:"
    for f in "${FAILURES[@]}"; do
        echo "  - $f"
    done
    echo ""
    exit 1
fi

echo "All smoke tests passed."
exit 0
