# Contributing

Create an environment and run the complete checks with `uv`:

```powershell
uv sync
uv run python tests/run_all.py
```

Build the package locally:

```powershell
uv build
```

Build the documentation site:

```powershell
uv sync --extra docs
uv run mkdocs serve
```

Keep new diagnostics covered by focused fixtures or module self-tests. Update
the rule documentation and `PLAN.md` when behavior or project workflows
change.
