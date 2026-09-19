"""Opt-in source style checks."""

from __future__ import annotations

from .diagnostic import Diagnostic, Severity


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
