"""Decision-receipt hardening for AssessHub compare and execution flows.

These tests stay separate from the broad backend end-to-end module so the Release-1 custody and
race invariants can be run as a small, high-signal gate.  They exercise the public API wherever an
operator can reach the behavior and use ``Store`` directly only for database transaction/trigger
properties that HTTP cannot observe.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "webapp"))

from backend import engine, execution  # noqa: E402
from backend.app import create_app  # noqa: E402
from backend.storage import Store  # noqa: E402
from cisco_toolkit.html import compute_cutover_gate  # noqa: E402
from cisco_toolkit.protocol_assurance import receipt_envelope  # noqa: E402


_GOLDEN = _REPO / "tests" / "golden" / "snapshot.json"


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "receipts.db"))
    with TestClient(app, base_url="http://localhost") as test_client:
        yield test_client


def _campaign(client: TestClient, name: str, engagement_id: str) -> dict:
    response = client.post(
        "/api/campaigns",
        json={"name": name, "engagement_id": engagement_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _upload(client: TestClient, campaign_id: int, label: str, raw: bytes | None = None) -> int:
    response = client.post(
        f"/api/campaigns/{campaign_id}/snapshots",
        files={"file": (f"{label}.json", raw or _GOLDEN.read_bytes(), "application/json")},
        data={"label": label},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _post_change_raw(*, collected_at: datetime | None = None) -> bytes:
    snapshot = json.loads(_GOLDEN.read_bytes())
    snapshot["collected_at"] = (collected_at or datetime.now(timezone.utc)).isoformat()
    return json.dumps(snapshot, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _pair(client: TestClient, *, engagement_id: str = "ENG-RECEIPTS") -> tuple[int, int]:
    campaign = _campaign(client, "receipt pair", engagement_id)
    return (
        _upload(client, campaign["id"], "before"),
        _upload(client, campaign["id"], "after"),
    )


def _start(client: TestClient, snapshot_id: int) -> dict:
    response = client.post(
        f"/api/snapshots/{snapshot_id}/executions",
        json={"label": "receipt run", "operator": "test"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _action_all_steps(client: TestClient, run: dict) -> dict:
    current = run
    for wave in list(current.get("waves") or []):
        for index, step in enumerate(list(wave.get("steps") or [])):
            if step.get("status") == "pending":
                response = client.post(
                    f"/api/executions/{current['id']}/step",
                    json={"wave": wave["group"], "index": index, "status": "done"},
                )
                assert response.status_code == 200, response.text
                current = response.json()
    return current


def _post_change_pair(
        client: TestClient, *, engagement_id: str = "ENG-RECEIPTS"
) -> tuple[int, int, dict]:
    """Create the after snapshot only after the execution start is durably recorded."""
    campaign = _campaign(client, "receipt pair", engagement_id)
    before_id = _upload(client, campaign["id"], "before")
    run = _start(client, before_id)
    run = _action_all_steps(client, run)
    implementation = execution.implementation_evidence_binding(run)
    assert implementation["valid"] is True
    collected_at = datetime.fromisoformat(implementation["completed_at"]) + timedelta(
        microseconds=1
    )
    after_id = _upload(
        client, campaign["id"], "after", _post_change_raw(collected_at=collected_at)
    )
    return before_id, after_id, run


def _persisted_blob(store: Store, snapshot_id: int) -> bytes:
    with store._lock:
        row = store._conn.execute(
            "SELECT CAST(snapshot_json AS BLOB) AS payload FROM snapshots WHERE id=?",
            (snapshot_id,),
        ).fetchone()
    assert row is not None
    payload = row["payload"]
    return payload.tobytes() if isinstance(payload, memoryview) else bytes(payload)


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _rehash_complete_comparison(comparison: dict) -> None:
    """Rebuild both detached and execution digests after an adversarial payload rewrite."""
    additive = {
        "comparison_schema", "comparison_admission", "change_intent", "protocol_families",
        "precert", "cutover_gate", "operator_evidence", "comparison_receipt",
    }
    delta = {key: value for key, value in comparison.items() if key not in additive}
    comparison["comparison_receipt"] = receipt_envelope(
        admission=comparison["comparison_admission"],
        change_intent=comparison["change_intent"],
        protocol_families=comparison["protocol_families"],
        delta=delta,
        precert=comparison["precert"],
        cutover_gate=comparison["cutover_gate"],
        operator_evidence=comparison["operator_evidence"],
    )


def test_execution_compare_refuses_cross_campaign_and_engagement_without_mutation(client):
    first = _campaign(client, "first", "ENG-A")
    same_engagement = _campaign(client, "same engagement", "ENG-A")
    other_engagement = _campaign(client, "other engagement", "ENG-B")
    before_id = _upload(client, first["id"], "before")
    same_engagement_id = _upload(client, same_engagement["id"], "same-engagement")
    other_engagement_id = _upload(client, other_engagement["id"], "other-engagement")
    run = _start(client, before_id)
    store = client.app.state.store
    original = store.get_execution(run["id"])
    assert original is not None

    cross_engagement = client.post(
        f"/api/executions/{run['id']}/compare",
        json={"after_snapshot_id": other_engagement_id},
    )
    assert cross_engagement.status_code == 409
    assert "different engagements" in cross_engagement.json()["detail"]

    cross_campaign = client.post(
        f"/api/executions/{run['id']}/compare",
        json={"after_snapshot_id": same_engagement_id},
    )
    assert cross_campaign.status_code == 409
    assert "different campaigns" in cross_campaign.json()["detail"]

    unchanged = store.get_execution(run["id"])
    assert unchanged is not None
    assert unchanged["_state_json"] == original["_state_json"]
    assert unchanged["comparisons"] == []


def test_execution_compare_refuses_older_snapshot_as_post_change_evidence(client):
    campaign = _campaign(client, "reverse order", "ENG-REVERSE")
    older_id = _upload(client, campaign["id"], "older candidate")
    before_id = _upload(client, campaign["id"], "execution start")
    run = _start(client, before_id)
    run = _action_all_steps(client, run)

    response = client.post(
        f"/api/executions/{run['id']}/compare",
        json={"after_snapshot_id": older_id},
    )

    assert response.status_code == 409
    assert "uploaded after this execution started" in response.json()["detail"]
    stored = client.app.state.store.get_execution(run["id"])
    assert stored is not None
    assert stored["comparisons"] == []
    assert "latest_comparison" not in stored["state"]


@pytest.mark.parametrize("capture_kind", ["missing", "stale", "naive", "future"])
def test_execution_compare_refuses_unproven_post_change_capture_time(client, capture_kind):
    campaign = _campaign(client, f"capture {capture_kind}", f"ENG-CAPTURE-{capture_kind}")
    before_id = _upload(client, campaign["id"], "before")
    run = _start(client, before_id)
    run = _action_all_steps(client, run)
    implementation = execution.implementation_evidence_binding(run)
    assert implementation["valid"] is True
    started_at = datetime.fromisoformat(implementation["completed_at"])
    if capture_kind == "missing":
        raw = _GOLDEN.read_bytes()
    elif capture_kind == "stale":
        raw = _post_change_raw(collected_at=started_at - timedelta(minutes=1))
    elif capture_kind == "naive":
        snapshot = json.loads(_GOLDEN.read_bytes())
        snapshot["collected_at"] = started_at.replace(tzinfo=None).isoformat()
        raw = json.dumps(snapshot, separators=(",", ":")).encode("utf-8")
    else:
        raw = _post_change_raw(collected_at=started_at + timedelta(days=1))
    after_id = _upload(client, campaign["id"], f"after {capture_kind}", raw)

    response = client.post(
        f"/api/executions/{run['id']}/compare",
        json={"after_snapshot_id": after_id},
    )

    assert response.status_code == 409
    assert "uploaded after this execution started" in response.json()["detail"]
    stored = client.app.state.store.get_execution(run["id"])
    assert stored is not None and stored["comparisons"] == []


def test_legacy_execution_cannot_be_backfilled_through_route_or_store(client):
    before_id, after_id = _pair(client)
    store = client.app.state.store
    before = store.get_snapshot(before_id)
    assert before is not None
    legacy_state = execution.start_run(before, "legacy run", "test")
    legacy_id = store.create_execution(before_id, legacy_state)
    original = store.get_execution(legacy_id)
    assert original is not None

    response = client.post(
        f"/api/executions/{legacy_id}/compare",
        json={"after_snapshot_id": after_id},
    )
    assert response.status_code == 409
    assert "predates canonical comparison receipts" in response.json()["detail"]

    canonical = client.post(
        "/api/compare", json={"old_id": before_id, "new_id": after_id}
    )
    assert canonical.status_code == 200, canonical.text
    receipt = engine.compact_execution_comparison(
        canonical.json(),
        before_snapshot_id=before_id,
        after_snapshot_id=after_id,
    )
    result = store.append_execution_comparison_if_unchanged(
        legacy_id, original["_state_json"], receipt
    )
    assert result == {"status": "legacy"}
    unchanged = store.get_execution(legacy_id)
    assert unchanged is not None
    assert unchanged["_state_json"] == original["_state_json"]
    assert unchanged["comparisons"] == []


def test_finished_execution_cannot_append_through_route_or_store(client):
    before_id, after_id = _pair(client)
    run = _start(client, before_id)
    finished = client.post(
        f"/api/executions/{run['id']}/finish",
        json={"status": "aborted", "note": "stop", "operator": "test"},
    )
    assert finished.status_code == 200, finished.text
    assert finished.json()["status"] == "aborted"

    response = client.post(
        f"/api/executions/{run['id']}/compare",
        json={"after_snapshot_id": after_id},
    )
    assert response.status_code == 409
    assert "finished execution" in response.json()["detail"]

    canonical = client.post(
        "/api/compare", json={"old_id": before_id, "new_id": after_id}
    )
    assert canonical.status_code == 200, canonical.text
    receipt = engine.compact_execution_comparison(
        canonical.json(),
        before_snapshot_id=before_id,
        after_snapshot_id=after_id,
    )
    store = client.app.state.store
    current = store.get_execution(run["id"])
    assert current is not None
    result = store.append_execution_comparison_if_unchanged(
        run["id"], current["_state_json"], receipt
    )
    assert result == {"status": "closed"}
    assert store.list_execution_comparisons(run["id"]) == []


def test_store_rejects_rehashed_miswired_and_detached_tampered_receipts(client):
    campaign = _campaign(client, "miswire", "ENG-MISWIRE")
    before_id = _upload(client, campaign["id"], "before")
    run = _start(client, before_id)
    run = _action_all_steps(client, run)
    implementation = execution.implementation_evidence_binding(run)
    assert implementation["valid"] is True
    collected_at = datetime.fromisoformat(implementation["completed_at"]) + timedelta(
        microseconds=1
    )
    intended_after_id = _upload(
        client,
        campaign["id"],
        "intended-after",
        _post_change_raw(collected_at=collected_at),
    )
    wrong_after_id = _upload(
        client,
        campaign["id"],
        "wrong-after",
        _post_change_raw(collected_at=collected_at),
    )
    store = client.app.state.store
    original = store.get_execution(run["id"])
    assert original is not None

    wrong_comparison = client.post(
        "/api/compare", json={"old_id": before_id, "new_id": wrong_after_id}
    )
    assert wrong_comparison.status_code == 200, wrong_comparison.text
    # This wrapper is internally self-consistent and freshly rehashed, but its outer after ID
    # deliberately names a different persisted source than the detached admission envelope.
    miswired = engine.compact_execution_comparison(
        wrong_comparison.json(),
        before_snapshot_id=before_id,
        after_snapshot_id=intended_after_id,
        after_collected_at=store.get_snapshot(intended_after_id)["collected_at"],
        implementation_binding=implementation,
    )
    assert store.append_execution_comparison_if_unchanged(
        run["id"], original["_state_json"], miswired
    ) == {"status": "source_mismatch"}

    correct_comparison = client.post(
        "/api/compare", json={"old_id": before_id, "new_id": intended_after_id}
    )
    assert correct_comparison.status_code == 200, correct_comparison.text
    correct = engine.compact_execution_comparison(
        correct_comparison.json(),
        before_snapshot_id=before_id,
        after_snapshot_id=intended_after_id,
        after_collected_at=store.get_snapshot(intended_after_id)["collected_at"],
        implementation_binding=implementation,
    )
    tampered = deepcopy(correct)
    tampered["comparison"]["cutover_gate"]["verdict"] = "TAMPERED"
    unsigned = dict(tampered)
    unsigned.pop("receipt_sha256")
    tampered["receipt_sha256"] = _canonical_sha256(unsigned)
    with pytest.raises(ValueError, match="detached receipt is invalid"):
        store.append_execution_comparison_if_unchanged(
            run["id"], original["_state_json"], tampered
        )

    # Hash integrity alone is insufficient.  A fully rewritten decision and freshly rebuilt
    # detached/outer hashes must still be refused because cutover_gate/1 is the sole verdict owner.
    forged = deepcopy(correct)
    forged["comparison"]["cutover_gate"]["verdict"] = "PASS"
    forged["comparison"]["cutover_gate"]["operator_note"] = "forged all-clear"
    _rehash_complete_comparison(forged["comparison"])
    forged_unsigned = dict(forged)
    forged_unsigned.pop("receipt_sha256")
    forged["receipt_sha256"] = _canonical_sha256(forged_unsigned)
    assert store.append_execution_comparison_if_unchanged(
        run["id"], original["_state_json"], forged
    ) == {"status": "comparison_mismatch"}

    # Recomputing the gate as well as every digest still cannot substitute attacker-authored
    # decision inputs for the comparison derived from the persisted snapshot pair.
    forged_inputs = deepcopy(correct)
    forged_comparison = forged_inputs["comparison"]
    forged_comparison["verdict_note"] = "This basis did not come from the persisted source bytes."
    additive = {
        "comparison_schema", "comparison_admission", "change_intent", "protocol_families",
        "precert", "cutover_gate", "operator_evidence", "comparison_receipt",
    }
    forged_delta = {
        key: value for key, value in forged_comparison.items() if key not in additive
    }
    forged_comparison["cutover_gate"] = compute_cutover_gate(
        forged_delta,
        forged_comparison["precert"],
        comparison_admission=forged_comparison["comparison_admission"],
        protocol_family_changes=forged_comparison["protocol_families"],
    )
    _rehash_complete_comparison(forged_comparison)
    forged_inputs_unsigned = dict(forged_inputs)
    forged_inputs_unsigned.pop("receipt_sha256")
    forged_inputs["receipt_sha256"] = _canonical_sha256(forged_inputs_unsigned)
    assert store.append_execution_comparison_if_unchanged(
        run["id"], original["_state_json"], forged_inputs
    ) == {"status": "comparison_mismatch"}

    # Python mapping equality aliases JSON booleans and numbers (False == 0).  A receipt with that
    # type-only rewrite and freshly rebuilt hashes must still fail the exact canonical JSON check
    # performed against the under-lock recomputation.
    type_collision = deepcopy(correct)
    collision_comparison = type_collision["comparison"]
    assert type(collision_comparison["health"]["n_regressed"]) is int
    assert collision_comparison["health"]["n_regressed"] == 0
    collision_comparison["health"]["n_regressed"] = False
    collision_delta = {
        key: value for key, value in collision_comparison.items() if key not in additive
    }
    collision_comparison["cutover_gate"] = compute_cutover_gate(
        collision_delta,
        collision_comparison["precert"],
        comparison_admission=collision_comparison["comparison_admission"],
        protocol_family_changes=collision_comparison["protocol_families"],
    )
    _rehash_complete_comparison(collision_comparison)
    collision_unsigned = dict(type_collision)
    collision_unsigned.pop("receipt_sha256")
    type_collision["receipt_sha256"] = _canonical_sha256(collision_unsigned)
    assert store.append_execution_comparison_if_unchanged(
        run["id"], original["_state_json"], type_collision
    ) == {"status": "comparison_mismatch"}

    # Even a previously valid canonical receipt is stale if the persisted source blob changes
    # before append (the public API never updates it, but a second process/corrupt write must fail).
    original_after = store.get_snapshot(intended_after_id)
    assert original_after is not None
    changed_source = json.dumps(
        {
            "script_version": "V3.23.0",
            "devices": {"CHANGED": {}},
            "collected_at": original_after["collected_at"],
        },
        separators=(",", ":"),
    )
    with store._lock:
        store._conn.execute(
            "UPDATE snapshots SET snapshot_json=? WHERE id=?",
            (changed_source, intended_after_id),
        )
        store._conn.commit()
    assert store.append_execution_comparison_if_unchanged(
        run["id"], original["_state_json"], correct
    ) == {"status": "source_mismatch"}

    unchanged = store.get_execution(run["id"])
    assert unchanged is not None
    assert unchanged["_state_json"] == original["_state_json"]
    assert unchanged["comparisons"] == []


def test_execution_compare_rejects_semantically_invalid_change_intent(client):
    before_id, after_id = _pair(client)
    run = _start(client, before_id)

    response = client.post(
        f"/api/executions/{run['id']}/compare",
        json={
            "after_snapshot_id": after_id,
            "change_intent": {
                "expected_changes": [{
                    "family": "bgp_configured_peer",
                    "transitions": ["coverage_lost"],
                    "subjects": [],
                    "reason": "Evidence loss cannot be authorized.",
                }],
            },
        },
    )

    assert response.status_code == 422
    assert "cannot authorize evidence loss" in response.json()["detail"]
    stored = client.app.state.store.get_execution(run["id"])
    assert stored is not None
    assert stored["comparisons"] == []


def test_execution_compare_detects_after_source_deleted_during_computation(
        client, monkeypatch):
    before_id, after_id = _pair(client)
    run = _start(client, before_id)
    run = _action_all_steps(client, run)
    store = client.app.state.store
    original_state = store.get_execution(run["id"])["_state_json"]
    compare_bound_pair = engine.compare_bound_pair

    def delete_after_compute(*args, **kwargs):
        comparison = compare_bound_pair(*args, **kwargs)
        assert store.delete_snapshot(after_id)
        return comparison

    monkeypatch.setattr(engine, "compare_bound_pair", delete_after_compute)
    response = client.post(
        f"/api/executions/{run['id']}/compare",
        json={"after_snapshot_id": after_id},
    )
    assert response.status_code == 404
    assert "source snapshot was deleted" in response.json()["detail"]
    unchanged = store.get_execution(run["id"])
    assert unchanged is not None
    assert unchanged["_state_json"] == original_state
    assert unchanged["comparisons"] == []


def test_receipt_bearing_execution_refuses_deletion_but_unreceipted_run_does_not(client):
    before_id, after_id, receipted = _post_change_pair(client)
    compared = client.post(
        f"/api/executions/{receipted['id']}/compare",
        json={"after_snapshot_id": after_id},
    )
    assert compared.status_code == 200, compared.text

    refused = client.delete(f"/api/executions/{receipted['id']}")
    assert refused.status_code == 409
    assert "immutable decision record" in refused.json()["detail"]
    surviving = client.get(f"/api/executions/{receipted['id']}")
    assert surviving.status_code == 200
    assert len(surviving.json()["comparison_receipts"]) == 1

    unreceipted = _start(client, before_id)
    assert client.delete(f"/api/executions/{unreceipted['id']}").status_code == 204
    assert client.get(f"/api/executions/{unreceipted['id']}").status_code == 404


def test_receipt_preserves_both_source_snapshots_and_parent_campaign(client):
    before_id, after_id, run = _post_change_pair(client)
    compared = client.post(
        f"/api/executions/{run['id']}/compare",
        json={"after_snapshot_id": after_id},
    )
    assert compared.status_code == 200, compared.text
    campaign_id = compared.json()["comparison_policy"]["before_snapshot"]["campaign_id"]

    for snapshot_id in (before_id, after_id):
        refused = client.delete(f"/api/snapshots/{snapshot_id}")
        assert refused.status_code == 409
        assert "canonical comparison receipt" in refused.json()["detail"]
        assert client.get(f"/api/snapshots/{snapshot_id}").status_code == 200

    refused_campaign = client.delete(f"/api/campaigns/{campaign_id}")
    assert refused_campaign.status_code == 409
    assert "immutable decision record" in refused_campaign.json()["detail"]
    assert client.get(f"/api/campaigns/{campaign_id}").status_code == 200


def test_database_trigger_refuses_direct_receipt_delete(client):
    before_id, after_id, run = _post_change_pair(client)
    compared = client.post(
        f"/api/executions/{run['id']}/compare",
        json={"after_snapshot_id": after_id},
    )
    assert compared.status_code == 200, compared.text
    store = client.app.state.store
    with pytest.raises(Exception, match="comparison receipts are immutable"):
        with store._lock:
            try:
                store._conn.execute(
                    "DELETE FROM execution_comparisons WHERE execution_id=?", (run["id"],)
                )
                store._conn.commit()
            except Exception:
                store._conn.rollback()
                raise


@pytest.mark.parametrize("verdict", ["BLOCKED", "INDETERMINATE", "FAIL"])
def test_non_pass_latest_gate_prevents_successful_outcome(verdict):
    state = {
        "label": "completed manual record",
        "status": "in_progress",
        "started_at": "2026-08-20T00:00:00+00:00",
        "ended_at": None,
        "plan_summary": {"current_baseline": {"verdict": "CLEAR"}},
        "comparison_policy": {
            "schema": "execution_comparison_policy/1",
            "canonical_gate_required": True,
        },
        "latest_comparison": {
            "schema": "execution_latest_comparison/1",
            "cutover_gate": {"schema": "cutover_gate/1", "verdict": verdict},
        },
        "waves": [{
            "closeout": {"decision": "COMPLETE"},
            "steps": [{"status": "done"}],
            "checks": [{"result": "pass"}],
        }],
        "events": [],
    }

    execution.finish(state, "completed", "", "test")

    assert state["outcome"] == execution.OUTCOME_PARTIAL


def test_compare_api_configured_bgp_loss_blocks_while_capture_loss_abstains(client, tmp_path):
    from tests.test_bgp_configured_peer_baseline import (
        EMPTY_IOS_SUMMARY,
        _run as bgp_owner,
    )

    before_path = tmp_path / "bgp-before"
    removed_path = tmp_path / "bgp-removed"
    missing_path = tmp_path / "bgp-missing"
    for path in (before_path, removed_path, missing_path):
        path.mkdir()
    before, *_ = bgp_owner(before_path)
    removed, *_ = bgp_owner(
        removed_path,
        config="version 17.9\nrouter bgp 65001\nend\n",
        runtime=EMPTY_IOS_SUMMARY,
    )
    unavailable, *_ = bgp_owner(
        missing_path, include_config=False, runtime=EMPTY_IOS_SUMMARY,
    )
    campaign = _campaign(client, "configured BGP decision", "ENG-BGP")

    def upload(label: str, baseline: dict) -> int:
        snapshot = {
            "script_version": "V3.23.0",
            "devices": {"edge1": {"platform": "ios"}},
            "bgp_configured_peer_baseline": baseline,
            "health_scores": [],
            "punchlist": [],
        }
        return _upload(
            client,
            campaign["id"],
            label,
            json.dumps(snapshot, separators=(",", ":")).encode("utf-8"),
        )

    before_id = upload("before", before)
    removed_id = upload("configured peer removed", removed)
    missing_id = upload("configuration capture missing", unavailable)

    regression = client.post(
        "/api/compare", json={"old_id": before_id, "new_id": removed_id}
    )
    assert regression.status_code == 200, regression.text
    bgp = next(
        family for family in regression.json()["protocol_families"]["families"]
        if family["family"] == "bgp_configured_peer"
    )
    lost_peer = next(row for row in bgp["changes"] if row["transition"] == "disappeared")
    assert lost_peer["decision_effect"] == "block"
    assert bgp["summary"]["n_blocking"] == 1
    assert regression.json()["cutover_gate"]["protocol_family_blocking"] == 1
    assert regression.json()["cutover_gate"]["verdict"] != "PASS"

    abstained = client.post(
        "/api/compare", json={"old_id": before_id, "new_id": missing_id}
    )
    assert abstained.status_code == 200, abstained.text
    bgp = next(
        family for family in abstained.json()["protocol_families"]["families"]
        if family["family"] == "bgp_configured_peer"
    )
    assert not any(row["transition"] == "disappeared" for row in bgp["changes"])
    assert any(
        row["transition"] == "coverage_lost"
        and row["decision_effect"] == "not_verified"
        for row in bgp["changes"]
    )
    assert abstained.json()["cutover_gate"]["verdict"] != "PASS"


def test_compare_and_execution_receipt_are_exactly_parity_bound_to_stored_bytes(client):
    before_id, after_id, run = _post_change_pair(client)
    canonical = client.post(
        "/api/compare", json={"old_id": before_id, "new_id": after_id}
    )
    assert canonical.status_code == 200, canonical.text
    canonical_body = canonical.json()

    compared = client.post(
        f"/api/executions/{run['id']}/compare",
        json={"after_snapshot_id": after_id},
    )
    assert compared.status_code == 200, compared.text
    execution_receipt = compared.json()["comparison_receipts"][-1]
    assert execution_receipt["receipt"]["comparison"] == canonical_body
    assert compared.json()["latest_comparison"]["receipt_sha256"] == (
        execution_receipt["receipt_sha256"]
    )
    assert compared.json()["latest_comparison"]["cutover_gate"] == canonical_body["cutover_gate"]

    store = client.app.state.store
    expected_hashes = {}
    for side, snapshot_id in (("before", before_id), ("after", after_id)):
        payload = _persisted_blob(store, snapshot_id)
        expected_hashes[side] = "sha256:" + hashlib.sha256(payload).hexdigest()
    source_binding = canonical_body["provenance"]["source_binding"]
    assert source_binding["before"]["sha256"] == expected_hashes["before"]
    assert source_binding["after"]["sha256"] == expected_hashes["after"]
    assert canonical_body["comparison_receipt"]["source_binding"] == source_binding

    stored_before = store.get_execution(run["id"])
    assert stored_before is not None
    stored_receipt = stored_before["comparisons"][-1]
    original_json = json.dumps(stored_receipt, sort_keys=True)
    with store._lock:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            store._conn.execute(
                "UPDATE execution_comparisons SET cutover_verdict=? WHERE id=?",
                ("PASS", stored_receipt["id"]),
            )
        store._conn.rollback()
    assert json.dumps(
        store.list_execution_comparisons(run["id"])[-1], sort_keys=True
    ) == original_json

    # Source custody is also a database invariant, not merely an API convention. Direct SQL may
    # neither orphan a receipt nor mutate any leaf named by its snapshot/engagement binding.
    foreign_campaign = _campaign(client, "foreign source", "ENG-FOREIGN")
    before_source = store.get_bound_snapshot(before_id)
    after_source = store.get_bound_snapshot(after_id)
    assert before_source is not None and after_source is not None
    before_binding = dict(before_source[1])
    after_binding = dict(after_source[1])
    with store._lock:
        for statement, params in (
            ("DELETE FROM snapshots WHERE id=?", (after_id,)),
            ("UPDATE snapshots SET label=? WHERE id=?", ("rewritten", before_id)),
            ("UPDATE snapshots SET snapshot_json=? WHERE id=?", ("{}", after_id)),
            (
                "UPDATE snapshots SET campaign_id=? WHERE id=?",
                (foreign_campaign["id"], before_id),
            ),
            (
                "UPDATE snapshots SET script_version=? WHERE id=?",
                ("V999.TAMPERED", after_id),
            ),
            (
                "INSERT OR REPLACE INTO snapshots("
                "id,campaign_id,label,uploaded_at,script_version,n_devices,summary_json,snapshot_json"
                ") SELECT id,campaign_id,?,uploaded_at,script_version,n_devices,summary_json,"
                "snapshot_json FROM snapshots WHERE id=?",
                ("replacement bypass", before_id),
            ),
            (
                "UPDATE campaign_identities SET engagement_id=? WHERE campaign_id=("
                "SELECT campaign_id FROM snapshots WHERE id=?)",
                ("ENG-REBOUND", before_id),
            ),
            (
                "INSERT OR REPLACE INTO campaign_identities(campaign_id,engagement_id) "
                "SELECT campaign_id,? FROM snapshots WHERE id=?",
                ("ENG-REPLACED", after_id),
            ),
        ):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                store._conn.execute(statement, params)
            store._conn.rollback()
    assert store.get_snapshot_meta(before_id) is not None
    assert store.get_snapshot_meta(after_id) is not None
    assert store.get_bound_snapshot(before_id)[1] == before_binding
    assert store.get_bound_snapshot(after_id)[1] == after_binding

    # Cached presentation summaries are intentionally outside the immutable source binding and
    # remain refreshable after a receipt is stored.
    assert store.update_summary(before_id, {"cache_refresh": True}) is True


def test_compare_append_and_finish_are_cross_process_compare_and_swap(tmp_path):
    database = tmp_path / "receipt-race.db"
    first = Store(database)
    second = None
    try:
        campaign = first.create_campaign("race", engagement_id="ENG-RACE")
        snapshot = json.loads(_GOLDEN.read_bytes())

        def action_direct(execution_id: int) -> tuple[dict, dict]:
            current = first.get_execution(execution_id)
            assert current is not None
            for wave in current["state"]["waves"]:
                for index, step in enumerate(wave["steps"]):
                    if step["status"] == "pending":
                        execution.apply_step(
                            current["state"], wave["group"], index, "done", "", "test"
                        )
            assert first.save_execution_if_unchanged(
                execution_id, current["_state_json"], current["state"]
            ) == "saved"
            actioned = first.get_execution(execution_id)
            assert actioned is not None
            binding = execution.implementation_evidence_binding(actioned["state"])
            assert binding["valid"] is True
            return actioned, binding

        before_id = first.add_snapshot(campaign["id"], "before", snapshot, {})["id"]
        before, before_binding = first.get_bound_snapshot(before_id)
        state = execution.start_run(
            before, "race run", "test", source_binding=before_binding
        )
        execution_id = first.create_execution(before_id, state)
        _actioned, implementation = action_direct(execution_id)
        after_snapshot = deepcopy(snapshot)
        after_snapshot["collected_at"] = (
            datetime.fromisoformat(implementation["completed_at"])
            + timedelta(microseconds=1)
        ).isoformat()
        after_id = first.add_snapshot(campaign["id"], "after", after_snapshot, {})["id"]
        after, after_binding = first.get_bound_snapshot(after_id)
        comparison = engine.compare_bound_pair(
            before,
            after,
            before_binding=before_binding,
            after_binding=after_binding,
        )
        receipt = engine.compact_execution_comparison(
            comparison,
            before_snapshot_id=before_id,
            after_snapshot_id=after_id,
            after_collected_at=after_snapshot["collected_at"],
            implementation_binding=implementation,
        )
        second = Store(database)

        stale_append = second.get_execution(execution_id)
        winning_finish = first.get_execution(execution_id)
        assert stale_append is not None and winning_finish is not None
        execution.finish(winning_finish["state"], "aborted", "", "test")
        assert first.save_execution_if_unchanged(
            execution_id,
            winning_finish["_state_json"],
            winning_finish["state"],
        ) == "saved"
        assert second.append_execution_comparison_if_unchanged(
            execution_id, stale_append["_state_json"], receipt
        ) == {"status": "conflict"}
        closed = second.get_execution(execution_id)
        assert closed is not None
        assert second.append_execution_comparison_if_unchanged(
            execution_id, closed["_state_json"], receipt
        ) == {"status": "closed"}
        assert second.list_execution_comparisons(execution_id) == []

        next_state = execution.start_run(
            before, "compare wins", "test", source_binding=before_binding
        )
        next_id = first.create_execution(before_id, next_state)
        _next_actioned, next_implementation = action_direct(next_id)
        next_after_snapshot = deepcopy(snapshot)
        next_after_snapshot["collected_at"] = (
            datetime.fromisoformat(next_implementation["completed_at"])
            + timedelta(microseconds=1)
        ).isoformat()
        next_after_id = first.add_snapshot(
            campaign["id"], "after compare-wins start", next_after_snapshot, {}
        )["id"]
        next_after, next_after_binding = first.get_bound_snapshot(next_after_id)
        next_comparison = engine.compare_bound_pair(
            before,
            next_after,
            before_binding=before_binding,
            after_binding=next_after_binding,
        )
        next_receipt = engine.compact_execution_comparison(
            next_comparison,
            before_snapshot_id=before_id,
            after_snapshot_id=next_after_id,
            after_collected_at=next_after_snapshot["collected_at"],
            implementation_binding=next_implementation,
        )
        winning_append = first.get_execution(next_id)
        stale_finish = second.get_execution(next_id)
        assert winning_append is not None and stale_finish is not None
        assert first.append_execution_comparison_if_unchanged(
            next_id, winning_append["_state_json"], next_receipt
        )["status"] == "saved"
        execution.finish(stale_finish["state"], "aborted", "", "test")
        assert second.save_execution_if_unchanged(
            next_id, stale_finish["_state_json"], stale_finish["state"]
        ) == "conflict"
        current = first.get_execution(next_id)
        assert current is not None
        assert current["state"]["status"] == "in_progress"
        assert current["state"]["latest_comparison"]["receipt_sha256"] == (
            next_receipt["receipt_sha256"]
        )
        assert len(current["comparisons"]) == 1
    finally:
        if second is not None:
            second.close()
        first.close()
