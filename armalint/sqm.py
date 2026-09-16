"""Extract addon names from Arma 3 ``mission.sqm`` files (text form).

Phase 1 of mod function-name extraction: this module only parses the de-RAP'd
text representation of a ``mission.sqm`` (specifically the ``addOns[]`` and
``addOnsAuto[]`` arrays). It deliberately does *not* read PBO or ``config.bin``
payloads.
"""

from __future__ import annotations

from .tokenizer import Token, tokenize

# Array property names to scan for (SQM is case-insensitive).
_ADDON_ARRAYS = ("addons", "addonsauto")

# Token types that may appear between significant tokens and are ignored.
_TRIVIA = ("comment", "preprocessor")


def _next_significant(tokens: list[Token], i: int) -> int:
    """Index of the first non-trivia token at or after ``i``."""
    while i < len(tokens) and tokens[i].type in _TRIVIA:
        i += 1
    return i


def _match_balanced(
    tokens: list[Token], i: int, open_t: str, close_t: str
) -> int | None:
    """If ``tokens[i]`` opens ``open_t``, return the index just past its matching ``close_t``.

    Returns ``None`` when ``tokens[i]`` is not ``open_t`` or the group is
    unbalanced.
    """
    if i >= len(tokens) or tokens[i].type != open_t:
        return None
    depth = 1
    j = i + 1
    while j < len(tokens):
        t = tokens[j].type
        if t == open_t:
            depth += 1
        elif t == close_t:
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return None


def extract_addons(text: str) -> list[str]:
    """Parse ``text`` (a mission.sqm, text form) and return its addon names.

    Scans for ``addOns[]``/``addOnsAuto[]`` array declarations and collects the
    ``string`` values inside their ``{ ... }`` bodies. The optional ``[]``
    subscript and a parenthesized variant are accepted, and an ``=`` must
    precede the body ``{``. Comments and preprocessor lines between tokens are
    ignored.

    Addons are deduplicated case-insensitively, keep their first-seen spelling,
    and are returned in order of first appearance. Malformed input never
    raises: whatever is found is returned.
    """
    tokens = tokenize(text)
    result: list[str] = []
    seen: set[str] = set()

    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok.type == "ident" and tok.value.lower() in _ADDON_ARRAYS:
            j = _next_significant(tokens, i + 1)

            # Optional ``[]`` subscript (e.g. ``addOns[] = { ... }``).
            k = _match_balanced(tokens, j, "lbracket", "rbracket")
            if k is not None:
                j = _next_significant(tokens, k)
            elif j < n and tokens[j].type == "lbracket":
                # Unbalanced ``[``: skip just the bracket and keep going.
                j = _next_significant(tokens, j + 1)

            # Optional parenthesized variant (e.g. ``addOns() = { ... }``).
            k = _match_balanced(tokens, j, "lparen", "rparen")
            if k is not None:
                j = _next_significant(tokens, k)

            # Require ``=`` before the array body.
            if j < n and tokens[j].type == "operator" and tokens[j].value == "=":
                j = _next_significant(tokens, j + 1)
            else:
                i += 1
                continue

            # Optional parentheses around the body value.
            k = _match_balanced(tokens, j, "lparen", "rparen")
            if k is not None:
                j = _next_significant(tokens, k)

            if j < n and tokens[j].type == "lbrace":
                end = _match_balanced(tokens, j, "lbrace", "rbrace")
                if end is None:
                    end = n  # Unbalanced body: collect strings to EOF.
                for k in range(j + 1, end):
                    item = tokens[k]
                    if item.type == "string":
                        key = item.value.lower()
                        if key not in seen:
                            seen.add(key)
                            result.append(item.value)
                i = end
                continue

        i += 1

    return result


if __name__ == "__main__":
    text = """\
version=54;
class Mission
{
    addOns[]=
    {
        "A3_Characters_F",
        "ace_main",
        "cba_main",
        "rhsusf_main"
    };
    addOnsAuto[]=
    {
        "A3_Modules_F",
        "ace_main"
    };
};
"""
    assert extract_addons(text) == [
        "A3_Characters_F",
        "ace_main",
        "cba_main",
        "rhsusf_main",
        "A3_Modules_F",
    ], extract_addons(text)

    # Dedupe is case-insensitive; the first-seen spelling is kept.
    assert extract_addons('addOns[]={"A3_Data_F","a3_data_f","ace_main"};') == [
        "A3_Data_F",
        "ace_main",
    ]

    # Array-omit and parenthesized variants are tolerated.
    assert extract_addons('addOns = {"ace_main"};') == ["ace_main"]
    assert extract_addons('addOns() = {"ace_main"};') == ["ace_main"]

    # Comments/preprocessor between tokens are skipped; garbage never raises.
    assert extract_addons(
        '#include "x"\naddOns /* hi */ [] /* there */ = { "ace_main", };'
    ) == ["ace_main"]
    assert extract_addons("not an sqm at all") == []
    assert extract_addons("") == []

    print("sqm self-test passed")
