# Domain pack — SP / MPLS-SR

A **retrieval lens**, not a standing agent (D6). Loaded by `cisco_toolkit.domain_packs.select_packs` **iff**
one of its architecture classes was *observed*. Surfaced on demand as a `/council` lens for provider-core /
transport outputs.

**Architecture classes this pack reviews** (keys into `cisco_toolkit/design_advisor.py ::
_ARCH_COVERAGE_REGISTRY`):

| class key | what | channel |
|---|---|---|
| `mpls` | SP/MPLS (LDP / L3VPN / L2VPN) | ssh |
| `bfd` | BFD fast-failover | ssh |

## Domain review checklist

- **MPLS control plane.** LDP sessions up (no `mpls-ldp-session-down`)? L3VPN VPNv4/VPNv6 routes present per
  VRF? L2VPN pseudowires up (no `mpls-l2vpn-pseudowire-down`)? Label ranges / LFIB consistent.
- **Fast convergence.** BFD sessions up and **not** degraded (`bfd-session-down-failover-degraded`)? Timers
  (min-tx / min-rx / multiplier) consistent on both ends and matched to the protection SLA? BFD bound to the
  IGP/BGP/static clients it is meant to protect?
- **Redundancy / SRLG.** Primary and backup paths do not share a fate (SRLG-disjoint)? PE-CE dual-homing
  where the SLA requires it?

## Coverage-honesty + a known scope gap (Law 3, D9)

- `not-observed` for `mpls`/`bfd` ≠ healthy — it means no LDP/BFD state was captured.
- **Segment Routing (SR / SR-MPLS / SRv6) has no detector in the registry yet.** If SR is in scope, say so
  explicitly as a **coverage gap** — do not imply SR was assessed because MPLS was. (Batfish twin-verify,
  when it lands, is **CLI-half only** per D9 — controller fabrics stay on the existing detectors.)

## Promotion rule (D6 / D1)

Pack + lens only; standing sub-agent solely when a real engagement sustains the load and the eval proves the
pack insufficient (client-gated). Roster stays at 8.
