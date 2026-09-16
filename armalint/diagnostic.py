"""Diagnostic primitives for Armalint."""

from __future__ import annotations

import enum
from dataclasses import dataclass


class Severity(enum.Enum):
    """Severity of a diagnostic, with string values."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Diagnostic:
    """A single lint finding: severity, machine code, message, 1-based position."""

    severity: Severity
    code: str
    message: str
    line: int
    column: int
    file: str = ""


def format_diagnostic(d: Diagnostic) -> str:
    """Render a diagnostic as a single human-readable line."""
    if d.file:
        return f"{d.file}:{d.line}:{d.column}: {d.severity.value} [{d.code}]: {d.message}"
    return f"line {d.line}, col {d.column}: {d.severity.value} [{d.code}]: {d.message}"
