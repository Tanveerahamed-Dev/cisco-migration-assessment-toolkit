"""The analyze layer's scoring foundation: the health-score / migration-readiness
tunables (`ScoringConfig` + the module-default `SCORING`) plus the two small pure
helpers every `compute_*` leans on (`_health_band`, `_host_role`). Depends only on
`dataclasses`, stdlib `re`/`typing`, and `cisco_toolkit.model`. Extracted verbatim
from COLLECT_PARSE_V3_23_0.py in PHASE 2.7 step 10 (behaviour byte-identical).

The `compute_*` functions themselves follow in later steps (they entangle with the
`_load_cmd_output` I/O helper that still lives in the monolith). The Excel
fill-colour maps (`_READY_FILL`/`_STATUS_FILL`) and sheet-name constants stay
behind too - they belong to the excel layer, not the data analysis."""
import ipaddress
import re
from functools import lru_cache
from dataclasses import dataclass, field as _dcfield   # aliased: 'field' is a common loop var elsewhere (avoids F402 shadowing)
from typing import Any, Dict, List, Optional, Tuple

from cisco_toolkit import portdb, protocol_kb
from cisco_toolkit.bgp_intent import validate_bgp_configured_peer_baseline
from cisco_toolkit.fhrp_intent import validate_fhrp_configured_group_baseline
from cisco_toolkit.fhrp_redundancy import (
    scope_fhrp_redundancy_domains,
    validate_fhrp_redundancy_domain_baseline,
)
from cisco_toolkit.vtp_safety import validate_vtp_safety_baseline
from cisco_toolkit.ipv6_routing import validate_ipv6_routing_adjacency_baseline
from cisco_toolkit.cmdio import TRUNK_TABLE_CMD_VARIANTS, _load_cmd_output, cmd_capture_state
from cisco_toolkit.model import DevicePhysical, InterfaceData
from cisco_toolkit.parse import (
    _parse_fhrp, _is_physical_port, parse_spanning_tree_blockedports,
    parse_spanning_tree_root, parse_spanning_tree_states,
    parse_ospf_neighbors, parse_bgp_summary,
    parse_eigrp_neighbors, parse_syslog_events, parse_qos_config,
)
from cisco_toolkit.textutils import (
    NATIVE1_CFG_BASIS, NATIVE1_CFG_UNIT, NATIVE1_OPS_BASIS, NATIVE1_OPS_SWITCH_UNIT, NATIVE1_OPS_UNIT,
    PHYSICAL_IFACE_RE, _as_num, _split_macs, is_finite_num, is_live_trunk_status, is_trunk_mode,
    normalize_ifname)


# score band -> (label, fill)
_HEALTH_BANDS = [(90, "Excellent", "36E08A"), (75, "Good", "7ADB8F"),
                 (60, "Fair", "FFE566"), (40, "Poor", "FF9F45"), (0, "Critical", "FF5775")]

# Default/global IPv4-unicast only.  The two explicit NX-OS forms precede the
# historic generic fallbacks so a multi-AF ``show bgp summary`` cannot silently
# authorize an IPv4 peer.  ``_load_cmd_output`` skips captured CLI errors and
# selects the first usable variant.
BGP_IPV4_SUMMARY_COMMANDS = (
    "show bgp ipv4 unicast summary",
    "show bgp ip unicast summary",
    "show ip bgp summary",
    "show bgp summary",
)


@dataclass(frozen=True)
class ScoringConfig:
    """NEW-V3.23.4: every health-score + migration-readiness tunable in one typed
    place (these were hard-coded as function-local dicts). The defaults reproduce
    the prior behaviour byte-for-byte; build a ScoringConfig(...) to recalibrate
    and pass it to compute_health_scores / compute_migration_readiness. The .md
    flags these as 'a defensible default, not calibrated - tune to taste.'"""
    # Per-finding deduction weights, by layer/category.
    l1_weights: Dict[str, int] = _dcfield(default_factory=lambda: {
        "err-disabled": 8, "single-fiber-uplink": 10, "error-rate-high": 5, "half-duplex": 8})
    l3_weights: Dict[str, int] = _dcfield(default_factory=lambda: {
        "single-gateway": 10, "no-FHRP": 3, "tracked-object-down": 12})
    xl_weights: Dict[str, int] = _dcfield(default_factory=lambda: {
        "Critical": 18, "High": 10, "Medium": 4, "Low": 2})
    proto_weights: Dict[str, int] = _dcfield(default_factory=lambda: {
        "High": 10, "Medium": 4})
    # NEW-V3.23.60: per-severity deduction for a FAILED CIS-aligned config-hardening check
    # (parse_security). Config/security posture is technical debt that lowers migration health;
    # only assessed on devices with a captured run-config (missing data is never treated as bad).
    sec_weights: Dict[str, int] = _dcfield(default_factory=lambda: {
        "high": 8, "medium": 3, "low": 1})
    # Per-category cap (max total deduction a single category can contribute). SEC (18) keeps config
    # posture meaningful without eclipsing the cross-layer SPOFs (45) that are the real blockers.
    caps: Dict[str, int] = _dcfield(default_factory=lambda: {
        "L1": 30, "L3": 30, "XL": 45, "PROTO": 25, "SEC": 18})
    # Score -> (band label, fill); first row whose threshold the score meets wins.
    bands: List[Tuple[int, str, str]] = _dcfield(default_factory=lambda: list(_HEALTH_BANDS))
    # Status a readiness check emits when its risk condition fires ('fail' ->
    # NOT READY for the group, 'warn' -> CAUTION).
    readiness: Dict[str, str] = _dcfield(default_factory=lambda: {
        "redundant_uplinks": "warn", "gateway_redundancy": "fail",
        "no_xl_critical": "fail", "no_errdisabled": "warn",
        "stp_consistency": "warn", "portchannels_healthy": "warn",
        "routing_adjacencies": "fail", "no_orphan_vlans": "warn",
        "clean_uplinks": "warn", "health_floor_critical": "fail",
        "health_floor_poor": "warn"})
    # NEW-V3.23.5; activated 2026-06-06: per-role multiplier on a switch's deductions — a
    # fault on a core/distribution switch has a wider blast radius than on an access closet
    # (research: "weight deductions by asset criticality; core/distribution carry higher
    # weight than access"). Conservative defaults — recalibrate via ScoringConfig. _host_role
    # auto-infers 'distribution' (hosts an L3 gateway SVI) vs 'access'; 'core' is manual-tag only.
    criticality_factors: Dict[str, float] = _dcfield(default_factory=lambda: {
        "core": 1.5, "distribution": 1.2, "access": 1.0})
    # NEW-V3.23.7: a switch whose collection covers less than this fraction of the
    # essential command set is reported 'Insufficient Data' instead of a
    # misleadingly-high band, so a partial collection can't look healthy (audit C3).
    data_quality_threshold: float = 0.5


# Module-default scoring configuration. Replace/extend by passing a custom
# ScoringConfig to the compute_* functions; the defaults keep behaviour identical.
SCORING = ScoringConfig()


def _health_band(score: int, bands=None):
    for thr, label, fill in (bands if bands is not None else SCORING.bands):
        if score >= thr:
            return label, fill
    return "Critical", "FF5775"


def _host_role(ifaces: Dict[str, InterfaceData]) -> str:
    """Infer a switch's migration-criticality role from already-parsed data: a
    switch that hosts an L3 gateway SVI carries wider blast radius -> 'distribution';
    otherwise 'access'. ('core' is reserved for manual tuning via
    ScoringConfig.criticality_factors.) Only affects scores when factors != 1.0."""
    for port, d in (ifaces or {}).items():
        if re.match(r"^Vlan\d+$", port, re.IGNORECASE) and (getattr(d, "svi_ip", "") or "").strip():
            return "distribution"
    return "access"


# =============================================================================
# NEW-V14.9: Move-group planning. Switches that share an L2 broadcast domain must
# migrate together; connected components over "shared-VLAN" edges = migration waves.
# Captures transitive coupling (A-VLAN10-B, B-VLAN20-C => A,B,C are one group) that
# is easy to miss by eye. Coupling uses ACTUAL VLAN presence (access port or SVI),
# consistent with the VLAN Census; trunk-allowed-only transit is NOT modeled, and
# VLAN 1 (default, present everywhere) is excluded from grouping by design.
# =============================================================================
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

    NOTE on `endpoints`: it is the SUM over the group's switches of each switch's learned MACs -- an
    endpoint seen on N of the group's switches counts N times, so a large coupled group can EXCEED the
    DISTINCT fleet endpoint total (executive_brief.scale.n_endpoints / the Endpoint Census). It is a
    blast-radius proxy, not a distinct count; surfaces label it "Endpoint MACs (per-switch sum)".
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
            # per-switch SUM of learned MACs (an endpoint on N switches counts N times) -- a blast-radius
            # proxy, NOT distinct fleet endpoints; surfaces label it "Endpoint MACs (per-switch sum)".
            "endpoints": sum(len(group_endpoints[h]) for h in members),
            "gateways": gw,
            "blocked_paths": blk,
            "vlan1_spans": vlan1_spans,
        })
    # Biggest blast radius first.
    groups.sort(key=lambda g: (-len(g["switches"]), -len(g["spanning_vlans"]),
                               g["switches"][0] if g["switches"] else ""))
    return groups


# =============================================================================
# NEW-V14.10: de-duplicated CDP/LLDP inter-switch link map. compute_topology_links()
# is the single source of truth used by the 'Topology Links' sheet, the Findings
# sheet, and the topology diagram. _canon_host / _is_infra_neighbor are analyze-
# internal (no excel writer calls them directly).
# =============================================================================
def _is_infra_neighbor(d: InterfaceData, scanned_hosts: set) -> bool:
    """A link endpoint is infrastructure (switch/router) if its endpoint_type says so
    or the neighbor name matches a scanned device. Excludes host endpoints (phones, APs...)."""
    if (d.endpoint_type or "") in ("Switch", "Router"):
        return True
    nb = _canon_host(d.cdp_neighbor)
    return bool(nb and nb in scanned_hosts)

def _canon_host(name: str) -> str:
    """Normalize a neighbor device-id for matching: strip FQDN domain + serial suffix '(FOC...)'.
    str()-coerce first: a rehydrated snapshot can carry a wrong-typed cdp_neighbor (a list / int),
    and .strip() on a non-str would raise -- breaking the cable map's 'never raises' contract."""
    n = str(name or "").strip()
    n = re.sub(r"\(.*?\)\s*$", "", n).strip()   # drop trailing '(serial)'
    n = n.split(".")[0]                          # drop FQDN domain
    return n.lower()

def compute_topology_links(all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> List[Dict[str, object]]:
    """De-duplicated inter-switch links from CDP/LLDP, one record per physical link.
    Each record: a_host, a_port, b_host, b_port, platform, speed, confirmation."""
    scanned_map = {_canon_host(h): h for h in all_interfaces}   # canon -> real scanned hostname
    scanned = set(scanned_map)
    links: Dict[Tuple[str, str], Dict[str, object]] = {}
    for host, ifaces in all_interfaces.items():
        for port, d in ifaces.items():
            if not d.cdp_neighbor or not _is_infra_neighbor(d, scanned):
                continue
            nbr = str(d.cdp_neighbor or "").strip()   # tolerate a wrong-typed cdp_neighbor (list/int) -> never raises
            # Display name: resolve a scanned neighbor advertised by its FQDN/serial-suffixed
            # CDP id (e.g. 'CORE.broadcast.example.net') back to its real scanned hostname, so the
            # diagram / 'Topology Links' sheet don't render it as a second, duplicate node. A
            # genuinely off-scan neighbor (no canon match) keeps its raw advertised name.
            b_host = scanned_map.get(_canon_host(nbr), nbr)
            key = tuple(sorted([f"{_canon_host(host)}|{str(port or '').lower()}",
                                f"{_canon_host(nbr)}|{str(d.neighbor_port or '?').lower()}"]))
            rec = links.get(key)
            if rec is None:
                links[key] = {"a_host": host, "a_port": port, "b_host": b_host,
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
# EDA-style physical CABLE MAP (SSOT for the explorer + webapp cable-map views).
# A Nokia-EDA cable map is a node/port/cable graph laid out in role tiers, with
# op-status colour DERIVED from the underlying interface states (EDA exposes no
# ready-made per-cable operationalState -- deep-research 2026-07-01). We compute it
# ONCE here so both front-ends render the identical model and cannot drift.
#   nodes  = devices (scanned + off-scan CDP peers), tier-assigned, op-status rolled up
#   cables = physical links from CDP/LLDP; is_pc members bundled into one cable
#   op_status: 'up' | 'down' | 'unknown'  -- 'unknown' is the coverage-honest
#     [NOT OBSERVED] state for uncollected devices/ports (never a fake green).
# -----------------------------------------------------------------------------
_UP_TIER_ROLES = ("core", "backbone", "superspine", "spine")   # seed the top lane


def _port_op_state(d: "InterfaceData") -> str:
    """Classify one interface's operational state from `show interface status`.
    Down tokens are tested first because 'notconnect' contains the substring 'connect'."""
    s = str(getattr(d, "status", "") or "").strip().lower()   # tolerate a wrong-typed status (int/list) -> 'unknown'
    if not s:
        return "unknown"
    if ("notconnect" in s or "disab" in s or "err" in s or "absent" in s
            or "inactive" in s or s == "down"):
        return "down"
    if "connect" in s or s == "up":
        return "up"
    return "unknown"


def _cable_op_state(a_state: str, b_state: str) -> str:
    """Roll two endpoint states into a cable colour: down wins; else any observed up
    -> up; else unknown (the coverage-honest [NOT OBSERVED] neutral)."""
    if a_state == "down" or b_state == "down":
        return "down"
    if a_state == "up" or b_state == "up":
        return "up"
    return "unknown"


# Node-kind classification for the cable map's fabric-only declutter. The load-bearing evidence
# is the advertised PLATFORM string, not endpoint_type: infer_endpoint_type classifies ANY
# 'cisco …' platform as 'Switch' (that is precisely how cisco APs / IP phones pass
# _is_infra_neighbor and enter the map), so only the platform can tell them apart. Rules:
#   * platform evidence OUTRANKS endpoint_type evidence (specific beats derived);
#   * across observers, the STRONGEST claim wins infra-first (an AP-looking platform from one
#     observer never demotes a node another observer identifies as a switch — hiding is the
#     risky direction);
#   * the front-ends may hide only POSITIVELY-identified edge gear (ap/phone/endpoint);
#     'unknown' always stays visible.
_KIND_RANK = ("switch", "router", "firewall", "ap", "phone", "endpoint", "unknown")
_EPTYPE_TO_KIND = {"switch": "switch", "router": "router", "firewall": "firewall",
                   "access point": "ap", "ip phone": "phone",
                   "server": "endpoint", "camera": "endpoint", "printer": "endpoint",
                   "ups/pdu": "endpoint", "storage": "endpoint"}
_PLATFORM_KIND_TOKENS = (   # checked in order; specific device families before generic infra
    ("phone", ("phone",)),
    ("ap", ("air-", "aironet", "access point", " wap")),
    ("firewall", ("asa", "firepower", "ftd", "fortigate", "palo")),
    ("endpoint", ("camera", "cctv", "printer")),
    ("router", ("asr", "isr", "csr", "ncs")),
    ("switch", ("nexus", "catalyst", "ws-c", "n9k", "n7k", "n5k", "n3k")),
)


def _kind_from_platform(platform: str) -> str:
    s = str(platform or "").lower()
    if not s:
        return ""
    for kind, tokens in _PLATFORM_KIND_TOKENS:
        if any(t in s for t in tokens):
            return kind
    return ""


def _node_kind(ep_types: Optional[list], platforms: Optional[list] = None) -> str:
    plat_kinds = {k for k in (_kind_from_platform(p) for p in (platforms or [])) if k}
    if plat_kinds:
        for k in _KIND_RANK:
            if k in plat_kinds:
                return k
    ep_kinds = {_EPTYPE_TO_KIND.get(str(t or "").strip().lower(), "unknown") for t in (ep_types or [])}
    for k in _KIND_RANK:
        if k in ep_kinds:
            return k
    return "unknown"


def compute_cable_map(all_interfaces: Dict[str, Dict[str, InterfaceData]],
                      health_scores: Optional[list] = None) -> dict:
    """Build the EDA-style physical cable map (node/port/cable, role-tiered lanes).

    Tolerant (never raises on odd input -> empty model) and deterministic (the golden
    freezes it). op-status is coverage-honest: an uncollected device, or a port with no
    observed status, is 'unknown' (rendered neutral), never silently 'up'.
    """
    empty = {"nodes": [], "cables": [], "tiers": [],
             "summary": {"n_nodes": 0, "n_cables": 0, "n_tiers": 0,
                         "op": {"up": 0, "down": 0, "unknown": 0}}}
    if not isinstance(all_interfaces, dict) or not all_interfaces:
        return empty

    roles: Dict[str, str] = {}
    for r in (health_scores or []):
        if isinstance(r, dict) and isinstance(r.get("switch"), str):
            roles[r["switch"]] = str(r.get("role") or "").strip().lower()

    # canonical -> real scanned hostname, so a CDP id that resolves to a scanned box keys
    # back to that box (mirrors build_network_model / compute_topology_links).
    scanned_map = {_canon_host(h): h for h in all_interfaces}

    # 1) raw physical links (deduped one-per-cable) from the shared CDP/LLDP builder.
    #    ep_ev collects the endpoint_type EVIDENCE each observing side reports about its peer,
    #    so an off-scan node classifies from what the fleet actually said it was.
    raw: List[dict] = []
    ep_ev: Dict[str, List[str]] = {}
    plat_ev: Dict[str, List[str]] = {}
    for L in compute_topology_links(all_interfaces):
        a_host = scanned_map.get(_canon_host(str(L["a_host"])), str(L["a_host"]))
        b_host = scanned_map.get(_canon_host(str(L["b_host"])), str(L["b_host"]))
        if not a_host or not b_host or a_host == b_host:
            continue
        a_port = str(L["a_port"])
        b_port = str(L.get("b_port") or "")
        da = all_interfaces.get(a_host, {}).get(a_port)
        db = all_interfaces.get(b_host, {}).get(b_port)
        is_pc = bool((da and str(da.port_channel or "").strip())
                     or (db and str(db.port_channel or "").strip()))
        if da is not None:
            ep_ev.setdefault(b_host, []).append(da.endpoint_type or "")
            plat_ev.setdefault(b_host, []).append(da.neighbor_platform or "")
        if db is not None:
            ep_ev.setdefault(a_host, []).append(db.endpoint_type or "")
            plat_ev.setdefault(a_host, []).append(db.neighbor_platform or "")
        raw.append({"a": a_host, "a_port": a_port, "b": b_host, "b_port": b_port, "is_pc": is_pc,
                    "state": _cable_op_state(_port_op_state(da), _port_op_state(db)),
                    "speed": str(L.get("speed") or ""),
                    "confirmation": str(L.get("confirmation") or "")})

    # 2) collapse LAG members (same host-pair, is_pc) into one bundled cable.
    cables: List[dict] = []
    bundles: Dict[frozenset, dict] = {}
    for L in raw:
        pair = frozenset((L["a"], L["b"]))
        if L["is_pc"] and pair in bundles:
            bun = bundles[pair]
            bun["members"].append({"a_port": L["a_port"], "b_port": L["b_port"]})
            bun["_states"].append(L["state"])
            if not bun["speed"] and L["speed"]:
                bun["speed"] = L["speed"]           # backfill like compute_topology_links does
            continue
        cab = {"a": L["a"], "a_port": L["a_port"], "b": L["b"], "b_port": L["b_port"],
               "is_pc": L["is_pc"], "members": [{"a_port": L["a_port"], "b_port": L["b_port"]}],
               "speed": L["speed"],
               "confirmation": L["confirmation"], "_states": [L["state"]]}
        cables.append(cab)
        if L["is_pc"]:
            bundles[pair] = cab
    for cab in cables:
        st = cab.pop("_states")
        cab["op_status"] = "down" if "down" in st else ("up" if "up" in st else "unknown")

    # 3) nodes = every host that is a scanned device OR a cable endpoint; ports = only the
    #    ports that terminate an observed cable (declutter -- deep-research open-Q #2).
    hosts = set(all_interfaces)
    for cab in cables:
        hosts.add(cab["a"])
        hosts.add(cab["b"])
    adj: Dict[str, set] = {h: set() for h in hosts}
    ports: Dict[str, dict] = {h: {} for h in hosts}
    down_incident: Dict[str, bool] = {h: False for h in hosts}
    for cab in cables:
        a, b = cab["a"], cab["b"]
        adj[a].add(b)
        adj[b].add(a)
        if cab["op_status"] == "down":
            down_incident[a] = True
            down_incident[b] = True
        ports[a][cab["a_port"]] = {"name": cab["a_port"], "peer": b, "peer_port": cab["b_port"],
                                   "op_status": cab["op_status"], "is_pc": cab["is_pc"]}
        ports[b][cab["b_port"]] = {"name": cab["b_port"], "peer": a, "peer_port": cab["a_port"],
                                   "op_status": cab["op_status"], "is_pc": cab["is_pc"]}

    # 4) tiers = BFS distance from the top-role seed (core/spine); degree-fallback seed when no
    #    role evidence (clab-io-draw: highest-degree = top). Mirrors the explorer's roleTiers.
    seeds = sorted(h for h in hosts if roles.get(h) in _UP_TIER_ROLES)
    if not seeds and hosts:
        seeds = [sorted(hosts, key=lambda h: (-len(adj[h]), h))[0]]
    tier: Dict[str, int] = {h: 0 for h in seeds}
    frontier = list(seeds)
    while frontier:
        nxt: List[str] = []
        for cur in frontier:
            for o in adj[cur]:
                if o not in tier:
                    tier[o] = tier[cur] + 1
                    nxt.append(o)
        frontier = nxt
    max_t = max(tier.values(), default=0)
    for h in hosts:                                    # isolated / unreached -> bottom lane
        tier.setdefault(h, max_t + 1)
    max_t = max(tier.values(), default=0)

    # within-tier order: barycenter vs the tier above (a few sweeps) to cut crossings.
    tiers = [sorted(h for h in hosts if tier[h] == k) for k in range(max_t + 1)]
    for _ in range(4):
        for k in range(1, len(tiers)):
            above = {h: i for i, h in enumerate(tiers[k - 1])}
            scored = []
            for h in tiers[k]:
                ns = [above[o] for o in adj[h] if o in above]
                scored.append((sum(ns) / len(ns) if ns else 1e9, h))
            tiers[k] = [h for _bc, h in sorted(scored)]
    order = {h: i for t in tiers for i, h in enumerate(t)}

    # 5) assemble nodes (stable sort by tier, order, host).
    nodes: List[dict] = []
    for h in sorted(hosts, key=lambda x: (tier[x], order.get(x, 0), x)):
        collected = h in all_interfaces
        badges: List[str] = []
        if not collected:
            badges.append("uncollected")             # the [NOT OBSERVED] marker
        if down_incident[h]:
            badges.append("links-down")
        nodes.append({
            "host": h, "role": roles.get(h, ""), "tier": tier[h], "order": order.get(h, 0),
            "collected": collected, "op_status": "up" if collected else "unknown",
            "kind": "device" if collected else _node_kind(ep_ev.get(h), plat_ev.get(h)),
            "badges": badges[:3],
            "ports": sorted(ports[h].values(), key=lambda p: p["name"].lower()),
        })

    cables.sort(key=lambda c: (c["a"].lower(), str(c["a_port"]).lower(), c["b"].lower()))
    op_roll = {"up": 0, "down": 0, "unknown": 0}
    for c in cables:
        op_roll[c["op_status"]] = op_roll.get(c["op_status"], 0) + 1
    return {"nodes": nodes, "cables": cables, "tiers": tiers,
            "summary": {"n_nodes": len(nodes), "n_cables": len(cables),
                        "n_tiers": len(tiers), "op": op_roll}}


def cable_map_of_snapshot(snap: Optional[dict]) -> dict:
    """Cable map for a STORED snapshot dict: prefer the engine-computed snap['cable_map']; for a
    snapshot that predates the cable-map engine, rehydrate the stored dict-interfaces back into
    InterfaceData (dropping unknown legacy keys) and recompute. Tolerant: anything else -> empty
    model. One rehydration SSOT — the --compare delta and the webapp endpoint both call this."""
    snap = snap if isinstance(snap, dict) else {}
    cm = snap.get("cable_map")
    if isinstance(cm, dict) and isinstance(cm.get("nodes"), list):
        # schema-staleness probe (device_dossiers precedent, webapp app.py): a stored section from a
        # pre-kind/speed engine is RECOMPUTED from the evidence when available, so newer features
        # (fabric filter, link speed) work on old uploads; with no evidence it still beats nothing.
        _n0 = next((n for n in cm["nodes"] if isinstance(n, dict)), None)
        _c0 = next((c for c in (cm.get("cables") or []) if isinstance(c, dict)), None)
        current = (_n0 is None or "kind" in _n0) and (_c0 is None or "speed" in _c0)
        if current or not isinstance(snap.get("interfaces"), dict):
            return cm
    raw = snap.get("interfaces")
    ifaces: Dict[str, Dict[str, InterfaceData]] = {}
    if isinstance(raw, dict):
        for host, ports_ in raw.items():
            if not isinstance(ports_, dict):
                continue
            ifaces[host] = {p: InterfaceData.from_sparse(d)   # restores '' defaults for sparse-encoded records
                            for p, d in ports_.items() if isinstance(d, dict)}
    return compute_cable_map(ifaces, snap.get("health_scores"))


def compute_cable_map_diff(old_cm: Optional[dict], new_cm: Optional[dict]) -> dict:
    """Physical-cabling delta for --compare: cables added / removed / op-status transitions + LAG
    member-count changes, keyed on the UNDIRECTED cable identity (the sorted host|port pair), so a
    link reported from the other side on the second run is the SAME cable, not an add+remove.

    Coverage-honest: a transition to 'unknown' is 'no longer observed' (a coverage event) — NEVER
    counted as a down; and a missing side, or zero cables on both sides, yields assessed=False —
    never a silent 'no cabling changes'."""
    empty_sum = {"n_old": 0, "n_new": 0, "n_added": 0, "n_removed": 0, "n_status_changed": 0,
                 "n_went_down": 0, "n_restored": 0, "n_no_longer_observed": 0,
                 "n_members_changed": 0, "n_unchanged": 0}
    out: dict = {"assessed": False, "added": [], "removed": [], "status_changes": [],
                 "members_changed": [], "summary": dict(empty_sum)}
    if not isinstance(old_cm, dict) or not isinstance(new_cm, dict):
        return out

    def _key(c: dict) -> tuple:
        return tuple(sorted([f"{str(c.get('a', '')).lower()}|{str(c.get('a_port', '')).lower()}",
                             f"{str(c.get('b', '')).lower()}|{str(c.get('b_port', '')).lower()}"]))

    def _index(cm: dict) -> Dict[tuple, dict]:
        return {_key(c): c for c in (cm.get("cables") or []) if isinstance(c, dict)}

    o, n = _index(old_cm), _index(new_cm)
    if not o and not n:
        return out
    out["assessed"] = True
    s = out["summary"]
    s["n_old"], s["n_new"] = len(o), len(n)
    out["added"] = [n[k] for k in sorted(set(n) - set(o))]
    out["removed"] = [o[k] for k in sorted(set(o) - set(n))]
    for k in sorted(set(o) & set(n)):
        oc, nc = o[k], n[k]
        fo, to = str(oc.get("op_status") or "unknown"), str(nc.get("op_status") or "unknown")
        changed = fo != to
        if changed:
            if to == "down":
                cls = "went down"
            elif to == "unknown":
                cls = "no longer observed"       # coverage event, not a down
            elif fo == "down":
                cls = "restored"
            else:
                cls = "newly observed up"        # unknown -> up: visibility gained, not a repair
            out["status_changes"].append({"a": nc.get("a", ""), "a_port": nc.get("a_port", ""),
                                          "b": nc.get("b", ""), "b_port": nc.get("b_port", ""),
                                          "is_pc": bool(nc.get("is_pc")),
                                          "from": fo, "to": to, "classification": cls})
            s["n_went_down"] += 1 if to == "down" else 0
            s["n_restored"] += 1 if cls == "restored" else 0
            s["n_no_longer_observed"] += 1 if cls == "no longer observed" else 0
        om, nm = len(oc.get("members") or []), len(nc.get("members") or [])
        if (oc.get("is_pc") or nc.get("is_pc")) and om != nm:
            out["members_changed"].append({"a": nc.get("a", ""), "a_port": nc.get("a_port", ""),
                                           "b": nc.get("b", ""), "b_port": nc.get("b_port", ""),
                                           "old_members": om, "new_members": nm})
        elif not changed:
            s["n_unchanged"] += 1
    s["n_added"], s["n_removed"] = len(out["added"]), len(out["removed"])
    s["n_status_changed"] = len(out["status_changes"])
    s["n_members_changed"] = len(out["members_changed"])
    return out


# -----------------------------------------------------------------------------
# Tier 1 #1: Findings / Risk Register  (pure cross-reference of InterfaceData)
# -----------------------------------------------------------------------------
_SEV_RANK = {"High": 0, "Medium": 1, "Low": 2, "Info": 3}

def _canon_host_map(all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> Dict[str, str]:
    """canonical-name -> real hostname key, to resolve CDP/LLDP neighbor names."""
    return {_canon_host(h): h for h in all_interfaces}


def compute_hostname_mismatches(all_device_physical: List[Any]) -> List[dict]:
    """NEW-V3.23.68: flag devices whose OWN configured hostname (DevicePhysical.reported_hostname,
    parsed from 'show version') differs from the inventory name it was collected under
    (DevicePhysical.hostname). That mismatch is what makes a device surface as a phantom, split
    node in the topology - its neighbors advertise it over CDP under its real name, which no
    longer canon-matches the typo'd inventory key (e.g. inventory 'AS08--BC-...' vs real
    'AS08-BC-...'). Returns [{inventory, reported}] (empty reported = unknown -> skipped)."""
    out: List[dict] = []
    for dp in (all_device_physical or []):
        inv = (getattr(dp, "hostname", "") or "").strip()
        rep = (getattr(dp, "reported_hostname", "") or "").strip()
        if inv and rep and _canon_host(inv) != _canon_host(rep):
            out.append({"inventory": inv, "reported": rep})
    return out


def reconcile_cdp_neighbor_names(all_interfaces: Dict[str, Dict[str, InterfaceData]],
                                 all_device_physical: List[Any]) -> int:
    """In-place fix for the phantom SPLIT-NODE class (audit-5 cross-artifact #1): a device collected under an
    inventory name that is a suffix-SHORTER / typo'd form of its OWN configured hostname (DevicePhysical.
    reported_hostname, from show version) is advertised by its NEIGHBORS over CDP/LLDP under that configured name,
    which canon-MISSES the inventory key -- so compute_topology_links renders it as a second, duplicate node and
    build_network_model DROPS the unresolved link (under-counting blast radius). This rewrites those neighbor
    advertisements back to the inventory key, using each device's OWN configured hostname as the reconciliation
    key, so the device renders as ONE node and its bidirectional link de-dups to one record.

    OVER-MERGE-SAFE by construction -- a configured name is mapped to an inventory key ONLY when (a) exactly ONE
    collected device reports it and (b) it is not itself an inventory key. So two genuinely distinct site devices,
    or FEX modules that report their parent switch's hostname, can NEVER be merged (a wrong merge would silently
    corrupt every downstream topology / dependency / failure-impact deliverable). Returns the count rewritten."""
    inv_canon = {_canon_host(h) for h in all_interfaces}
    claims: Dict[str, set] = {}
    for dp in (all_device_physical or []):
        inv = (getattr(dp, "hostname", "") or "").strip()
        rep = (getattr(dp, "reported_hostname", "") or "").strip()
        if inv and rep and inv in all_interfaces and _canon_host(inv) != _canon_host(rep):
            claims.setdefault(_canon_host(rep), set()).add(inv)
    resolve = {rc: next(iter(invs)) for rc, invs in claims.items()
               if len(invs) == 1 and rc not in inv_canon}     # unambiguous + not already an inventory key
    if not resolve:
        return 0
    rewritten = 0
    for ifaces in all_interfaces.values():
        for d in ifaces.values():
            nb = (getattr(d, "cdp_neighbor", "") or "").strip()
            tgt = resolve.get(_canon_host(nb)) if nb else None
            if tgt and tgt != nb:
                d.cdp_neighbor = tgt
                rewritten += 1
    return rewritten

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

    # (3) err-disabled ports - DEDUPLICATED per switch (one weighted row with a
    #     count + the port list, not one row per port, to avoid a 'sea of red').
    for host, ifaces in all_interfaces.items():
        bad = sorted([port for port, d in ifaces.items()
                      if "err" in (d.status or "").lower() and "disab" in (d.status or "").lower()])
        if bad:
            findings.append(("High", "Err-disabled", f"{host} ({len(bad)})",
                f"{len(bad)} err-disabled port(s): {', '.join(bad)}."))

    # (4) STP inconsistent ports - DEDUPLICATED per switch.
    for host, ifaces in all_interfaces.items():
        bad = sorted([port for port, d in ifaces.items()
                      if (d.stp_blocked or "") == "Inconsistent"])
        if bad:
            findings.append(("High", "STP inconsistent", f"{host} ({len(bad)})",
                f"{len(bad)} STP-inconsistent port(s): {', '.join(bad)} "
                f"(root-guard / loop-guard / type mismatch)."))

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


# =============================================================================
# Tier 1: network model + causality chains + failure-impact simulation. Pure
# reachability analysis over the scanned switch graph (no traffic telemetry).
# build_network_model is the shared graph; the two compute_* derive blast radius.
# The Excel sheet-name + fill constants and the write_* sheets stay in the monolith.
# =============================================================================
# The VLAN-range PARSE is memoized (Tier-2 #12): the same range strings (trunk-allowed / stp-fwd/blk
# lists) are tested against every VLAN on every link in the O(H x V x link) failure-impact / topology
# loops, so re-splitting on each call was the one measured superlinear term. Keyed on the raw string.
_VLAN_ALL = object()   # sentinel spec: matches every VLAN id (an 'all' / '1-4094' list)


@lru_cache(maxsize=8192)
def _parse_vlan_ranges(s: str):
    """Parse a Cisco VLAN-range string into a hashable membership spec: the _VLAN_ALL sentinel, or a
    tuple of (lo, hi) inclusive ranges (a single vid is (v, v)). Membership-only -- never enumerated,
    so '1-4094' stays cheap. Same semantics as the old inline parse (malformed range tokens skipped)."""
    s = (s or "").strip().lower()
    if not s or s in ("none", "--", "n/a"):
        return ()
    if s in ("all", "1-4094"):
        return _VLAN_ALL
    ranges = []
    for tok in re.split(r"[,\s]+", s):
        if not tok:
            continue
        if "-" in tok:
            try:
                lo, hi = (int(x) for x in tok.split("-", 1))
            except ValueError:
                continue
            ranges.append((lo, hi))
        elif tok.isdigit():
            v = int(tok)
            ranges.append((v, v))
    return tuple(ranges)


def _vlan_in_ranges(vid: int, s: str) -> bool:
    """True if integer VLAN id `vid` falls in a Cisco range string like '10,20-23,40'.
    Membership-only (no enumeration), so a '1-4094' trunk-allowed list never explodes."""
    spec = _parse_vlan_ranges(s)
    if spec is _VLAN_ALL:
        return True
    return any(lo <= vid <= hi for lo, hi in spec)


def _is_offscan_uplink_port(d: Optional[InterfaceData]) -> bool:
    """Does this LOCAL port look like an inter-switch uplink facing an UNCOLLECTED device?

    compute_topology_links admits any CDP/LLDP peer whose `endpoint_type` reads Switch/Router, and
    on a real collection that classification is coarse enough to include CDP-speaking IP phones and
    access points. Counting one of those as an uplink is not merely noise: an extra phantom uplink
    makes a genuinely single-homed switch look dual-homed and SUPPRESSES its single-fiber finding —
    the very false-health this off-scan handling exists to remove. So the off-scan side is admitted
    only on positive SWITCHING evidence: a live trunk, or a port-channel member. A routed L3 uplink
    to an off-scan router is deliberately not admitted (no switching evidence to stand on); that is
    an under-claim, which is the safe direction here."""
    if d is None:
        return False
    if str(getattr(d, "port_channel", "") or "").strip():
        return True
    if str(getattr(d, "switchport_mode", "") or "").strip().lower() == "trunk":
        return True
    return is_live_trunk_status(getattr(d, "trunk_status", ""))


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
            if m and (d.svi_ip or "").strip():   # only a Vlan SVI WITH an IP is a real L3 gateway -- a no-IP SVI
                vid = int(m.group(1))             # (esp. the universal default Vlan1) is a phantom gateway that
                raw = (d.hsrp_behavior or "").strip()   # strands access switches into 60 false 'VLAN 1' SPOFs (audit-5 #1)
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
    offscan_links: List[Dict[str, object]] = []
    for link in compute_topology_links(all_interfaces):
        ah = cmap.get(_canon_host(str(link["a_host"])))
        bh = cmap.get(_canon_host(str(link["b_host"])))
        if not ah or not bh or ah == bh:
            # ONE end scanned, the far device merely not collected. Dropping the link outright made
            # an access switch whose ONLY uplink faces an uncollected core look like a switch with no
            # uplink at all, so `_physical_uplink_index` found nothing single-homed and readiness
            # reported "no single-homed switch" over the commonest real topology (#14). Kept on a
            # SEPARATE key: we cannot read the far end's STP/trunk state, so it must never become a
            # forwarding edge in `links` (the VLAN-reachability graph is unchanged by this).
            if ah and not bh:
                near, nport, far = ah, normalize_ifname(str(link["a_port"])), str(link["b_host"])
            elif bh and not ah:
                near, nport, far = bh, normalize_ifname(str(link.get("b_port", ""))), str(link["a_host"])
            else:
                continue                       # self-loop, or neither end resolvable
            dn = all_interfaces.get(near, {}).get(nport)
            if _is_offscan_uplink_port(dn):
                offscan_links.append({"host": near, "port": nport, "far": far,
                                      "is_pc": bool(dn and dn.port_channel), "d": dn})
            continue
        ap = normalize_ifname(str(link["a_port"]))
        bp = normalize_ifname(str(link.get("b_port", "")))
        da = all_interfaces.get(ah, {}).get(ap)
        db = all_interfaces.get(bh, {}).get(bp)
        is_pc = bool((da and da.port_channel) or (db and db.port_channel))
        links.append({"a": ah, "ap": ap, "b": bh, "bp": bp, "is_pc": is_pc, "da": da, "db": db})

    vlans = set(gw) | set(access_presence) | {v for (_, v) in endpoints}
    return {"hosts": hosts, "links": links, "offscan_links": offscan_links, "gw": gw,
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


def _link_has_vlan_evidence(link: Dict[str, object]) -> bool:
    """True when at least one end of `link` carries the L2 VLAN evidence `_link_carries` reads
    (per-VLAN STP state, or a trunk allowed/native list). With NONE of it on EITHER end,
    `_link_carries` returns '' out of IGNORANCE -- byte-identical to the '' it returns for a
    positively not-carried VLAN. That conflation made a sole L2 transit switch whose trunk/STP
    output was never collected contribute no forwarding edge, so removing it stranded nobody and
    compute_failure_impact reported "No reachability impact ... (within the scan)" at severity
    Info: a clean bill written from the absence of evidence (#13)."""
    for d in (link.get("da"), link.get("db")):
        if d is None:
            continue
        if (str(getattr(d, "stp_fwd_vlans", "") or "").strip()
                or str(getattr(d, "stp_blk_vlans", "") or "").strip()
                or str(getattr(d, "trunk_allowed_vlans", "") or "").strip()
                or str(getattr(d, "trunk_native_vlan", "") or "").strip()):
            return True
    return False


def _carry(model: Dict[str, object], link: Dict[str, object], vid: int) -> str:
    """`_link_carries` memoized on the model for the compute's lifetime (Plan-A #12). The (link, vid)
    classification is a PURE function -- independent of removed_host -- yet the failure-impact /
    causality loops re-ask the same (link, vid) once per removed-host iteration (O(H) times for one
    answer). Caching it on the model (built fresh per compute, so no id reuse across computes)
    removes that H factor WITHOUT changing any result -- caching a pure function cannot. Keyed on
    (vid, id(link)); link objects are stable within one model, and '' (not-carried) is a real cached
    value distinct from the None 'absent' sentinel."""
    cache = model.setdefault("_carry_cache", {})
    key = (vid, id(link))
    rel = cache.get(key)
    if rel is None:
        rel = cache[key] = _link_carries(link, vid)
    return rel


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
        rel = _carry(model, link, vid)
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


def _vlan_list_summary(vids, cap: int = 12) -> str:
    """NEW-V3.23.90: compact, bounded VLAN-id list for an AGGREGATED finding, e.g.
    '10, 20, 30 (+5 more)'. Keeps an aggregated row's detail readable no matter how
    many VLANs a single device articulates (some carry 100+), instead of dumping the
    whole list. Sorted + de-duped so the text is deterministic for the golden."""
    vids = sorted(set(vids))
    if not vids:
        return ""
    shown = ", ".join(str(v) for v in vids[:cap])
    return shown if len(vids) <= cap else f"{shown} (+{len(vids) - cap} more)"


def compute_causality_chains(all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> List[tuple]:
    """Root-cause -> mechanism -> impact -> mitigation chains, derived from the network model.
    Returns (severity, trigger, mechanism, impact, mitigation, hosts) tuples, where `hosts` is a
    tuple of the switch hostname(s) the chain is ABOUT (NEW-V3.23.92: the explorer's Causality mode
    consumes this directly to highlight the right nodes -- one source of truth, like cross_layer's
    `hosts` -- instead of reverse-parsing hostnames out of the prose via substring match, which
    over-highlighted any host whose name was a substring of another's). `hosts` is a tuple (not a
    list) so the chain tuples stay hashable for the de-dup below."""
    model = build_network_model(all_interfaces)
    chains: List[tuple] = []

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
                    (gw_hosts[0],),
                ))

    # Chain B: transit articulation - removing a switch partitions a VLAN's endpoints from
    # its gateway. A reachable STP-blocked backup softens High -> Medium (transient only).
    # AGGREGATED per host (NEW-V3.23.90): the old per-(host,vid) emission produced one near-
    # identical "Transit switch X removed" chain PER VLAN -- ~13k rows on the real fleet (99.8%
    # of all chains), which buried the genuine criticals, bloated every deliverable (snapshot /
    # workbook / explorer), and saturated the health score's XL cap fleet-wide (zero band
    # discrimination). Industry practice for assessment findings is to group around the root-cause
    # DEVICE, not repeat the symptom per VLAN, so we roll all of a switch's articulation VLANs into
    # one chain. Severity is the worst across its VLANs: any hard (no-backup) partition -> High,
    # otherwise transient STP-healed -> Medium.
    b_hard: Dict[str, dict] = {}   # host -> {"vlans": set, "stranded": set, "eps": int}
    b_soft: Dict[str, dict] = {}
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
            bucket = b_hard if still else b_soft
            affected = still if still else stranded
            e = bucket.setdefault(host, {"vlans": set(), "stranded": set(), "eps": 0})
            e["vlans"].add(vid); e["stranded"] |= affected
            e["eps"] += _ep_count(vid, affected)
    for host in model["hosts"]:
        hard, soft = b_hard.get(host), b_soft.get(host)
        if hard:
            vl = sorted(hard["vlans"]); sw = sorted(hard["stranded"])
            extra = (f"; a further {len(soft['vlans'])} VLAN(s) hit only a transient STP outage"
                     if soft else "")
            chains.append((
                "High",
                f"Transit switch {host} is removed / migrated",
                f"It is the only forwarding L2 path to the gateway for {len(vl)} VLAN(s) "
                f"({_vlan_list_summary(vl)})",
                f"{len(sw)} switch(es) / {hard['eps']} endpoint(s) lose reachability to their "
                f"VLAN gateway across {len(vl)} VLAN(s), with no backup link{extra}",
                "Add a redundant uplink/path, or migrate this switch in the same wave as its dependents",
                (host,),
            ))
        elif soft:
            vl = sorted(soft["vlans"])
            chains.append((
                "Medium",
                f"Transit switch {host} is removed / migrated",
                f"It carries the active L2 path to the gateway for {len(vl)} VLAN(s) "
                f"({_vlan_list_summary(vl)}); a redundant link exists but is STP-blocked",
                f"{soft['eps']} endpoint(s) across {len(vl)} VLAN(s) hit a transient outage while "
                f"STP reconverges onto the backup link",
                "Expected to self-heal; verify STP reconvergence time before cutover",
                (host,),
            ))

    # Chain C: a switch's only forwarding uplink for an endpoint VLAN is a single
    # (non-port-channel) link -> link loss isolates that VLAN. AGGREGATED per (host, uplink)
    # (NEW-V3.23.90): one row per vulnerable uplink listing every VLAN that rides it, not one
    # row per VLAN (many VLANs share the same single uplink).
    c_grp: Dict[tuple, dict] = {}   # (host, near_port, far) -> {"vlans": set, "eps": int}
    for host in model["hosts"]:
        host_links = [l for l in model["links"] if host in (l["a"], l["b"])]
        host_vlans = {v for (h, v), n in model["endpoints"].items() if h == host and n > 0}
        host_vlans |= {v for v, hs in model["access_presence"].items() if host in hs}
        for vid in sorted(host_vlans):
            if host in [g["host"] for g in model["gw"].get(vid, [])]:
                continue  # gateway is local; uplink loss doesn't strand it from L3
            carrying = [l for l in host_links if _carry(model, l, vid) == "fwd"]
            backups  = [l for l in host_links if _carry(model, l, vid) == "blk"]
            if len(carrying) == 1 and not backups and not carrying[0]["is_pc"]:
                l = carrying[0]
                far = l["b"] if l["a"] == host else l["a"]
                near_port = l["ap"] if l["a"] == host else l["bp"]
                e = c_grp.setdefault((host, near_port, far), {"vlans": set(), "eps": 0})
                e["vlans"].add(vid); e["eps"] += model["endpoints"].get((host, vid), 0)
    for (host, near_port, far), e in sorted(c_grp.items()):
        vl = sorted(e["vlans"])
        chains.append((
            "Medium",
            f"Uplink {host} {near_port} -> {far} fails",
            f"It is {host}'s only forwarding inter-switch link carrying {len(vl)} VLAN(s) "
            f"({_vlan_list_summary(vl)}), and it is a single (non-port-channel) link",
            f"{len(vl)} VLAN(s) on {host} are isolated from the fabric"
            + (f" ({e['eps']} endpoint(s))" if e["eps"] else ""),
            "Add a second uplink or bundle the link as a port-channel",
            (host,),
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

    # Per-host count of inter-switch links whose VLAN carriage could not be determined AT ALL (no
    # trunk/STP evidence on either end). Those links are absent from every forwarding graph below
    # out of ignorance, not because they positively carry nothing -- so a switch that only touches
    # such links must not be reported as having no blast radius (#13).
    blind_links: Dict[str, int] = {}
    for _l in model["links"]:
        if not _link_has_vlan_evidence(_l):
            blind_links[_l["a"]] = blind_links.get(_l["a"], 0) + 1
            blind_links[_l["b"]] = blind_links.get(_l["b"], 0) + 1

    def _ep_count(vid: int, hosts: set) -> int:
        return sum(n for (h, v), n in model["endpoints"].items() if v == vid and h in hosts)

    for host in model["hosts"]:
        per_vlan: List[Tuple[int, str, int]] = []   # (vid, status, stranded)
        worst = 99; total_stranded = 0; hard = backup = fhrp = 0
        off_scan_gw_vlans = 0    # VLANs this host carries/transits whose GATEWAY is off-scan -> impact INDETERMINATE

        for vid in sorted(model["vlans"]):
            gw_hosts = [g["host"] for g in model["gw"].get(vid, [])]
            if not gw_hosts:
                # no in-scan gateway. If this host nonetheless carries OR transits endpoints in the VLAN, removing
                # it could strand them -- we just can't simulate it (the gateway device was not collected). Record
                # it as a coverage gap so the roll-up never reports "no impact" by silence: a transit SPOF whose
                # gateway is off-scan is INDETERMINATE, not benign (audit-3 #7 transit-SPOF false-health).
                _eph = {h for (h, v), n in model["endpoints"].items() if v == vid and n > 0}
                _eph |= model["access_presence"].get(vid, set())
                if _eph and ((host in _eph) or any(
                        host in (l["a"], l["b"]) and _carry(model, l, vid) for l in model["links"])):
                    off_scan_gw_vlans += 1
                continue  # no in-scan gateway -> "stranded from gateway" is N/A (see Findings)
            ep_hosts = {h for (h, v), n in model["endpoints"].items() if v == vid and n > 0}
            ep_hosts |= model["access_presence"].get(vid, set())
            if not ep_hosts:
                continue
            surviving_gw = [h for h in gw_hosts if h != host]
            any_fhrp = any(g["fhrp"] for g in model["gw"].get(vid, []))
            touches = (host in gw_hosts) or (host in ep_hosts) or any(
                host in (l["a"], l["b"]) and _carry(model, l, vid) for l in model["links"])
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
            if off_scan_gw_vlans:
                detail = (f"Blast radius INDETERMINATE — {off_scan_gw_vlans} VLAN(s) on this switch have an "
                          "off-scan gateway (gateway device not collected); removal impact not assessable — "
                          "this is a coverage gap, not a clean bill.")
            elif blind_links.get(host):
                detail = (f"Blast radius INDETERMINATE — {blind_links[host]} inter-switch link(s) on this "
                          "switch carry NO trunk/STP evidence, so whether it transits any VLAN could not "
                          "be determined; removal impact not assessable — this is a coverage gap, not a "
                          "clean bill.")
            else:
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
                        "fhrp": fhrp, "off_scan_gw_vlans": off_scan_gw_vlans, "detail": detail})

    sev_rank = {"High": 0, "Medium": 1, "Low": 2, "Info": 3}
    results.sort(key=lambda r: (sev_rank.get(r["severity"], 9), -r["stranded"],
                                -r["vlans_impacted"], r["host"].lower()))
    return results


# =============================================================================
# Scoring + migration-readiness synthesis. compute_data_quality reads collected
# output (via cmdio._load_cmd_output); the rest synthesise already-computed
# records. The Excel sheet-name + fill constants and the write_* sheets stay in
# the monolith.
# =============================================================================
_ESSENTIAL_CMD_VARIANTS = (
    ("show interface status",),
    ("show interface switchport", "show interfaces switchport"),
    ("show version",),
    ("show cdp neighbors detail", "show lldp neighbors detail"),
)
# operator-facing label per essential group (NEW-V3.23.109, collection-completeness report)
_ESSENTIAL_LABELS = ("interface status", "switchport", "version/inventory", "CDP/LLDP neighbors")

def _topology_adjacency(all_interfaces: Dict[str, Dict[str, InterfaceData]]):
    """Undirected adjacency {host: set(neighbor_host)} over SCANNED switches only, plus a
    {frozenset({a,b}): link-record} map — both from compute_topology_links (one source of truth
    with the topology diagram / 'Topology Links' sheet). Off-scan neighbours and self-loops dropped."""
    hosts = set(all_interfaces)
    adj: Dict[str, set] = {h: set() for h in hosts}
    edges: Dict[frozenset, dict] = {}
    for L in compute_topology_links(all_interfaces):
        a, b = str(L["a_host"]), str(L["b_host"])
        if a not in hosts or b not in hosts or a == b:
            continue
        adj[a].add(b); adj[b].add(a)
        k = frozenset((a, b))
        if k not in edges:
            edges[k] = {"a_host": a, "a_port": str(L["a_port"]),
                        "b_host": b, "b_port": str(L.get("b_port") or "")}
    return hosts, adj, edges


def _find_bridges(adj: Dict[str, set]) -> set:
    """Bridge edges (frozenset({a,b})) — links whose removal disconnects the graph (true SPOFs).
    Classic DFS low-link, ITERATIVE (explicit stack) so a long simple path — e.g. a 1000+-switch daisy chain —
    cannot blow the interpreter's recursion limit and crash the whole analysis (it used to RecursionError; the
    public entry compute_link_centrality took the same chain down)."""
    disc: Dict[str, int] = {}
    low: Dict[str, int] = {}
    bridges: set = set()
    timer = [0]

    def dfs_iter(root: str) -> None:
        # each frame is (node, parent, child-iterator). The iterator resumes exactly where it paused, so a node
        # is finalized (popped) only after ALL its children are fully explored — identical order to the recursion.
        disc[root] = low[root] = timer[0]; timer[0] += 1
        stack = [(root, None, iter(sorted(adj[root])))]
        while stack:
            u, parent, it = stack[-1]
            pushed = False
            for v in it:
                if v == parent:
                    continue
                if v not in disc:                                   # tree edge -> descend
                    disc[v] = low[v] = timer[0]; timer[0] += 1
                    stack.append((v, u, iter(sorted(adj[v]))))
                    pushed = True
                    break
                low[u] = min(low[u], disc[v])                       # back edge
            if not pushed:                                          # u exhausted -> finalize, propagate to parent
                stack.pop()
                if stack:
                    pu = stack[-1][0]
                    low[pu] = min(low[pu], low[u])
                    if low[u] > disc[pu]:
                        bridges.add(frozenset((pu, u)))

    for r in sorted(adj):
        if r not in disc:
            dfs_iter(r)
    return bridges


def _bridge_pairs_cut(adj: Dict[str, set], edge: frozenset) -> int:
    """For a bridge, the number of switch-pairs that lose ALL connectivity if it fails = the product
    of the sizes of the TWO components the edge actually separates.

    NEW-V3.23.91: BFS BOTH sides (a's component and b's component, each with the bridge removed) and
    multiply. The previous `size_a * (n - size_a)` was BOTH:
      * non-deterministic — `tuple(frozenset)` picks the BFS start side by hash order (PYTHONHASHSEED),
        so on an unequal split a's-side vs b's-side gave different products run-to-run (observed
        pairs_cut flipping 302 <-> 22082 for the same bridge); and
      * wrong on a fabric with OTHER disconnected components — `n - size_a` swept in switches that were
        never reachable through this bridge at all, over-stating the severed-pair count.
    component(a) * component(b) is symmetric (deterministic) and counts only pairs that genuinely lose
    their sole path. On a fully-connected fabric (component_b == n - size_a) it equals the old value."""
    from collections import deque
    a, b = tuple(edge)

    def _component_size(start: str) -> int:
        seen = {start}
        q = deque([start])
        while q:
            u = q.popleft()
            for w in adj[u]:
                if (u == a and w == b) or (u == b and w == a):
                    continue                   # don't cross the bridge under test
                if w not in seen:
                    seen.add(w); q.append(w)
        return len(seen)

    return _component_size(a) * _component_size(b)


def compute_link_centrality(all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> List[Dict[str, object]]:
    """Structural CHOKEPOINT analysis of the inter-switch topology — edge betweenness centrality
    (how much of the all-pairs shortest-path flow crosses each link) plus bridge detection (links
    whose removal disconnects the fabric). This ranks the LINKS, and is deliberately distinct from
    compute_failure_impact / the keystone ranking (which is per-SWITCH node removal): a link with
    two redundant equal-cost paths is correctly NOT a chokepoint here even if both its switches are
    busy. Built from compute_topology_links over the scanned switches. One record per link:
    {a_host,a_port,b_host,b_port, betweenness (float), is_bridge (bool), pairs_cut (int; switch-pairs
    severed if a bridge fails, else 0), rank (1 = highest betweenness)}, sorted by betweenness desc."""
    from collections import deque
    hosts, adj, edges = _topology_adjacency(all_interfaces)
    if not edges:
        return []
    nodes = sorted(hosts)
    bet: Dict[frozenset, float] = {k: 0.0 for k in edges}
    # Brandes edge-betweenness (unweighted BFS per source; dependency accumulated back to predecessors).
    for s in nodes:
        S: List[str] = []
        pred: Dict[str, List[str]] = {v: [] for v in nodes}
        sigma: Dict[str, float] = {v: 0.0 for v in nodes}; sigma[s] = 1.0
        dist: Dict[str, int] = {v: -1 for v in nodes}; dist[s] = 0
        q = deque([s])
        while q:
            v = q.popleft(); S.append(v)
            for w in sorted(adj[v]):
                if dist[w] < 0:
                    dist[w] = dist[v] + 1; q.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]; pred[w].append(v)
        delta: Dict[str, float] = {v: 0.0 for v in nodes}
        while S:
            w = S.pop()
            for v in pred[w]:
                c = (sigma[v] / sigma[w]) * (1.0 + delta[w])
                k = frozenset((v, w))
                if k in bet:
                    bet[k] += c
                delta[v] += c                  # dependency flows back to the PREDECESSOR
    bridges = _find_bridges(adj)
    out: List[Dict[str, object]] = []
    for k, rec in edges.items():
        r = dict(rec)
        r["betweenness"] = round(bet.get(k, 0.0) / 2.0, 3)   # undirected: each pair counted from both ends
        r["is_bridge"] = k in bridges
        r["pairs_cut"] = _bridge_pairs_cut(adj, k) if r["is_bridge"] else 0
        out.append(r)
    out.sort(key=lambda r: (-float(r["betweenness"]), not r["is_bridge"], str(r["a_host"]), str(r["b_host"])))
    for i, r in enumerate(out, 1):
        r["rank"] = i
    return out


def compute_wave_sequencing(all_interfaces: Dict[str, Dict[str, InterfaceData]],
                            move_groups: List[Dict[str, object]]) -> List[Dict[str, object]]:
    """Per move-group CUTOVER SEQUENCING (migration doctrine: make-before-break vs hard cutover).
    Classify each member switch by uplink redundancy from the physical topology: a SINGLE-homed switch
    (one inter-switch uplink — its uplink is a bridge, see compute_link_centrality) is a HARD CUTOVER
    (the uplink can't be moved make-before-break, so schedule a maintenance window and the endpoints on it
    take a hit), while a DUAL-homed switch (>=2 uplinks) can migrate MAKE-BEFORE-BREAK (move one path,
    validate, move the other — no outage). Topology-derived (reuses _topology_adjacency); one source of
    truth with the bridge analysis. Returns, per group (index-aligned with move_groups / migration_readiness):
    {group, make_before_break:[host], hard_cutover:[host], hard_cutover_endpoints:int, sequence:str}."""
    _hosts, adj, _edges = _topology_adjacency(all_interfaces)
    ep: Dict[str, int] = {}                       # per-host distinct end-host count (mirrors compute_move_groups)
    for host, ifaces in all_interfaces.items():
        macs: set = set()
        for d in ifaces.values():
            # SAME MAC-eligibility as compute_move_groups (Access AND a numeric VLAN) so a wave's
            # hard_cutover_endpoints can never EXCEED the group's SSOT endpoint total (audit-2 L1).
            if (d.switchport_mode or "") == "Access" and str(getattr(d, "vlan", "") or "").isdigit():
                for m in _split_macs(d.end_host_mac):
                    macs.add(m)
        ep[host] = len(macs)
    out: List[Dict[str, object]] = []
    for gi, g in enumerate(move_groups, 1):
        switches = [str(h) for h in (g.get("switches") or [])]
        mbb, hard, unknown = [], [], []
        for h in switches:
            if h not in (all_interfaces or {}):
                unknown.append(h)        # NEVER collected -> homing UNKNOWN: empty adjacency is absence of
            elif len(adj.get(h, set())) >= 2:   # topology evidence, NOT proof of single-homing (audit-5 #7)
                mbb.append(h)
            else:
                hard.append(h)
        hard_ep = sum(ep.get(h, 0) for h in hard)
        if not switches:
            seq = "empty group"
        elif not hard and not unknown:
            seq = f"all {len(mbb)} switch(es) dual-homed — fully make-before-break (no outage window needed)"
        elif not mbb and not unknown:
            seq = f"all {len(hard)} switch(es) single-homed — every cutover needs a maintenance window"
        else:
            bits = []
            if hard: bits.append(f"{len(hard)} hard cutover (single-homed, schedule a window)")
            if mbb: bits.append(f"{len(mbb)} make-before-break (dual-homed)")
            if unknown: bits.append(f"{len(unknown)} homing UNKNOWN (never collected — verify uplinks first)")
            seq = " + ".join(bits)
        out.append({"group": f"Group {gi}", "make_before_break": sorted(mbb),
                    "hard_cutover": sorted(hard), "homing_unknown": sorted(unknown),
                    "hard_cutover_endpoints": hard_ep, "sequence": seq})
    return out


# =============================================================================
# Per-VLAN cutover matrix (MASTER_PLAN 2026-07-05 §4.3): the sheet a cutover team
# runs the maintenance window from. One row per evidenced VLAN, every column JOINED
# from data already computed/collected (stp_roots, FHRP brief+detail, gateway SVIs,
# endpoint census, application domains, move-groups + wave sequencing, readiness,
# multicast querier coverage, DHCP relay) -- pure synthesis, no new collection.
# Coverage-honest: a VLAN with no FHRP evidence reads '[NOT OBSERVED]'; the
# "sole gateway (no FHRP)" claim is made only when the gateway evidence POSITIVELY
# shows exactly one gateway (mirrors compute_migration_readiness's wording).
# =============================================================================
VLAN_CUTOVER_NOT_OBSERVED = "[NOT OBSERVED]"

_VLAN_CUTOVER_READY_RANK = {"NOT READY": 0, "CAUTION": 1, "READY": 2}   # worst-first pull-through


def _fmt_endpoint_mix(classes: Dict[str, int], limit: int = 4) -> str:
    """Compact per-VLAN endpoint composition, most-common first ('8 Server · 3 Phone · 1 AP'), with a
    long tail collapsed to '+N more'. Distinct from Criticality (which apps matter) — this is WHAT
    physically moves, which drives cutover test/rollback approach. Empty → coverage-honest [NOT OBSERVED]."""
    if not classes:
        return VLAN_CUTOVER_NOT_OBSERVED
    items = sorted(classes.items(), key=lambda kv: (-kv[1], kv[0]))
    head = items[:limit]
    s = " · ".join(f"{n} {cls}" for cls, n in head)
    extra = len(items) - len(head)
    return s + (f" · +{extra} more" if extra > 0 else "")


def compute_vlan_cutover_matrix(all_interfaces: Dict[str, Dict[str, InterfaceData]],
                                stp_roots: Optional[Dict[str, dict]] = None,
                                fhrp_detail: Optional[Dict[str, list]] = None,
                                endpoint_identity: Optional[List[dict]] = None,
                                application_intelligence: Optional[dict] = None,
                                move_groups: Optional[List[dict]] = None,
                                wave_sequencing: Optional[List[dict]] = None,
                                migration_readiness: Optional[List[dict]] = None,
                                multicast_intelligence: Optional[dict] = None) -> List[dict]:
    """One row per evidenced VLAN with every cutover-relevant fact pre-filled from evidence the
    snapshot already carries. Returns [{vlan, name, stp_root, stp_root_default_election, fhrp,
    gateway_svi_hosts, endpoint_count, app_domain, criticality, dependencies, wave, scenario,
    readiness, cutover_window, rollback_owner}] sorted by VLAN id. cutover_window / rollback_owner
    are DELIBERATELY blank -- they belong to the human running the window. Deterministic; tolerant
    of empty / oddly-typed inputs (every join input is optional and abstains as ''/[])."""
    from cisco_toolkit.parse import _parse_fhrp

    # ---- VLAN universe: access-port presence + gateway SVIs (+ names) -------------------------
    vlan_hosts: Dict[int, set] = {}
    names: Dict[int, str] = {}
    gws: Dict[int, List[tuple]] = {}                 # vid -> [(host, InterfaceData)] gateway SVIs
    for host in sorted(all_interfaces or {}):
        for port, d in (all_interfaces[host] or {}).items():
            v = (getattr(d, "vlan", "") or "").strip()
            if (getattr(d, "switchport_mode", "") or "") == "Access" and v.isdigit():
                vid = int(v)
                vlan_hosts.setdefault(vid, set()).add(host)
                nm = (getattr(d, "vlan_name", "") or "").strip()
                if nm:
                    names.setdefault(vid, nm)
            m = re.match(r"^Vlan0*(\d+)$", str(port), re.IGNORECASE)
            if not m:
                continue
            vid = int(m.group(1))
            vlan_hosts.setdefault(vid, set()).add(host)
            nm = (getattr(d, "vlan_name", "") or "").strip()
            if nm:
                names.setdefault(vid, nm)
            if (getattr(d, "svi_ip", "") or "").strip() or (getattr(d, "hsrp_behavior", "") or "").strip():
                gws.setdefault(vid, []).append((host, d))
    # STP root evidence adds VLAN presence too (a trunk-carried VLAN still runs an STP instance on
    # its root even where no local access port / SVI was collected). MST keys are INSTANCE numbers,
    # not VLAN ids -- excluded, mirroring stp_root_findings. First sorted host claiming root wins.
    root_of: Dict[int, str] = {}
    root_prio: Dict[int, object] = {}
    for host in sorted(stp_roots or {}):
        for vlan, rec in (stp_roots[host] or {}).items():
            if not str(vlan).isdigit() or not isinstance(rec, dict) or rec.get("is_mst"):
                continue
            vid = int(vlan)
            vlan_hosts.setdefault(vid, set()).add(host)
            if rec.get("is_root") and vid not in root_of:
                root_of[vid] = host
                root_prio[vid] = rec.get("root_priority")

    # ---- join indexes over the precomputed axes ------------------------------------------------
    det_ix: Dict[tuple, dict] = {}                   # (host, vid) -> FHRP election-detail record
    for host, recs in (fhrp_detail or {}).items():
        for rec in (recs or []):
            m = re.match(r"^Vlan0*(\d+)$", str((rec or {}).get("ifname", "")), re.IGNORECASE)
            if m:
                det_ix.setdefault((host, int(m.group(1))), rec)
    ep_count: Dict[int, int] = {}                    # per-VLAN sum of learned MACs (per-port sum)
    ep_classes: Dict[int, Dict[str, int]] = {}       # per-VLAN endpoint-class composition (mac-weighted)
    for r in (endpoint_identity or []):
        v = str((r or {}).get("vlan", "")).strip()
        if v.isdigit():
            n = int(r.get("mac_count") or 1)
            ep_count[int(v)] = ep_count.get(int(v), 0) + n
            cls = str((r or {}).get("endpoint_class") or "").strip() or "Unknown"
            d = ep_classes.setdefault(int(v), {})
            d[cls] = d.get(cls, 0) + n
    doms_of: Dict[int, List[dict]] = {}
    for dom in ((application_intelligence or {}).get("domains") or []):
        for v in ((dom or {}).get("vlans") or []):
            if str(v).strip().isdigit():
                doms_of.setdefault(int(str(v).strip()), []).append(dom)
    group_of: Dict[str, str] = {}                    # host -> its move-group label
    for gi, g in enumerate(move_groups or [], 1):
        for h in ((g or {}).get("switches") or []):
            group_of.setdefault(str(h), f"Group {gi}")
    seq_of = {str(r.get("group", "")): r for r in (wave_sequencing or []) if isinstance(r, dict)}
    ready_of = {str(r.get("group", "")): str(r.get("readiness", ""))
                for r in (migration_readiness or []) if isinstance(r, dict)}
    mq = ((multicast_intelligence or {}).get("querier")) or {}
    mcast_vlans = {str(v) for v in (mq.get("multicast_vlans") or [])}
    gap_vlans = {str(v) for v in (mq.get("gap_vlans") or [])}

    rows: List[dict] = []
    for vid in sorted(vlan_hosts):
        hosts = vlan_hosts[vid]
        # STP root + the default-election smell (same 32768 / 32768+vlan test as stp_root_findings)
        root = root_of.get(vid, VLAN_CUTOVER_NOT_OBSERVED)
        prio = root_prio.get(vid)
        default_election = bool(vid in root_of and isinstance(prio, int)
                                and prio in (32768, 32768 + vid))
        # FHRP: brief behaviour string joined with the election detail where collected
        gwl = gws.get(vid, [])
        members: List[dict] = []
        for host, d in gwl:
            proto, role, vip, grp = _parse_fhrp((getattr(d, "hsrp_behavior", "") or "").strip())
            det = det_ix.get((host, vid))
            if not proto and not det:
                continue                             # a gateway with no FHRP evidence of its own
            members.append({"host": host,
                            "proto": (proto or "HSRP").upper(),   # detail parses 'show standby' -> HSRP
                            "group": grp or str((det or {}).get("group") or ""),
                            "vip": vip or str((det or {}).get("vip") or ""),
                            "role": (role or str((det or {}).get("state") or "")).lower(),
                            "priority": (det or {}).get("priority"),
                            "preempt": (det or {}).get("preempt"),
                            "vmac": str((det or {}).get("vmac") or "")})
        if members:
            fhrp: object = {"proto": "/".join(sorted({m["proto"] for m in members if m["proto"]})),
                            "group": "/".join(sorted({m["group"] for m in members if m["group"]})),
                            "vip": "/".join(sorted({m["vip"] for m in members if m["vip"]})),
                            "members": members}
        elif len(gwl) == 1:
            # positively-observed sole gateway -- compute_migration_readiness's wording
            fhrp = f"sole gateway on {gwl[0][0]} (no FHRP)"
        elif gwl:
            # >=2 observed gateways, none running FHRP -- compute_fhrp_consistency's wording
            fhrp = f"{len(gwl)} gateways but no FHRP — no first-hop redundancy"
        else:
            fhrp = VLAN_CUTOVER_NOT_OBSERVED         # no gateway evidence at all -> no claim
        # application domain + criticality tier (highest tier leads when several domains map)
        doms = sorted(doms_of.get(vid, []),
                      key=lambda d: (_APP_TIER_RANK.get(str(d.get("tier", "")), 9),
                                     str(d.get("domain", ""))))
        app_domain = " + ".join(str(d.get("domain", "")) for d in doms[:3])
        criticality = str(doms[0].get("tier", "")) if doms else ""
        # dependency flags: multicast activity / querier gap / DHCP relay off the gateway SVIs
        deps: List[str] = []
        if str(vid) in mcast_vlans:
            deps.append("multicast active")
        if str(vid) in gap_vlans:
            deps.append("no IGMP querier")
        helpers: List[str] = []
        for _h, d in gwl:
            for tok in re.split(r"[\s,]+", (getattr(d, "dhcp_helpers", "") or "").strip()):
                if tok and tok not in helpers:
                    helpers.append(tok)
        if helpers:
            deps.append("DHCP relay via " + ", ".join(helpers))
        # wave / scenario / readiness: via the VLAN's OWN switches (a VLAN inherits the group's
        # sequencing only for the switches it actually rides)
        glabels = sorted({group_of[h] for h in hosts if h in group_of},
                         key=lambda s: int(s.split()[-1]) if s.split()[-1].isdigit() else 0)
        n_hard = n_mbb = n_unk = 0
        for gl in glabels:
            rec = seq_of.get(gl) or {}
            n_hard += len(hosts & set(rec.get("hard_cutover") or []))
            n_mbb += len(hosts & set(rec.get("make_before_break") or []))
            n_unk += len(hosts & set(rec.get("homing_unknown") or []))
        bits: List[str] = []
        if n_hard and n_mbb:
            bits.append(f"mixed: {n_hard} hard cutover / {n_mbb} make-before-break")
        elif n_hard:
            bits.append("hard cutover (maintenance window)")
        elif n_mbb:
            bits.append("make-before-break")
        if n_unk:
            bits.append(f"{n_unk} switch(es) homing unknown — verify uplinks first")
        verdicts = [ready_of[gl] for gl in glabels if ready_of.get(gl)]
        rows.append({
            "vlan": vid, "name": names.get(vid, ""),
            "stp_root": root, "stp_root_default_election": default_election,
            "fhrp": fhrp, "gateway_svi_hosts": sorted(h for h, _d in gwl),
            "endpoint_count": ep_count.get(vid, 0),
            "endpoint_mix": _fmt_endpoint_mix(ep_classes.get(vid, {})),
            "app_domain": app_domain, "criticality": criticality,
            "dependencies": deps, "wave": ", ".join(glabels),
            "scenario": "; ".join(bits),
            "readiness": min(verdicts, key=lambda v: _VLAN_CUTOVER_READY_RANK.get(v, 9)) if verdicts else "",
            "cutover_window": "", "rollback_owner": "",    # deliberately blank human fields
        })
    return rows


def compute_data_quality(all_cmd_to_files: Dict[str, Dict[str, str]]) -> Dict[str, float]:
    """NEW-V3.23.7: per-switch collection completeness = fraction of the essential
    command set that returned usable (non-empty, non-error) output, via the
    existing _load_cmd_output. compute_health_scores uses it to flag under-observed
    switches so a partial collection can't masquerade as a healthy device (C3)."""
    out: Dict[str, float] = {}
    for host, c2f in (all_cmd_to_files or {}).items():
        present = sum(1 for variants in _ESSENTIAL_CMD_VARIANTS
                      if _load_cmd_output(c2f, *variants).strip())
        out[host] = present / len(_ESSENTIAL_CMD_VARIANTS)
    return out


def vlan_inventory(snap: dict):
    """Canonical VLAN inventory: distinct VLAN ids evidenced as IN USE, with the best-known name.
    Returns an ordered list of (vid:int, name:str). Three independent evidence sources, unioned:
      1. access-port `.vlan`         — a host-facing port assigned to the VLAN,
      2. `l3_forwarding[].vlan`      — a collected SVI / L3 gateway for the VLAN,
      3. IGMP-querier-evidenced VLANs — an active IGMP querier observed FIRST-HAND by a collected
         switch. Per Cisco, exactly one querier (normally the L3 default gateway) exists per active
         VLAN/L2 segment, so a querier proves the VLAN is live and trunk-carried even when its SVI /
         gateway sits on a device that was NOT collected (e.g. an uncollected core). Omitting these
         undercounts migration scope and risks stranded multicast at cutover.
    Pure read. SINGLE SOURCE OF TRUTH: every deliverable that reports a "VLANs in use" count (design
    doc, CRD, executive_brief.scale.n_vlans -> explorer + webapp) derives it from THIS, so they cannot
    drift, and a narrower access-port-only derivation is only ever an explicitly-labelled subset."""
    names: dict = {}
    vids: set = set()
    _ifaces = snap.get("interfaces")
    for host, ports in (_ifaces if isinstance(_ifaces, dict) else {}).items():   # coerce: a non-dict interfaces
        for d in (ports if isinstance(ports, dict) else {}).values():            # block must not crash (audit-4 #10)
            if not isinstance(d, dict):
                continue
            # str(): a non-str vlan / vlan_name leaf (int, list, dict in a malformed upload) is truthy
            # and survives `or ""`, then 500s .strip() -- the same coercion crd/design/mop/runbook apply
            # to every device string-field before .strip()/.lower().
            v = str(d.get("vlan") or "").strip()
            if v.isdigit():
                vids.add(int(v))
                nm = str(d.get("vlan_name") or "").strip()
                if nm and int(v) not in names:
                    names[int(v)] = nm
    _l3f = snap.get("l3_forwarding")
    for r in (_l3f if isinstance(_l3f, list) else []):
        if not isinstance(r, dict):
            continue
        v = str(r.get("vlan") or "").strip()
        if v.isdigit():
            vids.add(int(v))
    # IGMP-querier-evidenced active VLANs (gateway may be on an uncollected device) -- see docstring.
    _svc = snap.get("service_map")
    _mc = _svc.get("multicast") if isinstance(_svc, dict) else None
    # isinstance, not `or []`: a TRUTHY non-list igmp_queriers (an int in a malformed upload) survives
    # `or []` and 500s `for q in ...` -> a stored DoS on every route that recounts VLANs (design + crd).
    _q = _mc.get("igmp_queriers") if isinstance(_mc, dict) else None
    for q in (_q if isinstance(_q, list) else []):
        if not isinstance(q, dict):
            continue
        v = str(q.get("vlan") or "").strip()
        if v.isdigit():
            vids.add(int(v))
    return [(v, names.get(v, "")) for v in sorted(vids)]


def compute_collection_completeness(inventory_hosts: List[str],
                                    all_cmd_to_files: Dict[str, Dict[str, str]]) -> dict:
    """NEW-V3.23.109: pre-assessment BLIND-SPOT report. Every assessment finding is only as trustworthy
    as the data behind it, so this makes the gaps explicit: for each device in the INVENTORY
    (devices.json), tier it as 'complete' (all essential commands returned usable output), 'partial'
    (some essentials missing -> the health score bands it Insufficient Data), or 'not collected' (no
    usable essential output at all -- unreachable / auth-failed / empty captures), and list exactly which
    essential commands are missing. Pure read; Confirmed evidence (we know what was/wasn't collected).
    Returns {summary:{inventory,complete,partial,not_collected}, devices:[blind spots only]}."""
    acf = all_cmd_to_files or {}
    hosts: List[str] = [h for h in (inventory_hosts or [])]
    for h in acf:                                   # include any collected host missing from the inventory list
        if h not in hosts:
            hosts.append(h)
    summary = {"inventory": 0, "complete": 0, "partial": 0, "not_collected": 0}
    devices: List[dict] = []
    seen: set = set()
    for host in hosts:
        if not host or host in seen:
            continue
        seen.add(host)
        summary["inventory"] += 1
        c2f = acf.get(host, {})
        missing = [label for variants, label in zip(_ESSENTIAL_CMD_VARIANTS, _ESSENTIAL_LABELS)
                   if not _load_cmd_output(c2f, *variants).strip()]
        present = len(_ESSENTIAL_CMD_VARIANTS) - len(missing)
        dq = round(100 * present / len(_ESSENTIAL_CMD_VARIANTS))
        if present == 0:
            status = "not collected"; summary["not_collected"] += 1
        elif missing:
            status = "partial"; summary["partial"] += 1
        else:
            status = "complete"; summary["complete"] += 1
        if status != "complete":                    # the report lists only the blind spots
            devices.append({"host": host, "status": status, "data_quality": dq, "missing": missing})
    order = {"not collected": 0, "partial": 1}
    devices.sort(key=lambda d: (order.get(d["status"], 9), d["host"]))
    return {"summary": summary, "devices": devices}

def compute_health_scores(all_interfaces: Dict[str, Dict[str, InterfaceData]],
                          physical_health: List[dict], l3_forwarding: List[dict],
                          cross_layer: List[dict], protocol_health: List[dict],
                          config: ScoringConfig = SCORING,
                          data_quality: Optional[Dict[str, float]] = None,
                          security: Optional[Dict[str, dict]] = None) -> List[dict]:
    """Per-switch 0-100 health score with weighted, category-capped deductions.
    Weights/caps/bands come from `config` (ScoringConfig); the default instance
    reproduces the prior hard-coded behaviour byte-for-byte. `security` (NEW-V3.23.60,
    optional) is {host: parse_security()}; each FAILED CIS check deducts via
    config.sec_weights (capped at caps['SEC']). Omitting it (or a host without a
    captured run-config) adds no SEC deduction -- missing posture is never scored as bad."""
    # Drop a blank/whitespace hostname (a malformed devices.json row that nonetheless collected): it must not
    # become a scored asset, because compute_collection_completeness ALSO skips `if not host` (analyze.py:998).
    # Keeping it here made len(health_scores) exceed the inventory count, and ssot.reconcile then false-fired an
    # assessment_integrity DRIFT alarm on a benign data-entry artifact rather than a real published-fact conflict.
    hosts = sorted(h for h in all_interfaces if str(h).strip())
    ded: Dict[str, Dict[str, List[Tuple[str, int]]]] = {
        h: {"L1": [], "L3": [], "XL": [], "PROTO": [], "SEC": []} for h in hosts}

    L1W = config.l1_weights
    for rec in (physical_health or []):
        h = rec.get("switch")
        if h not in ded:
            continue
        for flag, pts in L1W.items():
            if flag in rec.get("risk", ""):
                ded[h]["L1"].append((f"{flag} @ {rec.get('port','')}", pts))
    L3W = config.l3_weights
    for rec in (l3_forwarding or []):
        h = rec.get("switch")
        if h not in ded:
            continue
        for flag, pts in L3W.items():
            if flag in rec.get("risk", ""):
                ded[h]["L3"].append((f"{flag} (VLAN {rec.get('vlan','')})", pts))
    XLW = config.xl_weights
    for f in (cross_layer or []):
        pts = XLW.get(f.get("severity"), 0)
        for h in f.get("hosts", []):
            if h in ded:
                ded[h]["XL"].append((f"{f['id']} {f['severity']}", pts))
    PW = config.proto_weights
    for rec in (protocol_health or []):
        h = rec.get("switch")
        if h in ded and rec.get("severity") in PW:
            ded[h]["PROTO"].append((f"{rec['protocol']} {rec['severity']}", PW[rec["severity"]]))
    SECW = config.sec_weights                                    # NEW-V3.23.60 (CIS config-hardening posture)
    for h, sec in (security or {}).items():
        if h not in ded:
            continue
        for f in (sec.get("findings") or []):
            if f.get("status") != "fail":
                continue
            pts = SECW.get(f.get("severity"), 0)
            if pts:
                ded[h]["SEC"].append((f"{f.get('id', '')} {f.get('severity', '')}", pts))

    CAP = config.caps
    records: List[dict] = []
    for h in hosts:
        # NEW-V3.23.5: scale this switch's deductions by its criticality role (round() keeps
        # integer scores). role + factor are surfaced on the record so the asset-criticality
        # weighting is auditable (research: "every score shows its line-item contributions").
        role = _host_role(all_interfaces.get(h, {}))
        factor = config.criticality_factors.get(role, 1.0)
        total = 0
        reasons: List[str] = []
        for cat, items in ded[h].items():
            if cat not in CAP:                                  # NEW-V3.23.60: a custom ScoringConfig whose
                continue                                        # caps dict predates a category (e.g. SEC) just skips it
            csum = min(round(sum(p for _r, p in items) * factor), CAP[cat])
            total += csum
            for r, p in sorted(items, key=lambda x: -x[1]):
                reasons.append(f"{r} (-{p})")
        score = max(0, 100 - total)
        band, _fill = _health_band(score, config.bands)
        rec = {"switch": h, "score": score, "band": band,
               "role": role, "criticality": factor, "deductions": reasons[:8]}
        if data_quality is not None:                          # NEW-V3.23.7 (audit C3)
            # A host ABSENT from the map was never measured -- compute_data_quality keys off
            # all_cmd_to_files, so a host present in all_interfaces but with no capture record (and
            # EVERY host when the data-quality phase fell back to {}) fell through `.get(h, 1.0)` to a
            # fabricated perfect score: an affirmative "all four essential commands returned usable
            # output" claim about a measurement that was never taken, and one the `dq < threshold`
            # test could never fire on. Unmeasured is 'Insufficient Data' with dq None, not 1.0 (#15).
            if h not in data_quality:
                rec["data_quality"] = None
                rec["band"] = "Insufficient Data"
                records.append(rec)
                continue
            dq = data_quality[h]
            rec["data_quality"] = round(dq, 2)
            # A collection gap is not health -- AND neither is a device whose essentials WERE collected (dq ok)
            # yet whose interface parse yielded ZERO interfaces. compute_data_quality measures raw show-command
            # FILE presence, not parse YIELD, so a NOS/format the interface parser can't read (or a truncated
            # capture that clears the error filter) produced an empty parse -> no deductions -> a perfect 100
            # 'Excellent', ranking the unreadable box the single healthiest asset and excluding it from every
            # finding. An empty parse is 'Insufficient Data', never Excellent (the absence-is-not-health rule).
            if dq < config.data_quality_threshold or not all_interfaces.get(h):
                rec["band"] = "Insufficient Data"             # collection gap / unparseable != healthy
        records.append(rec)
    records.sort(key=lambda r: (r["score"], r["switch"]))
    return records

def compute_score_sensitivity(all_interfaces: Dict[str, Dict[str, InterfaceData]],
                              physical_health: List[dict], l3_forwarding: List[dict],
                              cross_layer: List[dict], protocol_health: List[dict],
                              config: ScoringConfig = SCORING,
                              deltas: Tuple[float, ...] = (-0.5, -0.25, 0.25, 0.5),
                              security: Optional[Dict[str, dict]] = None) -> List[dict]:
    """NEW-V3.23.5: one-at-a-time (OAT) sensitivity sweep over the scoring weights.
    For each weight group, re-score the fleet with that group scaled by each delta
    and report how many switches change health band. Verdicts that flip under a
    small (+/-25%) perturbation are weakly supported - this is the OECD/JRC
    composite-indicator robustness check. Pure derivation; no new collection."""
    import dataclasses

    def _bands(cfg):
        return {r["switch"]: r["band"] for r in compute_health_scores(
            all_interfaces, physical_health, l3_forwarding, cross_layer, protocol_health, cfg,
            security=security)}

    base = _bands(config)
    out: List[dict] = []
    for grp in ("l1_weights", "l3_weights", "xl_weights", "proto_weights", "sec_weights"):
        for delta in deltas:
            scaled = {k: max(0, round(v * (1 + delta))) for k, v in getattr(config, grp).items()}
            new = _bands(dataclasses.replace(config, **{grp: scaled}))
            changed = sorted(h for h in base if base[h] != new.get(h))
            out.append({
                "perturbation": f"{grp.replace('_weights', '').upper()} "
                                f"{'+' if delta > 0 else ''}{int(delta * 100)}%",
                "group": grp, "delta_pct": int(delta * 100),
                "switches_changed_band": len(changed),
                "changed": changed,
                "detail": "; ".join(f"{h}: {base[h]}->{new[h]}" for h in changed) or "no band changes",
            })
    out.sort(key=lambda r: (-r["switches_changed_band"], r["group"], r["delta_pct"]))
    return out

def compute_calibration_report(health_scores: List[dict],
                               config: ScoringConfig = SCORING) -> dict:
    """NEW-V3.23.47: fleet-level scoring-CALIBRATION diagnostic over the computed
    health scores. Reports the band distribution + score spread, a discrimination
    metric (how well the current bands actually separate THIS fleet), and -- when
    discrimination is poor -- data-driven quantile band thresholds as a re-banding
    suggestion.

    This addresses the standing 'weights/bands are an uncalibrated default'
    limitation from a different angle than `compute_score_sensitivity` (which tests
    weight robustness): the *weights* can't be fit without a labelled dataset, but a
    scoring system that lumps every switch into one band gives no decision value
    regardless of the weights -- so we surface whether the BANDS discriminate at all,
    and offer a relative (curve-graded) re-banding when they don't. Pure derivation;
    no new collection. 'Insufficient Data' switches are excluded from the stats."""
    import math
    import statistics
    # is_finite_num + the per-row dict guard: `health_scores` is read from a snapshot, and
    # `isinstance(score, (int, float))` admits BOTH values json.loads accepts but float arithmetic
    # cannot survive -- the bare `Infinity`/`NaN` (statistics.mean -> int(nan) ValueError) and an
    # unbounded-precision int literal (OverflowError). `or []` also kept a truthy non-list section.
    scored = [r for r in (health_scores if isinstance(health_scores, list) else [])
              if isinstance(r, dict)
              and is_finite_num(r.get("score")) and r.get("band") != "Insufficient Data"]
    n = len(scored)
    if n == 0:
        return {"n": 0, "note": "no scored switches to calibrate against",
                "score_stats": {}, "band_distribution": [], "modal_band": "",
                "modal_pct": 0, "discrimination": None,
                "discrimination_quality": "unknown", "suggested_bands": None}
    scores = sorted(float(r["score"]) for r in scored)

    def _pct(p: float) -> float:   # linear-interpolated percentile on the sorted scores
        if n == 1:
            return scores[0]
        k = (n - 1) * p
        lo, hi = int(math.floor(k)), int(math.ceil(k))
        return scores[lo] if lo == hi else scores[lo] + (scores[hi] - scores[lo]) * (k - lo)

    stats = {"min": round(scores[0]), "max": round(scores[-1]),
             "mean": round(statistics.mean(scores), 1),
             "median": round(statistics.median(scores), 1),
             "p25": round(_pct(0.25), 1), "p75": round(_pct(0.75), 1),
             "stdev": round(statistics.pstdev(scores), 1)}

    order = list(dict.fromkeys(label for _thr, label, _fill in config.bands))   # band labels, highest-first
    counts = {label: 0 for label in order}
    for r in scored:
        counts[r["band"]] = counts.get(r["band"], 0) + 1
    band_distribution = [{"band": b, "count": counts[b], "pct": round(100 * counts[b] / n)}
                         for b in order]
    modal_band = max(order, key=lambda b: counts[b])
    modal_pct = round(100 * counts[modal_band] / n)

    # discrimination = normalized Shannon entropy of the band distribution (0 = all one band, 1 = uniform)
    H = -sum((c / n) * math.log(c / n) for c in counts.values() if c > 0)
    Hmax = math.log(len(order)) if len(order) > 1 else 1.0
    disc = round(H / Hmax, 2) if Hmax > 0 else 0.0
    if n < 4:
        quality = "n/a (too few switches)"
    elif disc < 0.4 or modal_pct >= 80:
        quality = "poor"
    elif disc < 0.7:
        quality = "fair"
    else:
        quality = "good"

    # Relative (curve-graded) re-banding: place thresholds at even quantiles so the fleet
    # spreads across every band. Only offered when discrimination is poor -- it is
    # norm-referenced (rank the fleet), NOT criterion-referenced like the absolute default.
    suggested = None
    if quality == "poor" and n >= len(order):
        k = len(order)
        suggested = [{"threshold": (0 if i == k - 1 else round(_pct((k - 1 - i) / k))), "band": label}
                     for i, label in enumerate(order)]

    note = (f"{n} switch(es); scores {stats['min']}-{stats['max']} (median {stats['median']}). "
            f"{modal_pct}% in '{modal_band}'. Band discrimination: {quality}"
            + (" -- consider the suggested quantile re-banding (relative grading)." if suggested else "."))
    return {"n": n, "score_stats": stats, "band_distribution": band_distribution,
            "modal_band": modal_band, "modal_pct": modal_pct, "discrimination": disc,
            "discrimination_quality": quality, "suggested_bands": suggested, "note": note}

_FHRP_PROTOCOL_ORDER = {"HSRP": 0, "VRRP": 1, "GLBP": 2}
_FHRP_VALIDATION = {
    "HSRP": {
        "command": "show standby brief",
        "leader_roles": ("Active",),
        "backup_roles": ("Standby", "Listen", "Speak"),
        "degraded_roles": ("Init", "Learn"),
    },
    "VRRP": {
        "command": "show vrrp brief",
        "leader_roles": ("Master",),
        "backup_roles": ("Backup",),
        "degraded_roles": ("Init",),
    },
    "GLBP": {
        "command": "show glbp brief",
        "leader_roles": ("Active",),
        "backup_roles": ("Standby", "Listen", "Speak"),
        "degraded_roles": ("Disabled", "Init", "Learn"),
    },
}


def summarize_fhrp_elections(all_interfaces: Any) -> List[dict]:
    """Return deterministic, evidence-bounded FHRP election summaries per L3 domain.

    The input may contain live ``InterfaceData`` objects or the dictionary records
    serialized into a snapshot.  ``hsrp_behavior`` carries only one projected group
    per SVI, and device captures are not simultaneous, so identity differences and
    cross-member role views are REVIEW evidence rather than proof of a broken pair.
    Only an unambiguously faulted local role is ``degraded``.  A single observed
    backup is healthy bounded evidence; no expected member count is invented.
    """
    if not isinstance(all_interfaces, dict):
        return []

    def _field(record: Any, name: str) -> Any:
        return record.get(name) if isinstance(record, dict) else getattr(record, name, "")

    by_domain: Dict[tuple, List[dict]] = {}
    for host_value, ifaces in all_interfaces.items():
        if not isinstance(ifaces, dict):
            continue
        host = str(host_value or "").strip()
        if not host:
            continue
        for interface_value, record in ifaces.items():
            interface = normalize_ifname(str(interface_value or "").strip())
            match = re.match(r"^Vlan(\d+)$", interface, re.IGNORECASE)
            if not match:
                continue
            behavior = _field(record, "hsrp_behavior")
            if not isinstance(behavior, str) or not behavior.strip():
                continue
            protocol, role, vip, group = _parse_fhrp(behavior)
            if protocol not in _FHRP_VALIDATION:
                continue
            vlan = int(match.group(1))
            raw_vrf = str(_field(record, "vrf") or "").strip().lower()
            vrf = "" if raw_vrf in ("", "default", "global") else raw_vrf
            svi_ip = str(_field(record, "svi_ip") or "").strip()
            subnet = _svi_network(svi_ip) or "(subnet-unobserved)"
            by_domain.setdefault((vlan, vrf, subnet), []).append({
                "host": host,
                "interface": interface,
                "protocol": protocol,
                "role": role,
                "group": group,
                "vip": vip,
            })

    rows: List[dict] = []
    for vlan, vrf, subnet in sorted(by_domain):
        members = sorted(
            by_domain[(vlan, vrf, subnet)],
            key=lambda member: (
                _FHRP_PROTOCOL_ORDER[member["protocol"]],
                int(member["group"]) if str(member["group"]).isdigit() else 10**9,
                str(member["group"]), str(member["vip"]),
                str(member["host"]).casefold(), str(member["host"]),
                str(member["interface"]).casefold(), str(member["role"]).casefold(),
            ),
        )
        protocols = sorted({member["protocol"] for member in members},
                           key=lambda protocol: _FHRP_PROTOCOL_ORDER[protocol])
        issues: List[str] = []
        findings: List[dict] = []
        has_degraded = False
        has_review = False
        scope = f"VLAN {vlan}, VRF {vrf or 'global'}, subnet {subnet}"

        def add_degraded(issue: str, finding_protocols, finding_hosts) -> None:
            nonlocal has_degraded
            has_degraded = True
            issues.append(issue)
            findings.append({"kind": "degraded", "issue": issue,
                             "protocols": sorted(set(finding_protocols),
                                                 key=lambda value: _FHRP_PROTOCOL_ORDER[value]),
                             "hosts": sorted(set(finding_hosts), key=lambda value: (value.casefold(), value))})

        def add_review(issue: str, finding_protocols, finding_hosts) -> None:
            nonlocal has_review
            has_review = True
            issues.append(issue)
            findings.append({"kind": "review", "issue": issue,
                             "protocols": sorted(set(finding_protocols),
                                                 key=lambda value: _FHRP_PROTOCOL_ORDER[value]),
                             "hosts": sorted(set(finding_hosts), key=lambda value: (value.casefold(), value))})

        if len(protocols) > 1:
            add_review(
                f"mixed FHRP protocols observed in {scope}: {', '.join(protocols)}; the one-record-per-SVI "
                "projection cannot distinguish independent elections from a mismatched pair — review required",
                protocols, [member["host"] for member in members],
            )

        for protocol in protocols:
            metadata = _FHRP_VALIDATION[protocol]
            protocol_members = [member for member in members if member["protocol"] == protocol]
            groups = sorted({member["group"] for member in protocol_members if member["group"]},
                            key=lambda value: (int(value) if value.isdigit() else 10**9, value))
            if len(groups) > 1:
                add_review(
                    f"{protocol} observed groups differ in {scope}: {', '.join(groups)}; the one-record-per-SVI "
                    "projection cannot distinguish independent elections from a mismatched pair — review required",
                    [protocol], [member["host"] for member in protocol_members],
                )
            vips = sorted({member["vip"] for member in protocol_members if member["vip"]})
            if len(vips) > 1:
                add_review(
                    f"{protocol} observed VIPs differ in {scope}: {', '.join(vips)}; the one-record-per-SVI "
                    "projection cannot distinguish independent elections from a mismatched pair — review required",
                    [protocol], [member["host"] for member in protocol_members],
                )
            elif len(protocol_members) > 1 and any(not member["vip"] for member in protocol_members):
                add_review(
                    f"{protocol} observed VIP evidence is incomplete in {scope} — live verification required",
                    [protocol], [member["host"] for member in protocol_members],
                )

            accepted = {
                role.casefold()
                for role in (*metadata["leader_roles"], *metadata["backup_roles"])
            }
            degraded = {role.casefold() for role in metadata["degraded_roles"]}
            for member in protocol_members:
                election = f"{protocol} group {member['group'] or '?'}"
                if member["vip"]:
                    election += f" VIP {member['vip']}"
                role_key = str(member["role"]).casefold()
                if role_key in degraded:
                    add_degraded(
                        f"{election} on {member['host']} {member['interface']} observed degraded "
                        f"role {member['role']}", [protocol], [member["host"]],
                    )
                elif role_key not in accepted:
                    add_review(
                        f"{election} on {member['host']} {member['interface']} observed unclassified "
                        f"role {member['role'] or '<missing>'} — live verification required",
                        [protocol], [member["host"]],
                    )

            elections: Dict[tuple, List[dict]] = {}
            for member in protocol_members:
                elections.setdefault((member["group"], member["vip"]), []).append(member)
            leader_roles = {role.casefold() for role in metadata["leader_roles"]}
            leader_label = "/".join(metadata["leader_roles"])
            for (group, vip), election_members in sorted(elections.items()):
                if len(election_members) < 2:
                    continue
                leaders = sum(
                    1 for member in election_members
                    if str(member["role"]).casefold() in leader_roles
                )
                identity = f"{protocol} group {group or '?'}"
                if vip:
                    identity += f" VIP {vip}"
                if leaders == 0:
                    add_review(
                        f"{identity} has no observed {leader_label} role across "
                        f"{len(election_members)} sequentially captured members; scope may be incomplete — "
                        "live simultaneous verification required",
                        [protocol], [member["host"] for member in election_members],
                    )
                elif leaders > 1:
                    add_review(
                        f"{identity} has {leaders} observed {leader_label} roles across "
                        f"{len(election_members)} sequentially captured members; capture timing may show election "
                        "churn — live simultaneous verification required",
                        [protocol], [member["host"] for member in election_members],
                    )

        for member in members:
            applicable = [finding for finding in findings
                          if member["protocol"] in finding["protocols"]
                          and member["host"] in finding["hosts"]]
            member["status"] = (
                "degraded" if any(finding["kind"] == "degraded" for finding in applicable)
                else ("review" if applicable else "healthy")
            )
            member["issues"] = [finding["issue"] for finding in applicable]

        validation = []
        for protocol in protocols:
            metadata = _FHRP_VALIDATION[protocol]
            validation.append({
                "protocol": protocol,
                "command": metadata["command"],
                "leader_roles": list(metadata["leader_roles"]),
                "backup_roles": list(metadata["backup_roles"]),
                "degraded_roles": list(metadata["degraded_roles"]),
            })
        rows.append({
            "vlan": vlan,
            "vrf": vrf,
            "subnet": subnet,
            "status": "degraded" if has_degraded else ("review" if has_review else "healthy"),
            "issues": issues,
            "findings": findings,
            "members": members,
            "validation": validation,
        })
    return rows


_FHRP_CONFIGURED_BLOCKER_STATES = frozenset({"degraded", "review", "not_verified"})


def _fhrp_projection_identity(record: Any) -> Optional[Tuple[str, str, str, str]]:
    """Return the exact local member identity shared by the two FHRP owners.

    The configured-group owner names a device with ``switch`` while the observed-election
    owner uses ``host``.  VIP is deliberately not part of this identity: a configured/runtime
    VIP disagreement is itself blocker evidence for the same local protocol/interface/group
    subject and must not cause a duplicate legacy row.
    """
    if not isinstance(record, dict):
        return None
    host = _strict_protocol_text(record.get("switch") or record.get("host"))
    protocol = _strict_protocol_text(record.get("protocol")).upper()
    interface = normalize_ifname(_strict_protocol_text(record.get("interface")))
    group = _strict_protocol_text(record.get("group"))
    if not host or protocol not in _FHRP_VALIDATION or not interface or not group:
        return None
    return (host.casefold(), protocol, interface.casefold(), group)


def _uncovered_fhrp_election_blockers(
        elections: Any, configured_rows: Any) -> List[Tuple[dict, dict]]:
    """Return observed election blocker members not owned by an exact configured row.

    Configured FHRP reconciliation and the compatibility one-record-per-SVI election view
    answer overlapping but non-identical questions.  A validated current-run configured
    blocker suppresses only its exact local member duplicate.  Mixed protocol/group/VIP and
    broader domain findings therefore remain additive, while healthy legacy members never
    duplicate configured acceptance rows.
    """
    rows = configured_rows if isinstance(configured_rows, list) else []
    covered: set[Tuple[str, str, str, str]] = set()
    for row in rows:
        if (
            not isinstance(row, dict)
            or _strict_protocol_text(row.get("status")).lower()
            not in _FHRP_CONFIGURED_BLOCKER_STATES
            or _strict_protocol_text(row.get("projection_custody"))
            != "current_run_source_bound"
        ):
            continue
        identity = _fhrp_projection_identity(row)
        if identity is not None:
            covered.add(identity)

    uncovered: List[Tuple[dict, dict]] = []
    safe_elections = elections if isinstance(elections, list) else []
    for election in safe_elections:
        if not isinstance(election, dict):
            continue
        members = election.get("members")
        for member in members if isinstance(members, list) else []:
            if not isinstance(member, dict):
                continue
            if _strict_protocol_text(member.get("status")).lower() not in {"degraded", "review"}:
                continue
            identity = _fhrp_projection_identity(member)
            # An unkeyable observed blocker cannot be proven covered, so retain it fail-closed.
            if identity is None or identity not in covered:
                uncovered.append((election, member))
    return uncovered


# Pre-migration checks; each returns (status, note). status in pass/warn/fail/info.
# Each check is mapped to a recognized migration-runbook phase (Inventory ->
# Baseline capture -> Dependency mapping -> Pilot/cutover -> Rollback) so the
# checklist is auditable against an external standard rather than ad hoc.
_READINESS_PHASES = {
    "Redundant uplinks": "Pilot/cutover",
    "Gateway redundancy": "Pilot/cutover",
    "No cross-layer Critical": "Dependency mapping",
    "No err-disabled ports": "Baseline capture",
    "STP consistency": "Dependency mapping",
    "Port-channels healthy": "Baseline capture",
    "Routing adjacencies up": "Baseline capture",
    "IPv6 routing adjacencies": "Baseline capture",
    "No orphan VLANs": "Inventory",
    "Clean uplinks (no half-duplex)": "Baseline capture",
    "Device health floor": "Pilot/cutover",
    "Dependency mapping complete": "Dependency mapping",
    "Baseline capture": "Baseline capture",
    "Rollback plan documented": "Rollback",
}


# ``None`` is a meaningful, explicitly supplied failed receipt.  A private
# sentinel keeps older direct callers on the historical sparse-health path
# while allowing current callers to fail closed when the receipt is absent.
_PROTOCOL_ASSESSABILITY_UNSET = object()

_FHRP_REDUNDANCY_DOMAIN_NOT_VERIFIED = (
    "FHRP REDUNDANCY DOMAIN NOT VERIFIED — BLOCKER:"
)


def _static_fhrp_redundancy_domain_rows(
        all_interfaces: Any, fhrp_configured_group_baseline: Any) -> List[dict]:
    """Return one safe, static abstention row per currently scoped SVI member.

    The domain receipt itself is deliberately not accepted here.  Identity comes only from the
    producer-owned scope helper over current interfaces plus the separately validated configured-group
    source; no rejected domain leaf can reach a decision surface.
    """
    rows: List[dict] = []
    for member in scope_fhrp_redundancy_domains(
            all_interfaces, fhrp_configured_group_baseline):
        if not isinstance(member, dict):
            continue
        host = member.get("switch") if isinstance(member.get("switch"), str) else ""
        interface = member.get("interface") if isinstance(member.get("interface"), str) else ""
        domain_key = member.get("domain_key") if isinstance(member.get("domain_key"), str) else ""
        if not host or not interface or not domain_key:
            continue
        vlan_value = member.get("vlan")
        vlan = vlan_value if type(vlan_value) is int else 0
        vrf = member.get("vrf") if isinstance(member.get("vrf"), str) else ""
        subnet = member.get("subnet") if isinstance(member.get("subnet"), str) else ""
        svi_ip = member.get("svi_ip") if isinstance(member.get("svi_ip"), str) else ""
        command_interface = interface if re.fullmatch(r"[A-Za-z][A-Za-z0-9./:-]{0,79}", interface) else ""
        command = (
            f"show running-config interface {command_interface}"
            if command_interface else "show ip interface brief"
        )
        rows.append({
            "switch": host,
            "interface": interface,
            "svi_ip": svi_ip,
            "vlan": vlan,
            "vrf": vrf,
            "subnet": subnet,
            "domain_key": domain_key,
            "candidate_key": "",
            "participation": "not_verified",
            "protocol": "",
            "group": "",
            "virtual_ip": "",
            "role": "",
            "status": "not_verified",
            "check": "FHRP redundancy-domain baseline not verified",
            "command": command,
            "acceptance": (
                f"{_FHRP_REDUNDANCY_DOMAIN_NOT_VERIFIED} No validated, source-bound "
                "current-run domain receipt authorizes a positive acceptance target for this "
                "scoped SVI member. Recompute the redundancy-domain baseline from current interfaces "
                "and the configured-group receipt before cutover."
            ),
            "why": (
                "The authoritative domain receipt was unavailable, embedded, malformed, or phase-failed; "
                "intended cross-switch FHRP membership and election composition remain unresolved."
            ),
            "source_key": "fhrp_redundancy_domain_baseline",
            "projection_custody": "embedded_unverified",
            "findings": [],
        })
    return rows


def _fhrp_redundancy_domain_consumer_view(
        value: Any, all_interfaces: Any, fhrp_configured_group_baseline: Any) -> dict:
    """Resolve authoritative current rows or a scope-only static abstention projection."""
    view = validate_fhrp_redundancy_domain_baseline(value, require_current_run=True)
    authorized = view.get("valid") is True and view.get("source_bound") is True
    return {
        "valid": authorized,
        "rows": (
            list(view.get("rows") or [])
            if authorized else
            _static_fhrp_redundancy_domain_rows(
                all_interfaces, fhrp_configured_group_baseline)
        ),
    }


_VTP_SCOPE_ABSTENTION_HOST = "(VTP subject scope not verified)"
_VTP_SCOPE_REJECTION_REASONS = {
    "scope_input_invalid", "scope_identity_invalid", "scope_host_cap_exceeded",
    "scope_identity_collision",
}


def _vtp_safety_scope_hosts(value: Any) -> set[str]:
    """Validate the path-free output of ``scope_vtp_safety_subjects``.

    The scope can only add static blockers; it never authorizes a positive row.  Reject the whole
    list on malformed, duplicate, or case-fold-colliding identities so hostile persisted data is
    neither echoed nor partially interpreted.
    """
    if value is None:
        return set()
    if (not isinstance(value, dict)
            or set(value) != {"schema", "valid", "attempted", "reason", "rows"}
            or value.get("schema") != "vtp_safety_subject_scope/1"
            or type(value.get("valid")) is not bool
            or type(value.get("attempted")) is not bool
            or not isinstance(value.get("reason"), str)
            or not value["reason"] or value["reason"] != value["reason"].strip()
            or len(value["reason"]) > 80
            or any(ord(char) < 32 or ord(char) == 127 for char in value["reason"])
            or not isinstance(value.get("rows"), list)):
        return {_VTP_SCOPE_ABSTENTION_HOST}
    if value["valid"] is False:
        return {_VTP_SCOPE_ABSTENTION_HOST}
    if value["reason"] != "ok":
        return {_VTP_SCOPE_ABSTENTION_HOST}
    if value["attempted"] is False and value["rows"] == []:
        return set()
    if value["attempted"] is not True or not value["rows"]:
        return {_VTP_SCOPE_ABSTENTION_HOST}
    value = value["rows"]
    if len(value) > 4096:
        return {_VTP_SCOPE_ABSTENTION_HOST}
    hosts: set[str] = set()
    folded: set[str] = set()
    for row in value:
        if not isinstance(row, dict) or set(row) != {"switch", "platform", "command"}:
            return {_VTP_SCOPE_ABSTENTION_HOST}
        host = row.get("switch")
        platform = row.get("platform")
        command = row.get("command")
        if (not isinstance(host, str) or not host or host != host.strip() or len(host) > 128
                or any(ord(char) < 32 or ord(char) == 127 for char in host)
                or not isinstance(platform, str) or platform != platform.strip()
                or len(platform) > 80
                or any(ord(char) < 32 or ord(char) == 127 for char in platform)
                or command != "show vtp status"):
            return {_VTP_SCOPE_ABSTENTION_HOST}
        identity = host.casefold()
        if identity in folded:
            return {_VTP_SCOPE_ABSTENTION_HOST}
        folded.add(identity)
        hosts.add(host)
    return hosts


def _vtp_safety_scope_reason(value: Any) -> str:
    """Return only producer-owned scope reason tokens; malformed values get static copy."""
    if value is None:
        return ""
    if (isinstance(value, dict)
            and value.get("schema") == "vtp_safety_subject_scope/1"
            and value.get("valid") is False
            and value.get("reason") in _VTP_SCOPE_REJECTION_REASONS):
        return value["reason"]
    if _vtp_safety_scope_hosts(value) == {_VTP_SCOPE_ABSTENTION_HOST}:
        return "scope_contract_invalid"
    return ""


def _vtp_safety_subject_hosts(protocol_health: Any, protocol_assessability: Any,
                              vtp_safety_subject_scope: Any = None) -> set[str]:
    """Return only independently evidenced VTP subjects for a static abstention row.

    Rejected VTP receipts contribute no leaves.  A sparse VTP health row, or a validated seven-family
    receipt proving the exact status command was attempted (usable/empty/error), is sufficient to
    scope a host but never to authorize mode/domain/revision acceptance text.
    """
    hosts = _vtp_safety_scope_hosts(vtp_safety_subject_scope)
    if isinstance(protocol_health, list):
        for row in protocol_health:
            if not isinstance(row, dict):
                continue
            host = _strict_protocol_text(row.get("switch"))
            if host and _strict_protocol_text(row.get("protocol")) == "VTP":
                hosts.add(host)
    receipt = _validate_protocol_assessability_receipt(protocol_assessability)
    if receipt.get("valid") is True:
        subjects = {
            (host, protocol)
            for (host, protocol), row in (receipt.get("index") or {}).items()
            if isinstance(row, dict) and (
                row.get("health_row_emitted") is True
                or (protocol == "VTP"
                    and isinstance(row.get("input_states"), dict)
                    and row["input_states"].get("status") in {"usable", "empty", "error"})
            )
        }
    else:
        subjects = set(receipt.get("claimed_subjects") or set())
    hosts.update(host for host, protocol in subjects if protocol == "VTP" and host)
    return hosts


def _static_vtp_safety_rows(hosts: Any, reason: str = "") -> List[dict]:
    rows: List[dict] = []
    safe_reason = _strict_protocol_text(reason)[:180]
    for host in sorted(
            {_strict_protocol_text(value) for value in (hosts or set())
             if _strict_protocol_text(value)},
            key=lambda value: (value.casefold(), value)):
        scope_abstention = host == _VTP_SCOPE_ABSTENTION_HOST
        rows.append({
            "switch": host,
            "platform": "",
            "mode": "unknown",
            "mode_present": False,
            "domain": "",
            "domain_present": False,
            "revision": 0,
            "revision_present": False,
            "version": "",
            "version_present": False,
            "status": "not_verified",
            "command": "show vtp status",
            "acceptance": (
                "VTP SAFETY BASELINE NOT VERIFIED — BLOCKER: No validated, source-bound "
                "current-run VTP safety baseline authorizes a positive cutover acceptance target. "
                "Re-collect show vtp status and explicitly disposition VTP domain/revision risk "
                "before the window."
            ),
            "why": (
                "The VTP safety analysis failed closed"
                + (f": {safe_reason}" if safe_reason else ".")
            ),
            "source_key": (
                "vtp_safety_subject_scope.valid/attempted/reason + vtp_safety_baseline"
                if scope_abstention else
                f"vtp_safety_subject_scope[{host}] + "
                f"protocol_assessability.rows[{host},VTP] + "
                f"protocol_health[{host},VTP] + vtp_safety_baseline"
            )[:300],
            "projection_custody": "embedded_unverified",
            "findings": [],
        })
    return rows


def _vtp_safety_consumer_view(value: Any, protocol_health: Any,
                              protocol_assessability: Any,
                              vtp_safety_subject_scope: Any = None) -> dict:
    """Resolve current-run owner rows or a subject-scoped static abstention projection."""
    view = validate_vtp_safety_baseline(value, require_current_run=True)
    authorized = view.get("valid") is True and view.get("source_bound") is True
    if not authorized:
        scope_reason = _vtp_safety_scope_reason(vtp_safety_subject_scope)
        baseline_reason = _strict_protocol_text(view.get("reason"))
        return {
            "valid": False,
            "rows": _static_vtp_safety_rows(
                _vtp_safety_subject_hosts(
                    protocol_health, protocol_assessability, vtp_safety_subject_scope),
                "; ".join(reason for reason in (scope_reason, baseline_reason) if reason),
            ),
        }

    baseline = view.get("baseline") if isinstance(view.get("baseline"), dict) else {}
    rows = [dict(row) for row in (view.get("rows") or []) if isinstance(row, dict)]
    attributed = {_strict_protocol_text(row.get("switch")) for row in rows}
    fallback_hosts = {
        _strict_protocol_text(cell.get("switch"))
        for cell in (baseline.get("coverage") or [])
        if isinstance(cell, dict) and cell.get("subject") is True
        and _strict_protocol_text(cell.get("status")) in {"review", "not_verified"}
        and _strict_protocol_text(cell.get("switch")) not in attributed
    }
    if fallback_hosts:
        rows.extend(_static_vtp_safety_rows(
            fallback_hosts,
            "the source-bound VTP receipt has blocking coverage without an attributable row",
        ))
    return {"valid": True, "rows": rows}


def _vtp_safety_finding_codes(row: Any) -> set[str]:
    if not isinstance(row, dict) or not isinstance(row.get("findings"), list):
        return set()
    return {
        code
        for finding in row["findings"]
        if isinstance(finding, dict)
        for code in [_strict_protocol_text(finding.get("code"))]
        if code
    }


_IPV6_ROUTING_PROTOCOLS = ("OSPFv3", "BGPv6")
_IPV6_ROUTING_PROTOCOL_ORDER = {
    protocol: index for index, protocol in enumerate(_IPV6_ROUTING_PROTOCOLS)
}
_IPV6_ROUTING_SCOPE_ABSTENTION_HOST = "(IPv6 routing subject scope not verified)"
_IPV6_ROUTING_SCOPE_REASONS = {
    "scope_input_invalid",
    "scope_identity_invalid",
    "scope_identity_collision",
    "scope_host_cap_exceeded",
    "scope_evidence_rejected",
}


def _ipv6_routing_scope_text(value: Any, limit: int, *, required: bool) -> bool:
    """Return whether a scope identity leaf is bounded, one-line UTF-8 text."""
    if (not isinstance(value, str) or len(value) > limit
            or value != value.strip() or (required and not value)
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _ipv6_routing_scope_subjects(value: Any) -> set[tuple[str, str, str]]:
    """Strictly consume the path-free, blocker-only IPv6 subject scope.

    A valid scope row can only scope a static NOT VERIFIED blocker. It never
    authorizes a peer/state acceptance target. Malformed, rejected, colliding,
    missing, or over-cap scope produces one fixed unattributed blocker without
    echoing any caller-controlled leaf. Direct-call compatibility is retained
    because callers that omit the baseline argument never invoke this helper.
    """
    global_blocker = {
        (_IPV6_ROUTING_SCOPE_ABSTENTION_HOST, "", "IPv6 Routing")
    }
    if value is None:
        return global_blocker
    if (not isinstance(value, dict)
            or set(value) != {"schema", "valid", "attempted", "reason", "rows"}
            or value.get("schema") != "ipv6_routing_subject_scope/1"
            or type(value.get("valid")) is not bool
            or type(value.get("attempted")) is not bool
            or not _ipv6_routing_scope_text(value.get("reason"), 80, required=True)
            or not isinstance(value.get("rows"), list)):
        return global_blocker
    if value["valid"] is False:
        if value["reason"] not in _IPV6_ROUTING_SCOPE_REASONS or value["rows"]:
            return global_blocker
        # A producer-owned invalid receipt scopes a blocker only when a
        # recognized IPv6 command was actually attempted.  A malformed scope
        # above cannot make that bounded claim and therefore fails closed to
        # one global blocker; an exact invalid/unattempted receipt is neutral.
        return global_blocker if value["attempted"] else set()
    if value["reason"] != "ok" or len(value["rows"]) > 4096:
        return global_blocker
    if not value["rows"]:
        # Both a recognized attempt with no positive bounded subject and no
        # recognized attempt are deliberately neutral. Neither proves absence.
        return set()
    if value["attempted"] is not True:
        return global_blocker

    subjects: set[tuple[str, str, str]] = set()
    folded_hosts: set[str] = set()
    for row in value["rows"]:
        if not isinstance(row, dict) or set(row) != {"switch", "platform", "protocols"}:
            return global_blocker
        host = row.get("switch")
        platform = row.get("platform")
        protocols = row.get("protocols")
        if (not _ipv6_routing_scope_text(host, 128, required=True)
                or host == _IPV6_ROUTING_SCOPE_ABSTENTION_HOST
                or not _ipv6_routing_scope_text(platform, 80, required=False)
                or not isinstance(protocols, list) or not protocols):
            return global_blocker
        canonical = [protocol for protocol in _IPV6_ROUTING_PROTOCOLS if protocol in protocols]
        if protocols != canonical:
            return global_blocker
        folded = host.casefold()
        if folded in folded_hosts:
            return global_blocker
        folded_hosts.add(folded)
        subjects.update((host, platform, protocol) for protocol in protocols)
    return subjects


def _static_ipv6_routing_rows(subjects: Any, reason: str = "") -> List[dict]:
    """Build fixed, leaf-free NOT VERIFIED rows from validated scope only."""
    del reason  # reasons are intentionally not reflected into decision rows
    rows: List[dict] = []
    for host, platform, protocol in sorted(
            subjects or set(),
            key=lambda item: (
                item[0].casefold(), item[0],
                _IPV6_ROUTING_PROTOCOL_ORDER.get(item[2], len(_IPV6_ROUTING_PROTOCOLS)),
            )):
        global_blocker = host == _IPV6_ROUTING_SCOPE_ABSTENTION_HOST
        if protocol == "OSPFv3":
            command = (
                "show ipv6 ospfv3 neighbors"
                if platform.casefold() in {"nxos", "nx-os", "nexus", "n9k"}
                else "show ospfv3 neighbor"
            )
        elif protocol == "BGPv6":
            command = "show bgp ipv6 unicast summary"
        else:
            protocol = "IPv6 Routing"
            command = "show ipv6 route summary"
        rows.append({
            "switch": host,
            "platform": platform,
            "protocol": protocol,
            "routing_instance": "default",
            "process": "",
            "peer": "",
            "peer_key": "",
            "interface": "",
            "remote_as": "",
            "role": "",
            "state_raw": "",
            "state": "NOT_VERIFIED",
            "prefix_count": 0,
            "prefix_count_present": False,
            "status": "not_verified",
            "command": command,
            "acceptance": (
                "IPV6 ROUTING BASELINE NOT VERIFIED — BLOCKER: No validated, source-bound "
                "current-run IPv6 routing adjacency baseline authorizes a positive acceptance "
                "target. Re-collect the scoped OSPFv3 and IPv6-unicast BGP evidence before cutover."
            ),
            "source_key": (
                "ipv6_routing_subject_scope.valid/attempted/reason + "
                "ipv6_routing_adjacency_baseline"
                if global_blocker else
                f"ipv6_routing_subject_scope[{host},{protocol}] + "
                "ipv6_routing_adjacency_baseline"
            ),
            "projection_custody": "embedded_unverified",
            "findings": [],
        })
    return rows


def _ipv6_routing_consumer_view(
        value: Any, ipv6_routing_subject_scope: Any = None) -> dict:
    """Resolve source-bound owner rows or strict subject-scope abstentions."""
    view = validate_ipv6_routing_adjacency_baseline(value, require_current_run=True)
    authorized = view.get("valid") is True and view.get("source_bound") is True
    if not authorized:
        subjects = _ipv6_routing_scope_subjects(ipv6_routing_subject_scope)
        reason = ""
        if subjects == {
                (_IPV6_ROUTING_SCOPE_ABSTENTION_HOST, "", "IPv6 Routing")}:
            raw_reason = (
                ipv6_routing_subject_scope.get("reason")
                if isinstance(ipv6_routing_subject_scope, dict) else ""
            )
            reason = raw_reason if raw_reason in _IPV6_ROUTING_SCOPE_REASONS else ""
        return {
            "valid": False,
            "rows": _static_ipv6_routing_rows(subjects, reason),
        }

    baseline = view.get("baseline") if isinstance(view.get("baseline"), dict) else {}
    rows = [dict(row) for row in (view.get("rows") or []) if isinstance(row, dict)]
    attributed = {
        (_strict_protocol_text(row.get("switch")), _strict_protocol_text(row.get("protocol")))
        for row in rows
    }
    fallback_subjects = {
        (
            _strict_protocol_text(cell.get("switch")),
            _strict_protocol_text(cell.get("platform")),
            _strict_protocol_text(cell.get("protocol")),
        )
        for cell in (baseline.get("coverage") or [])
        if isinstance(cell, dict) and cell.get("subject") is True
        and _strict_protocol_text(cell.get("protocol")) in _IPV6_ROUTING_PROTOCOLS
        and _strict_protocol_text(cell.get("status")) in {"review", "not_verified"}
        and (_strict_protocol_text(cell.get("switch")),
             _strict_protocol_text(cell.get("protocol"))) not in attributed
    }
    if fallback_subjects:
        rows.extend(_static_ipv6_routing_rows(fallback_subjects))
    return {"valid": True, "rows": rows}

def compute_migration_readiness(all_interfaces, move_groups, health_scores,
                                physical_health, l3_forwarding, cross_layer,
                                protocol_health, dep_map,
                                config: ScoringConfig = SCORING,
                                bgp_configured_peer_baseline: Optional[dict] = None,
                                fhrp_configured_group_baseline: Optional[dict] = None,
                                protocol_assessability: Any = _PROTOCOL_ASSESSABILITY_UNSET,
                                stp_roots: Any = _PROTOCOL_ASSESSABILITY_UNSET,
                                fhrp_redundancy_domain_baseline: Optional[dict] = None,
                                vtp_safety_baseline: Optional[dict] = None,
                                vtp_safety_subject_scope: Any = None,
                                ipv6_routing_adjacency_baseline: Optional[dict] = None,
                                ipv6_routing_subject_scope: Any = None) -> List[dict]:
    """Per move-group READY/CAUTION/NOT READY from a pre-migration checklist.
    Each check carries a runbook `phase` (Inventory / Baseline capture /
    Dependency mapping / Pilot/cutover / Rollback) so the list is auditable
    against an external standard. The status each risk-bearing check emits comes
    from `config.readiness`; the default instance reproduces the prior verdicts.
    Three audit checks (dependency-mapping / baseline-capture / rollback) are
    additive and designed not to flip any group's verdict on offline data."""
    R = config.readiness
    # per-host indexes
    sf_hosts = {h for (h, _p) in dep_map["single_fiber"]}
    errdis_hosts = {h for (h, _p) in dep_map["errdis"]}
    halfdup_hosts = {h for (h, _p) in dep_map["halfdup_up"]}
    sole_gw_hosts = set(dep_map["sole_gw"].values())
    band_by_host = {r["switch"]: r["band"] for r in health_scores}
    proto_high: Dict = {}                            # host -> set(protocols at High)
    fhrp_health_severity: Dict[str, str] = {}         # host -> worst observed Medium/High FHRP row
    routing_collected: set = set()                   # hosts with ANY OSPF/BGP row = routing was collected+parsed
    ospf_collected: set = set()                      # BGP has a configured-peer owner when supplied
    # Same coverage idiom for the two checks below (#12). compute_protocol_health emits an STP row
    # for EVERY host whose `show spanning-tree` returned usable output, so an STP row is an exact
    # "spanning tree was observed here" witness; and it emits an EtherChannel row for every host
    # whose bundle-member states parsed. Neither command is in _ESSENTIAL_CMD_VARIANTS, so a host
    # can score data_quality 1.0 with zero STP/port-channel evidence.
    stp_collected: set = set()
    ec_collected: set = set()
    # Keep the legacy indexes total for direct callers and hostile/foreign snapshots.  The original
    # value is still passed untouched to the strict STP owner below, where a malformed root/row cannot
    # become healthy and yields an attributable review blocker when a positive subject exists.
    protocol_health_rows = protocol_health if isinstance(protocol_health, list) else []
    for rec in protocol_health_rows:
        if not isinstance(rec, dict):
            continue
        rec_host = _strict_protocol_text(rec.get("switch"))
        rec_protocol = _strict_protocol_text(rec.get("protocol"))
        if rec.get("severity") == "High" and rec_host and rec_protocol:
            proto_high.setdefault(rec_host, set()).add(rec_protocol)
        if rec_protocol == "FHRP" and rec_host and rec.get("severity") in ("Medium", "High"):
            if rec.get("severity") == "High" or rec_host not in fhrp_health_severity:
                fhrp_health_severity[rec_host] = rec.get("severity")
        if rec_protocol in ("OSPF", "BGP") and rec_host:
            routing_collected.add(rec_host)
        if rec_protocol == "OSPF" and rec_host:
            ospf_collected.add(rec_host)
        if rec_protocol == "STP" and rec_host:
            stp_collected.add(rec_host)
        if rec_protocol == "EtherChannel" and rec_host:
            ec_collected.add(rec_host)
    # Hosts whose interface data evidences port-channel MEMBERSHIP (from the trunk table /
    # running-config, not only from the bundle summary). Without this, "no EtherChannel row" would
    # conflate "never collected" with the legitimate "this box bundles nothing" and the check below
    # would cry wolf on every non-bundling switch.
    pc_hosts = {h for h, ifs in (all_interfaces or {}).items()
                if any(str(getattr(d, "port_channel", "") or "").strip()
                       for d in (ifs or {}).values())}
    fhrp_elections = summarize_fhrp_elections(all_interfaces)
    xl_crit_hosts = {h for f in (cross_layer or []) if f.get("severity") == "Critical" for h in f.get("hosts", [])}
    # orphan VLAN -> its access switches
    orphan_hosts = set()
    for vid in dep_map["orphan"]:
        orphan_hosts |= dep_map["access_by_vlan"].get(vid, set())
    # audit-evidence indexes for the additive runbook checks
    model = dep_map.get("model") or {}
    topo_hosts = set(model.get("hosts", []) if isinstance(model, dict) else [])
    baseline_hosts = {rec.get("switch") for rec in (physical_health or [])}

    # Current pipeline callers supply the source-bound configured-peer baseline.
    # ``None`` is the deliberate compatibility boundary for older direct callers:
    # only that path retains the historical observed-only BGP readiness behaviour.
    bgp_contract_supplied = bgp_configured_peer_baseline is not None
    bgp_contract_view: dict = {}
    bgp_contract: dict = {}
    bgp_rows_by_host: Dict[str, List[dict]] = {}
    bgp_subject_coverage_hosts: set[str] = set()
    bgp_coverage_status_by_host: Dict[str, str] = {}
    if bgp_contract_supplied:
        bgp_contract_view = validate_bgp_configured_peer_baseline(
            bgp_configured_peer_baseline, require_current_run=True)
        if bgp_contract_view.get("valid") is True and bgp_contract_view.get("source_bound") is True:
            bgp_contract = bgp_contract_view.get("baseline") or {}
            for row in bgp_contract_view.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                host = _strict_protocol_text(row.get("switch"))
                if host:
                    bgp_rows_by_host.setdefault(host, []).append(row)
            for row in bgp_contract.get("coverage") or []:
                if not isinstance(row, dict) or row.get("subject") is not True:
                    continue
                host = _strict_protocol_text(row.get("switch"))
                if host:
                    bgp_subject_coverage_hosts.add(host)
                    bgp_coverage_status_by_host[host] = _strict_protocol_text(
                        row.get("status")).lower()

    # The configured-group denominator is authoritative only while its process-local current-run
    # marker is present. ``None`` deliberately retains the historical observed-election path for
    # direct callers; an explicitly supplied failed/serialized artifact is an abstention, not
    # feature absence and never a positive FHRP assertion.
    fhrp_contract_supplied = fhrp_configured_group_baseline is not None
    fhrp_contract_view: dict = {}
    fhrp_contract: dict = {}
    fhrp_rows_by_host: Dict[str, List[dict]] = {}
    fhrp_blocking_coverage_by_host: Dict[str, set[str]] = {}
    if fhrp_contract_supplied:
        fhrp_contract_view = validate_fhrp_configured_group_baseline(
            fhrp_configured_group_baseline, require_current_run=True)
        if (fhrp_contract_view.get("valid") is True
                and fhrp_contract_view.get("source_bound") is True):
            fhrp_contract = fhrp_contract_view.get("baseline") or {}
            for row in fhrp_contract_view.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                host = _strict_protocol_text(row.get("switch"))
                if host:
                    fhrp_rows_by_host.setdefault(host, []).append(row)
            for row in fhrp_contract.get("coverage") or []:
                if not isinstance(row, dict):
                    continue
                host = _strict_protocol_text(row.get("switch"))
                status = _strict_protocol_text(row.get("status")).lower()
                # Coverage failures are attributable even before the parser can prove a group
                # subject.  Incomplete/missing configuration is exactly why subject=False may be
                # all the producer can assert.  Complete no-subject cells are ``not_applicable``
                # and deliberately remain neutral.
                if host and status in {"degraded", "review", "not_verified"}:
                    fhrp_blocking_coverage_by_host.setdefault(host, set()).add(status)

    # Keep the broader observed-election owner additive when the configured contract is present,
    # but remove only exact local blocker duplicates.  The configured owner can reconcile an exact
    # candidate set; it does not replace mixed protocol/group/VIP or wider L3-domain review.
    fhrp_uncovered_by_election: Dict[int, List[dict]] = {}
    if fhrp_contract_supplied:
        configured_rows = [
            row for rows in fhrp_rows_by_host.values() for row in rows
            if isinstance(row, dict)
        ]
        for election, member in _uncovered_fhrp_election_blockers(
                fhrp_elections, configured_rows):
            fhrp_uncovered_by_election.setdefault(id(election), []).append(member)

    # Exact cross-switch domain composition is an additive owner.  Omission retains the historical
    # readiness path; an explicitly supplied invalid/embedded/phase-failed receipt is scoped only from
    # current interfaces plus the configured-group source and becomes static NOT VERIFIED evidence.
    fhrp_domain_supplied = fhrp_redundancy_domain_baseline is not None
    fhrp_domain_rows_by_host: Dict[str, List[dict]] = {}
    if fhrp_domain_supplied:
        fhrp_domain_view = _fhrp_redundancy_domain_consumer_view(
            fhrp_redundancy_domain_baseline,
            all_interfaces,
            fhrp_configured_group_baseline,
        )
        for row in fhrp_domain_view["rows"]:
            if not isinstance(row, dict):
                continue
            host = row.get("switch") if isinstance(row.get("switch"), str) else ""
            if host:
                fhrp_domain_rows_by_host.setdefault(host, []).append(row)

    # Current callers opt into the shared claim-specific STP owner.  Omission alone retains the
    # historical sparse protocol-health behavior for backward compatibility; an explicitly supplied
    # missing/malformed receipt is evidence failure, not an instruction to fall back to prose.
    stp_contract_supplied = (
        protocol_assessability is not _PROTOCOL_ASSESSABILITY_UNSET
        or stp_roots is not _PROTOCOL_ASSESSABILITY_UNSET
    )
    stp_consistency_by_host: Dict[str, dict] = {}
    if stp_contract_supplied:
        stp_consistency = summarize_stp_consistency_baseline(
            protocol_health,
            None if protocol_assessability is _PROTOCOL_ASSESSABILITY_UNSET
            else protocol_assessability,
            all_interfaces=all_interfaces,
            stp_roots=None if stp_roots is _PROTOCOL_ASSESSABILITY_UNSET else stp_roots,
        )
        stp_consistency_by_host = {
            row["switch"]: row for row in stp_consistency["rows"]
            if isinstance(row, dict) and _strict_protocol_text(row.get("switch"))
        }

    # VTP cutover safety is a separate bounded claim from sparse protocol health/intelligence.
    # Omission preserves direct-caller compatibility.  A supplied but unbound/failed receipt uses
    # only independently evidenced VTP subjects and static NOT VERIFIED copy.
    vtp_contract_supplied = vtp_safety_baseline is not None
    vtp_rows_by_host: Dict[str, List[dict]] = {}
    vtp_global_rows: List[dict] = []
    if vtp_contract_supplied:
        vtp_view = _vtp_safety_consumer_view(
            vtp_safety_baseline,
            protocol_health,
            None if protocol_assessability is _PROTOCOL_ASSESSABILITY_UNSET
            else protocol_assessability,
            vtp_safety_subject_scope,
        )
        for row in vtp_view["rows"]:
            if not isinstance(row, dict):
                continue
            host = _strict_protocol_text(row.get("switch"))
            if host:
                vtp_rows_by_host.setdefault(host, []).append(row)
                if host == _VTP_SCOPE_ABSTENTION_HOST:
                    vtp_global_rows.append(row)

    # IPv6 routing adjacency truth is independent from the legacy OSPFv2/BGPv4/EIGRP
    # projection. Omission preserves direct-caller compatibility; a supplied but
    # unauthorized receipt can contribute only strict scope-owned static blockers.
    ipv6_routing_contract_supplied = ipv6_routing_adjacency_baseline is not None
    ipv6_routing_rows_by_host: Dict[str, List[dict]] = {}
    ipv6_routing_global_rows: List[dict] = []
    if ipv6_routing_contract_supplied:
        ipv6_view = _ipv6_routing_consumer_view(
            ipv6_routing_adjacency_baseline, ipv6_routing_subject_scope)
        for row in ipv6_view["rows"]:
            if not isinstance(row, dict):
                continue
            host = _strict_protocol_text(row.get("switch"))
            if host:
                ipv6_routing_rows_by_host.setdefault(host, []).append(row)
                if host == _IPV6_ROUTING_SCOPE_ABSTENTION_HOST:
                    ipv6_routing_global_rows.append(row)

    out: List[dict] = []
    for gi, g in enumerate(move_groups, 1):
        gset = set(g["switches"])

        def any_in(s):
            return sorted(gset & s)

        checks = []
        # 1 redundant uplinks
        hit = any_in(sf_hosts)
        checks.append(("Redundant uplinks", R["redundant_uplinks"] if hit else "pass",
                       f"single-fiber uplink on {', '.join(hit)}" if hit else "no single-homed switch"))
        # 2 gateway redundancy (FHRP).  The sole-gateway topology signal and the observed election
        # state answer different questions, so preserve both.  In particular, protocol_health rates
        # Init/Learn Medium and the election summary catches cross-device split-brain/group/VIP/no-leader
        # evidence that no per-device health row can see.  A single observed Standby/Backup remains
        # allowed: without a second member in scope it is not evidence that the election lacks a leader.
        sole = any_in(sole_gw_hosts)
        health_hosts = sorted(gset & set(fhrp_health_severity))
        high_health = [host for host in health_hosts if fhrp_health_severity[host] == "High"]
        if fhrp_contract_supplied:
            fhrp_gate_rows = []
            for row in fhrp_elections:
                uncovered_members = fhrp_uncovered_by_election.get(id(row), [])
                relevant_members = [
                    member for member in uncovered_members if member.get("host") in gset
                ]
                if not relevant_members:
                    continue
                issues = list(dict.fromkeys(
                    issue
                    for member in relevant_members
                    for issue in (member.get("issues") or [])
                    if isinstance(issue, str) and issue.strip()
                ))
                fhrp_gate_rows.append({
                    "vlan": row.get("vlan"),
                    "status": (
                        "degraded"
                        if any(member.get("status") == "degraded"
                               for member in relevant_members)
                        else "review"
                    ),
                    "issues": issues or list(row.get("issues") or []),
                    "members": relevant_members,
                })
        else:
            fhrp_gate_rows = [
                row for row in fhrp_elections
                if row["status"] in ("review", "degraded")
                and gset & {member["host"] for member in row["members"]}
            ]
        gateway_statuses: List[str] = []
        gateway_notes: List[str] = []
        if sole:
            gateway_statuses.append(R["gateway_redundancy"])
            gateway_notes.append(f"sole gateway on {', '.join(sole)} (no FHRP)")
        if health_hosts:
            gateway_statuses.append("fail" if high_health else "warn")
            gateway_notes.append(
                "observed degraded FHRP health on "
                + ", ".join(
                    f"{host} ({fhrp_health_severity[host]})" for host in health_hosts
                )
            )
        if fhrp_gate_rows:
            gateway_statuses.append("warn")
            gateway_notes.extend(
                f"VLAN {row['vlan']} ({row['status'].upper()}): {'; '.join(row['issues'])}"
                for row in fhrp_gate_rows
            )
        if fhrp_contract_supplied:
            group_fhrp_rows = [
                row for host in sorted(gset) for row in fhrp_rows_by_host.get(host, [])
            ]
            degraded_groups = [row for row in group_fhrp_rows
                               if row.get("status") == "degraded"]
            indeterminate_groups = [row for row in group_fhrp_rows
                                    if row.get("status") in {"review", "not_verified"}]
            assessed_groups = [row for row in group_fhrp_rows
                               if row.get("status") == "assessed"]
            disabled_groups = [row for row in group_fhrp_rows
                               if row.get("status") == "administratively_disabled"]
            contract_valid = (
                fhrp_contract_view.get("valid") is True
                and fhrp_contract_view.get("source_bound") is True
            )
            contract_verdict = _strict_protocol_text(fhrp_contract.get("verdict")).upper()
            all_contract_blockers = [
                row for rows in fhrp_rows_by_host.values() for row in rows
                if row.get("status") in {"degraded", "review", "not_verified"}
            ]
            group_coverage_states = {
                state for host in gset
                for state in fhrp_blocking_coverage_by_host.get(host, set())
            }

            if degraded_groups:
                gateway_statuses.append("fail")
                gateway_notes.append(
                    "configured FHRP group blocker(s): "
                    + ", ".join(
                        f"{row.get('switch')} {row.get('protocol')} "
                        f"{row.get('interface')} group {row.get('group')}"
                        for row in degraded_groups
                    )
                )
            elif indeterminate_groups:
                gateway_statuses.append("warn")
                gateway_notes.append(
                    "configured FHRP group subject is INDETERMINATE: "
                    + ", ".join(
                        f"{row.get('switch')} {row.get('protocol')} "
                        f"{row.get('interface')} group {row.get('group')} "
                        f"({row.get('status')})"
                        for row in indeterminate_groups
                    )
                    + "; re-collect running-config and the matching protocol summary"
                )
            elif not contract_valid:
                gateway_statuses.append("warn")
                gateway_notes.append(
                    "configured FHRP group baseline is not a validated current-run artifact — "
                    "gateway redundancy is not assessable"
                )
            elif (contract_verdict == "BLOCKED" and not all_contract_blockers
                  and group_coverage_states):
                gateway_statuses.append("fail")
                gateway_notes.append(
                    "configured FHRP group baseline is BLOCKED but exposes no attributable "
                    "group row; re-run the bounded local group/VIP/state assessment"
                )
            elif (contract_verdict == "INDETERMINATE"
                  and group_coverage_states & {"degraded", "review", "not_verified"}):
                gateway_statuses.append("warn")
                gateway_notes.append(
                    "configured FHRP group subject is INDETERMINATE — re-collect running-config "
                    "and the matching protocol summary"
                )
            elif assessed_groups:
                gateway_statuses.append("pass")
                gateway_notes.append(
                    f"{len(assessed_groups)} configured FHRP group(s) assessed in the bounded "
                    "default IPv4 direct-literal local group/VIP/state scope; no peer or election "
                    "health was inferred"
                )
            elif disabled_groups or contract_verdict == "NOT_APPLICABLE":
                gateway_statuses.append("info")
                gateway_notes.append(
                    "FHRP is neutral in the bounded configured local-group scope "
                    "(not applicable or administratively disabled); this is not FHRP health"
                )
            else:
                gateway_statuses.append("info")
                gateway_notes.append(
                    "no active bounded configured FHRP group subject for this group; "
                    "no gateway-redundancy health claim is made"
                )
        if fhrp_domain_supplied:
            domain_rows = [
                row for host in sorted(gset)
                for row in fhrp_domain_rows_by_host.get(host, [])
            ]
            degraded_domains = [row for row in domain_rows if row.get("status") == "degraded"]
            uncertain_domains = [
                row for row in domain_rows if row.get("status") in {"review", "not_verified"}
            ]
            assessed_domains = [row for row in domain_rows if row.get("status") == "assessed"]
            if degraded_domains:
                gateway_statuses.append("fail")
                gateway_notes.append(
                    "FHRP redundancy-domain blocker(s): "
                    + "; ".join(str(row.get("why") or row.get("check") or "")
                                for row in degraded_domains)
                )
            elif uncertain_domains:
                gateway_statuses.append("warn")
                gateway_notes.append(
                    "FHRP redundancy-domain composition is INDETERMINATE: "
                    + "; ".join(str(row.get("why") or row.get("check") or "")
                                for row in uncertain_domains)
                )
            elif assessed_domains:
                gateway_statuses.append("pass")
                gateway_notes.append(
                    f"{len(assessed_domains)} FHRP redundancy-domain member row(s) boundedly "
                    "assessed from the current-run exact domain/candidate projection"
                )
        if gateway_statuses:
            status_rank = {"pass": 0, "info": 0, "warn": 1, "fail": 2}
            status = max(gateway_statuses, key=lambda value: status_rank.get(value, 1))
            note = "; ".join(dict.fromkeys(gateway_notes))
        else:
            status = "pass"
            note = "no sole gateway or degraded observed FHRP election evidence"
        checks.append(("Gateway redundancy", status, note))
        # 3 no cross-layer Critical
        hit = any_in(xl_crit_hosts)
        checks.append(("No cross-layer Critical", R["no_xl_critical"] if hit else "pass",
                       f"Critical correlation on {', '.join(hit)}" if hit else "none"))
        # 4 no err-disabled ports
        hit = any_in(errdis_hosts)
        checks.append(("No err-disabled ports", R["no_errdisabled"] if hit else "pass",
                       f"err-disabled on {', '.join(hit)}" if hit else "none"))
        # 5 STP consistency -- coverage-honest, same shape as check 7 below and as the Baseline-capture
        # check (`gset - baseline_hosts if baseline_hosts`). `no inconsistent ports` is an AFFIRMATIVE
        # claim about spanning tree; it may only be made about switches whose spanning tree was actually
        # observed. A group whose switches produced no STP row had `show spanning-tree` never collected
        # (or erroring), so the check is NOT assessable there -> 'warn', never a silent 'pass' that reads
        # identical to a verified-consistent group. The `if stp_collected` guard keeps a run that
        # collected STP NOWHERE from crying wolf on every group (mirrors checks 7/12).  (#12)
        if stp_contract_supplied:
            group_stp_rows = [stp_consistency_by_host[host] for host in sorted(gset)
                              if host in stp_consistency_by_host]
            degraded_stp = [row for row in group_stp_rows if row.get("status") == "degraded"]
            uncertain_stp = [row for row in group_stp_rows
                             if row.get("status") in {"review", "not_verified"}]
            if degraded_stp or uncertain_stp:
                statuses = ([R["stp_consistency"]] if degraded_stp else [])
                statuses += (["warn"] if uncertain_stp else [])
                status_rank = {"pass": 0, "info": 0, "warn": 1, "fail": 2}
                status = max(statuses, key=lambda value: status_rank.get(value, 1))
                notes = []
                if degraded_stp:
                    notes.append(
                        "bounded current-run STP inconsistency on "
                        + ", ".join(row["switch"] for row in degraded_stp)
                    )
                if uncertain_stp:
                    notes.append(
                        "STP consistency baseline not verified on "
                        + ", ".join(f"{row['switch']} ({row['status']})" for row in uncertain_stp)
                        + "; re-collect show spanning-tree and show spanning-tree inconsistentports"
                    )
                checks.append(("STP consistency", status, "; ".join(notes)))
            elif group_stp_rows:
                checks.append((
                    "STP consistency", "pass",
                    "bounded current-run state and inconsistent-port evidence assessed on "
                    + ", ".join(row["switch"] for row in group_stp_rows)
                    + "; blocked-port and topology-change evidence are disclosed separately",
                ))
            else:
                checks.append((
                    "STP consistency", "info",
                    "no positive STP/L2 subject for this group; no STP consistency health claim is made",
                ))
        else:
            hit = sorted({h for h in gset if "STP" in proto_high.get(h, set())})
            missing_stp = sorted(gset - stp_collected) if stp_collected else []
            if hit:
                checks.append(("STP consistency", R["stp_consistency"],
                               f"inconsistent STP on {', '.join(hit)}"))
            elif missing_stp:
                checks.append(("STP consistency", "warn",
                               f"no spanning-tree evidence for {', '.join(missing_stp)} — "
                               "STP consistency not assessable"))
            elif not stp_collected:
                # Nothing to compare anywhere in the run. #12 disclosed this honestly in the NOTE but
                # left the status 'pass', and excel.py:3589 paints the Status cell green from
                # _STATUS_FILL — so the Migration Readiness sheet showed a green PASS for an axis that
                # was never observed, with the caveat one column to the right. A colour is a claim
                # (the same rule this review applied to the Capacity sheet's amber fills), and the
                # Status column is precisely what a reader scans. 'info' keeps #12's no-cry-wolf
                # property intact — the verdict inspects only fail/warn — while withdrawing the health
                # claim. Now identical to its two siblings (checks 11 and 12) rather than a third
                # spelling of the same situation.
                checks.append(("STP consistency", "info",
                               "NOT ASSESSABLE — spanning tree was not collected anywhere in this run, "
                               "so consistency could not be compared. This is an ABSENCE of evidence, "
                               "not a clean spanning tree."))
            else:
                checks.append(("STP consistency", "pass", "no inconsistent ports"))

        # VTP safety is a pre-cutover review claim, not a health score.  A high observed server
        # revision is one bounded heuristic; other owned findings (for example an explicit empty
        # active-mode domain) also withhold an all-clear without being called a present outage.
        if vtp_contract_supplied:
            group_vtp_rows = [
                row for host in sorted(gset) for row in vtp_rows_by_host.get(host, [])
            ] + vtp_global_rows
            vtp_review = [row for row in group_vtp_rows if row.get("status") == "review"]
            vtp_not_verified = [
                row for row in group_vtp_rows if row.get("status") == "not_verified"
            ]
            if vtp_review or vtp_not_verified:
                notes = []
                if vtp_review:
                    notes.append(
                        "VTP safety REVIEW on "
                        + ", ".join(
                            f"{row.get('switch')} ({row.get('mode') or 'unknown'}"
                            + (f", revision {row.get('revision')}"
                               if row.get("revision_present") is True else "")
                            + ")"
                            for row in vtp_review
                        )
                        + "; resolve or explicitly disposition the local VTP safety finding before the window"
                    )
                if vtp_not_verified:
                    notes.append(
                        "VTP safety baseline NOT VERIFIED on "
                        + ", ".join(str(row.get("switch") or "") for row in vtp_not_verified)
                        + "; re-collect show vtp status before acceptance"
                    )
                checks.append(("VTP cutover safety", "warn", "; ".join(notes)))
            elif group_vtp_rows:
                checks.append((
                    "VTP cutover safety",
                    "pass",
                    "bounded current-run local VTP mode/domain/revision observation assessed on "
                    + ", ".join(str(row.get("switch") or "") for row in group_vtp_rows)
                    + "; this does not prove database authority, synchronization, authentication, "
                      "pruning, propagation, or overwrite safety",
                ))

        if ipv6_routing_contract_supplied:
            group_ipv6_rows = [
                row
                for host in sorted(gset)
                for row in ipv6_routing_rows_by_host.get(host, [])
            ] + ipv6_routing_global_rows
            ipv6_degraded = [
                row for row in group_ipv6_rows if row.get("status") == "degraded"
            ]
            ipv6_indeterminate = [
                row for row in group_ipv6_rows
                if row.get("status") in {"review", "not_verified"}
            ]

            def ipv6_subject(row: dict) -> str:
                protocol = _strict_protocol_text(row.get("protocol")) or "IPv6 routing"
                peer = _strict_protocol_text(row.get("peer"))
                state = _strict_protocol_text(row.get("state_raw")) or _strict_protocol_text(
                    row.get("state"))
                detail = f"{protocol} {peer or 'subject'}"
                return detail + (f" ({state})" if state else "")

            def ipv6_subject_summary(rows: List[dict]) -> str:
                # Readiness is a fleet-level synopsis, while Validation/NRFU retain every
                # individual blocker.  Bound this note so a valid high-cardinality receipt
                # cannot overrun an Excel cell or turn a decision banner into a multi-megabyte
                # string; disclose the exact omitted count and its authoritative sink.
                subjects = [ipv6_subject(row) for row in rows]
                shown = ", ".join(subjects[:8])
                if len(subjects) > 8:
                    shown += (
                        f"; +{len(subjects) - 8} additional blocker row(s) retained in "
                        "Cutover Validation and NRFU"
                    )
                return shown

            if ipv6_degraded:
                checks.append((
                    "IPv6 routing adjacencies",
                    R["routing_adjacencies"],
                    "degraded observed IPv6 adjacency: "
                    + ipv6_subject_summary(ipv6_degraded)
                    + (
                        f"; additionally, {len(ipv6_indeterminate)} REVIEW/NOT VERIFIED "
                        "blocker row(s) are retained in Cutover Validation and NRFU"
                        if ipv6_indeterminate else ""
                    )
                    + "; matching a degraded state after cutover is NOT ACCEPTANCE",
                ))
            elif ipv6_indeterminate:
                checks.append((
                    "IPv6 routing adjacencies",
                    "warn",
                    "IPv6 routing adjacency baseline requires review or is NOT VERIFIED: "
                    + ipv6_subject_summary(ipv6_indeterminate)
                    + "; re-collect the scoped OSPFv3/IPv6-unicast BGP evidence before acceptance",
                ))
            elif group_ipv6_rows:
                checks.append((
                    "IPv6 routing adjacencies",
                    "pass",
                    f"{len(group_ipv6_rows)} bounded observed OSPFv3/IPv6-unicast BGP "
                    "adjacency row(s) assessed; no expected-peer denominator, route-policy, "
                    "route-propagation, convergence, or freshness claim is made",
                ))
        # 6 port-channels healthy -- same treatment, but the coverage set has to be joined against
        # interface-evidenced port-channel MEMBERSHIP: a missing EtherChannel row means "bundle state
        # never observed" only for a switch that has members, and means "nothing to assess" for one
        # that bundles nothing. Claiming "all members bundled" for a switch with members whose bundle
        # summary was never captured is the same false-health as check 5.  (#12)
        hit = sorted({h for h in gset if "EtherChannel" in proto_high.get(h, set())})
        missing_ec = sorted((gset & pc_hosts) - ec_collected)
        if hit:
            checks.append(("Port-channels healthy", R["portchannels_healthy"],
                           f"unbundled member on {', '.join(hit)}"))
        elif missing_ec:
            checks.append(("Port-channels healthy", "warn",
                           f"port-channel members on {', '.join(missing_ec)} with no bundle-summary "
                           "evidence — member state not assessable"))
        else:
            checks.append(("Port-channels healthy", "pass",
                           "all members bundled" if gset & ec_collected
                           else "all members bundled / no port-channel members observed"))
        # 7 routing adjacencies up -- coverage-honest: this is a hard FAIL gate, but it can only fire when an
        # OSPF/BGP row was COLLECTED. With no routing evidence for ANY switch in the group the adjacency status is
        # NOT assessable -> 'warn', never a silent 'pass' that reads identical to a verified-up group (the bare
        # 'show logging'-on-NX-OS false-health class at the cutover gate; audit-4 #7).
        if not bgp_contract_supplied:
            # Backward-compatible observed-only behaviour for callers predating the configured-peer owner.
            hit = sorted({h for h in gset if proto_high.get(h, set()) & {"OSPF", "BGP"}})
            if hit:
                checks.append(("Routing adjacencies up", R["routing_adjacencies"],
                               f"down OSPF/BGP neighbor on {', '.join(hit)}"))
            elif gset & routing_collected:
                checks.append(("Routing adjacencies up", "pass", "all neighbors up"))
            elif routing_collected:
                checks.append(("Routing adjacencies up", "warn",
                               "routing not collected for this group — adjacency status not assessable"))
            else:
                checks.append(("Routing adjacencies up", "pass", "all neighbors up / none"))
        else:
            ospf_hit = sorted({h for h in gset if "OSPF" in proto_high.get(h, set())})
            group_bgp_rows = [
                row for host in sorted(gset) for row in bgp_rows_by_host.get(host, [])
            ]
            bgp_degraded = [
                row for row in group_bgp_rows
                if row.get("status") == "degraded"
            ]
            bgp_indeterminate = [
                row for row in group_bgp_rows
                if row.get("status") in {"review", "not_verified"}
            ]
            bgp_assessed = [row for row in group_bgp_rows if row.get("status") == "assessed"]
            bgp_disabled = [
                row for row in group_bgp_rows
                if row.get("status") == "administratively_disabled"
            ]
            contract_valid = (
                bgp_contract_view.get("valid") is True
                and bgp_contract_view.get("source_bound") is True
            )
            contract_verdict = _strict_protocol_text(bgp_contract.get("verdict")).upper()
            all_bgp_blockers = [
                row for rows in bgp_rows_by_host.values() for row in rows
                if row.get("status") in {"degraded", "review", "not_verified"}
            ]

            if ospf_hit or bgp_degraded:
                details: List[str] = []
                if ospf_hit:
                    details.append(f"down OSPF neighbor on {', '.join(ospf_hit)}")
                if bgp_degraded:
                    details.append(
                        "configured BGP default/global IPv4 peer blocker(s): "
                        + ", ".join(
                            f"{row.get('switch')} {row.get('peer')} ({row.get('status')})"
                            for row in bgp_degraded
                        )
                    )
                checks.append(("Routing adjacencies up", R["routing_adjacencies"], "; ".join(details)))
            elif bgp_indeterminate:
                checks.append((
                    "Routing adjacencies up", "warn",
                    "configured BGP default/global IPv4 peer subject is INDETERMINATE: "
                    + ", ".join(
                        f"{row.get('switch')} {row.get('peer')} ({row.get('status')})"
                        for row in bgp_indeterminate
                    )
                    + "; re-collect running-config and scoped IPv4 summary evidence",
                ))
            elif not contract_valid:
                # An explicitly supplied but failed/tampered phase is not equivalent to feature absence.
                checks.append(("Routing adjacencies up", "warn",
                               "configured BGP default/global IPv4 peer baseline is not a validated "
                               "current-run artifact — routing acceptance is not assessable"))
            elif contract_verdict == "BLOCKED" and not all_bgp_blockers and (
                    gset & bgp_subject_coverage_hosts):
                # Defensive reconciliation: a BLOCKED owner verdict must never collapse to READY even if a
                # malformed future producer omits its blocker row.
                checks.append(("Routing adjacencies up", R["routing_adjacencies"],
                               "configured BGP peer baseline is BLOCKED but exposes no attributable blocker "
                               "row; re-run the bounded default/global IPv4 assessment"))
            elif contract_verdict == "INDETERMINATE" and (
                    any(bgp_coverage_status_by_host.get(host) in {"review", "not_verified"}
                        for host in gset)):
                checks.append(("Routing adjacencies up", "warn",
                               "configured BGP default/global IPv4 peer subject is INDETERMINATE — "
                               "re-collect running-config and scoped IPv4 summary evidence"))
            elif bgp_assessed:
                note = (
                    f"{len(bgp_assessed)} configured literal BGP peer(s) assessed in the bounded "
                    "default/global IPv4-unicast scope"
                )
                if gset & ospf_collected:
                    note += "; observed OSPF neighbors are up"
                checks.append(("Routing adjacencies up", "pass", note))
            elif gset & ospf_collected:
                checks.append(("Routing adjacencies up", "pass", "observed OSPF neighbors are up; "
                               "no active in-scope configured BGP peer was asserted for this group"))
            elif ospf_collected:
                checks.append(("Routing adjacencies up", "warn",
                               "OSPF was collected elsewhere but not for this group; the configured BGP "
                               "baseline is neutral here — routing status is not assessable"))
            elif bgp_disabled or contract_verdict == "NOT_APPLICABLE":
                checks.append(("Routing adjacencies up", "info",
                               "BGP is neutral in the bounded default/global IPv4 literal-peer scope "
                               "(not applicable or administratively disabled); this is not BGP health"))
            else:
                checks.append(("Routing adjacencies up", "info",
                               "no assessed OSPF or active bounded default/global IPv4 BGP subject for this "
                               "group; no routing-health claim is made"))
        # 8 no orphan VLANs
        hit = any_in(orphan_hosts)
        checks.append(("No orphan VLANs", R["no_orphan_vlans"] if hit else "pass",
                       f"endpoints with off-scan gateway on {', '.join(hit)}" if hit else "none"))
        # 9 no degraded / half-duplex uplinks
        hit = any_in(halfdup_hosts)
        checks.append(("Clean uplinks (no half-duplex)", R["clean_uplinks"] if hit else "pass",
                       f"half-duplex uplink on {', '.join(hit)}" if hit else "none"))
        # 10 device health floor -- coverage-honest, the same shape as checks 5/6/7. "all switches Fair
        # or better" is an AFFIRMATIVE claim about EVERY switch in the group, so it may only be made
        # about switches that were actually SCORED. A host banded 'Insufficient Data' is
        # compute_health_scores' collection-gap / unparseable band (absent evidence -> no deductions ->
        # a near-perfect raw score); it is neither Critical nor Poor, so it fell straight through to the
        # 'pass' arm and a move-group made entirely of never-collected switches reached READY off it.
        # A host with no health-score row at all is the same gap by a different route. Not assessable
        # -> 'warn', never a silent pass that reads identical to a verified-Fair-or-better group.
        crit = sorted([h for h in gset if band_by_host.get(h) == "Critical"])
        poor = sorted([h for h in gset if band_by_host.get(h) == "Poor"])
        unscored = sorted([h for h in gset
                           if str(band_by_host.get(h) or "") in ("", "Insufficient Data")])
        if crit:
            st, note = R["health_floor_critical"], f"Critical-health switch: {', '.join(crit)}"
        elif poor:
            st, note = R["health_floor_poor"], f"Poor-health switch: {', '.join(poor)}"
        elif unscored:
            st, note = "warn", (f"no health evidence for {', '.join(unscored)} (Insufficient Data / "
                                "not scored) — device health floor not assessable")
        else:
            st, note = "pass", "all switches Fair or better"
        checks.append(("Device health floor", st, note))

        # ---- runbook audit checks (additive; never flip the verdict) ----
        # No-signal fall-back: when the evidence set is wholly absent we cannot audit it, so these
        # checks do not go to 'warn' — that is the engine's "fall-back-when-no-data never
        # false-negative" convention and it stands.
        #
        # But the fall-back used to emit "pass" WITH AN AFFIRMATIVE NOTE: `gset - topo_hosts` over an
        # EMPTY topo_hosts is empty, so "nothing is missing" became "topology/dependency map covers
        # all group switches". With no topology and no counters collected at all, a group was graded
        # READY / n_warn 0 while asserting coverage of both — the "not observed silently becomes
        # healthy" class CLAUDE.md guardrail 3 forbids, on the verdict a human schedules a cutover
        # from. The Device health floor check ~12 lines above already had the right shape for the
        # same situation ("not assessable"); these two were the siblings it was not applied to.
        #
        # 'info' keeps the no-cry-wolf contract intact (the verdict inspects only fail/warn, see
        # below) while refusing to claim coverage that was never measured. Whether a wholly
        # unassessed axis should ALSO downgrade READY is a separate design decision, deliberately
        # not taken here.
        # 11 dependency mapping complete: the group's switches are in the topology graph
        if not topo_hosts:
            checks.append(("Dependency mapping complete", "info",
                           "NOT ASSESSABLE — no topology/dependency evidence was collected for any "
                           "host, so group coverage could not be checked. This is an ABSENCE of "
                           "evidence, not coverage."))
        else:
            missing_topo = sorted(gset - topo_hosts)
            checks.append(("Dependency mapping complete", "pass" if not missing_topo else "warn",
                           "topology/dependency map covers all group switches" if not missing_topo
                           else f"no topology data for {', '.join(missing_topo)}"))
        # 12 baseline capture: interface/physical counters collected for the group's switches
        if not baseline_hosts:
            checks.append(("Baseline capture", "info",
                           "NOT ASSESSABLE — no interface/physical counters were collected for any "
                           "host, so a pre-change baseline could not be confirmed. This is an "
                           "ABSENCE of evidence, not a captured baseline."))
        else:
            missing_base = sorted(gset - baseline_hosts)
            checks.append(("Baseline capture", "pass" if not missing_base else "warn",
                           "interface/physical counters captured for all group switches" if not missing_base
                           else f"no baseline counters for {', '.join(missing_base)}"))
        # 13 rollback plan documented: no offline signal -> 'info' (never affects the verdict)
        checks.append(("Rollback plan documented", "info",
                       "manual: confirm documented rollback + back-out window"))

        # readiness/counts inspect only fail/warn, so 'info' checks are benign
        statuses = [c[1] for c in checks]
        readiness = "NOT READY" if "fail" in statuses else ("CAUTION" if "warn" in statuses else "READY")
        out.append({"group": f"Group {gi}", "switches": g["switches"],
                    "endpoints": g.get("endpoints", 0), "readiness": readiness,
                    "n_fail": statuses.count("fail"), "n_warn": statuses.count("warn"),
                    "checks": [{"check": c[0], "status": c[1], "note": c[2],
                                "phase": _READINESS_PHASES.get(c[0], "")} for c in checks]})
    return out


# =============================================================================
# NEW-V3.22: Protocol behavior analysis. One row per (switch, protocol) for
# STP / EtherChannel / VTP / OSPF / BGP / EIGRP / FHRP with a derived health
# severity. Re-parses already-collected raw output (+ the new STP-detail TCN).
# The STP/EtherChannel/VTP sub-parsers are analyze-internal (only used here).
# =============================================================================
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

# EtherChannel's producer vocabulary is deliberately closed and case-sensitive.  These are LOCAL
# observations from ``show etherchannel/port-channel summary`` -- never configured-member, partner,
# hashing, bandwidth, persistence, or multi-chassis intent.  P and NX-OS delay-LACP p are forwarding;
# H is a legitimate LACP hot standby.  D/s/I/f/M/m/u/r are definite local non-forwarding faults.
# Waiting (w) and BFD-wait (b), plus the platform-dependent d token, require live persistence/intent
# review rather than an asserted fault.  Group D/M/N are definite local bundle faults.
_EC_COMMANDS = ("show etherchannel summary", "show port-channel summary")
_EC_GROUP_DEGRADED_FLAGS = frozenset("DMN")
_EC_GROUP_CONTEXT_FLAGS = frozenset("SRUA")
_EC_MEMBER_FORWARDING_FLAGS = frozenset(("P", "p"))
_EC_MEMBER_STANDBY_FLAGS = frozenset(("H",))
_EC_MEMBER_DEGRADED_FLAGS = frozenset(("D", "s", "I", "f", "M", "m", "u", "r"))
_EC_MEMBER_REVIEW_FLAGS = frozenset(("w", "b", "d"))
_EC_MEMBER_KNOWN_FLAGS = (
    _EC_MEMBER_FORWARDING_FLAGS | _EC_MEMBER_STANDBY_FLAGS
    | _EC_MEMBER_DEGRADED_FLAGS | _EC_MEMBER_REVIEW_FLAGS
)
# Backward-compatible intelligence joins derive from the same alphabet -- no second classifier.
_EC_BAD_FLAGS = "".join(sorted(_EC_MEMBER_DEGRADED_FLAGS | _EC_MEMBER_REVIEW_FLAGS))
_EC_HARD_FLAGS = "".join(sorted(_EC_MEMBER_DEGRADED_FLAGS))
_EC_ADVISORY_FLAGS = "".join(sorted(
    _EC_MEMBER_DEGRADED_FLAGS | _EC_MEMBER_REVIEW_FLAGS | _EC_MEMBER_STANDBY_FLAGS
    | {"N", "p"}
))
_EC_MEMBER_TOKEN_RE = re.compile(
    r"(?<![\w-])([A-Za-z][A-Za-z-]*\d+(?:/\d+){1,2})\s*\(([A-Za-z]+)\)"
)
_EC_GROUP_ROW_RE = re.compile(
    r"^\s*(\d+)\s+((?:Po|Port-channel)\d+)\s*\(([A-Za-z]+)\)\s+(.+?)\s*$",
    re.IGNORECASE,
)
_EC_GROUP_CANDIDATE_RE = re.compile(
    r"^\s*\d+\s+(?:Po|Port-channel)\d+\b", re.IGNORECASE
)


def _ec_finding(kind: str, code: str, issue: str) -> dict:
    return {"kind": kind, "code": code, "issue": issue}


def _canonical_port_channel(value: Any) -> str:
    text = value.strip() if isinstance(value, str) else ""
    m = re.fullmatch(r"(?:Po|Port-channel)0*(\d+)", text, re.IGNORECASE)
    return f"Po{int(m.group(1))}" if m else ""


def _canonical_physical_interface(value: Any) -> str:
    text = normalize_ifname(value.strip()) if isinstance(value, str) else ""
    if not text or not PHYSICAL_IFACE_RE.fullmatch(text) or re.match(r"^Po\d+$", text, re.IGNORECASE):
        return ""
    m = re.fullmatch(r"([A-Za-z]+)(\d+(?:/\d+){1,2})", text)
    if not m:
        return ""
    prefixes = {
        "eth": "Eth", "gi": "Gi", "te": "Te", "tw": "Tw", "twe": "Twe",
        "fif": "Fif", "fi": "Fi", "ap": "Ap", "app": "Ap", "fo": "Fo",
        "hu": "Hu", "fa": "Fa",
    }
    prefix = prefixes.get(m.group(1).lower())
    if not prefix:
        return ""
    return prefix + "/".join(str(int(part)) for part in m.group(2).split("/"))


def _classify_etherchannel_member_flags(flags: Any, protocol: Any) -> Tuple[str, str, List[dict]]:
    token = flags if isinstance(flags, str) else ""
    proto = protocol.upper() if isinstance(protocol, str) else ""
    findings: List[dict] = []
    if not token or not token.isalpha():
        return "review", "unclassified", [
            _ec_finding("review", "member_flags_malformed",
                        "Member flags are missing or malformed; live verification is required.")
        ]
    unknown = sorted(set(token) - _EC_MEMBER_KNOWN_FLAGS)
    definite = sorted(set(token) & _EC_MEMBER_DEGRADED_FLAGS)
    forwarding = sorted(set(token) & _EC_MEMBER_FORWARDING_FLAGS)
    standby = "H" in token
    waiting = sorted(set(token) & _EC_MEMBER_REVIEW_FLAGS)

    # A positive forwarding/standby token combined with another state is contradictory.  A definite
    # fault still wins over an unrelated annotation/unknown token (e.g. the real-world RM token), but
    # never over a contradictory P/p/H claim in the same leaf.
    if (forwarding or standby) and (definite or waiting or unknown or len(set(token)) != 1):
        findings.append(_ec_finding(
            "review", "member_flags_contradictory",
            f"Member flag token {token} combines mutually incompatible observed states."
        ))
        return "review", "contradictory", findings
    if definite:
        findings.append(_ec_finding(
            "degraded", "member_non_forwarding",
            f"Member flag token {token} includes supported non-forwarding flag(s) {''.join(definite)}."
        ))
        return "degraded", "non_forwarding_observed", findings
    if forwarding:
        if len(token) != 1:
            return "review", "contradictory", [_ec_finding(
                "review", "member_flags_contradictory",
                f"Member flag token {token} does not describe one bounded forwarding state."
            )]
        return ("assessed", "delay_lacp_up", findings) if token == "p" else (
            "assessed", "forwarding_observed", findings
        )
    if standby:
        if proto != "LACP":
            findings.append(_ec_finding(
                "review", "standby_protocol_mismatch",
                f"Hot-standby flag H is only bounded for LACP, not protocol {proto or '?'}.",
            ))
            return "review", "standby_unverified", findings
        return "assessed", "hot_standby", findings
    if waiting:
        names = {"w": "LACP waiting", "b": "BFD session wait", "d": "platform-dependent delay/default"}
        findings.append(_ec_finding(
            "review", "member_wait_requires_review",
            "Member flag token " + token + " reports " + ", ".join(names[item] for item in waiting)
            + "; persistence and intent are not present in this snapshot.",
        ))
        return "review", "waiting_unverified", findings
    findings.append(_ec_finding(
        "review", "member_flags_unclassified",
        f"Member flag token {token} is outside the bounded producer vocabulary."
    ))
    return "review", "unclassified", findings


def _classify_etherchannel_group_flags(flags: Any) -> Tuple[str, str, List[dict]]:
    token = flags if isinstance(flags, str) else ""
    if not token or not token.isalpha():
        return "review", "unclassified", [_ec_finding(
            "review", "group_flags_malformed",
            "Port-channel group flags are missing or malformed; live verification is required.",
        )]
    definite = sorted(set(token) & _EC_GROUP_DEGRADED_FLAGS)
    unknown = sorted(set(token) - _EC_GROUP_DEGRADED_FLAGS - _EC_GROUP_CONTEXT_FLAGS)
    if definite:
        return "degraded", "down", [_ec_finding(
            "degraded", "group_non_forwarding",
            f"Group flag token {token} includes supported down/min-links flag(s) {''.join(definite)}.",
        )]
    switched = "S" in token
    routed = "R" in token
    if (switched == routed) or "U" not in token or unknown or len(token) != len(set(token)):
        detail = f"Group flag token {token} is not one bounded S/R plus U operational state"
        if unknown:
            detail += f"; unknown flag(s) {''.join(unknown)} are present"
        return "review", "unclassified", [_ec_finding(
            "review", "group_flags_unclassified", detail + ".",
        )]
    return "assessed", "up", []


def _parse_etherchannel_projection_body(output: Any) -> dict:
    """Parse one supported summary body without collapsing group/member identity or flag tokens."""
    text = output if isinstance(output, str) else ""
    groups: List[dict] = []
    findings: List[dict] = []
    rejected = 0
    declared_match = re.search(r"Number of channel-groups in use\s*:\s*(\d+)", text, re.IGNORECASE)
    declared_count = int(declared_match.group(1)) if declared_match else None
    by_group: Dict[str, dict] = {}
    by_id: Dict[str, str] = {}
    member_owner: Dict[str, str] = {}
    current: Optional[dict] = None

    def add_finding(target: List[dict], item: dict) -> None:
        if not any(old["code"] == item["code"] and old["issue"] == item["issue"] for old in target):
            target.append(item)

    for raw in text.splitlines():
        line = raw.rstrip()
        match = _EC_GROUP_ROW_RE.match(line)
        if match:
            group_id_raw, group_raw, group_flags, tail = match.groups()
            group_id = str(int(group_id_raw))
            group = _canonical_port_channel(group_raw)
            proto_match = re.search(r"(?:^|\s)(LACP|PAgP|NONE|-)(?=\s|$)", tail, re.IGNORECASE)
            protocol_raw = proto_match.group(1) if proto_match else ""
            protocol = "NONE" if protocol_raw == "-" else protocol_raw.upper()
            if group in by_group or group_id in by_id:
                rejected += 1
                add_finding(findings, _ec_finding(
                    "review", "duplicate_group_identity",
                    f"A colliding EtherChannel group identity was observed for group {group_id}/{group or group_raw}.",
                ))
                current = None
                continue
            flag_status, operational_state, group_findings = _classify_etherchannel_group_flags(group_flags)
            current = {
                "group_id": group_id,
                "group": group,
                "group_flags": group_flags,
                "protocol": protocol,
                "protocol_raw": protocol_raw,
                "status": flag_status,
                "operational_state": operational_state,
                "members": [],
                "findings": group_findings,
            }
            if not group or int(re.sub(r"\D", "", group) or -1) != int(group_id):
                add_finding(current["findings"], _ec_finding(
                    "review", "group_identity_mismatch",
                    f"Summary group {group_id} does not reconcile to port-channel {group or group_raw}.",
                ))
            if not protocol:
                add_finding(current["findings"], _ec_finding(
                    "review", "protocol_unclassified",
                    f"No bounded aggregation protocol token was parsed for {group or group_raw}.",
                ))
            groups.append(current)
            by_group[group] = current
            by_id[group_id] = group
        elif _EC_GROUP_CANDIDATE_RE.match(line):
            rejected += 1
            current = None
            add_finding(findings, _ec_finding(
                "review", "group_row_malformed",
                "An EtherChannel group row could not be normalized without guessing its flags or columns.",
            ))
            continue
        elif (not line.strip() or re.match(r"^\s*(?:[-+]{3,}|Group\b|Channel\b|Flags?:\b|Number\b)",
                                           line, re.IGNORECASE)):
            if not line.strip() or re.match(r"^\s*(?:Group\b|Flags?:\b|Number\b)", line, re.IGNORECASE):
                current = None

        member_matches = list(_EC_MEMBER_TOKEN_RE.finditer(line))
        if member_matches and current is None:
            rejected += len(member_matches)
            add_finding(findings, _ec_finding(
                "review", "orphan_member_row",
                "One or more EtherChannel member tokens were not attached to a trustworthy group row.",
            ))
            continue
        for member_match in member_matches:
            interface_raw, flags = member_match.groups()
            interface = _canonical_physical_interface(interface_raw)
            if not interface:
                rejected += 1
                add_finding(current["findings"], _ec_finding(
                    "review", "member_identity_malformed",
                    f"Member identity {interface_raw} is outside the bounded physical-interface grammar.",
                ))
                continue
            if interface in member_owner:
                rejected += 1
                add_finding(findings, _ec_finding(
                    "review", "duplicate_member_identity",
                    f"Member {interface} appears more than once across group rows ({member_owner[interface]} and "
                    f"{current['group']}); no ownership is inferred.",
                ))
                continue
            member_owner[interface] = current["group"]
            member_status, member_state, member_findings = _classify_etherchannel_member_flags(
                flags, current["protocol"]
            )
            current["members"].append({
                "interface": interface,
                "flags": flags,
                "status": member_status,
                "state": member_state,
                "findings": member_findings,
            })

    for group in groups:
        group["members"].sort(key=lambda item: (item["interface"].casefold(), item["interface"]))
        if not group["members"] and group["operational_state"] == "up":
            add_finding(group["findings"], _ec_finding(
                "review", "up_group_without_members",
                f"{group['group']} is flagged up but has zero observed members.",
            ))
        if (group["status"] == "degraded"
                or any(item["status"] == "degraded" for item in group["members"])):
            group["status"] = "degraded"
        elif (any(item["status"] == "review" for item in group["members"])
              or any(item["kind"] == "review" for item in group["findings"])):
            group["status"] = "review"
        else:
            group["status"] = "assessed"
        group["findings"] = sorted(group["findings"], key=lambda item: (item["code"], item["issue"]))

    if declared_count is not None and declared_count != len(groups):
        add_finding(findings, _ec_finding(
            "review", "declared_group_count_mismatch",
            f"The summary declares {declared_count} channel-group(s) but {len(groups)} unique group row(s) parsed.",
        ))
    if text.strip() and not groups and declared_count != 0:
        add_finding(findings, _ec_finding(
            "review", "summary_unrecognized",
            "Usable EtherChannel summary text contained no trustworthy group row or explicit zero-group result.",
        ))
    return {
        "groups": sorted(groups, key=lambda item: (int(item["group_id"]), item["group"])),
        "findings": sorted(findings, key=lambda item: (item["code"], item["issue"])),
        "rejected_line_count": rejected,
        "declared_group_count": declared_count,
    }


def _parse_etherchannel_member_states(output: str) -> Dict[str, str]:
    """Backward-compatible member->flag view backed by the structured, collision-aware parser."""
    result: Dict[str, str] = {}
    for group in _parse_etherchannel_projection_body(output)["groups"]:
        for member in group["members"]:
            result[member["interface"]] = member["flags"]
    return result


def _interface_leaf_value(leaf: Any, name: str) -> Any:
    return leaf.get(name) if isinstance(leaf, dict) else getattr(leaf, name, "")


def _etherchannel_associations(ifaces: Any) -> Tuple[List[dict], List[dict]]:
    if not isinstance(ifaces, dict):
        return [], [_ec_finding(
            "review", "association_projection_malformed",
            "Interface/config association projection has an unusable host shape.",
        )]
    associations: Dict[str, dict] = {}
    findings: List[dict] = []
    for port_key, leaf in ifaces.items():
        if not isinstance(leaf, (dict, InterfaceData)):
            if _canonical_physical_interface(port_key):
                findings.append(_ec_finding(
                    "review", "association_projection_malformed",
                    "A physical-interface association leaf has an unusable shape.",
                ))
            continue
        group_raw = _interface_leaf_value(leaf, "port_channel")
        if not isinstance(group_raw, str):
            if group_raw not in (None, ""):
                findings.append(_ec_finding(
                    "review", "association_identity_malformed",
                    "A port-channel association has a non-text group identity.",
                ))
            continue
        if not group_raw.strip():
            continue
        port_raw = port_key if isinstance(port_key, str) else _interface_leaf_value(leaf, "port")
        # build_interfaces intentionally gives the logical bundle record a self-reference
        # (Po1.port_channel == Po1).  That is group metadata, not a physical-member association;
        # omitting it must not contaminate an otherwise healthy raw summary with a false REVIEW.
        if _canonical_port_channel(port_raw):
            continue
        interface = _canonical_physical_interface(port_raw)
        group = _canonical_port_channel(group_raw)
        if not interface or not group:
            findings.append(_ec_finding(
                "review", "association_identity_malformed",
                "A port-channel association has an invalid physical-interface or group identity.",
            ))
            continue
        prior = associations.get(interface)
        if prior:
            code = "association_group_conflict" if prior["group"] != group else "duplicate_association_identity"
            findings.append(_ec_finding(
                "review", code,
                f"Interface association {interface} is duplicated"
                + (f" across {prior['group']} and {group}" if prior["group"] != group else "") + ".",
            ))
            continue
        associations[interface] = {"interface": interface, "group": group}
    return (
        sorted(associations.values(), key=lambda item: (item["interface"].casefold(), item["interface"])),
        sorted(findings, key=lambda item: (item["code"], item["issue"])),
    )


def compute_etherchannel_projection(all_interfaces: Any, all_cmd_to_files: Any) -> dict:
    """Return a deterministic, fail-closed current-run EtherChannel projection.

    Raw summary groups and their exact flags stay separate from interface/config/trunk associations.
    Associations establish a validation subject only; they never become an operational-state claim.
    """
    interface_root = all_interfaces if isinstance(all_interfaces, dict) else {}
    command_root = all_cmd_to_files if isinstance(all_cmd_to_files, dict) else {}
    hosts = sorted(
        {host.strip() for root in (interface_root, command_root) for host in root
         if isinstance(host, str) and host.strip()},
        key=lambda item: (item.casefold(), item),
    )
    rows: List[dict] = []
    capture_states = ("usable", "empty", "error", "missing")
    for host in hosts:
        c2f = command_root.get(host, {})
        host_findings: List[dict] = []
        if not isinstance(c2f, dict):
            c2f = {}
            host_findings.append(_ec_finding(
                "review", "command_projection_malformed",
                "Command-capture projection has an unusable host shape.",
            ))
        capture_state = cmd_capture_state(c2f, *_EC_COMMANDS)
        source_command = ""
        output = ""
        for command in _EC_COMMANDS:
            if cmd_capture_state(c2f, command) == capture_state and capture_state != "missing":
                source_command = command
                if capture_state == "usable":
                    output = _load_cmd_output(c2f, command)
                break
        if capture_state == "missing" and any(command in c2f for command in _EC_COMMANDS):
            host_findings.append(_ec_finding(
                "review", "capture_reference_unusable",
                "A recognized EtherChannel command key exists but its capture reference is unusable.",
            ))
        parsed = _parse_etherchannel_projection_body(output) if capture_state == "usable" else {
            "groups": [], "findings": [], "rejected_line_count": 0, "declared_group_count": None,
        }
        associations, association_findings = _etherchannel_associations(interface_root.get(host, {}))
        host_findings.extend(parsed["findings"])
        host_findings.extend(association_findings)
        deduped_findings = {
            (item["kind"], item["code"], item["issue"]): item for item in host_findings
        }
        rows.append({
            "switch": host,
            "source_command": source_command,
            "capture_state": capture_state,
            "declared_group_count": parsed["declared_group_count"],
            "groups": parsed["groups"],
            "associations": associations,
            "findings": sorted(deduped_findings.values(), key=lambda item: (item["code"], item["issue"])),
            "rejected_line_count": parsed["rejected_line_count"],
        })
    by_capture_state = {state: sum(row["capture_state"] == state for row in rows)
                        for state in capture_states}
    return {
        "schema": "etherchannel_projection/1",
        "rows": rows,
        "summary": {
            "n_devices": len(rows),
            "n_subject_devices": sum(bool(row["groups"] or row["associations"] or row["findings"])
                                     for row in rows),
            "n_groups": sum(len(row["groups"]) for row in rows),
            "n_members": sum(len(group["members"]) for row in rows for group in row["groups"]),
            "n_associations": sum(len(row["associations"]) for row in rows),
            "n_degraded_groups": sum(group["status"] == "degraded"
                                     for row in rows for group in row["groups"]),
            "n_review_groups": sum(group["status"] == "review"
                                   for row in rows for group in row["groups"]),
            "n_rejected_lines": sum(row["rejected_line_count"] for row in rows),
            "by_capture_state": by_capture_state,
        },
        "limitations": [
            "Group/member flags are one current-run local summary projection, not configured or partner intent.",
            "Interface/config/trunk associations are subject evidence only and carry no operational state.",
            "Waiting/BFD-wait flags require live persistence and intent verification.",
        ],
    }

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
                            all_cmd_to_files: Dict[str, Dict[str, str]],
                            etherchannel_projection: Any = None) -> List[dict]:
    """Per-(switch, protocol) health rows. Severity: High (down/inconsistent), Medium
    (waiting / soft), Info (healthy / present). Returns records for sheet + snapshot."""
    records: List[dict] = []
    if etherchannel_projection is None:
        resolved_etherchannel_projection = compute_etherchannel_projection(all_interfaces, all_cmd_to_files)
    else:
        supplied_projection = _validate_etherchannel_projection(etherchannel_projection)
        resolved_etherchannel_projection = (
            etherchannel_projection if supplied_projection["valid"]
            else compute_etherchannel_projection(all_interfaces, all_cmd_to_files)
        )
    etherchannel_by_host = {row["switch"]: row for row in resolved_etherchannel_projection["rows"]}

    def add(host, proto, sev, summary, detail=""):
        records.append({"switch": host, "protocol": proto, "severity": sev,
                        "summary": summary, "detail": detail})

    for host in sorted(all_interfaces):
        c2f = all_cmd_to_files.get(host, {})

        # ---- STP ----
        stp_out = _load_cmd_output(c2f, "show spanning-tree")
        mode = _parse_stp_mode(stp_out)
        stp_states = parse_spanning_tree_states(stp_out)
        stp_roots = parse_spanning_tree_root(stp_out)
        # ``parse_spanning_tree_root`` deliberately preserves a bare VLAN/MST header as a
        # partial record for its own consumers.  That header alone is not a health-state
        # witness: require an actual mode, port state, or root/bridge fact before emitting.
        stp_root_observed = any(
            rec.get("root_priority") is not None
            or bool(rec.get("root_address"))
            or rec.get("bridge_priority") is not None
            or bool(rec.get("is_root"))
            for rec in stp_roots.values()
        )
        if mode or stp_states or stp_root_observed:
            blocked = parse_spanning_tree_blockedports(_load_cmd_output(c2f, "show spanning-tree blockedports"))
            incons = parse_spanning_tree_blockedports(_load_cmd_output(c2f, "show spanning-tree inconsistentports"))
            maxt, _tot = _parse_stp_tcn(_load_cmd_output(c2f, "show spanning-tree detail"))
            nblk, ninc = len(blocked), len(incons)
            sev = "High" if ninc else "Info"
            summary = f"mode {mode or '?'}; {nblk} blocked, {ninc} inconsistent"
            if maxt is not None:
                summary += f"; max TCN {maxt}"
            detail = ("inconsistent: " + ", ".join(sorted(incons))) if ninc else ""
            add(host, "STP", sev, summary, detail)

        # ---- EtherChannel ----
        # The health sheet and cutover baseline deliberately consume the SAME structured projection and
        # closed flag classifier.  This preserves down zero-member groups, group-level D/M/N, NX-OS p/b/r,
        # IOS m/u, hot standby H, duplicates, and malformed rows instead of reducing them to an all-P count.
        ec_row = etherchannel_by_host.get(host, {})
        ec_groups = ec_row.get("groups", [])
        if ec_groups:
            degraded = [group for group in ec_groups if group["status"] == "degraded"]
            review = [group for group in ec_groups if group["status"] == "review"]
            structural_review = bool(ec_row.get("findings") or ec_row.get("rejected_line_count"))
            sev = "High" if degraded else ("Medium" if review or structural_review else "Info")
            members = [member for group in ec_groups for member in group["members"]]
            non_forwarding = [member for member in members if member["status"] == "degraded"]
            summary = f"{len(ec_groups)} bundle(s), {len(members)} member(s)"
            if non_forwarding:
                summary += f"; {len(non_forwarding)} not bundled"
            if degraded:
                summary += f"; {len(degraded)} degraded bundle(s)"
            if review or structural_review:
                summary += "; snapshot review required"
            detail_parts: List[str] = []
            for group in ec_groups:
                if group["operational_state"] != "up" or group["findings"]:
                    detail_parts.append(f"{group['group']}({group['group_flags']})")
                detail_parts.extend(
                    f"{member['interface']}({member['flags']})"
                    for member in group["members"]
                    if (member["status"] != "assessed"
                        or any(flag in _EC_ADVISORY_FLAGS for flag in member["flags"]))
                )
            detail_parts.extend(
                f"projection[{item['code']}]" for item in ec_row.get("findings", [])
            )
            add(host, "EtherChannel", sev, summary, "; ".join(dict.fromkeys(detail_parts)))

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
        bgp = parse_bgp_summary(_load_cmd_output(c2f, *BGP_IPV4_SUMMARY_COMMANDS))
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
            # A group stuck in a NON-FORWARDING role after convergence (Init/Learn -- interface down, auth
            # mismatch, or no peer) is a real first-hop-redundancy fault, not a healthy Info. Standby/Listen/
            # Speak are NORMAL for a non-active member, so an all-Standby device is NOT flagged (it can't be
            # told apart from a healthy backup without the peer's view) -- only Init/Learn escalates.
            stuck = [(g[3], g[0], g[1]) for g in groups if g[1].lower() in ("init", "learn")]
            sev = "Medium" if stuck else "Info"
            detail = "; ".join(f"{port} {proto} {role}" for port, proto, role in stuck)
            add(host, "FHRP", sev,
                f"{len(groups)} group(s) [{', '.join(protos)}]; {actives} active/master"
                + (f"; {len(stuck)} stuck (Init/Learn)" if stuck else ""), detail)

    return records


# Runtime protocol assessability is deliberately a SIBLING of protocol_health,
# not extra pseudo-health rows.  Several consumers use the presence of a health
# row as a parsed-evidence witness; inserting NOT ASSESSED rows into that list
# would silently turn missing evidence into "collected" in readiness/scoring.
PROTOCOL_ASSESSABILITY_STATES = (
    "assessed",
    "partial",
    "captured_no_record",
    "captured_empty",
    "capture_error",
    "not_collected",
    "analysis_unavailable",
)

PROTOCOL_ASSESSABILITY_FAMILIES = (
    {
        "protocol": "STP",
        "inputs": (
            {"id": "state", "commands": ("show spanning-tree",), "required": True},
            {"id": "blocked_ports", "commands": ("show spanning-tree blockedports",), "required": True},
            {"id": "inconsistent_ports", "commands": ("show spanning-tree inconsistentports",), "required": True},
            {"id": "topology_changes", "commands": ("show spanning-tree detail",), "required": False},
        ),
        "boundary": ("Observed mode/state and blocked/inconsistent ports require usable captures; "
                     "topology-change counts are optional and reported only when detail evidence parses."),
        "recollect": ("Re-run show spanning-tree plus blockedports and inconsistentports; add detail where "
                      "the platform supports it."),
    },
    {
        "protocol": "EtherChannel",
        "inputs": (
            {"id": "membership", "commands": ("show etherchannel summary", "show port-channel summary"),
             "required": True},
        ),
        "boundary": ("Observed member flags only; no configured-bundle, partner, hashing, bandwidth, or "
                     "multi-chassis denominator."),
        "recollect": "Re-run the platform's EtherChannel or port-channel summary command.",
    },
    {
        "protocol": "VTP",
        "inputs": (
            {"id": "status", "commands": ("show vtp status",), "required": True},
        ),
        "boundary": "Observed mode, domain, and revision only; no database-propagation proof.",
        "recollect": "Re-run show vtp status.",
    },
    {
        "protocol": "OSPF",
        "inputs": (
            {"id": "neighbors", "commands": ("show ip ospf neighbor",), "required": True},
        ),
        "boundary": ("Observed OSPFv2 neighbors only; configured or expected neighbors that are absent from "
                     "the table are not known."),
        "recollect": "Re-run show ip ospf neighbor and validate the expected-neighbor set separately.",
    },
    {
        "protocol": "BGP",
        "inputs": (
            {"id": "peers", "commands": BGP_IPV4_SUMMARY_COMMANDS, "required": True},
        ),
        "boundary": ("Observed default/global IPv4-unicast summary peers only. Configured-peer intent is "
                     "assessed by the separate bounded literal-peer baseline; other VRFs/address families "
                     "and route-policy correctness remain outside this runtime receipt."),
        "recollect": ("Re-run show ip bgp summary on IOS/IOS-XE or an explicitly IPv4-unicast BGP summary "
                      "on NX-OS, plus show running-config for configured-peer reconciliation."),
    },
    {
        "protocol": "EIGRP",
        "inputs": (
            {"id": "neighbors", "commands": ("show ip eigrp neighbors",), "required": True},
        ),
        "boundary": ("Presence-only observed IPv4 neighbors; missing expected neighbors and negative protocol "
                     "states cannot be inferred from an empty table."),
        "recollect": "Re-run show ip eigrp neighbors and supply an explicit expected-neighbor baseline.",
    },
    {
        "protocol": "FHRP",
        "inputs": (
            {"id": "hsrp_groups", "commands": (
                "show standby brief", "show standby all", "show hsrp brief", "show hsrp all"),
             "required": True},
            {"id": "vrrp_groups", "commands": ("show vrrp brief",), "required": True},
            {"id": "glbp_groups", "commands": ("show glbp brief",), "required": True},
        ),
        "boundary": ("Observed local HSRP, VRRP, and GLBP groups only; peer intent, timers, authentication, "
                     "tracking, and complete election state remain outside this receipt."),
        "recollect": "Re-run the supported HSRP, VRRP, and GLBP summary commands for this platform.",
    },
)


def compute_protocol_assessability(inventory_hosts: List[str],
                                   all_interfaces: Dict[str, Dict[str, InterfaceData]],
                                   all_cmd_to_files: Dict[str, Dict[str, str]],
                                   protocol_health: List[dict],
                                   *, analysis_available: bool = True) -> dict:
    """Return an exact per-device x seven-family runtime evidence receipt.

    ``protocol_health`` intentionally stays sparse: a row means the engine parsed a
    bounded state.  This receipt supplies the missing denominator without inventing
    protocol presence or health.  It retains command-capture state (usable / empty /
    error / missing), whether a health row was emitted, partial multi-input coverage,
    and a closed abstention reason.  No raw body or filesystem path is published.
    """
    host_names: set[str] = set()

    def _add_host(value: object) -> None:
        if isinstance(value, str) and value.strip():
            host_names.add(value.strip())

    for host in (inventory_hosts if isinstance(inventory_hosts, (list, tuple)) else []):
        _add_host(host)
    for source in (all_interfaces, all_cmd_to_files):
        if isinstance(source, dict):
            for host in source:
                _add_host(host)

    emitted: set[Tuple[str, str]] = set()
    for record in (protocol_health if isinstance(protocol_health, list) else []):
        if not isinstance(record, dict):
            continue
        host, protocol = record.get("switch"), record.get("protocol")
        if isinstance(host, str) and isinstance(protocol, str):
            _add_host(host)
            emitted.add((host.strip(), protocol))

    hosts = sorted(host_names, key=lambda value: (value.casefold(), value))
    family_contracts = [
        {
            "protocol": family["protocol"],
            "inputs": [
                {"id": item["id"], "commands": list(item["commands"]),
                 "required": item["required"]}
                for item in family["inputs"]
            ],
            "boundary": family["boundary"],
            "recollect": family["recollect"],
        }
        for family in PROTOCOL_ASSESSABILITY_FAMILIES
    ]
    by_state = {state: 0 for state in PROTOCOL_ASSESSABILITY_STATES}
    rows: List[dict] = []

    for host in hosts:
        c2f = all_cmd_to_files.get(host, {}) if isinstance(all_cmd_to_files, dict) else {}
        if not isinstance(c2f, dict):
            c2f = {}
        for family in PROTOCOL_ASSESSABILITY_FAMILIES:
            protocol = family["protocol"]
            input_states = {
                item["id"]: cmd_capture_state(c2f, *item["commands"])
                for item in family["inputs"]
            }
            required_input_states = {
                item["id"]: input_states[item["id"]]
                for item in family["inputs"] if item["required"]
            }
            # cmd_capture_state's usable > empty > error > missing precedence is correct WITHIN
            # one input group's alternative command spellings.  Across independent input groups,
            # an empty secondary must not hide a failed row-gating command.  Preserve usable as the
            # aggregate when any group is usable (the cell will be partial if another group is not);
            # otherwise fail closed in error > empty > missing order.
            input_values = tuple(required_input_states.values())
            if "usable" in input_values:
                capture_state = "usable"
            elif "error" in input_values:
                capture_state = "error"
            elif "empty" in input_values:
                capture_state = "empty"
            else:
                capture_state = "missing"
            health_row_emitted = (host, protocol) in emitted
            incomplete = [name for name, value in required_input_states.items()
                          if value != "usable"]

            if not analysis_available:
                state = "analysis_unavailable"
                reason = ("Protocol-health analysis was unavailable for this run. Captures are disclosed, "
                          "but no health conclusion is asserted.")
            elif health_row_emitted:
                if incomplete or "usable" not in required_input_states.values():
                    state = "partial"
                    detail = ", ".join(incomplete) if incomplete else "current-run source capture"
                    reason = (f"A health row was emitted, but {detail} evidence was not usable "
                              "(missing, empty, or errored). "
                              "Treat the observed result as partial, not a complete protocol verdict.")
                else:
                    state = "assessed"
                    reason = ("A bounded health row was emitted from usable current-run evidence. The family "
                              "boundary still applies; this is not protocol-completeness proof.")
            elif capture_state == "usable" and incomplete:
                state = "partial"
                reason = ("Usable evidence exists for part of this family, but "
                          f"{', '.join(incomplete)} evidence was not usable (missing, empty, or errored) "
                          "and no health row "
                          "was emitted. No complete protocol verdict is asserted.")
            elif capture_state == "usable":
                state = "captured_no_record"
                reason = ("Usable command output was captured, but no assessable protocol state was parsed. "
                          "This is not proof that the protocol is absent or healthy.")
            elif capture_state == "empty":
                state = "captured_empty"
                reason = ("A recognized command capture was empty. No protocol state was observed and no "
                          "health conclusion is made.")
            elif capture_state == "error":
                state = "capture_error"
                reason = ("Recognized command variants returned an error. Re-collect with a supported command "
                          "before drawing a protocol health conclusion.")
            else:
                state = "not_collected"
                reason = ("No recognized command capture is present. Re-collect before drawing a protocol "
                          "health conclusion.")

            by_state[state] += 1
            rows.append({
                "switch": host,
                "protocol": protocol,
                "input_states": input_states,
                "capture_state": capture_state,
                "health_row_emitted": health_row_emitted,
                "state": state,
                "reason": reason,
            })

    complete_devices = sum(
        1 for host in hosts
        if all(row["state"] == "assessed" for row in rows if row["switch"] == host)
    )
    return {
        "schema": "protocol_assessability/1",
        "families": family_contracts,
        "rows": rows,
        "summary": {
            "n_devices": len(hosts),
            "n_families": len(PROTOCOL_ASSESSABILITY_FAMILIES),
            "n_cells": len(rows),
            "n_health_rows": sum(1 for row in rows if row["health_row_emitted"]),
            "n_complete_devices": complete_devices,
            "by_state": by_state,
        },
        "limitations": [
            "A missing health row never proves that a protocol is absent or healthy.",
            "Observed routing neighbors are not an expected-neighbor or configuration denominator.",
            "The receipt reports current-run capture and parser reachability; it is not live field validation.",
        ],
    }


_ROUTING_BASELINE_PROTOCOLS = ("OSPF", "BGP", "EIGRP")
_ROUTING_BASELINE_COMMANDS = {
    "OSPF": "show ip ospf neighbor",
    "BGP": "show ip bgp summary",
    "EIGRP": "show ip eigrp neighbors",
}
_ROUTING_BASELINE_INPUTS = {"OSPF": "neighbors", "BGP": "peers", "EIGRP": "neighbors"}
_PROTOCOL_CAPTURE_STATES = {"usable", "empty", "error", "missing"}


def _strict_protocol_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _validate_protocol_assessability_receipt(value: Any) -> dict:
    """Strictly reconcile a public ``protocol_assessability/1`` receipt.

    The returned index is safe for receipt-gated feature helpers only when ``valid`` is true.
    ``claimed_subjects`` is deliberately retained on failure solely to scope a blocker row; it does
    not make any capture or health claim trustworthy.  Routing and EtherChannel share this exact
    validator so neither feature can relax the seven-family / one-cell-per-family denominator.
    """
    present = value is not None
    family_names = tuple(family["protocol"] for family in PROTOCOL_ASSESSABILITY_FAMILIES)
    family_inputs = {
        family["protocol"]: tuple(item["id"] for item in family["inputs"])
        for family in PROTOCOL_ASSESSABILITY_FAMILIES
    }
    required_inputs = {
        family["protocol"]: tuple(item["id"] for item in family["inputs"] if item["required"])
        for family in PROTOCOL_ASSESSABILITY_FAMILIES
    }

    def invalid(reason: str, claimed=()) -> dict:
        return {
            "present": present, "valid": False, "reason": reason, "index": {},
            "claimed_subjects": set(claimed),
        }

    if not isinstance(value, dict):
        return invalid("protocol assessability receipt is missing" if not present else
                       "protocol assessability receipt has an unusable shape")

    rows = value.get("rows")
    safely_claimed = set()
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict) or row.get("health_row_emitted") is not True:
                continue
            host = _strict_protocol_text(row.get("switch"))
            protocol = _strict_protocol_text(row.get("protocol"))
            if host and protocol in family_names:
                safely_claimed.add((host, protocol))
    if value.get("schema") != "protocol_assessability/1":
        return invalid("protocol assessability receipt schema is not protocol_assessability/1",
                       safely_claimed)
    families = value.get("families")
    summary = value.get("summary")
    observed_family_names = tuple(
        _strict_protocol_text(item.get("protocol")) for item in families if isinstance(item, dict)
    ) if isinstance(families, list) else ()
    if observed_family_names != family_names:
        return invalid("protocol assessability family denominator is incomplete or reordered",
                       safely_claimed)
    if not isinstance(rows, list) or not isinstance(summary, dict):
        return invalid("protocol assessability rows or summary have an unusable shape", safely_claimed)

    integer_fields = ("n_devices", "n_families", "n_cells", "n_health_rows", "n_complete_devices")
    if any(not isinstance(summary.get(name), int) or isinstance(summary.get(name), bool)
           or summary.get(name) < 0 for name in integer_fields):
        return invalid("protocol assessability summary contains an invalid count", safely_claimed)
    n_devices = summary["n_devices"]
    if (summary["n_families"] != len(family_names)
            or summary["n_cells"] != len(rows)
            or len(rows) != n_devices * len(family_names)):
        return invalid("protocol assessability summary does not reconcile to its exact denominator",
                       safely_claimed)

    index: Dict[tuple, dict] = {}
    hosts: set[str] = set()
    actual_by_state = {state: 0 for state in PROTOCOL_ASSESSABILITY_STATES}
    for row in rows:
        if not isinstance(row, dict):
            return invalid("protocol assessability contains a malformed row", safely_claimed)
        host = _strict_protocol_text(row.get("switch"))
        protocol = _strict_protocol_text(row.get("protocol"))
        state = _strict_protocol_text(row.get("state"))
        capture_state = _strict_protocol_text(row.get("capture_state"))
        emitted = row.get("health_row_emitted")
        input_states = row.get("input_states")
        if (not host or protocol not in family_names or state not in PROTOCOL_ASSESSABILITY_STATES
                or capture_state not in _PROTOCOL_CAPTURE_STATES or not isinstance(emitted, bool)
                or not isinstance(input_states, dict)):
            return invalid("protocol assessability contains an invalid switch, family, state, or leaf",
                           safely_claimed)
        if set(input_states) != set(family_inputs[protocol]) or any(
                state_value not in _PROTOCOL_CAPTURE_STATES for state_value in input_states.values()):
            return invalid("protocol assessability input-state denominator is malformed", safely_claimed)

        required_values = tuple(input_states[name] for name in required_inputs[protocol])
        expected_capture = (
            "usable" if "usable" in required_values else
            "error" if "error" in required_values else
            "empty" if "empty" in required_values else "missing"
        )
        incomplete = any(state_value != "usable" for state_value in required_values)
        if capture_state != expected_capture:
            return invalid("protocol assessability capture state does not reconcile to its inputs",
                           safely_claimed)
        state_consistent = (
            state == "analysis_unavailable"
            or (state == "assessed" and emitted and not incomplete)
            or (state == "partial" and incomplete and (emitted or capture_state == "usable"))
            or (state == "captured_no_record" and not emitted and not incomplete
                and capture_state == "usable")
            or (state == "captured_empty" and not emitted and capture_state == "empty")
            or (state == "capture_error" and not emitted and capture_state == "error")
            or (state == "not_collected" and not emitted and capture_state == "missing")
        )
        if not state_consistent:
            return invalid("protocol assessability row state contradicts capture and health-row evidence",
                           safely_claimed)
        key = (host, protocol)
        if key in index:
            return invalid("protocol assessability contains a duplicate switch-family cell",
                           safely_claimed)
        index[key] = row
        hosts.add(host)
        actual_by_state[state] += 1

    complete_devices = sum(
        1 for host in hosts
        if all(index.get((host, protocol), {}).get("state") == "assessed"
               for protocol in family_names)
    )
    by_state = summary.get("by_state")
    by_state_valid = (
        isinstance(by_state, dict)
        and set(by_state) == set(PROTOCOL_ASSESSABILITY_STATES)
        and all(isinstance(count, int) and not isinstance(count, bool) and count >= 0
                for count in by_state.values())
    )
    if (len(hosts) != n_devices or len(index) != len(rows)
            or summary["n_health_rows"] != sum(row["health_row_emitted"] for row in rows)
            or summary["n_complete_devices"] != complete_devices
            or not by_state_valid or by_state != actual_by_state):
        return invalid("protocol assessability rows do not reconcile to the summary", safely_claimed)
    return {
        "present": True, "valid": True, "reason": "", "index": index,
        "claimed_subjects": safely_claimed,
    }


def summarize_stp_consistency_baseline(
        protocol_health: Any, protocol_assessability: Any, *,
        all_interfaces: Any = None, stp_roots: Any = None) -> dict:
    """Return the one receipt-gated owner of a bounded STP-consistency claim.

    A subject is established only by positive STP/L2 evidence: a matching STP health row, an
    emitted STP receipt cell, normalized Access/Trunk or live-trunk/per-VLAN STP interface evidence,
    or a non-empty per-device STP-root projection.  Bare inventory, move-group membership, CDP,
    port-channel association, SVI presence, and inferred role are deliberately not subjects.

    The claim has only two evidence prerequisites: usable current-run ``state`` and
    ``inconsistent_ports`` captures.  ``blocked_ports`` remains disclosed but does not gate this
    consistency claim, and ``topology_changes`` is optional.  Exactly one well-formed producer STP
    health row must reconcile to every emitted claim.  Summary/detail prose is never interpreted.
    """
    receipt = _validate_protocol_assessability_receipt(protocol_assessability)
    stp_claims = {
        host for host, protocol in receipt["claimed_subjects"] if protocol == "STP"
    }
    health_by_host: Dict[str, List[dict]] = {}
    health_subjects: set[str] = set()
    health_shape_valid = isinstance(protocol_health, list)
    if health_shape_valid:
        for record in protocol_health:
            if not isinstance(record, dict) or record.get("protocol") != "STP":
                continue
            host = _strict_protocol_text(record.get("switch"))
            if not host:
                continue
            health_subjects.add(host)
            health_by_host.setdefault(host, []).append(record)

    def interface_leaf(record: Any, name: str) -> Any:
        return record.get(name) if isinstance(record, dict) else getattr(record, name, "")

    interface_subjects: set[str] = set()
    if isinstance(all_interfaces, dict):
        for host_value, ifaces in all_interfaces.items():
            host = _strict_protocol_text(host_value)
            if not host or not isinstance(ifaces, dict):
                continue
            for data in ifaces.values():
                mode = _strict_protocol_text(interface_leaf(data, "switchport_mode"))
                has_stp_state = any(
                    bool(_strict_protocol_text(interface_leaf(data, field)))
                    for field in ("stp_fwd_vlans", "stp_blk_vlans", "stp_other_vlans")
                )
                if (mode.casefold() == "access" or is_trunk_mode(mode)
                        or is_live_trunk_status(interface_leaf(data, "trunk_status"))
                        or has_stp_state):
                    interface_subjects.add(host)
                    break

    root_subjects: set[str] = set()
    if isinstance(stp_roots, dict):
        for host_value, roots in stp_roots.items():
            host = _strict_protocol_text(host_value)
            if host and isinstance(roots, dict) and bool(roots):
                root_subjects.add(host)

    subject_hosts = sorted(
        health_subjects | stp_claims | interface_subjects | root_subjects,
        key=lambda value: (value.casefold(), value),
    )
    evidence_order = {
        "protocol_health": 0,
        "protocol_assessability.health_row_emitted": 1,
        "interfaces.positive_l2": 2,
        "stp_roots": 3,
    }
    disclosure_labels = {
        "usable": "observed",
        "missing": "not collected",
        "empty": "captured empty",
        "error": "capture error",
    }
    rows: List[dict] = []
    for host in subject_hosts:
        findings: List[dict] = []

        def finding(kind: str, code: str, issue: str) -> None:
            if not any(item["code"] == code and item["issue"] == issue for item in findings):
                findings.append({"kind": kind, "code": code, "issue": issue})

        evidence = []
        if host in health_subjects:
            evidence.append("protocol_health")
        if host in stp_claims:
            evidence.append("protocol_assessability.health_row_emitted")
        if host in interface_subjects:
            evidence.append("interfaces.positive_l2")
        if host in root_subjects:
            evidence.append("stp_roots")
        evidence.sort(key=evidence_order.__getitem__)

        receipt_row = receipt["index"].get((host, "STP")) if receipt["valid"] else None
        if not receipt["present"]:
            finding("not_verified", "receipt_missing",
                    "Current-run protocol assessability receipt is missing.")
        elif not receipt["valid"]:
            finding("review", "receipt_invalid", receipt["reason"] + ".")
        elif receipt_row is None:
            finding("review", "subject_receipt_missing",
                    "The positive STP subject is absent from the validated receipt denominator.")

        candidates = health_by_host.get(host, [])

        def well_formed(record: Any) -> bool:
            severity = record.get("severity") if isinstance(record, dict) else None
            detail = record.get("detail") if isinstance(record, dict) else None
            return (
                isinstance(record, dict)
                and record.get("switch") == host
                and record.get("protocol") == "STP"
                and severity in {"Info", "High"}
                and bool(_strict_protocol_text(record.get("summary")))
                and isinstance(detail, str)
                and ((severity == "Info" and detail == "")
                     or (severity == "High" and bool(_strict_protocol_text(detail))))
            )

        valid_health = [record for record in candidates if well_formed(record)]
        if not health_shape_valid:
            finding("not_verified" if protocol_health is None else "review",
                    "health_missing" if protocol_health is None else "health_shape_invalid",
                    "The current-run protocol-health projection is missing." if protocol_health is None else
                    "The current-run protocol-health projection has an unusable shape.")
        if candidates and len(valid_health) != len(candidates):
            finding("review", "health_row_malformed",
                    "At least one matching STP health row is not a well-formed producer row.")
        if len(candidates) > 1:
            finding("review", "duplicate_health_rows",
                    "More than one matching STP health row exists for this switch.")

        receipt_state = _strict_protocol_text(receipt_row.get("state")) if receipt_row else (
            "invalid" if receipt["present"] else "missing"
        )
        capture_state = _strict_protocol_text(receipt_row.get("capture_state")) if receipt_row else ""
        emitted = receipt_row.get("health_row_emitted") if receipt_row else (
            True if host in stp_claims else None
        )
        input_states = dict(receipt_row.get("input_states")) if receipt_row else {}
        claim_prerequisites_usable = (
            input_states.get("state") == "usable"
            and input_states.get("inconsistent_ports") == "usable"
        )
        blocked_ports_state = input_states.get("blocked_ports", "not_verified")
        topology_changes_state = input_states.get("topology_changes", "not_verified")
        blocked_label = disclosure_labels.get(blocked_ports_state, "not verified")
        topology_label = disclosure_labels.get(topology_changes_state, "not verified")
        availability_disclosure = (
            f"Blocked-port capture: {blocked_label}; no blocked-port count is claimed. "
            f"Optional topology-change capture: {topology_label}; no topology-change count is claimed."
        )

        if receipt_row is not None:
            if emitted is True and len(candidates) != 1:
                finding("review", "emitted_health_reconciliation",
                        "The receipt declares an emitted STP health row, but exactly one matching row is not present.")
            elif emitted is False and candidates:
                finding("review", "emitted_health_reconciliation",
                        "A matching STP health row exists although the receipt says none was emitted.")

            if receipt_state == "partial" and not claim_prerequisites_usable:
                finding("review", "claim_prerequisite_partial",
                        "Usable current-run state and inconsistent-port captures are both required for this claim.")
            elif receipt_state in {
                    "captured_no_record", "captured_empty", "capture_error",
                    "not_collected", "analysis_unavailable"}:
                finding("not_verified", "receipt_not_assessed",
                        "The current-run receipt does not authorize an STP consistency conclusion.")
            elif receipt_state not in {"assessed", "partial"}:
                finding("review", "receipt_state_unusable",
                        "The STP receipt state is outside the bounded consistency-owner contract.")

        health_severity = valid_health[0]["severity"] if len(candidates) == 1 and len(valid_health) == 1 else ""
        if (receipt_row is not None and emitted is True and len(candidates) == 1
                and len(valid_health) == 1 and claim_prerequisites_usable
                and receipt_state in {"assessed", "partial"} and health_severity == "High"):
            finding("degraded", "inconsistent_ports_observed",
                    "The reconciled STP health row reports a High inconsistent-port condition.")

        if any(item["kind"] == "review" for item in findings):
            status = "review"
        elif any(item["kind"] == "not_verified" for item in findings):
            status = "not_verified"
        elif any(item["kind"] == "degraded" for item in findings):
            status = "degraded"
        elif (receipt_row is not None and emitted is True and len(candidates) == 1
              and len(valid_health) == 1 and claim_prerequisites_usable
              and receipt_state in {"assessed", "partial"} and health_severity == "Info"):
            status = "assessed"
        else:
            status = "not_verified"
            finding("not_verified", "consistency_not_verified",
                    "The bounded STP consistency prerequisites did not reconcile to an assessed claim.")

        issue = "; ".join(item["issue"] for item in findings)
        if status == "assessed":
            baseline = ("Usable current-run STP state and inconsistent-port evidence reconciles to exactly "
                        "one clean Info health row.")
            acceptance = (
                f"Observed bounded STP consistency baseline for {host}. Re-run show spanning-tree and "
                "show spanning-tree inconsistentports; accept only if STP state remains observable and no "
                "inconsistent ports are reported. Blocked-port and topology-change evidence are disclosed "
                "boundaries, not prerequisites for this claim."
            )
            note = "Bounded current-run STP consistency claim; not proof of intended topology or root placement."
        elif status == "degraded":
            baseline = ("Usable current-run STP state and inconsistent-port evidence reconciles to exactly "
                        "one High health row.")
            acceptance = (
                "PRE-CUTOVER DEGRADED — BLOCKER: a reconciled current-run STP High condition exists. "
                "Matching this degraded state after cutover is NOT ACCEPTANCE; resolve it and re-collect "
                "show spanning-tree plus show spanning-tree inconsistentports before the window."
            )
            note = "Definite bounded STP consistency degradation; no intended-topology denominator was inferred."
        elif status == "review":
            baseline = "The current-run STP consistency evidence is ambiguous or contradictory."
            acceptance = (
                f"PRE-CUTOVER REVIEW — BLOCKER: {issue} Re-collect show spanning-tree plus "
                "show spanning-tree inconsistentports and reconcile exactly one STP health row before acceptance."
            )
            note = "STP consistency evidence requires review; no health conclusion is asserted."
        else:
            baseline = "No receipt-verified current-run STP consistency baseline is available."
            acceptance = (
                "STP CONSISTENCY BASELINE NOT VERIFIED — BLOCKER: current-run STP state and "
                "inconsistent-port evidence are unavailable or not receipt-verified. Re-collect show spanning-tree "
                "plus show spanning-tree inconsistentports before acceptance."
            )
            note = "STP consistency is not verified; no health conclusion is asserted."

        acceptance = f"{acceptance} {availability_disclosure}"
        note = f"{note} {availability_disclosure}"

        source_parts = [
            f"protocol_health[{host},STP]",
            f"protocol_assessability.rows[{host},STP]",
        ]
        if host in interface_subjects:
            source_parts.append(f"interfaces.{host}")
        if host in root_subjects:
            source_parts.append(f"stp_roots.{host}")
        rows.append({
            "switch": host,
            "status": status,
            "receipt_state": receipt_state,
            "capture_state": capture_state,
            "health_row_emitted": emitted,
            "health_severity": health_severity,
            "input_states": input_states,
            "blocked_ports_state": blocked_ports_state,
            "topology_changes_state": topology_changes_state,
            "availability_disclosure": availability_disclosure,
            "subject_evidence": evidence,
            "findings": sorted(findings, key=lambda item: (item["code"], item["issue"])),
            "command": "show spanning-tree inconsistentports",
            "baseline": baseline,
            "acceptance": acceptance,
            "issue": issue,
            "note": note,
            "source_key": " + ".join(source_parts),
            "projection_custody": "embedded_unverified",
        })

    by_status = {state: sum(row["status"] == state for row in rows)
                 for state in ("assessed", "degraded", "review", "not_verified")}
    if by_status["degraded"]:
        overall = "degraded"
    elif by_status["review"]:
        overall = "review"
    elif by_status["not_verified"] or not rows:
        overall = "not_verified"
    else:
        overall = "assessed"
    return {
        "schema": "stp_consistency_baseline/1",
        "scope": "bounded_current_run_state_and_inconsistent_ports",
        "status": overall,
        "assessed": bool(rows) and all(row["status"] in {"assessed", "degraded"} for row in rows),
        "projection_custody": "embedded_unverified",
        "receipt": {
            "present": receipt["present"],
            "valid": receipt["valid"],
            "reason": receipt["reason"],
        },
        "rows": rows,
        "summary": {"n_subjects": len(rows), "by_status": by_status},
        "limitations": [
            "The claim requires usable current-run state and inconsistent-port captures only.",
            "Blocked-port evidence is disclosed but is not a prerequisite; topology-change evidence is optional.",
            "The baseline is not an intended-topology, root-placement, loop-freedom, or change-persistence proof.",
            "The embedded receipt does not cryptographically bind protocol_health to raw captures.",
        ],
    }


def _valid_etherchannel_findings(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, dict)
        and set(item) == {"kind", "code", "issue"}
        and item.get("kind") in ("degraded", "review")
        and bool(_strict_protocol_text(item.get("code")))
        and bool(_strict_protocol_text(item.get("issue")))
        for item in value
    )


def _validate_etherchannel_projection(value: Any) -> dict:
    """Strict structural/reconciliation view of ``etherchannel_projection/1``."""
    present = value is not None
    claimed_subjects: set[str] = set()
    raw_rows = value.get("rows") if isinstance(value, dict) else None
    if isinstance(raw_rows, list):
        for raw_row in raw_rows:
            if not isinstance(raw_row, dict):
                continue
            host = _strict_protocol_text(raw_row.get("switch"))
            if not host:
                continue
            if (raw_row.get("groups") or raw_row.get("associations") or raw_row.get("findings")
                    or raw_row.get("rejected_line_count")):
                claimed_subjects.add(host)

    def invalid(reason: str, *, scoped_host: str = "") -> dict:
        if scoped_host:
            claimed_subjects.add(scoped_host)
        return {
            "present": present, "valid": False, "reason": reason, "index": {},
            "claimed_subjects": claimed_subjects,
        }

    if not isinstance(value, dict):
        return invalid("EtherChannel projection is missing" if not present else
                       "EtherChannel projection has an unusable root shape")
    if value.get("schema") != "etherchannel_projection/1":
        return invalid("EtherChannel projection schema is not etherchannel_projection/1")
    summary = value.get("summary")
    if not isinstance(raw_rows, list) or not isinstance(summary, dict):
        return invalid("EtherChannel projection rows or summary have an unusable shape")

    index: Dict[str, dict] = {}
    seen_members: Dict[Tuple[str, str], str] = {}
    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            return invalid("EtherChannel projection contains a malformed device row")
        host = _strict_protocol_text(raw_row.get("switch"))
        if not host:
            return invalid("EtherChannel projection contains an invalid switch identity")
        if host in index:
            return invalid("EtherChannel projection contains a duplicate switch row", scoped_host=host)
        source_command = _strict_protocol_text(raw_row.get("source_command"))
        capture_state = _strict_protocol_text(raw_row.get("capture_state"))
        groups = raw_row.get("groups")
        associations = raw_row.get("associations")
        findings = raw_row.get("findings")
        rejected = raw_row.get("rejected_line_count")
        declared = raw_row.get("declared_group_count")
        if (source_command not in ("", *_EC_COMMANDS)
                or capture_state not in _PROTOCOL_CAPTURE_STATES
                or not isinstance(groups, list) or not isinstance(associations, list)
                or not _valid_etherchannel_findings(findings)
                or not isinstance(rejected, int) or isinstance(rejected, bool) or rejected < 0
                or (declared is not None and (not isinstance(declared, int)
                                              or isinstance(declared, bool) or declared < 0))):
            return invalid("EtherChannel projection contains an invalid device leaf", scoped_host=host)
        if capture_state == "usable" and not source_command:
            return invalid("Usable EtherChannel projection is missing its source command", scoped_host=host)
        if capture_state == "missing" and source_command:
            return invalid("Missing EtherChannel projection contradicts its source command", scoped_host=host)

        # Host-level findings retain parser facts that cannot be reconstructed from the surviving
        # normalized groups (a rejected duplicate row is deliberately not copied into ``groups``).
        # Reconcile every derivable invariant and require at least one owned rejection breadcrumb
        # whenever ``rejected_line_count`` is non-zero.  Otherwise stripping only the finding could
        # promote a duplicate/malformed raw summary from REVIEW to assessed while its rejected count
        # remained in plain sight.
        host_finding_codes = {
            "duplicate_group_identity", "group_row_malformed", "orphan_member_row",
            "duplicate_member_identity", "declared_group_count_mismatch", "summary_unrecognized",
            "association_projection_malformed", "association_identity_malformed",
            "association_group_conflict", "duplicate_association_identity",
            "command_projection_malformed", "capture_reference_unusable",
        }
        if (findings != sorted(findings, key=lambda item: (item["code"], item["issue"]))
                or len({(item["code"], item["issue"]) for item in findings}) != len(findings)
                or any(item["kind"] != "review" or item["code"] not in host_finding_codes
                       for item in findings)):
            return invalid("EtherChannel host findings are not canonical", scoped_host=host)
        rejection_codes = {
            "duplicate_group_identity", "group_row_malformed", "orphan_member_row",
            "duplicate_member_identity",
        }
        has_host_rejection_finding = any(item["code"] in rejection_codes for item in findings)
        expected_count_finding = _ec_finding(
            "review", "declared_group_count_mismatch",
            f"The summary declares {declared} channel-group(s) but {len(groups)} unique group row(s) parsed.",
        ) if declared is not None and declared != len(groups) else None
        count_findings = [item for item in findings if item["code"] == "declared_group_count_mismatch"]
        if count_findings != ([expected_count_finding] if expected_count_finding else []):
            return invalid("EtherChannel declared group count does not reconcile to its finding",
                           scoped_host=host)
        expected_empty_finding = _ec_finding(
            "review", "summary_unrecognized",
            "Usable EtherChannel summary text contained no trustworthy group row or explicit zero-group result.",
        ) if capture_state == "usable" and not groups and declared != 0 else None
        empty_findings = [item for item in findings if item["code"] == "summary_unrecognized"]
        if empty_findings != ([expected_empty_finding] if expected_empty_finding else []):
            return invalid("EtherChannel zero-group result does not reconcile to its finding",
                           scoped_host=host)

        seen_groups: set[str] = set()
        seen_ids: set[str] = set()
        has_nested_rejection_finding = False
        for group in groups:
            if not isinstance(group, dict):
                return invalid("EtherChannel projection contains a malformed group record", scoped_host=host)
            group_id = _strict_protocol_text(group.get("group_id"))
            group_name = _strict_protocol_text(group.get("group"))
            group_flags = group.get("group_flags")
            protocol = _strict_protocol_text(group.get("protocol"))
            protocol_raw = _strict_protocol_text(group.get("protocol_raw"))
            status = _strict_protocol_text(group.get("status"))
            operational_state = _strict_protocol_text(group.get("operational_state"))
            members = group.get("members")
            group_findings = group.get("findings")
            expected_protocol = "NONE" if protocol_raw == "-" else protocol_raw.upper()
            protocol_missing = not protocol and not protocol_raw
            if (not group_id.isdigit() or not group_name
                    or _canonical_port_channel(group_name) != group_name
                    or not isinstance(group_flags, str) or not group_flags.isalpha()
                    or (not protocol_missing and protocol not in ("LACP", "PAGP", "NONE"))
                    or (not protocol_missing and expected_protocol != protocol)
                    or status not in ("assessed", "degraded", "review")
                    or operational_state not in ("up", "down", "unclassified")
                    or not isinstance(members, list)
                    or not _valid_etherchannel_findings(group_findings)):
                return invalid("EtherChannel projection contains an invalid group leaf", scoped_host=host)
            if group_name in seen_groups or group_id in seen_ids:
                return invalid("EtherChannel projection contains a duplicate group identity", scoped_host=host)
            seen_groups.add(group_name)
            seen_ids.add(group_id)
            base_status, base_state, expected_group_findings = _classify_etherchannel_group_flags(group_flags)
            if base_state != operational_state:
                return invalid("EtherChannel group state does not reconcile to its exact flags", scoped_host=host)
            if protocol_missing:
                expected_group_findings.append(_ec_finding(
                    "review", "protocol_unclassified",
                    f"No bounded aggregation protocol token was parsed for {group_name}.",
                ))
            if int(group_id) != int(re.sub(r"\D", "", group_name)):
                expected_group_findings.append(_ec_finding(
                    "review", "group_identity_mismatch",
                    f"Summary group {group_id} does not reconcile to port-channel {group_name}.",
                ))

            member_statuses: List[str] = []
            seen_group_members: set[str] = set()
            for member in members:
                if not isinstance(member, dict):
                    return invalid("EtherChannel projection contains a malformed member record", scoped_host=host)
                interface = _strict_protocol_text(member.get("interface"))
                flags = member.get("flags")
                member_status = _strict_protocol_text(member.get("status"))
                member_state = _strict_protocol_text(member.get("state"))
                member_findings = member.get("findings")
                expected_status, expected_state, expected_member_findings = _classify_etherchannel_member_flags(
                    flags, protocol
                )
                if (_canonical_physical_interface(interface) != interface
                        or not isinstance(flags, str) or not flags.isalpha()
                        or member_status != expected_status or member_state != expected_state
                        or not _valid_etherchannel_findings(member_findings)
                        or member_findings != expected_member_findings):
                    return invalid("EtherChannel projection contains an invalid member leaf", scoped_host=host)
                if interface in seen_group_members or (host, interface) in seen_members:
                    return invalid("EtherChannel projection contains a duplicate member identity", scoped_host=host)
                seen_group_members.add(interface)
                seen_members[(host, interface)] = group_name
                member_statuses.append(member_status)
            if not members and base_state == "up":
                expected_group_findings.append(_ec_finding(
                    "review", "up_group_without_members",
                    f"{group_name} is flagged up but has zero observed members.",
                ))
            # The raw member-token grammar is intentionally wider than the canonical physical-interface
            # grammar so a logical/malformed token such as Vlan1/1(P) is disclosed rather than silently
            # skipped.  Its identity no longer exists in ``members`` after rejection, so this one exact,
            # bounded parser-owned finding is the only permissible non-classifier nested addition.
            malformed_identity_re = re.compile(
                r"^Member identity ([A-Za-z][A-Za-z-]*\d+(?:/\d+){1,2}) is outside the bounded "
                r"physical-interface grammar\.$"
            )
            parser_member_findings = []
            for item in group_findings:
                if item["code"] != "member_identity_malformed":
                    continue
                match = malformed_identity_re.fullmatch(item["issue"])
                if (item["kind"] != "review" or not match
                        or _canonical_physical_interface(match.group(1))):
                    return invalid("EtherChannel malformed-member finding is not canonical",
                                   scoped_host=host)
                parser_member_findings.append(item)
            if len({item["issue"] for item in parser_member_findings}) != len(parser_member_findings):
                return invalid("EtherChannel malformed-member findings contain a duplicate",
                               scoped_host=host)
            expected_group_findings.extend(parser_member_findings)
            has_nested_rejection_finding = has_nested_rejection_finding or bool(parser_member_findings)
            expected_group_findings = sorted(
                expected_group_findings, key=lambda item: (item["code"], item["issue"])
            )
            if group_findings != expected_group_findings:
                return invalid("EtherChannel group findings do not reconcile to exact flags and identity",
                               scoped_host=host)
            finding_kinds = {item["kind"] for item in expected_group_findings}
            expected_group_status = (
                "degraded" if base_status == "degraded" or "degraded" in member_statuses
                or "degraded" in finding_kinds else
                "review" if base_status == "review" or "review" in member_statuses
                or "review" in finding_kinds else "assessed"
            )
            if status != expected_group_status:
                return invalid("EtherChannel group status does not reconcile to group/member evidence",
                               scoped_host=host)

        if bool(rejected) != (has_host_rejection_finding or has_nested_rejection_finding):
            return invalid("EtherChannel rejected-line count lacks its parser finding", scoped_host=host)

        seen_associations: set[str] = set()
        for association in associations:
            if not isinstance(association, dict):
                return invalid("EtherChannel projection contains a malformed association", scoped_host=host)
            interface = _strict_protocol_text(association.get("interface"))
            group_name = _strict_protocol_text(association.get("group"))
            if (_canonical_physical_interface(interface) != interface
                    or _canonical_port_channel(group_name) != group_name
                    or interface in seen_associations):
                return invalid("EtherChannel projection contains an invalid or duplicate association",
                               scoped_host=host)
            seen_associations.add(interface)
        index[host] = raw_row

    expected_summary = {
        "n_devices": len(raw_rows),
        "n_subject_devices": sum(bool(row["groups"] or row["associations"] or row["findings"])
                                 for row in raw_rows),
        "n_groups": sum(len(row["groups"]) for row in raw_rows),
        "n_members": sum(len(group["members"]) for row in raw_rows for group in row["groups"]),
        "n_associations": sum(len(row["associations"]) for row in raw_rows),
        "n_degraded_groups": sum(group["status"] == "degraded"
                                 for row in raw_rows for group in row["groups"]),
        "n_review_groups": sum(group["status"] == "review"
                               for row in raw_rows for group in row["groups"]),
        "n_rejected_lines": sum(row["rejected_line_count"] for row in raw_rows),
        "by_capture_state": {
            state: sum(row["capture_state"] == state for row in raw_rows)
            for state in ("usable", "empty", "error", "missing")
        },
    }
    if summary != expected_summary:
        return invalid("EtherChannel projection rows do not reconcile to the exact summary")
    return {
        "present": True, "valid": True, "reason": "", "index": index,
        "claimed_subjects": claimed_subjects,
    }


def summarize_etherchannel_baseline(projection: Any,
                                    protocol_assessability: Any,
                                    devices: Any = None) -> dict:
    """Return a receipt-gated observed EtherChannel cutover baseline.

    A row needs a positive subject: observed/malformed group evidence, an interface/config/trunk
    association, or a receipt-owned EtherChannel health row.  Clean empty non-assessed cells are
    omitted.  No configured-member, partner, persistence, bandwidth, or multi-chassis denominator
    is inferred, and the embedded receipt/projection custody remains explicitly unverified.
    """
    projection_view = _validate_etherchannel_projection(projection)
    receipt = _validate_protocol_assessability_receipt(protocol_assessability)
    receipt_subjects = {
        host for host, protocol in receipt["claimed_subjects"] if protocol == "EtherChannel"
    }
    subject_hosts = sorted(
        projection_view["claimed_subjects"] | receipt_subjects,
        key=lambda item: (item.casefold(), item),
    )
    device_root = devices if isinstance(devices, dict) else {}
    rows: List[dict] = []

    for host in subject_hosts:
        findings: List[dict] = []

        def finding(kind: str, code: str, issue: str) -> None:
            item = _ec_finding(kind, code, issue)
            if not any(old["code"] == code and old["issue"] == issue for old in findings):
                findings.append(item)

        receipt_row = receipt["index"].get((host, "EtherChannel")) if receipt["valid"] else None
        projection_row = projection_view["index"].get(host) if projection_view["valid"] else None
        if not receipt["present"]:
            finding("not_verified", "receipt_missing",
                    "Current-run protocol assessability receipt is missing; EtherChannel state is not verified.")
        elif not receipt["valid"]:
            finding("review", "receipt_invalid", receipt["reason"] + ".")
        elif receipt_row is None:
            finding("review", "projection_receipt_contradiction",
                    "EtherChannel subject is absent from the exact protocol receipt denominator.")

        if not projection_view["present"]:
            finding("not_verified", "projection_missing",
                    "Current-run structured EtherChannel projection is missing.")
        elif not projection_view["valid"]:
            finding("review", "projection_invalid", projection_view["reason"] + ".")
        elif projection_row is None:
            finding("review", "projection_receipt_contradiction",
                    "Receipt-declared EtherChannel subject has no structured projection row.")

        receipt_state = _strict_protocol_text(receipt_row.get("state")) if receipt_row else (
            "invalid" if receipt["present"] else "missing"
        )
        emitted = receipt_row.get("health_row_emitted") if receipt_row else (
            True if host in receipt_subjects else None
        )
        capture_state = _strict_protocol_text(projection_row.get("capture_state")) if projection_row else ""
        groups = projection_row.get("groups", []) if projection_row else []
        associations = projection_row.get("associations", []) if projection_row else []
        rejected = projection_row.get("rejected_line_count", 0) if projection_row else 0

        if receipt_row is not None:
            receipt_capture = receipt_row["input_states"]["membership"]
            if projection_row is not None and capture_state != receipt_capture:
                finding("review", "projection_receipt_contradiction",
                        "Structured projection capture state does not reconcile to the receipt membership input.")
            if receipt_state != "assessed":
                if groups and receipt_state in {
                        "captured_no_record", "captured_empty", "capture_error", "not_collected"}:
                    finding("review", "projection_receipt_contradiction",
                            "Observed group rows exist even though the receipt says no EtherChannel health row was emitted.")
                else:
                    finding("not_verified", "receipt_not_assessed",
                            f"Protocol receipt state is {receipt_state}; EtherChannel is not fully assessed.")
            elif not groups:
                finding("review", "assessed_zero_projection",
                        "Receipt says assessed with an emitted health row, but the structured projection has zero groups.")

        if projection_row is not None:
            for item in projection_row["findings"]:
                finding("review", item["code"], item["issue"])
            raw_members: Dict[str, str] = {}
            for group in groups:
                for item in group["findings"]:
                    finding(item["kind"], item["code"], f"{group['group']}: {item['issue']}")
                for member in group["members"]:
                    raw_members[member["interface"]] = group["group"]
                    for item in member["findings"]:
                        finding(item["kind"], item["code"],
                                f"{group['group']} member {member['interface']}({member['flags']}): {item['issue']}")
            for association in associations:
                observed_group = raw_members.get(association["interface"])
                if groups and observed_group is None:
                    finding("review", "association_not_observed",
                            f"Association {association['interface']} -> {association['group']} has no operational "
                            "member row in the captured summary.")
                elif observed_group is not None and observed_group != association["group"]:
                    finding("review", "association_group_mismatch",
                            f"Association {association['interface']} -> {association['group']} conflicts with "
                            f"observed membership in {observed_group}.")

        if any(item["kind"] == "review" for item in findings):
            status = "review"
        elif any(item["kind"] == "not_verified" for item in findings):
            status = "not_verified"
        elif any(item["kind"] == "degraded" for item in findings):
            status = "degraded"
        else:
            status = "assessed"

        group_descriptions = []
        for group in groups:
            member_descriptions = []
            for member in group["members"]:
                label = {
                    "forwarding_observed": "forwarding observed",
                    "delay_lacp_up": "forwarding observed (delay-LACP)",
                    "hot_standby": "hot standby",
                    "non_forwarding_observed": "non-forwarding observed",
                    "waiting_unverified": "waiting; persistence unverified",
                    "standby_unverified": "standby unverified",
                    "contradictory": "contradictory flags",
                    "unclassified": "unclassified",
                }.get(member["state"], member["state"].replace("_", " "))
                member_descriptions.append(f"{member['interface']}({member['flags']}) {label}")
            member_text = ", ".join(member_descriptions) if member_descriptions else "zero observed members"
            group_descriptions.append(
                f"{group['group']} group {group['group_id']}({group['group_flags']}) "
                f"{group['protocol']}: {member_text}"
            )
        association_text = ", ".join(
            f"{item['interface']} -> {item['group']}" for item in associations
        )
        if group_descriptions:
            body = "; ".join(group_descriptions)
            if association_text:
                body += f". Separate association projection: {association_text}"
        elif association_text:
            body = (f"association-only evidence {association_text}; no operational member state is asserted")
        else:
            body = "no trustworthy group/member state could be normalized"
        prefix = ("Embedded/apparent unverified EtherChannel projection" if status in ("review", "not_verified")
                  else "Observed EtherChannel baseline")
        baseline = f"{prefix} for {host}: {body}"
        issue = "; ".join(item["issue"] for item in sorted(
            findings, key=lambda item: (item["code"], item["issue"])
        ))
        if status == "degraded":
            acceptance = (f"PRE-CUTOVER DEGRADED — BLOCKER: {baseline}. {issue} Matching this degraded "
                          "state after cutover is NOT ACCEPTANCE; resolve or explicitly disposition it before "
                          "the window.")
            note = ("Definite local group/member degradation; no configured-member, partner, persistence, "
                    "bandwidth, or multi-chassis denominator was inferred.")
        elif status == "review":
            acceptance = (f"PRE-CUTOVER REVIEW — BLOCKER: {baseline}. {issue} Re-collect and verify exact group, "
                          "protocol, member flags, partner state, and intended membership live before acceptance.")
            note = "EtherChannel evidence is ambiguous; no health conclusion is asserted."
        elif status == "not_verified":
            acceptance = (f"ETHERCHANNEL BASELINE NOT VERIFIED — BLOCKER: {baseline}. {issue} Re-collect and "
                          "verify exact group, protocol, member flags, partner state, and intended membership "
                          "live before acceptance.")
            note = "EtherChannel evidence is not receipt-verified; no health conclusion is asserted."
        else:
            acceptance = (f"{baseline}. Preserve each observed group identity, protocol, exact group flag state, "
                          "and per-member forwarding/hot-standby flag state; explain changes. No configured-member "
                          "or partner denominator was inferred.")
            note = ("Bounded observed local summary baseline; not proof that configured membership, partner state, "
                    "or multi-chassis intent is complete.")

        source_command = _strict_protocol_text(projection_row.get("source_command")) if projection_row else ""
        if source_command:
            command = source_command
        else:
            device = device_root.get(host, {})
            platform = _strict_protocol_text(device.get("platform")) if isinstance(device, dict) else ""
            command = "show port-channel summary" if "nx" in platform.casefold() else "show etherchannel summary"
        rows.append({
            "switch": host,
            "status": status,
            "receipt_state": receipt_state,
            "capture_state": capture_state,
            "health_row_emitted": emitted,
            "group_count": len(groups),
            "member_count": sum(len(group["members"]) for group in groups),
            "groups": groups,
            "associations": associations,
            "findings": sorted(findings, key=lambda item: (item["code"], item["issue"])),
            "rejected_line_count": rejected,
            "command": command,
            "baseline": baseline,
            "acceptance": acceptance,
            "issue": issue,
            "note": note,
            "source_key": (f"etherchannel_projection.rows[{host}] + "
                           f"protocol_assessability.rows[{host},EtherChannel]"),
            "projection_custody": "embedded_unverified",
        })

    by_status = {state: sum(row["status"] == state for row in rows)
                 for state in ("assessed", "degraded", "review", "not_verified")}
    if by_status["degraded"]:
        overall = "degraded"
    elif by_status["review"] or (projection_view["present"] and not projection_view["valid"]):
        overall = "review"
    elif by_status["not_verified"] or not rows:
        overall = "not_verified"
    else:
        overall = "assessed"
    return {
        "schema": "etherchannel_baseline/1",
        "scope": "baseline_observed",
        "status": overall,
        "assessed": bool(rows) and all(row["status"] in ("assessed", "degraded") for row in rows),
        "projection_custody": "embedded_unverified",
        "projection": {
            "present": projection_view["present"],
            "valid": projection_view["valid"],
            "reason": projection_view["reason"],
        },
        "receipt": {
            "present": receipt["present"], "valid": receipt["valid"], "reason": receipt["reason"],
        },
        "rows": rows,
        "summary": {
            "n_subject_devices": len(rows),
            "n_groups": sum(row["group_count"] for row in rows),
            "n_members": sum(row["member_count"] for row in rows),
            "n_associations": sum(len(row["associations"]) for row in rows),
            "n_degraded_groups": sum(group["status"] == "degraded"
                                     for row in rows for group in row["groups"]),
            "n_review_groups": sum(group["status"] == "review"
                                   for row in rows for group in row["groups"]),
            "n_rejected_lines": sum(row["rejected_line_count"] for row in rows),
            "by_status": by_status,
        },
        "limitations": [
            "The baseline covers observed local summary rows; it is not a configured-member or partner denominator.",
            "Association-only evidence carries no operational state and requires a current summary capture.",
            "A single snapshot cannot establish waiting persistence, hashing, capacity, or multi-chassis consistency.",
            "The embedded receipt does not cryptographically bind the projection to raw captures.",
        ],
    }


_ETHERCHANNEL_BASELINE_UNSET = object()


def validate_etherchannel_baseline(
        value: Any, *, projection: Any = _ETHERCHANNEL_BASELINE_UNSET,
        protocol_assessability: Any = _ETHERCHANNEL_BASELINE_UNSET,
        devices: Any = None) -> dict:
    """Authorize only an exact producer-owned ``etherchannel_baseline/1`` value.

    A baseline is an acceptance artifact, not an independently trustworthy assertion.  Both source
    inputs are therefore required together: the validator recomputes the public owner from the exact
    structured projection and protocol receipt and requires whole-object equality.  This prevents a
    snapshot edit from relabelling an ``SD``/``D`` group as assessed or replacing blocker copy with a
    fabricated healthy expectation.  Invalid input never returns caller-controlled rows or leaves.
    """
    present = value is not None

    def invalid(reason: str) -> dict:
        return {
            "present": present,
            "valid": False,
            "reason": reason,
            "source_bound": False,
            "rows": [],
            "index": {},
        }

    if not isinstance(value, dict):
        return invalid("EtherChannel baseline is missing" if not present else
                       "EtherChannel baseline has an unusable root shape")
    if value.get("schema") != "etherchannel_baseline/1" or not isinstance(value.get("rows"), list):
        return invalid("EtherChannel baseline schema or rows are invalid")
    has_projection = projection is not _ETHERCHANNEL_BASELINE_UNSET
    has_receipt = protocol_assessability is not _ETHERCHANNEL_BASELINE_UNSET
    if has_projection != has_receipt:
        return invalid("EtherChannel baseline source inputs are incomplete")
    if not has_projection:
        return invalid("EtherChannel baseline requires its projection and protocol receipt sources")

    expected = summarize_etherchannel_baseline(projection, protocol_assessability, devices=devices)
    if value != expected:
        return invalid("EtherChannel baseline does not reconcile to its exact projection and receipt sources")
    index: Dict[str, dict] = {}
    for row in expected["rows"]:
        host = _strict_protocol_text(row.get("switch")) if isinstance(row, dict) else ""
        if not host or host in index:
            return invalid("EtherChannel baseline contains an invalid or duplicate switch row")
        index[host] = row
    return {
        "present": True,
        "valid": True,
        "reason": "",
        "source_bound": True,
        "rows": expected["rows"],
        "index": index,
    }


def normalize_routing_adjacency_state(protocol: Any, raw_state: Any) -> Tuple[str, Optional[bool]]:
    """Return ``(stable_state, acceptable)`` for one projected routing adjacency.

    ``acceptable`` is ``None`` when the current producer has no bounded classification for the token.
    BGP prefix-count churn, EIGRP uptime, and OSPF DR/BDR role suffixes are deliberately normalized away.
    The EIGRP grammar is anchored: the producer can emit only ``up <uptime>`` and cannot evidence a
    negative neighbor state from the presence-only neighbor table.
    """
    proto = protocol.strip().upper() if isinstance(protocol, str) else ""
    text = raw_state.strip() if isinstance(raw_state, str) else ""
    if not text:
        return "", None
    if proto == "BGP":
        return ("ESTABLISHED", True) if text.isdigit() else (text.upper(), False)
    if proto == "EIGRP":
        return ("UP", True) if re.fullmatch(r"up(?:\s+\S+)?", text, re.IGNORECASE) else (text.upper(), None)
    if proto == "OSPF":
        compact = re.sub(r"\s+", "", text.upper())
        base = compact.split("/", 1)[0]
        return base, base in ("FULL", "2WAY")
    return text.upper(), None


def summarize_routing_baseline(routing_neighbors: Any,
                               protocol_assessability: Any) -> dict:
    """Return a total, receipt-gated baseline for observed OSPF/BGP/EIGRP peer cells.

    Rows are emitted only for a positive subject: a non-empty or malformed routing projection, or a safely
    scoped receipt row claiming that a protocol-health row was emitted.  A clean empty projection with no
    emitted health row is omitted, so a pure-L2 device is neutral rather than falsely healthy or cautionary.
    The embedded ``protocol_assessability/1`` receipt does not cryptographically bind ``routing_neighbors``;
    that custody limitation remains explicit even for structurally assessed rows.
    """
    receipt = _validate_protocol_assessability_receipt(protocol_assessability)
    receipt = dict(receipt)
    receipt["claimed_subjects"] = {
        pair for pair in receipt["claimed_subjects"] if pair[1] in _ROUTING_BASELINE_PROTOCOLS
    }
    projection_root = routing_neighbors if isinstance(routing_neighbors, dict) else None
    projection_pairs: Dict[tuple, dict] = {}
    projection_subjects: set[tuple] = set()

    def pair_view(host: str, protocol: str, raw_value: Any, *, explicitly_present: bool) -> dict:
        result = {"records": {}, "findings": [], "rejected": 0, "available": True}

        def reject(code: str, issue: str) -> None:
            result["rejected"] += 1
            if not any(finding["code"] == code and finding["issue"] == issue
                       for finding in result["findings"]):
                result["findings"].append({"kind": "review", "code": code, "issue": issue})

        if not isinstance(raw_value, list):
            if explicitly_present:
                result["available"] = False
                reject("projection_malformed", "Routing-neighbor projection has an unusable pair shape.")
            return result
        for item in raw_value:
            if not isinstance(item, dict):
                reject("projection_malformed", "Routing-neighbor projection contains a malformed peer record.")
                continue
            peer = _strict_protocol_text(item.get("neighbor"))
            state_raw = _strict_protocol_text(item.get("state"))
            try:
                address = ipaddress.ip_address(peer)
            except ValueError:
                address = None
            if (not peer or not state_raw or address is None
                    or (protocol in ("OSPF", "EIGRP") and address.version != 4)):
                reject("projection_malformed", "Routing-neighbor projection contains an invalid peer identity or state.")
                continue
            interface = _strict_protocol_text(item.get("interface"))
            neighbor_address = _strict_protocol_text(item.get("address"))
            remote_as = _strict_protocol_text(item.get("as"))
            metadata_valid = (
                (protocol == "OSPF" and bool(interface) and bool(neighbor_address))
                or (protocol == "BGP" and bool(re.fullmatch(r"\d+(?:\.\d+)?", remote_as)))
                or (protocol == "EIGRP" and bool(interface))
            )
            if not metadata_valid:
                reject("projection_malformed", "Routing-neighbor projection contains malformed required metadata.")
            if protocol == "OSPF" and neighbor_address:
                try:
                    if ipaddress.ip_address(neighbor_address).version != 4:
                        raise ValueError
                except ValueError:
                    reject("projection_malformed", "OSPF projection contains an invalid neighbor address.")
            peer_key = address.exploded.casefold()
            if peer_key in result["records"]:
                reject(
                    "duplicate_peer_identity",
                    "Routing-neighbor projection contains a colliding peer identity; VRF, process, or address-family "
                    "scope is not available, so live review is required.",
                )
                continue
            state, acceptable = normalize_routing_adjacency_state(protocol, state_raw)
            result["records"][peer_key] = {
                "peer": peer,
                "peer_key": peer_key,
                "state_raw": state_raw,
                "state": state,
                "status": "assessed" if acceptable is True else
                          ("degraded" if acceptable is False else "review"),
                "interface": interface,
                "address": neighbor_address,
                "remote_as": remote_as,
            }
        return result

    if projection_root is not None:
        for host_value, protocols in projection_root.items():
            host = _strict_protocol_text(host_value)
            if not host:
                continue
            if not isinstance(protocols, dict):
                for protocol in _ROUTING_BASELINE_PROTOCOLS:
                    projection_subjects.add((host, protocol))
                    projection_pairs[(host, protocol)] = {
                        "records": {},
                        "findings": [{
                            "kind": "review",
                            "code": "projection_malformed",
                            "issue": "Routing-neighbor projection has an unusable host shape.",
                        }],
                        "rejected": 1,
                        "available": False,
                    }
                continue
            for protocol in _ROUTING_BASELINE_PROTOCOLS:
                key = protocol.lower()
                explicitly_present = key in protocols
                raw_value = protocols.get(key, [])
                if explicitly_present and (not isinstance(raw_value, list) or bool(raw_value)):
                    projection_subjects.add((host, protocol))
                projection_pairs[(host, protocol)] = pair_view(
                    host, protocol, raw_value, explicitly_present=explicitly_present
                )

    subject_pairs = sorted(
        projection_subjects | receipt["claimed_subjects"],
        key=lambda pair: (pair[0].casefold(), pair[0], _ROUTING_BASELINE_PROTOCOLS.index(pair[1])),
    )
    rows: List[dict] = []
    for host, protocol in subject_pairs:
        findings: List[dict] = []

        def finding(kind: str, code: str, issue: str) -> None:
            if not any(existing["code"] == code and existing["issue"] == issue for existing in findings):
                findings.append({"kind": kind, "code": code, "issue": issue})

        receipt_row = receipt["index"].get((host, protocol)) if receipt["valid"] else None
        if not receipt["present"]:
            finding("not_verified", "receipt_missing",
                    "Current-run protocol assessability receipt is missing; the observed peers are not verified.")
        elif not receipt["valid"]:
            finding("review", "receipt_invalid", receipt["reason"] + ".")
        elif receipt_row is None:
            finding("review", "projection_receipt_contradiction",
                    "Routing-neighbor subject is absent from the exact protocol receipt denominator.")

        pair = projection_pairs.get((host, protocol))
        if pair is None:
            pair = {"records": {}, "findings": [], "rejected": 0, "available": False}
            finding("review", "projection_missing",
                    "Routing-neighbor projection is missing for a receipt-declared protocol subject.")
        for item in pair["findings"]:
            finding(item["kind"], item["code"], item["issue"])

        receipt_state = _strict_protocol_text(receipt_row.get("state")) if receipt_row else (
            "invalid" if receipt["present"] else "missing"
        )
        capture_state = _strict_protocol_text(receipt_row.get("capture_state")) if receipt_row else ""
        emitted = receipt_row.get("health_row_emitted") if receipt_row else (
            True if (host, protocol) in receipt["claimed_subjects"] else None
        )
        if receipt_row is not None and receipt_state != "assessed":
            if pair["records"] and receipt_state in {
                    "captured_no_record", "captured_empty", "capture_error", "not_collected"}:
                finding("review", "projection_receipt_contradiction",
                        "Routing peers are present even though the receipt says no assessable peer record was emitted.")
            else:
                finding("not_verified", "receipt_not_assessed",
                        f"Protocol receipt state is {receipt_state}; this subject is not fully assessed.")
        if receipt_row is not None and receipt_state == "assessed" and not pair["records"]:
            finding("review", "assessed_zero_projection",
                    "Receipt says assessed with an emitted health row, but the routing-neighbor projection has zero peers.")

        for peer in pair["records"].values():
            if peer["status"] == "degraded":
                code = "ospf_unacceptable_state" if protocol == "OSPF" else "bgp_not_established"
                finding("degraded", code,
                        f"{protocol} peer {peer['peer']} is observed in {peer['state_raw']} state.")
            elif peer["status"] == "review":
                finding("review", "unclassified_state",
                        f"{protocol} peer {peer['peer']} has a state outside the bounded producer vocabulary.")

        if any(item["kind"] == "review" for item in findings):
            status = "review"
        elif any(item["kind"] == "not_verified" for item in findings):
            status = "not_verified"
        elif any(item["kind"] == "degraded" for item in findings):
            status = "degraded"
        else:
            status = "assessed"

        peers = sorted(pair["records"].values(), key=lambda item: item["peer_key"])
        if status in ("review", "not_verified"):
            for peer in peers:
                peer["status"] = status
        observed = []
        for peer in peers:
            if protocol == "BGP" and peer["state"] == "ESTABLISHED":
                detail = (f"{peer['peer']} Established (observed prefix count {peer['state_raw']}; "
                          "prefix count is informational and not pinned)")
            elif protocol == "EIGRP" and peer["state"] == "UP":
                parts = peer["state_raw"].split(None, 1)
                detail = f"{peer['peer']} UP/present"
                if len(parts) == 2:
                    detail += f" (observed uptime {parts[1]}; uptime is informational and not pinned)"
            else:
                detail = f"{peer['peer']} state {peer['state_raw']}"
            if protocol == "OSPF":
                detail += f" via {peer['interface']} address {peer['address']}"
            elif protocol == "BGP":
                detail += f" remote AS {peer['remote_as']}"
            else:
                detail += f" via {peer['interface']}"
            observed.append(detail)
        if observed:
            prefix = ("Embedded/apparent unverified projection" if status in ("review", "not_verified")
                      else "Observed baseline")
            baseline = f"{prefix} for {protocol} on {host}: " + "; ".join(observed)
        else:
            baseline = f"No trustworthy {protocol} peer baseline could be normalized for {host}."
        issue = "; ".join(item["issue"] for item in findings)
        if status == "degraded":
            acceptance = (f"PRE-CUTOVER DEGRADED — BLOCKER: {baseline}. {issue} Matching this degraded state "
                          "after cutover is NOT ACCEPTANCE; resolve or explicitly disposition it before the window.")
            note = "Definite observed routing degradation; no expected-peer denominator was inferred."
        elif status == "review":
            acceptance = (f"PRE-CUTOVER REVIEW — BLOCKER: {baseline}. {issue} Re-collect and verify the intended "
                          "peer set live before acceptance; do not substitute an ideal healthy count.")
            note = "Routing evidence is ambiguous; no health conclusion is asserted."
        elif status == "not_verified":
            acceptance = (f"ROUTING BASELINE NOT VERIFIED — BLOCKER: {baseline}. {issue} Re-collect and verify "
                          "the intended peer set live before acceptance; do not substitute an ideal healthy count.")
            note = "Routing evidence is not receipt-verified; no health conclusion is asserted."
        else:
            if protocol == "BGP":
                preserve = ("Preserve each observed peer identity in Established state; prefix-count change is "
                            "informational and is not pinned")
            elif protocol == "EIGRP":
                preserve = ("Preserve each observed peer identity as present/UP; uptime change is informational "
                            "and is not pinned")
            else:
                preserve = "Preserve each observed peer identity and acceptable normalized state"
            acceptance = (f"{baseline}. {preserve}, and explain any peer or metadata change; no expected-peer "
                          "count was inferred.")
            note = "Bounded observed adjacency baseline; not proof that the configured peer set is complete."

        rows.append({
            "switch": host,
            "protocol": protocol,
            "status": status,
            "receipt_state": receipt_state,
            "capture_state": capture_state,
            "health_row_emitted": emitted,
            "peer_count": len(peers),
            "rejected_record_count": pair["rejected"],
            "peers": peers,
            "findings": sorted(findings, key=lambda item: (item["code"], item["issue"])),
            "command": _ROUTING_BASELINE_COMMANDS[protocol],
            "baseline": baseline,
            "acceptance": acceptance,
            "issue": issue,
            "note": note,
            "source_key": (f"routing_neighbors.{host}.{protocol.lower()} + "
                           f"protocol_assessability.rows[{host},{protocol}]"),
        })

    by_status = {state: sum(row["status"] == state for row in rows)
                 for state in ("assessed", "degraded", "review", "not_verified")}
    if by_status["degraded"]:
        overall = "degraded"
    elif by_status["review"]:
        overall = "review"
    elif by_status["not_verified"] or not rows:
        overall = "not_verified"
    else:
        overall = "assessed"
    return {
        "schema": "routing_adjacency_baseline/1",
        "scope": "baseline_observed",
        "status": overall,
        "assessed": bool(rows) and all(row["status"] in ("assessed", "degraded") for row in rows),
        "projection_custody": "embedded_unverified",
        "receipt": {
            "present": receipt["present"],
            "valid": receipt["valid"],
            "reason": receipt["reason"],
        },
        "rows": rows,
        "summary": {
            "n_subject_cells": len(rows),
            "n_peers": sum(row["peer_count"] for row in rows),
            "n_degraded_peers": sum(
                peer["status"] == "degraded" for row in rows for peer in row["peers"]
            ),
            "n_rejected_records": sum(row["rejected_record_count"] for row in rows),
            "by_status": by_status,
        },
        "limitations": [
            "The baseline covers observed peers; it is not a configured or expected-neighbor denominator.",
            "An empty or disappearing table is not proof that a protocol or expected peer is absent.",
            "The embedded receipt does not cryptographically bind routing_neighbors to the raw captures.",
            "OSPF 2WAY is context-bounded acceptable evidence, not proof every intended adjacency is Full.",
            "EIGRP neighbor evidence is positive-presence only; the current projection has no negative state model.",
        ],
    }


# =============================================================================
# Protocol-behaviour intelligence (NEW-V3.23.100). Joins the per-(switch,protocol)
# protocol_health rows against the offline protocol-state doctrine (protocol_kb) so an
# abnormal state becomes meaning + likely cause + remediation. The observed state is a
# fact (read from the device); the cause is Inferred. Derived purely from the already-
# computed protocol_health records -- it does NOT re-parse raw device output and does
# NOT mutate protocol_health (keeping that snapshot key byte-stable).
# =============================================================================
def _extract_protocol_states(proto: str, summary: str, detail: str) -> List[str]:
    """Pull the observed abnormal-state token(s) out of a protocol_health row's text (the format
    is produced by compute_protocol_health, so it is stable and under our control)."""
    summary, detail = summary or "", detail or ""
    if proto == "EtherChannel":                      # detail: 'Gi1/0/1(s); Gi1/0/2(RM)'
        # _parse_etherchannel_member_states deliberately keeps the FULL flag token, so scan every
        # CHARACTER of it against the same alphabet compute_protocol_health rates severity from.
        # A single-character class `\(([sDIwH])\)` silently dropped 'M' (min-links not met) and 'f'
        # (aggregator allocation failed) -- both rated High there -- and could not match a combined
        # token like '(RM)' at all, so a bundle the engine called DOWN produced no advisory (#52).
        out: set = set()
        for tok in re.findall(r"\(([A-Za-z]+)\)", detail):
            out.update(ch for ch in tok if ch in _EC_ADVISORY_FLAGS)
        return sorted(out)
    if proto == "OSPF":                              # detail: '10.0.0.1 EXSTART; 10.0.0.2 INIT'
        return sorted({seg.strip().split()[-1] for seg in detail.split(";") if seg.strip()})
    if proto == "BGP":                               # detail: '1.2.3.4 Active; 5.6.7.8 Idle (Admin)'
        out = set()
        for seg in detail.split(";"):
            parts = seg.strip().split(None, 1)
            if len(parts) == 2 and parts[1].strip():
                out.add(parts[1].strip().split()[0])   # first word of the state
        return sorted(out)
    if proto == "VTP":                               # summary: 'mode server; domain X; rev 150'
        m_mode = re.search(r"mode\s+(\w+)", summary, re.IGNORECASE)
        m_rev = re.search(r"rev\s+(\d+)", summary, re.IGNORECASE)
        if (m_mode and m_rev and m_mode.group(1).lower() == "server"
                and int(m_rev.group(1)) >= 100):
            return ["HIGH-REVISION"]
        return []
    if proto == "STP":                               # summary: 'mode rstp; 2 blocked, 1 inconsistent'
        m = re.search(r"(\d+)\s+inconsistent", summary)
        return ["INCONSISTENT"] if (m and int(m.group(1)) > 0) else []
    if proto == "FHRP":                              # detail: 'Vlan10 HSRP Init; Vlan20 VRRP Init'
        # Keep the concrete protocol subtype. HSRP Init/Learn have owned doctrine, while a VRRP/GLBP
        # state with the same spelling must not silently inherit HSRP semantics. Unknown subtypes still
        # reach compute_protocol_intelligence's explicit NOT ASSESSED fallback instead of disappearing.
        out = set()
        for seg in detail.split(";"):
            parts = seg.strip().split()
            if len(parts) >= 3 and parts[-2].upper() in {"HSRP", "VRRP", "GLBP"}:
                role = parts[-1].upper()
                if role in {"INIT", "LEARN"}:
                    out.add(f"{parts[-2].upper()}:{role}")
        return sorted(out)
    return []


def compute_protocol_intelligence(protocol_health: List[dict]) -> List[dict]:
    """For every abnormal protocol state in `protocol_health`, emit an advisory row with the
    meaning / likely cause / remediation from the offline doctrine (protocol_kb). One row per
    (switch, protocol, observed-state). Healthy/unknown states yield nothing. Sorted High first."""
    out: List[dict] = []
    for rec in (protocol_health or []):
        host, proto = rec.get("switch", ""), rec.get("protocol", "")
        for tok in _extract_protocol_states(proto, rec.get("summary", ""), rec.get("detail", "")):
            adv = protocol_kb.advise(proto, tok)
            if adv:
                out.append({"switch": host, "protocol": proto, "state": tok,
                            "severity": adv["severity"], "meaning": adv["meaning"],
                            "likely_cause": adv["likely_cause"], "remediation": adv["remediation"],
                            "confidence": adv["confidence"]})
            elif proto == "EtherChannel" and tok in _EC_BAD_FLAGS:
                # The flag is NON-FORWARDING by this module's own SSOT (_EC_BAD_FLAGS -- the same
                # alphabet compute_protocol_health rated High), but the offline doctrine KB carries
                # no entry for it. Dropping it silently made the advisory surface read clean for a
                # bundle the engine itself called DOWN (#52). Disclose it with the CAUSE explicitly
                # marked not-derived rather than let absence of doctrine read as absence of fault.
                out.append({"switch": host, "protocol": proto, "state": tok,
                            "severity": "High" if tok in _EC_HARD_FLAGS else "Medium",
                            "meaning": f"Member flag '{tok}' — the member is not bundled / not forwarding.",
                            "likely_cause": "NOT ASSESSED — this flag has no entry in the offline "
                                            "protocol-state doctrine (protocol_kb).",
                            "remediation": "Read the member's full flag token in `show etherchannel "
                                           "summary` (and `lacp min-links` / the peer's bundle "
                                           "config) before the window.",
                            "confidence": "observed state = fact; cause NOT assessed (no doctrine entry)"})
            elif proto == "FHRP" and tok.rsplit(":", 1)[-1] in {"INIT", "LEARN"}:
                # The health owner already classified the producer-controlled role as stuck. Preserve
                # that observed fault even when protocol_kb deliberately has no subtype-specific doctrine
                # (for example VRRP:INIT) rather than borrowing HSRP causes or dropping the row.
                subtype, role = tok.split(":", 1)
                out.append({"switch": host, "protocol": proto, "state": tok,
                            "severity": "Medium",
                            "meaning": f"{subtype} group is in the non-forwarding {role} state.",
                            "likely_cause": "NOT ASSESSED -- this subtype/state has no entry in the "
                                            "offline protocol-state doctrine (protocol_kb).",
                            "remediation": f"Inspect the full {subtype} group state, interface status, "
                                           "peer view, and protocol-specific configuration before cutover.",
                            "confidence": "observed state = fact; cause NOT assessed (no doctrine entry)"})
    out.sort(key=lambda r: (_SEV_RANK.get(r["severity"], 9), r["switch"], r["protocol"], r["state"]))
    return out


# =============================================================================
# L4 service map (NEW-V3.23.101). Resolve the L4 ports referenced in ACLs and the
# multicast activity on the fleet to named services/categories via the offline
# port/protocol registry (portdb). Evidence discipline: an ACL port reference is
# DESIGN INTENT (Inferred), NOT proof of active traffic -- there is no flow
# telemetry. Multicast forwarding presence (PIM/mroute on an interface) IS Confirmed,
# but per-group (S,G) classification awaits the richer IGMP/mroute collection.
# =============================================================================
_ACL_PROTOS = {"tcp", "udp", "sctp", "dccp"}

# The authority vocabulary portdb stamps on EVERY registry record (ports and multicast groups
# alike): whether the assignment (the number -> name binding) and the semantics (category /
# broadcast-AV flag) come from the retained authoritative IANA bytes or from this repo's curated
# overlay, plus which overlay disposition produced the row. Named once so the projections below
# and the renderers that label them cannot drift apart.
_REGISTRY_AUTHORITY_KEYS = ("assignment_authoritative", "semantics_authoritative", "overlay_status")
# A multicast group with no registry match carries NO authority claim at all. It is not
# "curated-only" (that is a real registry disposition) -- it is unclassified, and must be
# distinguishable from both.
_UNCLASSIFIED_OVERLAY_STATUS = "unclassified"


def _mcast_authority(mc: Optional[dict]) -> dict:
    """Authority labels for a multicast classification (``None`` = no registry match).

    Coverage-honest: an unmatched group gets ``overlay_status='unclassified'`` with both
    authoritative flags False, so no renderer can read "we could not classify this" as "the
    registry asserts this". A matched group carries portdb's own labels verbatim -- every
    multicast row in the pack is curated (``curated-only``), so both flags are False there
    too, which is exactly the fact that must reach the reader rather than being dropped."""
    src = mc if isinstance(mc, dict) else {}
    out = {k: bool(src.get(k)) for k in _REGISTRY_AUTHORITY_KEYS if k != "overlay_status"}
    out["assignment_source"] = str(src.get("assignment_source") or "")
    out["semantics_source"] = str(src.get("semantics_source") or "")
    out["overlay_status"] = str(src.get("overlay_status") or "") or _UNCLASSIFIED_OVERLAY_STATUS
    return out


def compute_service_map(acls: Dict[str, dict],
                        all_interfaces: Dict[str, Dict[str, InterfaceData]],
                        igmp_groups: Optional[list] = None,
                        ptp: Optional[dict] = None,
                        igmp_queriers: Optional[list] = None,
                        acl_hits: Optional[dict] = None) -> dict:
    """Map ACL L4 port references + fleet multicast activity to named services via portdb.
    Returns {services, categories, acl_rule_count, multicast}. Pure read; tolerant of empty input.

    The optional args fold in the richer collection (NEW-V3.23.102) when present, else stay inert:
      igmp_groups   : [group_ip,...] from IGMP/snooping/mroute -> classified into multicast groups
      acl_hits      : {"port:proto": matches} from ACL hit-counts -> upgrades a service's evidence to Confirmed
      ptp           : PTP clock/grandmaster health {device_type, grandmaster, offset_ns, locked, ...}
      igmp_queriers : [{vlan, querier},...] the L2 querier per VLAN"""
    acl_hits = acl_hits or {}
    svc: Dict[Tuple[int, str], dict] = {}     # (port, proto) -> {service, category, broadcast, refs, hosts}
    mcast_groups: Dict[str, dict] = {}        # multicast group ip -> classification
    rule_count = 0
    for host, named in (acls or {}).items():
        for _name, rules in (named or {}).items():
            for r in (rules or []):
                if not isinstance(r, dict):          # tolerate a stray non-dict rule entry
                    continue
                rule_count += 1
                proto = (r.get("proto") or "").lower()
                lookup_proto = proto if proto in _ACL_PROTOS else "udp"
                for operand in (r.get("sport"), r.get("dport")):
                    val = operand.get("val") if isinstance(operand, dict) else None
                    if not val:
                        continue
                    rec = portdb.service_for_port(val, lookup_proto)
                    if not rec:
                        continue
                    key = (val, lookup_proto)
                    # Carry the WHOLE registry record forward, not a hand-picked three of its
                    # fourteen keys. portdb labels every record with its own authority
                    # (assignment_authoritative / semantics_authoritative / overlay_status /
                    # *_source / note / aliases): projecting a named subset dropped all of it one
                    # hop from the lookup, so a curated-only, non-authoritative classification
                    # (e.g. 4440/udp "Dante-audio") reached the workbook indistinguishable from an
                    # IANA-assigned one -- and the ACL-hit "Confirmed" evidence class then read as
                    # if it confirmed the SERVICE NAME too. A projection is a named subset standing
                    # in for the class; splatting the record makes any future registry field flow
                    # through automatically instead of silently vanishing here.
                    # Copy the record's own list values as well: `rec` is the shared, process-lived
                    # registry cache entry, and a downstream consumer mutating a list it handed out
                    # would poison the registry for every later lookup. Only fires once per distinct
                    # (port, proto) thanks to setdefault, so it is not on the per-rule hot path.
                    e = svc.setdefault(key, dict({k: (list(v) if isinstance(v, list) else v)
                                                  for k, v in rec.items()}, refs=0, hosts=set()))
                    e["refs"] += 1
                    e["hosts"].add(host)
                for addr in (r.get("src"), r.get("dst")):
                    ip = addr.get("ip") if isinstance(addr, dict) else None
                    if ip and ip not in mcast_groups:
                        mc = portdb.classify_multicast(ip)
                        if mc:
                            mcast_groups[ip] = dict(_mcast_authority(mc),
                                                    group=ip, name=mc.get("group", ""),
                                                    category=mc["category"],
                                                    broadcast=mc["broadcast"],
                                                    source="ACL reference")

    def _evidence(port, proto):
        m = acl_hits.get(f"{port}:{proto}")
        if m:
            return f"Confirmed (ACL hit-counts: {m} matches)"
        return "Inferred (ACL design intent -- not active traffic; no flow telemetry)"

    # `hosts` is the only working-set key (a set -- not JSON-serialisable); everything else the
    # registry stamped on the record rides through to the renderers, including the authority
    # labels. `evidence_class` describes the TRAFFIC evidence (an ACL reference vs an ACL hit
    # count) and says nothing about whether the service NAME is authoritative -- the two are
    # independent, which is precisely why both must be published.
    services = sorted(
        (dict({k: v for k, v in e.items() if k != "hosts"},
              port=p, proto=pr, host_count=len(e["hosts"]), evidence_class=_evidence(p, pr))
         for (p, pr), e in svc.items()),
        key=lambda s: (-s["refs"], s["port"]))

    cat_refs: Dict[str, int] = {}
    for s in services:
        cat_refs[s["category"]] = cat_refs.get(s["category"], 0) + s["refs"]
    categories = [{"category": c, "refs": n}
                  for c, n in sorted(cat_refs.items(), key=lambda kv: -kv[1])]

    # fold in IGMP/snooping/mroute group census (NEW-V3.23.102) -- classify each via the registry
    for grp in (igmp_groups or []):
        if grp not in mcast_groups:
            mc = portdb.classify_multicast(grp)
            # `category` defaults to the generic "Multicast" when nothing matched -- a placeholder,
            # not a classification. The authority block below is what tells the two apart.
            mcast_groups[grp] = dict(_mcast_authority(mc),
                                     group=grp, name=(mc or {}).get("group", ""),
                                     category=(mc or {}).get("category", "Multicast"),
                                     broadcast=bool((mc or {}).get("broadcast")),
                                     source="IGMP/mroute")

    active_ifaces, active_switches = 0, set()
    for host, ports in (all_interfaces or {}).items():
        for _p, d in (ports or {}).items():
            if getattr(d, "multicast_info", ""):
                active_ifaces += 1
                active_switches.add(host)

    multicast = {
        "active_interfaces": active_ifaces,
        "active_switch_count": len(active_switches),
        "active_switches": sorted(active_switches)[:20],
        "classified_groups": sorted(mcast_groups.values(), key=lambda g: g["group"]),
        # per-group (S,G)/IGMP membership lights up on the new collection; Unknown until then
        "group_level_collected": bool(igmp_groups),
        "ptp": ptp or {},
        "igmp_queriers": igmp_queriers or [],
    }
    return {"services": services, "categories": categories,
            "acl_rule_count": rule_count, "multicast": multicast}


def compute_ptp_readiness(service_map: dict) -> List[dict]:
    """NEW-V3.23.108: PTP / media-timing readiness findings derived from the service map, shaped like
    punch-list items so they fold into the consolidated action list. For a broadcast fabric
    (SMPTE ST 2110 / AES67 / Dante) sub-microsecond timing typically needs PTP boundary-/transparent-
    clock mode on the media-path switches. Flags when PTP is present but NO switch is an operational
    boundary clock (timing distributed as plain multicast, not boundary-clocked), or a partial mix.
    Returns [] when no PTP data. Evidence-disciplined: the switch's clock state is Confirmed; whether
    media timing depends on it here is Inferred (hence Medium/Low, not High)."""
    mc = (service_map or {}).get("multicast") or {}
    ptp = mc.get("ptp") or {}
    if not ptp:
        return []
    oper = sorted(h for h, v in ptp.items() if (v or {}).get("operational"))
    dormant = sorted(h for h, v in ptp.items() if not (v or {}).get("operational"))
    ptp_mcast = [g.get("group") for g in (mc.get("classified_groups") or [])
                 if "PTP" in (g.get("name") or "")]
    out: List[dict] = []
    if dormant and not oper:
        detail = (f"PTP is configured on {len(ptp)} switch(es) but NONE are active boundary/transparent "
                  "clocks (Device Type Unknown / 0 active ports / no parent clock). "
                  + (f"PTP multicast ({', '.join(ptp_mcast)}) IS flowing in the fabric, so timing is "
                     "distributed as plain multicast, not boundary-clocked. " if ptp_mcast else "")
                  + "SMPTE ST 2110 / AES67 / Dante typically require boundary-clock mode on the media path.")
        out.append({"severity": "Medium", "category": "Timing/PTP", "devices": dormant,
                    "title": "PTP enabled but not boundary-clocked (media timing at risk)",
                    "detail": detail,
                    "remediation": "Confirm whether the media fabric requires PTP boundary/transparent-clock "
                                   "mode; if so, enable it on the media-path switches and verify clock lock "
                                   "(offset within spec) before the cutover."})
    elif dormant and oper:
        out.append({"severity": "Low", "category": "Timing/PTP", "devices": dormant,
                    "title": f"PTP dormant on {len(dormant)} switch(es) ({len(oper)} active boundary clock(s))",
                    "detail": (f"{len(oper)} switch(es) act as PTP boundary/transparent clocks; "
                               f"{len(dormant)} have PTP configured but dormant (Device Type Unknown / "
                               "0 active ports)."),
                    "remediation": "Confirm the dormant switches are not on a media-timing path; enable "
                                   "boundary-clock mode where ST 2110/AES67/Dante timing must traverse them."})
    return out


# =============================================================================
# Multicast / media-flow + timing intelligence (NEW-V3.23.115). Deepen the already-classified multicast
# groups + IGMP queriers + PTP clocks in service_map.multicast into media-fabric intelligence with concrete,
# standards-grounded checks. Group / MAC / VLAN level only -- per-(S,G) OIL is not collected (not faked).
# =============================================================================
_MCAST_ONAIR_CATS = {"Broadcast-AV"}


def _mcast_mac(ip: str) -> str:
    """The Ethernet multicast MAC an IPv4 group maps to (RFC 1112): 01:00:5e + the low 23 bits of the group.
    IPv4->MAC is 32:1, so groups differing only ABOVE the low 23 bits collapse to the SAME MAC and a
    MAC-level switch forwards them together (the RFC 4541 snooping pitfall). '' if not dotted IPv4 multicast."""
    try:
        o = [int(p) for p in str(ip or "").strip().split(".")]
    except ValueError:
        return ""
    if len(o) != 4 or not (224 <= o[0] <= 239) or any(not 0 <= b <= 255 for b in o):
        return ""
    return "01:00:5e:%02x:%02x:%02x" % (o[1] & 0x7f, o[2], o[3])


def compute_multicast_intelligence(service_map: Optional[dict] = None,
                                   all_interfaces: Optional[Dict[str, Dict[str, InterfaceData]]] = None) -> dict:
    """NEW-V3.23.115: media-fabric intelligence over service_map.multicast (classified groups + IGMP queriers
    + PTP clocks). Concrete checks: MAC aliasing (RFC 4541 -- IPv4 multicast is 32:1 lossy into L2 MACs, so
    aliased groups cross-deliver), IGMP querier coverage (RFC 4541 -- a multicast VLAN with no querier floods/
    blackholes), and the PTP timing tree (SMPTE ST 2059). Pure read; deterministic; tolerant of empty input.
    Group/MAC/VLAN level -- per-(S,G) OIL is not collected. Returns {groups, mac_aliases, querier, ptp,
    summary, risks}."""
    from collections import defaultdict
    mc = ((service_map or {}).get("multicast")) or {}
    raw = mc.get("classified_groups") or []
    ptp = mc.get("ptp") or {}
    queriers = mc.get("igmp_queriers") or []

    def _ipk(ip):
        try:
            return tuple(int(o) for o in str(ip).split("."))
        except ValueError:
            return (999,)

    groups: List[dict] = []
    by_mac: Dict[str, list] = defaultdict(list)
    for g in raw:
        if not isinstance(g, dict):
            continue
        ip = g.get("group", "")
        mac = _mcast_mac(ip)
        on_air = bool(g.get("broadcast")) or (g.get("category") or "") in _MCAST_ONAIR_CATS
        # `on_air` is derived ENTIRELY from the curated broadcast/category fields, so it inherits
        # their authority -- carry the labels through instead of laundering a curated claim into a
        # bare boolean. Every multicast row in the pack is curated-only, so `on_air` is never
        # semantically authoritative; that is a fact about the evidence, and it drives severity below.
        _auth = _mcast_authority(g)
        rec = {"group": ip, "name": g.get("name", ""), "category": g.get("category", ""),
               "broadcast": bool(g.get("broadcast")), "on_air": on_air,
               "on_air_authoritative": bool(on_air and _auth["semantics_authoritative"]),
               "source": g.get("source", ""), "mac": mac, **_auth}
        groups.append(rec)
        if mac:
            by_mac[mac].append(rec)
    groups.sort(key=lambda r: _ipk(r["group"]))

    mac_aliases: List[dict] = []
    for mac, recs in by_mac.items():
        if len(recs) > 1:
            mac_aliases.append({"mac": mac, "groups": sorted((r["group"] for r in recs), key=_ipk),
                                "names": sorted({r["name"] for r in recs if r["name"]}),
                                "has_av": any(r["on_air"] for r in recs),
                                # Does an AUTHORITATIVE source say one of these is on-air media, or
                                # only this repo's curated overlay? The severity below turns on
                                # has_av, so the basis of has_av has to travel with it.
                                "has_av_authoritative": any(r.get("on_air_authoritative")
                                                            for r in recs)})
    mac_aliases.sort(key=lambda a: (not a["has_av"], a["mac"]))

    # querier coverage: multicast-active SVI VLANs (PIM/mroute on a VlanN interface) lacking an IGMP querier
    q_vlans = {str(q.get("vlan", "")).strip() for q in queriers
               if isinstance(q, dict) and str(q.get("vlan", "")).strip()}
    mcast_vlans: set = set()
    for _host, ifaces in (all_interfaces or {}).items():
        for port, d in (ifaces or {}).items():
            if getattr(d, "multicast_info", ""):
                m = re.match(r"^Vlan(\d+)$", str(port), re.I)
                if m:
                    mcast_vlans.add(m.group(1))
    gap_vlans = sorted(mcast_vlans - q_vlans, key=lambda v: int(v))
    querier = {"n_querier_vlans": len(q_vlans),
               "multicast_vlans": sorted(mcast_vlans, key=lambda v: int(v)), "gap_vlans": gap_vlans}

    # PTP timing tree (ST 2059)
    oper = sorted(h for h, v in ptp.items() if (v or {}).get("operational"))
    dormant = sorted(h for h, v in ptp.items() if not (v or {}).get("operational"))
    gms = sorted({(v or {}).get("grandmaster") for v in ptp.values() if (v or {}).get("grandmaster")})
    ptp_tree = {"n_clocks": len(ptp), "n_operational": len(oper), "n_dormant": len(dormant),
                "grandmasters": gms, "operational": oper, "dormant": dormant}

    risks: List[dict] = []
    for a in mac_aliases:
        # The OVERLAP itself is arithmetic on the observed group addresses -- Confirmed, and the
        # sole reason this is a finding at all. The Broadcast-AV promotion from Medium to High is
        # NOT: it rests on the offline registry's curated media semantics, which carry no
        # authoritative source. Keep the higher severity (under-reporting a possible on-air impact
        # is the worse error) but publish the basis, so a reader is never told a curated guess and
        # an IANA-assigned fact in the same voice.
        _av_basis = ("registry semantics (authoritative source)" if a["has_av_authoritative"]
                     else "curated offline registry semantics — NOT an authoritative source")
        risks.append({"kind": "mac-alias", "severity": "High" if a["has_av"] else "Medium",
            "severity_basis": (f"raised to High because a member group is classified Broadcast-AV / on-air "
                               f"by {_av_basis}; the MAC overlap itself is arithmetic on the observed "
                               f"group addresses and is not in question."
                               if a["has_av"] else
                               "Medium: no member group is classified as on-air media. The MAC overlap "
                               "itself is arithmetic on the observed group addresses and is not in question."),
            "evidence_confidence": ("observed overlap = fact; on-air classification = "
                                    + ("authoritative" if a["has_av_authoritative"] else "curated, unverified")
                                    if a["has_av"] else "observed overlap = fact"),
            "title": f"Multicast MAC-address overlap on {a['mac']}",
            "detail": (f"Groups {', '.join(a['groups'])} all map to L2 MAC {a['mac']} (IPv4 multicast is 32:1 "
                       "into Ethernet MACs). A switch that constrains multicast at the MAC level forwards them "
                       "together — receivers of one group see the other's traffic"
                       + (f" (and at least one is classified Broadcast-AV / on-air by {_av_basis} — "
                          "confirm the group's real use before acting on the severity)."
                          if a["has_av"] else ".")),
            "remediation": "Re-address one overlapping group so the low-23-bit MAC differs (avoid 224.x/225.x… "
                           "239.x families that alias), or use IGMPv3 source-specific forwarding end-to-end.",
            "standard": "RFC 4541 / RFC 1112"})
    if gap_vlans:
        risks.append({"kind": "querier-gap", "severity": "High",
            "title": f"{len(gap_vlans)} multicast VLAN(s) without an IGMP querier",
            "detail": (f"VLAN(s) {', '.join(gap_vlans)} carry multicast (PIM/mroute on the SVI) but no IGMP "
                       "querier was seen — membership times out and the switch floods or blackholes the group."),
            "remediation": "Configure exactly one IGMP (snooping) querier per multicast VLAN (lowest IP wins).",
            "standard": "RFC 4541"})
    if ptp and not oper:
        risks.append({"kind": "ptp-dormant", "severity": "Medium",
            "title": f"PTP present on {len(ptp)} switch(es) but no active boundary clock",
            "detail": ("Every PTP switch is dormant (Device Type Unknown / 0 ports / no parent) — timing is "
                       "distributed as plain multicast, which does not scale for ST 2110 / AES67 / Dante."),
            "remediation": "Enable PTP boundary-clock mode on the media-path switches and verify lock; see the "
                           "PTP/media-timing punch-list item.", "standard": "SMPTE ST 2059"})

    summary = {"n_groups": len(groups), "n_av_groups": sum(1 for g in groups if g["on_air"]),
               # How many of those on-air classifications rest on an AUTHORITATIVE source. On the
               # shipped pack this is 0 (every multicast row is curated), and a headline that says
               # "44 broadcast/AV group(s)" without it presents a curated judgement as a measurement.
               "n_av_groups_authoritative": sum(1 for g in groups if g.get("on_air_authoritative")),
               "n_unclassified_groups": sum(1 for g in groups
                                            if g.get("overlay_status") == _UNCLASSIFIED_OVERLAY_STATUS),
               "n_mac_clashes": len(mac_aliases), "n_querier_gaps": len(gap_vlans),
               "n_mcast_vlans": len(mcast_vlans),   # collected multicast SVIs -> 0 = querier coverage NOT assessable
               "n_active_switches": mc.get("active_switch_count", 0),
               "n_active_interfaces": mc.get("active_interfaces", 0),
               "n_ptp_clocks": len(ptp), "n_ptp_dormant": len(dormant)}
    return {"groups": groups, "mac_aliases": mac_aliases, "querier": querier, "ptp": ptp_tree,
            "summary": summary, "risks": risks}


# =============================================================================
# Physical-health compute helpers (PHASE 2.7 step 17). The pure parsers
# (parse_interface_phy / _classify_media / _is_physical_port / _parse_poe_watts)
# live in parse.py; these derive metrics from already-parsed records / the model.
# =============================================================================
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
       uplink_ports       : set of (host, local_port) facing another switch
       single_fiber_ports : set of (host, local_port) where that port is the host's ONLY
                            inter-switch link and it is not a port-channel (no L1 redundancy).

    Reads `model['offscan_links']` as well as `model['links']`: an uplink to a device that was never
    collected is still a physical uplink, and it is exactly as un-redundant as one to a scanned peer.
    Deriving L1 redundancy from `links` alone (both ends scanned) meant an access switch homed to an
    uncollected core contributed nothing at all, so `single_fiber` came back empty and readiness
    check 1 reported "no single-homed switch" for the most common real topology (#14)."""
    by_host: Dict[str, List[Tuple[str, str, bool]]] = {}
    for l in model["links"]:                                   # links: {a,ap,b,bp,is_pc,da,db}
        if l.get("ap"):
            by_host.setdefault(l["a"], []).append((l["b"], l["ap"], bool(l["is_pc"])))
        if l.get("bp"):
            by_host.setdefault(l["b"], []).append((l["a"], l["bp"], bool(l["is_pc"])))
    _offscan = model.get("offscan_links")                      # offscan: {host,port,far,is_pc,d}
    for l in (_offscan if isinstance(_offscan, list) else []):  # absent on a foreign/older model
        if l.get("port"):
            by_host.setdefault(l["host"], []).append((l["far"], l["port"], bool(l.get("is_pc"))))
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


# =============================================================================
# Cross-layer dependency map + correlation rules (CL-01..CL-10). build_dependency_map
# bundles the L1/L3/topology facts; compute_cross_layer_correlations applies the rules.
# The _CL_FILL map + CROSS_LAYER_SHEET_NAME + write_cross_layer_sheet stay in the monolith.
# =============================================================================
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
    nofhrp_vlans: Dict = {}   # NEW-V3.23.10 (mypy var-annotated): typed out of the tuple-unpack
    sole_gw, tracked_down, fhrp_hosts, gw_switches = {}, set(), set(), set()
    fhrp_vlans = set()
    # `tracked_down` is a FLEET-WIDE host set with no VLAN dimension. CL-04 paired it against every
    # FHRP VLAN, so one device fault became N identical High findings / punch-list rows / XL score
    # deductions (#51). The l3_forwarding row it comes from is per-(switch, VLAN), so keep that join
    # key here; `tracked_down` stays as-is because CL-09 legitimately wants the host set.
    tracked_down_vlans: Dict = {}
    for rec in (l3_forwarding or []):
        vid, host, r = rec.get("vlan"), rec.get("switch"), rec.get("risk", "")
        gw_switches.add(host)
        if "single-gateway" in r:
            sole_gw[vid] = host
        if "no-FHRP" in r:
            nofhrp_vlans.setdefault(vid, []).append(host)
        if "tracked-object-down" in r:
            tracked_down.add(host)
            tracked_down_vlans.setdefault(vid, set()).add(host)
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
            "tracked_down_vlans": tracked_down_vlans,
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

    # CL-02 (L2+L3): transit articulation between endpoints and their gateway. AGGREGATED per host
    # (NEW-V3.23.90): dep["articulation"] is a set of (host, vid); the old per-pair emission produced
    # ~13k near-identical rows (95% of ALL cross-layer findings) that buried the genuine criticals,
    # made the punch-list it feeds unreadable, and saturated the health score's XL cap on every
    # articulation switch (whole fleet -> no band discrimination). One row per articulation switch,
    # listing its VLANs. CL-09's stacked-SPOF detection reads dep["articulation"] directly, not these
    # emitted rows, so its L2 signal is unaffected.
    art_by_host: Dict[str, set] = {}
    for (h, vid) in dep["articulation"]:
        art_by_host.setdefault(h, set()).add(vid)
    for h in sorted(art_by_host):
        vl = sorted(art_by_host[h])
        add("CL-02", "High", "L2+L3",
            f"{h}: only L2 transit to the gateway for {len(vl)} VLAN(s)",
            f"Removing {h} partitions endpoints in {len(vl)} VLAN(s) ({_vlan_list_summary(vl)}) "
            f"from their L3 gateway over forwarding links.",
            "Add a redundant path, or migrate this switch in the same wave as its dependents.", [h])

    # CL-03 (L2+L3): sole gateway, no FHRP (structural L3 SPOF)
    for vid, gw in sorted(dep["sole_gw"].items()):
        add("CL-03", "High", "L2+L3",
            f"VLAN {vid}: sole gateway {gw} with no FHRP",
            f"{gw} is the only in-scan L3 gateway for VLAN {vid}; loss drops the default gateway "
            f"for every VLAN {vid} host.",
            "Add an FHRP peer (HSRP/VRRP/GLBP) or confirm a redundant off-scan gateway.", [gw])

    # CL-04 (L3): FHRP gateway with a down tracked object. JOINED ON VLAN (#51): the fleet-wide
    # `tracked_down` host set carries no VLAN dimension, so pairing it with every FHRP VLAN turned
    # ONE device fault into N identical High findings -- N punch-list rows and N XL deductions that
    # saturate the cross-layer cap in compute_health_scores. `tracked_down_vlans` keeps the
    # (VLAN -> hosts) join key from the l3_forwarding row the fault came from. Absent key (a
    # foreign / pre-existing dep map): no VLAN attribution is available, so emit nothing rather
    # than re-inflate -- `tracked_down` is still surfaced via CL-09.
    tdv = dep.get("tracked_down_vlans") or {}
    for vid in sorted(dep["fhrp_vlans"]):
        down_hosts = sorted(tdv.get(vid) or ())
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

    # CL-06 (L1+L2): single-member port-channel on an uplink. AGGREGATED per host (NEW-V3.23.90):
    # one row per switch listing its single-member port-channels, not one row per port-channel
    # (same cry-wolf pattern as CL-02 on switches that bundle many one-member POs).
    up_hosts = {uh for (uh, _p) in up}
    smpc_by_host: Dict[str, set] = {}
    for (h, po) in dep["single_member_pc"]:
        if h in up_hosts:
            smpc_by_host.setdefault(h, set()).add(po)
    for h in sorted(smpc_by_host):
        pos = sorted(smpc_by_host[h])
        shown = ", ".join(pos[:12]) + (f" (+{len(pos) - 12} more)" if len(pos) > 12 else "")
        add("CL-06", "Medium", "L1+L2",
            f"{h}: {len(pos)} single-member port-channel(s)",
            f"{shown} on {h} bundle only one physical link each - the aggregation provides no L1 redundancy.",
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


# =============================================================================
# Flow trace: derive an L1->L3 path between two endpoint IPs and score its
# resilience. Pure derivation over already-parsed InterfaceData + the shared model
# (no new collection, no L4). The _RISK_FILL/_RISK_RANK maps + sheet-name constant
# + write_flow_trace_sheet stay in the monolith (excel).
# =============================================================================
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
            # V3.23.141: end_host_ip may be a MAC-aligned list (V3.23.140) -> match ANY of its addresses
            if ip in [x.strip() for x in (d.end_host_ip or "").split(",") if x.strip() and x.strip() != "-"]:
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
                            "next_hop": d.route_next_hop, "prefix": d.subnet_primary_route,
                            "vrf": getattr(d, "vrf", "") or ""})    # carried so inter-VLAN can honour VRF isolation
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
            same_router_dst_gw = next((g for g in (dst_gws or [])
                                       if g["host"] == reachable_src_gw["host"]), None)
            same_router = bool(same_router_dst_gw)
            src_vrf = (reachable_src_gw.get("vrf") or "").strip().lower()
            dst_vrf = (same_router_dst_gw.get("vrf") or "").strip().lower() if same_router_dst_gw else ""
            if same_router and src_vrf != dst_vrf and (src_vrf or dst_vrf):
                # Both SVIs on the same router but in DIFFERENT VRFs and no route leak is observed -> inter-VLAN
                # traffic does NOT cross the VRF boundary; the flow is L3-isolated. This is a definitive block per
                # the collected VRF assignment, NOT 'routed locally' -- the old verdict was a false-health
                # over-claim from data the engine itself collected (audit-2 #1).
                partitioned = True
                _add("L3", reachable_src_gw["host"], reachable_src_gw["host"], "",
                     f"BLOCKED at VRF boundary: VLAN {src_vid} SVI in VRF '{src_vrf or 'default'}', VLAN {dst_vid} "
                     f"SVI in VRF '{dst_vrf or 'default'}' -- inter-VLAN routing does not cross VRFs "
                     "(no route leak observed in the collected config)", spof=False)
            elif same_router:
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


def compute_flow_paths(all_interfaces: Dict[str, Dict[str, InterfaceData]],
                       endpoint_identity: Optional[list] = None, max_flows: int = 8) -> dict:
    """NEW-V3.23.126: representative end-to-end flow paths for the workbook + runbook — the STATIC twin
    of the explorer's interactive Flow Simulator. Reuses trace_full_flow() over a deterministic, curated
    set of flows: one representative endpoint per VLAN (the lowest IP, with its inferred class), paired
    across consecutive VLANs to exercise the routed inter-subnet path, each scored for SPOF / risk.
    Deterministic in its SELECTION (sorted VLANs, lowest-IP rep); the hop tie-break inside trace_full_flow
    is topology-dependent, so this output is intentionally NOT embedded in the frozen golden snapshot.
    Returns {flows:[{label, summary, hops}], summary:{n_flows, n_at_risk, n_partitioned}}."""
    ident = endpoint_identity or []
    by_vlan: Dict[int, dict] = {}                       # vlan -> representative endpoint (lowest IP)
    for r in ident:
        ip = (r.get("ip") or "").strip()
        vlan = str(r.get("vlan") or "").strip()
        if not ip or not vlan.isdigit():
            continue
        parts = ip.split(".")
        key = (tuple(int(o) for o in parts) if len(parts) == 4 and all(o.isdigit() for o in parts)
               else (999, 999, 999, 999))
        v = int(vlan)
        cur = by_vlan.get(v)
        if cur is None or key < cur["key"]:
            by_vlan[v] = {"ip": ip, "host": r.get("host", ""),
                          "cls": (r.get("endpoint_class") or ""), "key": key}
    vlans = sorted(by_vlan)
    flows: List[dict] = []
    seen: set = set()

    def _lbl(v, ep):
        cls = ep["cls"]
        return f"VLAN {v}" + (f" ({cls})" if cls and cls != "Unknown" else "")

    for i in range(len(vlans) - 1):
        if len(flows) >= max_flows:
            break
        a, b = by_vlan[vlans[i]], by_vlan[vlans[i + 1]]
        if a["ip"] == b["ip"] or (a["ip"], b["ip"]) in seen:
            continue
        seen.add((a["ip"], b["ip"]))
        ft = trace_full_flow(a["ip"], b["ip"], all_interfaces)
        flows.append({"label": f"{_lbl(vlans[i], a)} → {_lbl(vlans[i + 1], b)}",
                      "summary": ft["summary"], "hops": ft["hops"]})

    return {"flows": flows,
            "summary": {"n_flows": len(flows),
                        "n_at_risk": sum(1 for f in flows if f["summary"].get("risk") in ("HIGH", "CRITICAL")),
                        "n_partitioned": sum(1 for f in flows if f["summary"].get("partitioned"))}}


def stp_root_findings(all_stp_roots: Dict[str, dict],
                      all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> dict:
    """NEW-V3.23.62: cross-switch STP root-bridge analysis over the per-switch
    `parse_spanning_tree_root` data. Surfaces two design smells a migration inherits:
    (1) ACCIDENTAL root -- a VLAN whose root runs the default bridge priority
    (32768 + sys-id-ext), i.e. nobody deliberately elected a root, so it was won on a
    MAC tiebreak and can move unexpectedly on a cutover; and (2) root / gateway
    MISALIGNMENT -- the VLAN's root bridge is not a switch that hosts its L3 gateway
    SVI, so intra-VLAN traffic to the default gateway hairpins through the root. Pure
    derivation; no new collection. Returns {accidental:[...], misaligned:[...]}."""
    root_of: Dict[str, str] = {}
    for host in sorted(all_stp_roots or {}):
        for vlan, r in (all_stp_roots[host] or {}).items():
            if r.get("is_root"):
                root_of.setdefault(vlan, host)
    gw_of: Dict[str, set] = {}
    for host, ifaces in (all_interfaces or {}).items():
        for port, d in (ifaces or {}).items():
            m = re.match(r"^Vlan0*(\d+)$", port, re.IGNORECASE)
            if m and (getattr(d, "svi_ip", "") or "").strip():
                gw_of.setdefault(m.group(1), set()).add(host)
    accidental: List[dict] = []
    misaligned: List[dict] = []
    for vlan, host in root_of.items():
        rec = all_stp_roots[host][vlan] or {}
        # MST keys are INSTANCE numbers, not VLAN ids: the 32768+vlan accidental-root test would fire on
        # instance 0 at default priority (a non-existent 'VLAN 0' cry-wolf), and the gateway-misalignment join
        # (keyed on real VLAN ids) can never match an instance key. Both checks are PVST/RPVST-only.
        if rec.get("is_mst"):
            continue
        prio = rec.get("root_priority")
        # default bridge priority won on a MAC tiebreak. With extended-system-id ON (the common case) the field
        # reads 32768 + sys-id-ext(=vlan); with 'no spanning-tree extend system-id' (legacy IOS) it reads a BARE
        # 32768 -- accept BOTH, else a legacy ext-id-off accidental root is silently missed (audit-3 #14). A real
        # PVST vlan>=1 with ext-id ON never lands on exactly 32768, so the bare-32768 arm adds no false positive.
        if isinstance(prio, int) and prio in (32768, 32768 + int(vlan)):
            accidental.append({"vlan": vlan, "host": host, "priority": prio})
        gws = gw_of.get(vlan)
        if gws and host not in gws:
            misaligned.append({"vlan": vlan, "root": host, "gateways": sorted(gws)})
    accidental.sort(key=lambda x: int(x["vlan"]))
    misaligned.sort(key=lambda x: int(x["vlan"]))
    return {"accidental": accidental, "misaligned": misaligned}


# =============================================================================
# Endpoint identity & vendor intelligence (NEW-V3.23.95). Passive classification of access-port
# endpoints from already-collected signals -- MAC OUI (-> vendor, a directly-evidenced fact), the
# operator description, the CDP neighbour platform, and the collector's own endpoint_type -- into a
# migration-useful CLASS with an explicit CONFIDENCE label (the skill doctrine: the vendor is a fact;
# the role inferred from it is Inferred, never Confirmed). The rule base encodes domain research
# (broadcast A/V + IT vendors, hypervisor platforms, NIC/UPS makers); it is data, not magic.
# =============================================================================
# Description keyword -> (class, confidence-rank). Rank 2 = Inferred-high, 1 = Inferred-medium.
_EP_DESC_RULES = [
    (re.compile(r"cam(era)?|cctv|\bptz\b|surveill", re.I), "Camera", 2),
    (re.compile(r"dante|aes67|intercom|\bmic\b|\baudio\b", re.I), "Audio (Dante/AES67)", 2),
    # '2110' anchored to the SMPTE ST-2110 standard (st/smpte 2110, or 2110-<part> like 2110-20) -- the bare token
    # matched any room/rack/asset/VLAN number ('RM2110','AP-2110') and mislabeled ordinary endpoints (audit-2 #2).
    (re.compile(r"\bst[\s-]?2110\b|\bsmpte[\s-]?2110\b|\b2110-\d|\bsdi\b|playout|ingest|multiview|encoder|decoder|transcode|\bmcr\b|\bpcr\b|on.?air|\bvtr\b", re.I), "Broadcast A/V", 2),
    (re.compile(r"nexis|isilon|\bnas\b|\bsan\b|storage|datastore|\blun\b|netapp|\bemc\b", re.I), "Storage", 2),
    (re.compile(r"esx|vmware|hyper-?v|hypervisor|vcenter|nutanix|\bvm\b", re.I), "VM / Hypervisor", 2),
    (re.compile(r"\bsql\b|oracle|database|\bdb\b|postgres|mysql|mongo", re.I), "Database", 2),
    (re.compile(r"\bups\b|\bpdu\b", re.I), "UPS/PDU", 2),
    (re.compile(r"printer|\bmfp\b|copier", re.I), "Printer", 2),
    (re.compile(r"\bap[-_ ]|access.?point|\bwap\b|wireless", re.I), "Wireless AP", 2),
    (re.compile(r"phone|voip|\bsip\b", re.I), "Phone", 2),
    (re.compile(r"robot", re.I), "Robotics", 2),
    (re.compile(r"render|\bserver\b|\bsrv\b|compute|\bblade\b|\besxi\b", re.I), "Server", 2),
    (re.compile(r"firewall|\basa\b", re.I), "Firewall", 2),
    (re.compile(r"router|gateway", re.I), "Router", 1),
    (re.compile(r"switch", re.I), "Network", 1),
]
# Vendor substring -> (class, rank). Unambiguous makers are rank 2; ambiguous (Dell/HP = server OR
# workstation) are rank 1 so a description/CDP signal wins.
# KNOWN LIMITATION (audit-5 FF#7): the shipped Wireshark `manuf` registry consolidates ALL Aruba OUIs under the
# IEEE legal name 'Hewlett Packard Enterprise' -- NO registry row contains the string 'aruba'. So the 'aruba'
# substring in the rank-1 Network rule below only matches a NON-registry / custom vendor source; an Aruba AP or
# switch resolved through the shipped registry carries vendor 'Hewlett Packard Enterprise' and falls to the
# rank-1 'Server' rule. That is an OVERRIDABLE inference (a description / CDP neighbor / explicit role still wins),
# not a confident label -- but absent any such signal an OUI-only Aruba device reads as 'Server'. HPE-server vs
# HPE-Aruba cannot be told apart by vendor STRING alone (the registry erased the distinction); correcting it needs
# a per-device role signal, not another vendor substring. Do NOT delete the 'aruba' entry: it still classifies a
# custom/non-registry source that does surface 'aruba'.
_EP_VENDOR_RULES = [
    (("apc", "american power conversion", "schneider", "eaton", "tripp", "vertiv", "liebert", "cyberpower"),
     "UPS/PDU", 2),   # 'american power conversion' = APC's IEEE-registry LEGAL name (block 00C0B7); 'apc' is not in it
    (("audinate", "lawo", "riedel", "calrec", "digigram"), "Audio (Dante/AES67)", 2),
    (("grass valley", "evs broadcast", "evertz", "ross video", "blackmagic", "newtek", "imagine comm",
      "harmonic", "telestream", "vizrt", "nevion", "dektec", "bridge tech", "tag video", "l-s-b",
      "sony"), "Broadcast A/V", 2),
    (("axis comm", "hikvision", "dahua", "hanwha", "pelco", "vivotek", "mobotix"), "Camera", 2),
    (("netapp", "pure storage", "dell emc", "isilon", "nimble", "infinidat", "hitachi data", "qnap",
      "synology", "quantum corp", "spectra logic"), "Storage", 2),
    (("vmware", "nutanix"), "VM / Hypervisor", 2),
    (("avid",), "Storage", 1),
    (("super micro", "supermicro", "tyan", "inspur", "quanta", "wiwynn"), "Server", 2),
    (("juniper", "arista", "aruba", "ruckus", "ubiquiti", "extreme net", "fortinet", "palo alto",
      "check point", "f5 net", "f5 inc"), "Network", 1),
    (("canon", "epson", "brother indus", "xerox", "ricoh", "kyocera", "lexmark", "zebra tech"), "Printer", 2),
    (("polycom", "avaya", "mitel", "yealink", "grandstream"), "Phone", 2),
    (("dell", "hewlett packard", "hpe", "hp inc", "lenovo", "intel corp", "giga-byte", "asrock", "asustek"),
     "Server", 1),
    (("apple", "microsoft"), "Workstation", 1),
]
# Collector's own endpoint_type -> class (rank 2: it is CDP-capability derived).
_EP_TYPE_MAP = {"server": "Server", "storage": "Storage", "camera": "Camera", "ups/pdu": "UPS/PDU",
                "router": "Router", "firewall": "Firewall", "switch": "Network"}
_EP_CONF = {2: "Inferred-high", 1: "Inferred-medium", 0: "Unknown"}


def _classify_endpoint(vendor: str, desc: str, plat: str, etype: str, laa: bool):
    """Pick the highest-confidence class for one endpoint from its signals, returning
    (class, confidence, evidence-string). The vendor itself is reported separately as a fact."""
    cands = []  # (rank, class, evidence)
    for rx, cls, rank in _EP_DESC_RULES:
        if desc and rx.search(desc):
            cands.append((rank, cls, f"description '{desc.strip()[:32]}'")); break
    pl = (plat or "").lower()
    if "vmware" in pl or "esx" in pl:
        cands.append((2, "VM / Hypervisor", f"CDP platform '{plat.strip()[:24]}'"))
    elif "linux" in pl:
        cands.append((1, "Server", f"CDP platform '{plat.strip()[:24]}'"))
    if etype and etype.lower() in _EP_TYPE_MAP:
        cands.append((2, _EP_TYPE_MAP[etype.lower()], f"device-reported type '{etype}'"))
    if vendor:
        vl = vendor.lower()
        for subs, cls, rank in _EP_VENDOR_RULES:
            if any(s in vl for s in subs):
                cands.append((rank, cls, f"vendor '{vendor}'")); break
    if not cands:
        if laa:
            return "VM / Hypervisor", "Inferred-medium", "locally-administered MAC (virtual/randomized)"
        if vendor:
            # a vendor WAS resolved from the OUI but matched no class rule -> say so truthfully. The old 'no
            # vendor signal' string was factually false (contradicted by the row's own vendor column) (audit-4 #13).
            return "Unknown", "Unknown", f"vendor '{vendor}' resolved but matched no class rule"
        return "Unknown", "Unknown", "no vendor/description/platform signal"
    rank, cls, ev = max(cands, key=lambda c: c[0])
    return cls, _EP_CONF[rank], ev


def compute_endpoint_identity(all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> List[dict]:
    """NEW-V3.23.95: one record per access-port endpoint with its VENDOR (MAC OUI, a fact) and an
    inferred migration CLASS + confidence + the evidence that drove it. Pure read of already-parsed
    data + the offline OUI registry. One row per (host, port); a multi-MAC access port (downstream
    hub) is reported with its mac_count so endpoint-instances and ports stay distinguishable."""
    from cisco_toolkit.ouidb import vendor_for_mac, is_locally_administered
    out: List[dict] = []
    for host in sorted(all_interfaces):
        for port, d in all_interfaces[host].items():
            if (d.switchport_mode or "") != "Access":
                continue
            macs = _split_macs(d.end_host_mac)
            if not macs:
                continue
            vendor = ""
            for m in macs:
                vendor = vendor_for_mac(m)
                if vendor:
                    break
            laa = all(is_locally_administered(m) for m in macs)
            cls, conf, ev = _classify_endpoint(vendor, d.description or "", d.neighbor_platform or "",
                                               d.endpoint_type or "", laa)
            out.append({
                "host": host, "port": port, "vlan": (d.vlan or "").strip(),
                "ip": (d.end_host_ip or "").strip(), "mac": macs[0], "mac_count": len(macs),
                "vendor": vendor, "endpoint_class": cls, "confidence": conf, "evidence": ev,
            })
    return out


# Research-encoded "what to validate when this switch moves", keyed by endpoint class (NEW-V3.23.96).
# Each line is forwarding/service-proof, not control-plane-only (the false-health doctrine).
_VALIDATION_BY_CLASS = {
    "Storage": "datastore/LUN reachable AND the cluster peer (active/standby) is up — before and after the move",
    "VM / Hypervisor": "guest reachability + the live-migration/vMotion path; confirm shared storage stays reachable",
    "Broadcast A/V": "PTP clock lock on BOTH primary & secondary networks (ST-2022-7) + multicast (IGMP) joins",
    "Audio (Dante/AES67)": "Dante/AES67 PTP lock on both networks + flow subscriptions intact",
    "Camera": "NVR/VMS stream is live + PoE up",
    "UPS/PDU": "power-telemetry / shutdown-agent path to its manager",
    "Database": "replication/cluster quorum + application connectivity",
    "Server": "service/app reachability + the NIC-team peer leg stays up",
    "Phone": "call-manager registration",
    "Wireless AP": "controller registration + client roaming",
    "Robotics": "control/return path + PoE up (often on-air critical)",
}


def compute_endpoint_dependencies(endpoint_identity: List[dict],
                                  move_groups: Optional[list] = None) -> dict:
    """NEW-V3.23.96: cluster / dependency intelligence over the endpoint-identity model (workstream C).
    Turns 'a list of endpoints' into 'cohesive units + what depends on what + what to validate':
      * dual_homed  -- the SAME MAC seen on >=2 switches (NIC-team / dual-homed / a MAC move): the
        skill's 'never down both legs together' sequencing rule; flags pairs split across move-groups.
      * shared_ip   -- the same IP on >=2 switches (a service/cluster/VRRP IP).
      * clusters    -- per (vendor, class) distributed system: count + switch/VLAN spread + whether it
        spans multiple move-groups (a migration 'split' risk).
      * affinity    -- per-VLAN dominant class (the app tier living in that VLAN).
      * per_switch_validation -- per switch, the service-validation checklist derived from the classes
        it hosts (research-encoded), answering 'what must I validate when this switch moves'.
    Pure read of the precomputed identity records (one source of truth); confidence travels with those
    identity records."""
    from collections import Counter, defaultdict
    ident = endpoint_identity or []
    wave_of: Dict[str, str] = {}
    for g in (move_groups or []):
        for h in (g.get("switches") or []):          # tolerate switches=None, not just a missing key
            wave_of.setdefault(h, g.get("group", ""))

    mac_sw: Dict[str, set] = defaultdict(set); mac_meta: Dict[str, dict] = {}
    ip_sw: Dict[str, set] = defaultdict(set); ip_macs: Dict[str, set] = defaultdict(set)
    clusters: Dict[tuple, list] = defaultdict(lambda: [set(), set(), set()])   # (vendor,class)->[switches,vlans,DISTINCT macs]
    vlan_cls: Dict[str, Counter] = defaultdict(Counter)
    sw_classes: Dict[str, set] = defaultdict(set)
    sw_has_dualhomed: set = set()

    for r in ident:
        host, mac, ip = r.get("host", ""), (r.get("mac") or "").lower(), (r.get("ip") or "").strip()
        cls, vendor, vlan = r.get("endpoint_class", "Unknown"), r.get("vendor", ""), (r.get("vlan") or "").strip()
        if mac:
            mac_sw[mac].add(host)
            mac_meta.setdefault(mac, {"vendor": vendor, "endpoint_class": cls, "ip": ip, "ports": set()})
            mac_meta[mac]["ports"].add(f"{host}:{r.get('port', '')}")
        if ip:
            ip_sw[ip].add(host); ip_macs[ip].add(mac)
        if cls != "Unknown":
            sw_classes[host].add(cls)
            if vendor:
                c = clusters[(vendor, cls)]; c[0].add(host); c[1].add(vlan); c[2].add(mac)
        # per-VLAN affinity counts EVERY endpoint INCLUDING Unknown, so a VLAN that is mostly unclassified is not
        # labelled with the app tier of a tiny KNOWN minority -- the dominant + total stay honest (audit-5 #24).
        if vlan.isdigit():
            vlan_cls[vlan][cls] += 1

    dual_homed = []
    for mac, sws in mac_sw.items():
        if len(sws) >= 2:
            m = mac_meta[mac]; groups = sorted({wave_of.get(s, "") for s in sws} - {""})
            sw_has_dualhomed.update(sws)
            dual_homed.append({"mac": mac, "ip": m["ip"], "vendor": m["vendor"],
                               "endpoint_class": m["endpoint_class"], "switches": sorted(sws),
                               "ports": sorted(m["ports"])[:8], "move_groups": groups,
                               "split_across_groups": len(groups) > 1})
    dual_homed.sort(key=lambda d: (not d["split_across_groups"], d["endpoint_class"], d["mac"]))

    shared_ip = [{"ip": ip, "switches": sorted(sws), "macs": sorted(m for m in ip_macs[ip] if m)}
                 for ip, sws in ip_sw.items() if len(sws) >= 2]
    shared_ip.sort(key=lambda d: d["ip"])

    clu = []
    for (vendor, cls), (sws, vlans, macs) in clusters.items():
        cnt = len(macs - {""})            # DISTINCT MACs, not (host,port) rows -- a dual-homed / multi-port MAC
        if cnt < 3:                        # was counted once per row, inflating the cluster size (audit-5 scale-ssot #0)
            continue
        groups = sorted({wave_of.get(s, "") for s in sws} - {""})
        clu.append({"vendor": vendor, "endpoint_class": cls, "count": cnt, "switches": len(sws),
                    "vlans": len(vlans), "move_groups": len(groups), "spans_groups": len(groups) > 1})
    clu.sort(key=lambda c: -c["count"])

    affinity = []
    for vlan, c in vlan_cls.items():
        total = sum(c.values())
        if total < 5:
            continue
        affinity.append({"vlan": vlan, "total": total, "classes": dict(c.most_common(3)),
                         "dominant": c.most_common(1)[0][0]})
    affinity.sort(key=lambda a: -a["total"])

    per_switch_validation: Dict[str, list] = {}
    for host, classes in sw_classes.items():
        lines = [f"{cls}: {_VALIDATION_BY_CLASS[cls]}" for cls in sorted(classes)
                 if cls in _VALIDATION_BY_CLASS]
        if host in sw_has_dualhomed:
            lines.append("Dual-homed endpoint(s) present — sequence make-before-break so the peer leg "
                         "stays up during the move.")
        if lines:
            per_switch_validation[host] = lines

    return {"dual_homed": dual_homed, "shared_ip": shared_ip, "clusters": clu,
            "affinity": affinity, "per_switch_validation": per_switch_validation}


# =============================================================================
# Subnet & routing reachability intelligence (NEW-V3.23.97, plan workstream A). Per device: which
# subnets it is the DESTINATION for (terminates / gateways) vs which it can REACH (route table) vs,
# for an L2 access switch, which subnets its endpoints live in (transitively, via the SVI that
# gateways their VLAN) -- and, per move-group, the source<->destination split (local subnets that
# move with the group vs remote subnets that must stay reachable across the cutover). Built from the
# already-collected full 'show ip route' (passed in parsed) + the SVIs on InterfaceData; received BGP
# prefixes fold in when the new 'show ip bgp' collection is present (else reported as not-collected).
# =============================================================================
def _svi_network(svi_ip: str) -> str:
    """An SVI address ('ip/mask' CIDR, or 'ip mask', or bare ip) -> its connected network in CIDR, or
    '' if unparseable. Handles both forms seen in the wild."""
    import ipaddress
    s = (svi_ip or "").strip()
    if not s:
        return ""
    try:
        if "/" in s:
            return str(ipaddress.ip_network(s.split()[0], strict=False))
        parts = s.split()
        if len(parts) >= 2:
            return str(ipaddress.ip_network(f"{parts[0]}/{parts[1]}", strict=False))
    except ValueError:
        return ""
    return ""


def compute_subnet_intelligence(all_interfaces: Dict[str, Dict[str, InterfaceData]],
                                routes_full: Optional[dict] = None,
                                move_groups: Optional[list] = None,
                                bgp_received: Optional[dict] = None) -> dict:
    """NEW-V3.23.97: per-device subnet/routing reachability + per-move-group source<->destination view.
    `routes_full` = {host: parse_ip_routes output} (the FULL table, not the snapshot's scoped subset);
    `bgp_received` = {host: [prefix,...]} from the new 'show ip bgp' collection (optional). Pure read.
    Returns {per_device:[...], move_groups:[...], bgp_received_collected:bool}."""
    from collections import Counter, defaultdict
    routes_full = routes_full or {}
    bgp_received = bgp_received or {}

    vlan_gw: Dict[int, list] = defaultdict(list)        # vid -> [(gateway_host, subnet)]
    dev_svi_subnets: Dict[str, set] = defaultdict(set)
    for host, ifaces in all_interfaces.items():
        for port, d in ifaces.items():
            m = re.match(r"^Vlan(\d+)$", port, re.IGNORECASE)
            if m:
                net = _svi_network(getattr(d, "svi_ip", "") or "")
                if net:
                    vlan_gw[int(m.group(1))].append((host, net))
                    dev_svi_subnets[host].add(net)

    per_device = []; reach_full: Dict[str, set] = {}
    for host in sorted(all_interfaces):
        rdb = routes_full.get(host) or {}
        dest = set(dev_svi_subnets.get(host, set())); reach = []; src_c: Counter = Counter(); default_nh = ""
        for prefix, info in rdb.items():
            ents = info.get("entries") if isinstance(info, dict) else None
            ents = ents or [info if isinstance(info, dict) else {}]
            src = ""; nh = ""
            for e in ents:
                if not src and e.get("source"):
                    src = e.get("source")
                if not nh and e.get("next_hop"):
                    nh = e.get("next_hop")
            src = (src or "").lower()
            if prefix == "0.0.0.0/0":
                default_nh = nh or default_nh; continue
            if src in ("connected", "local"):
                if src == "connected":
                    dest.add(prefix)
                continue
            reach.append({"prefix": prefix, "source": src or "?", "next_hop": nh}); src_c[src or "?"] += 1
        is_l3 = bool(rdb) or bool(dev_svi_subnets.get(host))
        served = []
        if not is_l3:
            seen = set()
            for port, d in all_interfaces[host].items():
                if (getattr(d, "switchport_mode", "") or "") == "Access" and (getattr(d, "vlan", "") or "").isdigit():
                    for gw, net in vlan_gw.get(int(d.vlan), []):
                        if net not in seen:
                            seen.add(net); served.append({"subnet": net, "gateway": gw, "vlan": d.vlan})
        reach_full[host] = {e["prefix"] for e in reach}
        per_device.append({
            "host": host, "is_l3": is_l3,
            "destination_subnets": sorted(dest), "destination_count": len(dest),
            "reachable_count": len(reach), "reachable_sources": dict(src_c),
            "reachable_sample": sorted(reach, key=lambda e: e["prefix"])[:25],
            "default_next_hop": default_nh,
            "served_subnets": sorted(served, key=lambda s: s["subnet"])[:30],
            "bgp_received_count": len(bgp_received.get(host, [])),
        })

    dest_by = {r["host"]: set(r["destination_subnets"]) for r in per_device}
    served_by = {r["host"]: {s["subnet"] for s in r["served_subnets"]} for r in per_device}
    mg = []
    for g in (move_groups or []):
        members = g.get("switches") or []; local: set = set(); remote: set = set()
        for h in members:
            local |= dest_by.get(h, set()) | served_by.get(h, set())
        for h in members:
            remote |= reach_full.get(h, set())
        remote -= local
        mg.append({"group": g.get("group", ""), "switches": len(members),
                   "local_subnets": sorted(local)[:50], "local_count": len(local),
                   "remote_count": len(remote)})
    return {"per_device": per_device, "move_groups": mg, "bgp_received_collected": bool(bgp_received)}


# =============================================================================
# Migration scenario framework (NEW-V3.23.98, plan workstream D). Per move-group, recommend a cutover
# SCENARIO (phased / parallel-run / greenfield / big-bang) from the group's own shape -- readiness
# verdict, dual-homing ratio (make-before-break vs hard cutover), and size -- and attach the
# scenario-specific pre-check / validate / rollback playbook. General by design: it recommends, the
# war-room decides. Research-encoded (greenfield/parallel/phased/big-bang migration doctrine).
# =============================================================================
_SCENARIO_PLAYBOOK = {
    "parallel-run": {
        "pre": "Build the new path beside the legacy one; confirm both legs of every dual-homed endpoint are up.",
        "validate": "Cut one leg, prove forwarding from a real endpoint to its gateway + a cross-VLAN service, then cut the second.",
        "rollback": "Any endpoint loses reachability on the new leg -> fail back to the legacy leg (still up); re-validate."},
    "phased": {
        "pre": "Resolve gating checks first; schedule single-homed (hard-cutover) switches into maintenance windows.",
        "validate": "Per wave, prove forwarding for a sample endpoint of EACH hosted class before the next wave.",
        "rollback": "A wave fails validation -> re-home that wave's uplinks to the legacy path; hold the remaining waves."},
    "greenfield": {
        "pre": "Stand up a clean target fabric; pre-stage config/templates; map each endpoint to its new port/VLAN.",
        "validate": "Move a pilot group, soak it, prove every endpoint class end-to-end before scaling.",
        "rollback": "Pilot fails -> endpoints stay on legacy (untouched); fix the target, retry the pilot."},
    "big-bang": {
        "pre": "Single cutover window; freeze changes; have every owner on the bridge. HIGH RISK — last resort.",
        "validate": "Prove the full service set immediately after the window; no partial-success state.",
        "rollback": "Pre-agreed hard rollback to the legacy config snapshot; rehearse it before the window."},
}


def compute_migration_scenarios(migration_readiness: list, wave_sequencing: list,
                                health_scores: Optional[list] = None) -> dict:
    """NEW-V3.23.98: per move-group cutover-scenario recommendation + playbook, plus a fleet-level note.
    Synthesis of already-computed readiness + wave sequencing (+ optional health bands); no new data.
    Returns {per_group:[...], fleet_recommendation:str, scenario_counts:{...}}."""
    ws_by = {w.get("group", ""): w for w in (wave_sequencing or [])}
    per_group = []; counts: Dict[str, int] = {}
    for r in (migration_readiness or []):
        g = r.get("group", ""); w = ws_by.get(g, {})
        members = len(r.get("switches") or []); eps = r.get("endpoints", 0)
        mbb = len(w.get("make_before_break") or []); hard = len(w.get("hard_cutover") or [])
        hard_eps = w.get("hard_cutover_endpoints", 0); readiness = r.get("readiness", "")
        # compute_wave_sequencing classifies a NEVER-COLLECTED switch as `homing_unknown` precisely so an
        # empty adjacency is not read as proof of single-homing (audit-5 #7) -- and says so in its own
        # `sequence` text. Those switches are in NEITHER mbb nor hard, so `mbb / (mbb + hard)` is a ratio
        # over the ASSESSED subset while the sentence below labels it "% of switches": a group of 8 whose 5
        # uncollected members leave 3 dual-homed read "100% of switches are dual-homed" and were handed
        # parallel-run, the LOWEST-safeguard scenario, off a population that was mostly unassessed. Keep the
        # ratio over its real (assessed) basis, NAME that basis, and never recommend parallel-run while any
        # member's homing is unknown -- the make-before-break premise is that a second leg exists.
        unk = len(w.get("homing_unknown") or [])
        assessed = mbb + hard
        mbb_pct = round(100 * mbb / assessed) if assessed else 0
        if readiness == "NOT READY":
            sc = "phased"; why = (f"gating checks fail ({r.get('n_fail', 0)} blocker(s)) — resolve them, "
                                  "then migrate in small validated waves.")
        elif hard and hard_eps >= max(eps * 0.2, 1):
            sc = "phased"; why = (f"{hard} single-homed switch(es) ({hard_eps} endpoint(s) at risk) — "
                                  "phase into maintenance windows; dual-home first where possible.")
        elif unk:
            sc = "phased"; why = (f"{unk} of {members} switch(es) have UNKNOWN homing (never collected) — "
                                  "uplink redundancy is NOT assessable there, so make-before-break cannot "
                                  "be assumed. Collect them, then re-evaluate; phase until it is known.")
        elif members >= 4 and mbb_pct >= 80:
            sc = "parallel-run"; why = (f"{mbb_pct}% of the {assessed} assessed switch(es) are dual-homed — "
                                        "build beside and cut leg-by-leg (make-before-break) for minimal "
                                        "outage.")
        elif members <= 2:
            sc = "big-bang" if members <= 1 else "phased"
            why = ("tiny group — a single window is feasible (rehearse rollback)." if members <= 1
                   else "small group — migrate phased with per-endpoint validation.")
        else:
            sc = "phased"; why = "mixed homing — phased waves with per-class validation are the safe default."
        counts[sc] = counts.get(sc, 0) + 1
        per_group.append({"group": g, "switches": members, "endpoints": eps, "readiness": readiness,
                          # NB for consumers: dual_homed_pct's denominator is the ASSESSED subset
                          # (make_before_break + hard_cutover), NOT `switches` -- the difference is the
                          # never-collected, homing-UNKNOWN members, so the two must never be rendered
                          # as "<switches> switches - <dual_homed_pct>% dual-homed" without that basis.
                          "make_before_break": mbb, "hard_cutover": hard, "hard_cutover_endpoints": hard_eps,
                          "dual_homed_pct": mbb_pct, "recommended_scenario": sc, "rationale": why,
                          "playbook": _SCENARIO_PLAYBOOK[sc]})
    fleet = ""
    # Poor/Critical share is computed over ASSESSED switches only. An "Insufficient Data" row is an
    # UNCOLLECTED device (no evidence -> no health deductions -> never banded Poor/Critical); counting it in
    # the denominator silently treats it as healthy and DILUTES the degradation %, which can flip this
    # greenfield-vs-in-place recommendation below its 60% gate (audit-6 correctness: a 4/6=67% -> GREENFIELD
    # fleet reads 4/10=40% -> in-place when 4 devices were merely not collected). Matches the exec-brief
    # convention, which already averages health over genuinely-scored rows only (analyze.py compute_executive_brief).
    hs = [r for r in (health_scores or []) if r.get("band") != "Insufficient Data"]
    if hs:
        crit = sum(1 for r in hs if r.get("band") in ("Critical", "Poor"))
        pct = round(100 * crit / len(hs))
        if pct >= 60:
            fleet = (f"{pct}% of switches are Poor/Critical — consider a GREENFIELD rebuild for the most "
                     "degraded segments (move endpoints onto a clean fabric) rather than migrating debt in place.")
        else:
            fleet = (f"{pct}% of switches are Poor/Critical — an in-place PHASED / PARALLEL-RUN migration is "
                     "viable; reserve greenfield for any isolated worst-offenders.")
    return {"per_group": per_group, "fleet_recommendation": fleet, "scenario_counts": counts}


def compute_trunk_capture_gaps(all_interfaces: Dict[str, Dict[str, InterfaceData]],
                               all_cmd_to_files: Dict[str, Dict[str, str]]) -> List[str]:
    """Devices whose native-VLAN-1 exposure is NOT ASSESSABLE: collected, switchport-bearing (some
    port carries a switchport_mode -- i.e. the box plausibly trunks), but with NO usable trunk-table
    capture (cmdio.cmd_capture_state over TRUNK_TABLE_CMD_VARIANTS is 'missing' or 'error'). A
    captured-but-EMPTY trunk table is an ANSWER (zero trunks) and is deliberately not a gap; a device
    with no switchport evidence at all (a router) is outside this detector's scope. Feeds
    compute_operational_drift(trunk_not_captured=...) -- the mechanical backing for the
    l2-native-vlan-1 descriptor's abstains_when contract. Total: never raises, and a host whose
    capture state cannot be DETERMINED is reported as a gap rather than dropped (see below)."""
    gaps: List[str] = []
    for host, ports in (all_interfaces or {}).items():
        try:
            if not any((getattr(d, "switchport_mode", "") or "") for d in (ports or {}).values()):
                continue
            state = cmd_capture_state((all_cmd_to_files or {}).get(host) or {}, *TRUNK_TABLE_CMD_VARIANTS)
            if state in ("missing", "error"):
                gaps.append(host)
        except Exception:
            # FAIL-CLOSED. A bare `continue` here dropped the host from the coverage-gap list, so its
            # native-VLAN-1 exposure read clean -- the exact absence-reads-as-no-exposure failure this
            # detector exists to prevent, and the swallow was unbounded: EVERY host could raise and
            # the function would still return [] (#17). "Could not determine" is a blind spot, not a
            # clean bill, so an undeterminable host joins the gaps it may well belong to.
            gaps.append(host)
    return sorted(gaps, key=str)   # key=str: the except-path can now admit a non-str host key


def compute_operational_drift(all_interfaces: Dict[str, Dict[str, InterfaceData]],
                              all_device_physical: list,
                              trunk_not_captured: Optional[List[str]] = None) -> List[dict]:
    """NEW-V3.23.93: evidence-led FALSE-HEALTH / operational-drift detector. Surfaces the migration
    traps a green control plane hides (cisco-network-assessment doctrine: "configured is not healthy;
    up is not healthy"): temporary L2 bridges enlarging the broadcast/STP domain, PoE faults on ports
    described as live powered endpoints, native-VLAN-1 on operationally-trunking ports, and multi-year uptime
    (STP / control-plane not exercised recently -> latent risk that surfaces on the first change).

    `trunk_not_captured` (from compute_trunk_capture_gaps) lists collected switchport-bearing devices
    with no usable trunk-table capture: they are disclosed as an Info/Coverage row -- the native-VLAN-1
    check ABSTAINS there instead of silently reading clean ('not observed' is never 'healthy'). None
    (offline recompute without a capture record) leaves behaviour unchanged.

    Bulk patterns are AGGREGATED (one row + a count/list), never one row per port, per the same
    cry-wolf doctrine the rest of the toolkit follows. Returns punch-list-shaped finding dicts
    {severity, category, devices, title, detail, remediation}. Pure read of already-parsed data."""
    TEMP = re.compile(r"\btemp\b|temporary|temp[-_ ]|\btmp\b", re.I)
    POWERED = re.compile(r"cam|camera|ptz|robot|light|on.?air|access.?point|\bap[-_ ]", re.I)
    POE_FAULT = re.compile(r"fault|denied|err", re.I)
    out: List[dict] = []

    # 1. Temporary L2 bridges on infra/trunk ports -- broadcast/STP-domain blast radius.
    temp_by_host: Dict[str, list] = {}
    for host, ports in all_interfaces.items():
        for p, d in ports.items():
            desc = (d.description or "").strip()
            is_infra = bool((d.cdp_neighbor or "").strip()) or is_live_trunk_status(d.trunk_status)
            if desc and is_infra and TEMP.search(desc):
                temp_by_host.setdefault(host, []).append(f"{p} ({desc[:40]})")
    for host, ports in sorted(temp_by_host.items()):
        out.append({"severity": "High", "category": "False-health", "devices": [host],
                    "title": f"Temporary L2 bridge on {host}",
                    "detail": f"{len(ports)} infra port(s) described as a temporary bridge: "
                              f"{', '.join(ports[:6])}. A temporary L2 bridge enlarges the broadcast / "
                              "STP domain over production VLANs.",
                    "remediation": "Confirm whether the temporary bridge is still required; remove it or "
                                   "convert it to a designed, pruned link before cutover."})

    # 2. PoE fault -- a real pre-cutover action. A powered-endpoint description only RAISES severity (a
    # dark phone/AP); it must never SUPPRESS a fault, or faults on blank-described ports go unseen. (DET-poe-002)
    poe_by_host: Dict[str, list] = {}
    for host, ports in all_interfaces.items():
        for p, d in ports.items():
            ps = (d.poe_status or ""); desc = (d.description or "").strip()
            if ps and POE_FAULT.search(ps):
                poe_by_host.setdefault(host, []).append((p, desc, ps, bool(POWERED.search(desc))))
    for host, items in sorted(poe_by_host.items()):
        powered = [it for it in items if it[3]]
        shown = [f"{p} ({(desc[:30] + ': ') if desc else ''}{ps})" for p, desc, ps, _ in items[:6]]
        out.append({"severity": "High" if powered else "Medium", "category": "False-health", "devices": [host],
                    "title": f"PoE fault on {host}" + (" (powered endpoint affected)" if powered else ""),
                    "detail": f"{len(items)} port(s) in a PoE fault state"
                              + (f", {len(powered)} on a powered-endpoint description (endpoint likely dark)" if powered else "")
                              + f": {', '.join(shown)}.",
                    "remediation": "Resolve the PoE fault (power budget / cabling / device) before the "
                                   "cutover window."})

    # 3. Native VLAN 1 on operationally-trunking ports -- hygiene / VLAN-hopping exposure. AGGREGATED.
    # Counts LIVE trunk-table status via the shared textutils.is_live_trunk_status token owner
    # ('trunking' AND 'trnk-bndl' -- PR-#396 review: startswith('trunk') missed bundle members), with
    # NO inter-switch scoping: every live-trunking native-1 port counts, host-facing trunks included.
    # Deliberately a DIFFERENT measure from the design gap's switchport-mode count (design_advisor);
    # both texts name their unit+basis (textutils.NATIVE1_* tokens) so the figures cannot render as
    # one contradicting fact.
    nat1_hosts: list = []
    for host, ports in all_interfaces.items():
        if any(is_live_trunk_status(d.trunk_status)
               and (d.trunk_native_vlan or "").strip() == "1" for d in ports.values()):
            nat1_hosts.append(host)
    nat1_count = sum(1 for host, ports in all_interfaces.items() for d in ports.values()
                     if is_live_trunk_status(d.trunk_status)
                     and (d.trunk_native_vlan or "").strip() == "1")
    if nat1_hosts:
        out.append({"severity": "Low", "category": "False-health", "devices": sorted(nat1_hosts),
                    "title": f"Native VLAN 1 on {nat1_count} {NATIVE1_OPS_UNIT}",
                    "detail": f"{nat1_count} {NATIVE1_OPS_UNIT} ({NATIVE1_OPS_BASIS}) across "
                              f"{len(nat1_hosts)} {NATIVE1_OPS_SWITCH_UNIT} carry the default VLAN 1 "
                              "as the native (untagged) VLAN -- a hygiene and VLAN-hopping exposure. "
                              f"(The design gap counts {NATIVE1_CFG_UNIT} -- {NATIVE1_CFG_BASIS} -- "
                              "so the two figures can differ.)",
                    "remediation": "Set a dedicated, unused native VLAN on every 802.1Q trunk."})

    # 3b. Trunk-table capture gaps -- the l2-native-vlan-1 abstention, made MECHANICAL (the descriptor's
    # abstains_when promised per-port abstention but nothing implemented it: a collected device whose
    # trunk table was never captured contributed 0 to item 3 and read clean). Disclosed as an
    # Info/Coverage row -- present even when item 3 found nothing, so absence-of-evidence can never
    # render as absence-of-exposure. Title deliberately avoids the exact 'Native VLAN 1' phrase so
    # finding-row consumers (and the collision-guard test) never mistake it for the measured figure.
    if trunk_not_captured:
        _gaps = sorted({str(h) for h in trunk_not_captured if h})
        if _gaps:
            shown = ", ".join(_gaps[:6]) + ("..." if len(_gaps) > 6 else "")
            out.append({"severity": "Info", "category": "Coverage", "devices": _gaps,
                        "title": f"Native-VLAN-1 check not assessable on {len(_gaps)} device(s)",
                        "detail": f"{len(_gaps)} collected switchport-bearing device(s) have no usable "
                                  "trunk-table capture ('show interface trunk' missing or errored), so "
                                  "native-VLAN-1 exposure is NOT ASSESSABLE there -- not clean: "
                                  f"{shown}. (A captured-but-empty trunk table is an answer -- zero "
                                  "trunks -- and does not appear here.)",
                        "remediation": "Re-collect these devices including 'show interface trunk' "
                                       "before certifying native-VLAN hygiene."})

    # 4. Multi-year uptime -- STP / control-plane not exercised recently (latent cutover risk). AGGREGATED.
    year_re = re.compile(r"(\d+)\s*year")
    longup: list = []
    for dp in (all_device_physical or []):
        m = year_re.search(getattr(dp, "uptime", "") or "")
        if m and int(m.group(1)) >= 3:
            longup.append((getattr(dp, "hostname", ""), int(m.group(1))))
    if longup:
        longup.sort(key=lambda t: -t[1])
        top = ", ".join(f"{h} ({y}y)" for h, y in longup[:6])
        out.append({"severity": "Low", "category": "False-health", "devices": [h for h, _ in longup],
                    "title": f"Multi-year uptime on {len(longup)} device(s) (max {longup[0][1]} years)",
                    "detail": f"{len(longup)} device(s) have not reloaded in 3+ years (e.g. {top}). "
                              "STP / control-plane convergence has not been exercised recently -- latent "
                              "issues can surface on the first change.",
                    "remediation": "Plan a deliberate, monitored maintenance window; do not let the cutover "
                                   "be the first control-plane event in years."})
    return out


_PUNCH_RANK = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}

# W2-3 (framework-mapping matrix): the engine's existing config-hardening checks (parse._SEC_CHECKS) mapped to the
# control each one EVIDENCES in NIST 800-53r5 / PCI-DSS v4.0 / DISA Cisco IOS NDM STIG (the CIS ref already rides on
# each finding). A mapping over EXISTING checks -- NOT a new check engine. Control IDs grounded against the published
# frameworks (NIST 800-53r5 catalog; PCI-DSS v4.0: 2.2.7 non-console-admin encryption, 8.3.2 password crypto, 10.2
# audit logs, 10.6 time sync; NIST AC-17(2)/SC-8 = encrypted remote mgmt, AU-8 = time stamps, AU-2/6/12 = audit).
# Where an exact PCI sub-requirement is uncertain the safe PARENT requirement is used (never a fabricated number);
# a check with no mapping in a framework is left UNMAPPED -> 'not auto-assessed', never a silent 'pass' (doctrine guard).
_FRAMEWORK_MAP: Dict[str, Dict[str, str]] = {
    "password-encryption": {"nist": "IA-5(1)",             "pci": "8.3.2", "stig": "Cisco IOS NDM — password encryption"},
    "weak-enable":         {"nist": "IA-5(1)",             "pci": "8.3.2", "stig": "Cisco IOS NDM — privileged secret"},
    "weak-user-pw":        {"nist": "IA-5(1)",             "pci": "8.3.2", "stig": "Cisco IOS NDM — local password storage"},
    "no-aaa":              {"nist": "AC-2 / IA-2",         "pci": "8.2",   "stig": "Cisco IOS NDM — centralized AAA"},
    "insecure-snmp":       {"nist": "AC-17(2) / SC-8",     "pci": "2.2.7", "stig": "Cisco IOS NDM — SNMPv3 auth/priv"},
    "telnet-enabled":      {"nist": "AC-17(2) / SC-8",     "pci": "2.2.7", "stig": "Cisco IOS NDM — encrypted (SSH) management"},
    "risky-services":      {"nist": "CM-7",                "pci": "2.2",   "stig": "Cisco IOS NDM — disable unused services"},
    "no-ntp":              {"nist": "AU-8",                "pci": "10.6",  "stig": "Cisco IOS NDM — authenticated time source"},
    "no-logging":          {"nist": "AU-2 / AU-6 / AU-12", "pci": "10.2",  "stig": "Cisco IOS NDM — audit logging"},
    "no-banner":           {"nist": "AC-8",                "pci": "",      "stig": "Cisco IOS NDM — login banner"},
    "vty-hardening":       {"nist": "AC-17 / AC-12",       "pci": "8.2",   "stig": "Cisco IOS NDM — VTY ACL + exec-timeout"},
}
_FRAMEWORK_LABELS = {"CIS": "CIS Cisco Benchmark", "NIST": "NIST 800-53 r5",
                     "PCI": "PCI-DSS v4.0", "STIG": "DISA Cisco IOS NDM STIG"}


def compute_framework_coverage(security: Dict[str, dict]) -> dict:
    """Map the engine's EXISTING config-hardening findings to the control each EVIDENCES in CIS / NIST 800-53 /
    PCI-DSS / DISA STIG -- a 'proof of compliance' matrix over existing checks, NOT a new check engine. Per
    control the status rolls up across hosts (ANY fail -> fail; else any pass -> pass; else na). COVERAGE-HONEST:
    a check with no mapping in a framework is simply absent there ('not auto-assessed'), NEVER a silent 'pass';
    a not-applicable check stays 'na'. Config-only evidence (show running-config) -- a partial, config-evidenced
    mapping, NOT a full framework audit. Returns {frameworks:{KEY:{label,controls,n_assessed,n_fail}}, note, scope}."""
    sec = security if isinstance(security, dict) else {}
    agg: Dict[str, dict] = {}     # check_id -> rollup across hosts
    for host, s in sec.items():
        for f in ((s or {}).get("findings") or []):
            if not isinstance(f, dict):
                continue
            cid = f.get("id") or ""
            st = str(f.get("status") or "").lower()
            a = agg.setdefault(cid, {"pass": 0, "fail": 0, "na": 0, "title": f.get("title") or cid,
                                     "cis": f.get("cis_ref") or "", "hosts_fail": []})
            if st in ("pass", "fail", "na"):
                a[st] += 1
            if st == "fail" and host:
                a["hosts_fail"].append(host)

    def _rollup(a: dict) -> str:
        return "fail" if a["fail"] else ("pass" if a["pass"] else "na")

    def _control(fw: str, cid: str, a: dict) -> str:
        if fw == "CIS":
            return a["cis"]
        return (_FRAMEWORK_MAP.get(cid) or {}).get(fw.lower(), "")

    frameworks: Dict[str, dict] = {}
    for fw in ("CIS", "NIST", "PCI", "STIG"):
        controls = []
        for cid, a in sorted(agg.items()):
            c = _control(fw, cid, a)
            if not c:                       # no mapping in this framework -> NOT auto-assessed (never a fake pass)
                continue
            controls.append({"control": c, "check": cid, "title": a["title"], "status": _rollup(a),
                             "n_fail": a["fail"], "hosts_fail": sorted(set(a["hosts_fail"]))[:12]})
        controls.sort(key=lambda x: (0 if x["status"] == "fail" else 1 if x["status"] == "na" else 2, x["control"]))
        frameworks[fw] = {"label": _FRAMEWORK_LABELS[fw], "controls": controls,
                          "n_assessed": len(controls),
                          "n_fail": sum(1 for x in controls if x["status"] == "fail")}
    return {"frameworks": frameworks,
            "note": "Config-evidenced mapping of the engine's hardening checks to framework controls — NOT a full "
                    "framework audit. Controls outside this check set are not auto-assessed (never assumed 'pass'); "
                    "a not-applicable check stays 'na'.",
            "scope": "config-only (show running-config); management-plane hardening controls"}


# W1-3 (SmartyMe teardown -- per-claim provenance): the single `show` command whose output BACKS each punch-list
# category's evidence, so a finding can cite 'from: <show cmd>'. Grounded -- every value is a command in the
# engine's COMMANDS_IOS/NXOS registry (asserted in tests). COMPOSITE / multi-source / meta categories (Cross-layer,
# Compound risk, Health, Protocol, False-health) are DELIBERATELY ABSENT: they synthesize several commands, so
# citing one would be fabricated provenance -- and their absence keeps this from overclaiming 'every finding is
# traced' (the binding critic constraint). Provenance where it genuinely exists; silence where it doesn't.
_PUNCH_SOURCE_COMMAND: Dict[str, str] = {
    "STP": "show spanning-tree",
    "Security": "show running-config",
    "Config hygiene": "show running-config",
    "Inventory": "show version",
    "Software exposure": "show version",
    "Operational logs": "show logging",
    "L3": "show ip route",
    "Addressing": "show ip interface brief",
    "QoS": "show policy-map interface",
    "Multicast/Media": "show ip igmp snooping groups",
    "Timing/PTP": "show ptp clock",
    "FHRP": "show standby brief",
    "L1": "show interface status",
    "Trunk": "show interface trunk",
    "Link L1": "show interface status",
}

# review r10 EXIT A -- the fail-closed text a folded risk gets when it publishes NO usable basis for
# its own severity. Wording deliberately matches excel.py's mac-alias "Why this severity" cell so the
# workbook's two surfaces (the Multicast sheet and the Punch-List sheet) never disagree about what an
# unpublished basis means. Absence of a basis is a DISCLOSURE, never a licence to read the severity
# as if it had been measured.
# Discloses ABSENCE of a published basis WITHOUT asserting the severity was unmeasured -- two
# different claims, and fusing them made the sentinel wrong in the harmful direction. It is applied
# to every media risk, and `querier-gap`'s High IS a measurement (observed querier state); telling a
# reader not to trust a measured finding devalues the real ones and teaches them to skip the caveat
# on the curated rows it exists for. Say only what is true of every row it can land on.
PUNCH_BASIS_UNPUBLISHED = ("severity basis NOT published by this snapshot — check the finding's own "
                           "detail for what it rests on")
PUNCH_CONFIDENCE_UNPUBLISHED = "evidence confidence NOT published by this snapshot"


def _usable_text(value) -> str:
    """A basis string is only carried forward when its VALUE is usable prose.

    Keying a disclosure on key-PRESENCE (`"severity_basis" in risk`) is the fail-open shape this
    review keeps finding: a null / 0 / {} / "   " value satisfies the presence test and then renders
    as an empty cell that a reader takes for "nothing to disclose". Only a non-empty string is a
    basis; everything else is treated exactly like a missing one (i.e. FAIL CLOSED to the sentinel).
    """
    return value.strip() if isinstance(value, str) and value.strip() else ""


def compute_migration_punchlist(cross_layer: List[dict],
                                security: Dict[str, dict],
                                config_hygiene: Dict[str, dict],
                                physical_health: List[dict],
                                l3_forwarding: List[dict],
                                protocol_health: List[dict],
                                stp_findings: dict,
                                health_scores: List[dict],
                                move_groups: List[dict],
                                l2: Optional[dict] = None,
                                hostname_mismatches: Optional[list] = None,
                                drift: Optional[list] = None,
                                ptp_readiness: Optional[list] = None,
                                media_risks: Optional[list] = None,
                                syslog_intelligence: Optional[dict] = None,
                                qos_audit: Optional[dict] = None,
                                software_risk: Optional[dict] = None,
                                platform_health: Optional[dict] = None,
                                device_dossiers: Optional[dict] = None,
                                protocol_assessability: Any = None,
                                vtp_safety_baseline: Optional[dict] = None,
                                vtp_safety_subject_scope: Any = None,
                                ipv6_routing_adjacency_baseline: Optional[dict] = None,
                                ipv6_routing_subject_scope: Any = None) -> List[dict]:
    """NEW-V3.23.63: the consolidated, severity-ranked migration PUNCH-LIST -- one prioritized,
    de-duplicated, per-device, per-wave table that rolls up EVERY actionable finding the run
    produced (cross-layer SPOFs, security gaps, config hygiene, L1/L3 risks, protocol health,
    STP design, device health) so a migration lead reads one 'fix-this-first, in this order'
    list instead of cross-referencing ~25 sheets. Pure synthesis of already-computed records;
    no new collection. Sorted Critical->Low; like findings are grouped (one row + a device list,
    not one row per port) so it does not 'cry wolf'."""
    wave_of: Dict[str, str] = {}
    for g in (move_groups or []):
        for h in (g.get("switches") or []):          # tolerate switches=None, not just a missing key
            wave_of.setdefault(h, g.get("group", ""))
    items: List[dict] = []

    def _clip(s: str, n: int = 400) -> str:
        # Pathological-length bound only. The old hard (detail)[:300] slice cut mid-word and silently
        # evicted a long detail's tail -- the PR-#396-review truncation class: the native-VLAN-1 row's
        # disambiguating '(The design gap counts ...)' parenthetical vanished from the punch-list copy.
        s = s or ""
        return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + " …"

    def add(severity: str, category: str, devices, title: str, detail: str, remediation: str = "",
            basis: str = "", confidence: str = "") -> None:
        devs = sorted({d for d in devices if d})
        waves = sorted({wave_of.get(d, "") for d in devs} - {""})
        it = {"severity": severity, "rank": _PUNCH_RANK.get(severity, 0),
              "category": category, "devices": devs, "wave": ", ".join(waves),
              "title": title, "detail": _clip(detail), "remediation": remediation}
        # review r10 EXIT A. A folded risk that explains WHY it carries its severity must not lose
        # that explanation in the fold. Publish it two ways, because the punch-list has two kinds of
        # consumer and only one of them reads structured keys:
        #   * structured -- `severity_basis` / `evidence_confidence`, the producer's own key names,
        #     so a renderer can put the basis in its own column/tooltip;
        #   * rendered   -- appended to `detail`, which is the ONLY free-text field every existing
        #     punch-list renderer already prints (excel.write_punchlist_sheet col 7, the explorer's
        #     punchlistCard, the design/engagement/CRD tables). Without this the fix would be inert:
        #     no shipped renderer reads a key it has never heard of.
        # Appended AFTER _clip so the disclosure can never be the part that gets truncated away
        # (each note is length-bounded on its own, so a pathological snapshot still cannot run away).
        notes = []
        if basis:
            it["severity_basis"] = basis
            notes.append("Severity basis: " + _clip(basis))
        if confidence:
            it["evidence_confidence"] = confidence
            notes.append("Evidence: " + _clip(confidence))
        if notes:
            it["detail"] = (it["detail"] + "  [" + " | ".join(notes) + "]").strip()
        cmd = _PUNCH_SOURCE_COMMAND.get(category)   # W1-3: cite the backing show-command (absent for composite cats)
        if cmd:
            it["source_command"] = cmd
        items.append(it)

    for f in (cross_layer or []):                                   # already severity + hosts + title
        add(f.get("severity", "Medium"), "Cross-layer", f.get("hosts", []),
            f.get("title", f.get("id", "")), f.get("detail", ""), "")

    secgrp: Dict[str, dict] = {}                                    # group a security check across the devices it fails on
    for host, s in (security or {}).items():
        for f in (s.get("findings") or []):
            if f.get("status") == "fail":
                e = secgrp.setdefault(f.get("id", ""), {
                    "sev": f.get("severity", "medium"), "title": f.get("title", ""),
                    "rem": f.get("remediation", ""), "detail": f.get("detail", ""), "devs": []})
                e["devs"].append(host)
    for e in secgrp.values():
        add(str(e["sev"]).capitalize(), "Security", e["devs"], e["title"], e["detail"], e["rem"])

    for host, h in (config_hygiene or {}).items():
        for u in (h.get("undefined") or []):
            add("High", "Config hygiene", [host],
                f"Undefined {u.get('kind', '')} '{u.get('name', '')}'",
                f"Referenced ({u.get('context', '')}) but never defined -- it silently does nothing.",
                "Define the referenced structure, or remove the dangling reference.")

    L3SEV = {"single-gateway": "High", "tracked-object-down": "High", "no-FHRP": "Medium"}
    l3grp: Dict[tuple, list] = {}
    for r in (l3_forwarding or []):
        for flag, sev in L3SEV.items():
            if flag in r.get("risk", ""):
                l3grp.setdefault((flag, sev), []).append(r.get("switch"))
    for (flag, sev), devs in l3grp.items():
        add(sev, "L3", devs, flag.replace("-", " "),
            f"L3 forwarding risk '{flag}' on {len(set(devs))} switch(es).",
            "Add gateway / FHRP redundancy." if ("gateway" in flag or "FHRP" in flag)
            else "Investigate the tracked object / SLA.")

    L1SEV = {"err-disabled": "High", "single-fiber-uplink": "Medium",
             "half-duplex": "Medium", "error-rate-high": "Medium"}
    l1grp: Dict[tuple, list] = {}
    for r in (physical_health or []):
        for flag, sev in L1SEV.items():
            if flag in r.get("risk", ""):
                l1grp.setdefault((flag, sev), []).append(r.get("switch"))
    for (flag, sev), devs in l1grp.items():
        add(sev, "L1", devs, flag.replace("-", " "),
            f"L1 risk '{flag}' on {len(set(devs))} switch(es).", "")

    for r in (protocol_health or []):
        if r.get("severity") in ("High", "Medium"):
            add(r["severity"], "Protocol", [r.get("switch")],
                f"{r.get('protocol', '')} {r['severity'].lower()}", r.get("detail", ""), "")

    # VTP's sparse protocol-health row is intentionally Info: a high revision is an exposure, not a
    # present outage.  Fold the separate source-bound safety owner so that distinction does not erase
    # the pre-cutover review from the consolidated Punch-List.  This produces no configuration patch.
    if vtp_safety_baseline is not None:
        vtp_view = _vtp_safety_consumer_view(
            vtp_safety_baseline, protocol_health, protocol_assessability,
            vtp_safety_subject_scope)
        for row in vtp_view["rows"]:
            if not isinstance(row, dict) or row.get("status") not in {"review", "not_verified"}:
                continue
            host = _strict_protocol_text(row.get("switch"))
            if not host:
                continue
            status = _strict_protocol_text(row.get("status"))
            high_revision = "high_revision_server" in _vtp_safety_finding_codes(row)
            add(
                "Medium",
                "VTP",
                [host],
                ("VTP high-revision cutover exposure"
                 if status == "review" and high_revision
                 else "VTP cutover safety review"
                 if status == "review"
                 else "VTP safety baseline not verified"),
                _strict_protocol_text(row.get("acceptance")),
                ("Re-run show vtp status, back up the VLAN database, and explicitly disposition "
                 "the candidate switch's domain/version/revision exposure before connection."),
            )

    # The IPv6 routing owner is blocker-only in the consolidated punch-list:
    # healthy observed adjacencies need no action, while degraded, ambiguous,
    # and unverified evidence must be resolved or dispositioned.  Deliberately
    # leave remediation empty; adjacency observations do not authorize an
    # inferred neighbor configuration or any automatic change.
    if ipv6_routing_adjacency_baseline is not None:
        ipv6_view = _ipv6_routing_consumer_view(
            ipv6_routing_adjacency_baseline, ipv6_routing_subject_scope)
        for row in ipv6_view["rows"]:
            if not isinstance(row, dict):
                continue
            host = _strict_protocol_text(row.get("switch"))
            protocol = _strict_protocol_text(row.get("protocol")) or "IPv6 Routing"
            peer = _strict_protocol_text(row.get("peer"))
            state = (
                _strict_protocol_text(row.get("state_raw"))
                or _strict_protocol_text(row.get("state"))
            )
            status = _strict_protocol_text(row.get("status"))
            acceptance = _strict_protocol_text(row.get("acceptance"))
            if (not host or status not in {"degraded", "review", "not_verified"}
                    or not acceptance):
                continue
            identity = f"{protocol} {peer or 'subject'}"
            if state:
                identity += f" state {state}"
            add(
                "High" if status == "degraded" else "Medium",
                "IPv6 Routing",
                [host],
                {
                    "degraded": f"{identity} degraded before cutover",
                    "review": f"{identity} requires pre-cutover review",
                    "not_verified": f"{identity} baseline not verified",
                }[status],
                acceptance,
                "",
            )

    sf = stp_findings or {}
    for m in sf.get("misaligned", []):
        add("Medium", "STP", [m.get("root")] + list(m.get("gateways", [])),
            f"STP root != gateway (VLAN {m.get('vlan')})",
            "The spanning-tree root is not on the VLAN's gateway switch -- traffic to the default gateway hairpins.",
            "Align the STP root priority with the active gateway switch.")
    for a in sf.get("accidental", []):
        add("Low", "STP", [a.get("host")], f"Accidental root (VLAN {a.get('vlan')})",
            "Rooted on the default priority -- elected on a MAC tiebreak, so it can move on a cutover.",
            "Set a deliberate root-bridge priority on the intended switch.")

    for r in (health_scores or []):
        if r.get("band") in ("Critical", "Poor"):
            add("High" if r["band"] == "Critical" else "Medium", "Health", [r.get("switch")],
                f"{r['band']}-health switch", f"Health score {r.get('score', '')} ({r['band']} band).",
                "Resolve the deductions above before migrating this device.")

    # NEW-V3.23.64: fold in the cross-switch L2 checks that previously lived only in the explorer
    # (addressing conflicts, FHRP consistency, trunk native-VLAN, link duplex/speed) -- passed in as
    # `l2` (computed by the excel layer in main()) so the punch-list is genuinely complete.
    ll = l2 or {}
    for d in (ll.get("addressing") or {}).get("dup_ip", []):
        add("High", "Addressing", [w[0] for w in d.get("where", [])],
            f"Duplicate L3 IP {d.get('ip', '')}",
            "The same physical IP is configured on >=2 interfaces -- an L3 address clash.",
            "Re-IP one of the interfaces before the merge / cutover.")
    for d in (ll.get("addressing") or {}).get("dup_subnet", []):
        vrf = f" (VRF {d['vrf']})" if d.get("vrf") else ""
        add("Medium", "Addressing", [w[0] for w in d.get("where", [])],
            f"Overlapping subnet {d.get('net', '')}",
            f"One subnet sits behind multiple VLANs{vrf} -- ambiguous routing.",
            "Consolidate or re-subnet before cutover.")
    for fr in (ll.get("fhrp") or []):
        state = fr.get("status")
        hosts = [m.get("host") for m in fr.get("members", [])]
        issues = "; ".join(fr.get("issues", []))
        if state == "review":
            add(
                "Medium", "FHRP", hosts,
                f"FHRP domain composition review (VLAN {fr.get('vid')})",
                "Intended FHRP membership is unresolved. " + issues,
                "Verify intended members and simultaneous roles, then explicitly disposition the "
                "domain-composition review before cutover; do not auto-configure gateways from this evidence.",
            )
        elif state == "not_verified":
            add(
                "Medium", "FHRP", hosts,
                f"FHRP redundancy domain not verified (VLAN {fr.get('vid')})",
                issues or "The authoritative FHRP redundancy-domain receipt was not verified.",
                "Re-collect and validate the domain receipt before deciding intended membership or remediation.",
            )
        elif state == "degraded":
            add(
                "High", "FHRP", hosts,
                f"FHRP redundancy degraded (VLAN {fr.get('vid')})",
                issues,
                "Restore or explicitly disposition the definite source-bound local FHRP fault before cutover.",
            )
        else:
            # Backward compatibility for direct callers still carrying the pre-typed legacy row shape.
            add("High", "FHRP", hosts,
                f"Fake FHRP redundancy (VLAN {fr.get('vid')})", issues,
                "Standardize the FHRP protocol / group / virtual IP across the VLAN's gateways.")
    for t in (ll.get("trunk_native") or []):
        add("Medium", "Trunk", [t.get("a_host"), t.get("b_host")],
            f"Native-VLAN mismatch ({t.get('a_native')} vs {t.get('b_native')})",
            f"{t.get('a_host')} {t.get('a_port')} (native {t.get('a_native')}) <-> "
            f"{t.get('b_host')} {t.get('b_port')} (native {t.get('b_native')}) -- untagged L2 leak / VLAN-hopping exposure.",
            "Set a consistent native VLAN on both trunk ends.")
    for lp in (ll.get("link_phy") or []):
        what = "duplex" if lp.get("duplex") else "speed"
        add("Medium", "Link L1", [lp.get("a_host"), lp.get("b_host")],
            f"{what.capitalize()} mismatch on inter-switch link",
            f"{lp.get('a_host')} {lp.get('a_port')} <-> {lp.get('b_host')} {lp.get('b_port')} -- "
            f"{what} differs (late collisions / CRC errors, link up but degraded).",
            "Set matching duplex/speed (or autoneg) on both ends.")

    # NEW-V3.23.68: inventory/identity data quality -- a device collected under a name that differs
    # from its own configured hostname reconciles wrong in the topology (phantom split node) and
    # breaks any hostname-keyed cutover scripting.
    for hm in (hostname_mismatches or []):
        add("Medium", "Inventory", [hm.get("inventory")],
            f"Inventory name != device hostname ({hm.get('inventory')} vs {hm.get('reported')})",
            f"Collected as '{hm.get('inventory')}' but the device reports its hostname as "
            f"'{hm.get('reported')}' -- it reconciles as a duplicate/phantom node in the topology.",
            "Correct the inventory/devices.json name to match the device's configured hostname.")

    # NEW-V3.23.93: fold in the false-health / operational-drift findings (compute_operational_drift)
    # so the executive punch-list also carries the traps a green control plane hides.
    for d in (drift or []):
        add(d.get("severity", "Medium"), d.get("category", "False-health"), d.get("devices", []),
            d.get("title", ""), d.get("detail", ""), d.get("remediation", ""))

    # NEW-V3.23.108: fold in PTP / media-timing readiness (compute_ptp_readiness) so the broadcast
    # timing gap (PTP enabled but not boundary-clocked) is in the prioritized action list.
    for d in (ptp_readiness or []):
        add(d.get("severity", "Medium"), d.get("category", "Timing/PTP"), d.get("devices", []),
            d.get("title", ""), d.get("detail", ""), d.get("remediation", ""))

    # NEW-V3.23.115: fold in multicast/media-fabric findings (MAC-aliasing / IGMP querier gaps from
    # compute_multicast_intelligence) so the broadcast-fabric risks are in the prioritized action list.
    #
    # review r10 EXIT A. compute_multicast_intelligence raises a mac-alias risk from Medium to High
    # purely on a CURATED on-air classification (analyze.py :2774) and publishes exactly why, in
    # `severity_basis` + `evidence_confidence`. This fold used to drop both keys, so the punch-list --
    # and everything downstream of it (the workbook Punch-List sheet, the explorer, the executive
    # brief's severity counts, the engagement/CRD packs) -- carried a High with its basis erased, i.e.
    # an unverified registry hint presented in the same voice as an IANA-assigned fact.
    # Carry the basis through, and FAIL CLOSED on absence: a risk that publishes no usable basis
    # (older snapshot, or a null/non-string value) is rendered basis-NOT-published, never as though
    # the severity had been measured. Applied to EVERY media risk, not a hand-picked kind list --
    # querier-gap genuinely publishes no basis today, and saying so is honest rather than noisy.
    for d in (media_risks or []):
        add(d.get("severity", "Medium"), "Multicast/Media", d.get("devices", []),
            d.get("title", ""), d.get("detail", ""), d.get("remediation", ""),
            basis=_usable_text(d.get("severity_basis")) or PUNCH_BASIS_UNPUBLISHED,
            confidence=_usable_text(d.get("evidence_confidence")) or PUNCH_CONFIDENCE_UNPUBLISHED)

    # NEW-V3.23.169: fold in the V3.23.164-.167 axes so they reach the decision layer. Each axis
    # already aggregates per host; here like findings are GROUPED by kind across devices (the same
    # cry-wolf rule the security fold uses) -- one row + a device list, never one row per device.
    # Fleet-level rows (host '(fleet)') carry no device so they never pollute per-device wave maps.
    def _fold_axis(findings, category):
        # V3.23.171: every axis now emits the common {label, detail} shape (software_risk
        # aliases its surface/why into them), so the fold needs no per-axis adapter.
        bykind: Dict[str, dict] = {}
        for f in (findings or []):
            if not isinstance(f, dict):
                continue
            k = f.get("kind") or f.get("label") or ""
            g = bykind.setdefault(k, {"severity": f.get("severity", "Medium"),
                                      "title": f.get("label") or k,
                                      "devices": [], "details": [],
                                      "remediation": f.get("recommendation", "")})
            host = (f.get("host") or "").strip()
            if host and host != "(fleet)":
                g["devices"].append(host)
            d = f.get("detail")
            if d:
                g["details"].append(str(d))
        for k in sorted(bykind):
            g = bykind[k]
            n_dev = len(set(g["devices"]))
            detail = (f"{n_dev} device(s). " if n_dev > 1 else "") + (g["details"][0] if g["details"] else "")
            add(g["severity"], category, g["devices"], g["title"], detail, g["remediation"])

    _fold_axis((syslog_intelligence or {}).get("detections"), "Operational logs")
    _fold_axis((qos_audit or {}).get("findings"), "QoS")
    # V3.23.170: the CIS Security fold above already carries rows for telnet-on-vty and v1/v2c
    # SNMP from the same config lines -- folding software_risk's twins gave one issue two
    # prioritized rows at two severities (the de-dup contract violation the max review caught).
    # Those kinds stay on the Software Risk sheet / brief (where the advisory context lives);
    # the punch-list keeps the single CIS action row.
    _SWRISK_CIS_TWINS = ("telnet-vty", "snmp-v2c-rw", "snmp-v2c-ro")
    _fold_axis([f for f in ((software_risk or {}).get("findings") or [])
                if isinstance(f, dict) and f.get("kind") not in _SWRISK_CIS_TWINS],
               "Software exposure")
    _fold_axis((platform_health or {}).get("findings"), "Platform capacity")

    # NEW-V3.23.172: compound-risk patterns from the Device Risk Register. These are NOT
    # duplicates of the per-axis rows above -- the finding IS the coincidence (independent
    # risks stacked on one asset), which no single-axis row carries. CR-coded titles keep
    # them recognizably distinct from their contributing legs.
    for d in ((device_dossiers or {}).get("per_device") or []):
        if not isinstance(d, dict):
            continue
        for c in (d.get("compound") or []):
            if isinstance(c, dict):
                add(c.get("severity", "Medium"), "Compound risk", [d.get("host")],
                    f"{c.get('code', '')}: {c.get('title', '')}", c.get("basis", ""),
                    "Stacked independent risks on one asset — clear at least one leg "
                    "before this device's migration window.")

    items.sort(key=lambda x: (-x["rank"], x["category"], x["title"]))
    for i, it in enumerate(items, 1):
        it["priority"] = i
    return items


# =============================================================================
# Application & Network Intelligence (NEW-V3.23.112). The workload-synthesis layer:
# turn the already-computed device / endpoint / service facts into named APPLICATION
# DOMAINS, each with footprint (switches / VLANs / endpoints), a criticality tier, a
# health rollup, its migration-wave span, and a standards-grounded migration playbook
# + per-domain and cross-domain migration RISKS. Pure read of prior layers
# (endpoint_identity, endpoint_dependencies, service_map, health_scores, move_groups,
# punchlist) -- NO new collection; it lights up on the current snapshot.
#
# Evidence discipline (the tool's doctrine): a switch is attributed to a domain by a
# DELIBERATE hostname role token, by OBSERVED PTP/multicast (Confirmed), or by its
# DOMINANT endpoint class (Inferred) -- never guessed; the basis travels in `evidence`.
# Unclassified switches fall to a General bucket rather than being over-claimed as a
# media fabric (in this facility almost every hostname contains "BC", so "BC" is NOT a
# media signal). The risk rules are grounded in real broadcast / media-over-IP practice:
#   * SMPTE ST 2059 / Arista M&E PTP   -- media-path switches should be boundary clocks;
#     plain-multicast PTP (no boundary clock) is the timing risk.
#   * RFC 4541 (IGMP/MLD snooping)      -- exactly one querier per VLAN; without it
#     membership times out (multicast floods or blackholes). New cutover rule: a querier
#     that lands in a DIFFERENT migration wave than its VLAN's switches breaks multicast
#     on cutover; two distinct queriers on one VLAN is a split-brain hygiene fault.
#   * SMPTE ST 2022-7 (seamless protect) -- red/blue dual path must never go down
#     together -> on-air domains that span waves must be make-before-break.
#   * Avid NEXIS Network & Switch Guide  -- dual NIC legs (same speed/subnet), Rx
#     flow-control, no oversubscription -> storage dual-leg validation when legs split.
# =============================================================================
_APP_TIER_RANK = {"On-air critical": 0, "Production": 1, "Support": 2}
_APP_SEV_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}
_APP_BAND_RANK = {"Critical": 0, "Poor": 1, "Fair": 2, "Good": 3, "Excellent": 4, "Insufficient Data": 5}
# Migration-criticality weights (NEW-V3.23.114). Higher total = more critical/risky = cut over LATER with
# more safeguards; lowest = a safe pilot. Tunable in one place; documented heuristic, not a hard schedule.
_CRIT_WEIGHTS = {
    "tier": {"On-air critical": 40, "Production": 24, "Support": 8},
    "band": {"Critical": 18, "Poor": 11, "Fair": 5, "Good": 0, "Excellent": 0, "Insufficient Data": 6},
    "health_cap": 12, "high_risk": 5, "risk": 2, "risk_cap": 16,
    "coupling": 14, "spans_waves": 5, "ptp": 6, "size": 6, "last_threshold": 80,
}

# Ordered domain taxonomy. `token` (regex, matched case-insensitively on the hostname) is the
# strongest, most deliberate signal and is tried FIRST in list order; `classes` lets a switch's
# dominant endpoint class stand in when no token matches. Order resolves the real overlaps in this
# fleet (e.g. a management switch named "...-MGM-STD..." is Management, not Studio -> mgmt precedes
# studio). The Media Fabric domain (below) is attributed by observed PTP/multicast, not a token.
_APP_DOMAINS = [
    {"id": "audio", "name": "Audio over IP (Dante / AES67)", "tier": "On-air critical",
     "token": r"DANTE|AES67", "classes": {"Audio (Dante/AES67)"}, "needs_ptp": True, "dual_path": True,
     "validation": ["Dante/AES67 PTP lock on BOTH networks before and after the move",
                    "flow subscriptions / channel routing intact post-move"],
     "standard": "AES67 / SMPTE ST 2110-30 / ST 2059"},
    {"id": "robotics", "name": "Robotics & Camera Control", "tier": "On-air critical",
     "token": r"ROBOTIC", "classes": {"Robotics", "Camera"}, "needs_ptp": False, "dual_path": False,
     "validation": ["control + return path up", "PoE restored (often on-air critical)"],
     "standard": ""},
    {"id": "mcr", "name": "Master Control & Playout (MCR)", "tier": "On-air critical",
     "token": r"\bMCRR?|MASTER.?CONTROL|PLAYOUT", "classes": set(), "needs_ptp": False, "dual_path": True,
     "validation": ["playout / automation reachability", "router-control + on-air signal path validated"],
     "standard": ""},
    {"id": "ingest", "name": "Ingest / Teleport / Satellite", "tier": "Production",
     "token": r"INGEST|INGR|TELEPORT|TE421|SATR|\bSAT\b|INTERIM", "classes": set(),
     "needs_ptp": False, "dual_path": False,
     "validation": ["record / ingest chain reachable", "satellite / teleport feeds locked"],
     "standard": ""},
    {"id": "storage", "name": "Shared Storage & Replay (Avid NEXIS / EVS / Render)", "tier": "Production",
     "token": r"NEXIS|\bAVID|ISIS|\bEVS|RENDERFARM|RENDER", "classes": {"Storage"},
     "needs_ptp": False, "dual_path": True,
     "validation": ["both NIC legs up (same speed/subnet)",
                    "Rx flow-control (LFC) preserved; no new uplink oversubscription",
                    "datastore / workspace mounts verified before and after"],
     "standard": "Avid NEXIS Network & Switch Guide"},
    {"id": "investigative", "name": "Investigative / News", "tier": "Production",
     "token": r"INVESTIGATIV|\bNEWS", "classes": set(), "needs_ptp": False, "dual_path": False,
     "validation": ["editorial / craft-edit reachability"],
     "standard": ""},
    {"id": "mgmt", "name": "Management / Out-of-Band", "tier": "Support",
     "token": r"MGMT|MGM-|\bMGM\b|\bOOB\b|SANDBOX", "classes": set(), "needs_ptp": False, "dual_path": False,
     "validation": ["management / OOB reachability (do not strand a device's only management path)"],
     "standard": ""},
    {"id": "studio", "name": "Studio / Sets / LED", "tier": "Production",
     "token": r"\bSTD|SET\d|LED|STUDIO", "classes": set(), "needs_ptp": False, "dual_path": False,
     "validation": ["set / LED processors reachable", "camera + return feeds validated"],
     "standard": ""},
    {"id": "compute", "name": "Compute / Virtualization", "tier": "Support",
     "token": "", "classes": {"VM / Hypervisor", "Server", "Database"}, "needs_ptp": False, "dual_path": False,
     "validation": ["guest / app reachability", "NIC-team peer leg stays up", "shared storage stays reachable"],
     "standard": ""},
]
# Media Fabric: attributed by observed PTP/multicast evidence (no reliable hostname token here).
_APP_MEDIA = {"id": "media", "name": "Media Fabric (SMPTE ST 2110)", "tier": "On-air critical",
              "needs_ptp": True, "dual_path": True,
              "validation": ["PTP clock lock on BOTH red/blue networks (ST 2059) before and after the move",
                             "IGMP joins re-established for every ST 2110 essence flow",
                             "ST 2022-7 dual-path: never drop both paths in the same window (make-before-break)"],
              "standard": "SMPTE ST 2110 / ST 2059 / ST 2022-7"}
_APP_GENERAL = {"id": "general", "name": "General / Back-office (unclassified)", "tier": "Support",
                "needs_ptp": False, "dual_path": False,
                "validation": ["No application-specific signal collected -- classify these switches with the "
                               "facility owner before scheduling the cutover."],
                "standard": ""}
for _d in _APP_DOMAINS:
    _d["rx"] = re.compile(_d["token"], re.I) if _d.get("token") else None


def compute_application_intelligence(all_interfaces: Dict[str, Dict[str, InterfaceData]],
                                     endpoint_identity: Optional[list] = None,
                                     endpoint_dependencies: Optional[dict] = None,
                                     service_map: Optional[dict] = None,
                                     health_scores: Optional[list] = None,
                                     move_groups: Optional[list] = None,
                                     punchlist: Optional[list] = None,
                                     subnet_intelligence: Optional[dict] = None) -> dict:
    """NEW-V3.23.112: synthesize the prior layers into named APPLICATION DOMAINS (workloads) with
    footprint, criticality tier, health rollup, migration-wave span, a standards-grounded migration
    playbook, and per-domain + cross-domain migration RISKS. NEW-V3.23.113: also connect the domains
    into a dependency GRAPH -- `edges` (physical-link / shared-subnet / dual-homed couplings, each
    confidence-tagged) + `keystones` (the most cross-coupled domains = widest migration blast radius)
    + per-domain `degree`/`neighbors`, plus dependency-driven cross-domain risks. Pure read;
    deterministic (sorted output); tolerant of empty / oddly-typed inputs. See the block comment above
    for the research grounding. Returns {domains, summary, cross_domain_risks, edges, keystones,
    taxonomy_version}."""
    from collections import Counter, defaultdict
    hosts = sorted(all_interfaces or {})
    ident = endpoint_identity or []
    dep = endpoint_dependencies or {}
    sm = service_map or {}
    mc = sm.get("multicast") or {}
    ptp = mc.get("ptp") or {}
    queriers = mc.get("igmp_queriers") or []
    # the broadcast/timing multicast groups (PTP-AV etc.) to attribute to the media/audio domains
    classified = [g for g in (mc.get("classified_groups") or [])
                  if g.get("broadcast") or "PTP" in (g.get("name") or "")
                  or (g.get("category") or "") == "Broadcast-AV"]
    band_of = {r.get("switch"): r.get("band", "") for r in (health_scores or [])}
    wave_of: Dict[str, str] = {}
    for g in (move_groups or []):
        for h in (g.get("switches") or []):              # tolerate switches=None, not just a missing key
            wave_of.setdefault(h, g.get("group") or "")  # coerce a None group label to "" (move_groups may omit it)

    # ---- per-host endpoint classes + counts (from the identity layer) ----
    classes_by_host: Dict[str, "Counter"] = defaultdict(Counter)
    eps_by_host: Dict[str, int] = defaultdict(int)
    for r in ident:
        h = r.get("host", "")
        eps_by_host[h] += 1
        cls = r.get("endpoint_class", "Unknown")
        if cls and cls != "Unknown":
            classes_by_host[h][cls] += 1

    # ---- per-host VLANs (access-port VLAN + SVI) and media evidence (Confirmed) ----
    def _host_vlans(h: str) -> set:
        vs = set()
        for port, d in (all_interfaces.get(h) or {}).items():
            v = (getattr(d, "vlan", "") or "").strip()
            if v.isdigit():
                vs.add(v)
            m = re.match(r"^Vlan(\d+)$", str(port), re.I)
            if m:
                vs.add(m.group(1))
        return vs
    host_vlans = {h: _host_vlans(h) for h in hosts}
    media_host = {h: bool(any(getattr(d, "multicast_info", "") for d in (all_interfaces.get(h) or {}).values())
                          or h in ptp) for h in hosts}

    # ---- class -> domain id (the fallback when no token matches) ----
    cls_to_dom: Dict[str, str] = {}
    for d in _APP_DOMAINS:
        for c in (d.get("classes") or ()):
            cls_to_dom.setdefault(c, d["id"])
    domains_by_id = {d["id"]: d for d in _APP_DOMAINS}
    domains_by_id[_APP_MEDIA["id"]] = _APP_MEDIA
    domains_by_id[_APP_GENERAL["id"]] = _APP_GENERAL

    # ---- assign each switch to ONE primary domain (token -> media evidence -> class -> general) ----
    members: Dict[str, List[str]] = defaultdict(list)
    evidence_by_dom: Dict[str, "Counter"] = defaultdict(Counter)
    for h in hosts:
        hu = h.upper()
        chosen = None
        for d in _APP_DOMAINS:
            if d["rx"] and d["rx"].search(hu):
                chosen = (d["id"], "hostname role token"); break
        if not chosen and media_host[h]:
            chosen = ("media", "PTP / multicast active on this switch (Confirmed)")
        if not chosen and classes_by_host.get(h):
            dom_cls = classes_by_host[h].most_common(1)[0][0]
            did = cls_to_dom.get(dom_cls)
            if did:
                chosen = (did, f"dominant endpoint class '{dom_cls}'")
        if not chosen:
            chosen = ("general", "no application-specific signal")
        members[chosen[0]].append(h)
        evidence_by_dom[chosen[0]][chosen[1]] += 1

    def _risk(sev, title, detail, remediation, standard=""):
        return {"severity": sev, "title": title, "detail": detail,
                "remediation": remediation, "standard": standard}

    dual = dep.get("dual_homed") or []

    out_domains: List[dict] = []
    for did, mhosts in members.items():
        spec = domains_by_id[did]
        mhosts = sorted(mhosts)
        mset = set(mhosts)
        vlans = set()
        for h in mhosts:
            vlans |= host_vlans.get(h, set())
        vlans_sorted = sorted(vlans, key=lambda x: int(x))
        ep_count = sum(eps_by_host.get(h, 0) for h in mhosts)
        cls_counter: "Counter" = Counter()
        for h in mhosts:
            cls_counter.update(classes_by_host.get(h, {}))
        bands = [band_of.get(h, "") for h in mhosts]
        n_crit = sum(1 for b in bands if b == "Critical")
        n_poor = sum(1 for b in bands if b == "Poor")
        # 'Insufficient Data' is a COLLECTION GAP, not a health verdict, so it is excluded from the
        # worst-band rollup and counted separately -- the exec-brief / migration-scenario convention.
        # _APP_BAND_RANK ranks it 5, i.e. BETTER than Excellent (4), so `min(..., key=rank)` could never
        # select it: a domain of 1 Excellent + 4 never-collected switches published
        # `worst_band: Excellent`. Worse, _CRIT_WEIGHTS['band'] is applied to worst_band ALONE, so the
        # deliberate 'Insufficient Data': 6 weight (author-set between Fair 5 and Poor 11 -- uncollected
        # devices were MEANT to raise criticality) could never fire while any scored band existed. The
        # 80%-unassessed domain therefore scored LOWEST and was recommended cutover order 1 / "Pilot --
        # start here to fail-fast and learn": the least-safeguarded wave, chosen because we knew least
        # about it. Only score health where health was measured; disclose the rest. (band_of empty =
        # health scoring not supplied at all -> nothing to disclose, no cry-wolf.)
        n_unassessed = sum(1 for b in bands if b in ("", "Insufficient Data")) if band_of else 0
        worst = min((b for b in bands if b and b != "Insufficient Data"),
                    key=lambda b: _APP_BAND_RANK.get(b, 99), default="")
        waves = sorted({wave_of.get(h, "") for h in mhosts} - {""})
        spans = len(waves) > 1
        ptp_hosts = [h for h in mhosts if h in ptp]
        ptp_present = bool(ptp_hosts)
        ptp_bc = any((ptp.get(h) or {}).get("operational") for h in ptp_hosts)
        hi_find = [f for f in (punchlist or [])
                   if f.get("severity") in ("Critical", "High") and (mset & set(f.get("devices") or []))]
        dsplit = [d for d in dual
                  if spec.get("dual_path") and d.get("split_across_groups") and (set(d.get("switches") or []) & mset)]
        oncrit = spec["tier"] == "On-air critical"

        risks: List[dict] = []
        if spec.get("needs_ptp") and ptp_present and not ptp_bc:
            risks.append(_risk("High" if oncrit else "Medium", "Media timing not boundary-clocked",
                f"PTP is present on {len(ptp_hosts)} switch(es) in this domain but none is an active boundary/"
                "transparent clock -- timing is distributed as plain multicast, which does not scale for ST 2110.",
                "Enable PTP boundary-clock mode on the media-path switches and verify clock lock (offset within "
                "spec) on both red/blue networks before cutover.", spec.get("standard") or "SMPTE ST 2059"))
        if oncrit and spans:
            risks.append(_risk("High", "On-air-critical domain split across migration waves",
                f"This domain's switches are scheduled across {len(waves)} waves ({', '.join(waves)}); on-air media "
                "paths (incl. ST 2022-7 red/blue) must not lose both legs together.",
                "Sequence make-before-break: keep one redundant path/leg in service throughout and validate the "
                "on-air signal between waves.", "SMPTE ST 2022-7"))
        if dsplit:
            risks.append(_risk("High", f"Dual-homed endpoint leg(s) split across waves ({len(dsplit)})",
                "Dual-homed endpoints in this domain have their two legs on switches in different waves; cutting the "
                "wrong wave drops both legs / breaks redundancy.",
                "Make-before-break the legs; for storage validate both NIC legs (same speed/subnet) + Rx flow-control "
                "and no new oversubscription.", spec.get("standard") or "SMPTE ST 2022-7"))
        if n_crit or n_poor:
            risks.append(_risk("Medium", f"Domain rides {n_crit + n_poor} switch(es) in Critical/Poor health",
                f"{n_crit} Critical + {n_poor} Poor-band switch(es) carry this workload.",
                "Resolve the per-switch health deductions before migrating this domain.", ""))
        if n_unassessed:
            risks.append(_risk("Medium",
                f"Domain rides {n_unassessed} switch(es) with NO health evidence",
                f"{n_unassessed} of {len(mhosts)} switch(es) carrying this workload were never collected / "
                "banded 'Insufficient Data', so their condition is unknown — the health rollup above "
                "describes only the assessed remainder and is not a clean bill for the domain.",
                "Collect these devices before scheduling this domain's cutover; do not pilot a domain you "
                "cannot see.", ""))
        if hi_find:
            cats = ", ".join(sorted({f.get("category", "") for f in hi_find})[:5])
            risks.append(_risk("Low", f"{len(hi_find)} High/Critical punch-list item(s) on this domain's switches",
                f"Open High/Critical items (categories: {cats}) intersect this domain's switches.",
                "See the Migration Punch-List for the prioritized, per-device fix order.", ""))
        risks.sort(key=lambda r: _APP_SEV_RANK.get(r["severity"], 9))

        dom_groups = classified if did in ("media", "audio") else []
        out_domains.append({
            "id": did, "domain": spec["name"], "tier": spec["tier"],
            "switches": mhosts, "switch_count": len(mhosts),
            "vlans": vlans_sorted[:40], "vlan_count": len(vlans_sorted),
            "endpoint_count": ep_count, "classes": dict(cls_counter.most_common(6)),
            "media_groups": [{"group": g.get("group", ""), "name": g.get("name", ""),
                              "category": g.get("category", "")} for g in dom_groups][:20],
            "ptp_present": ptp_present, "ptp_boundary_clocked": ptp_bc,
            "health": {"worst_band": worst, "n_critical": n_crit, "n_poor": n_poor},
            "waves": waves, "spans_waves": spans,
            "evidence": "; ".join(f"{e} x{n}" if n > 1 else e
                                  for e, n in evidence_by_dom[did].most_common(3)),
            "validation": list(spec.get("validation") or []), "standard": spec.get("standard", ""),
            "risks": risks, "n_high_risk": sum(1 for r in risks if r["severity"] in ("Critical", "High")),
        })
    out_domains.sort(key=lambda d: (_APP_TIER_RANK.get(d["tier"], 9), -d["switch_count"], d["domain"]))

    # ---- cross-domain: IGMP querier continuity / split-brain (RFC 4541) ----
    vlan_hosts: Dict[str, set] = defaultdict(set)
    for h in hosts:
        for v in host_vlans.get(h, set()):
            vlan_hosts[v].add(h)
    # Group queriers by (vlan, querier /24) so the SAME VLAN id reused in independent L2 domains
    # (e.g. VLAN 12 with a querier in 10.202.12.0 AND another in 10.203.12.0) is NOT mis-flagged as a
    # split-brain -- only >1 distinct querier WITHIN one subnet is a real RFC-4541 fault. q_hosts keeps
    # the per-VLAN querier switches for the wave-continuity rule.
    q_hosts: Dict[str, set] = defaultdict(set)
    q_sub_ips: Dict[str, Dict[str, set]] = defaultdict(lambda: defaultdict(set))
    q_sub_hosts: Dict[str, Dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for q in queriers:
        v = str(q.get("vlan", "")).strip()
        ip = (q.get("querier") or "").strip()
        sw = q.get("switch")
        if not v or not ip:
            continue
        parts = ip.split(".")
        sub = ".".join(parts[:3]) if len(parts) == 4 else ip
        q_sub_ips[v][sub].add(ip)
        if sw:
            q_hosts[v].add(sw); q_sub_hosts[v][sub].add(sw)
    host_dom = {}
    for did, mhosts in members.items():
        for h in mhosts:
            host_dom[h] = did
    oncrit_hosts = {h for h, d in host_dom.items() if domains_by_id[d]["tier"] == "On-air critical"}

    cross: List[dict] = []
    for v in sorted(vlan_hosts, key=lambda x: int(x)):
        mh = vlan_hosts[v]
        vwaves = sorted({wave_of.get(h, "") for h in mh} - {""})
        if v in q_hosts and len(vwaves) > 1 and (mh & oncrit_hosts):
            qh = sorted(q_hosts[v]); qw = sorted({wave_of.get(h, "") for h in qh} - {""})
            cross.append({"severity": "High", "kind": "querier-wave", "vlan": v,
                "querier_switches": qh[:6], "querier_waves": qw, "vlan_waves": vwaves,
                "title": f"IGMP querier for VLAN {v} may not survive the cutover",
                "detail": f"VLAN {v} carries on-air media and spans waves {', '.join(vwaves)}; its IGMP querier is "
                          f"on {', '.join(qh[:6])} (wave {', '.join(qw) or '?'}). If the querier switch moves/reboots "
                          "independently, multicast membership times out on the other wave's switches (flood/blackhole).",
                "remediation": f"Keep an IGMP querier active on VLAN {v} throughout the cutover (querier on a switch "
                          "that stays up, or a transient secondary) and re-verify joins after each wave.",
                "standard": "RFC 4541"})
    for v in sorted(q_sub_ips, key=lambda x: int(x) if x.isdigit() else 0):
        for sub, ips in q_sub_ips[v].items():
            if len(ips) > 1:
                cross.append({"severity": "Medium", "kind": "querier-split", "vlan": v,
                    "subnet": f"{sub}.0/24", "querier_ips": sorted(ips)[:6],
                    "querier_switches": sorted(q_sub_hosts[v][sub])[:6], "querier_waves": [], "vlan_waves": [],
                    "title": f"Multiple IGMP queriers on VLAN {v} ({sub}.0/24)",
                    "detail": f"VLAN {v} in subnet {sub}.0/24 has {len(ips)} distinct querier IPs "
                              f"({', '.join(sorted(ips)[:6])}). RFC 4541 expects exactly one querier per L2 domain; "
                              "two produce inconsistent membership and intermittent multicast loss.",
                    "remediation": "Leave exactly one querier active in this subnet (lowest IP wins the election); "
                              "disable the others.", "standard": "RFC 4541"})
    # ---- inter-domain dependency edges (NEW-V3.23.113) -----------------------------------------
    # Project per-switch couplings up to domain PAIRS using strong, confidence-tagged signals only:
    # physical inter-switch links (Confirmed), shared subnets (Inferred-high -- subnets are globally
    # unique so no VLAN-id-reuse trap), and dual-homed NIC-teams whose legs span domains (Confirmed).
    # Media multicast is folded in as an enrichment NOTE on edges that touch the media fabric rather
    # than an invented edge (no per-(S,G) OIL collected -> honest). Undirected pairs.
    name_of = {d["id"]: d["domain"] for d in out_domains}
    edge_acc: Dict[Tuple[str, str], "Counter"] = defaultdict(Counter)

    def _bump(a, b, kind, w=1):
        if a and b and a != b:
            edge_acc[tuple(sorted((a, b)))][kind] += w

    for L in compute_topology_links(all_interfaces):                          # physical links
        _bump(host_dom.get(L.get("a_host")), host_dom.get(L.get("b_host")), "physical-link")
    subnet_doms: Dict[str, set] = defaultdict(set)                            # shared subnets
    for r in ((subnet_intelligence or {}).get("per_device") or []):
        dom = host_dom.get(r.get("host"))
        if not dom:
            continue
        for s in (r.get("destination_subnets") or []):
            subnet_doms[s].add(dom)
        for s in (r.get("served_subnets") or []):
            sub = s.get("subnet") if isinstance(s, dict) else s
            if sub:
                subnet_doms[sub].add(dom)
    for doms in subnet_doms.values():
        dl = sorted(doms)
        for i in range(len(dl)):
            for j in range(i + 1, len(dl)):
                _bump(dl[i], dl[j], "shared-subnet")
    for dh in (dep.get("dual_homed") or []):                                  # dual-homed NIC-teams
        dl = sorted({host_dom.get(s) for s in (dh.get("switches") or [])} - {None})
        for i in range(len(dl)):
            for j in range(i + 1, len(dl)):
                _bump(dl[i], dl[j], "dual-homed")

    _ECONF = {"physical-link": "Confirmed-high", "dual-homed": "Confirmed", "shared-subnet": "Inferred-high"}
    edges: List[dict] = []
    for (a, b), kinds in edge_acc.items():
        weight = sum(kinds.values())
        conf = ("Confirmed-high" if "physical-link" in kinds
                else "Confirmed" if "dual-homed" in kinds else "Inferred-high")
        media = a == "media" or b == "media"
        parts = []
        if kinds.get("physical-link"): parts.append(f"{kinds['physical-link']} inter-switch link(s)")
        if kinds.get("shared-subnet"): parts.append(f"{kinds['shared-subnet']} shared subnet(s)")
        if kinds.get("dual-homed"): parts.append(f"{kinds['dual-homed']} dual-homed endpoint(s)")
        note = "Make-before-break across this boundary; " if kinds.get("dual-homed") else ""
        if media:
            note += ("Media multicast may traverse this coupling -- preserve IGMP snooping/querier + PTP "
                     "across the cutover.")
        edges.append({"source": name_of.get(a, a), "target": name_of.get(b, b),
                      "source_id": a, "target_id": b, "kinds": sorted(kinds.keys()),
                      "weight": weight, "confidence": conf, "media": media,
                      "detail": "; ".join(parts), "migration_note": note.strip()})
    edges.sort(key=lambda e: (-e["weight"], e["source"], e["target"]))

    deg: "Counter" = Counter(); neigh: Dict[str, set] = defaultdict(set)
    for e in edges:
        deg[e["source_id"]] += e["weight"]; deg[e["target_id"]] += e["weight"]
        neigh[e["source_id"]].add(e["target"]); neigh[e["target_id"]].add(e["source"])
    for d in out_domains:
        d["degree"] = deg.get(d["id"], 0)
        d["neighbors"] = sorted(neigh.get(d["id"], set()))
    keystones = [{"domain": name_of.get(did, did), "degree": dg, "neighbors": sorted(neigh.get(did, set()))}
                 for did, dg in deg.most_common(5)]

    # dependency-driven cross-domain risks (fold into the same list as the querier risks)
    if keystones and keystones[0]["degree"] > 0:
        k = keystones[0]
        cross.append({"severity": "Low", "kind": "keystone-domain", "vlan": "",
            "title": f"{k['domain']} is the most cross-coupled domain (keystone)",
            "detail": f"{k['domain']} couples to {len(k['neighbors'])} other domain(s) (weighted degree "
                      f"{k['degree']}): {', '.join(k['neighbors'][:8])}. It has the widest cross-domain blast radius.",
            "remediation": "Sequence this domain deliberately (not as an early pilot); validate every coupled "
                           "domain after its cutover.", "standard": ""})
    for d in out_domains:
        if d["tier"] == "On-air critical" and d.get("degree", 0) > 0 and d.get("neighbors"):
            cross.append({"severity": "Medium", "kind": "on-air-coupling", "vlan": "",
                "title": f"On-air-critical domain '{d['domain']}' is coupled to {len(d['neighbors'])} other domain(s)",
                "detail": f"{d['domain']} shares fabric / subnets / dual-homed endpoints with: "
                          f"{', '.join(d['neighbors'][:8])}. A cutover in a coupled domain can disrupt the on-air path.",
                "remediation": "Coordinate the cutover order with these domains and make-before-break shared "
                               "links/legs; validate the on-air signal after each.", "standard": "SMPTE ST 2022-7"})

    # cap the (potentially many) per-VLAN querier risks, but ALWAYS keep the dependency risks (keystone /
    # on-air-coupling) -- they are few and would otherwise be truncated by the cap on a large flat fleet
    # (code-review V3.23.119). Output is unchanged whenever the total is under the cap.
    def _csort(r):
        return (_APP_SEV_RANK.get(r["severity"], 9), int(r["vlan"]) if str(r["vlan"]).isdigit() else 0)
    _dep_kinds = {"keystone-domain", "on-air-coupling"}
    _deps = [r for r in cross if r.get("kind") in _dep_kinds]
    _querier = sorted((r for r in cross if r.get("kind") not in _dep_kinds), key=_csort)[:55]
    cross = sorted(_deps + _querier, key=_csort)[:60]

    # ---- per-domain migration criticality score + recommended cutover order (NEW-V3.23.114) ----
    # Pure post-process over the domain records: blend tier / health / risk / coupling / flags / size into a
    # 0-100 score (higher = migrate LATER with more safeguards), then order the domains lowest-first (safe
    # pilot) -> Pilot/Early/Mid/Late/Last. Grounded in wave-planning practice (fail-fast on low-complexity
    # pilots; mission-critical last). A RECOMMENDATION (the war-room decides) -- like compute_migration_scenarios.
    W = _CRIT_WEIGHTS
    max_sw = max((d["switch_count"] for d in out_domains), default=1) or 1
    max_deg = max((d.get("degree", 0) for d in out_domains), default=0)
    for d in out_domains:
        hh = d.get("health") or {}
        score = float(W["tier"].get(d["tier"], 0))
        score += W["band"].get(hh.get("worst_band", ""), 0)
        # ...and where health could NOT be measured, charge the author's own 'Insufficient Data' weight.
        # It is defined in _CRIT_WEIGHTS between Fair (5) and Poor (11) -- an uncollected device was meant
        # to push a domain LATER in the order -- but it is looked up by worst_band alone, which now
        # (correctly) never reports a collection gap, so without this line the weight is dead code and an
        # unassessed domain sorts to the front as the "Pilot". Unknown is not safe; it is unknown.
        # (Re-derived from band_of rather than stored on the record, so the domain schema is unchanged;
        # the gap's structural disclosure is the "NO health evidence" risk row emitted above.)
        if band_of and any(band_of.get(h, "") in ("", "Insufficient Data")
                           for h in (d.get("switches") or [])):
            score += W["band"].get("Insufficient Data", 0)
        score += min(hh.get("n_critical", 0) * 3 + hh.get("n_poor", 0) * 1.5, W["health_cap"])
        score += min(d.get("n_high_risk", 0) * W["high_risk"] + len(d.get("risks") or []) * W["risk"], W["risk_cap"])
        score += (d.get("degree", 0) / max_deg * W["coupling"]) if max_deg else 0
        if d.get("spans_waves"):
            score += W["spans_waves"]
        if d.get("ptp_present") and not d.get("ptp_boundary_clocked"):
            score += W["ptp"]
        score += d["switch_count"] / max_sw * W["size"]
        d["criticality_score"] = int(max(0, min(100, round(score))))

    ordered = sorted(out_domains, key=lambda d: (d["criticality_score"], d["domain"]))
    n = len(ordered)

    _BAND_RANK = {"Pilot": 0, "Early": 1, "Mid": 2, "Late": 3, "Last": 4}

    def _band(d, pos):
        # base band tracks the score-ordered POSITION (lowest score = safest pilot, any tier)
        frac = pos / max(n - 1, 1)
        base = ("Pilot" if frac < 0.2 else "Early" if frac < 0.4 else "Mid"
                if frac < 0.65 else "Late" if frac < 0.85 else "Last")
        if d["tier"] == "On-air critical":                  # safeguard: on-air never pilots early
            if pos >= n - 1 or d["criticality_score"] >= W["last_threshold"]:
                return "Last"
            if _BAND_RANK[base] < _BAND_RANK["Late"]:
                return "Late"
        return base

    cutover_order = []
    for i, d in enumerate(ordered):
        band = _band(d, i)
        nbr = d.get("neighbors") or []
        rationale = (f"{d['tier']}; health {(d.get('health') or {}).get('worst_band', '') or 'n/a'}; "
                     f"{d.get('n_high_risk', 0)} high/crit risk(s); couples to {len(nbr)} domain(s)"
                     + (f" — coordinate with {', '.join(nbr[:3])}" if nbr else "")
                     + (". Start here to fail-fast and learn." if band == "Pilot"
                        else ". Migrate last: make-before-break + full validation." if band == "Last"
                        else "."))
        d["cutover"] = {"order": i + 1, "band": band, "rationale": rationale}
        cutover_order.append({"domain": d["domain"], "order": i + 1, "band": band,
                              "score": d["criticality_score"], "tier": d["tier"], "rationale": rationale})

    by_tier = Counter(d["tier"] for d in out_domains)
    summary = {
        "n_domains": len(out_domains), "by_tier": dict(by_tier),
        "n_on_air_critical": by_tier.get("On-air critical", 0),
        "n_spanning_waves": sum(1 for d in out_domains if d["spans_waves"]),
        "n_high_risk": sum(1 for d in out_domains if d["n_high_risk"]),
        "n_cross_domain_risks": len(cross),
        "ptp_boundary_clocked": any(d["ptp_boundary_clocked"] for d in out_domains),
        "n_edges": len(edges),
        "keystone_domain": keystones[0]["domain"] if keystones else "",
        "n_on_air_coupled": sum(1 for d in out_domains
                                if d["tier"] == "On-air critical" and d.get("degree", 0) > 0),
        "pilot_domain": cutover_order[0]["domain"] if cutover_order else "",
        "last_domain": cutover_order[-1]["domain"] if cutover_order else "",
    }
    return {"domains": out_domains, "summary": summary, "cross_domain_risks": cross,
            "edges": edges, "keystones": keystones, "cutover_order": cutover_order,
            "taxonomy_version": "app-domains/3"}


# =============================================================================
# Remediation generator (NEW-V3.23.116). The assess->ACT layer: turn the structured findings into
# per-device, platform-tagged, copy-pasteable Cisco config snippets a network engineer can REVIEW and
# apply. Generation FOR REVIEW ONLY -- the tool writes nothing and lacks full operational context; every
# item carries the evidence (why), a verify command, and a caution. Where a fix needs intent the tool
# cannot know (FHRP virtual IP, the 'correct' native VLAN), the template uses explicit <placeholder>
# markers rather than guessing. Pure read of the same structured sources the punch-list consumes.
# =============================================================================
_REMEDIATION_BANNER = ("GENERATED FOR REVIEW — validate against the device's running-config and your "
                       "change-control before applying. Snippets are starting points, not a turnkey script.")
_REMEDIATION_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}


def _is_nxos(platform: str) -> bool:
    p = (platform or "").lower()
    return "nx" in p or "nexus" in p


def compute_remediation_plan(devices: Optional[dict] = None,
                             l2: Optional[dict] = None,
                             stp_findings: Optional[dict] = None,
                             config_hygiene: Optional[dict] = None,
                             security: Optional[dict] = None,
                             multicast_intelligence: Optional[dict] = None,
                             move_groups: Optional[list] = None) -> dict:
    """NEW-V3.23.116: per-device, platform-tagged Cisco config snippets generated from the structured finding
    sources (STP root, trunk native-VLAN, link duplex/speed, config-hygiene undefined refs, CIS security,
    FHRP, multicast querier). REVIEW-ONLY -- no device writes; each item carries why / verify / caution and
    uses <placeholders> where the fix needs intent the tool cannot know. Pure read; deterministic; tolerant
    of empty / oddly-typed input. Returns {items, by_device, summary, banner}."""
    from collections import Counter, defaultdict
    devs = devices or {}
    l2 = l2 or {}
    wave_of: Dict[str, str] = {}
    for g in (move_groups or []):
        for h in (g.get("switches") or []):
            wave_of.setdefault(h, g.get("group") or "")

    def _plat(host):
        return (devs.get(host) or {}).get("platform", "ios") or "ios"

    items: List[dict] = []

    def add(device, category, severity, title, why, commands, verify, caution, source):
        items.append({"device": device, "platform": _plat(device), "category": category,
                      "severity": severity, "title": title, "why": (why or "")[:300],
                      "commands": [c for c in commands if c is not None], "verify": verify,
                      "caution": caution, "source": source, "wave": wave_of.get(device, "")})

    sf = stp_findings or {}
    for a in sf.get("accidental", []):                                    # STP accidental root (default priority)
        h, vlan = a.get("host"), a.get("vlan")
        add(h, "STP", "Low", f"Accidental root on VLAN {vlan}",
            "Rooted on the default bridge priority — elected on a MAC tiebreak, so the root can move on a cutover.",
            [f"spanning-tree vlan {vlan} priority 24576", "! (use 28672 for a secondary/backup root)"],
            f"show spanning-tree vlan {vlan}",
            "Set a DELIBERATE priority on the INTENDED root only; verify the topology before and after.",
            "stp-accidental")
    for m in sf.get("misaligned", []):                                    # STP root != gateway (hairpin)
        vlan, root, gws = m.get("vlan"), m.get("root"), list(m.get("gateways", []))
        gw = gws[0] if gws else "<gateway-switch>"
        add(gw, "STP", "Medium", f"STP root not on the gateway for VLAN {vlan}",
            f"The spanning-tree root for VLAN {vlan} is {root}, not the VLAN's gateway — traffic to the default "
            "gateway hairpins.",
            [f"spanning-tree vlan {vlan} root primary",
             f"! on {root}: raise its priority value (e.g. spanning-tree vlan {vlan} priority 28672) so it yields"],
            f"show spanning-tree vlan {vlan} root",
            "Align the root with the active gateway; do not move the root during traffic hours.", "stp-misaligned")

    for t in (l2.get("trunk_native") or []):                              # trunk native-VLAN mismatch (both ends)
        a_h, a_p, a_n = t.get("a_host"), t.get("a_port"), t.get("a_native")
        b_h, b_p, b_n = t.get("b_host"), t.get("b_port"), t.get("b_native")
        why = f"{a_h} {a_p} (native {a_n}) <-> {b_h} {b_p} (native {b_n}) — untagged L2 leak / VLAN-hopping exposure."
        for (h, p) in ((a_h, a_p), (b_h, b_p)):
            add(h, "Trunk", "Medium", f"Native-VLAN mismatch on {p}", why,
                [f"interface {p}", " switchport trunk native vlan <chosen-native-vlan>"],
                f"show interfaces {p} trunk",
                "Both ends MUST use the SAME native VLAN — pick one agreed value and set it on both.", "trunk-native")

    for lp in (l2.get("link_phy") or []):                                 # link duplex/speed mismatch (both ends)
        what = "duplex" if lp.get("duplex") else "speed"
        a_h, a_p, b_h, b_p = lp.get("a_host"), lp.get("a_port"), lp.get("b_host"), lp.get("b_port")
        why = f"{a_h} {a_p} <-> {b_h} {b_p} — {what} differs (late collisions / CRC errors; link up but degraded)."
        for (h, p) in ((a_h, a_p), (b_h, b_p)):
            add(h, "Link L1", "Medium", f"{what.capitalize()} mismatch on {p}", why,
                [f"interface {p}", " duplex auto" if lp.get("duplex") else " speed auto"],
                f"show interfaces {p} status",
                "Set BOTH ends to matching auto (or matching fixed) values — autoneg on one side + fixed on the "
                "other is the classic cause.", "link-phy")

    for host, hg in (config_hygiene or {}).items():                       # config hygiene: undefined references
        for u in (hg.get("undefined") or []):
            kind, name, ctx = u.get("kind", ""), u.get("name", ""), u.get("context", "")
            add(host, "Config hygiene", "High", f"Undefined {kind} '{name}'",
                f"Referenced ({ctx}) but never defined — it silently does nothing (e.g. an ACL/route-map that "
                "matches nothing).",
                [f"! Option A — DEFINE the missing {kind} '{name}' with the intended rules, e.g.:",
                 f"!   {kind} {name}", f"! Option B — REMOVE the dangling reference at: {ctx}",
                 "!   (negate the referencing line with its 'no' form)"],
                f"show running-config | include {name}",
                "Decide define-vs-remove from intent; a wrong 'no' can drop a security/routing control.",
                "hygiene-undefined")

    for host, s in (security or {}).items():                              # CIS security failures
        for f in (s.get("findings") or []):
            if f.get("status") != "fail":
                continue
            rem = (f.get("remediation") or "").strip()
            add(host, "Security", str(f.get("severity", "medium")).capitalize(),
                f.get("title", f.get("id", "CIS check")),
                f.get("detail", "") or f"CIS check '{f.get('id', '')}' failed.",
                (["! " + ln for ln in rem.splitlines()] if rem
                 else ["! See the Config Compliance sheet for the hardening step."]),
                f"show running-config | include {f.get('id', '')}",
                "CIS hardening — confirm the control suits this device's role before applying.", "cis-security")

    for fr in (l2.get("fhrp") or []):                                     # FHRP fake redundancy (templated)
        # Cross-switch domain composition never authorizes generated configuration: its worst status is
        # deliberately propagated to every member and cannot identify the local fault owner.  In
        # particular, zero participation is not permission to add HSRP everywhere.  Legacy untyped rows
        # retain the existing compatibility remediation path.
        if fr.get("authoritative") is True or fr.get("status") in {"review", "not_verified"}:
            continue
        vid = fr.get("vid")
        members = [m.get("host") for m in (fr.get("members") or []) if m.get("host")]
        why = f"VLAN {vid}: " + "; ".join(fr.get("issues", []))
        for h in members:
            if _is_nxos(_plat(h)):
                cmds = ["feature hsrp", f"interface Vlan{vid}", " hsrp <group>",
                        "  ip <virtual-ip>", "  priority <100-or-higher-on-primary>", "  preempt"]
            else:
                cmds = [f"interface Vlan{vid}", " standby <group> ip <virtual-ip>",
                        " standby <group> priority <100-or-higher-on-primary>", " standby <group> preempt"]
            add(h, "FHRP", "High", f"Fake FHRP redundancy on VLAN {vid}", why, cmds,
                "show hsrp brief" if _is_nxos(_plat(h)) else f"show standby vlan {vid}",
                "Standardize ONE FHRP protocol / group / virtual-IP across ALL the VLAN's gateways; <virtual-ip> "
                "is the agreed gateway address.", "fhrp")

    for vlan in ((multicast_intelligence or {}).get("querier") or {}).get("gap_vlans", []):  # multicast querier gap
        add("(media VLAN)", "Multicast", "High", f"No IGMP querier on multicast VLAN {vlan}",
            f"VLAN {vlan} carries multicast but no IGMP querier was seen — flooding / blackhole risk.",
            ["! IOS: ip igmp snooping querier   (exactly one switch per VLAN; lowest IP wins)",
             f"! NX-OS: vlan configuration {vlan}", "!          ip igmp snooping querier <ip-in-subnet>"],
            f"show ip igmp snooping querier vlan {vlan}",
            "Exactly ONE querier per VLAN — a second creates a split-brain.", "querier-gap")

    items.sort(key=lambda it: (_REMEDIATION_RANK.get(it["severity"], 9), str(it["device"]), it["category"],
                               it["title"]))
    by_device: Dict[str, list] = defaultdict(list)
    for it in items:
        by_device[it["device"]].append(it)
    summary = {"n_items": len(items), "n_devices": len(by_device),
               "by_category": dict(Counter(it["category"] for it in items)),
               "n_high": sum(1 for it in items if it["severity"] in ("Critical", "High"))}
    return {"items": items, "by_device": dict(by_device), "summary": summary, "banner": _REMEDIATION_BANNER}


# =============================================================================
# Cutover VALIDATION / test-plan generator (NEW-V3.23.143). Closes the assess->act->VERIFY loop: from the
# CURRENT-state topology, generate the per-wave checks an engineer runs DURING & AFTER a cutover to PROVE
# the network still works -- each with the exact show/ping command AND the expected "good" result derived
# from the pre-cutover state, so post-cutover output can be confirmed to MATCH. Pure synthesis over already-
# collected data (gateways/FHRP from the model, routing adjacencies, STP roots, port-channels); no new
# collection, no device writes. Deterministic; tolerant of empty/oddly-typed input. Mirrors the remediation
# generator's structure. Returns {items, by_wave, summary, banner}.
# =============================================================================
_VALIDATION_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}
_VALIDATION_BANNER = ("Run these AFTER each wave's cutover. The 'Observed baseline / acceptance' column "
                      "preserves what was actually observed and never invents a healthy count. Rows beginning "
                      "'PRE-CUTOVER DEGRADED — BLOCKER:' or 'PRE-CUTOVER REVIEW — BLOCKER:' are blockers: "
                      "matching a faulted observation is NOT ACCEPTANCE, and identity/timing ambiguity requires "
                      "live verification. 'BGP CONFIGURED PEER NOT VERIFIED — BLOCKER:', 'ROUTING BASELINE "
                      "NOT VERIFIED — BLOCKER:', 'ETHERCHANNEL BASELINE NOT VERIFIED — BLOCKER:', and "
                      "'VTP SAFETY BASELINE NOT VERIFIED — BLOCKER:' mean "
                      "the current-run receipt cannot authorize the "
                      "corresponding observed baseline and require re-collection. Evidence-backed rows disclose "
                      "projection custody; BGP configured-peer rows cover only direct static literal peers in the "
                      "default/global IPv4-unicast scope, OSPF/EIGRP remain observed-peer scope, and EtherChannel "
                      "is observed local group/member scope rather "
                      "than configured or partner intent. VTP safety is a local mode/domain/revision exposure "
                      "review, not database authority or propagation proof. Resolve or explicitly disposition "
                      "every blocker and "
                      "investigate every baseline deviation before acceptance.")


def _validation_wave_key(w: str):
    """Sort 'Group 2' before 'Group 10' (numeric), numbered waves before any non-numbered label."""
    m = re.search(r"(\d+)", w or "")
    return (0, int(m.group(1))) if m else (1, w or "")


def _bgp_configured_peer_acceptance(row: Any) -> str:
    """Return the one acceptance sentence shared by Validation and NRFU.

    The configured-peer owner supplies normalized facts and a source-bound prose
    explanation.  This projector owns the exact cutover blocker prefixes and the
    deliberately narrow positive-acceptance boundary.
    """
    record = row if isinstance(row, dict) else {}
    status = _strict_protocol_text(record.get("status"))
    supplied = _strict_protocol_text(record.get("acceptance"))
    peer = _strict_protocol_text(record.get("peer")) or "<configured-peer>"
    state = _strict_protocol_text(record.get("runtime_state_raw")) or "not observed"
    scope = _strict_protocol_text(record.get("scope")) or "default/global IPv4-unicast"
    fallback = f"Configured peer {peer}; runtime state {state}; scope {scope}."
    detail = supplied or fallback
    markers = {
        "degraded": "PRE-CUTOVER DEGRADED — BLOCKER:",
        "review": "PRE-CUTOVER REVIEW — BLOCKER:",
        "not_verified": "BGP CONFIGURED PEER NOT VERIFIED — BLOCKER:",
    }
    marker = markers.get(status)
    if marker:
        if detail.startswith(marker):
            return detail
        return f"{marker} {detail}"
    if status == "assessed":
        boundary = (
            "Acceptance is limited to the bounded default/global IPv4 literal-peer scope; "
            "it does not prove VRFs, other address families, inherited/dynamic peers, policy, "
            "RIB/FIB correctness, convergence, or capture simultaneity."
        )
        return detail if boundary in detail else f"{detail} {boundary}"
    if status == "administratively_disabled":
        return (
            f"{detail} Administratively disabled is neutral in the bounded default/global IPv4 "
            "literal-peer scope and is not evidence of BGP health."
        )
    return (
        "BGP CONFIGURED PEER NOT VERIFIED — BLOCKER: The configured-peer row has an unsupported "
        "status; re-run the bounded default/global IPv4 assessment before acceptance."
    )


def _fhrp_configured_group_acceptance(row: Any) -> str:
    """Return the shared Validation/NRFU acceptance for one configured FHRP group."""
    record = row if isinstance(row, dict) else {}
    status = _strict_protocol_text(record.get("status"))
    supplied = _strict_protocol_text(record.get("acceptance"))
    protocol = _strict_protocol_text(record.get("protocol")) or "FHRP"
    interface = _strict_protocol_text(record.get("interface")) or "<interface>"
    group = _strict_protocol_text(record.get("group")) or "<group>"
    detail = supplied or f"{protocol} {interface} group {group}."
    markers = {
        "degraded": "PRE-CUTOVER DEGRADED — BLOCKER:",
        "review": "PRE-CUTOVER REVIEW — BLOCKER:",
        "not_verified": "FHRP CONFIGURED GROUP NOT VERIFIED — BLOCKER:",
    }
    marker = markers.get(status)
    if marker:
        return detail if detail.startswith(marker) else f"{marker} {detail}"
    if status == "assessed":
        boundary = (
            "Acceptance is limited to the configured local group/VIP/runtime-state projection; "
            "it does not prove a peer, intended member count, election health, failover, tracking, "
            "authentication, convergence, or capture simultaneity."
        )
        return supplied or f"{detail} {boundary}"
    if status == "administratively_disabled":
        if supplied:
            return supplied
        return (
            f"{detail} Administratively disabled is neutral in the bounded configured local-group "
            "scope and is not evidence of FHRP health."
        )
    return (
        "FHRP CONFIGURED GROUP NOT VERIFIED — BLOCKER: The configured-group row has an "
        "unsupported status; re-run the bounded local group/VIP/state assessment before acceptance."
    )


def _fhrp_configured_group_command(protocol: str, nxos: bool) -> str:
    """Return the read-only runtime command for a normalized FHRP subtype."""
    kind = _strict_protocol_text(protocol).upper()
    if kind == "VRRP":
        return "show vrrp brief"
    if kind == "GLBP":
        return "show glbp brief"
    return "show hsrp brief" if nxos else "show standby brief"


def compute_validation_plan(all_interfaces: Dict[str, Dict[str, InterfaceData]],
                            move_groups: Optional[list] = None,
                            routing_neighbors: Optional[dict] = None,
                            stp_roots: Optional[dict] = None,
                            devices: Optional[dict] = None,
                            protocol_health: Optional[list] = None,
                            protocol_assessability: Optional[dict] = None,
                            etherchannel_baseline: Optional[dict] = None,
                            etherchannel_projection: Any = _ETHERCHANNEL_BASELINE_UNSET,
                            bgp_configured_peer_baseline: Optional[dict] = None,
                            fhrp_configured_group_baseline: Optional[dict] = None,
                            fhrp_redundancy_domain_baseline: Optional[dict] = None,
                            vtp_safety_baseline: Optional[dict] = None,
                            vtp_safety_subject_scope: Any = None,
                            ipv6_routing_adjacency_baseline: Optional[dict] = None,
                            ipv6_routing_subject_scope: Any = None) -> dict:
    """NEW-V3.23.143: per-wave post-cutover validation checklist generated from the current-state topology.
    Each item names the device + the command to run + the observed pre-cutover baseline to compare + why it
    matters + the severity if it fails. A degraded observation remains explicitly degraded rather than being
    rewritten as an ideal good state. Read-only synthesis; no new collection. Returns
    {items, by_wave, summary, banner}."""
    from collections import Counter, defaultdict
    devs = devices or {}
    stp = stp_roots or {}
    groups = list(move_groups or [])

    # host -> wave label ("Group N", enumerated exactly like compute_migration_readiness). A host not in any
    # multi-switch group still gets checks under "(unscheduled)" so nothing is silently skipped.
    wave_of: Dict[str, str] = {}
    for gi, g in enumerate(groups, 1):
        for h in (g.get("switches") or []):
            wave_of.setdefault(h, f"Group {gi}")

    def _plat(host):
        return (devs.get(host) or {}).get("platform", "ios") or "ios"

    model = build_network_model(all_interfaces)
    items: List[dict] = []

    def add(device, category, severity, check, command, expect, why, *,
            evidence_state="", projection_custody="", source_key="",
            bgp_metadata: Optional[dict] = None,
            fhrp_metadata: Optional[dict] = None):
        item = {"device": device, "platform": _plat(device),
                "wave": wave_of.get(device, "(unscheduled)"),
                "category": category, "severity": severity, "check": check,
                "command": command, "expect": expect, "why": (why or "")[:300]}
        if evidence_state:
            item.update({
                "evidence_state": evidence_state,
                "projection_custody": projection_custody,
                "source_key": source_key,
            })
        if bgp_metadata is not None:
            item.update({
                "peer": _strict_protocol_text(bgp_metadata.get("peer")),
                "peer_key": _strict_protocol_text(bgp_metadata.get("peer_key")),
                "local_as": _strict_protocol_text(bgp_metadata.get("local_as")),
                "configured_remote_as": _strict_protocol_text(
                    bgp_metadata.get("configured_remote_as")),
                "activation": _strict_protocol_text(bgp_metadata.get("activation")),
                "runtime_observed": bgp_metadata.get("runtime_observed") is True,
                "runtime_remote_as": _strict_protocol_text(bgp_metadata.get("runtime_remote_as")),
                "runtime_state_raw": _strict_protocol_text(bgp_metadata.get("runtime_state_raw")),
                "runtime_state": _strict_protocol_text(bgp_metadata.get("runtime_state")),
                "scope": _strict_protocol_text(bgp_metadata.get("scope")),
            })
        if fhrp_metadata is not None:
            item.update({
                "protocol": _strict_protocol_text(fhrp_metadata.get("protocol")),
                "interface": _strict_protocol_text(fhrp_metadata.get("interface")),
                "group": _strict_protocol_text(fhrp_metadata.get("group")),
                "group_key": _strict_protocol_text(fhrp_metadata.get("group_key")),
                "configured": fhrp_metadata.get("configured") is True,
                "configured_vip": _strict_protocol_text(fhrp_metadata.get("configured_vip")),
                "activation": _strict_protocol_text(fhrp_metadata.get("activation")),
                "runtime_observed": fhrp_metadata.get("runtime_observed") is True,
                "runtime_vip": _strict_protocol_text(fhrp_metadata.get("runtime_vip")),
                "runtime_state_raw": _strict_protocol_text(
                    fhrp_metadata.get("runtime_state_raw")),
                "runtime_state": _strict_protocol_text(fhrp_metadata.get("runtime_state")),
                "scope": _strict_protocol_text(fhrp_metadata.get("scope")),
            })
        items.append(item)

    # ---- Gateway SVI + first-hop redundancy. Read the SVI IP / FHRP string straight from the interfaces
    #      (the model only carries the FHRP bool). ----
    svi: Dict[tuple, dict] = {}   # (host, vid) -> {"ip", "fhrp"}
    for host, ifaces in all_interfaces.items():
        for port, d in ifaces.items():
            m = re.match(r"^Vlan(\d+)$", port, re.IGNORECASE)
            if m and ((getattr(d, "svi_ip", "") or "").strip() or (getattr(d, "hsrp_behavior", "") or "").strip()):
                svi[(host, int(m.group(1)))] = {"ip": (d.svi_ip or "").strip(),
                                                "fhrp": (d.hsrp_behavior or "").strip()}
    for (host, vid), info in sorted(svi.items()):
        ip = info["ip"].split()[0] if info["ip"] else ""
        add(host, "Gateway", "High",
            f"Default gateway for VLAN {vid} is up",
            f"show ip interface brief | include Vlan{vid}",
            f"Vlan{vid} {ip or '<svi-ip>'} up/up (line protocol up)",
            f"VLAN {vid} endpoints lose their default gateway if this SVI is down after cutover.")

    # ---- FHRP observed election baseline.  Without a configured contract, preserve every observed
    # member (including a single local backup) as the compatibility baseline.  With the configured
    # contract, retain only uncovered observed blockers: an exact source-bound configured blocker owns
    # its local duplicate, while mixed protocol/group/VIP and broader domain findings stay additive.
    fhrp_contract_supplied = fhrp_configured_group_baseline is not None
    fhrp_view: dict = {}
    fhrp_valid = False
    fhrp_contract: dict = {}
    fhrp_rows: List[dict] = []
    if fhrp_contract_supplied:
        fhrp_view = validate_fhrp_configured_group_baseline(
            fhrp_configured_group_baseline, require_current_run=True)
        fhrp_valid = (
            fhrp_view.get("valid") is True and fhrp_view.get("source_bound") is True
        )
        fhrp_contract = fhrp_view.get("baseline") or {}
        fhrp_rows = list(fhrp_view.get("rows") or []) if fhrp_valid else []
    fhrp_elections = summarize_fhrp_elections(all_interfaces)
    fhrp_uncovered_by_election: Dict[int, List[dict]] = {}
    if fhrp_contract_supplied:
        for election, member in _uncovered_fhrp_election_blockers(
                fhrp_elections, fhrp_rows):
            fhrp_uncovered_by_election.setdefault(id(election), []).append(member)
    for election in fhrp_elections:
        metadata_by_protocol = {
            item["protocol"]: item for item in election["validation"]
        }
        projected_members = (
            fhrp_uncovered_by_election.get(id(election), [])
            if fhrp_contract_supplied else election["members"]
        )
        for member in projected_members:
            protocol = member["protocol"]
            metadata = metadata_by_protocol[protocol]
            command = metadata["command"]
            # Preserve the already-supported NX-OS dialect while keeping the subtype owner canonical:
            # both commands retrieve HSRP brief state; VRRP/GLBP never inherit an HSRP spelling.
            if protocol == "HSRP" and _is_nxos(_plat(member["host"])):
                command = "show hsrp brief"
            leader_text = "/".join(metadata["leader_roles"])
            backup_text = "/".join(metadata["backup_roles"])
            identity = f"{member['interface']} {protocol} group {member['group'] or '?'}"
            if member["vip"]:
                identity += f" VIP {member['vip']}"
            observed = f"Observed local baseline: {identity} is {member['role']}"
            vocabulary = (f"{protocol} role vocabulary: leader {leader_text}; accepted observed "
                          f"non-leader {backup_text}")
            member_status = member.get("status", "healthy")
            issue_text = "; ".join(member.get("issues") or [])
            if member_status == "degraded":
                check = f"First-hop redundancy degraded baseline for VLAN {election['vlan']}"
                expect = (f"PRE-CUTOVER DEGRADED — BLOCKER: {observed}. Observed election issue(s): "
                          f"{issue_text}. Matching this degraded observation after cutover is NOT ACCEPTANCE; "
                          "resolve or explicitly disposition the blocker. Do NOT substitute an ideal healthy "
                          f"role/count. {vocabulary}.")
                why = (f"VLAN {election['vlan']} already has observed FHRP election degradation. It must be "
                        "resolved or explicitly accepted before cutover, and must not worsen afterward.")
            elif member_status == "review":
                check = f"First-hop redundancy evidence review for VLAN {election['vlan']}"
                expect = (f"PRE-CUTOVER REVIEW — BLOCKER: {observed}. Observed evidence issue(s): {issue_text}. "
                          "The one-record-per-SVI, sequential-capture projection cannot prove a broken pair or "
                          "a healthy independent election. Verify all intended members simultaneously before "
                          f"acceptance. {vocabulary}.")
                why = (f"VLAN {election['vlan']} carries identity, coverage, or capture-timing ambiguity. Live "
                       "simultaneous verification must establish the intended election before cutover.")
            else:
                check = f"First-hop redundancy observed baseline for VLAN {election['vlan']}"
                expect = (f"{observed}. Preserve or explain any role/VIP/group change; no expected peer "
                          f"count was inferred. {vocabulary}.")
                why = (f"A change from the observed {protocol} role/group/VIP on VLAN {election['vlan']} "
                       "can indicate election churn, lost failover, or split-brain. A single observed "
                       "backup-only member is not by itself classified as degraded.")
            # Publish the typed evidence state and exact source leaf alongside the human-readable
            # acceptance marker.  The marker remains a compatibility fallback for older snapshots;
            # current decision surfaces must not have to reverse-parse prose to find an FHRP blocker.
            evidence_state = {
                "healthy": "assessed",
                "degraded": "degraded",
                "review": "review",
            }.get(member_status, "review")
            host_key = _strict_protocol_text(member.get("host"))[:120]
            interface_key = _strict_protocol_text(member.get("interface"))[:80]
            source_key = f"interfaces.{host_key}.{interface_key}.hsrp_behavior"
            add(
                member["host"], "FHRP", "High", check, command, expect, why,
                evidence_state=evidence_state,
                projection_custody="embedded_unverified",
                source_key=source_key[:300],
            )

    if fhrp_contract_supplied:
        blocker_states = {"degraded", "review", "not_verified"}
        for row in fhrp_rows:
            if not isinstance(row, dict):
                continue
            host = _strict_protocol_text(row.get("switch"))
            protocol = _strict_protocol_text(row.get("protocol")).upper()
            interface = _strict_protocol_text(row.get("interface")) or "<interface>"
            group = _strict_protocol_text(row.get("group")) or "<group>"
            status = _strict_protocol_text(row.get("status"))
            if not host or protocol not in {"HSRP", "VRRP", "GLBP"} or status not in {
                    "assessed", "degraded", "review", "not_verified",
                    "administratively_disabled"}:
                continue
            check = {
                "assessed": f"{protocol} configured group {group} bounded baseline",
                "degraded": f"{protocol} configured group {group} degraded baseline",
                "review": f"{protocol} configured group {group} evidence review",
                "not_verified": f"{protocol} configured group {group} not verified",
                "administratively_disabled": (
                    f"{protocol} configured group {group} administratively disabled"
                ),
            }[status]
            add(
                host,
                "FHRP",
                "Info" if status == "administratively_disabled" else "High",
                check,
                _strict_protocol_text(row.get("command")) or _fhrp_configured_group_command(
                    protocol, _is_nxos(_plat(host))),
                _fhrp_configured_group_acceptance(row),
                (f"Configured-group reconciliation is bounded to {protocol} {interface} group "
                 f"{group} in the default IPv4 direct-literal local scope; it does not infer a "
                 "peer, intended member count, or election health."),
                evidence_state=status,
                projection_custody=_strict_protocol_text(row.get("projection_custody")),
                source_key=_strict_protocol_text(row.get("source_key")),
                fhrp_metadata=row,
            )

        fhrp_verdict = _strict_protocol_text(fhrp_contract.get("verdict")).upper()
        has_blocker_row = any(
            isinstance(row, dict) and row.get("status") in blocker_states
            for row in fhrp_rows
        )
        needs_fallback = (
            not fhrp_valid
            or (fhrp_verdict in {"BLOCKED", "INDETERMINATE"} and not has_blocker_row)
        )
        fallback_subjects: set[tuple[str, str]] = set()
        if needs_fallback and fhrp_valid:
            fallback_subjects = {
                (_strict_protocol_text(row.get("switch")),
                 _strict_protocol_text(row.get("protocol")).upper())
                for row in (fhrp_contract.get("coverage") or [])
                if isinstance(row, dict)
                and _strict_protocol_text(row.get("status")).lower() in {
                    "degraded", "review", "not_verified"}
                and _strict_protocol_text(row.get("switch"))
                and _strict_protocol_text(row.get("protocol")).upper() in {
                    "HSRP", "VRRP", "GLBP"}
            }
        elif needs_fallback:
            fallback_subjects = {
                (_strict_protocol_text(host), "FHRP")
                for host in set(devs) | set(all_interfaces)
                if _strict_protocol_text(host)
            }
            if not fallback_subjects and isinstance(fhrp_configured_group_baseline, dict):
                fallback_subjects = {
                    (_strict_protocol_text(row.get("switch")), "FHRP")
                    for row in (fhrp_configured_group_baseline.get("rows") or [])
                    if isinstance(row, dict) and _strict_protocol_text(row.get("switch"))
                }
        if fhrp_valid:
            reason = (
                f"configured-group owner verdict {fhrp_verdict or 'INDETERMINATE'} has no "
                "attributable group row; host/subtype coverage is incomplete"
            )
        else:
            reason = _strict_protocol_text(fhrp_view.get("reason")) or (
                "the configured-group artifact is not a validated current-run receipt"
            )
        for host, protocol in sorted(
                fallback_subjects, key=lambda value: (value[0].casefold(), value[0], value[1])):
            placeholder = {
                "switch": host, "protocol": protocol, "interface": "", "group": "",
                "group_key": "", "configured": False, "configured_vip": "",
                "activation": "not_verified", "runtime_observed": False,
                "runtime_vip": "", "runtime_state_raw": "",
                "runtime_state": "NOT_VERIFIED",
                "scope": "default IPv4 direct-literal local configured group",
                "status": "not_verified",
            }
            command_protocol = protocol if protocol in {"HSRP", "VRRP", "GLBP"} else "HSRP"
            add(
                host, "FHRP", "High", "FHRP configured-group baseline not verified",
                _fhrp_configured_group_command(command_protocol, _is_nxos(_plat(host))),
                "FHRP CONFIGURED GROUP NOT VERIFIED — BLOCKER: No validated, source-bound "
                "current-run configured-group baseline authorizes a positive FHRP acceptance "
                "target. Re-collect running-config and the matching HSRP/VRRP/GLBP summary "
                "before cutover.",
                f"The FHRP configured-group analysis failed closed: {reason}.",
                evidence_state="not_verified", projection_custody="embedded_unverified",
                source_key="fhrp_configured_group_baseline", fhrp_metadata=placeholder,
            )

    # The cross-switch redundancy-domain owner is strictly additive to local configured-group and
    # compatibility-election rows.  Its flat owner row is retained verbatim, with the validation-plan
    # envelope adding only device/wave/category/severity and the typed gate aliases.
    if fhrp_redundancy_domain_baseline is not None:
        domain_view = _fhrp_redundancy_domain_consumer_view(
            fhrp_redundancy_domain_baseline,
            all_interfaces,
            fhrp_configured_group_baseline,
        )
        for owner_row in domain_view["rows"]:
            if not isinstance(owner_row, dict):
                continue
            host = owner_row.get("switch") if isinstance(owner_row.get("switch"), str) else ""
            status = owner_row.get("status") if isinstance(owner_row.get("status"), str) else ""
            if not host or status not in {"assessed", "degraded", "review", "not_verified"}:
                continue
            item = dict(owner_row)
            item.update({
                "device": host,
                "platform": _plat(host),
                "wave": wave_of.get(host, "(unscheduled)"),
                "category": "FHRP",
                "severity": "High",
                "expect": owner_row["acceptance"],
                "evidence_state": status,
            })
            items.append(item)

    # VTP safety remains additive to protocol health/intelligence.  Preserve every validated owner
    # leaf used for execution (command/acceptance/source/custody/status); the envelope supplies only
    # wave, category, severity, and the generic current-baseline aliases.
    if vtp_safety_baseline is not None:
        vtp_view = _vtp_safety_consumer_view(
            vtp_safety_baseline, protocol_health, protocol_assessability,
            vtp_safety_subject_scope)
        for owner_row in vtp_view["rows"]:
            if not isinstance(owner_row, dict):
                continue
            host = _strict_protocol_text(owner_row.get("switch"))
            status = _strict_protocol_text(owner_row.get("status"))
            acceptance = _strict_protocol_text(owner_row.get("acceptance"))
            if (not host or status not in {"assessed", "review", "not_verified"}
                    or not acceptance):
                continue
            high_revision = "high_revision_server" in _vtp_safety_finding_codes(owner_row)
            owner_why = _strict_protocol_text(owner_row.get("why"))
            check = {
                "assessed": "VTP bounded local safety baseline",
                "review": (
                    "VTP high-revision cutover exposure review"
                    if high_revision else "VTP cutover safety review"
                ),
                "not_verified": "VTP safety baseline not verified",
            }[status]
            item = dict(owner_row)
            item.update({
                "device": host,
                "platform": _plat(host),
                "wave": wave_of.get(host, "(unscheduled)"),
                "category": "VTP",
                "severity": "Medium" if status == "assessed" else "High",
                "check": check,
                "expect": acceptance,
                "why": (
                    "Local VTP mode, domain, and revision evidence is a bounded pre-cutover safety "
                    "observation; a high-revision server is one review heuristic. The observation "
                    "does not prove database authority, synchronization, pruning, authentication, "
                    "propagation, or overwrite safety."
                    + (f" Owner evidence: {owner_why}" if owner_why else "")
                ),
                "evidence_state": status,
            })
            items.append(item)

    # OSPFv3 and IPv6-unicast BGP are a separate, source-bound adjacency owner.
    # Keep the validation contract generic so every existing current-baseline
    # consumer receives the typed blocker without learning a second metadata schema.
    if ipv6_routing_adjacency_baseline is not None:
        ipv6_view = _ipv6_routing_consumer_view(
            ipv6_routing_adjacency_baseline, ipv6_routing_subject_scope)
        for owner_row in ipv6_view["rows"]:
            if not isinstance(owner_row, dict):
                continue
            host = _strict_protocol_text(owner_row.get("switch"))
            protocol = _strict_protocol_text(owner_row.get("protocol")) or "IPv6 Routing"
            peer = _strict_protocol_text(owner_row.get("peer"))
            state_raw = _strict_protocol_text(owner_row.get("state_raw"))
            state = state_raw or _strict_protocol_text(owner_row.get("state"))
            status = _strict_protocol_text(owner_row.get("status"))
            acceptance = _strict_protocol_text(owner_row.get("acceptance"))
            if (not host or status not in {
                    "assessed", "degraded", "review", "not_verified"}
                    or not acceptance):
                continue
            identity = f"{protocol} {peer or 'subject'}"
            if state:
                identity += f" state {state}"
            check = {
                "assessed": f"{identity} observed baseline",
                "degraded": f"{identity} degraded baseline",
                "review": f"{identity} evidence review",
                "not_verified": f"{identity} baseline not verified",
            }[status]
            add(
                host,
                "IPv6 Routing",
                "High" if status == "degraded" else "Medium",
                check,
                _strict_protocol_text(owner_row.get("command")),
                acceptance,
                ("Observed OSPFv3/IPv6-unicast BGP adjacency evidence is bounded to the "
                 "default routing instance and does not infer an expected-peer set, route "
                 "propagation, policy correctness, convergence, simultaneous sampling, or freshness."),
                evidence_state=status,
                projection_custody=_strict_protocol_text(
                    owner_row.get("projection_custody")),
                source_key=_strict_protocol_text(owner_row.get("source_key")),
            )

    # ---- Endpoint -> gateway reachability: one representative ping per VLAN that has BOTH a gateway and a
    #      client edge switch (an access switch carrying endpoints that is not itself the gateway). ----
    for vid in sorted(model["vlans"]):
        gw_hosts = sorted({g["host"] for g in model["gw"].get(vid, [])})
        if not gw_hosts:
            continue
        edges = sorted((model["access_presence"].get(vid, set())
                        | {h for (h, v) in model["endpoints"] if v == vid}) - set(gw_hosts))
        if not edges:
            continue
        gw_ip = ""
        for gh in gw_hosts:
            ip = (svi.get((gh, vid), {}).get("ip") or "").split()
            if ip:
                gw_ip = ip[0]
                break
        add(edges[0], "Reachability", "High",
            f"VLAN {vid} endpoints can reach their gateway",
            f"ping {gw_ip or '<vlan-%d-gateway-ip>' % vid}",
            "Success rate is 100 percent",
            f"Proves a VLAN {vid} client edge ({edges[0]}) still reaches its default gateway after cutover.")

    # ---- Receipt-gated observed routing baseline.  OSPF/EIGRP retain their observed-peer owner.  When the
    #      configured BGP denominator is supplied, it replaces every observed-only BGP row so a missing
    #      configured peer cannot disappear from the validation plan.
    bgp_contract_supplied = bgp_configured_peer_baseline is not None
    bgp_contract_view: dict = {}
    if bgp_contract_supplied:
        bgp_contract_view = validate_bgp_configured_peer_baseline(
            bgp_configured_peer_baseline, require_current_run=True)
    routing_baseline = summarize_routing_baseline(routing_neighbors, protocol_assessability)
    for row in routing_baseline["rows"]:
        if bgp_contract_supplied and row.get("protocol") == "BGP":
            continue
        status = row["status"]
        if status == "degraded":
            check = f"{row['protocol']} degraded adjacency baseline"
        elif status == "review":
            check = f"{row['protocol']} adjacency evidence review"
        elif status == "not_verified":
            check = f"{row['protocol']} adjacency baseline not verified"
        else:
            check = f"{row['protocol']} observed adjacency baseline"
        add(
            row["switch"], "Routing", "High", check, row["command"], row["acceptance"], row["note"],
            evidence_state=status,
            projection_custody=routing_baseline["projection_custody"],
            source_key=row["source_key"],
        )

    if bgp_contract_supplied:
        contract_valid = (
            bgp_contract_view.get("valid") is True
            and bgp_contract_view.get("source_bound") is True
        )
        contract = bgp_contract_view.get("baseline") or {}
        contract_rows = list(bgp_contract_view.get("rows") or []) if contract_valid else []
        blocker_states = {"degraded", "review", "not_verified"}

        for row in contract_rows:
            if not isinstance(row, dict):
                continue
            host = _strict_protocol_text(row.get("switch"))
            peer = _strict_protocol_text(row.get("peer")) or "<configured-peer>"
            status = _strict_protocol_text(row.get("status"))
            if not host or status not in {
                    "assessed", "degraded", "review", "not_verified",
                    "administratively_disabled"}:
                continue
            check = {
                "assessed": f"BGP configured peer {peer} bounded IPv4 baseline",
                "degraded": f"BGP configured peer {peer} degraded baseline",
                "review": f"BGP configured peer {peer} evidence review",
                "not_verified": f"BGP configured peer {peer} not verified",
                "administratively_disabled": f"BGP configured peer {peer} administratively disabled",
            }[status]
            command = _strict_protocol_text(row.get("command")) or (
                "show bgp ipv4 unicast summary" if _is_nxos(_plat(host))
                else "show ip bgp summary"
            )
            add(
                host,
                "Routing",
                "Info" if status == "administratively_disabled" else "High",
                check,
                command,
                _bgp_configured_peer_acceptance(row),
                ("Configured-peer reconciliation is bounded to a literal IPv4 peer in the default/global "
                 "IPv4-unicast scope; every active configured peer must be accounted for at runtime."),
                evidence_state=status,
                projection_custody=_strict_protocol_text(row.get("projection_custody")),
                source_key=_strict_protocol_text(row.get("source_key")),
                bgp_metadata=row,
            )

        verdict = _strict_protocol_text(contract.get("verdict")).upper()
        has_blocker_row = any(
            isinstance(row, dict) and row.get("status") in blocker_states
            for row in contract_rows
        )
        # A failed/tampered phase, or an INDETERMINATE/BLOCKED receipt that cannot attribute its
        # verdict to a denominator row, must still keep the current baseline gate non-CLEAR.  Scope the
        # abstention to known devices without copying any unvalidated peer/config leaf.
        needs_fallback = (
            not contract_valid
            or (verdict in {"BLOCKED", "INDETERMINATE"} and not has_blocker_row)
        )
        if needs_fallback:
            if contract_valid:
                fallback_hosts = {
                    _strict_protocol_text(row.get("switch"))
                    for row in (contract.get("coverage") or [])
                    if isinstance(row, dict) and row.get("subject") is True
                    and _strict_protocol_text(row.get("status")).lower() in {
                        "degraded", "review", "not_verified"}
                    and _strict_protocol_text(row.get("switch"))
                }
            else:
                fallback_hosts = {
                    _strict_protocol_text(host) for host in set(devs) | set(all_interfaces)
                    if _strict_protocol_text(host)
                }
            if not fallback_hosts and isinstance(bgp_configured_peer_baseline, dict):
                # Only an invalid/tampered contract needs this last-resort scoping.  A valid global
                # INDETERMINATE with no subject coverage is neutral and must not become fleet-wide.
                if not contract_valid:
                    fallback_hosts = {
                        _strict_protocol_text(row.get("switch"))
                        for row in (bgp_configured_peer_baseline.get("rows") or [])
                        if isinstance(row, dict) and _strict_protocol_text(row.get("switch"))
                    }
            for host in sorted(fallback_hosts, key=lambda value: (value.casefold(), value)):
                placeholder = {
                    "switch": host,
                    "peer": "",
                    "peer_key": "",
                    "local_as": "",
                    "configured_remote_as": "",
                    "activation": "not_verified",
                    "runtime_observed": False,
                    "runtime_remote_as": "",
                    "runtime_state_raw": "",
                    "runtime_state": "NOT_VERIFIED",
                    "scope": "default/global IPv4-unicast literal-peer",
                    "status": "not_verified",
                }
                reason = _strict_protocol_text(bgp_contract_view.get("reason")) or (
                    f"configured-peer owner verdict {verdict or 'INDETERMINATE'} has no attributable blocker row"
                )
                add(
                    host, "Routing", "High", "BGP configured-peer baseline not verified",
                    "show bgp ipv4 unicast summary" if _is_nxos(_plat(host)) else "show ip bgp summary",
                    "BGP CONFIGURED PEER NOT VERIFIED — BLOCKER: No validated, source-bound current-run "
                    "configured-peer baseline authorizes a positive BGP acceptance target. Re-collect the "
                    "running-config and scoped default/global IPv4 summary before cutover.",
                    f"The BGP configured-peer analysis failed closed: {reason}.",
                    evidence_state="not_verified",
                    projection_custody="embedded_unverified",
                    source_key="bgp_configured_peer_baseline",
                    bgp_metadata=placeholder,
                )

    # ---- Shared receipt-gated STP consistency owner.  Root placement remains a separate claim: a
    #      clean inconsistent-port baseline does not prove that an intended root stayed in place. ----
    stp_consistency = summarize_stp_consistency_baseline(
        protocol_health,
        protocol_assessability,
        all_interfaces=all_interfaces,
        stp_roots=stp,
    )
    for row in stp_consistency["rows"]:
        status = row["status"]
        check = {
            "assessed": "STP observed consistency baseline",
            "degraded": "STP degraded consistency baseline",
            "review": "STP consistency evidence review",
            "not_verified": "STP consistency baseline not verified",
        }[status]
        add(
            row["switch"], "STP", "Medium" if status == "assessed" else "High",
            check, row["command"], row["acceptance"], row["note"],
            evidence_state=status,
            projection_custody=row["projection_custody"],
            source_key=row["source_key"],
        )

    # ---- STP root placement unchanged (a moved root reconverges L2 and shifts forwarding paths). ----
    for host in sorted(stp):
        for vlan, info in sorted((stp.get(host) or {}).items(), key=lambda kv: _validation_wave_key(str(kv[0]))):
            if isinstance(info, dict) and info.get("is_root"):
                add(host, "STP", "Medium",
                    f"Spanning-tree root for VLAN {vlan} unchanged",
                    f"show spanning-tree vlan {vlan}",
                    f"{host} reports 'This bridge is the root' for VLAN {vlan}",
                    "If the root moves on cutover, the L2 topology reconverges and forwarding paths change.")

    # ---- Receipt-gated observed EtherChannel baseline.  The old path reconstructed an operational
    #      all-(P) claim from ``interfaces.*.port_channel`` associations, even though that projection
    #      intentionally drops member flags and can come from configuration alone.  Consume the shared
    #      group/member owner verbatim.  For older direct callers without a precomputed baseline, build an
    #      association-only/missing-capture projection so the result fails closed as REVIEW/NOT VERIFIED.
    baseline_view = validate_etherchannel_baseline(
        etherchannel_baseline,
        projection=etherchannel_projection,
        protocol_assessability=protocol_assessability,
        devices=devs,
    ) if etherchannel_projection is not _ETHERCHANNEL_BASELINE_UNSET else (
        validate_etherchannel_baseline(etherchannel_baseline)
    )
    if baseline_view["valid"]:
        resolved_etherchannel_baseline = etherchannel_baseline
    elif etherchannel_projection is not _ETHERCHANNEL_BASELINE_UNSET:
        # The caller supplied the exact current-run source but the carried baseline failed its
        # source-bound equality check. Recompute from that source so a forged/stale acceptance row
        # cannot both survive and erase a real SD/D blocker merely because interfaces has no Po leaf.
        resolved_etherchannel_baseline = summarize_etherchannel_baseline(
            etherchannel_projection,
            protocol_assessability,
            devs,
        )
    else:
        # Legacy direct callers have no raw summary projection. Preserve association-only subject
        # evidence, but never promote it to an operational member-state baseline.
        resolved_etherchannel_baseline = summarize_etherchannel_baseline(
            compute_etherchannel_projection(all_interfaces, {}),
            protocol_assessability,
            devs,
        )
    for row in resolved_etherchannel_baseline["rows"]:
        if not isinstance(row, dict):
            continue
        host = _strict_protocol_text(row.get("switch"))
        status = _strict_protocol_text(row.get("status"))
        if not host or status not in {"assessed", "degraded", "review", "not_verified"}:
            continue
        check = {
            "assessed": "Port-channel observed group/member baseline",
            "degraded": "Port-channel degraded group/member baseline",
            "review": "Port-channel group/member evidence review",
            "not_verified": "Port-channel group/member baseline not verified",
        }[status]
        acceptance = _strict_protocol_text(row.get("acceptance"))
        if not acceptance:
            status = "not_verified"
            check = "Port-channel group/member baseline not verified"
            acceptance = (
                "ETHERCHANNEL BASELINE NOT VERIFIED — BLOCKER: the shared baseline row is malformed. "
                "Re-collect the platform EtherChannel summary and verify exact group/member flags before acceptance."
            )
        command = _strict_protocol_text(row.get("command")) or (
            "show port-channel summary" if _is_nxos(_plat(host)) else "show etherchannel summary"
        )
        add(
            host, "Link", "Medium" if status == "assessed" else "High", check,
            command, acceptance,
            _strict_protocol_text(row.get("note")) or
            "Association-only evidence is not an operational member-state baseline.",
            evidence_state=status,
            projection_custody=_strict_protocol_text(row.get("projection_custody")) or
                               resolved_etherchannel_baseline.get("projection_custody", ""),
            source_key=_strict_protocol_text(row.get("source_key")),
        )

    items.sort(key=lambda it: (_validation_wave_key(it["wave"]), _VALIDATION_RANK.get(it["severity"], 9),
                               it["category"], str(it["device"]), it["check"]))
    by_wave: Dict[str, list] = defaultdict(list)
    for it in items:
        by_wave[it["wave"]].append(it)
    summary = {"n_items": len(items), "n_waves": len(by_wave),
               "by_category": dict(Counter(it["category"] for it in items)),
               "n_high": sum(1 for it in items if it["severity"] in ("Critical", "High"))}
    return {"items": items, "by_wave": dict(by_wave), "summary": summary, "banner": _VALIDATION_BANNER}


_CURRENT_BASELINE_MARKERS = {
    "PRE-CUTOVER DEGRADED — BLOCKER:": "degraded",
    "PRE-CUTOVER REVIEW — BLOCKER:": "review",
    "BGP CONFIGURED PEER NOT VERIFIED — BLOCKER:": "not_verified",
    "FHRP CONFIGURED GROUP NOT VERIFIED — BLOCKER:": "not_verified",
    "FHRP REDUNDANCY DOMAIN NOT VERIFIED — BLOCKER:": "not_verified",
    "ROUTING BASELINE NOT VERIFIED — BLOCKER:": "not_verified",
    "ETHERCHANNEL BASELINE NOT VERIFIED — BLOCKER:": "not_verified",
    "STP CONSISTENCY BASELINE NOT VERIFIED — BLOCKER:": "not_verified",
    "VTP SAFETY BASELINE NOT VERIFIED — BLOCKER:": "not_verified",
    "IPV6 ROUTING BASELINE NOT VERIFIED — BLOCKER:": "not_verified",
}
_CURRENT_BASELINE_STATES = {
    "assessed", "degraded", "review", "not_verified", "administratively_disabled"
}
_CURRENT_BASELINE_ROW_LIMIT = 50


def classify_current_baseline_item(item: Any) -> str:
    """Classify one cutover-validation row without interpreting arbitrary prose.

    Current producers publish ``evidence_state``.  The exact acceptance prefixes are retained
    only for legacy validation plans (notably pre-typed FHRP rows).  A typed state that contradicts
    a legacy marker is invalid rather than being reconciled optimistically.  The function is total,
    returns only a bounded vocabulary, and never echoes device-controlled input.
    """
    if not isinstance(item, dict):
        return "invalid"
    raw_state = item.get("evidence_state", "")
    if raw_state is None:
        raw_state = ""
    if not isinstance(raw_state, str):
        return "invalid"
    state = raw_state.strip().casefold()
    if state and state not in _CURRENT_BASELINE_STATES:
        return "invalid"

    expect = item.get("expect", "")
    if not isinstance(expect, str):
        return "invalid"
    marker_states = [marker_state for marker, marker_state in _CURRENT_BASELINE_MARKERS.items()
                     if expect.startswith(marker)]
    if len(marker_states) > 1:
        return "invalid"
    marker_state = marker_states[0] if marker_states else ""

    if state:
        classified = "clear" if state in {"assessed", "administratively_disabled"} else state
        if marker_state and marker_state != classified:
            return "invalid"
        return classified
    return marker_state or "clear"


def compute_current_baseline_gate(validation_plan: Any) -> dict:
    """Return the acceptance gate for the *current* snapshot's validation baseline.

    This complements the before/after delta: an unchanged degraded baseline is still a cutover
    blocker.  The receipt reconciles ``items``, ``by_wave``, and ``summary`` before consuming any
    row.  Invalid structures therefore abstain with no copied blocker rows or positive counts.
    """
    from collections import Counter, defaultdict

    limitations = [
        "The gate classifies the bounded validation-plan projection; it is not an expected-protocol denominator.",
        "Marker classification is compatibility-only; current producers should publish typed evidence_state.",
        f"At most {_CURRENT_BASELINE_ROW_LIMIT} blocker rows are returned; summary counts cover all valid rows.",
    ]

    def receipt(verdict: str, note: str, *, assessed: bool = False,
                blockers: Optional[List[dict]] = None, counts: Optional[dict] = None,
                failures: Optional[List[str]] = None, n_items: int = 0) -> dict:
        rows = blockers or []
        by_state = dict((counts or {}).get("by_state") or {
            "degraded": 0, "review": 0, "not_verified": 0,
        })
        by_wave = dict((counts or {}).get("by_wave") or {})
        n_blockers = sum(by_state.values())
        return {
            "schema": "current_baseline_gate/1",
            "verdict": verdict,
            "assessed": assessed,
            "note": note,
            "summary": {
                "n_items": n_items,
                "n_blockers": n_blockers,
                "n_blockers_returned": len(rows),
                "blockers_capped": n_blockers > len(rows),
                "by_state": by_state,
                "by_wave": by_wave,
            },
            "blockers": rows,
            "integrity": {"valid": not failures, "failures": list(failures or [])[:20]},
            "limitations": limitations,
        }

    if validation_plan is None or validation_plan == {}:
        return receipt(
            "NOT_ASSESSED",
            "Current validation baseline was not assessed: no validation plan was present. "
            "This is not evidence that the current snapshot has no cutover blockers.",
        )
    if not isinstance(validation_plan, dict):
        return receipt(
            "INDETERMINATE",
            "Current validation baseline is indeterminate: the validation-plan contract is malformed. "
            "No malformed row was interpreted as a blocker or an all-clear.",
            failures=["validation_plan is not an object"],
        )

    items = validation_plan.get("items")
    by_wave = validation_plan.get("by_wave")
    summary = validation_plan.get("summary")
    failures: List[str] = []
    if not isinstance(items, list):
        failures.append("items is not a list")
    if not isinstance(by_wave, dict):
        failures.append("by_wave is not an object")
    if not isinstance(summary, dict):
        failures.append("summary is not an object")
    if failures:
        return receipt(
            "INDETERMINATE",
            "Current validation baseline is indeterminate: required plan sections are missing or malformed. "
            "No malformed row was interpreted as a blocker or an all-clear.",
            failures=failures,
        )

    def valid_count(value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0

    required_text = ("device", "platform", "wave", "category", "severity", "check", "command", "expect", "why")
    optional_text = (
        "evidence_state", "projection_custody", "source_key",
        "peer", "peer_key", "local_as", "configured_remote_as", "activation",
        "runtime_remote_as", "runtime_state_raw", "runtime_state", "scope",
        "protocol", "interface", "group", "group_key", "configured_vip", "runtime_vip",
    )
    optional_bool = ("runtime_observed", "configured")

    def signature(row: Any, where: str) -> Optional[tuple]:
        if not isinstance(row, dict):
            failures.append(f"{where} contains a non-object row")
            return None
        for key in required_text:
            if not isinstance(row.get(key), str):
                failures.append(f"{where} row has a non-text {key}")
                return None
        if not all(row[key].strip() for key in ("device", "wave", "category", "severity", "check")):
            failures.append(f"{where} row is missing a required identity field")
            return None
        if row["severity"] not in _VALIDATION_RANK:
            failures.append(f"{where} row has an unknown severity")
            return None
        for key in optional_text:
            if key in row and row[key] is not None and not isinstance(row[key], str):
                failures.append(f"{where} row has a non-text {key}")
                return None
        for key in optional_bool:
            if key in row and not isinstance(row[key], bool):
                failures.append(f"{where} row has a non-boolean {key}")
                return None
        classification = classify_current_baseline_item(row)
        if classification == "invalid":
            failures.append(f"{where} row has conflicting or invalid evidence state")
            return None
        return (
            tuple(row.get(key, "") or "" for key in (*required_text, *optional_text))
            + tuple(row.get(key) if key in row else None for key in optional_bool)
        )

    item_signatures = [signature(row, "items") for row in items]
    if any(value is None for value in item_signatures):
        item_counter = Counter()
    else:
        item_counter = Counter(item_signatures)

    wave_counter: Counter = Counter()
    if isinstance(by_wave, dict):
        for wave, rows in by_wave.items():
            if not isinstance(wave, str) or not wave.strip():
                failures.append("by_wave contains an invalid wave key")
                continue
            if not isinstance(rows, list):
                failures.append("by_wave contains a non-list bucket")
                continue
            for row in rows:
                sig = signature(row, "by_wave")
                if sig is not None:
                    if row.get("wave") != wave:
                        failures.append("by_wave row does not match its wave bucket")
                    wave_counter[sig] += 1
    if item_counter != wave_counter:
        failures.append("items and by_wave do not reconcile")

    # Only already-validated text can reach Counter: an unhashable malformed category (list/dict)
    # must produce an abstaining receipt, not raise while building the reconciliation view.
    expected_category = Counter(
        row.get("category") for row in items
        if isinstance(row, dict) and isinstance(row.get("category"), str)
    )
    raw_by_category = summary.get("by_category")
    if not valid_count(summary.get("n_items")) or summary.get("n_items") != len(items):
        failures.append("summary.n_items does not reconcile")
    if not valid_count(summary.get("n_waves")) or summary.get("n_waves") != len(by_wave):
        failures.append("summary.n_waves does not reconcile")
    if not valid_count(summary.get("n_high")) or summary.get("n_high") != sum(
            isinstance(row, dict) and row.get("severity") in ("Critical", "High") for row in items):
        failures.append("summary.n_high does not reconcile")
    if (not isinstance(raw_by_category, dict)
            or any(not isinstance(key, str) or not valid_count(value)
                   for key, value in raw_by_category.items())
            or Counter(raw_by_category) != expected_category):
        failures.append("summary.by_category does not reconcile")

    if failures:
        # Do not return any copied row/count from an invalid plan: callers receive an abstention,
        # not an attacker-controlled apparent blocker and never a hostile apparent all-clear.
        return receipt(
            "INDETERMINATE",
            "Current validation baseline is indeterminate: plan items, waves, and summary did not reconcile. "
            "No malformed row was interpreted as a blocker or an all-clear.",
            failures=failures,
        )

    if not items:
        return receipt(
            "NOT_ASSESSED",
            "Current validation baseline was not assessed: the reconciled validation plan contains no subjects. "
            "This is not evidence that the current snapshot has no cutover blockers.",
        )

    classified = []
    counts_by_state = {"degraded": 0, "review": 0, "not_verified": 0}
    counts_by_wave: Dict[str, int] = defaultdict(int)

    def bounded(value: Any, limit: int) -> str:
        text = value.strip() if isinstance(value, str) else ""
        if len(text) <= limit:
            return text
        return text[:max(0, limit - 3)] + "..."

    for row in items:
        state = classify_current_baseline_item(row)
        if state == "clear":
            continue
        counts_by_state[state] += 1
        counts_by_wave[bounded(row["wave"], 120)] += 1
        if len(classified) < _CURRENT_BASELINE_ROW_LIMIT:
            classified.append({
                "device": bounded(row["device"], 120),
                "wave": bounded(row["wave"], 120),
                "category": bounded(row["category"], 80),
                "severity": bounded(row["severity"], 20),
                "check": bounded(row["check"], 240),
                "evidence_state": state,
                "expect": bounded(row["expect"], 600),
                "projection_custody": bounded(row.get("projection_custody"), 120),
                "source_key": bounded(row.get("source_key"), 300),
            })

    counts = {
        "by_state": counts_by_state,
        "by_wave": dict(sorted(counts_by_wave.items(), key=lambda item: _validation_wave_key(item[0]))),
    }
    if counts_by_state["degraded"]:
        verdict = "BLOCKED"
        note = (f"Current validation baseline BLOCKED: {counts_by_state['degraded']} definite degraded "
                f"baseline row(s) and {counts_by_state['review'] + counts_by_state['not_verified']} "
                "review/not-verified row(s) require disposition before cutover acceptance.")
    elif counts_by_state["review"] or counts_by_state["not_verified"]:
        verdict = "INDETERMINATE"
        note = ("Current validation baseline is indeterminate: "
                f"{counts_by_state['review']} review row(s) and "
                f"{counts_by_state['not_verified']} not-verified row(s) withhold acceptance.")
    else:
        verdict = "CLEAR"
        note = (f"Current validation baseline CLEAR: all {len(items)} reconciled validation row(s) are free "
                "of typed or legacy-marker blockers within the bounded validation-plan scope.")
    return receipt(
        verdict, note, assessed=True, blockers=classified, counts=counts, n_items=len(items),
    )


# =============================================================================
# Golden-config DRIFT (NEW-V3.23.146). Per-device running-config drift vs a baseline of REQUIRED directives.
# Baseline source = a user-supplied golden file (--golden-config) if given, else AUTO-DERIVED as the global
# (top-level) config lines present on a MAJORITY of devices (the fleet's de-facto standard) -> flag the
# outliers missing them. Matching is normalized (whitespace-collapsed, case-folded) substring/line match, so
# harmless indentation/spacing differences don't read as drift. Pure read of the running-configs; no new
# collection. Returns {mode, baseline, per_device, summary}.
# =============================================================================
def _norm_cfg_line(line: str) -> str:
    return re.sub(r"\s+", " ", (line or "").strip()).lower()


def compute_golden_drift(run_configs: Optional[dict] = None,
                         golden_lines: Optional[list] = None,
                         min_fraction: float = 0.6) -> dict:
    """Per-device running-config drift vs a baseline. With `golden_lines` (a supplied standard: each entry a
    required directive; `# ...` comments ignored; `re:<pattern>` for a regex) the baseline is those required
    directives, matched as normalized substrings of the config; otherwise it is AUTO-DERIVED as the global
    (top-level) config lines present on >= min_fraction of devices, and devices missing them are flagged.
    Returns {mode, baseline, per_device, summary}; deterministic; tolerant of empty input."""
    import math
    from collections import Counter
    rc = run_configs or {}
    hosts = sorted(rc)

    # Structural / identity / secret-bearing top-level lines are excluded from the auto-derived MAJORITY
    # baseline: they're per-device, not policy, so they'd be noise (and a majority of identical
    # 'interface Vlan1' lines isn't an org standard). The golden-FILE path searches the whole config and is
    # unaffected by this filter.
    _STRUCTURAL = ("interface ", "hostname ", "boot ", "banner ", "username ", "enable secret",
                   "enable password", "license ", "ip address ", "ipv6 address ", "snmp-server location",
                   "snmp-server contact", "ntp clock-period", "crypto pki", "certificate ", "description ")

    # 'show running-config' CLI preamble lines (emitted at column 0, but not config directives).
    _NONCONFIG = ("building configuration", "current configuration")

    def _top_lines(text):
        out = set()
        in_banner = False
        delim = None
        for raw in (text or "").splitlines():
            # A 'banner <type> <delim> ... <delim>' body is emitted at COLUMN 0 -- its ASCII-art, the '* … *'
            # border and the closing delimiter are NOT config directives. Track the banner block and skip its body,
            # else a fleet-wide banner makes its art a 'required' majority-baseline line -> cry-wolf drift the
            # instant one device's banner text differs (audit-5 FF#8/#14).
            if in_banner:
                if delim and delim in raw:
                    in_banner = False
                    delim = None
                continue
            bm = re.match(r"banner\s+\S+\s+(\S+)", raw.strip(), re.IGNORECASE)
            if bm:
                delim = bm.group(1)
                if delim not in raw.strip()[bm.end():]:    # multi-line banner: skip the body until the delim recurs
                    in_banner = True
                continue
            if raw[:1] in (" ", "\t"):          # skip indented sub-config (interface/etc. = device-specific noise)
                continue
            n = _norm_cfg_line(raw)
            if not n or n.startswith("!") or n in ("end", "exit"):
                continue
            if any(n.startswith(p) for p in _NONCONFIG):   # 'show run' CLI preamble, not a directive (audit-5 FF#14)
                continue
            if any(n.startswith(p) for p in _STRUCTURAL):
                continue
            out.add(n)
        return out

    if golden_lines:
        mode = "golden-file"
        reqs = []                                # (kind, matcher, original)
        for ln in golden_lines:
            s = (ln or "").strip()
            if not s or s.startswith("#"):
                continue
            if s[:3].lower() == "re:":
                try:
                    reqs.append(("re", re.compile(s[3:].strip(), re.I), s))
                except re.error:
                    continue
            else:
                reqs.append(("sub", _norm_cfg_line(s), s))
        baseline = [orig for (_k, _m, orig) in reqs]
        full = {h: "\n".join(_norm_cfg_line(x) for x in (rc[h] or "").splitlines()) for h in hosts}
        per_device = []
        for h in hosts:
            joined = full[h]
            missing = [orig for (kind, m, orig) in reqs
                       if not ((m.search(joined) is not None) if kind == "re" else (m in joined))]
            present = len(reqs) - len(missing)
            pct = round(100 * present / len(reqs)) if reqs else 100
            per_device.append({"host": h, "compliance_pct": pct, "n_missing": len(missing),
                               "missing": missing[:30]})
    else:
        mode = "majority"
        dev_lines = {h: _top_lines(rc[h]) for h in hosts}
        n = len(hosts)
        if n >= 3:                               # a majority baseline needs >= 3 devices to be meaningful
            freq = Counter()
            for h in hosts:
                freq.update(dev_lines[h])
            thr = max(2, math.ceil(min_fraction * n))
            baseline = sorted(line for line, c in freq.items() if c >= thr)
        else:
            baseline = []
        per_device = []
        for h in hosts:
            have = dev_lines[h]
            missing = [b for b in baseline if b not in have]
            present = len(baseline) - len(missing)
            pct = round(100 * present / len(baseline)) if baseline else 100
            per_device.append({"host": h, "compliance_pct": pct, "n_missing": len(missing),
                               "missing": missing[:30]})

    per_device.sort(key=lambda d: (d["compliance_pct"], d["host"]))
    n_drift = sum(1 for d in per_device if d["n_missing"] > 0)
    avg = round(sum(d["compliance_pct"] for d in per_device) / len(per_device)) if per_device else 100
    summary = {"mode": mode, "n_devices": len(per_device), "n_baseline": len(baseline),
               "n_drifting": n_drift, "avg_compliance_pct": avg}
    return {"mode": mode, "baseline": baseline, "per_device": per_device, "summary": summary}


# =============================================================================
# Syslog intelligence (NEW-V3.23.164). The NOS-style operational log analysis: Cisco's Network
# Optimization Service names "syslog analysis" (top-N events + critical/error trends) as one of
# its four analytic pillars; this is its offline twin. Evidence = each device's already-collected
# 'show logging' buffer. DETECTIONS encode the log signatures a senior engineer greps for first;
# every one is deterministic on the collected text. A device without 'show logging' output is
# reported NOT-COLLECTED -- absence of logs is never scored as absence of problems.
# =============================================================================
# severity ordering: the module-wide _SEV_RANK (V3.23.171 — was a private copy per axis)

# kind -> (label, severity, recommendation). The senior-engineer doctrine per signature.
_SYSLOG_DOCTRINE: Dict[str, tuple] = {
    "mac-flap": ("MAC address flapping", "High",
                 "The same MAC is being learned on two ports -- usually an L2 loop or a dual-homed "
                 "host. Verify STP state on both ports and resolve before this domain's cutover window."),
    "err-disable": ("Port err-disabled", "High",
                    "Find the err-disable cause ('show interfaces status err-disabled') and fix the "
                    "root cause -- do not blindly re-enable the port."),
    "stp-guard": ("STP guard fired", "High",
                  "Root/loop/BPDU guard blocked a topology change attempt. Identify the offending "
                  "port or device before migrating this L2 domain."),
    "stability": ("Memory/CPU distress or traceback", "High",
                  "The control plane recorded distress (MALLOCFAIL / CPUHOG / traceback). Check the "
                  "software release against Cisco Bug Search before loading this device with a "
                  "migration window."),
    "environment": ("Environmental alarm", "High",
                    "PSU / fan / thermal alarm in the log window. Replace the failing FRU before "
                    "the migration window -- environmental failures void redundancy assumptions."),
    "resource": ("Hardware table pressure", "High",
                 "TCAM / forwarding-table exhaustion messages recorded. A feature/scale review is "
                 "needed before adding load or routes to this device."),
    "link-flap": ("Interface flapping", "Medium",
                  "Repeated up/down transitions point at physical-layer instability (cable / optic / "
                  "negotiation). Fix the media -- flapping links invalidate pre-cutover baselines."),
    "duplex-mismatch": ("Duplex mismatch", "Medium",
                        "CDP detected a duplex mismatch with the neighbor. Set both ends to auto (or "
                        "pin both); late collisions silently throttle throughput."),
    "native-vlan-mismatch": ("Native VLAN mismatch", "Medium",
                             "CDP detected differing native VLANs across a trunk -- untagged frames "
                             "are leaking between VLANs. Align both trunk ends."),
    "storm-control": ("Traffic storm suppressed", "Medium",
                      "Storm-control engaged in the log window. Find the source host or loop -- "
                      "suppression is a symptom, not a fix."),
    "reload": ("Device restart recorded", "Medium",
               "The device restarted inside the log window. Correlate with change records and "
               "confirm it was planned before trusting this device's baseline."),
    "login-fail": ("Repeated login failures", "Medium",
                   "Multiple failed logins recorded. Confirm AAA health and check for unauthorized "
                   "access attempts before the migration window."),
    "optic-degraded": ("Transceiver / optic fault", "High",
                       "An SFP/optic reported a DOM threshold violation or an unsupported/invalid "
                       "transceiver in the log window -- a marginal or wrong optic corrupts the link and "
                       "is migrated as-is; replace / qualify it before the NRFU baseline."),
    "lacp-error": ("EtherChannel / LACP error", "High",
                   "LACP reported a member suspended / incompatible-partner / misconfig in the log window -- "
                   "a degraded port-channel silently loses capacity and redundancy; reconcile the bundle "
                   "before cutover."),
}

# >= this many DOWN transitions on ONE interface = a flap detection. V3.23.170: the counter
# tallies DOWN transitions only (one physical flap cycle emits up to four UPDOWN lines --
# LINK down/up + LINEPROTO down/up -- so counting every line both double-counted and rendered
# an inflated figure in the detection text).
_SYSLOG_LINK_FLAP_MIN = 3
# V3.23.170: the interface token in a link event line, precompiled (was an inline re.search
# per event -- this loop is hottest exactly during the flap storms the axis exists to catch).
_SYSLOG_IF_RE = re.compile(r"Interface ([A-Za-z0-9/\.\-]+)")
_SYSLOG_LOGIN_FAIL_MIN = 5       # >= this many login failures = a detection


def compute_syslog_intelligence(all_syslogs: Optional[Dict[str, str]] = None) -> dict:
    """NEW-V3.23.164: NOS-style syslog analysis from already-collected 'show logging' text
    ({host: raw_text}; '' = not collected). Per device: severity profile, top messages and a
    config-change count. Fleet-wide: deterministic DETECTIONS (MAC flap, err-disable, link flap,
    duplex / native-VLAN mismatch, STP guard, storm-control, crash/traceback, reload,
    environmental, TCAM pressure, login failures) each carrying the senior-engineer doctrine.
    The log buffer is a bounded recent window, so counts are floors, not totals. Pure on its
    inputs; deterministic; tolerant of empty input; never raises."""
    from collections import Counter
    logs = all_syslogs or {}
    per_device: List[dict] = []
    detections: List[dict] = []
    tot_events = tot_crit = tot_err = 0

    def _det(host: str, kind: str, count: int, detail: str, example: str) -> None:
        label, sev, rec = _SYSLOG_DOCTRINE[kind]
        detections.append({"host": host, "kind": kind, "label": label, "severity": sev,
                           "count": count, "detail": detail, "example": example[:220],
                           "recommendation": rec})

    for host in sorted(logs):
        text = logs[host] or ""
        if not text.strip():
            per_device.append({"host": host, "collected": False, "events": 0,
                               "by_severity": {}, "top_messages": [], "config_changes": 0})
            continue
        events = parse_syslog_events(text)
        sev_band = {"crit_0_2": 0, "err_3": 0, "warn_4": 0, "info_5_7": 0}
        msg_count: "Counter" = Counter()
        kind_events: Dict[str, List[dict]] = {}
        updown_by_intf: "Counter" = Counter()
        config_changes = 0
        login_fails = 0
        for ev in events:
            sev = ev["severity"]
            if sev <= 2:
                sev_band["crit_0_2"] += 1
            elif sev == 3:
                sev_band["err_3"] += 1
            elif sev == 4:
                sev_band["warn_4"] += 1
            else:
                sev_band["info_5_7"] += 1
            msg_count[f"{ev['facility']}-{sev}-{ev['mnemonic']}"] += 1
            # V3.23.170: facilities carry stacked-module suffixes ('LINK-SP') and NX-OS uses
            # different facility names entirely (ETHPORT/VSHD/L2FM) -- every check below matches
            # the facility FAMILY (startswith) and the NX-OS equivalents, never an exact IOS literal.
            fac, mn = ev["facility"], ev["mnemonic"]
            kind = None
            if "MACFLAP" in mn or "MAC_FLAP" in mn or "MAC_MOVE" in mn:
                kind = "mac-flap"                      # IOS SW_MATM MACFLAP / NX-OS L2FM MAC_MOVE
            elif "ERR_DISABLE" in mn or "ERRDISABLE" in mn or "ERROR_DISABLED" in mn:
                kind = "err-disable"
            elif fac.startswith("SPANTREE") and any(t in mn for t in
                                                    ("ROOTGUARD", "LOOPGUARD", "BPDUGUARD", "BLOCK", "PVID")):
                kind = "stp-guard"
            else:
                up = ev["raw"].upper()                 # built only past the cheap mnemonic branches
                if mn in ("MALLOCFAIL", "CPUHOG") or "TRACEBACK" in up:
                    kind = "stability"
                elif (("ENV" in fac or "THERMAL" in fac)
                      or fac.startswith(("PFMA", "NOHMS", "PLATFORM_FEP", "NGWC_PLATFORM_FEP"))   # NX-OS/Cat9K power/FRU
                      or any(t in mn for t in ("FAN", "TEMP", "THERM", "PSU", "POWER",
                                               "PS_FAIL", "FRU_PS", "PFM_ALERT", "PS_CAPACITY"))) and (
                          sev <= 3 or any(t in mn for t in ("BAD", "FAIL", "FAULT", "REMOV", "SHUT", "DOWN"))):
                    # a sev-4 hardware FAILURE (Catalyst 4500/4948 '%...-4-POWERSUPPLYBAD') is real -- the old
                    # 'sev <= 3' gate silently dropped it as healthy (audit-5 #11); benign sev-4 env info (FANOK) skipped.
                    kind = "environment"
                elif "TCAM" in up and any(t in up for t in ("EXCEED", "EXHAUST", "FULL", "EXCEPTION")):
                    kind = "resource"
                elif "DUPLEX_MISMATCH" in mn:
                    kind = "duplex-mismatch"
                elif "NATIVE_VLAN_MISMATCH" in mn:
                    kind = "native-vlan-mismatch"
                elif fac.startswith("STORM_CONTROL"):
                    kind = "storm-control"
                elif "SFF8472" in fac or any(t in mn for t in
                        ("SFF8472", "UNSUPPORTED_TRANSCEIVER", "GBIC_INVALID", "SFP_NOT_SUPPORTED", "UNSUPPORTED_SFP")):
                    kind = "optic-degraded"      # DOM threshold violation / unsupported|invalid transceiver
                elif (fac.startswith(("ETH_PORT_CHANNEL", "LACP")) or fac == "EC") and any(t in mn for t in
                        ("SUSPEND", "INCOMPAT", "MISCFG", "MISCONFIG", "LACP_ERR")):
                    kind = "lacp-error"          # unambiguous LACP errors only (benign bundle events excluded)
                elif mn == "RESTART" or "SYSTEM RESTARTED" in up:
                    kind = "reload"
            if kind:
                kind_events.setdefault(kind, []).append(ev)
            # link flap: count DOWN transitions only (LINEPROTO mirrors LINK -- counting both
            # double-counts one physical cycle). IOS: %LINK[-SP]-3-UPDOWN '... state to down';
            # NX-OS: %ETHPORT-5-IF_DOWN_<cause>.
            is_down = ((fac.startswith("LINK") and mn == "UPDOWN" and "to down" in ev["msg"])
                       or (fac.startswith("ETHPORT") and mn.startswith("IF_DOWN")))
            if is_down:
                im = _SYSLOG_IF_RE.search(ev["msg"])
                if im:
                    updown_by_intf[im.group(1)] += 1
            # config-change audit: IOS %SYS[-SP]-5-CONFIG_I / NX-OS %VSHD-5-VSHD_SYSLOG_CONFIG_I
            if mn.endswith("CONFIG_I"):
                config_changes += 1
            # IOS: %SEC_LOGIN-...-LOGIN_FAILED; NX-OS/AAA: %AUTHPRIV/%DAEMON/%AAA '... authentication failed'.
            if (("LOGIN" in fac and "FAIL" in mn)
                    or (fac in ("AUTHPRIV", "DAEMON", "AAA") and "AUTHENTICATION FAIL" in ev["raw"].upper())):
                login_fails += 1

        for kind in sorted(kind_events):
            evs = kind_events[kind]
            _det(host, kind, len(evs), f"{len(evs)} event(s) in the collected log window.",
                 evs[0]["raw"])
        flapping = sorted((i for i, c in updown_by_intf.items() if c >= _SYSLOG_LINK_FLAP_MIN),
                          key=lambda i: (-updown_by_intf[i], i))
        if flapping:
            head = ", ".join(f"{i} ({updown_by_intf[i]}x)" for i in flapping[:5])
            _det(host, "link-flap", sum(updown_by_intf[i] for i in flapping),
                 f"{len(flapping)} interface(s) with >= {_SYSLOG_LINK_FLAP_MIN} down "
                 f"transitions: {head}.", "")
        if login_fails >= _SYSLOG_LOGIN_FAIL_MIN:
            _det(host, "login-fail", login_fails,
                 f"{login_fails} failed login(s) in the collected log window.", "")

        tot_events += len(events)
        tot_crit += sev_band["crit_0_2"]
        tot_err += sev_band["err_3"]
        per_device.append({
            "host": host, "collected": True, "events": len(events), "by_severity": sev_band,
            "top_messages": [{"msg": k, "count": c} for k, c in
                             sorted(msg_count.items(), key=lambda kv: (-kv[1], kv[0]))[:6]],
            "config_changes": config_changes})

    detections.sort(key=lambda d: (_SEV_RANK.get(d["severity"], 9), d["host"], d["kind"]))
    collected = [d for d in per_device if d["collected"]]
    not_collected = [d["host"] for d in per_device if not d["collected"]]
    by_kind = Counter(d["kind"] for d in detections)
    summary = {"n_devices": len(per_device), "n_collected": len(collected),
               "n_not_collected": len(not_collected), "hosts_not_collected": not_collected[:20],
               "total_events": tot_events, "crit_0_2": tot_crit, "err_3": tot_err,
               "n_detections": len(detections), "by_kind": dict(sorted(by_kind.items()))}
    note = ("Evidence is each device's buffered 'show logging' at collection time -- a bounded, "
            "recent window (the buffer wraps), so counts are floors, not totals. Devices listed "
            "as not-collected carry no log evidence either way.")
    return {"per_device": per_device, "detections": detections, "summary": summary, "note": note}


# =============================================================================
# QoS & service-policy audit (NEW-V3.23.165). QoS is a named design domain in every Cisco HLD/LLD
# (trust boundary at the access edge, per-hop behavior consistency fleet-wide) and the campus
# leading practice is explicit: trust only detected phones/APs at the edge, mark/police at ingress,
# queue on uplinks. This axis audits the CONFIGURED posture from the captured running-configs --
# config evidence only (never live queue counters), and a device without a full running-config
# capture is declared NOT ASSESSABLE, never scored.
# =============================================================================
# severity ordering: the module-wide _SEV_RANK (V3.23.171 — was a private copy per axis)

_QOS_DOCTRINE: Dict[str, tuple] = {
    "voice-without-qos": ("Voice VLAN without a QoS edge policy", "High",
                          "A voice VLAN whose port carries no trust statement, auto-QoS macro or "
                          "service-policy means phone markings are not honored at the edge. Trust "
                          "the phone ('trust device cisco-phone' / 'auto qos voip cisco-phone') or "
                          "attach the access policy before migrating voice."),
    "no-trust-boundary": ("QoS enabled with no trust boundary", "High",
                          "'mls qos' makes every port untrusted by default, so ingress CoS/DSCP is "
                          "remarked to 0 fleet-wide -- QoS in this state actively harms traffic. "
                          "Define the trust boundary (trust phones/APs/uplinks, mark at access) or "
                          "remove the global enable."),
    "inert-policy": ("Policy-maps defined but attached nowhere", "Medium",
                     "QoS policy exists only on paper: no interface or system target carries a "
                     "service-policy. Attach the policies or remove the dead config before it "
                     "misleads the next engineer."),
    "undefined-policy-ref": ("service-policy references a missing policy-map", "Medium",
                             "An attached service-policy names a policy-map that is absent from the "
                             "captured config. Verify the capture is complete, or fix the dangling "
                             "reference."),
    "mixed-posture": ("Inconsistent QoS posture across the fleet", "Medium",
                      "End-to-end QoS is only as good as the weakest hop: one unconfigured switch "
                      "in the path queues FIFO and may re-mark. Standardize the per-hop behavior "
                      "(same trust + queuing template per role) before the migration."),
    "best-effort-fleet": ("No QoS configured anywhere", "Low",
                          "The whole assessable fleet runs best-effort. Acceptable for pure data; a "
                          "documented risk if voice/video/storage rides this network. Record the "
                          "customer's stance as a CRD requirement before the migration."),
}


def compute_qos_audit(run_configs: Optional[Dict[str, str]] = None,
                      all_hosts: Optional[List[str]] = None) -> dict:
    """NEW-V3.23.165: audit the CONFIGURED QoS posture per device from the captured full
    running-configs ({host: text}); `all_hosts` (optional) is the complete fleet so devices
    without a capture are DECLARED not-assessable. Per device: mechanisms in use (MQC /
    auto-QoS / 'mls qos'), object + attachment + trust + voice-port counts. Fleet: doctrine
    findings (voice edge without QoS, trust-boundary absent, inert/dangling policy, mixed
    posture, best-effort fleet). Config-derived only -- never live queue state. Pure on its
    inputs; deterministic; tolerant of empty input; never raises."""
    from collections import Counter
    rc = run_configs or {}
    hosts = sorted(set(all_hosts or []) | set(rc))
    per_device: List[dict] = []
    findings: List[dict] = []

    def _find(host: str, kind: str, detail: str) -> None:
        label, sev, rec = _QOS_DOCTRINE[kind]
        findings.append({"host": host, "kind": kind, "label": label, "severity": sev,
                         "detail": detail, "recommendation": rec})

    n_voice_total = 0
    for host in hosts:
        text = (rc.get(host) or "").strip()
        if not text:
            per_device.append({"host": host, "assessable": False, "mode": "not assessable",
                               "n_class_maps": 0, "n_policy_maps": 0, "n_attached_if": 0,
                               "n_trust_if": 0, "n_auto_if": 0, "n_voice_if": 0,
                               "posture": "Not assessable — full running-config not captured."})
            continue
        q = parse_qos_config(text)
        ifs = q["interfaces"]
        attached_if = [i for i, a in ifs.items() if a["policy_in"] or a["policy_out"]]
        trust_if = [i for i, a in ifs.items() if a["trust"]]
        auto_if = [i for i, a in ifs.items() if a["auto_qos"]]
        voice_if = [i for i, a in ifs.items() if a["voice_vlan"]]
        n_voice_total += len(voice_if)
        mechanisms = []
        if q["policy_maps"] or attached_if or q["global_attach"]:
            mechanisms.append("MQC")
        if auto_if:
            mechanisms.append("auto-QoS")
        if q["mls_qos"]:
            mechanisms.append("mls qos")
        # V3.23.170: mode and has_qos use ONE predicate -- a class-maps-only device (config
        # debris, or the Nexus default class-fcoe maps) previously read has_qos=True yet
        # mode "none", landing in without_qos and falsifying the best-effort-fleet claim.
        if mechanisms:
            mode = " + ".join(mechanisms)
        elif trust_if:
            mode = "trust-only"
        elif q["class_maps"]:
            mode = "objects-only"
        else:
            mode = "none"
        if mode == "none":
            posture = "No QoS configuration — all traffic is forwarded best-effort."
        elif mode == "objects-only":
            posture = (f"objects-only: {len(q['class_maps'])} class-map(s) defined but no "
                       "policy attaches anywhere — effectively best-effort.")
        else:
            posture = (f"{mode}: {len(q['policy_maps'])} policy-map(s), service-policy on "
                       f"{len(attached_if)} interface(s), trust on {len(trust_if)}, "
                       f"auto-QoS on {len(auto_if)}.")
        per_device.append({"host": host, "assessable": True, "mode": mode,
                           "n_class_maps": len(q["class_maps"]), "n_policy_maps": len(q["policy_maps"]),
                           "n_attached_if": len(attached_if), "n_trust_if": len(trust_if),
                           "n_auto_if": len(auto_if), "n_voice_if": len(voice_if),
                           "posture": posture})

        # per-device doctrine checks
        naked_voice = sorted(i for i in voice_if
                             if not (ifs[i]["trust"] or ifs[i]["auto_qos"]
                                     or ifs[i]["policy_in"] or ifs[i]["policy_out"]))
        if naked_voice:
            _find(host, "voice-without-qos",
                  f"{len(naked_voice)} voice-VLAN port(s) with no trust / auto-QoS / "
                  f"service-policy: {', '.join(naked_voice[:6])}"
                  + (" …" if len(naked_voice) > 6 else "") + ".")
        if q["mls_qos"] and not (trust_if or auto_if or attached_if or q["global_attach"]):
            _find(host, "no-trust-boundary",
                  "'mls qos' is enabled globally but no interface carries a trust statement, "
                  "auto-QoS macro or service-policy.")
        if q["policy_maps"] and not (attached_if or q["global_attach"]):
            _find(host, "inert-policy",
                  f"{len(q['policy_maps'])} policy-map(s) defined "
                  f"({', '.join(q['policy_maps'][:5])}) but no service-policy attaches any of them.")
        attached_names = sorted({a["policy_in"] for a in ifs.values() if a["policy_in"]}
                                | {a["policy_out"] for a in ifs.values() if a["policy_out"]}
                                | set(q["global_attach"]))
        # V3.23.170: NX-OS system-defined policies (default-nq-*, fcoe-default-*, copp-system-*)
        # are attached in the plain running-config but DEFINED only in 'show running-config all' --
        # flagging them as dangling raised a false Medium on every stock Nexus.
        dangling = [n for n in attached_names
                    if n not in q["policy_maps"]
                    and not n.lower().startswith(("default-", "fcoe-default", "copp-system"))]
        if dangling:
            _find(host, "undefined-policy-ref",
                  f"service-policy attaches {', '.join(dangling[:5])} but no such policy-map "
                  "exists in the captured config.")

    # fleet-level doctrine checks (assessable devices only)
    assessable = [d for d in per_device if d["assessable"]]
    # V3.23.170: fleet consistency judges ACTIVE QoS only -- objects-only devices (class-maps
    # defined, nothing attached) are effectively best-effort, so they sit on the without side
    # and the best-effort text stays truthful ('no ACTIVE configuration').
    with_qos = [d["host"] for d in assessable if d["mode"] not in ("none", "objects-only")]
    without_qos = [d["host"] for d in assessable if d["mode"] in ("none", "objects-only")]
    if with_qos and without_qos:
        _find("(fleet)", "mixed-posture",
              f"{len(with_qos)} device(s) carry active QoS configuration ({', '.join(with_qos[:5])}) "
              f"while {len(without_qos)} carry none ({', '.join(without_qos[:5])}).")
    elif assessable and not with_qos:
        _find("(fleet)", "best-effort-fleet",
              f"None of the {len(assessable)} assessable device(s) has any active QoS "
              "configuration (policies attached, trust, or auto-QoS).")

    findings.sort(key=lambda f: (_SEV_RANK.get(f["severity"], 9), f["host"], f["kind"]))
    not_assessable = [d["host"] for d in per_device if not d["assessable"]]
    summary = {"n_devices": len(per_device), "n_assessable": len(assessable),
               "n_not_assessable": len(not_assessable), "hosts_not_assessable": not_assessable[:20],
               "modes": dict(sorted(Counter(d["mode"] for d in assessable).items())),
               "n_voice_ports": n_voice_total, "n_findings": len(findings),
               "by_kind": dict(sorted(Counter(f["kind"] for f in findings).items()))}
    note = ("Assessed from the captured running-config only — the CONFIGURED posture, not live "
            "queue counters. A device without a full 'show running-config' capture is declared "
            "not assessable, never scored.")
    return {"per_device": per_device, "findings": findings, "summary": summary, "note": note}


# =============================================================================
# Software risk screening (NEW-V3.23.166). The last pillar of Cisco's NOS analytic quartet
# (design review / config best practices / syslog analysis / SOFTWARE RISK). Two evidence-led
# layers, both honest about what an OFFLINE tool can know:
#   (1) ATTACK-SURFACE screening -- config-evidenced exposed services joined to a curated KB of
#       landmark public advisories (the ones a senior engineer checks first because they were
#       exploited in the wild). The claim is always "this surface is open and it is the surface
#       of advisory X" -- NEVER "this device is vulnerable to X": release applicability must be
#       validated with the Cisco PSIRT Software Checker (no live feed offline).
#   (2) SOFTWARE-TRAIN lifecycle -- a cautious, curated classification of the running release's
#       train (12.x / 15.x / XE 3.x|16.x|17.x / NX-OS 6|7|9|10) into replace / verify / current-era
#       bands with verify-against-Cisco wording; never an invented per-release EoL date.
# =============================================================================
# severity ordering: the module-wide _SEV_RANK (V3.23.171 — was a private copy per axis)

# kind -> (surface label, severity, [(advisory id, cve, note)], why, fix)
_SWRISK_SURFACE_KB: Dict[str, tuple] = {
    "http-server": (
        "Device web UI (ip http server / secure-server)", "High",
        [("cisco-sa-iosxe-webui-privesc-j22SaA4z", "CVE-2023-20198",
          "actively exploited in the wild (web-UI privilege escalation, CVSS 10)")],
        "The IOS XE web UI was mass-exploited in 2023-24 (tens of thousands of devices "
        "implanted); any HTTP(S) server on a network device is standing attack surface.",
        "Disable 'ip http server' / 'ip http secure-server', or restrict them to the management "
        "network with an ACL; validate the running release with the Cisco Software Checker."),
    "snmp-v2c-rw": (
        "SNMP v1/v2c with a READ-WRITE community", "High",
        [("cisco-sa-snmp-x4LPhte", "CVE-2025-20352",
          "exploited in the wild (SNMP stack overflow -> RCE/DoS)")],
        "A v2c RW community is full configuration control protected by a cleartext string, and "
        "the SNMP stack itself has had exploited RCEs.",
        "Remove v1/v2c communities (RW first), move to SNMPv3 auth+priv, and ACL the SNMP "
        "service to the management stations."),
    "snmp-v2c-ro": (
        "SNMP v1/v2c read-only community", "Medium",
        [("cisco-sa-snmp-x4LPhte", "CVE-2025-20352",
          "exploited in the wild (SNMP stack overflow -> RCE/DoS)")],
        "Cleartext community strings leak topology and credentials material, and v1/v2c packets "
        "still reach the (historically exploited) SNMP stack.",
        "Move to SNMPv3 auth+priv and ACL the SNMP service."),
    "smart-install": (
        "Smart Install (vstack)", "High",
        [("cisco-sa-20180328-smi", "CVE-2018-0171",
          "mass-abused since 2018; CISA re-warned in 2024 that state actors still leverage "
          "exposed Smart Install")],
        "An exposed Smart Install client allows unauthenticated config/image replacement on "
        "older Catalyst platforms.",
        "Configure 'no vstack' on every switch that is not actively being zero-touch "
        "provisioned, and verify with 'show vstack config'."),
    "telnet-vty": (
        "Telnet enabled on vty lines", "Medium", [],
        "Telnet sends credentials and session content in cleartext -- one capture on any "
        "transit segment is a full management compromise.",
        "Set 'transport input ssh' on all vty lines (and verify SSHv2-only)."),
    "ssh-v1": (
        "SSH protocol version 1", "Medium", [],
        "SSHv1 has known protocol-level weaknesses (CRC32 insertion) and is long deprecated.",
        "Configure 'ip ssh version 2'."),
    "ikev1": (
        "IKEv1 (crypto isakmp)", "Medium",
        [("cisco-sa-20160916-ikev1", "CVE-2016-6415",
          "information disclosure (BENIGNCERTAIN, an exploited NSA-toolkit leak)")],
        "IKEv1 endpoints have leaked memory contents to crafted packets and lack IKEv2's "
        "anti-DoS protections.",
        "Migrate crypto peers to IKEv2; if IKEv1 must stay, restrict peers with an ACL and "
        "validate the release with the Cisco Software Checker."),
    "small-services": (
        "Legacy small services (finger / rcmd / small-servers)", "Low", [],
        "Legacy diagnostic services expose information and reflection primitives for no "
        "operational benefit on a modern network.",
        "Remove 'service finger' / 'ip rcmd ...' / TCP-UDP small-servers."),
}

# train prefix tables: (match fn input = sw_version string, platform hint) -> (train, band, note)
_SWRISK_BAND_RANK = {"Replace/Upgrade": 0, "Verify EoL": 1, "Current-era": 2, "Unknown": 3}


def _swrisk_train(sw: str, platform: str) -> tuple:
    """Classify a running release string into a cautious lifecycle band:
    (train, band, note). Curated train-level knowledge only -- never an invented
    per-release date; 'verify' wording points at Cisco's published notices."""
    s = str(sw or "").strip()
    if not s:
        return ("(unknown)", "Unknown", "Version not captured -- not assessable.")
    p = (platform or "").lower()
    checks = [
        ("12.", "Classic IOS 12.x", "Replace/Upgrade",
         "End of software maintenance long past -- no current PSIRT fixes are produced for this "
         "train. Plan replacement or upgrade before the migration."),
        ("15.", "Classic IOS 15.x", "Verify EoL",
         "Most 15.x trains are past end of software maintenance -- verify the platform's EoL "
         "notice and target the published recommended release."),
        ("03.", "IOS XE 3.x", "Replace/Upgrade",
         "The converged-access IOS XE 3.x trains are past end of software maintenance. Plan the "
         "upgrade path to a supported XE release."),
        ("16.", "IOS XE 16.x", "Verify EoL",
         "Software maintenance has ended for most 16.x releases (16.12 was the final LTS) -- "
         "verify against Cisco's published notices and the recommended-release page."),
        ("17.", "IOS XE 17.x", "Current-era",
         "Current-era train -- validate the exact release against the recommended-release page "
         "and the Cisco Software Checker."),
    ]
    if p == "nxos":
        checks = [
            ("6.", "NX-OS 6.x", "Replace/Upgrade",
             "NX-OS 6.x is long past software maintenance -- plan the upgrade/replacement."),
            ("7.", "NX-OS 7.x", "Verify EoL",
             "Most NX-OS 7.x trains are past or near end of maintenance -- verify the platform's "
             "notice and the recommended NX-OS release."),
            ("9.", "NX-OS 9.x", "Current-era",
             "Mature train -- validate the exact release against the recommended NX-OS release "
             "for the platform."),
            ("10.", "NX-OS 10.x", "Current-era",
             "Current-era train -- validate the exact release against the recommended NX-OS "
             "release for the platform."),
        ]
    for prefix, train, band, note in checks:
        if s.startswith(prefix):
            return (train, band, note)
    return (f"({s.split('(')[0].strip() or s})", "Unknown",
            "Train not in the curated table -- verify the release against Cisco's published "
            "EoL notices and the Software Checker.")


def compute_software_risk(run_configs: Optional[Dict[str, str]] = None,
                          devices: Optional[Dict[str, dict]] = None,
                          platforms: Optional[Dict[str, dict]] = None,
                          all_hosts: Optional[List[str]] = None) -> dict:
    """NEW-V3.23.166: the NOS 'software risk analysis' pillar, offline-honest. From the captured
    full running-configs: attack-surface SCREENING (exposed web UI / SNMP v1-v2c / Smart Install /
    telnet / SSHv1 / IKEv1 / small services) joined to a curated landmark-advisory KB -- the claim
    is 'surface open' + 'this is the surface of advisory X (exploited in the wild)', never a
    per-release vulnerability verdict. From `devices` ({host:{model,sw_version}}) + `platforms`
    ({host:{platform}}): cautious software-TRAIN lifecycle bands (replace / verify / current-era)
    with verify-with-Cisco wording. A device without evidence for a layer is DECLARED not
    assessable for that layer. Pure on its inputs; deterministic; never raises."""
    from collections import Counter
    rc = run_configs or {}
    dv = devices or {}
    pf = platforms or {}
    hosts = sorted(set(all_hosts or []) | set(rc) | set(dv))
    per_device: List[dict] = []
    findings: List[dict] = []

    def _surface_status(text: str) -> Dict[str, tuple]:
        """kind -> (status, evidence). status: exposed / closed / verify."""
        lines = [ln.strip() for ln in text.splitlines()]
        def has(pat):
            rx = re.compile(pat, re.I)
            for ln in lines:
                if rx.match(ln):
                    return ln
            return None
        out: Dict[str, tuple] = {}
        hs = has(r"^ip http server$") or has(r"^ip http secure-server$")
        if hs:
            out["http-server"] = ("exposed", hs)
        elif has(r"^no ip http server$") or has(r"^no ip http secure-server$"):
            out["http-server"] = ("closed", "no ip http server")
        else:
            out["http-server"] = ("verify", "no explicit http-server line in the capture")
        # V3.23.170: the optional 'view <name>' qualifier sits between the community string and
        # the rw keyword ('snmp-server community <str> [view <name>] [ro|rw] [acl]') -- without
        # it a view-restricted READ-WRITE community was misclassified as read-only (High->Medium).
        if has(r"^snmp-server community\s+\S+(?:\s+view\s+\S+)?\s+rw\b"):
            out["snmp-v2c-rw"] = ("exposed", "snmp-server community <redacted> RW")
        elif has(r"^snmp-server community\s+\S+"):
            out["snmp-v2c-ro"] = ("exposed", "snmp-server community <redacted>")
        vs = has(r"^vstack($|\s)")
        if vs:
            out["smart-install"] = ("exposed", vs)
        elif has(r"^no vstack($|\s)"):
            out["smart-install"] = ("closed", "no vstack")
        else:
            out["smart-install"] = ("verify",
                                    "no vstack line in the capture -- default-on for older "
                                    "Catalyst; confirm with 'show vstack config'")
        # V3.23.170: 'transport input all' (the legacy form and old default) also permits telnet --
        # the CIS detector (parse_security) already treats it that way; the two now agree.
        tl = has(r"^transport input .*\b(?:telnet|all)\b")
        if tl:
            out["telnet-vty"] = ("exposed", tl)
        if has(r"^ip ssh version 1$"):
            out["ssh-v1"] = ("exposed", "ip ssh version 1")
        if has(r"^crypto isakmp policy"):
            out["ikev1"] = ("exposed", "crypto isakmp policy ...")
        sm = has(r"^service finger$") or has(r"^ip rcmd") or has(r"^service (tcp|udp)-small-servers$")
        if sm:
            out["small-services"] = ("exposed", sm)
        return out

    for host in hosts:
        text = (rc.get(host) or "").strip()
        meta = dv.get(host) or {}
        sw = str(meta.get("sw_version") or "").strip()
        platform = ((pf.get(host) or {}).get("platform") or "").strip()
        train, band, tnote = _swrisk_train(sw, platform)
        surfaces: Dict[str, str] = {}
        if text:
            st = _surface_status(text)
            for kind, (status, evidence) in sorted(st.items()):
                surfaces[kind] = status
                if status != "exposed":
                    continue
                label, sev, advs, why, fix = _SWRISK_SURFACE_KB[kind]
                findings.append({
                    "host": host, "kind": kind, "surface": label, "severity": sev,
                    # V3.23.171: label/detail ALIASES of surface/why -- the common finding
                    # shape the other three axes emit, so generic consumers (the punch-list
                    # fold, any future findings surface) need no per-axis adapter.
                    "label": label, "detail": why,
                    "evidence": evidence,
                    "advisories": [{"id": a, "cve": c, "note": n} for a, c, n in advs],
                    "why": why, "recommendation": fix})
        per_device.append({
            "host": host, "sw_version": sw or "(not captured)", "platform": platform or "?",
            "train": train, "train_band": band, "train_note": tnote,
            "config_assessable": bool(text), "surfaces": surfaces})

    findings.sort(key=lambda f: (_SEV_RANK.get(f["severity"], 9), f["host"], f["kind"]))
    per_device.sort(key=lambda d: (_SWRISK_BAND_RANK.get(d["train_band"], 9), d["host"]))
    assessable = [d for d in per_device if d["config_assessable"]]
    not_assessable = [d["host"] for d in per_device if not d["config_assessable"]]
    summary = {"n_devices": len(per_device), "n_config_assessable": len(assessable),
               "n_config_not_assessable": len(not_assessable),
               "hosts_config_not_assessable": sorted(not_assessable)[:20],
               "n_version_known": sum(1 for d in per_device if d["sw_version"] != "(not captured)"),
               "trains": dict(sorted(Counter(d["train"] for d in per_device).items())),
               "train_bands": dict(sorted(Counter(d["train_band"] for d in per_device).items())),
               "n_findings": len(findings),
               "by_kind": dict(sorted(Counter(f["kind"] for f in findings).items()))}
    note = ("Attack-surface SCREENING from configuration evidence joined to landmark public "
            "advisories -- not a vulnerability scan. The offline toolkit carries no live advisory "
            "feed: validate every running release with the Cisco PSIRT Software Checker, and read "
            "'exposed' as 'this surface is open', never as 'this release is vulnerable'.")
    return {"per_device": per_device, "findings": findings, "summary": summary, "note": note}


# =============================================================================
# Platform health (NEW-V3.23.167). The control-plane capacity question a senior engineer asks
# BEFORE adding migration load: "is this control plane already stressed?" Evidence = the device's
# own 'show processes cpu' / 'show processes memory' (IOS) and 'show system resources' (NX-OS),
# all captured at collection time. HONESTY: this is a single point-in-time sample -- a snapshot,
# not a trend -- so bands are screening, to be correlated with the syslog axis (CPUHOG/MALLOCFAIL
# events) and re-sampled before the migration window. A device whose capacity commands were not
# collected is DECLARED not collected, never scored.
# =============================================================================
_PLATHEALTH_CPU_HOT = 80        # 5-min CPU % >= this -> High
_PLATHEALTH_CPU_ELEVATED = 60   # 5-min CPU % >= this -> Medium
_PLATHEALTH_MEM_CRIT_PCT = 10   # free memory % <= this -> High
_PLATHEALTH_MEM_LOW_PCT = 20    # free memory % <= this -> Medium
_PLATHEALTH_BAND_RANK = {"Hot": 0, "Elevated": 1, "OK": 2, "Unknown": 3}

_PLATHEALTH_DOCTRINE: Dict[str, tuple] = {
    "hot-cpu": ("Control-plane CPU hot", "High",
                "A 5-minute CPU at/above 80% leaves no headroom for an STP/IGP reconvergence "
                "event or a config push. Find the consumer (processes vs interrupts), fix it, "
                "and re-sample before scheduling this device in a migration window."),
    "elevated-cpu": ("Control-plane CPU elevated", "Medium",
                     "A 5-minute CPU at/above 60% is workable but worth explaining before the "
                     "cutover adds protocol churn. Identify the top processes and confirm the "
                     "level is expected for this role."),
    "cpu-sample-high": ("Control-plane CPU high (instantaneous sample)", "Medium",
                        "The only CPU figure available is a single-instant reading ('show system "
                        "resources'), which can spike while the device renders show output. "
                        "Re-sample with 'show processes cpu' and judge the 5-minute average "
                        "before treating this device as a blocker."),
    "low-memory": ("Processor memory low", "High",
                   "Free processor memory at/below 10% risks MALLOCFAIL under churn -- routing "
                   "updates and config pushes allocate. Free or upgrade memory before the window."),
    "memory-watch": ("Processor memory tight", "Medium",
                     "Free processor memory at/below 20% deserves a check: confirm it is stable "
                     "(not leaking) and budget for the migration's added table churn."),
}


def compute_platform_health(metrics: Optional[Dict[str, dict]] = None) -> dict:
    """NEW-V3.23.167: per-device control-plane capacity screening from
    {host: {cpu, memory, system}} (build_platform_metrics; all-empty member dicts =
    not collected). CPU prefers the 5-minute average ('show processes cpu'); NX-OS
    falls back to 'show system resources' (instantaneous busy = 100 - idle, flagged
    as such). Memory prefers the IOS processor pool, else NX-OS system memory.
    Findings carry the pre-migration doctrine. Single point-in-time sample -- the
    note says so. Pure on its inputs; deterministic; never raises."""
    from collections import Counter
    mx = metrics or {}
    per_device: List[dict] = []
    findings: List[dict] = []

    def _find(host: str, kind: str, detail: str) -> None:
        label, sev, rec = _PLATHEALTH_DOCTRINE[kind]
        findings.append({"host": host, "kind": kind, "label": label, "severity": sev,
                         "detail": detail, "recommendation": rec})

    for host in sorted(mx):
        m = mx[host] or {}
        cpu = m.get("cpu") or {}
        mem = m.get("memory") or {}
        sysr = m.get("system") or {}
        collected = bool(cpu or mem or sysr)
        if not collected:
            per_device.append({"host": host, "collected": False, "cpu_5min": None,
                               "cpu_1min": None, "cpu_5sec": None, "cpu_source": "",
                               "mem_total_mb": None, "mem_free_pct": None, "mem_source": "",
                               "band": "Unknown",
                               "status": "Not collected — capacity commands absent from this collection."})
            continue

        # CPU: prefer the 5-min average; else the NX-OS instantaneous busy figure.
        cpu_5min = cpu.get("five_min")
        cpu_1min = cpu.get("one_min")
        cpu_5sec = cpu.get("five_sec")
        cpu_source = "show processes cpu (5-min avg)" if cpu else ""
        if cpu_5min is None and "cpu_idle" in sysr:
            cpu_5min = round(100 - sysr["cpu_idle"], 1)
            cpu_source = "show system resources (instantaneous)"

        # Memory: prefer the IOS processor pool; else NX-OS system memory.
        mem_total = mem.get("total")
        mem_free = mem.get("free")
        mem_source = "show processes memory (processor pool)" if mem else ""
        if mem_total is None and sysr.get("mem_total_kb"):
            mem_total = sysr["mem_total_kb"] * 1024
            mem_free = (sysr.get("mem_free_kb") or 0) * 1024
            mem_source = "show system resources (system memory)"
        mem_free_pct = (round(100 * mem_free / mem_total, 1)
                        if mem_total and mem_free is not None else None)
        mem_total_mb = round(mem_total / (1024 * 1024)) if mem_total else None

        band = "OK"
        cpu_instantaneous = cpu_source.endswith("(instantaneous)")
        if cpu_5min is not None:
            if cpu_instantaneous:
                # V3.23.170: an instantaneous figure must not be banded with the 5-minute
                # doctrine -- it can spike while the device renders show output. Cap at
                # Elevated with its own honest doctrine; never Hot off one instant.
                if cpu_5min >= _PLATHEALTH_CPU_ELEVATED:
                    band = "Elevated"
                    _find(host, "cpu-sample-high", f"CPU {cpu_5min}% ({cpu_source}).")
            elif cpu_5min >= _PLATHEALTH_CPU_HOT:
                band = "Hot"
                _find(host, "hot-cpu", f"CPU {cpu_5min}% ({cpu_source}).")
            elif cpu_5min >= _PLATHEALTH_CPU_ELEVATED:
                band = "Elevated"
                _find(host, "elevated-cpu", f"CPU {cpu_5min}% ({cpu_source}).")
        if mem_free_pct is not None:
            if mem_free_pct <= _PLATHEALTH_MEM_CRIT_PCT:
                band = "Hot"
                _find(host, "low-memory",
                      f"{mem_free_pct}% free of {mem_total_mb} MB ({mem_source}).")
            elif mem_free_pct <= _PLATHEALTH_MEM_LOW_PCT:
                if band == "OK":
                    band = "Elevated"
                _find(host, "memory-watch",
                      f"{mem_free_pct}% free of {mem_total_mb} MB ({mem_source}).")
        if cpu_5min is None and mem_free_pct is None:
            band = "Unknown"
        bits = []
        if cpu_5min is not None:
            bits.append(f"CPU {cpu_5min}%")
        if mem_free_pct is not None:
            bits.append(f"memory {mem_free_pct}% free")
        status = (" · ".join(bits) + f" — {band}.") if bits else \
            "Output collected but no capacity figures recognized."
        per_device.append({"host": host, "collected": True, "cpu_5min": cpu_5min,
                           "cpu_1min": cpu_1min, "cpu_5sec": cpu_5sec, "cpu_source": cpu_source,
                           "mem_total_mb": mem_total_mb, "mem_free_pct": mem_free_pct,
                           "mem_source": mem_source, "band": band, "status": status})

    findings.sort(key=lambda f: (_SEV_RANK.get(f["severity"], 9), f["host"], f["kind"]))
    per_device.sort(key=lambda d: (_PLATHEALTH_BAND_RANK.get(d["band"], 9), d["host"]))
    collected = [d for d in per_device if d["collected"]]
    not_collected = sorted(d["host"] for d in per_device if not d["collected"])
    summary = {"n_devices": len(per_device), "n_collected": len(collected),
               "n_not_collected": len(not_collected), "hosts_not_collected": not_collected[:20],
               "bands": dict(sorted(Counter(d["band"] for d in per_device).items())),
               "n_findings": len(findings),
               "by_kind": dict(sorted(Counter(f["kind"] for f in findings).items()))}
    note = ("Single point-in-time sample taken at collection — a snapshot, not a trend. "
            "Correlate with the syslog axis (CPUHOG / MALLOCFAIL events) and re-sample close "
            "to the migration window before treating a device as healthy.")
    return {"per_device": per_device, "findings": findings, "summary": summary, "note": note}


# =============================================================================
# Hardware lifecycle (EoL / End-of-Support) risk (NEW-V3.23.117). A new assessment AXIS: per-device
# replacement urgency from the offline `eoldb` knowledge base (a top REASON orgs migrate). Reference
# dates are copied from exact Cisco bulletin claims retained by the KB, never inferred from a generic
# support-window rule. Bands are relative to the assessment date. `Active` is retained as the public
# schema label for the pre-EoS date band; it is not a claim about service entitlement or an absence of
# an EoL announcement.
# =============================================================================
_LIFECYCLE_BAND_RANK = {"Past-LDoS": 0, "Near-LDoS": 1, "Past-EoS": 2, "Active": 3, "Unknown": 4}


def compute_lifecycle_risk(devices: Optional[dict] = None, asof: Optional[object] = None) -> dict:
    """NEW-V3.23.117: per-device hardware lifecycle (EoL/End-of-Support) risk from the offline eoldb KB,
    classified relative to `asof` (the assessment date; ISO 'YYYY-MM-DD' / date / datetime, default today).
    EoS/LDoS dates are bulletin-backed records (not device-read and never derived from a generic support
    window). Pure read; deterministic; tolerant of empty input. Returns {per_device, summary, risks, asof,
    note}."""
    from collections import Counter
    from datetime import date, datetime
    from cisco_toolkit import eoldb

    def _to_date(x):
        if isinstance(x, datetime):
            return x.date()
        if isinstance(x, date):
            return x
        try:
            return datetime.strptime(str(x or "")[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return date.today()
    today = _to_date(asof)

    def _d(s):
        try:
            return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None

    per_device: List[dict] = []
    for host in sorted(devices or {}):
        dv = devices[host] or {}
        model = str(dv.get("model") or "").strip()
        sw = str(dv.get("sw_version") or "").strip()
        rec = eoldb.lifecycle_for(model)
        if rec is None:
            per_device.append({"host": host, "model": model or "(unknown)", "platform": "", "sw_version": sw,
                               "eos": "", "ldos": "", "band": "Unknown", "years_to_ldos": None,
                               "status": "No retained Cisco EoX bulletin match for the collected model - "
                                         "support state undetermined; verify the exact PID on Cisco's EoX portal",
                               "source": "", "conf": "",
                               "matched_pattern": "", "match_kind": "none",
                               "reviewed_at": eoldb._EOL_REVIEWED, "citation_status": "missing"})
            continue
        eos, ldos = _d(rec.get("eos")), _d(rec.get("ldos"))
        # The eoldb contract admits only exact, bulletin-confirmed rows with both dates and a verified
        # retained-source chain. Enforce that authority at the consumer boundary: lifecycle_for()
        # deliberately returns the inline record with source_authoritative=False when the fixture is
        # missing, stale, or fails integrity, but those unverified dates must not drive a band. This also
        # prevents a future malformed/legacy row from turning a missing date into "no EoL announced".
        if rec.get("source_authoritative") is not True:
            band = "Unknown"
            status = (
                "Retained primary-source proof was not verified for the matched Cisco EoX row; "
                "lifecycle band withheld - verify the exact PID and repair the offline source chain"
            )
            yrs = None
        elif rec.get("conf") != "confirmed" or not eos or not ldos:
            band = "Unknown"
            status = (
                "Complete EoS/LDoS dates were not established by a bulletin-confirmed offline row; "
                "support state undetermined - verify the exact PID on Cisco's EoX portal"
            )
            yrs = None
        else:
            # Decide the band from the UNROUNDED delta; the rounded `yrs` is for DISPLAY only. Rounding first
            # let a device genuinely ~1.05 yr out round to 1.0 and fall into Near-LDoS (the band ~18 days too
            # wide). Past-LDoS keeps the STRICT `>` boundary: the recorded LDoS date itself is not
            # past; the Past-LDoS band begins on the following day. This date comparison makes no
            # claim about contract entitlement. test_lifecycle_boundary_drift_guard locks the rule.
            yrs_exact = ((ldos - today).days / 365.25) if ldos else None
            yrs = round(yrs_exact, 1) if yrs_exact is not None else None
            if ldos and today > ldos:
                band = "Past-LDoS"; status = f"Past end-of-support (LDoS {rec['ldos']}, {rec['conf']})"
            elif ldos and yrs_exact is not None and 0 <= yrs_exact <= 1.0:
                band = "Near-LDoS"; status = f"End-of-support within 1 year (LDoS {rec['ldos']}, {rec['conf']})"
            elif eos and today > eos:
                band = "Past-EoS"; status = f"Past end-of-sale (EoS {rec['eos']}; LDoS {rec['ldos']})"
            else:
                band = "Active"
                status = (
                    f"EoS not yet passed as of assessment (bulletin EoS {rec['eos']}; "
                    f"LDoS {rec['ldos']}); support entitlement not assessed"
                )
        # Withheld rows keep match/citation diagnostics, but not unverified dates. Publishing dates
        # beside band=Unknown would let Excel/explorer present authoritative-looking EoS/LDoS values
        # after this function had explicitly refused to classify from them.
        published_eos = rec["eos"] if band != "Unknown" else ""
        published_ldos = rec["ldos"] if band != "Unknown" else ""
        per_device.append({"host": host, "model": model, "platform": rec["platform"], "sw_version": sw,
                           "eos": published_eos, "ldos": published_ldos, "band": band, "years_to_ldos": yrs,
                           "status": status, "source": rec["source"], "conf": rec["conf"],
                           "matched_pattern": rec["matched_pattern"], "match_kind": rec["match_kind"],
                           "reviewed_at": rec["reviewed_at"], "citation_status": rec["citation_status"]})

    by_band = Counter(d["band"] for d in per_device)
    pcount: "Counter" = Counter(); pband: Dict[str, str] = {}; pldos: Dict[str, str] = {}
    for d in per_device:
        key = d["platform"] or "(unknown)"
        pcount[key] += 1
        if key not in pband or _LIFECYCLE_BAND_RANK[d["band"]] < _LIFECYCLE_BAND_RANK[pband[key]]:
            pband[key] = d["band"]; pldos[key] = d["ldos"]
    by_platform = sorted(({"platform": k, "count": pcount[k], "band": pband[k], "ldos": pldos.get(k, "")}
                          for k in pcount),
                         key=lambda r: (_LIFECYCLE_BAND_RANK[r["band"]], -r["count"], r["platform"]))

    risks: List[dict] = []
    for band, severity, title, remediation in (
        ("Past-LDoS", "Critical", "Hardware past Cisco end-of-support (no TAC / no fixes)",
         "Prioritize these in the migration / hardware refresh and verify each exact PID against Cisco EoX."),
        ("Near-LDoS", "High", "Hardware within 1 year of end-of-support",
         "Schedule replacement before LDoS and verify each exact PID against Cisco EoX."),
        ("Past-EoS", "Medium", "Hardware past end-of-sale with LDoS still future",
         "Plan refresh before the recorded LDoS; verify the exact PID and serial-numbered support "
         "entitlement separately because this date band does not establish it."),
    ):
        matching = [d for d in per_device if d["band"] == band]
        if not matching:
            continue
        # Non-confirmed or incomplete rows were already abstained above. Consequently every adverse
        # band here is based on dates copied from a retained bulletin claim; there is no "derived date"
        # population to downgrade or describe.
        devices_for_risk = sorted(d["host"] for d in matching)
        platforms = sorted({d["platform"] for d in matching})
        risks.append({
            "severity": severity,
            "devices": devices_for_risk,
            "title": title,
            "detail": (
                f"{len(devices_for_risk)} device(s) on {', '.join(platforms)}; "
                "lifecycle dates are bulletin-confirmed."
            ),
            "remediation": remediation,
            "evidence_confidence": "confirmed",
        })

    # The loop above enumerates the three adverse date bands, so a fleet whose platforms matched no EoX
    # bulletin produced `risks == []` -- and every downstream consumer (punch-list, workbook, explorer)
    # renders an empty risk list as "no lifecycle risk found". That is absence rendered as health: the
    # support state was never determined, which is not the same as determined-to-be-fine. Emitted after
    # the loop so it never outranks a real Past-LDoS/Near-LDoS/Past-EoS finding, and deliberately NOT Critical --
    # nothing observed says these are out of support, only that we cannot say they are in it.
    unknown_devices = [d for d in per_device if d["band"] == "Unknown"]
    if unknown_devices:
        _u_hosts = sorted(d["host"] for d in unknown_devices)
        # `platform` is empty for no-match rows but present for rows whose band was withheld because
        # the retained source chain failed. Fall back to the collected model only for the former, and
        # distinguish those two causes below so a provenance failure is never mislabeled as no match.
        _u_platforms = sorted({(d["platform"] or d["model"] or "").strip() for d in unknown_devices}
                              - {""})
        _u_where = (", ".join(_u_platforms) if _u_platforms
                    else "platforms whose model string was not collected")
        _u_unmatched = [d for d in unknown_devices if d.get("match_kind") == "none"]
        _u_withheld = [d for d in unknown_devices if d.get("match_kind") != "none"]
        _u_causes = []
        if _u_unmatched:
            _u_causes.append(
                f"{len(_u_unmatched)} had no retained exact Cisco EoX bulletin match"
            )
        if _u_withheld:
            _u_causes.append(
                f"{len(_u_withheld)} matched an offline row whose source authority or complete dates "
                "were not verified"
            )
        risks.append({
            "severity": "Medium",
            "devices": _u_hosts,
            "title": "Hardware lifecycle NOT ASSESSED (support state undetermined)",
            "detail": (
                f"No support band could be assigned to {len(_u_hosts)} device(s) on {_u_where}: "
                f"{'; '.join(_u_causes)}. Their "
                "end-of-support exposure is UNKNOWN, not nil — an empty lifecycle risk list would "
                "otherwise read as a clean fleet."
            ),
            "remediation": ("Resolve each exact PID against Cisco's published EoX data and re-run the "
                            "assessment; until then treat these devices as un-costed for refresh."),
            "evidence_confidence": "not-assessed",
        })

    summary = {"n_devices": len(per_device), "by_band": dict(by_band),
               "n_past_ldos": by_band.get("Past-LDoS", 0), "n_near": by_band.get("Near-LDoS", 0),
               "n_past_eos": by_band.get("Past-EoS", 0), "n_active": by_band.get("Active", 0),
               "n_unknown": by_band.get("Unknown", 0), "by_platform": by_platform, "asof": today.isoformat()}
    return {"per_device": per_device, "summary": summary, "risks": risks, "asof": today.isoformat(),
            "kb_reviewed_at": eoldb._EOL_REVIEWED,
            "note": "EoS and LDoS dates are copied from exact Cisco EoL bulletin claims retained in the "
                    "offline KB; no lifecycle date is derived from a generic support-window rule. A date-bearing "
                    "band is emitted only when the retained source chain verifies, then computed relative to the "
                    "assessment date. 'Active' is the schema label for a row whose recorded EoS has not passed "
                    "and whose LDoS is not within one year; it does not assert support entitlement or that Cisco "
                    "has announced no EoL. Verify exact PIDs on Cisco's End-of-Life portal."}


# =============================================================================
# Segmentation / isolation audit (NEW-V3.23.118). The mirror of the dependency graph: not what couples to
# what, but what is ISOLATED from what. Reads each gateway SVI's VRF + applied ACL and joins to the
# application-domain map -> is the on-air media fabric actually segmented, or is the L3 fabric flat (single
# global VRF, no gateway ACLs)? Pure read of already-collected SVI fields. Reports current posture only.
# =============================================================================
def compute_segmentation(all_interfaces: Dict[str, Dict[str, InterfaceData]],
                         application_intelligence: Optional[dict] = None) -> dict:
    """NEW-V3.23.118: L3 segmentation / isolation posture from the gateway SVIs (vrf + applied ACL) joined to
    the application-domain map. Pure read; deterministic; tolerant of empty input.
    Returns {vrfs, gateway_acl, domains, summary, risks}."""
    from collections import Counter, defaultdict

    def _global_vrf(v):
        raw = (v or "").strip()
        return "" if raw.lower() in ("", "default", "global") else raw   # "" = the global routing table

    gw: List[dict] = []
    for host, ports in (all_interfaces or {}).items():
        for port, d in (ports or {}).items():
            if not re.match(r"^Vlan(\d+)$", str(port), re.I):
                continue
            if not (getattr(d, "svi_ip", "") or "").strip():
                continue
            vrf = _global_vrf(getattr(d, "vrf", ""))
            has_acl = bool((getattr(d, "acl_in", "") or "").strip() or (getattr(d, "acl_out", "") or "").strip())
            gw.append({"host": host, "vrf": vrf, "has_acl": has_acl})

    n_gw = len(gw)
    n_acl = sum(1 for g in gw if g["has_acl"])
    vrf_counter = Counter((g["vrf"] or "(global)") for g in gw)
    vrfs = [{"vrf": k, "gateway_count": v} for k, v in sorted(vrf_counter.items(), key=lambda kv: (-kv[1], kv[0]))]
    distinct_real_vrfs = {g["vrf"] for g in gw if g["vrf"]}          # non-global VRFs
    flat = n_gw > 0 and not distinct_real_vrfs and n_acl == 0
    gateway_acl = {"n_gateways": n_gw, "n_with_acl": n_acl,
                   "coverage_pct": round(100.0 * n_acl / n_gw, 1) if n_gw else 0.0}

    gw_by_host: Dict[str, list] = defaultdict(list)
    for g in gw:
        gw_by_host[g["host"]].append(g)

    domains_out: List[dict] = []
    for dom in ((application_intelligence or {}).get("domains") or []):
        sws = set(dom.get("switches") or [])
        dgw = [g for h in sws for g in gw_by_host.get(h, [])]
        dvrfs = sorted({(g["vrf"] or "(global)") for g in dgw})
        dacl = sum(1 for g in dgw if g["has_acl"])
        # A domain is isolated only when EVERY gateway is protected (a dedicated VRF or a gateway ACL). The old
        # ANY test flipped the WHOLE domain to isolated when a SINGLE gateway had a VRF/ACL, masking sibling
        # gateways sitting in the global VRF with no ACL (reachable from every other domain at L3) -- so a real
        # on-air-critical exposure was dropped from exposed_oncrit and the executive Segmentation axis.
        n_protected = sum(1 for g in dgw if g["vrf"] or g["has_acl"])
        n_exposed = len(dgw) - n_protected
        isolated = bool(dgw) and n_exposed == 0
        if not dgw:
            exposure = "No L3 gateway on this domain's switches (L2-only, or its gateway lives elsewhere)."
        elif isolated:
            exposure = "Every gateway has a dedicated VRF or a gateway ACL."
        else:
            exposure = (f"{n_exposed} of {len(dgw)} gateway(s) share the global VRF with no ACL — "
                        "reachable from every other domain at L3.")
        domains_out.append({"domain": dom.get("domain"), "tier": dom.get("tier"), "gateways": len(dgw),
                            "vrfs": dvrfs, "gateways_with_acl": dacl, "isolated": isolated, "exposure": exposure})
    domains_out.sort(key=lambda d: (_APP_TIER_RANK.get(d["tier"], 9), -d["gateways"], d["domain"]))

    risks: List[dict] = []
    if flat:
        risks.append({"severity": "High", "devices": [],
            "title": "Flat L3 fabric — no VRF separation and no gateway ACLs",
            "detail": f"All {n_gw} gateway SVI(s) sit in the global routing table and 0 carry an ACL — there is "
                      "no L3 segmentation between application domains; any endpoint can reach any gateway.",
            "remediation": "Design segmentation into the target: place sensitive fabrics (on-air media, OT, "
                           "management) in dedicated VRFs and/or behind gateway ACLs / a firewall.", "standard": ""})
    else:
        if n_gw and n_acl == 0:
            risks.append({"severity": "Medium", "devices": [],
                "title": "No gateway ACLs — no L3/L4 enforcement at the SVI",
                "detail": f"0 of {n_gw} gateway SVI(s) apply an ACL; a compromised endpoint in any VLAN can reach "
                          "every gateway unfiltered.",
                "remediation": "Apply ingress ACLs on sensitive gateway SVIs.", "standard": ""})
        if n_gw and not distinct_real_vrfs:
            risks.append({"severity": "Medium", "devices": [],
                "title": "No VRF separation — single global routing table",
                "detail": f"All {n_gw} gateways share the global VRF.",
                "remediation": "Separate sensitive fabrics into dedicated VRFs in the target design.", "standard": ""})

    exposed_oncrit = [d["domain"] for d in domains_out
                      if d["tier"] == "On-air critical" and d["gateways"] and not d["isolated"]]
    if exposed_oncrit:
        risks.append({"severity": "High", "devices": [],
            "title": f"{len(exposed_oncrit)} on-air-critical domain(s) are not isolated",
            "detail": "These on-air domains share the global VRF with back-office and have no gateway ACL: "
                      + ", ".join(exposed_oncrit[:8]) + ". The media fabric is not segmented.",
            "remediation": "Isolate the media fabric (dedicated VRF + boundary ACL/firewall) in the target.",
            "standard": "SMPTE ST 2110 security guidance"})

    summary = {"n_vrfs": len(vrf_counter), "flat": flat, "gateway_acl_coverage": gateway_acl["coverage_pct"],
               "n_gateways": n_gw, "n_oncrit_exposed": len(exposed_oncrit),
               "global_only": n_gw > 0 and not distinct_real_vrfs}
    return {"vrfs": vrfs, "gateway_acl": gateway_acl, "domains": domains_out,
            "summary": summary, "risks": risks}


# =============================================================================
# Executive brief (NEW-V3.23.120). The cross-axis capstone: one headline per assessment axis rolled up into
# a single decision-grade synthesis (the seven new axes + health + punch-list + readiness). Pure read of each
# layer's already-computed summary; deterministic given inputs; the detail tabs remain the source of record.
# =============================================================================
def compute_executive_brief(health_scores: Optional[list] = None, punchlist: Optional[list] = None,
                            migration_readiness: Optional[list] = None,
                            application_intelligence: Optional[dict] = None,
                            lifecycle_risk: Optional[dict] = None, segmentation: Optional[dict] = None,
                            multicast_intelligence: Optional[dict] = None,
                            remediation_plan: Optional[dict] = None,
                            syslog_intelligence: Optional[dict] = None,
                            qos_audit: Optional[dict] = None,
                            software_risk: Optional[dict] = None,
                            platform_health: Optional[dict] = None,
                            device_dossiers: Optional[dict] = None,
                            endpoint_identity: Optional[list] = None) -> dict:
    """NEW-V3.23.120: cross-axis migration brief -- one headline per assessment axis rolled up into a single
    decision-grade synthesis. Pure read of each layer's already-computed summary; deterministic given inputs.
    V3.23.169: the operational-log / QoS / software-risk / platform-capacity axes joined the synthesis.
    Returns {scale, posture, axes, top_gating, posture_statement}."""
    hs = health_scores or []
    pl = punchlist or []
    mr = migration_readiness or []
    app = application_intelligence or {}
    asum = app.get("summary") or {}
    lc = (lifecycle_risk or {}).get("summary") or {}
    # compute_lifecycle_risk publishes an explicit NOT-ASSESSED risk row (evidence_confidence
    # 'not-assessed') for every device it could not band. Until now nothing in the repo read
    # `lifecycle_risk['risks']`, so that disclosure was inert -- an honesty record with no
    # consumer is not a disclosure. THIS is its consumer: it gates the EoL axis's severity below.
    lc_coverage_risks = [r for r in ((lifecycle_risk or {}).get("risks") or [])
                         if isinstance(r, dict) and r.get("evidence_confidence") == "not-assessed"]
    # A risk ROW is not a device. `len(lc_coverage_risks)` counts DISCLOSURES; the posture flag below
    # states a DEVICE count, and printing one where the other belongs is a number the run never
    # measured. Each row names the devices it covers, so the device population is the union of those
    # lists -- and when a row names none, the flag says what the number actually is instead of
    # borrowing the row count.
    lc_undetermined_hosts = sorted({str(h) for r in lc_coverage_risks
                                    for h in (r.get("devices") if isinstance(r.get("devices"),
                                                                             (list, tuple)) else [])})
    # The producer's own not-assessed SENTENCE (it names the platforms/models to resolve on Cisco's
    # EoX portal). Carried into the rendered EoL axis detail below so `lifecycle_risk["risks"]` has a
    # consumer that a READER reaches, not only a severity gate: a disclosure whose sole evidence is
    # that it exists in JSON is not a disclosure.
    lc_coverage_detail = next((str(r.get("detail") or "").strip()
                               for r in lc_coverage_risks if str(r.get("detail") or "").strip()), "")
    seg = (segmentation or {}).get("summary") or {}
    mi = (multicast_intelligence or {}).get("summary") or {}
    rem = (remediation_plan or {}).get("summary") or {}

    n = len(hs)
    bands: Dict[str, int] = {}
    for x in hs:
        bands[x.get("band", "")] = bands.get(x.get("band", ""), 0) + 1
    # honesty: average over only genuinely-scored, evidence-bearing rows — an 'Insufficient Data' device
    # (absent evidence -> no deductions -> a near-perfect score) must not inflate the fleet health headline.
    _scored = [x for x in hs if isinstance(x.get("score"), (int, float)) and x.get("band") != "Insufficient Data"]
    avg = round(sum(x["score"] for x in _scored) / len(_scored)) if _scored else 0
    n_crit = bands.get("Critical", 0)
    n_poor = bands.get("Poor", 0)
    worst = next((b for b in ("Critical", "Poor", "Fair", "Good", "Excellent") if bands.get(b)), "")
    # SSOT: n_endpoints is the canonical evidenced-endpoint total == len(endpoint_identity) (what ssot.reconcile
    # verifies and CANONICAL_FACTS documents). Use it directly when available; fall back to the per-domain
    # endpoint_count sum only when endpoint_identity was not supplied (older callers). The per-domain sum drops
    # any endpoint_identity row whose host is not an all_interfaces key, so deriving from it diverged from the
    # verifier on an off-pipeline snapshot and made reconcile/audit false-fire a spurious integrity violation.
    n_endpoints = (len(endpoint_identity) if isinstance(endpoint_identity, list)
                   else sum((d.get("endpoint_count") or 0) for d in (app.get("domains") or [])))
    sev_pl = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
    for it in pl:
        if it.get("severity") in sev_pl:
            sev_pl[it["severity"]] += 1
    not_ready = sum(1 for r in mr if r.get("readiness") == "NOT READY")
    lc_tot = lc.get("n_devices", 0)                               # EoL rollup -- shared by the axis + the posture flag
    lc_unknown = lc.get("n_unknown", 0)                           # no exact EoX match, or retained source/date authority withheld
    lc_known = lc_tot - lc_unknown                                # only KNOWN-model devices are EoL-assessable
    lc_support = lc.get("n_past_ldos", 0) + lc.get("n_near", 0)   # recorded LDoS passed, or falls within one year
    lc_eos = lc.get("n_past_eos", 0)                              # separate date band: LDoS remains future
    lc_pct = round(100 * lc_support / lc_known) if lc_known else 0 # % over ASSESSABLE devices, not diluted by unknowns (audit-3 #5)
    # COVERAGE, as a boolean, independent of what was found. `lc_unknown` counts devices whose
    # support state was never determined; `lc_coverage_risks` is the producer's own not-assessed
    # disclosure. Either one means this axis does not cover the whole fleet.
    lc_incomplete = bool(lc_unknown) or bool(lc_coverage_risks)

    axes: List[dict] = []

    def ax(axis, severity, headline, detail=""):
        axes.append({"axis": axis, "severity": severity, "headline": headline, "detail": detail})

    # 'assessed' is a COVERAGE claim -> count only the genuinely-scored rows (the same set the average is over),
    # and disclose the never-reached devices. Counting all n (incl. the 'Insufficient Data' uncollected rows) as
    # assessed beside an average that excludes them was a false coverage claim (audit-3 #6).
    _n_scored = len(_scored)
    _n_insuff = bands.get("Insufficient Data", 0)
    ax("Fleet health", "Critical" if n_crit else "High" if n_poor else "Low",
       f"{avg}/100 avg · {n_crit} Critical, {n_poor} Poor band",
       f"{_n_scored} switch(es) assessed" + (f"; {_n_insuff} not collected (no evidence)." if _n_insuff else "."))
    ax("Migration punch-list",
       "Critical" if sev_pl["Critical"] else "High" if sev_pl["High"] else "Medium" if pl else "Low",
       f"{len(pl)} item(s) · {sev_pl['Critical']} Critical, {sev_pl['High']} High",
       "Consolidated fix-this-first action list.")
    if asum:
        ax("Application domains", "High" if asum.get("n_high_risk") else "Low",
           f"{asum.get('n_domains', 0)} domain(s) · {asum.get('n_on_air_critical', 0)} on-air-critical · "
           f"keystone {asum.get('keystone_domain', '')}", f"{asum.get('n_edges', 0)} inter-domain coupling(s).")
        ax("Cutover sequence", "Medium" if not_ready else "Low",
           f"pilot {asum.get('pilot_domain', '')} → last {asum.get('last_domain', '')}"
           # 'move-group(s)', not 'wave(s)': len(mr) is the migration_readiness/move-group count (the 53),
           # a distinct unit from the sequenced wave_plan waves (the 9) -- keep 'wave' reserved for those.
           + (f" · {not_ready} of {len(mr)} move-group(s) NOT READY" if mr else ""),
           "Recommended lowest-risk-first order.")
    if lc.get("n_devices"):
        ax("Hardware lifecycle (EoL)",
           # `Low` is the CLEAN-FLEET value and it must require COMPLETE coverage, not merely one
           # bandable device. The old test was `Info if not lc_known else Low`, i.e. the green value
           # returned the instant a SINGLE device became assessable: measured, 2 Active / 8 Unknown
           # scored "Low" -- the same machine-readable severity as a fully-verified fleet, feeding
           # the axis colour, the _APP_SEV_RANK sort and top_gating. Absence of a finding across 80%
           # of the fleet is not a finding of absence. A REAL adverse finding still leads (Critical /
           # High outrank Info), so this only bites the case where nothing adverse was found and the
           # reason may simply be that nothing was looked at.
           "Critical" if lc.get("n_past_ldos") else "High" if lc.get("n_near")
           else "Medium" if lc_eos
           else "Info" if (lc_incomplete or not lc_known) else "Low",
           f"{lc.get('n_past_ldos', 0)} past end-of-support, {lc.get('n_near', 0)} within 1yr "
           f"({lc_pct}% of {lc_known} assessable)"
           + (f" · {lc_eos} past end-of-sale (LDoS still future)" if lc_eos else "")
           + (f" · {lc_unknown} NOT ASSESSED (no authoritative lifecycle band)" if lc_unknown else ""),
           f"Date-bearing bands use only exact Cisco bulletin claims whose retained source chain verified; "
           f"no EoS/LDoS date is derived from a generic support-window rule. Bands are time-relative, "
           f"computed as-of {lc.get('asof') or 'the analysis date'} (they shift as time passes). Re-verify "
           f"the exact PID on Cisco's EoX portal before acting. Past-EoS is a recorded date position; "
           f"contract entitlement is not inferred."
           # The NOT-ASSESSED row's own sentence, verbatim, on a RENDERED surface (this detail reaches
           # the workbook / deck / explorer / brief). It names the model strings that failed to match,
           # which is the actionable half of the disclosure and was previously visible only to a
           # reader of the raw snapshot JSON.
           + (f" NOT ASSESSED — {lc_coverage_detail}" if lc_coverage_detail else ""))
    if seg.get("n_gateways"):
        ax("Segmentation", "High" if seg.get("flat") or seg.get("n_oncrit_exposed") else "Low",
           ("flat L3 — " if seg.get("flat") else "")
           + f"{seg.get('n_oncrit_exposed', 0)} on-air-critical domain(s) not isolated · gateway-ACL "
           f"{seg.get('gateway_acl_coverage', 0)}%", "Current L3 isolation posture.")
    if mi.get("n_groups"):
        # querier coverage is BLIND when on-air AV multicast is known present yet NO multicast SVI was collected
        # (the gap signal derives from collected SVIs only) -> report Info / not-assessable, never '0 gaps / Low'
        # by silence -- so a blind media core doesn't read like a verified-clean one (audit-3 #12).
        _q_blind = mi.get("n_av_groups", 0) > 0 and not mi.get("n_mcast_vlans", 0)
        # The SAME curated-vs-measured disclosure the multicast MAC-overlap risk row already carries
        # (compute_multicast_intelligence: `has_av_authoritative` / evidence_confidence). `n_av_groups`
        # counts groups whose on-air label comes from the curated overlay; on the shipped pack NONE of
        # them rest on an authoritative registry source, so a bare "44 broadcast/AV group(s)" states a
        # judgement in the voice of a measurement. `n_av_groups_authoritative` is absent from
        # pre-feature snapshots -- that is "not recorded", never "0 authoritative", so it abstains
        # rather than asserting a number it does not have.
        _n_av = mi.get("n_av_groups", 0)
        _n_av_auth = mi.get("n_av_groups_authoritative")
        if not _n_av:
            _av_detail = f"{_n_av} broadcast/AV group(s)."
        elif not isinstance(_n_av_auth, int):
            _av_detail = (f"{_n_av} broadcast/AV group(s) — the basis of that on-air classification is "
                          "not recorded in this snapshot; treat it as curated, not measured.")
        else:
            _av_detail = (f"{_n_av} broadcast/AV group(s) — {_n_av_auth} classified on-air by an "
                          f"authoritative registry source, {max(0, _n_av - _n_av_auth)} by this repo's "
                          "curated overlay only (a judgement, not a measurement).")
        ax("Multicast / timing",
           "High" if mi.get("n_mac_clashes") or mi.get("n_querier_gaps")
           else "Medium" if mi.get("n_ptp_dormant")
           else "Info" if _q_blind else "Low",
           f"{mi.get('n_mac_clashes', 0)} MAC clash(es) · {mi.get('n_ptp_dormant', 0)}/"
           f"{mi.get('n_ptp_clocks', 0)} PTP dormant · "
           + ("querier coverage not assessable (no multicast SVI collected)" if _q_blind
              else f"{mi.get('n_querier_gaps', 0)} querier gap(s)"),
           _av_detail)
    if rem.get("n_items"):
        ax("Remediation", "Info",
           f"{rem.get('n_items', 0)} review-ready config snippet(s) across {rem.get('n_devices', 0)} device(s)",
           "Generated for review (validate before applying).")

    # NEW-V3.23.169: the four V3.23.164-.167 axes reach the brief. Severity = the axis's own worst
    # finding; an axis whose evidence was not collected reports Info honestly, never Low-by-silence.
    def _worst(findings):
        sevs = {f.get("severity") for f in (findings or []) if isinstance(f, dict)}
        return ("High" if "High" in sevs else "Medium" if "Medium" in sevs
                else "Low" if sevs else None)

    si_s = (syslog_intelligence or {}).get("summary") or {}
    if si_s.get("n_devices"):
        if si_s.get("n_collected"):
            w = _worst((syslog_intelligence or {}).get("detections")) or "Low"
            ax("Operational logs", w,
               f"{si_s.get('n_detections', 0)} detection(s) · {si_s.get('crit_0_2', 0)} critical "
               f"event(s) on {si_s.get('n_collected', 0)} device(s)",
               "From the fleet's own buffered logs (bounded window — counts are floors).")
        else:
            ax("Operational logs", "Info", "log evidence not collected",
               "Absence of logs is not scored as absence of problems.")
    qa_s = (qos_audit or {}).get("summary") or {}
    if qa_s.get("n_devices"):
        if qa_s.get("n_assessable"):
            w = _worst((qos_audit or {}).get("findings")) or "Low"
            ax("QoS posture", w,
               f"{qa_s.get('n_findings', 0)} finding(s) · "
               + (", ".join(f"{v}× {k}" for k, v in (qa_s.get('modes') or {}).items()) or "—"),
               "Configured posture from the captured running-configs (not live queue state).")
        else:
            ax("QoS posture", "Info", "not assessable — no full running-config captures", "")
    sr_s = (software_risk or {}).get("summary") or {}
    if sr_s.get("n_devices"):
        # V3.23.170: the same not-assessable honesty gate the sibling axes carry -- with no
        # config captures AND no versions there is no evidence in EITHER layer, and 'Low'
        # would be the Low-by-silence this fold exists to prevent.
        if not (sr_s.get("n_config_assessable") or sr_s.get("n_version_known")):
            ax("Software risk", "Info",
               "not assessable — no running-configs or software versions captured",
               "Absence of evidence is declared, never scored.")
        else:
            w = _worst((software_risk or {}).get("findings"))
            tb = sr_s.get("train_bands") or {}
            lifecycle_pressure = tb.get("Replace/Upgrade") or tb.get("Verify EoL")
            sev = w or ("Medium" if lifecycle_pressure else "Low")
            ax("Software risk", sev,
               f"{sr_s.get('n_findings', 0)} exposed advisory surface(s) · trains "
               + (", ".join(f"{v}× {k}" for k, v in tb.items()) or "—"),
               "Screening, not a scan — validate releases with the Cisco PSIRT Software Checker.")
    ph_s = (platform_health or {}).get("summary") or {}
    if ph_s.get("n_devices"):
        if ph_s.get("n_collected"):
            w = _worst((platform_health or {}).get("findings")) or "Low"
            ax("Platform capacity", w,
               f"{ph_s.get('n_findings', 0)} finding(s) · "
               + (", ".join(f"{v}× {k}" for k, v in (ph_s.get('bands') or {}).items()) or "—"),
               "Single point-in-time control-plane sample; re-check before the window.")
        else:
            ax("Platform capacity", "Info", "capacity output not collected", "")

    # NEW-V3.23.172: the Device Risk Register reaches the brief -- worst-asset framing
    # ("a network is only as strong as its weakest link"), not an average.
    dd_s = (device_dossiers or {}).get("summary") or {}
    if dd_s.get("n_devices"):
        dd_b = dd_s.get("bands") or {}
        n_sevr, n_elev = dd_b.get("Severe", 0), dd_b.get("Elevated", 0)
        ax("Asset risk register",
           "Critical" if n_sevr else "High" if n_elev else "Low",
           f"{n_sevr} Severe, {n_elev} Elevated of {dd_s.get('n_devices', 0)} asset(s)"
           + (" · worst: " + ", ".join(dd_s.get("worst") or []) if dd_s.get("worst") else ""),
           f"{dd_s.get('n_compound', 0)} compound pattern(s) — independent risks stacked per asset "
           "× topology impact.")

    axes.sort(key=lambda a: _APP_SEV_RANK.get(a["severity"], 9))
    top_gating = [a["headline"] for a in axes if a["severity"] in ("Critical", "High")]

    flags: List[str] = []
    if lc.get("n_past_ldos") or lc.get("n_near"):
        flags.append(f"hardware end-of-support is a primary driver ({lc_pct}% past/near)")
    # Coverage rides with its own topic and is INDEPENDENT of the flag above: the two are
    # orthogonal facts. Without it, an 89%-unassessed fleet produced the fallback sentence "no
    # top-tier blockers flagged across the assessed axes - proceed with the standard wave plan",
    # which is the whole posture headline of every deliverable. Placed second so the [:4] cut below
    # can never drop it while a real end-of-support finding leads.
    if lc_incomplete:
        # DEVICES, never risk rows: `lc_unknown` is a device count and `lc_undetermined_hosts` is the
        # union of the hosts the not-assessed rows name. If neither is available the sentence states
        # the quantity it DOES have (disclosures) and labels it as such, rather than presenting a
        # row count as a device count.
        _n_undet = lc_unknown or len(lc_undetermined_hosts)
        flags.append(f"hardware support state is UNDETERMINED on {_n_undet} device(s) — not assessed, "
                     "not clear" if _n_undet else
                     f"hardware support state is UNDETERMINED — {len(lc_coverage_risks)} not-assessed "
                     "lifecycle disclosure(s) name no device count — not assessed, not clear")
    if seg.get("flat"):
        flags.append("the L3 fabric is flat (no segmentation)")
    if mi.get("n_ptp_clocks") and mi.get("n_ptp_dormant") == mi.get("n_ptp_clocks"):
        flags.append("media timing is not boundary-clocked")
    if mi.get("n_mac_clashes"):
        flags.append("a multicast MAC-address clash is present")
    if not_ready:
        # 'move-group(s)', not 'wave(s)': not_ready counts migration_readiness rows (the 53 move-groups),
        # not the sequenced wave_plan waves (the 9). Matches the Cutover-sequence axis headline above.
        flags.append(f"{not_ready} move-group(s) are NOT READY")
    if n_crit:
        flags.append(f"{n_crit} switch(es) are in Critical health")
    # The [:4] cut is a DISPLAY cap, and an undisclosed display cap reads as the complete list --
    # this sentence is the posture headline of every deliverable and states no flag total anywhere
    # else. Say how many were held back.
    _flag_cut = max(0, len(flags) - 4)
    posture_statement = ("Migration posture: " + "; ".join(flags[:4])
                         + (f"; +{_flag_cut} further flag(s) not shown here (see the axis table)"
                            if _flag_cut else "")
                         + ". Address these in the target design and sequence before cutover." if flags
                         else "Migration posture: no top-tier blockers flagged across the assessed axes — "
                              "proceed with the standard wave plan.")

    return {"scale": {"n_devices": n, "n_domains": asum.get("n_domains", 0), "n_endpoints": n_endpoints},
            "posture": {"avg_health": avg, "n_critical": n_crit, "n_poor": n_poor, "worst_band": worst},
            "axes": axes, "top_gating": top_gating, "posture_statement": posture_statement}


# =============================================================================
# NEW-V3.23.172: the per-ASSET synthesis -- the Device Risk Register. Every axis
# above slices the fleet by TOPIC (one sheet per concern); a senior engineer's
# daily question slices it by ASSET: "tell me everything about this one box,
# and which boxes scare you most when the independent risks are stacked."
# Model (mirrors Cisco Cyber Vision's asset risk = likelihood x impact, and CX
# Cloud's asset-360 view): risk_index = IMPACT (topology blast radius + roles)
# x EXPOSURE (count/severity of independently red assessment axes). Compound
# patterns (CR-01..CR-06) name the coincidences that multiply concern -- the
# signature senior-engineer read. Pure synthesis of already-computed records;
# no new collection; an axis without evidence is 'not assessed', never red.
# =============================================================================
_DOSSIER_BANDS = ("Severe", "Elevated", "Guarded", "Low", "Unassessed")
_DOSSIER_BAND_RANK = {b: i for i, b in enumerate(_DOSSIER_BANDS)}
# risk_index thresholds (impact 1-10 x exposure 0-10 -> 0-100)
_DOSSIER_SEVERE, _DOSSIER_ELEVATED, _DOSSIER_GUARDED = 50, 25, 10


def compute_device_dossiers(health_scores: Optional[list] = None,
                            failure_impact: Optional[list] = None,
                            lifecycle_risk: Optional[dict] = None,
                            software_risk: Optional[dict] = None,
                            platform_health: Optional[dict] = None,
                            syslog_intelligence: Optional[dict] = None,
                            qos_audit: Optional[dict] = None,
                            golden_drift: Optional[dict] = None,
                            security: Optional[Dict[str, dict]] = None,
                            config_hygiene: Optional[Dict[str, dict]] = None,
                            stp_roots: Optional[Dict[str, dict]] = None,
                            vpc: Optional[Dict[str, dict]] = None,
                            physical_health: Optional[list] = None,
                            protocol_health: Optional[list] = None,
                            move_groups: Optional[list] = None) -> dict:
    """NEW-V3.23.172: per-device 360-degree dossier + compound-risk ranking.
    Joins the 11 per-device-capable axes (health / hardware EoL / software risk /
    control-plane capacity / operational logs / CIS posture / config hygiene /
    golden drift / QoS / physical / protocol) per asset, multiplies the stacked
    exposure by the asset's topology impact (failure_impact blast radius + STP
    root / gateway roles), and emits named compound patterns where independent
    risks coincide on one box. Deterministic; tolerant of empty/oddly-typed
    input; absence of evidence is state 'na' (not assessed) and NEVER counts
    toward exposure. Returns {per_device, summary, note}."""
    hs_by = {r.get("switch"): r for r in (health_scores or []) if isinstance(r, dict)}
    fi_by = {r.get("host"): r for r in (failure_impact or []) if isinstance(r, dict)}
    lc_by = {r.get("host"): r for r in ((lifecycle_risk or {}).get("per_device") or [])
             if isinstance(r, dict)}
    sw = software_risk or {}
    sw_by = {r.get("host"): r for r in (sw.get("per_device") or []) if isinstance(r, dict)}
    sw_find: Dict[str, list] = {}
    for f in (sw.get("findings") or []):
        if isinstance(f, dict):
            sw_find.setdefault(f.get("host", ""), []).append(f)
    ph_by = {r.get("host"): r for r in ((platform_health or {}).get("per_device") or [])
             if isinstance(r, dict)}
    si = syslog_intelligence or {}
    si_by = {r.get("host"): r for r in (si.get("per_device") or []) if isinstance(r, dict)}
    si_det: Dict[str, list] = {}
    for d in (si.get("detections") or []):
        if isinstance(d, dict):
            si_det.setdefault(d.get("host", ""), []).append(d)
    qa = qos_audit or {}
    qa_by = {r.get("host"): r for r in (qa.get("per_device") or []) if isinstance(r, dict)}
    qa_find: Dict[str, list] = {}
    for f in (qa.get("findings") or []):
        if isinstance(f, dict):
            qa_find.setdefault(f.get("host", ""), []).append(f)
    gd_by = {r.get("host"): r for r in ((golden_drift or {}).get("per_device") or [])
             if isinstance(r, dict)}
    # When fewer than 3 comparable configs exist (majority mode), compute_golden_drift derives NO baseline
    # (summary.n_baseline == 0) yet still emits per_device rows with n_missing 0 / compliance 100. Those must
    # read 'na -- no baseline', not 'ok / matches the config baseline' (asserting conformance to a baseline
    # that was never derived = false-health).
    _gd_has_baseline = bool((((golden_drift or {}).get("summary")) or {}).get("n_baseline"))
    sec = security or {}
    hyg = config_hygiene or {}
    roots = stp_roots or {}
    vpc = vpc or {}
    phy_by: Dict[str, list] = {}
    for r in (physical_health or []):
        if isinstance(r, dict):
            phy_by.setdefault(r.get("switch", ""), []).append(r)
    proto_by: Dict[str, list] = {}
    for r in (protocol_health or []):
        if isinstance(r, dict):
            proto_by.setdefault(r.get("switch", ""), []).append(r)
    wave_of: Dict[str, str] = {}
    for g in (move_groups or []):
        if isinstance(g, dict):
            for h in (g.get("switches") or []):
                wave_of.setdefault(h, g.get("group", ""))

    hosts = sorted({h for h in (set(hs_by) | set(fi_by) | set(lc_by) | set(sw_by)
                                | set(ph_by) | set(si_by) | set(qa_by) | set(gd_by)
                                | set(sec) | set(hyg)) if h})
    per_device: List[dict] = []
    for host in hosts:
        exposures: List[dict] = []

        def ax(axis: str, state: str, label: str) -> None:
            exposures.append({"axis": axis, "state": state, "label": label})

        # -- the 11 exposure axes (state: risk / watch / ok / na) ------------
        hsr = hs_by.get(host)
        band = (hsr or {}).get("band", "")
        if hsr is None:
            ax("Health", "na", "not scored")
        elif band == "Insufficient Data":
            ax("Health", "na", "not scored — collection gap")
        elif band == "Critical":
            ax("Health", "risk", f"health Critical ({hsr.get('score', '')}/100)")
        elif band == "Poor":
            ax("Health", "watch", f"health Poor ({hsr.get('score', '')}/100)")
        else:
            ax("Health", "ok", f"health {band or '—'} ({hsr.get('score', '')}/100)")

        lcr = lc_by.get(host)
        lcb = (lcr or {}).get("band", "Unknown")
        if lcr is None:
            ax("Hardware EoL", "na", "not lifecycle-assessed — no lifecycle row was produced")
        elif lcb == "Unknown":
            ax("Hardware EoL", "na", "no authoritative lifecycle band — either no exact EoX row "
               "matched or the matched row's source/date authority was withheld")
        elif lcb in ("Past-LDoS", "Near-LDoS"):
            ax("Hardware EoL", "risk", f"hardware {lcb.replace('-', ' ')}")
        elif lcb == "Past-EoS":
            ax("Hardware EoL", "watch", "hardware past end-of-sale")
        elif lcb == "Active":
            ax("Hardware EoL", "ok", "pre-EoS date position (schema: Active; support entitlement "
               "not assessed)")
        else:
            ax("Hardware EoL", "na", f"unrecognized lifecycle band {lcb!r} — not assessed")

        swr = sw_by.get(host)
        sw_sevs = {f.get("severity") for f in sw_find.get(host, [])}
        swb = (swr or {}).get("train_band", "Unknown")
        if swr is None or (not swr.get("config_assessable")
                           and str(swr.get("sw_version", "")).startswith("(not")):
            ax("Software risk", "na", "not assessable — no config or version evidence")
        elif "High" in sw_sevs or swb == "Replace/Upgrade":
            ax("Software risk", "risk",
               "open advisory surface" if "High" in sw_sevs else "software train end-of-era")
        elif sw_sevs or swb == "Verify EoL":
            ax("Software risk", "watch", "advisory surface to validate (PSIRT checker)")
        elif not swr.get("config_assessable"):
            # The advisory-SURFACE layer (http-server / SNMP v1-v2c / Smart Install / telnet / SSHv1 /
            # IKEv1 / small services) is screened from the running-config ALONE, and compute_software_risk
            # declares this device not assessable for it (`config_assessable` False, `surfaces` {}). The
            # na-guard above only fires when the VERSION layer is missing TOO, so a device with a known
            # version but no captured config fell through to "no exposed advisory surface flagged" -- an
            # affirmative clean bill for a screen that never ran, printed beside this same device's
            # 'Security posture: na - no captured running-config'. Absence of the config is a coverage
            # gap, not an absence of exposed surface.
            ax("Software risk", "na",
               "advisory surface not screened — no captured running-config"
               + (f" (software train {swb})" if swb and swb != "Unknown" else ""))
        else:
            ax("Software risk", "ok", "no exposed advisory surface flagged")

        phr = ph_by.get(host)
        phb = (phr or {}).get("band", "Unknown")
        # the band can come from MEMORY alone (low free %) with no CPU sample -- the label
        # cites every figure that exists, never "CPU None%" and never CPU-only when memory
        # drove the band.
        _cpu5 = (phr or {}).get("cpu_5min")
        _memf = (phr or {}).get("mem_free_pct")
        ph_parts = ([f"CPU {_cpu5}%"] if _cpu5 is not None else []) \
            + ([f"memory {_memf}% free"] if _memf is not None else [])
        ph_why = " · ".join(ph_parts) or "see sample"
        if phr is None or not phr.get("collected"):
            ax("Control plane", "na", "capacity output not collected")
        elif phb == "Hot":
            ax("Control plane", "risk", f"control plane Hot ({ph_why})")
        elif phb == "Elevated":
            ax("Control plane", "watch", f"control plane Elevated ({ph_why})")
        else:
            ax("Control plane", "ok", "control-plane capacity OK")

        sir = si_by.get(host)
        si_sevs = {d.get("severity") for d in si_det.get(host, [])}
        if sir is None or not sir.get("collected"):
            ax("Operational logs", "na", "log evidence not collected")
        elif "High" in si_sevs:
            ax("Operational logs", "risk", "high-severity operational events in the device's own logs")
        elif "Medium" in si_sevs:
            ax("Operational logs", "watch", "operational events to review in the logs")
        else:
            ax("Operational logs", "ok", "no flagged operational events")

        s = sec.get(host)
        fails = [f for f in ((s or {}).get("findings") or [])
                 if isinstance(f, dict) and f.get("status") == "fail"]
        if s is None:
            ax("Security posture", "na", "no captured running-config")
        elif any(str(f.get("severity", "")).lower() == "high" for f in fails):
            ax("Security posture", "risk", f"{len(fails)} CIS check(s) failing (incl. high)")
        elif fails:
            ax("Security posture", "watch", f"{len(fails)} CIS check(s) failing")
        else:
            ax("Security posture", "ok", "CIS checks pass")

        hg = hyg.get(host)
        n_undef = len((hg or {}).get("undefined") or [])
        if hg is None:
            ax("Config hygiene", "na", "no captured running-config")
        elif n_undef >= 5:
            ax("Config hygiene", "risk", f"{n_undef} undefined reference(s)")
        elif n_undef:
            ax("Config hygiene", "watch", f"{n_undef} undefined reference(s)")
        else:
            ax("Config hygiene", "ok", "no dangling references")

        gdr = gd_by.get(host)
        if gdr is None:
            ax("Golden drift", "na", "not in the drift baseline")
        elif not _gd_has_baseline:
            ax("Golden drift", "na", "no config baseline derived (need 3+ comparable configs)")
        elif _as_num(gdr.get("n_missing")) >= 5 or _as_num(gdr.get("compliance_pct"), 100) < 70:
            ax("Golden drift", "risk",
               f"{gdr.get('n_missing', 0)} required directive(s) missing "
               f"({gdr.get('compliance_pct', 0)}% compliant)")
        elif gdr.get("n_missing", 0):
            ax("Golden drift", "watch", f"{gdr.get('n_missing', 0)} required directive(s) missing")
        else:
            ax("Golden drift", "ok", "matches the config baseline")

        qar = qa_by.get(host)
        qa_sevs = {f.get("severity") for f in qa_find.get(host, [])}
        if qar is None or not qar.get("assessable"):
            ax("QoS posture", "na", "not assessable — full running-config not captured")
        elif qa_sevs & {"High", "Medium"}:
            # QoS doctrine gaps gate the DESIGN, not the asset's survival -> capped at watch.
            ax("QoS posture", "watch", "QoS doctrine finding(s) on this device")
        elif qa_sevs:
            ax("QoS posture", "ok", "minor QoS notes only")
        else:
            ax("QoS posture", "ok", "QoS posture consistent")

        # physical/protocol findings derive from the interface scan -- a host the scorer never
        # saw (in the roster only via EoL / software / log evidence) is 'na', not silently clean.
        # `hsr is not None` alone was INERT for the case it targets: a host banded 'Insufficient
        # Data' still HAS a health-score row, so it read scanned=True and rendered "ok - no L1
        # findings" / "protocol health clean" right beside its own "Health: na - collection gap"
        # (#16). Only a genuinely scored host licenses an 'ok' by silence; a host that produced
        # actual physical/protocol rows still does so through the `host in *_by` arm below.
        scanned = hsr is not None and band != "Insufficient Data"
        phys = [r for r in phy_by.get(host, [])
                if r.get("severity") not in (None, "", "Info", "OK")]
        hard_phy = [r for r in phys
                    if any(k in (r.get("risk") or "") for k in ("err-disabled", "error-rate-high"))]
        if hard_phy:
            ax("Physical", "risk", f"{len(hard_phy)} port(s) err-disabled / high error rate")
        elif phys:
            ax("Physical", "watch", f"{len(phys)} port(s) with L1 findings")
        elif scanned or host in phy_by:
            ax("Physical", "ok", "no L1 findings")
        else:
            ax("Physical", "na", "device not interface-scanned / collection gap")

        protos = proto_by.get(host, [])
        p_sevs = {r.get("severity") for r in protos}
        if "High" in p_sevs:
            ax("Protocol", "risk", "high-severity protocol-health finding")
        elif "Medium" in p_sevs:
            ax("Protocol", "watch", "protocol-health finding(s) to review")
        elif scanned or host in proto_by:
            ax("Protocol", "ok", "protocol health clean")
        else:
            ax("Protocol", "na", "device not interface-scanned / collection gap")

        n_risk = sum(1 for e in exposures if e["state"] == "risk")
        n_watch = sum(1 for e in exposures if e["state"] == "watch")
        n_na = sum(1 for e in exposures if e["state"] == "na")
        exposure_score = min(10, 2 * n_risk + n_watch)

        # -- impact: topology blast radius + control-plane roles -------------
        fir = fi_by.get(host)
        fi_sev = (fir or {}).get("severity", "")
        stranded = _as_num((fir or {}).get("stranded"))
        vlans_imp = _as_num((fir or {}).get("vlans_impacted"))
        impact = {"High": 8, "Medium": 5, "Low": 3}.get(fi_sev, 1)
        if stranded >= 200:
            impact += 2
        elif stranded >= 50:
            impact += 1
        root_vlans = sum(1 for v in (roots.get(host) or {}).values()
                         if isinstance(v, dict) and v.get("is_root"))
        if root_vlans:
            impact += 1                       # STP control-plane keystone
        if (hs_by.get(host) or {}).get("role") == "distribution":
            impact += 1                       # gateway-carrying asset
        impact = max(1, min(10, impact))

        risk_index = impact * exposure_score

        # -- compound patterns: independent risks coinciding on one asset ----
        state = {e["axis"]: e["state"] for e in exposures}
        compound: List[dict] = []

        def cr(code: str, title: str, severity: str, basis: str) -> None:
            compound.append({"code": code, "title": title, "severity": severity, "basis": basis})

        impact_phrase = (f"removal strands {stranded} endpoint(s) across {vlans_imp} VLAN(s)"
                         if stranded else f"removal impacts {vlans_imp} VLAN(s)" if vlans_imp
                         else "no modeled reachability impact")
        if lcb == "Past-LDoS" and fi_sev == "High":
            cr("CR-01", "End-of-support keystone", "Critical",
               f"Hardware is past last-day-of-support AND {impact_phrase} — "
               "an unsupportable box the network cannot lose.")
        elif lcb == "Near-LDoS" and fi_sev == "High":
            cr("CR-01", "Near-LDoS keystone", "High",
               f"Hardware reaches LDoS within one year AND {impact_phrase} — the replacement window "
               "is finite; support entitlement is not inferred from the date band.")
        if lcb == "Past-LDoS" and state.get("Health") == "risk":
            cr("CR-02", "Failing hardware past support", "High",
               "Critical health score on hardware that is past last-day-of-support — "
               "no standard TAC escalation path when it degrades further.")
        elif lcb == "Near-LDoS" and state.get("Health") == "risk":
            cr("CR-02", "Critical health near LDoS", "High",
               "Critical health score on hardware within one year of LDoS — stabilize it and schedule "
               "replacement before the deadline; support entitlement is not inferred from the date band.")
        if root_vlans and (state.get("Health") == "risk" or state.get("Physical") == "risk"):
            cr("CR-03", "Root bridge on degraded hardware", "High",
               f"STP root for {root_vlans} VLAN(s) on a device with "
               f"{'Critical health' if state.get('Health') == 'risk' else 'hard L1 findings'} — "
               "a root failure reconverges every VLAN it anchors.")
        if state.get("Software risk") == "risk" and fi_sev in ("High", "Medium"):
            cr("CR-04", "Open advisory surface on a high-impact asset", "High",
               f"Config-evidenced advisory surface is open AND {impact_phrase} — "
               "validate with the Cisco PSIRT Software Checker before the window.")
        if state.get("Control plane") == "risk" and fi_sev == "High":
            cr("CR-05", "Stressed control plane at a single point of failure", "High",
               f"Control plane is already Hot AND {impact_phrase} — "
               "migration protocol churn lands on a box with no headroom.")
        cfg_red = sum(1 for a in ("Security posture", "Config hygiene", "Golden drift")
                      if state.get(a) in ("risk", "watch"))
        if cfg_red >= 2 and fi_sev == "High":
            cr("CR-06", "Layered config debt on a critical asset", "Medium",
               f"{cfg_red} config-truth axes are off-baseline AND {impact_phrase} — "
               "drift on the box you can least afford to misjudge.")

        # banding: index thresholds, FLOORED by the worst compound pattern -- a Critical
        # coincidence IS the multiplied concern, whatever the arithmetic says.
        risk_band = ("Severe" if risk_index >= _DOSSIER_SEVERE
                     else "Elevated" if risk_index >= _DOSSIER_ELEVATED
                     else "Guarded" if risk_index >= _DOSSIER_GUARDED else "Low")
        comp_sevs = {c["severity"] for c in compound}
        if "Critical" in comp_sevs:
            risk_band = "Severe"
        elif "High" in comp_sevs and risk_band in ("Guarded", "Low"):
            risk_band = "Elevated"

        # exposure-only floor: a device with independent RED axes is materially risky even when its MODELED blast
        # radius is Info -- which on a partially-collected estate usually means its gateway/core was UNcollected
        # (impact forced to the floor at 1, capping risk_index at <=10 = Guarded), NOT that it is safe to lose. So
        # floor the band by the red-axis count, and never let a Critical-health box read 'Low / routine': a switch
        # the health scorer flagged Critical is, at minimum, a watch item in the risk register (audit-3 #11).
        if n_risk >= 3 and risk_band in ("Low", "Guarded"):
            risk_band = "Elevated"
        elif (n_risk >= 2 or state.get("Health") == "risk") and risk_band == "Low":
            risk_band = "Guarded"

        # coverage-honesty: a device with NO collected evidence (no health score -> 'Insufficient
        # Data' band, every risk axis n/a, no risk/watch signal) is NOT low-risk — it is UNASSESSED.
        # Banding it "Low / no stacked risk" would read a collection GAP as a clean bill of health
        # (the exact false-health the doctrine forbids). Distinct band so it never inflates the risk
        # view yet is counted + visible. (Meridian: the 50 not-collected devices.)
        if band == "Insufficient Data" and n_risk == 0 and n_watch == 0:
            risk_band = "Unassessed"

        # -- the engineer's one-sentence verdict ------------------------------
        red_labels = [e["label"] for e in exposures if e["state"] == "risk"][:3]
        watch_labels = [e["label"] for e in exposures if e["state"] == "watch"][:3]
        if risk_band == "Unassessed":
            verdict = ("Not assessed — no evidence was collected for this device; this is a coverage "
                       "gap, not a clean bill of health. Collect before relying on a risk verdict.")
        elif risk_band == "Severe":
            verdict = ("Stabilize or replace before migration — "
                       + "; ".join(red_labels or watch_labels) + f"; {impact_phrase}.")
        elif risk_band == "Elevated":
            verdict = ("Remediate inside the migration plan — "
                       + "; ".join(red_labels + watch_labels[:max(0, 3 - len(red_labels))])
                       + f"; {impact_phrase}.")
        elif risk_band == "Guarded":
            verdict = ("Watch items only — " + "; ".join(watch_labels or red_labels or ["minor findings"])
                       + ".")
        elif n_risk:
            # Low compound risk but a red axis IS present -> not 'routine'. (The band floor above already lifts
            # Critical-health / 2+-axis devices; this covers a lone non-health red axis on an Info-impact box.)
            verdict = ("Single red axis, no compounding — " + "; ".join(red_labels)
                       + f"; {impact_phrase}. Address on its own merits, not as routine.")
        else:
            verdict = "No stacked risk — routine migration handling."

        per_device.append({
            "host": host,
            "model": (lcr or {}).get("model", ""), "platform": (lcr or {}).get("platform", ""),
            "sw_version": (lcr or {}).get("sw_version", "") or (swr or {}).get("sw_version", ""),
            "role": (hsr or {}).get("role", ""), "wave": wave_of.get(host, ""),
            "health_score": (hsr or {}).get("score"), "health_band": band,
            "eol_band": lcb if lcr else "Unknown", "train_band": swb if swr else "Unknown",
            "platform_band": phb if phr else "Unknown",
            "vpc_role": (vpc.get(host) or {}).get("role", ""),
            "stp_root_vlans": root_vlans,
            "impact_score": impact, "impact_severity": fi_sev or "—",
            "stranded": stranded, "vlans_impacted": vlans_imp,
            "exposure_score": exposure_score, "exposures": exposures,
            "n_risk": n_risk, "n_watch": n_watch, "n_na": n_na,
            "compound": compound,
            "risk_index": risk_index, "risk_band": risk_band, "verdict": verdict})

    per_device.sort(key=lambda d: (_DOSSIER_BAND_RANK.get(d["risk_band"], 9),
                                   -d["risk_index"], d["host"]))
    bands_c = {b: sum(1 for d in per_device if d["risk_band"] == b) for b in _DOSSIER_BANDS}
    n_compound = sum(len(d["compound"]) for d in per_device)
    worst = [d["host"] for d in per_device
             if d["risk_band"] in ("Severe", "Elevated")][:3]
    summary = {"n_devices": len(per_device), "bands": bands_c, "n_compound": n_compound,
               "worst": worst,
               "avg_risk_index": (round(sum(d["risk_index"] for d in per_device)
                                        / len(per_device)) if per_device else 0)}
    return {"per_device": per_device, "summary": summary,
            "note": ("Risk index = topology impact (1-10) x stacked exposure (0-10) per asset, "
                     "mirroring asset-risk practice (likelihood x impact). Synthesis of already-"
                     "computed axes only; an axis without evidence is 'not assessed', never red.")}
