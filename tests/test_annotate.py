# SPDX-FileCopyrightText: 2026 Wellnizz contributors
# SPDX-License-Identifier: Apache-2.0
from wellnizz_local.annotate import annotate, load_reference, zygosity
from wellnizz_local.synth import REFERENCE_SITES


def test_reference_set_is_small_and_complete():
    ref = load_reference()
    assert len(ref) == 8
    for r in ref:
        assert r["rsid"].startswith("rs") and r["note"]
    # the synthetic generator uses exactly the reference positions
    assert {(r["chrom"], r["pos"], r["ref"], r["alt"]) for r in ref} == {
        (c, p, rf, a) for c, p, rf, a, _ in REFERENCE_SITES}


def test_reference_file_states_source_and_licence():
    from importlib import resources
    text = resources.files("wellnizz_local.reference").joinpath("variants_grch38.tsv").read_text()
    assert "SPDX-License-Identifier: CC0-1.0" in text
    assert "dbSNP" in text and "public domain" in text


def test_annotate_by_position_and_rsid():
    out = annotate([
        {"chrom": "6", "pos": 26092913, "rsid": None, "ref": "G", "alt": "A", "genotype": "1/1"},
        {"chrom": "19", "pos": 1, "rsid": "rs7412", "ref": "C", "alt": "T", "genotype": "0/1"},
        {"chrom": "19", "pos": 1, "rsid": "rs7412", "ref": "C", "alt": "G", "genotype": "0/1"},  # other allele
        {"chrom": "5", "pos": 5, "rsid": None, "ref": "A", "alt": "C", "genotype": "0/1"},
    ])
    assert [(a["rsid"], a["matched_on"], a["zygosity"]) for a in out] == [
        ("rs1800562", "position", "homozygous (two copies)"),
        ("rs7412", "rsid", "heterozygous (one copy)"),
    ]


def test_zygosity():
    assert zygosity("0/1") == "heterozygous (one copy)"
    assert zygosity("1|1") == "homozygous (two copies)"
    assert zygosity("1") == "hemizygous"
    assert zygosity("0/0") == "not carried"
