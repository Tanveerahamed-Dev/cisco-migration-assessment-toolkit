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
            # CDP id (e.g. 'CORE.broadcast.[HISTORY-REDACTED]') back to its real scanned hostname, so the
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
                                hostname_mismatches: Optional[list] = None) -> List[dict]:
    """NEW-V3.23.63: the consolidated, severity-ranked migration PUNCH-LIST -- one prioritized,
    de-duplicated, per-device, per-wave table that rolls up EVERY actionable finding the run
    produced (cross-layer SPOFs, security gaps, config hygiene, L1/L3 risks, protocol health,
    STP design, device health) so a migration lead reads one 'fix-this-first, in this order'
    list instead of cross-referencing ~25 sheets. Pure synthesis of already-computed records;
    no new collection. Sorted Critical->Low; like findings are grouped (one row + a device list,
    not one row per port) so it does not 'cry wolf'."""
    wave_of: Dict[str, str] = {}
    for g in (move_groups or []):
        for h in g.get("switches", []):
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

    items.sort(key=lambda x: (-x["rank"], x["category"], x["title"]))
    for i, it in enumerate(items, 1):
        it["priority"] = i
    return items
