"""Persisted multichassis baselines must reconcile to their snapshot evidence denominator."""

from __future__ import annotations

import json

from cisco_toolkit.multichassis_lag import (
    MULTICHASSIS_LAG_DELTA_SCHEMA,
    compute_multichassis_lag_domain_baseline,
    validate_multichassis_lag_snapshot_evidence,
)
from cisco_toolkit.l2_rehearsal import compute_l2_failure_rehearsal
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


def test_positive_legacy_local_subjects_must_exactly_match_typed_locals() -> None:
    snapshot = _persisted_pair()
    exact_vpc = {
        "LEAF-A": {"domain_id": "10", "peer_status": "peer adjacency formed ok"},
        "leaf-B": {"domain_id": "10", "peer_status": "peer adjacency formed ok"},
    }

    exact = validate_multichassis_lag_snapshot_evidence(
        snapshot["multichassis_lag_domain_baseline"],
        snapshot["multichassis_lag_typed_observations"],
        snapshot["devices"],
        legacy_vpc=exact_vpc,
    )
    missing = validate_multichassis_lag_snapshot_evidence(
        snapshot["multichassis_lag_domain_baseline"],
        snapshot["multichassis_lag_typed_observations"],
        snapshot["devices"],
        legacy_vpc={"leaf-a": exact_vpc["LEAF-A"]},
    )
    extra = validate_multichassis_lag_snapshot_evidence(
        snapshot["multichassis_lag_domain_baseline"],
        snapshot["multichassis_lag_typed_observations"],
        {**snapshot["devices"], "leaf-c": {}},
        legacy_vpc={**exact_vpc, "leaf-c": {
            "domain_id": "99", "peer_status": "peer adjacency not formed",
        }},
    )

    assert exact["valid"] is True
    assert exact["legacy_local_subjects"] == ["LEAF-A", "leaf-B"]
    for rejected in (missing, extra):
        assert rejected["valid"] is False
        assert rejected["reason"] == "legacy_local_subjects_do_not_reconcile"
        assert rejected["baseline"] == {}


def test_native_and_rehearsal_consumers_cannot_bypass_legacy_local_reconciliation() -> None:
    snapshot = _persisted_pair()
    snapshot["devices"]["leaf-c"] = {}
    snapshot["vpc"] = {
        "leaf-a": {"domain_id": "10", "peer_status": "peer adjacency formed ok"},
        "leaf-b": {"domain_id": "10", "peer_status": "peer adjacency formed ok"},
        "leaf-c": {"domain_id": "99", "peer_status": "peer adjacency not formed"},
    }
    raw = json.dumps(
        snapshot,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    bound = bind_snapshot_json_bytes(raw)

    native = _native_delta(snapshot)
    rehearsal = compute_l2_failure_rehearsal(bound)
    multichassis = [
        row for row in rehearsal["scenarios"]
        if row["family"] == "multichassis_lag"
    ]

    assert native["summary"]["by_transition"]["not_comparable"] == 1
    assert native["summary"]["by_transition"]["unchanged_healthy"] == 0
    assert multichassis
    assert {row["disposition"] for row in multichassis} == {"not_verified"}
    assert all("co-published typed observation" in row["note"]
               for row in multichassis)


def test_ambiguous_or_malformed_positive_legacy_locals_fail_closed() -> None:
    snapshot = _persisted_pair()
    positive = {"domain_id": "10", "peer_status": "peer adjacency formed ok"}
    cases = (
        {
            "legacy_vpc": {"leaf-a": positive, "LEAF-A": positive, "leaf-b": positive},
        },
        {
            "legacy_vpc": {"leaf-a": positive, "leaf-b": positive},
            "legacy_arista": {"LEAF-A": {"mlag": {"domain_id": "MLAG-1"}}},
        },
        {"legacy_vpc": {"leaf-a": "malformed-positive", "leaf-b": positive}},
        {"legacy_arista": "malformed-positive-root"},
    )

    for supplied in cases:
        rejected = validate_multichassis_lag_snapshot_evidence(
            snapshot["multichassis_lag_domain_baseline"],
            snapshot["multichassis_lag_typed_observations"],
            snapshot["devices"],
            **supplied,
        )
        assert rejected["valid"] is False
        assert rejected["reason"] == (
            "legacy_local_subject_identity_invalid_or_ambiguous"
        )
        assert rejected["baseline"] == {}


def test_empty_legacy_containers_do_not_create_a_runtime_denominator() -> None:
    snapshot = _persisted_pair()

    validation = validate_multichassis_lag_snapshot_evidence(
        snapshot["multichassis_lag_domain_baseline"],
        snapshot["multichassis_lag_typed_observations"],
        snapshot["devices"],
        legacy_vpc={},
        legacy_arista={"eos-not-running-mlag": {"mlag": {}}},
    )

    assert validation["valid"] is True
    assert validation["legacy_local_subjects"] == []


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
