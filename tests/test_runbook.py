"""NEW-V3.23.93: the Assessment & Migration Runbook (DOCX) deliverable. python-docx is optional, so
the whole module is skipped when it is not installed (the generator itself fails soft the same way)."""
import pytest

docx = pytest.importorskip("docx")  # skip the file if the optional dep is absent
from docx import Document  # noqa: E402

from cisco_toolkit.runbook import write_runbook_docx  # noqa: E402


def _snap():
    """A minimal but representative snapshot exercising every section the generator builds."""
    return {
        "script_version": "V3.23.0",
        "devices": {
            "sw1": {"hostname": "sw1", "model": "C9300", "sw_version": "17.9", "platform": "ios",
                    "ps_status": "ok", "fan_status": "ok", "temperature_status": "ok",
                    "total_ports": 48, "active_ports": 10},
            "sw2": {"hostname": "sw2", "model": "N9K-C93180", "ps_status": "fail", "fan_status": "ok",
                    "temperature_status": "ok", "total_ports": 48, "active_ports": 5},
        },
        "interfaces": {
            "sw1": {"Gi1/0/1": {"switchport_mode": "Access", "vlan": "10", "end_host_mac": "aaaa.0000.0001"},
                    "Gi1/0/2": {"switchport_mode": "Access", "vlan": "10", "end_host_mac": "aaaa.0000.0002"},
                    "Te1/1": {"switchport_mode": "Trunk", "end_host_mac": "cccc.0000.0001"}},  # trunk excluded
            "sw2": {"Gi1/0/1": {"switchport_mode": "Access", "vlan": "20", "end_host_mac": "bbbb.0000.0001"}},
        },
        "health_scores": [{"switch": "sw1", "score": 50, "band": "Poor"},
                          {"switch": "sw2", "score": 10, "band": "Critical"}],
        "move_groups": [{"switches": ["sw1"], "endpoints": 2}, {"switches": ["sw2"], "endpoints": 1}],
        "migration_readiness": [{"group": "Group 1", "switches": ["sw1"], "endpoints": 2,
                                 "readiness": "NOT READY", "n_fail": 1, "n_warn": 0, "checks": []}],
        "wave_sequencing": [{"group": "Group 1", "make_before_break": ["sw1"], "hard_cutover": [],
                             "hard_cutover_endpoints": 0, "sequence": "make-before-break"}],
        "cross_layer": [{"id": "CL-01", "severity": "Critical", "layers": "L1+L3",
                         "title": "VLAN 10: single-fiber uplink to a sole gateway",
                         "detail": "single fiber fronts the sole gateway", "recommendation": "add redundancy",
                         "hosts": ["sw1"]}],
        "punchlist": [{"severity": "Critical", "category": "Cross-layer", "devices": ["sw1"],
                       "title": "x", "detail": "y"}],
        "failure_impact": [{"host": "sw1", "severity": "High", "vlans_impacted": 3, "stranded": 5,
                            "hard": 2, "backup": 1, "fhrp": 0, "detail": "..."}],
        "link_centrality": [{"a_host": "sw1", "a_port": "Te1/1", "b_host": "sw2", "b_port": "Te1/1",
                             "betweenness": 1.0, "is_bridge": True, "pairs_cut": 4, "rank": 1}],
        "l3_forwarding": [{"switch": "sw1", "vlan": "10", "svi_ip": "10.0.10.1", "fhrp": "",
                           "role": "", "risk": "single-gateway"}],
        "capacity": [{"hostname": "sw1", "model": "C9300", "total_ports": 48, "active_ports": 10,
                      "free_ports": 38, "port_util": 20.8}],
        "operational_drift": [{"severity": "High", "category": "False-health", "devices": ["sw1"],
                               "title": "Temporary L2 bridge on sw1",
                               "detail": "a temp bridge enlarges the STP domain", "remediation": "remove it"}],
    }


def test_runbook_has_12_sections_and_reconciles(tmp_path):
    out = str(tmp_path / "rb.docx")
    write_runbook_docx(out, _snap(), "Unit Test Fleet")
    d = Document(out)
    h1 = [p.text for p in d.paragraphs if p.style.name == "Heading 1"]
    # the 12 standard sections (plus a Contents heading)
    for n in range(1, 13):
        assert any(t.startswith(f"{n}.") for t in h1), f"missing section {n}: {h1}"

    # numbers reconcile to the snapshot (the workbook-vs-runbook agreement contract)
    exec_rows = {r.cells[0].text: r.cells[1].text for r in d.tables[0].rows}
    assert exec_rows["Devices in scope"] == "2"
    assert exec_rows["Migration move groups"] == "2"
    assert exec_rows["Punch-list items"] == "1"
    assert exec_rows["Endpoints (access-port host MACs at snapshot)"] == "3"   # trunk MAC excluded


def _all_text(doc):
    """All visible text — paragraphs AND table cells (findings live in both)."""
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            parts.extend(c.text for c in row.cells)
    return "\n".join(parts)


def test_runbook_is_evidence_disciplined(tmp_path):
    out = str(tmp_path / "rb.docx")
    write_runbook_docx(out, _snap(), "Unit Test Fleet")
    text = _all_text(Document(out))
    # every material finding carries the evidence frame
    for token in ("Observed Evidence:", "Interpretation:", "Impact / Blast Radius:",
                  "Confidence:", "Unknowns:", "Next Validation:"):
        assert token in text, token
    # false-health doctrine + confidence vocabulary are present
    assert "gateway-active is not service proof" in text
    assert "Inferred-high" in text and "Unknown" in text
    # the cross-layer finding surfaced as a titled block
    assert "single-fiber uplink to a sole gateway" in text
    # the false-health / operational-drift section (§6.3) surfaced the drift finding
    assert "False-health / operational drift" in text
    assert "Temporary L2 bridge on sw1" in text


def test_runbook_failsoft_without_python_docx(monkeypatch, tmp_path):
    """If python-docx is not importable, the generator warns and returns -- it never crashes a run
    whose workbook/explorer/JSON already saved."""
    import builtins
    real_import = builtins.__import__

    def _blocked(name, *a, **k):
        if name == "docx" or name.startswith("docx."):
            raise ImportError("simulated missing python-docx")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    out = str(tmp_path / "rb.docx")
    write_runbook_docx(out, _snap(), "Unit Test Fleet")   # must not raise
    import os
    assert not os.path.exists(out)                          # nothing written, no crash
