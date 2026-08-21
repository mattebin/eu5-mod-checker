"""Automatic fixes for findings that can be repaired mechanically with
confidence. Anything needing design intent (E001 ordering choices, E002
tree anchors, E004 names, over-24h tick undersampling) is deliberately
NOT here.

Every fixer is conservative: it edits only the flagged thing, preserves
the rest of the file byte-for-byte, and never deletes - removed files
are renamed to .eu5lint-removed so the game ignores them and the author
can undo by renaming back.

Every change is backed up first through a FixSession: original file
bytes are snapshotted to %LOCALAPPDATA%/EU5ModChecker/backups/<stamp>/
before the first write, and renames are recorded. FixSession.revert()
restores everything from the session, newest batch first.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from .engine import Context, Finding
from .parser import UTF8_BOM

BACKUP_ROOT = (Path(os.environ.get("LOCALAPPDATA", Path.home()))
               / "EU5ModChecker" / "backups")


class FixSession:
    """Backups and undo for all fixes applied during one app run."""

    def __init__(self):
        self.stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.dir = BACKUP_ROOT / self.stamp
        # Ordered operation log, oldest first. Each op is
        # ("content", original_path, backup_path) or ("rename", src, dst).
        self.ops: list[tuple[str, str, str]] = []
        self._backed_up: set[str] = set()

    # ------------------------------------------------------- recording
    def backup(self, path: Path) -> None:
        """Snapshot a file's current bytes before the first change."""
        key = str(path).lower()
        if key in self._backed_up or not path.exists():
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        target = self.dir / f"{len(self.ops):03d}_{path.name}"
        target.write_bytes(path.read_bytes())
        self.ops.append(("content", str(path), str(target)))
        self._backed_up.add(key)
        self._write_manifest()

    def record_rename(self, src: Path, dst: Path) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ops.append(("rename", str(src), str(dst)))
        self._write_manifest()

    def _write_manifest(self) -> None:
        (self.dir / "manifest.json").write_text(
            json.dumps({"created": self.stamp, "ops": self.ops}, indent=1),
            encoding="utf-8")

    # --------------------------------------------------------- undoing
    def revert(self) -> list[str]:
        """Undo every recorded operation, newest first."""
        done: list[str] = []
        for op, a, b in reversed(self.ops):
            try:
                if op == "content":
                    Path(a).write_bytes(Path(b).read_bytes())
                    done.append(f"restored {Path(a).name}")
                elif op == "rename":
                    if Path(b).exists() and not Path(a).exists():
                        Path(b).rename(Path(a))
                        done.append(f"renamed back {Path(a).name}")
            except OSError as exc:
                done.append(f"could not revert {Path(a).name}: {exc}")
        self.ops.clear()
        self._backed_up.clear()
        return done

    @property
    def has_changes(self) -> bool:
        return bool(self.ops)


def _fix_e005(finding: Finding, ctx: Context, session: FixSession) -> str:
    raw = finding.path.read_bytes()
    if not raw.startswith(UTF8_BOM):
        session.backup(finding.path)
        finding.path.write_bytes(UTF8_BOM + raw)
    return f"added UTF-8 BOM: {finding.path.name}"


def _fix_e006(finding: Finding, ctx: Context, session: FixSession) -> str:
    text = finding.path.read_bytes().decode("utf-8-sig")
    lines = text.split("\n")
    i = finding.line - 1
    if i >= len(lines):
        return f"skipped (file changed): {finding.path.name}"
    merged = 0
    while lines[i].count('"') % 2 == 1 and i + 1 < len(lines):
        lines[i] = lines[i].rstrip("\r") + "\\n" + lines.pop(i + 1).lstrip()
        merged += 1
        if merged > 20:
            return f"skipped (could not rebalance quotes): {finding.path.name}"
    if merged == 0:
        return f"skipped (already balanced): {finding.path.name}"
    session.backup(finding.path)
    finding.path.write_bytes(UTF8_BOM + "\n".join(lines).encode("utf-8"))
    return (f"joined a split string with \\n: {finding.path.name} "
            f"line {finding.line}")


def _fix_rename_removed(finding: Finding, ctx: Context,
                        session: FixSession) -> str:
    target = finding.path.with_name(finding.path.name + ".eu5lint-removed")
    if finding.path.exists() and not target.exists():
        finding.path.rename(target)
        session.record_rename(finding.path, target)
    return f"renamed do-nothing copy: {finding.path.name} -> {target.name}"


def _fmt(v: float) -> str:
    return f"{v:g}"


def _fix_w104(finding: Finding, ctx: Context, session: FixSession) -> str:
    import re

    from .rules import TICK_VANILLA, _mod_defines

    defines = _mod_defines(ctx)
    ht = defines.get("HOUR_TICK")
    if ht is None or ht[0] == 2 or ht[0] > 24:
        return "skipped (tick state changed or above 24h)"
    ratio = ht[0] / 2.0

    if "movement" in (finding.fixable or "").lower():
        wanted = {
            "ARMY_MOVEMENT_SPEED": TICK_VANILLA["ARMY_MOVEMENT_SPEED"] * ratio,
            "NAVY_MOVEMENT_SPEED": TICK_VANILLA["NAVY_MOVEMENT_SPEED"] * ratio,
        }
        block = "NUnit"
    else:
        wanted = {
            "HOURS_PER_PHASE":
                max(1, round(TICK_VANILLA["HOURS_PER_PHASE"] / ratio)),
            "COMBAT_HOURLY_MORALE_TICK":
                TICK_VANILLA["COMBAT_HOURLY_MORALE_TICK"] * ratio,
            "COMBAT_DAMAGE_MULT":
                TICK_VANILLA["COMBAT_DAMAGE_MULT"] * ratio,
            "MINIMUM_COMBAT_DURATION":
                round(TICK_VANILLA["MINIMUM_COMBAT_DURATION"] / ratio),
            "MINIMUM_NAVAL_COMBAT_DURATION":
                round(TICK_VANILLA["MINIMUM_NAVAL_COMBAT_DURATION"] / ratio),
        }
        block = "NCombat"

    changed, added = [], {}
    for key, value in wanted.items():
        existing = defines.get(key)
        if existing is not None:
            sf = existing[1]
            text = sf.path.read_bytes().decode("utf-8-sig")
            pattern = re.compile(r"(\b" + key + r"\s*=\s*)-?[\d.]+")
            new_text, n = pattern.subn(
                lambda m: m.group(1) + _fmt(wanted[key]), text, count=1)
            if n:
                session.backup(sf.path)
                sf.path.write_bytes(UTF8_BOM + new_text.encode("utf-8"))
                changed.append(key)
        else:
            added[key] = value

    if added:
        path = finding.path
        text = path.read_bytes().decode("utf-8-sig")
        lines = [f"\n# Added by EU5 Mod Checker: tick compensation for "
                 f"HOUR_TICK {ht[0]:g} (vanilla values scaled by the "
                 f"tick ratio).",
                 block + " = {"]
        for key, value in added.items():
            lines.append(f"\t{key} = {_fmt(value)}")
        lines.append("}")
        session.backup(path)
        path.write_bytes(
            UTF8_BOM + (text.rstrip("\n") + "\n" + "\n".join(lines) + "\n")
            .encode("utf-8"))
    parts = []
    if changed:
        parts.append("updated " + ", ".join(changed))
    if added:
        parts.append("added " + ", ".join(added))
    kind = "movement" if block == "NUnit" else "combat"
    return f"{kind} compensation for the tick: " + "; ".join(parts)


_FIXERS = {
    "E005": _fix_e005,
    "E006": _fix_e006,
    "W102": _fix_rename_removed,
    "W103": _fix_rename_removed,
    "W104": _fix_w104,
}


def apply_fixes(findings: list[Finding], mod_path: Path,
                session: FixSession | None = None) -> list[str]:
    """Apply every fixable finding. Returns human descriptions of what
    was done. Re-run the check afterwards to confirm."""
    from .engine import Tree

    if session is None:
        session = FixSession()
    ctx = Context(mod=Tree.scan(mod_path), vanilla=None)
    fixable = [f for f in findings if f.fixable and f.rule in _FIXERS]
    # E006 fixes merge lines, shifting line numbers below them - apply
    # bottom-up per file so earlier findings stay accurate.
    fixable.sort(key=lambda f: (f.rule != "E006", str(f.path), -f.line))
    done: list[str] = []
    for finding in fixable:
        try:
            done.append(_FIXERS[finding.rule](finding, ctx, session))
        except OSError as exc:
            done.append(f"failed on {finding.path.name}: {exc}")
    return done
