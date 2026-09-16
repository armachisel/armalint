# CLI reference

## `armalint`

```text
armalint [--json] [--ignore GLOB] [--config PATH] [--version] PATH ...
armalint --file PATH [--json]
armalint --snippet 'sleep "soon";' [--json]
armalint --mission PATH --snippet 'sleep _delay;' [--json]
```

`PATH` can be a file or a directory. Directories are searched for `.sqf`,
`.sqs`, `.hpp`, and `.ext` files. The command exits with status 1 when it finds
an error-severity diagnostic. Warnings do not make it fail.

The most useful options are:

| Option | What it does |
| --- | --- |
| `--json` | Print one JSON array of diagnostics. |
| `--file PATH` | Lint one specific file; repeat the option for several files. |
| `--snippet SOURCE` | Lint inline SQF and label diagnostics as `<snippet>`. |
| `--mission PATH` | Use a mission's symbols and configuration while linting a snippet or file. |
| `--ignore GLOB` | Skip matching files. Repeat it when needed. |
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

## `armalint-update`

```text
armalint-update [--mission DIR] [--config PATH] [--workshop PATH]
                [--arma-dir PATH] [--out PATH] [--dry-run] [--clear-cache]
```

Normally automatic installation discovery is enough. If Arma is installed in
an unusual place, pass `--arma-dir`. Repeat `--workshop` and `--arma-dir` when
you need to search more than one location. `--dry-run` reports what would be
found without writing caches.

## `armalint-update-commands`

The built-in command list is generated data. Refresh it after an Arma update:

```powershell
armalint-update-commands
armalint-update-commands --dry-run
```
