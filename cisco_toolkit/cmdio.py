"""Command-output I/O glue: load a collected show-command's output from disk
(skipping empty/error captures via _CISCO_ERRORS) and run section parsers
fail-soft. Leaf layer: depends only on stdlib (os, logging, threading, typing).
Extracted verbatim from COLLECT_PARSE_V3_23_0.py in PHASE 2.7 step 14 (behaviour
byte-identical). This is the helper nearly every build_* / compute_* / write_*
leans on to read collected output, so it's homed before the I/O-fed analyze
functions move.

Parse-yield telemetry and compact positive parse receipts (Plan A / Tier-1 #3) also live here, at the one
chokepoint every builder already goes through. The #1 recurring bug class: an
unseen platform variant parses to []/{} — byte-identical to "feature absent"
everywhere downstream (a real NX-OS ubest/mbest RIB once zeroed this way and
survived four audit waves). The ledger records every parser call whose input had
REAL CONTENT but whose output carried 0 entities. Coverage-honest by design: an
event means "collected-but-unparsed evidence — possible parser format gap",
NEVER a device state verdict; absent / error captures are the Collection
Completeness axis's domain and are not counted here."""
import logging
import os
import threading
from typing import Dict, List

from .input_custody import read_text as read_custodied_text

logger = logging.getLogger(__name__)

_CISCO_ERRORS = (
    "% invalid", "% command not found",
    "% incomplete command", "% unknown command",
    "% ambiguous command", "% ip routing not enabled",
    "% routing not enabled", "invalid input detected",
    "error: invalid", "% requires vrf", "% vrf does not exist",
    # AUTHORIZATION denials (audit-6 coverage-honesty): a narrow read-only RBAC / TACACS+ command-authz
    # account -- which the security doctrine RECOMMENDS -- hitting a privileged `show` gets one of these
    # banners as the ENTIRE command output. Unfiltered it was NON-EMPTY text, so a device whose logs were
    # never actually read scored collected=True/0-events -> certified as having clean logs (false health on
    # the very `show logging` family doctrine #3 names). These forms are exact / '% '-anchored so a legit
    # DEEP syslog line ('%SEC-6-IPACCESSLOGP: ... permission denied') is never matched. Verified banner text:
    # NX-OS RBAC '% Permission denied for the role'; IOS exec '% Authorization failed.'; IOS/NX-OS per-command.
    "% permission denied for the role", "% authorization failed", "command authorization failed",
)

# --- zero-parse yield ledger ------------------------------------------------------
MIN_CONTENT_LINES = 3      # a 1-2 line banner / prompt echo is not "content" ...
MIN_CONTENT_CHARS = 200    # ... but a single-line controller-REST JSON blob is
_YIELD_EVENT_CAP = 500     # verbatim events kept; counters always keep the full truth

# Parsers for which zero-entities-on-real-content is a NORMAL healthy state. Their
# events stay visible in the ledger but OUT of the suspect count, so the red row never
# cries wolf. Two classes, seeded empirically from the synthetic-fixture run:
MAY_BE_EMPTY_PARSERS = frozenset({
    # 1) run-config-scoped parsers: a running-config always has CONTENT, but the specific
    #    feature section (ACLs / NAT / object-groups / redistribution / hygiene or
    #    hardening findings) is legitimately absent on many healthy devices — zero out of
    #    a real config is not a format-gap signal by itself. (parse_run_config_interfaces
    #    is deliberately NOT here: every real config has interface blocks, so zero IS
    #    suspect for it.)
    "parse_acls", "parse_object_groups", "parse_nat", "parse_security",
    "parse_config_hygiene", "parse_redistribution",
    # 2) state commands that print a header / legend even when empty-healthy:
    "parse_spanning_tree_blockedports",   # no blocked ports is the healthy state
    "parse_acl_hitcounts",                # ACLs defined but never matched print 0 rows
    "parse_policymap_drops",              # zero egress drops is the goal state
    "parse_copp_drops",                   # zero CoPP drops likewise
    "parse_igmp_groups",                  # no receivers joined is normal off-hours
})

_YIELD_LOCK = threading.Lock()
_PER_PARSER: Dict[str, Dict[str, int]] = {}
_EVENTS: List[dict] = []
_RECEIPTS: Dict[tuple, Dict[str, int]] = {}
_EVENTS_TRUNCATED = False
_TL = threading.local()    # .last_load = (cmd, path, chars, lines) — load→parse pairing

_UNATTRIBUTED = "[unattributed]"


# === PARSER_CONTRACTS =============================================================
# The command -> parser CONTRACT for the SSH `show`-command channel (the CLI-text surface
# that suffers the recurring "collected-but-unparsed / format-fidelity" drift this module's
# ledger exists to catch). Each key is a literal command dispatched via
# _load_cmd_output(cmd_to_file, ...) in build.py; each value is the tuple of parse_*
# functions that consume it -- usually one, but `show running-config` legitimately feeds
# several feature-section parsers and `show ip mroute` two. Variant spellings that fall
# back to the same output map to the same parser tuple.
#
# This is an AS-BUILT / coverage contract, NOT the runtime dispatcher -- build.py still
# calls the parsers directly. tests/test_parser_contracts.py reconciles this dict against
# build.py's own source (every named parser exists & is callable; no phantom command;
# every inline `_safe_parse(parse_X, _load_cmd_output(cmd_to_file, "show ..."))` is
# registered with parse_X) so the two cannot silently drift. Deliberately scoped to
# `show ` commands: the controller-REST / cloud channels (moquery, dataservice/, api/,
# aws, get system ...) are a structured-JSON path with different failure modes and are
# out of this contract. A handful of `show` reads with no dedicated parse_* (raw syslog
# logfile, `show ip interface brief` mgmt-IP scrape) are intentionally absent too.
PARSER_CONTRACTS = {
    # platform / control-plane health & identity
    "show processes cpu": ("parse_cpu_utilization",),
    "show processes memory": ("parse_memory_stats",),
    "show system resources": ("parse_system_resources",),
    "show version": ("parse_show_version",),
    "show inventory": ("parse_show_inventory",),
    "show module": ("parse_show_module_count",),
    "show environment": ("parse_show_environment",),
    "show environment all": ("parse_show_environment",),
    "show environment power": ("parse_show_environment_power",),
    "show power": ("parse_show_environment_power",),
    "show power inline": ("parse_show_power_inline",),
    "show vtp status": ("parse_vtp_status",),
    # running-config: one command, many feature-section parsers
    "show running-config": ("parse_acls", "parse_object_groups", "parse_nat", "parse_security",
                            "parse_config_hygiene", "parse_redistribution", "parse_run_config_interfaces"),
    "show running-config | section ^interface": ("parse_run_config_interfaces",),
    # spanning-tree / redundancy
    "show spanning-tree": ("parse_spanning_tree_root",),
    "show spanning-tree blockedports": ("parse_spanning_tree_blockedports",),
    "show spanning-tree inconsistentports": ("parse_spanning_tree_blockedports",),
    "show vpc": ("parse_vpc",),
    "show vpc role": ("parse_vpc_role",),
    "show lacp neighbor": ("parse_nxos_lacp_neighbors",),
    "show standby all": ("parse_hsrp_detail",),
    "show standby": ("parse_hsrp_detail",),
    "show standby brief": ("parse_hsrp_summary",),
    "show hsrp brief": ("parse_hsrp_summary",),
    "show hsrp all": ("parse_hsrp_summary",),
    "show vrrp brief": ("parse_vrrp_summary",),
    "show glbp brief": ("parse_glbp_summary",),
    # overlay (VXLAN / EVPN) & SP/MPLS
    "show nve peers": ("parse_nve_peers",),
    "show nve vni": ("parse_nve_vni",),
    "show bgp l2vpn evpn summary": ("parse_evpn_summary",),
    "show mpls ldp neighbor": ("parse_mpls_ldp_neighbors",),
    "show bgp vpnv4 unicast summary": ("parse_bgp_vpnv4_summary",),
    "show mpls l2transport vc": ("parse_mpls_l2vpn_vc",),
    # SD-Access / TrustSec / tunnels / crypto
    "show lisp session": ("parse_lisp_sessions",),
    "show cts environment-data": ("parse_cts_environment_data",),
    "show dmvpn": ("parse_dmvpn_peers",),
    "show crypto session": ("parse_crypto_sessions",),
    # firewall (ASA) & multi-vendor
    "show failover": ("parse_asa_failover",),
    "show resource usage": ("parse_asa_resource_usage",),
    "show mlag": ("parse_arista_mlag",),
    "show mlag interfaces detail": ("parse_arista_mlag_interfaces",),
    "show lacp peer": ("parse_arista_lacp_peer",),
    "show bgp evpn summary": ("parse_arista_bgp_evpn_summary",),
    "show chassis cluster status": ("parse_junos_chassis_cluster",),
    # multicast & timing
    "show ip mroute": ("parse_mroute_entries", "parse_multicast_info"),
    "show ip pim rp mapping": ("parse_pim_rp_mapping",),
    "show ip pim neighbor": ("parse_pim_neighbors",),
    "show ip pim interface": ("parse_multicast_info",),
    "show ip igmp snooping querier": ("parse_igmp_snooping_querier",),
    "show ptp clock": ("parse_ptp_clock",),
    "show ptp parent": ("parse_ptp_clock",),
    # BFD & IPv6
    "show bfd neighbors": ("parse_bfd_neighbors",),
    "show ipv6 interface": ("parse_ipv6_interface_addrs",),
    "show ipv6 route summary": ("parse_ipv6_route_summary",),
    "show ospfv3 neighbor": ("parse_ospfv3_neighbors",),
    "show ospfv3 neighbors": ("parse_ospfv3_neighbors",),
    "show ipv6 ospfv3 neighbors": ("parse_ospfv3_neighbors",),
    "show ipv6 ospf neighbor": ("parse_ospfv3_neighbors",),
    "show bgp ipv6 unicast summary": ("parse_bgp_ipv6_summary",),
    "show ipv6 nd raguard policy": ("parse_ipv6_raguard_policy",),
    "show ipv6 dhcp guard policy": ("parse_ipv6_dhcp_guard_policy",),
    # routing control & data plane
    "show ip ospf neighbor": ("parse_ospf_neighbors",),
    "show ip eigrp neighbors": ("parse_eigrp_neighbors",),
    "show ip bgp summary": ("parse_bgp_summary",),
    "show bgp summary": ("parse_bgp_summary",),
    "show ip route": ("parse_ip_routes",),
    "show ip route vrf all": ("parse_ip_routes",),
    "show ip bgp": ("parse_bgp_table",),
    "show bgp ipv4 unicast": ("parse_bgp_table",),
    # NTP / access-edge / QoS
    "show ntp status": ("parse_ntp_status",),
    "show ntp peer-status": ("parse_ntp_status",),
    "show port-security interface": ("parse_port_security_detail",),
    "show storm-control": ("parse_storm_control",),
    "show policy-map interface": ("parse_policymap_drops",),
    "show policy-map interface control-plane": ("parse_copp_drops",),
    "show ip access-lists": ("parse_acl_hitcounts",),
    # adjacency discovery
    "show cdp neighbors detail": ("parse_neighbors_detail",),
    "show lldp neighbors detail": ("parse_neighbors_detail",),
    # interfaces / switchport / VRF / port-channel / MAC / VLAN
    "show interface status": ("parse_show_interface_status",),
    "show interface switchport": ("parse_show_interface_switchport",),
    "show interfaces switchport": ("parse_show_interface_switchport",),
    "show interface trunk": ("parse_show_interface_trunk_table",),
    "show interfaces trunk": ("parse_show_interface_trunk_table",),
    "show vrf interface": ("parse_show_vrf_interface",),
    "show ip vrf interface": ("parse_show_vrf_interface",),
    "show ip vrf interfaces": ("parse_show_vrf_interface",),
    "show port-channel summary": ("parse_portchannel_protocol_from_summary",),
    "show etherchannel summary": ("parse_portchannel_protocol_from_summary",),
    "show mac address-table": ("parse_show_mac_address_table",),
    "show vlan brief": ("parse_vlan_brief",),
}


def parser_for(cmd):
    """The parse_* function name(s) that consume `cmd`, or () if it is not a registered
    `show`-channel command. Read-only convenience over PARSER_CONTRACTS."""
    return PARSER_CONTRACTS.get(cmd, ())


# === PARSER_RETURN_SHAPE ==========================================================
# Every parse_* in cisco_toolkit.parse -> its empty-container SHAPE, so _safe_parse's
# fail-soft fallback returns the RIGHT empty default for the parser instead of a hard-wired
# {} (the "{}-vs-[] hazard": a list-returning parser that RAISED used to yield {}, which is
# the wrong empty shape and can corrupt a downstream consumer expecting a list). Frozen here
# because cmdio is a leaf module and must not import parse; tests/test_parser_return_shapes.py
# reconciles this table against the live return annotations AND the build.py call-site
# defaults, so it can never silently drift from reality.
_DICT_PARSERS = (
    "parse_aci_health", "parse_acls", "parse_arista_mlag", "parse_asa_failover", "parse_auth_sessions",
    "parse_config_hygiene", "parse_cpu_utilization", "parse_cts_environment_data",
    "parse_dhcp_snooping_binding", "parse_etherchannel_protocol_ios", "parse_etherchannel_summary_members",
    "parse_fmc_ha_status", "parse_fmc_server_version", "parse_fortigate_ha_status", "parse_glbp_summary",
    "parse_hsrp_detail", "parse_hsrp_summary", "parse_interface_phy", "parse_ip_routes",
    "parse_ipv6_route_summary", "parse_memory_stats", "parse_multicast_info", "parse_nat",
    "parse_neighbors_cdp", "parse_neighbors_lldp", "parse_ntp_status", "parse_object_groups",
    "parse_pim_rp_mapping", "parse_port_security", "parse_port_security_detail",
    "parse_portchannel_protocol_from_summary", "parse_ptp_clock", "parse_qos_config",
    "parse_run_config_interfaces", "parse_security", "parse_show_environment", "parse_show_environment_power",
    "parse_show_interface_counters", "parse_show_interface_status", "parse_show_interface_switchport",
    "parse_show_interface_trunk_table", "parse_show_inventory", "parse_show_ip_arp",
    "parse_show_mac_address_table", "parse_show_power_inline", "parse_show_version", "parse_show_vrf_interface",
    "parse_spanning_tree_blockedports", "parse_spanning_tree_detail", "parse_spanning_tree_root",
    "parse_spanning_tree_states", "parse_system_resources", "parse_vlan_brief", "parse_vpc",
    "parse_vpc_role",
    "parse_vrrp_summary",
)
_LIST_PARSERS = (
    "parse_aci_bds", "parse_aci_epgs", "parse_aci_fabric_nodes", "parse_aci_faults", "parse_aci_tenants",
    "parse_aci_vrfs", "parse_acl_hitcounts", "parse_arista_bgp_evpn_summary",
    "parse_arista_lacp_peer", "parse_arista_mlag_interfaces", "parse_asa_resource_usage",
    "parse_aws_security_groups",   # annotation-less (list-or-None), guarded by an isinstance at its call site
    "parse_bfd_neighbors", "parse_bgp_ipv6_summary",
    # the neighbour parsers return List[Dict[...]] (a LIST of dicts, not a dict) -- their call sites `or []`:
    "parse_bgp_summary", "parse_eigrp_neighbors", "parse_neighbors_detail", "parse_ospf_neighbors",
    "parse_bgp_table", "parse_bgp_vpnv4_summary", "parse_copp_drops", "parse_crypto_sessions",
    "parse_dmvpn_peers", "parse_evpn_summary", "parse_fmc_deployable", "parse_fmc_devices",
    "parse_fmc_ha_pairs", "parse_igmp_groups", "parse_igmp_snooping_querier", "parse_ipv6_dhcp_guard_policy",
    "parse_ipv6_interface_addrs", "parse_ipv6_raguard_policy", "parse_ise_nodes", "parse_junos_chassis_cluster",
    "parse_lisp_sessions", "parse_mpls_l2vpn_vc", "parse_mpls_ldp_neighbors", "parse_mroute_entries",
    "parse_nve_peers", "parse_nve_vni", "parse_nxos_lacp_neighbors", "parse_ospfv3_neighbors", "parse_pim_neighbors",
    "parse_policymap_drops", "parse_redistribution", "parse_sdwan_control_connections", "parse_sdwan_devices",
    "parse_sdwan_omp_counters", "parse_storm_control", "parse_syslog_events",
)
PARSER_RETURN_SHAPE = {
    **{n: "dict" for n in _DICT_PARSERS},
    **{n: "list" for n in _LIST_PARSERS},
    # scalar parsers (called directly, never via _safe_parse's default path) -- registered for totality:
    "parse_switch_mgmt_ip": "str", "parse_vtp_status": "str", "parse_show_module_count": "int",
}

_EMPTY_BY_SHAPE = {"dict": dict, "list": list, "str": str, "int": int}


def _empty_for(fn) -> object:
    """The correct empty default for parser `fn` on a fail-soft miss: a fresh {} / [] / '' / 0
    by its registered return shape. Unknown parsers fall back to {} -- the historical default,
    so this is strictly backward-compatible."""
    return _EMPTY_BY_SHAPE.get(PARSER_RETURN_SHAPE.get(getattr(fn, "__name__", ""), "dict"), dict)()


def reset_parse_ledger() -> None:
    """Start-of-run reset (also clears this thread's pairing stash)."""
    global _EVENTS_TRUNCATED
    with _YIELD_LOCK:
        _PER_PARSER.clear()
        _EVENTS.clear()
        _RECEIPTS.clear()
        _EVENTS_TRUNCATED = False
    if hasattr(_TL, "last_load"):
        del _TL.last_load


def parse_yield_report() -> dict:
    """The deterministic, snapshot-ready ledger view (published as snap['parse_yield']).
    Wording is deliberately coverage-honest — see the module docstring."""
    with _YIELD_LOCK:
        per_parser = {
            name: dict(counts, may_be_empty=(name in MAY_BE_EMPTY_PARSERS))
            for name, counts in sorted(_PER_PARSER.items())
        }
        events = sorted(_EVENTS, key=lambda e: (e["parser"], e["device"], e["cmd"], e["file"]))
        receipts = [
            {"parser": parser, "device": device, "cmd": cmd, **counts}
            for (parser, device, cmd), counts in sorted(_RECEIPTS.items())
        ]
        suspect = sum(c["zero_yield"] for n, c in _PER_PARSER.items()
                      if n not in MAY_BE_EMPTY_PARSERS)
        expected = sum(c["zero_yield"] for n, c in _PER_PARSER.items()
                       if n in MAY_BE_EMPTY_PARSERS)
        errors = sum(c["errors"] for c in _PER_PARSER.values())
        return {
            "summary": {
                "parsers_called": len(per_parser),
                "zero_yield_suspect": suspect,
                "zero_yield_expected": expected,
                "parse_errors": errors,
                "note": ("Zero-yield = the command returned CONTENT but its parser produced 0 "
                         "entities: collected-but-unparsed evidence, a possible platform-variant "
                         "format gap in the parser — never a device state verdict. Absent or "
                         "error-captured commands are the Collection Completeness axis's domain "
                         "and are not counted here."),
            },
            "per_parser": per_parser,
            "events": events,
            "events_truncated": _EVENTS_TRUNCATED,
            # One aggregate per exact parser/device/command representation.  Unlike ``events`` this includes
            # successful non-empty parses and is not capped, so custody consumers cannot be masked by a
            # different host's successful call.  Paths and bodies are never published.
            "receipts": receipts,
        }


def _record_yield(fn, args, result, error: bool) -> None:
    """Telemetry only — must NEVER raise into the fail-soft parse path."""
    global _EVENTS_TRUNCATED
    try:
        name = getattr(fn, "__name__", repr(fn))
        text = next((a for a in args if isinstance(a, str)), None)
        chars = len(text) if text else 0
        lines = (text.count("\n") + 1) if text else 0
        with_content = text is not None and bool(text.strip()) and (
            lines >= MIN_CONTENT_LINES or chars >= MIN_CONTENT_CHARS)
        entities = len(result) if isinstance(result, (dict, list, tuple, set)) else None
        last = getattr(_TL, "last_load", None)
        if last is not None and last[2] == chars:   # len-verified: same text this thread loaded
            cmd, path = last[0], last[1]
            device = os.path.basename(os.path.dirname(path)) or _UNATTRIBUTED
            fname = os.path.basename(path)
        else:
            cmd, device, fname = _UNATTRIBUTED, _UNATTRIBUTED, ""
        with _YIELD_LOCK:
            pp = _PER_PARSER.setdefault(
                name, {"calls": 0, "with_content": 0, "zero_yield": 0, "errors": 0})
            pp["calls"] += 1
            if not with_content:
                return                      # absent/trivial input: Collection Completeness's domain
            pp["with_content"] += 1
            receipt = _RECEIPTS.setdefault(
                (name, device, cmd), {"calls": 0, "with_entities": 0, "zero_yield": 0, "errors": 0})
            receipt["calls"] += 1
            if error:
                pp["errors"] += 1
                receipt["errors"] += 1
            elif entities == 0:
                pp["zero_yield"] += 1
                receipt["zero_yield"] += 1
            else:
                receipt["with_entities"] += 1
                return                      # entities came out (or an unsized result): no event
            if len(_EVENTS) >= _YIELD_EVENT_CAP:
                _EVENTS_TRUNCATED = True
                return
            _EVENTS.append({"parser": name, "device": device, "cmd": cmd, "file": fname,
                            "lines_in": lines, "error": error})
    except Exception:
        pass


def _load_cmd_output(cmd_to_file: Dict[str, str], *cmd_variants: str) -> str:
    for cmd in cmd_variants:
        p = cmd_to_file.get(cmd)
        if p:
            try:
                content = read_custodied_text(
                    p, encoding="utf-8", errors="ignore")
                stripped = content.strip()
                if not stripped: continue
                first_chunk = stripped[:200].lower()
                if any(pat in first_chunk for pat in _CISCO_ERRORS): continue
                try:  # pairing stash for the yield ledger — never let telemetry break a load
                    _TL.last_load = (cmd, p, len(content), content.count("\n") + 1)
                except Exception:
                    pass
                return content
            except Exception as e:
                logger.debug(f"_load_cmd_output: failed reading {p} for '{cmd}': {e}")  # NEW-V3.23.1
    return ""


# ONE owner of the trunk-table command variants (build.py's loader + analyze's capture-gap check
# must resolve the SAME command or the abstention disclosure drifts from what was actually parsed).
TRUNK_TABLE_CMD_VARIANTS = ("show interface trunk", "show interfaces trunk")


def cmd_capture_state(cmd_to_file: Dict[str, str], *cmd_variants: str) -> str:
    """Coverage state of a command's capture across its variants: 'usable' | 'empty' | 'error' |
    'missing'. Mirrors _load_cmd_output's resolution (same cmd_to_file keys, same _CISCO_ERRORS
    screen) so the two can never disagree about what was loadable -- but where _load_cmd_output
    collapses empty/error/missing to '', this keeps them apart, because they mean DIFFERENT things
    for coverage-honesty: a captured-but-EMPTY output is an answer (e.g. a zero-trunk device),
    while a missing or errored capture is a blind spot ('not observed' must never read as healthy).
    Precedence across variants: usable > empty > error > missing."""
    best = "missing"
    rank = {"missing": 0, "error": 1, "empty": 2, "usable": 3}
    for cmd in cmd_variants:
        p = cmd_to_file.get(cmd)
        if not p:
            continue
        try:
            content = read_custodied_text(
                p, encoding="utf-8", errors="ignore")
        except Exception:
            continue
        stripped = content.strip()
        if not stripped:
            state = "empty"
        elif any(pat in stripped[:200].lower() for pat in _CISCO_ERRORS):
            state = "error"
        else:
            state = "usable"
        if rank[state] > rank[best]:
            best = state
        if best == "usable":
            break
    return best


def _safe_parse(fn, *args, _default=None):
    """FIX-V3.23.6 (P1): run a section parser fail-soft. If it raises on a
    malformed/unexpected block, log a breadcrumb and return _default so build_interfaces
    keeps the rest of the device's data instead of losing the whole device to one bad
    section. When no _default is given the fallback is the parser's OWN empty shape
    (_empty_for: [] for a list parser, {} for a dict parser) rather than a blanket {},
    closing the {}-vs-[] hazard. Happy path is unchanged - value-preserving."""
    try:
        result = fn(*args)
    except Exception as e:
        logger.warning(f"  [parse] {getattr(fn, '__name__', repr(fn))} failed: {e!r}; section skipped")
        result = _empty_for(fn) if _default is None else _default
        _record_yield(fn, args, result, error=True)
        return result
    _record_yield(fn, args, result, error=False)
    return result
