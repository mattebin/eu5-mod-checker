"""Game-version provenance.

Every rule in this tool encodes engine behavior that was verified against
a specific game version. A game patch can change engine behavior and turn
a true rule into a false-positive machine, so the tool always states what
its rules were verified on, and warns when the local game looks newer.

Detection is best effort: EU5 does not stamp its semantic version into the
install (the exe resource says 1.0.0.0), so we read the last-launched
version from the user's continue_game.json and accept --game-version as
an override.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# The game version the rule set was last empirically verified against.
VERIFIED_GAME_VERSION = "1.3.11"


def parse_version(text: str) -> tuple[int, ...] | None:
    match = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?", text.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups() if part is not None)


def detect_game_version() -> str | None:
    """Last-launched game version from continue_game.json, best effort."""
    home = Path.home()
    candidates = [
        home / "Documents" / "Paradox Interactive" / "Europa Universalis V"
        / "continue_game.json",
        home / "OneDrive" / "Documents" / "Paradox Interactive"
        / "Europa Universalis V" / "continue_game.json",
    ]
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        raw = data.get("rawGameVersion")
        if isinstance(raw, str) and parse_version(raw):
            return raw
    return None


def version_notice(detected: str | None) -> tuple[str, bool]:
    """Provenance line for the output header.

    Returns (message, is_warning).
    """
    base = f"rules verified on EU5 {VERIFIED_GAME_VERSION}"
    if detected is None:
        return (f"{base} (local game version unknown, pass --game-version "
                "to check)"), False
    detected_parsed = parse_version(detected)
    verified_parsed = parse_version(VERIFIED_GAME_VERSION)
    if detected_parsed is None or verified_parsed is None:
        return f"{base} (could not compare with '{detected}')", False
    if detected_parsed > verified_parsed:
        return (f"WARNING: {base}, but your game looks newer ({detected}). "
                "Engine behavior may have changed. Treat findings as "
                "provisional until the rules are re-verified on this "
                "version."), True
    return f"{base}, local game {detected}", False
