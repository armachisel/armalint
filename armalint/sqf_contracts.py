"""Conservative checks for SQF APIs whose contracts are structural."""

from __future__ import annotations

from .diagnostic import Diagnostic, Severity
from .tokenizer import Token, tokenize

_PARAMS = "W217"
_NAMESPACE = "W218"
_EVENT = "W219"
_REMOTE = "W220"
_PUBLIC = "W221"
_TRIVIA = frozenset(("comment", "preprocessor"))
_NAMESPACES = frozenset((
    "missionnamespace", "profilenamespace", "parsingnamespace", "uinamespace",
    "servernamespace", "localnamespace", "missionprofilenamespace",
))


def _next(tokens: list[Token], index: int) -> int:
    index += 1
    while index < len(tokens) and tokens[index].type in _TRIVIA:
        index += 1
    return index


def _items(tokens: list[Token], opening: int) -> tuple[list[list[Token]], int] | None:
    if opening >= len(tokens) or tokens[opening].type != "lbracket":
        return None
    result: list[list[Token]] = []
    item_start = opening + 1
    depth = 0
    i = opening + 1
    while i < len(tokens):
        kind = tokens[i].type
        if kind in ("lbracket", "lparen", "lbrace"):
            depth += 1
        elif kind in ("rbracket", "rparen", "rbrace"):
            if depth == 0:
                if any(t.type not in _TRIVIA for t in tokens[item_start:i]):
                    result.append(tokens[item_start:i])
                return result, i
            depth -= 1
        elif kind == "comma" and depth == 0:
            result.append(tokens[item_start:i])
            item_start = i + 1
        i += 1
    return None


def _first(item: list[Token]) -> Token | None:
    return next((token for token in item if token.type not in _TRIVIA), None)


def _diag(code: str, message: str, token: Token) -> Diagnostic:
    return Diagnostic(Severity.WARNING, code, message, token.line, token.column)


def check_sqf_contracts(tokens: list[Token]) -> list[Diagnostic]:
    """Check params, namespaces, event handlers, remote execution and public variables."""
    diagnostics: list[Diagnostic] = []
    registrations: set[tuple[str, str, str]] = set()
    for i, token in enumerate(tokens):
        if token.type in _TRIVIA:
            continue
        name = token.value.lower()

        if name == "params":
            opening = _next(tokens, i)
            parsed = _items(tokens, opening) if opening < len(tokens) else None
            if parsed is None:
                diagnostics.append(_diag(_PARAMS, "params expects an array of parameter declarations", token))
                continue
            declarations, _ = parsed
            for declaration in declarations:
                first = _first(declaration)
                if first is None:
                    diagnostics.append(_diag(_PARAMS, "params contains an empty declaration", token))
                    continue
                if first.type == "string":
                    if not first.value.startswith("_"):
                        diagnostics.append(_diag(_PARAMS, "params names must be local variables", first))
                    continue
                if first.type != "lbracket":
                    diagnostics.append(_diag(_PARAMS, "params declarations must be variable names or [name, default] arrays", first))
                    continue
                nested = _items(declaration, declaration.index(first))
                if nested is None:
                    diagnostics.append(_diag(_PARAMS, "malformed params declaration", first))
                    continue
                fields, _ = nested
                name_token = _first(fields[0]) if fields else None
                if name_token is None or name_token.type != "string" or not name_token.value.startswith("_"):
                    diagnostics.append(_diag(_PARAMS, "params declaration must start with a local variable name", first))
                if len(fields) > 3:
                    diagnostics.append(_diag(_PARAMS, "params declaration has too many fields", first))
                if len(fields) == 3 and (_first(fields[2]) is None or _first(fields[2]).type != "lbracket"):
                    diagnostics.append(_diag(_PARAMS, "params validators must be an array", _first(fields[2]) or first))

        if name in ("getvariable", "setvariable") and i > 0:
            previous = i - 1
            while previous >= 0 and tokens[previous].type in _TRIVIA:
                previous -= 1
            if previous >= 0 and tokens[previous].value.lower() in _NAMESPACES:
                argument = _next(tokens, i)
                valid = argument < len(tokens) and tokens[argument].type in ("string", "lbracket")
                if not valid:
                    diagnostics.append(_diag(_NAMESPACE, f"{tokens[previous].value} {name} expects a name or [name, value] array", token))

        if name in ("addeventhandler", "addmissioneventhandler", "addmpeventhandler"):
            opening = _next(tokens, i)
            parsed = _items(tokens, opening) if opening < len(tokens) else None
            if parsed is None or len(parsed[0]) < 2:
                diagnostics.append(_diag(_EVENT, f"{token.value} expects an event name and handler", token))
                continue
            event = _first(parsed[0][0])
            handler = _first(parsed[0][1])
            if event is None or event.type != "string" or handler is None or handler.type not in ("lbrace", "string", "ident", "local"):
                diagnostics.append(_diag(_EVENT, f"{token.value} has an invalid event-handler declaration", token))
            target = tokens[i - 1].value.lower() if i else "<unknown>"
            registrations.add((target, event.value.lower() if event and event.type == "string" else "<unknown>", "*"))

        if name in ("removeeventhandler", "removemissioneventhandler", "removempeventhandler"):
            opening = _next(tokens, i)
            parsed = _items(tokens, opening) if opening < len(tokens) else None
            if parsed is None or len(parsed[0]) < 2:
                diagnostics.append(_diag(_EVENT, f"{token.value} expects an event name and handler id", token))
                continue
            event = _first(parsed[0][0])
            handler_id = _first(parsed[0][1])
            target = tokens[i - 1].value.lower() if i else "<unknown>"
            key = (target, event.value.lower() if event and event.type == "string" else "<unknown>", "*")
            if handler_id and handler_id.type == "number" and key not in registrations:
                diagnostics.append(_diag(_EVENT, f"{token.value} removes an event handler that was not registered in this file", token))

        if name in ("remoteexec", "remoteexeccall"):
            opening = _next(tokens, i)
            parsed = _items(tokens, opening) if opening < len(tokens) else None
            if parsed is None or len(parsed[0]) not in (2, 3):
                diagnostics.append(_diag(_REMOTE, f"{token.value} expects [function, targets, jip]", token))
            elif len(parsed[0]) == 3:
                jip = _first(parsed[0][2])
                if jip is not None and not (jip.type == "keyword" and jip.value.lower() in ("true", "false")):
                    diagnostics.append(_diag(_REMOTE, f"{token.value} JIP argument must be Boolean", jip))

        if name in ("publicvariable", "publicvariableserver", "publicvariableclient"):
            argument = _next(tokens, i)
            if argument >= len(tokens) or tokens[argument].type != "string":
                diagnostics.append(_diag(_PUBLIC, f"{token.value} expects the name of a public variable as a String", token))
    return diagnostics


def check_sqf_contracts_text(source: str) -> list[Diagnostic]:
    return check_sqf_contracts(tokenize(source))


if __name__ == "__main__":
    assert check_sqf_contracts_text('params ["_x", ["_y", 0, [0]]];') == []
    assert any(d.code == _PARAMS for d in check_sqf_contracts_text('params "_x";'))
    assert any(d.code == _NAMESPACE for d in check_sqf_contracts_text('missionNamespace setVariable 1;'))
    assert check_sqf_contracts_text('player addEventHandler ["Killed", { hint "x"; }]; player removeEventHandler ["Killed", 0];') == []
    assert any(d.code == _EVENT for d in check_sqf_contracts_text('player removeEventHandler ["Killed", 0];'))
    assert any(d.code == _REMOTE for d in check_sqf_contracts_text('[] remoteExec ["fn", 2, "yes"];'))
    assert any(d.code == _PUBLIC for d in check_sqf_contracts_text('publicVariable 42;'))
    print("sqf_contracts self-test passed")
