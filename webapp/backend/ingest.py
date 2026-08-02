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
import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
import zipfile
import uuid
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Tuple

from . import engine, redaction_verify, summary
from .serve import ENGINE_SENTINEL

_REPO_ROOT = Path(engine.__file__).resolve().parents[2]
_ENGINE_SCRIPT = _REPO_ROOT / "COLLECT_PARSE_V3_23_0.py"

def reject_nonfinite(token: str):
    """`json.loads`' hook for the three tokens JSON itself does not define — ``Infinity``,
    ``-Infinity``, ``NaN``. Python's decoder accepts them by default; the HTTP layer cannot return
    them, so a snapshot carrying one is a STORED denial of service.

    Confirmed end to end: the token survives the upload, sqlite persists it (``json.dumps`` defaults
    to ``allow_nan=True``), and every later read materialises a non-finite float — at which point
    Starlette's ``JSONResponse.render`` calls ``json.dumps(..., allow_nan=False)`` and raises "Out of
    range float values are not JSON compliant". One poisoned leaf therefore makes
    ``/snapshots/{id}``, its sections, and everything derived from it answer HTTP 500 FOREVER for
    that snapshot, with no way to clear it from the UI.

    Refused at the two ingest boundaries rather than sanitised: coercing to null would silently
    invent a value the uploader never sent, and guarding per read route means every route added
    later re-inherits the bug. THE one owner — `app._parse_snapshot_bytes` (untrusted upload) and
    `_assess_tree` (engine output, which derives from untrusted device text) both call it.
    """
    raise ValueError(
        f"non-finite number {token!r}: JSON has no such literal, and a snapshot carrying one cannot "
        f"be served back over HTTP")


MAX_FILES = 20_000
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024       # compressed upload cap, enforced while reading the body
MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024  # generous: a 60-switch fleet's show outputs are ~tens of MB
ENGINE_TIMEOUT_S = 600
#: A redaction run renders the FULL document family (workbook, explorer, 7 DOCX, deck) rather than
#: ingest's snapshot-only fast path, so it needs a materially longer ceiling on a field laptop.
REDACT_TIMEOUT_S = 1800
OUTPUT_LOCK_TIMEOUT_S = 30.0

_DEVICE_KEYS = ("hostname", "ip", "username", "password", "platform")


class IngestError(ValueError):
    """The uploaded archive is not a usable collection (a 400-class, user-fixable problem)."""


class EngineRunError(RuntimeError):
    """The engine pipeline failed or timed out over an extracted collection."""


@contextlib.contextmanager
def _output_dir_lock(out: Path):
    """Interprocess exclusive lock for one canonical redaction destination."""
    lock_path = out.parent / f".{out.name}.atlas-redaction.lock"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        handle = open(lock_path, "a+b")
    except OSError as exc:
        raise IngestError(
            f"Cannot create the output folder {out}: {exc}. Check the drive letter and that "
            "the parent path is a writable directory."
        ) from exc
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    deadline = time.monotonic() + OUTPUT_LOCK_TIMEOUT_S
    acquired = False
    try:
        while not acquired:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise EngineRunError(
                        f"Another redaction run still owns the output folder {out}; "
                        "nothing from this run was written there."
                    )
                time.sleep(0.05)
        yield
    finally:
        if acquired:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


#: Windows reserved DEVICE names. ``open()`` on one of these SUCCEEDS and writes to the device
#: rather than to a file: bytes sent to ``NUL`` vanish without an error, ``COM1``-``COM9`` go out a
#: serial port, ``CON``/``PRN``/``AUX`` reach the console and the printer. The reservation is per
#: path COMPONENT and ignores the extension, so ``core1/NUL`` and ``core1/nul.txt`` are both the
#: null device — and both pass a containment check, because the path really does resolve inside
#: ``dest``. Checked on every OS, not only Windows: a ZIP extracted on a Linux server is carried to
#: a Windows field laptop, where the same names become devices again.
_WIN_RESERVED = frozenset(["con", "prn", "aux", "nul", "conin$", "conout$", "clock$"]
                          + [f"com{i}" for i in range(1, 10)]
                          + [f"lpt{i}" for i in range(1, 10)])


def _unsafe_component(part: str) -> str:
    """Why this component is unsafe or ambiguous on any supported extraction platform."""
    if not part:
        return "is empty"
    if part in (".", ".."):
        return "is a navigation component"
    if any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in part):
        return "contains a control, formatting, surrogate, or NUL character"
    if ":" in part:
        return "contains a colon (drive, URI, or NTFS alternate-data-stream syntax)"
    if part.strip() != part:
        return "starts or ends with whitespace"
    if part.rstrip(". ") != part:
        return ("ends in a dot or space, which Windows silently strips (it would land on top of "
                "another entry)")
    portable_stem = unicodedata.normalize("NFKC", part).split(".")[0].strip().casefold()
    if portable_stem in _WIN_RESERVED:
        return "is a reserved device name - writing it would go to the device, not to a file"
    return ""


def _source_size(source: bytes | bytearray | BinaryIO) -> int:
    if isinstance(source, (bytes, bytearray)):
        return len(source)
    try:
        original = source.tell()
        source.seek(0, os.SEEK_END)
        size = source.tell()
        source.seek(original)
    except (AttributeError, OSError, ValueError) as exc:
        raise IngestError("The uploaded archive is not a seekable file.") from exc
    return int(size)


def _zip_parts(info: zipfile.ZipInfo) -> Tuple[str, ...]:
    """Lexically validate one member name without touching the destination filesystem."""
    raw = info.filename
    normalized = raw.replace("\\", "/")
    lowered = normalized.casefold()
    if not raw:
        raise IngestError("Archive contains an empty member name - refused.")
    if (
        normalized.startswith("/")
        or lowered.startswith(("//?/", "//./", "/??/", "/device/", "/globalroot/"))
        or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", normalized)
    ):
        raise IngestError(
            f"Archive entry {raw!r} is rooted, remote, drive/device, URI, or ADS syntax - refused."
        )
    if any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in raw):
        raise IngestError(
            f"Archive entry {raw!r} contains a control or hidden formatting character - refused."
        )
    trimmed = normalized[:-1] if info.is_dir() and normalized.endswith("/") else normalized
    parts = tuple(trimmed.split("/"))
    if not parts or any(part in {"", ".", ".."} for part in parts):
        if ".." in parts:
            raise IngestError(
                f"Archive entry {raw!r} escapes the extraction directory "
                "(path traversal) - refused."
            )
        raise IngestError(
            f"Archive entry {raw!r} has an empty or ambiguous path component - refused."
        )
    for part in parts:
        why = _unsafe_component(part)
        if why:
            raise IngestError(f"Archive entry {raw!r} {why} - refused.")
        compat = unicodedata.normalize("NFKC", part)
        if "/" in compat or "\\" in compat:
            raise IngestError(
                f"Archive entry {raw!r} changes path structure under Unicode normalization - refused."
            )
    return parts


def _zip_member_special(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    kind = stat.S_IFMT(mode)
    if not kind:
        return False
    expected = stat.S_IFDIR if info.is_dir() else stat.S_IFREG
    return kind != expected


def _preflight_zip(zf: zipfile.ZipFile) -> List[Tuple[zipfile.ZipInfo, Tuple[str, ...]]]:
    """Validate all metadata and aliases before the first destination lookup or write."""
    infos = zf.infolist()
    files = [info for info in infos if not info.is_dir()]
    if not files:
        raise IngestError("The ZIP archive is empty.")
    if len(infos) > MAX_FILES:
        raise IngestError(
            f"Archive has {len(infos)} entries - more than the {MAX_FILES} limit."
        )

    prepared: List[Tuple[zipfile.ZipInfo, Tuple[str, ...]]] = []
    aliases: Dict[Tuple[str, str], str] = {}
    file_windows_keys: set[str] = set()
    all_windows_keys: List[Tuple[str, str]] = []
    total = 0
    supported_compression = {
        zipfile.ZIP_STORED,
        zipfile.ZIP_DEFLATED,
        getattr(zipfile, "ZIP_BZIP2", -1),
        getattr(zipfile, "ZIP_LZMA", -2),
    }
    for info in infos:
        parts = _zip_parts(info)
        if info.flag_bits & 0x1:
            raise IngestError(f"Archive entry {info.filename!r} is encrypted - refused.")
        if info.compress_type not in supported_compression:
            raise IngestError(
                f"Archive entry {info.filename!r} uses unsupported compression - refused."
            )
        if _zip_member_special(info):
            raise IngestError(
                f"Archive entry {info.filename!r} is a symlink or special filesystem object - refused."
            )
        if info.file_size < 0 or info.compress_size < 0:
            raise IngestError(f"Archive entry {info.filename!r} has an invalid size - refused.")
        if not info.is_dir():
            total += info.file_size
            if total > MAX_UNCOMPRESSED_BYTES:
                raise IngestError(
                    f"Archive expands beyond the "
                    f"{MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MB limit."
                )

        slash = "/".join(parts)
        namespaces = {
            "exact": info.filename,
            "slash": slash,
            "casefold": slash.casefold(),
            "nfc": unicodedata.normalize("NFC", slash),
            "nfkc": unicodedata.normalize("NFKC", slash),
            "windows": "/".join(
                unicodedata.normalize("NFKC", part).rstrip(" .").casefold()
                for part in parts
            ),
        }
        for namespace, key in namespaces.items():
            alias_key = (namespace, key)
            prior = aliases.get(alias_key)
            if prior is not None:
                raise IngestError(
                    f"Archive entries {prior!r} and {info.filename!r} are duplicate aliases "
                    f"under {namespace} normalization - refused."
                )
            aliases[alias_key] = info.filename
        windows_key = namespaces["windows"]
        all_windows_keys.append((windows_key, info.filename))
        if not info.is_dir():
            file_windows_keys.add(windows_key)
        prepared.append((info, parts))

    for key, original in all_windows_keys:
        components = key.split("/")
        for index in range(1, len(components)):
            if "/".join(components[:index]) in file_windows_keys:
                raise IngestError(
                    f"Archive entry {original!r} descends through another file entry - refused."
                )
    return prepared


def iobase_upload_file(stream: BinaryIO) -> BinaryIO:
    """Return ``stream`` carrying the full IO probe interface, unwrapping a py3.10 spool.

    py3.10's ``tempfile.SpooledTemporaryFile`` does not implement ``seekable()``/``readable()``/
    ``writable()`` -- they arrived in 3.11 (bpo-35112) -- and downstream consumers legitimately
    probe them: ``zipfile.ZipFile`` does (zipfile.py:744; AttributeError measured on the first
    py3.10 CI leg ever to run this path, five tests at once), and the ingest route promises its
    zip runner a stream that answers them (the runner is replaceable, so the unwrap inside
    ``_safe_extract`` alone cannot honour that contract). The spool's underlying ``._file``
    (BytesIO before rollover, a real temp file after) carries the full interface, so unwrap it
    rather than teaching every consumer about spools. On 3.11+ ``hasattr`` succeeds and this is
    the identity function -- which is why no other leg ever saw the gap.
    """
    if not hasattr(stream, "seekable") and hasattr(stream, "_file"):
        return stream._file
    return stream


def _safe_extract(source: bytes | bytearray | BinaryIO, dest: Path) -> int:
    """Extract a preflighted archive under ``dest`` without aliasing or special-file semantics."""
    if _source_size(source) > MAX_ARCHIVE_BYTES:
        raise IngestError(
            f"Archive exceeds the {MAX_ARCHIVE_BYTES // (1024 * 1024)} MB compressed-size limit."
        )
    archive_source: BinaryIO
    if isinstance(source, (bytes, bytearray)):
        archive_source = io.BytesIO(source)
    else:
        # Direct callers may still hand us a raw py3.10 spool; the route normalizes at its own
        # boundary, and iobase_upload_file's docstring owns the why.
        archive_source = iobase_upload_file(source)
        archive_source.seek(0)
    try:
        zf = zipfile.ZipFile(archive_source)
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise IngestError(f"Not a valid ZIP archive: {exc}") from exc
    with zf:
        # Load-bearing order: this lexical/metadata pass completes before dest.resolve(), mkdir(),
        # ZipFile.open(), or builtins.open() can run.
        prepared = _preflight_zip(zf)
        dest_resolved = dest.resolve(strict=True)
        written = 0
        actual_total = 0
        for info, parts in prepared:
            if info.is_dir():
                continue
            target = dest_resolved.joinpath(*parts)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "xb") as out:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        actual_total += len(chunk)
                        if actual_total > MAX_UNCOMPRESSED_BYTES:
                            raise IngestError(
                                "Archive expanded beyond its declared verification budget."
                            )
                        out.write(chunk)
            except IngestError:
                raise
            except (OSError, RuntimeError, NotImplementedError, ValueError, zipfile.BadZipFile) as exc:
                raise IngestError(
                    f"Cannot extract archive entry {info.filename!r}: {exc}"
                ) from exc
            if not target.is_file():
                raise IngestError(
                    f"Archive entry {info.filename!r} reported as written but is not on disk "
                    "afterwards - refused."
                )
            written += 1
    return written


def _find_collection_root(dest: Path) -> Tuple[Path, List[str]]:
    """Locate the directory whose immediate children are the per-device dirs of ``show_*.txt`` files.

    Tolerates a wrapping folder in the ZIP (``my-export/<host>/show_*.txt``) and stray copies nested
    INSIDE a device folder (``core1/backup/show_version.txt`` — the engine's loader ignores those
    too). Returns ``(root, device_dir_names)``."""
    def fail_walk(exc: OSError) -> None:
        raise IngestError(
            "The collection could not be completely enumerated; no partial folder scan "
            "will be assessed."
        ) from exc

    candidates: List[Path] = []
    for dirpath, _dirnames, filenames in os.walk(dest, onerror=fail_walk, followlinks=False):
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


def run_collection_zip(source: bytes | bytearray | BinaryIO) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Extract the ZIP, run the engine over it, and return ``(snapshot_dict, ingest_report)``."""
    workdir = Path(tempfile.mkdtemp(prefix="assesshub_ingest_"))
    try:
        extracted = workdir / "extracted"
        extracted.mkdir()
        n_files = _safe_extract(source, extracted)
        return _assess_tree(extracted, n_files, workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


#: Roots the HTTP ingest-folder channel may read from. A client-supplied absolute path is the
#: caller naming a directory on the SERVER, so it has to be contained: unbounded, the route reads any
#: directory the process can reach (another engagement's captures, an old collection in Downloads,
#: a UNC share), parses it, and stores a snapshot the caller then reads back in full — cross-engagement
#: client evidence exfiltrated through a route documented as "the folder is only READ". Reading is the
#: exposure here, not writing. Default: the app's own directory tree, which is the documented field
#: shape (ADR-0004 — "on the stick the collection already sits beside the app"). Override with
#: ASSESSHUB_INGEST_ROOTS (os.pathsep-separated) for deployments that keep collections elsewhere.
_INGEST_ROOTS_ENV = "ASSESSHUB_INGEST_ROOTS"


def _allowed_ingest_roots() -> List[Path]:
    def lexical(raw_path: str) -> Path:
        return Path(os.path.abspath(os.path.normpath(os.path.expanduser(raw_path))))

    raw = os.environ.get(_INGEST_ROOTS_ENV, "").strip()
    if raw:
        roots: List[Path] = []
        for configured in (p.strip() for p in raw.split(os.pathsep) if p.strip()):
            normalized = configured.replace("/", "\\")
            if ("\x00" in configured or any(ord(ch) < 32 for ch in configured)
                    or normalized.startswith("\\\\")
                    or (os.name == "nt" and normalized.startswith("\\"))
                    or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", configured)):
                raise IngestError(f"{_INGEST_ROOTS_ENV} contains an unsafe remote/device root.")
            roots.append(lexical(configured))
        return roots
    # The bundle root on a stick, or the repo checkout in a dev/server install.
    return [Path(sys.argv[0]).resolve().parent if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[2]]


def _is_link_or_reparse(st: os.stat_result) -> bool:
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & reparse)


def _directory_identity(st: os.stat_result) -> Tuple[int, int]:
    """Stable identity used to pin a queued directory across its scan delay."""
    return int(st.st_dev), int(st.st_ino)


def _file_identity(st: os.stat_result) -> Tuple[int, int, int, int]:
    return int(st.st_dev), int(st.st_ino), int(st.st_size), int(st.st_mtime_ns)


def _stage_physical_tree(source: Path, destination: Path) -> Dict[str, Dict[str, Any]]:
    """Copy one fully scanned physical tree into private custody using stable, no-follow reads.

    The engine receives only ``destination``.  A link/junction swap after the HTTP preflight can
    therefore neither redirect the subprocess nor change the bytes it analyses.
    """
    destination.mkdir(parents=True, exist_ok=False)
    try:
        root_stat = os.lstat(source)
    except OSError as exc:
        raise IngestError("The collection changed before it could enter private custody.") from exc
    if _is_link_or_reparse(root_stat) or not stat.S_ISDIR(root_stat.st_mode):
        raise IngestError("The collection became a link or non-directory before custody.")

    bindings: Dict[str, Dict[str, Any]] = {}
    total = 0
    pending = [(source, destination, _directory_identity(root_stat))]
    while pending:
        current, target, expected_directory = pending.pop()
        try:
            current_stat = os.lstat(current)
        except OSError as exc:
            raise IngestError("A collection directory disappeared during custody copy.") from exc
        if (
            _is_link_or_reparse(current_stat)
            or not stat.S_ISDIR(current_stat.st_mode)
            or _directory_identity(current_stat) != expected_directory
        ):
            raise IngestError("A collection directory changed identity during custody copy.")
        target.mkdir(parents=True, exist_ok=True)
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            raise IngestError("The collection could not be completely copied into custody.") from exc
        for entry in entries:
            if _unsafe_component(entry.name):
                raise IngestError("The collection contains an unsafe filesystem entry.")
            path = Path(entry.path)
            try:
                before = os.lstat(path)
            except OSError as exc:
                raise IngestError("A collection entry disappeared during custody copy.") from exc
            if _is_link_or_reparse(before):
                raise IngestError("The collection became linked during custody copy.")
            if stat.S_ISDIR(before.st_mode):
                pending.append(
                    (path, target / entry.name, _directory_identity(before))
                )
                continue
            if not stat.S_ISREG(before.st_mode):
                raise IngestError("The collection contains a special filesystem entry.")
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(path, flags)
                with os.fdopen(fd, "rb") as handle:
                    opened = os.fstat(handle.fileno())
                    if _file_identity(opened) != _file_identity(before):
                        raise IngestError("A collection file changed while custody opened it.")
                    chunks: List[bytes] = []
                    read = 0
                    while True:
                        chunk = handle.read(1024 * 1024)
                        if not chunk:
                            break
                        read += len(chunk)
                        total += len(chunk)
                        if total > MAX_UNCOMPRESSED_BYTES:
                            raise IngestError(
                                "The collection exceeded its byte budget during custody copy."
                            )
                        chunks.append(chunk)
                    after_handle = os.fstat(handle.fileno())
                after_path = os.lstat(path)
            except IngestError:
                raise
            except OSError as exc:
                raise IngestError("A collection file could not enter private custody.") from exc
            if (
                _file_identity(after_handle) != _file_identity(opened)
                or _file_identity(after_path) != _file_identity(opened)
                or _is_link_or_reparse(after_path)
                or read != opened.st_size
            ):
                raise IngestError("A collection file changed while it entered private custody.")
            data = b"".join(chunks)
            relative = path.relative_to(source).as_posix()
            (target / entry.name).write_bytes(data)
            bindings[relative] = {
                "identity": _file_identity(opened),
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        try:
            after_directory = os.lstat(current)
        except OSError as exc:
            raise IngestError("A collection directory disappeared during custody copy.") from exc
        if (
            _is_link_or_reparse(after_directory)
            or _directory_identity(after_directory) != expected_directory
        ):
            raise IngestError("A collection directory changed during custody copy.")
    return bindings


def _resolve_and_scan(path: Any, *, contain: bool = False) -> Tuple[Path, int]:
    """Resolve a local collection folder and enforce the shared caps — they bound the ENGINE's
    work, not just archive extraction, so every local channel (ingest, redaction) applies them.

    ``contain`` restricts the folder to :func:`_allowed_ingest_roots`. It is ON for the HTTP channel,
    where the path arrives from a client, and OFF for the CLI/Atlas channels, where the operator IS
    the caller and naming any folder on their own machine is the whole point of ``--redact-folder``.
    """
    raw_path = str(path)
    if contain:
        # Refuse remote/device forms before is_dir() or resolve(): on Windows either call can
        # initiate an outbound SMB lookup and offer NTLM credentials to a caller-selected host.
        normalized = raw_path.replace("/", "\\")
        if ("\x00" in raw_path or any(ord(ch) < 32 for ch in raw_path)
                or normalized.startswith("\\\\")
                or (os.name == "nt" and normalized.startswith("\\"))
                or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", raw_path)):
            raise IngestError("Remote, device, or control-character paths cannot be ingested.")
        folder = Path(os.path.abspath(os.path.normpath(os.path.expanduser(raw_path))))
        roots = _allowed_ingest_roots()
        matching = [root for root in roots if folder == root or folder.is_relative_to(root)]
        if not matching:
            raise IngestError(
                "That folder is outside the directories this server may ingest from. Move the "
                f"collection under the app directory, or set {_INGEST_ROOTS_ENV} to the roots you "
                "want to allow.")
        root = max(matching, key=lambda candidate: len(candidate.parts))
        cursor = root
        try:
            for component in folder.relative_to(root).parts:
                if _unsafe_component(component):
                    raise IngestError(
                        "The requested folder uses a reserved or ambiguous path component.")
                cursor = cursor / component
                if _is_link_or_reparse(os.lstat(cursor)):
                    raise IngestError(
                        "The requested folder crosses a symlink or junction; ingest a physical "
                        "directory beneath an allowed root instead.")
        except FileNotFoundError:
            raise IngestError("Not a directory, or not readable.") from None
        except OSError as exc:
            raise IngestError("Not a directory, or not readable.") from exc
        if not folder.is_dir():
            raise IngestError("Not a directory, or not readable.")
        try:
            resolved_root = root.resolve(strict=True)
            resolved_folder = folder.resolve(strict=True)
        except OSError as exc:
            raise IngestError("Not a directory, or not readable.") from exc
        if not (resolved_folder == resolved_root
                or resolved_folder.is_relative_to(resolved_root)):
            raise IngestError("The requested folder escapes its allowed ingest root.")
        folder = resolved_folder
    else:
        folder = Path(raw_path).expanduser()
        if not folder.is_dir():
            # Do not echo a resolved path: differing errors become a filesystem-layout oracle.
            raise IngestError("Not a directory, or not readable.")
        folder = folder.resolve()

    try:
        root_stat = os.lstat(folder)
    except OSError as exc:
        raise IngestError("Not a directory, or not readable.") from exc
    if _is_link_or_reparse(root_stat) or not stat.S_ISDIR(root_stat.st_mode):
        raise IngestError("Not a physical directory, or not readable.")

    n_entries = 0
    n_files = 0
    total = 0
    pending = [(folder, _directory_identity(root_stat))]
    while pending:
        current, expected_identity = pending.pop()
        try:
            current_stat = os.lstat(current)
        except OSError as exc:
            raise IngestError(
                "A queued collection directory disappeared before it could be scanned."
            ) from exc
        if (
            _is_link_or_reparse(current_stat)
            or not stat.S_ISDIR(current_stat.st_mode)
            or _directory_identity(current_stat) != expected_identity
        ):
            raise IngestError(
                "A queued collection directory changed identity or became a link before scanning; "
                "no partial folder scan will be assessed."
            )
        try:
            with os.scandir(current) as iterator:
                for entry in iterator:
                    n_entries += 1
                    if n_entries > MAX_FILES:
                        raise IngestError(
                            f"Folder has more than the {MAX_FILES}-entry limit."
                        )
                    if _unsafe_component(entry.name):
                        raise IngestError(
                            "The collection contains a reserved or ambiguous filesystem entry.")
                    try:
                        entry_stat = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        raise IngestError(
                            "A collection entry could not be statted; no partial folder scan will "
                            "be assessed."
                        ) from exc
                    if _is_link_or_reparse(entry_stat):
                        raise IngestError(
                            "The collection contains a symlink or junction; all ingested evidence "
                            "must be physically contained under the allowed root.")
                    if stat.S_ISDIR(entry_stat.st_mode):
                        # On Windows ``DirEntry.stat()`` may report zero device/inode fields even
                        # though ``lstat(path)`` exposes the stable file ID. Pin from a fresh lstat,
                        # also closing the entry-stat -> enqueue link-swap window.
                        try:
                            queued_stat = os.lstat(entry.path)
                        except OSError as exc:
                            raise IngestError(
                                "A collection directory disappeared before it could be queued."
                            ) from exc
                        if (
                            _is_link_or_reparse(queued_stat)
                            or not stat.S_ISDIR(queued_stat.st_mode)
                        ):
                            raise IngestError(
                                "A collection directory became a link or changed type before it "
                                "could be queued."
                            )
                        pending.append(
                            (Path(entry.path), _directory_identity(queued_stat))
                        )
                        continue
                    if not stat.S_ISREG(entry_stat.st_mode):
                        raise IngestError(
                            "The collection contains an unsupported special filesystem entry."
                        )
                    n_files += 1
                    total += entry_stat.st_size
                    if total > MAX_UNCOMPRESSED_BYTES:
                        raise IngestError(
                            f"Folder holds more than the "
                            f"{MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MB limit."
                        )
        except IngestError:
            raise
        except OSError as exc:
            raise IngestError(
                "The collection could not be completely enumerated; no partial folder scan "
                "will be assessed."
            ) from exc
    if not n_files:
        raise IngestError("The folder is empty.")
    return folder, n_files


def run_collection_folder(path: Any, *, contain: bool = False) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Run the engine over a SERVER-LOCAL collection folder and return
    ``(snapshot_dict, ingest_report)`` — the portable-app channel (ADR-0004 P1).

    Read-only on the user's tree: devices.json, the template and every output live in a private
    temp workdir; the engine only READS ``--collection-dir``. The ZIP caps apply here too — they
    bound the engine's work, not just archive extraction.

    ``contain`` restricts the folder to :func:`_allowed_ingest_roots`. The HTTP route passes True,
    because there the path is chosen by the CLIENT and reading an arbitrary server directory is the
    exposure. It defaults False for the in-process/CLI callers, where the operator IS the caller and
    naming any folder on their own machine is the point (``--redact-folder``)."""
    folder, n_files = _resolve_and_scan(path, contain=contain)
    workdir = Path(tempfile.mkdtemp(prefix="assesshub_ingest_"))
    try:
        staged = workdir / "custody"
        bindings = _stage_physical_tree(folder, staged)
        if len(bindings) != n_files:
            raise IngestError(
                "The collection file count changed between preflight and private custody."
            )
        return _assess_tree(staged, n_files, workdir)
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


#: The marker a run leaves when it could NOT certify its output. ONE owner for the name (SSOT
#: Law 1): it is written here, tested for by the completeness report, and — the reason it must not
#: be a third literal — decides whether the report may claim the folder is safe to share.
UNSAFE_MARKER = "DO-NOT-SEND-NOT-REDACTED.txt"


def _mark_output_unsafe(out: Path, why: str) -> None:
    """Leave a loud on-disk marker when a run did NOT certify its output.

    Nothing is deleted (destroying evidence is the worse failure), but the files are named
    ``*_redacted*`` — they assert the exact property the run declined to certify, and stderr
    scrolls away. The marker is what a hurried engineer sees in the folder."""
    try:
        (out / UNSAFE_MARKER).write_text(
            "This folder is NOT safe to share.\n\n"
            f"Atlas refused to certify this run: {why}.\n"
            "The files here are named *_redacted* but that property was NOT verified, and at\n"
            "least part of the set may contain real client data.\n\n"
            "Delete them or re-run the redaction, and do not send anything from this folder.\n",
            encoding="ascii")
    except OSError:
        pass  # best-effort: never mask the real error with a marker-write failure


#: Lines in the engine's own output that explain why a deliverable is absent: a writer that raised
#: (``… write failed: …``), an optional library that is not installed (``… skipped: python-docx …``),
#: a phase that was skipped, a PPDIOO document gate that refused. Matched GENERICALLY rather than
#: per-writer: the produced-vs-expected diff below is the authoritative signal, so these lines only
#: have to EXPLAIN a gap, never to detect one — which keeps the check immune to message drift.
_ENGINE_GAP_RE = re.compile(r"write failed|skipped:|\[SKIP\] Phase|\[GATE REFUSED\]", re.I)

#: First and last lines of the note `_mark_output_incomplete` writes. Together they are the
#: proof-of-authorship for `_clear_stale_incomplete_marker`: a note the engineer appended to no
#: longer ends with the trailer, so annotating it makes it un-deletable rather than deleting the
#: annotation. The note itself invites exactly that ("Delete this file once you have done so").
_INCOMPLETE_MARKER = "INCOMPLETE-SET.txt"
_INCOMPLETE_FALLBACK = "INCOMPLETE-SET-ATLAS.txt"
_INCOMPLETE_HEADER = "This deliverable set is INCOMPLETE."
_INCOMPLETE_TRAILER = "-- written by Atlas; delete once you have acted on it --"



def _engine_filenames(stem: str) -> frozenset:
    """Exactly the names an engine run writes for ``stem``: the family, plus its own sidecars."""
    from cisco_toolkit.docmeta import cli_artifacts

    return frozenset([f for _k, _n, f in cli_artifacts(stem)] +
                     [stem + s for s in (".snapshot.json", ".run_manifest.json",
                                         ".phase_timings.json")])


def _written_by_this_run(p: Path, engine_names: frozenset,
                         pre_existing: Dict[str, Tuple[float, int]]) -> bool:
    """Did the run that just finished write ``p``?

    New name = yes. Otherwise the file must be one the engine actually writes AND differ from what
    stood there before. The membership test is against that CLOSED set of names, not a
    stem-prefix: prefixing re-admitted anything the engineer happened to keep alongside the set,
    and a name like ``Assessment_redacted_IP_CROSSWALK.xlsx`` — a pseudonym-to-real-IP crosswalk,
    the one file that must never travel — would have been listed under the share-safe banner if it
    were saved while the (multi-minute) run was in flight. The original rule excluded every
    pre-existing name unconditionally; this preserves that for everything except the names the
    engine demonstrably owns.

    "Differ" is deliberately INEQUALITY, not a later timestamp. A strictly-greater test assumes
    the clock only moves forward, and this app runs on air-gapped field laptops and FAT32 sticks,
    where it does not: a manual clock correction, a DST change or carrying the stick across a
    timezone can make previously-written files read back as NEWER, at which point every document
    of a perfect run reports as missing. A false alarm on a good run is the failure this codebase
    has already paid for once (see the _DOC_KEYS note below), so the test must not depend on the
    direction the clock moved. Size is compared alongside mtime so a rewrite inside one coarse
    timestamp tick is still seen."""
    if not engine_names:
        # NO census supplied at all. The caller is not claiming to know what this run wrote, so
        # there is nothing here to contradict and staleness cannot be inferred from an empty set.
        # This is the contract stated in _assert_redaction_phases_ran's docstring — "with neither
        # supplied (the direct-call contract tests use that form) every file reads as this run's,
        # which is the pre-existing behaviour" — and the code did the opposite: an empty
        # `engine_names` made the membership test below fail for EVERY path, so the guard reported a
        # freshly written ledger in a fresh temp dir as "unchanged from before this run started, so
        # it belongs to an EARLIER run". A guard that refuses everything is not strict, it is broken,
        # and it refuses hardest exactly where it has the least information.
        #
        # This does NOT weaken the real path: `_engine_filenames()` always returns at least the
        # three sidecar names, so the production caller's census is never empty and still gets the
        # full closed-set membership test below.
        return True
    if p.name not in engine_names:
        return False
    prev = pre_existing.get(p.name)
    if prev is None:
        return True
    try:
        st = p.stat()
    except OSError:
        return False
    return (st.st_mtime, st.st_size) != prev


def _prior_set_in(out: Path, stem: str) -> List[str]:
    """Canonical engine output already sitting in ``out`` before this run starts.

    The engine's own sidecars count, not only the family documents. ``.snapshot.json`` is the
    fullest record of another engagement that exists — the entire assessment, and redaction keeps
    hostnames — while ``.run_manifest.json`` / ``.phase_timings.json`` describe THAT run, not this
    one. Checking only ``cli_artifacts`` let all three ride inside a delivery unlisted: they are
    not family documents, so ``_family_state`` never names them either, and a run that does not
    rewrite one leaves the other job's copy under this job's name. ``_engine_filenames`` already
    owns the closed set of names an engine run writes, so ask it rather than restate the list."""
    return sorted(f for f in _engine_filenames(stem) if (out / f).is_file())


def _refuse_reused_out_dir(out: Path, stem: str) -> None:
    """Refuse, BEFORE any work, to render into a folder that already holds a deliverable set.

    This is the whole answer to cross-job contamination, and it is a refusal rather than a repair
    because of where the hazard actually comes from. If two engagements share an output folder and
    one writer fails on the second run, the first job's document is left sitting under the exact
    name the second job's document should have had — and redaction KEEPS hostnames and site codes,
    so that file identifies another client inside this delivery. Every after-the-fact treatment
    was worse: leaving it warns about a file the engineer can plainly see and therefore disbelieves;
    moving it aside mutates the folder, contradicts the run manifest the engine has already sealed
    over the pre-move contents, and strips a GOOD same-job document out of an otherwise complete
    set. Refusing costs milliseconds instead of ten minutes, removes the hazard's precondition
    instead of mitigating its consequence, and enforces the habit README-FIELD.txt already
    prescribes. ``--reuse-out`` is the deliberate escape, and it is deliberately a decision the
    engineer has to make with the folder's contents named in front of them.

    The prior set is NOT called "redacted" when ``UNSAFE_MARKER`` sits beside it: that marker means
    an earlier run could not certify those very files, so describing them as redacted — in the same
    sentence that offers ``--reuse-out`` — talks the engineer into the one path that carries them
    forward into a delivery."""
    prior = _prior_set_in(out, stem)
    if not prior:
        return
    if (out / UNSAFE_MARKER).is_file():
        raise IngestError(
            f"{out} holds {UNSAFE_MARKER} and a deliverable set ({len(prior)} file(s), e.g. "
            f"{', '.join(prior[:3])}) that an earlier run could NOT certify as redacted - those "
            f"files may contain real client data. Do not render into this folder: any document "
            f"this run fails to write would leave the uncertified copy in place under the right "
            f"name, inside a set you are about to send. Move or delete that output first, then "
            f"use an EMPTY folder. (--reuse-out is deliberately NOT offered here.)")
    raise IngestError(
        f"{out} already holds a redacted deliverable set ({len(prior)} file(s), e.g. "
        f"{', '.join(prior[:3])}). If it is from ANOTHER job, its documents still carry that "
        f"client's hostnames and site codes, and any document this run fails to write would "
        f"leave that client's copy sitting in this delivery under the right name. Use an EMPTY "
        f"folder for each job. To render into this one anyway (for example re-running the same "
        f"job after a short set), add --reuse-out.")


def _unusable(p: Path) -> str:
    """Why ``p`` cannot be sent, or "" if it looks like a real document.

    Existence is NOT delivery. Every engine writer truncates its target and then writes, so a
    stick that fills up mid-render leaves a 0-byte ``_explorer.html`` (or a half-written .docx)
    carrying a brand-new timestamp — and the engine, being fail-soft, logs a warning and exits 0.
    Checking only for the filename would certify that folder as complete: the ORIGINAL bug with a
    fresh coat of paint. Worse on a re-run, where the truncate destroys the good copy from the
    previous run.

    The structural test is `docmeta.validate_artifact`, which the ENGINE already applies to the
    same bytes before admitting them to custody — one owner for "does this document actually
    open", so a new family member cannot be left behind. What stood here was a hand-listed
    `(".docx", ".pptx", ".xlsx")`: every member of `docmeta.CLI_ARTIFACT_SUFFIX` is a zip EXCEPT
    `_explorer.html`, and for that one the ONLY test was size > 0. Measured: a 36-byte
    `<!doctype html><html><body>truncated` produced ``missing == []``, no INCOMPLETE-SET.txt,
    receipt status "verified" and exit 0 - the repo's contract for "complete + verified, safe to
    send" - while `validate_artifact` on the very same file returned
    ``(False, 'HTML document is missing its root/open or closing tag')``.

    The 0-byte case keeps its own sentence because it names the CAUSE the engineer can act on (a
    full disk), which "empty file" does not."""
    try:
        if p.stat().st_size == 0:
            return "0 bytes - the write was cut short (a full disk does this)"
    except OSError as e:
        # strerror only: the full OSError repr carries the absolute path, and this string is
        # copied into a note that sits in the folder the engineer zips and sends.
        return f"cannot be read back ({e.__class__.__name__}: {e.strerror or 'unreadable'})"
    from cisco_toolkit.docmeta import validate_artifact

    try:
        ok, reason = validate_artifact(str(p))
    except Exception as e:                       # a validator that raises must not certify
        return f"could not be structurally validated ({e.__class__.__name__}) - do not send it"
    if ok:
        return ""
    # `reason` embeds the exception text for a malformed container, and that text carries the
    # ABSOLUTE path - the same WEBAP-01 disclosure the OSError branch above is written to avoid,
    # into a note that travels to the client. Scrub the path before it is quoted.
    absolute = os.path.abspath(str(p))
    detail = str(reason).replace(absolute, p.name).replace(os.path.dirname(absolute), "<out>")
    return f"{detail} - it will not open"


def _family_state(stem: str, out: Path, produced: set) -> List[Dict[str, str]]:
    """Every family document this run did NOT deliver, in reading order, each with WHY.

    Every deliverable writer in the engine is fail-soft — wrapped in ``try/except`` that only
    ``logger.warning``s and continues, so the workbook and snapshot still save when an optional
    library is missing (a deliberate design, and out of scope to change). The cost is that a run
    which rendered all but two of its documents exits 0 and reports them as the whole family.
    ``docmeta`` owns what the family IS, so the expected set is DERIVED from it rather than
    restated here — a new writer cannot leave this check behind. (No count is restated anywhere
    in this module: ``docmeta.CLI_ARTIFACT_SUFFIX`` is the owner, per SSOT Law 1.)

    Three outcomes, because they call for different actions and lumping them together produced a
    report that read as wrong: ``absent`` (nothing there), ``unusable`` (a file exists but is
    empty or will not open), and ``stale`` — present and openable but left by an EARLIER run.
    Stale is only reachable under ``reuse_out``; without it, a folder already holding a
    deliverable set is refused before the engine starts."""
    from cisco_toolkit.docmeta import cli_artifacts

    gaps = []
    for key, name, filename in cli_artifacts(stem):
        p = out / filename
        if not p.is_file():
            state, detail = "absent", "not written"
        elif filename not in produced:
            state, detail = "stale", ("left by an EARLIER run into this folder - this run did not "
                                      "rewrite it, so check which job it belongs to")
        else:
            why = _unusable(p)
            if not why:
                continue
            state, detail = "unusable", why
        gaps.append({"key": key, "name": name, "filename": filename,
                     "state": state, "detail": detail})
    return gaps


def _scrub_paths(text: str, workdir: Path, *others: Path) -> str:
    """Strip absolute paths out of engine output before this module reports it.

    Both channels surface the tail: to a (possibly remote, unauthenticated) uploader through the
    API 500 detail AND the success report (WEBAP-01), and to whoever receives the folder the field
    engineer zips. Scrubbing only the private workdir was not enough — the engine is pointed at
    ``--collection-dir``, which is the CALLER's absolute path, so one breadcrumb naming it
    (``... 'D:\\Acme-Bank-Merger\\collection\\core1\\show_run.txt'``) disclosed the server's
    filesystem layout and the engagement's own folder name. ``_engine_gap_lines`` already scrubbed
    three roots; this sibling scrubbed one. The workdir keeps its distinct ``<workdir>`` label
    because it is the one path whose mention is expected (the engine runs there and writes there),
    and it is replaced FIRST so a path nested under it is scrubbed by prefix."""
    text = (text or "").replace(str(workdir), "<workdir>")
    for p in others:
        text = text.replace(str(p), "<path>")
    return text


def _engine_gap_lines(engine_output: str, scrub: Tuple[Path, ...], limit: int = 8) -> List[str]:
    """The engine's own explanation for a gap: its warning/refusal lines, de-duplicated and
    capped. Advisory context for the diff above — never the detector.

    Paths are stripped first. These lines are copied into a note that TRAVELS: the folder is
    zipped and sent to the client, so an engine breadcrumb like
    ``[Errno 28] ... 'D:\\Acme-Bank-Merger\\share\\...'`` would carry the engagement name (and the
    server's layout, the WEBAP-01 concern) into the share-safe set."""
    lines: List[str] = []
    for raw in (engine_output or "").splitlines():
        line = raw.strip()
        for path in scrub:
            line = line.replace(str(path), "<path>")
        if line and _ENGINE_GAP_RE.search(line) and line not in lines:
            lines.append(line)
        if len(lines) >= limit:
            break
    return lines


def _mark_output_incomplete(out: Path, gaps: List[Dict[str, str]],
                            reasons: List[str]) -> Optional[Path]:
    """Leave an on-disk note when the set is SHORT of the full family. Returns the path actually
    written, or None — the caller must not promise a file that is not there.

    Deliberately NOT the ``DO-NOT-SEND`` marker: a missing document is not a leak, and crying leak
    over one is the false alarm that teaches an engineer to ignore both markers. The file exists
    for the same reason its sibling does — stderr scrolls away, and the folder is what a hurried
    engineer actually looks at before zipping it.

    **The safety line is CONDITIONAL, and that is the point.** This note used to open with
    "Everything in this folder IS redacted and safe to share" unconditionally. That sentence is
    false in a reachable state: a run whose redaction check FAILS leaves ``UNSAFE_MARKER`` and its
    unredacted documents on disk (nothing is deleted, by design); re-running into the same folder
    with ``--reuse-out`` — which the reuse refusal itself suggests — and losing one writer leaves
    that earlier run's UNREDACTED file under the canonical name, reported only as ``stale``. The
    note then asserted the folder was safe over a document that was not. A false *safe* claim is
    the mirror of the false *leak* claim this module is organised to avoid, and it is the worse
    of the two: the leak alarm costs a re-run, this one ships client data. So the claim is made
    only when the marker is absent, and inverted when it is present.

    An existing file of that name that Atlas did NOT write is never clobbered (it could be the
    engineer's own record of what they sent); the note goes to a fallback name instead."""
    unsafe = (out / UNSAFE_MARKER).is_file()
    stale = [g for g in gaps if g["state"] == "stale"]
    body = [_INCOMPLETE_HEADER, ""]
    if unsafe:
        body += [f"DO NOT SEND THIS FOLDER. It also holds {UNSAFE_MARKER}, left by a run whose",
                 "redaction could not be certified - so files here may contain REAL client data.",
                 "Read that file first; the list below is only about which documents are missing."]
    else:
        body += ["What this run wrote IS redacted - but the engine did not produce the whole",
                 "document family, and a partial set can read as the full one."]
    body += ["", "Not delivered by this run:"]
    body += [f"  - {g['name']}  ({g['filename']})\n      {g['state'].upper()}: {g['detail']}"
             for g in gaps]
    if stale:
        body += ["", "STALE means a file from an EARLIER run into this folder is sitting under the",
                 "name this run's document should have had. This run did not write it, so it is NOT",
                 "covered by this run's redaction check. Two ways that bites: if the earlier run was",
                 "for a DIFFERENT job it identifies another client (redaction keeps hostnames and",
                 "site codes), and if the earlier run FAILED its redaction check the file may be",
                 "UNREDACTED. Check which run it came from, or delete it and re-run into an EMPTY",
                 "folder."]
    if reasons:
        body += ["", "The engine reported:"] + [f"  {r}" for r in reasons]
    body += ["", "Either re-run the redaction, or tell the recipient which documents are not",
             "included.", "", _INCOMPLETE_TRAILER, ""]
    target = out / _INCOMPLETE_MARKER
    if _foreign(target):
        target = out / _INCOMPLETE_FALLBACK
        if _foreign(target):
            return None            # both taken by files that are not ours; overwrite neither
    try:
        target.write_text("\n".join(body), encoding="ascii", errors="replace")
        return target
    except OSError:
        return None  # best-effort: a marker-write failure must never mask the report itself


def _ours(p: Path) -> bool:
    """Is ``p`` an Atlas incompleteness note, still exactly as Atlas left it?"""
    try:
        text = p.read_text(encoding="ascii", errors="replace")
    except OSError:
        return False
    return text.startswith(_INCOMPLETE_HEADER) and text.rstrip().endswith(_INCOMPLETE_TRAILER)


def _foreign(p: Path) -> bool:
    """Does something stand at ``p`` that Atlas must not overwrite? A directory counts (and is why
    the write is attempted rather than assumed: the OSError path used to leave stderr promising a
    note that was never created)."""
    return p.exists() and not (p.is_file() and _ours(p))


def _clear_stale_incomplete_marker(out: Path) -> None:
    """Drop a previous run's incompleteness note once a run HAS produced the full family —
    a marker that outlives its cause is the same lie in the other direction.

    Only a note that is byte-for-byte still Atlas's own is removed. If the engineer annotated it
    (the note invites them to), it no longer ends with the trailer and is left alone: the standing
    lesson here is that a cleanup routine destroying the record it was meant to manage is the
    expensive failure, so the guard errs towards keeping the file."""
    for name in (_INCOMPLETE_MARKER, _INCOMPLETE_FALLBACK):
        marker = out / name
        try:
            if marker.is_file() and _ours(marker):
                marker.unlink()
        except OSError:
            pass


#: The engine's redaction phases. `_run_phase` (COLLECT_PARSE_V3_23_0.py:1383) LOGS AND CONTINUES
#: on any exception "so the workbook still saves" — so a redaction failure leaves the workbook
#: unredacted while `redact_snapshot` (a direct call) still succeeds and the snapshot stays clean.
#: Proven by fault injection: real serials and 9 private addresses shipped in Assessment.xlsx while
#: the verified snapshot was spotless and the run exited 0. Checking only the snapshot inspects the
#: one artifact that CANNOT fail; these phases are where it actually breaks.
_REDACTION_PHASES = ("redact collected dataclasses", "redact workbook cells")


def _phase_rows(data: Any) -> List[dict]:
    """The timed-phase rows out of a ``.phase_timings.json`` sidecar.

    The engine writes a DICT — ``{"n_devices": …, "workers": …, "total_seconds": …,
    "phases": [{phase, seconds, ok}]}`` (``COLLECT_PARSE_V3_23_0._stage_finalize``). This was read as
    if the file were the bare LIST of rows, so iterating it yielded the dict's KEYS, ``str.get``
    raised ``AttributeError``, and the defensive ``except`` below swallowed it — the sidecar arm
    never fired on a real run, leaving the stderr scrape as the only live signal for a failed
    redaction phase. A bare list is still accepted so the parser is not the fragile half again."""
    if isinstance(data, dict):
        data = data.get("phases")
    return [row for row in (data or []) if isinstance(row, dict)]


def _phase_ok(value: Any) -> bool:
    """True only when the ledger POSITIVELY records success.

    Not `value is not False`: the ledger is JSON written by another program, and `0`, `"false"`,
    `null` and a missing key all have to read as "not a success". Anything this function cannot
    positively confirm is treated as unverified by the caller and refuses — the whole point of the
    rewrite below is that silence must never mean "fine"."""
    return value is True


def _assert_redaction_phases_ran(out_xlsx: Path, engine_output: str,
                                 engine_names: frozenset = frozenset(),
                                 pre_existing: Optional[Dict[str, Tuple[float, int]]] = None
                                 ) -> None:
    """Refuse unless BOTH redaction phases are positively confirmed to have run and succeeded.

    Two independent signals, because either alone can go missing: the phase-ledger sidecar and the
    engine's own ``[SKIP] Phase …`` line on stderr.

    **This fails CLOSED, and that is the point.** It previously refused only on an explicit
    ``ok is False`` and let every other reading through, so a ledger that could not be understood —
    a renamed ``phases`` key, rows keyed by name, a truncated file, a phase that never ran at all —
    was indistinguishable from a clean run. That is the same silent-degrade the dict/list parse bug
    produced, one level up: the guard stops firing and nothing says so. Both phases are
    unconditional under ``--redact`` (``COLLECT_PARSE_V3_23_0.py:2008`` and ``:2575``) and this
    caller always passes ``--redact``, so a missing row is genuinely anomalous, never routine.

    A sidecar left by an EARLIER run is not evidence, and — unlike an absent one — it REFUSES.
    ``--reuse-out`` renders into a folder that already holds one, so on every reuse run the
    previous job's ledger sits under this run's name, and an ``ok: true`` ledger from a run that
    DID redact would otherwise certify a run whose redaction phase failed soft. Absence is
    NOT tolerated by this code — and the absent-ledger branch is UNREACHABLE in production, which is
    the honest description of its status. `ingest` raises on a non-zero engine exit ~28 lines before
    this check runs, and every engine path that omits the ledger exits non-zero, so no caller can
    observe this refusal. A producer-side escalation making the ledger mandatory was tried on
    2026-07-31 and reverted: it turned a fully successful run into `[INCOMPLETE]` under an ordinary
    file lock while buying this dead branch nothing (see the note at COLLECT_PARSE_V3_23_0.py's
    "Phase timings" emit). Whether to restore tolerance here is therefore a TIDINESS question, not a
    safety one; do not "fix" it by making the producer strict. A stale ledger is a different failure, and
    is the anomalous case rather than the routine one: the engine reached this check only by
    exiting 0, and it writes the sidecar after the redaction phases, so a normal reuse run
    rewrites it. ``engine_names``/``pre_existing`` are the caller's pre-run census; with neither
    supplied (the direct-call contract tests use that form) every file reads as this run's, which
    is the pre-existing behaviour."""
    failed, unverified = [], []
    timings = Path(str(out_xlsx)[: -len(".xlsx")] + ".phase_timings.json")
    if not timings.is_file():
        unverified.append(
            "the mandatory phase ledger is absent, so successful redaction phases are unproved"
        )
    elif not _written_by_this_run(timings, engine_names, pre_existing or {}):
        unverified.append("the phase ledger in the output folder is unchanged from before this run "
                          "started, so it belongs to an EARLIER run and this run left none of its "
                          "own")
    elif timings.is_file():
        rows: Optional[List[dict]] = None
        try:
            rows = _phase_rows(json.loads(timings.read_text(encoding="utf-8", errors="replace")))
        except (OSError, ValueError, TypeError, AttributeError) as e:
            unverified.append(f"the phase ledger could not be read ({type(e).__name__})")
        if rows is not None:
            seen: Dict[str, dict] = {}
            for row in rows:
                phase_name = str(row.get("phase", "")).lower()
                if phase_name not in _REDACTION_PHASES:
                    continue
                if phase_name in seen:
                    unverified.append(
                        f"the phase ledger repeats '{phase_name}', so its result is ambiguous"
                    )
                    continue
                seen[phase_name] = row
            for phase in _REDACTION_PHASES:
                if phase not in seen:
                    unverified.append(f"the phase ledger has no '{phase}' row, so there is no "
                                      f"evidence that phase ran")
                elif not _phase_ok(seen[phase].get("ok")):
                    failed.append(phase)
    low = (engine_output or "").lower()
    for phase in _REDACTION_PHASES:
        if f"[skip] phase '{phase}'" in low and phase not in failed:
            failed.append(phase)
    if failed:
        raise EngineRunError(
            f"REDACTION PHASE FAILED inside the engine ({', '.join(sorted(failed))}). The workbook "
            f"is very likely UNREDACTED even though the snapshot looks clean - this is the silent "
            f"failure the check exists for. Do NOT send anything from this run.")
    if unverified:
        raise EngineRunError(
            f"REDACTION COULD NOT BE VERIFIED - {'; '.join(unverified)}. The scrub may well have "
            f"run, but this check cannot confirm it, and an unverifiable redaction is treated as a "
            f"failed one. Do NOT send anything from this run until it is re-run or checked by hand.")


def _assert_mandatory_completion(
    out_xlsx: Path,
    engine_names: frozenset,
    pre_existing: Dict[str, Tuple[float, int]],
) -> None:
    """Require the current run's sealed, positive producer-finalization ledger."""
    manifest_path = Path(str(out_xlsx)[: -len(".xlsx")] + ".run_manifest.json")
    if (
        not manifest_path.is_file()
        or not _written_by_this_run(manifest_path, engine_names, pre_existing)
    ):
        raise EngineRunError(
            "RUN COMPLETION COULD NOT BE VERIFIED - the current run produced no mandatory "
            "manifest ledger. Process exit and stderr silence are not proof of success."
        )
    try:
        from cisco_toolkit import manifest as manifest_mod

        verified = manifest_mod.verify_file(
            str(manifest_path), artifacts_dir=str(manifest_path.parent)
        )
        if verified.get("ok") is not True:
            raise ValueError(verified.get("reason") or "manifest verification failed")
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        metadata = manifest_data.get("metadata")
        finalization = (
            metadata.get("producer_finalization")
            if isinstance(metadata, dict)
            else None
        )
        redaction = metadata.get("redaction") if isinstance(metadata, dict) else None
        if not isinstance(finalization, dict):
            raise ValueError("manifest has no producer finalization ledger")
        if (
            finalization.get("mandatory_prerequisites") != "complete"
            or finalization.get("failed_mandatory") != []
        ):
            raise ValueError("mandatory producer phases were not positively complete")
        if (
            not isinstance(redaction, dict)
            or redaction.get("requested") is not True
            or redaction.get("status") != "verified"
        ):
            raise ValueError("producer redaction verification is not positive")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise EngineRunError(
            f"RUN COMPLETION COULD NOT BE VERIFIED - {exc}. A quiet process is never treated "
            "as success; no output was certified."
        ) from exc


def _iter_evidence_strings(node: Any, path: str = ""):
    """Compatibility diagnostic: yield every string value without schema-wide exemptions.

    The independent verifier also scans dictionary keys; this iterator remains for the historical
    fixture-coverage regression, whose denominator counts string values only.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _iter_evidence_strings(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _iter_evidence_strings(value, f"{path}[{index}]")
    elif isinstance(node, str):
        yield path, node


def _assert_scrubbed(snap_path: Path) -> int:
    """Compatibility wrapper around the independent, all-class snapshot verifier."""
    try:
        return redaction_verify.verify_shareable_artifacts(snap_path, ())
    except redaction_verify.RedactionVerificationError as exc:
        raise EngineRunError(
            f"REDACTION DID NOT APPLY - the snapshot could not be read back or safely verified: "
            f"{exc}. The output is NOT safe to share; nothing was deleted, so inspect it before "
            "sending anything."
        ) from exc


def _assert_shareable_artifacts_scrubbed(snap_path: Path, paths: List[Path]) -> int:
    """Independently scan the snapshot and every current-run engine shareable artifact."""
    try:
        return redaction_verify.verify_shareable_artifacts(snap_path, paths)
    except redaction_verify.RedactionVerificationError as exc:
        raise EngineRunError(
            f"REDACTION POSTCONDITION FAILED - {exc}. At least one current-run shareable "
            "artifact is unsafe or unverifiable. Do NOT send anything from this run."
        ) from exc


def _certify_shareable_artifacts(
    snap_path: Path, paths: List[Path]
) -> Dict[str, str]:
    """Return digests of the exact independently verified bytes."""
    try:
        return redaction_verify.certify_shareable_artifacts(snap_path, paths)
    except redaction_verify.RedactionVerificationError as exc:
        raise EngineRunError(
            f"REDACTION POSTCONDITION FAILED - {exc}. At least one current-run shareable "
            "artifact is unsafe or unverifiable. Do NOT send anything from this run."
        ) from exc


def _stable_regular_sha256(path: Path) -> str:
    try:
        before = os.lstat(path)
        if _is_link_or_reparse(before) or not stat.S_ISREG(before.st_mode):
            raise OSError("not a physical regular file")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if _file_identity(opened) != _file_identity(before):
                raise OSError("identity changed while opening")
            digest = hashlib.sha256()
            read = 0
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                read += len(chunk)
                digest.update(chunk)
            after_handle = os.fstat(handle.fileno())
        after_path = os.lstat(path)
        if (
            _file_identity(after_handle) != _file_identity(opened)
            or _file_identity(after_path) != _file_identity(opened)
            or _is_link_or_reparse(after_path)
            or read != opened.st_size
        ):
            raise OSError("identity changed during digest")
        return digest.hexdigest()
    except OSError as exc:
        raise EngineRunError(
            f"{path.name} changed after verification; refusing to certify or promote the set."
        ) from exc


_REDACTION_RECEIPT = "Assessment_redacted.redaction.json"


def _promote_verified_delivery(
    stage: Path,
    out: Path,
    current_paths: List[Path],
    engine_names: frozenset,
    verifier_proof: Dict[str, str],
) -> Tuple[List[str], Optional[str]]:
    """Promote one staged generation; an atomic receipt is the coherent-set commit point."""
    for name, expected in verifier_proof.items():
        if _stable_regular_sha256(stage / name) != expected:
            raise EngineRunError(
                f"{name} no longer matches the independently verified bytes; nothing was promoted."
            )

    all_proof = {
        path.name: _stable_regular_sha256(path)
        for path in current_paths
    }
    run_id = uuid.uuid4().hex
    rollback = out.parent / f".{out.name}.replaced-{run_id}"
    moved_old: List[Tuple[Path, Path]] = []
    promoted: List[Path] = []
    out.mkdir(parents=True, exist_ok=True)
    try:
        # Preserve prior generation markers with the generation they describe. Keeping an old
        # failure marker beside a newly certified receipt makes the canonical folder contradict
        # itself even though the failed staged bytes were never promoted.
        old_names = set(engine_names) | {_REDACTION_RECEIPT, UNSAFE_MARKER}
        for name in sorted(old_names):
            old = out / name
            if not old.exists():
                continue
            rollback.mkdir(parents=True, exist_ok=True)
            saved = rollback / name
            os.replace(old, saved)
            moved_old.append((old, saved))
        for path in sorted(current_paths, key=lambda item: item.name):
            destination = out / path.name
            os.replace(path, destination)
            promoted.append(destination)
        # Recheck after promotion.  The receipt is written LAST and atomically renamed: without a
        # matching receipt the visible canonical files make no verified/coherent-set claim.
        for destination in promoted:
            if _stable_regular_sha256(destination) != all_proof[destination.name]:
                raise EngineRunError(
                    f"{destination.name} changed during coherent-set promotion."
                )
        receipt = {
            "schema": 1,
            "status": "verified",
            "run_id": run_id,
            "files": all_proof,
            "independent_verifier": verifier_proof,
        }
        receipt_tmp = out / f".{_REDACTION_RECEIPT}.{run_id}.tmp"
        receipt_tmp.write_text(
            json.dumps(receipt, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(receipt_tmp, out / _REDACTION_RECEIPT)
    except Exception:
        recovery = out.parent / f".{out.name}.failed-promotion-{run_id}"
        recovery.mkdir(parents=True, exist_ok=True)
        for path in promoted:
            if path.exists():
                try:
                    os.replace(path, recovery / path.name)
                except OSError:
                    pass
        for original, saved in reversed(moved_old):
            if saved.exists():
                try:
                    os.replace(saved, original)
                except OSError:
                    pass
        raise
    return (
        sorted([path.name for path in promoted] + [_REDACTION_RECEIPT]),
        str(rollback) if moved_old else None,
    )


#: The engine's own record of the opt-in raw-capture scrub (Phase 40,
#: ``COLLECT_PARSE_V3_23_0.py:3271-3278``). Unlike every other redaction step it is NOT a
#: ``_run_phase``: it leaves no row in the phase ledger, so ``_REDACTION_PHASES`` cannot see it,
#: and its failure line matches neither ``_ENGINE_GAP_RE`` nor the ``[SKIP] Phase`` scrape. These
#: two lines are the only evidence that exists for whether it ran.
_SCRUB_OK_RE = re.compile(r"redact-collection: scrubbed secret values in (\d+) of (\d+) "
                          r"raw capture file", re.I)
_SCRUB_FAIL_RE = re.compile(r"redact-collection failed", re.I)


def _is_raw_capture(path: Path) -> bool:
    """Is ``path`` a raw capture the scrub owns, by the SAME structural rule the producer and the
    independent verifier apply?

    All three used to test ``endswith(".txt")``, and three matchers that agree with each other are
    one matcher: ``backup-config.cfg`` and ``show_tech-support.log`` sitting beside a scrubbed
    ``show_version.txt`` were never scrubbed, never scanned, never counted, and the run still
    printed SCRUBBED and exited 0. The name half is asked of ``redaction_verify`` (one owner for
    the rule, and this module is the census, not a second opinion); the content half - a NUL byte
    means binary, so it is not a capture - is read here exactly as both other sites read it.

    Unreadable is NOT "not a capture": it stays counted, so a capture the scrub could not open
    still shows up as a shortfall instead of quietly leaving the denominator."""
    if redaction_verify.is_uncoverable_capture(path.name):
        return False
    try:
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    return True
                if b"\x00" in chunk:
                    return False
    except OSError:
        return True


def _count_raw_captures(root: Path) -> int:
    """How many raw captures the scrub SHOULD have scanned under ``root``.

    Matches ``redact_collection_dir``'s selector by RULE rather than by copied expression (see
    ``_is_raw_capture``), recursive from the collection root the engine was pointed at, because
    the whole value of the number is comparing like with like."""
    def fail_walk(exc: OSError) -> None:
        raise IngestError(
            "The raw capture folder could not be completely enumerated; scrub coverage is "
            "unverifiable."
        ) from exc

    n = 0
    for dirpath, _dirnames, filenames in os.walk(root, onerror=fail_walk, followlinks=False):
        n += sum(1 for f in filenames if _is_raw_capture(Path(dirpath) / f))
    return n


def _collection_scrub_outcome(engine_output: str, present: int) -> Tuple[bool, str]:
    """``(verified, detail)`` for the opt-in raw-capture secret scrub — what HAPPENED, never the
    flag that was passed in.

    This was reported straight off the argument (``bool(redact_collection)``), which is the one
    thing that cannot be wrong: it echoed the request back as though it were the result. The
    difference between the two is the enable secrets, SNMP communities and pre-shared keys still
    sitting in the raw captures on the stick, under an exit code of 0.

    Three ways the scrub can fall short, and none of them is loud on its own:
    ``redact_collection_dir`` skips a capture it cannot read and carries on (``logger.debug``);
    the whole phase is wrapped in a log-and-continue ``except``; and the phase runs after the
    manifest seal, so nothing downstream depends on it. So the counts are read back and compared
    with what is actually in the folder — ``scanned`` covers only the files it could open, and a
    shortfall means captures were left untouched.

    The FULL engine output is searched, not the 12-line tail: Phase 40 is followed by the perf
    sidecar and the closing banner, so its line is routinely pushed out of the tail. The counts are
    extracted rather than the line copied — the engine's line names the collection directory, and
    this string is reported (WEBAP-01)."""
    if _SCRUB_FAIL_RE.search(engine_output or ""):
        return False, ("the engine reported that the raw-capture scrub FAILED - the captures are "
                       "unchanged and still hold secret values")
    m = _SCRUB_OK_RE.search(engine_output or "")
    if not m:
        return False, ("COULD NOT VERIFY - the engine's output carries no record of the "
                       "raw-capture scrub, so there is no evidence it ran; treat the captures as "
                       "still holding secret values")
    changed, scanned = int(m.group(1)), int(m.group(2))
    if scanned < present:
        return False, (f"INCOMPLETE - the engine scrubbed {changed} of the {scanned} capture "
                       f"file(s) it could read, but {present} capture(s) are in the folder: "
                       f"{present - scanned} were not readable and were left untouched")
    return True, (f"scrubbed secret values in {changed} of {scanned} raw capture file(s), in "
                  f"place (IPs and hostnames kept by design)")


def _copy_back_scrubbed_collection(
    staged_source: Path,
    source: Path,
    bindings: Dict[str, Dict[str, Any]],
    root: Optional[Path] = None,
) -> int:
    """Replace original raw captures only if they still match the custody source bytes.

    The selector is the SAME structural rule the scrub and the verifier use, not ``rglob("*.txt")``
    - a fourth copy of the extension test would have made the whole fix pointless: the .cfg is
    scrubbed in the private staging tree, independently verified there, and then never written
    back, so the engineer's own folder keeps the cleartext secret while the run reports success.

    ``root`` scopes the walk to the collection root the engine actually scrubbed. Files staged from
    ABOVE it were never touched by the scrub, so copying them back is a no-op that only inflates
    the returned count past the verifier's - which the caller compares for equality."""
    base = Path(root) if root is not None else staged_source
    prepared: List[Tuple[Path, Path]] = []
    for staged in sorted(base.rglob("*")):
        if not staged.is_file() or not _is_raw_capture(staged):
            continue
        relative = staged.relative_to(staged_source).as_posix()
        binding = bindings.get(relative)
        if binding is None:
            raise EngineRunError(
                "A staged raw capture has no source custody binding; refusing copy-back."
            )
        original = source / Path(relative)
        if _stable_regular_sha256(original) != binding["sha256"]:
            raise EngineRunError(
                f"{relative} changed after entering custody; scrubbed bytes were not copied back."
            )
        temp = original.with_name(f".{original.name}.atlas-scrub-{uuid.uuid4().hex}.tmp")
        data = staged.read_bytes()
        temp.write_bytes(data)
        if _stable_regular_sha256(temp) != hashlib.sha256(data).hexdigest():
            raise EngineRunError(
                f"{relative} could not be staged safely for raw-capture scrub copy-back."
            )
        prepared.append((original, temp))
    for original, temp in prepared:
        os.replace(temp, original)
    return len(prepared)


def run_redaction_folder(path: Any, out_dir: Any, redact_collection: bool = False,
                         reuse_out: bool = False) -> Dict[str, Any]:
    """Serialize every run targeting one canonical output directory."""
    out = Path(str(out_dir)).expanduser().resolve()
    source_candidate = Path(str(path)).expanduser()
    if not source_candidate.is_dir():
        raise IngestError("Not a directory, or not readable.")
    _refuse_unsafe_out_dir(out, source_candidate.resolve())
    with _output_dir_lock(out):
        return _run_redaction_folder_locked(
            path, out, redact_collection=redact_collection, reuse_out=reuse_out
        )


def _run_redaction_folder_locked(path: Any, out_dir: Any, redact_collection: bool = False,
                                 reuse_out: bool = False) -> Dict[str, Any]:
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
       same unapproved design. And it would be a SILENT drop: ``run_redaction_folder`` captures the
       child's output and ``serve.run_redaction`` prints only the file list, so a ``[GATE REFUSED]``
       line never reaches the engineer here — unlike the ``cisco-assess`` CLI, which does surface
       it. Two quietly-absent files, with the same design shipping beside them, is worse than an
       honest ungated set (Guardrail 3).
    2. *A disclosure already exists, in a better place — though it is a partial one.* The SEVEN
       Word documents carry ``Status: DRAFT — generated; not yet reviewed`` in their Document
       Control table (``cisco_toolkit/docmeta.py`` ``add_document_control``). That travels INSIDE
       the file that gets emailed; a sidecar note in the folder does not. Two honest caveats: the
       workbook, explorer and deck carry NO such marking — and those are exactly the three carriers
       reason (1) leans on — and the row is a CONSTANT, so for a REVOKED approval it says "not yet
       reviewed" when the review happened and rejected it. Treat this as mitigation, not as
       equivalent to gate disclosure.
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
    recorded as OPEN in ``docs/log.md`` (2026-07-22); it needs the ledger-ownership problem in (3)
    solved first, and it is a change to what the field tool may withhold — not this function's
    call to make.
    Two independent honesty properties, because a run can fail either way. The redaction checks
    REFUSE (``EngineRunError`` + a do-not-send marker) when what was written may not be safe. The
    completeness check WARNS — ``report["missing"]`` lists any family document the engine's
    fail-soft writers did not produce, so a short set can never be reported as the whole family.
    A missing document is not a leak, so it does not raise; see ``_family_state``.

    ``reuse_out`` waives the refusal to render into a folder that already holds a deliverable set
    (``_refuse_reused_out_dir``) — the one path by which another engagement's documents can end up
    inside this delivery.
    """
    source, n_files = _resolve_and_scan(path)
    out = Path(str(out_dir)).expanduser().resolve()
    _refuse_unsafe_out_dir(out, source)
    if not getattr(sys, "frozen", False) and not _ENGINE_SCRIPT.is_file():
        raise EngineRunError(f"Engine entry point not found at {_ENGINE_SCRIPT}")

    workdir = Path(tempfile.mkdtemp(prefix="atlas_redact_"))
    try:
        staged_source = workdir / "custody"
        source_bindings = _stage_physical_tree(source, staged_source)
        if len(source_bindings) != n_files:
            raise IngestError(
                "The collection file count changed between preflight and private custody."
            )
        root, device_dirs = _find_collection_root(staged_source)
        devices, provenance, skipped = _load_or_synthesize_devices(
            root, staged_source, device_dirs
        )
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
        canonical_stem = "Assessment_redacted"
        if not reuse_out:
            _refuse_reused_out_dir(out, canonical_stem)
        engine_names = _engine_filenames(canonical_stem)
        delivery_stage = workdir / "delivery"
        delivery_stage.mkdir()
        out_xlsx = delivery_stage / f"{canonical_stem}.xlsx"
        # Name -> (mtime, size), so "did THIS run write it" survives a re-run into the same
        # folder. Membership alone (the original test) reported every re-rendered document as
        # pre-existing: a second run into the same --out printed "Wrote 0 file(s)" and would now
        # read as a set missing all 10 deliverables.
        # ...but (mtime, size) alone cannot see a BYTE-IDENTICAL rewrite inside one coarse mtime
        # tick, and re-running the same collection produces exactly that: the same MOP, same bytes,
        # same size, written within the same tick. Measured on this platform: an immediate
        # same-size rewrite moves st_mtime by 0.0 every time. The document was rewritten and the
        # check said it was not, so a correct run reported the whole family as
        # "left by an EARLIER run ... check which job it belongs to" — a false cross-job alarm on
        # good output, which is the failure mode _written_by_this_run's own docstring says this
        # codebase has already paid for once.
        #
        # Fixed by making the pre-run state DISTINGUISHABLE instead of hoping the clock ticks:
        # every family file the engine owns (and is about to overwrite) is stamped a sentinel mtime
        # a day back, so any rewrite moves it by ~86400s — far outside any tick, and detected by
        # the same inequality test, so a clock that jumps BACKWARDS is still caught. A file the
        # engine does not rewrite keeps the sentinel and is still correctly reported stale.
        # Only engine-owned names are stamped: the engineer's own notes beside the set are never
        # touched. If the run dies before the engine writes, those files read a day old on disk —
        # cosmetic, on files this run was about to overwrite anyway.
        pre_existing: Dict[str, Tuple[float, int]] = {}

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
        # Every exit below this point can leave *_redacted* files in `out`: the engine writes the
        # workbook and the documents as it goes, and nothing is deleted on failure (destroying
        # evidence is the worse failure). Those filenames ASSERT the property the run did not get
        # to certify, and stderr scrolls away - so each failure exit leaves the on-disk marker
        # too, exactly as the redaction-check failure below already did.
        except subprocess.TimeoutExpired as e:
            _mark_output_unsafe(out, "the engine run TIMED OUT before any check could be made")
            raise EngineRunError(
                f"Redaction run timed out after {REDACT_TIMEOUT_S}s ({len(device_dirs)} devices). "
                f"Partial output may exist in {out} - treat it as UNREDACTED.") from e
        duration = round(time.monotonic() - t0, 1)
        engine_output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        log_tail = _scrub_paths("\n".join(engine_output.strip().splitlines()[-12:]),
                                workdir, out, source)
        if proc.returncode != 0:
            _mark_output_unsafe(out, f"the engine exited with code {proc.returncode}")
            raise EngineRunError(f"Engine exited with code {proc.returncode}. Log tail:\n{log_tail}")

        snap_path = Path(str(out_xlsx)[: -len(".xlsx")] + ".snapshot.json")
        if not snap_path.is_file():
            _mark_output_unsafe(out, "the engine wrote no snapshot, so nothing could be verified")
            raise EngineRunError(f"Engine completed but wrote no snapshot. Log tail:\n{log_tail}")
        if not _written_by_this_run(snap_path, engine_names, pre_existing):
            # Under --reuse-out an EARLIER run's snapshot sits under this run's name. Verifying
            # that one certifies the previous job and says nothing about this one - the check
            # would pass over a run that produced no snapshot at all.
            _mark_output_unsafe(out, "the snapshot under this run's name was left by an EARLIER run")
            raise EngineRunError(
                f"Engine wrote no snapshot of its own - {snap_path.name} is unchanged from before "
                f"this run started, so it belongs to an EARLIER run and there is nothing from THIS "
                f"run to verify. Do NOT send anything from this folder. Log tail:\n{log_tail}")
        try:
            current_run_paths = [
                path for path in delivery_stage.iterdir()
                if path.is_file() and _written_by_this_run(path, engine_names, pre_existing)
            ]
            # Parse the canonical snapshot before consulting the producer ledger so a truncated
            # snapshot is reported as such, while artifact-family verification remains a separate
            # gate below.
            _assert_scrubbed(snap_path)
            # Positive producer evidence is the first gate. The independent byte scanner is a
            # separate second gate and must not obscure a producer-declared failed phase.
            _assert_redaction_phases_ran(out_xlsx, engine_output, engine_names, pre_existing)
            verifier_proof = _certify_shareable_artifacts(snap_path, current_run_paths)
            _assert_mandatory_completion(out_xlsx, engine_names, pre_existing)
            for name, expected_digest in verifier_proof.items():
                if _stable_regular_sha256(delivery_stage / name) != expected_digest:
                    raise EngineRunError(
                        f"{name} changed after independent verification; refusing the run."
                    )
        except (EngineRunError, OSError) as exc:
            _mark_output_unsafe(out, "a redaction check FAILED")
            if isinstance(exc, EngineRunError):
                raise
            raise EngineRunError(
                "REDACTION POSTCONDITION FAILED - current-run output could not be completely "
                "enumerated. Do NOT send anything from this run."
            ) from exc
        # Only what THIS run produced — enumerating the directory reported pre-existing files
        # (an engineer's own notes, an earlier unredacted export) under the share-safe banner.
        staged_written = sorted(path.name for path in current_run_paths)
        # Coverage honesty for the document family itself: the redaction checks above certify
        # that what IS here is safe, and say nothing about what is ABSENT. Every engine writer
        # fails soft, so an incomplete family is the one failure mode that still exits 0 and
        # prints a success banner. WARN rather than raise — a missing document is not a leak,
        # and routing it through EngineRunError would tell the engineer their correctly-redacted
        # files are UNREDACTED, which is both false and the fastest way to make the real alarm
        # unbelievable. The set stays usable; the gap is disclosed here, on the console and on disk.
        missing = _family_state(out_xlsx.stem, delivery_stage, set(staged_written))
        gap_lines = _engine_gap_lines(engine_output, (workdir, out, source))
        # What the raw-capture scrub actually DID, read back from the engine's own record and
        # compared against the captures that are really there. Only computed when it was asked
        # for: the folder walk is pointless otherwise, and "not requested" is not an outcome.
        scrub_ok, scrub_detail = (False, "")
        if redact_collection:
            scrub_ok, scrub_detail = _collection_scrub_outcome(engine_output,
                                                               _count_raw_captures(root))
            if not scrub_ok:
                _mark_output_unsafe(out, "the requested raw-capture scrub could not be verified")
                raise EngineRunError(
                    f"RAW-CAPTURE SCRUB COULD NOT BE VERIFIED - {scrub_detail}. "
                    "No deliverable set was promoted."
                )
            try:
                staged_scrub_proof = redaction_verify.verify_collection_secret_scrub(root)
                if staged_scrub_proof["files"] != _count_raw_captures(root):
                    raise EngineRunError(
                        "raw-capture verifier coverage did not match the staged collection"
                    )
                copied = _copy_back_scrubbed_collection(
                    staged_source, source, source_bindings, root
                )
                original_root = source / root.relative_to(staged_source)
                original_scrub_proof = redaction_verify.verify_collection_secret_scrub(
                    original_root
                )
                if (
                    copied != staged_scrub_proof["files"]
                    or original_scrub_proof != staged_scrub_proof
                ):
                    raise EngineRunError(
                        "raw-capture scrub copy-back does not match the independently verified "
                        "staged bytes"
                    )
                scrub_detail = (
                    f"independently verified {copied} raw capture file(s) after custody-bound "
                    "copy-back (IPs and hostnames kept by design)"
                )
                # Coverage honesty, and the reason the verifier returns this at all: files the
                # capture grammar cannot read (a JSON/XML controller dump, a binary) were NOT
                # scrubbed and NOT scanned. Reporting only the verified count let "verified N"
                # read as "the folder is clean", which is the same false-health shape as a
                # dark device disappearing out of an average.
                uncovered = staged_scrub_proof.get("uncovered") or []
                if uncovered:
                    names = ", ".join(row["file"] for row in uncovered[:6])
                    scrub_detail += (
                        f"; NOT COVERED: {len(uncovered)} file(s) under the collection root were "
                        f"neither scrubbed nor scanned ({names}"
                        + (", ..." if len(uncovered) > 6 else "")
                        + ") - the capture grammar does not read them, so this is NOT a statement "
                          "that they are free of secrets"
                    )
            except (EngineRunError, redaction_verify.RedactionVerificationError, OSError) as exc:
                _mark_output_unsafe(out, "the requested raw-capture scrub verification FAILED")
                if isinstance(exc, EngineRunError):
                    raise
                raise EngineRunError(
                    "RAW-CAPTURE SCRUB POSTCONDITION FAILED; no deliverable set was promoted."
                ) from exc
        written, previous_set = _promote_verified_delivery(
            delivery_stage,
            out,
            current_run_paths,
            engine_names,
            verifier_proof,
        )
        marker = None
        if missing:
            marker = _mark_output_incomplete(out, missing, gap_lines)
        else:
            _clear_stale_incomplete_marker(out)
        return {
            "out_dir": str(out),
            "files": written,
            "previous_set": previous_set,
            "missing": missing,
            "incomplete_note": str(marker) if marker else None,
            # A DO-NOT-SEND marker from an EARLIER failed run into this folder does not apply to
            # this one, and nothing removes it (deleting a safety warning is the wrong direction
            # to err). Surfacing it keeps the folder from saying "unsafe" and "complete" at once.
            "stale_unsafe_marker": (out / UNSAFE_MARKER).is_file(),
            # NOT `gap_lines if missing else []`. The produced-vs-expected diff is the DETECTOR
            # for a short set, but these lines are the engine's own account of what it refused or
            # could not do — a [GATE REFUSED], a writer that raised, a phase it skipped — and a
            # run can emit them while still producing every family document (a re-run into the
            # same folder, a writer that failed and then succeeded, a gate refusing a document
            # that was already on disk). Discarding them whenever the diff came back clean threw
            # away the evidence precisely in the case that looks healthy, which is the one case
            # where the reader has nothing else to go on.
            "engine_warnings": gap_lines,
            "n_device_dirs": len(device_dirs) - len(skipped),
            "devices": device_dirs,
            "skipped_dirs": skipped,
            "devices_json": provenance,
            "n_source_files": n_files,
            # Three keys, because one bool could not tell the three states apart and the old one
            # silently conflated two of them. `..._requested` is the FLAG (what was asked for);
            # `redacted_collection` is the OUTCOME (positively confirmed by the engine's own
            # record, so False also covers "asked for, could not be confirmed"); `..._detail` is
            # the sentence with the counts. Reporting the flag as the outcome told a field
            # engineer the secrets were off the stick when the scrub may never have run.
            "redacted_collection_requested": bool(redact_collection),
            "redacted_collection": scrub_ok,
            "redacted_collection_detail": scrub_detail,
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
    # its outputs under it, so paths in its output are workdir-rooted -- EXCEPT --collection-dir. For the
    # ZIP channel that is under workdir and the one replacement covered it; for run_collection_folder it is
    # the caller's own absolute path, which is how the engagement folder name leaked into the tail.
    log_tail = _scrub_paths(log_tail, workdir, tree)
    if proc.returncode != 0:
        raise EngineRunError(f"Engine exited with code {proc.returncode}. Log tail:\n{log_tail}")

    snap_path = Path(str(out_xlsx)[: -len(".xlsx")] + ".snapshot.json")
    if not snap_path.is_file():
        raise EngineRunError(f"Engine completed but wrote no snapshot. Log tail:\n{log_tail}")
    # Same non-finite refusal as the upload channel (see reject_nonfinite): this snapshot is about
    # to be STORED, and a non-finite float in it makes every later read of that stored row answer
    # HTTP 500 forever. The engine is our own code, but it derives values from untrusted device
    # output, so "we produced it" is not a guarantee that it is renderable.
    try:
        snap = json.loads(snap_path.read_text(encoding="utf-8"), parse_constant=reject_nonfinite)
    except ValueError as e:
        raise EngineRunError(
            f"The engine's snapshot carries a value that cannot be served back over HTTP ({e}). "
            f"Refusing to store it. Log tail:\n{log_tail}")
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
        "verification": summary.snapshot_verification(snap),
    }
    return snap, report
