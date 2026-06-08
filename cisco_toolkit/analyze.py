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
from typing import Any, Dict, List, Optional, Tuple

from cisco_toolkit import portdb, protocol_kb
from cisco_toolkit.cmdio import _load_cmd_output
from cisco_toolkit.model import DevicePhysical, InterfaceData
from cisco_toolkit.parse import (
    _parse_fhrp, _is_physical_port, parse_spanning_tree_blockedports,
    parse_etherchannel_summary_members, parse_ospf_neighbors, parse_bgp_summary,
    parse_eigrp_neighbors,
)
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
    scanned_map = {_canon_host(h): h for h in all_interfaces}   # canon -> real scanned hostname
    scanned = set(scanned_map)
    links: Dict[Tuple[str, str], Dict[str, object]] = {}
    for host, ifaces in all_interfaces.items():
        for port, d in ifaces.items():
            if not d.cdp_neighbor or not _is_infra_neighbor(d, scanned):
                continue
            nbr = d.cdp_neighbor.strip()
            # Display name: resolve a scanned neighbor advertised by its FQDN/serial-suffixed
            # CDP id (e.g. 'CORE.broadcast.ajmn') back to its real scanned hostname, so the
            # diagram / 'Topology Links' sheet don't render it as a second, duplicate node. A
            # genuinely off-scan neighbor (no canon match) keeps its raw advertised name.
            b_host = scanned_map.get(_canon_host(nbr), nbr)
            key = tuple(sorted([f"{_canon_host(host)}|{port.lower()}",
                                f"{_canon_host(nbr)}|{(d.neighbor_port or '?').lower()}"]))
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
            carrying = [l for l in host_links if _link_carries(l, vid) == "fwd"]
            backups  = [l for l in host_links if _link_carries(l, vid) == "blk"]
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
    Classic DFS low-link. Recursion depth is bounded by the longest simple path (campus fleets are
    tens of switches, well under the interpreter limit)."""
    disc: Dict[str, int] = {}
    low: Dict[str, int] = {}
    bridges: set = set()
    timer = [0]

    def dfs(u: str, parent) -> None:
        disc[u] = low[u] = timer[0]; timer[0] += 1
        for v in sorted(adj[u]):
            if v == parent:
                continue
            if v not in disc:
                dfs(v, u)
                low[u] = min(low[u], low[v])
                if low[v] > disc[u]:
                    bridges.add(frozenset((u, v)))
            else:
                low[u] = min(low[u], disc[v])

    for r in sorted(adj):
        if r not in disc:
            dfs(r, None)
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
            if (d.switchport_mode or "") == "Access":
                for m in _split_macs(d.end_host_mac):
                    macs.add(m)
        ep[host] = len(macs)
    out: List[Dict[str, object]] = []
    for gi, g in enumerate(move_groups, 1):
        switches = [str(h) for h in (g.get("switches") or [])]
        mbb, hard = [], []
        for h in switches:
            (mbb if len(adj.get(h, set())) >= 2 else hard).append(h)
        hard_ep = sum(ep.get(h, 0) for h in hard)
        if not switches:
            seq = "empty group"
        elif not hard:
            seq = f"all {len(mbb)} switch(es) dual-homed — fully make-before-break (no outage window needed)"
        elif not mbb:
            seq = f"all {len(hard)} switch(es) single-homed — every cutover needs a maintenance window"
        else:
            seq = (f"{len(hard)} hard cutover (single-homed, schedule a window) + "
                   f"{len(mbb)} make-before-break (dual-homed)")
        out.append({"group": f"Group {gi}", "make_before_break": sorted(mbb),
                    "hard_cutover": sorted(hard), "hard_cutover_endpoints": hard_ep, "sequence": seq})
    return out


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
    hosts = sorted(all_interfaces)
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
    scored = [r for r in (health_scores or [])
              if isinstance(r.get("score"), (int, float)) and r.get("band") != "Insufficient Data"]
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
    "No orphan VLANs": "Inventory",
    "Clean uplinks (no half-duplex)": "Baseline capture",
    "Device health floor": "Pilot/cutover",
    "Dependency mapping complete": "Dependency mapping",
    "Baseline capture": "Baseline capture",
    "Rollback plan documented": "Rollback",
}

def compute_migration_readiness(all_interfaces, move_groups, health_scores,
                                physical_health, l3_forwarding, cross_layer,
                                protocol_health, dep_map,
                                config: ScoringConfig = SCORING) -> List[dict]:
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
    for rec in (protocol_health or []):
        if rec.get("severity") == "High":
            proto_high.setdefault(rec["switch"], set()).add(rec["protocol"])
    xl_crit_hosts = {h for f in (cross_layer or []) if f.get("severity") == "Critical" for h in f.get("hosts", [])}
    # orphan VLAN -> its access switches
    orphan_hosts = set()
    for vid in dep_map["orphan"]:
        orphan_hosts |= dep_map["access_by_vlan"].get(vid, set())
    # audit-evidence indexes for the additive runbook checks
    model = dep_map.get("model") or {}
    topo_hosts = set(model.get("hosts", []) if isinstance(model, dict) else [])
    baseline_hosts = {rec.get("switch") for rec in (physical_health or [])}

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

        # ---- runbook audit checks (additive; never flip the verdict) ----
        # No-signal fall-back: when the evidence set is wholly absent we cannot
        # audit it, so we PASS rather than cry wolf (matches the engine's
        # "fall-back-when-no-data never false-negative" convention).
        # 11 dependency mapping complete: the group's switches are in the topology graph
        missing_topo = sorted(gset - topo_hosts) if topo_hosts else []
        checks.append(("Dependency mapping complete", "pass" if not missing_topo else "warn",
                       "topology/dependency map covers all group switches" if not missing_topo
                       else f"no topology data for {', '.join(missing_topo)}"))
        # 12 baseline capture: interface/physical counters collected for the group's switches
        missing_base = sorted(gset - baseline_hosts) if baseline_hosts else []
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
    if proto == "EtherChannel":                      # detail: 'Gi1/0/1(s); Gi1/0/2(I)'
        return sorted(set(re.findall(r"\(([sDIwH])\)", detail)))
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
            if not adv:
                continue
            out.append({"switch": host, "protocol": proto, "state": tok,
                        "severity": adv["severity"], "meaning": adv["meaning"],
                        "likely_cause": adv["likely_cause"], "remediation": adv["remediation"],
                        "confidence": adv["confidence"]})
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
                    e = svc.setdefault(key, {"service": rec["service"], "category": rec["category"],
                                             "broadcast": rec["broadcast"], "refs": 0, "hosts": set()})
                    e["refs"] += 1
                    e["hosts"].add(host)
                for addr in (r.get("src"), r.get("dst")):
                    ip = addr.get("ip") if isinstance(addr, dict) else None
                    if ip and ip not in mcast_groups:
                        mc = portdb.classify_multicast(ip)
                        if mc:
                            mcast_groups[ip] = {"group": ip, "name": mc.get("group", ""),
                                                "category": mc["category"], "broadcast": mc["broadcast"],
                                                "source": "ACL reference"}

    def _evidence(port, proto):
        m = acl_hits.get(f"{port}:{proto}")
        if m:
            return f"Confirmed (ACL hit-counts: {m} matches)"
        return "Inferred (ACL design intent -- not active traffic; no flow telemetry)"

    services = sorted(
        ({"port": p, "proto": pr, "service": e["service"], "category": e["category"],
          "broadcast": e["broadcast"], "refs": e["refs"], "host_count": len(e["hosts"]),
          "evidence_class": _evidence(p, pr)}
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
            mcast_groups[grp] = {"group": grp, "name": (mc or {}).get("group", ""),
                                 "category": (mc or {}).get("category", "Multicast"),
                                 "broadcast": bool((mc or {}).get("broadcast")),
                                 "source": "IGMP/mroute"}

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
        rec = {"group": ip, "name": g.get("name", ""), "category": g.get("category", ""),
               "broadcast": bool(g.get("broadcast")), "on_air": on_air,
               "source": g.get("source", ""), "mac": mac}
        groups.append(rec)
        if mac:
            by_mac[mac].append(rec)
    groups.sort(key=lambda r: _ipk(r["group"]))

    mac_aliases: List[dict] = []
    for mac, recs in by_mac.items():
        if len(recs) > 1:
            mac_aliases.append({"mac": mac, "groups": sorted((r["group"] for r in recs), key=_ipk),
                                "names": sorted({r["name"] for r in recs if r["name"]}),
                                "has_av": any(r["on_air"] for r in recs)})
    mac_aliases.sort(key=lambda a: (not a["has_av"], a["mac"]))

    # querier coverage: multicast-active SVI VLANs (PIM/mroute on a VlanN interface) lacking an IGMP querier
    q_vlans = {str(q.get("vlan", "")).strip() for q in queriers if str(q.get("vlan", "")).strip()}
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
        risks.append({"kind": "mac-alias", "severity": "High" if a["has_av"] else "Medium",
            "title": f"Multicast MAC-address overlap on {a['mac']}",
            "detail": (f"Groups {', '.join(a['groups'])} all map to L2 MAC {a['mac']} (IPv4 multicast is 32:1 "
                       "into Ethernet MACs). A switch that constrains multicast at the MAC level forwards them "
                       "together — receivers of one group see the other's traffic"
                       + (" (and at least one is a Broadcast-AV / on-air group)." if a["has_av"] else ".")),
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
               "n_mac_clashes": len(mac_aliases), "n_querier_gaps": len(gap_vlans),
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
        prio = (all_stp_roots[host][vlan] or {}).get("root_priority")
        if isinstance(prio, int) and prio == 32768 + int(vlan):
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
    (re.compile(r"2110|\bsdi\b|playout|ingest|multiview|encoder|decoder|transcode|\bmcr\b|\bpcr\b|on.?air|\bvtr\b", re.I), "Broadcast A/V", 2),
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
_EP_VENDOR_RULES = [
    (("apc", "schneider", "eaton", "tripp", "vertiv", "liebert", "cyberpower"), "UPS/PDU", 2),
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
      "check point", "f5 net"), "Network", 1),
    (("canon", "epson", "brother inds", "xerox", "ricoh", "kyocera", "lexmark", "zebra tech"), "Printer", 2),
    (("polycom", "avaya", "mitel", "yealink", "grandstream"), "Phone", 2),
    (("dell", "hewlett packard", "hpe", "lenovo", "intel corp", "gigabyte", "asrock", "asustek"),
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
    clusters: Dict[tuple, list] = defaultdict(lambda: [set(), set(), 0])   # (vendor,class)->[switches,vlans,count]
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
                c = clusters[(vendor, cls)]; c[0].add(host); c[1].add(vlan); c[2] += 1
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
    for (vendor, cls), (sws, vlans, cnt) in clusters.items():
        if cnt < 3:
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
        mbb_pct = round(100 * mbb / (mbb + hard)) if (mbb + hard) else 0
        if readiness == "NOT READY":
            sc = "phased"; why = (f"gating checks fail ({r.get('n_fail', 0)} blocker(s)) — resolve them, "
                                  "then migrate in small validated waves.")
        elif hard and hard_eps >= max(eps * 0.2, 1):
            sc = "phased"; why = (f"{hard} single-homed switch(es) ({hard_eps} endpoint(s) at risk) — "
                                  "phase into maintenance windows; dual-home first where possible.")
        elif members >= 4 and mbb_pct >= 80:
            sc = "parallel-run"; why = (f"{mbb_pct}% of switches are dual-homed — build beside and cut "
                                        "leg-by-leg (make-before-break) for minimal outage.")
        elif members <= 2:
            sc = "big-bang" if members <= 1 else "phased"
            why = ("tiny group — a single window is feasible (rehearse rollback)." if members <= 1
                   else "small group — migrate phased with per-endpoint validation.")
        else:
            sc = "phased"; why = "mixed homing — phased waves with per-class validation are the safe default."
        counts[sc] = counts.get(sc, 0) + 1
        per_group.append({"group": g, "switches": members, "endpoints": eps, "readiness": readiness,
                          "make_before_break": mbb, "hard_cutover": hard, "hard_cutover_endpoints": hard_eps,
                          "dual_homed_pct": mbb_pct, "recommended_scenario": sc, "rationale": why,
                          "playbook": _SCENARIO_PLAYBOOK[sc]})
    fleet = ""
    hs = health_scores or []
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


def compute_operational_drift(all_interfaces: Dict[str, Dict[str, InterfaceData]],
                              all_device_physical: list) -> List[dict]:
    """NEW-V3.23.93: evidence-led FALSE-HEALTH / operational-drift detector. Surfaces the migration
    traps a green control plane hides (cisco-network-assessment doctrine: "configured is not healthy;
    up is not healthy"): temporary L2 bridges enlarging the broadcast/STP domain, PoE faults on ports
    described as live powered endpoints, native-VLAN-1 on inter-switch trunks, and multi-year uptime
    (STP / control-plane not exercised recently -> latent risk that surfaces on the first change).

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
            is_infra = bool((d.cdp_neighbor or "").strip()) or (d.trunk_status or "").lower().startswith("trunk")
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

    # 2. PoE fault on a port described as a live powered endpoint -- a pre-cutover action, not cosmetic.
    poe_by_host: Dict[str, list] = {}
    for host, ports in all_interfaces.items():
        for p, d in ports.items():
            ps = (d.poe_status or ""); desc = (d.description or "").strip()
            if ps and POE_FAULT.search(ps) and POWERED.search(desc):
                poe_by_host.setdefault(host, []).append(f"{p} ({desc[:30]}: {ps})")
    for host, ports in sorted(poe_by_host.items()):
        out.append({"severity": "High", "category": "False-health", "devices": [host],
                    "title": f"PoE fault on powered endpoint(s) on {host}",
                    "detail": f"{len(ports)} port(s) in a PoE fault state with a powered-endpoint "
                              f"description: {', '.join(ports[:6])}. The endpoint is likely dark.",
                    "remediation": "Resolve the PoE fault (power budget / cabling / device) before the "
                                   "cutover window."})

    # 3. Native VLAN 1 on inter-switch trunks -- hygiene / VLAN-hopping exposure. AGGREGATED.
    nat1_hosts: list = []
    for host, ports in all_interfaces.items():
        if any((d.trunk_status or "").lower().startswith("trunk")
               and (d.trunk_native_vlan or "").strip() == "1" for d in ports.values()):
            nat1_hosts.append(host)
    nat1_count = sum(1 for host, ports in all_interfaces.items() for d in ports.values()
                     if (d.trunk_status or "").lower().startswith("trunk")
                     and (d.trunk_native_vlan or "").strip() == "1")
    if nat1_hosts:
        out.append({"severity": "Low", "category": "False-health", "devices": sorted(nat1_hosts),
                    "title": f"Native VLAN 1 on {nat1_count} inter-switch trunk(s)",
                    "detail": f"{nat1_count} trunk(s) across {len(nat1_hosts)} switch(es) carry the default "
                              "VLAN 1 as the native (untagged) VLAN -- a hygiene and VLAN-hopping exposure.",
                    "remediation": "Set a dedicated, unused native VLAN on inter-switch trunks."})

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
                                media_risks: Optional[list] = None) -> List[dict]:
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

    def add(severity: str, category: str, devices, title: str, detail: str, remediation: str = "") -> None:
        devs = sorted({d for d in devices if d})
        waves = sorted({wave_of.get(d, "") for d in devs} - {""})
        items.append({"severity": severity, "rank": _PUNCH_RANK.get(severity, 0),
                      "category": category, "devices": devs, "wave": ", ".join(waves),
                      "title": title, "detail": (detail or "")[:300], "remediation": remediation})

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
        add("High", "FHRP", [m.get("host") for m in fr.get("members", [])],
            f"Fake FHRP redundancy (VLAN {fr.get('vid')})",
            "; ".join(fr.get("issues", [])),
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
    for d in (media_risks or []):
        add(d.get("severity", "Medium"), "Multicast/Media", d.get("devices", []),
            d.get("title", ""), d.get("detail", ""), d.get("remediation", ""))

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
        worst = min((b for b in bands if b), key=lambda b: _APP_BAND_RANK.get(b, 99), default="")
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
# Hardware lifecycle (EoL / End-of-Support) risk (NEW-V3.23.117). A new assessment AXIS: per-device
# replacement urgency from the offline `eoldb` knowledge base (a top REASON orgs migrate). Reference
# dates (curated KB, not device-read); LDoS is often derived = EoS+5yr. The robust output is the BAND
# (Past-LDoS / Near / Past-EoS / Active / Unknown) -- correct even if an exact date is off by months.
# =============================================================================
_LIFECYCLE_BAND_RANK = {"Past-LDoS": 0, "Near-LDoS": 1, "Past-EoS": 2, "Active": 3, "Unknown": 4}


def compute_lifecycle_risk(devices: Optional[dict] = None, asof: Optional[object] = None) -> dict:
    """NEW-V3.23.117: per-device hardware lifecycle (EoL/End-of-Support) risk from the offline eoldb KB,
    classified relative to `asof` (the assessment date; ISO 'YYYY-MM-DD' / date / datetime, default today).
    Reference dates from a curated KB (not device-read); LDoS often derived = EoS+5yr. Pure read;
    deterministic; tolerant of empty input. Returns {per_device, summary, risks, asof, note}."""
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
        model = (dv.get("model") or "").strip()
        sw = (dv.get("sw_version") or "").strip()
        rec = eoldb.lifecycle_for(model)
        if rec is None:
            per_device.append({"host": host, "model": model or "(unknown)", "platform": "", "sw_version": sw,
                               "eos": "", "ldos": "", "band": "Unknown", "years_to_ldos": None,
                               "status": "Unknown model — verify on Cisco's EoL portal", "source": "", "conf": ""})
            continue
        eos, ldos = _d(rec["eos"]), _d(rec["ldos"])
        if rec["conf"] == "active" or (not eos and not ldos):
            band, status, yrs = "Active", "Active (no end-of-life announced)", None
        else:
            yrs = round((ldos - today).days / 365.25, 1) if ldos else None
            if ldos and today > ldos:
                band = "Past-LDoS"; status = f"Past end-of-support (LDoS {rec['ldos']}, {rec['conf']})"
            elif ldos and yrs is not None and yrs <= 1.0:
                band = "Near-LDoS"; status = f"End-of-support within 1 year (LDoS {rec['ldos']}, {rec['conf']})"
            elif eos and today > eos:
                band = "Past-EoS"; status = f"Past end-of-sale (EoS {rec['eos']}; LDoS {rec['ldos']})"
            else:
                band = "Active"; status = f"In support (LDoS {rec['ldos']})"
        per_device.append({"host": host, "model": model, "platform": rec["platform"], "sw_version": sw,
                           "eos": rec["eos"], "ldos": rec["ldos"], "band": band, "years_to_ldos": yrs,
                           "status": status, "source": rec["source"], "conf": rec["conf"]})

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
    for band, sev, title, rem in (
        ("Past-LDoS", "Critical", "Hardware past Cisco end-of-support (no TAC / no fixes)",
         "Prioritize these in the migration / hardware refresh — they get no software fixes or TAC support."),
        ("Near-LDoS", "High", "Hardware within 1 year of end-of-support",
         "Schedule replacement before LDoS; confirm the migration target covers these."),
    ):
        devs = sorted(d["host"] for d in per_device if d["band"] == band)
        if devs:
            plats = sorted({d["platform"] for d in per_device if d["band"] == band})
            risks.append({"severity": sev, "devices": devs, "title": title,
                          "detail": f"{len(devs)} device(s) on {', '.join(plats)}.", "remediation": rem})

    summary = {"n_devices": len(per_device), "by_band": dict(by_band),
               "n_past_ldos": by_band.get("Past-LDoS", 0), "n_near": by_band.get("Near-LDoS", 0),
               "n_past_eos": by_band.get("Past-EoS", 0), "n_active": by_band.get("Active", 0),
               "n_unknown": by_band.get("Unknown", 0), "by_platform": by_platform, "asof": today.isoformat()}
    return {"per_device": per_device, "summary": summary, "risks": risks, "asof": today.isoformat(),
            "note": "Reference dates from a curated offline KB (Cisco EoL bulletins); last-day-of-support is "
                    "often derived = end-of-sale + 5yr. Verify exact dates on Cisco's End-of-Life portal."}


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
        has_dedicated_vrf = any(g["vrf"] for g in dgw)
        isolated = bool(dgw) and (has_dedicated_vrf or dacl > 0)
        if not dgw:
            exposure = "No L3 gateway on this domain's switches (L2-only, or its gateway lives elsewhere)."
        elif isolated:
            exposure = "Has a dedicated VRF or a gateway ACL."
        else:
            exposure = "Shares the global VRF, no gateway ACL — reachable from every other domain at L3."
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
