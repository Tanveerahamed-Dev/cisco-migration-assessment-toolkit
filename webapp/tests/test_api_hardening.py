"""API robustness tests for the AssessHub backend — the error/validation paths and the
on-the-fly compute-fallback layer that the happy-path e2e tests (which use the demo sample,
whose snapshots STORE every heavy section) never exercise.

Runs against an isolated temp SQLite store via the FastAPI TestClient — no real DB, no engine
subprocess (every case here is in-process: recompute fallbacks, HTTP guards, extract-time zip
validation, or monkeypatched limits).
"""

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `backend` importable
_ENGINE_TESTS = str(Path(__file__).resolve().parents[2] / "tests")
if _ENGINE_TESTS not in sys.path:
    sys.path.append(_ENGINE_TESTS)

from backend.app import create_app  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "test.db"))
    # base_url=localhost so the default Host passes the no-token DNS-rebinding guard (app.py
    # _request_host_allowed) — the dev server this emulates is reached over loopback.
    with TestClient(app, base_url="http://localhost") as c:
        yield c


# A snapshot lacking the heavy STORED sections — so every derived view recomputes on the fly.
MINIMAL_SNAP = {
    "script_version": "V3.23.0",
    "devices": {"r1": {"model": "C9300", "sw_version": "17.9"}},
    "health_scores": [{"switch": "r1", "band": "Good", "score": 80}],
}


def _campaign(client, name="c"):
    r = client.post("/api/campaigns", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _upload(client, cid, snap, label="s"):
    r = client.post(
        f"/api/campaigns/{cid}/snapshots",
        files={"file": ("s.json", json.dumps(snap).encode(), "application/json")},
        data={"label": label},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _zip_bytes(entries: dict) -> bytes:
    """entries: arcname -> str/bytes. Empty dict → a valid but entry-less ZIP."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def _ingest(client, cid, entries: dict):
    return client.post(
        f"/api/campaigns/{cid}/ingest",
        files={"file": ("c.zip", _zip_bytes(entries), "application/zip")},
        data={"label": "z"},
    )


# ── the compute-fallback layer (the marquee gap: 0% covered) ────────────────────
def test_compute_fallback_recomputes_every_unstored_section(client):
    """A snapshot with no stored design/review/coverage sections must trigger the server-side
    one-source-of-truth recompute for EVERY derived view (app.py:413-498,558-559)."""
    cid = _campaign(client)
    sid = _upload(client, cid, MINIMAL_SNAP)

    design = client.get(f"/api/snapshots/{sid}/design")
    assert design.status_code == 200, design.text
    assert isinstance(design.json()["decisions"], list)

    ar = client.get(f"/api/snapshots/{sid}/archreview")
    assert ar.status_code == 200, ar.text
    assert isinstance(ar.json().get("checks"), list)

    cov = client.get(f"/api/snapshots/{sid}/architecture_coverage")
    assert cov.status_code == 200, cov.text
    assert cov.json()["summary"]["n_classes"] == 27

    for path in ("causal_flows", "domain_packs", "design/nrfu"):
        r = client.get(f"/api/snapshots/{sid}/{path}")
        assert r.status_code == 200, f"{path}: {r.text}"

    # a second /design fetch exercises the _fallback_bp memoise cache-hit (app.py:429)
    assert client.get(f"/api/snapshots/{sid}/design").status_code == 200


# ── upload / snapshot validation ────────────────────────────────────────────────
def test_valid_json_that_is_not_a_snapshot_is_rejected(client):
    """Well-formed JSON without a top-level 'devices' (or not an object) is a 400, not a 500
    or a silent store (app.py:143)."""
    cid = _campaign(client)
    for body in (b'{"foo": 1}', b"[1, 2, 3]"):
        r = client.post(
            f"/api/campaigns/{cid}/snapshots",
            files={"file": ("x.json", body, "application/json")},
            data={"label": "x"},
        )
        assert r.status_code == 400, r.text
        assert "devices" in r.json()["detail"].lower()


def test_upload_snapshot_to_unknown_campaign_404(client):
    r = client.post(
        "/api/campaigns/999999/snapshots",
        files={"file": ("s.json", json.dumps(MINIMAL_SNAP).encode(), "application/json")},
        data={"label": "s"},
    )
    assert r.status_code == 404


def test_section_endpoint_distinguishes_missing_snapshot_from_missing_section(client):
    cid = _campaign(client)
    sid = _upload(client, cid, MINIMAL_SNAP)
    # whitelisted section name, but the snapshot itself does not exist → 404 (app.py:351)
    assert client.get("/api/snapshots/999999/section/punchlist").status_code == 404
    # whitelisted section name, absent from THIS (minimal) snapshot → 404 "not present" (app.py:353)
    r = client.get(f"/api/snapshots/{sid}/section/subnet_intelligence")
    assert r.status_code == 404
    assert "not present" in r.json()["detail"].lower()


# ── gate board ──────────────────────────────────────────────────────────────────
def test_whitespace_only_wave_rejected(client):
    """GateIn.wave has min_length=1, so a single space passes validation but strips to empty —
    caught by the explicit guard (app.py:271), distinct from the 422 length cap."""
    cid = _campaign(client)
    r = client.post(f"/api/campaigns/{cid}/gates", json={"wave": "   ", "gate": "commit", "decision": "go"})
    assert r.status_code == 400
    assert "empty" in r.json()["detail"].lower()


def test_gate_board_empty_for_campaign_without_snapshots(client):
    cid = _campaign(client)
    r = client.get(f"/api/campaigns/{cid}/gates")
    assert r.status_code == 200
    assert r.json()["waves"] == []


# ── campaign lifecycle (single-GET / DELETE routes) ─────────────────────────────
def test_campaign_get_and_delete_lifecycle(client):
    assert client.get("/api/campaigns/999999").status_code == 404
    cid = _campaign(client, "lifecycle")
    got = client.get(f"/api/campaigns/{cid}")
    assert got.status_code == 200 and got.json()["name"] == "lifecycle"
    assert client.delete(f"/api/campaigns/{cid}").status_code == 204
    assert client.get(f"/api/campaigns/{cid}").status_code == 404
    assert client.delete("/api/campaigns/999999").status_code == 404


# ── execution war-room error vocabulary ─────────────────────────────────────────
def _seed_execution(client):
    sid = client.post("/api/demo/seed").json()["snapshot"]["id"]
    ex = client.post(f"/api/snapshots/{sid}/executions", json={}).json()
    return ex["id"], ex["waves"][0]["group"]


def test_execution_step_on_unknown_wave_is_404(client):
    eid, _ = _seed_execution(client)
    r = client.post(f"/api/executions/{eid}/step", json={"wave": "NOPE", "index": 0, "status": "done"})
    assert r.status_code == 404
    assert "unknown wave" in r.json()["detail"].lower()


def test_execution_out_of_vocabulary_values_are_400(client):
    """The mutation models type these fields as plain str, so the engine's ValueError (not Pydantic)
    is what rejects a bad status/result/kind — surfaced as 400 (app.py:592-593)."""
    eid, wave = _seed_execution(client)
    assert client.post(f"/api/executions/{eid}/step", json={"wave": wave, "index": 0, "status": "frobnicate"}).status_code == 400
    assert client.post(f"/api/executions/{eid}/check", json={"wave": wave, "index": 0, "result": "bogus"}).status_code == 400
    assert client.post(f"/api/executions/{eid}/finish", json={"status": "nonsense"}).status_code == 400


def test_start_execution_with_no_derivable_waves_is_400(client):
    cid = _campaign(client)
    sid = _upload(client, cid, {"script_version": "V3.23.0", "devices": {}})
    r = client.post(f"/api/snapshots/{sid}/executions", json={})
    assert r.status_code == 400
    assert "wave" in r.json()["detail"].lower()


# ── unknown-id 404 sweep across the remaining single-entity routes ──────────────
def test_unknown_id_404_sweep(client):
    cases = [
        ("get", "/api/campaigns/999999/trend"),
        ("get", "/api/snapshots/999999"),
        ("get", "/api/snapshots/999999/executions"),
        ("get", "/api/executions/999999/report"),
        ("delete", "/api/executions/999999"),
        ("get", "/api/snapshots/999999/explorer"),
        ("get", "/api/snapshots/999999/deliverable/mop"),
        ("delete", "/api/snapshots/999999"),
    ]
    for method, path in cases:
        r = getattr(client, method)(path)
        assert r.status_code == 404, f"{method.upper()} {path} → {r.status_code}"
    assert client.post("/api/snapshots/999999/executions", json={}).status_code == 404
    assert client.post("/api/snapshots/999999/design", json={}).status_code == 404
    assert client.post("/api/compare", json={"old_id": 999999, "new_id": 999998}).status_code == 404


# ── ingest: extract-time validation (no engine subprocess) ──────────────────────
def test_ingest_empty_zip_rejected(client):
    cid = _campaign(client)
    r = _ingest(client, cid, {})
    assert r.status_code == 400
    assert "empty" in r.json()["detail"].lower()


def test_ingest_malformed_bundled_devices_json_rejected(client):
    cid = _campaign(client)
    r = _ingest(client, cid, {"fleet/core1/show_version.txt": "Cisco IOS", "fleet/devices.json": "{bad json"})
    assert r.status_code == 400
    assert "devices.json" in r.json()["detail"].lower()


def test_ingest_device_folders_at_different_depths_rejected(client):
    cid = _campaign(client)
    r = _ingest(client, cid, {"fleet/core1/show_version.txt": "x", "fleet/sub/access1/show_version.txt": "y"})
    assert r.status_code == 400
    assert "depth" in r.json()["detail"].lower()


# ── guard rails reached via monkeypatch (real thresholds are impractical to hit) ─
def test_oversized_upload_rejected_413(client, monkeypatch):
    import backend.ingest as ing
    monkeypatch.setattr(ing, "MAX_ARCHIVE_BYTES", 10)  # app reads this at request time
    cid = _campaign(client)
    r = client.post(
        f"/api/campaigns/{cid}/snapshots",
        files={"file": ("s.json", json.dumps(MINIMAL_SNAP).encode(), "application/json")},
        data={"label": "s"},
    )
    assert r.status_code == 413
    assert "limit" in r.json()["detail"].lower()


def test_engine_run_error_maps_to_500(client, monkeypatch):
    import backend.ingest as ing
    def _boom(raw):
        raise ing.EngineRunError("engine exploded")
    monkeypatch.setattr(ing, "run_collection_zip", _boom)
    cid = _campaign(client)
    r = _ingest(client, cid, {"fleet/core1/show_version.txt": "x"})
    assert r.status_code == 500


def test_unavailable_deliverable_returns_503(client, monkeypatch):
    import backend.deliverables as deliv
    monkeypatch.setattr(deliv, "availability", lambda: {})
    sid = client.post("/api/demo/seed").json()["snapshot"]["id"]
    r = client.get(f"/api/snapshots/{sid}/deliverable/mop")
    assert r.status_code == 503
