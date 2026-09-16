"""Undefined script-local variable detection for Armalint (W101)."""

from __future__ import annotations

from .diagnostic import Diagnostic, Severity
from .tokenizer import Token, tokenize

_CODE = "W101"

# Script-local variables that are always defined by the SQF engine/context and
# therefore never flagged.
_ALWAYS_DEFINED = frozenset(
    (
        "_this", "_x", "_forEachIndex", "_index", "_exception",
        "_thisScript", "_fnc_scriptName",
        "_thisArgs", "_thisEventHandler", "_thisFSM", "_fnc_scriptNameParent",
    )
)

# Token types that are transparent to variable analysis.
_TRIVIA = frozenset(("comment", "preprocessor"))


def _next_significant(tokens: list[Token], index: int) -> int:
    """Index of the first non-trivia token after ``index`` (or ``len(tokens)``)."""
    j = index + 1
    while j < len(tokens) and tokens[j].type in _TRIVIA:
        j += 1
    return j


def _is_assignment_lhs(tokens: list[Token], index: int) -> bool:
    """True if the token at ``index`` is immediately followed by ``=``."""
    nxt = _next_significant(tokens, index)
    return (
        nxt < len(tokens)
        and tokens[nxt].type == "operator"
        and tokens[nxt].value == "="
    )


def _collect_string_names(
    tokens: list[Token], bracket_index: int, top_level_only: bool
) -> tuple[list[str], int]:
    """Collect string tokens starting with ``_`` inside the bracket group.

    Returns ``(names, next_index)`` where ``next_index`` is one past the closing
    bracket. When ``top_level_only`` is true, only direct elements of the
    bracket group are collected (nested arrays are skipped).
    """
    names: list[str] = []
    depth = 0
    k = bracket_index
    while k < len(tokens):
        ttype = tokens[k].type
        if ttype == "lbracket":
            depth += 1
        elif ttype == "rbracket":
            depth -= 1
            if depth <= 0:
                k += 1
                break
        elif ttype == "string" and tokens[k].value.startswith("_"):
            if not top_level_only or depth == 1:
                names.append(tokens[k].value)
        k += 1
    return names, k


def _collect_params_names(
    tokens: list[Token], bracket_index: int
) -> tuple[list[str], int]:
    """Collect locals defined by a ``params [...]`` expression.

    Top-level ``string`` tokens starting with ``_`` are collected directly. In
    addition, each nested ``[ ]`` array contributes its first significant token
    when that token is a ``string`` starting with ``_`` (the variable name of an
    optional parameter; the remaining elements are the default value and an
    optional trailing code array).

    Returns ``(names, next_index)`` where ``next_index`` is one past the closing
    bracket.
    """
    names: list[str] = []
    depth = 0
    k = bracket_index
    while k < len(tokens):
        ttype = tokens[k].type
        if ttype == "lbracket":
            depth += 1
            if depth == 2:
                # Nested array within the params list: its first significant
                # element names an optional parameter.
                m = _next_significant(tokens, k)
                if (
                    m < len(tokens)
                    and tokens[m].type == "string"
                    and tokens[m].value.startswith("_")
                ):
                    names.append(tokens[m].value)
        elif ttype == "rbracket":
            depth -= 1
            if depth <= 0:
                k += 1
                break
        elif ttype == "string" and tokens[k].value.startswith("_"):
            if depth == 1:
                names.append(tokens[k].value)
        k += 1
    return names, k


def check_undefined(tokens: list[Token]) -> list[Diagnostic]:
    """Return W101 warnings for script-local variables used before definition.

    A single flat ``defined`` set is used for the whole file (no nested block
    scoping) as a deliberate approximation.
    """
    defined: set[str] = set()
    diags: list[Diagnostic] = []
    n = len(tokens)
    i = 0

    while i < n:
        tok = tokens[i]
        ttype = tok.type

        if ttype in _TRIVIA:
            i += 1
            continue

        if ttype == "keyword":
            kw = tok.value.lower()

            if kw == "private":
                j = _next_significant(tokens, i)
                if j < n and tokens[j].type == "lbracket":
                    # private ["_a", "_b"]; — strings inside the brackets.
                    names, i = _collect_string_names(tokens, j, top_level_only=False)
                    defined.update(names)
                    continue
                # private _a; / private _a = ...; — local(s) before ';' or '='.
                k = j
                while k < n and tokens[k].type == "local":
                    defined.add(tokens[k].value)
                    k += 1
                i = k
                continue

            if kw == "params":
                j = _next_significant(tokens, i)
                if j < n and tokens[j].type == "lbracket":
                    # params ["_a", ["_b", 2], ["_c", false]]; — top-level
                    # strings plus the first element of each nested array.
                    names, i = _collect_params_names(tokens, j)
                    defined.update(names)
                    continue
                i += 1
                continue

            if kw == "for":
                # for "_i" from ... — first string after 'for' defines the local.
                j = _next_significant(tokens, i)
                if j < n and tokens[j].type == "string" and tokens[j].value.startswith("_"):
                    defined.add(tokens[j].value)
                i += 1
                continue

            i += 1
            continue

        if ttype == "local":
            if _is_assignment_lhs(tokens, i):
                defined.add(tok.value)
            elif tok.value not in _ALWAYS_DEFINED and tok.value not in defined:
                diags.append(
                    Diagnostic(
                        Severity.WARNING,
                        _CODE,
                        f"possible undefined variable: {tok.value}",
                        tok.line,
                        tok.column,
                    )
                )
            i += 1
            continue

        i += 1

    return diags


def check_undefined_text(source: str) -> list[Diagnostic]:
    """Tokenize ``source`` and run ``check_undefined`` over the result."""
    return check_undefined(tokenize(source))


if __name__ == "__main__":
    assert check_undefined_text("_x = 1; hint str _x;") == []

    diags = check_undefined_text("hint str _y;")
    assert len(diags) == 1, diags
    assert diags[0].severity is Severity.WARNING and diags[0].code == _CODE
    assert diags[0].message == "possible undefined variable: _y"
    assert (diags[0].line, diags[0].column) == (1, 10)

    assert check_undefined_text("private _a; hint str _a;") == []
    assert check_undefined_text("hint str _this;") == []

    # Arma 3 event-handler magic variables are always defined.
    assert check_undefined_text("hint str _thisArgs; hint str _thisEventHandler;") == []
    assert check_undefined_text("hint str _thisFSM; hint str _fnc_scriptNameParent;") == []

    # Additional rule coverage.
    assert check_undefined_text('private ["_a", "_b"]; hint str _a; hint str _b;') == []
    assert check_undefined_text('params ["_a", ["_b", 2]]; hint str _a;') == []
    assert check_undefined_text('for "_i" from 0 to 1 do { hint str _i; };') == []
    assert check_undefined_text("_x = _x + 1;") == []

    diags = check_undefined_text("hint str _z; _z = 5;")
    assert len(diags) == 1 and diags[0].message == "possible undefined variable: _z", diags

    # Nested params defaults define their first-element local.
    assert check_undefined_text('params ["_a", ["_b", 0]]; hint str _b;') == []
    assert check_undefined_text('params [["_a", 1], "_b", ["_c", false]]; hint str _a; hint str _c;') == []

    diags = check_undefined_text('params ["_a", ["_b", 0]]; hint str _missing;')
    assert len(diags) == 1, diags
    assert diags[0].message == "possible undefined variable: _missing", diags

    print("undefined self-test passed")
