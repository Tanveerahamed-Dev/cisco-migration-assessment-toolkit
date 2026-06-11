"""End-to-end regression test: run the real offline pipeline and assert the
JSON snapshot (the HTML explorer's contract) and the Excel sheet-name/header
schema are unchanged.

The snapshot is the single most important stability contract in the repo, so we
freeze it as a golden file. To intentionally update the goldens after a
reviewed change:

    UPDATE_GOLDEN=1 python -m pytest tests/test_pipeline_golden.py

Determinism: we run with --workers 1 (sequential) and strip the only volatile
field (`generated_at`) before comparing.
"""
import json
import os
import subprocess
import sys

import pytest
from openpyxl import Workbook, load_workbook

import synthetic_fixtures as fx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "COLLECT_PARSE_V3_23_0.py")
GOLDEN_DIR = os.path.join(ROOT, "tests", "golden")
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"


def _make_template(path):
    """Minimal template workbook: the loader only needs a header row containing
    hostname/port/status; the script appends the rest of the columns itself."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Interface Data"
    ws.append(["Hostname", "Port", "Status"])
    wb.save(path)


def _run_pipeline(tmp_path, out_xlsx=None):
    collection = fx.write_collection(str(tmp_path / "collection"))
    devices = tmp_path / "devices.json"
    devices.write_text(json.dumps(fx.DEVICES), encoding="utf-8")
    template = tmp_path / "template.xlsx"
    _make_template(str(template))
    if out_xlsx is None:
        out_xlsx = tmp_path / "out.xlsx"

    proc = subprocess.run(
        [sys.executable, SCRIPT,
         "--no-collect", "--collection-dir", collection,
         "--devices-file", str(devices), "--template", str(template),
         "--output", str(out_xlsx), "--no-html", "--workers", "1"],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, f"pipeline failed:\nSTDOUT\n{proc.stdout}\nSTDERR\n{proc.stderr}"
    snap_path = os.path.splitext(str(out_xlsx))[0] + ".snapshot.json"
    assert os.path.isfile(snap_path), "snapshot.json was not produced"
    with open(snap_path, encoding="utf-8") as f:
        snap = json.load(f)
    snap.pop("generated_at", None)            # volatile: wall-clock timestamp
    # lifecycle_risk is date-dependent (bands/years shift relative to 'today') -> exclude from the frozen
    # golden; its logic is pinned deterministically by tests/test_lifecycle.py with a fixed asof. (V3.23.117)
    snap.pop("lifecycle_risk", None)
    # executive_brief rolls up lifecycle (its EoL headline is date-relative) -> exclude too; pinned by
    # tests/test_executive_brief.py with synthetic summaries. (V3.23.120)
    snap.pop("executive_brief", None)
    # device_dossiers embeds the EoL band per asset (eol_band / exposure labels / risk_band shift as
    # dates pass) -> exclude like its lifecycle source; pinned by tests/test_device_dossiers.py with
    # synthetic axes. Its PUNCH-LIST fold stays frozen: the CR basis text is deliberately band-agnostic
    # ("past/near end-of-support"), so band transitions never reword a folded row. (V3.23.172)
    snap.pop("device_dossiers", None)
    return snap, str(out_xlsx)


def _sheet_schema(xlsx_path):
    wb = load_workbook(xlsx_path, read_only=True)
    schema = {}
    for name in wb.sheetnames:
        ws = wb[name]
        header = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))] if ws.max_row else []
        schema[name] = header
    wb.close()
    return schema


def _golden(name, produced):
    path = os.path.join(GOLDEN_DIR, name)
    if UPDATE or not os.path.isfile(path):
        os.makedirs(GOLDEN_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            # sort_keys=False: preserve meaningful order (snapshot key order is
            # code-defined; Excel sheet order is the workbook tab order).
            json.dump(produced, f, indent=1, sort_keys=False)
        if not UPDATE:
            pytest.skip(f"generated initial golden {name}; re-run to assert")
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_snapshot_matches_golden(tmp_path):
    snap, _xlsx = _run_pipeline(tmp_path)
    golden = _golden("snapshot.json", snap)
    if golden is None:
        return
    # compare as objects (key order irrelevant); pinpoint drift by section
    assert set(snap) == set(golden), "snapshot top-level keys changed"
    for key in golden:
        assert snap[key] == golden[key], f"snapshot section '{key}' changed vs golden"


def test_excel_sheet_schema_matches_golden(tmp_path):
    _snap, xlsx = _run_pipeline(tmp_path)
    schema = _sheet_schema(xlsx)
    golden = _golden("sheet_schema.json", schema)
    if golden is None:
        return
    assert list(schema.keys()) == list(golden.keys()), "Excel sheet set/order changed"
    for sheet, header in golden.items():
        assert schema[sheet] == header, f"header row of sheet '{sheet}' changed"


def test_missing_output_directory_is_created(tmp_path):
    """FIX-V3.23.103: a non-existent --output directory must be created up-front,
    not crash openpyxl's save() AFTER all the heavy compute. Point --output at a
    nested directory that does not exist and assert every output lands there."""
    out_xlsx = tmp_path / "does" / "not" / "exist" / "out.xlsx"
    assert not out_xlsx.parent.exists()           # precondition: dir is missing
    _snap, xlsx = _run_pipeline(tmp_path, out_xlsx=out_xlsx)
    assert os.path.isfile(xlsx), "workbook was not written into the created directory"
    snap_path = os.path.splitext(xlsx)[0] + ".snapshot.json"
    assert os.path.isfile(snap_path), "snapshot was not written into the created directory"
