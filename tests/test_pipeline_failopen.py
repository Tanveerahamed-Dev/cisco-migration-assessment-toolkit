"""Executive-brief synthesis must FAIL LOUD, not silently (wave R2-4-01).

When compute_executive_brief raises, the pipeline's _run_phase swallows it and returns the phase
default. Historically that default was {} -> the snapshot's canonical scale/posture/axes block silently
vanished and downstream surfaces (deck) rendered the missing numbers as healthy zeros/blanks. That is the
assembly-level analogue of the device-level false-health class. The pipeline must instead stamp a
machine-readable integrity flag so every consumer can disclose "cross-axis synthesis unavailable".
"""
import json
import os
import sys

from openpyxl import Workbook

import synthetic_fixtures as fx  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import COLLECT_PARSE_V3_23_0 as cp  # noqa: E402


def _make_template(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Interface Data"
    ws.append(["Hostname", "Port", "Status"])
    wb.save(path)


def test_executive_brief_failure_is_disclosed_not_silent(tmp_path, monkeypatch):
    collection = fx.write_collection(str(tmp_path / "collection"))
    devices = tmp_path / "devices.json"
    devices.write_text(json.dumps(fx.DEVICES), encoding="utf-8")
    template = tmp_path / "template.xlsx"
    _make_template(str(template))
    out_xlsx = tmp_path / "out.xlsx"

    def _boom(*a, **k):
        raise RuntimeError("synthetic executive-brief failure")
    monkeypatch.setattr(cp, "compute_executive_brief", _boom)   # module-level symbol the pipeline calls

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "cisco-assess", "--no-collect", "--collection-dir", collection,
        "--devices-file", str(devices), "--template", str(template),
        "--output", str(out_xlsx), "--no-html", "--workers", "1",
    ])
    cp.main()

    snap_path = os.path.splitext(str(out_xlsx))[0] + ".snapshot.json"
    snap = json.loads(open(snap_path, encoding="utf-8").read())
    # the failure is DISCLOSED as a machine-readable flag, not a silent empty brief
    assert snap.get("assessment_integrity", {}).get("executive_brief") == "compute_failed", \
        "a crashed brief must stamp assessment_integrity.executive_brief, not silently vanish"
    # and the brief carries the failure sentinel, distinguishable from a legitimately-empty {} result
    assert snap.get("executive_brief", {}).get("_unavailable") is True


def test_healthy_run_has_no_integrity_flag(tmp_path, monkeypatch):
    """Inverse guard: a normal run (brief succeeds) must NOT stamp the integrity flag -- the disclosure
    is reserved for genuine synthesis failure, never a false alarm on a healthy assessment."""
    collection = fx.write_collection(str(tmp_path / "collection"))
    devices = tmp_path / "devices.json"
    devices.write_text(json.dumps(fx.DEVICES), encoding="utf-8")
    template = tmp_path / "template.xlsx"
    _make_template(str(template))
    out_xlsx = tmp_path / "out.xlsx"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "cisco-assess", "--no-collect", "--collection-dir", collection,
        "--devices-file", str(devices), "--template", str(template),
        "--output", str(out_xlsx), "--no-html", "--workers", "1",
    ])
    cp.main()

    snap = json.loads(open(os.path.splitext(str(out_xlsx))[0] + ".snapshot.json", encoding="utf-8").read())
    assert "assessment_integrity" not in snap, "a healthy run must not raise a false integrity alarm"
    assert snap.get("executive_brief", {}).get("_unavailable") is not True
