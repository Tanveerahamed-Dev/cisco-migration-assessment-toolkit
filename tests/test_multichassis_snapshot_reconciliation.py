"""Persisted multichassis baselines must reconcile to their snapshot evidence denominator."""

from __future__ import annotations

import json

from cisco_toolkit.multichassis_lag import (
    MULTICHASSIS_LAG_DELTA_SCHEMA,
    compute_multichassis_lag_domain_baseline,
    validate_multichassis_lag_snapshot_evidence,
)
from cisco_toolkit.protocol_assurance import (
    bind_snapshot_json_bytes,
    bound_snapshot_source,
    compute_native_protocol_deltas,
)
from tests.test_multichassis_raw_sources import _nxos_pair


def _plain(value):
    return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))


def _persisted_pair() -> dict:
    typed = _nxos_pair()
    baseline = compute_multichassis_lag_domain_baseline(typed)
    return {
        "script_version": "multichassis-snapshot-reconciliation-test/1",
        "devices": {"leaf-a": {}, "leaf-b": {}},
        "multichassis_lag_typed_observations": _plain(typed),
        "multichassis_lag_domain_baseline": _plain(baseline),
    }


def _native_delta(snapshot: dict) -> dict:
    raw = json.dumps(
        snapshot,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    bound = bind_snapshot_json_bytes(raw)
    binding = bound_snapshot_source(bound)
    return next(
        result
        for result in compute_native_protocol_deltas(
            bound,
            bound,
            before_binding=binding,
            after_binding=binding,
        )
        if result.get("schema") == MULTICHASSIS_LAG_DELTA_SCHEMA
    )


def test_honest_copublished_pair_remains_decision_grade() -> None:
    snapshot = _persisted_pair()

    validation = validate_multichassis_lag_snapshot_evidence(
        snapshot["multichassis_lag_domain_baseline"],
        snapshot["multichassis_lag_typed_observations"],
        snapshot["devices"],
    )
    delta = _native_delta(snapshot)

    assert validation["valid"] is True
    assert validation["local_subjects"] == ["leaf-a", "leaf-b"]
    assert delta["comparison_failures"] == []
    assert delta["summary"]["by_transition"]["unchanged_healthy"] == 6
    assert any(row["record_type"] == "reciprocal_peer_pair" for row in delta["changes"])
    assert any(row["record_type"] == "reconciled_attachment" for row in delta["changes"])


def test_one_sided_typed_set_cannot_reuse_a_healthy_two_peer_baseline() -> None:
    snapshot = _persisted_pair()
    snapshot["multichassis_lag_typed_observations"]["observations"].pop()

    validation = validate_multichassis_lag_snapshot_evidence(
        snapshot["multichassis_lag_domain_baseline"],
        snapshot["multichassis_lag_typed_observations"],
        snapshot["devices"],
    )
    delta = _native_delta(snapshot)

    assert validation["valid"] is False
    assert validation["reason"] == "typed_observation_count_does_not_reconcile"
    assert delta["assurance_level"] == "not_verified"
    assert delta["changes"] == []
    assert delta["summary"]["by_transition"]["not_comparable"] == 1
    assert delta["summary"]["by_transition"]["unchanged_healthy"] == 0


def test_multichassis_local_hosts_must_belong_to_snapshot_devices() -> None:
    snapshot = _persisted_pair()
    snapshot["devices"] = {"unrelated-router": {}}

    validation = validate_multichassis_lag_snapshot_evidence(
        snapshot["multichassis_lag_domain_baseline"],
        snapshot["multichassis_lag_typed_observations"],
        snapshot["devices"],
    )
    delta = _native_delta(snapshot)

    assert validation["valid"] is False
    assert validation["reason"] == "multichassis_local_subject_not_in_snapshot_devices"
    assert validation["local_subjects"] == ["leaf-a", "leaf-b"]
    assert delta["assurance_level"] == "not_verified"
    assert delta["changes"] == []
    assert delta["summary"]["by_transition"]["not_comparable"] == 1


def test_baseline_without_copublished_typed_rows_abstains() -> None:
    snapshot = _persisted_pair()
    snapshot.pop("multichassis_lag_typed_observations")

    delta = _native_delta(snapshot)

    assert delta["assurance_level"] == "not_verified"
    assert delta["changes"] == []
    assert delta["summary"]["by_transition"]["not_comparable"] == 1


def test_typed_only_legacy_fallback_stays_local_and_not_verified() -> None:
    snapshot = _persisted_pair()
    snapshot.pop("multichassis_lag_domain_baseline")

    delta = _native_delta(snapshot)

    assert delta["assurance_level"] == "not_verified"
    assert delta["changes"]
    assert delta["summary"]["by_transition"]["unchanged_healthy"] == 0
    assert all(row["transition"] == "not_comparable" for row in delta["changes"])
    assert not any(
        row["record_type"] in {"reciprocal_peer_pair", "reconciled_attachment"}
        for row in delta["changes"]
    )
