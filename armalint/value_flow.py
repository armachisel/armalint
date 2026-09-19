"""Conservative value-flow diagnostics for local SQF variables."""

from __future__ import annotations

from .diagnostic import Diagnostic, Severity
from .tokenizer import Token, tokenize

_OVERWRITE = "W222"
_CONSTANT = "W223"
_EMPTY = "W224"
_TRIVIA = frozenset(("comment", "preprocessor"))


def check_value_flow(tokens: list[Token]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    assigned: dict[str, Token] = {}
    read_since: set[str] = set()
    literal_assignments: dict[str, tuple[str, Token]] = {}
    for i, token in enumerate(tokens):
        if token.type == "local":
            j = i + 1
            while j < len(tokens) and tokens[j].type in _TRIVIA:
                j += 1
            if j < len(tokens) and tokens[j].value == "=":
                name = token.value.lower()
                if name in assigned and name not in read_since:
                    diagnostics.append(Diagnostic(Severity.WARNING, _OVERWRITE, f"value assigned to {token.value} is overwritten before it is read", token.line, token.column))
                assigned[name] = token
                read_since.discard(name)
                rhs = j + 1
                while rhs < len(tokens) and tokens[rhs].type in _TRIVIA:
                    rhs += 1
                if rhs < len(tokens) and tokens[rhs].type in ("number", "string"):
                    value = tokens[rhs].value
                    previous = literal_assignments.get(name)
                    if previous and previous[0] == value:
                        diagnostics.append(Diagnostic(Severity.WARNING, _CONSTANT, f"repeated constant assignment to {token.value}", token.line, token.column))
                    literal_assignments[name] = (value, token)
                continue
            if token.value.lower() in assigned:
                read_since.add(token.value.lower())
        if token.type == "lbrace":
            j = i + 1
            while j < len(tokens) and tokens[j].type in _TRIVIA:
                j += 1
            if j < len(tokens) and tokens[j].type == "rbrace":
                diagnostics.append(Diagnostic(Severity.WARNING, _EMPTY, "empty code block has no effect", token.line, token.column))
        if token.type == "lbracket":
            j = i + 1
            while j < len(tokens) and tokens[j].type in _TRIVIA:
                j += 1
            if j < len(tokens) and tokens[j].type == "rbracket":
                k = j + 1
                while k < len(tokens) and tokens[k].type in _TRIVIA:
                    k += 1
                if k < len(tokens) and tokens[k].value.lower() == "select":
                    diagnostics.append(Diagnostic(Severity.WARNING, _EMPTY, "selecting from an empty array is ineffective", token.line, token.column))
    return diagnostics


def check_value_flow_text(source: str) -> list[Diagnostic]:
    return check_value_flow(tokenize(source))


if __name__ == "__main__":
    assert any(d.code == _OVERWRITE for d in check_value_flow_text('_x = 1; _x = 2; hint str _x;'))
    assert any(d.code == _CONSTANT for d in check_value_flow_text('_x = 1; _x = 1;'))
    assert any(d.code == _EMPTY for d in check_value_flow_text('{}; [] select 0;'))
    print("value_flow self-test passed")
