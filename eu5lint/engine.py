"""File discovery, mod/vanilla indexing and rule running."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .parser import ParsedFile, parse_script_file

DOMAINS = ("in_game", "loading_screen", "main_menu")

# Database Entry Modes (Tinto Talks #85): the official mechanism for
# editing vanilla database entries from a mod. Keys carrying these
# prefixes are deliberate edits, not accidental re-declarations, so the
# name-based rules must not flag them. Their semantics are not modeled
# yet (INJECT is a partial edit), so prefixed advances are excluded from
# graph analysis instead of being guessed at.
ENTRY_MODE_PREFIXES = (
    "INJECT:", "REPLACE:", "TRY_INJECT:", "TRY_REPLACE:",
    "REPLACE_OR_CREATE:", "INJECT_OR_CREATE:")


def has_entry_mode(key: str) -> bool:
    return key.startswith(ENTRY_MODE_PREFIXES)

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


@dataclass
class Finding:
    rule: str
    severity: str  # error | warning | info
    path: Path
    line: int
    message: str
    # Set when the finding can be fixed mechanically with confidence:
    # a short human description of what the fix will do.
    fixable: str | None = None

    def sort_key(self):
        return (SEVERITY_ORDER.get(self.severity, 3), str(self.path), self.line)


@dataclass
class ScriptFile:
    """A .txt script file inside a mod or the vanilla game."""

    path: Path            # absolute path
    rel: str              # path relative to the mod/game root, forward slashes
    domain: str | None    # in_game / loading_screen / main_menu / None
    db: str | None        # folder under common/, e.g. "advances"
    _parsed: ParsedFile | None = field(default=None, repr=False)

    def parsed(self) -> ParsedFile:
        if self._parsed is None:
            self._parsed = parse_script_file(self.path)
        return self._parsed


@dataclass
class LocFile:
    path: Path
    rel: str


def classify(root: Path, path: Path) -> ScriptFile | None:
    rel_parts = path.relative_to(root).parts
    rel = "/".join(rel_parts)
    domain = None
    db = None
    parts = [p.lower() for p in rel_parts]
    if "common" in parts:
        ci = parts.index("common")
        if ci > 0 and parts[ci - 1] in DOMAINS:
            domain = parts[ci - 1]
        if ci + 1 < len(parts) - 1:
            db = parts[ci + 1]
    return ScriptFile(path=path, rel=rel, domain=domain, db=db)


def is_loc_path(rel_parts: tuple[str, ...]) -> bool:
    lowered = [p.lower() for p in rel_parts]
    return "localization" in lowered or "localisation" in lowered


@dataclass
class Tree:
    """An indexed file tree (a mod, or the vanilla `game` directory)."""

    root: Path
    scripts: list[ScriptFile] = field(default_factory=list)
    loc_files: list[LocFile] = field(default_factory=list)
    by_rel: dict[str, ScriptFile] = field(default_factory=dict)
    gui_files: dict[str, Path] = field(default_factory=dict)  # rel -> path

    @classmethod
    def scan(cls, root: Path) -> "Tree":
        tree = cls(root=root)
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel_parts = path.relative_to(root).parts
            if any(p.startswith(".") for p in rel_parts):
                continue
            suffix = path.suffix.lower()
            if suffix == ".txt":
                sf = classify(root, path)
                if sf is not None:
                    tree.scripts.append(sf)
                    tree.by_rel[sf.rel.lower()] = sf
            elif suffix == ".yml" and is_loc_path(rel_parts):
                tree.loc_files.append(
                    LocFile(path=path, rel="/".join(rel_parts)))
            elif suffix == ".gui":
                tree.gui_files["/".join(rel_parts).lower()] = path
        return tree

    def db_files(self, db: str) -> list[ScriptFile]:
        return [s for s in self.scripts if s.db == db]


@dataclass
class Advance:
    name: str
    line: int
    file: ScriptFile
    requires: list[tuple[str, int]]
    in_tree_of: list[tuple[str, int]]
    starting_level: int


def parse_advances(tree: Tree) -> dict[str, Advance]:
    """Last definition wins, matching engine load order (alphabetical rglob)."""
    from .parser import ref_values

    advances: dict[str, Advance] = {}
    for sf in tree.db_files("advances"):
        parsed = sf.parsed()
        for kv in parsed.root.key_values():
            if not kv.is_block:
                continue
            if has_entry_mode(kv.key):
                continue  # deliberate partial edit, semantics not modeled
            requires: list[tuple[str, int]] = []
            in_tree_of: list[tuple[str, int]] = []
            starting = 0
            for inner in kv.value.key_values():
                if inner.key == "requires":
                    requires.extend(ref_values(inner))
                elif inner.key == "in_tree_of":
                    in_tree_of.extend(ref_values(inner))
                elif inner.key == "starting_technology_level":
                    if isinstance(inner.value, str):
                        try:
                            starting = int(inner.value)
                        except ValueError:
                            pass
            advances[kv.key] = Advance(
                name=kv.key, line=kv.line, file=sf,
                requires=requires, in_tree_of=in_tree_of,
                starting_level=starting)
    return advances


def effective_levels(advances: dict[str, Advance]) -> dict[str, int]:
    """Chain-max starting level: max over the advance and all ancestors
    reachable through `requires` edges. Cycles resolve to the max seen."""

    memo: dict[str, int] = {}

    def visit(name: str, stack: frozenset[str]) -> int:
        if name in memo:
            return memo[name]
        adv = advances.get(name)
        if adv is None:
            return 0
        if name in stack:
            return adv.starting_level
        level = adv.starting_level
        for parent, _line in adv.requires:
            level = max(level, visit(parent, stack | {name}))
        memo[name] = level
        return level

    return {name: visit(name, frozenset()) for name in advances}


RuleFn = Callable[["Context"], list[Finding]]

_RULES: list[tuple[str, str, bool, RuleFn]] = []


def rule(rule_id: str, description: str, needs_vanilla: bool = False):
    def register(fn: RuleFn) -> RuleFn:
        _RULES.append((rule_id, description, needs_vanilla, fn))
        return fn
    return register


def all_rules() -> list[tuple[str, str, bool, RuleFn]]:
    return list(_RULES)


@dataclass
class Context:
    mod: Tree
    vanilla: Tree | None
    _mod_advances: dict[str, Advance] | None = None
    _vanilla_advances: dict[str, Advance] | None = None
    _vanilla_static_names: set[str] | None = None

    def mod_advances(self) -> dict[str, Advance]:
        if self._mod_advances is None:
            self._mod_advances = parse_advances(self.mod)
        return self._mod_advances

    def vanilla_advances(self) -> dict[str, Advance]:
        if self._vanilla_advances is None:
            self._vanilla_advances = (
                parse_advances(self.vanilla) if self.vanilla else {})
        return self._vanilla_advances

    def vanilla_static_names(self) -> set[str]:
        if self._vanilla_static_names is None:
            names: set[str] = set()
            if self.vanilla:
                for sf in self.vanilla.db_files("static_modifiers"):
                    for kv in sf.parsed().root.key_values():
                        if kv.is_block:
                            names.add(kv.key)
            self._vanilla_static_names = names
        return self._vanilla_static_names


def is_suppressed(finding: Finding, parsed: ParsedFile | None) -> bool:
    if parsed is None:
        return False
    if parsed.suppress_file:
        return True
    rules_at_line = parsed.suppressions.get(finding.line)
    if rules_at_line is None:
        return False
    return not rules_at_line or finding.rule in rules_at_line


MOD_MARKER_DIRS = {"in_game", "loading_screen", "main_menu", "common",
                   "gui", "localization", "events", "gfx", "map_data",
                   "sound", ".metadata"}


def looks_like_mod(path: Path) -> bool:
    """Cheap preflight: does this folder look like an EU5 mod at all?
    Prevents accidentally scanning huge unrelated folders (drive roots, the game
    install, Documents) which reads as a hang."""
    try:
        names = {p.name.lower() for p in path.iterdir() if p.is_dir()}
    except OSError:
        return False
    return bool(names & MOD_MARKER_DIRS)


def scan_vanilla(vanilla_path: Path) -> "Tree":
    """Scan the game tree once; callers may cache and pass to run()."""
    game_dir = vanilla_path / "game"
    return Tree.scan(game_dir if game_dir.is_dir() else vanilla_path)


def run(mod_path: Path, vanilla_path: Path | None,
        enabled: set[str] | None = None,
        disabled: set[str] | None = None,
        vanilla_tree: "Tree | None" = None) -> tuple[list[Finding], list[str]]:
    """Run every applicable rule. Returns (findings, skipped_rule_ids)."""
    from . import rules  # noqa: F401  (registers rules on import)

    mod = Tree.scan(mod_path)
    vanilla = vanilla_tree
    if vanilla is None and vanilla_path is not None:
        vanilla = scan_vanilla(vanilla_path)
    ctx = Context(mod=mod, vanilla=vanilla)

    findings: list[Finding] = []
    skipped: list[str] = []
    parsed_cache: dict[Path, ParsedFile] = {}
    for sf in mod.scripts:
        try:
            parsed_cache[sf.path] = sf.parsed()
        except OSError:
            continue

    # Parse problems are findings too: a half-swallowed file could
    # otherwise silently hide real findings in everything after it.
    if not disabled or "P001" not in disabled:
        if not enabled or "P001" in enabled:
            for sf in mod.scripts:
                parsed = parsed_cache.get(sf.path)
                if parsed is None or parsed.suppress_file:
                    continue
                for note in parsed.parse_notes[:3]:
                    findings.append(Finding(
                        rule="P001", severity="info", path=sf.path, line=1,
                        message=f"parse note: {note}. Findings after this "
                                "point in the file may be incomplete."))
                if len(parsed.parse_notes) > 3:
                    findings.append(Finding(
                        rule="P001", severity="info", path=sf.path, line=1,
                        message=f"{len(parsed.parse_notes) - 3} more parse "
                                "notes in this file."))

    for rule_id, _desc, needs_vanilla, fn in all_rules():
        if enabled and rule_id not in enabled:
            continue
        if disabled and rule_id in disabled:
            continue
        if needs_vanilla and vanilla is None:
            skipped.append(rule_id)
            continue
        for finding in fn(ctx):
            parsed = parsed_cache.get(finding.path)
            if not is_suppressed(finding, parsed):
                findings.append(finding)

    findings.sort(key=Finding.sort_key)
    return findings, skipped
