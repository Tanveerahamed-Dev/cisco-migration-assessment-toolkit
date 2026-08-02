"""NEW-V3.23.112: the application & network intelligence layer -- switches synthesized into named
application DOMAINS with criticality tier, footprint, health rollup, wave span, and standards-grounded
migration risk (ST 2059 boundary clocks / RFC 4541 querier continuity / ST 2022-7 / NEXIS). Pure read
of already-computed layers; these tests pin the taxonomy, the risk rules, and the empty-input behaviour."""
from cisco_toolkit.analyze import compute_application_intelligence
from cisco_toolkit.model import InterfaceData

_TIER_RANK = {"On-air critical": 0, "Production": 1, "Support": 2}


def _sm(ptp=None, groups=None, queriers=None):
    return {"multicast": {"ptp": ptp or {}, "classified_groups": groups or [],
                          "igmp_queriers": queriers or []}}


def test_taxonomy_assigns_primary_domains():
    ai = {
        "SW01-BC-DANTE-CAR6": {"Gi1/0/1": InterfaceData(port="Gi1/0/1", vlan="10")},
        "SW01-BC-NEXIS-CAR05": {"Gi1/0/1": InterfaceData(port="Gi1/0/1", vlan="11")},
        "MERIDIAN-SW-ROBOTICS-152": {"Gi1/0/1": InterfaceData(port="Gi1/0/1", vlan="12")},
        "AS01-MGM-CA05R34": {"Gi1/0/1": InterfaceData(port="Gi1/0/1", vlan="13")},
        "MERIDIAN-SW-043": {"Vlan20": InterfaceData(port="Vlan20", multicast_info="PIM Sparse")},
        "AS99-GENERIC-X": {"Gi1/0/1": InterfaceData(port="Gi1/0/1", vlan="14")},
    }
    out = compute_application_intelligence(ai, [], {}, _sm(), [], [], [])
    dom = {d["id"]: d for d in out["domains"]}
    assert "SW01-BC-DANTE-CAR6" in dom["audio"]["switches"]
    assert "SW01-BC-NEXIS-CAR05" in dom["storage"]["switches"]
    assert "MERIDIAN-SW-ROBOTICS-152" in dom["robotics"]["switches"]
    assert "AS01-MGM-CA05R34" in dom["mgmt"]["switches"]
    assert "MERIDIAN-SW-043" in dom["media"]["switches"]            # by observed multicast, not a token
    assert "AS99-GENERIC-X" in dom["general"]["switches"]            # no signal -> not over-claimed
    # deterministic: domains ordered by criticality tier
    tiers = [d["tier"] for d in out["domains"]]
    assert tiers == sorted(tiers, key=lambda t: _TIER_RANK[t])
    assert out["summary"]["n_on_air_critical"] == 3                  # audio + robotics + media


def test_media_ptp_not_boundary_clocked_is_high_and_attributes_groups():
    ai = {"ACS01-BC-X": {"Vlan20": InterfaceData(port="Vlan20", multicast_info="PIM")}}
    sm = _sm(ptp={"ACS01-BC-X": {"operational": False}},
             groups=[{"group": "224.0.1.129", "name": "PTP-primary",
                      "broadcast": True, "category": "Broadcast-AV"}])
    out = compute_application_intelligence(ai, [], {}, sm, [], [], [])
    media = next(d for d in out["domains"] if d["id"] == "media")
    assert media["ptp_present"] and not media["ptp_boundary_clocked"]
    r = next(r for r in media["risks"] if "boundary-clocked" in r["title"])
    assert r["severity"] == "High" and "2059" in r["standard"]
    assert media["media_groups"] and media["media_groups"][0]["name"] == "PTP-primary"


def test_boundary_clocked_media_has_no_ptp_risk():
    ai = {"ACS01-BC-X": {"Vlan20": InterfaceData(port="Vlan20", multicast_info="PIM")}}
    sm = _sm(ptp={"ACS01-BC-X": {"operational": True}})
    out = compute_application_intelligence(ai, [], {}, sm, [], [], [])
    media = next(d for d in out["domains"] if d["id"] == "media")
    assert media["ptp_boundary_clocked"] is True
    assert not any("boundary-clocked" in r["title"] for r in media["risks"])


def test_querier_split_is_subnet_scoped():
    # two queriers in the SAME /24 = real split-brain; same VLAN id reused in a DIFFERENT /24 = not a fault
    ai = {"swA": {"Vlan1": InterfaceData(port="Vlan1")}, "swB": {"Vlan1": InterfaceData(port="Vlan1")},
          "swC": {"Vlan12": InterfaceData(port="Vlan12")}, "swD": {"Vlan12": InterfaceData(port="Vlan12")}}
    sm = _sm(queriers=[
        {"switch": "swA", "vlan": "1", "querier": "10.215.0.5"},
        {"switch": "swB", "vlan": "1", "querier": "10.215.0.21"},     # same /24 -> split-brain
        {"switch": "swC", "vlan": "12", "querier": "10.202.12.2"},
        {"switch": "swD", "vlan": "12", "querier": "10.203.12.2"},    # different /24 -> NOT flagged
    ])
    out = compute_application_intelligence(ai, [], {}, sm, [], [], [])
    splits = [c for c in out["cross_domain_risks"] if c["kind"] == "querier-split"]
    vlans = {c["vlan"] for c in splits}
    assert "1" in vlans and "12" not in vlans
    s1 = next(c for c in splits if c["vlan"] == "1")
    assert s1["subnet"] == "10.215.0.0/24" and "RFC 4541" in s1["standard"]


def test_on_air_domain_spanning_waves_is_flagged_make_before_break():
    ai = {"SW01-BC-DANTE-A": {"Gi1/0/1": InterfaceData(port="Gi1/0/1", vlan="10")},
          "SW02-BC-DANTE-B": {"Gi1/0/1": InterfaceData(port="Gi1/0/1", vlan="10")}}
    mg = [{"group": "Wave-1", "switches": ["SW01-BC-DANTE-A"]},
          {"group": "Wave-2", "switches": ["SW02-BC-DANTE-B"]}]
    out = compute_application_intelligence(ai, [], {}, _sm(), [], mg, [])
    audio = next(d for d in out["domains"] if d["id"] == "audio")
    assert audio["spans_waves"] and len(audio["waves"]) == 2
    r = next(r for r in audio["risks"] if "split across migration waves" in r["title"])
    assert r["severity"] == "High" and "2022-7" in r["standard"]


def test_storage_dual_leg_split_is_flagged():
    ai = {"SW01-BC-NEXIS-A": {"Gi1/0/1": InterfaceData(port="Gi1/0/1", vlan="11")},
          "SW02-BC-NEXIS-B": {"Gi1/0/1": InterfaceData(port="Gi1/0/1", vlan="11")}}
    dep = {"dual_homed": [{"mac": "aa", "switches": ["SW01-BC-NEXIS-A", "SW02-BC-NEXIS-B"],
                           "split_across_groups": True, "endpoint_class": "Storage"}]}
    out = compute_application_intelligence(ai, [], dep, _sm(), [], [], [])
    storage = next(d for d in out["domains"] if d["id"] == "storage")
    assert any("Dual-homed endpoint leg" in r["title"] for r in storage["risks"])


def test_class_fallback_health_and_punchlist_rollup():
    ai = {"NODE-X": {"Gi1/0/1": InterfaceData(port="Gi1/0/1", vlan="10")}}
    ident = [{"host": "NODE-X", "port": "Gi1/0/1", "vlan": "10", "endpoint_class": "Server", "mac": "x"}]
    hs = [{"switch": "NODE-X", "band": "Critical", "score": 10}]
    pl = [{"severity": "High", "category": "L3", "devices": ["NODE-X"], "title": "x"}]
    out = compute_application_intelligence(ai, ident, {}, _sm(), hs, [], pl)
    comp = next(d for d in out["domains"] if d["id"] == "compute")
    assert "NODE-X" in comp["switches"] and comp["endpoint_count"] == 1
    assert "dominant endpoint class" in comp["evidence"]
    assert comp["health"]["worst_band"] == "Critical" and comp["health"]["n_critical"] == 1
    titles = [r["title"] for r in comp["risks"]]
    assert any("Critical/Poor health" in t for t in titles)
    assert any("punch-list" in t for t in titles)


def test_empty_inputs_are_well_formed():
    out = compute_application_intelligence({}, None, None, None, None, None, None)
    assert out["domains"] == [] and out["cross_domain_risks"] == []
    assert out["summary"]["n_domains"] == 0 and out["taxonomy_version"] == "app-domains/3"
    assert out["edges"] == [] and out["keystones"] == [] and out["cutover_order"] == []
    assert out["summary"]["pilot_domain"] == "" and out["summary"]["last_domain"] == ""
    # a host with no ports / no signal still degrades cleanly to the General bucket
    out2 = compute_application_intelligence({"h": {}}, [], {}, {}, [], [], [])
    assert [d["id"] for d in out2["domains"]] == ["general"]


def test_output_is_json_serializable_and_deterministic():
    import json
    ai = {"SW01-BC-DANTE-A": {"Gi1/0/1": InterfaceData(port="Gi1/0/1", vlan="10")},
          "AS01-MGM-X": {"Gi1/0/1": InterfaceData(port="Gi1/0/1", vlan="11")}}
    a = compute_application_intelligence(ai, [], {}, _sm(), [], [], [])
    b = compute_application_intelligence(ai, [], {}, _sm(), [], [], [])
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# ---- V3.23.113: inter-domain dependency edges ----

def test_edges_shared_subnet_and_dual_homed_merge_into_one_pair():
    ai = {"SW01-BC-NEXIS-A": {"Gi1/0/1": InterfaceData(port="Gi1/0/1", vlan="11")},
          "AS01-MGM-X": {"Gi1/0/1": InterfaceData(port="Gi1/0/1", vlan="13")}}
    si = {"per_device": [
        {"host": "SW01-BC-NEXIS-A", "destination_subnets": ["10.0.5.0/24"], "served_subnets": []},
        {"host": "AS01-MGM-X", "destination_subnets": ["10.0.5.0/24"], "served_subnets": []}]}
    dep = {"dual_homed": [{"mac": "aa", "switches": ["SW01-BC-NEXIS-A", "AS01-MGM-X"]}]}
    out = compute_application_intelligence(ai, [], dep, _sm(), [], [], [], subnet_intelligence=si)
    assert len(out["edges"]) == 1
    e = out["edges"][0]
    assert {e["source_id"], e["target_id"]} == {"storage", "mgmt"}
    assert "shared-subnet" in e["kinds"] and "dual-homed" in e["kinds"] and e["weight"] == 2
    assert e["confidence"] == "Confirmed"            # dual-homed present (no physical link)
    dom = {d["id"]: d for d in out["domains"]}
    assert dom["storage"]["degree"] == 2 and dom["mgmt"]["degree"] == 2
    assert out["keystones"][0]["degree"] == 2 and out["summary"]["n_edges"] == 1


def test_edge_physical_link_from_cdp():
    ai = {"SW01-BC-DANTE-A": {"Te1/1": InterfaceData(port="Te1/1", cdp_neighbor="AS01-MGM-X",
                                                     neighbor_port="Te1/2")},
          "AS01-MGM-X": {"Te1/1": InterfaceData(port="Te1/1")}}
    out = compute_application_intelligence(ai, [], {}, _sm(), [], [], [])
    assert len(out["edges"]) == 1
    e = out["edges"][0]
    assert {e["source_id"], e["target_id"]} == {"audio", "mgmt"}
    assert e["kinds"] == ["physical-link"] and e["confidence"] == "Confirmed-high"


def test_media_coupling_adds_note_and_on_air_risk():
    ai = {"ACS01-BC-X": {"Te1/1": InterfaceData(port="Te1/1", multicast_info="PIM",
                                                cdp_neighbor="AS01-MGM-Y", neighbor_port="Te1/2")},
          "AS01-MGM-Y": {"Te1/1": InterfaceData(port="Te1/1")}}
    out = compute_application_intelligence(ai, [], {}, _sm(), [], [], [])
    e = out["edges"][0]
    assert e["media"] is True and "multicast" in e["migration_note"].lower()
    kinds = [c["kind"] for c in out["cross_domain_risks"]]
    assert "on-air-coupling" in kinds and "keystone-domain" in kinds
    risk = next(c for c in out["cross_domain_risks"] if c["kind"] == "on-air-coupling")
    assert "Media Fabric" in risk["title"] and "2022-7" in risk["standard"]


def test_isolated_domain_has_no_edges():
    ai = {"AS99-X": {"Gi1/0/1": InterfaceData(port="Gi1/0/1", vlan="10")}}
    out = compute_application_intelligence(ai, [], {}, _sm(), [], [], [])
    assert out["edges"] == [] and out["keystones"] == []
    assert out["summary"]["n_edges"] == 0 and out["summary"]["keystone_domain"] == ""


# ---- V3.23.114: criticality score + recommended cutover order ----

def test_cutover_pilots_low_risk_and_lasts_on_air():
    ai = {"SW01-BC-DANTE-A": {"Vlan10": InterfaceData(port="Vlan10", multicast_info="PIM")},
          "AS99-BACKOFFICE": {"Gi1/0/1": InterfaceData(port="Gi1/0/1", vlan="20")}}
    sm = _sm(ptp={"SW01-BC-DANTE-A": {"operational": False}},
             groups=[{"group": "224.0.1.129", "name": "PTP-primary", "broadcast": True,
                      "category": "Broadcast-AV"}])
    hs = [{"switch": "SW01-BC-DANTE-A", "band": "Critical"}, {"switch": "AS99-BACKOFFICE", "band": "Good"}]
    out = compute_application_intelligence(ai, [], {}, sm, hs, [], [])
    dom = {d["id"]: d for d in out["domains"]}
    # the on-air audio domain is more critical than the healthy back-office domain
    assert dom["audio"]["criticality_score"] > dom["general"]["criticality_score"]
    assert dom["audio"]["cutover"]["band"] in ("Late", "Last")     # on-air never an early pilot
    co = out["cutover_order"]
    assert [c["order"] for c in co] == list(range(1, len(co) + 1))  # contiguous 1..N
    assert co[0]["domain"] == dom["general"]["domain"]             # lowest-risk pilots first
    assert co[-1]["domain"] == dom["audio"]["domain"]             # on-air last
    assert out["summary"]["pilot_domain"] == co[0]["domain"]
    assert out["summary"]["last_domain"] == co[-1]["domain"]


def test_criticality_scores_bounded_and_cutover_well_formed():
    ai = {"SW01-BC-DANTE-A": {"Vlan10": InterfaceData(port="Vlan10", multicast_info="PIM")},
          "AS99-X": {"Gi1/0/1": InterfaceData(port="Gi1/0/1", vlan="20")}}
    out = compute_application_intelligence(ai, [], {}, _sm(ptp={"SW01-BC-DANTE-A": {"operational": False}}),
                                           [{"switch": "SW01-BC-DANTE-A", "band": "Critical"}], [], [])
    for d in out["domains"]:
        assert 0 <= d["criticality_score"] <= 100
        assert d["cutover"]["order"] >= 1
        assert d["cutover"]["band"] in ("Pilot", "Early", "Mid", "Late", "Last")
