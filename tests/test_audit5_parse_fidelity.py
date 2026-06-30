"""[audit-5 format-fidelity batch] parse.py parsers grounded against REAL device-output shapes (the recurring
self-authored-fixture trap: a parser tuned to one platform's format silently drops another's). Each fixture is a
faithful slice of the real [HISTORY-REDACTED] collection (migration_collection_20260613_063201)."""
from cisco_toolkit import parse


def test_parse_multicast_info_nxos_verbose_pim_interface():
    """[#0/#1 HIGH] The PIM regex only matched the IOS table row '<ip> <intf> v2/S'; the NX-OS verbose stanza
    ('VlanN, Interface status: protocol-up/...') was dropped, so PIM-configured SVIs on the NX-OS cores
    (CS01/CS02 -- 'both core') read as multicast-blind. Real CS01 output shape."""
    pim = ('PIM Interface Status for VRF "default"\n'
           'Vlan64, Interface status: protocol-up/link-up/admin-up\n'
           '  IP address: 10.203.64.2, IP subnet: 10.203.64.0/24\n'
           "  PIM DR: 10.203.64.3, DR's priority: 1\n"
           '  PIM neighbor count: 1\n'
           'Vlan28, Interface status: protocol-up/link-up/admin-up\n'
           '  IP address: 10.203.28.2, IP subnet: 10.203.28.0/24\n')
    res = parse.parse_multicast_info("", pim)   # signature is (mroute_out, pim_out)
    assert len(res) == 2, res
    assert all("PIM" in v for v in res.values())
    keys = " ".join(res)
    assert "64" in keys and "28" in keys


def _sec_findings(cfg):
    r = __import__("cisco_toolkit.parse", fromlist=["parse"]).parse_security(cfg)
    fl = r["findings"] if isinstance(r, dict) and "findings" in r else r
    return {f["id"]: f for f in fl}


def test_parse_security_nxos_type5_user_and_password_encryption():
    """[#2/#3 HIGH] weak_users flagged ANY 'username X password ...', but NX-OS 'username admin password 5
    <salted-md5>' is Type-5 (STRONG) -- only untyped cleartext / Type-0 / Type-7 is weak.
    [#12 MED] 'service password-encryption' is an IOS command absent on NX-OS (which encrypts by default), so the
    CIS check false-FAILED every NX-OS device with an impossible 'cleartext (Type-0)' claim -> must be N/A.
    Real CS01 shapes."""
    nxos = ("feature ospf\n"
            "username admin password 5 $1$/xzLOXP8$cb6hjzRZiOUAmAkP91S930  role network-admin\n"
            "username swadmin password 5 $1$.2qNwXmh$KYWx8jlR.OCGELDIxtNLi0  role vdc-operator\n")
    f = _sec_findings(nxos)
    assert f["weak-user-pw"]["status"] == "pass"        # Type-5 users are strong, not weak
    assert f["password-encryption"]["status"] == "na"   # not applicable on NX-OS (no false cleartext FAIL)
    # IOS weak forms still correctly flagged
    ios = ("service password-encryption\n"
           "username weakguy password 7 094F471A1A0A\n"
           "username clearguy password Sup3rCleartext\n")
    f2 = _sec_findings(ios)
    assert f2["weak-user-pw"]["status"] == "fail"
    assert "weakguy" in f2["weak-user-pw"]["detail"] and "clearguy" in f2["weak-user-pw"]["detail"]
    assert f2["password-encryption"]["status"] == "pass"


def test_parse_show_version_nxos_chassis_pid():
    """[#4 HIGH] parse_show_version emitted the bare Nexus marketing token ('6001', 'C93180YC-EX', '56128P') as
    the model, which eoldb never matches -> wrong EoL on every Nexus. Normalize the 'cisco Nexus <fam> <tok>
    Chassis' line to the NxK-C<...> PID. Real CS01 shape ('cisco Nexus 6001 Chassis')."""
    from cisco_toolkit import parse, eoldb
    r = parse.parse_show_version('Hardware\n  cisco Nexus 6001 Chassis ("Nexus 64 Supervisor")\n')
    assert r["model"] == "N6K-C6001", r["model"]
    assert eoldb.lifecycle_for(r["model"]) is not None      # now matches eoldb (was a no-match bare '6001')
    r2 = parse.parse_show_version("  cisco Nexus9000 C93180YC-EX Chassis\n")     # PID-body form
    assert r2["model"] == "N9K-C93180YC-EX", r2["model"]


def test_endpoint_vendor_rules_match_real_ieee_names():
    """[#13/#20] _EP_VENDOR_RULES used substrings that match ZERO entries in the shipped IEEE registry:
    'f5 net' (registry says 'F5 Inc.'), 'brother inds' ('Brother industries, LTD.'), 'gigabyte' ('Giga-Byte
    Technology'); and missed 'HP Inc.'. Each recognized vendor silently dropped to Unknown. Grounded in real
    OUIs from the bundled ouidb."""
    from cisco_toolkit import analyze, ouidb

    def C(v):
        return analyze._classify_endpoint(v, "", "", "", False)[0]
    # the real IEEE legal-name strings (were dead substrings -> Unknown)
    assert C("F5 Inc.") == "Network"
    assert C("Brother industries, LTD.") == "Printer"
    assert C("Giga-Byte Technology Co.,Ltd.") == "Server"
    assert C("HP Inc.") == "Server"
    # end-to-end via real OUIs
    def cls(oui):
        return analyze._classify_endpoint(ouidb.vendor_for_mac(oui + ":11:22:33"), "", "", "", False)[0]
    assert cls("00:01:d7") == "Network"     # F5 Inc.
    assert cls("00:80:77") == "Printer"     # Brother industries
    assert cls("00:1a:4d") == "Server"      # Giga-Byte Technology


def test_parse_neighbors_cdp_nxos_ipv4_address():
    """[#21] NX-OS 'show cdp neighbors detail' uses 'IPv4 Address:' (not IOS 'IP address:'), so the mgmt-IP
    regex missed it -> blank on all 55 real NX-OS devices. Real CS01 shape."""
    out = ("Device ID:NBR-A.example.tv\n"
           "Interface: Ethernet1/1,  Port ID (outgoing port): Ethernet1/2\n"
           "    IPv4 Address: 10.200.200.222\n")
    rec = next(iter(parse.parse_neighbors_cdp(out).values()))
    assert rec["mgmt_ip"] == "10.200.200.222"


def test_parse_neighbors_lldp_nxos_not_advertised_is_not_a_neighbor_name():
    """[#6] NX-OS LLDP 'System Name: not advertised' was stored as the neighbor device_id, so the explorer
    rendered a phantom hub literally labeled 'NOT ADVERTISED' (every name-suppressed neighbour collapsed into
    one node). The sentinel must become an empty name; real names still captured. Real CS01 shape."""
    out = ("Chassis id: AAAA\n"
           "Port id: 11aa.22bb.33cc\n"
           "Local Port id: Eth1/1\n"
           "System Name: not advertised\n"
           "Chassis id: BBBB\n"
           "Port id: Eth2/2\n"
           "Local Port id: Eth1/2\n"
           "System Name: RealNeighbor\n")
    names = {r["device_id"] for r in parse.parse_neighbors_lldp(out).values()}
    assert "not advertised" not in {n.lower() for n in names}     # no phantom 'NOT ADVERTISED' hub
    assert "RealNeighbor" in names                                 # real names still captured
