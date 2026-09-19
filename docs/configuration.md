# Configuration and troubleshooting

Armalint discovers `armalint.json` (or `.armalint.json`) by walking upward
from the file or directory being linted. An explicit `--config` path overrides
discovery. Configuration is project-specific: two missions can use different
mods, signatures, suppressions, and generated-file patterns without affecting
each other.

Discovery is performed per linted file, so a monorepo can contain multiple
nested missions with different `armalint.json` files. The nearest config
controls that file's suppressions, severities, presets, ignore patterns, and
plugins; indexed function metadata is combined across the files being linted.

## Common configuration

```json
{
  "mods": ["https://steamcommunity.com/sharedfiles/filedetails/?id=123456789"],
  "functionTags": ["ace_medical"],
  "functionTypes": {"ALT_fnc_route": ["Object", "String"]},
  "functionReturns": {"ALT_fnc_route": "Array"},
  "ignoreRules": ["W206"],
  "ignore": ["vendor/**", "generated/**"],
  "severity": {"W101": "error", "W206": "off"},
  "presets": ["recommended"],
  "plugins": ["tools/armalint_rules.py"]
}
```

`functionTags` is a broad fallback. Prefer an updater-generated exact index
when possible, because a tag also accepts misspelled names. `functionTypes`
and `functionReturns` document project contracts that cannot be extracted from
source. Severity values are `error`, `warning`, `info`, and `off`; the aliases
`ruleSeverity` and `ignorePatterns` are accepted.

Supported presets are `recommended`, `strict`, `style`, and `performance`.
`strict` promotes warnings to errors, while `style` enables whitespace rules.
The `--rules` option can select individual codes or categories (`syntax`,
`correctness`, `flow`, `suppression`, and `style`) for focused checks.
Configuration files are schema-checked; unknown keys, rule codes, presets, and
invalid severity values produce `E012` instead of being silently ignored.
Project plugins are Python files resolved relative to the configuration file;
see [`plugins.md`](plugins.md) for the registration API.

### External locals

Some projects compile template files into a caller's local scope. For example,
`call compile preprocessFileLineNumbers _path` may execute a template after the
caller creates `_addon`. Declare those contracts so use-before-definition checks
do not report the injected locals:

```json
{
  "externalLocals": ["_addon"]
}
```

For a one-off check, use `--external-local _addon`. During a project scan,
Armalint also discovers locals explicitly declared before an exact
`call compile preprocessFileLineNumbers` sequence. Dynamic loaders whose
scope cannot be proven from source should keep using this explicit contract;
names are never inferred from variable names or file paths alone.

## Cache files

`armalint-update` writes these files beside the mission configuration:

| File | Purpose |
| --- | --- |
| `armalint_mods.json` | Exact indexed function names. |
| `armalint_mods_types.json` | Extracted argument contracts. |
| `armalint_mods_metadata.json` | Schema, descriptions, lifecycle flags, provenance, confidence, and scan errors. |
| `armalint_scan_cache.json` | Fingerprints and reusable per-root scan results. |

The caches are safe to delete and regenerate. `--clear-cache` removes only the
incremental scan cache, preserving the last completed function and type index
until the next update writes a replacement.

## Troubleshooting updater scans

If required addons cannot be resolved, pass the Arma installation explicitly:

```powershell
armalint-update --mission C:\path\to\Mission.Altis `
  --arma-dir D:\Games\Arma3 `
  --workshop D:\SteamLibrary\steamapps\workshop\content\107410
```

The updater checks Steam library folders, common Windows installation paths,
`ARMA3_DIR`/`ARMA_3_DIR`, base `Addons`, DLC `Addons`, and selected `@` mods.
It does not scan every installed Workshop mod unless the mission requires it or
the project lists it in `mods`.

Use `--arma-version 2.18.152` to record an explicit game version in metadata.
Unreadable or unsupported PBOs are retained as scan notes so a successful
partial index is distinguishable from a complete scan.

## MCP and CI

`armalint-mcp` is read-only and uses existing project caches. It does not run
the updater or change files. Use `--sarif` for code-scanning systems and
`--json` for editor integrations that want a compact native format.
