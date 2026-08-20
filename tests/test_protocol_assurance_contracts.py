"""Release-1 source/custody/intent contracts around the canonical cutover decision."""

from copy import deepcopy
import json

from cisco_toolkit import protocol_assurance as pa
from cisco_toolkit.comparison import (
    bound_comparison_decision_input_authority,
    compare_bound_pair,
)
from cisco_toolkit.html import compute_cutover_gate


def _bound_snapshot(value):
    raw = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return pa.bind_snapshot_json_bytes(raw)


def _binding(snapshot_id=1, *, campaign=7, engagement="ENG-7", digest="1",
             snapshot=None, source=pa.PERSISTED_SOURCE):
    marker = pa.bound_snapshot_source(snapshot) if snapshot is not None else {}
    return {
        "source": source,
        "sha256": marker.get("sha256") or "sha256:" + digest * 64,
        "bytes": marker.get("bytes") or 100,
        "snapshot_id": snapshot_id,
        "campaign_id": campaign,
        "engagement_id": engagement,
        "label": f"s{snapshot_id}",
        "script_version": "V3.23.0",
    }


def _owner_versions(before_binding, after_binding):
    return pa.canonical_decision_owner_versions(
        before_snapshot_owner=before_binding.get("script_version"),
        after_snapshot_owner=after_binding.get("script_version"),
    )


def _admission_for(before, after, before_binding, after_binding):
    intent = pa.normalize_change_intent(None, binding={
        "engagement_id": before_binding.get("engagement_id"),
        "campaign_id": before_binding.get("campaign_id"),
        "before_snapshot_id": before_binding.get("snapshot_id"),
        "after_snapshot_id": after_binding.get("snapshot_id"),
        "before_sha256": before_binding.get("sha256"),
        "after_sha256": after_binding.get("sha256"),
    })
    return pa.comparison_admission(
        before,
        after,
        before_binding=before_binding,
        after_binding=after_binding,
        schema_status={"status": "ok"},
        change_intent=intent,
        owner_versions=_owner_versions(before_binding, after_binding),
        support_profiles=pa.protocol_support_profiles(),
    )


def _canonical_admission(*, before=None, after=None, before_binding=None, after_binding=None):
    if before is None:
        before = {"script_version": "V3.23.0", "devices": {"leaf-1": {}}}
    if after is None:
        after = {"script_version": "V3.23.0", "devices": {"leaf-1": {}}}
    if not isinstance(before, pa.BoundSnapshot):
        before = _bound_snapshot(before)
    if not isinstance(after, pa.BoundSnapshot):
        after = _bound_snapshot(after)
    if before_binding is None:
        before_binding = _binding(snapshot=before)
    if after_binding is None:
        after_binding = _binding(2, snapshot=after)
    return _admission_for(before, after, before_binding, after_binding)


def _native_source_receipts(*, before_bound=True, after_bound=True):
    def receipt(side, comparison_bound):
        return {
            "present": True,
            "valid": True,
            "source_bound": comparison_bound,
            "owner_source_authority": True,
            "comparison_source_bound": comparison_bound,
            "comparison_source_basis": (
                "current_run_owner_source" if comparison_bound else "not_source_bound"
            ),
            "snapshot_sha256": "" if comparison_bound else "sha256:" + side * 64,
            "projection_sha256": "sha256:" + ("a" if side == "1" else "b") * 64,
            "reason": "ok",
        }

    return {
        "before": receipt("1", before_bound),
        "after": receipt("2", after_bound),
    }


def _protocol_native_delta(*, transition, effect, assurance="local_safety_preservation",
                           applicability="applicable", receipts=None):
    rows = [] if transition is None else [{
        "family": "vtp_safety",
        "subject": "dist-1",
        "transition": transition,
        "decision_effect": effect,
        "before_state": {"revision": 4},
        "after_state": {"revision": 5},
        "note": "Producer-owned VTP transition.",
    }]
    by_transition = {token: 0 for token in pa.CHANGE_VOCABULARY}
    by_effect = {token: 0 for token in ("block", "review", "none", "not_verified")}
    for row in rows:
        by_transition[row["transition"]] += 1
        by_effect[row["decision_effect"]] += 1
    comparable = sum(
        count for token, count in by_transition.items()
        if token not in {"coverage_lost", "not_comparable"}
    )
    return {
        "schema": "vtp_safety_delta/1",
        "family": "vtp_safety",
        "owner": "vtp_safety_delta/1",
        "assurance_level": assurance,
        "owns_score": False,
        "owns_verdict": False,
        "applicability": applicability,
        "comparable": bool(comparable) and not by_transition["not_comparable"],
        "assessed": bool(comparable) and not (
            by_transition["coverage_lost"] or by_transition["not_comparable"]),
        "source_receipts": receipts or _native_source_receipts(),
        "summary": {
            "n_subjects": len(rows),
            "n_comparable": comparable,
            "by_transition": by_transition,
            "by_decision_effect": by_effect,
        },
        "changes": rows,
        "limitations": ["Test fixture exercises only the composition contract."],
    }


def _multichassis_source_binding():
    return {
        "custody": "persisted_snapshot_bytes_bound",
        "before_snapshot_sha256": "sha256:" + "1" * 64,
        "after_snapshot_sha256": "sha256:" + "2" * 64,
        "before_baseline_sha256": "sha256:" + "3" * 64,
        "after_baseline_sha256": "sha256:" + "4" * 64,
    }


def test_shared_vocabularies_and_support_profile_are_closed():
    assert pa.CHANGE_VOCABULARY == (
        "unchanged_healthy", "unchanged_degraded", "recovered", "regressed",
        "appeared", "disappeared", "intent_changed", "coverage_lost", "not_comparable",
    )
    assert pa.ASSURANCE_LEVELS == (
        "intent_reconciled_survival", "observed_state_preservation",
        "local_safety_preservation", "not_verified",
    )
    profiles = pa.protocol_support_profiles()
    assert len(profiles) == 10
    assert len({profile["family"] for profile in profiles}) == len(profiles)
    assert {profile["family"] for profile in profiles} == {
        "ipv4_routing_adjacency", "ipv6_routing_adjacency", "bgp_configured_peer",
        "stp_consistency", "stp_topology", "etherchannel", "vtp_safety",
        "fhrp_configured_group", "fhrp_redundancy_domain", "multichassis_lag",
    }
    assert profiles[0]["schema"] == "protocol_support_profile/1"
    assert profiles[0]["family"] == "ipv4_routing_adjacency"
    assert profiles[0]["implementation_state"] == "implemented"
    assert all(profile["schema"] == "protocol_support_profile/1" for profile in profiles)
    assert all(profile["implementation_state"] == "implemented" for profile in profiles)
    assert all("Catalog presence" in " ".join(profile["limitations"]) for profile in profiles)
    multichassis = next(profile for profile in profiles if profile["family"] == "multichassis_lag")
    assert [(row["platform"], row["collection_modes"]) for row in multichassis["variants"]] == [
        ("nxos", ["live", "offline"]), ("eos", ["offline"]),
    ]


def test_subject_identity_collision_is_a_noncomparable_admission():
    before = _bound_snapshot({
        "script_version": "V3.23.0", "devices": {"Leaf-1": {}, "leaf-1": {}},
    })
    after = _bound_snapshot({
        "script_version": "V3.23.0", "devices": {"Leaf-1": {}},
    })
    before_binding = _binding(snapshot=before)
    after_binding = _binding(2, snapshot=after)
    intent = pa.normalize_change_intent(None, binding={
        "engagement_id": "ENG-7", "campaign_id": 7,
        "before_snapshot_id": 1, "after_snapshot_id": 2,
        "before_sha256": before_binding["sha256"],
        "after_sha256": after_binding["sha256"],
    })
    admission = pa.comparison_admission(
        before,
        after,
        before_binding=before_binding,
        after_binding=after_binding,
        schema_status={"status": "ok", "message": "", "override": False},
        change_intent=intent,
        owner_versions=_owner_versions(before_binding, after_binding),
        support_profiles=pa.protocol_support_profiles(),
    )
    assert admission["status"] == "not_comparable"
    assert admission["decision_eligible"] is False
    assert any("collision" in item for item in admission["failures"])
    assert pa.validate_comparison_admission(admission)["valid"] is True


def test_admission_fails_closed_for_renamed_truncated_or_mismatched_custody_leaves():
    before = _bound_snapshot({"script_version": "V3.23.0", "devices": {"leaf-1": {}}})
    after = _bound_snapshot({"script_version": "V3.23.0", "devices": {"leaf-1": {}}})
    exact_before = _binding(snapshot=before)
    exact_after = _binding(2, snapshot=after)

    def admit(before_binding, after_binding):
        intent = pa.normalize_change_intent(None, binding={
            "engagement_id": before_binding.get("engagement_id"),
            "campaign_id": before_binding.get("campaign_id"),
            "before_snapshot_id": before_binding.get("snapshot_id"),
            "after_snapshot_id": after_binding.get("snapshot_id"),
            "before_sha256": before_binding.get("sha256"),
            "after_sha256": after_binding.get("sha256"),
        })
        return pa.comparison_admission(
            before, after,
            before_binding=before_binding, after_binding=after_binding,
            schema_status={"status": "ok"}, change_intent=intent,
            owner_versions=_owner_versions(before_binding, after_binding),
            support_profiles=pa.protocol_support_profiles(),
        )

    assert admit(exact_before, exact_after)["status"] == "admitted"
    mutations = []
    missing_bytes = deepcopy(exact_after)
    missing_bytes.pop("bytes")
    mutations.append(missing_bytes)
    renamed_hash = deepcopy(exact_after)
    renamed_hash["digest"] = renamed_hash.pop("sha256")
    mutations.append(renamed_hash)
    wrong_source = deepcopy(exact_after)
    wrong_source["source"] = "re-serialized request body"
    mutations.append(wrong_source)
    mismatched_owner = deepcopy(exact_after)
    mismatched_owner["script_version"] = "V9"
    mutations.append(mismatched_owner)
    for mutation in mutations:
        result = admit(exact_before, mutation)
        assert result["status"] == "not_comparable"
        assert result["decision_eligible"] is False


def test_admission_accepts_only_exact_bound_persisted_or_offline_file_bytes():
    for source in (pa.PERSISTED_SOURCE, pa.OFFLINE_FILE_SOURCE):
        before = _bound_snapshot({
            "script_version": "V3.23.0", "devices": {"leaf-1": {}}, "sequence": 1,
        })
        after = _bound_snapshot({
            "script_version": "V3.23.0", "devices": {"leaf-1": {}}, "sequence": 2,
        })
        before_binding = _binding(snapshot=before, source=source)
        after_binding = _binding(2, snapshot=after, source=source)

        admission = _admission_for(before, after, before_binding, after_binding)

        assert admission["status"] == "admitted", source
        assert admission["decision_eligible"] is True, source
        assert admission["source_binding"]["before"]["source"] == source
        assert pa.validate_comparison_admission(admission)["valid"] is True, source


def test_detached_mutated_or_mismatched_bound_snapshot_marker_withholds_gate():
    clean_delta = {
        "verdict": "CLEAN",
        "verdict_display": "NO DELTA REGRESSION OBSERVED",
        "verdict_note": "clean",
        "protocol_adjacencies": {
            "gate": "PASS",
            "summary": {
                "n_state_regressed": 0,
                "n_coverage_gaps": 0,
                "n_baseline_peers": 1,
            },
        },
    }
    certificate = {"verdict": "PASS", "verdict_note": "clean"}

    before = _bound_snapshot({
        "script_version": "V3.23.0", "devices": {"leaf-1": {}}, "sequence": 1,
    })
    exact_after = _bound_snapshot({
        "script_version": "V3.23.0", "devices": {"leaf-1": {}}, "sequence": 2,
    })
    before_binding = _binding(snapshot=before)
    exact_after_binding = _binding(2, snapshot=exact_after)

    mutated_after = _bound_snapshot(dict(exact_after))
    mutated_after["devices"]["leaf-2"] = {}
    mutated_binding = _binding(2, snapshot=mutated_after)
    # The binding must represent the bytes parsed before the in-memory mutation.
    mutated_binding.update({
        "sha256": exact_after_binding["sha256"],
        "bytes": exact_after_binding["bytes"],
    })

    marker_tampered_after = _bound_snapshot(dict(exact_after))
    marker_tampered_binding = _binding(2, snapshot=marker_tampered_after)
    marker_tampered_after._bound_source_sha256 = "sha256:" + "f" * 64

    mismatched_hash_binding = deepcopy(exact_after_binding)
    mismatched_hash_binding["sha256"] = "sha256:" + "e" * 64
    mismatched_bytes_binding = deepcopy(exact_after_binding)
    mismatched_bytes_binding["bytes"] += 1

    cases = (
        ("detached dict with caller hash", dict(exact_after), exact_after_binding),
        ("mutated live snapshot", mutated_after, mutated_binding),
        ("tampered process-local marker", marker_tampered_after, marker_tampered_binding),
        ("binding hash mismatch", exact_after, mismatched_hash_binding),
        ("binding byte-count mismatch", exact_after, mismatched_bytes_binding),
    )
    for label, after, after_binding in cases:
        admission = _admission_for(before, after, before_binding, after_binding)
        assert admission["status"] == "not_comparable", label
        assert admission["decision_eligible"] is False, label
        assert admission["assurance_level"] == "not_verified", label
        assert any(
            "parsed snapshot" in failure for failure in admission["failures"]
        ), label
        # The serialized non-admitted explanation is canonical even though its live proof failed.
        assert pa.validate_comparison_admission(admission)["valid"] is True, label
        gate = compute_cutover_gate(
            clean_delta,
            certificate,
            comparison_admission=admission,
        )
        assert gate["verdict"] == "INDETERMINATE", label
        assert gate["comparison_admission_status"] == "not_comparable", label

    admitted = _admission_for(
        before, exact_after, before_binding, exact_after_binding)
    unsupported = deepcopy(admitted)
    unsupported["source_binding"]["after"]["source"] = "input file"
    assert pa.validate_comparison_admission(unsupported)["valid"] is False
    assert compute_cutover_gate(
        clean_delta,
        certificate,
        comparison_admission=unsupported,
    )["verdict"] == "INDETERMINATE"


def test_change_intent_cannot_expected_away_coverage_loss():
    intent = pa.normalize_change_intent({
        "expected_changes": [{
            "family": "ipv4_routing_adjacency",
            "transitions": ["coverage_lost"],
            "subjects": [],
        }]
    }, binding={})
    assert intent["schema"] == "cutover_change_intent/1"
    assert intent["valid"] is False and intent["status"] == "invalid"
    assert any("cannot authorize" in item for item in intent["failures"])


def test_change_intent_rejects_unknown_or_malformed_fields_and_never_admits():
    before = _bound_snapshot({"script_version": "V3.23.0", "devices": {"leaf-1": {}}})
    after = _bound_snapshot({"script_version": "V3.23.0", "devices": {"leaf-1": {}}})
    before_binding = _binding(snapshot=before)
    after_binding = _binding(2, snapshot=after)
    intent_binding = {
        "engagement_id": before_binding["engagement_id"],
        "campaign_id": before_binding["campaign_id"],
        "before_snapshot_id": before_binding["snapshot_id"],
        "after_snapshot_id": after_binding["snapshot_id"],
        "before_sha256": before_binding["sha256"],
        "after_sha256": after_binding["sha256"],
    }
    malformed = (
        {"expected_change": []},
        {
            "expected_changes": [{
                "family": "ipv4_routing_adjacency",
                "transitions": ["appeared"],
                "subjects": [],
                "reasno": "misspelled reason",
            }],
        },
        {
            "expected_changes": [{
                "family": "not_an_executable_family",
                "transitions": ["appeared"],
                "subjects": [],
            }],
        },
        {
            "expected_changes": [{
                "family": "ipv4_routing_adjacency",
                "transitions": ["appeared"],
                "subjects": [7],
            }],
        },
    )
    clean_delta = {
        "verdict": "CLEAN",
        "verdict_display": "NO DELTA REGRESSION OBSERVED",
        "verdict_note": "clean",
        "protocol_adjacencies": {
            "gate": "PASS",
            "summary": {
                "n_state_regressed": 0,
                "n_coverage_gaps": 0,
                "n_baseline_peers": 1,
            },
        },
    }
    certificate = {"verdict": "PASS", "verdict_note": "clean"}

    for raw in malformed:
        intent = pa.normalize_change_intent(raw, binding=intent_binding)
        assert intent["status"] == "invalid", raw
        assert intent["valid"] is False, raw
        assert intent["failures"], raw
        admission = pa.comparison_admission(
            before,
            after,
            before_binding=before_binding,
            after_binding=after_binding,
            schema_status={"status": "ok"},
            change_intent=intent,
            owner_versions=_owner_versions(before_binding, after_binding),
            support_profiles=pa.protocol_support_profiles(),
        )
        assert admission["status"] == "not_comparable", raw
        assert admission["decision_eligible"] is False, raw
        assert compute_cutover_gate(
            clean_delta,
            certificate,
            comparison_admission=admission,
        )["verdict"] == "INDETERMINATE", raw

    canonical = pa.normalize_change_intent(None, binding=intent_binding)
    assert pa.validate_change_intent(canonical)["valid"] is True
    wrong_schema = deepcopy(canonical)
    wrong_schema["schema"] = "cutover_change_intent/999"
    missing_digest = deepcopy(canonical)
    missing_digest.pop("expected_changes_sha256")
    for malformed_receipt in (
        {"valid": True, "binding": intent_binding, "expected_changes": []},
        wrong_schema,
        missing_digest,
    ):
        admission = pa.comparison_admission(
            before,
            after,
            before_binding=before_binding,
            after_binding=after_binding,
            schema_status={"status": "ok"},
            change_intent=malformed_receipt,
            owner_versions=_owner_versions(before_binding, after_binding),
            support_profiles=pa.protocol_support_profiles(),
        )
        assert admission["status"] == "not_comparable", malformed_receipt
        assert admission["decision_eligible"] is False, malformed_receipt
        assert any(
            item.startswith("change intent contract:")
            for item in admission["failures"]
        ), malformed_receipt
        assert compute_cutover_gate(
            clean_delta,
            certificate,
            comparison_admission=admission,
        )["verdict"] == "INDETERMINATE", malformed_receipt


def test_family_change_set_is_reference_only_and_classifies_expected_changes():
    intent = pa.normalize_change_intent({
        "expected_changes": [{
            "family": "ipv4_routing_adjacency",
            "transitions": ["appeared"],
            "subjects": ["sw1|BGP|192.0.2.1"],
            "reason": "planned peer replacement",
        }]
    }, binding={})
    delta = {
        "schema": "protocol_adjacency_delta/1",
        "summary": {"n_preserved": 3},
        "changes": [
            {"switch": "sw1", "protocol": "BGP", "peer": "192.0.2.1",
             "before_state": "not observed", "after_state": "Established",
             "result": "added", "note": "new"},
            {"switch": "sw2", "protocol": "OSPF", "peer": "10.0.0.2",
             "before_state": "FULL", "after_state": "EXSTART",
             "result": "state_degraded", "note": "bad"},
        ],
        "coverage_gaps": [{
            "switch": "sw3", "protocol": "EIGRP", "before_state": "assessed",
            "after_state": "capture_missing", "reason": "not comparable",
        }],
    }
    result = pa.protocol_family_change_set(delta, intent)
    assert result["schema"] == "protocol_family_change_set/1"
    assert result["owns_score"] is False and result["owns_verdict"] is False
    assert "verdict" not in result and "gate" not in result
    family = result["families"][0]
    by_subject = {row["subject"]: row for row in family["changes"]}
    assert by_subject["sw1|BGP|192.0.2.1"]["expected"] is True
    assert by_subject["sw1|BGP|192.0.2.1"]["decision_effect"] == "none"
    assert by_subject["sw2|OSPF|10.0.0.2"]["transition"] == "regressed"
    assert by_subject["sw2|OSPF|10.0.0.2"]["decision_effect"] == "block"
    assert by_subject["sw3|EIGRP|*"]["transition"] == "coverage_lost"
    assert by_subject["sw3|EIGRP|*"]["expected"] is False
    assert by_subject["sw3|EIGRP|*"]["decision_effect"] == "not_verified"
    assert family["summary"]["by_transition"]["unchanged_healthy"] == 3
    assert family["summary"]["n_blocking"] == 1


def test_native_intent_can_clear_review_but_never_a_block_or_abstention():
    ipv4 = {
        "schema": "protocol_adjacency_delta/1",
        "summary": {"n_preserved": 0},
        "changes": [],
        "coverage_gaps": [],
    }

    def native(effect: str, transition: str) -> dict:
        return _protocol_native_delta(
            transition=transition,
            effect=effect,
            assurance=(
                "not_verified" if effect == "not_verified" else "local_safety_preservation"
            ),
        )

    intent = {"expected_changes": [{
        "family": "vtp_safety",
        "transitions": ["intent_changed", "unchanged_degraded"],
        "subjects": ["dist-1"],
    }]}
    reviewed = pa.protocol_family_change_set(
        ipv4, intent, native_deltas=[native("review", "intent_changed")])
    row = next(
        row for family in reviewed["families"] if family["family"] == "vtp_safety"
        for row in family["changes"]
    )
    assert row["expected"] is True
    assert row["decision_effect"] == "none"

    blocked = pa.protocol_family_change_set(
        ipv4, intent, native_deltas=[native("block", "unchanged_degraded")])
    row = next(
        row for family in blocked["families"] if family["family"] == "vtp_safety"
        for row in family["changes"]
    )
    assert row["expected"] is True
    assert row["decision_effect"] == "block"

    abstained = pa.protocol_family_change_set(
        ipv4, {"expected_changes": []},
        native_deltas=[native("not_verified", "coverage_lost")],
    )
    row = next(
        row for family in abstained["families"] if family["family"] == "vtp_safety"
        for row in family["changes"]
    )
    assert row["expected"] is False
    assert row["decision_effect"] == "not_verified"


def test_native_protocol_composition_requires_applicability_nonvacuity_and_bound_custody():
    ipv4 = {
        "schema": "protocol_adjacency_delta/1",
        "summary": {"n_preserved": 0},
        "changes": [],
        "coverage_gaps": [],
    }
    delta = {
        "verdict": "CLEAN",
        "verdict_display": "NO DELTA REGRESSION OBSERVED",
        "verdict_note": "clean",
        "protocol_adjacencies": {
            "gate": "PASS",
            "summary": {
                "n_state_regressed": 0,
                "n_coverage_gaps": 0,
                "n_baseline_peers": 1,
            },
        },
    }
    certificate = {"verdict": "PASS", "verdict_note": "clean"}

    trusted = pa.protocol_family_change_set(
        ipv4,
        {"expected_changes": []},
        native_deltas=pa.compute_native_protocol_deltas({}, {}),
    )
    assert pa.validate_protocol_family_change_set_authority(trusted)["valid"] is True
    assert compute_cutover_gate(
        delta, certificate, protocol_family_changes=trusted)["verdict"] == "PASS"

    def compose(native):
        return pa.protocol_family_change_set(
            ipv4, {"expected_changes": []}, native_deltas=[native])

    def family(change_set):
        return next(
            item for item in change_set["families"] if item["family"] == "vtp_safety")

    healthy = _protocol_native_delta(transition="unchanged_healthy", effect="none")
    accepted = compose(healthy)
    assert family(accepted)["composition_failures"] == []
    assert pa.validate_protocol_family_change_set_authority(accepted)["valid"] is False
    assert compute_cutover_gate(
        delta, certificate, protocol_family_changes=accepted)["verdict"] == "INDETERMINATE"

    not_applicable = _protocol_native_delta(
        transition=None, effect="none", applicability="not_applicable")
    accepted_na = compose(not_applicable)
    assert family(accepted_na)["changes"] == []
    assert family(accepted_na)["composition_failures"] == []
    assert compute_cutover_gate(
        delta, certificate, protocol_family_changes=accepted_na)["verdict"] == "INDETERMINATE"

    unbound_na = _protocol_native_delta(
        transition=None,
        effect="none",
        applicability="not_applicable",
        receipts=_native_source_receipts(after_bound=False),
    )
    refused_na_set = compose(unbound_na)
    refused_na = family(refused_na_set)
    assert refused_na["changes"][0]["transition"] == "not_comparable"
    assert refused_na["assurance_level"] == "not_verified"
    assert compute_cutover_gate(
        delta, certificate, protocol_family_changes=refused_na_set,
    )["verdict"] == "INDETERMINATE"

    coverage = _protocol_native_delta(
        transition="coverage_lost",
        effect="not_verified",
        assurance="not_verified",
        receipts=_native_source_receipts(after_bound=False),
    )
    accepted_loss = compose(coverage)
    assert family(accepted_loss)["composition_failures"] == []
    assert family(accepted_loss)["changes"][0]["transition"] == "coverage_lost"
    assert compute_cutover_gate(
        delta, certificate, protocol_family_changes=accepted_loss,
    )["verdict"] == "INDETERMINATE"

    def applicable_without_rows(value):
        value["changes"] = []
        value["summary"] = {
            "n_subjects": 0,
            "n_comparable": 0,
            "by_transition": {token: 0 for token in pa.CHANGE_VOCABULARY},
            "by_decision_effect": {
                token: 0 for token in ("block", "review", "none", "not_verified")
            },
        }
        value["comparable"] = value["assessed"] = False

    mutations = (
        ("missing applicability", lambda value: value.pop("applicability")),
        ("malformed applicability", lambda value: value.__setitem__("applicability", [])),
        ("applicable empty rows", applicable_without_rows),
        ("not-applicable with rows", lambda value: value.__setitem__(
            "applicability", "not_applicable")),
        ("missing receipt pair", lambda value: value.pop("source_receipts")),
        ("missing before receipt", lambda value: value["source_receipts"].pop("before")),
        ("renamed custody leaf", lambda value: value["source_receipts"]["after"].__setitem__(
            "source_bound_to_comparison",
            value["source_receipts"]["after"].pop("comparison_source_bound"),
        )),
        ("malformed projection digest", lambda value: value["source_receipts"]["after"].__setitem__(
            "projection_sha256", "sha256:truncated")),
        ("incoherent custody basis", lambda value: value["source_receipts"]["after"].__setitem__(
            "comparison_source_basis", "not_source_bound")),
        ("healthy row with coherent unbound after", lambda value: value.__setitem__(
            "source_receipts", _native_source_receipts(after_bound=False))),
    )
    for label, mutate in mutations:
        candidate = deepcopy(healthy)
        mutate(candidate)
        change_set = compose(candidate)
        refused = family(change_set)
        assert refused["assurance_level"] == "not_verified", label
        assert refused["changes"][0]["transition"] == "not_comparable", label
        assert refused["changes"][0]["decision_effect"] == "not_verified", label
        assert refused["composition_failures"], label
        gate = compute_cutover_gate(
            delta, certificate, protocol_family_changes=change_set)
        assert gate["verdict"] == "INDETERMINATE", label


def test_gate_rejects_detached_mutated_or_subset_family_compositions():
    ipv4 = {
        "schema": "protocol_adjacency_delta/1",
        "summary": {"n_preserved": 1},
        "changes": [],
        "coverage_gaps": [],
    }
    delta = {
        "verdict": "CLEAN",
        "verdict_display": "NO DELTA REGRESSION OBSERVED",
        "verdict_note": "clean",
        "protocol_adjacencies": {
            "gate": "PASS",
            "summary": {
                "n_state_regressed": 0,
                "n_coverage_gaps": 0,
                "n_baseline_peers": 1,
            },
        },
    }
    certificate = {"verdict": "PASS", "verdict_note": "clean"}
    intent = {"expected_changes": []}
    trusted = pa.protocol_family_change_set(
        ipv4,
        intent,
        native_deltas=pa.compute_native_protocol_deltas({}, {}),
    )
    assert compute_cutover_gate(
        delta, certificate, protocol_family_changes=trusted,
    )["verdict"] == "PASS"

    healthy = pa.protocol_family_change_set(
        ipv4,
        intent,
        native_deltas=[_protocol_native_delta(
            transition="unchanged_healthy", effect="none")],
    )
    assert compute_cutover_gate(
        delta, certificate, protocol_family_changes=healthy,
    )["verdict"] == "INDETERMINATE"

    custody_mutation = deepcopy(healthy)
    vtp = next(
        family for family in custody_mutation["families"]
        if family["family"] == "vtp_safety"
    )
    vtp["source_receipt"]["source_receipts"]["after"][
        "comparison_source_basis"
    ] = "detached_forgery"
    custody_gate = compute_cutover_gate(
        delta, certificate, protocol_family_changes=custody_mutation,
    )
    assert custody_gate["verdict"] == "INDETERMINATE"
    assert custody_gate["protocol_family_status"] == "not_comparable"

    blocking = pa.protocol_family_change_set(
        ipv4,
        intent,
        native_deltas=[_protocol_native_delta(
            transition="regressed", effect="block")],
    )
    assert blocking["summary"]["n_blocking"] == 1
    assert compute_cutover_gate(
        delta, certificate, protocol_family_changes=blocking,
    )["verdict"] == "INDETERMINATE"
    ipv4_only = pa.protocol_family_change_set(ipv4, intent, native_deltas=[])
    assert len(ipv4_only["families"]) == 1
    assert pa.validate_protocol_family_change_set_authority(ipv4_only)["valid"] is False
    assert compute_cutover_gate(
        delta, certificate, protocol_family_changes=ipv4_only,
    )["verdict"] == "INDETERMINATE"
    dropped_family = deepcopy(blocking)
    dropped_family["families"] = deepcopy(ipv4_only["families"])
    dropped_family["summary"] = deepcopy(ipv4_only["summary"])
    assert compute_cutover_gate(
        delta, certificate, protocol_family_changes=dropped_family,
    )["verdict"] == "INDETERMINATE"

    detached = json.loads(json.dumps(healthy))
    detached_gate = compute_cutover_gate(
        delta, certificate, protocol_family_changes=detached,
    )
    assert detached_gate["verdict"] == "INDETERMINATE"
    assert "detached" in detached_gate["protocol_family_note"]


def test_multichassis_composition_uses_its_distinct_source_binding_and_is_nonvacuous():
    ipv4 = {
        "schema": "protocol_adjacency_delta/1",
        "summary": {"n_preserved": 0},
        "changes": [],
        "coverage_gaps": [],
    }
    delta = {
        "verdict": "CLEAN",
        "verdict_display": "NO DELTA REGRESSION OBSERVED",
        "verdict_note": "clean",
        "protocol_adjacencies": {
            "gate": "PASS",
            "summary": {
                "n_state_regressed": 0,
                "n_coverage_gaps": 0,
                "n_baseline_peers": 1,
            },
        },
    }
    certificate = {"verdict": "PASS", "verdict_note": "clean"}
    by_transition = {token: 0 for token in pa.CHANGE_VOCABULARY}
    by_transition["unchanged_healthy"] = 1
    native = {
        "schema": "multichassis_lag_delta/1",
        "owner_version": "1",
        "family": "multichassis_lag",
        "owns_score": False,
        "owns_verdict": False,
        "assurance_level": "local_safety_preservation",
        "source_binding": _multichassis_source_binding(),
        "comparison_failures": [],
        "changes": [{
            "family": "multichassis_lag",
            "record_type": "local_observation",
            "subject": "local:leaf-a",
            "transition": "unchanged_healthy",
            "decision_effect": "none",
            "before_state": "healthy",
            "after_state": "healthy",
            "note": "The typed local multichassis observation remains healthy.",
        }],
        "summary": {
            "n_subjects": 1,
            "n_changes": 0,
            "by_transition": by_transition,
        },
    }

    def compose(value):
        return pa.protocol_family_change_set(
            ipv4, {"expected_changes": []}, native_deltas=[value])

    def family(change_set):
        return next(
            item for item in change_set["families"]
            if item["family"] == "multichassis_lag")

    accepted = compose(native)
    assert "applicability" not in native and "source_receipts" not in native
    assert family(accepted)["composition_failures"] == []
    assert family(accepted)["changes"][0]["subject_kind"] == "local_observation"
    assert pa.validate_protocol_family_change_set_authority(accepted)["valid"] is False
    assert compute_cutover_gate(
        delta, certificate, protocol_family_changes=accepted)["verdict"] == "INDETERMINATE"

    def remove_rows(value):
        value["changes"] = []
        value["summary"] = {
            "n_subjects": 0,
            "n_changes": 0,
            "by_transition": {token: 0 for token in pa.CHANGE_VOCABULARY},
        }

    mutations = (
        ("missing owner version", lambda value: value.pop("owner_version")),
        ("missing source binding", lambda value: value.pop("source_binding")),
        ("unsupported custody", lambda value: value["source_binding"].__setitem__(
            "custody", "embedded_unverified")),
        ("truncated snapshot digest", lambda value: value["source_binding"].__setitem__(
            "after_snapshot_sha256", "sha256:truncated")),
        ("missing comparison failures", lambda value: value.pop("comparison_failures")),
        ("source-bound but rowless", remove_rows),
    )
    for label, mutate in mutations:
        candidate = deepcopy(native)
        mutate(candidate)
        change_set = compose(candidate)
        refused = family(change_set)
        assert refused["assurance_level"] == "not_verified", label
        assert refused["changes"][0]["transition"] == "not_comparable", label
        assert refused["composition_failures"], label
        assert compute_cutover_gate(
            delta, certificate, protocol_family_changes=change_set,
        )["verdict"] == "INDETERMINATE", label


def test_receipt_envelope_digest_rejects_payload_and_envelope_mutation():
    payload = {
        "admission": {"source_binding": {}, "subject_binding": {}, "owner_versions": {},
                      "support_profiles": []},
        "change_intent": {"schema": "cutover_change_intent/1"},
        "protocol_families": {"schema": "protocol_family_change_set/1"},
        "delta": {"verdict": "CLEAN"},
        "precert": {"schema": "precert/1", "verdict": "PASS"},
        "cutover_gate": {"schema": "cutover_gate/1", "verdict": "PASS"},
    }
    envelope = pa.receipt_envelope(
        admission=payload["admission"],
        change_intent=payload["change_intent"],
        protocol_families=payload["protocol_families"],
        delta=payload["delta"],
        precert=payload["precert"],
        cutover_gate=payload["cutover_gate"],
    )
    assert pa.verify_receipt_envelope(envelope, payload)
    changed_payload = deepcopy(payload)
    changed_payload["cutover_gate"]["verdict"] = "FAIL"
    assert not pa.verify_receipt_envelope(envelope, changed_payload)
    changed_envelope = deepcopy(envelope)
    changed_envelope["source_binding"] = {"after": {"sha256": "sha256:" + "f" * 64}}
    assert not pa.verify_receipt_envelope(changed_envelope, payload)


def test_operator_evidence_reuses_planning_owners_without_claiming_rehearsal():
    evidence = pa.cutover_operator_evidence({
        "failure_impact": [{
            "host": "leaf-a", "severity": "High", "stranded": 3,
            "detail": "three endpoints lose their only observed path",
        }],
        "migration_scenarios": {
            "per_group": [{
                "group": "wave-1", "recommended_scenario": "phased",
                "playbook": {"rollback": "Re-home this wave to the retained legacy uplinks."},
            }],
        },
    })
    assert evidence["schema"] == "cutover_operator_evidence/1"
    assert evidence["owns_verdict"] is False
    assert evidence["rehearsal"]["status"] == "simulation_only"
    assert evidence["rehearsal"]["assurance_level"] == "not_verified"
    assert "no source-bound operator rehearsal" in evidence["rehearsal"]["note"]
    assert evidence["rollback"]["status"] == "planned"
    assert evidence["rollback"]["n_plans_total"] == 1
    assert "not proof" in evidence["rollback"]["note"]

    absent = pa.cutover_operator_evidence({})
    assert absent["rehearsal"]["status"] == "not_verified"
    assert absent["rollback"]["status"] == "not_verified"


def test_canonical_gate_consumes_admission_additively_and_cannot_pass_bad_custody():
    delta = {
        "verdict": "CLEAN",
        "verdict_display": "NO DELTA REGRESSION OBSERVED",
        "verdict_note": "delta clean",
        "protocol_adjacencies": {
            "gate": "PASS",
            "summary": {
                "n_state_regressed": 0,
                "n_coverage_gaps": 0,
                "n_baseline_peers": 1,
            },
        },
    }
    certificate = {"verdict": "PASS", "verdict_note": "certificate clean"}
    admitted = _canonical_admission()
    assert pa.validate_comparison_admission(admitted) == {
        "present": True,
        "valid": True,
        "reason": "ok",
        "failures": [],
    }
    detached_inputs = compute_cutover_gate(
        delta, certificate, comparison_admission=admitted)
    assert detached_inputs["verdict"] == "INDETERMINATE"
    assert detached_inputs["comparison_admission_status"] == "not_comparable"
    assert "detached" in detached_inputs["comparison_admission_note"]

    malformed = deepcopy(admitted)
    malformed["status"] = "not_comparable"
    malformed["decision_eligible"] = False
    malformed["assurance_level"] = "not_verified"
    malformed["failures"] = ["after persisted-source SHA-256 binding is malformed"]
    malformed["source_binding"]["after"]["sha256"] = "sha256:truncated"
    gate = compute_cutover_gate(delta, certificate, comparison_admission=malformed)
    assert gate["verdict"] == "INDETERMINATE"
    assert gate["comparison_admission_status"] == "not_comparable"
    assert "SHA-256" in gate["comparison_admission_note"]
    assert "Do not declare the cutover good" in gate["operator_note"]

    # The historical direct-call contract remains shape-compatible when no admission is supplied.
    legacy = compute_cutover_gate(delta, certificate)
    assert legacy["verdict"] == "PASS"
    assert "comparison_admission_status" not in legacy


def test_source_bound_gate_rejects_partial_cross_pair_and_caller_mixed_inputs():
    def pair(*, engagement, campaign, first_id, device):
        before = _bound_snapshot({
            "script_version": "V3.23.0",
            "devices": {device: {"platform": "ios"}},
        })
        after = _bound_snapshot({
            "script_version": "V3.23.0",
            "devices": {device: {"platform": "ios", "phase": "after"}},
        })
        return compare_bound_pair(
            before,
            after,
            before_binding=_binding(
                first_id, campaign=campaign, engagement=engagement, snapshot=before),
            after_binding=_binding(
                first_id + 1, campaign=campaign, engagement=engagement, snapshot=after),
        )

    pair_a = pair(engagement="ENG-A", campaign=70, first_id=700, device="leaf-a")
    pair_b = pair(engagement="ENG-B", campaign=80, first_id=800, device="leaf-b")
    assert pair_a["comparison_admission"]["status"] == "admitted"
    assert pair_b["comparison_admission"]["status"] == "admitted"

    additive = {
        "comparison_schema", "comparison_admission", "change_intent",
        "protocol_families", "precert", "cutover_gate", "operator_evidence",
        "comparison_receipt",
    }
    delta_b = {key: value for key, value in pair_b.items() if key not in additive}
    authority_b = bound_comparison_decision_input_authority(pair_b)

    cross_pair = compute_cutover_gate(
        delta_b,
        pair_b["precert"],
        comparison_admission=pair_b["comparison_admission"],
        protocol_family_changes=pair_a["protocol_families"],
        decision_input_authority=authority_b,
    )
    assert cross_pair["verdict"] == "INDETERMINATE"
    assert cross_pair["comparison_admission_status"] == "not_comparable"
    assert cross_pair["protocol_family_status"] == "not_comparable"
    assert "different exact comparison pair" in cross_pair["protocol_family_note"]

    crafted_clean_delta = {
        "verdict": "CLEAN",
        "verdict_display": "NO DELTA REGRESSION OBSERVED",
        "verdict_note": "caller-crafted clean delta",
        "protocol_adjacencies": {
            "gate": "PASS",
            "summary": {
                "n_state_regressed": 0,
                "n_coverage_gaps": 0,
                "n_baseline_peers": 1,
            },
        },
    }
    caller_mixed = compute_cutover_gate(
        crafted_clean_delta,
        {"verdict": "PASS", "verdict_note": "caller-crafted PASS"},
        comparison_admission=pair_b["comparison_admission"],
        protocol_family_changes=pair_b["protocol_families"],
        decision_input_authority=authority_b,
    )
    assert caller_mixed["verdict"] == "INDETERMINATE"
    assert caller_mixed["comparison_admission_status"] == "not_comparable"
    assert "changed or belong to different comparisons" in caller_mixed[
        "comparison_admission_note"
    ]

    ipv4 = {
        "schema": "protocol_adjacency_delta/1",
        "summary": {"n_preserved": 0},
        "changes": [],
        "coverage_gaps": [],
    }
    one_family = pa.protocol_family_change_set(
        ipv4, {"expected_changes": []}, native_deltas=[])
    assert len(one_family["families"]) == 1
    one_family_gate = compute_cutover_gate(
        crafted_clean_delta,
        {"verdict": "PASS", "verdict_note": "caller-crafted PASS"},
        protocol_family_changes=one_family,
    )
    assert one_family_gate["verdict"] == "INDETERMINATE"
    assert one_family_gate["protocol_family_status"] == "not_comparable"


def test_admitted_receipt_requires_every_canonical_identity_owner_profile_and_coherence_leaf():
    delta = {
        "verdict": "CLEAN",
        "verdict_display": "NO DELTA REGRESSION OBSERVED",
        "verdict_note": "delta clean",
        "protocol_adjacencies": {
            "gate": "PASS",
            "summary": {
                "n_state_regressed": 0,
                "n_coverage_gaps": 0,
                "n_baseline_peers": 1,
            },
        },
    }
    certificate = {"verdict": "PASS", "verdict_note": "certificate clean"}
    admitted = _canonical_admission()

    mutations = (
        ("minimal", lambda value: value.clear()),
        ("missing decision eligibility", lambda value: value.pop("decision_eligible")),
        ("incoherent decision eligibility", lambda value: value.__setitem__("decision_eligible", False)),
        ("incoherent assurance", lambda value: value.__setitem__("assurance_level", "not_verified")),
        ("top-level engagement mismatch", lambda value: value.__setitem__("engagement_id", "ENG-X")),
        ("top-level campaign mismatch", lambda value: value.__setitem__("campaign_id", 99)),
        ("source campaign mismatch", lambda value: value["source_binding"]["after"].__setitem__("campaign_id", 99)),
        ("same snapshot identity", lambda value: value["source_binding"]["after"].__setitem__("snapshot_id", 1)),
        ("subject digest mismatch", lambda value: value["subject_binding"]["after"].__setitem__("subjects_sha256", "sha256:" + "0" * 64)),
        ("subject count mismatch", lambda value: value["subject_binding"]["after"].__setitem__("n_subjects", 99)),
        ("missing owner", lambda value: value["owner_versions"].pop("cutover_gate")),
        ("renamed owner", lambda value: value["owner_versions"].__setitem__("cutover_gate", "cutover_gate/2")),
        ("extra owner", lambda value: value["owner_versions"].__setitem__("page_gate", "v1")),
        ("missing support profile", lambda value: value["support_profiles"].pop()),
        ("reordered support profiles", lambda value: value["support_profiles"].reverse()),
        ("mutated support owner", lambda value: value["support_profiles"][0].__setitem__("owner_schema", "renamed/1")),
        ("admitted with failure", lambda value: value["failures"].append("caller supplied failure")),
        ("admitted with gap", lambda value: value["coverage_gaps"].append("caller supplied gap")),
    )
    for label, mutate in mutations:
        candidate = deepcopy(admitted)
        mutate(candidate)
        validation = pa.validate_comparison_admission(candidate)
        assert validation["valid"] is False, label
        gate = compute_cutover_gate(
            delta,
            certificate,
            comparison_admission=candidate,
        )
        assert gate["verdict"] == "INDETERMINATE", label
        assert gate["comparison_admission_status"] == "not_comparable", label

    # Omission alone preserves the explicitly backward-compatible legacy two-argument behavior.
    legacy = compute_cutover_gate(delta, certificate)
    assert legacy["verdict"] == "PASS"
    assert "comparison_admission_status" not in legacy


def test_canonical_coverage_lost_admission_is_well_formed_but_never_decision_eligible():
    admission = _canonical_admission(
        before={"script_version": "V3.23.0", "devices": {}},
    )

    assert admission["status"] == "coverage_lost"
    assert admission["decision_eligible"] is False
    assert admission["coverage_gaps"] == ["before snapshot has no bound device subjects"]
    assert pa.validate_comparison_admission(admission)["valid"] is True


def test_admission_validator_is_total_and_producer_rejects_incomplete_canonical_rosters():
    delta = {
        "verdict": "CLEAN",
        "verdict_note": "clean",
        "protocol_adjacencies": {
            "gate": "PASS",
            "summary": {
                "n_state_regressed": 0,
                "n_coverage_gaps": 0,
                "n_baseline_peers": 1,
            },
        },
    }
    certificate = {"verdict": "PASS", "verdict_note": "clean"}
    assert pa.validate_comparison_admission(None)["valid"] is False
    for malformed in ([], "admitted", 7, {"schema": "protocol_comparison_admission/1"}):
        validation = pa.validate_comparison_admission(malformed)
        assert validation["valid"] is False
        assert compute_cutover_gate(
            delta,
            certificate,
            comparison_admission=malformed,
        )["verdict"] == "INDETERMINATE"

    before = _bound_snapshot({"script_version": "V3.23.0", "devices": {"leaf-1": {}}})
    after = _bound_snapshot({"script_version": "V3.23.0", "devices": {"leaf-1": {}}})
    before_binding = _binding(snapshot=before)
    after_binding = _binding(2, snapshot=after)
    intent = pa.normalize_change_intent(None, binding={
        "engagement_id": "ENG-7",
        "campaign_id": 7,
        "before_snapshot_id": 1,
        "after_snapshot_id": 2,
        "before_sha256": before_binding["sha256"],
        "after_sha256": after_binding["sha256"],
    })
    canonical_owners = _owner_versions(before_binding, after_binding)
    canonical_profiles = pa.protocol_support_profiles()
    incomplete_inputs = (
        ({key: value for key, value in canonical_owners.items() if key != "cutover_gate"},
         canonical_profiles),
        (canonical_owners, canonical_profiles[:-1]),
    )
    for owners, profiles in incomplete_inputs:
        admission = pa.comparison_admission(
            before,
            after,
            before_binding=before_binding,
            after_binding=after_binding,
            schema_status={"status": "ok"},
            change_intent=intent,
            owner_versions=owners,
            support_profiles=profiles,
        )
        assert admission["status"] == "not_comparable"
        assert admission["decision_eligible"] is False


def test_direct_family_composition_is_inspectable_but_not_gate_authoritative():
    delta = {
        "verdict": "CLEAN",
        "verdict_display": "NO DELTA REGRESSION OBSERVED",
        "verdict_note": "legacy delta is clean",
        "protocol_adjacencies": {
            "gate": "PASS",
            "summary": {"n_state_regressed": 0, "n_coverage_gaps": 0, "n_baseline_peers": 1},
        },
    }
    certificate = {"verdict": "PASS", "verdict_note": "certificate clean"}
    ipv4 = {
        "schema": "protocol_adjacency_delta/1",
        "summary": {"n_preserved": 0},
        "changes": [],
        "coverage_gaps": [],
    }

    def family_set(effect, transition="unchanged_degraded"):
        by_transition = {token: 0 for token in pa.CHANGE_VOCABULARY}
        by_transition[transition] = 1
        native = {
            "schema": "multichassis_lag_delta/1",
            "family": "multichassis_lag",
            "assurance_level": (
                "not_verified" if effect == "not_verified" else "intent_reconciled_survival"
            ),
            "owns_score": False,
            "owns_verdict": False,
            "owner_version": "1",
            "source_binding": _multichassis_source_binding(),
            "comparison_failures": [],
            "summary": {
                "n_subjects": 1,
                "n_changes": 0 if transition in {
                    "unchanged_healthy", "unchanged_degraded",
                } else 1,
                "by_transition": by_transition,
            },
            "changes": [{
                "family": "multichassis_lag",
                "record_type": "reciprocal_peer_pair",
                "subject": "pair:leaf-a|leaf-b",
                "transition": transition,
                "decision_effect": effect,
                "before_state": "degraded",
                "after_state": "degraded",
                "note": "Native multichassis subject transition.",
            }],
        }
        return pa.protocol_family_change_set(
            ipv4, {"expected_changes": []}, native_deltas=[native])

    blocked_set = family_set("block")
    assert blocked_set["summary"]["n_blocking"] == 1
    blocked = compute_cutover_gate(
        delta, certificate, protocol_family_changes=blocked_set)
    assert blocked["verdict"] == "INDETERMINATE"
    assert blocked["protocol_family_status"] == "not_comparable"
    assert "detached" in blocked["protocol_family_note"]

    lost_set = family_set("not_verified", "coverage_lost")
    assert lost_set["summary"]["n_not_verified"] == 1
    lost = compute_cutover_gate(
        delta, certificate,
        protocol_family_changes=lost_set,
    )
    assert lost["verdict"] == "INDETERMINATE"
    assert lost["protocol_family_status"] == "not_comparable"

    malformed = family_set("none", "unchanged_healthy")
    target = next(
        family for family in malformed["families"] if family["family"] == "multichassis_lag"
    )
    target["changes"][0].pop("decision_effect")
    refused = compute_cutover_gate(
        delta, certificate, protocol_family_changes=malformed)
    assert refused["verdict"] == "INDETERMINATE"
    assert refused["protocol_family_status"] == "not_comparable"

    def multichassis_family(value):
        return next(
            family for family in value["families"]
            if family["family"] == "multichassis_lag"
        )

    for mutate in (
        lambda value: multichassis_family(value).pop("summary"),
        lambda value: multichassis_family(value)["support_profile"].__setitem__(
            "owner_schema", "renamed_owner/1"),
        lambda value: multichassis_family(value)["changes"][0].__setitem__("note", ""),
        lambda value: value["summary"].__setitem__("n_subject_changes", 999),
    ):
        candidate = family_set("block")
        mutate(candidate)
        gate = compute_cutover_gate(
            delta, certificate, protocol_family_changes=candidate)
        assert gate["verdict"] == "INDETERMINATE"
        assert gate["protocol_family_status"] == "not_comparable"

    trusted = pa.protocol_family_change_set(
        ipv4,
        {"expected_changes": []},
        native_deltas=pa.compute_native_protocol_deltas({}, {}),
    )
    trusted_gate = compute_cutover_gate(
        delta, certificate, protocol_family_changes=trusted)
    assert trusted_gate["verdict"] == "PASS"
    assert trusted_gate["protocol_family_status"] == "clear"

    legacy = compute_cutover_gate(delta, certificate)
    assert legacy["verdict"] == "PASS"
    assert "protocol_family_status" not in legacy
