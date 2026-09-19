"""Rule suppression from configuration and inline source comments."""

from __future__ import annotations

import re

from .diagnostic import Diagnostic, Severity

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
    configured = {value.upper() for value in (ignored_rules or ())}
    disabled = set(configured)
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
        if code in configured or "*" in configured or "*" in active or code in active or "*" in line_codes or code in line_codes:
            continue
        result.append(diagnostic)
    return result


def apply_rule_severities(diagnostics: list[Diagnostic], severities: dict[str, str] | None = None) -> list[Diagnostic]:
    """Apply project rule severities before suppression and exit-status checks."""
    if not severities:
        return diagnostics
    result: list[Diagnostic] = []
    levels = {"error": Severity.ERROR, "warning": Severity.WARNING, "info": Severity.INFO}
    for diagnostic in diagnostics:
        level = severities.get(diagnostic.code.upper())
        if level == "off":
            continue
        if level in levels:
            diagnostic.severity = levels[level]
        result.append(diagnostic)
    return result


def check_suppression_quality(source: str, diagnostics: list[Diagnostic], require_justification: bool = False) -> list[Diagnostic]:
    """Report uncommented or unused inline suppressions when requested."""
    findings: list[Diagnostic] = []
    lines = source.splitlines()
    directives: list[tuple[int, str, set[str], str]] = []
    for line_no, line in enumerate(lines, 1):
        match = _DIRECTIVE.search(line)
        if not match:
            continue
        action, raw = match.groups()
        codes = _codes(raw)
        reason = re.sub(r"\b(?:E|W)\d{3}\b", "", raw, flags=re.IGNORECASE).strip(" -:;")
        directives.append((line_no, action.lower(), codes or {"*"}, reason))
        if require_justification and not reason:
            findings.append(Diagnostic(Severity.WARNING, "W229", "suppression requires a justification comment", line_no, 1))
    for index, (line_no, action, codes, _reason) in enumerate(directives):
        if action == "enable":
            continue
        if action == "disable-next-line":
            target_lines = {line_no + 1}
        elif action == "disable-line":
            target_lines = {line_no}
        else:
            end = len(lines) + 1
            for later_line, later_action, later_codes, _ in directives[index + 1:]:
                if later_action == "enable" and ("*" in later_codes or "*" in codes or codes & later_codes):
                    end = later_line
                    break
            target_lines = set(range(line_no + 1, end))
        used = any(d.line in target_lines and ("*" in codes or d.code.upper() in codes) for d in diagnostics)
        if not used:
            findings.append(Diagnostic(Severity.INFO, "W230", "suppression does not match any diagnostic", line_no, 1))
    return findings


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
    assert filter_suppressed(diagnostics, source, {"W201"}) == []
    severity_diagnostics = [
        Diagnostic(Severity.WARNING, "W206", "constant", 1, 1),
        Diagnostic(Severity.WARNING, "W101", "unused", 1, 1),
    ]
    adjusted = apply_rule_severities(severity_diagnostics, {"W206": "error", "W101": "off"})
    assert len(adjusted) == 1
    assert adjusted[0].severity is Severity.ERROR
    quality = check_suppression_quality("// armalint: disable-next-line W206\nif (true) then {};\n// armalint: disable-line W102 -- generated\nhint \"x\";\n", diagnostics, True)
    assert any(item.code == "W229" for item in quality)
    assert any(item.code == "W230" for item in quality)
    print("suppression self-test passed")
