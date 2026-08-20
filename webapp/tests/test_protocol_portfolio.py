"""Source-bound single-snapshot Protocol Assurance receipt and export contracts."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import create_app  # noqa: E402
from backend.protocol_portfolio import SUBJECT_RENDER_CAP  # noqa: E402
from cisco_toolkit.protocol_assurance import canonical_sha256  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "portfolio.db"))
    with TestClient(app, base_url="http://localhost") as value:
        yield value


def _campaign(client: TestClient) -> int:
    response = client.post("/api/campaigns", json={"name": "protocol portfolio"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _upload(client: TestClient, snapshot: dict, *, pretty: bool = False) -> tuple[int, bytes]:
    campaign_id = _campaign(client)
    raw = json.dumps(snapshot, indent=2 if pretty else None).encode("utf-8")
    response = client.post(
        f"/api/campaigns/{campaign_id}/snapshots",
        files={"file": ("snapshot.json", raw, "application/json")},
        data={"label": "portfolio source"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"], raw


def _minimal(**extra) -> dict:
    return {"script_version": "portfolio-test/1", "devices": {"sw1": {}}, **extra}


def test_single_snapshot_receipt_binds_exact_persisted_blob_and_script_owner(client):
    snapshot_id, upload_bytes = _upload(client, _minimal(), pretty=True)
    response = client.get(f"/api/snapshots/{snapshot_id}/section/protocol_assurance")
    assert response.status_code == 200, response.text
    receipt = response.json()["data"]["receipt"]

    store = client.app.state.store
    with store._lock:
        row = store._conn.execute(
            "SELECT CAST(snapshot_json AS BLOB) AS blob FROM snapshots WHERE id=?",
            (snapshot_id,),
        ).fetchone()
    persisted = bytes(row["blob"])

    source = receipt["source_binding"]
    assert receipt["schema"] == "protocol_single_snapshot_receipt/1"
    assert receipt["owns_score"] is False and receipt["owns_verdict"] is False
    assert receipt["custody_status"] == "bound"
    assert source["source"] == "persisted snapshots.snapshot_json blob"
    assert source["bytes"] == len(persisted)
    assert source["sha256"] == "sha256:" + hashlib.sha256(persisted).hexdigest()
    assert persisted != upload_bytes  # upload bytes are normalized/stamped and are not retained
    assert receipt["script_owner"] == {
        "source": "snapshot.script_version + snapshots.script_version column",
        "snapshot_value": "portfolio-test/1",
        "stored_value": "portfolio-test/1",
        "status": "bound",
    }
    assert "does not retain or claim the original upload bytes" in receipt["custody_note"]
    unsigned = dict(receipt)
    claimed = unsigned.pop("receipt_sha256")
    assert claimed == canonical_sha256(unsigned)

    meta = client.get(f"/api/snapshots/{snapshot_id}").json()
    section = next(row for row in meta["summary"]["sections"] if row["key"] == "protocol_assurance")
    assert section["label"] == "Protocol Assurance"
    assert section["count"] == receipt["summary"]["n_families"] == len(receipt["support_profiles"])


def test_missing_and_malformed_family_evidence_remain_neutral_not_verified(client):
    snapshot_id, _ = _upload(
        client,
        _minimal(bgp_configured_peer_baseline="malformed", protocol_assessability=5),
    )
    response = client.get(f"/api/snapshots/{snapshot_id}/section/protocol_assurance")
    assert response.status_code == 200, response.text
    receipt = response.json()["data"]["receipt"]
    families = {row["family"]: row for row in receipt["families"]}

    bgp = families["bgp_configured_peer"]
    assert bgp["evidence_status"] == "not_verified"
    assert bgp["subject_total"] == 0
    assert bgp["subjects"] == {"total": 0, "rendered": 0, "omitted": 0, "rows": []}
    assert "malformed" in bgp["status_reason"].lower() or "invalid" in bgp["status_reason"].lower()

    # No family is upgraded merely because its executable support profile exists.
    assert all(row["evidence_status"] != "observed" for row in receipt["families"])
    assert receipt["summary"]["by_evidence_status"]["not_verified"] >= 1
    assert all(profile["implementation_state"] == "implemented" for profile in receipt["support_profiles"])


def test_subject_cap_is_disclosed_and_complete_export_is_uncapped(client):
    golden = Path(__file__).resolve().parents[2] / "tests" / "golden" / "snapshot.json"
    snapshot = json.loads(golden.read_text(encoding="utf-8"))
    snapshot["routing_neighbors"] = {
        "core1": {
            "ospf": [
                {
                    "neighbor": f"10.200.{index // 254}.{index % 254 + 1}",
                    "address": f"10.200.{index // 254}.{index % 254 + 1}",
                    "interface": f"Vlan{index + 1}",
                    "state": "FULL/DR",
                }
                for index in range(SUBJECT_RENDER_CAP + 5)
            ],
            "bgp": [],
            "eigrp": [],
        }
    }
    snapshot_id, _ = _upload(client, snapshot)

    section = client.get(f"/api/snapshots/{snapshot_id}/section/protocol_assurance").json()["data"]
    receipt = section["receipt"]
    ipv4 = next(row for row in receipt["families"] if row["family"] == "ipv4_routing_adjacency")
    assert ipv4["subjects"]["total"] == SUBJECT_RENDER_CAP + 5
    assert ipv4["subjects"]["rendered"] == SUBJECT_RENDER_CAP
    assert ipv4["subjects"]["omitted"] == 5
    assert len(ipv4["subjects"]["rows"]) == SUBJECT_RENDER_CAP
    assert section["complete_export"]["url"].endswith(
        f"/snapshots/{snapshot_id}/protocol-assurance/export"
    )

    exported = client.get(section["complete_export"]["url"])
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-disposition"].endswith(
        f'protocol-assurance-snapshot-{snapshot_id}.json"'
    )
    payload = exported.json()
    assert payload["schema"] == "protocol_single_snapshot_export/1"
    complete_ipv4 = next(row for row in payload["families"] if row["family"] == "ipv4_routing_adjacency")
    assert complete_ipv4["subject_total"] == SUBJECT_RENDER_CAP + 5
    assert len(complete_ipv4["subjects"]) == SUBJECT_RENDER_CAP + 5
    assert canonical_sha256(payload) == receipt["complete_export"]["sha256"]
    assert exported.headers["x-atlas-content-sha256"] == receipt["complete_export"]["sha256"]


def test_protocol_assurance_export_404s_for_unknown_snapshot(client):
    assert client.get("/api/snapshots/999999/section/protocol_assurance").status_code == 404
    assert client.get("/api/snapshots/999999/protocol-assurance/export").status_code == 404
