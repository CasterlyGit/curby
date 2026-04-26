"""macOS NSWindow shims so curby's overlays stay visible regardless of which
app the user has focused, and persist across all desktop spaces.

By default Qt's frameless Tool windows on macOS are backed by NSPanel and
hide when the owning app is not active. We elevate the level to status-bar
class so the window floats above other apps' windows, and set collection
behavior so it shows on every space.
"""
import ctypes
import sys


# NSWindow.Level constants (matching AppKit).
_LEVEL_FLOATING       = 3
_LEVEL_STATUS_BAR     = 25
_LEVEL_POPUP_MENU     = 101
_LEVEL_SCREEN_SAVER   = 1000

# NSWindowCollectionBehavior bit flags.
_BEHAVIOR_CAN_JOIN_ALL_SPACES = 1 << 0
_BEHAVIOR_STATIONARY          = 1 << 4


def make_always_visible(widget) -> None:
    """Pin a Qt widget so it floats above every app on every space.

    Safe to call on every platform — no-ops on non-darwin or if PyObjC
    isn't available. Logs success/failure so we can verify it ran.
    """
    if sys.platform != "darwin":
        return
    try:
        import objc

        nsview_ptr = int(widget.winId())
        if not nsview_ptr:
            print("[mac] make_always_visible: widget has no native handle yet")
            return
        # PyObjC's objc_object constructor expects an actual ctypes c_void_p,
        # not a raw int — that was the bug in the previous attempt.
        nsview = objc.objc_object(c_void_p=ctypes.c_void_p(nsview_ptr))
        nswindow = nsview.window()
        if nswindow is None:
            print("[mac] make_always_visible: NSView has no window")
            return
        nswindow.setLevel_(_LEVEL_STATUS_BAR)
        nswindow.setCollectionBehavior_(
            _BEHAVIOR_CAN_JOIN_ALL_SPACES | _BEHAVIOR_STATIONARY
        )
        # Hide-on-deactivate is true for NSPanels by default; force it off.
        try:
            nswindow.setHidesOnDeactivate_(False)
        except Exception:
            pass
        print(f"[mac] pinned window @level={_LEVEL_STATUS_BAR} "
              f"all-spaces+stationary  ({type(widget).__name__})")
    except Exception as e:
        print(f"[mac] make_always_visible failed: {e}")
