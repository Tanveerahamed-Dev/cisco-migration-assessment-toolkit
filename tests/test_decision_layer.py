"""Tests for the V3.23.169 decision-layer fold: the syslog / QoS / software-risk /
platform-health axes reach compute_migration_punchlist (grouped, cry-wolf-safe rows)
and compute_executive_brief (one honest headline per axis)."""
from cisco_toolkit.analyze import compute_executive_brief, compute_migration_punchlist

_EMPTY = ([], {}, {}, [], [], [], {}, [], [])     # the punch-list's positional sources, all empty


def _punch(**kw):
    return compute_migration_punchlist(*_EMPTY, **kw)


# --------------------------------------------------------------------------- #
# punch-list folding
# --------------------------------------------------------------------------- #
def test_syslog_detections_grouped_by_kind_not_per_device():
    si = {"detections": [
        {"host": "sw1", "kind": "mac-flap", "label": "MAC address flapping", "severity": "High",
         "detail": "14 event(s) in the collected log window.", "recommendation": "Fix the loop."},
        {"host": "sw2", "kind": "mac-flap", "label": "MAC address flapping", "severity": "High",
         "detail": "3 event(s) in the collected log window.", "recommendation": "Fix the loop."},
        {"host": "sw1", "kind": "reload", "label": "Device restart recorded", "severity": "Medium",
         "detail": "1 event(s).", "recommendation": "Correlate with change records."},
    ]}
    items = _punch(syslog_intelligence=si)
    assert len(items) == 2                                   # grouped by kind, never per device
    flap = next(i for i in items if i["title"] == "MAC address flapping")
    assert flap["severity"] == "High" and flap["category"] == "Operational logs"
    assert flap["devices"] == ["sw1", "sw2"]
    assert flap["detail"].startswith("2 device(s).")
    assert flap["remediation"] == "Fix the loop."
    assert items[0]["priority"] == 1                         # priorities assigned, High first
    assert items[0]["severity"] == "High"


def test_qos_fleet_rows_carry_no_devices():
    qa = {"findings": [
        {"host": "(fleet)", "kind": "mixed-posture", "label": "Inconsistent QoS posture across the fleet",
         "severity": "Medium", "detail": "2 with, 3 without.", "recommendation": "Standardize."},
        {"host": "acc1", "kind": "voice-without-qos", "label": "Voice VLAN without a QoS edge policy",
         "severity": "High", "detail": "3 port(s).", "recommendation": "Trust the phone."},
    ]}
    items = _punch(qos_audit=qa)
    fleet = next(i for i in items if "Inconsistent" in i["title"])
    assert fleet["devices"] == [] and fleet["wave"] == ""    # never pollutes per-device maps
    voice = next(i for i in items if "Voice VLAN" in i["title"])
    assert voice["devices"] == ["acc1"] and voice["category"] == "QoS"


def test_software_risk_uses_surface_and_why():
    sr = {"findings": [{
        "host": "dist1", "kind": "http-server",
        "surface": "Device web UI (ip http server / secure-server)", "severity": "High",
        "evidence": "ip http server",
        "why": "The IOS XE web UI was mass-exploited in 2023-24.",
        "recommendation": "Disable it; validate with the Software Checker."}]}
    items = _punch(software_risk=sr)
    assert len(items) == 1
    it = items[0]
    assert it["category"] == "Software exposure"
    assert it["title"].startswith("Device web UI")
    assert "mass-exploited" in it["detail"]                  # 'why' is the detail fallback
    assert it["devices"] == ["dist1"]


def test_platform_health_fold_and_wave_attribution():
    ph = {"findings": [{"host": "dist2", "kind": "hot-cpu", "label": "Control-plane CPU hot",
                        "severity": "High", "detail": "CPU 84%.",
                        "recommendation": "Find the consumer."}]}
    groups = [{"group": "Group 1", "switches": ["dist2"]}]
    items = compute_migration_punchlist([], {}, {}, [], [], [], {}, [], groups,
                                        platform_health=ph)
    it = items[0]
    assert it["category"] == "Platform capacity" and it["wave"] == "Group 1"


def test_punchlist_defaults_unchanged():
    assert _punch() == []                                    # absent axes change nothing
    assert _punch(syslog_intelligence={}, qos_audit=None,
                  software_risk={"findings": []}, platform_health={}) == []


# --------------------------------------------------------------------------- #
# executive brief
# --------------------------------------------------------------------------- #
def test_brief_gains_axis_headlines_with_worst_severity():
    brief = compute_executive_brief(
        syslog_intelligence={"summary": {"n_devices": 3, "n_collected": 2, "n_detections": 2,
                                         "crit_0_2": 1},
                             "detections": [{"severity": "High"}, {"severity": "Medium"}]},
        qos_audit={"summary": {"n_devices": 3, "n_assessable": 2, "n_findings": 1,
                               "modes": {"MQC": 2}},
                   "findings": [{"severity": "Medium"}]},
        software_risk={"summary": {"n_devices": 3, "n_findings": 1, "n_config_assessable": 3,
                                   "n_version_known": 3,
                                   "train_bands": {"Verify EoL": 2, "Current-era": 1}},
                       "findings": [{"severity": "High"}]},
        platform_health={"summary": {"n_devices": 3, "n_collected": 3, "n_findings": 0,
                                     "bands": {"OK": 3}},
                         "findings": []})
    by_axis = {a["axis"]: a for a in brief["axes"]}
    assert by_axis["Operational logs"]["severity"] == "High"
    assert "2 detection(s)" in by_axis["Operational logs"]["headline"]
    assert by_axis["QoS posture"]["severity"] == "Medium"
    assert by_axis["Software risk"]["severity"] == "High"
    assert "Software Checker" in by_axis["Software risk"]["detail"]
    assert by_axis["Platform capacity"]["severity"] == "Low"
    # High axes reach the gating list
    assert any("detection(s)" in g for g in brief["top_gating"])


def test_brief_not_collected_is_info_never_low_by_silence():
    brief = compute_executive_brief(
        syslog_intelligence={"summary": {"n_devices": 3, "n_collected": 0}},
        platform_health={"summary": {"n_devices": 3, "n_collected": 0}},
        qos_audit={"summary": {"n_devices": 3, "n_assessable": 0}},
        software_risk={"summary": {"n_devices": 3, "n_config_assessable": 0,
                                   "n_version_known": 0, "n_findings": 0,
                                   "train_bands": {"Unknown": 3}},
                       "findings": []})
    by_axis = {a["axis"]: a for a in brief["axes"]}
    assert by_axis["Operational logs"]["severity"] == "Info"
    assert "not collected" in by_axis["Operational logs"]["headline"]
    assert by_axis["QoS posture"]["severity"] == "Info"
    assert by_axis["Platform capacity"]["severity"] == "Info"
    # V3.23.170: software risk now carries the same gate — zero evidence is Info, never Low
    assert by_axis["Software risk"]["severity"] == "Info"
    assert "not assessable" in by_axis["Software risk"]["headline"]
    # versions-only evidence still gets a real verdict (the gate needs BOTH layers empty)
    versions_only = compute_executive_brief(
        software_risk={"summary": {"n_devices": 2, "n_config_assessable": 0,
                                   "n_version_known": 2, "n_findings": 0,
                                   "train_bands": {"Verify EoL": 2}},
                       "findings": []})
    sw = next(a for a in versions_only["axes"] if a["axis"] == "Software risk")
    assert sw["severity"] == "Medium"                  # lifecycle pressure, honestly assessed


def test_punchlist_skips_swrisk_kinds_the_cis_fold_already_carries():
    # V3.23.170: telnet/snmp software-risk findings duplicate the CIS Security rows for the
    # same config lines — they stay on the Software Risk sheet but not in the punch-list.
    sr = {"findings": [
        {"host": "sw1", "kind": "telnet-vty", "surface": "Telnet enabled on vty lines",
         "severity": "Medium", "why": "cleartext", "recommendation": "ssh only"},
        {"host": "sw1", "kind": "snmp-v2c-rw", "surface": "SNMP v1/v2c with a READ-WRITE community",
         "severity": "High", "why": "write via cleartext string", "recommendation": "v3"},
        {"host": "sw1", "kind": "http-server", "surface": "Device web UI (ip http server / secure-server)",
         "severity": "High", "why": "exploited surface", "recommendation": "disable"},
    ]}
    items = _punch(software_risk=sr)
    titles = [i["title"] for i in items]
    assert titles == ["Device web UI (ip http server / secure-server)"]   # twins excluded


def test_brief_without_new_axes_unchanged():
    base = compute_executive_brief(health_scores=[{"band": "Good", "score": 90}])
    assert {a["axis"] for a in base["axes"]} == {"Fleet health", "Migration punch-list"}
    # software-risk axis with no findings but lifecycle pressure reads Medium
    pressured = compute_executive_brief(
        software_risk={"summary": {"n_devices": 2, "n_findings": 0, "n_version_known": 2,
                                   "train_bands": {"Replace/Upgrade": 1, "Current-era": 1}},
                       "findings": []})
    sw = next(a for a in pressured["axes"] if a["axis"] == "Software risk")
    assert sw["severity"] == "Medium"
