"""Conservative control-flow checks over :mod:`armalint.ast` trees."""

from __future__ import annotations

from .ast import Block, ExitWithStatement, IfStatement, LoopStatement, Node, Program, Statement, SwitchStatement, TerminatorStatement, TryCatchStatement, parse
from .diagnostic import Diagnostic, Severity
from .tokenizer import Token

_CODE = "W104"
_CONSTANT_CONDITION = "W206"
_TERMINATORS = frozenset(("exitwith", "throw", "breakout", "breakto", "continue"))


def _constant_condition(tokens: list[Token]) -> bool:
    def literal(token: Token) -> bool:
        return token.type in ("number", "string") or (
            token.type == "keyword" and token.value.lower() in ("true", "false", "nil")
        )
    visible = [t for t in tokens if t.type not in ("comment", "preprocessor")]
    while len(visible) >= 2 and visible[0].type == "lparen" and visible[-1].type == "rparen":
        depth = 0
        for index, token in enumerate(visible):
            depth += token.type == "lparen"
            depth -= token.type == "rparen"
            if depth == 0 and index != len(visible) - 1:
                break
        else:
            visible = visible[1:-1]
            continue
        break
    if len(visible) >= 4 and visible[0].type == "operator" and visible[0].value == "!" and visible[1].type == "lparen" and visible[-1].type == "rparen":
        return _constant_condition(visible[2:-1])
    if len(visible) == 2 and visible[0].type == "operator" and visible[0].value == "!":
        visible = visible[1:]
    if len(visible) == 1:
        return literal(visible[0])
    if len(visible) == 3 and visible[1].type == "operator" and visible[1].value in ("&&", "||"):
        return literal(visible[0]) and literal(visible[2])
    return len(visible) == 3 and literal(visible[0]) and \
        visible[1].type == "operator" and visible[1].value in ("==", "!=", "<", ">", "<=", ">=") and \
        literal(visible[2])


def _statement_terminates(statement: Statement) -> bool:
    visible = [t for t in statement.tokens if t.type not in ("comment", "preprocessor")]
    return bool(visible and visible[0].type == "keyword" and visible[0].value.lower() in _TERMINATORS)


def _node_terminates(node: Node) -> bool:
    if isinstance(node, TerminatorStatement):
        return True
    if isinstance(node, Statement):
        return _statement_terminates(node)
    if isinstance(node, ExitWithStatement):
        return True
    if isinstance(node, Block):
        return _block_terminates(node)
    if isinstance(node, IfStatement):
        return (node.then_block is not None and _block_terminates(node.then_block)
                and isinstance(node.else_block, (Block, IfStatement))
                and _node_terminates(node.else_block))
    if isinstance(node, LoopStatement):
        return False
    if isinstance(node, SwitchStatement):
        return bool(node.cases) and any(case.is_default for case in node.cases) and all(
            case.body is not None and _block_terminates(case.body) for case in node.cases
        )
    if isinstance(node, TryCatchStatement):
        return (node.try_block is not None and node.catch_block is not None
                and _block_terminates(node.try_block) and _block_terminates(node.catch_block))
    return False


def _block_terminates(block: Block) -> bool:
    return bool(block.statements) and _node_terminates(block.statements[-1])


def _walk_block(block: Block, diags: list[Diagnostic]) -> None:
    unreachable = False
    for node in block.statements:
        if unreachable:
            diags.append(Diagnostic(
                Severity.WARNING, _CODE,
                "unreachable statement after unconditional control flow",
                node.start.line, node.start.column,
            ))
            # Continue walking nested blocks so diagnostics remain useful.
        if isinstance(node, Statement):
            for embedded in getattr(node, "embedded", []):
                embedded_body = getattr(embedded, "body", None)
                if embedded_body:
                    _walk_block(embedded_body, diags)
                elif isinstance(embedded, Block):
                    _walk_block(embedded, diags)
        elif isinstance(node, Block):
            _walk_block(node, diags)
        elif isinstance(node, IfStatement):
            _walk_if(node, diags)
        elif isinstance(node, LoopStatement) and node.body:
            _walk_block(node.body, diags)
        elif isinstance(node, SwitchStatement):
            for case in node.cases:
                if case.body:
                    _walk_block(case.body, diags)
        elif isinstance(node, TryCatchStatement):
            if node.try_block:
                _walk_block(node.try_block, diags)
            if node.catch_block:
                _walk_block(node.catch_block, diags)
        elif isinstance(node, ExitWithStatement) and node.body:
            _walk_block(node.body, diags)
        if _node_terminates(node):
            unreachable = True


def _walk_if(node: IfStatement, diags: list[Diagnostic]) -> None:
    """Walk an else-if chain without dropping its nested else branch."""
    condition = [t for t in node.condition if t.type not in ("comment", "preprocessor")]
    if _constant_condition(node.condition):
        diags.append(Diagnostic(Severity.WARNING, _CONSTANT_CONDITION,
                                "if condition is constant", condition[0].line, condition[0].column))
    if node.then_block:
        _walk_block(node.then_block, diags)
    if isinstance(node.else_block, Block):
        _walk_block(node.else_block, diags)
    elif isinstance(node.else_block, IfStatement):
        _walk_if(node.else_block, diags)


def check_control_flow(tree: Program) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    synthetic = Block(
        start=tree.statements[0].start if tree.statements else None,
        end=tree.statements[-1].end if tree.statements else None,
        statements=tree.statements,
    )
    _walk_block(synthetic, diags)
    return diags


def check_control_flow_text(source: str) -> list[Diagnostic]:
    return check_control_flow(parse(source))


if __name__ == "__main__":
    assert check_control_flow_text('exitWith {}; hint "never";')[0].code == _CODE
    both = check_control_flow_text('if (true) then { exitWith {}; } else { throw 1; }; hint "never";')
    assert any(d.code == _CONSTANT_CONDITION for d in both), both
    assert any(d.code == _CODE for d in both), both
    literal = check_control_flow_text('if (false) then { hint "never"; };')
    assert len([d for d in literal if d.code == _CONSTANT_CONDITION]) == 1, literal
    negated_literal = check_control_flow_text('if (!true) then { hint "never"; };')
    assert len([d for d in negated_literal if d.code == _CONSTANT_CONDITION]) == 1, negated_literal
    comparison_literal = check_control_flow_text('if (1 == 1) then { hint "constant"; };')
    assert len([d for d in comparison_literal if d.code == _CONSTANT_CONDITION]) == 1, comparison_literal
    unknown_comparison = check_control_flow_text('if (1 == then) then { hint "unknown"; };')
    assert not any(d.code == _CONSTANT_CONDITION for d in unknown_comparison), unknown_comparison
    grouped_comparison = check_control_flow_text('if ((1 == 1)) then { hint "constant"; };')
    assert len([d for d in grouped_comparison if d.code == _CONSTANT_CONDITION]) == 1, grouped_comparison
    boolean_literal = check_control_flow_text('if (true && false) then { hint "constant"; };')
    assert len([d for d in boolean_literal if d.code == _CONSTANT_CONDITION]) == 1, boolean_literal
    negated_group = check_control_flow_text('if (!(true && false)) then { hint "constant"; };')
    assert len([d for d in negated_group if d.code == _CONSTANT_CONDITION]) == 1, negated_group
    assert check_control_flow_text('if (_condition) then { exitWith {}; }; hint "maybe";') == []
    embedded = check_control_flow_text('x = ({ exitWith {}; hint "never"; } forEach allUnits);')
    assert any(d.code == _CODE and "unreachable" in d.message for d in embedded), embedded
    embedded_exit = check_control_flow_text('x = ({ exitWith {}; hint "never"; } forEach allUnits);')
    assert len([d for d in embedded_exit if d.code == _CODE]) == 1
    spawned = check_control_flow_text('spawn { exitWith {}; hint "never"; };')
    assert len([d for d in spawned if d.code == _CODE]) == 1, spawned
    caught = check_control_flow_text('try { exitWith {}; } catch { throw 1; }; hint "never";')
    assert len([d for d in caught if d.code == _CODE]) == 1, caught
    for terminator in ("breakOut", "breakTo", "throw"):
        diagnostics = check_control_flow_text(f'{terminator} "scope"; hint "never";')
        assert len([d for d in diagnostics if d.code == _CODE]) == 1, (terminator, diagnostics)
    continued = check_control_flow_text('continue; hint "never";')
    assert len([d for d in continued if d.code == _CODE]) == 1, continued
    nested = check_control_flow_text('if (_a) then { exitWith {}; } else if (_b) then { throw 1; } else { breakOut "scope"; }; hint "never";')
    assert len([d for d in nested if d.code == _CODE]) == 1, nested
    print("control_flow self-test passed")
