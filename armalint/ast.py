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
        return IfStatement(start=self.tokens[pos], end=end, condition=self.tokens[condition_start + 1:close], then_block=then_node, else_block=else_node), next_pos


def parse(source_or_tokens: str | list[Token]) -> Program:
    return Parser(tokenize(source_or_tokens) if isinstance(source_or_tokens, str) else source_or_tokens).parse()


if __name__ == "__main__":
    tree = parse('if !(x > 0) then { hint "no"; } else { hint "yes"; };')
    assert isinstance(tree.statements[0], IfStatement)
    assert tree.statements[0].then_block is not None
    print("ast self-test passed")
