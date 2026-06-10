"""Unit tests for the syslog-intelligence axis (NEW-V3.23.164):
parse_syslog_events (parse layer) + compute_syslog_intelligence (analyze layer) —
the NOS-style operational log analysis (top messages, severity profile, detections)."""
from cisco_toolkit.analyze import (
    _SYSLOG_LINK_FLAP_MIN,
    _SYSLOG_LOGIN_FAIL_MIN,
    compute_syslog_intelligence,
)
from cisco_toolkit.parse import parse_syslog_events


def _kinds(si, host=None):
    return [d["kind"] for d in si["detections"] if host is None or d["host"] == host]


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
def test_parse_ios_nxos_and_stacked_facility_lines():
    text = """\
Syslog logging: enabled (0 messages dropped)
    Buffer logging: level debugging, 3 messages logged

000123: *Jun  9 12:00:01.123: %LINK-3-UPDOWN: Interface GigabitEthernet1/0/1, changed state to down
2026 Jun  9 12:00:02 nx1 %ETHPORT-5-IF_DOWN_LINK_FAILURE: Interface Ethernet1/1 is down (Link failure)
*Jun  9 12:00:03.000: %SPANTREE-SP-2-BLOCK_BPDUGUARD: Received BPDU on port Gi2/1 with BPDU Guard enabled. Disabling port.
"""
    ev = parse_syslog_events(text)
    assert len(ev) == 3                       # the two header lines are skipped
    assert ev[0] == {"facility": "LINK", "severity": 3, "mnemonic": "UPDOWN",
                     "msg": "Interface GigabitEthernet1/0/1, changed state to down",
                     "raw": ev[0]["raw"]}
    assert ev[1]["facility"] == "ETHPORT" and ev[1]["severity"] == 5
    assert ev[1]["mnemonic"] == "IF_DOWN_LINK_FAILURE"
    # stacked module prefix: facility keeps the '-SP' part, severity still parses
    assert ev[2]["facility"] == "SPANTREE-SP" and ev[2]["severity"] == 2
    assert ev[2]["mnemonic"] == "BLOCK_BPDUGUARD"


def test_parse_empty_and_garbage_input():
    assert parse_syslog_events("") == []
    assert parse_syslog_events(None) == []
    assert parse_syslog_events("no events here\njust % a stray percent\n") == []


# --------------------------------------------------------------------------- #
# detections
# --------------------------------------------------------------------------- #
def test_macflap_and_errdisable_detected_high():
    log = """\
*Jun  2 03:14:09.001: %SW_MATM-4-MACFLAP_NOTIF: Host 0011.22aa.0001 in vlan 10 is flapping between port Gi1/0/5 and port Gi1/0/9
*Jun  2 03:14:11.530: %SW_MATM-4-MACFLAP_NOTIF: Host 0011.22aa.0001 in vlan 10 is flapping between port Gi1/0/5 and port Gi1/0/9
*Jun  2 03:15:02.118: %PM-4-ERR_DISABLE: bpduguard error detected on Gi1/0/9, putting Gi1/0/9 in err-disable state
"""
    si = compute_syslog_intelligence({"sw1": log})
    kinds = _kinds(si, "sw1")
    assert "mac-flap" in kinds and "err-disable" in kinds
    det = {d["kind"]: d for d in si["detections"]}
    assert det["mac-flap"]["severity"] == "High" and det["mac-flap"]["count"] == 2
    assert "MACFLAP" in det["mac-flap"]["example"]
    assert det["err-disable"]["recommendation"]            # doctrine attached


def test_link_flap_threshold_is_per_interface():
    one_flap = "*Jun  2 03:15:03.220: %LINK-3-UPDOWN: Interface Gi1/0/9, changed state to down\n"
    below = compute_syslog_intelligence({"sw1": one_flap * (_SYSLOG_LINK_FLAP_MIN - 1)})
    assert "link-flap" not in _kinds(below)
    # the same number of events SPREAD across interfaces must not trigger either
    spread = "".join(
        f"*Jun  2 03:15:03.220: %LINK-3-UPDOWN: Interface Gi1/0/{i}, changed state to down\n"
        for i in range(_SYSLOG_LINK_FLAP_MIN))
    assert "link-flap" not in _kinds(compute_syslog_intelligence({"sw1": spread}))
    at = compute_syslog_intelligence({"sw1": one_flap * _SYSLOG_LINK_FLAP_MIN})
    flaps = [d for d in at["detections"] if d["kind"] == "link-flap"]
    assert len(flaps) == 1 and "Gi1/0/9" in flaps[0]["detail"]


def test_environment_resource_stp_guard_and_reload():
    log = """\
*Jun  1 01:00:00.000: %ENVMON-2-SUPPLY: Power supply 2 is faulty or removed
*Jun  1 01:00:01.000: %FMANRP_TCAM-3-TCAM_FULL: TCAM resource exhausted on slot 1
*Jun  1 01:00:02.000: %SPANTREE-2-ROOTGUARD_BLOCK: Root guard blocking port GigabitEthernet1/0/1 on VLAN0010
*Jun  1 01:00:03.000: %SYS-5-RESTART: System restarted -- Cisco IOS Software
"""
    si = compute_syslog_intelligence({"sw1": log})
    kinds = _kinds(si, "sw1")
    assert {"environment", "resource", "stp-guard", "reload"} <= set(kinds)
    sev = {d["kind"]: d["severity"] for d in si["detections"]}
    assert sev["environment"] == "High" and sev["reload"] == "Medium"
    # High detections sort before Medium
    assert [d["severity"] for d in si["detections"]] == sorted(
        [d["severity"] for d in si["detections"]], key={"High": 0, "Medium": 1}.get)


def test_login_fail_threshold():
    fail = "*May 30 22:13:41.404: %SEC_LOGIN-4-LOGIN_FAILED: Login failed [user: admin] [Source: 10.0.99.77]\n"
    below = compute_syslog_intelligence({"sw1": fail * (_SYSLOG_LOGIN_FAIL_MIN - 1)})
    assert "login-fail" not in _kinds(below)
    at = compute_syslog_intelligence({"sw1": fail * _SYSLOG_LOGIN_FAIL_MIN})
    assert "login-fail" in _kinds(at)


# --------------------------------------------------------------------------- #
# profile, honesty & empties
# --------------------------------------------------------------------------- #
def test_not_collected_is_declared_never_scored():
    log = "*Jun  1 09:12:01.123: %SYS-5-CONFIG_I: Configured from console by ops on vty0 (10.0.0.5)\n"
    si = compute_syslog_intelligence({"sw1": log, "sw2": "", "sw3": "   \n"})
    s = si["summary"]
    assert s["n_devices"] == 3 and s["n_collected"] == 1 and s["n_not_collected"] == 2
    assert s["hosts_not_collected"] == ["sw2", "sw3"]
    by_host = {d["host"]: d for d in si["per_device"]}
    assert by_host["sw2"]["collected"] is False and by_host["sw2"]["events"] == 0
    assert not _kinds(si, "sw2")              # nothing scored against the silent device
    assert by_host["sw1"]["config_changes"] == 1


def test_severity_profile_and_top_messages_deterministic():
    log = """\
*Jun  1 01:00:00.000: %ENVMON-1-ALARM: critical alarm
*Jun  1 01:00:01.000: %LINK-3-UPDOWN: Interface Gi1/0/1, changed state to down
*Jun  1 01:00:02.000: %CDP-4-DUPLEX_MISMATCH: duplex mismatch discovered on Gi1/0/5
*Jun  1 01:00:03.000: %SYS-5-CONFIG_I: Configured from console by ops
*Jun  1 01:00:04.000: %SYS-5-CONFIG_I: Configured from console by ops
"""
    si = compute_syslog_intelligence({"sw1": log})
    d = si["per_device"][0]
    assert d["by_severity"] == {"crit_0_2": 1, "err_3": 1, "warn_4": 1, "info_5_7": 2}
    assert d["top_messages"][0] == {"msg": "SYS-5-CONFIG_I", "count": 2}
    assert si["summary"]["crit_0_2"] == 1 and si["summary"]["err_3"] == 1
    assert "duplex-mismatch" in _kinds(si)


def test_empty_input_shapes():
    si = compute_syslog_intelligence({})
    assert si["per_device"] == [] and si["detections"] == []
    assert si["summary"]["n_devices"] == 0 and si["summary"]["n_detections"] == 0
    assert compute_syslog_intelligence(None)["summary"]["n_devices"] == 0
    assert si["note"]
