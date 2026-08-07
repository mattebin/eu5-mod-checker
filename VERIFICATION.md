# Verification dossier

Every rule in eu5lint is backed by a live-game verification. This file is
the evidence: claim, minimal repro, the engine's own response, and the
player-visible consequence. Method: the probe mod in `probes/eu5lint-probe`
junctioned into the mod folder, fresh single-player campaigns, -tdebug,
error.log read after each session, plus live tooltip observation for the
positive controls.

Verified on: **EU5 1.3.11** (Steam public branch), 2026-08-08.
Earlier provenance: the advances rules were first proven on 1.3.10 beta
during a nine-round bisect of a live Workshop mod, July 2026.

## E001: forward references in advances fail at parse time

**Claim:** `requires = X` pointing at a key defined later in the same file
fails. References resolve at parse time in file order.

**Repro:** `probes/.../advances/zz_eu5lint_probe_advances.txt`,
`lint_probe_e001_child` requires `lint_probe_e001_parent`, defined below it.

**Engine response:**
`[pdx_persistent_reader.cpp:289]: Error: "Failed to read key reference:
lint_probe_e001_parent" in file: "common/advances/zz_eu5lint_probe_advances.txt"`

**Consequence (the trap):** the advance still exists, still gets researched,
its effects still apply (observed live: both probe advances researched at
campaign start, modifiers visible in the prestige tooltip). Only the
dependency edge is missing, so the tree is silently miswired while
everything looks like it works.

## E002: in_tree_of targets must be roots

**Claim:** an `in_tree_of` target that has `requires` is rejected.

**Repro:** same file, `lint_probe_e002_leaf` has
`in_tree_of = lint_probe_e002_hub`, and hub has requires.

**Engine response:**
`[advance_definition.cpp:1435]: The advance 'lint_probe_e002_leaf'
(age_1_traditions) has in_tree_of that is not a root 'lint_probe_e002_hub'`

**Consequence:** the leaf's tree attachment is broken while the advance
itself keeps existing and applying (observed live, same tooltip).

## E003a: game_data blocks are invalid inside auto_modifiers

**Claim:** auto modifiers take scope from the file, not from a game_data
category block. A game_data block is rejected as an unknown modifier type.

**Repro:** `probes/.../auto_modifiers/zz_eu5lint_probe.txt`, two blocks
with `game_data = { category = ... }`.

**Engine response:**
`[pdx_persistent_reader.cpp:289]: Error: "Unknown modifier type: game_data.
It is either invalid, or a potential dynamic modifier type definition
missing from the database."` (twice, once per block)

**Positive control:** the same file's country-scope block
(`lint_probe_e003_control`, potential_trigger + monthly_prestige) applies
and is visible on the country: +10.00 monthly prestige observed live in
the prestige breakdown, labeled AUTO_MODIFIER_NAME_lint_probe_e003_control.
Custom-named files in common/auto_modifiers ARE evaluated at country scope.

**Open question for Paradox:** do location-scope keys (local_*) inside an
auto modifier apply from country scope, or are they silently dropped? A
live mod lost a feature to this on 1.3.x. We do not claim either way.

## E004: invented static-modifier block names are dead

**Claim:** the scaled static-modifier system applies blocks by
engine-known name. A new name is never applied by the scaling code.

**Repro:** `probes/.../static_modifiers/zz_eu5lint_probe.txt`,
block `lint_probe_e004_invented`.

**Engine response (the engine says it itself):**
`[static_modifier.cpp:516]: Modifier 'lint_probe_e004_invented' was not
used by the script or code but exists in the database, this is a waste`

## E005: missing UTF-8 BOM on defines is a warning, not a failure

**Claim (corrected by this verification):** a defines file without BOM
loads and applies. The engine logs a lexer warning.

**Repro:** two defines files, `aa_` WITH BOM setting HOUR_TICK 6, `zz_`
WITHOUT BOM setting HOUR_TICK 12.

**Engine response:**
`[lexer.cpp:501]: File 'common/defines/zz_eu5lint_probe_nobom.txt' should
be in utf8-bom encoding (will try to use it anyways)`

**Observed:** 2 ticks per day, twice, in two separate sessions - the
no-BOM file loaded and won. Our own earlier rule said BOM was required;
this probe falsified it and the rule was corrected before release.

## E007: re-declaring a vanilla static block in an added file is dropped

**Claim:** a same-named static-modifier block in a new file does not
extend or override the vanilla block. The engine drops the duplicate,
first definition wins. Extending requires copying the whole vanilla file
to the same path.

**Repro:** same probe file, a `capital = { ... }` block copying vanilla's
values plus one added line.

**Engine response:**
`[gamedatabase.h:408]: Duplicated key capital will not be created from
file: common/static_modifiers/zz_eu5lint_probe.txt:11`

**Note:** this rule was not on our list. The probe run discovered it.

## W101: starting research follows the chain max of starting_technology_level

**Claim:** a country starts with an advance researched iff the maximum
starting_technology_level over the advance and all its requires-ancestors
is at or below the country's starting level. A missing field counts as 0
and inherits the chain. Re-parenting an advance therefore silently
changes starting tech for countries the modder never touched.

**Provenance:** proven on 1.3.10 beta via a nine-round bisect after real
players hit it in a shipped tech-tree mod (public bug-report trail on the
Workshop: European countries lost starting Taxation). Consistent with
1.3.11: the probe advances carry no starting_technology_level and were
researched from start, as the rule predicts.

## W102: same-named files replace vanilla files completely

Standard Jomini load behavior, relied on by every full-file override in
the verified mods; the linter reports the override surface as a re-diff
checklist rather than claiming a defect.
