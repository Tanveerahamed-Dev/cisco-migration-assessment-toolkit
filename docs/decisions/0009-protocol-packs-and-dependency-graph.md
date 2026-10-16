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

## Amendment 1 (2026-10-16): every OSI layer

**Status:** accepted · **Decided by:** Claude Code under the owner's delegation · **Evidence:** a read-only
code audit of `main` at `9112a16e`. An independent refuter pass checked Layers 1 to 3; Layer 4 was mapped but
not refuted. Nothing was executed. Every defect below was found by reading code and must be reproduced on
real device output before its fix lands.

### What the audit found

- **Layer 1 is the shallowest layer.** Interface state, error counters, duplex, PoE and power supplies are
  judged, but never against an expected value. `_ARCH_COVERAGE_REGISTRY` has no Layer 1 class.
- **Optics are collected and never parsed.** `show interface transceiver` (NX-OS) and `show interfaces
  transceiver` (IOS) have no parser, and `parse_show_inventory` drops optic entries. The only optic signal
  is a syslog mnemonic. Module and PSU part numbers are parsed but unused; lifecycle covers the chassis only.
- **Not collected:** UDLD state, stack members and ring, supervisor redundancy, the err-disable cause,
  transceiver thresholds, MAC-table counts, DHCP-snooping and DAI state, and the IPv6 neighbor table.
- **In the collected running-config but not parsed:** UDLD, loop guard, BPDU filter, MST region,
  errdisable recovery, DAI, IP Source Guard, private VLANs, CDP/LLDP enablement, and configured speed,
  duplex, negotiation and `shutdown`. PortFast is parsed and then dropped.
- **MTU.** The `MTU N bytes` line of `show interface(s)` is not parsed. A bare `mtu` line is stored, but
  `fib._hop_mtu` reads only `ip_mtu` or an `effective_ipv4_mtu` token that no producer emits. The only
  both-ends MTU check is explorer JavaScript, and it treats an unset MTU as 1500.
- **CDP/LLDP.** The advertised native VLAN, duplex and VTP domain are not parsed. An LLDP-only neighbor
  that was not collected never enters the topology, and CDP phones and APs are classified as switches.
- **Both-ends checks have competing owners.** Native VLAN is compared in `excel.py`, where a blank end
  becomes VLAN 1, and in `analyze.compute_findings`, which abstains on blanks. Allowed-VLAN asymmetry and
  link MTU are compared only in the explorer.
- **Absence or failure that can read as health:** absent and failed PSU rows count as supplies, so `RES-3`
  can grade a chassis redundant. `normalize_duplex` maps `a-half` and `a-full` to `Auto`, so
  auto-negotiated ends drop out of the duplex checks while the link still counts as compared. PoE `Deny`
  and `errdisable` rows escape the fault test. Root guard is written `Disable` where nothing was observed.
- **Wrong verdicts:** output drops are flagged as a cable or optic fault. LACP passive and PAgP members
  become static `On`, which can raise the static-EtherChannel decision. VRF-lite address reuse raises
  the duplicate-IP decision.

### Decision

1. **Every pack declares its OSI layer, and physical packs are the roots of the graph.** A chain that
   needs a physical fact that was not observed ends as an *unknown link*.
2. **Roster.** In addition to the eight families moved in Wave 0 (STP, EtherChannel, VTP, OSPF, BGP,
   EIGRP, FHRP, IPv6 routing):
   - **L1:** `interface` (state, configured and negotiated speed/duplex, every counter), `transceiver`
     (type, part number, serial, vendor, DOM), `chassis_environment` (PSU per bay, fans, temperature,
     PoE), `hardware_lifecycle`, `stack_redundancy`, `udld`, `errdisable`.
   - **L1/L2:** `neighbor_discovery` (CDP/LLDP), `link` (both ends), `mtu`.
   - **L2:** `vlan_trunk`, `vpc_mlag`, `storm_control`, `port_security`, `dhcp_snooping_dai_ipsg`,
     `dot1x_mab`, `ipv6_first_hop_security`. **L2/L3:** `address_tables` (MAC, ARP, IPv6 ND).
   - **L3:** `ip_addressing`, `vrf`, `static_rib`, `route_policy`, `object_tracking`, `bfd`, `isis`,
     `segment_routing`, `mpls`, `vxlan_evpn`, `multicast`, `wan_tunnels`, `lisp_sda`.
   - **L4:** `acl_filters`, `nat`, `qos`, `copp`, `stateful_firewall`.
   - **Services the timeline and posture need:** `time_sync` (NTP, PTP), `control_plane_health`,
     `management_security`.
   - **Out of scope:** cable diagnostics (TDR). On many platforms the test disrupts the port, which
     conflicts with read-only collection. Ingesting results an operator captured needs a separate decision.
3. **The `link` pack owns both ends.** A link is a pair of interfaces joined by CDP/LLDP. For speed,
   duplex and negotiation, trunk mode, native VLAN, allowed VLANs, LACP mode pairing, and description
   against neighbor, it returns `problem`, `ok`, `unknown` (an end or the value was not captured) or
   `not_applicable`. A blank value is never filled with a default. The denominator is links with both ends
   collected and the attribute captured, against all links observed. The `mtu` pack applies the same rule
   to MTU on the same link objects. Together they replace the competing native-VLAN owner and the
   explorer-only comparisons, and the explorer then displays the engine's result (ADR 0008).
4. **Waves.**
   - **Wave 0** is unchanged and its output stays byte-identical. None of the defect fixes above ride in
     it; each lands as its own PR with a test on real device output and a reviewed golden regeneration.
   - **Wave 1** first builds the roots from evidence already collected: `interface`, `transceiver` (from
     the current commands), `neighbor_discovery`, `link`, `mtu`, `chassis_environment`, `vlan_trunk`,
     `vpc_mlag`, `object_tracking` and `time_sync` (ordering events across devices needs NTP evidence). The
     EtherChannel pack gains a member physical-diversity check from member names. The correlation work
     decided above follows. Until Wave 2 adds the NX-OS commands, the track and FHRP-detail chain is
     IOS-only and reads `unknown` on NX-OS.
   - **Wave 2** opens with new read-only commands. Each gets a parser contract in
     `cmdio.PARSER_CONTRACTS` and a not-observed state: transceiver detail with thresholds, UDLD neighbors,
     err-disabled ports and recovery, stack and supervisor redundancy, NX-OS HSRP detail and `show track`,
     MAC-table counts, and IPv6 neighbors. It then adds `udld`, `errdisable`, `stack_redundancy`,
     `hardware_lifecycle` (which also needs component rows in the EoL registry), `address_tables`,
     `ip_addressing`, `static_rib`, `route_policy`, `bfd` and `control_plane_health`, alongside the VRF
     foundation and routing depth.
   - **Wave 3** adds the L2 security packs, `acl_filters`, `stateful_firewall` and `management_security`
     to the services already listed. **Wave 4** is unchanged.
5. **Guards.** Every command in `COMMANDS_NXOS` and `COMMANDS_IOS` is claimed by at least one pack or is
   on an explicit unclaimed list with a reason, so evidence that is collected but not parsed stays
   visible. The depth matrix gains an OSI-layer column generated from pack registrations, and an area with
   no pack reads `missing`.
