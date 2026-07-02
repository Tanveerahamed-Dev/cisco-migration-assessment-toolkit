"""Parametric N-device scale fixture + manual sweep runner (Plan A / Tier-2 #11).

Builds an N-device offline collection by cloning the PROVEN synthetic fixtures
(tests/synthetic_fixtures.py — imported read-only, the golden contract is untouched):
the three template devices ship as-is, and access1's capture dir is cloned with the
hostname rewritten in every .txt body (parsers key device identity on the hostname
inside captures, not just the dir name), fanned across both cores.

As a module:   build_scale_collection(base_dir, n) -> (collection_dir, devices_file, hosts)
As a CLI:      python tests/perf_scale.py 100 300 600 1000
               runs the REAL pipeline per N (workers 1, no HTML) and prints each run's
               top-10 slowest phases from the .phase_timings.json sidecar — the
               measure-first numbers the compute_failure_impact restructure (#12) needs.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import synthetic_fixtures as fx  # noqa: E402

SCRIPT = os.path.join(ROOT, "COLLECT_PARSE_V3_23_0.py")
_TEMPLATE_HOST = "access1"           # the cloned template device
_CORES = ("core1", "core2")


def build_scale_collection(base_dir, n):
    """Write an n-device collection under base_dir -> (collection_dir, devices_file, hosts).
    n >= 3: the three fixture devices + (n-3) hostname-rewritten access clones,
    alternately homed (textually consistent: every capture body is rewritten, so
    CDP/ARP/MAC parsing sees one coherent device)."""
    if n < 3:
        raise ValueError("n must be >= 3 (the fixture ships core1/core2/access1)")
    coll = fx.write_collection(os.path.join(base_dir, "collection"))
    src = os.path.join(coll, _TEMPLATE_HOST)
    hosts = ["core1", "core2", _TEMPLATE_HOST]
    for i in range(2, n - 1):                       # access2..access<n-2>
        host = f"access{i}"
        dst = os.path.join(coll, host)
        shutil.copytree(src, dst)
        for fn in os.listdir(dst):
            if not fn.endswith(".txt"):
                continue
            p = os.path.join(dst, fn)
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                body = f.read()
            # hostname AND endpoint-MAC stem are rewritten per clone so the synthetic
            # fleet has realistic identity distribution (N devices sharing every MAC is
            # a fleet no real network has — the harness must benchmark scale, not an
            # artificial 100%-duplication corner).
            body = (body.replace(_TEMPLATE_HOST, host)
                        .replace("aabb.ccdd", f"aabb.c{(i % 4096):03x}"))
            with open(p, "w", encoding="utf-8") as f:
                f.write(body)
        hosts.append(host)
    # password is REQUIRED even though --no-collect never SSHes: load_devices runs its
    # credential chain regardless, and on a TTY a password-less entry falls into an
    # interactive getpass prompt — which DEADLOCKED this harness's first runs (the
    # pipeline child sat forever on a prompt nobody could answer; the 600 s "timeouts"
    # were that, not compute). Belt and braces: _run_one also pins stdin=DEVNULL.
    devices = [{"hostname": h, "ip": f"10.255.{i // 250}.{i % 250 + 1}",
                "username": "scale", "password": "offline-not-used", "platform": "auto"}
               for i, h in enumerate(hosts)]
    devfile = os.path.join(base_dir, "devices.json")
    with open(devfile, "w", encoding="utf-8") as f:
        json.dump(devices, f)
    return coll, devfile, hosts


def _run_one(n, keep=False):
    from openpyxl import Workbook
    base = tempfile.mkdtemp(prefix=f"perf_scale_{n}_")
    coll, devfile, hosts = build_scale_collection(base, n)
    tpl = os.path.join(base, "t.xlsx")
    wb = Workbook(); ws = wb.active; ws.title = "Interface Data"
    ws.append(["Hostname", "Port", "Status"]); wb.save(tpl)
    out = os.path.join(base, "out.xlsx")
    print(f"\n=== N={n}: running the real pipeline (workers 1, no HTML) ===")
    proc = subprocess.run(
        [sys.executable, SCRIPT, "--no-collect", "--collection-dir", coll,
         "--devices-file", devfile, "--template", tpl, "--output", out,
         "--no-html", "--no-docx", "--no-pptx", "--workers", "1"],
        cwd=base, capture_output=True, text=True,
        stdin=subprocess.DEVNULL)   # non-TTY in every context -> the loader can never prompt
    if proc.returncode != 0:
        print(proc.stderr[-2000:])
        raise SystemExit(f"pipeline failed at N={n}")
    pt = json.load(open(os.path.splitext(out)[0] + ".phase_timings.json", encoding="utf-8"))
    top = sorted(pt["phases"], key=lambda p: -p["seconds"])[:10]
    print(f"N={pt['n_devices']}  total={pt['total_seconds']}s  phases={len(pt['phases'])}")
    for p in top:
        print(f"  {p['seconds']:>9.3f}s  {p['phase']}" + ("" if p["ok"] else "  [FAILED]"))
    if not keep:
        shutil.rmtree(base, ignore_errors=True)
    return pt


if __name__ == "__main__":
    sizes = [int(a) for a in sys.argv[1:]] or [100]
    results = {n: _run_one(n) for n in sizes}
    print("\n=== scaling summary (total seconds per N) ===")
    for n, pt in results.items():
        print(f"  N={n:>5}: {pt['total_seconds']}s")
