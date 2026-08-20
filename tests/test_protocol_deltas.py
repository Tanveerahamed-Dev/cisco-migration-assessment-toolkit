"""Decision-grade, verdict-free native protocol delta contracts."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from cisco_toolkit.analyze import summarize_etherchannel_baseline
from cisco_toolkit.fhrp_redundancy import compute_fhrp_redundancy_domain_baseline
from cisco_toolkit.protocol_assurance import CHANGE_VOCABULARY
from cisco_toolkit.protocol_deltas import (
    BGP_CONFIGURED_PEER_DELTA_SCHEMA,
    ETHERCHANNEL_DELTA_SCHEMA,
    FHRP_CONFIGURED_GROUP_DELTA_SCHEMA,
    FHRP_REDUNDANCY_DOMAIN_DELTA_SCHEMA,
    IPV6_ROUTING_ADJACENCY_DELTA_SCHEMA,
    STP_CONSISTENCY_DELTA_SCHEMA,
    STP_TOPOLOGY_DELTA_SCHEMA,
    VTP_SAFETY_DELTA_SCHEMA,
    compute_bgp_configured_peer_delta,
    compute_etherchannel_delta,
    compute_fhrp_configured_group_delta,
    compute_fhrp_redundancy_domain_delta,
    compute_ipv6_routing_adjacency_delta,
    compute_stp_consistency_delta,
    compute_stp_topology_delta,
    compute_vtp_safety_delta,
)
from tests.test_bgp_configured_peer_baseline import (
    EMPTY_IOS_SUMMARY,
    _run as bgp_owner,
)
from tests.test_etherchannel_cutover_truth import (
    _project as etherchannel_projection,
    _receipt as protocol_receipt,
)
from tests.test_fhrp_configured_group_baseline import (
    HSRP_HEADER,
    _run as configured_fhrp_owner,
)
from tests.test_fhrp_redundancy_domain_baseline import _owner as fhrp_domain_sources
from tests.test_ipv6_routing_adjacency_baseline import (
    _bgp as bgpv6_capture,
    _ospf as ospfv3_capture,
    _owner as ipv6_owner,
    _route as ipv6_route_capture,
)
from tests.test_stp_consistency_truth import _stp_run
from tests.test_vtp_safety_baseline import _owner as vtp_owner, _status as vtp_status


GOLDEN_PATH = Path(__file__).parent / "golden" / "snapshot.json"

COMPUTERS = (
    (compute_ipv6_routing_adjacency_delta, IPV6_ROUTING_ADJACENCY_DELTA_SCHEMA),
    (compute_bgp_configured_peer_delta, BGP_CONFIGURED_PEER_DELTA_SCHEMA),
    (compute_stp_consistency_delta, STP_CONSISTENCY_DELTA_SCHEMA),
    (compute_stp_topology_delta, STP_TOPOLOGY_DELTA_SCHEMA),
    (compute_etherchannel_delta, ETHERCHANNEL_DELTA_SCHEMA),
    (compute_vtp_safety_delta, VTP_SAFETY_DELTA_SCHEMA),
    (compute_fhrp_configured_group_delta, FHRP_CONFIGURED_GROUP_DELTA_SCHEMA),
    (compute_fhrp_redundancy_domain_delta, FHRP_REDUNDANCY_DOMAIN_DELTA_SCHEMA),
)


def _golden() -> dict:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def _only(result: dict, transition: str) -> dict:
    return next(row for row in result["changes"] if row["transition"] == transition)


@pytest.mark.parametrize(("computer", "schema"), COMPUTERS)
def test_every_native_owner_has_one_closed_verdict_free_shape(computer, schema):
    result = computer(_golden(), _golden())

    assert result["schema"] == schema
    assert result["owner"] == schema
    assert result["owns_score"] is result["owns_verdict"] is False
    assert "score" not in result and "verdict" not in result and "gate" not in result
    assert tuple(result["summary"]["by_transition"]) == CHANGE_VOCABULARY
    assert set(result["summary"]["by_decision_effect"]) == {
        "block", "review", "none", "not_verified",
    }
    assert result["summary"]["n_subjects"] == len(result["changes"])
    assert all(row["family"] == result["family"] for row in result["changes"])
    assert all(row["transition"] in CHANGE_VOCABULARY for row in result["changes"])
    assert all(row["decision_effect"] in {
        "block", "review", "none", "not_verified",
    } for row in result["changes"])
    json.dumps(result, allow_nan=False)


def test_real_golden_baselines_preserve_faults_and_missing_capture_honestly():
    snap = _golden()

    ipv6 = compute_ipv6_routing_adjacency_delta(snap, snap)
    assert ipv6["summary"]["by_transition"]["unchanged_degraded"] == 2
    assert ipv6["summary"]["by_decision_effect"]["block"] == 2
    assert ipv6["summary"]["by_transition"]["coverage_lost"] > 0

    assert compute_bgp_configured_peer_delta(snap, snap)["summary"]["by_transition"][
        "coverage_lost"] == 3
    assert compute_stp_consistency_delta(snap, snap)["summary"]["by_transition"][
        "coverage_lost"] == 3
    assert compute_stp_topology_delta(snap, snap)["summary"]["by_transition"][
        "coverage_lost"] >= 2
    assert compute_vtp_safety_delta(snap, snap)["summary"]["by_transition"][
        "coverage_lost"] == 3
    assert compute_fhrp_redundancy_domain_delta(snap, snap)["summary"]["by_transition"][
        "coverage_lost"] == 2

    assert compute_etherchannel_delta(snap, snap)["summary"]["by_transition"][
        "unchanged_healthy"] == 2
    assert compute_fhrp_configured_group_delta(snap, snap)["summary"]["by_transition"][
        "unchanged_healthy"] == 4


@pytest.mark.parametrize(("computer", "_schema"), COMPUTERS)
@pytest.mark.parametrize("malformed", (None, [], "truncated", 7))
def test_malformed_or_missing_roots_are_total_and_never_healthy(computer, _schema, malformed):
    result = computer(malformed, malformed)

    assert result["assessed"] is False
    assert result["summary"]["by_transition"]["unchanged_healthy"] == 0
    assert (
        result["summary"]["by_transition"]["not_comparable"]
        + result["summary"]["by_transition"]["coverage_lost"]
    ) >= 1
    assert set(row["decision_effect"] for row in result["changes"]) == {"not_verified"}


@pytest.mark.parametrize(
    ("computer", "mutator"),
    (
        (compute_ipv6_routing_adjacency_delta,
         lambda snap: snap["ipv6_routing_adjacency_baseline"].__setitem__("schema", "renamed/1")),
        (compute_bgp_configured_peer_delta,
         lambda snap: snap["bgp_configured_peer_baseline"]["summary"].__setitem__("baseline_sha256", "0" * 64)),
        (compute_vtp_safety_delta,
         lambda snap: snap["vtp_safety_baseline"].__setitem__("rows", "truncated")),
        (compute_fhrp_configured_group_delta,
         lambda snap: snap["fhrp_configured_group_baseline"].__setitem__("schema", "renamed/1")),
        (compute_fhrp_redundancy_domain_delta,
         lambda snap: snap["fhrp_redundancy_domain_baseline"]["summary"].__setitem__("baseline_sha256", "bad")),
        (compute_etherchannel_delta,
         lambda snap: snap["etherchannel_projection"].__setitem__("rows", "truncated")),
        (compute_stp_consistency_delta,
         lambda snap: snap["protocol_assessability"].__setitem__("rows", "truncated")),
        (compute_stp_topology_delta,
         lambda snap: snap.__setitem__("stp_roots", ["truncated"])),
    ),
)
def test_required_leaf_mutations_cannot_restore_a_healthy_comparison(computer, mutator):
    before, after = _golden(), _golden()
    mutator(after)

    result = computer(before, after)

    assert result["assessed"] is False
    assert result["summary"]["by_transition"]["unchanged_healthy"] == 0
    assert (
        result["summary"]["by_transition"]["not_comparable"]
        + result["summary"]["by_transition"]["coverage_lost"]
    ) >= 1


def test_ipv6_known_state_regression_uses_validated_real_parser_output(tmp_path):
    _paths, before = ipv6_owner(tmp_path / "before", {
        "show ipv6 route summary": ipv6_route_capture(),
        "show ospfv3 neighbor": ospfv3_capture(("10.0.0.9", "FULL/DR", "Vlan10")),
        "show bgp ipv6 unicast summary": bgpv6_capture(("2001:db8::9", "65009", "4")),
    })
    _paths, after = ipv6_owner(tmp_path / "after", {
        "show ipv6 route summary": ipv6_route_capture(),
        "show ospfv3 neighbor": ospfv3_capture(("10.0.0.9", "EXSTART/-", "Vlan10")),
        "show bgp ipv6 unicast summary": bgpv6_capture(("2001:db8::9", "65009", "4")),
    })

    result = compute_ipv6_routing_adjacency_delta(
        {"ipv6_routing_adjacency_baseline": before},
        {"ipv6_routing_adjacency_baseline": after},
    )

    row = _only(result, "regressed")
    assert row["decision_effect"] == "block"
    assert row["before_state"]["state"] == "FULL"
    assert row["after_state"]["state"] == "EXSTART"


def test_configured_bgp_disappearance_blocks_but_capture_loss_abstains(tmp_path):
    for name in ("before", "removed", "missing"):
        (tmp_path / name).mkdir()
    before, *_ = bgp_owner(tmp_path / "before")
    after, *_ = bgp_owner(
        tmp_path / "removed",
        config="version 17.9\nrouter bgp 65001\nend\n",
        runtime=EMPTY_IOS_SUMMARY,
    )
    removed = compute_bgp_configured_peer_delta(
        {"bgp_configured_peer_baseline": before},
        {"bgp_configured_peer_baseline": after},
    )
    row = _only(removed, "disappeared")
    assert row["decision_effect"] == "block"
    assert "configured-active" in row["note"]

    unavailable, *_ = bgp_owner(
        tmp_path / "missing", include_config=False, runtime=EMPTY_IOS_SUMMARY,
    )
    lost = compute_bgp_configured_peer_delta(
        {"bgp_configured_peer_baseline": before},
        {"bgp_configured_peer_baseline": unavailable},
    )
    assert not any(row["transition"] == "disappeared" for row in lost["changes"])
    assert _only(lost, "coverage_lost")["decision_effect"] == "not_verified"


def test_vtp_movement_defaults_review_and_matching_high_revision_still_blocks(tmp_path):
    low, *_ = vtp_owner(tmp_path / "low", vtp_status(revision=4))
    moved, *_ = vtp_owner(tmp_path / "moved", vtp_status(revision=5))
    movement = compute_vtp_safety_delta(
        {"vtp_safety_baseline": low}, {"vtp_safety_baseline": moved})
    row = _only(movement, "intent_changed")
    assert row["decision_effect"] == "review"
    assert row["before_state"]["revision"] == 4
    assert row["after_state"]["revision"] == 5

    high, *_ = vtp_owner(tmp_path / "high", vtp_status(revision=100))
    unchanged = compute_vtp_safety_delta(
        {"vtp_safety_baseline": high}, {"vtp_safety_baseline": high})
    row = _only(unchanged, "unchanged_degraded")
    assert row["decision_effect"] == "block"
    assert "not acceptance" in row["note"].lower()


def test_stp_consistency_and_topology_regressions_are_distinct(tmp_path):
    (tmp_path / "before").mkdir()
    (tmp_path / "after").mkdir()
    before_ifaces, before_health, before_receipt = _stp_run(
        tmp_path / "before", inconsistent="No inconsistent ports observed\n")
    after_ifaces, after_health, after_receipt = _stp_run(
        tmp_path / "after", inconsistent="Gi1/0/7\n")
    consistency = compute_stp_consistency_delta(
        {"interfaces": before_ifaces, "protocol_health": before_health,
         "protocol_assessability": before_receipt, "stp_roots": {}},
        {"interfaces": after_ifaces, "protocol_health": after_health,
         "protocol_assessability": after_receipt, "stp_roots": {}},
    )
    assert _only(consistency, "regressed")["decision_effect"] == "block"

    before = {
        "stp_roots": {"sw1": {"10": {
            "is_mst": False, "is_root": True, "root_address": "aaaa.0001.0001",
            "root_priority": 24586, "bridge_priority": 24586,
        }}},
        "interfaces": {"sw1": {"Gi1/0/1": {
            "stp_fwd_vlans": "10", "stp_blk_vlans": None,
        }}},
    }
    after = deepcopy(before)
    after["interfaces"]["sw1"]["Gi1/0/1"]["stp_fwd_vlans"] = None
    after["interfaces"]["sw1"]["Gi1/0/1"]["stp_blk_vlans"] = "10"
    topology = compute_stp_topology_delta(before, after)
    assert _only(topology, "regressed")["decision_effect"] == "block"
    coverage = [row for row in topology["changes"] if row["transition"] == "coverage_lost"]
    assert {row["subject"].rsplit("|", 1)[-1] for row in coverage} >= {
        "port_roles", "topology_change_counters",
    }
    assert topology["assurance_level"] == "not_verified"


def _ether_snapshot(tmp_path: Path, body: str) -> dict:
    tmp_path.mkdir()
    projection, _interfaces, _commands = etherchannel_projection(tmp_path, "dist1", body)
    receipt = protocol_receipt({"dist1": {"EtherChannel": "assessed"}})
    baseline = summarize_etherchannel_baseline(projection, receipt)
    return {
        "etherchannel_projection": projection,
        "protocol_assessability": receipt,
        "etherchannel_baseline": baseline,
    }


def test_etherchannel_compares_local_capacity_without_inventing_partner_or_hash(tmp_path):
    before = _ether_snapshot(
        tmp_path / "before",
        "Group Port-channel Protocol Ports\n"
        "1 Po1(SU) LACP Gi1/0/1(P) Gi1/0/2(P)\n",
    )
    after = _ether_snapshot(
        tmp_path / "after",
        "Group Port-channel Protocol Ports\n1 Po1(SU) LACP Gi1/0/1(P)\n",
    )

    result = compute_etherchannel_delta(before, after)

    row = _only(result, "regressed")
    assert row["decision_effect"] == "block"
    assert row["before_state"]["forwarding_capacity_units"] == 2
    assert row["after_state"]["forwarding_capacity_units"] == 1
    rendered = json.dumps(result).lower()
    assert "partner identity" in rendered and "not inferred" in rendered
    assert "min-links" in rendered and "hashing" in rendered


def test_fhrp_local_role_movement_is_review_not_regression(tmp_path):
    before, *_ = configured_fhrp_owner(tmp_path / "before")
    standby = HSRP_HEADER + (
        "Vl10        10   110 P Standby  10.0.10.3      local           10.0.10.1\n"
    )
    after, *_ = configured_fhrp_owner(tmp_path / "after", runtime=standby)

    result = compute_fhrp_configured_group_delta(
        {"fhrp_configured_group_baseline": before},
        {"fhrp_configured_group_baseline": after},
    )

    row = _only(result, "intent_changed")
    assert row["decision_effect"] == "review"
    assert row["before_state"]["runtime_state"] == "ACTIVE"
    assert row["after_state"]["runtime_state"] == "STANDBY"


def _domain_snapshot(tmp_path: Path, hosts: dict[str, dict]) -> dict:
    tmp_path.mkdir()
    configured, interfaces = fhrp_domain_sources(tmp_path, hosts)
    return {
        "fhrp_redundancy_domain_baseline":
            compute_fhrp_redundancy_domain_baseline(interfaces, configured),
    }


def test_fhrp_domain_role_swap_survives_but_multiple_leaders_regresses(tmp_path):
    before = _domain_snapshot(tmp_path / "before", {
        "edge-a": {"ip": "10.0.10.2", "role": "Active"},
        "edge-b": {"ip": "10.0.10.3", "role": "Standby"},
    })
    swapped = _domain_snapshot(tmp_path / "swapped", {
        "edge-a": {"ip": "10.0.10.2", "role": "Standby"},
        "edge-b": {"ip": "10.0.10.3", "role": "Active"},
    })
    movement = compute_fhrp_redundancy_domain_delta(before, swapped)
    row = _only(movement, "intent_changed")
    assert row["decision_effect"] == "review"
    assert movement["summary"]["by_transition"]["regressed"] == 0

    dual_active = _domain_snapshot(tmp_path / "dual", {
        "edge-a": {"ip": "10.0.10.2", "role": "Active"},
        "edge-b": {"ip": "10.0.10.3", "role": "Active"},
    })
    regression = compute_fhrp_redundancy_domain_delta(before, dual_active)
    row = _only(regression, "regressed")
    assert row["decision_effect"] == "block"
    assert row["after_state"]["leader_count"] == 2

    unchanged_fault = compute_fhrp_redundancy_domain_delta(dual_active, dual_active)
    row = _only(unchanged_fault, "unchanged_degraded")
    assert row["decision_effect"] == "block"
    assert row["after_state"]["leader_count"] == 2
