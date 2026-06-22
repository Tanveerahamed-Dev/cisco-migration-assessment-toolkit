"""The model-construction layer: build the per-device InterfaceData table, the
DevicePhysical / switch-identity records, and the global-ARP enrichment from
already-collected show output. Depends on cmdio (loading), parse (parsers), model, and
textutils - a layer above those, independent of analyze/excel. Extracted verbatim from
COLLECT_PARSE_V3_23_0.py across PHASE 2.7 steps 27-28 (behaviour byte-identical):
step 27 = the switch-level builders + ARP enrichment, step 28 = build_interfaces."""
import ipaddress
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from cisco_toolkit.cmdio import _load_cmd_output, _safe_parse
from cisco_toolkit.model import DevicePhysical, InterfaceData
from cisco_toolkit.parse import (
    _compress_vlans, infer_endpoint_type, parse_etherchannel_protocol_ios,
    parse_etherchannel_summary_members, parse_glbp_summary, parse_hsrp_detail, parse_hsrp_summary,
    parse_ip_routes, parse_multicast_info, parse_neighbors_cdp, parse_neighbors_lldp,
    parse_portchannel_protocol_from_summary, parse_run_config_interfaces,
    parse_show_environment, parse_show_environment_power, _parse_poe_inline_budget,
    parse_show_interface_status,
    parse_show_interface_switchport, parse_show_interface_trunk_table, parse_show_inventory,
    parse_show_ip_arp, parse_show_mac_address_table, parse_show_module_count,
    parse_show_power_inline, parse_show_version, parse_show_vrf_interface,
    parse_spanning_tree_blockedports, parse_spanning_tree_detail, parse_spanning_tree_states,
    parse_spanning_tree_root, parse_vpc, parse_nve_peers, parse_evpn_summary, parse_nve_vni, parse_copp_drops,
    parse_bgp_vpnv4_summary, parse_mpls_ldp_neighbors, parse_mpls_l2vpn_vc,   # SP/MPLS: L3VPN VPNv4 / LDP underlay / L2VPN pseudowire
    parse_lisp_sessions, parse_cts_environment_data, parse_dmvpn_peers, parse_crypto_sessions, parse_bfd_neighbors, parse_ipv6_interface_addrs, parse_ipv6_route_summary, parse_ospfv3_neighbors, parse_bgp_ipv6_summary,   # universal arch coverage: SD-Access/CTS/DMVPN/IPsec/BFD/IPv6
    parse_aci_faults, parse_aci_fabric_nodes, parse_aci_health, parse_aci_vrfs,   # Cisco ACI (APIC JSON-ingestion channel)
    parse_aci_tenants, parse_aci_bds, parse_aci_epgs,                # Cisco ACI logical census (tenant/BD/EPG move-group units)
    parse_sdwan_control_connections, parse_sdwan_devices, parse_sdwan_omp_counters,   # Cisco Catalyst SD-WAN (vManage JSON channel)
    parse_pim_rp_mapping, parse_pim_neighbors,                        # PIM-SM control plane (RP / neighbor)
    parse_ipv6_raguard_policy, parse_ipv6_dhcp_guard_policy,          # IPv6 first-hop security (RA-Guard / DHCPv6-Guard)
    parse_ntp_status,                                                 # NTP clock-sync STATE (stratum 16 / unsynchronized)
    parse_port_security_detail,                                       # access-edge port-security DETAIL (Secure-shutdown)
    parse_storm_control,                                             # storm-control action (toothless 'None' rule)
    parse_policymap_drops,                                           # QoS runtime: egress queue/policer drops
    parse_neighbors_detail,                                          # CDP/LLDP detail w/ capability codes (shadow infra)
    parse_switch_mgmt_ip, parse_vlan_brief, parse_vrrp_summary, parse_vtp_status,
    parse_acls, parse_object_groups, parse_nat, parse_security, parse_config_hygiene,
    parse_cpu_utilization, parse_memory_stats, parse_system_resources,   # NEW-V3.23.167 (platform health)
    parse_ospf_neighbors, parse_eigrp_neighbors, parse_bgp_summary,   # protocol-to-protocol analysis
    parse_redistribution,                                            # protocol-to-protocol analysis (slice 2)
    parse_bgp_table,                                                 # NEW-V3.23.97 (BGP received prefixes)
    parse_igmp_groups, parse_igmp_snooping_querier, parse_ptp_clock, parse_acl_hitcounts,  # NEW-V3.23.102
)
from cisco_toolkit.textutils import PHYSICAL_IFACE_RE, detect_link_type, normalize_ifname

logger = logging.getLogger(__name__)


def read_run_config(cmd_to_file: Dict[str, str]) -> str:
    """Return this device's raw 'show running-config' text (offline-loaded), or '' when absent.
    Used by the golden-config drift check (compute_golden_drift). Fail-soft."""
    return _load_cmd_output(cmd_to_file, "show running-config") or ""


def read_syslog_log(cmd_to_file: Dict[str, str]) -> str:
    """NEW-V3.23.164: return this device's raw log-buffer text (offline-loaded), or ''
    when absent / a Cisco error. V3.23.170: NX-OS rejects the bare 'show logging'
    ('% Incomplete command' -- its buffer lives under 'show logging logfile'), so the
    logfile form is tried FIRST: on platform variants where the bare form prints only
    the logging CONFIGURATION (no events), preferring it would score the device as
    collected-but-quiet. Used by the syslog-intelligence axis. Fail-soft."""
    return _load_cmd_output(cmd_to_file, "show logging logfile", "show logging") or ""


def build_platform_metrics(cmd_to_file: Dict[str, str]) -> dict:
    """NEW-V3.23.167: parse this device's control-plane capacity facts from the
    already-collected output -> {cpu, memory, system} where cpu =
    parse_cpu_utilization('show processes cpu'), memory = parse_memory_stats
    ('show processes memory'), system = parse_system_resources('show system
    resources', NX-OS). Each member {} when its command is absent; all-{} =
    not collected. Fail-soft via _safe_parse."""
    return {
        "cpu": _safe_parse(parse_cpu_utilization,
                           _load_cmd_output(cmd_to_file, "show processes cpu")) or {},
        "memory": _safe_parse(parse_memory_stats,
                              _load_cmd_output(cmd_to_file, "show processes memory")) or {},
        "system": _safe_parse(parse_system_resources,
                              _load_cmd_output(cmd_to_file, "show system resources")) or {},
    }


def build_acls(cmd_to_file: Dict[str, str]) -> Dict[str, List[dict]]:
    """Parse ACL definitions (L4 allow/deny sim) from this device's already-collected
    'show running-config' -> {acl_name: [rule,...]}; {} when none. Fail-soft via _safe_parse."""
    run = _load_cmd_output(cmd_to_file, "show running-config")
    return _safe_parse(parse_acls, run) or {}


def build_object_groups(cmd_to_file: Dict[str, str]) -> Dict[str, dict]:
    """Parse object-group definitions (L4 depth) from this device's already-collected
    'show running-config' -> {name: {kind, members}}; {} when none. Fail-soft via _safe_parse."""
    run = _load_cmd_output(cmd_to_file, "show running-config")
    return _safe_parse(parse_object_groups, run) or {}


def build_nat(cmd_to_file: Dict[str, str]) -> dict:
    """Parse the NAT inventory (static / dynamic / pools / inside-outside ifaces) from this device's
    already-collected 'show running-config' -> {static,dynamic,pools,inside,outside}; {} when none.
    Fail-soft via _safe_parse."""
    run = _load_cmd_output(cmd_to_file, "show running-config")
    return _safe_parse(parse_nat, run) or {}


def build_security(cmd_to_file: Dict[str, str]) -> dict:
    """Parse the CIS-aligned security/compliance posture (weak credentials, insecure SNMP/telnet,
    risky services, missing baseline hardening) from this device's already-collected
    'show running-config' -> {findings:[...], summary:{...}}; {} when no run-config. The parser
    redacts every secret value before it reaches the snapshot. Fail-soft via _safe_parse."""
    run = _load_cmd_output(cmd_to_file, "show running-config")
    return _safe_parse(parse_security, run) or {}


def build_config_hygiene(cmd_to_file: Dict[str, str]) -> dict:
    """Batfish-style config hygiene (undefined references + unused structures) parsed from this
    device's already-collected 'show running-config' -> {undefined,unused,summary}; {} when the
    config defines/references no ACL/route-map/object-group/prefix-list. Fail-soft via _safe_parse."""
    run = _load_cmd_output(cmd_to_file, "show running-config")
    return _safe_parse(parse_config_hygiene, run) or {}


def build_stp_roots(cmd_to_file: Dict[str, str]) -> dict:
    """Per-VLAN STP root-bridge info (priority / address / is-this-switch-root) parsed from this
    device's already-collected 'show spanning-tree' -> {vlan:{root_priority,root_address,is_root}};
    {} when none. Powers the accidental-root + root/gateway-misalignment analysis. Fail-soft."""
    return _safe_parse(parse_spanning_tree_root, _load_cmd_output(cmd_to_file, "show spanning-tree")) or {}


def build_vpc(cmd_to_file: Dict[str, str]) -> dict:
    """vPC / MLAG status parsed from this device's already-collected 'show vpc' (NX-OS) ->
    {domain_id, role, peer_status, keepalive_status, vpcs:[...]}; {} when the device runs no vPC.
    Fail-soft. CONFIRMS MLAG peer pairs (vs topology inference) for the flow simulator."""
    return _safe_parse(parse_vpc, _load_cmd_output(cmd_to_file, "show vpc")) or {}


def build_fhrp_detail(cmd_to_file: Dict[str, str]) -> list:
    """Full first-hop-redundancy state for THIS device from 'show standby [all]' DETAIL (parse_hsrp_detail):
    [{ifname, group, state, priority, cfg_priority, preempt, preempt_delay, vip, vmac, standby_ip, track}].
    [] when the device runs no HSRP. The brief form (interface hsrp_behavior) keeps only state+VIP; this
    carries the election / preempt / tracking fields a senior FHRP audit needs (the AJ fleet ran no FHRP,
    so this is the first capability proven on a non-AJ environment). Fail-soft via _safe_parse."""
    d = _safe_parse(parse_hsrp_detail, _load_cmd_output(cmd_to_file, "show standby all", "show standby")) or {}
    return [{"ifname": k[0], "group": k[1], **v} for k, v in d.items()]


def build_overlay(cmd_to_file: Dict[str, str]) -> dict:
    """VXLAN-EVPN overlay state for THIS device from 'show nve peers': {nve_peers:[{interface, peer_ip,
    state, learn_type}]}. {} when the device runs no NVE/VXLAN. The engine's OWN target fabric was blind;
    a down VTEP peer partitions the overlay for every VNI it serves. Fail-soft via _safe_parse."""
    peers = _safe_parse(parse_nve_peers, _load_cmd_output(cmd_to_file, "show nve peers")) or []
    evpn = _safe_parse(parse_evpn_summary, _load_cmd_output(cmd_to_file, "show bgp l2vpn evpn summary")) or []
    vni = _safe_parse(parse_nve_vni, _load_cmd_output(cmd_to_file, "show nve vni")) or []
    out = {}
    if peers: out["nve_peers"] = peers
    if evpn: out["evpn_neighbors"] = evpn
    if vni: out["nve_vni"] = vni
    return out


def build_copp(cmd_to_file: Dict[str, str]) -> list:
    """Control-plane-policing drop state for THIS device from 'show policy-map interface control-plane'
    (NX-OS) or 'show policy-map control-plane' (IOS / IOS-XE), via parse_copp_drops:
    [{class, conformed, exceeded, violated, dropped, drops}]. [] when no CoPP policy. A class with drops > 0
    means the policer is actively discarding punted control-plane traffic. Fail-soft via _safe_parse."""
    return _safe_parse(parse_copp_drops, _load_cmd_output(
        cmd_to_file, "show policy-map interface control-plane", "show policy-map control-plane")) or []


def build_mpls(cmd_to_file: Dict[str, str]) -> dict:
    """SP/MPLS service-plane state for THIS device -> {ldp_neighbors, vpnv4_neighbors, l2vpn_vcs}. Covers the
    three planes an MPLS PE assessment must see: the LDP transport underlay ('show mpls ldp neighbor'), the
    L3VPN control plane ('show bgp vpnv4 unicast summary'), and L2VPN pseudowires ('show mpls l2transport
    vc'). {} when the device runs no MPLS. A not-Oper LDP session, a not-Established VPNv4 peer, or a DOWN
    pseudowire each breaks the service riding it. Fail-soft via _safe_parse."""
    ldp = _safe_parse(parse_mpls_ldp_neighbors, _load_cmd_output(cmd_to_file, "show mpls ldp neighbor")) or []
    vpnv4 = _safe_parse(parse_bgp_vpnv4_summary, _load_cmd_output(cmd_to_file, "show bgp vpnv4 unicast summary")) or []
    l2vc = _safe_parse(parse_mpls_l2vpn_vc, _load_cmd_output(cmd_to_file, "show mpls l2transport vc")) or []
    out = {}
    if ldp:
        out["ldp_neighbors"] = ldp
    if vpnv4:
        out["vpnv4_neighbors"] = vpnv4
    if l2vc:
        out["l2vpn_vcs"] = l2vc
    return out


def build_aci(cmd_to_file: Dict[str, str]) -> dict:
    """Cisco ACI controller-fabric state for THIS query host from an offline APIC export -> {faults, nodes,
    health}. This is the JSON-INGESTION channel: ACI/APIC fabrics are not assessable via device 'show' text,
    so a read-only APIC export (moquery -o json / REST /api/class/*.json saved into the collection dir) is
    read through the SAME _load_cmd_output path and json-normalized (no regex). A raised/unacknowledged
    critical-or-major faultInst, a fabricNode whose fabricSt is not active, or a degraded fabricHealthTotal
    are present, controller-reported broken-states. {} when no ACI export is present (a non-ACI fleet never
    fires). Fail-soft via _safe_parse."""
    faults = _safe_parse(parse_aci_faults, _load_cmd_output(cmd_to_file, "moquery -c faultInst")) or []
    nodes = _safe_parse(parse_aci_fabric_nodes, _load_cmd_output(cmd_to_file, "moquery -c fabricNode")) or []
    health = _safe_parse(parse_aci_health, _load_cmd_output(cmd_to_file, "moquery -c fabricHealthTotal")) or {}
    vrfs = _safe_parse(parse_aci_vrfs, _load_cmd_output(cmd_to_file, "moquery -c fvCtx")) or []
    # logical census (move-group-scoping inventory; not broken-states): tenants / bridge-domains / EPGs.
    tenants = _safe_parse(parse_aci_tenants, _load_cmd_output(cmd_to_file, "moquery -c fvTenant")) or []
    bds = _safe_parse(parse_aci_bds, _load_cmd_output(cmd_to_file, "moquery -c fvBD")) or []
    epgs = _safe_parse(parse_aci_epgs, _load_cmd_output(cmd_to_file, "moquery -c fvAEPg")) or []
    out = {}
    if faults:
        out["faults"] = faults
    if nodes:
        out["nodes"] = nodes
    if health:
        out["health"] = health
    if vrfs:
        out["vrfs"] = vrfs
    if tenants:
        out["tenants"] = tenants
    if bds:
        out["bds"] = bds
    if epgs:
        out["epgs"] = epgs
    return out


def build_sdwan(cmd_to_file: Dict[str, str]) -> dict:
    """Cisco Catalyst SD-WAN (vManage / SD-WAN Manager) overlay state for THIS query host from an offline
    vManage export -> {control_connections, devices}. The JSON-ingestion channel (the overlay state lives in
    the Manager's NMS database, not the edge CLI): GET /dataservice/device/control/connections and
    /dataservice/device, saved into the collection dir, are read through the SAME _load_cmd_output path and
    json-normalized. A control connection that is down (or actual < expected) or a device the Manager reports
    unreachable is a present broken-state. {} when no SD-WAN export is present. Fail-soft via _safe_parse."""
    conns = _safe_parse(parse_sdwan_control_connections,
                        _load_cmd_output(cmd_to_file, "dataservice/device/control/connections")) or []
    devs = _safe_parse(parse_sdwan_devices, _load_cmd_output(cmd_to_file, "dataservice/device")) or []
    omp = _safe_parse(parse_sdwan_omp_counters, _load_cmd_output(cmd_to_file, "dataservice/device/counters")) or []
    out = {}
    if conns:
        out["control_connections"] = conns
    if devs:
        out["devices"] = devs
    if omp:
        out["omp_counters"] = omp
    return out


def build_lisp(cmd_to_file: Dict[str, str]) -> dict:
    """Cisco SD-Access LISP fabric control-plane state for THIS device -> {sessions:[per-VRF blocks]}. Reads
    'show lisp session' (IOS-XE): each fabric edge/border opens a reliable-transport session to every control-
    plane node (map-server / map-resolver, port 4342) over which it registers and resolves EID-to-RLOC mappings.
    The published per-VRF summary (total / established) lets _d_lisp_fabric_session_down fire ONLY when a VRF has
    sessions configured (total>=1) yet ZERO established -- a genuine fabric control-plane partition for that node
    -- while a benign single Down peer (idle border/edge) keeps established>=1 and stays silent. {} when the
    device runs no SD-Access / LISP. Fail-soft via _safe_parse."""
    sessions = _safe_parse(parse_lisp_sessions,
                           _load_cmd_output(cmd_to_file, "show lisp session"), _default=[]) or []
    out = {}
    if sessions:
        out["sessions"] = sessions
    return out


def build_cts(cmd_to_file: Dict[str, str]) -> dict:
    """Cisco TrustSec environment-data download state for THIS device -> {environment_data: {...}} or {}.
    'show cts environment-data' reports the state machine that pulls the SGT->name table / SGACL policy from
    Cisco ISE; the env-data download is the prerequisite for ANY group-based (SGT/SGACL) enforcement. {} when
    the device runs no CTS (command absent / not configured) -- coverage-honest, so a non-TrustSec fleet never
    fires. A 'Current state' that is not COMPLETE means the SGT-to-policy data is stale or was never
    downloaded, so segmentation is blind/unenforced. Fail-soft via _safe_parse."""
    env = _safe_parse(parse_cts_environment_data,
                      _load_cmd_output(cmd_to_file, "show cts environment-data")) or {}
    out = {}
    if env:
        out["environment_data"] = env
    return out


def build_dmvpn(cmd_to_file: Dict[str, str]) -> dict:
    """DMVPN WAN-overlay (mGRE/NHRP) state for THIS device -> {peers: [{interface, nbma, tunnel_ip, state,
    attrb}]}. Reads 'show dmvpn' (IOS / IOS-XE only -- DMVPN is not an NX-OS feature, so a Nexus box simply has
    no capture and publishes {}). A peer whose State is not UP (NHRP / IKE / down) is a broken spoke/hub tunnel:
    no overlay forwarding to that site. {} when the device runs no DMVPN. Fail-soft via _safe_parse."""
    peers = _safe_parse(parse_dmvpn_peers, _load_cmd_output(cmd_to_file, "show dmvpn")) or []
    out = {}
    if peers:
        out["peers"] = peers
    return out


def build_crypto(cmd_to_file: Dict[str, str]) -> dict:
    """IPsec encrypted-WAN session state for THIS device -> {sessions: [{interface, peer, status}]}. Reads
    'show crypto session' (IOS / IOS-XE site-to-site IPsec, crypto-map or VTI). Each entry is one IKE/IPsec
    peering; a status that begins with DOWN (DOWN / DOWN-NEGOTIATING) means the IKE/IPsec SA is not
    established, so the encrypted tunnel is down. {} when the device runs no IPsec (no sessions parsed).
    Fail-soft via _safe_parse."""
    sessions = _safe_parse(parse_crypto_sessions, _load_cmd_output(cmd_to_file, "show crypto session")) or []
    out = {}
    if sessions:
        out["sessions"] = sessions
    return out


def build_bfd(cmd_to_file: Dict[str, str]) -> dict:
    """BFD fast-failover session state for THIS device -> {sessions: [{neighbor, local_disc, remote_disc,
    state, interface}]}. BFD provides sub-second forwarding-path failure detection for its client protocols
    (OSPF/BGP/EIGRP/HSRP/static); a session in the Down state means that fast-failover is broken and the
    client has fallen back to its native (multi-second) convergence timers. {} when the device runs no BFD
    (so a non-BFD box never publishes the axis and the detector stays silent). Fail-soft via _safe_parse."""
    sessions = _safe_parse(parse_bfd_neighbors, _load_cmd_output(cmd_to_file, "show bfd neighbors")) or []
    out = {}
    if sessions:
        out["sessions"] = sessions
    return out


def build_ipv6_nd(cmd_to_file: Dict[str, str]) -> dict:
    """IPv6 addressing / neighbor-discovery readiness for THIS device from 'show ipv6 interface'
    (parse_ipv6_interface_addrs) -> {interfaces:[{interface, admin_up, proto_up, ipv6_enabled, link_local,
    link_local_dup, global:[{addr, subnet, dad_state}]}]}. {} when the device shows no IPv6 at all -- a pure
    IPv4 box contributes nothing and the DAD detector never cries wolf over it. A global address in dad_state
    'duplicate' (or a duplicate link-local) is the OBSERVED broken state: DAD positively detected an address
    clash, so Cisco set the address to DUPLICATE and stopped using it -- a hard L3 fault on a dual-stack
    interface. Fail-soft via _safe_parse."""
    ifaces = _safe_parse(parse_ipv6_interface_addrs,
                         _load_cmd_output(cmd_to_file, "show ipv6 interface")) or []
    out = {}
    if ifaces:
        out["interfaces"] = ifaces
    return out


def build_ipv6_routing(cmd_to_file: Dict[str, str]) -> dict:
    """IPv6 routing-plane state for THIS device -> {route_summary, ospfv3_neighbors, bgp_ipv6_neighbors}. Covers the
    dual-stack reachability control plane: the IPv6 RIB census ('show ipv6 route summary', the routing-active GATE),
    OSPFv3 adjacencies ('show ospfv3 neighbor'), and IPv6 BGP peers ('show bgp ipv6 unicast summary'). {} when the
    device runs no IPv6 routing at all -> a pure-IPv4 box contributes nothing and the detector never cries wolf. An
    OSPFv3 neighbor stuck in a transient state (not FULL and not 2WAY), or an IPv6 BGP peer not Established, each
    means that dual-stack adjacency exchanges no IPv6 routes. Fail-soft via _safe_parse."""
    rsum = _safe_parse(parse_ipv6_route_summary,
                       _load_cmd_output(cmd_to_file, "show ipv6 route summary")) or {}
    ospfv3 = _safe_parse(parse_ospfv3_neighbors,
                         _load_cmd_output(cmd_to_file, "show ospfv3 neighbor", "show ipv6 ospf neighbor")) or []
    bgp6 = _safe_parse(parse_bgp_ipv6_summary,
                       _load_cmd_output(cmd_to_file, "show bgp ipv6 unicast summary")) or []
    out = {}
    if rsum:
        out["route_summary"] = rsum
    if ospfv3:
        out["ospfv3_neighbors"] = ospfv3
    if bgp6:
        out["bgp_ipv6_neighbors"] = bgp6
    return out


def build_pim(cmd_to_file: Dict[str, str]) -> dict:
    """PIM-SM control-plane facts for the multicast-resilience detector -> {rp_mapping, neighbors}:
      rp_mapping = parse_pim_rp_mapping('show ip pim rp mapping')  -- learned-RP summary
                   ({} when uncollected; {present, rp_count, rps, groups, ssm_only} otherwise)
      neighbors  = parse_pim_neighbors('show ip pim neighbor')     -- [{neighbor, interface, uptime}]
    'PIM running but no RP' (rp_mapping.present True, rp_count 0) is distinct from 'PIM not collected'
    ({}). Fail-soft via _safe_parse."""
    return {
        "rp_mapping": _safe_parse(parse_pim_rp_mapping,
                                  _load_cmd_output(cmd_to_file, "show ip pim rp mapping")) or {},
        "neighbors": _safe_parse(parse_pim_neighbors,
                                 _load_cmd_output(cmd_to_file, "show ip pim neighbor")) or [],
    }


def build_ipv6_fhs(cmd_to_file: Dict[str, str]) -> dict:
    """IPv6 first-hop-security posture for THIS device, fusing the dedicated FHS show-commands
    ('show ipv6 nd raguard policy', 'show ipv6 dhcp guard policy') with the already-collected
    'show running-config' (the most reliable, platform-agnostic evidence of dual-stack + per-interface
    attachment). {} when the device shows no IPv6 at all -> a pure-IPv4 device contributes nothing and the
    detector never cries wolf over it. Fail-soft via _safe_parse."""
    rag = _safe_parse(parse_ipv6_raguard_policy,
                      _load_cmd_output(cmd_to_file, "show ipv6 nd raguard policy")) or []
    dhg = _safe_parse(parse_ipv6_dhcp_guard_policy,
                      _load_cmd_output(cmd_to_file, "show ipv6 dhcp guard policy")) or []
    run = _load_cmd_output(cmd_to_file, "show running-config") or ""

    ipv6_svi_vlans: List[int] = []
    ra_if: Set[str] = set()
    dhg_if: Set[str] = set()
    cur_if = ""
    cur_is_svi = False
    cur_has_v6 = False
    for raw in run.splitlines():
        m = re.match(r"^\s*interface\s+(\S+)", raw, re.IGNORECASE)
        if m:
            cur_if = normalize_ifname(m.group(1))
            cur_is_svi = bool(re.match(r"^(Vlan|Vl)\d+$", m.group(1), re.IGNORECASE))
            cur_has_v6 = False
            continue
        if not cur_if:
            continue
        low = raw.strip().lower()
        if low.startswith("ipv6 address ") and "autoconfig" not in low:
            if cur_is_svi and not cur_has_v6:
                mvid = re.match(r"^(?:Vlan|Vl)(\d+)$", cur_if, re.IGNORECASE)
                if mvid:
                    ipv6_svi_vlans.append(int(mvid.group(1)))
                cur_has_v6 = True
        if re.match(r"^ipv6 nd raguard\b", low):
            ra_if.add(cur_if)
        if re.match(r"^ipv6 dhcp guard\b", low):
            dhg_if.add(cur_if)

    for pol in rag:
        for t in pol.get("targets", []):
            if t.get("type") == "PORT" and t.get("name"):
                ra_if.add(t["name"])
    for pol in dhg:
        for t in pol.get("targets", []):
            if t.get("type") == "PORT" and t.get("name"):
                dhg_if.add(t["name"])

    ra_policy_names = sorted({p.get("policy") for p in rag if p.get("policy")})
    dhg_policy_names = sorted({p.get("policy") for p in dhg if p.get("policy")})
    ra_vlan_attached = any(t.get("type") == "VLAN" for p in rag for t in p.get("targets", []))
    dhg_vlan_attached = any(t.get("type") == "VLAN" for p in dhg for t in p.get("targets", []))

    ra_present = bool(ra_if) or ra_vlan_attached
    dhg_present = bool(dhg_if) or dhg_vlan_attached
    dualstack = bool(ipv6_svi_vlans)

    if not dualstack and not ra_present and not dhg_present and not ra_policy_names and not dhg_policy_names:
        return {}
    return {
        "dualstack": dualstack,
        "ipv6_svi_vlans": sorted(set(ipv6_svi_vlans)),
        "ra_guard_policies": ra_policy_names,
        "dhcp_guard_policies": dhg_policy_names,
        "ra_guard_ifaces": sorted(ra_if),
        "dhcp_guard_ifaces": sorted(dhg_if),
        "ra_guard_present": ra_present,
        "dhcp_guard_present": dhg_present,
    }


def build_ntp(cmd_to_file: Dict[str, str]) -> dict:
    """Clock-synchronization STATE for THIS device from 'show ntp status' (IOS/IOS-XE) or, on NX-OS where that
    command carries no sync line, 'show ntp peer-status' (parse_ntp_status) -> {synchronized, stratum,
    reference, source}. {} when the device returned no NTP output (so a never-collected device is ABSENT from
    snap['ntp'] rather than counted unsynchronized). The OPERATIONAL complement to the config-only CIS no-ntp
    check. Fail-soft via _safe_parse."""
    return _safe_parse(parse_ntp_status,
                       _load_cmd_output(cmd_to_file, "show ntp status", "show ntp peer-status")) or {}


def build_port_security_detail(cmd_to_file: Dict[str, str]) -> dict:
    """Access-edge port-security state for THIS device from 'show port-security interface' DETAIL
    (parse_port_security_detail): {ifname: {enabled, port_status, violation_mode, violation_count, last_src,
    last_vlan}}. {} when the device runs no port-security or the detail form was not collected. An err-disabled
    (Secure-shutdown) secured port -- a live access outage -- was previously invisible to the design layer (the
    summary form has no port-status column). Fail-soft via _safe_parse."""
    return _safe_parse(parse_port_security_detail,
                       _load_cmd_output(cmd_to_file, "show port-security interface")) or {}


def build_storm_control(cmd_to_file: Dict[str, str]) -> list:
    """Per-interface traffic-storm-control state for THIS device from 'show storm-control' (parse_storm_control):
    [{interface, traffic, filter_state, upper, lower, current, action, configured}]. [] when the device runs no
    storm-control. The senior gap (-> _d_storm_control_action) is a CONFIGURED rule whose action is None -- it
    drops a storm silently with no trap and no err-disable. Fail-soft via _safe_parse."""
    return _safe_parse(parse_storm_control, _load_cmd_output(cmd_to_file, "show storm-control")) or []


def build_qos_runtime(cmd_to_file: Dict[str, str]) -> list:
    """QoS RUNTIME health for THIS device from 'show policy-map interface' (parse_policymap_drops):
    [{interface, policy, class, priority, drop_pkts, drop_bytes, output_pkts, police_drop_pkts,
    police_drop_bytes}] -- one row per EGRESS class/queue. [] when no service-policy is attached (or the command
    was not collected). The runtime complement to build/parse_qos_config (which only proves a policy EXISTS):
    a class with significant egress drops means the configured QoS is shedding the very traffic its intent
    classified. Fail-soft via _safe_parse."""
    return _safe_parse(parse_policymap_drops,
                       _load_cmd_output(cmd_to_file, "show policy-map interface")) or []


# Explicit switch/router model families, used ONLY when a neighbour advertises no capabilities (a bare
# LLDP neighbour). Deliberately NARROW -- it must NOT match a Cisco IP phone or access point, so we do NOT
# key off the bare word 'cisco' the way infer_endpoint_type does (that maps every Cisco box to 'Switch').
_INFRA_PLATFORM_RE = re.compile(
    r"(\bnexus|\bcatalyst|\bn[0-9]k\b|\bc9[0-9]{3}|\bc3[0-9]{3}|\bc2[0-9]{3}|\bws-c[23456]|"
    r"\basr[0-9]|\bisr[0-9]|\bcsr[0-9]|\bncs[- ]?[0-9]|\bcisco[ -][0-9]{4}\b)", re.IGNORECASE)


def _neighbor_is_infra(rec: Dict[str, str]) -> bool:
    """Classify a CDP/LLDP neighbour record (parse_neighbors_detail) as INFRASTRUCTURE (a switch/router in
    the L2/L3 path) vs an EDGE device (phone / access-point / host / WLC). The advertised CAPABILITIES are
    AUTHORITATIVE when present (a device that says it is a phone/AP/host is not silently re-read as a switch
    via its platform string):
      * CDP capabilities (full words): infra iff 'Switch' or 'Router' appears.
      * LLDP enabled-capabilities (letters): infra iff 'R' (Router) or 'B' (Bridge) is set AND 'W' (WLAN-AP)
        is NOT (an AP sets only W; a switch advertises B).
      * Only when NO capabilities are advertised do we fall back to an explicit switch/router PLATFORM family
        (_INFRA_PLATFORM_RE) -- never the greedy 'cisco'-substring rule.
    A neighbour with neither an infra capability nor an infra platform is treated as NON-infra."""
    caps = (rec.get("capabilities") or "").strip()
    proto = (rec.get("proto") or "cdp").lower()
    if caps:
        if proto == "lldp":
            tokens = {t.strip().upper() for t in re.split(r"[,\s]+", caps) if t.strip()}
            return ("R" in tokens or "B" in tokens) and "W" not in tokens
        low = caps.lower()
        return bool(re.search(r"\bswitch\b", low) or re.search(r"\brouter\b", low))
    return bool(_INFRA_PLATFORM_RE.search(rec.get("platform", "") or ""))


def build_undocumented_neighbors(cmd_to_file: Dict[str, str]) -> list:
    """INFRASTRUCTURE CDP/LLDP neighbours of THIS device, parsed from the already-collected
    'show cdp neighbors detail' + 'show lldp neighbors detail' (parse_neighbors_detail) and filtered to
    switches/routers via _neighbor_is_infra. Returns [{device_id, platform, capabilities, mgmt_ip,
    local_intf, remote_port, proto}] -- the candidate set the shadow-infra detector reconciles against the
    assessed inventory. Edge devices (phones / APs / hosts) are excluded here. [] when the device advertises no
    infra neighbour. No NEW collected command. Fail-soft via _safe_parse."""
    cdp = _safe_parse(parse_neighbors_detail, _load_cmd_output(cmd_to_file, "show cdp neighbors detail"), "cdp") or []
    lldp = _safe_parse(parse_neighbors_detail, _load_cmd_output(cmd_to_file, "show lldp neighbors detail"), "lldp") or []
    out = []
    seen = set()
    for rec in list(cdp) + list(lldp):
        if not _neighbor_is_infra(rec):
            continue
        key = ((rec.get("device_id") or "").strip().lower(), (rec.get("local_intf") or "").lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    return out


def build_routing_neighbors(cmd_to_file: Dict[str, str]) -> dict:
    """Protocol-to-protocol analysis: this device's dynamic-routing adjacencies, parsed from the
    already-collected 'show ip ospf neighbor' / 'show ip eigrp neighbors' / 'show [ip] bgp summary'
    (NO new collected command). Returns {ospf:[{neighbor,state,address,interface}],
    eigrp:[{neighbor,interface,state}], bgp:[{neighbor,as,state}]}; each list empty when that protocol
    isn't running. Lets the explorer surface protocol boundaries (devices running >=2 protocols),
    adjacency health (FULL/Established vs stuck), and the BGP AS map. Fail-soft via _safe_parse."""
    return {
        "ospf":  _safe_parse(parse_ospf_neighbors,  _load_cmd_output(cmd_to_file, "show ip ospf neighbor")) or [],
        "eigrp": _safe_parse(parse_eigrp_neighbors, _load_cmd_output(cmd_to_file, "show ip eigrp neighbors")) or [],
        "bgp":   _safe_parse(parse_bgp_summary,     _load_cmd_output(cmd_to_file, "show ip bgp summary", "show bgp summary")) or [],
    }


def build_redistribution(cmd_to_file: Dict[str, str]) -> List[dict]:
    """Protocol-to-protocol analysis (slice 2): this device's route-redistribution edges, parsed from the
    already-collected 'show running-config' -> [{into_proto,into_id,from_proto,from_id,route_map,raw}];
    [] when none. Each row is a protocol-to-protocol boundary the explorer flags. Fail-soft via _safe_parse."""
    run = _load_cmd_output(cmd_to_file, "show running-config")
    return _safe_parse(parse_redistribution, run, _default=[]) or []


# -----------------------------------------------------------------------------
# Route-aware reachability: embed each device's routing knowledge into the snapshot
# so the explorer can verify a gateway actually has a route toward the destination
# subnet, instead of assuming any gateway routes to any subnet. Parsed from the
# already-collected 'show ip route' (NO new collected command), and SCOPED to the
# in-scope gateway subnets + the default route so the single-file snapshot stays small.
# -----------------------------------------------------------------------------
def build_routes(cmd_to_file: Dict[str, str]) -> Dict[str, dict]:
    """Parse this device's full routing table from the already-collected 'show ip route'
    -> {prefix: {entries:[...]}}; {} when none. Fail-soft via _safe_parse. (Scoped down for
    the snapshot by scope_routes; the full parse stays transient.)"""
    out = _load_cmd_output(cmd_to_file, "show ip route", "show ip route vrf all")
    return _safe_parse(parse_ip_routes, out) or {}


def build_bgp_received(cmd_to_file: Dict[str, str]) -> list:
    """NEW-V3.23.97: the BGP RIB (received/best prefixes) from the new 'show ip bgp' collection
    -> [prefix,...]; [] when the command was not collected / device runs no BGP. Fail-soft."""
    out = _load_cmd_output(cmd_to_file, "show ip bgp", "show bgp ipv4 unicast")
    return _safe_parse(parse_bgp_table, out) or []


_MROUTE_GROUP_RE = re.compile(r"\(\s*\S+\s*,\s*(2(?:2[4-9]|3[0-9])\.\d{1,3}\.\d{1,3}\.\d{1,3})\s*\)")


def build_igmp_groups(cmd_to_file: Dict[str, str]) -> list:
    """NEW-V3.23.102: distinct multicast group IPs this device sees -- IGMP membership, IGMP-snooping
    groups, and mroute (S,G)/(*,G) state. [] when none of those commands were collected. Fail-soft.
    On a broadcast fabric these are the PTP / Dante / ST-2110 / production groups."""
    groups: set = set()
    for cmd in ("show ip igmp groups", "show ip igmp snooping groups"):
        groups.update(_safe_parse(parse_igmp_groups, _load_cmd_output(cmd_to_file, cmd)) or [])
    mroute = _load_cmd_output(cmd_to_file, "show ip mroute")
    if mroute:
        groups.update(_MROUTE_GROUP_RE.findall(mroute))
    return sorted(groups, key=lambda ip: tuple(int(o) for o in ip.split(".")))


def build_igmp_queriers(cmd_to_file: Dict[str, str]) -> list:
    """NEW-V3.23.102: the L2 IGMP-snooping querier per VLAN -> [{vlan, querier}]; [] when uncollected."""
    return _safe_parse(parse_igmp_snooping_querier,
                       _load_cmd_output(cmd_to_file, "show ip igmp snooping querier")) or []


def build_ptp(cmd_to_file: Dict[str, str]) -> dict:
    """NEW-V3.23.102: PTP (IEEE 1588) clock/grandmaster health -> {device_type, domain, grandmaster,
    offset_ns, mean_path_delay_ns, locked}; {} when no PTP output was collected. Fail-soft."""
    out = "\n".join(x for x in (_load_cmd_output(cmd_to_file, "show ptp clock"),
                                _load_cmd_output(cmd_to_file, "show ptp parent")) if x)
    return _safe_parse(parse_ptp_clock, out) or {}


def build_acl_hits(cmd_to_file: Dict[str, str]) -> dict:
    """NEW-V3.23.102: ACL hit-counts from 'show ip access-lists' -> {"port:proto": total_matches} for
    ACEs that report '(N matches)'. Turns ACL design-intent into Confirmed active-traffic evidence.
    {} when uncollected. Keyed by 'port:proto' to align with compute_service_map's service keys."""
    aces = _safe_parse(parse_acl_hitcounts, _load_cmd_output(cmd_to_file, "show ip access-lists")) or []
    hits: dict = {}
    for a in aces:
        if a.get("port") and a.get("matches"):
            proto = a.get("proto") if a.get("proto") in ("tcp", "udp", "sctp", "dccp") else "udp"
            key = f"{a['port']}:{proto}"
            hits[key] = hits.get(key, 0) + int(a["matches"])
    return hits


def inscope_subnets(all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> Set[str]:
    """The set of gateway (SVI) connected prefixes across all scanned switches, in CIDR form.
    These are the destination subnets the explorer asks reachability about, so the embedded
    routing table is scoped to the routes that could carry traffic toward one of them. Derived
    from each SVI's own 'ip address' (svi_ip), falling back to its connected subnet_primary_route."""
    nets: Set[str] = set()
    for ifaces in all_interfaces.values():
        for port, d in ifaces.items():
            if not re.match(r"^Vlan\d+$", port, re.IGNORECASE):
                continue
            ipmask = (getattr(d, "svi_ip", "") or "").split()
            if len(ipmask) >= 2:
                try:
                    nets.add(str(ipaddress.ip_network(f"{ipmask[0]}/{ipmask[1]}", strict=False)))
                    continue
                except ValueError:
                    pass
            pfx = (getattr(d, "subnet_primary_route", "") or "").strip()
            if pfx:
                try:
                    nets.add(str(ipaddress.ip_network(pfx, strict=False)))
                except ValueError:
                    pass
    return nets


def scope_routes(route_db: Dict[str, dict], inscope: Set[str]) -> List[dict]:
    """Flatten a parsed route table to the compact rows the explorer needs, keeping ONLY routes
    that could carry traffic toward an in-scope subnet (the route's prefix covers one) plus the
    default route. Drops host (/32 local) routes and out-of-scope prefixes, so the embedded
    snapshot stays small. Each row: {prefix, source, next_hop, out_intf}; deduped, order preserved."""
    nets: List[Any] = []   # IPv4Network | IPv6Network; Any keeps mypy at the package baseline
    for s in inscope:
        try:
            nets.append(ipaddress.ip_network(s, strict=False))
        except ValueError:
            pass
    out: List[dict] = []
    seen: Set[tuple] = set()
    for prefix, info in route_db.items():
        try:
            rnet = ipaddress.ip_network(prefix, strict=False)
        except ValueError:
            continue
        keep = rnet.prefixlen == 0   # default route is always relevant
        if not keep:
            for s in nets:
                if s.version == rnet.version and s.subnet_of(rnet):
                    keep = True
                    break
        if not keep:
            continue
        for e in info.get("entries", []):
            row = {"prefix": e.get("prefix", prefix), "source": e.get("source", "") or "",
                   "next_hop": e.get("next_hop", "") or "", "out_intf": e.get("out_intf", "") or ""}
            key = (row["prefix"], row["source"], row["next_hop"], row["out_intf"])
            if key not in seen:
                seen.add(key)
                out.append(row)
    return out


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
        dp.reported_hostname = ver.get("hostname_reported", "")

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

    # PoE budget fallback (DET-poe-001): access stacks report their inline-power budget only in the
    # 'show power inline' Module rows ('1  1120.0  0.0  1120.0'), which 'show environment power' above
    # never sees -- so poe_util read 0/303 fleet-wide. When the env-power parse left it blank, sum the
    # inline Module rows so PoE utilisation is real (n/a-only / non-PoE modules stay blank, not a false 0).
    if not str(dp.power_capacity_w).strip():
        _poe_inline = _load_cmd_output(cmd_to_file, "show power inline")
        if _poe_inline:
            _pb = _parse_poe_inline_budget(_poe_inline)
            if _pb.get("available"):
                dp.power_capacity_w = f"{_pb['available']} W"
                dp.power_drawn_w = f"{_pb.get('used', 0.0)} W"

    mod_out = _load_cmd_output(cmd_to_file, "show module")
    if mod_out and dp.num_modules == 0:
        dp.num_modules = parse_show_module_count(mod_out)

    # 'show environment' is rejected as '% Incomplete command' on IOS-XE (9300/3850) - those need
    # 'show environment all'. Feed whichever was collected (concatenated) to one parser; an error
    # line in either output matches nothing, so combining is safe.
    env_out = _load_cmd_output(cmd_to_file, "show environment")
    env_all_out = _load_cmd_output(cmd_to_file, "show environment all")
    env_out = "\n".join(x for x in (env_out, env_all_out) if x)
    if env_out:
        env = parse_show_environment(env_out)
        dp.fan_status         = env.get("fan_status", "")
        dp.temperature_status = env.get("temperature_status", "")
        # Catalyst 4948E / 4500-X recovery: 'show environment power' is unsupported there, so the
        # PS health comes from the 'show environment' Power-Supply table. Fall back to it only when
        # the (authoritative) env-power path above left these blank, so other platforms are unchanged.
        if not dp.ps_status and env.get("ps_status"):
            dp.ps_status = env["ps_status"]
        env_nps = int(env.get("num_ps", "0") or 0)
        if env_nps > dp.num_power_supplies:
            dp.num_power_supplies = env_nps

    physical = [p for p in interfaces
                if PHYSICAL_IFACE_RE.match(normalize_ifname(p))
                and not normalize_ifname(p).startswith("Po")]
    dp.total_ports  = len(physical)
    dp.active_ports = sum(1 for p in physical
                          if interfaces[p].status in ("connected","up"))
    return dp


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
    """Fill end_host_ip (and arp_source_switch) from global ARP. FIX-R4 + NEW-V11.

    V3.23.140: end_host_ip is now a list ALIGNED with end_host_mac (one IP per MAC, same order),
    so a port-channel / multi-MAC port shows every endpoint's IP instead of only the first MAC's.
    A MAC with no ARP entry gets a '-' placeholder so position N of the IP list always matches MAC N;
    trailing unresolved entries are trimmed to avoid noise. Single-MAC ports are byte-unchanged."""
    filled = 0
    for hostname, interfaces in all_interfaces.items():
        for p, d in interfaces.items():
            if d.end_host_ip or not d.end_host_mac: continue
            macs = [m.strip() for m in d.end_host_mac.split(",") if m.strip()]
            ips = [global_arp.get(mac, "") for mac in macs]
            if not any(ips): continue
            # trim trailing unresolved positions so we don't dangle '-' at the end
            last = max(i for i, ip in enumerate(ips) if ip)
            d.end_host_ip = ", ".join((ip or "-") for ip in ips[:last + 1])
            filled += sum(1 for ip in ips if ip)
            if global_arp_source and not d.arp_source_switch:
                for mac in macs:                                       # NEW-V11: provenance from the first resolved MAC
                    src = global_arp_source.get(mac, "")
                    if src:
                        d.arp_source_switch = src
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
# BUILD INTERFACE DB (per device) - PHASE 2.7 step 28
# =============================================================================
def build_interfaces(hostname: str, platform: str, cmd_to_file: Dict[str, str],
                     switch_identity: Optional[Dict[str, str]] = None) -> Dict[str, InterfaceData]:
    interfaces: Dict[str, InterfaceData] = {}
    switch_identity = switch_identity or {}

    # 1) show interface status
    st_out = _load_cmd_output(cmd_to_file, "show interface status")
    for p, v in _safe_parse(parse_show_interface_status, st_out).items():
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
    for p, v in _safe_parse(parse_show_interface_switchport, sw_out).items():
        interfaces.setdefault(p, InterfaceData(port=p))
        interfaces[p].switchport_mode = v.get("mode","") or interfaces[p].switchport_mode
        if interfaces[p].switchport_mode == "Access":
            interfaces[p].vlan      = v.get("access_vlan","")      or interfaces[p].vlan
            interfaces[p].vlan_name = v.get("access_vlan_name","") or interfaces[p].vlan_name

    # 3) trunk table
    tr_out = _load_cmd_output(cmd_to_file, "show interface trunk", "show interfaces trunk")
    for p, v in _safe_parse(parse_show_interface_trunk_table, tr_out).items():
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
    run_iface  = _safe_parse(parse_run_config_interfaces, run_out)
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
        if v.get("acl_in"):    interfaces[p].acl_in         = v["acl_in"]
        if v.get("acl_out"):   interfaces[p].acl_out        = v["acl_out"]
        if v.get("mtu"):       interfaces[p].mtu            = v["mtu"]   # NEW-V3.23.49 (path-MTU)
        if v.get("helpers"):   interfaces[p].dhcp_helpers   = v["helpers"]   # DHCP-relay reachability
        if v.get("pc_id") and not interfaces[p].port_channel:
            interfaces[p].port_channel = v["pc_id"]
        if v.get("pc_mode") and not interfaces[p].port_channel_protocol:
            mode = v["pc_mode"].lower()
            interfaces[p].port_channel_protocol = "Active" if mode == "active" else "On"

    # 5) VRF
    vrf_out = _load_cmd_output(cmd_to_file, "show vrf interface", "show ip vrf interface",
                               "show ip vrf interfaces")
    for p, vrf in _safe_parse(parse_show_vrf_interface, vrf_out).items():
        interfaces.setdefault(p, InterfaceData(port=p))
        if vrf and not interfaces[p].vrf: interfaces[p].vrf = vrf

    # 6) etherchannel / port-channel
    pc_out = _load_cmd_output(cmd_to_file, "show port-channel summary", "show etherchannel summary")
    pc_proto: Dict[str, str] = {}
    po_members: Dict[str, str] = {}
    if pc_out:
        pc_proto   = _safe_parse(parse_portchannel_protocol_from_summary, pc_out)
        if not pc_proto: pc_proto = _safe_parse(parse_etherchannel_protocol_ios, pc_out)
        po_members = _safe_parse(parse_etherchannel_summary_members, pc_out)

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
    mac_map = _safe_parse(parse_show_mac_address_table, mac_out)
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
    blocked = _safe_parse(parse_spanning_tree_blockedports,
        _load_cmd_output(cmd_to_file, "show spanning-tree blockedports"))
    incons  = _safe_parse(parse_spanning_tree_blockedports,
        _load_cmd_output(cmd_to_file, "show spanning-tree inconsistentports"))
    stp_states = _safe_parse(parse_spanning_tree_states, stp_out)
    stp_detail = _safe_parse(parse_spanning_tree_detail, stp_out)   # NEW-V14.7 per-VLAN breakdown
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
    for p, s in _safe_parse(parse_show_power_inline, poe_out).items():
        interfaces.setdefault(p, InterfaceData(port=p))
        interfaces[p].poe_status = s

    # 10) CDP + LLDP
    route_db = _safe_parse(parse_ip_routes, _load_cmd_output(cmd_to_file, 'show ip route'))
    vlan_names = {vid: (info.get("name") or "")                                     # NEW-V14.8
                  for vid, info in _safe_parse(parse_vlan_brief, _load_cmd_output(cmd_to_file, "show vlan brief")).items()}
    hsrp_db = _safe_parse(parse_hsrp_summary, _load_cmd_output(cmd_to_file, 'show standby brief', 'show standby all', 'show hsrp brief', 'show hsrp all'))
    vrrp_db = _safe_parse(parse_vrrp_summary, _load_cmd_output(cmd_to_file, 'show vrrp brief'))   # NEW-V14.6
    glbp_db = _safe_parse(parse_glbp_summary, _load_cmd_output(cmd_to_file, 'show glbp brief'))   # NEW-V14.6
    mcast_db = _safe_parse(parse_multicast_info, _load_cmd_output(cmd_to_file, 'show ip mroute'), _load_cmd_output(cmd_to_file, 'show ip pim interface'))
    cdp_out  = _load_cmd_output(cmd_to_file, "show cdp neighbors detail")
    lldp_out = _load_cmd_output(cmd_to_file, "show lldp neighbors detail")
    neigh: Dict[str, Dict[str, str]] = {}
    if cdp_out:  neigh.update(_safe_parse(parse_neighbors_cdp, cdp_out))
    if lldp_out:
        for k, v in _safe_parse(parse_neighbors_lldp, lldp_out).items():
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
