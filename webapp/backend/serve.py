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
   Browser auto-open unless ``--no-browser``.

Run from a checkout with ``python -m webapp.backend.serve`` (relative imports need the package
context) or the installed ``assesshub`` script. Console build (D3): the live-SSH credential prompt
needs a real terminal, so the frozen app is built ``console=True``.
"""

from __future__ import annotations

import argparse
import multiprocessing
import os
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
    try:
        dbp.parent.mkdir(parents=True, exist_ok=True)
        probe = dbp.parent / ".atlas-selftest-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        check("db-writable", None)
    except OSError as e:
        check("db-writable", f"cannot write {dbp.parent}: {e}")

    n_ok = sum(1 for _, failure in checks if failure is None)
    print(f"{APP_TITLE} — selftest · release {_release_version()}")
    for name, failure in checks:
        print(f"  [ ok ] {name}" if failure is None else f"  [FAIL] {name} — {failure}")
    verdict = "PASS" if n_ok == len(checks) else "FAIL"
    print(f"SELFTEST: {verdict} ({n_ok}/{len(checks)} checks ok)")
    return 0 if n_ok == len(checks) else 1


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
                             "docx/pptx, frontend dist, engine entry, DB dir) and exit non-zero "
                             "on any failure")
    parser.add_argument("--version", action="version", version=_version_line())
    args = parser.parse_args(argv)

    if args.selftest:
        return run_selftest(dist_dir=args.dist, db_path=args.db)

    from .app import create_app  # lazy: the engine-child path never pays the fastapi import

    dist = _resolve_dist(args.dist)
    app = create_app(db_path=_resolve_db(args.db), dist_dir=str(dist))
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
