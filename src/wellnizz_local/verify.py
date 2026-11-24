# SPDX-FileCopyrightText: 2026 Wellnizz contributors
# SPDX-License-Identifier: Apache-2.0
"""Verifier the person runs on their own device.

It opens the store read-only and checks, without trusting the code that wrote the log:
- sequence numbers start at 1 and have no gaps,
- every entry's hash and back-link are correct (nothing edited, removed or reordered),
- the device witness is authentic and matches the last entry (no truncated tail, no
  forged appended entries, no rollback of the database alone),
- every allowed read touched only tables covered by the tool's declared scopes, and
  every declared scope had been granted to the session.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .ledger import GENESIS, DeviceKey, Witness, entry_hash
from .store import SCOPE_TABLES


def verify_log(home: Path | str) -> dict:
    home = Path(home)
    problems: list[str] = []
    db = home / "store.db"
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(access_log)")]
        rows = [dict(zip(cols, r)) for r in conn.execute("SELECT * FROM access_log ORDER BY seq")]
    finally:
        conn.close()

    counts = {"allow": 0, "deny": 0, "write": 0}
    prev = GENESIS
    expected_seq = 1
    for e in rows:
        s = e["seq"]
        if s != expected_seq:
            problems.append(f"sequence gap: expected {expected_seq}, found {s}")
            expected_seq = s
        if e["prev_hash"] != prev:
            problems.append(f"entry {s}: back-link does not match previous entry (removed, inserted or reordered)")
        if entry_hash(e) != e["entry_hash"]:
            problems.append(f"entry {s}: content does not match its hash (edited)")
        counts[e["decision"]] = counts.get(e["decision"], 0) + 1
        if e["decision"] == "allow":
            declared = set(json.loads(e["declared"]))
            granted = set(json.loads(e["granted"]))
            read = set(json.loads(e["tables_read"]))
            allowed = set().union(*(SCOPE_TABLES.get(sc, set()) for sc in declared)) if declared else set()
            if not declared <= granted:
                problems.append(f"entry {s}: allowed call used scopes that were not granted")
            if not read <= allowed:
                problems.append(f"entry {s}: allowed call read tables outside its declared scopes: {sorted(read - allowed)}")
        prev = e["entry_hash"]
        expected_seq += 1

    last_seq = rows[-1]["seq"] if rows else 0
    witness = Witness(home, DeviceKey(home)) if (home / "device.key").exists() else None
    body = witness.read() if witness else None
    if witness is None:
        problems.append("device key missing: cannot check the witness")
    elif body is None:
        problems.append("witness missing")
    elif not witness.valid(body):
        problems.append("witness MAC invalid (witness edited or wrong device key)")
    else:
        if body["seq"] < last_seq:
            problems.append(f"log has {last_seq - body['seq']} entries after the witnessed head (appended without the device key)")
        elif body["seq"] > last_seq:
            problems.append(f"log ends at {last_seq} but the witness says {body['seq']} (tail removed or database rolled back)")
        elif body["head"] != prev:
            problems.append("last entry does not match the witnessed head hash (log replaced or rewritten)")

    return {"ok": not problems, "entries": len(rows), "counts": counts, "head": prev, "problems": problems}
