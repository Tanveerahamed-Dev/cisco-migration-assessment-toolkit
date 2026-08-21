"""New routed subjects must not hide a current fault behind expected intent."""

from __future__ import annotations

from pathlib import Path

from cisco_toolkit.protocol_assurance import protocol_family_change_set
from cisco_toolkit.protocol_deltas import (
    compute_bgp_configured_peer_delta,
    compute_ipv6_routing_adjacency_delta,
)
from tests.test_bgp_configured_peer_baseline import (
    EMPTY_IOS_SUMMARY,
    IOS_CONFIG,
    _run as bgp_owner,
)
from tests.test_ipv6_routing_adjacency_baseline import (
    _bgp,
    _owner as ipv6_owner,
    _ospf,
    _route,
)


_EMPTY_BGP_CONFIG = "version 17.9\nrouter bgp 65001\nend\n"
_IPV4_DELTA = {
    "schema": "protocol_adjacency_delta/1",
    "summary": {"n_preserved": 0},
    "changes": [],
    "coverage_gaps": [],
}


def _expected_row(delta: dict, subject: str) -> dict:
    composed = protocol_family_change_set(
        _IPV4_DELTA,
        {"expected_changes": [{
            "family": delta["family"],
            "transitions": ["appeared"],
            "subjects": [subject],
        }]},
        [delta],
    )
    family = next(
        item for item in composed["families"] if item["family"] == delta["family"]
    )
    return next(item for item in family["changes"] if item["subject"] == subject)


def test_new_degraded_configured_bgp_peer_remains_blocking(tmp_path: Path):
    before_path, after_path = tmp_path / "before", tmp_path / "after"
    before_path.mkdir()
    after_path.mkdir()
    before, *_ = bgp_owner(
        before_path, config=_EMPTY_BGP_CONFIG, runtime=EMPTY_IOS_SUMMARY,
    )
    after, *_ = bgp_owner(
        after_path, config=IOS_CONFIG, runtime=EMPTY_IOS_SUMMARY,
    )

    delta = compute_bgp_configured_peer_delta(
        {"bgp_configured_peer_baseline": before},
        {"bgp_configured_peer_baseline": after},
    )
    row = next(item for item in delta["changes"] if item["transition"] == "appeared")
    assert row["after_state"]["status"] == "degraded"
    assert row["decision_effect"] == "block"

    composed = _expected_row(delta, row["subject"])
    assert composed["expected"] is True
    assert composed["decision_effect"] == "block"


def test_new_degraded_ipv6_adjacency_remains_blocking(tmp_path: Path):
    _paths, before = ipv6_owner(tmp_path / "before", {
        "show ipv6 route summary": _route(),
        "show ospfv3 neighbor": _ospf(),
        "show bgp ipv6 unicast summary": _bgp(),
    })
    _paths, after = ipv6_owner(tmp_path / "after", {
        "show ipv6 route summary": _route(),
        "show ospfv3 neighbor": _ospf(
            ("10.0.0.9", "EXSTART/-", "GigabitEthernet0/1")),
        "show bgp ipv6 unicast summary": _bgp(),
    })

    delta = compute_ipv6_routing_adjacency_delta(
        {"ipv6_routing_adjacency_baseline": before},
        {"ipv6_routing_adjacency_baseline": after},
    )
    row = next(
        item for item in delta["changes"]
        if item["transition"] == "appeared" and item["after_state"].get("state") == "EXSTART"
    )
    assert row["after_state"]["status"] == "degraded"
    assert row["decision_effect"] == "block"

    composed = _expected_row(delta, row["subject"])
    assert composed["expected"] is True
    assert composed["decision_effect"] == "block"
