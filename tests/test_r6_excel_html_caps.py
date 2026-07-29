"""R6 truncation sweep — every reachable, undisclosed `[:N]` display cap in excel.py / html.py /
archreview.py.

Silent truncation was found four separate times in earlier review rounds (the workbook's
subnet-reachability `served_subnets[:8]`, the Findings-Delta `[:60]` CHARACTER cut that manufactured
"DS03-DC" out of the front half of a hostname, …). This file pins the remaining reachable ones. The
house rule is stated in `excel._xls_cell_value`: where the module bounds a list it DISCLOSES the cut,
with a trailing `(+N)` marker or an "…and N further …" sentence — and the disclosure must name the
TRUE remainder, so shown + hidden reconciles to the real population.

html.py contributes no test: its ONLY upper-bounded slice is `ts[:10]` (an ISO timestamp -> date),
and its one display cap — the Findings-Delta devices column — was already fixed to the house pattern
in an earlier round (`_devices_cell`, covered by the existing suite).

Every cap pinned here was MEASURED against real producer artifacts before it was fixed
(`Migration_Assessment_*.snapshot.json` = the [HISTORY-REDACTED] fleet, `webapp/sample_data/sample_fleet.snapshot.json`,
`tests/golden/snapshot.json`); the numbers quoted in each docstring are those measurements. Caps that
no real fleet reaches (`archreview` big/mid-VLAN `[:5]`, oversubscription `[:6]`, `other_vrfs[:6]`)
are deliberately NOT pinned here — they are unreachable, not broken.

Workbook assertions read the cell back from a SAVED-then-RELOADED file, never the in-memory object.
"""
import re

import pytest

from cisco_toolkit.archreview import _clip, _ev, compute_architecture_review

openpyxl = pytest.importorskip("openpyxl")
from openpyxl import Workbook, load_workbook  # noqa: E402

from cisco_toolkit.excel import write_executive_summary_sheet  # noqa: E402


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _saved_sheet(wb, tmp_path, name="Executive Summary"):
    """Save the workbook and read the sheet back from DISK — the only view that proves what the
    customer opens (some truncation is visible only after the save/reload round trip)."""
    out = tmp_path / "wb.xlsx"
    wb.save(str(out))
    return load_workbook(str(out))[name]


def _cells(ws):
    return [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]


def _value_right_of(ws, key):
    """The cell to the right of a label cell (the sheet's `_kv` layout)."""
    for row in ws.iter_rows():
        for c in row:
            if str(c.value).strip() == key:
                return str(ws.cell(c.row, c.column + 1).value)
    raise AssertionError(f"label {key!r} not found in sheet")


#: the migration-brief block (and with it the "Address first" row) renders only when the brief
#: carries axes — one axis is enough to reach the row under test.
_AXES = [{"axis": "Fleet posture", "severity": "Critical", "headline": "h"}]


def _hidden_count(text):
    """The N a disclosure marker claims — `(+N)`, `(+N more …)` or `… +N more`."""
    m = re.search(r"\(\+(\d+)", text) or re.search(r"\+(\d+) more", text)
    assert m, f"no disclosure marker in {text!r}"
    return int(m.group(1))


# --------------------------------------------------------------------------- #
# excel.py — Executive Summary (the one-page landing tab)
# --------------------------------------------------------------------------- #
def test_address_first_discloses_the_gating_items_it_drops(tmp_path):
    """`" · ".join(tg[:6])` cut the executive brief's GATING list with no marker. Measured on the [HISTORY-REDACTED]
    fleet: 9 top-gating headlines, 6 rendered — a reader planning around the six shown is three
    blockers short, and nothing else on the sheet carries them (the axis table below is one row per
    AXIS, not per gating item)."""
    tg = [f"gating-item-{i}" for i in range(9)]
    wb = Workbook()
    write_executive_summary_sheet(wb, [], [], [], [], brief={"axes": _AXES, "top_gating": tg})
    ws = _saved_sheet(wb, tmp_path)
    cell = _value_right_of(ws, "Address first")
    assert "gating-item-0" in cell and "gating-item-5" in cell        # the six shown
    assert "gating-item-6" not in cell                                # still capped at six
    shown = cell.split(" (+")[0].count("·") + 1
    assert shown + _hidden_count(cell) == len(tg), cell               # shown + hidden == the truth


def test_address_first_stays_unmarked_when_nothing_is_dropped(tmp_path):
    """The marker must be conditional — a cry-wolf "(+0)" on every workbook trains the reader to
    ignore it."""
    wb = Workbook()
    write_executive_summary_sheet(wb, [], [], [], [],
                                  brief={"axes": _AXES, "top_gating": ["a", "b", "c"]})
    assert "(+" not in _value_right_of(_saved_sheet(wb, tmp_path), "Address first")


def test_top_categories_discloses_the_categories_it_drops(tmp_path):
    """`sorted(...)[:5]` under the label "Top categories" named the ranking but not the population,
    so five entries read as the punch-list's whole category set. Measured: 17 categories on the [HISTORY-REDACTED]
    fleet (the 12 hidden ones carry 176 of the 1,805 items), 15 on the sample fleet, 14 on the
    golden fixture — this cap is hit by EVERY artifact in the repo."""
    punchlist = [{"severity": "High", "category": f"cat{i}"} for i in range(17)]
    wb = Workbook()
    write_executive_summary_sheet(wb, [], punchlist, [], [])
    cell = _value_right_of(_saved_sheet(wb, tmp_path), "Top categories")
    assert cell.count("(1)") == 5                                     # still five entries shown
    assert 5 + _hidden_count(cell) == 17, cell                        # …of seventeen, disclosed


def test_top_categories_unmarked_when_all_categories_fit(tmp_path):
    wb = Workbook()
    write_executive_summary_sheet(wb, [], [{"severity": "High", "category": "only"}], [], [])
    assert "(+" not in _value_right_of(_saved_sheet(wb, tmp_path), "Top categories")


def test_keystone_table_header_names_the_population_it_ranks(tmp_path):
    """`fi[:10]` renders ten rows under "Keystone devices — fix-first"; on the [HISTORY-REDACTED] fleet 193 of the
    303 simulated devices strand at least one endpoint. Ten rows with no ratio size the TABLE, not
    the problem. Rows carrying no `stranded` figure are unmeasured and must not be counted as
    keystones (coverage honesty: absent evidence is never a zero)."""
    fi = ([{"host": f"h{i}", "severity": "Critical", "stranded": 100 - i, "vlans_impacted": 3}
           for i in range(25)]
          + [{"host": f"u{i}", "severity": "Info", "stranded": None} for i in range(5)]
          + [{"host": f"z{i}", "severity": "Info", "stranded": 0} for i in range(5)])
    wb = Workbook()
    write_executive_summary_sheet(wb, [], [], [], fi)
    text = "\n".join(_cells(_saved_sheet(wb, tmp_path)))
    assert "Keystone devices" in text                                  # label preserved
    assert "top 10 of 25 device(s) that strand" in text, text[:400]     # 25 = stranded>0 only
    assert "h10" not in text                                           # table itself still 10 rows


def test_keystone_header_unmarked_when_every_keystone_is_shown(tmp_path):
    fi = [{"host": f"h{i}", "severity": "High", "stranded": 5} for i in range(4)]
    wb = Workbook()
    write_executive_summary_sheet(wb, [], [], [], fi)
    text = "\n".join(_cells(_saved_sheet(wb, tmp_path)))
    assert "Keystone devices" in text and "top 10 of" not in text


# --------------------------------------------------------------------------- #
# archreview.py — the evidence cap, whose "+N more" was itself wrong
# --------------------------------------------------------------------------- #
def _l3_snap(n=25):
    """A fleet whose HIER-1 evidence (the L3 tier) is larger than the 20-host evidence cap."""
    hosts = [f"core{i:02d}" for i in range(n)]
    return {"devices": {h: {"hostname": h} for h in hosts},
            "l3_forwarding": [{"switch": h, "vlan": 10} for h in hosts]}


def test_evidence_total_is_published_when_the_evidence_list_is_cut():
    """`add()` stores `sorted(evidence)[:20]`. Every renderer then appends "+N more" computed off
    that STORED list, so the disclosure understated the scope by everything the first cut dropped.
    Measured on the [HISTORY-REDACTED] fleet: 8 of 25 checks exceed the cap (L2-3 230 hosts — which rendered as
    "+15 more" — LC-1 152, HIER-1 116, SEC-1 74, HIER-2 67, L2-1 42, RES-1 21, L2-5 21)."""
    res = compute_architecture_review(_l3_snap(25))
    hier1 = next(c for c in res["checks"] if c["id"] == "HIER-1")
    assert len(hier1["evidence"]) == 20                    # the cap itself is unchanged
    assert hier1["evidence_total"] == 25                   # …and the true population is published


def test_evidence_total_absent_when_nothing_was_dropped():
    """Conditional, so a snapshot that fits the cap is byte-identical to before (this is also what
    keeps tests/golden/snapshot.json unchanged — its largest evidence list is 3 hosts)."""
    res = compute_architecture_review(_l3_snap(4))
    hier1 = next(c for c in res["checks"] if c["id"] == "HIER-1")
    assert "evidence_total" not in hier1


def test_ev_marker_reconciles_to_the_true_total_not_the_sample():
    """The renderer contract: shown + hidden == the real population."""
    sample, total = [f"h{i:02d}" for i in range(20)], 116
    rendered = _ev(sample, 5, total)
    assert rendered.count(",") == 4                                    # five hosts shown
    assert _hidden_count(rendered) == total - 5, rendered
    # …and with no `total` it still behaves exactly as before (no total known == no inflation)
    assert _hidden_count(_ev(sample, 5)) == 15
    # a `total` smaller than what we hold is never trusted downward
    assert _hidden_count(_ev(sample, 5, 3)) == 15


def test_scorecard_evidence_column_reconciles_in_the_saved_docx(tmp_path):
    """Read back from the SAVED .docx: §3's Evidence column must claim the true remainder."""
    pytest.importorskip("docx")
    from docx import Document

    from cisco_toolkit.archreview import write_archreview_docx
    out = str(tmp_path / "ar.docx")
    write_archreview_docx(out, _l3_snap(25), "R6 Fleet")
    d = Document(out)
    cells = [c.text for t in d.tables for row in t.rows for c in row.cells]
    ev_cells = [c for c in cells if "core00" in c and "more" in c]
    assert ev_cells, cells[:40]
    for cell in ev_cells:
        assert _hidden_count(cell) == 25 - 5, cell     # +20, NOT the pre-fix +15


# --------------------------------------------------------------------------- #
# archreview.py — narrative list caps that named no total
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# archreview.py — three narrative caps MEASURED as hit but whose fix is WITHHELD
#
# RES-4 / L2-1 / CAP-2 state their scope in `observed`, a string that lands in the published
# `architecture_review` snapshot section — and `tests/test_sample_fleet.py` locks that section
# against the committed demo snapshot, so disclosing the remainder is a legitimate change to
# webapp/sample_data/sample_fleet.snapshot.json (regenerate: webapp/sample_data/build_sample.py).
# The three tests below were left CHARACTERISING the undisclosed behaviour, because the pass that
# found them could not regenerate the demo snapshot. The fixes have since LANDED (the orchestrator
# owns the pin), so each now asserts the disclosure and reconciles shown + hidden against the true
# population — the form the docstrings specified.
# --------------------------------------------------------------------------- #
def test_res4_keystone_sentence_discloses_the_keystones_it_did_not_name():
    """RES-4 named 5 keystones and stopped, so the availability check read as "the fleet has five
    keystones". Measured: 193 devices strand endpoints on the [HISTORY-REDACTED] fleet, 19 on the sample — a
    migration that hardens the five leaves the rest unhardened and sequences waves off the wrong
    blast-radius population.

    The band is read off the DESCENDING tail (``keystones[5:]``), never "at least the 5th value",
    which would overstate every hidden row."""
    fi = [{"host": f"h{i:03d}", "stranded": 500 - i} for i in range(30)]
    res = compute_architecture_review({"failure_impact": fi})
    obs = next(c for c in res["checks"] if c["id"] == "RES-4")["observed"]
    assert obs.count("strands") == 5                                   # 5 still named by name …
    assert len([r for r in fi if r["stranded"] > 0]) == 30             # … of 30 that qualify
    assert "and 25 further device(s) strand 471-495 endpoint(s) each" in obs, obs
    # the band must bound the TAIL, not the named five: 500 (the top) must never appear in it
    assert "500 endpoint(s) each" not in obs


def test_res4_keystone_sentence_is_silent_when_every_keystone_is_named():
    """Refute the fix: at or below the cap there is no tail, so the sentence must be unchanged."""
    fi = [{"host": f"h{i}", "stranded": 9 - i} for i in range(4)]
    obs = next(c for c in compute_architecture_review({"failure_impact": fi})["checks"]
               if c["id"] == "RES-4")["observed"]
    assert "further device" not in obs, obs


def test_l2_1_stp_root_sentence_discloses_the_switches_it_did_not_name():
    """L2-1 names 6 root-holding access switches; measured 42 on the [HISTORY-REDACTED] fleet, 17 on the sample
    fleet. The sentence is the check's whole statement of SCOPE — how many closets the target design
    must re-pin, so a display cap was sizing an LLD task list."""
    hosts = [f"acc{i:02d}" for i in range(14)]
    snap = {"devices": {h: {"hostname": h} for h in hosts},
            "stp_roots": {h: {"10": {"is_root": True}} for h in hosts}}
    obs = next(c for c in compute_architecture_review(snap)["checks"]
               if c["id"] == "L2-1")["observed"]
    assert obs.count(" roots ") == 6                                   # 6 named of 14 rooted
    # 8 hidden, each rooting 1 VLAN -> shown + hidden reconciles to the real population
    assert "and 8 further access switch(es) rooting 8 VLAN(s) between them" in obs, obs


def test_cap2_tight_closet_sentence_discloses_the_closets_it_did_not_name():
    """CAP-2 names 6 closets past the 90% line; measured 16 on the sample fleet. The BoM sizes
    replacement hardware off this list, so the count past the 90% line must not be the display
    cap — ten full closets would get no spare-port allowance."""
    cap = ([{"hostname": f"acc{i:02d}", "port_util": 99.0 - i * 0.5} for i in range(11)]
           + [{"hostname": "ok01", "port_util": 40.0}])            # all 11 are past the 90% line
    obs = next(c for c in compute_architecture_review({"capacity": cap})["checks"]
               if c["id"] == "CAP-2")["observed"]
    assert obs.count("port utilisation") == 6                          # 6 named of 11 tight
    assert "and 5 further closet(s) above the 90% line" in obs, obs


def test_summary_statement_discloses_further_affected_domains():
    """"concentrated in: A, B, C, D" over 7 affected domains ([HISTORY-REDACTED] fleet) inverts the finding: the
    deviations are fleet-wide, not concentrated."""
    hosts = [f"acc{i:02d}" for i in range(6)]
    snap = {
        "devices": {h: {"hostname": h, "num_power_supplies": 1} for h in hosts},
        "l3_forwarding": [{"switch": hosts[0], "vlan": 10}],                    # D2 (single-PSU L3)
        "stp_roots": {h: {"10": {"is_root": True}} for h in hosts[1:]},         # D3
        "operational_drift": [{"severity": "Critical", "title": "drift"}],      # D6
        "security": {h: {"summary": {"grade": "weak"}} for h in hosts},         # D7
        "lifecycle_risk": {"summary": {"n_past_eos": 2},
                           "per_device": [{"host": hosts[0], "band": "Past-EoS"}]},   # D8
    }
    res = compute_architecture_review(snap)
    worst = [d["key"] for d in res["domains"] if d["verdict"] in ("critical", "deviation")]
    assert len(worst) > 4, worst                                       # the fixture must reach it
    st = res["summary"]["statement"]
    m = re.search(r"concentrated in: (.+?) and (\d+) further domain\(s\)", st)
    assert m, st
    assert m.group(1).count(",") + 1 + int(m.group(2)) == len(worst), st


# --------------------------------------------------------------------------- #
# archreview.py — the CHARACTER slices (the class that manufactures a name)
# --------------------------------------------------------------------------- #
def test_clip_never_manufactures_a_token():
    """A raw `str(...)[:60]` ends mid-word and reads as complete text — the same defect as the
    Findings-Delta devices column, where "DS03-DC" was the front half of a hostname. `_clip` cuts on
    a word boundary and marks it."""
    s = "Temporary L2 bridge on DS03-BC-CA05R52-AJDOH pending closet consolidation"
    out = _clip(s, 60)
    assert out.endswith("…") and len(out) <= 61
    assert s.startswith(out[:-1].rstrip(" ,;:-"))                      # a true prefix, nothing new
    assert not out[:-1].rstrip().endswith("DS03-BC-CA05R52-AJDO")      # no half identifier
    assert _clip(s, 500) == s and "…" not in _clip(s, 500)             # short values untouched
    assert _clip(None, 10) == "" and _clip(12345, 3) == "123…"         # non-str inputs are safe


def test_ops1_drift_titles_are_clipped_visibly():
    """Measured on the [HISTORY-REDACTED] fleet: 1 of the 3 rendered High/Critical drift titles is 69 chars and was
    cut mid-word at 60."""
    long_title = "PoE fault on AS01-BC-STDOPS-CAR3R13-BCDOH powered endpoint dropped twice"
    snap = {"operational_drift": [{"severity": "High", "title": long_title}]}
    obs = next(c for c in compute_architecture_review(snap)["checks"]
               if c["id"] == "OPS-1")["observed"]
    assert "…" in obs, obs                                             # the cut is visible
    assert long_title[:40] in obs                                      # and it is still the title
    assert "endpoint dropped twice" not in obs


def test_priority_queue_discloses_that_it_is_only_the_top_ten(tmp_path):
    """`actions[:10]` feeds a table headed "Priority remediation queue" — which reads as the whole
    remediation scope. Measured: 19 actionable checks on the [HISTORY-REDACTED] fleet, 14 on the sample fleet, 13 on
    the golden fixture — this cap is hit by every artifact in the repo. Disclosed in §1.1's prose so
    the published snapshot section is untouched."""
    pytest.importorskip("docx")
    from docx import Document

    from cisco_toolkit.archreview import write_archreview_docx
    checks = [{"id": f"C-{i}", "domain": "Layer-2 design", "title": f"t{i}",
               "verdict": "deviation", "observed": "o", "implication": "i",
               "recommendation": f"fix {i}", "reference": "ref", "evidence": []}
              for i in range(13)]
    snap = {"architecture_review": {
        "domains": [{"key": "Layer-2 design", "verdict": "deviation", "score_pct": 35,
                     "checks": [c["id"] for c in checks]}],
        "checks": checks,
        "top_actions": [{"rank": i + 1, "id": c["id"], "domain": c["domain"],
                         "verdict": c["verdict"], "action": c["recommendation"],
                         "evidence": []} for i, c in enumerate(checks[:10])],
        "summary": {"n_checks": 13, "statement": "s", "grade": "D", "score_pct": 35}}}
    out = str(tmp_path / "queue.docx")
    write_archreview_docx(out, snap, "R6 Fleet")
    text = "\n".join(p.text for p in Document(out).paragraphs)
    assert "Showing the top 10 of 13 check(s) requiring remediation" in text, text[:600]
    assert "remaining 3" in text


def test_priority_queue_unmarked_when_the_whole_queue_fits(tmp_path):
    pytest.importorskip("docx")
    from docx import Document

    from cisco_toolkit.archreview import write_archreview_docx
    checks = [{"id": f"C-{i}", "domain": "Layer-2 design", "title": f"t{i}",
               "verdict": "deviation", "observed": "o", "implication": "i",
               "recommendation": f"fix {i}", "reference": "ref", "evidence": []}
              for i in range(3)]
    snap = {"architecture_review": {
        "domains": [{"key": "Layer-2 design", "verdict": "deviation", "score_pct": 35,
                     "checks": [c["id"] for c in checks]}],
        "checks": checks,
        "top_actions": [{"rank": i + 1, "id": c["id"], "domain": c["domain"],
                         "verdict": c["verdict"], "action": c["recommendation"],
                         "evidence": []} for i, c in enumerate(checks)],
        "summary": {"n_checks": 3, "statement": "s", "grade": "D", "score_pct": 35}}}
    out = str(tmp_path / "queue2.docx")
    write_archreview_docx(out, snap, "R6 Fleet")
    assert "Showing the top" not in "\n".join(p.text for p in Document(out).paragraphs)
