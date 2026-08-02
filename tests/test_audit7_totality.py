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
non-str could never have matched a device key anyway.

MECHANICALLY CHECKED, and the claim is scoped to what was checked: reverting any ONE `_scalar`/`_hkey` call
site in design_advisor.py (`_scalar(X)` -> `True`, `_hkey(X)` -> `X`) turns this file RED — with one known
exception, `_signals`' `lifecycle_unknown_hosts` filter, which sits inside a `sorted(str(...) for ...)` and so
can only ever emit a poisoned host NAME, never raise; its reversion is not observable in the blueprint this
file inspects. That claim used to read "reverting any single guard re-raises the TypeError below" and was
false for SEVEN sites: four (single_gw_devices, the IPv6-FHS vlan set, l2_wide_hosts, the SD-WAN
control-connection dedup) were simply never reached by the fixture — each needed one more key to get past an
upstream `continue`/`if` — and the two wave-plan sites cannot raise at all, because `_skey` is a total sort
key. Those are pinned below on shape instead. When adding a guard, extend the fixture until reverting it
fails here; a guard this fixture cannot reach is pinned by nothing.
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
            # single_gw_devices: its own set comprehension, reached only by a row that is BOTH
            # risk='single-gateway' AND carries a switch. The first row above pairs a poison vlan
            # with no switch and the later two carry a poison switch with no single-gateway risk,
            # so neither reached this site and its guard was revertible with the file still green.
            {"vlan": 11, "risk": "single-gateway", "switch": _D},
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
        # dualstack is the gate on the whole IPv6-FHS branch: without it the loop `continue`s before
        # the ipv6_svi_vlans set-add, so the FHS guard this section claims to cover was never run.
        "ipv6_fhs": {"c": {"dualstack": True, "ipv6_svi_vlans": [_D], "ra_guard_present": False}},
        "interfaces": {"c": {"Gi0": {"switchport_mode": "access"}}},
        "security": {"c": {"findings": [{"status": "fail", "id": _D}]}},
        "aci": {"apic1": {"vrfs": [{"tenant": _D, "name": _D, "dn": _D, "pc_enf_pref": "unenforced"}]}},
        # vlan1_spans is what makes the wide-L2 host recovery read `switches` at all (`wide_hit`);
        # without it only the wave-plan read the list, and the l2_wide_hosts set-add was unreached.
        "move_groups": [{"switches": ["realsw", _D], "vlan1_spans": [1]},
                        # ...and a group whose switches are ALL poison. The wave plan drops it; kept
                        # unguarded it survives as a wave with zero members, which the cross-group
                        # tie-break sort then indexes. A group with one real switch cannot show this.
                        {"switches": [_D]}],
        # SD-WAN control-connection dedup: a short-but-UP row keys a (host, system_ip) tuple into a
        # set, so a dict system_ip poisons the tuple. Needs expected/actual ints with actual<expected.
        "sdwan": {"vm1": {"control_connections": [
            {"state": "up", "expected": 3, "actual": 1, "system_ip": _D}]}},
        "addressing_conflicts": {"dup_ip": [{"where": [[_D, "x"]]}]},
        "endpoint_dependencies": {"dual_homed": [{"switches": [_D, "realsw"]}]},
    }
    bp = compute_design_blueprint(hostile, {})                       # must NOT raise (was: unhashable / sorted-mixed)
    assert isinstance(bp, dict) and isinstance(bp.get("decisions"), list)
    # Not every guard in the family can be pinned by "does it raise": `_skey` is a TOTAL sort key, so
    # the wave-plan sites stay crash-free with their `_scalar` filter reverted and merely PUBLISH the
    # poison as a migration-wave member. Assert the published shape instead, or those two guards are
    # revertible with this file still green (which they were).
    waves = ((bp.get("target_state") or {}).get("wave_plan") or {}).get("waves") or []
    for w in waves:
        for s in w.get("switches") or []:
            assert isinstance(s, (str, int, float)), \
                f"a poisoned leaf was published as a migration-wave switch: {s!r} in {w}"
        assert w.get("switches"), f"an empty wave was published: {w}"
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
