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
import re
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
#: A redaction run renders the FULL document family (workbook, explorer, 7 DOCX, deck) rather than
#: ingest's snapshot-only fast path, so it needs a materially longer ceiling on a field laptop.
REDACT_TIMEOUT_S = 1800

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
        raise IngestError(f"Archive has {len(infos)} files - more than the {MAX_FILES} limit.")
    total = sum(i.file_size for i in infos)
    if total > MAX_UNCOMPRESSED_BYTES:
        raise IngestError(f"Archive expands to {total // (1024 * 1024)} MB - over the "
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


def _resolve_and_scan(path: Any) -> Tuple[Path, int]:
    """Resolve a local collection folder and enforce the shared caps — they bound the ENGINE's
    work, not just archive extraction, so every local channel (ingest, redaction) applies them."""
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
        raise IngestError(f"Folder holds {total // (1024 * 1024)} MB - over the "
                          f"{MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MB limit.")
    return folder, n_files


def run_collection_folder(path: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Run the engine over a SERVER-LOCAL collection folder and return
    ``(snapshot_dict, ingest_report)`` — the portable-app channel (ADR-0004 P1).

    Read-only on the user's tree: devices.json, the template and every output live in a private
    temp workdir; the engine only READS ``--collection-dir``. The ZIP caps apply here too — they
    bound the engine's work, not just archive extraction."""
    folder, n_files = _resolve_and_scan(path)
    workdir = Path(tempfile.mkdtemp(prefix="assesshub_ingest_"))
    try:
        return _assess_tree(folder, n_files, workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _refuse_unsafe_out_dir(out: Path, source: Path) -> None:
    """The deliverable set must not land where it will be destroyed or where it re-contaminates
    the captures: inside the frozen bundle (an update mirrors over everything but ``data\\``), or
    inside the collection folder being redacted."""
    if getattr(sys, "frozen", False):
        bundle = Path(sys.executable).resolve().parent
        if out == bundle or bundle in out.parents:
            raise IngestError(
                f"Refusing to write inside the Atlas folder ({bundle}) - deliverables do not "
                f"belong in the app folder, and an update replaces it. Choose a folder outside "
                f"it (data\\ is not a valid destination either: it is the database store).")
    if out == source or source in out.parents:
        raise IngestError(f"Refusing to write inside the collection folder being redacted "
                          f"({source}) - keep redacted output separate from the raw captures.")
    if out in source.parents:
        # The reverse case, just as dangerous: the RAW captures would sit inside the folder the
        # engineer is about to zip and send, and they are not listed among the produced files.
        raise IngestError(f"Refusing to write to {out} because the collection folder ({source}) "
                          f"is inside it - the raw captures would travel with the redacted set. "
                          f"Choose a folder that does not contain the captures.")


def _mark_output_unsafe(out: Path, why: str) -> None:
    """Leave a loud on-disk marker when a run did NOT certify its output.

    Nothing is deleted (destroying evidence is the worse failure), but the files are named
    ``*_redacted*`` — they assert the exact property the run declined to certify, and stderr
    scrolls away. The marker is what a hurried engineer sees in the folder."""
    try:
        (out / "DO-NOT-SEND-NOT-REDACTED.txt").write_text(
            "This folder is NOT safe to share.\n\n"
            f"Atlas refused to certify this run: {why}.\n"
            "The files here are named *_redacted* but that property was NOT verified, and at\n"
            "least part of the set may contain real client data.\n\n"
            "Delete them or re-run the redaction, and do not send anything from this folder.\n",
            encoding="ascii")
    except OSError:
        pass  # best-effort: never mask the real error with a marker-write failure


#: Private IPv4 space. Redaction remaps every /24 into the IANA-reserved Class E block
#: (``cisco_toolkit.html.redact_snapshot``), so a surviving RFC 1918 address proves the scrub did
#: not happen — the one failure that must never be silent.
_RFC1918_RE = re.compile(
    r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b")


#: Keys whose values are AUTHORED COPY, not observed evidence — form labels, guidance notes and
#: the like legitimately cite RFC 1918 ranges as examples ("supernet, e.g. 10.0.0.0/16"). Scanning
#: the raw JSON text flagged those and failed EVERY real run; a check that always fires is worse
#: than none, because it teaches the engineer to ignore it. (Found by running the real engine —
#: the stubbed unit tests could not have shown it.)
#: Deliberately SHORT. An earlier, wider list exempted 28% of the snapshot's strings — including
#: real observed evidence (`punchlist[].title`, `decisions[].evidence.summary`,
#: `interfaces.<host>.<port>.description`, per-device exposure labels). Those are exactly where a
#: surviving address would matter, so only keys that are unambiguously AUTHORED UI copy stay here.
_DOC_KEYS = frozenset({"help", "hint", "placeholder", "guidance", "doctrine", "tradeoffs"})
_EXAMPLE_MARKERS = ("e.g.", "eg.", "such as", "for example", "example:")


def _iter_evidence_strings(node: Any, path: str = ""):
    """Every string in the snapshot that is OBSERVED EVIDENCE rather than authored copy."""
    if isinstance(node, dict):
        for k, v in node.items():
            if str(k).lower() in _DOC_KEYS:
                continue
            yield from _iter_evidence_strings(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _iter_evidence_strings(v, f"{path}[{i}]")
    elif isinstance(node, str):
        yield path, node


#: The engine's redaction phases. `_run_phase` (COLLECT_PARSE_V3_23_0.py:1383) LOGS AND CONTINUES
#: on any exception "so the workbook still saves" — so a redaction failure leaves the workbook
#: unredacted while `redact_snapshot` (a direct call) still succeeds and the snapshot stays clean.
#: Proven by fault injection: real serials and 9 private addresses shipped in Assessment.xlsx while
#: the verified snapshot was spotless and the run exited 0. Checking only the snapshot inspects the
#: one artifact that CANNOT fail; these phases are where it actually breaks.
_REDACTION_PHASES = ("redact collected dataclasses", "redact workbook cells")


def _assert_redaction_phases_ran(out_xlsx: Path, engine_output: str) -> None:
    """Refuse if a redaction phase was skipped or failed inside the engine.

    Two independent signals, because either alone can go missing: the phase ledger sidecar
    (``ok: false``) and the engine's own ``[SKIP] Phase …`` line on stderr."""
    failed = []
    timings = Path(str(out_xlsx)[: -len(".xlsx")] + ".phase_timings.json")
    if timings.is_file():
        try:
            for row in json.loads(timings.read_text(encoding="utf-8", errors="replace")) or []:
                if str(row.get("phase", "")).lower() in _REDACTION_PHASES and row.get("ok") is False:
                    failed.append(row["phase"])
        except (OSError, ValueError, TypeError, AttributeError):
            pass  # a missing/odd ledger must not mask the stderr signal below
    low = (engine_output or "").lower()
    for phase in _REDACTION_PHASES:
        if f"[skip] phase '{phase}'" in low and phase not in failed:
            failed.append(phase)
    if failed:
        raise EngineRunError(
            f"REDACTION PHASE FAILED inside the engine ({', '.join(sorted(failed))}). The workbook "
            f"is very likely UNREDACTED even though the snapshot looks clean - this is the silent "
            f"failure the check exists for. Do NOT send anything from this run.")


def _assert_scrubbed(snap_path: Path) -> int:
    """Fail LOUD if the 'redacted' snapshot still carries private addresses in EVIDENCE.

    Shipping unredacted client evidence labelled redacted is the worst outcome of this feature,
    and a flag that silently did nothing looks identical to success — so the result is verified
    rather than trusted. Config text is scanned too (``ip address 10.x`` inside a running-config
    line is a real leak); only authored copy and explicit examples are exempt."""
    try:
        snap = json.loads(snap_path.read_text(encoding="utf-8", errors="replace"))
    except ValueError as e:
        # A truncated snapshot (stick filled, yank mid-write) reached the console as a
        # JSONDecodeError traceback. It also means the run is unverifiable — refuse.
        raise EngineRunError(f"The snapshot could not be read back for verification ({e}). "
                             f"Treat the output as UNREDACTED.")
    leaks: Dict[str, str] = {}
    for where, value in _iter_evidence_strings(snap):
        # Exempt only the SENTENCE carrying the example, not the whole string: one "e.g." used to
        # excuse an entire field, and real evidence summaries legitimately contain one.
        # Split on REAL sentence boundaries only (period + space + capital). Splitting on any
        # period severed "e.g." from the address it introduces, so the example itself lost its
        # exemption and every advisory string was flagged.
        segments = [s for s in re.split(r"(?<=[.;])\s+(?=[A-Z])", value)
                    if not any(m in s.lower() for m in _EXAMPLE_MARKERS)]
        for hit in _RFC1918_RE.findall(" ".join(segments)):
            leaks.setdefault(hit, where.lstrip("."))
    if leaks:
        shown = ", ".join(f"{ip} (at {loc})" for ip, loc in list(leaks.items())[:3])
        raise EngineRunError(
            f"REDACTION DID NOT APPLY - {len(leaks)} private address(es) survive in "
            f"{snap_path.name}: {shown}. The output is NOT safe to share; nothing was deleted, "
            f"so inspect it before sending anything.")
    return len(leaks)


def run_redaction_folder(path: Any, out_dir: Any,
                         redact_collection: bool = False) -> Dict[str, Any]:
    """Produce a **redacted, share-safe deliverable set** from a local collection folder.

    The field problem this closes (ADR-0004 P3): ``--redact`` is the control that makes client data
    shareable, but the engine hard-requires a ``--template`` workbook and a ``--devices-file`` that
    the stick does not carry, so the documented command could not run there at all. Both are
    synthesized here exactly as the ingest channel already does — the capability existed, it just
    was not reachable for a redaction run.

    Unlike ingest (which suppresses documents and keeps only the snapshot), this run produces the
    FULL family and preserves it in ``out_dir``; only the synthesized inputs and the engine's log
    live in the private workdir. The engine reads ``--collection-dir`` read-only unless
    ``redact_collection`` is set, which rewrites the raw captures in place — hence a separate,
    explicit argument rather than a default.

    **The PPDIOO document gates (P0-3/DEC-003) deliberately do NOT apply on this path.** Do not
    "fix" that by passing ``--gate-root``; three separate reasons, each independently sufficient:

    1. *Blocking would not contain anything.* ``enforce()`` refuses per DELIVERABLE, and the two
       gated DOCX are not the sole carriers of what they show: ``COLLECT_PARSE_V3_23_0`` writes the
       snapshot (:2817), the explorer (:2831) and the executive deck (:2853) — all rendering
       ``design_blueprint``'s ``target_state``/``wave_plan`` — BEFORE the gates run (:2864/:2879).
       Refusing drops two renderers into the same folder as three ungated artifacts showing the
       same unapproved design, while telling the engineer it was withheld. A false containment
       claim is worse than an honest ungated one (Guardrail 3).
    2. *The disclosure already exists, in a better place.* Every document carries
       ``Status: DRAFT — generated; not yet reviewed`` in its Document Control table
       (``cisco_toolkit/docmeta.py`` ``add_document_control``, used by all 8 DOCX writers). That
       travels INSIDE the file that gets emailed; a sidecar note in the folder does not.
    3. *Nothing here can identify the engagement's ledger.* Gate state is per-engagement but
       nothing binds a ledger to an engagement — it is found by proximity, and proximity is not
       ownership. Anchoring on cwd adopts the shell's directory (on the stick: the folder every
       update wipes); anchoring on the collection adopts the nearest ``docs/engagement-state.json``
       above it, which for the documented layouts is a *shared* parent or the repo checkout itself.
       Both were tried and both mis-attribute across engagements — and a wrong "approvals present"
       drawn from another client's ledger is far worse than saying nothing.

    Note the asymmetry that makes (3) decisive: the gate a design would fail on is
    ``assessment_approved``, and this path ships the assessment (workbook + snapshot) regardless.
    Withholding the design while shipping the unapproved assessment it derives from is backwards.

    The MOP is the one genuinely different case — its cutover procedure, rollback triggers and
    sign-off blocks exist in no other artifact, so refusing it WOULD contain something. That is
    tracked separately; it needs the ledger-ownership problem in (3) solved first, and it is a
    change to what the field tool may withhold, which is not this function's call to make.
    """
    source, n_files = _resolve_and_scan(path)
    out = Path(str(out_dir)).expanduser().resolve()
    _refuse_unsafe_out_dir(out, source)
    if not getattr(sys, "frozen", False) and not _ENGINE_SCRIPT.is_file():
        raise EngineRunError(f"Engine entry point not found at {_ENGINE_SCRIPT}")

    workdir = Path(tempfile.mkdtemp(prefix="atlas_redact_"))
    try:
        root, device_dirs = _find_collection_root(source)
        devices, provenance, skipped = _load_or_synthesize_devices(root, source, device_dirs)
        devices_file = workdir / "devices.json"
        devices_file.write_text(json.dumps(devices), encoding="utf-8")
        template = workdir / "template.xlsx"
        _write_min_template(template)
        try:
            out.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            # A mistyped drive letter, an existing FILE at that path, an illegal character or a
            # write-locked target used to reach the field console as a pathlib traceback. --out is
            # the one value the engineer invents on the spot, so it is the likeliest typo.
            raise IngestError(f"Cannot create the output folder {out}: {e}. Check the drive "
                              f"letter and that the path is writable and not an existing file.")
        pre_existing = {p.name for p in out.iterdir() if p.is_file()}
        out_xlsx = out / "Assessment_redacted.xlsx"

        cmd = [
            *_engine_argv(),
            "--no-collect", "--collection-dir", str(root),
            "--devices-file", str(devices_file),
            "--template", str(template),
            "--output", str(out_xlsx),
            "--workers", "1",
            "--redact",                       # the whole point: every deliverable is pseudonymized
            # NB deliberately NO --gate-root: the PPDIOO document gates do not apply on this path,
            # and that is now a decision rather than the accident it used to be. See the docstring.
        ]
        if redact_collection:
            cmd.append("--redact-collection")  # rewrites the RAW captures in place — opt-in only
        t0 = time.monotonic()
        try:
            # cwd=workdir keeps the engine's log file out of the user's output folder; stdin is
            # closed so an offline run can never block on a credential prompt.
            proc = subprocess.run(cmd, cwd=str(workdir), capture_output=True,
                                  encoding="utf-8", errors="replace",
                                  stdin=subprocess.DEVNULL, timeout=REDACT_TIMEOUT_S)
        except subprocess.TimeoutExpired as e:
            raise EngineRunError(
                f"Redaction run timed out after {REDACT_TIMEOUT_S}s ({len(device_dirs)} devices). "
                f"Partial output may exist in {out} - treat it as UNREDACTED.") from e
        duration = round(time.monotonic() - t0, 1)
        log_tail = "\n".join(((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
                             .splitlines()[-12:]).replace(str(workdir), "<workdir>")
        if proc.returncode != 0:
            raise EngineRunError(f"Engine exited with code {proc.returncode}. Log tail:\n{log_tail}")

        snap_path = Path(str(out_xlsx)[: -len(".xlsx")] + ".snapshot.json")
        if not snap_path.is_file():
            raise EngineRunError(f"Engine completed but wrote no snapshot. Log tail:\n{log_tail}")
        try:
            _assert_redaction_phases_ran(out_xlsx, (proc.stdout or "") + (proc.stderr or ""))
            _assert_scrubbed(snap_path)
        except EngineRunError:
            _mark_output_unsafe(out, "a redaction check FAILED")
            raise
        # Only what THIS run produced — enumerating the directory reported pre-existing files
        # (an engineer's own notes, an earlier unredacted export) under the share-safe banner.
        written = sorted(p.name for p in out.iterdir()
                         if p.is_file() and p.name not in pre_existing)
        return {
            "out_dir": str(out),
            "files": written,
            "n_device_dirs": len(device_dirs) - len(skipped),
            "devices": device_dirs,
            "skipped_dirs": skipped,
            "devices_json": provenance,
            "n_source_files": n_files,
            "redacted_collection": bool(redact_collection),
            "engine_seconds": duration,
            "engine_log_tail": log_tail,
        }
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
    # NB --no-design/--no-mop are load-bearing beyond speed: cwd below is a scratch workdir, so the
    # engine's default gate root ('.') finds no docs/engagement-state.json and the PPDIOO gates
    # would silently degrade to brownfield warn-and-proceed. Dropping either flag from this list
    # therefore emits a gated deliverable UNGATED. Do NOT "fix" that by passing os.getcwd() as
    # --gate-root: here that is the SERVER's directory, which is not any one engagement — see
    # run_redaction_folder's docstring. Pinned by test_gate_state.py's caller inventory.
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
