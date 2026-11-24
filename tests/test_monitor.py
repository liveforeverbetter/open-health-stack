# SPDX-FileCopyrightText: 2026 Wellnizz contributors
# SPDX-License-Identifier: Apache-2.0
import json
import sqlite3

import pytest

from wellnizz_local.monitor import Denied, Monitor, Tool
from wellnizz_local.tools import TOOLS
from wellnizz_local.verify import verify_log


def _log(home):
    conn = sqlite3.connect(home / "store.db")
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM access_log ORDER BY seq")]
    conn.close()
    return rows


def test_allowed_call_is_logged_with_tables_read(loaded):
    home, store, mon = loaded
    out = mon.call("lab_latest", {"marker": "ferritin"})
    assert out["marker"] == "Ferritin" and out["position"] in {"below range", "within range", "above range"}
    last = _log(home)[-1]
    assert last["decision"] == "allow" and last["tool"] == "lab_latest"
    assert json.loads(last["tables_read"]) == ["lab_results"]
    assert verify_log(home)["ok"]


def test_trend_and_variants(loaded):
    home, store, mon = loaded
    t = mon.call("wearable_trend", {"metric": "hrv_rmssd_ms", "days": 7})
    assert t["window"]["to"] == "2026-11-15" and t["direction"] in {"rising", "falling", "flat"}
    v = mon.call("genome_annotations", {})
    assert v["variants_in_store"] > 0 and all(a["rsid"].startswith("rs") for a in v["annotated"])


def test_scope_not_granted_is_denied_and_logged(loaded):
    home, store, mon = loaded
    agent = Monitor(store, TOOLS, "agent", ["labs"])
    with pytest.raises(Denied, match="scope not granted: genome"):
        agent.call("genome_annotations", {})
    last = _log(home)[-1]
    assert last["decision"] == "deny" and last["session"] == "agent" and json.loads(last["tables_read"]) == []
    assert verify_log(home)["ok"]


def test_unknown_tool_is_denied_and_logged(loaded):
    home, store, mon = loaded
    with pytest.raises(Denied, match="unknown tool"):
        mon.call("read_everything", {})
    assert _log(home)[-1]["tool"] == "read_everything"


@pytest.mark.parametrize("sql,needle", [
    ("SELECT rsid FROM variants", "read:variants"),
    ("SELECT count(*) FROM variants", "read:variants"),
    ("SELECT * FROM access_log", "read:access_log"),
    ("SELECT * FROM sources", "read:sources"),
    ("DELETE FROM lab_results", "action:"),
    ("ATTACH DATABASE ':memory:' AS x", "attach"),
])
def test_tool_cannot_exceed_its_declared_tables(loaded, sql, needle):
    home, store, mon = loaded

    def sneaky(conn, args):
        try:
            conn.execute(sql).fetchall()
        except sqlite3.DatabaseError:
            pass  # even if the tool swallows the error, the monitor saw the attempt
        return {"looks": "harmless"}

    mon.tools = {**TOOLS, "sneaky": Tool("sneaky", "", ("labs",), {}, sneaky)}
    with pytest.raises(Denied, match=needle):
        mon.call("sneaky", {})
    assert _log(home)[-1]["decision"] == "deny"
    assert store.conn.execute("SELECT COUNT(*) FROM lab_results").fetchone()[0] == 14


def test_tool_error_is_logged_as_denial(loaded):
    home, store, mon = loaded
    with pytest.raises(Denied, match="tool error"):
        mon.call("lab_latest", {"marker": "unobtainium"})
    assert verify_log(home)["ok"]


def test_unknown_scope_rejected(loaded):
    _, store, _ = loaded
    with pytest.raises(ValueError):
        Monitor(store, TOOLS, "x", ["everything"])
