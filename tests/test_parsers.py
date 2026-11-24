# SPDX-FileCopyrightText: 2026 Wellnizz contributors
# SPDX-License-Identifier: Apache-2.0
import gzip

import pytest

from wellnizz_local import parsers


def test_lab_csv(synthetic):
    rows = parsers.parse_lab_csv(synthetic["labs_csv"])
    assert len(rows) == 7
    ferritin = next(r for r in rows if r.loinc == "2276-4")
    assert ferritin.name == "Ferritin" and ferritin.unit == "ng/mL"
    assert ferritin.ref_low == 30 and ferritin.ref_high == 400
    ldl = next(r for r in rows if r.loinc == "13457-7")
    assert ldl.ref_low is None and ldl.ref_high == 100


def test_fhir_bundle(synthetic):
    rows = parsers.parse_fhir_bundle(synthetic["labs_fhir"])
    assert len(rows) == 7
    assert {r.collected_at for r in rows} == {"2026-09-14"}
    assert all(r.loinc for r in rows)


def test_fhir_rejects_non_bundle(tmp_path):
    p = tmp_path / "x.json"
    p.write_text('{"resourceType": "Patient"}')
    with pytest.raises(parsers.ParseError):
        parsers.parse_fhir_bundle(p)


def test_wearable_csv(synthetic):
    rows = parsers.parse_wearable_csv(synthetic["wearables"])
    metrics = {r.metric for r in rows}
    assert metrics == {"steps", "sleep_minutes", "hrv_rmssd_ms", "resting_hr_bpm"}
    assert all(r.day.startswith("2026-") for r in rows)


def test_wearable_partial_columns_and_blanks(tmp_path):
    p = tmp_path / "w.csv"
    p.write_text("date,steps,hrv_rmssd_ms\n2026-01-01,1000,\n2026-01-02,,40.5\n")
    rows = parsers.parse_wearable_csv(p)
    assert [(r.day, r.metric, r.value) for r in rows] == [
        ("2026-01-01", "steps", 1000.0), ("2026-01-02", "hrv_rmssd_ms", 40.5)]


def test_bad_date_is_reported(tmp_path):
    p = tmp_path / "w.csv"
    p.write_text("date,steps\nyesterday,10\n")
    with pytest.raises(parsers.ParseError, match="ISO date"):
        parsers.parse_wearable_csv(p)


VCF = """##fileformat=VCFv4.2
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1
chr1\t100\trs1\tA\tG\t.\tPASS\t.\tGT\t0/1
2\t200\t.\tC\tT,G\t.\tPASS\t.\tGT:DP\t1|2:30
3\t300\t.\tG\tA\t.\tPASS\t.\tGT\t0/0
"""


def test_vcf_plain_and_gz(tmp_path):
    p = tmp_path / "s.vcf"
    p.write_text(VCF)
    g = tmp_path / "s.vcf.gz"
    with gzip.open(g, "wt") as fh:
        fh.write(VCF)
    for path in (p, g):
        rows = parsers.parse_vcf(path)
        assert [(r.chrom, r.pos, r.alt, r.genotype) for r in rows] == [
            ("1", 100, "G", "0/1"), ("2", 200, "T", "1|0"), ("2", 200, "G", "0|1")]
        assert rows[0].rsid == "rs1"


def test_vcf_needs_header(tmp_path):
    p = tmp_path / "bad.vcf"
    p.write_text("1\t1\t.\tA\tG\t.\t.\t.\tGT\t0/1\n")
    with pytest.raises(parsers.ParseError):
        parsers.parse_vcf(p)
