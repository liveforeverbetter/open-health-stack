<!--
SPDX-FileCopyrightText: 2026 Wellnizz contributors
SPDX-License-Identifier: CC-BY-4.0
-->
# Data model (v1)

One SQLite file, `store.db`, in the store directory (`$WELLNIZZ_HOME`, default `~/.wellnizz-local`, mode 0700). Next to it: `device.key` (32 random bytes, mode 0600) and `witness.json`.

## Tables

| Table | Purpose | Readable by scope |
|---|---|---|
| `lab_results` | one row per lab result | `labs` |
| `wearable_daily` | one row per day and metric | `wearables` |
| `variants` | one row per carried ALT allele | `genome` |
| `sources` | one row per imported file (base name and SHA-256, never a path) | no tool |
| `access_log` | hash-linked log of every call and import | no tool (verifier only) |
| `meta` | schema version | no tool |

### `lab_results`
`collected_at` (ISO date), `loinc` (LOINC code or null), `name` (as reported), `value` (number), `unit` (as reported, UCUM-style), `ref_low`, `ref_high` (range reported with the result, nullable). Maps to FHIR R4 `Observation` (`code.coding[system=http://loinc.org]`, `valueQuantity`, `referenceRange`, `effectiveDateTime`). Units are stored as reported; no conversion in v1.

### `wearable_daily`
`day` (ISO date), `metric`, `value`, `unit`. Metrics and units in v1:

| metric | unit | meaning |
|---|---|---|
| `steps` | count | steps that day |
| `sleep_minutes` | min | main sleep duration |
| `hrv_rmssd_ms` | ms | heart-rate variability, RMSSD |
| `resting_hr_bpm` | /min | resting heart rate |

### `variants`
`chrom` (no `chr` prefix), `pos` (1-based, GRCh38), `rsid` (nullable), `ref`, `alt` (one allele per row), `genotype` (relative to this ALT: `0/1`, `1/1`, `0|1`, ...). Reference-only calls (`0/0`) are not stored.

### `access_log`
| column | meaning |
|---|---|
| `seq` | 1, 2, 3, ... with no gaps |
| `ts` | UTC time, ISO 8601 |
| `session` | session id (e.g. `cli-owner`, `mcp-<random>`) |
| `tool` | tool name or `import.<kind>` |
| `args_json` | canonical JSON of the arguments |
| `granted` | scopes granted to the session |
| `declared` | scopes the tool declares |
| `decision` | `allow`, `deny` or `write` |
| `reason` | why (e.g. `scope not granted: genome`, `undeclared access blocked: read:variants`) |
| `tables_read` | tables the SQLite authorizer saw the tool read |
| `result_sha256` | SHA-256 of the canonical JSON result (zeros when denied) |
| `prev_hash` | `entry_hash` of the previous entry (64 zeros for the first) |
| `entry_hash` | SHA-256 of the canonical JSON of all columns above |

`witness.json` = `{"seq", "head", "mac"}` where `mac = HMAC-SHA256(device.key, "wellnizz-local/witness/v1:<seq>:<head>")`.

## Input formats

**Lab CSV**: header `collected_date,loinc,name,value,unit,ref_low,ref_high`; lines starting with `#` are ignored.

**FHIR**: a `Bundle` whose entries include `Observation` resources with `code` (LOINC coding and/or text), `valueQuantity`, optional `referenceRange[0].low/high`, `effectiveDateTime`.

**Wearable CSV**: header `date` plus any of `steps,sleep_minutes,hrv_rmssd_ms,resting_hr_bpm`; blank cells are skipped.

**VCF**: VCF 4.x with `FORMAT` containing `GT` and one sample column; plain or gzip.

## Export

`observations.fhir.json` (FHIR R4 `Bundle` of `Observation`), `variants.json`, and `manifest.json` with the SHA-256 of each file, the log head at export time, and an HMAC under the device key.
