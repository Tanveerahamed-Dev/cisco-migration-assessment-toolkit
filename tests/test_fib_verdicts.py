"""Two coverage-honest verdict DIMENSIONS on the FIB path tracer (MASTER_PLAN 2026-07-05 §3.4;
orchestration-roadmap Frontier :231-:232).

VERDICT 1 -- MTU / jumbo-blackhole along the computed path. trace_fib_path collects each traced hop's
egress-interface MTU (from snap['interfaces'][host][out_intf]), computes path_mtu = min observed, and adds
{mtu_min, mtu_bottleneck_hop, mtu_verdict} plus (when a required/jumbo MTU is supplied) per-hop
jumbo-blackhole flags. COVERAGE-HONEST: a missing MTU is ABSTENTION ('INDETERMINATE'), never a fabricated
1500-byte pass -- a 1500-byte underlay silently drops VXLAN and mimics random loss, the single most
engagement-relevant missing check (EVPN research).

VERDICT 2 -- return-path / RPF asymmetry. trace_bidirectional composes a forward + a reverse trace and
classifies symmetric / asymmetric / INDETERMINATE. 'works one way, drops the other' -- pure composition, no
device contact.

All over small synthetic snapshots; tests/test_fib.py proves the 35 pre-existing traces stay backward-compatible.
"""
from cisco_toolkit import fib


# --------------------------------------------------------------------------- fixtures ---
def _snap_uniform():
    """R1 --transit 10.0.12.0/24-- R2. Both traced egress interfaces carry MTU 9216 -> a uniform jumbo path."""
    return {
        "routes": {
            "R1": [{"prefix": "10.1.1.0/24", "next_hop": "", "out_intf": "Vlan1", "source": "connected"},
                   {"prefix": "10.0.12.0/24", "next_hop": "", "out_intf": "Gi0/1", "source": "connected"},
                   {"prefix": "0.0.0.0/0", "next_hop": "10.0.12.2", "out_intf": "Gi0/1", "source": "static"}],
            "R2": [{"prefix": "10.0.12.0/24", "next_hop": "", "out_intf": "Gi0/1", "source": "connected"},
                   {"prefix": "10.2.2.0/24", "next_hop": "", "out_intf": "Vlan2", "source": "connected"}],
        },
        "interfaces": {
            "R1": {
                "Gi0/1": {"port": "Gi0/1", "mtu": "9216", "svi_ip": "10.0.12.1/24",
                           "mtu_semantics": "effective_ipv4_mtu"},
                "Vlan1": {"port": "Vlan1", "mtu": "9216", "mtu_semantics": "effective_ipv4_mtu"},
            },
            "R2": {
                "Gi0/1": {"port": "Gi0/1", "mtu": "9216", "svi_ip": "10.0.12.2/24",
                           "mtu_semantics": "effective_ipv4_mtu"},
                "Vlan2": {"port": "Vlan2", "mtu": "9216", "mtu_semantics": "effective_ipv4_mtu"},
            },
        },
    }


def _snap_bottleneck():
    """Same topology, but R2's egress toward the dst is a 1500-byte port -> a mid-path bottleneck the source
    (9216) does not share. A VXLAN/jumbo flow silently blackholes there."""
    snap = _snap_uniform()
    snap["interfaces"]["R2"]["Vlan2"]["mtu"] = "1500"
    return snap


def _snap_missing_mtu():
    """R2's traced egress carries NO collected MTU -> the path MTU is INDETERMINATE (never assumed 1500)."""
    snap = _snap_uniform()
    snap["interfaces"]["R2"]["Vlan2"]["mtu"] = ""      # not collected
    return snap


# ============================================================== VERDICT 1: MTU / jumbo ===
def test_mtu_uniform_when_all_observed_hops_equal():
    t = fib.trace_fib_path(_snap_uniform(), "10.1.1.5", "10.2.2.9")
    assert t["status"] == "computed:reached"
    assert t["mtu_min"] == 9216
    assert t["mtu_verdict"] == "uniform"
    assert t["mtu_bottleneck_hop"] is None
    # additive keys never disturb the frozen result shape
    assert t["reached"] is True and t["computed"] is True


def test_mtu_bottleneck_names_the_lower_hop():
    t = fib.trace_fib_path(_snap_bottleneck(), "10.1.1.5", "10.2.2.9")
    assert t["mtu_min"] == 1500
    assert t["mtu_verdict"] == "bottleneck"
    b = t["mtu_bottleneck_hop"]
    assert b is not None and b["host"] == "R2" and b["out_intf"] == "Vlan2" and b["mtu"] == 1500


def test_mtu_indeterminate_never_assumes_1500_on_missing():
    """The core coverage-honesty guard: a hop with NO collected MTU makes the whole path MTU INDETERMINATE --
    it must NOT silently become a 1500 (or 9216) pass, and the verdict must disclose N of M."""
    t = fib.trace_fib_path(_snap_missing_mtu(), "10.1.1.5", "10.2.2.9")
    assert t["mtu_verdict"].startswith("INDETERMINATE")
    assert "MTU not collected" in t["mtu_verdict"]
    assert " 1 of " in t["mtu_verdict"]                 # exactly one of the hops was unobserved
    assert t["mtu_verdict"] != "uniform"
    # the observed hops are still surfaced (data not lost), but no fabricated 1500 appears
    assert t["mtu_min"] == 9216                          # min of what WAS observed (R1 side), never a fabricated 1500
    assert {"host": "R2", "out_intf": "Vlan2"} in t["mtu_unobserved_hops"]


def test_mtu_blank_egress_interface_is_an_explicit_blind_hop():
    snap = _snap_uniform()
    snap["routes"]["R1"][-1]["out_intf"] = ""

    t = fib.trace_fib_path(
        snap, "10.1.1.5", "10.2.2.9", required_mtu=1400,
    )

    assert t["status"] == "computed:reached"
    assert t["mtu_verdict"].startswith("INDETERMINATE")
    assert {
        "host": "R1", "out_intf": "", "reason": "egress_interface_not_observed",
    } in t["mtu_unobserved_hops"]


def test_unknown_nonblank_mtu_semantics_cannot_become_proof():
    snap = _snap_uniform()
    for ports in snap["interfaces"].values():
        for record in ports.values():
            record["mtu_semantics"] = "unknown_vendor_layer"

    t = fib.trace_fib_path(
        snap, "10.1.1.5", "10.2.2.9", required_mtu=1600,
    )

    assert t["status"] == "computed:reached"
    assert t["mtu_min"] is None
    assert t["mtu_verdict"].startswith("INDETERMINATE")
    assert len(t["mtu_unobserved_hops"]) == len(t["hops"])


def test_explicit_ipv4_mtu_semantics_reads_the_bound_ip_field_not_generic_copy():
    snap = _snap_uniform()
    snap["interfaces"]["R1"]["Gi0/1"].update({
        "mtu": "9216", "link_mtu": "9216", "ip_mtu": "1500",
        "mtu_semantics": "explicit_ipv4_mtu",
    })

    t = fib.trace_fib_path(
        snap, "10.1.1.5", "10.2.2.9", required_mtu=1600,
    )

    assert t["mtu_min"] == 1500
    assert t["mtu_verdict"].startswith("below_required")
    assert any(row["host"] == "R1" and row["mtu"] == 1500 for row in t["jumbo_blackhole"])

    # Older snapshots may carry the dedicated field without the newer provenance token. The dedicated layer
    # remains authoritative, but a generic-only value with no layer provenance is not proof.
    snap["interfaces"]["R1"]["Gi0/1"].pop("mtu_semantics")
    legacy_explicit = fib.trace_fib_path(
        snap, "10.1.1.5", "10.2.2.9", required_mtu=1600,
    )
    assert legacy_explicit["mtu_min"] == 1500
    assert legacy_explicit["mtu_verdict"].startswith("below_required")

    snap["interfaces"]["R1"]["Gi0/1"].pop("ip_mtu")
    generic_only = fib.trace_fib_path(
        snap, "10.1.1.5", "10.2.2.9", required_mtu=1600,
    )
    assert generic_only["mtu_verdict"].startswith("INDETERMINATE")
    assert {"host": "R1", "out_intf": "Gi0/1"} in generic_only["mtu_unobserved_hops"]


def test_required_mtu_flags_jumbo_blackhole_and_names_the_hop():
    """A required/jumbo target (e.g. 1550 for VXLAN, 9216 for a jumbo underlay) flags each observed hop whose
    MTU < required as a jumbo-blackhole risk, naming the hop."""
    t = fib.trace_fib_path(_snap_bottleneck(), "10.1.1.5", "10.2.2.9", required_mtu=9216)
    jb = t["jumbo_blackhole"]
    assert len(jb) == 1
    assert jb[0]["host"] == "R2" and jb[0]["out_intf"] == "Vlan2"
    assert jb[0]["mtu"] == 1500 and jb[0]["required"] == 9216


def test_required_mtu_no_flag_when_all_hops_meet_target():
    t = fib.trace_fib_path(_snap_uniform(), "10.1.1.5", "10.2.2.9", required_mtu=1550)
    assert t["jumbo_blackhole"] == []


def test_required_mtu_missing_hop_is_abstention_not_a_jumbo_flag():
    """A hop with no collected MTU can NOT be asserted a jumbo-blackhole (that would fabricate a drop) -- it is
    disclosed as unobserved instead. Absence of evidence is never a violation."""
    t = fib.trace_fib_path(_snap_missing_mtu(), "10.1.1.5", "10.2.2.9", required_mtu=9216)
    # R2's traced egress is unobserved -> it appears in unobserved_hops, NOT in jumbo_blackhole
    assert {"host": "R2", "out_intf": "Vlan2"} in t["mtu_unobserved_hops"]
    assert all(not (h["host"] == "R2" and h["out_intf"] == "Vlan2") for h in t["jumbo_blackhole"])


def test_required_mtu_uniformly_too_narrow_path_is_not_reported_uniform():
    """review #32: mtu_verdict was computed purely from the SPREAD of observed MTUs, so the bottleneck
    branch (mtu_min < mtu_max) could not fire on the shape that matters most — EVERY hop below the
    requirement, which is exactly the 1500-byte underlay that silently drops VXLAN. It reported the clean
    one-word 'uniform' while jumbo_blackhole listed every hop on the path."""
    snap = _snap_uniform()
    for host in ("R1", "R2"):
        for port in snap["interfaces"][host]:
            snap["interfaces"][host][port]["mtu"] = "1500"          # uniformly narrow: no spread at all
    t = fib.trace_fib_path(snap, "10.1.1.5", "10.2.2.9", required_mtu=1550)
    assert t["reached"] is True and t["mtu_min"] == 1500
    assert len(t["jumbo_blackhole"]) == 2                            # both traced hops are under 1550
    assert t["mtu_verdict"] != "uniform"
    assert t["mtu_verdict"].startswith("below_required")
    assert "1550" in t["mtu_verdict"]                                # names the requirement it fails
    # control: the same uniform path with a requirement it MEETS is still the clean 'uniform'
    assert fib.trace_fib_path(_snap_uniform(), "10.1.1.5", "10.2.2.9",
                              required_mtu=1550)["mtu_verdict"] == "uniform"
    # control: no requirement supplied -> nothing to violate, the spread verdict stands
    assert fib.trace_fib_path(snap, "10.1.1.5", "10.2.2.9")["mtu_verdict"] == "uniform"


def test_required_mtu_violation_keeps_disclosing_uncollected_hops():
    """A PROVEN below-required hop outranks the unobserved-hop abstention (it is measured, not inferred),
    but the blind spots must still be disclosed in the same verdict — never traded away for the headline."""
    snap = _snap_missing_mtu()                       # R2's Vlan2 MTU not collected; R1's hops are 9216
    snap["interfaces"]["R1"]["Gi0/1"]["mtu"] = "1500"
    t = fib.trace_fib_path(snap, "10.1.1.5", "10.2.2.9", required_mtu=9216)
    assert t["mtu_verdict"].startswith("below_required")
    assert "MTU not collected on 1 of" in t["mtu_verdict"]
    assert {"host": "R2", "out_intf": "Vlan2"} in t["mtu_unobserved_hops"]


def test_mtu_verdict_indeterminate_when_trace_does_not_reach():
    """If the trace itself is a lower bound / drop (no reached path), the MTU verdict abstains too -- there is no
    proven path to audit."""
    l2 = {"routes": {"R1": [{"prefix": "10.1.1.0/24", "source": "connected"}]}}   # L2 access, no L3 evidence
    t = fib.trace_fib_path(l2, "10.1.1.5", "8.8.8.8")
    assert t["reached"] is False
    assert t["mtu_verdict"].startswith("INDETERMINATE")
    assert t["mtu_min"] is None and t["mtu_bottleneck_hop"] is None


def test_mtu_keys_present_and_defaulted_on_bad_input():
    """The additive MTU keys are ALWAYS present (total), even on bad input -- callers can read them unconditionally."""
    t = fib.trace_fib_path(None, "1.1.1.1", "2.2.2.2")
    for k in ("mtu_min", "mtu_bottleneck_hop", "mtu_verdict", "mtu_unobserved_hops", "jumbo_blackhole"):
        assert k in t
    assert t["mtu_min"] is None and t["jumbo_blackhole"] == []


def test_mtu_reads_dataclass_interface_records_too():
    """snap['interfaces'][host][port] may be an InterfaceData dataclass (in-process, pre-serialization) rather
    than a plain dict -- the MTU probe must read either."""
    from cisco_toolkit.model import InterfaceData
    snap = _snap_uniform()
    snap["interfaces"]["R2"]["Vlan2"] = InterfaceData(
        port="Vlan2", mtu="1500", mtu_semantics="effective_ipv4_mtu",
    )
    t = fib.trace_fib_path(snap, "10.1.1.5", "10.2.2.9")
    assert t["mtu_min"] == 1500 and t["mtu_verdict"] == "bottleneck"


# ================================================ VERDICT 2: return-path / RPF asymmetry ===
def _snap_symmetric():
    """A -- R1 --transit-- R2 -- B. Both directions traverse the same L3 hosts and both reach -> symmetric."""
    return {
        "routes": {
            "R1": [{"prefix": "10.1.1.0/24", "next_hop": "", "out_intf": "Vlan1", "source": "connected"},
                   {"prefix": "10.0.12.0/24", "next_hop": "", "out_intf": "Gi0/1", "source": "connected"},
                   {"prefix": "10.2.2.0/24", "next_hop": "10.0.12.2", "out_intf": "Gi0/1", "source": "ospf"}],
            "R2": [{"prefix": "10.0.12.0/24", "next_hop": "", "out_intf": "Gi0/1", "source": "connected"},
                   {"prefix": "10.2.2.0/24", "next_hop": "", "out_intf": "Vlan2", "source": "connected"},
                   {"prefix": "10.1.1.0/24", "next_hop": "10.0.12.1", "out_intf": "Gi0/1", "source": "ospf"}],
        },
        "interfaces": {
            "R1": {"Gi0/1": {"svi_ip": "10.0.12.1/24"}},
            "R2": {"Gi0/1": {"svi_ip": "10.0.12.2/24"}},
        },
    }


def _snap_asymmetric():
    """Forward A->B reaches, but the REVERSE B->A drops: R2 has NO route back to 10.1.1.0/24 and is a proven
    router (it runs a learned route to 10.2.2 via a transit /30 + a static). 'works one way, drops the other'."""
    return {
        "routes": {
            "R1": [{"prefix": "10.1.1.0/24", "next_hop": "", "out_intf": "Vlan1", "source": "connected"},
                   {"prefix": "10.0.12.0/30", "next_hop": "", "out_intf": "Gi0/1", "source": "connected"},
                   {"prefix": "10.2.2.0/24", "next_hop": "10.0.12.2", "out_intf": "Gi0/1", "source": "static"}],
            # R2 is a proven L3 router (connected /30 transit) but has NO return route to 10.1.1.0/24 -> reverse drops.
            "R2": [{"prefix": "10.0.12.0/30", "next_hop": "", "out_intf": "Gi0/1", "source": "connected"},
                   {"prefix": "10.2.2.0/24", "next_hop": "", "out_intf": "Vlan2", "source": "connected"}],
        },
        "interfaces": {
            "R1": {"Gi0/1": {"svi_ip": "10.0.12.1/30"}},
            "R2": {"Gi0/1": {"svi_ip": "10.0.12.2/30"}},
        },
    }


def _snap_indeterminate_reverse():
    """Forward reaches, but the reverse is a LOWER BOUND (R2's return next-hop is behind an uncollected router).
    Asymmetry cannot be PROVEN from an unprovable trace -> INDETERMINATE, never a fabricated 'asymmetric'."""
    return {
        "routes": {
            "R1": [{"prefix": "10.1.1.0/24", "next_hop": "", "out_intf": "Vlan1", "source": "connected"},
                   {"prefix": "10.0.12.0/30", "next_hop": "", "out_intf": "Gi0/1", "source": "connected"},
                   {"prefix": "10.2.2.0/24", "next_hop": "10.0.12.2", "out_intf": "Gi0/1", "source": "static"}],
            "R2": [{"prefix": "10.0.12.0/30", "next_hop": "", "out_intf": "Gi0/1", "source": "connected"},
                   {"prefix": "10.2.2.0/24", "next_hop": "", "out_intf": "Vlan2", "source": "connected"},
                   # return route points at an uncollected next-hop -> reverse trail is a lower bound.
                   {"prefix": "10.1.1.0/24", "next_hop": "172.31.99.1", "out_intf": "Gi0/2", "source": "static"}],
        },
        "interfaces": {
            "R1": {"Gi0/1": {"svi_ip": "10.0.12.1/30"}},
            "R2": {"Gi0/1": {"svi_ip": "10.0.12.2/30"}},
        },
    }


def test_bidirectional_symmetric():
    r = fib.trace_bidirectional(_snap_symmetric(), "10.1.1.5", "10.2.2.9")
    assert r["forward"]["reached"] is True and r["reverse"]["reached"] is True
    assert r["symmetric"] is True
    assert r["rpf_verdict"] == "symmetric"
    assert r["asymmetry"] == []


def test_bidirectional_asymmetric_forward_reaches_reverse_drops():
    r = fib.trace_bidirectional(_snap_asymmetric(), "10.1.1.5", "10.2.2.9")
    assert r["forward"]["reached"] is True
    assert r["reverse"]["reached"] is False and r["reverse"]["computed"] is True   # a DEFINITIVE reverse drop
    assert r["symmetric"] is False
    assert r["rpf_verdict"] == "asymmetric"
    assert r["asymmetry"], "the divergence must be named"


def test_bidirectional_indeterminate_when_reverse_is_a_lower_bound():
    """Can't prove asymmetry from an unprovable trace: a lower-bound reverse -> INDETERMINATE, not 'asymmetric'."""
    r = fib.trace_bidirectional(_snap_indeterminate_reverse(), "10.1.1.5", "10.2.2.9")
    assert r["forward"]["reached"] is True
    assert r["reverse"]["computed"] is False                    # reverse trail lost to incomplete collection
    assert r["rpf_verdict"] == "INDETERMINATE"
    assert r["symmetric"] is False                              # not proven symmetric


def test_bidirectional_indeterminate_when_forward_is_a_lower_bound():
    """Symmetric in reverse role: an inconclusive FORWARD trace also abstains."""
    snap = _snap_indeterminate_reverse()
    # swap endpoints so the lower-bound direction is now the 'forward' call
    r = fib.trace_bidirectional(snap, "10.2.2.9", "10.1.1.5")
    assert r["rpf_verdict"] == "INDETERMINATE"


def test_bidirectional_total_on_bad_input():
    r = fib.trace_bidirectional(None, "1.1.1.1", "2.2.2.2")
    assert r["rpf_verdict"] == "INDETERMINATE"
    assert r["symmetric"] is False
    assert "forward" in r and "reverse" in r


def test_bidirectional_carries_mtu_dimension_on_each_direction():
    """Composition means each direction is a full trace -> both carry the MTU keys; a jumbo target can be passed
    through so an asymmetric-MTU underlay is visible per direction."""
    r = fib.trace_bidirectional(_snap_symmetric(), "10.1.1.5", "10.2.2.9")
    assert "mtu_verdict" in r["forward"] and "mtu_verdict" in r["reverse"]


# =============================================== OPTIONAL: ECMP multipath-consistency ===
def _ecmp_snap(mtu_a="9216", mtu_b="9216", acl_a_in="", acl_b_in=""):
    """R1 installs TWO equal-cost OSPF legs to 10.9.9.0/24 (via Gi0/1 -> R2 and Gi0/2 -> R3). The two egress
    interfaces' MTU / ACL are parameterized so a test can make the legs agree or diverge.

    BOTH next-hop routers are collected and BOTH deliver the dst — without them the legs' FORWARDING is
    unresolved and a 'consistent' verdict would be certifying a dimension it never checked (review #27:
    ecmp_consistency compared only egress MTU and ACL names, never whether each leg forwards at all)."""
    return {
        "routes": {
            "R1": [{"prefix": "10.0.1.0/24", "next_hop": "", "out_intf": "Vlan1", "source": "connected"},
                   {"prefix": "10.0.12.0/30", "next_hop": "", "out_intf": "Gi0/1", "source": "connected"},
                   {"prefix": "10.0.13.0/30", "next_hop": "", "out_intf": "Gi0/2", "source": "connected"},
                   {"prefix": "10.9.9.0/24", "next_hop": "10.0.12.2", "out_intf": "Gi0/1", "source": "ospf"},
                   {"prefix": "10.9.9.0/24", "next_hop": "10.0.13.3", "out_intf": "Gi0/2", "source": "ospf"}],
            "R2": [{"prefix": "10.0.12.0/30", "next_hop": "", "out_intf": "Gi0/1", "source": "connected"},
                   {"prefix": "10.9.9.0/24", "next_hop": "", "out_intf": "Vlan99", "source": "connected"}],
            "R3": [{"prefix": "10.0.13.0/30", "next_hop": "", "out_intf": "Gi0/1", "source": "connected"},
                   {"prefix": "10.9.9.0/24", "next_hop": "", "out_intf": "Vlan99", "source": "connected"}],
        },
        "interfaces": {
            "R1": {
                "Gi0/1": {"port": "Gi0/1", "mtu": mtu_a, "acl_in": acl_a_in,
                           "svi_ip": "10.0.12.1/30", "mtu_semantics": "effective_ipv4_mtu"},
                "Gi0/2": {"port": "Gi0/2", "mtu": mtu_b, "acl_in": acl_b_in,
                           "svi_ip": "10.0.13.1/30", "mtu_semantics": "effective_ipv4_mtu"},
            },
            "R2": {"Gi0/1": {"port": "Gi0/1", "svi_ip": "10.0.12.2/30"}},
            "R3": {"Gi0/1": {"port": "Gi0/1", "svi_ip": "10.0.13.3/30"}},
        },
    }


def test_ecmp_consistent_when_legs_agree():
    r = fib.ecmp_consistency(_ecmp_snap(mtu_a="9216", mtu_b="9216"), "10.0.1.5", "10.9.9.5")
    assert r["host"] == "R1" and r["leg_count"] == 2
    assert r["verdict"] == "consistent"
    assert r["mtu_divergence"] == [] and r["acl_divergence"] == []


def test_ecmp_inconsistent_on_mtu_divergence():
    r = fib.ecmp_consistency(_ecmp_snap(mtu_a="9216", mtu_b="1500"), "10.0.1.5", "10.9.9.5")
    assert r["verdict"] == "inconsistent"
    mtus = {d["mtu"] for d in r["mtu_divergence"]}
    assert mtus == {1500, 9216}
    # the divergence names each egress interface
    assert {d["out_intf"] for d in r["mtu_divergence"]} == {"Gi0/1", "Gi0/2"}


def test_ecmp_inconsistent_on_acl_divergence():
    r = fib.ecmp_consistency(_ecmp_snap(acl_a_in="BLOCK_GUEST", acl_b_in=""), "10.0.1.5", "10.9.9.5")
    assert r["verdict"] == "inconsistent"
    assert any(d["acl_in"] == "BLOCK_GUEST" for d in r["acl_divergence"])


def test_ecmp_not_applicable_for_single_path():
    """A single installed path is not ECMP -> the check does not apply (not a fabricated 'consistent' pass)."""
    single = {
        "routes": {"R1": [{"prefix": "10.0.1.0/24", "source": "connected"},
                          {"prefix": "10.9.9.0/24", "next_hop": "10.0.1.2", "out_intf": "Vlan1", "source": "static"}]},
        "interfaces": {"R1": {"Vlan1": {"port": "Vlan1", "mtu": "1500"}}},
    }
    r = fib.ecmp_consistency(single, "10.0.1.5", "10.9.9.5")
    assert r["verdict"] == "not_ecmp" and r["leg_count"] == 1


def test_ecmp_indeterminate_when_a_leg_interface_is_unobserved():
    """A leg whose egress interface was not collected can't be proven consistent -> INDETERMINATE, disclosing the
    blind leg. Never a fabricated 'consistent'."""
    snap = _ecmp_snap(mtu_a="9216", mtu_b="9216")
    del snap["interfaces"]["R1"]["Gi0/2"]                 # one leg's interface not collected
    r = fib.ecmp_consistency(snap, "10.0.1.5", "10.9.9.5")
    assert r["verdict"] == "INDETERMINATE"
    assert any(leg["out_intf"] == "Gi0/2" for leg in r["unobserved_legs"])


def test_ecmp_indeterminate_when_a_leg_mtu_is_uncollected():
    """Adversarial-review #3/#10: the interface RECORD exists (so it is NOT a whole-leg blind spot) but its MTU
    field was never collected. The MTU dimension must NOT read 'consistent' by omission — a blank MTU is its own
    blind spot that forces INDETERMINATE, disclosed in mtu_unobserved_legs. This exercises the ('','') vs
    (None,None) distinction the pre-fix gate missed (an existing record with no ACL returns ('',''), so the old
    `mtu is None and ai is None and ao is None` guard never fired and the leg silently read consistent)."""
    snap = _ecmp_snap(mtu_a="9216", mtu_b="9216")
    snap["interfaces"]["R1"]["Gi0/2"].pop("mtu", None)   # record kept, MTU field absent (not the whole leg)
    r = fib.ecmp_consistency(snap, "10.0.1.5", "10.9.9.5")
    assert r["verdict"] == "INDETERMINATE"                # NOT 'consistent'
    assert any(leg["out_intf"] == "Gi0/2" for leg in r["mtu_unobserved_legs"])
    assert r["unobserved_legs"] == []                     # the leg's interface WAS collected — only its MTU is blind


def test_ecmp_total_on_bad_input():
    r = fib.ecmp_consistency(None, "1.1.1.1", "2.2.2.2")
    assert r["verdict"] == "INDETERMINATE" and r["leg_count"] == 0


# --- review #27: the forwarding dimension (a leg that agrees on MTU/ACL and still blackholes) ---------

def test_ecmp_inconsistent_when_one_leg_definitively_blackholes():
    """The legs are IDENTICAL on egress MTU and ACL — and one of them discards the flow (R3 summarises
    10.9.9.0/24 to Null0). Comparing only MTU/ACL names read that as 'consistent' while ~50% of the flows
    that hash onto Gi0/2 were dropped. The proven forwarding divergence must NAME the leg."""
    snap = _ecmp_snap()
    snap["routes"]["R3"] = [{"prefix": "10.0.13.0/30", "next_hop": "", "out_intf": "Gi0/1", "source": "connected"},
                            {"prefix": "10.9.9.0/24", "next_hop": "", "out_intf": "Null0", "source": "static"}]
    r = fib.ecmp_consistency(snap, "10.0.1.5", "10.9.9.5")
    assert r["mtu_divergence"] == [] and r["acl_divergence"] == []      # the two old dimensions see nothing
    assert r["verdict"] == "inconsistent"
    assert [d["out_intf"] for d in r["forwarding_divergence"]] == ["Gi0/2"]
    assert r["forwarding_divergence"][0]["leg_status"] == "computed:unreachable"


def test_ecmp_indeterminate_when_a_leg_forwarding_is_unresolved():
    """A leg whose next-hop router was never collected proves nothing about that leg — it must not read
    'consistent' by omission (the same absence-is-not-health rule the MTU/interface blind spots follow)."""
    snap = _ecmp_snap()
    del snap["routes"]["R3"]                                  # Gi0/2's next hop is now behind nobody collected
    r = fib.ecmp_consistency(snap, "10.0.1.5", "10.9.9.5")
    assert r["verdict"] == "INDETERMINATE"
    assert [d["out_intf"] for d in r["forwarding_unresolved_legs"]] == ["Gi0/2"]
    assert r["forwarding_divergence"] == []                   # unresolved is NOT a proven drop
