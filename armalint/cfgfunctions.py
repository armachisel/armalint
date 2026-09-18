"""Extract ``CfgFunctions`` function names from a parsed rapified config.

Arma 3 mods declare their precompiled functions under the ``CfgFunctions``
config root. The standard shape is::

    class CfgFunctions
    {
        class <tag>                // first-level child == the function tag
        {
            class <category>       // optional intermediate grouping (ignored)
            {
                class <fnc_name>   // a function: carries a ``file`` (and/or
                {                  // preInit/postInit/preStart/postStart,
                    file = "...";  // scriptName) property
                };
            };
        };
    };

The compiled function's global name is ``<tag>_fnc_<fnc_name>`` (lowercased).
Intermediate ``category`` classes are structural only and never contribute to
the name. This module walks a :class:`armalint.rapified.ConfigClass` tree and
returns the set of those full names; it does not require or perform any file
I/O.
"""

from __future__ import annotations

from .rapified import ConfigClass

#: Property names that mark a ``CfgFunctions`` child class as a function
#: definition (compared case-insensitively). The value is irrelevant — only
#: presence matters, matching how the engine recognizes a function entry.
_FUNCTION_PROPERTIES = frozenset(
    ("file", "scriptname", "preinit", "postinit", "prestart", "poststart")
)

_CFG_FUNCTIONS_NAME = "cfgfunctions"


def _effective_properties(
    node: ConfigClass,
    siblings: dict[str, ConfigClass] | None = None,
    seen: set[str] | None = None,
) -> dict:
    """Return local properties plus properties inherited from a local base.

    Rapified configs retain a class's base name, but do not encode a global
    symbol table.  CfgFunctions inheritance is normally between classes at the
    same level, so resolve only those local siblings.  This keeps extraction
    conservative when a base comes from another addon that is not available.
    """
    result: dict = {}
    if siblings and node.base:
        key = node.base.lower()
        seen = set() if seen is None else seen
        if key not in seen:
            parent = siblings.get(key)
            if parent is not None:
                result.update(_effective_properties(parent, siblings, seen | {key}))
    result.update(node.properties)
    return result


def _is_function(node: ConfigClass, siblings: dict[str, ConfigClass] | None = None) -> bool:
    """True if ``node`` or its local base carries a function marker."""
    return any(name.lower() in _FUNCTION_PROPERTIES for name in _effective_properties(node, siblings))


def extract_cfg_functions(config: ConfigClass) -> set[str]:
    """Return the set of full function names declared under ``CfgFunctions``.

    Every class named ``CfgFunctions`` (case-insensitive) anywhere in the tree
    is inspected. Its first-level children are tags; a descendant class of a
    tag that has any of ``file``/``scriptName``/``preInit``/``postInit``/
    ``preStart``/``postStart`` (case-insensitive) defines a function, whose
    full name is ``<tag>_fnc_<name>`` lowercased. Intermediate category
    classes do not appear in the name.
    """
    names: set[str] = set()

    def collect(node: ConfigClass, tag: str, siblings: list[ConfigClass]) -> None:
        sibling_map = {item.name.lower(): item for item in siblings}
        if _is_function(node, sibling_map):
            names.add(f"{tag}_fnc_{node.name.lower()}")
        for child in node.children:
            collect(child, tag, node.children)

    def visit(node: ConfigClass) -> None:
        if node.name.lower() == _CFG_FUNCTIONS_NAME:
            for tag in node.children:
                tag_name = tag.name.lower()
                for child in tag.children:
                    collect(child, tag_name, tag.children)
        for child in node.children:
            visit(child)

    visit(config)
    return names


def extract_cfg_function_files(config: ConfigClass) -> dict[str, str]:
    """Return declared function names mapped to their explicit ``file`` paths."""
    result: dict[str, str] = {}

    def collect(node: ConfigClass, tag: str, siblings: list[ConfigClass]) -> None:
        props = _effective_properties(node, {item.name.lower(): item for item in siblings})
        if any(key.lower() in _FUNCTION_PROPERTIES for key in props):
            for key, value in props.items():
                if key.lower() == "file" and isinstance(value, str):
                    result[f"{tag}_fnc_{node.name.lower()}"] = value
                    break
        for child in node.children:
            collect(child, tag, node.children)

    def visit(node: ConfigClass) -> None:
        if node.name.lower() == _CFG_FUNCTIONS_NAME:
            for tag in node.children:
                for child in tag.children:
                    collect(child, tag.name.lower(), tag.children)
        for child in node.children:
            visit(child)

    visit(config)
    return result


def extract_cfg_function_metadata(config: ConfigClass) -> dict[str, dict]:
    """Return descriptive and lifecycle metadata for declared functions."""
    result: dict[str, dict] = {}

    def collect(node: ConfigClass, tag: str, siblings: list[ConfigClass]) -> None:
        props = _effective_properties(node, {item.name.lower(): item for item in siblings})
        lowered = {str(k).lower(): v for k, v in props.items()}
        if any(key in _FUNCTION_PROPERTIES for key in lowered):
            name = f"{tag}_fnc_{node.name.lower()}"
            item = {"name": name, "confidence": "high", "provenance": "CfgFunctions"}
            for key in ("file", "description", "author", "preinit", "postinit", "prestart", "poststart"):
                if key in lowered and isinstance(lowered[key], (str, int, float, bool)):
                    item[key] = lowered[key]
            result[name] = item
        for child in node.children:
            collect(child, tag, node.children)

    def visit(node: ConfigClass) -> None:
        if node.name.lower() == _CFG_FUNCTIONS_NAME:
            for tag in node.children:
                for child in tag.children:
                    collect(child, tag.name.lower(), tag.children)
        for child in node.children:
            visit(child)

    visit(config)
    return result


if __name__ == "__main__":
    # Hand-built tree modeling the canonical nested layout from the task spec.
    tree = ConfigClass(
        name="",
        children=[
            ConfigClass(
                name="CfgFunctions",
                children=[
                    ConfigClass(
                        name="ace_medical",  # tag
                        children=[
                            ConfigClass(  # intermediate category (NOT in name)
                                name="medical",
                                children=[
                                    ConfigClass(name="setUnconscious", properties={"file": "a.sqf"}),
                                    ConfigClass(name="setDamage", properties={"file": "b.sqf"}),
                                ],
                            ),
                        ],
                    ),
                    ConfigClass(
                        name="CBA_settings",  # tag
                        children=[
                            ConfigClass(name="init", properties={"preInit": 1}),
                        ],
                    ),
                ],
            )
        ],
    )
    assert extract_cfg_functions(tree) == {
        "ace_medical_fnc_setunconscious",
        "ace_medical_fnc_setdamage",
        "cba_settings_fnc_init",
    }, extract_cfg_functions(tree)
    metadata = extract_cfg_function_metadata(tree)
    assert metadata["ace_medical_fnc_setunconscious"]["file"] == "a.sqf"
    assert metadata["cba_settings_fnc_init"]["preinit"] == 1

    # Case-insensitivity: CfgFunctions class name, property names, tag/function
    # casing all fold to lowercase in the result.
    mixed = ConfigClass(
        name="",
        children=[
            ConfigClass(
                name="cfgfunctions",
                children=[
                    ConfigClass(
                        name="MyTag",
                        children=[
                            ConfigClass(name="DoThing", properties={"FILE": "x.sqf"}),
                            ConfigClass(name="preThing", properties={"preStart": 0}),
                        ],
                    ),
                ],
            )
        ],
    )
    assert extract_cfg_functions(mixed) == {
        "mytag_fnc_dothing",
        "mytag_fnc_prething",
    }

    # Intermediate categories are ignored; every depth is searched.
    deep = ConfigClass(
        name="",
        children=[
            ConfigClass(
                name="CfgFunctions",
                children=[
                    ConfigClass(
                        name="t",
                        children=[
                            ConfigClass(
                                name="a",
                                children=[
                                    ConfigClass(
                                        name="b",
                                        children=[ConfigClass(name="leaf", properties={"file": "y.sqf"})],
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
    )
    assert extract_cfg_functions(deep) == {"t_fnc_leaf"}

    # Classes without any function-defining property are not functions.
    notfn = ConfigClass(
        name="",
        children=[
            ConfigClass(
                name="CfgFunctions",
                children=[
                    ConfigClass(
                        name="tag",
                        children=[
                            ConfigClass(name="category", properties={"requiredAddons": 0}, children=[
                                ConfigClass(name="noMarker", properties={"author": "me"}),
                            ]),
                        ],
                    )
                ],
            )
        ],
    )
    assert extract_cfg_functions(notfn) == set()

    # Multiple CfgFunctions blocks are unioned; non-CfgFunctions classes are
    # ignored entirely.
    multi = ConfigClass(
        name="",
        children=[
            ConfigClass(name="CfgVehicles", children=[ConfigClass(name="Car")]),
            ConfigClass(
                name="CfgFunctions",
                children=[ConfigClass(name="one", children=[ConfigClass(name="f", properties={"file": "1"})])],
            ),
            ConfigClass(
                name="CfgFunctions",
                children=[ConfigClass(name="two", children=[ConfigClass(name="g", properties={"postInit": 1})])],
            ),
        ],
    )
    assert extract_cfg_functions(multi) == {"one_fnc_f", "two_fnc_g"}

    # A local derived class inherits the function marker and file path from a
    # sibling base class.  External bases remain unresolved conservatively.
    inherited = ConfigClass(
        name="",
        children=[ConfigClass(
            name="CfgFunctions",
            children=[ConfigClass(
                name="tag",
                children=[
                    ConfigClass(name="baseFn", properties={"file": "base.sqf"}),
                    ConfigClass(name="derivedFn", base="baseFn"),
                    ConfigClass(name="externalFn", base="OtherAddonFn"),
                ],
            )],
        )],
    )
    assert extract_cfg_functions(inherited) == {"tag_fnc_basefn", "tag_fnc_derivedfn"}
    assert extract_cfg_function_files(inherited) == {
        "tag_fnc_basefn": "base.sqf",
        "tag_fnc_derivedfn": "base.sqf",
    }

    # Empty tree yields an empty set.
    assert extract_cfg_functions(ConfigClass(name="")) == set()

    print("cfgfunctions self-test passed")
