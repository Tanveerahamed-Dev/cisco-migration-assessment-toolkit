"""Tests for the Python-canonical unified CAUSAL FLOW model (cisco_toolkit.causal.compute_causal_flows).

This is the source the AssessHub webapp reads (GET /causal_flows) so the dashboard never re-derives causal
intent — it mirrors the blast_radius_explorer.html causalFlows() JS. These lock the contract: every finding
family normalised to one trigger->mechanism->impact->mitigation story, cross-layer counted ONCE (no double
-count with the punch-list), blast magnitude carried with the unit actually matched (coverage-honest), and
cross-layer compounds promoted to a bowtie shape.
"""
import json
import os

import pytest

from cisco_toolkit.causal import compute_causal_flows


# ---- a small synthetic snapshot with KNOWN family counts (deterministic, self-contained) ----
SNAP = {
    "devices": {"sw1": {}, "sw2": {}, "sw3": {}},
    "causality": [
        {"severity": "High", "trigger": "Gateway sw1:Vlan10 goes down",
         "mechanism": "only in-scan L3 gateway, no FHRP peer",
         "impact": "Every VLAN 10 host loses its gateway (5 endpoint(s); 2 other switch(es) affected)",
         "mitigation": "Add an FHRP peer", "hosts": ["sw1"]},
        {"severity": "Critical", "trigger": "Transit switch sw2 is removed / migrated",
         "mechanism": "sole forwarding path", "impact": "40 endpoint(s) lose reachability",
         "mitigation": "Add a redundant uplink", "hosts": ["sw2"]},
    ],
    "cross_layer": [
        {"id": "CL-01", "severity": "Critical", "layers": "L1+L3",
         "title": "VLAN 30: single-fiber uplink to a sole gateway",
         "detail": "VLAN 30's only L3 gateway is sw1 (no FHRP); sw3 reaches the fabric over a single fiber",
         "recommendation": "add a redundant uplink AND an FHRP peer", "hosts": ["sw1", "sw3"]},
        {"id": "CL-02", "severity": "High", "layers": "L2",
         "title": "native VLAN on a trunk", "detail": "trunk carries native VLAN 1",
         "recommendation": "prune the native VLAN", "hosts": ["sw2"]},
    ],
    "design_blueprint": {"decisions": [
        {"id": "d1", "title": "Enforce secure management", "priority": "Critical", "status": "recommended",
         "confidence": "Observed", "driver": "Management-plane integrity",
         "evidence": {"summary": "3 device(s) fail management-plane hardening", "count": 3,
                      "devices": ["sw1", "sw2", "sw3"], "fields": ["security[host].findings[].status"]},
         "principle": {"citation": "CCDE Session 19"}, "recommended_action": "Standardize SNMPv3 + SSH",
         "alternatives": "local-only AAA", "tradeoffs": "operational lift", "axes": ["security"]},
        # needs-requirement -> MUST be excluded (only `recommended` decisions become flows)
        {"id": "d2", "title": "Introduce FHRP", "priority": "High", "status": "needs-requirement",
         "driver": "x", "evidence": {}, "principle": {}},
    ]},
    "punchlist": [
        # category Cross-layer -> MUST be excluded (already covered by the cross_layer array; no double-count)
        {"severity": "Critical", "category": "Cross-layer", "title": "dup of CL-01",
         "detail": "...", "devices": ["sw1"]},
        {"severity": "High", "category": "FHRP", "title": "No FHRP on VLAN 10",
         "detail": "gateway has no standby", "remediation": "add HSRP", "devices": ["sw1"], "wave": "Wave 1"},
        {"severity": "Medium", "category": "Health", "title": "High CPU on sw3",
         "detail": "sw3 CPU 85%", "remediation": "investigate", "devices": ["sw3"]},
    ],
}


@pytest.fixture(scope="module")
def result():
    return compute_causal_flows(SNAP)


def _by_key(flows, key):
    return next(f for f in flows if f["key"] == key)


def test_total_and_family_counts(result):
    # 2 struct + 2 xlayer + 1 design(recommended) + 2 punchlist(non-crosslayer) = 7
    assert result["summary"]["n_flows"] == 7
    fam = {f["key"]: f["n"] for f in result["families"]}
    assert set(fam) == {"struct", "xlayer", "design", "FHRP", "Health"}
    assert result["summary"]["n_families"] == 5
    assert fam["struct"] == 2 and fam["xlayer"] == 2 and fam["design"] == 1


def test_cross_layer_counted_once_no_double_count(result):
    # cross-layer flows come ONLY from the cross_layer array; the punch-list 'Cross-layer' row is dropped
    xlayer = [f for f in result["flows"] if f["family"] == "xlayer"]
    assert len(xlayer) == 2
    assert all(f["key"].startswith("cl-") for f in xlayer)
    # no punch-list flow leaked in under the Cross-layer category
    assert not any(f["family"] == "Cross-layer" for f in result["flows"])
    assert not any(f["key"] == "pl-0" for f in result["flows"])  # the excluded Cross-layer punch row


def test_design_only_recommended(result):
    design = [f for f in result["flows"] if f["family"] == "design"]
    assert len(design) == 1
    d = design[0]
    assert d["confidence"] == "Observed"
    assert d["evidence"]["citation"] == "CCDE Session 19"
    assert d["alternatives"] == "local-only AAA"
    assert d["blast"] == 3 and d["blast_unit"] == "devices"


def test_blast_unit_is_coverage_honest(result):
    # struct-0 impact names "5 endpoint(s)" AND "2 switch(es)" — endpoints win, and the UNIT is endpoints
    s0 = _by_key(result["flows"], "struct-0")
    assert s0["blast"] == 5 and s0["blast_unit"] == "endpoints"
    # the FHRP punch row has no count in its detail -> falls back to the device count, labelled "device"
    # (singular, because the count is exactly 1 — "1 device", not "1 devices")
    fhrp = next(f for f in result["flows"] if f["family"] == "FHRP")
    assert fhrp["blast"] == 1 and fhrp["blast_unit"] == "device"


def test_cross_layer_promotes_to_bowtie(result):
    # look up by title, not key: cross-layer keys are index-based (CL-xx ids repeat in real snapshots)
    xlayer = [f for f in result["flows"] if f["family"] == "xlayer"]
    cl01 = next(f for f in xlayer if "single-fiber" in f["title"])   # two detail clauses -> bowtie
    assert cl01["shape"] == "bowtie"
    assert len(cl01["threats"]) >= 2
    cl02 = next(f for f in xlayer if "native VLAN" in f["title"])    # single clause -> linear
    assert cl02["shape"] == "linear"


def test_flow_keys_are_unique(result):
    keys = [f["key"] for f in result["flows"]]
    assert len(keys) == len(set(keys)), "every flow key must be unique (React reconciliation depends on it)"


def test_flow_keys_unique_despite_repeated_cross_layer_ids():
    """Cross-layer CL-xx ids REPEAT — a real [HISTORY-REDACTED] snapshot has 303 findings all id='CL-02'. The flow key must
    therefore be index-based, not id-based, or React/the UI sees duplicate keys. Locks that regression."""
    snap = {"devices": {"a": {}, "b": {}, "c": {}},
            "cross_layer": [{"id": "CL-02", "severity": "High", "title": f"box{c}: only L2 transit",
                             "detail": f"Removing box{c} partitions endpoints in 5 VLAN(s).", "hosts": [c]}
                            for c in ("a", "b", "c")]}
    keys = [f["key"] for f in compute_causal_flows(snap)["flows"]]
    assert len(keys) == len(set(keys)) == 3, f"keys must be unique despite the repeated CL-02 id: {keys}"


def test_severity_normalised_and_sorted(result):
    valid = {"Critical", "High", "Medium", "Low", "Info"}
    assert all(f["severity"] in valid for f in result["flows"])
    # 3 criticals: struct-1, cl-CL-01, design-d1
    assert result["summary"]["n_critical"] == 3
    # severity-ranked: the first flow is Critical, the last is the Medium Health row
    assert result["flows"][0]["severity"] == "Critical"
    assert result["flows"][-1]["severity"] == "Medium"
    # within Critical, blast-desc: struct-1 (40) precedes design-d1 (3) precedes cl-CL-01 (2 hosts)
    crit_keys = [f["key"] for f in result["flows"] if f["severity"] == "Critical"]
    assert crit_keys[0] == "struct-1"


def test_every_flow_has_the_four_stages(result):
    for f in result["flows"]:
        for stage in ("trigger", "mechanism", "impact", "mitigation"):
            assert stage in f
        assert f["family_label"] and f["icon"] and f["severity"]


def test_empty_snapshot_is_safe():
    r = compute_causal_flows({})
    assert r["flows"] == [] and r["families"] == [] and r["summary"]["n_flows"] == 0
    r2 = compute_causal_flows(None)
    assert r2["summary"]["n_flows"] == 0


def test_smoke_on_real_sample_snapshot():
    """The webapp's bundled sample fleet: cross-layer counted once, families present, shape sane."""
    path = os.path.join(os.path.dirname(__file__), "..", "webapp", "sample_data", "sample_fleet.snapshot.json")
    if not os.path.isfile(path):
        pytest.skip("sample snapshot not present")
    snap = json.load(open(path, encoding="utf-8"))
    r = compute_causal_flows(snap)
    assert r["summary"]["n_flows"] > 0
    fams = {f["key"] for f in r["families"]}
    assert "struct" in fams and "xlayer" in fams
    # cross-layer flows == len(cross_layer); punch-list Cross-layer rows excluded (no double-count)
    n_xlayer = sum(1 for f in r["flows"] if f["family"] == "xlayer")
    assert n_xlayer == len(snap.get("cross_layer") or [])
    n_pl = sum(1 for f in r["flows"] if f["key"].startswith("pl-"))
    assert n_pl == sum(1 for p in (snap.get("punchlist") or []) if (p.get("category") or "") != "Cross-layer")


# ---- robustness: a malformed-but-truthy snapshot must NEVER raise (it would 500 the webapp endpoint) ----
# Mirrors the explorer JS, which is Array.isArray-defensive. A `snap.get(K) or []` idiom does NOT guard a
# truthy non-list (e.g. "notalist"), so without type guards the loop iterates characters and calls str.get().
@pytest.mark.parametrize("snap", [
    {"causality": "notalist"},                                          # truthy non-list container
    {"cross_layer": "x"},
    {"punchlist": "x"},
    {"design_blueprint": "x"},                                          # str.get('decisions')
    {"design_blueprint": {"decisions": "x"}},
    {"devices": "x"},                                                   # str().keys()
    {"causality": {"a": 1}},                                            # dict where a list is expected
    {"causality": [1, 2, 3]},                                           # list of non-dict elements
    {"cross_layer": [None, "x", 5]},
    {"design_blueprint": {"decisions": [None, "x", {"status": "recommended", "evidence": None, "principle": None}]}},
    {"punchlist": [{"category": "X", "devices": "notalist", "detail": 12345}]},
    {"causality": [{"severity": {"level": "high"}, "hosts": ["a"]}]},   # UNhashable severity -> _sev must not crash
    {"causality": [{"severity": ["Critical"], "hosts": ["a"]}]},        # list severity -> must normalise, not KeyError
])
def test_never_raises_on_malformed_snapshot(snap):
    r = compute_causal_flows(snap)
    assert r["summary"]["n_flows"] >= 0
    assert isinstance(r["flows"], list) and isinstance(r["families"], list)
    # every emitted flow still carries a valid, hashable severity (so downstream _SEV lookups are total)
    for f in r["flows"]:
        assert f["severity"] in {"Critical", "High", "Medium", "Low", "Info"}


def test_xlayer_blast_surfaces_vlan_count_when_no_endpoint_count():
    """A CL-02-style transit-partition finding carries a VLAN count but no endpoint COUNT in its prose, so the
    blast magnitude should surface "51 VLANs" — matching the finding's OWN title ("…for 51 VLAN(s)") — rather
    than the lone host removed. VLAN is scanned ONLY for the cross-layer family."""
    snap = {"devices": {"sw9": {}}, "cross_layer": [{
        "id": "CL-X", "severity": "High", "layers": "L2+L3",
        "title": "sw9: only L2 transit to the gateway for 51 VLAN(s)",
        "detail": "Removing sw9 partitions endpoints in 51 VLAN(s) (3, 8, 9) from their L3 gateway.",
        "recommendation": "Add a redundant path", "hosts": ["sw9"]}]}
    cl = next(f for f in compute_causal_flows(snap)["flows"] if f["family"] == "xlayer")
    assert cl["blast"] == 51 and cl["blast_unit"] == "VLANs"
    # singular agreement when the count is exactly 1
    snap["cross_layer"][0]["detail"] = "Removing sw9 partitions endpoints in 1 VLAN(s) (3) from their gateway."
    cl1 = next(f for f in compute_causal_flows(snap)["flows"] if f["family"] == "xlayer")
    assert cl1["blast"] == 1 and cl1["blast_unit"] == "VLAN"
    # an endpoint COUNT, when present, still wins over the VLAN count (endpoints are the truer blast)
    snap["cross_layer"][0]["detail"] = "Removing sw9 partitions 286 endpoint(s) across 51 VLAN(s)."
    clE = next(f for f in compute_causal_flows(snap)["flows"] if f["family"] == "xlayer")
    assert clE["blast"] == 286 and clE["blast_unit"] == "endpoints"


def test_non_xlayer_families_do_not_scan_vlan():
    """VLAN is an xlayer-only magnitude: a punch-list finding mentioning "3 VLAN(s)" but no endpoint/device
    count must fall back to the device count, NOT show "3 VLANs" (the global _blast stays unchanged)."""
    snap = {"devices": {"sw1": {}}, "punchlist": [{
        "severity": "High", "category": "STP", "title": "STP topology change",
        "detail": "impacts 3 VLAN(s)", "devices": ["sw1"]}]}
    pl = next(f for f in compute_causal_flows(snap)["flows"] if f["family"] == "STP")
    assert pl["blast"] == 1 and pl["blast_unit"] == "device"   # 1 device, never "3 VLANs"


def test_design_flow_does_not_mislabel_metric_as_devices():
    """LIVE mislabel fix: a design decision's evidence.count is the decision's METRIC (ports / VLANs /
    member-legs / ... per its title), NOT a device count. The blast badge must show the affected-DEVICE count
    (labelled 'devices'), the metric stays in the title (and evidence.count for the chip), and a fleet-level
    decision with no device list falls back to the unit-neutral 'affected' -- never a false 'device(s)'."""
    snap = {"design_blueprint": {"decisions": [
        {"id": "ports", "title": "1339 port(s) show physical-layer faults", "priority": "High",
         "status": "recommended", "evidence": {"count": 1339, "devices": ["sw1", "sw2"]}},
        {"id": "vlans", "title": "202 VLANs span the fabric", "priority": "Medium",
         "status": "recommended", "evidence": {"count": 202, "devices": []}},
    ]}}
    flows = {f["key"]: f for f in compute_causal_flows(snap)["flows"]}
    ports = flows["design-ports"]
    assert ports["blast"] == 2 and ports["blast_unit"] == "devices"      # the DEVICE count, not the 1339 ports
    assert ports["impact"] == "2 device(s) carry this gap"
    assert ports["evidence"]["count"] == 1339                            # metric preserved (title + chip)
    vlans = flows["design-vlans"]
    assert vlans["blast"] == 202 and vlans["blast_unit"] == "affected"   # no device list -> neutral, NOT 'devices'
    assert vlans["impact"] == "202 affected by this gap"
