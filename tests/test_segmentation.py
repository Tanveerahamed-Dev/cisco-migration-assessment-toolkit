"""NEW-V3.23.118: L3 segmentation / isolation audit -- VRF separation + gateway-ACL coverage per application
domain. Pure read of the gateway SVIs (vrf / acl_in / acl_out) joined to the domain map."""
import json

from cisco_toolkit.analyze import compute_segmentation
from cisco_toolkit.model import InterfaceData


def _svi(key="Vlan10", vrf="", acl_in="", acl_out="", ip="10.0.0.1/24"):
    return InterfaceData(port=key, svi_ip=ip, vrf=vrf, acl_in=acl_in, acl_out=acl_out)


def _app(domains):
    return {"domains": domains}


def test_flat_fabric_global_vrf_no_acls():
    ai = {"sw1": {"Vlan10": _svi("Vlan10", vrf="default"), "Gi1/0/1": InterfaceData(port="Gi1/0/1")},
          "sw2": {"Vlan20": _svi("Vlan20", ip="10.0.20.1/24")}}    # blank vrf -> global
    out = compute_segmentation(ai, _app([]))
    assert out["summary"]["flat"] is True and out["summary"]["global_only"] is True
    assert out["gateway_acl"] == {"n_gateways": 2, "n_with_acl": 0, "coverage_pct": 0.0}
    assert out["vrfs"] == [{"vrf": "(global)", "gateway_count": 2}]
    assert any(r["title"].startswith("Flat L3 fabric") for r in out["risks"])


def test_dedicated_vrf_and_acl_count_as_isolated():
    ai = {"swA": {"Vlan10": _svi("Vlan10", vrf="MEDIA")},                          # dedicated VRF
          "swB": {"Vlan20": _svi("Vlan20", acl_in="GUARD", ip="10.0.20.1/24")}}    # global but has an ACL
    app = _app([{"domain": "Media", "tier": "On-air critical", "switches": ["swA"]},
                {"domain": "Guest", "tier": "Support", "switches": ["swB"]}])
    out = compute_segmentation(ai, app)
    dom = {d["domain"]: d for d in out["domains"]}
    assert dom["Media"]["isolated"] is True and "MEDIA" in dom["Media"]["vrfs"]
    assert dom["Guest"]["isolated"] is True and dom["Guest"]["gateways_with_acl"] == 1
    assert out["summary"]["flat"] is False          # a real VRF exists
    assert out["summary"]["n_oncrit_exposed"] == 0


def test_on_air_exposed_risk():
    ai = {"swM": {"Vlan10": _svi("Vlan10", vrf="default")}}    # media gateway, global, no ACL
    app = _app([{"domain": "Media Fabric", "tier": "On-air critical", "switches": ["swM"]}])
    out = compute_segmentation(ai, app)
    d = out["domains"][0]
    assert d["isolated"] is False and "global VRF" in d["exposure"]
    assert out["summary"]["n_oncrit_exposed"] == 1
    assert any("on-air-critical domain(s) are not isolated" in r["title"] for r in out["risks"])


def test_gateway_acl_coverage_pct():
    ai = {"s": {"Vlan10": _svi("Vlan10", acl_in="A"), "Vlan20": _svi("Vlan20", ip="10.0.20.1/24"),
                "Vlan30": _svi("Vlan30", acl_out="B", ip="10.0.30.1/24"),
                "Vlan40": _svi("Vlan40", ip="10.0.40.1/24")}}
    out = compute_segmentation(ai, _app([]))
    assert out["gateway_acl"]["n_gateways"] == 4 and out["gateway_acl"]["n_with_acl"] == 2
    assert out["gateway_acl"]["coverage_pct"] == 50.0


def test_empty_and_deterministic():
    assert compute_segmentation({}, {})["summary"]["n_gateways"] == 0
    assert compute_segmentation(None, None)["domains"] == []
    ai = {"sw1": {"Vlan10": _svi("Vlan10", vrf="default")}}
    app = _app([{"domain": "D", "tier": "Support", "switches": ["sw1"]}])
    a = compute_segmentation(ai, app)
    b = compute_segmentation(ai, app)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_segmentation_domain_isolated_requires_all_gateways_protected():
    """ANALY-03: a domain was marked 'isolated' if ANY ONE gateway had a VRF/ACL, masking sibling gateways in
    the global VRF with no ACL (reachable from every domain) -- so a real on-air-critical L3 exposure was
    dropped from the executive Segmentation axis. Isolation must require EVERY gateway protected."""
    from cisco_toolkit.analyze import compute_segmentation
    from cisco_toolkit.model import InterfaceData
    ai = {"SW1": {"Vlan10": InterfaceData(port="Vlan10", svi_ip="10.0.10.1/24", vrf="PROD")},
          "SW2": {"Vlan20": InterfaceData(port="Vlan20", svi_ip="10.0.20.1/24", vrf="")},        # exposed
          "SW3": {"Vlan30": InterfaceData(port="Vlan30", svi_ip="10.0.30.1/24", vrf="", acl_in="GUARD")}}
    app = {"domains": [{"domain": "Media", "tier": "On-air critical", "switches": ["SW1", "SW2"]},
                       {"domain": "Iso", "tier": "Support", "switches": ["SW3"]}]}
    out = compute_segmentation(ai, app)
    media = next(d for d in out["domains"] if d["domain"] == "Media")
    iso = next(d for d in out["domains"] if d["domain"] == "Iso")
    assert media["isolated"] is False and "1 of 2" in media["exposure"]   # one exposed gateway surfaces
    assert iso["isolated"] is True                                         # all-protected domain stays isolated
