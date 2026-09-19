"""Preprocessor for Arma 3 SQF: resolves ``#include`` directives.

Returns the inlined source together with a line map so downstream diagnostics
can report the original (file, line) for each output line. Only ``#include`` is
expanded; ``#define``/``#ifdef``/``#ifndef``/``#else``/``#endif`` and friends are
left untouched (the tokenizer emits them as ``preprocessor`` tokens which the
analyzers ignore).
"""

from __future__ import annotations

import os
import re

# ``#include "..."`` or ``#include <...>``, with optional surrounding whitespace.
_INCLUDE_RE = re.compile(r'^\s*#\s*include\s+(?:"([^"]*)"|<([^>]*)>)\s*$')
_DEFINE_RE = re.compile(r'^\s*#\s*define\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s+(.*?))?\s*$')
_FUNCTION_DEFINE_RE = re.compile(r'^\s*#\s*define\s+([A-Za-z_][A-Za-z0-9_]*)\(([^)]*)\)\s*(.*?)\s*$')
_UNDEF_RE = re.compile(r'^\s*#\s*undef\s+([A-Za-z_][A-Za-z0-9_]*)')
_IFDEF_RE = re.compile(r'^\s*#\s*(ifdef|ifndef)\s+([A-Za-z_][A-Za-z0-9_]*)')
_IF_DEFINED_RE = re.compile(r'^\s*#\s*if\s+(!\s*)?defined\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)\s*$')
_IF_LITERAL_RE = re.compile(r'^\s*#\s*if\s+(0|1|true|false)\s*$')
_ELIF_RE = re.compile(r'^\s*#\s*elif\s+(0|1|true|false)\s*$')
_ELIF_DEFINED_RE = re.compile(r'^\s*#\s*elif\s+(!\s*)?defined\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)\s*$')
_ELSE_RE = re.compile(r'^\s*#\s*else\s*$')
_ENDIF_RE = re.compile(r'^\s*#\s*endif\s*$')


def _strip_macro_comment(text: str) -> str:
    """Remove an inline C/C++ comment from a macro body, preserving strings."""
    quote = False
    escaped = False
    for index, char in enumerate(text):
        if char == '"' and not escaped:
            quote = not quote
        if char == "/" and not quote and index + 1 < len(text) and text[index + 1] == "/":
            return text[:index].rstrip()
        escaped = char == "\\" and not escaped
    return text.rstrip()


def find_include_cycles(path: str) -> list[tuple[str, int, str]]:
    """Return proven include-cycle edges as ``(file, line, target)`` tuples."""
    cycles: list[tuple[str, int, str]] = []
    seen_edges: set[tuple[str, int, str]] = set()

    def visit(current: str, stack: tuple[str, ...]) -> None:
        normalized = _normalized(current)
        if normalized in stack:
            return
        try:
            with open(current, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            return
        next_stack = stack + (normalized,)
        base_dir = os.path.dirname(os.path.abspath(current))
        for line_number, line in enumerate(lines, start=1):
            match = _INCLUDE_RE.match(line)
            if not match:
                continue
            target = os.path.normpath(os.path.join(base_dir, match.group(1) or match.group(2)))
            if not os.path.isfile(target):
                continue
            target_normalized = _normalized(target)
            edge = (current, line_number, target)
            if target_normalized in next_stack:
                if edge not in seen_edges:
                    seen_edges.add(edge)
                    cycles.append(edge)
                continue
            visit(target, next_stack)

    visit(path, ())
    return cycles


def find_include_guard_issues(path: str) -> list[tuple[str, int, str]]:
    """Return repeated includes whose target has no recognizable guard."""
    issues: list[tuple[str, int, str]] = []
    seen: set[str] = set()

    def guarded(target: str) -> bool:
        try:
            with open(target, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            return False
        if re.search(r"^\s*#\s*pragma\s+once\b", text, re.IGNORECASE | re.MULTILINE):
            return True
        match = re.search(r"^\s*#\s*ifndef\s+([A-Za-z_][A-Za-z0-9_]*)\b", text, re.IGNORECASE | re.MULTILINE)
        return bool(match and re.search(r"^\s*#\s*define\s+" + re.escape(match.group(1)) + r"\b", text, re.IGNORECASE | re.MULTILINE))

    def visit(current: str, stack: tuple[str, ...]) -> None:
        normalized = _normalized(current)
        if normalized in stack:
            return
        try:
            with open(current, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            return
        base_dir = os.path.dirname(os.path.abspath(current))
        for line_number, line in enumerate(lines, 1):
            match = _INCLUDE_RE.match(line)
            if not match:
                continue
            target = os.path.normpath(os.path.join(base_dir, match.group(1) or match.group(2)))
            if not os.path.isfile(target):
                continue
            target_key = _normalized(target)
            if target_key in seen and not guarded(target):
                issues.append((current, line_number, target))
            seen.add(target_key)
            visit(target, stack + (normalized,))

    visit(path, ())
    return issues


def _normalized(path: str) -> str:
    """Absolute, case-normalized (Windows) path used for cycle detection."""
    return os.path.normcase(os.path.abspath(path))


def _macro_arguments(text: str, start: int) -> tuple[list[str], int] | None:
    """Parse a function-like macro call beginning at ``start`` (the `(`)."""
    depth = 0
    quote = ""
    argument_start = start + 1
    arguments: list[str] = []
    index = start
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    index += 2
                    continue
                quote = ""
            index += 1
            continue
        if char in ('"', "'"):
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                value = text[argument_start:index].strip()
                if value or arguments:
                    arguments.append(value)
                return arguments, index + 1
        elif char == "," and depth == 1:
            arguments.append(text[argument_start:index].strip())
            argument_start = index + 1
        index += 1
    return None


def _expand_macros(
    line: str, defines: dict[str, str], function_defines: dict[str, tuple[list[str], str]] | None = None,
    depth: int = 0,
) -> str:
    """Expand object/function-like macros outside strings and comments."""
    if (not defines and not function_defines) or depth >= 32:
        return line
    function_defines = function_defines or {}
    output: list[str] = []
    index = 0
    quote = ""
    while index < len(line):
        char = line[index]
        if quote:
            output.append(char)
            if char == quote:
                if index + 1 < len(line) and line[index + 1] == quote:
                    output.append(line[index + 1])
                    index += 2
                    continue
                quote = ""
            index += 1
            continue
        if char in ('"', "'"):
            quote = char
            output.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < len(line) and line[index + 1] == "/":
            output.append(line[index:])
            break
        if char.isalpha() or char == "_":
            end = index + 1
            while end < len(line) and (line[end].isalnum() or line[end] == "_"):
                end += 1
            word = line[index:end]
            key = word.lower()
            macro = function_defines.get(key)
            call_start = end
            while call_start < len(line) and line[call_start] in " \t":
                call_start += 1
            if macro is not None and call_start < len(line) and line[call_start] == "(":
                parsed = _macro_arguments(line, call_start)
                if parsed is not None:
                    arguments, call_end = parsed
                    names, body = macro
                    if len(arguments) == len(names):
                        replacement = body
                        for name, value in zip(names, arguments):
                            # Use a callable replacement so backslashes in
                            # paths (common in Arma macro arguments) remain
                            # literal instead of being parsed as regex escapes.
                            replacement = re.sub(
                                r"\b" + re.escape(name) + r"\b",
                                lambda _match, value=value: value,
                                replacement,
                            )
                        replacement = re.sub(r"\s*##\s*", "", replacement)
                        output.append(_expand_macros(replacement, defines, function_defines, depth + 1))
                        index = call_end
                        continue
            output.append(defines.get(key, word))
            index = end
            continue
        output.append(char)
        index += 1
    return "".join(output)


def _preprocess_lines(
    source: str,
    filename: str,
    base_dir: str,
    _include_stack: tuple[str, ...],
    _defines: dict[str, str],
    _conditions: list[bool],
    _source_cache: dict[str, str] | None = None,
    _function_defines: dict[str, tuple[list[str], str]] | None = None,
) -> tuple[list[str], list[tuple[str, int]]]:
    """Split out the line-by-line work; returns ``(lines, line_map)``."""
    lines: list[str] = []
    line_map: list[tuple[str, int]] = []

    if source == "":
        return lines, line_map

    macro_continuation = False
    continuation_name: str | None = None
    continuation_params: list[str] | None = None
    continuation_body: list[str] = []
    for orig_line, line in enumerate(source.split("\n"), start=1):
        if macro_continuation:
            # The continuation belongs to a ``#define`` body, not to the SQF
            # program. Keep its physical line in the map while removing the
            # macro text from downstream syntax and semantic analysis.
            fragment = _strip_macro_comment(line.rstrip())
            macro_continuation = fragment.endswith("\\")
            continuation_body.append(fragment[:-1].rstrip() if macro_continuation else fragment)
            if not macro_continuation and continuation_name:
                if continuation_params is None:
                    _defines[continuation_name] = " ".join(continuation_body).strip()
                elif _function_defines is not None:
                    _function_defines[continuation_name] = (continuation_params, " ".join(continuation_body).strip())
                continuation_name = None
                continuation_params = None
                continuation_body = []
            lines.append("")
            line_map.append((filename, orig_line))
            continue
        if _ENDIF_RE.match(line):
            if _conditions:
                _conditions.pop()
            lines.append("")
            line_map.append((filename, orig_line))
            continue
        if _ELSE_RE.match(line):
            if _conditions:
                _conditions[-1] = not _conditions[-1]
            lines.append("")
            line_map.append((filename, orig_line))
            continue
        match = _ELIF_RE.match(line)
        if match:
            if _conditions:
                enabled = match.group(1).lower() in ("1", "true")
                _conditions[-1] = enabled and all(_conditions[:-1])
            lines.append("")
            line_map.append((filename, orig_line))
            continue
        match = _ELIF_DEFINED_RE.match(line)
        if match:
            if _conditions:
                enabled = match.group(2).lower() in _defines
                if match.group(1):
                    enabled = not enabled
                _conditions[-1] = enabled and all(_conditions[:-1])
            lines.append("")
            line_map.append((filename, orig_line))
            continue
        match = _IFDEF_RE.match(line)
        if match:
            name = match.group(2).lower()
            enabled = name in _defines
            if match.group(1).lower() == "ifndef":
                enabled = not enabled
            _conditions.append(enabled and all(_conditions))
            lines.append("")
            line_map.append((filename, orig_line))
            continue
        match = _IF_LITERAL_RE.match(line)
        if match:
            _conditions.append(match.group(1).lower() in ("1", "true") and all(_conditions))
            lines.append("")
            line_map.append((filename, orig_line))
            continue
        match = _IF_DEFINED_RE.match(line)
        if match:
            enabled = match.group(2).lower() in _defines
            if match.group(1):
                enabled = not enabled
            _conditions.append(enabled and all(_conditions))
            lines.append("")
            line_map.append((filename, orig_line))
            continue
        # Function-like definitions must be recognized before object-like
        # definitions.  The latter also matches ``#define NAME(args) body``
        # and would otherwise register only NAME as an object macro, leaving
        # calls such as ``FactionGet(...)`` or ``QUOTE(...)`` unresolved.
        function_match = _FUNCTION_DEFINE_RE.match(line)
        if function_match and all(_conditions):
            name = function_match.group(1).lower()
            params = [item.strip().lower() for item in function_match.group(2).split(",") if item.strip()]
            body = _strip_macro_comment(function_match.group(3))
            if _function_defines is not None:
                _function_defines[name] = (params, body.rstrip("\\").rstrip())
            macro_continuation = line.rstrip().endswith("\\")
            if macro_continuation:
                continuation_name = name
                continuation_params = params
                continuation_body = [body.rstrip()[:-1].rstrip()]
            lines.append("")
            line_map.append((filename, orig_line))
            continue
        match = _DEFINE_RE.match(line)
        if match and all(_conditions):
            body = _strip_macro_comment(match.group(2) or "1")
            _defines[match.group(1).lower()] = body or "1"
            macro_continuation = line.rstrip().endswith("\\")
            if macro_continuation:
                continuation_name = match.group(1).lower()
                continuation_params = None
                continuation_body = [body.rstrip()[:-1].rstrip()]
            lines.append("")
            line_map.append((filename, orig_line))
            continue
        match = _UNDEF_RE.match(line)
        if match and all(_conditions):
            _defines.pop(match.group(1).lower(), None)
            lines.append("")
            line_map.append((filename, orig_line))
            continue
        if not all(_conditions):
            lines.append("")
            line_map.append((filename, orig_line))
            continue
        match = _INCLUDE_RE.match(line)
        if match:
            include_path = match.group(1) if match.group(1) is not None else match.group(2)
            resolved = os.path.normpath(os.path.join(base_dir, include_path))
            normalized_resolved = _normalized(resolved)
            if os.path.isfile(resolved) and normalized_resolved not in _include_stack:
                sub_source = None
                if _source_cache is not None:
                    sub_source = _source_cache.get(resolved) or _source_cache.get(normalized_resolved)
                if sub_source is None:
                    with open(resolved, "r", encoding="utf-8", errors="replace") as fh:
                        sub_source = fh.read()
                sub_lines, sub_map = _preprocess_lines(
                    sub_source,
                    filename=resolved,
                    base_dir=os.path.dirname(resolved),
                    _include_stack=_include_stack + (normalized_resolved,),
                    _defines=_defines,
                    _conditions=_conditions,
                    _source_cache=_source_cache,
                    _function_defines=_function_defines,
                )
                lines.extend(sub_lines)
                line_map.extend(sub_map)
                continue
        # Not an include (or missing/cyclic): keep the line as-is.
        lines.append(_expand_macros(line, _defines, _function_defines))
        line_map.append((filename, orig_line))

    return lines, line_map


def preprocess(
    source: str,
    filename: str,
    base_dir: str,
    _include_stack: tuple = (),
    source_cache: dict[str, str] | None = None,
) -> tuple[str, list]:
    """Resolve ``#include`` directives in ``source``.

    Returns ``(combined_source, line_map)`` where ``line_map[i]`` is the
    ``(file, orig_line)`` (1-based) of combined line ``i + 1``.
    """
    # Most SQF files contain no preprocessor directives. Avoid the regex,
    # macro, and include machinery in that common case while preserving the
    # exact line mapping produced by the general path (including a trailing
    # empty line from ``str.split("\\n")``).
    if "#" not in source:
        lines = source.split("\n")
        return source, [(filename, line) for line in range(1, len(lines) + 1)]
    lines, line_map = _preprocess_lines(source, filename, base_dir, _include_stack, {}, [], source_cache, {})
    return "\n".join(lines), line_map


def preprocess_file(path: str) -> tuple[str, list]:
    """Read ``path`` and preprocess it, resolving includes relative to it."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        source = fh.read()
    return preprocess(source, path, os.path.dirname(os.path.abspath(path)))


def find_include_origins(path: str) -> dict[str, list[tuple[str, int]]]:
    """Return direct include sites reachable from *path*.

    Keys are normalized included-file paths. Values contain ``(including_file,
    line)`` pairs, which let consumers explain why a diagnostic in an included
    fragment is related to the parent source file.
    """
    origins: dict[str, list[tuple[str, int]]] = {}
    visited: set[str] = set()

    def visit(current: str) -> None:
        normalized = _normalized(current)
        if normalized in visited:
            return
        visited.add(normalized)
        try:
            with open(current, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
        except OSError:
            return
        for line_no, line in enumerate(lines, 1):
            match = _INCLUDE_RE.match(line)
            if not match:
                continue
            include_path = match.group(1) if match.group(1) is not None else match.group(2)
            target = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(current)), include_path))
            if not os.path.isfile(target):
                continue
            target_key = _normalized(target)
            origins.setdefault(target_key, []).append((current, line_no))
            visit(target)

    visit(path)
    return origins


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        main_path = os.path.join(tmpdir, "main.sqf")
        shared_path = os.path.join(tmpdir, "shared.sqf")

        with open(main_path, "w", encoding="utf-8") as fh:
            fh.write('#include "shared.sqf"\nhint str _definedInShared;\n')
        with open(shared_path, "w", encoding="utf-8") as fh:
            fh.write("private _definedInShared = 42;\n")

        combined, line_map = preprocess_file(main_path)
        assert "private _definedInShared" in combined
        assert line_map[0] == (shared_path, 1), line_map[0]
        assert line_map[2] == (main_path, 2), line_map[2]
        assert len(line_map) == combined.count("\n") + 1, (len(line_map), combined)

        with open(main_path, "w", encoding="utf-8") as fh:
            fh.write('#include "shared.sqf"\n#include "shared.sqf"\n')
        assert find_include_guard_issues(main_path), "unguarded repeated include should be reported"
        with open(shared_path, "w", encoding="utf-8") as fh:
            fh.write("#pragma once\nprivate _x = 1;\n")
        assert find_include_guard_issues(main_path) == []
        with open(shared_path, "w", encoding="utf-8") as fh:
            fh.write("private _definedInShared = 42;\n")

        # Missing include: directive is left in place, mapped to the main file.
        missing_main = os.path.join(tmpdir, "missing.sqf")
        with open(missing_main, "w", encoding="utf-8") as fh:
            fh.write('#include "nope.sqf"\nhint str 1;\n')
        combined2, line_map2 = preprocess_file(missing_main)
        assert '#include "nope.sqf"' in combined2
        assert line_map2[0] == (missing_main, 1), line_map2[0]

        # Self-include: must terminate (cycle guarded), not loop forever.
        self_path = os.path.join(tmpdir, "self.sqf")
        with open(self_path, "w", encoding="utf-8") as fh:
            fh.write('#include "self.sqf"\nhint str 1;\n')
        combined3, line_map3 = preprocess_file(self_path)
        assert isinstance(combined3, str)
        assert 'hint str 1;' in combined3

        # Angle-bracket form resolves relative to base_dir the same way.
        with open(main_path, "w", encoding="utf-8") as fh:
            fh.write("#include <shared.sqf>\nhint str _definedInShared;\n")
        combined4, _line_map4 = preprocess_file(main_path)
        assert "private _definedInShared" in combined4

        conditional = "#define ENABLED\n#ifdef ENABLED\nhint \"yes\";\n#else\nhint \"no\";\n#endif\n#ifndef MISSING\nhint \"still\";\n#endif\n"
        combined5, map5 = preprocess(conditional, main_path, tmpdir)
        assert 'hint "yes";' in combined5 and 'hint "still";' in combined5
        assert 'hint "no";' not in combined5
        assert len(map5) == combined5.count("\n") + 1

        macro_source = '#define LIMIT 42\nprivate _value = LIMIT;\nhint "LIMIT"; // LIMIT\n'
        macro_expanded, _ = preprocess(macro_source, main_path, tmpdir)
        assert "private _value = 42;" in macro_expanded
        assert 'hint "LIMIT";' in macro_expanded
        assert "// LIMIT" in macro_expanded

        function_macro = '#define QUOTE(value) "value"\n#define DOUBLES(a,b) a##b\nhint QUOTE(hello);\nprivate _path = DOUBLES(foo,bar);\n'
        function_expanded, _ = preprocess(function_macro, main_path, tmpdir)
        assert 'hint "hello";' in function_expanded
        assert "private _path = foobar;" in function_expanded

        windows_path_macro = '#define PATH(value) value\nprivate _path = PATH("A:\\Mission\\scripts\\fn.sqf");\n'
        windows_path_expanded, _ = preprocess(windows_path_macro, main_path, tmpdir)
        assert 'private _path = "A:\\Mission\\scripts\\fn.sqf";' in windows_path_expanded

        multiline_macro = '#define WRAP(value) { \\\n+    hint value; \\\n+}\nWRAP("ok");\n'
        multiline_expanded, _ = preprocess(multiline_macro, main_path, tmpdir)
        assert 'hint "ok";' in multiline_expanded

        inline_macro_comment = '#define STEP QUOTE(STEP) // explanatory comment\nprivate _x = [1] call (obj get STEP);\n'
        inline_expanded, _ = preprocess(inline_macro_comment, main_path, tmpdir)
        assert 'private _x = [1] call (obj get QUOTE(STEP));' in inline_expanded

        literals, _ = preprocess('#if 0\nhint "no";\n#elif 1\nhint "yes";\n#endif\n', main_path, tmpdir)
        assert 'hint "yes";' in literals and 'hint "no";' not in literals

        defined_elif, _ = preprocess('#define READY\n#if 0\nhint "no";\n#elif defined(READY)\nhint "yes";\n#endif\n', main_path, tmpdir)
        assert 'hint "yes";' in defined_elif and 'hint "no";' not in defined_elif

        cycle_a = os.path.join(tmpdir, "cycle_a.sqf")
        cycle_b = os.path.join(tmpdir, "cycle_b.sqf")
        with open(cycle_a, "w", encoding="utf-8") as fh:
            fh.write('#include "cycle_b.sqf"\n')
        with open(cycle_b, "w", encoding="utf-8") as fh:
            fh.write('#include "cycle_a.sqf"\n')
        assert find_include_cycles(cycle_a) == [(cycle_b, 1, cycle_a)]

    print("preprocessor self-test passed")
