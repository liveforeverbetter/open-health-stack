# SPDX-FileCopyrightText: 2026 Wellnizz contributors
# SPDX-License-Identifier: Apache-2.0
"""Command-line interface: wellnizz-local (or python -m wellnizz_local)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__, offline
from .export import export_store, verify_export
from .importer import KINDS, import_file
from .monitor import Denied, Monitor
from .store import ALL_SCOPES, Store
from .tools import TOOLS
from .verify import verify_log

DEFAULT_HOME = os.environ.get("WELLNIZZ_HOME", str(Path.home() / ".wellnizz-local"))


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False))


def _owner(home: str) -> tuple[Store, Monitor]:
    store = Store(home)
    return store, Monitor(store, TOOLS, "cli-owner", ALL_SCOPES)


def _scopes(text: str) -> list[str]:
    out = [s.strip() for s in text.split(",") if s.strip()]
    bad = [s for s in out if s not in ALL_SCOPES]
    if bad:
        raise argparse.ArgumentTypeError(f"unknown scope(s) {bad}; choose from {list(ALL_SCOPES)}")
    return out


def cmd_demo(args) -> int:
    """One command that rebuilds every result from synthetic data."""
    from .redteam import run
    from .synth import generate

    out = Path(args.out)
    if out.exists() and any(out.iterdir()) and not args.force:
        print(f"{out} is not empty; pass --force to overwrite", file=sys.stderr)
        return 2
    import shutil
    shutil.rmtree(out, ignore_errors=True)
    files = generate(out / "synthetic", seed=args.seed)
    store, mon = _owner(str(out / "store"))
    imports = [import_file(mon, p) for p in files.values()]
    answers = {
        "latest_ferritin": mon.call("lab_latest", {"marker": "Ferritin"}),
        "hrv_7_day_trend": mon.call("wearable_trend", {"metric": "hrv_rmssd_ms", "days": 7}),
        "genome_annotations": mon.call("genome_annotations", {}),
    }
    agent = Monitor(store, TOOLS, "demo-agent-labs-only", ["labs"])
    try:
        agent.call("genome_annotations", {})
    except Denied as d:
        answers["agent_without_genome_scope"] = {"denied": True, "reason": d.reason, "log_entry": d.seq}
    manifest = export_store(mon, out / "export")
    store.close()
    report = {
        "wellnizz_local": __version__,
        "seed": args.seed,
        "imports": imports,
        "answers": answers,
        "log_verification": verify_log(out / "store"),
        "export_manifest": manifest,
        "export_verification": verify_export(out / "export", out / "store"),
    }
    (out / "demo_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8")
    rt = run(n_sessions=args.sessions, seed=args.seed)
    (out / "redteam_report.json").write_text(json.dumps(rt, indent=2, sort_keys=True) + "\n", "utf-8")
    attempts = offline.attempts()
    print(f"demo report:     {out / 'demo_report.json'}")
    print(f"red-team report: {out / 'redteam_report.json'}")
    print(f"log verified:    {report['log_verification']['ok']} ({report['log_verification']['entries']} entries)")
    print(f"export verified: {report['export_verification']['ok']}")
    print(f"red-team claim:  {rt['claim']}")
    for k, v in rt["attacks"].items():
        print(f"  {k:<16} {v['detected']:>3}/{v['n']:<3} detected   expected: {v['expected']}")
    print(f"  benign sessions: {rt['benign']['n']}, false positives: {rt['benign']['false_positives']}")
    print(f"network/process attempts blocked during run: {len(attempts)}")
    ok = report["log_verification"]["ok"] and report["export_verification"]["ok"] and rt["claim_holds"] and not attempts
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="wellnizz-local", description=(
        "Local-first personal health data store with a verifiable access log. "
        "Educational, not medical advice."))
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--home", default=DEFAULT_HOME, help="store directory (default: $WELLNIZZ_HOME or ~/.wellnizz-local)")
    p.add_argument("--allow-network", action="store_true",
                   help="do not install the offline guard (nothing in this tool needs the network)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("synth", help="write synthetic sample files")
    s.add_argument("out")
    s.add_argument("--seed", type=int, default=7)

    s = sub.add_parser("import", help="import a lab CSV, FHIR bundle, wearable CSV or VCF")
    s.add_argument("file")
    s.add_argument("--kind", choices=sorted(KINDS))

    s = sub.add_parser("markers", help="list lab markers")
    s = sub.add_parser("latest", help="latest result for a lab marker vs its reported range")
    s.add_argument("marker")
    s = sub.add_parser("trend", help="trend of a daily wearable metric")
    s.add_argument("metric")
    s.add_argument("--days", type=int, default=7)
    sub.add_parser("variants", help="annotated variants from the bundled reference set")

    s = sub.add_parser("log", help="show the access log")
    s.add_argument("--tail", type=int, default=20)
    sub.add_parser("verify", help="verify the access log against the device witness")

    s = sub.add_parser("export", help="export everything with a hash manifest")
    s.add_argument("out")
    s = sub.add_parser("verify-export", help="check an export's manifest")
    s.add_argument("dir")

    s = sub.add_parser("serve-mcp", help="MCP server over stdio for a scoped session")
    s.add_argument("--grant", type=_scopes, required=True, help=f"comma list of scopes from {list(ALL_SCOPES)}")

    s = sub.add_parser("redteam", help="run the red-team suite on synthetic data")
    s.add_argument("--sessions", type=int, default=200)
    s.add_argument("--seed", type=int, default=7)

    s = sub.add_parser("demo", help="rebuild all results from synthetic data (one command)")
    s.add_argument("--out", default="results")
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--sessions", type=int, default=200)
    s.add_argument("--force", action="store_true")

    a = p.parse_args(argv)
    if not a.allow_network:
        offline.enable()

    try:
        if a.cmd == "synth":
            from .synth import generate
            for k, v in generate(a.out, a.seed).items():
                print(f"{k}: {v}")
            return 0
        if a.cmd == "demo":
            return cmd_demo(a)
        if a.cmd == "redteam":
            from .redteam import run
            rep = run(a.sessions, a.seed)
            _print(rep)
            return 0 if rep["claim_holds"] else 1
        if a.cmd == "verify":
            rep = verify_log(a.home)
            _print(rep)
            return 0 if rep["ok"] else 1
        if a.cmd == "verify-export":
            rep = verify_export(Path(a.dir), Path(a.home))
            _print(rep)
            return 0 if rep["ok"] else 1
        if a.cmd == "serve-mcp":
            from .mcp_stdio import serve
            serve(a.home, a.grant)
            return 0
        if a.cmd == "log":
            import sqlite3
            conn = sqlite3.connect(f"file:{Path(a.home) / 'store.db'}?mode=ro", uri=True)
            rows = conn.execute(
                "SELECT seq, ts, session, tool, decision, reason, tables_read FROM access_log ORDER BY seq DESC LIMIT ?",
                (a.tail,)).fetchall()
            conn.close()
            for r in reversed(rows):
                print(" | ".join(str(x) for x in r))
            return 0

        store, mon = _owner(a.home)
        try:
            if a.cmd == "import":
                _print(import_file(mon, Path(a.file), a.kind))
            elif a.cmd == "markers":
                _print(mon.call("lab_markers", {}))
            elif a.cmd == "latest":
                _print(mon.call("lab_latest", {"marker": a.marker}))
            elif a.cmd == "trend":
                _print(mon.call("wearable_trend", {"metric": a.metric, "days": a.days}))
            elif a.cmd == "variants":
                _print(mon.call("genome_annotations", {}))
            elif a.cmd == "export":
                _print(export_store(mon, Path(a.out)))
        finally:
            store.close()
        return 0
    except Denied as d:
        print(f"denied (log entry {d.seq}): {d.reason}", file=sys.stderr)
        return 3
    finally:
        if offline.attempts():
            print(f"offline guard blocked {len(offline.attempts())} attempt(s): {sorted(set(offline.attempts()))}",
                  file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
