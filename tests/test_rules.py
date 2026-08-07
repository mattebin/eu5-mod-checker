"""Every rule is sabotage-tested: it must fire on a bad fixture and stay
silent on a clean one. A rule that cannot fail is not a check."""

from pathlib import Path

import pytest

from eu5lint.engine import run

BOM = "﻿"


def write(root: Path, rel: str, text: str, bom: bool = False) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (BOM + text if bom else text).encode("utf-8")
    path.write_bytes(data)


@pytest.fixture
def mod(tmp_path: Path) -> Path:
    mod_dir = tmp_path / "mod"
    mod_dir.mkdir()
    return mod_dir


@pytest.fixture
def vanilla(tmp_path: Path) -> Path:
    """Minimal fake EU5 install with a game/ directory."""
    van = tmp_path / "eu5"
    game = van / "game"
    write(game, "in_game/common/advances/00_core.txt", """
root_a = { starting_technology_level = 2 }
child_a = { requires = root_a }
grandchild_a = { requires = child_a starting_technology_level = 1 }
unlock_hub = { }
attached = { in_tree_of = unlock_hub }
""")
    write(game, "main_menu/common/static_modifiers/location.txt", """
inverse_control = { local_unrest = -1 }
has_road = { local_monthly_control = 0.0005 }
""")
    return van


def run_ids(mod_dir: Path, vanilla_dir: Path | None = None,
            severity: str | None = None) -> list[str]:
    findings, _skipped = run(mod_dir, vanilla_dir)
    if severity:
        findings = [f for f in findings if f.severity == severity]
    return [f.rule for f in findings]


# E001 forward reference

def test_e001_fires_on_forward_reference(mod):
    write(mod, "in_game/common/advances/tree.txt", """
early = { requires = late }
late = { }
""")
    assert "E001" in run_ids(mod)


def test_e001_silent_when_sorted(mod):
    write(mod, "in_game/common/advances/tree.txt", """
late = { }
early = { requires = late }
""")
    assert "E001" not in run_ids(mod)


def test_e001_cross_file_reference_not_flagged(mod):
    write(mod, "in_game/common/advances/a.txt", "x = { requires = elsewhere }\n")
    write(mod, "in_game/common/advances/b.txt", "elsewhere = { }\n")
    assert "E001" not in run_ids(mod)


# E002 in_tree_of target must stay a root

def test_e002_fires_when_target_demoted(mod):
    write(mod, "in_game/common/advances/tree.txt", """
base = { }
hub = { requires = base }
leaf = { in_tree_of = hub }
""")
    assert "E002" in run_ids(mod)


def test_e002_fires_when_mod_demotes_vanilla_target(mod, vanilla):
    # vanilla: 'attached' has in_tree_of = unlock_hub (a root there).
    # The mod redefines unlock_hub WITH requires: demotes the root.
    write(mod, "in_game/common/advances/patch.txt", """
some_parent = { }
unlock_hub = { requires = some_parent }
""")
    assert "E002" in run_ids(mod, vanilla)


def test_e002_silent_on_root_target(mod):
    write(mod, "in_game/common/advances/tree.txt", """
hub = { }
leaf = { in_tree_of = hub }
""")
    assert "E002" not in run_ids(mod)


# E003 auto modifier content (probe-verified 1.3.11)

def test_e003_fires_on_game_data_block(mod):
    write(mod, "in_game/common/auto_modifiers/bad.txt", """
my_modifier = {
    game_data = { category = location }
    monthly_prestige = 0.1
}
""")
    assert "E003" in run_ids(mod, severity="error")


def test_e003_warns_on_local_key(mod):
    write(mod, "in_game/common/auto_modifiers/local.txt", """
my_modifier = {
    potential_trigger = { always = yes }
    local_unrest = 5
}
""")
    assert "E003" in run_ids(mod, severity="warning")
    assert "E003" not in run_ids(mod, severity="error")


def test_e003_silent_on_country_shape(mod):
    # The probe-verified working shape: country-scope keys, no game_data.
    write(mod, "in_game/common/auto_modifiers/alive.txt", """
my_live_modifier = {
    potential_trigger = { always = yes }
    monthly_prestige = 0.1
}
""")
    assert "E003" not in run_ids(mod)


def test_e003_suppressible_inline(mod):
    write(mod, "in_game/common/auto_modifiers/bad.txt", """
known_bad = {
    game_data = { category = location } # eu5lint:ignore E003
}
""")
    assert "E003" not in run_ids(mod)


# E004 invented static-modifier block names

def test_e004_fires_on_invented_block(mod, vanilla):
    write(mod, "main_menu/common/static_modifiers/mine.txt", """
my_new_scaled_block = { local_unrest = -1 }
""")
    assert "E004" in run_ids(mod, vanilla)


# E007 re-declared vanilla static blocks (probe-discovered 1.3.11)

def test_e007_fires_on_redeclaration_in_added_file(mod, vanilla):
    write(mod, "main_menu/common/static_modifiers/mine.txt", """
inverse_control = { local_unrest = -3 }
""")
    assert "E007" in run_ids(mod, vanilla, severity="error")


def test_e007_and_e004_silent_in_full_file_override(mod, vanilla):
    # Same path as vanilla: re-declaring there is the override mechanism.
    write(mod, "main_menu/common/static_modifiers/location.txt", """
inverse_control = { local_unrest = -3 }
has_road = { local_monthly_control = 0.0005 }
""")
    ids = run_ids(mod, vanilla)
    assert "E007" not in ids
    assert "E004" not in ids


def test_e004_skipped_without_vanilla(mod):
    write(mod, "main_menu/common/static_modifiers/mine.txt", """
my_new_scaled_block = { local_unrest = -1 }
""")
    findings, skipped = run(mod, None)
    assert "E004" in skipped
    assert "E004" not in [f.rule for f in findings]


# E005 defines BOM

def test_e005_warns_without_bom(mod):
    # Probe-verified 1.3.11: the file loads and applies anyway, so this
    # is a warning about the lexer complaint, not an error.
    write(mod, "loading_screen/common/defines/zz_my_defines.txt",
          "NGame = { HOUR_TICK = 6 }\n", bom=False)
    assert "E005" in run_ids(mod, severity="warning")
    assert "E005" not in run_ids(mod, severity="error")


def test_e005_silent_with_bom(mod):
    write(mod, "loading_screen/common/defines/zz_my_defines.txt",
          "NGame = { HOUR_TICK = 6 }\n", bom=True)
    assert "E005" not in run_ids(mod)


# E006 loc raw newline

def test_e006_fires_on_split_string(mod):
    write(mod, "main_menu/localization/english/mod_l_english.yml",
          'l_english:\n my_key:0 "first line\n second line"\n', bom=True)
    assert "E006" in run_ids(mod)


def test_e006_silent_on_escaped_newline(mod):
    write(mod, "main_menu/localization/english/mod_l_english.yml",
          'l_english:\n my_key:0 "first\\nsecond"\n', bom=True)
    assert "E006" not in run_ids(mod)


# W101 chain-max starting level shifts

def test_w101_fires_on_reparenting_shift(mod, vanilla):
    # vanilla: grandchild_a requires child_a requires root_a (level 2),
    # so its effective level is 2. The mod re-parents grandchild_a to a
    # fresh level-0 root: effective level drops to 1.
    write(mod, "in_game/common/advances/restructure.txt", """
new_root = { }
grandchild_a = { requires = new_root starting_technology_level = 1 }
""")
    assert "W101" in run_ids(mod, vanilla)


def test_w101_silent_when_chain_max_baked(mod, vanilla):
    # Same re-parenting, but the mod bakes the vanilla chain max (2).
    write(mod, "in_game/common/advances/restructure.txt", """
new_root = { }
grandchild_a = { requires = new_root starting_technology_level = 2 }
""")
    assert "W101" not in run_ids(mod, vanilla)


# W102 full-file overrides

def test_w102_reports_override_and_identical_copy(mod, vanilla):
    write(mod, "main_menu/common/static_modifiers/location.txt", """
inverse_control = { local_unrest = -1 }
has_road = { local_monthly_control = 0.0005 }
""")
    findings, _ = run(mod, vanilla)
    w102 = [f for f in findings if f.rule == "W102"]
    assert len(w102) == 1
    assert "identical copy" in w102[0].message


def test_w102_reports_drift_line_count(mod, vanilla):
    write(mod, "main_menu/common/static_modifiers/location.txt", """
inverse_control = { local_unrest = -5 }
has_road = { local_monthly_control = 0.0005 }
""")
    findings, _ = run(mod, vanilla)
    w102 = [f for f in findings if f.rule == "W102"]
    assert len(w102) == 1
    assert "changed lines" in w102[0].message


def test_w102_silent_on_new_files(mod, vanilla):
    write(mod, "main_menu/common/static_modifiers/zz_mine.txt", """
inverse_control = { local_unrest = -1 }
""")
    assert "W102" not in run_ids(mod, vanilla)


# file-level suppression

def test_ignore_file_suppresses_everything(mod):
    write(mod, "in_game/common/advances/tree.txt", """# eu5lint:ignore-file
early = { requires = late }
late = { }
""")
    assert run_ids(mod) == []
