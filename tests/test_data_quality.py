"""PHASE 2.4: 'missing data != healthy' (audit C3).

A switch whose collection is incomplete must not score a misleading high band -
compute_data_quality measures completeness and compute_health_scores overrides
the band to 'Insufficient Data' below the (configurable) threshold.
"""
import os

import synthetic_fixtures as fx
from cisco_toolkit import analyze   # ScoringConfig lives here since PHASE 2.7 step 15


def test_data_quality_full_vs_partial(cp, tmp_path):
    root = fx.write_collection(str(tmp_path / "c"))
    cmds = list(dict.fromkeys(cp.COMMANDS_NXOS + cp.COMMANDS_IOS))
    full = {c: os.path.join(root, "core1", fx.cmd_filename(c))
            for c in cmds if os.path.isfile(os.path.join(root, "core1", fx.cmd_filename(c)))}
    assert cp.compute_data_quality({"core1": full})["core1"] == 1.0     # all 4 essentials present

    # a switch with only 'show version' collected -> 1 of 4 essentials
    pdir = tmp_path / "partial" / "sw"
    pdir.mkdir(parents=True)
    vfile = pdir / fx.cmd_filename("show version")
    vfile.write_text("Cisco IOS Software, Version 15.2(7)E3\n", encoding="utf-8")
    partial = {"show version": str(vfile)}
    assert cp.compute_data_quality({"sw": partial})["sw"] == 0.25


def test_insufficient_data_overrides_band(cp):
    # score would be a perfect 100, but the collection gap must show as Insufficient Data
    recs = cp.compute_health_scores({"sw": {}}, [], [], [], [], data_quality={"sw": 0.25})
    assert recs[0]["score"] == 100
    assert recs[0]["band"] == "Insufficient Data"
    assert recs[0]["data_quality"] == 0.25


def test_sufficient_data_keeps_normal_band(cp):
    from cisco_toolkit.model import InterfaceData
    # sufficient data AND a non-empty interface parse -> a normal band, not overridden
    recs = cp.compute_health_scores({"sw": {"Gi1/0/1": InterfaceData(port="Gi1/0/1")}}, [], [], [], [],
                                    data_quality={"sw": 1.0})
    assert recs[0]["band"] == "Excellent"
    assert recs[0]["data_quality"] == 1.0


def test_collected_but_unparsed_device_is_insufficient_data(cp):
    """ANALY-01 (false-health): a device whose essentials WERE collected (dq high) but whose interface parse
    yielded ZERO interfaces is a parse/format failure (a NOS/format the parser can't read, or a truncated
    capture), NOT a flawless device. data_quality measures raw FILE presence, not parse YIELD, so the empty
    parse otherwise scored a perfect 100 'Excellent' and ranked the unreadable box the single healthiest asset,
    excluding it from every finding. It must band 'Insufficient Data'."""
    recs = cp.compute_health_scores({"sw": {}}, [], [], [], [], data_quality={"sw": 1.0})
    assert recs[0]["band"] == "Insufficient Data", recs[0]
    assert recs[0]["data_quality"] == 1.0


def test_no_data_quality_arg_is_byte_identical(cp):
    # default (None) -> no data_quality key and no override (back-compat / golden-safe)
    recs = cp.compute_health_scores({"sw": {}}, [], [], [], [])
    assert "data_quality" not in recs[0]
    assert recs[0]["band"] == "Excellent"


def test_threshold_is_configurable(cp):
    from cisco_toolkit.model import InterfaceData
    cfg = analyze.ScoringConfig(data_quality_threshold=0.2)   # 0.25 now clears the bar
    recs = cp.compute_health_scores({"sw": {"Gi1/0/1": InterfaceData(port="Gi1/0/1")}}, [], [], [], [],
                                    config=cfg, data_quality={"sw": 0.25})
    assert recs[0]["band"] == "Excellent"


def test_loader_registers_ers_and_classic_ios_ospfv3(cp):
    """Collect/--no-collect command coverage: a builder fallback variant is DEAD unless the command is also in
    the COMMANDS_* lists the collector writes and the --no-collect loader scans. (1) the ISE ERS fallback export
    'ers/config/node' (build_ise's second channel) -- without it a collected ERS-only ISE cluster re-analyzes as
    'not-observed'. (2) the classic-IOS OSPFv3 form 'show ipv6 ospf neighbor' (build_ipv6_routing's fallback) --
    without it OSPFv3 adjacency is blind on a classic-IOS router that rejects 'show ospfv3 neighbor'."""
    assert "ers/config/node" in cp.COMMANDS_NXOS
    assert "show ipv6 ospf neighbor" in cp.COMMANDS_IOS
