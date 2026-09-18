"""Collect mission-defined function symbols for Armalint.

Populates a :class:`~armalint.symbols.SymbolIndex` from two sources:

  * SQF source code — global function definitions of the form
    ``ALT_fnc_foo = { ... };`` (or ``ALT_fnc_foo = compile ...;``).
    Code-valued namespace registrations such as
    ``missionNamespace setVariable ["myCallback", { ... }];`` are indexed too.
  * ``description.ext`` config — ``class CfgFunctions { ... }`` tag/function
    class declarations.

The resulting index feeds the W201 unknown-function checker so that
mission-defined functions are not reported as false positives.
"""

from __future__ import annotations

import re

from .symbols import SymbolIndex
from .tokenizer import tokenize

# Token types that are transparent to collection.
_TRIVIA = frozenset(("comment", "preprocessor"))

# SQF identifiers: letters/underscore, then letters/digits/underscore.
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Function-name marker separating the tag from the function name.
_FNC = "_fnc_"

# Property names that mark a ``CfgFunctions`` class as a function definition
# (mirrors ``armalint.cfgfunctions._FUNCTION_PROPERTIES``). A class below a tag
# whose body assigns one of these is a function; a class without any is a
# structural ``category`` and is not named.
_FUNCTION_PROPERTIES = frozenset(
    ("file", "scriptname", "preinit", "postinit", "prestart", "poststart")
)

# Accepted ``compile``/``compileFinal`` tokens (``compile`` is a keyword, but
# ``compileFinal`` tokenizes as an ident, so match on lowercased value).
_COMPILE_KW = ("compile", "compilefinal")


def _next_significant(tokens: list, index: int) -> int:
    """Index of the first non-trivia token after ``index`` (or ``len(tokens)``)."""
    j = index + 1
    while j < len(tokens) and tokens[j].type in _TRIVIA:
        j += 1
    return j


def collect_code_functions(source: str, index: SymbolIndex, tokens: list | None = None) -> None:
    """Scan SQF ``source`` for global function definitions and add them to ``index``.

    Any global identifier (a bare ``ident`` token, so it cannot start with
    ``_``) that is immediately assigned a code block or a ``compile``/
    ``compileFinal`` expression is registered as a known function:

      * ``NAME = { ... };`` — a code-block function definition.
      * ``NAME = compile ...;`` / ``NAME = compileFinal ...;``.

    ``comment``/``preprocessor`` tokens between the parts are skipped. If the
    identifier contains ``_fnc_``, the leading tag (the part before the first
    ``_fnc_``) is also registered via ``index.add_tag``.
    """
    if tokens is None:
        tokens = tokenize(source)
    n = len(tokens)

    for i, tok in enumerate(tokens):
        if tok.type != "ident":
            continue
        if not _IDENT.match(tok.value) or tok.value.startswith("_"):
            continue

        j = _next_significant(tokens, i)
        if j >= n:
            continue
        if not (tokens[j].type == "operator" and tokens[j].value == "="):
            continue

        k = _next_significant(tokens, j)
        if k >= n:
            continue
        nxt = tokens[k]
        if nxt.type == "lbrace" or nxt.value.lower() in _COMPILE_KW:
            index.add_function(tok.value)
            if _FNC in tok.value:
                index.add_tag(tok.value.split(_FNC, 1)[0])

    # Namespace callback registration, for example:
    #   missionNamespace setVariable ["myCallback", { ... }];
    # The key and code value together are stronger evidence than a naming
    # convention, so register the key even when it has no ``_fnc_`` marker.
    for i, tok in enumerate(tokens):
        if tok.type != "ident" or tok.value.lower() != "setvariable":
            continue
        j = _next_significant(tokens, i)
        if j >= n or tokens[j].type != "lbracket":
            continue
        k = _next_significant(tokens, j)
        if k >= n or tokens[k].type != "string":
            continue
        name = tokens[k].value
        end = k
        has_code = False
        while end < n and tokens[end].type != "rbracket":
            if tokens[end].type == "lbrace" or tokens[end].value.lower() in _COMPILE_KW:
                has_code = True
            end += 1
        if has_code and _IDENT.match(name):
            index.add_function(name)
            if _FNC in name.lower():
                index.add_tag(name.split("_fnc_", 1)[0])


def collect_description_cfg_functions(source: str, index: SymbolIndex) -> None:
    """Parse ``description.ext``-style config for ``class CfgFunctions``.

    Classes one level below ``CfgFunctions`` are tags. Below a tag, a class
    defines a ``<tag>_fnc_<className>`` function only when its body assigns one
    of the function-defining properties (``file``/``scriptName``/``preInit``/
    ``postInit``/``preStart``/``postStart``); an intermediate ``category``
    class that carries none of those is structural and is not named (its
    children are still searched). Missing or malformed input is tolerated: the
    function simply returns without raising.
    """
    tokens = tokenize(source)
    n = len(tokens)

    def skip(i: int, limit: int) -> int:
        while i < limit and tokens[i].type in _TRIVIA:
            i += 1
        return i

    def matching(i: int, limit: int) -> int:
        # ``i`` is at an ``lbrace``; return the index just past its matching
        # ``rbrace`` (or ``limit`` when the group is unbalanced).
        depth = 1
        j = i + 1
        while j < limit:
            t = tokens[j].type
            if t == "lbrace":
                depth += 1
            elif t == "rbrace":
                depth -= 1
                if depth == 0:
                    return j + 1
            j += 1
        return limit

    def class_head(i: int, limit: int) -> tuple[str | None, str, int]:
        # ``i`` is at a ``class`` token; return ``(name, base, lbrace_index)``.
        j = skip(i + 1, limit)
        if j >= limit or tokens[j].type != "ident":
            return None, "", -1
        name = tokens[j].value
        k = skip(j + 1, limit)
        base = ""
        if k < limit and tokens[k].type == "operator" and tokens[k].value == ":":
            m = skip(k + 1, limit)
            if m < limit and tokens[m].type == "ident":
                base = tokens[m].value
                k = skip(m + 1, limit)
        if k < limit and tokens[k].type == "lbrace":
            return name, base, k
        return name, base, -1

    def is_function_body(start: int, end: int) -> bool:
        # True if the class body (``start``..``end``, exclusive) assigns a
        # function-defining property at its top level. Nested classes are
        # skipped, so a category containing a function is not itself a function.
        i = start
        while i < end:
            tok = tokens[i]
            if tok.type == "ident" and tok.value.lower() == "class":
                _name, _base, lbrace = class_head(i, end)
                if lbrace >= 0:
                    i = matching(lbrace, end)  # skip the nested class entirely
                    continue
            elif tok.type == "ident" and tok.value.lower() in _FUNCTION_PROPERTIES:
                nk = skip(i + 1, end)
                if nk < end and tokens[nk].type == "operator" and tokens[nk].value == "=":
                    return True
            i += 1
        return False

    def collect_tag(tag: str, start: int, end: int) -> None:
        # Walk classes nested under a tag and register the function classes.
        # Build a direct-sibling table first so ``class Derived: Base`` can
        # inherit a function marker from a local base class.
        entries: list[tuple[str, str, int, int]] = []
        i = start
        while i < end:
            tok = tokens[i]
            if tok.type == "ident" and tok.value.lower() == "class":
                name, base, lbrace = class_head(i, end)
                if name is None:
                    i += 1
                    continue
                if lbrace >= 0:
                    body_end = matching(lbrace, end)
                    entries.append((name, base, lbrace, body_end))
                    i = body_end
                    continue
            i += 1

        by_name = {name.lower(): (base, body_start, body_end) for name, base, body_start, body_end in entries}
        memo: dict[str, bool] = {}

        def is_entry_function(name: str, base: str, body_start: int, body_end: int, seen: set[str] | None = None) -> bool:
            key = name.lower()
            if key in memo:
                return memo[key]
            direct = is_function_body(body_start + 1, body_end - 1)
            if direct or not base:
                memo[key] = direct
                return direct
            seen = set() if seen is None else seen
            parent_key = base.lower()
            if parent_key in seen or parent_key not in by_name:
                memo[key] = False
                return False
            parent_base, parent_start, parent_end = by_name[parent_key]
            result = is_entry_function(base, parent_base, parent_start, parent_end, seen | {key})
            memo[key] = result
            return result

        for name, base, lbrace, body_end in entries:
            if is_entry_function(name, base, lbrace, body_end):
                index.add_function(f"{tag}{_FNC}{name}")
            collect_tag(tag, lbrace + 1, body_end - 1)

    i = 0
    while i < n:
        tok = tokens[i]
        if tok.type == "ident" and tok.value.lower() == "class":
            name, _base, lbrace = class_head(i, n)
            if name is not None and name.lower() == "cfgfunctions" and lbrace >= 0:
                end = matching(lbrace, n)
                # Direct children of CfgFunctions are tags.
                t = lbrace + 1
                while t < end - 1:
                    tt = tokens[t]
                    if tt.type == "ident" and tt.value.lower() == "class":
                        tag_name, _tag_base, tag_lbrace = class_head(t, end)
                        if tag_name is None:
                            t += 1
                            continue
                        if tag_lbrace >= 0:
                            tag_end = matching(tag_lbrace, end)
                            index.add_tag(tag_name)
                            collect_tag(tag_name.lower(), tag_lbrace + 1, tag_end - 1)
                            t = tag_end
                            continue
                    t += 1
                i = end
                continue
        i += 1


if __name__ == "__main__":
    idx = SymbolIndex()
    collect_code_functions('ALT_fnc_foo = { hint "x"; };', idx)
    assert "alt" in idx.tags, idx.tags
    assert "alt_fnc_foo" in idx.functions, idx.functions
    assert idx.is_known_function("ALT_fnc_foo") is True
    assert idx.is_known_function("ZZZ_fnc_nope") is False

    # Comments and preprocessor lines are skipped.
    idx2 = SymbolIndex()
    collect_code_functions(
        'TAG_fnc_bar /* c */ = /* c */ { 1; };\n'
        'TAG_fnc_baz = compile preprocessFileLineNumbers "x.sqf";',
        idx2,
    )
    assert "tag_fnc_bar" in idx2.functions
    assert "tag_fnc_baz" in idx2.functions
    assert "tag" in idx2.tags

    # Any global ident assigned a code block is a known function.
    idx6 = SymbolIndex()
    collect_code_functions('myCallback = { hint "x"; };', idx6)
    assert idx6.is_known_function("myCallback") is True

    # A plain non-code assignment does NOT register a function.
    idx7 = SymbolIndex()
    collect_code_functions("count = 5;", idx7)
    assert idx7.is_known_function("count") is False
    assert "count" not in idx7.functions

    # Namespace callback registration is discoverable from the key and code
    # value, even when the callback name does not use a function suffix.
    idx8 = SymbolIndex()
    collect_code_functions(
        'missionNamespace setVariable ["myCallback", { hint "x"; }]; '
        'profileNamespace setVariable ["ALT_fnc_fromNamespace", compile "x"];',
        idx8,
    )
    assert idx8.is_known_function("myCallback")
    assert idx8.is_known_function("ALT_fnc_fromNamespace")

    desc = r'''class CfgFunctions {
        class ALT {
            class formatScore { file = "scripts\scoring\fn_formatScore.sqf"; };
            class removeStatusOverlay { file = "..."; };
        };
    };'''
    idx3 = SymbolIndex()
    collect_description_cfg_functions(desc, idx3)
    assert "alt" in idx3.tags, idx3.tags
    assert "alt_fnc_formatscore" in idx3.functions, idx3.functions
    assert "alt_fnc_removestatusoverlay" in idx3.functions, idx3.functions
    assert idx3.is_known_function("ALT_fnc_formatScore") is True
    assert idx3.is_known_function("ALT_fnc_removeStatusOverlay") is True

    # A local derived CfgFunctions class inherits the function marker from its
    # sibling base class; an unresolved external base remains conservative.
    idx_inherit = SymbolIndex()
    collect_description_cfg_functions(
        "class CfgFunctions { class T { "
        'class Base { file = "base.sqf"; }; '
        'class Derived: Base {}; class External: Other {}; }; };',
        idx_inherit,
    )
    assert idx_inherit.functions == {"t_fnc_base", "t_fnc_derived"}, idx_inherit.functions

    # Intermediate category classes are structural: they are not functions,
    # but their children still are.
    idx_cat = SymbolIndex()
    collect_description_cfg_functions(
        "class CfgFunctions { class ace_hearing { class hearing { "
        'class putInEarplugs { file = "..."; }; }; }; };',
        idx_cat,
    )
    assert "ace_hearing" in idx_cat.tags, idx_cat.tags
    assert idx_cat.functions == {"ace_hearing_fnc_putinearplugs"}, idx_cat.functions

    # Missing CfgFunctions: no-op.
    idx4 = SymbolIndex()
    collect_description_cfg_functions("class SomethingElse { class ALT {}; };", idx4)
    assert idx4.counts() == (0, 0), idx4.counts()

    # Malformed/unbalanced input: must not raise.
    idx5 = SymbolIndex()
    collect_description_cfg_functions("class CfgFunctions { class ALT {", idx5)
    collect_description_cfg_functions("", idx5)

    print("collect self-test passed")
