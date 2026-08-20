"""Decision-grade, verdict-free native protocol delta contracts."""

from __future__ import annotations

from copy import deepcopy
import dataclasses
import json
from pathlib import Path

import pytest

from cisco_toolkit.analyze import summarize_etherchannel_baseline
from cisco_toolkit.bgp_intent import compute_bgp_configured_peer_baseline
from cisco_toolkit.fhrp_redundancy import compute_fhrp_redundancy_domain_baseline
from cisco_toolkit.ipv6_routing import compute_ipv6_routing_adjacency_baseline
from cisco_toolkit.protocol_assurance import (
    CHANGE_VOCABULARY,
    OFFLINE_FILE_SOURCE,
    bind_snapshot_json_bytes,
    bound_snapshot_source,
    compute_native_protocol_deltas,
)
from cisco_toolkit.comparison import compare_bound_pair
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
from cisco_toolkit.vtp_safety import compute_vtp_safety_baseline
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


def _bound_delta(computer, before: dict, after: dict) -> dict:
    bound_before, before_binding = _bind_snapshot(before)
    bound_after, after_binding = _bind_snapshot(after)
    return computer(
        bound_before,
        bound_after,
        comparison_source_binding={
            "before": before_binding,
            "after": after_binding,
        },
    )


def _bind_snapshot(value: dict) -> tuple[dict, dict]:
    raw = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
        default=lambda item: dataclasses.asdict(item)
        if dataclasses.is_dataclass(item) else str(item),
    ).encode("utf-8")
    snapshot = bind_snapshot_json_bytes(raw)
    return snapshot, {
        "sha256": bound_snapshot_source(snapshot)["sha256"],
        "bytes": len(raw),
    }


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

    ipv6 = _bound_delta(compute_ipv6_routing_adjacency_delta, snap, snap)
    assert ipv6["summary"]["by_transition"]["unchanged_degraded"] == 2
    assert ipv6["summary"]["by_decision_effect"]["block"] == 2
    assert ipv6["summary"]["by_transition"]["coverage_lost"] > 0

    assert _bound_delta(compute_bgp_configured_peer_delta, snap, snap)["summary"]["by_transition"][
        "coverage_lost"] == 3
    assert _bound_delta(compute_stp_consistency_delta, snap, snap)["summary"]["by_transition"][
        "coverage_lost"] == 3
    assert _bound_delta(compute_stp_topology_delta, snap, snap)["summary"]["by_transition"][
        "coverage_lost"] >= 2
    assert _bound_delta(compute_vtp_safety_delta, snap, snap)["summary"]["by_transition"][
        "coverage_lost"] == 3
    fhrp_domains = _bound_delta(compute_fhrp_redundancy_domain_delta, snap, snap)
    assert fhrp_domains["summary"]["by_transition"]["not_comparable"] == 1
    assert fhrp_domains["summary"]["by_decision_effect"]["not_verified"] == 1

    assert _bound_delta(compute_etherchannel_delta, snap, snap)["summary"]["by_transition"][
        "unchanged_healthy"] == 2
    fhrp_groups = _bound_delta(compute_fhrp_configured_group_delta, snap, snap)
    assert fhrp_groups["summary"]["by_transition"]["not_comparable"] == 1
    assert fhrp_groups["summary"]["by_decision_effect"]["not_verified"] == 1


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

    result = _bound_delta(computer, before, after)

    assert result["assessed"] is False
    assert result["summary"]["by_transition"]["unchanged_healthy"] == 0
    assert (
        result["summary"]["by_transition"]["not_comparable"]
        + result["summary"]["by_transition"]["coverage_lost"]
    ) >= 1


def test_json_round_trip_or_caller_hash_cannot_self_authorize_native_custody(tmp_path):
    current, *_ = bgp_owner(tmp_path)
    embedded = json.loads(json.dumps(current, allow_nan=False))
    plain = {"bgp_configured_peer_baseline": embedded}
    forged_binding = {
        "before": {"sha256": "sha256:" + "1" * 64},
        "after": {"sha256": "sha256:" + "2" * 64},
    }

    result = compute_bgp_configured_peer_delta(
        plain,
        plain,
        comparison_source_binding=forged_binding,
    )

    assert result["assessed"] is False
    assert result["assurance_level"] == "not_verified"
    assert result["summary"]["by_transition"]["unchanged_healthy"] == 0
    assert result["summary"]["by_transition"]["not_comparable"] == 1
    assert all(
        receipt["source_bound"] is False
        and receipt["comparison_source_bound"] is False
        for receipt in result["source_receipts"].values()
    )


def test_exact_byte_bound_snapshot_authorizes_only_its_matching_digest(tmp_path):
    current, *_ = bgp_owner(tmp_path)
    plain = {"bgp_configured_peer_baseline": json.loads(json.dumps(current))}
    raw = json.dumps(
        plain,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    before = bind_snapshot_json_bytes(raw)
    after = bind_snapshot_json_bytes(raw)
    digest = bound_snapshot_source(before)["sha256"]
    matching = {
        "before": {"sha256": digest},
        "after": {"sha256": digest},
    }

    authorized = compute_bgp_configured_peer_delta(
        before,
        after,
        comparison_source_binding=matching,
    )
    assert authorized["summary"]["by_transition"]["unchanged_healthy"] == 1
    assert all(
        receipt["source_bound"] is False
        and receipt["comparison_source_bound"] is True
        and receipt["comparison_source_basis"]
        == "exact_snapshot_bytes_and_validated_owner_projection"
        for receipt in authorized["source_receipts"].values()
    )

    mismatched = compute_bgp_configured_peer_delta(
        before,
        after,
        comparison_source_binding={
            "before": {"sha256": "sha256:" + "a" * 64},
            "after": {"sha256": "sha256:" + "b" * 64},
        },
    )
    assert mismatched["summary"]["by_transition"]["not_comparable"] == 1
    assert mismatched["summary"]["by_transition"]["unchanged_healthy"] == 0


def test_bound_baseline_to_unbound_after_is_coverage_loss(tmp_path):
    current, *_ = bgp_owner(tmp_path)
    plain = {"bgp_configured_peer_baseline": json.loads(json.dumps(current))}
    raw = json.dumps(
        plain,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    before = bind_snapshot_json_bytes(raw)
    digest = bound_snapshot_source(before)["sha256"]

    result = compute_bgp_configured_peer_delta(
        before,
        plain,
        comparison_source_binding={
            "before": {"sha256": digest},
            "after": {"sha256": digest},
        },
    )

    assert result["summary"]["by_transition"]["coverage_lost"] == 1
    assert result["summary"]["by_transition"]["unchanged_healthy"] == 0
    assert _only(result, "coverage_lost")["decision_effect"] == "not_verified"


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
    consistency = _bound_delta(
        compute_stp_consistency_delta,
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
    topology = _bound_delta(compute_stp_topology_delta, before, after)
    assert _only(topology, "regressed")["decision_effect"] == "block"
    coverage = [row for row in topology["changes"] if row["transition"] == "coverage_lost"]
    assert {row["subject"].rsplit("|", 1)[-1] for row in coverage} >= {
        "port_roles", "topology_change_counters",
    }
    assert topology["assurance_level"] == "not_verified"


def _stp_topology_path(*, forwarding: str | None, blocked: str | None) -> dict:
    return {
        "stp_roots": {"sw1": {"10": {
            "is_mst": False, "is_root": True, "root_address": "aaaa.0001.0001",
            "root_priority": 24586, "bridge_priority": 24586,
        }}},
        "interfaces": {"sw1": {"Gi1/0/1": {
            "stp_fwd_vlans": forwarding, "stp_blk_vlans": blocked,
        }}},
    }


def _stp_path_change(result: dict) -> dict:
    return next(row for row in result["changes"] if row["subject"] == "path|sw1|Gi1/0/1")


def test_stp_topology_expands_ranges_before_detecting_forwarding_regression():
    before = _stp_topology_path(forwarding="10-20", blocked=None)
    after = _stp_topology_path(forwarding="10-14,16-20", blocked="15")

    row = _stp_path_change(_bound_delta(compute_stp_topology_delta, before, after))

    assert row["transition"] == "regressed"
    assert row["decision_effect"] == "block"
    assert row["before_state"]["forwarding"] == ("10-20",)
    assert row["after_state"] == {
        "forwarding": ("10-14", "16-20"), "blocked": ("15",),
    }


def test_stp_topology_range_normalization_is_semantic_and_bidirectional():
    equivalent = _bound_delta(
        compute_stp_topology_delta,
        _stp_topology_path(forwarding="10-20", blocked=None),
        _stp_topology_path(forwarding="10,11-15,14-18,19,20", blocked=None),
    )
    unchanged = _stp_path_change(equivalent)
    assert unchanged["transition"] == "unchanged_healthy"
    assert unchanged["before_state"] == unchanged["after_state"] == {
        "forwarding": ("10-20",), "blocked": None,
    }

    boundary = _bound_delta(
        compute_stp_topology_delta,
        _stp_topology_path(forwarding="1-4094", blocked=None),
        _stp_topology_path(forwarding="1,2-4093,4094", blocked=None),
    )
    assert _stp_path_change(boundary)["transition"] == "unchanged_healthy"

    recovered = _bound_delta(
        compute_stp_topology_delta,
        _stp_topology_path(forwarding=None, blocked="10-20"),
        _stp_topology_path(forwarding="15", blocked="10-14,16-20"),
    )
    row = _stp_path_change(recovered)
    assert row["transition"] == "recovered"
    assert row["decision_effect"] == "none"


@pytest.mark.parametrize(
    "malformed",
    (
        "10-",
        "20-10",
        "10,,11",
        "not-a-vlan",
        "1-4095",
        "00001",
        "1-999999999999999999999999999999999999",
        ",".join(["1"] * 4096),
        "0" * 32_769,
    ),
    ids=(
        "truncated-range", "reversed-range", "empty-component", "nonnumeric",
        "out-of-domain", "oversized-token", "oversized-endpoint", "excessive-token-count",
        "oversized-text",
    ),
)
def test_stp_topology_malformed_or_oversized_ranges_fail_closed(malformed):
    before = _stp_topology_path(forwarding="10-20", blocked=None)
    after = _stp_topology_path(forwarding=malformed, blocked=None)

    result = _bound_delta(compute_stp_topology_delta, before, after)
    row = _stp_path_change(result)

    assert row["transition"] == "coverage_lost"
    assert row["decision_effect"] == "not_verified"
    assert result["assessed"] is False
    assert not any(
        change["subject"] == row["subject"] and change["transition"] == "unchanged_healthy"
        for change in result["changes"]
    )


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


def test_native_composer_does_not_turn_empty_stp_or_ether_containers_into_support(tmp_path):
    (tmp_path / "empty-ether").mkdir()
    projection, _interfaces, _commands = etherchannel_projection(
        tmp_path / "empty-ether", "routed1", ""
    )
    receipt = protocol_receipt({"routed1": {"EtherChannel": "captured_empty"}})
    baseline = summarize_etherchannel_baseline(projection, receipt)
    assert baseline["rows"] == []
    snapshot = {
        "script_version": "V3.23.0",
        "devices": {"routed1": {"platform": "ios"}},
        "interfaces": {"routed1": {}},
        "protocol_assessability": receipt,
        "stp_roots": {},
        "etherchannel_projection": projection,
        "etherchannel_baseline": baseline,
    }

    families = compute_native_protocol_deltas(snapshot, deepcopy(snapshot))

    assert not any(
        row["family"] in {"stp_consistency", "stp_topology", "etherchannel"}
        for row in families
    )


def test_native_composer_does_not_turn_fixed_vtp_fhrp_roster_cells_into_support():
    snapshot = {
        "script_version": "V3.23.0",
        "devices": {"routed1": {"platform": "ios"}},
        "protocol_assessability": {
            "families": [
                {"protocol": "VTP", "disposition": "not_collected"},
                {"protocol": "FHRP", "disposition": "not_collected"},
            ],
            "rows": [
                {"protocol": "VTP", "health_row_emitted": False},
                {"protocol": "FHRP", "health_row_emitted": False},
            ],
        },
    }

    families = compute_native_protocol_deltas(snapshot, deepcopy(snapshot))

    assert not any(
        row["family"] in {
            "vtp_safety",
            "fhrp_configured_group",
            "fhrp_redundancy_domain",
        }
        for row in families
    )


def test_bound_two_device_snapshot_rejects_empty_estate_owner_grafts(tmp_path):
    """A valid zero-host owner cannot authorize absence for a different bound estate."""
    ether_root = tmp_path / "ether-graft"
    ether_root.mkdir()
    ether_projection, _interfaces, _commands = etherchannel_projection(
        ether_root,
        "off-roster-edge",
        "Group Port-channel Protocol Ports\n"
        "1 Po1(SU) LACP Gi1/0/1(P) Gi1/0/2(P)\n",
    )
    ether_receipt = protocol_receipt({
        "off-roster-edge": {"EtherChannel": "assessed"},
    })
    ether_baseline = summarize_etherchannel_baseline(
        ether_projection, ether_receipt)
    snapshot = {
        "schema": "collect_parse_snapshot/1",
        "script_version": "V3.23.0",
        "devices": {
            "edge-a": {"platform": "ios"},
            "edge-b": {"platform": "nxos"},
        },
        "interfaces": {"edge-a": {}, "edge-b": {}},
        "bgp_configured_peer_baseline": compute_bgp_configured_peer_baseline(
            {}, {}, devices={}),
        "ipv6_routing_adjacency_baseline":
            compute_ipv6_routing_adjacency_baseline({}, {}, devices={}),
        "vtp_safety_baseline": compute_vtp_safety_baseline({}, {}, devices={}),
        "etherchannel_projection": ether_projection,
        "protocol_assessability": ether_receipt,
        "etherchannel_baseline": ether_baseline,
    }
    before, before_source = _bind_snapshot(snapshot)
    after, after_source = _bind_snapshot(deepcopy(snapshot))
    before_binding = {
        **before_source,
        "source": OFFLINE_FILE_SOURCE,
        "snapshot_id": 1001,
        "campaign_id": 91,
        "engagement_id": "ENG-EMPTY-GRAFT",
        "label": "before.json",
        "script_version": "V3.23.0",
    }
    after_binding = {
        **after_source,
        "source": OFFLINE_FILE_SOURCE,
        "snapshot_id": 1002,
        "campaign_id": 91,
        "engagement_id": "ENG-EMPTY-GRAFT",
        "label": "after.json",
        "script_version": "V3.23.0",
    }

    native = compute_native_protocol_deltas(
        before,
        after,
        before_binding=before_binding,
        after_binding=after_binding,
    )
    by_family = {row["family"]: row for row in native}
    for family in (
            "bgp_configured_peer", "ipv6_routing_adjacency", "vtp_safety",
            "etherchannel"):
        result = by_family[family]
        assert result["applicability"] == "applicable"
        assert result["assessed"] is False
        assert result["summary"]["by_transition"]["not_comparable"] == 1
        assert result["summary"]["by_transition"]["unchanged_healthy"] == 0
        assert "snapshot device" in result["changes"][0]["note"]

    comparison = compare_bound_pair(
        before,
        after,
        before_binding=before_binding,
        after_binding=after_binding,
    )
    assert comparison["comparison_admission"]["status"] == "admitted"
    assert comparison["cutover_gate"]["verdict"] != "PASS"
    assert {
        row["family"]
        for family in comparison["protocol_families"]["families"]
        for row in family["changes"]
        if row["transition"] == "not_comparable"
    } >= {
        "bgp_configured_peer", "ipv6_routing_adjacency", "vtp_safety",
        "etherchannel",
    }


def test_honest_captured_empty_owner_rosters_remain_not_applicable(tmp_path):
    (tmp_path / "bgp").mkdir()
    bgp, *_ = bgp_owner(
        tmp_path / "bgp",
        config="version 17.9\nhostname edge1\nend\n",
        runtime=EMPTY_IOS_SUMMARY,
    )
    _paths, ipv6 = ipv6_owner(
        tmp_path / "ipv6",
        {"show ipv6 route summary": ipv6_route_capture(ospf=0, bgp=0)},
    )
    vtp, *_ = vtp_owner(
        tmp_path / "vtp", "VTP is disabled.\n")
    cases = (
        (compute_bgp_configured_peer_delta, "edge1", "bgp_configured_peer_baseline", bgp),
        (compute_ipv6_routing_adjacency_delta, "sw1", "ipv6_routing_adjacency_baseline", ipv6),
        (compute_vtp_safety_delta, "edge1", "vtp_safety_baseline", vtp),
    )
    for computer, host, key, baseline in cases:
        snapshot = {
            "script_version": "V3.23.0",
            "devices": {host: {"platform": "ios"}},
            key: baseline,
        }
        result = _bound_delta(computer, snapshot, deepcopy(snapshot))
        assert result["applicability"] == "not_applicable"
        assert result["changes"] == []
        assert result["summary"]["n_subjects"] == 0


@pytest.mark.parametrize(
    ("computer", "baseline_key", "owner_factory"),
    (
        (
            compute_bgp_configured_peer_delta,
            "bgp_configured_peer_baseline",
            lambda root: bgp_owner(
                root,
                config="version 17.9\nhostname edge1\nend\n",
                runtime=EMPTY_IOS_SUMMARY,
            )[0],
        ),
        (
            compute_ipv6_routing_adjacency_delta,
            "ipv6_routing_adjacency_baseline",
            lambda root: ipv6_owner(
                root,
                {"show ipv6 route summary": ipv6_route_capture(ospf=0, bgp=0)},
            )[1],
        ),
        (
            compute_vtp_safety_delta,
            "vtp_safety_baseline",
            lambda root: vtp_owner(root, "VTP is disabled.\n")[0],
        ),
    ),
)
def test_structurally_valid_rowless_receipt_for_another_host_is_not_comparable(
        tmp_path, computer, baseline_key, owner_factory):
    source = tmp_path / computer.__name__
    source.mkdir()
    baseline = owner_factory(source)
    snapshot = {
        "script_version": "V3.23.0",
        "devices": {"renamed-edge": {"platform": "ios"}},
        baseline_key: baseline,
    }

    result = _bound_delta(computer, snapshot, deepcopy(snapshot))

    assert result["assessed"] is False
    assert result["summary"]["by_transition"]["not_comparable"] == 1
    assert result["summary"]["by_transition"]["unchanged_healthy"] == 0
    assert result["source_receipts"]["before"]["reason"].endswith(
        "does not exactly reconcile to snapshot devices")


def test_after_roster_mutation_is_not_comparable_but_missing_after_owner_is_coverage_lost(
        tmp_path):
    (tmp_path / "bgp-roster-mutation").mkdir()
    baseline, *_ = bgp_owner(
        tmp_path / "bgp-roster-mutation",
        config="version 17.9\nhostname edge1\nend\n",
        runtime=EMPTY_IOS_SUMMARY,
    )
    before = {
        "script_version": "V3.23.0",
        "devices": {"edge1": {"platform": "ios"}},
        "bgp_configured_peer_baseline": baseline,
    }

    mismatched = _bound_delta(
        compute_bgp_configured_peer_delta,
        before,
        {
            "script_version": "V3.23.0",
            "devices": {"renamed-edge": {"platform": "ios"}},
            "bgp_configured_peer_baseline": baseline,
        },
    )
    assert mismatched["summary"]["by_transition"]["not_comparable"] == 1
    assert mismatched["summary"]["by_transition"]["coverage_lost"] == 0
    assert mismatched["summary"]["by_transition"]["unchanged_healthy"] == 0

    missing = _bound_delta(
        compute_bgp_configured_peer_delta,
        before,
        {
            "script_version": "V3.23.0",
            "devices": {"edge1": {"platform": "ios"}},
        },
    )
    assert missing["summary"]["by_transition"]["coverage_lost"] == 1
    assert missing["summary"]["by_transition"]["not_comparable"] == 0
    assert missing["summary"]["by_transition"]["unchanged_healthy"] == 0


def test_fhrp_configured_positive_rows_must_belong_to_snapshot_devices(tmp_path):
    baseline, *_ = configured_fhrp_owner(tmp_path / "fhrp-positive")

    def compare(devices: dict) -> dict:
        snapshot = {
            "script_version": "V3.23.0",
            "devices": devices,
            "fhrp_configured_group_baseline": baseline,
        }
        raw = json.dumps(
            snapshot,
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        bound = bind_snapshot_json_bytes(raw)
        binding = {
            "sha256": bound_snapshot_source(bound)["sha256"],
            "bytes": len(raw),
        }
        return compute_fhrp_configured_group_delta(
            bound,
            bound,
            comparison_source_binding={"before": binding, "after": binding},
        )

    matching = compare({"edge1": {"platform": "ios"}})
    assert matching["summary"]["by_transition"]["unchanged_healthy"] == 1

    mismatched = compare({"renamed-edge": {"platform": "ios"}})
    assert mismatched["summary"]["by_transition"]["not_comparable"] == 1
    assert mismatched["summary"]["by_transition"]["unchanged_healthy"] == 0
    assert mismatched["source_receipts"]["before"]["reason"].endswith(
        "does not exactly reconcile to snapshot devices")


def test_stp_positive_rows_must_belong_to_snapshot_devices(tmp_path):
    stp_root = tmp_path / "stp-roster"
    stp_root.mkdir()
    interfaces, health, receipt = _stp_run(
        stp_root,
        inconsistent="No inconsistent ports observed\n",
    )
    consistency_snapshot = {
        "script_version": "V3.23.0",
        "devices": {
            "edge-a": {"platform": "ios"},
            "edge-b": {"platform": "ios"},
        },
        "interfaces": interfaces,
        "protocol_health": health,
        "protocol_assessability": receipt,
        "stp_roots": {},
    }
    consistency = _bound_delta(
        compute_stp_consistency_delta,
        consistency_snapshot,
        deepcopy(consistency_snapshot),
    )
    assert consistency["summary"]["by_transition"]["not_comparable"] == 1
    assert consistency["summary"]["by_transition"]["unchanged_healthy"] == 0

    topology_snapshot = _stp_topology_path(forwarding="10", blocked=None)
    topology_snapshot.update({
        "script_version": "V3.23.0",
        "devices": {
            "edge-a": {"platform": "ios"},
            "edge-b": {"platform": "ios"},
        },
    })
    topology = _bound_delta(
        compute_stp_topology_delta,
        topology_snapshot,
        deepcopy(topology_snapshot),
    )
    assert topology["summary"]["by_transition"]["not_comparable"] == 1
    assert topology["summary"]["by_transition"]["unchanged_healthy"] == 0


def test_fhrp_domain_reconciles_its_copublished_configured_roster(tmp_path):
    domain_root = tmp_path / "fhrp-domain-roster"
    domain_root.mkdir()
    configured, interfaces = fhrp_domain_sources(domain_root, {
        "edge-a": {"ip": "10.0.10.2", "role": "Active"},
        "edge-b": {"ip": "10.0.10.3", "role": "Standby"},
    })
    domain = compute_fhrp_redundancy_domain_baseline(interfaces, configured)

    def compare(devices: dict) -> dict:
        snapshot = {
            "script_version": "V3.23.0",
            "devices": devices,
            "interfaces": interfaces,
            "fhrp_configured_group_baseline": configured,
            "fhrp_redundancy_domain_baseline": domain,
        }
        raw = json.dumps(
            snapshot,
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
            default=lambda item: dataclasses.asdict(item)
            if dataclasses.is_dataclass(item) else str(item),
        ).encode("utf-8")
        bound = bind_snapshot_json_bytes(raw)
        binding = {
            "sha256": bound_snapshot_source(bound)["sha256"],
            "bytes": len(raw),
        }
        return compute_fhrp_redundancy_domain_delta(
            bound,
            bound,
            comparison_source_binding={"before": binding, "after": binding},
        )

    matching = compare({
        "edge-a": {"platform": "ios"},
        "edge-b": {"platform": "ios"},
    })
    assert matching["summary"]["by_transition"]["unchanged_healthy"] == 1

    mismatched = compare({
        "renamed-a": {"platform": "ios"},
        "renamed-b": {"platform": "ios"},
    })
    assert mismatched["summary"]["by_transition"]["not_comparable"] == 1
    assert mismatched["summary"]["by_transition"]["unchanged_healthy"] == 0


@pytest.mark.parametrize(
    "mutation",
    [
        lambda snap: snap.__setitem__(
            "stp_consistency_baseline", {"schema": "RENAMED/1", "rows": []}
        ),
        lambda snap: snap.__setitem__(
            "etherchannel_baseline", {"schema": "RENAMED/1", "rows": []}
        ),
        lambda snap: snap.__setitem__(
            "etherchannel_projection", {"schema": "RENAMED/1", "rows": []}
        ),
    ],
)
def test_native_composer_never_hides_malformed_empty_owner_attempts(mutation):
    snapshot = {
        "script_version": "V3.23.0",
        "devices": {"routed1": {"platform": "ios"}},
        "interfaces": {"routed1": {}},
        "stp_roots": {},
    }
    mutation(snapshot)

    families = compute_native_protocol_deltas(snapshot, deepcopy(snapshot))

    assert families
    assert any(
        change["transition"] == "not_comparable"
        and change["decision_effect"] == "not_verified"
        for family in families
        for change in family["changes"]
    )


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

    result = _bound_delta(compute_etherchannel_delta, before, after)

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
