"""Ingest a **raw collection ZIP** by running the real engine pipeline server-side.

Until now AssessHub consumed finished ``*.snapshot.json`` files — someone still had to run the CLI
engine offline first. This module closes that loop: upload a ZIP of the offline collection layout
(``<host>/show_*.txt``, exactly what ``--no-collect`` reads and what the collector itself writes) and
AssessHub runs ``COLLECT_PARSE_V3_23_0.py`` in a subprocess over it, harvests the snapshot it
produces, and stores it like any uploaded one. ``run_collection_folder`` is the same pipeline over
a SERVER-LOCAL directory — the portable-app path (ADR-0004 P1), where the collection already sits
on disk beside the app and a ZIP round-trip would be pure friction.

Design points:

* **The real pipeline, not a re-implementation** — the engine runs as a child process with the exact
  flags the test-suite uses (``--no-collect --collection-dir … --workers 1``), so an ingested snapshot
  is identical to what the CLI would have produced. A subprocess (not in-process ``main()``) keeps the
  engine's logging/global state out of the server and makes a hard timeout enforceable. Frozen
  (PyInstaller) builds have no script on disk and ``sys.executable`` IS the app — ``_engine_argv``
  re-invokes the exe with ``serve.ENGINE_SENTINEL``, which ``serve.main`` turns into the engine CLI
  before any server code runs; child isolation and the timeout are unchanged.
* **Deliverables are skipped** (every ``--no-*`` document flag): AssessHub renders the explorer and
  generates documents on demand from the stored snapshot, so only the workbook (which the engine
  always writes) and the snapshot are produced — the fast path. V3.23.170: the flag list had gone
  stale as deliverables accreted (crd/engagement/archreview/opshandbook were rendering on every
  ingest inside the request path); keep it in lockstep with the engine's argparse.
* **devices.json is optional.** If the ZIP carries one it is used (credentials are scrubbed — the
  offline path never connects); otherwise one is synthesized from the per-device directory names and
  the engine's own ``detect_platform_from_files`` autodetection does the rest.
* **Hostile-archive guards**: entry names are validated against path traversal / absolute paths, and
  the archive is capped on file count and total uncompressed size before anything is written.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import engine
from .serve import ENGINE_SENTINEL

_REPO_ROOT = Path(engine.__file__).resolve().parents[2]
_ENGINE_SCRIPT = _REPO_ROOT / "COLLECT_PARSE_V3_23_0.py"

MAX_FILES = 20_000
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024       # compressed upload cap, enforced while reading the body
MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024  # generous: a 60-switch fleet's show outputs are ~tens of MB
ENGINE_TIMEOUT_S = 600

_DEVICE_KEYS = ("hostname", "ip", "username", "password", "platform")


class IngestError(ValueError):
    """The uploaded archive is not a usable collection (a 400-class, user-fixable problem)."""


class EngineRunError(RuntimeError):
    """The engine pipeline failed or timed out over an extracted collection."""


def _safe_extract(raw: bytes, dest: Path) -> int:
    """Extract the archive under ``dest``, refusing traversal/absolute entries and bomb-sized content.

    Returns the number of files written."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as e:
        raise IngestError(f"Not a valid ZIP archive: {e}") from e
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if not infos:
        raise IngestError("The ZIP archive is empty.")
    if len(infos) > MAX_FILES:
        raise IngestError(f"Archive has {len(infos)} files — more than the {MAX_FILES} limit.")
    total = sum(i.file_size for i in infos)
    if total > MAX_UNCOMPRESSED_BYTES:
        raise IngestError(f"Archive expands to {total // (1024 * 1024)} MB — over the "
                          f"{MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MB limit.")
    dest_resolved = dest.resolve()
    for info in infos:
        name = info.filename.replace("\\", "/")
        target = (dest / name).resolve()
        if not str(target).startswith(str(dest_resolved) + os.sep):
            raise IngestError(f"Archive entry {info.filename!r} escapes the extraction directory "
                              "(path traversal) — refused.")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
        # Per-entry failures are user-fixable archive problems, not server faults: encrypted
        # entries (RuntimeError), unsupported compression like Deflate64 (NotImplementedError),
        # CRC mismatch on a truncated file (BadZipFile), names invalid on this OS (OSError).
        except (OSError, RuntimeError, NotImplementedError, ValueError, zipfile.BadZipFile) as e:
            raise IngestError(f"Cannot extract archive entry {info.filename!r}: {e}") from e
    return len(infos)


def _find_collection_root(dest: Path) -> Tuple[Path, List[str]]:
    """Locate the directory whose immediate children are the per-device dirs of ``show_*.txt`` files.

    Tolerates a wrapping folder in the ZIP (``my-export/<host>/show_*.txt``) and stray copies nested
    INSIDE a device folder (``core1/backup/show_version.txt`` — the engine's loader ignores those
    too). Returns ``(root, device_dir_names)``."""
    candidates: List[Path] = []
    for dirpath, _dirnames, filenames in os.walk(dest):
        if any(f.startswith("show_") and f.endswith(".txt") for f in filenames):
            candidates.append(Path(dirpath))
    if not candidates:
        raise IngestError(
            "No device outputs found. Expected the offline-collection layout: one folder per device "
            "containing its show-command outputs (e.g. core1/show_interface_status.txt).")
    if dest in candidates:
        raise IngestError(
            "show_*.txt files sit at the archive root. Place each device's outputs in its own folder "
            "named after the device (e.g. core1/show_interface_status.txt).")
    root = min({d.parent for d in candidates}, key=lambda p: len(p.parts))
    device_dirs = sorted({d.name for d in candidates if d.parent == root})
    for d in candidates:
        if d.parent == root:
            continue
        if d.is_relative_to(root) and d.relative_to(root).parts[0] in device_dirs:
            continue  # a stray copy inside a device folder — harmless, the engine reads only <host>/
        raise IngestError(
            "Device folders sit at different depths in the archive — put every device folder under "
            "one common directory.")
    return root, device_dirs


def _devices_json_path(root: Path, dest: Path) -> Optional[Path]:
    """A bundled devices.json at the collection root or any wrapping level up to the archive root —
    the collector's own working-directory layout keeps it NEXT TO the collection dir, not inside it."""
    cur = root
    while True:
        candidate = cur / "devices.json"
        if candidate.is_file():
            return candidate
        if cur == dest:
            return None
        cur = cur.parent


def _placeholder(hostname: str, platform: str = "") -> Dict[str, str]:
    # The offline run never connects, but blank credentials trigger the engine's interactive
    # getpass fallback on a TTY — placeholders keep it batch-safe.
    return {"hostname": hostname, "ip": "0.0.0.0", "username": "offline",
            "password": "offline", "platform": platform}


def _load_or_synthesize_devices(root: Path, dest: Path,
                                device_dirs: List[str]) -> Tuple[List[Dict[str, str]], str, List[str]]:
    """Device entries for the engine run: ``(devices, provenance, skipped_dirs)``.

    A bundled devices.json contributes the entries whose hostname maps to an existing device folder
    (the engine resolves a hostname's folder via ``safe_fs_name``, so match through it, not string
    equality); every folder it does NOT cover still gets a synthesized entry — a curated file must
    never silently shrink the assessed fleet. Folders whose name can't round-trip ``safe_fs_name``
    (the engine would look elsewhere) are skipped and reported."""
    from cisco_toolkit.textutils import safe_fs_name

    devices: List[Dict[str, str]] = []
    covered: set = set()
    bundled = _devices_json_path(root, dest)
    if bundled is not None:
        try:
            data = json.loads(bundled.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise IngestError(f"devices.json is not valid JSON: {e}") from e
        for d in (data if isinstance(data, list) else [data]):
            if not isinstance(d, dict) or not d.get("hostname"):
                continue
            hostname = str(d["hostname"])
            dirname = safe_fs_name(hostname)
            if dirname in set(device_dirs) and dirname not in covered:
                covered.add(dirname)
                devices.append(_placeholder(hostname, str(d.get("platform", "") or "")))

    skipped: List[str] = []
    for name in device_dirs:
        if name in covered:
            continue
        if safe_fs_name(name) != name:
            skipped.append(name)  # engine would resolve this hostname to a different folder name
            continue
        devices.append(_placeholder(name))
    if not devices:
        raise IngestError(
            "No usable device folders: none of the folder names are addressable as hostnames "
            f"(skipped: {', '.join(skipped[:8])}). Name each folder after its device hostname.")
    return devices, ("bundled" if covered else "synthesized"), skipped


def _write_min_template(path: Path) -> None:
    """The minimal workbook the loader needs (header row only) — same as the test-suite's."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Interface Data"
    ws.append(["Hostname", "Port", "Status"])
    wb.save(str(path))


def _engine_argv() -> List[str]:
    """Argv PREFIX that makes a child process run the engine CLI.

    Checkout: the interpreter + the repo-root script. Frozen (PyInstaller): there is no script on
    disk and ``sys.executable`` IS the app — re-invoke the exe with ``ENGINE_SENTINEL``, which
    ``serve.main`` turns into the engine CLI before any server code runs. Both forms stay a real
    child process: isolation and the hard timeout are identical."""
    if getattr(sys, "frozen", False):
        return [sys.executable, ENGINE_SENTINEL]
    return [sys.executable, str(_ENGINE_SCRIPT)]


def run_collection_zip(raw: bytes) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Extract the ZIP, run the engine over it, and return ``(snapshot_dict, ingest_report)``."""
    workdir = Path(tempfile.mkdtemp(prefix="assesshub_ingest_"))
    try:
        extracted = workdir / "extracted"
        extracted.mkdir()
        n_files = _safe_extract(raw, extracted)
        return _assess_tree(extracted, n_files, workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def run_collection_folder(path: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Run the engine over a SERVER-LOCAL collection folder and return
    ``(snapshot_dict, ingest_report)`` — the portable-app channel (ADR-0004 P1).

    Read-only on the user's tree: devices.json, the template and every output live in a private
    temp workdir; the engine only READS ``--collection-dir``. The ZIP caps apply here too — they
    bound the engine's work, not just archive extraction."""
    folder = Path(str(path)).expanduser()
    if not folder.is_dir():
        raise IngestError(f"Not a directory: {folder}")
    folder = folder.resolve()
    n_files = 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(folder):
        for name in filenames:
            n_files += 1
            if n_files > MAX_FILES:
                raise IngestError(f"Folder has more than the {MAX_FILES}-file limit.")
            try:
                total += os.stat(os.path.join(dirpath, name)).st_size
            except OSError:
                continue  # vanished/unreadable entry — the engine's loader skips it too
    if not n_files:
        raise IngestError("The folder is empty.")
    if total > MAX_UNCOMPRESSED_BYTES:
        raise IngestError(f"Folder holds {total // (1024 * 1024)} MB — over the "
                          f"{MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MB limit.")
    workdir = Path(tempfile.mkdtemp(prefix="assesshub_ingest_"))
    try:
        return _assess_tree(folder, n_files, workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _assess_tree(tree: Path, n_files: int, workdir: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Shared back half of both ingest channels: locate the collection root under ``tree``, run
    the engine child over it, harvest + sanity-check the snapshot, assemble the report."""
    if not getattr(sys, "frozen", False) and not _ENGINE_SCRIPT.is_file():
        raise EngineRunError(f"Engine entry point not found at {_ENGINE_SCRIPT}")
    root, device_dirs = _find_collection_root(tree)
    devices, provenance, skipped_dirs = _load_or_synthesize_devices(root, tree, device_dirs)

    devices_file = workdir / "devices.json"
    devices_file.write_text(json.dumps(devices), encoding="utf-8")
    template = workdir / "template.xlsx"
    _write_min_template(template)
    out_xlsx = workdir / "ingest.xlsx"

    cmd = [
        *_engine_argv(),
        "--no-collect", "--collection-dir", str(root),
        "--devices-file", str(devices_file),
        "--template", str(template),
        "--output", str(out_xlsx),
        "--workers", "1",
        "--no-html", "--no-docx", "--no-pptx", "--no-design", "--no-mop",
        "--no-crd", "--no-engagement", "--no-archreview", "--no-opshandbook",  # V3.23.170 (stale-list fix)
    ]
    t0 = time.monotonic()
    try:
        # stdin=DEVNULL: capture_output pipes only stdout/stderr — an inherited TTY stdin would
        # let the engine's interactive credential prompt block the run until the timeout.
        # Explicit utf-8 (not text=True's locale codepage): a non-cp1252 byte in engine output
        # otherwise kills the reader thread on Windows (log tail silently lost) or raises on POSIX.
        proc = subprocess.run(cmd, cwd=str(workdir), capture_output=True,
                              encoding="utf-8", errors="replace",
                              stdin=subprocess.DEVNULL, timeout=ENGINE_TIMEOUT_S)
    except subprocess.TimeoutExpired as e:
        raise EngineRunError(f"Engine run timed out after {ENGINE_TIMEOUT_S}s "
                             f"({len(device_dirs)} devices).") from e
    duration = round(time.monotonic() - t0, 1)
    log_tail = "\n".join(((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
                         .splitlines()[-12:])
    # WEBAP-01: this tail is surfaced to the (possibly remote, unauthenticated) uploader via the API 500
    # detail AND the success report. Strip the server-side working-directory absolute path so an engine
    # breadcrumb cannot disclose the server's filesystem layout. The engine runs with cwd=workdir and writes
    # its outputs under it, so paths in its output are workdir-rooted.
    log_tail = log_tail.replace(str(workdir), "<workdir>")
    if proc.returncode != 0:
        raise EngineRunError(f"Engine exited with code {proc.returncode}. Log tail:\n{log_tail}")

    snap_path = Path(str(out_xlsx)[: -len(".xlsx")] + ".snapshot.json")
    if not snap_path.is_file():
        raise EngineRunError(f"Engine completed but wrote no snapshot. Log tail:\n{log_tail}")
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    # The engine exits 0 even when it parsed nothing (a device with no matching files just
    # yields an empty section) — don't store a plausible-looking but empty assessment.
    if not snap.get("devices"):
        raise EngineRunError(f"Engine produced a snapshot with no devices. Log tail:\n{log_tail}")
    if not snap.get("interfaces"):
        raise EngineRunError(
            "Engine parsed no interface data from the archive — the show-command files did not "
            f"match any device. Log tail:\n{log_tail}")

    report = {
        "n_archive_files": n_files,
        # WEBAP-02: the headline count must not exceed the fleet actually assessed. Non-round-trippable
        # folder names are dropped into skipped_dirs (the engine would resolve their hostname to a different
        # folder), so counting them here over-reported the assessed device count -- the exact n-count drift
        # the project guards against. Report the addressable directories (skipped excluded; still disclosed).
        "n_device_dirs": len(device_dirs) - len(skipped_dirs),
        "devices": device_dirs,
        "skipped_dirs": skipped_dirs,
        "devices_json": provenance,
        "engine_seconds": duration,
        "engine_log_tail": log_tail,
    }
    return snap, report
