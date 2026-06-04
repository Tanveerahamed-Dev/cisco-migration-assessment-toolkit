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
from typing import Dict, List, Tuple

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
