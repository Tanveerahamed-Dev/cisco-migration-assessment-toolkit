"""Measure-first perf harness (Plan A / Tier-2 #11).

The guardrail this implements: NO perf work without measurements — before this,
every scaling claim was extrapolation (the one measured number, ~23 s for
compute_failure_impact on the real 303-device fleet, was taken by hand). Now:

- `_run_phase` times every phase it guards (perf_counter) into `_PHASE_TIMINGS`;
- the pipeline writes a `.phase_timings.json` SIDECAR next to the workbook —
  golden-neutral by construction (never a snapshot key, written after the manifest
  seal, chronological order preserved);
- `tests/perf_scale.py` builds a parametric N-device collection by cloning the
  proven synthetic fixtures (hostname-rewritten), and doubles as the manual sweep
  CLI: `python tests/perf_scale.py 100 300 600 1000`.

This is the hard predecessor of the compute_failure_impact restructure (#12): the
differential swap needs before/after numbers from the SAME harness."""
import json
import os
import subprocess
import sys

import synthetic_fixtures as fx
from openpyxl import Workbook

import perf_scale

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "COLLECT_PARSE_V3_23_0.py")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _template(path):
    wb = Workbook(); ws = wb.active; ws.title = "Interface Data"
    ws.append(["Hostname", "Port", "Status"]); wb.save(str(path))


def test_run_phase_records_timing_and_outcome():
    import COLLECT_PARSE_V3_23_0 as cp
    base = len(cp._PHASE_TIMINGS)
    assert cp._run_phase("probe-ok", lambda: 41 + 1) == 42
    assert cp._run_phase("probe-fail", lambda: 1 / 0, _default="dflt") == "dflt"
    new = cp._PHASE_TIMINGS[base:]
    assert [p["phase"] for p in new] == ["probe-ok", "probe-fail"]
    ok, fail = new
    assert ok["ok"] is True and fail["ok"] is False
    assert ok["seconds"] >= 0 and fail["seconds"] >= 0
    del cp._PHASE_TIMINGS[base:]                      # leave no residue for other tests


def test_pipeline_emits_the_timings_sidecar(tmp_path):
    collection = fx.write_collection(str(tmp_path / "collection"))
    devices = tmp_path / "devices.json"
    devices.write_text(json.dumps(fx.DEVICES), encoding="utf-8")
    template = tmp_path / "template.xlsx"; _template(template)
    out_xlsx = tmp_path / "out.xlsx"
    proc = subprocess.run(
        [sys.executable, SCRIPT, "--no-collect", "--collection-dir", collection,
         "--devices-file", str(devices), "--template", str(template),
         "--output", str(out_xlsx), "--no-html", "--workers", "1"],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=300,
        stdin=subprocess.DEVNULL)
    assert proc.returncode == 0, proc.stderr[-1500:]
    pt_path = os.path.splitext(str(out_xlsx))[0] + ".phase_timings.json"
    assert os.path.isfile(pt_path), "phase_timings sidecar was not written"
    pt = json.load(open(pt_path, encoding="utf-8"))
    assert pt["n_devices"] == 3
    assert pt["total_seconds"] > 0
    assert len(pt["phases"]) >= 50, f"expected the ~110 guarded phases, got {len(pt['phases'])}"
    for p in pt["phases"][:5]:
        assert set(p) == {"phase", "seconds", "ok"}
    # golden-neutral: the sidecar must never leak into the snapshot contract
    snap = json.load(open(os.path.splitext(str(out_xlsx))[0] + ".snapshot.json",
                          encoding="utf-8"))
    assert "phase_timings" not in snap


def test_scale_builder_produces_a_runnable_n_device_fleet(tmp_path):
    coll, devfile, hosts = perf_scale.build_scale_collection(str(tmp_path / "scale"), 6)
    assert len(hosts) == 6
    assert len(json.load(open(devfile, encoding="utf-8"))) == 6
    dirs = [d for d in os.listdir(coll) if os.path.isdir(os.path.join(coll, d))]
    assert len(dirs) == 6
    # the cloned captures must carry the REWRITTEN hostname (parsers key on it)
    clone = next(d for d in dirs if d not in ("core1", "core2", "access1"))
    runcfg = open(os.path.join(coll, clone, "show_running-config.txt"),
                  encoding="utf-8", errors="ignore").read()
    assert clone in runcfg, "clone's captures still carry the template hostname"
    # and the real pipeline runs on it end to end
    template = tmp_path / "t.xlsx"; _template(template)
    out_xlsx = tmp_path / "out.xlsx"
    proc = subprocess.run(
        [sys.executable, SCRIPT, "--no-collect", "--collection-dir", coll,
         "--devices-file", devfile, "--template", str(template),
         "--output", str(out_xlsx), "--no-html", "--workers", "1"],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=600,
        stdin=subprocess.DEVNULL)   # the getpass-deadlock guard (see perf_scale.py)
    assert proc.returncode == 0, proc.stderr[-1500:]
    pt = json.load(open(os.path.splitext(str(out_xlsx))[0] + ".phase_timings.json",
                        encoding="utf-8"))
    assert pt["n_devices"] == 6
