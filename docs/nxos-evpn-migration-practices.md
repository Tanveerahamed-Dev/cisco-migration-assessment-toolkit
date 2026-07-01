# NX-OS VXLAN-EVPN Migration — Leading Practices (2025–2026)

> Brownfield Cisco estate · Data Center + Campus · vendor-strategic.
> Source: a 5-angle deep-research pass (19 sources, mostly **primary Cisco**; 69 claims extracted → 25 verified
> under 3-vote adversarial refutation → 22 confirmed / 3 killed → 14 findings). Every finding is high-confidence
> (3-0 unanimous unless noted). The fast-moving strategic-direction items are flagged for re-verification at
> engagement time.
>
> The load-bearing migration guardrails in §3 are operationalised by `cisco_toolkit/evpn_migration.py`
> (`compute_evpn_migration_guardrails`), gated on a NX-OS-VXLAN-EVPN target and grounded in the assessed
> fleet's own evidence; they surface in the MOP (§2.2 "EVPN-migration guardrails") and the design-driven NRFU
> (`design_nrfu.evpn_acceptance`).

## Bottom line for a migration planner
1. **Target NX-OS VXLAN BGP EVPN as the go-forward fabric — but do *not* tell stakeholders ACI is "dead."**
   Cisco's Nov 19 2025 **"Nexus One Fabric"** position is *convergence*, not an ACI sunset (no formal ACI EoL
   exists; ACI 6.1/6.2 still ships; a new APIC-M6 appliance has a last-order date of 2026-06-18). The de-facto
   default for new/migrated fabrics is standards-based EVPN, managed by **Nexus Dashboard / NDFC**.
2. **The migration crux is the L2/L3 handoff, and it has two load-bearing gotchas** that are the most common
   cause of a failed cutover (§3, findings 8–10).

## 1 · Platform direction (fast-moving — re-verify at engagement time)
| # | Finding | Vote |
|---|---------|------|
| 1 | "Nexus One Fabric" = convergence of ACI + NX-OS-EVPN under one Nexus Dashboard, **not** an ACI EoL. ACI is gradually consolidated (rolling APIC appliance/software EoS-EoL), not killed. Practical default for new/migrated fabrics = NX-OS VXLAN BGP EVPN. | 2-1¹ |
| 2 | **Nexus Dashboard is the single management plane** for ACI *and* NX-OS-EVPN. ND 4.1 (Jul 2025) / 4.2.1 (Mar 2026) collapsed the formerly-separate NDFC/NDI/NDO into one platform; NDFC (ex-DCNM) is the EVPN fabric controller. | 3-0 |
| 3 | Go-forward architecture is **open-standards VXLAN/EVPN**; Cisco *asserts* authorship (first EVPN draft 2010 Sajassi → RFC 7432). EVPN is genuinely multi-vendor (Juniper/ALU/AT&T/Verizon/Bloomberg co-authors) — the strategic point is standards-based **multi-vendor interoperability**, unlike proprietary ACI. | 3-0 |

¹ *2-1 on the "convergence not deprecation" framing — "Nexus One Fabric" is a Cisco marketing banner; verified against the live web but not independent market reality. The single most time-sensitive item in this report.*

## 2 · Fabric design (stable, canonical CVD doctrine)
| # | Finding |
|---|---------|
| 4 | **Underlay** = IGP (OSPF *or* IS-IS; BGP optional). **Overlay** = iBGP EVPN is *mandatory*. **Spines = route-reflectors; leaves = VTEPs + distributed anycast gateway (DAG).** |
| 5 | **BUM/multicast** = NDFC fabric-create choice: **(a) multicast underlay** (RP count 2 or 4; RP co-located on the spine with the EVPN RR — efficient BUM, needs PIM in the underlay) vs **(b) ingress/head-end replication** (simpler underlay, head-end CPU cost). Multicast is NDFC's default. **TRM** handles routed multicast within tenants. |
| 6 | **Scale (NDFC 12.1.3b verified):** 500 switches / 3-node physical ND cluster (400 / 5-node virtual), **200 switches/fabric, 50 fabrics**. **Brownfield-imported overlays scale lower** (400 VRF / 1050 networks) than greenfield (500 VRF / 2000 L3 *or* 2500 L2); limits rise to greenfield once migration completes. *Version-pinned — confirm against the deployed NDFC release.* |

## 3 · Brownfield migration methodology (the actionable core)
| # | Finding |
|---|---------|
| 7 | **Cisco's documented method for *seamless* workload migration = 3-step "vPC back-to-back" (double-sided vPC) coexistence:** (1) build the new EVPN fabric alongside legacy; (2) build **both L2 and L3 interconnects** at the legacy L2/L3 demarcation; (3) migrate workloads — cross-traffic uses the step-2 links during transition. Reaffirmed in **BRKDCN-2951 (Cisco Live 2025)**. A non-seamless per-VLAN/subnet alternative + vPC Border Gateway/EVPN Multi-Site + L3-only VRF-lite are documented. |
| 8 | ⚠️ **#1 gotcha — loop safety is NOT automatic.** The L2 interconnect must be a **double-sided vPC (vPC+ for FabricPath)** keeping all links forwarding with no loop. **The VXLAN overlay neither forwards nor blocks STP BPDUs**, so a second active L2 path *will* loop and the fabric won't break it. Rule: **only ONE active L2 connection** legacy↔fabric; keep the classic network as STP root; BPDU-filter the interconnect; decommission when done. |
| 9 | ⚠️ **Gateway coexistence is NX-OS-version-gated.** Legacy **HSRP/FHRP and the EVPN DAG cannot coexist on the same subnet before NX-OS 10.2(3).** From 10.2(3)+ a coexistence feature exists and **is now the documented best-practice migration config.** → **Verify the running NX-OS train on both legacy and fabric-border devices** before planning gateway cutover; pre-10.2(3) forces an either/or sequence. |
| 10 | ⚠️ **Mandatory pre-step (maintenance window):** reconfigure the **legacy HSRP virtual MAC to match the fabric DAG MAC** (e.g. `2020.0000.00aa`) *before any workload moves*, then fail HSRP standby→active to force a **gratuitous ARP**. **Not all hosts honor GARP** (static / GARP-ignoring stacks need a manual ARP flush). A vMAC mismatch at cutover **black-holes the subnet** until ARP caches expire. *(With no FHRP — e.g. single physical gateways — there is no vMAC to pre-align, but the same gateway-MAC-change + forced-ARP-refresh risk applies.)* |
| 11 | **NDFC brownfield *import* ≠ data-plane migration.** Import *adopts* an already-built EVPN fabric into NDFC (non-disruptive, preserves configs, CDP-seed discovery, Nexus 9000 only). Don't conflate "adopt an existing fabric into the controller" with "move workloads off legacy STP/FabricPath." |
| 12 | **NDFC brownfield import has two overlay modes** (Advanced > Overlay Mode): **`config-profile`** (default) re-templatizes to NDFC profiles + strips redundant CLI (full lifecycle mgmt); **`CLI`** preserves existing overlay config as-is (minimal change). Mode locks once overlays deploy. |

## 4 · Campus EVPN (the 2025 reframe)
| # | Finding |
|---|---------|
| 13 | **SD-Access (Catalyst Center) now offers BGP EVPN as an in-product control-plane option** alongside the original LISP (Catalyst 9000 / IOS-XE **17.12.2+**). So "SD-Access vs DIY Catalyst-9000 EVPN" is now partly a **control-plane toggle**: **LISP** for large distributed wired+wireless mobility; **EVPN** for standards-based, multi-vendor, end-to-end *wired* fabric beyond the campus boundary. One Catalyst Center runs one or the other. |
| 14 | **SDA-EVPN mirrors DC EVPN:** IS-IS underlay via LAN Automation (brownfield may keep any existing IGP), iBGP overlay with **spine = RR**, distributed anycast gateway. Catalyst Center auto-manages iBGP **only** for L2VPN, mVPN, IPv4/IPv6 VRF AFs. Roles: Leaf (L3 access), Spine (RR), Border (edge), Border-Spine (collapsed core). **DC EVPN design knowledge transfers directly to campus.** |

## 5 · Day-2 ops & risk
Assured pieces: **Nexus Dashboard Insights** (assurance/observability), **NDFC fabric-consistency checks**, and the
named pitfalls — multiple active L2 interconnects → loop (overlay won't break it), gateway-MAC mismatch →
black-holing at cutover, pre-10.2(3) HSRP/DAG incompatibility, hosts ignoring GARP. *Honest gap: no single
ranked PRIMARY "top EVPN failure modes" source surfaced — this list is assembled from the migration white papers.*

## Refuted by the adversarial pass (3 claims, 0-3)
- ✗ "3rd-gen APIC (M3/L3/SE-NODE-G2) retired as of late 2025 / a Dec-14-2025 bulletin."
- ✗ "APIC-G5 is Cisco's stated replacement + a dedicated G5 cluster-migration guide proves ACI reinvestment."
- ✗ "HSRP and EVPN DAG must *never* coexist on a subnet" — that is exactly what NX-OS 10.2(3)+ enables (finding 9).

## Caveats / re-verify at engagement time
- **Strategic direction is the fastest-moving item** — "Nexus One Fabric" is Nov-2025; re-check before quoting it.
- **Version-pin everything:** NDFC scale = 12.1.3b; ND convergence = 4.x. Confirm against deployed releases.
- **Open questions:** a primary *ACI→NX-OS-EVPN* migration guide (the classic-Ethernet/FabricPath paths are
  well-documented; an ACI→EVPN one was not surfaced); post-12.1.3 verified-scale revisions; a ranked day-2
  failure-mode source; SDA-EVPN-vs-LISP scale/feature parity (wireless, SGT, multi-site).
- vPC back-to-back is for the *seamless* case; **NX-OS 10.6.x ESI multihoming** is an emerging standards-based
  alternative not yet displacing it.

## Primary sources
- Cisco blog — [Nexus One Fabric](https://blogs.cisco.com/datacenter/cisco-nexus-one-fabric-unify-data-center-operations-with-open-vxlan-evpn-standards) (Nov 19 2025)
- Cisco — [APIC EoS/EoL notice listing](https://www.cisco.com/c/en/us/products/cloud-systems-management/application-policy-infrastructure-controller-apic/eos-eol-notice-listing.html)
- Cisco Live — [BRKDCN-2918 (2024) fabric design](https://www.ciscolive.com/c/dam/r/ciscolive/global-event/docs/2024/pdf/BRKDCN-2918.pdf)
- Cisco Live — [BRKDCN-2951 (2025) migrating to VXLAN EVPN](https://www.ciscolive.com/c/dam/r/ciscolive/global-event/docs/2025/pdf/BRKDCN-2951.pdf)
- Cisco Live — [BRKENS-2650 (2025) campus EVPN / SD-Access](https://www.ciscolive.com/c/dam/r/ciscolive/global-event/docs/2025/pdf/BRKENS-2650.pdf)
- Cisco — [NDFC 12.1.3b Verified Scalability Guide](https://www.cisco.com/c/en/us/td/docs/dcn/ndfc/1213/verified-scalability/cisco-ndfc-verified-scalability-1213.html)
- Cisco — [Migrating Classic Ethernet to VXLAN BGP EVPN (white paper)](https://www.cisco.com/c/en/us/td/docs/dcn/whitepapers/migrating-classic-ethernet-to-vxlan-bgp-evpn-white-paper.html)
- Cisco — [Migrating a FabricPath environment to VXLAN BGP EVPN](https://www.cisco.com/c/en/us/td/docs/dcn/whitepapers/migrating-fabricpath-environment-vxlan-bgp-evpn.html)
- Cisco — [NDFC Brownfield Deployment guide](https://www.cisco.com/c/en/us/td/docs/dcn/ndfc/121x/configuration/fabric-controller/cisco-ndfc-fabric-controller-configuration-guide-121x/brownfield-deployment.html)
- Cisco — NX-OS Nexus 9000 VXLAN Config Guide, "Default Gateway Coexistence of HSRP and Anycast Gateway" (10.2(x)–10.6(x))
- Cisco — [SDA Cloud Campus Fabric with BGP EVPN VXLAN CVD](https://www.cisco.com/c/en/us/td/docs/solutions/CVD/Campus/Cloud_Campus_Fabric_with_BGP_EVPN_VXLAN_CVD_v0_9.html)
- IETF — RFC 7432 (BGP MPLS-Based Ethernet VPN), draft-sajassi-l2vpn-rvpls-bgp-00 (Mar 2010)
