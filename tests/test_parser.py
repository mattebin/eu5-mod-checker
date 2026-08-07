from pathlib import Path

from eu5lint.parser import read_script_bytes, ref_values


def parse(text: str):
    return read_script_bytes(text.encode("utf-8"), Path("test.txt"))


def test_key_values_and_blocks():
    parsed = parse("""
foo = {
    bar = 1
    baz = "quoted value"
    nested = { a = b }
}
""")
    foo = parsed.root.find("foo")
    assert foo is not None and foo.is_block
    assert foo.value.scalar("bar") == "1"
    assert foo.value.scalar("baz") == "quoted value"
    nested = foo.value.find("nested")
    assert nested.is_block and nested.value.scalar("a") == "b"


def test_line_numbers_preserved():
    parsed = parse("a = 1\nb = {\n c = 2\n}\n")
    b = parsed.root.find("b")
    assert b.line == 2
    assert b.value.find("c").line == 3


def test_operators_including_scope_link():
    parsed = parse("x ?= goods:iron\ny >= 3\nz != no\n")
    assert parsed.root.find("x").op == "?="
    assert parsed.root.find("x").value == "goods:iron"
    assert parsed.root.find("y").op == ">="
    assert parsed.root.find("z").op == "!="


def test_comments_and_bare_lists():
    parsed = parse("# a comment\ncolors = { 1 2 3 } # trailing\n")
    colors = parsed.root.find("colors")
    values = [item.value for item in colors.value.items]
    assert values == ["1", "2", "3"]


def test_ref_values_single_and_list():
    parsed = parse("a = { requires = x }\nb = { requires = { y z } }\n")
    a = parsed.root.find("a").value.find("requires")
    b = parsed.root.find("b").value.find("requires")
    assert [r for r, _ in ref_values(a)] == ["x"]
    assert [r for r, _ in ref_values(b)] == ["y", "z"]


def test_bom_detected():
    with_bom = read_script_bytes(b"\xef\xbb\xbfa = 1\n", Path("t.txt"))
    without = read_script_bytes(b"a = 1\n", Path("t.txt"))
    assert with_bom.has_bom
    assert not without.has_bom


def test_tolerant_on_garbage():
    # Stray closers and operators are skipped with a note; later
    # statements still parse.
    parsed = parse("} = broken\nvalid = yes\n")
    assert parsed.root.find("valid") is not None
    assert parsed.parse_notes  # noted, not crashed


def test_unbalanced_open_brace_never_crashes():
    # An unclosed block swallows the remainder (the game itself rejects
    # such files loudly), but parsing must not crash and must say so.
    parsed = parse("a = { {{ broken\nvalid = yes\n")
    assert parsed.parse_notes


def test_suppression_comments():
    parsed = parse("a = 1 # eu5lint:ignore\nb = 2 # eu5lint:ignore E003 E005\n")
    assert parsed.suppressions[1] == set()
    assert parsed.suppressions[2] == {"E003", "E005"}
