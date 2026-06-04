"""PHASE 2.3: parser robustness (P1).

Proves the per-section `_safe_parse` guard: a parser that *raises* on a malformed
block no longer takes the whole device down with it - the other sections still
populate.
"""
import os

import synthetic_fixtures as fx


def _c2f(cp, collection_root, host):
    cmds = list(dict.fromkeys(cp.COMMANDS_NXOS + cp.COMMANDS_IOS))
    dev_dir = os.path.join(collection_root, host)
    return {c: os.path.join(dev_dir, fx.cmd_filename(c))
            for c in cmds if os.path.isfile(os.path.join(dev_dir, fx.cmd_filename(c)))}


def test_safe_parse_swallows_raise_and_defaults(cp):
    def boom(*a, **k):
        raise ValueError("malformed block")
    assert cp._safe_parse(boom, "anything") == {}
    assert cp._safe_parse(boom, "x", _default=[]) == []
    assert cp._safe_parse(lambda s: {"ok": s}, "v") == {"ok": "v"}   # happy path passes through


def test_failing_section_parser_does_not_drop_device(cp, collection_root, monkeypatch):
    """If one section's parser explodes, build_interfaces must still return the
    rest of the device's interfaces (not an empty dict)."""
    def boom(*a, **k):
        raise RuntimeError("simulated malformed trunk block")
    monkeypatch.setattr(cp, "parse_show_interface_trunk_table", boom)

    ifaces = cp.build_interfaces("core1", "ios", _c2f(cp, collection_root, "core1"))

    assert ifaces, "device was dropped because one parser raised"
    # status / running-config / SVI sections still parsed despite the trunk blow-up
    assert "Vlan10" in ifaces        # SVI from running-config
    assert "Gi1/0/5" in ifaces       # access port from interface status


def test_multiple_failing_parsers_still_yield_partial_device(cp, collection_root, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom")
    for name in ("parse_show_mac_address_table", "parse_neighbors_cdp",
                 "parse_spanning_tree_states", "parse_ip_routes"):
        monkeypatch.setattr(cp, name, boom)
    ifaces = cp.build_interfaces("core1", "ios", _c2f(cp, collection_root, "core1"))
    assert ifaces and "Gi1/0/5" in ifaces       # core data survives several failures
