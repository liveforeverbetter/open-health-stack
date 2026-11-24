# SPDX-FileCopyrightText: 2026 Wellnizz contributors
# SPDX-License-Identifier: Apache-2.0
import ast
import socket
from pathlib import Path

import pytest

from wellnizz_local import offline
from wellnizz_local.cli import main

SRC = Path(__file__).resolve().parents[1] / "src" / "wellnizz_local"
FORBIDDEN = {"socket", "ssl", "urllib", "http", "requests", "httpx", "aiohttp", "ftplib", "smtplib",
             "subprocess", "ctypes", "multiprocessing", "asyncio", "webbrowser", "xmlrpc"}


def test_source_imports_no_network_or_process_modules():
    found = []
    for py in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(py.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            found += [f"{py.name}:{n}" for n in names if n.split(".")[0] in FORBIDDEN]
    assert found == []


def test_guard_blocks_and_records_socket_use():
    before = len(offline.attempts())
    with pytest.raises(offline.NetworkBlocked):
        socket.create_connection(("127.0.0.1", 9), timeout=0.1)
    assert len(offline.attempts()) > before
    offline.reset_attempts()


def test_full_demo_makes_no_network_attempts(tmp_path, capsys):
    offline.reset_attempts()
    rc = main(["--home", str(tmp_path / "h"), "demo", "--out", str(tmp_path / "out"), "--sessions", "40"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "network/process attempts blocked during run: 0" in out
    assert offline.attempts() == []
