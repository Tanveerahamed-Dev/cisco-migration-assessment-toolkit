"""The fleet-topology projection must not present absent evidence as a healthy fabric.

`/graph` feeds the cockpit's TopologyGraph panel — the picture an engineer reads before signing off
blast-radius review, and a picture is trusted more than a table. Three defects found in the
whole-repo review (2026-07-28) all rendered as the same reassuring image: a fabric with no
chokepoints.

The fixtures are built from the SHIPPED sample fleet, not hand-authored, so the matcher is exercised
against a real producer artifact.
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `backend` importable

from backend import graph  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLE = os.path.join(ROOT, "webapp", "sample_data", "sample_fleet.snapshot.json")

pytestmark = pytest.mark.skipif(not os.path.isfile(SAMPLE),
                                reason="shipped sample fleet snapshot not present")


@pytest.fixture(scope="module")
def snap():
    with open(SAMPLE, encoding="utf-8") as fh:
        return json.load(fh)


def _upper_hostnames(s):
    """Upper-case ONLY hostnames — the `interfaces`/`devices` top-level keys, `health_scores.switch`,
    `cdp_neighbor` values and the `link_centrality` endpoints. Field names are deliberately left
    alone: an earlier probe recursed into them, renamed `cdp_neighbor` itself, and 'reproduced' the
    bug for entirely the wrong reason."""
    o = json.loads(json.dumps(s))
    o["interfaces"] = {h.upper(): v for h, v in (o.get("interfaces") or {}).items()}
    o["devices"] = {h.upper(): v for h, v in (o.get("devices") or {}).items()}
    for r in o.get("health_scores") or []:
        if isinstance(r, dict) and isinstance(r.get("switch"), str):
            r["switch"] = r["switch"].upper()
    for ifs in (o.get("interfaces") or {}).values():
        for d in (ifs or {}).values():
            if isinstance(d, dict) and isinstance(d.get("cdp_neighbor"), str):
                d["cdp_neighbor"] = d["cdp_neighbor"].upper()
    for e in o.get("link_centrality") or []:
        if isinstance(e, dict):
            for k in ("a_host", "b_host"):
                if isinstance(e.get(k), str):
                    e[k] = e[k].upper()
    return o


def test_hostname_case_does_not_erase_the_fabric(snap):
    """`node_ids` held RAW snapshot keys while the neighbour was resolved through `canon()`, which
    lower-cases. So on any fleet whose hostnames are not already lower-case — MERIDIAN-CORE-01 /
    MERIDIAN-ACC-14, i.e. the Cisco norm — every neighbour failed the membership test and the graph came
    back with ZERO edges. That does not surface as an error: it draws every switch unlinked with an
    EMPTY single-point-of-failure overlay, while the cable map directly below draws the real
    topology (it resolves through a canon map, which is the idiom now copied here)."""
    base = graph.build_graph(snap)
    assert base["edges"], "precondition: the shipped sample must resolve a fabric"

    upper = graph.build_graph(_upper_hostnames(snap))
    assert len(upper["edges"]) == len(base["edges"]), (
        f"a pure hostname CASE change moved the edge count "
        f"{len(base['edges'])} -> {len(upper['edges'])}; the topology view and the cable map now "
        f"disagree about the same fleet")
    assert (sum(1 for e in upper["edges"] if e["is_bridge"])
            == sum(1 for e in base["edges"] if e["is_bridge"])), \
        "the single-point-of-failure overlay changed with hostname case"


def test_an_unmeasured_link_is_not_reported_as_redundant(snap):
    """`is_bridge` was `False` both for 'measured, this link is redundant' and for 'link_centrality
    was never computed'. With the section absent, every edge of the sample fleet came back False
    while 17 of them are genuine bridges — a fully grey fabric under a legend still advertising the
    red SPOF key. `bridge_assessed` is the third state the payload could not express."""
    measured = graph.build_graph(snap)
    assert measured["link_centrality_assessed"] is True
    assert any(e["is_bridge"] for e in measured["edges"]), \
        "precondition: the sample fleet must contain at least one measured bridge"
    assert all(e["bridge_assessed"] for e in measured["edges"])

    stripped = json.loads(json.dumps(snap))
    stripped.pop("link_centrality", None)
    unmeasured = graph.build_graph(stripped)
    assert unmeasured["edges"], "precondition: edges still resolve without link_centrality"
    assert unmeasured["link_centrality_assessed"] is False, \
        "a snapshot with no link_centrality must SAY so, not imply every link was checked"
    assert not any(e["bridge_assessed"] for e in unmeasured["edges"]), \
        "edges claim to have been assessed for bridge-ness when the section was never computed"


def test_offscan_neighbours_are_disclosed_not_silently_dropped(snap):
    """Dropping non-switch CDP peers keeps this an INTER-SWITCH fabric, which is the intent. But it
    also dropped genuine infrastructure without saying so: on the shipped sample that includes
    `wan-edge-rtr1.lab`, so the topology showed an estate with no WAN egress while the cable map
    listed it as an `uncollected` peer. The two views disagreed and neither said why."""
    g = graph.build_graph(snap)
    assert "offscan_peers" in g, "the projection must report what it dropped"
    assert any("wan-edge" in p for p in g["offscan_peers"]), (
        f"the WAN edge router is dropped from the fabric with no disclosure: "
        f"{g['offscan_peers']}")
    # ...and a peer that IS collected must never be reported as off-scan.
    node_ids = {n["id"] for n in g["nodes"]}
    assert not (set(g["offscan_peers"]) & node_ids), \
        "a collected device was reported as an off-scan peer"
