"""Hosted-only, budget-enforced real pipeline qualification on synthetic captures.

Each stage is a fresh process group. RSS is the 50 ms sampled sum of live group
residents, with wait4's exact leader high-water mark as a floor. This includes
AssessHub's engine child; it is neither a Python allocation count nor cache size.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
MIB = 1024 * 1024
# Fixed engineering ceilings, selected before the first measurement. Not tunable
# workflow inputs, and not an owner workload-approval or real-fleet acceptance.
BUDGETS = {
    "fixture": {"wall_seconds": 60, "peak_rss_bytes": 512 * MIB, "artifact_bytes": 128 * MIB},
    "engine": {"wall_seconds": 600, "peak_rss_bytes": 3072 * MIB, "artifact_bytes": 256 * MIB},
    "ingest": {"wall_seconds": 660, "peak_rss_bytes": 4096 * MIB, "artifact_bytes": 128 * MIB},
    "projection": {"wall_seconds": 180, "peak_rss_bytes": 2048 * MIB, "artifact_bytes": 64 * MIB},
    "scope": {"wall_seconds": 60, "peak_rss_bytes": 2048 * MIB, "artifact_bytes": 128 * MIB},
}


def hosted_only():
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise RuntimeError("Scale qualification runs only on GitHub-hosted runners")
    if sys.platform != "linux":
        raise RuntimeError("The RSS measurement contract requires the pinned Linux runner")


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def fleet_check(snapshot, fleet):
    if snapshot.get("assessment_integrity", {}).get("failed_phases"):
        raise AssertionError("Engine assessment carries failed analysis phases")
    expected = {d["host"] for d in fleet["devices"]}
    if set(snapshot.get("devices", {})) != expected:
        raise AssertionError("Engine device roster does not equal the synthetic input roster")
    actual = snapshot.get("cable_map", {}).get("cables", [])
    def key(link):
        return tuple(sorted(((link["a"], link["a_port"]), (link["b"], link["b_port"]))))
    # Engine normalizes port spellings; compare its common abbreviation without
    # collapsing distinct ports or dropping endpoint-only cable observations.
    from cisco_toolkit.textutils import normalize_ifname
    def normalized(link):
        return key({**link, "a_port": normalize_ifname(link["a_port"]), "b_port": normalize_ifname(link["b_port"])})
    if len(actual) != len(fleet["links"]) or {normalized(c) for c in actual} != {normalized(c) for c in fleet["links"]}:
        raise AssertionError(f"Engine cable census differs: {len(actual)} observed / {len(fleet['links'])} expected")
    # Read the engine-owned VLAN census, rather than accepting input size alone.
    from cisco_toolkit.analyze import vlan_inventory
    seen = {v for v, _name in vlan_inventory(snapshot)}
    if not set(fleet["vlan_ids"]) <= seen:
        raise AssertionError(f"Engine VLAN census lost input VLANs ({len(seen)} observed)")
    return {"managed_devices": len(expected), "physical_cables": len(actual), "vlan_count": len(seen)}


def stage(stage_name, work):
    import webapp.sample_data.build_scale as build_scale
    out = work / stage_name
    if stage_name == "fixture":
        fleet = build_scale.build(out)
        # ZIP headers are fixed too: neither the clock nor host file timestamps
        # enter the archive identity consumed by the real ingest route.
        with zipfile.ZipFile(out / "collection.zip", "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            files = sorted((out / f"collection_{build_scale.STAMP}").rglob("*.txt")) + [out / "devices.json"]
            for path in files:
                info = zipfile.ZipInfo(path.relative_to(out).as_posix(), date_time=(2026, 8, 7, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes())
        write_json(out / "result.json", {"captures_sha256": fleet["captures_sha256"],
                   "zip_sha256": hashlib.sha256((out / "collection.zip").read_bytes()).hexdigest(),
                   "roles": fleet["roles"], "managed_devices": fleet["managed_devices"],
                   "vlan_count": len(fleet["vlan_ids"]), "physical_cables": fleet["physical_cables"],
                   "capture_bytes": sum(d["capture_bytes"] for d in fleet["devices"]),
                   "min_device_capture_bytes": min(d["capture_bytes"] for d in fleet["devices"]),
                   "max_device_capture_bytes": max(d["capture_bytes"] for d in fleet["devices"])})
        return
    fleet = json.loads((work / "fixture/fleet.json").read_text())
    if stage_name == "scope":
        subprocess.run(["node", str(ROOT / "atlas-scope/tools/compile-all.mjs"), "--source",
                        str(work / "ingest/stored.snapshot.json"), "--out", str(out),
                        "--label", "Synthetic 300-device scale qualification"], check=True)
        fabric = json.loads((out / "fabric.json").read_text())
        expected_hosts = {d["host"] for d in fleet["devices"]}
        collected = [d["host"] for d in fabric["devices"] if d["collected"] and d["inventoried"]]
        nodes = expected_hosts | {link[side] for link in fleet["links"] for side in ("a", "b")}
        if len(collected) != len(expected_hosts) or set(collected) != expected_hosts or len(fabric["devices"]) != len(nodes) or {d["host"] for d in fabric["devices"]} != nodes:
            raise AssertionError("Scope compiled fabric lost the qualified fleet/cable census")
        from cisco_toolkit.textutils import normalize_ifname
        def edge(a, ap, b, bp):
            return tuple(sorted(((a, normalize_ifname(ap)), (b, normalize_ifname(bp)))))
        actual = {edge(c["a"], c["aPort"], c["b"], c["bPort"]) for c in fabric["links"]}
        expected = {edge(c["a"], c["a_port"], c["b"], c["b_port"]) for c in fleet["links"]}
        if len(fabric["links"]) != len(expected) or actual != expected:
            raise AssertionError("Scope compiled links lost qualified endpoint/port identity")
        write_json(out / "result.json", {"fabric_devices": len(fabric["devices"]), "fabric_links": len(fabric["links"])})
        return
    if stage_name == "engine":
        command = ["cisco-assess", "--no-collect", "--collection-dir", str(work / f"fixture/collection_{build_scale.STAMP}"),
                   "--devices-file", str(work / "fixture/devices.json"), "--template", str(work / "fixture/template.xlsx"),
                   "--output", str(out / "scale.xlsx"), "--workers", "1", "--no-html", "--no-docx", "--no-pptx",
                   "--no-design", "--no-mop", "--no-crd", "--no-engagement", "--no-archreview", "--no-opshandbook"]
        subprocess.run(command, cwd=out, stdin=subprocess.DEVNULL, check=True)
        snapshot = json.loads((out / "scale.snapshot.json").read_text())
        counts = fleet_check(snapshot, fleet)
        timings = json.loads((out / "scale.phase_timings.json").read_text())
        failures = [p["phase"] for p in timings["phases"] if not p["ok"]]
        if failures:
            raise AssertionError(f"Engine phases failed: {failures}")
        write_json(out / "result.json", {**counts, "slowest_phases": sorted(timings["phases"], key=lambda p: -p["seconds"])[:10]})
        return
    from fastapi.testclient import TestClient
    from webapp.backend.app import create_app
    database = work / "ingest/scale.db"
    app = create_app(db_path=str(database), scope_dist_dir=None)
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        if stage_name == "ingest":
            response = client.post("/api/campaigns", json={"name": "Synthetic scale qualification"})
            response.raise_for_status()
            cid = response.json()["id"]
            with (work / "fixture/collection.zip").open("rb") as archive:
                response = client.post(f"/api/campaigns/{cid}/ingest",
                                       files={"file": ("collection.zip", archive, "application/zip")})
            response.raise_for_status()
            meta = response.json()
            sid = meta["id"]
            raw = client.get(f"/api/snapshots/{sid}/raw")
            raw.raise_for_status()
            if raw.headers["x-snapshot-sha256"] != hashlib.sha256(raw.content).hexdigest():
                raise AssertionError("Stored snapshot byte custody differs")
            counts = fleet_check(raw.json(), fleet)
            (out / "stored.snapshot.json").write_bytes(raw.content)
            write_json(out / "result.json", {**counts, "snapshot_id": sid, "stored_sha256": hashlib.sha256(raw.content).hexdigest(),
                                           "stored_bytes": len(raw.content), "ingest": meta["ingest"]})
            return
        sid = json.loads((work / "ingest/result.json").read_text())["snapshot_id"]
        base = f"/api/snapshots/{sid}/ui-projection"
        rows = []
        def request(name, path, params):
            start = time.monotonic()
            response = client.get(path, params=params)
            duration = time.monotonic() - start
            response.raise_for_status()
            body = response.json()
            expected = json.loads((work / "ingest/result.json").read_text())
            if body["identity"]["sha256"] != "sha256:" + expected["stored_sha256"]:
                raise AssertionError("Projection does not bind the exact ingested snapshot")
            (out / f"{name}.json").write_bytes(response.content)
            rows.append({"request": name, "wall_seconds": duration, "response_bytes": len(response.content)})
            return body
        # Every view, every paged-list kind, both the first and last pages. Device
        # views cover each managed role and a final access host beyond page one.
        from webapp.backend.ui_projection_api import LIST_CATALOG, MAX_PAGE_SIZE
        cases = [(v, None) for v in ("overview", "trust", "inventory", "findings", "topology")]
        cases += [("device", next(d["host"] for d in fleet["devices"] if d["role"] == role)) for role in fleet["roles"]]
        cases.append(("device", "access240"))
        for view, host in cases:
            params = {"limit": MAX_PAGE_SIZE}
            if host:
                params["host"] = host
            name = f"{view}-{host or 'fleet'}"
            body = request(name, f"{base}/{view}", params)
            for n, pointer in enumerate(LIST_CATALOG[view]):
                value = body["payload"]
                for part in pointer[1:].split("/"):
                    value = value[part.replace("~1", "/").replace("~0", "~")]
                total = value["page"]["total"]
                for offset in sorted({0, max(0, total - MAX_PAGE_SIZE)}):
                    page = request(f"{name}-list{n}-{offset}", f"{base}/{view}/lists",
                                   {**params, "pointer": pointer, "offset": offset})["list"]["page"]
                    if page["total"] != total or page["returned"] != min(MAX_PAGE_SIZE, total - offset):
                        raise AssertionError("Projection paging lost its source-list census")
        write_json(out / "result.json", {"requests": rows, "views": sorted({v for v, _ in cases})})


def tree_bytes(root):
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


def group_rss(pgid):
    rss = 0
    for process in Path("/proc").iterdir():
        if not process.name.isdecimal():
            continue
        try:
            stat = (process / "stat").read_text().rsplit(") ", 1)[1].split()
            if int(stat[2]) == pgid:
                rss += int((process / "statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError, IndexError):
            continue  # process exited between the two read-only observations
    return rss


def breaches(metrics, budgets):
    return [key for key, ceiling in budgets.items() if metrics[key] > ceiling]


def measured(name, command, work, reports):
    out = work / name
    out.mkdir()
    log = reports / f"{name}.log"
    budget = BUDGETS[name]
    start = time.monotonic()
    peak, killed, usage, status = 0, None, None, None
    with log.open("wb") as output:
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        while True:
            peak = max(peak, group_rss(process.pid))
            pid, status, usage = os.wait4(process.pid, os.WNOHANG)
            if pid:
                process.returncode = os.waitstatus_to_exitcode(status)
                break
            wall = time.monotonic() - start
            if killed is None and (wall > budget["wall_seconds"] or peak > budget["peak_rss_bytes"]):
                killed = "wall_seconds" if wall > budget["wall_seconds"] else "peak_rss_bytes"
                os.killpg(process.pid, signal.SIGKILL)
            time.sleep(0.05)
    metrics = {"wall_seconds": round(time.monotonic() - start, 6),
               "peak_rss_bytes": max(peak, usage.ru_maxrss * 1024), "artifact_bytes": tree_bytes(out)}
    exceeded = breaches(metrics, budget)
    if killed and killed not in exceeded:
        exceeded.append(killed)
    result = {"stage": name, "status": "pass" if process.returncode == 0 and not exceeded else "fail",
              "exit_code": process.returncode, "metrics": metrics, "budgets": budget, "breaches": exceeded}
    if (out / "result.json").exists():
        result["observations"] = json.loads((out / "result.json").read_text())
    result["log_tail"] = log.read_text(errors="replace").splitlines()[-15:]
    return result


def summary(report):
    lines = [f"## Synthetic 300-device scale qualification: {report['status'].upper()}",
             f"Source: `{report['source_commit']}`; runner: `{report['runner_os']}` / `{report['image_version']}`.",
             "240 access, 40 distribution, 8 core, 6 WLC, 6 firewall; 200 VLANs; 1,500 cables including 868 uncollected endpoints.",
             "", "| Stage | Status | Wall s / budget | Peak RSS MiB / budget | Output MiB / budget |",
             "|---|---|---:|---:|---:|"]
    for row in report["stages"]:
        m, b = row.get("metrics"), row["budgets"]
        numbers = [f"{m['wall_seconds']:.3f} / {b['wall_seconds']}",
                   f"{m['peak_rss_bytes'] / MIB:.2f} / {b['peak_rss_bytes'] / MIB:.0f}",
                   f"{m['artifact_bytes'] / MIB:.2f} / {b['artifact_bytes'] / MIB:.0f}"] if m else ["not run"] * 3
        lines.append(f"| {row['stage']} | {row['status']} | " + " | ".join(numbers) + " |")
    lines += ["", "RSS: sampled live process-group sum (50 ms) with exact leader high-water floor; stage includes startup and output validation.",
              "Output size: complete stage-owned uncompressed files; report/logs and dependency installation excluded.",
              "Synthetic offline engine + real AssessHub ingest/API + Scope compiler qualification only. Real infrastructure, browser rendering, portable media and owner acceptance remain separate."]
    for row in report["stages"]:
        if row["status"] == "fail":
            lines += ["", f"### Failed stage: {row['stage']} ({', '.join(row['breaches']) or 'execution failure'})", "```text",
                      *row.get("log_tail", []), "```"]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--stage", choices=tuple(BUDGETS))
    args = parser.parse_args()
    hosted_only()
    work = args.work.resolve()
    if args.stage:
        stage(args.stage, work)
        return
    if args.report_dir is None or work.exists():
        raise ValueError("A fresh work directory and --report-dir are required")
    reports = args.report_dir.resolve()
    work.mkdir(parents=True)
    reports.mkdir(parents=True, exist_ok=True)
    report = {"schema": "atlas-scale-qualification/1", "synthetic_only": True,
              "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "source_tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip(),
              "run_id": os.environ["GITHUB_RUN_ID"], "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
              "runner_os": os.environ["RUNNER_OS"], "image_version": os.environ.get("ImageVersion", "unavailable"),
              "python": sys.version, "node": subprocess.check_output(["node", "--version"], text=True).strip(),
              "status": "fail", "stages": []}
    try:
        for name in BUDGETS:
            if report["stages"] and report["stages"][-1]["status"] != "pass":
                report["stages"].append({"stage": name, "status": "skipped", "budgets": BUDGETS[name], "breaches": []})
                continue
            command = [sys.executable, "-B", str(Path(__file__).resolve()), "--stage", name, "--work", str(work)]
            report["stages"].append(measured(name, command, work, reports))
            write_json(reports / "report.json", report)  # preserve completed rows before the next stage
        report["status"] = "pass" if len(report["stages"]) == len(BUDGETS) and all(r["status"] == "pass" for r in report["stages"]) else "fail"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        write_json(reports / "report.json", report)
        rendered = summary(report)
        (reports / "summary.md").write_text(rendered, encoding="utf-8")
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
                stream.write(rendered)
        print(rendered)
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
