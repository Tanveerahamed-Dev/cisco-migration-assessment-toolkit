"""[stored-availability DoS -- webapp read routes] A client-uploaded snapshot is ACCEPTED (201) even when a
section is malformed: a truthy NON-list/NON-dict (an int where a list/dict is expected) or a keystones list
carrying a non-dict element. The `(snap.get(x) or [])` / `(... or {})` guards catch only FALSY values, so the
malformed section survives the (unauthenticated) upload and then 500s a later GET read route -- a stored
availability DoS: one poisoned upload knocks out /graph or /cutover for that snapshot on every read.

Test-first, END-TO-END through the FastAPI TestClient (POST the poison snapshot -> 201; GET the read route ->
200), because the keystones case 500s in the ROUTE handler itself (app.py builds keystones with k.get("host"))
rather than inside build_graph -- a direct unit test on the projection would miss it. No real server, no engine
subprocess: an isolated temp SQLite store via create_app(db_path=...). Every read route must degrade, not 500.
"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `backend` importable

import backend.app as _appmod  # noqa: E402  (for _ALLOWED_SECTIONS -- keep the sweep in sync with the app)
from backend.app import create_app  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "test.db"))
    # base_url=localhost so the default Host passes the no-token DNS-rebinding guard (app.py
    # _request_host_allowed); with Sec-Fetch-Site absent the /graph|/cutover cross-site guard fails open.
    with TestClient(app, base_url="http://localhost") as c:
        yield c


@pytest.fixture()
def soft_client(tmp_path):
    """Like `client`, but surfaces a server error as a 500 RESPONSE instead of re-raising it. The sweep
    below asserts on status codes, so a regression reports `got 500 on <section>=<value>` rather than an
    opaque traceback -- and the non-vacuity check (revert the guards -> the sweep goes red) reads cleanly."""
    app = create_app(db_path=str(tmp_path / "test.db"))
    with TestClient(app, base_url="http://localhost", raise_server_exceptions=False) as c:
        yield c


def _campaign(client) -> int:
    r = client.post("/api/campaigns", json={"name": "dos"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _upload(client, cid: int, snap: dict) -> int:
    """POST a snapshot. The malformed section must NOT block the upload -- that is the whole point of a STORED
    DoS: the poison is accepted 201, then weaponised on a later read. (A 400 here would mean a DIFFERENT, safer
    outcome and would make the read-route assertion vacuous.)"""
    r = client.post(
        f"/api/campaigns/{cid}/snapshots",
        files={"file": ("s.json", json.dumps(snap).encode(), "application/json")},
        data={"label": "s"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ── GET /graph ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("snap, why", [
    ({"devices": {"sw1": {}}, "health_scores": 5},
     "graph.py:27 -- (snap.get('health_scores') or []) iterates a truthy non-list int -> TypeError"),
    ({"devices": {"sw1": {}}, "link_centrality": 5},
     "graph.py:55 -- (snap.get('link_centrality') or []) iterates a truthy non-list int -> TypeError"),
    ({"devices": {"sw1": {}}, "executive_brief": {"keystones": ["sw1", 123]}},
     "summary._keystones returned non-dict elements verbatim -> route k.get('host') -> AttributeError"),
], ids=["health_scores_int", "link_centrality_int", "keystones_nondict_elements"])
def test_graph_read_route_survives_malformed_section(client, snap, why):
    cid = _campaign(client)
    sid = _upload(client, cid, snap)            # accepted 201 despite the malformed section
    r = client.get(f"/api/snapshots/{sid}/graph")
    assert r.status_code == 200, f"{why}\n{r.text}"
    body = r.json()
    assert isinstance(body, dict) and "nodes" in body and "edges" in body


# ── GET /cutover ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("snap, why", [
    ({"devices": {"sw1": {}}, "health_scores": 5},
     "cutover.py:74 _rows -- (snap.get('health_scores') or []) iterated via _blind_hosts"),
    ({"devices": {"sw1": {}}, "wave_sequencing": 5},
     "cutover.py:74 _rows -- wave_sequencing truthy non-list int at build_plan entry"),
    ({"devices": {"sw1": {}}, "remediation_plan": 5, "validation_plan": 5},
     "cutover.py:305 -- (snap.get('remediation_plan') or {}).get(...) on a truthy non-dict int"),
    # inner poison: needs a wave so _wave_remediation/_wave_validation actually run on the coerced value
    ({"devices": {"sw1": {}}, "wave_sequencing": [{"group": "W1", "hard_cutover": ["sw1"]}],
      "remediation_plan": {"by_device": 5}},
     "cutover.py:305 -- inner .get('by_device') truthy non-dict -> _wave_remediation .items()"),
    ({"devices": {"sw1": {}}, "wave_sequencing": [{"group": "W1", "hard_cutover": ["sw1"]}],
      "validation_plan": {"by_wave": 5}},
     "cutover.py:305 -- inner .get('by_wave') truthy non-dict -> _wave_validation .get()"),
], ids=["health_scores_int", "wave_sequencing_int", "plans_int",
        "remediation_by_device_int", "validation_by_wave_int"])
def test_cutover_read_route_survives_malformed_section(client, snap, why):
    cid = _campaign(client)
    sid = _upload(client, cid, snap)
    r = client.get(f"/api/snapshots/{sid}/cutover")
    assert r.status_code == 200, f"{why}\n{r.text}"
    body = r.json()
    assert isinstance(body, dict) and "summary" in body and "waves" in body


# ── GET /section/device_dossiers (app.py health_scores read) ─────────────────────
def test_section_device_dossiers_survives_malformed_health_scores(client):
    """app.py:622 -- the device_dossiers section route reads (snap.get('health_scores') or []) to decide
    whether to recompute; a truthy non-list health_scores 500s the `for h in` iteration. device_dossiers
    must be PRESENT (else the route 404s at the section-presence guard before reaching the read)."""
    cid = _campaign(client)
    sid = _upload(client, cid, {"devices": {"sw1": {}}, "device_dossiers": {}, "health_scores": 5})
    r = client.get(f"/api/snapshots/{sid}/section/device_dossiers")
    assert r.status_code == 200, r.text
    assert r.json()["section"] == "device_dossiers"


# ── GET /gates (gates.waves_from_snapshot migration_readiness read) ──────────────
def test_gates_read_route_survives_malformed_migration_readiness(client):
    """gates.py:29 -- waves_from_snapshot did `(snap.get('migration_readiness') or [])` then iterated it; a
    truthy non-list migration_readiness 500s GET /api/campaigns/{id}/gates (a section-only hot-path read)."""
    cid = _campaign(client)
    _upload(client, cid, {"devices": {"sw1": {}}, "migration_readiness": 5})
    r = client.get(f"/api/campaigns/{cid}/gates")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["waves"] == [] and "cadence" in body and "records" in body


# ── POST /snapshots + GET /snapshots/{id} (summary.summarize devices read) ───────
def test_summary_survives_malformed_devices(client):
    """summary.py:163 -- `len(snap.get('devices') or {})` is the eagerly-evaluated default of a .get(); a
    truthy non-dict 'devices' (an int) 500s summarize(), which runs on EVERY upload AND on the snapshot
    read (freshen). The malformed upload is still accepted (top-level 'devices' key present)."""
    cid = _campaign(client)
    sid = _upload(client, cid, {"devices": 5})            # 201 (key present) -> summarize must not 500
    r = client.get(f"/api/snapshots/{sid}")
    assert r.status_code == 200, r.text


# ── comprehensive class sweep: every section x {int, str, list-of-scalars} x every read route ─────
# Poison the WHOLE reachable section set (the /section whitelist + the projection-only keys the
# summary/graph/cutover/gates read routes consume), not a named subset -- the recurring lesson is that a
# refuter finds the sibling route the point-fix missed. Each poison is a *well-formed upload* (top-level
# 'devices' present) that only malforms one section, then every webapp read route must degrade, never 500.
# NB the ENGINE-layer /design|/architecture_coverage|/domain_packs|/design/nrfu family (compute_design_
# blueprint list-of-scalar 500s) is out of scope here -- fixed separately on PR #451 -- so it is not swept.
_POISON_SECTIONS = sorted(set(_appmod._ALLOWED_SECTIONS) | {
    "executive_brief", "cable_map", "move_groups",   # projection-only keys (not /section-addressable)
})
_POISON_VALUES = [5, "x", [1, 2]]                     # truthy non-list/non-dict scalars + a list of scalars


@pytest.mark.parametrize("value", _POISON_VALUES, ids=["int", "str", "list_of_scalars"])
@pytest.mark.parametrize("section", _POISON_SECTIONS)
def test_every_read_route_survives_any_top_level_poison(soft_client, section, value):
    cid = _campaign(soft_client)
    # device_dossiers present by default so the /section/device_dossiers route reaches its health_scores
    # read (a `section == 'device_dossiers'` case simply overrides it with the poison value -- still valid).
    snap = {"devices": {"sw1": {}}, "device_dossiers": {}, section: value}
    up = soft_client.post(
        f"/api/campaigns/{cid}/snapshots",
        files={"file": ("s.json", json.dumps(snap).encode(), "application/json")},
        data={"label": "s"},
    )
    assert up.status_code == 201, f"upload rejected/500 on {section}={value!r}: {up.status_code} {up.text}"
    sid = up.json()["id"]

    routes = {
        "graph": f"/api/snapshots/{sid}/graph",
        "cutover": f"/api/snapshots/{sid}/cutover",
        "cable_map": f"/api/snapshots/{sid}/cable_map",
        "snapshot": f"/api/snapshots/{sid}",                       # summary.summarize (freshen)
        "gates": f"/api/campaigns/{cid}/gates",
        "section_device_dossiers": f"/api/snapshots/{sid}/section/device_dossiers",
        "section_health_scores": f"/api/snapshots/{sid}/section/health_scores",
    }
    if section in _appmod._ALLOWED_SECTIONS:                        # also slice the poisoned section itself
        routes["section_self"] = f"/api/snapshots/{sid}/section/{section}"
    for name, url in routes.items():
        r = soft_client.get(url)
        assert r.status_code < 500, (
            f"GET {name} returned {r.status_code} on {section}={value!r} (stored-DoS): {r.text}")
