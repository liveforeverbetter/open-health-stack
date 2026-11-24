# SPDX-FileCopyrightText: 2026 Wellnizz contributors
# SPDX-License-Identifier: Apache-2.0
"""Import parsed files into the store. Every import is itself a log entry."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from . import parsers
from .monitor import Monitor

KINDS = {
    "labs-csv": parsers.parse_lab_csv,
    "fhir": parsers.parse_fhir_bundle,
    "wearable-csv": parsers.parse_wearable_csv,
    "vcf": parsers.parse_vcf,
}


def guess_kind(path: Path) -> str:
    name = Path(path).name.lower()
    if name.endswith((".vcf", ".vcf.gz")):
        return "vcf"
    if name.endswith(".json"):
        return "fhir"
    if name.endswith(".csv"):
        with open(path, encoding="utf-8") as fh:
            header = next((ln for ln in fh if not ln.startswith("#")), "")
        return "labs-csv" if "loinc" in header else "wearable-csv"
    raise ValueError(f"cannot guess the format of {name}; pass --kind")


def import_file(monitor: Monitor, path: Path, kind: str | None = None) -> dict:
    path = Path(path)
    kind = kind or guess_kind(path)
    rows = KINDS[kind](path)
    digest = parsers.file_sha256(path)

    def write(conn):
        existing = conn.execute(
            "SELECT id FROM sources WHERE sha256 = ? AND kind = ?", (digest, kind)
        ).fetchone()
        if existing:
            return {"kind": kind, "file": path.name, "sha256": digest, "rows": 0, "duplicate": True}
        cur = conn.execute(
            "INSERT INTO sources(kind, filename, sha256, imported_at) VALUES (?, ?, ?, ?)",
            (kind, path.name, digest, _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")),
        )
        sid = cur.lastrowid
        if kind in ("labs-csv", "fhir"):
            conn.executemany(
                "INSERT INTO lab_results(source_id, collected_at, loinc, name, value, unit, ref_low, ref_high)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(sid, r.collected_at, r.loinc, r.name, r.value, r.unit, r.ref_low, r.ref_high) for r in rows],
            )
        elif kind == "wearable-csv":
            conn.executemany(
                "INSERT OR REPLACE INTO wearable_daily(source_id, day, metric, value, unit) VALUES (?, ?, ?, ?, ?)",
                [(sid, r.day, r.metric, r.value, r.unit) for r in rows],
            )
        else:
            conn.executemany(
                "INSERT INTO variants(source_id, chrom, pos, rsid, ref, alt, genotype) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(sid, r.chrom, r.pos, r.rsid, r.ref, r.alt, r.genotype) for r in rows],
            )
        return {"kind": kind, "file": path.name, "sha256": digest, "rows": len(rows), "duplicate": False}

    return monitor.record_write(f"import.{kind}", {"file": path.name, "sha256": digest}, write)
