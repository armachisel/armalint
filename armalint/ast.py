"""Small AST/control-flow foundation for SQF.

The parser deliberately starts with structural constructs and source spans. The
existing token passes remain authoritative while this tree grows into the
scope/type analysis layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .tokenizer import Token, tokenize


@dataclass
class Node:
    start: Token
    end: Token


@dataclass
class Expression(Node):
    pass


@dataclass
class LiteralExpression(Expression):
    value: Token = None  # type: ignore[assignment]


@dataclass
class NameExpression(Expression):
    name: Token = None  # type: ignore[assignment]


@dataclass
class ArrayExpression(Expression):
    items: list[Expression] = field(default_factory=list)


@dataclass
class CodeExpression(Expression):
    tokens: list[Token] = field(default_factory=list)
    body: Block | None = None


@dataclass
class CallExpression(Expression):
    command: Token = None  # type: ignore[assignment]
    target: Expression = None  # type: ignore[assignment]


@dataclass
class UnaryExpression(Expression):
    operator: Token = None  # type: ignore[assignment]
    operand: Expression = None  # type: ignore[assignment]


@dataclass
class GroupExpression(Expression):
    """An expression enclosed in parentheses, retaining its source span."""

    inner: Expression = None  # type: ignore[assignment]


@dataclass
class BinaryExpression(Expression):
    left: Expression = None  # type: ignore[assignment]
    operator: Token = None  # type: ignore[assignment]
    right: Expression = None  # type: ignore[assignment]


@dataclass
class CommandExpression(Expression):
    """A unary or binary SQF command applied to an expression."""

    command: Token = None  # type: ignore[assignment]
    left: Expression | None = None
    right: Expression | None = None


@dataclass
class Statement(Node):
    tokens: list[Token] = field(default_factory=list)
    terminator: str | None = None
    embedded: list[Node] = field(default_factory=list)
    expression: Expression | None = None


@dataclass
class TerminatorStatement(Statement):
    """A statement that unconditionally exits or changes control flow."""

    command: str = ""


@dataclass
class Block(Node):
    statements: list[Node] = field(default_factory=list)


@dataclass
class IfStatement(Node):
    condition: list[Token] = field(default_factory=list)
    then_block: Block | None = None
    else_block: Block | "IfStatement" | None = None
    negated: bool = False
    condition_ast: Expression | None = None


@dataclass
class LoopStatement(Node):
    """A loop with a structured code body and an unparsed header."""

    kind: str = "loop"
    header: list[Token] = field(default_factory=list)
    body: Block | None = None
    header_ast: Expression | None = None


@dataclass
class SwitchCase(Node):
    condition: list[Token] = field(default_factory=list)
    body: Block | None = None
    is_default: bool = False


@dataclass
class SwitchStatement(Node):
    expression: list[Token] = field(default_factory=list)
    cases: list[SwitchCase] = field(default_factory=list)
    expression_ast: Expression | None = None


@dataclass
class ExitWithStatement(Node):
    body: Block | None = None


@dataclass
class TryCatchStatement(Node):
    try_block: Block | None = None
    catch_block: Block | None = None


@dataclass
class Program:
    statements: list[Node] = field(default_factory=list)


def _matching(tokens: list[Token], start: int, opener: str, closer: str) -> int | None:
    depth = 0
    for i in range(start, len(tokens)):
        if tokens[i].type == opener:
            depth += 1
        elif tokens[i].type == closer:
            depth -= 1
            if depth == 0:
                return i
    return None


_EXPR_PRECEDENCE = {"=": 0, "||": 1, "&&": 2, "==": 3, "!=": 3, "<": 4, ">": 4, "<=": 4, ">=": 4, "+": 5, "-": 5, "*": 6, "/": 6, "%": 6}

# Commands which have the unambiguous SQF prefix form ``command operand``.
# Keeping this list local to the parser avoids coupling the syntax tree to the
# type checker while still giving common built-ins a useful AST shape.
_PREFIX_COMMANDS = frozenset({
    "abs", "acos", "asin", "atan", "ceil", "count", "cos", "floor",
    "isarray", "isclass", "isnil", "isnumber", "isnull", "isserver",
    "composetext", "parsenumber", "parsesimplearray", "parsetext", "round",
    "selectrandom", "sin", "sqrt", "str", "tan", "toarray", "tolower",
    "toupper", "typename", "typeof", "tostring",
})


def parse_expression(tokens: list[Token]) -> Expression | None:
    """Parse a conservative expression tree for common SQF operators."""
    visible = [t for t in tokens if t.type not in ("comment", "preprocessor", "eof")]
    pos = 0

    def primary() -> Expression | None:
        nonlocal pos
        if pos >= len(visible): return None
        token = visible[pos]
        if token.type == "keyword" and token.value.lower() in ("call", "spawn") and pos + 1 < len(visible):
            command = token
            pos += 1
            target = primary()
            return CallExpression(command, target.end if target else command, command, target) if target else None
        if token.type == "keyword" and token.value.lower() == "not":
            pos += 1
            item = primary()
            return UnaryExpression(token, item.end if item else token, token, item) if item else None
        if token.value.lower() in _PREFIX_COMMANDS and pos + 1 < len(visible):
            command = token
            pos += 1
            operand = primary()
            return (CommandExpression(command, operand.end, command, None, operand)
                    if operand else None)
        if token.type in ("number", "string") or (token.type == "keyword" and token.value.lower() in ("true", "false", "nil")):
            pos += 1; return LiteralExpression(token, token, token)
        if token.type in ("ident", "local", "keyword"):
            pos += 1; return NameExpression(token, token, token)
        if token.type in ("lbracket", "lbrace"):
            close = _matching(visible, pos, token.type, "rbracket" if token.type == "lbracket" else "rbrace")
            if close is None: return None
            if token.type == "lbrace":
                raw_start = pos
                pos = close + 1
                inner = visible[raw_start + 1:close]
                body = Block(token, visible[close], Parser(inner).parse().statements)
                return CodeExpression(token, visible[close], visible[raw_start:close + 1], body)
            start = pos; pos += 1; items = []
            while pos < close:
                item = expression(0)
                if item is None: return None
                items.append(item)
                if pos < close and visible[pos].type == "comma": pos += 1
                elif pos < close: return None
            pos = close + 1
            return ArrayExpression(visible[start], visible[close], items)
        if token.type == "lparen":
            opening = token
            pos += 1; item = expression(0)
            if item is not None and pos < len(visible) and visible[pos].type == "rparen":
                closing = visible[pos]
                pos += 1
                return GroupExpression(opening, closing, item)
            return None
        if token.type == "operator" and token.value in ("!", "+", "-"):
            pos += 1; item = primary()
            return UnaryExpression(token, item.end if item else token, token, item) if item else None
        return None

    def expression(minimum: int) -> Expression | None:
        nonlocal pos
        left = primary()
        if left is None: return None
        while pos < len(visible):
            op = visible[pos]
            precedence = _EXPR_PRECEDENCE.get(op.value) if op.type == "operator" else None
            if precedence is None or precedence < minimum: break
            pos += 1; right = expression(precedence + 1)
            if right is None: return None
            left = BinaryExpression(left.start, right.end, left, op, right)
        while pos < len(visible) and visible[pos].type in ("ident", "keyword"):
            op = visible[pos]
            pos += 1
            right = primary()
            if right is None: return None
            left = CommandExpression(left.start, right.end, op, left, right)
        return left

    result = expression(0)
    return result if result is not None and pos == len(visible) else None


def walk_expression(expression: Expression | None):
    """Yield an expression and all nested expression nodes depth-first."""
    if expression is None:
        return
    yield expression
    if isinstance(expression, (UnaryExpression, GroupExpression)):
        if isinstance(expression, GroupExpression):
            yield from walk_expression(expression.inner)
        else:
            yield from walk_expression(expression.operand)
    elif isinstance(expression, (BinaryExpression, CommandExpression)):
        yield from walk_expression(expression.left)
        yield from walk_expression(expression.right)
    elif isinstance(expression, ArrayExpression):
        for item in expression.items:
            yield from walk_expression(item)
    elif isinstance(expression, CallExpression):
        yield from walk_expression(expression.target)
    elif isinstance(expression, CodeExpression) and expression.body:
        for statement in expression.body.statements:
            yield from walk_expression(getattr(statement, "expression", None))


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = [t for t in tokens if t.type not in ("comment", "preprocessor", "eof")]

    def parse(self) -> Program:
        statements, _ = self._sequence(0, len(self.tokens), stop=None)
        return Program(statements)

    def _sequence(self, pos: int, limit: int, stop: str | None) -> tuple[list[Node], int]:
        result: list[Node] = []
        while pos < limit:
            if stop and self.tokens[pos].type == stop:
                return result, pos + 1
            node, pos = self._node(pos, limit)
            if node is not None:
                result.append(node)
            else:
                pos += 1
        return result, pos

    def _node(self, pos: int, limit: int) -> tuple[Node | None, int]:
        tok = self.tokens[pos]
        if tok.type == "keyword" and tok.value.lower() in ("throw", "breakout", "breakto", "continue"):
            end = pos
            while end < limit and self.tokens[end].type != "semicolon":
                end += 1
            final = self.tokens[end] if end < limit else self.tokens[end - 1]
            return TerminatorStatement(tok, final, self.tokens[pos:end], ";" if end < limit else None, [], None, tok.value.lower()), end + 1 if end < limit else end
        if tok.type == "lbrace":
            foreach = self._foreach_node(pos, limit)
            if foreach is not None:
                return foreach
            close = _matching(self.tokens, pos, "lbrace", "rbrace")
            if close is None or close >= limit:
                return None, pos + 1
            statements, _ = self._sequence(pos + 1, close, "rbrace")
            return Block(tok, self.tokens[close], statements), close + 1
        if tok.type == "keyword" and tok.value.lower() == "if":
            return self._if_node(pos, limit)
        if tok.type == "keyword" and tok.value.lower() in ("while", "for", "waituntil"):
            loop = self._loop_node(pos, limit)
            if loop is not None:
                return loop
        if tok.type == "keyword" and tok.value.lower() == "switch":
            switch = self._switch_node(pos, limit)
            if switch is not None:
                return switch
        if tok.type == "keyword" and tok.value.lower() == "exitwith":
            exit_with = self._exit_with_node(pos, limit)
            if exit_with is not None:
                return exit_with
        if tok.type == "keyword" and tok.value.lower() == "try":
            try_catch = self._try_catch_node(pos, limit)
            if try_catch is not None:
                return try_catch

        depth = 0
        end = pos
        while end < limit:
            kind = self.tokens[end].type
            if kind in ("lparen", "lbracket", "lbrace"):
                depth += 1
            elif kind in ("rparen", "rbracket", "rbrace"):
                if depth > 0:
                    depth -= 1
            elif kind == "semicolon" and depth == 0:
                statement_tokens = self.tokens[pos:end]
                return Statement(tok, self.tokens[end], statement_tokens, ";", self._embedded(statement_tokens), parse_expression(statement_tokens)), end + 1
            end += 1
        statement_tokens = self.tokens[pos:end]
        return Statement(tok, self.tokens[end - 1], statement_tokens, None, self._embedded(statement_tokens), parse_expression(statement_tokens)), end

    def _embedded(self, tokens: list[Token]) -> list[Node]:
        """Find structured code blocks embedded in expressions."""
        result: list[Node] = []
        for i, token in enumerate(tokens):
            if token.type == "keyword" and token.value.lower() == "exitwith":
                body_start = i + 1
                if body_start < len(tokens) and tokens[body_start].type == "lbrace":
                    close = _matching(tokens, body_start, "lbrace", "rbrace")
                    if close is not None:
                        body_statements, _ = Parser(tokens[body_start + 1:close])._sequence(0, close - body_start - 1, stop=None)
                        result.append(ExitWithStatement(
                            start=token,
                            end=tokens[close],
                            body=Block(tokens[body_start], tokens[close], body_statements),
                        ))
                continue
            if (token.type == "keyword" and token.value.lower() in ("call", "spawn")
                    and i + 1 < len(tokens) and tokens[i + 1].type == "lbrace"):
                close = _matching(tokens, i + 1, "lbrace", "rbrace")
                if close is not None:
                    body_statements, _ = Parser(tokens[i + 2:close])._sequence(0, close - i - 2, stop=None)
                    result.append(Block(tokens[i + 1], tokens[close], body_statements))
                continue
            if token.type != "lbrace":
                continue
            close = _matching(tokens, i, "lbrace", "rbrace")
            if close is None or close + 1 >= len(tokens):
                continue
            foreach = tokens[close + 1]
            if foreach.type != "keyword" or foreach.value.lower() != "foreach":
                continue
            body_statements, _ = Parser(tokens[i + 1:close])._sequence(0, close - i - 1, stop=None)
            body = Block(token, tokens[close], body_statements)
            header_end = len(tokens) - 1 if tokens and tokens[-1].type == "rparen" else len(tokens)
            result.append(LoopStatement(
                start=token,
                end=tokens[max(close + 2, header_end - 1)],
                kind="foreach",
                header=tokens[close + 2:header_end],
                body=body,
                header_ast=parse_expression(tokens[close + 2:header_end]),
            ))
        return result

    def _foreach_node(self, pos: int, limit: int) -> tuple[Node | None, int] | None:
        """Parse the valid ``{ ... } forEach expression`` form."""
        body_close = _matching(self.tokens, pos, "lbrace", "rbrace")
        if body_close is None or body_close + 1 >= limit:
            return None
        foreach = self.tokens[body_close + 1]
        if foreach.type != "keyword" or foreach.value.lower() != "foreach":
            return None
        end = body_close + 2
        depth = 0
        while end < limit:
            token_type = self.tokens[end].type
            if token_type in ("lparen", "lbracket", "lbrace"):
                depth += 1
            elif token_type in ("rparen", "rbracket", "rbrace"):
                depth = max(0, depth - 1)
            elif token_type == "semicolon" and depth == 0:
                break
            end += 1
        body_node, _ = self._node(pos, body_close + 1)
        if not isinstance(body_node, Block):
            return None
        final_end = self.tokens[end] if end < limit and self.tokens[end].type == "semicolon" else body_node.end
        next_pos = end + 1 if end < limit and self.tokens[end].type == "semicolon" else end
        return LoopStatement(
            start=self.tokens[pos],
            end=final_end,
            kind="foreach",
            header=self.tokens[body_close + 2:end],
            body=body_node,
            header_ast=parse_expression(self.tokens[body_close + 2:end]),
        ), next_pos

    def _loop_node(self, pos: int, limit: int) -> tuple[Node | None, int] | None:
        """Parse ``while {...} do {...}`` and ``for ... do {...}`` forms."""
        kind = self.tokens[pos].value.lower()
        body_start: int | None = None
        header_end: int | None = None
        if kind == "waituntil":
            body_start = pos + 1
            header_end = pos
        elif kind == "while":
            condition_start = pos + 1
            if condition_start >= limit or self.tokens[condition_start].type != "lbrace":
                return None
            condition_close = _matching(self.tokens, condition_start, "lbrace", "rbrace")
            if condition_close is None or condition_close + 1 >= limit:
                return None
            do_token = self.tokens[condition_close + 1]
            if do_token.type != "keyword" or do_token.value.lower() != "do":
                return None
            body_start = condition_close + 2
            header_end = condition_close
        else:
            # The ``for`` header ends at the first top-level ``do`` keyword.
            depth = 0
            for i in range(pos + 1, limit):
                token_type = self.tokens[i].type
                if token_type in ("lparen", "lbracket", "lbrace"):
                    depth += 1
                elif token_type in ("rparen", "rbracket", "rbrace"):
                    depth = max(0, depth - 1)
                elif depth == 0 and token_type == "keyword" and self.tokens[i].value.lower() == "do":
                    header_end = i - 1
                    body_start = i + 1
                    break
            if body_start is None:
                return None
        if body_start >= limit or self.tokens[body_start].type != "lbrace":
            return None
        body_close = _matching(self.tokens, body_start, "lbrace", "rbrace")
        if body_close is None or body_close >= limit:
            return None
        body_node, next_pos = self._node(body_start, limit)
        if not isinstance(body_node, Block):
            return None
        end = body_node.end
        if next_pos < limit and self.tokens[next_pos].type == "semicolon":
            end = self.tokens[next_pos]
            next_pos += 1
        return LoopStatement(
            start=self.tokens[pos],
            end=end,
            kind=kind,
            header=self.tokens[pos + 1:header_end + 1],
            body=body_node,
            header_ast=parse_expression(self.tokens[pos + 1:header_end + 1]),
        ), next_pos

    def _switch_node(self, pos: int, limit: int) -> tuple[Node | None, int] | None:
        """Parse ``switch (expression) do { case ...; default ... }``."""
        expression_start = pos + 1
        if expression_start >= limit or self.tokens[expression_start].type != "lparen":
            return None
        expression_close = _matching(self.tokens, expression_start, "lparen", "rparen")
        if expression_close is None or expression_close + 2 >= limit:
            return None
        do_token = self.tokens[expression_close + 1]
        body_start = expression_close + 2
        if do_token.type != "keyword" or do_token.value.lower() != "do":
            return None
        if self.tokens[body_start].type != "lbrace":
            return None
        body_close = _matching(self.tokens, body_start, "lbrace", "rbrace")
        if body_close is None or body_close >= limit:
            return None

        cases: list[SwitchCase] = []
        cursor = body_start + 1
        while cursor < body_close:
            token = self.tokens[cursor]
            if token.type not in ("keyword",) or token.value.lower() not in ("case", "default"):
                cursor += 1
                continue
            is_default = token.value.lower() == "default"
            condition_start = cursor + 1
            if is_default and condition_start < body_close and self.tokens[condition_start].type == "lbrace":
                colon = cursor
                body_start = condition_start
            else:
                body_start = None
                colon = condition_start
                depth = 0
                while colon < body_close:
                    current = self.tokens[colon]
                    if current.type in ("lparen", "lbracket"):
                        depth += 1
                    elif current.type in ("rparen", "rbracket"):
                        depth = max(0, depth - 1)
                    elif current.type == "operator" and current.value == ":" and depth == 0:
                        break
                    colon += 1
                if colon < body_close:
                    body_start = colon + 1
            if body_start is None or body_start >= body_close or self.tokens[body_start].type != "lbrace":
                cursor += 1
                continue
            case_body, next_cursor = self._node(body_start, body_close)
            if not isinstance(case_body, Block):
                cursor += 1
                continue
            case_end = case_body.end
            if next_cursor < body_close and self.tokens[next_cursor].type == "semicolon":
                case_end = self.tokens[next_cursor]
                next_cursor += 1
            cases.append(SwitchCase(
                start=token,
                end=case_end,
                condition=[] if is_default else self.tokens[condition_start:colon],
                body=case_body,
                is_default=is_default,
            ))
            cursor = next_cursor
        next_pos = body_close + 1
        end = self.tokens[body_close]
        if next_pos < limit and self.tokens[next_pos].type == "semicolon":
            end = self.tokens[next_pos]
            next_pos += 1
        return SwitchStatement(
            start=self.tokens[pos],
            end=end,
            expression=self.tokens[expression_start + 1:expression_close],
            cases=cases,
            expression_ast=parse_expression(self.tokens[expression_start + 1:expression_close]),
        ), next_pos

    def _exit_with_node(self, pos: int, limit: int) -> tuple[Node | None, int] | None:
        """Parse a standalone ``exitWith { ... }`` statement."""
        body_start = pos + 1
        if body_start >= limit or self.tokens[body_start].type != "lbrace":
            return None
        body, next_pos = self._node(body_start, limit)
        if not isinstance(body, Block):
            return None
        end = body.end
        if next_pos < limit and self.tokens[next_pos].type == "semicolon":
            end = self.tokens[next_pos]
            next_pos += 1
        return ExitWithStatement(start=self.tokens[pos], end=end, body=body), next_pos

    def _try_catch_node(self, pos: int, limit: int) -> tuple[Node | None, int] | None:
        """Parse ``try { ... } catch { ... }``."""
        try_start = pos + 1
        if try_start >= limit or self.tokens[try_start].type != "lbrace":
            return None
        try_node, next_pos = self._node(try_start, limit)
        if not isinstance(try_node, Block):
            return None
        if next_pos < limit and self.tokens[next_pos].type == "semicolon":
            next_pos += 1
        if next_pos >= limit or self.tokens[next_pos].type != "keyword" or self.tokens[next_pos].value.lower() != "catch":
            return None
        catch_start = next_pos + 1
        if catch_start >= limit or self.tokens[catch_start].type != "lbrace":
            return None
        catch_node, next_pos = self._node(catch_start, limit)
        if not isinstance(catch_node, Block):
            return None
        end = catch_node.end
        if next_pos < limit and self.tokens[next_pos].type == "semicolon":
            end = self.tokens[next_pos]
            next_pos += 1
        return TryCatchStatement(self.tokens[pos], end, try_node, catch_node), next_pos

    def _if_node(self, pos: int, limit: int) -> tuple[Node | None, int]:
        condition_start = pos + 1
        negated = False
        if condition_start < limit and self.tokens[condition_start].type == "operator" and self.tokens[condition_start].value == "!":
            negated = True
            condition_start += 1
        if condition_start >= limit or self.tokens[condition_start].type != "lparen":
            return None, pos + 1
        close = _matching(self.tokens, condition_start, "lparen", "rparen")
        if close is None or close + 1 >= limit:
            return None, pos + 1
        then_pos = close + 1
        if self.tokens[then_pos].type == "keyword" and self.tokens[then_pos].value.lower() in ("then", "exitwith"):
            then_pos += 1
        if then_pos >= limit or self.tokens[then_pos].type != "lbrace":
            return None, pos + 1
        then_node, next_pos = self._node(then_pos, limit)
        if not isinstance(then_node, Block):
            return None, pos + 1
        else_node = None
        if next_pos < limit and self.tokens[next_pos].type == "keyword" and self.tokens[next_pos].value.lower() == "else":
            next_pos += 1
            if next_pos < limit and self.tokens[next_pos].type == "keyword" and self.tokens[next_pos].value.lower() == "if":
                else_node, next_pos = self._if_node(next_pos, limit)
            elif next_pos < limit and self.tokens[next_pos].type == "lbrace":
                else_node, next_pos = self._node(next_pos, limit)
        end = else_node.end if isinstance(else_node, Node) else then_node.end
        # The semicolon after an if/else statement belongs to the statement
        # just parsed. Consuming it here prevents the parser from manufacturing
        # a separate statement whose only token is ``;``.
        if next_pos < limit and self.tokens[next_pos].type == "semicolon":
            end = self.tokens[next_pos]
            next_pos += 1
        condition = self.tokens[condition_start + 1:close]
        return IfStatement(start=self.tokens[pos], end=end, condition=condition, then_block=then_node, else_block=else_node, negated=negated, condition_ast=parse_expression(condition)), next_pos


def parse(source_or_tokens: str | list[Token]) -> Program:
    return Parser(tokenize(source_or_tokens) if isinstance(source_or_tokens, str) else source_or_tokens).parse()


if __name__ == "__main__":
    tree = parse('if !(x > 0) then { hint "no"; } else { hint "yes"; };')
    assert isinstance(tree.statements[0], IfStatement)
    assert tree.statements[0].negated is True
    assert tree.statements[0].then_block is not None
    assert len(tree.statements) == 1
    assert tree.statements[0].end.type == "semicolon"
    loop = parse('while { _x > 0 } do { exitWith {}; };').statements[0]
    assert isinstance(loop, LoopStatement) and loop.body is not None
    wait = parse('waitUntil { _ready; };').statements[0]
    assert isinstance(wait, LoopStatement) and wait.kind == "waituntil" and wait.body is not None
    foreach = parse('{ hint str _x; } forEach _items;').statements[0]
    assert isinstance(foreach, LoopStatement) and foreach.kind == "foreach"
    embedded = parse('_result = ({ _result pushBack _x; } forEach allUnits);').statements[0]
    assert isinstance(embedded, Statement) and len(embedded.embedded) == 1
    assert isinstance(embedded.embedded[0], LoopStatement)
    embedded_loop = embedded.embedded[0]
    assert embedded_loop.start.type == "lbrace" and embedded_loop.end.value.lower() == "allunits"
    assert any(token.value.lower() == "allunits" for token in embedded_loop.header)
    assert embedded_loop.body is not None and embedded_loop.body.start.type == "lbrace"
    early = parse('_result = ({ exitWith {}; } forEach allUnits);').statements[0]
    assert isinstance(early, Statement) and any(isinstance(node, ExitWithStatement) for node in early.embedded)
    spawned = parse('_handle = spawn { hint str _missing; };').statements[0]
    assert isinstance(spawned, Statement) and isinstance(spawned.embedded[0], Block)
    switch = parse('switch (_x) do { case 1: { hint "one"; }; default { hint "other"; }; };').statements[0]
    assert isinstance(switch, SwitchStatement) and len(switch.cases) == 2
    exit_with = parse('exitWith { hint "done"; };').statements[0]
    assert isinstance(exit_with, ExitWithStatement) and exit_with.body is not None
    caught = parse('try { hint str _value; } catch { hint str _exception; };').statements[0]
    assert isinstance(caught, TryCatchStatement) and caught.try_block is not None and caught.catch_block is not None
    terminator = parse('breakOut "scope";').statements[0]
    assert isinstance(terminator, TerminatorStatement) and terminator.command == "breakout"
    expr = parse('_value = 1 + 2;').statements[0]
    assert isinstance(expr, Statement) and isinstance(expr.expression, BinaryExpression)
    conditional = parse('if (1 == 1) then {};').statements[0]
    assert isinstance(conditional, IfStatement) and isinstance(conditional.condition_ast, BinaryExpression)
    switched = parse('switch (1) do { default {}; };').statements[0]
    assert isinstance(switched, SwitchStatement) and isinstance(switched.expression_ast, LiteralExpression)
    command_expr = parse('_value = player weaponDirection "rifle";').statements[0]
    assert isinstance(command_expr, Statement) and isinstance(command_expr.expression, BinaryExpression) and isinstance(command_expr.expression.right, CommandExpression)
    code_expr = parse('_handle = call { hint "x"; };').statements[0]
    assert isinstance(code_expr, Statement) and isinstance(code_expr.expression, BinaryExpression) and isinstance(code_expr.expression.right, CallExpression)
    assert isinstance(code_expr.expression.right.target, CodeExpression) and code_expr.expression.right.target.body is not None
    variable_call = parse('call _fnc;').statements[0]
    assert isinstance(variable_call, Statement) and isinstance(variable_call.expression, CallExpression)
    negated = parse('not _condition;').statements[0]
    assert isinstance(negated, Statement) and isinstance(negated.expression, UnaryExpression)
    grouped = parse('_value = (1 + 2);').statements[0]
    assert isinstance(grouped, Statement) and isinstance(grouped.expression, BinaryExpression)
    assert isinstance(grouped.expression.right, GroupExpression)
    unary_command = parse('count [1, 2];').statements[0]
    assert isinstance(unary_command, Statement) and isinstance(unary_command.expression, CommandExpression)
    assert unary_command.expression.left is None
    print("ast self-test passed")
