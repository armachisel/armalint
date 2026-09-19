"""Unknown direct-command detection for Armalint (W202).

Complements the W201 checker (which only inspects ``call``/``spawn`` targets)
by flagging unknown *direct* command calls: an identifier immediately followed
by an operand, e.g. ``roadSurface _r``.
"""

from __future__ import annotations

from .diagnostic import Diagnostic, Severity
from .known import is_known
from .symbols import SymbolIndex
from .tokenizer import Token, tokenize

_CODE = "W202"

# Token types that are transparent to reference detection.
_TRIVIA = frozenset(("comment", "preprocessor"))

# Token types that can begin an operand (the right-hand side of a command call).
_OPERAND_START_TYPES = frozenset(
    ("local", "number", "string", "lparen", "lbracket", "lbrace")
)

# Keyword literals that can begin an operand.
_OPERAND_START_KEYWORDS = frozenset(("true", "false", "nil"))


def _next_significant(tokens: list[Token], index: int) -> int:
    """Index of the first non-trivia token after ``index`` (or ``len(tokens)``)."""
    j = index + 1
    while j < len(tokens) and tokens[j].type in _TRIVIA:
        j += 1
    return j


def _is_operand_start(token: Token) -> bool:
    """True if ``token`` can begin an operand (the RHS of a command call)."""
    if token.type in _OPERAND_START_TYPES:
        return True
    if token.type == "keyword" and token.value.lower() in _OPERAND_START_KEYWORDS:
        return True
    return False


def check_commands(
    tokens: list[Token], index: SymbolIndex | None = None
) -> list[Diagnostic]:
    """Return W202 warnings for unknown direct command names.

    An identifier is treated as a direct command call when the next significant
    token begins an operand. An identifier followed by another identifier is
    *not* flagged, because that pattern is a variable on the left of a binary
    command (e.g. ``myGlobalVar setPos [0,0,0]``).
    """
    diags: list[Diagnostic] = []
    n = len(tokens)

    for i in range(n):
        tok = tokens[i]
        if tok.type != "ident":
            continue

        name = tok.value.lower()
        if is_known(name) or (index is not None and index.is_known_macro(name)):
            continue
        if index is not None and index.is_known_function(name):
            continue

        j = _next_significant(tokens, i)
        if j >= n:
            continue

        if not _is_operand_start(tokens[j]):
            continue

        message = f"unknown command/function: {tok.value}"
        if tok.value.lower().startswith("cba_"):
            message += " (CBA dependency is not indexed; declare it and run update)" if index is None or not index.cba_declared else " (CBA is declared but not indexed; run update)"
        diags.append(
            Diagnostic(
                Severity.WARNING,
                _CODE,
                message,
                tok.line,
                tok.column,
            )
        )

    return diags


def check_commands_text(
    source: str, index: SymbolIndex | None = None
) -> list[Diagnostic]:
    """Tokenize ``source`` and run :func:`check_commands` over the result."""
    return check_commands(tokenize(source), index)


if __name__ == "__main__":
    diags = check_commands_text("diag_log roadSurface _r;")
    assert len(diags) == 1, diags
    assert diags[0].severity is Severity.WARNING, diags
    assert diags[0].code == _CODE, diags
    assert diags[0].message == "unknown command/function: roadSurface", diags

    assert check_commands_text("player setPos [0,0,0];") == []
    assert check_commands_text("_r = 1; hint str _r;") == []
    assert check_commands_text("myGlobalVar setPos [0,0,0];") == []
    assert check_commands_text("ceil (ALT_postSuccessRecordingEndsAt - diag_tickTime);") == []
    # CBA/addon preprocessor helpers can remain unresolved when their external
    # header is outside the project being linted.
    from .symbols import SymbolIndex
    cba_index = SymbolIndex(cba_declared=True)
    assert check_commands_text('QUOTE("x"); PATHTOF_SYS(PREFIX,COMPONENT,x);')
    assert check_commands_text('QUOTE("x"); PATHTOF_SYS(PREFIX,COMPONENT,x);', cba_index)
    assert check_commands_text('EFUNC(Events,triggerEvent);', cba_index)

    print("commands self-test passed")
