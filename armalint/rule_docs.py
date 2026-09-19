"""Generate the machine-maintained rule catalog from the rule registry."""

from __future__ import annotations

import argparse
from pathlib import Path

from .rules import RULES, RULE_CATEGORIES


def render_rule_catalog() -> str:
    lines = [
        "# Generated rule catalog",
        "",
        "This file is generated from `armalint.rules`. Do not edit it by hand.",
        "",
        "| Code | Severity | Categories | Description |",
        "| --- | --- | --- | --- |",
    ]
    for code, (severity, description) in sorted(RULES.items()):
        categories = ", ".join(category for category, codes in RULE_CATEGORIES.items() if code in codes) or "-"
        lines.append(f"| `{code}` | {severity} | {categories} | {description} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="armalint-rule-docs")
    parser.add_argument("--output", default="docs/rule-catalog.md")
    parser.add_argument("--check", action="store_true", help="fail if the generated file is stale")
    args = parser.parse_args(argv)
    target = Path(args.output)
    expected = render_rule_catalog()
    if args.check:
        try:
            return 0 if target.read_text(encoding="utf-8") == expected else 1
        except OSError:
            return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(expected, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
