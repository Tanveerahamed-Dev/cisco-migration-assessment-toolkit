"""Plan-A Tier-2 #12 Phase-1: memoize the VLAN-range parse (the measured superlinear term inside
compute_failure_impact / the topology loops — the SAME range strings are tested against every VLAN on
every link). This pins _vlan_in_ranges' behaviour EXACTLY as a differential contract so the optimization
cannot change any output, and separately proves the parse is now cached (deterministic — not timing)."""
import pytest

from cisco_toolkit.analyze import _vlan_in_ranges, _parse_vlan_ranges

# (vid, range_string, expected) — a characterization of the CURRENT behaviour, so a refactor that
# changes any output turns red. Covers all/none sentinels, single vids, ranges, whitespace lists,
# malformed/inverted range tokens, non-numeric tokens, and case-insensitivity.
CASES = [
    (10, "", False), (10, "none", False), (10, "--", False), (10, "n/a", False),
    (10, "all", True), (4094, "all", True), (10, "1-4094", True), (1, "1-4094", True),
    (10, "10", True), (11, "10", False),
    (22, "10,20-23,40", True), (23, "10,20-23,40", True), (24, "10,20-23,40", False), (40, "10,20-23,40", True),
    (15, "10 20 30", False), (20, "10 20 30", True),
    (10, "10-x", False), (10, "10-20-30", False),
    (15, "20-10", False),
    (99, "abc,99", True), (5, "abc", False),
    (10, "ALL", True), (10, "None", False),
]


@pytest.mark.parametrize("vid,s,expected", CASES)
def test_vlan_in_ranges_contract(vid, s, expected):
    assert _vlan_in_ranges(vid, s) is expected


def test_parse_is_cached():
    """The optimization itself: the range PARSE is memoized, so re-testing the SAME range string against
    many VLAN ids (the failure-impact / topology inner loop) parses once and hits the cache thereafter.
    Deterministic proof via cache_info() -- no timing, so it can't flake on a slow CI box."""
    _parse_vlan_ranges.cache_clear()
    s = "10,20-23,40,100-200"
    for vid in range(1, 101):          # same string, 100 distinct membership tests -> 1 miss, 99 hits
        _vlan_in_ranges(vid, s)
    info = _parse_vlan_ranges.cache_info()
    assert info.misses == 1, f"expected the range string parsed exactly once, got {info.misses} misses"
    assert info.hits >= 99, f"expected the cache to serve repeat parses, got {info.hits} hits"
