# L1–L2 resilience — current-state characterization (2026-07-07)

**Status:** PROPOSE-ONLY assessment finding (completes the L1–L4 layer coverage; L3–L4 = the fleet risk
synthesis + KEV). **Evidence:** `failure_impact`, `link_centrality`, `endpoint_dependencies`, `fhrp`, `vpc`
in `Migration_Assessment_AUTOFILLED_20260613_063201.snapshot.json`.

## Headline — resilience is NOT certifiable from this collection (and the partial signals are concerning)

The single most important L1–L2 result is a **coverage** result: this collection lacks the physical-topology
and first-hop-redundancy data needed to *certify* the fleet's resilience posture. What partial data exists
points the wrong way — but must be **verified by a targeted collection**, not acted on as-is.

| Signal | Measured | Honest reading |
|---|---|---|
| First-hop redundancy | **All 52 of 52** multi-gateway VLANs show **no observed FHRP** ("N gateways but no FHRP") | Either a **critical fleet-wide gap** (no HSRP/VRRP/GLBP → no automatic gateway failover) **or** FHRP is configured but was not captured. **Must verify.** |
| Physical chokepoints | **43 cut-edges** of 238 collected links (`link_centrality.is_bridge`) | Bridges *in the collected graph* — but **`cable_map` is null** (physical topology partly inferred), so some may be artifacts of incomplete cabling collection. Worst-case, 43 single links each partition a segment. |
| Modeled failure impact | **253 of 303** devices = `High` (hard-partition, no backup path); only **2** have a proven backup; **0** FHRP-covered | Coverage-bounded worst-case (per the KEV blast-radius annex: FHRP parsed 0/52, STP-backup 2/303). NOT 253 certified SPOFs. |
| Endpoint resilience | **224** dual-homed endpoints (`endpoint_dependencies.dual_homed`) | Some access-layer redundancy IS present — the one positive resilience signal collected. |
| vPC | **49** devices carry vPC config | Datacenter MLAG present; peer/keepalive health not certifiable from the collected fields (verify per pair). |

## What this means for the assessment
- The engine reports **worst-case** because redundancy evidence is thin — this is the model being
  coverage-honest, not a claim that the fleet has no redundancy. A tree-like inferred L2 graph with no FHRP
  visibility *necessarily* yields hard-partition everywhere.
- Therefore the assessment **cannot hand leadership a resilience verdict** (SPOF count, FHRP coverage, dual-homing
  gaps) from this data. It can only say: *the signals that exist are concerning, and a targeted collection is
  required to separate "real gap" from "not collected."*

## The one required next step (a collection, not a change)
A **targeted read-only resilience collection** — `show standby/vrrp/glbp brief`, `show spanning-tree summary`,
`show cdp/lldp neighbors` (physical topology → populates `cable_map`), `show ip route`/adjacencies, `show vpc`
— resolves the load-bearing question: **is the 52-VLAN "no FHRP" a real design gap or a collection gap?** That
answer determines whether first-hop redundancy is a top-priority remediation (if genuinely absent) or a
non-issue (if merely uncollected).

## Coverage-honesty (Law 3)
- `cable_map` and `stp` are **null** in this snapshot → the physical/spanning-tree layers are largely inferred
  or absent; do not read the 43 cut-edges or 253 hard-partitions as certified physical SPOFs.
- 50 devices are `not collected` (`Info` severity in `failure_impact`) → excluded, not "resilient".
- "No FHRP observed" is **not** "no FHRP configured" until the targeted collection above confirms it.

**Bottom line for the brief:** L1–L2 resilience is the assessment's **biggest evidence gap**, not a clean bill.
The partial signals (52/52 VLANs no-FHRP, 43 inferred chokepoints) justify a **targeted resilience collection**
as a priority — cheap, read-only, and it converts an UNKNOWN posture into an assessable one.
