"""Release-1 source/custody/intent contracts around the canonical cutover decision."""

from copy import deepcopy

from cisco_toolkit import protocol_assurance as pa
from cisco_toolkit.html import compute_cutover_gate


def _binding(snapshot_id=1, *, campaign=7, engagement="ENG-7", digest="1"):
    return {
        "source": "persisted snapshots.snapshot_json blob",
        "sha256": "sha256:" + digest * 64,
        "bytes": 100,
        "snapshot_id": snapshot_id,
        "campaign_id": campaign,
        "engagement_id": engagement,
        "label": f"s{snapshot_id}",
        "script_version": "V3.23.0",
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
    before = {"script_version": "V3.23.0", "devices": {"Leaf-1": {}, "leaf-1": {}}}
    after = {"script_version": "V3.23.0", "devices": {"Leaf-1": {}}}
    intent = pa.normalize_change_intent(None, binding={
        "engagement_id": "ENG-7", "campaign_id": 7,
        "before_snapshot_id": 1, "after_snapshot_id": 2,
        "before_sha256": _binding()["sha256"],
        "after_sha256": _binding(2, digest="2")["sha256"],
    })
    admission = pa.comparison_admission(
        before,
        after,
        before_binding=_binding(),
        after_binding=_binding(2, digest="2"),
        schema_status={"status": "ok", "message": "", "override": False},
        change_intent=intent,
        owner_versions={"delta": "v1"},
        support_profiles=pa.protocol_support_profiles(),
    )
    assert admission["status"] == "not_comparable"
    assert admission["decision_eligible"] is False
    assert any("collision" in item for item in admission["failures"])


def test_admission_fails_closed_for_renamed_truncated_or_mismatched_custody_leaves():
    before = {"script_version": "V3.23.0", "devices": {"leaf-1": {}}}
    after = {"script_version": "V3.23.0", "devices": {"leaf-1": {}}}
    exact_before = _binding()
    exact_after = _binding(2, digest="2")

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
            owner_versions={"delta": "v1"},
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
        counts = {token: 0 for token in pa.CHANGE_VOCABULARY}
        counts[transition] = 1
        return {
            "schema": "vtp_safety_delta/1",
            "family": "vtp_safety",
            "assurance_level": (
                "not_verified" if effect == "not_verified" else "local_safety_preservation"
            ),
            "owns_score": False,
            "owns_verdict": False,
            "summary": {"by_transition": counts},
            "changes": [{
                "family": "vtp_safety",
                "subject": "dist-1",
                "transition": transition,
                "decision_effect": effect,
                "before_state": {"revision": 4},
                "after_state": {"revision": 5},
                "note": "Producer-owned VTP transition.",
            }],
        }

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
    admitted = {
        "schema": "protocol_comparison_admission/1",
        "status": "admitted",
        "failures": [],
        "coverage_gaps": [],
    }
    assert compute_cutover_gate(
        delta, certificate, comparison_admission=admitted)["verdict"] == "PASS"

    malformed = deepcopy(admitted)
    malformed["status"] = "not_comparable"
    malformed["failures"] = ["after persisted-source SHA-256 binding is malformed"]
    gate = compute_cutover_gate(delta, certificate, comparison_admission=malformed)
    assert gate["verdict"] == "INDETERMINATE"
    assert gate["comparison_admission_status"] == "not_comparable"
    assert "SHA-256" in gate["comparison_admission_note"]
    assert "Do not declare the cutover good" in gate["operator_note"]

    # The historical direct-call contract remains shape-compatible when no admission is supplied.
    legacy = compute_cutover_gate(delta, certificate)
    assert legacy["verdict"] == "PASS"
    assert "comparison_admission_status" not in legacy


def test_canonical_gate_consumes_complete_family_effects_without_changing_legacy_shape():
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
            "summary": {"by_transition": by_transition},
            "changes": [{
                "family": "multichassis_lag",
                "subject": "pair:leaf-a|leaf-b",
                "transition": transition,
                "decision_effect": effect,
                "before_state": {"health": "degraded"},
                "after_state": {"health": "degraded"},
                "note": "Native multichassis subject transition.",
            }],
        }
        ipv4 = {
            "schema": "protocol_adjacency_delta/1",
            "summary": {"n_preserved": 0},
            "changes": [],
            "coverage_gaps": [],
        }
        return pa.protocol_family_change_set(
            ipv4, {"expected_changes": []}, native_deltas=[native])

    blocked = compute_cutover_gate(
        delta, certificate, protocol_family_changes=family_set("block"))
    assert blocked["verdict"] == "REGRESSED"
    assert blocked["protocol_family_blocking"] == 1
    assert "native family owner" in blocked["operator_note"]

    lost = compute_cutover_gate(
        delta, certificate,
        protocol_family_changes=family_set("not_verified", "coverage_lost"),
    )
    assert lost["verdict"] == "INDETERMINATE"
    assert lost["protocol_family_status"] == "coverage_lost"

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

    legacy = compute_cutover_gate(delta, certificate)
    assert legacy["verdict"] == "PASS"
    assert "protocol_family_status" not in legacy
