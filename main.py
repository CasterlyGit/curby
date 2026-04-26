"""
Curby — the cursor buddy. MVP entry point.

Usage:
  set ANTHROPIC_API_KEY=sk-ant-...
  python main.py

Controls:
  - Window follows your cursor automatically
  - Click "Snap" to capture a screenshot of the area around your cursor
  - Type a question and press Enter or click "Ask"
  - The buddy sees the screenshot and answers
"""
import sys
import io
import pathlib

# Force UTF-8 output so terminal never crashes on Unicode in error messages.
# macOS skips this because the stdout wrapper defeats python -u unbuffering
# and hides early crash output.
if sys.platform != "darwin":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(pathlib.Path(__file__).parent))

# On macOS, run as an accessory app so our overlay windows never steal
# keyboard focus from whatever app the user is actually typing in.
if sys.platform == "darwin":
    try:
        from AppKit import NSApplication
        NSApplication.sharedApplication().setActivationPolicy_(2)  # NSApplicationActivationPolicyAccessory
    except Exception as e:
        print(f"[mac] could not set accessory policy: {e}")

    # Ask macOS for Screen Recording permission. This registers Python in
    # System Settings → Privacy → Screen Recording so the user can enable
    # the toggle. Unlike mss.grab(), this call does NOT block.
    try:
        from Quartz import CGPreflightScreenCaptureAccess, CGRequestScreenCaptureAccess
        if not CGPreflightScreenCaptureAccess():
            CGRequestScreenCaptureAccess()
            print("[mac] screen recording not granted — enable Python in "
                  "System Settings → Privacy & Security → Screen Recording, "
                  "then restart curby.")
        else:
            print("[mac] screen recording: granted")
    except Exception as e:
        print(f"[mac] screen permission check failed: {e}")

from src.app import CurbyApp

if __name__ == "__main__":
    app = CurbyApp()
    sys.exit(app.run())
