"""Embedded-SQF linting for class-based config files (``description.ext``/``.hpp``).

Config files are class-based: their *structure* (class names, property names,
hierarchy) must NOT be linted as SQF — doing so produced false W202 warnings.
But many property *values* are strings containing real SQF code (e.g.
``onButtonClick``, ``expression``, ``condition``, ``statement``). This module
finds those string-valued code fields and lints the SQF inside them, remapping
each diagnostic back to its position in the config file.
"""

from __future__ import annotations

import re

from .diagnostic import Diagnostic, Severity
from .linter import lint_text
from .symbols import SymbolIndex
from .tokenizer import tokenize

# Property names whose string value is always SQF code (matched case-insensitively).
CODE_FIELDS = frozenset(
    (
        "onload", "onunload", "ondestroy", "onchilddestroyed", "oncandestroy",
        "onbuttonclick", "onbuttondblclick", "onbuttondown", "onbuttonup",
        "onmousebuttondown", "onmousebuttonup", "onmousebuttonclick",
        "onmousebuttondblclick", "onmousezchanged", "onmousemoving",
        "onmouseholding", "onkeydown", "onkeyup", "onchar", "onimechar",
        "onsetfocus", "onkillfocus", "ontimer", "onlbselchanged", "onlbdblclick",
        "onlbdrag", "onlbdragging", "onlbdrop", "ontreeselchanged",
        "ontreedblclick", "ontreeexpanded", "ontreecollapsed",
        "ontreemousedown", "ontreemouseup", "ontreemousemove",
        "ontreemouseholding", "ontreemouseexit", "oncheckedchanged", "onchecked",
        "onsliderposchanged", "ontoolboxselchanged", "onvideostopped",
        "onhtmllink", "ondraw", "expression", "statement", "condition", "code",
    )
)

# Token types that are transparent when looking for ``ident = string``.
_TRIVIA = frozenset(("comment", "preprocessor"))

# An underscore followed by a word character (an SQF local-variable marker).
_LOCAL_MARKER = re.compile(r"_\w")


def _macro_lines(source: str) -> set[int]:
    """Return physical lines belonging to preprocessor macro definitions."""
    result: set[int] = set()
    continuation = False
    for line_number, line in enumerate(source.split("\n"), 1):
        stripped = line.lstrip()
        if continuation:
            result.add(line_number)
            continuation = line.rstrip().endswith("\\")
            continue
        if stripped.startswith("#define") and (len(stripped) == 7 or stripped[7].isspace()):
            result.add(line_number)
            continuation = line.rstrip().endswith("\\")
    return result


def check_config_structure(source: str, filename: str = "") -> list[Diagnostic]:
    """Check balanced config classes and duplicate properties in one class."""
    tokens = tokenize(source)
    diagnostics: list[Diagnostic] = []
    stack: list[tuple[Token, set[str]]] = []
    macro_lines = _macro_lines(source)
    # Keep the conditional branch context for each physical line.  Configs
    # commonly provide mutually exclusive alternatives such as one
    # ``maxPlayers`` value per map; those are not duplicate runtime
    # properties.  A context entry is ``(directive, branch)`` where branch
    # is True for the if-side and False for the else-side.
    conditional_context: dict[int, tuple[tuple[str, bool], ...]] = {}
    conditional_stack: list[tuple[str, bool]] = []
    for line_number, line in enumerate(source.split("\n"), 1):
        stripped = line.strip()
        conditional_context[line_number] = tuple(conditional_stack)
        match = re.match(r"#\s*(ifdef|ifndef|if)\s+(.+)$", stripped, re.IGNORECASE)
        if match:
            conditional_stack.append((match.group(2).strip().lower(), match.group(1).lower() != "ifndef"))
            continue
        if re.match(r"#\s*(else|elif)\b", stripped, re.IGNORECASE) and conditional_stack:
            name, branch = conditional_stack[-1]
            conditional_stack[-1] = (name, not branch)
            continue
        if re.match(r"#\s*endif\b", stripped, re.IGNORECASE) and conditional_stack:
            conditional_stack.pop()

    def conditional_alternative(first_line: int, second_line: int) -> bool:
        first = conditional_context.get(first_line, ())
        second = conditional_context.get(second_line, ())
        # Independent sibling ``#ifdef`` blocks are commonly used as a list
        # of mutually exclusive map/platform alternatives.  When both
        # declarations are conditional and their contexts differ, they do
        # not coexist in the intended configuration.
        if first and second and first != second:
            return True
        for name, branch in first:
            if (name, not branch) in second:
                return True
        return False

    previous_property_line: dict[int, dict[str, int]] = {}
    for i, token in enumerate(tokens):
        if token.line in macro_lines:
            continue
        if token.type == "lbrace":
            stack.append((token, set()))
        elif token.type == "rbrace":
            if not stack:
                diagnostics.append(Diagnostic(Severity.ERROR, "E010", "unmatched '}' in config", token.line, token.column, filename))
            else:
                stack.pop()
        elif token.type == "ident" and stack:
            j = _next_significant(tokens, i)
            if j < len(tokens) and tokens[j].type == "operator" and tokens[j].value == "=":
                key = token.value.lower()
                if key in stack[-1][1]:
                    # Find the earlier declaration in this class.  If the two
                    # declarations are in opposite preprocessor branches,
                    # only one exists in any concrete config and no duplicate
                    # property is present at runtime.
                    prior_line = None
                    for opening, props in reversed(stack):
                        prior_line = previous_property_line.get(id(props), {}).get(key)
                        if prior_line is not None:
                            break
                    if prior_line is None or not conditional_alternative(prior_line, token.line):
                        diagnostics.append(Diagnostic(Severity.WARNING, "W214", f"config property defined more than once: {token.value}", token.line, token.column, filename))
                stack[-1][1].add(key)
                previous_property_line.setdefault(id(stack[-1][1]), {})[key] = token.line
    for opening, _properties in stack:
        diagnostics.append(Diagnostic(Severity.ERROR, "E010", "unclosed '{' in config", opening.line, opening.column, filename))
    return diagnostics


def _next_significant(tokens, index: int) -> int:
    """Index of the first non-trivia token after ``index`` (or ``len(tokens)``)."""
    j = index + 1
    while j < len(tokens) and tokens[j].type in _TRIVIA:
        j += 1
    return j


def _looks_like_sqf(content: str) -> bool:
    """Heuristic: is ``content`` likely to be an SQF snippet?

    Requires a statement separator (``;``) plus at least one SQF marker: a
    local variable (``_`` followed by a word char), or one of the substrings
    ``call``/``spawn``/``{``/``(``. This is a fallback for code fields not
    enumerated in :data:`CODE_FIELDS`; it errs on the side of linting so
    embedded SQF is not silently skipped.
    """
    if ";" not in content:
        return False
    if _LOCAL_MARKER.search(content):
        return True
    if "call" in content or "spawn" in content:
        return True
    if "{" in content or "(" in content:
        return True
    return False


def lint_config(
    source: str, filename: str = "", index: SymbolIndex | None = None,
    function_signatures: dict[str, list[str | None]] | None = None,
    function_return_types: dict[str, str] | None = None,
    ignored_rules: set[str] | frozenset[str] | None = None,
    rule_severities: dict[str, str] | None = None,
    style: bool = False,
) -> list[Diagnostic]:
    """Lint the SQF embedded in string-valued code fields of ``source``.

    Only ``ident = string`` assignments are inspected: when the property name is
    a known code field (:data:`CODE_FIELDS`) or the string value looks like SQF
    (:func:`_looks_like_sqf`), the string content is linted with
    :func:`armalint.linter.lint_text` and each resulting diagnostic is remapped
    to the config file's coordinates. The config *structure* (class/property
    names) is never linted.
    """
    tokens = tokenize(source)
    n = len(tokens)
    diags: list[Diagnostic] = []
    diags.extend(check_config_structure(source, filename))

    for i, tok in enumerate(tokens):
        if tok.type != "ident":
            continue

        # Property name -> '=' -> string value (skipping comments/preprocessor).
        j = _next_significant(tokens, i)
        if j >= n or not (tokens[j].type == "operator" and tokens[j].value == "="):
            continue
        k = _next_significant(tokens, j)
        if k >= n or tokens[k].type != "string":
            continue

        name = tok.value.lower()
        content = tokens[k].value
        if name not in CODE_FIELDS and not _looks_like_sqf(content):
            continue

        string_tok = tokens[k]
        for d in lint_text(content, filename, index, function_signatures, function_return_types, ignored_rules, rule_severities, style):
            orig_line = d.line
            if orig_line == 1:
                # Same line as the opening quote: shift the column onto the
                # string token's starting column.
                d.column = string_tok.column + d.column
            # Multi-line strings: columns cannot be remapped exactly without the
            # string's internal layout, so keep the snippet column as-is.
            d.line = string_tok.line + (orig_line - 1)
            d.file = filename
            diags.append(d)

    return diags


if __name__ == "__main__":
    # A config snippet whose string code field contains an unknown function and
    # whose structural names must not be flagged as W202.
    src = (
        'class X { text = "Click me"; '
        "onButtonClick = \"hint 'clicked'; call thisFunctionDoesNotExist;\"; };"
    )
    diags = lint_config(src, "test.ext")
    w201 = [d for d in diags if d.code == "W201"]
    w202 = [d for d in diags if d.code == "W202"]
    assert len(w201) == 1, w201
    assert "thisFunctionDoesNotExist" in w201[0].message, w201[0].message
    assert not w202, w202

    # Column remapping: content "call foo;" lints `foo` at snippet line 1 col 6;
    # the string token starts at col 17 (the opening quote, after the 13-char
    # property name + " = "), so the remapped column is 17 + 6 = 23.
    remap = lint_config('onButtonClick = "call foo;";', "t.ext")
    r201 = [d for d in remap if d.code == "W201"]
    assert len(r201) == 1, r201
    assert (r201[0].line, r201[0].column) == (1, 23), (r201[0].line, r201[0].column)
    assert r201[0].file == "t.ext", r201[0].file
    assert any(d.code == "W214" for d in check_config_structure("class X { title = 1; title = 2; };", "t.ext"))
    assert any(d.code == "E010" for d in check_config_structure("class X {", "t.ext"))

    print("config_lint self-test passed")
