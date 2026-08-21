# EU5 Mod Checker

I make EU5 mods and kept losing days to mistakes the game loads without
any error. The files parse, error.log stays quiet, and the mod just does
not do what you wrote. So I built a checker for exactly those mistakes.
Every rule in it comes from a real bug in a live Workshop mod, then was
verified against the actual game.

## How to use it

1. Download **EU5 Mod Checker.exe** from the
   [latest release](https://github.com/mattebin/eu5-mod-checker/releases/latest).
   One file, no install.
2. Run it and pick your mod **folder**. Not a file, the folder - the one
   that has `in_game`, `loading_screen` or `main_menu` inside it. Examples:

   ```
   C:\Users\YOU\Documents\Paradox Interactive\Europa Universalis V\mod\my-mod
   C:\Program Files (x86)\Steam\steamapps\workshop\content\3450310\123456789
   ```

   Mods in your Paradox mod folder show up in the dropdown on their own.
3. Press **Check mod**. Click any line to see what is wrong and what to
   do about it, in plain language.

The **Fix automatically** button repairs the problems that can be fixed
safely. Everything is backed up first and one click reverts it all.

The first check reads your whole game folder once, so it takes the
longest. After that checks are quick.

## What it catches

| Rule | What it catches | Why it is silent |
|---|---|---|
| E001 | An advance references a `requires` or `in_tree_of` key defined later in the same file | References resolve at parse time in file order. A forward reference fails with only a buried log line and the advance loads half broken. |
| E002 | An `in_tree_of` target that is not a root | The engine only accepts depth-0 roots as tree anchors. Demoting one detaches every advance attached to it. |
| E003 | A `game_data` block or location-scope keys inside auto_modifiers | Auto modifiers take scope from the file, not the block. game_data is static-modifier syntax and gets rejected as an unknown modifier type. A location-scope pillar died silently this way in a shipped mod. |
| E004 | A new block name invented in `static_modifiers` | The scaled static-modifier system applies blocks by name. The engine confirms it at load: "was not used by the script or code but exists in the database, this is a waste". |
| E005 | A defines file without the UTF-8 BOM | The engine logs a lexer warning and loads it anyway. Paradox's own files ship with BOM, so keep loads warning-free. |
| E006 | A raw newline inside a quoted localization string | Splits the string and throws `Missing quoted string value`. The fix is the two-character escape `\n`. |
| E007 | A vanilla static-modifier block re-declared in an added file | The engine drops the whole block as a duplicated key. It does not extend or override anything. Extending requires a full-file copy at the vanilla path. |
| W101 | Effective starting-technology level changed against vanilla | A country starts with an advance researched when the chain max of `starting_technology_level` over the advance and all its ancestors fits the country level. Re-parenting an advance silently changes who starts with what, across the whole world. |
| W102 | Full-file overrides of vanilla files | A same-named file replaces the vanilla file completely. After every game patch it silently reverts whatever vanilla changed there. This rule is your re-diff checklist. |
| W103 | Full-file overrides of vanilla `.gui` files | Same patch-rot class as W102: gui files are whole-file-wins, so each override silently reverts vanilla's future changes to that window. |
| W104 | `HOUR_TICK` changed without drift compensation | Movement accrues per tick and combat advances a fixed 2 hours per tick (both measured on 1.3.11), so an unrescaled tick change slows them in calendar time. Ticks over 24h also undersample every daily system. The finding prints the correct compensation values for your tick. |
| P001 | Anything the checker itself could not parse | So a broken region never silently hides findings behind it. |
| S001 | A field name vanilla never uses in that database | Unknown keys load without any error and do nothing. The corpus comes from your installed game plus the engine itself, so typos get caught and rare-but-real keys pass. Suggests the closest real name. |
| S002 | A define the engine does not register, or a real define in the wrong N block | Checked against your own eu5.exe. Both cases load silently and do nothing. The wrong-block case tells you which block it actually belongs in. |

## Automatic fixes

`--fix` on the command line, or the Fix automatically button in the app.
It repairs what can be repaired with confidence: missing BOMs, split
localization strings, do-nothing identical override copies (renamed out
of the way, never deleted), and tick compensation values. Anything that
needs a design decision stays a finding.

## Command line

Python 3.10+, no dependencies.

```
git clone https://github.com/mattebin/eu5-mod-checker
cd eu5-mod-checker
python -m eu5lint path\to\your\mod
```

The vanilla-aware rules find your EU5 install on their own in common
Steam locations. Somewhere else: add
`--vanilla "D:\Games\Europa Universalis V"`. For CI: `--format json`,
exit code 1 on errors, `--strict` to fail on warnings too.

## The one-digit demo

I took a published tech tree mod (3156 advances, all green in game and
in error.log) and changed a single `starting_technology_level = 3` to `1`.
The checker caught the edited advance and traced the ripple: four vanilla
advances in culture-unique trees silently changed their effective starting
level through the modded ancestry. Nothing in the game would have told
anyone. That is the class of bug this tool exists for.

## How the rules stay honest

[VERIFICATION.md](VERIFICATION.md) has each rule's minimal repro and the
engine's actual response. The repro mod in `probes/eu5lint-probe` is
re-run against every game patch before the verified version is bumped.
The tool states which game version its rules were verified on and warns
you when your game is newer.

Structure errors (broken braces, split strings) and unknown names are
covered by P001, E006, S001 and S002. For live checking while you type,
CWTools in VS Code is worth using alongside this.

Found another silent trap? Open an issue with a small repro. Rules only
get added once the behavior is confirmed against the live game.

## Suppressing a finding

Same line, in a comment: `# eu5lint:ignore E003` (no rule id = all rules
on that line). `# eu5lint:ignore-file` in the first three lines skips
the whole file.

## License

MIT

---

Made by [Scoopiepoop](https://steamcommunity.com/profiles/76561198092461973/myworkshopfiles/?appid=3450310),
the Responsive Universalis mods for EU5.
