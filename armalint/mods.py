"""Mod discovery and function-name extraction for Armalint (standard library only).

This module bridges the project's mod config (``extract_mods``) to the actual
Arma 3 content on disk:

  * ``discover_workshop_roots`` locates Steam Workshop content roots for Arma 3
    (app id ``107410``) by reading ``<steam>/steamapps/libraryfolders.vdf`` and
    falling back to common default Steam install locations.
  * ``iter_mod_dirs`` / ``resolve_workshop_mod`` / ``find_addon_mod`` map
    workshop ids and addon names to mod folders.
  * ``list_addons`` / ``extract_mod_functions`` pull the exact function names
    out of a mod folder, whether its addons are packed ``.pbo`` archives
    (``config.bin`` inside) or unpacked ``config.cpp``/``*.hpp`` directories.
    ``CfgFunctions`` declarations, CBA ``PREP`` files (``fnc_*.sqf`` at any
    depth, including the addon root) and HATG-style function files
    (``fn_*.sqf``, tagged with the mod's ``PREFIX`` from ``script_mod.hpp`` /
    ``script_component.hpp``) are all recognized.
  * ``load_mod_cache`` / ``save_mod_cache`` persist the extracted names as a
    sorted JSON array so they can be reused without re-reading every PBO.

Only the standard library is used.
"""

from __future__ import annotations

import json
import os
import shutil
import re

from .cfgfunctions import extract_cfg_functions, extract_cfg_function_files, extract_cfg_function_metadata
from .collect import collect_description_cfg_functions
from .pbo import read_pbo
from .rapified import parse_config_bin
from .symbols import SymbolIndex
from .tokenizer import Token, tokenize

MOD_TYPE_CACHE_FILENAME = "armalint_mods_types.json"
MOD_METADATA_CACHE_FILENAME = "armalint_mods_metadata.json"
MOD_SCAN_CACHE_FILENAME = "armalint_scan_cache.json"
MOD_SCAN_CACHE_VERSION = 3

#: Steam app id for Arma 3 (the numeric folder under ``workshop/content``).
_ARMA_APP_ID = "107410"

#: Common default Steam install locations checked when the environment does not
#: advertise one via ``PROGRAMFILES``/``PROGRAMFILES(X86)``.
_DEFAULT_STEAM_DIRS = (
    "C:/Program Files (x86)/Steam",
    "C:/Program Files/Steam",
)

#: Matches a VDF ``"path"  "value"`` entry; the value is captured raw (still
#: escaped) and decoded by :func:`_unescape_vdf`.
_VDF_PATH_RE = re.compile(r'"path"\s*"((?:[^"\\]|\\.)*)"')

#: Matches ``#define PREFIX <name>`` in a macro header (``script_mod.hpp`` /
#: ``script_component.hpp``). The directive is matched case-insensitively;
#: group 1 is the prefix name (e.g. ``hatg`` from HATG's ``script_mod.hpp``).
_PREFIX_RE = re.compile(r"(?im)^\s*#define\s+PREFIX\s+([A-Za-z0-9_]+)")


def _unescape_vdf(value: str) -> str:
    """Decode a VDF string value (``\\``, ``\"``, ``\\n`` etc. escapes)."""
    out: list[str] = []
    mapping = {"\\": "\\", '"': '"', "n": "\n", "r": "\r", "t": "\t"}
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            out.append(mapping.get(value[i + 1], value[i + 1]))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _steam_install_dirs() -> list[str]:
    """Best-effort list of existing Steam installation directories."""
    candidates: list[str] = []
    for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "PROGRAMW6432"):
        base = os.environ.get(env)
        if base:
            candidates.append(os.path.join(base, "Steam"))
    steam_env = os.environ.get("STEAM_DIR")
    if steam_env:
        candidates.append(steam_env)
    candidates.extend(_DEFAULT_STEAM_DIRS)
    user_dir = os.path.expanduser("~")
    candidates.extend((
        os.path.join(user_dir, ".steam", "steam"),
        os.path.join(user_dir, ".local", "share", "Steam"),
        os.path.join(user_dir, "Library", "Application Support", "Steam"),
    ))

    result: list[str] = []
    seen: set[str] = set()
    for cand in candidates:
        cand = os.path.normpath(cand)
        key = os.path.normcase(os.path.abspath(cand))
        if key in seen:
            continue
        seen.add(key)
        if os.path.isdir(cand):
            result.append(cand)
    return result


def discover_steamcmd(search_roots: list[str] | None = None) -> str | None:
    """Locate SteamCMD on PATH or inside one of the supplied project roots.

    Project-local discovery is deliberately scoped to the root itself.  In
    particular, do not search sibling projects: a dependency download should
    be reproducible from the project being updated, and an unrelated checkout
    must not silently determine which executable is used.
    """
    candidates: list[str] = []
    for name in ("STEAMCMD", "STEAMCMD_PATH"):
        value = os.environ.get(name)
        if value: candidates.append(value)
    for executable in ("steamcmd.exe", "steamcmd"):
        found = shutil.which(executable)
        if found: candidates.append(found)
    for root in search_roots or []:
        root = os.path.abspath(os.path.expanduser(root))
        candidates.extend([
            os.path.join(root, "steamcmd.exe"),
            os.path.join(root, "steamcmd", "steamcmd.exe"),
            os.path.join(root, "tmp", "steamcmd", "steamcmd.exe"),
            os.path.join(root, "tools", "steamcmd", "steamcmd.exe"),
            os.path.join(root, ".armalint", "bin", "steamcmd.exe"),
        ])
    seen: set[str] = set()
    for candidate in candidates:
        candidate = os.path.abspath(os.path.expanduser(candidate))
        key = os.path.normcase(candidate)
        if key not in seen and os.path.isfile(candidate):
            return candidate
        seen.add(key)
    return None


def discover_arma_install_dirs(steam_dirs: list[str] | None = None) -> list[str]:
    """Find installed Arma 3 roots in known Steam libraries and common paths.

    Steam's ``libraryfolders.vdf`` is used to find additional libraries on
    other drives. ``ARMA3_DIR`` can point at a non-Steam installation. Passing
    ``steam_dirs`` is primarily useful for deterministic tests.
    """
    roots = list(steam_dirs if steam_dirs is not None else _steam_install_dirs())
    candidates: list[str] = []
    for env_name in ("ARMA3_DIR", "ARMA_3_DIR"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(value)
    for steam_dir in roots:
        libraries = [steam_dir]
        vdf_path = os.path.join(steam_dir, "steamapps", "libraryfolders.vdf")
        try:
            with open(vdf_path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            content = ""
        libraries.extend(_unescape_vdf(m.group(1)) for m in _VDF_PATH_RE.finditer(content))
        for library in libraries:
            candidates.append(os.path.join(library, "steamapps", "common", "Arma 3"))

    found: dict[str, str] = {}
    for candidate in candidates:
        candidate = os.path.abspath(os.path.expanduser(candidate))
        addons = _child_path_case_insensitive(candidate, "Addons")
        if not os.path.isdir(candidate) or not addons or not os.path.isdir(addons):
            continue
        key = os.path.normcase(candidate)
        found.setdefault(key, candidate)
    return sorted(found.values(), key=os.path.normcase)


def discover_workshop_roots() -> list[str]:
    """Discover Arma 3 Workshop content roots (``.../workshop/content/107410``).

    Reads each Steam install's ``steamapps/libraryfolders.vdf`` for ``"path"``
    entries and also checks the default install locations; returns the existing
    content directories (empty list if none are found).
    """
    roots: list[str] = []
    seen: set[str] = set()

    def add(root: str) -> None:
        root = os.path.normpath(root)
        key = os.path.normcase(os.path.abspath(root))
        if key in seen or not os.path.isdir(root):
            return
        seen.add(key)
        roots.append(root)

    for steam_dir in _steam_install_dirs():
        add(os.path.join(steam_dir, "steamapps", "workshop", "content", _ARMA_APP_ID))
        vdf_path = os.path.join(steam_dir, "steamapps", "libraryfolders.vdf")
        try:
            with open(vdf_path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        for m in _VDF_PATH_RE.finditer(text):
            lib = _unescape_vdf(m.group(1))
            if lib:
                add(os.path.join(lib, "steamapps", "workshop", "content", _ARMA_APP_ID))

    return roots


def iter_mod_dirs(roots: list[str], name_filter=None) -> list[str]:
    """List the immediate subdirectories of each root (individual mod folders).

    ``name_filter``, when given, is called with each subdirectory's *name* and
    must return true for the folder to be considered a mod folder (used to
    restrict Arma install directories to their ``@``-prefixed mods). Results
    are deduplicated and sorted for determinism.
    """
    dirs: list[str] = []
    seen: set[str] = set()
    for root in roots:
        try:
            entries = os.listdir(root)
        except OSError:
            continue
        for name in entries:
            if name_filter is not None and not name_filter(name):
                continue
            full = os.path.join(root, name)
            if not os.path.isdir(full):
                continue
            key = os.path.normcase(os.path.abspath(full))
            if key not in seen:
                seen.add(key)
                dirs.append(full)
    dirs.sort(key=lambda p: os.path.normcase(p))
    return dirs


def resolve_workshop_mod(workshop_id: str, roots: list[str]) -> str | None:
    """Return ``<root>/<workshop_id>`` if it exists, else ``None``."""
    for root in roots:
        candidate = os.path.join(root, workshop_id)
        if os.path.isdir(candidate):
            return candidate
    return None


def _contains_case_insensitive(dirpath: str, filename: str) -> bool:
    """True if ``dirpath`` contains ``filename`` (case-insensitive) as a file."""
    target = filename.lower()
    try:
        entries = os.listdir(dirpath)
    except OSError:
        return False
    for name in entries:
        if name.lower() == target and os.path.isfile(os.path.join(dirpath, name)):
            return True
    return False


def _child_path_case_insensitive(dirpath: str, filename: str) -> str | None:
    """Return a child path matching ``filename`` irrespective of casing."""
    try:
        entries = os.listdir(dirpath)
    except OSError:
        return None
    for entry in entries:
        if entry.lower() == filename.lower():
            return os.path.join(dirpath, entry)
    return None


def discover_game_addon_roots(game_dir: str) -> list[str]:
    """Return the Arma root and direct DLC roots containing an Addons dir.

    Deliberately does not recurse: Workshop content may live inside the game
    folder and must only be scanned when selected by the mission or config.
    """
    game_dir = os.path.abspath(game_dir)
    candidates = [game_dir]
    try:
        children = os.listdir(game_dir)
    except OSError:
        children = []
    for name in children:
        if name.startswith(("!", "@")) or name.isdigit():
            continue
        path = os.path.join(game_dir, name)
        if os.path.isdir(path):
            candidates.append(path)

    roots: set[str] = set()
    for root in candidates:
        addon_dir = _child_path_case_insensitive(root, "Addons")
        if not addon_dir or not os.path.isdir(addon_dir):
            continue
        try:
            if any(name.lower().endswith(".pbo") for name in os.listdir(addon_dir)):
                roots.add(root)
        except OSError:
            continue
    return sorted(roots, key=os.path.normcase)


def find_game_addon(addon_name: str, game_addon_roots: list[str]) -> str | None:
    """Return the installation root containing a base-game/DLC addon PBO."""
    target = (addon_name + ".pbo").lower()
    for root in game_addon_roots:
        addons_dir = _child_path_case_insensitive(root, "Addons")
        if not addons_dir:
            continue
        try:
            for entry in os.listdir(addons_dir):
                full = os.path.join(addons_dir, entry)
                if entry.lower() == target and os.path.isfile(full):
                    return root
        except OSError:
            continue
    return None


def find_addon_mod(addon_name: str, roots: list[str], name_filter=None) -> str | None:
    """Return the first mod dir containing ``addon_name``, else ``None``.

    A mod "contains" the addon when its ``addons/`` directory holds either
    ``<addon_name>.pbo`` or a ``<addon_name>/`` directory with a ``config.cpp``
    (both matched case-insensitively). ``name_filter`` is forwarded to
    :func:`iter_mod_dirs` to restrict which subdirectories count as mod folders.
    """
    name = addon_name.lower()
    pbo_name = name + ".pbo"
    for mod_dir in iter_mod_dirs(roots, name_filter=name_filter):
        addons_dir = os.path.join(mod_dir, "addons")
        if not os.path.isdir(addons_dir):
            continue
        try:
            entries = os.listdir(addons_dir)
        except OSError:
            continue
        for entry in entries:
            entry_lower = entry.lower()
            full = os.path.join(addons_dir, entry)
            if entry_lower == pbo_name and os.path.isfile(full):
                return mod_dir
            if (
                entry_lower == name
                and os.path.isdir(full)
                and _contains_case_insensitive(full, "config.cpp")
            ):
                return mod_dir
    return None


def list_addons(mod_dir: str) -> list[tuple[str, str]]:
    """Return ``[(kind, path)]`` for the addons of ``mod_dir``.

    ``kind`` is ``"pbo"`` for ``addons/*.pbo`` files, or ``"dir"`` for
    ``addons/*/`` directories that contain a ``config.cpp`` (case-insensitive).
    """
    addons_dir = _child_path_case_insensitive(mod_dir, "addons")
    if addons_dir is None:
        return []
    if not os.path.isdir(addons_dir):
        return []
    try:
        entries = sorted(os.listdir(addons_dir), key=lambda e: e.lower())
    except OSError:
        return []
    result: list[tuple[str, str]] = []
    for entry in entries:
        full = os.path.join(addons_dir, entry)
        if entry.lower().endswith(".pbo") and os.path.isfile(full):
            result.append(("pbo", full))
        elif os.path.isdir(full) and _contains_case_insensitive(full, "config.cpp"):
            result.append(("dir", full))
    return result


def _path_parts(path: str) -> list[str]:
    """Split a PBO-internal or filesystem path into non-empty components.

    Handles both ``\\`` and ``/`` separators (PBO archives use either).
    """
    return [part for part in path.replace("\\", "/").split("/") if part]


def _is_prep_function_path(path: str) -> bool:
    """True if ``path`` is a CBA ``PREP`` function file (``fnc_*.sqf``).

    The basename must start with ``fnc_`` and end with ``.sqf`` (case-
    insensitive). The file may live at any depth, including the PBO/addon root
    (CBA compiles component functions at the root, e.g. ``fnc_set.sqf``), and
    also under a ``functions`` directory (ACE3 convention). Files following the
    HATG ``fn_*.sqf`` convention are NOT matched.
    """
    parts = _path_parts(path)
    if not parts:
        return False
    base = parts[-1].lower()
    return base.startswith("fnc_") and base.endswith(".sqf")


def _prep_function_name(tag: str, path: str) -> str:
    """Map a PREP file path to its global function name under ``tag``.

    e.g. ``("ace_medical", "functions/fnc_setUnconscious.sqf")`` ->
    ``"ace_medical_fnc_setunconscious"``.
    """
    parts = _path_parts(path)
    base = parts[-1]
    name = base[4:-4]  # strip the leading "fnc_" and trailing ".sqf"
    return f"{tag}_fnc_{name}".lower()


def _is_hatg_function_path(path: str) -> bool:
    """True if ``path`` is a HATG function file (``fn_*.sqf``, case-insensitive).

    Matches the HATG convention where function files are named ``fn_<name>.sqf``
    (distinct from the CBA ``fnc_`` prefix handled by
    :func:`_is_prep_function_path`). The file may live at any depth.
    """
    parts = _path_parts(path)
    if not parts:
        return False
    base = parts[-1].lower()
    return base.startswith("fn_") and base.endswith(".sqf")


def _hatg_function_name(tag: str, path: str) -> str:
    """Map a HATG ``fn_*.sqf`` path to its global function name under ``tag``.

    e.g. ``("hatg", "functions/display/fn_getDisplay.sqf")`` ->
    ``"hatg_fnc_getdisplay"``.
    """
    parts = _path_parts(path)
    base = parts[-1]
    name = base[3:-4]  # strip the leading "fn_" and trailing ".sqf"
    return f"{tag}_fnc_{name}".lower()


def _addon_tag(addon_path: str) -> str:
    """Return an addon's function tag: its basename without a ``.pbo`` suffix."""
    base = os.path.basename(os.path.normpath(addon_path))
    if base.lower().endswith(".pbo"):
        base = base[:-4]
    return base


def _read_prefix_from_files(files: dict[str, bytes]) -> str | None:
    """Extract ``#define PREFIX <name>`` from a PBO's macro headers, if present.

    Scans ``script_mod.hpp`` and ``script_component.hpp`` (case-insensitive,
    in that order) for a ``#define PREFIX <name>`` directive and returns the
    matched name, or ``None``.
    """
    for wanted in ("script_mod.hpp", "script_component.hpp"):
        for name, data in files.items():
            if name.lower() != wanted:
                continue
            text = data.decode("utf-8", "replace")
            match = _PREFIX_RE.search(text)
            if match:
                return match.group(1)
    return None


def _read_prefix_from_dir(addon_dir: str) -> str | None:
    """Extract ``#define PREFIX <name>`` from an unpacked addon's macro headers."""
    try:
        entries = sorted(os.listdir(addon_dir), key=lambda e: e.lower())
    except OSError:
        return None
    for wanted in ("script_mod.hpp", "script_component.hpp"):
        for entry in entries:
            if entry.lower() != wanted:
                continue
            full = os.path.join(addon_dir, entry)
            if not os.path.isfile(full):
                continue
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            match = _PREFIX_RE.search(text)
            if match:
                return match.group(1)
    return None


def _mod_prefix(mod_dir: str) -> str | None:
    """Return a mod's ``PREFIX`` from any of its addons, or ``None``.

    HATG defines ``#define PREFIX hatg`` in ``core.pbo``'s ``script_mod.hpp``
    while its ``fn_*.sqf`` function files live in sibling addons (``gui.pbo``,
    ``functions.pbo``). Scanning every addon lets those siblings reuse the
    mod-wide prefix as their function tag even when their own ``script_component.hpp``
    only ``#include``\\s the real ``script_mod.hpp``.
    """
    for kind, path in list_addons(mod_dir):
        if kind == "pbo":
            try:
                files = read_pbo(path)
            except Exception:
                continue
            prefix = _read_prefix_from_files(files)
        else:
            prefix = _read_prefix_from_dir(path)
        if prefix:
            return prefix
    return None


def _dir_function_files(addon_dir: str, mod_prefix: str | None = None) -> set[str]:
    """Extract function names from function files in an unpacked addon.

    CBA ``fnc_*.sqf`` files (tag = addon basename) and HATG ``fn_*.sqf`` files
    (tag = the addon's own ``PREFIX``, else ``mod_prefix``, else the addon
    basename) at any depth are recognized.
    """
    tag = _addon_tag(addon_dir)
    hatg_tag = _read_prefix_from_dir(addon_dir) or mod_prefix or tag
    result: set[str] = set()
    for _dirpath, _dirnames, filenames in os.walk(addon_dir):
        for filename in filenames:
            lower = filename.lower()
            if lower.startswith("fnc_") and lower.endswith(".sqf"):
                name = filename[4:-4]  # strip the leading "fnc_" and trailing ".sqf"
                result.add(f"{tag}_fnc_{name}".lower())
            elif lower.startswith("fn_") and lower.endswith(".sqf"):
                name = filename[3:-4]  # strip the leading "fn_" and trailing ".sqf"
                result.add(f"{hatg_tag}_fnc_{name}".lower())
    return result


def _extract_pbo_functions(pbo_path: str, mod_prefix: str | None = None) -> set[str]:
    """Extract function names from a packed addon (``CfgFunctions`` + PREP + HATG).

    Reads the PBO once and unions the ``CfgFunctions`` names from ``config.bin``
    with CBA ``PREP`` names derived from ``fnc_*.sqf`` files (whose tag is the
    PBO basename without ``.pbo``) and HATG names derived from ``fn_*.sqf``
    files (whose tag is the addon's own ``PREFIX``, else ``mod_prefix``, else
    the PBO basename).
    """
    try:
        files = read_pbo(pbo_path)
    except Exception:
        return set()

    functions: set[str] = set()
    config_bin: bytes | None = None
    for name, data in files.items():
        if name.lower() == "config.bin":
            config_bin = data
            break
    if config_bin is not None:
        try:
            config = parse_config_bin(config_bin)
            functions |= extract_cfg_functions(config)
        except Exception:
            pass

    tag = _addon_tag(pbo_path)
    hatg_tag = _read_prefix_from_files(files) or mod_prefix or tag
    for name in files:
        if _is_prep_function_path(name):
            functions.add(_prep_function_name(tag, name))
        elif _is_hatg_function_path(name):
            functions.add(_hatg_function_name(hatg_tag, name))
    return functions


def _extract_dir_functions(addon_dir: str, mod_prefix: str | None = None) -> set[str]:
    """Extract function names from an unpacked addon (``CfgFunctions`` + PREP + HATG)."""
    try:
        entries = sorted(os.listdir(addon_dir), key=lambda e: e.lower())
    except OSError:
        return set()
    index = SymbolIndex()
    for entry in entries:
        lower = entry.lower()
        if lower != "config.cpp" and not lower.endswith(".hpp"):
            continue
        full = os.path.join(addon_dir, entry)
        if not os.path.isfile(full):
            continue
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as fh:
                source = fh.read()
        except OSError:
            continue
        collect_description_cfg_functions(source, index)
    functions = set(index.functions)
    functions |= _dir_function_files(addon_dir, mod_prefix)
    return functions


def extract_mod_functions(mod_dir: str) -> set[str]:
    """Extract exact function names (lowercased) from ``mod_dir``."""
    return extract_mod_data(mod_dir)[0]


def _split_sqf_array(tokens: list[Token], start: int) -> tuple[list[list[Token]], int] | None:
    """Split a tokenized array literal at top-level commas."""
    depth = 0
    pieces: list[list[Token]] = []
    item_start = start + 1
    for i in range(start, len(tokens)):
        kind = tokens[i].type
        if kind == "lbracket":
            depth += 1
        elif kind == "rbracket":
            depth -= 1
            if depth == 0:
                if i > item_start:
                    pieces.append(tokens[item_start:i])
                return pieces, i
        elif kind == "comma" and depth == 1:
            pieces.append(tokens[item_start:i])
            item_start = i + 1
    return None


def _sqf_type(token: Token) -> str | None:
    if token.type == "number":
        return "Number"
    if token.type == "string":
        return "String"
    if token.type == "lbracket":
        return "Array"
    if token.type == "lbrace":
        return "Code"
    if token.type == "keyword" and token.value.lower() in ("true", "false"):
        return "Boolean"
    if token.type == "ident":
        return {
            "objnull": "Object", "grpnull": "Group", "locationnull": "Location",
            "controlnull": "Control", "displaynull": "Display",
            "west": "Side", "east": "Side", "resistance": "Side",
            "civilian": "Side",
        }.get(token.value.lower())
    return None


def _extract_params_types(source: str) -> list[str | None]:
    """Read explicit ``params`` expectedDataTypes constraints from SQF source.

    Unconstrained params are represented by ``None`` to preserve their
    positions in the argument list. Defaults alone are not treated as a type
    contract because SQF params allows other types unless a validator is given.
    """
    tokens = tokenize(source)
    result: list[str | None] = []
    for i, tok in enumerate(tokens):
        if tok.type != "keyword" or tok.value.lower() != "params":
            continue
        j = i + 1
        while j < len(tokens) and tokens[j].type in ("comment", "preprocessor"):
            j += 1
        if j >= len(tokens) or tokens[j].type != "lbracket":
            continue
        outer = _split_sqf_array(tokens, j)
        if outer is None:
            continue
        params, _end = outer
        result = []
        for param in params:
            first = next((x for x in param if x.type not in ("comment", "preprocessor")), None)
            if first is None:
                continue
            if first.type == "string":
                result.append(None)
                continue
            if first.type != "lbracket":
                result.append(None)
                continue
            fields = _split_sqf_array(param, param.index(first))
            if fields is None:
                result.append(None)
                continue
            field_items, _ = fields
            if len(field_items) < 3:
                result.append(None)
                continue
            type_array = next((x for x in field_items[2] if x.type not in ("comment", "preprocessor")), None)
            if type_array is None or type_array.type != "lbracket":
                result.append(None)
                continue
            allowed = _split_sqf_array(field_items[2], field_items[2].index(type_array))
            if allowed is None:
                result.append(None)
                continue
            allowed_items, _ = allowed
            types: list[str] = []
            for item in allowed_items:
                scalar = [x for x in item if x.type not in ("comment", "preprocessor")]
                if len(scalar) == 1:
                    found = _sqf_type(scalar[0])
                    if found and found not in types:
                        types.append(found)
            result.append("|".join(types) if types else None)
        break

    # `param [index, default, [allowedTypeExamples]]` validates an individual
    # positional argument. Merge these into params declarations, or build a
    # sparse positional signature when the function only uses param.
    for i, tok in enumerate(tokens):
        if tok.type not in ("keyword", "ident") or tok.value.lower() != "param":
            continue
        j = i + 1
        while j < len(tokens) and tokens[j].type in ("comment", "preprocessor"):
            j += 1
        if j >= len(tokens) or tokens[j].type != "lbracket":
            continue
        parsed = _split_sqf_array(tokens, j)
        if not parsed:
            continue
        fields, _ = parsed
        if len(fields) < 3:
            continue
        index_token = next((x for x in fields[0] if x.type not in ("comment", "preprocessor")), None)
        if not index_token or index_token.type != "number":
            continue
        try:
            index = int(float(index_token.value))
        except ValueError:
            continue
        if index < 0 or index > 255:
            continue
        allowed_token = next((x for x in fields[2] if x.type not in ("comment", "preprocessor")), None)
        if not allowed_token or allowed_token.type != "lbracket":
            continue
        allowed = _split_sqf_array(fields[2], fields[2].index(allowed_token))
        if not allowed:
            continue
        types: list[str] = []
        for item in allowed[0]:
            scalar = [x for x in item if x.type not in ("comment", "preprocessor")]
            if len(scalar) == 1:
                found = _sqf_type(scalar[0])
                if found and found not in types:
                    types.append(found)
        if not types:
            continue
        while len(result) <= index:
            result.append(None)
        current = result[index]
        found = "|".join(types)
        if current is None:
            result[index] = found
        else:
            merged = list(dict.fromkeys(current.split("|") + types))
            result[index] = "|".join(merged)
    return result


def extract_mod_function_signatures(mod_dir: str) -> dict[str, list[str | None]]:
    """Extract explicit function argument contracts from ``mod_dir``."""
    return extract_mod_data(mod_dir)[1]


def _directory_addon_files(addon_dir: str) -> dict[str, bytes]:
    """Read relevant source/config files from an unpacked addon in one walk."""
    result: dict[str, bytes] = {}
    for root, _dirs, names in os.walk(addon_dir):
        for name in names:
            lower = name.lower()
            if not (lower.endswith((".sqf", ".hpp")) or lower == "config.cpp"):
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, addon_dir)
            try:
                with open(full, "rb") as fh:
                    result[rel] = fh.read()
            except OSError:
                continue
    return result


def _extract_cfg_file_paths(source: str, cfg_names: set[str]) -> dict[str, str]:
    """Best-effort extraction of explicit textual CfgFunctions file paths."""
    pattern = re.compile(
        r'class\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{(?:(?!\bclass\b).)*?\bfile\s*=\s*"([^"]+)"',
        re.IGNORECASE | re.DOTALL,
    )
    result: dict[str, str] = {}
    for function, path in pattern.findall(source):
        suffix = "_fnc_" + function.lower()
        for name in cfg_names:
            if name.lower().endswith(suffix):
                result[name] = path
    return result


def _walk_config(config):
    """Yield every node in a parsed rapified config tree."""
    yield config
    for child in config.children:
        yield from _walk_config(child)


def extract_mod_data(
    mod_dir: str,
    progress=None,
    addon_names: set[str] | None = None,
    metadata: dict | None = None,
) -> tuple[set[str], dict[str, list[str | None]]]:
    """Extract function names and explicit argument types in one addon pass.

    Each PBO is opened once and each unpacked addon is walked once. Relevant
    SQF sources are retained until the mod-wide HATG prefix is known, then
    names and signatures are attributed together.
    """
    records: list[tuple[str, str, str | None, set[str], dict[str, str], dict[str, dict], dict[str, bytes], str]] = []
    if metadata is not None:
        metadata.setdefault("errors", [])
        metadata.setdefault("sources", {})
    mod_prefix: str | None = None

    addons = list_addons(mod_dir)
    for kind, path in addons:
        if progress:
            progress(path, False)
        if kind == "pbo":
            try:
                files = read_pbo(path)
            except Exception as exc:
                if metadata is not None:
                    metadata["errors"].append({"path": path, "kind": "unreadable-or-unsupported-pbo", "error": str(exc)})
                if progress:
                    progress(path, True)
                continue
            cfg_names: set[str] = set()
            cfg_files: dict[str, str] = {}
            cfg_metadata: dict[str, dict] = {}
            for name, data in files.items():
                if name.lower() == "config.bin":
                    try:
                        config = parse_config_bin(data)
                        cfg_names = extract_cfg_functions(config)
                        cfg_files = extract_cfg_function_files(config)
                        cfg_metadata = extract_cfg_function_metadata(config)
                        if addon_names is not None:
                            addon_names.update(
                                child.name.lower()
                                for node in _walk_config(config)
                                if node.name.lower() == "cfgpatches"
                                for child in node.children
                            )
                    except Exception:
                        pass
                    break
            if addon_names is not None:
                addon_names.add(os.path.splitext(os.path.basename(path))[0].lower())
            tag = _addon_tag(path)
            prefix = _read_prefix_from_files(files)
            sources = {name: data for name, data in files.items() if name.lower().endswith(".sqf")}
        else:
            files = _directory_addon_files(path)
            cfg_index = SymbolIndex()
            cfg_sources: list[str] = []
            for name, data in files.items():
                if name.lower() == "config.cpp" or ("\\" not in name and "/" not in name and name.lower().endswith(".hpp")):
                    text = data.decode("utf-8", errors="replace")
                    collect_description_cfg_functions(text, cfg_index)
                    cfg_sources.append(text)
            cfg_names = set(cfg_index.functions)
            cfg_files = {}
            cfg_metadata = {}
            for text in cfg_sources:
                cfg_files.update(_extract_cfg_file_paths(text, cfg_names))
            tag = _addon_tag(path)
            prefix = _read_prefix_from_files(files)
            sources = {name: data for name, data in files.items() if name.lower().endswith(".sqf")}
        if prefix and mod_prefix is None:
            mod_prefix = prefix
        records.append((kind, tag, prefix, cfg_names, cfg_files, cfg_metadata, sources, path))
        if progress:
            progress(path, True)

    functions: set[str] = set()
    signatures: dict[str, list[str | None]] = {}
    for kind, tag, prefix, cfg_names, cfg_files, cfg_metadata, sources, addon_path in records:
        functions.update(cfg_names)
        if metadata is not None:
            for name in cfg_names:
                metadata["sources"].setdefault(name, addon_path)
            for name, details in cfg_metadata.items():
                metadata.setdefault("functions", {}).setdefault(name, {}).update(details)
        hatg_tag = prefix or mod_prefix or tag
        cfg_by_suffix: dict[str, set[str]] = {}
        for name in cfg_names:
            suffix = "_fnc_" + name.rsplit("_fnc_", 1)[-1]
            cfg_by_suffix.setdefault(suffix, set()).add(name)
        for path, raw in sources.items():
            if _is_prep_function_path(path):
                function_names = {_prep_function_name(tag, path)}
            elif _is_hatg_function_path(path):
                function_names = {_hatg_function_name(hatg_tag, path)}
            else:
                base = _path_parts(path)[-1][:-4].lower()
                if base.startswith("fn_"):
                    base = base[3:]
                function_names = set()
                normalized_path = path.replace("\\", "/").lower()
                for name, declared_path in cfg_files.items():
                    declared = declared_path.replace("\\", "/").lower()
                    if (normalized_path.endswith(declared.lstrip("/"))
                            or normalized_path.rsplit("/", 1)[-1] == declared.rsplit("/", 1)[-1]):
                        function_names.add(name)
                for suffix, candidates in cfg_by_suffix.items():
                    if suffix.endswith("_fnc_" + base):
                        function_names.update(candidates)
            functions.update(function_names)
            if metadata is not None:
                for name in function_names:
                    metadata["sources"].setdefault(name, addon_path)
                    details = metadata.setdefault("functions", {}).setdefault(name, {})
                    details.setdefault("name", name)
                    details.setdefault("source", addon_path)
                    details.setdefault("confidence", "medium")
                    text = raw.decode("utf-8", errors="replace")
                    comments = []
                    for line in text.splitlines()[:8]:
                        stripped = line.strip()
                        if stripped.startswith("//"):
                            comments.append(stripped[2:].strip())
                        elif stripped and not stripped.startswith("/*"):
                            break
                    if comments and "description" not in details:
                        details["description"] = " ".join(comments)
                        details["provenance"] = "source comment"
            types = _extract_params_types(raw.decode("utf-8", errors="replace"))
            if types and any(types):
                for name in function_names:
                    signatures[name] = types
    return functions, signatures


def _mod_data_fingerprint(mod_dir: str) -> list[list[str | int]]:
    """Fast metadata fingerprint for addon files (no PBO contents are read)."""
    root = os.path.abspath(mod_dir)
    result: list[list[str | int]] = []
    for kind, path in list_addons(root):
        files: list[str] = []
        if kind == "pbo":
            files = [path]
        else:
            for current, _dirs, names in os.walk(path):
                for name in names:
                    lower = name.lower()
                    if lower.endswith((".sqf", ".hpp")) or lower == "config.cpp":
                        files.append(os.path.join(current, name))
        for filename in files:
            try:
                stat = os.stat(filename)
            except OSError:
                continue
            result.append([
                os.path.relpath(filename, root).replace("\\", "/").lower(),
                stat.st_size,
                stat.st_mtime_ns,
            ])
    result.sort(key=lambda row: row[0])
    return result


def load_mod_scan_cache(path: str) -> dict:
    """Load cached per-root scan results and their file fingerprints."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict) or data.get("version") != MOD_SCAN_CACHE_VERSION:
        return {}
    roots = data.get("roots")
    return roots if isinstance(roots, dict) else {}


def save_mod_scan_cache(path: str, roots: dict) -> None:
    """Persist scan results for roots whose files are unchanged on later runs."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"version": MOD_SCAN_CACHE_VERSION, "roots": roots}, fh, sort_keys=True)


def extract_mod_data_cached(
    mod_dir: str,
    cache: dict,
    progress=None,
    addon_names: set[str] | None = None,
    stats: dict[str, int] | None = None,
) -> tuple[set[str], dict[str, list[str | None]]]:
    """Reuse a root's prior extraction when its file metadata is unchanged."""
    key = os.path.normcase(os.path.abspath(mod_dir))
    fingerprint = _mod_data_fingerprint(mod_dir)
    entry = cache.get(key)
    addons = list_addons(mod_dir)
    if isinstance(entry, dict) and entry.get("fingerprint") == fingerprint:
        if stats is not None:
            stats["reused"] = stats.get("reused", 0) + 1
        if addon_names is not None and isinstance(entry.get("addon_names"), list):
            addon_names.update(x for x in entry["addon_names"] if isinstance(x, str))
        if progress:
            for _kind, path in addons:
                progress(path, False)
                progress(path, True)
        names = entry.get("functions", [])
        signatures = entry.get("signatures", {})
        return (
            {x for x in names if isinstance(x, str)} if isinstance(names, list) else set(),
            signatures if isinstance(signatures, dict) else {},
        )

    extracted_addon_names: set[str] = set()
    if stats is not None:
        stats["rescanned"] = stats.get("rescanned", 0) + 1
    metadata: dict = {}
    functions, signatures = extract_mod_data(mod_dir, progress, extracted_addon_names, metadata)
    if addon_names is not None:
        addon_names.update(extracted_addon_names)
    cache[key] = {
        "fingerprint": fingerprint,
        "functions": sorted(functions),
        "signatures": signatures,
        "addon_names": sorted(extracted_addon_names),
        "source_root": os.path.abspath(mod_dir),
        "metadata": metadata,
    }
    return functions, signatures


def load_mod_cache(path: str) -> set[str]:
    """Load a mod function cache (a JSON array) into a set.

    Returns an empty set when the file is missing or invalid.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(data, list):
        return set()
    return {item for item in data if isinstance(item, str) and item}


def save_mod_cache(path: str, functions: set[str]) -> None:
    """Write ``functions`` to ``path`` as a sorted JSON array."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(sorted(functions), fh)


def load_mod_type_cache(path: str) -> dict[str, list[str | None]]:
    """Load the optional mod function signature cache."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    result: dict[str, list[str | None]] = {}
    for name, types in data.items():
        if isinstance(name, str) and isinstance(types, list) and all(x is None or isinstance(x, str) for x in types):
            result[name.lower()] = types
    return result


def save_mod_type_cache(path: str, signatures: dict[str, list[str | None]]) -> None:
    """Write mod-extracted function types in stable JSON form."""
    normalized = {name.lower(): types for name, types in sorted(signatures.items())}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(normalized, fh, sort_keys=True)


def save_mod_metadata_cache(path: str, metadata: dict) -> None:
    """Write versioned extraction provenance and scan diagnostics."""
    payload = {"schema": 1, **metadata}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, sort_keys=True)


def load_mod_metadata_cache(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) and data.get("schema") == 1 else {}


if __name__ == "__main__":
    import struct
    import tempfile

    from .rapified import ConfigClass, rapify

    _ENTRY = struct.Struct("<5I")

    def _pbo_entry(name: bytes, method: int, orig: int, size: int) -> bytes:
        return name + b"\x00" + _ENTRY.pack(method, orig, 0, 0, size)

    def _write_pbo(path: str, files: dict[str, bytes]) -> None:
        header = bytearray()
        for name, data in files.items():
            header += _pbo_entry(name.encode("ascii"), 0, len(data), len(data))
        header += _pbo_entry(b"", 0, 0, 0)  # terminator entry
        with open(path, "wb") as fh:
            fh.write(bytes(header) + b"".join(files.values()))

    with tempfile.TemporaryDirectory() as tmp:
        # Automatic install discovery follows Steam's libraryfolders.vdf onto
        # secondary drives and verifies an Addons folder exists.
        steam_root = os.path.join(tmp, "steam")
        primary_game = os.path.join(steam_root, "steamapps", "common", "Arma 3")
        secondary_library = os.path.join(tmp, "Library Two")
        secondary_game = os.path.join(secondary_library, "steamapps", "common", "Arma 3")
        os.makedirs(os.path.join(primary_game, "Addons"))
        os.makedirs(os.path.join(secondary_game, "Addons"))
        with open(os.path.join(steam_root, "steamapps", "libraryfolders.vdf"), "w", encoding="utf-8") as fh:
            escaped_library = secondary_library.replace("\\", "\\\\")
            fh.write(f'"libraryfolders" {{ "1" {{ "path" "{escaped_library}" }} }}')
        discovered = set(discover_arma_install_dirs([steam_root]))
        assert primary_game in discovered and secondary_game in discovered, discovered

        # --- Resolution ---
        workshop_root = os.path.join(tmp, "workshop", "107410")
        workshop_mod_addons = os.path.join(workshop_root, "123", "addons")
        os.makedirs(workshop_mod_addons)
        with open(os.path.join(workshop_mod_addons, "ace_main.pbo"), "wb") as fh:
            fh.write(b"")  # empty file is enough for discovery

        arma = os.path.join(tmp, "arma")
        ace_addons = os.path.join(arma, "@ace", "addons")
        os.makedirs(ace_addons)
        with open(os.path.join(ace_addons, "ace_medical.pbo"), "wb") as fh:
            fh.write(b"")

        assert resolve_workshop_mod("123", [workshop_root]) == os.path.join(workshop_root, "123")
        assert resolve_workshop_mod("999", [workshop_root]) is None
        assert find_addon_mod("ace_medical", [arma]) == os.path.join(arma, "@ace")
        assert find_addon_mod("does_not_exist", [arma]) is None

        # --- Packed round-trip: PBO -> config.bin -> CfgFunctions ---
        cfg = ConfigClass(
            name="",
            children=[
                ConfigClass(
                    name="CfgFunctions",
                    children=[
                        ConfigClass(
                            name="ace_medical",
                            children=[
                                ConfigClass(
                                    name="medical",
                                    children=[
                                        ConfigClass(name="setUnconscious", properties={"file": "a.sqf"}),
                                        ConfigClass(name="setDamage", properties={"file": "b.sqf"}),
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )
        bin_data = rapify(cfg)

        packed_mod = os.path.join(tmp, "packedmod")
        packed_addons = os.path.join(packed_mod, "addons")
        os.makedirs(packed_addons)
        _write_pbo(os.path.join(packed_addons, "ace_medical.pbo"), {"config.bin": bin_data})
        assert extract_mod_functions(packed_mod) == {
            "ace_medical_fnc_setunconscious",
            "ace_medical_fnc_setdamage",
        }, extract_mod_functions(packed_mod)

        # --- Unpacked extraction ---
        unpacked_mod = os.path.join(tmp, "unpackedmod")
        hearing = os.path.join(unpacked_mod, "addons", "ace_hearing")
        os.makedirs(hearing)
        with open(os.path.join(hearing, "config.cpp"), "w", encoding="utf-8") as fh:
            fh.write(
                "class CfgFunctions { class ace_hearing { class hearing { "
                'class putInEarplugs { file = "..."; }; }; }; };'
            )
        assert extract_mod_functions(unpacked_mod) == {
            "ace_hearing_fnc_putinearplugs"
        }, extract_mod_functions(unpacked_mod)

        # --- PREP + HATG extraction: packed addon with functions/fnc_*.sqf ---
        prep_mod = os.path.join(tmp, "prepmod")
        prep_addons = os.path.join(prep_mod, "addons")
        os.makedirs(prep_addons)
        _write_pbo(
            os.path.join(prep_addons, "ace_medical.pbo"),
            {
                "functions/fnc_setUnconscious.sqf": b"private _x;\n",
                "functions\\fnc_putInEarplugs.sqf": b"// backslash separator\n",
                "functions/readme.txt": b"not a function\n",
                # fn_*.sqf is a HATG function; without a PREFIX it falls back to
                # the addon basename ("ace_medical").
                "functions/fn_hatgNotAPrep.sqf": b"HATG convention function\n",
            },
        )
        assert extract_mod_functions(prep_mod) == {
            "ace_medical_fnc_setunconscious",
            "ace_medical_fnc_putinearplugs",
            "ace_medical_fnc_hatgnotaprep",
        }, extract_mod_functions(prep_mod)

        # --- PREP + HATG extraction: root-level fnc_*.sqf (CBA) + fn_*.sqf ---
        cba_prep_mod = os.path.join(tmp, "cbaprepmod")
        cba_prep_addons = os.path.join(cba_prep_mod, "addons")
        os.makedirs(cba_prep_addons)
        _write_pbo(
            os.path.join(cba_prep_addons, "cba_settings.pbo"),
            {
                "fnc_set.sqf": b"// root-level PREP\n",
                "fnc_get.sqf": b"// another root-level PREP\n",
                "fn_init.sqf": b"// HATG convention function\n",
            },
        )
        assert extract_mod_functions(cba_prep_mod) == {
            "cba_settings_fnc_set",
            "cba_settings_fnc_get",
            "cba_settings_fnc_init",
        }, extract_mod_functions(cba_prep_mod)

        # --- PREP + HATG extraction: unpacked addon dir ---
        prep_unpacked_mod = os.path.join(tmp, "prepunpackedmod")
        prep_hearing = os.path.join(prep_unpacked_mod, "addons", "ace_hearing")
        prep_hearing_functions = os.path.join(prep_hearing, "functions")
        os.makedirs(prep_hearing_functions)
        with open(os.path.join(prep_hearing, "config.cpp"), "w", encoding="utf-8") as fh:
            fh.write("class CfgPatches { class ace_hearing { units[] = {}; }; };\n")
        with open(
            os.path.join(prep_hearing_functions, "fnc_putInEarplugs.sqf"),
            "w",
            encoding="utf-8",
        ) as fh:
            fh.write("// putInEarplugs\n")
        # Root-level fnc_*.sqf (CBA convention) is also PREP; fn_*.sqf is a HATG
        # function (falling back to the addon basename when no PREFIX is found).
        with open(os.path.join(prep_hearing, "fnc_set.sqf"), "w", encoding="utf-8") as fh:
            fh.write("// root-level PREP\n")
        with open(os.path.join(prep_hearing, "fn_init.sqf"), "w", encoding="utf-8") as fh:
            fh.write("// HATG convention function\n")
        assert extract_mod_functions(prep_unpacked_mod) == {
            "ace_hearing_fnc_putinearplugs",
            "ace_hearing_fnc_set",
            "ace_hearing_fnc_init",
        }, extract_mod_functions(prep_unpacked_mod)

        # Explicit params/param validators in unpacked mod functions expose useful
        # argument types; a default alone is deliberately not treated as a contract.
        typed_mod = os.path.join(tmp, "typedmod")
        typed_addon = os.path.join(typed_mod, "addons", "acme")
        typed_functions = os.path.join(typed_addon, "functions")
        os.makedirs(typed_functions)
        with open(os.path.join(typed_addon, "config.cpp"), "w", encoding="utf-8") as fh:
            fh.write('class CfgFunctions { class acme { class api { class route { file = "\\acme\\fn_route.sqf"; }; }; }; };')
        with open(os.path.join(typed_functions, "fn_route.sqf"), "w", encoding="utf-8") as fh:
            fh.write('params [["_target", objNull, [objNull]], ["_wait", 0, [0]], "_anything"]; _this param [3, "", [""]];')
        assert extract_mod_function_signatures(typed_mod) == {
            "acme_fnc_route": ["Object", "Number", None, "String"]
        }, extract_mod_function_signatures(typed_mod)

        param_only = os.path.join(typed_functions, "fn_paramOnly.sqf")
        with open(param_only, "w", encoding="utf-8") as fh:
            fh.write('_this param [1, objNull, [objNull]];')
        # The file must be declared to CfgFunctions to be attributed.
        with open(os.path.join(typed_addon, "config.cpp"), "w", encoding="utf-8") as fh:
            fh.write('class CfgFunctions { class acme { class api { class route { file = "\\acme\\fn_route.sqf"; }; class paramOnly { file = "\\acme\\fn_paramOnly.sqf"; }; }; }; };')
        assert extract_mod_function_signatures(typed_mod)["acme_fnc_paramonly"] == [None, "Object"]

        # --- HATG extraction: script_mod.hpp #define PREFIX + fn_*.sqf ---
        hatg_mod = os.path.join(tmp, "hatgmod")
        hatg_addons = os.path.join(hatg_mod, "addons")
        os.makedirs(hatg_addons)
        _write_pbo(
            os.path.join(hatg_addons, "hatg_gui.pbo"),
            {
                "script_mod.hpp": b"#define PREFIX hatg\n",
                "functions/display/fn_getDisplay.sqf": b"// getDisplay\n",
                "functions/display/fnc_extra.sqf": b"// a CBA-style PREP file\n",
            },
        )
        assert extract_mod_functions(hatg_mod) == {
            "hatg_fnc_getdisplay",       # fn_*.sqf tagged with the PREFIX
            "hatg_gui_fnc_extra",        # fnc_*.sqf tagged with the addon name
        }, extract_mod_functions(hatg_mod)

        # --- HATG extraction: PREFIX defined in a sibling addon's script_mod.hpp ---
        # Mirrors the real HATG layout where core.pbo holds "#define PREFIX hatg"
        # while gui.pbo's fn_*.sqf files reference it via an #include.
        hatg_split_mod = os.path.join(tmp, "hatgsplitmod")
        hatg_split_addons = os.path.join(hatg_split_mod, "addons")
        os.makedirs(hatg_split_addons)
        _write_pbo(
            os.path.join(hatg_split_addons, "core.pbo"),
            {"script_mod.hpp": b"#define PREFIX hatg\n"},
        )
        _write_pbo(
            os.path.join(hatg_split_addons, "gui.pbo"),
            {
                "script_component.hpp": b'#include "\\z\\hatg\\addons\\core\\script_mod.hpp"\n',
                "functions/display/fn_getDisplay.sqf": b"// getDisplay\n",
            },
        )
        assert extract_mod_functions(hatg_split_mod) == {
            "hatg_fnc_getdisplay",
        }, extract_mod_functions(hatg_split_mod)

        # --- Cache ---
        cache_path = os.path.join(tmp, "cache.json")
        fns = {
            "ace_medical_fnc_setunconscious",
            "ace_medical_fnc_setdamage",
            "ace_hearing_fnc_putinearplugs",
        }
        save_mod_cache(cache_path, fns)
        assert load_mod_cache(cache_path) == fns
        type_cache_path = os.path.join(tmp, MOD_TYPE_CACHE_FILENAME)
        type_signatures = {"ace_medical_fnc_setunconscious": ["Object", "Number|Boolean", None]}
        save_mod_type_cache(type_cache_path, type_signatures)
        assert load_mod_type_cache(type_cache_path) == type_signatures

        # Missing / invalid caches yield an empty set.
        assert load_mod_cache(os.path.join(tmp, "nope.json")) == set()
        with open(os.path.join(tmp, "bad.json"), "w", encoding="utf-8") as fh:
            fh.write("{not json")
        assert load_mod_cache(os.path.join(tmp, "bad.json")) == set()

        # discover_workshop_roots is best-effort: it never raises and returns a
        # list (which may be empty on machines without Steam).
        roots = discover_workshop_roots()
        assert isinstance(roots, list)
        for r in roots:
            assert os.path.isdir(r)

    print("mods self-test passed")
