"""W27 (follow-up F2): every AssessHub failure-impact surface honours the W23 projection holds.

``analyze.compute_failure_impact`` writes Info, zero counts and a clean-bill detail for a switch it could not
simulate, and a partial simulation or an uncollected neighbour makes a low band or a zero only a lower bound. The
engine-owned projection (``ui_projection``'s one shared failure-impact row builder) withholds exactly those cells,
each with its state and reason. These tests hold the AssessHub surfaces that used to read the raw stored rows to it:

* the dashboard keystones (``summary._keystones`` -> ``summarize``) and the cutover plan's per-wave keystone tags;
* the cutover plan's worst-case blast radius (``cutover._worst_blast_radius``), on screen and in the .docx;
* the snapshot "Failure impact" tab (``GET /section/failure_impact``);
* the /graph keystone badge and a summary cached by the old raw-row ranking.

A held, duplicated, INDETERMINATE or uncollected-neighbour row never yields a published "no impact", a zero or an
Info-ranked worst; a clean, fully assessed row renders exactly as before. Rows come from the REAL producers
(``analyze.compute_failure_impact`` and ``analyze.compute_cable_map`` over constructed interfaces) and from the
shipped sample snapshot. The dossier recompute is deliberately left on the stored rows; its pin is the last test.
"""
from __future__ import annotations

import copy
import json
import sys
from dataclasses import asdict
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `backend` importable

from backend import cutover, summary  # noqa: E402  (also bootstraps sys.path for cisco_toolkit)
from backend.app import create_app  # noqa: E402
from cisco_toolkit import analyze  # noqa: E402
from cisco_toolkit import ui_projection as ui  # noqa: E402
from cisco_toolkit.model import InterfaceData  # noqa: E402

SAMPLE = Path(__file__).resolve().parents[1] / "sample_data" / "sample_fleet.snapshot.json"
#: The failure-impact cells that measure a simulated blast radius (host, off_scan_gw_vlans and detail do not).
MEASURES = ("severity", "vlans_impacted", "stranded", "hard", "backup", "fhrp")
#: Two blind spots, neither of them a sample switch with a row: one never reached, one reached in part.
BLIND = [{"host": "ghost1", "status": "not collected", "data_quality": 0, "missing": ["version/inventory"]},
         {"host": "access2", "status": "partial", "data_quality": 75, "missing": ["interface status"]}]
CLEAN_BILL = "No reachability impact from removing this switch (within the scan)."


@pytest.fixture(scope="module")
def sample():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "test.db"))
    # base_url=localhost so the default Host passes the no-token DNS-rebinding guard (app.py
    # _request_host_allowed) -- the dev server this emulates is reached over loopback.
    with TestClient(app, base_url="http://localhost") as c:
        yield c


def _upload(client, snap) -> int:
    cid = client.post("/api/campaigns", json={"name": "impact"}).json()["id"]
    r = client.post(f"/api/campaigns/{cid}/snapshots",
                    files={"file": ("s.json", json.dumps(snap).encode(), "application/json")},
                    data={"label": "s"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# --------------------------------------------------------------------------------------------------
# REAL producer fixtures (the W23 shapes): every interface carries run_config_observed, as build.py marks each
# interface its scoped interface running-config capture parsed -- the only source of an SVI's gateway address.
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
    """A CDP-seen trunk to a peer the collection never reached."""
    return InterfaceData(port=port, status="connected", switchport_mode="Trunk", cdp_neighbor=peer,
                         neighbor_port="Gi0/1", endpoint_type=endpoint_type, neighbor_platform=platform,
                         trunk_allowed_vlans="10", stp_fwd_vlans="10", run_config_observed=True)


def _unsimulatable_fleet():
    """`acc` carries VLAN 20, whose gateway was never scanned, and nothing it can simulate; `gw` gateways VLAN 10 for
    `acc` (a measured hard partition) and also carries VLAN 20; `x1` and `x2` share a trunk with no VLAN-carriage
    evidence on either end. So acc, x1 and x2 get the producer's INDETERMINATE Info rows with zero counts."""
    return {"gw": {"Gi1": _trunk("Gi1", "acc", "Gi1", "10,20"), "Vlan10": _svi(10, "10.10.0.1/24")},
            "acc": {"Gi1": _trunk("Gi1", "gw", "Gi1", "10,20"), "Gi10": _access("Gi10", 10, "0000.0000.000a"),
                    "Gi20": _access("Gi20", 20, "0000.0000.0014")},
            "x1": {"Gi1": _trunk("Gi1", "x2", "Gi1")}, "x2": {"Gi1": _trunk("Gi1", "x1", "Gi1")}}


def _downstream_fleet():
    """`gw` gateways VLAN 10 for `acc` (removing it is a measured hard partition, High) and trunks up to the router
    `wan`; `acc` trunks down to the switch `dsw`. The collection reached neither, so the producer writes its clean
    bill for `acc` whatever hangs behind `dsw`."""
    return {"gw": {"Gi1": _trunk("Gi1", "acc", "Gi1", "10"), "Gi47": _edge("Gi47", "wan", "Router", "cisco ISR4331/K9"),
                   "Vlan10": _svi(10, "10.10.0.1/24")},
            "acc": {"Gi1": _trunk("Gi1", "gw", "Gi1", "10"), "Gi10": _access("Gi10", 10, "0000.0000.000a"),
                    "Gi48": _edge("Gi48", "dsw", "Switch")}}


def _snapshot(interfaces, waves=()):
    """The REAL producers' rows over `interfaces`, as a stored snapshot carries them, with one hard-cutover wave per
    ``(group, hosts)``. JSON round-tripped: what the store hands every read route."""
    snap = {"schema": "collect_parse_snapshot/1", "devices": {host: {"hostname": host} for host in interfaces},
            "interfaces": {host: {port: asdict(row) for port, row in ports.items()}
                           for host, ports in interfaces.items()},
            "failure_impact": analyze.compute_failure_impact(interfaces),
            "cable_map": analyze.compute_cable_map(interfaces), "routes": {}}
    if waves:
        snap["wave_sequencing"] = [{"group": group, "make_before_break": [], "hard_cutover": list(hosts)}
                                   for group, hosts in waves]
    return json.loads(json.dumps(snap))


def _by_host(snap):
    return {row["host"]: row for row in snap["failure_impact"]}


def _node(snap, host):
    same = [n for n in snap["cable_map"]["nodes"] if n["host"] == host]
    assert len(same) == 1, (host, same)
    return same[0]


def _old_entry(row):
    """The pre-W27 keystone / blast-radius shape of a stored row, for a row the engine publishes in full."""
    return {field: row[field] for field in ("host", "severity", "stranded", "vlans_impacted", "detail")}


def _old_keystones(rows, top=8):
    """The pre-W27 ranking (severity, then stranded; stable over the stored order) of fully published rows."""
    ranked = sorted(rows, key=lambda r: (summary._SEV_RANK.get(r["severity"], 99), -r["stranded"]))
    return [_old_entry(row) for row in ranked[:top]]


def _old_worst(rows, switches):
    """The pre-W27 worst case of a wave over fully published rows (first minimal in the stored order)."""
    return min((r for r in rows if r["host"] in switches),
               key=lambda r: (cutover._SEV_RANK.get(r["severity"], 99), -r["stranded"]))


def _held_core1(sample, mode):
    """The sample with core1's row withheld by the projection, the mode naming the hold."""
    snap = copy.deepcopy(sample)
    rows = snap["failure_impact"]
    k = next(i for i, row in enumerate(rows) if row["host"] == "core1")
    assert rows[k]["severity"] == "High" and rows[k]["stranded"] > 0       # the sample's top keystone, as stored
    if mode == "no_run_config":
        for port in snap["interfaces"]["core1"].values():
            port.pop("run_config_observed", None)            # what html.sparsify_interfaces writes for false
        return snap, "run_config_observed"
    if mode == "legacy":
        del rows[k]["off_scan_gw_vlans"]
        return snap, "predates the producer's assessability marker"
    rows.append(dict(rows[k], severity="Info", vlans_impacted=0, stranded=0, hard=0, backup=0, fhrp=0,
                     detail=CLEAN_BILL))                                   # a contradicting second row for core1
    return snap, "name this exact host"


# --------------------------------------------------------------------------------------------------
# the hand-written constants are the projection's own
# --------------------------------------------------------------------------------------------------
def test_the_impact_fields_and_tokens_are_the_projections_own(sample):
    item = ui.project_topology(sample)["failure_impact"]["items"][0]
    assert [k for k in item if k not in ("index", "pointer", "node_refs", "style")] == list(summary.IMPACT_FIELDS)
    assert summary._PUBLISHED == ui._PUB and summary._COLLECTED_BUT_EMPTY == ui._CBE
    assert summary._IMPACT_BLIND_CAVEAT in {lim["id"] for lim in ui.LIMITATIONS}
    assert summary.IMPACT_NOT_ASSESSED == cutover.IMPACT_NOT_ASSESSED == cutover.GATE_NOT_ASSESSED


# --------------------------------------------------------------------------------------------------
# keystones: the dashboard panel, the cutover plan's per-wave tags
# --------------------------------------------------------------------------------------------------
def test_keystones_never_rank_a_row_the_engine_could_not_simulate():
    snap = _snapshot(_unsimulatable_fleet())
    raw = _by_host(snap)
    held = ("acc", "x1", "x2")
    for host in held:                       # the producer's own rows: Info and zeros that look like measurements
        assert raw[host]["severity"] == "Info" and raw[host]["stranded"] == 0, raw[host]
        assert raw[host]["detail"].startswith(ui.IMPACT_INDETERMINATE_PREFIX), raw[host]
    gw = raw["gw"]
    assert gw["severity"] == "High" and gw["stranded"] > 0 and gw["off_scan_gw_vlans"] == 1, gw
    keystones = summary.summarize(snap)["keystones"]
    # before W27 the panel listed all four rows, three of them as Info with 0 stranded
    assert keystones[:-1] == [_old_entry(gw)]          # High and its positive counts stay published lower bounds
    note = keystones[-1]
    assert note["host"] == "" and note["severity"] == summary.IMPACT_NOT_ASSESSED
    assert note["stranded"] is None and note["vlans_impacted"] is None and note["n_not_ranked"] == 3
    for host in held:
        assert f"{host}, " in note["detail"] or f"{host} — " in note["detail"], (host, note["detail"])
    assert "could not simulate" in note["detail"]
    assert not any(k["severity"] == "Info" or k["stranded"] == 0 for k in keystones), keystones
    assert cutover._keystone_hosts(snap) == {"gw"}      # the disclosure names no host, so it tags no wave


def test_keystones_never_rank_a_clean_bill_an_uncollected_neighbour_bounds():
    snap = _snapshot(_downstream_fleet())
    raw = _by_host(snap)
    acc, gw = raw["acc"], raw["gw"]
    assert acc["severity"] == "Info" and acc["stranded"] == 0 and acc["off_scan_gw_vlans"] == 0, acc
    assert acc["detail"] == CLEAN_BILL
    assert gw["severity"] == "High" and gw["stranded"] == 1, gw
    dsw = _node(snap, "dsw")
    assert dsw["collected"] is False and dsw["kind"] == "switch", dsw        # the REAL cable-map producer's node
    keystones = summary.summarize(snap)["keystones"]
    assert keystones[:-1] == [_old_entry(gw)]
    note = keystones[-1]
    assert note["severity"] == summary.IMPACT_NOT_ASSESSED and note["n_not_ranked"] == 1
    assert "acc — " in note["detail"] and "uncollected neighbour" in note["detail"], note["detail"]
    assert CLEAN_BILL not in note["detail"]
    # the control: the same stored row once the cable map shows that peer collected is a published clean bill,
    # ranked and rendered exactly as before, with no disclosure
    dsw["collected"] = True
    assert summary.summarize(snap)["keystones"] == [_old_entry(gw), _old_entry(acc)]


def test_keystones_on_the_sample_are_unchanged_and_carry_the_contract(sample):
    s = summary.summarize(copy.deepcopy(sample))
    assert s["keystone_contract"] == summary.KEYSTONE_CONTRACT_VERSION
    assert s["keystones"] == _old_keystones(sample["failure_impact"])
    assert all(k["host"] for k in s["keystones"])
    assert cutover._keystone_hosts(copy.deepcopy(sample)) == {k["host"] for k in s["keystones"]}


@pytest.mark.parametrize("mode", ["no_run_config", "legacy", "duplicate"])
def test_a_withheld_sample_row_never_ranks_and_is_disclosed(sample, mode):
    snap, why = _held_core1(sample, mode)
    keystones = summary.summarize(snap)["keystones"]
    ranked, note = keystones[:-1], keystones[-1]
    others = [row for row in sample["failure_impact"] if row["host"] != "core1"]
    assert ranked == _old_keystones(others), ranked                # core1 is neither ranked first nor shown as Info
    assert note["host"] == "" and note["severity"] == summary.IMPACT_NOT_ASSESSED
    assert note["n_not_ranked"] == (2 if mode == "duplicate" else 1)
    assert "core1" in note["detail"] and why in note["detail"], note["detail"]
    assert "core1" not in cutover._keystone_hosts(snap)


def test_a_failed_phase_leaves_no_keystone_and_never_an_empty_clean_panel(sample):
    snap = copy.deepcopy(sample)
    snap["assessment_integrity"] = {"failure_impact": "failed"}
    keystones = summary.summarize(snap)["keystones"]
    assert len(keystones) == 1, keystones                          # never [] ("no keystone devices flagged")
    note = keystones[0]
    assert note["severity"] == summary.IMPACT_NOT_ASSESSED and note["n_not_ranked"] == len(sample["failure_impact"])
    assert note["stranded"] is None and note["vlans_impacted"] is None


def test_a_blind_spot_makes_the_keystone_ranking_a_disclosed_lower_bound(sample):
    snap = copy.deepcopy(sample)
    snap["collection_completeness"]["devices"] = copy.deepcopy(BLIND)
    keystones = summary.summarize(snap)["keystones"]
    assert keystones[:-1] == _old_keystones(sample["failure_impact"])   # every row is still the engine's to rank
    note = keystones[-1]
    assert note["severity"] == summary.IMPACT_NOT_ASSESSED and note["n_not_ranked"] == 0
    assert "lower bound" in note["detail"] and "collection_completeness lists 2 device(s)" in note["detail"]


# --------------------------------------------------------------------------------------------------
# the cutover plan's worst-case blast radius
# --------------------------------------------------------------------------------------------------
def test_the_worst_case_never_ranks_a_row_the_engine_withholds():
    snap = _snapshot(_unsimulatable_fleet(), waves=[("held", ("acc", "x1")), ("mixed", ("gw", "acc")),
                                                    ("missing", ("gw", "ghost"))])
    raw = _by_host(snap)
    waves = {w["group"]: w for w in cutover.build_plan(snap)["waves"]}
    # before W27 this wave's worst case was acc's stored row: Info, 0 endpoints across 0 VLANs
    held = waves["held"]["blast_radius"]
    assert held["host"] == "" and held["severity"] == cutover.IMPACT_NOT_ASSESSED
    assert held["stranded"] is None and held["vlans_impacted"] is None
    assert held["complete"] is False and held["n_not_ranked"] == 2
    assert held["detail"].startswith("NOT ASSESSED") and "could not simulate" in held["detail"], held["detail"]
    assert "acc" in held["detail"] and "x1" in held["detail"]
    gw = raw["gw"]
    mixed = waves["mixed"]["blast_radius"]
    assert {k: mixed[k] for k in ("host", "severity", "stranded", "vlans_impacted")} == {
        k: gw[k] for k in ("host", "severity", "stranded", "vlans_impacted")}
    assert mixed["detail"].startswith(gw["detail"] + " — LOWER BOUND"), mixed["detail"]
    assert "acc — " in mixed["detail"] and mixed["complete"] is False and mixed["n_not_ranked"] == 1
    missing = waves["missing"]["blast_radius"]
    assert missing["host"] == "gw" and missing["complete"] is False and missing["n_not_ranked"] == 1
    assert "ghost — not collected: no failure_impact row names this switch" in missing["detail"], missing["detail"]


def test_a_wave_behind_an_uncollected_neighbour_is_not_assessed_and_its_control_renders_as_before():
    snap = _snapshot(_downstream_fleet(), waves=[("edge", ("acc",)), ("both", ("gw", "acc"))])
    raw = _by_host(snap)
    waves = {w["group"]: w for w in cutover.build_plan(snap)["waves"]}
    edge = waves["edge"]["blast_radius"]
    assert edge["severity"] == cutover.IMPACT_NOT_ASSESSED and edge["stranded"] is None
    assert "uncollected neighbour" in edge["detail"] and CLEAN_BILL not in edge["detail"], edge["detail"]
    both = waves["both"]["blast_radius"]
    assert both["host"] == "gw" and both["severity"] == "High" and both["complete"] is False
    # the control: once the peer reads collected, both waves render exactly the stored rows, plus the two new keys
    _node(snap, "dsw")["collected"] = True
    waves = {w["group"]: w for w in cutover.build_plan(snap)["waves"]}
    assert waves["edge"]["blast_radius"] == {**_old_entry(raw["acc"]), "complete": True, "n_not_ranked": 0}
    assert waves["both"]["blast_radius"] == {**_old_entry(raw["gw"]), "complete": True, "n_not_ranked": 0}


def test_the_sample_plan_keeps_its_worst_cases_and_a_duplicate_is_never_picked(sample):
    plan = cutover.build_plan(copy.deepcopy(sample))
    assert plan["waves"]
    for wave in plan["waves"]:
        want = _old_worst(sample["failure_impact"], set(wave["switches"]))
        assert wave["blast_radius"] == {**_old_entry(want), "complete": True, "n_not_ranked": 0}, wave["group"]
    snap, why = _held_core1(sample, "duplicate")
    wave = next(w for w in cutover.build_plan(snap)["waves"] if "core1" in w["switches"])
    br = wave["blast_radius"]
    others = [row for row in sample["failure_impact"] if row["host"] != "core1"]
    want = _old_worst(others, set(wave["switches"]))
    assert br["host"] != "core1" and br["severity"] != "Info"
    assert {k: br[k] for k in ("host", "severity", "stranded", "vlans_impacted")} == {
        k: want[k] for k in ("host", "severity", "stranded", "vlans_impacted")}
    assert br["detail"].startswith(want["detail"] + " — LOWER BOUND") and why in br["detail"]
    assert br["complete"] is False and br["n_not_ranked"] == 1


def test_the_cutover_document_prints_not_assessed_never_a_zero(tmp_path):
    pytest.importorskip("docx")
    from docx import Document

    from backend.cutover_docx import write_cutover_docx

    snap = _snapshot(_unsimulatable_fleet(), waves=[("held", ("acc", "x1"))])
    out = tmp_path / "cutover.docx"
    write_cutover_docx(str(out), snap, "W27")
    lines = [p.text for p in Document(out).paragraphs if p.text.startswith("Worst-case blast radius:")]
    assert len(lines) == 1, lines
    assert "NOT ASSESSED" in lines[0] and "could not simulate" in lines[0], lines[0]
    assert "0 endpoint(s)" not in lines[0] and "(Info)" not in lines[0], lines[0]


# --------------------------------------------------------------------------------------------------
# the snapshot "Failure impact" tab
# --------------------------------------------------------------------------------------------------
def test_the_failure_impact_tab_shows_the_engine_reason_never_a_withheld_value(client):
    sid = _upload(client, _snapshot(_unsimulatable_fleet()))
    stored = json.loads(client.get(f"/api/snapshots/{sid}/raw").content)
    table = client.get(f"/api/snapshots/{sid}/section/failure_impact").json()["data"]
    items = ui.project_topology(stored)["failure_impact"]["items"]
    assert len(table) == len(items) == len(stored["failure_impact"])
    for row, item, src in zip(table, items, stored["failure_impact"]):
        assert list(row) == list(summary.IMPACT_FIELDS), row
        for field in summary.IMPACT_FIELDS:                  # each cell is the projection's: value or reason
            fact = item[field]
            if fact["state"] == "published":
                assert row[field] == src[field], (src["host"], field)
            else:
                assert isinstance(row[field], str) and row[field] == fact["reason"], (src["host"], field)
    by_host = {src["host"]: row for row, src in zip(table, stored["failure_impact"])}
    for host in ("acc", "x1", "x2"):
        for field in MEASURES:                               # never the stored Info or 0
            cell = by_host[host][field]
            assert isinstance(cell, str) and cell.startswith("not collected:"), (host, field, cell)
            assert "could not simulate" in cell, (host, field, cell)
        # the producer's own INDETERMINATE disclosure stays published beside its held measures
        assert by_host[host]["detail"].startswith(ui.IMPACT_INDETERMINATE_PREFIX)
    gw = by_host["gw"]
    assert gw["severity"] == "High" and isinstance(gw["stranded"], int) and gw["stranded"] > 0
    for field in ("backup", "fhrp"):                         # a zero under a partial simulation is a lower bound
        assert isinstance(gw[field], str) and "only a lower bound" in gw[field], (field, gw[field])


def test_the_sample_tab_changes_only_the_zeros_core2s_uncollected_router_bounds(client, sample):
    sid = client.post("/api/demo/seed").json()["snapshot"]["id"]
    table = client.get(f"/api/snapshots/{sid}/section/failure_impact").json()["data"]
    assert len(table) == len(sample["failure_impact"])
    changed = []
    for row, src in zip(table, sample["failure_impact"]):
        assert list(row) == list(summary.IMPACT_FIELDS)
        for field in summary.IMPACT_FIELDS:
            if src["host"] == "core2" and field in MEASURES and src[field] == 0:
                assert isinstance(row[field], str) and "only a lower bound" in row[field], (field, row[field])
                assert "uncollected neighbour" in row[field], row[field]
                changed.append(field)
            else:
                assert row[field] == src[field], (src["host"], field)
    assert sorted(changed) == ["backup", "fhrp"], changed


def test_the_tab_withholds_unreadable_rows_and_returns_a_non_list_as_stored(client):
    sid = _upload(client, {"devices": {"sw1": {}},
                           "failure_impact": [1, "x", {"host": "sw1", "severity": "Info", "stranded": 0}]})
    table = client.get(f"/api/snapshots/{sid}/section/failure_impact").json()["data"]
    assert len(table) == 3
    for row in table:
        assert list(row) == list(summary.IMPACT_FIELDS)
        for field in MEASURES:
            assert isinstance(row[field], str) and row[field], (field, row[field])   # a reason, never Info or 0
    for row in table[:2]:                                    # a row that is not an object claims nothing at all
        assert all(isinstance(row[field], str) and row[field] for field in summary.IMPACT_FIELDS), row
    sid = _upload(client, {"devices": {"sw1": {}}, "failure_impact": 5})
    assert client.get(f"/api/snapshots/{sid}/section/failure_impact").json()["data"] == 5


# --------------------------------------------------------------------------------------------------
# the /graph keystone badge and a summary cached by the raw-row ranking
# --------------------------------------------------------------------------------------------------
def test_the_graph_badge_and_a_cached_summary_never_keep_a_withheld_keystone(client, sample):
    snap, _why = _held_core1(sample, "no_run_config")
    sid = _upload(client, snap)
    nodes = {n["id"]: n for n in client.get(f"/api/snapshots/{sid}/graph").json()["nodes"]}
    assert nodes["core1"]["keystone"] is False          # the raw ranking made it the first keystone (High, 45)
    assert nodes["access1"]["keystone"] is True
    # a summary cached by the raw-row ranking (no keystone contract) that still names core1
    store = client.app.state.store
    stale = dict(store.get_snapshot_meta(sid)["summary"])
    assert stale.pop("keystone_contract") == summary.KEYSTONE_CONTRACT_VERSION
    stale["keystones"] = [{"host": "core1", "severity": "High", "stranded": 45, "vlans_impacted": 3, "detail": ""}]
    store.update_summary(sid, stale)
    nodes = {n["id"]: n for n in client.get(f"/api/snapshots/{sid}/graph").json()["nodes"]}
    assert nodes["core1"]["keystone"] is False          # the badge reads the snapshot, never the stale cache
    fresh = client.get(f"/api/snapshots/{sid}").json()["summary"]
    assert fresh["keystone_contract"] == summary.KEYSTONE_CONTRACT_VERSION
    assert "core1" not in {k["host"] for k in fresh["keystones"]}
    assert store.get_snapshot_meta(sid)["summary"]["keystone_contract"] == summary.KEYSTONE_CONTRACT_VERSION


# --------------------------------------------------------------------------------------------------
# an owner fault withholds every surface; the dossier recompute keeps the engine's own input
# --------------------------------------------------------------------------------------------------
def test_a_projection_fault_withholds_every_surface(monkeypatch, sample):
    def fault(_snap):
        raise RuntimeError("owner fault")

    monkeypatch.setattr(summary.engine, "failure_impact_projection", fault)
    snap = copy.deepcopy(sample)
    keystones = summary.summarize(snap)["keystones"]
    assert len(keystones) == 1 and keystones[0]["severity"] == summary.IMPACT_NOT_ASSESSED, keystones
    assert "could not be built" in keystones[0]["detail"]
    for wave in cutover.build_plan(snap)["waves"]:
        br = wave["blast_radius"]
        assert br["severity"] == cutover.IMPACT_NOT_ASSESSED and br["stranded"] is None, br
    table = summary.failure_impact_table(snap)
    assert len(table) == len(sample["failure_impact"])
    assert all(row[field] == summary._R_IMPACT_FAULT for row in table for field in summary.IMPACT_FIELDS)


def test_the_dossier_recompute_forwards_the_stored_producer_rows_unchanged(client, monkeypatch):
    """Left on the stored rows on purpose: compute_device_dossiers is an engine function, and the pipeline hands it
    the same failure_impact list it stores (COLLECT_PARSE main). The webapp recompute must forward exactly that list,
    never a projection-derived substitute, so the engine keeps owning its own input."""
    seen = {}

    def capture(**kwargs):
        seen.update(kwargs)
        return {"summary": {"bands": {"Unassessed": 1}}, "per_device": []}

    monkeypatch.setattr(analyze, "compute_device_dossiers", capture)
    impact = [{"host": "good1", "severity": "Info", "vlans_impacted": 0, "stranded": 0, "hard": 0, "backup": 0,
               "fhrp": 0, "detail": CLEAN_BILL}]
    snap = {"devices": {"blind1": {}, "good1": {}},
            "health_scores": [{"switch": "blind1", "band": "Insufficient Data", "score": 90},
                              {"switch": "good1", "band": "Good", "score": 85}],
            "failure_impact": impact,
            "device_dossiers": {"summary": {"bands": {"Low": 1}}, "per_device": []}}
    sid = _upload(client, snap)
    r = client.get(f"/api/snapshots/{sid}/section/device_dossiers")
    assert r.status_code == 200, r.text
    assert seen["failure_impact"] == impact
