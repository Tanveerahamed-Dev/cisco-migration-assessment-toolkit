"""[audit-5 false-health batch] absence or weakness of a control must NOT read as healthy/clean/pass. Each test
plants the real-shaped insecure-but-present case and asserts it is surfaced, not silently passed."""
from cisco_toolkit import parse


def _ins(cfg):
    return {f["id"]: f for f in parse.parse_security(cfg)["findings"]}["insecure-snmp"]


def test_parse_security_snmpv3_noauth_and_weak():
    """[#2 HIGH / #20] The SNMPv3 check PASSed on the mere PRESENCE of an 'snmp-server user/group' line, so a
    noAuthNoPriv user (no auth -> no security) false-PASSed, and md5/des weak auth read as a clean 'auth/priv'
    PASS. Now noAuthNoPriv -> FAIL(high); weak md5/des -> PASS but disclosed."""
    f = _ins("feature ssh\nsnmp-server user OPER network-operator\n")     # no auth keyword -> noAuthNoPriv
    assert f["status"] == "fail" and f["severity"] == "high"
    fw = _ins("snmp-server user admin network-admin auth md5 0xabc priv 0xabc localizedkey\n")
    assert fw["status"] == "pass" and ("md5" in fw["detail"].lower() or "weak" in fw["detail"].lower())
    assert _ins("snmp-server user U vdc-operator auth sha 0xabc priv aes-128 0xdef localizedkey\n")["status"] == "pass"


def test_build_network_model_skips_no_ip_svi_gateway():
    """[#1 HIGH] build_network_model registered EVERY 'VlanN' SVI as a gateway regardless of an IP, so the
    universal no-IP Vlan1 interface became a phantom gateway on 243 devices -> 60 false 'VLAN 1: Hard partition'
    High failure_impact records (stranded:0). Only an SVI WITH an svi_ip is a real L3 gateway."""
    from cisco_toolkit import analyze
    from cisco_toolkit.model import InterfaceData
    ai = {"SW1": {
        "Vlan1":  InterfaceData(port="Vlan1"),                       # no svi_ip -> NOT a gateway
        "Vlan10": InterfaceData(port="Vlan10", svi_ip="10.0.10.1"),  # real gateway
    }}
    gw = analyze.build_network_model(ai)["gw"]
    assert 1 not in gw and 10 in gw
