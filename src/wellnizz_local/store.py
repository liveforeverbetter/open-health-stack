# SPDX-FileCopyrightText: 2026 Wellnizz contributors
# SPDX-License-Identifier: Apache-2.0
"""Local SQLite store and the table-level capability check (SQLite authorizer).

Every SQL statement is prepared with an authorizer callback. While a tool runs,
the authorizer only lets it read the tables that belong to the tool's declared
scopes, records every table it actually read, and denies everything else
(other tables, writes, ATTACH, PRAGMA). Statement caching is disabled so the
check runs on every execution, not only on first prepare.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL,          -- labs-csv | fhir-bundle | wearable-csv | vcf
    filename    TEXT NOT NULL,          -- base name only, never a full path
    sha256      TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    UNIQUE (sha256, kind)
);
CREATE TABLE IF NOT EXISTS lab_results (
    id           INTEGER PRIMARY KEY,
    source_id    INTEGER NOT NULL REFERENCES sources(id),
    collected_at TEXT NOT NULL,         -- ISO 8601 date
    loinc        TEXT,                  -- LOINC code if known
    name         TEXT NOT NULL,         -- display name as reported
    value        REAL NOT NULL,
    unit         TEXT NOT NULL,         -- UCUM-style unit string as reported
    ref_low      REAL,
    ref_high     REAL
);
CREATE INDEX IF NOT EXISTS ix_lab_name ON lab_results(name, collected_at);
CREATE TABLE IF NOT EXISTS wearable_daily (
    id        INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    day       TEXT NOT NULL,            -- ISO 8601 date
    metric    TEXT NOT NULL,            -- steps | sleep_minutes | hrv_rmssd_ms | resting_hr_bpm
    value     REAL NOT NULL,
    unit      TEXT NOT NULL,
    UNIQUE (day, metric, source_id)
);
CREATE INDEX IF NOT EXISTS ix_wear_metric ON wearable_daily(metric, day);
CREATE TABLE IF NOT EXISTS variants (
    id        INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    chrom     TEXT NOT NULL,            -- without 'chr' prefix
    pos       INTEGER NOT NULL,         -- 1-based, GRCh38
    rsid      TEXT,
    ref       TEXT NOT NULL,
    alt       TEXT NOT NULL,            -- one ALT allele per row
    genotype  TEXT NOT NULL             -- e.g. 0/1, 1/1, 0|1
);
CREATE INDEX IF NOT EXISTS ix_var_pos ON variants(chrom, pos);
CREATE TABLE IF NOT EXISTS access_log (
    seq            INTEGER PRIMARY KEY,
    ts             TEXT NOT NULL,
    session        TEXT NOT NULL,
    tool           TEXT NOT NULL,
    args_json      TEXT NOT NULL,
    granted        TEXT NOT NULL,       -- scopes the session was granted (JSON list)
    declared       TEXT NOT NULL,       -- scopes the tool declares (JSON list)
    decision       TEXT NOT NULL,       -- allow | deny | write
    reason         TEXT NOT NULL,
    tables_read    TEXT NOT NULL,       -- tables actually read, observed by the authorizer (JSON list)
    result_sha256  TEXT NOT NULL,
    prev_hash      TEXT NOT NULL,
    entry_hash     TEXT NOT NULL
);
"""

# Which tables each scope may read. The access_log, sources and meta tables
# are never readable by tools.
SCOPE_TABLES: dict[str, frozenset[str]] = {
    "labs": frozenset({"lab_results"}),
    "wearables": frozenset({"wearable_daily"}),
    "genome": frozenset({"variants"}),
}
ALL_SCOPES = tuple(SCOPE_TABLES)


def tables_for(scopes) -> frozenset[str]:
    out: set[str] = set()
    for s in scopes:
        out |= SCOPE_TABLES[s]
    return frozenset(out)


@dataclass
class ToolContext:
    """Authorizer state while one tool call runs."""

    allowed_tables: frozenset[str]
    tables_read: set[str] = field(default_factory=set)
    violations: set[str] = field(default_factory=set)


class Store:
    def __init__(self, home: Path | str):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.home, 0o700)
        except OSError:
            pass
        self.db_path = self.home / "store.db"
        self.conn = sqlite3.connect(
            self.db_path, cached_statements=0, isolation_level=None, check_same_thread=True
        )
        self.conn.executescript(SCHEMA)
        self.conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self._ctx: ToolContext | None = None
        self.conn.set_authorizer(self._authorize)

    # -- authorizer -------------------------------------------------------
    def _authorize(self, action, arg1, arg2, dbname, source):
        if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH):
            if self._ctx is not None:
                self._ctx.violations.add("attach")
            return sqlite3.SQLITE_DENY
        ctx = self._ctx
        if ctx is None:  # system context (imports, log writes, verifier)
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            if arg1 in ctx.allowed_tables:
                ctx.tables_read.add(arg1)
                return sqlite3.SQLITE_OK
            ctx.violations.add(f"read:{arg1}")
            return sqlite3.SQLITE_DENY
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, 33):  # 33 = SQLITE_RECURSIVE
            return sqlite3.SQLITE_OK
        ctx.violations.add(f"action:{action}:{arg1}")
        return sqlite3.SQLITE_DENY

    def enter_tool(self, ctx: ToolContext) -> None:
        self._ctx = ctx

    def exit_tool(self) -> None:
        self._ctx = None

    def close(self) -> None:
        self.conn.close()
