# Function indexes

Armalint can only recognise a function it knows about. The built-in registry
covers engine commands and the functions shipped with the project. Your
mission's own functions and its mods are a different matter. They change from
mission to mission, and they are often installed in different places on
different machines.

That is why Armalint uses project-specific indexes instead of one giant list
of every function anyone might have installed.

## Why index functions?

Without an index, a misspelled function can look exactly like a valid mod
function. For example, a broad `ace_medical` tag would hide both
`ace_medical_fnc_setUnconscious` and a typo such as
`ace_medical_fnc_setUnconsious`. An exact index recognises the first and keeps
warning about the second.

The index also gives the type checker a chance to help. When a function's
source contains explicit `params` or `param` validators, the updater records
those types. Armalint can then warn when a statically known argument is the
wrong kind of value.

Indexing is not required for basic syntax linting. It matters when you want
useful unknown-function and argument-type diagnostics.

There are two related sources of built-in knowledge. The updater extracts
function names and signatures from base-game and DLC addon PBOs. The separate
`armalint-update-commands` command refreshes the generated list of engine
command names used by the direct-command checker. Run both when refreshing
Arma data after a game update.

## Build an index

Run the updater from the mission directory or pass the mission explicitly:

```powershell
armalint-update --mission C:\path\to\MyMission.Altis
```

The updater uses `mission.sqm` to find required addons, checks the normal Arma
and DLC `Addons` folders, and searches the installed mod locations it can
discover. The game and DLC scan matters because many built-in functions are
declared in `CfgFunctions` inside those addon PBOs. They are indexed in the
same way as mod functions. You can provide locations explicitly when
automatic discovery is not enough:

```powershell
armalint-update `
  --mission C:\path\to\MyMission.Altis `
  --arma-dir D:\Games\Arma3 `
  --workshop D:\SteamLibrary\steamapps\workshop\content\107410
```

The updater writes four files:

| File | Purpose |
| --- | --- |
| `.armalint/armalint_mods.json` | Exact function names found in the selected base-game, DLC, and mod data. |
| `.armalint/armalint_mods_types.json` | Argument types extracted from function source. |
| `.armalint/armalint_scan_cache.json` | Hashes and scan results used to skip unchanged PBOs and files. |
| `.armalint/armalint_mods_metadata.json` | Versioned descriptions, lifecycle flags, source PBOs, confidence, and scan errors. |

The first scan may take a while. That is the price of looking inside the game
and mod data. Later scans reuse unchanged results. Use `--clear-cache` when
you want to force the scan:

```powershell
armalint-update --mission C:\path\to\MyMission.Altis --clear-cache
```

## Why the index is project-specific

The output is deliberately stored under `.armalint` beside the mission configuration, rather
than in one global user cache. Two missions can require different mods, use
different versions of the same mod, or define functions with the same name.
A global list would either miss valid functions or make invalid functions look
valid.

For example:

```text
Mission A\armalint.json
Mission A\.armalint\armalint_mods.json
Mission A\.armalint\armalint_mods_types.json

Mission B\armalint.json
Mission B\.armalint\armalint_mods.json
Mission B\.armalint\armalint_mods_types.json
```

Linting Mission A discovers and uses Mission A's files. Linting Mission B
does the same with Mission B's files. When linting several paths, Armalint
unions the indexes it discovers for those paths; it does not silently replace
one mission's data with another's.

The scan cache belongs to the same project for the same reason. A changed
mod, Arma installation, extractor, or mission configuration must not make an
unrelated mission's index change underneath it.

To record the game version used for an index, pass it explicitly:

```powershell
armalint-update --mission C:\path\to\MyMission.Altis --arma-version 2.18.152
```

The metadata cache records which addon/PBO supplied each function and notes
unreadable or unsupported PBOs. This makes an apparently valid partial scan
visible to editors and MCP clients.

## Broad tags and exact names

An `armalint.json` file can declare broad function namespaces:

```json
{
  "functionTags": ["ace_medical", "CBA_settings"]
}
```

Tags are useful when source is unavailable or when a mod generates functions
that cannot be extracted. They are intentionally broad. The updater's exact
index is better when you want typo detection.

You can add project-specific type contracts as well:

```json
{
  "functionTypes": {
    "acme_fnc_route": ["Object", "String"]
  }
}
```

These declarations belong to the project because they describe the functions
that project expects to call. They do not change the built-in database or any
other mission's analysis.

If a mission function has a known return type, declare it with
`functionReturns`. This lets type inference continue through a call:

```json
{
  "functionReturns": {
    "ALT_fnc_distanceToRoute": "Number",
    "ALT_fnc_getDensifiedRoute": "Array"
  }
}
```

For example, after the first declaration Armalint can understand
`_distance = [] call ALT_fnc_distanceToRoute; round _distance;` as a numeric
expression. Without the declaration it leaves the call's return type unknown
and does not guess.
