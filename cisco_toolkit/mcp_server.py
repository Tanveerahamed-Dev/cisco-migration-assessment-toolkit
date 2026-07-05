"""Optional Model Context Protocol (MCP) server over a produced snapshot.json.

Plan-A Tier-3 #18. Exposes READ-ONLY query tools an assistant can call to reason about an
assessed estate -- fleet orientation, inventory, per-device risk dossier, punch-list
findings (list and single-finding lookup), device search with health/risk posture,
failure blast-radius, topology chokepoints, architecture coverage, move-group readiness,
single-node what-if failure injection, the L2 failover twin (STP re-election + FHRP
takeover, actuated with a target) and its target-free readiness rollup, and fleet /
per-device health. It mirrors analysis the explorer / webapp already compute; it never
SSHes, never writes, never hits the network. Input is a snapshot file the engine already
produced.

Design: the data layer (the module-level functions below) is PURE and stdlib-only -- it
imports no `mcp`, so it is fully unit-testable without the optional dependency. The MCP
wiring lives in build_server(), which imports `mcp` lazily; installing the base package
never drags in `mcp`. Enable with:  pip install cisco-migration-assessment-toolkit[mcp]
then:  cisco-mcp-server path/to/snapshot.json

Coverage-honest: every extractor tolerates a missing / malformed section and returns an
empty or degraded result rather than raising -- a section the engine did not emit reads as
"absent", never a fabricated value.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

from . import failover, whatif

# The tools this server registers, in a stable order. Kept module-level so the test can
# assert the wired surface without importing `mcp`.
TOOL_NAMES = [
    "overview", "list_devices", "device_detail", "top_findings",
    "failure_impact", "chokepoints", "architecture_coverage",
    "get_finding", "search_devices", "get_move_groups", "whatif_node", "get_health",
    "failover_twin", "failover_readiness",
]


def _as_dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _as_list(v: Any) -> List[Any]:
    return v if isinstance(v, list) else []


def _pick(row: Dict[str, Any], keys) -> Dict[str, Any]:
    return {k: row.get(k) for k in keys}


def load_snapshot(path: str) -> Dict[str, Any]:
    """Load a snapshot.json from disk. Raises if it is not a JSON object (read-only)."""
    with open(path, encoding="utf-8") as f:
        snap = json.load(f)
    if not isinstance(snap, dict):
        raise ValueError(f"snapshot is not a JSON object: {path}")
    return snap


# --- pure data layer (no `mcp` import) -------------------------------------------------

def overview(snap: Dict[str, Any]) -> Dict[str, Any]:
    """High-level orientation: fleet scale, posture, and the top gating issues."""
    eb = _as_dict(snap.get("executive_brief"))
    scale = _as_dict(eb.get("scale"))
    return {
        "scale": _pick(scale, ("n_devices", "n_collected", "n_domains", "n_vlans", "n_endpoints")),
        "posture": eb.get("posture"),
        "posture_statement": eb.get("posture_statement"),
        "top_gating": _as_list(eb.get("top_gating")),
    }


def list_devices(snap: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Inventory: every device with model, platform, software, role, health and risk band."""
    per = _as_list(_as_dict(snap.get("device_dossiers")).get("per_device"))
    if per:
        cols = ("host", "model", "platform", "sw_version", "role", "wave",
                "health_band", "eol_band", "risk_band", "verdict")
        return [_pick(r, cols) for r in per if isinstance(r, dict)]
    # fallback for older snapshots without dossiers: derive from health_scores
    return [{"host": r.get("switch"), "role": r.get("role"),
             "health_band": r.get("band"), "score": r.get("score")}
            for r in _as_list(snap.get("health_scores")) if isinstance(r, dict)]


def device_detail(snap: Dict[str, Any], host: str) -> Dict[str, Any]:
    """The full risk dossier for ONE device, matched case-insensitively by hostname."""
    per = _as_list(_as_dict(snap.get("device_dossiers")).get("per_device"))
    want = str(host or "").strip().lower()
    for r in per:
        if isinstance(r, dict) and str(r.get("host", "")).lower() == want:
            return r
    available = [r.get("host") for r in per if isinstance(r, dict)][:40]
    return {"error": f"device not found: {host!r}", "available_hosts": available}


def top_findings(snap: Dict[str, Any], limit: int = 20,
                 severity: Optional[str] = None) -> List[Dict[str, Any]]:
    """Severity-ranked migration punch-list findings; optional exact-severity filter."""
    rows = [r for r in _as_list(snap.get("punchlist")) if isinstance(r, dict)]
    if severity:
        sev = str(severity).strip().lower()
        rows = [r for r in rows if str(r.get("severity", "")).lower() == sev]
    cols = ("severity", "rank", "category", "title", "devices", "wave", "detail", "remediation")
    return [_pick(r, cols) for r in rows[: max(0, int(limit))]]


def failure_impact(snap: Dict[str, Any], limit: int = 20) -> List[Dict[str, Any]]:
    """Per-device failure blast-radius: stranded endpoints, VLANs impacted, FHRP backup."""
    rows = [r for r in _as_list(snap.get("failure_impact")) if isinstance(r, dict)]
    cols = ("host", "severity", "stranded", "vlans_impacted", "hard", "backup", "fhrp", "detail")
    return [_pick(r, cols) for r in rows[: max(0, int(limit))]]


def chokepoints(snap: Dict[str, Any], limit: int = 20) -> List[Dict[str, Any]]:
    """Topology chokepoint links ranked by betweenness; bridges / articulation cuts."""
    out = []
    for r in _as_list(snap.get("link_centrality"))[: max(0, int(limit))]:
        if not isinstance(r, dict):
            continue
        out.append({
            "a": f"{r.get('a_host')}:{r.get('a_port')}",
            "b": f"{r.get('b_host')}:{r.get('b_port')}",
            "betweenness": r.get("betweenness"),
            "is_bridge": r.get("is_bridge"),
            "pairs_cut": r.get("pairs_cut"),
            "rank": r.get("rank"),
        })
    return out


def architecture_coverage(snap: Dict[str, Any]) -> Dict[str, Any]:
    """Coverage-honest architecture-class map: what was observed, per SSH / JSON channel."""
    ac = _as_dict(snap.get("architecture_coverage"))
    classes = [_pick(c, ("key", "label", "channel", "observed", "n_hosts"))
               for c in _as_list(ac.get("classes")) if isinstance(c, dict)]
    return {"summary": ac.get("summary"), "classes": classes}


def get_finding(snap: Dict[str, Any], finding: Any) -> Dict[str, Any]:
    """ONE punch-list finding in full detail (devices, remediation), looked up by priority
    number or case-insensitive title substring. An ambiguous substring is disambiguated
    honestly: it returns the candidate list, never an arbitrary pick."""
    sources = ["punchlist"]
    rows = [r for r in _as_list(snap.get("punchlist")) if isinstance(r, dict)]
    if not rows:
        return {"available": False, "sources": sources,
                "reason": "snapshot has no 'punchlist' section -- findings were not computed"}
    query = str(finding if finding is not None else "").strip()
    if not query:
        return {"available": False, "sources": sources,
                "reason": "empty query -- pass a priority number or a title substring"}
    if query.lstrip("-").isdigit():                      # 1) exact priority-index lookup
        want = int(query)
        for r in rows:
            if r.get("priority") == want:
                return {"available": True, "matched_by": "priority", "finding": r, "sources": sources}
        # fall through: a numeric query may still be a title fragment (e.g. '01')
    ql = query.lower()                                   # 2) case-insensitive title substring
    hits = [r for r in rows if ql in str(r.get("title", "")).lower()]
    if len(hits) == 1:
        return {"available": True, "matched_by": "title", "finding": hits[0], "sources": sources}
    if len(hits) > 1:
        return {"available": False, "ambiguous": True, "sources": sources,
                "reason": f"{len(hits)} findings match {query!r} -- refine the title or use a priority number",
                "matches": [_pick(r, ("priority", "severity", "title")) for r in hits[:25]]}
    return {"available": False, "sources": sources,
            "reason": f"no finding matches {query!r} (by priority number or title substring)"}


def search_devices(snap: Dict[str, Any], query: Any) -> Dict[str, Any]:
    """Find devices by hostname / IP / platform / model substring, with a one-line posture per
    match: health band always (dossier, else health_scores), risk band ONLY when dossiers were
    computed -- an un-assessed axis reads 'not-assessed', never a fabricated value."""
    sources = ["devices", "device_dossiers", "health_scores", "interfaces"]
    devices = _as_dict(snap.get("devices"))
    dossiers = {str(r.get("host", "")).lower(): r
                for r in _as_list(_as_dict(snap.get("device_dossiers")).get("per_device")) if isinstance(r, dict)}
    health = {str(r.get("switch", "")).lower(): r
              for r in _as_list(snap.get("health_scores")) if isinstance(r, dict)}
    interfaces = _as_dict(snap.get("interfaces"))
    if not (devices or dossiers or health or interfaces):
        return {"available": False, "sources": sources,
                "reason": "snapshot has no device inventory sections (devices / device_dossiers / "
                          "health_scores / interfaces)"}
    q = str(query or "").strip().lower()
    if not q:
        return {"available": False, "sources": sources,
                "reason": "empty query -- pass a hostname, IP or platform substring"}
    all_hosts, seen = [], set()
    for h in (list(devices) + [r.get("host") for r in dossiers.values()]
              + [r.get("switch") for r in health.values()] + list(interfaces)):
        hs = str(h or "")
        if hs and hs.lower() not in seen:
            seen.add(hs.lower())
            all_hosts.append(hs)
    matches = []
    for host in sorted(all_hosts, key=str.lower):
        hl = host.lower()
        dev = _as_dict(devices.get(host))
        dos = dossiers.get(hl, {})
        matched_on = []
        if q in hl or q in str(dev.get("hostname", "")).lower():
            matched_on.append("host")
        if any(v and q in str(v).lower() for v in (dev.get("platform"), dos.get("platform"))):
            matched_on.append("platform")
        if any(v and q in str(v).lower() for v in (dev.get("model"), dos.get("model"))):
            matched_on.append("model")
        ips = {str(r.get("current_switch_ip")) for r in _as_dict(interfaces.get(host)).values()
               if isinstance(r, dict) and r.get("current_switch_ip")}
        if any(q in ip.lower() for ip in ips):
            matched_on.append("ip")
        if not matched_on:
            continue
        health_band = dos.get("health_band") or health.get(hl, {}).get("band")
        risk_band = dos.get("risk_band") if dossiers else None    # no dossiers -> never fabricate a risk band
        matches.append({
            "host": host, "matched_on": matched_on,
            "health_band": health_band, "risk_band": risk_band,
            "posture": f"health: {health_band or 'not-assessed'}; risk: {risk_band or 'not-assessed'}",
        })
    return {"available": True, "query": str(query), "n_matches": len(matches),
            "matches": matches[:100], "sources": sources}


def get_move_groups(snap: Dict[str, Any]) -> Dict[str, Any]:
    """Move groups joined with their readiness verdict, gating checks, wave sequencing and the
    recommended migration scenario. A group whose readiness was never computed reads
    'not-assessed' -- absence of evidence is never health."""
    sources = ["move_groups", "migration_readiness", "wave_sequencing", "migration_scenarios"]
    raw = [g for g in _as_list(snap.get("move_groups")) if isinstance(g, dict)]
    if not raw:
        return {"available": False, "sources": sources,
                "reason": "snapshot has no 'move_groups' section -- grouping was not computed"}
    readiness_by = {str(r.get("group")): r for r in _as_list(snap.get("migration_readiness")) if isinstance(r, dict)}
    seq_by = {str(r.get("group")): r for r in _as_list(snap.get("wave_sequencing")) if isinstance(r, dict)}
    ms = _as_dict(snap.get("migration_scenarios"))
    scen_by = {str(r.get("group")): r for r in _as_list(ms.get("per_group")) if isinstance(r, dict)}
    groups = []
    for i, g in enumerate(raw):
        name = f"Group {i + 1}"     # move_groups rows are anonymous; downstream sections name them by index
        rdy, seq, scen = readiness_by.get(name), seq_by.get(name), scen_by.get(name)
        groups.append({
            "group": name,
            "switches": _as_list(g.get("switches")),
            "endpoints": g.get("endpoints"),
            "spanning_vlans": _as_list(g.get("spanning_vlans")),
            "gateways": _as_list(g.get("gateways")),
            "readiness": (rdy or {}).get("readiness") or "not-assessed",
            "gating": _pick(rdy, ("n_fail", "n_warn", "checks")) if rdy else None,
            "sequencing": _pick(seq, ("sequence", "make_before_break", "hard_cutover",
                                      "homing_unknown", "hard_cutover_endpoints")) if seq else None,
            "scenario": _pick(scen, ("recommended_scenario", "rationale", "playbook", "make_before_break",
                                     "hard_cutover", "dual_homed_pct")) if scen else None,
        })
    return {"available": True, "n_groups": len(groups), "groups": groups,
            "fleet_recommendation": ms.get("fleet_recommendation"), "sources": sources}


def whatif_node(snap: Dict[str, Any], host: Any) -> Dict[str, Any]:
    """Single-node failure injection over snap['routes'] via cisco_toolkit.whatif -- the engine
    result is returned VERBATIM so its coverage-honest wording (blocked vs lost-path vs
    inconclusive, the nothing-was-removed note) is preserved."""
    sources = ["routes"]
    want = str(host or "").strip()
    if not want:
        return {"available": False, "sources": sources,
                "reason": "no host given -- pass the hostname of the device to fail"}
    routes = snap.get("routes") if isinstance(snap, dict) else None
    if not isinstance(routes, dict) or not routes:
        return {"available": False, "sources": sources,
                "reason": "snapshot has no 'routes' section -- failure injection needs collected routing tables"}
    scenario = {"failures": [{"type": "node", "id": want}]}
    result = whatif.run_scenario(snap, scenario)
    out = {"available": True, "host": want, "result": result, "sources": sources}
    if not result.get("removed_hosts"):                  # honest miss: say which hosts COULD be failed
        out["available_route_hosts"] = sorted(routes.keys())
    return out


def get_health(snap: Dict[str, Any], host: Optional[str] = None) -> Dict[str, Any]:
    """Fleet health-band distribution and worst devices (default), or ONE device's score, band
    and top deductions when `host` is given (case-insensitive)."""
    sources = ["health_scores"]
    rows = [r for r in _as_list(snap.get("health_scores")) if isinstance(r, dict)]
    if not rows:
        return {"available": False, "sources": sources,
                "reason": "snapshot has no 'health_scores' section -- health was not scored"}
    if host is None or not str(host).strip():
        bands: Dict[str, int] = {}
        for r in rows:
            b = str(r.get("band") or "not-assessed")
            bands[b] = bands.get(b, 0) + 1
        worst = sorted(rows, key=lambda r: r["score"] if isinstance(r.get("score"), (int, float)) else float("inf"))
        return {"available": True, "n_devices": len(rows), "bands": bands,
                "worst": [_pick(r, ("switch", "score", "band", "role")) for r in worst[:10]],
                "sources": sources}
    want = str(host).strip().lower()
    for r in rows:
        if str(r.get("switch", "")).lower() == want:
            return {"available": True, "host": r.get("switch"), "score": r.get("score"),
                    "band": r.get("band"), "role": r.get("role"),
                    "top_issues": _as_list(r.get("deductions"))[:10], "sources": sources}
    return {"available": False, "sources": sources,
            "reason": f"device not found in health_scores: {host!r}",
            "available_hosts": [r.get("switch") for r in rows][:40]}


def failover_twin(snap: Dict[str, Any], target: Any) -> Dict[str, Any]:
    """L2 failover twin (cisco_toolkit.failover): remove a node/site and recompute per-VLAN STP root
    re-election and FHRP (HSRP/VRRP/GLBP) master takeover from snap['stp_roots'] + snap['fhrp_detail'].
    The engine result is returned VERBATIM so its coverage-honest wording (indeterminate abstention,
    default-election smell, split-brain / VIP-stranded flags) is preserved. `target` is a hostname (a
    node) or a site-code substring."""
    sources = ["stp_roots", "fhrp_detail"]
    want = str(target or "").strip()
    if not want:
        return {"available": False, "sources": sources,
                "reason": "no target given -- pass a hostname (node) or a site-code substring to fail"}
    has_stp = isinstance(snap.get("stp_roots"), dict) and snap.get("stp_roots")
    has_fhrp = isinstance(snap.get("fhrp_detail"), dict) and snap.get("fhrp_detail")
    if not (has_stp or has_fhrp):
        return {"available": False, "sources": sources,
                "reason": "snapshot has neither 'stp_roots' nor 'fhrp_detail' -- the L2 twin needs collected "
                          "spanning-tree / first-hop-redundancy state"}
    # accept a bare host OR the whatif {type,id} shape; default to a node match, fall back to a site substring
    result = failover.compute_failover_twin(snap, [{"type": "node", "id": want}])
    if not result["failed_hosts"]:
        result = failover.compute_failover_twin(snap, [{"type": "site", "id": want}])
    out = {"available": True, "target": want, "result": result, "sources": sources}
    if not result["failed_hosts"]:                       # honest miss: say which hosts COULD be failed
        hosts = set()
        for sec in ("stp_roots", "fhrp_detail"):
            s = snap.get(sec)
            if isinstance(s, dict):
                hosts.update(s.keys())
        out["available_l2_hosts"] = sorted(hosts)
    return out


def failover_readiness(snap: Dict[str, Any]) -> Dict[str, Any]:
    """Target-free L2 resilience rollup (cisco_toolkit.failover): for EVERY observed STP root and FHRP
    forwarding member, is there a PROVABLE backup on a single failure? Returns the engine's verbatim
    coverage-honest tallies (roots/actives with a proven backup vs default-election smell vs indeterminate)
    and the named at-risk list."""
    sources = ["stp_roots", "fhrp_detail"]
    has_stp = isinstance(snap.get("stp_roots"), dict) and snap.get("stp_roots")
    has_fhrp = isinstance(snap.get("fhrp_detail"), dict) and snap.get("fhrp_detail")
    if not (has_stp or has_fhrp):
        return {"available": False, "sources": sources,
                "reason": "snapshot has neither 'stp_roots' nor 'fhrp_detail' -- L2 readiness needs collected "
                          "spanning-tree / first-hop-redundancy state"}
    return {"available": True, "result": failover.compute_failover_readiness(snap), "sources": sources}


# name -> pure function, captured so build_server's same-named tool wrappers don't shadow it
_PURE = {
    "overview": overview, "list_devices": list_devices, "device_detail": device_detail,
    "top_findings": top_findings, "failure_impact": failure_impact,
    "chokepoints": chokepoints, "architecture_coverage": architecture_coverage,
    "get_finding": get_finding, "search_devices": search_devices,
    "get_move_groups": get_move_groups, "whatif_node": whatif_node, "get_health": get_health,
    "failover_twin": failover_twin, "failover_readiness": failover_readiness,
}


# --- MCP wiring (lazy `mcp` import) ----------------------------------------------------

def build_server(snap: Dict[str, Any], name: str = "cisco-assessment"):
    """Build a FastMCP server whose tools are bound to `snap`. Imports `mcp` lazily so the
    base package never depends on it. Returns the FastMCP instance (call .run() to serve)."""
    from mcp.server.fastmcp import FastMCP  # optional dependency, resolved only here

    server = FastMCP(name)
    P = _PURE

    @server.tool()
    def overview() -> dict:  # noqa: F811 - tool name is the wire contract
        """Fleet orientation: scale (device/VLAN/endpoint counts), posture, top gating issues."""
        return P["overview"](snap)

    @server.tool()
    def list_devices() -> list:  # noqa: F811
        """Inventory of every device: model, platform, software, role, health & risk band."""
        return P["list_devices"](snap)

    @server.tool()
    def device_detail(host: str) -> dict:  # noqa: F811
        """Full risk dossier for ONE device, by hostname (health, EoL, exposures, verdict)."""
        return P["device_detail"](snap, host)

    @server.tool()
    def top_findings(limit: int = 20, severity: str = "") -> list:  # noqa: F811
        """Severity-ranked migration punch-list findings; pass severity to filter (e.g. 'High')."""
        return P["top_findings"](snap, limit, severity or None)

    @server.tool()
    def failure_impact(limit: int = 20) -> list:  # noqa: F811
        """Per-device failure blast-radius: stranded endpoints, VLANs impacted, FHRP backup."""
        return P["failure_impact"](snap, limit)

    @server.tool()
    def chokepoints(limit: int = 20) -> list:  # noqa: F811
        """Topology chokepoint links ranked by betweenness; bridges / articulation points."""
        return P["chokepoints"](snap, limit)

    @server.tool()
    def architecture_coverage() -> dict:  # noqa: F811
        """Coverage-honest architecture-class map (observed per SSH / JSON controller channel)."""
        return P["architecture_coverage"](snap)

    @server.tool()
    def get_finding(finding: str) -> dict:  # noqa: F811
        """ONE punch-list finding in full detail (devices, remediation), by priority number or title substring."""
        return P["get_finding"](snap, finding)

    @server.tool()
    def search_devices(query: str) -> dict:  # noqa: F811
        """Find devices by hostname / IP / platform substring; one-line health + risk posture per match."""
        return P["search_devices"](snap, query)

    @server.tool()
    def get_move_groups() -> dict:  # noqa: F811
        """Move groups with readiness verdicts, gating checks, wave sequencing and recommended scenario."""
        return P["get_move_groups"](snap)

    @server.tool()
    def whatif_node(host: str) -> dict:  # noqa: F811
        """What-if failure injection: remove ONE device from the routing view; blocked vs lost-path flows."""
        return P["whatif_node"](snap, host)

    @server.tool()
    def get_health(host: str = "") -> dict:  # noqa: F811
        """Fleet health-band distribution (default), or one device's score, band and top deductions."""
        return P["get_health"](snap, host or None)

    @server.tool()
    def failover_twin(target: str) -> dict:  # noqa: F811
        """L2 failover twin: remove a node/site and recompute per-VLAN STP root re-election and FHRP
        (HSRP/VRRP/GLBP) master takeover; default-election smell + split-brain / VIP-stranded flags."""
        return P["failover_twin"](snap, target)

    @server.tool()
    def failover_readiness() -> dict:  # noqa: F811
        """L2 resilience rollup: for every observed STP root and FHRP active, is there a provable backup
        on a single failure (proven vs default-election smell vs indeterminate blind spot)."""
        return P["failover_readiness"](snap)

    return server


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(
        prog="cisco-mcp-server",
        description="Read-only MCP server over a produced cisco-assess snapshot.json (offline, no egress).")
    ap.add_argument("snapshot", help="path to a snapshot.json produced by cisco-assess")
    ap.add_argument("--name", default="cisco-assessment", help="server name advertised to the MCP client")
    ap.add_argument("--transport", default="stdio", choices=["stdio", "sse", "streamable-http"],
                    help="MCP transport (default: stdio)")
    args = ap.parse_args(argv)

    try:
        import mcp  # noqa: F401 - presence check only
    except ImportError:
        sys.exit("the MCP server needs the optional 'mcp' extra:\n"
                 "  pip install cisco-migration-assessment-toolkit[mcp]")

    snap = load_snapshot(args.snapshot)
    server = build_server(snap, name=args.name)
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
