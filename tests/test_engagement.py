"""NEW-V3.23.157: the Engagement Workflow & Plan of Record (DOCX) — the engagement-management
layer over the document set. python-docx is optional, so the module is skipped when it is absent
(the generator fails soft the same way). These tests pin the skeleton sections, the evidence-led
verdict (HOLD on blockers / PROCEED when clean), the pilot-first wave selection, the wave-schedule
reconciliation, the RAID seeding from real findings, the no-waves fallback, and the fail-soft path."""
import pytest

docx = pytest.importorskip("docx")  # skip the file if the optional dep is absent
from docx import Document  # noqa: E402

from cisco_toolkit.engagement import write_engagement_docx  # noqa: E402


def _snap():
    """A compact snapshot exercising every evidence-driven workflow section."""
    return {
        "script_version": "V3.23.0",
        "devices": {"core1": {}, "acc1": {}, "acc2": {}, "acc3": {}},
        "punchlist": [
            {"severity": "Critical", "category": "L3 design",
             "title": "VLAN 30 has a single gateway", "devices": ["core1"]},
            {"severity": "High", "category": "Physical",
             "title": "acc3 uplink is a single fiber", "devices": ["acc3"]},
        ],
        "migration_readiness": [
            {"group": "Group 1", "switches": ["acc1", "acc2"], "endpoints": 40,
             "readiness": "READY", "n_fail": 0},
            {"group": "Group 2", "switches": ["acc3"], "endpoints": 12,
             "readiness": "READY", "n_fail": 0},
            {"group": "Group 3", "switches": ["core1"], "endpoints": 90,
             "readiness": "NOT READY", "n_fail": 2},
        ],
        "wave_sequencing": [
            {"group": "Group 1", "make_before_break": ["acc1", "acc2"], "hard_cutover": [],
             "hard_cutover_endpoints": 0, "sequence": "make-before-break"},
            {"group": "Group 2", "make_before_break": [], "hard_cutover": ["acc3"],
             "hard_cutover_endpoints": 12, "sequence": "hard cutover"},
        ],
        "migration_scenarios": {
            "per_group": [{"group": "Group 1", "scenario": "parallel-run", "why": "dual-homed"},
                          {"group": "Group 2", "scenario": "phased", "why": "single-homed"}],
            "fleet_recommendation": "Parallel-run the dual-homed estate; window the rest.",
            "scenario_counts": {"parallel-run": 1, "phased": 1},
        },
        "validation_plan": {"by_wave": {"Group 1": [{}, {}, {}], "Group 2": [{}]},
                            "items": [], "summary": {}, "banner": ""},
        "collection_completeness": {
            "summary": {"inventory": 4, "complete": 3, "partial": 1, "not_collected": 0},
            "devices": [{"host": "acc3", "status": "partial", "data_quality": 60,
                         "missing": ["show cdp neighbors detail"]}],
        },
        "executive_brief": {"posture": "Fair", "posture_statement": "Fleet is migratable with care.",
                            "axes": [], "top_gating": ["1 Critical L3-design finding gates cutover"]},
        "lifecycle_risk": {"summary": {"n_devices": 4, "n_past_eos": 1}},
        "remediation_plan": {"summary": {"n_items": 5, "n_devices": 2}},
    }


def _all_text(doc):
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            parts.extend(c.text for c in row.cells)
    return "\n".join(parts)


def test_engagement_has_skeleton_sections_and_furniture(tmp_path):
    out = str(tmp_path / "e.docx")
    write_engagement_docx(out, _snap(), "Unit Test Fleet")
    d = Document(out)
    h1 = [p.text for p in d.paragraphs if p.style.name == "Heading 1"]
    for token in ("1. Engagement Verdict", "2. Engagement Phase Tracker", "3. Next Actions",
                  "4. Wave Gate Calendar", "5. RAID Log (seeded from the assessment)",
                  "6. Operating Rhythm"):
        assert any(t == token for t in h1), f"missing section: {token}; have {h1}"
    assert "Document Control" in h1 and "Document Acceptance" in h1
    text = _all_text(d)
    assert "Customer network owner" in text                     # acceptance roles
    assert "Assessment workbook (.xlsx)" in text                # related-documents cross-reference
    # self-exclusion: the doc never lists itself in its own related-documents table
    assert "Engagement Workflow & Plan of Record (.docx)" not in text


def test_engagement_verdict_holds_on_blockers_and_cites_evidence(tmp_path):
    out = str(tmp_path / "e.docx")
    write_engagement_docx(out, _snap(), "Unit Test Fleet")
    text = _all_text(Document(out))
    assert "HOLD" in text
    assert "1 Critical punch-list item(s)" in text              # condition cites the punch-list
    assert "Group 3" in text                                    # the NOT READY group is named
    assert "Fleet is migratable with care." in text             # exec-brief posture statement carried
    assert "1 Critical L3-design finding gates cutover" in text  # top_gating headline carried


def test_engagement_verdict_proceeds_on_clean_fleet(tmp_path):
    snap = _snap()
    snap["punchlist"] = []
    snap["migration_readiness"] = [r for r in snap["migration_readiness"]
                                   if r["readiness"] == "READY"]
    snap["collection_completeness"] = {"summary": {"inventory": 4, "complete": 4,
                                                   "partial": 0, "not_collected": 0}, "devices": []}
    snap["lifecycle_risk"] = {"summary": {"n_devices": 4, "n_past_eos": 0}}
    out = str(tmp_path / "e.docx")
    write_engagement_docx(out, snap, "Unit Test Fleet")
    text = _all_text(Document(out))
    assert "PROCEED" in text and "HOLD" not in text
    assert "No open issues seeded" in text                      # the empty-issues path


def test_engagement_pilot_is_smallest_ready_group(tmp_path):
    out = str(tmp_path / "e.docx")
    write_engagement_docx(out, _snap(), "Unit Test Fleet")
    text = _all_text(Document(out))
    # Group 2 (READY, 12 endpoints) beats Group 1 (READY, 40); Group 3 (NOT READY) never qualifies
    assert "Group 2 (PILOT)" in text
    assert "Group 3 (PILOT)" not in text and "Group 1 (PILOT)" not in text
    assert "smallest blast radius" in text


def test_engagement_wave_schedule_reconciles_to_evidence(tmp_path):
    out = str(tmp_path / "e.docx")
    write_engagement_docx(out, _snap(), "Unit Test Fleet")
    text = _all_text(Document(out))
    assert "parallel-run" in text and "phased" in text          # scenarios joined per wave
    assert "1 switch(es) / 12 endpoint(s)" in text              # hard-cutover exposure (Group 2)
    assert "Parallel-run the dual-homed estate; window the rest." in text   # fleet recommendation
    # T-minus gate cadence present
    for gate in ("T-28", "T-14", "T-1", "Go / No-Go", "Hypercare exit"):
        assert gate in text, gate


def test_engagement_raid_is_seeded_from_findings(tmp_path):
    out = str(tmp_path / "e.docx")
    write_engagement_docx(out, _snap(), "Unit Test Fleet")
    text = _all_text(Document(out))
    assert "RSK-001" in text and "VLAN 30 has a single gateway" in text     # risk from punch-list
    assert "past end-of-support" in text                                    # risk from lifecycle
    assert "ISS-001" in text and "show cdp neighbors detail" in text        # issue from blind spot
    assert "ASM-001" in text and "DEP-001" in text                          # assumptions + dependencies
    assert "DEC-001" in text and "PROPOSED" in text                         # decision log seeded


def test_engagement_no_waves_fallback(tmp_path):
    snap = _snap()
    snap["migration_readiness"] = []
    snap["wave_sequencing"] = []
    snap["migration_scenarios"] = {}
    snap["validation_plan"] = {}
    out = str(tmp_path / "e.docx")
    write_engagement_docx(out, snap, "Unit Test Fleet")
    d = Document(out)
    text = _all_text(d)
    assert "No migration waves are derivable" in text
    assert "(PILOT)" not in text
    h1 = [p.text for p in d.paragraphs if p.style.name == "Heading 1"]
    assert "Document Acceptance" in h1                          # furniture survives the fallback


def test_engagement_failsoft_without_python_docx(monkeypatch, tmp_path):
    import builtins, os
    real_import = builtins.__import__

    def _blocked(name, *a, **k):
        if name == "docx" or name.startswith("docx."):
            raise ImportError("simulated missing python-docx")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    out = str(tmp_path / "e.docx")
    write_engagement_docx(out, _snap(), "Unit Test Fleet")   # must not raise
    assert not os.path.exists(out)
