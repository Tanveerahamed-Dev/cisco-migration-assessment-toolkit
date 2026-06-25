"""Regression tests for the round-2 multi-agent code-review LOW/MEDIUM findings (engine side).

Each test names its finding id and pins the corrected behaviour so the bug class cannot silently
re-emerge. Webapp-side findings live under webapp/tests/.
"""
import logging

import pytest

from cisco_toolkit import analyze, portdb, ouidb
import cisco_toolkit.design_advisor as da


# ---------------------------------------------------------------- ANALY-04 ---
def test_blank_hostname_not_scored_so_reconcile_agrees():
    """ANALY-04: a blank/whitespace hostname (a malformed devices.json row that nonetheless collected) was
    scored by compute_health_scores but SKIPPED by compute_collection_completeness, so len(health_scores)
    exceeded the inventory count and ssot.reconcile false-fired an integrity DRIFT alarm. Both surfaces must
    now agree."""
    hs = analyze.compute_health_scores({"SW-A": {}, "SW-B": {}, "": {}}, [], [], [], [])
    assert sorted(r["switch"] for r in hs) == ["SW-A", "SW-B"]            # blank dropped, not scored
    cc = analyze.compute_collection_completeness(
        ["SW-A", "SW-B", ""],
        {"SW-A": {"show version": "x"}, "SW-B": {"show version": "x"}, "": {"show version": "x"}})
    assert len(hs) == cc["summary"]["inventory"]                          # surfaces agree -> no reconcile drift


# ---------------------------------------------------------------- ANALY-05 ---
def test_golden_drift_dossier_reads_na_when_no_baseline_derived():
    """ANALY-05: in majority mode with <3 comparable configs, compute_golden_drift derives NO baseline
    (summary.n_baseline == 0) yet still emits per_device rows with n_missing 0 / compliance 100. The dossier
    Golden-drift axis read those as 'ok / matches the config baseline' -- asserting conformance to a baseline
    that never existed (false-health). It must read 'na'."""
    gd = analyze.compute_golden_drift({"A": "hostname A\nip routing", "B": "hostname B"})
    assert gd["summary"]["n_baseline"] == 0
    dos = analyze.compute_device_dossiers(health_scores=[{"switch": "A"}, {"switch": "B"}], golden_drift=gd)
    states = [(e["state"], e["label"]) for pd in dos["per_device"]
              for e in pd["exposures"] if e["axis"] == "Golden drift"]
    assert states and all(s == "na" for s, _ in states), states
    assert all("no config baseline" in lbl for _, lbl in states)


# ---------------------------------------------------------------- LIFEC-04 ---
def test_near_ldos_band_compares_unrounded_delta():
    """LIFEC-04 (rounding half -- the other half, making the LDoS day itself 'Past', was REFUTED: LDoS = Last
    Day of Support, so support still exists ON that date; test_lifecycle_boundary_drift_guard locks the strict
    `>`). years_to_ldos was ROUNDED before the <= 1.0 band test, so a device genuinely ~1.05 yr from LDoS
    rounded to 1.0 and fell into Near-LDoS (the band ~18 days too wide). The band must use the UNROUNDED
    delta. (Catalyst 3850 LDoS = 2026-10-31.)"""
    band = lambda asof: analyze.compute_lifecycle_risk(
        {"sw1": {"model": "WS-C3850-48P"}}, asof=asof)["per_device"][0]["band"]
    assert band("2025-10-13") != "Near-LDoS"     # ~1.05 yr out: was Near via rounding (1.0), now Past-EoS
    assert band("2026-06-01") == "Near-LDoS"      # genuinely within 1 yr still Near
    assert band("2026-10-31") == "Near-LDoS"      # LDoS day: last supported day -> Near, not yet Past (strict >)


# ---------------------------------------------------------------- LIFEC-03 ---
def test_offline_registries_warn_on_load_failure_then_degrade(caplog):
    """LIFEC-03: portdb/ouidb._registry() swallowed ANY load error with a bare `except Exception: pass` and,
    being lru_cached, memoised the empty result for the whole process with NO signal -- a missing/corrupt
    shipped pack silently disabled the entire L4-service/multicast and MAC->vendor axes. A load failure must
    now emit a WARNING (and still degrade tolerantly to empty, never crash)."""
    assert portdb.service_for_port(179, "tcp") is not None                # sanity: the real pack loads
    p_orig, o_orig = portdb._DATA, ouidb._DATA
    try:
        portdb._DATA = "/nonexistent.gz"; portdb._registry.cache_clear()
        ouidb._DATA = "/nonexistent.gz"; ouidb._registry.cache_clear()
        with caplog.at_level(logging.WARNING):
            ports, mcast = portdb._registry()
            tables = ouidb._registry()
        assert ports == {} and mcast == []                               # tolerant degrade, no crash
        assert all(v == {} for v in tables.values())
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "portdb: could not load" in msgs                          # surfaced, not silent
        assert "ouidb: could not load" in msgs
    finally:                                                              # MUST restore or poison the suite
        portdb._DATA = p_orig; portdb._registry.cache_clear()
        ouidb._DATA = o_orig; ouidb._registry.cache_clear(); ouidb.vendor_for_mac.cache_clear()
    assert portdb.service_for_port(179, "tcp") is not None                # restored cleanly


# ---------------------------------------------------------------- DETEC-03 ---
def test_fhrp_no_preempt_fires_only_on_raised_priority_not_default():
    """DETEC-03: the signal flagged ANY active gateway with preempt off. But HSRP/VRRP/GLBP preemption is OFF
    BY DEFAULT (and parse_hsrp_detail defaults preempt=False), so every textbook default active group cried
    wolf. Only a gateway whose operator RAISED its configured priority above 100 deliberately wants to be
    primary -- without preempt that intended primary won't reclaim after a failover. A default-priority (100)
    active gateway with no preempt must stay silent."""
    default = {"fhrp_detail": {"d1": [{"ifname": "Vlan10", "group": "10", "state": "Active",
                                       "preempt": False, "priority": 100, "cfg_priority": 100,
                                       "track": [{"obj": "1", "decrement": 10}]}]}}
    raised = {"fhrp_detail": {"d2": [{"ifname": "Vlan20", "group": "20", "state": "Active",
                                      "preempt": False, "priority": 110, "cfg_priority": 110,
                                      "track": [{"obj": "1", "decrement": 10}]}]}}
    assert da._signals(default)["fhrp_no_preempt"] == []                  # benign default: silent
    assert da._signals(raised)["fhrp_no_preempt"] == ["d2 Vlan20 grp 20"]  # raised + no preempt: fires
    assert da._d_fhrp_resilience(default, da._signals(default)) is None    # no other arm fires either


# ---------------------------------------------------------------- DETEC-04 ---
def test_sdwan_control_shortfall_counted_once_per_device():
    """DETEC-04: vManage repeats the DEVICE-level expected/actual control-connection count on every per-peer
    row, so a single device short by one made every remaining UP row also satisfy actual<expected -- counting
    the same shortfall N times. It must be counted ONCE per device; a genuinely-down peer is still per-row."""
    rows = [{"system_ip": "10.0.0.13", "host_name": "BR13", "peer_type": "vsmart", "state": "up",
             "expected": 4, "actual": 3} for _ in range(3)]
    rows.append({"system_ip": "10.0.0.13", "host_name": "BR13", "peer_type": "vbond", "state": "down",
                 "expected": 4, "actual": 3})
    cc = da._signals({"sdwan": {"mgr1": {"control_connections": rows}}})["sdwan_control_down"]
    assert len(cc) == 2, cc                                               # was 4 (one per row); now 1 short + 1 down
    assert sum("control connections 3/4" in x for x in cc) == 1          # the shortfall: exactly once
    assert sum("(down)" in x for x in cc) == 1                            # the down peer: still surfaced
