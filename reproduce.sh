#!/usr/bin/env sh
# SPDX-FileCopyrightText: 2026 Wellnizz contributors
# SPDX-License-Identifier: Apache-2.0
# One command rebuilds every result from synthetic data: ./reproduce.sh
# Needs only Python 3.10+ (standard library). Writes results/demo_report.json and results/redteam_report.json.
set -eu
cd "$(dirname "$0")"
PYTHONPATH=src exec python3 -m wellnizz_local demo --out results --seed 7 --sessions 1000 --force "$@"
