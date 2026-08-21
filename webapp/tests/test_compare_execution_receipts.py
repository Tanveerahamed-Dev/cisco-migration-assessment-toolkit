"""Decision-receipt hardening for AssessHub compare and execution flows.

These tests stay separate from the broad backend end-to-end module so the Release-1 custody and
race invariants can be run as a small, high-signal gate.  They exercise the public API wherever an
operator can reach the behavior and use ``Store`` directly only for database transaction/trigger
properties that HTTP cannot observe.
"""

from __future__ import annotations

import base64
import hashlib
import dataclasses
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

from backend import engine, execution, storage as storage_owner  # noqa: E402
from backend.app import create_app  # noqa: E402
from backend.storage import ExecutionReceiptAuthorityError, Store  # noqa: E402
from cisco_toolkit.html import compute_cutover_gate  # noqa: E402
from cisco_toolkit.protocol_assurance import receipt_envelope  # noqa: E402
from tests.test_compare_cutover_gate_cli import _snapshot as _clean_snapshot  # noqa: E402
from tests.test_l2_failure_rehearsal import _multichassis_snapshot  # noqa: E402
from tests.test_l2_failure_rehearsal import _ether_snapshot  # noqa: E402
from tests.test_observed_l2_failure_evidence import (  # noqa: E402
    _partner_changed_ether_snapshot,
)


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


def _execution_clear_raw(*, collected_at: datetime | None = None) -> bytes:
    """Keep the golden migration waves while removing unrelated frozen baseline blockers."""
    snapshot = json.loads(_GOLDEN.read_bytes())
    snapshot["collected_at"] = (
        collected_at or datetime.now(timezone.utc) - timedelta(seconds=1)
    ).isoformat()
    plan = snapshot["validation_plan"]
    for rows in [plan["items"], *plan["by_wave"].values()]:
        for row in rows:
            row["evidence_state"] = "assessed"
            row["expect"] = "Verified current baseline."
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


def _pass_checks_and_close_waves(client: TestClient, run: dict) -> dict:
    current = run
    for wave in list(current.get("waves") or []):
        for index, check in enumerate(list(wave.get("checks") or [])):
            if check.get("result") == "pending":
                response = client.post(
                    f"/api/executions/{current['id']}/check",
                    json={"wave": wave["group"], "index": index, "result": "pass"},
                )
                assert response.status_code == 200, response.text
                current = response.json()
        response = client.post(
            f"/api/executions/{current['id']}/closeout",
            json={"wave": wave["group"], "decision": "COMPLETE"},
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


def _blob_rewrite_same_length(
        store: Store, table: str, column: str, row_id: int, payload: bytes) -> None:
    """Exercise sqlite's incremental-BLOB path, which deliberately bypasses row triggers."""
    with store._lock:
        row = store._conn.execute(
            f"SELECT CAST({column} AS BLOB) AS payload FROM {table} WHERE rowid=?",
            (row_id,),
        ).fetchone()
        assert row is not None
        current = row["payload"]
        current = current.tobytes() if isinstance(current, memoryview) else bytes(current)
        assert len(payload) <= len(current)
        replacement = payload + (b" " * (len(current) - len(payload)))
        with store._conn.blobopen(table, column, row_id, readonly=False) as blob:
            blob.write(replacement)
        store._conn.commit()


def _blob_column_bytes(store: Store, table: str, column: str, row_id: int) -> bytes:
    with store._lock:
        row = store._conn.execute(
            f"SELECT CAST({column} AS BLOB) AS payload FROM {table} WHERE rowid=?",
            (row_id,),
        ).fetchone()
    assert row is not None
    payload = row["payload"]
    return payload.tobytes() if isinstance(payload, memoryview) else bytes(payload)


def _changed_same_length(payload: bytes) -> bytes:
    assert payload
    return bytes([payload[0] ^ 1]) + payload[1:]


def _drop_integer_authority_tables(database: Path) -> None:
    connection = sqlite3.connect(database)
    try:
        for table in (
            "execution_l2_failure_trial_authority",
            "execution_comparison_authority",
            "snapshot_authority",
        ):
            trigger_rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
                (table,),
            ).fetchall()
            for (trigger_name,) in trigger_rows:
                connection.execute(f'DROP TRIGGER "{trigger_name}"')
            connection.execute(f'DROP TABLE "{table}"')
        connection.commit()
    finally:
        connection.close()


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _orphan_comparison_raw(tmp_path: Path) -> bytes:
    base = json.loads(json.dumps(
        _clean_snapshot("FULL/DR", "2026-08-20T00:00:00")
    ).replace("R1", "leaf-a").replace("R2", "leaf-b"))
    base.pop("routing_neighbors", None)
    l2 = _multichassis_snapshot(tmp_path, orphan=True)
    for key in (
            "devices", "protocol_assessability", "etherchannel_projection",
            "etherchannel_baseline", "etherchannel_operational_evidence",
            "multichassis_lag_typed_observations",
            "multichassis_lag_domain_baseline"):
        base[key] = l2[key]
    return json.dumps(
        base,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
        default=lambda item: dataclasses.asdict(item)
        if dataclasses.is_dataclass(item) else str(item),
    ).encode("utf-8")


def _observed_ether_phase_raw(
        tmp_path: Path, state: str, collected_at: datetime) -> bytes:
    body = {
        "pre": "10 Po10(SU) LACP Gi1/0/1(P) Gi1/0/2(P)",
        "post": "10 Po10(SU) LACP Gi1/0/1(P) Gi1/0/2(D)",
        "failed": "10 Po10(SU) LACP Gi1/0/1(P) Gi1/0/2(D)",
        "unwitnessed": "10 Po10(SU) LACP Gi1/0/1(P) Gi1/0/2(P)",
        "recovery": "10 Po10(SU) LACP Gi1/0/1(P) Gi1/0/2(P)",
    }[state]
    l2 = (
        _partner_changed_ether_snapshot(tmp_path)
        if state == "failed" else _ether_snapshot(tmp_path, body)
    )
    snapshot = deepcopy(_clean_snapshot("FULL/DR", collected_at.isoformat()))
    snapshot["devices"].update(deepcopy(l2["devices"]))
    for key, value in l2.items():
        if key != "devices":
            snapshot[key] = deepcopy(value)
    snapshot["collected_at"] = collected_at.isoformat()
    return json.dumps(
        snapshot,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
        default=lambda item: dataclasses.asdict(item)
        if dataclasses.is_dataclass(item) else str(item),
    ).encode("utf-8")


def _observed_ether_witness(induced_at: datetime) -> bytes:
    return json.dumps({
        "schema": "l2_failure_witness/1",
        "family": "etherchannel",
        "subject": "dist1|Po10",
        "failure_scenario": "single_observed_forwarding_member_loss",
        "action": "shut_link",
        "target": {"host": "dist1", "interface": "Gi1/0/2"},
        "induced_at": induced_at.isoformat(),
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _observed_failure_execution(client: TestClient, tmp_path: Path) -> tuple[dict, dict]:
    campaign = _campaign(client, "authority ratchet", "ENG-AUTHORITY-RATCHET")
    before_collected = datetime.now(timezone.utc) - timedelta(seconds=1)
    before = _clean_snapshot("FULL/DR", before_collected.isoformat())
    before["collected_at"] = before_collected.isoformat()
    before["wave_sequencing"] = json.loads(_GOLDEN.read_bytes())["wave_sequencing"]
    before_id = _upload(
        client, campaign["id"], "before",
        json.dumps(before, separators=(",", ":"), allow_nan=False).encode("utf-8"),
    )
    run = _action_all_steps(client, _start(client, before_id))
    anchor = datetime.fromisoformat(
        execution.implementation_evidence_binding(run)["completed_at"]
    )
    pre_id = _upload(
        client, campaign["id"], "pre-failure",
        _observed_ether_phase_raw(
            tmp_path / "authority-pre", "pre", anchor + timedelta(microseconds=1)
        ),
    )
    post_id = _upload(
        client, campaign["id"], "post-failure",
        _observed_ether_phase_raw(
            tmp_path / "authority-post", "failed", anchor + timedelta(microseconds=3)
        ),
    )
    recovery_id = _upload(
        client, campaign["id"], "recovery",
        _observed_ether_phase_raw(
            tmp_path / "authority-recovery", "recovery",
            anchor + timedelta(microseconds=4),
        ),
    )
    witness = _observed_ether_witness(anchor + timedelta(microseconds=2))
    compared = client.post(f"/api/executions/{run['id']}/compare", json={
        "after_snapshot_id": recovery_id,
        "l2_failure_trial": {
            "pre_failure_snapshot_id": pre_id,
            "post_failure_snapshot_id": post_id,
            "witness_json_base64": base64.b64encode(witness).decode("ascii"),
        },
    })
    assert compared.status_code == 200, compared.text
    assert compared.json()["latest_comparison"]["cutover_gate"]["verdict"] == "FAIL"
    assert compared.json()["l2_failure_trial_requirement"]["status"] == "observed_failure"
    return campaign, compared.json()


@pytest.mark.parametrize(
    ("path", "raw"),
    [
        ("/api/compare", b'{"old_id":1,"old_id":2,"new_id":3}'),
        (
            "/api/compare",
            b'{"old_id":1,"new_id":2,"change_intent":{"expected_changes":['
            b'{"family":"vtp_safety","transitions":["intent_changed"],'
            b'"intent_kind":"","intent_kind":"revision_reset"}]}}',
        ),
        (
            "/api/compare",
            b'{"old_id":1,"new_id":2,"change_intent":{"expected_changes":['
            b'{"family":"vtp_safety","transitions":["intent_changed"],'
            b'"reason":"first","reason":"second"}]}}',
        ),
        ("/api/executions/1/compare", b'{"after_snapshot_id":1,"after_snapshot_id":2}'),
        (
            "/api/executions/1/compare",
            b'{"after_snapshot_id":2,"change_intent":{"expected_changes":['
            b'{"family":"vtp_safety","transitions":["intent_changed"],'
            b'"intent_kind":"","intent_kind":"revision_reset"}]}}',
        ),
    ],
)
def test_decision_json_wire_body_rejects_duplicate_keys(client, path, raw):
    response = client.post(path, content=raw, headers={"content-type": "application/json"})

    assert response.status_code == 400
    assert "duplicate json object key" in response.json()["detail"].lower()


@pytest.mark.parametrize("bad_id", [True, "1", 1.0])
def test_compare_snapshot_ids_are_strict_integers(client, bad_id):
    response = client.post("/api/compare", json={"old_id": bad_id, "new_id": 1})

    assert response.status_code == 422


@pytest.mark.parametrize("bad_id", [True, "1", 1.0])
def test_execution_compare_snapshot_id_is_a_strict_integer(client, bad_id):
    response = client.post(
        "/api/executions/1/compare",
        json={"after_snapshot_id": bad_id},
    )

    assert response.status_code == 422


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
    ) == {"status": "authority_invalid"}

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


@pytest.mark.parametrize(
    "change_intent",
    [
        {"expected_change": []},
        {
            "expected_changes": [{
                "family": "ipv4_routing_adjacency",
                "transitions": ["appeared"],
                "subjects": [],
                "reasno": "misspelled reason",
            }],
        },
    ],
)
def test_compare_api_rejects_unknown_change_intent_fields(client, change_intent):
    before_id, after_id = _pair(client)

    response = client.post(
        "/api/compare",
        json={
            "old_id": before_id,
            "new_id": after_id,
            "change_intent": change_intent,
        },
    )

    assert response.status_code == 422
    assert "extra_forbidden" in response.text


def test_compare_api_consumes_source_bound_orphan_risk_in_canonical_gate(
        client, tmp_path):
    campaign = _campaign(client, "L2 orphan risk", "ENG-L2-ORPHAN")
    raw = _orphan_comparison_raw(tmp_path / "captures")
    before_id = _upload(client, campaign["id"], "before", raw)
    after_id = _upload(client, campaign["id"], "after", raw)

    response = client.post(
        "/api/compare", json={"old_id": before_id, "new_id": after_id})

    assert response.status_code == 200, response.text
    body = response.json()
    gate = body["cutover_gate"]
    l2 = body["operator_evidence"]["rehearsal"]["l2_failure_rehearsal"]
    assert body["comparison_admission"]["status"] == "admitted"
    assert body["verdict"] == "CLEAN"
    assert body["precert"]["verdict"] == "PASS"
    assert body["protocol_families"]["summary"]["n_blocking"] == 0
    assert gate["verdict"] == "REVIEW"
    assert gate["l2_rehearsal_status"] == "projected_risk"
    assert gate["l2_rehearsal_projected_risks"] == 1
    assert gate["l2_rehearsal_note"] in gate["note"]
    assert l2["applicability"] == {
        "stp": False,
        "etherchannel": True,
        "multichassis_lag": True,
        "service_path": False,
    }
    orphan = next(
        row for row in l2["scenarios"]
        if row["subject"] == "multichassis_lag|orphan|leaf-a|Eth1/45"
    )
    assert orphan["disposition"] == "projected_risk"
    assert orphan["assurance_level"] == "not_verified"
    assert orphan["evidence"]["service_path_survival"] == "not_verified"


def test_compare_api_acquires_one_persisted_observed_trial_source_set(
        client, tmp_path):
    campaign = _campaign(client, "observed L2 API", "ENG-OBSERVED-API")
    anchor = datetime.now(timezone.utc) - timedelta(minutes=2)
    before_id = _upload(
        client, campaign["id"], "before",
        _post_change_raw(collected_at=anchor),
    )
    pre_id = _upload(
        client, campaign["id"], "pre-failure",
        _observed_ether_phase_raw(tmp_path / "pre", "pre", anchor + timedelta(seconds=10)),
    )
    post_id = _upload(
        client, campaign["id"], "post-failure",
        _observed_ether_phase_raw(tmp_path / "post", "post", anchor + timedelta(seconds=30)),
    )
    recovery_id = _upload(
        client, campaign["id"], "recovery",
        _observed_ether_phase_raw(
            tmp_path / "recovery", "recovery", anchor + timedelta(seconds=40)
        ),
    )
    witness = _observed_ether_witness(anchor + timedelta(seconds=20))

    response = client.post("/api/compare", json={
        "old_id": before_id,
        "new_id": recovery_id,
        "l2_failure_trial": {
            "pre_failure_snapshot_id": pre_id,
            "post_failure_snapshot_id": post_id,
            "witness_json_base64": base64.b64encode(witness).decode("ascii"),
        },
    })

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["operator_evidence"]["rehearsal"]["status"] \
        == "local_safety_preservation"
    assert body["cutover_gate"]["l2_observed_trial_status"] == "observed_survival"
    receipt = body["operator_evidence"]["rehearsal"][
        "observed_l2_failure_evidence"
    ]
    assert receipt["source_binding"]["pre_failure"]["source_id"] == f"snapshot:{pre_id}"
    assert receipt["source_binding"]["post_failure"]["source_id"] == f"snapshot:{post_id}"
    assert receipt["source_binding"]["recovery"]["source_id"] \
        == f"snapshot:{recovery_id}"


def test_execution_trial_is_reminted_and_its_phase_sources_are_immutable(
        client, tmp_path):
    campaign = _campaign(client, "observed L2 execution", "ENG-OBSERVED-EXEC")
    before_id = _upload(
        client, campaign["id"], "before",
        _post_change_raw(
            collected_at=datetime.now(timezone.utc) - timedelta(seconds=1)
        ),
    )
    run = _action_all_steps(client, _start(client, before_id))
    implementation = execution.implementation_evidence_binding(run)
    anchor = datetime.fromisoformat(implementation["completed_at"])
    pre_collected = anchor + timedelta(microseconds=1)
    induced = anchor + timedelta(microseconds=2)
    post_collected = anchor + timedelta(microseconds=3)
    recovery_collected = anchor + timedelta(microseconds=4)
    pre_id = _upload(
        client, campaign["id"], "pre-failure",
        _observed_ether_phase_raw(tmp_path / "pre", "pre", pre_collected),
    )
    post_id = _upload(
        client, campaign["id"], "post-failure",
        _observed_ether_phase_raw(tmp_path / "post", "post", post_collected),
    )
    recovery_id = _upload(
        client, campaign["id"], "recovery",
        _observed_ether_phase_raw(
            tmp_path / "recovery", "recovery", recovery_collected
        ),
    )
    witness = _observed_ether_witness(induced)

    compared = client.post(f"/api/executions/{run['id']}/compare", json={
        "after_snapshot_id": recovery_id,
        "l2_failure_trial": {
            "pre_failure_snapshot_id": pre_id,
            "post_failure_snapshot_id": post_id,
            "witness_json_base64": base64.b64encode(witness).decode("ascii"),
        },
    })

    assert compared.status_code == 200, compared.text
    latest = compared.json()["comparison_receipts"][-1]
    assert latest["receipt"]["comparison"]["cutover_gate"][
        "l2_observed_trial_status"
    ] == "observed_survival"
    store = client.app.state.store
    with store._lock:
        source_row = store._conn.execute(
            """SELECT comparison_id, pre_failure_snapshot_id,
                      post_failure_snapshot_id, recovery_snapshot_id,
                      CAST(witness_blob AS BLOB) AS witness_blob, witness_sha256
               FROM execution_l2_failure_trial_sources WHERE comparison_id=?""",
            (latest["id"],),
        ).fetchone()
    assert source_row is not None
    assert tuple(source_row[key] for key in (
        "pre_failure_snapshot_id", "post_failure_snapshot_id", "recovery_snapshot_id"
    )) == (pre_id, post_id, recovery_id)
    stored_witness = source_row["witness_blob"]
    stored_witness = (
        stored_witness.tobytes() if isinstance(stored_witness, memoryview)
        else bytes(stored_witness)
    )
    assert stored_witness == witness

    for snapshot_id in (pre_id, post_id, recovery_id):
        refused = client.delete(f"/api/snapshots/{snapshot_id}")
        assert refused.status_code == 409

    foreign_campaign = _campaign(client, "foreign L2 phase", "ENG-FOREIGN-L2")
    foreign_snapshot_id = _upload(
        client, foreign_campaign["id"], "foreign execution source"
    )
    phase_bindings = {
        snapshot_id: dict(store.get_bound_snapshot(snapshot_id)[1])
        for snapshot_id in (pre_id, post_id, recovery_id)
    }
    with store._lock:
        for snapshot_id in (pre_id, post_id, recovery_id):
            for statement, params in (
                ("UPDATE snapshots SET label=? WHERE id=?", ("rewritten", snapshot_id)),
                (
                    "UPDATE snapshots SET uploaded_at=? WHERE id=?",
                    ("2099-01-01T00:00:00+00:00", snapshot_id),
                ),
                (
                    "UPDATE snapshots SET script_version=? WHERE id=?",
                    ("V999.TAMPERED", snapshot_id),
                ),
                ("UPDATE snapshots SET snapshot_json=? WHERE id=?", ("{}", snapshot_id)),
                (
                    "UPDATE snapshots SET campaign_id=? WHERE id=?",
                    (foreign_campaign["id"], snapshot_id),
                ),
                (
                    "INSERT OR REPLACE INTO snapshots("
                    "id,campaign_id,label,uploaded_at,script_version,n_devices,summary_json,"
                    "snapshot_json) SELECT id,campaign_id,?,uploaded_at,script_version,n_devices,"
                    "summary_json,snapshot_json FROM snapshots WHERE id=?",
                    ("replacement bypass", snapshot_id),
                ),
                (
                    "UPDATE campaign_identities SET engagement_id=? WHERE campaign_id=("
                    "SELECT campaign_id FROM snapshots WHERE id=?)",
                    ("ENG-REBOUND", snapshot_id),
                ),
                (
                    "INSERT OR REPLACE INTO campaign_identities(campaign_id,engagement_id) "
                    "SELECT campaign_id,? FROM snapshots WHERE id=?",
                    ("ENG-REPLACED", snapshot_id),
                ),
            ):
                with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                    store._conn.execute(statement, params)
                store._conn.rollback()
    for snapshot_id, binding in phase_bindings.items():
        assert store.get_bound_snapshot(snapshot_id)[1] == binding

    with store._lock:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            store._conn.execute(
                """INSERT OR REPLACE INTO execution_l2_failure_trial_sources(
                       comparison_id, pre_failure_snapshot_id, post_failure_snapshot_id,
                       recovery_snapshot_id, witness_blob, witness_sha256,
                       source, campaign_id, engagement_id)
                   SELECT comparison_id, pre_failure_snapshot_id, post_failure_snapshot_id,
                          recovery_snapshot_id, ?, witness_sha256,
                          source, campaign_id, engagement_id
                   FROM execution_l2_failure_trial_sources WHERE comparison_id=?""",
                (sqlite3.Binary(b"replacement"), latest["id"]),
            )
        store._conn.rollback()
        unchanged = store._conn.execute(
            """SELECT CAST(witness_blob AS BLOB) AS witness_blob
               FROM execution_l2_failure_trial_sources WHERE comparison_id=?""",
            (latest["id"],),
        ).fetchone()
    assert unchanged is not None
    unchanged_witness = unchanged["witness_blob"]
    unchanged_witness = (
        unchanged_witness.tobytes()
        if isinstance(unchanged_witness, memoryview) else bytes(unchanged_witness)
    )
    assert unchanged_witness == witness

    with store._lock:
        store._conn.execute("PRAGMA recursive_triggers=OFF")
        for statement, params in (
            (
                "INSERT OR REPLACE INTO execution_comparisons("
                "id,execution_id,before_snapshot_id,after_snapshot_id,receipt_sha256,"
                "cutover_verdict,created_at,receipt_json) "
                "SELECT id,execution_id,before_snapshot_id,after_snapshot_id,receipt_sha256,"
                "cutover_verdict,created_at,'{}' FROM execution_comparisons WHERE id=?",
                (latest["id"],),
            ),
            (
                "UPDATE executions SET snapshot_id=? WHERE id=?",
                (foreign_snapshot_id, run["id"]),
            ),
            (
                "UPDATE executions SET started_at=? WHERE id=?",
                ("2099-01-01T00:00:00+00:00", run["id"]),
            ),
            (
                "UPDATE executions SET started_at_epoch_us=started_at_epoch_us+1 WHERE id=?",
                (run["id"],),
            ),
            (
                "INSERT OR REPLACE INTO executions("
                "id,snapshot_id,label,status,started_at,ended_at,state_json) "
                "SELECT id,?,label,status,started_at,ended_at,state_json "
                "FROM executions WHERE id=?",
                (foreign_snapshot_id, run["id"]),
            ),
        ):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                store._conn.execute(statement, params)
            store._conn.rollback()
        receipt_row = store._conn.execute(
            "SELECT receipt_json FROM execution_comparisons WHERE id=?",
            (latest["id"],),
        ).fetchone()
        execution_row = store._conn.execute(
            "SELECT snapshot_id, started_at FROM executions WHERE id=?",
            (run["id"],),
        ).fetchone()
    assert receipt_row is not None and receipt_row["receipt_json"] != "{}"
    assert execution_row is not None
    assert execution_row["snapshot_id"] == before_id
    assert execution_row["started_at"] == run["started_at"]


def test_execution_observed_failure_cannot_be_erased_by_omitting_a_retrial(
        client, tmp_path):
    campaign = _campaign(client, "observed failure ratchet", "ENG-L2-RATCHET")
    before_id = _upload(
        client, campaign["id"], "before",
        _post_change_raw(
            collected_at=datetime.now(timezone.utc) - timedelta(seconds=1)
        ),
    )
    run = _action_all_steps(client, _start(client, before_id))
    implementation = execution.implementation_evidence_binding(run)
    anchor = datetime.fromisoformat(implementation["completed_at"])
    pre_id = _upload(
        client, campaign["id"], "pre-failure",
        _observed_ether_phase_raw(
            tmp_path / "pre", "pre", anchor + timedelta(microseconds=1)
        ),
    )
    post_id = _upload(
        client, campaign["id"], "post-failure",
        _observed_ether_phase_raw(
            tmp_path / "post", "failed", anchor + timedelta(microseconds=3)
        ),
    )
    recovery_id = _upload(
        client, campaign["id"], "recovery",
        _observed_ether_phase_raw(
            tmp_path / "recovery", "recovery", anchor + timedelta(microseconds=4)
        ),
    )
    witness = _observed_ether_witness(anchor + timedelta(microseconds=2))
    failed = client.post(f"/api/executions/{run['id']}/compare", json={
        "after_snapshot_id": recovery_id,
        "l2_failure_trial": {
            "pre_failure_snapshot_id": pre_id,
            "post_failure_snapshot_id": post_id,
            "witness_json_base64": base64.b64encode(witness).decode("ascii"),
        },
    })
    assert failed.status_code == 200, failed.text
    assert failed.json()["latest_comparison"]["cutover_gate"]["verdict"] == "FAIL"
    requirement = failed.json().get("l2_failure_trial_requirement")
    assert requirement is not None
    assert requirement["status"] == "observed_failure"

    later_id = _upload(
        client, campaign["id"], "later recovery without retrial",
        _observed_ether_phase_raw(
            tmp_path / "later", "recovery", anchor + timedelta(microseconds=5)
        ),
    )
    omitted = client.post(
        f"/api/executions/{run['id']}/compare",
        json={"after_snapshot_id": later_id},
    )

    assert omitted.status_code == 409
    assert "prior observed local l2 failure or not-verified trial remains unresolved" \
        in omitted.text.lower()
    stored = client.app.state.store.get_execution(run["id"])
    assert stored is not None
    assert len(stored["comparisons"]) == 1
    assert stored["state"]["latest_comparison"]["cutover_gate"]["verdict"] == "FAIL"


def test_execution_state_blob_cannot_erase_failure_ratchet_or_mint_success(
        client, tmp_path):
    _campaign_row, failed = _observed_failure_execution(client, tmp_path)
    ready = _pass_checks_and_close_waves(client, failed)
    store = client.app.state.store
    with store._lock:
        row = store._conn.execute(
            "SELECT state_json FROM executions WHERE id=?", (ready["id"],)
        ).fetchone()
    assert row is not None
    forged = json.loads(row["state_json"])
    forged.pop("l2_failure_trial_requirement", None)
    forged["latest_comparison"]["cutover_gate"]["verdict"] = "PASS"
    forged["latest_comparison"]["cutover_gate"]["operator_note"] = "FORGED PASS"
    forged_bytes = json.dumps(forged, separators=(",", ":")).encode("utf-8")
    _blob_rewrite_same_length(store, "executions", "state_json", ready["id"], forged_bytes)

    read = client.get(f"/api/executions/{ready['id']}")
    assert read.status_code == 200, read.text
    assert read.json()["latest_comparison"]["cutover_gate"]["verdict"] == "FAIL"
    assert read.json()["l2_failure_trial_requirement"]["status"] == "observed_failure"
    listed = client.get(f"/api/snapshots/{ready['snapshot_id']}/executions")
    assert listed.status_code == 200, listed.text
    listed_run = next(item for item in listed.json() if item["id"] == ready["id"])
    assert listed_run["latest_comparison"]["cutover_gate"]["verdict"] == "FAIL"

    finished = client.post(
        f"/api/executions/{ready['id']}/finish", json={"status": "completed"}
    )
    assert finished.status_code == 200, finished.text
    assert finished.json()["outcome"] == execution.OUTCOME_PARTIAL
    assert finished.json()["l2_failure_trial_requirement"]["status"] \
        == "observed_failure"

    # A second incremental rewrite cannot reopen the database-owned completed header either.
    with store._lock:
        row = store._conn.execute(
            "SELECT state_json FROM executions WHERE id=?", (ready["id"],)
        ).fetchone()
    reopened = json.loads(row["state_json"])
    reopened["status"] = "in_progress"
    reopened["events"] = []
    _blob_rewrite_same_length(
        store, "executions", "state_json", ready["id"],
        json.dumps(reopened, separators=(",", ":")).encode("utf-8"),
    )
    # The duplicated TEXT header is not authority either: even a direct SQL rewrite cannot
    # reopen the run while the non-blob lifecycle marker remains closed. The marker itself is
    # monotone once the execution has closed.
    with store._lock:
        store._conn.execute(
            "UPDATE executions SET status='in_progress' WHERE id=?", (ready["id"],)
        )
        store._conn.commit()
        with pytest.raises(sqlite3.IntegrityError, match="lifecycle is immutable"):
            store._conn.execute(
                "UPDATE executions SET lifecycle_state=0 WHERE id=?", (ready["id"],)
            )
        store._conn.rollback()
    refused = client.post(
        f"/api/executions/{ready['id']}/event",
        json={"kind": "note", "text": "attempted reopen"},
    )
    assert refused.status_code == 409
    assert "already completed" in refused.text.lower()


def test_no_receipt_v2_policy_blob_removal_cannot_create_legacy_success(client):
    campaign = _campaign(client, "no-receipt authority", "ENG-NO-RECEIPT-AUTH")
    before_id = _upload(client, campaign["id"], "before", _execution_clear_raw())
    ready = _pass_checks_and_close_waves(
        client, _action_all_steps(client, _start(client, before_id))
    )
    store = client.app.state.store
    with store._lock:
        row = store._conn.execute(
            "SELECT state_json FROM executions WHERE id=?", (ready["id"],)
        ).fetchone()
    forged = json.loads(row["state_json"])
    forged.pop("execution_schema", None)
    forged.pop("comparison_policy", None)
    forged["latest_comparison"] = {
        "schema": "execution_latest_comparison/1",
        "cutover_gate": {"schema": "cutover_gate/1", "verdict": "PASS"},
    }
    _blob_rewrite_same_length(
        store, "executions", "state_json", ready["id"],
        json.dumps(forged, separators=(",", ":")).encode("utf-8"),
    )

    read = client.get(f"/api/executions/{ready['id']}")
    assert read.status_code == 200, read.text
    assert read.json()["comparison_policy"]["canonical_gate_required"] is True
    assert "latest_comparison" not in read.json()
    finished = client.post(
        f"/api/executions/{ready['id']}/finish", json={"status": "completed"}
    )
    assert finished.status_code == 200, finished.text
    assert finished.json()["outcome"] == execution.OUTCOME_PARTIAL


def test_store_migrates_legacy_execution_authority_markers_once(tmp_path):
    database = tmp_path / "legacy-execution.db"
    started = "2026-08-20T00:00:00.000001+00:00"
    ended = "2026-08-20T00:00:01.000002+00:00"
    legacy_state = {
        "label": "legacy closed run",
        "status": "completed",
        "started_at": started,
        "ended_at": ended,
        "events": [],
        "waves": [],
    }
    connection = sqlite3.connect(database)
    connection.execute(
        """CREATE TABLE executions(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               snapshot_id INTEGER NOT NULL,
               label TEXT NOT NULL,
               status TEXT NOT NULL DEFAULT 'in_progress',
               started_at TEXT NOT NULL,
               ended_at TEXT,
               state_json TEXT NOT NULL)"""
    )
    connection.execute(
        """INSERT INTO executions(
               snapshot_id,label,status,started_at,ended_at,state_json)
           VALUES (?,?,?,?,?,?)""",
        (
            99, "legacy closed run", "completed", started, ended,
            json.dumps(legacy_state, separators=(",", ":")),
        ),
    )
    connection.commit()
    connection.close()

    store = Store(database)
    with store._lock:
        columns = {
            row["name"] for row in store._conn.execute(
                "PRAGMA table_info(executions)"
            ).fetchall()
        }
        row = store._conn.execute(
            """SELECT comparison_required, snapshot_id_high_watermark,
                      lifecycle_state, started_at_epoch_us, ended_at_epoch_us
               FROM executions WHERE id=1"""
        ).fetchone()
    assert {
        "comparison_required", "snapshot_id_high_watermark", "lifecycle_state",
        "started_at_epoch_us", "ended_at_epoch_us",
    } <= columns
    assert dict(row) == {
        "comparison_required": 0,
        "snapshot_id_high_watermark": 99,
        "lifecycle_state": 1,
        "started_at_epoch_us": 1_787_184_000_000_001,
        "ended_at_epoch_us": 1_787_184_001_000_002,
    }
    store.close()

    # Reopening after mutable mirrors disagree must not rerun migration and reset the marker.
    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE executions SET status='in_progress', state_json=? WHERE id=1",
        (json.dumps({**legacy_state, "status": "in_progress"}),),
    )
    connection.commit()
    connection.close()
    reopened = Store(database)
    rec = reopened.get_execution(1)
    assert rec is not None
    assert rec["state"]["status"] == "completed"
    with reopened._lock:
        marker = reopened._conn.execute(
            "SELECT lifecycle_state FROM executions WHERE id=1"
        ).fetchone()
    assert marker["lifecycle_state"] == 1
    reopened.close()


def test_store_migrates_valid_exact_receipt_source_authority_once(tmp_path):
    database = tmp_path / "legacy-receipt-authority.db"
    app = create_app(db_path=str(database))
    with TestClient(app, base_url="http://localhost") as test_client:
        _campaign_row, failed = _observed_failure_execution(
            test_client, tmp_path / "legacy-trial"
        )
        execution_id = failed["id"]
        receipt_id = failed["comparison_receipts"][-1]["id"]
    app.state.store.close()

    _drop_integer_authority_tables(database)
    migrated = Store(database)
    restored = migrated.get_execution(execution_id)
    assert restored is not None
    assert restored["state"]["l2_failure_trial_requirement"]["status"] \
        == "observed_failure"
    with migrated._lock:
        counts = {
            table: int(migrated._conn.execute(
                f'SELECT COUNT(*) FROM "{table}"'
            ).fetchone()[0])
            for table in (
                "snapshot_authority",
                "execution_comparison_authority",
                "execution_l2_failure_trial_authority",
            )
        }
    assert counts["snapshot_authority"] == 4
    assert counts["execution_comparison_authority"] == 1
    assert counts["execution_l2_failure_trial_authority"] == 1
    migrated.close()

    # Once sealed, reopening never blesses a same-length rewrite with a fresh anchor.
    connection = sqlite3.connect(database)
    try:
        row = connection.execute(
            "SELECT CAST(receipt_json AS BLOB) FROM execution_comparisons WHERE id=?",
            (receipt_id,),
        ).fetchone()
        receipt_bytes = bytes(row[0])
        with connection.blobopen(
                "execution_comparisons", "receipt_json", receipt_id,
                readonly=False) as blob:
            blob.write(_changed_same_length(receipt_bytes))
        connection.commit()
    finally:
        connection.close()
    reopened = Store(database)
    with pytest.raises(ExecutionReceiptAuthorityError):
        reopened.get_execution(execution_id)
    reopened.close()


def test_store_refuses_to_seal_invalid_pre_anchor_receipt_history(tmp_path):
    database = tmp_path / "invalid-legacy-receipt.db"
    app = create_app(db_path=str(database))
    with TestClient(app, base_url="http://localhost") as test_client:
        _before_id, after_id, run = _post_change_pair(test_client)
        compared = test_client.post(
            f"/api/executions/{run['id']}/compare",
            json={"after_snapshot_id": after_id},
        )
        assert compared.status_code == 200, compared.text
        receipt_id = compared.json()["comparison_receipts"][-1]["id"]
    app.state.store.close()

    _drop_integer_authority_tables(database)
    connection = sqlite3.connect(database)
    try:
        row = connection.execute(
            "SELECT CAST(receipt_json AS BLOB) FROM execution_comparisons WHERE id=?",
            (receipt_id,),
        ).fetchone()
        receipt_bytes = bytes(row[0])
        with connection.blobopen(
                "execution_comparisons", "receipt_json", receipt_id,
                readonly=False) as blob:
            blob.write(b"[" + receipt_bytes[1:])
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(ExecutionReceiptAuthorityError):
        Store(database)


def test_corrupted_immutable_receipt_blob_fails_closed_on_every_execution_surface(client):
    before_id, after_id, run = _post_change_pair(client)
    compared = client.post(
        f"/api/executions/{run['id']}/compare",
        json={"after_snapshot_id": after_id},
    )
    assert compared.status_code == 200, compared.text
    receipt_id = compared.json()["comparison_receipts"][-1]["id"]
    store = client.app.state.store
    with store._lock:
        row = store._conn.execute(
            "SELECT CAST(receipt_json AS BLOB) AS payload "
            "FROM execution_comparisons WHERE id=?",
            (receipt_id,),
        ).fetchone()
    receipt_bytes = row["payload"]
    receipt_bytes = (
        receipt_bytes.tobytes()
        if isinstance(receipt_bytes, memoryview) else bytes(receipt_bytes)
    )
    _blob_rewrite_same_length(
        store, "execution_comparisons", "receipt_json", receipt_id,
        b"[" + receipt_bytes[1:],
    )

    for method, path, body in (
        ("get", f"/api/executions/{run['id']}", None),
        ("get", f"/api/snapshots/{before_id}/executions", None),
        ("post", f"/api/executions/{run['id']}/finish", {"status": "completed"}),
        ("get", f"/api/executions/{run['id']}/report", None),
    ):
        response = getattr(client, method)(path, **({"json": body} if body else {}))
        assert response.status_code == 409, (path, response.text)
        assert "no pass is available" in response.text.lower()


def test_corrupted_observed_witness_source_blob_invalidates_the_receipt(client, tmp_path):
    _campaign_row, failed = _observed_failure_execution(client, tmp_path)
    receipt_id = failed["comparison_receipts"][-1]["id"]
    store = client.app.state.store
    with store._lock:
        row = store._conn.execute(
            "SELECT CAST(witness_blob AS BLOB) AS payload "
            "FROM execution_l2_failure_trial_sources WHERE comparison_id=?",
            (receipt_id,),
        ).fetchone()
    witness = row["payload"]
    witness = witness.tobytes() if isinstance(witness, memoryview) else bytes(witness)
    _blob_rewrite_same_length(
        store, "execution_l2_failure_trial_sources", "witness_blob", receipt_id,
        bytes([witness[0] ^ 1]) + witness[1:],
    )

    response = client.get(f"/api/executions/{failed['id']}")
    assert response.status_code == 409
    assert "no pass is available" in response.text.lower()


def test_integer_anchor_rejects_coordinated_comparison_text_blob_rewrites(client):
    before_id, after_id, run = _post_change_pair(client)
    compared = client.post(
        f"/api/executions/{run['id']}/compare",
        json={"after_snapshot_id": after_id},
    )
    assert compared.status_code == 200, compared.text
    receipt_id = compared.json()["comparison_receipts"][-1]["id"]
    store = client.app.state.store
    columns = ("receipt_json", "receipt_sha256", "cutover_verdict", "created_at")
    originals = {
        column: _blob_column_bytes(
            store, "execution_comparisons", column, receipt_id
        )
        for column in columns
    }

    # Rewrite every ordinary TEXT/BLOB integrity field together. Internal text hashes can be made
    # mutually consistent by an attacker with raw database access, but the independent INTEGER
    # limbs remain bound to the originally admitted bytes/header and cannot be opened as blobs.
    for column, payload in originals.items():
        _blob_rewrite_same_length(
            store, "execution_comparisons", column, receipt_id,
            _changed_same_length(payload),
        )

    for method, path, body in (
        ("get", f"/api/executions/{run['id']}", None),
        ("get", f"/api/snapshots/{before_id}/executions", None),
        ("post", f"/api/executions/{run['id']}/event", {
            "kind": "note", "text": "must not mutate invalid authority",
        }),
        ("post", f"/api/executions/{run['id']}/compare", {
            "after_snapshot_id": after_id,
        }),
        ("post", f"/api/executions/{run['id']}/finish", {"status": "completed"}),
        ("get", f"/api/executions/{run['id']}/report", None),
    ):
        response = getattr(client, method)(path, **({"json": body} if body else {}))
        assert response.status_code == 409, (path, response.text)

    with store._lock:
        for column in ("authority_version", "verdict_code", "digest_0"):
            with pytest.raises(sqlite3.OperationalError):
                store._conn.blobopen(
                    "execution_comparison_authority", column, receipt_id,
                    readonly=False,
                )

    for column, payload in originals.items():
        _blob_rewrite_same_length(
            store, "execution_comparisons", column, receipt_id, payload
        )
    restored = client.get(f"/api/executions/{run['id']}")
    assert restored.status_code == 200, restored.text


def test_integer_anchor_rejects_coordinated_trial_source_blob_rewrites(
        client, tmp_path):
    _campaign_row, failed = _observed_failure_execution(client, tmp_path)
    receipt_id = failed["comparison_receipts"][-1]["id"]
    store = client.app.state.store
    columns = ("witness_blob", "witness_sha256", "source", "engagement_id")
    originals = {
        column: _blob_column_bytes(
            store, "execution_l2_failure_trial_sources", column, receipt_id
        )
        for column in columns
    }
    for column, payload in originals.items():
        _blob_rewrite_same_length(
            store, "execution_l2_failure_trial_sources", column, receipt_id,
            _changed_same_length(payload),
        )

    read = client.get(f"/api/executions/{failed['id']}")
    assert read.status_code == 409
    refused = client.post(
        f"/api/executions/{failed['id']}/event",
        json={"kind": "note", "text": "must not mutate invalid trial authority"},
    )
    assert refused.status_code == 409
    with store._lock:
        for table, column in (
            ("execution_l2_failure_trial_authority", "authority_version"),
            ("execution_l2_failure_trial_authority", "source_code"),
            ("execution_l2_failure_trial_authority", "digest_0"),
            ("execution_l2_failure_trial_sources", "pre_failure_snapshot_id"),
        ):
            with pytest.raises(sqlite3.OperationalError):
                store._conn.blobopen(table, column, receipt_id, readonly=False)

    for column, payload in originals.items():
        _blob_rewrite_same_length(
            store, "execution_l2_failure_trial_sources", column, receipt_id, payload
        )
    restored = client.get(f"/api/executions/{failed['id']}")
    assert restored.status_code == 200, restored.text
    assert restored.json()["l2_failure_trial_requirement"]["status"] == "observed_failure"


def test_integer_anchor_rejects_coordinated_snapshot_source_blob_rewrites(client):
    before_id, after_id, run = _post_change_pair(client)
    compared = client.post(
        f"/api/executions/{run['id']}/compare",
        json={"after_snapshot_id": after_id},
    )
    assert compared.status_code == 200, compared.text
    store = client.app.state.store
    columns = ("snapshot_json", "label", "script_version")
    originals = {
        column: _blob_column_bytes(store, "snapshots", column, after_id)
        for column in columns
    }
    for column, payload in originals.items():
        _blob_rewrite_same_length(
            store, "snapshots", column, after_id, _changed_same_length(payload)
        )

    compared_again = client.post(
        "/api/compare", json={"old_id": before_id, "new_id": after_id}
    )
    assert compared_again.status_code == 409
    execution_read = client.get(f"/api/executions/{run['id']}")
    assert execution_read.status_code == 409
    with store._lock:
        for table, column, row_id in (
            ("snapshot_authority", "authority_version", after_id),
            ("snapshot_authority", "digest_0", after_id),
            ("snapshots", "campaign_id", after_id),
            ("snapshots", "uploaded_at", after_id),
        ):
            with pytest.raises(sqlite3.OperationalError):
                store._conn.blobopen(table, column, row_id, readonly=False)

    for column, payload in originals.items():
        _blob_rewrite_same_length(store, "snapshots", column, after_id, payload)
    restored = client.get(f"/api/executions/{run['id']}")
    assert restored.status_code == 200, restored.text


def test_execution_authority_fold_stays_inside_one_sqlite_read_snapshot(
        client, monkeypatch):
    before_id, after_id, run = _post_change_pair(client)
    compared = client.post(
        f"/api/executions/{run['id']}/compare",
        json={"after_snapshot_id": after_id},
    )
    assert compared.status_code == 200, compared.text
    store = client.app.state.store
    original = store._execution_receipt_authority_locked
    transaction_states = []

    def traced(*args, **kwargs):
        transaction_states.append(("entry", store._conn.in_transaction))
        result = original(*args, **kwargs)
        transaction_states.append(("exit", store._conn.in_transaction))
        return result

    monkeypatch.setattr(store, "_execution_receipt_authority_locked", traced)
    assert client.get(f"/api/executions/{run['id']}").status_code == 200
    assert client.get(f"/api/snapshots/{before_id}/executions").status_code == 200
    assert store.list_execution_comparisons(run["id"])
    assert transaction_states
    assert all(in_transaction for _phase, in_transaction in transaction_states)


def test_authority_fold_retains_historical_failure_across_later_trialless_receipt(
        client, tmp_path):
    campaign, failed = _observed_failure_execution(client, tmp_path)
    store = client.app.state.store
    before_id = failed["snapshot_id"]
    recovery_id = failed["latest_comparison"]["after_snapshot_id"]
    recovery = store.get_snapshot(recovery_id)
    assert recovery is not None
    before = store.get_snapshot(before_id)
    assert before is not None
    later = deepcopy(before)
    later.pop("_assesshub_provenance", None)
    later["collected_at"] = (
        datetime.fromisoformat(recovery["collected_at"]) + timedelta(microseconds=1)
    ).isoformat()
    later["generated_at"] = later["collected_at"]
    later_id = _upload(
        client, campaign["id"], "historical trial-less receipt",
        json.dumps(later, separators=(",", ":"), allow_nan=False).encode("utf-8"),
    )
    before_source = store.get_bound_snapshot(before_id)
    later_source = store.get_bound_snapshot(later_id)
    assert before_source is not None and later_source is not None
    comparison = engine.compare_bound_pair(
        before_source[0], later_source[0],
        before_binding=before_source[1], after_binding=later_source[1],
    )
    receipt = engine.compact_execution_comparison(
        comparison,
        before_snapshot_id=before_id,
        after_snapshot_id=later_id,
        after_collected_at=later["collected_at"],
        implementation_binding=failed["latest_comparison"]["implementation_binding"],
    )
    with store._lock:
        created_at = datetime.now(timezone.utc).isoformat()
        encoded_receipt = json.dumps(
            receipt, separators=(",", ":"), allow_nan=False
        )
        cursor = store._conn.execute(
            """INSERT INTO execution_comparisons(
                   execution_id, before_snapshot_id, after_snapshot_id, receipt_sha256,
                   cutover_verdict, created_at, receipt_json)
               VALUES (?,?,?,?,?,?,?)""",
            (
                failed["id"], before_id, later_id, receipt["receipt_sha256"],
                comparison["cutover_gate"]["verdict"],
                created_at,
                encoded_receipt,
            ),
        )
        receipt_id = int(cursor.lastrowid or 0)
        verdict = comparison["cutover_gate"]["verdict"]
        limbs = storage_owner._comparison_authority_limbs(
            comparison_id=receipt_id,
            execution_id=failed["id"],
            before_snapshot_id=before_id,
            after_snapshot_id=later_id,
            receipt_sha256=receipt["receipt_sha256"],
            cutover_verdict=verdict,
            created_at=created_at,
            receipt_blob=encoded_receipt.encode("utf-8"),
        )
        store._conn.execute(
            """INSERT INTO execution_comparison_authority(
                   comparison_id,authority_version,verdict_code,
                   digest_0,digest_1,digest_2,digest_3)
               VALUES (?,?,?,?,?,?,?)""",
            (
                receipt_id, 1, storage_owner._CUTOVER_VERDICT_CODES[verdict], *limbs,
            ),
        )
        store._conn.commit()

    read = client.get(f"/api/executions/{failed['id']}")
    assert read.status_code == 200, read.text
    assert comparison["cutover_gate"]["verdict"] == "PASS"
    assert len(read.json()["comparison_receipts"]) == 2
    assert read.json()["latest_comparison"]["after_snapshot_id"] == later_id
    assert read.json()["l2_failure_trial_requirement"]["status"] \
        == "observed_failure"
    assert read.json()["l2_failure_trial_requirement"]["phase_sources"][
        "recovery"
    ]["snapshot_id"] == recovery_id


def test_execution_latest_comparison_cannot_regress_in_evidence_time(client):
    campaign = _campaign(client, "latest chronology", "ENG-LATEST-CHRONOLOGY")
    before_id = _upload(client, campaign["id"], "before")
    run = _action_all_steps(client, _start(client, before_id))
    completed_at = datetime.fromisoformat(
        execution.implementation_evidence_binding(run)["completed_at"]
    )
    older_id = _upload(
        client, campaign["id"], "older post-change",
        _post_change_raw(collected_at=completed_at + timedelta(microseconds=1)),
    )
    newer_id = _upload(
        client, campaign["id"], "newer post-change",
        _post_change_raw(collected_at=completed_at + timedelta(microseconds=2)),
    )

    newest = client.post(
        f"/api/executions/{run['id']}/compare",
        json={"after_snapshot_id": newer_id},
    )
    assert newest.status_code == 200, newest.text
    stale = client.post(
        f"/api/executions/{run['id']}/compare",
        json={"after_snapshot_id": older_id},
    )

    assert stale.status_code == 409
    assert "append-only in evidence time" in stale.text
    stored = client.app.state.store.get_execution(run["id"])
    assert stored is not None
    assert len(stored["comparisons"]) == 1
    assert stored["state"]["latest_comparison"]["after_snapshot_id"] == newer_id


def test_execution_not_verified_trial_requires_newer_exact_retrial_and_blocks_finish(
        client, tmp_path):
    campaign = _campaign(client, "not verified ratchet", "ENG-L2-NOT-VERIFIED")
    before_id = _upload(
        client,
        campaign["id"],
        "before",
        _execution_clear_raw(),
    )
    run = _action_all_steps(client, _start(client, before_id))
    anchor = datetime.fromisoformat(
        execution.implementation_evidence_binding(run)["completed_at"]
    )
    pre_id = _upload(
        client, campaign["id"], "pre-failure",
        _observed_ether_phase_raw(
            tmp_path / "pre", "pre", anchor + timedelta(microseconds=1)
        ),
    )
    post_id = _upload(
        client, campaign["id"], "post-without-failure",
        _observed_ether_phase_raw(
            tmp_path / "post", "unwitnessed", anchor + timedelta(microseconds=3)
        ),
    )
    recovery_id = _upload(
        client, campaign["id"], "recovery",
        _observed_ether_phase_raw(
            tmp_path / "recovery", "recovery", anchor + timedelta(microseconds=4)
        ),
    )
    witness = _observed_ether_witness(anchor + timedelta(microseconds=2))
    attempted = client.post(f"/api/executions/{run['id']}/compare", json={
        "after_snapshot_id": recovery_id,
        "l2_failure_trial": {
            "pre_failure_snapshot_id": pre_id,
            "post_failure_snapshot_id": post_id,
            "witness_json_base64": base64.b64encode(witness).decode("ascii"),
        },
    })
    assert attempted.status_code == 200, attempted.text
    assert attempted.json()["latest_comparison"]["cutover_gate"]["verdict"] \
        != "PASS"
    assert attempted.json()["latest_comparison"]["cutover_gate"][
        "l2_observed_trial_status"
    ] == "not_verified"
    assert attempted.json()["l2_failure_trial_requirement"]["status"] \
        == "not_verified"

    later_id = _upload(
        client, campaign["id"], "later without retrial",
        _observed_ether_phase_raw(
            tmp_path / "later", "recovery", anchor + timedelta(microseconds=5)
        ),
    )
    omitted = client.post(
        f"/api/executions/{run['id']}/compare",
        json={"after_snapshot_id": later_id},
    )
    assert omitted.status_code == 409
    assert "prior observed local l2 failure or not-verified trial remains unresolved" \
        in omitted.text.lower()

    ready = _pass_checks_and_close_waves(client, attempted.json())
    finished = client.post(
        f"/api/executions/{run['id']}/finish",
        json={"status": "completed"},
    )
    assert finished.status_code == 200, finished.text
    assert ready["status"] == "in_progress"
    assert finished.json()["outcome"] == execution.OUTCOME_PARTIAL


def test_execution_cannot_replay_old_survival_to_clear_newer_observed_failure(
        client, tmp_path):
    campaign = _campaign(client, "L2 replay ratchet", "ENG-L2-REPLAY")
    before_id = _upload(
        client, campaign["id"], "before",
        _post_change_raw(
            collected_at=datetime.now(timezone.utc) - timedelta(seconds=1)
        ),
    )
    run = _action_all_steps(client, _start(client, before_id))
    anchor = datetime.fromisoformat(
        execution.implementation_evidence_binding(run)["completed_at"]
    )

    def upload_trial(prefix: str, post_state: str, offset: int):
        pre_id = _upload(
            client, campaign["id"], f"{prefix} pre",
            _observed_ether_phase_raw(
                tmp_path / prefix / "pre", "pre",
                anchor + timedelta(microseconds=offset),
            ),
        )
        post_id = _upload(
            client, campaign["id"], f"{prefix} post",
            _observed_ether_phase_raw(
                tmp_path / prefix / "post", post_state,
                anchor + timedelta(microseconds=offset + 2),
            ),
        )
        recovery_id = _upload(
            client, campaign["id"], f"{prefix} recovery",
            _observed_ether_phase_raw(
                tmp_path / prefix / "recovery", "recovery",
                anchor + timedelta(microseconds=offset + 3),
            ),
        )
        witness = _observed_ether_witness(
            anchor + timedelta(microseconds=offset + 1)
        )
        return pre_id, post_id, recovery_id, witness

    old_pre, old_post, old_recovery, old_witness = upload_trial("old", "post", 1)
    old_survival = client.post(f"/api/executions/{run['id']}/compare", json={
        "after_snapshot_id": old_recovery,
        "l2_failure_trial": {
            "pre_failure_snapshot_id": old_pre,
            "post_failure_snapshot_id": old_post,
            "witness_json_base64": base64.b64encode(old_witness).decode("ascii"),
        },
    })
    assert old_survival.status_code == 200, old_survival.text
    assert old_survival.json()["latest_comparison"]["cutover_gate"][
        "l2_observed_trial_status"
    ] == "observed_survival"

    new_pre, new_post, new_recovery, new_witness = upload_trial("new", "failed", 5)
    new_failure = client.post(f"/api/executions/{run['id']}/compare", json={
        "after_snapshot_id": new_recovery,
        "l2_failure_trial": {
            "pre_failure_snapshot_id": new_pre,
            "post_failure_snapshot_id": new_post,
            "witness_json_base64": base64.b64encode(new_witness).decode("ascii"),
        },
    })
    assert new_failure.status_code == 200, new_failure.text
    requirement = new_failure.json()["l2_failure_trial_requirement"]
    assert requirement["phase_sources"]["recovery"]["snapshot_id"] == new_recovery

    replay = client.post(f"/api/executions/{run['id']}/compare", json={
        "after_snapshot_id": old_recovery,
        "l2_failure_trial": {
            "pre_failure_snapshot_id": old_pre,
            "post_failure_snapshot_id": old_post,
            "witness_json_base64": base64.b64encode(old_witness).decode("ascii"),
        },
    })

    assert replay.status_code == 409
    stored = client.app.state.store.get_execution(run["id"])
    assert stored is not None
    assert len(stored["comparisons"]) == 2
    assert stored["state"]["l2_failure_trial_requirement"]["phase_sources"][
        "recovery"
    ]["snapshot_id"] == new_recovery

    fresh_pre, fresh_post, fresh_recovery, fresh_witness = upload_trial(
        "fresh", "post", 9
    )
    cleared = client.post(f"/api/executions/{run['id']}/compare", json={
        "after_snapshot_id": fresh_recovery,
        "l2_failure_trial": {
            "pre_failure_snapshot_id": fresh_pre,
            "post_failure_snapshot_id": fresh_post,
            "witness_json_base64": base64.b64encode(fresh_witness).decode("ascii"),
        },
    })
    assert cleared.status_code == 200, cleared.text
    assert "l2_failure_trial_requirement" not in cleared.json()
    assert cleared.json()["latest_comparison"]["cutover_gate"][
        "l2_observed_trial_status"
    ] == "observed_survival"
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


def test_unresolved_observed_failure_requirement_blocks_even_a_later_pass_gate():
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
        "l2_failure_trial_requirement": {
            "schema": "execution_l2_failure_trial_requirement/1",
            "family": "etherchannel",
            "subject": "dist1|Po10",
            "failure_scenario": "single_observed_forwarding_member_loss",
            "status": "observed_failure",
            "latest_receipt_id": 1,
        },
        "latest_comparison": {
            "schema": "execution_latest_comparison/1",
            "cutover_gate": {"schema": "cutover_gate/1", "verdict": "PASS"},
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
                "UPDATE snapshots SET uploaded_at=? WHERE id=?",
                ("2099-01-01T00:00:00+00:00", after_id),
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
