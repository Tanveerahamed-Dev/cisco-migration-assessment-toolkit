# Blast-Radius Annex — KEV Remediation (CAB gate P3 for the 2026-07-07 MOP)

**Author:** `topology-reachability-analyst` (read-only, forked snapshot, no device access). **Property under
test:** for each Wave-1 reload target, which downstream devices/hosts lose reachability, and is the box a SPOF
vs. a survivable redundant node. **Propose-only advice — no change authorized.**

**Evidence (all computed snapshot sections):** `failure_impact` (`cisco_toolkit/analyze.py:1063
compute_failure_impact` — removes each switch, recomputes per-VLAN endpoint→gateway reachability),
`link_centrality` (cut-edge `pairs_cut`), `endpoint_dependencies.dual_homed`, `endpoint_identity`,
`routes`/`routing_neighbors`, `fhrp`, `vpc`.

## COVERAGE BOUNDARY — read first (bounds every verdict below)

The model returns **High / Hard-partition for all 21 — but that is coverage-bounded, NOT proof of SPOF**,
because redundancy is barely represented in this collection:
- **FHRP parsed for 0 of 52 multi-gateway VLANs** (every one reads "N gateways but no FHRP"); the failover twin
  (`failover.py`) can't run — its input `fhrp_detail` is absent.
- **STP-backup provable for only 2 of 303 devices** fleet-wide (the detector *does* fire when redundancy is
  collected — so `backup=0` on the 21 is "no backup **collected**," not a broken check).
- **L3 is thin:** `routing_neighbors` = 5 hosts, `routes` = 47/303; only 2 of the 21 have a route table.

**Two rules the CAB must apply:**
1. **`stranded` is an upper bound and the counts OVERLAP — never sum them.** VLAN 208 holds 667 endpoints yet is
   "hard-partitioned" by 48 devices; the top-3 access boxes are largely the *same* VLAN-208 population attributed
   to each cut point. **VLAN 1 is flagged on 226 devices but holds 1 endpoint — treat as noise.**
2. **No SPOF verdict here is certified.** `stranded` is a valid *relative* ranking; the pass/fail SPOF fact needs
   the **per-device redundancy pre-check the MOP already mandates (P3 / §6.3)**. Flagged per device below.

## 1 + 3. Reload blast-radius, ranked (Phase B, the 21) + sequencing tier

None of the 21 have a model-proven external backup; none carry NIC-teamed (`dual_homed`) endpoints; VSS/stack
members have *chassis-internal* redundancy only, which a plain reload does **not** preserve (prefer ISSU/eFSU).

| # | Device | Role | SPOF? | Reload blast (collateral `stranded` / own) | Sequencing |
|---|---|---|---|---|---|
| 1 | AS20-MGM-CA11B29-Stack | Access stack 3850 | Yes (unproven-redundant) | **808** — VLAN208 (663)+VLAN200 (145); own 34 | ALONE + pre-check; don't batch w/ #2,#3 |
| 2 | AS21-MGM-TE421R02 | Access 3850 | Yes (unproven) | **789** — 208 (647)+200 (142); own 25 | ALONE + pre-check |
| 3 | AS25-BC-TR11SatR2-BCDOH | Access 3850 | Yes (unproven) | **636** — 208 (636); own 38 | ALONE + pre-check |
| 4 | **AS01-BC-CA01RA13-CXDOH** ⚠️canary | Access 3850 | Yes (unproven) | **294** / 7 VLANs; own 14 | ALONE; first in A2 (HTTP exposed) |
| 5 | 10GSW01-BC-CA11F17 | Nexus 6001 DC agg | Yes (unproven) | **286** — 12 (178)+25 (108); own 8 | **PAIR-CHECK w/ #6** — prove vPC/HSRP first |
| 6 | 10GSW02-BC-CA11F18 | Nexus 6001 DC agg | Yes (unproven) | **286** — 12+25; own 8 | never reload w/ #5 same step |
| 7 | **DS-VSS-CAR3-R13-ARDOH** | Distribution VSS 4500-X | **Yes — model+link-cut agree** (bridge `pairs_cut=12`) | **256** / 15 VLANs; own 4 | **highest-confidence true SPOF**; ALONE + pre-check |
| 8 | AS-BC-VSS-CAR07R07-AJDOH | Distribution VSS | Yes (unproven) | **147** — 200; own 0 | ALONE / eFSU; 200 overlaps #9,#10 |
| 9 | SW01-BC-CAR11RF16 | Distribution 4500-X | Yes (unproven) | **147** — 200; own 0 | don't co-reload w/ #18 (same RF16 block) |
| 10 | AS21-BC-TE421R01 | Access 3850 | Yes (unproven) | **145** — 200; own 9 | pre-check; TE421 cluster |
| 11 | AS22-BC-TE421R01 | Access 3850 | Yes (unproven) | **27** — 121; own 0 — cut-edge ↔ AS26 | **do NOT reload w/ #13** |
| 12 | AS20-BC-TR12SatR2-BCDOH | Access 3850 | Yes (unproven) | **22** — 121; own 5 | batchable, light pre-check |
| 13 | AS26-BC-TR11SatR2-BCDOH | Access 3850 | Yes (unproven) | **20** — 121; own 7 — cut-edge ↔ AS22 | **do NOT reload w/ #11** |
| 14 | ACS01-BC-CA11G20-PGDOH | Distribution 4500-X L3 | **Chokepoint — blast understated** | stranded 5 but **`pairs_cut=122`** | **Tier-1 despite low stranded**; collect downstream first |
| 15 | DS-VSS-AVID-CAR05-R37 | Distribution VSS | Yes (unproven) | **3** — 250; own 0 | low; confirm no live AVID media feed |
| 16 | AS22-BC-CA04R2-BCDOH | Access 3850 | **Low — self-contained** | **0**; own 9 | **safe to batch** |
| 17 | AS24-BC-TR11SatR2-Stack | Access stack | **Low — self-contained** | **0**; own 58 | **safe to batch** (largest local-only) |
| 18 | DS-VSS-BC-CAR6R1-CAR11RF16 | Distribution VSS | **Indeterminate — downstream off-scan** | 0 but **`pairs_cut=14`** | **understated — collect first**; pair-aware w/ #9 |
| 19 | DS-VSS-CA05R27CA11F17-SW | Distribution VSS | **Indeterminate** | 0; own 0 | 4500-X w/ 0 collateral implausible → collect first |
| 20 | DS01-DC-INVESTIGATIVE-AJSS | Distribution 4500-X | **Indeterminate** | 0; own 0 | collect first; confirm no evidentiary-system dep |
| 21 | DS21-BC-CA11G17 | Distribution 4500-X L3 | **Indeterminate** | 0; own 45 | route-server flag but 0 collateral → verify first |

## 2. Phase A mitigation impact (no reload)

- **Smart Install (`no vstack`, A1) — CONFIRMED INERT to the data plane.** TCP/4786 control-plane listener;
  appears in no VLAN/route/endpoint/gateway path. Disabling changes **zero** modeled reachability. (Only caveat,
  already in MOP A1: a live ZTP director is a provisioning-workflow dependency, not a reachability one.)
- **IOS-XE Web UI (A2, 8 IOS) — management-plane only; no modeled data-plane dependency on 80/443.** BUT the
  model does **not** represent mgmt-HTTP deps (RESTCONF / Prime / Catalyst Center) — absence here is **not** "no
  dependency." **Every one of the 8 needs OOB console confirmed before the change (MOP P6).** Highest lock-out
  consequence: **AS01/AS02-BC-CAR11RD22** (L3, stranded 527 each, **`not_collected_version` → platform unknown →
  prefer ACL-restrict over disable, verify platform first**); then the 2 exposed canaries (console mandatory);
  then DS17-20 (L3, stranded 147 each).

## Sequencing recommendation
1. **Canaries first, both phases** (`AAS13`, `AS01-BC-CA01RA13`), console standby.
2. **ALONE + redundancy pre-check:** #1 AS20-MGM, #2 AS21-MGM, #3 AS25-BC, #4 AS01-CA01RA13, **#7 DS-VSS-CAR3-R13
   (highest-confidence SPOF)**, **#14 ACS01 (hidden Tier-1 by link-cut)**.
3. **Prove the pairing, then one-at-a-time:** 10GSW01 ↔ 10GSW02.
4. **Never co-reload cut-edge pairs:** AS22 ↔ AS26; keep SW01-RF16 and DS-VSS-…-RF16 in separate windows.
5. **Collect downstream BEFORE scheduling** the four `stranded=0` distribution 4500-Xs (#18–#21).
6. **Batch safely:** AS22-BC-CA04R2 (own 9), AS24-BC-TR11SatR2 (own 58) — 0 collateral.
7. **VSS/stack members:** prefer **ISSU/eFSU** — a plain reload drops the whole logical unit.

## 4. Coverage-honesty ledger (explicit "not certified" set)
- **Blast UNKNOWN / understated → needs collection** (never infer "safe"): #18 DS-VSS-BC-CAR6R1, #19
  DS-VSS-CA05R27, #20 DS01-DC-INVESTIGATIVE, #21 DS21-BC-CA11G17 (stranded 0, downstream off-scan); #14 ACS01
  (stranded 5, `pairs_cut=122`).
- **Redundancy NOT certified for all 21** — FHRP 0/52, STP-backup 2/303, `fhrp_detail` absent. The per-device
  redundancy pre-check (MOP P3/§6.3) is a hard prerequisite.
- **Platform/version unknown**, used in A2: AS01/AS02-BC-CAR11RD22 (`not_collected_version`).

**Bottom line for the CAB:** the ranking (by `stranded`, corroborated by `link_centrality`) is deterministic and
grounded, but the L2 model runs with **no first-hop-redundancy visibility**, so it necessarily reports
worst-case. This annex gives the *sequence and the pre-checks*; it does **not** certify any device as redundant
or as a proven SPOF — that requires the P3 per-device redundancy confirmation before each window.
