"""Adversarial contract tests for the bounded configured-peer BGP owner.

The feature deliberately covers only direct, static, literal IPv4 peers in the
default/global IPv4-unicast scope.  These tests keep that narrow claim useful:
complete evidence can prove the configured denominator, while capture defects,
parser gaps, inheritance, and unsupported scopes can never become a clean gate.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from cisco_toolkit.bgp_intent import (
    BGP_CONFIGURED_PEER_SCHEMA,
    _CurrentRunBgpConfiguredPeerBaseline,
    compute_bgp_configured_peer_baseline,
    embedded_bgp_configured_peer_baseline,
    validate_bgp_configured_peer_baseline,
)
from cisco_toolkit.capture_integrity import compute_capture_integrity_from_paths


IOS_CONFIG = """\
version 17.9
router bgp 65001
 neighbor 192.0.2.2 remote-as 65002
end
"""

IOS_SUMMARY = """\
BGP router identifier 192.0.2.1, local AS number 65001
Neighbor V AS MsgRcvd MsgSent TblVer InQ OutQ Up/Down State/PfxRcd
192.0.2.2 4 65002 10 10 3 0 0 00:10:00 5
"""

EMPTY_IOS_SUMMARY = """\
BGP router identifier 192.0.2.1, local AS number 65001
Neighbor V AS MsgRcvd MsgSent TblVer InQ OutQ Up/Down State/PfxRcd
"""

COVERAGE_STATUS_ORDER = (
    "degraded", "review", "not_verified", "assessed", "not_applicable",
)


def _summary(*rows: str, local_as: str = "65001", nxos_header: bool = False) -> str:
    prefix = (
        "BGP summary information for VRF default, address family IPv4 Unicast\n"
        if nxos_header else
        f"BGP router identifier 192.0.2.1, local AS number {local_as}\n"
    )
    return (
        prefix
        + "Neighbor V AS MsgRcvd MsgSent TblVer InQ OutQ Up/Down State/PfxRcd\n"
        + "".join(row.rstrip("\n") + "\n" for row in rows)
    )


def _run(
    tmp_path: Path,
    *,
    config: str = IOS_CONFIG,
    runtime: str = IOS_SUMMARY,
    platform: str = "ios",
    runtime_command: str = "show ip bgp summary",
    extra_runtime: dict[str, str] | None = None,
    meta: dict[str, str] | None = None,
    include_config: bool = True,
):
    host = "edge1"
    mapping: dict[str, str] = {}
    if include_config:
        config_path = tmp_path / "show_running-config.txt"
        config_path.write_text(config, encoding="utf-8")
        mapping["show running-config"] = str(config_path)
    runtime_path = tmp_path / "show_bgp_primary.txt"
    runtime_path.write_text(runtime, encoding="utf-8")
    mapping[runtime_command] = str(runtime_path)
    for index, (command, body) in enumerate((extra_runtime or {}).items(), 1):
        path = tmp_path / f"show_bgp_extra_{index}.txt"
        path.write_text(body, encoding="utf-8")
        mapping[command] = str(path)
    paths = {host: mapping}
    integrity = compute_capture_integrity_from_paths(
        paths, {host: meta or {}}
    )
    baseline = compute_bgp_configured_peer_baseline(
        paths, integrity, {host: {"platform": platform}}
    )
    return baseline, paths, integrity


def _row(baseline: dict, peer: str = "192.0.2.2") -> dict:
    return next(row for row in baseline["rows"] if row["peer"] == peer)


def _reseal(value: dict) -> None:
    """Reproduce the public canonical digest to test semantics beyond checksum integrity."""
    payload = copy.deepcopy(value)
    payload["summary"].pop("baseline_sha256", None)
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    value["summary"]["baseline_sha256"] = hashlib.sha256(encoded).hexdigest()


def test_ios_implicit_default_ipv4_peer_is_source_bound_and_clear(tmp_path):
    baseline, _paths, _integrity = _run(tmp_path)

    assert isinstance(baseline, _CurrentRunBgpConfiguredPeerBaseline)
    assert set(baseline) == {
        "schema", "scope", "verdict", "assessed", "projection_custody",
        "rows", "coverage", "findings", "summary", "limitations",
    }
    assert baseline["schema"] == BGP_CONFIGURED_PEER_SCHEMA
    assert baseline["scope"] == {
        "routing_instance": "default", "afi": "ipv4", "safi": "unicast",
        "peer_kind": "direct_static_literal",
    }
    assert baseline["verdict"] == "CLEAR" and baseline["assessed"] is True
    assert list(baseline["summary"]["by_coverage_status"]) == list(COVERAGE_STATUS_ORDER)
    assert baseline["summary"]["by_coverage_status"] == {
        "degraded": 0,
        "review": 0,
        "not_verified": 0,
        "assessed": 1,
        "not_applicable": 0,
    }

    row = _row(baseline)
    assert row["scope"] == "default/ipv4-unicast"
    assert row["local_as"] == "65001"
    assert row["configured_remote_as"] == row["runtime_remote_as"] == "65002"
    assert row["activation"] == "active"
    assert row["runtime_observed"] is True
    assert row["runtime_state"] == "ESTABLISHED"
    assert row["runtime_state_raw"] == "5"
    assert row["status"] == "assessed"
    assert row["projection_custody"] == "current_run_source_bound"
    assert "Prefix count is not pinned" in row["acceptance"]

    coverage = baseline["coverage"][0]
    assert coverage["config_command"] == "show running-config"
    assert coverage["runtime_command"] == "show ip bgp summary"
    assert coverage["config_capture_status"] == coverage["runtime_capture_status"] == "ok"
    assert coverage["config_parser_status"] == coverage["runtime_parser_status"] == "complete"
    assert coverage["neighbor_candidate_count"] == coverage["supported_peer_count"] == 1
    assert coverage["rejected_candidate_count"] == 0
    assert coverage["runtime_candidate_count"] == coverage["runtime_parsed_count"] == 1
    assert coverage["runtime_rejected_count"] == 0
    for field in ("config_sha256", "runtime_sha256", "projection_sha256"):
        assert len(coverage[field]) == 64
        int(coverage[field], 16)

    view = validate_bgp_configured_peer_baseline(baseline, require_current_run=True)
    assert view["valid"] is True and view["source_bound"] is True
    assert set(view["index"]) == {("edge1", "192.0.2.2")}
    json.dumps(baseline, allow_nan=False)
    assert str(tmp_path) not in json.dumps(baseline)


def test_ios_explicit_activation_and_disabled_peers_are_distinct(tmp_path):
    config = """\
version 17.9
router bgp 65001
 no bgp default ipv4-unicast
 neighbor 192.0.2.2 remote-as 65002
 neighbor 192.0.2.3 remote-as 65003
 neighbor 192.0.2.4 remote-as 65004
 address-family ipv4
  neighbor 192.0.2.2 activate
  no neighbor 192.0.2.3 activate
 exit-address-family
 neighbor 192.0.2.4 shutdown
end
"""
    baseline, *_ = _run(tmp_path, config=config)
    by_peer = {row["peer"]: row for row in baseline["rows"]}

    assert baseline["verdict"] == "CLEAR"
    assert by_peer["192.0.2.2"]["activation"] == "active"
    assert by_peer["192.0.2.2"]["status"] == "assessed"
    for peer in ("192.0.2.3", "192.0.2.4"):
        assert by_peer[peer]["activation"] == "disabled"
        assert by_peer[peer]["status"] == "administratively_disabled"
        assert by_peer[peer]["runtime_observed"] is False
        assert "explicitly disabled" in by_peer[peer]["acceptance"]
    assert baseline["summary"]["n_disabled"] == 2


def test_no_default_ipv4_without_explicit_activate_is_ambiguous_not_missing_down(tmp_path):
    config = """\
version 17.9
router bgp 65001
 no bgp default ipv4-unicast
 neighbor 192.0.2.2 remote-as 65002
end
"""
    baseline, *_ = _run(tmp_path, config=config, runtime=EMPTY_IOS_SUMMARY)
    row = _row(baseline)

    assert baseline["verdict"] == "INDETERMINATE" and baseline["assessed"] is False
    assert row["activation"] == "ambiguous"
    assert row["runtime_observed"] is False
    assert row["status"] == "review"
    assert {finding["code"] for finding in row["findings"]} == {"activation_ambiguous"}
    assert "PRE-CUTOVER REVIEW" in row["acceptance"]
    assert "down" not in row["acceptance"].casefold()


def test_nxos_nested_neighbor_with_explicit_ipv4_unicast_is_clear(tmp_path):
    config = """\
!Command: show running-config
router bgp 65001
  neighbor 192.0.2.2
    remote-as 65002
    address-family ipv4 unicast
"""
    runtime = _summary(
        "192.0.2.2 4 65002 10 10 3 0 0 00:10:00 5",
        nxos_header=True,
    )
    baseline, *_ = _run(
        tmp_path, config=config, runtime=runtime, platform="nxos",
        runtime_command="show bgp ipv4 unicast summary",
    )

    assert baseline["verdict"] == "CLEAR"
    assert _row(baseline)["activation"] == "active"
    assert _row(baseline)["status"] == "assessed"


def test_nxos_uses_integrity_ok_scoped_fallback_with_proven_context(tmp_path):
    config = """\
!Command: show running-config
router bgp 65001
  neighbor 192.0.2.2
    remote-as 65002
    address-family ipv4 unicast
"""
    fallback = _summary(
        "192.0.2.2 4 65002 10 10 3 0 0 00:10:00 5",
        nxos_header=True,
    )
    baseline, *_ = _run(
        tmp_path, config=config,
        runtime="% Invalid input detected at '^' marker.\n", platform="nxos",
        runtime_command="show bgp ipv4 unicast summary",
        extra_runtime={"show bgp summary": fallback},
    )

    assert baseline["coverage"][0]["runtime_command"] == "show bgp summary"
    assert baseline["coverage"][0]["runtime_capture_status"] == "ok"
    assert baseline["verdict"] == "CLEAR"


def test_nxos_unscoped_summary_without_default_ipv4_header_never_clears(tmp_path):
    config = """\
!Command: show running-config
router bgp 65001
  neighbor 192.0.2.2
    remote-as 65002
    address-family ipv4 unicast
"""
    baseline, *_ = _run(
        tmp_path, config=config, runtime=IOS_SUMMARY, platform="nxos",
        runtime_command="show bgp summary",
    )

    assert baseline["verdict"] == "INDETERMINATE"
    assert baseline["coverage"][0]["runtime_parser_status"] == "review"
    assert "runtime_scope_unproven" in baseline["coverage"][0]["finding_codes"]
    assert not any(row["status"] == "assessed" for row in baseline["rows"])


def test_explicit_active_configured_peer_missing_is_blocked_but_only_not_observed(tmp_path):
    baseline, *_ = _run(tmp_path, runtime=EMPTY_IOS_SUMMARY)
    row = _row(baseline)

    assert baseline["verdict"] == "BLOCKED" and baseline["assessed"] is True
    assert row["status"] == "degraded"
    assert row["runtime_observed"] is False
    assert row["runtime_state"] == "NOT_OBSERVED"
    assert "not observed" in row["acceptance"]
    assert "is down" not in row["acceptance"].casefold()
    assert "not asserted administratively or physically down" in baseline["limitations"][-1]
    assert baseline["summary"]["by_coverage_status"] == {
        "degraded": 1, "review": 0, "not_verified": 0,
        "assessed": 0, "not_applicable": 0,
    }


@pytest.mark.parametrize("state", ["Idle", "Active", "Connect", "OpenSent", "OpenConfirm", "Idle (Admin)"])
def test_recognized_non_established_fsm_state_is_degraded(tmp_path, state):
    runtime = _summary(f"192.0.2.2 4 65002 0 0 0 0 0 never {state}")
    baseline, *_ = _run(tmp_path, runtime=runtime)
    row = _row(baseline)

    assert baseline["verdict"] == "BLOCKED"
    assert row["status"] == "degraded"
    assert row["runtime_observed"] is True
    assert row["runtime_state_raw"] == state
    assert "matching this degraded state is NOT ACCEPTANCE" in row["acceptance"]


def test_unknown_runtime_state_is_review_not_invented_down(tmp_path):
    runtime = _summary("192.0.2.2 4 65002 0 0 0 0 0 never VendorMystery")
    baseline, *_ = _run(tmp_path, runtime=runtime)
    row = _row(baseline)

    assert baseline["verdict"] == "INDETERMINATE"
    assert row["status"] == "review" and row["runtime_state"] == "UNCLASSIFIED"
    assert "runtime_state_unclassified" in {finding["code"] for finding in row["findings"]}


def test_runtime_remote_as_mismatch_is_review(tmp_path):
    runtime = _summary("192.0.2.2 4 65199 10 10 3 0 0 00:10:00 5")
    baseline, *_ = _run(tmp_path, runtime=runtime)
    row = _row(baseline)

    assert baseline["verdict"] == "INDETERMINATE"
    assert row["status"] == "review"
    assert row["configured_remote_as"] == "65002" and row["runtime_remote_as"] == "65199"
    assert "remote_as_mismatch" in {finding["code"] for finding in row["findings"]}


def test_runtime_only_peer_is_review_not_called_rogue(tmp_path):
    config = """\
version 17.9
router bgp 65001
 redistribute connected
end
"""
    baseline, *_ = _run(tmp_path, config=config)
    row = _row(baseline)

    assert baseline["verdict"] == "INDETERMINATE"
    assert row["configured_remote_as"] == "" and row["runtime_observed"] is True
    assert row["status"] == "review"
    assert "runtime_peer_not_in_bounded_config" in {finding["code"] for finding in row["findings"]}
    assert "rogue" not in json.dumps(row).casefold()


@pytest.mark.parametrize(
    "unsupported_line",
    [
        " bgp listen range 198.51.100.0/24 peer-group DYNAMIC",
        " neighbor PEERS peer-group",
        " template peer-session SESSION-TEMPLATE",
        " neighbor GigabitEthernet0/0 remote-as 65010",
    ],
)
def test_relevant_dynamic_template_or_nonliteral_syntax_prevents_clear(tmp_path, unsupported_line):
    config = IOS_CONFIG.replace("end\n", unsupported_line + "\nend\n")
    baseline, *_ = _run(tmp_path, config=config)

    assert baseline["verdict"] == "INDETERMINATE"
    assert baseline["coverage"][0]["status"] == "review"
    assert baseline["coverage"][0]["unsupported_relevant_count"] >= 1
    assert not any(row["status"] == "assessed" for row in baseline["rows"])
    assert baseline["summary"]["by_coverage_status"] == {
        "degraded": 0, "review": 1, "not_verified": 0,
        "assessed": 0, "not_applicable": 0,
    }


def test_unsupported_relevant_subject_without_literal_row_is_not_not_applicable(tmp_path):
    config = """\
version 17.9
router bgp 65001
 bgp listen range 198.51.100.0/24 peer-group DYNAMIC
end
"""
    baseline, *_ = _run(tmp_path, config=config, runtime=EMPTY_IOS_SUMMARY)

    assert baseline["rows"] == []
    assert baseline["coverage"][0]["unsupported_relevant_count"] == 1
    assert baseline["verdict"] == "INDETERMINATE"
    assert baseline["assessed"] is False


def test_nondefault_vrf_and_ipv6_peers_are_counted_excluded_not_faulted(tmp_path):
    config = """\
version 17.9
router bgp 65001
 neighbor 192.0.2.2 remote-as 65002
 address-family ipv6 unicast
  neighbor 2001:db8::2 remote-as 65012
 exit-address-family
 address-family ipv4 vrf BLUE
  neighbor 198.51.100.2 remote-as 65022
 exit-address-family
end
"""
    baseline, *_ = _run(tmp_path, config=config)

    assert baseline["verdict"] == "CLEAR"
    assert [row["peer"] for row in baseline["rows"]] == ["192.0.2.2"]
    assert baseline["coverage"][0]["excluded_scope_count"] >= 2
    assert baseline["coverage"][0]["unsupported_relevant_count"] == 0
    assert not baseline["findings"]


def test_no_bgp_subject_with_complete_config_is_neutral_not_applicable(tmp_path):
    config = "version 17.9\nhostname edge1\nend\n"
    baseline, *_ = _run(tmp_path, config=config, runtime=EMPTY_IOS_SUMMARY)

    assert baseline["verdict"] == "NOT_APPLICABLE"
    assert baseline["assessed"] is False
    assert baseline["rows"] == []
    assert baseline["coverage"][0]["subject"] is False
    assert baseline["coverage"][0]["status"] == "not_applicable"
    assert baseline["summary"]["by_coverage_status"] == {
        "degraded": 0, "review": 0, "not_verified": 0,
        "assessed": 0, "not_applicable": 1,
    }


def test_truncated_config_cannot_create_assessed_or_degraded_peer_rows(tmp_path):
    truncated = """\
Building configuration...
router bgp 65001
 neighbor 192.0.2.2 remote-as 65002
"""
    baseline, *_ = _run(tmp_path, config=truncated)

    assert baseline["verdict"] == "INDETERMINATE"
    assert baseline["coverage"][0]["config_capture_status"] == "incomplete"
    assert all(row["status"] == "not_verified" for row in baseline["rows"])
    assert not any(row["status"] in ("assessed", "degraded") for row in baseline["rows"])


def test_incomplete_config_with_empty_runtime_cannot_collapse_to_not_applicable(tmp_path):
    truncated = """\
Building configuration...
router bgp 65001
 neighbor 192.0.2.2 remote-as 65002
"""
    baseline, *_ = _run(tmp_path, config=truncated, runtime=EMPTY_IOS_SUMMARY)

    assert baseline["coverage"][0]["config_capture_status"] == "incomplete"
    assert baseline["coverage"][0]["status"] == "not_verified"
    assert baseline["verdict"] == "INDETERMINATE"
    assert baseline["assessed"] is False
    assert baseline["summary"]["by_coverage_status"] == {
        "degraded": 0, "review": 0, "not_verified": 1,
        "assessed": 0, "not_applicable": 0,
    }


def test_coverage_census_counts_every_host_without_promoting_a_non_subject(tmp_path):
    _baseline, paths, integrity = _run(tmp_path)
    baseline = compute_bgp_configured_peer_baseline(
        paths,
        integrity,
        {
            "edge1": {"platform": "ios"},
            "edge2": {"platform": "ios"},
        },
    )

    assert baseline["verdict"] == "CLEAR"
    assert baseline["summary"]["n_hosts"] == 2
    assert baseline["summary"]["n_subject_hosts"] == 1
    assert baseline["summary"]["by_coverage_status"] == {
        "degraded": 0, "review": 0, "not_verified": 1,
        "assessed": 1, "not_applicable": 0,
    }
    assert sum(baseline["summary"]["by_coverage_status"].values()) == 2
    assert validate_bgp_configured_peer_baseline(baseline)["valid"] is True


def test_pager_tailed_runtime_is_not_verified_even_if_a_peer_row_precedes_it(tmp_path):
    runtime = IOS_SUMMARY + "--More--\n"
    baseline, *_ = _run(tmp_path, runtime=runtime)

    assert baseline["coverage"][0]["runtime_capture_status"] == "incomplete"
    assert baseline["verdict"] == "INDETERMINATE"
    assert _row(baseline)["status"] == "not_verified"
    assert not any(row["status"] in ("assessed", "degraded") for row in baseline["rows"])


@pytest.mark.parametrize("command", ["show running-config", "show ip bgp summary"])
def test_timing_fallback_on_either_source_abstains(tmp_path, command):
    baseline, *_ = _run(tmp_path, meta={command: "timing_fallback"})

    coverage = baseline["coverage"][0]
    field = "config_capture_status" if command == "show running-config" else "runtime_capture_status"
    assert coverage[field] == "unverified_prompt"
    assert baseline["verdict"] == "INDETERMINATE"
    assert not any(row["status"] in ("assessed", "degraded") for row in baseline["rows"])


def test_duplicate_integrity_inspection_is_not_source_completeness(tmp_path):
    baseline, paths, integrity = _run(tmp_path)
    duplicate = copy.deepcopy(integrity)
    duplicate["inspections"].append({
        "host": "edge1", "command": "show ip bgp summary", "status": "ok",
    })
    result = compute_bgp_configured_peer_baseline(
        paths, duplicate, {"edge1": {"platform": "ios"}}
    )

    assert baseline["verdict"] == "CLEAR"  # positive control
    assert result["coverage"][0]["runtime_capture_status"] == "inspection_duplicate"
    assert result["verdict"] == "INDETERMINATE"
    assert _row(result)["status"] == "not_verified"


def test_partially_malformed_runtime_candidate_denominator_prevents_clear(tmp_path):
    config = IOS_CONFIG.replace(
        "end\n", " neighbor 192.0.2.3 remote-as 65003\nend\n"
    )
    runtime = _summary(
        "192.0.2.2 4 65002 10 10 3 0 0 00:10:00 5",
        "192.0.2.3 4 ??? truncated-row",
    )
    baseline, *_ = _run(tmp_path, config=config, runtime=runtime)
    coverage = baseline["coverage"][0]

    assert coverage["runtime_candidate_count"] == 2
    assert coverage["runtime_parsed_count"] == 1
    assert coverage["runtime_rejected_count"] == 1
    assert coverage["runtime_candidate_count"] == (
        coverage["runtime_parsed_count"] + coverage["runtime_rejected_count"]
    )
    assert baseline["verdict"] == "INDETERMINATE"
    assert all(row["status"] == "review" for row in baseline["rows"])


def test_wrapped_runtime_peer_is_never_silently_dropped_into_clear(tmp_path):
    runtime = _summary(
        "192.168.250.254 4 65002",
        "                         984 1086 11 0 0 16:16:33 Idle",
    )
    config = IOS_CONFIG.replace("192.0.2.2", "192.168.250.254")
    baseline, *_ = _run(tmp_path, config=config, runtime=runtime)

    assert baseline["verdict"] != "CLEAR"
    assert baseline["coverage"][0]["runtime_rejected_count"] >= 1
    assert not any(row["status"] == "assessed" for row in baseline["rows"])


def test_current_run_marker_is_lost_by_json_roundtrip_and_embedded_projection(tmp_path):
    baseline, *_ = _run(tmp_path)
    current = validate_bgp_configured_peer_baseline(baseline, require_current_run=True)
    loaded = json.loads(json.dumps(baseline))
    ordinary = validate_bgp_configured_peer_baseline(loaded)
    required = validate_bgp_configured_peer_baseline(loaded, require_current_run=True)
    embedded = embedded_bgp_configured_peer_baseline(baseline)
    embedded_view = validate_bgp_configured_peer_baseline(embedded)

    assert current["valid"] and current["source_bound"]
    assert ordinary["valid"] and ordinary["source_bound"] is False
    assert required == {
        "present": True, "valid": False,
        "reason": "baseline_not_current_run_source_bound", "source_bound": False,
        "rows": [], "index": {}, "baseline": {},
    }
    assert embedded_view["valid"] and embedded_view["source_bound"] is False
    assert embedded["projection_custody"] == "embedded_unverified"
    assert all(row["projection_custody"] == "embedded_unverified" for row in embedded["rows"])


def test_digest_detects_post_owner_row_mutation_and_echoes_no_hostile_rows(tmp_path):
    baseline, *_ = _run(tmp_path)
    mutated = copy.deepcopy(dict(baseline))
    mutated["rows"][0]["runtime_state"] = "IDLE"
    view = validate_bgp_configured_peer_baseline(mutated)

    assert view["valid"] is False and view["reason"] == "baseline_digest_mismatch"
    assert view["rows"] == [] and view["index"] == {} and view["baseline"] == {}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.__setitem__("verdict", "BLOCKED"),
        lambda value: value["coverage"][0].__setitem__("supported_peer_count", 999),
        lambda value: value["rows"][0].__setitem__("hostile_extra", "caller claim"),
    ],
)
def test_recomputed_checksum_cannot_authorize_semantically_hostile_receipt(tmp_path, mutate):
    baseline, *_ = _run(tmp_path)
    hostile = copy.deepcopy(dict(baseline))
    mutate(hostile)
    _reseal(hostile)

    view = validate_bgp_configured_peer_baseline(hostile)
    assert view["valid"] is False
    assert view["rows"] == [] and view["index"] == {} and view["baseline"] == {}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda census: census.pop("assessed"),
        lambda census: census.__setitem__("hostile_extra", 0),
        lambda census: census.__setitem__("assessed", True),
        lambda census: census.__setitem__("assessed", -1),
        lambda census: census.update({"assessed": 0, "review": 1}),
    ],
)
def test_resealed_coverage_census_must_be_typed_exact_and_reconciled(tmp_path, mutate):
    baseline, *_ = _run(tmp_path)
    hostile = copy.deepcopy(dict(baseline))
    mutate(hostile["summary"]["by_coverage_status"])
    _reseal(hostile)

    view = validate_bgp_configured_peer_baseline(hostile)
    assert view["valid"] is False
    assert view["rows"] == [] and view["index"] == {} and view["baseline"] == {}


def test_subject_coverage_can_never_claim_not_applicable(tmp_path):
    baseline, *_ = _run(tmp_path)
    hostile = copy.deepcopy(dict(baseline))
    hostile["coverage"][0]["status"] = "not_applicable"
    _reseal(hostile)

    view = validate_bgp_configured_peer_baseline(hostile)
    assert view["valid"] is False
    assert view["reason"] == "baseline_coverage_subject_status_invalid"


@pytest.mark.parametrize(
    "value",
    [None, 7, "bad", [], {}, {"schema": BGP_CONFIGURED_PEER_SCHEMA}, {"rows": [object()]},],
)
def test_validator_and_embedded_projection_are_total_on_hostile_roots(value):
    view = validate_bgp_configured_peer_baseline(value)
    embedded = embedded_bgp_configured_peer_baseline(value)

    assert view["valid"] is False
    assert view["rows"] == [] and view["index"] == {} and view["baseline"] == {}
    assert embedded["schema"] == BGP_CONFIGURED_PEER_SCHEMA
    assert embedded["verdict"] == "INDETERMINATE"
    assert embedded["projection_custody"] == "embedded_unverified"
    json.dumps(embedded, allow_nan=False)


@pytest.mark.parametrize(
    "mappings, integrity, devices",
    [
        (None, None, None),
        ([], [], []),
        ({7: "bad"}, {"inspections": [None, 7, "bad"]}, {"edge1": object()}),
        ({"edge1": 7}, {"inspections": "bad"}, {"edge1": {"platform": ["ios"]}}),
    ],
)
def test_compute_is_total_and_json_ready_on_hostile_outer_inputs(mappings, integrity, devices):
    baseline = compute_bgp_configured_peer_baseline(mappings, integrity, devices)
    assert baseline["schema"] == BGP_CONFIGURED_PEER_SCHEMA
    assert baseline["verdict"] in {"CLEAR", "BLOCKED", "INDETERMINATE", "NOT_APPLICABLE"}
    assert validate_bgp_configured_peer_baseline(baseline)["valid"] is True
    json.dumps(baseline, allow_nan=False)
