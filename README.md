# Armalint

Armalint is a pure-Python linter for **Arma 3 SQF** mission/script development.
It tokenizes SQF source and runs a set of static checks that catch common
mistakes — unbalanced brackets, unterminated strings,
probably-undefined local variables, and unknown `call`/`spawn` targets —
without needing Arma itself or any third-party dependencies.

It is intentionally small and deterministic: a single shared token stream is
fed to each analyzer, diagnostics carry machine-readable codes, and the CLI
supports both human and JSON output.

## Requirements

- Python **3.9+**
- Standard library only (no third-party packages)

## Installation

`armalint` runs directly from a checkout with no installation:

```powershell
python -m armalint <paths>
```

Optionally install it in editable mode so `armalint` is on your `PATH`
(requires `setuptools>=61`, already used as the build backend):

```powershell
pip install -e .
```

For an isolated command-line installation, use `uv` or `pipx`:

```powershell
uv tool install .
# or
pipx install .
```

The package also installs `armalint-update` and
`armalint-update-commands` entry points for refreshing the extracted mod and
engine command data.

## Usage

```text
python -m armalint [--json] [--ignore GLOB] [--rules RULE] [--version] <paths>...
python -m armalint --file PATH [--json]
python -m armalint --snippet SOURCE [--json]
python -m armalint --mission PATH --snippet SOURCE [--json]
```

| Option          | Description                                                        |
| --------------- | ------------------------------------------------------------------ |
| `paths`         | One or more files or directories to lint (positional, required).    |
| `--file PATH`   | Lint one explicit file; repeatable.                                 |
| `--snippet SOURCE` | Lint inline SQF without creating a file.                          |
| `--mission PATH` | Use mission symbols/configuration with `--snippet` or `--file`.      |
| `--json`        | Emit a single JSON array of diagnostic objects instead of text.     |
| `--ignore GLOB` | Skip files matching a `fnmatch` glob (relative to each directory argument). Repeatable. |
| `--rules RULE`  | Accepted for forward compatibility; currently ignored. Repeatable. |
| `--version`     | Print the version and exit.                                        |

When given a directory, Armalint walks it recursively and lints files ending
in `.sqf`, `.sqs`, `.hpp`, and `.ext`. The exit code is `0` when there are no
`error`-severity diagnostics and `1` otherwise.

For a quick expression check, lint a snippet directly:

```powershell
python -m armalint --snippet 'params [["_delay", 0]]; sleep _delay;' --json
```

Snippet diagnostics use `<snippet>` as their file name. A snippet cannot be
combined with positional paths or `--file`.

Use a mission as context when checking a function call or local signature:

```powershell
python -m armalint --mission MyMission.Altis --snippet 'ALT_fnc_start call [];'
```

### Examples

Lint a single file:

```powershell
python -m armalint tests/fixtures/clean.sqf
```

```text
1 file(s) linted, 0 diagnostic(s)
```

Lint a file with problems:

```powershell
python -m armalint tests/fixtures/buggy.sqf
```

```text
tests/fixtures/buggy.sqf:6:10: error [E001]: unclosed '('
tests/fixtures/buggy.sqf:7:10: warning [W101]: possible undefined variable: _undefinedVar
tests/fixtures/buggy.sqf:8:6: warning [W201]: unknown function/command: thisFunctionDoesNotExist
1 file(s) linted, 3 diagnostic(s)
```

(exit code `1`)

Machine-readable output:

```powershell
python -m armalint tests/fixtures/buggy.sqf --json
```

```json
[
  {"file": "tests/fixtures/buggy.sqf", "line": 6, "column": 10, "severity": "error", "code": "E001", "message": "unclosed '('"},
  {"file": "tests/fixtures/buggy.sqf", "line": 7, "column": 10, "severity": "warning", "code": "W101", "message": "possible undefined variable: _undefinedVar"},
  {"file": "tests/fixtures/buggy.sqf", "line": 8, "column": 6, "severity": "warning", "code": "W201", "message": "unknown function/command: thisFunctionDoesNotExist"}
]
```

Lint a whole mission folder, ignoring third-party scripts:

```powershell
python -m armalint mission\ --ignore "vendor\**" --ignore "*.bak.sqf"
```

## Rule set

| Code | Severity | Meaning                                                            |
| ---- | -------- | ------------------------------------------------------------------ |
| E001 | error    | Bracket balance: an unclosed or unmatched `(`, `[`, or `{`.         |
| E002 | error    | Unterminated string literal.                                        |
| E003 | error    | Trailing comma in an array.                                         |
| E004 | error    | Missing `then` after a parenthesized `if` condition.                 |
| E005 | error    | Invalid token after `else`.                                         |
| E006 | error    | Missing comma between adjacent literal array elements.              |
| E007 | error    | Reversed `forEach` form.                                             |
| W101 | warning  | Possible undefined local variable (used before definition).         |
| W201 | warning  | Unknown function/command name after `call` or `spawn`.              |
| W203 | warning  | Known built-in unary command received a statically incompatible value.|
| W204 | warning  | Indexed function received more arguments than its signature allows.   |
| W205 | warning  | `call` or `spawn` targeted a literal value rather than code.           |
| W206 | warning  | `if` condition is a literal value and is always truthy or falsey.    |

`W203` currently checks common built-ins `hint`, `hintSilent`, `sleep`,
`uiSleep`, `systemChat`, `parseNumber`, `toArray`, and `count`. It infers types
from literals and simple local assignments; unknown expressions are left alone.
The signature table is intentionally small and can be extended as more built-in
command signatures are added. Mission-defined function parameters are not yet
checked.

Error (`E*`) diagnostics make the CLI exit non-zero; warnings (`W*`) do not.

## Known limitations

- **No nested block scoping for variables.** Undefined-variable analysis
  (`W101`) uses a single flat "defined" set for the whole file. A variable
  assigned inside one `{ ... }` block is treated as defined everywhere after it,
  so shadowing and scope leakage are not modeled.
- **`params` nested-default entries are not auto-defined.** Only top-level
  strings are registered by `params`. For `params ["_a", ["_b", 2]]`, `_a` is
  treated as defined but the nested default `_b` is not.
- **Direct command-call detection is not implemented.** `W201` only inspects
  named references that follow `call`/`spawn` (e.g. `call BIS_fnc_param` or
  `call "BIS_fnc_param"`). Standalone command calls like `hint "x"` are not
  checked against the registry.
- **No statement-boundary/semicolon checks.** Because the final semicolon
  before a closing `}` is optional in SQF, statement boundaries cannot be
  inferred reliably from semicolons alone. Checking for missing semicolons and
  related statement-boundary issues is not currently implemented (future work).
- **Preprocessor directives are tokenized but not expanded.** `#define`,
  `#include`, `#ifdef`, and friends are emitted as opaque `preprocessor` tokens
  and are transparent to every check. No macro expansion or conditional
  compilation is performed.

## Extending the known-name registry

The `W201` check looks up names in `armalint/known.py`, which holds two
case-insensitive sets: `KNOWN_COMMANDS` (engine commands) and
`KNOWN_FUNCTIONS` (`BIS_fnc_*`-style functions).

`KNOWN_COMMANDS` is seeded from a comprehensive, generated list at
`armalint/data/commands.txt` (one lowercase command per line, sourced from the
Bohemia Interactive Community Wiki and its GitHub mirrors), UNION-ed with an
inline fallback set in `known.py` so the module still works if the data file is
absent. See the header of `armalint/data/commands.txt` for sources and
regeneration instructions.

**Option A — edit `known.py` directly:** add the name to the appropriate
literal set near the top of the file (a fallback; also add it to
`armalint/data/commands.txt` so it survives regeneration). Names are normalized
to lowercase at import time, so casing does not matter.

**Option B — register at runtime:**

```python
from armalint.known import register

register("myCustomCommand", "command")   # -> KNOWN_COMMANDS
register("MY_fnc_helper", "function")    # -> KNOWN_FUNCTIONS
register("myDualPurpose", "both")        # -> both sets
```

The `kind` argument is one of `"command"`, `"function"`, or `"both"`.
Lookups are also exposed via `is_known(name)`, `is_known_command(name)`, and
`is_known_function(name)`.

## Project configuration (mod function tags)

Mod-provided functions (`ace_medical_fnc_*`, `CBA_settings_fnc_*`, …) are not
in the built-in registry and would otherwise be reported as `W201`. Declare the
mods your project uses by placing an `armalint.json` (or `.armalint.json`)
file at the project root:

```json
{
  "functionTags": ["ace_medical", "ace_hearing", "CBA_settings"]
}
```

The mod updater also extracts argument types from explicit `params` and `param` validators
in installed mod function source. Run `python -m armalint.update` to write
`armalint_mods_types.json` next to the function cache. For contracts that are
not expressed in source, add ordered `_this` argument types under
`functionTypes`; these project declarations override extracted signatures:

```json
{
  "functionTags": ["acme"],
  "functionTypes": {
    "acme_fnc_route": ["Object", "String"]
  }
}
```

Argument types are checked when they are statically inferable (currently
literal values and simple literal assignments). Use a union such as
`"String|Array"` for an argument that accepts either type. Source extraction
only reports explicit validators; a default value by itself is not treated as
a type contract.

Armalint matches each tag case-insensitively against the leading part of a
function name before the first `_fnc_` — so the tag `ace_medical` suppresses
`W201` for `ace_medical_fnc_setUnconscious`, `ACE_Medical_fnc_whatever`, and any
other `<tag>_fnc_*` reference.

The config file is discovered automatically by walking **up** from each linted
path toward the filesystem root (`armalint.json` is preferred over
`.armalint.json` in the same directory). If several paths resolve to different
config files, their tags are unioned. You can override discovery with an
explicit path:

```powershell
python -m armalint --config path/to/armalint.json <paths>
```

## Mod function cache (exact function names)

Tags are broad: a tag like `ace_medical` suppresses `W201` for *any*
`ace_medical_fnc_*` reference, including typos. For exact matching, Armalint can
also load the **mod function cache** — a JSON array of the precise
`CfgFunctions` names provided by a mission's mods — written by
`python -m armalint.update`:

```powershell
python -m armalint.update --mission <dir> [--workshop <path>] [--arma-dir <path>]
```

This resolves the mission's required addons (from `mission.sqm`) plus any
optional mods declared in `armalint.json`, and scans the selected installation
for base-game/DLC `Addons` folders as well as local `@` mods. It writes exact
function names to `armalint_mods.json` and source-declared `params` type
validators to `armalint_mods_types.json`, next to the discovered `armalint.json`
(or in the mission directory when no config exists). Pass the Arma install root
with `--arma-dir` to select it explicitly; otherwise the updater checks common
Steam locations, `libraryfolders.vdf` entries, and `ARMA3_DIR` / `ARMA_3_DIR`.
The updater also writes `armalint_scan_cache.json` beside these caches. On later
updates it compares addon file sizes and modification times and reuses scan
results for unchanged roots, avoiding PBO parsing. Roots with changed, added, or
removed addon files are rescanned. Delete this file to force a complete rescan.
You can also clear it from the command line with
`python -m armalint.update --mission <dir> --clear-cache`; this preserves the
function-name and type caches and exits, so the next normal update performs a
full scan.

At lint time, `python -m armalint <dir>` auto-loads that cache and the adjacent
`armalint_mods_types.json`: for each lint
path Armalint walks **up** (the same discovery used for `armalint.json`) to find
`armalint_mods.json`, then registers every cached name on the symbol index for
**exact** (case-insensitive) matching. With both the cache and the tag mechanism
available, `ace_medical_fnc_setUnconscious` is recognized by exact name (so a
typo like `ace_medical_fnc_setUnconsious` is *not* suppressed), while any other
`<tag>_fnc_*` name is still covered by its tag. When several lint paths resolve
to different cache files, their function names are unioned.

## Updating the command database

`armalint/data/commands.txt` is a generated list of lowercase SQF command
names, seeded from community GitHub mirrors of the Bohemia Interactive
Community Wiki (the wiki's own API blocks bots with a 403). After Arma ships an
update with new commands, refresh it with a single command:

```powershell
python -m armalint.update_commands
```

This fetches the mirror sources, normalizes each name (lowercase, keeping only
`^[a-zA-Z_][a-zA-Z0-9_]*$` identifiers), and **UNION**s them with the names
already in `commands.txt` and the inline fallback in `known.py` — so
regeneration is strictly additive and never loses a name. The result is written
atomically with a fresh metadata header recording the generation timestamp,
source URLs, and total count.

To preview changes without touching the file:

```powershell
python -m armalint.update_commands --dry-run
```

The dry run prints the current count, the count that would result, and how many
names would be added.

## Testing

From the project root, run the aggregate test runner:

```powershell
python tests/run_all.py
```

It runs each analyzer module's built-in self-test, lints the fixtures, and
prints a PASS/FAIL summary (exits non-zero on any failure).
