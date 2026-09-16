"""Command-line interface for Armalint."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys

from . import __version__
from .config import (
    extract_function_tags,
    extract_function_type_signatures,
    find_config,
    find_mod_cache,
    find_mod_type_cache,
    load_config_file,
)
from .config_lint import lint_config
from .diagnostic import Severity, format_diagnostic
from .linter import build_symbol_index, lint_file
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


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="armalint", description="Arma 3 SQF linter"
    )
    parser.add_argument(
        "paths", nargs="+", help="files or directories to lint"
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

    files: list[str] = []
    for path in args.paths:
        files.extend(_collect_files(path, args.ignore))

    # De-duplicate while preserving determinism, then sort.
    files = sorted(set(files))

    # Resolve mod function tags from project config, then register them on the
    # symbol index so mod-provided functions are not reported as unknown.
    config_tags: set[str] = set()
    function_signatures: dict[str, list[str]] = {}
    if args.config:
        loaded_config = load_config_file(args.config)
        config_tags = extract_function_tags(loaded_config)
        function_signatures = extract_function_type_signatures(loaded_config)
    else:
        for path in args.paths:
            cfg_path = find_config(path)
            if cfg_path:
                loaded_config = load_config_file(cfg_path)
                config_tags |= extract_function_tags(loaded_config)
                for name, types in extract_function_type_signatures(loaded_config).items():
                    function_signatures.setdefault(name, types)

    # Build a mission-wide symbol index so mission-defined functions are not
    # reported as unknown (W201) before linting each file.
    index = build_symbol_index(files)
    for tag in config_tags:
        index.add_tag(tag)

    # Also load mod function caches (written by ``python -m armalint.update``)
    # so mod-provided functions are recognized by exact name. Caches are
    # discovered by walking up from each lint path; multiple caches are unioned.
    mod_cache_paths: set[str] = set()
    for path in args.paths:
        cache_path = find_mod_cache(path)
        if cache_path:
            mod_cache_paths.add(cache_path)
    for cache_path in sorted(mod_cache_paths):
        for name in load_mod_cache(cache_path):
            index.add_function(name)
    mod_type_cache_paths = {
        path for path in (find_mod_type_cache(target) for target in args.paths)
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
            all_diags.extend(lint_file(f, index=index, function_signatures=function_signatures))
        elif _is_config_file(f):
            try:
                with open(f, "r", encoding="utf-8", errors="replace") as fh:
                    source = fh.read()
            except OSError:
                continue
            linted_files.append(f)
            all_diags.extend(lint_config(source, filename=f, index=index, function_signatures=function_signatures))

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
