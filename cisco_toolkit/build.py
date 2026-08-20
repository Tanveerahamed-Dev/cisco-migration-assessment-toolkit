"""The model-construction layer: build the per-device InterfaceData table, the
DevicePhysical / switch-identity records, and the global-ARP enrichment from
already-collected show output. Depends on cmdio (loading), parse (parsers), model, and
textutils - a layer above those, independent of analyze/excel. Extracted verbatim from
COLLECT_PARSE_V3_23_0.py across PHASE 2.7 steps 27-28 (behaviour byte-identical):
step 27 = the switch-level builders + ARP enrichment, step 28 = build_interfaces."""
import ipaddress
import json
import logging
import re
from hashlib import sha256
from typing import Any, Dict, List, Optional, Set, Tuple

from cisco_toolkit.cmdio import TRUNK_TABLE_CMD_VARIANTS, _load_cmd_output, _safe_parse
from cisco_toolkit import input_custody
from cisco_toolkit.multichassis_lag import produce_multichassis_lag_typed_observation
from cisco_toolkit.model import DevicePhysical, InterfaceData
from cisco_toolkit.parse import (
    ParsedRouteTable,
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
    parse_asa_failover, parse_asa_resource_usage,                    # Cisco firewall (ASA / Secure Firewall Threat Defense) HA + resource capacity -- SSH show-text channel
    parse_ise_nodes,                                                 # Cisco ISE (Identity Services Engine) deployment -- JSON controller-REST channel
    parse_arista_mlag, parse_arista_bgp_evpn_summary,                # multi-vendor: Arista EOS MLAG + BGP-EVPN overlay (device-native JSON; first non-Cisco vendor)
    parse_junos_chassis_cluster,                                     # multi-vendor: Juniper Junos SRX chassis-cluster HA (the SECOND non-Cisco vendor; '| display json')
    parse_aws_security_groups,                                       # public cloud: AWS security-group exposure (the FIRST cloud-domain axis)
    parse_fortigate_ha_status,                                       # multi-vendor: Fortinet FortiGate HA cluster sync (the THIRD non-Cisco vendor)
    parse_mroute_entries,                                            # Cisco depth: multicast RPF integrity ((S,G) Null incoming-interface)
    parse_fmc_devices, parse_fmc_ha_pairs, parse_fmc_deployable, parse_fmc_ha_status, parse_fmc_server_version,   # Cisco Secure Firewall Mgmt Center (FMC) -- JSON controller-REST channel
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
    forwarding_gate_candidate_projection_incomplete,
    parse_redistribution,                                            # protocol-to-protocol analysis (slice 2)
    parse_bgp_table,                                                 # NEW-V3.23.97 (BGP received prefixes)
    parse_igmp_groups, parse_igmp_snooping_querier, parse_ptp_clock, parse_acl_hitcounts,  # NEW-V3.23.102
)
from cisco_toolkit.textutils import PHYSICAL_IFACE_RE, detect_link_type, is_live_trunk_status, normalize_ifname

logger = logging.getLogger(__name__)


class ScopedRouteProjection(list):
    """Current-run marker for the exact route rows retained from one parsed RIB.

    The marker and its receipt attributes are deliberately lost by JSON serialization.  Consumers can therefore
    distinguish a projection produced from the live parsed denominator from an arbitrary embedded route list.
    """

    def __init__(self, rows: List[dict], *, scope_networks: List[str], source_prefix_count: int,
                 source_entry_count: int, source_parse_receipt: Optional[dict],
                 source_parse_receipt_verified: bool) -> None:
        super().__init__(rows)
        encoded = json.dumps(rows, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.projection_receipt = {
            "schema": "scoped_route_projection/1",
            "algorithm": "overlap_and_next_hop_closure_v1",
            "complete": True,
            "scope_networks": list(scope_networks),
            "source_prefix_count": source_prefix_count,
            "source_entry_count": source_entry_count,
            "source_parse_receipt": source_parse_receipt,
            "source_parse_receipt_verified": source_parse_receipt_verified,
            "scoped_row_count": len(rows),
            "scoped_rows_sha256": sha256(encoded).hexdigest(),
        }


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
    Fail-soft. This legacy local projection does not confirm a peer pair or dual-homed attachment;
    the typed multichassis owner requires reciprocal system identities and matching LACP evidence."""
    return _safe_parse(parse_vpc, _load_cmd_output(cmd_to_file, "show vpc")) or {}


def build_multichassis_lag_typed_observation(
        hostname: str, platform: str, collection_mode: str,
        cmd_to_file: Dict[str, str]) -> Optional[dict]:
    """Produce one raw-byte-bound vPC/MLAG observation from already-custodied captures.

    NX-OS live/offline and EOS offline are the only declared variants.  The ordinary platform
    detector is Cisco-oriented, so an offline EOS import is selected from an actual ``show mlag``
    capture rather than from a caller label.  Missing or unreadable supplemental commands stay
    absent; the producer then emits incomplete/not-verified evidence instead of filling leaves from
    topology, domain IDs, vPC/MLAG IDs, or IP addresses.
    """
    mode = str(collection_mode or "").strip().casefold()

    def _read(commands: Tuple[str, ...]) -> Dict[str, bytes]:
        evidence = {}
        for command in commands:
            path = cmd_to_file.get(command)
            if not path:
                continue
            try:
                evidence[command] = input_custody.read_bytes(path)
            except (OSError, input_custody.BoundInputMutationError):
                # BoundInputMutationError is recorded by input_custody for mandatory finalization.
                # The local observation remains incomplete rather than parsing changed bytes.
                continue
        return evidence

    nxos_commands = ("show vpc", "show vpc role", "show lacp neighbor")
    if "show vpc" in cmd_to_file:
        observation = produce_multichassis_lag_typed_observation(
            hostname,
            vendor="cisco",
            platform="nxos",
            collection_mode=mode,
            command_bytes=_read(nxos_commands),
        )
        if observation is not None:
            return observation

    eos_commands = ("show mlag", "show mlag interfaces detail", "show lacp peer")
    if mode == "offline" and "show mlag" in cmd_to_file:
        return produce_multichassis_lag_typed_observation(
            hostname,
            vendor="arista",
            platform="eos",
            collection_mode=mode,
            command_bytes=_read(eos_commands),
        )
    return None


def build_fhrp_detail(cmd_to_file: Dict[str, str]) -> list:
    """Full first-hop-redundancy state for THIS device from 'show standby [all]' DETAIL (parse_hsrp_detail):
    [{ifname, group, state, priority, cfg_priority, preempt, preempt_delay, vip, vmac, standby_ip, track}].
    [] when the device runs no HSRP. The brief form (interface hsrp_behavior) keeps only state+VIP; this
    carries the election / preempt / tracking fields a senior FHRP audit needs (the Meridian reference fleet ran no FHRP,
    so this is the first capability proven on a non-Meridian environment). Fail-soft via _safe_parse."""
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


def build_firewall(cmd_to_file: Dict[str, str]) -> dict:
    """Cisco firewall (ASA / Secure Firewall Threat Defense) state for THIS device -> {failover, resource_usage}.
    Reads 'show failover' (classic ASA over SSH; FTD reaches the same LINA CLI via 'system support diagnostic-cli')
    -- the HA/failover state machine -- and 'show resource usage' -- per-resource Current/Peak/Limit/Denied for
    the capacity-sizing axis (a Denied>0 or near-Limit Peak on a data-plane resource is observed exhaustion). A pair with failover ENABLED but a unit Failed / Disabled or the peer
    Not Detected has no working standby, so a firewall in the data path is a single point of failure (the
    config-present-but-operationally-broken false-health trap). {} when the device is not a firewall / runs no
    failover (the command errors or is absent) -- coverage-honest, so a switch fleet never fires. Fail-soft."""
    fo = _safe_parse(parse_asa_failover, _load_cmd_output(cmd_to_file, "show failover")) or {}
    res = _safe_parse(parse_asa_resource_usage, _load_cmd_output(cmd_to_file, "show resource usage")) or []
    out = {}
    if fo:
        out["failover"] = fo
    if res:
        out["resource_usage"] = res
    return out


def build_ise(cmd_to_file: Dict[str, str]) -> dict:
    """Cisco ISE (Identity Services Engine) deployment state for THIS query host from a read-only Open API
    export -> {nodes: [...]}. The JSON-ingestion channel (like ACI/SD-WAN): ISE is a controller cluster, not
    a CLI-`show` device, so 'GET /api/v1/deployment/node' (saved into the collection dir) is read through the
    SAME _load_cmd_output path and json-normalized. The node list carries each node's personas (roles /
    services) and reachability (nodeStatus) -- a node not Connected, a lone Policy Service node, or a missing
    Secondary Admin/Monitoring are present, controller-reported gaps. {} when no ISE export. Fail-soft."""
    nodes = _safe_parse(parse_ise_nodes, _load_cmd_output(cmd_to_file, "api/v1/deployment/node")) or []
    if not nodes:                                          # ERS fallback (the consolidated /ers/config/node export)
        nodes = _safe_parse(parse_ise_nodes, _load_cmd_output(cmd_to_file, "ers/config/node")) or []
    out = {}
    if nodes:
        out["nodes"] = nodes
    return out


def build_fmc(cmd_to_file: Dict[str, str]) -> dict:
    """Cisco Secure Firewall Management Center (FMC) state for THIS query host from a read-only REST export ->
    {devices, ha_pairs, deployable, ha_status}. The JSON-ingestion channel (like ACI/SD-WAN/ISE): an FMC
    manages an FTD fleet centrally, so for an FMC-managed fleet the controller -- not the device CLI -- is the
    source of truth. Reads the four migration-relevant endpoint exports (devicerecords, ftddevicehapairs,
    deployabledevices, fmchastatuses) through the SAME _load_cmd_output path, json-normalized. {} when no FMC
    export. Fail-soft."""
    devs = _safe_parse(parse_fmc_devices, _load_cmd_output(cmd_to_file, "api/fmc_config/v1/devices/devicerecords")) or []
    ha = _safe_parse(parse_fmc_ha_pairs, _load_cmd_output(cmd_to_file, "api/fmc_config/v1/devicehapairs/ftddevicehapairs")) or []
    dep = _safe_parse(parse_fmc_deployable, _load_cmd_output(cmd_to_file, "api/fmc_config/v1/deployment/deployabledevices")) or []
    has = _safe_parse(parse_fmc_ha_status, _load_cmd_output(cmd_to_file, "api/fmc_config/v1/integration/fmchastatuses")) or {}
    sv = _safe_parse(parse_fmc_server_version, _load_cmd_output(cmd_to_file, "api/fmc_platform/v1/info/serverversion")) or {}
    out = {}
    if devs:
        out["devices"] = devs
    if ha:
        out["ha_pairs"] = ha
    if dep:
        out["deployable"] = dep
    if has:
        out["ha_status"] = has
    if sv:
        out["server_version"] = sv
    return out


def build_arista(cmd_to_file: Dict[str, str]) -> dict:
    """Arista EOS multi-vendor state for THIS device -> {mlag: {...}, evpn: [...]}. The FIRST non-Cisco vendor
    channel: EOS is JSON-native, so 'show mlag | json' (MLAG -- the dual-active analogue of Cisco vPC) and
    'show bgp evpn summary | json' (the BGP-EVPN/VXLAN overlay control plane -- the analogue of the Cisco NX-OS
    'show bgp l2vpn evpn summary') are captured per-device (like the Cisco show-text classes) and json-normalized
    by parse_arista_mlag / parse_arista_bgp_evpn_summary. {} when the device runs neither (no capture, MLAG
    'disabled', no EVPN peers) -- coverage-honest, so a Cisco switch fleet never fires. Fail-soft."""
    mlag = _safe_parse(parse_arista_mlag, _load_cmd_output(cmd_to_file, "show mlag")) or {}
    evpn = _safe_parse(parse_arista_bgp_evpn_summary, _load_cmd_output(cmd_to_file, "show bgp evpn summary")) or []
    out = {}
    if mlag:
        out["mlag"] = mlag
    if evpn:
        out["evpn"] = evpn
    return out


def build_juniper(cmd_to_file: Dict[str, str]) -> dict:
    """Juniper Junos multi-vendor state for THIS device -> {chassis_cluster: [...]}. The SECOND non-Cisco vendor
    channel, proving the adapter pattern generalises beyond Arista: Junos exposes structured state via 'show ...
    | display json', captured per-device and normalised by parse_junos_chassis_cluster. SRX chassis cluster is
    Juniper's stateful-firewall HA -- the analogue of the Cisco firewall 'show failover'. {} when the device is
    not a chassis cluster / runs no HA (no capture, or 'Chassis cluster is not enabled') -- coverage-honest, so
    a Cisco/Arista fleet never fires. Fail-soft."""
    cc = _safe_parse(parse_junos_chassis_cluster, _load_cmd_output(cmd_to_file, "show chassis cluster status")) or []
    out = {}
    if cc:
        out["chassis_cluster"] = cc
    return out


def build_cloud(cmd_to_file: Dict[str, str]) -> dict:
    """Public-cloud (AWS) network-exposure state for THIS account -> {security_groups: [...]}. The FIRST
    cloud-domain axis: a cloud account is added as a 'device' (like the ACI/ISE/FMC controllers), and its
    read-only 'aws ec2 describe-security-groups' export is read through the SAME _load_cmd_output path and
    json-normalised by parse_aws_security_groups. {} when there is no cloud export (coverage-honest, so an
    on-prem fleet never fires); {security_groups: []} when the export is present but nothing is world-open
    (observed / clean). Fail-soft."""
    sgs = _safe_parse(parse_aws_security_groups, _load_cmd_output(cmd_to_file, "aws ec2 describe-security-groups"), _default={})
    # shape-sentinel: Coverage-honesty must NOT hinge on 'the parser didn't raise'. Since Plan-A #16,
    # _safe_parse's DEFAULT crash fallback for a list parser is its registered shape -- [] -- which is itself a
    # list and would slip past the isinstance guard below, making build_cloud report {security_groups: []},
    # read downstream as 'cloud observed, nothing world-open' (false-health) instead of 'not observed'. So we
    # pin _default={}: a non-list crash sentinel (deliberately OFF the registry 'list' shape) that never
    # escapes -- the guard converts it to not-observed. `_default` fires ONLY on a raise, so a genuine clean []
    # on the happy path is preserved (unlike `or []`/`or {}`, which would collapse it). Only a LIST is a real
    # result; None (no export) and the {} crash-sentinel both -> not observed.
    if not isinstance(sgs, list):
        return {}
    return {"security_groups": sgs}


def build_fortigate(cmd_to_file: Dict[str, str]) -> dict:
    """Fortinet FortiGate multi-vendor state for THIS device -> {ha: {...}}. The THIRD non-Cisco vendor channel:
    FortiGate exposes its HA cluster state via 'get system ha status' (CLI show-text), captured per-device and
    normalised by parse_fortigate_ha_status. FortiGate HA is the firewall HA pair -- the analogue of the Cisco
    ASA/FTD 'show failover'. {} when the device is not an HA cluster (standalone) / runs no HA -- coverage-honest,
    so a Cisco / Arista / Juniper fleet never fires. Fail-soft."""
    ha = _safe_parse(parse_fortigate_ha_status, _load_cmd_output(cmd_to_file, "get system ha status")) or {}
    out = {}
    if ha:
        out["ha"] = ha
    return out


def build_mroute(cmd_to_file: Dict[str, str]) -> dict:
    """Cisco multicast RPF state for THIS device from 'show ip mroute' -> {n_entries, rpf_failures:[{source,
    group, oil_count}]}, or {} when no mroute table. rpf_failures lists ONLY the (S,G) source-tree entries with
    a Null incoming (RPF) interface AND a NON-ZERO RPF neighbour -- the genuinely anomalous blackhole. TWO benign
    Null-IIF classes are deliberately excluded so the detector cannot cry wolf:
      * (*,G) shared-tree entries (locally-joined / well-known / SSM groups -- 36 of them across the Meridian reference fleet); and
      * an (S,G) whose 'RPF nbr' is 0.0.0.0, which per Cisco means THIS router is the source (a local source / PIM
        register / SPT-pending) -- a normal, expected Null IIF, NOT an RPF failure (a real RPF failure shows a valid
        mismatched interface or dropped packets, never (S,G)+Null+RPF-0.0.0.0).
    {} when no multicast is running -- coverage-honest. Fail-soft."""
    entries = _safe_parse(parse_mroute_entries, _load_cmd_output(cmd_to_file, "show ip mroute")) or []
    if not entries:
        return {}
    rpf = [{"source": e.get("source"), "group": e.get("group"), "oil_count": e.get("oil_count", 0)}
           for e in entries
           if e.get("source") not in ("*", "", None) and str(e.get("iif", "")).strip().lower() == "null"
           and str(e.get("rpf_nbr", "")).strip() not in ("", "0.0.0.0")]   # RPF 0.0.0.0 == local source (benign)
    return {"n_entries": len(entries), "rpf_failures": rpf}


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
                         _load_cmd_output(cmd_to_file, "show ipv6 ospfv3 neighbors",
                                          "show ospfv3 neighbors", "show ospfv3 neighbor",
                                          "show ipv6 ospf neighbor")) or []
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


# A running-config line (stripped, lower-cased) that ENDS the interface block build_ipv6_fhs is walking:
# the `!` stanza separator, `end`, or the header of another top-level stanza. The three `... policy <NAME>`
# forms are listed explicitly because they are the GLOBAL first-hop-security policy DEFINITIONS, whose
# headers are prefix-identical to the per-interface attach commands.
_FHS_BLOCK_END_RE = (r"^(?:!|end$|vlan configuration\b|ipv6 (?:nd raguard|dhcp guard|snooping) policy\b"
                     r"|router\s|line\s|control-plane\b|vrf definition\b|class-map\s|policy-map\s)")


def build_ipv6_fhs(cmd_to_file: Dict[str, str]) -> dict:
    """IPv6 first-hop-security posture for THIS device, fusing the dedicated FHS show-commands
    ('show ipv6 nd raguard policy', 'show ipv6 dhcp guard policy') with the already-collected
    'show running-config' (the most reliable, platform-agnostic evidence of dual-stack + per-interface
    attachment). Only an ATTACHMENT counts: the global `ipv6 nd raguard policy <NAME>` / `ipv6 dhcp guard
    policy <NAME>` stanzas merely DEFINE a policy and protect nothing until attached to an interface or a
    `vlan configuration` block. {} when the device shows no IPv6 at all -> a pure-IPv4 device contributes
    nothing and the detector never cries wolf over it. Fail-soft via _safe_parse."""
    rag = _safe_parse(parse_ipv6_raguard_policy,
                      _load_cmd_output(cmd_to_file, "show ipv6 nd raguard policy")) or []
    dhg = _safe_parse(parse_ipv6_dhcp_guard_policy,
                      _load_cmd_output(cmd_to_file, "show ipv6 dhcp guard policy")) or []
    run = _load_cmd_output(cmd_to_file, "show running-config") or ""

    ipv6_svi_vlans: List[int] = []
    ra_if: Set[str] = set()
    dhg_if: Set[str] = set()
    ra_vlan_cfg = False
    dhg_vlan_cfg = False
    cur_if = ""
    cur_scope = ""          # "iface" | "vlan" (vlan-configuration mode) | "" (global / another stanza)
    cur_is_svi = False
    cur_has_v6 = False
    for raw in run.splitlines():
        m = re.match(r"^\s*interface\s+(\S+)", raw, re.IGNORECASE)
        if m:
            cur_if = normalize_ifname(m.group(1))
            cur_scope = "iface"
            cur_is_svi = bool(re.match(r"^(Vlan|Vl)\d+$", m.group(1), re.IGNORECASE))
            cur_has_v6 = False
            continue
        low = raw.strip().lower()
        if not low:
            continue
        # END of the interface block. `cur_if` was previously never cleared, so every later GLOBAL line was
        # credited to whatever interface happened to be seen last -- and `ipv6 nd raguard policy <NAME>` /
        # `ipv6 dhcp guard policy <NAME>` are the global policy-DEFINITION stanza HEADERS, which match the
        # attach patterns below. A box that DEFINES both policies and attaches NEITHER therefore reported
        # first-hop security in place on a real interface while being wide open to rogue RA / rogue DHCPv6
        # (absence rendered as health). Matched on the STRIPPED line, so an indentation-stripped capture
        # behaves identically to a normal one; `!` is the universal IOS/NX-OS stanza separator.
        if re.match(_FHS_BLOCK_END_RE, low):
            cur_if = ""
            cur_scope = "vlan" if low.startswith("vlan configuration") else ""
            continue
        if cur_scope == "iface":
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
        elif cur_scope == "vlan":
            # `vlan configuration <ids>` + `ipv6 dhcp guard attach-policy X` is a real VLAN-wide attachment:
            # it protects, but it names no interface -- credit PRESENCE, never a fabricated iface list.
            if re.match(r"^ipv6 nd raguard\b", low):
                ra_vlan_cfg = True
            if re.match(r"^ipv6 dhcp guard\b", low):
                dhg_vlan_cfg = True

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

    ra_present = bool(ra_if) or ra_vlan_attached or ra_vlan_cfg
    dhg_present = bool(dhg_if) or dhg_vlan_attached or dhg_vlan_cfg
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

# The literal strings a device prints INSTEAD of a capability advertisement. These mean "the TLV was
# absent", i.e. NO capabilities -- not "these are the capabilities". Lower-cased before the lookup.
# ('not advertised' is the same NX-OS/IOS-XE sentinel parse_neighbors_lldp already screens out of a
# neighbour's System Name, so the class is known to the codebase; it was just not applied here.)
_NO_CAPS_SENTINELS = {"not advertised", "n/a", "na", "null", "none", "-", "--"}


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
    # An LLDP capability TLV is OPTIONAL, and both IOS-XE and NX-OS render a missing one as literal
    # TEXT rather than an empty field ('not advertised' on 395 of the 838 LLDP neighbour records in
    # the Meridian collection; 'null' / 'N/A' elsewhere). Treating that text as a real advertisement made
    # the `if caps:` branch authoritative and SKIPPED the platform fallback the docstring above
    # promises for exactly this case -- so a neighbour that advertised NO capabilities could never
    # be classified infra no matter which switch/router family it named, and dropped silently out
    # of build_undocumented_neighbors (i.e. out of the shadow-infrastructure reconciliation, where
    # a missing candidate reads as 'no undocumented infrastructure found').
    if caps.lower() in _NO_CAPS_SENTINELS:
        caps = ""
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
    parsed = _safe_parse(parse_ip_routes, out)
    # ``ParsedRouteTable`` is deliberately falsy for a valid zero-row parse.  Do not let ``or {}`` erase its
    # current-run completeness receipt; parse-yield custody independently decides whether zero yield is usable.
    return parsed if isinstance(parsed, dict) else {}


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
            svi = (getattr(d, "svi_ip", "") or "").strip()
            ipmask = svi.split()
            if len(ipmask) >= 2:
                try:
                    nets.add(str(ipaddress.ip_network(f"{ipmask[0]}/{ipmask[1]}", strict=False)))
                    continue
                except ValueError:
                    pass
            if "/" in svi:                                   # NX-OS / IOS-XE slash form 'ip address 10.1.20.1/24'
                try:
                    nets.add(str(ipaddress.ip_network(svi, strict=False)))
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
    """Return an exact current-run projection for an in-scope route/next-hop closure.

    A destination inside an in-scope network can match a covering route *or* a more-specific route inside that
    network. Retaining only covering routes destroys longest-prefix-match truth and can invert a reachability
    verdict, so both directions of containment (all overlap) are required. All connected/local routes are retained
    to preserve next-hop ownership, and matching routes for recursive next hops are closed transitively. The default
    route is always relevant. The returned list subclass carries a non-serializable receipt used by Traffic
    Assurance; ordinary JSON lists cannot self-certify that they came from this full parsed-RIB projection.
    """
    raw_parse_receipt = getattr(route_db, "parse_receipt", None)
    parse_receipt_fields = (
        "schema", "complete", "candidate_rows", "parsed_rows", "unparsed_candidate_rows",
        "malformed_candidate_rows", "unexplained_candidate_rows", "ios_candidate_rows",
        "ios_parsed_rows", "ios_unparsed_rows", "nxos_prefix_blocks", "nxos_expected_ubest_rows",
        "nxos_via_candidate_rows", "nxos_parsed_via_rows", "nxos_unparsed_via_rows",
        "nxos_denominator_mismatch_blocks", "nxos_malformed_prefix_blocks",
        "ios_malformed_subnet_headers", "route_prefix_count", "route_entry_count", "routes_sha256",
        "incomplete_reasons",
    )
    source_parse_receipt = (
        {field: raw_parse_receipt.get(field) for field in parse_receipt_fields}
        if isinstance(raw_parse_receipt, dict) else None
    )
    source_entry_denominator = sum(
        len(info.get("entries", []))
        for info in route_db.values()
        if isinstance(info, dict) and isinstance(info.get("entries", []), list)
    )
    try:
        source_routes_digest = sha256(json.dumps(
            dict(route_db), ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
    except (TypeError, ValueError, UnicodeEncodeError):
        source_routes_digest = ""
    receipt_reasons = (source_parse_receipt or {}).get("incomplete_reasons")
    receipt_reasons_safe = (
        isinstance(receipt_reasons, list)
        and len(receipt_reasons) <= 16
        and all(isinstance(reason, str) and len(reason) <= 96 and reason.isascii()
                for reason in receipt_reasons)
    )
    source_parse_receipt_verified = (
        isinstance(route_db, ParsedRouteTable)
        and source_parse_receipt is not None
        and source_parse_receipt.get("schema") == "route_parse_receipt/1"
        and source_parse_receipt.get("route_prefix_count") == len(route_db)
        and source_parse_receipt.get("route_entry_count") == source_entry_denominator
        and bool(source_routes_digest)
        and source_parse_receipt.get("routes_sha256") == source_routes_digest
        and receipt_reasons_safe
    )
    nets: List[Any] = []   # IPv4Network | IPv6Network; Any keeps mypy at the package baseline
    for s in inscope:
        try:
            nets.append(ipaddress.ip_network(s, strict=False))
        except ValueError:
            pass
    scope_networks = sorted(str(net) for net in nets)
    source_prefix_count = 0
    source_entry_count = 0
    parsed: List[Tuple[Any, List[dict]]] = []
    keep_indexes: Set[int] = set()
    connected_sources = {"c", "l", "local", "connected", "direct", "attached", "directlyconnected"}
    for prefix, info in route_db.items():
        try:
            rnet = ipaddress.ip_network(prefix, strict=False)
        except ValueError:
            continue
        source_prefix_count += 1
        raw_entries = info.get("entries", []) if isinstance(info, dict) else []
        if not isinstance(raw_entries, list):
            raw_entries = []
        source_entry_count += len(raw_entries)
        entries = [entry for entry in raw_entries if isinstance(entry, dict)]
        index = len(parsed)
        parsed.append((rnet, entries))
        overlaps_scope = any(s.version == rnet.version and s.overlaps(rnet) for s in nets)
        locally_owned = any(
            str(entry.get("source") or "").strip().lower().replace(" ", "") in connected_sources
            for entry in entries
        )
        if rnet.prefixlen == 0 or overlaps_scope or locally_owned:
            keep_indexes.add(index)

    # Recursive routes can resolve a next hop through another non-connected route. Retain every matching prefix
    # (not just one representative) so longest-prefix and equal-cost choice remain available to the FIB owner.
    while True:
        next_hops = []
        for index in keep_indexes:
            for entry in parsed[index][1]:
                token = str(entry.get("next_hop") or "").split("%", 1)[0].strip()
                try:
                    next_hops.append(ipaddress.ip_address(token))
                except ValueError:
                    continue
        additions = {
            index for index, (network, _entries) in enumerate(parsed)
            if index not in keep_indexes
            and any(address.version == network.version and address in network for address in next_hops)
        }
        if not additions:
            break
        keep_indexes.update(additions)

    out: List[dict] = []
    seen: Set[tuple] = set()
    for index, (rnet, entries) in enumerate(parsed):
        if index not in keep_indexes:
            continue
        for e in entries:
            row = {"prefix": e.get("prefix", str(rnet)), "source": e.get("source", "") or "",
                   "next_hop": e.get("next_hop", "") or "", "out_intf": e.get("out_intf", "") or ""}
            if "admin_distance" in e:
                # Route selection must survive the scoped snapshot projection.  Presence is significant: an
                # absent AD permits fib's source-family fallback, while a malformed observed AD is retained so
                # fib can reject it rather than silently reclassifying bare BGP as eBGP AD 20.
                row["admin_distance"] = e.get("admin_distance")
            observed_ad = row.get("admin_distance")
            ad_key = ((type(observed_ad).__name__, observed_ad)
                      if isinstance(observed_ad, (str, int, float, bool, type(None)))
                      else (type(observed_ad).__name__,))
            key = (row["prefix"], row["source"], row["next_hop"], row["out_intf"],
                   "admin_distance" in row, ad_key)
            if key not in seen:
                seen.add(key)
                out.append(row)
    return ScopedRouteProjection(
        out,
        scope_networks=scope_networks,
        source_prefix_count=source_prefix_count,
        source_entry_count=source_entry_count,
        source_parse_receipt=source_parse_receipt,
        source_parse_receipt_verified=source_parse_receipt_verified,
    )


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
    # Coverage-honest active-port count: if NO physical port carries an observed link status (the
    # device's port up/down state was not collected — e.g. no 'show interfaces status'), the active
    # count is UNKNOWN -> None, not 0. A false 0 renders 0% utilization / all-ports-free and ranks the
    # device first as "most consolidation headroom" on the Capacity sheet. compute_capacity already
    # blanks util/free for a None count (test_compute_capacity_blanks_util_when_active_ports_unobserved).
    _status_seen = any((interfaces[p].status or "").strip() for p in physical)
    dp.active_ports = (sum(1 for p in physical if interfaces[p].status in ("connected", "up"))
                       if _status_seen else None)
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
    # Iterate in a DETERMINISTIC host order. all_cmd_to_files is populated in thread-COMPLETION order under
    # multi-worker collection (COLLECT_PARSE as_completed), so the first-writer-wins attribution below would
    # otherwise pick a different end_host_ip (on a MAC->IP conflict) and a different arp_source_switch
    # provenance run-to-run for the SAME evidence -- a reproducibility break on two persisted/displayed fields.
    # Sorting by hostname makes it order-independent ('lowest hostname wins' the tie). (Genuine MAC->IP conflicts
    # -- a moved host / overlapping-VRF ARP -- are inherently ambiguous; a subnet-containment tie-break is not
    # available here because interfaces/SVIs are parsed AFTER this phase, and it would not disambiguate the
    # common case where each switch reports an IP in its own connected subnet.)
    for hostname, cmd_to_file in sorted(all_cmd_to_files.items()):
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
        # CROSS-DEVICE means two DIFFERENT hostnames. Keying on (hostname, port) alone flagged a MAC seen
        # twice on ONE switch -- and step 7 of build_interfaces MANUFACTURES exactly that duplicate, copying
        # end_host_mac between a port-channel and each of its physical members. A single-homed endpoint
        # behind one switch's LAG then reported dual_connection='Yes': a redundancy claim with no second
        # home, which HIDES the single point of failure during move-group planning.
        if len({h for h, _ in unique}) > 1:
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
    tr_out = _load_cmd_output(cmd_to_file, *TRUNK_TABLE_CMD_VARIANTS)
    for p, v in _safe_parse(parse_show_interface_trunk_table, tr_out).items():
        interfaces.setdefault(p, InterfaceData(port=p))
        tstat = (v.get("status") or "")
        if tstat: interfaces[p].trunk_status = tstat
        if is_live_trunk_status(tstat): interfaces[p].switchport_mode = "Trunk"
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
    # A scoped ``show running-config ... interface`` capture cannot carry the global
    # ``vlan filter`` attachment that binds a VACL to an SVI.  Parse the full capture
    # independently, but project only parser-owned positive global forwarding evidence onto interfaces already
    # observed in the scoped capture. In particular, do not let the broader command create interface rows or
    # lend absence provenance to per-interface ACL fields.
    global_iface = (
        _safe_parse(parse_run_config_interfaces, global_run) if global_run else {}
    )
    global_vacl_by_iface = {
        p: row["vacl_policy"]
        for p, row in global_iface.items()
        if p in run_iface
        and isinstance(row, dict)
        and isinstance(row.get("vacl_policy"), str)
        and row["vacl_policy"]
    }
    global_forwarding_by_iface = {
        p: {
            field: row[field]
            for field in (
                "global_acl_in", "global_acl_out", "global_policy_gates", "trustsec_sgacl",
                "tcp_intercept", "flowspec_policy", "forwarding_gate_candidates",
                "forwarding_gate_unmodeled",
            )
            if isinstance(row.get(field), str) and row[field]
        }
        for p, row in global_iface.items()
        if p in run_iface and isinstance(row, dict)
        and any(isinstance(row.get(field), str) and row[field]
                for field in (
                    "global_acl_in", "global_acl_out", "global_policy_gates", "trustsec_sgacl",
                    "tcp_intercept", "flowspec_policy", "forwarding_gate_candidates",
                    "forwarding_gate_unmodeled",
                ))
    }
    # IOS-XE 16.x+ renamed the PortFast keyword: the global default is `spanning-tree portfast EDGE
    # bpduguard default` there, and the classic form on older IOS/IOS-XE. Matching only the classic
    # spelling read the newer platforms as "no global BPDU-Guard default" while the evidence was in
    # the collected running-config saying the opposite -- so every access port on those boxes carried
    # an EMPTY stp_bpduguard, which design_advisor/archreview both classify as NOT ASSESSED
    # ("BPDU Guard state was not captured"). Collected-and-protected therefore rendered as
    # not-observed; and on a box that also sets bpduguard on one interface explicitly, the
    # per-host `_bpdu_seen` gate flips and the rest of its ports become an OBSERVED unguarded gap
    # that does not exist. Measured on the Meridian collection: 25 devices / 647 access ports.
    global_bdg = bool(re.search(r"spanning-tree\s+portfast\s+(?:edge\s+)?bpduguard\s+default",
                                global_run, re.IGNORECASE))
    if global_bdg:
        logger.info(f"  [STP] Global portfast bpduguard default enabled on {hostname}")
    for p, v in run_iface.items():
        interfaces.setdefault(p, InterfaceData(port=p))
        interfaces[p].run_config_observed = True
        if v.get("desc") and not interfaces[p].description:
            interfaces[p].description = v["desc"]
        if v.get("bpduguard"):
            interfaces[p].stp_bpduguard = v["bpduguard"]
        elif global_bdg and interfaces[p].switchport_mode in ("Access",""):
            interfaces[p].stp_bpduguard = "Enable"
        if v.get("rootguard"): interfaces[p].stp_rootguard = v["rootguard"]
        if v.get("vrf"):       interfaces[p].vrf            = v["vrf"]
        if v.get("ip_addr"):   interfaces[p].svi_ip         = v["ip_addr"]  # NEW-V14.3
        if isinstance(v.get("ip_addresses"), list):
            interfaces[p].svi_ips = ";".join(str(item) for item in v["ip_addresses"] if str(item).strip())
        if v.get("acl_in"):    interfaces[p].acl_in         = v["acl_in"]
        if v.get("acl_out"):   interfaces[p].acl_out        = v["acl_out"]
        if v.get("acl_in_unmodeled"): interfaces[p].acl_in_unmodeled = v["acl_in_unmodeled"]
        if v.get("acl_out_unmodeled"): interfaces[p].acl_out_unmodeled = v["acl_out_unmodeled"]
        global_forwarding = global_forwarding_by_iface.get(p, {})
        if global_forwarding.get("global_acl_in"):
            interfaces[p].global_acl_in = global_forwarding["global_acl_in"]
        if global_forwarding.get("global_acl_out"):
            interfaces[p].global_acl_out = global_forwarding["global_acl_out"]
        if global_forwarding.get("global_policy_gates"):
            interfaces[p].global_policy_gates = global_forwarding["global_policy_gates"]
        if v.get("mtu"):       interfaces[p].mtu            = v["mtu"]   # NEW-V3.23.49 (path-MTU)
        if v.get("link_mtu"):  interfaces[p].link_mtu       = v["link_mtu"]
        if v.get("ip_mtu"):    interfaces[p].ip_mtu         = v["ip_mtu"]
        if v.get("mtu_semantics"): interfaces[p].mtu_semantics = v["mtu_semantics"]
        if v.get("pbr_policy"): interfaces[p].pbr_policy     = v["pbr_policy"]
        if v.get("urpf_mode"): interfaces[p].urpf_mode       = v["urpf_mode"]
        if v.get("security_zone"): interfaces[p].security_zone = v["security_zone"]
        if v.get("service_policy_in"): interfaces[p].service_policy_in = v["service_policy_in"]
        if v.get("service_policy_out"): interfaces[p].service_policy_out = v["service_policy_out"]
        if v.get("inspection_policy_in"): interfaces[p].inspection_policy_in = v["inspection_policy_in"]
        if v.get("inspection_policy_out"): interfaces[p].inspection_policy_out = v["inspection_policy_out"]
        if v.get("crypto_map"): interfaces[p].crypto_map = v["crypto_map"]
        if v.get("tunnel_protection"): interfaces[p].tunnel_protection = v["tunnel_protection"]
        for field in (
                "trustsec_sgacl", "wccp_redirection_in", "wccp_redirection_out",
                "tcp_intercept", "mpls_forwarding", "mpls_mtu", "flowspec_policy",
                "ips_policy_in", "ips_policy_out", "admission_policy",
                "forwarding_gate_candidates", "forwarding_gate_unmodeled"):
            scoped_value = v.get(field)
            global_value = global_forwarding.get(field)
            tokens = set()
            for value in (scoped_value, global_value):
                if isinstance(value, str):
                    tokens.update(token for token in value.split(",") if token)
            if tokens:
                setattr(
                    interfaces[p], field,
                    ",".join(sorted(tokens, key=lambda token: (token.casefold(), token))),
                )
        if forwarding_gate_candidate_projection_incomplete(interfaces[p]):
            tokens = set(filter(None, interfaces[p].forwarding_gate_unmodeled.split(",")))
            tokens.add("candidate_projection_incomplete")
            interfaces[p].forwarding_gate_unmodeled = ",".join(
                sorted(tokens, key=lambda token: (token.casefold(), token))
            )
        vacl_policy = v.get("vacl_policy") or global_vacl_by_iface.get(p, "")
        if vacl_policy: interfaces[p].vacl_policy = vacl_policy
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
        # `neighbor_switch_vtp_domain` used to be filled with switch_identity['vtp_domain'] -- THIS
        # switch's own domain, copied onto a column that claims to describe the NEIGHBOUR. It sits
        # beside `current_switch_vtp_domain`, which step 12 sets from the same value, so the pair was
        # identical by construction on every inter-switch link (367 of 367 rows on the Meridian collection):
        # a reader comparing the two columns to spot a VTP-domain mismatch could only ever conclude
        # "every trunk agrees" -- a health claim manufactured from a self-copy, never observed.
        # The neighbour's real domain IS advertised ('show cdp neighbors detail' carries a
        # `VTP Management Domain[ Name]:` line, and the Meridian captures show it genuinely differing
        # between neighbours), but extracting it belongs to parse.parse_neighbors_cdp -- the owner of
        # that block format -- not to this join layer. Until it is parsed there, the honest value is
        # "not observed": an empty column cannot be misread as a match.
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
        # `neighbor_switch_serial` used to be filled with d.cdp_neighbor -- the neighbour's HOSTNAME,
        # written into a column labelled "Neighbor Switch Serial" (581 rows on the Meridian collection where
        # the two were byte-identical). No serial was ever observed; CDP only embeds one in the
        # `Device ID: host(FOC1912R0XH)` form, which parse_neighbors_cdp keeps verbatim inside
        # device_id rather than splitting out. A hostname in a serial column is a fabricated
        # identifier at the asset-reconciliation step (and --redact's _REDACT_SERIAL_KEYS then
        # pseudonymised those hostnames to SNxxxx while keeping hostnames everywhere else). The
        # neighbour's name is already published in its OWN column (`cdp_neighbor`), so leaving this
        # one empty loses nothing real and stops the column asserting evidence that does not exist.
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
                # `''.split()` is [], so the old `.split()[0]` raised IndexError for an SVI with NO
                # configured address -- and this runs inside a sort KEY, so the exception escapes
                # build_interfaces and (under the default multi-worker parse) the whole device is
                # dropped with a logged "[FAIL] Parse exception", leaving it in the snapshot with
                # ZERO interfaces: absence rendered as "this switch has no ports". Reachable whenever
                # the run-config channel did not land (TACACS command-authorization denying
                # `show running-config` is screened as an error by _load_cmd_output, so svi_ip is
                # empty on every SVI) while `show ip route` DID -- and equally for a real SVI with no
                # IPv4 address (unnumbered / DHCP / v6-only) that a static route exits by interface.
                _svi_tok = (d.svi_ip or '').split()
                ipv = _svi_tok[0].split('/')[0] if _svi_tok else ''
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
