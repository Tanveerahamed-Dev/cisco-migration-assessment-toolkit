"""Canonical source-bound receipts on the persisted campaign Trend surface."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient


_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "webapp"))

from backend import engine  # noqa: E402
from backend.app import create_app  # noqa: E402
from cisco_toolkit.protocol_assurance import (  # noqa: E402
    bind_snapshot_json_bytes,
    bound_snapshot_source,
)


def _wire(value: object) -> object:
    """Normalize dict subclasses exactly as the HTTP JSON response does."""
    return json.loads(json.dumps(value, allow_nan=False))


def _binding(snapshot, *, snapshot_id: int, campaign_id: int, engagement_id: str) -> dict:
    marker = bound_snapshot_source(snapshot)
    return {
        "source": "persisted snapshots.snapshot_json blob",
        "sha256": marker["sha256"],
        "bytes": marker["bytes"],
        "snapshot_id": snapshot_id,
        "campaign_id": campaign_id,
        "engagement_id": engagement_id,
        "label": f"wave-{snapshot_id}",
        "script_version": snapshot["script_version"],
    }


def test_trend_route_carries_every_adjacent_canonical_comparison_in_order(tmp_path):
    app = create_app(db_path=str(tmp_path / "trend-receipts.db"))
    raw = (_REPO / "tests" / "golden" / "snapshot.json").read_bytes()

    with TestClient(app, base_url="http://localhost") as client:
        campaign = client.post(
            "/api/campaigns",
            json={"name": "receipt trend", "engagement_id": "ENG-TREND"},
        )
        assert campaign.status_code == 201, campaign.text
        campaign_id = campaign.json()["id"]

        ids = []
        for label in ("before", "middle", "after"):
            uploaded = client.post(
                f"/api/campaigns/{campaign_id}/snapshots",
                files={"file": (f"{label}.json", raw, "application/json")},
                data={"label": label},
            )
            assert uploaded.status_code == 201, uploaded.text
            ids.append(uploaded.json()["id"])

        trend_response = client.get(f"/api/campaigns/{campaign_id}/trend")
        assert trend_response.status_code == 200, trend_response.text
        trend = trend_response.json()

        assert trend["adjacent_comparison_status"] == {
            "schema": "campaign_adjacent_comparison_set/1",
            "status": "verified",
            "n_pairs_total": 2,
            "n_pairs_returned": 2,
            "complete": True,
            "note": (
                "Canonical comparisons were produced from the exact persisted bytes for every "
                "adjacent campaign pair."
            ),
        }
        pairs = trend["adjacent_comparisons"]
        assert [row["index"] for row in pairs] == [0, 1]
        assert [(row["before_snapshot_id"], row["after_snapshot_id"]) for row in pairs] == [
            (ids[0], ids[1]),
            (ids[1], ids[2]),
        ]
        assert [(row["before_label"], row["after_label"]) for row in pairs] == [
            ("before", "middle"),
            ("middle", "after"),
        ]

        for index, (before_id, after_id) in enumerate(zip(ids, ids[1:])):
            direct = client.post(
                "/api/compare", json={"old_id": before_id, "new_id": after_id}
            )
            assert direct.status_code == 200, direct.text
            assert pairs[index]["comparison"] == direct.json()
            assert pairs[index]["comparison"]["comparison_receipt"]["receipt_sha256"].startswith(
                "sha256:"
            )
            assert pairs[index]["comparison"]["cutover_gate"]["schema"] == "cutover_gate/1"


def test_trend_route_never_bridges_a_missing_middle_snapshot(tmp_path, monkeypatch):
    app = create_app(db_path=str(tmp_path / "trend-race.db"))
    raw = (_REPO / "tests" / "golden" / "snapshot.json").read_bytes()

    with TestClient(app, base_url="http://localhost") as client:
        campaign = client.post(
            "/api/campaigns",
            json={"name": "race-safe trend", "engagement_id": "ENG-TREND-RACE"},
        ).json()
        ids = []
        for label in ("before", "middle", "after"):
            uploaded = client.post(
                f"/api/campaigns/{campaign['id']}/snapshots",
                files={"file": (f"{label}.json", raw, "application/json")},
                data={"label": label},
            )
            assert uploaded.status_code == 201, uploaded.text
            ids.append(uploaded.json()["id"])

        get_bound_snapshot = app.state.store.get_bound_snapshot

        def missing_middle(snapshot_id):
            return None if snapshot_id == ids[1] else get_bound_snapshot(snapshot_id)

        monkeypatch.setattr(app.state.store, "get_bound_snapshot", missing_middle)
        response = client.get(f"/api/campaigns/{campaign['id']}/trend")

        assert response.status_code == 200, response.text
        trend = response.json()
        assert trend["verdict"] == "INDETERMINATE"
        assert trend["adjacent_comparisons"] == []
        assert trend["adjacent_comparison_status"] == {
            "schema": "campaign_adjacent_comparison_set/1",
            "status": "not_verified",
            "n_pairs_total": 2,
            "n_pairs_returned": 0,
            "complete": False,
            "note": (
                "Canonical adjacent comparisons are NOT VERIFIED because a source snapshot "
                "disappeared while the ordered campaign was read; no non-adjacent pair was "
                "substituted. Retry against a stable campaign roster."
            ),
        }


def test_legacy_or_detached_trend_inputs_never_synthesize_canonical_custody():
    snapshots = [
        {
            "script_version": "V3.23.0",
            "devices": {"sw1": {}},
            "health_scores": [],
            "punchlist": [],
        },
        {
            "script_version": "V3.23.0",
            "devices": {"sw1": {}},
            "health_scores": [],
            "punchlist": [],
        },
    ]
    legacy = engine.campaign_trend(snapshots)
    assert legacy["adjacent_comparisons"] == []
    assert legacy["adjacent_comparison_status"]["status"] == "not_verified"

    # Even a complete-looking receipt cannot recreate the process-local exact-byte marker after a
    # JSON/dict round trip.
    detached_bindings = [
        {
            "source": "persisted snapshots.snapshot_json blob",
            "sha256": "sha256:" + str(index) * 64,
            "bytes": 123,
            "snapshot_id": index,
            "campaign_id": 7,
            "engagement_id": "ENG-DETACHED",
            "label": f"wave-{index}",
            "script_version": "V3.23.0",
        }
        for index in (1, 2)
    ]
    detached = engine.campaign_trend(snapshots, source_bindings=detached_bindings)
    assert detached["adjacent_comparisons"] == []
    assert detached["adjacent_comparison_status"]["status"] == "not_verified"


def test_trend_fails_closed_when_exact_bindings_cross_campaign_or_engagement():
    raw = json.dumps(
        {
            "script_version": "V3.23.0",
            "devices": {"sw1": {}},
            "health_scores": [],
            "punchlist": [],
        },
        separators=(",", ":"),
    ).encode("utf-8")
    before = bind_snapshot_json_bytes(raw)
    after = bind_snapshot_json_bytes(raw)
    bindings = [
        _binding(before, snapshot_id=1, campaign_id=10, engagement_id="ENG-A"),
        _binding(after, snapshot_id=2, campaign_id=20, engagement_id="ENG-B"),
    ]

    trend = engine.campaign_trend([before, after], source_bindings=bindings)

    assert trend["verdict"] == "INDETERMINATE"
    assert trend["adjacent_comparison_status"]["status"] == "not_comparable"
    assert "cross campaign" in trend["adjacent_comparison_status"]["note"]
    assert "cross engagement" in trend["adjacent_comparison_status"]["note"]
    assert len(trend["adjacent_comparisons"]) == 1
    comparison = trend["adjacent_comparisons"][0]["comparison"]
    assert comparison["comparison_admission"]["status"] == "not_comparable"
    assert comparison["cutover_gate"]["verdict"] == "INDETERMINATE"
    assert _wire(comparison) == comparison
