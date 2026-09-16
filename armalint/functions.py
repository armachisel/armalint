"""Unknown function/command detection for Armalint (W201).

Only ``call``/``spawn`` named references are checked. Direct command-call
detection (e.g. ``hint "x"`` where ``hint`` is not preceded by ``call`` or
``spawn``) is intentionally out of scope for this module; see the module
docstring note below.
"""

from __future__ import annotations

from .diagnostic import Diagnostic, Severity
from .known import SCRIPT_EXTENSIONS, is_known
from .symbols import SymbolIndex
from .tokenizer import Token, tokenize

_CODE = "W201"

# Token types that are transparent to reference detection.
_TRIVIA = frozenset(("comment", "preprocessor"))


def _is_known(name: str, index: SymbolIndex | None) -> bool:
    """True if ``name`` is a known command/function (case-insensitive).

    A name is known if :func:`armalint.known.is_known` accepts it, or if a
    ``SymbolIndex`` is provided and it recognizes the name as a mission-defined
    function (by full name or by tag).
    """
    if is_known(name):
        return True
    return index is not None and index.is_known_function(name)


def _next_significant(tokens: list[Token], index: int) -> int:
    """Index of the first non-trivia token after ``index`` (or ``len(tokens)``)."""
    j = index + 1
    while j < len(tokens) and tokens[j].type in _TRIVIA:
        j += 1
    return j


def check_functions(tokens: list[Token], index: SymbolIndex | None = None) -> list[Diagnostic]:
    """Return W201 warnings for unknown function/command names after ``call``/``spawn``.

    For each ``call`` or ``spawn`` keyword, the next significant token names the
    target:
      - ``lbrace`` -> anonymous code block, skipped.
      - ``lparen`` -> parenthesized expression, skipped.
      - ``local`` -> a local variable holding code (``call _fnc`` means "call the
        code in this variable"), skipped — never a resolvable function name.
      - ``ident`` -> function/command name; unknown => W201.
      - ``string`` -> treated as a function name unless its value ends in a
        script-path extension (``.sqf``/``.sqs``/``.ext``), in which case it is
        skipped as a script path.

    Only ``call``/``spawn`` named references are checked here. Direct command
    calls (e.g. ``hint "x"``) are not analyzed.
    """
    diags: list[Diagnostic] = []
    n = len(tokens)

    for i in range(n):
        tok = tokens[i]
        if tok.type != "keyword":
            continue
        if tok.value.lower() not in ("call", "spawn"):
            continue

        j = _next_significant(tokens, i)
        if j >= n:
            continue

        nxt = tokens[j]
        ttype = nxt.type

        if ttype in ("lbrace", "lparen"):
            continue

        if ttype == "local":
            # A local variable holding code; "call _fnc" invokes the code in
            # the variable, not a resolvable function name. Never a W201.
            continue

        if ttype == "ident":
            name = nxt.value
            if not _is_known(name, index):
                diags.append(
                    Diagnostic(
                        Severity.WARNING,
                        _CODE,
                        f"unknown function/command: {name}",
                        nxt.line,
                        nxt.column,
                    )
                )
            continue

        if ttype == "string":
            value = nxt.value
            if value.lower().endswith(SCRIPT_EXTENSIONS):
                continue  # script path, not a function name
            if not _is_known(value, index):
                diags.append(
                    Diagnostic(
                        Severity.WARNING,
                        _CODE,
                        f"unknown function/command: {value}",
                        nxt.line,
                        nxt.column,
                    )
                )
            continue

    return diags


def check_functions_text(source: str, index: SymbolIndex | None = None) -> list[Diagnostic]:
    """Tokenize ``source`` and run :func:`check_functions` over the result."""
    return check_functions(tokenize(source), index)


if __name__ == "__main__":
    assert check_functions_text("call BIS_fnc_param;") == []
    assert check_functions_text("call thisFunctionDoesNotExist;")[0].code == _CODE
    assert len(check_functions_text("call thisFunctionDoesNotExist;")) == 1
    assert check_functions_text('spawn { hint "x"; };') == []
    assert check_functions_text('call "BIS_fnc_param";') == []
    assert check_functions_text('call "script.sqf";') == []
    assert check_functions_text("call (someExpression);") == []
    # A local variable holding code is never a resolvable function name.
    assert check_functions_text("call _someLocal;") == []
    assert check_functions_text('_fnc = { hint "x"; }; call _fnc;') == []

    diags = check_functions_text("spawn doesNotExistEither;")
    assert len(diags) == 1 and diags[0].severity is Severity.WARNING, diags
    assert diags[0].code == _CODE
    assert diags[0].message == "unknown function/command: doesNotExistEither"

    # SymbolIndex integration: a registered tag suppresses W201 for matching
    # references, without affecting the no-index (backward-compatible) path.
    idx = SymbolIndex()
    idx.add_tag("ALT")
    assert check_functions_text("call ALT_fnc_formatScore;", idx) == []
    assert len(check_functions_text("call ALT_fnc_formatScore;")) == 1
    assert check_functions_text("call ZZZ_fnc_nope;", idx)[0].code == _CODE

    print("functions self-test passed")
