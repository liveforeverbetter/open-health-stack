# SPDX-FileCopyrightText: 2026 Wellnizz contributors
# SPDX-License-Identifier: Apache-2.0
from wellnizz_local.redteam import ATTACKS, run


def test_redteam_claim_holds_on_small_run():
    rep = run(n_sessions=60, seed=5)
    assert rep["claim_holds"], rep
    assert rep["benign"]["false_positives"] == 0
    assert rep["attacks"]["rollback_all"]["detected"] == 0  # the documented gap stays visible
    assert set(rep["attacks"]) == set(ATTACKS)
