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
_DEFINE_RE = re.compile(r'^\s*#\s*define\s+([A-Za-z_][A-Za-z0-9_]*)')
_UNDEF_RE = re.compile(r'^\s*#\s*undef\s+([A-Za-z_][A-Za-z0-9_]*)')
_IFDEF_RE = re.compile(r'^\s*#\s*(ifdef|ifndef)\s+([A-Za-z_][A-Za-z0-9_]*)')
_IF_DEFINED_RE = re.compile(r'^\s*#\s*if\s+(!\s*)?defined\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)\s*$')
_ELSE_RE = re.compile(r'^\s*#\s*else\s*$')
_ENDIF_RE = re.compile(r'^\s*#\s*endif\s*$')


def _normalized(path: str) -> str:
    """Absolute, case-normalized (Windows) path used for cycle detection."""
    return os.path.normcase(os.path.abspath(path))


def _preprocess_lines(
    source: str,
    filename: str,
    base_dir: str,
    _include_stack: tuple[str, ...],
    _defines: set[str],
    _conditions: list[bool],
) -> tuple[list[str], list[tuple[str, int]]]:
    """Split out the line-by-line work; returns ``(lines, line_map)``."""
    lines: list[str] = []
    line_map: list[tuple[str, int]] = []

    if source == "":
        return lines, line_map

    for orig_line, line in enumerate(source.split("\n"), start=1):
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
        match = _IF_DEFINED_RE.match(line)
        if match:
            enabled = match.group(2).lower() in _defines
            if match.group(1):
                enabled = not enabled
            _conditions.append(enabled and all(_conditions))
            lines.append("")
            line_map.append((filename, orig_line))
            continue
        match = _DEFINE_RE.match(line)
        if match and all(_conditions):
            _defines.add(match.group(1).lower())
            lines.append("")
            line_map.append((filename, orig_line))
            continue
        match = _UNDEF_RE.match(line)
        if match and all(_conditions):
            _defines.discard(match.group(1).lower())
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
                with open(resolved, "r", encoding="utf-8", errors="replace") as fh:
                    sub_source = fh.read()
                sub_lines, sub_map = _preprocess_lines(
                    sub_source,
                    filename=resolved,
                    base_dir=os.path.dirname(resolved),
                    _include_stack=_include_stack + (normalized_resolved,),
                    _defines=_defines,
                    _conditions=_conditions,
                )
                lines.extend(sub_lines)
                line_map.extend(sub_map)
                continue
        # Not an include (or missing/cyclic): keep the line as-is.
        lines.append(line)
        line_map.append((filename, orig_line))

    return lines, line_map


def preprocess(
    source: str,
    filename: str,
    base_dir: str,
    _include_stack: tuple = (),
) -> tuple[str, list]:
    """Resolve ``#include`` directives in ``source``.

    Returns ``(combined_source, line_map)`` where ``line_map[i]`` is the
    ``(file, orig_line)`` (1-based) of combined line ``i + 1``.
    """
    lines, line_map = _preprocess_lines(source, filename, base_dir, _include_stack, set(), [])
    return "\n".join(lines), line_map


def preprocess_file(path: str) -> tuple[str, list]:
    """Read ``path`` and preprocess it, resolving includes relative to it."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        source = fh.read()
    return preprocess(source, path, os.path.dirname(os.path.abspath(path)))


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

    print("preprocessor self-test passed")
