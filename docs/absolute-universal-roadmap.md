# The Absolute-Universal Roadmap

*Goal: evolve the engine from a Cisco L1–L4 migration-assessment toolkit into an **absolute-universal
network-assessment platform** — able to assess **any** enterprise's network regardless of vendor, domain,
or how the evidence arrives — while never breaking the prime doctrine: **coverage-honesty** (fire only on an
observed, genuinely-broken state; "not observed" is never "healthy").*

Status: **foundation reconciled against code (2026-06-24); breadth waves grounded in the deep-research marathon.**
Baseline: **778 engine tests green**, canonical [HISTORY-REDACTED] fleet steady (the universality additions are coverage-honest
and silent on [HISTORY-REDACTED]).

---

## 1. What "absolute universal" means — five orthogonal axes

Universality is not one lever. The engine today is *deep on one vendor, two channels, one domain*. "Absolute
universal" is the product of **five independent axes**, each a multiplier:

| Axis | Today | Absolute-universal target |
|---|---|---|
| **A. Vendor breadth** | Cisco only (IOS/IOS-XE/NX-OS + Cisco controllers) | Arista, Juniper, Fortinet, Palo Alto, F5, Aruba/HPE, Nokia, … |
| **B. Architecture-class depth** | headline detector per class; deep per-class worklist mostly open | full senior-grade depth per class (the 278-item gap register) |
| **C. Ingestion-channel breadth** | SSH `show`-text + JSON controller-REST | + NETCONF/YANG, RESTCONF, gNMI/OpenConfig telemetry, SNMP |
| **D. Domain breadth** | on-prem campus / DC / WAN / SP | + public cloud (AWS/Azure/GCP), virtual/SDN (NSX), Kubernetes CNI |
| **E. Source-of-truth / intent** | evidence-only, single-snapshot | + SoT reconciliation (NetBox/Nautobot), IaC/intent-vs-actual |

The headline gap is **Axis A (vendor breadth)**: the engine literally cannot read a non-Cisco device. That is
the single fact that makes "universal" untrue today, and the highest-leverage axis to move first.

---

## 2. Current-state reconciliation (what's actually built, 2026-06-24)

The architecture is a clean, extensible pipeline — the same shape for every architecture class:

```
collect (COMMANDS_NXOS/IOS  or  rest_collect.py)
  → parse_*(text|json)            cisco_toolkit/parse.py        (tolerant regex / json.loads)
  → build_*(cmd_to_file)          cisco_toolkit/build.py        (_load_cmd_output + _safe_parse, fail-soft → {})
  → snap[<axis>]                  COLLECT_PARSE assembly        (one source of truth per axis)
  → _signals(snap)                design_advisor.py:143         (flatten axes into sig{})
  → _d_*(snap, sig)               design_advisor.py:1189-2823   (~70 coverage-honest detectors)
  → _ARCH_COVERAGE_REGISTRY       design_advisor.py:4111        (axis→label→channel→principle-ids)
  → compute_architecture_coverage design_advisor.py:4138        (observed / clean / not-observed SSOT)
  → deliverables + explorer + AssessHub  (all READ the SSOT — never re-derive)
```

**Coverage today — 23 architecture classes in `_ARCH_COVERAGE_REGISTRY`, ~40 arch-class detectors, across two
channels:**

- **SSH show-text (Cisco):** FHRP, VXLAN-EVPN (NVE/EVPN/VNI), CoPP, PIM, IPv6-FHS, NTP, port-security,
  storm-control, QoS-runtime, shadow-infra, SP/MPLS (LDP/L3VPN/L2VPN), SD-Access LISP, TrustSec/CTS, DMVPN,
  IPsec, BFD, IPv6 (DAD + OSPFv3/BGP), **firewall HA + resource capacity (ASA/FTD)**.
- **JSON controller-REST (Cisco):** ACI/APIC, Catalyst SD-WAN/vManage, ISE, FMC.

**The reconciliation insight:** the 2026-06-22 gap register (`docs/universality-gap-register.md`, 12 classes /
278 build items) is now **partially stale** — since it was written, ACI, SD-WAN, ISE, FMC, firewall-HA and the
switch-native classes were all built. But what was built is the **headline detector per class**. The **deep
per-class worklist remains substantially open** (Axis B), and **nothing crosses the Cisco boundary** (Axis A).

**The Cisco-coupling seams** (where breadth must extend) are narrow and well-isolated:
- `COLLECT_PARSE_V3_23_0.py:480` — `NETMIKO_TYPE = {"nxos":"cisco_nxos","ios":"cisco_ios"}` (live-SSH driver map)
- `COLLECT_PARSE_V3_23_0.py:713` — `detect_platform_from_files()` (offline NOS detection → `nxos`/`ios`)
- `COLLECT_PARSE_V3_23_0.py:1036-1062` — `plat_map` (devices.json `platform`/`os`/`nos` → normalized value)
- Per-device **`platform`** field already threads end-to-end — it is simply constrained to Cisco values today.

**Critical enabler:** the **offline channel** (`cisco-assess --no-collect --collection-dir <dir>`) reads captured
text/JSON per device dir and dispatches `build_*`. A new vendor can be added **entirely offline** — a new
`platform` value + `parse_<vendor>_*` + `build_<vendor>_*` + detector + registry entry — with **zero live-driver
risk**, exactly how the ACI/SD-WAN/ISE/FMC JSON channels were added. This is the safe path to multi-vendor.

---

## 3. Axis B — the Cisco-depth backlog (reconciled: built vs still-open)

Per-class, what the headline detector already covers and what senior-grade depth remains (from the gap register,
reconciled against the current `_d_*` inventory):

| Class | Built (headline) | Still open (senior depth) |
|---|---|---|
| **VXLAN-EVPN** | NVE-peer / EVPN-RR / VNI down; `_d_vpc_health` | **FEX** resilience; **vPC consistency-parameters** (split-brain PKL-on-peerlink, Type-1/2 mismatch); **anycast-gateway** consistency |
| **FHRP** | presence, split-brain, resilience (no-track / no-preempt) | **election** (equal-priority), **tracking-wired** proof (`show track` subscriber), **peer-consistency** (v1/v2, VIP, timers, auth) |
| **IPv6** | DAD duplicate; OSPFv3/BGP adjacency | **silent-FHS** (IPv6 up at access edge, zero RA-guard/DHCP-guard/ND-inspection — the headline IPv6 gap); non-/64 hygiene |
| **Multicast** | PIM RP resilience | **RPF integrity** (Null IIF — #1 mcast outage), **MSDP** liveness, **mrouter-aware** querier-gap |
| **SP/MPLS** | LDP / VPNv4 / L2VPN session down | **RD/RT integrity** (VPNv4/v6/EVPN), **SR SRGB** homogeneity, **TI-LFA** coverage (RFC 9855) |
| **SD-Access** | LISP session partition; CTS env-data | **fabric roles** (edge/border/CP), **CP/border redundancy**, **fabric MTU 9100**, **SGACL enforcement-counters** |
| **QoS run-state** | egress queue/policer drops | **marking** (RFC 4594/medianet), **unbounded LLQ** (priority w/o police), **conditional-trust** at phone edge, **PTP run-state** role |
| **WAN overlays** | DMVPN tunnel, IPsec crypto-session | **GETVPN** (GDOI), **FlexVPN**, **PfRv3** path-control |
| **Mgmt / Assurance** | config-plane hardening, CoPP | **NETCONF/RESTCONF/gNMI/MDT** observability posture |

These are **DEPTH within Cisco** — high-value and low-risk (the pattern exists, no new-vendor format fidelity
risk), but they do **not** move the "universal" needle on their own. They are the steady backlog, sequenced
**after** the breadth keystone proves the platform is multi-vendor.

---

## 4. The extension contract (every new capability obeys it)

Any new vendor / class / channel ships as a **vertical slice** that obeys the same contract — this is what keeps
"universal" from becoming "broad but wrong":

1. **Offline-first.** Read captured evidence via `_load_cmd_output`; never require a live device to *analyze*.
2. **Fail-soft & coverage-honest.** `build_*` returns `{}` when the feature/vendor is absent; the detector stays
   **silent** (never "healthy") on absent/healthy/transient/benign state. The cry-wolf trap is excluded by design.
3. **Test-first against REAL output.** Fixtures are verified against genuine vendor output (the
   parser-format-fidelity lesson — self-authored fixtures hide format blindness). Each detector has a
   *fires-on-broken* **and** *silent-on-clean* test, plus the fuzz/robustness gate.
4. **One source of truth.** Publish a single `snap[axis]`; register it in `_ARCH_COVERAGE_REGISTRY`; every surface
   READS it. No client-side re-derivation.
5. **Non-disruptive.** The canonical [HISTORY-REDACTED] fleet's decision count is unchanged (the addition is silent on evidence
   it didn't collect — proven each slice).

---

## 5. Axis A — vendor breadth (THE headline lever)

The pattern is a **vendor adapter**: each new NOS is `platform` value + `parse_<vendor>_*` + `build_<vendor>_*`
+ coverage-honest detector(s) + registry entry, **offline-first** (no live driver needed to *analyze*). The
detector layer, coverage SSOT, deliverables and dashboards are reused unchanged — only the parse/build front
edge is vendor-specific. Priority order (market presence × closeness-to-Cisco × assessment value):

| Wave | Vendor | First detector(s) — the headline redundancy/false-health trap | Structured access |
|---|---|---|---|
| **1a ✅ DONE** | **Arista EOS** | **MLAG degraded** (vPC analogue; configSanity-inconsistent / peer-link-down / single-homed ports) | `show … \| json` / eAPI (JSON-native → robust `json.loads`) |
| **1b ✅ DONE** | **Arista EOS** | **BGP-EVPN peer not Established** (`show bgp evpn summary` — the NX-OS EVPN-RR analogue) — VXLAN config-sanity / interface counters remain | same JSON channel — same device |
| **2 ✅ DONE** | **Juniper Junos** | **SRX chassis-cluster HA degraded** (`show chassis cluster status` — priority-0 "not ready" trap / monitor-failures / lost node; the Cisco-firewall-failover analogue) — Virtual-Chassis / interface drops remain | `\| display json` (the `[{"data":v}]`-wrapped dialect) |
| **3 ✅ FortiGate** | **Fortinet** ✅ / Palo Alto / F5 | **FortiGate HA cluster out-of-sync** (`get system ha status` — a config-checksum-mismatch standby holds a divergent ruleset; the Cisco-ASA-failover analogue) ✅; Palo Alto + F5 + capacity remain | `get system ha status` (CLI) / FortiOS REST / PAN-OS XML / F5 iControl |
| 4 | Aruba/HPE AOS-CX, Nokia SR OS/SR Linux | VSX / SRL redundancy; later | AOS-CX REST; gNMI/OpenConfig |

Every adapter obeys the §4 extension contract (offline, fail-soft, coverage-honest, test-first vs **real**
vendor output, one SSOT). The keystone (Arista MLAG) is shipped and proven (§10).

## 6. Axis C — channel breadth (NETCONF / RESTCONF / gNMI / OpenConfig)

The structured, vendor-neutral path that scales breadth without per-vendor regex. **OpenConfig-over-gNMI** is
the lever: a single normalized model (interfaces, LLDP neighbors, routing, redundancy, counters) supported in
production across Arista EOS, Cisco IOS-XR/XE/NX-OS, Juniper and Nokia. RESTCONF (RFC 8040) and NETCONF
(RFC 6241) are the request/response cousins; IETF YANG (`ietf-interfaces`, `ietf-network-instance`) is the
standards-body baseline where OpenConfig coverage is thin.

Plan: an **offline OpenConfig-JSON reader** reusing the exact "read an exported JSON file" pattern the
controller channels use, plus a thin **normalization layer** mapping vendor-native → the common device model.
Most telemetry value is live, so the offline entry ingests **exported** gNMI/NETCONF dumps; a `rest_collect`-style
read-only gNMI/RESTCONF collector is the live front door (opt-in, GET/Subscribe-only, dedicated RO account —
same safety doctrine as the existing REST collectors). This is the bridge that makes adding vendor #6, #7, #8
cheap.

## 7. Axis D — domain breadth (cloud / virtual / SDN)

> **✅ FIRST CLOUD AXIS SHIPPED:** `_d_cloud_sg_open_ingress` — an AWS security group open from `0.0.0.0/0`
> (or `::/0`) to an admin/DB/all port (CIS AWS 5.2/5.3; silent on a legit 80/443 web tier). Proves the engine
> extends beyond on-prem to **public cloud** via the same offline JSON pattern (account-as-device). Azure
> Resource Graph / GCP Cloud Asset Inventory / AWS Network Access Analyzer (reachability) extend the same class.

Cloud is "just another JSON channel." Each hyperscaler exposes a **read-only inventory/assessment export** that
drops into the offline pipeline:

- **AWS** — Config advanced-query / `describe*` (VPC, SecurityGroup, RouteTable, TransitGateway, Subnet, NAT),
  and **Network Access Analyzer / VPC Reachability Analyzer** (automated-reasoning reachable-path findings — the
  cloud equivalent of the engine's L1–L4 reachability).
- **Azure** — Resource Graph (KQL) over VNet/NSG/Virtual-WAN; Network Watcher.
- **GCP** — Cloud Asset Inventory; Network Intelligence Center.
- **Virtual/SDN** — VMware NSX-T DFW (any-any rule), Kubernetes `NetworkPolicy` (a namespace with **zero**
  policies = default-allow).

Candidate detectors (all coverage-honest, surface-OPEN-not-vulnerable): **0.0.0.0/0 ingress exposure** (CIS),
**AZ-spread SPOF** (all subnets in one AZ), transit/peering topology gaps, **quota/capacity** headroom, default
security-group in use. One unified cloud-config reader normalizing the three providers' JSON into a common
`account/region/resource/exposure/az` model unlocks all three at once.

## 8. Axis B — class depth (the Cisco gap-register backlog)

Detailed in §3. Sequenced by value once the breadth keystones land: **vPC consistency-parameters**
(split-brain / Type-1 mismatch) → **FHRP detail** (election/tracking/peer-consistency) → **IPv6 silent-FHS** →
**multicast RPF + MSDP** → **SR SRGB / TI-LFA** → **SD-Access fabric roles** → **QoS run-state** (marking /
unbounded-LLQ / PTP). These are low-risk (pattern exists, no new-vendor format risk) and run as the steady
backlog in parallel with breadth.

## 9. Build vs leverage — the parser-ecosystem decision

For non-Cisco **show-text** (where a vendor isn't JSON-native), do **not** hand-roll tolerant regex per vendor
from scratch — **leverage `ntc-templates` (TextFSM)**: broad multi-vendor coverage, parses a captured string
**offline** (no live connection), permissive license — ideal for the engine's offline model. Use **NAPALM
getters** as the reference schema for the normalization layer (NAPALM itself is mostly live-driver, so it's a
design reference, not a runtime dependency). For JSON-native platforms (Arista eAPI, all controllers), keep the
hand-rolled `json.loads` adapters (robust, zero-dep, full control — as the Arista keystone proves). The
coverage-honest **detector layer stays vendor-agnostic** regardless of how the evidence was parsed.

> *Decision:* hybrid — `json.loads` adapters for JSON-native sources; `ntc-templates` as the show-text backbone
> for regex-heavy vendors; NAPALM as the normalization-schema reference. Revisit per the research verdicts (§12).

## 10. The executed keystone (proof the plan is real) ✅

**Arista EOS MLAG** — the first non-Cisco vendor axis, shipped this session as a complete vertical slice and
**proven**:
- `parse_arista_mlag` (`show mlag \| json`) → `build_arista` → `_signals` → `_d_arista_mlag_degraded` → KB
  principle (`arista-mlag-domain-degraded`, cited to Arista EOS docs + ANTA) → `_ARCH_COVERAGE_REGISTRY`.
- **Wave 1b (also shipped):** `parse_arista_bgp_evpn_summary` (`show bgp evpn summary \| json`) →
  `_d_arista_evpn_degraded` (fires on a peer not `Established` — the analogue of the Cisco NX-OS
  `_d_evpn_rr_health`), added to the **same `arista` class** (no `n_classes` churn). JSON shape verified against
  ANTA's BGP-summary fixtures (`vrfs.*.peers.*.peerState`). The Arista leaf/spine DC fabric (MLAG + BGP-EVPN)
  is now assessed end-to-end. Full suite **801 green**.
- Coverage-honest: fires on a configured-but-degraded domain (configSanity inconsistent / peer-link down /
  single-homed ports); **silent** on healthy, on the transient `connecting` bring-up, and on `disabled`
  (absence of MLAG is never a finding).
- **Verified:** `tests/test_arista.py` 15/15; **full suite 793 green** (incl. the global emit-invariant + all
  three coverage count-locks); golden diff = **+18 lines, arista-only** (purely additive); the real **[HISTORY-REDACTED] fleet
  steady at 42 decisions** with `arista` *not-observed* (zero [HISTORY-REDACTED] MLAG evidence → 0 new [HISTORY-REDACTED] decisions).
- **Coverage now: 24 architecture classes (20 ssh + 4 json).** The next vendor is mechanical — same slice
  template + the documented count-lock map (`multi-vendor-foundation.md`).

## 11. Sequenced delivery plan

| Wave | Scope | Effort | Risk | Proves |
|---|---|---|---|---|
| **0 ✅** | Arista MLAG keystone | — | low | engine is multi-vendor |
| **1 ✅ core** | Arista BGP-EVPN ✅ + Juniper SRX chassis-cluster ✅ (VXLAN-sanity / Virtual-Chassis / interface counters remain) | M | low-med | **PROVEN: the adapter pattern generalizes to a 2nd NOS** |
| **2 ✅ core** | Multi-vendor firewalls — **Fortinet FortiGate HA ✅** (Palo Alto / F5 + capacity remain) | M | med | **security-edge universality (3rd vendor proven)** |
| **3** | OpenConfig/gNMI offline reader + normalization layer | L | med | the vendor-neutral channel (cheap vendor #6+) |
| **4 ✅ seeded** | Cloud JSON channel — **AWS security-group exposure ✅** (Azure/GCP exposure + AZ-spread SPOF + reachability remain) | L | med | **domain universality proven (on-prem + cloud)** |
| **5** | Class-depth backlog (vPC/FHRP/IPv6-FHS/RPF/SR/SDA/QoS) | L (parallel) | low | senior-grade depth per class |

Each wave is independent, coverage-honest, and non-disruptive to the canonical [HISTORY-REDACTED] fleet (additive axes are
`not-observed` on evidence that doesn't carry them). Vendor/channel breadth (Waves 1–4) is the "universal"
headline; class depth (Wave 5) runs as the steady parallel backlog.

## 12. Research appendix — verified specifics & citations

Deep-research marathon: **6 angles × adversarial verify, 12 agents, ~1.04M tokens, 343 tool-uses.**
**28 load-bearing claims confirmed, 2 refuted, 1 uncertain** against primary/vendor/standards sources.

**Vendor breadth (§5) — the detectors are ports of vendors' own test catalogs.** Arista detectors map 1:1 to
**ANTA** (Arista Network Test Automation), Arista's published, already-coverage-honest device-state catalog
with exact JSON field paths: `VerifyMlagStatus` / `VerifyMlagInterfaces` / `VerifyMlagConfigSanity` (**this is
the keystone — it confirms `_d_arista_mlag_degraded`'s firing logic field-for-field**), `VerifyVxlan1Interface`
/ `VerifyVxlanConfigSanity` / `VerifyVxlanVtep` / `VerifyVxlanVniBinding` (wave 1b), `VerifyInterfaceErrors` /
`Discards` / `ErrDisabled` / `VerifyPortChannels`. Channel: eAPI JSON-RPC (`POST /command-api
{"method":"runCmds"}`) or `show … | json`. Juniper: NETCONF (ncclient) + `| display json`, RPCs
`get-chassis-cluster-status` (SRX HA — the **redundancy-group priority-0** false-health trap) and
`get-virtual-chassis-information` (members `NotPrsnt`). Nokia SR Linux: gNMI/OpenConfig-native. Aruba AOS-CX:
REST v10 GET-only (`selector=status`, `/vsx-peer`), `show vsx status`. *[anta.arista.com; Arista eAPI
whitepaper; juniper.net NETCONF/Junos-XML docs]*

**Security edge (§5 wave 2).** FortiOS `get system ha status` (Configuration Status in-sync/out-of-sync) +
`diagnose sys session stat` (capacity); PAN-OS XML API `type=op` `<show><high-availability><state>` +
session-table; F5 iControl REST `/mgmt/tm`. All mirror the existing Cisco ASA/FTD HA + capacity detectors.

**Channels (§6).** gNMI-OpenConfig collector (Capabilities → Get(STATE)/Subscribe) producing offline
snapshots; a canonical multi-vendor model over `openconfig-interfaces` / `-lldp` / `-network-instance`.
**⚠ CAVEAT (uncertain verdict):** gNMI `Get` is **not universal** — some Juniper platforms (e.g. vMX) support
only `Subscribe`; ship a NETCONF `<get>` / RESTCONF GET fallback. *[RFC 6241; RFC 8040; openconfig.net]*

**Cloud (§7).** A unified reader over **AWS Config** / **Azure Resource Graph** / **GCP Cloud Asset Inventory**;
detectors: 0.0.0.0/0 ingress exposure (SG/NSG/Firewall), **AWS Network Access Analyzer** path ingester
(`GetNetworkInsightsAccessScopeAnalysisFindings` — empty = no violating path), AZ-spread SPOF, K8s zero-policy
default-allow, NSX-T any-any DFW.

**Build-vs-leverage (§9) — verified decision.** **Adopt `ntc-templates` (TextFSM)** as the non-Cisco offline
show-text parse backbone (`parse_output(platform='arista_eos', command='show…', data=…)`), wrapped in a
**coverage-honesty confidence gate** (ParsingException / empty list / all-null row → UNKNOWN, never "healthy").
Use **TTP (MIT)** for long-tail hierarchical parses. **Do NOT** take a runtime dependency on Cisco Genie/pyATS
(pyATS core is closed-source). **Skip NAPALM** for offline (live-driver only) — keep it as the
normalization-schema reference. Keep `json.loads` adapters for JSON-native sources (Arista eAPI, controllers).
Add **embedded Batfish (Apache-2.0)** for config-derived reachability + differential/what-if
(`bgpSessionCompatibility`, `aclReachability`, `differentialReachability`) — the category-parity capability
(Batfish/Suzieq/Forward/IP-Fabric define the "universal" benchmark).

**Reconciled refutations (verify-by-refutation did its job):**
- **REFUTED** "NetBox Assurance is open-source" → NetBox *core* is OSS, but **Assurance** (intent-vs-actual
  reconciliation) is **NOT** in Community Edition (NetBox Labs Enterprise/Cloud only). For SoT reconciliation,
  build natively or use **Nautobot Golden-Config (Apache-2.0)**.
- **REFUTED** "genieparser is Cisco-only" → genieparser (Apache-2.0, parses offline) covers **more than Cisco**;
  still not adopted (pyATS weight), but the constraint assumed was wrong.
- **UNCERTAIN** gNMI `Get` universality → folded into the §6 caveat above (NETCONF/RESTCONF fallback).
