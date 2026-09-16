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

For a mission that uses only built-in Arma commands, you can lint immediately.
For a useful check of mission and mod functions, build the mission's index
first:

```powershell
armalint-update --mission C:\path\to\mission
```

This reads the mission's required addons and scans the matching installed
Arma data, DLC data, and mod data. That includes the built-in functions defined
by the game's `CfgFunctions`, not just functions supplied by Workshop mods.
It writes the exact function names and any signatures it can extract beside
the mission configuration. That lets Armalint distinguish a real function
from a misspelling and perform more argument checks.

```powershell
armalint C:\path\to\mission
```

The [getting started guide](getting-started.md) covers the full setup,
including explicit Arma and Workshop paths when automatic discovery cannot
find them. The [function index guide](indexes.md) explains what is stored and
why each mission has its own index. The [CLI reference](cli.md) has the
options, and [rules and analysis](rules.md) explains the diagnostics.
