"""Runner for minimized production regression cases."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from armalint.linter import lint_file


CORPUS = Path(__file__).with_name("corpus")


def run_corpus() -> tuple[int, int, list[str]]:
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    passed = 0
    failures: list[str] = []
    cases = manifest.get("cases", [])
    for case in cases:
        path = CORPUS / case["file"]
        diagnostics = lint_file(str(path))
        actual = {diagnostic.code for diagnostic in diagnostics}
        expected = set(case.get("expect", []))
        missing = sorted(expected - actual)
        if missing:
            failures.append(f"{case['name']}: missing {', '.join(missing)}")
        else:
            passed += 1
    return passed, len(cases), failures


if __name__ == "__main__":
    passed, total, failures = run_corpus()
    print(f"{passed}/{total} corpus cases passed")
    if failures:
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)
