"""Lint rules.

Every rule here targets a failure the game engine accepts SILENTLY:
the files load, error.log stays quiet (or nearly quiet), and the mod
simply does not do what its author intended. All of them were found
the hard way, by bisecting live mods against EU5 1.3.x.
"""

from __future__ import annotations

import difflib

from .engine import Context, Finding, effective_levels, rule
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
            if kv.is_block and kv.key not in known:
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
                        "by name this is intentional; otherwise extend "
                        "the matching vanilla block via a full-file "
                        "copy.")))
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
            if kv.is_block and kv.key in known:
                findings.append(Finding(
                    rule="E007", severity="error", path=sf.path,
                    line=kv.line,
                    message=(
                        f"'{kv.key}' re-declares a vanilla static "
                        "modifier block in an added file. The engine "
                        "drops the whole block as a duplicate "
                        "('Duplicated key will not be created', verified "
                        "1.3.11): it does not extend or override "
                        "anything. To change a vanilla scaled block, "
                        "copy the entire vanilla file to the same path "
                        "in your mod and edit it there.")))
    return findings


@rule("E005", "Defines file without UTF-8 BOM")
def defines_bom(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    for sf in ctx.mod.db_files("defines"):
        raw = sf.path.read_bytes()
        if not raw.startswith(UTF8_BOM):
            findings.append(Finding(
                rule="E005", severity="warning", path=sf.path, line=1,
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
