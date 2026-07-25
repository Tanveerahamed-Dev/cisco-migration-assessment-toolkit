"""Stored-DoS guard: an UNHASHABLE leaf in a health_scores row must not 500 the deck deliverable.

Distinct from the truthy-non-dict falsy-guard class (test_stored_dos_read_route_guard.py): the deck
uses a row's `band` value as a DICT KEY (`deck.py` `band_counts[str(r.get("band",""))]`). The rows are
already `_R`-filtered to dicts, so this is purely the LEAF type — `as_dict`/`as_list` cannot fix it;
the repo's guard for this shape is `str()` (cf. design.py's `str(...)  # a dict sw_version would be an
unhashable key`).

Attacker path: the snapshot JSON is uploaded and stored verbatim (the only validation is
`isinstance(snap, dict) and "devices" in snap`), then rendered by
`deliverables.generate("deck", snap, ...)`, which re-raises -> HTTP 500. The POST is accepted first,
so an unhashable `band` is a STORED availability DoS, not a transient error.
"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("pptx")  # the deck writer is optional-dep; skip the FILE, never mask a live 503

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `backend` importable

from backend.app import create_app  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "test.db"))
    # base_url=localhost so the default Host passes the no-token guard; raise_server_exceptions=False
    # so a stored DoS surfaces as a 500 RESPONSE we can assert on, matching a real client.
    with TestClient(app, base_url="http://localhost", raise_server_exceptions=False) as c:
        yield c


def _upload(client, snap):
    cid = client.post("/api/campaigns", json={"name": "c"}).json()["id"]
    r = client.post(
        f"/api/campaigns/{cid}/snapshots",
        files={"file": ("s.json", json.dumps(snap).encode(), "application/json")},
        data={"label": "s"},
    )
    assert r.status_code == 201, r.text          # the poison is ACCEPTED -> the DoS is *stored*
    return r.json()["id"]


@pytest.mark.parametrize("band", [{"x": 1}, [1, 2]], ids=["band=dict", "band=list"])
def test_deck_route_survives_unhashable_band(client, band):
    """GET .../deliverable/deck must be 200, not 500, when a health_scores row's band is unhashable."""
    snap = {"devices": {"sw1": {"hostname": "sw1"}},
            "health_scores": [{"switch": "sw1", "score": 10, "band": band}]}
    sid = _upload(client, snap)
    r = client.get(f"/api/snapshots/{sid}/deliverable/deck")
    # Assert the exact success code: a bare `< 500` would pass on a 503 load-shed
    # (app.py's _generation_slot) and silently hide a regression.
    assert r.status_code == 200, f"unhashable band {band!r} -> {r.status_code}: {r.text[:300]}"
    assert r.content[:2] == b"PK", "expected a real .pptx (zip magic), not an error body"


def test_deck_route_wellformed_band_still_renders(client):
    """Baseline: the str() keying is a no-op for well-formed string bands."""
    snap = {"devices": {"sw1": {"hostname": "sw1"}},
            "health_scores": [{"switch": "sw1", "score": 10, "band": "Critical"}]}
    sid = _upload(client, snap)
    r = client.get(f"/api/snapshots/{sid}/deliverable/deck")
    assert r.status_code == 200, r.text
    assert r.content[:2] == b"PK"
