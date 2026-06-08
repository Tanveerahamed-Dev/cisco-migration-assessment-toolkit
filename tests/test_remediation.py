"""NEW-V3.23.116: the remediation generator — per-device, platform-tagged Cisco config snippets generated
FOR REVIEW from the structured findings. These tests pin the per-source templates, the platform dialect,
the <placeholder> markers for unknown-intent fixes, the always-present review caution, and empty tolerance."""
import json

from cisco_toolkit.analyze import compute_remediation_plan


def _find(items, source):
    return [it for it in items if it["source"] == source]


def test_stp_accidental_and_misaligned():
    stp = {"accidental": [{"host": "sw1", "vlan": "999"}],
           "misaligned": [{"vlan": "10", "root": "sw2", "gateways": ["gwsw"]}]}
    out = compute_remediation_plan(devices={}, stp_findings=stp)
    acc = _find(out["items"], "stp-accidental")[0]
    assert acc["device"] == "sw1" and "spanning-tree vlan 999 priority 24576" in acc["commands"]
    mis = _find(out["items"], "stp-misaligned")[0]
    assert mis["device"] == "gwsw" and any("root primary" in c for c in mis["commands"])


def test_trunk_native_both_ends_with_placeholder():
    l2 = {"trunk_native": [{"a_host": "a", "a_port": "Gi1/0/1", "a_native": "1",
                            "b_host": "b", "b_port": "Gi1/0/2", "b_native": "99"}]}
    items = _find(compute_remediation_plan(devices={}, l2=l2)["items"], "trunk-native")
    assert {it["device"] for it in items} == {"a", "b"}
    assert all(any("switchport trunk native vlan <chosen-native-vlan>" in c for c in it["commands"]) for it in items)


def test_link_phy_duplex_both_ends():
    l2 = {"link_phy": [{"a_host": "a", "a_port": "Gi1", "b_host": "b", "b_port": "Gi2",
                        "duplex": ["half", "full"]}]}
    items = _find(compute_remediation_plan(devices={}, l2=l2)["items"], "link-phy")
    assert {it["device"] for it in items} == {"a", "b"}
    assert all(" duplex auto" in it["commands"] for it in items)


def test_config_hygiene_offers_define_or_remove():
    hg = {"sw1": {"undefined": [{"kind": "ip access-list extended", "name": "FOO",
                                 "context": "ip access-group FOO in"}]}}
    it = _find(compute_remediation_plan(devices={}, config_hygiene=hg)["items"], "hygiene-undefined")[0]
    cmds = " ".join(it["commands"])
    assert "DEFINE" in cmds and "REMOVE" in cmds and "FOO" in cmds


def test_cis_security_passes_through_remediation():
    sec = {"sw1": {"findings": [{"id": "http", "title": "HTTP server", "severity": "high", "status": "fail",
                                 "remediation": "no ip http server", "detail": "HTTP enabled."}]}}
    it = _find(compute_remediation_plan(devices={}, security=sec)["items"], "cis-security")[0]
    assert it["severity"] == "High" and any("no ip http server" in c for c in it["commands"])
    # a passing check produces nothing
    sec2 = {"sw1": {"findings": [{"id": "x", "status": "pass", "remediation": "z"}]}}
    assert _find(compute_remediation_plan(devices={}, security=sec2)["items"], "cis-security") == []


def test_cis_multiline_remediation_comments_every_line():
    # code-review fix: a multi-line CIS remediation must have EVERY line commented (not just the first),
    # so a review-only snippet never renders uncommented config.
    sec = {"sw1": {"findings": [{"id": "x", "title": "X", "severity": "medium", "status": "fail",
                                 "remediation": "first line\nsecond line"}]}}
    it = _find(compute_remediation_plan(devices={}, security=sec)["items"], "cis-security")[0]
    assert it["commands"] == ["! first line", "! second line"]
    assert all(c.startswith("!") for c in it["commands"])


def test_fhrp_platform_dialect_and_intent_placeholder():
    l2 = {"fhrp": [{"vid": "20", "members": [{"host": "iosgw"}, {"host": "nxgw"}], "issues": ["no FHRP"]}]}
    devices = {"iosgw": {"platform": "ios"}, "nxgw": {"platform": "nxos"}}
    by = {it["device"]: it for it in _find(compute_remediation_plan(devices=devices, l2=l2)["items"], "fhrp")}
    assert any("standby" in c for c in by["iosgw"]["commands"])         # IOS dialect
    assert "feature hsrp" in by["nxgw"]["commands"]                     # NX-OS dialect
    assert all("<virtual-ip>" in " ".join(it["commands"]) for it in by.values())   # intent placeholder


def test_review_caution_and_banner_always_present():
    out = compute_remediation_plan(devices={}, stp_findings={"accidental": [{"host": "sw1", "vlan": "5"}]})
    assert out["banner"] and "REVIEW" in out["banner"].upper()
    assert all(it["caution"] for it in out["items"])


def test_empty_and_deterministic():
    assert compute_remediation_plan()["items"] == []
    assert compute_remediation_plan(devices=None, l2=None, stp_findings=None)["summary"]["n_items"] == 0
    stp = {"accidental": [{"host": "b", "vlan": "1"}, {"host": "a", "vlan": "2"}]}
    a = compute_remediation_plan(devices={}, stp_findings=stp)
    b = compute_remediation_plan(devices={}, stp_findings=stp)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
