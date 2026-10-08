"""W33 (follow-up F5): the ENGINE owns row-level failure-impact assessability.

``cisco_toolkit/impact_assessability.py`` is the one owner of the rules that decide whether a stored
``failure_impact`` row is a measurement: the producer's INDETERMINATE detail, a row older than its
``off_scan_gw_vlans`` marker, an unreadable off-scan count or host, a device whose scoped interface running-config
was not captured (``run_config_observed``), a positive off-scan count with nothing simulated, a partial simulation,
an uncollected neighbour that can carry endpoints (read from the stored cable map), and two rows naming one host.
It never re-simulates.

Three things are pinned here:

1. **The owner's predicates**, each driven by the REAL producers (``analyze.compute_failure_impact`` and
   ``analyze.compute_cable_map`` over constructed fleets), never by a hand-written row in the shape the owner expects.
2. **Projection parity.** ui_projection's shared row builder consumes the owner and must keep every pre-refactor
   state, reason and witness byte for byte: the full reason texts below are copied from ui_projection at origin/main
   d0e10888 (before W33), and the owner's verdict on each cell must equal the projection's state.
3. **The engine deliverables** (the workbook's Failure Impact and Executive Summary sheets, the design document, the
   executive deck, the architecture review, the device dossier and the explorer embed) read the same verdict: an
   INDETERMINATE, held or neighbour-bounded row never renders as Info / no impact / 0, and never ranks as a keystone.

No test here runs a pipeline.
"""
from __future__ import annotations

import ast
import copy
import json
import math
import pathlib
import re
import shutil
import subprocess
from dataclasses import asdict

import pytest

from cisco_toolkit import analyze
from cisco_toolkit import impact_assessability as ia
from cisco_toolkit import ui_projection as ui
from cisco_toolkit.model import InterfaceData

ROOT = pathlib.Path(__file__).resolve().parent.parent
OWNER = ROOT / "cisco_toolkit" / "impact_assessability.py"
PUB, CBE, NC, AU, UV = "published", "collected_but_empty", "not_collected", "analysis_unavailable", "unverified"
MEASURES = ("severity", "vlans_impacted", "stranded", "hard", "backup", "fhrp")

# --------------------------------------------------------------------------------------------------
# the pre-refactor reasons, copied verbatim from cisco_toolkit/ui_projection.py at origin/main d0e10888
# --------------------------------------------------------------------------------------------------
PRE_INDETERMINATE = ("not collected: analyze.compute_failure_impact could not simulate this switch's blast "
                     "radius (its detail says why), so its severity and counts are not measurements")
PRE_LEGACY = ("not collected: this stored row carries no off_scan_gw_vlans, so it predates the producer's "
              "assessability marker (analyze.compute_failure_impact). An engine that old wrote 'No reachability "
              "impact' with Info and zero counts for a switch it could not simulate, so this row's severity and "
              "counts are not measurements")
PRE_OFF_SCAN_ONLY = ("not collected: every VLAN analyze.compute_failure_impact found on this switch has an "
                     "off-scan gateway (1 counted in off_scan_gw_vlans), so it simulated none of them and its "
                     "severity and counts are not measurements")
PRE_OFF_SCAN_UNREAD = ("unverified: off_scan_gw_vlans is not a count, so whether the simulation covered this "
                       "switch's whole blast radius cannot be read")
PRE_NO_RUN_CONFIG = ("not collected: no interface of this device carries run_config_observed: true. build.py "
                     "marks every interface its scoped interface running-config capture ('show running-config "
                     "interface' or '| section ^interface') parsed, and takes SVI gateway addresses (svi_ip) "
                     "only from that capture, so this device's own gateways never reached the simulation and "
                     "its severity and counts are not measurements. A snapshot that predates the marker, or "
                     "drops it as false (html.sparsify_interfaces), reads the same: not captured")
PRE_UNDERSTATED = ("not collected: this severity may understate the blast radius: 1 VLAN(s) on this switch "
                   "have an off-scan gateway the simulation could not assess (off_scan_gw_vlans), and only the "
                   "worst band (High) cannot be understated")
PRE_ZERO_BOUND = ("not collected: this 0 is only a lower bound: 1 VLAN(s) on this switch have an off-scan "
                  "gateway the simulation could not assess (off_scan_gw_vlans), so it is not a measurement of "
                  "none")
PRE_PEER_CLAUSE = ("this row cannot account for endpoints behind 1 uncollected neighbour(s): the stored cable map "
                   "cables this switch to 1 peer(s) it does not show as collected that can carry endpoints or "
                   "transit (a cable_map.nodes row with collected: false and a kind other than ap, phone or endpoint, "
                   "or a cable end that does not join exactly one node), and analyze.compute_failure_impact "
                   "counts only endpoints on scanned switches")
PRE_PEER_SEVERITY = ("not collected: " + PRE_PEER_CLAUSE + ", so this severity may understate the blast radius, "
                     "and only the worst band (High) cannot be understated")
PRE_PEER_ZERO = "not collected: " + PRE_PEER_CLAUSE + ", so this 0 is only a lower bound, not a measurement of none"
PRE_PEER_DETAIL = ("not collected: " + PRE_PEER_CLAUSE + ", so this detail, which names no simulated VLAN, is not a "
                   "clean bill: it was never checked against what lies behind them")
PRE_DUP = ("unverified: 2 rows in failure_impact name this exact host, but analyze.compute_failure_impact "
           "writes one row per host, so no single row can be chosen")


# --------------------------------------------------------------------------------------------------
# fleets for the REAL producers (copied from tests/test_ui_projection_device_impact.py, not imported)
# --------------------------------------------------------------------------------------------------
def _trunk(port, peer, peer_port, vlans="", blocked=""):
    return InterfaceData(port=port, status="connected", switchport_mode="Trunk", cdp_neighbor=peer,
                         neighbor_port=peer_port, endpoint_type="Switch", trunk_allowed_vlans=vlans,
                         stp_fwd_vlans="" if blocked else vlans, stp_blk_vlans=blocked, run_config_observed=True)


def _access(port, vid, mac):
    return InterfaceData(port=port, status="connected", switchport_mode="Access", vlan=str(vid), end_host_mac=mac,
                         run_config_observed=True)


def _svi(vid, address, fhrp=""):
    return InterfaceData(port=f"Vlan{vid}", svi_ip=address, hsrp_behavior=fhrp, run_config_observed=True)


def _edge(port, peer, endpoint_type, platform=""):
    return InterfaceData(port=port, status="connected", switchport_mode="Trunk", cdp_neighbor=peer,
                         neighbor_port="Gi0/1", endpoint_type=endpoint_type, neighbor_platform=platform,
                         trunk_allowed_vlans="10", stp_fwd_vlans="10", run_config_observed=True)


def _mixed_fleet(peer="dsw", endpoint_type="Switch", platform=""):
    """`gw` gateways VLAN 10 for `acc` (removing `gw` is a measured hard partition: High, 1 stranded) and trunks up to
    the router `wan`; `acc` trunks down to `peer`; the collection reached neither. `x1` and `x2` share a trunk with
    no VLAN-carriage evidence on either end, so the producer writes its INDETERMINATE disclosure for both."""
    return {"gw": {"Gi1": _trunk("Gi1", "acc", "Gi1", "10"),
                   "Gi47": _edge("Gi47", "wan", "Router", "cisco ISR4331/K9"), "Vlan10": _svi(10, "10.10.0.1/24")},
            "acc": {"Gi1": _trunk("Gi1", "gw", "Gi1", "10"), "Gi10": _access("Gi10", 10, "0000.0000.000a"),
                    "Gi48": _edge("Gi48", peer, endpoint_type, platform)},
            "x1": {"Gi1": _trunk("Gi1", "x2", "Gi1")}, "x2": {"Gi1": _trunk("Gi1", "x1", "Gi1")}}


def _offscan_fleet():
    """`g1` and `g2` are FHRP peers gatewaying VLAN 10 for `acc` (removing either is FHRP-covered: Low); both also
    carry VLAN 20 to `acc`, whose gateway was never scanned. `acc` carries only what it cannot simulate."""
    return {"g1": {"Gi1": _trunk("Gi1", "acc", "Gi1", "10,20"), "Vlan10": _svi(10, "10.10.0.2/24", "Active")},
            "g2": {"Gi1": _trunk("Gi1", "acc", "Gi2", "10,20"), "Vlan10": _svi(10, "10.10.0.3/24", "Standby")},
            "acc": {"Gi1": _trunk("Gi1", "g1", "Gi1", "10,20"), "Gi2": _trunk("Gi2", "g2", "Gi1", "10,20"),
                    "Gi10": _access("Gi10", 10, "0000.0000.000a"), "Gi20": _access("Gi20", 20, "0000.0000.0014")}}


def _snapshot(interfaces):
    """The real producers' rows over `interfaces`, in the snapshot's own shape."""
    return {"schema": "collect_parse_snapshot/1", "devices": {host: {"hostname": host} for host in interfaces},
            "interfaces": {host: {port: asdict(row) for port, row in ports.items()}
                           for host, ports in interfaces.items()},
            "failure_impact": analyze.compute_failure_impact(interfaces),
            "cable_map": analyze.compute_cable_map(interfaces), "routes": {}}


def _k(snap, host):
    return next(i for i, row in enumerate(snap["failure_impact"]) if row.get("host") == host)


def _verdicts(snap):
    return {v.index: v for v in ia.assess_failure_impact(snap)}


def _node(snap, host):
    same = [n for n in snap["cable_map"]["nodes"] if n["host"] == host]
    assert len(same) == 1, (host, same)
    return same[0]


@pytest.fixture()
def mixed():
    return _snapshot(_mixed_fleet())


# --------------------------------------------------------------------------------------------------
# 1. the owner's predicates over the REAL producers
# --------------------------------------------------------------------------------------------------
def test_the_indeterminate_marker_is_the_real_producers_opening(mixed):
    """Both INDETERMINATE branches of analyze.compute_failure_impact open with the owner's marker, and the
    projection re-exports the owner's constant rather than keeping its own."""
    assert ui.IMPACT_INDETERMINATE_PREFIX is ia.IMPACT_INDETERMINATE_PREFIX
    assert ui.IMPACT_SEVERITIES is ia.IMPACT_SEVERITIES
    source = pathlib.Path(analyze.__file__).read_text(encoding="utf-8")
    assert source.count(f'f"{ia.IMPACT_INDETERMINATE_PREFIX} —') == 2
    for host in ("x1", "x2"):
        row = mixed["failure_impact"][_k(mixed, host)]
        assert row["detail"].startswith(ia.IMPACT_INDETERMINATE_PREFIX) and row["severity"] == "Info", row
        assert all(row[f] == 0 for f in MEASURES[1:]), row                    # zeros that look like measurements
    offscan = _snapshot(_offscan_fleet())
    row = offscan["failure_impact"][_k(offscan, "acc")]
    assert row["detail"].startswith(ia.IMPACT_INDETERMINATE_PREFIX) and row["off_scan_gw_vlans"] == 1, row


def test_each_verdict_from_the_real_producers(mixed):
    v = _verdicts(mixed)
    gw, acc, x1, x2 = (v[_k(mixed, h)] for h in ("gw", "acc", "x1", "x2"))
    for held in (x1, x2):                                    # the producer's own INDETERMINATE disclosure
        assert held.assessable == ia.NOT_ASSESSED and held.codes == ["indeterminate"], held.as_dict()
        assert all(held.withholds(f) for f in MEASURES)
        assert not held.withholds("detail")                  # its disclosure stays readable
        assert held.facts.hold.reason == PRE_INDETERMINATE
    # acc: the producer's clean bill, but it is cabled to an uncollected switch
    assert _node(mixed, "dsw")["collected"] is False and _node(mixed, "dsw")["kind"] == "switch"
    assert acc.assessable == ia.LOWER_BOUND and acc.codes == ["uncollected_neighbours"], acc.as_dict()
    assert all(acc.withholds(f) for f in MEASURES) and acc.withholds("detail")   # Info, zeros, clean-bill detail
    # gw: High, one stranded, cabled to an uncollected router: High and the positive counts are lower bounds
    src = mixed["failure_impact"][_k(mixed, "gw")]
    assert src["severity"] == "High" and src["stranded"] == src["hard"] == src["vlans_impacted"] == 1, src
    assert gw.assessable == ia.LOWER_BOUND, gw.as_dict()
    assert [f for f in MEASURES if gw.withholds(f)] == ["backup", "fhrp"]
    assert not gw.withholds("detail")                        # a per-VLAN detail lists what was simulated
    assert ia.table_value(gw, "severity") == "High (lower bound)" and ia.table_value(gw, "stranded") == "≥ 1"
    # the control: once the stored cable map shows the router collected, gw is the producer's measurement
    _node(mixed, "wan")["collected"] = True
    gw = _verdicts(mixed)[_k(mixed, "gw")]
    assert gw.assessable == ia.PUBLISHED and gw.summary == "published" and gw.codes == []
    assert not any(gw.withholds(f) for f in MEASURES + ("detail",))
    assert ia.table_value(gw, "stranded") == 1 and ia.table_detail(gw) == src["detail"]


def test_a_partial_simulation_is_a_lower_bound_and_off_scan_only_is_held():
    snap = _snapshot(_offscan_fleet())
    v = _verdicts(snap)
    g1 = v[_k(snap, "g1")]
    src = snap["failure_impact"][_k(snap, "g1")]
    assert src["severity"] == "Low" and src["off_scan_gw_vlans"] == 1 and src["vlans_impacted"] == 1, src
    assert g1.assessable == ia.LOWER_BOUND and g1.codes == ["off_scan_partial"], g1.as_dict()
    assert g1.withholds("severity") and not g1.withholds("vlans_impacted") and not g1.withholds("detail")
    acc = v[_k(snap, "acc")]
    assert acc.assessable == ia.NOT_ASSESSED and acc.codes == ["indeterminate"]
    # the same row without its prose marker: the count still says nothing was simulated
    snap["failure_impact"][_k(snap, "acc")]["detail"] = "No reachability impact from removing this switch."
    acc = _verdicts(snap)[_k(snap, "acc")]
    assert acc.codes == ["off_scan_only"] and acc.facts.hold.reason == PRE_OFF_SCAN_ONLY
    assert acc.withholds("detail")                             # a clean bill beside a hold is held with it


def test_holds_in_their_first_match_order(mixed):
    k = _k(mixed, "gw")
    _node(mixed, "wan")["collected"] = True                   # gw published: each mutation alone holds it
    row = mixed["failure_impact"][k]
    cases = []
    legacy = copy.deepcopy(mixed); del legacy["failure_impact"][k]["off_scan_gw_vlans"]
    cases.append((legacy, "legacy_row", NC, PRE_LEGACY, f"/failure_impact/{k}"))
    unread = copy.deepcopy(mixed); unread["failure_impact"][k]["off_scan_gw_vlans"] = "1"
    cases.append((unread, "off_scan_unreadable", UV, PRE_OFF_SCAN_UNREAD, f"/failure_impact/{k}/off_scan_gw_vlans"))
    nohost = copy.deepcopy(mixed); nohost["failure_impact"][k]["host"] = 7
    cases.append((nohost, "no_host", UV, ia.R_NO_HOST, f"/failure_impact/{k}"))
    norc = copy.deepcopy(mixed)
    for port in norc["interfaces"]["gw"].values():
        port.pop("run_config_observed", None)                 # what html.sparsify_interfaces writes for false
    cases.append((norc, "no_run_config", NC, PRE_NO_RUN_CONFIG, "/interfaces/gw"))
    marker_text = copy.deepcopy(mixed)
    for port in marker_text["interfaces"]["gw"].values():
        port["run_config_observed"] = "true"                  # present but not true reads as not captured
    cases.append((marker_text, "no_run_config", NC, PRE_NO_RUN_CONFIG, "/interfaces/gw"))
    gone = copy.deepcopy(mixed); del gone["interfaces"]["gw"]
    cases.append((gone, "no_run_config", NC, PRE_NO_RUN_CONFIG, "/interfaces"))
    for snap, code, state, reason, pointer in cases:
        v = _verdicts(snap)[k]
        assert v.assessable == ia.NOT_ASSESSED and v.codes == [code], (code, v.as_dict())
        assert v.facts.hold.state == state and v.facts.hold.reason == reason, code
        assert pointer in v.pointers, (code, v.pointers)
        assert all(v.withholds(f) for f in MEASURES + ("detail",)), code
    assert row["detail"] and not row["detail"].startswith(ia.IMPACT_INDETERMINATE_PREFIX)


@pytest.mark.parametrize("peer, platform, kind", [("ap1", "cisco AIR-AP2802I-E-K9", "ap"),
                                                   ("sep1", "Cisco IP Phone 8865", "phone")])
def test_uncollected_edge_gear_bounds_nothing_and_every_other_kind_does(peer, platform, kind):
    snap = _snapshot(_mixed_fleet(peer, "Switch", platform))
    k = _k(snap, "acc")
    assert _node(snap, peer)["collected"] is False and _node(snap, peer)["kind"] == kind
    assert _verdicts(snap)[k].assessable == ia.PUBLISHED
    for mutate in (lambda n: n.update(kind="unknown"), lambda n: n.pop("kind"), lambda n: n.update(kind="AP"),
                   lambda n: n.update(kind="device"), lambda n: n.pop("collected"),
                   lambda n: n.update(collected="false")):
        held = copy.deepcopy(snap)
        mutate(_node(held, peer))
        v = _verdicts(held)[k]
        assert v.assessable == ia.LOWER_BOUND and v.codes == ["uncollected_neighbours"], v.as_dict()
        assert v.facts.bounds[-1].severity_reason == PRE_PEER_SEVERITY


@pytest.mark.parametrize("mode, state", [("duplicate_node", NC), ("missing_node", NC), ("unreadable_cable", NC),
                                         ("malformed_cables", UV), ("absent_cables", NC), ("failed_cable_map", AU)])
def test_a_neighbour_the_join_cannot_resolve_fails_closed(mode, state):
    snap = _snapshot(_mixed_fleet("ap1", "Switch", "cisco AIR-AP2802I-E-K9"))
    k = _k(snap, "acc")
    assert _verdicts(snap)[k].assessable == ia.PUBLISHED
    nodes, cables = snap["cable_map"]["nodes"], snap["cable_map"]["cables"]
    if mode == "duplicate_node":
        nodes.append(copy.deepcopy(_node(snap, "ap1")))
    elif mode == "missing_node":
        nodes.remove(_node(snap, "ap1"))
    elif mode == "unreadable_cable":
        cables.append(None)
    elif mode == "malformed_cables":
        snap["cable_map"]["cables"] = 7
    elif mode == "absent_cables":
        del snap["cable_map"]["cables"]
    else:
        snap["assessment_integrity"] = {"cable_map": "failed"}
    v = _verdicts(snap)[k]
    assert v.assessable == ia.LOWER_BOUND, (mode, v.as_dict())
    assert v.facts.bounds[-1].state == state, mode
    code = "uncollected_neighbours" if mode in ("duplicate_node", "missing_node", "unreadable_cable") \
        else "neighbours_unreadable"
    assert v.codes == [code], (mode, v.codes)
    assert all(v.withholds(f) for f in MEASURES) and v.withholds("detail")


def test_two_rows_naming_one_host_are_ambiguous_never_picked(mixed):
    _node(mixed, "wan")["collected"] = True
    k = _k(mixed, "gw")
    mixed["failure_impact"].append(dict(mixed["failure_impact"][k], severity="Info", stranded=0))
    v = _verdicts(mixed)
    for i in (k, len(mixed["failure_impact"]) - 1):
        assert v[i].assessable == ia.AMBIGUOUS and v[i].codes == ["duplicate_host"], v[i].as_dict()
        assert v[i].facts.doubt.reason == PRE_DUP
        assert {f"/failure_impact/{k}", f"/failure_impact/{len(mixed['failure_impact']) - 1}"} <= set(v[i].pointers)
        assert all(v[i].withholds(f) for f in MEASURES + ("detail",)) and not v[i].withholds("host")
    # a case variant names another host: the key is exact text
    mixed["failure_impact"][-1]["host"] = "GW"
    assert _verdicts(mixed)[k].assessable == ia.PUBLISHED


def test_a_failed_section_reads_every_row_not_assessed(mixed):
    mixed["assessment_integrity"] = {"failed_phases": ["Failure Impact"]}
    verdicts = ia.assess_failure_impact(mixed)
    assert verdicts and all(v.assessable == ia.NOT_ASSESSED and v.codes == ["section_unavailable"] for v in verdicts)
    assert all(v.withholds(f) for v in verdicts for f in ia.IMPACT_FIELDS)


def test_verdict_pointers_resolve_and_the_document_is_aligned(mixed):
    doc = ia.assessment_document(mixed)
    assert doc["schema"] == ia.SCHEMA == "failure_impact_assessability/1"
    assert [r["index"] for r in doc["rows"]] == list(range(len(mixed["failure_impact"])))
    assert sum(doc["counts"].values()) == len(doc["rows"]) and set(doc["counts"]) == set(ia.VERDICTS)
    for row in doc["rows"]:
        assert row["assessable"] in ia.VERDICTS and set(row["codes"]) <= set(ia.CODE_PHRASES), row
        for pointer in row["pointers"]:
            node = mixed
            for tok in pointer.split("/")[1:]:
                tok = tok.replace("~1", "/").replace("~0", "~")
                node = node[int(tok)] if isinstance(node, list) else node[tok]
        assert set(row["withheld"]) <= set(ia.IMPACT_FIELDS)
        json.dumps(row, allow_nan=False)
    # the reader-facing reasons name no engine internals
    for phrase in ia.CODE_PHRASES.values():
        assert not re.search(r"analyze|compute_|build\.py|_gw_vlans|snapshot", phrase), phrase


@pytest.mark.parametrize("poison", [None, 7, "x", {"a": 1}, [None, 7, "x", [1], {"host": None}],
                                    [{"host": "h", "off_scan_gw_vlans": math.inf, "detail": 5}]])
def test_the_owner_is_total(poison):
    for snap in ({"failure_impact": poison}, {"failure_impact": poison, "interfaces": 5, "cable_map": [1]},
                 {"failure_impact": poison, "cable_map": {"cables": [None, {"a": 1}], "nodes": "x"}}):
        verdicts = ia.assess_failure_impact(snap)
        assert len(verdicts) == (len(poison) if isinstance(poison, list) else 0)
        assert not any(v.published for v in verdicts if not isinstance(v.raw, dict))
        json.dumps(ia.assessment_document(snap), allow_nan=False)


# --------------------------------------------------------------------------------------------------
# the owner never re-simulates and imports nothing but ssot
# --------------------------------------------------------------------------------------------------
SIMULATION_NAMES = frozenset({
    "compute_failure_impact", "compute_link_centrality", "build_network_model", "_topology_adjacency",
    "compute_topology_links", "compute_cable_map", "compute_causality_chains", "_vlan_components", "_link_carries",
    "_carry", "_link_has_vlan_evidence"})


def test_the_owner_never_names_a_topology_producer_and_imports_only_ssot():
    tree = ast.parse(OWNER.read_text(encoding="utf-8"))
    names = set()
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.update(f"{node.module}:{a.name}" for a in node.names)
    assert not names & SIMULATION_NAMES
    assert {"getattr", "__import__", "eval", "exec"}.isdisjoint(names)
    extra = {n for n in imported if not n.startswith(("typing:", "__future__:", "types:")) and n != "math"}
    assert extra == {"cisco_toolkit:ssot"}, extra
    # and the owner names no state of the protocol receipt (it is not one of its readers)
    assert "protocol_assessability" not in OWNER.read_text(encoding="utf-8")


# --------------------------------------------------------------------------------------------------
# 2. projection parity: the shared row builder consumes the owner, byte for byte as before W33
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("value", [0, 1, 2 ** 53 - 1, 2 ** 53, -1, 1.0, 2.5, math.inf, math.nan, True, False, None,
                                   "1", "", "core1", "\ud800", "café", [], {}])
def test_the_owner_value_checks_equal_the_projections(value):
    assert ia._count(value) == ui._count(value) or (value != value)      # NaN never equals itself
    assert ia._count(value)[0] == ui._count(value)[0]
    assert ia._is_text(value) == ui._is_text(value)
    assert ia.JS_MAX_SAFE_INT == ui.JS_MAX_SAFE_INT


def _cable_states(snap):
    ctx = ui._Ctx(snap)
    ui_state, _reason, _raw = ui._topology_source(ctx, ("cable_map", "cables"))
    src = ia.read_cable_source(snap)
    return (None if ui_state in (PUB, CBE) else ui_state if ui_state in (AU, UV) else NC), src.state


@pytest.mark.parametrize("cable_map", [
    {"nodes": [], "cables": []}, {"nodes": [], "cables": [{"a": "x", "b": "y"}]}, {"nodes": []}, None, 7, [],
    {"nodes": [], "cables": 7}, {"nodes": [], "cables": [None, {}]}, {"cables": [{"a": "x"}], "nodes": "n"}])
@pytest.mark.parametrize("integrity", [None, {"cable_map": "failed"}, {"failed_phases": ["Cable map"]},
                                       {"failed_phases": ["nobody classified this"]}])
def test_the_owners_cable_map_reading_follows_the_projections_list_states(cable_map, integrity):
    snap = {"failure_impact": [{"host": "x"}]}
    if cable_map is not None:
        snap["cable_map"] = cable_map
    if integrity is not None:
        snap["assessment_integrity"] = integrity
    projected, owned = _cable_states(snap)
    assert projected == owned, (cable_map, integrity, projected, owned)


def test_the_owners_joins_equal_the_projections(mixed):
    ctx = ui._Ctx(mixed)
    cables = mixed["cable_map"]["cables"] + [None, {"a": "gw"}, {"a": "gw", "b": "gw"}]
    mixed["cable_map"]["cables"] = cables
    assert ia.index_rows(cables, ("a", "b")) == ctx.index(("cable_map", "cables"), ("a", "b"))
    assert ia.unjoinable_rows(cables, ("a", "b")) == ui._unjoinable_rows(cables, ("a", "b"))
    assert ia.index_rows(mixed["failure_impact"], ("host",)) == ctx.index(("failure_impact",), ("host",))


def _reference_neighbour_join(snap, host):
    """The pre-W33 join loop of ui_projection._impact_peers (origin/main d0e10888), copied for parity: the bounding
    cable indices in iteration order, the far-end fail-closed map and the unreadable count."""
    cables = snap["cable_map"]["cables"]
    nodes = snap["cable_map"]["nodes"]
    index = ia.index_rows(nodes, ("host",))
    hits, peers, unreadable = [], {}, 0
    bad = set(ia.unjoinable_rows(cables, ("a", "b")))
    for j in sorted(set(ia.index_rows(cables, ("a", "b")).get(host, [])) | bad):
        if j in bad:
            hits.append(j)
            unreadable += 1
            continue
        ends = (cables[j]["a"], cables[j]["b"])
        far = ends[1] if ends[0] == host else ends[0]
        found = index.get(far, []) if far else []
        if len(found) == 1:
            node = nodes[found[0]]
            kind = node.get("kind")
            if node.get("collected") is True or (
                    node.get("collected") is False and ia._is_text(kind) and kind in ia.IMPACT_EDGE_KINDS):
                continue
        hits.append(j)
        peers[far] = peers.get(far, False) or len(found) != 1
    return hits, peers, unreadable


@pytest.mark.parametrize("extra", [
    [], [None], [{"a": "acc"}], [{"a": "acc", "b": 7}], [{"b": "gw"}, None, {"a": "x1", "b": "x1"}],
    [{"a": "acc", "b": "ghost"}, {"a": "ghost", "b": "acc"}], [{"a": "gw", "b": ""}]])
def test_the_neighbour_join_equals_the_pre_refactor_loop(mixed, extra):
    """The owner's join is restructured (readable rows first, the unreadable ones once per list), never re-ruled: for
    every host its witnesses, peer count and fail-closed count equal the pre-W33 loop, half-readable rows included."""
    mixed["cable_map"]["cables"] = mixed["cable_map"]["cables"] + extra
    src = ia.read_cable_source(mixed)
    for host in ("gw", "acc", "x1", "x2", "ghost"):
        hits, peers, unreadable = _reference_neighbour_join(mixed, host)
        bound = ia.neighbour_bound(host, src)
        if not hits:
            assert bound is None, (host, extra)
            continue
        closed = unreadable + sum(peers.values())
        clause = ia.R_PEERS.format(n=len(peers) + unreadable,
                                   closed=ia.R_PEERS_CLOSED.format(k=closed) if closed else "")
        assert bound.witnesses == [("witness", ("cable_map", "cables", j)) for j in hits], (host, extra)
        assert bound.reason == "not collected: " + clause and bound.n == len(peers) + unreadable, (host, extra)


def test_a_hostile_cable_list_keeps_verdicts_exact_and_witnesses_bounded(mixed):
    """A cable row the join cannot read bounds EVERY row. The deliverable verdicts keep their exact reasons and codes
    and cap only the witness pointers; the projection's uncapped reading keeps every witness."""
    mixed["cable_map"]["cables"] = mixed["cable_map"]["cables"] + [None] * 500
    exact = ia.ImpactSnapshot(mixed)                                   # no cap: the projection's reading
    for v in ia.assess_failure_impact(mixed):
        full = ia.RowVerdict(mixed, v.index, v.raw, exact.row(v.index, v.raw), None)
        assert (v.assessable, v.codes, v.reasons) == (full.assessable, full.codes, full.reasons), v.host
        assert len(v.pointers) <= 2 * ia.DELIVERABLE_WITNESS_CAP + 4, (v.host, len(v.pointers))
        assert [f for f in ia.IMPACT_FIELDS if v.withholds(f)] == [f for f in ia.IMPACT_FIELDS if full.withholds(f)]
    k = _k(mixed, "acc")
    assert len(exact.row(k, mixed["failure_impact"][k]).bounds[-1].witnesses) == 501   # dsw + every None row
    assert "501 uncollected neighbour(s)" in ia.assess_failure_impact(mixed)[k].reasons[0]


def _topology(snap):
    return ui.project_topology(snap)["failure_impact"]["items"]


def _refs(fact):
    return {(r["pointer"], r["role"]) for r in fact["refs"]}


def _assert_cells_follow_the_owner(snap):
    """Every measure and detail cell is withheld exactly when the owner's verdict withholds it (a well-typed row)."""
    rows = _topology(snap)
    for v in ia.assess_failure_impact(snap):
        for field in MEASURES + ("detail",):
            assert (rows[v.index][field]["state"] != PUB) == v.withholds(field), (v.host, field, v.as_dict())


def test_projection_reasons_and_witnesses_are_the_pre_refactor_ones(mixed):
    rows = _topology(mixed)
    _assert_cells_follow_the_owner(mixed)
    # INDETERMINATE: every measure held with the producer's detail as witness; the disclosure stays published
    for host in ("x1", "x2"):
        k = _k(mixed, host)
        for field in MEASURES:
            fact = rows[k][field]
            assert (fact["state"], fact["reason"]) == (NC, PRE_INDETERMINATE), (host, field)
            assert (f"/failure_impact/{k}/detail", "witness") in _refs(fact)
        assert rows[k]["detail"]["state"] == PUB
    # an uncollected neighbour: the exact severity / zero / clean-bill reasons and the cable witness
    k = _k(mixed, "acc")
    j = next(i for i, c in enumerate(mixed["cable_map"]["cables"]) if "dsw" in (c["a"], c["b"]))
    assert rows[k]["severity"]["reason"] == PRE_PEER_SEVERITY
    assert all(rows[k][f]["reason"] == PRE_PEER_ZERO for f in MEASURES[1:])
    assert rows[k]["detail"]["reason"] == PRE_PEER_DETAIL
    assert all((f"/cable_map/cables/{j}", "witness") in _refs(rows[k][f]) for f in MEASURES + ("detail",))
    # a partial simulation: the off-scan bound's understated / zero reasons
    snap = _snapshot(_offscan_fleet())
    rows = _topology(snap)
    _assert_cells_follow_the_owner(snap)
    k = _k(snap, "g1")
    assert rows[k]["severity"]["reason"] == PRE_UNDERSTATED
    assert rows[k]["stranded"]["reason"] == PRE_ZERO_BOUND
    assert (f"/failure_impact/{k}/off_scan_gw_vlans", "witness") in _refs(rows[k]["vlans_impacted"])


def test_projection_holds_and_doubts_are_the_pre_refactor_ones(mixed):
    _node(mixed, "wan")["collected"] = True
    k = _k(mixed, "gw")
    for mutate, reason, state in (
            (lambda s: s["failure_impact"][k].pop("off_scan_gw_vlans"), PRE_LEGACY, NC),
            (lambda s: s["failure_impact"][k].update(off_scan_gw_vlans="1"), PRE_OFF_SCAN_UNREAD, UV),
            (lambda s: [p.pop("run_config_observed", None) for p in s["interfaces"]["gw"].values()],
             PRE_NO_RUN_CONFIG, NC)):
        snap = copy.deepcopy(mixed)
        mutate(snap)
        row = _topology(snap)[k]
        _assert_cells_follow_the_owner(snap)
        for field in MEASURES + ("detail",):
            assert (row[field]["state"], row[field]["reason"]) == (state, reason), (reason[:30], field)
    snap = copy.deepcopy(mixed)
    snap["failure_impact"].append(copy.deepcopy(snap["failure_impact"][k]))
    rows = _topology(snap)
    for i in (k, len(snap["failure_impact"]) - 1):
        for field in ("host",) + MEASURES + ("detail",):
            assert (rows[i][field]["state"], rows[i][field]["reason"]) == (UV, PRE_DUP), (i, field)
    _assert_cells_follow_the_owner(snap)


def test_the_projection_reads_the_cable_list_through_its_own_envelope(mixed):
    """The projection injects its envelope reading of the cable list (reason text and failure records included):
    a failed cable map keeps the projection's own reason and its failure-record ref, as before W33."""
    _node(mixed, "wan")["collected"] = True
    mixed["assessment_integrity"] = {"cable_map": "failed"}
    k = _k(mixed, "acc")
    row = _topology(mixed)[k]
    fact = row["severity"]
    assert fact["state"] == AU and fact["reason"].startswith("analysis unavailable: whether this switch faces")
    assert "(analysis unavailable:" in fact["reason"]                          # the projection's own list reason
    assert ("/assessment_integrity/cable_map", "failure_record") in _refs(fact)


# --------------------------------------------------------------------------------------------------
# 3. the engine deliverables read the owner's verdict
# --------------------------------------------------------------------------------------------------
openpyxl = pytest.importorskip("openpyxl")


def _sheet_rows(ws):
    return [[c.value for c in row] for row in ws.iter_rows(min_row=2)]


def test_failure_impact_sheet_never_writes_info_or_zero_for_a_withheld_value(mixed):
    from openpyxl import Workbook
    from cisco_toolkit.excel import FAILURE_SHEET_NAME, write_failure_impact_sheet
    wb = Workbook()
    wb.active.title = "First"
    write_failure_impact_sheet(wb, mixed["failure_impact"])           # no evidence: every row is not assessed
    wb.create_sheet("Later")
    assert all(r[0] == ia.NOT_ASSESSED_CELL for r in _sheet_rows(wb[FAILURE_SHEET_NAME]))
    write_failure_impact_sheet(wb, mixed["failure_impact"], mixed)    # rewritten with the evidence, in place
    assert wb.sheetnames == ["First", FAILURE_SHEET_NAME, "Later"]
    rows = {r[1]: r for r in _sheet_rows(wb[FAILURE_SHEET_NAME])}
    for host in ("x1", "x2"):
        severity, _h, *counts, detail = rows[host]
        assert severity == ia.NOT_ASSESSED_CELL and counts == [ia.NOT_ASSESSED_CELL] * 5, rows[host]
        assert detail.startswith("Not assessed") and "Producer detail: Blast radius INDETERMINATE" in detail
    severity, _h, *counts, detail = rows["acc"]
    assert severity == ia.NOT_ASSESSED_CELL and counts == [ia.NOT_ASSESSED_CELL] * 5
    assert detail.startswith("Lower bound") and "No reachability impact" not in detail
    severity, _h, vlans, stranded, hard, backup, fhrp, detail = rows["gw"]
    assert severity == "High (lower bound)" and (vlans, stranded, hard) == ("≥ 1",) * 3
    assert backup == fhrp == ia.NOT_ASSESSED_CELL and detail.startswith("Lower bound")
    _node(mixed, "wan")["collected"] = True                            # the control: a measurement is written as is
    write_failure_impact_sheet(wb, mixed["failure_impact"], mixed)
    src = mixed["failure_impact"][_k(mixed, "gw")]
    assert {r[1]: r for r in _sheet_rows(wb[FAILURE_SHEET_NAME])}["gw"] == [
        src["severity"], "gw", src["vlans_impacted"], src["stranded"], src["hard"], src["backup"], src["fhrp"],
        src["detail"]]


def test_executive_summary_ranks_only_published_rows(mixed):
    from openpyxl import Workbook
    from cisco_toolkit.excel import EXEC_SUMMARY_SHEET_NAME, write_executive_summary_sheet
    wb = Workbook()
    write_executive_summary_sheet(wb, [], [], [], mixed["failure_impact"], impact_evidence=mixed)
    text = "\n".join(str(c.value) for row in wb[EXEC_SUMMARY_SHEET_NAME].iter_rows() for c in row
                     if c.value is not None)
    assert "Not ranked — 4 switch(es)" in text and "top keystone" not in text.lower()
    assert "No switch's blast radius is a measurement" in text
    _node(mixed, "wan")["collected"] = True
    wb = Workbook()
    write_executive_summary_sheet(wb, [], [], [], mixed["failure_impact"], impact_evidence=mixed)
    text = "\n".join(str(c.value) for row in wb[EXEC_SUMMARY_SHEET_NAME].iter_rows() for c in row
                     if c.value is not None)
    assert "gw is the top keystone" in text and "Not ranked — 3 switch(es)" in text


def test_architecture_review_never_conforms_over_a_withheld_zero(mixed):
    from cisco_toolkit.archreview import compute_architecture_review

    def res4(snap):
        return next(c for c in compute_architecture_review(snap)["checks"] if c["id"] == "RES-4")
    zero = copy.deepcopy(mixed)
    for row in zero["failure_impact"]:
        row["stranded"] = 0
    c = res4(zero)
    assert c["verdict"] == "not-assessable", c                       # INDETERMINATE + bounded zeros: never conforms
    assert "not graded" in c["observed"] and "x1" in c["observed"]
    c = res4(mixed)                                                  # gw strands 1, but only as a lower bound
    assert c["verdict"] == "not-assessable" and "strands at least 1 endpoint(s)" in c["observed"], c
    _node(mixed, "wan")["collected"] = True
    c = res4(mixed)
    assert c["verdict"] == "advisory" and c["evidence"] == ["gw"], c
    assert c["observed"].startswith("Losing gw strands 1 endpoint(s).") and "3 simulated device(s)" in c["observed"]


def test_design_and_deck_rank_only_published_keystones(mixed, tmp_path):
    pytest.importorskip("docx")
    pytest.importorskip("pptx")
    from docx import Document
    from pptx import Presentation
    from cisco_toolkit.deck import write_executive_deck_pptx
    from cisco_toolkit.design import write_design_doc_docx

    def design_text(snap, name):
        path = str(tmp_path / f"{name}.docx")
        write_design_doc_docx(path, snap, "W33")
        doc = Document(path)
        return [p.text for p in doc.paragraphs] + [" | ".join(c.text for c in r.cells)
                                                   for t in doc.tables for r in t.rows]

    def deck_text(snap, name):
        path = str(tmp_path / f"{name}.pptx")
        write_executive_deck_pptx(path, snap, "W33")
        return "\n".join(sh.text_frame.text for sl in Presentation(path).slides for sh in sl.shapes
                         if sh.has_text_frame)

    blocks = design_text(mixed, "held")
    assert not [b for b in blocks if b.startswith("Concentrated dependency:")]
    assert [b for b in blocks if b.startswith("Blast radius not a measurement:") and "4 switch(es)" in b]
    assert "Keystone devices (strand endpoints if lost) | 0" in blocks
    deck = deck_text(mixed, "held")
    assert "well distributed" not in deck and "INDETERMINATE — 4 switch(es)" in deck
    _node(mixed, "wan")["collected"] = True
    blocks = design_text(mixed, "ranked")
    assert [b for b in blocks if b.startswith("Concentrated dependency:") and "gw (1 endpoints)" in b]
    assert "Keystone devices (strand endpoints if lost) | 1" in blocks
    assert "…blast radius not a measurement (not ranked; §2.1) | 3" in blocks
    deck = deck_text(mixed, "ranked")
    assert "3 switch(es) not ranked" in deck and "well distributed" not in deck


def test_the_dossier_impact_term_never_reads_a_withheld_row_as_clean(mixed):
    rows = mixed["failure_impact"]
    plain = {d["host"]: d for d in analyze.compute_device_dossiers(failure_impact=rows)["per_device"]}
    assert plain["x1"]["impact_severity"] == "Info" and "impact_assessability" not in plain["x1"]   # unchanged
    doc = ia.assessment_document(mixed)
    dd = {d["host"]: d for d in analyze.compute_device_dossiers(
        failure_impact=rows, failure_impact_assessability=doc)["per_device"]}
    for host in ("x1", "x2"):
        d = dd[host]
        assert d["impact_assessability"]["assessable"] == ia.NOT_ASSESSED, d
        assert d["impact_assessability"]["pointer"] == f"/failure_impact/{_k(mixed, host)}"
        assert d["impact_severity"] == "—" and d["impact_score"] == 1
        assert "no modeled reachability impact" not in d["verdict"]
        assert d["verdict"] != "No stacked risk — routine migration handling."      # never routine by default
        assert "the blast radius is not assessed" in d["verdict"], d["verdict"]
        assert plain[host]["verdict"] == "No stacked risk — routine migration handling."  # the pre-W33 clean bill
    acc = dd["acc"]
    assert acc["impact_assessability"]["assessable"] == ia.LOWER_BOUND
    assert "the blast radius is only a lower bound" in acc["verdict"], acc["verdict"]
    gw = dd["gw"]
    assert gw["impact_assessability"]["assessable"] == ia.LOWER_BOUND and gw["impact_severity"] == "High"
    assert gw["impact_score"] == plain["gw"]["impact_score"]          # a lower bound's High still floors the term


def test_the_explorer_embed_carries_the_owners_verdicts(mixed):
    from cisco_toolkit.html import _slim_for_embed
    out = _slim_for_embed(mixed)
    assert [v["assessable"] for v in out["failure_impact_assessability"]] == [
        v.assessable for v in ia.assess_failure_impact(mixed)]
    assert "failure_impact_assessability" not in _slim_for_embed({"interfaces": {}})
    json.dumps(out, allow_nan=False)


NODE = shutil.which("node")


@pytest.mark.skipif(not NODE, reason="node is not available")
def test_the_explorer_keystone_card_ranks_only_published_rows(mixed, tmp_path):
    """Executed, not grepped: the embedded explorer script ranks a stored row only when the engine published it, and
    names every other switch (a held row, a row without a verdict, a scanned switch without a row) with the reason."""
    import test_explorer_render_safety as rs                    # the shared DOM stub and script runner
    from cisco_toolkit.html import _slim_for_embed
    driver = """
      const P=JSON.parse(require('fs').readFileSync(process.argv[2],'utf-8'));
      const out={};
      for(const k of Object.keys(P)){__EV('load')(P[k],'T',false);
        out[k]={ranked:__EV('cockpitKeystones')().map(r=>[r.host,r.blast]),card:__EV('keystoneCard')()};}
      process.stdout.write(JSON.stringify(out));
    """
    held = _slim_for_embed(mixed)
    published = copy.deepcopy(mixed)
    _node(published, "wan")["collected"] = True
    published = _slim_for_embed(published)
    no_verdicts = copy.deepcopy(published)
    del no_verdicts["failure_impact_assessability"]
    out = rs._run(driver, tmp_path, payload={"held": held, "published": published, "no_verdicts": no_verdicts})
    assert out["held"]["ranked"] == [], out["held"]
    assert "4 switches not ranked" in out["held"]["card"] and "x1" in out["held"]["card"]
    assert out["published"]["ranked"][0] == ["gw", 1], out["published"]
    assert "3 switches not ranked" in out["published"]["card"]
    assert out["no_verdicts"]["ranked"] == [] and "no engine assessability verdict" in out["no_verdicts"]["card"]
