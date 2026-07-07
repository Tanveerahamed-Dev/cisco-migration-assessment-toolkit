# NRFU / ATP Acceptance Plan — KEV-Exposure Remediation (2026-07-07)

**Verifier:** `nrfu-validator` (INDEPENDENT of the MOP author — proposer ≠ verifier). **Mode:** read-only; no
device writes; `--compare` skips SSH + template. **Sign-off:** reports PASS/FAIL + counterexamples; the
human/CAB accepts — the verifier never accepts its own results. **Tri-state:** every check → **PASS / FAIL /
NOT-VALIDATED**; NOT-VALIDATED is *blocking*, never silently promoted to PASS (Law 3).

**Grounded in:** `docs/security/kev-exposure-2026-07-07.md` · `docs/security/kev-exposure-2026-07-07-devices.json`
· PRE baseline `Migration_Assessment_AUTOFILLED_20260613_063201.snapshot.json` · engine observables
`cisco_toolkit/analyze.py` (`compute_software_risk` L5395 / `_surface_status` L5415 / `_SWRISK_SURFACE_KB`
L5287), diff `cisco_toolkit/html.py` (`compute_snapshot_delta` L61), CLI `--compare`
(`COLLECT_PARSE_V3_23_0.py` L1539).

## 0. Reconciled PRE baseline (measured — the ground truth POST is diffed against)

| Group | n | Measured current state |
|---|---|---|
| `smart_install_flagged` | 151 | 150 `verify` + 1 `exposed`. Exposed: **`AAS13-BC-CR02R03-TCDOH`**. Platform: **96 ios / 55 nxos**. |
| `http_server_flagged` | 63 | 61 `verify` + 2 `exposed`. Exposed: **`AAS13-BC-CR02R03-TCDOH`, `AS01-BC-CA01RA13-CXDOH`**. Platform: **8 ios / 55 nxos**. |
| `priority21_eol_and_exposed` | 21 | ⊆ `replace_upgrade_train` AND each carries a flagged surface = **Upgrade Wave 1**. |
| `replace_upgrade_train` | 54 | 54/54 non-blank `sw_version` (52 IOS XE 03.x, 2 NX-OS 6.x). |
| `not_collected_version` | 56 | 56/56 blank `sw_version` (50 Insufficient Data, 2 Critical, 4 Poor — still versionless). |

**Three independent-verifier facts that shape the criteria (each verified in code):**
1. **The diff only "sees" the 3 confirmed-`exposed` instances.** `compute_software_risk` emits a finding only
   for `exposed` surfaces (`if status != "exposed": continue`, analyze.py:5473) — a `verify→closed` transition
   produces **no** finding delta. Closure for the 150+61 `verify` devices is proven by the **per-device surface
   field + the live show command** (Part 1), NOT by `--compare`.
2. **ACL-restrict does not flip the engine flag** (detector anchors on `^ip http server$`, analyze.py:5425) —
   the restrict variant is certified on **ACL evidence**, not the engine flag.
3. **55 NX-OS + FEX flags are IOS-detector screening artifacts** — `vstack`/IOS `ip http server` are not the
   NX-OS model; CVE-2018-0171 / CVE-2023-20198 are IOS/IOS-XE. The PASS observable must be **platform-correct**;
   "feature not present on this platform" is a *validated* result only with positive confirmation, never inferred.

## 1. Surface-closed criteria

### 1A — Smart Install (`smart_install_flagged`) — CVE-2018-0171
- **SI-1 · IOS/IOS-XE (96):** PASS = live `show vstack config` shows not operating (`Role: none`/`Oper Mode:
  disabled`) **AND** POST `surfaces["smart-install"]` → `closed` (config has `no vstack`). FAIL = `Oper Mode:
  enabled`/`Role: client|director`, or surface still `exposed`, or a bare `vstack` remains. NOT-VALIDATED = no
  live output and no POST surface.
- **SI-1X · `AAS13-BC-CR02R03-TCDOH` (PRE `exposed`):** additional gate — POST `--compare` must list its Smart
  Install (High) finding under `findings.resolved`; still present → FAIL.
- **SI-2 · NX-OS (55):** PASS-by-non-applicability, **positively confirmed** — `platform=="nxos"` AND no
  `vstack` construct (NX-OS has none). The engine `verify` is a screening artifact.
- **SI-3 · FEX line cards:** N/A-by-architecture — parent Nexus certified (SI-2); FEX never logged into.

### 1B — IOS-XE Web UI (`http_server_flagged`) — CVE-2023-20198 / -20273
- **HS-1 · IOS/IOS-XE (8):** PASS(disabled) = `show ip http server status` → HTTP **and** HTTPS Disabled **AND**
  POST surface `closed`. PASS(restricted, only if the Web UI must stay up) = `ip http access-class <acl>` binding
  an ACL that permits **only** the mgmt host + the ACL body exhibited, HTTPS likewise — **coverage caveat:** the
  engine surface stays `exposed` (fact 2), so certification rests on the ACL evidence, and full-disable is
  weighted above restrict. FAIL = server Enabled with no access-class; NOT-VALIDATED = no live status + no POST.
- **HS-1X · `AAS13-BC-CR02R03-TCDOH` + `AS01-BC-CA01RA13-CXDOH` (PRE `exposed`):** POST `--compare` must show
  their Web-UI (High) finding under `findings.resolved` — the cleanest cases, the diff itself proves closure.
- **HS-2 · NX-OS (55):** observable `show nxapi`/`show feature | inc nxapi|http`; PASS = NXAPI/HTTP mgmt disabled
  or no unrestricted surface (positively confirmed). **HS-3 · FEX:** parent-certified, N/A-by-architecture.

## 2. Upgrade criteria (`replace_upgrade_train`, 54 — Wave 1 = the 21)

**`TARGET_RELEASE[wave]` = the PSIRT-fixed release per wave's model/train — PARAMETER-PENDING** (the KEV feed
lacks fixed-versions); until set, UP-1/UP-2 are **NOT-VALIDATED** (disclosed, never a fabricated version).
- **UP-1 · version lands on target:** POST `devices[host].sw_version == normalize(TARGET_RELEASE[wave])`; FAIL if
  still `03.`/NX-OS `6.` or a non-approved release; NOT-VALIDATED if blank.
- **UP-2 · train band cleared:** POST `train_band != "Replace/Upgrade"`.
- **UP-3 · health intact post-upgrade (no metric worse than PRE):** (a) health band rank not worse
  (`health.regressed`); (b) connected-interface count ≥ PRE (`cabling.n_went_down`); (c) OSPF/EIGRP/BGP
  adjacency count ≥ PRE (`routing_neighbors`, `protocol_health`); (d) ps/fan/temp OK + PSU/module count ≥ PRE
  (no line card lost after reload). Any single metric worse → FAIL.

## 3. Regression gate — `--compare` (no new harm)

`cisco-assess --compare <PRE> <POST> --output KEV_Remediation_Diff_<stamp>.xlsx` (per-wave pre/post):

| ID | Check | PASS | FAIL |
|---|---|---|---|
| RG-1 | Overall verdict | `CLEAN` | `REGRESSED`; `REVIEW` only if every reason reconciled in writing |
| RG-2 | No health regression | `health.n_regressed == 0` | any `health.regressed` new-rank > old |
| RG-3 | No new High/Critical (clean→finding) | `findings.n_opened_high == 0` | any opened Crit/High; *corroboration:* the 3 exposed SHOULD be in `findings.resolved` |
| RG-4 | No reachability regression | `reachability.assessed==True` AND `newly_blocked==[]` | any `newly_blocked`; `assessed==False` → NOT-VALIDATED (use UP-3c adjacency as compensating proof) |
| RG-5 | No physical/coverage loss | `cabling.n_went_down==0`; no `went_dark`; `switches.removed==[]` | a link DOWN / a device went dark / an unexplained newly-bad device |

The gate is **necessary but not sufficient**: a CLEAN diff does NOT prove closure for the `verify` devices
(fact 1) — closure is proven in Part 1. The gate only proves "no new harm."

## 4. Coverage-honesty gate — the 56 `not_collected_version` are BLOCKED

None of the 56 may receive a KEV PASS until a version is collected — exposure = UNKNOWN → NOT-VALIDATED →
BLOCKED (neither pass nor fail; "not observed" is never "not vulnerable"). Exit: a POST collection populates
`sw_version` (non-blank) + `config_assessable==True`, then the device enters Parts 1-2. Engine-enforced: a
freshly-collected bad device becomes `newly_assessed`/`newly_bad` → verdict REVIEW/REGRESSED, never silently
"improved" (html.py:86-101).

## 5. Verdict rule (rollup + single-counterexample law)

- **Per-device PASS** iff every *applicable* check PASS; FAIL iff any FAIL; else BLOCKED/NOT-VALIDATED (all 56
  not-collected start here).
- **Per-wave PASS** iff all devices PASS AND the wave `--compare` is CLEAN (or REVIEW fully reconciled) with
  RG-2…RG-5 satisfied.
- **Single-counterexample law:** one device FAIL, one unresolved NOT-VALIDATED, or one regression-gate
  counterexample → the **whole wave is NOT-PASS**. No percentage pass. Report the counterexample as **host +
  field + PRE→POST**.
- **Two parallel tracks:** Track A (surface closure) over 151+63; Track B (upgrade) over 54, Wave 1 = 21. Both
  under Part 3. Campaign trend: `cisco-assess --trend snap0 snap1 …` for monotonic improvement.

## Coverage-honesty about THIS plan (what is NOT yet validated)
- UP-1/UP-2 are **parameter-pending** until the PSIRT sweep sets `TARGET_RELEASE` (NOT-VALIDATED, not invented).
- RG-4 reachability may return `assessed==False` on this data (baseline carries `routing_neighbors` for only 5
  hosts) — where it does, it's "not validated," not "pass"; UP-3c adjacency is the compensating control.
- The `verify→closed` transition for the 150+61 devices is **invisible to the diff** — closure proven only by
  Part 1.
- NX-OS/FEX flags are screening artifacts — certified by platform-correct observables; "not applicable" = PASS
  only with positive confirmation.
