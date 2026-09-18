"""Command-line interface for Armalint."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys

from . import __version__
from .config import (
    extract_function_tags,
    extract_function_type_signatures,
    extract_function_return_types,
    extract_ignored_rules,
    find_config,
    find_mod_cache,
    find_mod_type_cache,
    load_config_file,
)
from .config_lint import lint_config
from .diagnostic import Severity, format_diagnostic
from .linter import build_symbol_index, lint_file, lint_text
from .mods import load_mod_cache
from .mods import load_mod_type_cache

_SCRIPT_EXTENSIONS = (".sqf", ".sqs", ".hpp", ".ext")
_CONFIG_EXTENSIONS = (".hpp", ".ext")


def _is_script_file(name: str) -> bool:
    return name.lower().endswith(_SCRIPT_EXTENSIONS)


def _is_sqf_file(name: str) -> bool:
    """True if ``name`` is an SQF script (linted directly)."""
    return name.lower().endswith(".sqf")


def _is_config_file(name: str) -> bool:
    """True if ``name`` is a class-based config file (linted for embedded SQF)."""
    return name.lower().endswith(_CONFIG_EXTENSIONS)


def _is_ignored(rel_path: str, patterns: list[str]) -> bool:
    """True if ``rel_path`` matches any of the ``fnmatch`` ``patterns``."""
    for pattern in patterns:
        if fnmatch.fnmatch(rel_path, pattern):
            return True
    return False


def _collect_files(path: str, ignores: list[str]) -> list[str]:
    """Expand ``path`` (file or directory) into a sorted list of script files."""
    files: list[str] = []
    if os.path.isdir(path):
        for root, _dirs, names in os.walk(path):
            for name in sorted(names):
                if not _is_script_file(name):
                    continue
                full = os.path.join(root, name)
                rel = os.path.relpath(full, path)
                if _is_ignored(rel, ignores):
                    continue
                files.append(full)
    elif os.path.isfile(path):
        files.append(path)
    return files


_INCLUDE_LINE_RE = re.compile(r'^\s*#\s*include\s+(?:"([^"]*)"|<([^>]*)>)')


def _collect_included_files(files: list[str]) -> set[str]:
    """Return files referenced by local include directives.

    Included fragments are linted on their own for syntax and type errors, but
    unused-local analysis is suppressed because their declarations may be
    consumed by the including file.
    """
    included: set[str] = set()
    pending = list(files)
    seen: set[str] = set()
    while pending:
        path = pending.pop()
        normalized = os.path.normcase(os.path.abspath(path))
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            continue
        base_dir = os.path.dirname(os.path.abspath(path))
        for line in lines:
            match = _INCLUDE_LINE_RE.match(line)
            if not match:
                continue
            target = os.path.normpath(os.path.join(base_dir, match.group(1) or match.group(2)))
            if os.path.isfile(target):
                included.add(os.path.normcase(os.path.abspath(target)))
                pending.append(target)
    return included


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="armalint", description="Arma 3 SQF linter"
    )
    parser.add_argument(
        "paths", nargs="*", help="files or directories to lint"
    )
    parser.add_argument(
        "--file", dest="files", action="append", default=[], metavar="PATH",
        help="lint one specific file (repeatable; equivalent to a positional file)",
    )
    parser.add_argument(
        "--snippet", metavar="SOURCE",
        help="lint an inline SQF snippet instead of files",
    )
    parser.add_argument(
        "--mission", metavar="PATH",
        help="use a mission directory/file as context for --snippet or --file",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit a JSON array of diagnostics",
    )
    parser.add_argument(
        "--ignore",
        action="append",
        default=[],
        metavar="GLOB",
        help="glob pattern to skip (repeatable)",
    )
    parser.add_argument(
        "--ignore-rule", action="append", default=[], metavar="RULE",
        help="suppress a diagnostic rule code for this run (repeatable)",
    )
    parser.add_argument(
        "--rules",
        action="append",
        default=[],
        metavar="RULE",
        help="rules to enable (accepted for forward-compat, currently ignored)",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="path to an armalint.json config file (overrides auto-discovery)",
    )
    parser.add_argument(
        "--version", action="version", version=__version__
    )
    return parser


def _main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    if args.snippet is not None and (args.paths or args.files):
        _build_arg_parser().error("--snippet cannot be combined with files or directories; use --mission for context")
    if args.snippet is None and not (args.paths or args.files):
        if not args.mission:
            _build_arg_parser().error("provide a file/directory, --file PATH, or --snippet SOURCE")

    input_paths = [*args.paths, *args.files]

    if args.snippet is not None:
        context_files = _collect_files(args.mission, args.ignore) if args.mission else []
        context_index = build_symbol_index(context_files)
        context_tags: set[str] = set()
        context_signatures: dict[str, list[str]] = {}
        context_returns: dict[str, str] = {}
        if args.config:
            context_config = load_config_file(args.config)
        elif args.mission and (context_path := find_config(args.mission)):
            context_config = load_config_file(context_path)
        else:
            context_config = {}
        context_tags = extract_function_tags(context_config)
        context_signatures = extract_function_type_signatures(context_config)
        context_returns = extract_function_return_types(context_config)
        context_ignored_rules = extract_ignored_rules(context_config) | {rule.upper() for rule in args.ignore_rule}
        for tag in context_tags:
            context_index.add_tag(tag)
        all_diags = lint_text(
            args.snippet, filename="<snippet>", index=context_index,
            function_signatures=context_signatures, function_return_types=context_returns,
            ignored_rules=context_ignored_rules,
        )
        linted_files = ["<snippet>"]
        if args.json:
            payload = [
                {"file": d.file, "line": d.line, "column": d.column,
                 "severity": d.severity.value, "code": d.code, "message": d.message}
                for d in all_diags
            ]
            print(json.dumps(payload))
        else:
            for d in all_diags:
                print(format_diagnostic(d))
            print(f"{len(linted_files)} snippet(s) linted, {len(all_diags)} diagnostic(s)")
        return 1 if any(d.severity is Severity.ERROR for d in all_diags) else 0

    files: list[str] = []
    for path in input_paths:
        files.extend(_collect_files(path, args.ignore))

    # De-duplicate while preserving determinism, then sort.
    files = sorted(set(files))
    included_files = _collect_included_files(files)

    # Resolve mod function tags from project config, then register them on the
    # symbol index so mod-provided functions are not reported as unknown.
    config_tags: set[str] = set()
    function_signatures: dict[str, list[str]] = {}
    function_return_types: dict[str, str] = {}
    ignored_rules: set[str] = {rule.upper() for rule in args.ignore_rule}
    context_paths = [*input_paths, args.mission] if args.mission else input_paths
    if args.config:
        loaded_config = load_config_file(args.config)
        config_tags = extract_function_tags(loaded_config)
        function_signatures = extract_function_type_signatures(loaded_config)
        function_return_types = extract_function_return_types(loaded_config)
        ignored_rules |= extract_ignored_rules(loaded_config)
    else:
        for path in context_paths:
            cfg_path = find_config(path)
            if cfg_path:
                loaded_config = load_config_file(cfg_path)
                config_tags |= extract_function_tags(loaded_config)
                for name, types in extract_function_type_signatures(loaded_config).items():
                    function_signatures.setdefault(name, types)
                for name, return_type in extract_function_return_types(loaded_config).items():
                    function_return_types.setdefault(name, return_type)
                ignored_rules |= extract_ignored_rules(loaded_config)

    # Build a mission-wide symbol index so mission-defined functions are not
    # reported as unknown (W201) before linting each file.
    index_files = list(files)
    if args.mission:
        index_files.extend(_collect_files(args.mission, args.ignore))
    token_cache = {}
    index = build_symbol_index(sorted(set(index_files)), token_cache=token_cache)
    for tag in config_tags:
        index.add_tag(tag)

    # Also load mod function caches (written by ``python -m armalint.update``)
    # so mod-provided functions are recognized by exact name. Caches are
    # discovered by walking up from each lint path; multiple caches are unioned.
    mod_cache_paths: set[str] = set()
    for path in context_paths:
        cache_path = find_mod_cache(path)
        if cache_path:
            mod_cache_paths.add(cache_path)
    for cache_path in sorted(mod_cache_paths):
        for name in load_mod_cache(cache_path):
            index.add_function(name)
    mod_type_cache_paths = {
        path for path in (find_mod_type_cache(target) for target in context_paths)
        if path
    }
    for cache_path in sorted(mod_type_cache_paths):
        for name, types in load_mod_type_cache(cache_path).items():
            function_signatures.setdefault(name, types)

    # SQF scripts are linted directly. Config files (.hpp/.ext) are class-based,
    # so their structure must not be linted as SQF; only the SQF embedded in
    # their string-valued code fields is analyzed. Legacy SQS and anything else
    # are skipped.
    linted_files: list[str] = []
    all_diags = []
    for f in files:
        if _is_sqf_file(f):
            linted_files.append(f)
            all_diags.extend(lint_file(f, index=index, function_signatures=function_signatures, function_return_types=function_return_types, ignored_rules=ignored_rules, pretokenized=token_cache.get(f), check_unused_locals_enabled=os.path.normcase(os.path.abspath(f)) not in included_files))
        elif _is_config_file(f):
            try:
                with open(f, "r", encoding="utf-8", errors="replace") as fh:
                    source = fh.read()
            except OSError:
                continue
            linted_files.append(f)
            all_diags.extend(lint_config(source, filename=f, index=index, function_signatures=function_signatures, function_return_types=function_return_types, ignored_rules=ignored_rules))

    if args.json:
        payload = [
            {
                "file": d.file,
                "line": d.line,
                "column": d.column,
                "severity": d.severity.value,
                "code": d.code,
                "message": d.message,
            }
            for d in all_diags
        ]
        print(json.dumps(payload))
    else:
        for d in all_diags:
            print(format_diagnostic(d))
        print(f"{len(linted_files)} file(s) linted, {len(all_diags)} diagnostic(s)")

    has_error = any(d.severity is Severity.ERROR for d in all_diags)
    return 1 if has_error else 0


if __name__ == "__main__":
    sys.exit(_main())
