# SPDX-FileCopyrightText: 2026 Wellnizz contributors
# SPDX-License-Identifier: Apache-2.0
"""Annotate stored variants against the small bundled, openly licensed reference set.

Matching is exact on (chrom, GRCh38 position, ref, alt), with the rsID as a
fallback when the VCF carries one. Deterministic; no network; no AI.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from importlib import resources

REFERENCE_FILE = "variants_grch38.tsv"
REFERENCE_SOURCE = (
    "NCBI dbSNP GRCh38.p14 placements (public domain), read 2026-11-23; "
    "notes by Wellnizz contributors (CC0-1.0)"
)


@lru_cache(maxsize=1)
def load_reference() -> tuple[dict, ...]:
    text = resources.files("wellnizz_local.reference").joinpath(REFERENCE_FILE).read_text("utf-8")
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    rows = []
    for r in csv.DictReader(lines, delimiter="\t"):
        r["pos"] = int(r["pos"])
        rows.append(r)
    return tuple(rows)


def zygosity(genotype: str) -> str:
    alleles = genotype.replace("|", "/").split("/")
    n = alleles.count("1")
    if n == 0:
        return "not carried"
    if len(alleles) == 1:
        return "hemizygous"
    return "homozygous (two copies)" if n == len(alleles) else "heterozygous (one copy)"


def annotate(variants: list[dict]) -> list[dict]:
    ref = load_reference()
    by_pos = {(r["chrom"], r["pos"], r["ref"], r["alt"]): r for r in ref}
    by_rsid = {r["rsid"]: r for r in ref}
    out = []
    for v in variants:
        hit = by_pos.get((v["chrom"], v["pos"], v["ref"], v["alt"]))
        matched_on = "position"
        if hit is None and v.get("rsid") and v["rsid"] in by_rsid:
            cand = by_rsid[v["rsid"]]
            if cand["alt"] == v["alt"]:
                hit, matched_on = cand, "rsid"
        if hit is None:
            continue
        out.append({
            "rsid": hit["rsid"],
            "gene": hit["gene"],
            "protein_change": hit["protein_change"],
            "position": f"{hit['chrom']}:{hit['pos']} {hit['ref']}>{hit['alt']} (GRCh38)",
            "genotype": v["genotype"],
            "zygosity": zygosity(v["genotype"]),
            "matched_on": matched_on,
            "note": hit["note"],
        })
    out.sort(key=lambda a: a["rsid"])
    return out
