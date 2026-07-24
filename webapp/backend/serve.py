"""Atlas production entry point — the one door the portable build opens (ADR-0004 P1).

The `assesshub` console script and the frozen `Atlas.exe` (P2, PyInstaller one-folder) both land in
:func:`main`, which does four things in a load-bearing order:

1. ``multiprocessing.freeze_support()`` — FIRST. In a frozen build every multiprocessing child
   re-executes the exe; without this a child boots a second server instead of doing its work.
2. Engine-child dispatch: ``<exe> --run-engine <engine argv>`` becomes the engine CLI in-process
   (``COLLECT_PARSE_V3_23_0.main()`` with ``sys.argv`` rewritten). This is the frozen half of
   ``backend/ingest.py``'s dispatch: on a checkout the dispatcher runs the repo-root script under
   the interpreter, but inside a one-folder build ``sys.executable`` IS the app — the sentinel is
   how the exe impersonates the engine while ingest keeps its child-process isolation and hard
   timeout. It is checked BEFORE argparse: engine flags are the engine's surface, not ours.
3. ``--selftest`` / ``--version`` — the fail-loud gate over the assets that otherwise degrade
   SILENTLY when missing (explorer template, OUI/port KBs, docx/pptx extras, frontend dist).
4. Production serve: ``uvicorn.run(<app object>)`` — the object, never an import string, so reload
   is structurally impossible; workers are never configured (one process owns the SQLite store).
   Browser auto-open unless ``--no-browser``. The boot is hardened (ADR-0004 P3 unplug-safety):
   a write probe turns a write-locked stick into a friendly refusal, and the store
   integrity-checks + backs itself up before serving (``storage.Store(boot_hardening=True)``) —
   a corrupt DB refuses to serve and is left untouched for a human restore.

Run from a checkout with ``python -m webapp.backend.serve`` (relative imports need the package
context) or the installed ``assesshub`` script. Console build (D3): the live-SSH credential prompt
needs a real terminal, so the frozen app is built ``console=True``.
"""

from __future__ import annotations

import argparse
import multiprocessing
import os
import sqlite3
import sys
import threading
from importlib.metadata import PackageNotFoundError, version as _dist_version
from pathlib import Path

from cisco_toolkit.brand_tokens import APP_TITLE

# The frozen exe re-invokes ITSELF with this first argument to become the engine CLI child
# (see backend/ingest.py:_engine_argv, the only producer).
ENGINE_SENTINEL = "--run-engine"

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8000


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _exe_dir() -> Path:
    return Path(sys.executable).resolve().parent


def _release_version() -> str:
    # A checkout/worktree wins over installed-dist metadata: running checkout code while an OLDER
    # pip install exists is the dev-box norm, and support reads this line in bug reports.
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if pyproject.is_file():
        try:
            import tomllib  # 3.11+; a 3.10 checkout just falls through to dist metadata

            with pyproject.open("rb") as f:
                v = tomllib.load(f).get("project", {}).get("version")
            if v:
                return f"{v} (checkout)"
        except (ImportError, OSError, ValueError):
            pass
    try:
        return _dist_version("cisco-migration-assessment-toolkit")
    except PackageNotFoundError:  # frozen bundle without dist metadata
        return "unpackaged"


def _version_line() -> str:
    from cisco_toolkit import __version__ as schema_version

    return f"{APP_TITLE} · release {_release_version()} · engine schema {schema_version}"


# ── engine-child dispatch (the frozen half of ingest's frozen-aware dispatch) ───
def _load_engine_main():
    """Import hook for the engine CLI — a seam so tests stub the heavy import."""
    import COLLECT_PARSE_V3_23_0 as engine_cli

    return engine_cli.main


def _run_engine(args: list) -> int:
    """Become the engine CLI: exactly what `cisco-assess <args>` does, inside this process."""
    sys.argv = ["cisco-assess", *args]
    rc = _load_engine_main()()
    return int(rc or 0)


# ── path resolution (dev checkout / env override / frozen bundle) ───────────────
def _resolve_dist(cli_dist) -> Path:
    """Built-frontend directory: --dist > $ASSESSHUB_DIST > the bundled copy (frozen) > the
    checkout's webapp/frontend/dist."""
    if cli_dist:
        return Path(cli_dist)
    env = os.environ.get("ASSESSHUB_DIST")
    if env:
        return Path(env)
    if _frozen():
        # P2 bundles the built SPA at <bundle>/webapp_dist (PyInstaller sets _MEIPASS for both
        # one-file and one-folder layouts).
        return Path(getattr(sys, "_MEIPASS", str(_exe_dir()))) / "webapp_dist"
    from . import app as app_module  # lazy: pulls fastapi

    return app_module.FRONTEND_DIST


def _resolve_db(cli_db):
    """DB path for create_app: --db > (None: create_app's default already honours $ASSESSHUB_DB) >
    frozen fallback `data\\assesshub.db` BESIDE the exe — the stick's only writable dir, never
    inside the bundle (which an update replaces wholesale)."""
    if cli_db:
        return cli_db
    if os.environ.get("ASSESSHUB_DB"):
        return None
    if _frozen():
        return str(_exe_dir() / "data" / "assesshub.db")
    return None


def _effective_db_path(cli_db) -> str:
    """The path the store will actually open (for the selftest's writability probe)."""
    resolved = _resolve_db(cli_db)
    if resolved:
        return resolved
    env = os.environ.get("ASSESSHUB_DB")
    if env:
        return env
    from . import app as app_module

    return app_module.DEFAULT_DB


def _schedule_browser_open(url: str) -> None:
    """uvicorn.run blocks — open the UI shortly after startup from a daemon timer.
    Fire-and-forget: a headless box just keeps the printed URL."""

    def _open() -> None:
        import webbrowser

        try:
            webbrowser.open(url)
        except Exception:
            pass

    t = threading.Timer(1.0, _open)
    t.daemon = True
    t.start()


# ── shared write probe (selftest + pre-serve) ──────────────────────────────────
def _writable_failure(dirpath: Path):
    """OSError text if `dirpath` cannot be created and written — the write-locked-stick /
    read-only-folder class a field boot must turn into a friendly refusal, not a traceback."""
    try:
        dirpath.mkdir(parents=True, exist_ok=True)
        probe = dirpath / ".atlas-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return None
    except OSError as e:
        return str(e)


# ── --selftest ──────────────────────────────────────────────────────────────────
def _explorer_template_path() -> Path:
    """Resolve exactly like cisco_toolkit.html does: the package copy, legacy repo-root fallback."""
    import cisco_toolkit.html as html_mod

    here = Path(html_mod.__file__).resolve().parent
    primary = here / "blast_radius_explorer.html"
    return primary if primary.is_file() else here.parent / "blast_radius_explorer.html"


def run_selftest(dist_dir=None, db_path=None) -> int:
    """Assert every asset that otherwise degrades SILENTLY when missing (ADR-0004 P1).

    Each check names the field symptom its failure would cause; returns 0 only when all pass."""
    checks = []

    def check(name: str, failure) -> None:
        checks.append((name, failure))

    tpl = _explorer_template_path()
    check("explorer-template",
          None if tpl.is_file() and tpl.stat().st_size > 10_000
          else f"missing/truncated at {tpl} — every explorer render would fail")

    from cisco_toolkit import ouidb, portdb

    vendor = ouidb.vendor_for_mac("00:00:0C:12:34:56")  # Cisco's classic MA-L block
    check("oui-kb", None if "cisco" in vendor.lower()
          else "MAC→vendor lookup degraded — oui_registry.tsv.gz missing/corrupt "
               "(endpoint classification would silently empty)")
    check("port-kb", None if portdb.service_for_port(443, "tcp")
          else "L4 port lookup degraded — port_registry.tsv.gz missing/corrupt")

    import importlib.util as _ilu

    check("python-docx", None if _ilu.find_spec("docx")
          else "python-docx not importable — the DOCX document family is dead (ADR-0004 D2 "
               "ships the full 12-document family)")
    check("python-pptx", None if _ilu.find_spec("pptx")
          else "python-pptx not importable — the executive deck is dead (ADR-0004 D2)")

    dist = Path(dist_dir) if dist_dir is not None else _resolve_dist(None)
    check("frontend-dist", None if (dist / "index.html").is_file()
          else f"no index.html under {dist} — the UI would be dead (API-only)")

    if _frozen():
        check("engine-entry", None if _ilu.find_spec("COLLECT_PARSE_V3_23_0")
              else "engine module not bundled — ingest would respawn the app instead of "
                   "running the engine")
    else:
        from . import ingest as ingest_mod

        check("engine-entry", None if ingest_mod._ENGINE_SCRIPT.is_file()
              else f"engine script not found at {ingest_mod._ENGINE_SCRIPT}")

    dbp = Path(_effective_db_path(db_path))
    err = _writable_failure(dbp.parent)
    check("db-writable", None if err is None else f"cannot write {dbp.parent}: {err}")

    bak = dbp.parent / "backups"
    err = _writable_failure(bak)
    check("backup-dir", None if err is None
          else f"cannot write {bak}: {err} — boot-time DB backups (unplug safety, "
               "ADR-0004 P3) would fail")

    n_ok = sum(1 for _, failure in checks if failure is None)
    print(f"{APP_TITLE} — selftest · release {_release_version()}")
    for name, failure in checks:
        print(f"  [ ok ] {name}" if failure is None else f"  [FAIL] {name} — {failure}")
    verdict = "PASS" if n_ok == len(checks) else "FAIL"
    print(f"SELFTEST: {verdict} ({n_ok}/{len(checks)} checks ok)")
    return 0 if n_ok == len(checks) else 1


# ── --redact-folder: the share-safe deliverable set, from the stick ─────────────
def run_redaction(src: str, out: str, redact_collection: bool = False,
                  reuse_out: bool = False) -> int:
    """Render a redacted deliverable set — the "before it leaves the site" step (ADR-0004 P3).

    Field-facing, so every failure is a plain sentence, never a traceback: this runs at a client
    site with no internet and no second document."""
    if not out:
        print(f"{APP_TITLE}: --redact-folder needs --out DIR (where the redacted set is written).",
              file=sys.stderr)
        return 2
    from . import ingest as ingest_mod  # lazy: the engine-child path must not pay for this

    print(f"{APP_TITLE}: redacting {src}\n  -> {out}\n"
          f"  Rendering the full document family; this can take several minutes.")
    if redact_collection:
        print("  --redact-collection: the RAW captures will also be scrubbed IN PLACE.")
    try:
        report = ingest_mod.run_redaction_folder(src, out, redact_collection=redact_collection,
                                                 reuse_out=reuse_out)
    except ingest_mod.IngestError as e:
        print(f"{APP_TITLE}: cannot redact that folder - {e}", file=sys.stderr)
        return 1
    except ingest_mod.EngineRunError as e:
        print(f"{APP_TITLE}: redaction FAILED - {e}\n"
              f"  Treat anything already written in {out} as UNREDACTED.", file=sys.stderr)
        return 1
    print(f"  {report['n_device_dirs']} device(s) in {report['engine_seconds']}s. "
          f"Wrote {len(report['files'])} file(s):")
    for name in report["files"]:
        print(f"    {name}")
    # No PPDIOO gate line is printed here ON PURPOSE — this run cannot identify the engagement's
    # ledger (see ingest.run_redaction_folder), and every document already carries its own
    # "DRAFT - generated; not yet reviewed" status. A gate verdict inferred from whichever ledger
    # happened to sit nearby would be worse than silence: it could report another client's
    # approvals as this engagement's.
    if report.get("stale_unsafe_marker"):
        print("\n  NOTE: this folder still holds DO-NOT-SEND-NOT-REDACTED.txt from an EARLIER\n"
              "  run. It does not describe this run, which passed its redaction checks. Delete\n"
              "  it once you are sure the older output it refers to is gone.")
    # Say exactly what was checked. The engine pseudonymizes IPs, MACs and serials, but the
    # verification here covers surviving PRIVATE IPv4 in the snapshot plus proof that the engine's
    # redaction phases actually ran. Claiming more than that ("every IP/MAC/serial ... verified")
    # certified roughly three times what the code inspects — and hostnames are kept BY DESIGN, so
    # a "fully anonymous" mental model is exactly the wrong one to leave the engineer with.
    print("  Checked: the engine's redaction phases ran, and no private (RFC 1918) address\n"
          "  survives in the redacted snapshot.\n"
          "  NOT checked: MACs, serials, public/IPv6 addresses, or the workbook's own cells.\n"
          "  HOSTNAMES ARE KEPT BY DESIGN - device names and site codes still identify the\n"
          "  client. Review before sending.")
    # An engine writer that fails is fail-soft by design (the workbook and snapshot still save),
    # so a short set otherwise reaches the engineer as an unqualified success banner: two fewer
    # files look exactly like a full family unless you know the set by heart. Not a refusal -
    # what IS here is redacted and safe.
    #
    # Printed LAST, and on stdout. When the engineer redirects a 10-minute run to a log
    # (`Atlas.exe ... > run.log 2>&1`, the natural thing to do), Python block-buffers stdout and
    # line-buffers stderr: the warning got hoisted ABOVE the command banner, so it read as
    # belonging to a previous command, and the log ENDED on the reassurance block. A `tail` showed
    # a clean success. One stream, warning last, so the final word is the warning.
    missing = report.get("missing") or []
    if not missing:
        return 0
    print(f"\n  INCOMPLETE SET - {len(missing)} deliverable(s) were NOT produced:")
    for m in missing:
        print(f"    {m['state'].upper():9} {m['name']}  ({m['filename']})\n"
              f"              {m['detail']}")
    for line in report.get("engine_warnings") or []:
        print(f"    engine: {line}")
    # Only promise the note if it was really written - a read-only folder, or a file of that
    # name Atlas did not author, means there is no note to go and read.
    note = report.get("incomplete_note")
    print(f"  The same list is saved as {note}." if note else
          "  (Could not write the note into the output folder - this console is the record.)")
    print("  What IS in the folder is redacted and safe to share. The SET is short: re-run into\n"
          "  an empty folder, or tell the recipient which documents are not included.")
    # Exit 3, not 0: this command exists to certify a deliverable set, so "0" must keep meaning
    # "complete and verified". Nothing consumes the code today, which is exactly why adopting it
    # now is free and adopting it later would be a breaking change. It is deliberately NOT 1 -
    # that is the redaction-failure code, and this output is safe.
    return 3


# ── entry point ─────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    # Frozen multiprocessing children re-enter here; this MUST precede everything else.
    multiprocessing.freeze_support()
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    if argv and argv[0] == ENGINE_SENTINEL:
        return _run_engine(argv[1:])

    parser = argparse.ArgumentParser(
        prog="assesshub",
        description=f"{APP_TITLE} — serve AssessHub (production: no reload, no workers).")
    parser.add_argument("--host", default=_DEFAULT_HOST,
                        help=f"bind address (default {_DEFAULT_HOST}; non-loopback serves need "
                             "ASSESSHUB_TOKEN — see webapp/README.md)")
    parser.add_argument("--port", type=int, default=_DEFAULT_PORT,
                        help=f"port (default {_DEFAULT_PORT})")
    parser.add_argument("--db", default=None,
                        help="SQLite store path (default: $ASSESSHUB_DB, else the app default; "
                             "frozen builds default to data\\assesshub.db beside the exe)")
    parser.add_argument("--dist", default=None,
                        help="built frontend directory (default: $ASSESSHUB_DIST, the bundled "
                             "copy when frozen, else webapp/frontend/dist)")
    parser.add_argument("--no-browser", action="store_true",
                        help="do not auto-open the UI in a browser")
    parser.add_argument("--selftest", action="store_true",
                        help="verify the silent-degrade assets (explorer template, OUI/port KBs, "
                             "docx/pptx, frontend dist, engine entry, DB + backup dirs) and exit "
                             "non-zero on any failure")
    parser.add_argument("--redact-folder", default=None, metavar="DIR",
                        help="produce a REDACTED, share-safe deliverable set from a local "
                             "collection folder and exit (needs --out). Synthesizes the template "
                             "and devices.json the engine requires, so nothing extra is needed "
                             "on the stick")
    parser.add_argument("--out", default=None, metavar="DIR",
                        help="destination for --redact-folder; must be OUTSIDE the Atlas folder "
                             "(an update replaces everything there except data\\)")
    parser.add_argument("--redact-collection", action="store_true",
                        help="with --redact-folder: ALSO scrub cleartext secrets from the raw "
                             "captures IN PLACE (rewrites the source folder; still "
                             "--compare/--trend-able)")
    parser.add_argument("--reuse-out", action="store_true",
                        help="with --redact-folder: render into an --out folder that already "
                             "holds a deliverable set. Refused by default: if that set is from "
                             "another job, any document this run fails to write leaves that "
                             "client's copy in this delivery under the right name")
    parser.add_argument("--version", action="version", version=_version_line())
    args = parser.parse_args(argv)

    if args.selftest:
        return run_selftest(dist_dir=args.dist, db_path=args.db)

    if args.redact_folder:
        return run_redaction(args.redact_folder, args.out, args.redact_collection, args.reuse_out)
    if args.out or args.redact_collection or args.reuse_out:
        print(f"{APP_TITLE}: --out, --redact-collection and --reuse-out only apply to "
              f"--redact-folder.", file=sys.stderr)
        return 2

    # Field refusal #1 — write-locked stick / read-only folder: friendly line, not a traceback.
    data_dir = Path(_effective_db_path(args.db)).parent
    err = _writable_failure(data_dir)
    if err:
        print(f"{APP_TITLE}: the data folder is not writable: {data_dir}\n"
              f"  ({err})\n"
              f"  Is the stick write-locked, or the folder read-only? Fix that and start again "
              f"(README-FIELD.txt, 'Read-only stick').", file=sys.stderr)
        return 1

    from .app import create_app  # lazy: the engine-child path never pays the fastapi import
    from .storage import StoreCorruptError

    dist = _resolve_dist(args.dist)
    # Field refusal #2 — corrupt store: refuse to serve, leave the file for a human restore.
    # ASCII separator on purpose: README-FIELD quotes this line and is ASCII-only (a cp437 field
    # console renders an em-dash as '?', so the guide could never match what the engineer sees).
    try:
        app = create_app(db_path=_resolve_db(args.db), dist_dir=str(dist), boot_hardening=True)
    except StoreCorruptError as e:
        print(f"{APP_TITLE}: refusing to start - {e}", file=sys.stderr)
        return 1
    except sqlite3.DatabaseError as e:
        # Anything else the store raises (unreadable file, locked by an AV scanner, a DB written
        # by a newer SQLite) must still be a refusal, not a traceback in the engineer's face.
        print(f"{APP_TITLE}: cannot open the store - {e}\n"
              f"  The file was not modified. Close any other Atlas window and try again "
              f"(README-FIELD.txt, 'Corruption').", file=sys.stderr)
        return 1
    url = f"http://{args.host}:{args.port}/"
    note = "" if (dist / "index.html").is_file() else \
        "   [frontend dist missing — API only; run --selftest]"
    print(f"{_version_line()}\n  {url}{note}")
    if not args.no_browser:
        _schedule_browser_open(url)

    import uvicorn  # lazy for the same reason

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":  # python -m webapp.backend.serve
    raise SystemExit(main())
