# CLI reference

## `armalint`

```text
armalint [--json|--sarif] [--style] [--ignore GLOB] [--ignore-rule RULE] [--config PATH] [--version] PATH ...
armalint --file PATH [--json|--sarif]
armalint --snippet 'sleep "soon";' [--json|--sarif]
armalint --mission PATH --snippet 'sleep _delay;' [--json|--sarif]
armalint-watch PATH [--interval SECONDS] [--once]
armalint-lsp
```

`PATH` can be a file or a directory. Directories are searched for `.sqf`,
`.sqs`, `.hpp`, and `.ext` files. The command exits with status 1 when it finds
an error-severity diagnostic. Warnings do not make it fail.

The most useful options are:

| Option | What it does |
| --- | --- |
| `--json` | Print one JSON array of diagnostics. |
| `--sarif` | Print SARIF 2.1.0 results with stable fingerprints, rule metadata, and help links. |
| `--checkstyle` | Print Checkstyle XML for CI systems that consume XML reports. |
| `--timings` | Report collection, indexing, lint, and total timings as JSON on stderr. |
| `--check-suppressions` | Report inline suppressions without reasons or matching diagnostics. |
| `--baseline PATH` | Suppress findings whose fingerprints are recorded in a JSON baseline. |
| `--style` | Enable optional style diagnostics (`W301`/`W302`). |
| `--fix` | Apply safe style fixes for trailing whitespace and tabs. |
| `--fix-preview` | Emit machine-readable safe edits without modifying files. |
| `--diff [REF]` | Report only findings on changed lines relative to `REF` (default `HEAD`). |
| `--diff-staged` | Report only findings in the staged Git index. |
| `--fail-on LEVEL` | Set the failure threshold: `error`, `warning`, `info`, or `none`. |
| `--github-actions` | Emit GitHub Actions annotation commands in text output. |
| `--file PATH` | Lint one specific file; repeat the option for several files. |
| `--snippet SOURCE` | Lint inline SQF and label diagnostics as `<snippet>`. |

## Incremental watching and editors

`armalint-watch` polls one or more SQF files or mission directories and emits
one JSON object for each changed file. The first poll reports all files; later
polls report only files whose timestamp or size changed. Use `--once` for a
single incremental pass, or set `--interval` to control polling frequency.

`armalint-lsp` speaks the Language Server Protocol over standard input/output.
It supports `initialize`, full-text `didOpen`/`didChange`, `didClose`, and
diagnostic publication. Configure it as an editor's stdio language server with
the command `armalint-lsp`.

`--fix` applies whitespace fixes and removes a trailing comma immediately
before an array close. Use `--fix-preview` to review the exact file offsets,
line/column, replacement text, and rule code before applying them. `--diff` is useful in
pull-request jobs where existing findings are already tracked separately. For
staged pre-commit checks, use `--diff-staged`; for pull requests, pass the
merge-base or target branch to `--diff`. Deleted lines are ignored because they
cannot produce current source diagnostics. For GitHub Actions, combine
`--github-actions` with `--fail-on warning` to annotate findings and fail when
warnings or errors are present.
| `--mission PATH` | Use a mission's symbols and configuration while linting a snippet or file. |
| `--ignore GLOB` | Skip matching files. Repeat it when needed. |
| `--ignore-rule RULE` | Suppress a diagnostic rule for the whole run, such as `W206`. Repeatable. |
| `--config PATH` | Use this `armalint.json` instead of discovering one. |
| `--version` | Print the installed version. |

For a quick check without creating a file, pass SQF directly:

```powershell
armalint --snippet 'params [["_delay", 0]]; sleep _delay;' --json
```

Use `--file` when an explicit single-file option is more convenient than a
positional path. Add `--mission` to resolve mission functions and signatures
without linting every mission file. A snippet cannot be combined with file or
directory paths.

Rules can also be suppressed in source comments:

```sqf
// armalint: disable-next-line W206
if (true) then { };
// armalint: disable-line W101
hint str _value;
```

Use `// armalint: disable W206` and `// armalint: enable W206` around a
file-level or section-wide exception. A mission's `armalint.json` can set
`{"ignoreRules": ["W206", "W101"]}` for every file in that mission.
Command-line and mission-configured rule suppressions also apply to diagnostics
from files pulled in through `#include`.

Project configuration can also set rule severity and file patterns:

```json
{"severity": {"W206": "off", "W101": "error"}, "ignore": ["vendor/**", "generated/**"]}
```

Severity values are `error`, `warning`, `info`, and `off`. The aliases
`ruleSeverity` and `ignorePatterns` are accepted as well. Use `--sarif` for
CI/code-scanning integrations; `--json` remains the compact native format.

## `armalint-update`

```text
armalint-update [--mission DIR] [--config PATH] [--workshop PATH]
                [--arma-dir PATH] [--out PATH] [--arma-version VERSION]
                [--dry-run] [--clear-cache]
```

Normally automatic installation discovery is enough. If Arma is installed in
an unusual place, pass `--arma-dir`. Repeat `--workshop` and `--arma-dir` when
you need to search more than one location. `--dry-run` reports what would be
found without writing caches.
`--arma-version` records the game version in the metadata cache; the
`ARMALINT_ARMA_VERSION` environment variable can provide the same value.

## `armalint-update-commands`

The built-in command list is generated data. Refresh it after an Arma update:

```powershell
armalint-update-commands
armalint-update-commands --dry-run
armalint-update-commands --refresh-signatures
```

The normal command update uses the checked-in snapshot. Use
`--refresh-signatures` only when you intentionally want to contact the XML
source and refresh typed command metadata.

## `armalint-mcp`

Armalint includes a dependency-free MCP server using stdio JSON-RPC. It is
read-only: it can lint text or paths, look up commands and functions, and
return the stable rule catalog, but it never updates or clears caches.

```powershell
armalint-mcp
```

For Claude Desktop, configure the command as a stdio MCP server:

```json
{
  "mcpServers": {
    "armalint": {"command": "armalint-mcp"}
  }
}
```

The tools are `lint_sqf`, `lint_path`, `lookup_command`, `lookup_function`,
and `list_rules`. Responses use a versioned `schema` field and diagnostics
include file, line, column, severity, rule code, and message. Function lookups
also return available `CfgFunctions` descriptions, lifecycle flags, declared
files, source comments, addon/PBO provenance, and a confidence level.
