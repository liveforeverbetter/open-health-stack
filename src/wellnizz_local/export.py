# SPDX-FileCopyrightText: 2026 Wellnizz contributors
# SPDX-License-Identifier: Apache-2.0
"""Full export with a hash manifest.

The export is itself a logged read (tool ``export_all``, all scopes). The
manifest lists the SHA-256 of every file, the log head at export time, and an
HMAC over the manifest under the device key. Anyone can check the file hashes;
the device that made the export can also check the HMAC.
"""

from __future__ import annotations

import json
from pathlib import Path

from .annotate import REFERENCE_SOURCE
from .ledger import DeviceKey, canonical, sha256_hex
from .monitor import Monitor, Tool


def _export_all(conn, args):
    labs = conn.execute(
        "SELECT collected_at, loinc, name, value, unit, ref_low, ref_high FROM lab_results ORDER BY collected_at, name"
    ).fetchall()
    wear = conn.execute("SELECT day, metric, value, unit FROM wearable_daily ORDER BY day, metric").fetchall()
    var = conn.execute("SELECT chrom, pos, rsid, ref, alt, genotype FROM variants ORDER BY chrom, pos").fetchall()
    entries = []
    for d, loinc, name, value, unit, lo, hi in labs:
        obs = {
            "resourceType": "Observation", "status": "final",
            "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "laboratory"}]}],
            "code": {"text": name, "coding": ([{"system": "http://loinc.org", "code": loinc}] if loinc else [])},
            "effectiveDateTime": d, "valueQuantity": {"value": value, "unit": unit},
        }
        rr = {}
        if lo is not None:
            rr["low"] = {"value": lo, "unit": unit}
        if hi is not None:
            rr["high"] = {"value": hi, "unit": unit}
        if rr:
            obs["referenceRange"] = [rr]
        entries.append({"resource": obs})
    for day, metric, value, unit in wear:
        entries.append({"resource": {
            "resourceType": "Observation", "status": "final",
            "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "activity"}]}],
            "code": {"text": metric}, "effectiveDateTime": day, "valueQuantity": {"value": value, "unit": unit},
        }})
    bundle = {"resourceType": "Bundle", "type": "collection", "entry": entries}
    variants = [dict(zip(("chrom", "pos", "rsid", "ref", "alt", "genotype"), r)) for r in var]
    return {"bundle": bundle, "variants": variants}


EXPORT_TOOL = Tool("export_all", "Export every record (owner only).", ("labs", "wearables", "genome"),
                   {"type": "object", "properties": {}}, _export_all)


def export_store(monitor: Monitor, out_dir: Path) -> dict:
    monitor.tools = {**monitor.tools, EXPORT_TOOL.name: EXPORT_TOOL}
    data = monitor.call("export_all", {"out_dir_name": Path(out_dir).name})
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "observations.fhir.json": json.dumps(data["bundle"], indent=1, sort_keys=True),
        "variants.json": json.dumps({"assembly": "GRCh38", "variants": data["variants"]}, indent=1, sort_keys=True),
    }
    for name, text in files.items():
        (out_dir / name).write_text(text + "\n", "utf-8")
    seq, head = monitor._head()
    manifest = {
        "format": "wellnizz-local-export/v1",
        "files": {n: sha256_hex((out_dir / n).read_bytes()) for n in sorted(files)},
        "log_seq": seq, "log_head": head,
        "reference": REFERENCE_SOURCE,
    }
    manifest["hmac_sha256"] = monitor.key.mac(canonical(manifest))
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", "utf-8")
    return manifest


def verify_export(out_dir: Path, home: Path | None = None) -> dict:
    out_dir = Path(out_dir)
    manifest = json.loads((out_dir / "manifest.json").read_text("utf-8"))
    problems = []
    for name, digest in manifest["files"].items():
        p = out_dir / name
        if not p.exists():
            problems.append(f"missing file {name}")
        elif sha256_hex(p.read_bytes()) != digest:
            problems.append(f"file changed since export: {name}")
    mac_checked = False
    if home is not None and (Path(home) / "device.key").exists():
        body = {k: v for k, v in manifest.items() if k != "hmac_sha256"}
        mac_checked = True
        if not DeviceKey(Path(home)).check(canonical(body), manifest["hmac_sha256"]):
            problems.append("manifest HMAC invalid (manifest edited or made by another device)")
    return {"ok": not problems, "hmac_checked": mac_checked, "problems": problems}
