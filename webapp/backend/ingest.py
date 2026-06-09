"""Ingest a **raw collection ZIP** by running the real engine pipeline server-side.

Until now AssessHub consumed finished ``*.snapshot.json`` files — someone still had to run the CLI
engine offline first. This module closes that loop: upload a ZIP of the offline collection layout
(``<host>/show_*.txt``, exactly what ``--no-collect`` reads and what the collector itself writes) and
AssessHub runs ``COLLECT_PARSE_V3_23_0.py`` in a subprocess over it, harvests the snapshot it
produces, and stores it like any uploaded one.

Design points:

* **The real pipeline, not a re-implementation** — the engine runs as a child process with the exact
  flags the test-suite uses (``--no-collect --collection-dir … --workers 1``), so an ingested snapshot
  is identical to what the CLI would have produced. A subprocess (not in-process ``main()``) keeps the
  engine's logging/global state out of the server and makes a hard timeout enforceable.
* **Deliverables are skipped** (``--no-html --no-docx --no-pptx --no-design --no-mop``): AssessHub
  renders the explorer and generates documents on demand from the stored snapshot, so only the
  workbook (which the engine always writes) and the snapshot are produced — the fast path.
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
from typing import Any, Dict, List, Tuple

from . import engine

_REPO_ROOT = Path(engine.__file__).resolve().parents[2]
_ENGINE_SCRIPT = _REPO_ROOT / "COLLECT_PARSE_V3_23_0.py"

MAX_FILES = 20_000
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
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)
    return len(infos)


def _find_collection_root(dest: Path) -> Tuple[Path, List[str]]:
    """Locate the directory whose immediate children are the per-device dirs of ``show_*.txt`` files.

    Tolerates a wrapping folder in the ZIP (``my-export/<host>/show_*.txt``). Returns
    ``(root, device_dir_names)``."""
    device_dirs: List[Path] = []
    for dirpath, _dirnames, filenames in os.walk(dest):
        if any(f.startswith("show_") and f.endswith(".txt") for f in filenames):
            device_dirs.append(Path(dirpath))
    if not device_dirs:
        raise IngestError(
            "No device outputs found. Expected the offline-collection layout: one folder per device "
            "containing its show-command outputs (e.g. core1/show_interface_status.txt).")
    if dest in device_dirs:
        raise IngestError(
            "show_*.txt files sit at the archive root. Place each device's outputs in its own folder "
            "named after the device (e.g. core1/show_interface_status.txt).")
    parents = {d.parent for d in device_dirs}
    if len(parents) > 1:
        raise IngestError(
            "Device folders sit at different depths in the archive — put every device folder under "
            "one common directory.")
    root = parents.pop()
    return root, sorted(d.name for d in device_dirs)


def _load_or_synthesize_devices(root: Path, dest: Path, device_dirs: List[str]) -> List[Dict[str, str]]:
    """Use a bundled devices.json when present (credentials scrubbed, entries filtered to folders that
    actually exist); otherwise synthesize one from the device folder names (platform autodetects)."""
    for candidate in (root / "devices.json", dest / "devices.json"):
        if candidate.is_file():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8-sig"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise IngestError(f"devices.json is not valid JSON: {e}") from e
            entries = data if isinstance(data, list) else [data]
            devices = []
            for d in entries:
                if not isinstance(d, dict) or not d.get("hostname"):
                    continue
                devices.append({
                    "hostname": str(d["hostname"]),
                    # The offline run never connects, but blank credentials trigger the engine's
                    # interactive getpass fallback on a TTY — placeholders keep it batch-safe.
                    "ip": "0.0.0.0", "username": "offline", "password": "offline",
                    "platform": str(d.get("platform", "") or ""),
                })
            devices = [d for d in devices if d["hostname"] in set(device_dirs)] or devices
            if devices:
                return devices
    return [{"hostname": name, "ip": "0.0.0.0", "username": "offline", "password": "offline",
             "platform": ""} for name in device_dirs]


def _write_min_template(path: Path) -> None:
    """The minimal workbook the loader needs (header row only) — same as the test-suite's."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Interface Data"
    ws.append(["Hostname", "Port", "Status"])
    wb.save(str(path))


def run_collection_zip(raw: bytes) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Extract the ZIP, run the engine over it, and return ``(snapshot_dict, ingest_report)``."""
    if not _ENGINE_SCRIPT.is_file():  # pragma: no cover - deployment misconfiguration
        raise EngineRunError(f"Engine entry point not found at {_ENGINE_SCRIPT}")
    workdir = Path(tempfile.mkdtemp(prefix="assesshub_ingest_"))
    try:
        extracted = workdir / "extracted"
        extracted.mkdir()
        n_files = _safe_extract(raw, extracted)
        root, device_dirs = _find_collection_root(extracted)
        devices = _load_or_synthesize_devices(root, extracted, device_dirs)

        devices_file = workdir / "devices.json"
        devices_file.write_text(json.dumps(devices), encoding="utf-8")
        template = workdir / "template.xlsx"
        _write_min_template(template)
        out_xlsx = workdir / "ingest.xlsx"

        cmd = [
            sys.executable, str(_ENGINE_SCRIPT),
            "--no-collect", "--collection-dir", str(root),
            "--devices-file", str(devices_file),
            "--template", str(template),
            "--output", str(out_xlsx),
            "--workers", "1",
            "--no-html", "--no-docx", "--no-pptx", "--no-design", "--no-mop",
        ]
        t0 = time.monotonic()
        try:
            # stdin=DEVNULL: capture_output pipes only stdout/stderr — an inherited TTY stdin would
            # let the engine's interactive credential prompt block the run until the timeout.
            proc = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True,
                                  stdin=subprocess.DEVNULL, timeout=ENGINE_TIMEOUT_S)
        except subprocess.TimeoutExpired as e:
            raise EngineRunError(f"Engine run timed out after {ENGINE_TIMEOUT_S}s "
                                 f"({len(device_dirs)} devices).") from e
        duration = round(time.monotonic() - t0, 1)
        log_tail = "\n".join(((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
                             .splitlines()[-12:])
        if proc.returncode != 0:
            raise EngineRunError(f"Engine exited with code {proc.returncode}. Log tail:\n{log_tail}")

        snap_path = Path(str(out_xlsx)[: -len(".xlsx")] + ".snapshot.json")
        if not snap_path.is_file():
            raise EngineRunError(f"Engine completed but wrote no snapshot. Log tail:\n{log_tail}")
        snap = json.loads(snap_path.read_text(encoding="utf-8"))

        report = {
            "n_archive_files": n_files,
            "n_device_dirs": len(device_dirs),
            "devices": device_dirs,
            "devices_json": "bundled" if (root / "devices.json").is_file()
                            or (extracted / "devices.json").is_file() else "synthesized",
            "engine_seconds": duration,
            "engine_log_tail": log_tail,
        }
        return snap, report
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
