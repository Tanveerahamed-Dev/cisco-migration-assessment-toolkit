"""CCDE-grounded network-design doctrine knowledge base (offline, evidence-mappable).

The senior-network-DESIGN-engineer brain: a curated set of network-design PRINCIPLES distilled
from the CCDE (Cisco Certified Design Expert) body of knowledge -- the 20-session design-technology
series, the worked design scenarios, and the CCDE In Depth study guide. Each principle carries the
design intent (the WHY), the trade-offs it balances, the OBSERVABLE brownfield condition that should
trigger it, the recommended target pattern, alternatives, a short source citation, and whether the
assessment engine can currently detect its trigger (engine_actionable).

design_advisor.compute_design_blueprint is the consumer: it matches the engine's collected evidence
against the engine_actionable principles to emit traceable target-state design decisions, and uses
TRADEOFF_AXES as the fixed-budget scorecard a senior designer reasons over.

Provenance / copyright: the principles below are an ORIGINAL, distilled re-expression of design ideas
(facts and engineering doctrine -- not copyrightable expression); no verbatim source text is reproduced.
Citations point to the originating CCDE topic for traceability only.
"""

import json

TRADEOFF_AXES = [
 {
  "key": "availability",
  "label": "High availability & resiliency",
  "intent": "Survive component, link and node failure; size redundancy to the requirement, not uniformly."
 },
 {
  "key": "convergence",
  "label": "Fast convergence",
  "intent": "Restore forwarding quickly after a failure (timers/BFD/summarization), traded against stability."
 },
 {
  "key": "scalability",
  "label": "Scalability",
  "intent": "Grow without redesign; bound table size, flooding scope and broadcast-domain size."
 },
 {
  "key": "modularity",
  "label": "Modularity & hierarchy",
  "intent": "Replicable, fault-isolating building blocks with clear tiers; the enabler of the other axes."
 },
 {
  "key": "security",
  "label": "Security & segmentation",
  "intent": "Least privilege, zoning, and control-/management-plane protection."
 },
 {
  "key": "simplicity",
  "label": "Simplicity vs complexity",
  "intent": "Prefer the simplest design that meets the requirement; complexity is a hidden, compounding cost."
 },
 {
  "key": "optimal_routing",
  "label": "Optimal routing",
  "intent": "Forwarding follows the intended, most-efficient paths; avoid suboptimal/asymmetric routing."
 },
 {
  "key": "load_balancing",
  "label": "Load balancing & efficiency",
  "intent": "Use available capacity; avoid idle redundant links (e.g. STP-blocked uplinks)."
 },
 {
  "key": "manageability",
  "label": "Manageability & operability",
  "intent": "Observable, consistent and automatable to operate (time, logging, AAA, baselines)."
 },
 {
  "key": "cost",
  "label": "Cost / affordability",
  "intent": "The universal counterweight every other axis draws from; spend where a requirement justifies it."
 }
]

METHODOLOGY = "SENIOR-DESIGNER MINDSET the engine should embody:\n\n1) WHY-FIRST, top-down. A design is good ONLY if it meets requirements; technology is chosen last. The reasoning order is WHY (business intent) -> WHAT (functional/application/technical requirements + fixed constraints) -> HOW (topology/protocol/device). Every target-state recommendation must trace to a stated requirement, never to a default technology preference or to maximizing one property in isolation. The engine, which holds rich current-state but NO requirements model, must therefore present its findings as evidence and explicitly flag the requirement gaps it cannot fill, rather than asserting 'the design should be X.'\n\n2) REQUIREMENTS GATHERING & CLASSIFICATION. Tag every gathered fact into exactly one bucket: business goal, functional requirement, application requirement (traffic profile, criticality, QoS/latency budget, RTO/convergence target), technical/non-functional -ility (availability, performance, scalability, security, manageability), or fixed CONSTRAINT (budget, installed base, skills, vendor/standards, regulatory, geography). Constraints BOUND the solution space and routinely veto the technically-ideal option — the engine must filter candidate recommendations through the constraint first. Maintain bidirectional traceability: requirement -> design decision -> validation test (and backward, decision -> why). Discovery captures, at minimum, the SLA/availability targets, the application communication matrix, and current device CPU/memory/capacity — each directly constrains topology, redundancy and QoS.\n\n3) CORE TRADE-OFF AXES the engine should reason over (treat as a fixed budget — raising one spends from the others; require ONE explicitly-ranked primary driver per decision, then record which axes were deliberately traded away): High-availability/resilience; Fast-convergence; Scalability; Modularity/hierarchy (an enabler); Security/segmentation; Simplicity-vs-complexity (the meta-axis and hidden cost); Optimal-routing; Load-balancing/efficient-resource-use; Manageability/operability; Cost/affordability (the universal counterweight, a tiebreaker only when the scenario names it). The canonical conflicts: HA vs cost/simplicity; fast-convergence vs stability; scalability vs optimal-routing (summarization hides specifics and risks black-holing); security vs usability/performance; load-balancing vs deterministic routing; redundancy past two tiers raises MTTR and LOWERS availability ('two's company, three's a crowd').\n\n4) COUNTEREXAMPLES OVER VIBES; ONE SOURCE OF TRUTH; COVERAGE-HONEST. Ground every device claim in collected evidence (cite the field). 'Not observed' must NEVER silently become 'healthy' — the bare-show-logging-on-NX-OS and the 'none'-is-truthy-FHRP false-health classes are the canonical failure modes the engine guards against (FHRP 'none' is unprotected; an uncollected core device is redundancy-UNKNOWN, not redundant). Reconcile every shared fact (device counts, VLANs, IPs, FHRP state) to a single canonical source so deliverables and dashboards cannot drift. Where a design principle is sound but NOT detectable from the snapshot evidence (35 of 62 here — summarization, area design, MPLS, VPN, BGP/multicast control plane, convergence mechanisms, the entire requirements layer), surface it as human-applied GUIDANCE and say so, rather than fabricating a finding. Proposer != verifier: an independent pass checks every consequential output against the baseline.\n\n5) ENGINE-AS-ASSISTANT, NOT ORACLE. The engine's job in this doctrine is to (a) detect the ~27 conditions it CAN observe and anchor them to evidence, (b) render UNKNOWN honestly for uncollected scope, and (c) carry the remaining principles as a design checklist the senior engineer applies once the requirements (which the engine does not hold) are known. The structuring discipline — one canonical, ID'd, declarative dataset of design decisions, each linking requirement<->decision<->validation, with documents and dashboards as pure renders of it — is how the engine keeps its outputs drift-free and auditable, mirroring the single-source-of-truth + docs-as-code patterns the web validation confirmed."

_DOCTRINE_JSON = "[\n {\n  \"id\": \"dc-restrict-vlan-span-routed-access\",\n  \"title\": \"Confine each VLAN to a single access switch and consider routed access to shrink oversized L2 domains\",\n  \"domain\": \"dc-switching\",\n  \"priority\": \"Critical\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"Limiting a VLAN's span keeps the spanning-tree and broadcast/failure domain small and deterministic, so a loop or storm is contained to one closet instead of rippling fleet-wide — and it is the prerequisite that makes routed access possible. Where VLANs need not span access switches, push the L3 boundary down (routed access): uplinks become routed (ECMP, fast IGP) with no STP and no FHRP, convergence becomes a routing event, and even a transient loop is a self-clearing microloop bounded by TTL. Make routed-access switches IGP stubs (EIGRP stub, or keep OSPF area 0 off the access) and summarize at the distribution boundary. Large flat L2 relying on STP is meltdown-prone.\",\n  \"tradeoffs\": \"Fault-domain containment, fast/deterministic convergence and no STP/FHRP complexity vs the loss of L2 adjacency across access switches (workload mobility, L2 clustering, vMotion) and more L3 config per access switch. Optimal routing vs one big L2 domain.\",\n  \"trigger\": \"A VLAN trunked across many access switches/closets relying on STP (large flat/oversized broadcast domain), no fabric/LAG to break loops, or STP/HSRP convergence being the failover bottleneck where VLANs need not span.\",\n  \"observable\": \"Directly observable. vlan_inventory is the canonical single source for VLAN count and explicitly flags flat/large L2 domains; the topology layer shows VLANs spanning multiple access switches and STP scope. So 'oversized/stretched L2 domain' is firmly detectable. Whether routed-access is appropriate depends on the L2-adjacency requirement (not held), so the recommendation is conditional.\",\n  \"recommended_action\": \"Scope each access VLAN to one switch and route between them at distribution; where mobility is genuinely required use an overlay (VXLAN/anycast gateway) rather than a flat stretched VLAN; adopt routed access (with stub access switches + distribution summarization) where VLANs need not span.\",\n  \"alternatives\": \"Deliberately stretched VLANs with storm-control/loop-guard and a tight failure-domain plan where L2 adjacency is required; fabric/anycast-gateway as the DC-scale equivalent.\",\n  \"citation\": \"CCDE In Depth Ch.1 / Session 16 (limit VLAN span, routed access, EIGRP stub + summary); engine vlan_inventory\"\n },\n {\n  \"id\": \"dc-multichassis-lag-over-stp\",\n  \"title\": \"Use multi-chassis link aggregation (vPC/VSS/SVL/MLAG) so redundant links forward without STP blocking\",\n  \"domain\": \"dc-switching\",\n  \"priority\": \"High\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"STP guarantees loop-freedom by blocking redundant links, so half the bandwidth sits idle and recovery is a reconvergence event. Bond redundant links into LACP port-channels that span two physical upstreams (vPC on Nexus, StackWise Virtual on Catalyst 9000, VSS on legacy 4500/6500, vendor MLAG) so both uplinks forward and the loss of one upstream is a sub-second port-channel member failure, not an STP topology change. On Catalyst 9000 distribution/core pairs prefer SVL; for fixed access use StackWise; migrate legacy VSS to SVL on refresh. At fabric scale an IS-IS-based L2 fabric (FabricPath/TRILL/SPB) also lets all links forward.\",\n  \"tradeoffs\": \"Active-active bandwidth and node-redundant uplinks vs configuration/operational complexity (peer-link, peer-keepalive, consistency checking) and tighter coupling of the paired switches; vPC keeps independent control planes (lower correlated-failure risk) while SVL/VSS merge to one (simpler but shared fate).\",\n  \"trigger\": \"Redundant uplinks with STP blocking one (idle link), an aggregation/ToR pair not configured as vPC/VSS/SVL/MLAG so downstreams cannot bond across both, or dual-NIC servers single-homed.\",\n  \"observable\": \"Directly observable. The engine detects STP-blocked redundant links ('a redundant link exists but is STP-blocked'), single non-port-channel uplinks as SPOFs, and EtherChannel/port-channel bundle membership from show etherchannel/port-channel summary — so 'redundant link idle under STP' and 'no port-channel where two exist' are detectable. It does not always know whether the upstream pair is a vPC/SVL domain (that needs both peers collected).\",\n  \"recommended_action\": \"Configure the aggregation/ToR pair as vPC/VSS/SVL/MLAG and present dual-homed downstreams a single LACP port-channel so both members forward; prefer SVL on Catalyst 9000, migrate legacy VSS to SVL; use an L2 fabric at large scale.\",\n  \"alternatives\": \"StackWise data-plane stacking for fixed access; routed (L3 ECMP) uplinks instead of L2 bonding; RSTP/MST as the loop-prevention backstop.\",\n  \"citation\": \"CCDE Session 16 (port-channel/TRILL over STP, vPC/VSS/MLAG); Cisco StackWise Virtual reference 2025\"\n },\n {\n  \"id\": \"dc-spine-leaf-evpn-vs-collapsed\",\n  \"title\": \"Adopt spine-leaf (VXLAN-EVPN) for the modern DC; keep collapsed-core+vPC only for small/static footprints\",\n  \"domain\": \"dc-switching\",\n  \"priority\": \"High\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"Spine-leaf (Clos) gives predictable, deterministic, equal-cost east-west bandwidth — every leaf one hop from every other via the spine, scaling by adding leaves (capacity) or spines (bandwidth) — and replaces an STP-bound oversubscribed tree for server-to-server traffic. The 2024+ pattern is a 3-stage CLOS with a BGP EVPN control plane (leaf=VTEP, spine=pure ECMP transit, anycast gateway on leaf), with VXLAN-EVPN Multi-Site for selective inter-DC L2/L3 extension. A traditional collapsed-core + vPC DC remains acceptable only for small/static scale.\",\n  \"tradeoffs\": \"Scale/determinism/multi-tenancy + segmentation vs the operational-maturity step to L3/overlay (ECMP, EVPN, automation/NDFC) and more inter-switch links; collapsed core is simpler/cheaper but STP-bounded with no overlay mobility/segmentation and a larger blast radius.\",\n  \"trigger\": \"A DC built as a 3-tier STP tree with oversubscribed/asymmetric east-west paths and growing server-to-server traffic, or STP blocking links in the DC.\",\n  \"observable\": \"Partially observable. The engine reconstructs topology and vlan_inventory and detects STP-blocked redundant links and oversized L2 domains in the DC, so 'STP-bound DC tree' is a detectable shape; it does not classify spine-leaf vs 3-tier or model east-west traffic, so the recommendation toward EVPN is heuristic. The [HISTORY-REDACTED] fleet's uncollected DS/CS core + EVS vPC pair limit DC-side conclusions.\",\n  \"recommended_action\": \"Design the DC as a leaf-spine CLOS with BGP-EVPN overlay (anycast gateway on leaf, endpoints only on leaves, ECMP) and VXLAN-EVPN Multi-Site for DCI; keep collapsed-core+vPC only for small/static DCs.\",\n  \"alternatives\": \"Traditional 3-tier for small footprints; FabricPath/TRILL/SPB as an L2 multipath fabric where an IP/overlay fabric is not yet justified.\",\n  \"citation\": \"CCDE Session 16 (spine-leaf); Cisco Nexus 9000 VXLAN BGP EVPN design guide; VXLAN-EVPN Multi-Site WP\"\n },\n {\n  \"id\": \"dc-stp-determinism-edge-protection\",\n  \"title\": \"Engineer a deterministic STP root at distribution, run Rapid-STP, and protect the topology (PortFast/BPDU/Root/Loop Guard, UDLD)\",\n  \"domain\": \"dc-switching\",\n  \"priority\": \"High\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"Where STP must exist, make it deterministic and fast: hard-set primary/secondary root on the distribution/aggregation pair (never let a low-MAC access switch win), run Rapid-PVST/RSTP (sub-second proposal/agreement) or MST at scale instead of legacy 802.1D, and protect the topology — PortFast + BPDU Guard on host ports (immediate forwarding, err-disable on a rogue BPDU), Root Guard where a port must never lead to root, and Loop Guard + UDLD on fibre uplinks to catch unidirectional links that would otherwise open a loop. Align the root with the FHRP active gateway. Use UDLD aggressive mode on dual-homed paths but normal mode (or ensure an alternate path) on single-homed links.\",\n  \"tradeoffs\": \"Deterministic optimal L2 paths, fast convergence and loop safety vs the discipline of explicit priorities and a small risk of err-disabling a legitimately-connected switch port or, with UDLD aggressive on a single-homed link, isolating a device with no backup path.\",\n  \"trigger\": \"STP root elected by default/lowest-MAC (root on an access switch), legacy/slow 802.1D, host ports without PortFast+BPDU Guard, no Root/Loop Guard, fibre uplinks without UDLD, or root misaligned with the FHRP active gateway.\",\n  \"observable\": \"Partially observable. The engine parses STP per device (mode rstp/pvst, root, blocked/inconsistent ports, max TCN) so 'legacy STP mode' and inconsistency/blocking are detectable, and it has a root-placement notion (root should be at distribution). PortFast/BPDU/Root/Loop Guard and UDLD enablement are config stanzas it does not robustly extract today, so edge-protection presence is largely NOT detected.\",\n  \"recommended_action\": \"Hard-set primary/secondary root on distribution for every VLAN/MST instance aligned to the active gateway; run Rapid-PVST/RSTP (MST at scale); enable BPDU Guard globally for PortFast edge ports, Root Guard on non-root ports, Loop Guard + UDLD on fibre (aggressive only on dual-homed).\",\n  \"alternatives\": \"Routed access to remove STP from the edge entirely; MST for per-instance control at scale; UplinkFast/BackboneFast on legacy PVST.\",\n  \"citation\": \"CCDE Session 16 (root at distribution, Rapid STP, BPDU/Root/Loop Guard, UDLD); engine STP parsing\"\n },\n {\n  \"id\": \"dc-three-tier-vs-collapsed-core\",\n  \"title\": \"Use a three-tier hierarchy for scale (or full-mesh the distribution if collapsing the core), and tier for blast-radius + RBAC\",\n  \"domain\": \"dc-switching\",\n  \"priority\": \"High\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"The core tier exists primarily for scalability: it lets distribution blocks grow by addition (hub-and-spoke of blocks) instead of meshing every distribution switch to every other. Add a dedicated core once the number of distribution blocks makes a collapsed-core mesh unwieldy; if intentionally core-less, fully mesh the distribution and place STP root/FHRP there. A layered Access/Pre-Agg/Agg/Core hierarchy also scales the control plane, contains the blast radius of any failure to one tier, gives faster localized convergence, and aligns operational/RBAC boundaries (juniors on edge, seniors on core).\",\n  \"tradeoffs\": \"Scale/fault-containment/operational separation vs cost and end-to-end path length — more tiers add devices/hops/design effort but localize faults and SPF scope; collapsing tiers is cheaper and lower-latency but widens the blast radius. Cisco scopes the collapsed core to smaller locations only.\",\n  \"trigger\": \"A collapsed/two-tier core with many distribution blocks but no full-mesh between them (growth blocked), a single collapsed switch carrying both roles, or a flat/collapsed estate where any change has fleet-wide reach and there is no role separation.\",\n  \"observable\": \"Partially observable. blast_radius/move_groups quantify how far a single removal propagates and which switches are coupled (a fault-domain/blast-radius proxy), and topology reconstruction shows the interconnect; the engine does not firmly label tiers (core/distribution/access role inference is limited), so 'collapsed core needs a dedicated core' is heuristic.\",\n  \"recommended_action\": \"Introduce a dedicated fast core so distribution blocks attach and scale by addition; if core-less, fully mesh the distribution with root/FHRP there; tier the network (with per-tier flooding domains and summarization) to bound blast radius and align RBAC.\",\n  \"alternatives\": \"Collapsed core for small/cost-bound sites (accept wider blast radius); two-tier spine-leaf for the DC; keep flat where the network is small and stable.\",\n  \"citation\": \"CCDE Session 16 (3 tiers = scalability, full-mesh distribution if no core); CCDE scenario (tiering = blast radius + RBAC)\"\n },\n {\n  \"id\": \"dc-igmp-snooping-and-app-delivery\",\n  \"title\": \"Enable IGMP/MLD snooping with a querier and group limits, and insert load-balancing at DC aggregation\",\n  \"domain\": \"dc-switching\",\n  \"priority\": \"Medium\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"Without snooping a switch floods multicast to every port in the VLAN like broadcast, wasting access bandwidth and host CPU; enable IGMP (IPv4)/MLD (IPv6) snooping on multicast VLANs — which requires an IGMP querier per active VLAN — and cap groups-joined per access port to bound (S,G) state and resist join floods. Insert application-delivery / load-balancing appliances at the DC aggregation layer (the natural service-insertion point where server-bound traffic converges), deployed as a redundant pair with health-check/persistence/server-selection policy — not at the access (too distributed) or the core (must stay fast and policy-free).\",\n  \"tradeoffs\": \"Bandwidth efficiency and abuse control vs dependence on a correctly-placed querier (a missing active VLAN strands snooping state) and group caps that can deny legitimate joins; centralized ADC policy and clean insertion vs creating a potential choke point/SPOF at aggregation (deploy as a pair).\",\n  \"trigger\": \"Multicast present but IGMP/MLD snooping disabled (flooded VLAN-wide), no querier for an active multicast VLAN, no per-port group cap, or load balancers/ADC placed at access/core with no health-check/persistence policy.\",\n  \"observable\": \"Partially observable. The querier dimension is exactly the engine's evidence: build_igmp_queriers records per-VLAN queriers (one per active L2 segment), so active multicast VLANs and the cutover-stranding risk of a missing one are surfaced. Snooping-enablement and group caps are config the engine does not parse; ADC/load-balancer placement is not modelled (separate appliances).\",\n  \"recommended_action\": \"Enable IGMP/MLD snooping on multicast VLANs with a querier per active VLAN and per-interface group-join limits; deploy load-balancing/ADC as a redundant pair at the DC aggregation layer with health-check and persistence.\",\n  \"alternatives\": \"Static multicast forwarding for fixed receivers; PIM/querier on the SVI gateway; distributed/host-based load balancing or service mesh for cloud-native workloads; DNS/GSLB across sites.\",\n  \"citation\": \"CCDE Session 16 (IGMP snooping/limits, ADC at aggregation); engine build_igmp_queriers\"\n },\n {\n  \"id\": \"igp-link-state-default\",\n  \"title\": \"Default to a link-state IGP; reserve distance-vector for specific niches\",\n  \"domain\": \"igp\",\n  \"priority\": \"High\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"Link-state (OSPF/IS-IS) gives every router an identical topology database, so each makes a fully-informed, loop-free path decision and converges predictably as the network grows. Standardize on link-state for any meshed, multi-path or growth-bound topology; choose distance-vector (EIGRP) only where its operational simplicity genuinely fits (hub-and-spoke edges, all-Cisco stubs).\",\n  \"tradeoffs\": \"Visibility/scale vs simplicity/resources — link-state needs more CPU/memory and operator skill but handles mesh and growth; EIGRP is lighter and simpler with easy summarization/query-containment but is Cisco-centric and weaker in mesh.\",\n  \"trigger\": \"Meshed/partial-mesh core running distance-vector, or a flat single-IGP network with no hierarchy slated to grow.\",\n  \"observable\": \"Directly observable. The routing-protocol inventory reports which IGP (OSPF/EIGRP/IS-IS) runs per device from parsed neighbour/state output, so 'distance-vector in a meshed core' or 'one flat IGP' is detectable. Whether the topology is truly meshed is reconstructed from CDP/LLDP adjacency (partial), so the meshed-ness qualifier is weaker than the protocol-identity fact.\",\n  \"recommended_action\": \"Adopt OSPF or IS-IS as the strategic core/campus IGP with a defined area/level hierarchy; keep EIGRP only for hub-and-spoke edges/stubs where it fits.\",\n  \"alternatives\": \"Keep EIGRP where it already serves small/medium hub-and-spoke well; BGP as inter-domain glue; mixed designs by tier.\",\n  \"citation\": \"CCDE Session 4 (IGP comparison) Link-State vs Distance-Vector; engine routing-protocol inventory\"\n },\n {\n  \"id\": \"mgmt-secure-protocols-and-rbac\",\n  \"title\": \"Enforce secure management (SSH/SNMPv3), centralized RBAC/AAA least-privilege, and retire plaintext\",\n  \"domain\": \"management\",\n  \"priority\": \"Critical\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"The management plane is the most privileged access path, so eliminate clear-text: SNMPv1/v2c carry community strings in plaintext and Telnet exposes credentials, so standardize on SNMPv3 (auth+priv) and SSH, disable Telnet/SNMPv1-v2c, and scope SNMP views to least information. Control who can do what via centralized AAA (TACACS+ for command authorization/accounting) with role-based CLI and least privilege, a guarded local fallback, banners and session timeouts — so every action is attributable and instantly revocable.\",\n  \"tradeoffs\": \"Confidentiality/integrity/accountability of the most-privileged plane vs the config overhead of v3 users/views, role definitions and an available AAA infrastructure; some legacy tools may only speak v2c.\",\n  \"trigger\": \"SNMPv1/v2c with plaintext (or default public/private) community strings, Telnet enabled, shared/local admin accounts with no TACACS+/RADIUS or command authorization (everyone effectively privilege-15).\",\n  \"observable\": \"Partially observable. The CIS/config-security audit detects Telnet-vs-SSH, SNMP version/community exposure, AAA/TACACS configuration and privilege/banner items on collected run-configs and folds gaps into the punchlist. So plaintext-management and missing-AAA are firmly engine-actionable; full RBAC-role correctness is partial.\",\n  \"recommended_action\": \"Standardize SNMPv3 + SSH, disable Telnet/SNMPv1-v2c, scope SNMP views; centralize AAA (TACACS+ command-authz/accounting + RADIUS access) with RBAC/least-privilege, guarded local fallback, banners and timeouts.\",\n  \"alternatives\": \"Read-only v2c restricted to a mgmt VRF with strong ACLs as an interim where v3 is unsupported; external IdP integration for larger estates; TLS-based transports (NETCONF/SSH, gRPC/TLS) for newer stacks.\",\n  \"citation\": \"CCDE Session 19 (secure management plane, SNMP versions, RBAC/AAA/least-privilege); engine CIS axis\"\n },\n {\n  \"id\": \"mgmt-time-sync-logging-baseline\",\n  \"title\": \"Synchronize time (hierarchical NTP), centralize severity-tuned logging, and keep a current baseline + documentation\",\n  \"domain\": \"management\",\n  \"priority\": \"High\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"Accurate common time is foundational: without a single synchronized source, logs/traps/telemetry/security events cannot be correlated and time-dependent crypto fails — deploy a hierarchical, authenticated NTP design feeding the whole fleet from a small set of trusted strata. Centralize syslog to a time-stamped collector and tune severity so the right signal is captured without drowning operators or leaking sensitive debug detail. And you cannot plan a target state or detect anomalies without knowing where you are — capture a current-state baseline (utilization, protocols, topology) and maintain layered living documentation (physical, logical/L2-L3, addressing, routing, services, security, hardware/config inventory).\",\n  \"tradeoffs\": \"Correlatable logs, reliable time-crypto, informed design and anomaly detection vs the effort to design/secure a stratum hierarchy and to keep logs and documentation current (stale docs mislead, verbose logging stresses devices); fault visibility vs log volume/storage/exposure.\",\n  \"trigger\": \"Inconsistent/unconfigured device clocks or unauthenticated/divergent NTP, no central time-stamped syslog (logs buffered locally and lost on reload), logging level mis-set, or missing/outdated baseline/topology/addressing documentation.\",\n  \"observable\": \"Partially observable. The CIS/config-security audit can detect NTP and logging configuration (NTP server presence, logging host/level) on collected devices; the engine itself produces a current-state baseline (inventory, topology, vlan_inventory, dossiers) which IS the documentation artifact. So NTP/syslog config gaps are partially detectable and the baseline is directly produced; whether external living documentation exists is not observable.\",\n  \"recommended_action\": \"Deploy hierarchical authenticated NTP from trusted strata to the whole fleet; forward all logs to a central NTP-stamped syslog/SIEM with per-platform severity tuned to capture warnings/errors while suppressing chatty debug; capture and maintain a baseline + layered documentation via automated discovery.\",\n  \"alternatives\": \"PTP/IEEE-1588 for sub-microsecond needs; streaming telemetry/EEM for high-value events; tiered (local+central) collectors at scale; periodic audit-and-reconcile instead of fully automated capture.\",\n  \"citation\": \"CCDE Session 19 (NTP stratum, syslog levels, baseline & documentation); engine CIS axis + baseline output\"\n },\n {\n  \"id\": \"fhrp-first-hop-gateway-redundancy\",\n  \"title\": \"Provide first-hop (gateway) redundancy on every L2-access default gateway\",\n  \"domain\": \"methodology\",\n  \"priority\": \"Critical\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"Where access connects to distribution at Layer 2 there is more than one distribution switch for redundancy, so a first-hop redundancy protocol (HSRP/VRRP/GLBP) is required to keep the default gateway alive when one distribution node fails. Without it, a distribution failure black-holes the whole subnet regardless of physical redundancy. Modern guidance prefers eliminating FHRP via a single logical gateway (StackWise Virtual/vPC) or anycast gateway (VXLAN-EVPN) where the platform supports it.\",\n  \"tradeoffs\": \"HA vs simplicity; standards/multivendor vs feature richness — VRRP buys interop, GLBP adds per-flow load-balancing but is proprietary and polarizes at stateful edges; more FHRP groups add config. Collapsing the control plane (SVL/anycast) removes FHRP entirely but is a platform/maturity step.\",\n  \"trigger\": \"L2 access with a single configured gateway/SVI per VLAN on one distribution switch and no HSRP/VRRP/GLBP standby observed.\",\n  \"observable\": \"Directly observable. compute_fhrp_consistency and the canonical (fhrp or 'none') != 'none' gate per gateway/SVI report FHRP present/absent per VLAN; the reachability engine flags gateway SPOF (len(src_gws)<=1 -> spof). On the [HISTORY-REDACTED] fleet FHRP is absent on 0/209 gateway instances = a confirmed first-hop-redundancy gap.\",\n  \"recommended_action\": \"Introduce FHRP (HSRP or VRRP) on the distribution pair for every access VLAN gateway, or — where the platform supports it — eliminate FHRP via SVL/vPC single logical gateway or VXLAN-EVPN anycast gateway. Use VRRP for multivendor; keep GLBP off stateful Internet/firewall edges.\",\n  \"alternatives\": \"Routed-access design (removes FHRP need entirely); anycast gateway / fabric (EVPN, SPB, FabricPath); StackWise Virtual single logical gateway.\",\n  \"citation\": \"CCDE In Depth Ch.1 (FHRP & L2 access); Cisco Campus CVD 2024 (SVL/anycast preferred over GLBP, VRRPv3 multivendor)\"\n },\n {\n  \"id\": \"fhrp-not-observed-is-not-healthy\",\n  \"title\": \"Treat unobserved FHRP/redundancy as UNKNOWN, never silently as healthy\",\n  \"domain\": \"methodology\",\n  \"priority\": \"Critical\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"Redundancy claims must be evidence-grounded. A gateway with FHRP 'none' is not protected, and a device that was not collected has UNKNOWN redundancy — neither may be reported as healthy. This is the same false-health class as a bare NX-OS show logging returning nothing being read as 'no errors'.\",\n  \"tradeoffs\": \"Coverage-honesty vs a cleaner-looking report; surfacing UNKNOWN forces follow-up collection but prevents a customer-facing false-redundancy claim.\",\n  \"trigger\": \"A gateway shows FHRP 'none', or a core/distribution device that carries redundancy responsibility is in the not-collected set, yet a deliverable would assert redundancy.\",\n  \"observable\": \"Directly observable and regression-locked. The 'none'-is-truthy bug class was fixed: crd.py and runbook.py now mirror analyze.py's (fhrp or 'none') != 'none' gate (tests assert FHRP=0 on the [HISTORY-REDACTED] fleet). The coverage analyzer reports inventory/complete/partial/not_collected so uncollected core devices are flagged as blind spots, not healthy.\",\n  \"recommended_action\": \"Render 'FHRP absent' and 'not collected -> redundancy UNKNOWN' explicitly; never let a missing observation become a positive health claim. For the [HISTORY-REDACTED] DS/CS core + EVS vPC pair (uncollected), mark redundancy UNKNOWN and recommend collection.\",\n  \"alternatives\": \"Collect the missing devices to convert UNKNOWN to a real verdict; explicit time-boxed risk acceptance only with a human sign-off.\",\n  \"citation\": \"Repo doctrine (evidence-grounded, coverage-honest); commits ee3a362/642ee31 (FHRP false-health fix); analyze.py:1886 canonical FHRP gate\"\n },\n {\n  \"id\": \"lifecycle-eol-out-of-critical-roles\",\n  \"title\": \"Drive EoL/EoS hardware out of critical roles and protect against the upgrade flag-day\",\n  \"domain\": \"methodology\",\n  \"priority\": \"Critical\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"End-of-life/end-of-support gear in a core/critical role is both a risk and an obstacle to non-disruptive change. A scale-out design (redundant supervisors / paired nodes) lets you upgrade software or replace hardware without a downtime flag-day. Modernizing outdated technology is a legitimate business goal.\",\n  \"tradeoffs\": \"Investment-protection/HA vs CapEx and migration risk — refresh and scale-out cost up front but reduce long-run risk/TCO and enable hitless maintenance; deferring saves CapEx but raises outage and security exposure.\",\n  \"trigger\": \"EoL/EoS hardware or unsupported software in a core/critical role, and/or single-supervisor nodes on critical devices that force a full reload (and outage) to upgrade.\",\n  \"observable\": \"Directly observable. The lifecycle/EoL axis screens platform/version against an offline advisory dataset and the punchlist folds EoL findings; software_risk reports advisory-surface exposure cautiously ('surface open', not 'vulnerable'). Combined with role/tier context the engine can flag EoL-in-critical-role. Single-supervisor detection is partial (depends on collected hardware inventory detail).\",\n  \"recommended_action\": \"Prioritize refresh of EoL/EoS devices in core/critical roles; specify dual-supervisor/dual-RP (SSO/NSF) or paired-node scale-out so upgrades/swaps are non-disruptive; sequence the migration so no single change becomes a flag-day.\",\n  \"alternatives\": \"ISSU on a single chassis where supported; staged maintenance-window upgrades with rollback; time-boxed risk acceptance.\",\n  \"citation\": \"CCDE In Depth Ch.2 Scalability (scale-out avoids the Flag Day) & Cost/TCO; engine EoL/software_risk axes\"\n },\n {\n  \"id\": \"availability-right-sized-per-tier\",\n  \"title\": \"Right-size availability to the application and place in the network, not 5x9 everywhere\",\n  \"domain\": \"methodology\",\n  \"priority\": \"High\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"Set the availability target from business/application requirements and where in the topology the module lives, rather than reflexively engineering five/six nines everywhere. Availability = MTBF/(MTBF+MTTR); over-building wastes CapEx/OpEx and adds complexity that itself lowers availability.\",\n  \"tradeoffs\": \"HA vs cost and HA vs simplicity — each added nine multiplies redundancy, hardware and operational burden; a datacentre and a retail store legitimately warrant different SLAs, and too much redundancy raises MTTR.\",\n  \"trigger\": \"Uniform redundancy posture applied across tiers with no requirement basis (full redundancy demanded at the edge while a core SPOF is unaddressed), or a flat best-effort posture on a tier hosting real-time/critical apps.\",\n  \"observable\": \"Partly observable: the engine sees the redundancy posture per tier as evidence (FHRP present/absent per gateway, dual-homing %, SPOF/blast-radius, core devices not-collected) and can flag a mismatch shape, but it cannot judge 'right-sized' without the per-class availability target, which it does not hold.\",\n  \"recommended_action\": \"Classify sites/modules by criticality and assign an availability target per class; invest redundancy where MTBF/MTTR and app sensitivity justify it, and explicitly accept lower availability where the business does not require it.\",\n  \"alternatives\": \"Single uniform SLA fleet-wide (simpler, mis-allocates spend); per-application SLA contracts; geographic/DR-tiered availability for cost-sensitive cases.\",\n  \"citation\": \"CCDE In Depth Ch.2 High Availability ('not every network needs 5x9/6x9'); CCDE Designer Skills (availability=MTBF/(MTBF+MTTR))\"\n },\n {\n  \"id\": \"modularity-fault-domains-replicable-blocks\",\n  \"title\": \"Design in modular, replicable blocks with small fault domains\",\n  \"domain\": \"methodology\",\n  \"priority\": \"High\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"Dividing the network by function/policy boundary (campus, branch, DC, Internet, management, security) makes each block replicable, independently designed/managed, and reduces deployment time through repeatable configuration. Smaller fault domains stop a failure in one part propagating fleet-wide, and enable role-based operational access.\",\n  \"tradeoffs\": \"Scalability/operability vs the discipline cost of enforcing boundaries — a common security policy and consistent addressing must span modules, and over-fragmentation adds inter-module routing/summarization overhead and path length.\",\n  \"trigger\": \"Monolithic/flat design with no clear functional module boundaries so a fault or change in one area propagates network-wide.\",\n  \"observable\": \"Partially observable. vlan_inventory flags flat/large L2 domains and the move_groups computation reveals coupling between switches (shared-VLAN coupling = a fault-domain proxy); blast-radius shows how far a single removal propagates. The engine sees the SHAPE of fault domains but does not label functional modules (campus/DC/mgmt) explicitly.\",\n  \"recommended_action\": \"Restructure into hierarchical repeatable modules with summarization at each module edge; standardize per-module config so new blocks replicate quickly; keep a small site collapsed where modular separation is not cost-justified.\",\n  \"alternatives\": \"Leaf-spine/PoD modularity for DC scale; geographic modularization for large estates.\",\n  \"citation\": \"CCDE In Depth Ch.2 Modularity & M&A; CCDE Designer Skills (Modularity/Resiliency)\"\n },\n {\n  \"id\": \"topology-triangles-not-squares-rings\",\n  \"title\": \"Build redundancy as triangles, not squares or rings\",\n  \"domain\": \"methodology\",\n  \"priority\": \"High\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"Triangle (fully-meshed three-node) topologies converge faster on link failure because an alternate path is directly available without waiting for routing reconvergence; squares and especially rings are the hardest topologies for convergence/optimality and poor candidates for IP fast-reroute. Dual-home each access/leaf to two upstreams so failover is a port-channel/routing event, not an STP unblock.\",\n  \"tradeoffs\": \"Fast-convergence/optimal-routing vs cost — more cross-links and ports cost money (full mesh is most expensive), so add just enough links to turn a ring/square into a partial mesh where demand or convergence justifies it.\",\n  \"trigger\": \"Core/distribution interconnect is a ring or square (each node single-homed to one neighbour, no direct cross-link) so recovery depends entirely on protocol reconvergence; or an access/leaf single-homed to one upstream.\",\n  \"observable\": \"Directly observable for the dual-homing dimension: the engine computes dual_homed sets, single (non-port-channel) uplinks, and STP-blocked redundant links, and flags 'a redundant link exists but is STP-blocked' and 'single uplink' SPOFs. Full triangle-vs-ring core-topology classification is partial (it reconstructs L1/L2 adjacency from CDP/LLDP but does not label the macro-shape).\",\n  \"recommended_action\": \"Re-cable to triangle/partial-mesh between distribution and core so each node has a direct alternate path; dual-home every access switch and bond uplinks (vPC/VSS/MLAG) so both forward.\",\n  \"alternatives\": \"Keep the ring but add MPLS-TE FRR (protects any topology including rings); full mesh only where the demand matrix warrants the cost; spine-leaf ECMP at L3.\",\n  \"citation\": \"CCDE In Depth Ch.2 Network Topologies ('Build Triangles, Not Squares'); CCDE Switching/DC Q1\"\n },\n {\n  \"id\": \"multicast-security-and-l2-edge\",\n  \"title\": \"Treat multicast as a security surface and enable IGMP snooping + group limits at the L2 edge\",\n  \"domain\": \"multicast\",\n  \"priority\": \"Critical\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"Open multicast is a DDoS vector. Define administratively-scoped multicast (239/8) with boundaries at perimeters (including Auto-RP/BSR scope filters) and remove PIM from untrusted edge interfaces so end stations cannot join the routed multicast control plane. At the access edge enable IGMP/MLD snooping so multicast is not flooded VLAN-wide like broadcast — which requires an IGMP querier per active VLAN to be present — and set per-port group-join limits to bound (S,G) state and resist join floods. Plan a deliberate group-address scheme (239/8 internal, 232/8 SSM, 233/8 GLOP) avoiding L2 MAC-overlap addresses.\",\n  \"tradeoffs\": \"Boundaries/snooping/limits sharply cut the attack surface and flooding but a missing querier strands snooping state and mis-set limits or scopes can black-hole legitimate flows; security/efficiency vs careful L2/address discipline.\",\n  \"trigger\": \"No multicast boundary/scoping, PIM on user-facing interfaces, IGMP snooping disabled on multicast VLANs, no IGMP querier for an active VLAN, no per-port group cap, or overlap-prone group addressing.\",\n  \"observable\": \"Partially observable. The querier evidence is exactly what the engine collects: build_igmp_queriers records per-VLAN queriers (IGMP querier = one per active L2 segment, so a missing active VLAN means stranded multicast at cutover — the grounding for counting them in vlan_inventory). So 'active multicast VLAN' is observed; snooping-disabled, PIM-on-edge, boundary filters, and group caps are NOT parsed. So the engine can flag querier-evidenced VLANs and their cutover risk but cannot audit the security controls.\",\n  \"recommended_action\": \"Scope 239/8 with boundaries (and Auto-RP/BSR filters), remove PIM from untrusted edges, enable IGMP/MLD snooping with a querier per active VLAN, set per-port group limits, and adopt a clean group-address plan.\",\n  \"alternatives\": \"Multicast rate-limiting and IGMP join limits as complementary controls; MVR for L2-only metro multicast; static group assignment on tightly-controlled segments.\",\n  \"citation\": \"CCDE Session 11/12 (multicast boundary, no edge PIM, IGMP snooping/limits, addressing); engine build_igmp_queriers + vlan_inventory\"\n },\n {\n  \"id\": \"qos-trust-boundary-end-to-end\",\n  \"title\": \"Establish a QoS trust boundary at the edge and a coherent end-to-end policy from app requirements\",\n  \"domain\": \"qos\",\n  \"priority\": \"High\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"Real-time apps have hard budgets (voice/video ~150ms one-way delay, ~30ms jitter, ~1% loss) that hold only if traffic is classified/marked at a trusted edge and the marking is honoured end-to-end. Trust the IP phone (conditionally its data port), mark voice via the voice VLAN, and police/re-mark untrusted data so endpoints cannot mark their own traffic into priority queues. The trust boundary lives at the access/voice edge.\",\n  \"tradeoffs\": \"Application performance vs simplicity — QoS adds classification/queuing to every hop; a capacity-rich core may deliberately omit it and over-provision instead. Trusting too liberally lets hosts game queues; trusting too little drops legitimate marks.\",\n  \"trigger\": \"Voice/video present but no QoS trust boundary at the access/voice edge (untrusted/unmarked ingress, or QoS disabled on the L2 switch), or inconsistent/absent DSCP marking and queuing end-to-end.\",\n  \"observable\": \"Directly observable. compute_qos_audit detects the trust-boundary/voice-edge posture from config — including the 'mls qos' foot-gun (global QoS disabled so all marking is untrusted) and 'voice port with no QoS' — and emits findings sorted high-first, folded into the punchlist as fleet rows. It does not measure live delay/jitter/loss (no IP SLA ingestion), so SLA conformance itself is not observed.\",\n  \"recommended_action\": \"Define a trust boundary at the access edge (trust phones/markings, re-mark untrusted ports), deploy a consistent end-to-end queuing policy sized to the app budgets, and unify divergent per-site QoS into one standard; trust access markings in the core rather than re-classifying.\",\n  \"alternatives\": \"Bandwidth over-provisioning instead of QoS in a simple capacity-rich core; per-domain QoS with re-marking only at boundaries; admission control where capacity is constrained.\",\n  \"citation\": \"CCDE In Depth Ch.2 M&A & Applications (150ms/30ms/1%); engine compute_qos_audit; Cisco Borderless Campus QoS\"\n },\n {\n  \"id\": \"qos-voice-priority-bounded\",\n  \"title\": \"Give voice strict priority but bound it; separate TCP/UDP and real-time subclasses; WRED for TCP only\",\n  \"domain\": \"qos\",\n  \"priority\": \"High\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"Real-time voice needs a strict low-latency (LLQ/EF) queue to meet its budget, but an unbounded priority queue starves other classes — so cap it with a policer and keep signaling/video in their own classes. Do not mix adaptive TCP with non-responsive UDP in one class (UDP starves TCP and makes WRED meaningless), and split real-time into voice/signaling/interactive-video/streaming-video. Use (W)RED only on TCP/AF classes to avoid global synchronization and tail-drop bursts; keep tail-behaviour off the EF/voice queue.\",\n  \"tradeoffs\": \"Latency guarantee for voice vs starvation protection for data; more classes give correctness but cost hardware resources; WRED smooths TCP but is pointless/harmful on UDP/voice.\",\n  \"trigger\": \"Voice with no priority queue or an uncapped strict-priority queue, a single class carrying both TCP and UDP, one lumped 'real-time' class, or WRED applied to a UDP/EF class.\",\n  \"observable\": \"Partially observable. compute_qos_audit detects voice-edge QoS presence and trust posture; it does not parse policy-map internals deeply enough to assert 'priority queue uncapped' or 'TCP and UDP share a class' or 'WRED on EF', so these queue-internals are largely NOT detected.\",\n  \"recommended_action\": \"Place voice in a bounded LLQ/EF class with a policer; give signaling and each video type its own class; separate TCP from UDP; apply (W)RED to TCP/AF classes only and exempt voice/UDP.\",\n  \"alternatives\": \"CBWFQ guaranteed-bandwidth class where latency budget allows; admission control to cap voice flows; collapse subclasses only when class-count limits force it.\",\n  \"citation\": \"CCDE Session 10 (LLQ bounding, TCP/UDP separation, WRED for TCP); CCDE scenario (RFC4594, WRED TCP-only)\"\n },\n {\n  \"id\": \"qos-class-model-from-app-profile\",\n  \"title\": \"Derive a lean DSCP/PHB class model from the application profile and align it to platform/WAN limits\",\n  \"domain\": \"qos\",\n  \"priority\": \"Medium\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"QoS is meaningless without classification driven by real apps. Build a small, RFC-4594-aligned class set (EF voice, AF video/business, CS control/signaling, default/BE, scavenger) mapped from the application inventory, sized to the platform queue/WRED/shaper limits and the WAN/SP's supported class count (commonly ~4-8, never 64). Mark close to the source so downstream nodes act on a simple DSCP field instead of re-running deep classification.\",\n  \"tradeoffs\": \"Granularity/precision vs hardware limits, operational simplicity and SP class-count constraints; too many classes hit hardware ceilings, too few starve real-time. Standardization vs per-device drift.\",\n  \"trigger\": \"Inconsistent/ad-hoc/absent DSCP markings across the fleet, class models exceeding the WAN/platform limit, or classification/marking happening deep in the network instead of at the edge.\",\n  \"observable\": \"Partially observable. compute_qos_audit detects per-device QoS config presence/shape and inconsistency (and the global-QoS-disabled foot-gun), so 'no/ad-hoc marking' is detectable; it does not compare class counts against an SP contract or fully normalize each device's DSCP-PHB map, so 'too many classes vs the SP' is not detected.\",\n  \"recommended_action\": \"Define and roll out an RFC-4594 DSCP/PHB scheme at the edge; consolidate to the lean class set the platform and WAN both support; mark close to source and trust those marks downstream.\",\n  \"alternatives\": \"Legacy IP-Precedence mapping on old gear; a smaller custom class set negotiated with the SP; collapse business-hi/lo to reduce count.\",\n  \"citation\": \"CCDE Session 10 (RFC 4594, minimize classes, close-to-source); CCDE scenario (1 PQ + N BQ from app matrix)\"\n },\n {\n  \"id\": \"scenario-ask-missing-requirements-no-assumptions\",\n  \"title\": \"Gather the decision-driving requirements before designing — never assume, never re-ask what's given\",\n  \"domain\": \"scenario-pattern\",\n  \"priority\": \"High\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"Start only after the inputs that actually change the design are known (the partner's existing edge capability determines new-circuit-vs-tunnel; the data's security classification determines encryption; the convergence target determines redundancy; provider reach/feature support determines the VPN option) and refuse to invent state or re-request facts already provided. Premature best-practice answers that ignore stated constraints are the classic failure mode. Run a discovery pass that captures SLA/availability (and penalty terms), the application communication matrix (per-app latency/loss/bandwidth, TCP/UDP, flows), and current device CPU/memory/capacity utilization, because each one directly constrains topology, redundancy and QoS.\",\n  \"tradeoffs\": \"Correct, requirement-grounded design vs the time of a discovery round-trip; assuming saves time at the risk of a costly redesign or an over/under-built network.\",\n  \"trigger\": \"A design decision being made (or a tool recommending a pattern) without the input that actually drives it — unknown existing/partner equipment capability, unstated data security classification, unstated convergence/SLA target, missing application matrix, or unknown provider coverage/feature support.\",\n  \"observable\": \"Conditionally observable. The engine HAS strong current-state device evidence (inventory, utilization via platform_health where collected, topology) — so it can answer 'what is' — but it has NO requirements/SLA/application-matrix model, so it must surface evidence and explicitly flag the requirement gaps rather than inventing them. This principle is itself the engine's coverage-honest operating discipline: it reports what it observed and names what it could not.\",\n  \"recommended_action\": \"Before committing a design choice, confirm the specific decision-driving inputs (existing/partner equipment capability, data security level, convergence/SLA target, application matrix, provider coverage/feature support); design to stated requirements, not reflexive best practice, and never re-ask facts already given.\",\n  \"alternatives\": \"Assume sensible defaults and proceed (fast, risks redesign); capture requirements iteratively where a full up-front gather is infeasible.\",\n  \"citation\": \"CCDE MilkaTurka & Ornio scenarios (requirements-gathering, no-assumptions); CCDE Scenario 1/2 (SLA + app matrix + device utilization first)\"\n },\n {\n  \"id\": \"scenario-build-before-break-phased-cutover\",\n  \"title\": \"Migrate through a transit/bridge site with build-before-break, parallel-running old and new until validated\",\n  \"domain\": \"scenario-pattern\",\n  \"priority\": \"High\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"Sequence a WAN/transport cutover to never drop connectivity: pick a transit site to bridge migrated and not-yet-migrated sites, stand up the new circuits and routing FIRST, shift traffic by metric so new is preferred while old still backs it, validate (QoS + monitoring), then remove the old path last (remote site before the transit site). Keep every step reversible until validated; a flag-day cut is cheaper but risks an outage with no rollback. Migrating two MPLS/IGP domains is similarly best done by keeping them separate (Inter-AS + BGP-LU) or scheduling re-addressing rather than flattening into one IGP.\",\n  \"tradeoffs\": \"Zero-downtime, reversible migration (parallel run, ordered teardown) vs a dual-transport cost window and added coordination; a flag-day is fast/cheap but outage-prone with no easy rollback.\",\n  \"trigger\": \"A migration plan that removes the old circuit before the new path is established and validated, lacks a transit/bridge site for mixed old/new, or has no metric-based preference for rollback.\",\n  \"observable\": \"Partly observable as a verification capability, not as plan authorship. The engine validates a cutover after the fact via --compare OLD NEW snapshot diff (and --trend), so it can confirm build-before-break worked (pre/post reachability/health diff) and detect regressions; it does not author the step ordering. So the migration-validation half is engine-actionable; the sequencing recommendation is methodology.\",\n  \"recommended_action\": \"Choose a transit site; establish new circuits + routing at transit then remote; set metrics so new is preferred while old remains fallback; enable QoS + monitoring; remove old circuits remote-first/transit-last; keep every step reversible and validate with a pre/post snapshot diff.\",\n  \"alternatives\": \"Flag-day cutover (fast, cheap, outage-prone); for MPLS-domain merges use Inter-AS Option B/C + BGP-LU or re-address rather than merging IGPs.\",\n  \"citation\": \"CCDE Ornio scenario (MPLS L3VPN migration step ordering); engine --compare/--trend snapshot diff\"\n },\n {\n  \"id\": \"scenario-match-redundancy-to-convergence-requirement\",\n  \"title\": \"Size redundancy (second path, BFD, fast timers) to the application's actual convergence requirement, not reflexive best practice\",\n  \"domain\": \"scenario-pattern\",\n  \"priority\": \"High\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"Refuse to add resilience the business did not ask for. When the stated recovery tolerance is generous (e.g. minutes), a second path per site, BFD, or sub-second detection is pure cost and complexity that buys nothing — and it multiplies hugely across a large site count. State the convergence target explicitly and design to it: single path / default timers for loose targets, dual-homing + BFD + feasible-successor only for genuinely tight (sub-second/second) recovery needs.\",\n  \"tradeoffs\": \"Fast convergence/extra resilience vs doubled tunnel/adjacency count and operational load; protecting a rare failure mode at every site rarely justifies the fleet-wide multiplication when convergence is non-critical.\",\n  \"trigger\": \"Dual/parallel paths, BFD, or aggressive timers proposed or in place for an application whose stated convergence tolerance is loose, especially where each extra path multiplies across a large site count.\",\n  \"observable\": \"Conditionally observable. The engine measures the redundancy posture (dual-homing %, SPOF, FHRP) but cannot judge whether it is over- or under-sized without the per-app convergence target, which it does not hold. On the [HISTORY-REDACTED] fleet the detected condition is UNDER-redundancy (FHRP absent), so the engine surfaces the gap as evidence and leaves the right-sizing to the requirement.\",\n  \"recommended_action\": \"Provision a single path/default timers for loose convergence targets; reserve dual-homing/BFD/feasible-successor/aggressive timers for apps with tight recovery needs; record the convergence target as the design basis.\",\n  \"alternatives\": \"Dual tunnels + BFD everywhere (textbook HA, unjustified at scale); single path with monitoring only.\",\n  \"citation\": \"CCDE MilkaTurka scenario (one-vs-two tunnels per store; BFD/feasible-successor under loose convergence)\"\n },\n {\n  \"id\": \"security-defense-in-depth-segmentation\",\n  \"title\": \"Defense-in-depth via modular, layered security zones — not perimeter-only\",\n  \"domain\": \"security\",\n  \"priority\": \"Critical\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"A single hardened perimeter fails the moment it is breached, so layer independent controls across modules so compromise of one does not yield the whole network, using MULTIPLE LAYERS and DIFFERENT TECHNOLOGIES (not just different vendors). Modularize into security zones (Internet edge, DMZ, server farm, campus/user, management) so a zone breach is contained, and drive security investment from asset value and risk (spend less than the cost of the damage prevented). Put the NMS/management in its own zone. Use Private VLANs to isolate hosts sharing a subnet that must not talk to each other (lateral-movement containment) without burning a subnet per host.\",\n  \"tradeoffs\": \"Security/containment vs operational simplicity and cost — more zones/layers mean more devices and policy surface; uniform blanket controls vs risk-prioritized ones; macro- vs micro-segmentation.\",\n  \"trigger\": \"Flat single-perimeter design (one edge firewall, no internal segmentation/zones), servers + management + users sharing one broadcast domain, or many hosts in one subnet with no intra-subnet isolation.\",\n  \"observable\": \"Partially observable. The segmentation/security-posture axis and vlan_inventory flag flat/large L2 domains and the absence of segmentation, and the engine sees whether management shares a user VLAN where collected. It does not model security zones or firewall placement, and Private-VLAN config is not specifically parsed — so 'flat, unsegmented' is detectable as a shape, but zone-completeness is not.\",\n  \"recommended_action\": \"Segment into security modules/zones with layered per-module controls (edge firewall + iACL + IPS + L2 access protections + AAA), put the NMS in its own zone, run an asset/risk analysis to size controls to asset value, and use Private VLANs for intra-subnet isolation.\",\n  \"alternatives\": \"Single stateful perimeter (cheaper, weaker once breached); host-based firewalls/service mesh microsegmentation; physical vs virtual (VRF/context) zone separation.\",\n  \"citation\": \"CCDE Session 13 (defense-in-depth, zones, risk-driven controls, Private VLAN)\"\n },\n {\n  \"id\": \"security-aaa-routing-auth-antispoof\",\n  \"title\": \"Centralize AAA, authenticate routing adjacencies, and anti-spoof at the edge (uRPF/BCP38)\",\n  \"domain\": \"security\",\n  \"priority\": \"High\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"Local/shared accounts give no accountability or per-command authorization — centralize AAA (TACACS+ for admin command-authorization/accounting, RADIUS for 802.1X) with role-based CLI and least privilege, keeping a guarded local fallback and OOB path. Authenticate IGP/BGP/FHRP adjacencies and bound BGP (prefix filters, max-prefix, GTSM, neighbour-change logging) so the control plane cannot be poisoned. Filter spoofed/bogon sources as close to the edge as possible (BCP38) with uRPF (loose on asymmetric/multihomed edges, strict where symmetric) and infrastructure ACLs that deny inbound traffic to infrastructure/loopback space.\",\n  \"tradeoffs\": \"Accountability, routing integrity and spoof-prevention vs AAA-server dependency, key-management overhead, and uRPF strict-mode breaking asymmetric flows; security wins at an Internet edge.\",\n  \"trigger\": \"Shared/local credentials with no TACACS+/RADIUS and no command authorization, routing adjacencies without authentication, eBGP with no prefix/max-prefix/GTSM, no uRPF/anti-bogon filtering, or infrastructure/loopback space reachable from outside.\",\n  \"observable\": \"Partially observable. The CIS/config-security audit can detect AAA/TACACS configuration, Telnet-vs-SSH, and some management-surface items on collected devices. Routing-protocol authentication, uRPF, GTSM, prefix-filters and infrastructure ACLs are largely NOT parsed today — so AAA presence is detectable but the routing/anti-spoof specifics are mostly outside the evidence set.\",\n  \"recommended_action\": \"Deploy AAA (TACACS+ admin command-authz/accounting + RADIUS access) with RBAC/least-privilege and a guarded fallback; authenticate routing adjacencies and constrain BGP; implement BCP38 (uRPF + anti-bogon/RFC1918 ACLs) and infrastructure ACLs at the edge.\",\n  \"alternatives\": \"RADIUS where TACACS+ is unavailable; MD5 vs stronger keychains; static routing on stubs to remove the dynamic attack surface; RPKI as the modern origin-validation successor.\",\n  \"citation\": \"CCDE Session 13 (AAA, routing auth, BCP38, iACLs); engine CIS axis (AAA/SSH detection)\"\n },\n {\n  \"id\": \"security-device-hardening-baseline\",\n  \"title\": \"Harden the device baseline: disable unneeded services, lock management, protect the control plane\",\n  \"domain\": \"security\",\n  \"priority\": \"High\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"Every enabled-but-unused service (CDP everywhere, proxy-ARP, IP redirects, small services, HTTP server) and every weak management path is attack surface. Apply a hardening baseline — disable unnecessary services, SSH-only with VTY source-restricted ACLs, service-password-encryption + enable secret, banners, session timeouts — and protect the control plane with CoPP and ICMP/feature rate-limiting so a punt flood cannot starve the CPU and make the device unmanageable.\",\n  \"tradeoffs\": \"Reduced attack surface and control-plane survivability vs operational convenience (CDP aids discovery, proxy-ARP eases addressing) and the risk of dropping legitimate control traffic if CoPP policers are mistuned.\",\n  \"trigger\": \"Devices with default-on services exposed (CDP/proxy-ARP/redirects/small services/HTTP), Telnet/cleartext management, no password encryption, no VTY ACL, no CoPP, or control-plane CPU spikes under load.\",\n  \"observable\": \"Directly observable for the config-hygiene dimension. The config-security/CIS axis (config-security-auditor) screens device hardening against a CIS-style baseline from collected run-configs and folds findings into the punchlist (with CIS-twin de-duplication). CoPP/ICMP-rate-limit presence detection depends on how deeply the audit parses those specific stanzas — service-disable and management-surface checks are the strongest; CoPP is partial.\",\n  \"recommended_action\": \"Apply the hardening baseline (disable unneeded services, SSH-only + VTY ACL, password encryption, banners, timeouts, AAA for admin) and deploy CoPP + ICMP/feature rate-limits.\",\n  \"alternatives\": \"Per-platform hardening templates vs a centrally-pushed CIS profile; keep CDP/LLDP on infrastructure-facing links only; hardware-policed vs software-only CoPP.\",\n  \"citation\": \"CCDE Session 13 (device hardening, control plane); engine config-security/CIS axis\"\n },\n {\n  \"id\": \"security-l2-access-edge-suite\",\n  \"title\": \"Harden the L2 access edge: port-security, DHCP snooping, DAI, IP Source Guard, storm-control, 802.1X\",\n  \"domain\": \"security\",\n  \"priority\": \"High\",\n  \"engine_actionable\": true,\n  \"design_intent\": \"The user access edge is where L2 attacks start — CAM-overflow turns a switch into a hub, rogue DHCP/ARP enable man-in-the-middle, broadcast storms saturate the domain. Block them at ingress with the standard suite: Port Security, DHCP Snooping (trusted uplinks), Dynamic ARP Inspection, IP Source Guard, inbound storm-control, and 802.1X/NAC to make port access an identity decision (RADIUS-backed, with MAB/guest fallback) rather than physical-presence trust. For IPv6 add the analogous RA Guard / DHCPv6 Guard / SEND.\",\n  \"tradeoffs\": \"L2 integrity and broadcast-domain stability vs configuration/operational burden and onboarding friction (snooping trust ports, DAI bindings, port-security limits, 802.1X supplicant coverage and fail-open/closed handling).\",\n  \"trigger\": \"Access ports with no port-security/DHCP-snooping/DAI/IP-Source-Guard/storm-control, flat access VLANs where rogue DHCP or ARP spoofing is possible, no 802.1X, or IPv6 access ports with no RA Guard/DHCPv6 Guard.\",\n  \"observable\": \"Partially observable. The CIS/config-security audit can detect several of these stanzas (port-security, DHCP snooping, storm-control, DAI, 802.1X) on collected access switches from run-config, folding gaps into the punchlist. Coverage depends on which checks are implemented; IPv6 first-hop-security (RA/DHCPv6 Guard) detection is weaker. So it is engine-actionable but not exhaustive.\",\n  \"recommended_action\": \"Standardize the access-edge bundle (port-security, DHCP snooping + IP Source Guard + DAI with trusted uplinks, storm-control, 802.1X with MAB/guest fallback); add RA Guard/DHCPv6 Guard for IPv6.\",\n  \"alternatives\": \"Private VLANs/VLAN ACLs for isolation; MAB where 802.1X is infeasible; monitor-mode/open-auth phased 802.1X rollout; static port-to-MAC for fixed assets.\",\n  \"citation\": \"CCDE Session 13/16 (L2 security suite, 802.1X/NAC); CCDE Session 15 (IPv6 RA/DHCPv6 Guard); engine CIS axis\"\n },\n {\n  \"id\": \"bgp-dual-isp-multihoming\",\n  \"title\": \"Use BGP for a multihomed Internet edge with two providers\",\n  \"domain\": \"bgp\",\n  \"priority\": \"High\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"When an enterprise homes to two ISPs, BGP is the only control plane that applies per-provider inbound/outbound policy and survives a provider failure deterministically. Static defaults/IGP cannot express path policy or fail over cleanly. For true HA use dual CPE to two different ISPs, advertise only enterprise (non-transit) prefixes, and pair eBGP with BFD for sub-second peer-failure detection.\",\n  \"tradeoffs\": \"Policy control, deterministic failover and provider independence vs needing an own ASN + provider-independent space and the operational weight of BGP (and possibly partial/full tables). BGP gives load-SHARING, not true load-balancing.\",\n  \"trigger\": \"Internet edge homed to two ISPs (or single CE/static default) with no BGP — failover/policy via static routes or a single default, no inbound/outbound TE control.\",\n  \"observable\": \"Partially observable. The engine parses BGP summary state, so it can see whether BGP runs and how many neighbours/peers exist at an edge device. It does not model 'this is the Internet edge' or count distinct ISPs, advertised prefixes, or inbound/outbound policy — so 'dual-ISP but no BGP' is only weakly inferable from device role + neighbour count.\",\n  \"recommended_action\": \"Run eBGP to each ISP, obtain a public ASN + PI block, advertise only enterprise prefixes outbound and filter inbound; use dual CPE to two ISPs for HA and BFD for fast peer detection.\",\n  \"alternatives\": \"Single CPE dual-homed (no router redundancy); dual CPE to one ISP (no provider redundancy); default-route-only static multihoming (weaker on policy/resilience).\",\n  \"citation\": \"CCDE Session 5/6 (BGP multihoming); Cisco BGP load-sharing doc; engine parse_bgp_summary\"\n },\n {\n  \"id\": \"bgp-edge-security-and-ddos-prearm\",\n  \"title\": \"Apply an eBGP edge hardening baseline and pre-arm RTBH/FlowSpec for DDoS\",\n  \"domain\": \"bgp\",\n  \"priority\": \"High\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"An unauthenticated, unfiltered eBGP edge is exposed to spoofed peers, TTL attacks, AS-path forgery and acceptance of bogon/RFC1918/hijacked prefixes. Apply session auth (MD5/TCP-AO), GTSM (TTL=255) on directly-connected eBGP, First-AS validation, max-prefix limits and inbound martian/RFC1918 filtering (origin validation/RPKI for hijacks). Separately pre-stage RTBH (Null0 + no-export, dest- and source-based) and BGP FlowSpec/scrubbing so volumetric and targeted DDoS can be dropped network-wide in seconds. Note MD5 is route-integrity, NOT DDoS protection — and can amplify CPU under a flood.\",\n  \"tradeoffs\": \"Control-plane protection and fast mitigation vs filter maintenance and (for dest-RTBH) collateral loss of the victim /32; source-RTBH and FlowSpec reduce collateral at more complexity. Mitigation speed vs precision/blast-radius.\",\n  \"trigger\": \"eBGP peering with no MD5/GTSM/First-AS/martian filtering, and an Internet edge with no automated DDoS response (manual ACLs only, no RTBH/FlowSpec/scrubbing).\",\n  \"observable\": \"NOT observable. The engine does not parse BGP session auth, GTSM, prefix-filters/max-prefix, RTBH or FlowSpec configuration. The general device-hardening/CIS axis covers box hygiene, but BGP-edge security specifics are outside the evidence set.\",\n  \"recommended_action\": \"Enable session auth, GTSM, First-AS, max-prefix and inbound bogon/RFC1918 filters (+RPKI ROV); pre-configure dest/source RTBH via BGP and FlowSpec/scrubbing; never count MD5 as DDoS defense.\",\n  \"alternatives\": \"uRPF + ACL anti-spoof at the edge; upstream/cloud scrubbing; prefix-list-only filtering where RPKI is unsupported.\",\n  \"citation\": \"CCDE Session 6 (BGP security, RTBH, FlowSpec); CCDE scenario (MD5-vs-GTSM, CoPP/uRPF/GTSM for DDoS)\"\n },\n {\n  \"id\": \"bgp-enterprise-core-model\",\n  \"title\": \"Choose the enterprise-core BGP model (iBGP / eBGP / hybrid) by scale and policy needs\",\n  \"domain\": \"bgp\",\n  \"priority\": \"High\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"A large multi-region enterprise carrying huge prefix counts must decide how BGP rides the core: an iBGP core over a common IGP yields optimal IGP-metric path selection; an eBGP core gives strong policy boundaries but risks sub-optimal paths (no shared IGP metric); the hybrid (iBGP within regions, eBGP+IGP across the core) combines optimal intra-region routing with inter-region policy control and is best for most large cores. Use BGP in the core when route scale and explicit policy control — not fast IGP convergence — are the actual drivers.\",\n  \"tradeoffs\": \"Optimal IGP-driven paths (iBGP) vs strong inter-region policy/modularity (eBGP) vs the hybrid's full control at apparent complexity; simplicity/optimal-routing vs policy-isolation/scale. BGP is overkill when the real problem is just fault isolation.\",\n  \"trigger\": \"Multi-region enterprise with large prefix counts and an ad-hoc or IGP-only core, causing either no policy isolation between regions or sub-optimal inter-region paths.\",\n  \"observable\": \"Weakly observable. The engine sees whether BGP runs and the IGP inventory, so 'IGP-only core' vs 'BGP present' is detectable per device, but it does not model regions, prefix scale, or policy intent, so the model recommendation cannot be derived.\",\n  \"recommended_action\": \"Adopt the hybrid for most large multi-region cores (iBGP per region + eBGP/IGP between); reserve pure iBGP-core for optimality-first and pure eBGP-core for policy-first designs; use RRs for iBGP scale.\",\n  \"alternatives\": \"iBGP full-mesh/RR core; eBGP-only core (policy, sub-optimal); stay IGP-only where scale/policy don't demand BGP.\",\n  \"citation\": \"CCDE Session 5/6 (enterprise BGP options); CCDE scenario (BGP-core for scale + control)\"\n },\n {\n  \"id\": \"bgp-pic-and-fast-detection\",\n  \"title\": \"Enable BGP PIC plus BFD and next-hop tracking for table-size-independent fast convergence\",\n  \"domain\": \"bgp\",\n  \"priority\": \"High\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"Without PIC, converging to a backup egress rewrites every affected prefix, so convergence scales with table size — fatal for full Internet/VPN tables. PIC uses hierarchical CEF so one next-hop pointer update flips all prefixes to a pre-computed backup. Pair it with BFD (not aggressive hold timers) for sub-second detection and Next-Hop-Tracking (loopback/multihop sessions) / Fast-External-Failover (directly-connected eBGP) so reaction is event-driven.\",\n  \"tradeoffs\": \"Near-constant reconvergence and fast detection vs pre-computing/holding a backup (extra FIB/RIB state), platform/hierarchical-CEF dependency, and instability if the underlying link flaps (so guard against flap).\",\n  \"trigger\": \"Edge/core carrying a large BGP table with no pre-installed backup and only default hold timers, missing sub-50ms SLAs on next-hop/link failure.\",\n  \"observable\": \"NOT observable. The engine does not extract BGP PIC, BFD-for-BGP, NHT, or Fast-External-Failover configuration; only BGP neighbour up/down state is parsed. Outside the current evidence vocabulary.\",\n  \"recommended_action\": \"Enable BGP PIC (core + PIC-Edge backup) backed by hierarchical CEF; run BFD on BGP next-hops; enable Next-Hop-Tracking on loopback/multihop sessions and Fast-External-Failover on directly-connected eBGP.\",\n  \"alternatives\": \"Add-Path/Best-External to supply the alternate; IGP-driven next-hop withdrawal; aggressive keepalive/hold (CPU-costly, less reliable).\",\n  \"citation\": \"CCDE Session 5/6 (BGP PIC, BFD, NHT/FEF)\"\n },\n {\n  \"id\": \"ibgp-full-mesh-to-route-reflector\",\n  \"title\": \"Replace iBGP full mesh with redundant route reflectors as the AS scales, and restore lost path diversity\",\n  \"domain\": \"bgp\",\n  \"priority\": \"High\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"iBGP needs a logical full mesh (n(n-1)/2 sessions) because iBGP-learned routes are not re-advertised to other iBGP peers; beyond a few dozen speakers this is unmanageable. A route-reflector hierarchy restores scale (loop-free via Originator-ID/Cluster-list), deployed as dual RRs per AFI/function with the RR logical topology congruent to the physical. Because an RR reflects only its best path, re-add diversity (Add-Path, Best-External, Shadow-RR/Session, ORR, unique-RD-per-PE) so fast reroute (BGP PIC) and optimal egress still work.\",\n  \"tradeoffs\": \"Massive session/config reduction and a removed control-plane SPOF vs loss of full-path visibility (RR hides alternates -> slower convergence, sub-optimal egress) and more RR state/memory when diversity is re-added.\",\n  \"trigger\": \"Hundreds of iBGP routers configured as a (near) full mesh; or a route-reflected design where clients see only one exit and converge slowly.\",\n  \"observable\": \"NOT observable in a meaningful sense. The engine parses BGP summary state per device but does not reconstruct the iBGP session graph, RR client/non-client roles, or path-diversity features. It cannot tell a full mesh from an RR design from the current evidence. (And the [HISTORY-REDACTED] fleet is enterprise L2/L3 access, not an iBGP-core SP context.)\",\n  \"recommended_action\": \"Introduce dual RRs per AFI sized in clusters, migrate speakers to clients, keep the RR topology congruent to physical, and re-add path diversity (Add-Path/Best-External/ORR/unique-RD) plus BGP PIC for sub-second reconvergence.\",\n  \"alternatives\": \"Confederation (sub-AS, better for BU/acquisition boundaries, more complex); keep full mesh at small scale.\",\n  \"citation\": \"CCDE Session 5/6 (RR rules, diversity, PIC); CCDE scenario (full-mesh iBGP -> RR)\"\n },\n {\n  \"id\": \"bgp-inbound-vs-outbound-attribute\",\n  \"title\": \"Pick the BGP attribute by traffic direction and prefer portable over proprietary/local\",\n  \"domain\": \"bgp\",\n  \"priority\": \"Medium\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"Map the knob to the goal: influence INBOUND (download) traffic with MED / AS-path-prepend / more-specifics / communities the upstream honours; influence OUTBOUND with LOCAL_PREF (preferred over Weight because it is AS-wide and standards-based and survives adding a second BGP router). Conflating the two yields asymmetric or uncontrolled routing. For true HA acquire an own ASN + PI block with diverse links.\",\n  \"tradeoffs\": \"Deterministic directional control and portability vs quick router-local fixes (Weight dies when a second BGP router is added); inbound is only an influence on the upstream's decision, outbound is fully yours. Two circuits to one PE will not load-share inbound regardless of attributes — split PEs or use loopback-sourced peering.\",\n  \"trigger\": \"A link-utilization/steering goal where the wrong-direction attribute is chosen, Weight used where a second router will be added, or two circuits to a single SP PE with one link idle.\",\n  \"observable\": \"NOT observable. The engine does not parse BGP policy (local-pref, MED, prepend, communities) or model multihoming intent/utilization. Outside the evidence set.\",\n  \"recommended_action\": \"Inbound: MED (single-homed)/prepend/communities; outbound: LOCAL_PREF over Weight; for HA get an own ASN + PI block; for dual circuits to one SP, terminate on different PEs or peer from a loopback reachable via two static routes.\",\n  \"alternatives\": \"ACL-based steering (crude); single provider (no resilience); NAT-based multihoming without BGP (limited control).\",\n  \"citation\": \"CCDE scenario (inbound vs outbound, LOCAL_PREF vs Weight, hot-potato/idle-uplink)\"\n },\n {\n  \"id\": \"bgp-internet-edge-table-size\",\n  \"title\": \"Right-size the Internet-edge BGP table: default vs default+partial vs full\",\n  \"domain\": \"bgp\",\n  \"priority\": \"Medium\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"How much Internet routing an edge needs is a deliberate choice driven by whether outbound path optimization is required and how much router memory/FIB is available. Taking a full table everywhere wastes resources when a default would meet the requirement.\",\n  \"tradeoffs\": \"Optimal outbound path selection / fine-grained TE (full/partial) vs router memory, FIB scale and convergence cost; a default is cheapest but yields no path intelligence.\",\n  \"trigger\": \"Internet edge taking a full BGP table on undersized hardware, or a default-only edge where the business needs per-destination outbound optimization across two providers.\",\n  \"observable\": \"Weakly observable. The engine sees BGP neighbour state and platform_health (CPU/mem) where collected, so an oversized table on a memory-pressured box is partially inferable, but it does not count received prefixes or model the path-selection requirement.\",\n  \"recommended_action\": \"Choose the smallest table that meets the goal: default-only for simple/single-exit, default + partial for moderate optimization, full only where outbound TE is genuinely required and the platform can hold it.\",\n  \"alternatives\": \"Conditional default origination; accept only a provider's customer cone (partial); full tables with aggressive inbound filtering.\",\n  \"citation\": \"CCDE Session 5 (Internet-edge table sizing)\"\n },\n {\n  \"id\": \"bgp-pe-ce-and-loop-prevention\",\n  \"title\": \"Use BGP as PE-CE for self-service TE, and solve same-AS/multihoming loops with AS-override + SoO\",\n  \"domain\": \"bgp\",\n  \"priority\": \"Medium\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"BGP is the universally-supported PE-CE protocol and the only one letting the customer shape VPN traffic without per-change SP coordination (vendor-neutral, policy-rich). At many-site scale use one customer AS everywhere and have the SP apply AS-override (keeping the fix provider-side); for multihomed sites add Site-of-Origin so a PE refuses a route back to the site that sourced it, since AS-override/Allow-AS-in defeat normal AS-path loop prevention.\",\n  \"tradeoffs\": \"Vendor-neutral self-service TE and AS-scalability vs the loop hazard AS-override reintroduces at dual-homed sites (needs SoO) and the loss of per-site AS-path visibility; EIGRP PE-CE is simpler but Cisco-only and weaker for TE over a VPN.\",\n  \"trigger\": \"A provider-VPN PE-CE choice wanting vendor neutrality/self-TE where a Cisco-only IGP is proposed; many-site VPN assigning a unique AS per site (private-AS exhaustion); or multihomed VPN/PE-CE sites with AS-override and no SoO.\",\n  \"observable\": \"NOT observable. SP/MPLS-VPN PE-CE constructs (AS-override, SoO, RDs) and per-site ASN assignment are outside what the engine parses; the [HISTORY-REDACTED] fleet is an enterprise campus, not an SP PE-CE estate.\",\n  \"recommended_action\": \"Run BGP PE-CE for self-service TE; use one customer AS everywhere with provider AS-override; assign a unique SoO per multihomed site and unique RDs for path diversity.\",\n  \"alternatives\": \"Unique AS per site (preserves visibility, exhausts range); per-site AS-path filtering; EIGRP PE-CE where TE/neutrality are not required.\",\n  \"citation\": \"CCDE Session 6 (SoO, AS-override); CCDE scenarios (BGP PE-CE, same-AS-everywhere)\"\n },\n {\n  \"id\": \"igp-authentication-and-overload-hygiene\",\n  \"title\": \"Authenticate IGP adjacencies and use the overload bit / startup hygiene on restart\",\n  \"domain\": \"igp\",\n  \"priority\": \"High\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"Unauthenticated IGP adjacencies let a rogue or misconfigured device inject routes and disrupt the core, so enable strong neighbour authentication (HMAC-MD5/SHA-256). On restart, set the IS-IS overload bit (or OSPF max-metric / BGP wait-for-BGP) so a still-converging node stays out of the transit path until its database and BGP next-hops are ready, preventing transient black-holing.\",\n  \"tradeoffs\": \"Security/stability vs key-management and a small restart-procedure step; authentication and overload-bit discipline harden the control plane and prevent transient blackholes.\",\n  \"trigger\": \"IGP adjacencies with no authentication (or weak MD5), or routers used for transit immediately on reboot before convergence.\",\n  \"observable\": \"NOT observable. The engine does not parse routing-protocol authentication config, key-chains, the overload bit, or max-metric-on-startup. (Adjacent device-hardening config such as service-password-encryption/SSH is covered by the security/CIS axis, but per-protocol auth is not extracted.)\",\n  \"recommended_action\": \"Enable IGP neighbour authentication everywhere (HMAC-MD5 IS-IS, SHA-256 EIGRP/keychains); set the IS-IS overload bit (or wait-for-BGP) on restarting/maintenance nodes.\",\n  \"alternatives\": \"Graceful Restart to ride through recovery instead of overloading; infrastructure ACLs/segmentation where per-protocol auth is unavailable.\",\n  \"citation\": \"CCDE Session 1/3 (IS-IS HMAC-MD5/overload bit, EIGRP SHA-256)\"\n },\n {\n  \"id\": \"igp-hierarchy-maps-to-tiers\",\n  \"title\": \"Map the IGP area/level hierarchy onto the core/distribution/access tiers\",\n  \"domain\": \"igp\",\n  \"priority\": \"High\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"Align IGP areas/levels with the physical tier model so fault domains, summarization points and the topology database all break on the same boundaries (IS-IS core=L2, distribution=L1/L2, access=L1; OSPF backbone area 0 + ABR on the core/distribution edge, ABR placed at the transit/DC boundary not the spoke). Keep areas sized (legacy guideline <~50 routers/area) for a stable SPF domain.\",\n  \"tradeoffs\": \"Optimal routing/one flat DB vs fault-isolation/scale — more areas shrink each SPF domain and contain instability at the cost of inter-area summarization, possible sub-optimal paths and dual-DB border nodes.\",\n  \"trigger\": \"Single-area/single-level IGP spanning the whole estate (one large flooding domain), area boundaries not aligned to tiers, or ABRs placed on access switches.\",\n  \"observable\": \"Partially observable. The protocol inventory can show whether OSPF runs and (from parsed neighbour/area context where present) hint at single-area, but the engine does not robustly extract per-router area membership / level / ABR placement, and tier/role inference is limited. So 'flat single-area IGP at scale' is a weak/heuristic detection, not a firm one.\",\n  \"recommended_action\": \"Introduce a hierarchical IGP: backbone in the core, area/level borders on the distribution-to-core edge, access in stub areas/IS-IS L1; place ABRs on core or DC-border nodes so the backbone stays small.\",\n  \"alternatives\": \"Two-tier collapsed-core hierarchy for smaller sites; single area where the router count is well under guideline and growth is bounded.\",\n  \"citation\": \"CCDE Session 1/2 (IS-IS 3-layer, OSPF ABR placement); CCDE scenario (ABR at DC border)\"\n },\n {\n  \"id\": \"igp-fast-convergence-bfd-lfa\",\n  \"title\": \"Layer BFD detection with pre-computed LFA/TI-LFA backups, matched to topology\",\n  \"domain\": \"igp\",\n  \"priority\": \"Medium\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"Real-time/SLA traffic needs sub-50ms recovery. Pair fast detection (BFD) with a pre-installed data-plane backup: basic LFA covers triangles, Remote-LFA covers squares, TI-LFA (with Segment Routing) guarantees coverage including rings and avoids micro-loops; classic/Directed LFA cannot protect ring topologies. EIGRP's feasible-successor is the distance-vector analog of a pre-computed backup; engineer topology/metrics so critical prefixes always have one and bound query scope with stubs/summaries to prevent Stuck-In-Active.\",\n  \"tradeoffs\": \"Fast-convergence/coverage vs complexity/stability — pre-computed backups give near-instant recovery; basic LFA has coverage gaps (rings), RLFA/TI-LFA add tunnel/SR machinery; aggressive BFD/timers risk flap churn so pair with dampening.\",\n  \"trigger\": \"Link-state/EIGRP core carrying real-time traffic with only native reconvergence (no BFD, no LFA/TI-LFA/feasible-successor), square/ring topologies where basic LFA leaves prefixes unprotected, or recurring EIGRP SIA on spokes.\",\n  \"observable\": \"NOT observable. The engine does not extract BFD enablement, LFA/TI-LFA/FRR configuration, EIGRP feasible-successor presence, stub configuration, or SIA history. It can reconstruct topology shape (ring/triangle) partially, but the convergence-mechanism facts are outside the current evidence set.\",\n  \"recommended_action\": \"Enable BFD for sub-second detection, then select FRR by topology (TI-LFA as the SR-era default incl. rings; classic LFA only where a loop-free alternate is guaranteed); engineer EIGRP feasible-successors and mark spokes as stubs to contain queries.\",\n  \"alternatives\": \"Tuned SPF/IGP fast-hellos where LFA coverage is incomplete; engineer topology toward triangles so basic LFA suffices; G.8032 on L2 access rings.\",\n  \"citation\": \"CCDE Session 1/2/3 (LFA/RLFA/TI-LFA, feasible-successor, SIA/stub); CCDE scenario (Directed-LFA fails on rings -> TI-LFA)\"\n },\n {\n  \"id\": \"igp-graceful-restart-nsf-nsr\",\n  \"title\": \"Use NSF/SSO and NSR/GR for control-plane HA during supervisor switchover and upgrades\",\n  \"domain\": \"igp\",\n  \"priority\": \"Medium\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"On redundant-supervisor platforms NSF/SSO keeps CEF forwarding through a switchover or ISSU while the control plane recovers, and Graceful Restart routes through (not around) the temporary failure provided neighbours support it; NSR synchronizes the control plane with no neighbour dependency. Together they enable near-zero-downtime upgrades — the in-box complement to triangles/dual-homing.\",\n  \"tradeoffs\": \"HA vs dependencies — GR depends on neighbour capability and the node returning before the hold timer and can delay true reconvergence on a real failure; NSR avoids the neighbour dependency but needs dual-control-plane hardware.\",\n  \"trigger\": \"Dual-supervisor/redundant-RP core or distribution platforms without NSF/SSO or NSR/GR, or planned ISSU that would otherwise drop forwarding, with edge neighbours of unknown GR capability.\",\n  \"observable\": \"NOT observable. The engine does not extract NSF/SSO/NSR/GR configuration or per-neighbour GR capability, and single-vs-dual-supervisor detection depends on hardware-inventory detail that is only partially collected. Outside the reliably-observable set.\",\n  \"recommended_action\": \"Enable NSF/SSO (with CEF) and NSR/GR for the IGP/BGP/LDP on redundant-control-plane nodes; verify adjacent-router GR support and hold-timer compatibility before enabling GR at the edge.\",\n  \"alternatives\": \"Rely on fast IGP reconvergence (BFD + tuned timers) where neighbours are not GR-capable; box-level (dual-device) redundancy instead of in-box.\",\n  \"citation\": \"CCDE Session 2/3 (NSF/GR/NSR prerequisites)\"\n },\n {\n  \"id\": \"igp-stub-area-types\",\n  \"title\": \"Use stub / totally-stubby / NSSA area types to shrink edge databases, and verify default-route reachability\",\n  \"domain\": \"igp\",\n  \"priority\": \"Medium\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"Because every router in an OSPF area holds an identical database, filtering happens only at the area edge. Converting edge areas to stub/totally-stubby replaces a flood of external/inter-area LSAs with a default, cutting memory/CPU/convergence on access hardware; NSSA keeps that benefit while allowing a local external injection (e.g. an ISP link). Pick the most restrictive type the requirements allow, then relax exactly as far as optimal-routing or local-external need demands — and confirm the default still propagates (NSSA does not originate a default by default).\",\n  \"tradeoffs\": \"Resource savings/stability vs routing granularity — a default-only edge is lean but loses per-destination exit choice; over-stubbing causes sub-optimal paths or black-holes (notably losing Internet access if the NSSA default is not originated).\",\n  \"trigger\": \"Edge/access OSPF areas carrying full external (LSA-5) and inter-area (LSA-3) tables, low-spec access hardware straining on LSA volume, or a freshly-converted NSSA edge that can reach internal apps but lost Internet/default.\",\n  \"observable\": \"NOT observable. The engine does not parse OSPF area-type, LSA composition, or default-route origination; the protocol layer reads adjacency/state, not stub-flags. This is a config-truth gap outside the current evidence vocabulary.\",\n  \"recommended_action\": \"Make leaf areas stub/totally-stubby (ABR injects only a default); use NSSA where the area must originate externals; explicitly originate the default from the ABR/ASBR and verify reachability after any area-type change.\",\n  \"alternatives\": \"LSA Type-3 filtering / area-range distance-infinity for selective pruning; keep a normal area where per-destination external choice is required.\",\n  \"citation\": \"CCDE Session 2/4 (stub/NSSA); CCDE scenario (Totally-NSSA then NSSA + Type-3 leak; NSSA default-route break)\"\n },\n {\n  \"id\": \"ipv6-dual-stack-phased-and-6vpe\",\n  \"title\": \"Introduce IPv6 by phased dual-stack from a contained module, or carry it at the edge over the existing core (6PE/6VPE)\",\n  \"domain\": \"ipv6\",\n  \"priority\": \"Medium\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"Dual-stack is the safest IPv6 introduction because every node keeps working on IPv4 while IPv6 is validated; start from one contained module (e.g. the Internet edge) to bound blast radius, following assess->plan->pilot->wide, and reserve tunnels (GRE/6rd) only for transit over non-IPv6 segments — not as a permanent solution. Crucially, an IPv4/MPLS core need NOT be dual-stacked to deliver IPv6 services: 6PE carries global IPv6 and 6VPE carries IPv6 L3VPN over the existing IPv4 LSPs in MP-BGP (VPNv6), so IPv6 is introduced incrementally per-PE with little/no core change. Avoid a big-bang core cutover. Provide IPv6 first-hop gateway redundancy via multiple RA-sending routers (HSRPv6/VRRPv3).\",\n  \"tradeoffs\": \"Safety/incrementalism vs running two stacks (more memory/CPU, two security/ACL policies, dual ops) during transition; tunnels avoid touching the core but add overhead/scaling limits; 6PE/6VPE reuse the IPv4 underlay but defer (not remove) native IPv6 transport parity. CGNAT/buying-more-IPv4 is a stopgap; IPv6 removes NAT state at the root.\",\n  \"trigger\": \"IPv4-only fleet with an IPv6 driver (new service, IoT, address exhaustion) and no migration plan, proposals to big-bang cut to IPv6 or re-address the working MPLS core, or tunnel sprawl used as a permanent solution.\",\n  \"observable\": \"Weakly observable. The engine inventories addressing/SVIs and l3_forwarding and could in principle flag IPv4-only operation, but it does not currently surface an explicit 'IPv6 readiness' or dual-stack assessment, and the driver/decision is requirement-led. So at most it provides the IPv4-only current-state fact, not the migration recommendation.\",\n  \"recommended_action\": \"Run dual-stack as the target transition state from a contained module after a HW/SW/app assessment + pilot; deliver IPv6 L3VPN with 6VPE (and 6PE for global) over the existing IPv4/MPLS core with per-PE rollout; provide RA-based IPv6 first-hop redundancy; reserve tunneling/NAT64 for transit/island cases.\",\n  \"alternatives\": \"NAT64/DNS64 for IPv6-only islands reaching IPv4; native dual-stack core for full parity; customer-side DMVPN where 6VPE is unavailable; one DMVPN tunnel can carry both families.\",\n  \"citation\": \"CCDE Session 15 (dual-stack phased, RA HA); CCDE scenarios (6PE/6VPE over IPv4 core, avoid big-bang)\"\n },\n {\n  \"id\": \"mgmt-change-config-mgmt-automation\",\n  \"title\": \"Wrap change in a reviewed lifecycle with rollback, version-control + drift detection, and templated/agentless automation\",\n  \"domain\": \"management\",\n  \"priority\": \"High\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"Treat configuration as more than backups: version configs (Git) for history/diff/rollback and an auditable change-decision trail, diff against a known-good baseline to detect drift, and include software-image/version + inventory management. Wrap every production change in a defined lifecycle (define-request-review-plan-execute-verify) so cost/benefit, feasibility and blast-radius are assessed before and validated after, with a rollback plan — the human-governance counterpart to read-only automation. Replace box-by-box CLI with model-based templated/controller automation (agentless e.g. Ansible where low-expertise/no-agent is a constraint) plus automated pre/post validation (e.g. pyATS/Genie) so changes are defined once, pushed consistently, and reversible. Drive monitoring proactively (tuned thresholds, OODA loop) and anchor operations to a framework (FCAPS/ITIL).\",\n  \"tradeoffs\": \"Auditability, fast rollback, consistency and stability vs the tooling/skills to build the toolchain and the process overhead — too-heavy a process invites shadow changes, too-light invites outages; continuous diffing adds load/noise if untuned; a central controller is a point of control to secure and make resilient.\",\n  \"trigger\": \"Changes made ad-hoc with no peer review/impact analysis/rollback, config backups manual with no change-tracking or drift detection, no software-version/inventory management, or provisioning manual per-device across tools with frequent human-error misconfig and difficult rollback.\",\n  \"observable\": \"Partly observable as a current-state fact, not as process. The engine produces inventory and a snapshot baseline and could diff successive snapshots (the --compare/--trend paths) to surface drift, and it reports software/EoL inventory; it cannot observe whether the customer runs Git/CAB/Ansible/pyATS or a change process. So drift-detection capability is partially supported (snapshot compare) but the governance practices are not observable.\",\n  \"recommended_action\": \"Introduce version control (Git) for config history/rollback and drift detection against a known-good baseline (+ software-image/inventory management); adopt a formal reviewed change lifecycle with mandatory rollback; deploy model-based templated/agentless automation with automated pre/post validation; run proactive threshold-based monitoring under an FCAPS/ITIL framework.\",\n  \"alternatives\": \"Agent-based config tools (Chef/Puppet) where more capability is acceptable; ITIL/CAB for large orgs vs lightweight peer-review + automated validation for faster teams; staged/canary rollout to bound blast radius; periodic compliance audits where continuous drift detection is not yet feasible.\",\n  \"citation\": \"CCDE Session 19 (change management, FCAPS configuration/drift, proactive monitoring); CCDE scenario (Git/Ansible/pyATS)\"\n },\n {\n  \"id\": \"mgmt-out-of-band-network\",\n  \"title\": \"Build a dedicated out-of-band management network so management survives a data-plane outage\",\n  \"domain\": \"management\",\n  \"priority\": \"High\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"Separate the management plane onto an independent path so the network stays reachable during a production outage, congestion, or a change that breaks the data plane; OOB removes the fate-sharing of in-band management and lets engineers diagnose and roll back remotely instead of dispatching a field engineer (lower OpEx, no truck rolls).\",\n  \"tradeoffs\": \"Independent reachability and lower OpEx vs the cost/complexity of a parallel (typically low-speed) network to secure and maintain; in-band simplicity vs OOB resilience during a data-plane outage.\",\n  \"trigger\": \"Management/SSH/SNMP reachability rides only the in-band data path (no console-server or dedicated mgmt VRF/interface); core/aggregation devices have no alternate path when the data plane is down.\",\n  \"observable\": \"Weakly observable. The engine sees management addressing/VRF context where collected and could in principle detect management sharing the data VRF, but it does not model the presence of a console-server/OOB network. So this is at most a partial inference, not a firm detection.\",\n  \"recommended_action\": \"Stand up an OOB management network (terminal/console servers, dedicated mgmt interfaces or a separate mgmt VRF/VPN) reaching every critical device; keep in-band primary and OOB the always-available backup.\",\n  \"alternatives\": \"In-band hardened with a dedicated management VRF + QoS protection for management traffic; hybrid (in-band primary, OOB fallback) where full OOB build-out is not justified.\",\n  \"citation\": \"CCDE Session 19 (in-band vs OOB, securing management plane)\"\n },\n {\n  \"id\": \"mgmt-modern-telemetry-and-active-measurement\",\n  \"title\": \"Move from polled SNMP toward NETCONF/YANG + streaming telemetry, and add active SLA measurement (IP SLA) and edge flow telemetry\",\n  \"domain\": \"management\",\n  \"priority\": \"Medium\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"SNMP polling is periodic (minutes) so it misses transient events and was never designed for transactional validated config — adopt NETCONF/YANG for model-driven transactional configuration (candidate/commit/rollback) and streaming telemetry for push-based near-real-time state, keeping SNMPv3 only where platforms cannot yet support the modern stack. Passive counters cannot prove real-time SLAs, so add synthetic IP SLA probes (delay/jitter/loss per class, hop-to-hop) to turn reactive monitoring into proactive SLA validation. For application/top-talker visibility deploy flow telemetry at the network/Internet edge on ingress, complete (unsampled) where blind spots are unacceptable and sampled where scale requires it, preferring standards-based IPFIX over vendor-specific export.\",\n  \"tradeoffs\": \"Transactional config, high-resolution visibility and proactive SLA evidence vs new tooling/collectors, probe traffic/resources, and device CPU/memory for unsampled flow; full flow has no blind spots but is hardware-limited, sampling scales but loses fidelity; edge-only placement misses purely-internal flows but avoids double-counting.\",\n  \"trigger\": \"Monitoring/automation depends solely on SNMP polling (often v2c) with box-by-box CLI config and no rollback, SLAs exist but only interface counters/RMON are collected (no delay/jitter/loss), or top-talker/app questions asked with only SNMP/syslog and no flow telemetry.\",\n  \"observable\": \"Weakly observable. The CIS/config audit can detect SNMP version and (partially) whether NETCONF/telemetry features are configured, but the engine does not model the monitoring stack's completeness, IP SLA presence, or flow-export placement. Mostly outside the evidence set; at best it flags SNMPv2c-only.\",\n  \"recommended_action\": \"Introduce NETCONF/YANG for transactional config and streaming telemetry for state (retain SNMPv3 only as fallback); deploy IP SLA probes per class on critical paths; enable IPFIX/NetFlow at the edge/peering on ingress, unsampled where blind spots are unacceptable.\",\n  \"alternatives\": \"SNMPv3 + RMON thresholds where modern stacks are unsupported; gNMI/gRPC telemetry as the push transport; sampled NetFlow on high-rate links; third-party synthetic monitoring.\",\n  \"citation\": \"CCDE Session 19 / Session 17 (NETCONF/YANG RFC 3535, telemetry, IP SLA, NetFlow placement); CCDE scenario (IPFIX over vendor-specific)\"\n },\n {\n  \"id\": \"convergence-bfd-not-aggressive-hellos\",\n  \"title\": \"Detect failures with L1/BFD, not aggressively-tuned routing-protocol hellos\",\n  \"domain\": \"methodology\",\n  \"priority\": \"High\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"Fast convergence starts with fast, reliable DETECTION. Aggressively-tuned routing hellos burden the control plane and risk false positives; BFD is a lightweight, protocol-independent, hardware-offloaded detector, and a physical/Layer-1 down signal is faster still — so detect as low in the stack as possible and leave IGP/BGP hellos at default.\",\n  \"tradeoffs\": \"Fast-convergence vs control-plane stability — sub-second timers chase speed but cause CPU load and flap churn; layering detection (L1 first, then BFD) gets speed without sacrificing stability. BFD is needed especially behind L2 switches/media-converters/optical that hide link-down.\",\n  \"trigger\": \"Real-time/voice/video present but detection relies on default 30-40s IGP dead timers, OR IGP/BGP hellos aggressively sub-second tuned with no BFD, OR routed neighbours separated by intervening L2/optical with no remote-fault signalling.\",\n  \"observable\": \"Not directly observable. The engine parses protocol neighbours/state (OSPF/BGP/HSRP) but does not currently extract per-neighbour BFD enablement or hello/dead-timer tuning, nor classify intervening L2/optical transport. Detecting a 'no BFD on a real-time path' gap is not supported by the current evidence vocabulary.\",\n  \"recommended_action\": \"Enable BFD for IGP/BGP/static next-hops on links lacking a fast L1-down signal and leave hello/dead timers at default; prefer native L1 loss-of-signal/carrier-delay where the media provides it; reserve aggressive timers for last resort.\",\n  \"alternatives\": \"Routing fast-hellos where BFD is unsupported; SONET/SDH APS or optical protection for transport; data-plane FRR (LFA/rLFA/TI-LFA/MPLS-TE FRR) layered for sub-50ms recovery.\",\n  \"citation\": \"CCDE In Depth Ch.2 Convergence ('don't tune IGP hellos aggressively, use BFD'); CCDE OSPF/IS-IS BFD\"\n },\n {\n  \"id\": \"core-simple-intelligence-at-edge\",\n  \"title\": \"Keep the core simple and fast; push intelligence, policy and stateful services to the edge\",\n  \"domain\": \"methodology\",\n  \"priority\": \"High\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"The core's job is fast packet forwarding only — not aggregation, policy insertion, user termination, or stateful services. Concentrating complexity at the edge keeps the core stable, predictable and scalable, and limits the blast radius of an edge change. A stateful core would be a single shared bottleneck.\",\n  \"tradeoffs\": \"Simplicity/stability vs feature placement — pushing policy/QoS/security to the edge multiplies enforcement points but protects core convergence; a collapsed core is acceptable for small sites if documented as a deliberate trade-off.\",\n  \"trigger\": \"Core/collapsed-core devices performing edge functions — user/VLAN termination, ACL/policy enforcement, NAT, or stateful firewalling in the core path.\",\n  \"observable\": \"Partially observable. The engine reconstructs topology/roles and SVIs/l3_forwarding per device and can see a collapsed-core device carrying many access SVIs; QoS audit can detect policy at a device. But it does not yet classify 'this is the core AND it terminates users/runs stateful policy' as a single rule — role inference is limited, so this is a weak/partial detection.\",\n  \"recommended_action\": \"Relocate user termination, policy and stateful services to distribution/edge; reduce the core to a lean high-speed forwarding layer; on a collapsed core, plan separation of aggregation/services from forwarding as scale grows.\",\n  \"alternatives\": \"Collapsed core for small sites (documented); service-leaf/border-leaf placement in fabric keeps services off the spine.\",\n  \"citation\": \"CCDE In Depth Ch.2 Network Topologies ('intelligence at the edge, core as simple as possible')\"\n },\n {\n  \"id\": \"optimal-routing-summarize-at-aggregation\",\n  \"title\": \"Summarize at the aggregation boundary to protect the core, accepting bounded sub-optimality\",\n  \"domain\": \"methodology\",\n  \"priority\": \"High\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"Summarizing at the aggregation/distribution layer keeps the core's table small and hides access-layer churn, so the core stays stable and access changes do not ripple inward. This is the deliberate price for the key trade-off: whenever you summarize, the chance of sub-optimal routing and (mishandled) black-holing rises. The distribution layer is the summarization + fault-isolation point.\",\n  \"tradeoffs\": \"Optimal-routing vs scalability/stability — summarization removes control-plane state (smaller tables, faster SPF, contained failures) at the cost of forwarding optimality and black-hole risk if a summarized component fails without a covering route. Demands contiguous per-module addressing.\",\n  \"trigger\": \"No IGP summarization at area/level or distribution-to-core boundaries — full specific routes from access leak into the core, so every access flap reaches the core.\",\n  \"observable\": \"NOT observable as configured. There is no compute_* that audits for area range / ip summary-address / aggregate-address presence or for clean contiguous addressing; the protocol layer parses BGP/OSPF state, not summarization config. The engine can only see indirect proxies (RIB/SVI counts, l3_forwarding breadth) — it cannot assert 'summarization is missing'.\",\n  \"recommended_action\": \"Configure summarization at the aggregation layer toward the core with contiguous per-module addressing; pair summaries with a discard/null route and component-aware advertisement to prevent black-holing of failed specifics.\",\n  \"alternatives\": \"No summarization where end-to-end optimal routing or TE visibility is required; selective summarization of stable prefixes; leak more-specifics where a path must stay optimal.\",\n  \"citation\": \"CCDE In Depth Ch.2 Optimal Routing; Cisco Campus CVD (summarize at distribution)\"\n },\n {\n  \"id\": \"requirements-classification-and-traceability\",\n  \"title\": \"Classify every requirement (business / functional / application / technical / constraint) and trace decision-to-requirement\",\n  \"domain\": \"methodology\",\n  \"priority\": \"High\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"A senior designer tags each gathered fact into exactly one bucket — business goal, functional requirement, application requirement, technical/non-functional requirement, or fixed constraint — and scores design options only inside the box that constraints draw. Each option links forward (requirement -> decision -> validation) and backward (decision -> why), giving an auditable requirements-traceability matrix.\",\n  \"tradeoffs\": \"Decision quality and auditability vs the up-front discovery effort; constraints (budget, installed base, skills, regulatory) frequently override the otherwise-ideal functional choice, so they must be captured as hard inputs.\",\n  \"trigger\": \"Design or recommendation is proceeding without a classified requirement set, or a 'best-practice' answer is being given that ignores a stated constraint.\",\n  \"observable\": \"Not observable from the snapshot: the engine ingests device evidence only, not a requirements/constraints register. It can emit decision records keyed to evidence, but cannot verify a requirement->decision->validation chain it was never given.\",\n  \"recommended_action\": \"Run a requirements pass that records business goals, the application matrix (per-app latency/loss/bandwidth + flows), technical -ilities (availability/scale/security/manageability), and fixed constraints; structure as linked records so each design element maps to a requirement and a validation test.\",\n  \"alternatives\": \"Lightweight assumption log where full RTM is overkill; templates/source-of-truth tooling to enforce the linkage on larger estates.\",\n  \"citation\": \"CCDE Study Guide Ch.1 (requirements taxonomy + constraints); Jama/ReqView RTM (forward/backward traceability); Orhan Ergun functional vs non-functional\"\n },\n {\n  \"id\": \"stp-root-fhrp-active-colocation\",\n  \"title\": \"Co-locate the STP root with the FHRP active gateway and enable preemption with delay\",\n  \"domain\": \"methodology\",\n  \"priority\": \"High\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"The spanning-tree root, the FHRP active gateway, and any active stateful service for a VLAN should sit on the SAME distribution switch; if they diverge, the inter-distribution link becomes a transit link and traffic takes a sub-optimal multi-hop L2 path to its gateway. HSRP should wait for STP to converge before going active to avoid a transient black hole.\",\n  \"tradeoffs\": \"Optimal-forwarding vs operational simplicity, and fast-recovery vs transient drops — HSRP defaults to no preemption (root and active desync after failback); enabling preemption restores optimality but without a boot/connectivity delay can black-hole when a returning switch preempts before it has core reachability.\",\n  \"trigger\": \"Per-VLAN STP root bridge and FHRP active gateway resolve to different distribution switches, and/or HSRP preemption disabled on a looped L2-access topology.\",\n  \"observable\": \"Partially observable but currently NOT correlated. The engine parses STP (root/blocked/inconsistent) and FHRP groups (HSRP/VRRP/GLBP active) separately, and has a root-placement notion, but there is no compute_* that joins per-VLAN STP-root identity to FHRP-active identity to assert co-location. Building that correlation is feasible from existing parsed fields.\",\n  \"recommended_action\": \"Align STP root priority and FHRP active (and stateful contexts) onto the same distribution node per VLAN; enable FHRP preempt with preempt-delay greater than measured switch boot/convergence time.\",\n  \"alternatives\": \"vPC/MLAG or routed-access removing the inter-distribution L2 transit dependency; anycast gateway in a fabric so the alignment problem disappears.\",\n  \"citation\": \"CCDE In Depth Ch.1 (STP-FHRP interaction); CCDE Switching/DC ('HSRP active follow STP root', 'HSRP wait till STP converged')\"\n },\n {\n  \"id\": \"trade-off-axes-named-primary-driver\",\n  \"title\": \"Score every decision against the canonical trade-off axes and name one ranked primary driver\",\n  \"domain\": \"methodology\",\n  \"priority\": \"High\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"No design maximizes availability, fast convergence, scalability, modularity, security, simplicity, optimal-routing, load-balancing, manageability and cost simultaneously. Treat them as a fixed budget: raising one spends from others. Each decision should declare its single primary driver, then rank the rest, and record which axes were deliberately traded away.\",\n  \"tradeoffs\": \"The axes are mutually constraining: HA vs cost/simplicity; fast-convergence vs stability; scalability vs optimal-routing (summarization hides specifics); security vs usability/performance; load-balancing vs deterministic routing. Cost is a tiebreaker only when the scenario names it, otherwise the budget all others draw from.\",\n  \"trigger\": \"A design choice is presented as strictly 'best' with no stated primary axis and no acknowledgement of what it costs on the other axes (a 'vibes' recommendation).\",\n  \"observable\": \"Partially observable as inputs to the reasoning: the engine measures several axes directly (availability via FHRP/SPOF/dual-homing; scalability proxies via vlan_inventory flat-L2 and RIB size; manageability via syslog/platform_health; lifecycle/cost-pressure via EoL). It cannot weigh them without a requirement ranking, so it surfaces the evidence per axis rather than choosing the winner.\",\n  \"recommended_action\": \"For each consequential decision emit {decision, driving_requirement, primary_axis, axis_scores, tensions_accepted, constraint_bounds}; require the primary driver to be explicit so the trade-off is auditable.\",\n  \"alternatives\": \"Single-axis optimization where the scenario truly has one overriding driver; defer the ranking to the human checkpoint when requirements are ambiguous.\",\n  \"citation\": \"Oppenheimer Top-Down Network Design (8 canonical axes, fixed-budget framing); CCDE In Depth Ch.2 (design = managing trade-offs)\"\n },\n {\n  \"id\": \"why-first-top-down-design\",\n  \"title\": \"Design top-down from business and application requirements (know the WHY)\",\n  \"domain\": \"methodology\",\n  \"priority\": \"High\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"Network design is the management of trade-offs to meet business and application requirements; technology is chosen last. Start from business goals, then applications and their SLAs, then users/traffic, and only then pick protocols/topology. Every target-state recommendation must trace to a stated requirement rather than being maximized in isolation.\",\n  \"tradeoffs\": \"This is the meta-axis governing all others: it forces each HA/convergence/scale/cost/security choice to be justified against a requirement, and guards against cutting-edge complexity that creates fragility. Cost is the universal counterweight every other axis draws from.\",\n  \"trigger\": \"Assessment findings exist but there is no captured statement of business goals, application/SLA requirements, growth forecast, or success criteria to justify target-state decisions.\",\n  \"observable\": \"The engine has rich current-state evidence (inventory, vlan_inventory, FHRP, SPOF/blast-radius, punchlist) but NO requirements model: there is no field for SLA targets, app criticality, RTO/convergence budgets, or budget constraints. It can detect the ABSENCE of a requirements basis only indirectly (it never receives one).\",\n  \"recommended_action\": \"Before recommending target-state changes, gather and record the requirement set (business goals, critical apps + delay/jitter/loss/availability needs, growth, constraints/budget) and justify each design decision by tracing it to a specific requirement; prefer the simplest solution that meets it.\",\n  \"alternatives\": \"Bottom-up/technology-first design (faster, risks rework — acceptable only for small well-understood changes); iterative requirements capture where a full up-front gather is infeasible.\",\n  \"citation\": \"CCDE In Depth (Ergun) Ch.2 'Know the purpose of your design'; Oppenheimer Top-Down Network Design (requirements-first); CCDE WHY->WHAT->HOW\"\n },\n {\n  \"id\": \"redistribution-avoid-or-fence\",\n  \"title\": \"Avoid redistribution where possible; where unavoidable, fence it with route tags and filters\",\n  \"domain\": \"methodology\",\n  \"priority\": \"Medium\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"Redistributing between routing protocols sharply increases complexity and is the classic place loops form — especially two-way (mutual) redistribution at multiple points. A single common IGP is almost always better for management, troubleshooting, convergence and availability. This is a frequent brownfield merger/acquisition artifact.\",\n  \"tradeoffs\": \"Necessary-complexity vs simplicity/stability — partner connections, BGP-into-IGP injection, or a merger may force redistribution; the cost is loop risk that must be actively contained with one-way flow where possible, tags and filters at every mutual point, and multiple redistribution points for redundancy (which themselves multiply loop risk).\",\n  \"trigger\": \"Multiple IGPs with mutual (two-way) redistribution, particularly at more than one boundary and without route tags/filters.\",\n  \"observable\": \"Partially observable. The engine's routing-protocol inventory shows WHICH protocols run per device (so 'two IGPs coexist' is detectable), but it does not parse redistribution statements, route tags, or filter lists — it cannot confirm a mutual-redistribution seam or whether it is tagged/filtered. Detection is limited to 'multiple IGPs present'.\",\n  \"recommended_action\": \"Where feasible converge onto one common IGP and delete redistribution; where it must stay, make it one-way if possible, redistribute at multiple points for redundancy, and tag-and-filter (deny the tag on re-entry) at every mutual point.\",\n  \"alternatives\": \"Inter-AS MPLS VPN/BGP at the seam; ships-in-the-night coexistence; controlled default-only injection.\",\n  \"citation\": \"CCDE In Depth Ch.2 Load Balancing/Redistribution & M&A; CCDE EIGRP/IGP-comparison\"\n },\n {\n  \"id\": \"simplicity-dual-redundancy-enough\",\n  \"title\": \"Use only necessary redundancy — two is company, three is a crowd\",\n  \"domain\": \"methodology\",\n  \"priority\": \"Medium\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"A robust network needs some complexity, but dual redundancy is generally enough; a third level adds cost and complexity without proportional benefit and can paradoxically raise MTTR and lower availability. Unnecessary complexity is the enemy — it raises OpEx, slows troubleshooting, and is the hidden cost of most feature additions.\",\n  \"tradeoffs\": \"HA vs simplicity/cost/OpEx — each redundancy tier raises CapEx and operational burden; the art is stopping at 'robust enough'. Shift complexity into automation rather than into more boxes.\",\n  \"trigger\": \"Over-engineered redundancy — triple-redundant nodes/paths, stacked overlapping HA mechanisms, or heavily customized non-default tuning whose benefit is not tied to a requirement.\",\n  \"observable\": \"Weakly observable. The engine can see dual-homing percentages and overlapping STP/FHRP mechanisms, but 'too much redundancy' is judged against a requirement the engine lacks; in practice the [HISTORY-REDACTED] fleet's gap is UNDER-redundancy (FHRP absent), so over-engineering is rarely the detected condition here.\",\n  \"recommended_action\": \"Standardize on dual redundancy for critical paths/nodes and remove the third+ tier; prefer the configuration that meets the requirement with the fewest steps; collapse overlapping HA features to one mechanism per failure mode.\",\n  \"alternatives\": \"Retain N+2 only where a quantified availability requirement demands it; move complexity into automation/NMS.\",\n  \"citation\": \"CCDE In Depth Ch.2 Simplicity ('two's company, three's a crowd'; too much redundancy increases MTTR)\"\n },\n {\n  \"id\": \"mpls-te-frr-and-protection-layer\",\n  \"title\": \"Choose the protection layer (L1 / IGP+BFD / MPLS-TE FRR) and FRR scope (link vs node) by failure model\",\n  \"domain\": \"mpls-te\",\n  \"priority\": \"Critical\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"Resilience can live at L1 (SONET/DWDM 1+1, fast but idle costly standby), in the IGP control plane (global view, sub-second but not guaranteed) or in MPLS-TE FRR (local repair at the PLR in ~50ms via pre-signaled make-before-break bypass). Pick the cheapest layer that meets each service's convergence target and don't stack overlapping protection. For FRR, default to link protection where ops capacity is limited, add node protection where a P-node failure is a real risk, and force primary/backup physical diversity with SRLG so a single fibre cut cannot take both.\",\n  \"tradeoffs\": \"Guaranteed speed vs cost/idle capacity (L1) vs simplicity-but-no-guarantee (IGP) vs fast-local-but-complex (FRR); node protection covers more but is heavier; SRLG accuracy is an ongoing operational burden; overlapping layers waste capex and interact badly.\",\n  \"trigger\": \"Core/transport relies on IGP-only reconvergence too slow for real-time SLAs, single-layer protection mismatched to the SLA, or 'redundant' links/tunnels not verified physically diverse.\",\n  \"observable\": \"NOT observable. MPLS-TE FRR, RSVP bypass, and protection-layer choice are outside the engine. SRLG/physical-path diversity is also not modelled (the engine reconstructs logical adjacency from CDP/LLDP but has no conduit/fibre/SRLG data) — so even logical 'two uplinks' cannot be proven physically diverse.\",\n  \"recommended_action\": \"Map each protected service to the cheapest layer meeting its target (FRR ~50ms for hard real-time, tuned IGP+BFD for general, L1 only where transport provides it); use link-FRR by default, node-FRR for real P-node risk, and SRLG-disjoint primary/backup.\",\n  \"alternatives\": \"Pure IGP fast-convergence; L1-only restoration; TI-LFA as a lighter loop-free alternative to RSVP FRR.\",\n  \"citation\": \"CCDE Session 9 (protection L1/L2/L3, FRR link/node, SRLG); CCDE scenario (SRLG same-duct, TI-LFA diverse paths)\"\n },\n {\n  \"id\": \"mpls-ldp-igp-sync-and-hygiene\",\n  \"title\": \"Enable LDP-IGP synchronization and loopback label hygiene to prevent black-holing\",\n  \"domain\": \"mpls-te\",\n  \"priority\": \"High\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"When an IGP path comes up before LDP has exchanged labels (or LDP fails while the IGP path stays up), labelled traffic is forwarded onto a link with no label binding and dropped. LDP-IGP synchronization (and session protection) holds the IGP off a link until labels are programmed. Source LDP/RSVP and BGP next-hops from stable loopbacks, use them as router-IDs, and filter label allocation to loopback /32s to keep the LFIB lean and next-hop resolution clean. Verify LSPs with MPLS OAM (LSP ping/BFD/traceroute) since an LSP can be control-plane 'up' yet data-plane broken.\",\n  \"tradeoffs\": \"Black-hole-free convergence and clean next-hop resolution vs slightly slower link activation and the discipline of consistent loopback addressing and allocation filters; an over-tight filter can break a needed LSP.\",\n  \"trigger\": \"An MPLS core running LDP with the IGP but no LDP-IGP sync/session-protection, labels allocated for many interface prefixes, sessions not loopback-sourced, or LSPs verified only by control-plane state.\",\n  \"observable\": \"NOT observable. The engine has no MPLS/LDP/RSVP/MPLS-OAM awareness. Outside the evidence set and not applicable to the [HISTORY-REDACTED] enterprise fleet.\",\n  \"recommended_action\": \"Enable LDP-IGP synchronization + session protection across the core; loopback-source sessions/router-IDs and filter label allocation to loopback /32s; run MPLS OAM (LSP ping/traceroute, LSP-BFD) on tunnels and pseudowires.\",\n  \"alternatives\": \"Converge on RSVP-TE LSPs (self-signal labels) to avoid the LDP-first-hop race; LDP graceful-restart alone where full sync is unsupported; on-demand LSP ping instead of always-on BFD.\",\n  \"citation\": \"CCDE Session 7 (LDP-IGP sync, loopback label hygiene, MPLS OAM)\"\n },\n {\n  \"id\": \"mpls-te-igp-extensions-and-scope\",\n  \"title\": \"Enable IGP TE extensions to feed CSPF and confine TE state to the core\",\n  \"domain\": \"mpls-te\",\n  \"priority\": \"High\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"CSPF can only compute a constrained path if the IGP floods per-link TE attributes (reservable bandwidth, TE metric, affinity) via OSPF Opaque LSA-10 or IS-IS extended TLVs (22/135) with wide metrics; without them the headend is blind and TE degrades to shortest-path. Scope TE (especially full meshes) to high-capacity core/P routers and use auto-mesh/auto-tunnel-backup so RSVP soft-state does not sprawl onto the edge.\",\n  \"tradeoffs\": \"Full TE topology for accurate computation vs extra LSA/LSP flooding and fleet-wide wide-metric support; core-only TE optimizes the backbone but not first/last-mile, and edge TE scales poorly.\",\n  \"trigger\": \"MPLS-TE (or a plan for it) with no IGP TE extensions (narrow IS-IS metrics, no Opaque LSAs), or tunnels fanning out to access/aggregation devices.\",\n  \"observable\": \"NOT observable. No MPLS-TE, IGP-TE-extension, RSVP-state, or wide-metric awareness exists in the engine. Outside the evidence set and not applicable to the [HISTORY-REDACTED] enterprise fleet.\",\n  \"recommended_action\": \"Turn on IGP TE extensions across the TE domain and advertise reservable bandwidth/TE-metric/affinity per link; scope TE to core PoP-to-PoP routers with RSVP auto-mesh, keeping access on LDP/IGP.\",\n  \"alternatives\": \"Explicit/static ERO tunnels on small stable topologies; PCE + BGP-LS for offline/inter-domain computation; SR-TE to remove per-LSP state.\",\n  \"citation\": \"CCDE Session 9 (IGP TE extensions, core-only scope, auto-mesh)\"\n },\n {\n  \"id\": \"mpls-te-needs-driver-and-rsvp\",\n  \"title\": \"Deploy MPLS-TE only for a concrete driver, and use RSVP-TE (not LDP) for constraint-based LSPs\",\n  \"domain\": \"mpls-te\",\n  \"priority\": \"High\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"LDP follows the plain IGP shortest path with no notion of bandwidth/latency/affinity, so it can never build a constraint-satisfying or explicitly-routed tunnel. Introduce RSVP-TE precisely when traffic must be placed by constraints — and only for a stated driver (extract capacity from existing links, guarantee bandwidth, load-share unequal paths, or sub-50ms protection). Use tactical TE first to relieve hot spots, then a strategic full-mesh for ongoing capacity management; SR-TE removes per-LSP RSVP soft-state.\",\n  \"tradeoffs\": \"Optimal/controlled path placement and admission control vs per-LSP RSVP soft-state and operational complexity; TE that solves no stated problem is pure overhead, and adding capacity is sometimes cheaper than TE complexity.\",\n  \"trigger\": \"Links congested while parallel/equal-cost paths sit idle (IGP shortest-path hot-spotting), or a guaranteed-bandwidth/protection requirement the IGP-only design cannot honour, with LDP-only label distribution.\",\n  \"observable\": \"NOT observable. The engine has no MPLS/RSVP-TE/LDP awareness, no per-link utilization or reservable-bandwidth telemetry, and no traffic matrix. Uneven utilization itself is not measured (no interface-counter trend ingestion). Outside the evidence set, and not applicable to the enterprise-L2/L3 [HISTORY-REDACTED] fleet.\",\n  \"recommended_action\": \"State the driver first; deploy RSVP-TE with CSPF for the constrained flows (keep LDP for any-to-any), tactical tunnels for hot spots then a strategic mesh, and consider SR-TE to drop per-LSP state.\",\n  \"alternatives\": \"IGP metric/ECMP tuning; QoS-only congestion management; capacity upgrade where the cost delta favours bandwidth.\",\n  \"citation\": \"CCDE Session 9 (TE drivers, LDP cannot build CBR LSPs); CCDE scenario (tactical->strategic TE)\"\n },\n {\n  \"id\": \"multicast-rp-redundancy\",\n  \"title\": \"Make the RP redundant (Anycast-RP + MSDP for SM; Phantom-RP for Bidir) and place it near sources\",\n  \"domain\": \"multicast\",\n  \"priority\": \"Critical\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"In PIM-SM/Bidir the RP is the root of the shared tree and a single point of failure; a lone static RP black-holes group joins on failure. Anycast-RP gives multiple routers the same RP address (receivers join the nearest, failover follows the IGP) with MSDP sharing active-source state between RP instances. Bidir has no source state so cannot use Anycast/MSDP — use Phantom-RP (advertise the RP loopback at two routers with different prefix lengths so the IGP fails it over). Position the RP near the sources to keep the shared tree short.\",\n  \"tradeoffs\": \"RP high-availability/load-sharing vs running MSDP (mesh-group beyond ~3 RPs) and keeping RP state consistent; Phantom-RP relies on careful IGP route-length engineering. HA/scale vs simplicity.\",\n  \"trigger\": \"A single statically-defined RP, multiple RPs with no MSDP peering, or Bidir-PIM deployed with one hard-coded RP and no Phantom-RP.\",\n  \"observable\": \"NOT observable. The engine does not parse RP configuration, Anycast-RP, MSDP, or Phantom-RP. (It sees IGMP queriers and PIM presence, but not the RP control-plane design.) Outside the evidence set.\",\n  \"recommended_action\": \"Deploy Anycast-RP (shared loopback on 2+ routers) + MSDP for SM/Bidir-source sharing; use Phantom-RP for Bidir; locate the RP near source aggregation.\",\n  \"alternatives\": \"BSR/Auto-RP for dynamic RP election; SSM (no RP at all) where receivers know sources; static RP only where availability is non-critical.\",\n  \"citation\": \"CCDE Session 11/12 (Anycast-RP/MSDP, Phantom-RP, RP placement)\"\n },\n {\n  \"id\": \"multicast-sparse-mode-never-dense\",\n  \"title\": \"Default to PIM Sparse-Mode (explicit-join); never run Dense-Mode, and prevent dense fallback\",\n  \"domain\": \"multicast\",\n  \"priority\": \"High\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"Sparse-Mode forwards a group only where a receiver has explicitly joined, so it scales and contains traffic; Dense-Mode (and sparse-dense) floods every group and relies on prune, which wastes bandwidth/state and can melt the network at scale. Standardize on SM everywhere multicast is routed, define an explicit RP strategy, and use 'ip pim autorp listener' (so only Auto-RP groups behave dense) rather than sparse-dense, so an RP/MA failure degrades gracefully instead of flooding. Migrate legacy dense-mode estates to sparse-mode.\",\n  \"tradeoffs\": \"SM adds an RP/control plane and join latency in exchange for bandwidth efficiency and bounded state; DM is trivial to turn on but trades that for flood-and-prune overhead and outage risk.\",\n  \"trigger\": \"PIM dense-mode or sparse-dense-mode on production interfaces/SVIs, multicast running with no RP, or sparse-dense in use for Auto-RP with no autorp-listener and no redundant RP.\",\n  \"observable\": \"Partially observable. The multicast/service-map layer extracts IGMP queriers and PIM presence per VLAN/segment (build_igmp_queriers; the 30 querier-evidenced VLANs that lifted the canonical count to 202 came from here). Whether the routed PIM mode is dense vs sparse, and RP/autorp-listener config, are NOT robustly parsed — so 'dense-mode in production' is a weak/heuristic detection at most.\",\n  \"recommended_action\": \"Standardize on PIM Sparse-Mode, define an explicit (redundant) RP, remove dense-mode from data interfaces, and use the Auto-RP listener instead of sparse-dense; migrate legacy dense-mode to sparse.\",\n  \"alternatives\": \"Bidir or SSM for specific application shapes; sparse-dense only as a discouraged transitional state; BSR for dynamic RP without dense fallback.\",\n  \"citation\": \"CCDE Session 11 (PIM modes, autorp-listener); CCDE scenario (migrate dense->sparse); engine build_igmp_queriers\"\n },\n {\n  \"id\": \"multicast-mode-by-pattern-ssm-bidir\",\n  \"title\": \"Select SSM / ASM / Bidir from the source-receiver pattern and the state-vs-optimality trade-off\",\n  \"domain\": \"multicast\",\n  \"priority\": \"Medium\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"Map the application flow to the PIM mode: one/few known sources to many receivers (IPTV/VoD/market-data) favours SSM (source-rooted SPT, no RP, most optimal, IGMPv3) or ASM where receivers do not know sources; genuinely many-to-many (message buses, conferencing, trading floors) favours Bidir to collapse (S,G) state (DF per link, no RPF) at the cost of RP-rooted sub-optimal paths and weaker RP redundancy. For latency-sensitive SM flows set SPT-threshold to 0 to leave the shared tree immediately. Accommodate intermittent (bursty) sources by extending state lifetime or using Bidir/SSM (not data-driven).\",\n  \"tradeoffs\": \"Optimal source trees / no RP (SSM, more state, needs IGMPv3) vs minimal router state (Bidir/ASM shared trees, need an RP); threshold-0 = optimal paths but max (S,G) state; Bidir minimizes state but is sub-optimal and RP-load-bound.\",\n  \"trigger\": \"One-to-many video on ASM/IGMPv2 (no SSM range 232/8, no IGMPv3), a many-to-many app on SM with exploding (S,G) state, latency-sensitive SM pinned to the shared tree (SPT-threshold infinity), or intermittent critical sources on data-driven SM.\",\n  \"observable\": \"NOT observable. The engine detects multicast presence (IGMP queriers/PIM) but not PIM mode (SSM/ASM/Bidir), SPT-threshold, IGMPv3 vs v2, or the application flow pattern. The mode recommendation requires application knowledge the engine lacks.\",\n  \"recommended_action\": \"Use SSM (232/8 + IGMPv3) for one-to-many with known sources; ASM where sources are unknown; Bidir for many-to-many; set SPT-threshold 0 for latency-sensitive SM; extend state lifetime or use Bidir/SSM for bursty sources.\",\n  \"alternatives\": \"ASM with Anycast-RP+MSDP where SSM host support is missing; static/DNS SSM source mapping; segment groups so only true many-to-many uses Bidir.\",\n  \"citation\": \"CCDE Session 11/12 (SSM/ASM/Bidir, SPT-threshold, intermittent sources); CCDE scenarios (mode by pattern)\"\n },\n {\n  \"id\": \"multicast-rpf-and-transit-fixes\",\n  \"title\": \"Repair RPF failures over tunnels/asymmetry, and bridge multicast across incapable transit (MSDP+MBGP, AMT, overlay)\",\n  \"domain\": \"multicast\",\n  \"priority\": \"Medium\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"Multicast forwarding depends on the RPF check (traffic must arrive on the unicast-toward-source interface), so GRE tunnels, asymmetric routing, or divergent multicast/unicast topologies silently break delivery — fix with a static mroute toward the correct interface (and ensure register/join arrive there too) or run MBGP to carry a coherent multicast RPF topology. Across domains use MSDP between RPs + MBGP (IPv4 multicast SAFI), not PIM-DM at the exchange. Where transit cannot carry the needed service (Internet/partner unicast-only, or an SP carrying only IPv4-unicast/dense-mode), use AMT or a customer GRE/DMVPN overlay rather than silently downgrading multicast to unicast.\",\n  \"tradeoffs\": \"Restored/extended delivery vs manual static-mroute maintenance (drifts from live topology), added MSDP/MBGP control protocols, or overlay/relay infrastructure and replication inefficiency; reach/correctness vs complexity.\",\n  \"trigger\": \"Multicast over GRE/overlay or asymmetric paths with no static mroute (RPF fails), separate multicast domains with no MSDP/MBGP, or a required multicast/IPv6 service riding transit (SP/Internet) that cannot carry it.\",\n  \"observable\": \"NOT observable. The engine does not model RPF state, mroutes, MSDP/MBGP, AMT, or SP transport capability. Outside the evidence set.\",\n  \"recommended_action\": \"Add a static mroute toward the tunnel/correct upstream (verifying register/join paths) or run MBGP; peer RPs with MSDP + MBGP across domains; use AMT or a customer overlay to carry multicast/IPv6 over incapable transit — never downgrade multicast to unicast.\",\n  \"alternatives\": \"MBGP multicast NLRI for a dynamic RPF topology; SSM end-to-end (no MSDP, needs source knowledge); SP mVPN/6VPE where a managed service exists.\",\n  \"citation\": \"CCDE Session 12 (RPF/mroute, MSDP/MBGP, AMT); CCDE scenarios (overlay over incapable SP)\"\n },\n {\n  \"id\": \"qos-diffserv-over-intserv\",\n  \"title\": \"Prefer DiffServ (class-based PHB) over per-flow IntServ/RSVP at scale, and don't run both as the QoS model\",\n  \"domain\": \"qos\",\n  \"priority\": \"High\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"Per-flow IntServ/RSVP holds reservation state for every flow and does not scale on aggregation/core links; DiffServ aggregates traffic into a small set of classes with per-hop behaviours, giving a scalable stateless-per-flow model. Standardize on DiffServ as the data-plane QoS; reserve RSVP for its TE/admission-control niche, and never run IntServ and DiffServ as overlapping QoS schemes for the same traffic.\",\n  \"tradeoffs\": \"Hard per-flow guarantees/admission (IntServ) vs scalability/simplicity (DiffServ); mixing both multiplies complexity for little gain.\",\n  \"trigger\": \"Per-flow reservation/RSVP-style QoS in an aggregation/core role, a design attempting per-flow guarantees fleet-wide, or both IntServ and DiffServ proposed as the QoS scheme in one domain.\",\n  \"observable\": \"Partially observable. compute_qos_audit reads QoS config and can surface the class/marking model on collected devices; it does not specifically classify IntServ-vs-DiffServ or detect overlapping models, so this is a weak detection at best.\",\n  \"recommended_action\": \"Adopt a DiffServ class-of-service model (mark at the edge, enforce CS/AF/EF PHBs hop-by-hop); reserve RSVP for MPLS-TE/CAC niches only.\",\n  \"alternatives\": \"RSVP/IntServ where strict per-flow admission is mandatory and flow count is small; NBAR-assisted RSVP; hybrid (RSVP-CAC over a DiffServ core).\",\n  \"citation\": \"CCDE Session 10 (IntServ limits vs DiffServ); CCDE scenario (don't mix IntServ+DiffServ)\"\n },\n {\n  \"id\": \"qos-edge-shaping-and-pervasive-queuing\",\n  \"title\": \"Shape egress to the contracted rate before the SP polices, and queue at every congestion point\",\n  \"domain\": \"qos\",\n  \"priority\": \"Medium\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"SPs police ingress to the subscribed CIR and drop the excess blindly (often hitting priority traffic), so shaping on the CE egress to the contracted rate lets the customer control which packets are delayed/dropped. More broadly, loss/latency arise wherever traffic can outrun an egress interface (speed mismatches, aggregation, oversubscribed uplinks), so enable queuing at every such point — not only the WAN edge — and over-provision the owned/uncongested core, keeping core QoS coarse (control traffic highest). On an owned, chronically uncongested core, skipping QoS is a valid simplicity choice.\",\n  \"tradeoffs\": \"Added egress delay from shaping vs blind provider drops; pervasive queuing coverage vs config effort; core over-provisioning cost vs core simplicity. QoS is a congestion tool — pointless where there is no contention.\",\n  \"trigger\": \"CE egress not shaped to the carrier CIR (rate mismatch) with real-time on the link; queuing only at the WAN edge while internal speed-mismatch/aggregation points run FIFO; or QoS proposed on an owned, under-utilized core.\",\n  \"observable\": \"Weakly observable. The engine sees device QoS-config presence (compute_qos_audit) and topology aggregation points, so 'no queuing on an aggregation device' is partially inferable; it does not measure link utilization or SP CIR, so 'shape before policing' and 'core is uncongested' cannot be confirmed.\",\n  \"recommended_action\": \"Apply hierarchical egress shaping on the CE to the CIR with a child queuing policy; deploy egress queuing at each congestion point (access uplinks, distribution/core aggregation, WAN edge); over-provision and keep coarse classes on an owned core, or skip core QoS where it is genuinely uncongested.\",\n  \"alternatives\": \"Negotiate a higher CIR/full-rate access; selective queuing only at proven choke points where the rest is non-blocking.\",\n  \"citation\": \"CCDE Session 10 (shape-before-police, queue everywhere, core over-provision); CCDE scenario (no QoS on owned uncongested core)\"\n },\n {\n  \"id\": \"scenario-terminate-untrusted-overlay-behind-firewall\",\n  \"title\": \"Terminate overlays from untrusted/partner sites on a dedicated device behind the firewall, not on the core/Internet edge\",\n  \"domain\": \"scenario-pattern\",\n  \"priority\": \"Critical\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"Traffic arriving from networks outside your administrative control must be decapsulated where the firewall can still inspect it and on hardware whose failure is isolated from production. Terminating tunnels on the core or Internet gateway both bypasses inspection and lets remote-site instability shake your most critical routers — so land the overlay on a dedicated termination router placed behind the firewall.\",\n  \"tradeoffs\": \"Failure-domain isolation + enforced stateful inspection vs the cost of an extra dedicated termination device; reusing existing core/edge routers is cheaper but creates fate-sharing and an inspection blind spot.\",\n  \"trigger\": \"Tunnels/overlays from partner or untrusted external sites terminating directly on core switches, Internet-gateway routers, or DC switches, so decapsulated traffic enters the trusted network without inspection and shares fate with production.\",\n  \"observable\": \"NOT observable. The engine does not model tunnel termination points, firewalls, or trust zones, and the relevant devices are typically WAN-edge/security appliances outside the assessed switching estate. Outside the evidence set.\",\n  \"recommended_action\": \"Land the overlay on a dedicated termination router behind the firewall so decapsulated traffic is statefully inspected before entering the internal network and a fault in the external sites cannot destabilize the core/edge.\",\n  \"alternatives\": \"Terminate on existing core/IGW (cheaper, no inspection + fate-sharing); terminate on the firewall itself where it scales and supports the encapsulation.\",\n  \"citation\": \"CCDE MilkaTurka scenario (GRE termination placement: failure isolation + stateful inspection)\"\n },\n {\n  \"id\": \"scenario-opex-over-capex-reuse-edge\",\n  \"title\": \"At large branch scale optimize for OpEx (reuse existing edge via tunnels) over CapEx (new device+circuit per site)\",\n  \"domain\": \"scenario-pattern\",\n  \"priority\": \"High\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"At hundreds-to-thousands of remote/partner sites the dominant lifetime cost is operational (truck rolls, spares, power/cooling, ticketing, RMAs), not the one-time hardware purchase. When existing/partner edge equipment can terminate a tunnel over existing transport, reusing it avoids a per-site fleet you must operate forever — so justify any per-site device against its multiplied OpEx, not its unit price, and buy dedicated hardware/circuits only where a hard requirement (control, isolation, capacity) demands it.\",\n  \"tradeoffs\": \"Lower OpEx and faster rollout vs less control over partner-owned gear and shared fate with equipment you don't manage; new dedicated hardware gives control and a clean failure domain but multiplies operational burden by the site count.\",\n  \"trigger\": \"A large fan-out of remote/partner sites where the proposed design adds a new managed router/firewall and a new circuit at every site, and existing edge gear can already terminate a tunnel.\",\n  \"observable\": \"NOT observable. This is a WAN/branch cost-and-architecture decision requiring site count, partner-equipment capability and OpEx/CapEx inputs the engine does not hold; the assessed estate is the campus, not the branch-WAN economics. Outside the evidence set.\",\n  \"recommended_action\": \"Default to an overlay tunnel over existing/partner edge and existing transport; add per-site hardware/circuits only where a hard requirement demands it, justified against multiplied OpEx.\",\n  \"alternatives\": \"New dedicated CPE + private circuit per site (control, clean failure domain, high OpEx); slower batch/periodic data exchange where near-real-time is not required.\",\n  \"citation\": \"CCDE MilkaTurka scenario (new-device-vs-tunnel cost analysis)\"\n },\n {\n  \"id\": \"scenario-nat-localas-for-merger-collisions\",\n  \"title\": \"Resolve merger address/AS-number collisions with NAT44 and BGP Local-AS, plan re-addressing as the clean fix\",\n  \"domain\": \"scenario-pattern\",\n  \"priority\": \"Medium\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"Two merged networks frequently reuse the same RFC1918 ranges (so they cannot route to each other) and sometimes the same BGP ASN (so eBGP/loop-prevention breaks at the seam). Interconnect overlapping address space with one-to-one NAT44 to preserve bidirectional per-host reachability and clean auditing — not PAT, which hides many hosts behind one address and breaks server-initiated/inbound flows. Bridge a duplicate-AS seam with BGP Local-AS as a fast low-risk interim. Treat both as interim; schedule a re-addressing / AS-redesign workstream as the long-term fix (overlapping space also blocks Inter-AS Option C and a common IGP).\",\n  \"tradeoffs\": \"Bidirectional reachability and interoperability now vs a disruptive re-addressing/AS-redesign project later; NAT44 scales per-host cleanly while PAT saves addresses but breaks inbound and obscures audit; Local-AS is a fast bridge, AS-redesign is correct but disruptive.\",\n  \"trigger\": \"Overlapping/duplicate IP subnets or duplicate BGP ASNs between two domains being interconnected post-acquisition, where direct routing or eBGP loop-prevention breaks.\",\n  \"observable\": \"Weakly observable. The engine inventories addressing/SVIs and BGP state per device, so within a single collected estate it could in principle surface duplicate subnets or a reused ASN, but it does not cross-correlate two separate networks at a merger seam (it assesses one estate at a time). Mostly outside the evidence set.\",\n  \"recommended_action\": \"Interconnect overlapping space with NAT44 (not PAT) for bidirectional auditable reachability; bridge duplicate ASNs with BGP Local-AS as an interim; schedule re-addressing/AS-redesign as the clean long-term fix.\",\n  \"alternatives\": \"PAT (rejected: breaks inbound/server-to-server, hard to audit); immediate full re-addressing/AS-redesign (clean, disruptive); keep domains separate via Inter-AS Option B which never leaks internal prefixes.\",\n  \"citation\": \"CCDE Scenario 1 (NAT44 vs PAT, Local-AS / AS redesign); Ornio (overlap blocks Option C)\"\n },\n {\n  \"id\": \"scenario-overlay-over-incapable-transit\",\n  \"title\": \"Overlay a customer tunnel to deliver a service the provider/transport cannot carry (multicast, IPv6, encryption)\",\n  \"domain\": \"scenario-pattern\",\n  \"priority\": \"Medium\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"An SP/transport carrying only IPv4 unicast (or only dense-mode multicast) will black-hole value-added services like sparse-mode multicast, IPv6, or anything needing confidentiality — the service is incomplete and those packets are simply dropped. Rather than wait for the SP to re-equip or churn providers, run a customer overlay (GRE/DMVPN, with IPsec where confidentiality is required) across the SP and carry the needed service inside it, decoupling the service from the underlay's limits — and never silently downgrade multicast to unicast. If an Internet-backed overlay already exists for resiliency, reuse it to carry multicast/IPv6 too.\",\n  \"tradeoffs\": \"Immediate service delivery and provider independence vs added tunnel state, MTU/encapsulation overhead and an extra operational layer; relying on the SP is simpler but fails the requirement.\",\n  \"trigger\": \"A required service (sparse-mode multicast, IPv6, end-to-end encryption) riding provider/SP transport that does not support it (IPv4-unicast-only L3VPN, dense-mode-only), so the service is dropped or silently downgraded.\",\n  \"observable\": \"NOT observable. The engine does not model SP transport capability, overlays, or the multicast/IPv6/encryption requirement; the decision is requirement- and WAN-led. Outside the evidence set.\",\n  \"recommended_action\": \"Build a customer GRE/DMVPN overlay (IPsec where confidentiality is needed) over the provider transport to carry the unsupported service end-to-end; reuse an existing resiliency overlay for multicast/IPv6 rather than downgrading to unicast.\",\n  \"alternatives\": \"Have the SP add the feature (6VPE/mVPN) or change provider (both slow/costly); buy the service as a managed VAS.\",\n  \"citation\": \"CCDE Ornio/ADF scenarios (overlay-over-L3VPN / GRE over dense-only SP)\"\n },\n {\n  \"id\": \"security-firewall-ips-placement\",\n  \"title\": \"Choose firewall mode and HA up front, account for context feature loss, and place IPS behind the firewall\",\n  \"domain\": \"security\",\n  \"priority\": \"High\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"Firewall placement, mode and redundancy are structural: routed mode participates in L3 (own routing table, NAT, gateway), transparent mode bridges into a segment without re-addressing; either way a single firewall is a SPOF, so build active/standby failover or clustering (clustering for high throughput / asymmetric-flow reassembly) from the start. When virtualizing into multi-context/instances, verify required features (dynamic routing, multicast) survive — historically lost in multi-context. Place the IPS BEHIND the firewall so it inspects only already-filtered traffic, keep its management interface unreachable/unadvertised, and tune signatures to a low false-positive rate.\",\n  \"tradeoffs\": \"Routed (L3/NAT) vs transparent (drop-in) mode; failover (simple) vs clustering (throughput/asymmetry, complex); consolidation vs feature loss in contexts; inline IPS (active blocking, adds latency/availability risk) vs promiscuous IDS (detection-only).\",\n  \"trigger\": \"A single non-redundant firewall on a critical path, firewall mode mismatched to the insertion point, multi-context consolidation where dynamic routing/multicast is still required through it, IPS in front of the firewall, or an exposed IPS management interface.\",\n  \"observable\": \"NOT observable. The engine does not model firewalls, contexts, IPS, or service insertion — these are typically separate appliances not in the switch/router collection. Outside the evidence set.\",\n  \"recommended_action\": \"Select mode to fit the insertion point and deploy failover/clustering; verify feature support before enabling contexts (keep single-context where dynamic routing/multicast is needed); place IPS behind the firewall with a hidden management interface and tuned signatures.\",\n  \"alternatives\": \"Stateful L3/L4 vs NGFW by zone sensitivity; multi-context/virtual firewalls per VRF for tenant separation; promiscuous IDS-with-TCP-reset where inline risk is unacceptable.\",\n  \"citation\": \"CCDE Session 13 (firewall mode/HA, multi-context feature loss, IPS placement)\"\n },\n {\n  \"id\": \"vpn-scale-dmvpn-getvpn-selection\",\n  \"title\": \"Scale site-to-site VPN with DMVPN (or GETVPN on a private core), and select the overlay by transport/security need\",\n  \"domain\": \"vpn\",\n  \"priority\": \"High\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"Manually-meshed point-to-point IPsec/GRE does not scale to hundreds of sites and loses dynamic spoke-to-spoke and multicast. Use DMVPN (mGRE + NHRP + IPsec) so spokes register to a hub and build on-demand spoke-to-spoke tunnels carrying dynamic routing/multicast over the public Internet (and dynamic-IP spokes), tuning the IGP (hub split-horizon off, spokes peer only with hubs) and scaling with active/active ECMP/hierarchical hubs. Use GETVPN's tunnel-less group-key model for any-to-any encryption over a TRUSTED PRIVATE (MPLS/IP) core (it preserves the IP header so it cannot traverse NAT/Internet). Derive the encapsulation from what must be carried (IPv6 ⇒ an L3-capable overlay like GRE/mGRE) and whether encryption is actually required — don't add IPsec with no confidentiality requirement; rule out provider MPLS L2/L3 VPN across the public Internet.\",\n  \"tradeoffs\": \"Scale + dynamic spoke-to-spoke + multicast (DMVPN) vs its IGP-design fragility, harder troubleshooting and hub multicast replication; tunnel-less any-to-any (GETVPN) vs its private-only/NAT-incompatible constraint; gratuitous encryption burns CPU and per-endpoint SA state for no benefit.\",\n  \"trigger\": \"Many-site VPN built as static IPsec/GRE meshes (config sprawl, no spoke-to-spoke, multicast/dynamic-routing not crossing), any-to-any encryption needed over a private core, or an overlay decision ignoring the carried protocol/encryption requirement.\",\n  \"observable\": \"NOT observable. The engine does not parse VPN/overlay (DMVPN/GETVPN/GRE/IPsec) configuration or model transport type, and these typically live on WAN edge devices outside the assessed campus. Outside the evidence set.\",\n  \"recommended_action\": \"Adopt DMVPN for large Internet-backed fan-outs (mGRE/NHRP/IPsec, spoke stubs); use GETVPN only on private/MPLS transport with no NAT; pick the simplest overlay that satisfies transport+security (GRE/mGRE for IPv6 with no crypto need; add IPsec only when confidentiality is required); never propose provider MPLS VPN over the public Internet.\",\n  \"alternatives\": \"VTI/DVTI for small site counts; GRE-over-IPsec where standards-based interop is needed; SSL VPN for remote-access users; account for tunnel MTU (pre-fragment/MSS clamp).\",\n  \"citation\": \"CCDE Session 14 (DMVPN/GETVPN/GRE-IPsec/VTI); CCDE scenarios (overlay selection, DMVPN vs GETVPN)\"\n },\n {\n  \"id\": \"vpn-overlay-routing-and-split-tunnel\",\n  \"title\": \"Choose WAN/overlay routing for adjacency scale, wrap IPsec in GRE/VTI for routing+multicast, and decide split-tunneling explicitly\",\n  \"domain\": \"vpn\",\n  \"priority\": \"Medium\",\n  \"engine_actionable\": false,\n  \"design_intent\": \"On a large hub-and-spoke overlay the binding constraint is the number of routing adjacencies the hub maintains, not the route count — pick a protocol that scales in neighbour count and carries the required address family (EIGRP for moderate scale/simplicity; BGP for very high neighbour count or rich policy), make spoke edges stubs so they are never transit and don't receive queries, and size the number of hub head-ends to the supported adjacency count. Plain IPsec carries unicast IP only, so add GRE/VTI when routing adjacencies or multicast must cross the encrypted path, and preserve QoS across IPsec with IP pre-classification. Treat split-tunneling as an explicit security-vs-performance choice (default tunnel-all for inspection; permit split only on trusted hardware clients).\",\n  \"tradeoffs\": \"Scalability/policy (BGP) vs simplicity (EIGRP, Cisco-only); GRE/VTI adds routable/multicast-capable encryption at MTU/overhead cost; split-tunnel gains performance/hub-offload but bypasses central inspection and exposes the endpoint as a bridge.\",\n  \"trigger\": \"A large hub-and-spoke overlay whose IGP ignores hub adjacency limits or the carried address family (e.g. OSPFv2 for IPv6), spokes not configured as stubs, plain IPsec where routing/multicast must cross, or split-tunneling enabled broadly (including software clients).\",\n  \"observable\": \"NOT observable. Overlay routing-protocol choice, stub configuration on spokes, GRE/VTI wrapping, IP pre-classify, and split-tunnel policy are WAN-edge/VPN config the engine does not parse. Outside the evidence set.\",\n  \"recommended_action\": \"Select the overlay IGP by adjacency scale and family (EIGRP moderate, BGP high/policy), stub the spokes, size hub head-ends to the supported neighbour count; wrap IPsec in GRE/VTI for routing/multicast with QoS pre-classify; default to tunnel-all and allow split-tunnel only on trusted hardware.\",\n  \"alternatives\": \"OSPF/IS-IS poorly fit large NBMA hub-and-spoke; DVTI for simpler always-up tunnels; tunnel-all with cloud-SIG local breakout instead of split-tunnel.\",\n  \"citation\": \"CCDE Session 14 (GRE/VTI, IP pre-classify, split-tunnel); CCDE scenario (EIGRP/BGP adjacency-scale, spoke stubs)\"\n }\n]"

DOCTRINE = json.loads(_DOCTRINE_JSON)


# --------------------------------------------------------------------------- public-sourced addendum
# Distilled (original wording -- no verbatim text reproduced) from authoritative PUBLIC sources, to
# deepen the design brain at the user's request without using any paywalled/credentialed content:
#   * ipSpace.net (Ivan Pepelnjak), public blog: "A Layer-2 Network Is a Single Failure Domain",
#     "The Need for Stretched VLANs", "Complexity Belongs to the Network Edge".
#   * Cisco CCDA / campus hierarchical-design best practice (a VLAN should not span multiple access switches).
# Citations are for traceability only.
_PUBLIC_SOURCED_ADDENDUM = [
    {
        "id": "dc-bound-layer2-failure-domain",
        "title": "Bound the Layer-2 failure domain: a bridged VLAN is one fault domain",
        "domain": "dc-switching",
        "priority": "High",
        "design_intent": "A transparently-bridged Ethernet segment (a VLAN) is a single failure domain: "
        "broadcast/unknown-unicast flooding, a spanning-tree topology change, or a loop is felt by every "
        "switch and endpoint the VLAN reaches. The wider a VLAN spans, the larger the blast radius of any "
        "one L2 event -- so failure-domain SIZE, not just loop-freeness, is a first-class design constraint.",
        "observable": "Per-VLAN switch span (how many switches each VLAN touches) and whether the default "
        "VLAN 1 spans the estate -- both already computed by the engine (move_groups[].spanning_vlans).",
        "trigger": "A user VLAN spans many access/distribution switches, or VLAN 1 spans the fabric -- an "
        "oversized bridging (failure) domain.",
        "recommended_action": "Confine each VLAN to the smallest practical span (ideally one access switch / "
        "one block); route between blocks at L3 (routed access or a distribution boundary) so an L2 event "
        "stays local; prune VLAN 1 and unused VLANs off trunks; where a stretch is unavoidable, isolate it "
        "(e.g. a controlled VXLAN/overlay segment with storm-control) rather than raw end-to-end bridging.",
        "alternatives": "Keep wide L2 with aggressive storm-control/BPDU-guard and rapid-PVST/MST hardening "
        "(accepts a large blast radius); overlay (VXLAN/EVPN) to contain bridging to the edge.",
        "tradeoffs": "Smaller failure domains add L3 boundaries/addressing and can complicate workload "
        "mobility, but bound the blast radius and improve convergence and scale.",
        "citation": "ipSpace.net (Pepelnjak) 'A Layer-2 Network Is a Single Failure Domain' / 'The Need for "
        "Stretched VLANs'; Cisco CCDA hierarchical-design best practice (no VLAN across multiple access switches)",
        "engine_actionable": True,
    },
    {
        "id": "methodology-minimize-accidental-complexity",
        "title": "Minimize accidental complexity: every feature is one you must operate",
        "domain": "methodology",
        "priority": "High",
        "design_intent": "Complexity is the dominant long-run cost and failure source in networks. Every "
        "protocol, feature, platform and exception added is something to configure, secure, monitor, "
        "troubleshoot and upgrade for the life of the network. Senior design asks 'do we really need it?' "
        "before adding, consolidates on the fewest platforms that meet the requirements, and pushes any "
        "unavoidable complexity to the network EDGE where its blast radius is smallest -- keeping the core "
        "simple and fast.",
        "observable": "Not directly auto-detected: needs a feature/platform inventory judged against "
        "requirements (the engine surfaces the related evidence -- mixed IGPs, VTP, idle features -- but "
        "the 'is it justified' judgement is human).",
        "trigger": "(Judgement) protocols/features/platforms present without a requirement that justifies "
        "them; complexity concentrated in the core rather than at the edge.",
        "recommended_action": "Trace every protocol/feature/platform to a requirement; remove or avoid those "
        "without one. Consolidate on the fewest platforms that meet the needs; keep the core a simple, fast "
        "transport and concentrate policy/intelligence at the edge.",
        "alternatives": "Best-of-breed per function (more capability, more integration/operational "
        "complexity); single-stack consolidation (simpler ops, possible feature gaps).",
        "tradeoffs": "Simplicity trades some peak capability/optimization for operability, reliability and "
        "lower OpEx -- usually the right trade for an enterprise.",
        "citation": "ipSpace.net (Pepelnjak) 'Complexity Belongs to the Network Edge' / 'The Road to Complex "
        "Designs Is Paved with Great Recipes'",
        "engine_actionable": False,
    },
]
DOCTRINE.extend(_PUBLIC_SOURCED_ADDENDUM)

# --------------------------------------------------------------------- firewall-in-different-designs
# Firewall placement/insertion across the canonical design contexts (public sources, original wording):
#   * Cisco SAFE (Secure Edge / Secure Data Center) + Cisco Firewall-and-IPS CVD (perimeter/DMZ tiers).
#   * NIST SP 800-207 Zero Trust Architecture (micro-segmentation limits east-west lateral movement).
#   * Cisco Secure Firewall routed-vs-transparent & failover docs; ipSpace.net (Pepelnjak) "Stateful
#     Firewall Cluster High Availability Theater" (flow symmetry; HA is not free).
# All NON-actionable: the L1-L4 switch/router assessment does not collect firewall state, so these are
# design doctrine for the HLD security narrative / design chat -- not auto-emitted decisions (honest).
_FIREWALL_DESIGN_ADDENDUM = [
    {
        "id": "security-firewall-perimeter-dmz-topology",
        "title": "Segregate public services in a DMZ; use a screened-subnet (dual-firewall) edge for high assurance",
        "domain": "security",
        "priority": "High",
        "design_intent": "At the Internet/WAN edge the job is to keep publicly-reachable services off the "
        "trusted inside. Two canonical topologies: a single firewall with a third 'DMZ' leg (three-legged "
        "-- cheaper, but one device is the whole boundary), or a dual-firewall SCREENED SUBNET / 'sandwich' "
        "(an outer firewall facing untrusted, an inner firewall facing trusted, the DMZ between) for higher "
        "assurance and separation of duties. Public-facing systems live in the DMZ, never on the inside.",
        "observable": "Not collected by the L1-L4 assessment (firewall/edge state is out of scope) -- design doctrine.",
        "trigger": "(Design) an Internet/partner edge that publishes services, or a flat edge with public hosts inside.",
        "recommended_action": "Place public-facing services in a DMZ behind the edge firewall; for a "
        "high-assurance edge use a dual-firewall screened subnet (ideally different vendors/OSes so a single "
        "advisory can't breach both); permit only required DMZ<->inside flows; terminate remote-access VPN in "
        "its own zone, not straight onto the inside.",
        "alternatives": "Single three-legged firewall (lower cost/ops, single breach point); host public "
        "services in cloud/SaaS (moves the boundary).",
        "tradeoffs": "A dual-firewall edge costs more and adds operational surface, but bounds blast radius "
        "and separates duties between the outer and inner control.",
        "citation": "Cisco SAFE Secure Edge; Cisco Firewall-and-IPS CVD; standard DMZ / screened-subnet design practice",
        "engine_actionable": False,
    },
    {
        "id": "security-firewall-dc-eastwest-microsegmentation",
        "title": "In the data center, add east-west micro-segmentation -- a north-south perimeter is necessary but not sufficient",
        "domain": "security",
        "priority": "High",
        "design_intent": "Most data-center breaches spread EAST-WEST (server-to-server lateral movement) and "
        "never re-cross the north-south perimeter, so a perimeter firewall alone leaves the interior flat to "
        "an attacker. Modern DC security enforces policy between workloads -- micro-segmentation -- so a "
        "compromised workload cannot freely reach its neighbours (the zero-trust 'assume breach' posture).",
        "observable": "Not collected by the L1-L4 assessment (workload/firewall policy is out of scope) -- design doctrine.",
        "trigger": "(Design) a data centre whose security is perimeter-only, with unrestricted intra-tier / "
        "intra-VLAN server-to-server reachability.",
        "recommended_action": "Pair the north-south edge firewall with EAST-WEST enforcement: micro-segment "
        "with distributed/host-based firewalling, hypervisor (e.g. NSX) or fabric policy (e.g. ACI contracts), "
        "or steer inter-zone traffic through a firewall; default-deny intra-tier where feasible; drive policy "
        "from workload identity, not IP, under a least-privilege / zero-trust model.",
        "alternatives": "Perimeter-only (cheapest, large lateral blast radius); coarse VLAN/VRF ACL "
        "segmentation (simpler than per-workload micro-seg, but blunter).",
        "tradeoffs": "Micro-segmentation adds policy-authoring and lifecycle overhead, but contains lateral "
        "movement and shrinks the internal attack surface.",
        "citation": "NIST SP 800-207 Zero Trust Architecture (micro-segmentation limits lateral movement); Cisco SAFE Secure Data Center",
        "engine_actionable": False,
    },
    {
        "id": "security-firewall-flow-symmetry-insertion",
        "title": "Insert stateful firewalls on a SYMMETRIC path -- asymmetric routing breaks state, and HA is not free",
        "domain": "security",
        "priority": "High",
        "design_intent": "A stateful firewall must see BOTH directions of every flow or it drops the return "
        "packets it has no state for. So insertion and routing must guarantee flow symmetry: forward and "
        "return paths must traverse the SAME firewall (or the same active unit of an HA pair). Asymmetric "
        "routing is the classic stateful-firewall killer, and active/active clustering does not deliver "
        "'free' stateful HA -- state sync and flow pinning have real limits. Complements "
        "security-firewall-ips-placement (mode/HA): even a correctly-moded HA pair fails on an asymmetric path.",
        "observable": "Not collected by the L1-L4 assessment (firewall/path-symmetry state is out of scope) -- design doctrine.",
        "trigger": "(Design) equal-cost or multi-homed paths around a stateful firewall; an HA pair assumed "
        "to give stateful failover without state-sync/symmetry analysis.",
        "recommended_action": "Insert the firewall on the symmetric path (inline routed/transparent, or "
        "one-arm with PBR/VRF that forces both directions through it); avoid ECMP that lets return traffic "
        "bypass it; on HA pairs verify connection-state sync and divert/pin asymmetric flows to the active "
        "unit; test that failover preserves or gracefully re-establishes state.",
        "alternatives": "Stateless ACLs where statefulness isn't required (tolerate asymmetry); explicit "
        "per-flow steering / service-chaining to force symmetry.",
        "tradeoffs": "Enforcing symmetry constrains routing/load-balancing freedom, but stateful inspection "
        "is unreliable -- silently dropping flows -- without it.",
        "citation": "Cisco Secure Firewall routed/transparent & failover docs; ipSpace.net (Pepelnjak) 'Stateful Firewall Cluster High Availability Theater'; asymmetric-routing design guidance",
        "engine_actionable": False,
    },
]
DOCTRINE.extend(_FIREWALL_DESIGN_ADDENDUM)


# ------------------------------------------------------- DC-fabric / cloud reference-corpus addendum
# Distilled (ORIGINAL wording -- no verbatim source text reproduced) from the engagement reference
# corpus the user supplied, to teach the design brain the modern data-center TARGET vocabulary behind
# the real [HISTORY-REDACTED] Solution Design (Nexus 9000 VXLAN BGP-EVPN Multi-Site fabric). Sources: ipSpace.net
# (Pepelnjak/Dutt/Krattiger -- EVPN/VXLAN, leaf-spine, Multi-Site/DCI, active-active DC, private cloud,
# load-balancing, sizing; knowledge/ideas usable, verbatim text is not), Cisco DC/EVPN design guides,
# the [HISTORY-REDACTED] SDD/NRFU, and public IETF RFCs. Load-bearing standards facts were web-verified against
# primary sources (RFC 7348/7432/8365/9135/9136/7938/6513/4610). Citations are for traceability only.
# All are engine_actionable=False DOCTRINE (the L1-L4 assessment collects no fabric/cloud/service
# state) EXCEPT dc-multisite-interconnect-fabrics-as-isolated-sites, a requirement-gated design choice
# surfaced via design_advisor._NEEDS (like the other DC-fabric choices). Honest non-actionability is
# locked by tests/test_design_blueprint.py::test_dc_corpus_doctrine_present_cited_and_honest +
# ::test_every_engine_actionable_principle_is_emitted.
_DC_CORPUS_ADDENDUM = json.loads(r"""
[
 {
  "id": "dc-fabric-vxlan-evpn-control-plane",
  "title": "A VXLAN fabric needs a BGP-EVPN control plane built on L3VPN machinery, not flood-and-learn",
  "domain": "dc-fabric",
  "priority": "High",
  "design_intent": "VXLAN is only a MAC-in-UDP data-plane encapsulation: it carries an Ethernet frame across an IP transport but has no native way to map a customer MAC to the right VTEP or to suppress BUM flooding, so the legacy multicast-underlay + dynamic-MAC-learning answer re-imports classic bridging's scaling and flooding problems into the overlay. The target pattern pairs the VXLAN data plane with an explicit BGP-EVPN control plane (l2vpn evpn AFI) that ADVERTISES MAC/IP-to-VTEP reachability, reusing the proven RD/RT/route-reflector constructs of MPLS L3VPN (RT-2 = MAC/IP, RT-3 = per-VNI flood list, RT-5 = IP prefix) so engineers get multi-tenancy and address mobility without inventing new scaffolding. 'VXLAN with dynamic MAC learning only' is a recognizable anti-pattern to flag whenever a fabric target state is proposed.",
  "observable": "Not collected -- the L1-L4 engine has no visibility into EVPN/VXLAN/VTEP/VNI/RD/RT state or overlay learning mode; it sees device inventory, VLANs, STP/VTP, FHRP, routing adjacencies and IGMP queriers, but not the intended fabric.",
  "trigger": "(Design) any target-state introducing VXLAN/overlay transport, or a brownfield being assessed for migration onto an IP fabric, where the overlay's MAC-learning/flooding/tenancy strategy is unspecified.",
  "recommended_action": "Specify BGP-EVPN (l2vpn evpn AFI) as the fabric control plane with RD per VTEP/loopback and RT-based tenant membership (auto-derived from loopback+VNI where supported); reuse the customer's existing BGP operational model and route reflection rather than a new protocol; treat multicast-underlay flood-and-learn as a flooding/scaling risk to call out in the HLD.",
  "alternatives": "Multicast-underlay flood-and-learn VXLAN (legacy, discouraged); controller-programmed overlays (e.g. NDFC/SDN) that hide BGP; classic VLAN/STP L2 (the brownfield it replaces).",
  "tradeoffs": "A control-plane overlay adds BGP-EVPN operational skill and configuration surface (and disciplined RT policy -- misconfigured RTs leak tenants) versus the deceptively 'simple' flood-and-learn; the payoff is bounded flooding, deterministic MAC reachability and host mobility without the bridging blow-up.",
  "citation": "ipSpace.net 'VXLAN and EVPN 101' (Pepelnjak) / 'EVPN Basics' (Dutt); RFC 7348 (VXLAN), RFC 7432 (BGP MPLS-Based EVPN), RFC 8365 (NVO/EVPN-VXLAN), RFC 4364 (BGP/MPLS L3VPN) | standards note: RFC 7432 is BGP-MPLS EVPN (route types 1-4); the VXLAN data-plane binding is RFC 8365 (NVO), and EVPN IP-Prefix (RT-5) is RFC 9136.",
  "engine_actionable": false
 },
 {
  "id": "dc-fabric-underlay-overlay-separation",
  "title": "Separate a simple IP underlay from the EVPN overlay; let one eBGP session carry both",
  "domain": "dc-fabric",
  "priority": "Medium",
  "design_intent": "A clean EVPN-VXLAN fabric is two decoupled layers: a simple, fast-converging IP underlay whose only job is loopback-to-loopback (VTEP) reachability across the leaf-spine CLOS, and an EVPN overlay that rides on top to carry tenant MAC/IP state, so transport and control-plane reachability evolve independently and the spines stay tenant-agnostic transit. In the DC the deployment can be radically simpler than the SP IGP+iBGP model: if the underlay already runs eBGP leaf-to-spine, the same single eBGP session can also carry the EVPN address family and the spines naturally behave like route reflectors because every leaf peers with them. Practical rules fall out: do NOT next-hop-self EVPN routes (keep the egress VTEP as next hop), let spines retain route targets they don't import (RR-like), and auto-derive RD/RT.",
  "observable": "Not collected -- fabric underlay/overlay BGP topology, AS layout and next-hop policy are outside L1-L4 scope; the engine sees OSPF/IS-IS/EIGRP/BGP adjacency PRESENCE but not the intended fabric scheme.",
  "trigger": "(Design) choosing the routing model for a new leaf-spine fabric, or deciding how to carry overlay reachability when the customer already runs (or wants) eBGP in the underlay.",
  "recommended_action": "Specify an IP-only underlay for VTEP reachability plus an EVPN overlay; where the underlay is eBGP, run a single eBGP session per leaf-spine adjacency carrying both AFIs, keep next-hop-unchanged for EVPN routes, and let spines act as RR-equivalent transit with auto-derived RD/RT.",
  "alternatives": "Traditional IGP (OSPF/IS-IS) underlay + iBGP/route-reflector overlay; controller-managed fabric that abstracts the BGP design entirely.",
  "tradeoffs": "An eBGP-only underlay+overlay is operationally uniform and self-documenting (AS-path loop prevention, no separate IGP) but needs careful next-hop and RT handling; the SP-style IGP+iBGP+RR model is more familiar to enterprises but adds a second protocol to operate.",
  "citation": "ipSpace.net 'EVPN Basics' (Dutt) BGP-models section / 'VXLAN and EVPN 101'; RFC 7938 (BGP for DC routing), RFC 8365 (EVPN-VXLAN NVO)",
  "engine_actionable": false
 },
 {
  "id": "dc-fabric-distributed-anycast-gateway-irb",
  "title": "Prefer a distributed anycast gateway with symmetric IRB over centralized spine routing",
  "domain": "dc-fabric",
  "priority": "High",
  "design_intent": "Where inter-subnet routing happens in an EVPN fabric is a first-order decision. Centralized routing (an external box or active/standby VRRP on the spines) forces all inter-VLAN traffic through one chokepoint, hairpins local east-west flows up to the spine, and leaves each VLAN one fabric-wide failure domain. The target is a distributed anycast gateway: every leaf owns the same gateway IP and MAC for a subnet and routes locally with integrated routing and bridging (IRB), so a host's default gateway is always one hop away. Symmetric IRB (route on ingress leaf, bridge across a per-VRF transit segment, route on egress leaf) is near-optimal because subnets need exist only on leaves with active endpoints -- shrinking the L2 footprint -- whereas asymmetric (ingress-only) IRB needs every VRF VLAN on every participating leaf. EVPN ARP/ND suppression then turns broadcast ARP into local proxy answers built from the RT-2 {VNI,MAC,IP} bindings, sharply cutting overlay broadcast (caveat: suppression and BUM-drop depend on the host already being learned, so genuinely silent hosts and non-suppressed families like ND can break under aggressive flood reduction).",
  "observable": "Partially adjacent -- the engine sees today's FHRP gateway placement, per-VLAN switch span and SVI/L3-forwarding, but not the EVPN anycast-gateway / IRB / ARP-suppression target state.",
  "trigger": "(Design) introducing inter-VLAN routing over a fabric, or a brownfield with a centralized/aggregation-pair default gateway (e.g. FHRP at a collapsed core) being considered for fabric migration; large flat subnets being migrated into VNIs.",
  "recommended_action": "Specify a distributed anycast gateway (same gateway IP/MAC on all leaves) with symmetric IRB so subnets are confined to leaves with active endpoints; enable ARP (and, where supported, ND) suppression per VNI; before turning off or dropping BUM flooding, verify there are no silent hosts and confirm vendor support; avoid centralized spine/external gateways unless an external service (firewall/LB) genuinely must sit in the inter-subnet path.",
  "alternatives": "Centralized routing on spines (active/standby VRRP or anycast); external/firewall routing for inter-VLAN; asymmetric (ingress-only) IRB where silicon or operational simplicity favours it; leave BUM flooding on (tolerant of silent hosts) with ingress replication.",
  "tradeoffs": "Distributed anycast routing optimizes east-west paths and confines failure domains but demands IRB-capable silicon (symmetric IRB/RIOT is not on every chipset) and more per-leaf L3 config; centralized routing is simpler and naturally inserts firewalls/LBs but chokepoints and hairpins traffic.",
  "citation": "ipSpace.net 'Routing in EVPN Fabrics' / 'EVPN Basics' (Pepelnjak/Dutt); RFC 7432 / RFC 9135 (EVPN integrated routing and bridging); Cisco/Arista distributed-anycast-gateway design guides",
  "engine_actionable": false
 },
 {
  "id": "dc-fabric-bum-replication-ingress-default",
  "title": "Default BUM replication to ingress replication; reserve a multicast underlay for heavy multi-destination load",
  "domain": "dc-fabric",
  "priority": "Medium",
  "design_intent": "Even with a control plane, an overlay must still deliver broadcast/unknown-unicast/multicast (BUM), and EVPN offers two strategies with opposite trade-offs. Ingress (head-end) replication keeps the underlay simple (no PIM, no per-VNI group mapping) and is the most broadly supported model, at the cost of the ingress VTEP duplicating each BUM frame to every interested remote VTEP -- which scales poorly as VTEP count or multi-destination volume rises. An L3 multicast underlay maps each VNI's BUM to a PIM group and is efficient for heavy multi-destination workloads, but adds PIM design, box-by-box VNI-to-group mapping and harder troubleshooting. The default stance is ingress replication unless a QUANTIFIED multicast/broadcast load justifies the multicast underlay's operational cost.",
  "observable": "Partially adjacent -- the engine sees IGMP-querier / multicast-risk evidence for the current L2 network (a soft hint at multicast intensity), but not the overlay BUM-replication mode.",
  "trigger": "(Design) an EVPN target where BUM/multicast volume or VTEP scale must be sized, or a multicast-heavy application profile is present in the brownfield evidence.",
  "recommended_action": "Default the EVPN target to ingress replication for BUM; only specify an L3 (PIM) multicast underlay when measured multi-destination/multicast load or VTEP scale makes head-end replication inefficient, and document the per-VNI group mapping if so.",
  "alternatives": "Ingress/head-end replication (default); L3 PIM multicast underlay (heavy multicast); dropping BUM entirely with ARP/ND suppression where silent-host risk is acceptable.",
  "tradeoffs": "Ingress replication minimizes underlay complexity and troubleshooting surface but burns ingress-VTEP CPU/bandwidth as VTEP count and BUM volume grow; a multicast underlay scales BUM efficiently but imports PIM design, per-VNI mapping toil and harder fault isolation.",
  "citation": "ipSpace.net 'EVPN Basics' (Dutt) multi-destination-frame section; RFC 7432 (Inclusive Multicast Ethernet Tag / BUM handling), RFC 8365 (NVO replication options)",
  "engine_actionable": false
 },
 {
  "id": "dc-fabric-clos-sizing-oversubscription-ecmp",
  "title": "Size a leaf-spine Clos by an explicit oversubscription ratio and keep the fabric control plane deliberately dumb",
  "domain": "dc-fabric",
  "priority": "High",
  "design_intent": "A leaf-and-spine fabric is a folded multi-stage Clos: every leaf connects to every spine so any endpoint is the same small, fixed number of hops (and bandwidth) from any other, replacing the bandwidth- and port-count-driven 3-tier hierarchy with a flatter design that grows by adding identical building blocks instead of forklifting bigger chassis. Make the contention explicit: state a downlink:uplink oversubscription ratio up front (a 3:1 leaf is 48x10GE edge against 4x40GE uplinks) and mechanically derive leaf-port split, leaf count, leaf-to-spine link count and spine count from the edge-port target and that ratio. Because the graph is regular, the control plane should be as uniform and feature-free as possible -- one protocol, no areas, no summarization, no clever knobs (eBGP-as-IGP with a shared spine AS and a private per-leaf AS is the simplest); a correct design needs neither inter-leaf nor inter-spine links, and needing them signals drift.",
  "observable": "Not collected -- leaf/spine roles, per-link bandwidth, oversubscription ratios, ECMP width, AS layout and the intended Clos build are target-state facts an L1-L4 brownfield assessment does not gather (it sees device/VLAN/adjacency inventory, no port-speed census).",
  "trigger": "(Design) a DC fabric being sized, or a brownfield still on a 3-tier core/aggregation/access hierarchy whose oversubscription and chassis dependence limit east-west growth; any review where the committed oversubscription is undeclared.",
  "recommended_action": "Adopt a folded 3-stage Clos sized to the edge-port count on uniform fixed-config switches; state the target oversubscription ratio and derive leaf/spine port and device counts from it (tighten the ratio or add spines for bandwidth-heavy workloads); run one protocol fabric-wide (eBGP-as-IGP: single-AS spines + per-leaf AS), avoid areas/summarization/redistribution, prefer point-to-point routed (optionally unnumbered/IPv6-LLA) core links, and design so no inter-spine/inter-leaf links are required.",
  "alternatives": "Stay 3-tier when port/throughput limits genuinely require modular chassis (or when only two switches are needed at all); OSPF/IS-IS underlay (fine, but tempts operators into areas/summarization); over-provision uniformly to the highest speed (simple, costly).",
  "tradeoffs": "Flattening trades the chassis vendor's internal redundancy for many-small-boxes simplicity and horizontal scale, and assumes high-radix fixed switches plus disciplined automation; a tighter ratio buys less contention at the cost of more uplinks/spines/optics, a looser ratio saves ports but risks elephant-flow/microburst congestion.",
  "citation": "ipSpace.net 'Leaf-and-Spine Fabric Designs' workshop (Clos 101; Physical Design Process; Routing Protocol Selection; Unnumbered Interfaces) and 'Data Center Network Reference Architecture'; Charles Clos (1953) multistage switching theory | RFC 7938 (BGP for large-scale DC); oversubscription is the downlink:uplink BANDWIDTH ratio (port-count N:M equals it only at uniform speed).",
  "engine_actionable": false
 },
 {
  "id": "dc-fabric-ecmp-equal-capacity-no-core-summarization",
  "title": "Keep fabric ECMP equal-capacity: no LAG/parallel-slow uplinks and never summarize in the Clos core",
  "domain": "dc-fabric",
  "priority": "Medium",
  "design_intent": "A routed Clos relies on wide, 5-tuple-hashed equal-cost multipath across the spines, and ECMP assumes every equal-cost path has equal CAPACITY. Three habits silently break that assumption: bundling leaf-to-spine links as a LAG, running several parallel lower-speed links as separate ECMP members, or summarizing reachability in the core. In each case a single member failure leaves the path COST unchanged while real capacity drops, so traffic keeps being hashed onto a now-undersized path and congests -- or, with summaries, lands on a spine that has no specific route to the destination leaf and black-holes. This is the explicit COUNTER-case to the classic 'summarize at the aggregation boundary' instinct, which is correct in a hierarchy but harmful in a Clos.",
  "observable": "Not collected -- leaf/spine roles, per-link bandwidth, LAG-vs-routed fabric uplinks and ECMP width are outside L1-L4 scope; the engine sees routing adjacencies but cannot tell that an equal-cost path lost capacity.",
  "trigger": "(Design) fabric uplinks built with LAG bundles or multiple parallel slower links between leaf and spine, or a fabric that advertises summaries/default from spines toward leaves.",
  "recommended_action": "Use single higher-speed leaf-to-spine links (40/100GE) rather than LAGs or parallel slower links so a member loss is visible to routing as a path loss; carry full fabric reachability with NO core summarization so every spine has a specific route to every leaf; rely on wide per-flow ECMP on the ingress switch.",
  "alternatives": "LAG or parallel sub-speed members plus core summarization reduce link/route count but then require extra inter-spine links to repair the asymmetry they create -- added complexity the design should avoid.",
  "tradeoffs": "Single high-speed links and a fully-specific core cost more optics and routing state than LAGs/summaries, but preserve the ECMP capacity invariant so failures degrade gracefully instead of congesting or black-holing; this deliberately contradicts the generic summarize-at-aggregation rule.",
  "citation": "ipSpace.net 'Leaf-and-Spine Fabric Designs' workshop ('Link Aggregation On Leaf-to-Spine Links Is Bad', 'Parallel L3 Leaf-to-Spine Links Are Bad', 'Route Summarization is Bad')",
  "engine_actionable": false
 },
 {
  "id": "dc-fabric-fabric-drops-bpdu-single-l2-handoff",
  "title": "An EVPN/VXLAN fabric silently drops STP BPDUs -- the legacy L2 handoff must be one logical link per VLAN, with the VTEP as STP root",
  "domain": "dc-fabric",
  "priority": "High",
  "design_intent": "During brownfield-to-fabric coexistence the VXLAN fabric does NOT run spanning tree across the overlay, so the classic safety net that blocks a second parallel L2 path is absent: a second handoff for the same VLAN is an instant bridging loop with no STP to break it. Where standard L2 ports still connect hosts or legacy switches at the fabric boundary, the VTEP/leaf must own the spanning-tree root and guard the edge so a downstream loop or rogue switch cannot destabilize the segment. This is sharper than a generic 'avoid L2 loops' note: the non-obvious point is that STP gives NO protection on the inter-domain handoff because the fabric eats the BPDUs.",
  "observable": "Adjacent and partly observable -- the engine computes per-VLAN switch span (move_groups[].spanning_vlans), STP mode/root/blocked ports (protocol_health), edge-port BPDU-guard posture (config-hygiene) and link cut-edges, so it can flag a VLAN that spans multiple candidate handoff edges or a legacy STP-root that won't match the fabric edge; the fabric/overlay itself is not collected.",
  "trigger": "(Migration) a move-group bridges a legacy VLAN into the fabric AND that VLAN is seen on more than one inter-domain handoff/uplink (or the legacy side retains redundant uplinks into the new fabric); leaf edge ports facing hosts or legacy switches during/after migration.",
  "recommended_action": "Enforce exactly one logical L2 connection per VLAN between legacy and fabric; configure the VTEP as STP root for all its L2 segments and enable BPDU Guard on all edge ports plus MAC-move violation logging on every leaf; enable South-Bound Loop Detection; verify STP root per VLAN before bridging.",
  "alternatives": "Stage a brief dual-path window only under tight change control with one side administratively down; carry the legacy L2 over a controlled VXLAN segment with storm-control instead of raw parallel bridging.",
  "tradeoffs": "A single logical handoff removes the loop risk but forfeits L2 path redundancy across the boundary during coexistence; making the VTEP the root and guarding edges adds config but contains any downstream L2 fault to the access port.",
  "citation": "[HISTORY-REDACTED] SDD Migration Approach ('only a single logical layer 2 connection per VLAN ... the EVPN VXLAN fabric is not forwarding any STP BPDUs'), 'Dot1Q VLAN and Spanning Tree Design', 'MAC Move Violation'",
  "engine_actionable": false
 },
 {
  "id": "dc-fabric-multicast-underlay-now-trm-later",
  "title": "For a media fabric, get the underlay multicast (PIM-ASM + Anycast-RP + IGMP-snooping) right at cutover even when Tenant Routed Multicast is deferred",
  "domain": "dc-fabric",
  "priority": "High",
  "design_intent": "A media/IPTV network depends on multicast, so a multicast VLAN migrated into the fabric without a fabric SVI and IGMP snooping is stranded at cutover -- an active L2 segment whose multicast simply stops. Even when overlay Tenant Routed Multicast (TRM) is planned for a later phase, the underlay PIM-ASM + Anycast-RP (per RFC 4610) and per-VNI IGMP snooping must be correct from day one so multicast is not lost now and TRM can be enabled later, including migrating an existing external RP into the fabric Anycast-RP. Because the engine evidences one IGMP querier per active L2 segment, it can flag a querier-bearing VLAN that would land in the fabric without snooping/SVI -- sharper than a generic 'enable multicast' note.",
  "observable": "Partly observable -- the engine evidences IGMP queriers per VLAN, querier-gap VLANs, multicast risks and per-VLAN switch span, so it can flag a multicast VLAN heading into the fabric without provisioning; the target underlay PIM/Anycast-RP/TRM config is not collected.",
  "trigger": "(Migration) VLANs/segments carrying multicast (IGMP queriers observed; IPTV/media segments) are migrated before TRM is enabled, or a multicast VLAN would be instantiated in the fabric without a querier/SVI.",
  "recommended_action": "Ensure every active multicast VLAN is instantiated in the fabric WITH IGMP snooping; configure the underlay with PIM-ASM and PIM Anycast-RP; plan an external-RP-to-fabric-Anycast-RP coexistence for the TRM phase; for mixed/non-TRM platforms consider L2-mode TRM.",
  "alternatives": "Enable TRM from day one (fabric goes live later but no multicast phasing risk); external vs distributed Anycast-RP placement; L2-mode TRM for non-TRM-capable leaves.",
  "tradeoffs": "Deferring TRM lets the fabric go live sooner but risks stranded multicast if active querier VLANs are not pre-provisioned; getting the underlay RP right early is cheap insurance against a media outage at cutover.",
  "citation": "[HISTORY-REDACTED] SDD 'Underlay Multicast (PIM-ASM & PIM Anycast RP)', 'Tenant Routed Multicast' ('considered for the future Deployment'), 'L3 TRM PIM RP Placement'; RFC 4610 (Anycast-RP) | TRM routed-multicast control plane is ngMVPN (RFC 6513/6514).",
  "engine_actionable": false
 },
 {
  "id": "dc-multisite-interconnect-fabrics-as-isolated-sites",
  "title": "Interconnect EVPN fabrics as isolated sites (Multi-Site at the border-leaf), not one stretched Multi-Pod fabric",
  "domain": "dc-multisite",
  "priority": "High",
  "design_intent": "When joining VXLAN/EVPN fabrics across pods or data centers, the central decision is whether the result is ONE fabric ('Multi-Pod' = a single end-to-end control plane, underlay, BUM domain and VNI space) or several interconnected-but-isolated fabrics ('Multi-Site', where a Border Gateway terminates and re-originates the overlay so each site keeps its own underlay and BUM domain). Multi-Pod is operationally simpler but shares one fate: a single control-plane defect, underlay event or broadcast storm ripples through every pod. Multi-Site deliberately segments those planes at the Border Gateway so a fault is contained to one site. Inter-site links must land on dedicated border-LEAF nodes, never the spine -- partial spine meshing destroys traffic symmetry and a spine gray-failure then degrades roughly half of all flows -- and each site must be its own control-plane failure domain joined by a path-vector protocol (eBGP) so a routing fault is naturally bounded; never share one link-state area or chassis-virtualization across the WAN, and explicitly design the 'all inter-site links down' and split-brain-management cases.",
  "observable": "Mostly not collected -- EVPN/VXLAN/Border-Gateway/Multi-Site state and fabric roles are out of scope. The engine CAN observe a single IGP/link-state domain or absence of an eBGP boundary (routing_neighbors) and multi-site VLAN span, so it can flag a control plane that is not segmented across sites; it cannot judge circuit diversity or chassis internals.",
  "trigger": "(Design) two or more L2/L3 fabrics or pods are joined, OR a single OSPF/IS-IS area / single shared (virtual-chassis) control plane spans two sites, OR the brownfield already stretches one bridging/flooding domain across sites with no containment boundary.",
  "recommended_action": "Target a Multi-Site interconnect: terminate each site's overlay on a redundant Border-Gateway (anycast) cluster at dedicated border-leaf nodes, keep underlays per-site (no underlay extension between sites), run eBGP between site overlays, and enforce per-site BUM/storm-control at the gateway; terminate the IGP at each site boundary so a control-plane fault is contained per site; design and test the total-inter-site-link-loss and split-brain scenarios. Reserve a single stretched (Multi-Pod) fabric for pods within one facility on reliable links where shared fate is acceptable.",
  "alternatives": "A single stretched (Multi-Pod) fabric for tightly-coupled pods in one facility; full spine-to-spine meshing IF interconnecting at the spine (never partial); Super-spine for very large east-west scale.",
  "tradeoffs": "Multi-Site adds Border-Gateway hardware, per-site edge state and an extra control-plane hop, but contains a fault, broadcast storm or gray failure to one site; Multi-Pod is simpler and cheaper but makes the interconnected fabrics one failure domain.",
  "citation": "ipSpace.net 'Multi-Site and Multi-Pod Fabrics' / 'Using VXLAN and EVPN in Multi-Pod and Multi-Site Fabrics' (Krattiger/Pepelnjak); Cisco VXLAN EVPN Multi-Site Design (c11-739942); IETF draft-ietf-bess-dci-evpn-overlay",
  "engine_actionable": true
 },
 {
  "id": "dc-multisite-route-server-and-anycast-bgw",
  "title": "At scale, replace full-mesh inter-site peering with a Route Server, and collapse the Border Gateway onto the spine deliberately",
  "domain": "dc-multisite",
  "priority": "Medium",
  "design_intent": "With more than a few sites, a full mesh of Border-Gateway eBGP sessions becomes O(n^2) operational complexity, so a redundant Route-Server pair (eBGP route-reflector behaviour with next-hop-unchanged and route-target rewrite, kept out of the data path) becomes the star point for the whole inter-site EVPN control plane and the place to reconcile mismatched per-site ASNs. A small/medium site may also collapse the Anycast Border Gateway onto the spine to save hardware -- a valid choice, but one with consequences: there is then no direct spine-to-spine path, so inter-BGW designated-forwarder synchronization must traverse the site-internal leaves and the Route Server, and exit-point scale becomes tied to spine count. Make both the Route-Server-vs-full-mesh and the BGW-on-spine-vs-border-leaf calls explicitly, not by default.",
  "observable": "Not collected -- inter-site BGW/Route-Server topology, site count, DF-election paths and AS layout are target-state design inputs an L1-L4 brownfield assessment does not hold.",
  "trigger": "(Design) a Multi-Site fabric with more than ~3 sites where inter-site eBGP would otherwise be full-mesh, or a small/medium site where dedicated border-leaf BGWs are not warranted.",
  "recommended_action": "Deploy redundant Route Servers reachable from every BGW (require EVPN AF, VPN-route reflection, next-hop-unchanged and RT-rewrite; keep them out of the data path); where border leaves are not justified, use spine-as-Anycast-BGW with a Site-ID and per-L2VNI DF election, providing the BGW-to-BGW control path via iBGP to the Route Server, and scale out to up to ~4 A-BGWs per site.",
  "alternatives": "Full-mesh eBGP between BGWs (acceptable only at small site count); dedicated border-leaf A-BGW (preferred where separate border leaves exist); vPC BGW (only when external connectivity is needed on the BGW); a Super-spine route-server role for very large scale.",
  "tradeoffs": "A Route Server adds two devices and an extra control-plane hop but removes O(n^2) peering and enables RT-rewrite across mismatched ASNs; spine-as-BGW saves devices but makes BGW sync indirect and ties exit-point scale to spine count.",
  "citation": "[HISTORY-REDACTED] SDD 'Anycast Border Gateway' / 'BGW on Spine' / 'Route Server' / 'Next Hop unchanged' / 'Route-target rewrite'; corroborated by Cisco VXLAN EVPN Multi-Site design",
  "engine_actionable": false
 },
 {
  "id": "dc-multisite-prefer-l3-dci-bound-any-stretch",
  "title": "Prefer L3 DCI; if a VLAN must stretch, bound its flooding at the LAN-WAN edge and never attach it through a switch",
  "domain": "dc-multisite",
  "priority": "High",
  "design_intent": "A Data Center Interconnect is a design problem before a technology: an L3 interconnect (per-zone path isolation via multi-VRF or MPLS/EVPN) keeps each site a separate broadcast and failure domain, while an L2 DCI extends one broadcast/failure/availability domain across sites and imports split-brain, long-distance flooding, traffic trombones and WAN-wide spanning-tree exposure. An any-to-any L2 WAN service (VPLS/E-LAN/pseudowire) collapses every connected site into one STP/broadcast/security/multicast domain, so a site must attach through a ROUTER (or routed sub-interface), never a switch, and a stretched-VLAN DCI is a last resort. When a stretch is genuinely required (stretched cluster, VM mobility), the edge device must actively contain it: a single forwarding device or MLAG pair per VLAN at the LAN-WAN boundary, storm-control and unknown-unicast suppression on the DCI edge, no STP across the WAN, and VXLAN/EVPN with ARP suppression rather than raw bridging -- driven down by application architecture and global load balancing so the L2 stretch shrinks or disappears.",
  "observable": "Partly observable in-fabric -- per-VLAN switch span, VRF/segmentation list, STP mode/blocked ports and VTP mode let the engine flag a VLAN spanning many switches/sites with no isolation boundary; the OTV/VXLAN/VPLS transport and which port faces a carrier L2 service are NOT collected, so the DCI-attachment specifics stay narrative.",
  "trigger": "(Design / partly observed) an L2 segment / VLAN spans more than one site or DCI link, a 'stretched cluster / VM mobility' requirement drives bridging across a WAN, or an L2 WAN service (VPLS/E-LAN/pseudowire/stretched VLAN) is terminated on a switch rather than a router.",
  "recommended_action": "Default to L3 DCI with path isolation (multi-VRF for a few zones, MPLS-VPN/EVPN to scale) and a distinct IP prefix per site; use routers/routed interfaces as the attachment point to any any-to-any L2 service so each site keeps its own STP/broadcast/security/multicast domain; where a VLAN must stretch, place one forwarding device or MLAG pair per VLAN at the boundary, do not extend STP across the WAN, enable storm-control and unknown-unicast suppression, and prefer VXLAN/EVPN-with-ARP-suppression (split-horizon) over raw bridging; treat stretched-VLAN DCI as a last resort with an explicit split-brain mitigation.",
  "alternatives": "Routed DCI with EVPN/L2-extension overlays instead of raw bridging; multiple VPLS instances to split the bridge in large networks; P2P pseudowires on routers for special needs only; accept stretched-L2/DCI only where the application truly requires identical L2 across sites.",
  "tradeoffs": "L2 transparency / workload mobility across sites vs a single shared STP/broadcast/security/multicast fault domain and split-brain DCI risk; router-attachment (fault containment, an extra L3 hop) vs switch-attachment (simple bridging, fleet-wide blast radius).",
  "citation": "ipSpace.net 'Data Center Interconnects' / 'External Routing with Layer-2 DCI' (Pepelnjak) and 'Choose the Optimal VPN Service' (E-LAN/VPLS usage; stretched-VLAN-DCI 'disaster'); OTV / IETF EVPN",
  "engine_actionable": false
 },
 {
  "id": "dc-multisite-mobility-trombone-and-split-brain",
  "title": "A stretched/mobile subnet must engineer ingress, egress and statefulness deliberately, or accept trombones and split-brain",
  "domain": "dc-multisite",
  "priority": "High",
  "design_intent": "Moving a server across a stretched VLAN does not move its conversations: clients, peer servers, storage, load balancers and firewalls stay put, so traffic 'trombones' across the DCI and stateful devices in the path break on asymmetry. The outbound leg is fixable by localizing the first hop -- an anycast gateway (common in EVPN) or active-active FHRP with FHRP filtering on the DCI so each site uses its LOCAL gateway, never one remote active FHRP. The inbound leg is not a network trick: the external prefix is still advertised from the old site, so without a routing signal (a more-specific host route injected into BGP, or DNS/anycast service-location) inbound traffic keeps landing at the origin and trombones back. Worse, a firewall/load-balancer cluster STRETCHED across sites builds one inter-site failure domain that split-brains on DCI loss and pins flows to the box holding state -- making ingress/egress optimization impossible. The durable answer is a scale-out application reachable by anycast/DNS with L3 DCI, keeping stateful service clusters site-local as independent pairs.",
  "observable": "Partly observable -- the engine knows per-VLAN switch span, FHRP presence per gateway VLAN and SVI/L3-forwarding placement, so it can flag a gateway VLAN that spans multiple switches/sites yet has its first-hop gateway concentrated on one (non-distributed) device as an egress-hairpin candidate; it cannot see ingress BGP host-routes/DNS/LISP, load balancers, firewalls, cluster state or live traffic paths.",
  "trigger": "(Design / partly observed) VM mobility / workload migration over a VLAN stretched across switches or sites, a stretched VLAN whose first-hop gateway is a single non-distributed FHRP, or a firewall/LB/HA cluster whose members sit in different sites or sync state across the DCI.",
  "recommended_action": "Localize egress with an anycast gateway or active-active FHRP plus FHRP filtering on the DCI so each site forwards via its local gateway; engineer ingress explicitly (host-route injection or DNS/anycast), or prefer DNS/anycast-reachable scale-out services over a single mobile IP; keep stateful firewall/LB clusters within a single site as independent pairs -- do not stretch them across the DCI -- and provide inter-site continuity at the application layer; if stateful services must front a stretched subnet, document the split-brain and flow-symmetry failure modes as accepted risk.",
  "alternatives": "Single central gateway with accepted DCI hairpin (simplest, suboptimal); per-site independent clusters with application-level redirection (preferred) vs an active/standby stretched cluster with stateful failover (rejected: failure domain + split-brain); global-LB/VIP-per-site instead of stretched L2.",
  "tradeoffs": "Distributed/anycast gateways and host-route injection optimize the path but add control-plane state and config; site-local independent stateful pairs sacrifice the illusion of one seamless cluster and may need app-level continuity work, but eliminate the cross-site blast radius and split-brain class.",
  "citation": "ipSpace.net 'Designing Active-Active and Disaster Recovery Data Centers' / 'Data Center Interconnects' (Pepelnjak) -- ingress/egress flows, anycast gateway, stretched stateful services / split-brain; FHRP localization/filtering",
  "engine_actionable": false
 },
 {
  "id": "dc-multisite-dr-and-active-active-from-rto-rpo",
  "title": "Drive DR/active-active from business RTO/RPO and failover headroom, not from stretched-L2 heroics",
  "domain": "dc-multisite",
  "priority": "High",
  "design_intent": "Disaster recovery and active-active are business decisions before network ones: the budget, per-application acceptable downtime, RTO and RPO dictate the replication mechanism (synchronous vs asynchronous storage replication, live DB replica, or log shipping) and how much warm infrastructure must already stand at the second site. Because a full data-center loss is a rare (roughly once-a-decade) event, building permanent stretched-VLAN / long-distance live-VM-mobility machinery to shave it is usually over-engineering that becomes standing technical debt paid every day. The disciplined path is warm data already present at a tested, automated DR site, with any stretched-L2 segment reserved as a temporary migration tool to be torn down afterward. Active-active adds a hard capacity rule: if a single-site failure must be survivable, neither site may exceed ~50% utilization (N+N) unless an automated load-shed step frees capacity -- and chatty inter-tier flows that are microseconds inside a DC become milliseconds across the DCI, so latency-coupled tiers must not be split. Multi-DC resilience is better achieved with global load balancing (VIP per site behind global DNS/anycast, synced local LBs) and a graceful drain/shift than with L2 extension or vMotion.",
  "observable": "Not collected -- RTO/RPO targets, storage/database replication, DR-site state, HA-cluster topology, per-site/per-link utilization, application tier communication patterns and cross-site latency are outside an L1-L4 assessment. The adjacent already-actionable signal (a VLAN stretched across many switches) is owned by dc-bound-layer2-failure-domain.",
  "trigger": "(Design) a DR/active-active plan that leads with stretched VLANs / long-distance vMotion / stretched HA clusters instead of stating RTO/RPO; both sites loaded past ~50% while a single-site failure must be survivable; distributing tiers of a chatty app across sites without analyzing inter-tier request/round-trip counts.",
  "recommended_action": "Capture business RTO/RPO/budget and per-app downtime tolerance FIRST; choose the replication tier from RPO (synchronous only where a near-zero RPO truly justifies its cost/distance limits, otherwise async / DB-replica / log-shipping); keep warm data and minimal warm infrastructure already running at the DR site; prefer restart-at-DR with DNS/service-discovery endpoints (or VIP-per-site behind global DNS/anycast with a drain-and-shift migration) over stretched-L2 live mobility; cap steady-state per-site utilization near 50% (N+N) or commit to an automated load-shed step; keep latency-coupled tiers co-located; avoid stretched firewall/LB clusters across the DCI; test automated failover under realistic conditions.",
  "alternatives": "Permanent stretched-L2 'disaster avoidance' with live mobility (lower app change, but permanent complexity and a shared failure domain); active/standby with the standby idle (wastes the second site but trivially survivable); active-active at >50% with automated load-shedding (better utilization, depends on the shed step working); cold backup-restore (rejected when RTO is short).",
  "tradeoffs": "Orchestrated, business-sized DR needs disciplined automation and tested runbooks up front and may disappoint teams who asked for transparent mobility, but removes a permanent failure-domain, split-brain exposure and standing OpEx; holding ~50% headroom leaves capacity idle but guarantees single-site survivability.",
  "citation": "ipSpace.net 'From Disaster Recovery Sites to Active-Active Data Centers' / 'Designing Active-Active and Disaster Recovery Data Centers' / 'Active-Active Application Deployment' (Pepelnjak); standard N+N capacity-planning; CAP-theorem limits on distributed databases",
  "engine_actionable": false
 },
 {
  "id": "dc-services-load-balancer-vip-pool-and-insertion-mode",
  "title": "Model the load balancer as a health-checked VIP-to-pool, choose its insertion mode by return-path and client-IP cost, and don't build LB to mask a non-scale-out app",
  "domain": "dc-services",
  "priority": "Medium",
  "design_intent": "The durable model of an L4-L7 load balancer is three parts -- each service is a virtual IP (and port), the VIP is bound to a pool of real servers, and the LB continuously HEALTH-CHECKS members (from pings to application requests) so it steers each new session to a healthy, least-loaded member and pulls a failed one automatically; the availability value is in the control-plane health-checking, not the data-plane spreading, which is why plain DNS round-robin keeps handing clients dead servers until caches expire. HOW the LB sits in the path is a sharp trade: proxy/destination-NAT keeps the client source IP but pins the LB onto the (usually larger) return path; one-arm/source-NAT lets it sit off-path but rewrites the client IP (recoverable only via X-Forwarded-For for HTTP/after SSL offload); Direct Server Return shares the VIP on server loopbacks and rewrites only the L2 header so servers reply directly and bypass the LB on the return flow, at the price of L2 adjacency (or an IP tunnel) and ARP discipline. And the prior question is the application's: only horizontal scale-out forces an LB tier, and scale-out only works once shared state is removed (the canonical first move is decoupling the database) -- so resist building an elaborate LB fabric to paper over an app that has not been made stateless first.",
  "observable": "Not collected -- LB VIPs, server pools, health-probe config, NAT/DSR mode, X-Forwarded-For behaviour, application tier topology, server roles and session-state design are not in the L1-L4 evidence set (no LB/firewall config is gathered); per-link/return-path volume is not measured.",
  "trigger": "(Design) a service must present a single stable address over multiple interchangeable backends or an availability requirement asks for automatic removal of failed instances; an application owner asks the network to 'load-balance' or 'make it highly available'; LB placement is being decided with high return/download volume or a hard requirement to preserve client source IP.",
  "recommended_action": "Before committing LB hardware/VIPs, confirm the application is genuinely stateless/scale-out (DB decoupled, no server-pinned session state) and raise a requirement gap if it is scale-up/session-bound rather than masking it in the network; specify the VIP(s), pool membership and the health-probe type/interval per service, preferring an LB (or anycast with route withdrawal) that withdraws failed members over DNS round-robin; choose the insertion mode from return-path and client-IP needs -- Direct Server Return when reverse traffic dwarfs requests, proxy/source-NAT with X-Forwarded-For when full L7 control or the true client IP is needed (documenting that L4-only/IPv6 cases cannot recover the client IP cleanly).",
  "alternatives": "DNS round-robin for non-critical services; local anycast with health-driven route withdrawal; application-level/client-side balancing where the app handles member selection; two-arm transparent destination-NAT (keep client IP, LB in path) vs source-NAT one-arm (flexible placement, recover client IP at L7) vs DSR (offload the return path).",
  "tradeoffs": "A real LB gives health-aware steering, stickiness and content control but is an extra stateful in-path device to size and make redundant; DSR offloads the heavy return path and scales throughput but constrains topology (L2/tunnel, loopback-VIP, ARP) and limits L7 on the return flow; scale-up is simpler but rigid and obliges no LB, scale-out is elastic but bounded by shared state.",
  "citation": "ipSpace.net / NIL 'Load Balancing and Scale-Out Application Architectures' (LB principles & operations; transparent vs one-arm; Direct Server Return; X-Forwarded-For; scale-up vs scale-out, decouple-DB prerequisite)",
  "engine_actionable": false
 },
 {
  "id": "dc-services-shared-border-firewall-and-service-insertion",
  "title": "Anchor firewall/LB at a shared border in its own AS; insert inline services transparently to avoid readdressing",
  "domain": "dc-services",
  "priority": "Medium",
  "design_intent": "A multi-site fabric can funnel all external connectivity and L4-L7 (active/standby firewalls + load balancers) through ONE shared border in a distinct ASN that performs centralized VRF route-leaking -- a single policy-enforcement and route-leak point (with a dedicated FW-bypass shared-services VRF and import-maps that deny default-route leakage, and advertise-PIP to avoid black-holing) rather than per-site borders. Independently, when a new inline appliance (filter, firewall, traffic-control box) must go between two existing L3 devices, inserting it as a routed L3 hop forces new subnets, readdressing and a routing redesign, whereas a TRANSPARENT L2 (bump-in-the-wire) insertion leaves addressing and routing untouched -- the existing routers keep their adjacency across the bridge, and that very adjacency becomes a liveness check that reroutes traffic if the device fails (the transparent device must forward ARP/BPDU/non-IP and ideally announce itself via LLDP).",
  "observable": "Not collected -- firewall/LB topology, cluster/HA membership, service-chain placement and whether an inline device is L2-transparent or L3-routed are out of L1-L4 scope; the engine sees routing adjacencies and subnets generally, and a QoS audit can corroborate the access-edge trust boundary, but not the border policy or insertion mode.",
  "trigger": "(Design) a multi-site EVPN that must share one firewall/LB perimeter and one route-leaking point, or a security/filtering/traffic-control appliance that must be added into an existing forwarding path without re-engineering the IP plan.",
  "recommended_action": "Deploy the shared border as a site-external L3-only VTEP in a separate AS with active/standby FW and LB over vPC and centralized route-leaking (dedicated FW-bypass VRF, import-maps denying default leakage, advertise-PIP); for inline service insertion prefer transparent L2 so existing subnets/adjacencies are preserved -- permit the routing hellos across the device, forward ARP/BPDU/non-IP, and use the surviving L3 adjacency as the path-health signal that triggers reroute on appliance failure.",
  "alternatives": "Per-site border leaves with local firewalls (rejected where one FW/LB perimeter is shared); routed L3 insertion where the appliance is meant to be a deliberate routing/policy boundary; policy-based redirection / service-chaining in fabric designs; host-based filtering when an inline box is undesirable.",
  "tradeoffs": "Centralizing at a shared border simplifies policy/route-leak but makes the border + FW pair a shared blast radius (mitigated by A/S redundancy + advertise-PIP); transparent insertion is least disruptive and self-heals via the routing adjacency but the device is invisible to L3 troubleshooting and can black-hole if it fails open/closed wrongly.",
  "citation": "[HISTORY-REDACTED] SDD 'Shared Border' / 'Shared Border - Firewall' (Centralized Route Leaking, FW-Bypass-VRF) / 'Shared Border - Load Balancer'; ipSpace.net 'High-Speed Multi-Tenant Isolation' (transparent bump-in-the-wire vs routed insertion; routing adjacency as path check)",
  "engine_actionable": false
 },
 {
  "id": "dc-services-tenant-isolation-vrf-acl-and-vrflite-ceiling",
  "title": "Isolate tenants with per-tenant VRF over a shared L3 core; respect the stateless-ACL TCAM ceiling and the VRF-Lite single-hop limit",
  "domain": "dc-services",
  "priority": "High",
  "design_intent": "A high-density multi-tenant DC keeps tenants apart not with physical separation but with ONE shared L3 backbone carrying many independent routing domains -- one VRF per tenant/zone -- so each gets complete L3 separation while the operator runs a single fabric, and inter-tenant / tenant-to-outside reachability becomes an explicit policy decision at the container edge rather than an accident of a flat address space. Two scaling guardrails bound the technique. First, enforcement: where no regulation mandates stateful firewalls and the fleet is hardened, stateless prefix-based ACLs on existing L3 switches can enforce the allowed flows (with established-session permits for the return direction and a fragment drop at the boundary) -- but ToR switches hold a bounded number of ACL/TCAM entries, so per-HOST rule generation explodes combinatorially (the Cartesian product of source x destination) and rules MUST be written against prefixes/groups. Second, transport: VRF-Lite gives every VRF its own interfaces, routing instance and table -- ideal for single-box/single-hop separation -- but does NOT scale end-to-end, because every router on the path must carry all VRFs and run a separate per-VRF routing instance (parallel adjacencies, per-instance convergence) that grows with both VRF count and path length; once isolation must cross more than one hop, switch to MP-BGP/MPLS-VPN (or EVPN/VXLAN in the DC) where only the PE edges hold the VRFs and the core label-switches.",
  "observable": "Partly observable -- the engine collects the VRF/segmentation list per device, per-VLAN switch span and routing_neighbors, so it can see whether per-tenant/zone VRFs exist or everything rides one global table, AND detect the SAME VRF replicated across multiple hops with per-VRF adjacencies (the VRF-Lite multi-hop antipattern); it does NOT see EVPN/VXLAN/VNI overlays, per-device ACL-entry consumption vs TCAM budget, or whether a filter is stateful.",
  "trigger": "(Partly observed) multiple tenants/zones must share one fabric yet remain L3-isolated; distinct tenants/zones collapse into one global routing table; the same VRF appears on multiple routers with a per-VRF IGP/BGP instance on each, or isolation must extend end-to-end across several L3 hops while still on VRF-Lite trunks; an inter-zone isolation requirement with no statefulness mandate being placed on existing L3 switches.",
  "recommended_action": "Map each tenant/zone to its own VRF on the shared core and force all inter-tenant and tenant-to-outside traffic through an explicit policy point; flag any design collapsing distinct zones into one global table as a segmentation gap; where statefulness is not mandated, allow stateless PREFIX-based ACLs with explicit established-session permits and a boundary fragment-drop, but size the ruleset against the switch's published ACL/TCAM capacity and reject per-host rule generation; cap VRF-Lite at single-box/single-hop use and, where isolation must traverse the core, adopt MP-BGP/MPLS-VPN (single-hop PE-PE first) -- or EVPN/VXLAN per-tenant VNIs on an overlay-capable fabric -- so the core stops carrying every VRF's routing.",
  "alternatives": "Physically separate fabrics per tenant (maximum isolation, maximum cost); VLAN/ACL-only separation inside one routing table (weaker, leak-prone); stateful firewalls/NGFW where regulation or threat model demands; x86/NIC-offload software filters at 10GE when switch TCAM is the limit; EVPN/VXLAN per-tenant VNIs where an overlay-capable fabric exists.",
  "tradeoffs": "Per-tenant VRFs give strong, scalable isolation and a clean policy seam but multiply routing-domain state and RT import/export bookkeeping; stateless ACLs are cheap and line-rate but cannot track state, reassemble fragments or scale to per-host rules; VRF-Lite is simple with no MPLS footprint but explodes per-hop/per-VRF state, while MPLS-VPN adds a scalable single control plane at the cost of MPLS skill and operational surface.",
  "citation": "ipSpace.net 'High-Speed Multi-Tenant Isolation' (per-tenant VRF over shared L3; stateless ACL vs stateful FW, established-session match, ToR ACL/TCAM Cartesian explosion, drop fragments); NIL 'Enterprise MPLS/VPN Deployment' ('Multi-VRF Does Not Scale'); RFC 4364",
  "engine_actionable": false
 },
 {
  "id": "dc-services-anycast-gateway-dhcp-relay-giaddr",
  "title": "Under a distributed anycast gateway, give DHCP relay a unique per-switch loopback GiAddr with Option-82/VNI scope selection",
  "domain": "dc-services",
  "priority": "Low",
  "design_intent": "With a distributed anycast gateway the relay GiAddr would be identical on every leaf, so a DHCP reply could return to any leaf and land on the wrong switch. The fix is a unique loopback per switch as the GiAddr plus DHCP Option-82 (dhcp option vpn) scope selection keyed to the L2VNI, so replies come back to the correct switch and the right subnet scope is chosen. It is a subtle but real anycast-gateway caveat that only surfaces once the gateway has moved to the fabric.",
  "observable": "Partly adjacent -- the reachability engine is DHCP-relay-aware (it sees helper/relay addresses), but the unique-loopback-GiAddr / Option-82-by-VNI remediation is target-state fabric config it does not collect.",
  "trigger": "(Migration) a migrated VLAN relies on DHCP relay and its gateway has moved (or is moving) to the fabric distributed anycast gateway.",
  "recommended_action": "Per leaf, assign a unique loopback as the DHCP relay GiAddr and enable Option-82 (dhcp option vpn) scope selection keyed to the L2VNI at the point the gateway is cut to the fabric.",
  "alternatives": "Centralized DHCP relay at a non-anycast boundary; per-VLAN relay on the SVI that owns the scope; reservation/static addressing for the few hosts that cannot tolerate relay nuances.",
  "tradeoffs": "The unique-loopback + Option-82 approach adds per-leaf relay configuration but guarantees replies return to the correct switch under an identical anycast GiAddr; skipping it risks mis-delivered or dropped DHCP offers after the gateway move.",
  "citation": "[HISTORY-REDACTED] SDD 'DHCP RELAY' (Layer 2 Design) -- unique loopback as GiAddr; Option-82 (dhcp option vpn) scope selection by L2VNI",
  "engine_actionable": false
 },
 {
  "id": "cloud-standardized-pod-as-availability-zone",
  "title": "Build the cloud from standardized pods sized to measured workload, each pod an independently-survivable availability zone",
  "domain": "cloud",
  "priority": "High",
  "design_intent": "A private cloud should be a small number of standardized, repeatable building blocks (pods) on dedicated infrastructure, each a self-contained unit of compute, storage and network you replicate to grow -- and crucially each pod is ONE failure domain / availability zone that owns its own ToR pair and the critical services it depends on, so a fault, flooding event or maintenance action in one pod never cascades fleet-wide. Define the blast radius FIRST and let it bound every other choice: anything that silently widens it -- a stretched VLAN, a single shared orchestrator/management instance spanning racks, or an L2 storage-replication/clustering dependency that fuses two zones -- is a design defect. SIZE the pod from MEASURED long-term workload (per-VM cores/RAM/IOPS, storage, VM-network bandwidth and the north-south-vs-east-west split, or documented public-cloud instance ratios when local data is missing) rather than guesswork or vendor datasheet port counts, and quote real one-direction bandwidth (discount ingress+egress 'marketing math'). Standardization shrinks the operational surface, makes capacity planning linear and is the precondition for automation.",
  "observable": "Partly observable -- the engine has an endpoint/VLAN census, per-switch port inventory and per-VLAN switch span / move-groups / cut-edges / FHRP (enough to flag a stretched-L2 fault domain that bleeds across blocks); it does NOT collect per-VM/host CPU/RAM/IOPS, per-link bandwidth, the east-west/north-south traffic ratio, orchestration/management instances, storage replication, or the intended pod/zone boundaries.",
  "trigger": "(Design) cloud/DC capacity modelled as one big shared fabric rather than independent zones; ad-hoc, non-replicable, guess-sized builds; a single management/orchestration or critical-service instance that, if lost, takes multiple racks or sites down; an L2 segment, storage-replication or clustering dependency that fuses two zones; sizing driven by vendor port-count datasheets with no stated east-west/north-south ratio.",
  "recommended_action": "Define a standardized pod (fixed compute/storage/network recipe, ideally hyperconverged) and grow by replicating it; build the capacity model first -- measure cores/RAM/IOPS and per-host/per-VM bandwidth, apply a growth factor, and translate to total edge ports by media, transport class (IP vs lossless/FCoE) and the east-west/north-south split (quoting real one-direction bandwidth); make each pod an independently-survivable availability zone with its own redundant access and its own (or an automatically-failing-over) instance of the management/orchestration/DHCP/DNS services it depends on; never run a single critical service instance across racks (and especially not across data centres); keep inter-zone connectivity routed (L3) and isolate any required stretch behind an overlay with storm-control; reject storage-replication/clustering that mandates end-to-end L2 between zones.",
  "alternatives": "One large shared fabric/management domain (simplest to operate, but one fault is fleet-wide); a few very large monolithic blocks (fewer entities, larger blast radius, coarser capacity steps); bespoke per-application sizing (best per-app fit, unrepeatable and hard to automate); vendor-led datasheet sizing (fast, risks mis-fit and over/under-build).",
  "tradeoffs": "Standardized, independent pods can over- or under-provision an atypical workload and multiply management/licensing instances, but cap each failure to one block, make capacity linearly replicable and enable automation; sizing from real data costs measurement effort up front but prevents both starvation and marketing-math over-provisioning.",
  "citation": "ipSpace.net 'Designing a Private Cloud Infrastructure' / 'From Traditional Silos to SDDC' / DC Design Case Studies ch.6 & ch.11 'Cloud Infrastructure Failure Domains' (Pepelnjak); RFC 2119 requirement levels",
  "engine_actionable": false
 },
 {
  "id": "cloud-decouple-overlay-from-stable-ip-underlay",
  "title": "Decouple the virtual network from the physical: a stable IP underlay plus overlay removes the maintenance-window tax",
  "domain": "cloud",
  "priority": "Medium",
  "design_intent": "In a traditional silo, every tenant or application network change is also a physical change -- a VLAN to plumb, a trunk to edit, a maintenance window -- which is the real reason provisioning is slow and risky. The SDDC pattern breaks that coupling: build the physical network as a stable, simple, rarely-touched IP transport (the underlay) and express all per-tenant/per-application segmentation as OVERLAYS (MAC-in-IP/VXLAN) provisioned in software, so virtual-network change no longer requires physical change or an outage window, the underlay can be upgraded independently, and self-service becomes possible because the consumer never touches the fabric. This is the architectural decoupling that makes change-automation and self-service possible -- distinct from config/change discipline -- and it is also what lifts the classic 4K-VLAN and single-failure-domain ceilings of fabric-managed segmentation.",
  "observable": "Partly observable as a symptom -- the engine can see the coupled-world signature (many VLANs spanning many switches, manual per-VLAN trunking, a large sprawling VLAN inventory), but NOT whether an overlay decoupling, controller or orchestration model exists (VXLAN/VTEP/VNI/controller state is out of scope).",
  "trigger": "(Design) a fabric where every new segment/tenant means hand-edited VLANs and trunks across physical switches (observable proxy: a large VLAN inventory spanning many switches), i.e. virtual change is bolted to physical change.",
  "recommended_action": "Architect the physical network as a stable IP underlay whose only job is fast, simple, loop-free transport, and move all tenant/application segmentation into an overlay provisioned by the orchestration system; keep the underlay configuration small and change it rarely; let the overlay (and self-service) absorb the churn so segment adds/moves need no physical change or maintenance window. Where heavy manual VLAN sprawl is observed, surface decoupling-via-overlay as a design option.",
  "alternatives": "Stay with VLAN-based segmentation managed directly on the physical fabric (well-understood, no new control plane, but every change touches the network and hits the 4K-segment and single-failure-domain ceilings); buy a turnkey SDN/controller stack (faster to stand up, vendor lock-in and an operational learning curve).",
  "tradeoffs": "Decoupling adds an overlay control plane and new troubleshooting skills, and the physical/virtual split can hide end-to-end paths from ops; in return it removes the maintenance-window tax, lets underlay and overlay evolve independently, and is the precondition for self-service and automation.",
  "citation": "ipSpace.net 'From Traditional Silos to SDDC' / 'Designing a Private Cloud Infrastructure' (Pepelnjak); corroborated by VXLAN/EVPN overlay design literature",
  "engine_actionable": false
 },
 {
  "id": "cloud-east-west-flattens-tiering-vswitch-and-server-attach",
  "title": "East-west traffic now dominates: flatten to non-blocking multipath, and treat the hypervisor vSwitch + server NIC-teaming as a first-class, STP-less access edge",
  "domain": "cloud",
  "priority": "Medium",
  "design_intent": "Virtualization, clustering and distributed applications invert the classic north-south hierarchy: the bulk of DC traffic is now EAST-WEST (replication, storage, app tiers, VM mobility), and STP makes it worse by blocking half the links so the survivors carry more than their share -- which is exactly what pushed designs from STP triangles to non-blocking multipath (MLAG, then leaf-spine). Two server-edge realities follow. First, server virtualization pushes the real L2 access edge INTO the server: a hypervisor vSwitch tags VLANs for dozens of VMs but runs NO spanning tree (it prevents loops by split-horizon + source-MAC pinning), so its uplinks look like independent orphan hosts to the physical/MLAG switch and VM-to-NIC pinning -- not the switch -- decides egress. Second, match server attachment to the topology: all-active dual-homed servers need a server-side LAG with LACP terminated on an MLAG ToR pair (a non-LAG dual-homed server in a routed fabric blackholes via ECMP to the wrong ToR), but if servers are single-homed/non-LAG, pairing the ToRs into MLAG/stack HURTS -- those become orphan ports whose mutual traffic hairpins across the limited peer-link, so leave the ToRs independent and dedicate the freed ports to leaf-to-spine uplinks. Never use static (no-LACP) bundles, which cannot detect miswiring or a half-failed link.",
  "observable": "Partly observable for the symptom, not the cause -- the engine sees STP mode and STP-blocked links (protocol_health) and wide L2 domains, hinting at the east-west penalty; it does NOT collect per-link bandwidth, the east-west/north-south ratio, hypervisor/vSwitch presence, NIC-teaming/bonding mode, port-groups, VM-to-NIC pinning, or ToR MLAG/peer-link/orphan-port state (EtherChannel-mode parsing is out of scope).",
  "trigger": "(Design / partly observed) a DC fabric still built as oversubscribed N/S tiers with STP blocking redundant uplinks while the workload is virtualized/clustered; virtualized hosts dual-homed to the access/MLAG layer whose per-server uplinks are not bundled into a server-side LACP LAG and whose vSwitch topology the network team cannot see; ToRs paired into vPC/MLAG/stack while attached servers are single-homed; LAGs configured static without LACP.",
  "recommended_action": "Treat east-west bisectional bandwidth as a first-class requirement: eliminate STP-blocked uplinks by moving to active-active multipath (MLAG at small scale, a leaf-spine VXLAN fabric beyond two switches) and size leaf uplinks to the real oversubscription target; treat the server trunk as an edge facing an unmanaged STP-less bridge -- pre-provision the VLANs on the ToR (or automate via orchestration), use a distributed vSwitch with LACP where a bundled uplink is wanted so the MLAG pair sees one LAG not orphan ports, apply storm-control and don't rely on STP toward the server; for all-active dual-homed servers use server-to-switch LACP LAG on an MLAG ToR pair, but for single-homed/non-LAG servers do NOT MLAG/stack the ToRs (dedicate the ports to uplinks); always use LACP, never static port-channels.",
  "alternatives": "Keep the N/S-optimized hierarchy with STP and just add uplink bandwidth (cheapest, half the links idle, east-west tromboned); scale up to chassis switches before scaling out to a fabric; accept active/standby NIC teaming with no server-side LAG (simplest, half the bandwidth idle and pinning-dependent egress); push the L2 edge back onto the network with hardware VXLAN/fabric-extender so hypervisor and bare-metal hosts look equivalent; FabricPath/TRILL L2 multipath instead of MLAG.",
  "tradeoffs": "A non-blocking multipath fabric costs more switches/optics and a new control plane but converts idle redundant links into usable east-west capacity and removes the STP-blocking penalty; coordinating with the vSwitch (distributed switch + LACP, pre-provisioned VLANs) adds cross-team process and licensing but removes orphan-port tromboning and surprise loops; matching MLAG to actual server homing avoids peer-link hairpinning at the cost of two access-design variants.",
  "citation": "ipSpace.net 'Data Center 3.0 for Networking Engineers' / 'Server Virtualization Overview' / 'Redundant Server-to-Network Connectivity' / DC Design Case Studies ch.7 (Pepelnjak); VMware vSphere networking design; IEEE 802.1AX (LACP)",
  "engine_actionable": false
 },
 {
  "id": "dc-switching-unified-fabric-io-consolidation",
  "title": "Consolidate LAN and storage onto one lossless Ethernet fabric only with DCB and a stable L2 -- it merges two failure domains",
  "domain": "dc-switching",
  "priority": "Low",
  "design_intent": "Traditionally a server carried separate adapters and cabling for the LAN (Ethernet) and SAN (Fibre Channel), doubling access-layer wiring, ports and adapters. I/O consolidation (FCoE, or IP storage over iSCSI/NFS) carries storage over the same 10GE+ fabric, collapsing two networks into one to cut adapter/cable/port count. The catch is that storage will not tolerate the drops a normal best-effort, spanning-tree-churning LAN produces: convergence REQUIRES lossless Ethernet (Data Center Bridging / PFC) and a very stable underlying L2, and it MERGES what were two independent failure domains, so the converged fabric's stability and QoS budget become storage-critical.",
  "observable": "Not collected -- per-link bandwidth, FCoE/DCB/lossless-Ethernet configuration, storage protocols and adapter/cabling inventory are out of L1-L4 scope; the engine sees Ethernet switchports and VLANs, not whether storage shares the fabric or whether DCB/PFC is enabled.",
  "trigger": "(Design) a greenfield or refresh DC choosing between parallel LAN+SAN fabrics and a converged Ethernet fabric, or a converged design running storage over an L2 that is not demonstrably lossless/stable.",
  "recommended_action": "Where adapter/cable/port reduction justifies it, converge LAN and storage onto a single 10GE+ fabric using FCoE (with DCB/PFC for lossless behaviour) or IP storage (iSCSI/NFS); insist on a stable, loop-controlled underlay (minimize spanning tree, prefer multipath) because storage cannot absorb LAN-style instability; budget and protect a storage QoS class end-to-end; keep the converged-fabric blast radius in mind since LAN and SAN now share a failure domain.",
  "alternatives": "Keep physically separate LAN and SAN fabrics (maximum isolation and independent failure domains, double the adapters/cabling/ports/silos); use IP storage (iSCSI/NFS) on existing Ethernet without full FCoE/DCB (simpler, but without lossless guarantees performance is congestion-sensitive).",
  "tradeoffs": "Convergence cuts capital and cabling cost and simplifies the physical plant, but couples two previously independent failure domains and demands lossless-Ethernet engineering plus disciplined QoS; physical separation is more expensive and wasteful but isolates storage from LAN faults.",
  "citation": "ipSpace.net 'Data Center 3.0 for Networking Engineers' / 'Server Virtualization Overview' (Pepelnjak); Cisco unified-fabric / FCoE design guidance",
  "engine_actionable": false
 },
 {
  "id": "dc-switching-capacity-from-measured-traffic-not-average",
  "title": "Size capacity from measured traffic and concurrency -- average utilization is not health, and microbursts drop below 70%",
  "domain": "dc-switching",
  "priority": "Medium",
  "design_intent": "Data traffic is bursty, so capacity should be sized from MEASUREMENT, not a single average or a guess. A defensible method is per-edge-port 95th-percentile utilization x port density x a growth factor, plus real-time session bandwidth (sessions x per-session rate at the QoS reservation). Crucially, a link whose average and even per-coarse-sample peak sits well below 100% can still drop traffic: sub-second microbursts overrun egress buffers even at low average utilization, and the cure is QoS scheduling, NOT bigger buffers -- oversized buffers cause bufferbloat (latency/jitter that confuses TCP and lowers goodput). This is the capacity-planning sibling of the engine's false-health stance: 'average looks fine' must never silently become 'healthy'.",
  "observable": "Not collected -- per-link bandwidth, 95th-percentile utilization, flow/NetFlow data, microburst counters and TCP retransmit stats are not gathered by the L1-L4 assessment; interface-error/duplex hygiene IS collected, but utilization-based sizing is not.",
  "trigger": "(Design) capacity-planning a new or growing network/fabric, sizing uplinks, or interpreting an assessment where a link is declared healthy purely because average/peak utilization looks low.",
  "recommended_action": "Base link sizes on 95th-percentile edge-port utilization x port count x growth, plus summed real-time session bandwidth; look at egress discards/drops and TCP retransmit ratios (not just utilization) to find congestion; apply QoS to protect real-time and police abusive flows rather than enlarging buffers; size for the busy period and for the service level required DURING a failure.",
  "alternatives": "Guessing or buying the newest/highest speed 'to be safe' is the most common method and sometimes pragmatic ('as much bandwidth as the customer can afford'), but it forgoes the analysis that justifies the spend and still misses microburst loss.",
  "tradeoffs": "Measurement-based sizing costs collection/analysis effort but earns CFO trust and avoids both under-provisioning (lost productivity) and over-provisioning (wasted capex); QoS-over-buffers trades a little engineering for protection of latency-sensitive traffic without the bufferbloat penalty.",
  "citation": "ipSpace.net / NetCraftsmen 'Sizing the Network' (Terry Slattery) -- 95th-percentile & concurrent-endpoint sizing, microbursts below 70% average, bufferbloat, Mathis-equation loss sensitivity; Cisco WAN capacity-planning white paper",
  "engine_actionable": false
 },
 {
  "id": "management-oob-must-not-transit-the-fabric",
  "title": "Build the OOB management network on physically separate gear so it survives a fabric meltdown and never transits the fabric it manages",
  "domain": "management",
  "priority": "Medium",
  "design_intent": "A data-center out-of-band management network exists precisely to reach infrastructure when the production fabric is melting down -- during a bridging loop, broadcast storm or brownout when the data plane is unusable -- and when a bad change breaks the in-band path. For that to hold it must be PHYSICALLY independent of the very fabric it recovers: built on a dedicated pair of small management switches and the devices' dedicated management ports (mgmt0/CIMC), NOT on the production ToRs or fabric-extenders hanging off them, and its path to the rest of the network must NOT transit the VXLAN fabric (typically up to a redundant vPC OOB-aggregation pair reaching the existing network via the edge firewall). Riding the production fabric makes management fate-share with the outage, defeating its purpose; the management plane has modest bandwidth needs (FE/GE), so the separate gear is cheap insurance.",
  "observable": "Not collected -- the engine does not model the management-plane topology or whether management rides the production fabric/ToR/FEX; management-plane wiring is outside L1-L4 switch/router evidence.",
  "trigger": "(Design) an OOB/management network whose switches are the same ToRs (or FEX off those ToRs) that carry production/storage traffic, a management path that could be carried over the production fabric, or no physically independent path to reach devices during a forwarding-plane failure.",
  "recommended_action": "Provision the OOB management network on dedicated, low-cost management switches separate from the production fabric, cabled to the devices' dedicated management ports (mgmt0 + ND/CIMC), and keep it off the user and storage data planes and off the VXLAN fabric; uplink to a redundant vPC OOB-aggregation pair with L3 to the A/S firewalls; never source the management path from the production ToR/FEX you may need to recover; size it for management traffic only (FE/GE), and use in-band (Loopback/VRF-management) only where a tool genuinely requires it. Treat reachability-during-a-meltdown -- not steady-state convenience -- as the design requirement.",
  "alternatives": "In-band management / management VLAN on the production fabric (cheaper, fate-shares with the outage; allowed only as a secondary path for specific tools); a fully separate OOB switch fabric (small extra cost, survives a data-plane meltdown).",
  "tradeoffs": "A separate OOB fabric adds a little gear and cabling but is the only way management survives the bridging-loop/brownout case it is meant to cover.",
  "citation": "ipSpace.net DC Design Case Studies ch.6 'Designing a Private Cloud Network Infrastructure' (Management Network) (Pepelnjak); [HISTORY-REDACTED] SDD 'Fabric Management' / 'Out-of-Band Management'; Cisco DC management/OOB best practice",
  "engine_actionable": false
 },
 {
  "id": "wan-vpn-make-vs-buy-and-test-before-buy-sp-transparency",
  "title": "Choose provider-vs-self-built VPN by who owns convergence, and make SP-controlled behaviors test-before-buy acceptance criteria",
  "domain": "wan-vpn",
  "priority": "Medium",
  "design_intent": "A provider L3VPN (MPLS/VPN) makes the carrier the new backbone: highly scalable with low CapEx/OpEx, but the SP then owns your core AND your convergence, most routing fixes require changes on PE routers you do not control, and you inherit vendor lock-in and a high barrier to change. A customer-built tunnel overlay (GRE/VTI/DMVPN over the Internet or over the SP's IP service) inverts this -- total routing/convergence control and no lock-in, at higher CapEx/OpEx and self-managed complexity -- so make 'who owns convergence and the core' an explicit, scored decision axis, not a feature checklist. Because so much L3VPN behavior lives on equipment you cannot see, the senior move is to convert the unknowns into TEST-BEFORE-BUY acceptance criteria: verify PE-to-CE load-sharing and automatic backup behavior (or mandate BGP PE-CE to own it), and for L2 services validate transparency -- who is your STP neighbor, are BPDUs/CDP/LACP carried, jumbo MTU, per-pseudowire bandwidth and 802.1p/DSCP preservation, and how remote link-loss is signaled. An unknown is a risk, not an assumption -- never let unverified SP capability pass silently as 'healthy'.",
  "observable": "Not collected -- WAN/VPN tunnels, SP service definitions, per-provider topology, PE/CE behavior, pseudowire transparency, per-link load-sharing and contractual lock-in are outside the L1-L4 evidence set; the engine can only note context like a CE-only edge or single-uplink dependence, not the ownership/lock-in judgement or the SP-side behavior.",
  "trigger": "(Design) selecting, renewing or migrating a WAN/site-to-site transport where failover, load-sharing, QoS, MTU or L2 transparency are functional requirements realized on SP-managed PE/CE devices, or where the brownfield shows reliance on a single managed-service provider for core forwarding/convergence and the business cares about change-agility, multi-provider sourcing or SP dependency.",
  "recommended_action": "Make ownership-of-convergence-and-core an explicit scored criterion alongside cost: prefer provider L3VPN where the SP is competent and the priority is maximum outsourcing of a large simple network; build a customer overlay (optionally over the provider's IP service to also fix a weak SP) where retaining routing/convergence control, avoiding lock-in or spanning multiple providers matters; document SP competence as a stated assumption. Build a test-before-buy/PoC gate: verify PE-to-CE load-sharing and automatic backup (or mandate BGP PE-CE), confirm end-to-end transparency (STP/BPDU/CDP/LACP, jumbo MTU, QoS marking, remote link-loss signaling), and capture each as a pass/fail acceptance criterion.",
  "alternatives": "Provider L3 MPLS/VPN (max outsourcing); customer-built overlay over the Internet (max control, lowest cost, must harden + encrypt); customer overlay over the SP's IP/MPLS service (keep control AND better QoS/SLA); contractually pin transparency/QoS/MTU SLAs and test them.",
  "tradeoffs": "Outsourcing, scale and low CapEx/OpEx vs loss of convergence/routing control, lock-in and SP-mediated change; up-front PoC/test effort vs discovering missing failover/transparency/QoS only in production; mandating BGP PE-CE to gain control vs accepting SP-default behavior to keep the CE simple.",
  "citation": "ipSpace.net 'Choose the Optimal VPN Service' (Pepelnjak) -- MPLS/VPN benefits/drawbacks, decision guidelines, 'Test-before-buy!' load-sharing/backup/transparency slides; RFC 4271 (BGP-4)",
  "engine_actionable": false
 },
 {
  "id": "wan-vpn-bgp-everywhere-and-mtu-headroom-on-coexistence",
  "title": "When MPLS/VPN forces BGP into the design, run BGP end-to-end instead of redistribution -- and plan MTU headroom before any label/tunnel",
  "domain": "wan-vpn",
  "priority": "Medium",
  "design_intent": "A domain where a SINGLE routing protocol runs is consistently less complex and more failure-resilient than one stitched with multiple protocols and mutual redistribution. This becomes a concrete VPN-selection driver: the provider backbone always runs BGP and the PE-CE boundary forces BGP-to-IGP redistribution (provider-managed CEs cannot carry MPLS/VPN extended communities into your IGP, so remote routes arrive flat-external), so keeping OSPF/EIGRP end-to-end means parallel two-way redistribution whose minor mistakes cause network-wide loops -- whereas extending BGP across the whole WAN removes the redistribution entirely and yields a rich policy toolset (local-pref/MED/communities) for primary/backup and TE. OSPF/EIGRP as PE-CE or over a parallel overlay also hides traps: the PE is always an ABR so remote routes arrive inter-area or external and an intra-area backdoor/second-overlay path is wrongly preferred over the MPLS path; making it work forces sham-links (needing SP cooperation) and EIGRP site-of-origin for multihomed loops. Separately, every encapsulation steals bytes: an MPLS label stack, GRE header or IPsec ESP enlarges the frame, so engineer MTU end-to-end up front -- raise core/transit MTU (jumbo/baby-jumbo, >=1526 for a single label/GRE, more for stacked labels or GRE+IPsec) or clamp the PE-CE/access MTU -- or large/PMTUD-blocked flows silently fragment or black-hole.",
  "observable": "Partly observable -- routing_neighbors expose the protocol mix and the devices where redistribution must occur (a BGP adjacency on a router also running OSPF/EIGRP toward the site; IGP-at-the-CE-edge; multihomed redistribution-prone sites), and L2 switch/interface/trunk MTU is collected so default-1500 transit links on a path slated to carry labels/tunnels can be flagged; the WAN tunnels, SP backbone, OSPF area/LSA detail, sham-link config and which links will actually carry labels are NOT collected.",
  "trigger": "(Partly observed) an MPLS/VPN service coexists with (or is being joined to) an IGP-based site or a second WAN/overlay -- evidenced by two-way IGP<->BGP redistribution at multiple edges, remote routes appearing as external OSPF/EIGRP, OSPF/EIGRP used as PE-CE or overlay routing parallel to an MPLS path, or a plan to add Internet-VPN/DMVPN alongside existing MPLS/VPN; OR a target state introduces MPLS/GRE/IPsec over an existing path, or transit L2 switches sit at default 1500-byte MTU with no jumbo headroom.",
  "recommended_action": "When combining MPLS/VPN with any other WAN connectivity, adopt BGP as the single WAN routing protocol end-to-end instead of multiplying redistribution boundaries, reserving the IGP for intra-site reachability and BGP-next-hop resolution and using communities/local-pref/MED for path selection; if OSPF must stay, keep the PE-CE link in area 0, anticipate the ABR/external behavior, add sham-links only with SP coordination, avoid multi-process-plus-mutual-redistribution failover, and use EIGRP SoO for multihomed sites. Before enabling any encapsulation, compute the worst-case header stack and set MTU accordingly (bump core/transit-switch MTU to jumbo/baby-jumbo, or clamp PE-CE/access MTU / MSS), audit L2 switches on the path for jumbo support and current MTU, and record MTU as an explicit pre-cutover gate.",
  "alternatives": "BGP end-to-end on the WAN (preferred when MPLS/VPN is present); keep the IGP and fence redistribution with tags/filters (acceptable for simple single-boundary cases); OSPF strictly with PE-CE in area 0 + sham-links (SP cooperation required); EIGRP with SoO for multihomed sites; for MTU: raise core+transit MTU (transparent to endpoints) vs clamp edge MTU/MSS (no core change, smaller payloads) vs rely on fragmentation (worst).",
  "tradeoffs": "BGP-everywhere removes redistribution loops and gives rich policy at the cost of the team mastering BGP and losing IGP familiarity; OSPF familiarity vs distorted route selection, sham-link/SP dependency and fragile multi-process redistribution; end-to-end large-payload/PMTUD correctness vs the chore of consistent jumbo MTU on every transit device.",
  "citation": "ipSpace.net 'Integrating Internet VPN with MPLS/VPN WAN' / 'Combining DMVPN and MPLS VPN' / 'Choose the Optimal VPN Service' (Pepelnjak) and NIL 'Enterprise MPLS/VPN Deployment' (PE-CE redistribution, OSPF-as-PE-CE traps, core MTU/jumbo-frames guidance)",
  "engine_actionable": false
 }
]
""")
DOCTRINE.extend(_DC_CORPUS_ADDENDUM)

# ------------------------------------------------- evidence-grounded actionable detectors (follow-up)
# These two principles are engine_actionable=True because design_advisor wires a dedicated detector that
# reads ALREADY-COLLECTED evidence for each (so the coverage-honesty invariant
# test_every_engine_actionable_principle_is_emitted holds). Grounded + refutation-verified against the
# real [HISTORY-REDACTED] snapshot: (1) rapid-PVST per-VLAN STP at high VLAN scale -> MST (reads protocol_health STP mode
# + n_vlans; scoped to rapid-PVST so it does NOT double-count the legacy-PVST switches owned by
# _d_stp_det); (2) on-air-critical application tiers left L3-exposed -> macro-segment (reads the
# segmentation axis's own tier classification + gateway-ACL coverage). Standards/refs are public.
_ACTIONABLE_DETECTOR_ADDENDUM = [
    {
        "id": "dc-stp-mst-instance-scale",
        "title": "Move per-VLAN spanning tree (Rapid-PVST) to MST at high VLAN scale -- one STP instance per VLAN does not scale",
        "domain": "dc-switching",
        "priority": "Medium",
        "design_intent": "Per-VLAN spanning tree (PVST+/Rapid-PVST) runs an independent STP state machine "
        "for every VLAN on every trunk, so an estate with many VLANs across many switches carries up to "
        "(VLANs x switches) STP instances -- each consuming CPU, BPDU bandwidth, topology-change processing "
        "and a per-VLAN root-placement chore. Rapid-PVST is fine at small scale, but the instance count "
        "grows linearly with VLANs and becomes a control-plane burden (and a mis-rooted or storming VLAN is "
        "multiplied across every instance). MST (IEEE 802.1s) maps many VLANs onto a small set of instances "
        "(often 1-16), collapsing the instance count and the root-placement surface while keeping per-region "
        "load distribution.",
        "observable": "STP mode per switch is parsed into protocol_health[].summary ('mode rapid-pvst|pvst|"
        "mst; N blocked, ...'); the VLAN count is the canonical executive_brief.scale.n_vlans / vlan_inventory.",
        "trigger": "Many switches run Rapid-PVST (per-VLAN STP) across a high VLAN count -- the per-VLAN STP "
        "instance count is an unmanaged control-plane scale problem.",
        "recommended_action": "Migrate the per-VLAN STP estate to MST: define a small set of MST instances "
        "with an explicit VLAN-to-instance map, align the region name/revision/map fleet-wide (a mismatched "
        "region silently splits the domain), place per-instance roots deterministically at the distribution, "
        "and keep edge protection (BPDU guard / PortFast). In the EVPN/VXLAN target this concern disappears "
        "at the fabric (L2 is bounded to the leaf) -- MST is the interim remedy for the brownfield tier.",
        "alternatives": "Stay on Rapid-PVST (simplest, per-VLAN load distribution, but O(VLANs) instances and "
        "a per-VLAN root chore); bound the VLAN span so per-switch instance counts stay low; move to a routed "
        "/ EVPN fabric so spanning tree is edge-only.",
        "tradeoffs": "MST adds a region/instance-map design and a fleet-wide config-consistency requirement "
        "(a mismatched region silently splits), but collapses the STP instance count, CPU/BPDU load and "
        "root-placement surface at scale.",
        "citation": "IEEE 802.1s (Multiple Spanning Tree) / 802.1Q-2014; Cisco campus STP design guidance (Rapid-PVST vs MST at VLAN scale)",
        "engine_actionable": True,
    },
    {
        "id": "security-isolate-oncritical-application-tier",
        "title": "Isolate the on-air-critical / high-value application tier -- do not leave it L3-reachable on the flat estate",
        "domain": "security",
        "priority": "High",
        "design_intent": "A network's highest-value tiers must not share a flat Layer-3 reachability domain "
        "with general IT. In a broadcast plant the on-air-critical media fabric (SMPTE ST 2110 uncompressed "
        "video, AES67/Dante audio, camera/robotics control) carries the live signal; if those tiers sit in "
        "the global VRF with no gateway ACLs, any compromised or misconfigured host anywhere on the estate "
        "can reach the on-air path -- a single fault then has plant-wide, on-air blast radius. "
        "Macro-segmentation places each critical tier in its own VRF/zone with enforced inter-zone policy, so "
        "the on-air fabric is reachable only by what must reach it.",
        "observable": "The segmentation axis classifies each application domain's tier (On-air critical / ...) "
        "and whether it is isolated, and measures gateway-ACL coverage (segmentation.summary.n_oncrit_exposed, "
        "gateway_acl.coverage_pct, domains[].tier/isolated) -- all already computed by the engine.",
        "trigger": "One or more on-air-critical (or otherwise high-value) application domains are L3-reachable "
        "(isolated=false) and/or gateway-ACL coverage is ~0 across the gateways -- an observed, un-bounded "
        "exposure of the most critical tier.",
        "recommended_action": "Macro-segment the on-air-critical tiers into dedicated VRFs/zones (or a "
        "separate fabric segment) with enforced inter-zone policy -- gateway ACLs at minimum, a stateful "
        "firewall for IT<->broadcast flows, default-deny into the on-air path. In the EVPN target, a "
        "per-tenant VRF + L3VNI per critical tier with selective route leaking; keep PTP/ST-2110 multicast "
        "scoped within the tier.",
        "alternatives": "A single flat VRF with per-gateway ACLs (cheaper, blunter, ACL sprawl); air-gap the "
        "on-air fabric (strongest isolation, hardest to operate / share services); per-workload "
        "micro-segmentation (finest control, highest lifecycle overhead).",
        "tradeoffs": "Macro-segmentation adds VRF/zone design and inter-zone policy lifecycle, but bounds the "
        "blast radius of any IT-side compromise or misconfiguration away from the live on-air signal path.",
        "citation": "Cisco IP Fabric for Media (SMPTE ST 2110) design guide; Cisco SAFE secure segmentation; NIST SP 800-207 (segment high-value assets)",
        "engine_actionable": True,
    },
]
DOCTRINE.extend(_ACTIONABLE_DETECTOR_ADDENDUM)


# ----------------------------------------------- net-new evidence-grounded detector addendum (v2)
# FIVE more actionable detectors over evidence the engine ALREADY collects but did not yet reason over
# at design-decision altitude. Each grounds on a populated snapshot axis, is emitted by a dedicated
# design_advisor detector (so engine_actionable=True is honest -- the emit-invariant test enforces it),
# and DISAPPEARS when its evidence is absent (refutation-locked in tests/test_design_blueprint.py):
#   addressing_conflicts -> renumber/NAT overlaps before any L3 merge;
#   physical_health       -> remediate CRC/duplex/err-disable L1 faults before cutover (clean NRFU baseline);
#   capacity              -> size the target for current load + growth headroom, not 1:1;
#   endpoint_dependencies -> preserve dual-homing + keep clusters together across move-groups;
#   interfaces.trunk_native_vlan -> dedicated native VLAN on trunks (close the VLAN-hopping/double-tag vector).
_ACTIONABLE_DETECTOR_ADDENDUM_2 = [
    {
        "id": "addressing-resolve-overlaps-before-merge",
        "title": "Resolve duplicate-IP / overlapping-subnet collisions before merging any L3 domain",
        "domain": "methodology",
        "priority": "Critical",
        "design_intent": "A migration that joins or collapses Layer-3 domains cannot tolerate address "
        "overlap: two devices answering to the same IP, or two sites advertising the same prefix, produce "
        "non-deterministic forwarding, broken management reachability and silent black-holes the moment the "
        "domains touch. Overlap is the single most common reason a 'simple' merge/cutover fails. It must be "
        "designed out UP FRONT -- in the target addressing plan, not discovered during the window -- by "
        "renumbering the smaller/least-disruptive side onto unique space, or, where renumber is infeasible, "
        "bridging the overlap with NAT/NPTv6 as an explicit, documented exception.",
        "observable": "The engine already computes addressing_conflicts.dup_ip (same address on multiple "
        "device/interface pairs) and addressing_conflicts.dup_subnet (overlapping prefixes) from the parsed "
        "L3 evidence -- a directly observed collision set, not an inference.",
        "trigger": "addressing_conflicts.dup_ip or .dup_subnet is non-empty -- at least one duplicate IP or "
        "overlapping subnet exists in scope of the planned merge.",
        "recommended_action": "Build a target addressing plan that assigns globally-unique, summarisable "
        "space per zone; renumber the duplicates on the least-disruptive side ahead of the window; where a "
        "renumber is genuinely infeasible, document a NAT/NPTv6 bridge as a tracked exception with an owner "
        "and a removal plan. Re-run the conflict check until dup_ip / dup_subnet are zero before cutover.",
        "alternatives": "NAT/NPTv6 to mask the overlap (fast, but adds stateful translation, breaks "
        "end-to-end visibility and embeds technical debt); defer to the window (highest risk -- a collision "
        "discovered mid-cutover has no clean rollback).",
        "tradeoffs": "Renumbering costs project effort and endpoint/DNS churn up front, but is the only option "
        "that yields clean, deterministic forwarding; NAT trades that effort for permanent operational "
        "complexity and lost traceability.",
        "citation": "RFC 1918 (private address space); Cisco enterprise network-merger / migration addressing "
        "guidance (overlapping space -> renumber, or NAT/NPTv6 as an explicit exception).",
        "engine_actionable": True,
    },
    {
        "id": "physical-remediate-l1-faults-before-cutover",
        "title": "Remediate physical-layer faults (CRC / input-errors / half-duplex / err-disable) before cutover",
        "domain": "methodology",
        "priority": "High",
        "design_intent": "A migration inherits whatever physical layer it is built on. Ports showing CRC/FCS "
        "or input errors, half-duplex (almost always a duplex-mismatch -> late collisions and CRCs), or an "
        "err-disabled state are carrying real faults -- marginal optics, damaged/too-long cabling, a mismatch, "
        "or a protective shutdown. Two failure modes follow if they are not cleaned first: (1) the fault is "
        "physically migrated into the new fabric on the same cable/optic, so the 'new' network is born "
        "degraded; (2) the NRFU/ATP baseline is taken over a dirty L1, so post-cutover error counters can't be "
        "trusted to certify the change. A clean physical layer is a precondition for a trustworthy acceptance "
        "test, not a nice-to-have.",
        "observable": "The engine collects per-port physical_health[] with crc_errors, input_errors, duplex "
        "and status (err-disabled) -- directly observed counters/states, per switch and port.",
        "trigger": "One or more ports show crc_errors>0, input_errors>0, half-duplex, or an err-disabled "
        "status -- an observed L1 fault that would be carried across the migration.",
        "recommended_action": "Triage and clear the physical faults before the window: reseat/replace optics "
        "and cabling on CRC/input-error ports, hard-set or correct duplex/speed on half-duplex links (no "
        "auto/half mismatch), and resolve the root cause behind each err-disable (don't just recover the port). "
        "Then re-baseline error counters to zero so NRFU can certify the cutover against a clean L1.",
        "alternatives": "Carry the faults and remediate post-cutover (cheapest now, but the new fabric starts "
        "degraded and the acceptance baseline is meaningless); replace the affected hardware wholesale during "
        "the refresh (clean, but higher BoM cost).",
        "tradeoffs": "Pre-cutover L1 remediation costs field time and possibly optics/cabling spend, but is the "
        "only way to guarantee the target is born clean and the NRFU baseline is trustworthy.",
        "citation": "IEEE 802.3 auto-negotiation (duplex mismatch -> late collisions / CRC); Cisco IOS/NX-OS "
        "interface error-counter troubleshooting; NRFU/ATP clean-baseline practice.",
        "engine_actionable": True,
    },
    {
        "id": "capacity-size-target-with-growth-headroom",
        "title": "Size each switch's replacement for its load plus a growth headroom -- don't port a near-full switch 1:1",
        "domain": "methodology",
        "priority": "Medium",
        "design_intent": "A switch running near its port (or PoE) ceiling cannot be replaced 1:1: a target "
        "sized to today's active-port count is born full, with no room for the moves/adds/changes, the phased "
        "build-before-break (which needs spare ports to stand the target up in parallel), or the growth the "
        "refresh is supposed to buy. Capacity is a per-device design input, not an afterthought -- each "
        "saturated switch's replacement must be sized from the OBSERVED utilisation plus an explicit headroom "
        "(and a build-before-break overhead). Most of a lightly-loaded estate ports 1:1 fine; this names the "
        "specific switches that do not.",
        "observable": "The engine computes per-device capacity[] with port_util and poe_util as PERCENTAGES "
        "(active/total ports, PoE drawn vs capacity) plus free_ports -- observed utilisation, per switch.",
        "trigger": "One or more switches run at or above the high-utilisation threshold (port_util >= 85%, i.e. "
        "< 15% free ports, or PoE near budget) -- little or no headroom to absorb growth or a parallel cutover. "
        "On a lightly-loaded estate this fires for only the few genuinely-saturated switches (evidence-gated).",
        "recommended_action": "Size the target from observed port_util/poe_util plus a documented growth "
        "headroom (e.g. +30-50%) AND the build-before-break overhead; prefer higher-density or modular "
        "platforms where switches are saturated; verify the PoE budget covers the powered-endpoint load with "
        "margin. Carry the headroom assumption into the BoM, not just the slide.",
        "alternatives": "Port 1:1 to minimise BoM (cheapest, but the fabric is born full and a near-term "
        "upgrade is forced); over-provision uniformly (simple, wastes spend on lightly-loaded tiers).",
        "tradeoffs": "Headroom raises the up-front hardware/BoM cost, but a target born full forces a premature "
        "second refresh and leaves no room to execute the migration in parallel.",
        "citation": "Cisco Enterprise Campus / CVD capacity & oversubscription planning (size for growth, not "
        "1:1); IEEE 802.3af/at/bt PoE power budgeting.",
        "engine_actionable": True,
    },
    {
        "id": "migration-preserve-dual-homed-endpoints",
        "title": "Preserve dual-homed endpoints across move-groups -- move both attachment points together",
        "domain": "scenario-pattern",
        "priority": "High",
        "design_intent": "An endpoint whose MAC is seen on two switches is dual-homed (two NICs/uplinks for "
        "redundancy, or NIC-teaming). Its resilience depends on the network keeping BOTH attachment points up. "
        "A move-group plan that splits the two attachment switches across different waves silently single-homes "
        "the endpoint for the duration -- one failure away from an outage during the most fragile phase of the "
        "project. So multi-homing is a MIGRATION CONSTRAINT: the wave plan must move both attachment points of "
        "each dual-homed endpoint together, and must reconcile shared-IP sets (VRRP/HSRP VIPs and anycast, vs "
        "genuine duplicates) deliberately rather than carrying them blind.",
        "observable": "The engine computes endpoint_dependencies.dual_homed (a MAC observed on two switches) "
        "and .shared_ip from the MAC/ARP/topology evidence -- observed multi-attach, not assumed. (The separate "
        ".clusters analytic is a vendor/class affinity grouping, not an HA cluster, so it is NOT used here.)",
        "trigger": "endpoint_dependencies.dual_homed is non-empty -- observed dual-homed endpoints whose second "
        "path a switch-by-switch move-group would transiently break.",
        "recommended_action": "Constrain the move-group/wave generator so BOTH attachment switches of each "
        "dual-homed endpoint land in the SAME wave; validate per wave that each endpoint still has two live "
        "paths after the move; and classify every shared-IP set (legitimate FHRP/anycast vs a real duplicate to "
        "renumber) before cutover.",
        "alternatives": "Move purely by switch/closet ignoring multi-homing (simplest plan, but transiently "
        "single-homes endpoints); freeze the dual-homed endpoints to a single big-bang wave (safer for them, "
        "less granular rollback for everything else).",
        "tradeoffs": "Multi-homing constraints make the wave plan less free (some waves grow to keep both legs "
        "of an endpoint together), but they preserve the very redundancy the endpoints were built with.",
        "citation": "Cisco Advanced Services migration move-group methodology (preserve endpoint redundancy "
        "across waves); NIC-teaming / dual-homing dependency on both network paths.",
        "engine_actionable": True,
    },
    {
        "id": "l2-dedicated-native-vlan-on-trunks",
        "title": "Use a dedicated, unused native VLAN on inter-switch trunks -- never VLAN 1",
        "domain": "security",
        "priority": "High",
        "design_intent": "Carrying VLAN 1 (the default) as the untagged native VLAN on inter-switch trunks is "
        "both a hygiene gap and a concrete attack surface: where the native VLAN is also a user/data VLAN, an "
        "attacker can double-tag a frame (802.1Q VLAN-hopping) so the first (native) tag is stripped at the "
        "first trunk and the inner tag delivers it into another VLAN -- a one-way injection across a segment "
        "boundary. VLAN 1 also can't be cleanly pruned and tends to accumulate control traffic estate-wide. The "
        "target L2 design must set a dedicated, unused native VLAN on every trunk (or tag the native), and "
        "prune VLAN 1 from trunks, so the untagged path crosses no data segment.",
        "observable": "The engine parses switchport_mode and trunk_native_vlan per interface; trunks whose "
        "native VLAN is 1 are directly countable (interfaces[host][port]) -- the same field the workbook's "
        "trunk-native and archreview checks key off, so the count cannot drift.",
        "trigger": "One or more inter-switch trunks carry VLAN 1 as the native (untagged) VLAN -- an observed "
        "double-tag / VLAN-hopping exposure.",
        "recommended_action": "Assign a dedicated, unused native VLAN (not 1, not a data VLAN) on every "
        "inter-switch trunk and prune VLAN 1 from trunks; optionally enforce 'vlan dot1q tag native' so even "
        "the native VLAN is tagged. Apply it consistently on BOTH trunk ends (a native-VLAN mismatch is its own "
        "fault), and bake the chosen native VLAN into the target build template.",
        "alternatives": "Tag the native VLAN globally (vlan dot1q tag native) instead of choosing a dedicated "
        "one (closes the hop, keeps VLAN 1 plumbing); leave native as VLAN 1 and rely on access-edge controls "
        "only (weakest -- does not close the trunk-side double-tag vector).",
        "tradeoffs": "A dedicated native VLAN adds one VLAN id to the plan and a both-ends consistency "
        "requirement, but removes the untagged frame from every data segment and closes the VLAN-hopping vector.",
        "citation": "Cisco L2 security hardening (dedicated native VLAN, 'vlan dot1q tag native', prune VLAN 1); "
        "802.1Q double-tagging / VLAN-hopping; CIS Cisco benchmark trunk native-VLAN guidance.",
        "engine_actionable": True,
    },
    {
        "id": "design-resolve-false-health-masks-before-baseline",
        "title": "Resolve high-severity false-health masks (temporary bridges, masked faults) before baselining the design",
        "domain": "methodology",
        "priority": "High",
        "design_intent": "A target design and its NRFU baseline are only as trustworthy as the current-state "
        "picture they are built from. Some operational conditions actively MASK the true state: a temporary L2 "
        "bridge stood up as a workaround makes a broken or non-redundant path look healthy (the canonical "
        "NX-OS false-health class -- a 'show'-level green hiding a real gap), and a masked PoE/endpoint fault "
        "makes a degraded device look up. If the design is drawn -- or the cutover validated -- over that "
        "masked state, it inherits the hidden fault: redundancy that is not actually there, a loop risk left "
        "in place, or an acceptance test that certifies a lie. These high-severity false-health conditions "
        "must be surfaced, understood, and resolved (or explicitly risk-accepted) BEFORE the current-state "
        "baseline is frozen and the target is designed from it.",
        "observable": "The engine's false-health / operational-drift detector publishes operational_drift[] "
        "with severity + title + the masking devices. The HIGH-severity rows (temporary L2 bridges, masked "
        "PoE/endpoint faults) are the design-blocking masks; LOW rows (e.g. native-VLAN-1, long uptime) are "
        "owned by other detectors / informational and are excluded here -- so this never double-counts.",
        "trigger": "operational_drift carries one or more HIGH-severity false-health conditions -- an observed "
        "mask over the true redundancy/topology/health state.",
        "recommended_action": "For each high-severity false-health condition, determine what it is hiding (why "
        "the temporary bridge exists -- a failed uplink? a missing vPC peer-link? -- and what the masked fault "
        "is), remediate or remove the workaround, and re-collect so the current-state baseline reflects "
        "reality. Only then freeze the baseline, design the target from it, and take the NRFU pre-cutover "
        "snapshot. Track any condition that genuinely cannot be cleared pre-cutover as an explicit risk with "
        "an owner.",
        "alternatives": "Design over the masked state and discover the hidden fault at cutover (cheapest now, "
        "highest risk -- the mask becomes an outage when it is removed); leave the workaround permanently "
        "(accepts the false-health as the design, defeating the redundancy it hides).",
        "tradeoffs": "Clearing the masks costs investigation + remediation time before the design can be "
        "frozen, but it is the only way the current-state baseline -- and therefore the target design and the "
        "NRFU certification -- reflects the real network rather than a workaround hiding a fault.",
        "citation": "Cisco NX-OS operational-health guidance (a 'show'-level healthy state can mask a real "
        "gap); Cisco Advanced Services pre-cutover baseline discipline (design from verified current state).",
        "engine_actionable": True,
    },
    {
        "id": "dc-restore-degraded-portchannel-members-before-cutover",
        "title": "Restore degraded EtherChannel / port-channel members (down / suspended / standalone) before cutover",
        "domain": "dc-switching",
        "priority": "High",
        "design_intent": "A port-channel (EtherChannel / LAG) earns its bandwidth and link-level redundancy "
        "only while ALL its members are bundled and forwarding. A member in the down (D), suspended (s -- "
        "LACP/PAgP did not agree, so it is not forwarding), or standalone/individual (I -- running on its own, "
        "not in the bundle) state silently cuts the bundle's capacity and removes the very redundancy the LAG "
        "exists to provide -- and a 'show ... summary' often still reports the channel as Up, so it is a "
        "textbook false-health. Building or cutting over onto a bundle that is already running degraded "
        "inherits a hidden single-link exposure: the next member loss is then an outage, not a non-event. "
        "These degraded bundles must be diagnosed and restored to full membership BEFORE the design is "
        "baselined and the cutover is scheduled.",
        "observable": "The engine's protocol_intelligence axis emits per-switch EtherChannel member findings "
        "with a state (D/s/I) + severity + plain-language meaning -- directly observed; the engine's own "
        "High/Critical rating is read as-is (not re-derived).",
        "trigger": "protocol_intelligence carries one or more High/Critical EtherChannel member anomalies "
        "(member down / suspended / standalone) -- an observed degraded bundle.",
        "recommended_action": "For each degraded bundle, find why the member is not bundling (physical: "
        "cabling / SFP / errdisable; config: speed-duplex or LACP/PAgP mode/rate mismatch between the two "
        "ends) and restore full membership; verify all members are forwarding before freezing the "
        "current-state baseline and scheduling the cutover. In the target, keep LAG min-links / fast-LACP and "
        "member monitoring so a future member loss is alarmed, not silent.",
        "alternatives": "Cut over on the degraded bundle and remediate after (cheapest now, but the target "
        "starts a single failure from outage on that uplink); reduce the bundle to its working members as a "
        "documented interim if a member genuinely cannot be restored in the window (accepts lower capacity, "
        "explicitly).",
        "tradeoffs": "Restoring members costs pre-cutover diagnosis / field time, but it is the only way the "
        "target inherits the bundle's full bandwidth AND its link-level redundancy rather than a hidden "
        "single-link exposure.",
        "citation": "Cisco EtherChannel / LACP (IEEE 802.3ad / 802.1AX) member-state troubleshooting "
        "(D=down, s=suspended, I=standalone); Cisco port-channel design (min-links, mode/rate match).",
        "engine_actionable": True,
    },
    {
        "id": "dc-vpc-mlag-peer-fabric-integrity",
        "title": "Reconcile vPC / MLAG peer-fabric health (down* legs + consistency mismatches) before cutover",
        "domain": "dc-switching",
        "priority": "High",
        "design_intent": "A vPC / MLAG (multi-chassis EtherChannel) gives a dual-homed access device an "
        "active/active, loop-free uplink across two peers -- but only while the domain is healthy AND each "
        "member vPC is bundled on both peers. A member leg in 'down*' (the vPC is down on this peer, so the "
        "device behind it has lost one -- or, if both legs are down*, all -- of its dual-homing) or carrying a "
        "type-1/type-2 consistency mismatch (the two peers disagree on the port's config, so traffic on the "
        "affected VLANs is blocked) is phantom redundancy: the topology diagram shows an HA pair, the live "
        "fabric does not deliver it. A peer-adjacency, keepalive or peer-link fault at the domain level is "
        "worse -- it risks a split-brain / dual-active event at the moment of change. These must be diagnosed "
        "and reconciled BEFORE the current-state baseline is frozen and the cutover scheduled, or the target "
        "inherits redundancy that is not actually in service plus a latent consistency drift that drops traffic "
        "the first time the affected VLAN is exercised.",
        "observable": "The engine's vpc axis carries, per peer, the domain-level peer_status / keepalive_status "
        "/ global consistency / peer-link status AND each member vPC's status (up / down*) and per-vPC "
        "consistency -- all directly observed from 'show vpc'.",
        "trigger": "snap['vpc'] shows one or more member legs in a non-'up' (down*) state, one or more member "
        "legs with consistency != success, or a domain with a peer-adjacency / keepalive / peer-link fault.",
        "recommended_action": "For each down* member vPC, find why it is not bundling on one or both peers "
        "(downstream device down, port-channel member fault, or an admin-down leg) and either restore it or "
        "record it as intentionally single-attached; clear every type-1 (must-match) and type-2 consistency "
        "mismatch so the peers agree; confirm peer-link, keepalive and peer-adjacency are healthy on every "
        "domain. Verify each dual-homed device has BOTH legs 'up' before freezing the baseline. In the target, "
        "keep peer-link + keepalive monitored and a consistency-check alarm so a future drift is alarmed, not "
        "silent.",
        "alternatives": "Cut over on the degraded fabric and reconcile after (cheapest now, but the dual-homed "
        "estate starts a single failure -- or a consistency event -- from outage); convert genuinely "
        "single-attached devices to a documented orphan-port design rather than leaving them as down* vPCs "
        "(honest, removes the phantom-redundancy reading).",
        "tradeoffs": "Reconciling the fabric costs pre-cutover diagnosis and possibly field time, but it is the "
        "only way the target inherits the active/active redundancy the vPC design implies instead of a topology "
        "that looks redundant and is not.",
        "citation": "Cisco NX-OS vPC design & troubleshooting (peer-link / peer-keepalive, type-1/type-2 "
        "consistency, 'down*' member state); Cisco multi-chassis (vPC / VSS / MLAG) HA design guidance.",
        "engine_actionable": True,
    },
]
DOCTRINE.extend(_ACTIONABLE_DETECTOR_ADDENDUM_2)


# --------------------------------------------------------- ACI / EVPN / SP design-corpus addendum
# Mined from the real Cisco DC design corpus (ACI HLD/LLD/NIP -- NRG DC, EXPO2020 -- Cisco AS ACI
# Design & Deployment, Stretched Active-Active ACI, Transit Routing, ACI lessons-learned; native
# BGP-EVPN + PBB-EVPN deep-dives; SP BGP-LU; multicast snooping case studies), cross-checked with the
# CURRENT Cisco Nexus 9000 VXLAN BGP-EVPN design guidance + Nexus Dashboard (2026). The L1-L4 assessment
# collects NO ACI/APIC/controller/EPG/contract/policy state -> these are DOCTRINE the HLD narrative / chat
# / target-state reasoning cites (engine_actionable=False), NOT auto-detected claims. THE ONE EXCEPTION is
# the fabric OPERATING-MODEL choice below: like its sibling DC-fabric CHOICES (dc-three-tier-vs-collapsed,
# dc-spine-leaf-evpn-vs-collapsed) it is a REQUIREMENT-GATED decision the advisor DOES emit (via _NEEDS),
# so it is engine_actionable=True -- emitted as an open question, flipped to recommended once the
# fabric_operating_model requirement is supplied. Provenance: ORIGINAL re-expression of design FACTS /
# engineering doctrine; no verbatim source text is reproduced. Citations are for traceability only.
_ACI_CORPUS_ADDENDUM = [
 {
  "id": "dc-fabric-aci-vs-nxos-evpn-operating-model",
  "domain": "dc-fabric",
  "title": "Choose the DC fabric operating model: standalone NX-OS VXLAN-EVPN (default) vs Cisco ACI policy fabric",
  "priority": "High",
  "engine_actionable": True,
  "design_intent": "Migrating a flat, STP-bound L2 estate to a spine-leaf fabric with a distributed anycast "
    "gateway over a VXLAN data plane is one decision; HOW that fabric is operated and policed is a separate, "
    "top-down one. Cisco ACI realises it as an APIC-controlled, application-centric policy fabric (tenants / "
    "application-profiles / EPGs / contracts as a whitelist, service graph + PBR, identity micro-segmentation "
    "from a single declarative controller). Standalone NX-OS VXLAN BGP-EVPN realises the SAME forwarding "
    "outcome controller-less, on open standards, managed by Nexus Dashboard (NDFC). The choice is an "
    "operating-model decision -- not a forwarding one -- and must be driven by requirements, not assumed.",
  "tradeoffs": "manageability (single declarative controller + intent-based policy) vs simplicity & portability "
    "(open standards, no controller dependency, multivendor-transferable EVPN skills); security (controller-"
    "native identity micro-segmentation) vs operational familiarity; capex/opex and existing-investment lock-in.",
  "trigger": "A brownfield DC (or campus-DC) being migrated to a spine-leaf fabric, when the team must decide "
    "how the fabric is operated and segmented.",
  "observable": "Flat L2 / single global VRF / VLANs spanning many switches with a fabric refresh on the table "
    "-- the assessment sees the current state; the target operating model is a requirement, not an observable.",
  "recommended_action": "Default to standalone NX-OS VXLAN BGP-EVPN for new builds (open RFC 7432 EVPN / RFC "
    "8365 VXLAN / RFC 9135 IRB standards, portable multivendor skills, Nexus Dashboard / NDFC operations "
    "including IP Fabric for Media for broadcast/media estates, BGP-EVPN policy + VXLAN GPO group policy for "
    "segmentation). Choose Cisco ACI when an existing ACI estate, or an application-centric end-to-end identity "
    "micro-segmentation operating model, justifies a single declarative APIC controller. Note the 2026 "
    "trajectory: ACI is converging into the unified Nexus Dashboard / open-VXLAN-EVPN model (APIC federation + "
    "VXLAN GPO), which narrows ACI's once-unique segmentation advantage.",
  "alternatives": "A hybrid managed by Nexus Dashboard (NDO / NDFC) that federates ACI and NX-OS-EVPN domains "
    "where both already exist, presenting one policy and segmentation model across them.",
  "citation": "Cisco AS ACI Design & Deployment (Telco DC) + NRG / EXPO2020 ACI HLD/LLD operating model, "
    "cross-checked with the current Cisco Nexus 9000 VXLAN BGP-EVPN design guide + Nexus Dashboard (2026).",
 },
 # ---- ACI policy model (how a controller fabric segments + migrates) ----
 {
  "id": "aci-policy-network-centric-onramp-then-application-centric",
  "domain": "aci-policy",
  "title": "Migrate to ACI network-centric first (1 VLAN = 1 BD = 1 EPG), then evolve to application-centric",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "An ACI migration can model policy two ways. Network-centric maps each legacy VLAN almost "
    "one-to-one onto a Bridge Domain + EPG (often keeping gateways on external firewalls/routers and a permit-"
    "any contract), so the fabric reproduces today's L2 segments verbatim and the cutover is a low-risk like-"
    "for-like lift-and-shift. Application-centric groups endpoints into EPGs by application tier with allow-list "
    "contracts between them -- the real ACI value, but it needs a trustworthy application-dependency map.",
  "tradeoffs": "simplicity & convergence (reversible like-for-like cutover) vs security & manageability "
    "(the zero-trust micro-segmentation benefit is deferred); modularity comes only at the application-centric phase.",
  "trigger": "Planning the policy model for a brownfield-to-ACI migration.",
  "observable": "Flat L2 / per-VLAN segments with no documented application-flow map (the assessment sees VLANs, not app tiers).",
  "recommended_action": "Phase 1: instantiate a 1:1:1 VLAN-to-BD-to-EPG mapping (pervasive anycast gateway on "
    "the BD, or external gateways with permit-any) so endpoints move 1:1 and forwarding is proven. Phase 2: "
    "regroup EPGs into Application Profiles by tier and replace permit-any with least-privilege contracts as the "
    "application dependencies are documented post-cutover.",
  "alternatives": "Go straight to application-centric only when a reliable app-dependency map exists and downtime "
    "tolerance is high; stay permanently network-centric where the fabric is only ever a high-speed L2 transport.",
  "citation": "EXPO2020 ACI NIP/LLD (network-centric 1:1:1 VLAN-EPG-BD) + Cisco AS Secure Multi-Tenant ACI "
    "Design (Application-Centric vs Network-Centric), cross-checked with Cisco 'Migrating Existing Networks to ACI'.",
 },
 {
  "id": "aci-policy-epg-contract-whitelist-default-deny",
  "domain": "aci-policy",
  "title": "Segment with the EPG/contract whitelist (default-deny inter-EPG), seeded from the existing firewall policy",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "An application-centric fabric inverts the classic permit-by-default model: endpoints are "
    "grouped into EPGs by role (decoupled from VLAN/subnet), and NO EPG-to-EPG traffic flows until an explicit "
    "provider/consumer contract permits it -- a default-deny whitelist that IS the segmentation engine. Intra-EPG "
    "is open by default (tighten with intra-EPG isolation/micro-EPG for high-value tiers); vzAny binds a VRF-wide "
    "policy once. The network itself becomes the distributed enforcement point, not inline firewalls.",
  "tradeoffs": "security (explicit least-privilege, identity-follows-endpoint) vs manageability (contract sprawl; "
    "vzAny over-broadens if misused) and finite leaf policy-TCAM at scale.",
  "trigger": "Adopting ACI as the segmentation enforcement layer for an estate that needs east-west micro-segmentation.",
  "observable": "A flat estate where segmentation is by VLAN/subnet + inline firewall, with an existing firewall rule-base.",
  "recommended_action": "Model tenant -> VRF -> Application-Profile -> EPG with provider/consumer contracts as the "
    "segmentation layer (default-deny inter-EPG, contracts only where flows are required); seed the initial "
    "contract catalogue from the current firewall policy and bind a change process that updates contracts whenever "
    "firewall rules change; use vzAny for VRF-wide common policy and micro-EPG/intra-EPG isolation for high-value tiers.",
  "alternatives": "A documented permit-any (Preferred-Group / unenforced VRF) as a temporary cutover bridge, then "
    "tighten; standalone NX-OS VXLAN-EVPN with VXLAN GPO / SGT-ACL segmentation where no controller is adopted.",
  "citation": "EXPO2020 ACI LLD4 (Tenants/VRFs/EPGs/Contracts/vzAny) + ACI Network Implementation Plan (Contracts) "
    "+ ACI Security & Service Integration; web-verified against Cisco ACI Policy Model + Contract guides.",
 },
 {
  "id": "aci-policy-contract-route-is-not-reachability",
  "domain": "aci-policy",
  "title": "In a contract fabric, a route is not reachability: validate the programmed contract, not just the RIB",
  "priority": "Medium",
  "engine_actionable": False,
  "design_intent": "In an EPG/contract (whitelist) fabric, control-plane reachability and data-plane permission "
    "are decoupled by design. Two networks can each have a valid route in the RIB and still have ALL traffic "
    "dropped, because the default zoning rule is deny and no contract has been authored between their groups. This "
    "is the #1 ACI troubleshooting trap and a critical NRFU check -- 'the route is there' proves nothing.",
  "tradeoffs": "zero-trust default-deny security + explicit intent vs the operational burden of authoring a "
    "contract for every permitted relationship (and validating the programmed permit/deny, not just the route).",
  "trigger": "Validating connectivity (NRFU / troubleshooting) on a contract-based fabric.",
  "observable": "Two external/internal groups have routes but no contract between them.",
  "recommended_action": "Treat connectivity as route PLUS contract: enumerate the required inter-group flows as "
    "explicit contracts and validate the programmed deny/permit zoning rules, not route presence alone; make this "
    "an explicit NRFU acceptance item for any whitelist fabric.",
  "alternatives": "A traditional any-to-any L3 domain with ACLs trades segmentation for simplicity -- only where "
    "micro-segmentation is not required.",
  "citation": "Cisco ACI Contract Guide (implicit-deny drops a flow even with a route present; two L3Out external "
    "EPGs need a contract); web-verified.",
 },
 {
  "id": "aci-policy-vrf-scale-ceiling-legacy-l2-tradeoff",
  "domain": "aci-policy",
  "title": "At extreme overlapping-tenant scale, the VRF ceiling forces legacy-L2 BD mode -- and the loss of fabric policy",
  "priority": "Medium",
  "engine_actionable": False,
  "design_intent": "For massive multi-tenant 'bring-your-own-IP' scale there are two ways to host overlapping "
    "address space. VRF separation (one VRF per tenant) lets the fabric be the gateway with full routing / optimized-"
    "ARP / contract function, but the per-fabric VRF count is bounded. Beyond that ceiling the design must fall back "
    "to legacy L2-only BD mode (unicast routing off, flood mode) -- which buys very high segment density and "
    "overlapping-IP support but surrenders every value-added fabric feature (gateway, policy, optimized forwarding).",
  "tradeoffs": "a direct scalability-vs-capability axis: legacy L2 mode buys segment density + overlapping-IP at "
    "the cost of fabric routing, distributed gateway and contract policy (relocated to external routers).",
  "trigger": "Sizing a multi-tenant ACI fabric where tenant/VRF count may exceed the platform ceiling.",
  "observable": "A bring-your-own-IP / very-high-tenant-count requirement on a single fabric.",
  "recommended_action": "Stay VRF-per-tenant while tenant count fits the VRF budget and the fabric gateway/policy "
    "is wanted; switch a BD to legacy L2 mode only when segment scale demands it, and explicitly relocate gateway/"
    "routing/security to external devices; or partition tenants across multiple fabrics/pods to stay under the ceiling.",
  "alternatives": "Standalone NX-OS VXLAN/EVPN, where L2 scale and routing coexist differently; multiple fabrics/pods.",
  "citation": "Cisco AS ACI Practice (Service-Provider Cloud) -- overlapping networks / legacy BD mode / Tenant-"
    "Context-BD scale; web-confirmed against Cisco APIC scale docs.",
 },
 # ---- ACI L4-7 services (policy-driven insertion) ----
 {
  "id": "aci-services-servicegraph-pbr-symmetric-insertion",
  "domain": "aci-services",
  "title": "Insert L4-7 services via service-graph PBR (redirect BD, symmetric hashing, health-tracking, N+M), not by VLAN stitching",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "Rather than hard-wiring firewalls/load-balancers into the topology by VLAN stitching and "
    "default-gateway tricks, ACI attaches L4-7 functions to the CONTRACT between groups as a service graph: a "
    "redirect (PBR) action steers only the flows a contract selects through an ordered appliance chain, while the "
    "fabric stays every endpoint's gateway -- so an appliance can be inserted or removed with no readdressing or "
    "routing change. Correctness hinges on keeping both directions of a stateful flow on the same node.",
  "tradeoffs": "security & manageability (transparent, policy-driven, auditable insertion; no topology surgery) vs "
    "complexity (redirect BD with data-plane learning disabled, symmetric-hash, health groups, location awareness).",
  "trigger": "Inserting stateful firewalls/load-balancers into a policy fabric, especially a scaled appliance pool.",
  "observable": "Stateful services that today sit inline via VLAN stitching / as the default gateway.",
  "recommended_action": "Use service-graph + PBR with a dedicated redirect BD (endpoint data-plane learning off), "
    "symmetric sip-dip-protocol hashing so a flow pins to one node, health-group tracking that withdraws a node in "
    "BOTH directions on any leg failure, resilient hashing so only the failed node's flows rehash, and N+M backup "
    "sized so survivors are not overloaded; in Multi-Pod add location-based PBR awareness.",
  "alternatives": "Routed/inline firewall as the gateway (loses fabric-as-gateway and flexible steering) when "
    "readdressing is acceptable; a single active/standby appliance pair when throughput fits one node.",
  "citation": "EXPO2020 ACI LLD4 (PBR / Firewall integration / Anycast service) + ACI Security & Service "
    "Integration (Symmetric PBR, Tracking, Resilient-Hash, N+M); web-verified against Cisco PBR Service-Graph docs.",
 },
 # ---- ACI fabric structure / controller / external connectivity ----
 {
  "id": "aci-fabric-controller-cluster-odd-quorum-sharding",
  "domain": "aci-fabric",
  "title": "Size the policy-controller (APIC) cluster for quorum: odd >=3, sharded/replicated, minority degrades read-only -- never split-brain",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "A controller-managed fabric separates the clustered controllers (control/management plane) from "
    "the switches (data plane), so the fabric keeps forwarding even if the whole cluster is down -- but the cluster's "
    "OWN availability must be designed on quorum, not appliance count. Config is sharded across active-active "
    "controllers, each shard replicated (typically threefold) with one elected leader taking writes; a partitioned "
    "minority is read-only BY DESIGN (no split-brain writes) and reconciles by timestamp when quorum heals. Adding "
    "controllers scales fabric size, not resiliency.",
  "tradeoffs": "predictable management-plane availability + graceful read-only degradation vs cost/rigor (>=3 "
    "controllers, odd count, site spread, ordered add/remove, shard rebalancing on expansion).",
  "trigger": "Designing the controller-cluster placement/sizing for any SDN/controller-based fabric (e.g. ACI).",
  "observable": "A controller-based target where a partition could otherwise produce two writers.",
  "recommended_action": "Deploy an odd cluster of at least three controllers; rely on shard replication + per-shard "
    "leader election; spread members across pods/rooms/power and off the forwarding path; document that a minority "
    "is read-only-but-forwarding and freeze policy changes until majority recovers; scale the cluster for fabric "
    "size, not for HA.",
  "alternatives": "Larger odd clusters (5/7) when leaf scale demands it; for a non-controller fabric (NX-OS EVPN) "
    "this quorum concern disappears entirely -- there is no central controller.",
  "citation": "EXPO2020 ACI LLD4 + NRG ACI HLD + ACI Architecture (APIC clustering / sharding / leader election / "
    "minority behavior); web-verified against Cisco APIC Cluster Management (3-node quorum 2/3, 3-replica shards).",
 },
 {
  "id": "aci-fabric-access-policy-chain-ssot",
  "domain": "aci-fabric",
  "title": "Treat the APIC cluster + the VLAN-pool -> domain -> AEP -> EPG access-policy chain as the fabric's single source of truth",
  "priority": "Medium",
  "engine_actionable": False,
  "design_intent": "A controller-driven fabric centralises state in the APIC cluster and reaches the wire only "
    "through a disciplined access-policy chain: VLAN pool -> physical/external-routed domain -> Attachable Access "
    "Entity Profile (AEP) -> interface/switch profile -> EPG static binding. Skipping the discipline (GUI-wizard "
    "per-vPC config) yields duplicate-profile sprawl that defeats automation and audit. A clean, named, non-"
    "overlapping chain is what makes the fabric a true automatable single source of truth.",
  "tradeoffs": "a steeper modelling discipline up front vs manageability, scale and a genuine SSOT (clean pools/"
    "domains/AEPs make the fabric automatable and auditable).",
  "trigger": "Standing up an ACI fabric's access-policy model and naming conventions before scale-out.",
  "observable": "Greenfield fabric build, or an existing fabric configured ad hoc via per-object GUI wizards.",
  "recommended_action": "Define non-overlapping static VLAN pools per function, bind each to one domain and AEP, "
    "reuse named switch/interface profiles, and freeze a naming convention before scale-out; deploy an odd "
    "(three-node) APIC cluster as the policy SSOT.",
  "alternatives": "GUI-wizard-driven per-vPC configuration is faster initially but breeds duplicate-profile sprawl; "
    "single/dual controllers only in non-production where quorum loss is tolerable.",
  "citation": "Cisco AS Secure Multi-Tenant ACI Design (APIC Connectivity; Naming Conventions; Pools/Domains/AEPs); "
    "web-verified against Cisco APIC access-policy documentation.",
 },
 {
  "id": "aci-fabric-l3out-external-epg-classifies-not-filters",
  "domain": "aci-fabric",
  "title": "An L3Out external-EPG subnet is a security CLASSIFIER, not a route filter -- scope each flag to one purpose, never 0.0.0.0/0 to classify",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "On an ACI L3Out the external-subnet scopes each do exactly one job -- classify external traffic "
    "into an external EPG for contract enforcement, advertise a prefix outbound, gate a prefix inbound, or leak "
    "across a VRF. Conflating them (the 'tick every box until it works' anti-pattern) is a top field error: using "
    "0.0.0.0/0 as the classifier makes the policy tag non-unique and silently couples external networks.",
  "tradeoffs": "simplicity/manageability + security (a unique, prefix-scoped policy tag) vs the convenience of one "
    "catch-all 0/0 entry (which trades away classification precision and invites collisions).",
  "trigger": "Designing external (north-south) connectivity and its security policy on an ACI fabric.",
  "observable": "One L3Out serving multiple external peers/policies, or 0.0.0.0/0 used as a classification subnet.",
  "recommended_action": "Scope each external-subnet flag to its single purpose: a specific classification prefix "
    "per external EPG (avoid 0/0 so the policy tag stays unique), Export/Import Route Control only to advertise/gate "
    "routes, Shared Route-Control + Shared-Security for deliberate inter-VRF leaks; advertise BD subnets explicitly, "
    "never by default; isolate a peer needing a default classification on its own dedicated L3Out.",
  "alternatives": "A single 0/0 external EPG only where all external traffic is genuinely treated identically (a "
    "true single-exit stub).",
  "citation": "ACI Best Practices: Lessons from the Front Lines (Cisco SEVT) + ACI NIP (External EPGs / BD Subnet "
    "Advertisement) + ACI Transit Routing; web-verified against Cisco APIC L3 Networking guide.",
 },
 {
  "id": "aci-fabric-l3out-one-uniform-policy-split-into-l3outs",
  "domain": "aci-fabric",
  "title": "An ACI L3Out applies ONE uniform routing+security policy to all its peers -- split into separate L3Outs for per-exit policy, don't toggle flags on one",
  "priority": "Medium",
  "engine_actionable": False,
  "design_intent": "The L3Out is ACI's unit of policy granularity: every route and peer under a single L3Out gets "
    "the SAME routing policy and the same security policy. Requirements like 'Prod may use only WAN1' or 'prefer "
    "WAN1, fail to WAN2' cannot be met by toggling flags on one stretched L3Out; they need separate L3Outs (or, for "
    "security alone, separate external EPGs). The fabric is a stub by default -- transit between two L3Outs is an "
    "explicit act (export only the required prefixes; never a 0/0 default as the coupling mechanism).",
  "tradeoffs": "per-exit routing/security precision vs more configuration objects and state; centralised inter-VRF "
    "leak (via a fusion router) vs an extra external routing hop.",
  "trigger": "Designing multi-exit external routing or differentiated north-south policy on ACI.",
  "observable": "A single L3Out asked to carry differentiated per-exit routing or security policy.",
  "recommended_action": "Provision one L3Out per distinct routing-or-security policy domain; bind contracts between "
    "the specific source EPG and the intended external EPG; enable transit explicitly (export only required "
    "prefixes); leak inter-VRF/transit routes via an external fusion router (matching VRF per fabric VRF) where "
    "native shared-L3Out scale does not fit.",
  "alternatives": "Keep one L3Out and shift differentiation onto the external router (metrics/attributes) when ACI-"
    "side per-exit policy is not required; native shared-L3Out / inter-VRF contract leaking where scale permits.",
  "citation": "ACI Best Practices: Lessons from the Front Lines (Cisco SEVT) + ACI Transit Routing + EXPO2020 ACI "
    "LLD4 (L3Out / external EPG / fusion route-leak); web-verified against Cisco APIC L3 guide.",
 },
 {
  "id": "aci-fabric-gateway-anchor-firewall-vs-fabric",
  "domain": "aci-fabric",
  "title": "Choose the default-gateway anchor deliberately per tier (firewall vs fabric); an external-service gateway forces that BD into L2-transport mode",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "In a policy fabric the first-hop gateway can live in three places, each forcing a different "
    "traffic pattern: firewall-as-gateway (fabric is pure L2 transit; every flow is inspected), fabric-as-gateway "
    "with a default-route-to-firewall (only internet traffic is inspected; intranet is fabric-routed), or fabric-as-"
    "gateway with iBGP to a border router. Critically, if an external service device IS the gateway, the fabric's "
    "optimisations (IP routing, ARP suppression, IP+MAC learning) BREAK that BD -- it must be set to L2-transport "
    "(unicast routing off, ARP/unknown-unicast flood, MAC forwarding) or traffic black-holes.",
  "tradeoffs": "security/inspection coverage vs path efficiency/convergence (firewall-anchored maximises inspection "
    "but makes the firewall a chokepoint); correctness (dumb-L2 transport forwards reliably) vs giving up fabric "
    "routing efficiency and the distributed anycast gateway.",
  "trigger": "Deciding where each tier's first-hop gateway lives on a policy fabric.",
  "observable": "A tier whose gateway is (or must remain) an external firewall/router, vs one the fabric can own.",
  "recommended_action": "Anchor untrusted/regulated tiers on the firewall for full inspection; for tiers needing "
    "efficient intranet reach, place the gateway on the fabric with default-route-to-firewall + more-specific "
    "intranet routes; for every BD whose gateway is an external service device, explicitly set the fabric to L2-"
    "transport mode (no unicast routing, ARP flood, MAC forwarding) and run device-to-router dynamic routing "
    "directly between the appliances.",
  "alternatives": "Uniform firewall-as-gateway for a strict inspect-everything posture; uniform fabric distributed-"
    "anycast gateway with selective service-graph/PBR redirection where no requirement forces an external gateway.",
  "citation": "Cisco AS ACI Design & Deployment (Telco DC) -- Firewall-as-Gateway / Fabric-as-Gateway / iBGP-to-ASR "
    "+ ACI Architecture (Traditional Services Insertion, MAC forwarding); web-verified against Cisco ACI L3Out/BD docs.",
 },
 {
  "id": "aci-fabric-bpdu-transparency-edge-loop-protection",
  "domain": "aci-fabric",
  "title": "An ACI access edge is STP-transparent: flood external BPDUs within the EPG so outside STP breaks loops, and add MCP / Rogue-EP / port-tracking as the fabric's own safeguards",
  "priority": "Medium",
  "engine_actionable": False,
  "design_intent": "An ACI fabric runs no spanning tree. On an access port it floods received BPDUs to the other "
    "ports of the same EPG, so to an external switch the fabric looks like a wire and the EXTERNAL switches' STP "
    "elects roots and blocks the loop-causing port. The design consequence: during coexistence you must NOT filter/"
    "guard those external BPDUs (or you blind the only loop-breaker), and you must add the fabric's own intrinsic "
    "safeguards -- MisCabling Protocol (MCP), Rogue-EP control, uplink port-tracking -- to catch what external STP cannot.",
  "tradeoffs": "availability (external STP still protects against L2 loops during coexistence; MCP/Rogue-EP catch "
    "mobility/miscabling faults) vs simplicity (guard/filter placement must be exactly right).",
  "trigger": "Connecting an ACI fabric to a legacy STP L2 domain during migration coexistence.",
  "observable": "External switches/blade chassis attached to the fabric while the legacy STP domain still exists.",
  "recommended_action": "Leave BPDU filter/guard DISABLED on ports toward external switches/blade chassis so their "
    "STP keeps converging; enable BPDU guard only on host ports; enable MCP (with a key), Rogue-EP control and "
    "uplink port-tracking as the fabric's intrinsic loop/mobility safeguards. A clean single L2 handoff that drops "
    "BPDUs is appropriate only once the legacy STP domain is retired.",
  "alternatives": "A single clean L2 handoff that drops external BPDUs entirely -- only after the legacy STP domain "
    "is decommissioned.",
  "citation": "Cisco ACI design doctrine (NIP STP BPDU Filter/Guard + Global Policies / MCP / Rogue-EP), grounded in "
    "the D:\\ ACI corpus; web-verified that ACI runs no STP and floods BPDUs within the EPG.",
 },
 # ---- ACI multi-pod / multi-site (geo extension of a controller fabric) ----
 {
  "id": "aci-multisite-multipod-vs-multisite-choice",
  "domain": "aci-multisite",
  "title": "Multi-Pod (one stretched policy domain) vs Multi-Site (isolated domains) is a failure-isolation choice -- and Multi-Pod needs a witness pod for cluster quorum on a site loss",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "Extending a policy fabric across rooms/sites is a spectrum. Multi-Pod keeps a SINGLE controller/"
    "policy domain spanning all pods (one change applies everywhere; controllers spread across pods for resiliency) "
    "with per-pod control-plane fault isolation -- seamless workload mobility, but one shared change/blast domain. "
    "Multi-Site federates INDEPENDENT fabrics/APIC-clusters with templated policy -- stronger fault and config "
    "isolation, independent upgrade cadence, at the cost of single-pane simplicity. Because Multi-Pod is one "
    "controller cluster, a two-site split needs a third (witness) pod or the cluster loses quorum on a site loss.",
  "tradeoffs": "single-domain simplicity + seamless mobility (Multi-Pod) vs strong failure/config isolation + "
    "independent change windows (Multi-Site); plus the controller-quorum constraint across sites.",
  "trigger": "Extending an ACI fabric across multiple rooms, buildings or data centres.",
  "observable": "A multi-room/multi-site estate with a stated fault-containment / DR-isolation requirement (or lack of one).",
  "recommended_action": "Select Multi-Pod for one stretched policy domain with per-pod fault isolation (and place a "
    "third/witness pod to preserve APIC quorum on a site loss, degrading to read-only -- never two writers); select "
    "Multi-Site for independently-failing domains with templated policy and independent upgrades.",
  "alternatives": "Stretched-fabric or standalone NX-OS EVPN multi-site for non-controller designs; per-site "
    "independent fabrics where no third location exists.",
  "citation": "EXPO2020 ACI NIP/LLD4 (Multi-Pod over IPN, 3-node APIC quorum + Witness pod) + ACI Stretched Active-"
    "Active WP; web-verified against Cisco ACI Multi-Pod / Multi-Site white papers (c11-737855 / c11-739714).",
 },
 {
  "id": "aci-multisite-ipn-underlay-is-a-first-class-dependency",
  "domain": "aci-multisite",
  "title": "ACI Multi-Pod hinges on a qualified IPN underlay (PIM-Bidir + phantom-RP, jumbo MTU, OSPF, DHCP-relay); a stretched subnet needs host-route advertisement to avoid asymmetric egress",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "ACI Multi-Pod is one fabric stretched over an Inter-Pod Network, so the IPN is a hard-"
    "requirement transit, not an afterthought: it must carry PIM-Bidir for BUM (with a phantom-RP for redundancy, "
    "since anycast-RP is unsupported), jumbo MTU (9000+) for VXLAN, DHCP-relay for cross-pod node discovery, and "
    "OSPF for TEP-pool reachability with the RP path engineered OFF the spines. A subnet stretched across pods needs "
    "host-route advertisement (or GOLF) or ingress traffic egresses asymmetrically.",
  "tradeoffs": "availability/operational-simplicity (one fabric, one APIC cluster, stretched L3Outs) vs a shared "
    "failure domain AND a strict, multicast-capable underlay that becomes a first-class design dependency.",
  "trigger": "Committing to ACI Multi-Pod over an inter-pod/inter-room transport.",
  "observable": "A metro/multi-room estate proposed as one stretched ACI fabric, with an inter-pod L3 transport.",
  "recommended_action": "Qualify the IPN for PIM-Bidir (phantom-RP, hardware Bidir support, P2P OSPF loopbacks), "
    "jumbo MTU, DHCP-relay and routed subinterfaces BEFORE committing to Multi-Pod; raise OSPF cost on spine-IPN "
    "links so the RP path avoids spines; assign an anycast TEP/ETEP per pod as the next-hop; use spine route-"
    "reflector peering for pod scale; and for any cross-pod subnet plan host-route advertisement.",
  "alternatives": "ACI Multi-Site (separate fabrics, separate APIC clusters, no IPN multicast, latency-tolerant) "
    "where DR-grade fault containment outweighs stretched-L3Out simplicity.",
  "citation": "ACI NIP (Multi-Pod / IPN) + ACI Best Practices: Lessons from the Front Lines (Inter-Pod Network "
    "Requirements) + EXPO2020 ACI LLD4; web-verified against Cisco ACI Multi-Pod white papers.",
 },
 # ---- standards-based EVPN (the standalone NX-OS alternative's control plane) ----
 {
  "id": "evpn-esi-all-active-multihoming",
  "domain": "evpn",
  "title": "Use standards-based EVPN ESI all-active multihoming, not proprietary MC-LAG/vPC, to drop the peer-link and the two-chassis ceiling",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "Legacy multihoming (vPC/VSS/cluster) bonds exactly two boxes through a dedicated inter-chassis "
    "link that carries synchronisation state and orphan traffic -- capping redundancy at a dual-homed pair and "
    "coupling the two chassis. EVPN signals a shared Ethernet Segment Identifier (ESI) in the BGP control plane "
    "(Type-4 Ethernet-Segment + Type-1 Ethernet A-D routes) so MORE than two PEs can forward all-active for the same "
    "segment with no inter-chassis link, using aliasing for load-balancing -- a standards-based, multivendor design.",
  "tradeoffs": "removes the inter-chassis link as a shared-fate component and lifts the two-box ceiling, at the cost "
    "of a BGP-EVPN control-plane dependency (and the operational familiarity of a simple MC-LAG peer-link).",
  "trigger": "Designing redundant host/switch attachment on a VXLAN-EVPN fabric.",
  "observable": "Dual-homed endpoints today served by vPC/VSS/MC-LAG with a peer-link.",
  "recommended_action": "Specify EVPN ESI-based all-active multihoming (auto-derived or manual ESI, advertised via "
    "the Ethernet-Segment route) for dual/multi-attached endpoints; reserve single-active per-service mode for cases "
    "where the CE cannot run a single LACP bundle across PEs.",
  "alternatives": "Proprietary MC-LAG (vPC/VSS/StackWise-Virtual) where two-box dual-homing + a peer-link are "
    "acceptable and EVPN skills are absent; single-active per-service where a simpler failure model suffices.",
  "citation": "RFC 7432 (BGP-MPLS-Based EVPN) §8 Multi-Homing Functions -- Type-4 Ethernet-Segment + Type-1 Ethernet "
    "A-D routes, ESI, aliasing, DF election; web-verified against RFC 7432.",
 },
 {
  "id": "evpn-bum-df-election-split-horizon",
  "domain": "evpn",
  "title": "Make all-active multihoming loop-free and duplicate-free with designated-forwarder election plus a split-horizon segment label",
  "priority": "Medium",
  "engine_actionable": False,
  "design_intent": "When several PEs forward all-active for the same Ethernet Segment, naive flooding would loop "
    "BUM frames back to the originating site and deliver duplicate copies to a multihomed receiver -- the exact "
    "pathologies that sank flat VPLS. EVPN closes both: per-segment split-horizon filtering (an ESI label) stops a "
    "PE forwarding BUM back onto the segment it arrived from, and per-EVI Designated-Forwarder election (from the "
    "Type-4 Ethernet-Segment route) ensures exactly one PE delivers BUM to a multihomed CE.",
  "tradeoffs": "a loop-free, duplicate-free all-active L2 service vs extra control-plane state (segment routes, "
    "per-EVI DF state, split-horizon labels) and a DF-failover convergence event to engineer.",
  "trigger": "Deploying EVPN all-active multihoming (the loop/duplicate-prevention design that makes it safe).",
  "observable": "Multiple PEs forwarding for the same Ethernet Segment (the all-active multihoming design).",
  "recommended_action": "Specify per-EVI DF election and per-segment split-horizon filtering for every multihomed "
    "Ethernet Segment; rely on segment auto-discovery (ES-import-filtered) for peer agreement; and explicitly set/"
    "justify the peering and recovery timers that govern BUM forwarding during failover.",
  "alternatives": "Single-active multihoming (one forwarder per service) where the simpler failure model is "
    "acceptable and per-flow load-balancing is not needed.",
  "citation": "RFC 7432 (Route-Type 4 Ethernet-Segment = DF election; split-horizon/ESI label) + native EVPN "
    "deep-dive (DF Election / Split-Horizon / Aliasing); web-verified against RFC 7432.",
 },
 # ---- service-provider transport (seamless MPLS) ----
 {
  "id": "sp-mpls-bgp-lu-seamless-unified-transport",
  "domain": "sp-mpls",
  "title": "Use BGP labeled-unicast to stitch one end-to-end LSP across a domain/AS boundary with no shared IGP/LDP",
  "priority": "Medium",
  "engine_actionable": False,
  "design_intent": "When an MPLS service must cross a boundary where the two sides share no IGP and no LDP adjacency "
    "(access/aggregation vs core, or two ASes), there is a gap in the label-switched path and any service that "
    "relies on an end-to-end LSP (a pseudowire or L3VPN) cannot form. BGP labeled-unicast advertises the transport/"
    "service endpoints WITH labels across the seam (eBGP between border nodes and the remote PE), yielding one "
    "contiguous LSP -- 'seamless / unified MPLS' -- while each domain keeps its own small IGP+LDP.",
  "tradeoffs": "scalability + modularity (each domain keeps a small IGP/LDP and AS independence; no flat merged "
    "label domain) and a single federated transport vs an extra BGP control-plane layer to operate.",
  "trigger": "Carrying an MPLS service (pseudowire / L3VPN) across an IGP/LDP or AS boundary.",
  "observable": "Two MPLS domains/ASes that must carry an end-to-end LSP but share no IGP/LDP adjacency.",
  "recommended_action": "Scope IGP+LDP inside each domain; add a BGP labeled-unicast session across the seam (eBGP "
    "between border nodes and the remote PE) advertising only the service/transport endpoints with labels for a "
    "contiguous end-to-end LSP; carry the customer service as a pseudowire/VPN over it.",
  "alternatives": "A single flat IGP+LDP domain end to end (simplest control plane, but largest fault/label domain "
    "and no AS independence); inter-domain MPLS-TE tunnels stitched across the seam.",
  "citation": "BGP-LU on the TIM OPM network (Overview / Topology / Packet forwarding); web-verified against RFC "
    "8277 (Using BGP to Bind MPLS Labels to Address Prefixes, obsoletes RFC 3107).",
 },
 # ---- enrichments to existing domains (security / multicast) ----
 {
  "id": "security-management-plane-source-allowlist",
  "domain": "security",
  "title": "Filter the management plane (VTY/SNMP) to an explicit allowlist of NMS/NOC/VPN source prefixes -- not just SSH-only",
  "priority": "Medium",
  "engine_actionable": False,
  "design_intent": "SSH and AAA authenticate WHO connects; they do not constrain WHERE connections may originate. "
    "Binding a per-line VTY access-class and an SNMP-server ACL that permit ONLY the known management source "
    "networks (jump hosts, NMS/monitoring, management VPN, NOC out-of-band) shrinks the management attack surface to "
    "a handful of prefixes -- a distinct hardening layer beyond protocol security and RBAC. On a device with a "
    "management VRF, the access-class must include the VRF path ('in vrf-also').",
  "tradeoffs": "hardens the management plane (security) vs an ACL to maintain and a lock-out risk if management "
    "source ranges change without updating it.",
  "trigger": "Hardening the management plane of routers/switches beyond protocol security.",
  "observable": "Devices reachable for management from anywhere (SSH/SNMP open to all sources), no source allowlist.",
  "recommended_action": "Define a management source allowlist (NMS, monitoring, management VPN, NOC OOB) and enforce "
    "it with a per-line VTY access-class plus an SNMP-server ACL on every device tier; include the management-VRF "
    "path ('in vrf-also'); pair with SSH-only, exec-timeout and a legal login banner.",
  "alternatives": "SSH-only + AAA with no source filter (authenticated but reachable from everywhere -- larger "
    "surface); push all management onto a physically separate OOB network.",
  "citation": "EXPO2020 PSN Infra Hardening MOP (VTY access-class 'in vrf-also'; SNMP-server use-ipv4acl; exec-"
    "timeout); web-verified against Cisco IOS/IOS-XE management-plane hardening guidance.",
 },
 {
  "id": "multicast-snooping-without-querier-is-platform-dependent-not-fail-open",
  "domain": "multicast",
  "title": "Never assume a missing IGMP querier fails open: snooping-without-querier floods on some platforms and black-holes on others -- guarantee a querier",
  "priority": "Medium",
  "engine_actionable": False,
  "design_intent": "When IGMP snooping is enabled but no querier (router or configured switch) exists on a VLAN, the "
    "snooping state is never primed and the resulting behaviour is PLATFORM-DEPENDENT: some switch families fall "
    "back to flooding the multicast VLAN-wide (degraded but delivering), while others prune and BLACK-HOLE the "
    "groups. 'Snooping with no querier is harmless flooding' is a false-health assumption that silently breaks media "
    "delivery on the wrong platform -- and a stranded-multicast trap at cutover.",
  "tradeoffs": "guaranteed delivery vs the operational cost of explicitly owning a querier per active multicast VLAN "
    "(availability/correctness over an assumed-safe default).",
  "trigger": "Designing or validating L2 multicast (IGMP snooping) for a media/broadcast estate.",
  "observable": "An active multicast VLAN with snooping enabled but no confirmed querier (router or designated switch).",
  "recommended_action": "Require a confirmed IGMP querier on every active multicast VLAN (a router by default, else "
    "the designated lowest-IP snooping switch); do not depend on the snooping-flood fallback as a safety net; in "
    "mixed fleets explicitly verify the no-querier behaviour of the receiver-hosting platforms before cutover.",
  "alternatives": "Designate a snooping switch as querier where no router exists; disable snooping on a VLAN only "
    "where intentional VLAN-wide flooding is acceptable.",
  "citation": "Cisco IGMP-snooping case study (no-mrouter/querier behaviour differs across Catalyst families -- some "
    "flood, some prune); web-verified that no-querier snooping behaviour is implementation-specific, not standardised.",
 },
 # ---- change-execution rigor (distinct from the config-automation TOOLING principle) ----
 {
  "id": "methodology-tested-rollback-restores-exact-prior-state",
  "domain": "methodology",
  "title": "Pair every change step with a defined, TESTED rollback that restores the exact prior state, then verify the rollback",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "A change is only as safe as its reversibility, and 'we have a rollback plan' is not the same as "
    "a rollback that has been proven to work. Each block of applied commands must have a matching undo that returns "
    "the device to its captured pre-change configuration, the undo itself must be dry-run, and the rollback must end "
    "with explicit post-rollback verification against the pre-change baseline -- because an unverified rollback can "
    "leave the device in a third, worse state. This is change-EXECUTION rigor, distinct from config-management "
    "tooling (version control / drift detection): it governs how a single maintenance-window step is made reversible.",
  "tradeoffs": "manageability/cost (authoring and dry-running the undo doubles the effort and adds verification "
    "steps) vs a bounded worst-case blast radius and a recovery the team has actually tested, not assumed.",
  "trigger": "Authoring a MOP / cutover change step for a production maintenance window.",
  "observable": "Change steps with a forward procedure but no tested, state-restoring undo and no post-rollback check.",
  "recommended_action": "For every change block, author the exact reverse commands, dry-run them, and add explicit "
    "post-rollback verification that the device matches its captured pre-change baseline; keep each step "
    "independently reversible and capture the pre-change state before touching the device.",
  "alternatives": "Forward-only change with 'reimage/reload from backup' as the only recovery (simpler to write, "
    "slower and riskier to execute); staged build-before-break, where the legacy path itself is the rollback.",
  "citation": "EXPO2020 PSN Infra Hardening MOP §5 Rollback plan (§5.1 Undo the changes / §5.1.1 Post-Rollback "
    "checks); aligns with Cisco change-management leading practice. Distinct from mgmt-change-config-mgmt-automation.",
 },
]
DOCTRINE.extend(_ACI_CORPUS_ADDENDUM)


# ------------------------------------------------------- Service-Provider / Segment-Routing addendum
# Mined from the D:\\ SP/transport design corpus (Orhan Ergun CCIE-SP design-comparison charts + inter-AS
# L3VPN workbooks, a real Segment-Routing Phase-2 test report, Cisco MPLS L2/L3-VPN troubleshooting course,
# Nick Russo CCIE-SP comp guide) and a dedicated SR/SRv6 + ngMVPN web-research pass. EVERY principle here is
# DOCTRINE (engine_actionable=False) with NO exception: an L1-L4 ENTERPRISE brownfield assessment collects no
# SR/LDP/RSVP/MP-BGP-VPN/MVPN/L2VPN control-plane state, so the design brain cites these for SP-flavoured
# engagements + the HLD narrative + chat, never as auto-detected findings. (The VPLS-flood-domain and no-PE-
# loopback-summarization rules have a plausible FUTURE evidence trigger -- spanning_vlans / IGP summarization
# -- but stay doctrine until a detector is actually wired and locked by test_every_engine_actionable_principle
# _is_emitted.) Standards are web-verified (note: TI-LFA is now RFC 9855, Oct 2025 -- no longer a draft).
# Provenance: ORIGINAL re-expression of design facts/doctrine; no verbatim source text.
_SP_CORPUS_ADDENDUM = [
 # ---- Segment Routing (SR-MPLS / SRv6): control-plane collapse + resilience ----
 {
  "id": "sp-sr-mpls-collapse-ldp-rsvp-to-igp-sid",
  "domain": "segment-routing",
  "title": "Collapse LDP + RSVP-TE onto one IGP-distributed SID plane (SR-MPLS) to delete transport control-plane state",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "Classic MPLS runs three transport control planes in lockstep -- the IGP for reachability, "
    "LDP for label binding, and RSVP-TE for engineered tunnels -- each with its own adjacency, state machine, "
    "soft-state refresh and failure mode (LDP-IGP synchronization exists only to paper over the seam between two "
    "of them). Segment Routing carries the labels IN the link-state IGP itself: a global prefix-SID per node "
    "loopback and a local adjacency-SID per link, so LDP and RSVP-TE can be retired and forwarding state lives "
    "only at the edge.",
  "tradeoffs": "simplicity & manageability (one control plane, no LDP/RSVP soft-state or LDP-IGP-sync) and "
    "scalability vs a one-time forklift of doctrine + platform SR-capability + label-planning discipline (a "
    "managed, contiguous, fleet-consistent SRGB).",
  "trigger": "Designing or modernising an MPLS transport core where the platform supports SR.",
  "observable": "Not collected by an L1-L4 enterprise assessment (no LDP/RSVP/SR core state); applies to an "
    "SP/MPLS transport design engagement.",
  "recommended_action": "On an SR-capable target, run SR-MPLS over a single link-state IGP (IS-IS preferred for "
    "SP-scale multi-level + wide metrics; OSPF acceptable), advertise a prefix-SID per node loopback from a "
    "domain-wide consistent SRGB plus adjacency-SIDs per link, then decommission LDP and RSVP-TE once SR "
    "forwarding is verified end-to-end.",
  "alternatives": "Keep LDP where the core is pure best-effort IP-VPN transport with no TE need and the platform "
    "will never gain SR (LDP is simpler to adopt incrementally on a legacy base); SRv6 (RFC 8986) where an "
    "MPLS-free IPv6 data plane + network programming is wanted.",
  "citation": "RFC 8402 (Segment Routing Architecture) + RFC 8660 (SR-MPLS data plane) + Nick Russo CCIE-SP SR "
    "chapter; web-verified.",
 },
 {
  "id": "sp-sr-srgb-homogeneous-non-overlapping-global-block",
  "domain": "segment-routing",
  "title": "Reserve one non-overlapping SRGB and make it identical fleet-wide for deterministic end-to-end SR labels",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "The Segment Routing Global Block (SRGB) is the label range a router derives prefix-SID labels "
    "from -- a node computes a prefix's local label as its own SRGB lower bound plus the advertised prefix-SID "
    "index. Two rules follow: the SRGB must NOT overlap the platform's dynamic global MPLS label pool, and "
    "making it identical on every node means a prefix-SID index yields the SAME absolute label everywhere -- one "
    "global label identifies a destination across the whole domain, so traces and troubleshooting are readable.",
  "tradeoffs": "manageability/operability (one label identifies a destination everywhere; deterministic traces) "
    "vs label-space planning discipline (a reserved, documented, domain-wide constant block).",
  "trigger": "Planning the SR label scheme for an SR-MPLS domain.",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to SR-MPLS design.",
  "recommended_action": "Allocate one reserved SRGB that is identical on all SR nodes and provably disjoint from "
    "the dynamic MPLS label pool; document its lower bound and size as a domain-wide constant so prefix-SID "
    "indices map to the same absolute label on every hop.",
  "alternatives": "Per-node heterogeneous SRGBs are tolerable for small labs or where vendors disagree on default "
    "ranges -- accepting that label values differ per hop and complicate operational tooling.",
  "citation": "RFC 8402 + RFC 8660 (SR-MPLS data plane / SRGB) + Nick Russo CCIE-SP SR chapter; web-verified.",
 },
 {
  "id": "sp-sr-ti-lfa-guaranteed-postconvergence-repair",
  "domain": "segment-routing",
  "title": "Use TI-LFA for 100% single-failure coverage on the actual post-convergence path, not best-effort LFA",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "Classic LFA / remote-LFA give a backup only where a loop-free neighbour happens to exist, so "
    "coverage is topology-dependent (ring and square topologies leave protection holes) and the repair path often "
    "differs from where the IGP will actually settle -- causing a second, disruptive reroute. TI-LFA uses an SR "
    "repair SID-list to steer traffic down the EXACT post-convergence path, giving near-100% link/node/SRLG "
    "coverage in any two-connected topology with no transient micro-loop.",
  "tradeoffs": "availability + fast convergence + determinism (guaranteed coverage on the settled path) vs deeper "
    "repair label stacks (verify platform push limits) and the SR prerequisite.",
  "trigger": "Engineering fast-reroute on an SR IGP, especially over rings/spoke topologies with thin protection.",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to SR-MPLS/SRv6 FRR design.",
  "recommended_action": "Enable TI-LFA for link, node and SRLG protection across the SR IGP so every destination "
    "has a precomputed post-convergence repair SID-list; define SRLGs so fate-shared fibres/conduits are not each "
    "other's backup; verify the repair label-stack depth is within platform push limits before commit; pair with "
    "IGP micro-loop avoidance.",
  "alternatives": "Plain LFA/remote-LFA only on rich-mesh topologies where coverage is already ~100%; RSVP-TE FRR "
    "(facility/one-to-one backup) where an existing mature RSVP deployment dominates.",
  "citation": "RFC 9855 (Topology Independent Fast Reroute Using Segment Routing -- Standards Track, Oct 2025; "
    "supersedes the long-running draft) + RFC 8402; web-verified.",
 },
 {
  "id": "sp-sr-ldp-interworking-mapping-server-for-migration",
  "domain": "segment-routing",
  "title": "Migrate LDP to SR incrementally with an SR Mapping Server (SRMS) and contiguous loopback blocks",
  "priority": "Medium",
  "engine_actionable": False,
  "design_intent": "A brownfield core cannot flip to SR atomically -- some nodes lag in hardware/NOS support. The "
    "SR Mapping Server advertises prefix-SID bindings ON BEHALF OF LDP-only routers so SR and LDP islands "
    "interwork during a phased cutover -- a build-before-break migration, not a flag-day. Pre-planning loopbacks "
    "as contiguous /32 blocks lets one mapping range cover many nodes and keeps the interworking footprint small.",
  "tradeoffs": "migration safety + continuity (incremental coexistence, reversible per node) vs transitional "
    "complexity (a temporary dual control plane + label-preference rules during the overlap).",
  "trigger": "Cutting a brownfield LDP core over to SR-MPLS.",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to an SR migration.",
  "recommended_action": "Stage the LDP->SR migration through an SRMS (advertise-local on the server, receive on "
    "clients) so SR and LDP islands coexist; carve the SRGB clear of LDP's dynamic labels and set SR-preferred "
    "label preference; pre-plan loopbacks as contiguous /32 blocks so a single mapping range covers many nodes.",
  "alternatives": "A flag-day cutover only on a small, fully SR-capable core in a maintenance window; per-node "
    "ships-in-the-night LDP+SR without an SRMS where every node is already SR-capable.",
  "citation": "RFC 8661 (Segment Routing MPLS Interworking with LDP -- defines the SR Mapping Server) + Nick "
    "Russo CCIE-SP SR chapter; web-verified.",
 },
 {
  "id": "sp-srte-prefix-sid-vs-adjacency-sid-and-explicit-path-validation",
  "domain": "segment-routing",
  "title": "Encode SR-TE paths with prefix-SIDs for resilience; reserve adjacency-SID explicit paths for strict steering, and guard the no-validation blackhole",
  "priority": "Medium",
  "engine_actionable": False,
  "design_intent": "An SR-TE path is a resilience-vs-precision trade. A prefix-SID (node-SID) path is interface-"
    "independent -- it survives local link failures and pushes the fewest labels, and an anycast prefix-SID adds "
    "node redundancy. An adjacency-SID / strict-label path pins the LSP to specific interfaces (exact steering) "
    "but breaks if one of those links fails. Critically, a head-end does NOT validate a label-explicit path, so a "
    "stale or wrong SID-list silently blackholes -- explicit paths need independent monitoring.",
  "tradeoffs": "availability/resilience + simplicity (prefix-SID paths reroute around local failures, shorter "
    "stacks) vs path precision/steerability (adjacency-SID exact-hop control).",
  "trigger": "Choosing how to express an SR-TE policy's segment list.",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to SR-TE design.",
  "recommended_action": "Default SR-TE forwarding to prefix-SID (node) paths for resilience and minimal stack "
    "depth; use adjacency-SID/strict-label paths only where exact link steering is required, and wherever label-"
    "explicit paths are used add active path validation/probing because the head-end will not detect a broken "
    "explicit path itself.",
  "alternatives": "Dynamic CSPF/min-fill computation when no strict constraint exists; retain RSVP-TE alongside "
    "during transition where its admission control is required.",
  "citation": "RFC 9256 (SR Policy Architecture, updates RFC 8402) + the Cisco SR Phase-2 Solution Test Report "
    "(SR-TE caveats); web-verified.",
 },
 # ---- SP transport TE / hygiene / topology ----
 {
  "id": "sp-sr-te-stateless-source-routing-vs-rsvp",
  "domain": "sp-transport",
  "title": "Prefer SR-TE stateless source-routed policies over RSVP-TE soft-state for scalable traffic engineering",
  "priority": "Medium",
  "engine_actionable": False,
  "design_intent": "Traffic engineering can be expressed two ways. RSVP-TE signals an explicit LSP hop-by-hop and "
    "holds soft-state (PATH/RESV refresh) at the head-end AND every midpoint, so tunnel count drives state and "
    "refresh load across the core. SR-TE encodes the engineered path as a segment list imposed only at the head-"
    "end; midpoints are stateless, so the core scales with links, not tunnels.",
  "tradeoffs": "scalability + simplicity (no midpoint/soft-state; policies live at the edge) vs guaranteed-"
    "bandwidth admission control (the stateless model has no per-LSP reservation).",
  "trigger": "Selecting the TE mechanism for a new or scaling transport core.",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to SP TE design.",
  "recommended_action": "Default new TE to SR-TE (head-end-imposed segment lists, stateless midpoints) for scale "
    "and operational simplicity; retain or overlay RSVP-TE only on the specific paths that need bandwidth "
    "admission / guaranteed reservations the stateless model cannot provide.",
  "alternatives": "Stay on RSVP-TE where hard bandwidth guarantees, auto-bandwidth with admission, or a mature "
    "RSVP-FRR deployment dominate; use a PCE/controller to compute SR-TE policies at scale.",
  "citation": "RFC 9256 (SR Policy = ordered segment list, source-routed) + Nick Russo CCIE-SP; web-verified.",
 },
 {
  "id": "sp-srte-pce-pcep-bgpls-centralized-controller-maturity-gate",
  "domain": "sp-transport",
  "title": "Centralise SR-TE with a stateful PCE over PCEP + BGP-LS, but gate the controller on feature maturity and validate paths yourself",
  "priority": "Medium",
  "engine_actionable": False,
  "design_intent": "SR-TE's strength is application-aware, centrally-optimised paths: a stateful PCE learns the "
    "topology via BGP-LS and initiates/updates/deletes SR LSPs on the PCC over PCEP. But the controller becomes a "
    "first-class dependency that must be chosen on PROVEN feature completeness, not roadmap -- and PCE/head-end "
    "state can read 'up' across a failed midpoint or inter-AS hop, so the design must add its own liveness check.",
  "tradeoffs": "optimality + agility + manageability (central programmatic WAN orchestration) vs availability/"
    "correctness risk (a controller SPOF + stale 'up' state masking a black hole).",
  "trigger": "Architecting centralised/SDN traffic engineering for an SR transport network.",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to SR-TE/SDN design.",
  "recommended_action": "Architect SR-TE with a stateful PCE (PCE-initiated LSPs over PCEP) fed by BGP-LS, "
    "selecting only a controller whose required SR-TE features are GA; add active liveness/path validation "
    "(independent probing) because PCE/head-end state can show 'up' across a failed hop; design controller "
    "redundancy so it is not a single point of failure.",
  "alternatives": "Distributed (router-local) SR-TE or static SID-list policies where a controller is unjustified "
    "or immature; keep RSVP-TE where its existing path-validation/admission dominates.",
  "citation": "RFC 8664 (PCEP extensions for SR) + RFC 9552 (BGP-LS, obsoletes RFC 7752) + RFC 9256 + the Cisco "
    "SR Phase-2 Test Report (SDN/PCE defects); web-verified.",
 },
 {
  "id": "sp-transport-keep-pe-loopbacks-as-host-routes-no-core-summarization",
  "domain": "sp-transport",
  "title": "Never summarize PE BGP-next-hop loopbacks in the core IGP -- VPN/LSP label resolution needs the exact /32",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "In an MPLS-VPN core, every VPNv4/L2VPN service rides a two-label stack whose OUTER label is "
    "the transport label bound to the egress PE's BGP next-hop -- its loopback. That binding and the LSP exist "
    "only if the PE loopback is present in the core IGP as an EXACT host route; an aggregate that hides the /32 "
    "leaves the next-hop label unresolved and silently black-holes every VPN service riding that PE -- one of the "
    "most common MPLS-VPN design failures.",
  "tradeoffs": "correctness/reachability of VPN services (host-route loopbacks make LSPs resolvable) vs core "
    "routing-table scale (you give up aggressive summarization of the PE loopback range).",
  "trigger": "Designing core IGP summarization / address aggregation in an MPLS-VPN backbone.",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to MPLS-VPN core design (but the same "
    "anti-pattern -- summarizing a next-hop a label binds to -- is worth checking in any labelled core).",
  "recommended_action": "Exclude PE / PE-next-hop loopbacks from any core IGP summarization or filtering; carry "
    "them as exact host routes end-to-end (or stitch summarized domains with BGP-LU); summarize only customer / "
    "infrastructure prefixes, and verify label/LSP resolution to each PE loopback in the design's NRFU plan.",
  "alternatives": "Aggressive core summarization is fine in a pure IP core; in an MPLS-VPN core the only safe "
    "pattern is host-route loopbacks (or BGP-LU across summarization boundaries).",
  "citation": "RFC 4364 (BGP/MPLS IP VPNs -- backbone IGP must carry a host route to each LSP egress PE) + Cisco "
    "MPLS L2/L3-VPN troubleshooting course; web-verified.",
 },
 {
  "id": "sp-transport-physical-topology-selection-matrix",
  "domain": "sp-transport",
  "title": "Select the physical transport topology (ring / hub-spoke / partial-mesh / full-mesh) from the role each layer serves",
  "priority": "Medium",
  "engine_actionable": False,
  "design_intent": "There is no single best physical topology: ring, hub-and-spoke, partial-mesh and full-mesh "
    "trade cost, optimal forwarding, convergence, FRR-friendliness and resource consumption against each other, "
    "and each wins in a different layer. Choose deliberately per role -- rings for cost-driven SP access/"
    "collection (accepting worst-case convergence, which is exactly why a ring needs engineered TI-LFA), hub-and-"
    "spoke where a clear concentration point exists (mitigate the hub SPOF), partial-mesh for core/aggregation "
    "diversity at bounded cost, full-mesh only where latency + diversity justify the O(n^2) cost.",
  "tradeoffs": "cost vs availability vs convergence vs scalability vs simplicity -- ring minimizes ports/cost but "
    "worsens convergence + optimal forwarding; full-mesh maximizes diversity at quadratic cost.",
  "trigger": "Choosing the physical/logical topology for a transport or WAN layer.",
  "observable": "Not collected by an L1-L4 enterprise assessment; a design-selection concept, complements the "
    "convergence-geometry rule (redundancy as triangles, not squares/rings).",
  "recommended_action": "Map each transport layer to a topology by its dominant requirement (cost-sensitive "
    "collection -> ring + engineered FRR; concentration point -> hub-and-spoke + SPOF mitigation; "
    "core/aggregation -> partial-mesh; latency/diversity-critical -> full-mesh); never apply one topology "
    "uniformly across all layers.",
  "alternatives": "A flat single-topology choice is simpler to operate but is almost always wrong at one end (a "
    "full-mesh access wastes capex; a hub-and-spoke core strands diversity).",
  "citation": "Orhan Ergun CCIE-SP design-comparison chart (ring vs hub-spoke vs partial-mesh vs full-mesh); "
    "complements topology-triangles-not-squares-rings (the convergence-geometry rule).",
 },
 # ---- inter-AS / L3VPN identity + topology (sp-mpls, sibling of sp-mpls-bgp-lu) ----
 {
  "id": "sp-interas-l3vpn-options-abc-csc-scale-vs-trust",
  "domain": "sp-mpls",
  "title": "Choose the inter-AS L3VPN handoff (Option A/B/C, plus CsC) by the ASBR-state vs scale vs trust tradeoff",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "Inter-AS MPLS L3VPN is not one design but a spectrum trading control-plane state at the "
    "border against scale and inter-provider trust. Option A (back-to-back VRF) keeps each AS fully isolated and "
    "is simplest to secure, but per-VPN sub-interfaces + IP forwarding at the ASBR do not scale. Option B (ASBR-"
    "to-ASBR VPNv4, retain-RT) scales further but puts VPN state on the border. Option C (multihop MP-eBGP RR-to-"
    "RR with PE next-hops preserved + BGP-LU between ASBRs) scales furthest but couples the providers' label "
    "paths. CsC is the hierarchical-carrier case -- a customer carrier rides a backbone carrier, exchanging "
    "labels (BGP-LU) at the CsC boundary.",
  "tradeoffs": "scalability (Option-C/CsC scale far past Option A's per-VPN sub-interfaces) + manageability vs "
    "security/isolation (Option A's hard per-AS boundary) and inter-provider coordination cost.",
  "trigger": "Handing an L3VPN off across an AS / inter-provider boundary.",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to inter-provider MPLS-VPN design.",
  "recommended_action": "Select by requirement: Option A when isolation/simplicity dominate and VPN count is low; "
    "Option B for moderate scale with VPN state acceptable at the border (retain route-targets across the ASBR); "
    "Option C / CsC when many VPNs + a provider hierarchy demand loopback-to-loopback label paths and the "
    "providers accept the coordination (Option C preserves the originating PE next-hop; CsC exchanges labels via "
    "BGP-LU at the boundary).",
  "alternatives": "Stay intra-AS where no real administrative boundary exists; a non-MPLS overlay handoff "
    "(IPsec/SD-WAN between domains) where label-path coupling is unacceptable.",
  "citation": "RFC 4364 §10 (inter-AS L3VPN Options a/b/c) + Orhan Ergun CCIE-SP inter-AS / CsC workbooks; web-verified.",
 },
 {
  "id": "sp-l3vpn-interas-edge-explicit-route-policy",
  "domain": "sp-mpls",
  "title": "Treat the inter-AS / inter-provider edge as untrusted: explicit inbound + outbound route-policy, never pass-all",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "An ASBR forming eBGP with another autonomous system is the boundary where one operator's "
    "routing trust ends. IOS-XR makes this safe-by-default -- an eBGP neighbour advertises and accepts nothing "
    "until an explicit route-policy is bound in each direction -- and that default should be honoured, never "
    "bypassed with a permit-any. A pass-all inter-AS policy is a prefix-leak / hijack surface.",
  "tradeoffs": "security (explicit per-direction filtering + RT scoping contain leaks/hijacks) vs simplicity/"
    "manageability (the policies + RT allowlists cost configuration + review effort).",
  "trigger": "Configuring any inter-AS / inter-provider eBGP edge (especially a VPNv4 hand-off).",
  "observable": "Not collected by an L1-L4 enterprise assessment of an enterprise estate; a security-grade rule "
    "for SP/inter-provider edges (a pass-all policy found in review is a finding).",
  "recommended_action": "At every inter-AS edge bind explicit, named inbound AND outbound route-policies that "
    "permit only the intended prefixes/loopbacks and (for VPNv4) only the intended route-targets; never ship a "
    "permit-any; pair the filter with prefix-count limits / max-prefix on the neighbour.",
  "alternatives": "A tightly-scoped prefix-list / route-target allowlist is the norm; a deliberately wider policy "
    "only inside a single administrative domain you fully control, never toward another AS.",
  "citation": "RFC 4364 §10 (inter-provider) + Orhan Ergun CCIE-SP inter-AS lab (IOS-XR sends/accepts nothing "
    "until a route-policy is applied); web-verified.",
 },
 {
  "id": "sp-l3vpn-rd-disambiguates-overlapping-vpn-address-space",
  "domain": "sp-mpls",
  "title": "Plan the Route Distinguisher to keep overlapping customer prefixes distinct (and per-PE-unique where VPN path diversity is needed)",
  "priority": "Medium",
  "engine_actionable": False,
  "design_intent": "The Route Distinguisher is the 8-byte value prepended to a customer IPv4 prefix to form a "
    "globally-unique 12-byte VPNv4 NLRI; its job is to keep two customers' overlapping address space (both using "
    "10.1.1.0/24) from colliding in one MP-BGP table. The RD is a field, not a BGP attribute -- it does not by "
    "itself build VPN topology (that is the Route-Target's job). A secondary consequence: a UNIQUE RD per VRF per "
    "PE makes a dual-homed site's two PE paths distinct NLRI, so a route reflector relays both (path diversity).",
  "tradeoffs": "correctness (overlap disambiguation) + convergence/availability (per-PE-unique RD preserves "
    "backup VPN paths through an RR) vs simplicity (one RD per VRF reads more cleanly).",
  "trigger": "Designing the VPNv4/v6 RD allocation for an MPLS L3VPN.",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to MPLS-VPN design.",
  "recommended_action": "Assign each VRF an explicit, planned RD (do not rely on the auto/default RD); keep RD "
    "allocation in an addressing/RD plan; where a VRF is anchored on two+ PEs and VPN path redundancy/multipath "
    "is required, allocate a distinct RD per PE (or use BGP Add-Path on the RR) so the RR retains all paths.",
  "alternatives": "A shared RD per VRF when paths should be deliberately de-duplicated and the topology is single-"
    "homed; per-PE-unique RD (or RR Add-Path) when dual-homed sites need their backup VPN path preserved.",
  "citation": "RFC 4364 (VPN-IPv4 = 8-byte RD + 4-byte IPv4) + Cisco MPLS L2/L3-VPN course; web-verified.",
 },
 {
  "id": "sp-l3vpn-rt-import-export-builds-the-vpn-topology",
  "domain": "sp-mpls",
  "title": "Engineer L3VPN connectivity topology with Route-Target import/export, not with the RD",
  "priority": "Medium",
  "engine_actionable": False,
  "design_intent": "The Route-Target -- an 8-byte extended community -- is what actually decides which VRFs "
    "receive which VPNv4 prefixes: a PE exports its VRF routes tagged with an export-RT, and any remote VRF whose "
    "import-RT matches installs them. Because import and export RT sets are independent and can be asymmetric, "
    "the RT scheme IS the VPN connectivity matrix -- any-to-any, hub-and-spoke, or controlled extranet are all "
    "just RT patterns.",
  "tradeoffs": "security & policy (asymmetric RTs enforce hub-and-spoke / central inspection) vs reachability/"
    "simplicity (full-mesh RT is simplest but allows any-to-any).",
  "trigger": "Designing the connectivity topology of one or more MPLS L3VPNs.",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to MPLS-VPN design.",
  "recommended_action": "Design the VPN connectivity matrix explicitly as an RT import/export plan -- symmetric "
    "RTs for any-to-any, hub-exports/spoke-imports (and the inverse) for hub-and-spoke, a dedicated shared-"
    "services RT for controlled extranet -- and document the intended topology alongside the RT scheme so "
    "membership cannot drift.",
  "alternatives": "Full-mesh RT for simple any-to-any enterprise VPNs; asymmetric hub-and-spoke RT where policy/"
    "inspection must sit between sites; a per-service extranet RT for shared services.",
  "citation": "RFC 4364 (Route-Target extended community governs VRF import/export) + Cisco MPLS L2/L3-VPN course; web-verified.",
 },
 # ---- L2VPN ----
 {
  "id": "sp-l2vpn-vpls-is-one-stretched-flood-domain-cap-it",
  "domain": "sp-l2vpn",
  "title": "Treat a VPLS instance as one WAN-wide flood / MAC-learning domain and bound it with limits + snooping",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "Because VPLS presents the interconnected PEs as ONE emulated LAN, it inherits every Ethernet "
    "broadcast-domain hazard but stretches it across the WAN: unknown-unicast/multicast/broadcast flood to all "
    "attachment circuits, PEs learn MACs dynamically per VFI, and a single mis-stated MTU, loop or MAC storm "
    "becomes a WAN-wide failure. A VPLS instance is a failure domain the size of the whole emulated LAN.",
  "tradeoffs": "availability + blast-radius containment (MAC limits + snooping bound the flood domain) vs "
    "reachability/transparency (a hard MAC cap can drop endpoints if undersized).",
  "trigger": "Designing or sizing a VPLS (multipoint L2VPN) service.",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to L2VPN design (the same bounded-flood-"
    "domain discipline mirrors the engine's bounded-L2-failure-domain rule for campus/DC VLANs).",
  "recommended_action": "Right-size the emulated LAN: set per-VFI MAC-address-table limits with an explicit "
    "unknown-MAC action, enable IGMP/PIM snooping to constrain multicast flooding, control BPDUs at the access "
    "edge, and prefer L3VPN or point-to-point VPWS where multipoint L2 reach is not actually required.",
  "alternatives": "Bounded VPLS (limits + snooping) when multipoint L2 is mandatory; routed L3VPN when the "
    "customer only needs IP reachability (smaller failure domain); VPWS for a simple point-to-point pseudowire; "
    "EVPN where control-plane MAC learning + all-active multihoming are wanted.",
  "citation": "RFC 4761 (VPLS using BGP) / RFC 4762 (VPLS using LDP) + Cisco MPLS L2/L3-VPN course; web-verified.",
 },
 # ---- Multicast VPN (ngMVPN) ----
 {
  "id": "sp-mvpn-decouple-provider-tunnel-from-customer-signalling",
  "domain": "sp-mvpn",
  "title": "Choose the provider tunnel and the C-multicast signalling plane as two independent decisions",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "Next-gen MVPN's central gain over draft-Rosen is splitting one monolithic choice into two "
    "orthogonal axes: how the core REPLICATES traffic (the P-tunnel: PIM-GRE, mLDP P2MP/MP2MP, or P2MP-TE) and "
    "how PEs LEARN which customer (S,G)/(*,G) lives where (the C-multicast plane: overlay PIM vs BGP MCAST-VPN "
    "auto-discovery + C-multicast routes). A 'profile number' bundles a specific pair, but the design decision is "
    "the two axes, each sized to its own driver.",
  "tradeoffs": "manageability + scalability (each plane sized to its own constraint -- core protection/state for "
    "the tunnel, PE/adjacency scale for the signalling) vs simplicity (two planes = more moving parts).",
  "trigger": "Designing multicast over an MPLS/BGP IP-VPN (MVPN).",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to SP MVPN design.",
  "recommended_action": "State the P-tunnel and the C-multicast signalling as SEPARATE selections in the HLD, each "
    "justified against its own driver (core protection/state for the tunnel; PE/adjacency scale for the "
    "signalling) -- never adopt a profile number as a bundle.",
  "alternatives": "Keep them coupled (classic draft-Rosen, profile 0) only for a tiny deployment where the core "
    "already runs PIM and operational familiarity outweighs scale.",
  "citation": "RFC 6513 (Multicast in MPLS/BGP IP VPNs framework) + RFC 6514 (BGP encodings / MCAST-VPN A-D + "
    "C-multicast routes); web-verified.",
 },
 {
  "id": "sp-mvpn-prefer-mldp-over-pim-gre-in-the-core",
  "domain": "sp-mvpn",
  "title": "Prefer mLDP (label-switched P-tunnels) over PIM-GRE to keep PIM and per-VPN state out of the core",
  "priority": "Medium",
  "engine_actionable": False,
  "design_intent": "PIM-GRE (profile 0 / draft-Rosen) requires PIM enabled across the whole P-network and builds "
    "a per-VPN NBMA default-MDT on which every PE becomes a PIM neighbour of every other PE -- so adjacency + "
    "mroute state grow with PEs x VPNs and ride a separate GRE/PIM plane the core's unicast LSPs never see. mLDP "
    "builds the multicast distribution tree as label-switched P2MP/MP2MP LSPs over the SAME MPLS data plane, "
    "removing core PIM and getting MPLS-grade protection (TI-LFA), and constrains high-rate streams onto a data-"
    "MDT.",
  "tradeoffs": "scalability + convergence (mLDP slashes core control-plane state, reuses MPLS forwarding + FRR) "
    "vs simplicity/compatibility (mLDP assumes an MPLS core; PIM-GRE interops with legacy/IP cores).",
  "trigger": "Selecting the MVPN provider-tunnel (core replication) technology.",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to SP MVPN design.",
  "recommended_action": "Specify mLDP P2MP (and MP2MP where a shared tree fits) as the default P-tunnel; use a "
    "data-MDT to move high-rate streams off the default tree; reserve PIM-GRE for interop with legacy PEs or a "
    "non-MPLS core, documenting the core-state + protection consequences if it is retained.",
  "alternatives": "PIM-GRE only for backward compatibility with gear that cannot do mLDP or a non-MPLS core; "
    "P2MP-TE instead of mLDP where per-tree bandwidth admission / explicit-path is required.",
  "citation": "RFC 6388 (mLDP -- LDP extensions for P2MP/MP2MP LSPs) + RFC 6037 (Cisco draft-Rosen MVPN, "
    "informational); web-verified.",
 },
 # ---- BGP route-reflection path diversity (the problem the existing RR principle's remedy list assumes) ----
 {
  "id": "bgp-rr-best-path-hiding-diversity-remedy",
  "domain": "bgp",
  "title": "Restore the path diversity a route reflector hides before relying on it for PE redundancy or fast reroute",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "A vanilla route reflector re-advertises only its single best path to clients, so all the "
    "alternate exit PEs a full mesh would have exposed are silently hidden. That collapse is invisible until a "
    "client needs a backup it never received: BGP PIC, multipath load-sharing and dual-homed PE redundancy all "
    "fail quietly because the backup path was never relayed. (This is the WHY behind the remedy list the "
    "enterprise RR principle names -- here scoped to the SP/MPLS-VPN case and made a deliberate design check.)",
  "tradeoffs": "scalability + simplicity (RR clustering) vs availability + convergence (RR clustering trades away "
    "the very path diversity PIC/multipath/dual-homing depend on).",
  "trigger": "Introducing or relying on route reflectors where clients need redundancy / fast reroute.",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to BGP RR design (the existing "
    "ibgp-full-mesh-to-route-reflector principle lists the remedies; this one explains the failure mode + how to "
    "choose among them).",
  "recommended_action": "Where RRs serve clients that need redundancy, deliberately restore diversity and size "
    "the remedy against four axes (MPLS-VPN fitness / extra session+RR cost / migration disruption / operational "
    "familiarity): BGP Add-Path (RFC 7911) for standards-based per-next-hop diversity, unique-RD-per-PE for "
    "MPLS L3VPN, shadow-RR or shadow-session where Add-Path is unavailable; pair with BGP PIC for sub-second reconverge.",
  "alternatives": "A full iBGP mesh restores diversity natively but does not scale; BGP best-external advertises a "
    "backup at the originating PE but does not by itself make a remote dual-homed path visible through an RR.",
  "citation": "RFC 7911 (Advertisement of Multiple Paths in BGP / Add-Path) + Orhan Ergun CCIE-SP path-diversity "
    "comparison (Add-Path vs Shadow-RR vs Shadow-Session vs Unique-RD); complements ibgp-full-mesh-to-route-reflector.",
 },
]
DOCTRINE.extend(_SP_CORPUS_ADDENDUM)


# --------------------------------------------------------------- SD-WAN / modern-WAN addendum
# Mined from the D:\\ SD-WAN corpus (Orhan Ergun "Evolving Technology: SD-WAN" deck + CCIE-EI SD-WAN lab
# workbooks) anchored + a dedicated Cisco Catalyst SD-WAN web-research pass (Catalyst SD-WAN Design Guide /
# CVD). The KB's WAN doctrine stopped at DMVPN/GETVPN/overlay-routing; this adds the CONTROLLER-based fabric.
# EVERY principle is DOCTRINE (engine_actionable=False): an L1-L4 enterprise assessment collects no SD-WAN
# overlay / controller / OMP / policy / TLOC state, so the design brain cites these for WAN-modernization
# engagements + the HLD narrative + chat, never as auto-detected findings. Current naming web-verified:
# Cisco rebranded Viptela -> Cisco Catalyst SD-WAN (Manager=vManage / Controller=vSmart / Validator=vBond);
# OMP is Cisco-PROPRIETARY (BGP-structured), not an IETF/RFC standard. Original re-expression; no verbatim.
_SDWAN_CORPUS_ADDENDUM = [
 {
  "id": "sdwan-four-plane-controller-fabric-separation",
  "domain": "sd-wan",
  "title": "Adopt SD-WAN as a four-plane controller fabric (Manager/Controller/Validator/WAN-Edge); only the data plane forwards, and it survives the control plane",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "SD-WAN's net-new value over a router-built tunnel overlay (DMVPN/GETVPN/FlexVPN) is "
    "architectural: it decomposes the WAN into four independent planes that scale, fail and are secured on "
    "their own axes -- Manager (vManage: GUI/API/config/telemetry), Controller (vSmart: OMP control + policy), "
    "Validator (vBond: zero-touch orchestration/onboarding, the only publicly-reachable role), and WAN Edge "
    "(cEdge/vEdge: IPsec data). Critically the controllers are OFF the user data path -- edges build IPsec "
    "tunnels directly to each other -- so OMP graceful restart lets the data plane keep forwarding on cached "
    "routes/TLOCs/keys through a full controller outage (default ~12h). The control plane's loss is non-fatal.",
  "tradeoffs": "manageability + scalability + security (each plane independent; fleet-scale central ops) and "
    "availability (data plane survives control-plane loss) vs a controller dependency + licensing + the skills "
    "to operate a controller fabric.",
  "trigger": "Designing a modern enterprise WAN where centralized policy, transport-independence and fleet-scale "
    "operations are required.",
  "observable": "Not collected by an L1-L4 enterprise assessment (no SD-WAN controller/overlay state); applies "
    "to a WAN-modernization design engagement.",
  "recommended_action": "Target four explicitly-separated planes (Manager cluster / redundant Controllers / "
    "redundant Validators / thin WAN edges); keep edges thin and policy central; rely on (and verify) OMP "
    "graceful restart so a controller outage never drops forwarding, and size the IPsec rekey timer to span the "
    "GR window.",
  "alternatives": "A router-resident overlay (DMVPN phase-3 + IGP/BGP, GETVPN for any-to-any private-core "
    "encryption -- the KB's vpn-scale-dmvpn-getvpn-selection) wins for a small, stable, few-site estate that "
    "values no-controller autonomy and per-box control.",
  "citation": "Orhan Ergun 'Evolving Technology: SD-WAN' deck + Cisco Catalyst SD-WAN Design Guide; web-verified "
    "(Viptela -> Catalyst SD-WAN: Manager/Controller/Validator).",
 },
 {
  "id": "sdwan-omp-bgp-style-overlay-control-plane",
  "domain": "sd-wan",
  "title": "Let OMP to the Controller be the BGP-style overlay control plane -- routes, TLOCs and policy over one controller-rooted session, not a routing full-mesh",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "In a controller-based fabric every WAN Edge forms an OMP (Overlay Management Protocol) "
    "session only to the Controller (route-reflector-like), never edge-to-edge for routing. OMP -- a Cisco-"
    "PROPRIETARY, BGP-structured protocol (NOT an IETF/RFC standard) -- advertises OMP routes (prefix + TLOC), "
    "TLOC routes (TLOC -> WAN-IP) and service routes, and the Controller can rewrite attributes to reshape the "
    "fabric centrally. This decouples control-plane peering from data-plane topology, and runs a BGP-like "
    "best-path (prefer active over stale/graceful-restart, then route/TLOC preference).",
  "tradeoffs": "scalability + manageability (one controller-rooted session carries routing AND policy; central "
    "attribute rewrite) vs a proprietary control plane (no RFC portability) and a controller dependency.",
  "trigger": "Designing the overlay routing/control plane of an SD-WAN fabric.",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to SD-WAN design.",
  "recommended_action": "Place overlay routing under OMP to a redundant Controller cluster sited OUT of the data "
    "path; keep edges free of per-pair routing config; express path bias as OMP route-preference / TLOC-"
    "preference; keep site-local underlay routing (BGP/OSPF/connected) separate and redistribute into OMP "
    "deliberately.",
  "alternatives": "A classic iBGP route-reflector / IGP overlay (the KB's ibgp-full-mesh-to-route-reflector / "
    "bgp-rr-best-path-hiding-diversity-remedy) centralizes routing without a controller, but lacks the "
    "integrated TLOC/policy/zero-touch model.",
  "citation": "Cisco Catalyst SD-WAN Design Guide (OMP) + SD-WAN labs; web-verified that OMP is Cisco-proprietary, "
    "BGP-style, controller-rooted.",
 },
 {
  "id": "sdwan-tloc-transport-independence",
  "domain": "sd-wan",
  "title": "Model every WAN uplink as a TLOC (system-IP + color + encap) so one overlay rides MPLS, Internet and LTE/5G simultaneously and transport-agnostically",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "Transport-independence -- SD-WAN's core property -- comes from abstracting each physical WAN "
    "attachment into a TLOC (Transport Locator = system-IP + color + encapsulation). The 'color' (mpls, biz-"
    "internet, public-internet, lte, private1-6, metro-ethernet, ...) labels the transport and governs which "
    "TLOCs mesh (private colors use the carrier-private IP, public colors use the post-NAT public IP). The same "
    "IPsec overlay is built over every colored transport at once -- active/active ECMP across equal-preference "
    "TLOCs -- so transport choice becomes a price/capacity decision, not a topology one.",
  "tradeoffs": "availability + cost (blend cheap Internet + LTE with MPLS, active/active, sub-second failover) vs "
    "the discipline of a consistent color taxonomy + tight allow-service on Internet-facing TLOCs.",
  "trigger": "Designing the WAN transport / uplink model for multi-circuit sites.",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to SD-WAN design.",
  "recommended_action": "Define each uplink as a TLOC with a deliberate, consistent color taxonomy (private "
    "colors for MPLS/private, public colors for Internet/LTE/5G), default to IPsec encapsulation, BFD-track "
    "every transport, and use color + preference to express active/active vs active/standby; scope allow-service "
    "tightly on Internet TLOCs.",
  "alternatives": "A single-transport design (MPLS-only, or Internet-only with a device-built IPsec overlay) "
    "wins where only one circuit type exists or simplicity dominates -- but ties the design to the underlay.",
  "citation": "Cisco Catalyst SD-WAN Design Guide (TLOC, colors, transport-independence) + SD-WAN labs; web-verified.",
 },
 {
  "id": "sdwan-application-aware-sla-routing",
  "domain": "sd-wan",
  "title": "Steer each application to a transport meeting its measured SLA class (loss/latency/jitter), and decide the no-path-meets-SLA behaviour per class",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "Legacy WAN routing picks a path on reachability + a coarse metric and keeps forwarding there "
    "until the link is hard-down, so a 'brown' transport (degraded loss/latency/jitter but still up) keeps "
    "carrying voice/video. SD-WAN closes this: per-tunnel BFD probes measure liveness AND circuit quality, and "
    "application-aware routing steers each app to any transport currently meeting its SLA class, re-steering on "
    "breach. Two BFD timescales must be kept distinct -- fast hellos (~1s) for liveness, aggregated app-route "
    "probes (~10s poll) for the SLA decision -- or you get flapping or sluggish steering. And the all-out-of-SLA "
    "behaviour is application-specific: strict (drop) for integrity-critical classes vs backup/best-of-worst for "
    "availability-first classes.",
  "tradeoffs": "performance + availability (apps follow live path quality, not stale routes) vs configuration "
    "complexity (SLA classes, app classification, probe tuning) and the per-class strict-vs-backup decision.",
  "trigger": "Designing WAN forwarding for an estate with differentiated, SLA-sensitive applications (voice/video/SaaS).",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to SD-WAN design.",
  "recommended_action": "Define a lean set of SLA classes (max loss/latency/jitter), map apps to classes via "
    "DSCP/application classification, bind them in app-aware-routing policy; tune the BFD hello-interval for "
    "liveness and the app-route poll-interval/multiplier for SLA responsiveness separately; and explicitly "
    "choose strict (drop) vs loose/backup fallback per class and document it.",
  "alternatives": "Classic DiffServ marking + queuing (qos-class-model-from-app-profile) protects an app WITHIN "
    "a link's queues but cannot MOVE it off a brown transport; PfR/IWAN-style performance routing is a coarser "
    "non-SD-WAN approximation.",
  "citation": "Cisco SD-WAN Application-Aware Routing deploy guide + SD-WAN labs; web-verified (BFD probes, SLA "
    "classes, strict vs backup-sla).",
 },
 {
  "id": "sdwan-centralized-control-vs-localized-data-policy",
  "domain": "sd-wan",
  "title": "Split policy by plane: centralized CONTROL policy moves routes/TLOCs/topology on the Controller; LOCALIZED data policy acts on packets at the edge",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "Catalyst SD-WAN intentionally separates policy along two axes, and a clean design keeps each "
    "concern where it belongs. Centralized CONTROL policy runs on the Controller and manipulates the OMP control "
    "plane (routes/TLOCs/topology) for the whole fabric -- it never touches a packet. Centralized DATA policy "
    "(also on the Controller) and LOCALIZED policy (on the edge: ACL/QoS/policer/mirror) act on packets. Moving "
    "intent off the boxes into the Controller -- and driving edge config from centralized device/feature "
    "templates with only per-device values externalized as variables -- makes the Controller/Manager the single "
    "source of intent and kills configuration drift.",
  "tradeoffs": "manageability + consistency (one source of intent, no drift, fabric-wide change) vs the modelling "
    "discipline of templates + the centralized-vs-localized placement decision.",
  "trigger": "Designing how WAN policy and edge configuration are authored and maintained at fleet scale.",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to SD-WAN design.",
  "recommended_action": "Author fabric-wide steering/segmentation/app-route as centralized control + data policy "
    "on the Controller (site-list/VPN-list scoped, directional); reserve localized policy for genuinely "
    "interface-scoped ACL/QoS; standardize edges on centralized device/feature templates with per-device "
    "divergence as keyed variables, and route all fleet change through template edits.",
  "alternatives": "Per-device route-maps/ACLs/golden-config (the traditional model) keeps config local but drifts "
    "across a large estate and offers no fabric-wide intent.",
  "citation": "Cisco Catalyst SD-WAN Policy + Templates design guidance + SD-WAN labs; web-verified.",
 },
 {
  "id": "sdwan-topology-by-controller-policy-not-physical",
  "domain": "sd-wan",
  "title": "Choose full-mesh vs hub-spoke vs regional topology by Controller policy, decoupled from physical transport",
  "priority": "Medium",
  "engine_actionable": False,
  "design_intent": "A Catalyst SD-WAN fabric is full-mesh by default (every edge can tunnel to every other), and "
    "the logical topology is then a DESIGN CHOICE expressed as centralized control policy -- independent of how "
    "sites are physically cabled. Hub-and-spoke, partial-mesh or a regional topology is built by selectively "
    "advertising/rewriting TLOCs and routes on the Controller, so topology becomes a policy artifact you can "
    "change without touching a single edge.",
  "tradeoffs": "scalability + manageability (topology as policy; change without re-cabling) vs the tunnel/OMP "
    "scale of a full mesh (which only suits small or latency-critical any-to-any estates).",
  "trigger": "Deciding the logical overlay topology of an SD-WAN fabric.",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to SD-WAN design.",
  "recommended_action": "Use the default full-mesh only where direct any-to-any is justified and tunnel/OMP scale "
    "is acceptable (e.g. latency-critical inter-branch voice); otherwise express hub-and-spoke or a regional "
    "topology as centralized control policy (selective TLOC/route advertisement), and revisit it as the estate "
    "grows.",
  "alternatives": "Full-mesh for small or latency-critical any-to-any; hub-spoke at scale where spoke-to-spoke is "
    "rare; Multi-Region Fabric for a large multi-region estate (see sdwan-multi-region-fabric-hierarchical-scale).",
  "citation": "Cisco Catalyst SD-WAN Design Guide (centralized control policy / topology) + SD-WAN labs; web-verified.",
 },
 {
  "id": "sdwan-end-to-end-segmentation-vpn-segments",
  "domain": "sd-wan",
  "title": "Segment the WAN end-to-end with service VPNs carried in one tunnel; reserve VPN 0 for transport and VPN 512 for OOB management",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "SD-WAN delivers multi-tenant segmentation natively: a service VPN is a VRF on the WAN Edge "
    "with its own forwarding table, and an interface lives in exactly one VPN. Traffic from any service VPN "
    "crosses the SAME IPsec tunnel between edges carrying a VPN tag that lands it in the correct VPN at the far "
    "end, and OMP propagates VPN-ID membership fabric-wide. Two VPNs are structural and reserved -- VPN 0 is the "
    "transport VPN (WAN interfaces/TLOCs/OMP/BFD, the front-door) and VPN 512 is out-of-band management -- so "
    "the transport network cannot reach the services by default.",
  "tradeoffs": "security + isolation (per-LoB/compliance/partner segmentation end-to-end, transport fenced from "
    "services) vs the planning to map zones to VPNs and make inter-VPN reachability explicit (route-leak/service-chain).",
  "trigger": "Designing WAN segmentation for lines-of-business / compliance zones / partners.",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to SD-WAN design (mirrors the engine's "
    "bounded-segmentation discipline for campus/DC).",
  "recommended_action": "Map each isolation domain to one service VPN before build; keep all WAN/TLOC interfaces "
    "in transport VPN 0 and device management in VPN 512; map each LAN segment into exactly one service VPN; make "
    "all inter-VPN reachability explicit (route-leak or service insertion), never implicit.",
  "alternatives": "A single flat VPN is simplest but offers no isolation; per-segment separate tunnels/overlays "
    "isolate but multiply state -- the in-tunnel VPN-tag model gives isolation without extra tunnels.",
  "citation": "Cisco Catalyst SD-WAN segmentation design (service VPNs, VPN 0 / VPN 512) + SD-WAN labs; web-verified.",
 },
 {
  "id": "sdwan-branch-dia-security-onbox-vs-cloud-sig",
  "domain": "sd-wan",
  "title": "Break out SaaS/Internet locally (DIA) instead of backhauling, and place branch security per site: on-box ZBFW/IPS/URL/AMP vs cloud SIG",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "The legacy WAN trombones every Internet/SaaS packet from the branch to a regional DC, inspects "
    "it centrally, and sends it back -- two extra WAN hops of latency burning the private circuit for traffic "
    "that never needed the DC. SD-WAN enables local Direct-Internet-Access, but once a branch breaks out it "
    "becomes its own Internet edge and must enforce a full threat stack -- placed per site, two ways for the "
    "SAME controls: ON-BOX (the WAN edge's Catalyst SD-WAN security stack: ZBFW, IPS/IDS, URL-filtering, "
    "AMP/TLS-proxy) or CLOUD-delivered via a Secure Internet Gateway (Cisco Umbrella SIG).",
  "tradeoffs": "performance + cost (local breakout removes the trombone, frees the private circuit) and security "
    "(full inspection at the edge) vs the platform/licensing for on-box inspection or the dependency on a cloud "
    "SIG; data-sovereignty may force one or the other.",
  "trigger": "Designing branch Internet/SaaS access + branch security for an SD-WAN estate.",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to SD-WAN design.",
  "recommended_action": "Steer trusted SaaS/web/IaaS to local DIA, reserving backhaul only for traffic that must "
    "transit the core (regulated/legacy-central); choose security placement per site -- on-box ZBFW+IPS+URL+AMP "
    "where the branch is large, latency/compliance-sensitive, or must inspect during a cloud outage; cloud SIG "
    "where light branches favour a thin edge; commonly a hybrid (on-box as the SIG-down fallback).",
  "alternatives": "Full backhaul-and-inspect still wins where regulation forbids branch egress or mandates one "
    "audited choke point; all-on-box wins under strict air-gap/sovereignty.",
  "citation": "Cisco Catalyst SD-WAN security design (on-box stack vs Umbrella SIG; DIA) + SD-WAN labs; web-verified.",
 },
 {
  "id": "sdwan-sase-convergence-and-sig-high-availability",
  "domain": "sd-wan",
  "title": "Design SD-WAN and cloud security (SASE/SSE) as one converged fabric, and make the SIG breakout highly available",
  "priority": "Medium",
  "engine_actionable": False,
  "design_intent": "SASE is the convergence of WAN networking (SD-WAN) and cloud-delivered security (SSE -- Cisco "
    "Umbrella / Secure Access) into one operating model, and the payoff only lands if they are architected "
    "TOGETHER: express security + steering intent once, and let app-aware routing pick SIG vs on-box vs backhaul "
    "per application. But offloading security to a cloud SIG makes that tunnel the branch's security lifeline -- "
    "if it is the only path and fails, the branch loses Internet or, worse, egresses uninspected -- so SIG HA is "
    "non-negotiable.",
  "tradeoffs": "manageability + consistency (one converged network+security fabric, intent authored once) vs "
    "single-vendor coupling; and SIG availability (redundant tunnels + health-tracking) vs the cost/complexity "
    "of multi-DC SIG redundancy.",
  "trigger": "Converging WAN and cloud security (SASE) and designing cloud-SIG breakout.",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to SD-WAN + SASE design.",
  "recommended_action": "Design SD-WAN and the SSE (Umbrella SIG / Secure Access) as one fabric with intent "
    "authored once; provision at least two SIG tunnels per breakout site across multiple Umbrella data centres "
    "(active + backup), bind a layer-7 health tracker so failover follows real cloud reachability (not interface "
    "state), and define an explicit SIG-down fallback (on-box stack or controlled drop -- never silent "
    "uninspected egress).",
  "alternatives": "Keeping SD-WAN and an independent/third-party SSE as decoupled layers avoids single-vendor "
    "lock-in or reuses an incumbent security cloud, at the cost of two operating models; a single SIG tunnel with "
    "no fallback only for low-criticality guest breakout.",
  "citation": "Cisco SASE / Umbrella SIG + Catalyst SD-WAN security design; web-verified.",
 },
 {
  "id": "sdwan-zero-trust-ztp-onboarding-and-pki",
  "domain": "sd-wan",
  "title": "Onboard WAN edges zero-touch on a mutual-trust chain -- allow-listed serial/chassis + a shared root CA + per-device certs, brokered by the Validator -- and encrypt by default",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "Catalyst SD-WAN is zero-trust by construction and the design must preserve it. Every element "
    "-- Manager, Controller, Validator and every edge -- proves identity with an X.509 certificate (SUDI/TAm on "
    "hardware, CA-signed on controllers) chained to a common root CA and a consistent organization-name before "
    "anything is trusted. A new edge needs only IP reachability to the Validator (vBond), which validates its "
    "serial/chassis against the uploaded allow-list AND the mutual certificate chain before introducing it. The "
    "control plane runs on authenticated DTLS/TLS and the data plane is IPsec, keyed per-TLOC and distributed "
    "INSIDE OMP -- so the fabric is encrypted-and-authenticated by default, not via a separate IKE control plane.",
  "tradeoffs": "security (per-device cryptographic identity, zero-touch at scale, encrypted-by-default) vs the "
    "PKI/allow-list discipline (root-CA choice, cert lifecycle, reliable NTP for cert validity).",
  "trigger": "Designing WAN-edge onboarding and fabric trust for an SD-WAN deployment.",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to SD-WAN design.",
  "recommended_action": "Choose the root-CA model deliberately (enterprise CA where internal PKI control is "
    "required, else Cisco PKI), distribute the root chain to every controller and edge, enforce one consistent "
    "organization-name, drive CSR/sign/install through the Manager, maintain the serial/chassis allow-list as a "
    "change-controlled artifact, and guarantee reliable NTP; treat the fabric as encrypted/authenticated by "
    "default and write transport firewall rules around the control-plane ports.",
  "alternatives": "Manual pre-staging / pre-shared trust per device gives full control but no zero-touch and does "
    "not scale; a lighter cert posture is for lab/PoC only, never production.",
  "citation": "Cisco Catalyst SD-WAN onboarding / certificate trust (Validator allow-list + PKI; OMP-keyed IPsec) "
    "+ SD-WAN labs; web-verified.",
 },
 {
  "id": "sdwan-controller-redundancy-placement-and-scale",
  "domain": "sd-wan",
  "title": "Size a redundant, identical-policy Controller cluster off the data path, and bound fan-out by controller affinity",
  "priority": "Medium",
  "engine_actionable": False,
  "design_intent": "The control plane is the scaling pivot and a potential SPOF, so the design must make it "
    "redundant AND ensure its loss is non-fatal. A Controller terminates a large but finite number of control "
    "connections (~5000 per instance, up to ~12 Controllers in a production deployment), so growth to thousands "
    "of edges is handled by adding identical-policy Controllers and bounding each edge's fan-out with controller-"
    "groups + max-controllers (affinity). Because controllers are off the user data path, their placement "
    "(Cisco-cloud-hosted vs on-prem) is an operations/availability/sovereignty decision, not a throughput one.",
  "tradeoffs": "availability + scalability (redundant, geographically/cloud-diverse controllers; affinity bounds "
    "fan-out) vs cost/operational footprint; cloud-hosted offloads undifferentiated heavy lifting but cedes "
    "control; on-prem gives sovereignty at the cost of operating the controllers.",
  "trigger": "Sizing and placing the SD-WAN controller cluster for a given estate scale.",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to SD-WAN design.",
  "recommended_action": "Deploy at least two geographically/cloud-diverse Controllers with byte-identical policy; "
    "configure each edge with redundant control connections; add Controllers toward the ~12 ceiling as edges "
    "grow past a single Controller's ~5000-connection limit; use controller-groups + per-edge max-controllers to "
    "bound fan-out; default to Cisco-cloud-hosted controllers unless sovereignty/air-gap/regulatory or a "
    "committed DC investment dictates on-prem.",
  "alternatives": "A single Controller pair with no affinity wins for small fabrics (hundreds of edges); a single "
    "controller only for a lab/pilot where an outage of all overlay control + policy change is tolerable.",
  "citation": "Cisco Catalyst SD-WAN controller scale/redundancy/affinity design; web-verified (~5000 conn/"
    "controller, controller groups, cloud-hosted vs on-prem).",
 },
 {
  "id": "sdwan-vs-traditional-wan-target-decision",
  "domain": "sd-wan",
  "title": "Choose controller-based SD-WAN vs DMVPN/GETVPN/MPLS by whether transport-independence, app-aware SLA and central policy justify a controller",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "The headline modern-WAN decision is whether to keep a router-managed overlay (DMVPN/GETVPN) "
    "or traditional MPLS, or adopt a controller-based fabric (Cisco Catalyst SD-WAN). SD-WAN's value is "
    "transport-independent multi-transport blending, per-application SLA path selection, central zero-touch "
    "policy, integrated branch security (DIA + SIG), and cloud/SaaS optimization (Cloud OnRamp) -- but it brings "
    "a controller dependency, licensing, and a new operating model. The choice is requirement-driven, not a "
    "fashion.",
  "tradeoffs": "manageability + performance + security + agility (central policy, app-SLA, transport-independence, "
    "integrated security) vs simplicity + cost + autonomy (no controller dependency, per-box control, lower "
    "licensing).",
  "trigger": "Modernising an enterprise WAN -- deciding the target WAN architecture.",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to a WAN-modernization design engagement.",
  "recommended_action": "Adopt controller-based Cisco Catalyst SD-WAN when the estate needs transport-independent "
    "multi-transport blending, per-application SLA steering, central zero-touch policy at fleet scale, integrated "
    "branch security/DIA, or cloud/SaaS optimization; otherwise keep DMVPN/GETVPN where a simple, stable, few-"
    "site overlay with no-controller autonomy and lower cost suffices.",
  "alternatives": "DMVPN wins for a simple, stable, few-site estate valuing no-controller autonomy + per-box "
    "control; GETVPN for any-to-any encryption over a trusted private MPLS core; traditional MPLS where the "
    "provider owns SLA and no overlay intelligence is needed.",
  "citation": "Cisco Catalyst SD-WAN Design Guide + Orhan Ergun 'Evolving Technology: SD-WAN'; complements the "
    "KB's vpn-scale-dmvpn-getvpn-selection / wan-vpn-make-vs-buy; web-verified.",
 },
 {
  "id": "sdwan-multi-region-fabric-hierarchical-scale",
  "domain": "sd-wan",
  "title": "Scale a large SD-WAN estate with Multi-Region Fabric (regions + border routers + core region 0), not one flat global full-mesh",
  "priority": "Medium",
  "engine_actionable": False,
  "design_intent": "A single flat SD-WAN fabric tries to build a global tunnel mesh and propagate OMP routing "
    "across every edge worldwide, which does not scale operationally or in control-plane state for a large, "
    "geographically distributed estate. Multi-Region Fabric (formerly Hierarchical SD-WAN) partitions edges into "
    "regions with intra-region direct tunnels, deploys regional hubs as Border Routers that form a core region 0, "
    "and routes inter-region traffic via the border routers -- bounding tunnel mesh and OMP scope per region.",
  "tradeoffs": "scalability + manageability (bounded per-region mesh/OMP, regional fault/scope isolation) vs the "
    "extra roles (border routers, core region) and complexity -- unjustified below large/multi-region scale.",
  "trigger": "Designing a large, geographically distributed (multi-region) SD-WAN estate.",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to large-scale SD-WAN design.",
  "recommended_action": "For a large multi-region estate, design the overlay as Multi-Region Fabric: assign edges "
    "to regions (intra-region direct tunnels), deploy regional hubs as border routers forming core region 0, "
    "route inter-region traffic via border routers, and keep OMP/topology scope per region; avoid the extra "
    "roles until scale/geography/control-plane state actually demand them.",
  "alternatives": "A small-to-mid single-region estate is simpler as one flat fabric (full/partial mesh, no "
    "regions); hub-and-spoke by policy handles moderate scale without the Multi-Region roles.",
  "citation": "Cisco Catalyst SD-WAN Multi-Region Fabric design; web-verified.",
 },
 {
  "id": "sdwan-phased-mpls-to-sdwan-migration-coexistence",
  "domain": "sd-wan",
  "title": "Migrate MPLS-to-SD-WAN per-site over a deliberate hybrid-coexistence period, with an explicit interworking point -- never a flag-day swap",
  "priority": "High",
  "engine_actionable": False,
  "design_intent": "Converting a brownfield MPLS WAN to SD-WAN is a long-lived coexistence exercise, not a "
    "cutover. The durable design stands the SD-WAN fabric up ALONGSIDE the live MPLS network and migrates sites "
    "in waves, keeping migrated and not-yet-migrated sites mutually reachable throughout via an explicit "
    "MPLS<->SD-WAN transit/interworking point (a router in both worlds), with rollback preserved per wave -- the "
    "WAN echo of the build-before-break discipline.",
  "tradeoffs": "availability + risk-containment (parallel run, per-wave validation + rollback, no big-bang) vs a "
    "longer dual-run period (two WANs + an interworking point to operate during coexistence).",
  "trigger": "Planning a brownfield MPLS-to-SD-WAN migration.",
  "observable": "Not collected by an L1-L4 enterprise assessment; applies to WAN-migration planning (mirrors the "
    "engine's build-before-break phased-cutover principle).",
  "recommended_action": "Stand SD-WAN up in parallel with the live MPLS WAN; migrate sites in waves; retain the "
    "regional MPLS CEs/circuits and define an explicit MPLS<->SD-WAN transit/interworking point so all sites stay "
    "reachable throughout; validate (NRFU) and preserve rollback per wave; decommission MPLS only once the last "
    "wave is proven.",
  "alternatives": "For a very small estate with a single maintenance window and tolerant business, a coordinated "
    "all-at-once swap may be acceptable -- but only with full rollback staged.",
  "citation": "Cisco Catalyst SD-WAN migration guidance + SD-WAN labs; complements scenario-build-before-break-"
    "phased-cutover; web-verified.",
 },
]
DOCTRINE.extend(_SDWAN_CORPUS_ADDENDUM)


# ------------------------------------------------- multi-domain mega addendum (breadth waves)
# A 60-agent multi-domain mining wave (4 ACI-advanced disk-miners over Advance-Services-DC decks + 11
# web-research miners) covering the modern net-new design domains the KB still lacked: SD-Access/campus-
# fabric, enterprise wireless, network automation/telemetry, DC compute+storage (UCS/FCoE/OTV), cloud-native/
# container + cloud connectivity, IPv6 depth, and ACI-advanced (GOLF / uSeg / service-graph modes / VMM).
# EVERY principle is DOCTRINE (engine_actionable=False): an L1-L4 IOS/NX-OS assessment collects none of this
# state (wireless RF / SD-Access fabric / automation-controller / K8s / cloud / UCS / ACI-controller), so the
# design brain cites these for design narrative + chat, never as auto-detected findings. Current naming/
# standards web-verified: DNA Center -> Cisco Catalyst Center; Wi-Fi 6E/7 = 802.11ax/be (Wi-Fi 7 MLO/320MHz/
# 4K-QAM); Istio Ambient (ztunnel+waypoint) / Cilium eBPF sidecarless mesh; NVMe-oF (FC/TCP/RoCE); gNMI/
# OpenConfig; SGT carried in the VXLAN-GPO header. Original re-expression; no verbatim source text.
_MEGA_CORPUS_ADDENDUM = [
 # ---- SD-Access / campus fabric ----
 {
  "id": "campus-sda-vs-routed-access-target-decision",
  "domain": "campus-fabric", "priority": "High", "engine_actionable": False,
  "title": "Adopt SD-Access only for a concrete driver (identity-segmentation / automation / mobility); else keep routed-access -- and design the border/fusion handoff",
  "design_intent": "Cisco SD-Access (a controller-based campus fabric: Catalyst Center management, LISP control, "
    "VXLAN data, TrustSec policy) is justified by a NAMED driver -- identity-based micro-segmentation, controller "
    "automation/assurance at scale, or location-independent endpoint mobility -- not by default. Absent such a "
    "driver, a traditional routed-access / collapsed-core campus is simpler and cheaper. And where fabric IS "
    "chosen, the segmentation only holds inside it: the border + fusion-device handoff to the rest of the network "
    "is where VRFs/SGTs must be deliberately stitched or terminated.",
  "tradeoffs": "security + manageability + mobility (identity segmentation, central automation/assurance) vs "
    "simplicity + cost (a controller fabric is more moving parts than routed-access).",
  "trigger": "Choosing the campus access architecture for a refresh.",
  "observable": "Not collected by an L1-L4 assessment (no fabric/LISP/Catalyst-Center state); a campus design choice.",
  "recommended_action": "Adopt SD-Access only when a named driver (segmentation / automation / mobility) earns "
    "the complexity; otherwise keep routed-access. If fabric is chosen, explicitly design the border node + "
    "fusion device that leaks/terminates VNs and propagates SGTs to the non-fabric world.",
  "alternatives": "Traditional routed-access / collapsed-core (the KB's dc-three-tier / routed-access doctrine) "
    "where no segmentation/automation/mobility driver exists; NX-OS VXLAN-EVPN for the DC, not the campus.",
  "citation": "Cisco SD-Access (Software-Defined Access) Design Guide; web-verified (Catalyst Center, ex-DNA Center).",
 },
 {
  "id": "campus-sda-four-plane-fabric-lisp-vxlan-trustsec",
  "domain": "campus-fabric", "priority": "Medium", "engine_actionable": False,
  "title": "Treat SD-Access as four decoupled planes (Catalyst Center / LISP / VXLAN / TrustSec) on a routed underlay; kill flood-and-learn",
  "design_intent": "SD-Access splits the campus into four independent planes: Catalyst Center owns management/"
    "automation/assurance, LISP owns the control plane (an endpoint-ID-to-RLOC map-server, replacing L2 flood-"
    "and-learn -- edges register endpoints and query on cache-miss), VXLAN owns the data plane (carrying the VN "
    "and SGT), and TrustSec owns policy. The overlay rides a stable, fully-routed L3 underlay (loopbacks + P2P "
    "links only, jumbo MTU >= 9100) -- keep underlay and overlay separate. New fabrics should use LISP Pub/Sub "
    "(drops the in-fabric iBGP dependency).",
  "tradeoffs": "scalability + manageability (no flood-and-learn; controller automation; planes evolve "
    "independently) vs the LISP/VXLAN/controller skill set and a redundant control-plane-node requirement.",
  "trigger": "Designing the SD-Access fabric architecture + underlay.",
  "observable": "Not collected by an L1-L4 assessment; an SD-Access design.",
  "recommended_action": "Document four named planes with owners/failure-modes; build a routed L3 underlay (LAN "
    "Automation / IS-IS, MTU >= 9100, loopbacks + transit only); deploy >= 2 control-plane nodes per site (their "
    "own devices on medium/large sites); standardize on LISP Pub/Sub for new fabrics (image 17.6+).",
  "alternatives": "Legacy LISP-with-BGP control plane on older images; a traditional STP/flood-and-learn campus "
    "where a fabric is not adopted.",
  "citation": "Cisco SD-Access Design Guide (LISP control plane, VXLAN, LAN Automation, Pub/Sub); web-verified.",
 },
 {
  "id": "campus-sda-macro-vn-then-micro-sgt-segmentation",
  "domain": "campus-fabric", "priority": "High", "engine_actionable": False,
  "title": "Layer SD-Access segmentation: macro-isolate with Virtual Networks (VRF), micro-segment inside with SGTs, ISE as the single policy source",
  "design_intent": "SD-Access offers two orthogonal segmentation tiers. A Virtual Network is exactly a VRF / LISP "
    "Instance-ID giving complete L3 isolation between large domains (employee / IoT / guest / OT), default no "
    "inter-VN traffic (bridge only via an explicit fusion). Inside a VN, the Scalable Group Tag -- carried inline "
    "in the VXLAN-GPO 16-bit Group-Policy-ID (~64K groups) -- enforces group-to-group policy decoupled from IP/"
    "topology via SGACLs. ISE is the policy single-source-of-truth that classifies endpoints (802.1X/MAB) and "
    "returns the VN + SGT, so identity, not the patch port, decides placement -- and ISE's failure must be designed for.",
  "tradeoffs": "security (identity-based macro+micro isolation that follows the endpoint) vs the ISE/TrustSec "
    "operating model + SGT-propagation design (inline tagging vs SXP) across every fabric boundary.",
  "trigger": "Designing campus segmentation on an SD-Access fabric.",
  "observable": "Not collected by an L1-L4 assessment; an SD-Access policy design.",
  "recommended_action": "Define a deliberately small set of VNs aligned to hard trust boundaries; micro-segment "
    "inside each with SGTs/SGACLs; onboard endpoints closed-loop with ISE (802.1X/MAB -> VN+SGT via RADIUS, CoA "
    "for re-auth); design SGT propagation (inline where supported, SXP where not) and ISE redundancy.",
  "alternatives": "VLAN/subnet ACL segmentation (drift-prone, topology-bound) where TrustSec is not adopted; "
    "macro-only VN isolation where micro-segmentation is not required.",
  "citation": "Cisco SD-Access / TrustSec Design Guide (VN=VRF, SGT in VXLAN-GPO ~64K, ISE/SGACL); web-verified.",
 },
 {
  "id": "campus-sda-fabric-enabled-wireless-distributed-data-plane",
  "domain": "campus-fabric", "priority": "High", "engine_actionable": False,
  "title": "Put wireless on the fabric: WLC keeps the CAPWAP control plane, but distribute the data plane via VXLAN at the fabric APs",
  "design_intent": "In SD-Access fabric-enabled wireless the WLC is 'fabric-enabled': it still terminates the "
    "CAPWAP CONTROL plane (AP join, RRM, mobility, config) and registers wireless clients into the LISP control "
    "plane, but it does NOT tunnel client DATA back centrally. Instead the fabric APs VXLAN-encapsulate client "
    "traffic directly to the first-hop fabric edge -- so wired and wireless share one anycast gateway and one "
    "SGT/VN policy, the data path is distributed (no CAPWAP data hairpin to the WLC), and segmentation is "
    "consistent across both media.",
  "tradeoffs": "performance + policy-consistency (distributed data plane, one wired+wireless gateway/policy) vs "
    "requiring fabric-capable WLC/APs and the SD-Access fabric itself.",
  "trigger": "Integrating wireless into an SD-Access campus fabric.",
  "observable": "Not collected by an L1-L4 assessment; an SD-Access wireless design.",
  "recommended_action": "Use fabric-enabled wireless so APs VXLAN-encapsulate client data to the local fabric "
    "edge (shared anycast gateway + SGT for wired/wireless), keeping the WLC on the CAPWAP control plane; size "
    "WLC/edge for the distributed model.",
  "alternatives": "Traditional centralized CAPWAP (local-mode, all client data tunneled to the WLC) outside a "
    "fabric, or FlexConnect for branches -- see the wireless WLC-deployment principle.",
  "citation": "Cisco SD-Access Fabric Wireless Design Guide; web-verified.",
 },
 # ---- enterprise wireless ----
 {
  "id": "wireless-wlc-deployment-model-by-survivability-and-wan",
  "domain": "wireless", "priority": "High", "engine_actionable": False,
  "title": "Pick the WLC deployment model (centralized local-mode / FlexConnect / embedded / cloud) from branch survivability and WAN latency",
  "design_intent": "The controller deployment model is the load-bearing wireless decision -- it sets what "
    "survives a WAN/controller outage and where client traffic egresses. Centralized local-mode tunnels all "
    "client data in CAPWAP back to the WLC (clean policy, but a WAN cut kills the branch and hairpins traffic). "
    "FlexConnect local-switching drops client data locally at the AP (with local auth, users survive Standalone "
    "mode on a WAN cut). Embedded (EWC) and cloud-managed (Meraki) suit small/distributed estates.",
  "tradeoffs": "survivability + path-efficiency (local switching survives WAN loss, avoids hairpin) vs policy "
    "centralization/simplicity (centralized local-mode is cleanest where the WAN is reliable).",
  "trigger": "Choosing the wireless controller architecture for campus + branches.",
  "observable": "Not collected by an L1-L4 assessment; a wireless design.",
  "recommended_action": "Keep campus on centralized local-mode within a low-latency LAN; default branches with "
    "unreliable or >100ms WAN to FlexConnect local-switching + local authentication (survive Standalone); use "
    "embedded EWC / cloud-managed for small or highly-distributed sites.",
  "alternatives": "All-centralized where every site has a reliable low-latency path to the WLC; all-cloud "
    "(Meraki) where a controller-less SaaS operating model is preferred.",
  "citation": "Cisco Enterprise Wireless / Catalyst 9800 Design Guide (local-mode vs FlexConnect, CAPWAP); web-verified.",
 },
 {
  "id": "wireless-rf-capacity-not-coverage-cell-sizing-rrm",
  "domain": "wireless", "priority": "High", "engine_actionable": False,
  "title": "Design RF for capacity by shrinking cells (not coverage by raising power); let RRM own channel/power and validate with a survey chain",
  "design_intent": "The foundational RF trade-off is coverage-oriented vs capacity-oriented design, and dense "
    "spaces demand capacity. Coverage design (high power, wide cells, few APs) suits sparse areas but collapses "
    "under density (co-channel contention, one big shared cell). Capacity design lowers AP power and adds APs to "
    "SHRINK cells, raises RX-SOP, disables the lowest legacy data rates, and targets ~15-20% overlap for roaming. "
    "Manual channel/power planning cannot survive a live RF environment -- delegate it to RRM (DCA/TPC/FRA) -- and "
    "a modeled design is only a hypothesis until validated by a predictive -> passive -> active survey chain.",
  "tradeoffs": "capacity + roaming (small cells, RRM-managed, narrow channels) vs AP count/cost; channel-width "
    "(wider = more throughput per client but fewer non-overlapping channels = more contention in density).",
  "trigger": "Designing RF coverage/capacity + validating a WLAN.",
  "observable": "Not collected by an L1-L4 assessment; a wireless RF design.",
  "recommended_action": "For high density, lower AP power + add APs to shrink cells, raise RX-SOP, disable lowest "
    "legacy rates, target ~15-20% overlap, keep placement uniform; enable DCA/TPC/coverage-hole + FRA on XOR "
    "radios; choose narrow (20/40MHz) channel width in density; run predictive -> passive -> active surveys + a "
    "post-install validation.",
  "alternatives": "Coverage-oriented design (high power, wide cells) for warehouses/low-density; wider channels "
    "only where spectrum is clean and client count low.",
  "citation": "Cisco High-Density Wi-Fi / RRM design guidance; web-verified.",
 },
 {
  "id": "wireless-fast-roaming-stack-11r-11k-11v",
  "domain": "wireless", "priority": "High", "engine_actionable": False,
  "title": "Engineer the roam, not just the cell: combine 802.11k/v steering with 802.11r Fast Transition (or OKC) to hold the handoff under the real-time budget",
  "design_intent": "For voice-over-WLAN and real-time apps the failure mode is the ROAM, not the cell: a full "
    "re-authentication on every AP change adds handshake delay that drops calls. The fix is a layered roaming "
    "stack -- 802.11k gives the client a neighbor list (roam to the right AP), 802.11v steers it (BSS-transition), "
    "and 802.11r Fast Transition pre-authenticates so the handoff skips the full EAP/4-way exchange (use OKC for "
    "non-11r clients, adaptive-11r for mixed fleets).",
  "tradeoffs": "convergence/availability for real-time apps (sub-budget handoff) vs client-compatibility care "
    "(11r support varies; adaptive-11r / OKC handle mixed fleets).",
  "trigger": "Designing WLAN for voice/video/real-time roaming-sensitive clients.",
  "observable": "Not collected by an L1-L4 assessment; a wireless roaming design.",
  "recommended_action": "On roam-sensitive SSIDs enable 802.11k neighbor lists + 802.11v BSS-transition steering, "
    "add 802.11r FT (or OKC / adaptive-11r for mixed fleets) to pre-authenticate; keep the roam within an L2 "
    "domain or design L3 roaming via the WLC/fabric.",
  "alternatives": "Plain WPA2/3 re-auth roaming where no real-time apps exist; OKC where the client fleet lacks 11r.",
  "citation": "Cisco wireless roaming design (802.11r/k/v, OKC); web-verified.",
 },
 {
  "id": "wireless-wpa3-owe-8021x-eaptls-security-baseline",
  "domain": "wireless", "priority": "High", "engine_actionable": False,
  "title": "Make WPA3 + PMF the WLAN baseline (OWE for guest, 6GHz WPA3-only with SAE H2E); authenticate corporate with 802.1X/EAP-TLS to ISE",
  "design_intent": "WPA2's structural weaknesses (PSK offline-dictionary attacks, unprotected management frames "
    "enabling deauth) are fixed by WPA3: SAE replaces the 4-way-handshake PSK exchange with a dictionary-attack-"
    "resistant one, and Protected Management Frames stop deauth attacks. 6GHz is WPA3-only (SAE H2E, no WPA2/open). "
    "Corporate WLAN should be identity-based, not a shared secret: 802.1X/EAP to a redundant RADIUS/ISE plane, "
    "preferring certificate-based EAP-TLS (no shared WLAN passwords), with ISE driving dynamic VLAN/SGT/posture.",
  "tradeoffs": "security (dictionary-resistant auth, protected frames, per-identity policy, no shared secrets) vs "
    "client-compatibility (transition-mode SSIDs for WPA2 legacy must be a deliberate, time-boxed choice).",
  "trigger": "Designing WLAN authentication + encryption.",
  "observable": "Not collected by an L1-L4 assessment; a WLAN security design.",
  "recommended_action": "Adopt WPA3 + mandatory PMF as the personal/enterprise baseline, Enhanced-Open (OWE) for "
    "guest, 6GHz strictly WPA3-only with SAE H2E; authenticate managed WLAN with 802.1X to a redundant ISE plane, "
    "prefer EAP-TLS; scope WPA3-Enterprise 192-bit to CNSA-required networks; treat transition-mode SSIDs as "
    "temporary.",
  "alternatives": "WPA2-PSK only for isolated IoT that cannot do WPA3/802.1X (segment it); PSK + ISE for "
    "headless devices via MAB.",
  "citation": "Wi-Fi Alliance WPA3 + Cisco WLAN security design (OWE, SAE H2E, 802.1X/EAP-TLS, ISE); web-verified.",
 },
 {
  "id": "wireless-wifi6e-wifi7-phy-airtime-efficiency-mlo",
  "domain": "wireless", "priority": "Medium", "engine_actionable": False,
  "title": "Exploit Wi-Fi 6/6E airtime efficiency (OFDMA/MU-MIMO/BSS-color/TWT) in dense cells; treat Wi-Fi 7 (802.11be) as a 6GHz-anchored MLO capacity play",
  "design_intent": "802.11ax (Wi-Fi 6/6E) is an EFFICIENCY standard: OFDMA packs many small flows into one "
    "transmit opportunity (Resource Units), MU-MIMO serves spatial-stream-rich high-rate clients in parallel, BSS "
    "Coloring reclaims the medium under co-channel reuse, and TWT schedules battery/IoT wake-ups. Wi-Fi 7 "
    "(802.11be) adds Multi-Link Operation (one association across bands for latency/reliability), 320MHz channels "
    "and 4096-QAM (4K-QAM) -- gains realizable mainly in 6GHz, the only band with contiguous clean spectrum wide "
    "enough; reserve 320MHz for the few cells with clean spectrum + capable clients.",
  "tradeoffs": "throughput + latency + density (efficiency features, MLO reliability) vs client-capability/"
    "spectrum reality (320MHz/4K-QAM only pay off in clean 6GHz with capable clients).",
  "trigger": "Designing for high-density or latency-critical WLAN with modern client mixes.",
  "observable": "Not collected by an L1-L4 assessment; a wireless RF/standards design.",
  "recommended_action": "Enable OFDMA + BSS-Coloring for dense low-rate populations, reserve MU-MIMO for high-rate "
    "clients, apply TWT to IoT/battery; anchor Wi-Fi 7 value in 6GHz with MLO for latency/reliability-critical "
    "SSIDs and 320MHz only where spectrum + clients allow.",
  "alternatives": "Stay on Wi-Fi 5/6 where client fleet and density do not justify 6E/7; 5GHz where 6GHz clients "
    "are absent.",
  "citation": "IEEE 802.11ax / 802.11be + Cisco/Meraki Wi-Fi 6E/7 design; web-verified (Wi-Fi 7 MLO/320MHz/4K-QAM).",
 },
 # ---- network automation / telemetry ----
 {
  "id": "automation-model-driven-config-over-screen-scraped-cli",
  "domain": "automation", "priority": "High", "engine_actionable": False,
  "title": "Drive config through model-based interfaces (NETCONF/RESTCONF/gNMI over YANG) applied transactionally -- not screen-scraped CLI",
  "design_intent": "CLI was authored for humans (per-platform prompts, free-text, no schema), so screen-scraping "
    "is brittle and offers no transactional/validation guarantees. Model-driven interfaces bind to YANG: NETCONF/"
    "RESTCONF/gNMI carry structured config a tool can validate against schema and apply ATOMICALLY (NETCONF "
    "candidate datastore: stage -> validate -> confirmed-commit with an auto-revert timer so a change that severs "
    "your own management path rolls back). The data-model is itself a choice: OpenConfig/IETF for multivendor "
    "portability, native YANG (contained) for full feature fidelity -- expect to mix both.",
  "tradeoffs": "reliability + multivendor portability + transactional safety vs the tooling/skills shift off CLI "
    "and uneven YANG-path/feature coverage per platform.",
  "trigger": "Designing how device configuration is rendered and applied.",
  "observable": "Not collected by an L1-L4 assessment; an automation operating-model design.",
  "recommended_action": "Standardize on a model-driven transport (NETCONF/gNMI for config, RESTCONF where a REST/"
    "JSON toolchain fits) bound to YANG; apply via candidate-commit with confirmed-commit/auto-revert for risky "
    "in-band changes; default to OpenConfig/IETF models for the portable surface, native YANG only where features demand.",
  "alternatives": "Templated CLI push (Netmiko/Jinja) as a transitional bridge on platforms lacking model support; "
    "vendor controllers (NSO/Catalyst Center) abstracting the model.",
  "citation": "NETCONF/RESTCONF (RFC 6241/8040) + YANG (RFC 7950) + OpenConfig + gNMI; web-verified.",
 },
 {
  "id": "automation-network-source-of-truth-declarative-idempotent",
  "domain": "automation", "priority": "High", "engine_actionable": False,
  "title": "Anchor automation on a Network Source of Truth holding intended state; render config from it declaratively and idempotently, never the reverse",
  "design_intent": "Automation without a single authoritative model of intent just scales inconsistency. A Network "
    "Source of Truth (e.g. NetBox) holds the INTENDED state; device configuration is rendered as a deterministic "
    "function of SoT data + templates, so 'what should this network be' has a canonical answer and drift is "
    "detectable as SoT-vs-device diff. Express change as DECLARATIVE desired-state (Terraform/OpenTofu, NSO "
    "service intent, idempotent Ansible) so the engine computes and applies the delta -- imperative step-scripts "
    "re-encode 'how' for every change and compound damage on a half-applied retry.",
  "tradeoffs": "consistency + drift-detection + safe re-runs (idempotent declarative + SoT) vs the up-front "
    "modelling discipline (populate + govern the SoT; design the render pipeline).",
  "trigger": "Establishing the automation architecture / operating model.",
  "observable": "Not collected by an L1-L4 assessment; an automation design.",
  "recommended_action": "Stand up a Network Source of Truth as the authoritative intended-state store; render "
    "device config from SoT + templates (config = function of intent); model change as declarative idempotent "
    "desired-state (Terraform/NSO/idempotent Ansible) so the tool reconciles the delta; detect drift as SoT-vs-device diff.",
  "alternatives": "Imperative runbooks/scripts for one-off tactical changes; spreadsheet+CLI for tiny static "
    "estates (accepting drift).",
  "citation": "Network Source of Truth (NetBox) + IaC (Terraform/Ansible/NSO) design practice; web-verified.",
 },
 {
  "id": "automation-gitops-cicd-pre-post-validation-pipeline",
  "domain": "automation", "priority": "High", "engine_actionable": False,
  "title": "Make network change a Git-reviewed CI/CD pipeline with offline pre-change and post-change validation",
  "design_intent": "Treating network change as code (GitOps) gives governance ad-hoc device edits cannot: every "
    "change is a peer-reviewed merge request against the Git repo that is the source of truth, so branch-"
    "protection + CODEOWNERS enforce review, CI runs pre-change validation (lint/schema, and ideally a virtual "
    "twin / batfish-style what-if), the merge triggers deploy, and post-change validation confirms the intended "
    "state and triggers rollback on failure. The repo is the audit trail and the rollback source.",
  "tradeoffs": "change safety + governance + auditability vs the pipeline/CI build-out + the cultural shift to "
    "review-before-merge.",
  "trigger": "Designing the network change-management / deployment workflow.",
  "observable": "Not collected by an L1-L4 assessment; a change-pipeline design.",
  "recommended_action": "Adopt a GitOps pipeline: intent/config in Git (source of truth), every change a reviewed "
    "MR with branch-protection + CODEOWNERS; CI runs offline pre-change validation; deploy on merge; run post-"
    "change validation and auto-rollback on failure; keep the repo as the audit + rollback source.",
  "alternatives": "A lighter reviewed-change lifecycle (the KB's mgmt-change-config-automation) where a full CI/CD "
    "pipeline is unjustified; ticket-gated manual change for tiny estates.",
  "citation": "NetDevOps / GitOps for network automation (CI/CD, pre/post validation); web-verified.",
 },
 {
  "id": "automation-streaming-telemetry-subscriptions-what-and-cadence",
  "domain": "automation", "priority": "High", "engine_actionable": False,
  "title": "Replace SNMP polling with model-driven streaming telemetry: named YANG-path subscriptions, on-change for state and tiered periodic for counters, dial-out by default",
  "design_intent": "SNMP poll/trap forces the collector to ask, on a fixed interval, for a flattened MIB -- it "
    "cannot say 'tell me only when this changes', cannot subscribe to a precise sub-tree, and scales poorly. "
    "Model-driven telemetry (gNMI/gRPC subscriptions on explicit YANG xpaths) pushes data: on-change for "
    "operational STATE/events (interface/protocol/neighbor state, alarms, config commits) so faults arrive as "
    "they happen, and tiered periodic for counters -- never one global short interval ('SNMP but faster' destroys "
    "the value). Default to dial-out gRPC for large/zero-touch fleets; size a redundant collector->TSDB pipeline.",
  "tradeoffs": "fault-detection speed + fidelity + scale (push, sub-tree, on-change) vs designing the "
    "subscription plan + a sized, redundant collector/TSDB pipeline (cardinality matters).",
  "trigger": "Designing network observability / telemetry collection.",
  "observable": "Not collected by an L1-L4 assessment; a telemetry design.",
  "recommended_action": "Specify telemetry as named subscriptions on explicit YANG paths: on-change for state/"
    "events, tiered periodic for counters; default dial-out gRPC for fleets; verify path mode via the device's "
    "mdt-capabilities; size a redundant collector + time-series store to the stream rate/cardinality; add flow "
    "telemetry (full NetFlow/IPFIX for security, sampled for capacity) for the traffic matrix.",
  "alternatives": "SNMPv3 retained only as a fallback for un-instrumented gear; dial-in gRPC where the device "
    "must initiate to a fixed collector.",
  "citation": "gNMI/gRPC model-driven telemetry + NetFlow/IPFIX design; web-verified (beyond the KB's modern-telemetry principle).",
 },
 {
  "id": "automation-assurance-active-synthetic-closed-loop",
  "domain": "automation", "priority": "Medium", "engine_actionable": False,
  "title": "Add active/synthetic assurance for paths you don't own, baseline per-network with AI analytics, and close the loop only on verified telemetry + safe rollback",
  "design_intent": "Device telemetry describes the network you own -- but user experience increasingly traverses "
    "the Internet, SaaS and clouds you do NOT own, where there is no device to stream from. Active/synthetic "
    "assurance (enterprise/endpoint/cloud agents probing real user paths, e.g. ThousandEyes) measures those off-"
    "net paths. An assurance platform (Catalyst Center Assurance / AI Network Analytics) learns each network's own "
    "adaptive baseline and flags anomalies -- but health scores are DERIVED telemetry whose inputs/thresholds you "
    "must own. Closed-loop remediation is safe only when driven by verified telemetry with a tested rollback.",
  "tradeoffs": "end-to-end visibility + faster anomaly detection (off-net + AI baselines) vs trusting derived "
    "scores (own the inputs) and the risk of closed-loop action (gate on verification + rollback).",
  "trigger": "Designing assurance / closed-loop operations for an estate with SaaS/cloud/Internet dependence.",
  "observable": "Not collected by an L1-L4 assessment; an assurance design.",
  "recommended_action": "Place active/synthetic agents at user-representative vantage points (branch/DC/cloud) to "
    "measure off-net paths; use AI analytics for adaptive per-site baselines/anomaly ranking rather than static "
    "global thresholds, owning the inputs; gate any closed-loop remediation on verified telemetry + a tested rollback.",
  "alternatives": "Passive device telemetry only where all critical paths are on-net; manual NOC triage where "
    "closed-loop automation is not yet trusted.",
  "citation": "ThousandEyes / Catalyst Center Assurance + closed-loop automation design; web-verified.",
 },
 # ---- DC compute + storage + DCI ----
 {
  "id": "dc-compute-ucs-fabric-interconnect-end-host-mode-default",
  "domain": "dc-compute", "priority": "High", "engine_actionable": False,
  "title": "Run UCS Fabric Interconnects in end-host mode by default; carry disjoint upstream L2 by VLAN-to-uplink pinning, not switch mode",
  "design_intent": "A UCS Fabric Interconnect terminating dozens-to-hundreds of blades is a giant aggregation "
    "point. End-host mode presents its uplinks to the upstream LAN as if it were a big multi-homed server -- it "
    "runs no STP and creates no loops upstream, pinning server vNICs to uplinks (MAC-pinning). When blades must "
    "reach multiple separate upstream L2 domains (prod / backup / DMZ / OOB that are intentionally NOT bridged), "
    "the wrong reflex is FI switch mode (which bridges them + reintroduces STP); the right design is disjoint L2 "
    "by non-overlapping VLAN-to-uplink pinning with one vNIC per domain.",
  "tradeoffs": "simplicity + loop-freedom + upstream-scale (end-host mode, no STP) vs the rare case needing the FI "
    "to switch (switch mode) -- which reintroduces STP and is a last resort.",
  "trigger": "Designing UCS Fabric Interconnect upstream connectivity.",
  "observable": "Not collected by an L1-L4 assessment; a UCS compute-network design.",
  "recommended_action": "Default the FI pair to end-host mode, bundle uplinks to the upstream (vPC) pair as port-"
    "channels; for multiple disjoint upstream L2 domains use non-overlapping VLAN-to-uplink pinning with one vNIC "
    "per domain; reserve switch mode for genuinely upstream-incapable cases.",
  "alternatives": "FI switch mode only where the FI must actively switch between upstreams that cannot do it; "
    "rack servers direct to ToR where UCS-managed compute is not used.",
  "citation": "Cisco UCS Design Guide (end-host mode, disjoint L2, uplink pinning); web-verified.",
 },
 {
  "id": "dc-compute-ucs-stateless-service-profiles-and-fcoe-edge",
  "domain": "dc-compute", "priority": "High", "engine_actionable": False,
  "title": "Abstract server identity into stateless service profiles from pools/templates (UCS Manager per-domain vs Intersight), and engineer a lossless no-drop class if converging FCoE",
  "design_intent": "In UCS a server's personality (UUID, every vNIC MAC, every vHBA WWNN/WWPN, BIOS/boot/firmware "
    "policy, VLAN/VSAN/QoS bindings) is abstracted out of the physical blade into a logical service profile built "
    "from non-overlapping POOLS and stamped from TEMPLATES -- so compute is stateless and a profile can move to a "
    "spare blade in minutes. Operate the fleet through this policy/profile/template hierarchy (embedded UCS "
    "Manager per single domain; Intersight for multi-domain/cloud). If converging SAN onto the same fabric with "
    "FCoE, FC's lossless assumption must be recreated in ONE no-drop class engineered end-to-end (PFC + ETS + DCBX).",
  "tradeoffs": "agility + consistency (stateless, pool/template-driven, fast re-provision) vs the modelling "
    "discipline (pools/templates/policies) -- and FCoE convergence adds a strict lossless-class requirement.",
  "trigger": "Designing UCS compute provisioning (and optional FCoE convergence).",
  "observable": "Not collected by an L1-L4 assessment; a UCS design.",
  "recommended_action": "Derive every identity from non-overlapping pools, stamp service profiles from templates "
    "(updating templates for fleet change); operate via UCS Manager (single domain) or Intersight (multi-domain); "
    "if converging FCoE, define one no-drop CoS engineered end-to-end (PFC on the FCoE priority, ETS bandwidth, "
    "DCBX auto-negotiation), keeping the storage VLAN distinct from LAN.",
  "alternatives": "Per-server manual config (no statelessness) for tiny estates; keep LAN and SAN on separate "
    "adapters/fabrics where convergence isn't justified (the KB's unified-fabric principle).",
  "citation": "Cisco UCS / Intersight + FCoE DCB design; web-verified.",
 },
 {
  "id": "dc-compute-san-dual-fabric-air-gap-and-storage-transport",
  "domain": "dc-compute", "priority": "Medium", "engine_actionable": False,
  "title": "Build two air-gapped SAN fabrics (A/B) that never merge with single-initiator zoning; pick the storage transport (NVMe/FC or NVMe/TCP before RoCE; iSCSI as legacy) by loss-sensitivity",
  "design_intent": "Storage availability comes from two COMPLETELY independent fabrics, not redundancy inside one: "
    "each host and array dual-attaches one port to SAN A and one to SAN B, host multipathing rides the survivor, "
    "and A is NEVER connected to B (a merge or a fabric-wide event then can't take both). Zone single-initiator-"
    "to-target by pWWN, with NPV/NPIV at the edge. The transport choice is really how much lossless discipline "
    "operations must carry: NVMe/FC keeps the proven FC model (built-in flow control, A/B, no Ethernet DCB "
    "tuning); NVMe/TCP suits standard-Ethernet/cloud-native; NVMe/RoCEv2 only when the latency budget justifies a "
    "verified end-to-end lossless build; iSCSI is the legacy IP-storage option.",
  "tradeoffs": "availability + integrity (independent A/B, single-initiator zoning) vs cost/operational-model; "
    "transport: FC-grade determinism vs Ethernet simplicity vs RoCE latency-at-lossless-complexity.",
  "trigger": "Designing SAN/storage networking for a DC.",
  "observable": "Not collected by an L1-L4 assessment; a storage-network design.",
  "recommended_action": "Provision two physically+logically separate fabrics; dual-attach every host/array (one "
    "port per fabric) with multipathing; never connect A to B; zone single-initiator-to-target by pWWN; NPV/NPIV "
    "at the edge; default the transport to NVMe/FC where FC exists or NVMe/TCP for standard Ethernet, RoCEv2 only "
    "with a verified lossless fabric.",
  "alternatives": "Single converged FCoE fabric (the unified-fabric principle) where adapter/port reduction "
    "dominates and dual-fabric SAN isolation is not required; iSCSI for cost-sensitive IP storage.",
  "citation": "Cisco MDS / SAN design + NVMe-oF (NVMe/FC, NVMe/TCP, NVMe/RoCE) guidance; web-verified.",
 },
 {
  "id": "dc-compute-otv-control-plane-dci-mac-routing-aed",
  "domain": "dc-compute", "priority": "Medium", "engine_actionable": False,
  "title": "Extend L2 between DCs with a control-plane DCI (OTV-style): advertise MACs, suppress unknown-unicast/ARP across the interconnect, and multihome with per-VLAN AED",
  "design_intent": "When two-three DCs must share L2 subnets, the danger is fate-sharing the failure domain across "
    "the WAN. OTV contains it by treating MAC reachability as ROUTING: an IS-IS overlay control plane advertises "
    "which MACs live at which site, suppresses unknown-unicast flooding and ARP across the overlay, and filters "
    "BPDUs/FHRP so each site keeps its own STP root and gateway -- only the VLANs that truly need stretching are "
    "extended. Multihoming is made loop-free by the Authoritative Edge Device role: a deterministic per-VLAN split "
    "(plus a site-VLAN and site-ID) keeps dual edges active/active without a loop.",
  "tradeoffs": "L2 extension WITH failure-domain containment (MAC-routing, no flood, per-site STP/FHRP) vs the "
    "preference to avoid stretched L2 at all (L3 DCI is safer where the app allows).",
  "trigger": "Designing DC interconnect where some VLANs must be L2-extended.",
  "observable": "Not collected by an L1-L4 assessment; a DCI design.",
  "recommended_action": "Extend only the VLANs that truly need it over a control-plane DCI (OTV or equivalent) "
    "that advertises MACs, suppresses unknown-unicast + ARP, and filters BPDU/FHRP per site; deploy >= 2 edge "
    "devices per site with per-VLAN AED election + a dedicated site-VLAN and unique site-ID.",
  "alternatives": "VXLAN-EVPN Multi-Site (the KB's dc-multisite principle) for modern fabric DCI; prefer L3 DCI "
    "(the KB's prefer-L3-DCI principle) wherever the application does not require stretched L2.",
  "citation": "Cisco OTV DCI design (IS-IS overlay, AED, unknown-unicast suppression); web-verified.",
 },
 # ---- cloud-native / container / cloud connectivity ----
 {
  "id": "cloud-native-cni-overlay-vs-bgp-native-and-dataplane",
  "domain": "cloud-native", "priority": "Medium", "engine_actionable": False,
  "title": "Make pod-network reachability a deliberate overlay-vs-BGP-native choice with a managed IPAM plan, and pick the CNI data plane (eBPF vs iptables) by scale",
  "design_intent": "Pods need an IP and a path off the node, and a Kubernetes cluster is an address SINK (a node "
    "CIDR + large pod and Service CIDRs, often a /24 of pod space per node) that can exhaust enterprise RFC1918 "
    "and overlap on-prem. The CNI offers an encapsulated OVERLAY (VXLAN / Calico IP-in-IP -- underlay sees only "
    "node IPs) vs non-overlay BGP-NATIVE routing (pod IPs routable + inspectable, each node BGP-peers its ToR). "
    "And the data plane (legacy kube-proxy iptables/IPVS rule chains vs an eBPF data plane like Cilium) decides "
    "forwarding/Service-LB scale. Treat pod/Service CIDRs as managed, non-overlapping enterprise prefixes.",
  "tradeoffs": "routability + visibility + scale (BGP-native + eBPF) vs simplicity/underlay-independence (overlay) "
    "and the IPAM cost of routable pod space; eBPF scale vs kube-proxy familiarity.",
  "trigger": "Designing Kubernetes cluster networking + pod IPAM.",
  "observable": "Not collected by an L1-L4 assessment; a container-network design.",
  "recommended_action": "Plan pod/Service CIDRs as coordinated, non-overlapping enterprise prefixes sized for "
    "real scale; on a BGP-capable fabric prefer non-overlay BGP-native routing (peer each node to its ToR) so pod "
    "IPs are routable/inspectable; default to an eBPF data plane (Cilium kube-proxy replacement) past a few "
    "hundred Services or where DSR/socket-LB/identity policy is needed.",
  "alternatives": "Encapsulated overlay (VXLAN/IP-in-IP) where the underlay cannot route pod space or "
    "underlay-independence is wanted; kube-proxy/iptables for small clusters.",
  "citation": "Kubernetes CNI design (Calico/Cilium, overlay vs BGP, eBPF vs iptables, IPAM); web-verified.",
 },
 {
  "id": "cloud-native-identity-microsegmentation-networkpolicy",
  "domain": "cloud-native", "priority": "Medium", "engine_actionable": False,
  "title": "Segment pods by workload identity (labels), default-deny -- never by ephemeral pod IP/CIDR -- and front north-south with stable ingress/egress gateways",
  "design_intent": "Pod IPs are ephemeral and reused, so an IP/CIDR ACL is stale the moment a pod reschedules. "
    "Kubernetes NetworkPolicy (and CiliumNetworkPolicy) express allow rules in terms of pod/namespace LABELS "
    "(workload identity), which the CNI resolves to current endpoints -- so segmentation follows the workload, not "
    "the address. Default-deny per namespace and allow by identity. And because pod/node IPs churn, the rest of "
    "the enterprise (firewalls, partners, DNS) must never depend on one: funnel north-south through stable ingress/"
    "Gateway-API entry points and a pinned egress gateway.",
  "tradeoffs": "security + stability (identity policy that follows the workload; stable N-S edges) vs the labelling/"
    "policy discipline and CNI feature dependency.",
  "trigger": "Designing east-west segmentation + north-south edges for a cluster.",
  "observable": "Not collected by an L1-L4 assessment; a container-security design.",
  "recommended_action": "Adopt namespace default-deny; author NetworkPolicy/CiliumNetworkPolicy by pod/namespace "
    "labels (identity), reserving CIDR selectors only for genuinely external endpoints; expose inbound only via an "
    "HA ingress/Gateway-API gateway and route compliance-sensitive egress through a pinned egress gateway.",
  "alternatives": "Perimeter firewalling at the cluster edge only (no in-cluster micro-seg) for low-sensitivity "
    "clusters; service-mesh authz (below) for L7 identity policy.",
  "citation": "Kubernetes NetworkPolicy + CiliumNetworkPolicy + Gateway-API design; web-verified.",
 },
 {
  "id": "cloud-native-service-mesh-ambient-vs-sidecar",
  "domain": "cloud-native", "priority": "Medium", "engine_actionable": False,
  "title": "Split the service mesh into always-on L4 mTLS and opt-in L7 (ambient ztunnel + waypoint), rather than an Envoy sidecar in every pod",
  "design_intent": "A service mesh provides east-west mTLS identity, L7 traffic management and observability. The "
    "classic model injects an Envoy SIDECAR into every pod -- per-pod CPU/memory, lifecycle coupling, restart-to-"
    "enroll, a double hop. The 2024-25 shift is sidecarless: Istio AMBIENT mode separates a per-NODE ztunnel "
    "(cluster-wide L4 identity/mTLS) from namespace-scoped WAYPOINT proxies added only where L7 is needed; Cilium's "
    "eBPF mesh pushes identity-aware policy into the kernel and uses Envoy only when necessary -- both cut the "
    "per-pod overhead and the operational coupling of sidecars.",
  "tradeoffs": "lower overhead + simpler lifecycle (no per-pod proxy; L4 always-on, L7 opt-in) vs a newer "
    "operating model and the need to scope waypoints deliberately.",
  "trigger": "Adding a service mesh for east-west mTLS / L7 / observability.",
  "observable": "Not collected by an L1-L4 assessment; a container-mesh design.",
  "recommended_action": "Default new meshes to ambient: per-node ztunnel for cluster-wide L4 mTLS/identity, add "
    "namespace-scoped waypoint proxies only for services needing L7 routing/retries/authz; or a Cilium eBPF mesh "
    "where the CNI already provides it -- reserving sidecars for cases that genuinely require per-pod Envoy.",
  "alternatives": "Sidecar mesh where mature tooling/per-pod isolation is required and the overhead is acceptable; "
    "no mesh (NetworkPolicy + ingress) where L7 identity/observability is not needed.",
  "citation": "Istio Ambient (ztunnel/waypoint) + Cilium Service Mesh (eBPF, sidecarless) design; web-verified.",
 },
 {
  "id": "cloud-vpc-az-striped-tiers-transit-hub-and-central-egress",
  "domain": "cloud-native", "priority": "Medium", "engine_actionable": False,
  "title": "Design cloud VPC/VNet as AZ-striped subnet tiers, interconnect via a transit hub (not full-mesh peering), and centralize egress/inspection per-AZ",
  "design_intent": "A cloud subnet is NOT an on-prem broadcast domain: it is Availability-Zone-scoped and purely a "
    "routing+policy construct, so each functional tier (public/app/data) is replicated and STRIPED across >= 2-3 "
    "AZs from a hierarchical, summarizable, non-overlapping IP plan (distinct CIDRs per on-prem/region/account). "
    "VPC/VNet peering is non-transitive and O(n^2), so beyond a handful of networks interconnect via a TRANSIT "
    "hub (Transit Gateway / Virtual WAN / hub-VNet) for transitive routing + segmentation. And rather than a "
    "NAT+IGW + firewall in every spoke, centralize internet egress and inspection in a shared-services hub "
    "deployed per-AZ -- one policy/logging chokepoint.",
  "tradeoffs": "scalability + segmentation + single-inspection-point (transit hub, central egress) vs hub cost/"
    "bandwidth + a deliberate per-AZ HA build; layered stateless-subnet-ACL under stateful-instance rules.",
  "trigger": "Designing cloud (VPC/VNet) connectivity + segmentation + egress.",
  "observable": "Not collected by an L1-L4 assessment; a cloud-network design.",
  "recommended_action": "Draw a hierarchical non-overlapping IP plan first (distinct CIDRs per on-prem/region/"
    "account); stripe each tier across >= 2-3 AZs; layer stateful instance rules under stateless subnet ACLs; "
    "interconnect via a transit hub once VPC count/transitive needs appear; route spoke egress through a shared "
    "egress/inspection VPC instantiated in every AZ; resolve hybrid private DNS via hub resolver endpoints.",
  "alternatives": "Direct VPC peering for a handful of stable networks; per-spoke egress only for tiny isolated "
    "workloads (accepting scattered policy/cost).",
  "citation": "AWS/Azure cloud network design (Transit Gateway / vWAN, AZ subnets, centralized egress, Route 53/"
    "DNS); web-verified.",
 },
 {
  "id": "cloud-hybrid-dedicated-circuit-primary-vpn-backup-and-onramp",
  "domain": "cloud-native", "priority": "High", "engine_actionable": False,
  "title": "Connect on-prem to cloud over a dedicated circuit (Direct Connect/ExpressRoute) as primary with a diverse second path + BGP, IPsec VPN as backup; extend an existing SD-WAN via Cloud OnRamp",
  "design_intent": "Internet IPsec VPN to the cloud is cheap and fast to stand up but inherits public-internet "
    "jitter/loss and a throughput ceiling; a dedicated private circuit (AWS Direct Connect / Azure ExpressRoute) "
    "gives predictable latency and higher, more consistent bandwidth -- but a single circuit/router/location is a "
    "SPOF, so a production hybrid path needs a diverse second circuit (separate path/location, redundant edges, "
    "dual VIFs) with BGP for automatic failover, and an IPsec VPN as cheap backup. And an enterprise that already "
    "runs SD-WAN should extend it with Cloud OnRamp (automated peering to TGW/vWAN/GCP) rather than hand-build a "
    "different connectivity+security model in each cloud.",
  "tradeoffs": "availability + predictability (dedicated + diverse second path + BGP) vs cost (two circuits) -- and "
    "reuse-of-fabric (SD-WAN Cloud OnRamp) vs per-cloud bespoke builds.",
  "trigger": "Designing on-prem-to-cloud / hybrid connectivity.",
  "observable": "Not collected by an L1-L4 assessment; a hybrid-cloud design.",
  "recommended_action": "Make a dedicated private circuit the primary hybrid path, provision a second on diverse "
    "paths/locations (redundant edges, dual VIFs) with BGP for failover, keep an IPsec VPN as backup; where an "
    "SD-WAN fabric exists, extend it with Cloud OnRamp for Multicloud so segmentation + app-aware policy reach the "
    "cloud uniformly.",
  "alternatives": "IPsec VPN only for non-critical/low-bandwidth or rapid-standup; single circuit only for "
    "dev/test where an outage is tolerable.",
  "citation": "AWS Direct Connect / Azure ExpressRoute resiliency + Cisco SD-WAN Cloud OnRamp design; web-verified.",
 },
 # ---- IPv6 depth ----
 {
  "id": "ipv6-addressing-plan-nibble-hierarchy-64-boundary",
  "domain": "ipv6", "priority": "High", "engine_actionable": False,
  "title": "Build a deterministic nibble-aligned IPv6 plan from a /48, hold every host subnet at /64, and delegate downstream with DHCPv6-PD",
  "design_intent": "An IPv6 plan is not a scarcity exercise -- with a /48 (65,536 /64s) per site you stop "
    "conserving and instead encode TOPOLOGY into the address so the prefix is self-documenting and summarizable. "
    "Fix every host/access subnet at /64 (SLAAC and many features require it), reserve nibble-aligned blocks per "
    "region -> site -> role -> VLAN, and align summary boundaries to aggregation points. For automated downstream "
    "hierarchy, DHCPv6 Prefix Delegation (RFC 8415) hands a sub-prefix (e.g. /56 or /60 from the site /48) to "
    "downstream routers, keeping delegation boundaries nibble-aligned.",
  "tradeoffs": "manageability + summarizability (self-documenting, hierarchical, /64-uniform) vs the discipline of "
    "designing the hierarchy up front (and not 'sub-/64' to save space, which breaks SLAAC).",
  "trigger": "Designing the IPv6 addressing plan.",
  "observable": "Not collected by an L1-L4 assessment; an IPv6 design (the KB's single ipv6 principle covers "
    "transition, not the addressing plan).",
  "recommended_action": "Obtain a /48 per site (/44-/40 for large multi-region orgs); reserve nibble-aligned "
    "blocks per region->site->role->VLAN; allocate host/access subnets as /64 only; align summary boundaries to "
    "aggregation; use DHCPv6-PD for downstream sub-prefix delegation.",
  "alternatives": "Provider-assigned addressing where PI space isn't available (design for renumbering); ULA as a "
    "stable internal adjunct (below), never as IPv6 'private NAT'.",
  "citation": "IPv6 addressing architecture (RFC 4291) + DHCPv6-PD (RFC 8415); web-verified.",
 },
 {
  "id": "ipv6-host-config-slaac-vs-dhcpv6-and-gua-not-nat",
  "domain": "ipv6", "priority": "High", "engine_actionable": False,
  "title": "Pick the host-config model per RA M/O flags (design for the Android no-DHCPv6 reality); default to GUA end-to-end, ULA only as a stable adjunct -- never NAT",
  "design_intent": "How hosts get addresses is governed by the RA M (managed) and O (other-config) flags plus the "
    "per-prefix A (autonomous) flag. SLAAC (A=1, M=0) is universal and serverless but yields no central record/"
    "reservation; stateful DHCPv6 (M=1) gives control but ANDROID DOES NOT SUPPORT DHCPv6 -- so on mixed-OS/BYOD/"
    "wireless segments you must use SLAAC + stateless DHCPv6 (O=1) for DNS, reserving stateful DHCPv6 for tightly-"
    "managed Android-free segments. And IPv6 ends address scarcity, so the IPv4 reflex of 'private space + NAT' is "
    "an anti-pattern: assign Global Unicast end-to-end and enforce reachability with firewalls/ACLs, adding ULA "
    "(RFC 4193) only as a stable internal adjunct for renumber-independence.",
  "tradeoffs": "compatibility (SLAAC works everywhere incl. Android) vs central control (stateful DHCPv6 records/"
    "reservations but no Android); security-via-firewall (GUA + stateful ACL) vs the false comfort of NAT.",
  "trigger": "Designing IPv6 host addressing + the GUA/ULA model.",
  "observable": "Not collected by an L1-L4 assessment; an IPv6 design.",
  "recommended_action": "For mixed-OS/BYOD/wireless use SLAAC (A=1) + stateless DHCPv6 (O=1) for DNS; reserve "
    "stateful DHCPv6 (M=1) for managed Android-free segments; default to GUA end-to-end secured by stateful "
    "firewall/ACLs (no NAT); add ULA only where renumber-independence / hard-offline-internal is required.",
  "alternatives": "Stateful DHCPv6 everywhere only on an Android-free managed estate; NPTv6 (prefix translation, "
    "not NAT44-style) only for specific multihoming/renumber cases.",
  "citation": "IPv6 SLAAC (RFC 4862) / DHCPv6 (RFC 8415) / ULA (RFC 4193) design; web-verified (Android no-DHCPv6).",
 },
 {
  "id": "ipv6-transition-dualstack-then-ipv6-mostly-translation",
  "domain": "ipv6", "priority": "High", "engine_actionable": False,
  "title": "Choose the coexistence model deliberately: dual-stack to de-risk, then IPv6-mostly (NAT64/DNS64/464XLAT, PREF64, DHCPv4 Option 108) to retire IPv4 at the edge",
  "design_intent": "Coexistence is a spectrum, not a switch. Dual-stack (v4 and v6 in parallel) is the lowest-risk "
    "first step but DOUBLES the operational surface (two tables, two ACL sets, two failure modes) and never "
    "reduces IPv4 dependence. The modern endpoint is to move user/wireless segments to IPv6-MOSTLY: deploy NAT64 + "
    "DNS64, advertise PREF64 in RAs (don't rely on DNS64 alone), and emit DHCPv4 Option 108 so CLAT-capable "
    "clients (464XLAT) go single-stack IPv6 while legacy IPv4-only apps still work via the translator -- shrinking "
    "the IPv4 footprint to the translator.",
  "tradeoffs": "de-risking (dual-stack first) vs operational doubling; IPv6-mostly retires edge IPv4 "
    "(simplification, address relief) at the cost of a translation tier + its correctness (PREF64, Option 108).",
  "trigger": "Planning the IPv4->IPv6 coexistence/transition.",
  "observable": "Not collected by an L1-L4 assessment; an IPv6 transition design (extends the KB's dual-stack/6VPE principle).",
  "recommended_action": "Start dual-stack to de-risk; then move user/wireless segments to IPv6-mostly with NAT64+"
    "DNS64, PREF64 advertised in RAs, and DHCPv4 Option 108 for CLAT/464XLAT clients; keep IPv4 only where "
    "dependencies require it, behind the translator.",
  "alternatives": "Stay dual-stack where translation can't be validated for all apps; carry IPv6 over MPLS with "
    "6VPE/6PE (the existing principle) on an IPv4/MPLS core.",
  "citation": "IPv6 transition (NAT64/DNS64 RFC 6146/6147, 464XLAT RFC 6877, PREF64 RFC 8781, DHCP Option 108 RFC "
    "8925); web-verified.",
 },
 # ---- ACI-advanced (depth beyond wave-1) ----
 {
  "id": "aci-fabric-golf-l3out-at-spine-for-wan-scale",
  "domain": "aci-fabric", "priority": "Medium", "engine_actionable": False,
  "title": "Move the L3Out to the spine (GOLF) when per-tenant border-leaf WAN scale runs out -- the WAN edge becomes a logical border-leaf via MP-BGP EVPN + VXLAN",
  "design_intent": "When per-tenant L3Outs at border leaves no longer scale (one BGP session + one config block "
    "per VRF, multiplied by tenant count), relocate the fabric-to-WAN handoff to the spine using L3 EVPN 'GOLF': "
    "the spines hold a single MP-BGP EVPN session (Type-5 IP-Prefix NLRI) + VXLAN to WAN-edge routers acting as "
    "logical border-leaves, with OpFlex automating per-VRF provisioning -- so adding a tenant no longer adds "
    "border-leaf config. For a stretched (Multi-Pod) fabric with GOLF, ingress/egress path symmetry must be "
    "engineered (host-routes inbound, local-GOLF egress preference) or traffic hairpins across the inter-pod network.",
  "tradeoffs": "scalability (one spine EVPN session replaces N per-tenant border-leaf L3Outs) vs added GOLF/EVPN "
    "complexity at the spine + the path-symmetry engineering on a stretched fabric.",
  "trigger": "Designing ACI WAN connectivity where border-leaf L3Out scale is the constraint.",
  "observable": "Not collected by an L1-L4 assessment; an ACI WAN design (depth beyond wave-1 L3Out principles).",
  "recommended_action": "Where border-leaf L3Out scale is the limit, use GOLF (spine MP-BGP EVPN Type-5 + VXLAN to "
    "WAN-edge logical border-leaves, OpFlex-automated per-VRF); on a stretched fabric engineer ingress/egress "
    "symmetry (advertise fabric host-routes inbound, prefer the local GOLF for egress, AS-path tuning per pod).",
  "alternatives": "Per-tenant border-leaf L3Outs (the wave-1 model) where tenant/VRF count is modest; standalone "
    "NX-OS VXLAN-EVPN border for a non-ACI fabric.",
  "citation": "Cisco ACI GOLF / Layer-3 EVPN WAN design; web-verified.",
 },
 {
  "id": "aci-fabric-vmm-domain-virtual-leaf-integration",
  "domain": "aci-fabric", "priority": "Medium", "engine_actionable": False,
  "title": "Extend the fabric policy edge into the hypervisor with a VMM domain (APIC-driven DVS / AVE, OpFlex policy) and choose the micro-seg enforcement locus deliberately",
  "design_intent": "The fabric's policy edge should extend into the hypervisor as a controller-managed virtual "
    "leaf, not stop at the physical ToR. A VMM (Virtual Machine Manager) domain pairs APIC with vCenter/OpenStack/"
    "K8s so creating the domain auto-provisions the virtual switch and pushes per-EPG port-groups/encapsulation, "
    "with OpFlex (not CDP/LLDP) carrying policy + endpoint state. ACI Virtual Edge (AVE) goes further -- a virtual "
    "leaf that can do local switching and stateful intra-host firewalling inside the hypervisor. The design choice "
    "is the ENFORCEMENT LOCUS: hypervisor local-switching filters east-west/intra-EPG on the host (efficient, "
    "workload-proximate) vs hairpinning to the physical leaf -- and enabling the stateful hypervisor firewall "
    "couples live workload mobility (vMotion) to an inter-instance connection-state-sync path that must be designed.",
  "tradeoffs": "policy consistency + efficiency (controller-driven vSwitch, host-local enforcement) vs the VMM/"
    "OpFlex integration + (for stateful firewalling) a designed state-replication path that couples to mobility.",
  "trigger": "Designing ACI integration with a virtualization platform / hypervisor micro-segmentation.",
  "observable": "Not collected by an L1-L4 assessment; an ACI VMM design (beyond wave-1).",
  "recommended_action": "Integrate a VMM domain so APIC drives the DVS and pushes per-EPG port-groups, with OpFlex "
    "as the policy/endpoint plane; use AVE/virtual-leaf local switching where host-proximate east-west filtering "
    "is wanted; before enabling the stateful hypervisor firewall, design + monitor the inter-instance state-sync "
    "path that vMotion depends on.",
  "alternatives": "Physical-leaf-only enforcement (hairpin) where hypervisor integration is not available/desired; "
    "standalone NX-OS-EVPN + host networking outside ACI.",
  "citation": "Cisco ACI VMM domain / AVE / micro-segmentation design; web-verified.",
 },
 {
  "id": "aci-policy-useg-attribute-microsegmentation",
  "domain": "aci-policy", "priority": "Medium", "engine_actionable": False,
  "title": "Reclassify endpoints below the base EPG with micro-EPGs (uSeg) by IP/MAC/VM-attribute, plus intra-EPG isolation -- knowing IP-uSeg only acts on ROUTED traffic",
  "design_intent": "When a base EPG (a VLAN/subnet of endpoints) is too coarse for the security posture, ACI carves "
    "a finer security group -- a micro-segmented EPG (uSeg/µEPG) -- by matching endpoint ATTRIBUTES (IP/MAC/VM-"
    "name/attribute) rather than where they plug in, without re-IP or re-VLAN. Two design facts: IP-based µEPG "
    "classification is a leaf ROUTING-path lookup, so same-Bridge-Domain same-subnet BRIDGED flows bypass it (make "
    "endpoints cross-subnet, or accept same-subnet pairs aren't enforced); and where overlapping attribute "
    "criteria can match one endpoint, set explicit match precedence for determinism. To stop east-west inside ONE "
    "group, use intra-EPG isolation (deny-all) rather than modelling per-endpoint EPGs.",
  "tradeoffs": "security granularity (attribute-based, location-independent, no re-IP) vs complexity + the routed-"
    "only/precedence gotchas; intra-EPG isolation vs per-endpoint EPG sprawl.",
  "trigger": "Designing fine-grained ACI segmentation beyond app-tier EPG/contract whitelisting.",
  "observable": "Not collected by an L1-L4 assessment; an ACI micro-seg design (beyond wave-1 whitelist).",
  "recommended_action": "Reserve plain EPG+contract whitelisting for app-tier/zone separation; escalate to a µEPG "
    "only where attribute-based classification is genuinely needed; for IP-µEPG ensure cross-subnet (routed) "
    "flows + enable unicast routing/SVI; set explicit attribute precedence; use intra-EPG isolation for same-role "
    "mutual isolation.",
  "alternatives": "Plain EPG/contract whitelisting (wave-1) for most cases; SGT/TrustSec micro-seg on a non-ACI "
    "campus/fabric.",
  "citation": "Cisco ACI micro-segmentation / uSeg-EPG design; web-verified.",
 },
 {
  "id": "aci-services-service-graph-device-modes-and-management",
  "domain": "aci-services", "priority": "Medium", "engine_actionable": False,
  "title": "Pick the service-graph device mode (GoTo routed / GoThrough transparent / one-arm) by the flow it enforces, and choose managed vs unmanaged by who owns L4-L7 config",
  "design_intent": "The service-graph function node's device MODE dictates fabric behaviour and constrains "
    "insertion: GoTo (routed/L3) needs unicast routing + the fabric to learn the device's far-side route (static/"
    "OSPF/iBGP) and is the prerequisite when PBR or route-peering is used; GoThrough (transparent/L2) is for "
    "bump-in-the-wire; one-arm pairs with PBR. Separately, decide up front whether APIC MANAGES the appliance "
    "(managed/service-policy mode, via a vendor device package that pushes FW/ADC config at graph instantiation) "
    "or only STITCHES the fabric (unmanaged/network-policy) -- default to unmanaged when a separate team/"
    "orchestrator owns the L4-L7 device or no maintained device package exists.",
  "tradeoffs": "correct insertion + single-pane control (right mode; managed) vs flexibility/ownership (unmanaged "
    "lets the security/LB team keep their tooling; managed needs a maintained device package).",
  "trigger": "Inserting an L4-L7 service via an ACI service graph.",
  "observable": "Not collected by an L1-L4 assessment; an ACI service-insertion design (depth beyond wave-1 PBR).",
  "recommended_action": "Use GoTo (routed) as the default + the prerequisite for PBR/route-peering (enable unicast "
    "routing, ensure the fabric knows the far-side subnet); GoThrough only for transparent bump-in-the-wire; "
    "default to unmanaged (network-policy) mode unless single-pane APIC control of the appliance is wanted AND a "
    "maintained device package exists.",
  "alternatives": "Managed (service-policy) mode for single-pane control where a device package is maintained; a "
    "copy service (not redirect) for passive IDS/analytics taps off the data path.",
  "citation": "Cisco ACI L4-L7 service-graph design (device modes, managed/unmanaged); web-verified.",
 },
 {
  "id": "aci-fabric-shared-services-inter-vrf-route-leaking-rules",
  "domain": "aci-fabric", "priority": "Low", "engine_actionable": False,
  "title": "Build ACI inter-VRF shared services to the leaking rules: provider subnet under the EPG, consumer under the BD, contract scope global, conserve class-IDs",
  "design_intent": "Inter-VRF (shared-services / shared-L3Out) communication in ACI is route-leaking driven by "
    "contracts, and its rules are non-obvious and easy to get wrong: to leak, a subnet must be flagged 'shared "
    "between VRFs', the provider subnet is defined under the EPG (not just the BD) while the consumer subnet sits "
    "under the BD, the contract scope must be Global, and overlapping subnets break leaking -- so per-EPG carvings "
    "must be non-overlapping. Designing to these rules (and conserving the finite global class-IDs that shared "
    "contracts consume) keeps a shared-services VRF maintainable.",
  "tradeoffs": "controlled cross-VRF shared services (DNS/AD/backup reachable from many tenant VRFs) vs the "
    "leaking-rule discipline + finite global class-ID budget.",
  "trigger": "Designing cross-VRF shared services / shared-L3Out on ACI.",
  "observable": "Not collected by an L1-L4 assessment; an ACI shared-services design (beyond wave-1).",
  "recommended_action": "Flag the provider subnet 'shared' under the EPG with non-overlapping per-EPG carvings; "
    "put the consumer subnet under the BD; set contract scope Global (or exported); keep leaked subnets non-"
    "overlapping; budget the global class-IDs shared contracts consume.",
  "alternatives": "A fusion router / external firewall for inter-VRF leaking at scale (the wave-1 inter-VRF-via-"
    "fusion pattern); keep services per-VRF where sharing isn't required.",
  "citation": "Cisco ACI shared-services / inter-VRF route-leaking design; web-verified.",
 },
 # ---- additive depth surfaced by the mega-wave synth's diff vs the live KB (6 net-new; 6 of its 12
 #      recommendations were dropped as already subsumed by the principles above) ----
 {
  "id": "campus-sda-fabric-roles-and-availability-placement",
  "domain": "campus-fabric", "priority": "Medium", "engine_actionable": False,
  "title": "Place SD-Access fabric roles (edge / border / control-plane / intermediate) by site size: separate for HA, collapse to Fabric-in-a-Box only for the smallest sites",
  "design_intent": "An SD-Access fabric site needs at least an edge node, a control-plane node and a border node. "
    "Edge nodes are the LISP xTRs where endpoints attach (the access layer); border nodes are the fabric's gateway "
    "to everything outside it; control-plane nodes hold the map-server/map-resolver. On medium/large or critical "
    "sites these roles must be distributed onto separate, redundant devices so no single box is edge + border + "
    "control-plane (a single failure then loses the whole site). Only the smallest sites should collapse the roles "
    "(Fabric-in-a-Box), accepting no redundancy.",
  "tradeoffs": "availability (separate, redundant roles survive a single device loss) vs cost/footprint (collapsed "
    "Fabric-in-a-Box is cheapest but a single point of failure).",
  "trigger": "Sizing the SD-Access fabric role placement for a site.",
  "observable": "Not collected by an L1-L4 assessment; an SD-Access design.",
  "recommended_action": "For medium/large/critical sites, distribute edge, border and control-plane onto separate "
    "(and redundant) devices; reserve Fabric-in-a-Box (collapsed roles) for small sites that accept no redundancy; "
    "use a stack/SVL where chassis redundancy at a collapsed role is wanted.",
  "alternatives": "Fabric-in-a-Box for the smallest sites; a redundant control-plane-node pair + dual borders for "
    "the largest, with edges scaled horizontally.",
  "citation": "Cisco SD-Access Design Guide (fabric roles, Fabric-in-a-Box, HA placement); web-verified.",
 },
 {
  "id": "campus-sda-multisite-sdaccess-transit-vs-ip-transit",
  "domain": "campus-fabric", "priority": "High", "engine_actionable": False,
  "title": "For multi-site SD-Access, prefer SD-Access transit to keep VN+SGT intact end-to-end; use IP transit only to hand off to a non-fabric WAN",
  "design_intent": "Connecting fabric sites is a transit choice. SD-Access transit carries traffic between sites "
    "natively in LISP/VXLAN through a dedicated transit control-plane node (which has no edge/border of its own), "
    "so the Virtual Network AND the SGT stay intact end-to-end and multi-exit/HA is native -- the policy follows "
    "the packet across sites. IP transit instead hands off at the border to a regular routed WAN (MPLS/SD-WAN/"
    "Internet), which means the VN must be re-mapped (VRF-lite/option-A) and the SGT must be re-carried "
    "(SXP/inline) or it is lost at the boundary.",
  "tradeoffs": "policy continuity + simplicity (SD-Access transit keeps VN+SGT) vs transport flexibility (IP "
    "transit rides any WAN but loses native VN/SGT continuity and needs re-mapping).",
  "trigger": "Interconnecting two or more SD-Access fabric sites.",
  "observable": "Not collected by an L1-L4 assessment; a multi-site SD-Access design.",
  "recommended_action": "Where the inter-site path can carry LISP/VXLAN and meet RTT/MTU, use SD-Access transit "
    "(dedicated transit control-plane node, no edge/border) so VN + SGT stay intact end-to-end; use IP transit "
    "when you must hand off to a non-fabric WAN, and then explicitly re-map the VN (VRF-lite) and re-carry the SGT "
    "(SXP/inline tagging) across the boundary.",
  "alternatives": "IP transit (border hand-off to MPLS/SD-WAN) where the WAN can't carry VXLAN or fabric doesn't "
    "extend; a single large fabric where sites are close enough to be one fabric.",
  "citation": "Cisco SD-Access multi-site design (SD-Access transit vs IP transit); web-verified.",
 },
 {
  "id": "aci-fabric-l3out-route-control-import-export-asymmetry",
  "domain": "aci-fabric", "priority": "Medium", "engine_actionable": False,
  "title": "Design ACI L3Out route-control around its default asymmetry: inbound import is permit-all (tighten on BGP only), outbound export is deny-all and exact-mask",
  "design_intent": "ACI L3Out route filtering is deliberately ASYMMETRIC and must be designed to, not assumed. "
    "INBOUND: import route-control is DISABLED by default -- a 'permit-all' admits every external prefix into "
    "MP-BGP, and it can be tightened (enumerate permitted prefixes) only on a BGP L3Out. OUTBOUND: export is "
    "DENY-ALL by default -- nothing is advertised until you explicitly add each BD/transit subnet, and matches are "
    "exact-mask only (no implicit longest-prefix). Getting this backwards leaks every external prefix inbound or "
    "silently advertises nothing outbound.",
  "tradeoffs": "control + safety (explicit per-prefix export, tightened BGP import) vs the configuration discipline "
    "(enumerate every advertised subnet; remember import is open by default on non-BGP L3Outs).",
  "trigger": "Designing route advertisement/admission on an ACI L3Out.",
  "observable": "Not collected by an L1-L4 assessment; an ACI L3Out design (depth beyond the wave-1 L3Out principles).",
  "recommended_action": "Enable import route-control only on BGP L3Outs and enumerate every permitted inbound "
    "prefix; rely on the export deny-all default and explicitly add each BD/transit subnet to be advertised "
    "(exact-mask); document the L3Out route policy rather than assuming a symmetric filter.",
  "alternatives": "Leave import permit-all only where the external peer is fully trusted and prefix-bounded; use a "
    "dedicated L3Out per route-policy domain (the wave-1 granularity principle).",
  "citation": "Cisco ACI L3Out route-control design (import permit-all / export deny-all asymmetry); web-verified.",
 },
 {
  "id": "aci-fabric-overlay-to-vswitch-confines-vlan-sprawl",
  "domain": "aci-fabric", "priority": "Medium", "engine_actionable": False,
  "title": "Run the EPG overlay from the ACI leaf to the virtual switch so an intermediate L2 / blade fabric-interconnect carries only the infra VLAN, not per-EPG VLAN sprawl",
  "design_intent": "When workloads sit behind an intermediate Layer-2 network -- a blade-chassis fabric-"
    "interconnect estate, or a legacy Nexus L2 cloud between the ACI leaf and the host -- you can either trunk "
    "every per-EPG VLAN across that intermediate fabric (VLAN sprawl, a scaling + management burden, and the "
    "intermediate gear must learn every EPG VLAN) or extend the EPG overlay (VXLAN) all the way to the virtual "
    "switch so the intermediate fabric and the FI carry only the single infra VLAN. The latter confines VLAN "
    "sprawl and keeps the policy edge at the vSwitch.",
  "tradeoffs": "scalability + manageability (intermediate gear carries one infra VLAN, not N EPG VLANs) vs "
    "requiring a VMM/AVE-style overlay-to-vSwitch integration through the intermediate fabric.",
  "trigger": "Designing ACI attachment where an unmanaged intermediate L2 / blade FI sits between leaf and host.",
  "observable": "Not collected by an L1-L4 assessment; an ACI attachment design.",
  "recommended_action": "Where an intermediate L2 / blade-FI sits between the ACI leaf and virtualized hosts, "
    "extend the EPG overlay (VXLAN) to the virtual switch so the intermediate fabric and FI carry only the infra "
    "VLAN, rather than trunking every per-EPG VLAN across it.",
  "alternatives": "Trunk per-EPG VLANs across the intermediate fabric where the EPG count is small and overlay-to-"
    "vSwitch integration is unavailable; collapse the intermediate L2 by attaching hosts directly to the leaf.",
  "citation": "Cisco ACI virtualization / blade-FI integration design; web-verified.",
 },
 {
  "id": "aci-services-pbr-redirect-bd-and-dataplane-learning-discipline",
  "domain": "aci-services", "priority": "Medium", "engine_actionable": False,
  "title": "Give a PBR service node its own routed BD and disable remote-leaf source-VTEP learning to stop endpoint flapping",
  "design_intent": "ACI Policy-Based Redirect rewrites the destination MAC to the service node's VMAC while "
    "keeping the real source/destination IPs -- which makes the same endpoint IP appear behind multiple leaves and "
    "causes endpoint flapping unless data-plane learning is handled. The discipline: allocate a dedicated routed "
    "service BD per PBR node, disable remote-leaf source-VTEP learning on it (both directions if the return is "
    "also redirected), register the node IP+VMAC in the redirect policy, and meet the platform's PBR requirements "
    "-- so the redirect is stable and does not corrupt the endpoint table.",
  "tradeoffs": "correctness/stability (no endpoint flapping; clean redirect) vs the configuration discipline "
    "(dedicated redirect BD + learning-disable per node, both directions for symmetric redirect).",
  "trigger": "Inserting a service node via PBR redirect on an ACI fabric.",
  "observable": "Not collected by an L1-L4 assessment; an ACI service-insertion design (depth beyond the wave-1 "
    "service-graph principle).",
  "recommended_action": "Allocate a dedicated routed service BD per PBR node, disable remote-leaf source-VTEP "
    "learning on it (both directions if return is redirected), register the node IP+VMAC in the redirect policy, "
    "and confirm the leaf platform supports the redirect; validate the endpoint table stays stable after insertion.",
  "alternatives": "Inline/routed service insertion (service as a routed hop) where PBR's data-plane-learning "
    "subtleties are unwanted; a copy service for passive taps off the data path.",
  "citation": "Cisco ACI PBR service-graph design (redirect BD, data-plane learning); web-verified.",
 },
 {
  "id": "wireless-capwap-control-data-split-latency-budget",
  "domain": "wireless", "priority": "Medium", "engine_actionable": False,
  "title": "Treat CAPWAP as a split control/data plane with a hard AP-to-WLC latency budget and a mandatory DTLS control channel",
  "design_intent": "Lightweight APs reach the WLC over CAPWAP, which is deliberately two planes: a DTLS-encrypted "
    "CONTROL channel (UDP 5246, mandatory) for join/config/RRM/mobility, and a DATA channel (UDP 5247, DTLS "
    "optional) that in local-mode tunnels every client frame back to the WLC. Because control is real-time and "
    "centralized, AP-to-WLC RTT has a hard budget (Cisco's ~300ms limit; aim < ~100ms for centralized designs) "
    "and the control channel should be priority-queued across the path -- exceed the budget and APs disjoin/flap. "
    "(This is also why high-latency branches favour FlexConnect local-switching -- see the WLC-deployment principle.)",
  "tradeoffs": "central control + policy (CAPWAP tunneling) vs the WAN latency budget + WLC/uplink sizing for "
    "aggregate tunneled data (local-mode hairpins all client data to the WLC).",
  "trigger": "Designing AP-to-WLC connectivity / WAN paths for centralized wireless.",
  "observable": "Not collected by an L1-L4 assessment; a wireless transport design.",
  "recommended_action": "Keep AP-to-WLC RTT inside ~300ms (aim < ~100ms for centralized); priority-queue CAPWAP "
    "control (UDP 5246) across the path; size the WLC + its uplink for the aggregate local-mode data tunnel; move "
    "high-latency/unreliable branches to FlexConnect local-switching rather than stretching CAPWAP.",
  "alternatives": "FlexConnect local-switching (data drops locally, control over CAPWAP) for high-latency branches; "
    "cloud-managed (Meraki) where a controller-less model is preferred.",
  "citation": "Cisco CAPWAP / Catalyst 9800 design (control UDP 5246 DTLS, data 5247, RTT budget); web-verified.",
 },
]
DOCTRINE.extend(_MEGA_CORPUS_ADDENDUM)


# ---------------------------------------------------------------------------- actionable-detector addendum
# Unlike the mined-doctrine addenda above (engine_actionable=False -- reference knowledge the chat/HLD can
# cite but the advisor cannot auto-detect), EVERY principle here is engine_actionable=True: each is wired to a
# NEW firing detector in design_advisor.py that reads collected-but-previously-unused snapshot evidence and
# emits a traceable target-state DESIGN decision. They were surfaced by the 2026-06 multi-domain mining wave,
# python-measured on the canonical [HISTORY-REDACTED] snapshot, and adversarially refutation-gated. The emit-invariant
# (tests/test_design_blueprint.py::test_every_engine_actionable_principle_is_emitted) and the per-detector
# honesty tests (tests/test_design_addenda.py) lock that each fires on real evidence and returns None on clean.
_ACTIONABLE_DETECTOR_ADDENDUM = [
    {
        "id": "addressing-one-vlan-one-subnet-integrity",
        "domain": "dc-switching", "priority": "High", "engine_actionable": True,
        "title": "Bind each VLAN to exactly one IP subnet (one-VLAN-one-subnet integrity) before any L2 merge or collapse",
        "design_intent": "A broadcast domain (VLAN) and an IP subnet are meant to be 1:1. When the same VLAN id "
            "carries two or more distinct subnets across different gateway switches, the L2 domain has conflicting "
            "L3 identities: hosts in one subnet ARP for a gateway that another switch answers for a different "
            "subnet, and any target that merges or stretches that VLAN forwards non-deterministically. Reconcile "
            "each VLAN to a single subnet (renumber the minority, or split the VLAN) before the migration touches it.",
        "tradeoffs": "Addressing integrity and a deterministic merge vs the renumber/re-IP effort on the minority "
            "subnet and its endpoints. A silent collision at cutover is far costlier than the planned renumber.",
        "trigger": "One VLAN id mapped to >=2 distinct subnets across >=2 gateways, or a subnet that strictly "
            "contains another on the same VLAN (a /22 over a /24) -- a silent black-hole at the mask boundary.",
        "observable": "Directly observable. subnet_intelligence.per_device[].served_subnets[] gives the "
            "VLAN->subnet->gateway binding first-hand; l3_forwarding[].primary_subnet corroborates and supplies "
            "the containment/mask-mismatch arm (excluding /30+ point-to-point links). Scoped to collected gateways.",
        "recommended_action": "For each offending VLAN, choose the authoritative subnet and renumber the others "
            "(or split the VLAN per subnet); resolve any containment/mask mismatch so no subnet contains another on "
            "the same VLAN; verify one-VLAN-one-subnet before merging or stretching the domain in the target.",
        "alternatives": "Keep the VLANs separate in the target (no merge) where a renumber is infeasible; or route "
            "between the two subnets rather than bridging them into one L2 domain.",
        "citation": "Cisco campus/DC L2-L3 design (VLAN<->subnet 1:1, SVI per subnet); RFC 950/1812 subnetting; web-verified.",
    },
    {
        "id": "dc-stp-root-determinism",
        "domain": "dc-switching", "priority": "High", "engine_actionable": True,
        "title": "Engineer an explicit STP root priority on every active VLAN -- never let the root be elected by the MAC tiebreak",
        "design_intent": "Spanning tree breaks priority ties on the lowest bridge MAC address. A switch left at the "
            "default bridge priority (32768) that wins the root role did so accidentally -- on a MAC tiebreak, not by "
            "design -- so the root is wherever the oldest/lowest-MAC switch happens to sit, not at the distribution/"
            "aggregation where the active gateway lives. At migration a newly-introduced switch with a lower MAC can "
            "silently steal the root, moving the L2 topology and the traffic path under you. Set the root explicitly.",
        "tradeoffs": "Deterministic, gateway-aligned L2 forwarding and a safe cutover vs a one-time priority-"
            "engineering pass across the VLANs (and keeping primary/secondary aligned with the FHRP active).",
        "trigger": "A switch is the STP root for a VLAN while still at the default bridge priority (root_priority == "
            "32768 + VLAN id) -- i.e. it won on the MAC tiebreak; or the root is not co-located with the active gateway.",
        "observable": "Directly observable. stp_roots[host][vlan].{is_root, root_priority} gives the elected root and "
            "its priority per VLAN; the same evidence analyze.stp_root_findings feeds to the punch-list/workbook.",
        "recommended_action": "Configure 'spanning-tree vlan X root primary' on the intended root (priority 24576) and "
            "'root secondary' (28672) on its peer, co-located with the active FHRP gateway, for every production VLAN; "
            "re-verify after introducing any new switch in the migration.",
        "alternatives": "Move to MST and engineer the per-instance root; or a routed-access / spine-leaf target where "
            "STP root placement stops being the failover mechanism.",
        "citation": "Cisco STP design (default bridge priority 32768, lowest-MAC tiebreak, explicit root primary/secondary); web-verified.",
    },
    {
        "id": "addressing-reserved-vlan-range-hygiene",
        "domain": "dc-switching", "priority": "High", "engine_actionable": True,
        "title": "Keep production SVIs out of the platform-reserved VLAN range (e.g. 3968-4095 on Nexus) before migrating to that platform",
        "design_intent": "Nexus / NX-OS reserves VLANs 3968-4095 for internal device use by default and will not let "
            "you configure an SVI or user data there unless the reserved block is first moved ('system vlan reserve') "
            "and the device reloaded. A legacy platform that tolerated an SVI on, say, VLAN 4094 will migrate that "
            "config to a target Nexus that silently refuses it -- the L3 interface never comes up and the link "
            "black-holes at cutover. Renumber any reserved-range SVI into the normal user range as part of the design.",
        "tradeoffs": "A clean, portable addressing plan vs renumbering the affected (usually infrastructure /30) links "
            "and updating both ends + any routing that references them.",
        "trigger": "An L3 SVI (svi_ip present) configured on a VLAN id in the platform-reserved range (3968-4095 for "
            "Nexus; also the legacy 1002-1005) on a fleet migrating to that platform.",
        "observable": "Directly observable. l3_forwarding[].vlan + l3_forwarding[].svi_ip expose the SVI's VLAN id.",
        "recommended_action": "Renumber each reserved-range SVI into the user VLAN range (1-3967) on both ends before "
            "cutover; if the reserved block genuinely must move on the target, schedule the 'system vlan reserve' "
            "change + reload in the MOP and validate the SVI comes up.",
        "alternatives": "Keep the link on a routed (no-SVI) sub-interface or physical L3 port that is not subject to the "
            "VLAN-id reservation.",
        "citation": "Cisco Nexus 9000 NX-OS Layer-2 Switching Config Guide (VLANs 3968-4095 reserved for internal use); web-verified.",
    },
    {
        "id": "dc-lacp-over-static-etherchannel",
        "domain": "dc-switching", "priority": "High", "engine_actionable": True,
        "title": "Negotiate multi-member EtherChannels with LACP, not static 'mode on'",
        "design_intent": "A static ('channel-group ... mode on') EtherChannel bundles its members with no negotiation: "
            "there is no LACP exchange to confirm the far end agrees, the speeds/duplex match, and the link is "
            "bidirectional. A miscabled, one-way, or mismatched member is admitted into the bundle anyway and silently "
            "black-holes its share of the load-balance hash -- an Up-but-broken fault that 'show' does not flag. LACP "
            "(mode active) detects exactly these and suspends the bad member instead of forwarding into a hole.",
        "tradeoffs": "Member-level health/miscabling detection and safe bundle formation (LACP) vs a small amount of "
            "control traffic and the requirement that both ends speak LACP (true for all modern Cisco platforms).",
        "trigger": "A multi-member (>=2 physical) port-channel whose members are all static 'mode on' "
            "(port_channel_protocol == ON), excluding FEX fabric/HIF links where mode-on is by design.",
        "observable": "Directly observable. interfaces[host][port].port_channel groups the members and "
            "interfaces[host][port].port_channel_protocol exposes ON vs LACP/PAgP; FEX-HIF ports are excluded.",
        "recommended_action": "Convert each static bundle to LACP (channel-group N mode active on both ends), confirm "
            "all members reach 'bundled' (P) state, and leave a single member's failure to suspend rather than blackhole.",
        "alternatives": "Where a peer genuinely cannot run LACP, keep mode-on but add explicit member-up monitoring; "
            "FEX HIFs legitimately stay mode-on (the parent negotiates).",
        "citation": "Cisco EtherChannel/LACP design (LACP detects miscabling/one-way members that static mode-on admits); web-verified.",
    },
    {
        "id": "dc-power-supply-redundancy",
        "domain": "dc-switching", "priority": "High", "engine_actionable": True,
        "title": "Restore N+1 power-supply redundancy before a multi-PSU chassis is silently single-corded",
        "design_intent": "A chassis fitted with more than one power supply is meant to survive the loss of one. When it "
            "reports a FAILED supply, that redundancy is already gone -- it is running on the remaining feed and the "
            "next power event (a tripped breaker, a pulled cord, a grid blip) is a full-chassis outage. On a keystone "
            "distribution/core node that strands hundreds of endpoints, the failed PSU is the single further event "
            "between 'healthy' and a major outage. Replace the supply (and dual-feed/dual-grid the keystones) first.",
        "tradeoffs": "Restored N+1 (or 2N) power resilience vs the cost of the replacement supply and a dual-feed "
            "circuit; trivially justified on any aggregation node whose loss strands a closet or a rack.",
        "trigger": "A device with more than one power supply (num_power_supplies > 1) reporting a failed supply "
            "(ps_status containing 'fail') -- redundancy lost, now single-corded.",
        "observable": "Directly observable. devices[host].ps_status (a '/'-joined per-PSU status list) and "
            "devices[host].num_power_supplies. Single-PSU-by-design boxes (num==1) are excluded.",
        "recommended_action": "Replace the failed supply to restore N+1; on distribution/core keystones move to dual "
            "supplies on independent feeds/grids (2N) and alarm on PSU state; verify both supplies 'OK' before cutover.",
        "alternatives": "Where the chassis is being replaced anyway, ensure the replacement ships with dual supplies "
            "and dual feeds rather than repairing the outgoing unit.",
        "citation": "Cisco DC platform power design + leading-practice N+1/2N PSU redundancy on aggregation/core; web-verified.",
    },
    {
        "id": "migration-gateway-cutover-order",
        "domain": "scenario-pattern", "priority": "Medium", "engine_actionable": True,
        "title": "Move the default gateway (SVI) LAST for any subnet whose endpoints straddle multiple switches",
        "design_intent": "When a subnet's endpoints sit on more than one switch, you cannot move them all in one "
            "instant. As long as ANY workload of that subnet remains on the legacy side, the legacy default gateway "
            "must stay live and the target broadcast domain must keep flooding/anycast ready -- so the gateway (SVI) "
            "is the LAST thing to move, after the workloads, not the first. Cut the gateway early and every endpoint "
            "still trailing on the old side loses its first hop mid-migration. This sequences the move-group plan.",
        "tradeoffs": "A safe, reversible per-subnet cutover (gateway-move-last, build-before-break) vs a longer window "
            "where the subnet's L3 is split across legacy and target and must be kept consistent on both.",
        "trigger": "A gateway SVI whose subnet has evidenced endpoints across >=2 switches -- a move-order constraint "
            "(the SVI cannot move until its trailing endpoints have).",
        "observable": "Directly observable. l3_forwarding[].{vlan, svi_ip} gives the gateways; endpoint_identity[]."
            "{vlan, host} gives which switches still hold each subnet's endpoints (the count that must reach zero first).",
        "recommended_action": "In each move-group, schedule the SVI/default-gateway move as the final step for every "
            "straddling subnet; keep the legacy gateway active and the target BD flooding (ARP/unknown-unicast) on with "
            "unicast routing off until all workloads are across; only then move the gateway and enable routing.",
        "alternatives": "Move the whole subnet in a single wave where it fits one switch/move-group (no straddle, no "
            "ordering constraint); or use an anycast/distributed gateway so the gateway exists on both sides during the cut.",
        "citation": "Cisco 'Migrating Existing Networks to ACI' (BD flood on / unicast-routing off until workloads move; gateway last); web-verified.",
    },
    {
        "id": "dc-size-l2-subnet-to-endpoint-count",
        "domain": "dc-switching", "priority": "Medium", "engine_actionable": True,
        "title": "Size each VLAN's subnet to its endpoint count -- a VLAN with >254 endpoints cannot live in a /24",
        "design_intent": "A /24 holds at most 254 usable host addresses. A VLAN already carrying more evidenced "
            "endpoints than that physically cannot be a single /24 in the target -- it needs a larger prefix (/23, /22) "
            "or, better for the failure domain, to be split into multiple smaller broadcast domains. This is a sizing "
            "REALITY visible from the current endpoint census, independent of any supplied address-space requirement, "
            "so it should be surfaced up front rather than discovered when the allocator runs out of addresses.",
        "tradeoffs": "A subnet sized to its hosts (no overflow) vs either a larger broadcast/failure domain (one big "
            "prefix) or the segmentation effort of splitting the VLAN. Splitting shrinks the fault domain; one big "
            "prefix is simpler but bridges more hosts into one storm radius.",
        "trigger": "A VLAN (id != 1) whose evidenced endpoint count exceeds 254 -- it overflows a single /24.",
        "observable": "Directly observable. endpoint_identity[].{vlan, host} gives the evidenced endpoint count per "
            "VLAN; the access-port census corroborates. Independent of the requirement-gated address allocator.",
        "recommended_action": "Size each oversized VLAN's target prefix to its endpoint count plus headroom (/23 or "
            "/22), or split the broadcast domain into multiple VLANs/subnets to bound the failure domain; reflect the "
            "choice in the addressing plan.",
        "alternatives": "Keep one large prefix where L2 adjacency across the whole population is genuinely required "
            "(accepting the larger storm radius); otherwise prefer splitting.",
        "citation": "IPv4 subnetting (/24 = 254 usable hosts) + Cisco fault-domain sizing (bound the broadcast domain); web-verified.",
    },
    {
        # NET-NEW engine_actionable principle: build_pim + _d_pim_rp_health FIRE on a PIM sparse-mode device
        # that is running (live neighbor) but has learned no RP and is not SSM-only.
        "id": "multicast-pim-rp-resilience",
        "domain": "multicast", "priority": "High", "engine_actionable": True,
        "title": "Keep a reachable rendezvous point (RP) for every running PIM sparse-mode domain (or move groups to SSM)",
        "design_intent": "PIM sparse-mode builds ASM (*,G) shared trees rooted at a rendezvous point. If sparse-mode is "
            "running (a live PIM neighbor) but no RP is learned, the shared tree can never form and multicast forwarding "
            "is broken (RFC 7761) -- a silent fault that a cutover baseline would carry forward. SSM (232.0.0.0/8) needs "
            "no RP, so an SSM-only domain is healthy without one.",
        "tradeoffs": "RP availability (redundant/anycast RP, Auto-RP or BSR election) and the operational discipline to "
            "keep it reachable, vs the simplicity of SSM where the application supports source-specific joins.",
        "trigger": "snap['pim'] shows a device with >=1 live PIM neighbor AND a collected 'show ip pim rp mapping' that "
            "learned ZERO RPs AND the domain is not SSM-only.",
        "observable": "Directly observable. build_pim parses 'show ip pim rp mapping' (learned-RP summary, with a "
            "'present' flag so 'not collected' is never read as 'no RP') and 'show ip pim neighbor' (proof sparse-mode is "
            "live); _d_pim_rp_health fires only on running + collected + zero-RP + not-SSM-only.",
        "recommended_action": "Restore RP reachability/election (static RP with anycast-RP redundancy, Auto-RP, or BSR), "
            "verify each running PIM device learns the RP, or migrate the affected groups to SSM; re-verify before the "
            "cutover baseline.",
        "alternatives": "Migrate to SSM (no RP needed) where the application supports source-specific joins; or run "
            "anycast-RP / phantom-RP for RP redundancy.",
        "citation": "RFC 7761 (PIM-SM); Cisco PIM RP configuration & verification (Auto-RP / BSR / static / anycast-RP); web-verified.",
    },
    {
        # GRADUATED from reference doctrine to engine_actionable: build_ipv6_fhs + _d_ipv6_fhs now FIRE this on
        # observed dual-stack access switches missing RA-Guard (moved out of _MEGA_CORPUS_ADDENDUM).
        "id": "ipv6-first-hop-security-suite-at-access-edge",
        "domain": "ipv6", "priority": "High", "engine_actionable": True,
        "title": "Enable the full IPv6 first-hop security suite at the access edge -- RA-Guard, DHCPv6-Guard, ND inspection/device-tracking, IPv6 Source Guard",
        "design_intent": "IPv6 Neighbor Discovery (RFC 4861) is as trust-on-the-wire as IPv4 ARP: a single rogue or "
            "fat-fingered Router Advertisement can hijack the default gateway for a whole segment, and spoofed ND/DHCPv6 "
            "enables MITM and address theft. First-hop security is the L2-edge countermeasure suite -- and absent it, an "
            "IPv6 deployment is wide open at the access layer (RFC 6104).",
        "tradeoffs": "security (gateway-hijack / ND-spoof / address-theft prevention) vs the access-port configuration "
            "discipline (mark only real router/server uplinks trusted) and platform feature support.",
        "trigger": "A switch that is OBSERVABLY dual-stack (>=1 IPv6-addressed SVI) and owns host-facing access ports "
            "but applies NO RA-Guard anywhere (no global policy on a port/VLAN, no interface 'ipv6 nd raguard').",
        "observable": "Directly observable. build_ipv6_fhs fuses 'show ipv6 nd raguard policy' / 'show ipv6 dhcp guard "
            "policy' with the running-config (IPv6 SVIs + per-interface attach); _d_ipv6_fhs fires only on a live "
            "dual-stack access switch with no RA-Guard (a pure-IPv4 switch or an already-guarded switch stays silent).",
        "recommended_action": "On every host-facing access port enable RA-Guard + DHCPv6-Guard (only real uplinks "
            "trusted), enable IPv6 ND inspection / device-tracking to build the binding table, then layer IPv6 Source "
            "Guard off that table; apply even on IPv4-only segments where hosts are IPv6-capable (block rogue RAs).",
        "alternatives": "Disable IPv6 on truly IPv6-free access (rarely clean -- hosts often still process RAs); SEND "
            "(cryptographic ND) where supported and required.",
        "citation": "Cisco IPv6 First-Hop Security (RA-Guard, DHCPv6-Guard, ND inspection, Source Guard); RFC 6104; web-verified.",
    },
    {
        # NET-NEW engine_actionable principle: build_undocumented_neighbors + _d_shadow_infra reconcile collected
        # CDP/LLDP infra neighbours against the assessed inventory and FIRE on any undocumented switch/router.
        "id": "discover-undocumented-infrastructure-before-cutover",
        "domain": "operations", "priority": "High", "engine_actionable": True,
        "title": "Discover and inventory undocumented (shadow) infrastructure before baselining the design",
        "design_intent": "CDP/LLDP discovery is the cross-check that the device inventory is COMPLETE; an infra "
            "neighbour (switch/router) absent from the inventory is undocumented 'shadow' infrastructure carrying "
            "production traffic outside the migration scope -- its uplinks, redundancy, software and end-of-support "
            "state are all unknown, and a cutover wave that depends on it can break silently.",
        "tradeoffs": "Chasing every neighbour costs discovery time, but it is the only way the inventory -- and the "
            "hardening/lifecycle/cutover plans built on it -- is provably complete rather than silently partial.",
        "trigger": "snap['shadow_infra'] is non-empty: an infra-capable CDP/LLDP neighbour whose canonical hostname is "
            "not an assessed device (collected OR inventoried). Edge devices (phones / APs / hosts) are excluded by "
            "capability so they never trigger it.",
        "observable": "Directly observable. parse_neighbors_detail keeps the CDP/LLDP capability codes the topology-link "
            "parsers discard; _neighbor_is_infra filters to switches/routers; _d_shadow_infra reconciles by canonical "
            "hostname exactly like the topology map, so an in-scope neighbour advertised by its FQDN is not mis-flagged.",
        "recommended_action": "Identify each shadow node from the advertising device+port and its CDP/LLDP platform/mgmt "
            "IP, then add it to the inventory and collect it (or formally scope it out WITH the customer and record it). "
            "Re-run discovery until every infra neighbour reconciles, then freeze the baseline.",
        "alternatives": "Proceed on the partial inventory and discover the device during cutover (cheapest now, but the "
            "wave starts blind to a live dependency).",
        "citation": "Cisco Discovery Protocol (CDP) + IEEE 802.1AB LLDP capability codes (Switch/Router vs Trans-Bridge/"
            "Host/Phone); Cisco PPDIOO Prepare/Plan network-discovery & inventory-completeness practice.",
    },
]
DOCTRINE.extend(_ACTIONABLE_DETECTOR_ADDENDUM)


# ---------------------------------------------------------------------------- media-fabric (broadcast) addendum
# A single doctrine principle for broadcast media-over-IP (SMPTE ST 2110) timing. engine_actionable=False: the
# full PTP profile/domain is a media-design detail the L1-L4 assessment does not collect, but the
# multicast_intelligence.ptp axis DOES observe PTP-capable switches + grandmaster state, so compute_target_state
# surfaces this as a 'Media / timing fabric' TARGET-STATE DIMENSION (not a firing decision). Relevant to the [HISTORY-REDACTED]
# ([HISTORY-REDACTED]) broadcast estate; cited as a dimension driver. Web-verified (SMPTE ST 2059-2 / ST 2110-10).
_MEDIA_FABRIC_ADDENDUM = [
    {
        "id": "multicast-media-fabric-ptp-timing",
        "domain": "multicast", "priority": "High", "engine_actionable": False,
        "title": "Give a broadcast (ST 2110) media fabric a resilient PTP timing plane: SMPTE ST 2059-2, boundary clocks, redundant grandmasters",
        "design_intent": "Professional media-over-IP (SMPTE ST 2110) carries uncompressed video/audio as multicast "
            "essence flows that are usable only if every endpoint shares a common, sub-microsecond time reference -- "
            "delivered by PTP (IEEE 1588) under the SMPTE ST 2059-2 broadcast profile. The timing plane must be "
            "engineered, not assumed: run a boundary clock on every switch in the media path (each locks to the "
            "grandmaster and re-serves downstream, which scales far better than one flat PTP domain), lock those to a "
            "REDUNDANT grandmaster pair (>=2, for seamless BMCA failover), and keep the whole media plane in a "
            "dedicated VRF/zone with IGMPv3/SSM rather than on the flat L3. PTP-capable switches sitting dormant with "
            "no operational grandmaster mean the media fabric has no timing reference at all: the essence flows are "
            "unprotected and a clock event corrupts them silently.",
        "tradeoffs": "Deterministic sub-microsecond media timing + resilience (boundary clocks + redundant GMs) vs "
            "the cost of GNSS-locked grandmasters, PTP-aware switches and a separate media VRF/zone; a boundary clock "
            "per hop vs a simpler but unscalable and fragile single flat PTP domain.",
        "trigger": "A broadcast/media estate carrying ST 2110 (or AES67/Dante audio) AV multicast groups and "
            "PTP-capable switches -- especially where the PTP clocks are dormant or there is no operational, "
            "redundant grandmaster.",
        "observable": "Partially observable from an L1-L4 assessment: multicast_intelligence.ptp enumerates the "
            "PTP-capable switches and whether any operational clock/grandmaster is seen, and the AV multicast group "
            "census shows the media plane; the full PTP profile/domain config is a media-design detail not collected.",
        "recommended_action": "Deploy >=2 GNSS-locked grandmasters (redundant, ST 2059-2 profile); enable boundary "
            "clock on every media-path switch; place the media plane in a dedicated VRF/zone with IGMPv3/SSM; verify "
            "all clocks lock and converge inside the ~1 microsecond accuracy budget.",
        "alternatives": "A single flat PTP domain (simpler, unscalable, no per-hop correction) for a very small media "
            "island; external/black-burst legacy sync where ST 2110 is not yet adopted.",
        "citation": "SMPTE ST 2059-2 (PTP broadcast profile) + ST 2110-10 timing; boundary-clock + redundant-"
            "grandmaster leading practice (The Broadcast Bridge / KeyCode Media / Leader-Phabrix); web-verified.",
    },
]
DOCTRINE.extend(_MEDIA_FABRIC_ADDENDUM)


# --- mega-wave gap-filling doctrine (2026-06-21): 55 net-new REFERENCE principles for KB-thin/
# absent design domains (optical-transport / storage-fabric / ddi-ipam / observability are brand-
# new; EVPN / SP-L2VPN / SP-MVPN / cloud / ACI-multisite & -services enriched). ALL
# engine_actionable=False -- the L1-L4 assessment collects no live state for these, so they inform
# the HLD/design-chat narrative, never an auto-emitted decision. Curated + de-duplicated (absent/
# thin domains only) from a 161-agent multi-domain mining wave; full mined set kept outside the repo.
_WAVE2_GAP_ADDENDUM = json.loads('[{"id": "aci-services-build-a-multi-node-pbr-service-chain", "domain": "aci-services", "title": "Build a multi-node PBR service chain as an ORDERED function list, and govern node failure with the threshold down-action (permit / deny / bypass)", "priority": "Medium", "design_intent": "When inserting more than one L4-L7 function (e.g. firewall then load-balancer), model the service graph as an ordered multi-node chain (up to five function nodes), enabling redirect independently per service-node connector and per direction so each hop terminates on the intended appliance. Decide up front what the WHOLE chain does when a node\'s health-tracking drops it below the threshold: \'deny\' drops the flow (fail-closed, for a mandatory security node), \'permit\' bypasses the entire chain and sends traffic direct (fail-open), and \'bypass\' (multi-node only) lets traffic continue through the remaining up / non-bypassable nodes of the chain instead of failing the whole insertion. The down-action is a deliberate availability-vs-security choice per node, not a default.", "recommended_action": "In the target HLD, render each L4-L7 insertion as an explicit ordered node list with a per-node threshold down-action rationale (security nodes fail-closed/deny; optional optimization nodes bypass or permit), and require IP-SLA tracking on every PBR destination so the down-action can actually fire.", "citation": "Cisco APIC Layer 4 to Layer 7 Services Deployment Guide, Configuring Policy-Based Redirect (multi-node PBR up to 5 function nodes; Threshold Down Action deny/permit/bypass, bypass added APIC 4.1(2)); Cisco ACI PBR Service Graph Design White Paper (c11-739971)", "engine_actionable": false}, {"id": "aci-multisite-organize-ndo-schemas-templates-by-object-scope", "domain": "aci-multisite", "title": "Organize NDO schemas/templates by object scope (site-local vs stretched) with one owning template per object, not one schema per fabric", "priority": "Medium", "design_intent": "When ACI Multi-Site is the target, the Nexus Dashboard Orchestrator schema/template layout is a first-class design decision, separate from the physical Multi-Pod/Multi-Site transport choice. Lay out templates by the SCOPE of the policy: put genuinely cross-site (stretched) VRFs/BDs/EPGs/contracts in a multi-site template associated to several fabrics, and keep site-local policy in templates associated only to the fabric that should receive it -- so a site-local change can never accidentally stretch an object or program shadow objects on a fabric that does not need it. Separate the networking constructs (VRF/BD) from the application-policy constructs (EPG/contract/AP) into distinct templates/schemas that cross-reference, and group all of a tenant\'s application templates inside one schema for operability, splitting across additional schemas only to stay under the verified per-schema scale limits. Every managed object should have exactly ONE owning template (one source of truth); on brownfield import, decide deliberately per object whether NDO or the local APIC remains the authority and avoid editing the same object from both, because dual management drifts the intent.", "recommended_action": "If the target architecture is ACI Multi-Site (or a mixed estate orchestrated by NDO), require the HLD to specify the schema/template organization explicitly: which objects are stretched vs site-local, the networking-vs-application template split, per-tenant schema grouping against the release\'s Verified Scalability limits, and a single owning template per object with a stated NDO-vs-APIC authority for any brownfield-imported policy. Flag a layout that maps one schema per fabric or co-mingles stretched and site-local objects in the same template as a change-blast-radius and drift risk.", "citation": "Cisco, \'Nexus Dashboard Orchestrator Schemas and Application Templates / Templates Overview and Operations for ACI Fabrics, Release 4.3.x\' (Schema and Template Design Considerations); Cisco ACI Multi-Site Architecture White Paper c11-739609", "engine_actionable": false}, {"id": "aci-multisite-gate-multi-pod-vs-multi-site-on", "domain": "aci-multisite", "title": "Gate Multi-Pod vs Multi-Site on the hard latency + single-APIC scale ceilings, not just fault-isolation taste", "priority": "Medium", "design_intent": "Treat the Multi-Pod-vs-Multi-Site decision as bounded by documented hard limits, not preference. Multi-Pod keeps one APIC cluster/policy domain across pods but only inside the qualified inter-pod RTT envelope (~50ms) and a single-fabric scale cap (order of ~12 pods / ~400 leaf), and every pod still runs its own IS-IS/COOP/MP-BGP so a control-plane fault is pod-contained. When sites exceed that latency or scale, or need an independent failure domain per region, choose Multi-Site: each fabric gets its own APIC cluster and control plane, interconnected over a routed core with optionally CloudSec-encrypted inter-site VXLAN. Never interconnect two independent fabrics back-to-back through leaf switches (dual-fabric) -- that topology is unvalidated/unsupported; use Multi-Site orchestration instead.", "recommended_action": "When proposing ACI as the DC target, decide Multi-Pod vs Multi-Site against the measured inter-site RTT and the fabric scale forecast: Multi-Pod inside the ~50ms / single-APIC-domain envelope; Multi-Site once latency, leaf/pod scale, or per-region fault-isolation crosses the line. Forbid back-to-back-leaf dual-fabric interconnect; orchestrate multiple fabrics via Nexus Dashboard Orchestrator/Multi-Site.", "citation": "Cisco ACI Multi-Site Architecture White Paper (c11-739609) and Cisco ACI Multi-Pod White Paper (c11-737855)", "engine_actionable": false}, {"id": "aci-multisite-localize-broadcast-by-default-on-a-stretched", "domain": "aci-multisite", "title": "Localize broadcast by default on a stretched ACI Multi-Site BD: keep per-BD \'Intersite BUM Traffic Allow\' OFF unless a flooding driver exists", "priority": "Medium", "design_intent": "When a bridge domain is stretched across ACI Multi-Site fabrics, BUM (broadcast / unknown-unicast / multicast) flooding between sites is an independent, per-BD policy (\'Intersite BUM Traffic Allow\' / ARP-flooding flags), separate from the decision to stretch the subnet itself. The leading-practice default is to stretch the BD with inter-site flooding DISABLED: broadcast and L2 multicast stay localized at each site, ARP is resolved as inter-site unicast via the MP-BGP EVPN/COOP control plane, and only true drivers turn flooding on. Those drivers are narrow and must be named: L2-multicast application clustering, live VM migration that needs L2 broadcast adjacency, or a legacy-to-ACI / inter-DC migration window where endpoints\' default gateway has not yet moved into the fabric. The design trap to flag explicitly: the Nexus Dashboard Orchestrator ENABLES ARP-flooding and Intersite BUM by default when it builds a stretched BD, so the safe posture is an active deselection, not an omission. Disabling inter-site BUM shrinks the WAN-wide L2 flood domain (the classic broadcast-storm / failure-domain risk of any DCI) to a per-site domain while preserving subnet stretch.", "recommended_action": "For every bridge domain proposed to stretch across ACI sites, require an explicit per-BD decision: default \'Intersite BUM Traffic Allow\' (and inter-site ARP flooding) to disabled, and only enable it where a documented driver (L2-multicast clustering, live migration, or a bounded legacy-migration cutover) exists -- then plan to turn it back off once the gateway moves into the fabric. Because the orchestrator defaults these knobs ON, treat them as an active \'turn-off\' step in the LLD, not a no-op.", "citation": "Cisco ACI Multi-Site Architecture White Paper (c11-739609) and Cisco ACI Multi-Site Fundamentals Guide (Stretched Layer 2 with/without flooding); Cisco Nexus Dashboard Orchestrator Configuration Guide for ACI Fabrics", "engine_actionable": false}, {"id": "aci-multisite-aci-multi-site-stretches-l2-over-a", "domain": "aci-multisite", "title": "ACI Multi-Site stretches L2 over a plain routed inter-site network via spine Head-End Replication -- no multicast DCI, but EX/FX+ spines are a hard dependency for VNID/Class-ID translation", "priority": "Medium", "design_intent": "ACI Multi-Site delivers inter-site Layer-2 (stretched BD BUM) using Head-End / ingress replication at the SOURCE spine: the spine makes one unicast VXLAN copy per remote site toward that site\'s Overlay Multicast TEP (O-MTEP, an anycast address shared by the site\'s spines). Consequently the inter-site network (ISN) needs only unicast IP routing (OSPF/BGP) with jumbo MTU -- it does NOT need multicast routing. This is the key architectural contrast with ACI Multi-Pod, whose IPN underlay DOES require PIM-Bidir + phantom-RP to carry BUM; Multi-Site trades that multicast-DCI dependency for spine replication state. The non-obvious hard constraint to surface in any HLD: because each site is an independent namespace (locally-significant VNIDs for BDs/VRFs and Class-IDs for EPGs), the connecting spines must perform cross-site namespace normalization (translate the VXLAN VNID and source Class-ID to the remote site\'s values), and that translation requires Cisco Nexus 9000 \'EX\'/\'FX\' (or newer) spine hardware. First-generation spines cannot do Multi-Site -- a lifecycle/hardware gate that must be checked before L2-stretch is even on the table.", "recommended_action": "When the target is ACI Multi-Site with any stretched BD, specify the ISN as a unicast-only routed core (OSPF/BGP, jumbo MTU, no PIM required) and explicitly verify the inter-site/spine tier is Nexus 9000 EX/FX or newer; if first-gen spines are present, treat Multi-Site L2-stretch as blocked until those spines are refreshed (or fall back to Multi-Pod, which has its own multicast-IPN cost). Capture the contrast with Multi-Pod\'s PIM-Bidir IPN so the team picks the DCI underlay deliberately.", "citation": "Cisco ACI Multi-Site Architecture White Paper (c11-739609); Cisco ACI Multi-Site Fundamentals Guide (cross-site namespace normalization / O-MTEP head-end replication); Cisco Multi-Site Deployment Guide for ACI Fabrics", "engine_actionable": false}, {"id": "evpn-bound-evpn-mac-mobility-with-the-rt-2", "domain": "evpn", "title": "Bound EVPN MAC mobility with the RT-2 sequence number, and arm duplicate-MAC freeze (N moves / M seconds) so a misconfig loop cannot melt the control plane", "priority": "Medium", "design_intent": "In a BGP-EVPN fabric, every host move is signaled by re-advertising the RT-2 (MAC/IP) route with an incremented MAC-Mobility extended-community sequence number, and the highest sequence wins -- this is what makes mobility fast and deterministic. But a duplicated MAC (two misconfigured hosts, a back-door L2 loop, or a flapping NIC) drives an unbounded sequence-number war that floods the overlay control plane. Design the fabric to detect this: if a single MAC records more than N moves within an M-second window it is declared duplicate and held down, then frozen after repeated offenses, ignoring further updates until cleared. Standards-based duplicate detection should be paired with the all-active DF/split-horizon loop guards (which only cover the multihomed case), and a known-static endpoint (e.g. a gateway VMAC) should carry the sticky/static flag so it can never be \'moved\' by a spoof.", "recommended_action": "Specify in the target-state HLD/LLD that EVPN duplicate-MAC / host-mobility detection is enabled with explicit thresholds (RFC 7432 / Cisco NX-OS default = 5 moves in 180 s, 30 s hold-down, freeze after 5 hold-downs in 24 h), that the static/sticky flag is set on anycast-gateway and other fixed MACs, and that an operational runbook exists to locate and clear a frozen/duplicate MAC. This is target-architecture doctrine: the brownfield engine collects no live EVPN host-mobility-manager state, so it cannot be auto-verified.", "citation": "IETF RFC 7432 (BGP MPLS-Based Ethernet VPN) Section 15 / 15.1 \'Duplicate MAC Detection\' (recommended defaults N=5, M=180s); Cisco Nexus 9000 NX-OS VXLAN BGP EVPN Configuration Guide (host-mobility-manager move-count / freeze-time / retry-count)", "engine_actionable": false}, {"id": "evpn-decide-rt-2-host-route-vs-rt-5", "domain": "evpn", "title": "Decide RT-2 host-route vs RT-5 prefix advertisement deliberately -- decouple IP-from-MAC for floating/silent endpoints, and design coexistence preference so the same host isn\'t learned twice", "priority": "Medium", "design_intent": "EVPN gives two ways to make an endpoint\'s IP reachable across the fabric: the RT-2 (MAC/IP) host route, which ties the /32-/128 to a specific MAC and enables ARP suppression and immediate per-host mobility; and the RT-5 (IP-prefix) route, which advertises a prefix decoupled from any MAC. Choose per use case. RT-5 is right for summarized inter-subnet/L3VNI reachability, floating/VIP addresses, prefixes behind a downstream router, and external/border connectivity -- it scales better and avoids per-host MAC churn. RT-2 host routes are right where ARP/ND suppression and host-granular mobility matter. The trap is the silent endpoint: a quiet TCP host whose MAC ages out (often ~5 min) triggers RT-2 withdrawal and loss of host-route reachability; mitigate with ARP/MAC-aging alignment or an RT-5 prefix that keeps the subnet reachable regardless. Where a host is learned by BOTH an RT-2 and an RT-5 for the same IP, the design must rely on a defined coexistence-preference (RT-2 host route preferred) so forwarding is unambiguous.", "recommended_action": "In the target-state design, document the RT-2-vs-RT-5 advertisement policy per VRF/VNI (host-route granularity only where suppression/mobility is needed; RT-5 prefixes for L3VNI, floating IPs, and external reach), align MAC-aging/ARP-refresh timers to prevent silent-host route withdrawal, and pin the RT-2/RT-5 coexistence preference. Target-architecture doctrine -- not auto-verifiable, as the engine collects no EVPN route-type advertisement state.", "citation": "IETF RFC 9136 (IP Prefix Advertisement in EVPN, the RT-5 route); RFC 7432 Section 7 (RT-2 MAC/IP Advertisement); Juniper \'EVPN Type 2 and Type 5 Route Coexistence with EVPN-VXLAN\' (coexistence preference algorithm); Arista \'EVPN Type-5 Routes: IP Prefix Advertisement\'", "engine_actionable": false}, {"id": "evpn-choose-the-evpn-df-election-algorithm-deliberately-default", "domain": "evpn", "title": "Choose the EVPN DF-election algorithm deliberately (default mod-N vs HRW vs preference-based) and control preemption", "priority": "Medium", "design_intent": "The Designated-Forwarder election is not a single fixed behavior: the default \'service-carving\' modulo-N (V mod N over VLAN and PE count) reshuffles which PE forwards BUM whenever a peer joins or leaves the Ethernet Segment, causing avoidable churn and a non-deterministic, operator-uncontrollable result. Treat the DF algorithm as an explicit design choice -- prefer the HRW (Highest-Random-Weight) algorithm for a deterministic, low-churn, node-consistent outcome, and move to the preference-based algorithm (highest configured preference value wins) when operations need to pin which PE is DF, drain a node for maintenance, and choose whether a returning PE may preempt. All PEs on the same segment must run the same algorithm or the election diverges and BUM is duplicated or black-holed.", "recommended_action": "In the HLD, state the chosen DF-election algorithm per Ethernet Segment and justify it: HRW for deterministic minimal-churn behaviour by default; preference-based when DF placement must be operator-pinned, with non-revertive (no-preempt) selected so a recovered PE does not preempt and re-disrupt traffic during a maintenance return. Mandate that every PE on a shared ES is provisioned with the identical algorithm and capability set, and that maintenance runbooks lower preference (or use DF-election timers) to drain a PE gracefully rather than yanking the link.", "citation": "IETF RFC 8584 (Framework for EVPN Designated Forwarder Election Extensibility, incl. the HRW algorithm) and RFC 9785 (Preference-Based EVPN Designated Forwarder Election, June 2025 -- Highest-Preference algorithm + Non-Revertive capability, updating RFC 8584)", "engine_actionable": false}, {"id": "evpn-engineer-the-ethernet-segment-identity-one-consistent-esi", "domain": "evpn", "title": "Engineer the Ethernet Segment identity: one consistent ESI + shared LACP system-ID across the multihoming PE pair", "priority": "Medium", "design_intent": "All-active multihoming is only correct if the multihomed CE believes its uplinks land on a single LAG peer. That requires the participating PEs to advertise the SAME 10-octet ESI value AND present the SAME LACP system-ID (with the same system-MAC) on the bundle facing that CE, while keeping a DIFFERENT ESI/system-ID per distinct segment. A mismatched or duplicated-across-segments ESI, or divergent LACP system-IDs, causes the CE to split its bundle, the PEs to miscompute the Ethernet Segment, and the DF/split-horizon machinery to break -- yielding loops, duplicate frames, or a collapsed redundancy. Because manual ESI/system-ID coordination across leaf pairs is drift-prone, prefer auto-derivation (e.g. NX-OS Type-0x03 MAC-based ESI auto-derived from the LACP system-ID + port-channel key) so identity is consistent by construction.", "recommended_action": "In the LLD, define the ESI allocation scheme: one unique, stable ESI per Ethernet Segment, identical on both PEs of the pair; the same LACP system-ID/system-MAC on the CE-facing bundle of both PEs; and a different ESI/system-ID for every other segment. Prefer auto-LACP ESI derivation over hand-assigned ESIs to eliminate cross-leaf coordination error, and record the ESI-to-segment map as part of the build sheet so it is auditable at NRFU.", "citation": "Juniper EVPN-LAG Multihoming guide (ESI Types & LACP -- same ESI and LACP system-id on all LAG member links) and Cisco NX-OS VXLAN EVPN multihoming guidance (Type-0x03 MAC-based ESI auto-derived from LACP system-id + port-channel key; identical system-MAC across PEs sharing an ESI)", "engine_actionable": false}, {"id": "evpn-stand-up-the-evpn-type-1-fast-convergence", "domain": "evpn", "title": "Stand up the EVPN Type-1 fast-convergence plane: per-EVI Aliasing for load-share, per-ES Mass-Withdrawal for sub-second failover", "priority": "Medium", "design_intent": "All-active multihoming convergence and load-balancing do not come from the MAC (Type-2) routes alone -- they ride the Type-1 Ethernet Auto-Discovery routes, and these must be deliberately enabled and verified. The per-EVI EAD route (Aliasing) lets a remote PE load-balance toward a CE across ALL PEs on the segment even before that PE has learned the CE\'s MAC, so traffic is not pinned to whichever PE happened to learn the host first. The per-ES EAD route (Mass-Withdrawal) lets a single withdrawal collapse reachability for every MAC behind a failed segment in one update -- delivering convergence independent of MAC-table size, instead of waiting to age out thousands of Type-2 routes. In single-active mode the same EAD machinery installs a pre-programmed backup path. A design that ignores these route types gets traffic polarization and MAC-scale-dependent failover.", "recommended_action": "In the HLD/LLD convergence section, require both EAD route families on every multihomed segment: per-EVI EAD (Aliasing) for all-active load distribution and per-ES EAD (Mass-Withdrawal) for fast failover, plus the Single-Active backup-path bit where single-active is chosen. Make NRFU assert that per-ES and per-EVI Type-1 routes are present and that a link-down on one PE converges via mass-withdrawal (one update) rather than by MAC aging -- and tie this to the application\'s stated convergence-time requirement.", "citation": "IETF RFC 7432 (Ethernet A-D per-EVI = Aliasing; Ethernet A-D per-ES = Mass-Withdrawal) and Cisco IOS-XR / IOS-XE EVPN Multihoming configuration guides (per-EVI Aliasing load-balancing, per-ES Mass-Withdrawal fast convergence, Single-Active backup path)", "engine_actionable": false}, {"id": "evpn-make-the-vrf-to-l3vni-mapping-a-single", "domain": "evpn", "title": "Make the VRF-to-L3VNI mapping a single fleet-wide invariant -- a per-VTEP mismatch silently black-holes inter-subnet routing", "priority": "Medium", "design_intent": "In symmetric IRB the L3VNI is the routing context stamped into the VXLAN header, so every VTEP that participates in a tenant must map that tenant\'s VRF to the identical L3VNI (and to matching route-targets). Because this is a control-plane agreement rather than a link that visibly goes down, an inconsistent or omitted mapping on one leaf does not error -- it simply drops or mis-VRFs that tenant\'s routed traffic at the receiving VTEP, a failure mode that hides until cutover. Treat the VRF->L3VNI->RT triplet as one source of truth rendered from the IPAM/automation system to every leaf, and forbid the L3VNI from colliding with any L2VNI ID (a collision suppresses the L2VNI). This is the EVPN-routing analogue of the one-VLAN-one-subnet and vPC-consistency invariants the engine already enforces at L2.", "recommended_action": "Define one canonical per-tenant VRF->L3VNI->route-target mapping and render it identically to all participating VTEPs from automation/SoT; add a pre-cutover conformance check that the mapping is present and identical on every leaf carrying the tenant, and that no L3VNI reuses an L2VNI ID.", "citation": "RFC 9135 / RFC 9136 (IP-VRF-to-VRF model, consistent L3VNI requirement); Cisco Nexus 9000 NX-OS VXLAN Configuration Guide (External VRF Connectivity & Route Leaking)", "engine_actionable": false}, {"id": "evpn-leak-between-tenant-vrfs-only-through-controlled-rt", "domain": "evpn", "title": "Leak between tenant VRFs only through controlled RT import/export (RFC 9136 IP-VRF-to-VRF), never an ad-hoc fusion router", "priority": "Medium", "design_intent": "Shared services (DNS, NTP, monitoring, shared Internet edge) and any deliberate inter-tenant reachability in a symmetric-IRB fabric should be expressed as scoped route-target import/export between the IP-VRFs -- export the shared-services prefixes into each consumer VRF and import the consumers\' return routes into the shared VRF -- following the RFC 9136 interface-less IP-VRF-to-VRF model. This keeps the leak auditable and default-deny: only the explicitly imported/exported prefixes cross, with the L3VNI preserving VRF context end-to-end. Avoid stitching tenants together with an out-of-band \'fusion\' router or back-to-back VRF interfaces, which reintroduces a stateful choke point, can break flow symmetry for any inserted firewall, and obscures which prefixes actually leak. Bound the leak to specific prefixes, not full-table import.", "recommended_action": "For shared-services or inter-tenant reachability, design scoped RT export of the shared prefixes into consumer VRFs and import of consumer return routes into the shared VRF (per-prefix, not full-table); document the leak matrix as the source of truth and avoid fusion-router workarounds; if a firewall is inserted, keep the path symmetric.", "citation": "RFC 9136 (IP Prefix Advertisement in EVPN, IP-VRF-to-VRF models); Cisco Nexus 9000 NX-OS VXLAN Configuration Guide -- External VRF Connectivity and Route Leaking / Centralized VRF Route-Leaking for VXLAN BGP-EVPN", "engine_actionable": false}, {"id": "evpn-terminate-vxlan-evpn-external-l3-at-a-dedicated", "domain": "evpn", "title": "Terminate VXLAN-EVPN external L3 at a dedicated border (leaf or spine) over per-VRF VRF-lite handoff, originating Type-5", "priority": "Medium", "design_intent": "Concentrate north-south exit from a standalone NX-OS VXLAN-EVPN fabric on a dedicated border node (border-leaf by default; border-spine only when north-south optimization outweighs mixing roles) rather than letting arbitrary leaves peer outward. The border is the one place that is both a VTEP and an external router: it hands tenant L3 to the edge/WAN router with the two-box VRF-lite model (one sub-interface and one routing session per tenant VRF over a shared physical link), and re-originates what it learns externally back into the fabric as EVPN Type-5 (IP-prefix) routes so every other VTEP can reach outside. Choosing border-leaf vs border-spine is an explicit failure-isolation and scale trade-off, not a default.", "recommended_action": "In the HLD/LLD name the external-connectivity boundary explicitly: which nodes are border (leaf vs spine and why), the per-tenant-VRF VRF-lite sub-interface/routing-session plan to the edge router, and the requirement that external prefixes re-enter the fabric as Type-5. Do not scatter external peering across compute leaves.", "citation": "Cisco \'Nexus 9000 VXLAN BGP EVPN Data Center Fabrics Fundamental Design and Implementation Guide\' and \'VXLAN Network with MP-BGP EVPN Control Plane Design Guide\' (cisco.com); Cisco IOS-XE \'Configuring EVPN VXLAN External Connectivity\' (Catalyst 9000)", "engine_actionable": false}, {"id": "evpn-suppress-fabric-host-routes-32-128-at-the", "domain": "evpn", "title": "Suppress fabric host-routes (/32, /128) at the EVPN border and summarize external prefixes inbound -- the border is a route-scale firebreak", "priority": "Medium", "design_intent": "A VXLAN-EVPN fabric advertises endpoint host-routes (/32, /128) by default for optimal east-west routing, and the external/WAN side imports a large external table -- neither belongs unfiltered across the border. Outbound, the border should advertise only the tenant aggregate/prefix routes to the edge router (host-routes add no inbound value and bloat the WAN), suppressing /32-/128 via route filtering or summarization at the border. Inbound, the border should summarize the external table before re-originating it as Type-5 into the fabric so leaf TCAM/route scale is not driven by the Internet/WAN. The border is the deliberate aggregation boundary in both directions.", "recommended_action": "Design an explicit border route-policy in both directions: outbound filter/summarize so fabric host-routes (/32,/128) are not leaked to the WAN; inbound summarize external prefixes (or inject a default) before they become Type-5 in the fabric. State the leaf route-scale and WAN-table-size budgets the policy protects.", "citation": "Cisco \'Nexus 9000 VXLAN BGP EVPN Data Center Fabrics Fundamental Design and Implementation Guide\' and \'VXLAN Network with MP-BGP EVPN Control Plane Design Guide\' (cisco.com) -- host-route suppression and external-route summarization at the border", "engine_actionable": false}, {"id": "evpn-gate-evpn-type-5-ingress-import-only-intended", "domain": "evpn", "title": "Gate EVPN Type-5 ingress: import only intended external prefixes / a default into each tenant VRF, never an unfiltered route-leak across the border", "priority": "Medium", "design_intent": "External connectivity must not become an open inter-VRF / tenant-isolation leak. EVPN Type-5 (IP-prefix) ingress into a tenant VRF is an explicit, per-VRF design act -- the L3VNI and import policy decide exactly which external prefixes (often just a default route, or a controlled aggregate) enter which tenant, and the WAN-facing peering must be treated as untrusted with an inbound route-policy. Without an import filter the border silently grants tenants reachability the design never sanctioned (bypassing the intended firewall/inspection path or merging tenant reachability), and the EVPN type-2/type-5 coexistence must be reasoned about so the intended next-hop wins. The external L3Out of an EVPN fabric is a security/segmentation boundary, not just a routing convenience.", "recommended_action": "For each tenant VRF, specify the Type-5 import policy at the border: which external prefixes (or default-only) are admitted, an explicit inbound route-policy on the untrusted WAN peer, and confirmation that admitted external reachability routes through the intended security/inspection path rather than bypassing it.", "citation": "Cisco \'Nexus 9000 VXLAN BGP EVPN ... Fundamental Design and Implementation Guide\' (Type-5 origination/import in the tenant VRF, cisco.com); Juniper \'EVPN Type-2 and Type-5 Route Coexistence with EVPN-VXLAN\' (junos type-5 ip-prefix-routes import discipline)", "engine_actionable": false}, {"id": "sp-l2vpn-carry-point-to-point-e-line-over", "domain": "sp-l2vpn", "title": "Carry point-to-point E-Line over EVPN-VPWS (no PW signaling, no MAC learning) instead of LDP pseudowires", "priority": "Medium", "design_intent": "For a point-to-point Ethernet service (E-Line / EPL / EVPL), use the EVPN VPWS service type rather than a targeted-LDP or BGP-AD pseudowire. EVPN-VPWS reuses the EVPN BGP control plane but, because the service is point-to-point, it advertises only per-EVI/per-EVPN-Ethernet-A-D (Type-1) reachability keyed by the VPWS service identifier (EVI + Ethernet-tag / AC-ID) and never learns or advertises customer MAC routes. This eliminates the per-pseudowire targeted-LDP session mesh and its O(n^2) signaling, gives one unified L2VPN+L3VPN control plane on the PEs, and turns the cross-connect into a BGP-discovered object instead of a manually-pinned PW. Use it as the default for new E-Line provisioning and as the modernization target for legacy VPWS.", "recommended_action": "When designing or modernizing point-to-point Ethernet (E-Line) transport, specify EVPN-VPWS (RFC 8214) as the service type: one EVI per service with a VPWS service ID (Ethernet-tag/AC-ID), route-targets to scope reachability, and no MAC advertisement. Reserve LDP/BGP-AD pseudowires only for interop with PE nodes that cannot run EVPN.", "citation": "IETF RFC 8214, \'Virtual Private Wire Service Support in Ethernet VPN\' (Aug 2017); Cisco \'EVPN Virtual Private Wire Service (VPWS) -- E-Line Service\', IOS XR L2VPN/EVPN Configuration Guide.", "engine_actionable": false}, {"id": "sp-l2vpn-migrate-legacy-vpls-ldp-vpws-to-evpn", "domain": "sp-l2vpn", "title": "Migrate legacy VPLS/LDP-VPWS to EVPN one PE at a time via dual-stack coexistence; collapse fan-out with FXC service-multiplexing only after", "priority": "Medium", "design_intent": "Two distinct EVPN-VPWS design levers, sequenced. (1) Brownfield migration: an EVPN-VPWS PE can run legacy VPWS and EVPN-VPWS cross-connects for the same attachment circuit over the same MPLS core, so the cutover is per-PE and per-AC (seamless dual-stack), not a network-wide flag-day software upgrade — pair each migrated PE with its legacy LDP/BGP-AD peer until both ends are EVPN. (2) Scale lever: once on EVPN, Flexible Cross-Connect (FXC) multiplexes many ACs across several Ethernet Segments/interfaces into ONE VPWS service tunnel, advertising a single Ethernet-A-D-per-EVI route for the first AC and locally associating the rest — so BGP state stops growing per-AC while single-active/all-active multihoming is preserved. Sequence matters: migrate first (PE-by-PE), then consolidate fan-out with FXC; don\'t fold the two changes into one cutover.", "recommended_action": "Plan an SP L2VPN modernization as: (a) per-PE dual-stack EVPN-VPWS+legacy-VPWS coexistence over the existing MPLS core, migrating one AC/PE pair at a time with rollback to the legacy PW; then (b) where AC fan-out is high, adopt FXC (single VPWS service ID, normalized VIDs not signaled) to cap BGP route count. Verify route-count and convergence at each step.", "citation": "Cisco \'Migration of VPLS and VPWS Networks to EVPN\' (IOS XR EVPN Configuration Guide); IETF RFC 9744, \'EVPN VPWS Flexible Cross-Connect (FXC) Service\' (Mar 2025).", "engine_actionable": false}, {"id": "sp-l2vpn-select-the-evpn-ethernet-segment-redundancy-mode", "domain": "sp-l2vpn", "title": "Select the EVPN Ethernet-Segment redundancy mode (all-active / single-active / port-active) from the access constraint", "priority": "Medium", "design_intent": "All-active is not a default to apply everywhere; the EVPN multihoming redundancy mode is a per-Ethernet-Segment decision driven by what the access side can tolerate. All-active gives per-flow load-balancing but REQUIRES the CE to bundle its links into a single LACP LAG (identical system-id/port-key/priority synchronized across the peering PEs) and tolerates flow-hashed asymmetry. Single-active (service-carving active/standby per service) suits a CE that cannot LAG across both PEs, or where per-VLAN determinism / loop-avoidance is needed. Port-active — the newer interface-level active/standby standardized in 2025 — gives deterministic active/standby for the WHOLE bundle (e.g. for deterministic QoS over an MC-LAG attachment circuit or strict ordering), independent of underlay (MPLS/VXLAN/SRv6). Pick the mode from the access topology and the traffic\'s load-balancing-vs-determinism requirement, and synchronize LACP state across the redundant PEs whichever mode is chosen.", "recommended_action": "For each multihomed segment, name the redundancy mode and justify it: all-active only where the CE presents one cross-PE LACP LAG and per-flow LB is wanted; single-active where the CE can\'t LAG or per-service carving is required; port-active where bundle-level deterministic active/standby (QoS/ordering) is needed. Require synchronized LACP parameters across the PE pair in every case.", "citation": "IETF RFC 7432 (All-Active/Single-Active redundancy); IETF RFC 9786 (EVPN Port-Active Redundancy Mode, Jun 2025); Cisco IOS XE MPLS Configuration Guide, CE EVPN Multihoming.", "engine_actionable": false}, {"id": "sp-l2vpn-migrate-vpls-to-evpn-seamlessly-per-vpn", "domain": "sp-l2vpn", "title": "Migrate VPLS to EVPN seamlessly per-VPN-instance with RFC 8560 integration, not a flag-day re-provision", "priority": "Medium", "design_intent": "Move a brownfield VPLS/LDP-signalled L2VPN core to BGP-EVPN as a staged, site-by-site and per-VPN-instance migration rather than a synchronized flag-day cutover. Introduce EVPN-capable PEs into the existing VPLS mesh for the same VPN instance: the EVPN PE auto-discovers and builds a pseudowire to every legacy VPLS PE (from its VPLS auto-discovery route) while running native EVPN to the other EVPN PEs, so old and new planes carry the same broadcast domain in parallel and customer traffic keeps flowing while PEs are converted one at a time. Decommission VPLS only once the last PE of an instance is EVPN. This preserves the VPLS investment (no forklift, often not even a software upgrade on the legacy PEs) and bounds the blast radius of the change to one instance/PE at a time.", "recommended_action": "When the target state is BGP-EVPN over an MPLS/SR core that today runs VPLS, plan the cutover as RFC 8560 seamless integration: enable EVPN on PEs incrementally per VPN instance, let each EVPN PE bridge to remaining VPLS PEs via pseudowires, validate the union domain, then retire VPLS per instance. Do not schedule one global VPLS-to-EVPN flag day.", "citation": "IETF RFC 8560 (Seamless Integration of EVPN with VPLS and their PBB Equivalents, 2019); Cisco IOS XR EVPN Configuration Guide, \'Seamless Migration of VPLS Network to EVPN\'.", "engine_actionable": false}, {"id": "sp-l2vpn-keep-multihoming-single-active-until-the-last", "domain": "sp-l2vpn", "title": "Keep multihoming Single-Active until the last VPLS PE of an instance is gone; defer EVPN all-active to the EVPN-only end state", "priority": "Medium", "design_intent": "EVPN\'s headline win over VPLS is standards-based all-active (per-flow) multihoming via Ethernet Segments, but it cannot be switched on while any VPLS PE still serves the same instance. VPLS has no Ethernet-Segment / designated-forwarder machinery, so a CE dual-homed to one EVPN PE and one VPLS PE (or to two PEs in a mixed redundancy group) has no coordinated forwarder — all-active there causes loops, duplicate frames and MAC flip-flop. RFC 8560 therefore mandates Single-Active redundancy for any multihomed segment during coexistence. The design consequence: stage all-active as an END-STATE benefit, enabled per Ethernet Segment only after both attachment PEs are EVPN and the instance has no remaining VPLS PE. Until then, dual-homed sites run active/standby, and the migration plan must call out exactly when each ES flips from Single-Active to All-Active.", "recommended_action": "In the VPLS-to-EVPN HLD/MOP, gate All-Active EVPN multihoming behind \'instance fully EVPN\'. Configure Single-Active on every multihomed segment that still shares an instance with a VPLS PE, and schedule the per-ES flip to All-Active as an explicit post-migration step, not as part of initial EVPN turn-up.", "citation": "IETF RFC 8560 (All-Active redundancy not applicable to VPLS coexistence -- MUST use Single-Active); RFC 7432 EVPN Ethernet-Segment redundancy modes.", "engine_actionable": false}, {"id": "sp-l2vpn-coordinate-a-redundant-pw-set-so-both", "domain": "sp-l2vpn", "title": "Coordinate a redundant PW set so both PE endpoints select the SAME single active pseudowire", "priority": "Medium", "design_intent": "When two PEs (or T-PEs) are joined by a redundant set of pseudowires, the failure mode is not \'no path\' but disagreement: if the two ends independently pick different members as active, the AC traffic is either duplicated or black-holed. The design must therefore make the active/standby choice a coordinated decision, not two local ones. Pick the coordination model deliberately: independent mode (each PE advertises its local Preferential-Forwarding state and both run an identical selection algorithm, so the active PW is the one both mark active) versus master/slave mode (one PE dictates, the other mirrors) — master/slave removes ambiguity at the cost of flexibility. Make tie-breaking deterministic with an explicit precedence value (lowest wins) or a primary/secondary designation, and choose revertive vs non-revertive switchover on purpose (revertive gives predictable steering back to the primary; non-revertive avoids a second hit). Only one member forwards at a time — a hot-standby PW that is signalled-up but not forwarding is correct, not a fault.", "recommended_action": "For every redundant pseudowire set, specify the coordination mode (independent vs master/slave), an explicit per-PW precedence or primary/secondary order, and the revertive policy; verify both endpoints agree on the single active member before cutover so the standby PW is hot-standby, not a second active path.", "citation": "IETF RFC 6718 (Pseudowire Redundancy) and RFC 6870 (Pseudowire Preferential Forwarding Status Bit).", "engine_actionable": false}, {"id": "sp-l2vpn-pin-the-service-pw-to-a-transport", "domain": "sp-l2vpn", "title": "Pin the service PW to a transport path (preferred-path) and drive fast failover with PW-status / MAC-withdrawal signalling", "priority": "Medium", "design_intent": "PW redundancy spans two layers that must be designed together. At the transport layer, bind the pseudowire to an explicit forwarding path via a preferred-path (e.g. an MPLS-TE / SR tunnel) in the PW class, so the service rides an engineered, protectable path instead of whatever the IGP next-hop happens to be — and decide what happens when that path is gone (disable-fallback to hold the service down vs fall back to the IGP path). At the service layer, make a failover propagate quickly: when the active PW or its attachment circuit drops, the PE must signal the change (PW status TLV) and, for any multipoint/VPLS member, trigger a MAC-address-withdrawal so remote PEs flush MACs learned via the failed PW and relearn over the new active one — otherwise traffic black-holes to stale MAC entries until aging. Treat the transport-protection layer (TE-FRR/TI-LFA on the tunnel) and the service-redundancy layer (backup PW + status/withdraw) as complementary, not interchangeable: fast transport repair protects the path, PW redundancy protects against endpoint/AC loss.", "recommended_action": "Bind each protected PW to a preferred-path transport tunnel with an explicit fallback policy, and ensure failover propagation is enabled (PW status signalling plus MAC-withdrawal on VPLS/multipoint members) so remote PEs flush stale MACs and reconverge onto the new active PW instead of black-holing.", "citation": "Cisco MPLS Layer 2 VPNs Configuration Guide -- L2VPN Pseudowire Redundancy & preferred-path (pseudowire-class); VPLS MAC Address Withdrawal (LDP MAC-list TLV), consistent with RFC 6870 PW status procedures.", "engine_actionable": false}, {"id": "sp-mvpn-default-to-mldp-p-tunnels-for-mvpn", "domain": "sp-mvpn", "title": "Default to mLDP P-tunnels for MVPN; reserve RSVP-TE P2MP for bandwidth-guaranteed few-source trees (and ride mLDP over TE when you need both)", "priority": "Medium", "design_intent": "Both mLDP and RSVP-TE P2MP build label-switched provider multicast trees, but they sit at opposite ends of a state-vs-control tradeoff. mLDP is receiver/tail-end-initiated: one P2MP LSP in both control and data plane, branch state grown on-demand from the leaves inward, no head-end per-leaf bookkeeping -- the safe, scalable default for general MVPN. RSVP-TE P2MP is head-end-initiated and signals a P2P sub-LSP toward every leaf, so the root and core hold per-leaf state, but in return it offers constraint-based/explicit routing and bandwidth admission control -- so confine it to the narrow case it earns: a few source sites distributing high-rate video that genuinely needs a reserved, engineered path. Two corollaries from the doctrine: (a) resilience scales the same way -- a receiver-initiated mLDP tree self-protects with TI-LFA / MoFRR local repair and no pre-built backups, whereas RSVP-TE P2MP node-protection must pre-establish a backup tree per-tree-per-node (state that explodes with tree count), so \'I need fast-reroute\' is not by itself a reason to choose RSVP-TE P2MP; (b) when a deployment needs mLDP\'s low state AND a TE/bandwidth-engineered core path, steer the mLDP tree onto an RSVP-TE LSP (the \'mpls mldp path traffic-eng\' construct) rather than converting the whole MVPN to RSVP-TE P2MP.", "recommended_action": "In the target-state MVPN design, set mLDP as the default provider-tunnel type fleet-wide and justify any RSVP-TE P2MP island against a concrete bandwidth-reservation/few-source-video driver; if TE or guaranteed-path is required under an otherwise-mLDP design, document the mLDP-over-RSVP-TE-tunnel steering option and the FRR model (TI-LFA/MoFRR for mLDP) instead of head-end P2MP-TE backup trees. Engine cannot verify the provider core, so emit this as advisory doctrine, not a fired detector.", "citation": "Cisco, \'Core of Multicast VPNs: Rationale for Using mLDP\' (whitepaper C11-598929); NANOG 49, \'Introduction to Label-Switched Multicast: P2MP-TE & mLDP\'; RFC 9860 \'Multicast-Only Fast Reroute (MoFRR) Based on TI-LFA\' (Informational, Oct 2025)", "engine_actionable": false}, {"id": "sp-mvpn-minimize-provider-core-tree-state-with-on", "domain": "sp-mvpn", "title": "Minimize provider-core tree state with on-demand / partitioned MDT (S-PMSI built only between PEs that actually exchange traffic) instead of a full-mesh default MDT", "priority": "Medium", "design_intent": "A classic \'default MDT\' builds a provider tree (P2MP rooted at every PE, or one MP2MP) that EVERY PE in the MVPN must join -- so core branch state and bandwidth are spent even for PEs that are pure senders or have no interested receivers, and the tree count grows with PE count regardless of actual traffic interest. Partitioned / on-demand MDT (Cisco mVPN Profile 14) inverts this: it builds nothing until a receiver expresses interest, then instantiates a selective P-tunnel (S-PMSI) only between the specific ingress PE that sources a flow and the egress PEs that requested it. The result is \'maximal optimization of state in the core -- only P2MP trees, and only on demand\', i.e. core state tracks real receiver demand rather than membership. This is the modern default for a new-build MVPN core where tree-state scaling, not setup simplicity, is the constraint -- accepting a small first-packet/join-latency cost and a more complex control plane (BGP MVPN auto-discovery / C-multicast signalling) in exchange for far fewer trees at scale.", "recommended_action": "For a target-state MVPN, prefer an on-demand selective-tree model (partitioned MDT / S-PMSI-on-demand, Profile 14-style) over a full-mesh always-on default MDT when PE count or source/receiver sparsity makes per-PE tree state the scaling bottleneck; size the expected tree count from the source-to-interested-receiver matrix, not from PE count. Advisory only -- the engine has no view of the provider MDT plane.", "citation": "Cisco, \'IP Multicast: MVPN Configuration Guide -- MVPN mLDP Partitioned MDT\' (IOS XE 17.1.x); Cisco, \'Configure mVPN Profiles within Cisco IOS XR\' (Doc 200512, Profile 14 Partitioned MDT)", "engine_actionable": false}, {"id": "sp-mvpn-set-the-data-mdt-threshold-and-its", "domain": "sp-mvpn", "title": "Set the data-MDT threshold (and its hold-down) as an explicit bandwidth-vs-core-state trade-off, not a default", "priority": "Medium", "design_intent": "Whether a C-flow rides the default-MDT or a data-MDT is governed by a single SP-owned knob -- the data-MDT threshold -- and that knob is a deliberate trade-off, not a checkbox. Lowering it (more flows onto selective trees) saves core bandwidth and offloads non-receiver PEs but multiplies the (S,G) / mLDP-LSP state the P routers must hold and the Join-TLV/S-PMSI signalling churn; raising it (or leaving data-MDT off) minimises core state but floods heavy flows to every PE. Two further behaviours must be designed, not assumed: switchover is rate-sampled (sub-second), and switch-BACK to the default-MDT is gated by a data-holddown timer so a bursty source does not flap between inclusive and selective trees, thrashing core state. The design output is a per-MVPN threshold + holddown chosen from the source-rate distribution and the P-router state budget -- the provider explicitly owning where the bandwidth-vs-state line sits.", "recommended_action": "Document, per multicast VRF, the data-MDT threshold and data-holddown (switch-back) timer, and justify the value against the C-source rate distribution and the core\'s per-router multicast-state budget. Avoid both extremes: an unset threshold (heavy flows flood all PEs) and an aggressively low one (state explosion + tree flapping on bursty sources). Re-evaluate the threshold when source bandwidth profiles change rather than leaving an inherited default.", "citation": "RFC 6037 (Rosen) Data-MDT (SP-owned bandwidth-vs-P-router-state tradeoff); RFC 6513 (Selective vs Inclusive PMSI); Cisco IP Multicast: MVPN Configuration Guide (mdt data threshold, data holddown / switchover)", "engine_actionable": false}, {"id": "cloud-pin-per-flow-az-affinity-appliance-mode-when", "domain": "cloud", "title": "Pin per-flow AZ affinity (appliance mode) when inserting a centralized inspection VPC behind a cloud transit hub", "priority": "Medium", "design_intent": "When a stateful firewall/IPS lives in a shared inspection VPC behind a cloud transit gateway, the hub\'s default behavior is to keep each flow in its originating Availability Zone; the return half of a cross-AZ flow then lands on a different-AZ appliance instance that never saw the request and silently drops it. Insert the appliance only with per-flow AZ stickiness enabled (a flow-hash that pins both directions to one appliance interface for the life of the flow), and respect its constraints: exactly one transit gateway per inspection VPC (peer hubs do not share flow state), and source+destination must enter from the same hub attachment, or inspection breaks. This is the cloud-transit-hub analog of on-prem stateful-firewall flow symmetry, but it is a distinct, AZ-scoped failure mode that does not exist in the on-prem case.", "recommended_action": "For any hybrid on-ramp that hairpins inter-VPC/inter-spoke traffic through a centralized inspection VPC, mandate appliance-mode / per-flow AZ affinity on the inspection attachment and document the single-hub and same-attachment constraints in the HLD; never assume a multi-AZ firewall fleet inspects symmetrically by default.", "citation": "AWS Transit Gateway documentation, \'Example: Appliance in a shared services VPC\' and \'Stateful appliances and appliance mode\' (docs.aws.amazon.com/vpc/latest/tgw/how-transit-gateways-work.html)", "engine_actionable": false}, {"id": "cloud-treat-the-cloud-transit-hub-s-route-domains", "domain": "cloud", "title": "Treat the cloud transit hub\'s route domains as the segmentation SSOT, and resolve overlapping CIDRs before on-ramp attachment", "priority": "Medium", "design_intent": "In a cloud transit hub, segmentation is not a firewall rule -- it is which hub route table each attachment associates to and propagates into, with blackhole routes for explicit isolation (the isolated-VPC and isolated-with-shared-services patterns). This route-domain map is the single source of truth for east-west reachability and must be designed deliberately, not left on the default \'everything propagates to one table\' router. Two hard ceilings bound it: the hub allows only a finite number of route tables and total routes (e.g. a default of 20 route tables and 10,000 combined routes on AWS Transit Gateway), so segment count is a capacity decision; and attachments carrying overlapping CIDRs cannot be routed or load-balanced across (the hub is longest-prefix-match only, with no ECMP across overlaps). A brownfield estate with overlapping RFC1918 space must therefore re-address or NAT before it can be attached -- the on-ramp cannot paper over an address collision the way a stretched L2 merge might.", "recommended_action": "Author the hub route-domain map (association + propagation + blackhole routes) as a first-class HLD artifact sized against the route-table/route quotas; gate on-ramp attachment on an addressing-overlap check and require re-addressing or NAT for any overlapping prefix before it joins the fabric.", "citation": "AWS Transit Gateway documentation, \'Routing\' / \'Isolated VPCs\' / \'Equal Cost Multipath routing\' (VPC CIDRs cannot overlap) and AWS Transit Gateway Quotas (docs.aws.amazon.com/vpc/latest/tgw/transit-gateway-quotas.html)", "engine_actionable": false}, {"id": "cloud-size-the-vpn-based-cloud-on-ramp-by", "domain": "cloud", "title": "Size the VPN-based cloud on-ramp by tunnel quantization: aggregate only via ECMP with dynamic BGP, then scale out horizontally", "priority": "Medium", "design_intent": "An IPsec VPN on-ramp does not deliver a smooth bandwidth dial -- throughput is quantized per tunnel (a single AWS Site-to-Site VPN tunnel caps near 1.25 Gbps), and the only way to aggregate is equal-cost multipath across multiple tunnels, which requires dynamic BGP and the hub\'s VPN-ECMP option enabled; a statically-routed VPN gets no ECMP and is stuck at one tunnel\'s ceiling. Beyond a few tunnels, the validated pattern is horizontal scale-out: stand up additional on-ramp router instances and ECMP-load-share across them, rather than expecting one tunnel or one appliance to scale vertically. Two coupled constraints must be designed in: the VPN path MTU (1500) is far below the intra-fabric MTU (8500) with MSS clamping, so jumbo assumptions break at the on-ramp; and a dedicated private circuit (Direct Connect / ExpressRoute) advertising the same prefixes is preferred over the VPN, which then serves only as the lower-throughput backup.", "recommended_action": "Compute required on-ramp bandwidth, divide by per-tunnel capacity to get tunnel/instance count, mandate dynamic BGP + VPN-ECMP (never static) for aggregation, plan horizontal scale-out past a few tunnels, and pin the VPN MTU/MSS expectations; treat VPN as backup to a dedicated circuit when sustained throughput matters.", "citation": "AWS Site-to-Site VPN / Transit Gateway docs (per-tunnel ~1.25 Gbps; ECMP requires dynamic BGP + VPN-ECMP option) + Cisco Catalyst SD-WAN Cloud OnRamp for IaaS/Colocation design guides (horizontal data-plane scale-out)", "engine_actionable": false}, {"id": "cloud-engineer-the-hybrid-edge-bgp-path-attribute-plane", "domain": "cloud", "title": "Engineer the hybrid-edge BGP path-attribute plane explicitly -- the cloud\'s LPM/relative-cost overrides AS-path prepend", "priority": "Medium", "design_intent": "Make traffic symmetry and primary/backup selection over Direct Connect / ExpressRoute / Cloud Interconnect an explicit BGP-policy decision, not an accident of defaults. Steer ingress (cloud->on-prem) by what the cloud honors -- a more-specific advertisement or the provider\'s well-known LocalPref community (e.g. AWS 7224:7300/7200/7100) -- not by AS-path prepend, because the cloud evaluates longest-prefix-match and its own relative connection cost BEFORE AS_PATH, so prepend is silently ignored across regions or unequal-cost links. Steer egress (on-prem->cloud) on your own routers with LocalPref. Keep advertised prefixes/LocalPref/MED/AS-path identical on both legs only when active-active load-share is the actual intent.", "recommended_action": "For each cloud attachment, document the intended primary/secondary and active-active behavior, then choose the steering lever per direction: more-specific prefix or provider LocalPref community for cloud-side ingress, on-prem LocalPref for egress; treat AS-path prepend as advisory only and verify it is not overridden by LPM/relative-cost. Flag any hybrid edge that relies solely on prepend for failover.", "citation": "AWS Direct Connect User Guide -- Routing policies and BGP communities (Local Preference community tags 7224:7100/7200/7300 evaluated before AS_PATH; prepend ineffective across regions / unequal relative cost); Azure ExpressRoute routing (LPM) guidance", "engine_actionable": false}, {"id": "cloud-respect-the-cloud-gateway-s-prefix-advertisement-ceiling", "domain": "cloud", "title": "Respect the cloud gateway\'s prefix-advertisement ceiling -- summarize on-prem, because over-advertising idles the whole BGP session", "priority": "Medium", "design_intent": "Cloud BGP attachments enforce a hard cap on the number of prefixes you may advertise INTO them, and breaching it is not graceful degradation -- the session drops to idle and ALL routes/traffic over that attachment cease. AWS Direct Connect private/transit VIFs cap at 100 IPv4 + 100 IPv6 (Transit Gateway association raised to ~200), public VIFs at 1000; Azure ExpressRoute and other providers impose their own learned/advertised quotas. Design the on-prem advertisement as a deliberately summarized supernet plan that fits the ceiling with headroom, rather than leaking the full interior table; where more-specifics are genuinely needed for steering, budget them explicitly against the cap.", "recommended_action": "Build an advertisement plan per cloud attachment: aggregate on-prem prefixes to a small summarized set sized under the provider ceiling (with growth headroom), and explicitly account for any more-specifics injected for traffic-symmetry. Never let the interior IGP/BGP table redistribute unfiltered toward the cloud edge.", "citation": "AWS Direct Connect quotas / User Guide (100-prefix per-VIF limit on private & transit VIFs -> BGP session goes idle when exceeded; 1000 on public VIF; ~200 per TGW-to-DXGW association); Azure ExpressRoute advertised/learned-route limits", "engine_actionable": false}, {"id": "cloud-normalize-segmentation-to-a-provider-neutral-intent-model", "domain": "cloud", "title": "Normalize segmentation to a provider-neutral intent model, then render per-cloud -- never lift-and-shift a security-group rule set", "priority": "Medium", "design_intent": "Each cloud\'s native access-control primitive is semantically different, so a rule set cannot be ported one-to-one across providers. AWS Security Groups are allow-only, stateful and instance-scoped (anything not permitted is implicitly denied); Azure NSGs support explicit allow AND deny and bind at instance or subnet; GCP firewall rules are stateful and VPC-scoped. Author segmentation once in a single provider-neutral intent model (application tiers / roles and their permitted flows) and let a controller compile that intent down into each provider\'s primitive, rather than hand-translating between dialects where a missing deny-rule or a wrong attach-point silently changes the effective posture. This keeps one source of truth for who-may-talk-to-whom and prevents per-cloud drift from masquerading as policy.", "recommended_action": "When the target spans more than one public cloud, define segmentation as provider-neutral intent (tier-to-tier flow rules) and generate each cloud\'s SG/NSG/firewall config from it; document the per-primitive semantic gaps (allow-only vs allow+deny, instance vs subnet vs VPC scope, stateful vs stateless NACL) so a normalized rule cannot be assumed to behave identically everywhere.", "citation": "Cisco Multicloud Defense White Paper (cisco.com/c/en/us/products/collateral/security/multicloud-defense/multicloud-defense-wp.html); AWS/Azure/GCP access-control documentation (SG allow-only stateful instance-scoped; NSG allow+deny instance/subnet; GCP firewall stateful VPC-scoped)", "engine_actionable": false}, {"id": "cloud-carry-segmentation-identity-across-the-on-prem-cloud", "domain": "cloud", "title": "Carry segmentation identity across the on-prem/cloud boundary as shared dynamic tag-group objects -- not as static IP ACLs that drift with autoscaling", "priority": "Medium", "design_intent": "In a hybrid estate a segment (an application tier, a trust zone) must mean the same thing on the on-prem firewall and on the cloud-side enforcement gateway, or the policy frays at the seam. Encode the segment as a dynamic, tag/label-based group object that is discovered continuously and shared as a single common object across the on-prem firewall, the cloud gateways and the orchestrator, so the SAME named group resolves to the right (and provider-specific, autoscaling-current) IP set on each side. Pinning the segment to a hand-maintained IP/CIDR allow-list instead is the failure mode: cloud workload IPs are ephemeral, so the list goes stale the moment an instance scales or recycles, opening or stranding flows. Continuity of the group identity -- not of the addresses -- is what holds segmentation together across the boundary.", "recommended_action": "For site-to-cloud segmentation, model each zone/tier as a dynamic tag-based group shared between the on-prem firewall and the cloud enforcement point (one common object, not two hand-synced lists); avoid static IP/CIDR allow-lists for any group whose membership autoscales, and confirm the tag-to-membership resolution is provider-aware on each side.", "citation": "Cisco Hybrid Mesh Firewall / Multicloud Defense \'Hybrid Segmentation\' + dynamic tag-based address objects (blogs.cisco.com/security/cisco-hybrid-mesh-firewall...; Cisco Multicloud Defense User Guide - Rules and Rule Sets)", "engine_actionable": false}, {"id": "optical-transport-select-the-dci-optical-transport-tier-from", "domain": "optical-transport", "title": "Select the DCI optical transport tier from fiber availability, reach and capacity: grey optics, then pluggable DWDM (ZR/ZR+), then transponder DWDM", "priority": "Medium", "design_intent": "Choose the data-center-interconnect optical layer as a ranked decision, not a default. Grey (uncolored) client optics are the least-cost choice when dark fiber is plentiful and the span is short; pluggable coherent DWDM (400G ZR for DCI-class reach, ZR+/OpenZR+ for metro/regional) is preferred when fiber is scarce or capacity is high, because one colored wavelength multiplies a single fiber pair into dozens of channels; a full external coherent transponder/muxponder shelf is reserved for long-haul reach, very high per-fiber channel counts, or where the router faceplate cannot host the optic. Drive the pick by the concrete axes (fiber count available, distance/OSNR reach, target capacity per fiber, cost, and faceplate power), and right-size rather than over-buy reach.", "recommended_action": "When a design spans buildings/sites over owned or leased fiber, state the optical tier explicitly with its justification: grey if fiber is abundant and reach is short; pluggable DWDM (ZR/ZR+) if fiber is constrained or capacity is high; transponder DWDM only for long-haul or extreme channel density. Record which axis (fiber scarcity vs reach vs capacity vs cost) was the ranked primary driver.", "citation": "OIF 400ZR Implementation Agreement; OpenZR+ MSA white paper (rev 0.92, 2023); Cisco \'Routed Optical Networking / Coherent Pluggable Optics\' Solution Overview", "engine_actionable": false}, {"id": "optical-transport-prefer-ip-over-dwdm-faceplate-coherent-zr", "domain": "optical-transport", "title": "Prefer IP-over-DWDM (faceplate coherent ZR/ZR+ pluggables) over a separate transponder layer when the router supports it -- collapse the optical layer, but engineer the line system and OSNR budget", "priority": "Medium", "design_intent": "IP-over-DWDM removes the middle transponder shelf by seating the coherent DSP optic (QSFP-DD/OSFP) directly in the router faceplate, cutting cost (transponder elimination) and roughly a third-to-quarter of the per-wavelength power versus an external transponder slot. But collapsing the layer transfers optical-engineering responsibility to the IP team: the pluggable is an \'alien wavelength\' on the DWDM line system, so its launch power, channel plan, and end-to-end OSNR/loss budget (fiber attenuation, connectors/splices, amplifier noise figure, ROADM add/drop loss, plus design margin) must be validated against the optic\'s required receive OSNR for the chosen modulation, and certified for interop with the third-party ROADM/amplifier line system. A point-to-point amplified pair and a ROADM-switched line system are different budget problems.", "recommended_action": "For new DCI/metro links, default to faceplate coherent pluggables (IPoDWDM) where the platform and reach allow; require an explicit optical link-budget worksheet (per-channel launch power, span loss, amplifier/ROADM insertion loss, margin, receive OSNR vs the optic\'s threshold) and an alien-wavelength interop sign-off with the line-system vendor before committing the design.", "citation": "OIF 400ZR / OpenZR+ IA; ITU-T G.698.2 (amplified multichannel DWDM application code / alien wavelength) and G.680; Cisco Routed Optical Networking design guidance", "engine_actionable": false}, {"id": "optical-transport-split-survivability-across-layers-on-a-dwdm", "domain": "optical-transport", "title": "Split survivability across layers on a DWDM core: optical-layer 1+1/1+1+R (with SRLG-diverse fibers) for wavelength services, IP-layer TI-LFA/FRR for packet services -- and never double-protect the same failure twice", "priority": "Medium", "design_intent": "On an IP-over-DWDM network the optical and IP layers each offer protection, and the design must assign each failure class to exactly one owner rather than paying for both. Wavelength/circuit services that need hardware-fast recovery use optical-layer protection (1+1 dedicated, or 1+1+R adding CDC-ROADM optical restoration to survive a second failure), engineered so working and protect wavelengths ride physically SRLG-diverse fiber routes -- otherwise one backhoe cut takes both. Packet services lean on the IP layer (Segment-Routing TI-LFA giving sub-50 ms, SRLG-aware, post-convergence repair) so the optical layer need not pre-build a protect path for every router link. Coordinating the two (e.g. IP A/B-plane + optical restoration) measurably reduces line-interface count versus protecting everything at one layer, but uncoordinated double protection wastes capacity and can fight during a fault.", "recommended_action": "On any DWDM/IPoDWDM core, document a multilayer survivability matrix: which failure classes are recovered at the optical layer (and the scheme: 1+1 / 1:1 / 1+1+R) vs the IP layer (TI-LFA/FRR), enforce SRLG/conduit diversity on the working+protect fibers, and explicitly forbid protecting the same failure at both layers. Tie hold-off timers so the faster layer acts first.", "citation": "ITU-T G.808/G.873 (optical protection architectures 1+1/1:1); RFC 9855 (Segment-Routing TI-LFA, SRLG-aware sub-50ms IP FRR)", "engine_actionable": false}, {"id": "optical-transport-choose-the-roadm-add-drop-architecture-by", "domain": "optical-transport", "title": "Choose the ROADM add/drop architecture by the flexibility tier actually needed (colorless / directionless / contentionless), not maximal CDC by default", "priority": "Medium", "design_intent": "Treat the optical add/drop plane as a deliberate tiered choice. Colorless makes any add/drop port wavelength-agnostic (a channel can be retuned in software without recabling); directionless lets any add/drop port reach any line degree so a wavelength can be re-pointed to a new direction with no on-site truck-roll; contentionless additionally lets multiple instances of the same wavelength terminate on one add/drop device, which a colorless-directionless block would otherwise block. Each added \'C\' buys remote-reconfigurability but costs WSS ports, optics, and complexity, so select the tier from the real provisioning/restoration agility the service needs rather than buying full CDC-F everywhere. A hard structural constraint follows: for a node to be truly contentionless at N degrees, the number of independent drop units must equal the node\'s degree count, which sizes the add/drop hardware up front.", "recommended_action": "When an optical/DWDM transport layer is in scope, state the target add/drop tier per ROADM site (fixed mux/demux vs colorless, +directionless, +contentionless, +flex-grid) and justify it from the wavelength-churn and remote-reconfiguration requirement; size contentionless nodes so drop units match the degree count. This engine collects no photonic state, so it cannot detect the installed ROADM tier -- carry this as a design-questionnaire item and an HLD optical-layer decision, never inferred from the assessed L1-L4 evidence.", "citation": "Cisco ONS 15454 & NCS 2000 DWDM Network Configuration Guides (colorless/directionless/contentionless ROADM, flex-spectrum SMR line cards); Cisco Transport Planner", "engine_actionable": false}, {"id": "optical-transport-plan-optical-layer-survivability-as-a-deliberate", "domain": "optical-transport", "title": "Plan optical-layer survivability as a deliberate choice between hard wavelength protection and GMPLS/WSON dynamic restoration -- colorless+tunable add/drop is the enabler, contention is the failure mode", "priority": "Medium", "design_intent": "At Layer 0 there are two survivability models with different cost/recovery trade-offs. Dedicated optical protection (e.g. a pre-provisioned 1+1 / OMS or path protection) gives the fastest, deterministic recovery but reserves a standby wavelength end-to-end. GMPLS/WSON dynamic restoration instead recomputes and re-establishes a lightpath after a failure across a colorless-directionless mesh, which uses spectrum far more efficiently (shared, not dedicated) but recovers more slowly and only if a wavelength-continuous, contention-free path still exists -- so blocking/contention is a real restoration failure mode, and tunable line interfaces plus colorless add/drop are the hardware enablers. Match the model to the circuit\'s tolerated outage: keep protection for the few latency/loss-critical services, restoration for the bulk, and verify restorability rather than assuming the mesh always heals.", "recommended_action": "For any DWDM/OTN transport in scope, decide per service class whether it gets dedicated optical protection or GMPLS/WSON restoration, and validate that restorable circuits have a spectrum/wavelength-feasible alternate path (no contention) under the single-failure cases. This is HLD optical-survivability doctrine: the engine collects no Layer-0 control-plane or wavelength state, so it cannot compute optical restorability -- never let absence of optical evidence read as \'optical layer is protected\'.", "citation": "ITU-T/GMPLS WSON optical control-plane principles as applied in Cisco WSON / NCS optical control-plane design; Fibre Systems \'The case for SDN-based optical network restoration\'", "engine_actionable": false}, {"id": "optical-transport-decide-the-ip-over-dwdm-layer-collapse", "domain": "optical-transport", "title": "Decide the IP-over-DWDM layer-collapse (Routed Optical Networking) vs a transponder-based optical layer as an explicit architecture trade -- faceplate power/OSNR and open-line-system ownership are the constraints", "priority": "Medium", "design_intent": "Coherent pluggables (OIF 400ZR, OpenZR+, 800ZR) in router faceplates collapse the standalone transponder shelf onto the router (Routed Optical Networking / IPoDWDM), leaving two layers -- routers carrying coherent optics over a simplified open line system -- which cuts rack units, power, management planes and infrastructure cost materially versus a three-layer IP+OTN+DWDM stack. The trade is real and must be designed, not assumed: a pluggable launches near -10 dBm versus a bright line-card transponder\'s ~0/+1 dBm, so it is OSNR/reach-constrained and depends on a well-engineered amplified line system; 400ZR is a fixed-rate short-reach DCI profile while OpenZR+ adds flexible modulation/baud for longer amplified reach; and the open, multi-vendor router-to-line-system boundary moves the integration and fault-domain responsibility onto the operator. Pick the model from reach, capacity, operational ownership and the willingness to run one converged IP+optical management plane.", "recommended_action": "When optical transport is in scope, state whether the target is IPoDWDM/Routed-Optical-Networking (coherent pluggables in the router over an open line system) or a transponder-based optical layer, and justify it against per-span reach/OSNR feasibility, the 400ZR-vs-OpenZR+ profile, and who owns the open-line-system fault domain. The engine sees no optical reach/OSNR/line-system data, so this stays an HLD decision and design-interview item; do not infer optical feasibility from the L1-L4 assessment.", "citation": "Cisco Routed Optical Networking design guidance; OIF 400ZR Implementation Agreement and OpenZR+ MSA white paper", "engine_actionable": false}, {"id": "optical-transport-select-the-coherent-pluggable-400zr-vs-openzr", "domain": "optical-transport", "title": "Select the coherent pluggable (400ZR vs OpenZR+/ZR+) from the actual span reach and line-system type, not from the line rate alone", "priority": "Medium", "design_intent": "400ZR and OpenZR+ share the QSFP-DD/OSFP form factor and an Ethernet-only host interface but are different engineering envelopes. Baseline OIF 400ZR is fixed DP-16QAM with CFEC, ~40 km unamplified and ~120 km over an amplified line, in a lower power budget -- ideal for metro/campus DCI point-to-point. OpenZR+ adds OpenROADM oFEC for far greater coding gain (amplified reach of 500 km and beyond), multi-rate (100/200/300/400G) and multi-modulation (QPSK/8QAM/16QAM) flexibility, and higher dispersion tolerance, at a larger ~25 W module power budget, and is defined for amplified line systems. Choosing by \'it\'s 400G\' alone strands links: a 400ZR module will not close a long amplified span, while paying for ZR+ on a sub-120 km unamplified hop wastes power and money. Pick per span from reach, amplification, and whether the wavelength must traverse a ROADM/OpenROADM line system.", "recommended_action": "For each IPoDWDM link, choose the coherent pluggable from the span budget: 400ZR (fixed 16QAM/CFEC) for unamplified <=~40 km or amplified <=~120 km point-to-point; OpenZR+/ZR+ (oFEC, multi-rate/multi-modulation, ~25 W) for longer amplified spans, ROADM-traversing wavelengths, or where sub-rate multiplexing is needed -- and verify the router port supplies the module\'s power/cooling envelope.", "citation": "OIF 400ZR Implementation Agreement; OpenZR+ MSA Technical Specification; Cisco 400G QSFP-DD Digital Coherent Optics Data Sheet (QDD-400G-ZR-S / QDD-400G-ZRP-S)", "engine_actionable": false}, {"id": "optical-transport-engineer-the-ipodwdm-optical-link-as-a", "domain": "optical-transport", "title": "Engineer the IPoDWDM optical link as a first-class budget (Tx power / OSNR / add-drop) and operate IP and optical as one cross-layer fault domain", "priority": "Medium", "design_intent": "Putting the wavelength on the router does not remove optical-layer engineering -- it relocates ownership to the IP team. Each coherent link must still close an optical budget: tunable channel on the DWDM grid, Tx launch power matched to the line system (ZR/ZR+ launch can be as low as ~-10 dBm, ~0 dBm on newer ZR+), span loss and amplifier/mux-demux plan, and a received-OSNR margin meeting the implementation-agreement floor (e.g. ~26 dB/0.1 nm Rx OSNR for 400ZR), coordinated with the optical line system\'s add/drop port power. Equally, because one physical fault now shows simultaneously as an optical alarm and an IP/routing-adjacency failure, design a cross-layer correlation and assurance model up front (unified inventory + OpenConfig/IETF models, an ACTN-style controller / EPNM-style correlation) so an optical degradation is root-caused as optical, not chased as a routing flap. Validate the cross-layer link (transmit-power-to-receive-power continuity through the add/drop) before declaring it in service.", "recommended_action": "For every coherent IPoDWDM link, produce and verify an optical link budget (grid channel, Tx power vs line-system add/drop, span loss, Rx OSNR margin) at design time, and stand up cross-layer fault correlation (unified IP+optical inventory and assurance, OpenConfig/IETF/ACTN-aligned) so optical degradations are correlated to root cause rather than misdiagnosed as IP instability; gate the link\'s NRFU on a Tx/Rx power-continuity validation through the optical add/drop.", "citation": "IETF ACTN framework (RFC 8453); OIF 400ZR Implementation Agreement (Rx OSNR); Cisco Routed Optical Networking Solution Guide cross-layer fault correlation", "engine_actionable": false}, {"id": "optical-transport-plan-router-host-port-power-thermal-headroom", "domain": "optical-transport", "title": "Plan router host-port power, thermal headroom and faceplate density for coherent pluggables, and unify IP+optical fault/PM under one telemetry plane", "priority": "Medium", "design_intent": "Collapsing the optical layer into the router shifts two burdens onto the router: power/heat and operations. A 400ZR draws roughly a 15W envelope and OpenZR+ up to 25W per port, far above a grey QSFP-DD, so not every faceplate port can host a coherent optic at full reach without exceeding the line card\'s per-port power and cooling budget and de-rating density. Plan supported-slot/port placement and thermal headroom up front. Operationally, once the transponder is gone there is no separate optical EMS to raise alarms: the router must source optical PM and coherent alarms (Rx power, OSNR, pre/post-FEC BER, Q-margin) via streaming telemetry and model-driven (YANG) interfaces, and fault correlation between the IP layer and the line/ROADM system must be designed deliberately so an optical degradation is not misdiagnosed as a routing fault.", "recommended_action": "Validate per-port power/thermal and supported-slot rules before populating coherent optics (don\'t assume every 400G port takes a ZR+ at full reach); and stand up a single IP+optical telemetry/alarm model (streaming optical PM + coherent alarms with IP-to-line-system fault correlation) instead of a separate optical EMS.", "citation": "Cisco Routed Optical Networking Solution Guide Rel 4.0 / Routed Optical Networking HLD (xrdocs.io) -- ZR/ZR+ power classes, host placement, model-driven management; OpenZR+ MSA white paper (15W vs 25W module power targets)", "engine_actionable": false}, {"id": "storage-fabric-isolate-fc-fabrics-into-vsans-and-zone", "domain": "storage-fabric", "title": "Isolate FC fabrics into VSANs and zone by stable WWN identity (device-alias / smart-zoning), never by switch port", "priority": "Medium", "design_intent": "Beyond the physical A/B air-gap, partition each fabric into VSANs so that multiple logical fabrics (and their independent FSPF, zoneset, domain-ID and fabric services) ride shared director hardware without a control-plane fault in one VSAN propagating to another. Bind zone membership to the end-device\'s port-WWN through a device-alias, not to a physical switch port or FCID, so a recabling or HBA replacement does not silently break or widen access; and use single-initiator (or smart) zoning so one initiator\'s fault domain stays one zone. This is the access-control and fault-isolation layer that sits on top of the dual-fabric redundancy already in the KB.", "recommended_action": "Design one VSAN per logical fabric/tenant with an explicitly allocated, non-default domain-ID per VSAN; zone exclusively by pWWN via device-aliases under a documented naming standard; default to single-initiator/single-target zones (or smart zoning to collapse the zone count without losing that property); keep the default VSAN 1 unused for production traffic.", "citation": "Cisco MDS 9000 Series Fabric Configuration Guide (Configuring and Managing Zones; Configuring and Managing VSANs); Cisco Community \'Cisco MDS SAN Zoning Best Practices\'", "engine_actionable": false}, {"id": "storage-fabric-select-core-edge-vs-collapsed-core-san", "domain": "storage-fabric", "title": "Select core-edge vs collapsed-core SAN topology and size ISLs to an explicit storage-to-host fan-out / oversubscription budget", "priority": "Medium", "design_intent": "An FC fabric is engineered to a bandwidth contract, not just a redundancy pattern. Choose a collapsed-core (single-tier, hosts and storage on the same director pair) for port counts a director pair can absorb, and a two-tier core-edge (host/storage edge switches homed to a core) when port density or growth outgrows that -- then size the edge-to-core ISL bundle so the host-edge oversubscription stays within the storage array\'s published fan-out ratio (array port : host port, commonly up to ~12:1 for spinning disk, far tighter for flash/NVMe). Build the ISL as a single SAN port-channel so FSPF sees one logical link with deterministic exchange-based (SID/DID/OX-ID) load-balancing and a member-link failure does not reroute the fabric. This is the SAN-tier capacity/topology decision, separate from both the A/B redundancy principle and the LAN Clos oversubscription rule.", "recommended_action": "Document the target fan-out ratio per storage platform and derive the host-edge ISL port-channel width from it (e.g. an 8:1 budget on a given host-edge defines required ISL Gbps to the core); collapse to a single-tier core only where the director pair holds the full port count with growth headroom; bundle every edge-core link set into one FC port-channel spanning line cards for resilience, and keep the A/B fabrics symmetric in this sizing.", "citation": "Cisco Large SAN Design Best Practices (MDS 9710/9700 directors) white paper; Cisco MDS 9000 Interfaces Configuration Guide (Configuring Port Channels)", "engine_actionable": false}, {"id": "storage-fabric-treat-fc-fabric-merge-e-port-isl", "domain": "storage-fabric", "title": "Treat FC fabric-merge (E-port/ISL bring-up) as a change gate: pre-reconcile zoneset and domain-ID conflicts or the merging fabric isolates", "priority": "Medium", "design_intent": "Bringing up an ISL between two FC switches (or expanding/migrating a SAN) is a fabric MERGE, not a simple link-up: the two switches exchange and reconcile their active zonesets, VSAN configuration and domain-ID assignments, and any conflict (overlapping/static domain-IDs, divergent default-zone policy, incompatible zoneset members) drives the new E-port into an isolated state -- so a careless merge can black-hole storage rather than add capacity. Storage fabric growth and migration must therefore pass a pre-merge reconciliation gate before any E-port is enabled, consistent with the build-before-break, tested-rollback discipline already in the methodology KB.", "recommended_action": "Before enabling any new ISL/E-port between fabrics, capture and diff both sides\' active zoneset, VSAN list and domain-ID allocation; resolve domain-ID overlaps (static, non-conflicting allocation) and default-zone/zoneset policy mismatches first; stage the merge in a maintenance window with a defined rollback (shut the E-port) and verify the merged fabric\'s zoneset activated cleanly and no switch isolated.", "citation": "Cisco MDS 9000 Series Fabric Configuration Guide (zone-merge / zoneset-activation behavior); Cisco MDS 9000 Interfaces Configuration Guide (E-port/TE-port and port-channel formation)", "engine_actionable": false}, {"id": "storage-fabric-rocev2-nvme-of-demands-an-engineered-lossless", "domain": "storage-fabric", "title": "RoCEv2 / NVMe-oF demands an engineered lossless fabric: dedicated no-drop PFC class + ECN/WRED (DCQCN) + jumbo MTU, kept inside a pod", "priority": "Medium", "design_intent": "If NVMe-oF is carried over RoCEv2 (or any RDMA-over-Ethernet storage/AI tier is chosen), the fabric is not optional plumbing -- it must be designed lossless end to end. Map RoCEv2 to a dedicated no-drop class of service and enable Priority Flow Control on that priority so congestion pauses the storage queue instead of dropping it (RDMA collapses on loss). Pair PFC\'s fast hop-by-hop pause with ECN/WRED marking at the leaf and spine so DCQCN throttles senders before buffers fill -- PFC alone risks head-of-line blocking and pause storms, ECN alone reacts too slowly. Provision jumbo MTU consistently on every hop in the no-drop path. Prefer to confine the RoCEv2 domain within a pod / single leaf-spine block (a bridged or contained L2/VXLAN segment) rather than stretching it across summarized L3 boundaries, because the no-drop guarantee, PFC headroom, and buffer engineering are hard to preserve across an arbitrary routed core. This is materially deeper than the KB\'s generic \'DCB + stable L2\' consolidation line.", "recommended_action": "When RoCEv2/NVMe-oF (or an AI/ML RDMA tier) is the target, specify the lossless contract explicitly: a dedicated no-drop CoS with PFC on the RoCEv2 priority, ECN/WRED thresholds at leaf and spine for DCQCN, end-to-end jumbo MTU on every hop, and a pod-bounded RoCEv2 domain; flag any plan that runs RDMA storage over a best-effort or partially-configured fabric as a design risk.", "citation": "Cisco \'Data Center Networking Blueprint for AI/ML Applications\' and \'RoCE Storage Implementation over NX-OS VXLAN Fabrics\' (PFC + WRED-ECN no-drop class); NVIDIA RoCE-over-lossless-fabric (PFC+ECN) guide; DCQCN (SIGCOMM 2015)", "engine_actionable": false}, {"id": "storage-fabric-enforce-san-zoning-with-enhanced-zoning-pwwn", "domain": "storage-fabric", "title": "Enforce SAN zoning with enhanced zoning, pWWN device-aliases and smart zoning -- hard, init-to-target-only, name-based", "priority": "Medium", "design_intent": "Beyond merely \'single-initiator\', specify HOW zoning is enforced. Default to Enhanced Zoning (session-locked, full-database-distributed, validated activation) rather than Basic Zoning, reserve basic only for interop VSANs. Identify members by pWWN device-alias in enhanced (name-native) mode with a strict one-to-one alias-to-pWWN mapping so a device that moves ports keeps its zone membership, instead of brittle switch-port (domain,port) zoning. Use Smart Zoning so one functional zone can hold many initiators and targets while the switch programs ACLs that permit only initiator-to-target adjacencies and silently drop initiator-to-initiator and target-to-target -- collapsing the single-initiator zone explosion without weakening it. Rely on the platform\'s hardware/frame-level (hard) enforcement, not name-server-advisory (soft) zoning, which a host that learns a WWN can bypass.", "recommended_action": "In the LLD mandate enhanced zoning (basic only for interop), pWWN device-alias enhanced mode with 1:1 mapping, and smart zoning for init-to-target-only adjacency; prohibit soft/name-server-only enforcement and (domain,port) member identity for production hosts.", "citation": "Cisco MDS 9000 Series Fabric Configuration Guide (Configuring and Managing Zones; Distributing Device Alias Services); Cisco Community \'Cisco MDS SAN Zoning Best Practices\' (enhanced zoning, device-alias enhanced mode, smart zoning, hard vs soft)", "engine_actionable": false}, {"id": "storage-fabric-cross-vsan-storage-access-route-with-inter", "domain": "storage-fabric", "title": "Cross-VSAN storage access: route with Inter-VSAN Routing, never merge the two VSANs", "priority": "Medium", "design_intent": "When an initiator in one VSAN legitimately needs a target in another (shared tape library, replication appliance, or a phased migration between an old and a new VSAN), grant exactly that adjacency with Inter-VSAN Routing rather than collapsing the two VSANs into one fault domain. IVR virtualises the remote device into the local VSAN via a virtual domain and an IVR zone scoped to the specific pWWNs, distributes the IVR topology over Cisco Fabric Services, and uses service groups to keep IVR control traffic off non-IVR VSANs. The result is selective, audited cross-VSAN reachability that preserves each VSAN\'s separate zone server, domain space and RSCN scope -- the SAN analogue of preferring an L3/routed interconnect over a stretched-L2 merge. Merging VSANs to share one device forfeits isolation permanently and risks a fabric-wide rebuild.", "recommended_action": "In the design, satisfy any cross-VSAN storage requirement with IVR (virtual-domain + pWWN-scoped IVR zones + service groups), explicitly forbidding a VSAN merge as the means of sharing a target; document each IVR adjacency as a reviewed exception to default VSAN isolation.", "citation": "Cisco MDS 9000 Series Inter-VSAN Routing Configuration Guide (Basic Inter-VSAN Routing Configuration: IVR virtual domain, IVR zones, CFS-distributed IVR topology, service groups)", "engine_actionable": false}, {"id": "ddi-ipam-front-critical-infrastructure-services-dns-ntp-aaa", "domain": "ddi-ipam", "title": "Front critical infrastructure services (DNS/NTP/AAA) on a service anycast VIP, scoped local-IGP inside the site and global-BGP only across sites", "priority": "Medium", "design_intent": "For stateless or near-stateless infrastructure services (recursive/authoritative DNS first, also NTP, RADIUS/TACACS, syslog collectors), assign one shared service address (a dedicated /32 host route, /128 for IPv6) to several independent server instances rather than handing clients a single unicast resolver IP or a hand-maintained primary/secondary list. Deploy at least a few instances per service so a single node loss simply re-routes to the next-nearest one with no client reconfiguration. Scope the anycast deliberately: inside a site/DC use the IGP, which can carry the bare host route with no covering aggregate and gives sub-second proximity failover; only across sites/AS boundaries does BGP enter, where the host route needs a route that will survive import filters and where Local-instance-to-Global-instance is the intended fail-over path. This is a different construct from the distributed anycast GATEWAY (EVPN/IRB first-hop routing) and from Anycast-RP (multicast) already in the KB -- it is an application-service VIP, not a default gateway or an RP.", "recommended_action": "(Design) Define a target-state services-addressing plan: a dedicated anycast /32 (and /128) per critical service, advertised from >=2-4 instances; specify IGP-scoped anycast within each site (host route, no summarization that would swallow or mask the /32) and reserve BGP for the inter-site/global scope with a filter-surviving advertisement and an explicit Local->Global failover order. Migrate clients/DHCP options to the anycast VIP rather than per-server unicast IPs. Document the service prefix(es) as protected host routes that must never be aggregated away at the distribution/core boundary.", "citation": "IETF RFC 4786 / BCP 126 \'Operation of Anycast Services\' (sec. 4.2-4.3 local-IGP vs global-BGP scope, host route vs covering prefix); RFC 3258 \'Distributing Authoritative Name Servers via Shared Unicast Addresses\'; RFC 9199 \'Considerations for Large Authoritative DNS Server Operators\'", "engine_actionable": false}, {"id": "ddi-ipam-couple-the-anycast-service-advertisement-to-a", "domain": "ddi-ipam", "title": "Couple the anycast service advertisement to a real service health check (route health injection) and damp advertise/withdraw oscillation", "priority": "Medium", "design_intent": "An anycast service VIP is only as good as the signal that withdraws it when the local instance is sick. The load-bearing discipline is route health injection: the node advertises the service /32 ONLY while a local health check proves the actual service is answering (e.g. a real DNS query succeeds, not merely that the daemon\'s TCP port is open or the loopback is up), and withdraws the route the moment the service fails -- otherwise the node keeps attracting the nearest clients into a black hole because routing has no idea the application died. Equally important, the design must damp flapping: a minimum dwell after a withdrawal before re-advertising, plus aggressive flap-dampening of the service prefix close to the origin, so a half-dead instance does not oscillate the whole anycast cloud. Without these two halves, anycast is strictly worse than a static resolver list because failures hide behind a still-advertised route.", "recommended_action": "(Design) Specify, per anycast service, a health-injection contract: an application-level probe (functional DNS/NTP/AAA transaction, not just port/loopback liveness) that gates the route advertisement via the routing daemon (BIRD/FRR conditional advertise, or interface/next-hop tracking), withdraw-on-failure semantics, a minimum re-advertise dwell timer to prevent rapid oscillation, and origin-proximate flap-dampening of the service prefix. Call out monitoring that is per-instance (observed availability varies by client location, so a single external probe can look healthy while a regional instance black-holes).", "citation": "IETF RFC 4786 / BCP 126 \'Operation of Anycast Services\' (sec. 4.4.1 availability triggers advertisement / non-availability triggers withdrawal + minimum re-advertise delay; sec. 4.4.4 origin-proximate flap-dampening; client-location availability caveat)", "engine_actionable": false}, {"id": "ddi-ipam-give-every-endpoint-bearing-subnet-a-redundant", "domain": "ddi-ipam", "title": "Give every endpoint-bearing subnet a redundant DHCP path: dual relay destinations + a server-failover backend, never one helper", "priority": "Medium", "design_intent": "A subnet whose default gateway forwards DHCP to only one server (a single ip helper-address / relay destination), or to none, is a silent single point of failure: lease renewal and onboarding stop the moment that one server or path is unreachable. Leading practice is to forward each broadcast in parallel to at least two DHCP servers that share the scope through a failover/HA backend, so either server can answer. Treat any endpoint-bearing VLAN whose gateway has fewer than two distinct DHCP relay destinations as a DHCP-availability gap to remediate before cutover, and an SVI with endpoints but zero relay destinations (and no server on-segment) as a hard finding.", "recommended_action": "From the collected relay configuration, count distinct DHCP relay destinations (ip helper-address / forwarding targets) per gateway SVI; cross-reference against endpoint-bearing VLANs. Flag endpoint-bearing subnets whose gateway has 0 relay destinations (DHCP black-hole risk) as Critical/High and those with exactly 1 (no DHCP redundancy) as Medium, citing the specific SVI/VLAN. Recommend a second relay destination plus a failover/HA pairing on the server side.", "citation": "Cisco IOS IP Addressing: DHCP Configuration Guide -- DHCP Relay Agent (multiple \'ip helper-address\' forwards a copy to each server); ipSpace.net \'DHCP Relaying with Redundant DHCP Servers\'", "engine_actionable": false}, {"id": "ddi-ipam-choose-the-dhcp-server-redundancy-model-deliberately", "domain": "ddi-ipam", "title": "Choose the DHCP server-redundancy model deliberately -- stateful failover/HA over split-scope -- and verify DHCPv6 has its own (RFC 8156) story", "priority": "Medium", "design_intent": "DHCP server availability is a first-class design decision, not an afterthought of pointing a relay at two boxes. The strongest model is a stateful failover/HA pair sharing one scope (ISC DHCP failover or Kea HA / Windows DHCP failover), where either server can serve and renew any lease and one transitions to partner-down on failure -- governed by Maximum Client Lead Time (MCLT) and a load-balancing-vs-hot-standby choice (RFC 3074 hashing splits the clients). Split-scope (e.g. 80/20 or 50/50 across two independent servers) is the weaker fallback: it gives no lease continuity and breaks once the pool is highly utilized. Critically, IPv4 failover does NOT cover IPv6: ISC DHCP is DHCPv4-only, so a dual-stack design must pick a backend (e.g. Kea) that implements DHCPv6 failover per RFC 8156 or it has redundant v4 and a single-point-of-failure v6.", "recommended_action": "In the target-state addressing/DDI design, specify the DHCP redundancy model explicitly (failover/HA pair vs split-scope), the mode (load-balancing vs hot-standby) and MCLT, and confirm the chosen server platform provides DHCPv6 failover for every dual-stack scope -- not just DHCPv4. Avoid split-scope where pool utilization is high.", "citation": "RFC 8156 \'DHCPv6 Failover Protocol\' & RFC 7031 \'DHCPv6 Failover Requirements\'; RFC 3074 \'DHC Load Balancing Algorithm\'; ISC KB \'Kea High Availability vs. ISC DHCP Failover\'", "engine_actionable": false}, {"id": "ddi-ipam-make-the-relay-path-fhrp-aware-and", "domain": "ddi-ipam", "title": "Make the relay path FHRP-aware and the snooping/Option-82 trust boundary coherent, so the gateway pair does not double-relay or drop legitimate DHCP", "priority": "Medium", "design_intent": "Two failure modes live at the relay edge. (1) When DHCP relay runs on a redundant first-hop pair (HSRP/VRRP), BOTH gateways relay the same broadcast by default, sending duplicate DISCOVER/REQUESTs to the failover server and producing inconsistent lease durations and offers; the design must make relay FHRP-aware so only the active gateway relays (and uses a stable source so the reply returns) -- not naively enable ip helper-address on both. (2) Where access switches run DHCP snooping and insert Option-82, the upstream relay/server trust model must agree: snooping drops Option-82 frames arriving on untrusted ports, and a relay receiving Option-82 with a zero giaddr discards it unless explicitly told to trust it (\'ip dhcp relay information trusted\'). A mismatched trust boundary silently black-holes legitimate DHCP. Design the relay and the snooping/Option-82 policy as one coherent trust plane.", "recommended_action": "In the relay design, specify FHRP-aware DHCP relay on redundant gateways (active-only relay with a deterministic source/return path) rather than independent helper-addresses on both peers; and define one Option-82 trust policy end-to-end -- snooping trusted/untrusted port roles at the access edge reconciled with \'relay information trust-all/trusted\' and the server\'s Option-82 handling -- so legitimate requests are neither duplicated nor dropped.", "citation": "Cisco IOS \'HSRP-Aware DHCP Relay\' and \'DHCP Relay Server ID Override and Link Selection (Option 82) Suboptions\' configuration guides; Cisco DHCP Snooping configuration guide (Option-82 trusted/untrusted ports, \'ip dhcp relay information trusted\')", "engine_actionable": false}, {"id": "ddi-ipam-build-the-ipam-addressing-plan-as-a", "domain": "ddi-ipam", "title": "Build the IPAM addressing plan as a topology-aligned, summarizable CIDR/VLSM hierarchy (region -> site -> tier) so it aggregates at every routing boundary", "priority": "Medium", "design_intent": "An IPAM that is to serve as the addressing source-of-truth must encode a hierarchical, classless plan whose block boundaries line up with the routing topology — a contiguous region block subdividing into per-site blocks subdividing into per-tier/per-VLAN subnets — so that each aggregation point (site edge, distribution, area boundary) can advertise a single summary instead of scattered host routes. The plan should be VLSM-right-sized per segment (host subnets no larger than the endpoint count needs) yet allocated from contiguous parent ranges reserved with growth headroom, and infrastructure/static ranges carved out of the dynamic DHCP pools. This is the CIDR aggregation strategy applied to enterprise IPAM: a flat or randomly-scattered allocation cannot be summarized and inflates every routing table and the migration\'s re-addressing effort. The target plan itself is a design decision driven by the site/region hierarchy and growth forecast, which are business inputs, not state on the wire.", "recommended_action": "When authoring/target-state addressing, structure the IPAM plan as contiguous nibble-or-CIDR-aligned parent blocks per region and site that summarize at aggregation boundaries, VLSM-size each segment to its host count, reserve static/infrastructure ranges out of DHCP scopes, and prefer re-addressing scattered legacy subnets into the hierarchy over porting a non-summarizable scatter. (Doctrine: the engine can observe current subnet scatter but cannot derive the intended region/site hierarchy or growth target — those are uncollected business inputs.)", "citation": "RFC 4632 (obsoletes RFC 1519) \'Classless Inter-domain Routing (CIDR): The Internet Address Assignment and Aggregation Plan\'; RFC 1518 \'An Architecture for IP Address Allocation with CIDR\'", "engine_actionable": false}, {"id": "observability-define-reliability-as-sli-slo-error-budget-contracts", "domain": "observability", "title": "Define reliability as SLI/SLO/error-budget contracts, not \'five-nines everywhere\'", "priority": "Medium", "design_intent": "Express each user-facing service\'s reliability as a Service Level Indicator (a good-events / total-events ratio over a rolling window: availability, latency-under-threshold, loss), set an explicit Service Level Objective target per service tier, and derive the error budget as 100% minus the SLO. Treat the remaining budget as a finite currency that gates change: spend it on feature/migration velocity while healthy, and freeze non-reliability change when it is exhausted. This replaces vague \'highly available\' aspirations with a measurable, tier-differentiated target and an objective, pre-agreed decision rule shared by engineering and the business.", "recommended_action": "For the target-state design, attach an SLI definition (the exact good/total ratio and window) and an SLO target to each critical service tier, and write an error-budget policy that states what happens to change-freeze and release cadence as the budget depletes. Differentiate targets by tier rather than applying one number fleet-wide. Capture these as named requirements so the deliverables carry the reliability contract, not just the topology.", "citation": "Google SRE Book, \'Service Level Objectives\'; The Site Reliability Workbook, \'Implementing SLOs\' (sre.google)", "engine_actionable": false}, {"id": "observability-alert-on-multi-window-multi-burn-rate-error", "domain": "observability", "title": "Alert on multi-window, multi-burn-rate error-budget consumption, not on raw threshold crossings", "priority": "Medium", "design_intent": "Page on how fast the error budget is being consumed rather than on instantaneous metric thresholds. A single static threshold either fires noisily on harmless blips or detects sustained degradation too late. Pair a fast-burn alert (a short and a long window that must both breach a high burn-rate multiple, e.g. consuming a few percent of a 30-day budget in an hour) with a slower-burn ticket alert (a multi-hour/day window at a lower multiple). Requiring both the short and long window of a tier to be active simultaneously gives fast detection of acute outages while suppressing false positives from transient spikes, and the slow tier still catches a low-grade chronic burn that never trips the fast tier.", "recommended_action": "Design the observability alerting as a small set of burn-rate tiers, each with two windows (short approximately one-twelfth of the long), tied to the service\'s SLO: a high-burn-rate pair that pages, and a low-burn-rate pair that opens a ticket. Tune burn-rate multiples and windows to the SLO target and acceptable alert volume, and make resetting/recovery explicit. Avoid raw per-counter threshold alarms as the primary reliability signal.", "citation": "Google The Site Reliability Workbook, \'Alerting on SLOs\' (multiwindow, multi-burn-rate alerting), sre.google/workbook", "engine_actionable": false}]')
DOCTRINE.extend(_WAVE2_GAP_ADDENDUM)


# ---------------------------------------------------------------------------- coverage honesty
# `engine_actionable` MUST mean "design_advisor.compute_design_blueprint emits a decision for this
# principle's observed trigger". The following are valuable doctrine the HLD / chat can still cite,
# but the advisor does NOT auto-detect their trigger from collected evidence today -- either the
# trigger needs a requirements register (a target-state CHOICE, not an observation), or it shares
# evidence already owned by another detector, or no dedicated finding is collected. So they must not
# CLAIM auto-detection. Demoting here keeps the design brain coverage-honest about its own reach.
# Locked by tests/test_design_blueprint.py::test_every_engine_actionable_principle_is_emitted.
# (The two DC-fabric CHOICES -- dc-three-tier-vs-collapsed-core and dc-spine-leaf-evpn-vs-collapsed --
# ARE engine-actionable, but as REQUIREMENT-GATED decisions: design_advisor._NEEDS surfaces them as open
# design questions and flips them to recommended once a growth horizon is supplied. They are not listed
# below because the advisor does emit them.)
_NOT_YET_AUTO_DETECTED = {
    "dc-igmp-snooping-and-app-delivery",            # same multicast evidence drives multicast-security-and-l2-edge
    "modularity-fault-domains-replicable-blocks",   # same flat-L2 evidence drives dc-restrict-vlan-span
    "security-aaa-routing-auth-antispoof",          # AAA drives mgmt-secure-protocols; routing-auth/uRPF not collected
    "security-l2-access-edge-suite",                # no port-security / BPDU-guard / DHCP-snooping finding collected
}
for _p in DOCTRINE:
    if _p.get("id") in _NOT_YET_AUTO_DETECTED and _p.get("engine_actionable"):
        _p["engine_actionable"] = False


def all_principles():
    """Every doctrine principle (list of dicts)."""
    return list(DOCTRINE)


def by_id(pid):
    """The principle with this id, or None."""
    for p in DOCTRINE:
        if p.get("id") == pid:
            return p
    return None


def by_domain(domain):
    """All principles in a domain (methodology/igp/bgp/qos/...)."""
    return [p for p in DOCTRINE if p.get("domain") == domain]


def engine_actionable():
    """Principles whose trigger the assessment engine can detect from snapshot evidence."""
    return [p for p in DOCTRINE if p.get("engine_actionable")]


def axis(key):
    """A trade-off axis descriptor by key, or None."""
    for a in TRADEOFF_AXES:
        if a.get("key") == key:
            return a
    return None
