"""Top-level lint orchestration for Armalint."""

from __future__ import annotations

import os

from .collect import collect_code_functions, collect_description_cfg_functions
from .argument_types import check_argument_types
from .commands import check_commands
from .control_flow import check_control_flow
from .definitions import check_definitions
from .diagnostic import Diagnostic
from .functions import check_functions
from .preprocessor import preprocess
from .symbols import SymbolIndex
from .suppression import filter_suppressed
from .syntax import check_syntax
from .tokenizer import tokenize
from .undefined import check_undefined

# Extensions treated as config files for symbol collection.
_CONFIG_EXTENSIONS = (".hpp", ".ext", ".cpp", ".cfg")


def _deduplicate(diags: list[Diagnostic]) -> list[Diagnostic]:
    """Drop identical findings emitted by overlapping analysis passes."""
    result: list[Diagnostic] = []
    seen: set[tuple[str, int, int, str, str, str]] = set()
    for diagnostic in diags:
        key = (
            diagnostic.file,
            diagnostic.line,
            diagnostic.column,
            diagnostic.severity.value,
            diagnostic.code,
            diagnostic.message,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(diagnostic)
    return result


def lint_text(
    source: str, filename: str = "", index: SymbolIndex | None = None,
    function_signatures: dict[str, list[str | None]] | None = None,
    function_return_types: dict[str, str] | None = None,
    ignored_rules: set[str] | frozenset[str] | None = None,
) -> list[Diagnostic]:
    """Run all analyzers over ``source`` and return their diagnostics.

    The source is tokenized once and the token stream is shared across the
    syntax, undefined-variable, and function/command analyzers. Each resulting
    diagnostic has its ``file`` field set to ``filename``.

    ``index`` (optional) is a :class:`~armalint.symbols.SymbolIndex` used by the
    function/command analyzer to recognize mission-defined functions.
    """
    tokens = tokenize(source)

    diags: list[Diagnostic] = []
    diags.extend(check_syntax(tokens))
    from .ast import parse
    diags.extend(check_control_flow(parse(tokens)))
    diags.extend(check_definitions(tokens))
    # Type inference is file-local. Include expansion is useful for symbol and
    # undefined-variable analysis, but carrying inferred locals across included
    # files creates false positives when common names are reused.
    diags.extend(check_argument_types(tokens, function_signatures, function_return_types))
    diags.extend(check_undefined(tokens))
    diags.extend(check_functions(tokens, index=index))
    diags.extend(check_commands(tokens, index=index))

    for d in diags:
        d.file = filename

    return _deduplicate(filter_suppressed(diags, source, ignored_rules))


def lint_file(
    path: str, index: SymbolIndex | None = None,
    function_signatures: dict[str, list[str | None]] | None = None,
    function_return_types: dict[str, str] | None = None,
    ignored_rules: set[str] | frozenset[str] | None = None,
) -> list[Diagnostic]:
    """Read the UTF-8 file at ``path`` and lint its contents.

    ``#include`` directives are resolved before analysis so that locals defined
    in included files are visible to the undefined-variable checker. Each
    diagnostic is remapped back to the original file/line it came from so
    findings still point at the source the user actually wrote.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        source = fh.read()

    combined, line_map = preprocess(
        source, path, os.path.dirname(os.path.abspath(path))
    )
    tokens = tokenize(combined)
    from .ast import parse
    tree = parse(tokens)

    diags: list[Diagnostic] = []
    diags.extend(check_syntax(tokens))
    diags.extend(check_control_flow(tree))
    diags.extend(check_definitions(tokens))
    diags.extend(check_argument_types(tokenize(source), function_signatures, function_return_types))
    diags.extend(check_undefined(tokens))
    diags.extend(check_functions(tokens, index=index))
    diags.extend(check_commands(tokens, index=index))

    for d in diags:
        if 1 <= d.line <= len(line_map):
            orig_file, orig_line = line_map[d.line - 1]
            d.file = orig_file
            d.line = orig_line
        else:
            d.file = path

    return _deduplicate(filter_suppressed(diags, source, ignored_rules))


def build_symbol_index(file_paths: list[str]) -> SymbolIndex:
    """Build a mission-wide :class:`SymbolIndex` from ``file_paths``.

    For each path, the file is read as UTF-8 (with ``errors="replace"``) and the
    appropriate collector is invoked based on its extension:

      * ``.hpp``/``.ext``/``.cpp``/``.cfg`` -> :func:`collect_description_cfg_functions`
      * ``.sqf``                            -> :func:`collect_code_functions`

    Other extensions (e.g. ``.sqs``) and missing/unreadable files are ignored.
    """
    index = SymbolIndex()
    for path in file_paths:
        ext = os.path.splitext(path)[1].lower()
        if ext not in _CONFIG_EXTENSIONS and ext != ".sqf":
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                source = fh.read()
        except OSError:
            continue
        if ext in _CONFIG_EXTENSIONS:
            collect_description_cfg_functions(source, index)
        else:
            collect_code_functions(source, index)
    return index
