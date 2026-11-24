# SPDX-FileCopyrightText: 2026 Wellnizz contributors
# SPDX-License-Identifier: Apache-2.0
"""Open-science hygiene the funder checks: SPDX tags everywhere, no real data in the repo."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "venv", "results", "__pycache__", ".pytest_cache", "LICENSES"}
SKIP_FILES = {"LICENSE"}


def _files():
    for p in ROOT.rglob("*"):
        if p.is_file() and not (set(p.relative_to(ROOT).parts) & SKIP_DIRS) and p.name not in SKIP_FILES                 and not p.name.endswith((".pyc", ".license")):
            yield p


def test_every_file_has_an_spdx_tag():
    missing = []
    for p in _files():
        sidecar = p.with_name(p.name + ".license")
        text = p.read_text("utf-8", errors="replace")
        if "SPDX-License-Identifier:" not in text and not sidecar.exists():
            missing.append(str(p.relative_to(ROOT)))
    assert missing == []


def test_no_data_files_committed_outside_reference():
    data = [p for p in _files() if p.suffix in {".vcf", ".gz", ".csv", ".fhir", ".db", ".sqlite"}]
    assert data == []
