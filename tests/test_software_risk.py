"""Unit tests for the software-risk screening axis (NEW-V3.23.166):
compute_software_risk (+ the _swrisk_train classifier) — the NOS 'software risk
analysis' pillar: config-evidenced attack surfaces joined to landmark advisories,
plus cautious software-train lifecycle bands. Screening, never a vuln scan."""
from cisco_toolkit.analyze import _swrisk_train, compute_software_risk


_EXPOSED_CFG = """\
hostname dist1
ip http server
no ip http secure-server
snmp-server community s3cret RW
vstack
ip ssh version 1
crypto isakmp policy 10
 encr aes
service finger
line vty 0 4
 transport input telnet ssh
"""

_HARDENED_CFG = """\
hostname dist2
no ip http server
no ip http secure-server
no vstack
snmp-server group OPS v3 priv
ip ssh version 2
line vty 0 4
 transport input ssh
"""


def _kinds(sr, host=None):
    return [f["kind"] for f in sr["findings"] if host is None or f["host"] == host]


# --------------------------------------------------------------------------- #
# attack-surface screening
# --------------------------------------------------------------------------- #
def test_exposed_surfaces_all_detected():
    sr = compute_software_risk({"dist1": _EXPOSED_CFG})
    kinds = set(_kinds(sr, "dist1"))
    assert {"http-server", "snmp-v2c-rw", "smart-install", "ssh-v1",
            "ikev1", "small-services", "telnet-vty"} <= kinds
    d = {f["kind"]: f for f in sr["findings"]}
    # the landmark-advisory join: web UI -> CVE-2023-20198, marked exploited
    http = d["http-server"]
    assert http["severity"] == "High"
    assert any(a["cve"] == "CVE-2023-20198" for a in http["advisories"])
    assert "exploited" in http["advisories"][0]["note"]
    assert "Software Checker" in http["recommendation"]
    # secrets never leak into evidence
    assert "s3cret" not in str(sr)


def test_hardened_config_yields_no_findings():
    sr = compute_software_risk({"dist2": _HARDENED_CFG})
    assert _kinds(sr, "dist2") == []
    surf = sr["per_device"][0]["surfaces"]
    assert surf["http-server"] == "closed"
    assert surf["smart-install"] == "closed"


def test_snmp_rw_takes_precedence_over_ro():
    rw = compute_software_risk({"sw": "snmp-server community foo RW\n"})
    assert _kinds(rw) == ["snmp-v2c-rw"]
    ro = compute_software_risk({"sw": "snmp-server community foo RO\n"})
    assert _kinds(ro) == ["snmp-v2c-ro"]
    none = compute_software_risk({"sw": "snmp-server group OPS v3 priv\n"})
    assert "snmp-v2c-ro" not in _kinds(none) and "snmp-v2c-rw" not in _kinds(none)


def test_snmp_view_qualified_rw_is_still_rw():
    # V3.23.170: 'snmp-server community <str> view <name> rw [acl]' is valid IOS syntax;
    # the view qualifier must not downgrade a READ-WRITE community to read-only.
    sr = compute_software_risk({"sw": "snmp-server community s3cret view FULLVIEW rw 10\n"})
    assert _kinds(sr) == ["snmp-v2c-rw"]
    assert "s3cret" not in str(sr)


def test_transport_input_all_is_telnet_exposure():
    # V3.23.170: 'transport input all' permits telnet (legacy form / old default) —
    # the CIS detector already treats it that way; the two must agree.
    sr = compute_software_risk({"sw": "line vty 0 4\n transport input all\n"})
    assert "telnet-vty" in _kinds(sr)


def test_default_dependent_surfaces_are_verify_not_exposed():
    sr = compute_software_risk({"sw": "hostname sw\n"})
    surf = sr["per_device"][0]["surfaces"]
    # neither 'ip http server' nor 'no ip http server' captured -> verify, no finding
    assert surf["http-server"] == "verify"
    assert surf["smart-install"] == "verify"
    assert _kinds(sr) == []


# --------------------------------------------------------------------------- #
# software-train lifecycle bands
# --------------------------------------------------------------------------- #
def test_train_bands_curated_and_cautious():
    assert _swrisk_train("12.2(55)SE12", "ios")[1] == "Replace/Upgrade"
    assert _swrisk_train("15.2(4)E10", "ios")[1] == "Verify EoL"
    assert _swrisk_train("03.06.06E", "ios")[1] == "Replace/Upgrade"
    assert _swrisk_train("16.12.04", "ios")[1] == "Verify EoL"
    train, band, note = _swrisk_train("17.3.5", "ios")
    assert band == "Current-era" and "Software Checker" in note
    assert _swrisk_train("6.2(16)", "nxos")[1] == "Replace/Upgrade"
    assert _swrisk_train("7.0(3)I7(8)", "nxos")[1] == "Verify EoL"
    assert _swrisk_train("9.3(8)", "nxos")[1] == "Current-era"
    assert _swrisk_train("10.2(5)", "nxos")[1] == "Current-era"
    assert _swrisk_train("", "ios")[1] == "Unknown"
    # an unrecognized train never gets an invented verdict
    t, b, n = _swrisk_train("8.4(1)", "ios")
    assert b == "Unknown" and "verify" in n.lower()


def test_per_device_sorted_worst_band_first():
    sr = compute_software_risk(
        {}, devices={"new": {"sw_version": "17.3.5"}, "old": {"sw_version": "12.2(55)SE"}},
        platforms={"new": {"platform": "ios"}, "old": {"platform": "ios"}})
    assert [d["host"] for d in sr["per_device"]] == ["old", "new"]
    assert sr["summary"]["train_bands"] == {"Current-era": 1, "Replace/Upgrade": 1}


# --------------------------------------------------------------------------- #
# honesty & shapes
# --------------------------------------------------------------------------- #
def test_not_assessable_declared_never_scored():
    sr = compute_software_risk({"sw1": _EXPOSED_CFG}, all_hosts=["sw1", "sw2"])
    s = sr["summary"]
    assert s["n_devices"] == 2 and s["n_config_assessable"] == 1
    assert s["hosts_config_not_assessable"] == ["sw2"]
    by_host = {d["host"]: d for d in sr["per_device"]}
    assert by_host["sw2"]["config_assessable"] is False
    assert by_host["sw2"]["surfaces"] == {} and not _kinds(sr, "sw2")
    assert by_host["sw2"]["sw_version"] == "(not captured)"


def test_findings_sorted_high_first_and_note_disclaims():
    sr = compute_software_risk({"sw1": _EXPOSED_CFG})
    sevs = [f["severity"] for f in sr["findings"]]
    assert sevs == sorted(sevs, key={"High": 0, "Medium": 1, "Low": 2}.get)
    assert "not a vulnerability scan" in sr["note"]
    assert sum(sr["summary"]["by_kind"].values()) == sr["summary"]["n_findings"]


def test_empty_input_shapes():
    sr = compute_software_risk({})
    assert sr["per_device"] == [] and sr["findings"] == []
    assert sr["summary"]["n_devices"] == 0
    assert compute_software_risk(None)["summary"]["n_findings"] == 0
