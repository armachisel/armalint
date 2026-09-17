"""Syntax checks for Armalint (operates on the tokenizer's token stream)."""

from __future__ import annotations

from .diagnostic import Diagnostic, Severity, format_diagnostic
from .ast import Block, ExitWithStatement, IfStatement, LoopStatement, Node, Statement, SwitchStatement, TryCatchStatement, parse
from .tokenizer import Token, tokenize

# Token-type -> bracket character mappings used by the balance check.
_OPENERS = {"lparen": "(", "lbracket": "[", "lbrace": "{"}
_CLOSERS = {"rparen": ")", "rbracket": "]", "rbrace": "}"}
_MATCHING = {"(": ")", "[": "]", "{": "}"}

_CODE_BRACKET = "E001"
_CODE_STRING = "E002"
_TRAILING_COMMA = "E003"
_MISSING_THEN = "E004"
_BAD_ELSE = "E005"
_MISSING_COMMA = "E006"
_FOREACH_ORDER = "E007"
_MISSING_SEMICOLON = "E008"


def _significant(tokens: list[Token]) -> list[Token]:
    return [t for t in tokens if t.type not in ("comment", "preprocessor", "eof")]


def _matching_close(tokens: list[Token], start: int) -> int | None:
    pairs = {"lparen": "rparen", "lbracket": "rbracket", "lbrace": "rbrace"}
    stack: list[str] = []
    for i in range(start, len(tokens)):
        kind = tokens[i].type
        if kind in pairs:
            stack.append(pairs[kind])
        elif kind in ("rparen", "rbracket", "rbrace"):
            if not stack or stack.pop() != kind:
                return None
            if not stack:
                return i
    return None


def _ast_statement_boundary_diagnostics(tokens: list[Token]) -> list[Diagnostic]:
    """Find clear block/statement boundaries from the parsed AST."""
    try:
        roots = parse(tokens).statements
    except Exception:
        return []
    structured = (IfStatement, LoopStatement, SwitchStatement, ExitWithStatement, TryCatchStatement)
    diagnostics: list[Diagnostic] = []

    def visit(nodes: list[Node]) -> None:
        for previous, current in zip(nodes, nodes[1:]):
            if (isinstance(previous, structured) or
                    (isinstance(previous, Statement) and previous.embedded)):
                if (previous.end.type == "rbrace" and current.start.line == previous.end.line
                        and current.start.value.lower() not in ("else", "catch", "then")):
                    diagnostics.append(Diagnostic(
                        Severity.ERROR, _MISSING_SEMICOLON,
                        "missing semicolon after code block",
                        current.start.line, current.start.column,
                    ))
        for node in nodes:
            for name in ("then_block", "else_block", "body", "try_block", "catch_block"):
                child = getattr(node, name, None)
                if isinstance(child, Block):
                    visit(child.statements)
                elif isinstance(child, Node):
                    visit([child])
            for case in getattr(node, "cases", ()):
                if case.body:
                    visit(case.body.statements)

    visit(roots)
    return diagnostics


def check_syntax(tokens: list[Token]) -> list[Diagnostic]:
    """Run syntax checks over a token stream (which ends with ``eof``)."""
    diags: list[Diagnostic] = []
    stack: list[tuple[Token, str]] = []  # (opener token, opener char)
    previous_significant: Token | None = None
    sig = _significant(tokens)

    # Conservative local grammar checks for forms with an unambiguous shape.
    for i, tok in enumerate(sig):
        if tok.type == "keyword" and tok.value.lower() == "if" and i + 1 < len(sig):
            # SQF permits `if !(condition) exitWith {...}` as well as the
            # usual `if (condition) then {...}` form.
            condition_start = i + 1
            if sig[condition_start].type == "operator" and sig[condition_start].value == "!":
                condition_start += 1
            if condition_start >= len(sig) or sig[condition_start].type != "lparen":
                continue
            close = _matching_close(sig, condition_start)
            if close is not None and (close + 1 == len(sig) or not (sig[close + 1].type == "keyword" and sig[close + 1].value.lower() in ("then", "exitwith"))):
                bad = sig[close + 1] if close + 1 < len(sig) else sig[close]
                diags.append(Diagnostic(Severity.ERROR, _MISSING_THEN, "expected 'then' after if condition", bad.line, bad.column))
        if tok.type == "keyword" and tok.value.lower() == "else":
            nxt = sig[i + 1] if i + 1 < len(sig) else tok
            if nxt.type != "lbrace" and not (nxt.type == "keyword" and nxt.value.lower() == "if"):
                diags.append(Diagnostic(Severity.ERROR, _BAD_ELSE, "expected code block or if after 'else'", nxt.line, nxt.column))
        if tok.type == "keyword" and tok.value.lower() == "foreach" and i + 2 < len(sig) and sig[i + 1].type in ("ident", "local") and sig[i + 2].type == "lbrace":
            diags.append(Diagnostic(Severity.ERROR, _FOREACH_ORDER, "expected code block before 'forEach'", tok.line, tok.column))
        if tok.type == "lbracket":
            close = _matching_close(sig, i)
            if close is not None:
                for left, right in zip(sig[i + 1:close], sig[i + 2:close + 1]):
                    if left.type in ("number", "string") and right.type in ("number", "string"):
                        diags.append(Diagnostic(Severity.ERROR, _MISSING_COMMA, "missing comma between array elements", right.line, right.column))
                        break
    diags.extend(_ast_statement_boundary_diagnostics(tokens))

    for tok in tokens:
        t = tok.type

        # Comments and preprocessor lines are transparent to the checks.
        if t in ("comment", "preprocessor"):
            continue

        # SQF arrays use square brackets and do not allow a comma before the
        # closing bracket. Comments and whitespace are ignored by tokenization.
        if t == "rbracket" and previous_significant is not None and previous_significant.type == "comma":
            diags.append(
                Diagnostic(Severity.ERROR, _TRAILING_COMMA, "trailing comma in array",
                           previous_significant.line, previous_significant.column)
            )

        if t in _OPENERS:
            stack.append((tok, _OPENERS[t]))
        elif t in _CLOSERS:
            closer = _CLOSERS[t]
            if not stack or _MATCHING[stack[-1][1]] != closer:
                diags.append(
                    Diagnostic(Severity.ERROR, _CODE_BRACKET, f"unmatched '{closer}'",
                               tok.line, tok.column)
                )
            else:
                stack.pop()

        if t == "string":
            if tok.raw and not tok.raw.endswith(tok.raw[0]):
                diags.append(
                    Diagnostic(Severity.ERROR, _CODE_STRING, "unterminated string",
                               tok.line, tok.column)
                )

        previous_significant = tok

    for opener_tok, opener in stack:
        diags.append(
            Diagnostic(Severity.ERROR, _CODE_BRACKET, f"unclosed '{opener}'",
                       opener_tok.line, opener_tok.column)
        )

    return diags


def check_syntax_text(source: str) -> list[Diagnostic]:
    """Tokenize ``source`` and run ``check_syntax`` over the result."""
    return check_syntax(tokenize(source))


if __name__ == "__main__":
    diags = check_syntax_text('_x = (player;')
    assert any(
        d.severity is Severity.ERROR and d.code == _CODE_BRACKET
        and "unclosed" in d.message and "'('" in d.message
        for d in diags
    ), diags

    diags = check_syntax_text('_x = "abc;')
    assert any(d.code == _CODE_STRING and d.message == "unterminated string" for d in diags), diags

    diags = check_syntax_text('_x = player);')
    assert any(d.code == _CODE_BRACKET and "unmatched" in d.message for d in diags), diags

    d = Diagnostic(Severity.ERROR, "E001", "message text", 3, 5)
    assert format_diagnostic(d) == "line 3, col 5: error [E001]: message text"

    diags = check_syntax_text("_x = [1, 2,];")
    assert len(diags) == 1 and diags[0].code == _TRAILING_COMMA, diags
    assert diags[0].line == 1 and diags[0].column == 11, diags
    assert check_syntax_text("_x = [1, [2, 3]];") == []
    assert check_syntax_text("_x = [1, /* comment */ ];")[0].code == _TRAILING_COMMA
    assert any(d.code == _MISSING_THEN for d in check_syntax_text("if (_x) { hint 'x'; }"))
    assert any(d.code == _BAD_ELSE for d in check_syntax_text("if (_x) then {} else;"))
    assert any(d.code == _MISSING_COMMA for d in check_syntax_text("_x = [1 2];"))
    assert any(d.code == _FOREACH_ORDER for d in check_syntax_text("forEach _items { hint 'x'; };"))

    print("syntax self-test passed")
