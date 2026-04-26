"""
Curby — voice-driven agent dispatcher. Entry point.

Usage:
  python main.py

Controls:
  - Tap Ctrl+Space to start listening; tap again to send the task.
  - Tap Ctrl+. to type a prompt instead of speaking.
  - Hover a task puck to pause / cancel / amend that task.
  - Esc to quit.
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

from src.app import CurbyApp

if __name__ == "__main__":
    app = CurbyApp()
    sys.exit(app.run())
