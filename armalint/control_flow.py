"""Conservative control-flow checks over :mod:`armalint.ast` trees."""

from __future__ import annotations

from .ast import Block, ExitWithStatement, IfStatement, LoopStatement, Node, Program, Statement, SwitchStatement, parse
from .diagnostic import Diagnostic, Severity

_CODE = "W104"
_TERMINATORS = frozenset(("exitwith", "throw", "breakout", "continue"))


def _statement_terminates(statement: Statement) -> bool:
    visible = [t for t in statement.tokens if t.type not in ("comment", "preprocessor")]
    return bool(visible and visible[0].type == "keyword" and visible[0].value.lower() in _TERMINATORS)


def _node_terminates(node: Node) -> bool:
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
                if isinstance(embedded, LoopStatement) and embedded.body:
                    _walk_block(embedded.body, diags)
        elif isinstance(node, Block):
            _walk_block(node, diags)
        elif isinstance(node, IfStatement):
            if node.then_block:
                _walk_block(node.then_block, diags)
            if isinstance(node.else_block, Block):
                _walk_block(node.else_block, diags)
            elif isinstance(node.else_block, IfStatement) and node.else_block.then_block:
                _walk_block(node.else_block.then_block, diags)
        elif isinstance(node, LoopStatement) and node.body:
            _walk_block(node.body, diags)
        elif isinstance(node, SwitchStatement):
            for case in node.cases:
                if case.body:
                    _walk_block(case.body, diags)
        elif isinstance(node, ExitWithStatement) and node.body:
            _walk_block(node.body, diags)
        if _node_terminates(node):
            unreachable = True


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
    assert check_control_flow_text('if (true) then { exitWith {}; } else { throw 1; }; hint "never";')[0].code == _CODE
    assert check_control_flow_text('if (true) then { exitWith {}; }; hint "maybe";') == []
    embedded = check_control_flow_text('x = ({ exitWith {}; hint "never"; } forEach allUnits);')
    assert any(d.code == _CODE and "unreachable" in d.message for d in embedded), embedded
    print("control_flow self-test passed")
