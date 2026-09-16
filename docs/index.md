# Armalint

Armalint is a linter for Arma 3 SQF missions and scripts. It started with the
fairly unambitious goal of catching the mistakes that are easy to make and
annoying to find in game: one missing bracket, a forgotten comma, or a function
name that is almost right.

It has grown from there. It now checks a small amount of control flow and type
information, and it can read function information from the base game, DLC, and
installed mods. It is still a static checker. When the type of an expression
cannot be worked out safely, it leaves it alone. That is generally more useful
than confidently reporting nonsense.

## Install

For an isolated command-line install:

```powershell
uv tool install armalint
```

From a checkout, use:

```powershell
uv sync
uv run armalint --version
```

## First lint

```powershell
armalint C:\path\to\mission
```

The [getting started guide](getting-started.md) covers the first mission scan.
The [CLI reference](cli.md) has the options, and [rules and analysis](rules.md)
explains what the diagnostics mean.
