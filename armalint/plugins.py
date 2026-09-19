"""Project-defined lint checks.

Plugins are ordinary Python files listed in ``armalint.json`` under
``plugins``. A plugin exposes ``register(api)`` and calls
``api.register("W901", "warning", "Description", check)``. ``check`` receives
``(source, filename)`` and returns :class:`Diagnostic` objects or dictionaries
with matching fields.
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from types import ModuleType
from typing import Callable, Iterable

from .diagnostic import Diagnostic, Severity


@dataclass
class PluginRule:
    code: str
    severity: str
    description: str
    check: Callable[[str, str], Iterable[Diagnostic]]


class PluginAPI:
    def __init__(self) -> None:
        self.rules: list[PluginRule] = []

    def register(self, code: str, severity: str, description: str, check: Callable) -> None:
        normalized = str(code).upper()
        if not normalized or not callable(check) or severity not in {"error", "warning", "info"}:
            raise ValueError("plugin rules require an E/W code, valid severity, description, and callable check")
        self.rules.append(PluginRule(normalized, severity, str(description), check))


def load_plugins(paths: Iterable[str], base_dir: str = "") -> tuple[list[PluginRule], list[str]]:
    rules: list[PluginRule] = []
    errors: list[str] = []
    for raw_path in paths:
        path = raw_path if os.path.isabs(raw_path) else os.path.join(base_dir, raw_path)
        path = os.path.abspath(path)
        try:
            spec = importlib.util.spec_from_file_location(f"armalint_plugin_{len(rules)}", path)
            if spec is None or spec.loader is None:
                raise OSError("could not create an import spec")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            api = PluginAPI()
            register = getattr(module, "register", None)
            if callable(register):
                register(api)
            declared = getattr(module, "RULES", {})
            if isinstance(declared, dict):
                for code, definition in declared.items():
                    if isinstance(definition, dict):
                        api.register(code, definition.get("severity", "warning"), definition.get("description", str(code)), definition["check"])
            rules.extend(api.rules)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    return rules, errors


def run_plugin_checks(source: str, filename: str, rules: Iterable[PluginRule]) -> tuple[list[Diagnostic], list[str]]:
    diagnostics: list[Diagnostic] = []
    errors: list[str] = []
    for rule in rules:
        try:
            result = rule.check(source, filename)
            for item in result or ():
                if isinstance(item, Diagnostic):
                    diagnostic = item
                elif isinstance(item, dict):
                    diagnostic = Diagnostic(
                        Severity(str(item.get("severity", rule.severity))),
                        str(item.get("code", rule.code)), str(item.get("message", rule.description)),
                        int(item.get("line", 1)), int(item.get("column", 1)), str(item.get("file", filename)),
                    )
                else:
                    continue
                if not diagnostic.file:
                    diagnostic.file = filename
                if not diagnostic.code:
                    diagnostic.code = rule.code
                diagnostics.append(diagnostic)
        except Exception as exc:
            errors.append(f"{rule.code}: {exc}")
    return diagnostics, errors
