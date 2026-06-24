"""Cisco firewall (ASA / Secure Firewall Threat Defense) HA assessment -- the SSH show-text channel.

Covers parse_asa_failover (the 'show failover' state parser), build_firewall (the per-device axis), the
_signals firewall-HA extraction, and the _d_firewall_ha_degraded detector. The contract is the universal
coverage-honesty doctrine: the detector fires ONLY on an OBSERVED, settled-broken HA state (a unit Failed /
Disabled, or the peer Not Detected) while failover is ENABLED; it stays silent for a healthy Active+Standby
pair, for every transient sync state (a pair mid-bring-up must never cry wolf), and for a standalone firewall
with no failover (absence of HA is NOT broken HA). Proposer != verifier: a fires-on-broken AND a
silent-on-clean assertion for each case, plus a hostile-input robustness sweep."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from cisco_toolkit import parse  # noqa: E402
import cisco_toolkit.design_advisor as da  # noqa: E402


# --- real 'show failover' shapes (per the ASA/FTD command reference + config guide) ---------------------
_HEALTHY = """\
Failover On
Failover unit Primary
Failover LAN Interface: FAILOVER GigabitEthernet0/2 (up)
Unit Poll frequency 1 seconds, holdtime 15 seconds
Interface Poll frequency 5 seconds, holdtime 25 seconds
Interface Policy 1
Monitored Interfaces 3 of 1050 maximum
Version: Ours 9.16(3)23, Mate 9.16(3)23
Last Failover at: 12:00:00 UTC Jan 1 2026
        This host: Primary - Active
                Active time: 1234567 (sec)
                  Interface outside (203.0.113.1): Normal (Monitored)
                  Interface inside (10.0.0.1): Normal (Monitored)
        Other host: Secondary - Standby Ready
                Active time: 0 (sec)
                  Interface outside (203.0.113.2): Normal (Monitored)
                  Interface inside (10.0.0.2): Normal (Monitored)
"""

_PEER_FAILED = _HEALTHY.replace("Secondary - Standby Ready", "Secondary - Failed")
_PEER_NOT_DETECTED = _HEALTHY.replace("Secondary - Standby Ready", "Secondary - Not Detected")
_THIS_FAILED = _HEALTHY.replace("Primary - Active", "Primary - Failed")

# A pair mid-resync (Cold Standby) / mid-negotiation -- TRANSIENT, must NOT fire.
_TRANSIENT_COLD = _HEALTHY.replace("Secondary - Standby Ready", "Secondary - Cold Standby")
_TRANSIENT_SYNC = _HEALTHY.replace("Secondary - Standby Ready", "Secondary - Sync Config")

# Standalone firewall: failover not enabled -- coverage-honest, absence of HA is not broken HA.
_STANDALONE = """\
Failover Off
Failover unit Secondary
Failover LAN Interface: not Configured
Unit Poll frequency 1 seconds, holdtime 15 seconds
"""

# Active/Active failover: the role is on the 'This/Other host' line and each failover GROUP carries its own
# state beneath it. Healthy = each group is Active on a different unit (none Failed). Broken = a group Failed
# on this unit. (Per the ASA command reference A/A 'show failover' layout.)
_AA_HEALTHY = """\
Failover On
Failover unit Primary
  This host:    Primary
  Group 1       State:          Active
                Active time:    2896 (sec)
  Group 2       State:          Standby Ready
  Other host:   Secondary
  Group 1       State:          Standby Ready
  Group 2       State:          Active
"""
_AA_BROKEN = _AA_HEALTHY.replace("Group 2       State:          Standby Ready",
                                 "Group 2       State:          Failed", 1)


# ============================================================ parser
def test_parse_failover_healthy_pair():
    fo = parse.parse_asa_failover(_HEALTHY)
    assert fo["enabled"] is True
    states = {(u["host"], u["state"]) for u in fo["units"]}
    assert ("this", "Active") in states
    assert ("other", "Standby Ready") in states
    # roles parsed
    assert {u["role"] for u in fo["units"]} == {"Primary", "Secondary"}


def test_parse_failover_off_is_disabled_not_empty():
    fo = parse.parse_asa_failover(_STANDALONE)
    assert fo.get("enabled") is False


def test_parse_failover_peer_failed_state_captured():
    fo = parse.parse_asa_failover(_PEER_FAILED)
    other = [u for u in fo["units"] if u["host"] == "other"][0]
    assert other["state"] == "Failed"


def test_parse_failover_non_failover_text_returns_empty():
    # a switch that doesn't know 'show failover' returns an error / unrelated text -> {} (tolerant gate)
    assert parse.parse_asa_failover("% Invalid input detected at '^' marker.") == {}
    assert parse.parse_asa_failover("") == {}


# ============================================================ build
def test_build_firewall_reads_failover(tmp_path):
    from cisco_toolkit import build
    p = tmp_path / "show_failover.txt"
    p.write_text(_PEER_FAILED, encoding="utf-8")
    fw = build.build_firewall({"show failover": str(p)})
    assert fw["failover"]["enabled"] is True
    assert any(u["state"] == "Failed" for u in fw["failover"]["units"])


def test_build_firewall_empty_when_absent(tmp_path):
    from cisco_toolkit import build
    assert build.build_firewall({}) == {}
    # a switch that doesn't know 'show failover' emits '% Invalid input' -- _load_cmd_output skips Cisco
    # error output, so build_firewall is coverage-honestly empty (a switch fleet never fabricates a firewall)
    err = tmp_path / "show_failover.txt"
    err.write_text("% Invalid input detected at '^' marker.", encoding="utf-8")
    assert build.build_firewall({"show failover": str(err)}) == {}


# ============================================================ detector (fires-on-broken / silent-on-clean)
def _snap(text):
    return {"firewall": {"FW-EDGE-01": {"failover": parse.parse_asa_failover(text)}}}


def test_detector_fires_on_peer_failed():
    snap = _snap(_PEER_FAILED)
    d = da._d_firewall_ha_degraded(snap, da._signals(snap))
    assert d is not None
    assert d["id"] == "firewall-ha-failover-degraded"
    assert "FW-EDGE-01" in d["evidence"]["devices"]


def test_detector_fires_on_peer_not_detected_and_this_failed():
    for text in (_PEER_NOT_DETECTED, _THIS_FAILED):
        snap = _snap(text)
        assert da._d_firewall_ha_degraded(snap, da._signals(snap)) is not None


def test_detector_silent_on_healthy_pair():
    snap = _snap(_HEALTHY)
    assert da._d_firewall_ha_degraded(snap, da._signals(snap)) is None


def test_detector_silent_on_transient_sync_states():
    # a pair mid-bring-up / mid-resync must NOT cry wolf
    for text in (_TRANSIENT_COLD, _TRANSIENT_SYNC):
        snap = _snap(text)
        assert da._d_firewall_ha_degraded(snap, da._signals(snap)) is None


def test_detector_silent_on_standalone_firewall():
    # Failover Off: absence of HA is coverage-honest 'not broken', not a finding
    snap = _snap(_STANDALONE)
    assert da._d_firewall_ha_degraded(snap, da._signals(snap)) is None


def test_parse_failover_active_active_group_states():
    # Active/Active: per-group state parsed under the host context
    fo = parse.parse_asa_failover(_AA_BROKEN)
    assert fo["enabled"] is True
    states = {(u["host"], u.get("group"), u["state"]) for u in fo["units"]}
    assert ("this", "1", "Active") in states
    assert ("this", "2", "Failed") in states
    assert ("other", "2", "Active") in states


def test_detector_fires_on_active_active_failed_group():
    snap = _snap(_AA_BROKEN)
    d = da._d_firewall_ha_degraded(snap, da._signals(snap))
    assert d is not None and "FW-EDGE-01" in d["evidence"]["devices"]


def test_detector_silent_on_healthy_active_active():
    # each group Active on a different unit, none Failed -> no finding
    snap = _snap(_AA_HEALTHY)
    assert da._d_firewall_ha_degraded(snap, da._signals(snap)) is None


def test_detector_silent_when_no_firewall_axis():
    assert da._d_firewall_ha_degraded({}, da._signals({})) is None


# ============================================================ coverage SSOT
def test_firewall_in_architecture_coverage_registry():
    keys = {axis for axis, *_ in da._ARCH_COVERAGE_REGISTRY}
    assert "firewall" in keys
    cov = da.compute_architecture_coverage(_snap(_PEER_FAILED) | {
        "design_blueprint": {"decisions": [{"id": "firewall-ha-failover-degraded"}]}})
    fw = [c for c in cov["classes"] if c["key"] == "firewall"][0]
    assert fw["observed"] is True and fw["status"] == "finding" and fw["channel"] == "ssh"


# ============================================================ robustness (tolerant; never raises)
def test_parse_failover_tolerates_hostile_input():
    for bad in ["", "   ", "\x00\x01", "Failover", "This host:", "Other host: -",
                "Failover On\nThis host:  - \n", "%" * 200, "\n\n\n", "Failover On"]:
        out = parse.parse_asa_failover(bad)
        assert isinstance(out, dict)


def test_parse_failover_tolerates_non_string_input():
    # the docstring promises 'never raises' -- a non-string scalar/container must degrade to {}, not raise
    for bad in (None, 123, 3.14, True, b"Failover On", ["x"], {"a": 1}):
        assert parse.parse_asa_failover(bad) == {}


def test_detector_survives_malformed_firewall_axis():
    for snap in [{"firewall": None}, {"firewall": "x"}, {"firewall": {"h": None}},
                 {"firewall": {"h": {"failover": "x"}}},
                 {"firewall": {"h": {"failover": {"enabled": True, "units": "x"}}}},
                 {"firewall": {"h": {"failover": {"enabled": True, "units": [None, 1, {"state": None}]}}}}]:
        sig = da._signals(snap)
        assert da._d_firewall_ha_degraded(snap, sig) is None or isinstance(
            da._d_firewall_ha_degraded(snap, sig), dict)


# --- resource / capacity ('show resource usage') ---------------------------------------------------------
# Real ASA/FTD output (verified vs the Cisco S-command reference + the ASA-performance TechNote): the resource
# NAME can carry spaces + a bracketed suffix ('Conns [rate]'), so the row is parsed RIGHT-anchored. SSH
# Denied=44 here is the canonical benign administrative case (failed mgmt logins) that must be EXCLUDED.
_RES_HEALTHY = """\
Resource          Current     Peak       Limit       Denied  Context
SSH                     0        5           5           44   System
Conns                4156     9817      280000            0   System
Xlates               2912     8400         N/A            0   System
Hosts               15955    24871         N/A            0   System
Conns [rate]           62      984         N/A            0   System
"""
_RES_DENIED = _RES_HEALTHY.replace("Conns                4156     9817      280000            0   System",
                                   "Conns                4156     9817      280000          120   System")
_RES_NEAR = _RES_HEALTHY.replace("Conns                4156     9817      280000            0   System",
                                 "Conns              250000   265000      280000            0   System")


def test_parse_resource_usage_right_anchored():
    rows = parse.parse_asa_resource_usage(_RES_HEALTHY)
    by = {r["resource"]: r for r in rows}
    assert by["Conns"]["limit"] == 280000 and by["Conns"]["peak"] == 9817 and by["Conns"]["denied"] == 0
    assert by["Xlates"]["limit"] is None          # 'N/A' -> None (unlimited)
    assert by["Conns [rate]"]["current"] == 62    # bracketed multi-word name parsed from the right
    assert by["SSH"]["denied"] == 44


def test_resource_detector_fires_on_dataplane_denied():
    snap = {"firewall": {"FW1": {"resource_usage": parse.parse_asa_resource_usage(_RES_DENIED)}}}
    d = da._d_firewall_resource_exhaustion(snap, da._signals(snap))
    assert d is not None and d["id"] == "firewall-resource-exhaustion" and "FW1" in d["evidence"]["devices"]


def test_resource_detector_fires_on_peak_near_numeric_limit():
    snap = {"firewall": {"FW1": {"resource_usage": parse.parse_asa_resource_usage(_RES_NEAR)}}}
    assert da._d_firewall_resource_exhaustion(snap, da._signals(snap)) is not None


def test_resource_detector_silent_on_healthy_and_admin_denied():
    # SSH Denied=44 is administrative (failed logins) -> excluded; Conns peak 3.5% of limit -> silent
    snap = {"firewall": {"FW1": {"resource_usage": parse.parse_asa_resource_usage(_RES_HEALTHY)}}}
    assert da._d_firewall_resource_exhaustion(snap, da._signals(snap)) is None


def test_resource_detector_silent_when_no_firewall_axis():
    assert da._d_firewall_resource_exhaustion({}, da._signals({})) is None


def test_parse_resource_usage_tolerates_hostile():
    for bad in ("", None, 123, "garbage\nno numbers", "Resource Current Peak Limit Denied Context", ["x"]):
        assert isinstance(parse.parse_asa_resource_usage(bad), list)
