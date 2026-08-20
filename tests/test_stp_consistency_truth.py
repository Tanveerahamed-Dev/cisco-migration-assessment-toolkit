"""Receipt-gated STP consistency truth across readiness and Validation."""

from __future__ import annotations

import copy

from cisco_toolkit.analyze import (
    build_dependency_map,
    compute_current_baseline_gate,
    compute_migration_readiness,
    compute_protocol_assessability,
    compute_protocol_health,
    compute_validation_plan,
    summarize_stp_consistency_baseline,
)
from cisco_toolkit.model import InterfaceData


_STP_STATE = """\
VLAN0010
  Spanning tree enabled protocol rstp
  Root ID    Priority    24586
             Address     aaaa.0001.0001
             This bridge is the root
  Bridge ID  Priority    24586
             Address     aaaa.0001.0001
Interface        Role Sts Cost      Prio.Nbr Type
Gi1/0/1          Desg FWD 4         128.1    P2p
"""


def _capture(tmp_path, name: str, body: str) -> str:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return str(path)


def _stp_run(tmp_path, *, inconsistent: str | None,
             blocked: str | None = None,
             topology: str | None = None) -> tuple[dict, list, dict]:
    ifaces = {
        "sw1": {
            "Gi1/0/1": InterfaceData(
                port="Gi1/0/1", switchport_mode="Access", vlan="10"
            )
        }
    }
    commands = {"sw1": {"show spanning-tree": _capture(tmp_path, "state.txt", _STP_STATE)}}
    if blocked is not None:
        commands["sw1"]["show spanning-tree blockedports"] = _capture(
            tmp_path, "blocked.txt", blocked
        )
    if inconsistent is not None:
        commands["sw1"]["show spanning-tree inconsistentports"] = _capture(
            tmp_path, "inconsistent.txt", inconsistent
        )
    if topology is not None:
        commands["sw1"]["show spanning-tree detail"] = _capture(
            tmp_path, "topology.txt", topology
        )
    health = compute_protocol_health(ifaces, commands)
    receipt = compute_protocol_assessability(["sw1"], ifaces, commands, health)
    return ifaces, health, receipt


def _stp_receipt_row(receipt: dict) -> dict:
    return next(row for row in receipt["rows"] if row["protocol"] == "STP")


def _readiness(ifaces: dict, health, receipt=..., stp_roots=...) -> tuple[dict, dict]:
    kwargs = {} if receipt is ... else {"protocol_assessability": receipt}
    if stp_roots is not ...:
        kwargs["stp_roots"] = stp_roots
    result = compute_migration_readiness(
        ifaces,
        [{"group": "G", "switches": ["sw1"]}],
        [{"switch": "sw1", "band": "Good"}],
        [],
        [],
        [],
        health,
        build_dependency_map(ifaces, [], []),
        **kwargs,
    )[0]
    return result, {row["check"]: row for row in result["checks"]}


def test_claim_specific_clean_baseline_ignores_blocked_and_optional_detail(tmp_path):
    ifaces, health, receipt = _stp_run(
        tmp_path, inconsistent="No inconsistent ports observed\n"
    )
    receipt_row = _stp_receipt_row(receipt)
    assert receipt_row["state"] == "partial"
    assert receipt_row["input_states"] == {
        "state": "usable",
        "blocked_ports": "missing",
        "inconsistent_ports": "usable",
        "topology_changes": "missing",
    }

    # The owner consumes the structured severity/detail relation, never numeric-looking summary prose.
    health[0]["summary"] = "untrusted prose claims 999 inconsistent ports"
    baseline = summarize_stp_consistency_baseline(
        health, receipt, all_interfaces=ifaces
    )
    row = baseline["rows"][0]
    assert row["status"] == "assessed"
    assert row["input_states"]["blocked_ports"] == "missing"
    assert row["input_states"]["topology_changes"] == "missing"
    assert row["blocked_ports_state"] == "missing"
    assert row["topology_changes_state"] == "missing"
    assert row["availability_disclosure"] == (
        "Blocked-port capture: not collected; no blocked-port count is claimed. "
        "Optional topology-change capture: not collected; no topology-change count is claimed."
    )
    assert row["acceptance"].endswith(row["availability_disclosure"])
    assert row["note"].endswith(row["availability_disclosure"])
    assert row["command"] == "show spanning-tree inconsistentports"
    assert row["projection_custody"] == "embedded_unverified"
    assert "interfaces.sw1" in row["source_key"]

    readiness, checks = _readiness(ifaces, health, receipt)
    assert readiness["readiness"] == "READY"
    assert checks["STP consistency"]["status"] == "pass"
    assert "bounded current-run" in checks["STP consistency"]["note"]


def test_missing_inconsistent_evidence_is_caution_and_typed_validation_blocker(tmp_path):
    ifaces, health, receipt = _stp_run(tmp_path, inconsistent=None)
    row = summarize_stp_consistency_baseline(
        health, receipt, all_interfaces=ifaces
    )["rows"][0]
    assert row["status"] == "review"
    assert row["acceptance"].startswith("PRE-CUTOVER REVIEW — BLOCKER:")
    assert {item["code"] for item in row["findings"]} == {"claim_prerequisite_partial"}

    readiness, checks = _readiness(ifaces, health, receipt)
    assert readiness["readiness"] == "CAUTION"
    assert checks["STP consistency"]["status"] == "warn"
    assert "not verified" in checks["STP consistency"]["note"]

    plan = compute_validation_plan(
        ifaces, protocol_health=health, protocol_assessability=receipt
    )
    stp_items = [item for item in plan["items"] if item["category"] == "STP"]
    assert len(stp_items) == 1
    assert stp_items[0]["evidence_state"] == "review"
    assert stp_items[0]["expect"].startswith("PRE-CUTOVER REVIEW — BLOCKER:")
    assert stp_items[0]["source_key"] == row["source_key"]
    gate = compute_current_baseline_gate(plan)
    assert gate["verdict"] == "INDETERMINATE"
    assert gate["summary"]["by_state"]["review"] == 1


def test_availability_disclosure_maps_capture_states_to_operator_vocabulary(tmp_path):
    ifaces, health, receipt = _stp_run(
        tmp_path,
        inconsistent="No inconsistent ports observed\n",
        blocked="No blocked ports observed\n",
        topology="Number of topology changes 2 last change occurred 00:01:00 ago\n",
    )
    row = summarize_stp_consistency_baseline(
        health, receipt, all_interfaces=ifaces
    )["rows"][0]
    assert row["availability_disclosure"] == (
        "Blocked-port capture: observed; no blocked-port count is claimed. "
        "Optional topology-change capture: observed; no topology-change count is claimed."
    )

    ifaces, health, receipt = _stp_run(
        tmp_path,
        inconsistent="No inconsistent ports observed\n",
        blocked="\n",
        topology="% Invalid input detected at '^' marker.\n",
    )
    row = summarize_stp_consistency_baseline(
        health, receipt, all_interfaces=ifaces
    )["rows"][0]
    assert "Blocked-port capture: captured empty" in row["availability_disclosure"]
    assert "Optional topology-change capture: capture error" in row["availability_disclosure"]


def test_high_with_usable_inconsistent_evidence_stays_degraded_when_blocked_missing(tmp_path):
    ifaces, health, receipt = _stp_run(tmp_path, inconsistent="Gi1/0/7\n")
    assert health[0]["severity"] == "High" and health[0]["detail"]
    assert _stp_receipt_row(receipt)["state"] == "partial"
    row = summarize_stp_consistency_baseline(
        health, receipt, all_interfaces=ifaces
    )["rows"][0]
    assert row["status"] == "degraded"
    assert row["input_states"]["blocked_ports"] == "missing"
    assert row["acceptance"].startswith("PRE-CUTOVER DEGRADED — BLOCKER:")
    assert row["acceptance"].endswith(row["availability_disclosure"])
    assert row["note"].endswith(row["availability_disclosure"])
    assert "Blocked-port capture: not collected; no blocked-port count is claimed." in row["acceptance"]
    assert "Optional topology-change capture: not collected" in row["note"]

    readiness, checks = _readiness(ifaces, health, receipt)
    assert readiness["readiness"] == "CAUTION"
    assert checks["STP consistency"]["status"] == "warn"
    plan = compute_validation_plan(
        ifaces, protocol_health=health, protocol_assessability=receipt
    )
    assert compute_current_baseline_gate(plan)["verdict"] == "BLOCKED"


def test_health_row_reconciliation_requires_exactly_one_canonical_row(tmp_path):
    ifaces, health, receipt = _stp_run(
        tmp_path, inconsistent="No inconsistent ports observed\n"
    )

    duplicate = health + [copy.deepcopy(health[0])]
    duplicate_row = summarize_stp_consistency_baseline(
        duplicate, receipt, all_interfaces=ifaces
    )["rows"][0]
    assert duplicate_row["status"] == "review"
    assert "duplicate_health_rows" in {item["code"] for item in duplicate_row["findings"]}

    forged_info = copy.deepcopy(health)
    forged_info[0]["detail"] = "inconsistent: Gi1/0/7"
    assert summarize_stp_consistency_baseline(
        forged_info, receipt, all_interfaces=ifaces
    )["rows"][0]["status"] == "review"

    high, high_receipt = copy.deepcopy(health), copy.deepcopy(receipt)
    high[0]["severity"] = "High"
    # Receipt reconciliation covers row emission, not severity; High + empty detail is still malformed.
    assert summarize_stp_consistency_baseline(
        high, high_receipt, all_interfaces=ifaces
    )["rows"][0]["status"] == "review"

    invalid_receipt = copy.deepcopy(receipt)
    invalid_receipt["summary"]["n_health_rows"] += 1
    invalid_row = summarize_stp_consistency_baseline(
        health, invalid_receipt, all_interfaces=ifaces
    )["rows"][0]
    assert invalid_row["status"] == "review"
    assert invalid_row["findings"][0]["code"] == "receipt_invalid"


def test_subject_guard_uses_positive_l2_and_roots_but_excludes_bare_inventory():
    hosts = ["access", "dynamic", "live", "per-vlan", "root", "bare"]
    receipt = compute_protocol_assessability(hosts, {}, {}, [])
    ifaces = {
        "access": {"Gi1": InterfaceData(port="Gi1", switchport_mode="access")},
        "dynamic": {"Gi1": InterfaceData(port="Gi1", switchport_mode="dynamic trunk")},
        "live": {"Gi1": InterfaceData(port="Gi1", trunk_status="trnk-bndl")},
        "per-vlan": {"Gi1": InterfaceData(port="Gi1", stp_other_vlans="10")},
        "bare": {
            "Gi1": InterfaceData(
                port="Gi1", cdp_neighbor="peer", port_channel="Po1", endpoint_type="Switch"
            ),
            "Vlan10": InterfaceData(port="Vlan10", svi_ip="10.0.10.1"),
        },
    }
    baseline = summarize_stp_consistency_baseline(
        [], receipt, all_interfaces=ifaces,
        stp_roots={"root": {"10": {"is_root": True}}},
    )
    assert {row["switch"] for row in baseline["rows"]} == {
        "access", "dynamic", "live", "per-vlan", "root"
    }
    assert {row["status"] for row in baseline["rows"]} == {"not_verified"}
    assert "stp_roots.root" in next(
        row["source_key"] for row in baseline["rows"] if row["switch"] == "root"
    )


def test_no_stp_subject_is_neutral_and_omitted_receipt_preserves_legacy_path():
    ifaces = {"sw1": {"Gi1": InterfaceData(port="Gi1")}}
    receipt = compute_protocol_assessability(["sw1"], ifaces, {}, [])
    baseline = summarize_stp_consistency_baseline([], receipt, all_interfaces=ifaces)
    assert baseline["rows"] == []
    assert baseline["summary"]["n_subjects"] == 0

    current, current_checks = _readiness(ifaces, [], receipt)
    assert current["readiness"] == "READY"
    assert current_checks["STP consistency"]["status"] == "info"
    assert "no STP consistency health claim" in current_checks["STP consistency"]["note"]

    legacy, legacy_checks = _readiness(ifaces, [])
    assert legacy["readiness"] == "READY"
    assert legacy_checks["STP consistency"]["status"] == "info"
    assert "NOT ASSESSABLE" in legacy_checks["STP consistency"]["note"]


def test_missing_receipt_never_promotes_a_clean_health_row(tmp_path):
    ifaces, health, _receipt = _stp_run(
        tmp_path, inconsistent="No inconsistent ports observed\n"
    )
    row = summarize_stp_consistency_baseline(
        health, None, all_interfaces=ifaces
    )["rows"][0]
    assert row["status"] == "not_verified"
    assert row["acceptance"].startswith(
        "STP CONSISTENCY BASELINE NOT VERIFIED — BLOCKER:"
    )
    assert "Blocked-port capture: not verified" in row["acceptance"]
    assert row["note"].endswith(row["availability_disclosure"])
    readiness, checks = _readiness(ifaces, health, None)
    assert readiness["readiness"] == "CAUTION"
    assert checks["STP consistency"]["status"] == "warn"


def test_readiness_is_total_and_fails_closed_for_malformed_protocol_health(tmp_path):
    ifaces, health, receipt = _stp_run(
        tmp_path, inconsistent="No inconsistent ports observed\n"
    )
    malformed_stp = copy.deepcopy(health)
    malformed_stp[0]["detail"] = "forged inconsistent detail on an Info row"
    cases = (
        health[0],                 # mapping root instead of the required list
        None,                      # explicitly missing phase output
        [None, "not a row"],      # malformed list members
        [{"switch": {}, "protocol": "STP", "severity": "High",
          "summary": "malformed identity", "detail": "Gi1/0/1"}],
        malformed_stp,            # attributable but non-canonical STP row
    )
    for protocol_health in cases:
        readiness, checks = _readiness(ifaces, protocol_health, receipt)
        assert readiness["readiness"] == "CAUTION"
        assert checks["STP consistency"]["status"] == "warn"
        assert "not verified" in checks["STP consistency"]["note"]


def test_root_only_subject_has_readiness_and_validation_parity():
    ifaces = {"sw1": {"Gi1": InterfaceData(port="Gi1")}}
    receipt = compute_protocol_assessability(["sw1"], ifaces, {}, [])
    roots = {"sw1": {"10": {"is_root": True, "root_priority": "24576"}}}

    owner = summarize_stp_consistency_baseline(
        [], receipt, all_interfaces=ifaces, stp_roots=roots
    )
    assert len(owner["rows"]) == 1
    assert owner["rows"][0]["status"] == "not_verified"
    assert owner["rows"][0]["subject_evidence"] == ["stp_roots"]

    readiness, checks = _readiness(ifaces, [], receipt, roots)
    assert readiness["readiness"] == "CAUTION"
    assert checks["STP consistency"]["status"] == "warn"

    plan = compute_validation_plan(
        ifaces, stp_roots=roots, protocol_health=[], protocol_assessability=receipt
    )
    consistency = [
        item for item in plan["items"]
        if item["check"] == "STP consistency baseline not verified"
    ]
    assert len(consistency) == 1
    assert consistency[0]["evidence_state"] == "not_verified"
    assert compute_current_baseline_gate(plan)["verdict"] == "INDETERMINATE"
