# SPDX-FileCopyrightText: 2026 Wellnizz contributors
# SPDX-License-Identifier: Apache-2.0
import json

from wellnizz_local.export import export_store, verify_export
from wellnizz_local.synth import generate


def test_export_round_trip_and_tamper(loaded, tmp_path):
    home, store, mon = loaded
    out = tmp_path / "exp"
    manifest = export_store(mon, out)
    assert set(manifest["files"]) == {"observations.fhir.json", "variants.json"}
    assert verify_export(out, home) == {"ok": True, "hmac_checked": True, "problems": []}
    bundle = json.loads((out / "observations.fhir.json").read_text())
    assert bundle["resourceType"] == "Bundle" and len(bundle["entry"]) > 14
    (out / "variants.json").write_text("{}")
    assert not verify_export(out, home)["ok"]


def test_synthetic_data_is_deterministic_and_marked(tmp_path):
    a = generate(tmp_path / "a", seed=3)
    b = generate(tmp_path / "b", seed=3)
    c = generate(tmp_path / "c", seed=4)
    for k in a:
        assert a[k].read_bytes() == b[k].read_bytes()
        assert b"SYNTHETIC" in a[k].read_bytes()
    assert a["vcf"].read_bytes() != c["vcf"].read_bytes()


def test_reimport_is_idempotent(loaded, synthetic):
    from wellnizz_local.importer import import_file
    home, store, mon = loaded
    r = import_file(mon, synthetic["labs_csv"])
    assert r["duplicate"] is True
