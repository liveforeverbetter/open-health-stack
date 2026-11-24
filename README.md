<!--
SPDX-FileCopyrightText: 2026 Wellnizz contributors
SPDX-License-Identifier: Apache-2.0
-->
# open-health-stack

[![ci](https://github.com/liveforeverbetter/open-health-stack/actions/workflows/ci.yml/badge.svg)](https://github.com/liveforeverbetter/open-health-stack/actions/workflows/ci.yml)

Repository: `open-health-stack`. Python package and command-line tool: `wellnizz-local`.

A small, local-first store for one person's own health data (lab results, daily wearable metrics and a DNA variant file) with a **reference monitor** in front of it: every read by the command line or by an AI assistant connected over MCP is checked against the scopes the person granted and written to a **hash-linked access log** that the person can verify on their own device.

It runs entirely offline, uses only the Python standard library, and ships with a generator for **synthetic** data. No real person's data is in this repository.

> Educational software. Not medical advice, not a diagnosis, not a medical device. Reference ranges shown are the ones that came with each result.

| | |
|---|---|
| Licence | Apache-2.0 (code), CC0-1.0 (bundled reference notes and generated synthetic data); SPDX tag in every file |
| Runtime dependencies | none (Python 3.10+ standard library) |
| Network | none; an offline guard blocks and counts any attempt |
| Repository | https://github.com/liveforeverbetter/open-health-stack |
| Related | [Wellnizz](https://wellnizz.com) hosted service ([MCP setup repo](https://github.com/liveforeverbetter/wellnizz-mcp)). This repository is a separate, fully open prototype. |

## Quick start

```sh
git clone https://github.com/liveforeverbetter/open-health-stack.git && cd open-health-stack
./reproduce.sh            # one command: synthetic data -> store -> queries -> export -> verification -> red-team suite
```

`reproduce.sh` needs only `python3` (3.10 or newer). It writes `results/demo_report.json` and `results/redteam_report.json` and prints a summary like this (from the run on 23 Nov 2026):

```
log verified:    True (9 entries)
export verified: True
red-team claim:  every detectable attack detected and no false positives
  out_of_grant      50/50  detected   expected: detected
  rogue_tool        50/50  detected   expected: detected
  delete_middle     50/50  detected   expected: detected
  delete_tail       50/50  detected   expected: detected
  edit_entry        50/50  detected   expected: detected
  edit_and_rehash   50/50  detected   expected: detected
  reorder           50/50  detected   expected: detected
  forge_append      50/50  detected   expected: detected
  rollback_db       50/50  detected   expected: detected
  rollback_all       0/50  detected   expected: undetected (known gap)
  benign sessions: 500, false positives: 0
network/process attempts blocked during run: 0
```

`rollback_all` is reported on purpose: restoring an older copy of both the database and the witness file cannot be caught without a monotonic counter the attacker cannot reset. That gap is the research question this prototype sets up (see [docs/PRIVACY.md](docs/PRIVACY.md)).

## Use it step by step

```sh
pip install .                     # or: export PYTHONPATH=src and use python3 -m wellnizz_local
export WELLNIZZ_HOME=/tmp/my-store

wellnizz-local synth samples/     # writes 4 synthetic files (seeded, CC0-1.0)
wellnizz-local import samples/labs_2026-03-02.csv
wellnizz-local import samples/labs_2026-09-14.fhir.json
wellnizz-local import samples/wearable_daily.csv
wellnizz-local import samples/synthetic_001.vcf

wellnizz-local latest Ferritin    # latest value vs its reported range, with the previous result
wellnizz-local trend hrv_rmssd_ms --days 7
wellnizz-local variants           # matches against the bundled 8-position reference set

wellnizz-local log                # who read what, when, allowed or denied
wellnizz-local verify             # check the log against the device witness
wellnizz-local export out/ && wellnizz-local verify-export out/
```

## Connect an assistant (MCP over stdio, scoped)

The assistant only gets the scopes you grant for that session (`labs`, `wearables`, `genome`). Calls outside them are refused **and** logged.

```json
{
  "mcpServers": {
    "wellnizz-local": {
      "command": "wellnizz-local",
      "args": ["--home", "/path/to/store", "serve-mcp", "--grant", "labs,wearables"]
    }
  }
}
```

Tools: `lab_markers`, `lab_latest`, `wearable_trend`, `genome_annotations`. All are read-only and annotated `readOnlyHint: true`. The server uses stdin/stdout only; it opens no socket.

## What it does

| Part | Module | Notes |
|---|---|---|
| Store | `store.py` | One SQLite file; data model in [docs/DATA_MODEL.md](docs/DATA_MODEL.md) |
| Parsers | `parsers.py` | Lab CSV, HL7 FHIR R4 `Bundle` of `Observation`, generic daily wearable CSV (steps, sleep, HRV RMSSD, resting HR), VCF 4.x (plain or `.gz`) |
| Annotation | `annotate.py` | Exact match on GRCh38 position and allele (rsID fallback) against a bundled 8-position set from NCBI dbSNP (public domain) |
| Queries | `tools.py` | Latest lab value vs range, N-day trend with slope and change vs the previous N days, annotated variants |
| Reference monitor | `monitor.py`, `store.py` | Scope check, then the SQLite authorizer limits the tool to its declared tables and records what it actually read |
| Access log | `ledger.py` | SHA-256 hash chain; HMAC-authenticated witness of the head, keyed by `device.key` |
| Verifier | `verify.py` | Gaps, edits, reorders, truncation, forged appends, out-of-scope reads |
| Export | `export.py` | FHIR-style JSON plus variants, with a SHA-256 manifest and HMAC |
| Offline guard | `offline.py` | PEP 578 audit hook blocks socket, HTTP, subprocess and native-library events |
| Red-team suite | `redteam.py` | 10 attack types plus benign sessions on synthetic data |
| Synthetic data | `synth.py` | Seeded; identical output for the same seed |

There is no generative AI model in this project. All parsing, annotation and queries are deterministic code.

Phone support: the wearable parser reads a generic daily CSV. Native adapters for vendor exports (for example Android Health Connect) are planned, not included.

## Tests

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Every test runs with the offline guard on. CI (`.github/workflows/ci.yml`) runs the tests on Python 3.10 to 3.13, rebuilds all results, and repeats the rebuild in a container with networking disabled.

## Privacy model in one paragraph

The claim, the attacker, what is verified and what is not are written out in [docs/PRIVACY.md](docs/PRIVACY.md). In short: against an assistant that over-reaches or follows injected instructions, and against someone who can edit the store files but does not hold the device key, the person can check that every read through the monitor is on record and within the scopes they granted. It does not protect against a fully compromised device, and the device key is a file in this prototype.

## AI use

The code, tests and documentation in this repository were written with an AI coding assistant, then reviewed and tested by the maintainer, who is responsible for them. The assistant is not part of the software: there is no generative AI model in this project. Only synthetic data was used to build and test it. This is educational software, not medical advice.

## Licence

Code: [Apache-2.0](LICENSE). Bundled reference notes and generated synthetic data: CC0-1.0. Licence texts are in [`LICENSES/`](LICENSES/). See [NOTICE](NOTICE) for data sources.
