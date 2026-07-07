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
| First-hop redundancy | **All 52 of 52** multi-gateway VLANs show **no observed FHRP** ("N gateways but no FHRP") | **Leans toward a real gap** — the engine parsed 459 real SVI IPs and found multiple gateways per subnet with **no shared virtual IP** (the missing-FHRP signature), and `hsrp_behavior` is uniformly empty. But the snapshot keeps *parsed* data, not raw configs, so it is **not certified** — a targeted FHRP collection confirms design-gap vs. parse-gap. |
| Physical chokepoints | **43 cut-edges** of 238 collected links (`link_centrality.is_bridge`) | Bridges *in the collected graph* — but **`cable_map` is null** (physical topology partly inferred), so some may be artifacts of incomplete cabling collection. Worst-case, 43 single links each partition a segment. |
| Modeled failure impact | **253 of 303** devices = `High` (hard-partition, no backup path); only **2** have a proven backup; **0** FHRP-covered | Coverage-bounded worst-case (per the KEV blast-radius annex: FHRP parsed 0/52, STP-backup 2/303). NOT 253 certified SPOFs. |
| Endpoint resilience | **224** dual-homed endpoints (`endpoint_dependencies.dual_homed`) | Some access-layer redundancy IS present — the one positive resilience signal collected. |
| vPC | **49** devices carry vPC config | Datacenter MLAG present; peer/keepalive health not certifiable from the collected fields (verify per pair). |

## STP root analysis — the under-used signal, now mined (`stp_roots`: 248 devices / 271 VLANs)

The collected spanning-tree root data is **not** bounded by the physical/FHRP gaps, so it yields real signal —
one positive, one concern:

- **Positive — root placement is intentional, not accidental.** 100 devices are STP root for ≥1 VLAN, and the
  top holders are all **distribution/core**: `DS-VSS-CAR3-R13-ARDOH` (22 VLANs), `CS01/CS02-BC-CA21…` (18
  each), `DS05`–`DS10` (12–13 each). Roots sit on the aggregation layer, **not** on access switches — the STP
  design is deliberate. (Corroboration: `DS-VSS-CAR3-R13`, the KEV blast-radius annex's highest-confidence
  SPOF, is also the single largest root-holder — the two independent analyses agree.)
- **Concern — 78 of 271 VLANs show INCONSISTENT roots** (devices disagree on the root bridge; VLAN 9 is seen
  with **7** distinct roots). For a *single* bridged domain that is STP instability/misconfiguration; for a
  VLAN **ID reused across separate L2 domains** (common in a large campus) it is expected. Distinguishing
  needs the physical topology (`cable_map`, absent) — so this is a concrete, prioritized item for the targeted
  collection, not a standalone verdict.
- **Concentration:** two aggregation devices root ~122 and ~110 VLANs — a concentration point, mitigated only
  if they are the redundant halves of a VSS/vPC pair (verify).

## What this means for the assessment
- The engine reports **worst-case** because redundancy evidence is thin — this is the model being
  coverage-honest, not a claim that the fleet has no redundancy. A tree-like inferred L2 graph with no FHRP
  visibility *necessarily* yields hard-partition everywhere.
- Therefore the assessment **cannot hand leadership a resilience verdict** (SPOF count, FHRP coverage, dual-homing
  gaps) from this data. It can only say: *the signals that exist are concerning, and a targeted collection is
  required to separate "real gap" from "not collected."*

## The one required next step (a collection, not a change)
A **targeted read-only resilience + media collection** — `show standby/vrrp/glbp brief`, `show spanning-tree
summary`, `show cdp/lldp neighbors` (physical topology → populates `cable_map`), `show ip route`/adjacencies,
`show vpc`, **plus the media-transport + L2-containment commands (below)** — resolves the load-bearing question:
**is the 52-VLAN "no FHRP" a real design gap or a collection gap?** That answer determines whether first-hop
redundancy is a top-priority remediation (if genuinely absent) or a non-issue (if merely uncollected).

> **Media transport — NOT ASSESSED (this snapshot's parsed data cannot speak to it).** This is a broadcast/media
> facility (finding: endpoint inventory — ST2110/Dante/AES67), where live A/V is **multicast + PTP-timed +
> QoS-critical** — precisely the dimensions most sensitive to the resilience uncertainty above. None are
> characterized here. Add to the collection: `show ip mroute` / `show ip igmp snooping` / PIM-RP state,
> `show ptp clock`/`show ptp foreign-masters`, QoS policy-maps + `show mls qos`/queue drops, and L2 edge
> protection (`show spanning-tree inconsistentports`, BPDU-guard/root-guard/DHCP-snooping/`port-security`
> status). Do not schedule an A/V-path change until this is collected.

## Coverage-honesty (Law 3)
- `cable_map` is **absent** (physical topology inferred) → this is what bounds the numbers: do not read the 43
  cut-edges or 253 hard-partitions as certified physical SPOFs. **STP data, by contrast, IS present** —
  `stp_roots` holds per-VLAN root elections for **248 devices** (77 distinct root MACs, 100 devices root for
  ≥1 VLAN) plus per-interface STP state — **now mined** (see *STP root analysis* above: intentional
  distribution/core root placement, but 78/271 VLANs show inconsistent roots). The L2 layer is
  better-collected than the physical layer.
- 50 devices are `not collected` (`Info` severity in `failure_impact`) → excluded, not "resilient".
- "No FHRP observed" is **not** "no FHRP configured" until the targeted collection above confirms it.

**Bottom line for the brief:** L1–L2 resilience is the assessment's **biggest evidence gap**, not a clean bill.
The partial signals (52/52 VLANs no-FHRP, 43 inferred chokepoints) justify a **targeted resilience collection**
as a priority — cheap, read-only, and it converts an UNKNOWN posture into an assessable one.
