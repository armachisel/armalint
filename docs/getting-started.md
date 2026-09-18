# Getting started

There are two useful ways to run Armalint. Install it as a command you can use
from anywhere, or keep a checkout around while working on the linter itself.

## Install it as a command

```powershell
uv tool install .
```

That gives you `armalint`, `armalint-update`, `armalint-update-commands`, and
`armalint-mcp`. `pipx install .` does the same job if that is what
you already use.

For a reproducible development environment, install `uv`, then run:

```powershell
uv sync
uv run python tests/run_all.py
uv build
```

The project uses Hatchling as its PEP 621 build backend. Both the wheel and
source archive include the bundled command and function data needed for normal
linting; extracted mission and mod caches remain outside the package.

On Windows, `uv tool install .` places the three CLI tools and `armalint-mcp`
on the uv tool bin directory. `uv tool upgrade armalint` upgrades a published
release, while `uv tool install --force .` refreshes a local checkout.

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

The first scan can take a while. The updater hashes and records the files it
has examined, so later scans can reuse unchanged results. It writes
`armalint_mods.json`, `armalint_mods_types.json`, and
`armalint_scan_cache.json` beside the mission configuration.
The updater also writes `armalint_mods_metadata.json`, which records the
metadata schema, optional Arma version, source addon/PBO for extracted
functions, and unreadable or unsupported PBOs.

If you want to start that scan again from scratch:

```powershell
armalint-update --mission C:\path\to\MyMission.Altis --clear-cache
```

The cache is per mission. A second mission gets its own list and its own scan
cache. An `armalint.json` file can add optional mods, broad function tags,
project-specific argument types, and mission-wide rule suppression with
`"ignoreRules": ["W206"]`. It can also set severities and skip generated paths:

```json
{"ignore": ["vendor/**", "generated/**"], "severity": {"W206": "off", "W101": "error"}}
```

Severity values are `error`, `warning`, `info`, and `off`. For one run, use
`armalint --ignore-rule W206 <path>`; source comments can suppress a single
line or section. Use `--sarif` for CI/code-scanning integrations and `--style`
to enable optional whitespace diagnostics (`W301` and `W302`).
