"""Checks for repeated or overwritten global SQF function definitions."""

from __future__ import annotations

from .diagnostic import Diagnostic, Severity
from .tokenizer import Token, tokenize

_DUPLICATE = "W207"
_OVERWRITE = "W208"
_TRIVIA = frozenset(("comment", "preprocessor"))
_COMPILE = frozenset(("compile", "compilefinal"))


def _next(tokens: list[Token], index: int) -> int:
    index += 1
    while index < len(tokens) and tokens[index].type in _TRIVIA:
        index += 1
    return index


def check_definitions(tokens: list[Token]) -> list[Diagnostic]:
    """Report repeated function definitions and later global overwrites."""
    functions: dict[str, Token] = {}
    diagnostics: list[Diagnostic] = []
    for i, token in enumerate(tokens):
        if token.type != "ident" or token.value.startswith("_"):
            continue
        equals = _next(tokens, i)
        if equals >= len(tokens) or tokens[equals].value != "=":
            continue
        value = _next(tokens, equals)
        if value >= len(tokens):
            continue
        name = token.value.lower()
        is_function = tokens[value].type == "lbrace" or tokens[value].value.lower() in _COMPILE
        if is_function:
            if name in functions:
                diagnostics.append(Diagnostic(Severity.WARNING, _DUPLICATE, f"duplicate function definition: {token.value}", token.line, token.column))
            else:
                functions[name] = token
        elif name in functions:
            diagnostics.append(Diagnostic(Severity.WARNING, _OVERWRITE, f"function overwritten by non-code value: {token.value}", token.line, token.column))
    return diagnostics


def check_definitions_text(source: str) -> list[Diagnostic]:
    return check_definitions(tokenize(source))


if __name__ == "__main__":
    assert check_definitions_text("TAG_fnc_a = {}; TAG_fnc_a = {}; ")[0].code == _DUPLICATE
    assert check_definitions_text("TAG_fnc_a = {}; TAG_fnc_a = 1;")[0].code == _OVERWRITE
    assert check_definitions_text("private _fn = {}; _value = 1;") == []
    print("definitions self-test passed")
