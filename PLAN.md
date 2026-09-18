# Armalint roadmap

This roadmap is ordered by impact on correctness and false-positive reduction.

## Priority 1: parser and control flow

- [x] Add an AST/control-flow foundation while retaining the current token passes.
- [x] Add conservative unreachable-code diagnostics after unconditional terminators.
- [x] Parse expressions, statements, blocks, `if`/`else`, loops, `switch`, and `exitWith` with source spans.
- [x] Make undefined-variable analysis scope-aware and merge definitions across branches.
- [x] Add unreachable-code diagnostics after `exitWith`, `throw`, `breakOut`, and `continue`.
- [x] Replace heuristic statement-boundary checks with AST statement termination rules.
- [x] Model `private`, `params`, loop variables, and nested code blocks as lexical scopes.

## Priority 2: semantic and type analysis

- [x] Expand built-in command signatures, arity metadata, and return types.
- [x] Infer types through arithmetic, comparisons, array operations, `select`, and namespace access.
- [x] Check statically known mission/mod function argument counts and types for `call` and `spawn`.
- [x] Distinguish unary, binary, and nular command usage using command metadata.
- [x] Detect calls to values that are known not to contain code.
- [x] Report duplicate function definitions, suspicious overwrites, and constant conditions.
- [x] Report unused locals conservatively across include and nested-scope boundaries.

## Priority 3: preprocessor and config coverage

- [ ] Add include-guard diagnostics; object-like macro substitution, conditional compilation, and nested includes are supported.
- [x] Make CfgFunctions inheritance and custom `file` mappings fully parser-based.
- [ ] Improve callback discovery through event handlers and namespace variables.

## Priority 4: registry and updater quality

- [ ] Generate built-in, DLC, and mod signatures with versioned metadata.
- [x] Invalidate scan caches when the extractor/parser schema changes.
- [x] Remove stale functions when addons disappear; source-root provenance is recorded in the scan cache.
- [x] Report reused versus rescanned roots.
- [ ] Include Arma-version metadata, per-function source-PBO provenance, and unreadable/unsupported PBO diagnostics.

## Priority 5: developer-facing linter features

- [x] Add inline rule suppression and per-project severity configuration.
- [x] Add ignore patterns for generated files/directories.
- [x] Add stable JSON/SARIF rule metadata and diagnostic deduplication.
- [x] Add optional style rules for naming, whitespace, line length, and bracket style.

## Priority 6: packaging and distribution

- [ ] Adopt the modern PEP 621 `pyproject.toml` layout with Hatchling (or
  another standard backend only if needed), explicit Python version
  requirements, and console-script entry points for `armalint` and its
  updater.
- [ ] Use `uv` as the project and dependency-management frontend for fast,
  reproducible environments, locking, test commands, and build orchestration;
  commit the lockfile and document the supported install and upgrade commands.
- [ ] Build and validate source and wheel distributions in CI, including a
  clean-install smoke test that runs the CLI and updater.
- [ ] Publish versioned releases to the appropriate package index with release
  notes, while keeping the extracted Arma/mod signature databases outside the
  wheel and downloading or generating them through an explicit update command.
- [ ] Provide a practical Windows distribution path (pip/uv install first,
  with a standalone executable considered if the dependency footprint or user
  environment makes it worthwhile).
- [ ] Add package metadata, license/readme inclusion, typed package data, and
  an automated compatibility matrix for supported Python versions.

## Priority 7: documentation and project communication

- [ ] Create a contributor and user documentation set covering installation,
  CLI usage, mission updates, cache management, configuration, diagnostics,
  signature extraction, and troubleshooting.
- [ ] Keep a concise README as the landing page, with the full documentation
  in a `docs/` tree and examples that can be copied and run on Windows.
- [ ] Document the rule catalog, severity model, JSON output, supported Arma
  data sources, and the limits of static type/control-flow analysis.
- [ ] Add contributor guidance for tests, packaging, updater changes, adding
  command/function signatures, and release procedures.
- [ ] Build the site with MkDocs (Material theme can be evaluated during
  implementation) and deploy it from GitHub Actions to GitHub Pages. Keep the
  source Markdown and build configuration in this repository so the site can
  later move to another static host without rewriting the docs.
- [ ] Add documentation checks and link validation to CI, and publish versioned
  release notes alongside package releases.

## Priority 8: editor and agent integration

- [ ] Expose Armalint through a standard MCP server usable by Claude and other
  MCP clients. The initial read-only tools should include:
  - lint SQF text and return structured diagnostics with file/line/column data;
  - lint a mission file or directory using its discovered project config;
  - look up whether a command or function name is known;
  - look up extracted mission/mod function signatures and source addons.
- [ ] Support stdio transport first, with clear setup instructions for Claude
  Desktop and other local MCP hosts.
- [ ] Keep MCP calls isolated from cache mutation by default; expose updating
  or cache-clearing as separate explicitly named operations if needed.
- [ ] Version the MCP response schema and include rule codes, severity, and
  actionable messages so clients can present or auto-fix diagnostics safely.
- [ ] Extract useful function metadata where it is available locally:
  - descriptions/documentation fields from `CfgFunctions` and `CfgPatches`;
  - leading comments or docblocks immediately preceding function source files;
  - source addon/PBO, file path, preInit/postInit flags, and required addons.
- [ ] Return that metadata through MCP so Claude can explain functions, suggest
  likely alternatives, and provide context for type warnings.
- [ ] Mark metadata provenance and confidence; missing descriptions are normal
  for compiled engine functions and many mod functions.
