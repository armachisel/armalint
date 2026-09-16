"""Rule suppression from configuration and inline source comments."""

from __future__ import annotations

import re

from .diagnostic import Diagnostic

_DIRECTIVE = re.compile(
    r"//\s*armalint:\s*(disable-next-line|disable-line|disable|enable)\b(.*)$",
    re.IGNORECASE,
)
_RULE = re.compile(r"\b(?:E|W)\d{3}\b", re.IGNORECASE)


def _codes(raw: str) -> set[str]:
    return {value.upper() for value in _RULE.findall(raw)}


def filter_suppressed(
    diagnostics: list[Diagnostic], source: str,
    ignored_rules: set[str] | frozenset[str] | None = None,
) -> list[Diagnostic]:
    """Filter configured and inline-suppressed diagnostics."""
    disabled = {value.upper() for value in (ignored_rules or ())}
    next_line: dict[int, set[str]] = {}
    line_rules: dict[int, set[str]] = {}
    active_by_line: dict[int, set[str]] = {}
    for line_no, line in enumerate(source.splitlines(), 1):
        match = _DIRECTIVE.search(line)
        if match:
            action, raw = match.groups()
            codes = _codes(raw)
            action = action.lower()
            if action == "disable-next-line":
                next_line[line_no + 1] = codes or {"*"}
            elif action == "disable-line":
                line_rules[line_no] = codes or {"*"}
            elif action == "disable":
                disabled.update(codes or {"*"})
            elif codes:
                disabled.difference_update(codes)
            else:
                disabled.clear()
        active_by_line[line_no] = set(disabled)

    result: list[Diagnostic] = []
    for diagnostic in diagnostics:
        code = diagnostic.code.upper()
        line_codes = next_line.get(diagnostic.line, set()) | line_rules.get(diagnostic.line, set())
        active = active_by_line.get(diagnostic.line, set())
        if "*" in active or code in active or "*" in line_codes or code in line_codes:
            continue
        result.append(diagnostic)
    return result


if __name__ == "__main__":
    from .diagnostic import Severity

    source = "// armalint: disable-next-line W206 W101\nif (true) then {};\n// armalint: disable-line W101 W201\nhint str _x;\n// armalint: disable W201 W206\ncall missing;\n// armalint: enable W201 W206\ncall other;"
    diagnostics = [
        Diagnostic(Severity.WARNING, "W206", "constant", 2, 1),
        Diagnostic(Severity.WARNING, "W101", "next-line", 2, 1),
        Diagnostic(Severity.WARNING, "W101", "undefined", 3, 1),
        Diagnostic(Severity.WARNING, "W201", "same-line", 3, 1),
        Diagnostic(Severity.WARNING, "W201", "missing", 6, 1),
        Diagnostic(Severity.WARNING, "W201", "other", 8, 1),
    ]
    assert [item.message for item in filter_suppressed(diagnostics, source)] == ["other"]
    assert filter_suppressed(diagnostics, source, {"W201"})[-1].message == "other"
    print("suppression self-test passed")
