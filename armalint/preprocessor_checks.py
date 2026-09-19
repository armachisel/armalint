"""Diagnostics for malformed or unsupported SQF preprocessor directives."""

from __future__ import annotations

import re

from .diagnostic import Diagnostic, Severity

_DIRECTIVE = re.compile(r"^\s*#\s*([A-Za-z_][A-Za-z0-9_]*)\b(.*)$")
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_KNOWN = {"include", "define", "undef", "ifdef", "ifndef", "if", "elif", "else", "endif", "pragma"}


def check_preprocessor(source: str) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    defines: set[str] = set()
    conditionals: list[int] = []
    for line_number, line in enumerate(source.splitlines(), 1):
        match = _DIRECTIVE.match(line)
        if not match:
            continue
        directive, rest = match.group(1).lower(), match.group(2).strip()
        token_column = line.find("#") + 1
        if directive not in _KNOWN:
            diagnostics.append(Diagnostic(Severity.WARNING, "W228", f"unsupported preprocessor directive: #{directive}", line_number, token_column))
            continue
        if directive == "define":
            name = rest.split(None, 1)[0] if rest else ""
            function_match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\(([^)]*)\)", name)
            if function_match:
                name = function_match.group(1)
            if not _NAME.match(name):
                diagnostics.append(Diagnostic(Severity.WARNING, "W228", "malformed #define directive", line_number, token_column))
                continue
            if name.lower() in defines:
                diagnostics.append(Diagnostic(Severity.WARNING, "W225", f"macro redefined: {name}", line_number, token_column))
            defines.add(name.lower())
        elif directive == "undef":
            name = rest.split(None, 1)[0] if rest else ""
            if name.lower() not in defines:
                diagnostics.append(Diagnostic(Severity.WARNING, "W226", f"undefined macro in #undef: {name or '<missing>'}", line_number, token_column))
            defines.discard(name.lower())
        elif directive in ("ifdef", "ifndef"):
            name = rest.split(None, 1)[0] if rest else ""
            if not _NAME.match(name):
                diagnostics.append(Diagnostic(Severity.WARNING, "W228", f"malformed #{directive} directive", line_number, token_column))
            conditionals.append(line_number)
        elif directive == "if":
            expression = rest.replace(" ", "")
            if expression and not (expression in ("0", "1", "true", "false") or expression.startswith("defined(") or expression.startswith("!defined(")):
                diagnostics.append(Diagnostic(Severity.WARNING, "W226", f"macro or expression cannot be resolved in #if: {rest}", line_number, token_column))
            conditionals.append(line_number)
        elif directive == "elif":
            if not conditionals:
                diagnostics.append(Diagnostic(Severity.WARNING, "W227", "#elif without a matching conditional", line_number, token_column))
        elif directive == "else":
            if not conditionals:
                diagnostics.append(Diagnostic(Severity.WARNING, "W227", "#else without a matching conditional", line_number, token_column))
        elif directive == "endif":
            if not conditionals:
                diagnostics.append(Diagnostic(Severity.WARNING, "W227", "#endif without a matching conditional", line_number, token_column))
            else:
                conditionals.pop()
        elif directive == "pragma" and rest.lower() != "once":
            diagnostics.append(Diagnostic(Severity.WARNING, "W228", f"unsupported #pragma: {rest}", line_number, token_column))
    for opening in conditionals:
        diagnostics.append(Diagnostic(Severity.WARNING, "W227", "conditional directive is not closed with #endif", opening, 1))
    return diagnostics


if __name__ == "__main__":
    source = "#define X 1\n#define X 2\n#if UNKNOWN\n#endif\n#endif\n#pragma bad\n"
    codes = {d.code for d in check_preprocessor(source)}
    assert {"W225", "W226", "W227", "W228"} <= codes
    print("preprocessor_checks self-test passed")
