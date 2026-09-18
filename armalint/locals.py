"""Conservative unused-local diagnostics (W209)."""

from __future__ import annotations

from .diagnostic import Diagnostic, Severity
from .tokenizer import Token, tokenize

_CODE = "W209"
_TRIVIA = frozenset(("comment", "preprocessor"))
_IGNORED = frozenset(("_x", "_this", "_thisargs"))


def _next(tokens: list[Token], index: int) -> int:
    index += 1
    while index < len(tokens) and tokens[index].type in _TRIVIA:
        index += 1
    return index


def check_unused_locals(tokens: list[Token]) -> list[Diagnostic]:
    """Report locals with no later reference in their lexical scope.

    The check deliberately gives up for files containing includes: an
    included fragment can declare or consume a local from its caller, and the
    standalone token stream cannot prove which relationship applies. Uses in
    nested scopes count as references to an outer declaration, which is
    conservative around closures and callbacks.
    """
    if any(
        token.type == "preprocessor"
        and token.value.lstrip().lower().lstrip("#").startswith("include")
        for token in tokens
    ):
        return []

    # Assign each token a brace-scope path. A descendant path is allowed to
    # reference a declaration in an enclosing scope.
    paths: list[tuple[int, ...]] = []
    stack: list[int] = []
    next_scope = 1
    for token in tokens:
        paths.append(tuple(stack))
        if token.type == "lbrace":
            stack.append(next_scope)
            next_scope += 1
        elif token.type == "rbrace" and stack:
            stack.pop()

    declarations: list[tuple[str, int, tuple[int, ...], Token]] = []
    for i, token in enumerate(tokens):
        if token.type != "keyword" or token.value.lower() not in ("private", "params"):
            continue
        j = _next(tokens, i)
        if j >= len(tokens):
            continue
        if tokens[j].type == "local":
            name = tokens[j].value.lower()
            if name not in _IGNORED:
                declarations.append((name, j, paths[j], tokens[j]))
            continue
        if tokens[j].type != "lbracket":
            continue
        depth = 0
        k = j
        while k < len(tokens):
            if tokens[k].type == "lbracket":
                depth += 1
            elif tokens[k].type == "rbracket":
                depth -= 1
                if depth == 0:
                    break
            elif depth == 1 and tokens[k].type == "string" and tokens[k].value.startswith("_"):
                name = tokens[k].value.lower()
                if name not in _IGNORED:
                    declarations.append((name, k, paths[k], tokens[k]))
            k += 1

    diagnostics: list[Diagnostic] = []
    for name, declaration_index, declaration_scope, declaration_token in declarations:
        used = False
        for index in range(declaration_index + 1, len(tokens)):
            token = tokens[index]
            if token.type != "local" or token.value.lower() != name:
                continue
            scope = paths[index]
            if len(scope) >= len(declaration_scope) and scope[:len(declaration_scope)] == declaration_scope:
                used = True
                break
        if not used:
            diagnostics.append(Diagnostic(
                Severity.WARNING,
                _CODE,
                f"unused local variable: {declaration_token.value}",
                declaration_token.line,
                declaration_token.column,
            ))
    return diagnostics


def check_unused_locals_text(source: str) -> list[Diagnostic]:
    return check_unused_locals(tokenize(source))


if __name__ == "__main__":
    assert [d.code for d in check_unused_locals_text("private _used = 1; hint str _used;")] == []
    assert [d.code for d in check_unused_locals_text("private _unused = 1;")] == [_CODE]
    assert [d.code for d in check_unused_locals_text("params [\"_used\"]; { hint str _used; };")] == []
    assert [d.code for d in check_unused_locals_text("#include \"shared.sqf\"\nprivate _maybeUsed;")] == []
    assert [d.code for d in check_unused_locals_text("{ private _inner; hint str _outer; }; private _outer;")] == [_CODE, _CODE]
    print("locals self-test passed")
