# Domain pack — Enterprise / SD-Access

A **retrieval lens**, not a standing agent (D6). Loaded by `cisco_toolkit.domain_packs.select_packs` **iff**
one of its architecture classes was *observed* in the snapshot's `architecture_coverage`. Surfaced on demand
as a `/council` lens for consequential campus/branch-WAN outputs.

**Architecture classes this pack reviews** (keys into `cisco_toolkit/design_advisor.py ::
_ARCH_COVERAGE_REGISTRY` — the registry owns the detector ids):

| class key | what | channel |
|---|---|---|
| `lisp` | SD-Access LISP fabric | ssh |
| `fhrp_detail` | First-hop redundancy (HSRP/VRRP/GLBP) | ssh |
| `port_security` | Access-edge port-security | ssh |
| `storm_control` | Storm control | ssh |
| `pim` | Multicast PIM-SM | ssh |
| `ipv6_fhs` / `ipv6_nd` / `ipv6_routing` | IPv6 first-hop security / addressing-DAD / routing | ssh |
| `qos_runtime` | QoS runtime (egress queue/policer drops) | ssh |
| `shadow_infra` | Undocumented / shadow infrastructure | ssh |
| `sdwan` | Cisco Catalyst SD-WAN (vManage) | json |
| `dmvpn` / `crypto` | DMVPN WAN overlay / IPsec encrypted WAN | ssh |

## Domain review checklist

- **SD-Access / LISP.** Fabric sessions up? Control plane (map-server / map-resolver) reachable? Border /
  edge nodes registered (no `lisp-fabric-session-down`)?
- **First-hop redundancy.** Exactly one active per HSRP/VRRP/GLBP group? Preempt **and** interface/object
  tracking configured so the active follows the uplink? No dual-active / no orphaned VIP.
- **Access edge.** Port-security suite present; storm-control action on edge ports; IPv6 first-hop security
  (RA-guard / DHCPv6-guard / ND-inspection) at the access edge.
- **Multicast.** PIM RP resilience (anycast-RP / MSDP)? Any RPF failure on an (S,G)?
- **IPv6.** DAD failures (duplicate address)? OSPFv3 / BGP IPv6 adjacencies up?
- **Runtime + hygiene.** Egress queue/policer drops within budget? Any undocumented / shadow device found
  before cutover (`discover-undocumented-infrastructure-before-cutover`)?
- **Branch WAN.** SD-WAN control connections + OMP peers up, devices reachable (vManage); DMVPN tunnels up;
  IPsec crypto sessions up.

## Coverage-honesty (Law 3)

`not-observed` ≠ healthy. No LISP capture / no vManage export means the fabric wasn't seen — flag it as an
evidence gap, don't render it clean.

## Promotion rule (D6 / D1)

Pack + lens only; standing sub-agent solely when a real engagement sustains the load and the eval proves the
pack insufficient (client-gated). Roster stays at 8.
