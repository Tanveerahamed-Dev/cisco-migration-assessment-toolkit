"""W59 T14: the FROZEN Atlas bundle discloses what its SSH session to a SHA-1-only device negotiated.

Hosted ``windows-2025`` portable job only (design section 8, critique P1-2). It proves PR-1's headline claim on
the artifact that ships, not on the floating test environment:

* PR-1 (``--expect sha1-without-opt-in``): the bundle still locks paramiko 4.0.0, whose stock tables negotiate
  SHA-1. Against the SHA-1-only fixture, on the DEFAULT profile with NO opt-in, the frozen engine must
  establish, and its sealed session record and snapshot must say ``legacy_sha1``, effective profile
  ``default``, ``default_permits_sha1`` true, and the "without opt-in" label -- the silent SHA-1 the W59 brief
  exists to end is now at least DISCLOSED.
* From W59 PR-3 (``--expect refused-once``) the same smoke is a NEGATIVE CONTROL: the re-locked paramiko 5
  refuses the device as ``refused_legacy_only`` after exactly one attempt, ``default_permits_sha1`` false.

The peer is the asyncssh fixture (tests/ssh_fixture/server.py) run from its own hash-pinned virtualenv; its
SHA-1-only offer is proven on the wire (tests/ssh_fixture/raw_peer.probe_kexinit) before the bundle connects.
The bundle is copied to a fresh field-layout directory first, so the build output never gains runtime data.

Run with an interpreter that has openpyxl (the hash-locked build venv) -- it writes the engine's minimal
template. Exit 0 = the claim holds; any other exit names the failed assertion.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from cisco_toolkit import ssh_session as S  # noqa: E402
from ssh_fixture.raw_peer import kexinit_names, probe_kexinit  # noqa: E402

HOST = "lab-sw1"
ENGINE_TIMEOUT_S = 1800


def _fail(msg: str) -> NoReturn:
    print(f"T14 FAILED: {msg}", file=sys.stderr)
    raise SystemExit(1)


def _start_fixture(fixture_python: str, log: Path) -> tuple:
    server = ROOT / "tests" / "ssh_fixture" / "server.py"
    proc = subprocess.Popen([fixture_python, "-I", "-B", str(server), "--profile", "sha1-only", "--log", str(log)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8")
    box = []
    reader = threading.Thread(target=lambda: box.append(proc.stdout.readline()), daemon=True)
    reader.start()
    reader.join(90)
    line = box[0] if box else ""
    if not line.startswith("READY "):
        proc.kill()
        _out, err = proc.communicate(timeout=15)
        _fail(f"fixture did not start ({line!r}): {(err or '')[-1500:]}")
    return proc, int(line.split()[1])


def _template(path: Path) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.title = "Interface Data"
    wb.active.append(["Hostname", "Port", "Status"])
    wb.save(str(path))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="W59 T14 frozen SSH disclosure smoke")
    ap.add_argument("--atlas-dist", required=True, help="the built bundle folder (holds Atlas.exe)")
    ap.add_argument("--fixture-python", required=True)
    ap.add_argument("--work", required=True, help="a fresh directory outside the repository")
    ap.add_argument("--expect", choices=("sha1-without-opt-in", "refused-once"), required=True)
    args = ap.parse_args(argv)

    work = Path(args.work).resolve()
    if work.exists():
        _fail(f"--work must not exist yet: {work}")
    work.mkdir(parents=True)
    dist = Path(args.atlas_dist).resolve(strict=True)
    bundle = work / dist.name
    shutil.copytree(dist, bundle)
    exe = bundle / f"{dist.name}.exe"
    if not exe.is_file():
        _fail(f"no {exe.name} in the copied bundle")

    fixture, port = _start_fixture(args.fixture_python, work / "fixture-events.jsonl")
    try:
        wire = probe_kexinit("127.0.0.1", port)
        if kexinit_names(wire, "kex") != [S.LEGACY_SHA1_TIER_KEX[0]] or \
                wire["host_key"] != [S.LEGACY_SHA1_TIER_HOST_KEYS[0]]:
            _fail(f"the fixture is not SHA-1-only on the wire: {wire}")
        job = work / "job"
        job.mkdir()
        collection = job / "collection_20261009_000000"
        devices = job / "devices.json"
        devices.write_text(json.dumps([{"hostname": HOST, "ip": "127.0.0.1", "port": port, "username": "lab",
                                        "password": "lab", "platform": "ios"}]), encoding="utf-8")
        template = job / "template.xlsx"
        _template(template)
        out_xlsx = job / "t14.xlsx"
        cmd = [str(exe), "--allow-live-network", "--run-engine",
               "--devices-file", str(devices), "--template", str(template), "--output", str(out_xlsx),
               "--collection-dir", str(collection), "--workers", "1",
               "--no-html", "--no-docx", "--no-pptx", "--no-design", "--no-mop", "--no-crd", "--no-engagement",
               "--no-archreview", "--no-opshandbook"]
        print("T14: running the frozen engine live against the loopback SHA-1-only fixture ...")
        proc = subprocess.run(cmd, cwd=str(job), stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=ENGINE_TIMEOUT_S)
        tail = "\n".join(((proc.stdout or "") + "\n" + (proc.stderr or "")).strip().splitlines()[-40:])
        print(tail)
        if proc.returncode != 0:
            _fail(f"the frozen engine exited {proc.returncode}")
    finally:
        try:
            fixture.stdin.close()
        except OSError:
            pass
        try:
            fixture.wait(timeout=30)
        except subprocess.TimeoutExpired:
            fixture.kill()

    sidecar = collection / HOST / S.SIDECAR_FILENAME
    if not sidecar.is_file():
        _fail(f"no sealed session record at {sidecar.relative_to(work)}")
    record, reason = S.parse_record(sidecar.read_bytes())
    if record is None:
        _fail(f"the session record fails its closed schema: {reason}")
    row = S.derive_row(HOST, sidecar.read_bytes(), evidence=f"{HOST}/{S.SIDECAR_FILENAME}", live=True)
    snap = json.loads(Path(str(out_xlsx)[: -len(".xlsx")] + ".snapshot.json").read_text(encoding="utf-8"))
    snap_rows = {r["host"]: r for r in snap.get("ssh_sessions", {}).get("rows", [])}
    findings = [f for f in snap.get("software_risk", {}).get("findings", [])
                if f.get("kind") == S.SURFACE_KIND and f.get("host") == HOST]
    events = [json.loads(x) for x in (work / "fixture-events.jsonl").read_text(encoding="utf-8").splitlines() if x]
    attempts = sum(1 for e in events if e["event"] == "connection") - 1          # minus the wire probe

    if args.expect == "sha1-without-opt-in":
        neg = record.get("negotiated") or {}
        checks = {
            "outcome established": record["outcome"] == "established",
            "SHA-1 kex negotiated": neg.get("kex") == S.LEGACY_SHA1_TIER_KEX[0] and neg.get("kex_hash_bytes") == 20,
            "2048-bit group recorded": neg.get("dh_group_bits") == 2048,
            "SHA-1 host-key signature": neg.get("host_key_algorithm") == S.LEGACY_SHA1_TIER_HOST_KEYS[0],
            "default profile, no opt-in": record["consent"]["effective_profile"] == S.DEFAULT_PROFILE,
            "library permits SHA-1": record["library"]["default_permits_sha1"] is True,
            "status legacy_sha1": row["status"] == "legacy_sha1",
            "'without opt-in' label": "without opt-in" in (row["label"] or ""),
            "snapshot row agrees": snap_rows.get(HOST, {}).get("status") == "legacy_sha1",
            "Medium software-risk finding": [f["severity"] for f in findings] == ["Medium"],
        }
    else:
        checks = {
            "outcome refused": record["outcome"] == "negotiation_refused",
            "classified refused_legacy_only": (record.get("refusal") or {}).get("classification")
            == "refused_legacy_only",
            "exactly one attempt": record["attempts"] == 1 and attempts == 1,
            "library does not permit SHA-1": record["library"]["default_permits_sha1"] is False,
            "snapshot row agrees": snap_rows.get(HOST, {}).get("status") == "refused_legacy_only",
            "no password crossed": not [e for e in events if e["event"] == "auth"],
        }
    failed = [name for name, ok in checks.items() if not ok]
    for name, ok in checks.items():
        print(f"  [{'ok' if ok else 'FAIL'}] {name}")
    if failed:
        _fail("; ".join(failed) + f" -- record: {json.dumps(record, sort_keys=True)}")
    print(f"T14 OK ({args.expect}): {row['label'] or row['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
