# Release notes

## 0.1.0

The initial release provides a dependency-free Arma 3 SQF linter with syntax,
control-flow, undefined-variable, command, function, and conservative static
type checks. It includes mission-specific indexing for base-game, DLC, and mod
functions; incremental scan caches; JSON and SARIF output; configurable rule
suppression and severity; optional style checks; and a read-only stdio MCP
server for editor and agent integrations.

The package is distributed as a wheel and source archive. `uv tool install`
is the recommended Windows installation path.
