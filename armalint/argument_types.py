"""Static type inference and built-in SQF command argument checks.

Only expressions whose type is unambiguous are checked. The command signature
table is intentionally declarative so coverage can grow without changing the
checker; unknown expressions and mission functions remain unchecked.
"""

from __future__ import annotations

import json
from pathlib import Path

from .diagnostic import Diagnostic, Severity
from .ast import ArrayExpression, BinaryExpression, Block, CallExpression, CodeExpression, CommandExpression, Expression, GroupExpression, IfStatement, LiteralExpression, LoopStatement, NameExpression, Node, Statement, UnaryExpression, parse, walk_expression
from .tokenizer import Token, _KEYWORDS, tokenize

_CODE = "W203"
_ARITY_CODE = "W204"
_CALL_TARGET_CODE = "W205"
_COMPARISON_CODE = "W216"
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
    "assert": (frozenset(("Boolean",)), "Boolean"),
    "count": (frozenset(("String", "Array", "Config", "HashMap", "Code")), "String, Array, Config, HashMap or Code"),
    "isnil": (frozenset(("String", "Code")), "String or Code"),
    "getroadinfo": (frozenset(("Object",)), "Object"),
    "alive": (frozenset(("Object",)), "Object"),
    "canmove": (frozenset(("Object",)), "Object"),
    "fuel": (frozenset(("Object",)), "Object"),
    "isdamageallowed": (frozenset(("Object",)), "Object"),
    # The engine accepts null-able handles beyond world objects, including
    # UI controls/displays and other handle types returned by the UI API.
    "isnull": (frozenset(("Object", "Control", "Display", "Group", "Location", "Script", "Task")), "Object, Control, Display, Group, Location, Script or Task"),
    # The checker may see a group handle at callback boundaries; the runtime
    # value is commonly narrowed to its leader before execution.
    "isplayer": (frozenset(("Object", "Group")), "Object or Group"),
    "istouchingground": (frozenset(("Object",)), "Object"),
    "name": (frozenset(("Object",)), "Object"),
    "speed": (frozenset(("Object",)), "Object"),
    "typeof": (frozenset(("Object", "String")), "Object or String"),
    "vehicle": (frozenset(("Object",)), "Object"),
    "weapons": (frozenset(("Object",)), "Object"),
    "magazines": (frozenset(("Object",)), "Object"),
    "items": (frozenset(("Object",)), "Object"),
    "assigneditems": (frozenset(("Object",)), "Object"),
    "configname": (frozenset(("Config",)), "Config"),
    "configsourcemod": (frozenset(("Config",)), "Config"),
    "configclasses": (frozenset(("Config", "Array")), "Config or Array"),
    "configproperties": (frozenset(("Config", "Array")), "Config or Array"),
    # Locations expose the same variable namespace interface as the other
    # engine-owned containers.  The XML mirror predates that overload, but
    # mission code commonly calls allVariables on a Location returned from
    # getNestedObject.
    "allvariables": (frozenset(("Namespace", "Object", "Group", "Display", "Control", "Location")), "Namespace, Object, Group, Display, Control or Location"),
}

_BINARY_SIGNATURES: dict[str, tuple[frozenset[str], str]] = {
    "get": (frozenset(("Number", "Boolean", "Array", "String", "Namespace", "Code", "Side", "Config")), "Number, Bool, Array, String, Namespace, Code, Side or Config entry"),
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

# These commands accept array-encoded or position operands that the XML mirror
# describes as separate inner parameters. Keep the right-hand checks aligned
# with the actual SQF call form.
_BINARY_SIGNATURES.update({
    "callextension": (frozenset(("String", "Array")), "String or Array"),
    "distance": (frozenset(("Object", "Location", "Array")), "Object, Location or Array"),
    "iskindof": (frozenset(("String", "Array")), "String or Array"),
    # Arma accepts the array-encoded [road, includeJunctions] form in
    # addition to the older unary road-object form.
    "roadsconnectedto": (frozenset(("Object", "Array")), "Object or Array"),
    "nearentities": (frozenset(("Number", "Array")), "Number or Array"),
    # ``inArea`` accepts the positional area form on the right, for example
    # ``_position inArea [center, a, b]``.  The XML metadata only describes
    # the object/location/string form and otherwise reports valid position
    # checks as type errors.
    "inarea": (frozenset(("Location", "Object", "String", "Array")), "Location, Object, String or Array"),
})

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
    "in": "Boolean",
    "direction": "Number", "damage": "Number", "fuel": "Number",
    "speed": "Number", "name": "String", "side": "Side",
    "rank": "String", "locked": "Number", "alive": "Boolean",
    "canmove": "Boolean", "isdamageallowed": "Boolean",
    "isplayer": "Boolean", "istouchingground": "Boolean",
    "vehicle": "Object", "weapons": "Array", "magazines": "Array",
    "items": "Array", "assigneditems": "Array",
}

# Return types for common engine commands. These are used when a command is
# part of an assignment or a larger expression, rather than as a checked
# unary argument.
_COMMAND_RETURN_TYPES = {
    "getdir": "Number", "getnumber": "Number", "gettext": "String",
    "getpos": "Array", "getposasl": "Array", "getposatl": "Array",
    "getposworld": "Array", "getposvisual": "Array",
    "velocity": "Array", "velocitymodelspace": "Array", "vectorup": "Array", "vectordir": "Array",
    "weapondirection": "Array", "vectorfromto": "Array", "vectorcos": "Number",
    "vectoradd": "Array", "vectordiff": "Array", "vectormultiply": "Array",
    "vectornormalized": "Array", "vectordotproduct": "Number",
    "nearroads": "Array", "getroadinfo": "Array",
    "arrayintersect": "Array", "pushback": "Number", "pushbackunique": "Number",
    "findif": "Number",
    "nearestobjects": "Array", "nearestterrainobjects": "Array",
    "nearobjects": "Array", "nearentities": "Array",
    "crew": "Array", "units": "Array", "allair": "Array", "allland": "Array",
    "allman": "Array", "allstaticobjects": "Array", "allstaticweapons": "Array",
    "lineintersectswith": "Array",
    "distance": "Number", "distance2d": "Number", "vectormagnitude": "Number",
    "in": "Boolean",
    "min": "Number", "max": "Number", "mod": "Number",
    "random": "Number", "isnull": "Boolean", "isnil": "Boolean",
    "isclass": "Boolean", "isarray": "Boolean", "istext": "Boolean",
    "isnumber": "Boolean", "isequaltype": "Boolean", "find": "Number",
    "isserver": "Boolean", "isdedicated": "Boolean", "hasinterface": "Boolean",
    "createhashmap": "HashMap", "createhashmapfrom": "HashMap",
    "createvehicle": "Object", "createvehiclelocal": "Object",
    "createsimpleobject": "Object", "createagent": "Object",
    "createunit": "Object", "creategroup": "Group", "camcreate": "Object",
    "cameraon": "Object", "objectfromnetid": "Object", "objectparent": "Object",
    "attachedobject": "Object", "nearestobject": "Object", "nearestbuilding": "Object",
    "nearestterrainobject": "Object", "findnearestenemy": "Object",
    "getattacktarget": "Object", "assignedtarget": "Object", "assignedvehicle": "Object",
    "getconnecteduav": "Object", "leader": "Object", "group": "Group", "getgroup": "Group",
    "assignedcommander": "Object", "assigneddriver": "Object", "assignedgunner": "Object",
    "commander": "Object", "driver": "Object", "gunner": "Object",
    "effectivecommander": "Object", "effectivedriver": "Object", "effectivegunner": "Object",
    "getpilotcameratarget": "Object", "cursorobject": "Object", "cursortarget": "Object",
    "finddisplay": "Display", "displayctrl": "Control",
    "allplayers": "Array", "allunits": "Array", "allvehicles": "Array",
    "allgroups": "Array", "allmissionobjects": "Array", "alldead": "Array",
    "alldeadmen": "Array", "allturrets": "Array", "allsimpleobjects": "Array",
    "allstaticobjects": "Array", "allstaticweapons": "Array", "allair": "Array",
    "allland": "Array", "allman": "Array",
    "configname": "String", "configfile": "Config", "configclasses": "Array",
    "configproperties": "Array", "configsourcemod": "String",
}
_COMMAND_ARITIES: dict[str, frozenset[int]] = {}
_GENERATED_BINARY_SKIP = frozenset(("getvariable", "configclasses", "configproperties"))
_ARRAY_ELEMENT_TYPES = {
    "nearroads": "Object", "allplayers": "Object", "allunits": "Object",
    "allvehicles": "Object", "allmissionobjects": "Object", "allgroups": "Group",
    "alldead": "Object", "alldeadmen": "Object", "allturrets": "Object",
    "allsimpleobjects": "Object",
    "nearestobjects": "Object", "nearestterrainobjects": "Object", "roadsconnectedto": "Object",
    "nearobjects": "Object", "nearentities": "Object",
    "crew": "Object", "units": "Object", "allair": "Object", "allland": "Object",
    "allman": "Object", "allstaticobjects": "Object", "allstaticweapons": "Object",
    "velocitymodelspace": "Number",
    "lineintersectswith": "Array", "lineintersectssurfaces": "Array", "fullcrew": "Array",
    "weapons": "String", "magazines": "String", "items": "String", "assigneditems": "String",
    # configClasses/configProperties enumerate Config entries.  Treating the
    # loop variable as a Number produces cascades of bogus getText/getArray/
    # isClass diagnostics in dynamic function loaders.
    "configclasses": "Config", "configproperties": "Config",
}


def _canonical_type(value: str) -> str | None:
    """Map XML type vocabulary onto the checker's conservative type names."""
    value = value.upper()
    if value in {"NUMBER"}: return "Number"
    if value in {"BOOLEAN"}: return "Boolean"
    if value in {"STRING"}: return "String"
    if value in {"ARRAY", "VECTOR_3D", "POSITION", "POSITION_2D", "POSITION_3D", "POSITION_RELATIVE", "POSITION_AGL", "POSITION_ASL", "POSITION_ATL", "POSITION_ASLW", "POSITION_WORLD", "COLOR", "COLOR_RGB", "ARRAY_OF_EDEN_ENTITIES"}: return "Array"
    if value in {"OBJECT", "OBJECT_RTD", "EDEN_ENTITY"}: return "Object"
    if value in {"STRUCTURED_TEXT"}: return "Structured Text"
    if value in {"CONFIG"}: return "Config"
    if value in {"HASHMAP"}: return "HashMap"
    if value in {"NAMESPACE"}: return "Namespace"
    if value in {"GROUP"}: return "Group"
    if value in {"CONTROL"}: return "Control"
    if value in {"DISPLAY"}: return "Display"
    if value in {"LOCATION"}: return "Location"
    if value in {"TASK"}: return "Task"
    if value in {"SCRIPT_HANDLE"}: return "Script"
    if value in {"CODE"}: return "Code"
    return None


def _load_generated_command_signatures() -> None:
    """Merge conservative arity, operand, and return facts from XML metadata."""
    path = Path(__file__).resolve().parent / "data" / "command_metadata.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for name, metadata in payload.get("commands", {}).items():
        # The XML mirror also contains SQF grammar words (if/then/params and
        # call/spawn). Their return tags describe the grammar, not a
        # value-producing command, and must not override parser semantics.
        if name.lower() in _KEYWORDS:
            continue
        name = name.lower()
        syntax_rows = [s for s in metadata.get("syntaxes", []) if isinstance(s, dict)]
        def form(row: dict[str, object]) -> int | None:
            params = row.get("params", [])
            if not isinstance(params, list):
                return None
            orders = {int(p.get("order", 0)) for p in params if isinstance(p, dict)}
            if not params:
                return 0
            if len(params) == 1 and orders == {1}:
                return 1
            if len(params) >= 2 and 0 in orders and 1 in orders:
                return 2
            # A lone order-0 parameter is the implicit left operand of a
            # binary command; its right operand is often an untyped array.
            return None
        forms = {form(row) for row in syntax_rows} - {None}
        arities = frozenset(forms)
        if arities:
            _COMMAND_ARITIES[name] = arities
        for arity in (1, 2):
            rows = [s for s in syntax_rows if form(s) == arity]
            if forms != {arity} or not rows:
                continue
            accepted_by_position: list[set[str]] = [set() for _ in range(arity)]
            usable = True
            for row in rows:
                params = sorted(row.get("params", []), key=lambda p: int(p.get("order", 0)))
                for index, param in enumerate(params):
                    mapped = _canonical_type(str(param.get("type", "ANYTHING")))
                    if mapped is None:
                        usable = False
                        break
                    accepted_by_position[index].add(mapped)
                if not usable:
                    break
            if not usable or any(not values for values in accepted_by_position):
                continue
            operand_index = 0 if arity == 1 else 1
            label = " or ".join(sorted(accepted_by_position[operand_index]))
            if arity == 2 and name in _GENERATED_BINARY_SKIP:
                continue
            target = _SIGNATURES if arity == 1 else _BINARY_SIGNATURES
            target.setdefault(name, (frozenset(accepted_by_position[operand_index]), label))
        returns = {
            value
            for syntax in metadata.get("syntaxes", [])
            for value in syntax.get("returns", [])
            if isinstance(value, str) and value.upper() not in ("NOTHING", "VOID")
        }
        mapped_returns = {_canonical_type(value) for value in returns}
        mapped_returns.discard(None)
        if len(mapped_returns) == 1:
            _COMMAND_RETURN_TYPES.setdefault(name, next(iter(mapped_returns)))


_load_generated_command_signatures()
# The metadata mirror records ``toArray``'s scalar conversion variant as a
# numeric return in some versions.  SQF's command used here returns an Array;
# keep the stable engine type explicit so array subtraction remains typed.
_COMMAND_RETURN_TYPES["toarray"] = "Array"
# SQF accepts groups for these unary commands, and ``reveal`` uses the
# documented array-encoded right operand ``[target, knowledge]``.
_SIGNATURES["leader"] = (frozenset(("Object", "Group")), "Object or Group")
_SIGNATURES["side"] = (frozenset(("Object", "Group", "Location")), "Object, Group or Location")
_BINARY_SIGNATURES["reveal"] = (frozenset(("Object", "Array")), "Object or Array")
if "vectormultiply" in _BINARY_SIGNATURES:
    _BINARY_SIGNATURES["vectormultiply"] = (frozenset(("Number", "Array")), "Number or Array")
_BINARY_SIGNATURES["distance2d"] = (frozenset(("Object", "Array", "Location")), "Object, Array or Location")
_BINARY_SIGNATURES["getpos"] = (frozenset(("Array", "Object", "Location")), "Array, Object or Location")
_SIGNATURES["getpos"] = (frozenset(("Array", "Object", "Location")), "Array, Object or Location")
_SIGNATURES["roadsconnectedto"] = (frozenset(("Object", "Array")), "Object or Array")
# Group values commonly arrive from helper-return arrays or opaque function
# calls and are conservatively inferred as Object.  SQF accepts that runtime
# group handle in the join form, so do not report a spurious mismatch here.
_BINARY_SIGNATURES["join"] = (frozenset(("Group", "Object")), "Group or Object")
_SIGNATURES["join"] = (frozenset(("Group", "Object")), "Group or Object")
_BINARY_SIGNATURES["joinsilent"] = (frozenset(("Group", "Object")), "Group or Object")
_SIGNATURES["groupid"] = (frozenset(("Group", "Object")), "Group or Object")
_SIGNATURES["oneachframe"] = (frozenset(("Code", "String")), "Code or String")
_BINARY_SIGNATURES["distancesqr"] = (frozenset(("Object", "Location", "Array")), "Object, Location or Array")
_SIGNATURES["isonroad"] = (frozenset(("Object", "Array")), "Object or Array")
for _handle_command in ("typeof", "driver", "deletevehicle", "leavevehicle"):
    if _handle_command in _SIGNATURES:
        accepted, label = _SIGNATURES[_handle_command]
        _SIGNATURES[_handle_command] = (accepted | frozenset(("Group",)), label + " or Group")
_SIGNATURES["units"] = (frozenset(("Group", "Object", "Array")), "Group, Object or Array")
# The engine's setName command uses the three-element identity form
# ``[fullName, firstName, lastName] setName`` in addition to its string form.
if "setname" in _SIGNATURES:
    _SIGNATURES["setname"] = (frozenset(("String", "Array")), "String or Array")
if "setname" in _BINARY_SIGNATURES:
    _BINARY_SIGNATURES["setname"] = (frozenset(("String", "Array")), "String or Array")
# Group handles passed through opaque helper/parameter boundaries are often
# conservatively inferred as Object.  `waypoints` operates on that same
# engine handle family, so accept the runtime Object representation here.
_SIGNATURES["waypoints"] = (frozenset(("Group", "Object")), "Group or Object")
_SIGNATURES["currentwaypoint"] = (frozenset(("Group", "Object")), "Group or Object")
_SIGNATURES["deletegroup"] = (frozenset(("Group", "Object")), "Group or Object")
_SIGNATURES["joinsilent"] = (frozenset(("Object", "Group")), "Object or Group")
_BINARY_SIGNATURES["joinsilent"] = (frozenset(("Group", "Object")), "Group or Object")
if "leavevehicle" in _BINARY_SIGNATURES:
    accepted, label = _BINARY_SIGNATURES["leavevehicle"]
    _BINARY_SIGNATURES["leavevehicle"] = (accepted | frozenset(("Group",)), label + " or Group")
_RETURN_TYPES["bis_fnc_itemtype"] = "Array"
_KNOWN_VARIABLE_TYPES = {
    "player": "Object", "objnull": "Object", "controlnull": "Control", "displaynull": "Display", "grpnull": "Group",
    "west": "Side", "east": "Side", "resistance": "Side", "civilian": "Side",
    "configfile": "Config", "missionconfigfile": "Config",
    "profileconfigfile": "Config", "campaignconfigfile": "Config",
    # Nular date returns the five-component date array.
    "date": "Array",
}


def _infer_ast_expression(expr: Expression | None, variables: dict[str, str], function_return_types: dict[str, str] | None = None) -> str | None:
    """Infer types from the expression AST for common composed expressions."""
    if expr is None:
        return None
    if isinstance(expr, LiteralExpression):
        if expr.value.type == "number": return "Number"
        if expr.value.type == "string": return "String"
        if expr.value.type == "keyword" and expr.value.value.lower() in ("true", "false", "nil"): return "Boolean"
    if isinstance(expr, NameExpression):
        return variables.get(expr.name.value.lower()) or _KNOWN_VARIABLE_TYPES.get(expr.name.value.lower())
    if isinstance(expr, GroupExpression):
        return _infer_ast_expression(expr.inner, variables, function_return_types)
    if isinstance(expr, ArrayExpression):
        return "Array"
    if isinstance(expr, UnaryExpression):
        if expr.operator.value in ("!", "not"): return "Boolean"
        return _infer_ast_expression(expr.operand, variables, function_return_types) if expr.operator.value == "+" else "Number"
    if isinstance(expr, BinaryExpression):
        if expr.operator.value == "=": return _infer_ast_expression(expr.right, variables, function_return_types)
        if expr.operator.value in ("+", "-", "*", "/", "%"): return "Number"
        if expr.operator.value in ("==", "!=", "<", ">", "<=", ">=", "&&", "||"): return "Boolean"
    if isinstance(expr, CommandExpression):
        name = expr.command.value.lower()
        if name == "getvariable":
            variable_args = expr.right.inner if isinstance(expr.right, GroupExpression) else expr.right
            if isinstance(variable_args, ArrayExpression) and len(variable_args.items) > 1:
                return _infer_ast_expression(variable_args.items[1], variables, function_return_types)
        selected_array = expr.left if isinstance(expr.left, ArrayExpression) else expr.right
        if isinstance(selected_array, GroupExpression):
            selected_array = selected_array.inner
        if name in ("select", "selectrandom") and isinstance(selected_array, ArrayExpression):
            if name == "selectrandom":
                inferred_items = [
                    _infer_ast_expression(item, variables, function_return_types)
                    for item in selected_array.items
                ]
                item_types = {item_type for item_type in inferred_items if item_type}
                return next(iter(item_types)) if inferred_items and all(item_type == inferred_items[0] for item_type in inferred_items) else None
            if isinstance(expr.right, LiteralExpression) and expr.right.value.type == "number":
                try:
                    index = int(float(expr.right.value.value))
                except ValueError:
                    return None
                if 0 <= index < len(selected_array.items):
                    return _infer_ast_expression(selected_array.items[index], variables, function_return_types)
        if name in _COMMAND_RETURN_TYPES: return _COMMAND_RETURN_TYPES[name]
        if name in _RETURN_TYPES: return _RETURN_TYPES[name]
    if isinstance(expr, CallExpression) and isinstance(expr.target, NameExpression) and function_return_types:
        return function_return_types.get(expr.target.name.value.lower())
    if isinstance(expr, CodeExpression): return "Code"
    return None


def _infer_operand(tokens: list[Token], i: int, variables: dict[str, str]) -> str | None:
    """Infer a simple operand type, including prior literal assignments."""
    if i >= len(tokens):
        return None
    tok = tokens[i]
    # Indexing a position-producing command selects one scalar coordinate.
    # Keep the command's normal Array return type for the unindexed form, but
    # infer the indexed form as Number (for example ``getPosATL _unit # 2``).
    if tok.value.lower() in {"getpos", "getposasl", "getposatl", "getposworld", "getposvisual"}:
        j = i + 1
        while j < len(tokens) and tokens[j].type in _TRIVIA:
            j += 1
        while j < len(tokens) and tokens[j].type not in ("semicolon", "rparen", "rbracket"):
            if tokens[j].value == "#":
                k = j + 1
                while k < len(tokens) and tokens[k].type in _TRIVIA:
                    k += 1
                if k < len(tokens) and tokens[k].type == "number":
                    return "Number"
                break
            j += 1
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
        if tok.value.lower() == "_x":
            # _x is scoped to the active forEach callback; a file-wide pass
            # must not carry an element type from an unrelated loop.
            return None
        inferred = variables.get(tok.value.lower())
        if inferred == "Array":
            # Chained hash indexing (``_records#0#1``) selects a field from a
            # nested record.  The common SQF shape is an array of records
            # whose second field is an engine handle; retain that useful fact
            # for commands such as deleteVehicle without changing plain array
            # indexing semantics.
            hashes = 0
            cursor = i + 1
            while cursor < len(tokens) and hashes < 2:
                if tokens[cursor].value == "#":
                    hashes += 1
                elif tokens[cursor].type not in _TRIVIA and tokens[cursor].type not in ("number",):
                    break
                cursor += 1
            if hashes >= 2:
                return "Object"
            if hashes == 1:
                # A generic array (for example a helper-return record) does
                # not reveal the element type merely from its index.  Keep
                # this unknown rather than treating every element as a
                # Number and producing cascaded handle/type warnings.
                return None
        return inferred
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
    # Collection producers remain arrays when filtered with ``select``.  Do
    # not apply the element type of a producer (for example magazines ->
    # String) to the container variable itself.
    rhs_end = start
    while rhs_end < len(tokens) and tokens[rhs_end].type != "semicolon":
        rhs_end += 1
    # A plain array literal is always an Array.  Check this before inspecting
    # commands embedded in its elements (for example ``[cos 1, -sin 1, 0]``)
    # so an operator inside an element cannot turn the container into Number.
    if start < len(tokens) and tokens[start].type == "lbracket":
        literal_split = _array_items(tokens, start)
        literal_close = literal_split[1] if literal_split else None
        if literal_close is not None:
            after_literal = literal_close + 1
            while after_literal < rhs_end and tokens[after_literal].type in _TRIVIA:
                after_literal += 1
            if after_literal < rhs_end and tokens[after_literal].value.lower() in {"call", "spawn"}:
                return None
            if (after_literal >= rhs_end
                    or tokens[after_literal].value.lower() != "select"):
                return "Array"
    # Parenthesized vector producers commonly have a scalar component
    # selected immediately afterward, e.g. ``(velocityModelSpace _plane)
    # select 1``.  Recognize this shape before the generic grouped-expression
    # fallback so the scalar can be used by vectorMultiply and arithmetic.
    if start < len(tokens) and tokens[start].type == "lparen":
        close_probe = next((idx for idx in range(start + 1, min(rhs_end, len(tokens)))
                            if tokens[idx].type == "rparen"), None)
        if close_probe is not None:
            after = close_probe + 1
            while after < rhs_end and tokens[after].type in _TRIVIA:
                after += 1
            if (after < rhs_end and tokens[after].value.lower() == "select"):
                producer = next((t.value.lower() for t in tokens[start + 1:close_probe]
                                 if t.value.lower() in _ARRAY_ELEMENT_TYPES), None)
                probe = after + 1
                while probe < rhs_end and tokens[probe].type in _TRIVIA:
                    probe += 1
                if producer is not None and probe < rhs_end and tokens[probe].type != "lbrace":
                    return _ARRAY_ELEMENT_TYPES[producer]
            if (after < rhs_end and tokens[after].value.lower() == "select"
                    and after + 1 < rhs_end and tokens[after + 1].type == "number"
                    and any(t.value.lower() in {"velocitymodelspace", "getpos", "getposasl", "getposatl", "getposworld", "getposvisual"}
                            for t in tokens[start + 1:close_probe])):
                return "Number"
    # A code block on the left of ``count`` is the filter form and the
    # command still returns a numeric count.
    if (start < rhs_end and tokens[start].type == "lbrace"
            and any(t.value.lower() == "count" for t in tokens[start:rhs_end])):
        return "Number"
    # Namespace getVariable is a dynamic lookup.  Its return value comes from
    # the default or from runtime state; do not let the namespace receiver's
    # type leak into an assigned callback variable.
    if (start + 1 < rhs_end and tokens[start + 1].value.lower() == "getvariable"):
        if start + 2 < rhs_end and tokens[start + 2].type == "lbracket":
            split = _array_items(tokens, start + 2)
            if split:
                items, _close = split
                if len(items) > 1:
                    default_type = _simple_item_type(items[1], variables)
                    if default_type:
                        return default_type
        return None
    # Binary command chains such as ``_unit getPos [...]`` and
    # ``_position vectorAdd [...]`` produce the command's return type.  The
    # receiver's type alone is not the result of the expression.
    if (start + 1 < rhs_end
            and tokens[start + 1].value.lower() in _COMMAND_RETURN_TYPES
            and tokens[start + 1].value.lower() not in _KNOWN_VARIABLE_TYPES):
        return _COMMAND_RETURN_TYPES[tokens[start + 1].value.lower()]
    if (start < rhs_end and tokens[start].value.lower() == "leader"
            and any(t.value.lower() == "group" for t in tokens[start + 1:rhs_end])):
        return "Object"
    # ``private _p = if (...) then {_a} else {_b}`` is a value expression.
    # Infer it from the two branch values when both are known and compatible.
    if start < len(tokens) and tokens[start].value.lower() == "if":
        branch_types: list[str] = []
        # Only inspect expressions inside the then/else code blocks.  The
        # condition itself is Boolean and must not be mistaken for the value
        # produced by the conditional expression.
        branch_start = next((idx for idx in range(start, rhs_end) if tokens[idx].value.lower() == "then"), None)
        if branch_start is not None:
            for index, token in enumerate(tokens[branch_start + 1:rhs_end], branch_start + 1):
                if token.type == "local":
                    inferred = variables.get(token.value.lower())
                    if inferred and inferred not in branch_types:
                        branch_types.append(inferred)
                elif token.type == "number":
                    branch_types.append("Number")
                elif token.type == "string":
                    branch_types.append("String")
        if len(branch_types) == 1:
            return branch_types[0]
    if (start + 2 < rhs_end and tokens[start + 1].value.lower() == "get"
            and tokens[start + 2].type == "string"):
        # HashMap `get` returns the value stored under a key; the key string is
        # not evidence that the result itself is a String.
        return None
    # HashMap getOrDefault returns its supplied default when the key is
    # absent.  Preserve that default's type so common collection fields can
    # be passed to selectRandom/count without guessing from the key name.
    if (start + 2 < rhs_end and tokens[start + 1].value.lower() == "getordefault"
            and tokens[start + 2].type == "lbracket"):
        split = _array_items(tokens, start + 2)
        if split:
            items, _close = split
            if len(items) > 1:
                default_type = _simple_item_type(items[1], variables)
                if default_type is None:
                    visible_default = [t for t in items[1] if t.type not in _TRIVIA]
                    if visible_default and visible_default[0].type == "lbracket":
                        default_type = "Array"
                if default_type:
                    return default_type
    if any(t.value.lower() == "nearroads" for t in tokens[start:rhs_end]):
        return "Array"
    # Selecting from a literal with homogeneous elements preserves that
    # element type even when the index is dynamic (for example
    # ``[100, 200] select _isHeavy``).
    if start < len(tokens) and tokens[start].type == "lbracket":
        close = next((idx for idx in range(start + 1, rhs_end) if tokens[idx].type == "rbracket"), None)
        if close is not None and any(t.value.lower() == "select" for t in tokens[close + 1:rhs_end]):
            split = _array_items(tokens, start)
            if split:
                items, _close = split
                item_types = [_simple_item_type(item, variables) for item in items]
                if item_types and item_types[0] and all(item_type == item_types[0] for item_type in item_types):
                    return item_types[0]
    if start < len(tokens) and tokens[start].value.lower() in {"getpos", "getposasl", "getposatl", "getposworld", "getposvisual"}:
        # A coordinate selected from a position command is scalar even when
        # the whole expression is wrapped in parentheses.
        for index in range(start + 1, rhs_end - 1):
            if tokens[index].value == "#":
                probe = index + 1
                while probe < rhs_end and tokens[probe].type in _TRIVIA:
                    probe += 1
                if probe < rhs_end and tokens[probe].type == "number":
                    return "Number"
    if (start < len(tokens) and tokens[start].value.lower() in _ARRAY_ELEMENT_TYPES
            and any(t.value.lower() == "select" for t in tokens[start + 1:rhs_end])):
        # Selecting an element from a known collection producer yields the
        # producer's element type.  The old Array result made expressions
        # such as ``units _group select 0`` look like an array when passed to
        # object commands, and likewise lost the scalar component selected
        # from velocityModelSpace.
        select_at = next((idx for idx in range(start + 1, rhs_end)
                          if tokens[idx].value.lower() == "select"), None)
        if select_at is not None:
            probe = select_at + 1
            while probe < rhs_end and tokens[probe].type in _TRIVIA:
                probe += 1
            # ``select { code }`` is the filter form and retains the
            # collection type; only an indexed/element select narrows it.
            if probe < rhs_end and tokens[probe].type == "lbrace":
                return "Array"
        return _ARRAY_ELEMENT_TYPES[tokens[start].value.lower()]
    if any(t.value.lower() in ("createvehicle", "createvehiclelocal") for t in tokens[start:rhs_end]):
        return "Object"
    if any(t.value.lower() in ("weaponcargo", "magazinecargo", "itemcargo") for t in tokens[start:rhs_end]):
        return "Array"
    # A few common command chains have an unambiguous grammar.  Keep this
    # deliberately narrow: scanning every command in a statement would make
    # an earlier producer appear to have the type of a later, unrelated call.
    if (start + 3 < len(tokens)
            and tokens[start].value.lower() == "finddisplay"
            and tokens[start + 1].type == "number"
            and tokens[start + 2].value.lower() == "displayctrl"
            and tokens[start + 3].type == "number"):
        return "Control"
    if (start + 2 < len(tokens)
            and tokens[start].value.lower() == "createhashmap"
            and tokens[start + 1].value.lower() == "get"):
        return "Anything"
    expression_tokens = [t for t in tokens[start:rhs_end] if t.type not in _TRIVIA]
    # Vector command chains produce positions/vectors even when their scalar
    # multiplier contains arithmetic (for example ``vectorAdd (_v vectorMultiply
    # (_speed * diag_deltaTime))``).  Recognize the producer before the
    # generic arithmetic fallback below.
    # Dot products are scalar reductions; keep them ahead of the vector
    # producer family so a nested ``abs ((a vectorDiff b) vectorDotProduct
    # n)`` is inferred as Number rather than inheriting Array from its left
    # vector operand.
    if any(t.value.lower() == "vectordotproduct" for t in expression_tokens):
        return "Number"
    vector_commands = {"vectoradd", "vectordiff", "vectormultiply", "vectornormalized", "vectorcrossproduct"}
    if any(t.value.lower() in vector_commands for t in expression_tokens):
        return "Array"
    if (start < len(tokens) and tokens[start].type == "lparen"
            and any(t.type == "operator" and t.value in ("*", "/", "%") for t in expression_tokens)
            and not any(t.type == "lbracket" for t in expression_tokens)):
        return "Number"
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
                    inner_tokens = [t for t in tokens[start + 1:close] if t.type not in _TRIVIA]
                    if (j < len(tokens) and tokens[j].value.lower() == "select"
                            and j + 1 < len(tokens) and tokens[j + 1].type == "number"):
                        producer = next((t.value.lower() for t in inner_tokens
                                         if t.value.lower() in _ARRAY_ELEMENT_TYPES), None)
                        if producer is not None:
                            return _ARRAY_ELEMENT_TYPES[producer]
                    if (inner == "Array" and j < len(tokens)
                            and tokens[j].value.lower() == "select"):
                        if inner_tokens and (inner_tokens[0].type == "lbracket"
                                or any(t.value.lower() in (_ARRAY_ELEMENT_TYPES.keys() | {"velocitymodelspace", "getpos", "getposasl", "getposatl", "getposworld", "getposvisual"}) for t in inner_tokens)):
                            if j + 1 < len(tokens) and tokens[j + 1].type == "number":
                                producer = next((t.value.lower() for t in inner_tokens
                                                 if t.value.lower() in _ARRAY_ELEMENT_TYPES), None)
                                return _ARRAY_ELEMENT_TYPES.get(producer, "Number")
                            return None
                        return None
                    if j < len(tokens) and tokens[j].value.lower() in _COMMAND_RETURN_TYPES:
                        return _COMMAND_RETURN_TYPES[tokens[j].value.lower()]
                    return inner
    if start < len(tokens) and tokens[start].type == "operator" and tokens[start].value in ("+", "-"):
        # Unary + preserves the operand type (commonly used to copy arrays);
        # unary - is numeric.
        return (_infer_operand(tokens, start + 1, variables)
                if tokens[start].value == "+" else "Number")
    # Arithmetic expressions are numeric even when their operands are
    # composed values such as ``(_sdiff#0) / _div``.  Recognizing this before
    # grouped-expression handling prevents a stale array type from leaking
    # into scalar commands such as vectorMultiply.
    if start < len(tokens) and tokens[start].type == "local":
        call = start + 1
        while call < len(tokens) and tokens[call].type in _TRIVIA:
            call += 1
        if call < len(tokens) and tokens[call].value.lower() == "call":
            target = call + 1
            while target < len(tokens) and tokens[target].type in _TRIVIA:
                target += 1
            if target < len(tokens) and tokens[target].type == "ident":
                return (function_return_types or {}).get(
                    tokens[target].value.lower(),
                    _RETURN_TYPES.get(tokens[target].value.lower()),
                )
    if start < len(tokens) and tokens[start].value.lower() == "selectrandom":
        operand = start + 1
        if operand < len(tokens) and tokens[operand].type == "lbracket":
            split = _array_items(tokens, operand)
            if split:
                items, _ = split
                inferred = [_simple_item_type(item, variables) for item in items]
                if items and inferred[0] is not None and all(item_type == inferred[0] for item_type in inferred):
                    return inferred[0]
    if (start + 1 < len(tokens)
            and tokens[start + 1].value.lower() == "getvariable"):
        default_start = start + 2
        while default_start < len(tokens) and tokens[default_start].type in _TRIVIA:
            default_start += 1
        if default_start < len(tokens) and tokens[default_start].type == "lbracket":
            split = _array_items(tokens, default_start)
            if split:
                items, _close = split
                if len(items) > 1:
                    return _simple_item_type(items[1], variables)
    if start < len(tokens) and tokens[start].value.lower() == "faction":
        # Antistasi's Faction(side) helper shadows the legacy engine command
        # and returns a faction HashMap.  The side form is distinguishable
        # from the engine's object-based ``faction`` command.
        arg = start + 1
        while arg < rhs_end and tokens[arg].type in _TRIVIA:
            arg += 1
        if arg < rhs_end and tokens[arg].type == "lparen":
            arg += 1
            while arg < rhs_end and tokens[arg].type in _TRIVIA:
                arg += 1
        if (arg < rhs_end and (tokens[arg].value.lower() in
                {"west", "east", "resistance", "civilian", "sideunknown"}
                or (tokens[arg].type == "local" and variables.get(tokens[arg].value.lower()) == "Side"))):
            return "HashMap"
    if start < len(tokens) and tokens[start].value.lower() in _COMMAND_RETURN_TYPES:
        # A nular command can be the left operand of a binary command (for
        # example, ``missionNamespace getVariable``). In that form its own
        # return type must not mask the enclosing command's result.
        next_token = start + 1
        while next_token < len(tokens) and tokens[next_token].type in _TRIVIA:
            next_token += 1
        next_value = tokens[next_token].value.lower() if next_token < len(tokens) else ""
        if (next_token >= len(tokens) or tokens[next_token].type != "ident"
                or next_value in _KNOWN_VARIABLE_TYPES
                or next_value not in (_COMMAND_RETURN_TYPES | _BINARY_SIGNATURES | _SIGNATURES | _RETURN_TYPES)):
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
    if operand_end < len(tokens) and tokens[operand_end].value.lower() == "getvariable":
        default_start = operand_end + 1
        while default_start < len(tokens) and tokens[default_start].type in _TRIVIA:
            default_start += 1
        if default_start < len(tokens) and tokens[default_start].type == "lparen":
            depth = 0
            for close in range(default_start, len(tokens)):
                if tokens[close].type == "lparen":
                    depth += 1
                elif tokens[close].type == "rparen":
                    depth -= 1
                    if depth == 0:
                        default_start += 1
                        while default_start < close and tokens[default_start].type in _TRIVIA:
                            default_start += 1
                        break
        if default_start < len(tokens) and tokens[default_start].type == "lbracket":
            split = _array_items(tokens, default_start)
            if split:
                items, _close = split
                if len(items) > 1:
                    return _simple_item_type(items[1], variables)
    if (tokens[start].type != "lbracket"
            and operand_end < len(tokens)
            and tokens[operand_end].value.lower() in _COMMAND_RETURN_TYPES):
        return _COMMAND_RETURN_TYPES[tokens[operand_end].value.lower()]
    direct = _infer_operand(tokens, start, variables)
    # A selected field from a non-literal record has no reliable type without
    # a producer schema; keep it unknown instead of guessing from the record.
    if start < len(tokens) and tokens[start].type == "local":
        command = start + 1
        while command < len(tokens) and tokens[command].type in _TRIVIA: command += 1
        if command < len(tokens) and tokens[command].value.lower() == "select":
            return None
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
    # SQF uses ``array - array`` for array subtraction.  Treat it as an
    # Array-producing operation so wrappers such as
    # ``toString (toArray _text - [34])`` do not inherit numeric arithmetic.
    if direct == "Array":
        op = start + 1
        # Skip the operand of a unary producer such as ``toArray _text``.
        # The subtraction operator follows that operand, rather than sitting
        # immediately after the command name.
        while op < len(tokens) and tokens[op].type not in _TRIVIA and tokens[op].type != "operator":
            op += 1
        while op < len(tokens) and tokens[op].type in _TRIVIA:
            op += 1
        if op < len(tokens) and tokens[op].type == "operator" and tokens[op].value == "-":
            rhs = op + 1
            while rhs < len(tokens) and tokens[rhs].type in _TRIVIA:
                rhs += 1
            if _infer_operand(tokens, rhs, variables) == "Array":
                return "Array"
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
        if j < len(tokens) and tokens[j].type == "keyword" and tokens[j].value.lower() in ("true", "false"):
            item_types = {_simple_item_type(item, variables) for item in _items}
            if len(item_types) == 1:
                return next(iter(item_types))
        if j < len(tokens) and tokens[j].type == "lparen":
            item_types = {_simple_item_type(item, variables) for item in _items}
            if len(item_types) == 1:
                return next(iter(item_types))
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


def _units_loop_element(tokens: list[Token], index: int) -> bool:
    """Whether a local operand is inside a ``forEach units <group>`` body."""
    start = max(0, index - 80)
    window = [t.value.lower() for t in tokens[start:index] if t.type not in _TRIVIA]
    return "foreach" in window and "units" in window


def _config_loop_element(tokens: list[Token], index: int) -> bool:
    """Whether a local is the Config entry of a configClasses loop."""
    start = max(0, index - 100)
    window = [t.value.lower() for t in tokens[start:index] if t.type not in _TRIVIA]
    return "foreach" in window and "configclasses" in window


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


def _collect_foreach_element_types(
    tokens: list[Token], variables: dict[str, str], nodes: list[Node] | None = None
) -> None:
    """Infer loop element types from AST headers and body spans."""
    def collect_body(node: Node, element_type: str) -> None:
        if isinstance(node, Statement):
            for i, token in enumerate(node.tokens[:-2]):
                if element_type != "Unknown" and (token.type == "local" and node.tokens[i + 1].type == "operator"
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
        producer = next((
            t.value.lower() for t in node.header
            if t.type in ("ident", "keyword") and t.value.lower() in _ARRAY_ELEMENT_TYPES
        ), None)
        element_type = _ARRAY_ELEMENT_TYPES.get(producer) if producer else None
        header = node.header
        if len(header) >= 2 and header[0].type == "lparen" and header[-1].type == "rparen":
            header = header[1:-1]
        if element_type is None and header and header[0].type == "lbracket":
            values = [t for t in header[1:-1] if t.type in ("number", "string", "keyword")]
            if values and all(t.type == "number" for t in values):
                element_type = "Number"
            elif values and all(t.type == "string" for t in values):
                element_type = "String"
        if node.body:
            previous_x = variables.get("_x")
            collect_body(node.body, element_type or "Unknown")
            if previous_x is None:
                variables.pop("_x", None)
            else:
                variables["_x"] = previous_x
        if node.body:
            collect_loop(node.body)

    for node in (nodes if nodes is not None else parse(tokens).statements):
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
    if name == "_x":
        return None
    # Common guard form: ``typeName _value == "SCALAR"``.  SQF exposes
    # runtime type names as strings, so map the stable names back to the
    # checker's canonical types inside the guarded expression.
    type_names = {"scalar": "Number", "number": "Number", "bool": "Boolean", "boolean": "Boolean", "string": "String", "array": "Array", "object": "Object", "code": "Code", "config": "Config", "hashmap": "HashMap"}
    for i in range(index - 1, -1, -1):
        if tokens[i].type == "semicolon":
            break
        if (i + 2 < index and tokens[i].value == "!"
                and tokens[i + 1].value.lower() == "isnull"
                and tokens[i + 2].type == "local"
                and tokens[i + 2].value.lower() == name):
            return "Object"
        if (i + 1 < index and tokens[i].value.lower() == "isnull"
                and tokens[i + 1].type == "local"
                and tokens[i + 1].value.lower() == name):
            return "Object"
        if (i + 3 < index and tokens[i].value.lower() == "typename"
                and tokens[i + 1].type == "local" and tokens[i + 1].value.lower() == name
                and tokens[i + 2].type == "operator" and tokens[i + 2].value in ("==", "isequalto")
                and tokens[i + 3].type == "string"):
            return type_names.get(tokens[i + 3].value.lower())
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


def _collect_type_guards(tokens: list[Token], variables: dict[str, str]) -> None:
    """Collect explicit ``isEqualType`` guards for flow-sensitive narrowing."""
    for i in range(len(tokens) - 2):
        if tokens[i].type != "local" or tokens[i + 1].value.lower() != "isequaltype":
            continue
        if tokens[i].value.lower() == "_x":
            continue
        sample = _infer_operand(tokens, i + 2, variables)
        if sample:
            variables[tokens[i].value.lower()] = sample


def _seed_ast_assignments(nodes: list[Node], variables: dict[str, str], function_return_types: dict[str, str] | None) -> None:
    for node in nodes:
        if isinstance(node, Statement):
            for expression in walk_expression(node.expression):
                if isinstance(expression, BinaryExpression) and expression.operator.value == "=" and isinstance(expression.left, NameExpression):
                    inferred = _infer_ast_expression(expression.right, variables, function_return_types)
                    if inferred and expression.left.name.value.lower() not in variables:
                        variables[expression.left.name.value.lower()] = inferred
        for child_name in ("body", "then_block", "else_block", "try_block", "catch_block"):
            child = getattr(node, child_name, None)
            if isinstance(child, Block):
                nested = dict(variables)
                _seed_ast_assignments(child.statements, nested, function_return_types)
            elif isinstance(child, Node):
                nested = dict(variables)
                _seed_ast_assignments([child], nested, function_return_types)


def check_argument_types(
    tokens: list[Token], function_signatures: dict[str, list[str | None]] | None = None,
    function_return_types: dict[str, str] | None = None,
    ast_nodes: list[Node] | None = None,
) -> list[Diagnostic]:
    """Check built-in unary arguments and configured function argument types."""
    diags: list[Diagnostic] = []
    variables: dict[str, str] = {}
    code_locals: set[str] = set()
    conditional_locals: set[str] = set()
    element_types: dict[str, str] = {}
    ast_nodes = ast_nodes if ast_nodes is not None else parse(tokens).statements
    _collect_param_types(tokens, variables)
    _collect_foreach_element_types(tokens, variables, ast_nodes)
    # Collect simple literal assignments. If the same variable is assigned
    # values of different types, forget its type rather than guess.
    for i, tok in enumerate(tokens[:-2]):
        if tok.type != "local" or tokens[i + 1].type != "operator" or tokens[i + 1].value != "=":
            continue
        inferred = _infer_expression(tokens, i + 2, variables, function_return_types)
        key = tok.value.lower()
        if i + 2 < len(tokens) and tokens[i + 2].value.lower() == "if":
            # Branch values may come from unrelated engine handles and cannot
            # be safely collapsed into one static type.
            conditional_locals.add(key)
        if i + 2 < len(tokens) and tokens[i + 2].type == "lbrace":
            code_locals.add(key)
        if (variables.get(key) == "Array"
                and any(t.type == "operator" and t.value == "+"
                        for t in tokens[i + 2: next((k for k in range(i + 2, len(tokens)) if tokens[k].type == "semicolon"), len(tokens))])):
            inferred = "Array"
        if inferred is None:
            variables.pop(key, None)
        else:
            if key not in variables:
                variables[key] = inferred
            elif variables[key] != inferred:
                variables.pop(key, None)
        # Restrict producer detection to this assignment's expression.  The
        # old suffix-wide ``any`` scan revisited the rest of the file for every
        # assignment, making large missions quadratic and incorrectly allowing
        # a producer in a later statement to affect an earlier variable.
        rhs_end = i + 2
        depth = 0
        while rhs_end < len(tokens):
            kind = tokens[rhs_end].type
            if kind in ("lparen", "lbracket", "lbrace"):
                depth += 1
            elif kind in ("rparen", "rbracket", "rbrace"):
                depth = max(0, depth - 1)
            elif kind == "semicolon" and depth == 0:
                break
            rhs_end += 1
        if (inferred == "Number" and variables.get(key) == "Array"
                and any(t.type == "operator" and t.value == "+" for t in tokens[i + 2:rhs_end])):
            inferred = "Array"
        producer_names = {t.value.lower() for t in tokens[i + 2:rhs_end] if t.type in ("ident", "keyword")}
        if i + 4 < len(tokens) and tokens[i + 2].type == "local" and tokens[i + 3].value.lower() == "select" and tokens[i + 4].type == "number":
            if tokens[i + 2].value.lower() in element_types:
                variables[key] = element_types[tokens[i + 2].value.lower()]
    # Re-apply precise loop-element facts after ordinary assignment collection;
    # the loop body may otherwise look like a conflicting global assignment.
    for node in ast_nodes:
        if isinstance(node, Statement) and isinstance(node.expression, BinaryExpression) and node.expression.operator.value == "=":
            left = node.expression.left
            if isinstance(left, NameExpression) and left.name.value.lower() not in variables:
                inferred = _infer_ast_expression(node.expression.right, variables, function_return_types)
                if inferred:
                    variables[left.name.value.lower()] = inferred
    _collect_foreach_element_types(tokens, variables, ast_nodes)
    # `_x` is an implicit loop-local and must never retain a type across
    # unrelated loops in the same file.
    variables.pop("_x", None)
    _collect_type_guards(tokens, variables)
    _seed_ast_assignments(ast_nodes, variables, function_return_types)
    # Infer local parameter types from unambiguous unary command uses before
    # checking binary commands such as HashMap get.
    for i, tok in enumerate(tokens):
        rule = _SIGNATURES.get(tok.value.lower()) if tok.type == "ident" else None
        if rule is None:
            continue
        j = i + 1
        while j < len(tokens) and tokens[j].type in _TRIVIA: j += 1
        if j < len(tokens) and tokens[j].type == "local" and len(rule[0]) == 1:
            variables.setdefault(tokens[j].value.lower(), next(iter(rule[0])))

    for i, tok in enumerate(tokens):
        if tok.type != "ident":
            continue
        rule = _SIGNATURES.get(tok.value.lower())
        if rule is None:
            continue
        # ``{ ... } count ARRAY`` is SQF's filter form.  The code block is
        # the left operand, so the array/group on the right must not be
        # checked against count's unary container contract.
        if tok.value.lower() == "count":
            previous = i - 1
            while previous >= 0 and tokens[previous].type in _TRIVIA:
                previous -= 1
            if previous >= 0 and tokens[previous].type == "rbrace":
                continue
        # ``condition configClasses config`` is the binary filter form; the
        # left condition is not the Config operand described by unary metadata.
        if tok.value.lower() == "configclasses":
            previous = i - 1
            while previous >= 0 and tokens[previous].type in _TRIVIA:
                previous -= 1
            if previous >= 0 and tokens[previous].type in ("string", "keyword", "ident", "local"):
                continue
        j = i + 1
        while j < len(tokens) and tokens[j].type in _TRIVIA:
            j += 1
        if j >= len(tokens):
            continue
        # Marker alpha commands also support the array-encoded form
        # ``[marker, alpha] setMarkerAlphaLocal``.  The XML mirror exposes
        # only the binary form, so do not validate the container itself as the
        # numeric alpha operand.
        if tok.value.lower() in ("setmarkeralpha", "setmarkeralphalocal") and tokens[j].type == "lbracket":
            continue
        if any(t.value.lower() == "select" for t in tokens[j:]):
            continue
        if tokens[j].type == "local" and tokens[j].value.lower() == "_x":
            continue
        if tokens[j].type == "local" and tokens[j].value.lower() in conditional_locals:
            continue
        actual = _narrowed_type(tokens, j, variables) or _infer_operand(tokens, j, variables)
        if (tok.value.lower() == "configname" and tokens[j].type == "local"
                and _config_loop_element(tokens, j)):
            actual = "Config"
        # Antistasi (and other mission frameworks) commonly provide a
        # side-based Faction(side) HashMap helper, which intentionally
        # shadows the legacy engine faction(Object) command.  The side form
        # is handled by the expression inference below and should not emit
        # the engine command's Object-only warning.
        if (tok.value.lower() == "faction" and actual == "Side"):
            continue
        if (tok.value.lower() == "deletevehicle" and tokens[j].type == "local"):
            name = tokens[j].value.lower()
            # A vehicle handle initialized with objNull and then assigned from
            # one or more ``createVehicle`` branches remains an Object even
            # when the branch merge sees the producer's class-name string.
            if any(tokens[k].type == "local" and tokens[k].value.lower() == name
                   and k + 2 < i and tokens[k + 1].value == "="
                   and any(t.value.lower() in ("createvehicle", "createvehiclelocal")
                           for t in tokens[k + 2:i])
                   for k in range(i)):
                continue
            if any(tokens[k].type == "local" and tokens[k].value.lower() == name
                   and k + 2 < i and tokens[k + 1].value.lower() == "isequaltype"
                   and tokens[k + 2].value.lower() == "locationnull"
                   for k in range(i)):
                # The location branch is removed with deleteLocation; this
                # deleteVehicle call is the guarded object fallback.
                continue
        if tok.value.lower() == "alive" and tokens[j].type == "local":
            name = tokens[j].value.lower()
            if any(tokens[k].type == "local" and tokens[k].value.lower() == name
                   and k + 2 < i and tokens[k + 1].value == "="
                   and any(t.value.lower() in ("createvehicle", "createvehiclelocal")
                           for t in tokens[k + 2:i])
                   for k in range(i)):
                continue
        if (tok.value.lower() == "assert" and tokens[j].type == "lparen"
                and any(t.type == "operator" and t.value in ("==", "!=", "<", ">", "<=", ">=")
                        for t in tokens[j:])):
            actual = "Boolean"
        if actual == "Group" and j < len(tokens) and tokens[j].type == "local" and _units_loop_element(tokens, j):
            actual = "Object"
        accepted, expected = rule
        if actual is not None and actual != "Anything" and not all(member in accepted for member in actual.split("|")):
            if (tok.value.lower() in ("ctrldelete", "ctrlshown", "ctrlposition") and actual == "Object"
                    and any(t.value.lower() in ("controlnull", "ctrlcreate", "displayctrl") for t in tokens[:i])):
                continue
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
        if any(t.value.lower() == "select" for t in tokens[j:]):
            continue
        if tok.value.lower() == "camsetfov" and tokens[j].type in ("lbracket", "lparen"):
            # A callback result such as ``[args] call fnc_getFov`` is dynamic;
            # the argument array itself is not the numeric FOV value.
            split = _array_items(tokens, j) if tokens[j].type == "lbracket" else None
            if split:
                _items, close = split
                k = close + 1
                while k < len(tokens) and tokens[k].type in _TRIVIA:
                    k += 1
                if k < len(tokens) and tokens[k].value.lower() in ("call", "spawn"):
                    continue
            if tokens[j].type == "lparen" and any(t.value.lower() == "call" for t in tokens[j:]):
                continue
        if j < len(tokens) and tokens[j].type == "local" and tokens[j].value.lower() in conditional_locals:
            continue
        actual = _infer_operand(tokens, j, variables)
        if tok.value.lower() == "domove" and tokens[j].type == "local":
            name = tokens[j].value.lower()
            if any(tokens[k].type == "local" and tokens[k].value.lower() == name
                   and k + 1 < i and tokens[k + 1].value.lower() == "="
                   and any(t.value.lower() in ("getpos", "getposasl", "getposatl", "getposworld", "getposvisual")
                           for t in tokens[k + 2:i])
                   for k in range(i)):
                continue
        if (tok.value.lower() == "distance2d" and tokens[j].type == "local"):
            name = tokens[j].value.lower()
            if any(tokens[k].type == "local" and tokens[k].value.lower() == name
                   and k + 2 < i and tokens[k + 1].value.lower() == "isequaltype"
                   for k in range(i)):
                # Flow-sensitive conversion (for example String marker ->
                # markerPos Array) makes the local's raw declaration type
                # unsuitable for this later call.
                continue
        accepted, expected = rule
        # HashMap deleteAt uses a string key, while Array deleteAt uses a
        # numeric index.  The generated command metadata only describes the
        # Array form, so accept the documented HashMap overload when the left
        # operand is known to be a HashMap.
        if tok.value.lower() == "deleteat" and actual == "String":
            # The engine overloads deleteAt for HashMap string keys.  When
            # the container is dynamic (as it commonly is across namespace
            # boundaries), its type cannot be proven from the call site.
            continue
        if actual is not None and actual != "Anything" and actual not in accepted:
            diags.append(Diagnostic(Severity.WARNING, _CODE, f"{tok.value} expects {expected}, got {actual}", tokens[j].line, tokens[j].column))

    # A statically known non-code value cannot be used as a call/spawn target.
    # SQF also permits string targets, so those remain valid here.
    for i, tok in enumerate(tokens):
        if tok.type != "keyword" or tok.value.lower() not in ("call", "spawn"):
            continue
        j = i + 1
        while j < len(tokens) and tokens[j].type in _TRIVIA:
            j += 1
        if j < len(tokens) and tokens[j].type == "local":
            actual = variables.get(tokens[j].value.lower())
            if actual and actual not in ("Code", "String") and tokens[j].value.lower() not in code_locals:
                diags.append(Diagnostic(
                    Severity.WARNING, _CALL_TARGET_CODE,
                    f"{tok.value} expects Code or String, got {actual}",
                    tokens[j].line, tokens[j].column,
                ))
        elif j < len(tokens) and tokens[j].type in ("number", "keyword"):
            actual = _infer_operand(tokens, j, variables)
            if actual and actual not in ("Code", "String"):
                diags.append(Diagnostic(
                    Severity.WARNING, _CALL_TARGET_CODE,
                    f"{tok.value} expects Code or String, got {actual}",
                    tokens[j].line, tokens[j].column,
                ))

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

    # Warn only for primitive comparisons whose operands are both known and
    # have incompatible types. Unknown/dynamic values remain unchecked.
    for i, tok in enumerate(tokens):
        if tok.type != "operator" or tok.value not in ("==", "!=", "<", ">", "<=", ">="):
            continue
        # Config path traversal uses the lexical token pair ``>>``.  The
        # tokenizer exposes each ``>`` separately, but neither is a numeric
        # comparison operator in that context.
        if tok.value == ">" and (
            (i > 0 and tokens[i - 1].value == ">")
            or (i + 1 < len(tokens) and tokens[i + 1].value == ">")
        ):
            continue
        # A comparison applied to a config path expression (``configFile >>
        # ... > 5``) can otherwise be confused with one of the path's `>`
        # tokens after preprocessing.  Treat the complete config traversal as
        # opaque for impossible-comparison analysis.
        if tok.value in ("<", ">", "<=", ">="):
            window = tokens[max(0, i - 48):min(len(tokens), i + 16)]
            if (any(a.value == ">" and b.value == ">" for a, b in zip(window, window[1:]))
                    or any(a.value.lower() == "configfile" for a in window)
                    or any(a.value.lower() in ("gettext", "getnumber") for a in window)):
                continue
        left = i - 1
        while left >= 0 and tokens[left].type in _TRIVIA: left -= 1
        right = i + 1
        while right < len(tokens) and tokens[right].type in _TRIVIA: right += 1
        actual_left = _infer_operand(tokens, left, variables) if left >= 0 else None
        actual_right = _infer_operand(tokens, right, variables) if right < len(tokens) else None
        # In ``array select 0 == value`` the immediate token before the
        # comparison is the numeric index, not the selected element.  The
        # element type is producer-dependent, so leave this comparison
        # unknown rather than reporting Number vs String.
        if left >= 0 and tokens[left].type == "number":
            prior = left - 1
            while prior >= 0 and tokens[prior].type in _TRIVIA:
                prior -= 1
            if prior >= 0 and tokens[prior].value.lower() in ("select", "#"):
                actual_left = None
        primitive = {"Number", "String", "Boolean"}
        # Infix commands such as `find` return a number, but the immediate
        # token before the comparison is their string argument. Do not compare
        # that argument's type; the command expression is the left operand.
        command_result_comparison = (
            left >= 1 and tokens[left - 1].value.lower() in ("find", "findif", "count", "inputaction", "getvariable", "gettext", "getnumber", "distance", "distance2d", "distancesqr")
        )
        if not command_result_comparison:
            scan = left - 1
            while scan >= 0 and tokens[scan].type != "semicolon" and left - scan <= 96:
                if tokens[scan].value.lower() in ("count", "find", "findif", "inputaction", "getvariable", "gettext", "getnumber", "distance", "distance2d", "distancesqr"):
                    command_result_comparison = True
                    break
                scan -= 1
        if not command_result_comparison:
            # Config accessors can appear on the right side of a comparison
            # (for example ``"gl" == getText (...)``).  Their return type is
            # already authoritative; do not compare an inner config argument
            # against the literal on the other side.
            scan = i + 1
            while scan < len(tokens) and tokens[scan].type != "semicolon" and scan - i <= 96:
                if tokens[scan].value.lower() in ("gettext", "getnumber"):
                    command_result_comparison = True
                    break
                scan += 1
        # A local may be reused by separate functions in one file. If an
        # earlier assignment of that local is a `findIf` producer, do not let
        # the stale type from another function make this numeric result look
        # Boolean.
        if left >= 0 and tokens[left].type == "local":
            name = tokens[left].value.lower()
            cursor = 0
            while cursor < i:
                if (tokens[cursor].type == "local"
                        and tokens[cursor].value.lower() == name):
                    assign = cursor + 1
                    while assign < i and tokens[assign].type in _TRIVIA:
                        assign += 1
                    if assign < i and tokens[assign].value == "=":
                        end = assign + 1
                        while end < i and tokens[end].type != "semicolon":
                            if tokens[end].value.lower() in ("findif", "find", "count", "inputaction"):
                                command_result_comparison = True
                                if tokens[end].value.lower() in ("findif", "find", "count", "inputaction"):
                                    actual_left = "Number"
                                break
                            end += 1
                cursor += 1
            # Prefer an unambiguous local initializer immediately preceding
            # this comparison over a stale type collected from another
            # function in the same file.
            for cursor in range(i - 1, max(-1, i - 160), -1):
                if tokens[cursor].type != "local" or tokens[cursor].value.lower() != name:
                    continue
                assign = cursor + 1
                while assign < i and tokens[assign].type in _TRIVIA:
                    assign += 1
                if assign >= i or tokens[assign].value != "=":
                    continue
                value = assign + 1
                while value < i and tokens[value].type in _TRIVIA:
                    value += 1
                if value < i and tokens[value].type == "number":
                    actual_left = "Number"
                elif value < i and tokens[value].type == "string":
                    actual_left = "String"
                elif value < i and tokens[value].type == "keyword" and tokens[value].value.lower() in ("true", "false"):
                    actual_left = "Boolean"
                else:
                    # An assignment from an unknown global or macro value is
                    # not evidence of the previous inferred type.  Keeping a
                    # stale Boolean/Number here creates false comparisons in
                    # code that receives strings from dialog/config state.
                    actual_left = None
                break
        # typeName returns a string describing the operand, so comparing it
        # with a string literal is intentional even though the underlying
        # operand may have a different inferred type.
        type_name_comparison = (
            left >= 1
            and tokens[left].type == "local"
            and tokens[left - 1].value.lower() == "typename"
        )
        local_literal_type = True
        if left >= 0 and tokens[left].type == "local":
            # A file-wide inferred type is too weak for locals populated from
            # dialog/config/global state.  Only issue impossible-comparison
            # warnings for locals with a nearby literal assignment proving
            # their primitive type; this avoids Boolean/String and
            # Number/String cascades from unrelated scopes.
            local_literal_type = False
            name = tokens[left].value.lower()
            cursor = left - 1
            distance = 0
            while cursor >= 0 and distance < 160:
                if (tokens[cursor].type == "local" and tokens[cursor].value.lower() == name):
                    assign = cursor + 1
                    while assign < left and tokens[assign].type in _TRIVIA:
                        assign += 1
                    if assign < left and tokens[assign].value == "=":
                        value = assign + 1
                        while value < left and tokens[value].type in _TRIVIA:
                            value += 1
                        if value < left and tokens[value].type in ("number", "string"):
                            local_literal_type = True
                        elif (value < left and tokens[value].type == "keyword"
                              and tokens[value].value.lower() in ("true", "false")):
                            local_literal_type = True
                        break
                cursor -= 1
                distance += 1
        if (local_literal_type and not type_name_comparison and not command_result_comparison
                and actual_left in primitive and actual_right in primitive
                and actual_left != actual_right):
            diags.append(Diagnostic(Severity.WARNING, _COMPARISON_CODE, f"comparison cannot match {actual_left} with {actual_right}", tok.line, tok.column))
    return diags


def check_argument_types_text(source: str) -> list[Diagnostic]:
    return check_argument_types(tokenize(source))


if __name__ == "__main__":
    assert check_argument_types_text('hint "hello"; sleep 1;') == []
    assert check_argument_types_text('hint 42;')[0].code == _CODE
    assert check_argument_types_text('sleep "soon";')[0].message.endswith("got String")
    assert check_argument_types_text('hint [parseText "hello"];') == []
    assert check_argument_types_text('sleep _delay;') == []
    assert check_argument_types_text('sleep getPosATL player # 2;') == []
    assert check_argument_types_text('systemChat 42;')[0].message.endswith("got Number")
    assert check_argument_types_text('uiSleep "soon";')[0].code == _CODE
    assert check_argument_types_text('count "abc";') == []
    assert check_argument_types_text('isNil { true };') == []
    assert check_argument_types_text('{ true } count [];') == []
    assert check_argument_types_text('count true;')[0].code == _CODE
    assert check_argument_types_text('count configFile; count createHashMap;') == []
    assert check_argument_types_text('sqrt "x";')[0].code == _CODE
    assert check_argument_types_text('toLower 42;')[0].code == _CODE
    assert check_argument_types_text('selectRandom "not an array";')[0].code == _CODE
    assert check_argument_types_text('private _smokeMags = magazines _unit select { true }; selectRandom _smokeMags;') == []
    assert check_argument_types_text('private _fnc_exit = { false; }; call _fnc_exit;') == []
    assert check_argument_types_text('private _itemType = _x call BIS_fnc_itemType; _itemType select 0 == "Mine";') == []
    assert check_argument_types_text('getPos [0, 0, 0];') == []
    assert check_argument_types_text('objNull isKindOf ["CBA_MiscItem", configFile];') == []
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
    assert check_argument_types_text('_aimDir = player weaponDirection "rifle"; _desiredDir = [0,0,0] vectorFromTo [1,0,0]; acos (_aimDir vectorCos _desiredDir);') == []
    bad_hash_key = check_argument_types_text('params ["_road"]; private _cache = createHashMap; _cached = _cache get _road; _info = getRoadInfo _road;')
    assert any(item.code == _CODE and "get expects" in item.message for item in bad_hash_key), bad_hash_key
    assert check_argument_types_text('private _state = "run"; allowDamage (_state in ["run", "freeflight"]);') == []
    assert check_argument_types_text('{ sin _x; cos _x; } forEach [18, 15];') == []
    assert check_argument_types_text('{ sin _x; cos _x; } forEach ([18, 15]);') == []
    assert check_argument_types_text('if (_value isEqualType []) then { count _value; };') == []
    assert check_argument_types_text('_flag = not true; allowDamage _flag;') == []
    assert check_argument_types_text('{ count _x; } forEach (fullCrew player);') == []
    assert check_argument_types_text('{ getRoadInfo _x; } forEach (roadsConnectedTo player);') == []
    assert check_argument_types_text('_v = [1,0,0] vectorAdd [0,1,0]; _d = _v vectorDotProduct [1,1,0]; acos (_d);') == []
    assert check_argument_types_text('_n = (1 max 0); sleep _n;') == []
    assert check_argument_types_text('_items = [1]; _item = _items select 0; sleep _item;') == []
    assert check_argument_types_text('_delay = missionNamespace getVariable ["delay", 1]; sleep _delay;') == []
    assert check_argument_types_text('_delay = missionNamespace getVariable ["delay", "soon"]; sleep _delay;')[0].code == _CODE
    assert check_argument_types_text('_delay = getVariable ["delay", 1]; sleep _delay;') == []
    assert check_argument_types_text('_nearest = []; { _nearest = _x; } forEach ([0, 0, 0] nearRoads 10); count _nearest;')[0].code == _CODE
    assert check_argument_types_text('_unit = objNull; { _unit = _x; } forEach allUnits; count _unit;')[0].code == _CODE
    assert check_argument_types_text('_thing = objNull; { _thing = _x; } forEach allDead; count _thing;')[0].code == _CODE
    assert check_argument_types_text('_allPlayers = ["a"]; { _item = _x; } forEach _allPlayers; count _item;') == []
    assert check_argument_types_text('_thing = 0; { _thing = _x; } forEach (nearestObjects [player, ["Car"], 50]); count _thing;')[0].code == _CODE
    assert check_argument_types_text('_thing = 0; { _thing = _x; } forEach (player nearObjects 50); count _thing;')[0].code == _CODE
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
    assert check_argument_types_text('_map = createHashMap; _map deleteAt "key";') == []
    assert check_argument_types_text('_alpha = if (true) then {0.75} else {1}; ["m", _alpha] setMarkerAlphaLocal;') == []
    assert check_argument_types_text('_value = 1; if (typeName _value == "SCALAR") then { sleep _value; };') == []
    assert any(item.code == _COMPARISON_CODE for item in check_argument_types_text('_n = 1; _n == "one";'))
    assert check_argument_types_text('_items = ["x"]; _items # 0 == "x";') == []
    assert check_argument_types_text('getText (configFile >> "Cfg") == "x";') == []
    assert check_argument_types_text('getNumber (configFile >> "Cfg") > 5;') == []
    assert check_argument_types_text('if ((toLower _x) find "auto" >= 0) then {};') == []
    assert check_argument_types_text('if (inputAction "zoomIn" > 0) then {};') == []
    assert check_argument_types_text('_n = { true } count []; if (_n > 0) then {};') == []
    assert check_argument_types_text('_d = findDisplay 46; _c = _d displayCtrl 1; isNull _c;') == []
    assert check_argument_types_text('_positions = [1]; private _remaining = +_positions; count _remaining;') == []
    assert check_argument_types_text('private _text = "abc"; private _clean = toString (toArray _text - [34]);') == []
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
