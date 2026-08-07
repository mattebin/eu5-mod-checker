"""Tolerant parser for Clausewitz/Jomini script files.

Preserves file order and line numbers, because several EU5 engine rules
depend on parse order (references resolve at parse time, in file order).
Unparseable regions are skipped with a note instead of aborting, so one
broken line never hides findings in the rest of the file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Union

OPERATORS = ("?=", "<=", ">=", "!=", "=", "<", ">")

UTF8_BOM = b"\xef\xbb\xbf"


@dataclass
class Token:
    kind: str  # IDENT | STRING | OP | LBRACE | RBRACE
    text: str
    line: int
    col: int


@dataclass
class KeyValue:
    key: str
    op: str
    value: Union[str, "Block"]
    line: int  # line of the key
    quoted: bool = False  # value was a quoted string

    @property
    def is_block(self) -> bool:
        return isinstance(self.value, Block)


@dataclass
class BareValue:
    value: Union[str, "Block"]
    line: int
    quoted: bool = False


Item = Union[KeyValue, BareValue]


@dataclass
class Block:
    items: list[Item] = field(default_factory=list)
    line: int = 0

    def key_values(self) -> Iterator[KeyValue]:
        for item in self.items:
            if isinstance(item, KeyValue):
                yield item

    def find(self, key: str) -> KeyValue | None:
        for kv in self.key_values():
            if kv.key == key:
                return kv
        return None

    def find_all(self, key: str) -> list[KeyValue]:
        return [kv for kv in self.key_values() if kv.key == key]

    def scalar(self, key: str) -> str | None:
        kv = self.find(key)
        if kv is not None and isinstance(kv.value, str):
            return kv.value
        return None


@dataclass
class ParsedFile:
    path: Path
    root: Block
    has_bom: bool
    encoding: str
    parse_notes: list[str] = field(default_factory=list)
    # line numbers (1-based) that carry an inline suppression comment,
    # mapped to the set of rule ids suppressed there (empty set = all rules)
    suppressions: dict[int, set[str]] = field(default_factory=dict)
    suppress_file: bool = False


def _tokenize(text: str, notes: list[str],
              suppressions: dict[int, set[str]]) -> list[Token]:
    tokens: list[Token] = []
    line = 1
    col = 1
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
            col = 1
            i += 1
            continue
        if ch in " \t\r":
            i += 1
            col += 1
            continue
        if ch == "#":
            end = text.find("\n", i)
            if end == -1:
                end = n
            comment = text[i:end]
            _record_suppression(comment, line, suppressions)
            col += end - i
            i = end
            continue
        if ch == '"':
            end = text.find('"', i + 1)
            if end == -1:
                notes.append(f"line {line}: unterminated string")
                end = n - 1
            raw = text[i + 1:end]
            tokens.append(Token("STRING", raw, line, col))
            newlines = raw.count("\n")
            if newlines:
                line += newlines
                col = 1
            col += end - i + 1
            i = end + 1
            continue
        if ch == "{":
            tokens.append(Token("LBRACE", "{", line, col))
            i += 1
            col += 1
            continue
        if ch == "}":
            tokens.append(Token("RBRACE", "}", line, col))
            i += 1
            col += 1
            continue
        matched_op = None
        for op in OPERATORS:
            if text.startswith(op, i):
                matched_op = op
                break
        if matched_op is not None:
            tokens.append(Token("OP", matched_op, line, col))
            i += len(matched_op)
            col += len(matched_op)
            continue
        # identifier: run until whitespace, brace, comment or operator start
        start = i
        while i < n:
            c = text[i]
            if c in ' \t\r\n#{}"':
                break
            if any(text.startswith(op, i) for op in OPERATORS):
                break
            i += 1
        ident = text[start:i]
        tokens.append(Token("IDENT", ident, line, col))
        col += i - start
    return tokens


def _record_suppression(comment: str, line: int,
                        suppressions: dict[int, set[str]]) -> None:
    marker = "eu5lint:ignore"
    idx = comment.find(marker)
    if idx == -1:
        return
    rest = comment[idx + len(marker):].strip()
    rules = {part.strip() for part in rest.replace(",", " ").split() if part.strip()}
    suppressions[line] = rules


class _Parser:
    def __init__(self, tokens: list[Token], notes: list[str]):
        self.tokens = tokens
        self.pos = 0
        self.notes = notes

    def peek(self, offset: int = 0) -> Token | None:
        idx = self.pos + offset
        if idx < len(self.tokens):
            return self.tokens[idx]
        return None

    def next(self) -> Token | None:
        tok = self.peek()
        if tok is not None:
            self.pos += 1
        return tok

    def parse_block(self, line: int, top_level: bool = False) -> Block:
        block = Block(line=line)
        while True:
            tok = self.peek()
            if tok is None:
                if not top_level:
                    self.notes.append(f"line {line}: unclosed block")
                return block
            if tok.kind == "RBRACE":
                if top_level:
                    self.notes.append(f"line {tok.line}: unexpected '}}'")
                    self.next()
                    continue
                self.next()
                return block
            if tok.kind == "LBRACE":
                self.next()
                inner = self.parse_block(tok.line)
                block.items.append(BareValue(inner, tok.line))
                continue
            if tok.kind in ("IDENT", "STRING"):
                nxt = self.peek(1)
                if nxt is not None and nxt.kind == "OP":
                    key_tok = self.next()
                    op_tok = self.next()
                    val_tok = self.peek()
                    if val_tok is None:
                        self.notes.append(
                            f"line {key_tok.line}: '{key_tok.text}' has no value")
                        return block
                    if val_tok.kind == "LBRACE":
                        self.next()
                        inner = self.parse_block(val_tok.line)
                        block.items.append(
                            KeyValue(key_tok.text, op_tok.text, inner,
                                     key_tok.line))
                    elif val_tok.kind in ("IDENT", "STRING"):
                        self.next()
                        block.items.append(
                            KeyValue(key_tok.text, op_tok.text, val_tok.text,
                                     key_tok.line,
                                     quoted=val_tok.kind == "STRING"))
                    else:
                        self.notes.append(
                            f"line {val_tok.line}: unexpected token "
                            f"'{val_tok.text}' after '{key_tok.text} {op_tok.text}'")
                        self.next()
                    continue
                self.next()
                block.items.append(
                    BareValue(tok.text, tok.line, quoted=tok.kind == "STRING"))
                continue
            if tok.kind == "OP":
                self.notes.append(
                    f"line {tok.line}: stray operator '{tok.text}'")
                self.next()
                continue
            self.next()


def read_script_bytes(raw: bytes, path: Path) -> ParsedFile:
    has_bom = raw.startswith(UTF8_BOM)
    encoding = "utf-8-sig"
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
        encoding = "cp1252"
    notes: list[str] = []
    suppressions: dict[int, set[str]] = {}
    tokens = _tokenize(text, notes, suppressions)
    parser = _Parser(tokens, notes)
    root = parser.parse_block(line=1, top_level=True)
    suppress_file = any(
        line <= 3 and _has_ignore_file(text, line)
        for line in suppressions)
    return ParsedFile(path=path, root=root, has_bom=has_bom,
                      encoding=encoding, parse_notes=notes,
                      suppressions=suppressions,
                      suppress_file=suppress_file)


def _has_ignore_file(text: str, line: int) -> bool:
    lines = text.splitlines()
    if line - 1 < len(lines):
        return "eu5lint:ignore-file" in lines[line - 1]
    return False


def parse_script_file(path: Path) -> ParsedFile:
    return read_script_bytes(path.read_bytes(), path)


def ref_values(kv: KeyValue) -> list[tuple[str, int]]:
    """Values of a reference field as (name, line) pairs.

    Handles both `requires = x` and `requires = { x y }`.
    """
    if isinstance(kv.value, str):
        return [(kv.value, kv.line)]
    refs: list[tuple[str, int]] = []
    for item in kv.value.items:
        if isinstance(item, BareValue) and isinstance(item.value, str):
            refs.append((item.value, item.line))
    return refs
