# Wave backlog — full triage verdict (2026-06-21, 4 parallel agents vs live code)

150 findings triaged against CURRENT code. Counts: ~16 DONE (prior sessions), ~9 FALSE/blocked,
~50 ACTIONABLE, rest MARGINAL.

## SESSION PROGRESS (2026-06-22) — implemented + verified (all green: engine suite 565)
DONE this arc (deliverables regenerated + INDEPENDENT-QA-validated, 3 blocks found → all fixed):
- Tier-1: HON-design-unguarded-1 + HON-webapp-backend-001 (webapp-500 crash guards); DET-poe-002 (PoE-fault no
  longer description-gated); DET-capacity-04 (port-bound 90→85, golden regenerated clean); R2-1-02 (lifecycle
  date provenance); HON-webapp-frontend-2 (falsy-zero avg).
- Tier-1b coverage-honesty: scale.n_collected KEYSTONE (early-injected COLLECT_PARSE:1993 + assembly:2108) read by
  deck/engagement/ops covers ("253 collected of 303"), runbook §1 canonical 5127/202, runbook §8 active_ports
  guard, AND workbook Exec Summary (QA F1: "253 / 303" + QA F2: avg_health 41 not local-recompute 49).
- Tier-2 detectors: DET-fhrp-state-01 (broken-FHRP; 0× on AJ = coverage-honest), DET-syslog-3 (optic-degraded 39 +
  lacp-error 28 on AJ), DET-poe-001 (poe_util now real on 19 switches, was 0/303 — budget in `show power inline`).
- QA F3: runbook IGMP querier "1313 VLAN(s)" → "134 VLAN(s) (1313 querier records)".

STILL DEFERRED (scoped; need unhurried care — rushing risks cry-wolf / half-done):
- DET-cdp-lldp-001 (canon-host false-positive risk), DET-storm-001 (what-to-flag judgment),
  DET-fhrp-state-02 (0× on AJ — no FHRP), EX-workbook-002/-003 (write-before-assembly phase reorder).
- R2-7-02 (EoL %-denominator 70→86 — USER CALL). F4 (EoS vs LDoS shorthand — Info, non-blocking).

## FALSE / blocked (no collected evidence, or claim refuted) — DO NOT implement
R2-3-03 (asof already=collected_at), DET-ntp-001/002 (no clock-sync collected), DET-aaa-02 (no aaa_audit),
DET-capacity-02 (no mac_entries), DET-capacity-03 (no FIB/TCAM), DET-errdisable-002 (no errdisable_recovery),
DET-dhcp-snoop-01 (no L2 trust state), DET-mac-arp-003 (no aging-time collected).

## DONE already (verified in live code)
SSOT-vlan-deliv-01, SSOT-device-deliv-03, R2-2-03, SSOT-webapp-backend-001, EX-workbook-001, R2-2-01,
HON-mop-precision-1/2, DET-aaa-01, SSOT-device-deliv-01, HON-deck-headline-2, R2-7-03, DET-vpc-01,
DET-snmp-002, DET-capacity-01, EX-runbook-01(dup), R2-1-02(this session), DET-intf-errors-002(this session).

## ACTIONABLE — implement (grouped by file; from agent verdicts)
### Tier 1 — crash / false-health / customer-facing / SSOT keystone (DO FIRST)
- HON-design-unguarded-1 | design.py:179 | `bp.get("summary",{})` dict-default doesn't guard `summary:None` -> AttributeError 500s webapp; use `_sm=bp.get("summary") or {}`.
- HON-webapp-backend-001 | webapp/backend/summary.py:69,115 | eb/lr `or {}` raises on truthy non-dict; isinstance-guard + wrap engine.trend_point in try/except -> opaque 500 on malformed upload.
- R2-7-02 | analyze.py:5001 | EoL `lc_pct` denominator = n_devices(303) incl 56 Unknown -> 70% understates; use known=tot-n_unknown; label "% of devices with a known lifecycle".
- HON-analyze-falsehealth-1 | analyze.py:3924 | compute_golden_drift has no all_hosts; 50 uncollected vanish; add all_hosts param + not-assessable rows + n_not_assessable.
- DET-intf-errors-003 | design_advisor.py:242 | output_drops>0 not in _phy_dirty though sheet flags it; add (oper-up gated) to predicate + summary/sources.
- DET-capacity-04 | excel.py:587 | compute_capacity Port-bound at >=90 but detector _PORT_UTIL_HOT=85 -> 2 boundary switches blank in workbook; unify on 85.
- DET-poe-002 | analyze.py:2830 | PoE-fault gated by BOTH POE_FAULT and POWERED desc -> drops real faults on blank-desc ports; raise for any POE_FAULT, use desc only for severity.
- HON-webapp-frontend-2 | webapp/frontend/src/pages/Dashboard.tsx:14 | `{s.avg_health || "—"}` renders em-dash for legit 0; guard on typeof number.
- R2-4-03 | excel.py:2904 | `if eb.get("axes")` migration-brief block no else -> failed brief silently dropped; add "synthesis unavailable" row.
- SSOT-device-deliv-06 | analyze.py:5138 | scale lacks n_collected/n_inventoried; inject n_collected=collection_completeness.summary.complete at assembly (mirror n_vlans).
- HON-runbook-drop-1 | runbook.py:811 | §8 low_util no active_ports guard -> unobserved 0% sort to top; add isdigit(active_ports) filter.

### Tier 1b — "303 assessed/evidence-scope" coverage-honesty (relabel inventoried-vs-collected)
- SSOT-device-deliv-02 / EX-deck-02 | deck.py:166,187 | "303 switches assessed" -> in-scope + add "253 collected of 303".
- SSOT-device-deliv-04 / EX-engagement-001 | engagement.py:210 | "303 devices in evidence scope" -> inventoried + collected split.
- SSOT-device-deliv-05 | ops.py:115 | "303 devices in evidence scope" -> in scope / collected.
- EX-workbook-003 | excel.py:154 | inventory sheet no "Collected" column -> 50 blind-spots invisible; add Yes/No col.
- EX-workbook-002 | excel.py:374 | VLAN census shows 172 rows vs canonical 202; add reconciling banner.
- SSOT-endpoint-deliv-1 / EX-runbook-02 / HON-runbook-drop-2 | runbook.py:187,188,779 | headline endpoints=5292 (MAC sum) vs canonical 5127; VLANs=121 vs 202; surface canonical, demote subsets.

### Tier 2 — real detectors (evidence IS collected; bigger effort)
- DET-stp-001 | _d_stp_topology_instability (protocol_health STP TCN; threshold ~100000).
- DET-cdp-lldp-001 | _d_undocumented_neighbors (cdp_neighbor infra not in inventory).
- DET-qos-copp-001 | parse control-plane copp + copp-absent finding + _d_copp (L3 classic-IOS).
- DET-syslog-3 | analyze.py:4123 add optic-degraded (SFF8472/IF_UNSUPPORTED_TRANSCEIVER) + lacp-error kinds.
- DET-fhrp-state-01 | design_advisor.py:96 sig['fhrp_broken'] (split-brain strings) + _d_fhrp_state.
- DET-fhrp-state-02 | parse.py:137 bind HSRP priority/preempt -> split-active/preempt checks.
- DET-storm-001 | parse.py:679 InterfaceData.storm_control + _d_storm_control (121 lines/36 sw).
- DET-poe-001 | parse.py:2133 _parse_poe_inline_budget (Module budget row) -> poe_util.
- DET-intf-errors-001 | parse_interface_transceiver DOM + _d_optic_health (197 IOS devices have DOM; add `details` to collection for future).

### Tier 2b — archreview rigor (data already in snapshot)
- EX-archreview-2 | RES-4 magnitude escalation (>=20% endpoints -> deviation).
- EX-archreview-3 | RES-2 split FHRP absence vs real consistency mismatch.
- EX-archreview-4 | actions[:10] drops a deviation; take all critical+deviation first.
- EX-archreview-5 | multicast not reviewed nor declared NOT_ASSESSED; add honesty/check.
- EX-archreview-6 | RES-5 vPC/MLAG health check (reads snap['vpc']).

### Tier 3 — content / SSOT reconciliation
- EX-crd-002 (+Priority col §8), EX-crd-003 (positional REQ-D IDs -> stable), HON-crd-overclaim-2 (FHRP denom 231/0 -> 209).
- EX-deck-03 (axes[:4] drops High axes -> show all Critical/High).
- EX-hld-01 (§2.4 vPC table), -02 (§2.6 hardening), -03 (§2.3 BFD/convergence), -04 (§2.8 mgmt), -05 (§2.4 L1 policy).
- EX-lld-01 (§3.3 40-cap truncates 213 devices).
- EX-mop-2 (§x.6 add Why col), EX-mop-3 (mop.py:551 rollback tuple).
- R2-2-02 (snapshot-delta endpoint+VLAN deltas), R2-2-04 (diff-workbook Switches row -> use delta).
- R2-6-02 (lifecycle n_past_ldos_derived), R2-6-04 (lifecycle sheet Confidence col).
- EX-nrfu-001 (NRFU DOCX per-test body §2.2), EX-nrfu-002 (Phase II by-wave grouping).
- R2-9-01 (cutover_docx "Devices in scope" label collision + distinct count).
- SSOT-explorer-posture-001 (explorer Health-view reads canonical posture).

## MARGINAL — disposition won't-do (cosmetic / latent / enhancement; full list in agent transcripts)
DET-errdisable-001, EX-lld-02/03/04/05/06/07/08, R2-3-02/04(04 is actionable-trivial), EX-engagement-002/003,
EX-workbook-004/005, R2-6-03, DET-vpc-03/04, DET-mac-arp-001/002, DET-snmp-001, DET-syslog-4, EX-mop-4/5,
EX-ops-01/02/04/05, HON-design-unguarded-2/3/4/5, R2-3-04, SSOT-vlan-subsets-01, R2-11-3, HON-mop-precision-3,
DET-qos-copp-002, SSOT-posture-deliv-002/003, R2-6-05, R2-8-03, EX-crd-004, HON-crd-overclaim-3, R2-10-01,
HON-webapp-frontend-1, EX-nrfu-003/004, HON-archreview-passbysilence-OPS-4, SSOT-blueprint-decisions-001, HON-ops-baseline-1.
