# Contributing

The project has no complicated build system. That is deliberate. Create an
environment with `uv`, run the checks, and build the same artefacts that CI
will build:

```powershell
uv sync
uv run python tests/run_all.py
uv build
```

The complete test runner includes the module self-tests and the command-line
fixtures. It also runs the counted parser/analysis case matrix in
`tests/analysis_cases.py`; add a named case there when you add a parser,
control-flow, scope, type, or suppression behavior. If you change a
diagnostic, add a small fixture or a focused module test that demonstrates the
case. Small examples are easier to reason about when a later change breaks
one.

Production regressions belong in `tests/corpus/`. Add a minimized SQF file and
an entry in `manifest.json` with the real-world context and diagnostic codes it
must continue to produce. The aggregate runner executes the corpus on every
change.

To work on the documentation locally:

```powershell
uv sync --extra docs
uv run mkdocs serve
```

Keep the rule documentation and `PLAN.md` in step with behavior changes. The
mod updater and the signature databases are particularly easy to misunderstand,
so explain where data came from and what the linter does when it cannot find
it.

## Adding a rule or analyzer

Give a diagnostic a stable `E###` or `W###` code and add its description to
`armalint/rules.py` and `docs/rules.md`. Prefer a focused regression case in
`tests/analysis_cases.py` or a module self-test. Run the full suite before
changing the expected count. Keep inference conservative: an unknown value is
usually safer than a warning based on a naming guess.

## Updating command and function data

The checked-in command names and typed XML snapshot are refreshed with
`armalint-update-commands`. The mission updater extracts base-game, DLC, and
selected mod functions into project-local caches. Do not commit mission cache
files. If extraction changes, document the source and update the relevant
metadata/provenance tests.

## Documentation and release checks

Build the strict documentation site and distributions locally:

```powershell
uv sync --extra docs
uv run mkdocs build --strict
uv build
```

The package workflow tests Python 3.9 and 3.13, builds both sdist and wheel,
checks bundled data, installs the wheel in an isolated environment, and runs
the CLI. The release workflow is manual; it validates artifacts and publishes
to PyPI only when its `publish` input is enabled.
