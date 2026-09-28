"""`GET /api/snapshots/{id}/raw` — the stored snapshot bytes, unchanged, for a runtime consumer.

Atlas Scope (served same-origin under /scope) must compile client evidence in the browser at run
time rather than baking it into a static bundle: AssessHub serves static files outside its access
guard, so any evidence compiled into them would be readable cross-site. This route is the one
source it reads. What it must guarantee, each pinned below:

* the body is EXACTLY the persisted ``snapshots.snapshot_json`` bytes (the store's binding), never a
  re-serialisation — ``sha256(body)`` equals ``X-Snapshot-Sha256`` and ``len(body)`` equals
  ``X-Snapshot-Bytes``, and both equal the store's own binding for the row;
* it is ``Cache-Control: no-store`` (client evidence must not persist in a browser/proxy cache);
* it inherits every /api guard with NO per-route code: cross-site GET 403, foreign Host 403,
  non-loopback peer without a token 403, token mode without the session cookie 401;
* an unknown id is 404, not an empty 200.
"""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `backend` importable

from backend.app import create_app  # noqa: E402


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    monkeypatch.delenv("ASSESSHUB_ALLOWED_HOSTS", raising=False)
    return str(tmp_path / "raw.db")


@pytest.fixture()
def client(db_path):
    app = create_app(db_path=db_path, scope_dist_dir=None)
    with TestClient(app, base_url="http://localhost") as c:
        yield c


def _seed(client) -> int:
    r = client.post("/api/demo/seed")
    assert r.status_code == 200, r.text
    return r.json()["snapshot"]["id"]


def _stored_blob(db_path: str, snapshot_id: int) -> bytes:
    """The persisted bytes, read straight from SQLite — independent of any app/store accessor."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT CAST(snapshot_json AS BLOB) FROM snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    return bytes(row[0])


def test_raw_returns_the_stored_bytes_unchanged_with_their_binding(client, db_path):
    sid = _seed(client)
    r = client.get(f"/api/snapshots/{sid}/raw", headers={"sec-fetch-site": "same-origin"})
    assert r.status_code == 200, r.text[:300]
    body = r.content

    # exact persisted bytes, not a re-serialisation
    assert body == _stored_blob(db_path, sid)
    # the headers are the binding of THOSE bytes
    assert r.headers["x-snapshot-sha256"] == hashlib.sha256(body).hexdigest()
    assert r.headers["x-snapshot-bytes"] == str(len(body))
    # ...and equal the store's own binding (the digest compare/trend receipts already use)
    _snap, binding = client.app.state.store.get_bound_snapshot(sid)
    assert binding["sha256"] == "sha256:" + r.headers["x-snapshot-sha256"]
    assert binding["bytes"] == len(body)
    # the digest form is named, so a consumer never confuses it with a file-level digest
    assert r.headers["x-snapshot-digest-form"] == "assesshub-store-blob"

    assert r.headers["content-type"].split(";")[0].strip() == "application/json"
    assert r.headers["cache-control"] == "no-store"
    # it parses to the stored snapshot
    assert json.loads(body) == client.app.state.store.get_snapshot(sid)


def test_raw_unknown_snapshot_is_404(client):
    _seed(client)
    r = client.get("/api/snapshots/987654/raw")
    assert r.status_code == 404
    assert "x-snapshot-sha256" not in r.headers


def test_raw_refuses_a_cross_site_get(client):
    sid = _seed(client)
    r = client.get(f"/api/snapshots/{sid}/raw", headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 403
    assert "cross-site" in r.json()["detail"].lower()
    assert "x-snapshot-sha256" not in r.headers
    # control: the same request same-origin is served, so the 403 above is the guard, not a 404
    assert client.get(f"/api/snapshots/{sid}/raw",
                      headers={"sec-fetch-site": "same-origin"}).status_code == 200


def test_raw_refuses_a_foreign_host_header(client):
    sid = _seed(client)
    r = client.get(f"/api/snapshots/{sid}/raw", headers={"host": "evil.example"})
    assert r.status_code == 403
    assert "host" in r.json()["detail"].lower()
    assert client.get(f"/api/snapshots/{sid}/raw").status_code == 200


def test_raw_refuses_a_non_loopback_peer_without_a_token(db_path):
    app = create_app(db_path=db_path, scope_dist_dir=None)
    with TestClient(app, base_url="http://localhost") as local:
        sid = _seed(local)
        assert local.get(f"/api/snapshots/{sid}/raw").status_code == 200
    app = create_app(db_path=db_path, scope_dist_dir=None)
    with TestClient(app, base_url="http://localhost", client=("10.0.0.5", 50000)) as remote:
        r = remote.get(f"/api/snapshots/{sid}/raw")
        assert r.status_code == 403
        assert "ASSESSHUB_TOKEN" in r.json()["detail"]


def test_raw_in_token_mode_requires_the_session_cookie(db_path, monkeypatch):
    monkeypatch.setenv("ASSESSHUB_TOKEN", "raw-secret")
    app = create_app(db_path=db_path, scope_dist_dir=None)
    with TestClient(app, base_url="http://localhost") as c:
        assert c.post("/api/demo/seed",
                      headers={"Authorization": "Bearer raw-secret"}).status_code == 200
        sid = 1
        r = c.get(f"/api/snapshots/{sid}/raw")
        assert r.status_code == 401
        assert "x-snapshot-sha256" not in r.headers
        # control: the same-origin browser session (what a /scope page's fetch carries) is enough
        assert c.post("/api/session",
                      headers={"Authorization": "Bearer raw-secret"}).status_code == 204
        ok = c.get(f"/api/snapshots/{sid}/raw")
        assert ok.status_code == 200
        assert ok.headers["x-snapshot-sha256"] == hashlib.sha256(ok.content).hexdigest()


def test_a_scope_page_reads_raw_with_the_session_but_cannot_write_with_it(db_path, monkeypatch):
    """Same-origin write containment, token mode. The session cookie a /scope page carries is the
    same authority the AssessHub UI writes with, and the cross-site/CSRF guards pass a same-origin
    request. A /scope page's requests carry a same-origin Referer (Referrer-Policy: same-origin on
    every /scope response), and the /api guard refuses any non-GET request referred from /scope/ —
    before authentication, so neither the cookie nor the Bearer token itself unlocks a write.
    Defence in depth: the viewer has no write code; a hostile script could rewrite its Referer."""
    monkeypatch.setenv("ASSESSHUB_TOKEN", "raw-secret")
    scope_page = {"referer": "http://localhost/scope/snapshots/1/", "origin": "http://localhost",
                  "sec-fetch-site": "same-origin"}
    app = create_app(db_path=db_path, scope_dist_dir=None)
    with TestClient(app, base_url="http://localhost") as c:
        assert c.post("/api/demo/seed",
                      headers={"Authorization": "Bearer raw-secret"}).status_code == 200
        assert c.post("/api/session",
                      headers={"Authorization": "Bearer raw-secret"}).status_code == 204
        read = c.get("/api/snapshots/1/raw", headers=scope_page)
        assert read.status_code == 200
        assert read.headers["x-snapshot-sha256"] == hashlib.sha256(read.content).hexdigest()
        for extra in ({}, {"Authorization": "Bearer raw-secret"}):
            r = c.post("/api/campaigns", json={"name": "from scope"}, headers={**scope_page, **extra})
            assert r.status_code == 403, (extra, r.status_code, r.text[:200])
            assert "Atlas Scope" in r.json()["detail"]
            assert c.delete("/api/snapshots/1", headers={**scope_page, **extra}).status_code == 403
        assert c.get("/api/snapshots/1/raw").status_code == 200  # still there
        # control: the same session writes when the request is not referred from /scope/
        ui_page = {**scope_page, "referer": "http://localhost/campaigns"}
        created = c.post("/api/campaigns", json={"name": "from the UI"}, headers=ui_page)
        assert created.status_code == 201, created.text[:200]
