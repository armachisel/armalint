"""Focused parser and semantic analysis cases counted by the aggregate runner."""

from __future__ import annotations

from armalint.argument_types import check_argument_types_text
from armalint.ast import Block, LoopStatement, TryCatchStatement, parse
from armalint.control_flow import check_control_flow_text
from armalint.suppression import filter_suppressed
from armalint.undefined import check_undefined_text
from armalint.diagnostic import Diagnostic, Severity


def _ast_wait_until() -> bool:
    node = parse("waitUntil { _ready; };").statements[0]
    return isinstance(node, LoopStatement) and node.kind == "waituntil" and node.body is not None


def _ast_try_catch() -> bool:
    node = parse("try { hint str _x; } catch { hint str _exception; };").statements[0]
    return isinstance(node, TryCatchStatement) and node.try_block is not None and node.catch_block is not None


def _ast_spawn_block() -> bool:
    node = parse("spawn { hint str _missing; };").statements[0]
    return bool(getattr(node, "embedded", None)) and isinstance(node.embedded[0], Block)


def _control_flow_spawn() -> bool:
    diagnostics = check_control_flow_text('spawn { exitWith {}; hint "never"; };')
    return len([item for item in diagnostics if item.code == "W104"]) == 1


def _control_flow_try() -> bool:
    diagnostics = check_control_flow_text('try { exitWith {}; } catch { throw 1; }; hint "never";')
    return len([item for item in diagnostics if item.code == "W104"]) == 1


def _undefined_wait_until() -> bool:
    diagnostics = check_undefined_text("waitUntil { hint str _ready; };")
    return len(diagnostics) == 1 and "_ready" in diagnostics[0].message


def _undefined_try_branch() -> bool:
    diagnostics = check_undefined_text("try { _tryValue = 1; } catch { _catchValue = 2; }; hint str _tryValue;")
    return any("_tryValue" in item.message for item in diagnostics)


def _types_config_hashmap() -> bool:
    return check_argument_types_text("count configFile; count createHashMap;") == []


def _types_near_roads() -> bool:
    diagnostics = check_argument_types_text("_items = []; { _items = _x; } forEach ([0,0,0] nearRoads 10); count _items;")
    return any(item.code == "W203" for item in diagnostics)


def _types_engine_object_collection() -> bool:
    diagnostics = check_argument_types_text("_value = 0; { _value = _x; } forEach allDead; count _value;")
    return any(item.code == "W203" for item in diagnostics)


def _types_local_array_named_like_collection() -> bool:
    return check_argument_types_text('_allPlayers = ["a"]; { _item = _x; } forEach _allPlayers; count _item;') == []


def _types_nearest_objects() -> bool:
    diagnostics = check_argument_types_text('_value = 0; { _value = _x; } forEach (nearestObjects [player, ["Car"], 50]); count _value;')
    return any(item.code == "W203" for item in diagnostics)


def _types_near_entities() -> bool:
    diagnostics = check_argument_types_text('_value = 0; { _value = _x; } forEach (player nearEntities 50); count _value;')
    return any(item.code == "W203" for item in diagnostics)


def _types_common_object_collections() -> bool:
    samples = (
        "allAir", "allLand", "allMan", "allStaticObjects", "allStaticWeapons",
        "crew player", "units group player",
    )
    for producer in samples:
        source = f'_value = 0; {{ _value = _x; }} forEach {producer}; count _value;'
        if not any(item.code == "W203" for item in check_argument_types_text(source)):
            return False
    return True


def _suppression_multi_code() -> bool:
    source = "// armalint: disable-next-line W206 W101\nif (true) then {};"
    diagnostics = [
        Diagnostic(Severity.WARNING, "W206", "constant", 2, 1),
        Diagnostic(Severity.WARNING, "W101", "undefined", 2, 1),
    ]
    return filter_suppressed(diagnostics, source) == []


CASES = (
    ("AST waitUntil node", _ast_wait_until),
    ("AST try/catch node", _ast_try_catch),
    ("AST embedded spawn block", _ast_spawn_block),
    ("unreachable code in spawn", _control_flow_spawn),
    ("terminating try/catch branches", _control_flow_try),
    ("undefined variable in waitUntil", _undefined_wait_until),
    ("try/catch definition merge", _undefined_try_branch),
    ("Config and HashMap type inference", _types_config_hashmap),
    ("object array loop type inference", _types_near_roads),
    ("engine object collection inference", _types_engine_object_collection),
    ("local array is not engine collection", _types_local_array_named_like_collection),
    ("nearest object collection inference", _types_nearest_objects),
    ("near entity collection inference", _types_near_entities),
    ("common object collection inference", _types_common_object_collections),
    ("multi-code suppression", _suppression_multi_code),
)


if __name__ == "__main__":
    failures = [name for name, case in CASES if not case()]
    if failures:
        raise SystemExit("failed: " + ", ".join(failures))
    print(f"analysis cases: {len(CASES)}/{len(CASES)} passed")
