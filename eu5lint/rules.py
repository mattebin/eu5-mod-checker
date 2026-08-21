"""Lint rules.

Every rule here targets a failure the game engine accepts SILENTLY:
the files load, error.log stays quiet (or nearly quiet), and the mod
simply does not do what its author intended. All of them were found
the hard way, by bisecting live mods against EU5 1.3.x.
"""

from __future__ import annotations

import difflib

from .engine import Context, Finding, effective_levels, has_entry_mode, rule
from .parser import UTF8_BOM

# Keys inside an auto modifier block that are structure, not modifiers.
AUTO_MODIFIER_STRUCTURE_KEYS = {"potential_trigger", "game_data",
                                "requires_real"}


@rule("E001", "Forward reference inside an advances file")
def forward_reference(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    from .parser import ref_values

    for sf in ctx.mod.db_files("advances"):
        parsed = sf.parsed()
        defined_at: dict[str, int] = {}
        order: list[str] = []
        for kv in parsed.root.key_values():
            if kv.is_block and kv.key not in defined_at:
                defined_at[kv.key] = kv.line
                order.append(kv.key)
        seen: set[str] = set()
        for kv in parsed.root.key_values():
            if not kv.is_block:
                continue
            for inner in kv.value.key_values():
                if inner.key not in ("requires", "in_tree_of"):
                    continue
                for ref, line in ref_values(inner):
                    if ref in defined_at and ref not in seen and ref != kv.key:
                        findings.append(Finding(
                            rule="E001", severity="error", path=sf.path,
                            line=line,
                            message=(
                                f"'{kv.key}' references '{ref}' before it is "
                                f"defined (line {defined_at[ref]}). References "
                                "resolve at parse time in file order, so this "
                                "one fails silently and the advance loads "
                                "half-broken. Move the definition of "
                                f"'{ref}' above this block.")))
            seen.add(kv.key)
    return findings


@rule("E002", "in_tree_of target is not a root")
def in_tree_of_root(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    mod_advances = ctx.mod_advances()
    vanilla_advances = ctx.vanilla_advances()

    # Where does each advance's final definition come from, and does it
    # have requires? Mod definitions override vanilla ones with the same key.
    def final_requires(name: str) -> list[tuple[str, int]] | None:
        if name in mod_advances:
            return mod_advances[name].requires
        if name in vanilla_advances:
            return vanilla_advances[name].requires
        return None

    # All in_tree_of targets, from the mod and (if available) vanilla.
    targets: dict[str, list[tuple[str, str, int]]] = {}
    for adv in mod_advances.values():
        for target, line in adv.in_tree_of:
            targets.setdefault(target, []).append(
                (adv.name, str(adv.file.path), line))
    if vanilla_advances:
        for adv in vanilla_advances.values():
            for target, _line in adv.in_tree_of:
                targets.setdefault(target, [])

    for target, users in targets.items():
        reqs = final_requires(target)
        if reqs is None or not reqs:
            continue
        # The target ends up with requires, so it is not a root.
        if target in mod_advances:
            adv = mod_advances[target]
            findings.append(Finding(
                rule="E002", severity="error", path=adv.file.path,
                line=adv.line,
                message=(
                    f"'{target}' is an in_tree_of target but has "
                    "'requires', so it is not a root. The engine only "
                    "accepts roots as in_tree_of targets "
                    "(error.log: 'has in_tree_of that is not a root'). "
                    "Remove its requires or repoint the in_tree_of users.")))
        else:
            for user, path, line in users:
                from pathlib import Path
                findings.append(Finding(
                    rule="E002", severity="error", path=Path(path), line=line,
                    message=(
                        f"'{user}' uses in_tree_of = {target}, but "
                        f"'{target}' is not a root (it has requires). "
                        "in_tree_of targets must stay depth-0 roots.")))
    return findings


@rule("E003", "Auto modifier block with wrong-scope content")
def auto_modifier_content(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    for sf in ctx.mod.db_files("auto_modifiers"):
        parsed = sf.parsed()
        for kv in parsed.root.key_values():
            if not kv.is_block:
                continue
            game_data = kv.value.find("game_data")
            if game_data is not None:
                findings.append(Finding(
                    rule="E003", severity="error", path=sf.path,
                    line=game_data.line,
                    message=(
                        f"auto modifier '{kv.key}' contains a game_data "
                        "block. That is static-modifier syntax: auto "
                        "modifiers take their scope from the file, not "
                        "the block, and the engine rejects it ('Unknown "
                        "modifier type: game_data', verified 1.3.11). "
                        "Remove the game_data block.")))
            for inner in kv.value.key_values():
                if inner.key in AUTO_MODIFIER_STRUCTURE_KEYS:
                    continue
                if inner.key.startswith("local_"):
                    findings.append(Finding(
                        rule="E003", severity="warning", path=sf.path,
                        line=inner.line,
                        message=(
                            f"location-scope key '{inner.key}' inside "
                            f"auto modifier '{kv.key}'. Auto modifiers "
                            "apply at country or organization scope, and "
                            "a location-scope pillar died silently this "
                            "way on 1.3.x. Whether local_ keys apply "
                            "from country scope is unverified on the "
                            "current patch: verify in game before "
                            "relying on this, or use the scaled "
                            "static_modifiers system for per-location "
                            "effects.")))
    return findings


@rule("E004", "Invented static-modifier block name", needs_vanilla=True)
def static_modifier_names(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    known = ctx.vanilla_static_names()
    if not known:
        return findings
    for sf in ctx.mod.db_files("static_modifiers"):
        parsed = sf.parsed()
        for kv in parsed.root.key_values():
            if kv.is_block and not has_entry_mode(kv.key) \
                    and kv.key not in known:
                findings.append(Finding(
                    rule="E004", severity="warning", path=sf.path,
                    line=kv.line,
                    message=(
                        f"static modifier block '{kv.key}' does not exist "
                        "in vanilla. The engine applies scaled "
                        "static-modifier blocks by name and confirms this "
                        "one is dead at load: 'was not used by the script "
                        "or code but exists in the database, this is a "
                        "waste' (verified 1.3.11). If a script applies it "
                        "by name this is intentional; otherwise edit the "
                        "vanilla block instead (INJECT: entry mode, or a "
                        "full-file copy).")))
    return findings


@rule("E007", "Vanilla static block re-declared in an added file",
      needs_vanilla=True)
def static_modifier_duplicates(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    known = ctx.vanilla_static_names()
    if not known or ctx.vanilla is None:
        return findings
    for sf in ctx.mod.db_files("static_modifiers"):
        if sf.rel.lower() in ctx.vanilla.by_rel:
            continue  # full-file override: re-declaring there is the point
        parsed = sf.parsed()
        for kv in parsed.root.key_values():
            if kv.is_block and not has_entry_mode(kv.key) \
                    and kv.key in known:
                findings.append(Finding(
                    rule="E007", severity="error", path=sf.path,
                    line=kv.line,
                    message=(
                        f"'{kv.key}' re-declares a vanilla static "
                        "modifier block in an added file. The engine "
                        "drops the whole block as a duplicate "
                        "('Duplicated key will not be created', verified "
                        "1.3.11): it does not extend or override "
                        "anything. To edit a vanilla scaled block, use "
                        "the documented database entry modes "
                        "(INJECT:name) or copy the entire vanilla file "
                        "to the same path and edit it there.")))
    return findings


@rule("E005", "Defines file without UTF-8 BOM")
def defines_bom(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    for sf in ctx.mod.db_files("defines"):
        raw = sf.path.read_bytes()
        if not raw.startswith(UTF8_BOM):
            findings.append(Finding(
                rule="E005", severity="warning", path=sf.path, line=1,
                fixable="Add the UTF-8 BOM to the file",
                message=(
                    "defines file has no UTF-8 BOM. The engine logs a "
                    "lexer warning ('should be in utf8-bom encoding') "
                    "and loads the file anyway (verified 1.3.11: the "
                    "overrides do apply). Paradox's own files ship with "
                    "the BOM, so add it to keep your loads "
                    "warning-free.")))
    return findings


@rule("E006", "Raw newline inside a localization string")
def loc_raw_newline(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    for lf in ctx.mod.loc_files:
        try:
            text = lf.path.read_bytes().decode("utf-8-sig", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            colon = stripped.find(":")
            if colon <= 0:
                continue
            after = stripped[colon + 1:].lstrip("0123456789 ").strip()
            if not after.startswith('"'):
                continue
            if after.count('"') % 2 == 1:
                findings.append(Finding(
                    rule="E006", severity="error", path=lf.path, line=lineno,
                    fixable="Join the split string with the \n escape",
                    message=(
                        "localization value opens a quote that never closes "
                        "on this line. A real newline splits the string and "
                        "the game throws 'Missing quoted string value'. Use "
                        "the two-character escape \\n inside the quotes "
                        "instead.")))
    return findings


@rule("W101", "Effective starting-technology level changed vs vanilla",
      needs_vanilla=True)
def chain_max_shift(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    vanilla_advances = ctx.vanilla_advances()
    mod_advances = ctx.mod_advances()
    if not vanilla_advances or not mod_advances:
        return findings

    vanilla_levels = effective_levels(vanilla_advances)

    merged = dict(vanilla_advances)
    merged.update(mod_advances)
    merged_levels = effective_levels(merged)

    for name, adv in mod_advances.items():
        if name not in vanilla_levels:
            continue
        before = vanilla_levels[name]
        after = merged_levels.get(name, before)
        if before != after:
            direction = "lower" if after < before else "higher"
            findings.append(Finding(
                rule="W101", severity="warning", path=adv.file.path,
                line=adv.line,
                message=(
                    f"'{name}': effective starting level changed from "
                    f"{before} to {after} ({direction}). A country starts "
                    "with an advance researched when the chain max of "
                    "starting_technology_level over the advance and all "
                    "its ancestors is at or below the country level, so "
                    "re-parenting silently changes who starts with it. "
                    "Bake the vanilla chain max into this advance if the "
                    "change is unintended.")))

    # Also: vanilla advances whose level shifted because a mod advance
    # sits in their ancestry chain.
    reported = {f.line and f.message.split("'")[1] for f in findings}
    changed_others = []
    for name, before in vanilla_levels.items():
        if name in mod_advances or name in reported:
            continue
        after = merged_levels.get(name, before)
        if before != after:
            changed_others.append((name, before, after))
    if changed_others:
        sample = ", ".join(
            f"{n} ({b}->{a})" for n, b, a in changed_others[:5])
        more = len(changed_others) - 5
        suffix = f" and {more} more" if more > 0 else ""
        anchor = next(iter(mod_advances.values()))
        findings.append(Finding(
            rule="W101", severity="warning", path=anchor.file.path, line=1,
            message=(
                f"{len(changed_others)} vanilla advances changed effective "
                f"starting level through modded ancestors: {sample}{suffix}. "
                "Every one of these silently changes which countries start "
                "with the advance researched.")))
    return findings


@rule("W102", "Full-file override of a vanilla file", needs_vanilla=True)
def override_drift(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    assert ctx.vanilla is not None
    for sf in ctx.mod.scripts:
        vanilla_sf = ctx.vanilla.by_rel.get(sf.rel.lower())
        if vanilla_sf is None:
            continue
        try:
            mod_lines = sf.path.read_bytes().decode(
                "utf-8-sig", errors="replace").splitlines()
            van_lines = vanilla_sf.path.read_bytes().decode(
                "utf-8-sig", errors="replace").splitlines()
        except OSError:
            continue
        if mod_lines == van_lines:
            findings.append(Finding(
                rule="W102", severity="info", path=sf.path, line=1,
                fixable="Rename the do-nothing copy to .eu5lint-removed",
                message=(
                    f"identical copy of vanilla {sf.rel}. It does nothing "
                    "today but will silently revert this file's future "
                    "vanilla changes after every game patch. Remove it or "
                    "keep it on the re-diff checklist.")))
            continue
        diff = sum(1 for line in difflib.unified_diff(
            van_lines, mod_lines, lineterm="", n=0)
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))
        findings.append(Finding(
            rule="W102", severity="info", path=sf.path, line=1,
            message=(
                f"full-file override of vanilla {sf.rel} "
                f"({diff} changed lines). Same-named files replace the "
                "vanilla file completely, so after every game patch this "
                "copy silently reverts whatever vanilla changed here. "
                "Re-diff it against vanilla on each patch.")))
    return findings


@rule("W103", "Full-file override of a vanilla gui file", needs_vanilla=True)
def gui_override_drift(ctx: Context) -> list[Finding]:
    """Same patch-rot class as W102, for .gui files. Gui files are
    whole-file-wins (verified live July 2026: a mod replacing base
    templates restyles other mods' windows), so every same-named gui file
    silently reverts vanilla's future changes to it after each patch."""
    findings: list[Finding] = []
    assert ctx.vanilla is not None
    for rel, path in sorted(ctx.mod.gui_files.items()):
        vanilla_path = ctx.vanilla.gui_files.get(rel)
        if vanilla_path is None:
            continue
        try:
            mod_lines = path.read_bytes().decode(
                "utf-8-sig", errors="replace").splitlines()
            van_lines = vanilla_path.read_bytes().decode(
                "utf-8-sig", errors="replace").splitlines()
        except OSError:
            continue
        diff = sum(1 for line in difflib.unified_diff(
            van_lines, mod_lines, lineterm="", n=0)
            if line.startswith(("+", "-"))
            and not line.startswith(("+++", "---")))
        same = " (identical copy, does nothing today)" if diff == 0 else             f" ({diff} changed lines)"
        findings.append(Finding(
            rule="W103", severity="info", path=path, line=1,
            fixable=("Rename the do-nothing copy to .eu5lint-removed"
                     if diff == 0 else None),
            message=(
                f"full-file override of vanilla {rel}{same}. Gui files "
                "replace the vanilla file completely, so after every game "
                "patch this copy silently reverts whatever vanilla changed "
                "here. Re-diff it against vanilla on each patch.")))
    return findings


# 1.3.11 anchors for the tick-drift model. All engine behavior below was
# measured live (timed marches 2026-08-16, dice cadence 2026-08-19) or
# cross-validated against Faster Universalis (daily undersampling,
# 2026-08-21); see the Responsive Universalis engine notes.
TICK_VANILLA = {
    "HOUR_TICK": 2.0,
    "ARMY_MOVEMENT_SPEED": 0.13,
    "NAVY_MOVEMENT_SPEED": 0.5,
    "COMBAT_HOURLY_MORALE_TICK": 0.01,
    "COMBAT_DAMAGE_MULT": 0.01,
    "MINIMUM_COMBAT_DURATION": 24.0,
    "MINIMUM_NAVAL_COMBAT_DURATION": 72.0,
    "HOURS_PER_PHASE": 5.0,
}


def _mod_defines(ctx: Context) -> dict[str, tuple[float, "object", int]]:
    """name -> (value, file, line) across the mod's defines files,
    last file in load order wins per key."""
    out: dict[str, tuple[float, object, int]] = {}
    for sf in sorted(ctx.mod.db_files("defines"), key=lambda s: s.rel):
        try:
            parsed = sf.parsed()
        except OSError:
            continue
        for block in parsed.root.key_values():
            if not block.is_block:
                continue
            for kv in block.value.key_values():
                if kv.is_block:
                    continue
                try:
                    out[kv.key] = (float(kv.value), sf, kv.line)
                except (TypeError, ValueError):
                    continue
    return out


@rule("W104", "Tick change without drift compensation")
def tick_drift(ctx: Context) -> list[Finding]:
    """The simulation has per-tick systems: they run once per tick no
    matter how many game hours the tick spans. A mod that raises
    HOUR_TICK without rescaling them slows those systems down in
    calendar terms. Movement accrues per tick (timed-march proven) and
    combat advances a fixed 2 hours per tick (dice-cadence proven), and
    ticks longer than 24 hours additionally undersample every daily
    system. This rule does the arithmetic and prints the correct values."""
    defines = _mod_defines(ctx)
    ht = defines.get("HOUR_TICK")
    if ht is None or ht[0] == TICK_VANILLA["HOUR_TICK"]:
        return []
    ratio = ht[0] / TICK_VANILLA["HOUR_TICK"]
    sf, line = ht[1], ht[2]
    findings: list[Finding] = []

    def value_of(key):
        got = defines.get(key)
        return got[0] if got else None

    def off(key, expected, tol=0.05):
        got = value_of(key)
        if got is None:
            return True
        return abs(got - expected) > abs(expected) * tol

    army = TICK_VANILLA["ARMY_MOVEMENT_SPEED"] * ratio
    navy = TICK_VANILLA["NAVY_MOVEMENT_SPEED"] * ratio
    if off("ARMY_MOVEMENT_SPEED", army) or off("NAVY_MOVEMENT_SPEED", navy):
        findings.append(Finding(
            rule="W104", severity="warning", path=sf.path, line=line,
            fixable="Write the correct movement values into this file",
            message=(
                f"HOUR_TICK {ht[0]:g} without movement compensation: "
                "movement accrues per tick, so armies and navies will "
                f"move ~{ratio:g}x slower per calendar day than vanilla "
                "(timed-march proven on 1.3.11). Expected "
                f"ARMY_MOVEMENT_SPEED = {army:g} and NAVY_MOVEMENT_SPEED "
                f"= {navy:g} (vanilla 0.13 / 0.5 times the tick ratio).")))

    morale = TICK_VANILLA["COMBAT_HOURLY_MORALE_TICK"] * ratio
    dmg = TICK_VANILLA["COMBAT_DAMAGE_MULT"] * ratio
    min_land = TICK_VANILLA["MINIMUM_COMBAT_DURATION"] / ratio
    min_naval = TICK_VANILLA["MINIMUM_NAVAL_COMBAT_DURATION"] / ratio
    hpp = TICK_VANILLA["HOURS_PER_PHASE"] / ratio
    combat_off = (off("COMBAT_HOURLY_MORALE_TICK", morale)
                  or off("COMBAT_DAMAGE_MULT", dmg)
                  or off("MINIMUM_COMBAT_DURATION", min_land, tol=0.5)
                  or off("MINIMUM_NAVAL_COMBAT_DURATION", min_naval, tol=0.5)
                  or off("HOURS_PER_PHASE", hpp, tol=0.5))
    if combat_off:
        findings.append(Finding(
            rule="W104", severity="warning", path=sf.path, line=line,
            fixable="Write the correct combat values into this file",
            message=(
                f"HOUR_TICK {ht[0]:g} without combat compensation: combat "
                "advances a fixed 2 hours per tick, so battles will run "
                f"~{ratio:g}x longer in calendar days (dice-cadence proven "
                "on 1.3.11). Expected roughly: COMBAT_HOURLY_MORALE_TICK "
                f"= {morale:g}, COMBAT_DAMAGE_MULT = {dmg:g}, "
                f"MINIMUM_COMBAT_DURATION = {min_land:g}, "
                f"MINIMUM_NAVAL_COMBAT_DURATION = {min_naval:g}, "
                f"HOURS_PER_PHASE = {hpp:g} (nearest integer). If the mod "
                "compensates through modifiers or script instead, this is "
                "intentional.")))

    if ht[0] > 24:
        pct = 24.0 / ht[0]
        findings.append(Finding(
            rule="W104", severity="warning", path=sf.path, line=line,
            message=(
                f"HOUR_TICK {ht[0]:g} is longer than a day. A tick spans "
                f"{ht[0] / 24:.2f} days but daily systems only process one "
                f"day per tick, so every day-denominated mechanic runs at "
                f"~{pct:.0%} speed (sieges, parliament, recovery rates, "
                "education...). Each one needs hand-scaling; systems you "
                "miss drift silently (cross-validated on 1.3.11).")))
    return findings
