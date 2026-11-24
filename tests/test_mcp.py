# SPDX-FileCopyrightText: 2026 Wellnizz contributors
# SPDX-License-Identifier: Apache-2.0
import io
import json

from wellnizz_local.mcp_stdio import serve
from wellnizz_local.verify import verify_log


def _session(home, grant, messages):
    store_home = home
    out = io.StringIO()
    serve(store_home, grant, stdin=io.StringIO("\n".join(json.dumps(m) for m in messages) + "\n"), stdout=out)
    return [json.loads(line) for line in out.getvalue().splitlines()]


def test_mcp_initialize_list_and_scoped_calls(loaded):
    home, store, _ = loaded
    store.close()
    replies = _session(home, ["labs"], [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "lab_latest", "arguments": {"marker": "TSH"}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "genome_annotations", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 5, "method": "nope"},
    ])
    assert [r["id"] for r in replies] == [1, 2, 3, 4, 5]
    assert replies[0]["result"]["serverInfo"]["name"] == "wellnizz-local"
    tools = replies[1]["result"]["tools"]
    assert all(t["annotations"]["readOnlyHint"] and not t["annotations"]["destructiveHint"] for t in tools)
    assert replies[2]["result"]["isError"] is False
    assert replies[2]["result"]["structuredContent"]["marker"] == "TSH"
    assert replies[3]["result"]["isError"] is True and "scope not granted" in replies[3]["result"]["content"][0]["text"]
    assert replies[4]["error"]["code"] == -32601
    assert verify_log(home)["ok"]
