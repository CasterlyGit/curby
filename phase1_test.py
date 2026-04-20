"""
Phase 1 smoke test.
Run:  python phase1_test.py
- Prints cursor position for 5 seconds
- Then grabs a screenshot centred on the last known cursor position and saves it
"""
import sys
import time
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from src.cursor_tracker import CursorTracker
from src.screen_capture import grab_region, get_screen_size

moves = []

def on_move(x, y):
    moves.append((x, y))
    print(f"  cursor: ({x}, {y})", end="\r", flush=True)

print("=== Phase 1: Cursor Tracker ===")
print("Move your mouse around for 5 seconds...")

tracker = CursorTracker(on_move=on_move)
tracker.start()
time.sleep(5)
tracker.stop()

print(f"\nCaptured {len(moves)} move events.")
assert len(moves) > 0, "No move events received — is pynput installed?"

print("\n=== Phase 1: Screen Capture ===")
screen_w, screen_h = get_screen_size()
print(f"Screen size: {screen_w}x{screen_h}")

x, y = tracker.position
print(f"Last cursor position: ({x}, {y})")

img = grab_region(x, y, radius=400)
print(f"Captured image size: {img.size}")
assert img.size[0] > 0 and img.size[1] > 0, "Image has zero dimension"

out = pathlib.Path(__file__).parent / "phase1_capture.png"
img.save(out)
print(f"Saved screenshot to: {out}")

print("\nPhase 1 PASSED")
