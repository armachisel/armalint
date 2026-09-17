"""Regenerate Armalint data files from community mirror sources.

Run from the project root::

    python -m armalint.update_commands            # fetch, union, write
    python -m armalint.update_commands --dry-run  # fetch + report, no write

Two data files are maintained:

  * ``armalint/data/commands.txt``  -- SQF scripting commands.
  * ``armalint/data/functions.txt`` -- ``BIS_fnc_*`` functions.

Each database is a lowercase, one-name-per-line list seeded from GitHub mirrors
of the Bohemia Interactive Community Wiki. Regeneration is strictly *additive*:
the fetched names are UNION-ed with (i) the names already in the data file and
(ii) the inline fallback set in :mod:`armalint.known`, so no name is ever lost.

Only the standard library is used (``urllib.request`` for fetching).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from .known import _INLINE_COMMANDS, _INLINE_FUNCTIONS

# --- Source definitions (declarative: fetch URLs + a parser each) ------------

_REFERENCE_TXT_URL = (
    "https://raw.githubusercontent.com/ffredyk/SQF.VSC/main/reference.txt"
)

_GIT_TREE_URL_TEMPLATE = (
    "https://api.github.com/repos/kayler-renslow/arma-commands-syntax"
    "/git/trees/{ref}?recursive=1"
)
# HEAD should resolve for a normal checkout; fall back to master/main if it 404s.
_GIT_TREE_REFS = ("HEAD", "master", "main")
_COMMAND_XML_URL = "https://raw.githubusercontent.com/kayler-renslow/arma-commands-syntax/{ref}/command_xml/{name}.xml"

_FUNCTIONS_JSON_URL_TEMPLATE = (
    "https://raw.githubusercontent.com/HakonRydland/Arma3CfgFunctions"
    "/{ref}/Arma3CfgFunctions/src/Data/fnc.json"
)
_FUNCTIONS_JSON_REFS = ("main", "master")

_BIS_FNC_GIST_URL = "https://gist.githubusercontent.com/AgentRev/6426982/raw"


class FetchError(Exception):
    """Raised when a source cannot be fetched."""


@dataclass(frozen=True)
class Source:
    """One upstream source of names.

    ``name``  -- human-readable label (used in output and the file header).
    ``urls``  -- candidate URLs, tried in order until one succeeds.
    ``parse`` -- maps the fetched text to a set of raw candidate names.
    """

    name: str
    urls: tuple[str, ...]
    parse: Callable[[str], set[str]]


def _parse_reference_text(text: str) -> set[str]:
    """Parse the SQF.VSC ``reference.txt`` line list.

    One command per line; whitespace is stripped and blank lines / ``#``
    comments are skipped. Entries that are not valid identifiers (operators,
    multi-word wiki titles, etc.) are filtered out later by :func:`_normalize`.
    """
    names: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names.add(line)
    return names


def _parse_git_tree(text: str) -> set[str]:
    """Parse the kayler-renslow/arma-commands-syntax GitHub git-tree JSON.

    Command names are the basenames of ``*.xml`` blob files (minus the ``.xml``
    extension).
    """
    data = json.loads(text)
    names: set[str] = set()
    for entry in data.get("tree", []):
        path = entry.get("path", "")
        if entry.get("type") == "blob" and path.endswith(".xml"):
            names.add(os.path.basename(path)[:-len(".xml")])
    return names


def _parse_functions_json(text: str) -> set[str]:
    """Parse the Arma3CfgFunctions ``fnc.json`` (a dict keyed by function name).

    Only the lowercased ``bis_fnc_*`` keys are returned; ``bin_fnc_*`` (Eden
    editor) and any other tags are dropped, matching the ``BIS_fnc_*`` scope of
    ``armalint.known.KNOWN_FUNCTIONS``.
    """
    data = json.loads(text)
    names: set[str] = set()
    for key in data:
        if key.startswith("bis_fnc_"):
            names.add(key)
    return names


def _parse_bis_fnc_gist(text: str) -> set[str]:
    """Parse the AgentRev "All BIS_fnc's" gist (one ``BIS_fnc_*`` name per line)."""
    names: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("bis_fnc_"):
            names.add(line)
    return names


SOURCES: tuple[Source, ...] = (
    Source(
        name="ffredyk/SQF.VSC reference.txt (wiki Scripting Commands category mirror)",
        urls=(_REFERENCE_TXT_URL,),
        parse=_parse_reference_text,
    ),
    Source(
        name="kayler-renslow/arma-commands-syntax (one XML per command)",
        urls=tuple(_GIT_TREE_URL_TEMPLATE.format(ref=ref) for ref in _GIT_TREE_REFS),
        parse=_parse_git_tree,
    ),
)

FUNCTION_SOURCES: tuple[Source, ...] = (
    Source(
        name="HakonRydland/Arma3CfgFunctions fnc.json (BIS_fnc_* database)",
        urls=tuple(_FUNCTIONS_JSON_URL_TEMPLATE.format(ref=ref) for ref in _FUNCTIONS_JSON_REFS),
        parse=_parse_functions_json,
    ),
    Source(
        name="AgentRev gist 6426982 (all BIS_fnc_* names)",
        urls=(_BIS_FNC_GIST_URL,),
        parse=_parse_bis_fnc_gist,
    ),
)

# --- Normalization -----------------------------------------------------------

_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _normalize(name: str) -> str | None:
    """Return ``name`` lowercased if it is a valid SQF identifier, else None.

    This drops operator/multi-word wiki titles (anything not matching
    ``^[a-zA-Z_][a-zA-Z0-9_]*$``).
    """
    n = name.strip()
    if not n or not _NAME_RE.match(n):
        return None
    return n.lower()


def _normalize_all(names: Iterable[str]) -> set[str]:
    result: set[str] = set()
    for name in names:
        normalized = _normalize(name)
        if normalized is not None:
            result.add(normalized)
    return result


# --- Fetching ----------------------------------------------------------------

DEFAULT_TIMEOUT = 30.0

COMMANDS_PATH = Path(__file__).resolve().parent / "data" / "commands.txt"
FUNCTIONS_PATH = Path(__file__).resolve().parent / "data" / "functions.txt"
COMMAND_METADATA_PATH = Path(__file__).resolve().parent / "data" / "command_metadata.json"


def _parse_command_xml(text: str) -> dict[str, object]:
    """Parse one arma-commands-syntax XML document into JSON-safe metadata."""
    root = ET.fromstring(text)
    def types(element: ET.Element) -> list[str]:
        result: list[str] = []
        for value in element.findall(".//value"):
            value_type = value.attrib.get("type")
            if value_type:
                result.append(value_type.upper())
            for alternate in value.findall("./alt-types/t"):
                if alternate.attrib.get("type"):
                    result.append(alternate.attrib["type"].upper())
        return list(dict.fromkeys(result))

    syntaxes: list[dict[str, object]] = []
    for syntax in root.findall("./syntax"):
        params = []
        for param in syntax.findall("./param"):
            params.append({
                "name": param.attrib.get("name", ""),
                "type": param.attrib.get("type", "ANYTHING").upper(),
                "optional": param.attrib.get("optional", "f").lower() == "t",
                "order": int(param.attrib.get("order", "0")),
            })
        returns = types(syntax.find("./return")) if syntax.find("./return") is not None else []
        syntaxes.append({"params": params, "returns": returns})
    return {
        "name": root.attrib.get("name", ""),
        "version": root.attrib.get("version"),
        "game": root.attrib.get("game"),
        "deprecated": root.find("./deprecated") is not None,
        "uncertain": root.find("./uncertain") is not None,
        "syntaxes": syntaxes,
    }


def _metadata_return_type(metadata: dict[str, object]) -> str | None:
    """Return a single conservative return type when every syntax agrees."""
    values = {
        value
        for syntax in metadata.get("syntaxes", [])
        for value in syntax.get("returns", [])
        if isinstance(value, str) and value not in ("NOTHING", "VOID")
    }
    return next(iter(values)).title() if len(values) == 1 else None


def _fetch(url: str, timeout: float) -> str:
    request = urllib.request.Request(
        url, headers={"User-Agent": "armalint-command-updater"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace")
    except OSError as exc:
        raise FetchError(f"{url}: {exc}") from exc


def _fetch_source(source: Source, timeout: float) -> str:
    errors: list[str] = []
    for url in source.urls:
        try:
            return _fetch(url, timeout)
        except FetchError as exc:
            errors.append(str(exc))
    raise FetchError(
        f"{source.name}: all candidate URLs failed:\n    " + "\n    ".join(errors)
    )


# --- Data-file helpers -------------------------------------------------------

def _load_existing(path: Path) -> set[str]:
    """Load names already present in the data file (ignoring comments/blank lines)."""
    names: set[str] = set()
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                name = line.strip()
                if not name or name.startswith("#"):
                    continue
                names.add(name.lower())
    except OSError:
        # No existing file (e.g. first generation): nothing to preserve.
        pass
    return names


def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (temp file + ``os.replace``)."""
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".commands-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _format_header(
    count: int,
    generated: str,
    kind: str,
    kinds: str,
    inline_name: str,
    sources: tuple[Source, ...],
) -> str:
    lines = [
        f"# Armalint known SQF {kind} registry.",
        "#",
        f"# One lowercase {kind} name per line. Lines starting with '#' are",
        "# comments and blank lines are ignored. Loaded by armalint/known.py and",
        f"# UNION-ed with the inline {inline_name} fallback so the module keeps",
        "# working even if this file is missing.",
        "#",
        f"# Generated: {generated}",
        "# Method:     stdlib urllib.request against the community mirrors below;",
        "#             names are normalized (lowercase, ^[a-zA-Z_][a-zA-Z0-9_]*$),",
        "#             case-insensitively deduplicated, sorted, and written",
        "#             atomically.",
        "#",
        "# Sources (UNION):",
    ]
    for i, source in enumerate(sources, 1):
        lines.append(f"#   {i}. {source.name}")
        for url in source.urls:
            lines.append(f"#      {url}")
    lines.append(
        f"#   {len(sources) + 1}. Names already in this file "
        "(regeneration is additive; nothing is lost)."
    )
    lines.append(
        f"#   {len(sources) + 2}. The inline {inline_name} fallback in "
        "armalint/known.py."
    )
    lines.append("#")
    lines.append(f"# Total {kinds} in this file: {count}")
    lines.append("#")
    lines.append("# To regenerate, run: python -m armalint.update_commands")
    lines.append("# (add --dry-run to preview changes without writing).")
    return "\n".join(lines) + "\n"


# --- Main --------------------------------------------------------------------

@dataclass(frozen=True)
class _Dataset:
    """One regenerable data file."""

    label: str
    path: Path
    sources: tuple[Source, ...]
    inline: Iterable[str]
    kind: str
    kinds: str
    inline_name: str


DATASETS: tuple[_Dataset, ...] = (
    _Dataset(
        label="commands",
        path=COMMANDS_PATH,
        sources=SOURCES,
        inline=_INLINE_COMMANDS,
        kind="command",
        kinds="commands",
        inline_name="_INLINE_COMMANDS",
    ),
    _Dataset(
        label="functions",
        path=FUNCTIONS_PATH,
        sources=FUNCTION_SOURCES,
        inline=_INLINE_FUNCTIONS,
        kind="function",
        kinds="functions",
        inline_name="_INLINE_FUNCTIONS",
    ),
)


def _refresh(dataset: _Dataset, dry_run: bool) -> tuple[int, int, int]:
    """Fetch + union + (optionally) write one data file; return ``(current, new, added)``."""
    existing = _load_existing(dataset.path)
    current_count = len(existing)

    # Start from the existing names and the inline fallback so regeneration is
    # strictly additive and never loses a name.
    names: set[str] = set(existing)
    names |= _normalize_all(dataset.inline)

    print(f"\n{dataset.kinds} ({dataset.path.name}):")
    for index, source in enumerate(dataset.sources, 1):
        raw = _fetch_source(source, DEFAULT_TIMEOUT)
        fetched = _normalize_all(source.parse(raw))
        names |= fetched
        print(f"  [{index}/{len(dataset.sources)}] {source.name}")
        print(f"        fetched {len(fetched)} name(s)")

    new_count = len(names)
    added = new_count - current_count

    if not dry_run:
        generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") + " UTC"
        body = "".join(f"{name}\n" for name in sorted(names))
        _atomic_write(
            dataset.path,
            _format_header(
                new_count,
                generated,
                kind=dataset.kind,
                kinds=dataset.kinds,
                inline_name=dataset.inline_name,
                sources=dataset.sources,
            )
            + body,
        )
        print(f"  Wrote {dataset.path}")

    print(f"  current: {current_count}")
    print(f"  new:     {new_count}")
    print(f"  added:   {added}")
    return current_count, new_count, added


def _refresh_command_metadata(dry_run: bool, ref: str = "master") -> int:
    """Fetch typed XML definitions for all known commands and write JSON."""
    names = sorted(_load_existing(COMMANDS_PATH) | _normalize_all(_INLINE_COMMANDS))
    metadata: dict[str, dict[str, object]] = {}
    print(f"\ncommand metadata ({COMMAND_METADATA_PATH.name}):")
    for index, name in enumerate(names, 1):
        try:
            raw = _fetch(_COMMAND_XML_URL.format(ref=ref, name=name), DEFAULT_TIMEOUT)
            parsed = _parse_command_xml(raw)
        except (FetchError, ET.ParseError):
            continue
        metadata[name] = parsed
        if index % 100 == 0 or index == len(names):
            print(f"  parsed {index}/{len(names)} command XML files")
    if not dry_run:
        generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") + " UTC"
        payload = {"schema": 1, "generated": generated, "source": _COMMAND_XML_URL, "commands": metadata}
        _atomic_write(COMMAND_METADATA_PATH, json.dumps(payload, indent=2, sort_keys=True) + "\n")
        print(f"  Wrote {COMMAND_METADATA_PATH} ({len(metadata)} command definitions)")
    return len(metadata)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m armalint.update_commands",
        description=(
            "Regenerate armalint/data/commands.txt and armalint/data/functions.txt "
            "from community mirror sources."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and compute the result, but do not write the data files.",
    )
    parser.add_argument(
        "--signatures",
        action="store_true",
        help="also fetch typed command XML and write data/command_metadata.json",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))

    print("armalint data file updater")
    try:
        for dataset in DATASETS:
            _refresh(dataset, dry_run=args.dry_run)
        if args.signatures:
            _refresh_command_metadata(dry_run=args.dry_run)
    except FetchError as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("\nDry run (no changes written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
