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
class Statement(Node):
    tokens: list[Token] = field(default_factory=list)
    terminator: str | None = None


@dataclass
class Block(Node):
    statements: list[Node] = field(default_factory=list)


@dataclass
class IfStatement(Node):
    condition: list[Token] = field(default_factory=list)
    then_block: Block | None = None
    else_block: Block | "IfStatement" | None = None


@dataclass
class LoopStatement(Node):
    """A loop with a structured code body and an unparsed header."""

    kind: str = "loop"
    header: list[Token] = field(default_factory=list)
    body: Block | None = None


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
        if tok.type == "lbrace":
            close = _matching(self.tokens, pos, "lbrace", "rbrace")
            if close is None or close >= limit:
                return None, pos + 1
            statements, _ = self._sequence(pos + 1, close, "rbrace")
            return Block(tok, self.tokens[close], statements), close + 1
        if tok.type == "keyword" and tok.value.lower() == "if":
            return self._if_node(pos, limit)
        if tok.type == "keyword" and tok.value.lower() in ("while", "for"):
            loop = self._loop_node(pos, limit)
            if loop is not None:
                return loop

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
                return Statement(tok, self.tokens[end], self.tokens[pos:end], ";"), end + 1
            end += 1
        return Statement(tok, self.tokens[end - 1], self.tokens[pos:end], None), end

    def _loop_node(self, pos: int, limit: int) -> tuple[Node | None, int] | None:
        """Parse ``while {...} do {...}`` and ``for ... do {...}`` forms."""
        kind = self.tokens[pos].value.lower()
        body_start: int | None = None
        header_end: int | None = None
        if kind == "while":
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
        ), next_pos

    def _if_node(self, pos: int, limit: int) -> tuple[Node | None, int]:
        condition_start = pos + 1
        if condition_start < limit and self.tokens[condition_start].type == "operator" and self.tokens[condition_start].value == "!":
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
        return IfStatement(start=self.tokens[pos], end=end, condition=self.tokens[condition_start + 1:close], then_block=then_node, else_block=else_node), next_pos


def parse(source_or_tokens: str | list[Token]) -> Program:
    return Parser(tokenize(source_or_tokens) if isinstance(source_or_tokens, str) else source_or_tokens).parse()


if __name__ == "__main__":
    tree = parse('if !(x > 0) then { hint "no"; } else { hint "yes"; };')
    assert isinstance(tree.statements[0], IfStatement)
    assert tree.statements[0].then_block is not None
    assert len(tree.statements) == 1
    assert tree.statements[0].end.type == "semicolon"
    loop = parse('while { _x > 0 } do { exitWith {}; };').statements[0]
    assert isinstance(loop, LoopStatement) and loop.body is not None
    print("ast self-test passed")
