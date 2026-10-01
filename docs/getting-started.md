# Getting started

There are two useful ways to run Armalint. Install it as a command you can use
from anywhere, or keep a checkout around while working on the linter itself.

## Install it as a command

```powershell
uv tool install armalint
uv tool update-shell
```

That gives you `armalint`, `armalint-update`, `armalint-update-commands`,
`armalint-mcp`, `armalint-watch`, and `armalint-lsp`. `pipx install armalint`
does the same job if that is what you already use.

`uv tool update-shell` adds uv's tool directory to the user PATH when needed.
For development from a local checkout, use an editable install so source
changes take effect immediately:

```powershell
uv tool install --editable C:\path\to\armalint
uv tool update-shell
```

For a reproducible development environment, install `uv`, then run:

```powershell
uv sync
uv run python tests/run_all.py
uv build
```

The project uses Hatchling as its PEP 621 build backend. Both the wheel and
source archive include the bundled command and function data needed for normal
linting; extracted mission and mod caches remain outside the package.

On Windows, `uv tool install` places the CLI tools, including `armalint-watch`
and `armalint-lsp`, on the uv tool bin directory. `uv tool upgrade armalint`
upgrades a published release, while `uv tool install --force --editable
C:\path\to\armalint` refreshes an existing local tool installation.

`pip --user` is also supported, but pip does not add Python's user `Scripts`
directory to PATH. Add that directory yourself if you choose that route.

## First project check

For a mission project, update its index and then lint it:

```powershell
armalint-update --mission C:\path\to\MyMission.Altis --download-dependencies
armalint C:\path\to\MyMission.Altis
```

The update indexes the Arma, DLC, and mod functions, signatures, and macros
needed by that mission. Armalint uses the index to recognize dependency-provided
functions and perform more argument checks; unchanged data is reused from the
project cache. Add `--download-dependencies` when declared Workshop content is
not already installed locally.

## Lint a mission

Point Armalint at a mission folder:

```powershell
armalint C:\path\to\MyMission.Altis
```

It walks the folder and checks the script and config files it recognises. If
you are feeding the result to an editor or another tool, ask for JSON:

```powershell
armalint --json C:\path\to\MyMission.Altis
```

## Find the functions provided by a mission's mods

The updater reads `mission.sqm`, finds the relevant installed game and mod
data, and writes a cache for the linter to use:

```powershell
armalint-update --mission C:\path\to\MyMission.Altis
```

With `--download-dependencies`, the updater downloads every declared Workshop
entry from both `mods` and `dependencies` into the project's
`.armalint/dependencies` directory. Without that flag, those entries must
already be present in a discovered Steam Workshop library.

Workshop names and IDs identify downloads; addon dependencies use Arma patch
names from `CfgPatches`. You can get those names from `mission.sqm`, the
updater's `required addon` output, or an addon's `config.cpp`/`config.bin`.

SteamCMD uses a separate login session from the desktop Steam client. Signing
in to SteamCMD can log the desktop Steam client out on the same machine, so
save any active Steam work and be prepared to sign in again afterward.

The updater indexes the base Arma data and only DLC data referenced by the
mission's declared addon dependencies. This keeps scans smaller and lets the
linter report accidental use of an undeclared DLC function as an unknown
function. Use `--all-game-data` when the project intentionally supports any
installed DLC.

The first scan can take a while. With a large Arma installation, a large mod
list, or many declared source and Workshop dependencies, it may take several
minutes because Armalint has to open and inspect each selected PBO. The updater
shows scan progress while it works. It hashes and records the files it has
examined, so later scans can reuse unchanged results and are usually much
faster. It writes
`.armalint/armalint_mods.json`, `.armalint/armalint_mods_types.json`, and
`.armalint/armalint_scan_cache.json` under the mission directory.
The updater also writes `.armalint/armalint_mods_metadata.json`, which records the
metadata schema, optional Arma version, source addon/PBO for extracted
functions, and unreadable or unsupported PBOs.

Downloaded dependencies are kept in `.armalint/dependencies` and are treated as
normal scan roots on later runs. Existing downloads and unchanged scan roots
are reused; `--force-download-dependencies` refreshes Workshop items, while
`--rebuild` refreshes dependencies and rebuilds every scan root.

If you want to start that scan again from scratch:

```powershell
armalint-update --mission C:\path\to\MyMission.Altis --rebuild
```

`--clear-cache` only removes the incremental scan cache and exits. It is useful
when you want to clear the cache before a separately controlled update.

The cache is per mission. A second mission gets its own list and its own scan
cache. An `armalint.json` file can add optional mods, broad function tags,
project-specific argument types, and mission-wide rule suppression with
`"ignoreRules": ["W206"]`. It can also set severities and skip generated paths:

```json
{"ignore": ["vendor/**", "generated/**"], "severity": {"W206": "off", "W101": "error"}}
```

Severity values are `error`, `warning`, `info`, and `off`. For one run, use
`armalint --ignore-rule W206 <path>`; source comments can suppress a single
line or section. Use `--sarif` for CI/code-scanning integrations. Whitespace
diagnostics (`W301` and `W302`) are enabled by default; use `--no-style` to
disable them.

For CI, use `--fail-on warning`, `--github-actions`, `--checkstyle`, or
`--diff-staged` as appropriate. Use `--fix-preview` to inspect safe edits
before applying them with `--fix`.
