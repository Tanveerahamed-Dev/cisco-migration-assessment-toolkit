"""Tests for the gated, evidence-grounded EVPN-migration guardrails (cisco_toolkit/evpn_migration.py)."""
from cisco_toolkit import evpn_migration as em
from cisco_toolkit.design_advisor import compute_design_blueprint, compute_design_nrfu


# ----------------------------------------------------------------- NX-OS version comparator (format-fidelity)
def test_nxos_version_tuple_parses_real_release_forms():
    assert em._nxos_version_tuple("10.2(3)") == (10, 2, 3)
    assert em._nxos_version_tuple("10.3(4a)") == (10, 3, 4)        # letter rebuild suffix ignored
    assert em._nxos_version_tuple("9.3(10)") == (9, 3, 10)
    assert em._nxos_version_tuple("7.0(3)I7(9)") == (7, 0, 3)      # I7 platform sub-train ignored for the gate
    assert em._nxos_version_tuple("6.0(2)N2(3)") == (6, 0, 2)      # N2 sub-train ignored
    assert em._nxos_version_tuple("garbage") is None
    assert em._nxos_version_tuple("") is None


def test_nxos_below_coexist_gate_is_10_2_3():
    assert em._nxos_below_coexist("10.2(3)") is False             # the gate itself: NOT below
    assert em._nxos_below_coexist("10.2(2)") is True              # one maint below
    assert em._nxos_below_coexist("10.3(1)") is False            # newer minor
    assert em._nxos_below_coexist("11.1(1)") is False            # newer major
    assert em._nxos_below_coexist("9.3(10)") is True             # older major, high maint still below
    assert em._nxos_below_coexist("6.0(2)N2(3)") is True
    assert em._nxos_below_coexist("7.0(3)I7(9)") is True
    assert em._nxos_below_coexist("not-a-version") is None       # coverage-honest: not asserted either way


def test_is_nxos_detection():
    assert em._is_nxos("Nexus 6001", "N6K-C6001-64P") is True
    assert em._is_nxos("", "N9K-C93180YC-FX") is True
    assert em._is_nxos("NX-OS", "") is True
    assert em._is_nxos("Catalyst 9300", "C9300-48U") is False
    assert em._is_nxos("", "WS-C3850-48P") is False


# ----------------------------------------------------------------- gate (coverage-honesty)
def _evpn_snap():
    """A fabric-scale brownfield with mixed NX-OS releases, no FHRP, and a vPC pair."""
    return {
        "lifecycle_risk": {"per_device": [
            {"host": "n6k1", "platform": "Nexus 6001", "model": "N6K-C6001", "sw_version": "6.0(2)N2(3)"},   # below
            {"host": "n9k1", "platform": "Nexus 9300", "model": "N9K-C93180", "sw_version": "9.3(10)"},      # below
            {"host": "n9k2", "platform": "Nexus 9300", "model": "N9K-C93180", "sw_version": "10.3(2)"},      # at/above
            {"host": "cat1", "platform": "Catalyst 9300", "model": "C9300-48", "sw_version": "17.9.3"},      # not NX-OS
        ]},
        "l3_forwarding": [{"switch": "n9k1", "vlan": 10, "fhrp": "none"},
                          {"switch": "n9k1", "vlan": 20, "fhrp": "none"}],
        "vpc": {"n9k1": {"domain_id": 1}, "n9k2": {"domain_id": 1}},
        # parse_*_roots publishes a {host: {vlan: {...}}} DICT, not a list — count the hosts, not _as_list (=0)
        "stp_roots": {"n9k1": {"10": {"is_root": True}}, "n9k2": {"10": {"is_root": False}}, "cat1": {}},
    }


def test_silent_when_not_a_fabric_target():
    """A small non-DC estate with no stated fabric model -> not applicable -> renders nothing (coverage-honest)."""
    out = em.compute_evpn_migration_guardrails({"l3_forwarding": [{"switch": "a", "vlan": 1, "fhrp": "none"}]})
    assert out["applicable"] is False and out["guardrails"] == []


def test_silent_when_target_is_aci():
    """Even at fabric scale, an ACI target is a DIFFERENT migration playbook -> these EVPN guardrails stay silent."""
    out = em.compute_evpn_migration_guardrails(_evpn_snap(), {"fabric_operating_model": "aci"})
    assert out["applicable"] is False and out["guardrails"] == []


def test_applicable_when_nxos_evpn_requirement_confirmed():
    out = em.compute_evpn_migration_guardrails(_evpn_snap(), {"fabric_operating_model": "nxos-evpn"})
    assert out["applicable"] is True
    assert "requirement-confirmed" in out["model_basis"]
    ids = {g["id"] for g in out["guardrails"]}
    assert ids == {
        "evpn-pre-nxos-1023-gateway-coexistence", "evpn-pre-gateway-vmac-transition",
        "evpn-cut-single-active-l2-interconnect", "evpn-cut-vpc-back-to-back-method", "evpn-rollback-triggers"}
    # every guardrail is cited and grounded
    assert all(g["source"] and g["basis"] for g in out["guardrails"])
    # CUT-1 counts the {host: {...}} stp_roots DICT (not _as_list, which would read 0) + the vPC domains
    cut1 = next(g for g in out["guardrails"] if g["id"] == "evpn-cut-single-active-l2-interconnect")
    assert "STP present on 3 device(s)" in cut1["basis"] and "vPC domain(s)" in cut1["basis"]
    assert cut1["severity"] == "Critical"


def test_applicable_as_engine_default_without_requirement():
    """At fabric scale (>=30 inventoried devices) with NO stated model, the guardrails fire as the engine
    default and SAY so. (sig['inventory'] reads collection_completeness.summary.inventory, not the device list.)"""
    snap = _evpn_snap()
    snap["collection_completeness"] = {"summary": {"inventory": 44}}
    out = em.compute_evpn_migration_guardrails(snap)
    assert out["applicable"] is True and "engine-default" in out["model_basis"]


# ----------------------------------------------------------------- evidence grounding
def test_version_gate_enumerates_only_below_nxos_devices():
    out = em.compute_evpn_migration_guardrails(_evpn_snap(), {"fabric_operating_model": "nxos-evpn"})
    g = next(x for x in out["guardrails"] if x["id"] == "evpn-pre-nxos-1023-gateway-coexistence")
    assert g["severity"] == "High"
    assert "2 of 3 NX-OS device(s)" in g["basis"]      # n6k1 + n9k1 below; n9k2 above; cat1 not NX-OS
    assert "n6k1 6.0(2)N2(3)" in g["basis"] and "n9k1 9.3(10)" in g["basis"]
    assert "n9k2" not in g["basis"] and "cat1" not in g["basis"]


def test_gateway_guardrail_adapts_to_fhrp_presence():
    # FHRP absent -> physical-MAC transition phrasing
    out0 = em.compute_evpn_migration_guardrails(_evpn_snap(), {"fabric_operating_model": "nxos-evpn"})
    g0 = next(x for x in out0["guardrails"] if x["id"] == "evpn-pre-gateway-vmac-transition")
    assert "0 running FHRP/HSRP" in g0["basis"] and "PHYSICAL gateway MAC" in g0["basis"]
    # FHRP present -> vMAC-alignment phrasing
    snap = _evpn_snap()
    snap["l3_forwarding"] = [{"switch": "n9k1", "vlan": 10, "fhrp": "hsrp"},
                             {"switch": "n9k1", "vlan": 20, "fhrp": "none"}]
    out1 = em.compute_evpn_migration_guardrails(snap, {"fabric_operating_model": "nxos-evpn"})
    g1 = next(x for x in out1["guardrails"] if x["id"] == "evpn-pre-gateway-vmac-transition")
    assert "1 of 2 gateway(s) run FHRP/HSRP" in g1["basis"]
    assert "2020.0000.00aa" in g1["detail"] and "gratuitous arp" in g1["detail"].lower()


# ----------------------------------------------------------------- design-NRFU integration (assembly mirror)
def test_blueprint_folds_in_evpn_migration_and_nrfu_surfaces_acceptance():
    """compute_design_blueprint folds the guardrails INTO the blueprint (so the published blueprint stays
    reproducible from the snapshot — the SSOT contract test_pipeline_inprocess locks). compute_design_nrfu then
    surfaces them as a SEPARATE evpn_acceptance list, leaving the per-decision items<->recommended contract
    untouched; a blueprint without the key (an older snapshot) yields an empty list, not a crash."""
    snap = _evpn_snap()
    snap["collection_completeness"] = {"summary": {"inventory": 44}}
    bp = compute_design_blueprint(snap, {"fabric_operating_model": "nxos-evpn"})
    assert bp["evpn_migration"]["applicable"] is True                 # folded into the canonical blueprint
    nrfu = compute_design_nrfu(bp)
    assert nrfu["n_items"] == len(nrfu["items"])                      # per-decision items contract UNCHANGED
    acc = nrfu["evpn_acceptance"]
    assert len(acc) == 5
    assert {a["decision_id"] for a in acc} == {g["id"] for g in bp["evpn_migration"]["guardrails"]}
    assert all(a["pass_criteria"].startswith("Verify:") and a["principle_citation"] for a in acc)
    # a blueprint WITHOUT the key (older snapshot) -> empty acceptance, no crash
    bp.pop("evpn_migration")
    assert compute_design_nrfu(bp)["evpn_acceptance"] == []
