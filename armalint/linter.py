"""Top-level lint orchestration for Armalint."""

from __future__ import annotations

import os
import re

from .collect import collect_code_functions, collect_description_cfg_functions
from .argument_types import check_argument_types
from .commands import check_commands
from .control_flow import check_control_flow
from .definitions import check_definitions
from .diagnostic import Diagnostic, Severity
from .functions import check_functions
from .locals import check_unused_locals
from .preprocessor import find_include_cycles, find_include_guard_issues, find_include_origins, preprocess
from .symbols import SymbolIndex
from .suppression import apply_rule_severities, filter_suppressed, check_suppression_quality
from .syntax import check_syntax
from .style import check_style
from .sqf_contracts import check_sqf_contracts
from .tokenizer import tokenize
from .undefined import check_undefined
from .value_flow import check_value_flow
from .preprocessor_checks import check_preprocessor
from .plugins import PluginRule, run_plugin_checks

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
    rule_severities: dict[str, str] | None = None,
    style: bool = False,
    check_suppressions: bool = False,
    plugin_rules: list[PluginRule] | None = None,
    external_locals: set[str] | frozenset[str] | None = None,
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
    diags.extend(check_preprocessor(source))
    diags.extend(check_syntax(tokens))
    from .ast import parse
    tree = parse(tokens)
    diags.extend(check_control_flow(tree))
    diags.extend(check_definitions(tokens))
    diags.extend(check_unused_locals(tokens))
    # Type inference is file-local. Include expansion is useful for symbol and
    # undefined-variable analysis, but carrying inferred locals across included
    # files creates false positives when common names are reused.
    diags.extend(check_argument_types(tokens, function_signatures, function_return_types, tree.statements))
    diags.extend(check_undefined(tokens, tree, external_locals))
    diags.extend(check_functions(tokens, index=index))
    diags.extend(check_commands(tokens, index=index))
    diags.extend(check_sqf_contracts(tokens))
    diags.extend(check_value_flow(tokens))
    if style:
        diags.extend(check_style(source))
    plugin_diags, plugin_errors = run_plugin_checks(source, filename, plugin_rules or [])
    diags.extend(plugin_diags)
    diags.extend(Diagnostic(Severity.ERROR, "E012", f"plugin check failed: {error}", 1, 1, filename) for error in plugin_errors)

    for d in diags:
        d.file = filename

    adjusted = apply_rule_severities(diags, rule_severities)
    adjusted.extend(check_suppression_quality(source, adjusted, check_suppressions))
    return _deduplicate(filter_suppressed(adjusted, source, ignored_rules))


def lint_file(
    path: str, index: SymbolIndex | None = None,
    function_signatures: dict[str, list[str | None]] | None = None,
    function_return_types: dict[str, str] | None = None,
    ignored_rules: set[str] | frozenset[str] | None = None,
    pretokenized: list | None = None,
    check_unused_locals_enabled: bool = True,
    rule_severities: dict[str, str] | None = None,
    style: bool = False,
    check_suppressions: bool = False,
    plugin_rules: list[PluginRule] | None = None,
    source_text: str | None = None,
    source_cache: dict[str, str] | None = None,
    external_locals: set[str] | frozenset[str] | None = None,
) -> list[Diagnostic]:
    """Read the UTF-8 file at ``path`` and lint its contents.

    ``#include`` directives are resolved before analysis so that locals defined
    in included files are visible to the undefined-variable checker. Each
    diagnostic is remapped back to the original file/line it came from so
    findings still point at the source the user actually wrote.
    """
    if source_text is None:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            source = fh.read()
    else:
        source = source_text

    combined, line_map = preprocess(
        source, path, os.path.dirname(os.path.abspath(path)), source_cache=source_cache,
    )
    include_origins = find_include_origins(path)
    tokens = pretokenized if combined == source and pretokenized is not None else tokenize(combined)
    from .ast import parse
    tree = parse(tokens)

    diags: list[Diagnostic] = []
    diags.extend(check_preprocessor(source))
    normalized_path = os.path.normcase(os.path.abspath(path))
    for cycle_file, cycle_line, cycle_target in find_include_cycles(path):
        if os.path.normcase(os.path.abspath(cycle_file)) == normalized_path:
            diags.append(Diagnostic(
                Severity.WARNING, "W210",
                f"include cycle detected through {cycle_target}",
                cycle_line, 1,
            ))
    for include_file, include_line, include_target in find_include_guard_issues(path):
        if os.path.normcase(os.path.abspath(include_file)) == normalized_path:
            diags.append(Diagnostic(
                Severity.WARNING, "W211",
                f"repeated include without guard: {os.path.basename(include_target)}",
                include_line, 1,
            ))
    diags.extend(check_syntax(tokens))
    diags.extend(check_control_flow(tree))
    diags.extend(check_definitions(tokens))
    source_tokens = tokens if combined == source else tokenize(source)
    source_nodes = tree.statements if combined == source else None
    if check_unused_locals_enabled:
        diags.extend(check_unused_locals(source_tokens))
    diags.extend(check_argument_types(source_tokens, function_signatures, function_return_types, source_nodes))
    diags.extend(check_undefined(tokens, tree, external_locals))
    diags.extend(check_functions(tokens, index=index))
    diags.extend(check_commands(tokens, index=index))
    diags.extend(check_sqf_contracts(source_tokens))
    diags.extend(check_value_flow(source_tokens))
    if style:
        diags.extend(check_style(source))
    plugin_diags, plugin_errors = run_plugin_checks(source, path, plugin_rules or [])
    diags.extend(plugin_diags)
    diags.extend(Diagnostic(Severity.ERROR, "E012", f"plugin check failed: {error}", 1, 1, path) for error in plugin_errors)

    for d in diags:
        if 1 <= d.line <= len(line_map):
            orig_file, orig_line = line_map[d.line - 1]
            d.file = orig_file
            d.line = orig_line
            if os.path.normcase(os.path.abspath(orig_file)) != normalized_path:
                for including_file, include_line in include_origins.get(os.path.normcase(os.path.abspath(orig_file)), []):
                    d.related_locations.append({
                        "file": including_file,
                        "line": include_line,
                        "column": 1,
                        "message": f"included from {os.path.basename(including_file)}",
                    })
        else:
            d.file = path

    adjusted = apply_rule_severities(diags, rule_severities)
    adjusted.extend(check_suppression_quality(source, adjusted, check_suppressions))
    return _deduplicate(filter_suppressed(adjusted, source, ignored_rules))


def build_symbol_index(
    file_paths: list[str], token_cache: dict[str, list] | None = None,
    source_cache: dict[str, str] | None = None,
) -> SymbolIndex:
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
        if source_cache is not None:
            source_cache[path] = source
        if ext in _CONFIG_EXTENSIONS:
            # CBA preprocessor helpers are available only when the project
            # explicitly declares a CBA addon patch.  Merely using a copied
            # CBA macro must remain visible as an unresolved macro/command.
            if re.search(r"requiredAddons\s*\[\]\s*=\s*\{[^}]*\bcba_[A-Za-z0-9_]+", source, re.IGNORECASE | re.DOTALL):
                index.cba_declared = True
            collect_description_cfg_functions(source, index)
            # CBA's standard ``script_component.hpp`` defines the config tag
            # as ``ADDON``.  When that external macro header is unavailable,
            # the config parser quite correctly sees the literal tag
            # ``addon``.  Recover the conventional fully-qualified tag from
            # the addon directory so calls such as A3A_Logistics_fnc_getCargo
            # remain discoverable in a source-tree scan.
            if "addon" in index.tags:
                normalized = os.path.normpath(path)
                parts = normalized.replace("\\", "/").split("/")
                try:
                    addon_pos = next(i for i, part in enumerate(parts) if part.lower() == "addons")
                    component = parts[addon_pos + 1]
                except (StopIteration, IndexError):
                    component = ""
                if component and component.lower() != "addon":
                    prefix = "A3A"
                    for candidate in file_paths:
                        if os.path.basename(candidate).lower() != "script_mod.hpp":
                            continue
                        try:
                            with open(candidate, "r", encoding="utf-8", errors="replace") as fh:
                                text = fh.read()
                        except OSError:
                            continue
                        match = re.search(r"#define\s+PREFIX\s+([A-Za-z0-9_]+)", text)
                        if match:
                            prefix = match.group(1)
                            break
                    index.add_tag(f"{prefix}_{component}")
        else:
            tokens = tokenize(source)
            if token_cache is not None:
                token_cache[path] = tokens
            collect_code_functions(source, index, tokens=tokens)
    return index
