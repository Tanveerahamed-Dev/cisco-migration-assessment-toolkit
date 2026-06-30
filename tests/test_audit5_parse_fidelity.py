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
