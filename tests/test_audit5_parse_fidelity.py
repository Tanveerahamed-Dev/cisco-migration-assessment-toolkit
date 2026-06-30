"""[audit-5 format-fidelity batch] parse.py parsers grounded against REAL device-output shapes (the recurring
self-authored-fixture trap: a parser tuned to one platform's format silently drops another's). Each fixture is a
faithful slice of the real AJ collection (migration_collection_20260613_063201)."""
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
