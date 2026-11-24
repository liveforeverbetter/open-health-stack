# SPDX-FileCopyrightText: 2026 Wellnizz contributors
# SPDX-License-Identifier: Apache-2.0
"""Each tampering kind from the red-team suite, run once against a real store."""

import random
import shutil

import pytest

from wellnizz_local.redteam import _tamper
from wellnizz_local.verify import verify_log


@pytest.fixture
def busy(loaded, tmp_path):
    home, store, mon = loaded
    mon.call("lab_markers", {})
    snap = tmp_path / "snap"
    shutil.copytree(home, snap)
    for _ in range(3):
        mon.call("wearable_trend", {"metric": "steps"})
    store.close()
    assert verify_log(home)["ok"]
    return home, snap


@pytest.mark.parametrize("kind", ["delete_middle", "delete_tail", "edit_entry", "edit_and_rehash",
                                  "reorder", "forge_append", "rollback_db"])
def test_tampering_is_detected(busy, kind):
    home, snap = busy
    _tamper(kind, home, snap, random.Random(1))
    rep = verify_log(home)
    assert not rep["ok"] and rep["problems"]


def test_known_gap_rollback_of_db_and_witness(busy):
    """Documented limitation: restoring both files together is not detectable without a hardware counter."""
    home, snap = busy
    _tamper("rollback_all", home, snap, random.Random(1))
    assert verify_log(home)["ok"]


def test_missing_or_edited_witness(busy):
    home, _ = busy
    w = home / "witness.json"
    w.write_text(w.read_text().replace('"seq":', '"seq":1'))
    assert "witness MAC invalid" in " ".join(verify_log(home)["problems"])
    w.unlink()
    assert "witness missing" in verify_log(home)["problems"]
