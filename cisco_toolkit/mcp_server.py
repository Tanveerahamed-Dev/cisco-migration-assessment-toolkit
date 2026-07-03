"""Optional Model Context Protocol (MCP) server over a produced snapshot.json.

Plan-A Tier-3 #18. Exposes READ-ONLY query tools an assistant can call to reason about an
assessed estate -- fleet orientation, inventory, per-device risk dossier, punch-list
findings, failure blast-radius, topology chokepoints, architecture coverage. It mirrors
analysis the explorer / webapp already compute; it never SSHes, never writes, never hits
the network. Input is a snapshot file the engine already produced.

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

# The tools this server registers, in a stable order. Kept module-level so the test can
# assert the wired surface without importing `mcp`.
TOOL_NAMES = [
    "overview", "list_devices", "device_detail", "top_findings",
    "failure_impact", "chokepoints", "architecture_coverage",
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


# name -> pure function, captured so build_server's same-named tool wrappers don't shadow it
_PURE = {
    "overview": overview, "list_devices": list_devices, "device_detail": device_detail,
    "top_findings": top_findings, "failure_impact": failure_impact,
    "chokepoints": chokepoints, "architecture_coverage": architecture_coverage,
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
