# Assessment executive brief — 303-device Cisco fleet (2026-07-07)

**Audience:** decision-makers (prioritize + resource). **Basis:** the engine's assessment of
`Migration_Assessment_AUTOFILLED_20260613_063201.snapshot.json`, plus a live CISA-KEV threat-intel sweep.
**Posture:** every figure is evidence-grounded and reproducible; all recommendations are **propose-only** —
no change has been made, and none happens without your CAB approval inside a maintenance window.

## Bottom line
The fleet carries **one urgent, actively-exploited exposure** and **four fleet-scale structural findings**
(credential/config-hardening · software-currency + health · an L1–L2 resilience *evidence gap* ·
inventory/shadow-L2). The urgent item is ready to close now with a **no-reload** change; the structural ones
are **programs or collections**, not single change windows, and need resourcing decisions. *Context: the
endpoint mix identifies this as a **broadcast/media facility** (Grass Valley, Dante/AES67 audio, cameras) —
live real-time A/V raises the stakes on the resilience gap (finding 4), and change windows must treat media
paths as production-critical.*

## The five findings, by urgency

| # | Finding | Scale | Urgency | Action ready? |
|---|---|---|---|---|
| 1 | **Actively-exploited surfaces** — Smart Install (CVE-2018-0171) + IOS-XE Web UI (CVE-2023-20198/-20273, CVSS 10) | 96 + 8 IOS devices (3 confirmed-`exposed` instances on 2 of them) | **NOW** — being exploited in the wild | ✅ **Phase-A CAB request drafted, QA-approved, no reload** |
| 2 | **Cleartext SNMP (v2c)** | **106 devices** | High — sniffable recon | ◑ Direction set (→ SNMPv3); needs the v3 credential scheme + NMS coordination |
| 3 | **Software-currency + health debt** | **217 (~72%) EoL/replace-grade** (+75 unknown-train, separately unassessed); **67% Critical/Poor** health; only **3.6% current** | Chronic — support + exposure risk | ◑ A phased refresh **program**; needs PSIRT fixed-versions + refresh budget |
| 4 | **L1–L2 resilience — *un-certifiable* from this data** (all 52 multi-gateway VLANs show no observed FHRP; 43 inferred topology chokepoints; `cable_map` absent) | Fleet-wide **evidence gap** | Blocks any resilience verdict | ✗ Needs a **targeted read-only collection** first (cheap) |
| 5 | **Config-hardening gaps** (247/253 = 98% with a VTY hardening gap; **73 devices High** weak local passwords; 32 permit-any ACLs; 74/253 with ≥1 High) | Fleet-wide | High — mgmt-plane + credential exposure | ◑ All **config-plane, no reload** — batch with SNMPv3 |

## Recommended sequence
1. **This maintenance window — approve KEV Phase-A** ([CAB request](../security/kev-phaseA-cab-request-2026-07-07.md)).
   Closes the actively-exploited surfaces, **no reload**, canary-first, independent NRFU acceptance. Lowest
   risk, highest urgency.
2. **Next window — one hardening wave** (all config-plane, no reload): **SNMPv2c → SNMPv3** (106) **+ VTY
   hardening** (247: SSH-only + `access-class` + `exec-timeout`) **+ local-password migration** (73 High
   Type-7→Type-8/9 + 64 `service password-encryption`). Fastest *fleet-wide* risk reduction. Prerequisite:
   agree the SNMPv3 auth/priv scheme + reconfigure the NMS/poller first (or monitoring goes dark).
3. **Program (quarters, not a window) — software-currency refresh** of the ~217 EoL/replace devices, phased
   by the per-device blast-radius pre-checks, targeting PSIRT-fixed releases.

**Sequencing aid:** the [device risk heat-map](device-risk-heatmap-2026-07-07.md) ranks all 253 devices by
**security-finding density** — **8 stack five risks** (KEV + weak-password + EoL + SNMP + VTY), **93 carry
≥ 4**. Batch those into **coordinated per-device touches** rather than three separate windows. **Read it
*alongside* the [blast-radius annex](../security/kev-remediation-blast-radius-2026-07-07.md) for change
sequencing** — the heat-map does **not** weight topological consequence, so the fleet's highest-confidence SPOF
(`DS-VSS-CAR3-R13`) ranks by blast radius there, not by finding-count here. *(Only the KEV wave carries full
MOP/NRFU/blast-radius rigor today; the hardening + currency waves will get the same before execution.)*

## What we need from you (the gates)
- **CAB approval** + a window for Phase-A (and later SNMP).
- **Cisco openVuln API credentials** — the fixed-version lookup is built and waiting on creds (turns the
  refresh targets from "TBD" into concrete releases).
- **A read-only collection** for the **50 not-collected / 56 version-unknown** devices — their risk is
  *unknown*, not clean, until we see them.
- **A targeted resilience + media collection** (FHRP/STP/CDP-LLDP topology/routing **+ multicast IGMP/PIM/RP,
  PTP timing, QoS, and L2 edge-protection** — BPDU-guard/DHCP-snooping/port-security) — cheap, read-only.
  Resolves the 52-VLAN "no FHRP" question **and** characterizes the media-transport + L2-containment dimensions
  a broadcast facility cannot go to change without. Converts the L1–L2 + media posture from **UNKNOWN** to
  assessable.
- **Refresh budget/roadmap** for the currency program (a fleet that is 3.6% current is a strategic, not
  tactical, decision).

## Coverage-honesty (what we are NOT claiming)
- "Not observed / not collected" is never "healthy" — 50 devices are unassessed and excluded from clean
  counts. `Verify-EoL` is a prompt to confirm against Cisco EoX bulletins, not a proven end-of-life date.
- The intel gives *which* CVEs and *whether* exploited, not the fixed release — that needs the PSIRT lookup.
- **Three coverage denominators, all correct + distinct:** **50** not-collected (no data) ⊆ **56**
  version-unknown (blank `sw_version`) ≠ **75** unknown-*train* (version present, lifecycle band unclassifiable).
- **Snapshot currency:** the evidence snapshot is dated **2026-06-13** (24 days before this report) — negligible
  for brownfield config/lifecycle, but re-collect immediately before any execution.
- **Dimensions NOT assessed (a stated scope boundary, not a silence — parsed-data-only limits):** **media
  transport** (multicast IGMP/PIM/RP, PTP timing, QoS) — *material for this broadcast facility*; **L3/L4
  control-plane, segmentation & AAA** (routing collected for only 5/303); **L2 edge-protection** (BPDU-guard /
  root-guard / DHCP-snooping / port-security — the containment for the 117 shadow-L2 ports). None claimed clean;
  each needs the targeted collection above.
- Nothing here is applied; every remediation is a reviewable artifact for your change process.

## Detail (for the engineering track)
Full grounded artifacts: KEV [finding](../security/kev-exposure-2026-07-07.md) · [MOP](../security/kev-remediation-mop-2026-07-07.md)
· [NRFU](../security/kev-remediation-nrfu-2026-07-07.md) · [blast-radius](../security/kev-remediation-blast-radius-2026-07-07.md)
· fleet [risk synthesis](fleet-risk-synthesis-2026-07-07.md) · [L1–L2 resilience](l1l2-resilience-2026-07-07.md)
· [config-hardening](config-hardening-2026-07-07.md) · [endpoint inventory](endpoint-inventory-2026-07-07.md).
