"""[audit-6 leaf-coercion crash batch -- webapp] The UNAUTHENTICATED /graph + /cable_map endpoints call these
graph functions UNWRAPPED (app.py:384/393), so a wrong-typed cdp_neighbor / status / port_channel (a list/int
in a malformed or hostile upload) that reaches a .strip()/.lower() escapes as an unhandled HTTP 500. Each must
degrade, never raise. (Unique basename vs the engine-side tests/test_audit6_leaf_coercion.py: pytest derives
the module name from the filename.)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `backend` importable

INF = float("inf")


def test_build_graph_tolerates_wrongtyped_cdp_neighbor_and_infinite_pairs_cut():
    """[#3] /graph -> build_graph did `(d.get('cdp_neighbor') or '').strip()`; a truthy non-str cdp_neighbor
    (a list/int) slips past `or ''` -> AttributeError -> unhandled 500. str()-coerced now. ALSO the edge
    enrichment did a raw `int(link_centrality.pairs_cut)` -> OverflowError on a JSON Infinity (audit-6 fuzz)."""
    from backend import graph
    # NB lowercase hostnames: build_graph canonicalises neighbours with the engine's _canon_host, which
    # LOWERCASES -- so the sw2->sw1 neighbour must resolve to a lowercase node id for the sw1<->sw2 EDGE to
    # form. Without an edge, the link_centrality/pairs_cut enrichment (graph.py:65) never runs and the
    # pairs_cut assertion would be VACUOUS (reverting the fix would still pass).
    snap = {
        "interfaces": {"sw1": {"Gi1/0/1": {"cdp_neighbor": ["sw2"]},   # wrong-typed (list) -> str-coerced
                               "Gi1/0/2": {"cdp_neighbor": 7}},         # wrong-typed (int) -> str-coerced
                       "sw2": {"Gi0/1": {"cdp_neighbor": "sw1"}}},       # valid -> forms the sw1<->sw2 edge
        "health_scores": [{"switch": "sw1", "band": "Healthy"}, {"switch": "sw2", "band": "Critical"}],
        "devices": {"sw1": {}, "sw2": {}},
        "link_centrality": [{"a_host": "sw1", "b_host": "sw2", "is_bridge": True, "pairs_cut": INF}],
    }
    g = graph.build_graph(snap, [])
    assert isinstance(g, dict) and "nodes" in g
    assert g["edges"], "fixture must form an edge so the pairs_cut (graph.py:65) fix is actually exercised"


def test_summarize_tolerates_infinite_stranded_on_upload():
    """[#1-class, UNAUTHENTICATED UPLOAD] summarize() runs on every POST /snapshots; _keystones sorted with a
    raw `-int(stranded)` -> OverflowError on a JSON Infinity (the highest-exposure instance of finding #1's
    pattern, surfaced by the audit-6 fuzz). Routed through the shared fail-soft coercer now."""
    from backend.summary import summarize
    s = summarize({"devices": {"SW1": {}},
                   "failure_impact": [{"host": "SW1", "stranded": INF, "severity": "High"}]})
    assert isinstance(s, dict)


def test_cutover_build_plan_tolerates_malformed_counts():
    """[reachable-class sibling] /cutover -> cutover.build_plan -> summary._keystones + cutover._int; both
    coerced a device count without catching OverflowError. A JSON Infinity 500'd /cutover. Fixed."""
    from backend import cutover
    snap = {"devices": {"SW1": {}},
            "failure_impact": [{"host": "SW1", "stranded": INF, "severity": "High"}],
            "move_groups": [{"name": "g1", "switches": ["SW1"], "endpoints": INF}],
            "migration_readiness": [{"group": "g1", "readiness": "READY"}]}
    p = cutover.build_plan(snap)
    assert isinstance(p, dict)


def test_cable_map_from_snapshot_tolerates_wrongtyped_interface_fields():
    """[#3] /cable_map -> cable_map_from_snapshot -> analyze.cable_map_of_snapshot; a wrong-typed cdp_neighbor
    / status / neighbor_port / port_channel raised AttributeError -> unhandled 500. str()-coerced now."""
    from backend import graph
    snap = {"interfaces": {
        "SW1": {"Gi1/0/1": {"cdp_neighbor": ["SW2"], "endpoint_type": "Switch",
                            "neighbor_port": ["Gi2"], "status": 1, "port_channel": ["Po1"]}},
        "SW2": {"Gi2": {"cdp_neighbor": 7, "endpoint_type": "Switch", "neighbor_port": 5,
                        "status": {"x": 1}, "port_channel": 99}},
    }}
    cm = graph.cable_map_from_snapshot(snap)
    assert isinstance(cm, dict) and "nodes" in cm
