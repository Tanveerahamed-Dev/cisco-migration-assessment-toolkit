"""Configured BGP peer truth reaches readiness, validation, and NRFU unchanged."""

from __future__ import annotations

from copy import deepcopy

from cisco_toolkit.analyze import (
    BGP_IPV4_SUMMARY_COMMANDS,
    compute_current_baseline_gate,
    compute_migration_readiness,
    compute_validation_plan,
)
from cisco_toolkit.bgp_intent import (
    compute_bgp_configured_peer_baseline,
    embedded_bgp_configured_peer_baseline,
    validate_bgp_configured_peer_baseline,
)
from cisco_toolkit.capture_integrity import compute_capture_integrity_from_paths
from cisco_toolkit.nrfu_export import compute_nrfu_commands


def _current_baseline(tmp_path, *, config: str, runtime: str):
    config_path = tmp_path / "show_running-config.txt"
    runtime_path = tmp_path / "show_ip_bgp_summary.txt"
    config_path.write_text(config, encoding="utf-8")
    runtime_path.write_text(runtime, encoding="utf-8")
    paths = {"r1": {
        "show running-config": str(config_path),
        "show ip bgp summary": str(runtime_path),
    }}
    integrity = compute_capture_integrity_from_paths(paths)
    baseline = compute_bgp_configured_peer_baseline(
        paths, integrity, devices={"r1": {"platform": "ios"}},
    )
    assert validate_bgp_configured_peer_baseline(
        baseline, require_current_run=True)["valid"] is True
    return baseline


def _two_configured_one_runtime(tmp_path):
    return _current_baseline(
        tmp_path,
        config=(
            "hostname r1\n"
            "router bgp 65001\n"
            " neighbor 192.0.2.1 remote-as 65002\n"
            " neighbor 192.0.2.2 remote-as 65003\n"
            "end\n"
        ),
        runtime=(
            "BGP router identifier 203.0.113.1, local AS number 65001\n"
            "Neighbor V AS MsgRcvd MsgSent TblVer InQ OutQ Up/Down State/PfxRcd\n"
            "192.0.2.1 4 65002 10 11 1 0 0 00:10:00 5\n"
        ),
    )


def _dep_map():
    return {
        "single_fiber": [], "errdis": [], "halfdup_up": [], "sole_gw": {},
        "orphan": set(), "access_by_vlan": {}, "model": {"hosts": ["r1"]},
    }


def _readiness(baseline):
    return compute_migration_readiness(
        {"r1": {}}, [{"switches": ["r1"], "endpoints": 0}],
        [{"switch": "r1", "band": "Good"}], [{"switch": "r1"}], [], [], [],
        _dep_map(), bgp_configured_peer_baseline=baseline,
    )[0]


def _plan(baseline):
    return compute_validation_plan(
        {"r1": {}},
        move_groups=[{"switches": ["r1"]}],
        routing_neighbors={"r1": {"bgp": [
            {"neighbor": "192.0.2.1", "as": "65002", "state": "5"},
        ]}},
        devices={"r1": {"platform": "ios"}},
        bgp_configured_peer_baseline=baseline,
    )


def _bgp_nrfu_cases(baseline, *, observed=True):
    routing = {"r1": {"bgp": [
        {"neighbor": "192.0.2.1", "as": "65002", "state": "5"},
    ]}} if observed else {"r1": {"bgp": []}}
    output = compute_nrfu_commands({
        "devices": {"r1": {"platform": "ios"}},
        "interfaces": {"r1": {}},
        "move_groups": [{"switches": ["r1"]}],
        "routing_neighbors": routing,
        "bgp_configured_peer_baseline": baseline,
    })
    cases = [
        case
        for wave in output["waves"]
        for device in wave["devices"]
        for case in device["cases"]
        if case.get("evidence_family") == "BGP"
    ]
    return output, cases


def test_missing_configured_peer_blocks_every_decision_surface(tmp_path):
    baseline = _two_configured_one_runtime(tmp_path)
    assert baseline["verdict"] == "BLOCKED"
    assert [(row["peer"], row["status"]) for row in baseline["rows"]] == [
        ("192.0.2.1", "assessed"),
        ("192.0.2.2", "degraded"),
    ]

    readiness = _readiness(baseline)
    routing_check = next(
        check for check in readiness["checks"] if check["check"] == "Routing adjacencies up"
    )
    assert readiness["readiness"] == "NOT READY"
    assert routing_check["status"] == "fail"
    assert "192.0.2.2" in routing_check["note"]

    plan = _plan(baseline)
    rows = [row for row in plan["items"] if row.get("peer")]
    assert len(rows) == 2
    assert {row["peer"] for row in rows} == {"192.0.2.1", "192.0.2.2"}
    missing = next(row for row in rows if row["peer"] == "192.0.2.2")
    assert missing["evidence_state"] == "degraded"
    assert missing["expect"].startswith("PRE-CUTOVER DEGRADED — BLOCKER:")
    assert missing["local_as"] == "65001"
    assert missing["configured_remote_as"] == "65003"
    assert missing["runtime_observed"] is False
    assert missing["runtime_state"] == "NOT_OBSERVED"
    assert missing["scope"] == "default/ipv4-unicast"
    assert compute_current_baseline_gate(plan)["verdict"] == "BLOCKED"

    nrfu, cases = _bgp_nrfu_cases(baseline)
    assert len(cases) == 2
    assert nrfu["summary"]["n_routing_blockers"] == 1
    missing_case = next(case for case in cases if case["peer"] == "192.0.2.2")
    assert missing_case["evidence_state"] == "degraded"
    assert missing_case["expected"].startswith("PRE-CUTOVER DEGRADED — BLOCKER:")
    assert missing_case["runtime_observed"] is False
    assert missing_case["bgp_scope"] == "default/ipv4-unicast"


def test_serialized_or_phase_failed_baseline_cannot_authorize_positive_bgp(tmp_path):
    current = _two_configured_one_runtime(tmp_path)
    embedded = embedded_bgp_configured_peer_baseline(current)
    assert validate_bgp_configured_peer_baseline(embedded)["valid"] is True
    assert validate_bgp_configured_peer_baseline(
        embedded, require_current_run=True)["valid"] is False
    tampered = deepcopy(embedded)
    tampered["rows"][0]["acceptance"] = "forged healthy target"
    assert validate_bgp_configured_peer_baseline(tampered)["valid"] is False

    readiness = _readiness(embedded)
    assert readiness["readiness"] == "CAUTION"
    assert next(check for check in readiness["checks"]
                if check["check"] == "Routing adjacencies up")["status"] == "warn"

    for rejected in (embedded, {}, tampered):
        plan = _plan(rejected)
        gate = compute_current_baseline_gate(plan)
        assert gate["verdict"] != "CLEAR"
        assert any(row["expect"].startswith(
            "BGP CONFIGURED PEER NOT VERIFIED — BLOCKER:") for row in plan["items"])

        output, cases = _bgp_nrfu_cases(rejected)
        assert cases
        assert all(case["evidence_state"] == "not_verified" for case in cases)
        assert all(case["expected"].startswith(
            "BGP CONFIGURED PEER NOT VERIFIED — BLOCKER:") for case in cases)
        assert output["summary"]["n_routing_blockers"] >= 1


def test_legacy_direct_callers_keep_observed_only_behavior():
    plan = compute_validation_plan(
        {"r1": {}}, routing_neighbors={"r1": {"bgp": [
            {"neighbor": "192.0.2.1", "as": "65002", "state": "5"},
        ]}}, devices={"r1": {"platform": "ios"}},
    )
    row = next(item for item in plan["items"] if item["category"] == "Routing")
    assert row["check"] == "BGP adjacency baseline not verified"
    assert "configured_remote_as" not in row

    readiness = compute_migration_readiness(
        {"r1": {}}, [{"switches": ["r1"]}], [{"switch": "r1", "band": "Good"}],
        [{"switch": "r1"}], [], [],
        [{"switch": "r1", "protocol": "BGP", "severity": "Info"}], _dep_map(),
    )[0]
    routing = next(check for check in readiness["checks"]
                   if check["check"] == "Routing adjacencies up")
    assert routing == {
        "check": "Routing adjacencies up", "status": "pass", "note": "all neighbors up",
        "phase": "Baseline capture",
    }


def test_administratively_disabled_peer_is_typed_neutral(tmp_path):
    baseline = _current_baseline(
        tmp_path,
        config=(
            "router bgp 65001\n"
            " neighbor 192.0.2.9 remote-as 65009\n"
            " neighbor 192.0.2.9 shutdown\n"
            "end\n"
        ),
        runtime=(
            "BGP router identifier 203.0.113.1, local AS number 65001\n"
            "Neighbor V AS MsgRcvd MsgSent TblVer InQ OutQ Up/Down State/PfxRcd\n"
        ),
    )
    assert baseline["verdict"] == "NOT_APPLICABLE"
    assert baseline["rows"][0]["status"] == "administratively_disabled"

    plan = _plan(baseline)
    row = next(item for item in plan["items"] if item.get("peer") == "192.0.2.9")
    assert row["evidence_state"] == "administratively_disabled"
    assert "not evidence of BGP health" in row["expect"]
    assert compute_current_baseline_gate(plan)["verdict"] == "CLEAR"

    output, cases = _bgp_nrfu_cases(baseline)
    assert cases[0]["evidence_state"] == "administratively_disabled"
    assert output["summary"]["n_routing_blockers"] == 0


def test_not_applicable_is_neutral_only_inside_the_current_run_trust_boundary(tmp_path):
    baseline = _current_baseline(
        tmp_path,
        config="hostname r1\ninterface Loopback0\n description no-bgp\nend\n",
        runtime=(
            "BGP router identifier 203.0.113.1, local AS number 65001\n"
            "Neighbor V AS MsgRcvd MsgSent TblVer InQ OutQ Up/Down State/PfxRcd\n"
        ),
    )
    assert baseline["verdict"] == "NOT_APPLICABLE"
    output, cases = _bgp_nrfu_cases(baseline, observed=False)
    assert cases == []
    assert output["summary"]["n_routing_blockers"] == 0

    # Serialization intentionally erases source-bound custody.  Even a digest-valid embedded
    # NOT_APPLICABLE projection cannot re-authorize absence when NRFU is recomputed later.
    embedded = embedded_bgp_configured_peer_baseline(baseline)
    output, cases = _bgp_nrfu_cases(embedded, observed=False)
    assert cases and all(case["evidence_state"] == "not_verified" for case in cases)
    assert output["summary"]["n_routing_blockers"] >= 1


def test_nxos_collection_and_runtime_receipt_prefer_scoped_ipv4_summaries():
    import COLLECT_PARSE_V3_23_0 as pipeline

    scoped = {"show bgp ipv4 unicast summary", "show bgp ip unicast summary"}
    assert scoped <= set(pipeline.COMMANDS_NXOS)
    assert scoped.isdisjoint(pipeline.COMMANDS_IOS)
    assert BGP_IPV4_SUMMARY_COMMANDS[:2] == (
        "show bgp ipv4 unicast summary", "show bgp ip unicast summary",
    )


def test_indeterminate_subject_is_scoped_to_its_own_group(tmp_path):
    bodies = {
        "r1": (
            "router bgp 65001\n neighbor 192.0.2.1 remote-as 65002\nend\n",
            "BGP router identifier 203.0.113.1, local AS number 65001\n"
            "Neighbor V AS MsgRcvd MsgSent TblVer InQ OutQ Up/Down State/PfxRcd\n"
            "192.0.2.1 4 65002 10 11 1 0 0 00:10:00 5\n",
        ),
        "r2": (
            "router bgp 65100\n bgp listen range 198.51.100.0/24 peer-group DYNAMIC\nend\n",
            "BGP router identifier 203.0.113.2, local AS number 65100\n"
            "Neighbor V AS MsgRcvd MsgSent TblVer InQ OutQ Up/Down State/PfxRcd\n",
        ),
    }
    paths = {}
    for host, (config, runtime) in bodies.items():
        config_path = tmp_path / f"{host}-running.txt"
        runtime_path = tmp_path / f"{host}-bgp.txt"
        config_path.write_text(config, encoding="utf-8")
        runtime_path.write_text(runtime, encoding="utf-8")
        paths[host] = {
            "show running-config": str(config_path),
            "show ip bgp summary": str(runtime_path),
        }
    baseline = compute_bgp_configured_peer_baseline(
        paths, compute_capture_integrity_from_paths(paths),
        devices={host: {"platform": "ios"} for host in bodies},
    )
    assert baseline["verdict"] == "INDETERMINATE"
    assert [(row["switch"], row["status"]) for row in baseline["rows"]] == [
        ("r1", "assessed"),
    ]

    groups = [{"switches": ["r1"]}, {"switches": ["r2"]}]
    readiness = compute_migration_readiness(
        {"r1": {}, "r2": {}}, groups,
        [{"switch": host, "band": "Good"} for host in bodies],
        [{"switch": host} for host in bodies], [], [], [],
        {**_dep_map(), "model": {"hosts": ["r1", "r2"]}},
        bgp_configured_peer_baseline=baseline,
    )
    routing = {
        row["switches"][0]: next(check for check in row["checks"]
                                 if check["check"] == "Routing adjacencies up")
        for row in readiness
    }
    assert routing["r1"]["status"] == "pass"
    assert routing["r2"]["status"] == "warn"

    plan = compute_validation_plan(
        {"r1": {}, "r2": {}}, move_groups=groups,
        devices={host: {"platform": "ios"} for host in bodies},
        bgp_configured_peer_baseline=baseline,
    )
    bgp_rows = [row for row in plan["items"] if "BGP configured" in row["check"]]
    assert [(row["device"], row["evidence_state"]) for row in bgp_rows] == [
        ("r1", "assessed"), ("r2", "not_verified"),
    ]

    output = compute_nrfu_commands({
        "devices": {host: {"platform": "ios"} for host in bodies},
        "interfaces": {"r1": {}, "r2": {}}, "move_groups": groups,
        "routing_neighbors": {"r1": {"bgp": []}, "r2": {"bgp": []}},
        "bgp_configured_peer_baseline": baseline,
    })
    nrfu = {
        device["host"]: [case for case in device["cases"]
                         if case.get("evidence_family") == "BGP"]
        for wave in output["waves"] for device in wave["devices"]
    }
    assert nrfu["r1"][0]["evidence_state"] == "assessed"
    assert nrfu["r2"][0]["evidence_state"] == "not_verified"
