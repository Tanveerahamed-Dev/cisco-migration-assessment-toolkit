"""Exact, source-bound cross-member reconciliation for configured FHRP groups."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from cisco_toolkit.capture_integrity import compute_capture_integrity_from_paths
from cisco_toolkit.fhrp_intent import (
    _coverage_receipt_hashes,
    compute_fhrp_configured_group_baseline,
    embedded_fhrp_configured_group_baseline,
    validate_fhrp_configured_group_baseline,
)


_PROTOCOL_FIXTURES = {
    "HSRP": {
        "config": "standby {group} ip {vip}",
        "command": "show standby brief",
        "header": "Interface   Grp  Pri P State    Active          Standby         Virtual IP\n",
        "row": "{interface}  {group}  110 P {state}  10.0.10.2  local  {vip}\n",
    },
    "VRRP": {
        "config": "vrrp {group} ip {vip}",
        "command": "show vrrp brief",
        "header": "Interface  Grp Pri Time Own Pre State  Master addr  Group addr\n",
        "row": "{interface}  {group}  110 3570 Y Y {state}  10.0.10.2  {vip}\n",
    },
    "GLBP": {
        "config": "glbp {group} ip {vip}",
        "command": "show glbp brief",
        "header": "Interface Grp Fwd Pri State  Address  Active router Standby router\n",
        "row": "{interface}  {group}  -  110 {state}  {vip}  local  10.0.10.2\n",
    },
}


def _build(tmp_path: Path, members: list[dict], *, reverse_hosts: bool = False) -> dict:
    paths: dict[str, dict[str, str]] = {}
    ordered = list(reversed(members)) if reverse_hosts else members
    for index, member in enumerate(ordered):
        host = member["host"]
        protocol = member.get("protocol", "HSRP")
        interface = member.get("interface", "Vlan10")
        group = str(member.get("group", "10"))
        vip = member.get("vip", "10.0.10.1")
        state = member["state"]
        fixture = _PROTOCOL_FIXTURES[protocol]
        config = (
            f"hostname {host}\n"
            f"interface {interface}\n"
            f" {fixture['config'].format(group=group, vip=vip)}\n"
            "end\n"
        )
        runtime = fixture["header"] + fixture["row"].format(
            interface=interface.replace("Vlan", "Vl"),
            group=group,
            state=state,
            vip=vip,
        )
        host_dir = tmp_path / f"member_{index}"
        host_dir.mkdir(parents=True)
        config_path = host_dir / "config.txt"
        runtime_path = host_dir / "runtime.txt"
        config_path.write_text(config, encoding="utf-8")
        runtime_path.write_text(runtime, encoding="utf-8")
        paths[host] = {
            "show running-config": str(config_path),
            fixture["command"]: str(runtime_path),
        }
    integrity = compute_capture_integrity_from_paths(paths)
    return compute_fhrp_configured_group_baseline(
        paths,
        integrity,
        {member["host"]: {"platform": "ios"} for member in members},
    )


def _rows(baseline: dict, protocol: str = "HSRP") -> list[dict]:
    return [row for row in baseline["rows"] if row["protocol"] == protocol]


def _cells(baseline: dict, protocol: str = "HSRP") -> list[dict]:
    return [cell for cell in baseline["coverage"] if cell["protocol"] == protocol]


def _reseal(value: dict) -> None:
    payload = copy.deepcopy(value)
    payload["summary"].pop("baseline_sha256", None)
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    value["summary"]["baseline_sha256"] = hashlib.sha256(encoded).hexdigest()


def test_multiple_sequential_hsrp_leaders_review_every_exact_candidate(tmp_path):
    baseline = _build(tmp_path, [
        {"host": "edge-a", "state": "Active"},
        {"host": "edge-b", "state": "Active"},
    ])

    assert baseline["verdict"] == "INDETERMINATE"
    assert baseline["assessed"] is False
    assert baseline["summary"]["n_review"] == 2
    assert baseline["summary"]["n_assessed"] == 0
    for row in _rows(baseline):
        assert row["status"] == "review"
        assert row["source_key"].endswith(" + show standby brief")
        assert row["projection_custody"] == "current_run_source_bound"
        assert [finding["code"] for finding in row["findings"]] == [
            "election_multiple_leaders_observed"
        ]
        issue = row["findings"][0]["issue"]
        assert "scope default/ipv4, HSRP interface Vlan10 group 10" in issue
        assert "configured/runtime VIP 10.0.10.1" in issue
        assert "observed role composition ACTIVE=2 across 2 distinct hosts" in issue
        assert "multiple ACTIVE leaders were observed in sequential captures" in issue
        assert "Capture timing is not simultaneous evidence" in issue
        assert "verify the intended candidates simultaneously" in issue
        assert "explicitly disposition the election" in issue
        assert "split brain" not in issue.casefold()
        assert row["acceptance"].startswith("PRE-CUTOVER REVIEW — BLOCKER:")
        assert "Matching the conflicting or unresolved sequential roles is NOT ACCEPTANCE" in (
            row["acceptance"]
        )
    assert all(cell["status"] == "review" for cell in _cells(baseline))
    assert all(cell["finding_codes"] == ["election_multiple_leaders_observed"]
               for cell in _cells(baseline))
    assert validate_fhrp_configured_group_baseline(
        baseline, require_current_run=True,
    )["valid"] is True


def test_zero_sequential_hsrp_leaders_is_review_not_an_expected_peer_claim(tmp_path):
    baseline = _build(tmp_path, [
        {"host": "edge-a", "state": "Standby"},
        {"host": "edge-b", "state": "Standby"},
    ])

    for row in _rows(baseline):
        assert row["status"] == "review"
        assert row["findings"] == [{
            "kind": "review",
            "code": "election_no_leader_observed",
            "issue": row["findings"][0]["issue"],
        }]
        issue = row["findings"][0]["issue"]
        assert "observed role composition STANDBY=2 across 2 distinct hosts" in issue
        assert "no ACTIVE leader was observed in sequential captures" in issue
        assert "expected" not in issue.casefold()
        assert "peer" not in issue.casefold()
        assert "simultaneous split" not in issue.casefold()


def test_one_leader_with_accepted_backup_stays_local_assessed_only(tmp_path):
    baseline = _build(tmp_path, [
        {"host": "edge-a", "state": "Active"},
        {"host": "edge-b", "state": "Standby"},
    ])

    assert baseline["verdict"] == "CLEAR"
    assert [row["status"] for row in _rows(baseline)] == ["assessed", "assessed"]
    assert all(not row["findings"] for row in _rows(baseline))
    assert all("no expected member count" in row["acceptance"] for row in _rows(baseline))
    assert all("no expected member count, simultaneous election" in row["acceptance"]
               for row in _rows(baseline))


def test_single_backup_never_invents_a_missing_member_or_leader(tmp_path):
    baseline = _build(tmp_path, [{"host": "edge-a", "state": "Standby"}])

    row = _rows(baseline)[0]
    assert baseline["verdict"] == "CLEAR"
    assert row["status"] == "assessed"
    assert row["findings"] == []
    assert "missing" not in row["acceptance"].casefold()
    assert "leader" not in row["acceptance"].casefold()


@pytest.mark.parametrize(
    ("protocol", "leader", "backup"),
    [("VRRP", "Master", "Backup"), ("GLBP", "Active", "Standby")],
)
def test_subtype_leader_vocabularies_are_exact(tmp_path, protocol, leader, backup):
    multiple = _build(tmp_path / "multiple", [
        {"host": "edge-a", "protocol": protocol, "state": leader},
        {"host": "edge-b", "protocol": protocol, "state": leader},
    ])
    expected_leader = "MASTER" if protocol == "VRRP" else "ACTIVE"
    issue = _rows(multiple, protocol)[0]["findings"][0]["issue"]
    assert f"multiple {expected_leader} leaders" in issue

    leaderless = _build(tmp_path / "leaderless", [
        {"host": "edge-a", "protocol": protocol, "state": backup},
        {"host": "edge-b", "protocol": protocol, "state": backup},
    ])
    issue = _rows(leaderless, protocol)[0]["findings"][0]["issue"]
    assert f"no {expected_leader} leader" in issue

    accepted = _build(tmp_path / "accepted", [
        {"host": "edge-a", "protocol": protocol, "state": leader},
        {"host": "edge-b", "protocol": protocol, "state": backup},
    ])
    assert [row["status"] for row in _rows(accepted, protocol)] == [
        "assessed", "assessed",
    ]


@pytest.mark.parametrize(
    "changed",
    [
        {"vip": "10.0.10.254"},
        {"group": "20"},
        {"interface": "Vlan20"},
        {"protocol": "VRRP", "state": "Master"},
    ],
)
def test_nonidentical_candidate_dimensions_never_cross_join(tmp_path, changed):
    baseline = _build(tmp_path, [
        {"host": "edge-a", "state": "Active"},
        {"host": "edge-b", "state": "Active", **changed},
    ])

    assert baseline["verdict"] == "CLEAR"
    assert all(row["status"] == "assessed" for row in baseline["rows"])
    assert all(not row["findings"] for row in baseline["rows"])


def test_candidate_and_finding_order_is_deterministic(tmp_path):
    members = [
        {"host": "edge-z", "state": "Active"},
        {"host": "edge-a", "state": "Active"},
    ]
    forward = _build(tmp_path / "forward", members)
    reverse = _build(tmp_path / "reverse", members, reverse_hosts=True)

    assert dict(forward) == dict(reverse)
    assert [row["switch"] for row in _rows(forward)] == ["edge-a", "edge-z"]


def test_valid_two_host_election_uses_independent_row_findings(tmp_path):
    baseline = _build(tmp_path, [
        {"host": "edge-a", "state": "Active"},
        {"host": "edge-b", "state": "Active"},
    ])
    rows = _rows(baseline)

    assert validate_fhrp_configured_group_baseline(baseline)["valid"] is True
    assert "ACTIVE=2 across 2 distinct hosts" in rows[0]["findings"][0]["issue"]
    assert rows[0]["findings"][0] == rows[1]["findings"][0]
    assert rows[0]["findings"][0] is not rows[1]["findings"][0]


def test_one_host_case_variant_interface_rows_cannot_inflate_election(tmp_path):
    control = _build(tmp_path / "control", [
        {"host": "edge-a", "state": "Active"},
        {"host": "edge-b", "state": "Active"},
    ])
    forged = copy.deepcopy(dict(_build(
        tmp_path / "forged", [{"host": "edge-a", "state": "Active"}],
    )))
    duplicate = copy.deepcopy(forged["rows"][0])
    duplicate["interface"] = duplicate["interface"].casefold()
    duplicate["group_key"] = (
        f"{duplicate['protocol']}:{duplicate['interface']}:{duplicate['group']}"
    )
    forged["rows"].append(duplicate)

    finding = copy.deepcopy(control["rows"][0]["findings"][0])
    acceptance = control["rows"][0]["acceptance"]
    for row in forged["rows"]:
        row["status"] = "review"
        row["findings"] = [copy.deepcopy(finding)]
        row["acceptance"] = acceptance

    cell = _cells(forged)[0]
    cell.update({
        "status": "review",
        "config_candidate_count": 2,
        "configured_group_count": 2,
        "runtime_candidate_count": 2,
        "runtime_parsed_count": 2,
        "finding_codes": ["election_multiple_leaders_observed"],
    })
    (cell["config_sha256"], cell["runtime_sha256"],
     cell["projection_sha256"]) = _coverage_receipt_hashes(cell, forged["rows"])
    forged["summary"].update({
        "n_configured_groups": 2,
        "n_active_groups": 2,
        "n_runtime_groups": 2,
        "n_assessed": 0,
        "n_review": 2,
    })
    forged["summary"]["by_status"]["assessed"] = 0
    forged["summary"]["by_status"]["review"] = 2
    forged["summary"]["by_coverage_status"]["assessed"] = 0
    forged["summary"]["by_coverage_status"]["review"] = 1
    forged["verdict"] = "INDETERMINATE"
    forged["assessed"] = False
    _reseal(forged)

    view = validate_fhrp_configured_group_baseline(forged)
    assert view["valid"] is False
    assert view["reason"] == "baseline_duplicate_or_key_invalid"


def test_switch_case_aliases_cannot_establish_two_coverage_hosts(tmp_path):
    baseline = _build(tmp_path, [
        {"host": "edge-a", "state": "Active", "group": "10"},
        {"host": "edge-b", "state": "Active", "group": "20"},
    ])
    assert validate_fhrp_configured_group_baseline(baseline)["valid"] is True
    forged = copy.deepcopy(dict(baseline))
    for row in forged["rows"]:
        if row["switch"] == "edge-b":
            row["switch"] = "EDGE-A"
    for cell in forged["coverage"]:
        if cell["switch"] == "edge-b":
            cell["switch"] = "EDGE-A"
    _reseal(forged)

    view = validate_fhrp_configured_group_baseline(forged)
    assert view["valid"] is False
    assert view["reason"] == "baseline_coverage_identity_invalid"


def test_resealed_removal_of_required_election_review_is_rejected(tmp_path):
    baseline = _build(tmp_path, [
        {"host": "edge-a", "state": "Active"},
        {"host": "edge-b", "state": "Active"},
    ])
    forged = copy.deepcopy(dict(baseline))
    for row in _rows(forged):
        row["status"] = "assessed"
        row["findings"] = []
        row["acceptance"] = (
            f"Require configured-active {row['protocol']} {row['interface']} group "
            f"{row['group']} VIP {row['configured_vip']} to preserve local state "
            f"{row['runtime_state']}. This is a local group-state check only; no expected "
            "member count, simultaneous election, failover, or convergence claim is made."
        )
    for cell in _cells(forged):
        # A re-sealer cannot hide the cross-row invariant behind weakened parser
        # labels and fresh bounded-receipt hashes.
        cell["config_parser_status"] = "review"
        cell["runtime_parser_status"] = "review"
        cell["status"] = "assessed"
        cell["finding_codes"] = []
        cell_rows = [
            row for row in forged["rows"]
            if (row["switch"], row["protocol"])
            == (cell["switch"], cell["protocol"])
        ]
        (cell["config_sha256"], cell["runtime_sha256"],
         cell["projection_sha256"]) = _coverage_receipt_hashes(cell, cell_rows)
    forged["summary"]["n_review"] = 0
    forged["summary"]["n_assessed"] = 2
    forged["summary"]["by_status"]["review"] = 0
    forged["summary"]["by_status"]["assessed"] = 2
    forged["summary"]["by_coverage_status"]["review"] = 0
    forged["summary"]["by_coverage_status"]["assessed"] = 2
    forged["verdict"] = "CLEAR"
    forged["assessed"] = True
    _reseal(forged)

    view = validate_fhrp_configured_group_baseline(forged)
    assert view["valid"] is False
    assert view["reason"] == "baseline_election_reconciliation_mismatch"


def test_embedded_projection_retains_the_same_semantic_invariant_without_authority(tmp_path):
    baseline = _build(tmp_path, [
        {"host": "edge-a", "state": "Active"},
        {"host": "edge-b", "state": "Active"},
    ])

    embedded = embedded_fhrp_configured_group_baseline(baseline)
    view = validate_fhrp_configured_group_baseline(embedded)
    current = validate_fhrp_configured_group_baseline(
        embedded, require_current_run=True,
    )

    assert view["valid"] is True
    assert view["source_bound"] is False
    assert all(row["status"] == "review" for row in view["rows"])
    assert all(row["projection_custody"] == "embedded_unverified"
               for row in view["rows"])
    assert current["valid"] is False
    assert current["reason"] == "baseline_not_current_run_source_bound"


def test_deeply_nested_hostile_receipt_fails_closed_without_echoing_leaves(tmp_path):
    baseline = _build(tmp_path, [{"host": "edge-a", "state": "Standby"}])
    hostile = copy.deepcopy(dict(baseline))
    nested: object = "hostile-secret-leaf"
    for _ in range(2_500):
        nested = [nested]
    hostile["rows"][0]["findings"] = nested

    view = validate_fhrp_configured_group_baseline(hostile)

    assert view["valid"] is False
    assert view["reason"] == "baseline_digest_mismatch"
    assert view["rows"] == []
    assert view["index"] == {}
    assert view["baseline"] == {}
    assert "hostile-secret-leaf" not in json.dumps(view, sort_keys=True)
