"""In-process end-to-end test: drive the real pipeline through ``main()`` (no subprocess) and assert
the three deliverables are produced and well-formed.

This complements ``test_pipeline_golden.py`` (which runs the pipeline in a SUBPROCESS to freeze the
snapshot/Excel-schema byte-for-byte). Running in-process instead buys two things the subprocess can't:

  * **Coverage** — the workbook writers (``excel.py``), the orchestration (``build.py``), and the
    HTML-embed path (``html.py``) are exercised IN THIS PROCESS, so ``pytest --cov`` actually credits
    them. Under the subprocess golden they run in a child the coverage tool never sees (which made
    ``excel.py`` read as ~18% covered when it is in fact exercised end to end).
  * **Debuggability** — a workbook-build regression surfaces here as a real Python traceback at the
    failing writer, instead of a stdout/stderr diff from a dead child process.

It deliberately asserts only STRUCTURAL properties (the files exist, the workbook opens and carries its
lead sheets, the snapshot carries its computed keys, the explorer embeds the snapshot) — never the
byte-exact golden, which stays the subprocess test's job, so the two don't duplicate each other.
"""
import json
import os
import sys

from openpyxl import Workbook, load_workbook

import synthetic_fixtures as fx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import COLLECT_PARSE_V3_23_0 as cp   # noqa: E402  (the entry module; main() is the console entry point)


def _make_template(path):
    """Minimal template workbook — the loader only needs a header row with hostname/port/status."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Interface Data"
    ws.append(["Hostname", "Port", "Status"])
    wb.save(path)


def test_pipeline_inprocess_builds_all_three_deliverables(tmp_path, monkeypatch):
    collection = fx.write_collection(str(tmp_path / "collection"))
    devices = tmp_path / "devices.json"
    devices.write_text(json.dumps(fx.DEVICES), encoding="utf-8")
    template = tmp_path / "template.xlsx"
    _make_template(str(template))
    out_xlsx = tmp_path / "out.xlsx"

    # Run from a clean working directory (main() writes its log file into cwd) with argv set as if
    # invoked from the command line. HTML is intentionally LEFT ON so write_html_explorer is exercised.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "cisco-assess",
        "--no-collect", "--collection-dir", collection,
        "--devices-file", str(devices), "--template", str(template),
        "--output", str(out_xlsx), "--workers", "1",
    ])

    cp.main()   # the actual console entry point — exercises build/excel/html/runbook in-process

    # ---- workbook ----
    assert out_xlsx.is_file(), "workbook was not written"
    wb = load_workbook(str(out_xlsx), read_only=True)
    sheets = wb.sheetnames
    wb.close()
    assert "Executive Summary" in sheets, f"Executive Summary sheet missing; got {sheets[:5]}…"
    assert len(sheets) >= 20, f"expected the full multi-sheet workbook, got only {len(sheets)} sheets"

    # ---- snapshot (the data contract) ----
    snap_path = os.path.splitext(str(out_xlsx))[0] + ".snapshot.json"
    assert os.path.isfile(snap_path), "snapshot.json was not written"
    snap = json.loads(open(snap_path, encoding="utf-8").read())
    for key in ("devices", "interfaces", "health_scores", "punchlist", "causality", "executive_brief"):
        assert key in snap, f"snapshot missing computed key {key!r}"

    # ---- explorer (snapshot embedded into the single-file viewer) ----
    explorer = os.path.splitext(str(out_xlsx))[0] + "_explorer.html"
    assert os.path.isfile(explorer), "explorer HTML was not written"
    html = open(explorer, encoding="utf-8").read()
    assert "EMBEDDED_SNAPSHOT" in html, "explorer did not get the live snapshot embedded"

    # ---- executive deck (optional python-pptx): if the lib is present, main() must have written it ----
    try:
        import pptx  # noqa: F401
    except ImportError:
        pass
    else:
        deck = os.path.splitext(str(out_xlsx))[0] + "_executive_deck.pptx"
        assert os.path.isfile(deck), "executive deck (PPTX) was not written despite python-pptx installed"
