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

from backend.app import create_app  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "test.db"))
    # base_url=localhost so the default Host passes the no-token DNS-rebinding guard (app.py
    # _request_host_allowed); with Sec-Fetch-Site absent the /graph|/cutover cross-site guard fails open.
    with TestClient(app, base_url="http://localhost") as c:
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
