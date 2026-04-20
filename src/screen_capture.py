import mss
import mss.tools
from PIL import Image


def get_screen_size():
    with mss.mss() as sct:
        monitor = sct.monitors[0]  # full virtual screen
        return monitor["width"], monitor["height"]


def grab_region(x, y, radius=400):
    """Capture a square region of `radius` pixels around (x, y), clamped to screen bounds."""
    screen_w, screen_h = get_screen_size()

    left = max(0, x - radius)
    top = max(0, y - radius)
    right = min(screen_w, x + radius)
    bottom = min(screen_h, y + radius)

    region = {"left": left, "top": top, "width": right - left, "height": bottom - top}

    with mss.mss() as sct:
        raw = sct.grab(region)
        return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")


def grab_monitor_at(x: int, y: int) -> tuple[Image.Image, int, int]:
    """
    Grab the monitor containing (x, y).

    Uses Qt's QScreen.geometry() as the authoritative source for both the
    logical size and logical offset — this is the SAME coordinate system used
    by QWidget.move() and QCursor.pos(), so Claude's returned pixel coords map
    directly to screen positions with no DPI correction needed.

    mss is used only for the fast pixel capture; its monitor dict is NOT used
    for offsets or sizing.
    """
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()

    # Find which Qt screen contains (x, y) — Qt geometry is always logical pixels
    qt_screen = None
    for screen in app.screens():
        if screen.geometry().contains(x, y):
            qt_screen = screen
            break
    if qt_screen is None:
        qt_screen = app.primaryScreen()

    geo = qt_screen.geometry()           # logical rect
    left, top = geo.x(), geo.y()
    w, h = geo.width(), geo.height()

    # Capture via mss (fast); the capture region uses the logical bounds
    region = {"left": left, "top": top, "width": w, "height": h}
    with mss.mss() as sct:
        raw = sct.grab(region)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    # mss may return physical pixels on HiDPI; resize to logical size so
    # Claude's coordinates are 1:1 with the logical screen space
    if img.size != (w, h):
        print(f"[screen] HiDPI resize {img.size} → ({w},{h})  DPR={qt_screen.devicePixelRatio():.2f}")
        img = img.resize((w, h), Image.LANCZOS)

    print(f"[screen] grabbed {w}x{h} at logical offset ({left},{top})")
    return img, left, top
