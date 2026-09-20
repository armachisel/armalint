"""Small dependency-free MCP server for Armalint.

The server uses MCP's JSON-RPC messages over stdin/stdout and never mutates
mission caches. Cache updates remain the responsibility of ``armalint-update``.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from .argument_types import _COMMAND_ARITIES, _COMMAND_RETURN_TYPES
from .config import extract_dependencies, find_config, find_mod_cache, find_mod_type_cache, load_config_file
from .known import KNOWN_COMMANDS, KNOWN_FUNCTIONS
from .linter import build_symbol_index, lint_file, lint_text
from .mods import load_mod_cache, load_mod_type_cache, load_mod_metadata_cache, expand_core_function_aliases, MOD_METADATA_CACHE_FILENAME
from .rules import metadata as rule_metadata

PROTOCOL_VERSION = "2024-11-05"
SERVER_VERSION = "0.1.0"

TOOLS = [
    {"name": "lint_sqf", "description": "Lint SQF text without changing files or caches.", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}, "filename": {"type": "string"}, "mission": {"type": "string"}}, "required": ["text"]}},
    {"name": "lint_path", "description": "Lint one mission file or directory using its project configuration.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "mission": {"type": "string"}}, "required": ["path"]}},
    {"name": "lookup_command", "description": "Look up a built-in SQF command and its known metadata.", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "lookup_function", "description": "Look up a built-in, mission, or extracted mod function.", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "mission": {"type": "string"}}, "required": ["name"]}},
    {"name": "list_rules", "description": "Return Armalint's stable rule catalog.", "inputSchema": {"type": "object", "properties": {}}},
]


def _result(value: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(value, sort_keys=True)}], "structuredContent": value}


def _diagnostics(items) -> list[dict[str, Any]]:
    return [{"file": d.file, "line": d.line, "column": d.column, "severity": d.severity.value, "code": d.code, "message": d.message, **({"relatedLocations": d.related_locations} if d.related_locations else {})} for d in items]


def _context(mission: str | None):
    root = os.path.abspath(mission) if mission else None
    config_path = find_config(root) if root else None
    config = load_config_file(config_path) if config_path else {}
    cache = find_mod_cache(root) if root else None
    type_cache = find_mod_type_cache(root) if root else None
    index = None
    if root and os.path.isdir(root):
        files = []
        for current, _dirs, names in os.walk(root):
            files.extend(os.path.join(current, n) for n in names if n.lower().endswith((".sqf", ".hpp", ".ext")))
        index = build_symbol_index(sorted(files))
        index.cba_declared |= any(dep.startswith("cba_") for dep in extract_dependencies(config))
    if cache:
        from .symbols import SymbolIndex
        index = index or SymbolIndex()
        for name in expand_core_function_aliases(load_mod_cache(cache)): index.add_function(name)
    signatures = load_mod_type_cache(type_cache) if type_cache else {}
    metadata_path = os.path.join(os.path.dirname(type_cache), MOD_METADATA_CACHE_FILENAME) if type_cache else None
    metadata = load_mod_metadata_cache(metadata_path) if metadata_path else {}
    return root, config, index, signatures, metadata


def _command_metadata(name: str) -> dict[str, Any]:
    """Read the vendored command metadata without making network requests."""
    path = os.path.join(os.path.dirname(__file__), "data", "command_metadata.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        item = data.get("commands", {}).get(name)
        return item if isinstance(item, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "list_rules":
        return _result({"schema": 1, "rules": rule_metadata()})
    if name == "lookup_command":
        command = str(arguments.get("name", "")).strip().lower()
        details = _command_metadata(command)
        return _result({"schema": 1, "name": command, "known": command in KNOWN_COMMANDS, "arities": sorted(_COMMAND_ARITIES.get(command, ())), "returnType": _COMMAND_RETURN_TYPES.get(command), "metadata": details or None, "provenance": "vendored command metadata" if details else None, "confidence": "high" if details else "baseline"})
    if name == "lookup_function":
        function = str(arguments.get("name", "")).strip().lower()
        _root, _config, index, signatures, metadata = _context(arguments.get("mission"))
        known = function in KNOWN_FUNCTIONS or bool(index and index.is_known_function(function))
        details = metadata.get("functions", {}).get(function, {}) if isinstance(metadata, dict) else {}
        details = dict(details) if isinstance(details, dict) else {}
        if details and not details.get("source"):
            details["source"] = metadata.get("signature_sources", {}).get(function)
        return _result({"schema": 1, "name": function, "known": known, "signature": signatures.get(function), "metadata": details or None, "source": details.get("source") if details else ("builtin" if function in KNOWN_FUNCTIONS else None), "provenance": details.get("provenance") if details else ("builtin registry" if function in KNOWN_FUNCTIONS else None), "confidence": details.get("confidence", "baseline") if details else "baseline"})
    if name == "lint_sqf":
        text = arguments.get("text")
        if not isinstance(text, str): raise ValueError("text must be a string")
        _root, config, index, signatures, _metadata = _context(arguments.get("mission"))
        diagnostics = lint_text(text, str(arguments.get("filename") or "<snippet>"), index, signatures, ignored_rules=set(), rule_severities=None)
        return _result({"schema": 1, "diagnostics": _diagnostics(diagnostics)})
    if name == "lint_path":
        path = os.path.abspath(str(arguments.get("path", "")))
        if not os.path.exists(path): raise ValueError("path does not exist")
        mission = arguments.get("mission") or (path if os.path.isdir(path) else os.path.dirname(path))
        _root, config, index, signatures, _metadata = _context(mission)
        files = [path] if os.path.isfile(path) else sorted(os.path.join(root, n) for root, _dirs, names in os.walk(path) for n in names if n.lower().endswith(".sqf"))
        diagnostics = [d for file in files for d in lint_file(file, index, signatures)]
        return _result({"schema": 1, "path": path, "diagnostics": _diagnostics(diagnostics), "files": len(files)})
    raise ValueError(f"unknown tool: {name}")


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    if method == "notifications/initialized": return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}}, "serverInfo": {"name": "armalint", "version": SERVER_VERSION}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        try:
            params = message.get("params", {})
            return {"jsonrpc": "2.0", "id": request_id, "result": call_tool(params.get("name", ""), params.get("arguments") or {})}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": str(exc)}}
    if request_id is not None:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return None


def main() -> int:
    for line in sys.stdin:
        try:
            response = handle(json.loads(line))
            if response is not None:
                print(json.dumps(response, separators=(",", ":")), flush=True)
        except Exception as exc:
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
