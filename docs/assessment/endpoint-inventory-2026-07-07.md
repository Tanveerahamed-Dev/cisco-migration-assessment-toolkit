# Endpoint inventory & shadow-L2 — what's actually connected (2026-07-07)

**Status:** PROPOSE-ONLY assessment finding (moderate severity — informational + one actionable item).
**Evidence:** `endpoint_identity` (5,127 endpoints) in `Migration_Assessment_AUTOFILLED_20260613_063201.snapshot.json`.

## Context — this is a broadcast / media facility (informs the whole engagement)
The endpoint mix is not a generic enterprise: **573 Broadcast A/V, 42 Audio (Dante/AES67), 43 Camera, 22
Robotics**, alongside **1,717 Server, 490 UPS/PDU, 262 VM/Hypervisor**. Top vendors include **Grass Valley
(Belden)** and DigiBoard next to HP/Dell/Cisco/APC. This is a **media/broadcast** network — which raises the
stakes on the L1–L2 resilience gap (finding 4): real-time A/V (Dante/AES67, ST 2110-class) is intolerant of
the STP reconvergence / gateway-failover uncertainty that finding flagged. Any change window must treat live
media paths as production-critical.

## The one actionable finding — 117 undocumented downstream L2 extensions
**117 access ports show `mac_count > 1`** (up to 5 MACs on a single port) — i.e. an **unmanaged switch or hub
hangs off that port**. Concentrated on a handful of hosts (`EVS01-BC-CAR7R181` = 6 such ports; several
access/FEX switches with 4). Each is **shadow L2**: uninventoried, unmanaged, and a
security + spanning-tree risk (an unmanaged switch can inject BPDUs, loop, or host rogue devices). These are
concrete targets to **physically trace and either adopt or remove before the migration** — they also relate to
the engine's `shadow_infra` detector.

## Visibility gap
**1,770 of 5,127 endpoints (35%) are class `Unknown`** (confidence: 1,767 inferred-high, 1,590 inferred-medium,
1,770 unknown) — a third of what's connected is unidentified. Not a risk per se, but it caps how completely any
security/segmentation posture can be asserted.

## Coverage-honesty (Law 3)
- `endpoint_class` is **inferred** (from MAC OUI / vendor / evidence), not authenticated — "Server" / "Camera"
  are best-effort classifications, not identity. 35% are honestly labelled `Unknown` rather than guessed.
- `mac_count > 1` is a strong **indicator** of a downstream switch/hub, but a few may be legitimate (a phone +
  PC daisy-chain, a virtualization host) — the 117 are a **trace-and-confirm list**, not 117 confirmed rogue
  switches.

**Bottom line:** the facility is media/broadcast (elevating the finding-4 resilience concern for live A/V), and
there are **117 undocumented downstream L2 extensions** to trace before cutover — plus a 35% endpoint-visibility
gap. Moderate severity; folds into the pre-migration dependency-mapping work, not an urgent change.
