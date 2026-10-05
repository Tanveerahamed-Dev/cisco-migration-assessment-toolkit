"""Offline HTTP projection benchmark for the committed sample and synthetic scale fixture.

Run ``py -3.12 tests/perf_ui_projection.py --output <receipt.json>``. Timings include
the ASGI request, store custody, projection/validation, paging and serialization.
The 300-device fixture is synthetic load, not a new assessment or golden baseline.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "webapp"))

from fastapi.testclient import TestClient  # noqa: E402
from backend.app import create_app  # noqa: E402
from backend.ui_projection_api import LIST_CATALOG  # noqa: E402
from test_ui_projection_inventory import _big  # noqa: E402


def resident_bytes():
    """Optional process observation, outside the timed interval; not cache-only allocation."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ("peak", "resident", "peak_paged", "paged",
                                                    "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        current = ctypes.WinDLL("kernel32").GetCurrentProcess
        current.restype = wintypes.HANDLE
        observe = ctypes.WinDLL("psapi").GetProcessMemoryInfo
        observe.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        observe.restype = wintypes.BOOL
        return counters.resident if observe(current(), ctypes.byref(counters), counters.cb) else None
    try:
        import psutil
    except ImportError:
        return None
    return psutil.Process().memory_info().rss


def measure(snapshot, repeats, limit, all_lists):
    with tempfile.TemporaryDirectory(prefix="atlas-projection-benchmark-") as directory:
        app = create_app(db_path=str(Path(directory) / "benchmark.db"), scope_dist_dir=None)
        store = app.state.store
        campaign = store.create_campaign("Synthetic projection benchmark")
        sid = store.add_snapshot(campaign["id"], "Synthetic benchmark", snapshot, {})["id"]
        raw, binding = store.get_snapshot_blob(sid)
        host = sorted(snapshot["devices"])[len(snapshot["devices"]) // 2]
        base = f"/api/snapshots/{sid}/ui-projection"
        requests = [(view, f"{base}/{view}", {"limit": limit})
                    for view in ("overview", "trust", "inventory", "findings", "topology")]
        requests += [("device", f"{base}/device", {"host": host, "limit": limit}),
                     ("inventory_page", f"{base}/inventory/lists",
                      {"pointer": "/devices/rows", "offset": 10, "limit": limit}),
                     ("findings_page", f"{base}/findings/lists",
                      {"pointer": "/rows", "offset": 10, "limit": limit}),
                     ("device_page", f"{base}/device/lists",
                      {"host": host, "pointer": "/interfaces/rows", "offset": 10, "limit": limit})]
        if all_lists:
            for view, pointers in LIST_CATALOG.items():
                for pointer in pointers:
                    params = {"pointer": pointer, "offset": 0, "limit": limit}
                    if view == "device":
                        params["host"] = host
                    requests.append((f"{view}:{pointer}", f"{base}/{view}/lists", params))
        rows = []
        topology = None
        path_diagnostic = None
        memory_before = resident_bytes()
        with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
            for name, path, params in requests:
                samples = []
                digest = None
                for _ in range(repeats + 1):
                    start = time.perf_counter()
                    response = client.get(path, params=params)
                    elapsed = 1000 * (time.perf_counter() - start)
                    response.raise_for_status()
                    actual = hashlib.sha256(response.content).hexdigest()
                    if digest is not None and digest != actual:
                        raise AssertionError(f"Response changed between identical requests: {name}")
                    digest = actual
                    samples.append(elapsed)
                warm = samples[1:]
                rows.append({"endpoint": name, "first_ms": samples[0], "warm_ms": warm,
                             "warm_median_ms": statistics.median(warm), "warm_max_ms": max(warm),
                             "response_bytes": len(response.content), "response_sha256": digest})
                if name == "topology":
                    topology = response.json()["payload"]
                print(f"{len(snapshot['devices'])} devices {name}: first={samples[0]:.1f} ms, "
                      f"warm median={statistics.median(warm):.1f} ms, max={max(warm):.1f} ms", flush=True)
            # Query computation has a different workload and remains outside the
            # existing sample view/page gate. These are observed address choices,
            # not a claim that the route is reachable or uniquely attributable.
            addresses = [row["address"]["value"] for row in topology["source_addresses"]["page"]["items"]
                         if row["address"]["state"] == "published"]
            if len(addresses) >= 2:
                query = {"src_ip": addresses[0], "dst_ip": addresses[-1]}
                samples = []
                digest = None
                for _ in range(repeats + 1):
                    start = time.perf_counter()
                    response = client.get(f"{base}/topology/path", params=query)
                    elapsed = 1000 * (time.perf_counter() - start)
                    response.raise_for_status()
                    actual = hashlib.sha256(response.content).hexdigest()
                    if digest is not None and digest != actual:
                        raise AssertionError("Path response changed between identical requests")
                    digest = actual
                    samples.append(elapsed)
                result = response.json()["payload"]["result"]
                path_diagnostic = {"query": query, "first_ms": samples[0], "repeated_ms": samples[1:],
                                   "repeated_max_ms": max(samples[1:]), "result_state": result["state"],
                                   "route_status": result["value"]["status"] if result["value"] is not None else None,
                                   "response_bytes": len(response.content), "response_sha256": digest,
                                   "scope": "diagnostic; first and last published address on the first topology page"}
            memory_warm = resident_bytes()
        return {"devices": len(snapshot["devices"]),
                "interfaces": sum(len(value) for value in snapshot.get("interfaces", {}).values()),
                "endpoints": len(snapshot.get("endpoint_identity", [])),
                "stored_bytes": len(raw), "stored_sha256": binding["sha256"],
                "process_rss_before_requests": memory_before, "process_rss_warm": memory_warm,
                "process_rss_warm_scope": "after view/page and optional path probes; not cache-only allocation",
                "topology_lists": {key: {"rows": topology[key]["page"]["total"],
                                         "state": topology[key]["source_list"]["state"]}
                                   for key in ("nodes", "cables", "structural_links", "failure_impact", "source_addresses")},
                "path_diagnostic": path_diagnostic,
                "requests": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--sample-only", action="store_true")
    parser.add_argument("--all-lists", action="store_true")
    parser.add_argument("--limit", type=int, default=50, choices=range(1, 201))
    parser.add_argument("--require-sample-warm-ms", type=float)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    sample = json.loads((ROOT / "webapp/sample_data/sample_fleet.snapshot.json").read_bytes())
    sources = ("cisco_toolkit/ui_projection.py", "cisco_toolkit/coverage_matrix.py",
               "cisco_toolkit/protocol_assurance.py", "cisco_toolkit/fib.py",
               "webapp/backend/ui_projection_api.py", "webapp/backend/engine.py",
               "webapp/backend/storage.py", "webapp/backend/app.py", "webapp/backend/serve.py",
               "webapp/sample_data/sample_fleet.snapshot.json",
               "tests/test_ui_projection_inventory.py", "tests/perf_ui_projection.py", "pyproject.toml")
    def hashes():
        return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in sources}
    def tracked_identity():
        return (subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                hashlib.sha256(subprocess.check_output(["git", "diff", "HEAD", "--binary"], cwd=ROOT)).hexdigest())
    source_hashes = hashes()
    commit, diff_digest = tracked_identity()
    receipt = {"schema": "ui_projection_http_benchmark/1", "python": platform.python_version(),
               "platform": platform.platform(),
               "dependencies": {name: version(name) for name in ("fastapi", "starlette", "pydantic", "jsonschema")},
               "source_sha256": source_hashes,
               "source_commit": commit, "tracked_diff_sha256": diff_digest,
               "tracked_changes": subprocess.check_output(["git", "diff", "--name-only", "HEAD"], cwd=ROOT, text=True).splitlines(),
               "method": "sequential ASGI HTTP; first request then repeated identical requests",
               "limit": args.limit, "all_list_selectors": args.all_lists,
               "fleets": [measure(sample, args.repeats, args.limit, args.all_lists)]}
    if not args.sample_only:
        synthetic, _ = _big(sample)
        receipt["fleets"].append(measure(synthetic, args.repeats, args.limit, args.all_lists))
    if hashes() != source_hashes or tracked_identity() != (commit, diff_digest):
        raise RuntimeError("Benchmark source changed during measurement")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    if args.require_sample_warm_ms is not None:
        rows = receipt["fleets"][0]["requests"]
        # Only the first Overview builds the complete snapshot document. Include
        # first visits to every later view/page, not just identical-response repeats.
        worst = max([row["warm_max_ms"] for row in rows] + [row["first_ms"] for row in rows[1:]])
        if worst >= args.require_sample_warm_ms:
            raise SystemExit(f"Sample snapshot-warm maximum {worst:.1f} ms exceeds {args.require_sample_warm_ms:.1f} ms")


if __name__ == "__main__":
    main()
