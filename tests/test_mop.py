"""NEW-V3.23.149: the per-wave Method of Procedure (MOP, DOCX) deliverable. python-docx is optional, so
the module is skipped when it is absent (the generator fails soft the same way). These tests pin the
one-section-per-wave structure, the change-overview reconciliation, the reuse of the existing validation
plan as the post-cutover checks, the blocker surfacing, and the fail-soft path."""
import pytest

docx = pytest.importorskip("docx")  # skip the file if the optional dep is absent
from docx import Document  # noqa: E402

from cisco_toolkit.mop import write_mop_docx  # noqa: E402


def _snap():
    """A two-wave migration snapshot exercising every part of a MOP wave section."""
    return {
        "script_version": "V3.23.0",
        "devices": {"distA": {"platform": "ios"}, "distB": {"platform": "nxos"}, "acc1": {"platform": "ios"}},
        "move_groups": [{"switches": ["distA", "distB"], "endpoints": 40},
                        {"switches": ["acc1"], "endpoints": 12}],
        "migration_readiness": [
            {"group": "Group 1", "switches": ["distA", "distB"], "endpoints": 40,
             "readiness": "CAUTION", "n_fail": 0, "n_warn": 2, "checks": []},
            {"group": "Group 2", "switches": ["acc1"], "endpoints": 12,
             "readiness": "NOT READY", "n_fail": 1, "n_warn": 0, "checks": []},
        ],
        "wave_sequencing": [
            {"group": "Group 1", "make_before_break": ["distA", "distB"], "hard_cutover": [],
             "hard_cutover_endpoints": 0, "sequence": "make-before-break"},
            {"group": "Group 2", "make_before_break": [], "hard_cutover": ["acc1"],
             "hard_cutover_endpoints": 12, "sequence": "hard-cutover"},
        ],
        "migration_scenarios": {
            "per_group": [
                {"group": "Group 1", "switches": 2, "endpoints": 40, "readiness": "CAUTION",
                 "recommended_scenario": "parallel-run", "rationale": "dual-homed — build beside",
                 "playbook": {"pre": "stage target beside legacy", "validate": "cut one leg, prove forwarding",
                              "rollback": "fail back to the legacy leg"}},
                {"group": "Group 2", "switches": 1, "endpoints": 12, "readiness": "NOT READY",
                 "recommended_scenario": "hard-cutover", "rationale": "single-homed access edge",
                 "playbook": {"pre": "schedule outage window", "validate": "ping the gateway",
                              "rollback": "re-cable to legacy port"}},
            ],
            "fleet_recommendation": "Cut the dual-homed core first, then the single-homed access edge.",
            "scenario_counts": {"parallel-run": 1, "hard-cutover": 1},
        },
        "validation_plan": {
            "items": [
                {"category": "Gateway", "device": "distA", "check": "VLAN 10 gateway up",
                 "command": "show ip interface brief", "expect": "10.0.10.1 up/up", "wave": "Group 1"},
                {"category": "FHRP", "device": "distA", "check": "HSRP role",
                 "command": "show standby brief", "expect": "Active/Standby", "wave": "Group 1"},
                {"category": "Reachability", "device": "acc1", "check": "gateway reachable",
                 "command": "ping 10.0.20.1", "expect": "100 percent", "wave": "Group 2"},
            ],
            "by_wave": {
                "Group 1": [
                    {"category": "Gateway", "device": "distA", "check": "VLAN 10 gateway up",
                     "command": "show ip interface brief", "expect": "10.0.10.1 up/up", "wave": "Group 1"},
                    {"category": "FHRP", "device": "distA", "check": "HSRP role",
                     "command": "show standby brief", "expect": "Active/Standby", "wave": "Group 1"},
                ],
                "Group 2": [
                    {"category": "Reachability", "device": "acc1", "check": "gateway reachable",
                     "command": "ping 10.0.20.1", "expect": "100 percent", "wave": "Group 2"},
                ],
            },
            "summary": {"n_items": 3, "n_waves": 2, "n_high": 2, "by_category": {"Gateway": 1}},
            "banner": "3 checks across 2 waves",
        },
        "failure_impact": [{"host": "distA", "severity": "High", "stranded": 22, "vlans_impacted": 3},
                           {"host": "acc1", "severity": "Medium", "stranded": 6, "vlans_impacted": 1}],
        "remediation_plan": {"items": [
            {"source": "fhrp", "device": "acc1", "severity": "High", "title": "Add FHRP peer",
             "why": "single gateway strands the VLAN", "commands": ["interface Vlan20", " standby 20 ip 10.0.20.254"]},
            {"source": "hygiene-undefined", "device": "distA", "severity": "Low", "title": "unused ACL",
             "commands": ["! review only"]},
        ]},
        "punchlist": [{"severity": "Critical", "category": "L3 design", "devices": ["acc1"],
                       "title": "VLAN 20 single gateway", "detail": "x"},
                      {"severity": "Low", "category": "Hygiene", "devices": ["distA"],
                       "title": "cosmetic", "detail": "y"}],
        "executive_brief": {"top_gating": ["Resolve the VLAN 20 single-gateway exposure before wave 2."]},
    }


def _all_text(doc):
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            parts.extend(c.text for c in row.cells)
    return "\n".join(parts)


def test_mop_has_one_section_per_wave(tmp_path):
    out = str(tmp_path / "m.docx")
    write_mop_docx(out, _snap(), "Unit Test Fleet")
    d = Document(out)
    h1 = [p.text for p in d.paragraphs if p.style.name == "Heading 1"]
    assert any(t == "1. Change Overview" for t in h1)
    assert any(t.startswith("2. Global Prerequisites") for t in h1)
    # one MOP section per wave
    assert any(t == "3. MOP — Group 1" for t in h1), h1
    assert any(t == "4. MOP — Group 2" for t in h1), h1
    # final acceptance section closes it
    assert any("Post-Migration Acceptance" in t for t in h1)


def test_mop_reuses_validation_plan_as_checks(tmp_path):
    out = str(tmp_path / "m.docx")
    write_mop_docx(out, _snap(), "Unit Test Fleet")
    text = _all_text(Document(out))
    # the EXISTING validation plan items appear as the post-cutover go/no-go checks (one source of truth)
    assert "show standby brief" in text and "Active/Standby" in text          # Group 1 FHRP check
    assert "ping 10.0.20.1" in text and "100 percent" in text                 # Group 2 reachability check
    # strategy drives the procedure wording: make-before-break vs hard cutover
    assert "BESIDE" in text or "beside" in text
    assert "hard cutover" in text.lower()


def test_mop_surfaces_blockers_and_rollback(tmp_path):
    out = str(tmp_path / "m.docx")
    write_mop_docx(out, _snap(), "Unit Test Fleet")
    text = _all_text(Document(out))
    # the high-severity remediation for acc1 is surfaced as a wave-2 blocker (Low items are not)
    assert "Add FHRP peer" in text
    assert "standby 20 ip 10.0.20.254" in text
    # the critical punch-list item touching acc1 surfaces; rollback + sign-off scaffolding present
    assert "VLAN 20 single gateway" in text
    assert "Rollback" in text and "fail back to the legacy leg" in text
    assert "Implementing engineer" in text
    # the change overview reconciles the wave count
    assert "2 wave(s)" in text or "sequenced into 2 wave(s)" in text


def test_mop_carries_document_furniture(tmp_path):
    """V3.23.150: AS-style front matter (Document Control with the 'Ready for service' caveat from
    the Cisco migration-service MOP definition) + the closing signature gate under the existing
    Post-Migration Acceptance section (no new H1)."""
    out = str(tmp_path / "m.docx")
    write_mop_docx(out, _snap(), "Unit Test Fleet")
    d = Document(out)
    h1 = [p.text for p in d.paragraphs if p.style.name == "Heading 1"]
    assert "Document Control" in h1
    assert "Document Acceptance" not in h1            # gate renders under Post-Migration Acceptance
    text = _all_text(d)
    assert "Ready for service" in text                # MOP-specific acceptance-criteria caveat
    assert "Customer network owner" in text           # closing signature roles
    assert "Assessment workbook (.xlsx)" in text      # related-documents cross-reference


def test_mop_port_mapping_raci_and_success_criteria(tmp_path):
    """V3.23.155: the migration-service MOP shape — §2.1 RACI, per-wave §x.4 port/interface mapping
    with <target> columns + evidence-derived staged config stubs, and a success criterion per step."""
    snap = _snap()
    snap["interfaces"] = {
        "acc1": {
            "Gi1/0/5": {"switchport_mode": "Access", "vlan": "20", "end_host_mac": "bbbb.0000.0001",
                        "description": "CAM-12"},
            "Gi1/0/1": {"switchport_mode": "Trunk", "cdp_neighbor": "distA"},
            "Gi1/0/9": {"switchport_mode": "Access", "vlan": "30"},   # no endpoint evidence
        },
    }
    out = str(tmp_path / "m.docx")
    write_mop_docx(out, snap, "Unit Test Fleet")
    d = Document(out)
    text = _all_text(d)
    h2 = [p.text for p in d.paragraphs if p.style.name == "Heading 2"]
    # RACI up front, per the AS migration-service ownership split
    assert "2.1 Responsibilities (RACI)" in h2
    assert "In-window execution of each step" in text and "Customer operations" in text
    # wave 2 (acc1) = section 4: mapping table reads the evidence, target columns stay placeholders
    assert "4.4 Port / interface mapping & staged configuration" in h2, h2
    assert "Gi1/0/5" in text and "<target device>" in text
    assert "Uplink → distA" in text
    assert "Gi1/0/9" not in text                        # no endpoint evidence → excluded
    assert "switchport access vlan 20" in text          # evidence-derived staged stub
    assert "description CAM-12" in text
    # renumbered chain + per-step success criteria
    assert "4.5 Cutover procedure" in h2 and "4.8 Sign-off" in h2
    assert "Success:" in text
    # wave 1 (distA/distB) has no interface evidence → the fresh-collection fallback renders
    assert "build the mapping from a fresh interface collection" in text


def test_mop_failsoft_without_python_docx(monkeypatch, tmp_path):
    import builtins, os
    real_import = builtins.__import__

    def _blocked(name, *a, **k):
        if name == "docx" or name.startswith("docx."):
            raise ImportError("simulated missing python-docx")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    out = str(tmp_path / "m.docx")
    write_mop_docx(out, _snap(), "Unit Test Fleet")   # must not raise
    assert not os.path.exists(out)


def test_mop_join_apportions_endpoints_to_subwave():
    """AUDIT FIX: a coupled sub-wave (a SLICE of a larger move-group) must NOT inherit the parent group's
    full endpoint total — apportion by the sub-wave's switch share. A full-coverage wave keeps the total."""
    from cisco_toolkit.mop import _join_group_records
    rbg = {"Group 1": {"group": "Group 1", "switches": ["a", "b", "c", "d"], "endpoints": 400,
                       "n_fail": 0, "n_warn": 2, "readiness": "CAUTION"}}
    r1, *_ = _join_group_records(["Group 1"], ["a"], rbg, {}, {}, {})       # 1 of 4 switches
    assert r1["endpoints"] == 100                                          # 400 * 1/4, NOT 400
    r4, *_ = _join_group_records(["Group 1"], ["a", "b", "c", "d"], rbg, {}, {}, {})
    assert r4["endpoints"] == 400                                          # full coverage -> full total


def _snap_waves():
    """_snap() + a canonical wave_plan: Group 1 (distA,distB) sliced into 2 coupled-subwaves; Group 2
    (acc1) as an independent-batch — 3 waves."""
    snap = _snap()
    snap["design_blueprint"] = {"target_state": {"wave_plan": {
        "waves": [
            {"wave": 1, "kind": "coupled-subwave", "n_switches": 1, "switches": ["distA"], "source_groups": [0]},
            {"wave": 2, "kind": "coupled-subwave", "n_switches": 1, "switches": ["distB"], "source_groups": [0]},
            {"wave": 3, "kind": "independent-batch", "n_switches": 1, "switches": ["acc1"], "source_groups": [1]},
        ],
        "n_waves": 3, "wave_cap": 40, "n_move_groups": 2, "largest_group": 2, "n_subdivided_groups": 1,
        "note": "candidate waves"}}}
    return snap


def test_mop_sections_keyed_to_wave_plan(tmp_path):
    """F2: with a canonical wave_plan the MOP emits one section per WAVE (wave-keyed title), not one per
    move-group/readiness row."""
    out = str(tmp_path / "m.docx")
    write_mop_docx(out, _snap_waves(), "Unit Test Fleet")
    h1 = [p.text for p in Document(out).paragraphs if p.style.name == "Heading 1"]
    assert any(t == "3. MOP — Wave 1 (coupled-subwave)" for t in h1), h1
    assert any(t == "4. MOP — Wave 2 (coupled-subwave)" for t in h1), h1
    assert any(t == "5. MOP — Wave 3 (independent-batch)" for t in h1), h1
    assert not any("MOP — Group 1" in t for t in h1)             # NOT keyed on move-groups when wave_plan present


def test_mop_coupled_subwave_surfaces_shared_vlan_caveat(tmp_path):
    """F2 honesty: coupled-subwave sections carry the shared-L2/VLAN SEQUENCE caveat; an independent-batch
    wave does not."""
    out = str(tmp_path / "m.docx")
    write_mop_docx(out, _snap_waves(), "Unit Test Fleet")
    d = Document(out)
    paras = [p.text for p in d.paragraphs]
    # the caveat appears (coupled sub-wave shares VLANs, is a SEQUENCE)
    assert any("coupled sub-wave" in t.lower() and "SEQUENCE" in t for t in paras), paras[:0] or "no caveat"
    assert sum(1 for t in paras if "Shared-L2 coordination" in t) >= 2   # one per coupled-subwave (waves 1 & 2)


def test_mop_reads_wave_plan_not_recompute(tmp_path):
    """F2 REFUTATION / SSOT mutation guard: a wave_plan grouping move_groups would NEVER produce
    (distA + acc1 together) must render verbatim — proving the MOP reads wave_plan, not a re-slice of
    move_groups."""
    snap = _snap()
    snap["design_blueprint"] = {"target_state": {"wave_plan": {
        "waves": [
            {"wave": 1, "kind": "independent-batch", "n_switches": 2, "switches": ["distA", "acc1"], "source_groups": [0, 1]},
            {"wave": 2, "kind": "coupled-subwave", "n_switches": 1, "switches": ["distB"], "source_groups": [0]},
        ],
        "n_waves": 2, "wave_cap": 40, "n_move_groups": 2, "largest_group": 2, "n_subdivided_groups": 0, "note": "x"}}}
    out = str(tmp_path / "m.docx")
    write_mop_docx(out, snap, "Unit Test Fleet")
    d = Document(out)
    h1 = [p.text for p in d.paragraphs if p.style.name == "Heading 1"]
    assert any("Wave 1 (independent-batch)" in t for t in h1) and any("Wave 2 (coupled-subwave)" in t for t in h1)
    assert not any("MOP — Group 1" in t for t in h1)             # not recomputed from move_groups
    assert "distA, acc1" in _all_text(d)                          # wave 1 co-locates distA+acc1 (impossible from a move-group recompute)
