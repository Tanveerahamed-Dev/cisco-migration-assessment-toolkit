"""G14: a section whose analysis phase FAILED must never read as "collected, nothing found".

`_run_phase` is fail-soft: a phase that raises returns its `_default` (usually `[]` / `{}`) and the
failure is recorded in `assessment_integrity.failed_phases`. The SSOT abstention core
(`ssot.abstention_reason`) never read that record, so the fallback -- byte-identical to a clean
empty result -- was classified `collected_but_empty` ("collected, nothing of this kind found (not a
blind spot)"). The coverage census, the state-assertion pack (a `not_contains "Critical"` check over
a crashed punch-list PASSED) and the Law-8 eval all inherited that lie.

The honest token is `analysis_unavailable` -- the engine already uses it for a failed protocol
analysis -- attributed through ONE registry (`ssot.PHASE_SECTIONS`) that an AST ratchet below keeps
complete against `COLLECT_PARSE_V3_23_0.main()`: a phase added there without a classification fails
this file rather than silently tainting nothing.
"""
import ast
import json
import os
import pathlib
import sys

import pytest

from cisco_toolkit import ssot

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENGINE = ROOT / "COLLECT_PARSE_V3_23_0.py"
GOLDEN = ROOT / "tests" / "golden" / "snapshot.json"
SAMPLE = ROOT / "webapp" / "sample_data" / "sample_fleet.snapshot.json"
AU = "analysis_unavailable"
CBE = "collected_but_empty"


def _failed(labels, **sections):
    return dict(sections, assessment_integrity={"failed_phases": labels})


# --------------------------------------------------------------------------------------------------
# abstention_reason
# --------------------------------------------------------------------------------------------------
def test_t1_failed_phase_section_is_unavailable_and_an_independent_empty_is_not():
    snap = _failed(["QoS audit"], qos_audit={}, vpc={})
    assert ssot.abstention_reason(snap, "qos_audit") == AU
    assert ssot.abstention_reason(snap, "vpc") == CBE
    assert ssot.ANALYSIS_UNAVAILABLE == AU


def test_t2_a_populated_error_default_is_unavailable_not_published():
    default = {"schema": "traffic_assurance_set/1", "state": "error", "results": [],
               "summary": {"n": 0, "proven": 0, "refuted": 0}}
    assert ssot.abstention_reason(_failed(["Traffic assurance"], traffic_assurance=default),
                                  "traffic_assurance") == AU


def test_t3_unavailable_sentinel_taints_the_section_and_its_subpaths():
    snap = {"executive_brief": {"_unavailable": True, "ssot": {"n_facts": 3}}}
    assert ssot.abstention_reason(snap, "executive_brief") == AU
    assert ssot.abstention_reason(snap, "executive_brief.ssot.n_facts") == AU


def test_t4_integrity_stamp_on_a_section_key_is_honoured_and_a_non_section_stamp_is_not():
    snap = {"assessment_integrity": {"architecture_review": "compute_failed"},
            "architecture_review": {"grade": "A"}}
    assert ssot.abstention_reason(snap, "architecture_review") == AU
    drift = {"assessment_integrity": {"ssot_reconciliation": "failed"}, "vpc": {}}
    assert ssot.abstention_reason(drift, "vpc") == CBE


def test_t5_an_absent_section_of_a_failed_phase_is_unavailable_not_a_blind_spot():
    assert ssot.abstention_reason(_failed(["State assertion pack"]), "state_assertions") == AU
    assert ssot.abstention_reason({}, "state_assertions") == "not_collected"


def test_t6_a_failed_workbook_sheet_writer_does_not_taint_the_section():
    assert ssot.abstention_reason(_failed(["QoS Audit sheet"], qos_audit={}), "qos_audit") == CBE


def test_t7_a_failed_intermediate_taints_every_empty_section_but_not_populated_ones():
    snap = _failed(["dependency map"], cross_layer=[], vpc={"sw1": {"role": "primary"}})
    assert ssot.abstention_reason(snap, "cross_layer") == AU
    assert ssot.abstention_reason(snap, "vpc") == "published"


def test_t8_an_unknown_label_fails_closed():
    snap = _failed(["X new phase"], qos_audit={}, vpc={"sw1": {"role": "primary"}})
    assert ssot.abstention_reason(snap, "qos_audit") == AU
    assert ssot.abstention_reason(snap, "vpc") == "published"


def test_t9_a_malformed_failure_record_fails_closed_and_garbage_does_not_crash():
    snap = {"assessment_integrity": {"failed_phases": "QoS audit"}, "qos_audit": {}}
    assert ssot.abstention_reason(snap, "qos_audit") == AU
    garbage = {"assessment_integrity": "garbage", "vpc": {}}
    assert ssot.abstention_reason(garbage, "vpc") == CBE
    assert ssot.failed_sections(garbage) == (frozenset(), False)
    assert ssot.failed_sections(None) == (frozenset(), False)


def test_t10_a_device_blind_spot_still_wins():
    snap = _failed(["QoS audit"], qos_audit={},
                   collection_completeness={"devices": [{"host": "sw9", "status": "not collected"}]})
    assert ssot.abstention_reason(snap, "qos_audit", device="sw9") == "not_collected"


def test_failed_sections_reports_attribution():
    direct, unattributed = ssot.failed_sections(
        _failed(["Golden-config drift", "QoS Audit sheet", "HTML Explorer"]))
    assert {"golden_drift", "feature_compliance"} <= direct and not unattributed
    _d, unattributed = ssot.failed_sections(_failed(["dependency map"]))
    assert unattributed


# --------------------------------------------------------------------------------------------------
# consumers: census / assertions / Law-8 eval
# --------------------------------------------------------------------------------------------------
def test_c1_census_counts_the_new_state_honestly():
    census = ssot.compute_schema_census(_failed(["QoS audit"], qos_audit={}, vpc={}))
    rows = {r["key"]: r for r in census["sections"]}
    assert rows["qos_audit"]["state"] == AU and rows["vpc"]["state"] == CBE
    note = rows["qos_audit"]["note"].lower()
    assert "failed" in note and not any(w in note.split() for w in ("ok", "healthy"))
    s = census["summary"]
    assert s["n_analysis_unavailable"] == 1
    assert (s["n_published"] + s["n_collected_but_empty"] + s["n_not_collected"]
            + s["n_analysis_unavailable"]) == s["n_sections"]
    clean = ssot.compute_schema_census({"vpc": {}, "qos_audit": {"a": 1}})["summary"]
    assert set(clean) == {"n_published", "n_collected_but_empty", "n_not_collected", "n_sections"}


def test_a1_assertion_over_a_crashed_section_abstains_instead_of_passing():
    from cisco_toolkit import assertions
    snap = {"assessment_integrity": {"failed_phases": ["Migration Punch-List"]}, "punchlist": []}
    spec = {"id": "no-crit", "subject": "punchlist",
            "all_of": [{"type": "not_contains", "value": "Critical"}]}
    r = assertions.evaluate_assertion(snap, spec)
    assert r["status"] == assertions.NOT_OBSERVED and r["abstention"] == AU, r
    pack = assertions.evaluate_pack(snap, {"assertions": [spec]})
    assert pack["summary"]["n_pass"] == 0 and pack["summary"]["n_assessed"] == 0, pack["summary"]


def test_a1b_for_each_over_a_crashed_section_abstains():
    from cisco_toolkit import assertions
    snap = {"assessment_integrity": {"architecture_review": "compute_failed"},
            "architecture_review": {"sw1": {"grade": "A"}}}
    spec = {"id": "fe", "for_each": "architecture_review",
            "field_rules": [{"field": "grade", "type": "contains", "value": "A"}]}
    r = assertions.evaluate_pack(snap, {"for_each": [spec]})["results"][0]
    assert r["status"] == assertions.NOT_OBSERVED and r["abstention"] == AU, r


def test_e1_law8_census_accounts_for_the_new_state():
    from cisco_toolkit import eval_harness
    snap = _failed(["QoS audit"], qos_audit={}, vpc={})
    assert ssot.compute_schema_census(snap)["summary"].get("n_analysis_unavailable") == 1
    checks = {c.check_id: c for c in eval_harness._check_not_observed(snap, None)}
    assert checks["law8.census"].status == eval_harness._PASS, checks["law8.census"]


def test_e1b_law8_rejects_a_healthy_note_on_an_unavailable_row(monkeypatch):
    from cisco_toolkit import eval_harness
    monkeypatch.setitem(ssot._CENSUS_NOTE, AU, "ok")
    checks = {c.check_id: c for c in eval_harness._check_not_observed(
        _failed(["QoS audit"], qos_audit={}), None)}
    assert checks["law8.census"].status == eval_harness._FAIL


# --------------------------------------------------------------------------------------------------
# the committed snapshots are unchanged (no failure record in either)
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("path", [GOLDEN, SAMPLE], ids=["golden", "sample"])
def test_g1_committed_snapshots_classify_exactly_as_embedded(path):
    s = json.loads(path.read_text(encoding="utf-8"))
    assert ssot.failed_sections(s) == (frozenset(), False)
    embedded = {r["key"]: r["state"] for r in s["schema_census"]["sections"]}
    # The golden strips its volatile sections (generated_at, executive_brief, ...) AFTER the census was
    # embedded; only the sections it still carries can be re-classified from its own bytes.
    present = [k for k in embedded if k in s]
    assert len(present) >= 100, len(present)
    for key in present:
        assert ssot.abstention_reason(s, key) == embedded[key], key


def test_g1_sample_census_recomputes_byte_equal():
    s = json.loads(SAMPLE.read_text(encoding="utf-8"))
    assert ssot.compute_schema_census(s) == s["schema_census"]


def test_r2_the_token_is_the_engine_vocabulary():
    from cisco_toolkit import analyze
    assert ssot.ANALYSIS_UNAVAILABLE in analyze.PROTOCOL_ASSESSABILITY_STATES
    assert ssot.ANALYSIS_UNAVAILABLE in ssot.ABSTENTION_STATES
    assert set(ssot._CENSUS_NOTE) == set(ssot.ABSTENTION_STATES)


# --------------------------------------------------------------------------------------------------
# R1: the registry is complete against the engine's own source (AST ratchet)
# --------------------------------------------------------------------------------------------------
_RECORDERS = ("_run_phase", "_emit_artifact", "_record_phase_failure", "_record_mandatory_failure",
              "_atomic_receipt_refresh")


def _engine():
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    return tree, main


def _label_node(call):
    if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id in _RECORDERS \
            and call.args:
        return call.args[0]
    return None


def _all_labels(tree):
    """Every literal failure label the engine can record, plus the leading text of f-string labels."""
    literal, fstring_prefixes = set(), set()
    for n in ast.walk(tree):
        node = _label_node(n)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literal.add(node.value)
        elif isinstance(node, ast.JoinedStr):
            head = node.values[0] if node.values else None
            fstring_prefixes.add(head.value if isinstance(head, ast.Constant) else "")
        # a Name label is either a recorder's own parameter or the data-authority loop variable below
        if isinstance(n, ast.For) and isinstance(n.target, ast.Tuple) and isinstance(n.iter, ast.Tuple):
            names = [t.id for t in n.target.elts if isinstance(t, ast.Name)]
            if "_axis" in names:
                idx = names.index("_axis")
                for elt in n.iter.elts:
                    if isinstance(elt, ast.Tuple) and isinstance(elt.elts[idx], ast.Constant):
                        literal.add(elt.elts[idx].value)
    return literal, fstring_prefixes


def _direct_edges(main):
    """section -> {labels}: `snap_dict["k"] = <expr>` where <expr> is a `_run_phase("L")` call or
    names a variable assigned from one."""
    var_labels, edges = {}, {}

    def calls(expr):
        return [c for c in ast.walk(expr) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                and c.func.id == "_run_phase" and c.args and isinstance(c.args[0], ast.Constant)]

    for n in ast.walk(main):
        if not isinstance(n, ast.Assign):
            continue
        cs = calls(n.value)
        for t in n.targets:
            if isinstance(t, ast.Name) and cs:
                var_labels.setdefault(t.id, set()).update(c.args[0].value for c in cs)
    for n in ast.walk(main):
        if not isinstance(n, ast.Assign):
            continue
        for t in n.targets:
            if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id == "snap_dict"
                    and isinstance(t.slice, ast.Constant)):
                labels = {c.args[0].value for c in calls(n.value)}
                for name in {x.id for x in ast.walk(n.value) if isinstance(x, ast.Name)}:
                    labels |= var_labels.get(name, set())
                if labels:
                    edges.setdefault(t.slice.value, set()).update(labels)
    return edges


def test_r1_every_direct_phase_to_section_edge_is_registered():
    _tree, main = _engine()
    edges = _direct_edges(main)
    assert len(edges) >= 50, "the edge extractor went blind -- a ratchet over nothing proves nothing"
    missing = sorted((k, lab) for k, labs in edges.items() for lab in labs
                     if k not in ssot.PHASE_SECTIONS.get(lab, ()))
    assert not missing, f"phase->section edges absent from ssot.PHASE_SECTIONS: {missing}"


def test_r1_every_failure_label_is_classified():
    tree, _main = _engine()
    literal, prefixes = _all_labels(tree)
    assert len(literal) >= 150, "the label extractor went blind"
    unclassified = sorted(lab for lab in literal if ssot.phase_classification(lab) == "unknown")
    assert not unclassified, f"classify these in ssot (sections / intermediate / non-section): {unclassified}"
    assert prefixes == {"interface rows ("}, prefixes
    assert all(ssot.phase_classification(p + "sw1)") == "non_section" for p in prefixes)


def test_r1_registry_sets_are_disjoint_and_sheet_writers_own_no_section():
    sec, mid, non = set(ssot.PHASE_SECTIONS), set(ssot.INTERMEDIATE_PHASES), set(ssot.NON_SECTION_PHASES)
    assert not (sec & mid) and not (sec & non) and not (mid & non)
    assert not [lab for lab in sec | mid if lab.endswith(" sheet")]
    _tree, main = _engine()
    for n in ast.walk(main):
        if not isinstance(n, ast.Assign):
            continue
        for c in ast.walk(n.value):
            node = _label_node(c)
            if (getattr(c, "func", None) is not None and getattr(c.func, "id", "") == "_run_phase"
                    and isinstance(node, ast.Constant) and node.value.endswith(" sheet")):
                pytest.fail(f"sheet writer {node.value!r} returns a value that is used")


# --------------------------------------------------------------------------------------------------
# P1: the real engine
# --------------------------------------------------------------------------------------------------
def _run_engine(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "tests"))
    import synthetic_fixtures as fx
    from openpyxl import Workbook
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import COLLECT_PARSE_V3_23_0 as cp
    collection = fx.write_collection(str(tmp_path / "collection"))
    devices = tmp_path / "devices.json"
    devices.write_text(json.dumps(fx.DEVICES), encoding="utf-8")
    template = tmp_path / "template.xlsx"
    wb = Workbook(); wb.active.title = "Interface Data"; wb.active.append(["Hostname", "Port", "Status"])
    wb.save(str(template))
    out = tmp_path / "out.xlsx"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["cisco-assess", "--no-collect", "--collection-dir", collection,
                                      "--devices-file", str(devices), "--template", str(template),
                                      "--output", str(out), "--workers", "1", "--no-html"])
    return cp, out


def _census_rows(out):
    snap = json.loads(pathlib.Path(str(out)[:-len(".xlsx")] + ".snapshot.json").read_text(encoding="utf-8"))
    return snap, {r["key"]: r["state"] for r in snap["schema_census"]["sections"]}


def test_p1_real_engine_reports_crashed_phases_as_unavailable(tmp_path, monkeypatch):
    cp, out = _run_engine(tmp_path, monkeypatch)

    def _boom(*a, **kw):
        raise RuntimeError("synthetic phase failure")

    for name in ("compute_cross_layer_correlations", "_punchlist", "compute_qos_audit"):
        monkeypatch.setattr(cp, name, _boom)
    cp.main()
    snap, rows = _census_rows(out)
    for key in ("cross_layer", "punchlist", "qos_audit"):
        assert rows[key] == AU, (key, rows[key], snap.get("assessment_integrity"))
    for key in ("vpc", "mroute", "trunk_native", "link_phy", "addressing_conflicts"):
        if key in rows and rows[key] != "published":
            assert rows[key] == CBE, (key, rows[key])
    assert snap["schema_census"]["summary"]["n_analysis_unavailable"] >= 3


def test_p1_clean_real_engine_run_has_no_unavailable_row(tmp_path, monkeypatch):
    cp, out = _run_engine(tmp_path, monkeypatch)
    cp.main()
    snap, rows = _census_rows(out)
    assert "assessment_integrity" not in snap, snap.get("assessment_integrity")
    assert AU not in rows.values()
    assert "n_analysis_unavailable" not in snap["schema_census"]["summary"]
