"""[audit-6 leaf-coercion crash batch] A malformed NUMERIC leaf in an externally-supplied snapshot (a webapp
upload, a `--compare` / `--trend` file) -- a non-numeric string, a dict/list, or the bare JSON Infinity/NaN
that `json.loads` accepts by default -- must DEGRADE the one field (coverage-honest) and never crash the whole
deliverable / endpoint / workbook. The engine's #1 doctrine is fail-soft; each of these was a real MEDIUM
violation. Every test feeds the malformed leaf to the REAL function/generator and asserts it produces output
instead of raising.

Non-vacuousness (revert -> crash) is proven per site in the PR description. NOTE the trigger types differ:
a raw int()/round() with NO guard crashes on ANY bad type, but the finding-#2 sites already caught
(TypeError, ValueError) and bypassed ONLY on `float('inf')` -- `int(float('inf'))` raises OverflowError --
so those fixtures MUST plant inf to stay non-vacuous. (Unique basename: pytest derives the module name from
the filename, which must not collide with any other test module.)"""

import pytest

from cisco_toolkit.textutils import _as_num, xml_safe

INF = float("inf")
NAN = float("nan")


# --- the shared root-cause helper --------------------------------------------------------------------------
def test_as_num_rejects_every_trap_input():
    """Non-numeric str / dict / list / None + the JSON Infinity / -Infinity / NaN all degrade to the default.
    inf is the insidious one: int(float('inf')) raises OverflowError, which the usual (TypeError, ValueError)
    guards MISS -- and json.loads accepts a bare `Infinity`, so it survives the upload round-trip."""
    for bad in ("many", {"a": 1}, ["x"], None, INF, -INF, NAN, complex(1, 2)):
        assert _as_num(bad) == 0
        assert _as_num(bad, default=-1) == -1


def test_as_num_preserves_finite_numbers_and_intness():
    """The happy path is a clean drop-in for the int() calls it replaces: integer-valued inputs come back as
    ints (so counts render "5", not "5.0"); a genuinely fractional value is preserved rather than truncated."""
    assert _as_num(5) == 5 and isinstance(_as_num(5), int)
    assert _as_num(5.0) == 5 and isinstance(_as_num(5.0), int)
    assert _as_num("7") == 7 and isinstance(_as_num("7"), int)
    assert _as_num(3.7) == 3.7
    assert _as_num(0) == 0 and _as_num("0") == 0


# --- the latent xml_safe container gap ---------------------------------------------------------------------
def test_xml_safe_coerces_containers_but_passes_scalars_through():
    """A dict/list reaching a directly-rendered openpyxl cell raises ValueError, which excel._run_phase catches
    PER SHEET -> every later row silently dropped (a coverage-honesty false all-clear). xml_safe now discloses
    the container as a typed placeholder. Scalars (int / None / float / bool) still pass through so numeric
    cells keep their native type (openpyxl renders them)."""
    assert xml_safe({"a": 1}) == "[unrenderable dict]"
    assert xml_safe([1, 2]) == "[unrenderable list]"
    assert xml_safe((1,)) == "[unrenderable tuple]"
    assert xml_safe({1, 2}) == "[unrenderable set]"
    assert xml_safe(5) == 5 and xml_safe(None) is None and xml_safe(3.5) == 3.5 and xml_safe(True) is True
    assert xml_safe("keep\ttab") == "keep\ttab"          # legal XML whitespace still preserved


# --- finding #1 + #2: the deliverable generators -----------------------------------------------------------
def _hostile_numeric_snapshot():
    """A thin-but-otherwise-valid snapshot whose numeric leaves are malformed in a MIX of trigger types, so
    every consumer's old coercion chokes on at least one planted value:
      * inf   -> the int() / round() / _as_int (OverflowError) sites (deck/design/mop/ops/crd/engagement/archreview);
      * a str -> the unary-minus-WITHOUT-int() site (runbook `-(x or 0)`) + the subtraction site (deck n_devices);
      * a dict-> a third truthy shape for the sort keys.
    Otherwise minimal so the ONLY failure surface is the numeric coercions under test."""
    return {
        "devices": {"SW1": {"hostname": "SW1", "num_power_supplies": INF, "ps_status": "fail"},
                    "SW2": {"hostname": "SW2"}, "SW3": {"hostname": "SW3"}},
        # an inf health score exercises the ssot front-matter round(mean(scores)) (every .docx renders it).
        "health_scores": [{"switch": "SW1", "band": "Healthy", "role": "core", "score": INF},
                          {"switch": "SW2", "band": "Critical", "role": "access", "score": "many"}],
        "failure_impact": [
            {"host": "SW1", "stranded": INF, "off_scan_gw_vlans": INF, "vlans_impacted": NAN,
             "hard": 0, "severity": "High", "detail": "a"},
            {"host": "SW2", "stranded": "many", "off_scan_gw_vlans": "x", "vlans_impacted": "y",
             "hard": 0, "severity": "Medium", "detail": "b"},
            {"host": "SW3", "stranded": {"n": 1}, "severity": "Low", "detail": "c"},
        ],
        "lifecycle_risk": {
            "summary": {"n_devices": INF, "n_unknown": INF, "n_past_ldos": INF, "n_near": NAN,
                        "n_past_eos": "lots", "by_band": {}, "n_baseline": 3},
            "per_device": [{"host": "SW1", "band": "Past-LDoS", "model": "C9300"}],
        },
        "service_map": {"multicast": {"active_interfaces": INF, "active_switch_count": "many",
                                      "classified_groups": [], "igmp_queriers": [], "ptp": {}}},
        "golden_drift": {"summary": {"n_baseline": 3},
                         "per_device": [{"host": "SW1", "n_missing": "many", "compliance_pct": "high"}]},
        "collection_completeness": {"summary": {"partial": INF, "not_collected": "x"}},
        # exercises ops _fail_of (security.summary.fail) + the syslog-detection count aggregation (ops.py).
        "security": {"SW1": {"summary": {"fail": INF, "pass": "x"}}},
        "syslog_intelligence": {"detections": [{"label": "L", "count": INF, "severity": "High"}], "per_device": []},
        # a bridge with a malformed pairs_cut exercises the runbook chokepoint-table `-<pairs_cut>` sort key;
        # the subnet_intelligence row exercises runbook's `-(destination_count + reachable_count)` sort key.
        "link_centrality": [{"a_host": "SW1", "b_host": "SW2", "is_bridge": True, "pairs_cut": "many"}],
        "subnet_intelligence": {"per_device": [{"host": "SW1", "is_l3": True,
                                                "destination_count": "many", "reachable_count": INF}]},
    }


def test_docx_pptx_deliverables_tolerate_malformed_numeric_leaves(tmp_path):
    """[#1/#2] deck / design / mop / ops / runbook / crd / engagement / archreview each coerced a device-derived
    count with a raw int() / round() / unary-minus (or an _as_int/_i guard that missed OverflowError). A single
    malformed leaf (inf / str / dict) 500'd the webapp deliverable route or aborted the doc. Each must now
    degrade the field and still emit a valid file."""
    pytest.importorskip("docx")
    pytest.importorskip("pptx")
    from cisco_toolkit import archreview, crd, deck, design, engagement, mop, ops, runbook
    snap = _hostile_numeric_snapshot()
    deck.write_executive_deck_pptx(str(tmp_path / "k.pptx"), snap, "AJ")
    design.write_design_doc_docx(str(tmp_path / "d.docx"), snap, "AJ")
    mop.write_mop_docx(str(tmp_path / "m.docx"), snap, "AJ")
    ops.write_ops_handbook_docx(str(tmp_path / "o.docx"), snap, "AJ")
    runbook.write_runbook_docx(str(tmp_path / "r.docx"), snap, "AJ")
    crd.write_crd_docx(str(tmp_path / "c.docx"), snap, "AJ")
    engagement.write_engagement_docx(str(tmp_path / "e.docx"), snap, "AJ")
    archreview.write_archreview_docx(str(tmp_path / "a.docx"), snap, "AJ")
    assert all((tmp_path / f).exists()
               for f in ("k.pptx", "d.docx", "m.docx", "o.docx", "r.docx", "c.docx", "e.docx", "a.docx"))


# --- finding #4: compute_device_dossiers -------------------------------------------------------------------
def test_compute_device_dossiers_tolerates_malformed_counts():
    """[#4] The dossier coerced failure_impact.stranded/vlans_impacted with a raw int() (ValueError on 'many',
    OverflowError on inf) and compared golden_drift.n_missing / compliance_pct with >= / < (TypeError on a
    str). Reachable via the webapp section recompute. All routed through _as_num now."""
    from cisco_toolkit import analyze
    out = analyze.compute_device_dossiers(
        health_scores=[{"switch": "SW1", "band": "Healthy", "role": "core"}],
        failure_impact=[{"host": "SW1", "stranded": "many", "vlans_impacted": INF, "severity": "High"}],
        golden_drift={"summary": {"n_baseline": 3},
                      "per_device": [{"host": "SW1", "n_missing": "many", "compliance_pct": "high"}]})
    assert isinstance(out, dict) and "per_device" in out


# --- reachable-class sibling (surfaced during the fix): the /design + /architecture_coverage compute --------
def test_compute_design_blueprint_tolerates_malformed_counts():
    """design_advisor._as_int + inline int() guards (cfg_priority / root_priority / num_power_supplies) missed
    OverflowError, so a JSON Infinity in those device counts 500'd the /design + /architecture_coverage
    endpoints (compute_design_blueprint runs on the uploaded snapshot). Not in the original finding list -- a
    same-class sibling the audit-6 fuzz surfaced; the user opted to fix the whole reachable class."""
    from cisco_toolkit import design_advisor
    snap = {
        "devices": {"SW1": {"num_power_supplies": INF, "ps_status": "fail"}},
        "health_scores": [{"switch": "SW1", "role": "core"}],
        "l3_forwarding": [{"switch": "SW1", "vlan": "10", "fhrp": "hsrp", "cfg_priority": INF, "preempt": False}],
        "stp_roots": {"SW1": {"10": {"root_priority": INF, "is_root": True}}},
        # _signals also coerces these with float(): a non-numeric coverage (ValueError) + a huge-int port_util
        # (float(10**400) -> OverflowError) each 500'd /design before _as_float was hardened.
        "segmentation": {"summary": {"gateway_acl_coverage": "high", "n_gateways": INF}},
        "capacity": [{"hostname": "SW1", "port_util": 10 ** 400, "poe_util": INF}],
    }
    bp = design_advisor.compute_design_blueprint(snap, {})     # must NOT raise OverflowError / ValueError
    assert isinstance(bp, dict)


# --- finding #3: the cable map (engine SSOT) ---------------------------------------------------------------
def test_cable_map_of_snapshot_tolerates_wrongtyped_interface_fields():
    """[#3] compute_cable_map / cable_map_of_snapshot promise 'Tolerant -- never raises', but .strip()/.lower()
    on a wrong-typed cdp_neighbor (list) / status (int) / neighbor_port / port_channel raised AttributeError.
    Reachable UNWRAPPED via the webapp /cable_map + /graph endpoints. str()-coerced now."""
    from cisco_toolkit import analyze
    snap = {"interfaces": {
        "SW1": {
            "Gi1/0/1": {"cdp_neighbor": ["SW2"], "endpoint_type": "Switch", "neighbor_port": ["Gi2"],
                        "status": 1, "port_channel": ["Po1"]},
            "Gi1/0/2": {"cdp_neighbor": ["PHONE"], "neighbor_port": 5},   # non-infra -> exercises _canon_host(cdp)
        },
        "SW2": {"Gi2": {"cdp_neighbor": 7, "endpoint_type": "Switch", "neighbor_port": 5,
                        "status": {"x": 1}, "port_channel": 99}},
    }}
    cm = analyze.cable_map_of_snapshot(snap)      # docstring contract: never raises
    assert isinstance(cm, dict) and "nodes" in cm


# --- finding #5: the campaign trend point ------------------------------------------------------------------
def test_trend_point_tolerates_nonlist_and_nondict_row_sections():
    """[#5] _trend_point iterated health_scores / migration_readiness / punchlist assuming a list-of-dicts; a
    dict there iterates its KEYS (str), and str.get raises AttributeError -> the trend workbook aborts (the
    CLI --trend path is unwrapped). Guarded to a list of dicts."""
    from cisco_toolkit import html
    for bad_snap in (
        {"health_scores": {"k": "v"}},
        {"migration_readiness": {"k": "v"}},
        {"punchlist": {"k": "v"}},
        {"health_scores": ["notadict", 5], "migration_readiness": [None], "punchlist": [1, "x"]},
        # truthy non-dict SECTION / subsection (a different class than the list iterations above): the `or {}`
        # pattern let these through to a .get()/len() that raised -> 500 on the unwrapped /trend endpoint.
        {"lifecycle_risk": [1]},
        {"executive_brief": "corrupt"},
        {"executive_brief": {"scale": [1], "posture": "x"}},
        {"devices": 5},
    ):
        assert isinstance(html._trend_point(bad_snap), dict)


def test_compute_campaign_trend_tolerates_nonlist_health_scores():
    """[#5] Propagates to the public CLI --trend entry: compute_campaign_trend calls _trend_point per snap."""
    from cisco_toolkit import html
    out = html.compute_campaign_trend([{"health_scores": {"k": "v"}, "devices": {"a": {}}}])
    assert isinstance(out, dict) and "timeline" in out


# --- finding #6: the opt-in controller-REST collectors -----------------------------------------------------
def test_collect_apic_tolerates_scalar_imdata(tmp_path, monkeypatch):
    """[#6] The APIC fault-envelope check iterated `for m in (obj.get('imdata') or [])`; a truthy SCALAR imdata
    (7 / true / a float in a malformed or spoofed controller reply) is not iterable -> TypeError aborted the
    opt-in collector. Now isinstance-guarded to a list."""
    from cisco_toolkit import rest_collect
    monkeypatch.setattr(rest_collect, "_post", lambda *a, **k: object())        # login "succeeds"
    monkeypatch.setattr(rest_collect, "_safe_close", lambda *a, **k: None)
    monkeypatch.setattr(rest_collect, "_get_json", lambda *a, **k: {"imdata": 7})   # truthy scalar
    monkeypatch.setattr(rest_collect, "_write", lambda out_dir, cmd, obj: f"{out_dir}/{cmd}")
    out = rest_collect.collect_apic("https://apic.example", "ro", "pw", str(tmp_path))
    assert isinstance(out, list)                  # must NOT raise TypeError


def test_collect_ise_tolerates_nondict_searchresult(tmp_path, monkeypatch):
    """[#6] ISE ERS pagination did `(sr.get('SearchResult') or {}).get('resources')`; a truthy NON-DICT
    SearchResult (a scalar/list in a malformed or spoofed ERS reply) slips past `or {}` -> AttributeError.
    Now isinstance-guarded; pagination stops cleanly."""
    from cisco_toolkit import rest_collect
    monkeypatch.setattr(rest_collect, "_get_json", lambda *a, **k: {"SearchResult": 7})   # truthy non-dict
    monkeypatch.setattr(rest_collect, "_write", lambda out_dir, cmd, obj: f"{out_dir}/{cmd}")
    out = rest_collect.collect_ise("https://ise.example", "ro", "pw", str(tmp_path))
    assert isinstance(out, list)                  # must NOT raise AttributeError
