"""PHASE 2.7 step 1: the cisco_toolkit package extraction.

Guards the extraction boundary - the leaf text helpers live in
cisco_toolkit.textutils and the monolith re-exports the *same* objects (so a
future accidental re-definition in the monolith would break the identity check).
"""


def test_textutils_importable_standalone():
    from cisco_toolkit.textutils import normalize_ifname, is_valid_iface, normalize_mac
    assert normalize_ifname("GigabitEthernet1/0/1") == "Gi1/0/1"
    assert is_valid_iface("Gi1/0/1") is True
    assert is_valid_iface("garbage") is False
    assert normalize_mac("00:11:22:33:44:55") == "0011.2233.4455"


def test_monolith_reexports_the_package_objects(cp):
    from cisco_toolkit import textutils
    # identity, not equality: the monolith must use the package's functions/regex,
    # not a re-defined copy.
    assert cp.normalize_ifname is textutils.normalize_ifname
    assert cp.detect_link_type is textutils.detect_link_type
    # is_valid_iface is now used only inside the package (its monolith callers moved out)
    assert callable(textutils.is_valid_iface)
    assert cp.VALID_IFACE_RE is textutils.VALID_IFACE_RE
    assert cp.IFACE_TOKEN_RE is textutils.IFACE_TOKEN_RE


def test_parse_module_reexported_and_functional(cp):
    from cisco_toolkit import parse
    # primitives live in the package; the monolith no longer references them
    # directly now that the table parsers moved out (so it doesn't import them).
    assert callable(parse.extract_fixed_cols) and callable(parse.slice_col)
    # parsers the monolith still calls are re-exported as the SAME object.
    assert cp.parse_ospf_neighbors is parse.parse_ospf_neighbors
    assert cp.parse_bgp_summary is parse.parse_bgp_summary
    assert cp.parse_show_interface_status is parse.parse_show_interface_status
    # functional smoke straight from the package
    rows = parse.parse_ospf_neighbors("10.0.0.2  1  FULL/DR  00:00:35  10.0.0.2  Gi0/1")
    assert rows and rows[0]["state"] == "FULL/DR" and rows[0]["interface"] == "Gi0/1"
