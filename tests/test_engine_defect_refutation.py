"""Adversarial regression cases for the interrupted G13/G15 checkpoint."""
import pytest

from cisco_toolkit import analyze, failover, nrfu_export
from cisco_toolkit.stp_topology import classify_stp_root_election, stp_default_priority


def root(address, *, is_root=True, priority=4096, is_mst=False):
    return {"root_address": address, "is_root": is_root, "root_priority": priority,
            "bridge_priority": priority, "is_mst": is_mst}


@pytest.mark.parametrize("token", ["²", "9" * 5000], ids=["nondecimal", "oversized"])
def test_unparseable_numeric_tokens_abstain_without_crashing(token):
    assert stp_default_priority("30", token) is None
    assert stp_default_priority(token, 32768) is None
    assert classify_stp_root_election({"a": {token: root("aaaa")}}) == {
        "pvst_vlan": {}, "mst_instance": {}}


def test_null_root_address_cannot_certify_an_incumbent():
    row = classify_stp_root_election({"a": {"30": root(None)}})["pvst_vlan"]["30"]
    assert row["state"] == "ambiguous"
    assert row["reason"] == "malformed_root_rows"
    assert row["root"] is None


def test_malformed_row_does_not_disappear_next_to_a_claimant():
    row = classify_stp_root_election({"a": {"30": root("aaaa")},
                                     "b": {"30": None}})["pvst_vlan"]["30"]
    assert row["state"] == "ambiguous"
    assert row["reason"] == "malformed_root_rows"


def test_nrfu_uses_owner_ordinal_for_non_numeric_written_labels():
    snap = {"devices": {"a": {"platform": "ios"}},
            "move_groups": [{"group": "Pilot", "switches": ["a"]}]}
    result = nrfu_export.compute_nrfu_commands(snap)
    assert [wave["wave_id"] for wave in result["waves"]] == ["Pilot"]


def test_ungrouped_device_is_explicitly_unscheduled():
    rows = analyze.compute_migration_punchlist(
        [], {}, {}, [{"switch": "solo", "port": "Gi1/0/1", "risk": "err-disabled"}],
        [], [], {}, [], [])
    assert next(row for row in rows if row["devices"] == ["solo"])["wave"] == analyze.MOVE_GROUP_UNSCHEDULED
    remediation = analyze.compute_remediation_plan(
        stp_findings={"accidental": [{"host": "solo", "vlan": "10"}]})
    assert remediation["items"][0]["wave"] == analyze.MOVE_GROUP_UNSCHEDULED


def test_failover_keeps_mst_instance_and_pvst_vlan_separate():
    snap = {"stp_roots": {
        "pvst-root": {"1": root("aaaa")},
        "pvst-backup": {"1": root("aaaa", is_root=False, priority=8192)},
        "mst-root": {"1": root("bbbb", is_mst=True)},
        "mst-backup": {"1": root("bbbb", is_root=False, priority=8192, is_mst=True)},
    }}
    rows = failover.compute_stp_failover(snap, ["pvst-root", "mst-root"])
    assert {(row["vlan"], row["is_mst"], row["old_root"], row["new_root"])
            for row in rows} == {
        ("1", False, "pvst-root", "pvst-backup"),
        ("1", True, "mst-root", "mst-backup"),
    }
    assert all(not row["indeterminate"] for row in rows)
    readiness = failover.compute_failover_readiness(snap)
    assert readiness["n_stp_roots"] == 2
    assert readiness["n_stp_roots_with_backup"] == 2
    assert readiness["n_stp_indeterminate"] == 0


@pytest.mark.parametrize("token", ["²", "9" * 5000], ids=["nondecimal", "oversized"])
def test_failover_rejects_unparseable_survivor_priority(token):
    snap = {"stp_roots": {"a": {"10": root("aaaa")},
                          "b": {"10": {**root("aaaa", is_root=False), "bridge_priority": token}}}}
    row = failover.compute_stp_failover(snap, ["a"])[0]
    assert row["indeterminate"] is True
    assert row["new_root"] is None


def test_failover_keeps_malformed_evidence_in_the_election():
    snap = {"stp_roots": {"a": {"30": root("aaaa")}, "b": {"30": None},
                          "c": {"30": root("aaaa", is_root=False, priority=8192)}}}
    row = failover.compute_stp_failover(snap, ["a"])[0]
    assert row["indeterminate"] is True and row["new_root"] is None
    readiness = failover.compute_failover_readiness(snap)
    assert readiness["n_stp_roots_with_backup"] == 0
    assert readiness["n_stp_indeterminate"] == 1


@pytest.mark.parametrize("token", ["²", "9" * 5000], ids=["nondecimal", "oversized"])
@pytest.mark.parametrize("surface", ["matrix", "validation", "failover", "nrfu"])
def test_every_election_consumer_tolerates_unusable_vlan_tokens(token, surface):
    stp = {"a": {token: root("aaaa")}}
    if surface == "matrix":
        assert analyze.compute_vlan_cutover_matrix({}, stp) == []
    elif surface == "validation":
        result = analyze.compute_validation_plan({}, stp_roots=stp)
        assert not any("spanning-tree vlan" in row["command"] for row in result["items"])
    elif surface == "failover":
        assert failover.compute_stp_failover({"stp_roots": stp}, ["a"]) == []
    else:
        result = nrfu_export.compute_nrfu_commands({"stp_roots": stp, "devices": {"a": {"platform": "ios"}}})
        assert not any("spanning-tree vlan" in case["command"] for wave in result["waves"]
                       for device in wave["devices"] for case in device["cases"])


def test_failover_canonicalizes_numeric_tokens_before_joining_bridges():
    snap = {"stp_roots": {"a": {"030": root("aaaa")},
                          "b": {"30": root("aaaa", is_root=False, priority=8192)}}}
    row = failover.compute_stp_failover(snap, ["a"])[0]
    assert row["vlan"] == "30" and row["new_root"] == "b"
    assert row["indeterminate"] is False
