# SPDX-FileCopyrightText: 2026 Wellnizz contributors
# SPDX-License-Identifier: Apache-2.0
"""Minimal Model Context Protocol server over stdio (JSON-RPC 2.0, one message per line).

No sockets: the client starts this process and talks to it through stdin and
stdout. Every tools/call goes through the reference monitor, so the session's
scope grant (``--grant``) is enforced and every call, allowed or denied, is
in the hash-linked log. Tools are read-only and annotated as such.
"""

from __future__ import annotations

import json
import sys
import uuid

from . import __version__
from .monitor import Denied, Monitor
from .store import Store
from .tools import TOOLS

PROTOCOL_VERSION = "2025-06-18"


def _tool_list(granted) -> list[dict]:
    out = []
    for t in TOOLS.values():
        out.append({
            "name": t.name,
            "title": t.name.replace("_", " ").capitalize(),
            "description": f"{t.description} Requires scope(s): {', '.join(t.scopes)}."
                           + ("" if set(t.scopes) <= set(granted) else " (not granted in this session)"),
            "inputSchema": t.input_schema,
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True,
                            "openWorldHint": False},
        })
    return out


def handle(monitor: Monitor, msg: dict) -> dict | None:
    mid = msg.get("id")
    method = msg.get("method")
    if mid is None:  # notification
        return None
    if method == "initialize":
        result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "wellnizz-local", "version": __version__},
                  "instructions": "Local, read-only health data tools on synthetic or user-imported data. "
                                  "Educational, not medical advice. Every call is logged."}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": _tool_list(monitor.granted)}
    elif method == "tools/call":
        params = msg.get("params") or {}
        try:
            data = monitor.call(str(params.get("name")), params.get("arguments") or {})
            result = {"content": [{"type": "text", "text": json.dumps(data, sort_keys=True)}],
                      "structuredContent": data, "isError": False}
        except Denied as d:
            result = {"content": [{"type": "text", "text": f"Denied and logged (entry {d.seq}): {d.reason}"}],
                      "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(home, granted, stdin=None, stdout=None) -> None:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    store = Store(home)
    monitor = Monitor(store, TOOLS, f"mcp-{uuid.uuid4().hex[:12]}", granted)
    try:
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
            else:
                reply = handle(monitor, msg)
            if reply is not None:
                stdout.write(json.dumps(reply) + "\n")
                stdout.flush()
    finally:
        store.close()
