# Universality Gap Register (2026-06-22) — toward a universal ASNE

Source:  wave (36 agents, 12 architecture classes; engine-coverage audit @ file:line + CCIE/CCDE capability research @ primary Cisco sources). Full detail: .

**Verdict: 0 strong / 6 partial / 6 absent. 278 build items (140 P1 / 91 P2 / 47 P3).**

| Architecture | Coverage | P1 | Headline gap |
|---|---|---|---|
| NX-OS / Nexus DC Switching | partial | 12 | VXLAN-EVPN — the engine's own target fabric — has ZERO data/control-plane visibility: nothing collects `show n |
| Cisco ACI fabric | absent | 19 | No APIC evidence channel exists: the engine is 100% SSH show-command driven (COMMANDS_NXOS/IOS, netmiko cisco_ |
| Cisco Catalyst SD-WAN | absent | 10 | The entire SD-WAN overlay is collection-blind: COLLECT_PARSE_V3_23_0.py emits zero `show sdwan ...` commands,  |
| SP / MPLS core | absent | 16 | The engine collects and parses ZERO MPLS/SR/VPN state (no LFIB, no LDP/RSVP-TE, no VPNv4/v6, no EVPN, no SRGB/ |
| Cisco IOS-XE Campus & SD-Access | absent | 15 | The engine is fabric-blind: zero LISP/VXLAN/CTS/device-tracking/StackWise parsers exist and every campus-sda-* |
| First-Hop Redundancy | partial | 10 | The engine collects 'show standby all' but parses only the brief form — so priority, preempt, tracking, authen |
| IPv6 / dual-stack | absent | 8 | The engine collects ZERO `show ipv6 *` commands — so every downstream IPv6 axis (FHS, HSRPv6, addressing, NAT6 |
| Multicast | partial | 12 | The entire PIM-SM control plane is blind: no RP discovery/redundancy (rp mapping/rp-hash), no RPF integrity (t |
| QoS & media transport | partial | 12 | The engine audits QoS/PTP INTENT (running-config) only and never reconciles it against RUN-STATE — none of the |
| Classic Cisco WAN overlays | absent | 10 | Zero overlay-control evidence is collected — no show dmvpn/ip nhrp/crypto session/crypto gdoi/domain master ou |
| Control/management-plane hardening | partial | 8 | CoPP/CPPr health is the biggest gap: the engine can name a control-plane service-policy (parse_qos_config.glob |
| Management & Assurance plane | partial | 8 | Model-Driven Telemetry + programmatic management (NETCONF/RESTCONF/gNMI/MDT) is completely unobserved — no col |

## P1 build worklist (by architecture)

### NX-OS / Nexus DC Switching — partial (12 P1)
> VXLAN-EVPN — the engine's own target fabric — has ZERO data/control-plane visibility: nothing collects `show nve interface|peers|vni` or `show bgp l2vpn evpn`, so anycast-gateway, RD/RT, NVE-peer-Up and EVPN-RR health (the things the senior checklist hinges on) cannot be assessed at all.

- **[parser/M]** Collect VXLAN/EVPN data+control-plane: add 'show nve interface nve1 detail', 'show nve peers', 'show nve peers control-plane-vni', 'show nve vni', 'show bgp l2vpn evpn summary', 'show bgp l2vpn evpn'   
  ↳  — VXLAN-EVPN control/data plane up: NVE peers Up (CP-learned), iBGP-EVPN RR neighbors established, VNI<->VLAN/L3VNI mapping present, BUM via P
- **[parser/M]** parse_nve_interface() + parse_nve_peers() + parse_nve_vni(): return {nve:{admin,oper,source_loopback,vtep_ip,secondary_anycast_ip}}, [{peer_ip,state,learn_source}], [{vni,vlan_or_l3vni,mode_cp,state,m  
  ↳  — show nve interface (source+secondary anycast IP), show nve peers (State Up, learn-source CP), show nve vni (VNIs CP/Up, mcast/IR).
- **[parser/M]** parse_evpn_summary() + parse_evpn_routes(): EVPN address-family neighbor table {neighbor,as,state,pfx} and route-type tallies (Type-2 MAC+IP / Type-3 IMET / Type-5 prefix), plus duplicate-RD / RT-mism  
  ↳  — show bgp l2vpn evpn summary (RR/peer Established) + show bgp l2vpn evpn (route-types 2/3/5 present; unique RD per VTEP, RT import/export con
- **[analysis/M]** build_overlay(cmd_to_file): safe-parse the NVE/EVPN parsers into a snapshot key snap['overlay']={nve,nve_peers,nve_vni,evpn_summary,evpn_routes}; register in COLLECT_PARSE assembly (mirror the build_v  
  ↳  — One-source overlay state surfaced once for every reader; evidence-gated, '' when feature absent (not silently healthy).
- **[detector/M]** _d_anycast_gateway_consistency(): fire when a VXLAN-extended VLAN's SVI lacks 'fabric forwarding mode anycast-gateway' or the global anycast-gateway-mac is missing/divergent across VTEPs; cite the SVI  
  ↳  — Every stretched-VLAN SVI uses anycast-gateway with one global anycast-gateway-mac (any other mode unsupported) -> prevents duplicate-IP/asym
- **[detector/M]** _d_evpn_readiness(): evidence-driven readiness fire — NVE peers not Up, EVPN RR neighbor not Established, missing/duplicate RD or RT mismatch, or underlay/BUM path absent; distinct from the existing c  
  ↳  — NVE peers Up + iBGP-EVPN RRs Established + unique RD/correct RT + IGP underlay/PIM-or-IR BUM path; flag any leg down.
- **[parser/M]** Collect + parse FEX: add 'show fex', 'show fex detail', 'show interface fex-fabric' to NX-OS collection; parse_fex_inventory() -> [{fex_id,state,model,image,desc,fabric_links,single_or_dualhomed,pinni  
  ↳  — show fex detail (state Online/AA, image match); show interface fex-fabric (>=2 fabric links / port-channel).
- **[detector/M]** _d_fex_resilience(): fire on single-homed straight-through FEX where ToR redundancy is expected, FEX not Online (Discovered/AA-version-mismatch), pinning max-links>1 with a failed member, or under-pro  
  ↳  — FEX dual-homed Active-Active via vPC where redundancy required; single-homed straight-through FEX is an SPOF; host ports never used for L3/u
- **[fixture/M]** NX-OS NVE/EVPN/FEX parser fixtures: add representative 'show nve peers/vni', 'show bgp l2vpn evpn summary', 'show fex detail' captures (healthy + degraded: down peer, RT mismatch, single-homed FEX) to  
  ↳  — Parsers tolerate NX-OS variants and degrade to {} on feature-absent; degraded captures prove the detector fires.
- **[parser/M]** Collect + parse vPC consistency-parameters & role/keepalive: add 'show vpc consistency-parameters global', 'show vpc consistency-parameters vpc <id>', 'show vpc role', 'show vpc peer-keepalive'; parse  
  ↳  — Type-1 rows 'success' (else vPC/VLANs SUSPENDED); flag Type-2 drift; deterministic role (priority+system-priority not both default).
- **[detector/S]** _d_vpc_split_brain_risk(): fire when peer-keepalive runs over the peer-link path or in default VRF (PKL dst-interface == peer-link members, or vrf=default) -> dual-active/split-brain on peer-link loss  
  ↳  — vPC peer-keepalive on a path SEPARATE from the peer-link, in a separate (mgmt) VRF — never over the peer-link or default VRF.
- **[detector/M]** _d_vpc_consistency_type_mismatch(): fire on Type-1 consistency 'failed' (global or per-interface) naming the offending param (STP mode/MST region, MTU, port mode, allowed-VLAN, LACP mode) and the susp  
  ↳  — Type-1 consistency success globally + per-interface; Type-2 consistent (else silent forwarding asymmetry).

### Cisco ACI fabric — absent (19 P1)
> No APIC evidence channel exists: the engine is 100% SSH show-command driven (COMMANDS_NXOS/IOS, netmiko cisco_nxos/ios) with zero REST/moquery transport — so an ACI fabric cannot be collected at all, and every ACI check (faults, quorum, contracts, L3Out) is unbuildable until an acidiag/moquery+REST collection path and a faultInst-grounded false-health gate land first.

- **[parser/L]** ACI evidence channel: add an APIC collection mode to the collector — SSH-to-APIC running acidiag avread/fnvread + a curated moquery -c <class> batch (and/or HTTPS REST token+class-query), writing one   
  ↳  — Coverage-honesty note (6): ACI state comes from APIC/ND REST/moquery, NOT show-over-SSH — without this channel nothing downstream is engine_
- **[parser/M]** parse_acidiag_avread() — parse APIC cluster membership: per-controller adminSt(in-service), operSt(available), health(fully-fit), chassis/serial, and active-vs-target cluster size.  
  ↳  — APIC cluster not Fully Fit / split-data-layer / active-size<target / even-or-<3 size (quorum 3/5/7) — config writes unsafe
- **[parser/M]** parse_acidiag_fnvread() — Fabric Node Vector: node-id, name, role(leaf/spine), serial, TEP, registration state; flag any not 'active'/Fabric-discovered.  
  ↳  — Fabric discovery/membership gaps: registered count != expected, nodes unknown/undiscovered/inactive/decommissioned, ghost serials
- **[parser/M]** parse_moquery_faultinst() — parse faultInst / faultCountsWithDetails rows into {code,sev,dn,descr,lc}; index by node and by code (F0467, F1394, F1545).  
  ↳  — Open Critical/Major faults masked by a green health score — the #1 ACI false-health trap; 'no faults' must come from an actual faultInst que
- **[parser/M]** parse_moquery_topsystem() + parse_moquery_firmware() — one row/node (role,serial,version,podId,TEP,uptime,currentTime) and firmwareRunning/firmwareCtrlrRunning + firmwareFwGrp/maintUpgStatus.  
  ↳  — Firmware uniformity & recommended-release conformance; version-skew baseline; nodes outside a firmware group / stuck mid-upgrade
- **[parser/L]** parse_moquery_tenant_model() — fvTenant/fvCtx/fvBD/fvAEPg/fvSubnet dump into a Tenant>VRF>BD>EPG tree: VRF pcEnfPref(enforced/unenforced)+pcEnfDir, BD flags(unkMacUcastAct,arpFlood,unicastRoute,limitI  
  ↳  — Logical-model conformance: VRF enforcement mode, BD flooding posture, IP-dataplane-learning, subnet/gateway scope
- **[parser/L]** parse_moquery_zoning_rule() / parse_zoning_rule() — programmed zoning-rules (srcPcTag,dstPcTag,filter,scope/VRF,action permit|deny|redir) + vzAny/vzRsAnyToCons/Prov + Preferred-Group posture.  
  ↳  — Over-permissive/effectively-unenforced segmentation (vzAny permit-all, Preferred-Group, VRF Unenforced) AND programmed-rule-vs-intended-cont
- **[parser/M]** parse_moquery_l3out() — l3extOut/l3extInstP/l3extSubnet/l3extRsPathL3OutAtt: routing protocol, ext-EPG subnet scope flags(import-security,shared-security,shared-rtctrl,export-rtctrl,aggregate), SVI MT  
  ↳  — L3Out external-EPG too broad (0.0.0.0/0 classifier) / missing route-control scoping; L3Out SVI MTU mismatch vs external router
- **[parser/L]** parse_moquery_access_chain() — infraAccPortGrp/infraRsAttEntP(AAEP)/infraRsDomP/infraRsVlanNs/fvnsEncapBlk/fvRsDomAtt: reconstruct the Interface-PG→AAEP→Domain→VLAN-pool→EPG binding chain.  
  ↳  — Access-policy binding chain broken — the root cause of F0467 'encap not deployed' (the #1 reason a VLAN silently never passes on a leaf)
- **[detector/M]** compute_aci_controller_health(avread, infraWiNode) — APIC quorum/fully-fit axis: emit Critical if any controller not in-service+available+fully-fit, Data-Layer-Partially-Divergent, active<target, or c  
  ↳  — APIC cluster not Fully Fit / split-data-layer / sub-quorum (severity high)
- **[detector/M]** compute_aci_fault_surface(faultInst, healthInst-per-node) — fault-grounded false-health detector: list open Critical/Major faults per node, and explicitly flag any node with a high health score AND op  
  ↳  — Open Critical/Major faults masked by a green health score — the primary ACI false-health trap (F0467/F1394)
- **[detector/M]** compute_fabric_membership(fnvread, topSystem vs intended inventory) — discovery-gap axis: nodes not 'active', count mismatch vs devices.json, version skew across the fleet.  
  ↳  — Fabric discovery/membership gaps + firmware/version-skew baseline (severity high)
- **[detector/L]** compute_contract_reachability(zoning_rule, fvCtx, vzAny) — segmentation-posture axis: VRF Unenforced, vzAny/Preferred-Group permit-all, broad VRF-scope permit; and contract-vs-programmed-rule mismatch  
  ↳  — Over-permissive segmentation + programmed-zoning-rules diverge from intended contracts (aci-policy-contract-route-is-not-reachability)
- **[detector/L]** compute_access_policy_hygiene(access_chain) — bind-chain integrity axis: EPG→domain whose VLAN pool lacks the encap, AAEP not tied to PG/domain, static-port encap reused across two EPGs on a leaf, dom  
  ↳  — Access-policy binding chain broken / F0467 encap-not-deployed (aci-fabric-access-policy-chain-ssot)
- **[detector/M]** compute_l3out_health(l3out) — external-connectivity axis: 0.0.0.0/0 ext-EPG anti-pattern, missing import/export/shared route-control where transit/shared intended, SVI-MTU mismatch, single-routing-pro  
  ↳  — L3Out external-EPG classifies-not-filters + MTU/route-control errors (aci-fabric-l3out-external-epg-classifies-not-filters)
- **[fixture/L]** ACI fixtures — golden sample collection dir with representative acidiag avread/fnvread, moquery faultInst (incl. one F0467 + one F1394), topSystem, firmwareRunning, fvCtx/fvBD/fvAEPg, zoning-rule, l3e  
  ↳  — Evidence-grounded & coverage-honest: every detector verified against real moquery shapes; 'not observed' never becomes 'healthy'
- **[fixture/M]** test_aci_parsers.py + test_aci_axes.py — unit tests over the fixtures: each parser returns the expected MO fields; each axis fires on the anti-pattern fixture and stays silent (emitting 'not assessed'  
  ↳  — Proposer≠verifier + false-health gate regression-locked; absence-of-evidence honesty enforced by test
- **[analysis/M]** Snapshot wiring — assemble the ACI axes into snap (e.g. snap['aci'] = {controller, membership, faults, contracts, access_policy, l3out}) at COLLECT_PARSE main, fold the ACI findings into snap['punchli  
  ↳  — One source of truth — ACI findings reconcile into the same punchlist/exec-brief decision layer every deliverable already reads
- **[deliverable/M]** archreview.py ACI conformance domain — add a 9th domain ('ACI Fabric Conformance') with add()-pattern checks (APIC fully-fit, fabric discovery complete, no fault-masked health, contracts enforce white  
  ↳  — Architecture-review conformance for ACI; not-assessable honesty when no APIC evidence captured

### Cisco Catalyst SD-WAN — absent (10 P1)
> The entire SD-WAN overlay is collection-blind: COLLECT_PARSE_V3_23_0.py emits zero `show sdwan ...` commands, so parse/analyze/detect have nothing to read — fabric health (control connections, OMP, BFD, app-route, trackers) is structurally unobservable and the 14 SD-WAN doctrine entries stay WHY-only with no HOW. First build the collector+parsers (P1) or every downstream detector starves.

- **[parser/L]** Add the Catalyst SD-WAN show-command set to the live/offline collection command lists so every downstream layer has evidence to read. Add: show sdwan control connections, control connection-history, c  
  ↳  — All control/data/overlay/policy/security axes; evidence-honesty: state lives only on Manager/controllers/live edges, so collect it or mark a
- **[parser/M]** parse_sdwan_control_connections / parse_sdwan_control_history / parse_sdwan_local_properties — parse PEER TYPE (vsmart/vbond/vmanage), peer system-ip/site-id, STATE (up/down), and from connection-hist  
  ↳  — Control-plane redundancy (controllers per edge vs expected) + control connection DOWN/flapping diagnosable cause (cert/org-name/board-id/DTL
- **[parser/M]** parse_sdwan_bfd_sessions / parse_sdwan_bfd_summary — per-session SRC/DST TLOC, COLOR, STATE (up/down/NA), transitions count, encap; and sessions-up vs total from summary. Reconcile DST color-pairs to   
  ↳  — BFD sessions DOWN/NA or excessive transitions = data-plane blackhole/flapping tunnel even when control is up (UDP 12346/port-hop blocked, NA
- **[parser/M]** parse_sdwan_omp_peers / parse_sdwan_omp_summary / parse_sdwan_omp_routes_tlocs — OMP peer STATE + R(received)/I(installed)/S(sent) counters per vSmart; from summary admin/oper-state, vsmart-peers, gra  
  ↳  — OMP peering incomplete / route propagation broken (received=0 while sent>0); GR disabled; send-path-limit/ecmp-limit capped at default 4 vs 
- **[parser/M]** parse_sdwan_tloc_summary — per-TLOC system-ip + color + encapsulation(ipsec/gre), preference/weight, and per-site color count + edge count (from tloc-summary-list / local-properties), so single-transp  
  ↳  — Single-homed sites / single transport (one edge or one TLOC color) — the dominant brownfield fragility class for dual-transport SD-WAN
- **[analysis/L]** compute_sdwan_fabric_health — analysis axis that folds the parsed control/OMP/BFD/TLOC state into a per-fabric signal block: controllers-per-edge vs expected, BFD up/total, OMP peer up + received/inst  
  ↳  — Aggregates control-redundancy / OMP / BFD / single-homed / GR / ECMP checks into detector-ready signals; bare-config false-health guard
- **[detector/M]** _d_sdwan_control_redundancy — detector (engine_actionable) firing when distinct Controllers(vsmart) or Validators(vbond) == 1, a Manager cluster is an even/non-quorum node count, controllers share one  
  ↳  — Control-plane underbuilt/non-redundant controllers (single Controller/Validator, even Manager quorum, co-located) + edge connected to only o
- **[detector/M]** _d_sdwan_bfd_health — detector (engine_actionable) firing on any BFD session down/NA on an advertised color-pair or high-transition flapping; reports blackholed/unstable transports per site with src/d  
  ↳  — BFD sessions DOWN/NA or excessive transitions = data-plane blackhole / flapping tunnel
- **[detector/M]** _d_sdwan_omp_health — detector (engine_actionable) firing on OMP peer not up, routes received=0/installed=0 while sent>0, GR disabled, or send-path-limit/ecmp-limit left at default 4 while more equal-  
  ↳  — OMP peering incomplete/route propagation broken + ECMP/path-redundancy capped + graceful-restart disabled/misaligned
- **[fixture/L]** SD-WAN fixtures + honesty/golden tests — captured `show sdwan ...` sample outputs (control connections incl. error codes, bfd sessions up+down, omp peers with R/I/S, tloc summary single-homed case, ap  
  ↳  — Evidence-honesty / not-observed-never-healthy across all checks; proposer != verifier

### SP / MPLS core — absent (16 P1)
> The engine collects and parses ZERO MPLS/SR/VPN state (no LFIB, no LDP/RSVP-TE, no VPNv4/v6, no EVPN, no SRGB/TI-LFA, no MVPN) — every SP-core health check is unimplementable until a collection+parser+build layer feeds new snapshot fields; the 28 sp-* KB principles are all engine_actionable:false because no data gates them.

- **[parser/M]** Add the SP/MPLS transport collection block to BOTH the NX-OS and IOS/XR command lists: show mpls forwarding-table / show mpls forwarding (XR), show mpls ldp neighbor detail, show mpls ldp discovery, s  
  ↳  — show mpls forwarding LFIB is the core forwarding source of truth; show mpls ldp neighbor/igp sync underpins the LDP-session-down and LDP-IGP
- **[parser/M]** parse_mpls_forwarding_table(output) -> [{prefix, local_label, out_label(Pop/Unlabelled/Aggregate/<n>), out_iface, next_hop}] handling BOTH 'show mpls forwarding-table' (IOS) and 'show mpls forwarding'  
  ↳  — BGP-free core / transport-label continuity — a VPN next-hop /32 must resolve to a labeled end-to-end path; detect Unlabelled/Pop-too-early i
- **[parser/M]** parse_mpls_ldp_neighbors(output) -> [{peer_id, state(Oper/up/down), discovery_sources, targeted, holdtime, session_protection(bool)}] from 'show mpls ldp neighbor detail'; plus parse_mpls_ldp_igp_sync  
  ↳  — LDP session down/flapping; LDP-IGP synchronization missing (Sync not achieved while link in IGP forwarding -> transient black-hole on link-u
- **[analysis/M]** build_mpls_transport(cmd_to_file) -> {lfib:[...], ldp_neighbors:[...], ldp_igp_sync:[...], mpls_interfaces:[...]} mirroring build_routing_neighbors: parse-from-already-collected, _safe_parse fail-soft  
  ↳  — Establishes the canonical mpls_transport snapshot field the whole detector layer reads (one-source-of-truth join), matching the existing rou
- **[detector/M]** _d_mpls_lsp_health(snap, sig): coverage-honest detector firing only when snap['mpls_transport'] is non-empty. Flags (a) LDP neighbors not Oper/up, (b) LFIB prefixes with Unlabelled/no out-label for kn  
  ↳  — LDP session down + transport-label continuity broken + LDP session protection absent
- **[parser/M]** Add the MP-BGP service-plane collection: show bgp vpnv4 unicast summary, show bgp vpnv6 unicast summary, show bgp l2vpn evpn summary, show bgp vpnv4 unicast vrf all labels, show vrf detail (XR: show v  
  ↳  — MP-BGP VPNv4/VPNv6/EVPN session down or RR SPOF; RT/RD design fault; provides the per-VRF + RD/RT evidence for the L3VPN integrity detector
- **[parser/M]** parse_bgp_vpnv4_summary(output) (and reuse for vpnv6/evpn AFI by passing the AFI label) -> [{neighbor, as, state(Established/...), pfx_rcd(int), tbl_ver, is_rr_client}]. parse_vrf_detail(output) -> {v  
  ↳  — VPNv4/v6/EVPN session state != Established or PfxRcd stuck/0; single-RR SPOF; RD/RT import-export reconciliation across the two PEs of a VPN
- **[analysis/M]** build_vpn_service(cmd_to_file) -> {vpnv4:[...], vpnv6:[...], evpn:[...], vrfs:{...}} fail-soft, keyed into snapshot as snap['vpn_service']; extend build_routing_neighbors / parse_*_neighbors to captur  
  ↳  — VRF/PE-CE routing-table segmentation context (med gap) — distinguish PE/CE from campus core; feeds the RD/RT and inter-AS detectors
- **[detector/M]** _d_vpn_rd_rt_integrity(snap, sig): fires only when snap['vpn_service'].vrfs present. Detects (a) VPNv4/v6/EVPN sessions not Established or PfxRcd=0, (b) single RR neighbor (no redundancy), (c) asymmet  
  ↳  — MP-BGP session down / RR SPOF + Route-Target/RD design fault (asymmetric RT = route leak or missing routes; same RD reused)
- **[parser/M]** Add Segment-Routing + TI-LFA collection: show segment-routing mpls (XR) / show isis segment-routing, show isis segment-routing label table / show ospf segment-routing, show route <PE-loopback> + show   
  ↳  — Non-homogeneous SRGB / prefix-SID conflict; TI-LFA/FRR leaving prefixes unprotected (no Backup TI-LFA repair next-hop)
- **[parser/M]** parse_segment_routing_sids(output) -> {srgb_base, srgb_range, prefix_sids:[{prefix, sid_index, label}], adj_sids:[...]} and parse_ti_lfa_coverage(output) -> [{prefix, protected(bool), repair_type(TI-L  
  ↳  — Homogeneous SRGB across the domain (heterogeneous = design smell, resize needs reload, SRGB_ALLOC_FAIL); TI-LFA per-prefix repair present
- **[detector/M]** _d_sr_srgb_homogeneity(snap, sig): diff parsed SRGB base/range across all SR-capable nodes; flag any node whose SRGB differs from the fleet mode, plus duplicate/overlapping prefix-SID indices. Coverag  
  ↳  — Non-homogeneous SRGB or prefix-SID conflict breaks label-stack consistency / can fail SR programming
- **[detector/M]** _d_ti_lfa_coverage(snap, sig): from parse_ti_lfa_coverage, count P2P/core prefixes with no precomputed repair next-hop; flag the unprotected set as a sub-50ms convergence-SLA blocker. Fires only when   
  ↳  — TI-LFA/FRR not enabled or leaving prefixes unprotected -> >50ms loss on single link/node failure (TI-LFA = RFC 9855)
- **[analysis/M]** Flip the gated sp-* / segment-routing / evpn KB principles (sp-sr-srgb-homogeneous-non-overlapping-global-block, sp-sr-ti-lfa-guaranteed-postconvergence-repair, sp-l3vpn-rd-disambiguates-overlapping-v  
  ↳  — Coverage-honesty invariant: a principle is engine_actionable only when collected evidence can gate it (mirrors the existing per-addendum hon
- **[fixture/L]** SP-core fixtures: add realistic IOS-XR + IOS show-command captures (LFIB, ldp neighbor detail, ldp igp sync, bgp vpnv4/vpnv6/l2vpn evpn summary, vrf detail, isis segment-routing label table, show rout  
  ↳  — Parser robustness + the NX-OS bare-'show logging' false-health class (use logfile form); every parser proven on a real capture and on garbag
- **[fixture/M]** Detector unit tests proving each new _d_* fires on a crafted unhealthy snapshot AND stays silent (not 'healthy') on an empty/non-MPLS snapshot — the coverage-honesty mutation test. Follow test_design_  
  ↳  — Proposer != verifier; 'Not observed' never silently becomes 'healthy' (false-health guard)

### Cisco IOS-XE Campus & SD-Access — absent (15 P1)
> The engine is fabric-blind: zero LISP/VXLAN/CTS/device-tracking/StackWise parsers exist and every campus-sda-* principle in design_kb.py is engine_actionable:False, so a live SD-Access site is assessed as if it were traditional routed-access (no fabric role, control-plane SPOF, SGACL-enforcement, or underlay-MTU visibility at all).

- **[parser/M]** Add SD-Access show-commands to the IOS/IOS-XE collection list so any fabric evidence is captured (gated behind a fabric-detected platform to keep non-fabric collections clean): show lisp session, show  
  ↳  — All SD-Access key_show_commands; coverage-honesty (controller/off-box axes stay 'not observed' when only switch CLI is collected)
- **[parser/M]** parse_lisp_session(output): per-peer LISP control-plane sessions (peer RLOC, Up/Down, in/out count). Emit a structured dict the detector layer can read; flag Down-to-CP vs benign Down-on-edge-with-no-  
  ↳  — 'show lisp session' — Up with non-zero in/out; a Down to the CP node is a fabric outage, a Down on an edge with no local EIDs is benign
- **[parser/L]** parse_lisp_database(output) + parse_lisp_server(output) + parse_lisp_map_cache(output): locally-registered EIDs per instance-id (xTR view), the CP-node Host-Tracking DB (EID->RLOC), and resolved remot  
  ↳  — show lisp instance-id <IID> ipv4/ethernet database|server|map-cache — authoritative endpoint map; map-cache state != complete reveals silent
- **[parser/L]** parse_cts_environment(output) + parse_cts_role_based(output) (permissions + counters + sgt-map): CTS env-data state/lifetime from ISE, installed SGACL matrix cells, per-cell permit/deny hit counts, an  
  ↳  — show cts environment-data (Complete/current), show cts role-based permissions/counters (non-zero = actually enforced), show cts role-based s
- **[parser/M]** parse_device_tracking(output): SISF/IPDT binding table (IP+MAC+VLAN+interface, REACHABLE/STALE/DOWN) — the feeder for LISP host registration, ARP suppression and SGT IP-binding. Distinct from the exis  
  ↳  — show device-tracking database — missing/STALE entries break onboarding; the edge side of the HTDB-integrity join
- **[analysis/M]** Wire the new parsers into the build pipeline and snapshot model so detectors can read them: add a fabric block to the per-host parse assembly + Model fields (e.g. snap['fabric'] with roles, lisp_sessi  
  ↳  — Three-plane separation (underlay / overlay-control / overlay-policy) surfaced as first-class snapshot evidence so every downstream surface r
- **[analysis/M]** compute_fabric_roles(snap): enumerate per-device fabric role (edge / border / control-plane / intermediate / Fabric-in-a-Box) from LISP session direction + database/server presence + (where available)  
  ↳  — Fabric role mapping + collapsed Fabric-in-a-Box SPOF detection; control-plane redundancy basis
- **[analysis/M]** compute_fabric_underlay(snap): join system-MTU probe + IS-IS adjacency + RLOC-loopback reachability into an underlay-readiness verdict (>=9100 jumbo for VXLAN, IS-IS full mesh, BFD on crosslinks, CLNS  
  ↳  — End-to-end fabric MTU 9100 (the intermittent large-frame-only fault class) + underlay IS-IS/RLOC reachability
- **[detector/M]** _d_fabric_cp_redundancy detector: fire when distinct Map-Server/Resolver (CP-node) RLOC count < 2 per site, or > 2 CP nodes while fabric-wireless is enabled (wireless client-context desync). Single CP  
  ↳  — Control-plane node redundancy: >=2 CP nodes/site; exactly a pair with fabric wireless
- **[detector/M]** _d_fabric_border_redundancy detector: fire on single border node, or a VN with no eBGP advertise/receive at the VRF-Lite handoff (a VN silently un-leaked north/south).  
  ↳  — Border-node redundancy + correct VN-to-VRF handoff with an active neighbor per VN
- **[detector/S]** _d_fabric_mtu detector: fire when any in-path fabric/underlay interface system-MTU < 9100 (or SVL CLNS MTU != 1400). Encodes the classic VXLAN ~50-byte-overhead intermittent-drop fault.  
  ↳  — End-to-end fabric MTU 9100 per SD-Access CVD
- **[detector/M]** _d_trustsec_enforcement detector: fire on env-data stale/Failed, empty role-based-permissions where policy is expected, or zero SGACL hit-counts (downloaded-but-not-enforced), or expired/absent PAC. C  
  ↳  — TrustSec environment-data & SGACL enforcement actually live (state Complete, matrix installed, counters incrementing)
- **[detector/M]** Flip the campus-sda-* principles to engine_actionable:True for those now backed by a firing detector (campus-sda-fabric-roles-and-availability-placement, four-plane-fabric, macro-vn-then-micro-sgt, fa  
  ↳  — SD-Access target-state decisions (fabric adoption, VN+SGT, fabric-vs-routed-access, role placement) actually recommended — not just document
- **[fixture/M]** Fabric fixtures: realistic show-output captures for each new parser — show lisp session (CP-up + edge-down-benign cases), lisp server/database/map-cache (complete + send-map-request), device-tracking   
  ↳  — Counterexample fixtures encode the benign-vs-outage distinction (LISP Down-no-EIDs is normal; Down-to-CP is an outage) so detectors don't cr
- **[fixture/M]** Detector + segmentation unit tests: lock each new _d_fabric_* (fires on the bad fixture, silent on the healthy/benign one) and the fabric-VN segmentation extension; add a fabric-honesty test mirroring  
  ↳  — Proposer != verifier — every consequential fabric output checked against a baseline fixture; coverage-honesty enforced by test, not just pro

### First-Hop Redundancy — partial (10 P1)
> The engine collects 'show standby all' but parses only the brief form — so priority, preempt, tracking, authentication, timers and HSRP version are silently discarded, leaving every senior-grade FHRP correctness check (the four pillars beyond presence/split-brain) unbuilt on data already on disk.

- **[parser/L]** parse_hsrp_detail(output) -> {(ifname,group): {priority, cfg_priority, state, preempt:bool, preempt_delay, active_ip, standby_ip, vip, vmac, hello, hold, auth_type(none|text|md5), auth_key_present, ve  
  ↳  — Primary HSRP source of truth: State, Priority/cfg-priority, Preemption+delay, Virtual IP, vMAC, Hello/Hold, Authentication, Track list, grou
- **[analysis/L]** compute_fhrp_config_audit(all_interfaces, fhrp_config_db) -> per-(segment,group) PEER-JOINED audit rows: each row carries the joined peer records + an issues[] list spanning election/tracking/peer-con  
  ↳  — FHRP correctness is a peer-pair property — every check evaluated by JOINING two peers on (segment, group); a lone collected peer = UNKNOWN, 
- **[analysis/M]** Publish snapshot axis snap['fhrp_config'] = compute_fhrp_config_audit(...) in COLLECT_PARSE assembly (alongside the existing snap['fhrp']=compute_fhrp_consistency at L1831/2091), and strip it from the  
  ↳  — One source of truth: the peer-joined FHRP config audit must be a published snapshot axis every surface reads, not recomputed per-deliverable
- **[detector/M]** _d_fhrp_election(snap, sig): fires when a peer-joined group has (a) equal priorities across peers (default 100/100 — non-deterministic election), or (b) HSRP/GLBP preempt OFF so the primary never recl  
  ↳  — Priority mis-set / no differentiation + preempt missing: intended primary must have highest priority AND (priority_primary - sum_decrements)
- **[detector/M]** _d_fhrp_tracking(snap, sig): fires when an Active/Master group at an L2/L3 boundary has NO track object wired (untracked active gateway black-holes on uplink loss), OR a track object exists but no gro  
  ↳  — No interface/object tracking on the active gateway = classic silent outage; tracked object must be actually referenced by the group (show tr
- **[parser/M]** parse_show_track(output) -> {obj_id: {type(ip-sla|interface|route|list), state(Up|Down), delay, subscribers:[group...]}}: structured parser for 'show track'/'show track brief'. Currently 'show track'   
  ↳  — show track proves tracking is actually WIRED to the group (subscriber list) and the object is Up/Down — an Up object nothing tracks is dead 
- **[detector/M]** _d_fhrp_peer_consistency(snap, sig): fires on any peer mismatch within a joined group — HSRP v1-vs-v2 (vMAC-prefix/version differs → both go active), virtual-IP mismatch (DIFFVIP class), timer asymmet  
  ↳  — Peer consistency: version, group#, VIP, vMAC, timers and auth must be identical on every peer — any mismatch = two-active / no-redundancy / 
- **[deliverable/S]** Collection add: append 'show standby all','show hsrp brief','show vrrp all','show glbp' (full forms) to COMMANDS_IOS/COMMANDS_NXOS so VRRP/GLBP detail is captured (HSRP detail already rides the build.  
  ↳  — Capture both IOS ('show standby ...') and NX-OS ('show hsrp ...') dialects, and the full VRRP/GLBP forms — brief-only loses priority/preempt
- **[fixture/M]** FHRP detail fixtures: synthetic 'show standby all' (priority+preempt+track+auth+timers, v1 and v2), 'show vrrp all' (owner-255 + v3 IPv4/IPv6 dialect + legacy v2 'vrrp ip'), 'show glbp' (AVG + N forwa  
  ↳  — Mutation-proof every join-based check: a fixture where two peers disagree must turn a detector RED, and a one-peer-collected fixture must yi
- **[fixture/M]** Detector unit tests: assert _d_fhrp_election/_tracking/_peer_consistency/_authentication/_vpc_alignment fire on the broken fixtures and stay SILENT (0) on a clean peer-pair (mirroring how the AJ fleet  
  ↳  — Coverage-honest + counterexample-driven: every new detector must have a fires-on-broken AND silent-on-clean test, and the 'none'-truthy fals

### IPv6 / dual-stack — absent (8 P1)
> The engine collects ZERO `show ipv6 *` commands — so every downstream IPv6 axis (FHS, HSRPv6, addressing, NAT64, ACL-parity) is structurally impossible; on a dual-stack brownfield this means a silent, unguarded IPv6 plane is invisible AND silently passes as healthy (the false-health trap). Land IPv6 collection first; nothing else can fire without it.

- **[parser/S]** Add the IPv6 show-command set to BOTH NOS lists (NX-OS + IOS/IOS-XE), spelled per-NOS. Minimum P1 floor: `show ipv6 interface brief`, `show ipv6 interface`, `show ipv6 routers`, `show ipv6 neighbors`,  
  ↳  — Silent/unguarded IPv6 on a dual-stack edge; coverage-honesty caveat 'nearly all IPv6 health is live-CLI-only' — without these commands every
- **[parser/M]** parse_ipv6_interface(output) -> {ifname: {admin, proto, link_local fe80::, prefixes:[{prefix,len,flags A/L/autoconfig,on_link}], dad_state, dad_attempts, ra_suppress, ra_interval, ra_lifetime, mtu, ma  
  ↳  — Non-/64 host subnet detection (flag len != /64; /127 only on RFC 6164 P2P); link-local/global-up presence = the silent-IPv6 trigger; M/O/A f
- **[parser/L]** parse_ipv6_fhs(output) -> per-interface/per-policy {raguard:{bound,device_role host|router,managed_flag}, dhcp_guard:{bound,device_role server|client}, nd_inspection:{bound}, source_guard, prefix_guar  
  ↳  — Missing FHS on access ports (HIGH) + 'not observed != not vulnerable'; rogue-RA, DHCPv6-spoof, Source/Prefix/Destination-Guard absence all k
- **[parser/S]** parse_ipv6_routers(output) -> [{interface/vlan, router_ll, lifetime, pref, flags M/O}] from `show ipv6 routers`. Feeds the rogue/extra-RA detector (>1 router on a host VLAN) and the 'single RA source   
  ↳  — Rogue/extra Router Advertisement (>1 entry in show ipv6 routers on an access VLAN = second default gateway / rogue-RA / Windows ICS).
- **[parser/M]** build_ipv6_interfaces / build_ipv6_fhs / build_ipv6_routers (cmd_to_file readers, fail-soft via _safe_parse like build_routes:154 and build_igmp_groups:172). Assemble per-device IPv6 state into the sn  
  ↳  — Coverage-honesty: a snapshot lacking the IPv6 show-commands must mark IPv6 posture UNKNOWN — the [] / {} sentinel is what lets the detector 
- **[analysis/L]** compute_ipv6_posture(snap) in analyze.py -> {observed:bool, segments:[{vlan, stage dual-stack|v6-only|v4-only|unknown, prefix, len, fhs_bound:bool, ra_sources:int, dad_state}], findings, summary{n_v6_  
  ↳  — Per-segment transition-stage classification (dual-stack / IPv6-mostly / IPv6-only); the dual-stack SSOT 'map IPv6 prefix<->VLAN<->IPv4 subne
- **[detector/M]** _d_ipv6_silent_fhs detector: fires when a segment has IPv6 up (link-local/global in show ipv6 interface) but the access port has NONE of raguard/dhcp-guard/nd-inspection/device-tracking. Coverage-hone  
  ↳  — Silent/unguarded IPv6 on dual-stack or IPv4-only access edge (HIGH) — the headline gap; the first IPv6 principle to become live-detectable.
- **[fixture/M]** Fixtures: real IOS-XE + NX-OS captures for show ipv6 interface [brief], show ipv6 routers, show ipv6 nd raguard/dhcp guard/snooping policy, show ipv6 neighbor binding, show ipv6 device tracking databa  
  ↳  — Per-NOS command-spelling divergence (IOS-XE 'show ipv6 snooping' vs NX-OS 'show ipv6 neighbor binding') + the Nexus empty-on-success false-h

### Multicast — partial (12 P1)
> The entire PIM-SM control plane is blind: no RP discovery/redundancy (rp mapping/rp-hash), no RPF integrity (the #1 multicast outage), and no MSDP liveness — the engine sees L2 group membership + per-interface PIM mode but cannot tell where the RP is, whether it is redundant, or whether (S,G) state has a valid incoming interface.

- **[parser/S]** Add PIM control-plane + MSDP show commands to the collection lists (both IOS/IOS-XE and NX-OS blocks). Add: 'show ip pim rp mapping', 'show ip pim neighbor', 'show ip rpf', 'show ip mroute count', 'sh  
  ↳  — Single/non-redundant RP; RPF failure; >2 Anycast RPs without MSDP mesh-group; SSM/IGMPv3; rogue-RP hardening (all best_practice_checks depen
- **[parser/M]** parse_pim_rp_state(rp_mapping_out, runcfg_out) -> {rp_method (static/auto-rp/bsr), rps:[{rp_ip, group_ranges, learn_source, bidir, is_static}], anycast_candidates, ssm_ranges}. Regex over 'show ip pim  
  ↳  — RP discovery method per group-range (static vs Auto-RP vs BSR); detect inconsistent/overlapping RP ranges
- **[parser/M]** parse_pim_rpf(rpf_out, mroute_out) -> {rpf_checks:[{target, incoming_interface, rpf_neighbor, ok}], null_iif_groups:[...]}. Parse 'show ip rpf <ip>' (RPF interface / RPF neighbor / 'failed') and exten  
  ↳  — RPF failure — mroute incoming-interface Null or 'show ip rpf' returns no/incorrect interface (the single most common multicast data-plane ou
- **[parser/M]** parse_msdp_state(peer_out, sa_cache_out) -> {peers:[{peer_ip, state, sa_rcv, sa_sent, resets}], n_sa_cache, originator_id, mesh_group_present}. Parse 'show ip msdp peer' (State Up/Down, SA counts) + '  
  ↳  — >2 Anycast RPs without MSDP mesh-group / Anycast pair with MSDP down so (S,G) state is not shared; MSDP SA plane unhardened (sa-filter/sa-li
- **[parser/S]** parse_igmp_snooping_mrouter(out) -> [{vlan, mrouter_ports:[...], learn_mode}]. Parse 'show ip igmp snooping mrouter'. This is the missing half of the querier-gap logic: a VLAN with ZERO mrouter ports   
  ↳  — L2 VLAN with snooping enabled but NO querier AND NO mrouter port — membership ages out and multicast stops/floods
- **[analysis/M]** Assemble the new parsed records into service_map.multicast: extend the collection loop and compute_service_map to thread pim_rp_state, rpf, msdp, pim_neighbors, igmp_interface (version), and snooping_  
  ↳  — Coverage-honesty: assemble evidence before deriving findings; one source of truth for RP/MSDP/RPF state
- **[detector/L]** Extend compute_multicast_intelligence with an RP-redundancy analyzer: classify RP architecture (single static RP=SPOF / Anycast with N RPs / Phantom-RP Bidir / BSR), and emit risks: single-static-RP (  
  ↳  — Single/non-redundant RP; Anycast loopback not /32; >2 Anycast RPs without MSDP mesh-group; inconsistent/overlapping C-RP ranges
- **[detector/M]** Add an RPF-integrity detector to compute_multicast_intelligence: emit 'rpf-failure' risk (High) for any (*,G)/(S,G) with Null incoming-interface or failed 'show ip rpf', citing the group and target; a  
  ↳  — RPF failure (Null IIF / rpf failed / missing route to source/RP) — single most common multicast outage
- **[detector/M]** Upgrade the querier-gap detector to be coverage-honest and mrouter-aware. Currently gap_vlans is derived ONLY from collected SVIs carrying multicast_info (:1756-1765), so an L2 island whose SVI sits o  
  ↳  — L2 VLAN snooping-on, no querier, no mrouter = stops/floods; coverage-honesty — 'no querier observed' must be UNKNOWN when L3 core uncollecte
- **[detector/M]** Extend design_advisor signature + the _d_mcast detector. In design_advisor.py extract the new multicast_intelligence summary fields (rp_architecture, n_rp_redundancy_risks, n_rpf_failures, n_msdp_down  
  ↳  — Single/non-redundant RP → design must introduce Anycast-RP+MSDP; RPF integrity surfaced as a design action
- **[fixture/M]** Add parse-level fixtures + tests for the new parsers: sample 'show ip pim rp mapping' (Auto-RP, BSR, static, Anycast /32, Bidir), 'show ip rpf' (success + 'failed'), mroute with Null IIF, 'show ip msd  
  ↳  — RP discovery/redundancy; RPF; MSDP liveness; mrouter reconciliation; SSM/IGMPv3 — parser-locked
- **[fixture/M]** Add detector-level + coverage-honesty tests: assert single-static-RP -> SPOF risk; Anycast non-/32 -> risk; MSDP-down+empty-cache -> risk; Null-IIF -> rpf-failure risk; SSM-without-IGMPv3 -> risk; and  
  ↳  — Coverage-honesty — 'no querier/RP observed' is UNKNOWN when upstream uncollected, never healthy; every consequential output evidence-grounde

### QoS & media transport — partial (12 P1)
> The engine audits QoS/PTP INTENT (running-config) only and never reconciles it against RUN-STATE — none of the decisive operational commands (show policy-map interface, show queuing interface, show ptp brief/port/corrections, interface drop counters) are even collected, so the 'configured-but-ASIC-rejected / unbounded-LLQ / trust-on-wrong-port / PTP-up-but-not-locked' false-health classes are structurally invisible.

- **[parser/S]** Add run-state QoS + PTP commands to BOTH collection lists (COMMANDS_NXOS ~L505-530, COMMANDS_IOS ~L532-584): 'show policy-map interface', 'show policy-map interface brief', 'show queuing interface' (N  
  ↳  — Reconcile INTENT (running-config) against RUN-STATE (show policy-map interface / show queuing interface / show ptp clock|corrections) — neve
- **[parser/L]** parse_policy_map_content(text): extend the running-config QoS parse to capture, per policy-map, each class's match criteria (match dscp/cos/qos-group/access-group), marking actions (set ip dscp / set   
  ↳  — Voice priority queue has NO policer (unbounded LLQ) — a strict-priority class with no police can starve all other classes under congestion
- **[parser/L]** parse_policy_map_interface(output): NEW run-state parser for 'show policy-map interface <if>' — per-(interface,direction,class) offered rate, drop counters, priority/police conform/exceed/drop, and wh  
  ↳  — Service-policy configured but NOT applied / silently rejected by ASIC-TCAM — policy in running-config but show policy-map interface shows it
- **[detector/M]** _d_qos_marking / extend compute_qos_audit (analyze.py:4264-4390) to validate marking values against the RFC 4594-as-adapted-by-Cisco medianet table: EF=46 voice, CS3=24 call-signaling (NOT CS5 — encod  
  ↳  — DSCP marking values violate the RFC 4594 / medianet model (voice not EF46, signaling not CS3, video not AF41, broadcast not CS5, scavenger n
- **[detector/M]** _d_unbounded_llq detector (analyze.py, new _QOS_DOCTRINE kind): firing when a parsed policy-map has a 'priority' class with no 'police' (IOS LLQ) / a NX-OS priority qos-group with no conforming type-q  
  ↳  — Voice priority queue has NO policer (unbounded LLQ) — Cisco mandates the priority queue be policed at a configured rate
- **[analysis/M]** Platform-dialect branching in parse_qos_config / compute_qos_audit: branch QoS interpretation by NOS family so a Catalyst-9000 fleet is not false-negatived. Legacy IOS/Cat-OS = 'mls qos' + srr-queue/w  
  ↳  — QoS not enabled / default-pass on legacy IOS (global mls qos OFF by default makes all trust/queue config inert) — platform-scoped to legacy 
- **[detector/S]** _d_conditional_trust detector: flag voice-VLAN access ports lacking conditional trust ('trust device cisco-phone' IOS-XE / 'mls qos trust device cisco-phone' IOS) AND lacking an ingress marking policy  
  ↳  — Conditional trust missing at the phone edge — voice ports with no 'trust device cisco-phone' so phone markings are reset to DF and voice los
- **[parser/M]** parse_ptp_brief(output) + parse_ptp_port(output): NEW run-state parsers extracting per-port PTP role (MASTER/SLAVE/PASSIVE/DISABLED/FAULTY), peer, announce/sync/delay-req intervals, and delay mechanis  
  ↳  — PTP port stuck in PASSIVE/FAULTY or unexpected MASTER — a port that should be SLAVE-to-GM is PASSIVE/FAULTY, or a leaf is erroneously MASTER
- **[detector/M]** _d_ptp_role / extend compute_ptp_readiness (analyze.py:1651-1688) with run-state port-role findings: PASSIVE/FAULTY ports on a media path, a leaf gone MASTER, and on NX-OS a non-boundary device-type (  
  ↳  — PTP running in a non-boundary mode on Nexus, or PTP port stuck PASSIVE/FAULTY/unexpected-MASTER (Nexus 9000 = boundary-clock only; transpare
- **[fixture/M]** Golden PTP/QoS run-state fixtures: add deterministic fixtures for the new parsers — 'show policy-map interface' (priority class with drops + a not-attached policy = ASIC-rejection), 'show ptp brief' (  
  ↳  — False-health classes specific to this architecture: policy configured-but-not-attached, unbounded priority queue, trust on wrong port, PTP u
- **[fixture/M]** Unit tests for the new marking/LLQ/platform detectors, mirroring tests/test_qos_audit.py: assert RFC4594/medianet marking mismatches fire (incl. NOT correcting CS3 signaling to CS5), unbounded-LLQ fir  
  ↳  — Cisco medianet deviation must be preserved (Call-Signaling=CS3, Broadcast-Video=CS5) — do not 'correct' a CS3 mark to CS5
- **[fixture/M]** Unit tests for the new PTP run-state detectors (new file tests/test_ptp_runstate.py — none exists today): port-role PASSIVE/FAULTY/unexpected-MASTER findings, NX-OS boundary-clock-only enforcement, co  
  ↳  — Judge PTP on run-state (offset, corrections, port role, GM stability), never on config presence — a configured PTP that is FAULTY/PASSIVE is

### Classic Cisco WAN overlays — absent (10 P1)
> Zero overlay-control evidence is collected — no show dmvpn/ip nhrp/crypto session/crypto gdoi/domain master output exists, so every DMVPN/GETVPN/FlexVPN/PfRv3 health verdict is structurally UNKNOWN; the P1 fix is adding the collection set, without which no parser or detector below can run honestly.

- **[parser/M]** Add the WAN-overlay collection set to BOTH command lists (COMMANDS_IOS, and COMMANDS_NXOS where a verb exists): show dmvpn detail, show ip nhrp detail, show ip nhrp nhs detail, show crypto session det  
  ↳  — COVERAGE-HONESTY: NHRP/GDOI/PfR/crypto are not in show run+show version; uncollected => redundancy/anti-replay/path-control UNKNOWN, never h
- **[parser/M]** parse_crypto_session(): 'show crypto session [detail]' -> per-peer [{peer, ivrf, fvrf, status, uptime, ike_sa, ipsec_flows}]. Status UP-ACTIVE = up; anything else (DOWN/NEGOTIATING) = not up. The fast  
  ↳  — show crypto session status UP-ACTIVE evidences a live tunnel; absence/other state = tunnel not up.
- **[parser/M]** parse_crypto_ipsec_sa(): 'show crypto ipsec sa' -> per peer/interface [{peer, local, remote, pkts_encaps, pkts_decaps, send_errors, recv_errors, pfs_group, path_mtu, in_spi, out_spi, transform}]. Carr  
  ↳  — IPsec one-way/black-hole: #pkts encaps rising while #pkts decaps=0 (or mirror) + non-zero send/recv errors.
- **[parser/L]** parse_dmvpn(): 'show dmvpn detail' + 'show ip nhrp nhs detail' -> per-tunnel [{tunnel, peers:[{nbma, tunnel_addr, attr_flags(D/S/I), state(UP/DOWN/NHRP)}], nhs_state(RE/E/DOWN), peer_count, nhrp_group  
  ↳  — DMVPN NHRP registration failure / NHS down: NHS not RE; hub cache has no/incomplete(I) spoke entries.
- **[parser/M]** parse_crypto_algorithms(): scan 'show crypto ipsec transform-set' + 'show crypto ikev2 proposal' + 'show crypto isakmp policy' (and run-config crypto) -> {host: [{context, encryption, integrity, dh_gr  
  ↳  — Weak/deprecated crypto: DES/3DES/esp-null, MD5/SHA1, DH 1/2/5 — negotiates today but FN72510 breaks it on IOS-XE 17.11.1+ upgrade.
- **[analysis/L]** compute_wan_overlay(snap): the analysis pillar that joins all WAN parsers into a per-device + fleet overlay model: classify each device's role (DMVPN hub/spoke, GETVPN KS/GM, PfR MC/BR, BGP edge), per  
  ↳  — Single-source overlay model: every overlay health claim cites the show field that evidences it; uncollected role => UNKNOWN.
- **[detector/S]** _d_wan_overlay_unknown: coverage-honesty gate detector — when a device is plausibly a WAN-edge router (has Tunnel interfaces, crypto config, or eBGP) but the overlay show-state was NOT collected, emit  
  ↳  — 'Not observed' never becomes 'healthy' — uncollected overlay control plane is reported UNKNOWN with the exact missing command.
- **[detector/M]** _d_crypto_weak: engine_actionable detector — flags devices whose transform-set/IKE proposal uses DES/3DES/esp-null, MD5/SHA1, or DH 1/2/5; dual-labels each as (a) cryptographically weak now and (b) FN  
  ↳  — Weak crypto on overlay tunnels — security finding AND post-FN72510 upgrade blocker; fails negotiation after upgrade.
- **[fixture/L]** WAN-overlay fixtures: synthetic device captures exercising each parser+detector — (a) healthy dual-cloud DMVPN hub+spoke with NHS RE and AES-GCM, (b) NHS-down spoke + incomplete hub cache, (c) one-way  
  ↳  — Each canonical fragile-vs-sound case is reproduced so detectors are proven on evidence, not asserted.
- **[fixture/M]** test_wan_overlay.py: lock the parsers + compute_wan_overlay + each _d_* detector against the fixtures, INCLUDING the negative/honesty assertions — uncollected overlay => UNKNOWN (not healthy), and a f  
  ↳  — Proposer != verifier: detectors validated by independent test; coverage-honesty negative cases enforced.

### Control/management-plane hardening — partial (8 P1)
> CoPP/CPPr health is the biggest gap: the engine can name a control-plane service-policy (parse_qos_config.global_attach captures copp-system-*) but parses ZERO violate/conform/drop counters and no `show copp status/diff`, so "CoPP not observed" silently reads as healthy — the dominant false-health failure class for this architecture.

- **[parser/M]** parse_copp_policy(output) -> {policy, classes:[{name, conform_pkts, exceed_pkts, violate_pkts, drop_pkts, cir}], applied:bool, default_profile, source}. Parse BOTH dialects: IOS-XE `show policy-map in  
  ↳  — CoPP present but actively starving the control plane — sustained violate/exceed drops on legitimate classes (BGP/OSPF/EIGRP/HSRP/SSH/SNMP/AR
- **[parser/S]** parse_copp_status(output) -> {profile: strict|moderate|lenient|dense|none, applied:bool, diff_lines:[...]}. NX-OS `show copp status` (which default profile is applied / 'No CoPP policy') + `show copp   
  ↳  — NX-OS CoPP drifted from a known-good default profile, or a class set to police ... conform drop (drops conforming traffic); profile set to n
- **[fixture/S]** Add collection commands: `show policy-map interface control-plane` (IOS/IOS-XE), `show policy-map type control-plane` + `show copp status` + `show copp diff profile strict applied` (NX-OS), `show cont  
  ↳  — CoPP entirely absent on a control-plane-bearing platform (no service-policy on control-plane / NX-OS profile=none) leaves the supervisor ope
- **[analysis/L]** compute_control_plane_audit(run_configs, copp_by_host, all_hosts) -> per-device {assessable, copp_state: enabled|absent|unknown, profile, violate_classes:[...], n_violate_drops} + fleet doctrine findi  
  ↳  — Detectors must treat 'not observed' as UNKNOWN, never 'healthy'; absent `show policy-map interface control-plane` does NOT mean CoPP is heal
- **[parser/M]** parse_arp_inspection(output) -> {vlans_enabled:[...], interfaces:{if:{trust:bool, rate_limit, forwarded, dropped, dhcp_drops, acl_drops}}}. Parse `show ip arp inspection` (per-VLAN enable + ACL-match/  
  ↳  — DAI not enabled on snooped VLANs (ARP-spoof/MITM exposure), or enabled WITHOUT bindings/ARP-ACL so legit ARP is dropped; rising Dropped/DHCP
- **[parser/M]** parse_dhcp_snooping_state(output) -> {enabled_vlans:[...], trusted_ports:[...], untrusted_ports:[...], db_count}. Parse `show ip dhcp snooping` (the enable+trust-boundary view, distinct from the exist  
  ↳  — DHCP snooping disabled on user VLANs, or trust boundary wrong — uplink/server ports left UNtrusted (breaks DHCP) or access/user ports left t
- **[detector/M]** Extend parse_security() with management-plane depth checks emitting NEW _SEC_CHECKS ids (do NOT duplicate existing insecure-snmp/weak-enable/telnet-enabled/vty-hardening): (a) ssh-v1 = `ip ssh version  
  ↳  — AAA login with NO local fallback => full lockout when TACACS+/RADIUS unreachable; fallback to line/none is an auth-bypass backdoor; SNMP com
- **[fixture/M]** Test fixtures + detector tests: tests/test_copp.py (IOS-XE control-plane policy-map with violate-drops on a routing class => High; NX-OS copp status profile=none => High; no capture => copp_state UNKN  
  ↳  — Every detector EVIDENCE-GATED; 'not observed' => UNKNOWN; false-health (CoPP/snoop/AAA absent silently passing) is the dominant failure clas

### Management & Assurance plane — partial (8 P1)
> Model-Driven Telemetry + programmatic management (NETCONF/RESTCONF/gNMI/MDT) is completely unobserved — no collection, no parser, no detector — so the engine cannot grade whether assurance is actually streaming, nor catch the config-present/pubd-dead false-health trap.

- **[fixture/S]** Collect the model-driven-management + assurance show-commands. Add to COMMANDS_NXOS/COMMANDS_IOS (and the COMMANDS_ALL dedupe is automatic): 'show telemetry model-driven subscription', 'show telemetry  
  ↳  — Enablement & process health + dial-out SSOT integrity require the telemetry/netconf/gnmi/http and ntp-status/snmp-user output to even exist;
- **[parser/L]** parse_telemetry_subscriptions(text) + parse_telemetry_transport(text): structure IOS-XE 'show telemetry model-driven subscription [receiver]' (subscription id, State Valid/Invalid, type Configured/Dyn  
  ↳  — Telemetry SSOT integrity (dial-out): reconcile sensor-group→destination-group→subscription and read the receiver/transport state field — the
- **[parser/M]** parse_mgmt_programmability(text): from 'show running-config | section …' + 'show netconf-yang sessions' + 'show gnmi-yang state' + 'show grpc' + 'show ip http server [secure] status' extract {netconf_  
  ↳  — Enablement & process health (netconf-yang/pubd, gnmi secure vs insecure) + security of the mgmt surface (RESTCONF on HTTPS not plain http se
- **[parser/M]** build_telemetry_state(cmd_to_file) + build_mgmt_programmability(cmd_to_file): offline-load and _safe_parse the telemetry/netconf/gnmi/http outputs into per-device {transport_sessions, subscriptions, p  
  ↳  — Coverage & redundancy signals: a device with no telemetry evidence is 'not observed', never silently 'streaming fine'.
- **[detector/L]** compute_streaming_telemetry_readiness(telemetry_state): per-device + fleet roll-up detecting (a) configured-but-process-dead / receiver never Connected (false-health, HIGH); (b) receiver/transport NOT  
  ↳  — Telemetry process-dead false-health + dial-out receiver-not-connected + single-collector + plaintext/unauthenticated transport + cadence/enc
- **[detector/M]** parse_ntp_status(text) + build_ntp_status(cmd_to_file) + compute_ntp_health(): parse 'show ntp status' (sync state / stratum / offset) and 'show ntp associations [detail]' (the '*' sys.peer master, re  
  ↳  — NTP actually-synchronized + authenticated + redundant + access-grouped — an unsynced/single/spoofable clock makes every timestamp untrustwor
- **[detector/M]** parse_syslog_config(text) + compute_syslog_delivery_readiness(): from 'show running-config | include logging|service timestamps' extract {hosts:[…], trap_severity, source_interface, buffered_size, con  
  ↳  — ≥2 remote collectors, source-interface pinned, appropriate trap severity, high-resolution zone-aware timestamps, no console/monitor logging 
- **[fixture/M]** Fixtures + tests for every new parser/detector: real-shape sample outputs for 'show telemetry model-driven subscription receiver' (Connected AND Resolving cases), NX-OS 'show telemetry transport' (Con  
  ↳  — Proposer≠verifier + 'not observed never becomes healthy': the config-present/process-dead false-health trap and the NX-OS bare-show-logging 
