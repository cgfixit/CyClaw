#!/usr/bin/env python3
"""Reference tokenizer for one env/shell assignment line.

Normative rules live in ENVLINE_SPEC.md next to this file. Vectors live in
envline_vectors.tsv. Both are language-neutral: a shell loader can reimplement
the spec and check itself against the same table. This module is stdlib-only
on purpose so dotenv-guard stays install-free.

    python3 .claude/skills/dotenv-guard/envline.py --check-vectors
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

BOM = "\ufeff"

# Longer suffixes first so a reader comparing by eye sees API_KEY before KEY.
# is_secret_name accepts a name when the uppercased form ends in _<suffix>
# and has at least one character before that tail. KEY also matches
# AWS_ACCESS_KEY and, as a known cost, non-secrets such as PRINT_KEY.
SECRET_SUFFIXES = (
    "API_KEY",
    "CREDENTIALS",
    "PASSWORD",
    "SECRET",
    "TOKEN",
    "PAT",
    "DSN",
    "KEY",
)

_KEYWORDS = frozenset({"export", "declare", "typeset", "readonly", "local"})
_ASSIGN_WORD = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(\+?=)(.*)$", re.DOTALL)
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FLAG = re.compile(r"^[-+][A-Za-z]+$")
_LITERAL = re.compile(
    r"(?<![A-Za-z0-9_$])([A-Za-z][A-Za-z0-9_]*)\s*\+?\s*=",
    re.IGNORECASE,
)
_EVAL_CAT = re.compile(
    r"^\$\(\s*cat\s+([\s\S]+?)\s*\)$|^`\s*cat\s+([\s\S]+?)\s*`$|^\$\(\s*<\s*([\s\S]+?)\s*\)$"
)
_REDACT = re.compile(
    r"([A-Za-z][A-Za-z0-9_]*)(\s*\+?\s*=\s*)(\S+)",
    re.IGNORECASE,
)

VECTORS_NAME = "envline_vectors.tsv"
_VECTOR_COLUMNS = (
    "id",
    "line",
    "seq",
    "name",
    "op",
    "value",
    "classified",
    "source_kind",
    "source_operand",
)


@dataclass(frozen=True)
class Assignment:
    """One NAME= or NAME+= word. `value` is quote-removed and not expanded."""

    name: str
    op: str
    value: str


@dataclass(frozen=True)
class SourceLoad:
    """A `.` / `source` command, or `eval` of `cat` / `<`."""

    kind: str
    operand: str


def is_secret_name(name: str) -> bool:
    """True when `name` is secret-classified. Comparison is case-insensitive."""
    if not name or not ("A" <= name[0] <= "Z" or "a" <= name[0] <= "z"):
        return False
    for ch in name:
        if not (ch == "_" or "A" <= ch <= "Z" or "a" <= ch <= "z" or "0" <= ch <= "9"):
            return False
    upper = name.upper()
    for suffix in SECRET_SUFFIXES:
        tail = "_" + suffix
        if len(upper) > len(tail) and upper.endswith(tail):
            return True
    return False


def is_dotenv_filename(name: str) -> bool:
    """True for a basename that K2 treats as a dotenv file."""
    if name in {".env", ".envrc"}:
        return True
    if name.endswith(".env") or name.endswith(".env.example") or name.endswith(".envrc"):
        return True
    if name.startswith(".env.") or name.startswith(".env-"):
        return True
    return False


def literal_secret_names(text: str) -> list[str]:
    """Secret names written as NAME= or NAME+= anywhere in `text`.

    This is the writer/doc heuristic. It does not understand shell quoting,
    so a name inside `echo "NAME=..."` still counts. The assignment tokenizer
    below is the stricter shell reading.
    """
    found: list[str] = []
    for match in _LITERAL.finditer(text):
        name = match.group(1)
        if is_secret_name(name) and name not in found:
            found.append(name)
    return found


def redact_secret_assignments(text: str) -> str:
    """Replace values of secret NAME= / NAME+= tokens with `<redacted>`."""

    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        if not is_secret_name(name):
            return match.group(0)
        return f"{name}{match.group(2)}<redacted>"

    return _REDACT.sub(repl, text)


def assignments(line: str) -> list[Assignment]:
    """Every shell assignment on `line`, left to right."""
    found: list[Assignment] = []
    for segment in split_simple_commands(line):
        found.extend(_assignments_in_segment(segment))
    return found


def source_loads(line: str) -> list[SourceLoad]:
    """Dot, source, and eval-cat loads on `line`, left to right."""
    found: list[SourceLoad] = []
    for segment in split_simple_commands(line):
        found.extend(_sources_in_segment(segment))
    return found


def split_simple_commands(line: str) -> list[str]:
    """Split on unquoted `;`, `&`, `|`, `&&`, and `||`.

    A `#` that is not inside quotes ends the line: separators after it are
    part of the comment and are not splits. `$(...)` and backticks are opaque.
    """
    line = _strip_bom(line).rstrip("\r")
    parts: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(line)
    in_single = False
    in_double = False
    paren = 0
    tick = False
    while i < n:
        c = line[i]
        if in_single:
            buf.append(c)
            if c == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            buf.append(c)
            if c == "\\" and i + 1 < n:
                buf.append(line[i + 1])
                i += 2
                continue
            if c == '"':
                in_double = False
            i += 1
            continue
        if tick:
            buf.append(c)
            if c == "`":
                tick = False
            i += 1
            continue
        if paren:
            buf.append(c)
            if c == "\\" and i + 1 < n:
                buf.append(line[i + 1])
                i += 2
                continue
            if c == "'":
                in_single = True
                i += 1
                continue
            if c == '"':
                in_double = True
                i += 1
                continue
            if c == "`":
                tick = True
                i += 1
                continue
            if line.startswith("$(", i):
                paren += 1
                buf.append("(")
                i += 2
                continue
            if c == "(":
                paren += 1
            elif c == ")":
                paren -= 1
            i += 1
            continue
        if c == "\\":
            buf.append(c)
            if i + 1 < n:
                buf.append(line[i + 1])
                i += 2
            else:
                i += 1
            continue
        if c == "'":
            in_single = True
            buf.append(c)
            i += 1
            continue
        if c == '"':
            in_double = True
            buf.append(c)
            i += 1
            continue
        if c == "`":
            tick = True
            buf.append(c)
            i += 1
            continue
        if line.startswith("$(", i):
            paren = 1
            buf.append("$(")
            i += 2
            continue
        if c == "#":
            break
        two = line[i : i + 2]
        if two in {"&&", "||"}:
            parts.append("".join(buf))
            buf = []
            i += 2
            continue
        if c in ";|&":
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    parts.append("".join(buf))
    return parts


def _strip_bom(text: str) -> str:
    if text.startswith(BOM):
        return text[len(BOM) :]
    return text


def _read_balanced_paren(text: str, i: int) -> int:
    """`i` points at `(`. Return the index just after the matching `)`."""
    depth = 1
    i += 1
    n = len(text)
    in_single = False
    in_double = False
    while i < n and depth:
        c = text[i]
        if in_single:
            if c == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == '"':
                in_double = False
            i += 1
            continue
        if c == "\\":
            i += 2 if i + 1 < n else 1
            continue
        if c == "'":
            in_single = True
            i += 1
            continue
        if c == '"':
            in_double = True
            i += 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        i += 1
    return i


def _read_backtick(text: str, i: int) -> int:
    """`i` points at the opening backtick. Return the index just after the closer."""
    i += 1
    n = len(text)
    while i < n:
        if text[i] == "\\" and i + 1 < n:
            i += 2
            continue
        if text[i] == "`":
            return i + 1
        i += 1
    return i


def _split_words(segment: str) -> list[tuple[str, str]]:
    """Split one simple command into (quote-removed, raw) words."""
    words: list[tuple[str, str]] = []
    i = 0
    n = len(segment)
    while i < n:
        while i < n and segment[i] in " \t":
            i += 1
        if i >= n or segment[i] == "#":
            break
        start = i
        decoded: list[str] = []
        in_single = False
        in_double = False
        while i < n:
            c = segment[i]
            if in_single:
                if c == "'":
                    in_single = False
                else:
                    decoded.append(c)
                i += 1
                continue
            if in_double:
                if c == "\\" and i + 1 < n and segment[i + 1] in "$`\"\\\n":
                    decoded.append(segment[i + 1])
                    i += 2
                    continue
                if c == '"':
                    in_double = False
                    i += 1
                    continue
                if segment.startswith("$(", i):
                    j = _read_balanced_paren(segment, i + 1)
                    decoded.append(segment[i:j])
                    i = j
                    continue
                if c == "`":
                    j = _read_backtick(segment, i)
                    decoded.append(segment[i:j])
                    i = j
                    continue
                decoded.append(c)
                i += 1
                continue
            if c in " \t":
                break
            if c == "\\":
                if i + 1 < n:
                    decoded.append(segment[i + 1])
                    i += 2
                else:
                    i += 1
                continue
            if c == "'":
                in_single = True
                i += 1
                continue
            if c == '"':
                in_double = True
                i += 1
                continue
            if segment.startswith("$(", i):
                j = _read_balanced_paren(segment, i + 1)
                decoded.append(segment[i:j])
                i = j
                continue
            if c == "`":
                j = _read_backtick(segment, i)
                decoded.append(segment[i:j])
                i = j
                continue
            decoded.append(c)
            i += 1
        words.append(("".join(decoded), segment[start:i]))
    return words


def _assignments_in_segment(segment: str) -> list[Assignment]:
    words = _split_words(segment)
    if not words:
        return []
    idx = 0
    if words[0][0] in _KEYWORDS:
        idx = 1
        while idx < len(words):
            word = words[idx][0]
            if word == "--":
                idx += 1
                break
            if _FLAG.fullmatch(word):
                idx += 1
                continue
            break
    found: list[Assignment] = []
    while idx < len(words):
        decoded = words[idx][0]
        matched = _ASSIGN_WORD.fullmatch(decoded)
        if matched:
            found.append(Assignment(matched.group(1), matched.group(2), matched.group(3)))
            idx += 1
            continue
        spaced = _spaced_assignment(words, idx)
        if spaced is None:
            break
        item, idx = spaced
        found.append(item)
    return found


def _spaced_assignment(words: list[tuple[str, str]], idx: int) -> tuple[Assignment, int] | None:
    """Recognize `NAME = value` and `NAME += value` (whitespace the shell rejects)."""
    name = words[idx][0]
    if _IDENT.fullmatch(name) is None or idx + 1 >= len(words):
        return None
    nxt = words[idx + 1][0]
    if nxt == "=" or (nxt.startswith("=") and not nxt.startswith("==")):
        if nxt == "=":
            if idx + 2 < len(words):
                return Assignment(name, "=", words[idx + 2][0]), idx + 3
            return Assignment(name, "=", ""), idx + 2
        return Assignment(name, "=", nxt[1:]), idx + 2
    if nxt == "+=" or nxt.startswith("+="):
        if nxt == "+=":
            if idx + 2 < len(words):
                return Assignment(name, "+=", words[idx + 2][0]), idx + 3
            return Assignment(name, "+=", ""), idx + 2
        return Assignment(name, "+=", nxt[2:]), idx + 2
    if nxt == "+" and idx + 2 < len(words):
        third = words[idx + 2][0]
        if third == "=":
            if idx + 3 < len(words):
                return Assignment(name, "+=", words[idx + 3][0]), idx + 4
            return Assignment(name, "+=", ""), idx + 3
        if third.startswith("=") and not third.startswith("=="):
            return Assignment(name, "+=", third[1:]), idx + 3
    return None


def _strip_wrapping_quotes(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def _sources_in_segment(segment: str) -> list[SourceLoad]:
    words = _split_words(segment)
    if len(words) < 2:
        return []
    cmd = words[0][0]
    operand = words[1][0]
    if cmd == ".":
        return [SourceLoad("dot", operand)]
    if cmd == "source":
        return [SourceLoad("source", operand)]
    if cmd == "eval":
        matched = _EVAL_CAT.fullmatch(operand)
        if matched:
            inner = next(group for group in matched.groups() if group is not None)
            return [SourceLoad("eval_cat", _strip_wrapping_quotes(inner.strip()).strip())]
    return []


def unescape_field(text: str) -> str:
    """Undo TSV escapes: `\\\\`, `\\t`, `\\n`, `\\r`, `\\uFEFF`."""
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            if nxt == "\\":
                out.append("\\")
                i += 2
                continue
            if nxt == "t":
                out.append("\t")
                i += 2
                continue
            if nxt == "n":
                out.append("\n")
                i += 2
                continue
            if nxt == "r":
                out.append("\r")
                i += 2
                continue
            if text[i : i + 6].lower() == "\\ufeff":
                out.append(BOM)
                i += 6
                continue
        out.append(text[i])
        i += 1
    return "".join(out)


def load_vectors(path: Path) -> list[dict[str, str]]:
    """Read envline_vectors.tsv. Blank lines and `#` comments are skipped."""
    rows: list[dict[str, str]] = []
    header: list[str] | None = None
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        cols = raw.split("\t")
        if header is None:
            header = cols
            if tuple(header) != _VECTOR_COLUMNS:
                raise ValueError(f"{path}:{lineno}: header must be {','.join(_VECTOR_COLUMNS)}")
            continue
        if len(cols) != len(_VECTOR_COLUMNS):
            raise ValueError(f"{path}:{lineno}: want {len(_VECTOR_COLUMNS)} columns, got {len(cols)}")
        rows.append({key: unescape_field(value) for key, value in zip(header, cols, strict=True)})
    if header is None:
        raise ValueError(f"{path}: empty vectors file")
    return rows


def check_vectors(path: Path) -> list[str]:
    """Return human-readable mismatches. An empty list means the table holds."""
    errors: list[str] = []
    grouped: dict[str, list[dict[str, str]]] = {}
    order: list[str] = []
    for row in load_vectors(path):
        case_id = row["id"]
        if case_id not in grouped:
            grouped[case_id] = []
            order.append(case_id)
        grouped[case_id].append(row)
    for case_id in order:
        rows = grouped[case_id]
        line = rows[0]["line"]
        if any(row["line"] != line for row in rows):
            errors.append(f"{case_id}: rows disagree on the line text")
            continue
        expected_assignments = [row for row in rows if row["name"] != ""]
        expected_sources = [row for row in rows if row["source_kind"] != ""]
        got = assignments(line)
        if len(got) != len(expected_assignments):
            errors.append(
                f"{case_id}: expected {len(expected_assignments)} assignments, got {len(got)} ({got!r})"
            )
        for index, (row, item) in enumerate(zip(expected_assignments, got, strict=False)):
            if row["seq"] != str(index):
                errors.append(f"{case_id}: seq {row['seq']!r} is not {index}")
            if row["name"] != item.name or row["op"] != item.op or row["value"] != item.value:
                errors.append(
                    f"{case_id}[{index}]: expected {row['name']!r} {row['op']!r} {row['value']!r}, "
                    f"got {item.name!r} {item.op!r} {item.value!r}"
                )
            if (row["classified"] == "1") != is_secret_name(item.name):
                errors.append(
                    f"{case_id}[{index}]: classified flag {row['classified']!r} does not match {item.name}"
                )
        got_sources = source_loads(line)
        if len(got_sources) != len(expected_sources):
            errors.append(
                f"{case_id}: expected {len(expected_sources)} sources, got {len(got_sources)} ({got_sources!r})"
            )
        for row, loaded in zip(expected_sources, got_sources, strict=False):
            if row["source_kind"] != loaded.kind or row["source_operand"] != loaded.operand:
                errors.append(
                    f"{case_id}: expected source {row['source_kind']}:{row['source_operand']!r}, "
                    f"got {loaded.kind}:{loaded.operand!r}"
                )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check envline_vectors.tsv against this tokenizer.")
    parser.add_argument("--check-vectors", action="store_true")
    parser.add_argument("--vectors", type=Path, default=None)
    args = parser.parse_args(argv)
    path = args.vectors or Path(__file__).with_name(VECTORS_NAME)
    if not args.check_vectors:
        parser.print_help()
        return 2
    if not path.is_file():
        print(f"env error: vectors not found: {path}", file=sys.stderr)
        return 3
    try:
        errors = check_vectors(path)
    except (OSError, ValueError) as exc:
        print(f"env error: {exc}", file=sys.stderr)
        return 3
    if errors:
        print(f"{len(errors)} vector mismatch(es) in {path}")
        for err in errors:
            print(f"  {err}")
        return 2
    print(f"envline vectors: OK ({path.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
