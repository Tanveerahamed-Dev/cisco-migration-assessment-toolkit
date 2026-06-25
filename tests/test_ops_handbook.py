"""Tests for the Operations Handbook deliverable (NEW-V3.23.168, cisco_toolkit/ops.py) —
the PPDIOO Operate-phase document: evidence-derived baselines, evidence-gated sections,
family furniture, fail-soft behaviour."""
import json
import os

import pytest

docx = pytest.importorskip("docx")  # the deliverable needs the optional python-docx
from docx import Document  # noqa: E402

from cisco_toolkit.ops import write_ops_handbook_docx  # noqa: E402

_GOLDEN = os.path.join(os.path.dirname(__file__), "golden", "snapshot.json")


def _all_text(doc):
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            parts.extend(c.text for c in row.cells)
    return "\n".join(parts)


@pytest.fixture(scope="module")
def golden_snap():
    with open(_GOLDEN, encoding="utf-8") as f:
        return json.load(f)


def test_rich_snapshot_renders_evidence_derived_baselines(tmp_path, golden_snap):
    out = tmp_path / "ops.docx"
    write_ops_handbook_docx(str(out), golden_snap, "golden-fleet")
    doc = Document(str(out))
    text = _all_text(doc)
    heads = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
    # the section skeleton
    for h in ("1. Purpose & Audience", "2. Network Quick Reference",
              "3. Monitoring & Alerting Baseline", "4. Operational Standards & Drift Control",
              "5. Software & Lifecycle Governance", "6. Routine Operations Calendar",
              "7. Escalation & TAC Readiness"):
        assert any(h in x for x in heads), h
    # baselines really come from the golden fleet's own evidence
    assert "core1" in text                               # quick reference inventory
    assert "MAC address flapping" in text                # syslog axis detection (3.1)
    assert "Cisco PSIRT Software Checker" in text        # software governance (5)
    assert "single point in time" in text                # capacity honesty (3.2)
    assert "Right-click" in text                         # TOC field placeholder
    # furniture: document control + related docs excluding self + acceptance
    assert "Document control" in text or "Document Control" in text
    assert "Operations Handbook" in text
    assert "Architecture Review & Conformance Report" in text   # related-docs table
    assert "Acceptance" in text


def test_ops_routing_adjacency_and_fhrp_day2_section(tmp_path):
    """N36: the handbook carries a Day-2 routing-adjacency + first-hop-redundancy monitoring
    subsection — observed routing protocols get adjacency monitoring, and the FHRP coverage (or its
    absence) is a NAMED monitored item, not a silent gap."""
    snap = {
        "script_version": "V3.23.0", "devices": {"r1": {}},
        "protocol_health": [
            {"switch": "r1", "protocol": "OSPF", "severity": "Info", "summary": "1 nbr Full"},
            {"switch": "r1", "protocol": "EtherChannel", "severity": "High", "summary": "member down"}],
        "l3_forwarding": [{"switch": "r1", "vlan": "10", "svi_ip": "10.0.10.1", "fhrp": "none"},
                          {"switch": "r1", "vlan": "20", "svi_ip": "10.0.20.1", "fhrp": "none"}],
    }
    out = str(tmp_path / "ops.docx")
    write_ops_handbook_docx(out, snap, "Unit Test Fleet")
    d = Document(out)
    heads = [p.text for p in d.paragraphs if p.style.name.startswith("Heading")]
    text = _all_text(d)
    assert any("routing-adjacency" in h.lower() for h in heads), heads
    assert "OSPF" in text                                   # observed routing protocol monitored
    assert "0 of 2" in text                                 # FHRP coverage named: 0 of 2 gateways


def test_related_docs_exclude_self(tmp_path, golden_snap):
    out = tmp_path / "ops.docx"
    write_ops_handbook_docx(str(out), golden_snap, "x")
    doc = Document(str(out))
    rel = None
    for t in doc.tables:
        hdr = " ".join(c.text for c in t.rows[0].cells)
        if "Document" in hdr and "Role in the set" in hdr:
            rel = t
            break
    assert rel is not None
    names = "\n".join(c.text for row in rel.rows[1:] for c in row.cells)
    assert "Operations Handbook" not in names            # never lists itself
    assert "Executive Presentation Deck" in names        # the rest of the 12-doc family


def test_empty_snapshot_declares_absent_evidence(tmp_path):
    out = tmp_path / "ops_empty.docx"
    write_ops_handbook_docx(str(out), {}, "empty")
    doc = Document(str(out))
    text = _all_text(doc)
    # honest declarations, not invented baselines
    assert text.count("Not in this snapshot:") >= 3
    assert "re-run the collection" in text or "re-run the assessment" in text
    # the always-true content still renders
    assert "Routine Operations Calendar" in text
    assert "Daily" in text and "Quarterly" in text
    assert "P1" in text                                  # escalation skeleton


def test_malformed_sections_degrade_not_crash(tmp_path):
    snap = {
        "devices": {"sw1": None},                         # null device record
        "failure_impact": ["not-a-dict", {"host": "sw1", "stranded": "oops"}],
        "syslog_intelligence": "truthy-non-dict",
        "platform_health": {"summary": None, "per_device": "nope"},
        "golden_drift": {"summary": {"n_baseline": "x"}},
        "software_risk": [],
        "security": {"sw1": {"summary": {"fail": "many"}}},
    }
    out = tmp_path / "ops_bad.docx"
    write_ops_handbook_docx(str(out), snap, "bad")        # must not raise
    assert out.exists() and out.stat().st_size > 1000


def test_missing_docx_is_warning_not_crash(monkeypatch, tmp_path):
    import builtins
    real_import = builtins.__import__

    def boom(name, *a, **k):
        if name == "docx" or name.startswith("docx."):
            raise ImportError("no docx")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", boom)
    out = tmp_path / "never.docx"
    write_ops_handbook_docx(str(out), {}, "x")            # warns + returns
    assert not out.exists()


def test_ops_handbook_tolerates_non_dict_protocol_health_row(tmp_path):
    """[audit-2 #14] a non-dict row in snap['protocol_health'] crashed write_ops_handbook_docx (.get on a str/None)
    despite the 'never raises' contract."""
    from cisco_toolkit.ops import write_ops_handbook_docx
    out = str(tmp_path / "ops.docx")
    write_ops_handbook_docx(out, {"devices": {"sw1": None}, "protocol_health": ["STP up", None]}, "bad")  # no raise
    import os
    assert os.path.exists(out)
