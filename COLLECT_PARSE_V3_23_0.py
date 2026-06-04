#!/usr/bin/env python3
"""
CISCO MIGRATION EXTRACTOR - COLLECT + PARSE + AUTO-POPULATE EXCEL (V3.23.0)

V3.23.0 (additive; health scoring + migration readiness - final intelligence layer):
  * compute_health_scores() + 'Health Scores' sheet (Phase 28): a per-switch 0-100 score with
    weighted deductions synthesised from the physical (L1), L3-forwarding, cross-layer and
    protocol-health findings already computed this run; banded Excellent/Good/Fair/Poor/Critical.
  * compute_migration_readiness() + 'Migration Readiness' sheet (Phase 29): per move-group
    (reusing compute_move_groups) a READY / CAUTION / NOT READY verdict from a 10-check
    pre-migration checklist (uplink + gateway redundancy, cross-layer criticals, err-disable,
    STP, port-channels, routing adjacencies, orphan VLANs, degraded uplinks, device health).
  * Both embedded in the snapshot ('health_scores', 'migration_readiness') and rendered by the
    HTML explorer's new health mode (nodes coloured by score band). Cross-layer findings now
    carry a 'hosts' field for per-device attribution. Pure derivation; no new collection.

V3.22.0 (additive; protocol behavior analysis):
  * compute_protocol_health() + 'Protocol Health' sheet (Phase 27) - one row per
    (switch, protocol) for STP / EtherChannel / VTP / OSPF / BGP / EIGRP / FHRP, each with a
    derived health severity. Re-parses already-collected raw output (STP blocked/inconsistent
    ports, etherchannel member-state flags, VTP mode/revision, OSPF/BGP neighbor states) plus
    the FHRP info on InterfaceData. Adds 'show spanning-tree detail' to collection for STP
    topology-change counts (tolerant: absent output -> TCN omitted). Embedded in the snapshot
    under 'protocol_health'. No new InterfaceData fields, no new imports.

V3.21.0 (additive; cross-layer correlation):
  * build_dependency_map() + compute_cross_layer_correlations() + 'Cross-Layer Analysis'
    sheet (Phase 26). Correlates findings ACROSS layers - it ingests the physical-health (L1)
    and L3-forwarding (L3) records already computed this run, plus topology facts derived from
    the model (articulation via _vlan_components, single-fiber uplinks, single-member port-
    channels, orphan VLANs), and emits CL-01..CL-10 compounded-risk findings (e.g. a single
    fiber that is the only path to a sole gateway = total isolation with no L1 or L3 backup).
    Embedded in the snapshot under 'cross_layer'. Pure derivation; no new collection, no new
    InterfaceData fields, no new imports.

V3.20.0 (additive; L3 forwarding map):
  * 'L3 Forwarding Map' sheet (Phase 25) - one row per gateway SVI: VLAN, SVI IP, FHRP
    protocol/role/virtual-IP (parsed from hsrp_behavior), routing source + next hop +
    primary/secondary subnets, device object-tracking summary, and a derived L3 Risk flag
    (single-gateway / tracked-object-down / no-FHRP / ok). Adds 'show track' to collection
    for object/IP-SLA tracking (tolerant: absent output -> blank). Pure derivation otherwise;
    reuses the existing FHRP parsers and per-SVI routing enrichment. Embedded in the snapshot
    under 'l3_forwarding'. No new InterfaceData fields, no new imports.
    Note: tracked objects are device-level (show track is not bound to a specific SVI without
    parsing HSRP 'standby ... track' config), so the Tracking column is per-device context.

V3.19.0 (additive; full-stack flow trace):
  * trace_full_flow(src_ip, dst_ip, all_interfaces) + optional 'Flow Trace' sheet (written
    only when BOTH --flow-src and --flow-dst are given). Traces an L1->L3 path between two
    endpoint IPs: locates each endpoint's access switch/port/VLAN (end_host_ip), resolves the
    gateway SVI(s) per subnet (svi_ip + subnet_primary_route containment, FHRP peers), decides
    L2-same-subnet vs L3-routed, and walks the fabric over STP-forwarding links (reuses
    _link_carries / build_network_model). Flags single-points-of-failure on the path
    (single-fiber uplinks via _physical_uplink_index, single gateway, VLAN partition) and
    scores risk LOW/MEDIUM/HIGH/CRITICAL. Embedded in the snapshot under 'flow_trace' for the
    HTML explorer's Flow mode. L4 note: no ACL/service-policy data is collected, so transport
    filtering is NOT simulated (path reachability is reported as L1-L3, L4 assumed open).
    Routing is DERIVED from InterfaceData (no standalone routing_data dict exists). No new
    collection, no new InterfaceData fields, no new top-level imports.

V3.18.0 (additive; L1 physical health):
  * 'Physical Health' sheet (Phase 23) - one row per physical port: negotiated speed/duplex/
    media, input/CRC errors, output drops, port-channel, PoE, and a derived Physical Risk flag
    (err-disabled / half-duplex-on-trunk / error-rate-high / single-fiber-uplink / ok). Pure
    derivation from already-parsed data: error counters via parse_show_interface_counters,
    uplink topology via build_network_model (single-fiber), PoE budget via DevicePhysical;
    negotiated duplex/media read from the 'show interfaces' DETAIL block (InterfaceData.duplex
    is normalized and drops half-duplex). Records embedded in the snapshot under
    'physical_health'. No new collection, no new InterfaceData fields, no new imports.

V3.17.0 (additive; consolidation):
  * One run now also emits a self-contained Blast-Radius Explorer ('<output>_explorer.html')
    with the live topology baked in - no more hand-loading the snapshot into a separate HTML
    tool. write_html_explorer() patches a copy of the read-only 'blast_radius_explorer.html'
    template that ships beside this script; '--no-html' suppresses it; a missing template is a
    warning, not a crash. New: Phase 22 (post-save). No new imports, no new InterfaceData fields.

V3.16.0 intelligence layer (additive; deterministic graph reasoning over already-parsed
data - no new collection, no external calls):
  * 'Causality Chains' sheet - root cause -> propagation mechanism -> blast radius, e.g. a
    sole-gateway VLAN with no FHRP, a transit switch that is the only L2 path from some
    endpoints to their gateway, or a single non-bundled uplink that isolates a VLAN.
  * 'Failure Impact' sheet - migration blast-radius simulation: each switch is removed from
    the CDP/LLDP-derived graph and per-VLAN endpoint->gateway reachability is recomputed,
    classifying each VLAN as Hard partition / Backup-covered (STP reconverges via a named
    blocked link) / FHRP-covered (standby gateway) / no impact.
  Limits: graph completeness == CDP/LLDP discovery (off-scan links invisible -> impact is a
  lower bound); reachability simulation, not bandwidth (no traffic-volume telemetry);
  post-failure path is approximate (backup links are proven and named, STP trees are not
  recomputed). See the NEW-V3.16 block above main() for details.

V3.15.0 feature batch (Tier 1 + Tier 2). All additive; the existing interface-build
pipeline (build_interfaces / InterfaceData / the main interface sheet) is unchanged.
  Tier 1 (aggregations of already-parsed data, no new collection):
   * 'Findings' sheet - a risk register cross-referenced from the interface DB:
     no-gateway VLANs, multi-SVI VLANs without FHRP, err-disabled ports, STP-inconsistent
     ports, and native-VLAN/duplex mismatches across confirmed inter-switch links.
   * 'Capacity' sheet - per-switch port and PoE headroom (from DevicePhysical) with
     port-bound / PoE-bound flags, for consolidation planning.
   * Topology diagram - writes topology.mmd (Mermaid) and topology.dot (Graphviz) next to
     the workbook; one-end-only links are drawn dashed. (compute_topology_links() is now the
     shared link builder used by the Topology Links sheet, Findings, and the diagram.)
   * Pre/post-cutover diff - a snapshot JSON (<output>.snapshot.json) is written next to every
     workbook; run with '--compare OLD.json NEW.json' to emit a diff workbook (Summary /
     Interface Changes / Endpoint Changes / SVI Changes). --compare skips SSH and the template.
  Tier 2 (new commands collected on both platforms; parsers are best-effort and blank when a
  platform/feature is absent - _load_cmd_output() already skips command output that errored):
   * 'Interface Health' sheet - input/CRC errors, output drops and last-input/last-output from
     'show interfaces' (IOS) / 'show interface' (NX-OS); flags error ports and up-but-idle ports.
   * 'Security Posture' sheet - port-security, 802.1X/MAB sessions and DHCP-snooping binding
     counts ('show port-security', 'show authentication sessions', 'show ip dhcp snooping binding').
   * 'Routing Adjacencies' sheet - OSPF/EIGRP neighbors and BGP peers ('show ip ospf neighbor',
     'show ip eigrp neighbors', 'show ip bgp summary' / 'show bgp summary').

V3.14.13 fix: per-SVI subnet matching now prefers the CONNECTED route whose prefix contains
  the SVI's own IP, so a coexisting /32 host route or redistributed loopback can no longer be
  picked as the SVI's subnet (seen on a 4500-X VSS where Vlan167/169 matched 10.0.0.60/32
  instead of their connected /24). Connected-and-containing > connected > less-specific.

V3.14.12 platform-resilience hardening (a wrong 'platform' in devices.json was silently
gutting the SVI/routing/HSRP/run-config columns - it ran the NX-OS command set against IOS
Catalyst gear, so NX-only command forms errored and that data was never collected):
FIX-V14-19 collect() now gathers the UNION of IOS+NX-OS command variants (ordered by the
  detected platform). The two lists differ only in platform-divergent forms (show standby vs
  show hsrp, the two run-config forms, show interfaces vs show interface, etc.); collecting
  both means a wrong label no longer drops data - _load_cmd_output() already skips the form
  that errors and keeps the one that worked.
FIX-V14-20 detect_platform_from_files() now treats a command that errored on the wrong
  platform as NOT a valid marker (checks all _CISCO_ERRORS, not just 'invalid'); an IOS
  '% Incomplete command' file was being miscounted as an NX-OS marker.
FIX-V14-21 After collection the platform is re-derived from the actual (non-error) output and
  overrides a wrong devices.json value, so parsing and the Switch Inventory label are correct.
  NOTE: the netmiko driver is still chosen at connect time from the device-file platform, so
  for best results set 'platform' to 'ios'/'auto' (not a wrong value) in devices.json.

V3.14.11 cleanup/quality pass:
CLEAN-V14-16 Removed parse_management_ip_from_neighbors() - orphaned since V3.14.4 (FIX-V14-8
  re-sourced mgmt IP from the switch's own interfaces); it had zero callers.
FIX-V14-17 parse_multicast_info() rewritten: parse the real 'show ip pim interface' table
  (Address/Interface/Ver-Mode) instead of an 'X is up' assumption that never matched it, and
  capture VlanN interfaces in mroute IIF/OIL via a function-local Vlan-aware token regex (the
  global IFACE_TOKEN_RE intentionally excludes Vlan so it can't be widened safely). The
  Multicast Info column now populates on SVIs running PIM instead of staying blank.
FIX-V14-18 HSRP non-brief fallback (m1/m2) now captures the virtual IP via last-IP-on-line,
  the same heuristic as the brief branch, instead of a weak trailing optional that usually
  missed it. (These lines were a live fallback for 'show standby all'-style output, not dead
  code as a prior changelog note implied.)

V3.14.10 adds over V3.14.9:
FEAT-V14-15 New "Topology Links" sheet: physical inter-switch link map built from CDP/LLDP.
  The two parsers now also capture the remote port; each link is de-duplicated across both
  endpoints' views into one canonical undirected row and flagged "Both ends" (seen from both
  switches) or "One end" (only one side reported). Host endpoints (phones/APs/servers) are
  excluded - infrastructure links only. This is the physical map for cutover sequencing and
  also informs the transit-coupling gap noted on the Move Groups sheet.

V3.14.9 adds over V3.14.8:
FEAT-V14-14 New "Move Groups" sheet: proposes migration waves by computing connected
  components of the shared-VLAN graph (switches that share an L2 broadcast domain must move
  together). Captures TRANSITIVE coupling - if VLAN10 spans A+B and VLAN20 spans B+C, then
  A/B/C are one group even though A and C share nothing directly (easy to miss by eye). Each
  row: the switches in the wave, the spanning VLANs that force the coupling, endpoint count,
  gateways, and any redundant STP-blocked paths to verify before cutover. Ordered
  largest-blast-radius first. Coupling uses ACTUAL VLAN presence (access port or SVI),
  consistent with the VLAN Census; trunk-allowed-only transit is not modeled and VLAN 1
  (default) is excluded from grouping (flagged in Notes where it still spans a group).

V3.14.8 adds over V3.14.7:
FEAT-V14-13 Two assessment sheets aggregated from the interface DB (no new parsing risk):
  - "VLAN Census": one row per in-use VLAN (has access ports and/or an SVI) with VLAN id +
    name, switch spread, access-port count, distinct-endpoint (MAC) count, and the gateway
    (which switch holds the SVI, its IP, subnet, FHRP state). The migration move-group unit.
  - "Endpoint Census": flat cross-switch list, one row per port with a learned MAC -
    hostname, port, VLAN(+name), MAC, IP, endpoint type, location, neighbor.
  Also collects 'show vlan brief' and uses it to fill authoritative VLAN names (enriching the
  interface sheet's VLAN Name column too).

V3.14.7 adds over V3.14.6:
FEAT-V14-12 New "STP Detail" Excel sheet: one row per STP port showing WHICH VLANs it
  forwards vs blocks (compressed ranges, e.g. "10,20-23"), instead of only the collapsed
  state on the interface sheet. Surfaces per-trunk blocked VLANs - the redundant/standby
  path per VLAN, key for migration move-group planning. The summary parser was refactored
  to derive from the new per-VLAN detail parser, so the interface-sheet STP state and this
  sheet can never disagree. Under MST the VLAN columns hold MST instance numbers.

V3.14.6 adds/fixes over V3.14.5:
FEAT-V14-10 VRRP and GLBP gateways are now parsed ('show vrrp brief', 'show glbp brief',
  collected on IOS + NX-OS). Previously only HSRP was recognized, so VRRP/GLBP gateways were
  blank. The column is renamed "HSRP Behavior" -> "FHRP Behavior" (the umbrella term for
  HSRP/VRRP/GLBP) and each value is prefixed with the actual protocol (e.g. "VRRP grp 1
  Master VIP ..."). HSRP takes precedence when multiple are present on one interface. The old
  "hsrp behavior" header is still recognized on existing sheets (no duplicate column on re-run).
CLEAN-V14-11 Removed 3 stray backspace (\x08) bytes that had corrupted the detailed-format
  HSRP regexes in parse_hsrp_summary, restoring the 'show standby all' / 'show hsrp all'
  fallback path. Updated stale log-file/logger/usage-example version strings to V3.14.6.

V3.14.5 fixes over V3.14.4:
FIX-V14-9 STP state column no longer claims "Forwarding" from link-up alone (a false-health
  signal: a port can be up but STP-blocked). "Forwarding" is now asserted only when confirmed
  by the per-VLAN Role/Sts table in 'show spanning-tree' (newly collected). Blocked ports come
  from 'show spanning-tree blockedports'; the previously-collected-but-unused
  'show spanning-tree inconsistentports' is now honored as "Inconsistent". When STP state
  cannot be confirmed the cell is left blank (honest "unknown") instead of a false "Forwarding".

V3.14.4 fixes over V3.14.3:
FIX-V14-8 'Switch Mgmt IP' / current_switch_ip now reflects the switch's OWN management IP.
  Previously it was taken from parse_management_ip_from_neighbors(), i.e. a CDP/LLDP
  NEIGHBOR's IP, so the column was wrong on both the interface and SVI sheets. Now sourced
  from the switch's own 'show ip interface brief' (default VRF + NX-OS 'vrf management' for
  mgmt0), with a running-config 'ip address' fallback. Priority: OOB mgmt port > loopback >
  sole management SVI > lowest up SVI. Blank (honest) if nothing qualifies, instead of wrong.
  neighbor_switch_ip is unchanged (correctly CDP-sourced).

V3.14.3 adds over V3.14.2:
FEAT-V14-7 New "SVI Gateway" Excel sheet: one row per SVI (Vlan interface) across all
  devices, carrying the per-SVI routing / HSRP / multicast data that the interface sheet
  excludes by design (it drops Vlan/loopback/tunnel rows). Adds a 'svi_ip' field captured
  from each SVI's 'ip address' line (IOS dotted-mask and NX-OS prefix forms). The interface
  sheet and physical-port rows are unchanged.

V3.14.2 Fixes over V3.14.1 (make the V3.14 feature set actually function end-to-end):
FIX-V14-2 build_interfaces() now accepts switch_identity. It was declared with a dead
  global_bpduguard parameter while the caller passed switch_identity=..., so EVERY parse
  raised TypeError. On the default parallel run the worker pool swallowed it and the
  interface sheet came out empty; with --workers 1 it hard-crashed.
FIX-V14-3 Added the 12 V3.14 fields to InterfaceData (current/neighbor switch identity,
  per-SVI routing, HSRP, multicast). They were read and written but never defined on the
  model, raising AttributeError as soon as FIX-V14-2 was applied.
FIX-V14-4 Collected the commands the V3.14 enrichment consumes: show ip route,
  show vtp status, show standby brief / show hsrp brief, show ip mroute,
  show ip pim interface. They were referenced by parsers but absent from the collection
  lists, so routing/HSRP/multicast/VTP enrichment was always empty.
FIX-V14-5 Wired the 12 fields through to Excel (HEADER_TO_FIELD, ensure_headers, row writer).
FIX-V14-6 Corrected per-SVI subnet matching: now matches the connected route whose outgoing
  interface is the SVI, instead of attaching the first /24-/28 in the table to every SVI.

V3.13.0 Enhancements over V3.11.0:
NEW-V12-1 New "Switch Inventory" Excel sheet (site survey): one row per switch.
  Columns: Hostname, Platform, Model/PID, Serial Number, Chassis Serial,
  SW Version, Uptime, System MAC, # Power Supplies, PS Status,
  Power Capacity (W), Power Drawn (W), Power Remaining (W), # Modules,
  Total Ports, Active Ports, Fan Status, Temperature Status.
NEW-V12-2 New parsers: parse_show_version, parse_show_inventory,
  parse_show_environment_power, parse_show_environment, parse_show_module_count.
NEW-V12-3 New commands: show version, show inventory, show environment power,
  show environment (both platforms), show module (NX-OS).
NEW-V12-4 DevicePhysical dataclass + build_device_physical() builder.
Backward compatible: interface sheet and all existing columns unchanged.

V3.14.1 Fixes over V3.14.0:
FIX-V14-1 Guarded Phase 6 interface row writing against missing per-host interface dictionaries to prevent KeyError and continue processing.

V3.14.0 Enhancements over V3.13.0:
NEW-V14-1 Added current-switch identity fields to interface model: current switch serial, current switch mgmt IP, current switch VTP domain.
NEW-V14-2 Added neighbor-switch identity fields from CDP/LLDP: neighbor switch serial, neighbor switch mgmt IP, neighbor switch VTP domain.
NEW-V14-3 Added per-SVI/routed subnet enrichment: primary route, secondary route(s), next-hop, routing source, HSRP behavior, multicast information.
NEW-V14-4 Kept backward compatibility by only appending new commands, parsers, dataclass fields, and optional Excel columns.

V3.11.0 Enhancements over V3.10.0:
NEW-V11-1 "ARP Source Switch" column: switch whose ARP resolved the MAC->IP.
NEW-V11-2 "CDP/LLDP Neighbor" column: CDP/LLDP device-id on that port.

V3.10.0 Fixes over V3.9.0:
FIX-V10-1  Expanded Cisco error rejection in _load_cmd_output.
FIX-V10-2  collect_global_arp: additive merge across all ARP commands.
FIX-V10-3  Added "show ip arp detail" as third ARP source.
FIX-V10-4  Per-device ARP contribution logged at INFO.

V3.9.0 Fixes: FIX-R1..FIX-R10 (see git history for details).

Requirements: pip install netmiko openpyxl
Run:
  python3 COLLECT_PARSE_V3_14_6.py --devices-file devices.json \
          --template Migration_Assessment_Template_Updated.xlsx
Optional:
  --output OUT.xlsx  --debug-headers  --no-collect
  --collection-dir DIR  --workers N  --debug-arp
"""

import os, sys, json, re, logging, warnings, argparse, time  # CHANGED-V3.23.1: +time (connect backoff)
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from openpyxl.cell.cell import MergedCell
warnings.filterwarnings("ignore")

try:
    from netmiko import ConnectHandler
except ImportError:
    print("ERROR: netmiko not installed. Run: python3 -m pip install netmiko paramiko")
    sys.exit(1)

try:
    from netmiko.ssh_autodetect import SSHDetect
except Exception:
    SSHDetect = None

try:
    from openpyxl import load_workbook
    from openpyxl.styles import Font, PatternFill, Alignment  # NEW-V3.23.1: hoisted (were repeated in ~30 writers)
    from openpyxl.utils import get_column_letter              # NEW-V3.23.1: hoisted
except ImportError:
    print("ERROR: openpyxl not installed. Run: python3 -m pip install openpyxl")
    sys.exit(1)

# =============================================================================
# CONFIG
# =============================================================================
LOG_FILE              = "cisco_migration_autofill_v3_14_6.log"
COLLECTION_DIR        = "migration_collection_{}"
DEFAULT_TEMPLATE_FILE = "Migration_Assessment_Template_Updated.xlsx"
DEFAULT_OUTPUT_FILE   = "Migration_Assessment_AUTOFILLED_{}.xlsx"

NETMIKO_TYPE = {"nxos": "cisco_nxos", "ios": "cisco_ios"}

COMMANDS_NXOS = [
    "show interface brief",
    "show interface status",
    "show interface switchport",
    "show vlan brief",           # NEW-V14.8 (authoritative VLAN id->name for census)
    "show interface trunk",
    "show interface transceiver",
    "show port-channel summary",
    "show etherchannel summary",
    "show spanning-tree",                # NEW-V14.5 (confirmed per-VLAN STP state)
    "show spanning-tree blockedports",
    "show spanning-tree inconsistentports",
    "show cdp neighbors detail",
    "show lldp neighbors detail",
    "show mac address-table",
    "show vrf interface",
    "show ip vrf interface",
    "show running-config interface",
    "show running-config",
    "show power inline",
    "show ip arp",
    "show ip arp vrf all",       # FIX-R1
    "show version",              # NEW-V12
    "show inventory",            # NEW-V12
    "show environment power",    # NEW-V12
    "show environment",          # NEW-V12
    "show module",               # NEW-V12 NX-OS
    "show ip route",             # NEW-V14.2 wiring (per-SVI routing enrichment)
    "show vtp status",           # NEW-V14.2 wiring (VTP domain identity)
    "show hsrp brief",           # NEW-V14.2 wiring (gateway / HSRP behavior)
    "show vrrp brief",           # NEW-V14.6 (VRRP gateways)
    "show glbp brief",           # NEW-V14.6 (GLBP gateways)
    "show ip mroute",            # NEW-V14.2 wiring (multicast info)
    "show ip pim interface",     # NEW-V14.2 wiring (multicast info)
    "show ip interface brief",            # NEW-V14.4 (switch's own mgmt IP)
    "show ip interface brief vrf management",  # NEW-V14.4 (NX-OS mgmt0 lives here)
    "show interface",            # NEW-V15 (interface health counters - NX-OS)
    "show port-security",        # NEW-V15 (security posture)
    "show ip dhcp snooping binding",  # NEW-V15 (security posture)
    "show ip ospf neighbor",     # NEW-V15 (routing adjacencies)
    "show ip eigrp neighbors",   # NEW-V15 (routing adjacencies)
    "show bgp summary",          # NEW-V15 (routing adjacencies - NX-OS)
    "show ip bgp summary",       # NEW-V15 (routing adjacencies)
]

COMMANDS_IOS = [
    "show interface status",
    "show interfaces switchport",
    "show vlan brief",           # NEW-V14.8 (authoritative VLAN id->name for census)
    "show interfaces trunk",
    "show interfaces transceiver",
    "show etherchannel summary",
    "show spanning-tree",                # NEW-V14.5 (confirmed per-VLAN STP state)
    "show spanning-tree blockedports",
    "show spanning-tree inconsistentports",
    "show cdp neighbors detail",
    "show lldp neighbors detail",
    "show mac address-table",
    "show vrf interface",
    "show ip vrf interfaces",
    "show running-config | section ^interface",
    "show running-config",
    "show power inline",
    "show ip arp",
    "show ip arp vrf all",       # FIX-R1
    "show version",              # NEW-V12
    "show inventory",            # NEW-V12
    "show environment power",    # NEW-V12
    "show environment",          # NEW-V12
    "show ip route",             # NEW-V14.2 wiring (per-SVI routing enrichment)
    "show vtp status",           # NEW-V14.2 wiring (VTP domain identity)
    "show standby brief",        # NEW-V14.2 wiring (gateway / HSRP behavior)
    "show vrrp brief",           # NEW-V14.6 (VRRP gateways)
    "show glbp brief",           # NEW-V14.6 (GLBP gateways)
    "show ip mroute",            # NEW-V14.2 wiring (multicast info)
    "show ip pim interface",     # NEW-V14.2 wiring (multicast info)
    "show ip interface brief",   # NEW-V14.4 (switch's own mgmt IP)
    "show interfaces",                # NEW-V15 (interface health counters - IOS)
    "show port-security",             # NEW-V15 (security posture)
    "show authentication sessions",   # NEW-V15 (security posture - 802.1X/MAB)
    "show ip dhcp snooping binding",  # NEW-V15 (security posture)
    "show ip ospf neighbor",          # NEW-V15 (routing adjacencies)
    "show ip eigrp neighbors",        # NEW-V15 (routing adjacencies)
    "show ip bgp summary",            # NEW-V15 (routing adjacencies)
    "show track",                     # NEW-V3.20 (L3 forwarding: object / IP-SLA tracking)
    "show spanning-tree detail",      # NEW-V3.22 (STP topology-change counters)
]

COMMANDS_ALL = list(dict.fromkeys(COMMANDS_NXOS + COMMANDS_IOS))

IFACE_TOKEN_RE = re.compile(
    r"\b(?:Po\d+|Eth\d+/\d+(?:/\d+)?|Gi\d+/\d+(?:/\d+)?|Te\d+/\d+(?:/\d+)?|"
    r"Tw\d+/\d+(?:/\d+)?|Fo\d+/\d+(?:/\d+)?|Hu\d+/\d+(?:/\d+)?|Fa\d+/\d+(?:/\d+)?)\b",
    re.IGNORECASE)

VALID_IFACE_RE = re.compile(
    r"^(?:Po\d+|Eth\d+/\d+(?:/\d+)?|Gi\d+/\d+(?:/\d+)?|Te\d+/\d+(?:/\d+)?|"
    r"Tw\d+/\d+(?:/\d+)?|Fo\d+/\d+(?:/\d+)?|Hu\d+/\d+(?:/\d+)?|Fa\d+/\d+(?:/\d+)?|"
    r"Vlan\d+|Lo\d+|mgmt0)$",
    re.IGNORECASE)

PHYSICAL_IFACE_RE = re.compile(
    r"^(?:Po\d+|Eth\d+/\d+(?:/\d+)?|Gi\d+/\d+(?:/\d+)?|Te\d+/\d+(?:/\d+)?|"
    r"Tw\d+/\d+(?:/\d+)?|Fo\d+/\d+(?:/\d+)?|Hu\d+/\d+(?:/\d+)?|Fa\d+/\d+(?:/\d+)?)$",
    re.IGNORECASE)

_JUNK_IFACE_TOKENS  = {"port","ports","capability","status","native","vlan","name","duplex","speed","type"}
_TRUNK_STATUS_WORDS = {"trunking","trnk-bndl","notconnect","connected","disabled","suspended"}

# =============================================================================
# LOGGING
# =============================================================================
def setup_logging(level=logging.INFO):
    logger = logging.getLogger("CiscoMigrationAutofillV3_14_6")
    logger.setLevel(level)
    if logger.handlers:
        logger.handlers.clear()
    fh = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(logging.Formatter("%(levelname)s - %(message)s"))
    logger.addHandler(ch)
    return logger

logger = setup_logging()

# =============================================================================
# DATA MODEL - InterfaceData
# =============================================================================
@dataclass
class InterfaceData:
    port: str = ""
    status: str = ""
    switchport_mode: str = ""
    vlan: str = ""
    vlan_name: str = ""
    vrf: str = ""
    duplex: str = ""
    speed: str = ""
    port_type: str = ""
    link_type: str = ""
    description: str = ""
    end_host_mac: str = ""
    end_host_ip: str = ""
    port_channel: str = ""
    port_channel_protocol: str = ""
    stp_blocked: str = ""
    stp_bpduguard: str = ""
    stp_rootguard: str = ""
    poe_status: str = ""
    system_owner: str = ""
    endpoint_type: str = ""
    endpoint_location: str = ""
    dual_connection: str = ""
    trunk_native_vlan: str = ""
    trunk_allowed_vlans: str = ""
    trunk_status: str = ""
    arp_source_switch: str = ""  # NEW-V11
    cdp_neighbor: str = ""       # NEW-V11
    # NEW-V14 (defined in V3.14.2; previously read/written but missing from the model)
    current_switch_serial: str = ""
    current_switch_ip: str = ""
    current_switch_vtp_domain: str = ""
    neighbor_switch_serial: str = ""
    neighbor_switch_ip: str = ""
    neighbor_switch_vtp_domain: str = ""
    subnet_primary_route: str = ""
    subnet_secondary_routes: str = ""
    route_next_hop: str = ""
    routing_source: str = ""
    hsrp_behavior: str = ""
    multicast_info: str = ""
    svi_ip: str = ""  # NEW-V14.3 (the SVI's own 'ip address' = gateway IP; for SVI/Gateway sheet)
    # NEW-V14.7 per-VLAN STP detail (compressed VLAN/instance ranges) for the STP Detail sheet
    stp_fwd_vlans: str = ""
    stp_blk_vlans: str = ""
    stp_other_vlans: str = ""
    # NEW-V14.10 neighbor remote port + platform (for the Topology / Links sheet)
    neighbor_port: str = ""
    neighbor_platform: str = ""

# =============================================================================
# DATA MODEL - DevicePhysical (NEW-V12)
# =============================================================================
@dataclass
class DevicePhysical:
    """Switch-level physical inventory for site survey sheet."""
    hostname: str = ""
    platform: str = ""
    model: str = ""
    serial_number: str = ""
    chassis_serial: str = ""
    sw_version: str = ""
    uptime: str = ""
    system_mac: str = ""
    num_power_supplies: int = 0
    ps_status: str = ""
    power_capacity_w: str = ""
    power_drawn_w: str = ""
    power_remaining_w: str = ""
    num_modules: int = 0
    total_ports: int = 0
    active_ports: int = 0
    fan_status: str = ""
    temperature_status: str = ""

# =============================================================================
# NORMALIZATION HELPERS
# =============================================================================
def normalize_ifname(s: str) -> str:
    if not s: return ""
    x = s.strip()
    x = re.sub(r"^Ethernet",          "Eth", x, flags=re.IGNORECASE)
    x = re.sub(r"^FastEthernet",      "Fa",  x, flags=re.IGNORECASE)
    x = re.sub(r"^GigabitEthernet",   "Gi",  x, flags=re.IGNORECASE)
    x = re.sub(r"^TenGigabitEthernet","Te",  x, flags=re.IGNORECASE)
    x = re.sub(r"^FortyGigabitEthernet","Fo",x, flags=re.IGNORECASE)
    x = re.sub(r"^TwentyFiveGigE",    "Tw",  x, flags=re.IGNORECASE)
    x = re.sub(r"^HundredGigE",       "Hu",  x, flags=re.IGNORECASE)
    x = re.sub(r"^[Pp]ort-[Cc]hannel","Po",  x)
    return x

def is_valid_iface(name: str) -> bool:
    n = normalize_ifname((name or "").strip())
    if not n: return False
    if n.lower() in _JUNK_IFACE_TOKENS: return False
    return bool(VALID_IFACE_RE.match(n))

def normalize_status(s: str) -> str:
    if not s: return ""
    t = s.strip().lower()
    return {"up": "connected", "down": "notconnect"}.get(t, t)

def normalize_duplex(s: str) -> str:
    if not s: return ""
    t = s.strip().lower()
    return {"a-full":"Auto","a-half":"Auto","full":"Full","half":"Half","auto":"Auto"}.get(t, s.strip())

def normalize_speed(s: str) -> str:
    if not s: return ""
    t = s.strip().lower().replace("a-","auto-")
    t = re.sub(r"\([ad]\)", "", t)
    mp = {
        "auto":"Auto","auto-1000":"1000","auto-10g":"10G","auto-25g":"25G",
        "auto-40g":"40G","auto-100g":"100G","10g":"10G","25g":"25G","40g":"40G",
        "100g":"100G","1g":"1000","1000":"1000","100":"100","10":"10",
    }
    return mp.get(t, s.strip())

def normalize_mac(mac_str: str) -> str:
    if not mac_str: return ""
    mac = re.sub(r"[\s\-:.]", "", mac_str.strip().lower())
    if len(mac) != 12 or not re.match(r"^[0-9a-f]{12}$", mac): return ""
    return f"{mac[0:4]}.{mac[4:8]}.{mac[8:12]}"

def detect_link_type(transceiver_or_type: str, speed: str) -> str:
    t = (transceiver_or_type or "").lower()
    if any(k in t for k in ["sr","lr","lrm","er","zr","qsfp","sfp","xfp","cfp","glc","-sx","-lx","-lr"]):
        return "Fiber"
    if any(k in t for k in ["copper","cr","dac","twinax","base-t","rj45","-t"]):
        return "Copper"
    s = normalize_speed(speed)
    if any(x in s for x in ["10G","25G","40G","100G"]): return "Fiber"
    if s in ["1000","100","10"]: return "Copper"
    return ""

def safe_fs_name(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r'[<>:"/\\|?*]', "_", s)
    return s.rstrip(". ") or "UNKNOWN_DEVICE"

# =============================================================================
# EXCEL HEADER DEBUG
# =============================================================================
def debug_scan_headers(ws, max_rows=120, max_cols=80):
    print("\n=== DEBUG HEADER SCAN START ===")
    for r in range(1, max_rows + 1):
        vals = [(c, ws.cell(row=r, column=c).value.strip()[:60])
                for c in range(1, min(ws.max_column, max_cols)+1)
                if isinstance(ws.cell(row=r, column=c).value, str)
                and ws.cell(row=r, column=c).value.strip()]
        if vals:
            print(f"ROW {r}: {vals[:18]}")
    print("=== DEBUG HEADER SCAN END ===\n")

# =============================================================================
# PLATFORM AUTODETECT
# =============================================================================
def autodetect_platform(ip: str, username: str, password: str) -> str:
    if SSHDetect is None: return "ios"
    try:
        guesser = SSHDetect(device_type="autodetect", host=ip,
                            username=username, password=password)
        best = (guesser.autodetect() or "").strip().lower()
        if "nxos" in best: return "nxos"
        return "ios"
    except Exception as e:
        logger.debug(f"autodetect_platform({ip}) failed; defaulting to ios: {e}")  # NEW-V3.23.1
        return "ios"

def detect_platform_from_files(dev_dir: str) -> str:
    nxos_markers = ["show_interface_brief.txt","show_interface_switchport.txt",
                    "show_port-channel_summary.txt","show_running-config_interface.txt"]
    ios_markers  = ["show_interfaces_switchport.txt","show_etherchannel_summary.txt",
                    "show_running-config___section_interface.txt"]
    def has_real(fname):
        p = os.path.join(dev_dir, fname)
        if not os.path.isfile(p): return False
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                c = f.read(512).strip()
            # V14.12: a command that errored on the wrong platform is NOT a valid marker.
            low = c[:200].lower()
            if any(pat in low for pat in _CISCO_ERRORS): return False
            return len(c) > 10
        except Exception as e:
            logger.debug(f"detect_platform_from_files: unreadable marker {fname}: {e}")  # NEW-V3.23.1
            return False
    nxos_score = sum(1 for f in nxos_markers if has_real(f))
    ios_score  = sum(1 for f in ios_markers  if has_real(f))
    return "nxos" if nxos_score > ios_score else "ios"

# =============================================================================
# SSH COLLECTION
# =============================================================================
# NEW-V3.23.1: bounded connection retry. A one-shot audit shouldn't lose a live
# switch to a momentary SSH timeout. Transient/timeout failures get a few backoff
# retries; AUTH failures are never retried (a bad credential won't fix itself and
# repeated tries can lock the account). Set CONNECT_MAX_ATTEMPTS = 1 to restore the
# original single-shot behaviour.
CONNECT_MAX_ATTEMPTS = 3        # total attempts per device (1 = no retry)
CONNECT_BACKOFF_BASE = 2.0      # seconds between attempts: 2s, 4s, ...

try:  # netmiko moved its exception classes across versions - stay tolerant
    from netmiko.exceptions import (NetmikoAuthenticationException,
                                    NetmikoTimeoutException)
except Exception:
    try:
        from netmiko.ssh_exception import (NetmikoAuthenticationException,
                                           NetmikoTimeoutException)
    except Exception:
        NetmikoAuthenticationException = NetmikoTimeoutException = None

def _is_auth_error(exc) -> bool:
    """True for an authentication failure (these are NOT retried)."""
    if NetmikoAuthenticationException is not None and \
       isinstance(exc, NetmikoAuthenticationException):
        return True
    m = str(exc).lower()  # fallback if the class isn't importable
    return "authentication" in m or "auth failed" in m or "bad password" in m

def connect_device(ip, hostname, username, password, platform):
    resolved = platform
    if platform in ("auto", ""):                       # CHANGED-V3.23.1: detect once,
        resolved = autodetect_platform(ip, username, password)  # not per retry
    attempts = max(1, CONNECT_MAX_ATTEMPTS)
    last_err = None
    for attempt in range(1, attempts + 1):
        try:
            logger.info(f"Connecting to {hostname} ({ip}) [{resolved}] "
                        f"(attempt {attempt}/{attempts}) ...")
            dev = ConnectHandler(
                device_type=NETMIKO_TYPE.get(resolved, "cisco_ios"),
                host=ip, username=username, password=password,
                timeout=120, conn_timeout=30, auth_timeout=30,
                global_delay_factor=3, fast_cli=False,
            )
            for cmd in ("terminal length 0", "terminal width 511"):
                try: dev.send_command(cmd, read_timeout=30)
                except Exception: pass
            logger.info(f"[OK] Connected to {hostname}")
            return dev, resolved
        except Exception as e:
            last_err = e
            if _is_auth_error(e):                       # don't retry bad credentials
                logger.error(f"[FAIL] Authentication failed to {hostname}: {e} (not retrying)")
                return None, resolved
            if attempt < attempts:
                wait = CONNECT_BACKOFF_BASE * attempt
                logger.warning(f"[RETRY] Connect to {hostname} failed "
                               f"(attempt {attempt}/{attempts}): {e}; retrying in {wait:.0f}s ...")
                time.sleep(wait)
    logger.error(f"[FAIL] Connection failed to {hostname} after {attempts} attempt(s): {last_err}")
    return None, resolved

_SLOW_CMDS = {"show running-config", "show cdp neighbors detail",
              "show lldp neighbors detail", "show mac address-table",
              "show interface trunk", "show interfaces trunk",
              "show interfaces", "show interface"}  # NEW-V15 (full counter dumps)

def send_cmd(dev, cmd: str) -> str:
    try:
        timeout = 300 if any(s in cmd for s in _SLOW_CMDS) else 120
        return dev.send_command_timing(cmd, read_timeout=timeout) or ""
    except Exception as e:
        logger.warning(f"Command failed '{cmd}': {e}")
        return ""

def collect(hostname: str, platform: str, dev, out_dir: str,
            archive_all_output: bool = False,
            include_config_backup: bool = False,
            include_heavy_commands: bool = False) -> Dict[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    # V14.12: collect the UNION of command variants, ordered by the detected platform.
    # The two lists differ only in platform-divergent forms (show standby vs show hsrp,
    # the two run-config forms, etc.); collecting both makes the run resilient to a wrong
    # platform label - _load_cmd_output() already skips the form that errors. Extra commands
    # on the wrong platform just return a quick error and are ignored.
    if platform == "nxos":
        cmds = list(dict.fromkeys(COMMANDS_NXOS + COMMANDS_IOS))
    elif platform == "ios":
        cmds = list(dict.fromkeys(COMMANDS_IOS + COMMANDS_NXOS))
    else:
        cmds = COMMANDS_ALL

    extra_cmds: List[str] = []
    if include_config_backup:
        extra_cmds.append("show startup-config")
    if include_heavy_commands:
        extra_cmds.extend(["show logging", "show tech-support"])

    cmds = list(dict.fromkeys(cmds + extra_cmds))
    paths: Dict[str, str] = {}
    command_index: List[dict] = []
    started = datetime.now().isoformat()

    for cmd in cmds:
        logger.info(f"  Executing: {cmd}")
        out = send_cmd(dev, cmd)
        fn  = cmd.replace(" ","_").replace("|","_").replace("^","").replace("/","_") + ".txt"
        p   = os.path.join(out_dir, fn)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(out)
        paths[cmd] = p

        if archive_all_output:
            size = 0
            sha = ""
            try:
                size = os.path.getsize(p)
                sha = file_sha256(p)
            except Exception:
                pass
            command_index.append({
                "command": cmd,
                "file": fn,
                "path": os.path.abspath(p),
                "bytes": size,
                "sha256": sha,
                "collected_at": datetime.now().isoformat(),
                "has_output": bool((out or "").strip()),
            })

    if archive_all_output:
        device_info = {
            "hostname": hostname,
            "platform": platform,
            "output_dir": os.path.abspath(out_dir),
            "collection_started": started,
            "collection_finished": datetime.now().isoformat(),
            "command_count": len(command_index),
        }
        write_json_file(os.path.join(out_dir, "device_info.json"), device_info)
        write_json_file(os.path.join(out_dir, "command_index.json"), {"commands": command_index})

    return paths

# =============================================================================
# SAFE FILE LOADER
# =============================================================================
_CISCO_ERRORS = (
    "% invalid", "% command not found",
    "% incomplete command", "% unknown command",
    "% ambiguous command", "% ip routing not enabled",
    "% routing not enabled", "invalid input detected",
    "error: invalid", "% requires vrf", "% vrf does not exist",
)

def _load_cmd_output(cmd_to_file: Dict[str, str], *cmd_variants: str) -> str:
    for cmd in cmd_variants:
        p = cmd_to_file.get(cmd)
        if p and os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                stripped = content.strip()
                if not stripped: continue
                first_chunk = stripped[:200].lower()
                if any(pat in first_chunk for pat in _CISCO_ERRORS): continue
                return content
            except Exception as e:
                logger.debug(f"_load_cmd_output: failed reading {p} for '{cmd}': {e}")  # NEW-V3.23.1
    return ""

# =============================================================================
# PARSERS - interface commands
# =============================================================================
def extract_fixed_cols(header_line: str, keys: List[Tuple[str,str]]) -> Dict[str, Tuple[int, Optional[int]]]:
    pos = {}
    for needle, name in keys:
        p = header_line.find(needle)
        if p >= 0: pos[name] = p
    items = sorted(pos.items(), key=lambda x: x[1])
    ranges = {}
    for i, (name, start) in enumerate(items):
        end = items[i+1][1] if i < len(items)-1 else None
        ranges[name] = (start, end)
    return ranges

def slice_col(line: str, start: int, end: Optional[int]) -> str:
    return line[start:].strip() if end is None else line[start:end].strip()

def parse_show_interface_status(output: str) -> Dict[str, Dict[str, str]]:
    res: Dict[str, Dict[str, str]] = {}
    col = None
    for line in output.splitlines():
        if ("Port" in line and "Name" in line and "Status" in line and
                "Vlan" in line and "Duplex" in line and "Speed" in line and "Type" in line):
            col = extract_fixed_cols(line, [
                ("Port","port"),("Name","name"),("Status","status"),("Vlan","vlan"),
                ("Duplex","duplex"),("Speed","speed"),("Type","type")])
            continue
        if not col or not line.strip() or "----" in line: continue
        port = normalize_ifname(slice_col(line, *col["port"]))
        if not port or not is_valid_iface(port): continue
        raw_duplex = slice_col(line, *col["duplex"])
        raw_speed  = slice_col(line, *col["speed"])
        if raw_speed.startswith("-") and raw_duplex.endswith(" a"):
            raw_speed  = "a" + raw_speed
            raw_duplex = raw_duplex[:-2].strip()
        res[port] = {
            "name":   slice_col(line, *col["name"]),
            "status": normalize_status(slice_col(line, *col["status"])),
            "vlan_raw": slice_col(line, *col["vlan"]),
            "duplex": normalize_duplex(raw_duplex),
            "speed":  normalize_speed(raw_speed),
            "type":   slice_col(line, *col["type"]),
        }
    return res

def parse_show_interface_switchport(output: str) -> Dict[str, Dict[str, str]]:
    res: Dict[str, Dict[str, str]] = {}
    current = None
    block: List[str] = []

    def commit(intf, lines):
        if not intf: return
        intf_n = normalize_ifname(intf)
        if not is_valid_iface(intf_n): return
        d = {"mode":"","access_vlan":"","access_vlan_name":"",
             "native_vlan":"","native_vlan_name":"","allowed_vlans":""}
        admin_mode = oper_mode = ""
        allowed_capture = False
        for ln in lines:
            low = ln.strip().lower()
            if low.startswith("administrative mode:"):
                admin_mode = ln.split(":",1)[1].strip()
            if low.startswith("operational mode:"):
                oper_mode = ln.split(":",1)[1].strip()
            if "access mode vlan:" in low:
                m = re.search(r"access mode vlan:\s*([0-9]+)\s*(?:\(([^)]+)\))?", ln, re.IGNORECASE)
                if m:
                    d["access_vlan"]      = m.group(1)
                    d["access_vlan_name"] = (m.group(2) or "").strip()
            if "trunking native" in low and "vlan" in low:
                m = re.search(r"vlan:\s*([0-9]+)\s*(?:\(([^)]+)\))?", ln, re.IGNORECASE)
                if m:
                    d["native_vlan"]      = m.group(1)
                    d["native_vlan_name"] = (m.group(2) or "").strip()
            if "trunking vlans allowed" in low:
                tail = ln.split(":",1)[1].strip() if ":" in ln else ""
                if tail: d["allowed_vlans"] = tail
                allowed_capture = True; continue
            if allowed_capture:
                if ":" in ln: allowed_capture = False
                else:
                    cont = ln.strip()
                    if cont: d["allowed_vlans"] = (d["allowed_vlans"]+","+cont).strip(",")
        mode = ""
        if "trunk" in (oper_mode or "").lower() or "trunk" in (admin_mode or "").lower():
            mode = "Trunk"
        elif "access" in (oper_mode or "").lower() or "access" in (admin_mode or "").lower():
            mode = "Access"
        d["mode"] = mode
        res[intf_n] = d

    for line in output.splitlines():
        m = re.match(r"^\s*Name:\s*(\S+)", line)
        if m:
            if current is not None: commit(current, block)
            current = m.group(1); block = []; continue
        if current is not None: block.append(line)
    if current is not None: commit(current, block)
    return res

def parse_show_interface_trunk_table(output: str) -> Dict[str, Dict[str, str]]:
    res: Dict[str, Dict[str, str]] = {}
    section = None
    ios_top = nxos_top = False
    for raw in output.splitlines():
        line = raw.strip()
        if not line or set(line) == {"-"}: continue
        if line.startswith("%"): continue
        low = line.lower()
        if low.startswith("port") and "mode" in low and "encapsulation" in low:
            section = "top"; ios_top = True;  nxos_top = False; continue
        if low.startswith("port") and "native" in low and "status" in low and "channel" in low:
            section = "top"; nxos_top = True; ios_top = False; continue
        if low.startswith("port") and "native" in low and "status" in low:
            section = "top"; ios_top = True;  nxos_top = False; continue
        if low.startswith("port") and "vlans allowed on trunk" in low:
            section = "allowed"; ios_top = nxos_top = False; continue
        if low.startswith("port") and ("vlans allowed" in low or "vlans in spanning" in low):
            section = "other"; continue
        if section == "top":
            parts = line.split()
            if len(parts) < 3: continue
            intf = normalize_ifname(parts[0])
            if not is_valid_iface(intf): continue
            res.setdefault(intf, {"native_vlan":"","status":"","port_channel":"","allowed_vlans":""})
            if nxos_top:
                res[intf]["native_vlan"] = parts[1] if parts[1].isdigit() else ""
                res[intf]["status"]      = parts[2] if len(parts) > 2 else ""
                po = parts[3] if len(parts) > 3 else "--"
                res[intf]["port_channel"] = "" if po in ("--","") else normalize_ifname(po)
            else:
                if len(parts) >= 5:
                    res[intf]["status"]      = parts[3]
                    res[intf]["native_vlan"] = parts[4] if parts[4].isdigit() else ""
                elif len(parts) == 4:
                    res[intf]["status"]      = parts[2]
                    res[intf]["native_vlan"] = parts[3] if parts[3].isdigit() else ""
                res[intf]["port_channel"] = ""
        if section == "allowed":
            parts = line.split(None, 1)
            if len(parts) == 2:
                intf  = normalize_ifname(parts[0])
                if not is_valid_iface(intf): continue
                vlans = parts[1].strip()
                if "feature vtp is not enabled" in vlans.lower(): vlans = ""
                res.setdefault(intf, {"native_vlan":"","status":"","port_channel":"","allowed_vlans":""})
                res[intf]["allowed_vlans"] = "" if vlans.lower() == "none" else vlans
    return res

def parse_show_mac_address_table(output: str) -> Dict[str, List[str]]:
    res: Dict[str, List[str]] = {}
    seen: Dict[str, set] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith(("VLAN","Legend","----","Total","Note")): continue
        parts = line.split()
        if len(parts) < 4: continue
        idx = 0
        if not parts[0].isdigit(): idx = 1
        if idx + 2 >= len(parts): continue
        mac   = parts[idx + 1]
        typ   = parts[idx + 2].lower()
        iface = parts[-1]
        if typ != "dynamic": continue
        mac_n = normalize_mac(mac)
        if_n  = normalize_ifname(iface)
        if not mac_n or not if_n: continue
        res.setdefault(if_n, []);  seen.setdefault(if_n, set())
        if mac_n not in seen[if_n]:
            res[if_n].append(mac_n); seen[if_n].add(mac_n)
    return res

def parse_spanning_tree_blockedports(output: str) -> Dict[str, bool]:
    blocked: Dict[str, bool] = {}
    for line in output.splitlines():
        for t in IFACE_TOKEN_RE.findall(line):
            blocked[normalize_ifname(t)] = True
    return blocked

def parse_vlan_brief(output: str) -> Dict[str, Dict[str, object]]:
    """Parse 'show vlan brief' (IOS + NX-OS) -> {vlan_id: {'name': str, 'ports': [ifnames]}}.

    Primary row: '<id> <name> <status> <ports...>'; port lists may wrap onto indented
    continuation lines, which are appended to the last VLAN seen.
    """
    res: Dict[str, Dict[str, object]] = {}
    cur: Optional[str] = None
    for raw in output.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m = re.match(r"^(\d+)\s+(\S+)\s+(active|suspended|act/lshut|act/unsup|sus/lshut|\S+)\s*(.*)$", line)
        if m:
            cur = m.group(1)
            res[cur] = {"name": m.group(2), "ports": []}
            for t in IFACE_TOKEN_RE.findall(m.group(4) or ""):
                res[cur]["ports"].append(normalize_ifname(t))
        elif cur and re.match(r"^\s+\S", raw) and not re.match(r"^\s*(VLAN|----)", line, re.IGNORECASE):
            for t in IFACE_TOKEN_RE.findall(line):
                res[cur]["ports"].append(normalize_ifname(t))
    return res

_STP_STS_NAME = {"FWD": "Forwarding", "BLK": "Blocked", "BKN": "Blocked",
                 "LIS": "Listening", "LRN": "Learning", "DIS": "Disabled"}

def parse_spanning_tree_detail(output: str) -> Dict[str, Dict[str, List[str]]]:
    """Parse full 'show spanning-tree' -> {ifname: {state_name: [vlan/instance ids]}}.

    The output is organized per VLAN (Rapid-PVST) or per instance (MST):
        VLAN0010
        Interface  Role Sts Cost  Prio.Nbr Type
        Gi1/0/1    Root FWD 4     128.1    P2p
        Gi1/0/24   Altn BLK 19    128.24   P2p
    Each port row's status (FWD/BLK/...) is recorded under the current VLAN/instance.
    Under MST the captured ids are MST instance numbers, not VLAN ids.
    """
    detail: Dict[str, Dict[str, List[str]]] = {}
    if not output:
        return detail
    vhdr = re.compile(r"^(?:VLAN0*(\d+)|MST0*(\d+))\b", re.IGNORECASE)
    row  = re.compile(
        r"^(\S+)\s+(?:Root|Desg|Altn|Back|Boun|Mstr)\*?\s+(FWD|BLK|LIS|LRN|DIS|BKN)\b",
        re.IGNORECASE)
    cur: Optional[str] = None
    for raw in output.splitlines():
        s = raw.strip()
        if not s:
            continue
        vm = vhdr.match(s)
        if vm:
            cur = vm.group(1) or vm.group(2)
            continue
        m = row.match(s)
        if m and cur is not None and is_valid_iface(m.group(1)):
            ifn = normalize_ifname(m.group(1))
            st  = _STP_STS_NAME.get(m.group(2).upper())
            if st:
                lst = detail.setdefault(ifn, {}).setdefault(st, [])
                if cur not in lst:
                    lst.append(cur)
    return detail

def parse_spanning_tree_states(output: str) -> Dict[str, str]:
    """{ifname: collapsed STP state}. Blocked-wins summary, derived from the per-VLAN
    detail so the two views never disagree. NOT inferred from link-up."""
    out: Dict[str, str] = {}
    for ifn, st in parse_spanning_tree_detail(output).items():
        if st.get("Blocked"):      out[ifn] = "Blocked"
        elif st.get("Forwarding"): out[ifn] = "Forwarding"
        elif st.get("Learning"):   out[ifn] = "Learning"
        elif st.get("Listening"):  out[ifn] = "Listening"
        elif st.get("Disabled"):   out[ifn] = "Disabled"
    return out

def _compress_vlans(vlans: List[str]) -> str:
    """[10, 20, 21, 22, 23] -> '10,20-23'. Non-numeric ids are appended as-is."""
    nums = sorted({int(v) for v in vlans if str(v).isdigit()})
    extra = [str(v) for v in vlans if not str(v).isdigit()]
    out: List[str] = []
    if nums:
        start = prev = nums[0]
        for v in nums[1:]:
            if v == prev + 1:
                prev = v; continue
            out.append(f"{start}-{prev}" if start != prev else f"{start}")
            start = prev = v
        out.append(f"{start}-{prev}" if start != prev else f"{start}")
    return ",".join(out + extra)

def parse_show_vrf_interface(output: str) -> Dict[str, str]:
    m: Dict[str, str] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line or line.lower().startswith(("interface","vrf","----")): continue
        parts = line.split()
        if len(parts) >= 2 and is_valid_iface(parts[0]):
            m[normalize_ifname(parts[0])] = parts[1]
    return m

def parse_show_power_inline(output: str) -> Dict[str, str]:
    m: Dict[str, str] = {}
    for line in output.splitlines():
        if not line.strip(): continue
        it = IFACE_TOKEN_RE.search(line)
        if not it: continue
        intf = normalize_ifname(it.group(0))
        low  = line.lower()
        if "not supported" in low:   m[intf] = "Not Supported"
        elif "delivering" in low:    m[intf] = "Delivering"
        elif re.search(r"\bon\b", low): m[intf] = "Delivering"
        elif "searching" in low:     m[intf] = "Searching"
        elif "fault" in low:         m[intf] = "Fault"
        elif "deny" in low or "denied" in low: m[intf] = "Deny"
        elif "disabled" in low:      m[intf] = "Disabled"
        elif "off" in low:           m[intf] = "Off"
    return m

def parse_neighbors_cdp(output: str) -> Dict[str, Dict[str, str]]:
    res: Dict[str, Dict[str, str]] = {}
    for sec in re.split(r"-{5,}", output):
        sec = sec.strip()
        if not sec: continue
        device_id = platform_s = mgmt_ip = local_intf = remote_port = ""
        for line in sec.splitlines():
            line = line.strip()
            if line.lower().startswith("device id:"):
                device_id  = line.split(":",1)[1].strip()
            if line.lower().startswith("platform:"):
                platform_s = line.split(":",1)[1].strip()
                platform_s = re.split(r",\s*Capabilities", platform_s, 1)[0].strip()
            ipm = re.search(r"\bip address:\s*(\d+\.\d+\.\d+\.\d+)\b", line, re.IGNORECASE)
            if ipm: mgmt_ip = ipm.group(1)
            if line.lower().startswith("interface:"):
                mv = re.search(r"Interface:\s*([^,]+)", line, re.IGNORECASE)
                if mv: local_intf = normalize_ifname(mv.group(1).strip())
                pm = re.search(r"Port ID\s*\(outgoing port\):\s*(\S+)", line, re.IGNORECASE)
                if pm: remote_port = normalize_ifname(pm.group(1).strip())
        if local_intf:
            res[local_intf] = {"device_id": device_id, "platform": platform_s,
                               "mgmt_ip": mgmt_ip, "remote_port": remote_port}
    return res

def parse_neighbors_lldp(output: str) -> Dict[str, Dict[str, str]]:
    res: Dict[str, Dict[str, str]] = {}
    for ch in re.split(r"\n\s*Local Intf:\s*", "\n" + output):
        ch = ch.strip()
        if not ch: continue
        local   = normalize_ifname(ch.splitlines()[0].strip().split()[0])
        sysname = mgmt = remote_port = ""
        for line in ch.splitlines():
            ls = line.strip()
            if ls.lower().startswith("system name:"):
                sysname = ls.split(":",1)[1].strip()
            if ls.lower().startswith("port id:"):
                remote_port = normalize_ifname(ls.split(":",1)[1].strip())
            if ls.lower().startswith("management address:"):
                ipm = re.search(r"(\d+\.\d+\.\d+\.\d+)", ls)
                if ipm: mgmt = ipm.group(1)
        if local:
            res[local] = {"device_id": sysname, "platform": "", "mgmt_ip": mgmt,
                          "remote_port": remote_port}
    return res

_DESC_EP_PATTERNS = [
    (re.compile(r"\b(ap|access.?point|wap|aironet|wifi)\b",          re.I), "Access Point"),
    (re.compile(r"\b(ip.?phone|phone|voip|7[0-9]{3})\b",             re.I), "IP Phone"),
    (re.compile(r"\b(server|srv|esxi|vmware|ucs|blade)\b",            re.I), "Server"),
    (re.compile(r"\b(camera|cctv|ipcam|nvr)\b",                       re.I), "Camera"),
    (re.compile(r"\b(printer|mfp|copier)\b",                          re.I), "Printer"),
    (re.compile(r"\b(ups|pdu|apc|power.?supply)\b",                   re.I), "UPS/PDU"),
    (re.compile(r"\b(router|rtr|gateway|gw)\b",                       re.I), "Router"),
    (re.compile(r"\b(firewall|fw|asa|ftd|fortigate|palo)\b",          re.I), "Firewall"),
    (re.compile(r"\b(switch|sw|catalyst|nexus)\b",                    re.I), "Switch"),
    (re.compile(r"\b(storage|san|nas|emc|netapp|ds3|ds4)\b",          re.I), "Storage"),
]

def infer_endpoint_type(platform: str, device_id: str, description: str = "") -> str:
    p = (platform or "").lower(); d = (device_id or "").lower()
    if any(x in p for x in ["nexus","catalyst","cisco","ws-c"]): return "Switch"
    if any(x in p for x in ["asr","isr","csr","ncs"]):           return "Router"
    if any(x in p for x in ["asa","firepower","ftd"]):            return "Firewall"
    if any(x in d for x in ["esx","ucs","vm","srv","server"]):   return "Server"
    if platform or device_id: return "Neighbour"
    desc = (description or "").lower()
    for pat, label in _DESC_EP_PATTERNS:
        if pat.search(desc): return label
    return ""

def parse_run_config_interfaces(output: str) -> Dict[str, Dict[str, str]]:
    res: Dict[str, Dict[str, str]] = {}
    current = None
    global_bpduguard = False
    for line in output.splitlines():
        if re.search(r"spanning-tree portfast bpduguard default", line, re.IGNORECASE):
            global_bpduguard = True; continue
        m = re.match(r"^\s*interface\s+(\S+)", line, re.IGNORECASE)
        if m:
            current = normalize_ifname(m.group(1))
            res.setdefault(current, {"bpduguard":"","rootguard":"","pc_mode":"","pc_id":"","vrf":"","desc":"","portfast":"","ip_addr":""})
            if global_bpduguard:
                res[current]["bpduguard"] = "Enable"
            continue
        if not current: continue
        low = line.strip().lower()
        if low.startswith("description "):
            res[current]["desc"] = line.strip()[len("description "):].strip()
        # SVI / L3 interface IP. IOS: 'ip address 10.10.10.1 255.255.255.0'
        # NX-OS: 'ip address 10.10.10.1/24'. Skip secondary/dhcp/negotiated.
        if low.startswith("ip address ") and "secondary" not in low and "dhcp" not in low and "negotiated" not in low:
            mip = re.search(r"ip address\s+(\d+\.\d+\.\d+\.\d+)(?:\s+(\d+\.\d+\.\d+\.\d+)|/(\d+))",
                            line.strip(), re.IGNORECASE)
            if mip and not res[current].get("ip_addr"):
                ip = mip.group(1)
                if mip.group(3):                       # NX-OS prefix form
                    res[current]["ip_addr"] = f"{ip}/{mip.group(3)}"
                elif mip.group(2):                     # IOS dotted-mask form
                    res[current]["ip_addr"] = f"{ip} {mip.group(2)}"
                else:
                    res[current]["ip_addr"] = ip
        if "spanning-tree bpduguard" in low:
            if "enable" in low:                         res[current]["bpduguard"] = "Enable"
            elif "disable" in low or low.endswith("no"): res[current]["bpduguard"] = "Disable"
        if "spanning-tree guard root" in low:
            res[current]["rootguard"] = "Disable" if low.startswith("no ") else "Enable"
        if "spanning-tree portfast" in low and "disable" not in low:
            res[current]["portfast"] = "Enable"
        if "channel-group" in low and "mode" in low:
            cm = re.search(r"channel-group\s+(\d+)\s+mode\s+(\S+)", low)
            if cm:
                res[current]["pc_id"]   = f"Po{cm.group(1)}"
                res[current]["pc_mode"] = cm.group(2)
        if low.startswith("vrf member "):    res[current]["vrf"] = line.strip().split()[-1]
        if low.startswith("vrf forwarding "): res[current]["vrf"] = line.strip().split()[-1]
    return res

def _proto_from_token(tok: str) -> str:
    t = (tok or "").strip().upper()
    if t == "LACP": return "Active"
    if t == "PAGP": return "Active"
    if t in ("NONE","-","ON"): return "On"
    return ""

def parse_portchannel_protocol_from_summary(output: str) -> Dict[str, str]:
    proto: Dict[str, str] = {}
    for line in output.splitlines():
        m = re.search(r"\b(Po\d+)\b\s*(?:\(\w+\))?\s+(?:\w+\s+)*(LACP|PAgP|NONE|-)\b",
                      line, re.IGNORECASE)
        if m:
            po = normalize_ifname(m.group(1))
            p  = _proto_from_token(m.group(2))
            if p: proto[po] = p
    return proto

def parse_etherchannel_protocol_ios(output: str) -> Dict[str, str]:
    proto: Dict[str, str] = {}
    for line in output.splitlines():
        m = re.search(r"\b(Po\d+)\b.*?\b(LACP|PAgP|NONE|-)\b", line, re.IGNORECASE)
        if m:
            po = normalize_ifname(m.group(1))
            p  = _proto_from_token(m.group(2))
            if p: proto[po] = p
    return proto

def parse_etherchannel_summary_members(output: str) -> Dict[str, str]:
    members: Dict[str, str] = {}
    current_po = ""
    for line in output.splitlines():
        pm = re.search(r"\b(Po\d+)\b", line, re.IGNORECASE)
        if pm: current_po = normalize_ifname(pm.group(1))
        if not current_po: continue
        for tok in IFACE_TOKEN_RE.findall(line):
            n = normalize_ifname(tok)
            if not n.startswith("Po"): members[n] = current_po
    return members

def parse_show_ip_arp(output: str) -> Dict[str, str]:
    """FIX-R2+FIX-R8: token-scan based, tolerates any column order, skips VRF banners."""
    result: Dict[str, str] = {}
    _IP_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
    _SKP   = re.compile(
        r"^(protocol|address|ip address|ip arp|arp|total|vrf|context|flags|"
        r"hardware addr|incomplete|age|interface|#|--|===)", re.IGNORECASE)
    for line in output.splitlines():
        line = line.strip()
        if not line: continue
        if _SKP.match(line): continue
        if "incomplete" in line.lower(): continue
        parts = line.split()
        if len(parts) < 3: continue
        ip_addr = mac_addr = ""
        for tok in parts:
            if not ip_addr and _IP_RE.match(tok):
                ip_addr = tok
            if not mac_addr:
                mn = normalize_mac(tok)
                if mn: mac_addr = mn
        if ip_addr and mac_addr:
            result.setdefault(mac_addr, ip_addr)
    return result

def parse_vtp_status(output: str) -> str:
    if not output:
        return ""
    for line in output.splitlines():
        m = re.search(r"(?:vtp\s+domain\s+name|domain name)\s*:?\s*(.+)$", line.strip(), re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if val and val.lower() not in ("not configured", "none", "null"):
                return val
    return ""

def _parse_ip_int_brief(blob: str) -> Dict[str, Tuple[str, bool]]:
    """Parse 'show ip interface brief' (IOS + NX-OS) -> {ifname: (ip, is_up)}.

    IOS line:   GigabitEthernet0/0  10.99.0.5  YES NVRAM  up  up
    NX-OS line: mgmt0               10.99.0.5  protocol-up/link-up/admin-up
    'unassigned' / no-IP lines are skipped.
    """
    res: Dict[str, Tuple[str, bool]] = {}
    if not blob:
        return res
    for raw in blob.splitlines():
        s = raw.strip()
        if not s or s.lower().startswith(("interface", "ip interface status")):
            continue
        m = re.match(r"^(\S+)\s+(\d+\.\d+\.\d+\.\d+)\b(.*)$", s)
        if not m:
            continue
        ifn = normalize_ifname(m.group(1))
        ip  = m.group(2)
        rest = m.group(3).lower()
        # up if NX-OS 'protocol-up' & 'link-up', or IOS trailing 'up   up' (proto up)
        if "protocol-up" in rest or "link-up" in rest:
            is_up = ("protocol-up" in rest) and ("admin-up" in rest or "link-up" in rest)
        else:
            toks = rest.split()
            is_up = len(toks) >= 2 and toks[-1] == "up"   # IOS: last col = protocol
        if ifn not in res or (is_up and not res[ifn][1]):
            res[ifn] = (ip, is_up)
    return res

def parse_switch_mgmt_ip(ipbrief_blob: str, run_iface: Optional[Dict[str, Dict[str, str]]] = None) -> str:
    """Best-effort 'this switch's own management IP', NOT a neighbor's.

    Priority: OOB mgmt port (mgmt0 / Management* / Gi0/0 / Fa0/0) > lowest Loopback >
    a sole management SVI > lowest-numbered up SVI. Prefers up interfaces within a tier.
    Falls back to run-config 'ip address' lines if ip-int-brief is unavailable.
    Returns a bare address (no mask/prefix), or '' if nothing qualifies.
    """
    ifs = _parse_ip_int_brief(ipbrief_blob)

    # Fallback: derive {ifname: (ip, up?)} from run-config-captured ip_addr (up unknown -> True)
    if not ifs and run_iface:
        for ifn, v in run_iface.items():
            raw_ip = (v.get("ip_addr") or "").strip()
            if not raw_ip:
                continue
            ipv = raw_ip.split()[0].split("/")[0]
            if ipv:
                ifs[normalize_ifname(ifn)] = (ipv, True)
    if not ifs:
        return ""

    def bare(ip: str) -> str:
        return ip.split()[0].split("/")[0]
    def num(ifn: str) -> int:
        m = re.search(r"(\d+)", ifn);  return int(m.group(1)) if m else 0
    def pick(cands: List[str]) -> str:
        if not cands:
            return ""
        cands.sort(key=lambda i: (not ifs[i][1], num(i)))  # up first, then lowest index
        return bare(ifs[cands[0]][0])

    oob  = [i for i in ifs if re.match(r"^(mgmt|management|gigabitethernet0/0|fastethernet0/0|gi0/0|fa0/0)", i, re.IGNORECASE)]
    if oob:  return pick(oob)
    loop = [i for i in ifs if i.lower().startswith(("lo", "loop"))]
    if loop: return pick(loop)
    svis = [i for i in ifs if re.match(r"^Vlan\d+$", i, re.IGNORECASE)]
    if len(svis) == 1:        # sole SVI with an IP == the management SVI
        return bare(ifs[svis[0]][0])
    if svis:                  # L3 switch with many gateway SVIs: best-effort, lowest up SVI
        return pick(svis)
    return pick(list(ifs.keys()))

def parse_ip_routes(output: str) -> Dict[str, Dict[str, object]]:
    routes: Dict[str, Dict[str, object]] = {}
    if not output:
        return routes
    code_map = {
        'C':'connected','L':'local','S':'static','R':'rip','M':'mobile','B':'bgp','D':'eigrp','EX':'eigrp-external',
        'O':'ospf','IA':'ospf-interarea','N1':'ospf-nssa1','N2':'ospf-nssa2','E1':'ospf-ext1','E2':'ospf-ext2',
        'i':'isis','su':'static','*':'candidate-default','H':'hsrp'
    }
    current = None
    for raw in output.splitlines():
        line = raw.rstrip()
        s = line.strip()
        if not s or s.lower().startswith(('gateway of last resort','codes:','route source','is variably subnetted','is subnetted')):
            continue
        m = re.match(r"^([A-Z][A-Z0-9\*]*)\s+(\d+\.\d+\.\d+\.\d+/\d+|\d+\.\d+\.\d+\.\d+\s*/\s*\d+)", s)
        if m:
            code = m.group(1)
            prefix = m.group(2).replace(' ', '')
            nh = ''
            out_intf = ''
            mvia = re.search(r"via\s+(\d+\.\d+\.\d+\.\d+)", s, re.IGNORECASE)
            if mvia:
                nh = mvia.group(1)
            mint = re.search(r",\s*([A-Za-z]+[A-Za-z0-9/\.:-]+)\s*$", s)
            if mint and not re.match(r"^\d+\.\d+\.\d+\.\d+$", mint.group(1)):
                out_intf = normalize_ifname(mint.group(1))
            routes.setdefault(prefix, {'entries': []})
            entry = {'prefix': prefix, 'code': code, 'source': code_map.get(code, code.lower()), 'next_hop': nh, 'out_intf': out_intf, 'raw': s}
            routes[prefix]['entries'].append(entry)
            current = prefix
            continue
        if current:
            m2 = re.search(r"via\s+(\d+\.\d+\.\d+\.\d+)", s, re.IGNORECASE)
            if m2:
                nh = m2.group(1)
                mint = re.search(r",\s*([A-Za-z]+[A-Za-z0-9/\.:-]+)\s*$", s)
                out_intf = ''
                if mint and not re.match(r"^\d+\.\d+\.\d+\.\d+$", mint.group(1)):
                    out_intf = normalize_ifname(mint.group(1))
                routes[current]['entries'].append({'prefix': current, 'code': '', 'source': '', 'next_hop': nh, 'out_intf': out_intf, 'raw': s})
    return routes

def parse_hsrp_summary(output: str) -> Dict[str, str]:
    res: Dict[str, str] = {}
    if not output:
        return res
    current_intf = ''
    current_grp = ''
    current_state = ''
    current_vip = ''
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        # show standby brief / show hsrp brief tabular format:
        #   Interface  Grp  Pri P State  Active  Standby  Virtual-IP   (last IP = VIP)
        bm = re.match(r"^(Vl(?:an)?\d+|\S+)\s+(\d+)\s+\d+\s+[P\s]?\s*"
                      r"(Active|Standby|Listen|Speak|Init|Learn)\b", line, re.IGNORECASE)
        if bm:
            intf = re.sub(r"^Vl(\d)", r"Vlan\1", bm.group(1), flags=re.IGNORECASE)  # Vl10 -> Vlan10
            intf = normalize_ifname(intf)
            grp, state = bm.group(2), bm.group(3).capitalize()
            ips = re.findall(r"\b(\d+\.\d+\.\d+\.\d+)\b", line)
            vip = ips[-1] if ips else ''
            res[intf] = f'HSRP grp {grp} {state}' + (f' VIP {vip}' if vip else '')
            current_intf, current_grp, current_state = intf, grp, state
            continue
        m1 = re.match(r"^(Vlan\d+|\S+)\s+-?\s*Group\s*(\d+)\b.*?\b(Active|Standby|Listen|Speak|Init|Learn)\b", line, re.IGNORECASE)
        m2 = re.match(r"^(Vlan\d+|\S+)\s+(\d+)\s+(Active|Standby|Listen|Speak|Init|Learn)\b", line, re.IGNORECASE)
        m = m1 or m2
        if m:
            current_intf = normalize_ifname(m.group(1))
            current_grp = m.group(2)
            current_state = m.group(3).capitalize()
            # V14.11: VIP = last IP on the line (same heuristic as the brief branch),
            # instead of the old weak trailing optional capture that usually missed it.
            ips = re.findall(r"\b(\d+\.\d+\.\d+\.\d+)\b", line)
            current_vip = ips[-1] if ips else ''
            behavior = f'HSRP grp {current_grp} {current_state}' + (f' VIP {current_vip}' if current_vip else '')
            res[current_intf] = behavior
            continue
        if current_intf and 'virtual ip address is' in line.lower():
            m = re.search(r"virtual ip address is\s+(\d+\.\d+\.\d+\.\d+)", line, re.IGNORECASE)
            if m:
                vip = m.group(1)
                base = res.get(current_intf, f'HSRP grp {current_grp} {current_state}'.strip())
                if 'VIP' not in base:
                    res[current_intf] = base + f' VIP {vip}'
    return res

def parse_vrrp_summary(output: str) -> Dict[str, str]:
    """Parse 'show vrrp brief' (IOS + NX-OS) -> {ifname: 'VRRP grp N State VIP x'}.

    IOS:   Vlan10  1  100 3609   Y  Master  10.10.10.1   10.10.10.254  (last IP = VIP/Group addr)
    NX-OS: Vlan10  1  IPV4  100  100  Y  Master  10.10.10.254          (last IP = VIP)
    """
    res: Dict[str, str] = {}
    if not output:
        return res
    for raw in output.splitlines():
        s = raw.strip()
        if not s or s.lower().startswith("interface"):
            continue
        m = re.match(r"^(\S+)\s+(\d+)\b", s)
        if not m or not is_valid_iface(m.group(1)):
            continue
        st = re.search(r"\b(Master|Backup|Init|Listen)\b", s, re.IGNORECASE)
        if not st:
            continue
        ips = re.findall(r"\b(\d+\.\d+\.\d+\.\d+)\b", s)
        vip = ips[-1] if ips else ''
        ifn = normalize_ifname(m.group(1))
        res[ifn] = f'VRRP grp {m.group(2)} {st.group(1).capitalize()}' + (f' VIP {vip}' if vip else '')
    return res

def parse_glbp_summary(output: str) -> Dict[str, str]:
    """Parse 'show glbp brief' -> {ifname: 'GLBP grp N State VIP x'} (group rows only).

    Group row has Fwd column '-' and an IP in the Address column (the virtual IP):
      Vlan10  1  -  100  Active  10.10.10.254  local  10.10.10.3
    Forwarder rows (Fwd = 1/2/3, Address = a MAC) are ignored.
    """
    res: Dict[str, str] = {}
    if not output:
        return res
    for raw in output.splitlines():
        s = raw.strip()
        if not s or s.lower().startswith("interface"):
            continue
        m = re.match(r"^(\S+)\s+(\d+)\s+-\s+\S+\s+"
                     r"(Active|Standby|Listen|Init|Disabled)\b\s+(\d+\.\d+\.\d+\.\d+)",
                     s, re.IGNORECASE)
        if not m or not is_valid_iface(m.group(1)):
            continue
        ifn = normalize_ifname(m.group(1))
        res[ifn] = f'GLBP grp {m.group(2)} {m.group(3).capitalize()} VIP {m.group(4)}'
    return res

def parse_multicast_info(mroute_out: str, pim_out: str) -> Dict[str, str]:
    """Per-interface multicast state from 'show ip pim interface' + 'show ip mroute'.

    V14.11: parse the real PIM table (Address / Interface / Ver/Mode / ...) instead of the
    incorrect 'X is up' assumption, and capture VlanN interfaces in mroute IIF/OIL (the global
    IFACE_TOKEN_RE deliberately excludes Vlan, so a local Vlan-aware token regex is used here).
    """
    # Vlan-aware token regex, scoped to this function only. Matches both abbreviated
    # (Gi1/0/1) and full (GigabitEthernet1/0/1) names, plus Vlan/Port-channel.
    tok_re = re.compile(
        r"\b(?:Vlan\d+|(?:Port-?channel|Po)\d+|[A-Za-z]{2,}\d+/\d+(?:/\d+)?)\b",
        re.IGNORECASE)
    res: Dict[str, List[str]] = {}

    if pim_out:
        _MODE = {"s": "Sparse", "d": "Dense", "sd": "Sparse-Dense", "ss": "Sparse"}
        for line in pim_out.splitlines():
            s = line.strip()
            if not s or s.lower().startswith(("address", "interface")):
                continue
            # Table row: '<ip> <interface> <ver/mode> ...'  (interface may be VlanN)
            mt = re.match(r"^(\d+\.\d+\.\d+\.\d+)\s+(\S+)\s+v?\d?\s*/?\s*([A-Za-z]+)?", s)
            if mt and is_valid_iface(mt.group(2)):
                intf = normalize_ifname(mt.group(2))
                mode = _MODE.get((mt.group(3) or "").lower(), "")
                res.setdefault(intf, []).append("PIM" + (f" {mode}" if mode else ""))
                continue
            # Some platforms: '<interface> is up, ... PIM ...'
            mi = re.match(r"^(Vlan\d+|\S+)\s+is\s+(?:up|down)", s, re.IGNORECASE)
            if mi and is_valid_iface(mi.group(1)):
                res.setdefault(normalize_ifname(mi.group(1)), []).append("PIM enabled")

    if mroute_out:
        for line in mroute_out.splitlines():
            low = line.lower()
            tag = "Mroute IIF" if "incoming interface" in low else (
                  "Mroute OIL" if ("outgoing" in low or line.startswith((" ", "\t"))) else "Mroute")
            for tok in tok_re.findall(line):
                res.setdefault(normalize_ifname(tok), []).append(tag)

    return {k: " / ".join(dict.fromkeys(v)) for k, v in res.items()}

# =============================================================================
# PHYSICAL PARSERS (NEW-V12)
# =============================================================================

def parse_show_version(output: str) -> Dict[str, str]:
    """Parse 'show version' for IOS/IOS-XE and NX-OS."""
    r: Dict[str, str] = {"model": "", "serial_number": "", "sw_version": "",
                          "uptime": "", "system_mac": "", "hostname_reported": ""}
    if not output:
        return r
    for line in output.splitlines():
        low = line.strip().lower()
        m = re.match(r"^cisco\s+(\S+)\s*(?:\(|processor|chassis|with)", line.strip(), re.IGNORECASE)
        if m and not r["model"]:
            cand = m.group(1).strip().rstrip(",")
            if len(cand) > 3 and not cand.lower().startswith(("ios","xe","nx")):
                r["model"] = cand
        m2 = re.match(r"^\s*cisco\s+(Nexus\S*|N\d[Kk]-\S+|\S+)\s+(?:chassis|switch)", line, re.IGNORECASE)
        if m2 and not r["model"]:
            r["model"] = m2.group(1).strip()
        m3 = re.search(r"(?:system serial number\s*[:=]|processor board id)\s*(\S+)", low)
        if m3 and not r["serial_number"]:
            r["serial_number"] = line.split()[-1].strip()
        m3b = re.match(r"^\s*Processor Board ID\s+(\S+)", line, re.IGNORECASE)
        if m3b and not r["serial_number"]:
            r["serial_number"] = m3b.group(1).strip()
        m4 = re.search(r"version\s+([\d\.()A-Za-z]+)", line, re.IGNORECASE)
        if m4 and not r["sw_version"] and any(k in low for k in ("ios","nx-os","nxos","software")):
            r["sw_version"] = m4.group(1).strip().rstrip(",")
        m4b = re.match(r"^\s*system:\s+version\s+(\S+)", line, re.IGNORECASE)
        if m4b:
            r["sw_version"] = m4b.group(1).strip()
        m5 = re.search(r"uptime is\s+(.+)", line, re.IGNORECASE)
        if m5 and not r["uptime"]:
            r["uptime"] = m5.group(1).strip().rstrip(".")
        m5b = re.search(r"kernel uptime is\s+(.+)", line, re.IGNORECASE)
        if m5b:
            r["uptime"] = m5b.group(1).strip()
        m6 = re.search(
            r"(?:base ethernet mac address|system mac address|mac address)\s*[:\-]?\s*"
            r"([0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}|(?:[0-9a-fA-F]{2}[:\-]){5}[0-9a-fA-F]{2})",
            line, re.IGNORECASE)
        if m6 and not r["system_mac"]:
            r["system_mac"] = normalize_mac(m6.group(1))
        m7 = re.match(r"^(\S+)\s+uptime is", line)
        if m7 and not r["hostname_reported"]:
            r["hostname_reported"] = m7.group(1).strip()
    return r


def _inv_commit(entry: Dict[str, str], result: Dict) -> None:
    """Classify one inventory entry and accumulate into result dict."""
    name  = (entry.get("name")  or "").lower().strip()
    descr = (entry.get("descr") or "").lower()
    pid   = (entry.get("pid")   or "")
    sn    = (entry.get("sn")    or "")
    pid_l = pid.lower()

    # Power supply: highest priority
    is_ps = (
        any(k in name  for k in ("power supply","psu","ps ","power-supply","power module")) or
        any(k in descr for k in ("power supply","psu","power-supply","power module"))       or
        bool(re.match(r"^(pwr-|n[0-9][kk]-pac|c[0-9]+-pwr|pwrs-|pwr[0-9])", pid_l))
    )

    # Module / linecard: check before chassis to avoid C9300-NM-* matching chassis
    _module_pid = bool(re.match(
        r"^(n[0-9][kk]-[mx]|n[0-9][kk]-lc|n[0-9][kk]-sup|"
        r"c[0-9]+-nm-|c[0-9]+-uadp|nm-|spa-|sm-)", pid_l))
    is_module = (
        not is_ps and (
            any(k in name  for k in ("module","linecard","line card","supervisor","sup","fabric")) or
            any(k in descr for k in ("linecard","supervisor","fabric",
                                     "uplink module","switching module","ethernet module",
                                     "network module")) or
            _module_pid
        )
    )

    # Chassis: the main switch body
    _chassis_pid = (
        bool(re.match(r"^(ws-c|n[0-9][kk]-c[0-9])", pid_l)) or
        bool(re.match(r"^c[0-9]{4}-[0-9]+[pg]", pid_l)) or
        bool(re.match(r"^n[0-9]{4}-[0-9]", pid_l)) or
        bool(re.match(r"^(n9k-c|n7k-c|n6k-c|n5k-c)", pid_l))
    )
    is_chassis = (
        not is_ps and not is_module and (
            name in ("1","switch","switch 1","chassis") or
            ("chassis" in name and "module" not in name) or
            ("chassis" in descr and "module" not in descr) or
            _chassis_pid
        )
    )

    if is_chassis and not result["chassis_model"]:
        result["chassis_model"]  = pid
        result["chassis_serial"] = sn
    if is_ps:
        result["num_power_supplies"] += 1
        if pid: result["ps_pids"].append(pid)
        if sn:  result["ps_serials"].append(sn)
    if is_module:
        result["num_modules"] += 1
        if pid: result["module_pids"].append(pid)


def parse_show_inventory(output: str) -> Dict[str, object]:
    """Parse 'show inventory' NAME/DESCR/PID/SN blocks (IOS + NX-OS)."""
    result = {"chassis_model":"","chassis_serial":"",
              "num_power_supplies":0,"ps_pids":[],"ps_serials":[],
              "num_modules":0,"module_pids":[]}
    if not output:
        return result
    current: Dict[str, str] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line:
            if current: _inv_commit(current, result)
            current = {}
            continue
        m_name = re.match(r'NAME:\s*"([^"]*)"\s*,?\s*DESCR:\s*"([^"]*)"', line, re.IGNORECASE)
        if m_name:
            if current: _inv_commit(current, result)
            current = {"name": m_name.group(1), "descr": m_name.group(2), "pid":"", "sn":""}
            continue
        m_pid = re.match(r'PID:\s*(\S*)\s*,\s*VID:\s*\S*\s*,\s*SN:\s*(\S*)', line, re.IGNORECASE)
        if m_pid:
            current["pid"] = m_pid.group(1).strip()
            current["sn"]  = m_pid.group(2).strip()
    if current: _inv_commit(current, result)
    return result


def parse_show_environment_power(output: str) -> Dict[str, object]:
    """Parse power capacity, draw, remaining and PS status lines."""
    r: Dict[str, object] = {"total_capacity_w":"","total_drawn_w":"",
                             "total_remaining_w":"","num_ps":0,"ps_status_list":[]}
    if not output:
        return r
    ps_list: List[str] = []
    for line in output.splitlines():
        low = line.strip().lower()
        # IOS one-liner: "Available:1100.0(w)  Used:207.4(w)  Remaining:892.6(w)"
        m = re.search(
            r"available\s*:\s*([\d\.]+)\s*\(w\).*?used\s*:\s*([\d\.]+)\s*\(w\).*?remaining\s*:\s*([\d\.]+)\s*\(w\)",
            low)
        if m:
            r["total_capacity_w"]  = m.group(1)
            r["total_drawn_w"]     = m.group(2)
            r["total_remaining_w"] = m.group(3)
        mc = re.search(r"(?:total power capacity|capacity)[^:]*:\s*([\d\.]+)\s*[wW]", low)
        if mc and not r["total_capacity_w"]: r["total_capacity_w"] = mc.group(1)
        mc2 = re.search(r"\bcapacity\s*:\s*([\d\.]+)\s*[wW]", low)
        if mc2 and not r["total_capacity_w"]: r["total_capacity_w"] = mc2.group(1)
        md = re.search(r"(?:total power output|used)[^:]*:\s*([\d\.]+)\s*[wW]", low)
        if md and not r["total_drawn_w"]: r["total_drawn_w"] = md.group(1)
        me = re.search(r"(?:total power available|remaining)[^:]*:\s*([\d\.]+)\s*[wW]", low)
        if me and not r["total_remaining_w"]: r["total_remaining_w"] = me.group(1)
        # PS status rows: lines starting with slot number or PS label
        if re.match(r"^\s*\d[AB]?\s+\S", line) or re.match(r"^\s*[Pp][Ss]\d?\s", line):
            if "ok" in low:                               ps_list.append("OK")
            elif "fail" in low:                           ps_list.append("FAIL")
            elif "absent" in low or "not present" in low: ps_list.append("ABSENT")
    if r["total_capacity_w"] and r["total_drawn_w"] and not r["total_remaining_w"]:
        try:
            r["total_remaining_w"] = str(round(
                float(r["total_capacity_w"]) - float(r["total_drawn_w"]), 1))
        except Exception as e:
            logger.debug(f"remaining-power calc failed (cap={r['total_capacity_w']} drawn={r['total_drawn_w']}): {e}")  # NEW-V3.23.1
    r["ps_status_list"] = ps_list
    r["num_ps"] = len(set(ps_list))
    return r


def parse_show_environment(output: str) -> Dict[str, str]:
    """Parse fan and temperature health from 'show environment' (IOS + NX-OS)."""
    r = {"fan_status":"","temperature_status":""}
    if not output:
        return r
    fan_states: List[str]  = []
    temp_states: List[str] = []
    for line in output.splitlines():
        low = line.strip().lower()
        if not low: continue
        mt = re.search(r"temperature\s+is\s+(ok|normal|warning|critical|alert)", low)
        if mt:
            temp_states.append({"ok":"OK","normal":"OK","warning":"Warning",
                                 "critical":"Critical","alert":"Warning"}.get(mt.group(1),""))
        mf = re.search(r"fan\s+is\s+(ok|normal|warning|failed|fault)", low)
        if mf:
            fan_states.append({"ok":"OK","normal":"OK","warning":"Warning",
                                "failed":"Failed","fault":"Failed"}.get(mf.group(1),""))
        if re.match(r"^\s*fan\d*\s+\S", low):
            if "ok" in low or "good" in low:       fan_states.append("OK")
            elif "fail" in low or "fault" in low:  fan_states.append("Failed")
            elif "warn" in low or "minor" in low:  fan_states.append("Warning")
        if re.match(r"^\s*\d+\s+\S", low) and any(k in low for k in ("inlet","outlet","sensor")):
            if "ok" in low or "normal" in low:        temp_states.append("OK")
            elif "critical" in low or "major" in low: temp_states.append("Critical")
            elif "warn" in low or "minor" in low:     temp_states.append("Warning")
    def _worst(states: List[str]) -> str:
        if "Critical" in states or "Failed" in states: return "Critical/Failed"
        if "Warning"  in states: return "Warning"
        if "OK"       in states: return "OK"
        return ""
    r["fan_status"]         = _worst(fan_states)
    r["temperature_status"] = _worst(temp_states)
    return r


def parse_show_module_count(output: str) -> int:
    """Count occupied module slots from 'show module' (NX-OS)."""
    count = 0
    for line in output.splitlines():
        m = re.match(r"^\s*(\d+)\s+\d+\s+(\S+)", line)
        if m and m.group(2).upper() not in ("N/A","--","NONE","EMPTY"):
            count += 1
    return count

# =============================================================================
# BUILD PHYSICAL DEVICE SUMMARY (NEW-V12)
# =============================================================================
def build_device_physical(hostname: str, platform: str,
                           cmd_to_file: Dict[str, str],
                           interfaces: Dict) -> DevicePhysical:
    """Build switch-level physical data for the site survey sheet."""
    dp = DevicePhysical(hostname=hostname, platform=platform)

    ver_out = _load_cmd_output(cmd_to_file, "show version")
    if ver_out:
        ver = parse_show_version(ver_out)
        dp.model         = ver.get("model", "")
        dp.serial_number = ver.get("serial_number", "")
        dp.sw_version    = ver.get("sw_version", "")
        dp.uptime        = ver.get("uptime", "")
        dp.system_mac    = ver.get("system_mac", "")

    inv_out = _load_cmd_output(cmd_to_file, "show inventory")
    if inv_out:
        inv = parse_show_inventory(inv_out)
        if inv.get("chassis_model"):
            dp.model = inv["chassis_model"]
        if inv.get("chassis_serial"):
            dp.serial_number  = inv["chassis_serial"]
            dp.chassis_serial = inv["chassis_serial"]
        if inv.get("num_power_supplies", 0):
            dp.num_power_supplies = inv["num_power_supplies"]
        if inv.get("num_modules", 0):
            dp.num_modules = inv["num_modules"]

    pwr_out = _load_cmd_output(cmd_to_file, "show environment power", "show power")
    if pwr_out:
        pwr = parse_show_environment_power(pwr_out)
        if pwr.get("total_capacity_w"):  dp.power_capacity_w  = pwr["total_capacity_w"]  + " W"
        if pwr.get("total_drawn_w"):     dp.power_drawn_w     = pwr["total_drawn_w"]      + " W"
        if pwr.get("total_remaining_w"): dp.power_remaining_w = pwr["total_remaining_w"]  + " W"
        if pwr.get("num_ps", 0) > dp.num_power_supplies:
            dp.num_power_supplies = pwr["num_ps"]
        ps_list = [s for s in pwr.get("ps_status_list", []) if s]
        if ps_list:
            dp.ps_status = " / ".join(list(dict.fromkeys(ps_list)))

    mod_out = _load_cmd_output(cmd_to_file, "show module")
    if mod_out and dp.num_modules == 0:
        dp.num_modules = parse_show_module_count(mod_out)

    env_out = _load_cmd_output(cmd_to_file, "show environment")
    if env_out:
        env = parse_show_environment(env_out)
        dp.fan_status         = env.get("fan_status", "")
        dp.temperature_status = env.get("temperature_status", "")

    physical = [p for p in interfaces
                if PHYSICAL_IFACE_RE.match(normalize_ifname(p))
                and not normalize_ifname(p).startswith("Po")]
    dp.total_ports  = len(physical)
    dp.active_ports = sum(1 for p in physical
                          if interfaces[p].status in ("connected","up"))
    return dp

# =============================================================================
# SITE SURVEY SHEET WRITER (NEW-V12)
# =============================================================================
INVENTORY_SHEET_NAME = "Switch Inventory"

INVENTORY_COLUMNS = [
    ("Hostname",            "hostname"),
    ("Platform",            "platform"),
    ("Model / PID",         "model"),
    ("Serial Number",       "serial_number"),
    ("Chassis Serial",      "chassis_serial"),
    ("SW Version",          "sw_version"),
    ("Uptime",              "uptime"),
    ("System MAC",          "system_mac"),
    ("# Power Supplies",    "num_power_supplies"),
    ("PS Status",           "ps_status"),
    ("Power Capacity (W)",  "power_capacity_w"),
    ("Power Drawn (W)",     "power_drawn_w"),
    ("Power Remaining (W)", "power_remaining_w"),
    ("# Modules",           "num_modules"),
    ("Total Ports",         "total_ports"),
    ("Active Ports",        "active_ports"),
    ("Fan Status",          "fan_status"),
    ("Temperature Status",  "temperature_status"),
]

def write_device_inventory_sheet(wb, all_device_physical: List[DevicePhysical]) -> None:
    """Write (or replace) 'Switch Inventory' sheet with one row per switch."""

    if INVENTORY_SHEET_NAME in wb.sheetnames:
        del wb[INVENTORY_SHEET_NAME]
    ws = wb.create_sheet(INVENTORY_SHEET_NAME)

    HDR_FONT  = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
    HDR_FILL  = PatternFill("solid", fgColor="1F497D")
    HDR_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
    DAT_FONT  = Font(name="Calibri", size=10)
    DAT_L     = Alignment(horizontal="left",   vertical="center")
    DAT_C     = Alignment(horizontal="center", vertical="center")
    _NUM      = {"num_power_supplies","num_modules","total_ports","active_ports"}

    for col, (header, _) in enumerate(INVENTORY_COLUMNS, 1):
        c = ws.cell(row=1, column=col, value=header)
        c.font = HDR_FONT; c.fill = HDR_FILL; c.alignment = HDR_ALIGN
    ws.row_dimensions[1].height = 30

    for row, dp in enumerate(all_device_physical, 2):
        for col, (_, field) in enumerate(INVENTORY_COLUMNS, 1):
            val = getattr(dp, field, "")
            if val == 0: val = ""
            c = ws.cell(row=row, column=col, value=val)
            c.font = DAT_FONT
            c.alignment = DAT_C if field in _NUM else DAT_L

    for col, (header, _) in enumerate(INVENTORY_COLUMNS, 1):
        mx = len(header)
        for row in range(2, len(all_device_physical) + 2):
            v = ws.cell(row=row, column=col).value
            if v: mx = max(mx, len(str(v)))
        ws.column_dimensions[get_column_letter(col)].width = min(max(mx + 2, 12), 48)

    ws.freeze_panes = "A2"
    logger.info(f"  [OK] '{INVENTORY_SHEET_NAME}' sheet: {len(all_device_physical)} device(s)")

# =============================================================================
# NEW-V14.3: SVI / Gateway sheet (one row per SVI) - surfaces the per-SVI routing,
# HSRP and multicast data that the interface sheet excludes by design.
# =============================================================================
SVI_SHEET_NAME = "SVI Gateway"

SVI_COLUMNS = [
    ("Hostname",               "hostname"),
    ("SVI",                    "port"),
    ("Description",            "description"),
    ("VLAN",                   "vlan"),
    ("VRF",                    "vrf"),
    ("Gateway IP (configured)","svi_ip"),
    ("Subnet / Primary Route", "subnet_primary_route"),
    ("Routing Source",         "routing_source"),
    ("Route Next Hop",         "route_next_hop"),
    ("Secondary Routes",       "subnet_secondary_routes"),
    ("FHRP Behavior",          "hsrp_behavior"),
    ("Multicast Info",         "multicast_info"),
    ("Switch Serial",          "current_switch_serial"),
    ("Switch Mgmt IP",         "current_switch_ip"),
    ("VTP Domain",             "current_switch_vtp_domain"),
]

def _is_svi(port: str) -> bool:
    return bool(re.match(r"^Vlan\d+$", (port or "").strip(), re.IGNORECASE))

def write_svi_gateway_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> None:
    """Write (or replace) 'SVI Gateway' sheet: one row per SVI across all devices.

    This is the home for the per-SVI fields (routing / HSRP / multicast) that
    append_interface_rows() intentionally skips, since the interface sheet drops
    Vlan/loopback/tunnel rows. Physical-port rows are unaffected.
    """

    if SVI_SHEET_NAME in wb.sheetnames:
        del wb[SVI_SHEET_NAME]
    ws = wb.create_sheet(SVI_SHEET_NAME)

    HDR_FONT  = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
    HDR_FILL  = PatternFill("solid", fgColor="1F497D")
    HDR_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
    DAT_FONT  = Font(name="Calibri", size=10)
    DAT_L     = Alignment(horizontal="left",   vertical="center")

    for col, (header, _) in enumerate(SVI_COLUMNS, 1):
        c = ws.cell(row=1, column=col, value=header)
        c.font = HDR_FONT; c.fill = HDR_FILL; c.alignment = HDR_ALIGN
    ws.row_dimensions[1].height = 30

    # Collect SVIs, sorted by hostname then numeric VLAN id for a stable, readable sheet.
    rows: List[Tuple[str, InterfaceData]] = []
    for hostname, ifaces in all_interfaces.items():
        for port, d in ifaces.items():
            if _is_svi(port):
                rows.append((hostname, d))
    def _vlan_id(p: str) -> int:
        m = re.search(r"(\d+)", p or "")
        return int(m.group(1)) if m else 0
    rows.sort(key=lambda hd: (hd[0].lower(), _vlan_id(hd[1].port)))

    r = 2
    for hostname, d in rows:
        for col, (_, field) in enumerate(SVI_COLUMNS, 1):
            val = hostname if field == "hostname" else getattr(d, field, "")
            c = ws.cell(row=r, column=col, value=val)
            c.font = DAT_FONT; c.alignment = DAT_L
        r += 1

    for col, (header, _) in enumerate(SVI_COLUMNS, 1):
        mx = len(header)
        for row in range(2, r):
            v = ws.cell(row=row, column=col).value
            if v: mx = max(mx, len(str(v)))
        ws.column_dimensions[get_column_letter(col)].width = min(max(mx + 2, 12), 48)

    ws.freeze_panes = "A2"
    logger.info(f"  [OK] '{SVI_SHEET_NAME}' sheet: {len(rows)} SVI(s)")


# =============================================================================
# NEW-V14.7: STP Detail sheet (one row per STP port) - shows WHICH VLANs each port
# forwards vs blocks, instead of the single collapsed state on the interface sheet.
# =============================================================================
STP_SHEET_NAME = "STP Detail"

STP_COLUMNS = [
    ("Hostname",          "hostname"),
    ("Port",              "port"),
    ("STP Summary",       "_summary"),       # computed: Forwarding / Blocked / Mixed (FWD+BLK)
    ("Forwarding VLANs",  "stp_fwd_vlans"),
    ("Blocked VLANs",     "stp_blk_vlans"),
    ("Other (Lis/Lrn/Dis)", "stp_other_vlans"),
]

def write_stp_detail_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> None:
    """Write (or replace) 'STP Detail': one row per port that appears in 'show spanning-tree',
    with the per-VLAN forwarding/blocking breakdown. Ports with no STP data are omitted.
    Under MST the VLAN columns hold MST instance numbers (see header note in the docs)."""

    if STP_SHEET_NAME in wb.sheetnames:
        del wb[STP_SHEET_NAME]
    ws = wb.create_sheet(STP_SHEET_NAME)

    HDR_FONT  = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
    HDR_FILL  = PatternFill("solid", fgColor="1F497D")
    HDR_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
    DAT_FONT  = Font(name="Calibri", size=10)
    DAT_L     = Alignment(horizontal="left", vertical="center")

    for col, (header, _) in enumerate(STP_COLUMNS, 1):
        c = ws.cell(row=1, column=col, value=header)
        c.font = HDR_FONT; c.fill = HDR_FILL; c.alignment = HDR_ALIGN
    ws.row_dimensions[1].height = 30

    rows: List[Tuple[str, InterfaceData]] = []
    for hostname, ifaces in all_interfaces.items():
        for d in ifaces.values():
            if d.stp_fwd_vlans or d.stp_blk_vlans or d.stp_other_vlans:
                rows.append((hostname, d))

    def _natkey(hd):
        host, d = hd
        m = re.findall(r"\d+", d.port or "")
        return (host.lower(), d.port[:2].lower(), [int(x) for x in m])
    rows.sort(key=_natkey)

    def _summary(d: InterfaceData) -> str:
        f, b = bool(d.stp_fwd_vlans), bool(d.stp_blk_vlans)
        if f and b: return "Mixed (FWD+BLK)"
        if b:       return "Blocked"
        if f:       return "Forwarding"
        return d.stp_other_vlans and "Transitional" or ""

    r = 2
    for hostname, d in rows:
        for col, (_, field) in enumerate(STP_COLUMNS, 1):
            if field == "hostname":  val = hostname
            elif field == "_summary": val = _summary(d)
            else:                     val = getattr(d, field, "")
            c = ws.cell(row=r, column=col, value=val)
            c.font = DAT_FONT; c.alignment = DAT_L
        r += 1

    for col, (header, _) in enumerate(STP_COLUMNS, 1):
        mx = len(header)
        for row in range(2, r):
            v = ws.cell(row=row, column=col).value
            if v: mx = max(mx, len(str(v)))
        ws.column_dimensions[get_column_letter(col)].width = min(max(mx + 2, 12), 48)

    ws.freeze_panes = "A2"
    logger.info(f"  [OK] '{STP_SHEET_NAME}' sheet: {len(rows)} STP port(s)")


# =============================================================================
# NEW-V14.8: VLAN Census + Endpoint Census sheets (aggregations of the interface DB).
# =============================================================================
VLAN_CENSUS_SHEET_NAME = "VLAN Census"
ENDPOINT_CENSUS_SHEET_NAME = "Endpoint Census"

_CENSUS_HDR_FILL = "1F497D"

def _census_header(ws, columns):
    hf = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
    fill = PatternFill("solid", fgColor=_CENSUS_HDR_FILL)
    al = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for col, header in enumerate(columns, 1):
        c = ws.cell(row=1, column=col, value=header)
        c.font = hf; c.fill = fill; c.alignment = al
    ws.row_dimensions[1].height = 30

def _census_autofit(ws, ncols, nrows):
    for col in range(1, ncols + 1):
        mx = len(str(ws.cell(row=1, column=col).value or ""))
        for row in range(2, nrows + 1):
            v = ws.cell(row=row, column=col).value
            if v: mx = max(mx, len(str(v)))
        ws.column_dimensions[get_column_letter(col)].width = min(max(mx + 2, 12), 48)
    ws.freeze_panes = "A2"

def _split_macs(s: str) -> List[str]:
    return [t for t in re.split(r"[,\s;]+", s or "") if t]

def write_vlan_census_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> None:
    """One row per in-use VLAN (has access ports and/or an SVI), aggregated across all
    devices: where it lives, access-port and endpoint (MAC) counts, and its gateway/SVI."""
    cols = ["VLAN ID", "Name", "# Switches", "Switches", "# Access Ports", "# Endpoints",
            "Gateway Switch(es)", "Gateway IP", "Subnet", "FHRP"]
    if VLAN_CENSUS_SHEET_NAME in wb.sheetnames:
        del wb[VLAN_CENSUS_SHEET_NAME]
    ws = wb.create_sheet(VLAN_CENSUS_SHEET_NAME)
    _census_header(ws, cols)

    agg: Dict[int, Dict[str, object]] = {}
    def fresh():
        return {"name": "", "switches": set(), "access_ports": 0, "macs": set(),
                "gw_switches": set(), "gw_ip": "", "subnet": "", "fhrp": ""}
    for hostname, ifaces in all_interfaces.items():
        for port, d in ifaces.items():
            # access ports in this VLAN
            if (d.switchport_mode or "") == "Access" and d.vlan.isdigit():
                vid = int(d.vlan); a = agg.setdefault(vid, fresh())
                a["switches"].add(hostname); a["access_ports"] += 1
                if d.vlan_name and not a["name"]: a["name"] = d.vlan_name
                for mac in _split_macs(d.end_host_mac): a["macs"].add(mac)
            # SVI = the gateway for this VLAN
            m = re.match(r"^Vlan(\d+)$", port, re.IGNORECASE)
            if m:
                vid = int(m.group(1)); a = agg.setdefault(vid, fresh())
                a["gw_switches"].add(hostname)
                if d.vlan_name and not a["name"]: a["name"] = d.vlan_name
                if d.svi_ip and not a["gw_ip"]: a["gw_ip"] = d.svi_ip
                if d.subnet_primary_route and not a["subnet"]: a["subnet"] = d.subnet_primary_route
                if d.hsrp_behavior and not a["fhrp"]: a["fhrp"] = d.hsrp_behavior

    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="center")
    r = 2
    for vid in sorted(agg.keys()):
        a = agg[vid]
        vals = [vid, a["name"], len(a["switches"]), ", ".join(sorted(a["switches"])),
                a["access_ports"], len(a["macs"]),
                ", ".join(sorted(a["gw_switches"])), a["gw_ip"], a["subnet"], a["fhrp"]]
        for col, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT; c.alignment = DAT_L
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    logger.info(f"  [OK] '{VLAN_CENSUS_SHEET_NAME}' sheet: {len(agg)} VLAN(s)")

def write_endpoint_census_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> None:
    """Flat list of endpoints across all devices: one row per port that has a learned MAC."""
    cols = ["Hostname", "Port", "VLAN", "VLAN Name", "MAC Address", "IP Address",
            "Endpoint Type", "Location", "CDP/LLDP Neighbor"]
    if ENDPOINT_CENSUS_SHEET_NAME in wb.sheetnames:
        del wb[ENDPOINT_CENSUS_SHEET_NAME]
    ws = wb.create_sheet(ENDPOINT_CENSUS_SHEET_NAME)
    _census_header(ws, cols)

    rows: List[Tuple[str, InterfaceData]] = []
    for hostname, ifaces in all_interfaces.items():
        for d in ifaces.values():
            if d.end_host_mac and (d.switchport_mode or "") != "Trunk":
                rows.append((hostname, d))
    def _key(hd):
        host, d = hd
        vid = int(d.vlan) if d.vlan.isdigit() else 0
        nums = [int(x) for x in re.findall(r"\d+", d.port or "")]
        return (host.lower(), vid, d.port[:2].lower(), nums)
    rows.sort(key=_key)

    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="center")
    r = 2
    for hostname, d in rows:
        vals = [hostname, d.port, d.vlan, d.vlan_name, d.end_host_mac, d.end_host_ip,
                d.endpoint_type, d.endpoint_location, d.cdp_neighbor]
        for col, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT; c.alignment = DAT_L
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    logger.info(f"  [OK] '{ENDPOINT_CENSUS_SHEET_NAME}' sheet: {len(rows)} endpoint(s)")


# =============================================================================
# NEW-V14.9: Move-group planning. Switches that share an L2 broadcast domain must
# migrate together; connected components over "shared-VLAN" edges = migration waves.
# Captures transitive coupling (A-VLAN10-B, B-VLAN20-C => A,B,C are one group) that
# is easy to miss by eye. Coupling uses ACTUAL VLAN presence (access port or SVI),
# consistent with the VLAN Census; trunk-allowed-only transit is NOT modeled, and
# VLAN 1 (default, present everywhere) is excluded from grouping by design.
# =============================================================================
MOVEGROUP_SHEET_NAME = "Move Groups"
MOVEGROUP_EXCLUDED_VLANS = {1}   # default VLAN; would collapse all switches into one group

def _uf_find(parent: Dict[str, str], x: str) -> str:
    root = x
    while parent[root] != root:
        root = parent[root]
    while parent[x] != root:        # path compression
        parent[x], x = root, parent[x]
    return root

def _uf_union(parent: Dict[str, str], a: str, b: str) -> None:
    ra, rb = _uf_find(parent, a), _uf_find(parent, b)
    if ra != rb:
        parent[rb] = ra

def compute_move_groups(all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> List[Dict[str, object]]:
    """Return migration move-groups (connected components of the shared-VLAN graph).

    Each group dict: switches(list), spanning_vlans(list[(vid,name,nswitches)]),
    endpoints(int), gateways(list[str]), blocked_paths(list[str]), vlan1_spans(bool).
    """
    # VLAN -> presence set, plus metadata, mirroring the VLAN Census definition.
    vlan_switches: Dict[int, set] = {}
    vlan_name: Dict[int, str] = {}
    group_endpoints: Dict[str, set] = {h: set() for h in all_interfaces}
    gateways: Dict[int, set] = {}
    blocked: List[Tuple[str, str, str]] = []   # (host, port, blocked_vlans)

    for host, ifaces in all_interfaces.items():
        for port, d in ifaces.items():
            if (d.switchport_mode or "") == "Access" and d.vlan.isdigit():
                vid = int(d.vlan)
                vlan_switches.setdefault(vid, set()).add(host)
                if d.vlan_name and vid not in vlan_name: vlan_name[vid] = d.vlan_name
                for mac in _split_macs(d.end_host_mac):
                    group_endpoints[host].add(mac)
            m = re.match(r"^Vlan(\d+)$", port, re.IGNORECASE)
            if m:
                vid = int(m.group(1))
                vlan_switches.setdefault(vid, set()).add(host)
                gateways.setdefault(vid, set()).add(host)
                if d.vlan_name and vid not in vlan_name: vlan_name[vid] = d.vlan_name
            if d.stp_blk_vlans:
                blocked.append((host, port, d.stp_blk_vlans))

    # Union-find over ALL switches (every switch is at least its own group).
    parent = {h: h for h in all_interfaces}
    for vid, sws in vlan_switches.items():
        if vid in MOVEGROUP_EXCLUDED_VLANS or len(sws) < 2:
            continue
        sws_l = sorted(sws)
        for other in sws_l[1:]:
            _uf_union(parent, sws_l[0], other)

    # Collect components.
    comps: Dict[str, List[str]] = {}
    for h in all_interfaces:
        comps.setdefault(_uf_find(parent, h), []).append(h)

    groups: List[Dict[str, object]] = []
    for root, members in comps.items():
        mset = set(members)
        spanning = []
        vlan1_spans = False
        for vid, sws in vlan_switches.items():
            in_grp = sws & mset
            if len(in_grp) >= 2:
                if vid in MOVEGROUP_EXCLUDED_VLANS:
                    vlan1_spans = True
                else:
                    spanning.append((vid, vlan_name.get(vid, ""), len(in_grp)))
        spanning.sort(key=lambda t: (-t[2], t[0]))
        gw = sorted({f"{h}:Vlan{vid}" for vid, sws in gateways.items()
                     for h in (sws & mset)})
        blk = sorted({f"{h}/{p} blocks {v}" for (h, p, v) in blocked if h in mset})
        groups.append({
            "switches": sorted(members),
            "spanning_vlans": spanning,
            "endpoints": sum(len(group_endpoints[h]) for h in members),
            "gateways": gw,
            "blocked_paths": blk,
            "vlan1_spans": vlan1_spans,
        })
    # Biggest blast radius first.
    groups.sort(key=lambda g: (-len(g["switches"]), -len(g["spanning_vlans"]),
                               g["switches"][0] if g["switches"] else ""))
    return groups

def write_move_group_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> None:
    """Write (or replace) 'Move Groups': one row per migration wave (connected component
    of the shared-VLAN graph), ordered largest-coupling first."""
    cols = ["Group", "# Switches", "Switches", "# Spanning VLANs", "Spanning VLANs",
            "# Endpoints", "Gateways", "Redundant (STP-blocked) Paths", "Notes"]
    if MOVEGROUP_SHEET_NAME in wb.sheetnames:
        del wb[MOVEGROUP_SHEET_NAME]
    ws = wb.create_sheet(MOVEGROUP_SHEET_NAME)
    _census_header(ws, cols)

    groups = compute_move_groups(all_interfaces)
    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="top", wrap_text=True)

    r = 2
    for i, g in enumerate(groups, 1):
        span_txt = ", ".join(f"{vid}{'('+name+')' if name else ''}[x{n}]"
                             for vid, name, n in g["spanning_vlans"])
        notes = []
        if len(g["switches"]) == 1:
            notes.append("Standalone — migrate independently, any order")
        else:
            notes.append("Migrate together — shared L2 broadcast domain(s)")
        if g["vlan1_spans"]:
            notes.append("VLAN 1 also spans group (default, excluded from grouping)")
        if g["blocked_paths"]:
            notes.append("Has redundant blocked path(s) — verify before cutover")
        vals = [f"Group {i}", len(g["switches"]), ", ".join(g["switches"]),
                len(g["spanning_vlans"]), span_txt, g["endpoints"],
                ", ".join(g["gateways"]), "; ".join(g["blocked_paths"]), " | ".join(notes)]
        for col, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT; c.alignment = DAT_L
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    # widen the two free-text columns
    ws.column_dimensions["E"].width = 40
    ws.column_dimensions["I"].width = 48
    logger.info(f"  [OK] '{MOVEGROUP_SHEET_NAME}' sheet: {len(groups)} group(s)")


# =============================================================================
# NEW-V14.10: Physical topology / inter-switch link map from CDP/LLDP. Deduplicates
# the two directed views of each physical link (A sees B, B sees A) into one
# canonical undirected row, and flags links confirmed from both ends vs one end.
# =============================================================================
TOPOLOGY_SHEET_NAME = "Topology Links"

def _is_infra_neighbor(d: InterfaceData, scanned_hosts: set) -> bool:
    """A link endpoint is infrastructure (switch/router) if its endpoint_type says so
    or the neighbor name matches a scanned device. Excludes host endpoints (phones, APs...)."""
    if (d.endpoint_type or "") in ("Switch", "Router"):
        return True
    nb = _canon_host(d.cdp_neighbor)
    return bool(nb and nb in scanned_hosts)

def _canon_host(name: str) -> str:
    """Normalize a neighbor device-id for matching: strip FQDN domain + serial suffix '(FOC...)'."""
    n = (name or "").strip()
    n = re.sub(r"\(.*?\)\s*$", "", n).strip()   # drop trailing '(serial)'
    n = n.split(".")[0]                          # drop FQDN domain
    return n.lower()

def write_topology_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> None:
    """Write (or replace) 'Topology Links': one row per physical inter-switch link,
    discovered from CDP/LLDP and de-duplicated across both endpoints' views."""
    cols = ["Switch A", "Port A", "Switch B", "Port B", "Neighbor Platform",
            "Link Speed", "Confirmation"]
    if TOPOLOGY_SHEET_NAME in wb.sheetnames:
        del wb[TOPOLOGY_SHEET_NAME]
    ws = wb.create_sheet(TOPOLOGY_SHEET_NAME)
    _census_header(ws, cols)

    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="center")
    ordered = compute_topology_links(all_interfaces)   # V3.15.0: shared link builder
    r = 2
    for rec in ordered:
        vals = [rec["a_host"], rec["a_port"], rec["b_host"], rec["b_port"],
                rec["platform"], rec["speed"], rec["confirmation"]]
        for col, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT; c.alignment = DAT_L
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    logger.info(f"  [OK] '{TOPOLOGY_SHEET_NAME}' sheet: {len(ordered)} link(s)")


def build_switch_identity(hostname: str, platform: str, cmd_to_file: Dict[str, str]) -> Dict[str, str]:
    ident = {
        'hostname': hostname,
        'serial_number': '',
        'mgmt_ip': '',
        'vtp_domain': ''
    }
    ver_out = _load_cmd_output(cmd_to_file, 'show version')
    if ver_out:
        ident['serial_number'] = parse_show_version(ver_out).get('serial_number', '')
    inv_out = _load_cmd_output(cmd_to_file, 'show inventory')
    if inv_out:
        inv = parse_show_inventory(inv_out)
        ident['serial_number'] = inv.get('chassis_serial', '') or ident['serial_number']
    ident['vtp_domain'] = parse_vtp_status(_load_cmd_output(cmd_to_file, 'show vtp status'))
    # NEW-V14.4: the switch's OWN management IP (was wrongly taken from a neighbor's CDP/LLDP).
    ipbrief = "\n".join(filter(None, [
        _load_cmd_output(cmd_to_file, 'show ip interface brief'),
        _load_cmd_output(cmd_to_file, 'show ip interface brief vrf management'),
    ]))
    run_if = parse_run_config_interfaces(
        _load_cmd_output(cmd_to_file, 'show running-config | section ^interface',
                         'show running-config'))
    ident['mgmt_ip'] = parse_switch_mgmt_ip(ipbrief, run_if)
    return ident

# =============================================================================
# BUILD INTERFACE DB (per device)
# =============================================================================
def build_interfaces(hostname: str, platform: str, cmd_to_file: Dict[str, str],
                     switch_identity: Optional[Dict[str, str]] = None) -> Dict[str, InterfaceData]:
    interfaces: Dict[str, InterfaceData] = {}
    switch_identity = switch_identity or {}

    # 1) show interface status
    st_out = _load_cmd_output(cmd_to_file, "show interface status")
    for p, v in (parse_show_interface_status(st_out) if st_out else {}).items():
        interfaces.setdefault(p, InterfaceData(port=p))
        interfaces[p].status    = v.get("status","")
        interfaces[p].duplex    = v.get("duplex","")
        interfaces[p].speed     = v.get("speed","")
        interfaces[p].port_type = v.get("type","")
        name = (v.get("name") or "").strip()
        if name and name != "--":
            interfaces[p].description = interfaces[p].description or name

    # 2) switchport
    sw_out = _load_cmd_output(cmd_to_file, "show interface switchport", "show interfaces switchport")
    for p, v in (parse_show_interface_switchport(sw_out) if sw_out else {}).items():
        interfaces.setdefault(p, InterfaceData(port=p))
        interfaces[p].switchport_mode = v.get("mode","") or interfaces[p].switchport_mode
        if interfaces[p].switchport_mode == "Access":
            interfaces[p].vlan      = v.get("access_vlan","")      or interfaces[p].vlan
            interfaces[p].vlan_name = v.get("access_vlan_name","") or interfaces[p].vlan_name

    # 3) trunk table
    tr_out = _load_cmd_output(cmd_to_file, "show interface trunk", "show interfaces trunk")
    for p, v in (parse_show_interface_trunk_table(tr_out) if tr_out else {}).items():
        interfaces.setdefault(p, InterfaceData(port=p))
        tstat = (v.get("status") or "")
        if tstat: interfaces[p].trunk_status = tstat
        if tstat.lower() in ("trunking","trnk-bndl"): interfaces[p].switchport_mode = "Trunk"
        if v.get("native_vlan"):   interfaces[p].trunk_native_vlan  = v["native_vlan"]
        if v.get("allowed_vlans"): interfaces[p].trunk_allowed_vlans = v["allowed_vlans"]
        if v.get("port_channel") and not interfaces[p].port_channel:
            interfaces[p].port_channel = v["port_channel"]

    # 4) running-config
    run_out = _load_cmd_output(cmd_to_file,
                               "show running-config interface",
                               "show running-config | section ^interface")
    run_iface  = parse_run_config_interfaces(run_out) if run_out else {}
    global_run = _load_cmd_output(cmd_to_file, "show running-config")
    global_bdg = bool(re.search(r"spanning-tree portfast bpduguard default", global_run, re.IGNORECASE))
    if global_bdg:
        logger.info(f"  [STP] Global portfast bpduguard default enabled on {hostname}")
    for p, v in run_iface.items():
        interfaces.setdefault(p, InterfaceData(port=p))
        if v.get("desc") and not interfaces[p].description:
            interfaces[p].description = v["desc"]
        if v.get("bpduguard"):
            interfaces[p].stp_bpduguard = v["bpduguard"]
        elif global_bdg and interfaces[p].switchport_mode in ("Access",""):
            interfaces[p].stp_bpduguard = "Enable"
        if v.get("rootguard"): interfaces[p].stp_rootguard = v["rootguard"]
        if v.get("vrf"):       interfaces[p].vrf            = v["vrf"]
        if v.get("ip_addr"):   interfaces[p].svi_ip         = v["ip_addr"]  # NEW-V14.3
        if v.get("pc_id") and not interfaces[p].port_channel:
            interfaces[p].port_channel = v["pc_id"]
        if v.get("pc_mode") and not interfaces[p].port_channel_protocol:
            mode = v["pc_mode"].lower()
            interfaces[p].port_channel_protocol = "Active" if mode == "active" else "On"

    # 5) VRF
    vrf_out = _load_cmd_output(cmd_to_file, "show vrf interface", "show ip vrf interface",
                               "show ip vrf interfaces")
    for p, vrf in (parse_show_vrf_interface(vrf_out) if vrf_out else {}).items():
        interfaces.setdefault(p, InterfaceData(port=p))
        if vrf and not interfaces[p].vrf: interfaces[p].vrf = vrf

    # 6) etherchannel / port-channel
    pc_out = _load_cmd_output(cmd_to_file, "show port-channel summary", "show etherchannel summary")
    pc_proto: Dict[str, str] = {}
    po_members: Dict[str, str] = {}
    if pc_out:
        pc_proto   = parse_portchannel_protocol_from_summary(pc_out)
        if not pc_proto: pc_proto = parse_etherchannel_protocol_ios(pc_out)
        po_members = parse_etherchannel_summary_members(pc_out)

    for po, proto in pc_proto.items():
        interfaces.setdefault(po, InterfaceData(port=po))
        interfaces[po].port_channel          = po
        interfaces[po].port_channel_protocol = proto

    for phys, po_name in po_members.items():
        interfaces.setdefault(phys, InterfaceData(port=phys))
        if not interfaces[phys].port_channel:
            interfaces[phys].port_channel          = po_name
        if not interfaces[phys].port_channel_protocol:
            interfaces[phys].port_channel_protocol = pc_proto.get(po_name, "")
        interfaces.setdefault(po_name, InterfaceData(port=po_name))
        if not interfaces[po_name].port_channel:
            interfaces[po_name].port_channel          = po_name
        if not interfaces[po_name].port_channel_protocol:
            interfaces[po_name].port_channel_protocol = pc_proto.get(po_name, "")

    for p, v in run_iface.items():
        if v.get("pc_id"):
            po_name_rc = v["pc_id"]
            interfaces.setdefault(p, InterfaceData(port=p))
            if not interfaces[p].port_channel:
                interfaces[p].port_channel          = po_name_rc
            if not interfaces[p].port_channel_protocol:
                interfaces[p].port_channel_protocol = pc_proto.get(po_name_rc, "")
            interfaces.setdefault(po_name_rc, InterfaceData(port=po_name_rc))
            if not interfaces[po_name_rc].port_channel:
                interfaces[po_name_rc].port_channel          = po_name_rc
            if not interfaces[po_name_rc].port_channel_protocol:
                interfaces[po_name_rc].port_channel_protocol = pc_proto.get(po_name_rc, "")

    for p in list(interfaces.keys()):
        if p.startswith("Po") and not interfaces[p].port_channel:
            interfaces[p].port_channel = p

    # 7) MAC table + Po member propagation
    mac_out = _load_cmd_output(cmd_to_file, "show mac address-table")
    mac_map = parse_show_mac_address_table(mac_out) if mac_out else {}
    for intf, macs in mac_map.items():
        if not macs: continue
        interfaces.setdefault(intf, InterfaceData(port=intf))
        if not interfaces[intf].end_host_mac:
            interfaces[intf].end_host_mac = ", ".join(macs[:5])
    for phys, po_name in po_members.items():
        if po_name in interfaces and interfaces[po_name].end_host_mac:
            interfaces.setdefault(phys, InterfaceData(port=phys))
            if not interfaces[phys].end_host_mac:
                interfaces[phys].end_host_mac = interfaces[po_name].end_host_mac
        if phys in interfaces and interfaces[phys].end_host_mac:
            interfaces.setdefault(po_name, InterfaceData(port=po_name))
            if not interfaces[po_name].end_host_mac:
                interfaces[po_name].end_host_mac = interfaces[phys].end_host_mac

    # 8) STP state (V3.14.5: read from STP data only — never inferred from link-up).
    stp_out = _load_cmd_output(cmd_to_file, "show spanning-tree")
    blocked = parse_spanning_tree_blockedports(
        _load_cmd_output(cmd_to_file, "show spanning-tree blockedports"))
    incons  = parse_spanning_tree_blockedports(
        _load_cmd_output(cmd_to_file, "show spanning-tree inconsistentports"))
    stp_states = parse_spanning_tree_states(stp_out)
    stp_detail = parse_spanning_tree_detail(stp_out)   # NEW-V14.7 per-VLAN breakdown
    for p, d in interfaces.items():
        if blocked.get(p):
            interfaces[p].stp_blocked = "Blocked"
        elif incons.get(p):
            interfaces[p].stp_blocked = "Inconsistent"
        elif p in stp_states:
            interfaces[p].stp_blocked = stp_states[p]   # FWD/BLK/etc, confirmed by show spanning-tree
        # else: leave blank — STP state unknown, NOT asserted "Forwarding" from a link-up signal
        det = stp_detail.get(p)
        if det:
            interfaces[p].stp_fwd_vlans = _compress_vlans(det.get("Forwarding", []))
            interfaces[p].stp_blk_vlans = _compress_vlans(det.get("Blocked", []))
            other = []
            for label, key in (("LIS", "Listening"), ("LRN", "Learning"), ("DIS", "Disabled")):
                rng = _compress_vlans(det.get(key, []))
                if rng:
                    other.append(f"{label}:{rng}")
            interfaces[p].stp_other_vlans = " ".join(other)

    # 9) PoE
    poe_out = _load_cmd_output(cmd_to_file, "show power inline")
    for p, s in (parse_show_power_inline(poe_out) if poe_out else {}).items():
        interfaces.setdefault(p, InterfaceData(port=p))
        interfaces[p].poe_status = s

    # 10) CDP + LLDP
    route_db = parse_ip_routes(_load_cmd_output(cmd_to_file, 'show ip route'))
    vlan_names = {vid: (info.get("name") or "")                                     # NEW-V14.8
                  for vid, info in parse_vlan_brief(_load_cmd_output(cmd_to_file, "show vlan brief")).items()}
    hsrp_db = parse_hsrp_summary(_load_cmd_output(cmd_to_file, 'show standby brief', 'show standby all', 'show hsrp brief', 'show hsrp all'))
    vrrp_db = parse_vrrp_summary(_load_cmd_output(cmd_to_file, 'show vrrp brief'))   # NEW-V14.6
    glbp_db = parse_glbp_summary(_load_cmd_output(cmd_to_file, 'show glbp brief'))   # NEW-V14.6
    mcast_db = parse_multicast_info(_load_cmd_output(cmd_to_file, 'show ip mroute'), _load_cmd_output(cmd_to_file, 'show ip pim interface'))
    cdp_out  = _load_cmd_output(cmd_to_file, "show cdp neighbors detail")
    lldp_out = _load_cmd_output(cmd_to_file, "show lldp neighbors detail")
    neigh: Dict[str, Dict[str, str]] = {}
    if cdp_out:  neigh.update(parse_neighbors_cdp(cdp_out))
    if lldp_out:
        for k, v in parse_neighbors_lldp(lldp_out).items():
            neigh.setdefault(k, v)

    dev_to_ports: Dict[str, List[str]] = {}
    for local, v in neigh.items():
        did = (v.get("device_id") or "").strip()
        if did: dev_to_ports.setdefault(did, []).append(local)
    dual_ports = {p for ports in dev_to_ports.values() if len(set(ports)) > 1 for p in ports}

    for local, v in neigh.items():
        local = normalize_ifname(local)
        interfaces.setdefault(local, InterfaceData(port=local))
        device_id  = v.get("device_id","")
        platform_s = v.get("platform","")
        mgmt_ip    = v.get("mgmt_ip","")
        interfaces[local].endpoint_type = infer_endpoint_type(
            platform_s, device_id, interfaces[local].description)
        # NEW-V11: CDP/LLDP neighbor name
        if device_id and not interfaces[local].cdp_neighbor:
            interfaces[local].cdp_neighbor = device_id
        # NEW-V14.10: remote port + platform for the topology map
        if v.get("remote_port") and not interfaces[local].neighbor_port:
            interfaces[local].neighbor_port = v.get("remote_port","")
        if platform_s and not interfaces[local].neighbor_platform:
            interfaces[local].neighbor_platform = platform_s
        if mgmt_ip:
            if not interfaces[local].end_host_ip:
                interfaces[local].end_host_ip = mgmt_ip
            interfaces[local].neighbor_switch_ip = mgmt_ip
        if interfaces[local].endpoint_type == 'Switch' or (device_id and re.search(r'(sw|switch|n9k|n7k|c9k|catalyst|nexus)', device_id, re.IGNORECASE)):
            interfaces[local].neighbor_switch_vtp_domain = switch_identity.get('vtp_domain', '')
        mloc = re.search(r"(rack\s*\d+|r\d+)\s*[-_ ]*\s*(u\d+)?", device_id, re.IGNORECASE)
        if mloc: interfaces[local].endpoint_location = mloc.group(0).strip()
        if local in dual_ports: interfaces[local].dual_connection = "Yes"

    # 11) Description-based endpoint type fallback
    for p, d in interfaces.items():
        if not d.endpoint_type and d.description:
            ep = infer_endpoint_type("", "", d.description)
            if ep: interfaces[p].endpoint_type = ep

    # 12) Final enrichment
    for p, d in interfaces.items():
        if not d.link_type:
            d.link_type = detect_link_type(d.port_type, d.speed)
        if (d.switchport_mode or "").lower() == "trunk" and not d.vlan and d.trunk_allowed_vlans:
            d.vlan = d.trunk_allowed_vlans
        if p.startswith("Po") and not d.port_channel_protocol:
            d.port_channel_protocol = pc_proto.get(p, "") or ""
        if not d.stp_rootguard and d.switchport_mode == "Access":
            d.stp_rootguard = "Disable"
        d.current_switch_serial = switch_identity.get('serial_number', '')
        d.current_switch_ip = switch_identity.get('mgmt_ip', '')
        d.current_switch_vtp_domain = switch_identity.get('vtp_domain', '')
        if d.endpoint_type == 'Switch' and not d.neighbor_switch_serial:
            d.neighbor_switch_serial = d.cdp_neighbor
        # Per-SVI subnet enrichment: among the routes whose outgoing interface is THIS SVI,
        # choose the SVI's CONNECTED subnet as primary -- preferring the prefix that actually
        # contains the SVI's own configured IP -- so a coexisting /32 host route or a
        # redistributed loopback can't be picked ahead of the real connected /24. (V14.13)
        if re.match(r'^Vlan\d+$', p, re.IGNORECASE):
            svi_routes = []
            for rk, rv in route_db.items():
                for e in rv.get('entries', []):
                    if normalize_ifname(e.get('out_intf', '')) == p:
                        svi_routes.append(e)

            def _contains_svi_ip(prefix: str) -> bool:
                ipv = (d.svi_ip or '').split()[0].split('/')[0]
                if not ipv or not prefix:
                    return False
                try:
                    import ipaddress
                    return ipaddress.ip_address(ipv) in ipaddress.ip_network(prefix, strict=False)
                except Exception:
                    return False

            def _rank(e):
                # lower sorts first = higher priority
                src = (e.get('source', '') or '').lower()
                pfx = e.get('prefix', '')
                contains = _contains_svi_ip(pfx)
                is_conn  = src.startswith('connected') or src in ('c', 'l', 'local')
                try:
                    masklen = int(pfx.split('/')[1]) if '/' in pfx else 32
                except Exception:
                    masklen = 32
                # prefer: contains-SVI-IP, then connected, then the less-specific (smaller masklen) prefix
                return (0 if contains else 1, 0 if is_conn else 1, masklen)

            svi_routes.sort(key=_rank)
            if svi_routes:
                primary = svi_routes[0]
                d.subnet_primary_route = primary.get('prefix', '')
                d.routing_source       = primary.get('source', '') or 'connected'
                d.route_next_hop       = primary.get('next_hop', '') or normalize_ifname(primary.get('out_intf', ''))
                extras = []
                for e in svi_routes[1:]:
                    nh = e.get('next_hop', '') or e.get('prefix', '')
                    if nh:
                        extras.append(nh)
                if extras:
                    d.subnet_secondary_routes = '; '.join(dict.fromkeys(extras))
        if p in hsrp_db:
            d.hsrp_behavior = hsrp_db[p]
        elif p in vrrp_db:                 # NEW-V14.6: VRRP gateway
            d.hsrp_behavior = vrrp_db[p]
        elif p in glbp_db:                 # NEW-V14.6: GLBP gateway
            d.hsrp_behavior = glbp_db[p]
        if p in mcast_db:
            d.multicast_info = mcast_db[p]
        # NEW-V14.8: authoritative VLAN name from 'show vlan brief' where still missing.
        if vlan_names and not d.vlan_name:
            vid = d.vlan if d.vlan.isdigit() else ""
            if not vid:
                mm = re.match(r"^Vlan(\d+)$", p, re.IGNORECASE)   # SVI -> its VLAN id
                vid = mm.group(1) if mm else ""
            if vid and vlan_names.get(vid):
                d.vlan_name = vlan_names[vid]

    return interfaces

# =============================================================================
# GLOBAL ARP COLLECTION (FIX-R1, FIX-R3, FIX-R5, NEW-V11)
# =============================================================================
def collect_global_arp(all_cmd_to_files: Dict[str, Dict[str, str]],
                       all_neigh: Optional[Dict[str, Dict[str, Dict[str, str]]]] = None,
                       ) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Build network-wide {mac->ip} and {mac->source_switch_hostname}.
    NEW-V11: returns tuple so callers can populate arp_source_switch column.
    """
    global_arp:        Dict[str, str] = {}
    global_arp_source: Dict[str, str] = {}   # NEW-V11
    for hostname, cmd_to_file in all_cmd_to_files.items():
        _ARP_CMDS   = ["show ip arp vrf all", "show ip arp", "show ip arp detail"]
        device_new   = 0
        device_total = 0
        for arp_cmd in _ARP_CMDS:
            arp_out = _load_cmd_output(cmd_to_file, arp_cmd)
            if not arp_out: continue
            entries = parse_show_ip_arp(arp_out)
            if not entries: continue
            cmd_new = 0
            for mac, ip in entries.items():
                if mac not in global_arp:
                    global_arp[mac]        = ip
                    global_arp_source[mac] = hostname   # NEW-V11
                    cmd_new += 1
            device_total += len(entries)
            device_new   += cmd_new
            logger.debug(f"  ARP [{hostname}] {arp_cmd}: {len(entries)} entries, {cmd_new} new")
        if device_total > 0:
            logger.info(f"  ARP [{hostname}]: {device_total} total entries, {device_new} new to global table")
        else:
            logger.debug(f"  ARP [{hostname}]: no ARP output (pure L2 or no routing)")

    logger.info(f"  Global ARP table: {len(global_arp)} unique MAC->IP mappings")
    return global_arp, global_arp_source   # NEW-V11

def apply_global_arp(all_interfaces: Dict[str, Dict[str, InterfaceData]],
                     global_arp: Dict[str, str],
                     global_arp_source: Optional[Dict[str, str]] = None) -> None:
    """Fill end_host_ip (and arp_source_switch) from global ARP. FIX-R4 + NEW-V11."""
    filled = 0
    for hostname, interfaces in all_interfaces.items():
        for p, d in interfaces.items():
            if d.end_host_ip or not d.end_host_mac: continue
            for mac in [m.strip() for m in d.end_host_mac.split(",") if m.strip()]:
                ip = global_arp.get(mac, "")
                if ip:
                    d.end_host_ip = ip
                    filled += 1
                    if global_arp_source and not d.arp_source_switch:
                        d.arp_source_switch = global_arp_source.get(mac, "")   # NEW-V11
                    break
    logger.info(f"  ARP phase filled {filled} IP addresses")

def detect_cross_device_dual_connections(all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> None:
    mac_locations: Dict[str, List[Tuple[str,str]]] = {}
    for hostname, interfaces in all_interfaces.items():
        for p, d in interfaces.items():
            for mac in [m.strip() for m in d.end_host_mac.split(",") if m.strip()]:
                mac_locations.setdefault(mac, []).append((hostname, p))
    for mac, locs in mac_locations.items():
        unique = list({(h,p) for h,p in locs})
        if len(unique) > 1:
            for hostname, p in unique:
                if p in all_interfaces.get(hostname, {}):
                    all_interfaces[hostname][p].dual_connection = "Yes"

# =============================================================================
# EXCEL WRITER
# =============================================================================
def norm_header(h: str) -> str:
    h = (h or "").strip().lower()
    return re.sub(r"\s+", " ", h)

HEADER_TO_FIELD = {
    "hostname": "hostname", "ports": "port", "status": "status",
    "swqitchport mode": "switchport_mode",
    "swqitchport mode (access/trunk)": "switchport_mode",
    "switchport mode": "switchport_mode",
    "switchport mode (access/trunk)": "switchport_mode",
    "vlan": "vlan", "vlan name": "vlan_name",
    "vrf name": "vrf", "vrf name ": "vrf",
    "duplex": "duplex", "duplex (full/half/auto)": "duplex",
    "speed": "speed", "port type": "port_type",
    "link type (copper/fiber)": "link_type", "link type (copper/fibre)": "link_type",
    "link type": "link_type", "description": "description",
    "end host mac address": "end_host_mac", "end host ip address": "end_host_ip",
    "port-channel": "port_channel",
    "port-channel protocol (active/on/none)": "port_channel_protocol",
    "port-channel protocol": "port_channel_protocol",
    "spanning tree block ports status": "stp_blocked",
    "spanning tree bpdu (enable/disable)": "stp_bpduguard",
    "spanning tree bpdu": "stp_bpduguard",
    "spanning tree rootguard (enable/disable)": "stp_rootguard",
    "spanning tree rootguard": "stp_rootguard",
    "poe status": "poe_status",
    "system owner ([HISTORY-REDACTED] to confirm)": "system_owner", "system owner": "system_owner",
    "end point type": "endpoint_type",
    "end point location rack-unit": "endpoint_location", "end point location": "endpoint_location",
    "dual connection": "dual_connection",
    "trunk native vlan": "trunk_native_vlan",
    "trunk allowed vlans": "trunk_allowed_vlans",
    "trunk status": "trunk_status",
    # NEW-V11
    "arp source switch": "arp_source_switch",
    "arp source":        "arp_source_switch",
    "cdp neighbor":      "cdp_neighbor",
    "cdp/lldp neighbor": "cdp_neighbor",
    "connected device":  "cdp_neighbor",
    "neighbor device":   "cdp_neighbor",
    # NEW-V14.2 (keys must match the header text written by ensure_headers in main())
    "current switch serial":      "current_switch_serial",
    "current switch mgmt ip":     "current_switch_ip",
    "current switch vtp domain":  "current_switch_vtp_domain",
    "neighbor switch serial":     "neighbor_switch_serial",
    "neighbor switch mgmt ip":    "neighbor_switch_ip",
    "neighbor switch vtp domain": "neighbor_switch_vtp_domain",
    "subnet primary route":       "subnet_primary_route",
    "subnet secondary routes":    "subnet_secondary_routes",
    "route next hop":             "route_next_hop",
    "routing source":             "routing_source",
    "hsrp behavior":              "hsrp_behavior",
    "fhrp behavior":              "hsrp_behavior",  # NEW-V14.6 canonical (HSRP/VRRP/GLBP)
    "multicast info":             "multicast_info",
    # Aliases
    "port": "port", "interface": "port", "state": "status",
}

def find_header_row(ws, must_have=("hostname","port","status")) -> Tuple[int, Dict[str,int]]:
    for r in range(1, 301):
        col_map: Dict[str,int] = {}
        for c in range(1, ws.max_column+1):
            val = ws.cell(row=r, column=c).value
            if not isinstance(val, str): continue
            nh = norm_header(val)
            if nh in HEADER_TO_FIELD:
                field = HEADER_TO_FIELD[nh]
                if field not in col_map: col_map[field] = c
        if all(k in col_map for k in must_have):
            return r, col_map
    raise RuntimeError("Could not find header row. Try --debug-headers")

def ensure_headers(ws, header_row, col_map, new_headers):
    for header_text, field in new_headers.items():
        if field in col_map: continue
        new_col = ws.max_column + 1
        ws.cell(row=header_row, column=new_col, value=header_text)
        col_map[field] = new_col
    return col_map

def sortkey(portname: str):
    pn = normalize_ifname(portname or "")
    m  = re.match(r"^Po(\d+)$", pn, re.IGNORECASE)
    if m: return (0, int(m.group(1)), 0, 0)
    m = re.match(r"^(Eth|Fa|Gi|Te|Tw|Fo|Hu)(\d+)(?:/(\d+))?(?:/(\d+))?$", pn, re.IGNORECASE)
    if m:
        pref = m.group(1).capitalize()
        rank = {"Eth":1,"Fa":2,"Gi":3,"Te":4,"Tw":5,"Fo":6,"Hu":7}.get(pref, 9)
        return (rank, int(m.group(2)), int(m.group(3) or 0), int(m.group(4) or 0))
    return (99, pn)

def append_interface_rows(ws, header_row: int, col_map: Dict[str,int],
                          hostname: str, interfaces: Dict[str, InterfaceData]):
    required_cols = [col_map["hostname"], col_map["port"], col_map["status"]]

    def row_is_writable(r):
        return not any(isinstance(ws.cell(row=r, column=c), MergedCell) for c in required_cols)

    existing_rows: Dict[Tuple[str,str],int] = {}
    for r in range(header_row+1, ws.max_row+1):
        if not row_is_writable(r): continue
        hv = ws.cell(row=r, column=col_map["hostname"]).value
        pv = ws.cell(row=r, column=col_map["port"]).value
        if hv and pv:
            existing_rows[(str(hv).strip(), normalize_ifname(str(pv).strip()))] = r

    def next_empty_row(start):
        r = start
        while True:
            if not row_is_writable(r): r += 1; continue
            if ws.cell(row=r, column=col_map["hostname"]).value not in (None,""): r += 1; continue
            return r

    append_row = next_empty_row(header_row+1)

    for port in sorted(interfaces.keys(), key=sortkey):
        d      = interfaces[port]
        norm_p = normalize_ifname(port)
        if norm_p.lower().startswith(("vlan","lo","loop","null","tunnel","mgmt0")): continue
        if port.strip().startswith("%"): continue
        if not PHYSICAL_IFACE_RE.match(norm_p):
            if not re.match(r"^(Fa|mgmt)\d", norm_p, re.IGNORECASE): continue

        key = (hostname, normalize_ifname(port))
        if key in existing_rows:
            row = existing_rows[key]
        else:
            row = next_empty_row(append_row)
            append_row = row + 1

        ws.cell(row=row, column=col_map["hostname"], value=hostname)
        ws.cell(row=row, column=col_map["port"],     value=d.port)
        ws.cell(row=row, column=col_map["status"],   value=d.status)

        def w(field, val):
            if field not in col_map: return
            cell = ws.cell(row=row, column=col_map[field])
            if isinstance(cell, MergedCell): return
            cell.value = val if val else (cell.value or None)

        def w_po(field, val):
            if field not in col_map: return
            cell = ws.cell(row=row, column=col_map[field])
            if isinstance(cell, MergedCell): return
            existing = str(cell.value or "").strip().lower()
            if existing in _TRUNK_STATUS_WORDS: cell.value = val if val else None
            else: cell.value = val if val else (cell.value or None)

        w("switchport_mode",      d.switchport_mode)
        w("vlan",                 d.vlan)
        w("vlan_name",            d.vlan_name)
        w("vrf",                  d.vrf)
        w("duplex",               d.duplex)
        w("speed",                d.speed)
        w("port_type",            d.port_type)
        w("link_type",            d.link_type)
        w("description",          d.description)
        w("end_host_mac",         d.end_host_mac)
        w("end_host_ip",          d.end_host_ip)
        w_po("port_channel",      d.port_channel)
        w("port_channel_protocol",d.port_channel_protocol)
        w("stp_blocked",          d.stp_blocked)
        w("stp_bpduguard",        d.stp_bpduguard)
        w("stp_rootguard",        d.stp_rootguard)
        w("poe_status",           d.poe_status)
        w("system_owner",         d.system_owner)
        w("endpoint_type",        d.endpoint_type)
        w("endpoint_location",    d.endpoint_location)
        w("dual_connection",      d.dual_connection)
        w("trunk_native_vlan",    d.trunk_native_vlan)
        w("trunk_allowed_vlans",  d.trunk_allowed_vlans)
        w("trunk_status",         d.trunk_status)
        w("arp_source_switch",    d.arp_source_switch)   # NEW-V11
        w("cdp_neighbor",         d.cdp_neighbor)        # NEW-V11
        # NEW-V14.2
        w("current_switch_serial",      d.current_switch_serial)
        w("current_switch_ip",          d.current_switch_ip)
        w("current_switch_vtp_domain",  d.current_switch_vtp_domain)
        w("neighbor_switch_serial",     d.neighbor_switch_serial)
        w("neighbor_switch_ip",         d.neighbor_switch_ip)
        w("neighbor_switch_vtp_domain", d.neighbor_switch_vtp_domain)
        w("subnet_primary_route",       d.subnet_primary_route)
        w("subnet_secondary_routes",    d.subnet_secondary_routes)
        w("route_next_hop",             d.route_next_hop)
        w("routing_source",             d.routing_source)
        w("hsrp_behavior",              d.hsrp_behavior)
        w("multicast_info",             d.multicast_info)

# =============================================================================
# DEVICES LOADER
# =============================================================================
def load_devices(devices_file: str) -> List[dict]:
    if not os.path.isfile(devices_file):
        raise FileNotFoundError(f"Devices file not found: {devices_file}")
    with open(devices_file, "r", encoding="utf-8-sig") as f:
        raw = f.read().strip()
    if not raw: raise ValueError(f"Devices file is empty: {devices_file}")
    data = None
    try:
        parsed = json.loads(raw)
        data = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        pass
    if data is None:
        try:
            items = [json.loads(l) for l in raw.splitlines() if l.strip()]
            if items: data = items
        except json.JSONDecodeError:
            pass
    if data is None:
        decoder = json.JSONDecoder()
        idx, items = 0, []
        while idx < len(raw):
            mv = re.search(r"[^\s,]", raw[idx:])
            if not mv: break
            idx += mv.start()
            try:
                obj, end_idx = decoder.raw_decode(raw, idx)
                items.append(obj); idx = end_idx
            except json.JSONDecodeError:
                break
        if items: data = items
    if data is None:
        raise ValueError(f"Could not parse {devices_file} as valid JSON.")
    plat_map = {
        "cisco_nxos":"nxos","nxos":"nxos","nexus":"nxos","nx-os":"nxos",
        "cisco_ios":"ios","ios":"ios","ios-xe":"ios","iosxe":"ios",
        "cisco_xe":"ios","xe":"ios","auto":"auto","autodetect":"auto","":"auto",
    }
    for d in data:
        for alias, key in [("host","ip"),("address","ip"),("name","hostname"),
                           ("user","username"),("pass","password"),("secret","password")]:
            if alias in d and key not in d: d[key] = d[alias]
        for k in ("ip","hostname","username"):     # CHANGED-V3.23.1: 'password' no longer
            if k not in d:                          # hard-required - it may come from env/getpass
                raise ValueError(f"Missing '{k}' in devices.json entry: {d}")
        for k in ("ip","hostname","username"):
            d[k] = (d.get(k) or "").strip()
        # NEW-V3.23.1: resolve the password WITHOUT forcing plaintext into the file.
        #   1) explicit "password" in the entry  (unchanged - fully back-compatible)
        #   2) per-entry  "password_env": "VAR"   -> os.environ["VAR"]
        #   3) global      $CISCO_PASS
        #   4) (after the loop) a secure getpass prompt, only on an interactive TTY
        pw = d.get("password") or ""
        if not pw and d.get("password_env"):
            pw = os.environ.get(d["password_env"], "")
        if not pw:
            pw = os.environ.get("CISCO_PASS", "")
        d["password"] = pw
        plat_raw = (d.get("platform") or d.get("device_type") or d.get("os") or d.get("nos") or "auto")
        d["platform"] = plat_map.get(plat_raw.strip().lower(), "auto")

    # NEW-V3.23.1: prompt securely for any device still lacking a password - but ONLY when
    # attached to a terminal. An unattended/batch run must not block on input, so it keeps the
    # previous blank-password behaviour (those devices then fail auth visibly: connect_device
    # logs the auth failure and, per V3.23.1, does not retry it). Prompt once per username.
    need_pw = [d for d in data if not d["password"]]
    if need_pw:
        if sys.stdin.isatty():
            import getpass
            by_user: Dict[str, str] = {}
            for d in need_pw:
                u = d["username"]
                if u not in by_user:
                    by_user[u] = getpass.getpass(f"  SSH password for '{u}': ")
                d["password"] = by_user[u]
        else:
            hosts = ", ".join(sorted({d["hostname"] for d in need_pw}))
            logger.warning(f"  [WARN] No password for {len(need_pw)} device(s) "
                           f"(no entry, no password_env, no $CISCO_PASS): {hosts}. "
                           f"Set $CISCO_PASS or run interactively to be prompted.")
    return data


def write_json_file(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def file_sha256(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_run_manifest(rootdir: str, script_version: str, devices_meta: List[dict], output_xlsx: str, template_file: str, archive_enabled: bool) -> dict:
    return {
        "script_version": script_version,
        "generated_at": datetime.now().isoformat(),
        "collection_root": os.path.abspath(rootdir),
        "archive_enabled": bool(archive_enabled),
        "template_file": os.path.abspath(template_file) if template_file else "",
        "output_excel": os.path.abspath(output_xlsx) if output_xlsx else "",
        "device_count": len(devices_meta),
        "devices": devices_meta,
    }

# =============================================================================
# V3.15.0 ADDITIONS - new analysis outputs (Tier 1) + new collection (Tier 2).
# Tier 1 sheets aggregate already-parsed data (InterfaceData / DevicePhysical).
# Tier 2 sheets parse raw command output directly (writer takes the per-device
# cmd_to_file map) so the existing interface-building pipeline is untouched.
# =============================================================================

# -----------------------------------------------------------------------------
# Shared: de-duplicated CDP/LLDP inter-switch link map. compute_topology_links()
# is also used by the existing 'Topology Links' sheet (write_topology_sheet),
# the Findings sheet, and the topology diagram - one source of truth.
# -----------------------------------------------------------------------------
def compute_topology_links(all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> List[Dict[str, object]]:
    """De-duplicated inter-switch links from CDP/LLDP, one record per physical link.
    Each record: a_host, a_port, b_host, b_port, platform, speed, confirmation."""
    scanned = {_canon_host(h) for h in all_interfaces}
    links: Dict[Tuple[str, str], Dict[str, object]] = {}
    for host, ifaces in all_interfaces.items():
        for port, d in ifaces.items():
            if not d.cdp_neighbor or not _is_infra_neighbor(d, scanned):
                continue
            nbr = d.cdp_neighbor.strip()
            key = tuple(sorted([f"{_canon_host(host)}|{port.lower()}",
                                f"{_canon_host(nbr)}|{(d.neighbor_port or '?').lower()}"]))
            rec = links.get(key)
            if rec is None:
                links[key] = {"a_host": host, "a_port": port, "b_host": nbr,
                              "b_port": d.neighbor_port or "", "platform": d.neighbor_platform or "",
                              "speed": d.speed or "", "seen_from": {_canon_host(host)}}
            else:
                rec["seen_from"].add(_canon_host(host))
                if not rec["platform"] and d.neighbor_platform: rec["platform"] = d.neighbor_platform
                if not rec["b_port"] and d.neighbor_port: rec["b_port"] = d.neighbor_port
    ordered = sorted(links.values(),
                     key=lambda r: (str(r["a_host"]).lower(), str(r["a_port"]).lower()))
    for rec in ordered:
        rec["confirmation"] = ("Both ends" if len(rec["seen_from"]) >= 2
                               else f"One end ({rec['a_host']})")
    return ordered


# -----------------------------------------------------------------------------
# Tier 1 #1: Findings / Risk Register  (pure cross-reference of InterfaceData)
# -----------------------------------------------------------------------------
FINDINGS_SHEET_NAME = "Findings"
_SEV_RANK = {"High": 0, "Medium": 1, "Low": 2, "Info": 3}

def _canon_host_map(all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> Dict[str, str]:
    """canonical-name -> real hostname key, to resolve CDP/LLDP neighbor names."""
    return {_canon_host(h): h for h in all_interfaces}

def compute_findings(all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> List[Tuple[str, str, str, str]]:
    """Return (severity, category, scope, detail) findings derived entirely from
    already-parsed InterfaceData + the topology link map. High-signal only."""
    findings: List[Tuple[str, str, str, str]] = []

    access_vlans: Dict[int, set] = {}
    svi_hosts: Dict[int, set] = {}
    svi_fhrp: Dict[int, List[str]] = {}
    for host, ifaces in all_interfaces.items():
        for port, d in ifaces.items():
            if (d.switchport_mode or "") == "Access" and d.vlan.isdigit():
                access_vlans.setdefault(int(d.vlan), set()).add(host)
            m = re.match(r"^Vlan(\d+)$", port, re.IGNORECASE)
            if m:
                vid = int(m.group(1))
                svi_hosts.setdefault(vid, set()).add(host)
                svi_fhrp.setdefault(vid, []).append(d.hsrp_behavior or "")

    # (1) Access VLAN with no SVI anywhere in scan = no L3 gateway found.
    for vid, hosts in sorted(access_vlans.items()):
        if vid in MOVEGROUP_EXCLUDED_VLANS:
            continue
        if vid not in svi_hosts:
            findings.append(("Medium", "No gateway", f"VLAN {vid}",
                f"Access ports on {len(hosts)} switch(es) but no SVI in scan "
                f"(L2-only, or its gateway is off-scan)."))

    # (2) VLAN with SVIs on >=2 switches but no FHRP = gateway redundancy gap.
    for vid, hosts in sorted(svi_hosts.items()):
        if len(hosts) >= 2 and not any((f or "").strip() for f in svi_fhrp.get(vid, [])):
            findings.append(("High", "Gateway redundancy", f"VLAN {vid}",
                f"SVIs on {len(hosts)} switches but no FHRP (HSRP/VRRP/GLBP) detected "
                f"- duplicate-IP / split-gateway risk."))

    # (3) err-disabled ports.
    for host, ifaces in all_interfaces.items():
        for port, d in ifaces.items():
            s = (d.status or "").lower()
            if "err" in s and "disab" in s:
                findings.append(("High", "Err-disabled", f"{host} {port}",
                    f"Port status '{d.status}'."))

    # (4) STP inconsistent ports.
    for host, ifaces in all_interfaces.items():
        for port, d in ifaces.items():
            if (d.stp_blocked or "") == "Inconsistent":
                findings.append(("High", "STP inconsistent", f"{host} {port}",
                    "Port is STP-inconsistent (root-guard / loop-guard / type mismatch)."))

    # (5)/(6) Link-level mismatches need both ends - use the topology link map.
    cmap = _canon_host_map(all_interfaces)
    for link in compute_topology_links(all_interfaces):
        if str(link.get("confirmation", "")).startswith("One end"):
            findings.append(("Info", "Topology", f"{link['a_host']} {link['a_port']}",
                f"Link to {link['b_host']} {link.get('b_port', '')} seen from one end only "
                f"(check reverse CDP/LLDP or cabling docs)."))
            continue
        ah = cmap.get(_canon_host(str(link["a_host"]))); ap = str(link["a_port"])
        bh = cmap.get(_canon_host(str(link["b_host"]))); bp = str(link.get("b_port", ""))
        da = all_interfaces.get(ah, {}).get(normalize_ifname(ap)) if ah else None
        db = all_interfaces.get(bh, {}).get(normalize_ifname(bp)) if bh else None
        if not da or not db:
            continue
        na, nb = (da.trunk_native_vlan or "").strip(), (db.trunk_native_vlan or "").strip()
        if na and nb and na != nb:
            findings.append(("High", "Native VLAN mismatch",
                f"{link['a_host']} {ap} <-> {link['b_host']} {bp}",
                f"Native VLAN {na} vs {nb}."))
        dxa, dxb = (da.duplex or "").lower(), (db.duplex or "").lower()
        if dxa in ("half", "full") and dxb in ("half", "full") and dxa != dxb:
            findings.append(("High", "Duplex mismatch",
                f"{link['a_host']} {ap} <-> {link['b_host']} {bp}",
                f"Duplex {da.duplex} vs {db.duplex}."))

    findings.sort(key=lambda t: (_SEV_RANK.get(t[0], 9), t[1], t[2]))
    return findings

def write_findings_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> None:
    """Write (or replace) 'Findings': a risk register cross-referenced from the
    interface DB. Empty when nothing notable is found."""
    cols = ["Severity", "Category", "Scope", "Finding"]
    if FINDINGS_SHEET_NAME in wb.sheetnames:
        del wb[FINDINGS_SHEET_NAME]
    ws = wb.create_sheet(FINDINGS_SHEET_NAME)
    _census_header(ws, cols)
    findings = compute_findings(all_interfaces)
    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="top", wrap_text=True)
    sev_fill = {"High": PatternFill("solid", fgColor="F4CCCC"),
                "Medium": PatternFill("solid", fgColor="FCE5CD"),
                "Low": PatternFill("solid", fgColor="FFF2CC"),
                "Info": PatternFill("solid", fgColor="EFEFEF")}
    r = 2
    for sev, cat, scope, detail in findings:
        for col, v in enumerate([sev, cat, scope, detail], 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT; c.alignment = DAT_L
            if col == 1 and sev in sev_fill: c.fill = sev_fill[sev]
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    ws.column_dimensions["D"].width = 70
    logger.info(f"  [OK] '{FINDINGS_SHEET_NAME}' sheet: {len(findings)} finding(s)")


# -----------------------------------------------------------------------------
# Tier 1 #4: Capacity / Consolidation  (from the already-built DevicePhysical)
# -----------------------------------------------------------------------------
CAPACITY_SHEET_NAME = "Capacity"

def _to_float(s) -> Optional[float]:
    m = re.search(r"-?\d+(?:\.\d+)?", str(s or ""))
    return float(m.group(0)) if m else None

def write_capacity_sheet(wb, all_device_physical: List[DevicePhysical]) -> None:
    """Write (or replace) 'Capacity': per-switch port and PoE headroom for
    consolidation decisions. Flags switches that are port- or PoE-bound."""
    cols = ["Hostname", "Model", "Total Ports", "Active Ports", "Free Ports",
            "Port Util %", "PoE Capacity (W)", "PoE Drawn (W)", "PoE Remaining (W)",
            "PoE Util %", "Flag"]
    if CAPACITY_SHEET_NAME in wb.sheetnames:
        del wb[CAPACITY_SHEET_NAME]
    ws = wb.create_sheet(CAPACITY_SHEET_NAME)
    _census_header(ws, cols)
    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="center")
    DAT_C = Alignment(horizontal="center", vertical="center")
    warn_fill = PatternFill("solid", fgColor="FCE5CD")
    r = 2
    for dp in sorted(all_device_physical, key=lambda d: d.hostname.lower()):
        total, active = dp.total_ports or 0, dp.active_ports or 0
        free = max(total - active, 0) if total else ""
        putil = round(100.0 * active / total, 1) if total else ""
        cap, drawn = _to_float(dp.power_capacity_w), _to_float(dp.power_drawn_w)
        if dp.power_remaining_w:
            rem = dp.power_remaining_w
        elif cap is not None and drawn is not None:
            rem = round(cap - drawn, 1)
        else:
            rem = ""
        poe_util = round(100.0 * drawn / cap, 1) if (cap and drawn is not None and cap > 0) else ""
        flags = []
        if putil != "" and putil >= 90: flags.append("Port-bound (>=90%)")
        if poe_util != "" and poe_util >= 80: flags.append("PoE-bound (>=80%)")
        vals = [dp.hostname, dp.model, total or "", active or "", free, putil,
                dp.power_capacity_w, dp.power_drawn_w, rem, poe_util, "; ".join(flags)]
        for col, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT
            c.alignment = DAT_C if 3 <= col <= 10 else DAT_L
            if flags and col in (6, 10): c.fill = warn_fill
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    logger.info(f"  [OK] '{CAPACITY_SHEET_NAME}' sheet: {len(all_device_physical)} device(s)")


# -----------------------------------------------------------------------------
# Tier 1 #3: Topology diagram (Mermaid + Graphviz) from the CDP/LLDP link map.
# -----------------------------------------------------------------------------
def _mermaid_id(name: str, idmap: Dict[str, str]) -> str:
    if name not in idmap:
        idmap[name] = f"n{len(idmap)}"
    return idmap[name]

def write_topology_diagram(all_interfaces: Dict[str, Dict[str, InterfaceData]],
                           out_dir: str, basename: str = "topology") -> List[str]:
    """Emit the inter-switch link map as Mermaid (.mmd) and Graphviz (.dot) files.
    One-end-only links are drawn dashed. Returns the two file paths."""
    links = compute_topology_links(all_interfaces)
    os.makedirs(out_dir, exist_ok=True)
    nodes = set()
    for L in links:
        nodes.add(str(L["a_host"])); nodes.add(str(L["b_host"]))

    idmap: Dict[str, str] = {}
    mm = ["graph LR"]
    for n in sorted(nodes):
        mm.append(f'    {_mermaid_id(n, idmap)}["{n}"]')
    for L in links:
        a, b = _mermaid_id(str(L["a_host"]), idmap), _mermaid_id(str(L["b_host"]), idmap)
        lbl = f'{L["a_port"]} - {L.get("b_port") or "?"}'
        edge = "-.-" if str(L["confirmation"]).startswith("One end") else "---"
        mm.append(f'    {a} {edge}|"{lbl}"| {b}')
    mm_path = os.path.join(out_dir, basename + ".mmd")
    with open(mm_path, "w", encoding="utf-8") as f:
        f.write("\n".join(mm) + "\n")

    dot = ["graph topology {", "    rankdir=LR;", "    node [shape=box, fontsize=10];"]
    for L in links:
        style = ' style="dashed"' if str(L["confirmation"]).startswith("One end") else ""
        lbl = f'{L["a_port"]}\\n{L.get("b_port") or "?"}'
        dot.append(f'    "{L["a_host"]}" -- "{L["b_host"]}" [label="{lbl}"{style}];')
    dot.append("}")
    dot_path = os.path.join(out_dir, basename + ".dot")
    with open(dot_path, "w", encoding="utf-8") as f:
        f.write("\n".join(dot) + "\n")

    logger.info(f"  [OK] Topology diagram: {mm_path} , {dot_path} "
                f"({len(links)} link(s), {len(nodes)} node(s))")
    return [mm_path, dot_path]


# -----------------------------------------------------------------------------
# Tier 1 #2: Pre/post-cutover snapshot + diff. A snapshot JSON is written next
# to every output workbook; '--compare OLD NEW' produces a diff workbook.
# -----------------------------------------------------------------------------
def snapshot_state(all_interfaces: Dict[str, Dict[str, InterfaceData]],
                   all_device_physical: List[DevicePhysical]) -> dict:
    import dataclasses
    return {
        "schema": "collect_parse_snapshot/1",
        "script_version": "V3.23.0",
        "generated_at": datetime.now().isoformat(),
        "devices": {dp.hostname: dataclasses.asdict(dp) for dp in all_device_physical},
        "interfaces": {host: {port: dataclasses.asdict(d) for port, d in ifaces.items()}
                       for host, ifaces in all_interfaces.items()},
    }


# -----------------------------------------------------------------------------
# NEW-V3.17: HTML consolidation. Bake the live snapshot into a copy of the
# read-only Blast-Radius Explorer template so one run yields both the workbook
# and a ready-to-open, air-gapped topology explorer (no second tool, no manual
# snapshot load). Pure stdlib (os + json); no new imports.
# -----------------------------------------------------------------------------
def write_html_explorer(output_path: str, snap_dict: dict, label: str) -> None:
    """
    Emit a self-contained Blast-Radius Explorer with the live topology embedded.

    Reads 'blast_radius_explorer.html' from the same directory as THIS script,
    replaces its demo bootstrap with the embedded snapshot, and writes the patched
    single-file HTML to output_path.

    The template boots on a demo via the LAST statement in its <script>:
        load(demoSnapshot(),"DEMO TOPOLOGY",false);
    That exact text also appears earlier as the demo button's onclick handler, so a
    naive str.replace() (which replaces every occurrence) would corrupt the button -
    it would inject a `const` declaration into an arrow-function body and break all
    JS on the page. We therefore replace ONLY the final occurrence (the real
    bootstrap) via rpartition(), leaving the demo button intact as a one-click way
    back to the sample topology.

    Safety / robustness:
      * Missing template -> warn and skip (never crash a run whose workbook already saved).
      * Bootstrap line absent (template changed) -> warn and skip.
      * Snapshot is minified (separators=(',',':')) to keep the embedded payload small.
      * Any literal '</' inside the data is escaped to '<\\/' so the JSON can never
        break out of the <script> block (valid JSON escape; parses back to '</').
      * label is emitted via json.dumps() -> a properly quoted/escaped JS string literal.
    """
    template = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "blast_radius_explorer.html")
    if not os.path.isfile(template):
        logger.warning(f"  HTML Explorer skipped: template not found at {template}")
        return

    with open(template, encoding="utf-8") as f:
        html = f.read()

    bootstrap = 'load(demoSnapshot(),"DEMO TOPOLOGY",false);'
    if bootstrap not in html:
        logger.warning("  HTML Explorer skipped: demo bootstrap line not found in template "
                       "(template may have changed).")
        return

    embedded = json.dumps(snap_dict, separators=(",", ":"), ensure_ascii=False)
    embedded = embedded.replace("</", "<\\/")          # cannot break out of <script>
    replacement = (f"const EMBEDDED_SNAPSHOT={embedded};\n"
                   f"load(EMBEDDED_SNAPSHOT,{json.dumps(label)},true);")

    # Replace ONLY the last occurrence (the bootstrap), not the button's onclick.
    head, _sep, tail = html.rpartition(bootstrap)
    patched = head + replacement + tail

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(patched)
    logger.info(f"[Phase 22] HTML Explorer written: {output_path}")


_DIFF_FIELDS = ["status", "switchport_mode", "vlan", "trunk_native_vlan",
                "trunk_allowed_vlans", "stp_blocked", "port_channel",
                "svi_ip", "hsrp_behavior", "subnet_primary_route"]

def _macset(s: str) -> set:
    return set(t for t in re.split(r"[,\s;]+", s or "") if t)

def write_diff_workbook(old: dict, new: dict, out_path: str) -> None:
    """Write a diff workbook (Summary / Interface Changes / Endpoint Changes /
    SVI Changes) comparing two snapshot_state() dicts."""
    from openpyxl import Workbook
    HF = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
    FILL = PatternFill("solid", fgColor="1F497D")
    AL = Alignment(horizontal="left", vertical="top", wrap_text=True)
    DF = Font(name="Calibri", size=10)
    NONE = "\u2205"  # empty marker

    wb = Workbook(); wb.remove(wb.active)

    def sheet(title, cols):
        ws = wb.create_sheet(title)
        for c, h in enumerate(cols, 1):
            cell = ws.cell(row=1, column=c, value=h)
            cell.font = HF; cell.fill = FILL
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.freeze_panes = "A2"
        return ws

    def autofit(ws, ncols):
        for col in range(1, ncols + 1):
            mx = len(str(ws.cell(row=1, column=col).value or ""))
            for row in range(2, ws.max_row + 1):
                v = ws.cell(row=row, column=col).value
                if v is not None: mx = max(mx, len(str(v)))
            ws.column_dimensions[get_column_letter(col)].width = min(max(mx + 2, 12), 60)

    oi, ni = old.get("interfaces", {}), new.get("interfaces", {})
    od, nd = old.get("devices", {}), new.get("devices", {})

    # Summary
    ws = sheet("Summary", ["Metric", "Old", "New", "Delta"])
    added_sw = sorted(set(nd) - set(od)); removed_sw = sorted(set(od) - set(nd))
    o_if = sum(len(v) for v in oi.values()); n_if = sum(len(v) for v in ni.values())
    metrics = [
        ("Switches", len(od), len(nd), len(nd) - len(od)),
        ("Switches added", "", "", ", ".join(added_sw) or "0"),
        ("Switches removed", "", "", ", ".join(removed_sw) or "0"),
        ("Interfaces (total)", o_if, n_if, n_if - o_if),
    ]
    r = 2
    for m in metrics:
        for c, v in enumerate(m, 1):
            cell = ws.cell(row=r, column=c, value=v); cell.font = DF; cell.alignment = AL
        r += 1
    autofit(ws, 4)

    # Interface Changes
    ws = sheet("Interface Changes", ["Hostname", "Port", "Change", "Field: Old -> New"])
    r = 2
    for host in sorted(set(oi) | set(ni)):
        op, npp = oi.get(host, {}), ni.get(host, {})
        for port in sorted(set(op) | set(npp)):
            o, n = op.get(port), npp.get(port)
            if o is None and n is None:
                continue
            if o is None:
                change, deltas = "Added port", []
            elif n is None:
                change, deltas = "Removed port", []
            else:
                change = "Modified"
                deltas = [f"{f}: {o.get(f, '') or NONE} -> {n.get(f, '') or NONE}"
                          for f in _DIFF_FIELDS if (o.get(f, "") or "") != (n.get(f, "") or "")]
                if not deltas:
                    continue
            for c, v in enumerate([host, port, change, " | ".join(deltas)], 1):
                cell = ws.cell(row=r, column=c, value=v); cell.font = DF; cell.alignment = AL
            r += 1
    autofit(ws, 4); ws.column_dimensions["D"].width = 70

    # Endpoint (MAC) Changes
    ws = sheet("Endpoint Changes", ["Hostname", "Port", "Change", "MAC"])
    r = 2
    for host in sorted(set(oi) | set(ni)):
        op, npp = oi.get(host, {}), ni.get(host, {})
        for port in sorted(set(op) | set(npp)):
            om = _macset((op.get(port) or {}).get("end_host_mac", ""))
            nm = _macset((npp.get(port) or {}).get("end_host_mac", ""))
            for mac in sorted(nm - om):
                for c, v in enumerate([host, port, "MAC appeared", mac], 1):
                    cell = ws.cell(row=r, column=c, value=v); cell.font = DF; cell.alignment = AL
                r += 1
            for mac in sorted(om - nm):
                for c, v in enumerate([host, port, "MAC gone", mac], 1):
                    cell = ws.cell(row=r, column=c, value=v); cell.font = DF; cell.alignment = AL
                r += 1
    autofit(ws, 4)

    # SVI / Gateway Changes
    ws = sheet("SVI Changes", ["Hostname", "SVI", "Change", "Detail"])
    r = 2
    for host in sorted(set(oi) | set(ni)):
        op, npp = oi.get(host, {}), ni.get(host, {})
        svis = sorted({p for p in (set(op) | set(npp)) if re.match(r"^Vlan\d+$", p, re.I)})
        for p in svis:
            o, n = op.get(p), npp.get(p)
            if o is None and n is not None:
                ch = "SVI added"
                detail = f"IP {n.get('svi_ip', '') or NONE}, FHRP {n.get('hsrp_behavior', '') or NONE}"
            elif n is None and o is not None:
                ch = "SVI removed"
                detail = f"was IP {o.get('svi_ip', '') or NONE}"
            else:
                diffs = [f"{f}: {o.get(f, '') or NONE} -> {n.get(f, '') or NONE}"
                         for f in ("svi_ip", "hsrp_behavior", "subnet_primary_route")
                         if (o.get(f, "") or "") != (n.get(f, "") or "")]
                if not diffs:
                    continue
                ch, detail = "SVI changed", " | ".join(diffs)
            for c, v in enumerate([host, p, ch, detail], 1):
                cell = ws.cell(row=r, column=c, value=v); cell.font = DF; cell.alignment = AL
            r += 1
    autofit(ws, 4); ws.column_dimensions["D"].width = 60

    wb.save(out_path)


# -----------------------------------------------------------------------------
# Tier 2 #1: Interface health counters  ('show interfaces' / 'show interface')
# -----------------------------------------------------------------------------
INTERFACE_HEALTH_SHEET_NAME = "Interface Health"

def parse_show_interface_counters(output: str) -> Dict[str, Dict[str, object]]:
    """Per-interface error/health counters from IOS 'show interfaces' or NX-OS
    'show interface'. Tolerant across both; unknown values stay blank. Returns
    {port: {oper, input_errors, crc, output_drops, last_input, last_output}}."""
    res: Dict[str, Dict[str, object]] = {}
    cur = None
    buf: List[str] = []

    def _flush(name, lines):
        if not name or not lines:
            return
        text = "\n".join(lines)
        rec: Dict[str, object] = {"oper": "", "input_errors": "", "crc": "",
                                  "output_drops": "", "last_input": "", "last_output": ""}
        mhdr = re.match(r"^\S+\s+is\s+([A-Za-z ]+?)(?:,|$)", lines[0])
        if mhdr: rec["oper"] = mhdr.group(1).strip()
        m = re.search(r"(\d+)\s+input error", text)
        if m: rec["input_errors"] = int(m.group(1))
        m = re.search(r"(\d+)\s+CRC", text)
        if m: rec["crc"] = int(m.group(1))
        m = re.search(r"Total output drops:\s*(\d+)", text)
        if m:
            rec["output_drops"] = int(m.group(1))
        else:
            m = re.search(r"(\d+)\s+output discard", text)   # NX-OS
            if m: rec["output_drops"] = int(m.group(1))
        m = re.search(r"Last input\s+(\S+?),\s*output\s+(\S+?)[,\s]", text)
        if m:
            rec["last_input"] = m.group(1).rstrip(",")
            rec["last_output"] = m.group(2).rstrip(",")
        res[name] = rec

    for line in output.splitlines():
        mh = re.match(r"^(\S+)\s+is\s+(up|down|administratively down)\b", line)
        if mh:
            nm = normalize_ifname(mh.group(1))
            if VALID_IFACE_RE.match(nm):
                _flush(cur, buf)
                cur, buf = nm, [line]
                continue
        if cur is not None:
            buf.append(line)
    _flush(cur, buf)
    return res

def write_interface_health_sheet(wb, all_cmd_to_files: Dict[str, Dict[str, str]]) -> None:
    """One row per interface with a health signal worth seeing: any errors/CRC/drops,
    or oper-up with 'Last input never' (connected-but-idle, a retire candidate)."""
    cols = ["Hostname", "Port", "Oper", "Input Errors", "CRC", "Output Drops",
            "Last Input", "Last Output", "Flag"]
    if INTERFACE_HEALTH_SHEET_NAME in wb.sheetnames:
        del wb[INTERFACE_HEALTH_SHEET_NAME]
    ws = wb.create_sheet(INTERFACE_HEALTH_SHEET_NAME)
    _census_header(ws, cols)
    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="center")
    DAT_C = Alignment(horizontal="center", vertical="center")
    warn = PatternFill("solid", fgColor="F4CCCC")
    idle = PatternFill("solid", fgColor="FFF2CC")
    rows = []
    for host in sorted(all_cmd_to_files):
        out = _load_cmd_output(all_cmd_to_files[host], "show interfaces", "show interface")
        if not out:
            continue
        for port, rec in parse_show_interface_counters(out).items():
            ie = rec["input_errors"] if isinstance(rec["input_errors"], int) else 0
            cr = rec["crc"] if isinstance(rec["crc"], int) else 0
            od = rec["output_drops"] if isinstance(rec["output_drops"], int) else 0
            has_err = bool(ie or cr or od)
            is_idle = (str(rec["oper"]).lower().startswith("up")
                       and str(rec["last_input"]).lower() == "never")
            if not (has_err or is_idle):
                continue
            flag = []
            if has_err: flag.append("Errors")
            if is_idle: flag.append("Up but idle (no input)")
            rows.append((host, port, rec, "; ".join(flag), has_err, is_idle))
    def _key(t):
        host, port = t[0], t[1]
        nums = [int(x) for x in re.findall(r"\d+", port)]
        return (host.lower(), port[:2].lower(), nums)
    rows.sort(key=_key)
    r = 2
    for host, port, rec, flag, has_err, is_idle in rows:
        vals = [host, port, rec["oper"], rec["input_errors"], rec["crc"],
                rec["output_drops"], rec["last_input"], rec["last_output"], flag]
        for col, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT
            c.alignment = DAT_C if 4 <= col <= 6 else DAT_L
        if has_err:
            ws.cell(row=r, column=9).fill = warn
        elif is_idle:
            ws.cell(row=r, column=9).fill = idle
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    logger.info(f"  [OK] '{INTERFACE_HEALTH_SHEET_NAME}' sheet: {len(rows)} port(s) flagged")


# -----------------------------------------------------------------------------
# Tier 2 #2: Security posture  (port-security / 802.1X / DHCP snooping)
# -----------------------------------------------------------------------------
SECURITY_SHEET_NAME = "Security Posture"

def parse_port_security(output: str) -> Dict[str, Dict[str, str]]:
    """IOS 'show port-security' summary: per-port max/current/violations/action.
    Handles both short (Gi1/0/5) and full (GigabitEthernet1/0/5) names."""
    res: Dict[str, Dict[str, str]] = {}
    for line in output.splitlines():
        toks = line.split()
        if not toks:
            continue
        p = normalize_ifname(toks[0])
        if not PHYSICAL_IFACE_RE.match(p):
            continue
        nums = re.findall(r"\b\d+\b", " ".join(toks[1:]))
        act = ""
        ma = re.search(r"\b(Shutdown|Restrict|Protect)\b", line, re.IGNORECASE)
        if ma: act = ma.group(1).capitalize()
        if len(nums) >= 3:
            res[p] = {"max": nums[0], "current": nums[1], "violations": nums[2], "action": act}
    return res

def parse_auth_sessions(output: str) -> Dict[str, Dict[str, str]]:
    """IOS 'show authentication sessions': per-port 802.1X/MAB method+status+MAC.
    Handles both short and full interface names."""
    res: Dict[str, Dict[str, str]] = {}
    for line in output.splitlines():
        port = ""
        for t in line.split():
            n = normalize_ifname(t)
            if PHYSICAL_IFACE_RE.match(n):
                port = n
                break
        if not port:
            continue
        mac = ""
        mm = re.search(r"\b([0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4})\b", line)
        if mm: mac = mm.group(1)
        method = ""
        mt = re.search(r"\b(dot1x|mab|webauth)\b", line, re.IGNORECASE)
        if mt: method = mt.group(1).lower()
        status = ""
        ms = re.search(r"\b(Authz?|Authc|Authorized|Authenticated|Unauth\w*|Running|Idle|No[- ]?resp\w*)\b",
                       line, re.IGNORECASE)
        if ms: status = ms.group(1)
        if method or mac or status:
            res[port] = {"method": method, "status": status, "mac": mac}
    return res

def parse_dhcp_snooping_binding(output: str) -> Dict[str, int]:
    """'show ip dhcp snooping binding': count of bindings per interface (full or short names)."""
    res: Dict[str, int] = {}
    for line in output.splitlines():
        if not re.search(r"[0-9a-fA-F]{2}[:.\-][0-9a-fA-F]{2}", line):
            continue
        if not re.search(r"\d+\.\d+\.\d+\.\d+", line):
            continue
        port = ""
        for t in line.split():
            n = normalize_ifname(t)
            if PHYSICAL_IFACE_RE.match(n):
                port = n
        if not port:
            continue
        res[port] = res.get(port, 0) + 1
    return res

def write_security_posture_sheet(wb, all_cmd_to_files: Dict[str, Dict[str, str]]) -> None:
    """One row per port with port-security, an 802.1X session, or DHCP-snoop bindings."""
    cols = ["Hostname", "Port", "Port-Security Max", "PS Current", "PS Violations",
            "PS Action", "802.1X Method", "802.1X Status", "Auth MAC", "DHCP-Snoop Bindings"]
    if SECURITY_SHEET_NAME in wb.sheetnames:
        del wb[SECURITY_SHEET_NAME]
    ws = wb.create_sheet(SECURITY_SHEET_NAME)
    _census_header(ws, cols)
    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="center")
    rows = []
    for host in sorted(all_cmd_to_files):
        c2f = all_cmd_to_files[host]
        ps = parse_port_security(_load_cmd_output(c2f, "show port-security"))
        au = parse_auth_sessions(_load_cmd_output(c2f, "show authentication sessions"))
        ds = parse_dhcp_snooping_binding(_load_cmd_output(c2f, "show ip dhcp snooping binding"))
        for p in (set(ps) | set(au) | set(ds)):
            pv = ps.get(p, {}); av = au.get(p, {})
            rows.append((host, p, pv.get("max", ""), pv.get("current", ""),
                         pv.get("violations", ""), pv.get("action", ""),
                         av.get("method", ""), av.get("status", ""), av.get("mac", ""),
                         ds.get(p, "")))
    def _key(t):
        host, port = t[0], t[1]
        nums = [int(x) for x in re.findall(r"\d+", port)]
        return (host.lower(), port[:2].lower(), nums)
    rows.sort(key=_key)
    r = 2
    for row in rows:
        for col, v in enumerate(row, 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT; c.alignment = DAT_L
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    logger.info(f"  [OK] '{SECURITY_SHEET_NAME}' sheet: {len(rows)} port(s)")


# -----------------------------------------------------------------------------
# Tier 2 #3: Routing adjacencies  (OSPF / EIGRP neighbors, BGP peers)
# -----------------------------------------------------------------------------
ROUTING_SHEET_NAME = "Routing Adjacencies"

def parse_ospf_neighbors(output: str) -> List[Dict[str, str]]:
    """'show ip ospf neighbor' -> [{neighbor, state, address, interface}]."""
    rows = []
    for line in output.splitlines():
        m = re.match(r"\s*(\d+\.\d+\.\d+\.\d+)\s+\d+\s+(\S+)\s+\S+\s+(\d+\.\d+\.\d+\.\d+)\s+(\S+)", line)
        if m:
            rows.append({"neighbor": m.group(1), "state": m.group(2),
                         "address": m.group(3), "interface": normalize_ifname(m.group(4))})
    return rows

def parse_eigrp_neighbors(output: str) -> List[Dict[str, str]]:
    """'show ip eigrp neighbors' -> [{neighbor, interface, state}]."""
    rows = []
    for line in output.splitlines():
        m = re.match(r"\s*\d+\s+(\d+\.\d+\.\d+\.\d+)\s+(\S+)\s+\d+\s+(\S+)", line)
        if m:
            rows.append({"neighbor": m.group(1), "interface": normalize_ifname(m.group(2)),
                         "state": f"up {m.group(3)}"})
    return rows

def parse_bgp_summary(output: str) -> List[Dict[str, str]]:
    """'show ip bgp summary' / 'show bgp summary' -> [{neighbor, as, state}].
    Last column (State/PfxRcd) is the established state or the prefix count."""
    rows = []
    for line in output.splitlines():
        m = re.match(r"\s*(\d+\.\d+\.\d+\.\d+|[0-9A-Fa-f:]+:[0-9A-Fa-f:]+)\s+\d+\s+(\d+)\s+.*\s(\S+)\s*$", line)
        if m:
            rows.append({"neighbor": m.group(1), "as": m.group(2), "state": m.group(3)})
    return rows

def write_routing_adjacency_sheet(wb, all_cmd_to_files: Dict[str, Dict[str, str]]) -> None:
    """One row per dynamic-routing adjacency (OSPF/EIGRP neighbor, BGP peer)."""
    cols = ["Hostname", "Protocol", "Neighbor", "State / PfxRcd", "Interface / AS"]
    if ROUTING_SHEET_NAME in wb.sheetnames:
        del wb[ROUTING_SHEET_NAME]
    ws = wb.create_sheet(ROUTING_SHEET_NAME)
    _census_header(ws, cols)
    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="center")
    rows = []
    for host in sorted(all_cmd_to_files):
        c2f = all_cmd_to_files[host]
        for n in parse_ospf_neighbors(_load_cmd_output(c2f, "show ip ospf neighbor")):
            rows.append((host, "OSPF", n["neighbor"], n["state"], n["interface"]))
        for n in parse_eigrp_neighbors(_load_cmd_output(c2f, "show ip eigrp neighbors")):
            rows.append((host, "EIGRP", n["neighbor"], n["state"], n["interface"]))
        for n in parse_bgp_summary(_load_cmd_output(c2f, "show ip bgp summary", "show bgp summary")):
            rows.append((host, "BGP", n["neighbor"], n["state"], f"AS {n['as']}"))
    r = 2
    for row in sorted(rows, key=lambda t: (t[0].lower(), t[1], t[2])):
        for col, v in enumerate(row, 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT; c.alignment = DAT_L
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    logger.info(f"  [OK] '{ROUTING_SHEET_NAME}' sheet: {len(rows)} adjacency(ies)")


# =============================================================================
# NEW-V3.16: INTELLIGENCE LAYER - causality chains + traffic-flow (failure) simulation
#
# A deterministic graph-reasoning pass over the already-parsed InterfaceData (no new
# collection, no external calls - same philosophy as compute_findings()). It builds a
# switch-level graph from CDP/LLDP links, annotates each link with the VLANs it FORWARDS
# vs BLOCKS using real 'show spanning-tree' state, then answers two migration questions:
#
#   * Causality chains  - root condition -> propagation mechanism -> blast radius
#     (sole-gateway SPOFs, transit switches that are the only L2 path to a gateway,
#      single non-bundled uplinks that isolate a switch's endpoints).
#   * Failure Impact    - pull each switch out of the graph and recompute per-VLAN
#     reachability: hard partition / backup-covered (STP reconverges via a named blocked
#     link) / FHRP-covered (standby gateway) / no impact. This is the migration
#     blast-radius simulation.
#
# HONEST LIMITS (also surfaced on the sheets):
#   - The graph is only as complete as CDP/LLDP discovery; links to non-Cisco/off-scan
#     gear are invisible, so impact is a LOWER BOUND. Only scanned<->scanned links are
#     modelled - a switch's single uplink to an off-scan core is not analysed.
#   - This is REACHABILITY simulation, not bandwidth/congestion - there is no traffic
#     volume telemetry. Connectivity-under-failure is exact; the precise post-failure
#     active path is approximate (a backup link is proven to exist and named, but STP's
#     resulting tree is not recomputed without bridge priorities/costs).
#   - Scope is L2 reachability of endpoints to their VLAN's SVI gateway (the migration-
#     critical question). L3 core path recomputation between gateways is out of scope.
# =============================================================================
CAUSALITY_SHEET_NAME = "Causality Chains"
FAILURE_SHEET_NAME   = "Failure Impact"
_SEV_FILL = {"High": "F4CCCC", "Medium": "FCE5CD", "Low": "FFF2CC", "Info": "EFEFEF"}


def _vlan_in_ranges(vid: int, s: str) -> bool:
    """True if integer VLAN id `vid` falls in a Cisco range string like '10,20-23,40'.
    Membership-only (no enumeration), so a '1-4094' trunk-allowed list never explodes."""
    s = (s or "").strip().lower()
    if not s or s in ("none", "--", "n/a"):
        return False
    if s in ("all", "1-4094"):
        return True
    for tok in re.split(r"[,\s]+", s):
        if not tok:
            continue
        if "-" in tok:
            try:
                lo, hi = (int(x) for x in tok.split("-", 1))
            except ValueError:
                continue
            if lo <= vid <= hi:
                return True
        elif tok.isdigit() and int(tok) == vid:
            return True
    return False


def build_network_model(all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> Dict[str, object]:
    """Switch-level graph shared by the causality chains and the failure simulation.

    Returns:
      hosts            : sorted scanned hostnames
      links            : list of {a, ap, b, bp, is_pc, da, db} undirected inter-switch
                         links where BOTH ends are scanned (a/b are real hostname keys)
      gw               : {vid: [{host, fhrp(bool), raw}]}      (SVIs = L3 gateways)
      access_presence  : {vid: set(hosts with an access port in vid)}
      endpoints        : {(host, vid): learned-MAC count}
      vlans            : set of "interesting" VLAN ids (have a gateway and/or endpoints)
    """
    cmap = _canon_host_map(all_interfaces)
    hosts = sorted(all_interfaces.keys())

    gw: Dict[int, List[Dict[str, object]]] = {}
    access_presence: Dict[int, set] = {}
    endpoints: Dict[Tuple[str, int], int] = {}

    for host, ifaces in all_interfaces.items():
        for port, d in ifaces.items():
            m = re.match(r"^Vlan(\d+)$", port, re.IGNORECASE)
            if m:
                vid = int(m.group(1))
                raw = (d.hsrp_behavior or "").strip()
                gw.setdefault(vid, []).append({"host": host, "fhrp": bool(raw), "raw": raw})
            if (d.switchport_mode or "") == "Access" and d.vlan.isdigit():
                vid = int(d.vlan)
                access_presence.setdefault(vid, set()).add(host)
                n = len(_split_macs(d.end_host_mac))
                if n:
                    endpoints[(host, vid)] = endpoints.get((host, vid), 0) + n

    # Inter-switch links from the shared CDP/LLDP builder; resolve both endpoints to real
    # hostname keys so we can read each side's STP/trunk state. Both ends must be scanned.
    links: List[Dict[str, object]] = []
    for link in compute_topology_links(all_interfaces):
        ah = cmap.get(_canon_host(str(link["a_host"])))
        bh = cmap.get(_canon_host(str(link["b_host"])))
        if not ah or not bh or ah == bh:
            continue
        ap = normalize_ifname(str(link["a_port"]))
        bp = normalize_ifname(str(link.get("b_port", "")))
        da = all_interfaces.get(ah, {}).get(ap)
        db = all_interfaces.get(bh, {}).get(bp)
        is_pc = bool((da and da.port_channel) or (db and db.port_channel))
        links.append({"a": ah, "ap": ap, "b": bh, "bp": bp, "is_pc": is_pc, "da": da, "db": db})

    vlans = set(gw) | set(access_presence) | {v for (_, v) in endpoints}
    return {"hosts": hosts, "links": links, "gw": gw,
            "access_presence": access_presence, "endpoints": endpoints, "vlans": vlans}


def _link_carries(link: Dict[str, object], vid: int) -> str:
    """How a link relates to VLAN `vid`: 'fwd' (forwarding), 'blk' (STP-blocked backup),
    or '' (not carried). STP state wins; absent STP info falls back to the VLAN being
    mutually trunk-allowed on both ends. An STP block on either end => backup."""
    da, db = link.get("da"), link.get("db")
    if (da and _vlan_in_ranges(vid, da.stp_blk_vlans)) or (db and _vlan_in_ranges(vid, db.stp_blk_vlans)):
        return "blk"
    if (da and _vlan_in_ranges(vid, da.stp_fwd_vlans)) and (db and _vlan_in_ranges(vid, db.stp_fwd_vlans)):
        return "fwd"
    a_allow = bool(da) and (_vlan_in_ranges(vid, da.trunk_allowed_vlans)
                            or str(vid) == (da.trunk_native_vlan or "").strip())
    b_allow = bool(db) and (_vlan_in_ranges(vid, db.trunk_allowed_vlans)
                            or str(vid) == (db.trunk_native_vlan or "").strip())
    return "fwd" if (a_allow and b_allow) else ""


def _vlan_components(model: Dict[str, object], vid: int,
                     removed_host: Optional[str] = None,
                     include_backup: bool = False) -> List[set]:
    """Connected components (list of host-sets) of switches reachable from each other for
    VLAN `vid`, over forwarding links (plus STP-blocked backups if include_backup), with
    `removed_host` deleted from the graph."""
    nodes = set()
    for g in model["gw"].get(vid, []):
        nodes.add(g["host"])
    nodes |= model["access_presence"].get(vid, set())
    nodes |= {h for (h, v) in model["endpoints"] if v == vid}
    adj: Dict[str, set] = {n: set() for n in nodes}
    for link in model["links"]:
        a, b = link["a"], link["b"]
        if removed_host in (a, b):
            continue
        rel = _link_carries(link, vid)
        if rel == "fwd" or (include_backup and rel == "blk"):
            adj.setdefault(a, set()); adj.setdefault(b, set())
            adj[a].add(b); adj[b].add(a)
    adj.pop(removed_host, None)
    seen: set = set()
    comps: List[set] = []
    for start in adj:
        if start in seen:
            continue
        stack = [start]; comp: set = set()
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x); comp.add(x)
            stack.extend(y for y in adj.get(x, ()) if y not in seen)
        comps.append(comp)
    return comps


def compute_causality_chains(all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> List[Tuple[str, str, str, str, str]]:
    """Root-cause -> mechanism -> impact -> mitigation chains, derived from the network
    model. Returns (severity, trigger, mechanism, impact, mitigation) tuples."""
    model = build_network_model(all_interfaces)
    chains: List[Tuple[str, str, str, str, str]] = []

    def _eps(vid: int) -> set:
        e = {h for (h, v), n in model["endpoints"].items() if v == vid and n > 0}
        return e | model["access_presence"].get(vid, set())

    def _ep_count(vid: int, hosts: Optional[set] = None) -> int:
        return sum(n for (h, v), n in model["endpoints"].items()
                   if v == vid and (hosts is None or h in hosts))

    # Chain A: sole-gateway SPOF (one in-scan gateway, no FHRP) with remote endpoints.
    for vid in sorted(model["vlans"]):
        gws = model["gw"].get(vid, [])
        if not gws:
            continue
        gw_hosts = sorted({g["host"] for g in gws})
        if len(gw_hosts) == 1 and not any(g["fhrp"] for g in gws):
            remote = sorted(_eps(vid) - set(gw_hosts))
            if remote:
                n_ep = _ep_count(vid)
                chains.append((
                    "High",
                    f"Gateway {gw_hosts[0]}:Vlan{vid} goes down",
                    f"It is the only in-scan L3 gateway for VLAN {vid}, with no FHRP peer",
                    f"Every VLAN {vid} host loses its default gateway "
                    f"({n_ep or 'unknown #'} endpoint(s); {len(remote)} other switch(es) affected)",
                    "Add an FHRP (HSRP/VRRP/GLBP) peer, or confirm a redundant off-scan gateway",
                ))

    # Chain B: transit articulation - removing a switch partitions a VLAN's endpoints from
    # its gateway. A reachable STP-blocked backup softens High -> Medium (transient only).
    for host in model["hosts"]:
        for vid in sorted(model["vlans"]):
            gw_hosts = [g["host"] for g in model["gw"].get(vid, [])]
            surviving_gw = [h for h in gw_hosts if h != host]
            if not gw_hosts or host in gw_hosts or not surviving_gw:
                continue  # gateway-loss is chain A's / the failure sheet's job
            ep_hosts = _eps(vid); ep_hosts.discard(host)
            if not ep_hosts:
                continue
            stranded = set()
            for comp in _vlan_components(model, vid, removed_host=host):
                if not any(g in comp for g in surviving_gw):
                    stranded |= (comp & ep_hosts)
            if not stranded:
                continue
            still = set()
            for comp in _vlan_components(model, vid, removed_host=host, include_backup=True):
                if not any(g in comp for g in surviving_gw):
                    still |= (comp & stranded)
            gwname = surviving_gw[0]
            if still:
                chains.append((
                    "High",
                    f"Transit switch {host} is removed / migrated",
                    f"It is the only forwarding L2 path from {', '.join(sorted(stranded))} "
                    f"to gateway {gwname} for VLAN {vid}",
                    f"{len(still)} switch(es) / {_ep_count(vid, still)} endpoint(s) lose "
                    f"reachability to the VLAN {vid} gateway, with no backup link",
                    "Add a redundant uplink/path, or migrate this switch in the same wave",
                ))
            else:
                chains.append((
                    "Medium",
                    f"Transit switch {host} is removed / migrated",
                    f"It carries the active L2 path to gateway {gwname} for VLAN {vid}; a "
                    f"redundant link exists but is STP-blocked",
                    f"{_ep_count(vid, stranded)} endpoint(s) hit a transient outage while STP "
                    f"reconverges onto the backup link",
                    "Expected to self-heal; verify STP reconvergence time before cutover",
                ))

    # Chain C: a switch's only forwarding uplink for an endpoint VLAN is a single
    # (non-port-channel) link -> link loss isolates that VLAN.
    for host in model["hosts"]:
        host_links = [l for l in model["links"] if host in (l["a"], l["b"])]
        host_vlans = {v for (h, v), n in model["endpoints"].items() if h == host and n > 0}
        host_vlans |= {v for v, hs in model["access_presence"].items() if host in hs}
        for vid in sorted(host_vlans):
            if host in [g["host"] for g in model["gw"].get(vid, [])]:
                continue  # gateway is local; uplink loss doesn't strand it from L3
            carrying = [l for l in host_links if _link_carries(l, vid) == "fwd"]
            backups  = [l for l in host_links if _link_carries(l, vid) == "blk"]
            if len(carrying) == 1 and not backups and not carrying[0]["is_pc"]:
                l = carrying[0]
                far = l["b"] if l["a"] == host else l["a"]
                near_port = l["ap"] if l["a"] == host else l["bp"]
                n_ep = model["endpoints"].get((host, vid), 0)
                chains.append((
                    "Medium",
                    f"Uplink {host} {near_port} -> {far} fails",
                    f"It is {host}'s only forwarding inter-switch link carrying VLAN {vid}, "
                    f"and it is a single (non-port-channel) link",
                    f"VLAN {vid} on {host} is isolated from the fabric"
                    + (f" ({n_ep} endpoint(s))" if n_ep else ""),
                    "Add a second uplink or bundle the link as a port-channel",
                ))

    sev_rank = {"High": 0, "Medium": 1, "Low": 2, "Info": 3}
    chains.sort(key=lambda c: (sev_rank.get(c[0], 9), c[1], c[3]))
    seen: set = set(); uniq: List[Tuple[str, str, str, str, str]] = []
    for c in chains:
        if c not in seen:
            seen.add(c); uniq.append(c)
    return uniq


def compute_failure_impact(all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> List[Dict[str, object]]:
    """Migration blast-radius simulation: remove each scanned switch and recompute per-VLAN
    endpoint->gateway reachability. One roll-up record per switch. 'Stranded' counts
    collateral endpoints on OTHER switches (the removed switch's own endpoints migrate with
    it). Returns records sorted by severity then blast radius."""
    model = build_network_model(all_interfaces)
    results: List[Dict[str, object]] = []

    def _ep_count(vid: int, hosts: set) -> int:
        return sum(n for (h, v), n in model["endpoints"].items() if v == vid and h in hosts)

    for host in model["hosts"]:
        per_vlan: List[Tuple[int, str, int]] = []   # (vid, status, stranded)
        worst = 99; total_stranded = 0; hard = backup = fhrp = 0

        for vid in sorted(model["vlans"]):
            gw_hosts = [g["host"] for g in model["gw"].get(vid, [])]
            if not gw_hosts:
                continue  # no in-scan gateway -> "stranded from gateway" is N/A (see Findings)
            ep_hosts = {h for (h, v), n in model["endpoints"].items() if v == vid and n > 0}
            ep_hosts |= model["access_presence"].get(vid, set())
            if not ep_hosts:
                continue
            surviving_gw = [h for h in gw_hosts if h != host]
            any_fhrp = any(g["fhrp"] for g in model["gw"].get(vid, []))
            touches = (host in gw_hosts) or (host in ep_hosts) or any(
                host in (l["a"], l["b"]) and _link_carries(l, vid) for l in model["links"])
            if not touches:
                continue

            comps_active = _vlan_components(model, vid, removed_host=host)
            stranded_active = set()
            for comp in comps_active:
                if not any(g in comp for g in surviving_gw):
                    stranded_active |= (comp & ep_hosts)
            stranded_active.discard(host)   # removed switch's own endpoints move with it

            if (host in gw_hosts) and not surviving_gw and (ep_hosts - {host}):
                status, rank = "Hard partition", 0
                strand = _ep_count(vid, ep_hosts - {host})
            elif stranded_active:
                still = set()
                for comp in _vlan_components(model, vid, removed_host=host, include_backup=True):
                    if not any(g in comp for g in surviving_gw):
                        still |= (comp & stranded_active)
                if still:
                    status, rank = "Hard partition", 0
                    strand = _ep_count(vid, still)
                else:
                    status, rank = "Backup-covered", 1
                    strand = 0
            elif (host in gw_hosts) and surviving_gw and any_fhrp:
                status, rank, strand = "FHRP-covered", 2, 0
            else:
                continue

            per_vlan.append((vid, status, strand))
            total_stranded += strand
            worst = min(worst, rank)
            hard += status == "Hard partition"
            backup += status == "Backup-covered"
            fhrp += status == "FHRP-covered"

        if not per_vlan:
            sev = "Info"
            detail = "No reachability impact from removing this switch (within the scan)."
        else:
            sev = {0: "High", 1: "Medium", 2: "Low"}.get(worst, "Info")
            order = {"Hard partition": 0, "Backup-covered": 1, "FHRP-covered": 2}
            pv = sorted(per_vlan, key=lambda t: (order.get(t[1], 9), -t[2], t[0]))
            parts = [f"VLAN {vid}: {st}" + (f" ({s} ep)" if s else "") for vid, st, s in pv[:8]]
            if len(pv) > 8:
                parts.append(f"... +{len(pv) - 8} more")
            detail = "; ".join(parts)

        results.append({"host": host, "severity": sev, "vlans_impacted": len(per_vlan),
                        "stranded": total_stranded, "hard": hard, "backup": backup,
                        "fhrp": fhrp, "detail": detail})

    sev_rank = {"High": 0, "Medium": 1, "Low": 2, "Info": 3}
    results.sort(key=lambda r: (sev_rank.get(r["severity"], 9), -r["stranded"],
                                -r["vlans_impacted"], r["host"].lower()))
    return results


def write_causality_chains_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> None:
    """Write (or replace) 'Causality Chains': cause -> mechanism -> blast radius reasoning."""
    cols = ["Severity", "Trigger (root cause)", "Mechanism (why it propagates)",
            "Impact (blast radius)", "Mitigation"]
    if CAUSALITY_SHEET_NAME in wb.sheetnames:
        del wb[CAUSALITY_SHEET_NAME]
    ws = wb.create_sheet(CAUSALITY_SHEET_NAME)
    _census_header(ws, cols)
    chains = compute_causality_chains(all_interfaces)
    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="top", wrap_text=True)
    r = 2
    for sev, trig, mech, impact, mit in chains:
        for col, v in enumerate([sev, trig, mech, impact, mit], 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT; c.alignment = DAT_L
            if col == 1 and sev in _SEV_FILL:
                c.fill = PatternFill("solid", fgColor=_SEV_FILL[sev])
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    for colL, w in (("B", 34), ("C", 46), ("D", 46), ("E", 40)):
        ws.column_dimensions[colL].width = w
    logger.info(f"  [OK] '{CAUSALITY_SHEET_NAME}' sheet: {len(chains)} chain(s)")


def write_failure_impact_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> None:
    """Write (or replace) 'Failure Impact': per-switch migration blast-radius simulation."""
    cols = ["Severity", "Switch (remove / migrate)", "VLANs Impacted", "Stranded Endpoints",
            "Hard Partitions", "Backup-Covered", "FHRP-Covered", "Per-VLAN Detail"]
    if FAILURE_SHEET_NAME in wb.sheetnames:
        del wb[FAILURE_SHEET_NAME]
    ws = wb.create_sheet(FAILURE_SHEET_NAME)
    _census_header(ws, cols)
    rows = compute_failure_impact(all_interfaces)
    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="top", wrap_text=True)
    r = 2
    for rec in rows:
        vals = [rec["severity"], rec["host"], rec["vlans_impacted"], rec["stranded"],
                rec["hard"], rec["backup"], rec["fhrp"], rec["detail"]]
        for col, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT; c.alignment = DAT_L
            if col == 1 and rec["severity"] in _SEV_FILL:
                c.fill = PatternFill("solid", fgColor=_SEV_FILL[rec["severity"]])
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    ws.column_dimensions["H"].width = 70
    logger.info(f"  [OK] '{FAILURE_SHEET_NAME}' sheet: {len(rows)} switch(es) analyzed")


# -----------------------------------------------------------------------------
# NEW-V3.18: Physical Health (L1). One row per physical port - negotiated
# speed/duplex/media, error counters, port-channel, PoE, and a derived physical
# risk flag. Pure derivation: reuses parse_show_interface_counters (errors),
# build_network_model (uplink topology -> single-fiber), and DevicePhysical
# (PoE budget). Negotiated duplex/media/speed come from the 'show interfaces'
# DETAIL block because InterfaceData.duplex is normalized and loses half-duplex.
# No new collection, no new InterfaceData fields, no new imports.
# -----------------------------------------------------------------------------
PHYSICAL_HEALTH_SHEET_NAME = "Physical Health"

# Logical (non-physical) interfaces excluded from the per-physical-port sheet.
_NON_PHYSICAL_RE = re.compile(
    r"^(Vlan\d+|Lo\d+|Loopback\d+|Po\d+|Port-channel\d+|Tu\d+|Tunnel\d+|"
    r"Null\d*|mgmt0|Bundle-Ether\d+|BE\d+)$", re.IGNORECASE)

def _is_physical_port(port: str) -> bool:
    p = (port or "").strip()
    return bool(p) and not _NON_PHYSICAL_RE.match(p)

def _classify_media(s: str) -> str:
    """Map a 'media type is ...' / port-type string to copper / SFP-fiber / QSFP / unknown."""
    low = (s or "").lower()
    if not low:
        return "unknown"
    if "qsfp" in low:
        return "QSFP"
    if ("sfp" in low or "base-sx" in low or "base-lx" in low or "base-sr" in low
            or "base-lr" in low or "base-er" in low or "1000basesx" in low or "fiber" in low):
        return "SFP/fiber"
    if ("basetx" in low or "baset" in low or "10/100" in low or "rj45" in low or "copper" in low):
        return "copper"
    return s.strip()[:24] or "unknown"

def parse_interface_phy(output: str) -> Dict[str, Dict[str, str]]:
    """Best-effort negotiated duplex/speed/media per interface from IOS 'show interfaces' /
    NX-OS 'show interface' DETAIL. Returns {port: {'duplex','speed','media'}}; values stay
    blank when the platform format omits the line (some NX-OS) -> caller marks unknown."""
    res: Dict[str, Dict[str, str]] = {}
    cur = None
    buf: List[str] = []

    def _flush(name, lines):
        if not name or not lines:
            return
        text = "\n".join(lines)
        rec = {"duplex": "", "speed": "", "media": ""}
        m = re.search(r"\b(Full|Half|Auto)-duplex\b", text, re.IGNORECASE)
        if m:
            rec["duplex"] = m.group(1).capitalize()
        m = re.search(r"-duplex,\s*([^,]+?)\s*,", text)        # token between duplex and next comma
        if m:
            rec["speed"] = m.group(1).strip()
        m = re.search(r"media type is\s+(.+)", text, re.IGNORECASE)
        if m:
            rec["media"] = _classify_media(m.group(1).strip())
        res[name] = rec

    for line in output.splitlines():
        mh = re.match(r"^(\S+)\s+is\s+(?:up|down|administratively down)\b", line)
        if mh:
            nm = normalize_ifname(mh.group(1))
            if VALID_IFACE_RE.match(nm):
                _flush(cur, buf)
                cur, buf = nm, [line]
                continue
        if cur is not None:
            buf.append(line)
    _flush(cur, buf)
    return res

def _parse_poe_watts(output: str) -> Dict[str, float]:
    """Best-effort per-port PoE watts (consumed) from 'show power inline'. {port: watts}.
    Reads the first decimal on each interface line (the consumed-watts column)."""
    res: Dict[str, float] = {}
    for line in output.splitlines():
        it = IFACE_TOKEN_RE.search(line)
        if not it:
            continue
        intf = normalize_ifname(it.group(0))
        if not _is_physical_port(intf):
            continue
        m = re.search(r"\b(\d+\.\d+)\b", line[it.end():])
        if m:
            try:
                res[intf] = float(m.group(1))
            except ValueError:
                pass
    return res

def _poe_device_util(all_device_physical: List[DevicePhysical]) -> Dict[str, float]:
    """hostname -> PoE utilisation %, from DevicePhysical capacity/drawn (mirrors Capacity sheet)."""
    out: Dict[str, float] = {}
    for dp in all_device_physical:
        try:
            cap = float(str(dp.power_capacity_w).split()[0]) if str(dp.power_capacity_w).strip() else 0.0
            drawn = float(str(dp.power_drawn_w).split()[0]) if str(dp.power_drawn_w).strip() else None
        except (ValueError, IndexError):
            cap, drawn = 0.0, None
        if cap > 0 and drawn is not None:
            out[dp.hostname] = round(100.0 * drawn / cap, 1)
    return out

def _physical_uplink_index(model: Dict[str, object]):
    """From the shared network model, return (uplink_ports, single_fiber_ports):
       uplink_ports       : set of (host, local_port) facing another scanned switch
       single_fiber_ports : set of (host, local_port) where that port is the host's ONLY
                            inter-switch link and it is not a port-channel (no L1 redundancy)."""
    by_host: Dict[str, List[Tuple[str, str, bool]]] = {}
    for l in model["links"]:                                   # links: {a,ap,b,bp,is_pc,da,db}
        if l.get("ap"):
            by_host.setdefault(l["a"], []).append((l["b"], l["ap"], bool(l["is_pc"])))
        if l.get("bp"):
            by_host.setdefault(l["b"], []).append((l["a"], l["bp"], bool(l["is_pc"])))
    uplink_ports = set()
    single_fiber = set()
    for host, ups in by_host.items():
        for (_oh, lp, _pc) in ups:
            uplink_ports.add((host, lp))
        distinct = {(oh, lp) for (oh, lp, _pc) in ups}
        if len(distinct) == 1:
            oh, lp = next(iter(distinct))
            pc = any(p for (o, l, p) in ups if (o, l) == (oh, lp))
            if not pc:
                single_fiber.add((host, lp))
    return uplink_ports, single_fiber

def write_physical_health_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]],
                                all_cmd_to_files: Dict[str, Dict[str, str]],
                                all_device_physical: List[DevicePhysical]) -> List[dict]:
    """Write the 'Physical Health' (L1) sheet and return its records for the snapshot.
    One row per physical port; risk flag derived purely from already-parsed data."""

    model = build_network_model(all_interfaces)
    uplink_ports, single_fiber = _physical_uplink_index(model)
    poe_util = _poe_device_util(all_device_physical)

    headers = ["Switch", "Port", "Status", "Negotiated Speed", "Duplex", "Media Type",
               "Input Errors", "CRC Errors", "Output Drops", "Port-Channel",
               "PoE Allocated (W)", "Physical Risk"]

    def _intpos(v):
        return isinstance(v, int) and v > 0

    records: List[dict] = []
    for host in sorted(all_interfaces):
        c2f = all_cmd_to_files.get(host, {})
        out = _load_cmd_output(c2f, "show interfaces", "show interface")
        counters = parse_show_interface_counters(out) if out else {}
        phy = parse_interface_phy(out) if out else {}
        poe_out = _load_cmd_output(c2f, "show power inline")
        poe_watts = _parse_poe_watts(poe_out) if poe_out else {}

        for port, d in sorted(all_interfaces[host].items()):
            if not _is_physical_port(port):
                continue
            cnt = counters.get(port, {})
            ph = phy.get(port, {})

            status = d.status or cnt.get("oper", "")
            oper_up = bool(re.search(r"up|connected", (cnt.get("oper", "") or status or ""), re.IGNORECASE))

            speed = ph.get("speed") or normalize_speed(d.speed) or d.speed or ""
            duplex = ph.get("duplex") or ""                    # DETAIL is authoritative for half
            media = ph.get("media") or (_classify_media(d.port_type) if d.port_type else "")

            ie = cnt.get("input_errors", "")
            crc = cnt.get("crc", "")
            od = cnt.get("output_drops", "")
            pc = d.port_channel or ""

            # PoE cell: per-port watts if parseable, else the status word; mark over-budget devices.
            watts = poe_watts.get(port)
            if watts is not None:
                poe_cell = f"{watts:g} W"
            elif d.poe_status:
                poe_cell = d.poe_status
            else:
                poe_cell = ""
            util = poe_util.get(host)
            if util is not None and util > 90 and (watts is not None or d.poe_status):
                poe_cell = (poe_cell + f"  (dev PoE {util:g}%)").strip()

            # ---- risk derivation (highest severity wins for the cell fill) ----
            flags: List[str] = []
            sev = "Info"
            is_uplink = (host, port) in uplink_ports
            is_trunk = (d.switchport_mode or "").strip().lower() == "trunk"

            if re.search(r"err[- ]?disab", (status or ""), re.IGNORECASE):
                flags.append("err-disabled"); sev = "High"
            if duplex == "Half" and (is_trunk or is_uplink):
                flags.append("half-duplex"); sev = "High"
            if (host, port) in single_fiber:
                flags.append("single-fiber-uplink")
                if sev != "High": sev = "Medium"
            if oper_up and (_intpos(ie) or _intpos(crc) or _intpos(od)):
                flags.append("error-rate-high")
                if sev != "High": sev = "Medium"
            if not flags:
                flags = ["ok"]

            records.append({"switch": host, "port": port, "status": status or "",
                            "speed": speed or "unknown", "duplex": duplex or "unknown",
                            "media": media or "unknown", "input_errors": ie, "crc_errors": crc,
                            "output_drops": od, "port_channel": pc, "poe": poe_cell,
                            "risk": "; ".join(flags), "severity": sev})

    # ---- write the sheet ----
    ws = wb.create_sheet(PHYSICAL_HEALTH_SHEET_NAME)
    hdr_font = Font(bold=True, color="FFFFFF")
    hdr_fill = PatternFill("solid", fgColor="434343")
    for col, h in enumerate(headers, 1):
        c = ws.cell(1, col, h)
        c.font = hdr_font
        c.fill = hdr_fill
        c.alignment = Alignment(horizontal="center")
    for r, rec in enumerate(records, 2):
        vals = [rec["switch"], rec["port"], rec["status"], rec["speed"], rec["duplex"],
                rec["media"], rec["input_errors"], rec["crc_errors"], rec["output_drops"],
                rec["port_channel"], rec["poe"], rec["risk"]]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v)
            if col == len(headers) and rec["severity"] in _SEV_FILL:     # fill Physical Risk cell
                c.fill = PatternFill("solid", fgColor=_SEV_FILL[rec["severity"]])
    for i, w in enumerate([16, 16, 14, 16, 9, 14, 12, 11, 13, 13, 18, 28], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"

    n_flagged = sum(1 for x in records if x["risk"] != "ok")
    logger.info(f"  [OK] '{PHYSICAL_HEALTH_SHEET_NAME}' sheet: {len(records)} physical port(s), "
                f"{n_flagged} flagged")
    return records


# -----------------------------------------------------------------------------
# NEW-V3.19: Full-stack flow trace (L1->L3). Given two endpoint IPs, derive the
# path: locate each endpoint (end_host_ip), resolve gateway SVIs per subnet
# (svi_ip + subnet_primary_route containment + FHRP peers), decide L2 vs L3, walk
# the fabric over STP-forwarding links (_link_carries), flag single points of
# failure (single-fiber uplinks, single gateway, VLAN partition) and score risk.
# Pure derivation - routing comes from InterfaceData (no routing_data dict exists).
# L4 is NOT simulated (no ACL/service-policy is collected). No new imports.
# -----------------------------------------------------------------------------
FLOW_TRACE_SHEET_NAME = "Flow Trace"
_RISK_FILL = {"LOW": "36E08A", "MEDIUM": "FFE566", "HIGH": "FF9F45", "CRITICAL": "FF5775"}
_RISK_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

def _ip_in_prefix(ip: str, prefix: str) -> bool:
    if not ip or not prefix:
        return False
    try:
        import ipaddress
        return ipaddress.ip_address(ip.strip()) in ipaddress.ip_network(prefix.strip(), strict=False)
    except Exception:
        return False

def _find_endpoint_by_ip(all_interfaces: Dict[str, Dict[str, InterfaceData]], ip: str):
    """Locate the access switch/port/VLAN that learned `ip`. Returns (host, port, vid, mac) or None."""
    ip = (ip or "").strip()
    for host in sorted(all_interfaces):
        for port, d in sorted(all_interfaces[host].items()):
            if not _is_physical_port(port):
                continue
            if (d.end_host_ip or "").strip() == ip:
                vid = int(d.vlan) if (d.vlan or "").isdigit() else None
                return (host, port, vid, d.end_host_mac or "")
    return None

def _find_gateways_for(all_interfaces: Dict[str, Dict[str, InterfaceData]], ip: str, vid):
    """All scanned SVIs that serve `ip` (by VLAN id or by subnet containment) = candidate
    gateways. >1 entry => FHRP/redundant gateway; 1 => single gateway (L3 SPOF candidate)."""
    res = []
    for host in sorted(all_interfaces):
        for port, d in all_interfaces[host].items():
            m = re.match(r"^Vlan(\d+)$", port, re.IGNORECASE)
            if not m:
                continue
            svid = int(m.group(1))
            match = (vid is not None and svid == vid) or _ip_in_prefix(ip, d.subnet_primary_route)
            if match:
                res.append({"host": host, "vid": svid, "svi_ip": d.svi_ip,
                            "fhrp": d.hsrp_behavior, "source": d.routing_source,
                            "next_hop": d.route_next_hop, "prefix": d.subnet_primary_route})
    return res

def _bfs_forwarding_path(model: Dict[str, object], vid, src_host: str, dst_host: str):
    """Shortest path of inter-switch hops from src_host to dst_host over STP-forwarding links
    for VLAN `vid`. Returns [] if same host, a list of hop dicts, or None if no forwarding path."""
    if not vid or src_host == dst_host:
        return [] if src_host == dst_host else None
    from collections import deque
    adj: Dict[str, set] = {}
    portmap: Dict[Tuple[str, str], Tuple[str, str]] = {}
    for link in model["links"]:
        if _link_carries(link, vid) != "fwd":
            continue
        a, b, ap, bp = link["a"], link["b"], link["ap"], link["bp"]
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
        portmap[(a, b)] = (ap, bp)
        portmap[(b, a)] = (bp, ap)
    prev: Dict[str, Optional[str]] = {src_host: None}
    q = deque([src_host])
    while q:
        cur = q.popleft()
        if cur == dst_host:
            break
        for nb in sorted(adj.get(cur, ())):
            if nb not in prev:
                prev[nb] = cur
                q.append(nb)
    if dst_host not in prev:
        return None
    chain = []
    node = dst_host
    while prev[node] is not None:
        p = prev[node]
        ap, bp = portmap[(p, node)]
        chain.append({"from": p, "out_port": ap, "in_port": bp, "to": node})
        node = p
    chain.reverse()
    return chain

def trace_full_flow(src_ip: str, dst_ip: str,
                    all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> dict:
    """Derive an L1->L3 path between two endpoint IPs and score its resilience.
    Returns {summary{...}, hops[...]}. Path is a lower bound (scan-bound topology)."""
    model = build_network_model(all_interfaces)
    uplink_ports, single_fiber = _physical_uplink_index(model)

    src = _find_endpoint_by_ip(all_interfaces, src_ip)
    dst = _find_endpoint_by_ip(all_interfaces, dst_ip)
    src_vid = src[2] if src else None
    dst_vid = dst[2] if dst else None
    src_gws = _find_gateways_for(all_interfaces, src_ip, src_vid)
    dst_gws = _find_gateways_for(all_interfaces, dst_ip, dst_vid)
    same_subnet = bool(src_vid and dst_vid and src_vid == dst_vid)

    hops: List[dict] = []
    spofs: List[str] = []
    notes: List[str] = []
    partitioned = False

    def _add(layer, frm, to, iface, detail, spof=False):
        hops.append({"n": len(hops) + 1, "layer": layer, "from": frm, "to": to,
                     "iface": iface, "detail": detail, "spof": bool(spof)})

    def _walk(vid, a_host, a_port_in, b_host, segment_label):
        """Append fabric hops a_host->b_host for vid; flag single-fiber uplinks; detect partition."""
        nonlocal partitioned
        path = _bfs_forwarding_path(model, vid, a_host, b_host)
        if path is None:
            partitioned = True
            _add("L2", a_host, b_host, "", f"{segment_label}: NO forwarding path in VLAN {vid} "
                                           f"(partitioned / off-scan)", spof=True)
            spofs.append(f"partition:{a_host}->{b_host}:vlan{vid}")
            return
        for h in path:
            sf_from = (h["from"], h["out_port"]) in single_fiber
            sf_to = (h["to"], h["in_port"]) in single_fiber
            sf = sf_from or sf_to
            det = f"trunk {h['out_port']} -> {h['in_port']} (VLAN {vid})"
            if sf:
                det += "  [single-fiber uplink]"
                if sf_from:
                    spofs.append(f"uplink:{h['from']}:{h['out_port']}")
                if sf_to:
                    spofs.append(f"uplink:{h['to']}:{h['in_port']}")
            _add("L1/L2", h["from"], h["to"], h["out_port"], det, spof=sf)

    # ---- source endpoint ----
    if src:
        _add("L1/L2", src_ip, src[0], src[1], f"endpoint on access port (VLAN {src_vid})")
    else:
        notes.append(f"source {src_ip} not located on any scanned access port (off-scan)")
        _add("L1/L2", src_ip, "?", "", "source endpoint NOT located (off-scan)")

    if same_subnet:
        # ---- L2 flow: src access switch -> dst access switch within the VLAN ----
        if src and dst:
            _walk(src_vid, src[0], src[1], dst[0], "L2 switching")
        notes.append(f"same-subnet L2 flow (VLAN {src_vid}); no gateway traversal")
    else:
        # ---- L3 flow: src -> src gateway -> (route) -> dst gateway -> dst ----
        reachable_src_gw = None
        if src and src_gws:
            for g in src_gws:
                if _bfs_forwarding_path(model, src_vid, src[0], g["host"]) is not None:
                    reachable_src_gw = g
                    break
            reachable_src_gw = reachable_src_gw or src_gws[0]
        if src and reachable_src_gw:
            _walk(src_vid, src[0], src[1], reachable_src_gw["host"], "to src gateway")
            gw_spof = len(src_gws) <= 1
            fhrp = (reachable_src_gw.get("fhrp") or "").strip()
            det = f"gateway SVI {reachable_src_gw.get('svi_ip','?')} on {reachable_src_gw['host']} " \
                  f"(VLAN {src_vid}); {'FHRP: ' + fhrp if fhrp else 'no FHRP'}"
            if gw_spof:
                det += "  [single gateway]" + ("" if not fhrp else " - only one peer in scan")
                spofs.append(f"gateway:vlan{src_vid}:{reachable_src_gw['host']}")
            _add("L3", reachable_src_gw["host"], reachable_src_gw["host"],
                 f"Vlan{src_vid}", det, spof=gw_spof)
            # routing decision toward dst subnet
            same_router = bool(dst_gws and any(g["host"] == reachable_src_gw["host"] for g in dst_gws))
            if same_router:
                _add("L3", reachable_src_gw["host"], reachable_src_gw["host"], "",
                     f"inter-VLAN routed locally to VLAN {dst_vid} "
                     f"(source: {reachable_src_gw.get('source','?')})")
            else:
                nh = reachable_src_gw.get("next_hop") or reachable_src_gw.get("source") or "unknown"
                _add("L3", reachable_src_gw["host"], dst_gws[0]["host"] if dst_gws else "?", "",
                     f"routed to dst subnet via {nh} "
                     f"(redundancy of routed segment not verified - scan bound)")
                notes.append("routed inter-router segment is a lower bound (off-scan paths not modeled)")
        # dst gateway -> dst
        reachable_dst_gw = None
        if dst and dst_gws:
            for g in dst_gws:
                if _bfs_forwarding_path(model, dst_vid, g["host"], dst[0]) is not None:
                    reachable_dst_gw = g
                    break
            reachable_dst_gw = reachable_dst_gw or dst_gws[0]
        if dst and reachable_dst_gw:
            dgw_spof = len(dst_gws) <= 1
            if dgw_spof and f"gateway:vlan{dst_vid}:{reachable_dst_gw['host']}" not in spofs:
                spofs.append(f"gateway:vlan{dst_vid}:{reachable_dst_gw['host']}")
            _add("L3", reachable_dst_gw["host"], reachable_dst_gw["host"], f"Vlan{dst_vid}",
                 f"dst gateway SVI {reachable_dst_gw.get('svi_ip','?')} on {reachable_dst_gw['host']}"
                 + ("  [single gateway]" if dgw_spof else ""), spof=dgw_spof)
            _walk(dst_vid, reachable_dst_gw["host"], "", dst[0], "from dst gateway")
        if not src_gws:
            notes.append(f"no scanned gateway found for source {src_ip}")
        if not dst_gws:
            notes.append(f"no scanned gateway found for destination {dst_ip}")

    # ---- destination endpoint ----
    if dst:
        _add("L1/L2", dst[0], dst_ip, dst[1], f"endpoint on access port (VLAN {dst_vid})")
    else:
        notes.append(f"destination {dst_ip} not located on any scanned access port (off-scan)")
        _add("L1/L2", "?", dst_ip, "", "destination endpoint NOT located (off-scan)")

    notes.append("L4 transport filtering not evaluated (no ACL/service-policy collected); "
                 "path reflects L1-L3 reachability only")

    # ---- risk scoring ----
    spofs = list(dict.fromkeys(spofs))      # de-dup, preserve order
    n_spof = len(spofs)
    incomplete = (src is None or dst is None)
    if partitioned:
        risk = "CRITICAL"
    elif incomplete:
        risk = "MEDIUM"     # cannot assert end-to-end resilience on an off-scan path
    elif n_spof == 0:
        risk = "LOW"
    elif n_spof == 1:
        risk = "MEDIUM"
    elif n_spof == 2:
        risk = "HIGH"
    else:
        risk = "CRITICAL"

    summary = {
        "src_ip": src_ip, "dst_ip": dst_ip,
        "flow_type": "L2 (same subnet)" if same_subnet else "L3 (routed)",
        "src_location": (f"{src[0]} {src[1]} (VLAN {src_vid})" if src else "not located"),
        "dst_location": (f"{dst[0]} {dst[1]} (VLAN {dst_vid})" if dst else "not located"),
        "risk": risk, "spof_count": n_spof, "spofs": spofs,
        "incomplete": incomplete, "partitioned": partitioned, "notes": notes,
    }
    return {"summary": summary, "hops": hops}

def write_flow_trace_sheet(wb, flow: dict) -> None:
    """Write the 'Flow Trace' sheet from a trace_full_flow() result."""

    s = flow["summary"]
    ws = wb.create_sheet(FLOW_TRACE_SHEET_NAME)
    bold = Font(bold=True)

    ws.cell(1, 1, f"Flow Trace  {s['src_ip']}  ->  {s['dst_ip']}").font = Font(bold=True, size=13)
    meta = [("Source", s["src_location"]), ("Destination", s["dst_location"]),
            ("Flow type", s["flow_type"]),
            ("SPOFs on path", f"{s['spof_count']}" + (f"  ({', '.join(s['spofs'])})" if s["spofs"] else "")),
            ("Risk level", s["risk"])]
    r = 2
    for label, val in meta:
        ws.cell(r, 1, label).font = bold
        c = ws.cell(r, 2, val)
        if label == "Risk level" and s["risk"] in _RISK_FILL:
            c.fill = PatternFill("solid", fgColor=_RISK_FILL[s["risk"]])
            c.font = bold
        r += 1
    r += 1

    headers = ["#", "Layer", "From", "To", "Interface", "Detail", "SPOF"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(r, col, h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="434343")
        c.alignment = Alignment(horizontal="center")
    r += 1
    for hop in flow["hops"]:
        vals = [hop["n"], hop["layer"], hop["from"], hop["to"], hop["iface"], hop["detail"],
                "YES" if hop["spof"] else ""]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v)
            if hop["spof"]:
                c.fill = PatternFill("solid", fgColor="F4CCCC")
        r += 1

    for i, w in enumerate([5, 8, 16, 16, 16, 60, 7], 1):
        ws.column_dimensions[chr(64 + i)].width = w

    logger.info(f"  [OK] '{FLOW_TRACE_SHEET_NAME}' sheet: {len(flow['hops'])} hop(s), "
                f"risk {s['risk']}, {s['spof_count']} SPOF(s)")


# -----------------------------------------------------------------------------
# NEW-V3.20: L3 Forwarding Map. One row per gateway SVI - VLAN, SVI IP, FHRP
# protocol/role/VIP (parsed from the existing hsrp_behavior string), routing
# source/next-hop/subnets, device object-tracking summary, and a derived L3 Risk
# flag. Pure derivation; 'show track' is the only added collection (tolerant).
# -----------------------------------------------------------------------------
L3_FORWARDING_SHEET_NAME = "L3 Forwarding Map"

def _parse_fhrp(behavior: str):
    """('HSRP grp 1 Active VIP 10.0.10.1') -> (proto, role, vip, group). Blank tuple if none."""
    if not behavior:
        return ("", "", "", "")
    m = re.match(r"(HSRP|VRRP|GLBP)\s+grp\s+(\d+)\s+(\w+)(?:\s+VIP\s+(\S+))?", behavior.strip(), re.IGNORECASE)
    if m:
        return (m.group(1).upper(), m.group(3).capitalize(), m.group(4) or "", m.group(2))
    return ("", "", "", "")

def _parse_track(output: str) -> dict:
    """Best-effort 'show track' (IOS + NX-OS) -> {objects:[{id,desc,state}], up, down}.
    State is Up/Down/'' (unknown). Device-level; not bound to a specific SVI."""
    objs: List[dict] = []
    cur = None
    for line in output.splitlines():
        m = re.match(r"^Track\s+(\d+)\b", line.strip())
        if m:
            cur = {"id": m.group(1), "desc": "", "state": ""}
            objs.append(cur)
            continue
        if cur is None:
            continue
        sm = (re.search(r"\b(?:reachability|line[- ]protocol|list|threshold|state)\s+is\s+(up|down)\b", line, re.IGNORECASE)
              or re.search(r"\bis\s+(up|down)\b", line, re.IGNORECASE))
        if sm and not cur["state"]:
            cur["state"] = sm.group(1).capitalize()
        elif not cur["desc"] and line.strip() and not re.search(r"\b(up|down)\b", line, re.IGNORECASE):
            cur["desc"] = line.strip()[:40]
    down = sum(1 for o in objs if o["state"].lower() == "down")
    up = sum(1 for o in objs if o["state"].lower() == "up")
    return {"objects": objs, "up": up, "down": down}

def _track_summary(tr: dict) -> str:
    if not tr or not tr["objects"]:
        return ""
    head = f"{len(tr['objects'])} obj"
    if tr["down"]:
        head += f" ({tr['down']} DOWN)"
    detail = "; ".join(f"T{o['id']}:{o['state'] or '?'}" for o in tr["objects"][:6])
    return f"{head} - {detail}" if detail else head

def write_l3_forwarding_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]],
                              all_cmd_to_files: Dict[str, Dict[str, str]]) -> List[dict]:
    """Write the 'L3 Forwarding Map' sheet and return its records for the snapshot."""

    # gateways per VLAN across all scanned switches (for the redundancy signal)
    vlan_gw: Dict[int, set] = {}
    for host in all_interfaces:
        for port, d in all_interfaces[host].items():
            m = re.match(r"^Vlan(\d+)$", port, re.IGNORECASE)
            if m and (d.svi_ip or d.hsrp_behavior or d.subnet_primary_route):
                vlan_gw.setdefault(int(m.group(1)), set()).add(host)

    # per-device object tracking (best effort)
    track_by_host: Dict[str, dict] = {}
    for host in all_interfaces:
        out = _load_cmd_output(all_cmd_to_files.get(host, {}), "show track")
        track_by_host[host] = _parse_track(out) if out else {"objects": [], "up": 0, "down": 0}

    headers = ["Switch", "VLAN", "SVI IP", "FHRP", "Role", "Virtual IP", "Routing Source",
               "Next Hop", "Primary Subnet", "Backup / Secondary", "Tracking", "L3 Risk"]

    records: List[dict] = []
    for host in sorted(all_interfaces):
        tr = track_by_host.get(host, {"objects": [], "up": 0, "down": 0})
        tsum = _track_summary(tr)
        for port, d in sorted(all_interfaces[host].items(),
                              key=lambda kv: int(re.match(r"^Vlan(\d+)$", kv[0], re.IGNORECASE).group(1))
                              if re.match(r"^Vlan(\d+)$", kv[0], re.IGNORECASE) else 1 << 30):
            m = re.match(r"^Vlan(\d+)$", port, re.IGNORECASE)
            if not m:
                continue
            if not (d.svi_ip or d.hsrp_behavior or d.subnet_primary_route):
                continue
            vid = int(m.group(1))
            proto, role, vip, _grp = _parse_fhrp(d.hsrp_behavior)
            gw_count = len(vlan_gw.get(vid, set()))

            flags: List[str] = []
            sev = "Info"
            if tr["down"] > 0:
                flags.append("tracked-object-down"); sev = "High"
            if gw_count <= 1:
                flags.append("single-gateway")
                if sev != "High":
                    sev = "Medium"
            elif not proto:
                flags.append("no-FHRP")
                if sev == "Info":
                    sev = "Low"
            if not flags:
                flags = ["ok"]

            records.append({"switch": host, "vlan": vid, "svi_ip": d.svi_ip or "",
                            "fhrp": proto or "none", "role": role or "", "vip": vip or "",
                            "routing_source": d.routing_source or "", "next_hop": d.route_next_hop or "",
                            "primary_subnet": d.subnet_primary_route or "",
                            "secondary": d.subnet_secondary_routes or "",
                            "tracking": tsum, "risk": "; ".join(flags), "severity": sev})

    ws = wb.create_sheet(L3_FORWARDING_SHEET_NAME)
    hdr_font = Font(bold=True, color="FFFFFF")
    hdr_fill = PatternFill("solid", fgColor="434343")
    for col, h in enumerate(headers, 1):
        c = ws.cell(1, col, h)
        c.font = hdr_font
        c.fill = hdr_fill
        c.alignment = Alignment(horizontal="center")
    for r, rec in enumerate(records, 2):
        vals = [rec["switch"], rec["vlan"], rec["svi_ip"], rec["fhrp"], rec["role"], rec["vip"],
                rec["routing_source"], rec["next_hop"], rec["primary_subnet"], rec["secondary"],
                rec["tracking"], rec["risk"]]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v)
            if col == len(headers) and rec["severity"] in _SEV_FILL:
                c.fill = PatternFill("solid", fgColor=_SEV_FILL[rec["severity"]])
    for i, w in enumerate([16, 7, 15, 7, 9, 15, 16, 16, 18, 22, 30, 26], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"

    n_flagged = sum(1 for x in records if x["risk"] != "ok")
    logger.info(f"  [OK] '{L3_FORWARDING_SHEET_NAME}' sheet: {len(records)} gateway SVI(s), "
                f"{n_flagged} flagged")
    return records


# -----------------------------------------------------------------------------
# NEW-V3.21: Cross-layer correlation. Combines the L1 (physical_health) and L3
# (l3_forwarding) records already computed this run with topology facts from the
# model (articulation, single-fiber uplinks, single-member port-channels, orphan
# VLANs) to surface compounded-risk findings CL-01..CL-10 that no single-layer
# view shows. Pure derivation; no new collection.
# -----------------------------------------------------------------------------
CROSS_LAYER_SHEET_NAME = "Cross-Layer Analysis"
_CL_FILL = {"Critical": "FF5775", "High": "F4CCCC", "Medium": "FCE5CD", "Low": "FFF2CC", "Info": "EFEFEF"}
_CL_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}

def build_dependency_map(all_interfaces: Dict[str, Dict[str, InterfaceData]],
                         physical_health: List[dict], l3_forwarding: List[dict]) -> dict:
    """Bundle the cross-layer facts the correlation rules need: L1 from physical_health,
    L3 from l3_forwarding, topology from the shared model."""
    model = build_network_model(all_interfaces)
    uplink_ports, single_fiber = _physical_uplink_index(model)

    # L1 facts (from the physical-health records)
    errored_up, halfdup_up, errdis = set(), set(), set()
    for rec in (physical_health or []):
        key = (rec.get("switch"), rec.get("port"))
        r = rec.get("risk", "")
        if "error-rate-high" in r and key in uplink_ports:
            errored_up.add(key)
        if "half-duplex" in r:
            halfdup_up.add(key)
        if "err-disabled" in r:
            errdis.add(key)

    # L3 facts (from the l3-forwarding records)
    sole_gw, nofhrp_vlans, tracked_down, fhrp_hosts, gw_switches = {}, {}, set(), set(), set()
    fhrp_vlans = set()
    for rec in (l3_forwarding or []):
        vid, host, r = rec.get("vlan"), rec.get("switch"), rec.get("risk", "")
        gw_switches.add(host)
        if "single-gateway" in r:
            sole_gw[vid] = host
        if "no-FHRP" in r:
            nofhrp_vlans.setdefault(vid, []).append(host)
        if "tracked-object-down" in r:
            tracked_down.add(host)
        if (rec.get("fhrp", "none") or "none") != "none":
            fhrp_hosts.add(host)
            fhrp_vlans.add(vid)

    # topology facts (from the model)
    access_by_vlan, orphan = {}, set()
    for vid in model["vlans"]:
        eps = set(model["access_presence"].get(vid, set())) | {h for (h, v) in model["endpoints"] if v == vid}
        access_by_vlan[vid] = eps
        gw_hosts = [g["host"] for g in model["gw"].get(vid, [])]
        ep_count = sum(n for (h, v), n in model["endpoints"].items() if v == vid)
        if ep_count > 0 and not gw_hosts:
            orphan.add(vid)

    articulation = set()                  # (host, vid): removing host strands vid endpoints from gateway
    for vid in model["vlans"]:
        gw_hosts = [g["host"] for g in model["gw"].get(vid, [])]
        if not gw_hosts:
            continue
        for host in model["hosts"]:
            if host in gw_hosts:
                continue
            surviving = [h for h in gw_hosts if h != host]
            if not surviving:
                continue
            ep_hosts = access_by_vlan.get(vid, set()) - {host}
            if not ep_hosts:
                continue
            stranded = set()
            for comp in _vlan_components(model, vid, removed_host=host):
                if not any(g in comp for g in surviving):
                    stranded |= (comp & ep_hosts)
            if stranded:
                articulation.add((host, vid))

    pc_members: Dict[Tuple[str, str], int] = {}
    for host in all_interfaces:
        for port, d in all_interfaces[host].items():
            if _is_physical_port(port) and d.port_channel:
                pc_members[(host, d.port_channel)] = pc_members.get((host, d.port_channel), 0) + 1
    single_member_pc = {k for k, c in pc_members.items() if c == 1}

    return {"model": model, "uplink_ports": uplink_ports, "single_fiber": single_fiber,
            "errored_up": errored_up, "halfdup_up": halfdup_up, "errdis": errdis,
            "sole_gw": sole_gw, "nofhrp_vlans": nofhrp_vlans, "tracked_down": tracked_down,
            "fhrp_hosts": fhrp_hosts, "fhrp_vlans": fhrp_vlans, "gw_switches": gw_switches,
            "access_by_vlan": access_by_vlan, "orphan": orphan,
            "articulation": articulation, "single_member_pc": single_member_pc}

def compute_cross_layer_correlations(dep: dict) -> List[dict]:
    """Apply CL-01..CL-10 to the dependency map. Returns finding dicts sorted by severity."""
    F: List[dict] = []
    sf = dep["single_fiber"]
    up = dep["uplink_ports"]

    def add(cid, sev, layers, title, detail, rec, hosts=None):
        F.append({"id": cid, "severity": sev, "layers": layers, "title": title,
                  "detail": detail, "recommendation": rec, "hosts": sorted(set(hosts or []))})

    # CL-01 (L1+L3): single-fiber uplink fronting a sole-gateway VLAN
    for vid, gw in sorted(dep["sole_gw"].items()):
        access = dep["access_by_vlan"].get(vid, set())
        cset = [(h, p) for (h, p) in sf if h in access]
        culprits = sorted([f"{h} {p}" for (h, p) in cset])
        if culprits:
            add("CL-01", "Critical", "L1+L3",
                f"VLAN {vid}: single-fiber uplink to a sole gateway",
                f"VLAN {vid}'s only L3 gateway is {gw} (no FHRP); {', '.join(culprits)} reach the "
                f"fabric over a single non-redundant fiber.",
                "A single fiber cut isolates the VLAN with no L1 path and no L3 backup - add a "
                "redundant uplink AND an FHRP peer.", [gw] + [h for (h, _p) in cset])

    # CL-02 (L2+L3): transit articulation between endpoints and their gateway
    for (h, vid) in sorted(dep["articulation"]):
        add("CL-02", "High", "L2+L3",
            f"{h}: only L2 transit to the VLAN {vid} gateway",
            f"Removing {h} partitions VLAN {vid} endpoints from their L3 gateway over forwarding links.",
            "Add a redundant path, or migrate this switch in the same wave as its dependents.", [h])

    # CL-03 (L2+L3): sole gateway, no FHRP (structural L3 SPOF)
    for vid, gw in sorted(dep["sole_gw"].items()):
        add("CL-03", "High", "L2+L3",
            f"VLAN {vid}: sole gateway {gw} with no FHRP",
            f"{gw} is the only in-scan L3 gateway for VLAN {vid}; loss drops the default gateway "
            f"for every VLAN {vid} host.",
            "Add an FHRP peer (HSRP/VRRP/GLBP) or confirm a redundant off-scan gateway.", [gw])

    # CL-04 (L3): FHRP gateway with a down tracked object
    for vid in sorted(dep["fhrp_vlans"]):
        down_hosts = sorted(dep["tracked_down"])
        if down_hosts:
            add("CL-04", "High", "L3",
                f"VLAN {vid}: FHRP failover with a down tracked object",
                f"VLAN {vid} runs FHRP, but a tracked object is DOWN on {', '.join(down_hosts)} - "
                f"the object that drives failover/decrement is in a failed state.",
                "Verify the tracked IP-SLA / interface and the standby track/decrement config.", down_hosts)

    # CL-05 (L1+L2): single-fiber uplink that is also errored or half-duplex
    for (h, p) in sorted(sf):
        if (h, p) in dep["errored_up"] or (h, p) in dep["halfdup_up"]:
            why = "high error counters" if (h, p) in dep["errored_up"] else "half-duplex"
            add("CL-05", "High", "L1+L2",
                f"{h} {p}: degraded sole uplink",
                f"{h} {p} is the switch's only forwarding uplink AND is unhealthy ({why}).",
                "The single path is also failing - replace optic/cable and add a second uplink.", [h])

    # CL-06 (L1+L2): single-member port-channel on an uplink
    for (h, po) in sorted(dep["single_member_pc"]):
        if any(uh == h for (uh, _p) in up):
            add("CL-06", "Medium", "L1+L2",
                f"{h} {po}: single-member port-channel",
                f"{po} on {h} bundles only one physical link - the aggregation provides no L1 redundancy.",
                "Add a second member, or do not rely on the port-channel for resilience.", [h])

    # CL-07 (L1+L3): err-disabled / high-error port on a switch that hosts an L3 gateway
    gw_hosts = dep["gw_switches"]
    bad_on_gw = sorted({h for (h, _p) in (dep["errdis"] | dep["errored_up"]) if h in gw_hosts})
    for h in bad_on_gw:
        add("CL-07", "Medium", "L1+L3",
            f"{h}: L1 fault on an L3 gateway switch",
            f"{h} hosts L3 gateway SVIs and has an err-disabled or high-error port - physical "
            f"instability at a routing aggregation point.",
            "Investigate the affected port; instability here affects every VLAN gatewayed by this switch.", [h])

    # CL-08 (L1+L2): half-duplex on an inter-switch trunk/uplink
    for (h, p) in sorted(dep["halfdup_up"]):
        if (h, p) in up:
            add("CL-08", "Medium", "L1+L2",
                f"{h} {p}: half-duplex inter-switch link",
                f"{h} {p} is a trunk/uplink negotiated to half-duplex - collisions and throughput "
                f"collapse on a transit path.",
                "Hard-set speed/duplex on both ends or replace the media.", [h])

    # CL-09 (L1+L2+L3): stacked - one switch implicated across multiple layers
    l1_hosts = {h for (h, _p) in (sf | dep["errored_up"] | dep["halfdup_up"] | dep["errdis"])}
    l2_hosts = {h for (h, _v) in dep["articulation"]}
    l3_hosts = set(dep["sole_gw"].values()) | dep["tracked_down"]
    for h in sorted(set(all_hosts(dep))):
        hits = [lyr for lyr, s in (("L1", l1_hosts), ("L2", l2_hosts), ("L3", l3_hosts)) if h in s]
        if len(hits) >= 2 and ("L3" in hits or "L1" in hits):
            sev = "Critical" if "L3" in hits and "L1" in hits else "High"
            add("CL-09", sev, "+".join(hits),
                f"{h}: stacked single point of failure across {', '.join(hits)}",
                f"{h} is implicated at multiple layers at once ({', '.join(hits)}) - "
                f"its loss compounds physical, switching, and/or routing failure.",
                "Treat as a top migration risk: stage redundancy at every implicated layer before cutover.", [h])

    # CL-10 (L2+L3): orphan VLAN - endpoints present but no in-scan gateway
    for vid in sorted(dep["orphan"]):
        add("CL-10", "Medium", "L2+L3",
            f"VLAN {vid}: endpoints with no in-scan gateway",
            f"VLAN {vid} has active endpoints but no L3 gateway in the scanned set - its default "
            f"gateway is off-scan/undiscovered.",
            f"Confirm where VLAN {vid} is gatewayed; ensure that device is in scope before migration.",
            sorted(dep["access_by_vlan"].get(vid, set())))

    F.sort(key=lambda x: (_CL_RANK.get(x["severity"], 9), x["id"]))
    return F

def all_hosts(dep: dict) -> set:
    return set(dep["model"]["hosts"])

def write_cross_layer_sheet(wb, findings: List[dict]) -> None:
    """Write the 'Cross-Layer Analysis' sheet from compute_cross_layer_correlations()."""

    ws = wb.create_sheet(CROSS_LAYER_SHEET_NAME)
    headers = ["CL", "Severity", "Layers", "Finding", "Detail", "Recommendation"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(1, col, h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="434343")
        c.alignment = Alignment(horizontal="center")
    for r, f in enumerate(findings, 2):
        vals = [f["id"], f["severity"], f["layers"], f["title"], f["detail"], f["recommendation"]]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v)
            if col == 2 and f["severity"] in _CL_FILL:
                c.fill = PatternFill("solid", fgColor=_CL_FILL[f["severity"]])
                c.font = Font(bold=True)
    for i, w in enumerate([7, 9, 8, 42, 60, 52], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    if not findings:
        ws.cell(2, 1, "No cross-layer correlations found (no compounded L1/L2/L3 risks detected).")
    logger.info(f"  [OK] '{CROSS_LAYER_SHEET_NAME}' sheet: {len(findings)} cross-layer finding(s)")


# -----------------------------------------------------------------------------
# NEW-V3.22: Protocol behavior analysis. One row per (switch, protocol) for
# STP / EtherChannel / VTP / OSPF / BGP / EIGRP / FHRP with a derived health
# severity. Re-parses already-collected raw output (+ the new STP-detail TCN).
# -----------------------------------------------------------------------------
PROTOCOL_HEALTH_SHEET_NAME = "Protocol Health"

def _parse_stp_mode(stp_output: str) -> str:
    m = re.search(r"spanning[- ]tree enabled protocol\s+(\S+)", stp_output or "", re.IGNORECASE)
    if not m:
        return ""
    p = m.group(1).lower()
    return {"ieee": "pvst", "rstp": "rapid-pvst", "mstp": "mst", "mst": "mst"}.get(p, p)

def _parse_stp_tcn(detail_output: str):
    """Topology-change counts from 'show spanning-tree detail' -> (max, total) or (None, None)."""
    counts = [int(m.group(1)) for m in
              re.finditer(r"number of topology changes\s+(\d+)", detail_output or "", re.IGNORECASE)]
    if not counts:
        return (None, None)
    return (max(counts), sum(counts))

def _parse_etherchannel_member_states(output: str) -> Dict[str, str]:
    """'show etherchannel/port-channel summary' -> {member_port: flag} (single-letter status:
    P bundled, s suspended, D down, I stand-alone, w waiting, H hot-standby, R L3)."""
    res: Dict[str, str] = {}
    for line in (output or "").splitlines():
        for m in re.finditer(r"\b([A-Za-z]{2,}[\d/]+)\(([A-Za-z]+)\)", line):
            nm = normalize_ifname(m.group(1))
            if not nm.startswith("Po"):
                res[nm] = m.group(2)[0]
    return res

def _parse_vtp_full(output: str) -> dict:
    mode = domain = ""
    rev = 0
    for raw in (output or "").splitlines():
        s = raw.strip()
        m = re.search(r"VTP Operating Mode\s*:?\s*(\w+)", s, re.IGNORECASE)
        if m:
            mode = m.group(1)
        m = re.search(r"(?:VTP Domain Name|Domain Name)\s*:?\s*(\S+)", s, re.IGNORECASE)
        if m and m.group(1).lower() not in ("not", "none", "null"):
            domain = m.group(1)
        m = re.search(r"Configuration Revision\s*:?\s*(\d+)", s, re.IGNORECASE)
        if m:
            rev = int(m.group(1))
    return {"mode": mode, "domain": domain, "revision": rev}

def compute_protocol_health(all_interfaces: Dict[str, Dict[str, InterfaceData]],
                            all_cmd_to_files: Dict[str, Dict[str, str]]) -> List[dict]:
    """Per-(switch, protocol) health rows. Severity: High (down/inconsistent), Medium
    (waiting / soft), Info (healthy / present). Returns records for sheet + snapshot."""
    records: List[dict] = []

    def add(host, proto, sev, summary, detail=""):
        records.append({"switch": host, "protocol": proto, "severity": sev,
                        "summary": summary, "detail": detail})

    for host in sorted(all_interfaces):
        c2f = all_cmd_to_files.get(host, {})

        # ---- STP ----
        stp_out = _load_cmd_output(c2f, "show spanning-tree")
        if stp_out:
            blocked = parse_spanning_tree_blockedports(_load_cmd_output(c2f, "show spanning-tree blockedports"))
            incons = parse_spanning_tree_blockedports(_load_cmd_output(c2f, "show spanning-tree inconsistentports"))
            mode = _parse_stp_mode(stp_out)
            maxt, _tot = _parse_stp_tcn(_load_cmd_output(c2f, "show spanning-tree detail"))
            nblk, ninc = len(blocked), len(incons)
            sev = "High" if ninc else "Info"
            summary = f"mode {mode or '?'}; {nblk} blocked, {ninc} inconsistent"
            if maxt is not None:
                summary += f"; max TCN {maxt}"
            detail = ("inconsistent: " + ", ".join(sorted(incons))) if ninc else ""
            add(host, "STP", sev, summary, detail)

        # ---- EtherChannel ----
        ec_out = _load_cmd_output(c2f, "show etherchannel summary", "show port-channel summary")
        if ec_out:
            states = _parse_etherchannel_member_states(ec_out)
            if states:
                bad = {m: f for m, f in states.items() if f in ("s", "D", "I", "w")}
                npo = len({po for po in parse_etherchannel_summary_members(ec_out).values()})
                hard = any(f in ("s", "D", "I") for f in bad.values())
                sev = "High" if hard else ("Medium" if bad else "Info")
                summary = f"{npo} bundle(s), {len(states)} member(s)" + (f"; {len(bad)} not bundled" if bad else "")
                detail = ("; ".join(f"{m}({f})" for m, f in sorted(bad.items()))) if bad else ""
                add(host, "EtherChannel", sev, summary, detail)

        # ---- VTP ----
        vtp_out = _load_cmd_output(c2f, "show vtp status")
        if vtp_out:
            v = _parse_vtp_full(vtp_out)
            if v["mode"] or v["domain"]:
                add(host, "VTP", "Info",
                    f"mode {v['mode'] or '?'}; domain {v['domain'] or '-'}; rev {v['revision']}",
                    "high revision can overwrite the VLAN DB" if v["revision"] >= 100 else "")

        # ---- OSPF ----
        ospf = parse_ospf_neighbors(_load_cmd_output(c2f, "show ip ospf neighbor"))
        if ospf:
            bad = [n for n in ospf if not (n["state"].upper().startswith("FULL")
                                           or n["state"].upper().startswith("2WAY"))]
            sev = "High" if bad else "Info"
            add(host, "OSPF", sev, f"{len(ospf)} neighbor(s); {len(bad)} not Full/2Way",
                ("; ".join(f"{n['neighbor']} {n['state']}" for n in bad)) if bad else "")

        # ---- BGP ----
        bgp = parse_bgp_summary(_load_cmd_output(c2f, "show ip bgp summary", "show bgp summary"))
        if bgp:
            bad = [p for p in bgp if not re.match(r"^\d+$", p["state"])]
            sev = "High" if bad else "Info"
            add(host, "BGP", sev, f"{len(bgp)} peer(s); {len(bad)} not Established",
                ("; ".join(f"{p['neighbor']} {p['state']}" for p in bad)) if bad else "")

        # ---- EIGRP ----
        eigrp = parse_eigrp_neighbors(_load_cmd_output(c2f, "show ip eigrp neighbors"))
        if eigrp:
            add(host, "EIGRP", "Info", f"{len(eigrp)} neighbor(s) up")

        # ---- FHRP ----
        groups = []
        for port, d in all_interfaces[host].items():
            if re.match(r"^Vlan\d+$", port, re.IGNORECASE) and d.hsrp_behavior:
                proto, role, _vip, grp = _parse_fhrp(d.hsrp_behavior)
                if proto:
                    groups.append((proto, role, grp, port))
        if groups:
            protos = sorted({g[0] for g in groups})
            actives = sum(1 for g in groups if g[1].lower() in ("active", "master"))
            add(host, "FHRP", "Info",
                f"{len(groups)} group(s) [{', '.join(protos)}]; {actives} active/master")

    return records

def write_protocol_health_sheet(wb, records: List[dict]) -> None:
    """Write the 'Protocol Health' sheet from compute_protocol_health()."""

    ws = wb.create_sheet(PROTOCOL_HEALTH_SHEET_NAME)
    headers = ["Switch", "Protocol", "Summary", "Detail", "Health"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(1, col, h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="434343")
        c.alignment = Alignment(horizontal="center")
    word = {"High": "DEGRADED", "Medium": "WARNING", "Low": "MINOR", "Info": "OK"}
    for r, rec in enumerate(records, 2):
        vals = [rec["switch"], rec["protocol"], rec["summary"], rec["detail"],
                word.get(rec["severity"], rec["severity"])]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v)
            if col == 5 and rec["severity"] in _SEV_FILL:
                c.fill = PatternFill("solid", fgColor=_SEV_FILL[rec["severity"]])
                c.font = Font(bold=True)
    for i, w in enumerate([16, 13, 46, 50, 11], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    n_bad = sum(1 for x in records if x["severity"] in ("High", "Medium"))
    logger.info(f"  [OK] '{PROTOCOL_HEALTH_SHEET_NAME}' sheet: {len(records)} row(s), {n_bad} flagged")


# -----------------------------------------------------------------------------
# NEW-V3.23: Health scoring + migration readiness (final intelligence layer).
# Per-switch 0-100 score (weighted deductions from L1/L3/cross-layer/protocol
# findings) and per-move-group READY/CAUTION/NOT READY from a 10-check checklist.
# Pure derivation over the records already computed this run; no new collection.
# -----------------------------------------------------------------------------
HEALTH_SCORES_SHEET_NAME = "Health Scores"
MIGRATION_READINESS_SHEET_NAME = "Migration Readiness"
# score band -> (label, fill)
_HEALTH_BANDS = [(90, "Excellent", "36E08A"), (75, "Good", "7ADB8F"),
                 (60, "Fair", "FFE566"), (40, "Poor", "FF9F45"), (0, "Critical", "FF5775")]
_READY_FILL = {"READY": "36E08A", "CAUTION": "FFE566", "NOT READY": "FF5775"}
_STATUS_FILL = {"pass": "36E08A", "warn": "FFE566", "fail": "FF5775"}

def _health_band(score: int):
    for thr, label, fill in _HEALTH_BANDS:
        if score >= thr:
            return label, fill
    return "Critical", "FF5775"

def compute_health_scores(all_interfaces: Dict[str, Dict[str, InterfaceData]],
                          physical_health: List[dict], l3_forwarding: List[dict],
                          cross_layer: List[dict], protocol_health: List[dict]) -> List[dict]:
    """Per-switch 0-100 health score with weighted, category-capped deductions."""
    hosts = sorted(all_interfaces)
    ded: Dict[str, Dict[str, List[Tuple[str, int]]]] = {
        h: {"L1": [], "L3": [], "XL": [], "PROTO": []} for h in hosts}

    L1W = {"err-disabled": 8, "single-fiber-uplink": 10, "error-rate-high": 5, "half-duplex": 8}
    for rec in (physical_health or []):
        h = rec.get("switch")
        if h not in ded:
            continue
        for flag, pts in L1W.items():
            if flag in rec.get("risk", ""):
                ded[h]["L1"].append((f"{flag} @ {rec.get('port','')}", pts))
    L3W = {"single-gateway": 10, "no-FHRP": 3, "tracked-object-down": 12}
    for rec in (l3_forwarding or []):
        h = rec.get("switch")
        if h not in ded:
            continue
        for flag, pts in L3W.items():
            if flag in rec.get("risk", ""):
                ded[h]["L3"].append((f"{flag} (VLAN {rec.get('vlan','')})", pts))
    XLW = {"Critical": 18, "High": 10, "Medium": 4, "Low": 2}
    for f in (cross_layer or []):
        pts = XLW.get(f.get("severity"), 0)
        for h in f.get("hosts", []):
            if h in ded:
                ded[h]["XL"].append((f"{f['id']} {f['severity']}", pts))
    PW = {"High": 10, "Medium": 4}
    for rec in (protocol_health or []):
        h = rec.get("switch")
        if h in ded and rec.get("severity") in PW:
            ded[h]["PROTO"].append((f"{rec['protocol']} {rec['severity']}", PW[rec["severity"]]))

    CAP = {"L1": 30, "L3": 30, "XL": 45, "PROTO": 25}
    records: List[dict] = []
    for h in hosts:
        total = 0
        reasons: List[str] = []
        for cat, items in ded[h].items():
            csum = min(sum(p for _r, p in items), CAP[cat])
            total += csum
            for r, p in sorted(items, key=lambda x: -x[1]):
                reasons.append(f"{r} (-{p})")
        score = max(0, 100 - total)
        band, _fill = _health_band(score)
        records.append({"switch": h, "score": score, "band": band,
                        "deductions": reasons[:8]})
    records.sort(key=lambda r: (r["score"], r["switch"]))
    return records

# 10 pre-migration checks; each returns (status, note). status in pass/warn/fail.
def compute_migration_readiness(all_interfaces, move_groups, health_scores,
                                physical_health, l3_forwarding, cross_layer,
                                protocol_health, dep_map) -> List[dict]:
    """Per move-group READY/CAUTION/NOT READY from a 10-check pre-migration checklist."""
    # per-host indexes
    sf_hosts = {h for (h, _p) in dep_map["single_fiber"]}
    errdis_hosts = {h for (h, _p) in dep_map["errdis"]}
    halfdup_hosts = {h for (h, _p) in dep_map["halfdup_up"]}
    sole_gw_hosts = set(dep_map["sole_gw"].values())
    band_by_host = {r["switch"]: r["band"] for r in health_scores}
    proto_high = {}                                  # host -> set(protocols at High)
    for rec in (protocol_health or []):
        if rec.get("severity") == "High":
            proto_high.setdefault(rec["switch"], set()).add(rec["protocol"])
    xl_crit_hosts = {h for f in (cross_layer or []) if f.get("severity") == "Critical" for h in f.get("hosts", [])}
    # orphan VLAN -> its access switches
    orphan_hosts = set()
    for vid in dep_map["orphan"]:
        orphan_hosts |= dep_map["access_by_vlan"].get(vid, set())

    out: List[dict] = []
    for gi, g in enumerate(move_groups, 1):
        gset = set(g["switches"])

        def any_in(s):
            return sorted(gset & s)

        checks = []
        # 1 redundant uplinks
        hit = any_in(sf_hosts)
        checks.append(("Redundant uplinks", "warn" if hit else "pass",
                       f"single-fiber uplink on {', '.join(hit)}" if hit else "no single-homed switch"))
        # 2 gateway redundancy (FHRP)
        hit = any_in(sole_gw_hosts)
        checks.append(("Gateway redundancy", "fail" if hit else "pass",
                       f"sole gateway on {', '.join(hit)} (no FHRP)" if hit else "gateways redundant / none in group"))
        # 3 no cross-layer Critical
        hit = any_in(xl_crit_hosts)
        checks.append(("No cross-layer Critical", "fail" if hit else "pass",
                       f"Critical correlation on {', '.join(hit)}" if hit else "none"))
        # 4 no err-disabled ports
        hit = any_in(errdis_hosts)
        checks.append(("No err-disabled ports", "warn" if hit else "pass",
                       f"err-disabled on {', '.join(hit)}" if hit else "none"))
        # 5 STP consistency
        hit = sorted({h for h in gset if "STP" in proto_high.get(h, set())})
        checks.append(("STP consistency", "warn" if hit else "pass",
                       f"inconsistent STP on {', '.join(hit)}" if hit else "no inconsistent ports"))
        # 6 port-channels healthy
        hit = sorted({h for h in gset if "EtherChannel" in proto_high.get(h, set())})
        checks.append(("Port-channels healthy", "warn" if hit else "pass",
                       f"unbundled member on {', '.join(hit)}" if hit else "all members bundled / none"))
        # 7 routing adjacencies up
        hit = sorted({h for h in gset if proto_high.get(h, set()) & {"OSPF", "BGP"}})
        checks.append(("Routing adjacencies up", "fail" if hit else "pass",
                       f"down OSPF/BGP neighbor on {', '.join(hit)}" if hit else "all neighbors up / none"))
        # 8 no orphan VLANs
        hit = any_in(orphan_hosts)
        checks.append(("No orphan VLANs", "warn" if hit else "pass",
                       f"endpoints with off-scan gateway on {', '.join(hit)}" if hit else "none"))
        # 9 no degraded / half-duplex uplinks
        hit = any_in(halfdup_hosts)
        checks.append(("Clean uplinks (no half-duplex)", "warn" if hit else "pass",
                       f"half-duplex uplink on {', '.join(hit)}" if hit else "none"))
        # 10 device health floor
        crit = sorted([h for h in gset if band_by_host.get(h) == "Critical"])
        poor = sorted([h for h in gset if band_by_host.get(h) == "Poor"])
        if crit:
            st, note = "fail", f"Critical-health switch: {', '.join(crit)}"
        elif poor:
            st, note = "warn", f"Poor-health switch: {', '.join(poor)}"
        else:
            st, note = "pass", "all switches Fair or better"
        checks.append(("Device health floor", st, note))

        statuses = [c[1] for c in checks]
        readiness = "NOT READY" if "fail" in statuses else ("CAUTION" if "warn" in statuses else "READY")
        out.append({"group": f"Group {gi}", "switches": g["switches"],
                    "endpoints": g.get("endpoints", 0), "readiness": readiness,
                    "n_fail": statuses.count("fail"), "n_warn": statuses.count("warn"),
                    "checks": [{"check": c[0], "status": c[1], "note": c[2]} for c in checks]})
    return out

def write_health_scores_sheet(wb, records: List[dict]) -> None:
    ws = wb.create_sheet(HEALTH_SCORES_SHEET_NAME)
    headers = ["Switch", "Score", "Band", "Top Deductions"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(1, col, h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="434343")
        c.alignment = Alignment(horizontal="center")
    for r, rec in enumerate(records, 2):
        _lbl, fill = _health_band(rec["score"])
        ws.cell(r, 1, rec["switch"])
        c = ws.cell(r, 2, rec["score"]); c.fill = PatternFill("solid", fgColor=fill); c.font = Font(bold=True)
        c2 = ws.cell(r, 3, rec["band"]); c2.fill = PatternFill("solid", fgColor=fill)
        ws.cell(r, 4, "; ".join(rec["deductions"]) if rec["deductions"] else "healthy")
    for i, w in enumerate([16, 8, 11, 80], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    avg = round(sum(r["score"] for r in records) / len(records)) if records else 0
    logger.info(f"  [OK] '{HEALTH_SCORES_SHEET_NAME}' sheet: {len(records)} switch(es), avg score {avg}")

def write_migration_readiness_sheet(wb, readiness: List[dict]) -> None:
    ws = wb.create_sheet(MIGRATION_READINESS_SHEET_NAME)
    headers = ["Group / Check", "Status", "Detail"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(1, col, h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="434343")
        c.alignment = Alignment(horizontal="center")
    r = 2
    for g in readiness:
        c = ws.cell(r, 1, f"{g['group']}  ({len(g['switches'])} switch(es), {g['endpoints']} endpoint(s))")
        c.font = Font(bold=True)
        cs = ws.cell(r, 2, g["readiness"])
        cs.font = Font(bold=True)
        if g["readiness"] in _READY_FILL:
            cs.fill = PatternFill("solid", fgColor=_READY_FILL[g["readiness"]])
        ws.cell(r, 3, ", ".join(g["switches"]))
        r += 1
        for chk in g["checks"]:
            ws.cell(r, 1, "    " + chk["check"])
            sc = ws.cell(r, 2, chk["status"].upper())
            if chk["status"] in _STATUS_FILL:
                sc.fill = PatternFill("solid", fgColor=_STATUS_FILL[chk["status"]])
            ws.cell(r, 3, chk["note"])
            r += 1
        r += 1   # blank row between groups
    for i, w in enumerate([40, 9, 70], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    nready = sum(1 for g in readiness if g["readiness"] == "READY")
    logger.info(f"  [OK] '{MIGRATION_READINESS_SHEET_NAME}' sheet: {len(readiness)} group(s), {nready} READY")


# =============================================================================
# MAIN
# =============================================================================
def main():
    ap = argparse.ArgumentParser(description="Cisco Migration Extractor V3.23.0")
    ap.add_argument("--devices-file",   default=None,
                    help="Devices JSON (required unless --compare is used)")
    ap.add_argument("--template",        default=DEFAULT_TEMPLATE_FILE)
    ap.add_argument("--output",          default="")
    ap.add_argument("--no-collect",      action="store_true")
    ap.add_argument("--collection-dir",  default="")
    ap.add_argument("--debug-headers",   action="store_true")
    ap.add_argument("--workers",         type=int, default=5,
                    help="Parallel SSH workers (default 5; use 1 for sequential)")
    ap.add_argument("--debug-arp",       action="store_true",
                    help="Enable DEBUG logging for per-device ARP counts")
    ap.add_argument("--compare",         nargs=2, default=None,
                    metavar=("OLD_SNAPSHOT", "NEW_SNAPSHOT"),
                    help="NEW-V15: compare two snapshot JSONs and write a diff workbook; "
                         "skips collection and the template.")
    ap.add_argument("--no-html",         action="store_true",
                    help="NEW-V3.17: skip Blast-Radius Explorer (HTML) generation "
                         "(default: HTML is always written beside the workbook).")
    ap.add_argument("--flow-src",        default=None, metavar="IP",
                    help="NEW-V3.19: source endpoint IP for the optional Flow Trace sheet "
                         "(requires --flow-dst).")
    ap.add_argument("--flow-dst",        default=None, metavar="IP",
                    help="NEW-V3.19: destination endpoint IP for the optional Flow Trace sheet "
                         "(requires --flow-src).")
    args = ap.parse_args()

    if args.debug_arp:
        logger.setLevel(logging.DEBUG)
        for h in logger.handlers: h.setLevel(logging.DEBUG)

    # NEW-V15: diff mode - compare two snapshots, no SSH/template needed.
    if args.compare:
        old_p, new_p = args.compare
        try:                                              # NEW-V3.23.1: clean message, not a raw traceback
            with open(old_p, encoding="utf-8") as f: old_snap = json.load(f)
            with open(new_p, encoding="utf-8") as f: new_snap = json.load(f)
        except FileNotFoundError as e:
            ap.error(f"--compare: snapshot file not found: {e.filename}")
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            ap.error(f"--compare: could not parse snapshot JSON ({e})")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        diff_out = args.output or f"Migration_Diff_{stamp}.xlsx"
        write_diff_workbook(old_snap, new_snap, diff_out)
        logger.info(f"[OK] Saved diff workbook: {os.path.abspath(diff_out)}")
        return

    if not args.devices_file:
        ap.error("--devices-file is required (unless using --compare OLD NEW)")

    if not os.path.exists(args.template):
        raise FileNotFoundError(f"Template not found: {args.template}")

    devices = load_devices(args.devices_file)
    stamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_xlsx = args.output or DEFAULT_OUTPUT_FILE.format(stamp)

    wb = load_workbook(args.template)
    ws = wb.active
    logger.info(f"[OK] Loaded template: {args.template}")

    if args.debug_headers:
        debug_scan_headers(ws, max_rows=150, max_cols=90)
        print("Exiting because --debug-headers was used.")
        return

    header_row, col_map = find_header_row(ws)
    logger.info(f"[OK] Header row at row {header_row}")
    col_map = ensure_headers(ws, header_row, col_map, {
        "TRUNK Native VLAN":    "trunk_native_vlan",
        "TRUNK Allowed VLANs":  "trunk_allowed_vlans",
        "TRUNK Status":         "trunk_status",
        "ARP Source Switch":    "arp_source_switch",  # NEW-V11
        "CDP/LLDP Neighbor":    "cdp_neighbor",       # NEW-V11
        # NEW-V14.2 (header text normalizes to the HEADER_TO_FIELD keys above)
        "Current Switch Serial":      "current_switch_serial",
        "Current Switch Mgmt IP":     "current_switch_ip",
        "Current Switch VTP Domain":  "current_switch_vtp_domain",
        "Neighbor Switch Serial":     "neighbor_switch_serial",
        "Neighbor Switch Mgmt IP":    "neighbor_switch_ip",
        "Neighbor Switch VTP Domain": "neighbor_switch_vtp_domain",
        "Subnet Primary Route":       "subnet_primary_route",
        "Subnet Secondary Routes":    "subnet_secondary_routes",
        "Route Next Hop":             "route_next_hop",
        "Routing Source":             "routing_source",
        "FHRP Behavior":              "hsrp_behavior",
        "Multicast Info":             "multicast_info",
    })

    root_dir = args.collection_dir or COLLECTION_DIR.format(stamp)
    os.makedirs(root_dir, exist_ok=True)
    logger.info(f"[OK] Collection directory: {root_dir}")

    _progress_lock = threading.Lock()
    _done_count    = [0]

    def collect_one(devinfo):
        ip       = devinfo["ip"]
        hostname = devinfo["hostname"]
        username = devinfo["username"]
        password = devinfo["password"]
        platform = devinfo["platform"]
        safe_host = safe_fs_name(hostname)
        dev_dir   = os.path.join(root_dir, safe_host)
        cmd_to_file: Dict[str,str] = {}

        if args.no_collect:
            if platform in ("auto",""):
                platform = detect_platform_from_files(dev_dir)
                logger.info(f"  [{hostname}] Auto-detected platform: {platform}")
            all_cmds = list(dict.fromkeys(COMMANDS_NXOS + COMMANDS_IOS))
            for cmd in all_cmds:
                fn    = cmd.replace(" ","_").replace("|","_").replace("^","").replace("/","_")+".txt"
                fpath = os.path.join(dev_dir, fn)
                if os.path.isfile(fpath): cmd_to_file[cmd] = fpath
        else:
            logger.info(f"  Connecting to {hostname} ({ip}) ...")
            dev, platform = connect_device(ip, hostname, username, password, platform)
            if not dev:
                logger.error(f"  [FAIL] Skipped {hostname}")
                with _progress_lock:
                    _done_count[0] += 1
                    logger.info(f"  Progress: {_done_count[0]}/{len(devices)} devices done")
                return hostname, platform, None
            try:
                cmd_to_file = collect(hostname, platform, dev, dev_dir)
            finally:
                try: dev.disconnect()
                except Exception: pass

        # V14.12: correct the platform from the actually-collected output. Union collection
        # means both command forms are present; whichever returned real (non-error) output
        # reveals the true OS. Fixes a wrong 'platform' in devices.json (e.g. nxos on an IOS
        # Catalyst) so parsing and the Switch Inventory label are right.
        if cmd_to_file:
            detected = detect_platform_from_files(dev_dir)
            if detected != platform:
                logger.info(f"  [{hostname}] Platform corrected '{platform}' -> '{detected}' from collected output")
                platform = detected

        with _progress_lock:
            _done_count[0] += 1
            logger.info(f"  [{_done_count[0]}/{len(devices)}] Finished collecting {hostname}")
        return hostname, platform, cmd_to_file

    # Phase 1: Collect
    workers = max(1, min(args.workers, len(devices)))
    logger.info(f"\n[Phase 1] Collecting {len(devices)} device(s) with {workers} parallel worker(s) ...")
    all_cmd_to_files: Dict[str, Dict[str,str]] = {}
    all_devices_meta = []

    if workers == 1:
        results = [collect_one(d) for d in devices]
    else:
        results = []
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="collector") as pool:
            futures = {pool.submit(collect_one, d): d["hostname"] for d in devices}
            for fut in as_completed(futures):
                try:
                    results.append(fut.result())
                except Exception as e:
                    logger.error(f"  [FAIL] Worker exception for {futures[fut]}: {e}")

    for hostname, platform, cmd_to_file in results:
        if cmd_to_file is None: continue
        all_cmd_to_files[hostname] = cmd_to_file
        all_devices_meta.append((hostname, platform, cmd_to_file))

    logger.info(f"  Collection complete: {len(all_devices_meta)}/{len(devices)} succeeded.")

    # Phase 2: Global ARP
    logger.info("\n[Phase 2] Building global ARP table ...")
    global_arp, global_arp_source = collect_global_arp(all_cmd_to_files)  # NEW-V11 tuple

    # Phase 3: Parallel Parse
    logger.info(f"\n[Phase 3] Parsing {len(all_devices_meta)} device(s) ...")
    all_interfaces: Dict[str, Dict[str, InterfaceData]] = {}

    def parse_one(args_tuple):
        hostname, platform, cmd_to_file = args_tuple
        switch_identity = build_switch_identity(hostname, platform, cmd_to_file)
        ifaces = build_interfaces(hostname, platform, cmd_to_file, switch_identity=switch_identity)
        logger.info(f"  Parsed {hostname}: {len(ifaces)} interfaces")
        return hostname, ifaces

    if workers == 1:
        parse_results = [parse_one(t) for t in all_devices_meta]
    else:
        parse_results = []
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="parser") as pool:
            futures = {pool.submit(parse_one, t): t[0] for t in all_devices_meta}
            for fut in as_completed(futures):
                try:
                    parse_results.append(fut.result())
                except Exception as e:
                    logger.error(f"  [FAIL] Parse exception for {futures[fut]}: {e}")

    for hostname, ifaces in parse_results:
        all_interfaces[hostname] = ifaces

    # Phase 4: Cross-device dual-connection detection
    logger.info("\n[Phase 4] Cross-device dual-connection detection ...")
    detect_cross_device_dual_connections(all_interfaces)

    # Phase 5: Apply global ARP -> IP + arp_source_switch
    logger.info("\n[Phase 5] Applying global ARP -> IP addresses ...")
    apply_global_arp(all_interfaces, global_arp, global_arp_source)  # NEW-V11

    # Phase 5.5: Build device physical inventory (NEW-V12)
    logger.info("\n[Phase 5.5] Building device physical inventory ...")
    all_device_physical: List[DevicePhysical] = []
    for hostname, platform, cmd_to_file in all_devices_meta:
        dp = build_device_physical(hostname, platform, cmd_to_file,
                                   all_interfaces.get(hostname, {}))
        all_device_physical.append(dp)
        logger.info(f"  [OK] Physical: {hostname}  model={dp.model}  "
                    f"PSU={dp.num_power_supplies}  "
                    f"cap={dp.power_capacity_w}  draw={dp.power_drawn_w}")

    # Phase 6: Write interface rows to template sheet
    logger.info("\n[Phase 6] Writing interface rows ...")
    for hostname, platform, cmd_to_file in all_devices_meta:
        iface_rows = all_interfaces.get(hostname, {})
        if not iface_rows:
            logger.warning(f"  [SKIP] No parsed interfaces for {hostname}")
            continue
        append_interface_rows(ws, header_row, col_map, hostname, iface_rows)
        logger.info(f"  [OK] {len(iface_rows)} rows for {hostname}")

    # Phase 7: Write Switch Inventory sheet (NEW-V12)
    logger.info("\n[Phase 7] Writing Switch Inventory sheet ...")
    write_device_inventory_sheet(wb, all_device_physical)

    # Phase 8: Write SVI / Gateway sheet (NEW-V14.3)
    logger.info("\n[Phase 8] Writing SVI / Gateway sheet ...")
    write_svi_gateway_sheet(wb, all_interfaces)

    # Phase 9: Write STP Detail sheet (NEW-V14.7)
    logger.info("\n[Phase 9] Writing STP Detail sheet ...")
    write_stp_detail_sheet(wb, all_interfaces)

    # Phase 10: Write VLAN Census sheet (NEW-V14.8)
    logger.info("\n[Phase 10] Writing VLAN Census sheet ...")
    write_vlan_census_sheet(wb, all_interfaces)

    # Phase 11: Write Endpoint Census sheet (NEW-V14.8)
    logger.info("\n[Phase 11] Writing Endpoint Census sheet ...")
    write_endpoint_census_sheet(wb, all_interfaces)

    # Phase 12: Write Move Groups sheet (NEW-V14.9)
    logger.info("\n[Phase 12] Writing Move Groups sheet ...")
    write_move_group_sheet(wb, all_interfaces)

    # Phase 13: Write Topology Links sheet (NEW-V14.10)
    logger.info("\n[Phase 13] Writing Topology Links sheet ...")
    write_topology_sheet(wb, all_interfaces)

    # Phase 14: Findings / Risk Register (NEW-V15)
    logger.info("\n[Phase 14] Writing Findings sheet ...")
    write_findings_sheet(wb, all_interfaces)

    # Phase 15: Capacity / Consolidation (NEW-V15)
    logger.info("\n[Phase 15] Writing Capacity sheet ...")
    write_capacity_sheet(wb, all_device_physical)

    # Phase 16: Interface Health counters (NEW-V15)
    logger.info("\n[Phase 16] Writing Interface Health sheet ...")
    write_interface_health_sheet(wb, all_cmd_to_files)

    # Phase 17: Security Posture (NEW-V15)
    logger.info("\n[Phase 17] Writing Security Posture sheet ...")
    write_security_posture_sheet(wb, all_cmd_to_files)

    # Phase 18: Routing Adjacencies (NEW-V15)
    logger.info("\n[Phase 18] Writing Routing Adjacencies sheet ...")
    write_routing_adjacency_sheet(wb, all_cmd_to_files)

    # Phase 19: Causality Chains (NEW-V3.16 intelligence layer)
    logger.info("\n[Phase 19] Writing Causality Chains sheet ...")
    write_causality_chains_sheet(wb, all_interfaces)

    # Phase 20: Failure Impact simulation (NEW-V3.16 intelligence layer)
    logger.info("\n[Phase 20] Writing Failure Impact sheet ...")
    write_failure_impact_sheet(wb, all_interfaces)

    # Phase 23: Physical Health (L1) - NEW-V3.18. Sheet writers must precede wb.save(); the
    # phase number is a logical label (21/22 are post-save: snapshot/diagram + HTML). The
    # returned records are injected into snap_dict below so they reach both JSON and HTML.
    logger.info("\n[Phase 23] Writing Physical Health sheet ...")
    physical_health = write_physical_health_sheet(wb, all_interfaces, all_cmd_to_files, all_device_physical)

    # Phase 24: Flow Trace (L1->L3) - NEW-V3.19. Optional; only when BOTH endpoint IPs given.
    flow_trace = None
    if args.flow_src and args.flow_dst:
        logger.info(f"\n[Phase 24] Tracing flow {args.flow_src} -> {args.flow_dst} ...")
        try:
            flow_trace = trace_full_flow(args.flow_src, args.flow_dst, all_interfaces)
            write_flow_trace_sheet(wb, flow_trace)
        except Exception as e:
            logger.warning(f"  [WARN] Flow Trace failed: {e}")
            flow_trace = None
    elif args.flow_src or args.flow_dst:
        logger.warning("  [WARN] --flow-src and --flow-dst must be given together; skipping Flow Trace.")

    # Phase 25: L3 Forwarding Map - NEW-V3.20 (pre-save; records reused in snapshot)
    logger.info("\n[Phase 25] Writing L3 Forwarding Map sheet ...")
    l3_forwarding = write_l3_forwarding_sheet(wb, all_interfaces, all_cmd_to_files)

    # Phase 26: Cross-Layer Analysis - NEW-V3.21 (consumes physical_health + l3_forwarding)
    logger.info("\n[Phase 26] Writing Cross-Layer Analysis sheet ...")
    dep_map = build_dependency_map(all_interfaces, physical_health, l3_forwarding)
    cross_layer = compute_cross_layer_correlations(dep_map)
    write_cross_layer_sheet(wb, cross_layer)

    # Phase 27: Protocol Health - NEW-V3.22 (re-parses collected protocol output)
    logger.info("\n[Phase 27] Writing Protocol Health sheet ...")
    protocol_health = compute_protocol_health(all_interfaces, all_cmd_to_files)
    write_protocol_health_sheet(wb, protocol_health)

    # Phase 28: Health Scores - NEW-V3.23 (synthesises L1/L3/cross-layer/protocol findings)
    logger.info("\n[Phase 28] Writing Health Scores sheet ...")
    health_scores = compute_health_scores(all_interfaces, physical_health, l3_forwarding,
                                          cross_layer, protocol_health)
    write_health_scores_sheet(wb, health_scores)

    # Phase 29: Migration Readiness - NEW-V3.23 (per move-group 10-check verdict)
    logger.info("\n[Phase 29] Writing Migration Readiness sheet ...")
    move_groups = compute_move_groups(all_interfaces)
    migration_readiness = compute_migration_readiness(all_interfaces, move_groups, health_scores,
                                                      physical_health, l3_forwarding, cross_layer,
                                                      protocol_health, dep_map)
    write_migration_readiness_sheet(wb, migration_readiness)

    wb.save(out_xlsx)
    logger.info(f"\n[OK] Saved: {out_xlsx}")
    logger.info(f"[OK] Log:   {LOG_FILE}")

    # Phase 21: Topology diagram files + state snapshot (NEW-V15). abspath() guarantees a
    # directory component so the diagram dir and snapshot path are always well-formed.
    diagram_dir = os.path.dirname(os.path.abspath(out_xlsx)) or "."
    try:
        write_topology_diagram(all_interfaces, diagram_dir)
    except Exception as e:
        logger.warning(f"  Topology diagram write failed: {e}")
    snap_path = os.path.splitext(os.path.abspath(out_xlsx))[0] + ".snapshot.json"
    snap_dict = snapshot_state(all_interfaces, all_device_physical)  # CHANGED-V3.17: capture for reuse (JSON + HTML)
    snap_dict["physical_health"] = physical_health                   # NEW-V3.18
    snap_dict["l3_forwarding"] = l3_forwarding                       # NEW-V3.20
    snap_dict["cross_layer"] = cross_layer                           # NEW-V3.21
    snap_dict["protocol_health"] = protocol_health                   # NEW-V3.22
    snap_dict["health_scores"] = health_scores                       # NEW-V3.23
    snap_dict["migration_readiness"] = migration_readiness           # NEW-V3.23
    if flow_trace is not None:                                       # NEW-V3.19
        snap_dict["flow_trace"] = flow_trace
    try:
        write_json_file(snap_path, snap_dict)
        logger.info(f"[OK] Snapshot: {snap_path}  (use --compare OLD NEW for pre/post diff)")
    except Exception as e:
        logger.warning(f"  Snapshot write failed: {e}")

    # Phase 22: HTML Explorer (self-contained) - NEW-V3.17. Embeds the same snap_dict the
    # snapshot.json carries directly into a copy of blast_radius_explorer.html, so one run
    # yields both the workbook and a ready-to-open, air-gapped topology explorer. The JSON
    # write (above) and this HTML write are the last emits, so any future per-version
    # enrichment of snap_dict lands in both outputs.
    if not args.no_html:
        html_out = os.path.splitext(os.path.abspath(out_xlsx))[0] + "_explorer.html"
        label = os.path.splitext(os.path.basename(out_xlsx))[0]
        try:
            write_html_explorer(html_out, snap_dict, label)
        except Exception as e:
            logger.warning(f"  HTML Explorer write failed: {e}")


if __name__ == "__main__":
    main()
