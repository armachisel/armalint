# CLI reference

## `armalint`

```text
armalint [--json] [--ignore GLOB] [--config PATH] [--version] PATH ...
```

`PATH` may be a file or directory. Directories are searched for `.sqf`,
`.sqs`, `.hpp`, and `.ext` files. The process exits with status 1 when an
error-severity diagnostic is found.

## `armalint-update`

```text
armalint-update [--mission DIR] [--config PATH] [--workshop PATH]
                [--arma-dir PATH] [--out PATH] [--dry-run] [--clear-cache]
```

Use repeated `--workshop` and `--arma-dir` options when automatic discovery is
not appropriate. `--dry-run` reports the scan without writing caches.

## `armalint-update-commands`

Refresh the generated built-in command registry:

```powershell
armalint-update-commands
armalint-update-commands --dry-run
```
