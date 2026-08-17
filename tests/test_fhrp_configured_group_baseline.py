"""Adversarial contract tests for bounded configured FHRP group truth.

The owner deliberately proves only direct literal local IPv4 groups in the
default/global scope.  These tests protect the useful part of that narrow
claim: every configured and runtime group survives as its own identity, while
capture defects, parser gaps, and custody loss can never become a green gate.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from cisco_toolkit.capture_integrity import compute_capture_integrity_from_paths
from cisco_toolkit.fhrp_intent import (
    FHRP_CONFIGURED_GROUP_SCHEMA,
    _CurrentRunFhrpConfiguredGroupBaseline,
    compute_fhrp_configured_group_baseline,
    embedded_fhrp_configured_group_baseline,
    validate_fhrp_configured_group_baseline,
)


IOS_CONFIG = """\
hostname edge1
interface Vlan10
 ip address 10.0.10.2 255.255.255.0
 standby 10 ip 10.0.10.1
end
"""

HSRP_HEADER = (
    "Interface   Grp  Pri P State    Active          Standby         Virtual IP\n"
)
IOS_HSRP = HSRP_HEADER + (
    "Vl10        10   110 P Active   local           10.0.10.3      10.0.10.1\n"
)

STATUS_ORDER = (
    "degraded", "review", "not_verified", "assessed",
    "administratively_disabled",
)
COVERAGE_STATUS_ORDER = (
    "degraded", "review", "not_verified", "assessed", "not_applicable",
)


def _run(
    tmp_path: Path,
    *,
    config: str = IOS_CONFIG,
    runtime: str = IOS_HSRP,
    platform: str = "ios",
    config_command: str = "show running-config",
    runtime_command: str = "show standby brief",
    extra_captures: dict[str, str] | None = None,
    include_config: bool = True,
    host: str = "edge1",
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    captures = dict(extra_captures or {})
    if include_config:
        captures[config_command] = config
    captures[runtime_command] = runtime
    mapping: dict[str, str] = {}
    for index, (command, body) in enumerate(captures.items(), 1):
        path = tmp_path / f"capture_{index}.txt"
        path.write_text(body, encoding="utf-8")
        mapping[command] = str(path)
    paths = {host: mapping}
    integrity = compute_capture_integrity_from_paths(paths)
    baseline = compute_fhrp_configured_group_baseline(
        paths, integrity, {host: {"platform": platform}},
    )
    return baseline, paths, integrity


def _row(
    baseline: dict,
    *,
    protocol: str = "HSRP",
    interface: str = "Vlan10",
    group: str = "10",
) -> dict:
    return next(
        row for row in baseline["rows"]
        if (row["protocol"], row["interface"], row["group"])
        == (protocol, interface, group)
    )


def _coverage(baseline: dict, protocol: str = "HSRP") -> dict:
    return next(cell for cell in baseline["coverage"] if cell["protocol"] == protocol)


def _reseal(value: dict) -> None:
    """Reproduce the canonical public digest to exercise semantic validation."""
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


def test_ios_hsrp_group_is_source_bound_clear_and_has_exact_censuses(tmp_path):
    baseline, _paths, _integrity = _run(tmp_path)

    assert isinstance(baseline, _CurrentRunFhrpConfiguredGroupBaseline)
    assert set(baseline) == {
        "schema", "scope", "verdict", "assessed", "projection_custody",
        "rows", "coverage", "findings", "summary", "limitations",
    }
    assert baseline["schema"] == FHRP_CONFIGURED_GROUP_SCHEMA
    assert baseline["scope"] == {
        "routing_instance": "default",
        "afi": "ipv4",
        "group_kind": "direct_literal_local",
    }
    assert baseline["verdict"] == "CLEAR" and baseline["assessed"] is True
    assert len(baseline["coverage"]) == 3
    assert [cell["protocol"] for cell in baseline["coverage"]] == [
        "HSRP", "VRRP", "GLBP",
    ]
    assert baseline["summary"]["n_subject_cells"] == 1
    assert list(baseline["summary"]["by_status"]) == list(STATUS_ORDER)
    assert list(baseline["summary"]["by_coverage_status"]) == list(
        COVERAGE_STATUS_ORDER,
    )
    assert baseline["summary"]["by_status"] == {
        "degraded": 0,
        "review": 0,
        "not_verified": 0,
        "assessed": 1,
        "administratively_disabled": 0,
    }
    assert baseline["summary"]["by_coverage_status"] == {
        "degraded": 0,
        "review": 0,
        "not_verified": 0,
        "assessed": 1,
        "not_applicable": 2,
    }

    row = _row(baseline)
    assert row["group_key"] == "HSRP:Vlan10:10"
    assert row["scope"] == "default/ipv4"
    assert row["configured"] is row["runtime_observed"] is True
    assert row["configured_vip"] == row["runtime_vip"] == "10.0.10.1"
    assert row["activation"] == "active"
    assert row["runtime_state_raw"] == "Active"
    assert row["runtime_state"] == "ACTIVE"
    assert row["status"] == "assessed"
    assert row["command"] == "show standby brief"
    assert row["projection_custody"] == "current_run_source_bound"
    assert "no expected member count" in row["acceptance"]

    coverage = _coverage(baseline)
    assert coverage["subject"] is True and coverage["status"] == "assessed"
    assert coverage["config_command"] == "show running-config"
    assert coverage["runtime_command"] == "show standby brief"
    assert coverage["config_capture_status"] == "ok"
    assert coverage["runtime_capture_status"] == "ok"
    assert coverage["config_parser_status"] == "complete"
    assert coverage["runtime_parser_status"] == "complete"
    assert coverage["config_candidate_count"] == 1
    assert coverage["configured_group_count"] == 1
    assert coverage["runtime_candidate_count"] == 1
    assert coverage["runtime_parsed_count"] == 1
    for field in ("config_sha256", "runtime_sha256", "projection_sha256"):
        assert len(coverage[field]) == 64
        int(coverage[field], 16)

    view = validate_fhrp_configured_group_baseline(
        baseline, require_current_run=True,
    )
    assert view["valid"] is True and view["source_bound"] is True
    assert set(view["index"]) == {("edge1", "HSRP", "Vlan10", "10")}
    json.dumps(baseline, allow_nan=False)
    assert str(tmp_path) not in json.dumps(baseline)


def test_same_interface_multi_group_runtime_is_lossless_and_bad_role_blocks(tmp_path):
    config = """\
hostname edge1
interface Vlan10
 standby 10 ip 10.0.10.1
 standby 20 ip 10.0.10.254
end
"""
    runtime = HSRP_HEADER + (
        "Vl10        10   110 P Active   local           10.0.10.3      10.0.10.1\n"
        "Vl10        20   100 P Init     unknown         unknown        10.0.10.254\n"
    )
    baseline, *_ = _run(tmp_path, config=config, runtime=runtime)

    assert baseline["verdict"] == "BLOCKED" and baseline["assessed"] is True
    assert [
        (row["interface"], row["group"], row["status"])
        for row in baseline["rows"]
    ] == [
        ("Vlan10", "10", "assessed"),
        ("Vlan10", "20", "degraded"),
    ]
    bad = _row(baseline, group="20")
    assert bad["runtime_state"] == "INIT"
    assert bad["findings"][0]["code"] == "runtime_state_degraded"
    assert bad["acceptance"].startswith("PRE-CUTOVER DEGRADED — BLOCKER:")
    assert "matching this degraded state is NOT ACCEPTANCE" in bad["acceptance"]
    assert baseline["summary"]["n_configured_groups"] == 2
    assert baseline["summary"]["n_runtime_groups"] == 2


@pytest.mark.parametrize(
    ("protocol", "config_line", "runtime_command", "runtime", "state"),
    [
        (
            "VRRP",
            "vrrp 10 ip 10.0.10.1",
            "show vrrp brief",
            (
                "Interface  Grp Pri Time Own Pre State  Master addr  Group addr\n"
                "Vl10       10  110 3570 Y   Y   Master local        10.0.10.1\n"
            ),
            "MASTER",
        ),
        (
            "GLBP",
            "glbp 10 ip 10.0.10.1",
            "show glbp brief",
            (
                "Interface Grp Fwd Pri State  Address     Active router Standby router\n"
                "Vl10      10  -   110 Active 10.0.10.1  local         10.0.10.3\n"
                "Vl10      10  1   -   Active 0007.b400.0a01 local      -\n"
            ),
            "ACTIVE",
        ),
    ],
)
def test_ios_vrrp_and_glbp_flat_groups_are_distinct_supported_subtypes(
    tmp_path,
    protocol,
    config_line,
    runtime_command,
    runtime,
    state,
):
    config = (
        "hostname edge1\n"
        "interface Vlan10\n"
        f" {config_line}\n"
        "end\n"
    )
    baseline, *_ = _run(
        tmp_path,
        config=config,
        runtime=runtime,
        runtime_command=runtime_command,
    )

    row = _row(baseline, protocol=protocol)
    assert baseline["verdict"] == "CLEAR"
    assert row["status"] == "assessed"
    assert row["runtime_state"] == state
    assert row["configured_vip"] == row["runtime_vip"] == "10.0.10.1"
    assert _coverage(baseline, protocol)["runtime_parsed_count"] == 1


def test_nxos_nested_hsrp_and_hsrp_command_preference_are_supported(tmp_path):
    config = """\
!Command: show running-config interface
interface Vlan10
  no shutdown
  hsrp 10
    ip 10.0.10.1
    priority 110
    preempt
"""
    runtime = HSRP_HEADER + (
        "Vlan10      10   110 P Standby  10.0.10.3      local           10.0.10.1\n"
    )
    baseline, *_ = _run(
        tmp_path,
        config=config,
        runtime=runtime,
        platform="nxos",
        config_command="show running-config interface",
        runtime_command="show hsrp brief",
    )

    assert baseline["verdict"] == "CLEAR"
    row = _row(baseline)
    assert row["runtime_state"] == "STANDBY"
    assert row["status"] == "assessed"
    cell = _coverage(baseline)
    assert cell["config_command"] == "show running-config interface"
    assert cell["runtime_command"] == "show hsrp brief"


def test_explicit_ios_platform_is_not_reinterpreted_by_hsrp_command_alias(tmp_path):
    baseline, *_ = _run(
        tmp_path,
        platform="ios",
        runtime_command="show hsrp brief",
    )

    assert baseline["verdict"] == "CLEAR"
    assert _row(baseline)["status"] == "assessed"
    assert _coverage(baseline)["runtime_command"] == "show hsrp brief"


def test_integrity_ok_ios_scoped_config_wins_over_incomplete_full_config(tmp_path):
    incomplete_full = "hostname edge1\ninterface Vlan999\n description truncated\n"
    baseline, *_ = _run(
        tmp_path,
        config=IOS_CONFIG,
        config_command="show running-config | section ^interface",
        extra_captures={"show running-config": incomplete_full},
    )

    assert baseline["verdict"] == "CLEAR"
    assert _coverage(baseline)["config_command"] == (
        "show running-config | section ^interface"
    )
    assert _coverage(baseline)["config_capture_status"] == "ok"


def test_configured_active_missing_from_complete_summary_is_degraded_not_observed(tmp_path):
    baseline, *_ = _run(tmp_path, runtime=HSRP_HEADER)

    row = _row(baseline)
    assert baseline["verdict"] == "BLOCKED"
    assert row["runtime_observed"] is False
    assert row["runtime_state"] == "NOT_OBSERVED"
    assert row["status"] == "degraded"
    assert {finding["code"] for finding in row["findings"]} == {
        "configured_group_not_observed",
    }
    assert "was not observed" in row["acceptance"]
    assert "is down" not in row["acceptance"].casefold()


def test_subtype_specific_bad_roles_degrade_without_peer_or_election_inference(tmp_path):
    config = """\
hostname edge1
interface Vlan10
 vrrp 10 ip 10.0.10.1
end
"""
    runtime = (
        "Interface  Grp Pri Time Own Pre State Master addr Group addr\n"
        "Vl10       10  110 3570 Y   Y   Fault unknown     10.0.10.1\n"
    )
    baseline, *_ = _run(
        tmp_path,
        config=config,
        runtime=runtime,
        runtime_command="show vrrp brief",
    )

    row = _row(baseline, protocol="VRRP")
    assert row["runtime_state"] == "FAULT" and row["status"] == "degraded"
    assert "peer" not in row["findings"][0]["issue"].casefold()
    assert "election" not in row["findings"][0]["issue"].casefold()


def test_runtime_only_group_is_review_not_invented_configuration(tmp_path):
    config = "hostname edge1\ninterface Vlan10\n description no fhrp\nend\n"
    baseline, *_ = _run(tmp_path, config=config)

    row = _row(baseline)
    assert baseline["verdict"] == "INDETERMINATE"
    assert row["configured"] is False and row["activation"] == "ambiguous"
    assert row["runtime_observed"] is True
    assert row["status"] == "review"
    assert {finding["code"] for finding in row["findings"]} == {
        "runtime_group_not_in_bounded_config",
    }
    assert row["acceptance"].startswith("PRE-CUTOVER REVIEW — BLOCKER:")


def test_vip_mismatch_is_review_not_assessed(tmp_path):
    runtime = HSRP_HEADER + (
        "Vl10        10   110 P Active   local           10.0.10.3      10.0.10.254\n"
    )
    baseline, *_ = _run(tmp_path, runtime=runtime)

    row = _row(baseline)
    assert baseline["verdict"] == "INDETERMINATE"
    assert row["status"] == "review"
    assert row["configured_vip"] == "10.0.10.1"
    assert row["runtime_vip"] == "10.0.10.254"
    assert {finding["code"] for finding in row["findings"]} == {
        "virtual_ip_mismatch",
    }


def test_unknown_runtime_role_is_retained_and_reviewed_losslessly(tmp_path):
    runtime = HSRP_HEADER + (
        "Vl10        10   110 P Maintenance local        10.0.10.3      10.0.10.1\n"
    )
    baseline, *_ = _run(tmp_path, runtime=runtime)

    row = _row(baseline)
    assert baseline["verdict"] == "INDETERMINATE"
    assert row["runtime_observed"] is True
    assert row["runtime_state_raw"] == "Maintenance"
    assert row["runtime_state"] == "UNCLASSIFIED"
    assert row["status"] == "review"


def test_unsupported_relevant_syntax_reviews_and_never_leaks_authentication(tmp_path):
    config = """\
hostname edge1
interface Vlan10
 standby 10 ip 10.0.10.1 secondary
 standby 10 authentication md5 key-string SUPER_SECRET_MATERIAL
end
"""
    baseline, *_ = _run(tmp_path, config=config)
    serialized = json.dumps(baseline)

    row = _row(baseline)
    assert baseline["verdict"] == "INDETERMINATE"
    assert row["status"] == "review"
    assert "secondary_vip_unsupported" in {
        finding["code"] for finding in row["findings"]
    }
    assert "SUPER_SECRET_MATERIAL" not in serialized
    assert str(tmp_path) not in serialized


def test_receipt_hashes_cover_bounded_semantics_not_raw_secret_bearing_bodies(tmp_path):
    def config(secret: str, vip: str = "10.0.10.1") -> str:
        return (
            "hostname edge1\n"
            "interface Vlan10\n"
            f" standby 10 ip {vip}\n"
            f" standby 10 authentication md5 key-string {secret}\n"
            "end\n"
        )

    first, *_ = _run(tmp_path / "first-secret", config=config("SECRET_ALPHA"))
    second, *_ = _run(tmp_path / "second-secret", config=config("SECRET_BRAVO"))
    changed, *_ = _run(
        tmp_path / "changed-vip",
        config=config("SECRET_ALPHA", "10.0.10.254"),
    )

    first_cell = _coverage(first)
    second_cell = _coverage(second)
    changed_cell = _coverage(changed)
    assert first_cell["config_sha256"] == second_cell["config_sha256"]
    assert first_cell["projection_sha256"] == second_cell["projection_sha256"]
    assert first_cell["config_sha256"] != changed_cell["config_sha256"]
    assert "SECRET_ALPHA" not in json.dumps(first)
    assert "SECRET_BRAVO" not in json.dumps(second)


def test_incomplete_runtime_evidence_is_not_verified(tmp_path):
    runtime = HSRP_HEADER + "--More--"
    baseline, *_ = _run(tmp_path, runtime=runtime)

    row = _row(baseline)
    assert baseline["verdict"] == "INDETERMINATE"
    assert row["status"] == "not_verified"
    assert row["acceptance"].startswith(
        "FHRP CONFIGURED GROUP NOT VERIFIED — BLOCKER:",
    )
    assert _coverage(baseline)["runtime_capture_status"] == "incomplete"


def test_incomplete_configuration_without_visible_subject_is_indeterminate(tmp_path):
    config = "hostname edge1\ninterface Vlan10\n description truncated\n"
    baseline, *_ = _run(tmp_path, config=config, runtime=HSRP_HEADER)

    assert baseline["rows"] == []
    assert baseline["verdict"] == "INDETERMINATE"
    assert baseline["assessed"] is False
    assert baseline["summary"]["by_coverage_status"]["not_verified"] == 3
    assert validate_fhrp_configured_group_baseline(
        baseline, require_current_run=True,
    )["valid"] is True


def test_explicitly_disabled_group_is_neutral_and_makes_no_health_claim(tmp_path):
    config = """\
hostname edge1
interface Vlan10
 standby 10 ip 10.0.10.1
 standby 10 shutdown
end
"""
    baseline, *_ = _run(tmp_path, config=config, runtime=HSRP_HEADER)

    row = _row(baseline)
    assert baseline["verdict"] == "NOT_APPLICABLE"
    assert baseline["assessed"] is False
    assert row["activation"] == "disabled"
    assert row["runtime_observed"] is False
    assert row["status"] == "administratively_disabled"
    assert "explicitly disabled" in row["acceptance"]
    assert "no runtime role, peer, or election-health claim" in row["acceptance"]


def test_flat_no_group_shutdown_reenables_the_configured_group(tmp_path):
    config = """\
hostname edge1
interface Vlan10
 standby 10 ip 10.0.10.1
 standby 10 shutdown
 no standby 10 shutdown
end
"""
    baseline, *_ = _run(tmp_path, config=config)

    row = _row(baseline)
    assert baseline["verdict"] == "CLEAR"
    assert row["activation"] == "active"
    assert row["status"] == "assessed"


def test_disabled_group_observed_at_runtime_requires_review(tmp_path):
    config = """\
hostname edge1
interface Vlan10
 standby 10 ip 10.0.10.1
 standby 10 shutdown
end
"""
    baseline, *_ = _run(tmp_path, config=config)

    row = _row(baseline)
    assert baseline["verdict"] == "INDETERMINATE"
    assert row["status"] == "review"
    assert {finding["code"] for finding in row["findings"]} == {
        "disabled_group_observed",
    }


def test_non_default_vrf_group_is_excluded_not_silently_assessed(tmp_path):
    config = """\
hostname edge1
interface Vlan10
 vrf forwarding TENANT_RED
 standby 10 ip 10.0.10.1
end
"""
    baseline, *_ = _run(tmp_path, config=config, runtime=HSRP_HEADER)

    assert baseline["verdict"] == "NOT_APPLICABLE"
    assert baseline["rows"] == []
    assert _coverage(baseline)["excluded_scope_count"] == 1
    assert _coverage(baseline)["subject"] is False
    assert "VRFs" in " ".join(baseline["limitations"])


def test_current_run_json_and_embedded_custody_boundaries_are_strict(tmp_path):
    baseline, *_ = _run(tmp_path)
    serialized = json.loads(json.dumps(baseline))

    assert validate_fhrp_configured_group_baseline(serialized)["valid"] is True
    rejected = validate_fhrp_configured_group_baseline(
        serialized, require_current_run=True,
    )
    assert rejected == {
        "present": True,
        "valid": False,
        "reason": "baseline_not_current_run_source_bound",
        "source_bound": False,
        "rows": [],
        "index": {},
        "baseline": {},
    }

    embedded = embedded_fhrp_configured_group_baseline(baseline)
    view = validate_fhrp_configured_group_baseline(embedded)
    assert view["valid"] is True and view["source_bound"] is False
    assert embedded["projection_custody"] == "embedded_unverified"
    assert all(
        row["projection_custody"] == "embedded_unverified"
        for row in embedded["rows"]
    )


def test_invalid_embedded_input_is_an_indeterminate_non_validating_abstention():
    embedded = embedded_fhrp_configured_group_baseline({})

    assert embedded["verdict"] == "INDETERMINATE"
    assert embedded["projection_custody"] == "embedded_unverified"
    assert embedded["summary"]["baseline_sha256"] == ""
    view = validate_fhrp_configured_group_baseline(embedded)
    assert view["valid"] is False
    assert view["rows"] == [] and view["index"] == {} and view["baseline"] == {}


def test_compute_without_any_captured_host_cannot_certify_not_applicable():
    baseline = compute_fhrp_configured_group_baseline({}, {}, None)

    assert not isinstance(baseline, _CurrentRunFhrpConfiguredGroupBaseline)
    assert baseline["verdict"] == "INDETERMINATE"
    assert baseline["projection_custody"] == "embedded_unverified"
    assert validate_fhrp_configured_group_baseline(baseline)["valid"] is False


def test_digest_and_resealed_semantic_tampering_are_rejected(tmp_path):
    baseline, *_ = _run(tmp_path)
    ordinary = copy.deepcopy(baseline)
    ordinary["rows"][0]["acceptance"] = "forged healthy target"
    assert validate_fhrp_configured_group_baseline(ordinary)["reason"] == (
        "baseline_digest_mismatch"
    )

    contradiction = copy.deepcopy(baseline)
    contradiction["rows"][0]["runtime_vip"] = "10.0.10.254"
    _reseal(contradiction)
    assert validate_fhrp_configured_group_baseline(contradiction)["reason"] == (
        "baseline_assessed_row_contradiction"
    )

    census = copy.deepcopy(baseline)
    census["summary"]["n_assessed"] = 999
    _reseal(census)
    assert validate_fhrp_configured_group_baseline(census)["reason"] == (
        "baseline_summary_mismatch"
    )

    acceptance = copy.deepcopy(baseline)
    acceptance["rows"][0]["acceptance"] = "forged operator acceptance"
    _reseal(acceptance)
    assert validate_fhrp_configured_group_baseline(acceptance)["reason"] == (
        "baseline_row_acceptance_invalid"
    )

    receipt = copy.deepcopy(baseline)
    receipt["rows"][0]["source_key"] = "show running-config#line:1 + show hsrp brief"
    _reseal(receipt)
    assert validate_fhrp_configured_group_baseline(receipt)["reason"] == (
        "baseline_row_receipt_mismatch"
    )

    receipt_hash = copy.deepcopy(baseline)
    receipt_hash["coverage"][0]["config_sha256"] = "0" * 64
    _reseal(receipt_hash)
    assert validate_fhrp_configured_group_baseline(receipt_hash)["reason"] == (
        "baseline_coverage_receipt_hash_mismatch"
    )


def test_detail_fallback_retains_each_hsrp_group(tmp_path):
    config = """\
hostname edge1
interface Vlan10
 standby 10 ip 10.0.10.1
 standby 20 ip 10.0.10.254
end
"""
    detail = """\
Vlan10 - Group 10
  State is Active
  Virtual IP address is 10.0.10.1
Vlan10 - Group 20
  State is Standby
  Virtual IP address is 10.0.10.254
"""
    baseline, *_ = _run(
        tmp_path,
        config=config,
        runtime=detail,
        runtime_command="show standby all",
    )

    assert baseline["verdict"] == "CLEAR"
    assert [(row["group"], row["runtime_state"]) for row in baseline["rows"]] == [
        ("10", "ACTIVE"),
        ("20", "STANDBY"),
    ]
    assert _coverage(baseline)["runtime_command"] == "show standby all"


def test_explicit_no_standby_groups_is_a_complete_empty_summary(tmp_path):
    baseline, *_ = _run(tmp_path, runtime="No standby groups configured\n")

    row = _row(baseline)
    assert _coverage(baseline)["runtime_parser_status"] == "complete"
    assert row["status"] == "degraded"
    assert row["runtime_observed"] is False


def test_host_by_subtype_coverage_matrix_is_complete_and_deterministic(tmp_path):
    first, *_ = _run(tmp_path / "first")
    second, *_ = _run(tmp_path / "second")

    assert [
        (cell["switch"], cell["protocol"], cell["status"])
        for cell in first["coverage"]
    ] == [
        ("edge1", "HSRP", "assessed"),
        ("edge1", "VRRP", "not_applicable"),
        ("edge1", "GLBP", "not_applicable"),
    ]
    assert first["summary"]["baseline_sha256"] == second["summary"][
        "baseline_sha256"
    ]


@pytest.mark.parametrize("value", [None, [], "baseline", 42, {"schema": "wrong"}])
def test_validator_fails_closed_without_copying_untrusted_leaves(value):
    view = validate_fhrp_configured_group_baseline(value)

    assert view["valid"] is False and view["source_bound"] is False
    assert view["rows"] == [] and view["index"] == {} and view["baseline"] == {}
    assert view["present"] is (value is not None)
