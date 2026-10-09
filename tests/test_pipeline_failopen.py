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
import pytest

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


@pytest.mark.parametrize(("labels", "expected"), [
    ([], ()),
    (["Cable map"], ("cable_map",)),
    (["VLAN cutover matrix"], ("vlan_cutover",)),
    (["VLAN cutover matrix", "Cable map", "Cable map"], ("cable_map", "vlan_cutover")),
    (["VLAN Cutover Matrix sheet", "Cabling Schedule sheet"], ()),
    (["STP topology baseline", "QoS audit"], ()),
    (["dependency map", "unknown phase"], ()),
])
def test_carriage_input_failures_use_attributed_sources_not_derived_or_writer_labels(monkeypatch, labels, expected):
    monkeypatch.setattr(cp, "_PHASE_TIMINGS", [
        {"phase": label, "ok": False} for label in labels
    ] + [{"phase": "Cable map", "ok": True}])
    # Unknown/intermediate scope remains in the assessment's own integrity record;
    # it is not evidence that a specific raw interface/STP source actually failed.
    assert cp._vlan_carriage_input_failures() == expected


@pytest.mark.parametrize(("function", "label", "source"), [
    ("compute_vlan_carriage", "VLAN carriage", None),
    ("compute_cable_map", "Cable map", "cable_map"),
    ("compute_vlan_cutover_matrix", "VLAN cutover matrix", "vlan_cutover"),
])
def test_guarded_carriage_and_upstream_failures_remain_unavailable_in_real_pipeline(
        tmp_path, monkeypatch, function, label, source):
    from cisco_toolkit import ssot
    from cisco_toolkit.vlan_carriage import validate_vlan_carriage

    collection = fx.write_collection(str(tmp_path / "collection"))
    devices = tmp_path / "devices.json"
    devices.write_text(json.dumps(fx.DEVICES), encoding="utf-8")
    template = tmp_path / "template.xlsx"
    _make_template(str(template))
    out_xlsx = tmp_path / "out.xlsx"
    failed_calls, carriage_phases = [], []
    original_phase = cp._run_phase

    def _boom(*args, **kwargs):
        failed_calls.append((args, kwargs))
        raise RuntimeError("synthetic carriage dependency failure")

    def _observed_phase(phase, fn, *args, **kwargs):
        result = original_phase(phase, fn, *args, **kwargs)
        if phase == "VLAN carriage":
            carriage_phases.append((args, kwargs, result))
        return result

    monkeypatch.setattr(cp, function, _boom)
    monkeypatch.setattr(cp, "_run_phase", _observed_phase)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "cisco-assess", "--no-collect", "--collection-dir", collection,
        "--devices-file", str(devices), "--template", str(template),
        "--output", str(out_xlsx), "--workers", "1",
        "--no-html", "--no-docx", "--no-pptx", "--no-design", "--no-mop",
        "--no-crd", "--no-engagement", "--no-opshandbook", "--no-archreview",
    ])
    cp.main()

    snap = json.loads((tmp_path / "out.snapshot.json").read_text(encoding="utf-8"))
    assert label in snap["assessment_integrity"]["failed_phases"]
    assert ssot.abstention_reason(snap, "vlan_carriage") == ssot.ANALYSIS_UNAVAILABLE
    assert len(failed_calls) == len(carriage_phases) == 1
    args, kwargs, returned = carriage_phases[0]
    assert len(args) == 4
    assert kwargs["failed_sources"] == (() if source is None else (source,))
    assert snap["vlan_carriage"] == returned
    timings = json.loads((tmp_path / "out.phase_timings.json").read_text(encoding="utf-8"))
    current = [row for row in timings["phases"] if row["phase"] == "VLAN carriage"]
    assert len(current) == 1 and current[0]["ok"] is (source is not None)
    if source is None:
        assert returned == {}  # A recorded failed fallback is never a collected-empty result.
    else:
        assert "VLAN carriage" not in snap["assessment_integrity"]["failed_phases"]
        assert validate_vlan_carriage(returned) == (True, "ok")
        assert returned["state"] == "analysis_unavailable"
        assert returned["coverage"]["input_census_complete"] is False
        assert returned["coverage"]["capture_completeness_claim"] is False
        assert returned["rows"] == []
        assert any(issue["pointer"] == "/" + source and issue["state"] == "analysis_unavailable"
                   for issue in returned["issues"])
