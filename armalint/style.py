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
