"""Command-line interface for Armalint."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import time

from . import __version__
from .config import (
    extract_function_tags,
    extract_function_type_signatures,
    extract_function_return_types,
    extract_ignored_rules,
    extract_external_locals,
    extract_ignore_patterns,
    extract_rule_severities,
    extract_presets,
    extract_plugins,
    validate_config,
    find_config,
    discover_configs,
    find_mod_cache,
    find_mod_type_cache,
    load_config_file,
    extract_dependencies,
)
from .config_lint import lint_config
from .contracts import discover_external_locals
from .diagnostic import Diagnostic, Severity, format_diagnostic
from .linter import build_symbol_index, lint_file, lint_text
from .mods import load_mod_cache
from .mods import load_mod_type_cache
from .sqm import check_mission_sqm
from .rules import metadata as rule_metadata
from .rules import PRESETS, RULES, RULE_CATEGORIES
from .plugins import load_plugins
from .style import apply_safe_fix_edits, safe_fix_edits

_SCRIPT_EXTENSIONS = (".sqf", ".sqs", ".hpp", ".ext", ".sqm")
_CONFIG_EXTENSIONS = (".hpp", ".ext")


def _is_script_file(name: str) -> bool:
    return name.lower().endswith(_SCRIPT_EXTENSIONS)


def _is_sqf_file(name: str) -> bool:
    """True if ``name`` is an SQF script (linted directly)."""
    return name.lower().endswith(".sqf")


def _is_config_file(name: str) -> bool:
    """True if ``name`` is a class-based config file (linted for embedded SQF)."""
    return name.lower().endswith(_CONFIG_EXTENSIONS)


def _is_mission_file(name: str) -> bool:
    return name.lower().endswith(".sqm")


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


def _collect_included_files(files: list[str], source_cache: dict[str, str] | None = None) -> set[str]:
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
        normalized_path = os.path.normcase(os.path.abspath(path))
        cached_source = None
        if source_cache is not None:
            cached_source = source_cache.get(path) or source_cache.get(normalized_path)
        if cached_source is not None:
            lines = cached_source.splitlines()
        else:
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
    parser.add_argument("--sarif", action="store_true", help="emit SARIF 2.1.0 diagnostics")
    parser.add_argument("--checkstyle", action="store_true", help="emit Checkstyle XML diagnostics")
    parser.add_argument("--style", action="store_true", help="enable optional source style checks")
    parser.add_argument("--fix", action="store_true", help="apply safe formatting fixes and write changed files")
    parser.add_argument("--fix-preview", action="store_true", help="emit safe autofix edits as JSON without changing files")
    parser.add_argument("--diff", nargs="?", const="HEAD", metavar="REF", help="report only diagnostics on lines changed from REF (default: HEAD)")
    parser.add_argument("--diff-staged", action="store_true", help="report only diagnostics in the staged Git index")
    parser.add_argument("--fail-on", choices=("error", "warning", "info", "none"), default="error", help="minimum severity that makes the command fail (default: error)")
    parser.add_argument("--github-actions", action="store_true", help="emit GitHub Actions workflow-command annotations")
    parser.add_argument("--timings", action="store_true", help="report scan duration and phase timings as JSON on stderr")
    parser.add_argument("--max-issues", type=int, metavar="N", help="stop after reporting at most N diagnostics")
    parser.add_argument("--check-suppressions", action="store_true", help="report unjustified and unused inline suppressions")
    parser.add_argument("--baseline", metavar="PATH", help="suppress diagnostics recorded in a JSON baseline file")
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
        "--external-local", action="append", default=[], metavar="NAME",
        help="declare a local supplied by an external call-compile contract (repeatable)",
    )
    parser.add_argument(
        "--rules",
        action="append",
        default=[],
        metavar="RULE",
        help="rule code or category to select (repeatable)",
    )
    parser.add_argument(
        "--preset", action="append", default=[], metavar="NAME",
        help="named rule preset: recommended, strict, style, or performance",
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


def _git_changed_lines(reference: str, paths: list[str], staged: bool = False) -> dict[str, set[int]]:
    """Return changed line numbers for tracked and untracked files."""
    changed: dict[str, set[int]] = {}
    pathspecs = [os.path.relpath(path, os.getcwd()) if os.path.isabs(path) else path for path in paths]
    command = ["git", "diff", "--cached" if staged else "--unified=0"]
    if staged:
        command.extend(["--unified=0"])
    else:
        command.append(reference)
    command.extend(["--", *pathspecs])
    try:
        proc = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError:
        return changed
    current: str | None = None
    for line in proc.stdout.splitlines():
        if line.startswith("+++ b/"):
            current = os.path.abspath(line[6:])
            changed.setdefault(os.path.normcase(current), set())
            continue
        if current is None or not line.startswith("@@"):
            continue
        match = re.search(r"\+(\d+)(?:,(\d+))?", line)
        if not match:
            continue
        start = int(match.group(1))
        count = int(match.group(2) or "1")
        if count:
            changed[os.path.normcase(current)].update(range(start, start + count))
    # New files are not present in ``git diff HEAD`` until staged. Include all
    # their lines so a first CI run cannot silently miss diagnostics.
    try:
        untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "--", *pathspecs], capture_output=True, text=True, check=False)
        for item in untracked.stdout.splitlines():
            full = os.path.normcase(os.path.abspath(item))
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as fh:
                    changed[full] = set(range(1, len(fh.read().splitlines()) + 1))
            except OSError:
                continue
    except OSError:
        pass
    return changed


def _github_annotation(diagnostic) -> str:
    file_name = str(diagnostic.file or "").replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A").replace(":", "%3A").replace(",", "%2C")
    message = diagnostic.message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    command = "error" if diagnostic.severity is Severity.ERROR else "warning" if diagnostic.severity is Severity.WARNING else "notice"
    return f"::{command} file={file_name},line={diagnostic.line},col={diagnostic.column},title={diagnostic.code}::{message}"


def _checkstyle_output(diagnostics) -> str:
    """Render diagnostics in the Checkstyle XML interchange format."""
    grouped: dict[str, list] = {}
    for diagnostic in diagnostics:
        grouped.setdefault(diagnostic.file or "<snippet>", []).append(diagnostic)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<checkstyle version="1.0">']
    for file_name, items in grouped.items():
        lines.append(f'  <file name="{html.escape(file_name, quote=True)}">')
        for diagnostic in items:
            lines.append(
                f'    <error line="{diagnostic.line}" column="{diagnostic.column}" '
                f'severity="{html.escape(diagnostic.severity.value)}" '
                f'message="{html.escape(diagnostic.message, quote=True)}" '
                f'source="armalint.{html.escape(diagnostic.code, quote=True)}" />'
            )
        lines.append("  </file>")
    lines.append("</checkstyle>")
    return "\n".join(lines)


def _main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    if args.max_issues is not None and args.max_issues < 1:
        _build_arg_parser().error("--max-issues must be at least 1")
    started_at = time.perf_counter()
    timings: dict[str, float | int] = {}
    config_issues: dict[str, list[str]] = {}
    checked_configs: dict[str, dict] = {}
    plugin_rules = []
    plugin_errors: list[str] = []

    def load_checked(path: str) -> dict:
        absolute = os.path.abspath(path)
        if absolute not in checked_configs:
            loaded = load_config_file(path)
            checked_configs[absolute] = loaded
            config_issues[absolute] = validate_config(loaded)
        return checked_configs[absolute]

    baseline_keys: set[str] = set()
    if args.baseline:
        try:
            with open(args.baseline, "r", encoding="utf-8") as fh:
                baseline = json.load(fh)
            entries = baseline.get("diagnostics", []) if isinstance(baseline, dict) else baseline if isinstance(baseline, list) else []
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict):
                        baseline_keys.add(_diagnostic_fingerprint(entry.get("code", entry.get("ruleId", "")), entry.get("file", ""), entry.get("line", entry.get("startLine", 0)), entry.get("column", entry.get("startColumn", 0)), entry.get("message", "")))
        except (OSError, ValueError, TypeError):
            _build_arg_parser().error("--baseline must point to a readable JSON baseline")

    if args.snippet is not None and (args.paths or args.files):
        _build_arg_parser().error("--snippet cannot be combined with files or directories; use --mission for context")
    if args.snippet is not None and args.diff:
        _build_arg_parser().error("--diff requires files or a directory, not --snippet")
    if args.snippet is not None and args.diff_staged:
        _build_arg_parser().error("--diff-staged requires files or a directory, not --snippet")
    if args.snippet is not None and (args.fix or args.fix_preview):
        _build_arg_parser().error("autofixes require files or a directory, not --snippet")
    if args.diff and args.diff_staged:
        _build_arg_parser().error("--diff and --diff-staged cannot be combined")
    if args.snippet is None and not (args.paths or args.files):
        if not args.mission:
            _build_arg_parser().error("provide a file/directory, --file PATH, or --snippet SOURCE")
    unknown_presets = [name for name in args.preset if name.strip().lower() not in PRESETS]
    if unknown_presets:
        _build_arg_parser().error(f"unknown rule preset: {unknown_presets[0]}")

    input_paths = [*args.paths, *args.files]

    if args.snippet is not None:
        context_files = _collect_files(args.mission, args.ignore) if args.mission else []
        context_index = build_symbol_index(context_files)
        context_tags: set[str] = set()
        context_signatures: dict[str, list[str]] = {}
        context_returns: dict[str, str] = {}
        if args.config:
            context_config = load_checked(args.config)
        elif args.mission and (context_path := find_config(args.mission)):
            context_config = load_checked(context_path)
        else:
            context_config = {}
        context_tags = extract_function_tags(context_config)
        context_signatures = extract_function_type_signatures(context_config)
        context_returns = extract_function_return_types(context_config)
        context_ignored_rules = extract_ignored_rules(context_config) | {rule.upper() for rule in args.ignore_rule}
        context_external_locals = extract_external_locals(context_config) | {
            name.strip().lower() for name in args.external_local if name.strip()
        }
        context_severities = extract_rule_severities(context_config)
        context_presets = [*extract_presets(context_config), *(name.lower() for name in args.preset)]
        context_plugin_rules, context_plugin_errors = load_plugins(extract_plugins(context_config), os.path.dirname(args.config or context_path) if (args.config or context_path) else os.getcwd())
        if "strict" in context_presets:
            context_severities.update({code: "error" for code, (severity, _message) in RULES.items() if severity == "warning"})
        context_selected: set[str] = set()
        for item in args.rules:
            key = item.strip().lower()
            if key.upper() in RULES:
                context_selected.add(key.upper())
            elif key in RULE_CATEGORIES:
                context_selected.update(RULE_CATEGORIES[key])
        if context_selected:
            context_ignored_rules |= set(RULES) - context_selected
        for tag in context_tags:
            context_index.add_tag(tag)
        all_diags = lint_text(
            args.snippet, filename="<snippet>", index=context_index,
            function_signatures=context_signatures, function_return_types=context_returns,
            ignored_rules=context_ignored_rules, rule_severities=context_severities, style=(args.style or "style" in context_presets or bool(context_selected & {"W301", "W302"})), check_suppressions=args.check_suppressions, plugin_rules=context_plugin_rules, external_locals=context_external_locals,
        )
        all_diags.extend(Diagnostic(Severity.ERROR, "E012", f"plugin load failed: {error}", 1, 1, "") for error in context_plugin_errors)
        for config_path, issues in config_issues.items():
            all_diags.extend(Diagnostic(Severity.ERROR, "E012", message, 1, 1, config_path) for message in issues)
        if baseline_keys:
            all_diags = [
                d for d in all_diags
                if _diagnostic_fingerprint(d.code, d.file, d.line, d.column, d.message) not in baseline_keys
            ]
        if args.max_issues is not None:
            all_diags = all_diags[:args.max_issues]
        linted_files = ["<snippet>"]
        if args.checkstyle:
            print(_checkstyle_output(all_diags))
        elif args.json:
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
        threshold = {"error": 3, "warning": 2, "info": 1, "none": 99}[args.fail_on]
        severity_rank = {Severity.INFO: 1, Severity.WARNING: 2, Severity.ERROR: 3}
        return 1 if any(severity_rank[d.severity] >= threshold for d in all_diags) else 0

    collection_ignores = list(args.ignore)
    for path in input_paths:
        cfg_path = args.config or find_config(path)
        if cfg_path:
            collection_ignores.extend(extract_ignore_patterns(load_checked(cfg_path)))
    files: list[str] = []
    for path in input_paths:
        files.extend(_collect_files(path, collection_ignores))

    # De-duplicate while preserving determinism, then sort.
    files = sorted(set(files))
    file_configs = discover_configs(files)
    filtered_files: list[str] = []
    for file in files:
        config_path = file_configs.get(os.path.normcase(os.path.abspath(file)))
        patterns = extract_ignore_patterns(load_checked(config_path)) if config_path else []
        relative = os.path.relpath(file, os.path.dirname(config_path)) if config_path else os.path.basename(file)
        if not _is_ignored(relative, patterns):
            filtered_files.append(file)
    files = filtered_files
    # Filtering cannot change a file's nearest config, so retain the first
    # discovery result instead of walking upward through every file again.
    file_configs = {
        os.path.normcase(os.path.abspath(file)): file_configs[key]
        for file in files
        if (key := os.path.normcase(os.path.abspath(file))) in file_configs
    }
    for config_path in sorted(set(file_configs.values())):
        load_checked(config_path)
    timings["collection_ms"] = round((time.perf_counter() - started_at) * 1000, 2)

    if args.fix_preview:
        preview: list[dict[str, object]] = []
        for file in files:
            if not _is_sqf_file(file):
                continue
            try:
                with open(file, "r", encoding="utf-8", errors="replace") as fh:
                    edits = safe_fix_edits(fh.read())
            except OSError:
                continue
            if edits:
                preview.append({"file": file, "edits": edits})
        print(json.dumps(preview, indent=2))
        return 0
    source_cache: dict[str, str] = {}

    # Resolve mod function tags from project config, then register them on the
    # symbol index so mod-provided functions are not reported as unknown.
    config_tags: set[str] = set()
    function_signatures: dict[str, list[str]] = {}
    function_return_types: dict[str, str] = {}
    ignored_rules: set[str] = {rule.upper() for rule in args.ignore_rule}
    external_locals: set[str] = {
        name.strip().lower() for name in args.external_local if name.strip()
    }
    rule_severities: dict[str, str] = {}
    declared_dependencies: set[str] = set()
    context_paths = [*input_paths, args.mission] if args.mission else input_paths
    if args.config:
        loaded_config = load_checked(args.config)
        config_tags = extract_function_tags(loaded_config)
        declared_dependencies |= extract_dependencies(loaded_config)
        function_signatures = extract_function_type_signatures(loaded_config)
        function_return_types = extract_function_return_types(loaded_config)
        ignored_rules |= extract_ignored_rules(loaded_config)
        external_locals |= extract_external_locals(loaded_config)
        rule_severities.update(extract_rule_severities(loaded_config))
    else:
        for path in context_paths:
            cfg_path = find_config(path)
            if cfg_path:
                loaded_config = load_checked(cfg_path)
                config_tags |= extract_function_tags(loaded_config)
                declared_dependencies |= extract_dependencies(loaded_config)
                for name, types in extract_function_type_signatures(loaded_config).items():
                    function_signatures.setdefault(name, types)
                for name, return_type in extract_function_return_types(loaded_config).items():
                    function_return_types.setdefault(name, return_type)
                ignored_rules |= extract_ignored_rules(loaded_config)
                external_locals |= extract_external_locals(loaded_config)
                rule_severities.update(extract_rule_severities(loaded_config))
    for config_path in sorted(set(file_configs.values())):
        loaded_config = load_checked(config_path)
        config_tags |= extract_function_tags(loaded_config)
        declared_dependencies |= extract_dependencies(loaded_config)
        external_locals |= extract_external_locals(loaded_config)
        for name, types in extract_function_type_signatures(loaded_config).items():
            function_signatures.setdefault(name, types)
        for name, return_type in extract_function_return_types(loaded_config).items():
            function_return_types.setdefault(name, return_type)
        rules, errors = load_plugins(extract_plugins(loaded_config), os.path.dirname(config_path))
        plugin_rules.extend(rules)
        plugin_errors.extend(errors)

    project_presets = [*args.preset]
    for config in checked_configs.values():
        project_presets.extend(extract_presets(config))
    if "strict" in {name.lower() for name in project_presets}:
        rule_severities.update({code: "error" for code, (severity, _message) in RULES.items() if severity == "warning"})
    selected_rules: set[str] = set()
    for item in args.rules:
        key = item.strip().lower()
        if key.upper() in RULES:
            selected_rules.add(key.upper())
        elif key in RULE_CATEGORIES:
            selected_rules.update(RULE_CATEGORIES[key])
        else:
            _build_arg_parser().error(f"unknown rule or category: {item}")
    if selected_rules:
        ignored_rules |= set(RULES) - selected_rules
    style_requested = args.style or args.fix or "style" in {name.lower() for name in project_presets} or bool(selected_rules & {"W301", "W302"})

    # Build a mission-wide symbol index so mission-defined functions are not
    # reported as unknown (W201) before linting each file.
    index_files = list(files)
    if args.mission:
        index_files.extend(_collect_files(args.mission, collection_ignores))
    token_cache = {}
    index = build_symbol_index(
        sorted(set(index_files)), token_cache=token_cache,
        source_cache=source_cache,
    )
    index.cba_declared |= any(dep.startswith("cba_") for dep in declared_dependencies)
    timings["index_ms"] = round((time.perf_counter() - started_at) * 1000 - float(timings["collection_ms"]), 2)
    timings["index_files"] = len(index_files)
    timings["token_cache_entries"] = len(token_cache)
    # A dynamically compiled template executes in the caller's scope.  Infer
    # explicitly declared locals from exact ``call compile
    # preprocessFileLineNumbers`` sites so template files do not require a
    # manual externalLocals entry in common static-loader patterns.
    external_locals |= discover_external_locals(source_cache)
    included_files = _collect_included_files(files, source_cache)
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
        nearest_config = file_configs.get(os.path.normcase(os.path.abspath(f)))
        file_config = load_checked(nearest_config) if nearest_config else {}
        file_ignored_rules = ignored_rules | extract_ignored_rules(file_config)
        file_external_locals = external_locals | extract_external_locals(file_config)
        file_severities = dict(rule_severities)
        file_severities.update(extract_rule_severities(file_config))
        file_presets = {name.lower() for name in extract_presets(file_config)}
        file_style = style_requested or "style" in file_presets
        if _is_sqf_file(f):
            pretokenized = token_cache.get(f)
            if args.fix:
                try:
                    with open(f, "r", encoding="utf-8", errors="replace") as fh:
                        original = fh.read()
                    edits = safe_fix_edits(original)
                    fixed = apply_safe_fix_edits(original, edits)
                    if fixed != original:
                        with open(f, "w", encoding="utf-8", newline="") as fh:
                            fh.write(fixed)
                        pretokenized = None
                        source_cache.pop(f, None)
                except OSError:
                    pass
            linted_files.append(f)
            all_diags.extend(lint_file(f, index=index, function_signatures=function_signatures, function_return_types=function_return_types, ignored_rules=file_ignored_rules, rule_severities=file_severities, style=file_style, check_suppressions=args.check_suppressions, plugin_rules=plugin_rules, pretokenized=pretokenized, source_text=source_cache.get(f), source_cache=source_cache, external_locals=file_external_locals, check_unused_locals_enabled=os.path.normcase(os.path.abspath(f)) not in included_files))
        elif _is_config_file(f):
            try:
                with open(f, "r", encoding="utf-8", errors="replace") as fh:
                    source = fh.read()
            except OSError:
                continue
            linted_files.append(f)
            all_diags.extend(lint_config(source, filename=f, index=index, function_signatures=function_signatures, function_return_types=function_return_types, ignored_rules=file_ignored_rules, rule_severities=file_severities, style=file_style))
        elif _is_mission_file(f):
            try:
                with open(f, "r", encoding="utf-8", errors="replace") as fh:
                    source = fh.read()
            except OSError:
                continue
            linted_files.append(f)
            all_diags.extend(check_mission_sqm(source, f))
        if args.max_issues is not None and len(all_diags) >= args.max_issues:
            all_diags = all_diags[:args.max_issues]
            break

    timings["lint_ms"] = round((time.perf_counter() - started_at) * 1000 - float(timings["collection_ms"]) - float(timings["index_ms"]), 2)
    timings["files"] = len(linted_files)
    timings["diagnostics"] = len(all_diags)

    for config_path, issues in config_issues.items():
        all_diags.extend(
            Diagnostic(Severity.ERROR, "E012", message, 1, 1, config_path)
            for message in issues
        )
    all_diags.extend(Diagnostic(Severity.ERROR, "E012", f"plugin load failed: {error}", 1, 1, "") for error in plugin_errors)

    if baseline_keys:
        all_diags = [d for d in all_diags if _diagnostic_fingerprint(d.code, d.file, d.line, d.column, d.message) not in baseline_keys]

    if args.max_issues is not None:
        all_diags = all_diags[:args.max_issues]

    if args.diff or args.diff_staged:
        changed_lines = _git_changed_lines(args.diff or "HEAD", input_paths, staged=args.diff_staged)
        all_diags = [
            d for d in all_diags
            if os.path.normcase(os.path.abspath(d.file)) in changed_lines
            and d.line in changed_lines[os.path.normcase(os.path.abspath(d.file))]
        ]

    if args.checkstyle:
        print(_checkstyle_output(all_diags))
    elif args.sarif:
        payload = {
            "version": "2.1.0",
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "runs": [{
                "automationDetails": {"id": "armalint/default"},
                "tool": {"driver": {"name": "armalint", "version": __version__, "informationUri": "docs/", "rules": rule_metadata(plugin_rules)}},
                "results": [{
                    "ruleId": d.code,
                    "level": {"error": "error", "warning": "warning", "info": "note"}.get(d.severity.value, "warning"),
                    "message": {"text": d.message},
                    "partialFingerprints": {"armalint/v1": _diagnostic_fingerprint(d.code, d.file, d.line, d.column, d.message)},
                    "locations": [{"physicalLocation": {"artifactLocation": {"uri": d.file}, "region": {"startLine": d.line, "startColumn": d.column}}}],
                    **({"relatedLocations": _sarif_related_locations(d)} if _sarif_related_locations(d) else {}),
                } for d in all_diags],
            }],
        }
        print(json.dumps(payload))
    elif args.json:
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
        if args.github_actions:
            for d in all_diags:
                print(_github_annotation(d))
        else:
            for d in all_diags:
                print(format_diagnostic(d))
        print(f"{len(linted_files)} file(s) linted, {len(all_diags)} diagnostic(s)")

    threshold = {"error": 3, "warning": 2, "info": 1, "none": 99}[args.fail_on]
    severity_rank = {Severity.INFO: 1, Severity.WARNING: 2, Severity.ERROR: 3}
    if args.timings:
        timings["total_ms"] = round((time.perf_counter() - started_at) * 1000, 2)
        timings["token_cache_hit_rate"] = round((len(token_cache) / len(index_files)) if index_files else 1.0, 3)
        print(json.dumps(timings, sort_keys=True), file=sys.stderr)
    return 1 if any(severity_rank[d.severity] >= threshold for d in all_diags) else 0


def _diagnostic_fingerprint(code: object, file: object, line: object, column: object, message: object) -> str:
    """Stable identity shared by SARIF output and JSON baselines."""
    raw = "|".join(str(value or "") for value in (code, file, line, column, message))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _sarif_related_locations(diagnostic) -> list[dict[str, object]]:
    """Convert diagnostic provenance locations to SARIF related locations."""
    related: list[dict[str, object]] = []
    for index, location in enumerate(getattr(diagnostic, "related_locations", []), 1):
        if not isinstance(location, dict) or not location.get("file"):
            continue
        related.append({
            "id": index,
            "message": {"text": str(location.get("message") or "related source location")},
            "physicalLocation": {
                "artifactLocation": {"uri": str(location["file"])},
                "region": {
                    "startLine": int(location.get("line") or 1),
                    "startColumn": int(location.get("column") or 1),
                },
            },
        })
    return related


if __name__ == "__main__":
    sys.exit(_main())
