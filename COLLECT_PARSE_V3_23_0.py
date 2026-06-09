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
   * Pre/post-cutover validation - a snapshot JSON (<output>.snapshot.json) is written next to every
     workbook; run with '--compare OLD.json NEW.json' to emit a validation workbook: a Summary CUTOVER
     VERDICT (CLEAN / REVIEW / REGRESSED) + Interface / Endpoint / SVI changes + Health Shifts (per-switch
     band regressions/improvements) + Findings Delta (punch-list findings opened vs resolved by the
     cutover). --compare skips SSH and the template.
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
# 'from dataclasses import dataclass, field' moved to cisco_toolkit.analyze with
# ScoringConfig (PHASE 2.7 step 10) - the monolith's last dataclass user.
from datetime import datetime
from typing import Dict, List   # Optional dropped step 28 (build_interfaces moved); Tuple step 27

# 'from openpyxl.cell.cell import MergedCell' dropped (step 26): its only user,
# append_interface_rows, moved to cisco_toolkit.excel.
# NEW-V3.23.11 (PHASE 2.7 step 1): pure text/interface-name helpers + regex
# constants extracted to the cisco_toolkit package; imported back so every
# existing reference keeps working unchanged (behaviour byte-identical).
# normalize_ifname / detect_link_type dropped step 28 (build_interfaces, their last monolith
# user, moved to build); PHYSICAL_IFACE_RE step 27; _TRUNK_STATUS_WORDS step 26;
# VALID_IFACE_RE / IFACE_TOKEN_RE / normalize_speed (steps 17/25). Only safe_fs_name remains.
from cisco_toolkit.textutils import safe_fs_name
# _split_macs re-import dropped in step 21 (its last monolith user, write_vlan_census_sheet,
# moved to excel; analyze.py + excel.py now import it from textutils directly).
# NEW-V3.23.38 (PHASE 2.7 step 28): the monolith no longer imports ANY parser from
# cisco_toolkit.parse - build_interfaces, the last parser consumer, moved to
# cisco_toolkit.build. The ~30 parsers all live in cisco_toolkit/parse.py; the parser
# unit tests import them from there directly (test_parsers / test_platform_variants).
# NEW-V3.23.19 (PHASE 2.7 step 9): the passed-around data model (InterfaceData /
# DevicePhysical) extracted to the package leaf; imported back so every type hint
# and constructor call keeps working unchanged (behaviour byte-identical).
from cisco_toolkit.model import InterfaceData, DevicePhysical
# NEW-V3.23.40 (PHASE 2.7 step 30): the version string, hoisted into cisco_toolkit/__init__.py
# (single source of truth); imported back here so LOG_FILE / argparse keep working + snapshot_state
# (now in cisco_toolkit.html) reads the same value.
from cisco_toolkit import __version__
# NEW-V3.23.20-.25 (PHASE 2.7 steps 10-15): analyze-layer symbols imported back so the
# Excel writers + the physical/L3/flow functions + main() still in this file keep working.
# ScoringConfig / SCORING / _host_role are NOT re-exported anymore (step 15 moved their last
# monolith users, the scoring compute_*); _health_band stays (write_health_scores_sheet uses it).
from cisco_toolkit.analyze import (
    compute_move_groups,   # _health_band dropped (step 23): write_health_scores_sheet moved to excel
    # compute_topology_links / compute_findings dropped (step 22): their last monolith users
    # (write_topology_sheet / write_findings_sheet) moved to excel.
    # build_network_model dropped (step 25): write_physical_health_sheet (its last monolith user) moved.
    # _link_carries (step 19) / _vlan_components (step 18) / compute_causality_chains / compute_failure_impact
    # (step 24) were dropped earlier for the same reason.
    compute_data_quality, compute_health_scores,
    compute_score_sensitivity, compute_calibration_report, compute_migration_readiness,
    compute_protocol_health,   # _poe_device_util / _physical_uplink_index dropped (step 25): phy writer moved
    build_dependency_map, compute_cross_layer_correlations, trace_full_flow,
    stp_root_findings, compute_migration_punchlist,   # NEW-V3.23.62 / .63 (STP root analysis + consolidated punch-list)
    compute_hostname_mismatches,                       # NEW-V3.23.68 (inventory-name vs configured-hostname)
    compute_operational_drift,                         # NEW-V3.23.93 (false-health / operational-drift detector)
    compute_endpoint_identity,                         # NEW-V3.23.95 (endpoint vendor + class intelligence)
    compute_flow_paths,                                # NEW-V3.23.126 (representative end-to-end flow paths; workbook/runbook twin of the Flow Simulator)
    compute_endpoint_dependencies,                     # NEW-V3.23.96 (clusters / dependencies / per-switch validation)
    compute_subnet_intelligence,                       # NEW-V3.23.97 (subnet / routing reachability)
    compute_migration_scenarios,                       # NEW-V3.23.98 (per-group cutover scenario framework)
    compute_protocol_intelligence,                     # NEW-V3.23.100 (protocol-state doctrine: cause + remediation)
    compute_service_map,                               # NEW-V3.23.101 (L4 service map from ACL ports + multicast activity)
    compute_ptp_readiness,                             # NEW-V3.23.108 (PTP / media-timing readiness -> punch-list)
    compute_multicast_intelligence,                    # NEW-V3.23.115 (media-fabric deep-dive: MAC-alias / querier / PTP tree)
    compute_remediation_plan,                          # NEW-V3.23.116 (assess->act: per-device config snippets, review-only)
    compute_validation_plan,                           # NEW-V3.23.143 (assess->verify: per-wave post-cutover checks)
    compute_golden_drift,                              # NEW-V3.23.146 (per-device config drift vs a baseline)
    compute_lifecycle_risk,                            # NEW-V3.23.117 (hardware EoL / end-of-support band per device)
    compute_segmentation,                              # NEW-V3.23.118 (L3 isolation posture: VRF / gateway-ACL per domain)
    compute_executive_brief,                           # NEW-V3.23.120 (cross-axis migration brief synthesis)
    compute_collection_completeness,                   # NEW-V3.23.109 (pre-assessment blind-spot / collection report)
    compute_application_intelligence,                  # NEW-V3.23.112 (application-domain synthesis + migration risk)
)
# NEW-V3.23.24 (PHASE 2.7 step 14): the command-output I/O glue. _load_cmd_output +
# _safe_parse dropped step 28 (build_interfaces, their last monolith user, moved to
# build); only _CISCO_ERRORS stays (platform detection reuses it).
from cisco_toolkit.cmdio import _CISCO_ERRORS
# NEW-V3.23.30 (PHASE 2.7 step 20): the Excel layer's shared sheet/header helpers; imported
# back so the write_* sheet builders + main()'s template-fill keep working unchanged.
from cisco_toolkit.excel import (
    find_header_row, ensure_headers,   # sortkey dropped step 26 (append_interface_rows moved);
    # _census_header/_census_autofit were dropped step 24 (their writers moved to excel).
    write_device_inventory_sheet, write_svi_gateway_sheet, write_stp_detail_sheet,  # step 21
    write_vlan_census_sheet, write_endpoint_census_sheet,                            # step 21
    write_move_group_sheet, write_topology_sheet, write_findings_sheet,             # step 22
    write_capacity_sheet, compute_capacity, write_topology_diagram,                 # step 22 (compute_capacity: V3.23.87 capacity embedded in snapshot)
    write_cross_layer_sheet, write_protocol_health_sheet,   # _SEV_FILL dropped step 25 (last writers moved)
    write_health_scores_sheet, write_score_sensitivity_sheet, write_calibration_sheet,  # step 23 (+calibration V3.23.47)
    write_nat_sheet,   # NAT inventory V3.23.50
    write_security_sheet,   # Security Posture (CIS-aligned) V3.23.59
    write_config_hygiene_sheet,   # Config Hygiene (undefined refs / unused structures) V3.23.61
    write_stp_roots_sheet,   # STP Root Bridges (accidental root / gateway misalignment) V3.23.62
    write_punchlist_sheet,   # Migration Punch-List (consolidated, severity-ranked) V3.23.63
    write_protocol_boundaries_sheet,   # protocol-to-protocol analysis (workbook surfacing)
    write_addressing_conflicts_sheet,  # reachability findings -> workbook surfacing
    write_fhrp_consistency_sheet,      # reachability findings -> workbook surfacing
    write_trunk_native_sheet,          # reachability findings -> workbook surfacing
    write_link_phy_sheet,              # reachability findings -> workbook surfacing
    compute_addressing_conflicts, compute_fhrp_consistency,   # NEW-V3.23.64 (L2 checks -> punch-list)
    compute_trunk_native_mismatches, compute_duplex_speed_mismatches,
    write_migration_readiness_sheet,
    write_interface_health_sheet, write_security_posture_sheet, write_routing_adjacency_sheet,  # step 24
    write_causality_chains_sheet, write_failure_impact_sheet, write_link_centrality_sheet,      # step 24 (+Link Centrality V3.23.88)
    write_wave_sequencing_sheet,                                                                # NEW-V3.23.89 (cutover sequencing)
    write_endpoint_intelligence_sheet,                          # NEW-V3.23.95 (endpoint vendor + class)
    write_endpoint_dependencies_sheet,                          # NEW-V3.23.96 (clusters / dependencies)
    write_subnet_reachability_sheet,                            # NEW-V3.23.97 (subnet / routing reachability)
    write_migration_scenarios_sheet,                            # NEW-V3.23.98 (per-group cutover scenario)
    write_protocol_intelligence_sheet,                          # NEW-V3.23.100 (protocol-state cause + remediation)
    write_service_map_sheet,                                     # NEW-V3.23.101 (L4 service map + multicast activity)
    write_multicast_intelligence_sheet,                          # NEW-V3.23.115 (media-fabric multicast intelligence)
    write_remediation_plan_sheet,                                # NEW-V3.23.116 (generated config snippets, review-only)
    write_validation_plan_sheet,                                 # NEW-V3.23.143 (per-wave post-cutover validation checklist)
    write_golden_drift_sheet,                                    # NEW-V3.23.146 (per-device config drift vs baseline)
    write_lifecycle_risk_sheet,                                  # NEW-V3.23.117 (hardware EoL / end-of-support)
    write_segmentation_sheet,                                    # NEW-V3.23.118 (L3 segmentation / isolation posture)
    write_collection_completeness_sheet,                         # NEW-V3.23.109 (pre-assessment blind-spot report)
    write_application_intelligence_sheet,                        # NEW-V3.23.112 (application-domain synthesis)
    write_executive_summary_sheet,                              # NEW-V3.23.75 (one-page landing synthesis)
    write_physical_health_sheet, write_flow_trace_sheet, write_flow_paths_sheet, write_l3_forwarding_sheet,             # step 25
    append_interface_rows,                                                                       # step 26
)
# NEW-V3.23.37-.38 (PHASE 2.7 steps 27-28): the model-construction layer - the per-device
# InterfaceData builder + switch-level DevicePhysical / switch-identity records + global-ARP
# enrichment. Homed in cisco_toolkit/build.py; imported back so main() keeps calling them.
from cisco_toolkit.build import (
    build_interfaces,   # step 28: the big per-device InterfaceData builder
    build_device_physical, build_switch_identity, collect_global_arp,
    apply_global_arp, detect_cross_device_dual_connections, build_acls, build_object_groups,
    read_run_config,   # NEW-V3.23.146 (raw running-config text for golden-config drift)
    build_routes, inscope_subnets, scope_routes, build_bgp_received, build_nat, build_security, build_config_hygiene, build_stp_roots, build_vpc, build_routing_neighbors,
    build_igmp_groups, build_igmp_queriers, build_ptp, build_acl_hits,   # NEW-V3.23.102 (multicast / PTP / ACL-hit collection)
    build_redistribution,
)
# NEW-V3.23.39-.40 (PHASE 2.7 steps 29-30): the snapshot-reporting layer - snapshot_state (the JSON
# contract), write_html_explorer (bakes the snapshot into the Blast-Radius Explorer), and the
# '--compare OLD NEW' diff workbook. Homed in cisco_toolkit/html.py; imported back so main() keeps
# building/serializing the snapshot + emitting the HTML + diff outputs.
from cisco_toolkit.html import (snapshot_state, write_html_explorer, write_diff_workbook,
                                write_campaign_workbook, redact_snapshot)   # NEW-V3.23.145 (campaign trend)
from cisco_toolkit.runbook import write_runbook_docx                 # NEW-V3.23.93 (DOCX runbook deliverable)
from cisco_toolkit.deck import write_executive_deck_pptx             # NEW-V3.23.144 (executive PPTX deck deliverable)
from cisco_toolkit.design import write_design_doc_docx               # NEW-V3.23.148 (As-Built HLD/LLD design document)
from cisco_toolkit.mop import write_mop_docx                         # NEW-V3.23.149 (per-wave Method of Procedure)
# FIX-V3.23.8 (P4): scope the warnings filter to DeprecationWarning (netmiko /
# paramiko / cryptography churn + Netmiko 5.x deprecations) instead of suppressing
# EVERYTHING - so genuine UserWarning / RuntimeWarning signals surface.
warnings.filterwarnings("ignore", category=DeprecationWarning)

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
    # Font / PatternFill / Alignment (styles) + get_column_letter (utils) dropped step 29:
    # their last monolith user, write_diff_workbook, moved to cisco_toolkit.html.
except ImportError:
    print("ERROR: openpyxl not installed. Run: python3 -m pip install openpyxl")
    sys.exit(1)

# =============================================================================
# CONFIG
# =============================================================================
# __version__ moved to cisco_toolkit/__init__.py (PHASE 2.7 step 30); imported back near the top of this file.
LOG_FILE              = f"cisco_migration_autofill_v{__version__.replace('.', '_')}.log"
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
    "show vpc",                          # NEW-V3.23.125 (vPC / MLAG peer confirmation for the flow simulator)
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
    "show bgp ipv4 unicast",     # NEW-V3.23.97 (BGP RIB / received prefixes - NX-OS)
    "show ip igmp groups",          # NEW-V3.23.102 (multicast membership census - broadcast fabric)
    "show ip igmp snooping groups", # NEW-V3.23.102 (L2 multicast forwarding)
    "show ip igmp snooping querier",# NEW-V3.23.102 (L2 querier per VLAN)
    "show ptp clock",               # NEW-V3.23.102 (IEEE 1588 PTP clock health)
    "show ptp parent",              # NEW-V3.23.102 (PTP grandmaster)
    "show ip access-lists",         # NEW-V3.23.102 (ACL hit-counts = active-traffic evidence)
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
    "show environment all",      # NEW-V3.23.67 (IOS-XE 9300/3850: bare 'show environment' -> '% Incomplete command')
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
    "show ip bgp",                    # NEW-V3.23.97 (BGP RIB / received prefixes - IOS/IOS-XE)
    "show track",                     # NEW-V3.20 (L3 forwarding: object / IP-SLA tracking)
    "show spanning-tree detail",      # NEW-V3.22 (STP topology-change counters)
    "show ip igmp groups",            # NEW-V3.23.102 (multicast membership census - broadcast fabric)
    "show ip igmp snooping groups",   # NEW-V3.23.102 (L2 multicast forwarding)
    "show ip igmp snooping querier",  # NEW-V3.23.102 (L2 querier per VLAN)
    "show ptp clock",                 # NEW-V3.23.102 (IEEE 1588 PTP clock health)
    "show ptp parent",                # NEW-V3.23.102 (PTP grandmaster)
    "show ip access-lists",           # NEW-V3.23.102 (ACL hit-counts = active-traffic evidence)
]

COMMANDS_ALL = list(dict.fromkeys(COMMANDS_NXOS + COMMANDS_IOS))

# Interface regex constants moved to cisco_toolkit.textutils (PHASE 2.7 step 1);
# imported near the top of this file.

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

# DATA MODEL - InterfaceData / DevicePhysical moved to cisco_toolkit.model
# (PHASE 2.7 step 9); imported back near the top of this file. ScoringConfig
# stays here - it travels with the analyze layer, not the data model.

# Normalization helpers moved to cisco_toolkit.textutils (PHASE 2.7 step 1);
# imported near the top of this file.

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
    # FIX (C2): prefer pattern-based send_command() (waits for the device prompt)
    # over send_command_timing(), which can return early/truncated output that is
    # then parsed as if complete. read_timeout is sized up for slow/large dumps.
    # Fall back to the timing-based read only if the prompt pattern isn't matched,
    # so behaviour is no worse than before on edge cases.
    timeout = 300 if any(s in cmd for s in _SLOW_CMDS) else 120
    try:
        return dev.send_command(cmd, read_timeout=timeout) or ""
    except Exception as e:
        logger.warning(f"Command '{cmd}' pattern-read failed ({e}); retrying timing-based")
        try:
            return dev.send_command_timing(cmd, read_timeout=timeout) or ""
        except Exception as e2:
            logger.warning(f"Command failed '{cmd}': {e2}")
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
# _CISCO_ERRORS / _load_cmd_output / _safe_parse moved to cisco_toolkit.cmdio
# (PHASE 2.7 step 14); all three imported back near the top of this file (nearly
# every build_*/compute_*/write_* reads collected output via _load_cmd_output, and
# platform detection reuses _CISCO_ERRORS).

# =============================================================================
# PARSERS - interface commands
# =============================================================================
# extract_fixed_cols / slice_col moved to cisco_toolkit.parse (PHASE 2.7 step 2);
# imported near the top of this file.

# parse_show_interface_status / _switchport / _trunk_table moved to
# cisco_toolkit.parse (PHASE 2.7 step 4); imported at the top of this file.

# MAC / STP / vlan_brief / _compress_vlans moved to cisco_toolkit.parse
# (PHASE 2.7 step 5); imported at the top of this file.

# VRF / PoE / CDP / LLDP / infer_endpoint_type moved to cisco_toolkit.parse
# (PHASE 2.7 step 5); imported at the top of this file.

# run-config / etherchannel proto+members / ip-arp parsers moved to
# cisco_toolkit.parse (PHASE 2.7 step 6); imported at the top of this file.

# vtp_status / _parse_ip_int_brief / parse_switch_mgmt_ip moved to
# cisco_toolkit.parse (PHASE 2.7 step 6); imported at the top of this file.

# parse_ip_routes moved to cisco_toolkit.parse (PHASE 2.7 step 3); imported at top.

# parse_hsrp_summary / parse_vrrp_summary / parse_glbp_summary moved to
# cisco_toolkit.parse (PHASE 2.7 step 3); imported at the top of this file.

# parse_multicast_info moved to cisco_toolkit.parse (PHASE 2.7 step 6);
# imported at the top of this file.

# =============================================================================
# PHYSICAL PARSERS (NEW-V12)
# =============================================================================

# parse_show_version / _inv_commit / parse_show_inventory moved to
# cisco_toolkit.parse (PHASE 2.7 step 7); imported at the top of this file.


# parse_show_environment_power / parse_show_environment / parse_show_module_count
# moved to cisco_toolkit.parse (PHASE 2.7 step 7); imported at the top of this file.

# =============================================================================
# BUILD PHYSICAL DEVICE SUMMARY (NEW-V12)
# =============================================================================
# build_device_physical moved to cisco_toolkit.build (PHASE 2.7 step 27); imported
# back near the top of this file (main() calls it per device).

# =============================================================================
# SITE SURVEY SHEET WRITER (NEW-V12)
# =============================================================================
# Census/inventory sheet writers moved to cisco_toolkit.excel (PHASE 2.7 step 21):
# write_device_inventory_sheet / write_svi_gateway_sheet / write_stp_detail_sheet /
# write_vlan_census_sheet / write_endpoint_census_sheet (+ their *_COLUMNS / *_SHEET_NAME
# constants + _is_svi). All five writers imported back near the top of this file (main()
# calls them); the constants + _is_svi are package-internal.

# (SVI / STP Detail / VLAN Census / Endpoint Census writers also moved to
# cisco_toolkit.excel in step 21 - see the note above.)


# =============================================================================
# NEW-V14.9: Move-group planning. Switches that share an L2 broadcast domain must
# migrate together; connected components over "shared-VLAN" edges = migration waves.
# Captures transitive coupling (A-VLAN10-B, B-VLAN20-C => A,B,C are one group) that
# is easy to miss by eye. Coupling uses ACTUAL VLAN presence (access port or SVI),
# consistent with the VLAN Census; trunk-allowed-only transit is NOT modeled, and
# VLAN 1 (default, present everywhere) is excluded from grouping by design.
# =============================================================================
# Analysis sheet writers (move-group / topology / findings / capacity / topology-diagram)
# moved to cisco_toolkit.excel (PHASE 2.7 step 22); the five writers are imported back near
# the top of this file (main() calls them). They call the analyze compute_* internally now,
# so compute_move_groups / compute_topology_links / compute_findings are no longer used here.


# build_switch_identity moved to cisco_toolkit.build (PHASE 2.7 step 27); imported
# back near the top of this file (main() calls it per device).

# =============================================================================
# BUILD INTERFACE DB (per device)
# =============================================================================
# build_interfaces (the per-device InterfaceData builder) moved to cisco_toolkit.build
# (PHASE 2.7 step 28); imported back near the top of this file (main() calls it per device).

# =============================================================================
# GLOBAL ARP COLLECTION (FIX-R1, FIX-R3, FIX-R5, NEW-V11)
# =============================================================================
# collect_global_arp / apply_global_arp / detect_cross_device_dual_connections moved to
# cisco_toolkit.build (PHASE 2.7 step 27); imported back near the top of this file
# (main() calls them during the global-ARP enrichment + dual-connection pass).

# =============================================================================
# EXCEL WRITER
# =============================================================================
# norm_header / HEADER_TO_FIELD / find_header_row / ensure_headers / sortkey moved to
# cisco_toolkit.excel (PHASE 2.7 step 20); find_header_row / ensure_headers (main()) and
# sortkey (append_interface_rows below) are imported back near the top of this file.
# norm_header / HEADER_TO_FIELD are package-internal.

# append_interface_rows (the main 'Migration Assessment' interface-sheet filler) moved to
# cisco_toolkit.excel (PHASE 2.7 step 26); imported back near the top of this file (main()
# calls it per device). It's the last sheet writer - the whole excel layer now lives in
# cisco_toolkit/excel.py.

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
# compute_topology_links moved to cisco_toolkit.analyze (PHASE 2.7 step 12); imported
# back near the top of this file (write_topology_sheet / write_topology_diagram use it).
# -----------------------------------------------------------------------------


# -----------------------------------------------------------------------------
# Tier 1 #1: Findings / Risk Register  (pure cross-reference of InterfaceData)
# -----------------------------------------------------------------------------
# (Findings / Capacity / Topology-diagram writers also moved to cisco_toolkit.excel in
# step 22 - see the note above. _to_float / _mermaid_id moved with them as package-internal.)


# -----------------------------------------------------------------------------
# Tier 1 #2: Pre/post-cutover snapshot + diff. A snapshot JSON is written next
# to every output workbook; '--compare OLD NEW' produces a diff workbook.
# -----------------------------------------------------------------------------
# snapshot_state + write_html_explorer moved to cisco_toolkit.html (PHASE 2.7 step 30);
# both imported back near the top of this file (main() builds the snapshot + emits the HTML).


# _DIFF_FIELDS / _macset / write_diff_workbook moved to cisco_toolkit.html (PHASE 2.7 step 29);
# write_diff_workbook imported back near the top of this file (main()'s --compare path calls it).
# _DIFF_FIELDS / _macset are package-internal. (snapshot_state + write_html_explorer follow in step 30.)


# -----------------------------------------------------------------------------
# Tier 2 #1: Interface health counters  ('show interfaces' / 'show interface')
# -----------------------------------------------------------------------------
# Tier-2 (file-reading) + intelligence sheet writers moved to cisco_toolkit.excel
# (PHASE 2.7 step 24): write_interface_health_sheet / write_security_posture_sheet /
# write_routing_adjacency_sheet / write_causality_chains_sheet / write_failure_impact_sheet.
# All five imported back near the top of this file (main() calls them). excel.py now imports
# _load_cmd_output + the parse parsers + compute_causality_chains/compute_failure_impact itself.


# (Causality Chains + Failure Impact writers also moved to cisco_toolkit.excel in step 24 -
# see the note above. The intelligence-layer design doc lives with compute_causality_chains /
# compute_failure_impact in cisco_toolkit/analyze.py + the .md.)


# -----------------------------------------------------------------------------
# NEW-V3.18: Physical Health (L1). One row per physical port - negotiated
# speed/duplex/media, error counters, port-channel, PoE, and a derived physical
# risk flag. Pure derivation: reuses parse_show_interface_counters (errors),
# build_network_model (uplink topology -> single-fiber), and DevicePhysical
# (PoE budget). Negotiated duplex/media/speed come from the 'show interfaces'
# DETAIL block because InterfaceData.duplex is normalized and loses half-duplex.
# No new collection, no new InterfaceData fields, no new imports.
# -----------------------------------------------------------------------------
# Fused compute-in-writer sheets (write_physical_health_sheet / write_l3_forwarding_sheet /
# write_flow_trace_sheet) moved to cisco_toolkit.excel (PHASE 2.7 step 25). The physical-health
# + l3-forwarding writers compute their L1/L3 records inline and RETURN them; main() captures
# those via _run_phase. All three imported back near the top of this file.


# -----------------------------------------------------------------------------
# NEW-V3.19: Full-stack flow trace (L1->L3). Given two endpoint IPs, derive the
# path: locate each endpoint (end_host_ip), resolve gateway SVIs per subnet
# (svi_ip + subnet_primary_route containment + FHRP peers), decide L2 vs L3, walk
# the fabric over STP-forwarding links (_link_carries), flag single points of
# failure (single-fiber uplinks, single gateway, VLAN partition) and score risk.
# Pure derivation - routing comes from InterfaceData (no routing_data dict exists).
# L4 is NOT simulated (no ACL/service-policy is collected). No new imports.
# -----------------------------------------------------------------------------
# (Flow Trace + L3 Forwarding writers also moved to cisco_toolkit.excel in step 25 - see the
# note above. _parse_track / _track_summary moved with write_l3_forwarding_sheet (package-internal).)


# -----------------------------------------------------------------------------
# NEW-V3.21: Cross-layer correlation. Combines the L1 (physical_health) and L3
# (l3_forwarding) records already computed this run with topology facts from the
# model (articulation, single-fiber uplinks, single-member port-channels, orphan
# VLANs) to surface compounded-risk findings CL-01..CL-10 that no single-layer
# view shows. Pure derivation; no new collection.
# -----------------------------------------------------------------------------
# Health / analysis sheet writers (write_cross_layer_sheet / write_protocol_health_sheet /
# write_health_scores_sheet / write_score_sensitivity_sheet / write_migration_readiness_sheet)
# moved to cisco_toolkit.excel (PHASE 2.7 step 23); imported back near the top of this file
# (main() runs them via _run_phase). Their fill maps + sheet-name constants + _SEV_FILL moved too.


# =============================================================================
# MAIN
# =============================================================================
def _empty_dep_map() -> dict:
    """Empty dependency-map skeleton with every key the cross-layer and
    migration-readiness consumers read. Used as the resilient fallback if
    build_dependency_map() raises, so one analysis failure can't sink the run."""
    return {"single_fiber": set(), "uplink_ports": set(), "sole_gw": {},
            "access_by_vlan": {}, "articulation": set(), "fhrp_vlans": set(),
            "tracked_down": set(), "errored_up": set(), "halfdup_up": set(),
            "single_member_pc": set(), "errdis": set(), "gw_switches": set(),
            "orphan": set(), "model": {"hosts": set()}}


def _run_phase(label, fn, *args, _default=None, **kwargs):
    """FIX (resilience): run a pre-save phase so a failure LOGS AND CONTINUES
    instead of aborting the whole run before wb.save() (extends the FIX-V14-1
    'guard and continue' idea from Phase 6 to every phase). Returns the phase's
    result, or _default if it raised. Happy-path behaviour is unchanged."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        logger.error(f"  [SKIP] Phase '{label}' failed: {e!r}; "
                     f"continuing so the workbook still saves.")
        return _default


def main():
    ap = argparse.ArgumentParser(description=f"Cisco Migration Extractor V{__version__}")
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
                    help="NEW-V15: compare two snapshot JSONs and write a pre/post-cutover validation "
                         "workbook (Summary verdict + Interface/Endpoint/SVI changes + Health Shifts + "
                         "Findings Delta); skips collection and the template.")
    ap.add_argument("--no-html",         action="store_true",
                    help="NEW-V3.17: skip Blast-Radius Explorer (HTML) generation "
                         "(default: HTML is always written beside the workbook).")
    ap.add_argument("--no-docx",         action="store_true",
                    help="NEW-V3.23.93: skip the Assessment & Migration Runbook (DOCX). The runbook is "
                         "the narrative twin of the workbook; it needs python-docx (a missing library is "
                         "a warning, not an error).")
    ap.add_argument("--no-pptx",         action="store_true",
                    help="NEW-V3.23.144: skip the Executive presentation deck (PPTX). The deck is the "
                         "stakeholder twin of the workbook; it needs python-pptx (a missing library is "
                         "a warning, not an error).")
    ap.add_argument("--no-design",       action="store_true",
                    help="NEW-V3.23.148: skip the As-Built Network Design Document (HLD/LLD, DOCX). It "
                         "reconstructs the current design + target-state recommendations from the "
                         "snapshot; needs python-docx (a missing library is a warning, not an error).")
    ap.add_argument("--no-mop",          action="store_true",
                    help="NEW-V3.23.149: skip the per-wave Method of Procedure (MOP, DOCX) — a "
                         "maintenance-window cutover template per migration wave; needs python-docx "
                         "(a missing library is a warning, not an error).")
    ap.add_argument("--golden-config",   default=None, metavar="FILE",
                    help="NEW-V3.23.146: a golden-config baseline file (one required directive per line; "
                         "'#' comments and 're:<regex>' supported) for the Golden-Config Drift sheet. "
                         "Omit to auto-derive the baseline from the fleet's majority (de-facto standard).")
    ap.add_argument("--flow-src",        default=None, metavar="IP",
                    help="NEW-V3.19: source endpoint IP for the optional Flow Trace sheet "
                         "(requires --flow-dst).")
    ap.add_argument("--flow-dst",        default=None, metavar="IP",
                    help="NEW-V3.19: destination endpoint IP for the optional Flow Trace sheet "
                         "(requires --flow-src).")
    ap.add_argument("--trend",           nargs="+", default=None, metavar="SNAPSHOT",
                    help="NEW-V3.23.145: migration-campaign trend across a SERIES of snapshot JSONs (>=2, "
                         "oldest first) -> a trend workbook (Campaign Summary verdict + Timeline w/ chart + "
                         "Burndown). Skips collection and the template.")
    ap.add_argument("--redact",          action="store_true",
                    help="NEW-V3.23.41: pseudonymize IPs / MACs / serial numbers in the snapshot "
                         "JSON + embedded HTML explorer (consistent, subnet-preserving; hostnames "
                         "kept) so the single-file deliverable can be shared without leaking real "
                         "addressing. Default off.")
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
        os.makedirs(os.path.dirname(os.path.abspath(diff_out)) or ".", exist_ok=True)  # FIX-V3.23.103: same missing-output-dir guard
        write_diff_workbook(old_snap, new_snap, diff_out)
        logger.info(f"[OK] Saved diff workbook: {os.path.abspath(diff_out)}")
        return

    # NEW-V3.23.145: trend mode - migration-campaign trajectory across a SERIES of snapshots, no SSH/template.
    if args.trend:
        if len(args.trend) < 2:
            ap.error("--trend: need at least two snapshot JSON files (oldest first).")
        snaps = []
        try:                                              # clean message, not a raw traceback
            for p in args.trend:
                with open(p, encoding="utf-8") as f:
                    snaps.append(json.load(f))
        except FileNotFoundError as e:
            ap.error(f"--trend: snapshot file not found: {e.filename}")
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            ap.error(f"--trend: could not parse snapshot JSON ({e})")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        trend_out = args.output or f"Migration_Trend_{stamp}.xlsx"
        os.makedirs(os.path.dirname(os.path.abspath(trend_out)) or ".", exist_ok=True)
        write_campaign_workbook(snaps, trend_out)
        logger.info(f"[OK] Saved campaign trend workbook: {os.path.abspath(trend_out)}")
        return

    if not args.devices_file:
        ap.error("--devices-file is required (unless using --compare OLD NEW)")

    if not os.path.exists(args.template):
        raise FileNotFoundError(f"Template not found: {args.template}")

    devices = load_devices(args.devices_file)
    stamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_xlsx = args.output or DEFAULT_OUTPUT_FILE.format(stamp)

    # FIX-V3.23.103: create the --output directory up-front, the moment the path is
    # resolved -- BEFORE the ~31 phases of multi-minute compute. The workbook, snapshot,
    # topology diagram, HTML explorer and runbook are all emitted only at the very end of
    # the run, and they all derive their directory from this same out_xlsx (see the
    # post-save block). A missing output directory would otherwise crash openpyxl's
    # wb.save() with FileNotFoundError AFTER all the heavy compute, wasting the whole run.
    # One guard here covers every output. No behaviour change when the directory exists.
    os.makedirs(os.path.dirname(os.path.abspath(out_xlsx)) or ".", exist_ok=True)

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

    # Phase 5.6: ACL definitions (L4 allow/deny sim) - parsed from the already-collected
    # run-config; emitted into the snapshot below so the explorer can evaluate flows offline.
    all_acls: Dict[str, dict] = {}
    all_object_groups: Dict[str, dict] = {}
    all_nat: Dict[str, dict] = {}                                    # NEW-V3.23.50 (NAT inventory)
    all_security: Dict[str, dict] = {}                               # NEW-V3.23.59 (CIS-aligned security posture)
    all_config_hygiene: Dict[str, dict] = {}                         # NEW-V3.23.61 (undefined refs / unused structures)
    all_stp_roots: Dict[str, dict] = {}                              # NEW-V3.23.62 (per-VLAN STP root bridge)
    all_vpc: Dict[str, dict] = {}                                    # NEW-V3.23.125 (vPC / MLAG status per device)
    all_routing_neighbors: Dict[str, dict] = {}                      # protocol-to-protocol analysis (OSPF/EIGRP/BGP adjacencies)
    all_redistribution: Dict[str, list] = {}                         # protocol-to-protocol analysis (redistribution edges)
    all_run_configs: Dict[str, str] = {}                             # NEW-V3.23.146 (raw running-config for golden-config drift)
    for hostname, platform, cmd_to_file in all_devices_meta:
        rc_text = read_run_config(cmd_to_file)                       # NEW-V3.23.146
        if rc_text:
            all_run_configs[hostname] = rc_text
        acls = build_acls(cmd_to_file)
        if acls:
            all_acls[hostname] = acls
            logger.info(f"  [ACL] {hostname}: {len(acls)} access-list(s) parsed")
        og = build_object_groups(cmd_to_file)
        if og:
            all_object_groups[hostname] = og
            logger.info(f"  [ACL] {hostname}: {len(og)} object-group(s) parsed")
        nat = build_nat(cmd_to_file)
        if nat:
            all_nat[hostname] = nat
            logger.info(f"  [NAT] {hostname}: {len(nat.get('static', []))} static, "
                        f"{len(nat.get('dynamic', []))} dynamic rule(s)")
        sec = build_security(cmd_to_file)
        if sec:
            all_security[hostname] = sec
            _summ = sec.get("summary", {})
            logger.info(f"  [SEC] {hostname}: {_summ.get('fail', 0)} fail / "
                        f"{len(sec.get('findings', []))} check(s) ({_summ.get('grade', '')})")
        hyg = build_config_hygiene(cmd_to_file)
        if hyg:
            all_config_hygiene[hostname] = hyg
            _hs = hyg.get("summary", {})
            logger.info(f"  [HYGIENE] {hostname}: {_hs.get('undefined', 0)} undefined ref(s), "
                        f"{_hs.get('unused', 0)} unused structure(s)")
        stp_roots = build_stp_roots(cmd_to_file)
        if stp_roots:
            all_stp_roots[hostname] = stp_roots
            logger.info(f"  [STP] {hostname}: root bridge info for {len(stp_roots)} VLAN(s)")
        vpc = build_vpc(cmd_to_file)
        if vpc:
            all_vpc[hostname] = vpc
            logger.info(f"  [vPC] {hostname}: domain {vpc.get('domain_id')} role {vpc.get('role') or '?'}, "
                        f"{len(vpc.get('vpcs', []))} vPC(s)")
        rn = build_routing_neighbors(cmd_to_file)
        if any(rn.values()):
            all_routing_neighbors[hostname] = rn
            logger.info(f"  [PROTO] {hostname}: {len(rn['ospf'])} OSPF, "
                        f"{len(rn['eigrp'])} EIGRP, {len(rn['bgp'])} BGP adjacency(ies)")
        redist = build_redistribution(cmd_to_file)
        if redist:
            all_redistribution[hostname] = redist
            logger.info(f"  [PROTO] {hostname}: {len(redist)} redistribution edge(s)")

    # Phase 5.7: routing tables (route-aware reachability) - parsed from the already-collected
    # 'show ip route', scoped to the in-scope gateway subnets so the embedded snapshot stays small.
    all_routes: Dict[str, list] = {}
    all_routes_full: Dict[str, dict] = {}                            # NEW-V3.23.97 (FULL table for subnet intelligence; transient, not embedded)
    all_bgp_received: Dict[str, list] = {}                           # NEW-V3.23.97 (BGP RIB when 'show ip bgp' was collected)
    # NEW-V3.23.102: multicast/PTP/ACL-hit collection (inert until the new commands are collected).
    _igmp_groups: set = set()                                        # distinct multicast groups, fleet-wide
    all_igmp_queriers: list = []                                     # [{switch, vlan, querier}]
    all_ptp: Dict[str, dict] = {}                                   # {host: ptp clock health}
    all_acl_hits: Dict[str, int] = {}                              # {"port:proto": total matches}
    _inscope = inscope_subnets(all_interfaces)
    for hostname, platform, cmd_to_file in all_devices_meta:
        rdb = build_routes(cmd_to_file)
        if rdb:
            all_routes_full[hostname] = rdb
        scoped = scope_routes(rdb, _inscope)
        if scoped:
            all_routes[hostname] = scoped
            logger.info(f"  [ROUTE] {hostname}: {len(scoped)} in-scope route(s) embedded")
        bgpr = build_bgp_received(cmd_to_file)
        if bgpr:
            all_bgp_received[hostname] = bgpr
        _igmp_groups.update(build_igmp_groups(cmd_to_file))
        for q in build_igmp_queriers(cmd_to_file):
            all_igmp_queriers.append({"switch": hostname, **q})
        ptp = build_ptp(cmd_to_file)
        if ptp:
            all_ptp[hostname] = ptp
        for k, v in build_acl_hits(cmd_to_file).items():
            all_acl_hits[k] = all_acl_hits.get(k, 0) + v
    all_igmp_groups = sorted(_igmp_groups, key=lambda ip: tuple(int(o) for o in ip.split(".")))

    # Phase 6: Write interface rows to template sheet (each host guarded so one
    # host's write failure can't abort the run before wb.save()).
    logger.info("\n[Phase 6] Writing interface rows ...")
    for hostname, platform, cmd_to_file in all_devices_meta:
        iface_rows = all_interfaces.get(hostname, {})
        if not iface_rows:
            logger.warning(f"  [SKIP] No parsed interfaces for {hostname}")
            continue
        _run_phase(f"interface rows ({hostname})", append_interface_rows,
                   ws, header_row, col_map, hostname, iface_rows)
        logger.info(f"  [OK] {len(iface_rows)} rows for {hostname}")

    # Phases 7-20 are pure sheet writers; each is guarded so a single sheet's
    # failure logs and is skipped rather than sinking the whole workbook.
    # Phase 7: Write Switch Inventory sheet (NEW-V12)
    logger.info("\n[Phase 7] Writing Switch Inventory sheet ...")
    _run_phase("Switch Inventory sheet", write_device_inventory_sheet, wb, all_device_physical)

    # Phase 8: Write SVI / Gateway sheet (NEW-V14.3)
    logger.info("\n[Phase 8] Writing SVI / Gateway sheet ...")
    _run_phase("SVI / Gateway sheet", write_svi_gateway_sheet, wb, all_interfaces)

    # Phase 9: Write STP Detail sheet (NEW-V14.7)
    logger.info("\n[Phase 9] Writing STP Detail sheet ...")
    _run_phase("STP Detail sheet", write_stp_detail_sheet, wb, all_interfaces)

    # Phase 10: Write VLAN Census sheet (NEW-V14.8)
    logger.info("\n[Phase 10] Writing VLAN Census sheet ...")
    _run_phase("VLAN Census sheet", write_vlan_census_sheet, wb, all_interfaces)

    # Phase 11: Write Endpoint Census sheet (NEW-V14.8)
    logger.info("\n[Phase 11] Writing Endpoint Census sheet ...")
    _run_phase("Endpoint Census sheet", write_endpoint_census_sheet, wb, all_interfaces)

    # Phase 12: Write Move Groups sheet (NEW-V14.9)
    logger.info("\n[Phase 12] Writing Move Groups sheet ...")
    _run_phase("Move Groups sheet", write_move_group_sheet, wb, all_interfaces)

    # Phase 13: Write Topology Links sheet (NEW-V14.10)
    logger.info("\n[Phase 13] Writing Topology Links sheet ...")
    _run_phase("Topology Links sheet", write_topology_sheet, wb, all_interfaces)

    # Phase 14: Findings / Risk Register (NEW-V15)
    logger.info("\n[Phase 14] Writing Findings sheet ...")
    _run_phase("Findings sheet", write_findings_sheet, wb, all_interfaces)

    # Phase 15: Capacity / Consolidation (NEW-V15)
    logger.info("\n[Phase 15] Writing Capacity sheet ...")
    _run_phase("Capacity sheet", write_capacity_sheet, wb, all_device_physical)

    # Phase 15b: Endpoint Intelligence (NEW-V3.23.95). Compute ONCE here (vendor via offline OUI +
    # inferred class); reused by the sheet AND the snapshot (one source of truth -> explorer + runbook).
    logger.info("\n[Phase 15b] Writing Endpoint Intelligence sheet ...")
    endpoint_identity = _run_phase("Endpoint identity", compute_endpoint_identity, all_interfaces, _default=[])
    _run_phase("Endpoint Intelligence sheet", write_endpoint_intelligence_sheet, wb, endpoint_identity)

    # Phase 16: Interface Health counters (NEW-V15)
    logger.info("\n[Phase 16] Writing Interface Health sheet ...")
    _run_phase("Interface Health sheet", write_interface_health_sheet, wb, all_cmd_to_files)

    # Phase 17: Security Posture (NEW-V15)
    logger.info("\n[Phase 17] Writing Security Posture sheet ...")
    _run_phase("Security Posture sheet", write_security_posture_sheet, wb, all_cmd_to_files)

    # Phase 18: Routing Adjacencies (NEW-V15)
    logger.info("\n[Phase 18] Writing Routing Adjacencies sheet ...")
    _run_phase("Routing Adjacencies sheet", write_routing_adjacency_sheet, wb, all_cmd_to_files)

    # Phase 19-20: Causality Chains + Failure Impact (NEW-V3.16 intelligence layer).
    # NEW-V3.23.91: compute each ONCE here and reuse for the sheet, the executive summary, and the
    # snapshot. The heavy model rebuild + per-(host,VLAN) articulation walk / per-switch removal
    # simulation previously ran 2-3x per report (the snapshot-build phase recomputed both), which was
    # ~2.5 min of the run on the real fleet. Local import keeps these out of this module's namespace
    # (the test_package re-export contract asserts they are NOT attributes of this module).
    from cisco_toolkit.analyze import compute_causality_chains, compute_failure_impact
    logger.info("\n[Phase 19] Writing Causality Chains sheet ...")
    causality_chains = _run_phase("Causality Chains", compute_causality_chains, all_interfaces, _default=[])
    _run_phase("Causality Chains sheet", write_causality_chains_sheet, wb, causality_chains)

    # Phase 20: Failure Impact simulation (NEW-V3.16 intelligence layer)
    logger.info("\n[Phase 20] Writing Failure Impact sheet ...")
    failure_impact = _run_phase("Failure Impact", compute_failure_impact, all_interfaces, _default=[])
    _run_phase("Failure Impact sheet", write_failure_impact_sheet, wb, failure_impact)
    _run_phase("Link Centrality sheet", write_link_centrality_sheet, wb, all_interfaces)   # NEW-V3.23.88 (chokepoint links)

    # Phase 23: Physical Health (L1) - NEW-V3.18. Sheet writers must precede wb.save(); the
    # phase number is a logical label (21/22 are post-save: snapshot/diagram + HTML). The
    # returned records are injected into snap_dict below so they reach both JSON and HTML.
    logger.info("\n[Phase 23] Writing Physical Health sheet ...")
    physical_health = _run_phase("Physical Health", write_physical_health_sheet,
                                 wb, all_interfaces, all_cmd_to_files, all_device_physical,
                                 _default=[])

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

    # Phase 24b: Representative Flow Paths - NEW-V3.23.126. The static twin of the explorer's Flow
    # Simulator: one representative endpoint per VLAN, traced L1->L3 (reuses trace_full_flow). Always
    # written; NOT embedded in the snapshot (the hop tie-break is topology-dependent -> not golden-stable).
    flow_paths = _run_phase("Flow paths", compute_flow_paths, all_interfaces, endpoint_identity,
                            _default={"flows": [], "summary": {}})
    _run_phase("Flow Paths sheet", write_flow_paths_sheet, wb, flow_paths)

    # Phase 25: L3 Forwarding Map - NEW-V3.20 (pre-save; records reused in snapshot)
    logger.info("\n[Phase 25] Writing L3 Forwarding Map sheet ...")
    l3_forwarding = _run_phase("L3 Forwarding Map", write_l3_forwarding_sheet,
                               wb, all_interfaces, all_cmd_to_files, _default=[])

    # Phase 26: Cross-Layer Analysis - NEW-V3.21 (consumes physical_health + l3_forwarding).
    # A failed dependency map falls back to an empty skeleton so Phases 28-29 still run.
    logger.info("\n[Phase 26] Writing Cross-Layer Analysis sheet ...")
    dep_map = _run_phase("dependency map", build_dependency_map,
                         all_interfaces, physical_health, l3_forwarding,
                         _default=_empty_dep_map()) or _empty_dep_map()
    cross_layer = _run_phase("Cross-Layer correlations", compute_cross_layer_correlations,
                             dep_map, _default=[])
    _run_phase("Cross-Layer Analysis sheet", write_cross_layer_sheet, wb, cross_layer)

    # Phase 27: Protocol Health - NEW-V3.22 (re-parses collected protocol output)
    logger.info("\n[Phase 27] Writing Protocol Health sheet ...")
    protocol_health = _run_phase("Protocol Health", compute_protocol_health,
                                 all_interfaces, all_cmd_to_files, _default=[])
    _run_phase("Protocol Health sheet", write_protocol_health_sheet, wb, protocol_health)
    # Phase 27b: Protocol Intelligence (NEW-V3.23.100). Join the protocol_health rows against the
    # offline protocol-state doctrine -> meaning + likely cause + remediation. Derived from
    # protocol_health (no re-parse); compute once -> sheet + snapshot (one source of truth).
    protocol_intelligence = _run_phase("Protocol intelligence", compute_protocol_intelligence,
                                       protocol_health, _default=[])
    _run_phase("Protocol Intelligence sheet", write_protocol_intelligence_sheet, wb, protocol_intelligence)
    # Phase 27c: Service Map (NEW-V3.23.101). Resolve ACL L4 port references + fleet multicast activity to
    # named services via the offline port registry (portdb). ACL refs are design intent (Inferred), not
    # active traffic. Compute once -> sheet + snapshot (one source of truth).
    service_map = _run_phase("Service map", compute_service_map, all_acls, all_interfaces, _default={},
                             igmp_groups=all_igmp_groups, ptp=all_ptp,
                             igmp_queriers=all_igmp_queriers, acl_hits=all_acl_hits)
    _run_phase("Service Map sheet", write_service_map_sheet, wb, service_map)
    # Phase 27c-bis: Multicast Intelligence (NEW-V3.23.115). Media-fabric deep-dive over service_map.multicast
    # (MAC-address aliasing / IGMP querier coverage / PTP timing tree). Compute once -> sheet + snapshot +
    # punch-list fold (one source of truth).
    multicast_intelligence = _run_phase("Multicast intelligence", compute_multicast_intelligence,
                                        service_map, all_interfaces, _default={})
    _run_phase("Multicast Intelligence sheet", write_multicast_intelligence_sheet, wb, multicast_intelligence)
    # Phase 27c-ter: Hardware Lifecycle Risk (NEW-V3.23.117). Per-device EoL / end-of-support band from the
    # offline eoldb KB (a top reason orgs migrate). asof defaults to now (the assessment date). Compute once
    # -> sheet + snapshot + punch-list fold.
    _dev_lifecycle = {dp.hostname: {"model": dp.model, "sw_version": dp.sw_version} for dp in all_device_physical}
    lifecycle_risk = _run_phase("Lifecycle risk", compute_lifecycle_risk, _dev_lifecycle, _default={})
    _run_phase("Lifecycle Risk sheet", write_lifecycle_risk_sheet, wb, lifecycle_risk)

    # Phase 27d: Collection completeness (NEW-V3.23.109). The pre-assessment blind-spot report -- which
    # INVENTORY (devices.json) devices were not / only partially collected, so the gaps are explicit
    # rather than buried in band counts. Compute once -> sheet + snapshot (one source of truth).
    _inventory_hosts = [d.get("hostname", "") for d in devices]
    collection_completeness = _run_phase("Collection completeness", compute_collection_completeness,
                                         _inventory_hosts, all_cmd_to_files, _default={})
    _run_phase("Collection Completeness sheet", write_collection_completeness_sheet, wb, collection_completeness)

    # Phase 28: Health Scores - NEW-V3.23 (synthesises L1/L3/cross-layer/protocol findings)
    logger.info("\n[Phase 28] Writing Health Scores sheet ...")
    data_quality = _run_phase("data quality", compute_data_quality, all_cmd_to_files, _default={}) or {}
    health_scores = _run_phase("Health Scores", compute_health_scores,
                               all_interfaces, physical_health, l3_forwarding,
                               cross_layer, protocol_health, _default=[],
                               data_quality=data_quality, security=all_security)
    _run_phase("Health Scores sheet", write_health_scores_sheet, wb, health_scores)

    # Phase 29: Migration Readiness - NEW-V3.23 (per move-group 10-check verdict)
    logger.info("\n[Phase 29] Writing Migration Readiness sheet ...")
    move_groups = _run_phase("move groups", compute_move_groups, all_interfaces, _default=[])
    migration_readiness = _run_phase(
        "Migration Readiness", compute_migration_readiness,
        all_interfaces, move_groups, health_scores, physical_health, l3_forwarding,
        cross_layer, protocol_health, dep_map, _default=[])
    _run_phase("Migration Readiness sheet", write_migration_readiness_sheet, wb, migration_readiness)
    _run_phase("Wave Sequencing sheet", write_wave_sequencing_sheet, wb, all_interfaces, move_groups)   # NEW-V3.23.89 (make-before-break vs hard cutover; needs move_groups computed just above)
    # Phase 29b: Endpoint Dependencies (NEW-V3.23.96). Needs both endpoint_identity (Phase 15b) and
    # move_groups (just above); compute once -> sheet + snapshot (one source of truth).
    endpoint_dependencies = _run_phase("Endpoint dependencies", compute_endpoint_dependencies,
                                       endpoint_identity, move_groups, _default={})
    _run_phase("Endpoint Dependencies sheet", write_endpoint_dependencies_sheet, wb, endpoint_dependencies)
    # Phase 29c: Subnet & routing reachability (NEW-V3.23.97). Full route table (transient) + SVIs +
    # move_groups -> per-device destination/reachable + per-group source<->destination; compute once.
    subnet_intelligence = _run_phase("Subnet intelligence", compute_subnet_intelligence,
                                     all_interfaces, all_routes_full, move_groups, all_bgp_received,
                                     _default={})
    _run_phase("Subnet Reachability sheet", write_subnet_reachability_sheet, wb, subnet_intelligence)
    # Phase 29d: Migration scenarios (NEW-V3.23.98). Synthesise readiness + wave sequencing + health
    # bands into a per-group cutover-scenario recommendation; compute once -> sheet + snapshot. Local
    # import of compute_wave_sequencing keeps it out of this module's namespace (test_package contract).
    from cisco_toolkit.analyze import compute_wave_sequencing as _compute_ws
    _ws_seq = _compute_ws(all_interfaces, move_groups)
    migration_scenarios = _run_phase("Migration scenarios", compute_migration_scenarios,
                                     migration_readiness, _ws_seq, health_scores, _default={})
    _run_phase("Migration Scenarios sheet", write_migration_scenarios_sheet, wb, migration_scenarios)

    # Phase 30: Score Sensitivity - NEW-V3.23.5 (OAT robustness sweep over scoring weights)
    logger.info("\n[Phase 30] Writing Score Sensitivity sheet ...")
    score_sensitivity = _run_phase("Score Sensitivity", compute_score_sensitivity,
                                   all_interfaces, physical_health, l3_forwarding,
                                   cross_layer, protocol_health, _default=[],
                                   security=all_security)
    _run_phase("Score Sensitivity sheet", write_score_sensitivity_sheet, wb, score_sensitivity)

    # Phase 30b: Score Calibration - NEW-V3.23.47 (fleet band-discrimination diagnostic + re-banding suggestion)
    calibration = _run_phase("Score Calibration", compute_calibration_report, health_scores, _default={})
    _run_phase("Score Calibration sheet", write_calibration_sheet, wb, calibration)

    # Phase 30c: NAT Inventory - NEW-V3.23.50 (every static/dynamic NAT rule the migration must recreate)
    _run_phase("NAT Inventory sheet", write_nat_sheet, wb, all_nat)
    _run_phase("Config Compliance sheet", write_security_sheet, wb, all_security)
    _run_phase("Config Hygiene sheet", write_config_hygiene_sheet, wb, all_config_hygiene)
    _run_phase("STP Root Bridges sheet", write_stp_roots_sheet, wb, all_stp_roots, all_interfaces)

    # Phase 30d: Migration Punch-List - NEW-V3.23.63 (consolidated, severity-ranked fix-this-first roll-up);
    # V3.23.64 folds in the cross-switch L2 checks (addressing / FHRP / trunk-native / link duplex-speed).
    _stp_findings = stp_root_findings(all_stp_roots, all_interfaces)
    _l2 = {"addressing": compute_addressing_conflicts(all_interfaces),
           "fhrp": compute_fhrp_consistency(all_interfaces),
           "trunk_native": compute_trunk_native_mismatches(all_interfaces),
           "link_phy": compute_duplex_speed_mismatches(all_interfaces)}
    _hostname_mismatches = compute_hostname_mismatches(all_device_physical)   # NEW-V3.23.68
    _drift = _run_phase("Operational drift", compute_operational_drift,
                        all_interfaces, all_device_physical, _default=[])      # NEW-V3.23.93 (false-health)
    _ptp_readiness = _run_phase("PTP readiness", compute_ptp_readiness, service_map, _default=[])  # NEW-V3.23.108
    # NEW-V3.23.115: fold the media-fabric findings (MAC-aliasing / IGMP querier gaps) into the punch-list;
    # PTP is already folded via _ptp_readiness, so exclude the ptp-dormant risk to avoid a duplicate item.
    _media_risks = [r for r in ((multicast_intelligence or {}).get("risks") or [])
                    if r.get("kind") in ("mac-alias", "querier-gap")]
    # NEW-V3.23.117: lifecycle risk is kept as its OWN axis (sheet / cockpit / runbook §4.1), NOT folded into
    # the punch-list -- its band is date-relative, which would make the frozen golden punch-list date-dependent.
    punchlist = _run_phase("Migration Punch-List", compute_migration_punchlist,
                           cross_layer, all_security, all_config_hygiene, physical_health,
                           l3_forwarding, protocol_health, _stp_findings, health_scores, move_groups,
                           l2=_l2, hostname_mismatches=_hostname_mismatches, drift=_drift,
                           ptp_readiness=_ptp_readiness, media_risks=_media_risks, _default=[])
    _run_phase("Migration Punch-List sheet", write_punchlist_sheet, wb, punchlist)

    # Phase 30d-ter: Remediation Plan - NEW-V3.23.116. The assess->act layer: turn the SAME structured finding
    # sources into per-device, platform-tagged, copy-pasteable Cisco config snippets (review-only). Reuses
    # the _l2 bundle / _stp_findings / hygiene / security / multicast_intelligence already computed above.
    _dev_platform = {dp.hostname: {"platform": dp.platform} for dp in all_device_physical}
    remediation_plan = _run_phase("Remediation plan", compute_remediation_plan,
                                  _dev_platform, _l2, _stp_findings, all_config_hygiene, all_security,
                                  multicast_intelligence, move_groups, _default={})
    _run_phase("Remediation Plan sheet", write_remediation_plan_sheet, wb, remediation_plan)

    # Phase 30d-quater: Cutover VALIDATION plan - NEW-V3.23.143 (assess->ACT->verify). From the current-state
    # topology, generate the per-wave checks an engineer runs after each cutover to PROVE it worked -- gateway
    # up, FHRP healthy, endpoints reach their gateway, routing adjacencies re-established, STP root unchanged,
    # port-channels bundled - each with the expected good result captured from the pre-cutover state. Pure
    # synthesis of already-collected data; compute once -> sheet + snapshot (one source of truth).
    validation_plan = _run_phase("Validation plan", compute_validation_plan,
                                 all_interfaces, move_groups, all_routing_neighbors, all_stp_roots,
                                 _dev_platform, _default={})
    _run_phase("Cutover Validation sheet", write_validation_plan_sheet, wb, validation_plan)

    # Phase 30d-quinquies: Golden-config DRIFT - NEW-V3.23.146. Per-device running-config drift vs a baseline:
    # the user's --golden-config file (required directives) if supplied, else the fleet's auto-derived MAJORITY
    # baseline (de-facto standard) -> flag the outliers. Compute once -> sheet + snapshot (one source of truth).
    _golden_lines = None
    if args.golden_config:
        try:
            with open(args.golden_config, encoding="utf-8") as f:
                _golden_lines = f.read().splitlines()
            logger.info(f"[Phase 30d] Golden-config baseline: {len(_golden_lines)} line(s) from {args.golden_config}")
        except OSError as e:
            logger.warning(f"  --golden-config not read ({e}); falling back to the auto-derived majority baseline.")
    golden_drift = _run_phase("Golden-config drift", compute_golden_drift,
                              all_run_configs, _golden_lines, _default={})
    _run_phase("Golden-Config Drift sheet", write_golden_drift_sheet, wb, golden_drift)

    # Phase 30d-bis: Application Intelligence - NEW-V3.23.112. Synthesize endpoint_identity +
    # endpoint_dependencies + service_map + health_scores + move_groups + punchlist into named
    # application DOMAINS (workloads) with footprint, criticality tier, health rollup, migration-wave
    # span, and standards-grounded migration risks (PTP boundary-clock / ST 2059, IGMP querier
    # continuity / RFC 4541, ST 2022-7 dual-path, NEXIS dual-leg). Pure synthesis of already-computed
    # records; compute once -> sheet + snapshot (one source of truth).
    application_intelligence = _run_phase("Application intelligence", compute_application_intelligence,
                                          all_interfaces, endpoint_identity, endpoint_dependencies,
                                          service_map, health_scores, move_groups, punchlist,
                                          subnet_intelligence=subnet_intelligence, _default={})
    _run_phase("Application Intelligence sheet", write_application_intelligence_sheet, wb, application_intelligence)
    # Phase 30d-bis2: Segmentation / isolation audit (NEW-V3.23.118). L3 isolation posture per application
    # domain (VRF separation + gateway-ACL coverage) from the gateway SVIs + the domain map. Compute once ->
    # sheet + snapshot.
    segmentation = _run_phase("Segmentation audit", compute_segmentation,
                              all_interfaces, application_intelligence, _default={})
    _run_phase("Segmentation sheet", write_segmentation_sheet, wb, segmentation)

    # Phase 30e: Executive Summary - NEW-V3.23.75 (one-page synthesis, landed as the FIRST workbook tab)
    logger.info("\n[Phase 30e] Writing Executive Summary sheet ...")
    # NEW-V3.23.120: the cross-axis migration brief -- one headline per assessment axis (the 7 new axes +
    # health + punch-list + readiness) rolled up into one decision-grade synthesis. Compute once -> the
    # Executive Summary sheet leads with it + snapshot.
    executive_brief = _run_phase("Executive brief", compute_executive_brief,
                                 health_scores, punchlist, migration_readiness, application_intelligence,
                                 lifecycle_risk, segmentation, multicast_intelligence, remediation_plan,
                                 _default={})
    _run_phase("Executive Summary sheet", write_executive_summary_sheet, wb,
               health_scores, punchlist, migration_readiness, failure_impact,   # NEW-V3.23.91: reuse precomputed fi
               brief=executive_brief)
    _run_phase("Protocol Boundaries sheet", write_protocol_boundaries_sheet, wb, all_routing_neighbors, all_redistribution)
    _run_phase("Addressing Conflicts sheet", write_addressing_conflicts_sheet, wb, all_interfaces)
    _run_phase("FHRP Consistency sheet", write_fhrp_consistency_sheet, wb, all_interfaces)
    _run_phase("Trunk Native-VLAN sheet", write_trunk_native_sheet, wb, all_interfaces)
    _run_phase("Link Duplex-Speed sheet", write_link_phy_sheet, wb, all_interfaces)

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
    snap_dict["protocol_intelligence"] = protocol_intelligence       # NEW-V3.23.100 (per-(switch,protocol,state) cause + remediation; reused from Phase 27b)
    snap_dict["service_map"] = service_map                           # NEW-V3.23.101 (L4 services from ACL ports + multicast activity; reused from Phase 27c)
    snap_dict["multicast_intelligence"] = multicast_intelligence     # NEW-V3.23.115 (media-fabric deep-dive; reused from Phase 27c-bis)
    snap_dict["lifecycle_risk"] = lifecycle_risk                     # NEW-V3.23.117 (hardware EoL band per device; reused from Phase 27c-ter)
    snap_dict["remediation_plan"] = remediation_plan                 # NEW-V3.23.116 (generated config snippets, review-only; reused from Phase 30d-ter)
    snap_dict["validation_plan"] = validation_plan                   # NEW-V3.23.143 (per-wave post-cutover validation checklist; reused from Phase 30d-quater)
    snap_dict["golden_drift"] = golden_drift                         # NEW-V3.23.146 (per-device config drift vs baseline; reused from Phase 30d-quinquies)
    snap_dict["collection_completeness"] = collection_completeness   # NEW-V3.23.109 (pre-assessment blind-spot report; reused from Phase 27d)
    snap_dict["health_scores"] = health_scores                       # NEW-V3.23
    snap_dict["migration_readiness"] = migration_readiness           # NEW-V3.23
    snap_dict["score_sensitivity"] = score_sensitivity               # NEW-V3.23.5
    snap_dict["nat"] = all_nat                                       # NEW-V3.23.50 (NAT inventory: {host:{static,dynamic,pools,inside,outside}})
    snap_dict["security"] = all_security                            # NEW-V3.23.59 (CIS-aligned security posture: {host:{findings,summary}})
    snap_dict["config_hygiene"] = all_config_hygiene                # NEW-V3.23.61 (undefined refs / unused structures: {host:{undefined,unused,summary}})
    snap_dict["stp_roots"] = all_stp_roots                          # NEW-V3.23.62 (per-VLAN STP root bridge: {host:{vlan:{root_priority,root_address,is_root}}})
    snap_dict["vpc"] = all_vpc                                       # NEW-V3.23.125 (vPC / MLAG status: {host:{domain_id,role,peer_status,vpcs}}) -> confirms MLAG peers in the flow simulator
    snap_dict["punchlist"] = punchlist                              # NEW-V3.23.63 (consolidated severity-ranked migration punch-list)
    snap_dict["operational_drift"] = _drift                         # NEW-V3.23.93 (false-health / operational-drift findings; also folded into the punch-list)
    snap_dict["calibration"] = calibration                           # NEW-V3.23.47 (fleet band-discrimination diagnostic)
    snap_dict["acls"] = all_acls                                     # NEW (L4 ACL sim): {host:{name:[rule,...]}}
    snap_dict["object_groups"] = all_object_groups                  # NEW (L4 depth): {host:{name:{kind,members}}}
    snap_dict["routes"] = all_routes                                # NEW (route-aware reachability): {host:[{prefix,source,next_hop,out_intf}]}
    snap_dict["routing_neighbors"] = all_routing_neighbors          # NEW (protocol-to-protocol analysis): {host:{ospf:[...],eigrp:[...],bgp:[...]}}
    snap_dict["redistribution"] = all_redistribution                # NEW (protocol-to-protocol analysis): {host:[{into_proto,into_id,from_proto,from_id,route_map,raw}]}
    # NEW-V3.23.81: embed the causality chains + failure-impact rollup the workbook computes, so the
    # explorer's Causality mode + cockpit keystones consume the SAME analysis instead of re-deriving in JS
    # (one source of truth). NEW-V3.23.91: REUSE the values already computed for the Phase 19/20 sheets
    # (causality_chains / failure_impact) instead of recomputing here -- this snapshot phase was the main
    # source of the duplicate heavy walks. Tuples -> dicts for a self-describing JSON contract. Local
    # import (link_centrality / wave_sequencing only) keeps those out of this module's public surface.
    from cisco_toolkit.analyze import compute_link_centrality, compute_wave_sequencing
    snap_dict["causality"] = [{"severity": s, "trigger": t, "mechanism": m, "impact": i, "mitigation": mt,
                               "hosts": list(hosts)}                            # NEW-V3.23.92: explicit host list (one source of truth; explorer highlights these directly)
                              for (s, t, m, i, mt, hosts) in (causality_chains or [])]
    snap_dict["failure_impact"] = failure_impact
    snap_dict["link_centrality"] = compute_link_centrality(all_interfaces)   # NEW-V3.23.88 (chokepoint links: betweenness + bridges; LINK twin of failure_impact)
    snap_dict["wave_sequencing"] = compute_wave_sequencing(all_interfaces, move_groups)   # NEW-V3.23.89 (per-group make-before-break vs hard cutover)
    # NEW-V3.23.84: embed the 4 cross-switch L2/L3 consistency checks the workbook computes, so the
    # explorer consumes the SAME analysis instead of re-deriving in JS (one source of truth). These
    # compute_* fns are already imported at module level (V3.23.64, also used to build the punch-list
    # above), so no local re-import is needed — and adding one would shadow that earlier use.
    snap_dict["addressing_conflicts"] = compute_addressing_conflicts(all_interfaces)
    snap_dict["fhrp"] = compute_fhrp_consistency(all_interfaces)
    snap_dict["trunk_native"] = compute_trunk_native_mismatches(all_interfaces)
    snap_dict["link_phy"] = compute_duplex_speed_mismatches(all_interfaces)
    snap_dict["move_groups"] = move_groups                           # NEW-V3.23.86 (Migration Waves mode: the move-group / shared-VLAN-domain structure the readiness verdicts attach to; already computed above for migration_readiness)
    snap_dict["capacity"] = compute_capacity(all_device_physical)    # NEW-V3.23.87 (port + PoE headroom: same fn that drives the 'Capacity' sheet -> explorer + workbook agree)
    snap_dict["endpoint_identity"] = endpoint_identity               # NEW-V3.23.95 (per-endpoint vendor + inferred class; reused from the Phase 15b compute)
    snap_dict["endpoint_dependencies"] = endpoint_dependencies       # NEW-V3.23.96 (clusters / dual-homed / VLAN tiers / per-switch validation; reused from Phase 29b)
    snap_dict["subnet_intelligence"] = subnet_intelligence           # NEW-V3.23.97 (per-device subnet source/destination + move-group reachability; reused from Phase 29c)
    snap_dict["migration_scenarios"] = migration_scenarios           # NEW-V3.23.98 (per-group cutover scenario recommendation; reused from Phase 29d)
    snap_dict["application_intelligence"] = application_intelligence  # NEW-V3.23.112 (application-domain synthesis + migration risk; reused from Phase 30d-bis)
    snap_dict["segmentation"] = segmentation                         # NEW-V3.23.118 (L3 isolation posture; reused from Phase 30d-bis2)
    snap_dict["executive_brief"] = executive_brief                   # NEW-V3.23.120 (cross-axis migration brief; reused from Phase 30e)
    if flow_trace is not None:                                       # NEW-V3.19
        snap_dict["flow_trace"] = flow_trace
    if args.redact:                                                  # NEW-V3.23.41
        snap_dict = redact_snapshot(snap_dict)
        logger.info("  [redact] snapshot IPs / MACs / serials pseudonymized (--redact)")
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

    # Phase 31: Assessment & Migration Runbook (DOCX) - NEW-V3.23.93. The narrative sign-off twin of
    # the workbook, built from the SAME snap_dict (one source of truth -> every number agrees), to the
    # cisco-network-assessment 12-section, evidence-disciplined standard. Optional (python-docx); a
    # missing library is a warning, never a crash (the workbook / explorer / JSON already saved).
    if not args.no_docx:
        docx_out = os.path.splitext(os.path.abspath(out_xlsx))[0] + "_runbook.docx"
        label = os.path.splitext(os.path.basename(out_xlsx))[0]
        try:
            write_runbook_docx(docx_out, snap_dict, label, flow_paths=flow_paths)
        except Exception as e:
            logger.warning(f"  Runbook (DOCX) write failed: {e}")

    # NEW-V3.23.144: Executive presentation deck (PPTX) - the stakeholder twin of the workbook, rendered
    # from the same snapshot. Optional python-pptx; a missing library is a warning, never a crash.
    if not args.no_pptx:
        pptx_out = os.path.splitext(os.path.abspath(out_xlsx))[0] + "_executive_deck.pptx"
        label = os.path.splitext(os.path.basename(out_xlsx))[0]
        try:
            write_executive_deck_pptx(pptx_out, snap_dict, label)
        except Exception as e:
            logger.warning(f"  Executive deck (PPTX) write failed: {e}")

    # Phase 33: As-Built Network Design Document (HLD/LLD, DOCX) - NEW-V3.23.148. The Design-phase twin
    # of the workbook: reconstructs the current (as-built) design + target-state recommendations from the
    # SAME snapshot (one source of truth). Optional python-docx; a missing library is a warning, never a crash.
    if not args.no_design:
        design_out = os.path.splitext(os.path.abspath(out_xlsx))[0] + "_design.docx"
        label = os.path.splitext(os.path.basename(out_xlsx))[0]
        try:
            write_design_doc_docx(design_out, snap_dict, label)
        except Exception as e:
            logger.warning(f"  Design document (DOCX) write failed: {e}")

    # Phase 34: per-wave Method of Procedure (MOP, DOCX) - NEW-V3.23.149. The Implement-phase cutover
    # template, one section per migration wave, reusing the validation plan as the post-cutover checks.
    # Optional python-docx; a missing library is a warning, never a crash.
    if not args.no_mop:
        mop_out = os.path.splitext(os.path.abspath(out_xlsx))[0] + "_mop.docx"
        label = os.path.splitext(os.path.basename(out_xlsx))[0]
        try:
            write_mop_docx(mop_out, snap_dict, label)
        except Exception as e:
            logger.warning(f"  MOP (DOCX) write failed: {e}")


if __name__ == "__main__":
    main()
