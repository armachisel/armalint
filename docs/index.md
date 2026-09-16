# Armalint

Armalint is a pure Python linter for Arma 3 SQF missions and scripts. It
reports syntax errors, unknown functions, undefined locals, and statically
detectable argument type mismatches without requiring Arma 3 to be running.

## Install

For an isolated command-line install:

```powershell
uv tool install armalint
```

For development from a checkout:

```powershell
uv sync
uv run armalint --version
```

## First lint

```powershell
armalint path\to\mission
```

See [Getting started](getting-started.md) for mission cache setup and
[CLI reference](cli.md) for all commands.
