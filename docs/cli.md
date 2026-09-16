# CLI reference

## `armalint`

```text
armalint [--json] [--ignore GLOB] [--config PATH] [--version] PATH ...
```

`PATH` can be a file or a directory. Directories are searched for `.sqf`,
`.sqs`, `.hpp`, and `.ext` files. The command exits with status 1 when it finds
an error-severity diagnostic. Warnings do not make it fail.

The most useful options are:

| Option | What it does |
| --- | --- |
| `--json` | Print one JSON array of diagnostics. |
| `--ignore GLOB` | Skip matching files. Repeat it when needed. |
| `--config PATH` | Use this `armalint.json` instead of discovering one. |
| `--version` | Print the installed version. |

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
