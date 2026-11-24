# SPDX-FileCopyrightText: 2026 Wellnizz contributors
# SPDX-License-Identifier: Apache-2.0
"""Reference monitor: the only path from a caller (CLI, MCP client, agent) to the data.

For every tool call it
1. checks that the tool exists and that every scope the tool declares was
   granted to the session,
2. runs the tool with the SQLite authorizer limited to the tables of the
   tool's declared scopes, observing which tables were actually read,
3. appends an allow/deny entry to the hash-linked log in the same SQLite
   transaction as the read, then updates the device witness.

A call whose log entry cannot be written returns nothing: no log entry, no data.
"""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Callable

from .ledger import GENESIS, DeviceKey, Witness, canonical, entry_hash, sha256_hex
from .store import ALL_SCOPES, Store, ToolContext, tables_for


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    scopes: tuple[str, ...]
    input_schema: dict
    fn: Callable[[sqlite3.Connection, dict], Any]


class Denied(Exception):
    def __init__(self, reason: str, seq: int):
        super().__init__(reason)
        self.reason = reason
        self.seq = seq


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds")


class Monitor:
    def __init__(self, store: Store, tools: dict[str, Tool], session: str, granted):
        bad = set(granted) - set(ALL_SCOPES)
        if bad:
            raise ValueError(f"unknown scopes: {sorted(bad)}")
        self.store = store
        self.tools = tools
        self.session = session
        self.granted = tuple(sorted(set(granted)))
        self.key = DeviceKey(store.home)
        self.witness = Witness(store.home, self.key)
        # Create the witness only for an empty log. A missing witness next to a
        # non-empty log is left missing so the verifier reports it.
        if self.witness.read() is None and self._head() == (0, GENESIS):
            self.witness.write(0, GENESIS)

    # -- log ----------------------------------------------------------------
    def _head(self) -> tuple[int, str]:
        row = self.store.conn.execute(
            "SELECT seq, entry_hash FROM access_log ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return (row[0], row[1]) if row else (0, GENESIS)

    def _append(self, *, tool: str, args: dict, declared, decision: str, reason: str,
                tables_read, result_sha256: str) -> tuple[int, str]:
        seq, prev = self._head()
        entry = {
            "seq": seq + 1,
            "ts": _now(),
            "session": self.session,
            "tool": tool,
            "args_json": canonical(args),
            "granted": canonical(list(self.granted)),
            "declared": canonical(sorted(declared)),
            "decision": decision,
            "reason": reason,
            "tables_read": canonical(sorted(tables_read)),
            "result_sha256": result_sha256,
            "prev_hash": prev,
        }
        entry["entry_hash"] = entry_hash(entry)
        cols = ", ".join(entry)
        marks = ", ".join("?" for _ in entry)
        self.store.conn.execute(f"INSERT INTO access_log ({cols}) VALUES ({marks})", tuple(entry.values()))
        return entry["seq"], entry["entry_hash"]

    def record_write(self, tool: str, args: dict, do_write: Callable[[sqlite3.Connection], Any]) -> Any:
        """Run a write (import) in system context and log it in the same transaction."""
        conn = self.store.conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            result = do_write(conn)
            head = self._append(tool=tool, args=args, declared=[], decision="write",
                                reason="owner import", tables_read=[],
                                result_sha256=sha256_hex(canonical(result)))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        self.witness.write(*head)
        return result

    # -- calls ----------------------------------------------------------------
    def call(self, name: str, args: dict | None = None) -> Any:
        args = dict(args or {})
        tool = self.tools.get(name)
        conn = self.store.conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            result = None
            if tool is None:
                decision, reason, declared, read = "deny", "unknown tool", [], set()
            elif not set(tool.scopes) <= set(self.granted):
                missing = sorted(set(tool.scopes) - set(self.granted))
                decision, reason, declared, read = "deny", f"scope not granted: {','.join(missing)}", tool.scopes, set()
            else:
                declared = tool.scopes
                ctx = ToolContext(allowed_tables=tables_for(tool.scopes))
                self.store.enter_tool(ctx)
                error = None
                try:
                    result = tool.fn(conn, args)
                except sqlite3.DatabaseError as exc:
                    error = exc
                except Exception as exc:  # noqa: BLE001 - every failure is logged as a denial
                    error = exc
                finally:
                    self.store.exit_tool()
                read = set(ctx.tables_read)
                if ctx.violations:
                    decision = "deny"
                    reason = "undeclared access blocked: " + ",".join(sorted(ctx.violations))
                    result = None
                elif error is not None:
                    decision, reason, result = "deny", f"tool error: {type(error).__name__}: {error}", None
                else:
                    decision, reason = "allow", "ok"
            result_hash = sha256_hex(canonical(result)) if decision == "allow" else GENESIS
            head = self._append(tool=name, args=args, declared=declared, decision=decision,
                                reason=reason, tables_read=read, result_sha256=result_hash)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        self.witness.write(*head)
        if decision != "allow":
            raise Denied(reason, head[0])
        return result

    def timed_call(self, name: str, args: dict | None = None) -> tuple[Any, float]:
        t0 = time.perf_counter()
        out = self.call(name, args)
        return out, time.perf_counter() - t0


def tool_result_json(result: Any) -> str:
    return json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False)
