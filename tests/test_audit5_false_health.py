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


def test_wave_sequencing_uncollected_is_unknown_homing_not_single_homed():
    """[#7 HIGH] compute_wave_sequencing classified a switch single-homed (hard cutover) when its topology
    adjacency was empty -- but a NEVER-COLLECTED device has empty adjacency from absence of evidence, not from
    being single-homed. 50 uncollected AJ devices were labeled 'single-homed -> hard cutover'. Uncollected ->
    homing UNKNOWN."""
    from cisco_toolkit import analyze
    from cisco_toolkit.model import InterfaceData
    ai = {"collected1": {"Gi0/1": InterfaceData(port="Gi0/1")}}   # collected, no 2nd uplink -> single-homed
    out = analyze.compute_wave_sequencing(ai, [{"switches": ["collected1", "uncollected1"]}])
    row = out[0]
    assert "uncollected1" in row["homing_unknown"]               # never collected -> UNKNOWN
    assert "uncollected1" not in row["hard_cutover"]
    assert "collected1" in row["hard_cutover"]                   # genuinely single-homed (collected, no 2nd uplink)
    assert "UNKNOWN" in row["sequence"]


def test_syslog_intelligence_catalyst_sev4_psu_failure_surfaced():
    """[#11 HIGH] The environment-event classifier gated on 'sev <= 3', so the Catalyst 4500/4948 PSU-failure
    syslog '%...-4-POWERSUPPLYBAD' (severity 4) was silently dropped -- a real hardware failure read as healthy.
    A sev-4 FAILURE mnemonic now surfaces; benign sev-4 env info (FANOK) still skipped (no cry-wolf)."""
    from cisco_toolkit import analyze
    bad = "*Mar  1 00:00:00.000: %C4K_IOSMODPORTMAN-4-POWERSUPPLYBAD: Power supply 1 has failed or been turned off\n"
    assert any(d["kind"] == "environment" for d in analyze.compute_syslog_intelligence({"sw1": bad})["detections"])
    ok = "%PLATFORM-4-FANOK: Fan module 1 is OK\n"
    assert not any(d["kind"] == "environment" for d in analyze.compute_syslog_intelligence({"sw1": ok})["detections"])
