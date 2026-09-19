"""Minimal dependency-free Language Server Protocol adapter for Armalint.

It supports full-text document synchronization and publishes diagnostics after
``didOpen`` and ``didChange``. The implementation deliberately keeps the
transport small so it can run through ``stdio`` in any editor.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from .linter import lint_text


def _path(uri: str) -> str:
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        value = unquote(parsed.path)
        if len(value) >= 3 and value[0] == "/" and value[2] == ":":
            value = value[1:]
        return str(Path(value))
    return uri


def _severity(value: str) -> int:
    return {"error": 1, "warning": 2, "info": 3}.get(value, 2)


class Server:
    def __init__(self) -> None:
        self.documents: dict[str, str] = {}
        self.shutdown_requested = False

    def _response(self, request_id, result) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _publish(self, uri: str) -> dict:
        text = self.documents.get(uri, "")
        filename = _path(uri)
        diagnostics = lint_text(text, filename=filename)
        return {
            "jsonrpc": "2.0",
            "method": "textDocument/publishDiagnostics",
            "params": {
                "uri": uri,
                "diagnostics": [
                    {
                        "range": {
                            "start": {"line": max(0, d.line - 1), "character": max(0, d.column - 1)},
                            "end": {"line": max(0, d.line - 1), "character": max(0, d.column)},
                        },
                        "severity": _severity(d.severity.value),
                        "code": d.code,
                        "source": "armalint",
                        "message": d.message,
                    }
                    for d in diagnostics
                ],
            },
        }

    def handle(self, message: dict) -> tuple[dict | None, list[dict]]:
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}
        notifications: list[dict] = []
        if method == "initialize":
            return self._response(request_id, {
                "capabilities": {
                    "textDocumentSync": {"openClose": True, "change": 1},
                },
                "serverInfo": {"name": "armalint", "version": "0.1.0"},
            }), notifications
        if method == "shutdown":
            self.shutdown_requested = True
            return self._response(request_id, None), notifications
        if method == "exit":
            return None, notifications
        if method == "textDocument/didOpen":
            document = params.get("textDocument", {})
            uri = str(document.get("uri", ""))
            self.documents[uri] = str(document.get("text", ""))
            notifications.append(self._publish(uri))
            return None, notifications
        if method == "textDocument/didChange":
            document = params.get("textDocument", {})
            uri = str(document.get("uri", ""))
            changes = params.get("contentChanges") or []
            if changes and isinstance(changes[-1], dict) and "text" in changes[-1]:
                self.documents[uri] = str(changes[-1]["text"])
            notifications.append(self._publish(uri))
            return None, notifications
        if method == "textDocument/didClose":
            document = params.get("textDocument", {})
            uri = str(document.get("uri", ""))
            self.documents.pop(uri, None)
            notifications.append({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics", "params": {"uri": uri, "diagnostics": []}})
            return None, notifications
        if request_id is not None:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"method not found: {method}"}}, notifications
        return None, notifications


def _read_message(stream) -> dict | None:
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            return None
        line = line.decode("ascii", "replace").strip()
        if not line:
            break
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    body = stream.read(length)
    return json.loads(body.decode("utf-8"))


def _write_message(stream, message: dict) -> None:
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    stream.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
    stream.flush()


def main() -> int:
    server = Server()
    while True:
        message = _read_message(sys.stdin.buffer)
        if message is None:
            return 0
        response, notifications = server.handle(message)
        if response is not None:
            _write_message(sys.stdout.buffer, response)
        for notification in notifications:
            _write_message(sys.stdout.buffer, notification)
        if message.get("method") == "exit":
            return 0 if server.shutdown_requested else 1


if __name__ == "__main__":
    raise SystemExit(main())
