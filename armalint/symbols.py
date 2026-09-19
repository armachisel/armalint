"""Symbol index for Armalint.

Collects mission-defined function tags and full function names so the W201
unknown-function checker can recognize user-defined functions instead of
flagging them as false positives.

Names are stored lowercased because SQF identifiers are case-insensitive.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _normalize(name: str) -> str:
    """Lowercase and strip a name for storage/lookup."""
    return name.strip().lower()


@dataclass
class SymbolIndex:
    """Index of mission-defined function tags and full function names."""

    tags: set[str] = field(default_factory=set)
    functions: set[str] = field(default_factory=set)
    macros: set[str] = field(default_factory=set)
    cba_declared: bool = False

    def add_tag(self, tag: str) -> None:
        """Register a function tag (e.g. ``ALT`` -> ``alt``)."""
        self.tags.add(_normalize(tag))

    def add_function(self, name: str) -> None:
        """Register a full function name (e.g. ``ALT_fnc_foo`` -> ``alt_fnc_foo``)."""
        self.functions.add(_normalize(name))

    def add_macro(self, name: str) -> None:
        self.macros.add(_normalize(name))

    def is_known_function(self, name: str) -> bool:
        """True if ``name`` is a known mission function (case-insensitive).

        A name is known if it is present in :attr:`functions`, or if its
        leading tag (the part before the first ``_fnc_``) is present in
        :attr:`tags`.
        """
        n = _normalize(name)
        if n in self.functions:
            return True
        if "_fnc_" in n:
            tag = n.split("_fnc_", 1)[0]
            if tag in self.tags:
                return True
        return False

    def is_known_macro(self, name: str) -> bool:
        """True when a project-declared dependency provides this macro."""
        from .known import is_known_macro
        return _normalize(name) in self.macros or is_known_macro(name, cba_declared=self.cba_declared)

    def counts(self) -> tuple[int, int]:
        """Return ``(len(tags), len(functions))``."""
        return (len(self.tags), len(self.functions))

    def __len__(self) -> int:
        """Total number of collected symbols (tags + functions)."""
        return len(self.tags) + len(self.functions)


if __name__ == "__main__":
    idx = SymbolIndex()
    assert idx.counts() == (0, 0)
    assert len(idx) == 0

    idx.add_tag("ALT")
    idx.add_function("ALT_fnc_formatScore")
    assert idx.tags == {"alt"}
    assert idx.functions == {"alt_fnc_formatscore"}
    assert idx.counts() == (1, 1)
    assert len(idx) == 2

    assert idx.is_known_function("alt_fnc_formatscore")
    assert idx.is_known_function("ALT_fnc_formatScore")
    # Tag-only lookup: any ALT_fnc_* name is known via its tag.
    assert idx.is_known_function("ALT_fnc_doesNotExist")
    assert not idx.is_known_function("BIS_fnc_nope")
    assert not idx.is_known_function("someRandomCommand")

    print("symbols self-test passed")
