"""AssessHub compare exposes the same source-bound VTP owner consumed by the gate."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "webapp"))

from backend.app import create_app  # noqa: E402
from cisco_toolkit.vtp_extended import embedded_vtp_extended_evidence  # noqa: E402
from cisco_toolkit.vtp_safety import embedded_vtp_safety_baseline  # noqa: E402
from tests.test_vtp_extended_evidence import _sources, _spec  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "vtp-compare.db"))
    with TestClient(app, base_url="http://localhost") as value:
        yield value


def test_compare_api_projects_extended_vtp_state_and_canonical_gate(client, tmp_path):
    devices = {
        "access1": _spec(),
        "core1": _spec(),
        "core2": _spec(nxos=True, platform="nxos"),
    }
    before_v1, before_ext, _paths, _integrity = _sources(
        tmp_path / "before", devices)
    after_specs = dict(devices)
    after_specs["core1"] = _spec(pruning="vtp pruning")
    after_v1, after_ext, _paths, _integrity = _sources(
        tmp_path / "after", after_specs)

    golden = json.loads((_REPO / "tests" / "golden" / "snapshot.json").read_text(
        encoding="utf-8"))

    def snapshot(protected: dict, extended: dict, generated_at: str) -> bytes:
        value = dict(golden)
        value["generated_at"] = generated_at
        value["vtp_safety_baseline"] = embedded_vtp_safety_baseline(protected)
        value["vtp_extended_evidence"] = embedded_vtp_extended_evidence(extended)
        return json.dumps(value, separators=(",", ":"), allow_nan=False).encode("utf-8")

    campaign = client.post(
        "/api/campaigns",
        json={"name": "VTP source-bound compare", "engagement_id": "ENG-VTP"},
    )
    assert campaign.status_code == 201, campaign.text
    campaign_id = campaign.json()["id"]

    def upload(label: str, raw: bytes) -> int:
        response = client.post(
            f"/api/campaigns/{campaign_id}/snapshots",
            files={"file": (f"{label}.json", raw, "application/json")},
            data={"label": label},
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]

    before_id = upload("before", snapshot(
        before_v1, before_ext, "2026-08-20T00:00:00Z"))
    after_id = upload("after", snapshot(
        after_v1, after_ext, "2026-08-20T00:05:00Z"))
    response = client.post(
        "/api/compare", json={"old_id": before_id, "new_id": after_id})
    assert response.status_code == 200, response.text
    comparison = response.json()

    family = next(
        row for row in comparison["protocol_families"]["families"]
        if row["family"] == "vtp_safety")
    movement = next(row for row in family["changes"] if row["subject"] == "core1")
    assert movement["transition"] == "intent_changed"
    assert movement["decision_effect"] == "review"
    assert movement["expected"] is False
    assert movement["before_state"]["pruning_state"] == "not_configured"
    assert movement["after_state"]["pruning_state"] == "configured_enabled"
    assert movement["after_state"]["vlan_database_digest"].startswith("sha256:")
    assert movement["after_state"]["authentication_configured"] is False
    assert family["support_profile"]["evidence_contracts"] == [
        "vtp_safety_baseline/1", "vtp_extended_evidence/1",
    ]
    assert family["support_profile"]["scope"] == {
        "protocol": "VTP",
        "platforms": ["IOS", "IOS-XE", "NX-OS"],
        "collection_modes": ["live", "offline_import"],
        "commands": ["show vtp status", "show vlan brief", "show running-config"],
        "claim": "source-bound local and reconciled same-database safety",
    }
    receipts = family["source_receipt"]["source_receipts"]
    assert all(receipts[side]["comparison_source_bound"] is True
               for side in ("before", "after"))
    assert all(receipts[side]["comparison_source_basis"] ==
               "exact_snapshot_bytes_and_validated_owner_projection"
               for side in ("before", "after"))
    assert comparison["cutover_gate"]["protocol_family_review"] >= 1
    assert comparison["cutover_gate"]["verdict"] != "PASS"
    assert "password" not in movement["before_state"]
    assert "password" not in movement["after_state"]
