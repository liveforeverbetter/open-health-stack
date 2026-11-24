# SPDX-FileCopyrightText: 2026 Wellnizz contributors
# SPDX-License-Identifier: Apache-2.0
"""Read-only query tools. Each tool declares the scopes it needs; the monitor enforces them.

The same tools back the CLI and the MCP stdio server. Answers are plain
numbers and comparisons with the reference range that came with the result:
educational, not medical advice.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3

from .annotate import REFERENCE_SOURCE, annotate
from .monitor import Tool
from .parsers import WEARABLE_METRICS

DISCLAIMER = "Educational information, not medical advice or a diagnosis."


def _position(value: float, low, high) -> str:
    if low is not None and value < low:
        return "below range"
    if high is not None and value > high:
        return "above range"
    if low is None and high is None:
        return "no range given"
    return "within range"


def lab_markers(conn: sqlite3.Connection, args: dict) -> dict:
    rows = conn.execute(
        "SELECT name, loinc, COUNT(*), MAX(collected_at) FROM lab_results GROUP BY name, loinc ORDER BY name"
    ).fetchall()
    return {"markers": [{"name": n, "loinc": l, "results": c, "latest": d} for n, l, c, d in rows]}


def lab_latest(conn: sqlite3.Connection, args: dict) -> dict:
    marker = str(args["marker"]).strip()
    rows = conn.execute(
        "SELECT collected_at, name, loinc, value, unit, ref_low, ref_high FROM lab_results"
        " WHERE lower(name) = lower(?) OR loinc = ? ORDER BY collected_at DESC, id DESC LIMIT 2",
        (marker, marker),
    ).fetchall()
    if not rows:
        raise KeyError(f"no lab results for {marker!r}")
    d, name, loinc, value, unit, lo, hi = rows[0]
    out = {
        "marker": name, "loinc": loinc, "date": d, "value": value, "unit": unit,
        "reference_range": {"low": lo, "high": hi, "source": "as reported with the result"},
        "position": _position(value, lo, hi),
        "disclaimer": DISCLAIMER,
    }
    if len(rows) > 1:
        pd, _, _, pv, pu, _, _ = rows[1]
        out["previous"] = {"date": pd, "value": pv, "unit": pu,
                           "change": round(value - pv, 3) if pu == unit else None}
    return out


def _slope(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    return 0.0 if den == 0 else sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def wearable_trend(conn: sqlite3.Connection, args: dict) -> dict:
    metric = str(args["metric"])
    if metric not in WEARABLE_METRICS:
        raise ValueError(f"metric must be one of {sorted(WEARABLE_METRICS)}")
    days = int(args.get("days", 7))
    if not 2 <= days <= 365:
        raise ValueError("days must be between 2 and 365")
    end = conn.execute("SELECT MAX(day) FROM wearable_daily WHERE metric = ?", (metric,)).fetchone()[0]
    if end is None:
        raise KeyError(f"no data for {metric}")
    end_d = _dt.date.fromisoformat(end)
    start_d = end_d - _dt.timedelta(days=days - 1)
    prev_start = start_d - _dt.timedelta(days=days)
    rows = conn.execute(
        "SELECT day, AVG(value), MAX(unit) FROM wearable_daily WHERE metric = ? AND day BETWEEN ? AND ?"
        " GROUP BY day ORDER BY day",
        (metric, prev_start.isoformat(), end),
    ).fetchall()
    cur = [(d, v) for d, v, _ in rows if d >= start_d.isoformat()]
    prev = [v for d, v, _ in rows if d < start_d.isoformat()]
    unit = rows[-1][2]
    xs = [(_dt.date.fromisoformat(d) - start_d).days for d, _ in cur]
    ys = [v for _, v in cur]
    mean = sum(ys) / len(ys)
    slope = _slope(xs, ys) if len(ys) >= 2 else 0.0
    rel = slope * (days - 1) / mean if mean else 0.0
    direction = "rising" if rel > 0.05 else "falling" if rel < -0.05 else "flat"
    out = {
        "metric": metric, "unit": unit, "window": {"from": start_d.isoformat(), "to": end, "days_with_data": len(ys)},
        "mean": round(mean, 2), "min": min(ys), "max": max(ys),
        "slope_per_day": round(slope, 3), "direction": direction,
        "daily": [{"day": d, "value": round(v, 2)} for d, v in cur],
        "disclaimer": DISCLAIMER,
    }
    if prev:
        pm = sum(prev) / len(prev)
        out["previous_window_mean"] = round(pm, 2)
        out["change_vs_previous_pct"] = round(100 * (mean - pm) / pm, 1) if pm else None
    return out


def genome_annotations(conn: sqlite3.Connection, args: dict) -> dict:
    rows = conn.execute("SELECT chrom, pos, rsid, ref, alt, genotype FROM variants").fetchall()
    variants = [dict(zip(("chrom", "pos", "rsid", "ref", "alt", "genotype"), r)) for r in rows]
    return {
        "variants_in_store": len(variants),
        "annotated": annotate(variants),
        "reference": REFERENCE_SOURCE,
        "disclaimer": DISCLAIMER,
    }


TOOLS: dict[str, Tool] = {t.name: t for t in (
    Tool("lab_markers", "List lab markers in the store with result counts and latest date.",
         ("labs",), {"type": "object", "properties": {}, "additionalProperties": False}, lab_markers),
    Tool("lab_latest", "Latest result for one lab marker (name or LOINC code) compared with its reported reference range.",
         ("labs",), {"type": "object", "properties": {"marker": {"type": "string"}}, "required": ["marker"],
                     "additionalProperties": False}, lab_latest),
    Tool("wearable_trend", "Trend of a daily wearable metric over the last N days (default 7) versus the N days before.",
         ("wearables",), {"type": "object", "properties": {
             "metric": {"type": "string", "enum": sorted(WEARABLE_METRICS)},
             "days": {"type": "integer", "minimum": 2, "maximum": 365}},
             "required": ["metric"], "additionalProperties": False}, wearable_trend),
    Tool("genome_annotations", "Stored variants that match the bundled reference set, with genotype and an educational note.",
         ("genome",), {"type": "object", "properties": {}, "additionalProperties": False}, genome_annotations),
)}
