# eu5-mod-lint

A linter for Europa Universalis V mods. It catches the mistakes the game
loads **without any error** and simply ignores.

EU5's engine accepts a lot of broken input silently. The files parse,
error.log stays quiet, and your mod just does not do what you wrote. Every
rule in this tool is one of those traps, found the hard way while
maintaining live Workshop mods on EU5 1.3.x, then verified by bisecting
against the real game. None of them are documented anywhere else.

## Quickstart

Python 3.10+, no dependencies.

```
git clone https://github.com/mattebin/eu5-mod-lint
cd eu5-mod-lint
python -m eu5lint path\to\your\mod
```

The vanilla-aware rules need your EU5 install. The tool auto-detects
common Steam locations. If yours is somewhere else:

```
python -m eu5lint path\to\your\mod --vanilla "D:\Games\Europa Universalis V"
```

## What it catches

| Rule | What it catches | Why it is silent |
|---|---|---|
| E001 | An advance references a `requires` or `in_tree_of` key defined later in the same file | References resolve at parse time in file order. A forward reference fails with only a buried log line and the advance loads half broken. |
| E002 | An `in_tree_of` target that is not a root | The engine only accepts depth-0 roots as tree anchors. Demoting one detaches every advance attached to it. |
| E003 | An auto modifier with `category = location` | The engine only evaluates auto modifiers for countries and international organizations. A location one loads fine and is never applied. This exact trap killed a shipped feature for days. |
| E004 | A new block name invented in `static_modifiers` | The scaled static-modifier system applies blocks by name. The engine cannot scale a name it does not know, so the block is dead on arrival. Extend a vanilla block instead. |
| E005 | A defines file without the UTF-8 BOM | Defines overrides can fail to load without it. |
| E006 | A raw newline inside a quoted localization string | Splits the string and throws `Missing quoted string value`. The fix is the two-character escape `\n`. |
| W101 | Effective starting-technology level changed against vanilla | A country starts with an advance researched when the chain max of `starting_technology_level` over the advance and all its ancestors fits the country level. Re-parenting an advance silently changes who starts with what, across the whole world. |
| W102 | Full-file overrides of vanilla files | A same-named file replaces the vanilla file completely. After every game patch it silently reverts whatever vanilla changed there. This rule is your re-diff checklist. |
| P001 | Anything the linter itself could not parse | So a broken region never silently hides findings behind it. |

## The one-digit demo

We took a published tech tree mod (3156 advances, all green in game and
in error.log) and changed a single `starting_technology_level = 3` to `1`.
The linter caught the edited advance and traced the ripple: four vanilla
advances in culture-unique trees silently changed their effective starting
level through the modded ancestry. Nothing in the game would have told
anyone. That is the class of bug this tool exists for.

## Suppressing a finding

Same line, in a comment:

```
my_block = { # eu5lint:ignore E003
```

`# eu5lint:ignore` with no rule ids suppresses every rule on that line.
`# eu5lint:ignore-file` in the first three lines skips the whole file.

## For CI

`--format json` prints machine-readable output. Exit code is 1 when there
are errors, 0 otherwise. Add `--strict` to fail on warnings too.

## Game updates

Rules split into three tiers for version resilience:

1. **Vanilla-aware rules (E004, W101, W102) update themselves.** They read
   your installed game at run time instead of hardcoding any vanilla
   content, so a game patch automatically refreshes what they check
   against.
2. **Parse-behavior rules (E001, E005, E006) encode engine fundamentals**
   that are stable across patches.
3. **Engine-behavior rules could in principle be fixed by Paradox** (the
   best outcome for everyone). Because of that, the tool states the game
   version its rules were last verified on, auto-detects your version,
   and warns you to treat findings as provisional when your game is
   newer. Every rule gets re-verified against each game patch before the
   verified version is bumped.

## What this is not

It is not a schema validator. CWTools and similar editor extensions check
syntax and types and are worth using alongside this. eu5-mod-lint only
knows about behaviors that pass every syntax check and still do nothing.
The rule list is precision-first: a small number of checks that are
actually proven, instead of a large number of guesses.

Found another silent trap? Open an issue with a minimal repro. Rules only
get added once the behavior is confirmed against the live game.

## License

MIT
