# SPDX-FileCopyrightText: 2026 Wellnizz contributors
# SPDX-License-Identifier: Apache-2.0
"""Deterministic parsers for open, documented input formats. No network, no AI.

Supported inputs (see docs/DATA_MODEL.md for the exact columns):
- lab results as CSV
- lab results as an HL7 FHIR R4 Bundle of Observation resources (JSON)
- daily wearable/phone metrics as a generic CSV (one row per day)
- small-variant calls as VCF 4.x (single sample, plain text or .gz)
"""

from __future__ import annotations

import csv
import datetime as _dt
import gzip
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path

LOINC_SYSTEM = "http://loinc.org"

WEARABLE_METRICS = {
    "steps": "count",
    "sleep_minutes": "min",
    "hrv_rmssd_ms": "ms",
    "resting_hr_bpm": "/min",
}


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class LabRow:
    collected_at: str
    loinc: str | None
    name: str
    value: float
    unit: str
    ref_low: float | None
    ref_high: float | None


@dataclass(frozen=True)
class WearableRow:
    day: str
    metric: str
    value: float
    unit: str


@dataclass(frozen=True)
class VariantRow:
    chrom: str
    pos: int
    rsid: str | None
    ref: str
    alt: str
    genotype: str


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _date(text: str, where: str) -> str:
    text = (text or "").strip()
    try:
        return _dt.date.fromisoformat(text[:10]).isoformat()
    except ValueError as exc:
        raise ParseError(f"{where}: not an ISO date: {text!r}") from exc


def _num(text, where: str, optional: bool = False) -> float | None:
    if text is None or str(text).strip() == "":
        if optional:
            return None
        raise ParseError(f"{where}: missing number")
    try:
        return float(str(text).strip())
    except ValueError as exc:
        raise ParseError(f"{where}: not a number: {text!r}") from exc


def _text_lines(path: Path) -> io.TextIOBase:
    path = Path(path)
    if path.suffix == ".gz":
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8")
    return open(path, encoding="utf-8", newline="")


def _csv_rows(path: Path):
    with _text_lines(path) as fh:
        lines = [ln for ln in fh if not ln.startswith("#")]
    return list(csv.DictReader(lines))


# -- labs -------------------------------------------------------------------
LAB_COLUMNS = ("collected_date", "loinc", "name", "value", "unit", "ref_low", "ref_high")


def parse_lab_csv(path: Path) -> list[LabRow]:
    rows = _csv_rows(path)
    if rows and not set(LAB_COLUMNS) <= set(rows[0]):
        raise ParseError(f"lab CSV needs columns {LAB_COLUMNS}, got {tuple(rows[0])}")
    out = []
    for i, r in enumerate(rows, start=2):
        where = f"{Path(path).name}:{i}"
        out.append(LabRow(
            collected_at=_date(r["collected_date"], where),
            loinc=(r["loinc"] or "").strip() or None,
            name=r["name"].strip(),
            value=_num(r["value"], where),
            unit=r["unit"].strip(),
            ref_low=_num(r["ref_low"], where, optional=True),
            ref_high=_num(r["ref_high"], where, optional=True),
        ))
    return out


def parse_fhir_bundle(path: Path) -> list[LabRow]:
    with _text_lines(path) as fh:
        doc = json.load(fh)
    if doc.get("resourceType") != "Bundle":
        raise ParseError("expected a FHIR Bundle")
    out = []
    for n, entry in enumerate(doc.get("entry", [])):
        res = entry.get("resource", {})
        if res.get("resourceType") != "Observation":
            continue
        where = f"{Path(path).name}:entry[{n}]"
        codings = res.get("code", {}).get("coding", [])
        loinc = next((c.get("code") for c in codings if c.get("system") == LOINC_SYSTEM), None)
        name = res.get("code", {}).get("text") or next((c.get("display") for c in codings if c.get("display")), None)
        q = res.get("valueQuantity")
        if not name or not q or "value" not in q:
            raise ParseError(f"{where}: Observation needs code text/display and valueQuantity.value")
        rr = (res.get("referenceRange") or [{}])[0]
        out.append(LabRow(
            collected_at=_date(res.get("effectiveDateTime", ""), where),
            loinc=loinc,
            name=name,
            value=_num(q["value"], where),
            unit=q.get("unit") or q.get("code") or "",
            ref_low=_num((rr.get("low") or {}).get("value"), where, optional=True),
            ref_high=_num((rr.get("high") or {}).get("value"), where, optional=True),
        ))
    return out


# -- wearables ----------------------------------------------------------------
def parse_wearable_csv(path: Path) -> list[WearableRow]:
    rows = _csv_rows(path)
    if not rows:
        return []
    if "date" not in rows[0]:
        raise ParseError("wearable CSV needs a 'date' column")
    known = [m for m in WEARABLE_METRICS if m in rows[0]]
    if not known:
        raise ParseError(f"wearable CSV needs at least one of {tuple(WEARABLE_METRICS)}")
    out = []
    for i, r in enumerate(rows, start=2):
        where = f"{Path(path).name}:{i}"
        day = _date(r["date"], where)
        for m in known:
            v = _num(r.get(m), where, optional=True)
            if v is not None:
                out.append(WearableRow(day, m, v, WEARABLE_METRICS[m]))
    return out


# -- VCF ------------------------------------------------------------------------
def parse_vcf(path: Path) -> list[VariantRow]:
    out = []
    saw_header = False
    with _text_lines(path) as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.rstrip("\n\r")
            if not line:
                continue
            if line.startswith("##"):
                continue
            if line.startswith("#CHROM"):
                cols = line.split("\t")
                if len(cols) < 10:
                    raise ParseError("VCF must contain FORMAT and one sample column")
                saw_header = True
                continue
            if not saw_header:
                raise ParseError(f"line {lineno}: data before #CHROM header")
            f = line.split("\t")
            if len(f) < 10:
                raise ParseError(f"line {lineno}: expected >= 10 columns")
            chrom = f[0][3:] if f[0].lower().startswith("chr") else f[0]
            pos = int(f[1])
            rsid = f[2] if f[2].startswith("rs") else None
            ref = f[3].upper()
            alts = [a.upper() for a in f[4].split(",")]
            fmt = f[8].split(":")
            sample = f[9].split(":")
            if "GT" not in fmt:
                raise ParseError(f"line {lineno}: FORMAT has no GT")
            gt = sample[fmt.index("GT")]
            alleles = gt.replace("|", "/").split("/")
            for idx, alt in enumerate(alts, start=1):
                if alt in (".", "*", "<NON_REF>"):
                    continue
                if str(idx) not in alleles:
                    continue  # this ALT is not carried by the sample
                # Re-express the genotype relative to this ALT only.
                sep = "|" if "|" in gt else "/"
                rel = sep.join("1" if a == str(idx) else ("." if a == "." else "0") for a in alleles)
                out.append(VariantRow(chrom, pos, rsid, ref, alt, rel))
    if not saw_header:
        raise ParseError("no #CHROM header found")
    return out
