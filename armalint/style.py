"""Opt-in source style checks."""

from __future__ import annotations

from .diagnostic import Diagnostic, Severity
from .tokenizer import tokenize


def check_style(source: str) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for line_number, line in enumerate(source.splitlines(), 1):
        if line.endswith((" ", "\t")):
            diagnostics.append(Diagnostic(Severity.WARNING, "W301", "trailing whitespace", line_number, len(line.rstrip(" \t")) + 1))
        if "\t" in line:
            diagnostics.append(Diagnostic(Severity.WARNING, "W302", "tab character in source indentation", line_number, line.index("\t") + 1))
    return diagnostics


def fix_style(source: str) -> str:
    """Apply only formatting changes that are semantics-preserving in SQF."""
    # Trailing whitespace has no meaning. Convert indentation tabs to spaces;
    # tabs are only diagnosed as indentation/style issues, never as syntax.
    lines = source.splitlines(keepends=True)
    fixed: list[str] = []
    for line in lines:
        newline = ""
        body = line
        if body.endswith("\r\n"):
            body, newline = body[:-2], "\r\n"
        elif body.endswith("\n") or body.endswith("\r"):
            body, newline = body[:-1], body[-1]
        body = body.rstrip(" \t").replace("\t", "    ")
        fixed.append(body + newline)
    return "".join(fixed)


def safe_fix_edits(source: str) -> list[dict[str, object]]:
    """Return semantics-preserving edits for formatting and trailing commas."""
    edits: list[dict[str, object]] = []
    offsets = [0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    for line_no, line in enumerate(source.splitlines(keepends=True), 1):
        body = line.rstrip("\r\n")
        trailing_start = len(body.rstrip(" \t"))
        if trailing_start != len(body):
            start = offsets[line_no - 1] + trailing_start
            edits.append({"line": line_no, "column": trailing_start + 1, "start": start, "end": offsets[line_no - 1] + len(body), "replacement": "", "rule": "W301"})
        for column, character in enumerate(body, 1):
            if character == "\t":
                start = offsets[line_no - 1] + column - 1
                edits.append({"line": line_no, "column": column, "start": start, "end": start + 1, "replacement": "    ", "rule": "W302"})
    tokens = tokenize(source)
    significant = [token for token in tokens if token.type not in {"comment", "eof"}]
    for index, token in enumerate(significant[:-1]):
        if token.type != "comma" or significant[index + 1].type != "rbracket":
            continue
        start = offsets[token.line - 1] + token.column - 1
        edits.append({"line": token.line, "column": token.column, "start": start, "end": start + len(token.raw), "replacement": "", "rule": "E003"})
    edits.sort(key=lambda item: int(item["start"]))
    result: list[dict[str, object]] = []
    last_end = -1
    for edit in edits:
        if int(edit["start"]) >= last_end:
            result.append(edit)
            last_end = int(edit["end"])
    return result


def apply_safe_fix_edits(source: str, edits: list[dict[str, object]]) -> str:
    """Apply edits from :func:`safe_fix_edits` from right to left."""
    result = source
    for edit in reversed(edits):
        result = result[:int(edit["start"])] + str(edit["replacement"]) + result[int(edit["end"]):]
    return result
