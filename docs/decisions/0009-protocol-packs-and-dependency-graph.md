# 0009: Protocol packs and the cross-protocol dependency graph

**Date:** 2026-10-16 · **Status:** accepted ·
**Decided by:** Claude Code under the owner's explicit delegation ("take the decisions … you are the
leader") · **Related:** `docs/decisions/0008-engine-computes-interface-displays.md` (the engine computes,
the interface displays), `master-reference/content/capability-catalog.json` (closed capability catalog),
`master-reference/app/atlas/protocol-depth.json` (eight-family depth matrix),
`docs/universality-gap-register.md`, `docs/decisions/0002-batfish-twin-verify-spike.md`

## Context

On 2026-10-16 the owner asked whether Atlas covers the depth and width of networking protocols
(routing, forwarding, NAT, QoS, MPLS, segment routing and so on) and the interaction between them, for
example a spanning-tree problem that breaks HSRP, causes asymmetric routing and disturbs OSPF, across
every layer.

Measured on `main` at `9112a16e`, the answer is **no, not at that depth**:

- **Width.** The closed catalog (`capability-catalog.json`, version 2026.08.07) classifies 39 protocol
  capabilities: 22 partial, 17 missing, none current. The missing ones include IS-IS, SR-MPLS/SRv6/TI-LFA,
  advanced BGP, policy-based routing and route policy, SNMP, DNS/DHCP, MACsec and OAM.
- **Depth.** `protocol-depth.json` covers eight families: STP, EtherChannel, VTP, OSPF, BGP, EIGRP,
  FHRP and IPv6 routing. Collection and parsing are covered for all eight. Normalization, assessment
  and validation are partial for all eight, and simulation is missing for six. OSPF is assessed on
  neighbor state only, with no expected-neighbor denominator and no LSDB or area model. BGP covers only
  literal default/global IPv4-unicast peers; VRFs, VPNv4/EVPN, policy and best path are excluded.
- **Forwarding.** `traffic_assurance._BASE_LIMITATIONS` states that routing is not VRF-aware, that
  tunnels stop at the overlay RIB, that PBR and uRPF abstain, and that NAT, stateful sessions, zones and
  service chains are not modeled. `parse.py` accounts for every NAT statement, but no forwarding model
  consumes them. QoS is posture hints only.
- **Correlation.**
  - `analyze.compute_cross_layer_correlations` applies ten hand-written pairwise rules, CL-01 to CL-10,
    over the L1–L3 dependency map. Examples: a single-fiber uplink in front of a sole gateway, a sole
    gateway with no FHRP, an FHRP gateway with a tracked object down, and one switch implicated across
    several layers.
  - The STP election check reports a root bridge that is not the VLAN's gateway.
  - `protocol_kb` maps one protocol's observed state to its likely cause, for example OSPF EXSTART to an
    MTU mismatch.
  - `causal.compute_causal_flows` re-renders existing findings as trigger → mechanism → impact. It does
    not infer causes across protocols.
  - Traffic Assurance reports `symmetric`/`asymmetry` only for a declared five-tuple.
- **Time.** `parse.parse_syslog_events` keeps facility, severity, mnemonic and message but **no
  timestamp**. Its classifier has 14 kinds (MAC flap, err-disable, link flap and so on), and none of
  them is a protocol state change. So OSPF/EIGRP/BGP adjacency changes, HSRP/VRRP state changes, STP
  topology changes and line-protocol transitions cannot be ordered into a chain.

There is also a structural problem. Protocol depth lives in several hand-maintained lists: the CL
rules, the `protocol_kb` table, `protocol-depth.json`, and the catalog. That is the defect shape this
repository keeps relearning, a named subset standing in for the class.

## Decision

1. **Release 1 ships today's depth, stated honestly.** The Atlas scope band and the Trust drawer name
   the limits above. Deeper protocol modeling and cross-protocol correlation are the engine's next
   program. They are built modularly, not as a rewrite, and they are not interface work (ADR 0008).

2. **Each protocol family becomes one protocol pack.** Packs live in `cisco_toolkit/packs/` behind one
   registry, `PROTOCOL_PACKS`. A pack is the single owner of its family and declares:
   1. its read-only commands per platform, which feed the one collector command catalogue;
   2. a parser to a typed, normalized state model, tested against **real device output**, never a
      hand-made fixture;
   3. a denominator, *expected* (from configuration) against *observed* (runtime). Absent evidence is
      `unknown`, never healthy;
   4. checks, each returning `problem`, `ok`, `unknown` or `not_applicable` with evidence pointers;
   5. the objects it binds to (interface, VLAN, VRF, prefix, peer) and the facts it depends on from other
      packs: the **dependency edges**;
   6. the syslog signatures of its state changes;
   7. the question kinds it answers, each with a confirm-on-device command and expected value, served
      through the question registry and the `analysis_result/1` envelope.

   A packed family's row in the protocol-depth matrix is **generated** from its registration and its
   witness tests, so it is no longer hand-maintained.

3. **One dependency graph and one correlation pass** (`cisco_toolkit/protocol_graph.py`).
   - **Graph.** The nodes are (pack, object) facts. The edges are the dependencies the packs declare,
     joined to the existing physical/L2 dependency map.
   - **Correlation.** For each problem node, the pass walks upstream to the deepest problem that
     explains it (the root-cause candidate, labelled *Inferred*) and downstream to what it affects
     (the blast radius).
   - **Evidence.** Every hop carries evidence. A hop without evidence ends the chain as an explicit
     *unknown link*; it is never bridged.
   - **Existing rules.** CL-01 to CL-10 keep their ids and become instances of the graph. They are
     not removed in one step.

   The graph must be able to express these chains:
   - errored or flapping link → STP topology change on the VLAN → HSRP/VRRP state change on that VLAN's
     gateway → return traffic through the other gateway → stateful-firewall drop;
   - uplink down → HSRP track decrement → active gateway moves → STP root no longer on the active gateway
     → suboptimal or asymmetric L2 path;
   - MTU mismatch → OSPF stuck in EXSTART → missing route → BGP next hop unreachable → BGP peer Active;
   - IGP route to a loopback missing → LDP session down → L3VPN label path broken.

4. **One event timeline.** Packs contribute state-change signatures to the one syslog classifier, which
   also parses the device timestamp. Events are ordered per object, and only inside the collected log
   window. Ordering across devices is claimed only when the NTP evidence shows the clocks synchronized;
   otherwise it is `unknown`. Nothing is inferred outside the buffer.

5. **Asymmetry is a correlated finding, not only a declared-flow result.** For each gateway subnet, the
   FHRP active gateway is compared with the upstream routers' collected routes back to that subnet, and
   with STP root and firewall placement. *Outbound through A, return through B* is reported with
   evidence from both directions. Traffic Assurance's per-direction verdict still answers exact flows.

6. **Order of work.** Each wave is a series of small, independently reviewed PRs. At most one engine
   protocol stream runs at a time, alongside the interface stream.
   - **Wave 0: the contract, with no behavior change.** The registry, the pack contract, and generated
     depth rows. The eight existing families move into packs with the golden output byte-identical.
     Guards: every family `compute_protocol_health` emits has a pack, every pack has a generated
     matrix row, and every catalog protocol cell that a pack claims points to it.
   - **Wave 1: correlation on evidence already collected.** This answers the owner's example. It covers
     state-change events and timestamps, the per-object timeline, the dependency graph and correlation
     pass, the gateway/return asymmetry check, and the STP-root / FHRP-active / track chain. It feeds
     the plan's Phase 3 "Why" view.
   - **Wave 2: routing depth on a VRF foundation.** A VRF-aware RIB and Traffic Assurance; OSPF expected
     neighbors from configuration, plus areas, DR/BDR and MTU; BGP per VRF and address family, plus
     policy presence; EIGRP; static routes and redistribution.
   - **Wave 3: services in the path.** NAT inside Traffic Assurance (IOS and ASA/FTD, from the existing
     NAT accounting); a QoS model of MQC policies, the trust boundary and drop counters; CoPP; storm
     control, port security and IPv6 first-hop security.
   - **Wave 4: SP and data-center fabrics.** The MPLS LDP/L3VPN label path, IS-IS, SR-MPLS and TI-LFA,
     VXLAN-EVPN route types and VTEPs, and PIM/RPF depth.
   - **Out of scope until a separate decision:** wireless, model-driven and flow/packet telemetry, QUIC,
     RoCE/DCB and OT protocols.

7. **No per-protocol screens.** A pack adds question kinds and checks. The Atlas interface shows them
   through the same registries without new interface code. A pack that lands with no interface change
   is the success condition.

8. **Batfish stays an optional twin-verifier** for CLI remediations, per ADR 0002. It is not the
   forwarding model: it is a JVM service, models configuration rather than runtime state, and does not
   fit the one-folder portable bundle.

## Consequences

- The protocol-depth matrix and the catalog's protocol cells come from pack registrations instead of
  parallel hand-kept lists. A missing cell stays `missing` until a pack lands. A changed denominator is
  disclosed as scope evolution, per the catalog's own rule.
- Wave 0 keeps the golden and sample outputs byte-identical. Every later wave adds snapshot fields and
  lands with a reviewed golden regeneration.
- Correlated chains are *Inferred*. Evidence is shown at every hop, and an unknown hop is visible, so
  "not observed" never becomes "explained".
- The order puts what consultants meet most in brownfield campus and data-center work (L2/FHRP/IGP
  interaction, asymmetry, VRFs) ahead of SP-only depth.
