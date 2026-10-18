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
    from cisco_toolkit import ui_projection
    base = graph.build_graph(snap)
    upper_snap = _upper_hostnames(snap)
    upper = graph.build_graph(upper_snap)
    assert base["topology"]["cables"]["items"]
    assert upper == ui_projection.project_tools_topology(upper_snap)
    assert upper["topology"] == ui_projection.project_topology(upper_snap)
    # Stored cable-map membership, including its case, is never rebuilt from CDP.
    assert upper["topology"]["cables"] == base["topology"]["cables"]
    assert upper["topology"]["nodes"] == base["topology"]["nodes"]
    assert len(upper["edges"]) == len(base["edges"])
    assert {n["id"] for n in upper["nodes"]} == {n["id"] for n in base["nodes"]}


def test_an_unmeasured_link_is_not_reported_as_redundant(snap):
    measured = graph.build_graph(snap)
    assert measured["topology"]["structural_links"]["state"] == "published"
    assert any(row["is_bridge"]["value"] is True for row in measured["topology"]["structural_links"]["items"])
    stripped = json.loads(json.dumps(snap))
    stripped.pop("link_centrality")
    unmeasured = graph.build_graph(stripped)
    assert unmeasured["topology"]["cables"] == measured["topology"]["cables"]
    assert unmeasured["edges"]
    assert all(not e["bridge_assessed"] for e in unmeasured["edges"])
    assert unmeasured["topology"]["structural_links"]["state"] == "not_collected"
    assert unmeasured["topology"]["structural_links"]["items"] == []
    assert unmeasured["topology"]["structural_links"]["reason"]


def test_offscan_neighbours_are_disclosed_not_silently_dropped(snap):
    projected = graph.build_graph(snap)
    peers = [row for row in projected["topology"]["nodes"]["items"] if row["collected"]["value"] is False]
    assert peers
    assert any("wan-edge" in row["host"]["value"] for row in peers)
    assert all(row["style"]["value"]["token"] == "uncollected" for row in peers)
    assert not any(row["collected"]["value"] is True for row in peers)

    assert {row["host"]["value"] for row in peers} == set(projected["offscan_peers"])
    assert set(projected["offscan_peers"]) <= {node["id"] for node in projected["nodes"]}


@pytest.mark.parametrize("mutation", ["duplicate_node", "unreadable_node", "missing_cables", "unjoinable_cable"])
def test_unknown_membership_refuses_the_diagram_instead_of_zero_degrees(snap, mutation):
    candidate = json.loads(json.dumps(snap))
    if mutation == "duplicate_node":
        candidate["cable_map"]["nodes"].append(dict(candidate["cable_map"]["nodes"][0]))
    elif mutation == "unreadable_node":
        candidate["cable_map"]["nodes"][0]["host"] = None
    elif mutation == "missing_cables":
        candidate["cable_map"].pop("cables")
    else:
        candidate["cable_map"]["cables"][0]["a"] = "synthetic-never-observed"
    result = graph.build_graph(candidate)
    assert result["nodes"] == [] and result["edges"] == []
    assert result["diagram"]["state"] != "published"
    assert result["diagram"]["value"] is None and result["diagram"]["reason"]


def test_diagram_degrees_and_bridge_cells_are_owned_by_the_projected_topology(snap):
    result = graph.build_graph(snap)
    assert result["nodes"] and result["edges"]
    owner = result["topology"]
    cables = {frozenset((r["ends"]["value"]["a"], r["ends"]["value"]["b"]))
              for r in owner["cables"]["items"]}
    edges = {frozenset((r["source"], r["target"])) for r in result["edges"]}
    assert edges == cables
    for node in result["nodes"]:
        assert node["degree"] == sum(node["id"] in pair for pair in cables)
        assert node["keystone"] is None, "An obsolete summary badge cannot become a measured false"
