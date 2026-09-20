"""Build Armalint function and type caches from locally-installed content.

This module orchestrates the existing building blocks to produce a cache of the
exact ``CfgFunctions`` names provided by a mission's mods:

  * ``armalint.sqm.extract_addons``      — a mission's required addons
    (``mission.sqm`` ``addOns[]``).
  * ``armalint.config``                  — optional mods (by Workshop URL) from
    ``armalint.json``.
  * ``armalint.mods``                    — scan installed mod folders and
    base/DLC ``Addons`` folders for function names and explicit ``params``
    type validators.

This reads *installed* mods only — it never downloads anything (no steamcmd).
The CLI is driven via :func:`main` (importable for tests); running the module
directly (``python -m armalint.update``) runs the real CLI. The built-in
self-test is still available via ``python -m armalint.update --self-test``::

    from armalint.update import main     # main(["--mission", ...]) -> int

Only the standard library is used.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import subprocess
import urllib.request
import urllib.error
import zipfile
import threading
import time

from .config import extract_mods, extract_dependency_specs, find_config, load_config_file, project_state_dir
from .mods import (
    discover_workshop_roots,
    discover_steamcmd,
    discover_game_addon_roots,
    discover_arma_install_dirs,
    find_game_addon,
    extract_mod_data_cached,
    extract_mod_macros,
    extract_source_macros,
    load_mod_scan_cache,
    save_mod_scan_cache,
    list_addons,
    find_addon_mod,
    resolve_workshop_mod,
    save_mod_cache,
    save_mod_type_cache,
    save_mod_macro_cache,
    load_mod_type_cache,
    MOD_TYPE_CACHE_FILENAME,
    MOD_MACRO_CACHE_FILENAME,
    MOD_SCAN_CACHE_FILENAME,
    MOD_METADATA_CACHE_FILENAME,
    save_mod_metadata_cache,
    expand_core_function_aliases,
)
from .sqm import extract_addons

#: Cache filename used when ``--out`` is not supplied.
_DEFAULT_CACHE_NAME = "armalint_mods.json"


def _warn(message: str) -> None:
    """Print a one-line warning to stderr."""
    print(f"warning: {message}", file=sys.stderr)


def _download_workshop_item(steamcmd: str, workshop_id: str, install_dir: str, name: str | None = None, steam_user: str | None = None, steam_password: str | None = None, steam_guard: str | None = None) -> bool:
    os.makedirs(install_dir, exist_ok=True)
    stream = sys.stderr if sys.stderr.isatty() else None
    process = None
    stop = threading.Event()
    spinner = None
    output_thread = None
    try:
        login = steam_user or "anonymous"
        interactive_login = bool(steam_user and not steam_password)
        process = subprocess.Popen(
            [steamcmd, "+force_install_dir", install_dir, "+login", login,
             "+workshop_download_item", "107410", workshop_id, "+quit"],
            # Authentication prompts and Steam Guard challenges must remain
            # visible; anonymous downloads can stay quiet behind the spinner.
            stdin=subprocess.PIPE if steam_password else None,
            stdout=subprocess.PIPE if interactive_login else subprocess.DEVNULL,
            stderr=None if steam_user and not steam_password else subprocess.STDOUT,
            text=True if interactive_login else False,
            bufsize=1 if interactive_login else 0,
        )
        if interactive_login and process.stdout is not None:
            # SteamCMD prints its own numeric-only success line. Forward its
            # interactive output, but replace that line with our named result
            # below so logs identify which dependency was downloaded.
            def forward_output() -> None:
                for line in process.stdout:
                    if re.search(r"Success\. Downloaded item \d+ to", line):
                        continue
                    sys.stdout.write(line)
                    sys.stdout.flush()

            output_thread = threading.Thread(target=forward_output, daemon=True)
            output_thread.start()
        if stream and not steam_user:
            frames = "|/-\\"
            width = max(32, shutil.get_terminal_size((80, 24)).columns - 1)

            def show_progress() -> None:
                index = 0
                while not stop.wait(0.15):
                    label = name or workshop_id
                    message = f"SteamCMD preparing dependency {label} {frames[index % len(frames)]}"
                    stream.write("\r" + message[:width].ljust(width))
                    stream.flush()
                    index += 1

            spinner = threading.Thread(target=show_progress, daemon=True)
            spinner.start()
        if steam_password:
            credentials = steam_password + "\n"
            if steam_guard:
                credentials += steam_guard + "\n"
            _output, _ = process.communicate(credentials)
            returncode = process.returncode
        else:
            returncode = process.wait()
        if output_thread:
            output_thread.join(timeout=1)
    except OSError as exc:
        _warn(f"could not run SteamCMD for Workshop item {workshop_id}: {exc}")
        return False
    finally:
        stop.set()
        if spinner:
            spinner.join(timeout=1)
        if stream and not steam_user:
            width = max(32, shutil.get_terminal_size((80, 24)).columns - 1)
            stream.write("\r" + (" " * width) + "\r")
            stream.flush()
    if returncode != 0:
        _warn(f"SteamCMD failed to download Workshop item {workshop_id}")
        return False
    content_path = os.path.join(install_dir, "steamapps", "workshop", "content", "107410", workshop_id)
    if not os.path.isdir(content_path) or not any(os.scandir(content_path)):
        _warn(f"SteamCMD did not install Workshop dependency {name or workshop_id}; check its SteamCMD log (authenticated Arma 3 access may be required)")
        return False
    # SteamCMD's own success line only includes the numeric Workshop ID.
    # Echo a stable, human-readable mapping so logs remain useful when a
    # project downloads several dependencies in one run.
    label = f'{name} (Workshop ID {workshop_id})' if name else f'Workshop item {workshop_id}'
    print(f'Success. Downloaded dependency {label} to "{content_path}"')
    return True


def _download_steamcmd_archive(destination: str) -> None:
    """Download the SteamCMD archive with a single-line terminal progress display."""
    stream = sys.stderr if sys.stderr.isatty() else None
    response = urllib.request.urlopen(
        "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
    )
    total = int(response.headers.get("Content-Length") or 0)
    downloaded = 0
    width = max(32, shutil.get_terminal_size((80, 24)).columns - 1)
    with response, open(destination, "wb") as output:
        while True:
            chunk = response.read(1024 * 64)
            if not chunk:
                break
            output.write(chunk)
            downloaded += len(chunk)
            if stream:
                if total:
                    message = f"Downloading SteamCMD {downloaded * 100 // total:3d}%"
                else:
                    message = f"Downloading SteamCMD ({downloaded // 1024} KiB)"
                stream.write("\r" + message[:width].ljust(width))
                stream.flush()
    if stream:
        stream.write("\r" + (" " * width) + "\r")
        stream.flush()


def _acquire_dependency_source(spec: dict, source_root: str) -> str | None:
    """Clone a declared dependency source into the project cache."""
    source = spec.get("source")
    if isinstance(source, dict):
        url = source.get("url")
        ref = source.get("ref") or source.get("branch")
    else:
        url = source
        ref = spec.get("ref")
    if not isinstance(url, str) or not url.strip():
        return None
    destination = os.path.join(source_root, re.sub(r"[^A-Za-z0-9_.-]+", "_", str(spec.get("name", "dependency"))))
    if os.path.isdir(os.path.join(destination, ".git")):
        try:
            subprocess.run(["git", "-C", destination, "pull", "--ff-only"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return destination
        except OSError:
            return None
    os.makedirs(source_root, exist_ok=True)
    command = ["git", "clone", "--depth", "1"]
    if isinstance(ref, str) and ref:
        command.extend(["--branch", ref])
    command.extend([url.strip(), destination])
    try:
        result = subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return None
    return destination if result.returncode == 0 else None


def _ensure_steamcmd(project_state: str, detected: str | None) -> str | None:
    # A user-supplied --steamcmd path may be stale or mistyped.  Treat it the
    # same as an undiscovered executable so the interactive installer can
    # still offer a working local copy.
    if detected and os.path.isfile(detected):
        return detected
    if not sys.stdin.isatty():
        _warn("SteamCMD was not found; rerun interactively to download it into .armalint/bin")
        return None
    answer = input("SteamCMD is required to download dependencies. Download it from Valve now? [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        _warn("SteamCMD download declined; dependencies were not downloaded")
        return None
    bin_dir = os.path.join(project_state, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    archive = os.path.join(bin_dir, "steamcmd.zip")
    try:
        _download_steamcmd_archive(archive)
        with zipfile.ZipFile(archive) as package:
            package.extractall(bin_dir)
    except (OSError, urllib.error.URLError, zipfile.BadZipFile) as exc:
        _warn(f"could not download SteamCMD: {exc}")
        return None
    finally:
        try: os.remove(archive)
        except OSError: pass
    executable = os.path.join(bin_dir, "steamcmd.exe")
    if not os.path.isfile(executable):
        _warn("SteamCMD download completed but steamcmd.exe was not found")
        return None
    return executable


def _extract_with_progress(path: str, label: str, root_number: int, root_total: int,
                           completed: int, overall_total: int,
                           addon_names: set[str], scan_cache: dict,
                           cache_stats: dict[str, int] | None = None):
    """Scan a root and display aggregate addon progress on interactive terminals."""
    stream = (
        sys.stderr if sys.stderr.isatty()
        else sys.stdout if sys.stdout.isatty()
        else None
    )
    if stream is None:
        return extract_mod_data_cached(path, scan_cache, None, addon_names, cache_stats)

    stop = threading.Event()
    state = {"done": completed, "item": "starting"}
    frames = "|/-\\"
    width = max(20, shutil.get_terminal_size((100, 24)).columns - 1)

    def status() -> str:
        percent = 100 if overall_total == 0 else int(state["done"] * 100 / overall_total)
        message = (f"Scanning {percent:3d}% ({state['done']}/{overall_total}) "
                   f"[{root_number}/{root_total} {label}] {state['item']}")
        return message

    def progress(item: str, finished: bool) -> None:
        state["item"] = os.path.basename(item)
        if finished:
            state["done"] += 1
        else:
            # Draw synchronously before entering a potentially CPU-heavy PBO
            # parse.  The spinner thread may not get scheduled while a parser
            # holds the interpreter, but the user still sees what is active.
            draw(status())

    def draw(message: str, end: str = "") -> None:
        # Pad the entire line so shorter updates erase leftovers without ANSI
        # codes, which some PowerShell hosts display literally.
        print("\r" + message[:width].ljust(width), end=end, file=stream, flush=True)

    def spin() -> None:
        frame = 0
        while not stop.wait(0.12):
            draw(f"{status()} {frames[frame % len(frames)]}")
            frame += 1

    thread = threading.Thread(target=spin, daemon=True)
    draw(f"{status()} |")
    thread.start()
    try:
        return extract_mod_data_cached(path, scan_cache, progress, addon_names, cache_stats)
    finally:
        stop.set()
        thread.join()
        draw(
            f"{status()} done",
            end="\n" if root_number == root_total else "",
        )


def _is_mod_dir_name(name: str) -> bool:
    """True if ``name`` is a mod folder: a numeric Workshop id or a ``@`` mod.

    Steam Workshop content roots hold one numeric-id folder per subscribed mod;
    an Arma install directory holds one ``@``-prefixed folder per local mod.
    Everything else (``Dta``, ``Missions``, ``Addons``, …) is not a mod.
    """
    return name.startswith("@") or name.isdigit()


def _read_mission_sqm(mission_dir: str) -> tuple[str | None, list[str]]:
    """Read the root and nested SQMs and return ``(root, required_addons)``.

    The root file controls the usual missing-file warning. Nested SQMs are
    scanned only for addon declarations; they may be templates or map
    fragments and are not required to contain a complete ``class Mission``.
    """
    sqm_path = os.path.join(mission_dir, "mission.sqm")
    if not os.path.isfile(sqm_path):
        _warn(f"mission.sqm not found in {mission_dir}; no required addons")
        return None, []
    try:
        with open(sqm_path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        _warn(f"could not read {sqm_path}: {exc}; no required addons")
        return sqm_path, []
    addons: list[str] = []
    seen: set[str] = set()

    def add_from(source: str) -> None:
        for addon in extract_addons(source):
            key = addon.lower()
            if key not in seen:
                seen.add(key)
                addons.append(addon)

    add_from(text)
    # Nested mission files occur in addon/map templates.  They can carry
    # dependencies even when they are not standalone missions.
    for root, dirs, names in os.walk(mission_dir):
        dirs[:] = [name for name in dirs if name.lower() != ".armalint"]
        for name in names:
            if not name.lower().endswith(".sqm"):
                continue
            nested = os.path.join(root, name)
            if os.path.normcase(os.path.abspath(nested)) == os.path.normcase(os.path.abspath(sqm_path)):
                continue
            try:
                with open(nested, "r", encoding="utf-8", errors="replace") as fh:
                    add_from(fh.read())
            except OSError as exc:
                _warn(f"could not read nested mission file {nested}: {exc}")
    return sqm_path, addons


def run_update(args) -> int:
    """Resolve a mission's mods to installed folders and write the cache.

    ``args`` is an argparse-style namespace with ``mission``, ``config``,
    ``workshop`` (list), ``arma_dir`` (list), ``out``, and ``dry_run``. Returns
    0 on success (unresolved mods are warnings, not errors); 1 is reserved for
    fatal errors such as bad arguments (handled by ``argparse`` before this
    point).
    """
    mission_dir = os.path.abspath(getattr(args, "mission", None) or os.getcwd())

    # 1. Required addons from mission.sqm.
    _sqm_path, required_addons = _read_mission_sqm(mission_dir)

    # 2. Optional mods from armalint.json (explicit --config or discovery).
    config_path = getattr(args, "config", None) or find_config(mission_dir)
    optional_mods: list[dict] = []
    dependency_specs: list[dict[str, str]] = []
    if config_path:
        loaded_config = load_config_file(config_path)
        optional_mods = extract_mods(loaded_config)
        dependency_specs = extract_dependency_specs(loaded_config)

    if getattr(args, "out", None):
        out_path = os.path.abspath(args.out)
    elif config_path:
        out_path = os.path.join(project_state_dir(os.path.dirname(os.path.abspath(config_path))), _DEFAULT_CACHE_NAME)
    else:
        out_path = os.path.join(project_state_dir(mission_dir), _DEFAULT_CACHE_NAME)
    if not getattr(args, "dry_run", False):
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
    scan_cache_path = os.path.join(os.path.dirname(out_path), MOD_SCAN_CACHE_FILENAME)
    scan_cache = load_mod_scan_cache(scan_cache_path)

    # 3. Search roots: workshop content roots + Arma install directories.
    workshop_roots = list(getattr(args, "workshop", None) or discover_workshop_roots())
    source_macros: set[str] = set()
    source_dependency_roots: list[tuple[str, dict]] = []
    source_cache_root = os.path.join(os.path.dirname(out_path), "dependencies", "source")
    for spec in dependency_specs:
        source = spec.get("source")
        if not source:
            continue
        source_path = None
        if getattr(args, "download_dependencies", False):
            source_path = _acquire_dependency_source(spec, source_cache_root)
        else:
            candidate = os.path.join(source_cache_root, re.sub(r"[^A-Za-z0-9_.-]+", "_", str(spec.get("name", "dependency"))))
            if os.path.isdir(candidate):
                source_path = candidate
        if source_path:
            source_dependency_roots.append((source_path, spec))
            source_info = source if isinstance(source, dict) else spec
            roots = source_info.get("includeRoots", source_info.get("include_roots", [])) if isinstance(source_info, dict) else []
            if isinstance(roots, str):
                roots = [roots]
            source_macros |= extract_source_macros(source_path, roots if isinstance(roots, list) else [])
        elif getattr(args, "download_dependencies", False):
            _warn(f"could not acquire source dependency {spec.get('name', '<unnamed>')}")
    if getattr(args, "download_dependencies", False):
        steamcmd = getattr(args, "steamcmd", None) or discover_steamcmd(
            [mission_dir]
        )
        steamcmd = _ensure_steamcmd(os.path.dirname(out_path), steamcmd)
        steam_user = getattr(args, "steamcmd_user", None)
        steam_user = steam_user or os.environ.get("STEAMCMD_USER")
        steam_password = os.environ.get("STEAMCMD_PASSWORD")
        steam_guard = os.environ.get("STEAMCMD_GUARD_CODE")
        if steam_password and not steam_user:
            _warn("STEAMCMD_PASSWORD is set but STEAMCMD_USER is missing; ignoring the password")
            steam_password = None
        if steamcmd and not steam_user and sys.stdin.isatty() and sys.stdout.isatty():
            answer = input("Use an authenticated Steam account for Workshop downloads? [y/N] ").strip().lower()
            if answer in ("y", "yes"):
                steam_user = input("Steam username: ").strip() or None
        dependency_cache = os.path.join(os.path.dirname(out_path), "dependencies")
        specs_to_download = list(dependency_specs)
        cba_specs = [spec for spec in specs_to_download if spec.get("name", "").startswith("cba_")]
        if cba_specs:
            # CBA_MAIN, CBA_EVENTS, CBA_XEH, etc. are addon components from
            # one CBA Workshop item; they must not be downloaded separately.
            specs_to_download = [spec for spec in specs_to_download if not spec.get("name", "").startswith("cba_")]
            cba_id = next((spec.get("workshopId") or spec.get("workshop_id") for spec in cba_specs), None)
            if cba_id:
                specs_to_download.append({"name": "cba_main", "workshopId": cba_id})
            else:
                _warn("CBA is declared but has no Workshop ID; skipping download")
        if not getattr(args, "force_download_dependencies", False):
            specs_to_download = [
                spec for spec in specs_to_download
                if not (spec.get("workshopId") or spec.get("workshop_id"))
                or not resolve_workshop_mod(
                    spec.get("workshopId") or spec.get("workshop_id"), workshop_roots
                )
            ]
        for spec in specs_to_download:
            workshop_id = spec.get("workshopId") or spec.get("workshop_id")
            if not workshop_id:
                _warn(f"dependency {spec['name']} has no Workshop ID; skipping download")
            elif steamcmd and _download_workshop_item(steamcmd, workshop_id, dependency_cache, spec.get("name"), steam_user, steam_password, steam_guard):
                workshop_roots.append(os.path.join(dependency_cache, "steamapps", "workshop", "content", "107410"))
            elif not steamcmd:
                _warn("--download-dependencies requested but SteamCMD was not found")
    configured_arma_dirs = list(getattr(args, "arma_dir", None) or [])
    arma_dirs = configured_arma_dirs or discover_arma_install_dirs()
    all_search_roots = workshop_roots + arma_dirs
    game_addon_roots = sorted({
        root for game_dir in arma_dirs for root in discover_game_addon_roots(game_dir)
    }, key=os.path.normcase)

    # 4. Resolve mod folders (deduplicated by path).
    resolved: dict[str, dict] = {}

    def register(path: str, name, workshop_id, reason: str) -> None:
        info = resolved.get(path)
        if info is None:
            resolved[path] = {
                "path": path,
                "name": name,
                "workshop_id": workshop_id,
                "reasons": [reason],
            }
            return
        info["reasons"].append(reason)
        if info["name"] is None and name is not None:
            info["name"] = name
        if info["workshop_id"] is None and workshop_id is not None:
            info["workshop_id"] = workshop_id

    for mod in optional_mods:
        wid = mod["workshop_id"]
        if not wid:
            _warn(f"optional mod has no workshop id (skipped): {mod['url']}")
            continue
        path = resolve_workshop_mod(wid, workshop_roots)
        if path:
            register(path, mod["name"], wid, f"workshop mod {wid}")
        else:
            label = f" ({mod['name']})" if mod["name"] else ""
            _warn(f"could not resolve workshop mod {wid}{label}")

    # Dependency declarations are also scan inputs.  Downloading a Workshop
    # item or cloning its source without registering the resulting root leaves
    # its functions invisible to the linter (and produces misleading W201
    # diagnostics in the consuming project).
    for spec in dependency_specs:
        name = spec.get("name")
        wid = spec.get("workshopId") or spec.get("workshop_id")
        if wid:
            path = resolve_workshop_mod(wid, workshop_roots)
            if path:
                register(path, name, wid, f"dependency {name or wid}")
        # Source roots are handled independently so a source-only dependency
        # remains useful even when no Workshop download is available.
    for path, spec in source_dependency_roots:
        if list_addons(path):
            register(path, spec.get("name"), spec.get("workshopId") or spec.get("workshop_id"), f"dependency source {spec.get('name') or path}")

    unresolved_required: list[str] = []
    resolved_required: set[str] = set()
    for addon in required_addons:
        path = find_addon_mod(addon, all_search_roots, name_filter=_is_mod_dir_name)
        if path:
            resolved_required.add(addon.lower())
            register(path, None, None, f"required addon {addon}")
        elif find_game_addon(addon, game_addon_roots):
            # Base-game and DLC Addons are scanned below as a group; they are
            # valid required addons even though they aren't @mod folders.
            resolved_required.add(addon.lower())
            continue
        else:
            # Game addon patch names are declared inside config.bin and do not
            # necessarily match the PBO filename. Check them after the scan.
            unresolved_required.append(addon)

    # 5. Extract the exact CfgFunctions names from every resolved mod folder.
    functions: set[str] = set()
    function_types: dict[str, list[str | None]] = {}
    macros: set[str] = set()
    macros |= source_macros
    scan_roots = [
        (path, "mod") for path in sorted(resolved, key=lambda p: os.path.normcase(p))
    ] + [(root, "game data") for root in game_addon_roots]
    overall_total = sum(len(list_addons(path)) for path, _label in scan_roots)
    completed_addons = 0
    installed_addon_names: set[str] = set()
    cache_stats = {"reused": 0, "rescanned": 0}
    for current, (path, label) in enumerate(scan_roots, start=1):
        names, types_by_name = _extract_with_progress(
            path, label, current, len(scan_roots), completed_addons, overall_total,
            installed_addon_names, scan_cache,
            cache_stats,
        )
        completed_addons += len(list_addons(path))
        functions |= names
        macros |= extract_mod_macros(path)
        for name, types in types_by_name.items():
            function_types.setdefault(name, types)
    for addon in unresolved_required:
        if addon.lower() not in resolved_required and addon.lower() not in installed_addon_names:
            _warn(f"could not resolve required addon {addon}")

    # Preserve public compatibility names such as TFAR_fnc_* alongside their
    # component-qualified CfgFunctions implementations.
    functions = expand_core_function_aliases(functions)
    for name, types in list(function_types.items()):
        match = re.match(r"^([a-z0-9]+)_core_fnc_(.+)$", name.lower())
        if match:
            function_types.setdefault(f"{match.group(1)}_fnc_{match.group(2)}", types)

    arma_version = getattr(args, "arma_version", None) or os.environ.get("ARMALINT_ARMA_VERSION")
    metadata_path = os.path.join(os.path.dirname(out_path), MOD_METADATA_CACHE_FILENAME)
    metadata = {
        "arma_version": arma_version,
        "roots": {
            root: entry.get("metadata", {})
            for root, entry in scan_cache.items()
            if isinstance(entry, dict) and isinstance(entry.get("metadata"), dict)
        },
        "signature_sources": {
            name: entry.get("metadata", {}).get("sources", {}).get(name)
            for entry in scan_cache.values() if isinstance(entry, dict)
            for name in entry.get("functions", []) if isinstance(name, str)
            and entry.get("metadata", {}).get("sources", {}).get(name)
        },
        "functions": {
            name: details
            for entry in scan_cache.values() if isinstance(entry, dict)
            for name, details in entry.get("metadata", {}).get("functions", {}).items()
            if isinstance(name, str) and isinstance(details, dict)
        },
        "scan_errors": [error for entry in scan_cache.values() if isinstance(entry, dict)
                        for error in entry.get("metadata", {}).get("errors", [])],
    }

    # 6. Save result caches unless this was a dry run.
    dry_run = bool(getattr(args, "dry_run", False))
    if not dry_run:
        save_mod_cache(out_path, functions)
        type_cache_path = os.path.join(os.path.dirname(out_path), MOD_TYPE_CACHE_FILENAME)
        save_mod_type_cache(type_cache_path, function_types)
        save_mod_macro_cache(os.path.join(os.path.dirname(out_path), MOD_MACRO_CACHE_FILENAME), macros)
        save_mod_scan_cache(scan_cache_path, scan_cache)
        save_mod_metadata_cache(metadata_path, metadata)

    # 7. Human-readable summary.
    print("armalint mod cache update")
    print(f"  mission   : {mission_dir}")
    print(f"  config    : {config_path or '(none)'}")
    print(f"  resolved  : {len(resolved)} mod folder(s)")
    print(f"  arma roots: {len(arma_dirs)} ({'explicit' if configured_arma_dirs else 'auto-detected'})")
    for root in arma_dirs:
        print(f"      - {root}")
    print(f"  game data : {len(game_addon_roots)} base/DLC Addons folder(s)")
    for info in sorted(resolved.values(), key=lambda i: os.path.normcase(i["path"])):
        parts: list[str] = []
        if info["name"]:
            parts.append(str(info["name"]))
        if info["workshop_id"]:
            parts.append(f"id={info['workshop_id']}")
        label = " ".join(parts) if parts else info["reasons"][0]
        print(f"      - {label}: {info['path']}")
    print(f"  functions : {len(functions)} exact function name(s)")
    print(f"  signatures: {len(function_types)} function type signature(s)")
    print(f"  scan work : {cache_stats['reused']} reused, {cache_stats['rescanned']} rescanned root(s)")
    print(f"  scan cache: {scan_cache_path}")
    if dry_run:
        print(f"  cache     : {out_path} + {MOD_TYPE_CACHE_FILENAME} (dry run, not written)")
    else:
        print(f"  cache     : {out_path} + {type_cache_path} + {metadata_path}")
    if metadata["scan_errors"]:
        print(f"  scan notes: {len(metadata['scan_errors'])} unreadable/unsupported item(s)")

    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m armalint.update",
        description="Build Armalint function/type caches from installed mods and game data.",
    )
    parser.add_argument(
        "--mission",
        metavar="DIR",
        default=None,
        help="directory containing mission.sqm (default: current directory)",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="armalint.json with optional mods (default: auto-discovered)",
    )
    parser.add_argument(
        "--workshop",
        metavar="PATH",
        action="append",
        default=[],
        help="Steam Workshop content root (.../workshop/content/107410); repeatable",
    )
    parser.add_argument(
        "--arma-dir",
        metavar="PATH",
        action="append",
        default=[],
        help="Arma install directory (default: discover Steam installs); scans base/DLC Addons and @* mod folders; repeatable",
    )
    parser.add_argument(
        "--out",
        metavar="PATH",
        default=None,
        help="cache output path (default: <config-or-mission-dir>/armalint_mods.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="compute and report but do not write the cache",
    )
    parser.add_argument("--download-dependencies", action="store_true",
                        help="download declared Workshop dependencies with SteamCMD")
    parser.add_argument("--force-download-dependencies", action="store_true",
                        help="refresh declared Workshop dependencies even when already installed")
    parser.add_argument("--steamcmd", metavar="PATH", default=None,
                        help="SteamCMD executable for --download-dependencies")
    parser.add_argument("--steamcmd-user", metavar="NAME", default=None,
                        help="authenticated Steam username for dependency downloads (password and Steam Guard remain interactive)")
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="remove the incremental scan cache for this mission and exit",
    )
    parser.add_argument(
        "--arma-version", metavar="VERSION", default=None,
        help="record the Arma version in extraction metadata (or use ARMALINT_ARMA_VERSION)",
    )
    return parser


def _run_self_test() -> int:
    """Run the update self-test (exercises the full pipeline on a temp tree)."""
    # ---------------------------------------------------------------------
    # Self-test. Builds a fake mission / Workshop / Arma tree with real
    # rapified CfgFunctions inside hand-written uncompressed PBOs, runs the
    # full update pipeline, and asserts the cache contents.
    # ---------------------------------------------------------------------
    import struct
    import tempfile
    import contextlib
    import io

    from .mods import find_game_addon, load_mod_cache
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

    def _cfg_functions(tag: str, function: str) -> bytes:
        cfg = ConfigClass(
            name="",
            children=[
                ConfigClass(
                    name="CfgFunctions",
                    children=[
                        ConfigClass(
                            name=tag,
                            children=[
                                ConfigClass(
                                    name="category",
                                    children=[
                                        ConfigClass(
                                            name=function,
                                            properties={"file": "x.sqf"},
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )
        return rapify(cfg)

    def _cfg_patch(name: str) -> bytes:
        return rapify(ConfigClass(
            name="",
            children=[ConfigClass(
                name="CfgPatches",
                children=[ConfigClass(name=name, properties={"units": []})],
            )],
        ))

    with tempfile.TemporaryDirectory() as tmp:
        mission_dir = os.path.join(tmp, "mission")
        os.makedirs(mission_dir)
        with open(os.path.join(mission_dir, "mission.sqm"), "w", encoding="utf-8") as fh:
            fh.write(
                'version=54;\nclass Mission\n{\n'
                '    addOns[]=\n    {\n        "ace_main",\n        "ace_medical",\n'
                '        "A3_Characters_F",\n        "A3_Air_F_Heli_Light_01"\n    };\n'
                "};\n"
            )
        nested_sqm_dir = os.path.join(mission_dir, "templates")
        os.makedirs(nested_sqm_dir)
        with open(os.path.join(nested_sqm_dir, "template.sqm"), "w", encoding="utf-8") as fh:
            fh.write('addOns[] = {"nested_template_dependency"};\n')
        _root_sqm, discovered_addons = _read_mission_sqm(mission_dir)
        assert "nested_template_dependency" in discovered_addons
        config_path = os.path.join(mission_dir, "armalint.json")
        with open(config_path, "w", encoding="utf-8") as fh:
            fh.write(
                '{"mods":[{"name":"ACE3",'
                '"url":"https://steamcommunity.com/sharedfiles/filedetails/?id=123"}]}'
            )

        workshop_root = os.path.join(tmp, "ws", "107410")
        workshop_mod_addons = os.path.join(workshop_root, "123", "addons")
        os.makedirs(workshop_mod_addons)
        _write_pbo(
            os.path.join(workshop_mod_addons, "ace_main.pbo"),
            {"config.bin": _cfg_functions("ace_main", "initialize")},
        )

        arma_dir = os.path.join(tmp, "arma")
        ace_addons = os.path.join(arma_dir, "@ace", "addons")
        os.makedirs(ace_addons)
        _write_pbo(
            os.path.join(ace_addons, "ace_medical.pbo"),
            {
                "config.bin": _cfg_functions("ace_medical", "setUnconscious"),
                "functions/fnc_setUnconscious.sqf": b'params [["_unit", objNull, [objNull]], ["_duration", 0, [0]]];',
            },
        )
        base_addons = os.path.join(arma_dir, "Addons")
        os.makedirs(base_addons)
        _write_pbo(
            os.path.join(base_addons, "a3_functions.pbo"),
            {"functions/fnc_baseOnly.sqf": b'params [["_thing", objNull, [objNull]]];'},
        )
        _write_pbo(os.path.join(base_addons, "characters_f.pbo"),
                   {"config.bin": _cfg_patch("A3_Characters_F")})
        dlc_addons = os.path.join(arma_dir, "Expansion", "Addons")
        os.makedirs(dlc_addons)
        _write_pbo(
            os.path.join(dlc_addons, "dlc_functions.pbo"),
            {"functions/fnc_dlcOnly.sqf": b'params [["_name", "", [""]]];'},
        )
        _write_pbo(os.path.join(dlc_addons, "air_f_heli.pbo"),
                   {"config.bin": _cfg_patch("A3_Air_F_Heli_Light_01")})
        unselected_workshop_addons = os.path.join(
            arma_dir, "!Workshop", "@unselected", "Addons"
        )
        os.makedirs(unselected_workshop_addons)
        _write_pbo(
            os.path.join(unselected_workshop_addons, "unselected_mod.pbo"),
            {"config.bin": _cfg_functions("unselected_mod", "shouldNotScan")},
        )
        game_roots = discover_game_addon_roots(arma_dir)
        assert set(game_roots) == {arma_dir, os.path.join(arma_dir, "Expansion")}, game_roots
        assert find_game_addon("A3_Characters_F", game_roots) is None
        assert find_game_addon("A3_Air_F_Heli_Light_01", game_roots) is None
        assert find_game_addon("missing_addon", game_roots) is None

        out_path = os.path.join(tmp, "armalint_mods.json")
        args = argparse.Namespace(
            mission=mission_dir,
            config=config_path,
            workshop=[workshop_root],
            arma_dir=[arma_dir],
            out=out_path,
            dry_run=False,
        )
        captured_stderr = io.StringIO()
        with contextlib.redirect_stderr(captured_stderr):
            rc = run_update(args)
        assert rc == 0, rc
        assert "could not resolve required addon A3_Characters_F" not in captured_stderr.getvalue()
        assert "could not resolve required addon A3_Air_F_Heli_Light_01" not in captured_stderr.getvalue()

        expected = {
            "ace_main_fnc_initialize",
            "ace_medical_fnc_setunconscious",
            "a3_functions_fnc_baseonly",
            "dlc_functions_fnc_dlconly",
        }
        cached = load_mod_cache(out_path)
        assert cached == expected, (cached, expected)
        cached_types = load_mod_type_cache(os.path.join(tmp, MOD_TYPE_CACHE_FILENAME))
        assert cached_types == {
            "ace_medical_fnc_setunconscious": ["Object", "Number"],
            "a3_functions_fnc_baseonly": ["Object"],
            "dlc_functions_fnc_dlconly": ["String"],
        }, cached_types

        # The cache file itself is a sorted JSON array.
        with open(out_path, "r", encoding="utf-8") as fh:
            assert fh.read().strip() == '["a3_functions_fnc_baseonly", "ace_main_fnc_initialize", "ace_medical_fnc_setunconscious", "dlc_functions_fnc_dlconly"]'

        scan_cache_path = os.path.join(tmp, MOD_SCAN_CACHE_FILENAME)
        assert os.path.isfile(scan_cache_path)
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            assert run_update(args) == 0
        assert load_mod_cache(out_path) == expected
        _write_pbo(
            os.path.join(workshop_mod_addons, "ace_extra.pbo"),
            {"config.bin": _cfg_functions("ace_extra", "second")},
        )
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            assert run_update(args) == 0
        assert load_mod_cache(out_path) == expected | {"ace_extra_fnc_second"}
        with contextlib.redirect_stdout(io.StringIO()):
            assert main(["--mission", mission_dir, "--out", out_path, "--clear-cache"]) == 0
        assert not os.path.exists(scan_cache_path)
        assert os.path.isfile(out_path)
        assert os.path.isfile(os.path.join(tmp, MOD_TYPE_CACHE_FILENAME))

    print("update self-test passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (importable for tests): parse ``argv`` and run the update.

    ``--self-test`` runs the built-in self-test instead of the normal update
    pipeline (checked before any argparse parsing); everything else is handed
    to ``run_update``.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in args:
        return _run_self_test()
    parsed = _build_parser().parse_args(args)
    if parsed.clear_cache:
        mission_dir = os.path.abspath(parsed.mission or os.getcwd())
        config_path = parsed.config or find_config(mission_dir)
        if parsed.out:
            out_path = os.path.abspath(parsed.out)
        elif config_path:
            out_path = os.path.join(project_state_dir(os.path.dirname(os.path.abspath(config_path))), _DEFAULT_CACHE_NAME)
        else:
            out_path = os.path.join(project_state_dir(mission_dir), _DEFAULT_CACHE_NAME)
        scan_cache_path = os.path.join(os.path.dirname(out_path), MOD_SCAN_CACHE_FILENAME)
        try:
            os.remove(scan_cache_path)
            print(f"Cleared scan cache: {scan_cache_path}")
        except FileNotFoundError:
            print(f"No scan cache to clear: {scan_cache_path}")
        except OSError as exc:
            _warn(f"could not clear scan cache {scan_cache_path}: {exc}")
            return 1
        return 0
    return run_update(parsed)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
