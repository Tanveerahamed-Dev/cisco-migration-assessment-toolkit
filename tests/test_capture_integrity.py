"""Tests for the per-config-body capture-integrity guard (roadmap K1).

compute_collection_completeness tiers a device by essential-command FILE PRESENCE, not body integrity
(its own comment at analyze.py:1188) — so a truncated `show running-config` that returned *some* text
scores 'complete' and every downstream finding off it can silently pass. This guard inspects the body
for truncation / pager / CLI-error signatures and marks it [INCOMPLETE] so the absence-is-not-health
rule can fire on a partial capture.
"""
from cisco_toolkit import capture_integrity as ci


def test_running_config_with_end_is_ok():
    assert ci.inspect_capture("show running-config", "hostname R1\n!\ninterface Gi1\n!\nend\n")["status"] == "ok"


def test_running_config_without_end_is_incomplete():
    r = ci.inspect_capture("show running-config", "hostname R1\n!\ninterface Gi1\n switchport access vlan 10")
    assert r["status"] == "incomplete"
    assert "end" in r["reason"].lower()


def test_non_config_command_needs_no_end():
    assert ci.inspect_capture("show version", "Cisco IOS XE Software, Version 17.9\nuptime is 5 days\n")["status"] == "ok"


def test_pager_artifact_is_incomplete():
    r = ci.inspect_capture("show interfaces", "GigabitEthernet1 is up\n line protocol is up\n --More-- ")
    assert r["status"] == "incomplete"
    assert "pager" in r["reason"].lower() or "more" in r["reason"].lower()


def test_cli_error_is_error():
    r = ci.inspect_capture("show running-config", "% Invalid input detected at '^' marker.")
    assert r["status"] == "error"


def test_empty_body_is_empty():
    assert ci.inspect_capture("show version", "   \n  ")["status"] == "empty"


def test_compute_over_host_bodies_lists_only_problems():
    bodies = {
        "sw1": {"show running-config": "hostname sw1\nend", "show version": "v17.9"},
        "sw2": {"show running-config": "hostname sw2\ninterface Gi1\n switchport"},   # truncated: no end
        "sw3": {"show running-config": "% Incomplete command"},                        # errored
    }
    out = ci.compute_capture_integrity(bodies)
    by = {(f["host"], f["command"]): f for f in out["findings"]}
    assert ("sw1", "show running-config") not in by            # healthy -> not listed
    assert by[("sw2", "show running-config")]["status"] == "incomplete"
    assert by[("sw3", "show running-config")]["status"] == "error"
    assert out["summary"]["n_incomplete"] == 1
    assert out["summary"]["n_error"] == 1
    assert out["summary"]["n_hosts_affected"] == 2
    # every finding carries a citation for the reviewer
    assert all(f.get("citation") for f in out["findings"])


# --- review-wave-1 regression tests (false positives/negatives) -----------------------------------

def test_nxos_config_without_end_is_ok():
    body = "!Command: show running-config\n!Running configuration last done\nhostname N9K\nfeature bgp\nlogging origin-id hostname"
    assert ci.inspect_capture("show running-config", body)["status"] == "ok"   # NX-OS emits no terminating 'end'


def test_scoped_or_filtered_dump_needs_no_end():
    body = "interface GigabitEthernet1/1\n switchport mode access\n switchport access vlan 10\n!"
    assert ci.inspect_capture("show running-config | section interface", body)["status"] == "ok"


def test_prompt_echo_after_end_is_ok():
    assert ci.inspect_capture("show running-config", "hostname R1\n!\nend\n\nR1#")["status"] == "ok"


def test_cli_error_phrase_in_config_data_is_ok():
    body = "hostname R1\ninterface Gi1\n description sensor flags 'invalid input detected' to syslog\n!\nend"
    assert ci.inspect_capture("show running-config", body)["status"] == "ok"   # the phrase is config DATA, not a CLI error


def test_pager_phrase_in_banner_mid_config_is_ok():
    body = "hostname R1\nbanner motd ^C\nRun 'show ...' then press --More--\n^C\n!\nend"
    assert ci.inspect_capture("show running-config", body)["status"] == "ok"   # '--More--' is banner text, end present


def test_pager_variants_are_caught():
    for tail in ["--More(35%)--", "-- More --", "--more--"]:
        r = ci.inspect_capture("show interface", "Gi1 is up\n line protocol is up\n" + tail)
        assert r["status"] == "incomplete", tail
