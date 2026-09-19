"""Conservative discovery of locals supplied to dynamically compiled SQF."""

from __future__ import annotations

import re


_COMPILE_RE = re.compile(
    r"\bcall\s+compile\s+preprocessFileLineNumbers\b(?P<arg>[^;\n]+)",
    re.IGNORECASE,
)
_PRIVATE_RE = re.compile(r"\bprivate\s+(_[A-Za-z0-9_]+)", re.IGNORECASE)
_PARAMS_RE = re.compile(r"\bparams\s*\[([^\]]*)\]", re.IGNORECASE | re.DOTALL)
_LOCAL_RE = re.compile(r"\b(_[A-Za-z][A-Za-z0-9_]*)\b")


def _declared_before(source: str, end: int) -> set[str]:
    """Return explicit locals declared before a compile call.

    Only ``private`` and simple array ``params`` declarations are considered;
    ordinary assignments are deliberately excluded to avoid treating globals
    as caller-provided locals.
    """
    prefix = source[:end]
    names = {match.group(1).lower() for match in _PRIVATE_RE.finditer(prefix)}
    for match in _PARAMS_RE.finditer(prefix):
        names.update(name.lower() for name in _LOCAL_RE.findall(match.group(1)))
    return names


def discover_external_locals(sources: dict[str, str]) -> set[str]:
    """Discover locals supplied to ``call compile preprocessFileLineNumbers``.

    SQF commonly compiles a template in the caller's scope.  When a caller has
    explicitly declared locals before that exact compile sequence, those names
    are valid in the compiled source even though they are absent from the
    template itself.  The path operand may be dynamic, so the resulting names
    are project-level contracts.  This is intentionally limited to the exact
    command sequence and explicit declarations; arbitrary assignments and
    similarly named variables are never inferred.
    """
    discovered: set[str] = set()
    for source in sources.values():
        for match in _COMPILE_RE.finditer(source):
            discovered.update(_declared_before(source, match.start()))
    return discovered


if __name__ == "__main__":
    sample = 'private _addon; call compile preprocessFileLineNumbers _path;'
    assert discover_external_locals({"loader.sqf": sample}) == {"_addon"}
    assert discover_external_locals({"plain.sqf": 'private _addon; compile _path;'}) == set()
    assert discover_external_locals({"params.sqf": 'params ["_addon"]; call compile preprocessFileLineNumbers _path;'}) == {"_addon"}
    print("contracts self-test passed")
