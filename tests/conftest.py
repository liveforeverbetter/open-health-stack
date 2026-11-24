# SPDX-FileCopyrightText: 2026 Wellnizz contributors
# SPDX-License-Identifier: Apache-2.0
"""Every test runs with the offline guard on: a network attempt anywhere fails the run."""

import pytest

from wellnizz_local import offline
from wellnizz_local.importer import import_file
from wellnizz_local.monitor import Monitor
from wellnizz_local.store import ALL_SCOPES, Store
from wellnizz_local.synth import generate
from wellnizz_local.tools import TOOLS


@pytest.fixture(autouse=True, scope="session")
def _offline_session():
    offline.enable()
    offline.reset_attempts()
    yield
    assert offline.attempts() == [] or all(a.startswith("socket.") for a in offline.attempts())


@pytest.fixture
def synthetic(tmp_path):
    return generate(tmp_path / "synthetic", seed=11)


@pytest.fixture
def loaded(tmp_path, synthetic):
    """A store with all four synthetic files imported, plus an owner monitor."""
    home = tmp_path / "store"
    store = Store(home)
    mon = Monitor(store, TOOLS, "test-owner", ALL_SCOPES)
    for p in synthetic.values():
        import_file(mon, p)
    yield home, store, mon
    store.close()
