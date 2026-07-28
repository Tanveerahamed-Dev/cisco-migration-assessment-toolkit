"""A CRASHED analysis phase must not be published as a clean one (whole-repo review 2026-07-28).

`_run_phase` is fail-soft by design: a phase that raises is logged and the run continues so the
workbook still saves. The cost is that its `_default` -- `[]` or `{}` for 39 of the 41 fail-soft
sections `main()` publishes -- is BYTE-IDENTICAL on disk to "computed fine, found nothing". Only
`executive_brief` and `architecture_review` carried a `_unavailable` sentinel and an
`assessment_integrity` stamp; everything else fell back silently. A crashed `cross_layer` therefore
published no cross-layer criticals, and a crashed `punchlist` published a clean punch-list -- "not
observed" rendered as "healthy", which is the class CLAUDE.md guardrail 3 forbids.

Driven through the REAL `main()` on the synthetic fixtures, with the phase's own function forced to
raise, so the assertion is on the snapshot the engine actually wrote.
"""
import json
import os
import sys

from openpyxl import Workbook

import synthetic_fixtures as fx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import COLLECT_PARSE_V3_23_0 as cp   # noqa: E402


def _run(tmp_path, monkeypatch):
    """One real offline engine run over the synthetic collection; returns the parsed snapshot."""
    collection = fx.write_collection(str(tmp_path / "collection"))
    devices = tmp_path / "devices.json"
    devices.write_text(json.dumps(fx.DEVICES), encoding="utf-8")
    template = tmp_path / "template.xlsx"
    wb = Workbook()
    wb.active.title = "Interface Data"
    wb.active.append(["Hostname", "Port", "Status"])
    wb.save(str(template))
    out_xlsx = tmp_path / "out.xlsx"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "cisco-assess",
        "--no-collect", "--collection-dir", collection,
        "--devices-file", str(devices), "--template", str(template),
        "--output", str(out_xlsx), "--workers", "1", "--no-html",
    ])
    cp.main()
    snap = str(out_xlsx)[: -len(".xlsx")] + ".snapshot.json"
    return json.load(open(snap, encoding="utf-8"))


def test_a_crashed_phase_is_disclosed_not_published_as_an_empty_clean_result(tmp_path, monkeypatch):
    """Force two independent analysis phases to raise. Each still falls back to `[]` (unchanged --
    consumers index that shape), but the run must now DISCLOSE that they crashed, so nobody reads the
    empty result as evidence of a clean fabric."""
    def _boom(*a, **kw):
        raise RuntimeError("synthetic phase failure")

    monkeypatch.setattr(cp, "compute_cross_layer_correlations", _boom)
    monkeypatch.setattr(cp, "_punchlist", _boom)

    snap = _run(tmp_path, monkeypatch)

    # the fail-soft fallback itself is unchanged -- and is exactly why disclosure is needed:
    # on disk this is indistinguishable from a fabric with no cross-layer findings.
    assert snap.get("cross_layer") == []
    assert snap.get("punchlist") == []

    integrity = snap.get("assessment_integrity") or {}
    failed = integrity.get("failed_phases") or []
    assert "Cross-Layer correlations" in failed, (
        f"a crashed phase was published as an empty (= clean) section with no disclosure: {integrity}")
    assert "Migration Punch-List" in failed, failed
    # not vacuous: the disclosure names the phases that actually failed, not every phase
    assert len(failed) < 10, f"the failed-phase list must be the failures only, got {failed}"


def test_a_clean_run_publishes_no_integrity_flag(tmp_path, monkeypatch):
    """Negative control, and the golden-neutrality proof: with nothing failing, the key is absent
    entirely -- so this disclosure cannot alter the frozen `tests/golden/snapshot.json`. A guard that
    fires on every run is as useless as one that never fires."""
    snap = _run(tmp_path, monkeypatch)
    assert "failed_phases" not in (snap.get("assessment_integrity") or {})
    # and the sections really were computed (proving the harness runs a genuine analysis)
    assert "cross_layer" in snap and "punchlist" in snap
