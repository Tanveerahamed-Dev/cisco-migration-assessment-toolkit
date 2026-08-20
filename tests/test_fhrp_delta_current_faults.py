"""Current FHRP faults cannot be converted into harmless expected changes."""

from __future__ import annotations

from pathlib import Path

from cisco_toolkit.fhrp_redundancy import (
    compute_fhrp_redundancy_domain_baseline,
)
from cisco_toolkit.protocol_assurance import protocol_family_change_set
from cisco_toolkit.protocol_deltas import (
    compute_fhrp_configured_group_delta,
    compute_fhrp_redundancy_domain_delta,
)
from tests.test_fhrp_configured_group_baseline import IOS_CONFIG, _run
from tests.test_fhrp_redundancy_domain_baseline import _owner


_EMPTY_CONFIG = """\
hostname edge1
interface Vlan10
 ip address 10.0.10.2 255.255.255.0
end
"""
_NO_GROUPS = "No standby groups configured\n"
_IPV4_DELTA = {
    "schema": "protocol_adjacency_delta/1",
    "summary": {"n_preserved": 0},
    "changes": [],
    "coverage_gaps": [],
}


def _expected_effect(delta: dict) -> str:
    change = next(row for row in delta["changes"] if row["transition"] == "appeared")
    composed = protocol_family_change_set(
        _IPV4_DELTA,
        {"expected_changes": [{
            "family": delta["family"],
            "transitions": ["appeared"],
            "subjects": [change["subject"]],
        }]},
        [delta],
    )
    family = next(
        item for item in composed["families"] if item["family"] == delta["family"]
    )
    row = next(item for item in family["changes"] if item["subject"] == change["subject"])
    assert row["expected"] is True
    return row["decision_effect"]


def test_new_degraded_configured_group_blocks_even_when_expected(tmp_path: Path):
    before, *_ = _run(
        tmp_path / "before", config=_EMPTY_CONFIG, runtime=_NO_GROUPS,
    )
    healthy, *_ = _run(tmp_path / "healthy")
    degraded, *_ = _run(
        tmp_path / "degraded", config=IOS_CONFIG, runtime=_NO_GROUPS,
    )

    healthy_delta = compute_fhrp_configured_group_delta(
        {"fhrp_configured_group_baseline": before},
        {"fhrp_configured_group_baseline": healthy},
    )
    healthy_row = next(
        row for row in healthy_delta["changes"] if row["transition"] == "appeared"
    )
    assert healthy_row["decision_effect"] == "review"
    assert _expected_effect(healthy_delta) == "none"

    degraded_delta = compute_fhrp_configured_group_delta(
        {"fhrp_configured_group_baseline": before},
        {"fhrp_configured_group_baseline": degraded},
    )
    degraded_row = next(
        row for row in degraded_delta["changes"] if row["transition"] == "appeared"
    )
    assert degraded_row["after_state"]["status"] == "degraded"
    assert degraded_row["decision_effect"] == "block"
    assert _expected_effect(degraded_delta) == "block"


def _domain_snapshot(path: Path, hosts: dict[str, dict]) -> dict:
    path.mkdir()
    configured, interfaces = _owner(path, hosts)
    return {
        "fhrp_redundancy_domain_baseline":
            compute_fhrp_redundancy_domain_baseline(interfaces, configured),
    }


def test_new_faulted_redundancy_domain_blocks_even_when_expected(tmp_path: Path):
    before = _domain_snapshot(tmp_path / "before", {
        "edge-a": {"ip": "10.0.10.2", "role": "Active", "group": False},
        "edge-b": {"ip": "10.0.10.3", "role": "Standby", "group": False},
    })
    healthy = _domain_snapshot(tmp_path / "healthy", {
        "edge-a": {"ip": "10.0.10.2", "role": "Active"},
        "edge-b": {"ip": "10.0.10.3", "role": "Standby"},
    })
    dual_leader = _domain_snapshot(tmp_path / "dual-leader", {
        "edge-a": {"ip": "10.0.10.2", "role": "Active"},
        "edge-b": {"ip": "10.0.10.3", "role": "Active"},
    })

    healthy_delta = compute_fhrp_redundancy_domain_delta(before, healthy)
    healthy_row = next(
        row for row in healthy_delta["changes"] if row["transition"] == "appeared"
    )
    assert healthy_row["decision_effect"] == "review"
    assert _expected_effect(healthy_delta) == "none"

    fault_delta = compute_fhrp_redundancy_domain_delta(before, dual_leader)
    fault_row = next(
        row for row in fault_delta["changes"] if row["transition"] == "appeared"
    )
    assert fault_row["after_state"]["leader_count"] == 2
    assert fault_row["decision_effect"] == "block"
    assert _expected_effect(fault_delta) == "block"
