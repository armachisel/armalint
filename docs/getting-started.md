# Getting started

There are two useful ways to run Armalint. Install it as a command you can use
from anywhere, or keep a checkout around while working on the linter itself.

## Install it as a command

```powershell
uv tool install .
```

That gives you `armalint`, `armalint-update`, and
`armalint-update-commands`. `pipx install .` does the same job if that is what
you already use.

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

If you want to start that scan again from scratch:

```powershell
armalint-update --mission C:\path\to\MyMission.Altis --clear-cache
```

The cache is per mission. A second mission gets its own list and its own scan
cache. An `armalint.json` file can add optional mods, broad function tags, and
project-specific argument types.
