"""
Self-quitting test harness for Curby.

Env vars:
  CURBY_SAFE_MODE=1   — skip ghost cursor (heaviest widget) + slow timers
  CURBY_TEST_SECS=N   — auto-quit after N seconds (default 15)
  CURBY_AUTO_PROMPT=1 — programmatically trigger text popup after 3s
"""
import os
import sys
import pathlib
import traceback
import faulthandler
import datetime

# Tee stdout/stderr to test.log so you can `tail -f test.log` in another terminal
_LOG = open(pathlib.Path(__file__).parent / "test.log", "a", buffering=1)
_LOG.write(f"\n===== {datetime.datetime.now().isoformat()} =====\n")

class _Tee:
    def __init__(self, *streams): self.streams = streams
    def write(self, s):
        for st in self.streams:
            try: st.write(s); st.flush()
            except Exception: pass
    def flush(self):
        for st in self.streams:
            try: st.flush()
            except Exception: pass

sys.stdout = _Tee(sys.stdout, _LOG)
sys.stderr = _Tee(sys.stderr, _LOG)

faulthandler.enable(file=_LOG)

sys.path.insert(0, str(pathlib.Path(__file__).parent))

# macOS: accessory policy (no focus stealing, no dock icon)
if sys.platform == "darwin":
    try:
        from AppKit import NSApplication
        NSApplication.sharedApplication().setActivationPolicy_(2)
    except Exception as e:
        print(f"[harness] accessory policy failed: {e}", flush=True)

    # Permission probe
    try:
        import mss
        with mss.mss() as _sct:
            img = _sct.grab(_sct.monitors[0])
            # Check if image is actually captured (non-black) to detect missing permission
            px = bytes(img.bgra[:12])
            print(f"[harness] screen probe ok, first pixels={px.hex()}", flush=True)
    except Exception as e:
        print(f"[harness] screen probe failed: {e}", flush=True)


def main() -> int:
    from PyQt6.QtCore import QTimer

    secs = int(os.environ.get("CURBY_TEST_SECS", "15"))
    auto_prompt = os.environ.get("CURBY_AUTO_PROMPT") == "1"

    print(f"[harness] starting — will quit after {secs}s  safe_mode={os.environ.get('CURBY_SAFE_MODE','0')}", flush=True)

    try:
        from src.app import CurbyApp
        app = CurbyApp()
    except Exception as e:
        print(f"[harness] CurbyApp construct failed: {e}", flush=True)
        traceback.print_exc()
        return 2

    # Auto-quit timer
    QTimer.singleShot(secs * 1000, lambda: (print(f"[harness] auto-quit after {secs}s", flush=True), app._qt.quit()))

    # Optional: trigger the text popup mid-run to verify that pathway
    if auto_prompt:
        def _trigger():
            try:
                print("[harness] triggering text popup", flush=True)
                app._bridge.text_prompt_show.emit(400, 400)
            except Exception as e:
                print(f"[harness] trigger failed: {e}", flush=True)
        QTimer.singleShot(3000, _trigger)

    try:
        rc = app.run()
        print(f"[harness] app.run() returned {rc}", flush=True)
        return 0 if rc == 0 else rc
    except Exception as e:
        print(f"[harness] app.run() threw: {e}", flush=True)
        traceback.print_exc()
        return 3


if __name__ == "__main__":
    sys.exit(main())
