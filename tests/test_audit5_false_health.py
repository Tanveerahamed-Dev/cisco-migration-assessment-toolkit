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


def test_vrrp_abbreviated_vlan_iface_not_dropped():
    """[#8 HIGH] is_valid_iface rejected the abbreviated SVI form 'Vl10' (only 'Vlan10' passed) and
    normalize_ifname kept them distinct, so a VRRP/GLBP gateway shown on 'Vl10' in 'show vrrp brief' was silently
    dropped -> the VLAN read as no-FHRP (a redundant gateway hidden). 'Vl10' now canonicalizes to 'Vlan10'."""
    assert parse.normalize_ifname("Vl10") == "Vlan10"
    assert parse.normalize_ifname("Vlan10") == "Vlan10"    # canonical form unchanged
    assert parse.is_valid_iface("Vl10")
    out = ("Interface  Grp Pri Time  Own Pre State   Master addr     Group addr\n"
           "Vl10       1   100 3609   Y   Y   Master  10.10.10.1      10.10.10.254\n")
    r = parse.parse_vrrp_summary(out)
    assert "Vlan10" in r and "VRRP" in r["Vlan10"]         # keyed canonically -> matches the Vlan10 SVI


def test_parse_ptp_clock_ignores_deprecated_command_banner():
    """[#13] 'show ptp clock' on NX-OS can return '% Unavailable command (deprecated by show ptp local-clock)' --
    that banner mentions 'ptp', so parse_ptp_clock parsed it into a (mostly empty) dict and the device read as
    PTP-present. An error/deprecation banner -> {} (no PTP); a real clock still parses."""
    assert parse.parse_ptp_clock("% Unavailable command (deprecated by show ptp local-clock)\n") == {}
    real = parse.parse_ptp_clock("PTP Device Type: boundary-clock\nPTP Device Profile: smpte-2059-2\n")
    assert real and real["device_type"] == "boundary-clock"


def test_trunk_native_sheet_no_mismatch_discloses_coverage():
    """[#6] When there are no native-VLAN mismatches the sheet printed an unqualified 'clean -- No native-VLAN
    mismatches on inter-switch trunks', reading absence-of-collection as health. It must instead disclose the
    basis (collected devices only; uncollected not assessed)."""
    import pytest
    openpyxl = pytest.importorskip("openpyxl")
    from cisco_toolkit import excel
    from cisco_toolkit.model import InterfaceData
    wb = openpyxl.Workbook()
    excel.write_trunk_native_sheet(wb, {"sw1": {"Gi0/1": InterfaceData(port="Gi0/1")}})   # no trunks -> no mismatch
    ws = wb[excel.TRUNK_NATIVE_SHEET_NAME]
    banner = " ".join(str(ws.cell(2, c).value or "") for c in (1, 2)).lower()
    assert "not assessed" in banner and ("uncollected" in banner or "collected" in banner)
    assert banner.strip() != "clean no native-vlan mismatches on inter-switch trunks"


def test_config_hygiene_sheet_empty_discloses_coverage():
    """[#23] An empty Config Hygiene sheet (no undefined/unused issues) showed nothing, reading as a fleet-wide
    clean bill though only collected devices are assessed. The empty case now discloses the assessed scope."""
    import pytest
    openpyxl = pytest.importorskip("openpyxl")
    from cisco_toolkit import excel
    wb = openpyxl.Workbook()
    excel.write_config_hygiene_sheet(wb, {"sw1": {"undefined": [], "unused": [], "summary": {}}})
    ws = wb[excel.CONFIG_HYGIENE_SHEET_NAME]
    banner = " ".join(str(ws.cell(2, c).value or "") for c in (1, 2)).lower()
    assert "not assessed" in banner and "collected running-config" in banner


def test_campaign_trend_collected_switch_going_dark_is_not_clean_improving():
    """[#9 HIGH] The survivorship guard detected only devices REMOVED from 'devices', but the engine keeps an
    uncollected device as an 'Insufficient Data' STUB in 'devices'. A previously-collected switch going dark
    (real band -> 'Insufficient Data') raised avg-health (its low score drops out of the average) and read as
    IMPROVING with no disclosure. The band transition now counts as gone-dark."""
    from cisco_toolkit.html import compute_campaign_trend

    def snap(hs, avg):
        return {"devices": {h["switch"]: {} for h in hs}, "interfaces": {}, "health_scores": hs,
                "punchlist": [], "executive_brief": {"posture": {"avg_health": avg}}}
    c1 = snap([{"switch": "a", "band": "Critical", "score": 10},
               {"switch": "b", "band": "Good", "score": 80}], avg=45)
    c2 = snap([{"switch": "a", "band": "Insufficient Data", "score": 90},   # 'a' went dark, still in devices
               {"switch": "b", "band": "Good", "score": 80}], avg=85)        # avg rose -> survivorship
    t = compute_campaign_trend([c1, c2])
    assert t["verdict"] != "IMPROVING"                    # survivorship -> not a clean improvement
    assert "dark" in t["verdict_note"].lower()
