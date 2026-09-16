# Getting started

## Install from the repository

```powershell
uv tool install .
```

The package provides `armalint`, `armalint-update`, and
`armalint-update-commands` commands. `pipx install .` is also supported.

## Lint a mission

```powershell
armalint C:\path\to\MyMission.Altis
```

Use `--json` for tooling integrations:

```powershell
armalint --json C:\path\to\MyMission.Altis
```

## Discover mission and mod functions

Update the per-mission function and type caches from installed Arma, DLC, and
required mod data:

```powershell
armalint-update --mission C:\path\to\MyMission.Altis
```

The updater stores `armalint_mods.json`, `armalint_mods_types.json`, and an
incremental `armalint_scan_cache.json` beside the mission configuration. Force
a fresh scan with:

```powershell
armalint-update --mission C:\path\to\MyMission.Altis --clear-cache
```

The updater reads `armalint.json` when present. Use `functionTags` for broad
mod namespaces and `functionTypes` for project-specific argument contracts.
