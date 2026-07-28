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
    # isinstance-guard over `or []` (as _ifaces/_devices above): a TRUTHY non-list health_scores (an int in a
    # malformed upload) survives `or []` and 500s the `for r in` iteration -> unhandled 500 on /graph.
    _health_scores = snap.get("health_scores")
    health = {r.get("switch"): r for r in (_health_scores if isinstance(_health_scores, list) else [])
              if isinstance(r, dict) and isinstance(r.get("switch"), str)}
    node_ids = set(ifaces.keys()) | set(health.keys()) | set(devices.keys())
    ks = set(keystones or [])

    # CANONICAL -> RAW node id. Both sides of the comparison must live in the same namespace, and
    # they did not: `node_ids` holds RAW snapshot keys while `target` came back from `canon()`, which
    # lower-cases (engine.canon_host('[HISTORY-REDACTED]-CORE-01.lab') -> '[HISTORY-REDACTED]-core-01'). So on any fleet whose
    # hostnames are not already lower-case -- [HISTORY-REDACTED]-CORE-01 / [HISTORY-REDACTED]-ACC-14, i.e. the Cisco norm -- EVERY
    # neighbour failed the `target not in node_ids` test and the graph came back with ZERO edges.
    # Measured on the shipped sample fleet: 23 nodes / 25 edges as stored, 23 nodes / 0 edges with
    # the same fleet upper-cased. That does not render as an error; it renders as a fabric of
    # unlinked switches with an EMPTY single-point-of-failure overlay, while the cable map directly
    # below draws the real topology (it resolves through a canon map -- analyze.py `scanned_map` --
    # which is the idiom copied here). Absence of resolvable evidence presented as an absence of
    # chokepoints is the one thing this codebase's doctrine forbids.
    by_canon: Dict[str, str] = {}
    for raw in sorted(node_ids):                  # sorted -> deterministic winner on a canon collision
        by_canon.setdefault(canon(raw) or raw, raw)

    # Edges from CDP neighbours, undirected + de-duped, only between known switch nodes.
    seen: set = set()
    edges: List[Dict[str, Any]] = []
    offscan: set = set()
    for host, host_ifaces in ifaces.items():
        if not isinstance(host_ifaces, dict):
            continue
        for _name, d in host_ifaces.items():
            if not isinstance(d, dict):
                continue
            nb = str(d.get("cdp_neighbor") or "").strip()   # tolerate a wrong-typed cdp_neighbor (list/int) -> never 500s /graph
            if not nb:
                continue
            ckey = canon(nb)
            if not ckey:
                continue
            target = by_canon.get(ckey)
            if target is None:
                # A neighbour this snapshot never collected. Dropping it keeps the view an
                # INTER-SWITCH fabric (the docstring's intent: APs and phones do not belong here),
                # but silently dropping it also removed genuine infrastructure -- on the shipped
                # sample that includes wan-edge-rtr1.lab, so the topology showed an estate with no
                # WAN egress while the cable map listed it as an `uncollected` peer. Report them so
                # the surface can disclose the difference rather than the two views just disagreeing.
                offscan.add(nb)
                continue
            if target == host:
                continue
            key = tuple(sorted((host, target)))
            if key in seen:
                continue
            seen.add(key)
            edges.append({"source": key[0], "target": key[1]})

    # Enrich edges with bridge / pairs-cut from link_centrality (matched undirected).
    lc: Dict[tuple, dict] = {}
    # isinstance-guard over `or []`: a TRUTHY non-list link_centrality (an int in a malformed upload) survives
    # `or []` and 500s the `for e in` iteration -> unhandled 500 on /graph.
    _link_centrality = snap.get("link_centrality")
    for e in (_link_centrality if isinstance(_link_centrality, list) else []):
        if isinstance(e, dict) and e.get("a_host") and e.get("b_host"):
            lc[tuple(sorted((e["a_host"], e["b_host"])))] = e

    degree: Dict[str, int] = {}
    for e in edges:
        degree[e["source"]] = degree.get(e["source"], 0) + 1
        degree[e["target"]] = degree.get(e["target"], 0) + 1
        m = lc.get(tuple(sorted((e["source"], e["target"]))))
        # `is_bridge` stays a plain bool so the existing consumers keep working, but it can no longer
        # be read as a VERDICT on its own: `else False` means "we did not measure this link", and it
        # was rendering identically to a measured "this link is redundant". With `link_centrality`
        # absent entirely -- an older snapshot, or a run where the section was not computed -- all 25
        # edges of the sample fleet came back False while 17 of them are genuine bridges, so the SVG
        # drew a fully grey fabric under a legend still advertising the red single-point-of-failure
        # key. `bridge_assessed` is the third state the payload had no way to express.
        e["bridge_assessed"] = m is not None
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

    return {
        "nodes": nodes,
        "edges": edges,
        # Coverage, so the surface can tell "measured redundant" from "never measured" and
        # "no neighbours" from "neighbours we could not resolve". Both were previously
        # indistinguishable from a healthy fabric.
        "link_centrality_assessed": bool(lc),
        "offscan_peers": sorted(offscan),
    }


def cable_map_from_snapshot(snap: Dict[str, Any]) -> Dict[str, Any]:
    """EDA-style physical cable map for the webapp cable-map view.

    Thin pass-through to the engine's cable_map_of_snapshot — the ONE rehydration SSOT the
    --compare delta also uses: prefer the engine-computed snap['cable_map'], else recompute from
    the stored interface evidence so pre-feature uploads still render. Coverage-honest either
    way — an uncollected device stays [NOT OBSERVED], never a fake green.
    """
    return engine.cable_map_of_snapshot(snap)
