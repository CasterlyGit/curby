"""Voice / TTS configuration for quick-ask.

Picks the best macOS `say` voice available, honoring an optional user
override at ~/.curby/config.json. Defaults to a curated preference list
that prefers any installed Premium voice (significantly more natural)
over the basic catalog.

Config file shape:
    {
      "voice": "Ava (Premium)",   // exact name as `say -v ?` lists it
      "rate":  220                 // words per minute
    }

If `voice` is set, it's used as-is (and unmet preferences are silently
skipped). If unset, we walk PREFERRED_VOICES and pick the first that
shows up in `say -v ?`. `rate` defaults to 220.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

CONFIG_PATH = Path(os.path.expanduser("~/.curby/config.json"))
DEFAULT_RATE = 220

# Order matters — first installed match wins. Premium variants are
# vastly more natural; download via System Settings → Accessibility →
# Spoken Content → System Voice → Manage Voices.
PREFERRED_VOICES = [
    "Ava (Premium)",
    "Zoe (Premium)",
    "Allison (Premium)",
    "Samantha (Premium)",
    "Evan (Enhanced)",
    "Ava (Enhanced)",
    "Samantha (Enhanced)",
    # Basic-tier fallbacks — installed by default on macOS.
    "Samantha",
    "Karen",      # Australian en
    "Moira",      # Irish en
    "Tessa",      # South African en
]


def _list_installed_voices() -> list[str]:
    """Return the bare voice names from `say -v ?` (one per line; the
    locale + sample sentence are stripped). Empty on any failure — caller
    just falls back to the system default."""
    if not shutil.which("say"):
        return []
    try:
        out = subprocess.run(["say", "-v", "?"], capture_output=True,
                             text=True, timeout=5).stdout
    except Exception:
        return []
    names = []
    for line in out.splitlines():
        # Format: "Name (variant)    locale    # Sample sentence."
        # Drop the trailing locale token + sample so we just have the name.
        if "#" not in line:
            continue
        head = line.split("#", 1)[0].rstrip()
        parts = head.rsplit(None, 1)
        if len(parts) != 2:
            continue
        full = parts[0].strip()
        names.append(full)
        # ALSO include the bare prefix (e.g. "Samantha" alongside
        # "Samantha (English (US))") so preference-list entries that
        # don't bake in the locale tag still match. Premium/Enhanced
        # variants stay as-is — those carry meaning we want to preserve.
        if " (" in full and "Premium" not in full and "Enhanced" not in full:
            names.append(full.split(" (", 1)[0])
    return names


def _load_user_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except Exception:
        return {}


def resolve_voice() -> tuple[str | None, int, bool]:
    """Returns (voice_name, rate_wpm, used_premium). voice_name is None
    if no preference matched and we should fall back to `say` default.
    `used_premium` is True iff the picked voice has '(Premium)' or
    '(Enhanced)' in its name — used to suppress the install-hint."""
    cfg = _load_user_config()
    rate = int(cfg.get("rate", DEFAULT_RATE))

    if cfg.get("voice"):
        v = str(cfg["voice"])
        return v, rate, ("Premium" in v or "Enhanced" in v)

    installed = set(_list_installed_voices())
    for candidate in PREFERRED_VOICES:
        if candidate in installed:
            return candidate, rate, ("Premium" in candidate or "Enhanced" in candidate)
    return None, rate, False


def install_hint() -> str:
    """Multi-line hint to print at startup if we couldn't find a Premium
    voice. Tells the user how to install one in <2 minutes."""
    return (
        "[quick-ask] tip: macOS Premium voices (Ava, Zoe, Allison) sound\n"
        "  vastly more natural than the default Samantha. Install one via:\n"
        "  System Settings → Accessibility → Spoken Content → System Voice\n"
        "  → click the (i), tap a (Premium) voice, download (~100 MB).\n"
        "  Then either restart curby (it auto-picks) or set the voice name\n"
        "  in ~/.curby/config.json: {\"voice\": \"Ava (Premium)\"}"
    )
