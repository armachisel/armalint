"""Incremental file watching for editor and CI workflows.

The watcher is dependency-free and polls file metadata. It rebuilds the symbol
index only when the file set changes, while re-linting only files whose size or
mtime changed. Each update is emitted as one JSON object, making it easy for an
editor adapter or a shell pipeline to consume.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from .linter import build_symbol_index, lint_file


def _files(paths: list[str]) -> list[str]:
    result: list[str] = []
    for raw in paths:
        path = Path(raw)
        if path.is_file() and path.suffix.lower() == ".sqf":
            result.append(str(path.resolve()))
        elif path.is_dir():
            result.extend(str(item.resolve()) for item in path.rglob("*.sqf") if item.is_file())
    return sorted(set(result))


class IncrementalLinter:
    """Track a set of SQF files and lint only changed files."""

    def __init__(self, paths: list[str]):
        self.paths = paths
        self._signatures: dict[str, tuple[int, int]] = {}
        self._files: list[str] = []
        self._index = None

    def poll(self) -> list[dict[str, object]]:
        files = _files(self.paths)
        signatures: dict[str, tuple[int, int]] = {}
        for file in files:
            try:
                stat = os.stat(file)
                signatures[file] = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                continue
        changed = sorted(set(files) ^ set(self._files) | {
            file for file, signature in signatures.items() if self._signatures.get(file) != signature
        })
        if changed or self._index is None:
            self._index = build_symbol_index(files)
        results: list[dict[str, object]] = []
        for file in changed:
            if file not in signatures:
                results.append({"file": file, "diagnostics": [], "deleted": True})
                continue
            diagnostics = lint_file(file, index=self._index)
            results.append({
                "file": file,
                "diagnostics": [
                    {"line": d.line, "column": d.column, "severity": d.severity.value, "code": d.code, "message": d.message}
                    for d in diagnostics
                ],
            })
        self._files = files
        self._signatures = signatures
        return results


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="armalint-watch", description="Incrementally lint changed SQF files.")
    parser.add_argument("paths", nargs="+", help="SQF file(s) or mission directories")
    parser.add_argument("--interval", type=float, default=0.5, help="poll interval in seconds (default: 0.5)")
    parser.add_argument("--once", action="store_true", help="scan changed files once and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.interval <= 0:
        _build_parser().error("--interval must be greater than zero")
    watcher = IncrementalLinter(args.paths)
    while True:
        for event in watcher.poll():
            print(json.dumps(event, sort_keys=True), flush=True)
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
