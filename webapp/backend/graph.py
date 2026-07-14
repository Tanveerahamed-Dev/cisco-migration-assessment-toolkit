"""Derive a switch-topology graph (nodes + edges) from a snapshot, for the cockpit's force-graph view.

Read-only projection: nodes come from the health scores / inventory (so each carries its health band,
score, and role); edges come from per-interface CDP neighbours, canonicalised with the engine's own
`_canon_host` so hosts group identically to the rest of the toolkit, then de-duplicated undirected and
enriched with bridge / pairs-cut info from `link_centrality`. Non-switch CDP neighbours (APs, phones)
are dropped so the graph is the inter-switch fabric, matching what the deep explorer draws.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import engine


def build_graph(snap: Dict[str, Any], keystones: Optional[List[str]] = None) -> Dict[str, Any]:
    canon = engine.canon_host
    # isinstance-guard, not `or {}`: a TRUTHY non-dict (a JSON string/list in a malformed upload that passed the
    # 'devices' in snap gate) would slip through `or {}` and crash .keys() -> an unhandled 500 on /graph.
    _ifaces = snap.get("interfaces")
    ifaces = _ifaces if isinstance(_ifaces, dict) else {}
    _devices = snap.get("devices")
    devices = _devices if isinstance(_devices, dict) else {}
    # require a STRING 'switch' key: a row without one would inject a None node id and make sorted(node_ids)
    # raise TypeError (str vs None) -> an unhandled 500 on /graph (multi-domain audit #10).
    health = {r.get("switch"): r for r in (snap.get("health_scores") or [])
              if isinstance(r, dict) and isinstance(r.get("switch"), str)}
    node_ids = set(ifaces.keys()) | set(health.keys()) | set(devices.keys())
    ks = set(keystones or [])

    # Edges from CDP neighbours, undirected + de-duped, only between known switch nodes.
    seen: set = set()
    edges: List[Dict[str, Any]] = []
    for host, host_ifaces in ifaces.items():
        if not isinstance(host_ifaces, dict):
            continue
        for _name, d in host_ifaces.items():
            if not isinstance(d, dict):
                continue
            nb = str(d.get("cdp_neighbor") or "").strip()   # tolerate a wrong-typed cdp_neighbor (list/int) -> never 500s /graph
            if not nb:
                continue
            target = canon(nb)
            if not target or target == host or target not in node_ids:
                continue
            key = tuple(sorted((host, target)))
            if key in seen:
                continue
            seen.add(key)
            edges.append({"source": key[0], "target": key[1]})

    # Enrich edges with bridge / pairs-cut from link_centrality (matched undirected).
    lc: Dict[tuple, dict] = {}
    for e in (snap.get("link_centrality") or []):
        if isinstance(e, dict) and e.get("a_host") and e.get("b_host"):
            lc[tuple(sorted((e["a_host"], e["b_host"])))] = e

    degree: Dict[str, int] = {}
    for e in edges:
        degree[e["source"]] = degree.get(e["source"], 0) + 1
        degree[e["target"]] = degree.get(e["target"], 0) + 1
        m = lc.get(tuple(sorted((e["source"], e["target"]))))
        e["is_bridge"] = bool(m.get("is_bridge")) if m else False
        e["pairs_cut"] = engine.as_num(m.get("pairs_cut")) if m else 0   # fail-soft: a JSON Infinity would 500 /graph

    nodes: List[Dict[str, Any]] = []
    for nid in sorted(node_ids):
        r = health.get(nid, {})
        nodes.append({
            "id": nid,
            "band": r.get("band", ""),
            "score": r.get("score"),
            "role": r.get("role", ""),
            "degree": degree.get(nid, 0),
            "keystone": nid in ks,
        })

    return {"nodes": nodes, "edges": edges}


def cable_map_from_snapshot(snap: Dict[str, Any]) -> Dict[str, Any]:
    """EDA-style physical cable map for the webapp cable-map view.

    Thin pass-through to the engine's cable_map_of_snapshot — the ONE rehydration SSOT the
    --compare delta also uses: prefer the engine-computed snap['cable_map'], else recompute from
    the stored interface evidence so pre-feature uploads still render. Coverage-honest either
    way — an uncollected device stays [NOT OBSERVED], never a fake green.
    """
    return engine.cable_map_of_snapshot(snap)
