"""Focused parser and semantic analysis cases counted by the aggregate runner."""

from __future__ import annotations

import json
from pathlib import Path

from armalint.argument_types import check_argument_types_text
from armalint.argument_types import _BINARY_SIGNATURES, _COMMAND_ARITIES, _SIGNATURES
from armalint.ast import BinaryExpression, Block, CallExpression, CommandExpression, GroupExpression, LoopStatement, TerminatorStatement, TryCatchStatement, parse, parse_expression, walk_expression
from armalint.tokenizer import tokenize
from armalint.control_flow import check_control_flow_text
from armalint.definitions import check_definitions_text
from armalint.suppression import filter_suppressed
from armalint.syntax import check_syntax
from armalint.update_commands import _metadata_return_type, _parse_command_xml
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


def _ast_terminator_node() -> bool:
    node = parse('breakOut "scope";').statements[0]
    return isinstance(node, TerminatorStatement) and node.command == "breakout"


def _ast_nested_spawn_expression() -> bool:
    node = parse('_handle = spawn { _result = 1 + 2; };').statements[0]
    expr = getattr(node, "expression", None)
    return bool(expr and isinstance(getattr(expr, "right", None), CallExpression))


def _ast_expression_walker() -> bool:
    node = parse('_handle = spawn { _result = 1 + 2; };').statements[0]
    names = list(walk_expression(getattr(node, "expression", None)))
    return len(names) >= 5 and any(isinstance(item, BinaryExpression) for item in names)


def _ast_chained_command_expression() -> bool:
    node = parse('player setPosASL [0, 0, 0];').statements[0]
    return bool(getattr(node, "expression", None) and len(list(walk_expression(node.expression))) >= 3)


def _ast_unary_command_expression() -> bool:
    node = parse('count [1, 2];').statements[0]
    expr = getattr(node, "expression", None)
    return isinstance(expr, CommandExpression) and expr.left is None and expr.command.value.lower() == "count"


def _ast_select_element_type() -> bool:
    diagnostics = check_argument_types_text('_value = [1, "x"] select 0; allowDamage _value;')
    return any(d.code == "W203" and "allowDamage" in d.message for d in diagnostics)


def _ast_select_random_element_type() -> bool:
    diagnostics = check_argument_types_text('_value = selectRandom [1, 2]; allowDamage _value;')
    return any(d.code == "W203" and "allowDamage" in d.message for d in diagnostics)


def _ast_text_prefix_command() -> bool:
    node = parse('_text = str 42;').statements[0]
    expr = getattr(node, "expression", None)
    return isinstance(expr, BinaryExpression) and isinstance(expr.right, CommandExpression) and expr.right.left is None


def _ast_group_expression_span() -> bool:
    node = parse('_value = (1 + 2);').statements[0]
    expr = getattr(node, "expression", None)
    return isinstance(expr, BinaryExpression) and isinstance(expr.right, GroupExpression) and expr.right.start.type == "lparen" and expr.right.end.type == "rparen"


def _ast_walker_structured_conditions() -> bool:
    node = parse('_fn = { if (1 == 1) then { hint "ok"; }; };').statements[0]
    expr = getattr(node, "expression", None)
    return expr is not None and any(isinstance(item, BinaryExpression) and item.operator.value == "==" for item in walk_expression(expr))


def _ast_switch_case_condition() -> bool:
    node = parse('switch (_value) do { case 1 == 1: { hint "ok"; }; };').statements[0]
    case = getattr(node, "cases", [None])[0]
    return case is not None and isinstance(getattr(case, "condition_ast", None), BinaryExpression)


def _switch_case_select_random_type() -> bool:
    diagnostics = check_argument_types_text('switch (1) do { case 1: { _value = selectRandom [1, 2]; allowDamage _value; }; };')
    return any(d.code == "W203" and "allowDamage" in d.message for d in diagnostics)


def _ast_grouped_select_type() -> bool:
    diagnostics = check_argument_types_text('_value = ([1, 2]) select 0; allowDamage _value;')
    return any(d.code == "W203" and "allowDamage" in d.message for d in diagnostics)


def _ast_namespace_default_type() -> bool:
    diagnostics = check_argument_types_text('_value = missionNamespace getVariable ["flag", 1]; allowDamage _value;')
    return any(d.code == "W203" and "allowDamage" in d.message for d in diagnostics)


def _ast_grouped_namespace_default_type() -> bool:
    diagnostics = check_argument_types_text('_value = missionNamespace getVariable (["flag", 1]); allowDamage _value;')
    return any(d.code == "W203" and "allowDamage" in d.message for d in diagnostics)


def _non_code_call_target() -> bool:
    diagnostics = check_argument_types_text('_value = 1; call _value;')
    return any(d.code == "W205" and "call" in d.message for d in diagnostics)


def _literal_non_code_call_target() -> bool:
    diagnostics = check_argument_types_text('call 1; spawn false;')
    return len([d for d in diagnostics if d.code == "W205"]) == 2


def _ast_statement_boundary() -> bool:
    diagnostics = check_syntax(tokenize('if (true) then {} hint 1;'))
    return len([d for d in diagnostics if d.code == "E008"]) == 1


def _expanded_builtin_signatures() -> bool:
    diagnostics = check_argument_types_text('alive 1; _name = name player; count _name;')
    return any(d.code == "W203" and "alive" in d.message for d in diagnostics) and not any(d.code == "W203" and "count" in d.message for d in diagnostics)


def _nular_collection_returns() -> bool:
    diagnostics = check_argument_types_text('_players = allPlayers; count _players; _units = allUnits; count _units;')
    return not any(d.code == "W203" for d in diagnostics)


def _config_builtin_signatures() -> bool:
    diagnostics = check_argument_types_text('configName 1; _classes = configClasses configFile; count _classes;')
    return any(d.code == "W203" and "configName" in d.message for d in diagnostics) and not any(d.code == "W203" and "count" in d.message for d in diagnostics)


def _object_constructor_returns() -> bool:
    diagnostics = check_argument_types_text('_object = "SomeClass" createVehicleLocal [0, 0, 0]; isNull _object;')
    return not any(d.code == "W203" and "isNull" in d.message for d in diagnostics)


def _camera_and_config_returns() -> bool:
    source = '_cam = "camera" camCreate [0, 0, 0]; isNull _cam; _classes = "scope >= 2" configClasses (configFile >> "CfgVehicles"); count _classes;'
    diagnostics = check_argument_types_text(source)
    return not any(d.code == "W203" and ("isNull" in d.message or "configClasses" in d.message) for d in diagnostics)


def _object_producer_returns() -> bool:
    source = '_a = objectFromNetId "1:2"; isNull _a; _b = cameraOn; isNull _b; _c = nearestObject [player, "Car"]; isNull _c;'
    diagnostics = check_argument_types_text(source)
    return not any(d.code == "W203" and "isNull" in d.message for d in diagnostics)


def _extended_object_producer_returns() -> bool:
    source = '_a = effectiveDriver player; isNull _a; _b = assignedGunner player; isNull _b; _c = cursorObject; isNull _c;'
    diagnostics = check_argument_types_text(source)
    return not any(d.code == "W203" and "isNull" in d.message for d in diagnostics)


def _isnull_accepts_engine_handles() -> bool:
    source = 'private _display = findDisplay 46; private _control = findDisplay 46 displayCtrl 1; isNull _display; isNull _control;'
    return not any(d.code == "W203" and "isNull" in d.message for d in check_argument_types_text(source))


def _in_checks_right_array_operand() -> bool:
    diagnostics = check_argument_types_text('{ if !(_x in (assignedItems player)) then {}; } forEach ["NVGoggles", "ItemMap"];')
    return not any(d.code == "W203" and " in " in d.message for d in diagnostics)


def _definition_overwrite_checks() -> bool:
    duplicate = check_definitions_text('ALT_fnc_a = {}; ALT_fnc_a = {};')
    overwrite = check_definitions_text('ALT_fnc_a = {}; ALT_fnc_a = 1;')
    local = check_definitions_text('private _fn = {}; _value = 1;')
    callback = check_definitions_text('ALT_callback = {}; ALT_callback = false;')
    invoked_callback = check_definitions_text('[1] call ALT_callback; ALT_callback = {}; ALT_callback = false;')
    return duplicate and duplicate[0].code == "W207" and overwrite and overwrite[0].code == "W208" and not local and not callback and invoked_callback and invoked_callback[0].code == "W208"


def _postfix_command_syntax() -> bool:
    from armalint.syntax import check_syntax_text
    bad = check_syntax_text('_nodeIds reverse;')
    good = check_syntax_text('_nodeIds = reverse _nodeIds;')
    return any(item.code == "E009" for item in bad) and not any(item.code == "E009" for item in good)


def _missing_semicolon_after_apply() -> bool:
    from armalint.syntax import check_syntax_text
    missing = check_syntax_text('_nodeIds apply { _x } _next = 1;')
    valid = check_syntax_text('_nodeIds apply { _x }\n};')
    return any(item.code == "E008" for item in missing) and not any(item.code == "E008" for item in valid)


def _generated_signature_forms() -> bool:
    unary = _SIGNATURES.get("finddisplay")
    binary = _BINARY_SIGNATURES.get("setposasl")
    return (
        unary is not None and "Number" in unary[0]
        and binary is not None and "Array" in binary[0]
        and _COMMAND_ARITIES.get("finddisplay") == frozenset({1})
        and 2 in _COMMAND_ARITIES.get("setposasl", frozenset())
    )


def _ui_and_array_encoded_commands_stay_unchecked() -> bool:
    source = 'private _d = findDisplay 46; _d setVariable ["x", 1]; private _c = _d ctrlCreate ["RscText", 1]; _c ctrlSetPosition [0, 0, 1, 1]; _c ctrlCommit 0; private _v = _d getVariable ["x", 0]; sleep _v;'
    return not any(d.code == "W203" for d in check_argument_types_text(source))


def _engine_array_operand_commands() -> bool:
    source = '"ext" callExtension ["arm", ["x"]]; private _a = [0, 0, 0]; private _b = [1, 1, 1]; _a distance _b; private _cam = "camera" camCreate [0, 0, 0]; _cam camSetFov ([getPosASL player, [0, 0, 0]] call ALT_fnc_fov); private _names = allVariables player;'
    return not any(d.code == "W203" for d in check_argument_types_text(source))


def _extension_distance_and_ui_handles() -> bool:
    source = '"ext" callExtension ["arm", ["x"]]; private _a = [0, 0, 0]; private _b = [1, 1, 1]; _a distance _b; private _cam = "camera" camCreate [0, 0, 0]; _cam camSetFov ([getPosASL player, _b] call ALT_fnc_fov); private _names = allVariables player;'
    return not any(d.code == "W203" for d in check_argument_types_text(source))


def _command_xml_metadata_parser() -> bool:
    xml = """<command name='fake' version='1.70' game='arma3' format='1'><syntax><return><value type='OBJECT' order='0'/></return><param type='STRING' name='id' optional='f' order='1'/></syntax></command>"""
    metadata = _parse_command_xml(xml)
    return metadata["name"] == "fake" and metadata["game"] == "arma3" and _metadata_return_type(metadata) == "Object"


def _vendored_command_metadata_snapshot() -> bool:
    path = Path(__file__).resolve().parents[1] / "armalint" / "data" / "command_metadata.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    commands = payload.get("commands", {})
    return payload.get("schema") == 1 and isinstance(commands, dict) and len(commands) >= 2000


def _hashmap_foreach_value_scope() -> bool:
    from armalint.undefined import check_undefined_text
    return not any(d.code == "W101" and "_y" in d.message for d in check_undefined_text('{ hint str _y; } forEach _map;'))


def _ast_malformed_expression_recovery() -> bool:
    return parse_expression(tokenize('[1,')) is None


def _control_flow_spawn() -> bool:
    diagnostics = check_control_flow_text('spawn { exitWith {}; hint "never"; };')
    return len([item for item in diagnostics if item.code == "W104"]) == 1


def _control_flow_try() -> bool:
    diagnostics = check_control_flow_text('try { exitWith {}; } catch { throw 1; }; hint "never";')
    return len([item for item in diagnostics if item.code == "W104"]) == 1


def _control_flow_terminators() -> bool:
    for source in (
        'breakOut "scope"; hint "never";',
        'breakTo "scope"; hint "never";',
        'continue; hint "never";',
    ):
        if len([item for item in check_control_flow_text(source) if item.code == "W104"]) != 1:
            return False
    return True


def _control_flow_nested_else_if() -> bool:
    source = 'if (_a) then { exitWith {}; } else if (_b) then { throw 1; } else { breakOut "scope"; }; hint "never";'
    return len([item for item in check_control_flow_text(source) if item.code == "W104"]) == 1


def _constant_negated_condition() -> bool:
    diagnostics = check_control_flow_text('if (!true) then { hint "never"; };')
    return len([item for item in diagnostics if item.code == "W206"]) == 1


def _constant_comparison_condition() -> bool:
    diagnostics = check_control_flow_text('if (1 == 1) then { hint "constant"; };')
    return len([item for item in diagnostics if item.code == "W206"]) == 1


def _undefined_constant_comparison() -> bool:
    diagnostics = check_undefined_text('if (1 == 1) then { _assigned = 1; }; hint str _assigned;')
    return not any(item.code == "W101" and "_assigned" in item.message for item in diagnostics)


def _undefined_boolean_condition() -> bool:
    diagnostics = check_undefined_text('if (true && false) then { _assigned = 1; }; hint str _assigned;')
    return len([item for item in diagnostics if item.code == "W101" and "_assigned" in item.message]) == 1


def _unknown_keyword_not_constant() -> bool:
    diagnostics = check_control_flow_text('if (1 == then) then { hint "unknown"; };')
    return not any(item.code == "W206" for item in diagnostics)


def _grouped_constant_comparison() -> bool:
    diagnostics = check_control_flow_text('if ((1 == 1)) then { hint "constant"; };')
    return len([item for item in diagnostics if item.code == "W206"]) == 1


def _constant_boolean_composition() -> bool:
    diagnostics = check_control_flow_text('if (true && false) then { hint "constant"; };')
    return len([item for item in diagnostics if item.code == "W206"]) == 1


def _negated_grouped_condition() -> bool:
    diagnostics = check_control_flow_text('if (!(true && false)) then { hint "constant"; };')
    return len([item for item in diagnostics if item.code == "W206"]) == 1


def _undefined_wait_until() -> bool:
    diagnostics = check_undefined_text("waitUntil { hint str _ready; };")
    return len(diagnostics) == 1 and "_ready" in diagnostics[0].message


def _undefined_try_branch() -> bool:
    diagnostics = check_undefined_text("try { _tryValue = 1; } catch { _catchValue = 2; }; hint str _tryValue;")
    return any("_tryValue" in item.message for item in diagnostics)


def _undefined_params_scope() -> bool:
    diagnostics = check_undefined_text('if (true) then { params ["_inner"]; hint str _inner; }; hint str _inner;')
    return len([item for item in diagnostics if item.code == "W101" and "_inner" in item.message]) == 1


def _undefined_switch_case() -> bool:
    diagnostics = check_undefined_text('switch (_value) do { case _missingCase: { hint "case"; }; default { hint "default"; }; };')
    return len([item for item in diagnostics if item.code == "W101" and "_missingCase" in item.message]) == 1


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


def _types_vector_angle() -> bool:
    source = '_aimDir = player weaponDirection "rifle"; _desiredDir = [0,0,0] vectorFromTo [1,0,0]; acos (_aimDir vectorCos _desiredDir);'
    return check_argument_types_text(source) == []


def _types_vector_producers() -> bool:
    source = '_v = [1,0,0] vectorAdd [0,1,0]; _d = _v vectorDotProduct [1,1,0]; acos (_d);'
    return check_argument_types_text(source) == []


def _types_hashmap_object_key() -> bool:
    source = 'params ["_road"]; private _cache = createHashMap; _cached = _cache get _road; _info = getRoadInfo _road;'
    return any(item.code == "W203" and "get expects" in item.message for item in check_argument_types_text(source))


def _types_is_equal_type_guard() -> bool:
    return check_argument_types_text('if (_value isEqualType []) then { count _value; };') == []


def _types_mission_record_patterns() -> bool:
    snippets = (
        '{ sin _x; cos _x; } forEach ([0, 60, 120, 180, 240, 300]);',
        'private _route = []; private _wp = _route select 2; count _wp;',
        'private _hit = []; private _normal = _hit select 1; count _hit;',
        'private _center = []; private _z = _center select 2; abs _z;',
    )
    return all(not any(item.code == "W203" for item in check_argument_types_text(source)) for source in snippets)


def _types_selected_fields_stay_unknown() -> bool:
    source = 'private _route = []; private _wp = _route select 2; count _wp; private _spawn = []; setPosASL player _spawn; setDir player (_spawn select 1);'
    return not any(item.code == "W203" for item in check_argument_types_text(source))


def _types_nested_scope_isolated() -> bool:
    source = 'spawn { _value = 1; }; sleep _value;'
    return not any(item.code == "W203" for item in check_argument_types_text(source))


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
    ("AST terminator node", _ast_terminator_node),
    ("AST nested spawn expression", _ast_nested_spawn_expression),
    ("AST expression walker", _ast_expression_walker),
    ("AST chained command expression", _ast_chained_command_expression),
    ("AST unary command expression", _ast_unary_command_expression),
    ("AST select element type", _ast_select_element_type),
    ("AST selectRandom element type", _ast_select_random_element_type),
    ("AST text prefix command", _ast_text_prefix_command),
    ("AST grouped expression span", _ast_group_expression_span),
    ("AST walker structured conditions", _ast_walker_structured_conditions),
    ("AST switch case condition", _ast_switch_case_condition),
    ("switch case selectRandom type", _switch_case_select_random_type),
    ("AST grouped select type", _ast_grouped_select_type),
    ("AST namespace default type", _ast_namespace_default_type),
    ("AST grouped namespace default type", _ast_grouped_namespace_default_type),
    ("non-code call target", _non_code_call_target),
    ("literal non-code call target", _literal_non_code_call_target),
    ("AST statement boundary", _ast_statement_boundary),
    ("expanded built-in signatures", _expanded_builtin_signatures),
    ("nular collection returns", _nular_collection_returns),
    ("config built-in signatures", _config_builtin_signatures),
    ("object constructor returns", _object_constructor_returns),
    ("camera and config returns", _camera_and_config_returns),
    ("object producer returns", _object_producer_returns),
    ("extended object producer returns", _extended_object_producer_returns),
    ("isNull accepts engine handles", _isnull_accepts_engine_handles),
    ("in checks right array operand", _in_checks_right_array_operand),
    ("function definition overwrite checks", _definition_overwrite_checks),
    ("postfix command syntax", _postfix_command_syntax),
    ("missing semicolon after apply", _missing_semicolon_after_apply),
    ("generated signature forms", _generated_signature_forms),
    ("UI and array-encoded commands stay unchecked", _ui_and_array_encoded_commands_stay_unchecked),
    ("engine array operand commands", _engine_array_operand_commands),
    ("extension distance and UI handles", _extension_distance_and_ui_handles),
    ("command XML metadata parser", _command_xml_metadata_parser),
    ("vendored command metadata snapshot", _vendored_command_metadata_snapshot),
    ("HashMap foreach value scope", _hashmap_foreach_value_scope),
    ("AST malformed expression recovery", _ast_malformed_expression_recovery),
    ("unreachable code in spawn", _control_flow_spawn),
    ("terminating try/catch branches", _control_flow_try),
    ("loop terminator unreachable code", _control_flow_terminators),
    ("nested else-if control flow", _control_flow_nested_else_if),
    ("negated constant condition", _constant_negated_condition),
    ("literal comparison condition", _constant_comparison_condition),
    ("constant comparison branch", _undefined_constant_comparison),
    ("constant boolean branch", _undefined_boolean_condition),
    ("unknown keyword is not constant", _unknown_keyword_not_constant),
    ("grouped literal comparison", _grouped_constant_comparison),
    ("literal boolean composition", _constant_boolean_composition),
    ("negated grouped condition", _negated_grouped_condition),
    ("undefined variable in waitUntil", _undefined_wait_until),
    ("try/catch definition merge", _undefined_try_branch),
    ("params lexical scope", _undefined_params_scope),
    ("undefined switch case local", _undefined_switch_case),
    ("Config and HashMap type inference", _types_config_hashmap),
    ("object array loop type inference", _types_near_roads),
    ("engine object collection inference", _types_engine_object_collection),
    ("local array is not engine collection", _types_local_array_named_like_collection),
    ("nearest object collection inference", _types_nearest_objects),
    ("near entity collection inference", _types_near_entities),
    ("common object collection inference", _types_common_object_collections),
    ("vector angle inference", _types_vector_angle),
    ("vector producer inference", _types_vector_producers),
    ("HashMap rejects object key", _types_hashmap_object_key),
    ("isEqualType guard narrowing", _types_is_equal_type_guard),
    ("mission record type patterns", _types_mission_record_patterns),
    ("selected fields stay unknown", _types_selected_fields_stay_unknown),
    ("nested type scope isolated", _types_nested_scope_isolated),
    ("multi-code suppression", _suppression_multi_code),
)


if __name__ == "__main__":
    failures = [name for name, case in CASES if not case()]
    if failures:
        raise SystemExit("failed: " + ", ".join(failures))
    print(f"analysis cases: {len(CASES)}/{len(CASES)} passed")
