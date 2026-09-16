"""Undefined script-local variable detection for Armalint (W101)."""

from __future__ import annotations

from .diagnostic import Diagnostic, Severity
from .ast import Block, ExitWithStatement, IfStatement, LoopStatement, Node, Statement, SwitchStatement, parse
from .tokenizer import Token, tokenize

_CODE = "W101"

# Script-local variables that are always defined by the SQF engine/context and
# therefore never flagged.
_ALWAYS_DEFINED = frozenset(
    (
        "_this", "_x", "_forEachIndex", "_index", "_exception",
        "_thisScript", "_fnc_scriptName",
        "_thisArgs", "_thisEventHandler", "_thisFSM", "_fnc_scriptNameParent",
    )
)

# Token types that are transparent to variable analysis.
_TRIVIA = frozenset(("comment", "preprocessor"))


def _constant_condition(tokens: list[Token]) -> bool | None:
    """Return a literal boolean condition when its value is unambiguous."""
    visible = [token for token in tokens if token.type not in _TRIVIA]
    if len(visible) != 1 or visible[0].type != "keyword":
        return None
    value = visible[0].value.lower()
    if value == "true":
        return True
    if value in ("false", "nil"):
        return False
    return None


def _next_significant(tokens: list[Token], index: int) -> int:
    """Index of the first non-trivia token after ``index`` (or ``len(tokens)``)."""
    j = index + 1
    while j < len(tokens) and tokens[j].type in _TRIVIA:
        j += 1
    return j


def _is_assignment_lhs(tokens: list[Token], index: int) -> bool:
    """True if the token at ``index`` is immediately followed by ``=``."""
    nxt = _next_significant(tokens, index)
    return (
        nxt < len(tokens)
        and tokens[nxt].type == "operator"
        and tokens[nxt].value == "="
    )


def _collect_string_names(
    tokens: list[Token], bracket_index: int, top_level_only: bool
) -> tuple[list[str], int]:
    """Collect string tokens starting with ``_`` inside the bracket group.

    Returns ``(names, next_index)`` where ``next_index`` is one past the closing
    bracket. When ``top_level_only`` is true, only direct elements of the
    bracket group are collected (nested arrays are skipped).
    """
    names: list[str] = []
    depth = 0
    k = bracket_index
    while k < len(tokens):
        ttype = tokens[k].type
        if ttype == "lbracket":
            depth += 1
        elif ttype == "rbracket":
            depth -= 1
            if depth <= 0:
                k += 1
                break
        elif ttype == "string" and tokens[k].value.startswith("_"):
            if not top_level_only or depth == 1:
                names.append(tokens[k].value)
        k += 1
    return names, k


def _collect_params_names(
    tokens: list[Token], bracket_index: int
) -> tuple[list[str], int]:
    """Collect locals defined by a ``params [...]`` expression.

    Top-level ``string`` tokens starting with ``_`` are collected directly. In
    addition, each nested ``[ ]`` array contributes its first significant token
    when that token is a ``string`` starting with ``_`` (the variable name of an
    optional parameter; the remaining elements are the default value and an
    optional trailing code array).

    Returns ``(names, next_index)`` where ``next_index`` is one past the closing
    bracket.
    """
    names: list[str] = []
    depth = 0
    k = bracket_index
    while k < len(tokens):
        ttype = tokens[k].type
        if ttype == "lbracket":
            depth += 1
            if depth == 2:
                # Nested array within the params list: its first significant
                # element names an optional parameter.
                m = _next_significant(tokens, k)
                if (
                    m < len(tokens)
                    and tokens[m].type == "string"
                    and tokens[m].value.startswith("_")
                ):
                    names.append(tokens[m].value)
        elif ttype == "rbracket":
            depth -= 1
            if depth <= 0:
                k += 1
                break
        elif ttype == "string" and tokens[k].value.startswith("_"):
            if depth == 1:
                names.append(tokens[k].value)
        k += 1
    return names, k


def _scan_tokens(tokens: list[Token], defined: set[str] | None = None) -> tuple[list[Diagnostic], set[str]]:
    """Return W101 warnings for script-local variables used before definition.

    ``defined`` is supplied by the structured walker so each branch can be
    analyzed independently before definitions are merged at control-flow joins.
    """
    defined = set() if defined is None else set(defined)
    diags: list[Diagnostic] = []
    n = len(tokens)
    i = 0

    while i < n:
        tok = tokens[i]
        ttype = tok.type

        if ttype in _TRIVIA:
            i += 1
            continue

        if ttype == "keyword":
            kw = tok.value.lower()

            if kw == "private":
                j = _next_significant(tokens, i)
                if j < n and tokens[j].type == "lbracket":
                    # private ["_a", "_b"]; — strings inside the brackets.
                    names, i = _collect_string_names(tokens, j, top_level_only=False)
                    defined.update(names)
                    continue
                # private _a; / private _a = ...; — local(s) before ';' or '='.
                k = j
                while k < n and tokens[k].type == "local":
                    defined.add(tokens[k].value)
                    k += 1
                i = k
                continue

            if kw == "params":
                j = _next_significant(tokens, i)
                if j < n and tokens[j].type == "lbracket":
                    # params ["_a", ["_b", 2], ["_c", false]]; — top-level
                    # strings plus the first element of each nested array.
                    names, i = _collect_params_names(tokens, j)
                    defined.update(names)
                    continue
                i += 1
                continue

            if kw == "for":
                # for "_i" from ... — first string after 'for' defines the local.
                j = _next_significant(tokens, i)
                if j < n and tokens[j].type == "string" and tokens[j].value.startswith("_"):
                    defined.add(tokens[j].value)
                i += 1
                continue

            i += 1
            continue

        if ttype == "local":
            if _is_assignment_lhs(tokens, i):
                defined.add(tok.value)
            elif tok.value not in _ALWAYS_DEFINED and tok.value not in defined:
                diags.append(
                    Diagnostic(
                        Severity.WARNING,
                        _CODE,
                        f"possible undefined variable: {tok.value}",
                        tok.line,
                        tok.column,
                    )
                )
            i += 1
            continue

        i += 1

    return diags, defined


def _private_names(nodes: list[Node]) -> set[str]:
    names: set[str] = set()
    for node in nodes:
        if not isinstance(node, Statement):
            continue
        tokens = node.tokens
        for i, token in enumerate(tokens):
            if token.type != "keyword" or token.value.lower() != "private":
                continue
            j = _next_significant(tokens, i)
            if j < len(tokens) and tokens[j].type == "local":
                names.add(tokens[j].value)
            elif j < len(tokens) and tokens[j].type == "lbracket":
                names.update(name for name in _collect_string_names(tokens, j, True)[0])
    return names


def _walk_node(node: Node, incoming: set[str], scoped: bool = False) -> tuple[list[Diagnostic], set[str]]:
    """Analyze structured nodes and conservatively merge branch definitions."""
    if isinstance(node, Statement):
        diags, defined = _scan_tokens(node.tokens, incoming)
        for embedded in node.embedded:
            embedded_diags, _ = _walk_node(embedded, set(defined), True)
            diags.extend(embedded_diags)
        unique: dict[tuple[int, int, str, str], Diagnostic] = {}
        for diagnostic in diags:
            unique[(diagnostic.line, diagnostic.column, diagnostic.code, diagnostic.message)] = diagnostic
        diags = list(unique.values())
        return diags, defined
    if isinstance(node, Block):
        diags: list[Diagnostic] = []
        defined = set(incoming)
        for child in node.statements:
            child_diags, defined = _walk_node(child, defined, isinstance(child, Block))
            diags.extend(child_diags)
        if scoped:
            defined.difference_update(_private_names(node.statements) - incoming)
        return diags, defined
    if isinstance(node, IfStatement):
        diags, _ = _scan_tokens(node.condition, incoming)
        constant = _constant_condition(node.condition)
        if constant is True and node.then_block:
            then_diags, then_defined = _walk_node(node.then_block, set(incoming), True)
            diags.extend(then_diags)
            return diags, then_defined
        if constant is False:
            if node.else_block is not None:
                else_diags, else_defined = _walk_node(node.else_block, set(incoming), True)
                diags.extend(else_diags)
                return diags, else_defined
            return diags, set(incoming)
        then_diags, then_defined = _walk_node(node.then_block, set(incoming), True) if node.then_block else ([], set(incoming))
        diags.extend(then_diags)
        if node.else_block is None:
            return diags, set(incoming)
        else_diags, else_defined = _walk_node(node.else_block, set(incoming), True)
        diags.extend(else_diags)
        return diags, then_defined & else_defined
    if isinstance(node, LoopStatement):
        loop_in = set(incoming)
        if node.kind == "for":
            for token in node.header:
                if token.type == "string" and token.value.startswith("_"):
                    loop_in.add(token.value)
                    break
        diags, _ = _scan_tokens(node.header, loop_in)
        if node.body:
            body_diags, _ = _walk_node(node.body, loop_in, True)
            diags.extend(body_diags)
        return diags, set(incoming)
    if isinstance(node, ExitWithStatement):
        return _walk_node(node.body, set(incoming), True) if node.body else ([], set(incoming))
    if isinstance(node, SwitchStatement):
        diags, _ = _scan_tokens(node.expression, incoming)
        branches: list[set[str]] = [set(incoming)]
        for case in node.cases:
            if case.body:
                case_diags, case_defined = _walk_node(case.body, set(incoming), True)
                diags.extend(case_diags)
                branches.append(case_defined)
        merged = set.intersection(*branches) if branches else set(incoming)
        return diags, merged
    return [], set(incoming)


def check_undefined(tokens: list[Token]) -> list[Diagnostic]:
    """Return W101 warnings with conservative branch-aware definition merging."""
    tree = parse(tokens)
    diags: list[Diagnostic] = []
    defined: set[str] = set()
    for node in tree.statements:
        node_diags, defined = _walk_node(node, defined)
        diags.extend(node_diags)
    return diags


def check_undefined_text(source: str) -> list[Diagnostic]:
    """Tokenize ``source`` and run ``check_undefined`` over the result."""
    return check_undefined(tokenize(source))


if __name__ == "__main__":
    assert check_undefined_text("_x = 1; hint str _x;") == []

    diags = check_undefined_text("hint str _y;")
    assert len(diags) == 1, diags
    assert diags[0].severity is Severity.WARNING and diags[0].code == _CODE
    assert diags[0].message == "possible undefined variable: _y"
    assert (diags[0].line, diags[0].column) == (1, 10)

    assert check_undefined_text("private _a; hint str _a;") == []
    assert check_undefined_text("hint str _this;") == []
    assert check_undefined_text('if (true) then { _a = 1; }; hint str _a;') == []
    assert len(check_undefined_text('if (false) then { _a = 1; }; hint str _a;')) == 1

    # Arma 3 event-handler magic variables are always defined.
    assert check_undefined_text("hint str _thisArgs; hint str _thisEventHandler;") == []
    assert check_undefined_text("hint str _thisFSM; hint str _fnc_scriptNameParent;") == []

    # Additional rule coverage.
    assert check_undefined_text('private ["_a", "_b"]; hint str _a; hint str _b;') == []
    assert check_undefined_text('params ["_a", ["_b", 2]]; hint str _a;') == []
    assert check_undefined_text('for "_i" from 0 to 1 do { hint str _i; };') == []
    assert check_undefined_text("_x = _x + 1;") == []

    diags = check_undefined_text("hint str _z; _z = 5;")
    assert len(diags) == 1 and diags[0].message == "possible undefined variable: _z", diags

    # Nested params defaults define their first-element local.
    assert check_undefined_text('params ["_a", ["_b", 0]]; hint str _b;') == []
    assert check_undefined_text('params [["_a", 1], "_b", ["_c", false]]; hint str _a; hint str _c;') == []

    diags = check_undefined_text('params ["_a", ["_b", 0]]; hint str _missing;')
    assert len(diags) == 1, diags
    assert diags[0].message == "possible undefined variable: _missing", diags

    # Definitions are merged only when both branches provide them.
    assert check_undefined_text('if (true) then { _value = 1; } else { _value = 2; }; hint str _value;') == []
    branch_only = check_undefined_text('if (_condition) then { _value = 1; }; hint str _value;')
    assert sum("_value" in diagnostic.message for diagnostic in branch_only) == 1, branch_only
    assert check_undefined_text('if (true) then { private _inner; _inner = 1; hint str _inner; };') == []
    private_leak = check_undefined_text('if (true) then { private _inner; _inner = 1; }; hint str _inner;')
    assert len(private_leak) == 1 and "_inner" in private_leak[0].message, private_leak
    embedded_loop = check_undefined_text('_result = ({ hint str _missingInLoop; } forEach allUnits);')
    assert len(embedded_loop) == 1 and "_missingInLoop" in embedded_loop[0].message, embedded_loop

    print("undefined self-test passed")
