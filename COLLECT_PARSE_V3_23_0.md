# COLLECT_PARSE_V3_23_0.py

> Builds on **V3.22.0** (protocol health) → … → V3.16. The final intelligence layer. See earlier `.md`s. This documents **only what V3.23.0 adds**: health scoring + migration readiness + the HTML Health mode.

## Purpose
Synthesises everything the run has computed into two decision-ready outputs:
- **`Health Scores`** — a per-switch **0–100** score with weighted deductions, banded Excellent / Good / Fair / Poor / Critical.
- **`Migration Readiness`** — a per **move-group** verdict **READY / CAUTION / NOT READY** from a 10-check pre-migration checklist.
Both are embedded in the snapshot and rendered by the explorer's new **🏥 Health** mode (nodes coloured by score band).

## Quick Start
Unchanged. Both sheets appear automatically; data also goes into `snap_dict["health_scores"]` and `snap_dict["migration_readiness"]`.

## Dependencies
Unchanged: `netmiko` + `openpyxl` + stdlib. **No new imports, no new collection** (pure synthesis of in-run records).

## Inputs & Outputs
- **Input:** unchanged.
- **Output:** unchanged, plus the `Health Scores` and `Migration Readiness` worksheets, two new snapshot keys, and the HTML Health mode.

## Health score (0–100)
Starts at 100; weighted deductions, **capped per category** so one noisy area can't zero the score:

| Category (cap) | Deductions |
|---|---|
| L1 (−30) | err-disabled −8, single-fiber-uplink −10, error-rate-high −5, half-duplex −8 |
| L3 (−30) | single-gateway −10, no-FHRP −3, tracked-object-down −12 |
| Cross-layer (−45) | Critical −18, High −10, Medium −4, Low −2 (attributed via each finding's `hosts`) |
| Protocol (−25) | High −10, Medium −4 |

Bands: **≥90 Excellent** (#36e08a) · **≥75 Good** (#7adb8f) · **≥60 Fair** (#ffe566) · **≥40 Poor** (#ff9f45) · **<40 Critical** (#ff5775).

## Migration readiness — 10-check checklist (per move group)
Reuses `compute_move_groups` for the wave definition. Each check is `pass` / `warn` / `fail`; **any fail → NOT READY**, else **any warn → CAUTION**, else **READY**.

1. Redundant uplinks (warn on single-fiber) · 2. **Gateway redundancy** (fail on sole gateway) · 3. **No cross-layer Critical** (fail) · 4. No err-disabled (warn) · 5. STP consistency (warn) · 6. Port-channels healthy (warn) · 7. **Routing adjacencies up** (fail on down OSPF/BGP) · 8. No orphan VLANs (warn) · 9. Clean uplinks / no half-duplex (warn) · 10. **Device-health floor** (fail on a Critical-band switch, warn on Poor).

## How It Works (delta only)
- **Phase 28**: `compute_health_scores(all_interfaces, physical_health, l3_forwarding, cross_layer, protocol_health)` → `snap_dict["health_scores"]`.
- **Phase 29**: `compute_migration_readiness(all_interfaces, compute_move_groups(...), health_scores, …, dep_map)` → `snap_dict["migration_readiness"]`.
- **Cross-layer enrichment**: `compute_cross_layer_correlations` now attaches a **`hosts`** list to every finding, so cross-layer risk can be attributed to specific switches for scoring and the Health view.
- **HTML 🏥 Health mode**: `drawHealthCanvas` colours each node by band; `renderHealthMode` lists per-switch scores + top issues and the per-group readiness verdicts. Graceful empty state when a snapshot predates V3.23. See `blast_radius_explorer.md`.
- New symbols: `HEALTH_SCORES_SHEET_NAME`, `MIGRATION_READINESS_SHEET_NAME`, `_HEALTH_BANDS`, `_READY_FILL`, `_STATUS_FILL`, `_health_band`, `compute_health_scores`, `compute_migration_readiness`, `write_health_scores_sheet`, `write_migration_readiness_sheet`.

## Known Limitations / TODOs
- **Deduction weights and the band thresholds are a defensible default**, not calibrated against a labelled dataset — tune to taste.
- Readiness reuses the shared-VLAN connected-component move groups; if you migrate by a different grouping, feed your own groups to `compute_migration_readiness`.
- The single-fiber check is a **warn** (common in real access tiers), not a hard fail; gateway-redundancy / cross-layer-Critical / down-adjacency / Critical-health are the hard fails.
- Everything is scan-bound (a redundant off-scan uplink or gateway would change a verdict).
- Inherits all V3.16–V3.22 limits.

## Testing
A `pytest` suite lives in `tests/` (added V3.23.2). It runs fully offline — no
SSH, no real device data:
- **Regression net:** `tests/test_pipeline_golden.py` runs the real
  `--no-collect` pipeline against synthetic fixtures and asserts the
  `snapshot.json` (the HTML explorer's contract) and the workbook's
  sheet-name/header schema against frozen goldens in `tests/golden/`.
- **Unit tests:** `tests/test_parsers.py` (show-command parsers) and
  `tests/test_compute.py` (`compute_move_groups`, `compute_cross_layer_correlations`,
  `compute_health_scores`, `compute_migration_readiness`, `compute_protocol_health`).
- **Fixtures:** `tests/synthetic_fixtures.py` — fully synthetic IOS + NX-OS
  output for 3 switches; safe to commit.

Run `python -m pip install -r requirements-dev.txt` then `python -m pytest`.
Regenerate goldens after a *reviewed* change with
`UPDATE_GOLDEN=1 python -m pytest tests/test_pipeline_golden.py`.

## Chat Context
**Problem being solved:** Roll the full L1→L4 + cross-layer + protocol picture up into a single per-switch health number and a go/no-go migration verdict per wave — the answer a migration lead actually asks for.
**Date:** 2026-06-03
**Related scripts:** `COLLECT_PARSE_V3_22_0.py` (prior version); consumes every prior intelligence layer; renders via `blast_radius_explorer.html` / `.md` (🏥 Health mode).

## Change Log
| Date | Change |
|---|---|
| 2026-06-04 | **V3.23.2** — *test safety net (additive; no behavioral change to the script).* Added a `pytest` suite under `tests/`: synthetic IOS+NX-OS offline fixtures (3 switches: trunks, a 2-member port-channel, HSRP-redundant SVIs, a sole-gateway VLAN, a single-fiber uplink, an err-disabled port, a down OSPF neighbor); a **golden end-to-end regression** that runs the real `--no-collect` pipeline (`--workers 1`) and asserts the normalized `snapshot.json` + the Excel sheet-name/header schema (`tests/golden/`); and unit tests for the parsers and the `compute_*` intelligence functions (cap behavior + an explicit band-spread/anti-cry-wolf check). 27 tests, deterministic. The in-code version strings stay at `3.23.0` (same convention as V3.23.1). Run: `python -m pytest`; regenerate goldens after a reviewed change with `UPDATE_GOLDEN=1 python -m pytest tests/test_pipeline_golden.py`. |
| 2026-06-04 | **V3.23.1** — *connection resilience.* `connect_device` now retries transient/timeout SSH failures with linear backoff (`CONNECT_MAX_ATTEMPTS=3`, `CONNECT_BACKOFF_BASE=2.0s`); **authentication failures are never retried** (avoids account lockout). Platform autodetect runs once per device, not per retry. **No behavioural change on first-attempt success.** Set `CONNECT_MAX_ATTEMPTS=1` to restore single-shot. Tolerant `netmiko.exceptions` import (falls back to message sniffing if the class isn't importable). Verified by a 4-scenario stub test (first-try success, auth no-retry, timeout retry-to-max, recover-on-2nd). Note: in-file docstring/argparse version strings and filename left at 3.23.0 (release-naming is the maintainer's call). **Also (C):** hoisted `Font` / `PatternFill` / `Alignment` / `get_column_letter` to module scope, removing **28 duplicate local imports** across the sheet writers — pure cleanup, no behavioural change (verified: module imports + all writers resolve the names globally). **Also (E):** `--compare` now exits with a clear `ap.error` message on a missing or malformed snapshot file instead of a raw traceback (verified: exit 2 + message for not-found and bad-JSON). **Also (A) — credentials.** Password is no longer a required field in the devices file. It now resolves in order: explicit `"password"` (back-compat) → per-entry `"password_env": "VAR"` (read from `os.environ`) → global `$CISCO_PASS` → a secure `getpass` prompt (once per username) **only on an interactive TTY** — an unattended/batch run never blocks and instead warns + leaves blank (those devices fail auth visibly via the no-retry path above). SSH-key auth intentionally not added. Verified: 6 cases (explicit, `password_env`, `$CISCO_PASS`, non-TTY warn-no-hang, TTY prompt-once-per-user, missing required key still raises). **Also (D) — observability.** Four previously-silent `except` swallows (`autodetect_platform`, `detect_platform_from_files`, `_load_cmd_output`, remaining-power calc) now emit a `logger.debug` breadcrumb; control flow and exception types are unchanged, so behaviour at the default INFO level is identical and only `--debug-*`/DEBUG surfaces the cause. The `ipaddress` in-prefix predicates were left broad on purpose (returning `False` on bad input is the correct answer, not a hidden error). |
| 2026-06-03 | **V3.23.0** — `compute_health_scores` + `Health Scores` sheet (Phase 28); `compute_migration_readiness` + `Migration Readiness` sheet (Phase 29); cross-layer findings gain `hosts`; `snap_dict["health_scores"]` + `["migration_readiness"]`; HTML 🏥 Health mode. Verified: 22 Python + 19 HTML + 9 end-to-end embed checks (scoring bands, 10-check readiness, node colouring, panel, empty states, snapshot re-parse). |
| — | (V3.22.0 and earlier: see the prior `.md`s) |
