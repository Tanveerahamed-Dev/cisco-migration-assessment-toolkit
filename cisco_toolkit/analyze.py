"""The analyze layer's scoring foundation: the health-score / migration-readiness
tunables (`ScoringConfig` + the module-default `SCORING`) plus the two small pure
helpers every `compute_*` leans on (`_health_band`, `_host_role`). Depends only on
`dataclasses`, stdlib `re`/`typing`, and `cisco_toolkit.model`. Extracted verbatim
from COLLECT_PARSE_V3_23_0.py in PHASE 2.7 step 10 (behaviour byte-identical).

The `compute_*` functions themselves follow in later steps (they entangle with the
`_load_cmd_output` I/O helper that still lives in the monolith). The Excel
fill-colour maps (`_READY_FILL`/`_STATUS_FILL`) and sheet-name constants stay
behind too - they belong to the excel layer, not the data analysis."""
import re
from dataclasses import dataclass, field as _dcfield   # aliased: 'field' is a common loop var elsewhere (avoids F402 shadowing)
from typing import Dict, List, Optional, Tuple

from cisco_toolkit.cmdio import _load_cmd_output
from cisco_toolkit.model import InterfaceData
from cisco_toolkit.textutils import _split_macs, normalize_ifname


# score band -> (label, fill)
_HEALTH_BANDS = [(90, "Excellent", "36E08A"), (75, "Good", "7ADB8F"),
                 (60, "Fair", "FFE566"), (40, "Poor", "FF9F45"), (0, "Critical", "FF5775")]


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
    # Per-category cap (max total deduction a single category can contribute).
    caps: Dict[str, int] = _dcfield(default_factory=lambda: {
        "L1": 30, "L3": 30, "XL": 45, "PROTO": 25})
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
    # NEW-V3.23.5: per-role multiplier on a switch's deductions (a fault on a
    # core/distribution switch has wider blast radius than on an access closet).
    # Defaults are 1.0 for every role, so scores stay byte-identical until tuned.
    criticality_factors: Dict[str, float] = _dcfield(default_factory=lambda: {
        "core": 1.0, "distribution": 1.0, "access": 1.0})
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
    """Normalize a neighbor device-id for matching: strip FQDN domain + serial suffix '(FOC...)'."""
    n = (name or "").strip()
    n = re.sub(r"\(.*?\)\s*$", "", n).strip()   # drop trailing '(serial)'
    n = n.split(".")[0]                          # drop FQDN domain
    return n.lower()

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

def compute_health_scores(all_interfaces: Dict[str, Dict[str, InterfaceData]],
                          physical_health: List[dict], l3_forwarding: List[dict],
                          cross_layer: List[dict], protocol_health: List[dict],
                          config: ScoringConfig = SCORING,
                          data_quality: Optional[Dict[str, float]] = None) -> List[dict]:
    """Per-switch 0-100 health score with weighted, category-capped deductions.
    Weights/caps/bands come from `config` (ScoringConfig); the default instance
    reproduces the prior hard-coded behaviour byte-for-byte."""
    hosts = sorted(all_interfaces)
    ded: Dict[str, Dict[str, List[Tuple[str, int]]]] = {
        h: {"L1": [], "L3": [], "XL": [], "PROTO": []} for h in hosts}

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

    CAP = config.caps
    records: List[dict] = []
    for h in hosts:
        # NEW-V3.23.5: scale this switch's deductions by its criticality role.
        # round() keeps integer scores; the default factor 1.0 is a no-op.
        factor = config.criticality_factors.get(_host_role(all_interfaces.get(h, {})), 1.0)
        total = 0
        reasons: List[str] = []
        for cat, items in ded[h].items():
            csum = min(round(sum(p for _r, p in items) * factor), CAP[cat])
            total += csum
            for r, p in sorted(items, key=lambda x: -x[1]):
                reasons.append(f"{r} (-{p})")
        score = max(0, 100 - total)
        band, _fill = _health_band(score, config.bands)
        rec = {"switch": h, "score": score, "band": band, "deductions": reasons[:8]}
        if data_quality is not None:                          # NEW-V3.23.7 (audit C3)
            dq = data_quality.get(h, 1.0)
            rec["data_quality"] = round(dq, 2)
            if dq < config.data_quality_threshold:
                rec["band"] = "Insufficient Data"             # collection gap != healthy
        records.append(rec)
    records.sort(key=lambda r: (r["score"], r["switch"]))
    return records

def compute_score_sensitivity(all_interfaces: Dict[str, Dict[str, InterfaceData]],
                              physical_health: List[dict], l3_forwarding: List[dict],
                              cross_layer: List[dict], protocol_health: List[dict],
                              config: ScoringConfig = SCORING,
                              deltas: Tuple[float, ...] = (-0.5, -0.25, 0.25, 0.5)) -> List[dict]:
    """NEW-V3.23.5: one-at-a-time (OAT) sensitivity sweep over the scoring weights.
    For each weight group, re-score the fleet with that group scaled by each delta
    and report how many switches change health band. Verdicts that flip under a
    small (+/-25%) perturbation are weakly supported - this is the OECD/JRC
    composite-indicator robustness check. Pure derivation; no new collection."""
    import dataclasses

    def _bands(cfg):
        return {r["switch"]: r["band"] for r in compute_health_scores(
            all_interfaces, physical_health, l3_forwarding, cross_layer, protocol_health, cfg)}

    base = _bands(config)
    out: List[dict] = []
    for grp in ("l1_weights", "l3_weights", "xl_weights", "proto_weights"):
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

# 10 pre-migration checks; each returns (status, note). status in pass/warn/fail.
def compute_migration_readiness(all_interfaces, move_groups, health_scores,
                                physical_health, l3_forwarding, cross_layer,
                                protocol_health, dep_map,
                                config: ScoringConfig = SCORING) -> List[dict]:
    """Per move-group READY/CAUTION/NOT READY from a 10-check pre-migration
    checklist. The status each check emits when its risk fires comes from
    `config.readiness`; the default instance reproduces the prior behaviour."""
    R = config.readiness
    # per-host indexes
    sf_hosts = {h for (h, _p) in dep_map["single_fiber"]}
    errdis_hosts = {h for (h, _p) in dep_map["errdis"]}
    halfdup_hosts = {h for (h, _p) in dep_map["halfdup_up"]}
    sole_gw_hosts = set(dep_map["sole_gw"].values())
    band_by_host = {r["switch"]: r["band"] for r in health_scores}
    proto_high: Dict = {}                            # host -> set(protocols at High)
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
        checks.append(("Redundant uplinks", R["redundant_uplinks"] if hit else "pass",
                       f"single-fiber uplink on {', '.join(hit)}" if hit else "no single-homed switch"))
        # 2 gateway redundancy (FHRP)
        hit = any_in(sole_gw_hosts)
        checks.append(("Gateway redundancy", R["gateway_redundancy"] if hit else "pass",
                       f"sole gateway on {', '.join(hit)} (no FHRP)" if hit else "gateways redundant / none in group"))
        # 3 no cross-layer Critical
        hit = any_in(xl_crit_hosts)
        checks.append(("No cross-layer Critical", R["no_xl_critical"] if hit else "pass",
                       f"Critical correlation on {', '.join(hit)}" if hit else "none"))
        # 4 no err-disabled ports
        hit = any_in(errdis_hosts)
        checks.append(("No err-disabled ports", R["no_errdisabled"] if hit else "pass",
                       f"err-disabled on {', '.join(hit)}" if hit else "none"))
        # 5 STP consistency
        hit = sorted({h for h in gset if "STP" in proto_high.get(h, set())})
        checks.append(("STP consistency", R["stp_consistency"] if hit else "pass",
                       f"inconsistent STP on {', '.join(hit)}" if hit else "no inconsistent ports"))
        # 6 port-channels healthy
        hit = sorted({h for h in gset if "EtherChannel" in proto_high.get(h, set())})
        checks.append(("Port-channels healthy", R["portchannels_healthy"] if hit else "pass",
                       f"unbundled member on {', '.join(hit)}" if hit else "all members bundled / none"))
        # 7 routing adjacencies up
        hit = sorted({h for h in gset if proto_high.get(h, set()) & {"OSPF", "BGP"}})
        checks.append(("Routing adjacencies up", R["routing_adjacencies"] if hit else "pass",
                       f"down OSPF/BGP neighbor on {', '.join(hit)}" if hit else "all neighbors up / none"))
        # 8 no orphan VLANs
        hit = any_in(orphan_hosts)
        checks.append(("No orphan VLANs", R["no_orphan_vlans"] if hit else "pass",
                       f"endpoints with off-scan gateway on {', '.join(hit)}" if hit else "none"))
        # 9 no degraded / half-duplex uplinks
        hit = any_in(halfdup_hosts)
        checks.append(("Clean uplinks (no half-duplex)", R["clean_uplinks"] if hit else "pass",
                       f"half-duplex uplink on {', '.join(hit)}" if hit else "none"))
        # 10 device health floor
        crit = sorted([h for h in gset if band_by_host.get(h) == "Critical"])
        poor = sorted([h for h in gset if band_by_host.get(h) == "Poor"])
        if crit:
            st, note = R["health_floor_critical"], f"Critical-health switch: {', '.join(crit)}"
        elif poor:
            st, note = R["health_floor_poor"], f"Poor-health switch: {', '.join(poor)}"
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
