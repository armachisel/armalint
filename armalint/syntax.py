"""Syntax checks for Armalint (operates on the tokenizer's token stream)."""

from __future__ import annotations

from .diagnostic import Diagnostic, Severity, format_diagnostic
from .ast import Block, ExitWithStatement, IfStatement, LoopStatement, Node, Statement, SwitchStatement, TryCatchStatement, parse
from .tokenizer import Token, tokenize
from .known import is_known

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
_INVALID_POSTFIX_COMMAND = "E009"


def _significant(tokens: list[Token]) -> list[Token]:
    return [t for t in tokens if t.type not in ("comment", "preprocessor", "eof")]


def _matching_closes(tokens: list[Token]) -> dict[int, int]:
    """Build opener-to-closer indexes in one pass.

    The previous implementation rescanned the remainder of the token stream
    for every opener. Large mission files contain thousands of nested arrays
    and code blocks, making that approach quadratic. Invalid/mismatched groups
    are simply omitted; callers retain their existing conservative behavior.
    """
    expected = {"lparen": "rparen", "lbracket": "rbracket", "lbrace": "rbrace"}
    stack: list[tuple[int, str]] = []
    closes: dict[int, int] = {}
    for index, token in enumerate(tokens):
        kind = token.type
        if kind in expected:
            stack.append((index, expected[kind]))
        elif kind in _CLOSERS:
            if not stack or stack[-1][1] != kind:
                continue
            opener, _ = stack.pop()
            closes[opener] = index
    return closes


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
    matching_closes = _matching_closes(sig)

    # A two-token statement of ``value command;`` is never a complete SQF
    # command expression when the second token is a known command. This catches
    # postfix unary-command mistakes such as ``_nodeIds reverse;``.
    statement: list[Token] = []
    for tok in sig + [Token("semicolon", ";", 0, 0, ";")]:
        if tok.type == "semicolon":
            if (len(statement) == 2 and statement[0].type in ("local", "ident")
                    and statement[0].type != "keyword"
                    and not is_known(statement[0].value)
                    and statement[1].type == "ident" and is_known(statement[1].value)):
                command = statement[1]
                diags.append(Diagnostic(Severity.ERROR, _INVALID_POSTFIX_COMMAND,
                                        f"invalid postfix command expression; use '{command.value} <value>' or assign its result",
                                        command.line, command.column))
            statement = []
        else:
            statement.append(tok)

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
            close = matching_closes.get(condition_start)
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
            close = matching_closes.get(i)
            if close is not None:
                for left, right in zip(sig[i + 1:close], sig[i + 2:close + 1]):
                    if left.type in ("number", "string") and right.type in ("number", "string"):
                        diags.append(Diagnostic(Severity.ERROR, _MISSING_COMMA, "missing comma between array elements", right.line, right.column))
                        break
        # A command that consumes a code block must be terminated before the
        # next statement.  A final expression before the enclosing `}` is
        # valid SQF and is intentionally left alone.
        if tok.type == "lbrace" and i > 0 and sig[i - 1].type == "ident" and is_known(sig[i - 1].value):
            close = matching_closes.get(i)
            if close is not None and close + 1 < len(sig):
                nxt = sig[close + 1]
                # Operators, delimiters, and control-flow keywords commonly
                # continue the enclosing expression (`findIf {...} >= 0`,
                # `isNil {...} exitWith {...}`, etc.).  A missing terminator
                # is unambiguous only when another identifier/local starts a
                # new statement.
                # A known command immediately following the block is usually
                # the next leg of a postfix command chain, e.g.
                # ``items apply { str _x } joinString ","``.  Treating that
                # command as a new statement produces a false E008 at the
                # closing brace.  Unknown identifiers remain conservative:
                # they still indicate a likely missing terminator.
                if (nxt.type in ("ident", "local")
                        and nxt.value.lower() not in ("isequalto", "isnotequalto")
                        and not is_known(nxt.value)):
                    diags.append(Diagnostic(
                        Severity.ERROR, _MISSING_SEMICOLON,
                        "missing semicolon after command with code block",
                        nxt.line, nxt.column,
                    ))
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
