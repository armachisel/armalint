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

from .diagnostic import Diagnostic
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
        for d in lint_text(content, filename, index, function_signatures):
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

    print("config_lint self-test passed")
