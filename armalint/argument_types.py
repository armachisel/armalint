"""Static type inference and built-in SQF command argument checks.

Only expressions whose type is unambiguous are checked. The command signature
table is intentionally declarative so coverage can grow without changing the
checker; unknown expressions and mission functions remain unchecked.
"""

from __future__ import annotations

from .diagnostic import Diagnostic, Severity
from .tokenizer import Token, tokenize

_CODE = "W203"
_TRIVIA = frozenset(("comment", "preprocessor"))

# (accepted inferred types, user-facing type label). This initial set covers
# common unary built-ins with stable input types; see the module docstring.
_SIGNATURES: dict[str, tuple[frozenset[str], str]] = {
    "sleep": (frozenset(("Number",)), "Number"),
    "uisleep": (frozenset(("Number",)), "Number"),
    "hint": (frozenset(("String", "Array", "Structured Text")), "String or Structured Text"),
    "hintsilent": (frozenset(("String", "Array", "Structured Text")), "String or Structured Text"),
    "systemchat": (frozenset(("String",)), "String"),
    "parsenumber": (frozenset(("String",)), "String"),
    "toarray": (frozenset(("String",)), "String"),
    "tolower": (frozenset(("String",)), "String"),
    "toupper": (frozenset(("String",)), "String"),
    "abs": (frozenset(("Number",)), "Number"),
    "ceil": (frozenset(("Number",)), "Number"),
    "floor": (frozenset(("Number",)), "Number"),
    "round": (frozenset(("Number",)), "Number"),
    "sqrt": (frozenset(("Number",)), "Number"),
    "sin": (frozenset(("Number",)), "Number"),
    "cos": (frozenset(("Number",)), "Number"),
    "tan": (frozenset(("Number",)), "Number"),
    "asin": (frozenset(("Number",)), "Number"),
    "acos": (frozenset(("Number",)), "Number"),
    "atan": (frozenset(("Number",)), "Number"),
    "selectrandom": (frozenset(("Array",)), "Array"),
    "count": (frozenset(("String", "Array")), "String, Array, Config or HashMap"),
}

_RETURN_TYPES = {
    "str": "String", "format": "String", "parsetext": "Structured Text",
    "composetext": "Structured Text", "parsenumber": "Number",
    "toarray": "Array", "tolower": "String", "toupper": "String",
    "count": "Number", "find": "Number", "abs": "Number", "ceil": "Number",
    "floor": "Number", "round": "Number", "sqrt": "Number",
    "sin": "Number", "cos": "Number", "tan": "Number",
    "asin": "Number", "acos": "Number", "atan": "Number",
    "selectrandom": None,
}

# Return types for common engine commands. These are used when a command is
# part of an assignment or a larger expression, rather than as a checked
# unary argument.
_COMMAND_RETURN_TYPES = {
    "getdir": "Number", "getnumber": "Number", "gettext": "String",
    "getpos": "Array", "getposasl": "Array", "getposatl": "Array",
    "velocity": "Array", "vectorup": "Array", "vectordir": "Array",
    "nearroads": "Array", "getroadinfo": "Array",
    "distance": "Number", "distance2d": "Number", "vectormagnitude": "Number",
    "random": "Number", "isnull": "Boolean", "isnil": "Boolean",
    "isclass": "Boolean", "isequaltype": "Boolean", "find": "Number",
}
_KNOWN_VARIABLE_TYPES = {
    "player": "Object", "objnull": "Object", "grpnull": "Group",
    "west": "Side", "east": "Side", "resistance": "Side", "civilian": "Side",
}


def _infer_operand(tokens: list[Token], i: int, variables: dict[str, str]) -> str | None:
    """Infer a simple operand type, including prior literal assignments."""
    if i >= len(tokens):
        return None
    tok = tokens[i]
    if tok.type == "operator" and tok.value == "!":
        return "Boolean"
    if tok.type == "number":
        return "Number"
    if tok.type == "string":
        return "String"
    if tok.type == "lbracket":
        return "Array"
    if tok.type == "lbrace":
        return "Code"
    if tok.type == "local":
        return variables.get(tok.value.lower())
    if tok.type == "keyword" and tok.value.lower() in ("true", "false"):
        return "Boolean"
    if tok.type in ("ident", "keyword"):
        return _RETURN_TYPES.get(tok.value.lower(), _KNOWN_VARIABLE_TYPES.get(tok.value.lower()))
    return None


def _infer_expression(
    tokens: list[Token], start: int, variables: dict[str, str],
    function_return_types: dict[str, str] | None = None,
) -> str | None:
    """Infer a few common composed expressions used in assignments."""
    if start < len(tokens) and tokens[start].type == "operator" and tokens[start].value in ("+", "-"):
        # Unary + preserves the operand type (commonly used to copy arrays);
        # unary - is numeric.
        return (_infer_operand(tokens, start + 1, variables)
                if tokens[start].value == "+" else "Number")
    if start < len(tokens) and tokens[start].value.lower() in _COMMAND_RETURN_TYPES:
        return _COMMAND_RETURN_TYPES[tokens[start].value.lower()]
    operand_end = start + 1
    while operand_end < len(tokens) and tokens[operand_end].type in _TRIVIA:
        operand_end += 1
    if operand_end < len(tokens) and tokens[operand_end].value.lower() in _COMMAND_RETURN_TYPES:
        return _COMMAND_RETURN_TYPES[tokens[operand_end].value.lower()]
    direct = _infer_operand(tokens, start, variables)
    if direct != "Array" or start >= len(tokens):
        return direct
    split = _array_items(tokens, start)
    if split is None:
        return direct
    _items, close = split
    j = close + 1
    while j < len(tokens) and tokens[j].type in _TRIVIA:
        j += 1
    if j < len(tokens) and tokens[j].value.lower() in _COMMAND_RETURN_TYPES:
        return _COMMAND_RETURN_TYPES[tokens[j].value.lower()]
    if j < len(tokens) and tokens[j].type == "keyword" and tokens[j].value.lower() in ("call", "spawn"):
        # An argument array is not the result of the function call. Without a
        # known return signature, leave the result unknown rather than calling
        # it an Array and producing a false W203 later.
        target = j + 1
        while target < len(tokens) and tokens[target].type in _TRIVIA:
            target += 1
        if target < len(tokens) and tokens[target].type == "ident":
            return (function_return_types or {}).get(tokens[target].value.lower())
        return None
    if j < len(tokens) and tokens[j].value.lower() == "select":
        j += 1
        if j < len(tokens) and tokens[j].type == "number":
            index = int(float(tokens[j].value))
            if 0 <= index < len(_items):
                return _simple_item_type(_items[index], variables)
    return direct


def _array_items(tokens: list[Token], start: int) -> tuple[list[list[Token]], int] | None:
    """Split one array literal into top-level item token slices."""
    depth = 0
    items: list[list[Token]] = []
    item_start = start + 1
    for i in range(start, len(tokens)):
        kind = tokens[i].type
        if kind == "lbracket":
            depth += 1
        elif kind == "rbracket":
            depth -= 1
            if depth == 0:
                if i > item_start:
                    items.append(tokens[item_start:i])
                return items, i
        elif kind == "comma" and depth == 1:
            items.append(tokens[item_start:i])
            item_start = i + 1
    return None


def _simple_item_type(item: list[Token], variables: dict[str, str]) -> str | None:
    visible = [t for t in item if t.type not in _TRIVIA]
    if len(visible) != 1:
        return None
    # Find token within full input to allow normal literal and symbol typing.
    return _infer_operand(visible, 0, variables)


def check_argument_types(
    tokens: list[Token], function_signatures: dict[str, list[str | None]] | None = None,
    function_return_types: dict[str, str] | None = None,
) -> list[Diagnostic]:
    """Check built-in unary arguments and configured function argument types."""
    diags: list[Diagnostic] = []
    variables: dict[str, str] = {}
    # Collect simple literal assignments. If the same variable is assigned
    # values of different types, forget its type rather than guess.
    for i, tok in enumerate(tokens[:-2]):
        if tok.type != "local" or tokens[i + 1].type != "operator" or tokens[i + 1].value != "=":
            continue
        inferred = _infer_expression(tokens, i + 2, variables, function_return_types)
        key = tok.value.lower()
        if inferred is None:
            variables.pop(key, None)
        elif key not in variables:
            variables[key] = inferred
        elif variables[key] != inferred:
            variables.pop(key, None)

    for i, tok in enumerate(tokens):
        if tok.type != "ident":
            continue
        rule = _SIGNATURES.get(tok.value.lower())
        if rule is None:
            continue
        j = i + 1
        while j < len(tokens) and tokens[j].type in _TRIVIA:
            j += 1
        if j >= len(tokens):
            continue
        actual = _infer_operand(tokens, j, variables)
        accepted, expected = rule
        if actual is not None and actual not in accepted:
            diags.append(Diagnostic(Severity.WARNING, _CODE, f"{tok.value} expects {expected}, got {actual}", tokens[j].line, tokens[j].column))

    # Project-configured functions, including mod functions, use the common
    # SQF form `[arg1, arg2] call tag_fnc_name;`. Verify each known argument.
    signatures = {name.lower(): types for name, types in (function_signatures or {}).items()}
    for i, tok in enumerate(tokens):
        if tok.type != "lbracket":
            continue
        split = _array_items(tokens, i)
        if split is None:
            continue
        items, close = split
        j = close + 1
        while j < len(tokens) and tokens[j].type in _TRIVIA:
            j += 1
        if j >= len(tokens) or tokens[j].type != "keyword" or tokens[j].value.lower() not in ("call", "spawn"):
            continue
        j += 1
        while j < len(tokens) and tokens[j].type in _TRIVIA:
            j += 1
        if j >= len(tokens) or tokens[j].type != "ident":
            continue
        signature = signatures.get(tokens[j].value.lower())
        if signature is None:
            continue
        for arg_index, expected in enumerate(signature[:len(items)]):
            if expected is None:
                continue
            actual = _simple_item_type(items[arg_index], variables)
            if actual is None:
                continue
            accepted = {part.strip().title() for part in expected.split("|")}
            if actual not in accepted and "Anything" not in accepted:
                arg_tok = next((t for t in items[arg_index] if t.type not in _TRIVIA), tok)
                diags.append(Diagnostic(Severity.WARNING, _CODE, f"{tokens[j].value} argument {arg_index + 1} expects {expected}, got {actual}", arg_tok.line, arg_tok.column))
    return diags


def check_argument_types_text(source: str) -> list[Diagnostic]:
    return check_argument_types(tokenize(source))


if __name__ == "__main__":
    assert check_argument_types_text('hint "hello"; sleep 1;') == []
    assert check_argument_types_text('hint 42;')[0].code == _CODE
    assert check_argument_types_text('sleep "soon";')[0].message.endswith("got String")
    assert check_argument_types_text('hint [parseText "hello"];') == []
    assert check_argument_types_text('sleep _delay;') == []
    assert check_argument_types_text('systemChat 42;')[0].message.endswith("got Number")
    assert check_argument_types_text('uiSleep "soon";')[0].code == _CODE
    assert check_argument_types_text('count "abc";') == []
    assert check_argument_types_text('count true;')[0].code == _CODE
    assert check_argument_types_text('sqrt "x";')[0].code == _CODE
    assert check_argument_types_text('toLower 42;')[0].code == _CODE
    assert check_argument_types_text('selectRandom "not an array";')[0].code == _CODE
    assert check_argument_types_text('abs -2; toUpper "ok";') == []
    assert check_argument_types_text('_d = [0, 0, []] call unknown_fnc; round _d;') == []
    assert check_argument_types_text('_d = getDir player; sin _d;') == []
    assert check_argument_types_text('_p = [0, 0, 0] getPosASL objNull; count _p;') == []
    assert check_argument_types_text('_roads = [0, 0, 0] nearRoads 8; count _roads;') == []
    assert check_argument_types(
        tokenize('_d = [] call ALT_fnc_distanceToRoute; round _d;'),
        function_return_types={"ALT_fnc_distanceToRoute": "Number"},
    ) == []
    assert check_argument_types_text('_delay = "soon"; sleep _delay;')[-1].code == _CODE
    assert check_argument_types_text('_positions = [1]; private _remaining = +_positions; count _remaining;') == []
    assert check_argument_types_text(
        'private _remaining = +ALT_currentEnemyPositions; while { (count _remaining) > 0 } do {};'
    ) == []
    assert check_argument_types_text('_value = 1; _value = "x"; sleep _value;') == []
    assert check_argument_types(tokenize('[42, "ok"] call acme_fnc_route;'), {"acme_fnc_route": ["Object", "String"]})[0].message == "acme_fnc_route argument 1 expects Object, got Number"
    assert check_argument_types(tokenize('[player, "ok"] call acme_fnc_route;'), {"ACME_fnc_route": ["Object", "String"]}) == []
    assert check_argument_types(tokenize('[true] spawn acme_fnc_route;'), {"acme_fnc_route": ["Number"]})[0].code == _CODE
    print("argument_types self-test passed")
