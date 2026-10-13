"""Round-3 real upload lifecycle: committed reads, failed preparation and measured scale intake."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
from threading import Event
import time

import pytest
from fastapi.testclient import TestClient

from cisco_toolkit.vlan_carriage import compute_vlan_carriage
from test_ui_projection_vlan_carriage import _round2_bundle
import test_vlan_carriage_budget as budget

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import engine, storage  # noqa: E402
from backend.app import create_app  # noqa: E402


# Reuse the actual 300-device / 200-VLAN / 1,500-cable producer fixture, without changing it.
fleet = budget.fleet


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    monkeypatch.delenv("ASSESSHUB_ALLOWED_HOSTS", raising=False)
    app = create_app(db_path=str(tmp_path / "carriage-ingestion.db"), scope_dist_dir=None)
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000),
                    raise_server_exceptions=False) as transport:
        yield transport


def _upload(client, campaign_id, snapshot, label):
    return client.post(
        f"/api/campaigns/{campaign_id}/snapshots",
        data={"label": label},
        files={"file": ("synthetic.snapshot.json", snapshot, "application/json")},
    )


def _small_snapshot_bytes():
    snapshot = _round2_bundle(None)
    snapshot["devices"] = {host: {} for host in snapshot["interfaces"]}
    snapshot["vlan_carriage"] = compute_vlan_carriage(
        snapshot["cable_map"], snapshot["interfaces"],
        snapshot["stp_topology_observations"], snapshot["vlan_cutover"])
    return json.dumps(snapshot, separators=(",", ":"), allow_nan=False).encode("utf-8")


@pytest.mark.parametrize("fail_after_first_row", [False, True])
def test_committed_http_reads_finish_while_real_upload_row_stream_is_held(
        client, monkeypatch, fail_after_first_row):
    """The review's first-next Event falsifier, also proving a later stream failure publishes nothing."""
    store = client.app.state.store
    campaign_id = store.create_campaign("Concurrent carriage preparation")["id"]
    payload = _small_snapshot_bytes()
    seeded = _upload(client, campaign_id, payload, "committed")
    assert seeded.status_code == 201
    existing_id = seeded.json()["id"]
    metadata_before = client.get(f"/api/snapshots/{existing_id}")
    raw_before = client.get(f"/api/snapshots/{existing_id}/raw")
    assert metadata_before.status_code == raw_before.status_code == 200
    with store._lock:
        parts_before = store._conn.execute("SELECT COUNT(*) FROM carriage_projection_v2_parts").fetchone()[0]
    observed = []
    store.add_snapshot_digest_observer(observed.append)
    original = engine.prepare_carriage_projection
    entered, release = Event(), Event()

    def gated_preparation(raw):
        preparation = original(raw)
        rows = preparation["rows"]

        def gated_rows():
            try:
                # Executed by first next(), not by the preparation factory.
                entered.set()
                assert release.wait(20), "test did not release the real preparation stream"
                if fail_after_first_row:
                    yield next(rows)  # Let the real consumer fully process a genuine row and its variants.
                    raise RuntimeError("synthetic failure after one prepared carriage row")
                yield from rows
            finally:
                rows.close()

        return {**preparation, "rows": gated_rows()}

    monkeypatch.setattr(engine, "prepare_carriage_projection", gated_preparation)

    def read_committed():
        metadata = client.get(f"/api/snapshots/{existing_id}")
        raw = client.get(f"/api/snapshots/{existing_id}/raw")
        document = client.get(f"/api/snapshots/{existing_id}/ui-projection/inventory")
        campaign = client.get(f"/api/campaigns/{campaign_id}")
        assert metadata.status_code == raw.status_code == document.status_code == campaign.status_code == 200
        assert metadata.json() == metadata_before.json()
        assert raw.content == raw_before.content
        assert raw.headers["x-snapshot-sha256"] == hashlib.sha256(raw.content).hexdigest()
        assert [item["id"] for item in campaign.json()["snapshots"]] == [existing_id]
        with store._lock:
            assert store._conn.in_transaction is False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(_upload, client, campaign_id, payload, "staged upload")
        try:
            assert entered.wait(20), "the multipart upload did not enter the genuine lazy row stream"
            assert not pending.done() and not release.is_set()
            assert pool.submit(read_committed).result(timeout=10) is True
            assert not pending.done() and not release.is_set()
        finally:
            release.set()
        response = pending.result(timeout=20)

    if fail_after_first_row:
        assert response.status_code == 500
        assert [item["id"] for item in store.list_snapshots(campaign_id)] == [existing_id]
        assert observed == []
        with store._lock:
            assert store._conn.execute("SELECT COUNT(*) FROM snapshot_authority").fetchone()[0] == 1
            assert store._conn.execute("SELECT COUNT(*) FROM carriage_projection_v2_parts").fetchone()[0] == parts_before
        # The failed producer must release its preparation resources and not poison the next upload.
        monkeypatch.setattr(engine, "prepare_carriage_projection", original)
        response = _upload(client, campaign_id, payload, "retry after preparation failure")
    assert response.status_code == 201
    new_id = response.json()["id"]
    assert new_id != existing_id
    assert len(observed) == 1
    assert {item["id"] for item in store.list_snapshots(campaign_id)} == {existing_id, new_id}
    assert client.get(f"/api/snapshots/{new_id}/ui-projection/inventory").status_code == 200
    assert client.get(f"/api/snapshots/{existing_id}/raw").content == raw_before.content


def test_actual_multipart_upload_reports_the_existing_budget_fleet(client, fleet, capsys, monkeypatch):
    """Time one actual HTTP request, including parse, provenance, summary, preparation and commit."""
    snapshot = {**fleet, "devices": {host: {} for host in fleet["interfaces"]}}
    snapshot["vlan_carriage"] = compute_vlan_carriage(
        snapshot["cable_map"], snapshot["interfaces"],
        snapshot["stp_topology_observations"], snapshot["vlan_cutover"])
    assert len(snapshot["devices"]) == 300
    assert len(snapshot["vlan_cutover"]) == 200
    assert len(snapshot["cable_map"]["cables"]) == 1500
    payload = json.dumps(snapshot, separators=(",", ":"), allow_nan=False).encode("utf-8")
    store = client.app.state.store
    campaign_id = store.create_campaign("Actual multipart carriage budget")["id"]
    original_stage = store._stage_carriage_projection
    original_publish = store._write_carriage_projection_locked
    stages, publications = [], []

    def measured_stage(preparation):
        start = time.perf_counter()
        staged = original_stage(preparation)
        stages.append((round(1000 * (time.perf_counter() - start), 1), len(staged)))
        return staged

    def measured_publish(*args):
        start = time.perf_counter()
        result = original_publish(*args)
        publications.append(round(1000 * (time.perf_counter() - start), 1))
        return result

    # Each wrapper observes exactly one ordinary call; there is no target preflight or warm-up.
    monkeypatch.setattr(store, "_stage_carriage_projection", measured_stage)
    monkeypatch.setattr(store, "_write_carriage_projection_locked", measured_publish)
    started = time.perf_counter()
    response = _upload(client, campaign_id, payload, "300-device multipart upload")
    upload_ms = round(1000 * (time.perf_counter() - started), 1)
    assert response.status_code == 201
    snapshot_id = response.json()["id"]
    stored_raw, binding = store.get_snapshot_blob(snapshot_id)
    assert json.loads(stored_raw)["vlan_carriage"] == snapshot["vlan_carriage"]
    assert binding["sha256"] == "sha256:" + hashlib.sha256(stored_raw).hexdigest()
    assert response.json()["n_devices"] == 300
    assert [row["id"] for row in store.list_snapshots(campaign_id)] == [snapshot_id]
    derivative_bytes = store.get_carriage_projection_payload_bytes(snapshot_id)
    assert 0 < derivative_bytes <= storage.CARRIAGE_PROJECTION_PAYLOAD_LIMIT
    assert len(stages) == len(publications) == 1
    framing_bytes = stages[0][1] - derivative_bytes
    assert 0 < framing_bytes <= storage._CARRIAGE_STAGING_METADATA_LIMIT
    assert client.get(f"/api/snapshots/{snapshot_id}/ui-projection/inventory").status_code == 200
    budget._report(capsys, "multipart-upload", {
        "actual_http_request": True, "upload_ms": upload_ms, "uploaded_bytes": len(payload),
        "transport": "in-process ASGI multipart", "external_network_measured": False,
        "stored_source_bytes": len(stored_raw), "stored_derivative_payload_bytes": derivative_bytes,
        "payload_byte_limit": storage.CARRIAGE_PROJECTION_PAYLOAD_LIMIT,
        "row_stream_stage_ms": stages[0][0], "stage_bytes": stages[0][1],
        "stage_framing_bytes": framing_bytes, "stage_framing_limit": storage._CARRIAGE_STAGING_METADATA_LIMIT,
        "part_publication_ms": publications[0], "part_publication_includes_commit": False,
        "devices": 300, "vlans": 200, "cables": 1500,
        "includes_sqlite_file_overhead": False, "rss_measured": False,
    })
