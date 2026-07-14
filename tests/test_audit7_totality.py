"""[audit-7 totality-crash batch] An UNHASHABLE dict/list leaf reaching a set/dict comprehension raises
`TypeError: unhashable type: 'dict'` (and a `sorted()` over the mix raises `'<' not supported`) -- a fail-soft
HTTP 500 on the UNAUTHENTICATED webapp compute routes (/design, /architecture_coverage, /archreview), reachable
because those endpoints run the engine over an uploaded snapshot. This is a DISTINCT class from the audit-6
leaf-COERCION batch (int()/round()/float()/.strip() on a wrong-type scalar): here the leaf is used as a set
MEMBER, a dict KEY, a dedup-tuple element, or a `sorted()` element.

Discovered by a recursive dict-poison fuzz (replace a snapshot leaf with {"x": 1}) over the golden snapshot,
driven through every untrusted compute fn. Each site is guarded by design_advisor._scalar (FILTER a comprehension
so a poison leaf is dropped while valid scalars pass through unchanged -- dedup/counts/sort order preserved) or
._hkey (coerce a dict KEY / dedup-tuple element to a hashable form), or an inline `isinstance(sw, str)` where a
non-str could never have matched a device key anyway. Reverting any single guard re-raises the TypeError below.
"""

# A dict where a scalar (vlan/vid/host/switch/subnet/gateway/id/name/...) is expected -> unhashable in a set.
_D = {"x": 1}


def test_compute_design_blueprint_tolerates_dict_valued_set_and_key_leaves():
    """Every set/dict-comprehension, set.add, dict-key and sorted() site in _signals + the target-state
    builders that keys on a device-derived leaf must DROP the poison and degrade, not 500. Sites covered (one
    hostile section each): l3_forwarding.vlan (single_gw) / .switch (v2gw + reserved-vlan); fhrp.vid +
    members.host (broken-FHRP); physical_health.switch (phy-dirty); protocol_intelligence.switch (bundle);
    subnet_intelligence served_subnets.subnet + .gateway (vlan->subnet map); endpoint_identity.host (gw-move);
    syslog_intelligence.detections.host (mac-flap); ipv6_fhs.ipv6_svi_vlans (FHS); security.findings.id
    (fail-host map KEY); aci.vrfs tenant/name/dn (ACI move-group KEY + unenforced-VRF set); move_groups.switches
    (wave-plan sorted); addressing_conflicts.dup_ip.where (addr-overlap); endpoint_dependencies.dual_homed.switches."""
    from cisco_toolkit.design_advisor import compute_architecture_coverage, compute_design_blueprint
    hostile = {
        "devices": {"c": {}},
        "l3_forwarding": [
            {"vlan": _D, "risk": "single-gateway"},
            {"vlan": 7, "primary_subnet": "10.0.0.0/24", "switch": _D},
            {"vlan": 4000, "svi_ip": "10.0.0.1/24", "switch": _D},
        ],
        "fhrp": [{"vid": _D, "issues": ["split-brain"], "members": [{"host": _D}]}],
        "physical_health": [{"switch": _D, "crc_errors": 9}],
        "protocol_intelligence": [{"protocol": "EtherChannel", "severity": "High", "switch": _D}],
        "subnet_intelligence": {"per_device": [{"served_subnets": [
            {"vlan": 8, "subnet": _D, "gateway": "10.0.0.1"},
            {"vlan": 9, "subnet": "10.9.0.0/24", "gateway": _D},
        ]}]},
        "endpoint_identity": [{"vlan": 9, "host": _D}],
        "syslog_intelligence": {"detections": [{"kind": "mac-flap", "host": _D}]},
        "ipv6_fhs": {"c": {"ipv6_svi_vlans": [_D], "ra_guard_present": False}},
        "interfaces": {"c": {"Gi0": {"switchport_mode": "access"}}},
        "security": {"c": {"findings": [{"status": "fail", "id": _D}]}},
        "aci": {"apic1": {"vrfs": [{"tenant": _D, "name": _D, "dn": _D, "pc_enf_pref": "unenforced"}]}},
        "move_groups": [{"switches": ["realsw", _D]}],
        "addressing_conflicts": {"dup_ip": [{"where": [[_D, "x"]]}]},
        "endpoint_dependencies": {"dual_homed": [{"switches": [_D, "realsw"]}]},
    }
    bp = compute_design_blueprint(hostile, {})                       # must NOT raise (was: unhashable / sorted-mixed)
    assert isinstance(bp, dict) and isinstance(bp.get("decisions"), list)
    # and the coverage SSOT computed from that blueprint must degrade too (the /architecture_coverage path)
    snap = dict(hostile)
    snap["design_blueprint"] = bp
    cov = compute_architecture_coverage(snap)
    assert isinstance(cov, dict) and isinstance(cov.get("classes"), list)


def test_architecture_coverage_tolerates_dict_valued_decision_id():
    """The /architecture_coverage endpoint KEEPS an uploaded dict design_blueprint (it recomputes only when the
    section is not a dict), so a decision carrying a dict-valued 'id' reaches `{d.get('id') for d in decisions}`
    -- an unhashable set member. It must degrade, not 500."""
    from cisco_toolkit.design_advisor import compute_architecture_coverage
    snap = {"devices": {"c": {}},
            "design_blueprint": {"decisions": [{"id": _D, "priority": "High"}, {"id": "real-id"}]}}
    cov = compute_architecture_coverage(snap)
    assert isinstance(cov, dict) and isinstance(cov.get("classes"), list)


def test_compute_architecture_review_tolerates_dict_valued_switch():
    """archreview._fleet_model tests `r.get('switch') in devices` and `.add(r.get('switch'))` (and the SVI-owner
    loop) on the raw l3_forwarding switch; a dict switch made the `in devices` membership hash an unhashable key
    on the UNWRAPPED /archreview endpoint. A non-str can never be a device key, so it is dropped."""
    from cisco_toolkit.archreview import compute_architecture_review
    hostile = {"devices": {"c": {}},
               "l3_forwarding": [{"vlan": 7, "switch": _D}, {"vlan": 8, "switch": "c"}]}
    ar = compute_architecture_review(hostile)                        # must NOT raise (was: unhashable membership)
    assert isinstance(ar, dict) and isinstance(ar.get("checks"), list)
