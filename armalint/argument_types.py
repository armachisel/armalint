"""Static type inference and built-in SQF command argument checks.

Only expressions whose type is unambiguous are checked. The command signature
table is intentionally declarative so coverage can grow without changing the
checker; unknown expressions and mission functions remain unchecked.
"""

from __future__ import annotations

from .diagnostic import Diagnostic, Severity
from .ast import Block, IfStatement, LoopStatement, Node, Statement, parse
from .tokenizer import Token, tokenize

_CODE = "W203"
_ARITY_CODE = "W204"
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
    "parsesimplearray": (frozenset(("String",)), "String"),
    "toarray": (frozenset(("String",)), "String"),
    "tostring": (frozenset(("Array",)), "Array"),
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
    "count": (frozenset(("String", "Array", "Config", "HashMap")), "String, Array, Config or HashMap"),
}

_BINARY_SIGNATURES: dict[str, tuple[frozenset[str], str]] = {
    "arrayintersect": (frozenset(("Array",)), "Array"),
    "setpos": (frozenset(("Array",)), "Array"),
    "setposasl": (frozenset(("Array",)), "Array"),
    "setposatl": (frozenset(("Array",)), "Array"),
    "setvelocity": (frozenset(("Array",)), "Array"),
    "setvectordir": (frozenset(("Array",)), "Array"),
    "setvectorup": (frozenset(("Array",)), "Array"),
    "setdir": (frozenset(("Number",)), "Number"),
    "setdamage": (frozenset(("Number",)), "Number"),
    "setfuel": (frozenset(("Number",)), "Number"),
    "setcaptive": (frozenset(("Boolean",)), "Boolean"),
    "allowdamage": (frozenset(("Boolean",)), "Boolean"),
    "setbehaviour": (frozenset(("String",)), "String"),
    "setunitpos": (frozenset(("String",)), "String"),
}

_RETURN_TYPES = {
    "str": "String", "format": "String", "parsetext": "Structured Text",
    "composetext": "Structured Text", "parsenumber": "Number",
    "toarray": "Array", "tolower": "String", "toupper": "String",
    "typename": "String", "typeof": "String", "tostring": "String",
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
    "getposworld": "Array", "getposvisual": "Array",
    "velocity": "Array", "vectorup": "Array", "vectordir": "Array",
    "nearroads": "Array", "getroadinfo": "Array",
    "arrayintersect": "Array", "pushback": "Number", "pushbackunique": "Number",
    "findif": "Number",
    "distance": "Number", "distance2d": "Number", "vectormagnitude": "Number",
    "min": "Number", "max": "Number", "mod": "Number",
    "random": "Number", "isnull": "Boolean", "isnil": "Boolean",
    "isclass": "Boolean", "isarray": "Boolean", "istext": "Boolean",
    "isnumber": "Boolean", "isequaltype": "Boolean", "find": "Number",
    "isserver": "Boolean", "isdedicated": "Boolean", "hasinterface": "Boolean",
    "createhashmap": "HashMap", "createhashmapfrom": "HashMap",
}
_ARRAY_ELEMENT_TYPES = {
    "nearroads": "Object", "allplayers": "Object", "allunits": "Object",
    "allvehicles": "Object", "allmissionobjects": "Object", "allgroups": "Group",
}
_KNOWN_VARIABLE_TYPES = {
    "player": "Object", "objnull": "Object", "grpnull": "Group",
    "west": "Side", "east": "Side", "resistance": "Side", "civilian": "Side",
    "configfile": "Config", "missionconfigfile": "Config",
    "profileconfigfile": "Config", "campaignconfigfile": "Config",
}


def _infer_operand(tokens: list[Token], i: int, variables: dict[str, str]) -> str | None:
    """Infer a simple operand type, including prior literal assignments."""
    if i >= len(tokens):
        return None
    tok = tokens[i]
    if tok.type == "lparen":
        depth = 0
        for end in range(i, len(tokens)):
            if tokens[end].type == "lparen":
                depth += 1
            elif tokens[end].type == "rparen":
                depth -= 1
                if depth == 0:
                    inner = [t for t in tokens[i + 1:end] if t.type not in _TRIVIA]
                    return _infer_expression(inner, 0, variables) if inner else None
        return None
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
    if start < len(tokens) and tokens[start].type == "lparen":
        depth = 0
        for close in range(start, len(tokens)):
            if tokens[close].type == "lparen":
                depth += 1
            elif tokens[close].type == "rparen":
                depth -= 1
                if depth == 0:
                    inner = _infer_expression(tokens[start + 1:close], 0, variables)
                    j = close + 1
                    while j < len(tokens) and tokens[j].type in _TRIVIA:
                        j += 1
                    if (inner == "Array" and j < len(tokens)
                            and tokens[j].value.lower() == "select"):
                        return "Number" if j + 1 < len(tokens) and tokens[j + 1].type == "number" else None
                    if j < len(tokens) and tokens[j].value.lower() in _COMMAND_RETURN_TYPES:
                        return _COMMAND_RETURN_TYPES[tokens[j].value.lower()]
                    return inner
    if start < len(tokens) and tokens[start].type == "operator" and tokens[start].value in ("+", "-"):
        # Unary + preserves the operand type (commonly used to copy arrays);
        # unary - is numeric.
        return (_infer_operand(tokens, start + 1, variables)
                if tokens[start].value == "+" else "Number")
    if start < len(tokens) and tokens[start].value.lower() in _COMMAND_RETURN_TYPES:
        return _COMMAND_RETURN_TYPES[tokens[start].value.lower()]
    if start < len(tokens) and tokens[start].value.lower() == "getvariable":
        default_start = start + 1
        while default_start < len(tokens) and tokens[default_start].type in _TRIVIA:
            default_start += 1
        if default_start < len(tokens) and tokens[default_start].type == "lbracket":
            split = _array_items(tokens, default_start)
            if split:
                items, _close = split
                if len(items) > 1:
                    return _simple_item_type(items[1], variables)
    operand_end = start + 1
    while operand_end < len(tokens) and tokens[operand_end].type in _TRIVIA:
        operand_end += 1
    if start < len(tokens) and tokens[start].value.lower() in {
        "getpos", "getposasl", "getposatl", "getposworld", "getposvisual",
    }:
        select = operand_end + 1
        while select < len(tokens) and tokens[select].type in _TRIVIA:
            select += 1
        if (select < len(tokens) and tokens[select].value.lower() == "select"
                and select + 1 < len(tokens) and tokens[select + 1].type == "number"):
            return "Number"
    if operand_end < len(tokens) and tokens[operand_end].value.lower() in _COMMAND_RETURN_TYPES:
        return _COMMAND_RETURN_TYPES[tokens[operand_end].value.lower()]
    if operand_end < len(tokens) and tokens[operand_end].value.lower() == "getvariable":
        default_start = operand_end + 1
        while default_start < len(tokens) and tokens[default_start].type in _TRIVIA:
            default_start += 1
        if default_start < len(tokens) and tokens[default_start].type == "lbracket":
            split = _array_items(tokens, default_start)
            if split:
                items, _close = split
                if len(items) > 1:
                    return _simple_item_type(items[1], variables)
    direct = _infer_operand(tokens, start, variables)
    # A small amount of arithmetic inference is safe when both operands have
    # already-known numeric types. SQF also uses ``min``/``max`` as binary
    # numeric commands; those are covered by the command return table above.
    if direct == "Number":
        op = start + 1
        while op < len(tokens) and tokens[op].type in _TRIVIA:
            op += 1
        if op < len(tokens) and tokens[op].type == "operator" and tokens[op].value in ("+", "-", "*", "/", "%"):
            rhs = op + 1
            while rhs < len(tokens) and tokens[rhs].type in _TRIVIA:
                rhs += 1
            if _infer_operand(tokens, rhs, variables) == "Number":
                return "Number"
    # Comparisons and boolean composition always produce Boolean values when
    # their operands are statically understood. This is useful for assignments
    # later consumed by condition-oriented commands or guards.
    op = start + 1
    while op < len(tokens) and tokens[op].type in _TRIVIA:
        op += 1
    if op < len(tokens) and tokens[op].type == "operator" and tokens[op].value in (
        "<", ">", "<=", ">=", "==", "!=", "&&", "||",
    ):
        rhs = op + 1
        while rhs < len(tokens) and tokens[rhs].type in _TRIVIA:
            rhs += 1
        if _infer_operand(tokens, rhs, variables) is not None:
            return "Boolean"
    if direct != "Array" or start >= len(tokens):
        return direct
    split = _array_items(tokens, start)
    if split is None:
        # An array variable followed by ``select`` yields the element type,
        # which cannot be recovered from the container type alone.
        command = start + 1
        while command < len(tokens) and tokens[command].type in _TRIVIA:
            command += 1
        if command < len(tokens) and tokens[command].value.lower() == "select":
            return None
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


def _collect_param_types(tokens: list[Token], variables: dict[str, str]) -> None:
    """Infer locals from ``params [[name, default, [validators]], ...]``."""
    for i, token in enumerate(tokens):
        if token.type != "keyword" or token.value.lower() != "params":
            continue
        start = i + 1
        while start < len(tokens) and tokens[start].type in _TRIVIA:
            start += 1
        if start >= len(tokens) or tokens[start].type != "lbracket":
            continue
        depth = 0
        j = start
        while j < len(tokens):
            if tokens[j].type == "lbracket":
                depth += 1
                if depth == 2:
                    name = j + 1
                    while name < len(tokens) and tokens[name].type in _TRIVIA:
                        name += 1
                    if name < len(tokens) and tokens[name].type == "string" and tokens[name].value.startswith("_"):
                        comma = name + 1
                        while comma < len(tokens) and tokens[comma].type not in ("comma", "rbracket"):
                            comma += 1
                        if comma < len(tokens) and tokens[comma].type == "comma":
                            default = comma + 1
                            while default < len(tokens) and tokens[default].type in _TRIVIA:
                                default += 1
                            inferred = _infer_operand(tokens, default, variables)
                            if inferred:
                                variables[tokens[name].value.lower()] = inferred
            elif tokens[j].type == "rbracket":
                depth -= 1
                if depth == 0:
                    break
            j += 1


def _collect_foreach_element_types(tokens: list[Token], variables: dict[str, str]) -> None:
    """Infer loop element types from AST headers and body spans."""
    def collect_body(node: Node, element_type: str) -> None:
        if isinstance(node, Statement):
            for i, token in enumerate(node.tokens[:-2]):
                if (token.type == "local" and node.tokens[i + 1].type == "operator"
                        and node.tokens[i + 1].value == "="
                        and node.tokens[i + 2].type == "local"
                        and node.tokens[i + 2].value.lower() == "_x"):
                    variables[token.value.lower()] = element_type
            for embedded in node.embedded:
                collect_loop(embedded)
        elif isinstance(node, Block):
            for child in node.statements:
                collect_body(child, element_type)
        elif isinstance(node, IfStatement):
            if node.then_block:
                collect_body(node.then_block, element_type)
            if node.else_block:
                collect_body(node.else_block, element_type)

    def collect_loop(node: Node) -> None:
        if not isinstance(node, LoopStatement):
            if isinstance(node, Statement):
                for embedded in node.embedded:
                    collect_loop(embedded)
            elif isinstance(node, Block):
                for child in node.statements:
                    collect_loop(child)
            elif isinstance(node, IfStatement):
                if node.then_block: collect_loop(node.then_block)
                if node.else_block: collect_loop(node.else_block)
            return
        producer = next((t.value.lower() for t in node.header if t.value.lower() in _ARRAY_ELEMENT_TYPES), None)
        if producer and node.body:
            collect_body(node.body, _ARRAY_ELEMENT_TYPES[producer])
        if node.body:
            collect_loop(node.body)

    for node in parse(tokens).statements:
        collect_loop(node)


def _merge_types(previous: str | None, inferred: str | None) -> str | None:
    if inferred is None:
        return previous
    if previous is None or previous == inferred:
        return inferred
    members = set(previous.split("|")) | set(inferred.split("|"))
    return "|".join(sorted(members))


def _narrowed_type(tokens: list[Token], index: int, variables: dict[str, str]) -> str | None:
    """Use a preceding ``x isEqualType literal`` guard for this operand.

    SQF commonly validates an argument with a short-circuit expression before
    using it, for example ``_n isEqualType 0 && { abs _n < 10 }``.  The
    assignment/params pass quite correctly sees the declared default type, but
    within this guarded expression the operand has the checked type.
    """
    if index >= len(tokens) or tokens[index].type != "local":
        return None
    name = tokens[index].value.lower()
    for i in range(index - 1, -1, -1):
        if tokens[i].type == "semicolon":
            break
        if (tokens[i].type == "local" and tokens[i].value.lower() == name
                and i + 2 < index
                and tokens[i + 1].value.lower() == "isequaltype"):
            sample = _infer_operand(tokens, i + 2, variables)
            if sample:
                return sample
    return None


def check_argument_types(
    tokens: list[Token], function_signatures: dict[str, list[str | None]] | None = None,
    function_return_types: dict[str, str] | None = None,
) -> list[Diagnostic]:
    """Check built-in unary arguments and configured function argument types."""
    diags: list[Diagnostic] = []
    variables: dict[str, str] = {}
    _collect_param_types(tokens, variables)
    _collect_foreach_element_types(tokens, variables)
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
    # Re-apply precise loop-element facts after ordinary assignment collection;
    # the loop body may otherwise look like a conflicting global assignment.
    _collect_foreach_element_types(tokens, variables)

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
        actual = _narrowed_type(tokens, j, variables) or _infer_operand(tokens, j, variables)
        accepted, expected = rule
        if actual is not None and not all(member in accepted for member in actual.split("|")):
            diags.append(Diagnostic(Severity.WARNING, _CODE, f"{tok.value} expects {expected}, got {actual}", tokens[j].line, tokens[j].column))

    # A small set of binary commands has a stable right-hand operand type.
    # Keep this separate from unary signatures until command metadata can
    # describe arity and left/right operand rules generally.
    for i, tok in enumerate(tokens):
        rule = _BINARY_SIGNATURES.get(tok.value.lower()) if tok.type == "ident" else None
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
        if len(items) > len(signature):
            expected = len(signature)
            actual = len(items)
            message = f"{tokens[j].value} received {actual} argument(s), signature has {expected}"
            diags.append(Diagnostic(
                Severity.WARNING, _ARITY_CODE, message,
                tokens[j].line, tokens[j].column,
            ))
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
    assert check_argument_types_text('count configFile; count createHashMap;') == []
    assert check_argument_types_text('sqrt "x";')[0].code == _CODE
    assert check_argument_types_text('toLower 42;')[0].code == _CODE
    assert check_argument_types_text('selectRandom "not an array";')[0].code == _CODE
    assert check_argument_types_text('abs -2; toUpper "ok";') == []
    assert check_argument_types_text('parseSimpleArray "[1]"; toString [1, 2];') == []
    assert check_argument_types_text('parseSimpleArray 42;')[0].code == _CODE
    assert check_argument_types_text('_d = [0, 0, []] call unknown_fnc; round _d;') == []
    assert check_argument_types_text('_d = getDir player; sin _d;') == []
    assert check_argument_types_text('_p = [0, 0, 0] getPosASL objNull; count _p;') == []
    assert check_argument_types_text('_roads = [0, 0, 0] nearRoads 8; count _roads;') == []
    assert check_argument_types_text('_a = 10; _b = 2; _c = _a - _b; sqrt _c;') == []
    assert check_argument_types_text('_a = 10; _b = 2; _c = _a min _b; sin _c;') == []
    assert check_argument_types_text('_ok = 1 > 0; sleep _ok;')[0].code == _CODE
    assert check_argument_types_text('_ok = (1 > 0); sleep _ok;')[0].code == _CODE
    assert check_argument_types_text('_alt = round (((getPosATL player) select 2) max 0);') == []
    assert check_argument_types_text('_n = (1 max 0); sleep _n;') == []
    assert check_argument_types_text('_items = [1]; _item = _items select 0; sleep _item;') == []
    assert check_argument_types_text('_delay = missionNamespace getVariable ["delay", 1]; sleep _delay;') == []
    assert check_argument_types_text('_delay = missionNamespace getVariable ["delay", "soon"]; sleep _delay;')[0].code == _CODE
    assert check_argument_types_text('_delay = getVariable ["delay", 1]; sleep _delay;') == []
    assert check_argument_types_text('_nearest = []; { _nearest = _x; } forEach ([0, 0, 0] nearRoads 10); count _nearest;')[0].code == _CODE
    assert check_argument_types_text('_unit = objNull; { _unit = _x; } forEach allUnits; count _unit;')[0].code == _CODE
    assert check_argument_types_text('_items = [1]; _index = _items pushBack 2; sleep _index;') == []
    assert check_argument_types_text('_common = [1] arrayIntersect [2]; count _common;') == []
    assert check_argument_types_text('[1] arrayIntersect 2;')[0].code == _CODE
    assert check_argument_types_text('player setPos [0, 0, 0]; player setDir 90;') == []
    assert check_argument_types_text('player setPos 42;')[0].code == _CODE
    assert check_argument_types_text('player setFuel 0.5; player allowDamage true; player setBehaviour "COMBAT";') == []
    assert check_argument_types_text('player setFuel "full";')[0].code == _CODE
    assert check_argument_types(
        tokenize('_d = [] call ALT_fnc_distanceToRoute; round _d;'),
        function_return_types={"ALT_fnc_distanceToRoute": "Number"},
    ) == []
    assert check_argument_types_text('params [["_delay", 0, [0]]]; sleep _delay;') == []
    assert check_argument_types_text('params [["_delay", "soon", [""]]]; sleep _delay;')[0].code == _CODE
    assert check_argument_types_text('params [["_n", ""]]; { _n isEqualType 0 && { abs _n < 100 } };') == []
    assert check_argument_types_text('_delay = "soon"; sleep _delay;')[-1].code == _CODE
    assert check_argument_types_text('_positions = [1]; private _remaining = +_positions; count _remaining;') == []
    assert check_argument_types_text(
        'private _remaining = +ALT_currentEnemyPositions; while { (count _remaining) > 0 } do {};'
    ) == []
    assert check_argument_types_text('_value = 1; _value = "x"; sleep _value;') == []
    assert check_argument_types(tokenize('[42, "ok"] call acme_fnc_route;'), {"acme_fnc_route": ["Object", "String"]})[0].message == "acme_fnc_route argument 1 expects Object, got Number"
    assert check_argument_types(tokenize('[player, "ok"] call acme_fnc_route;'), {"ACME_fnc_route": ["Object", "String"]}) == []
    assert check_argument_types(tokenize('[player] call acme_fnc_route;'), {"acme_fnc_route": ["Object", "String"]}) == []
    assert check_argument_types(tokenize('[player, "ok", 1] call acme_fnc_route;'), {"acme_fnc_route": ["Object", "String"]})[0].code == _ARITY_CODE
    assert check_argument_types(tokenize('[true] spawn acme_fnc_route;'), {"acme_fnc_route": ["Number"]})[0].code == _CODE
    print("argument_types self-test passed")
