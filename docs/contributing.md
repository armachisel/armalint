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

To work on the documentation locally:

```powershell
uv sync --extra docs
uv run mkdocs serve
```

Keep the rule documentation and `PLAN.md` in step with behavior changes. The
mod updater and the signature databases are particularly easy to misunderstand,
so explain where data came from and what the linter does when it cannot find
it.
