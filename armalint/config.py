"""Project configuration for Armalint (standard library only).

A project may place an ``armalint.json`` (or ``.armalint.json``) file at its
root declaring mod function tags. These tags let mod-provided functions (e.g.
``ace_medical_fnc_*``, ``CBA_settings_fnc_*``) be recognized by the W201
unknown-function checker instead of being reported as false positives.
"""

from __future__ import annotations

import json
import os
import re
import sys

# Candidate config filenames, checked in order at each directory level.
_CONFIG_FILENAMES = ("armalint.json", ".armalint.json")

#: Filename of the mod function cache written by ``python -m armalint.update``.
MOD_CACHE_FILENAME = "armalint_mods.json"
MOD_TYPE_CACHE_FILENAME = "armalint_mods_types.json"

# Matches ``?id=<digits>`` or ``&id=<digits>`` in a Workshop URL; group 1 is
# the numeric id (kept as a string to preserve any leading zeros).
_WORKSHOP_ID_RE = re.compile(r"[?&]id=(\d+)")


def load_config_file(path: str) -> dict:
    """Read and JSON-decode the config file at ``path``.

    Returns ``{}`` when the file is missing or unreadable, or when its contents
    are not a JSON object. A JSON parse error produces a one-line warning on
    stderr; a missing file does not.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except OSError:
        return {}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"warning: could not parse config {path}: {exc}", file=sys.stderr)
        return {}

    if not isinstance(data, dict):
        return {}
    return data


def _find_upwards(start_path: str, filenames) -> str | None:
    """Walk up from ``start_path`` looking for the first existing file in ``filenames``.

    If ``start_path`` is a file, the search begins at its parent directory.
    At each directory the ``filenames`` are checked in order; the first existing
    one is returned, or ``None`` if none are found before the filesystem root.
    """
    if os.path.isfile(start_path):
        current = os.path.dirname(os.path.abspath(start_path))
    else:
        current = os.path.abspath(start_path)

    while True:
        for name in filenames:
            candidate = os.path.join(current, name)
            if os.path.isfile(candidate):
                return candidate
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def find_config(start_path: str) -> str | None:
    """Walk up from ``start_path`` looking for an Armalint config file.

    If ``start_path`` is a file, the search begins at its parent directory.
    At each directory, ``armalint.json`` is checked before ``.armalint.json``.
    The first match is returned; ``None`` if no config is found before the
    filesystem root.
    """
    return _find_upwards(start_path, _CONFIG_FILENAMES)


def find_mod_cache(start_path: str) -> str | None:
    """Walk up from ``start_path`` looking for an Armalint mod function cache.

    The cache (``armalint_mods.json``, written by ``python -m armalint.update``)
    is discovered using the same upward walk as :func:`find_config`: if
    ``start_path`` is a file, the search begins at its parent directory, then
    proceeds toward the filesystem root. The first ``armalint_mods.json`` found
    is returned, or ``None`` if none exists.
    """
    return _find_upwards(start_path, (MOD_CACHE_FILENAME,))


def find_mod_type_cache(start_path: str) -> str | None:
    """Walk upward for the cache of inferred mod function parameter types."""
    return _find_upwards(start_path, (MOD_TYPE_CACHE_FILENAME,))


def extract_function_tags(config: dict) -> set[str]:
    """Extract normalized mod function tags from ``config["functionTags"]``.

    The ``"functionTags"`` key is expected to be a list of strings. Each value
    is stripped and lowercased (SQF identifiers are case-insensitive); empty
    strings and non-string entries are ignored.
    """
    tags: set[str] = set()
    raw = config.get("functionTags")
    if not isinstance(raw, (list, tuple)):
        return tags
    for item in raw:
        if isinstance(item, str):
            tag = item.strip().lower()
            if tag:
                tags.add(tag)
    return tags


def extract_function_type_signatures(config: dict) -> dict[str, list[str]]:
    """Read optional ``functionTypes`` argument types from project config.

    Example: ``{"functionTypes": {"acme_fnc_route": ["Object", "String"]}}``.
    A type can be a union such as ``"String|Array"``. Invalid entries are
    ignored so one bad declaration does not prevent the rest of the config.
    """
    raw = config.get("functionTypes")
    if not isinstance(raw, dict):
        return {}
    result: dict[str, list[str]] = {}
    for name, types in raw.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(types, list):
            continue
        normalized = [item.strip() for item in types if isinstance(item, str) and item.strip()]
        if len(normalized) == len(types):
            result[name.strip().lower()] = normalized
    return result


def extract_function_return_types(config: dict) -> dict[str, str]:
    """Read optional ``functionReturns`` types from project config."""
    raw = config.get("functionReturns")
    if not isinstance(raw, dict):
        return {}
    result: dict[str, str] = {}
    for name, return_type in raw.items():
        if (isinstance(name, str) and name.strip()
                and isinstance(return_type, str) and return_type.strip()):
            result[name.strip().lower()] = return_type.strip()
    return result


def extract_ignored_rules(config: dict) -> set[str]:
    """Read rule codes configured for mission-wide suppression."""
    raw = config.get("ignoreRules")
    if not isinstance(raw, (list, tuple)):
        return set()
    return {
        item.strip().upper()
        for item in raw
        if isinstance(item, str) and re.fullmatch(r"(?:E|W)\d{3}", item.strip(), re.IGNORECASE)
    }


def extract_rule_severities(config: dict) -> dict[str, str]:
    """Read optional per-rule severities (``error``, ``warning``, ``info``, ``off``)."""
    raw = config.get("severity", config.get("ruleSeverity"))
    if not isinstance(raw, dict):
        return {}
    allowed = {"error", "warning", "info", "off"}
    return {
        code.upper(): value.lower()
        for code, value in raw.items()
        if isinstance(code, str) and re.fullmatch(r"(?:E|W)\d{3}", code.strip(), re.IGNORECASE)
        and isinstance(value, str) and value.lower() in allowed
    }


def extract_ignore_patterns(config: dict) -> list[str]:
    """Read file/directory glob patterns from ``ignore`` or ``ignorePatterns``."""
    raw = config.get("ignore", config.get("ignorePatterns"))
    if not isinstance(raw, (list, tuple)):
        return []
    return [item.strip() for item in raw if isinstance(item, str) and item.strip()]


def extract_mods(config: dict) -> list[dict]:
    """Normalize ``config["mods"]`` into a list of ``{"name", "url", "workshop_id"}`` dicts.

    Each entry may be a URL string (e.g. a Steam Workshop ``.../filedetails/?id=...``)
    or an object ``{"url": "...", "name": "..."}`` where ``name`` is optional.
    ``workshop_id`` is extracted from the URL via the regex ``[?&]id=(\\d+)``
    (group 1, kept as a string) or ``None`` when the URL has no such parameter.
    Entries without a usable (non-empty string) URL are skipped.
    """
    mods: list[dict] = []
    raw = config.get("mods")
    if not isinstance(raw, (list, tuple)):
        return mods

    for entry in raw:
        name: str | None = None
        if isinstance(entry, str):
            url = entry
        elif isinstance(entry, dict):
            name = entry.get("name")
            url = entry.get("url")
        else:
            continue

        if not isinstance(url, str):
            continue
        url = url.strip()
        if not url:
            continue

        if name is not None and not isinstance(name, str):
            name = None

        match = _WORKSHOP_ID_RE.search(url)
        workshop_id = match.group(1) if match else None

        mods.append({"name": name, "url": url, "workshop_id": workshop_id})

    return mods


if __name__ == "__main__":
    import tempfile

    # find_config walks up from a nested path to the project root.
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "proj")
        nested = os.path.join(root, "a", "b")
        os.makedirs(nested)
        cfg = os.path.join(root, ".armalint.json")
        with open(cfg, "w", encoding="utf-8") as fh:
            fh.write('{"functionTags": ["ace_medical", "CBA_settings"]}')
        assert find_config(nested) == cfg
        assert find_config(os.path.join(nested, "x.sqf")) == cfg
        assert find_config(tmp) is None

        # armalint.json is preferred over .armalint.json in the same directory.
        plain = os.path.join(root, "armalint.json")
        with open(plain, "w", encoding="utf-8") as fh:
            fh.write("{}")
        assert find_config(nested) == plain

        assert extract_function_return_types({
            "functionReturns": {"ALT_fnc_distanceToRoute": "Number", "bad": 3}
        }) == {"alt_fnc_distancetoroute": "Number"}
        assert extract_ignored_rules({"ignoreRules": ["w206", " W101 ", "bad", 3]}) == {"W206", "W101"}
        assert extract_rule_severities({"severity": {"w206": "error", "W209": "off", "bad": "warning", 3: "info"}}) == {"W206": "error", "W209": "off"}
        assert extract_ignore_patterns({"ignore": ["generated/**", "", 3]}) == ["generated/**"]

        # find_mod_cache walks up looking for armalint_mods.json.
        assert find_mod_cache(nested) is None
        cache = os.path.join(root, "armalint_mods.json")
        with open(cache, "w", encoding="utf-8") as fh:
            fh.write('["ace_medical_fnc_setunconscious"]')
        assert find_mod_cache(nested) == cache
        assert find_mod_cache(os.path.join(nested, "x.sqf")) == cache
        assert find_mod_cache(tmp) is None

    # load_config_file: missing -> {}, parse error -> {} with warning.
    assert load_config_file("__does_not_exist__.json") == {}
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=".json", delete=False
    ) as fh:
        bad_path = fh.name
        fh.write("{not json")
    assert load_config_file(bad_path) == {}
    os.remove(bad_path)

    # extract_function_tags normalization.
    assert extract_function_tags({}) == set()
    assert extract_function_tags({"functionTags": "nope"}) == set()
    assert extract_function_tags(
        {"functionTags": [" Ace_Medical ", "CBA_settings", "", "ace_medical", 42]}
    ) == {"ace_medical", "cba_settings"}
    assert extract_function_type_signatures({"functionTypes": {
        " Acme_fnc_route ": ["Object", "String|Array"], "bad": ["Number", 2], 7: ["Code"]
    }}) == {"acme_fnc_route": ["Object", "String|Array"]}

    # extract_mods normalization.
    assert extract_mods({}) == []
    assert extract_mods({"mods": "nope"}) == []
    assert extract_mods(
        {"mods": [
            "https://steamcommunity.com/sharedfiles/filedetails/?id=3168260137",
            {"name": "ACE3", "url": "https://steamcommunity.com/sharedfiles/filedetails/?id=463939057"},
            {"url": "https://example.com/some-page"},
            {"name": "missing url"},
            42,
        ]}
    ) == [
        {"name": None, "url": "https://steamcommunity.com/sharedfiles/filedetails/?id=3168260137", "workshop_id": "3168260137"},
        {"name": "ACE3", "url": "https://steamcommunity.com/sharedfiles/filedetails/?id=463939057", "workshop_id": "463939057"},
        {"name": None, "url": "https://example.com/some-page", "workshop_id": None},
    ]

    print("config self-test passed")
