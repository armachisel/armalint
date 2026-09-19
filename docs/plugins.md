# Project plugins

Projects can add local checks without changing Armalint. List Python plugin
files in `armalint.json`:

```json
{
  "plugins": ["tools/armalint_rules.py"]
}
```

Paths are resolved relative to the configuration file. A plugin defines a
`register(api)` function and registers checks with a project-owned rule code:

```python
from armalint.diagnostic import Diagnostic, Severity

def check_todo(source, filename):
    return [
        Diagnostic(Severity.WARNING, "W901", "TODO left in mission source", line, 1, filename)
        for line, text in enumerate(source.splitlines(), 1)
        if "TODO" in text
    ]

def register(api):
    api.register("W901", "warning", "TODO left in mission source", check_todo)
```

Plugin checks receive the complete source and filename and return diagnostics.
They participate in normal suppression, severity, JSON, SARIF, Checkstyle, and
exit-threshold handling. SARIF identifies plugin rules as `plugin` category
rules. Plugin loading or execution failures are reported as `E012`.

Keep plugins deterministic and side-effect free. They run during every lint
invocation and should not modify mission files or Armalint caches.
