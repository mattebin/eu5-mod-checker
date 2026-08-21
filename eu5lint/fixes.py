"""Automatic fixes for findings that can be repaired mechanically with
confidence. Anything needing design intent (E001 ordering choices, E002
tree anchors, E004 names, over-24h tick undersampling) is deliberately
NOT here.

Every fixer is conservative: it edits only the flagged thing, preserves
the rest of the file byte-for-byte, and never deletes - removed files
are renamed to .eu5lint-removed so the game ignores them and the author
can undo by renaming back.
"""

from __future__ import annotations

from pathlib import Path

from .engine import Context, Finding
from .parser import UTF8_BOM


def _fix_e005(finding: Finding, ctx: Context) -> str:
    raw = finding.path.read_bytes()
    if not raw.startswith(UTF8_BOM):
        finding.path.write_bytes(UTF8_BOM + raw)
    return f"added UTF-8 BOM: {finding.path.name}"


def _fix_e006(finding: Finding, ctx: Context) -> str:
    text = finding.path.read_bytes().decode("utf-8-sig")
    lines = text.split("\n")
    i = finding.line - 1
    if i >= len(lines):
        return f"skipped (file changed): {finding.path.name}"
    # Merge following lines into the flagged one until its quotes balance.
    merged = 0
    while lines[i].count('"') % 2 == 1 and i + 1 < len(lines):
        lines[i] = lines[i].rstrip("\r") + "\\n" + lines.pop(i + 1).lstrip()
        merged += 1
        if merged > 20:  # runaway guard: give up, change nothing
            return f"skipped (could not rebalance quotes): {finding.path.name}"
    if merged == 0:
        return f"skipped (already balanced): {finding.path.name}"
    finding.path.write_bytes(
        UTF8_BOM + "\n".join(lines).encode("utf-8"))
    return (f"joined a split string with \\n: {finding.path.name} "
            f"line {finding.line}")


def _fix_rename_removed(finding: Finding, ctx: Context) -> str:
    target = finding.path.with_name(finding.path.name + ".eu5lint-removed")
    if finding.path.exists() and not target.exists():
        finding.path.rename(target)
    return f"renamed do-nothing copy: {finding.path.name} -> {target.name}"


# ------------------------------------------------------------- W104
def _fmt(v: float) -> str:
    return f"{v:g}"


def _fix_w104(finding: Finding, ctx: Context) -> str:
    from .rules import TICK_VANILLA, _mod_defines

    defines = _mod_defines(ctx)
    ht = defines.get("HOUR_TICK")
    if ht is None or ht[0] == 2 or ht[0] > 24:
        return "skipped (tick state changed or above 24h)"
    ratio = ht[0] / 2.0

    if "movement" in finding.fixable.lower():
        wanted = {
            "ARMY_MOVEMENT_SPEED": TICK_VANILLA["ARMY_MOVEMENT_SPEED"] * ratio,
            "NAVY_MOVEMENT_SPEED": TICK_VANILLA["NAVY_MOVEMENT_SPEED"] * ratio,
        }
        block = "NUnit"
    else:
        hpp = max(1, round(TICK_VANILLA["HOURS_PER_PHASE"] / ratio))
        wanted = {
            "HOURS_PER_PHASE": hpp,
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
            import re
            pattern = re.compile(
                r"(\b" + key + r"\s*=\s*)-?[\d.]+")
            new_text, n = pattern.subn(
                lambda m: m.group(1) + _fmt(wanted[key]), text, count=1)
            if n:
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


def apply_fixes(findings: list[Finding], mod_path: Path) -> list[str]:
    """Apply every fixable finding. Returns human descriptions of what
    was done. Re-run the check afterwards to confirm."""
    from .engine import Tree

    ctx = Context(mod=Tree.scan(mod_path), vanilla=None)
    fixable = [f for f in findings if f.fixable and f.rule in _FIXERS]
    # E006 fixes merge lines, shifting line numbers below them - apply
    # bottom-up per file so earlier findings stay accurate.
    fixable.sort(key=lambda f: (f.rule != "E006", str(f.path), -f.line))
    done: list[str] = []
    for finding in fixable:
        try:
            done.append(_FIXERS[finding.rule](finding, ctx))
        except OSError as exc:
            done.append(f"failed on {finding.path.name}: {exc}")
    return done
