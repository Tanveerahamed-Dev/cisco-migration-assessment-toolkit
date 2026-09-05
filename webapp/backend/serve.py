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
   SILENTLY when missing (explorer template, OUI/port/EoL KBs, docx/pptx extras, frontend dist).
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
import hashlib
import ipaddress
import json
import multiprocessing
import os
import re
import sqlite3
import stat
import sys
import tempfile
import threading
from importlib.metadata import PackageNotFoundError, version as _dist_version
from pathlib import Path

from cisco_toolkit.brand_tokens import APP_TITLE
from cisco_toolkit.docmeta import artifact_family_metadata

# The frozen exe re-invokes ITSELF with this first argument to become the engine CLI child
# (see backend/ingest.py:_engine_argv, the only producer).
ENGINE_SENTINEL = "--run-engine"
LIVE_NETWORK_FLAG = "--allow-live-network"
DATABASE_PREFLIGHT_ENV = "ATLAS_PORTABLE_DATABASE_PREFLIGHT"
DATABASE_PREFLIGHT_MARKER = "atlas-db-preflight.json"

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8000
_EXTERNAL_LAUNCH_LOCK = threading.Lock()


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
            try:
                import tomllib  # stdlib 3.11+
            except ModuleNotFoundError:
                # 3.10: the old comment said "a 3.10 checkout just falls through to dist metadata"
                # -- which silently DROPPED the "(checkout)" marker there, and the first py3.10 CI
                # leg ever to run failed the version-flag test on exactly that. tomli ships in
                # [dev] and verify_release.py already falls back to it; the marker should not
                # depend on which Python happens to run the checkout.
                import tomli as tomllib  # type: ignore[no-redef]

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


def _set_windows_dll_directory(value: str | None) -> bool:
    import ctypes

    return bool(ctypes.windll.kernel32.SetDllDirectoryW(value))


def _open_external_url(url: str, opener=None) -> bool:
    """Launch a system browser without leaking PyInstaller's DLL search path to it."""
    import webbrowser

    launch = opener or webbrowser.open
    if os.name != "nt" or not _frozen():
        return bool(launch(url))
    bundle = str(getattr(sys, "_MEIPASS", ""))
    prior_path = os.environ.get("PATH")
    parts = (prior_path or "").split(os.pathsep)
    folded_bundle = os.path.normcase(os.path.abspath(bundle)) if bundle else ""
    cleaned = [
        item for item in parts
        if not folded_bundle
        or not os.path.normcase(os.path.abspath(item or ".")).startswith(folded_bundle)
    ]
    with _EXTERNAL_LAUNCH_LOCK:
        try:
            if not _set_windows_dll_directory(None):
                raise OSError("could not restore the system DLL search directory")
            os.environ["PATH"] = os.pathsep.join(cleaned)
            return bool(launch(url))
        finally:
            if prior_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = prior_path
            if bundle:
                _set_windows_dll_directory(bundle)


def _schedule_browser_open(url: str) -> None:
    """uvicorn.run blocks — open the UI shortly after startup from a daemon timer.
    Fire-and-forget: a headless box just keeps the printed URL."""

    def _open() -> None:
        try:
            _open_external_url(url)
        except Exception:
            pass

    t = threading.Timer(1.0, _open)
    t.daemon = True
    t.start()


def _bind_is_loopback(host: str) -> bool:
    candidate = str(host).strip()
    if candidate.lower() == "localhost":
        return True
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def _bind_is_numeric_loopback(host: str) -> bool:
    """Frozen binding never delegates the meaning of ``localhost`` to hosts/DNS state."""
    candidate = str(host).strip()
    if candidate.startswith("[") and candidate.endswith("]"):
        return False  # brackets are URL syntax, not a valid uvicorn bind address
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


#: Characters that make a value unusable as a path/host but survive `str.strip()`: the zero-width
#: and BOM codepoints (str.strip removes NBSP and the exotic spaces, but NOT these), plus every C0
#: control including NUL.
_INVISIBLE = "​‌‍⁠﻿"


def _unusable_value(value: str):
    """Why this CLI value cannot be used, as a sentence fragment, or None if it is fine.

    Two ways a value looked present and was not. A string of zero-width spaces passes
    `str.strip()`, so `--db "\\u200b"` sailed through the empty-value guard and CREATED A REAL
    SQLITE STORE named with an invisible character - the very "quietly opened a different store
    than the one you named" outcome that guard exists to stop, reached with a value that is not
    technically blank. And an embedded NUL raises ValueError deep inside pathlib/sqlite3
    (`ingest.py` resolve, `sqlite3.connect`), escaping main() as a traceback after the job banner
    had already printed - this file's contract is a plain sentence, never a traceback."""
    if any(ch == "\x00" or ord(ch) < 32 for ch in value):
        return "contains a control character, which is not a usable path or host."
    if not value.strip().strip(_INVISIBLE).strip():
        return ("was given an empty value (or one made only of invisible characters)."
                if value.strip() else "was given an empty value.")
    return None


# ── shared write probe (selftest + pre-serve) ──────────────────────────────────
def _writable_failure(dirpath: Path):
    """OSError text if `dirpath` cannot be created and written — the write-locked-stick /
    read-only-folder class a field boot must turn into a friendly refusal, not a traceback."""
    fd = -1
    probe: Path | None = None
    try:
        dirpath.mkdir(parents=True, exist_ok=True)
        fd, raw_probe = tempfile.mkstemp(prefix=".atlas-write-probe-", dir=str(dirpath))
        probe = Path(raw_probe)
        os.write(fd, b"ok")
        os.close(fd)
        fd = -1
        probe.unlink()
        probe = None
        return None
    except OSError as e:
        return str(e)
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        if probe is not None:
            try:
                probe.unlink(missing_ok=True)
            except OSError:
                pass


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

    from cisco_toolkit import eoldb, ouidb, portdb, registry_integrity

    oui_health = ouidb.registry_health()
    oui_rows = oui_health.get("row_count")
    oui_detail = (f"{oui_rows or 0} rows; "
                  f"provenance={oui_health.get('provenance_status', 'unknown')}")
    # Routed through registry_integrity.pack_is_usable, the ONE owner of "can this pack be relied
    # on" (three consumers had previously each written their own conjunction and disagreed). It
    # distinguishes CANNOT-CHECK-HERE from CHECKED-AND-FAILED: a wheel or frozen bundle ships
    # without reference-data/official-sources/** (handoff 5.5), so the source chain is structurally
    # unverifiable there -- the first-ever wheel-context run of this self-test (CI, 2026-08-02)
    # failed on exactly that, as the port-authority refuter's F7 predicted. Where the inventory is
    # absent the pack passes on bytes + build provenance, and the [ok] line SAYS SO; a present
    # inventory that fails verification is still a hard [FAIL].
    _oui_degraded = (" — retained official sources NOT present in this install form; source chain "
                     "verifiable from the repository/sdist only (bytes + build provenance verified)"
                     if registry_integrity.official_sources_available() is False else "")
    check(f"oui-kb [{oui_detail}]{_oui_degraded}",
          None if registry_integrity.pack_is_usable(oui_health)
          and isinstance(oui_rows, int) and oui_rows > 0
          else "OUI registry is not authoritative — "
               f"{oui_health.get('error') or oui_health.get('status', 'unknown')}")

    port_health = portdb.registry_health()
    port_rows = port_health.get("row_count")
    port_detail = (
        f"{port_rows or 0} rows "
        f"({port_health.get('port_count', 0)} ports, "
        f"{port_health.get('multicast_count', 0)} multicast); "
        f"provenance={port_health.get('provenance_status', 'unknown')}"
    )
    # SCOPED AUTHORITY (handoff 5.2). The port pack is deliberately MIXED: IANA assignment records
    # are official and freshness-verified, while curated service hints and the 21 bounded multicast
    # scopes are explicitly non-authoritative. `authoritative` is therefore whole-pack and correctly
    # False -- relabelling curated rows as official to make it True would be the actual lie.
    #
    # Gating the self-test on that flag treated an honest mixed pack as a DEAD registry: Atlas
    # reported "[FAIL] port-kb ... Port registry is not authoritative" on a pack whose bytes,
    # schema and IANA source chain had all verified. What this check must require is that the pack
    # is intact and its OFFICIAL component is source-proven -- not universal authority over every
    # curated row.
    #
    # Freshness is not a separate condition here because it is subsumed:
    # registry_integrity.source_authority_details only sets source_authoritative when the retained
    # source bytes verify AND satisfy the 180-day max-age / 5-minute future-skew bounds. Exposing a
    # duplicate official_source_fresh would assert a second, independent proof that does not exist.
    check(f"port-kb [{port_detail}]{_oui_degraded}",
          None if registry_integrity.pack_is_usable(port_health)
          and isinstance(port_rows, int) and port_rows > 0
          else "Port registry unusable — "
               f"{port_health.get('error') or port_health.get('status', 'unknown')}"
               + ("" if port_health.get("integrity_verified") else " [pack integrity FAILED]")
               + ("" if port_health.get("official_source_authoritative")
                  else " [IANA source chain unverified or stale]"))

    eol_health = eoldb.registry_health()
    eol_rows = eol_health.get("row_count")
    eol_detail = (
        f"{eol_rows or 0} model scopes; "
        f"{eol_health.get('bulletin_count', 0)} Cisco bulletins; "
        f"provenance={eol_health.get('status', 'unknown')}"
    )
    # Unlike the large IEEE/IANA source corpus, the compact retained Cisco bulletin fixture ships
    # with the wheel and frozen Atlas bundle. There is therefore no cannot-check-here exception for
    # lifecycle claims: installed code must verify the retained bytes, their exact semantic binding
    # to every runtime PID/date/URL claim, and freshness. Without this check an otherwise-green
    # release can install successfully yet make the engine's lifecycle phase fail when it first
    # consumes a row.
    eol_usable = (
        registry_integrity.pack_is_usable(eol_health)
        and eol_health.get("schema_verified") is True
        and eol_health.get("build_provenance_verified") is True
        and eol_health.get("retained_source_bytes_verified") is True
        and eol_health.get("source_authoritative") is True
        and eol_health.get("source_fresh") is True
        and isinstance(eol_rows, int)
        and eol_rows > 0
        and eol_health.get("bulletin_cited_rows") == eol_rows
        and eol_health.get("fixture_bound_rows") == eol_rows
        and eol_health.get("unresolved_reference_rows") == 0
    )
    check(
        f"eol-kb [{eol_detail}]",
        None if eol_usable
        else "Lifecycle registry lacks authoritative retained Cisco bulletin evidence — "
             f"{eol_health.get('error') or eol_health.get('status', 'unknown')}"
             + ("" if eol_health.get("retained_source_bytes_verified")
                else " [retained fixture missing or invalid]")
             + ("" if eol_health.get("build_provenance_verified")
                else " [runtime semantic binding FAILED]")
             + ("" if eol_health.get("source_fresh")
                else " [source evidence stale or future-dated]"),
    )

    import importlib.util as _ilu

    family = artifact_family_metadata()
    check("python-docx", None if _ilu.find_spec("docx")
          else "python-docx not importable — registry-declared DOCX artifacts are dead "
               f"({family['pre_cutover']} pre-cutover artifacts plus "
               f"{family['conditional_post_execution']} conditional post-execution artifact)")
    check("python-pptx", None if _ilu.find_spec("pptx")
          else "python-pptx not importable — the executive deck is dead (ADR-0004 D2)")

    dist = Path(dist_dir) if dist_dir is not None else _resolve_dist(None)
    check("frontend-dist", None if (dist / "index.html").is_file()
          else f"no index.html under {dist} — the UI would be dead (API-only)")

    if _frozen():
        check("engine-entry", None if _ilu.find_spec("COLLECT_PARSE_V3_23_0")
              else "engine module not bundled — ingest would respawn the app instead of "
                   "running the engine")
        from portable import network_boundary

        network_ok = network_boundary.installed() and (
            network_boundary.live_network_allowed() or network_boundary.offline_probe()
        )
        mode = "explicit-live" if network_boundary.live_network_allowed() else "offline-loopback-only"
        check(
            f"network-boundary [{mode}]",
            None if network_ok
            else "portable socket boundary is absent or failed its non-loopback denial probe",
        )
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
        print("  --redact-collection: the RAW captures will ALSO be scrubbed in place; the result "
              "is reported below.")
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
    # A successful promotion archives a prior generation and its marker together. A marker that
    # nevertheless appears beside the current receipt is therefore contradictory external state,
    # and is reported loudly.
    if report.get("stale_unsafe_marker"):
        print(f"\n  WARNING: this folder still holds {ingest_mod.UNSAFE_MARKER} from an EARLIER\n"
              f"  run whose redaction could NOT be certified. This run passed its own checks, but\n"
              f"  that conflicts with the current verified receipt. Do not send this folder until\n"
              f"  the marker's provenance is understood.")
    # Say exactly what was checked. Hostnames remain by design, so this is a share-safety claim
    # about identity tokens and recognised credentials, not a claim of full anonymisation.
    # The raw-capture scrub is the ONE control that removes cleartext secrets (enable secrets, SNMP
    # communities, PSKs) from the captures on the stick, and it is fail-soft: redact_collection_dir
    # skips any capture it cannot read or rewrite and continues. Its verdict is therefore reported
    # from what HAPPENED, and it has to be printed -- an engineer who asked for the scrub and reads
    # only a success banner will believe the secrets are gone.
    if report.get("redacted_collection_requested"):
        verdict = "SCRUBBED" if report.get("redacted_collection") else "*** NOT VERIFIED ***"
        print(f"\n  Raw captures (--redact-collection): {verdict}\n"
              f"    {report.get('redacted_collection_detail', 'no detail reported')}")
        if not report.get("redacted_collection"):
            print("    The RAW captures may still hold secrets in cleartext. Do not hand the\n"
                  "    collection folder over until you have confirmed the scrub yourself.")
    print("  Checked: mandatory redaction/finalization completed; every current JSON, HTML and\n"
          "  OOXML artifact was independently scanned for non-synthetic IP, MAC, email and serial\n"
          "  identities plus recognised credential residue; verified digests were rechecked at\n"
          "  coherent-set promotion.\n"
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
    # The engine's own account of what it refused, skipped or could not do. `ingest.run_redaction_folder`
    # deliberately keeps these EVEN WHEN the family came out complete (see its `engine_warnings` comment:
    # "Discarding them whenever the diff came back clean threw away the evidence precisely in the case
    # that looks healthy"), and then this function only printed them inside the INCOMPLETE branch below --
    # so on exactly that healthy-looking case they reached no human at all, and the key was a control in
    # name only. Printed here, before the early return, so both outcomes surface them.
    engine_warnings = report.get("engine_warnings") or []
    if engine_warnings:
        print(f"\n  The engine reported {len(engine_warnings)} warning(s) during this run:")
        for line in engine_warnings:
            print(f"    engine: {line}")
    missing = report.get("missing") or []
    if not missing:
        return 0
    print(f"\n  INCOMPLETE SET - {len(missing)} deliverable(s) were NOT produced:")
    for m in missing:
        print(f"    {m['state'].upper():9} {m['name']}  ({m['filename']})\n"
              f"              {m['detail']}")
    # (the engine's warnings are printed above, on BOTH the complete and incomplete paths)
    # Only promise the note if it was really written - a read-only folder, or a file of that
    # name Atlas did not author, means there is no note to go and read.
    note = report.get("incomplete_note")
    print(f"  The same list is saved as {note}." if note else
          "  (Could not write the note into the output folder - this console is the record.)")
    # Scoped to what THIS run wrote. The unqualified version ("What IS in the folder is redacted
    # and safe to share") was false whenever a STALE document from an earlier, uncertified run sat
    # in the folder — see ingest._mark_output_incomplete for the full reachable path.
    if report.get("stale_unsafe_marker"):
        print(f"  DO NOT SEND THIS FOLDER until you have read {ingest_mod.UNSAFE_MARKER} above -\n"
              f"  files from the earlier uncertified run may contain REAL client data.")
    else:
        print("  What THIS RUN wrote is independently verified; no prior canonical artifact was\n"
              "  carried into it. The SET is short: re-run, or tell the recipient which documents\n"
              "  are not included.")
    # Exit 3, not 0: this command exists to certify a deliverable set, so "0" must keep meaning
    # "complete and verified". Nothing consumes the code today, which is exactly why adopting it
    # now is free and adopting it later would be a breaking change. It is deliberately NOT 1 -
    # that is the redaction-failure code, and this output is safe.
    return 3


# ── --verify-manifest: does a delivered manifest still match its own seal? ──────
def run_verify_manifest(path: str, expect_root=None, metadata_only: bool = False) -> int:
    """Check a ``*.run_manifest.json`` from the stick. There is no Python on a field laptop, so
    ``python -m cisco_toolkit.manifest verify`` — the repo-side command — is unreachable there;
    this is the same check behind the one door, delegating to the same function so the two can
    never drift apart."""
    from cisco_toolkit import manifest as manifest_mod  # lazy: the engine-child path skips it

    res = manifest_mod.verify_file(
        path,
        expect_root=expect_root,
        metadata_only=metadata_only,
    )
    if res["ok"]:
        print(f"{APP_TITLE}: manifest OK - {res['reason']}")
    else:
        print(f"{APP_TITLE}: manifest INTEGRITY FAILURE - {res['reason']}", file=sys.stderr)
    for a in res["artifacts"]:
        if a["state"] != "ok":
            print(f"    [{a['state']}] {a['name']}", file=sys.stderr)
    if res["ok"] and not expect_root:
        print("  The seal is unkeyed, so this proves the file was not carelessly edited - NOT that\n"
              "  nobody re-sealed it. To pin it to the run, compare --expect-root against the\n"
              "  chain_root recorded in the report.")
    return 0 if res["ok"] else 4


def _preflight_file_bytes(path: Path, what: str) -> tuple[bytes, os.stat_result]:
    """Read one physical, single-link file while holding its exact handle."""
    metadata = path.lstat()
    reparse = int(getattr(metadata, "st_file_attributes", 0)) & int(
        getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )
    if path.is_symlink() or reparse or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise OSError(f"{what} must be a regular, non-reparse, single-link file")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        value = stream.read()
        after = os.fstat(stream.fileno())
    final = path.lstat()
    identities = {
        (item.st_dev, item.st_ino, item.st_mode, item.st_size, item.st_mtime_ns)
        for item in (metadata, opened, after, final)
    }
    if len(identities) != 1 or len(value) != final.st_size:
        raise OSError(f"{what} changed while read")
    return value, final


def _preflight_request(raw: bytes) -> dict:
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate request key")
            result[key] = value
        return result

    value = json.loads(
        raw.decode("utf-8", errors="strict"),
        object_pairs_hook=pairs,
        parse_constant=lambda token: (_ for _ in ()).throw(
            ValueError(f"non-finite request number {token}")
        ),
    )
    canonical = (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    if not isinstance(value, dict) or canonical != raw:
        raise ValueError("request is not a canonical JSON object")
    return value


def run_database_preflight(path: str) -> int:
    """Open and migrate one caller-supplied DB whose same-directory request is exact-bound."""
    nonce = os.environ.get(DATABASE_PREFLIGHT_ENV, "")
    if not re.fullmatch(r"[0-9a-f]{32}", nonce):
        print(f"{APP_TITLE}: database preflight requires a valid one-run request nonce.",
              file=sys.stderr)
        return 2
    db = Path(os.path.abspath(path))
    marker = db.with_name(DATABASE_PREFLIGHT_MARKER)
    try:
        if _frozen():
            active = (_exe_dir() / "data" / "assesshub.db").resolve(strict=False)
            if os.path.normcase(str(db.resolve(strict=True))) == os.path.normcase(str(active)):
                raise OSError("database preflight refuses the active frozen Atlas store")
        before_bytes, before_metadata = _preflight_file_bytes(db, "database preflight input")
        marker_bytes, _marker_metadata = _preflight_file_bytes(marker, "database preflight marker")
        request = _preflight_request(marker_bytes)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"{APP_TITLE}: database preflight request is invalid: {exc}", file=sys.stderr)
        return 1
    before = hashlib.sha256(before_bytes).hexdigest()
    expected_request = {
        "schema": "atlas.database-preflight-request/1",
        "nonce": nonce,
        "database_name": db.name,
        "input_copy_sha256": before,
        "input_copy_bytes": len(before_bytes),
        "requested_action": "open_migrate_copy_and_report",
    }
    if request != expected_request:
        print(f"{APP_TITLE}: database preflight request does not bind the exact input copy.",
              file=sys.stderr)
        return 1
    if any(db.with_name(db.name + suffix).exists() for suffix in ("-journal", "-wal", "-shm")):
        print(f"{APP_TITLE}: database preflight copy has live journal/WAL sidecars.", file=sys.stderr)
        return 1
    from portable.database_preflight import migrate_and_compare
    from .storage import Store

    try:
        logical_migration = migrate_and_compare(db, Store)
        counts = {
            row["name"]: row["row_count"]
            for row in logical_migration["after"]["tables"]
        }
    except Exception as exc:  # noqa: BLE001 - hidden field command must return bounded refusal
        print(f"{APP_TITLE}: database preflight failed: {exc}", file=sys.stderr)
        return 1
    try:
        after_bytes, after_metadata = _preflight_file_bytes(db, "migrated database preflight input")
        final_marker, _ = _preflight_file_bytes(marker, "database preflight marker")
    except OSError as exc:
        print(f"{APP_TITLE}: database preflight final binding failed: {exc}", file=sys.stderr)
        return 1
    if (before_metadata.st_dev, before_metadata.st_ino) != (
        after_metadata.st_dev, after_metadata.st_ino
    ):
        print(f"{APP_TITLE}: database preflight input identity was replaced.", file=sys.stderr)
        return 1
    if final_marker != marker_bytes:
        print(f"{APP_TITLE}: database preflight marker changed during migration.", file=sys.stderr)
        return 1
    after = hashlib.sha256(after_bytes).hexdigest()
    print(json.dumps({
        "schema": "atlas.database-preflight/1",
        "status": "pass",
        "request_sha256": hashlib.sha256(marker_bytes).hexdigest(),
        "request_nonce": nonce,
        "input_copy_binding": {
            "database_name": db.name,
            "bytes": len(before_bytes),
            "sha256": before,
        },
        "migrated_copy_sha256": after,
        "migrated_copy_bytes": len(after_bytes),
        "quick_check": "ok",
        "row_counts": counts,
        "logical_migration": logical_migration,
        "caller_supplied_database_modified": after != before,
        "authority_effect": "NONE",
    }, sort_keys=True, separators=(",", ":")))
    return 0


# ── entry point ─────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    # Frozen multiprocessing children re-enter here; this MUST precede everything else.
    multiprocessing.freeze_support()
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    if argv.count(LIVE_NETWORK_FLAG) > 1:
        print(f"{APP_TITLE}: {LIVE_NETWORK_FLAG} may be supplied only once.", file=sys.stderr)
        return 2
    live_requested = LIVE_NETWORK_FLAG in argv
    if live_requested:
        # The runtime hook checks this value dynamically at each connection. Removing the Atlas
        # flag before engine dispatch keeps the engine's own argparse surface unchanged.
        argv.remove(LIVE_NETWORK_FLAG)
    prior_live = os.environ.get("ATLAS_PORTABLE_ALLOW_LIVE_NETWORK")
    if live_requested:
        os.environ["ATLAS_PORTABLE_ALLOW_LIVE_NETWORK"] = "1"
    else:
        os.environ.pop("ATLAS_PORTABLE_ALLOW_LIVE_NETWORK", None)
    try:
        return _main_scoped(argv)
    finally:
        if prior_live is None:
            os.environ.pop("ATLAS_PORTABLE_ALLOW_LIVE_NETWORK", None)
        else:
            os.environ["ATLAS_PORTABLE_ALLOW_LIVE_NETWORK"] = prior_live


def _main_scoped(argv: list[str]) -> int:
    if argv and argv[0] == ENGINE_SENTINEL:
        return _run_engine(argv[1:])

    parser = argparse.ArgumentParser(
        prog="assesshub",
        description=f"{APP_TITLE} — serve AssessHub (production: no reload, no workers).")
    parser.add_argument("--host", default=_DEFAULT_HOST,
                        help=f"bind address (default {_DEFAULT_HOST}; non-loopback serves need "
                             "ASSESSHUB_TOKEN + TLS — see webapp/README.md)")
    parser.add_argument("--port", type=int, default=_DEFAULT_PORT,
                        help=f"port (default {_DEFAULT_PORT})")
    parser.add_argument("--db", default=None,
                        help="SQLite store path (default: $ASSESSHUB_DB, else the app default; "
                             "frozen builds default to data\\assesshub.db beside the exe)")
    parser.add_argument("--dist", default=None,
                        help="built frontend directory (default: $ASSESSHUB_DIST, the bundled "
                             "copy when frozen, else webapp/frontend/dist)")
    parser.add_argument("--ssl-certfile", default=os.environ.get("ASSESSHUB_TLS_CERT"),
                        help="TLS certificate PEM (or $ASSESSHUB_TLS_CERT)")
    parser.add_argument("--ssl-keyfile", default=os.environ.get("ASSESSHUB_TLS_KEY"),
                        help="TLS private-key PEM (or $ASSESSHUB_TLS_KEY)")
    parser.add_argument("--no-browser", action="store_true",
                        help="do not auto-open the UI in a browser")
    # Parsed early and removed before engine dispatch; this hidden declaration keeps the shipped
    # app-flag inventory mechanically complete for the field guide.
    parser.add_argument("--allow-live-network", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--selftest", action="store_true",
                        help="verify the silent-degrade assets (explorer template, OUI/port/EoL KBs, "
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
    parser.add_argument("--verify-manifest", default=None, metavar="FILE",
                        help="check a delivered <name>.run_manifest.json against its own hash chain "
                             "and exit (0 clean, 4 broken). Unkeyed: catches careless edits, not a "
                             "forger who re-seals - add --expect-root to pin it to its run")
    parser.add_argument("--database-preflight", default=None, metavar="COPY", help=argparse.SUPPRESS)
    parser.add_argument("--expect-root", default=None, metavar="SHA256",
                        help="with --verify-manifest: the chain_root recorded out of band (in the "
                             "report) that this file must match")
    parser.add_argument("--metadata-only", action="store_true",
                        help="with --verify-manifest: explicitly skip listed artifact bytes and "
                             "check only the sealed chain/metadata; use only when the files were "
                             "deliberately separated from the manifest")
    # Backward-compatible no-op: artifact-byte verification is now the safe default.
    parser.add_argument("--verify-artifacts", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--reuse-out", action="store_true",
                        help="with --redact-folder: render into an --out folder that already "
                             "holds a deliverable set. Refused by default: if that set is from "
                             "another job, any document this run fails to write leaves that "
                             "client's copy in this delivery under the right name")
    parser.add_argument("--version", action="version", version=_version_line())
    args = parser.parse_args(argv)

    # ── empty-string flag values ───────────────────────────────────────────────
    # argparse accepts `--flag ""`, and every dispatch below is a truthiness test, so an empty
    # value behaves EXACTLY as if the flag had never been passed. Measured, not theorised:
    # `--redact-folder ""` fell through the redaction branch AND its own refusal and STARTED THE
    # WEB SERVER (rc=0), so an engineer who asked for a share-safe deliverable set got a running
    # cockpit and a success code; `--out ""` did the same; `--db ""` quietly opened a different
    # store than the one they named. A field command that does something other than what was
    # asked, while reporting success, is the exact failure this surface exists to prevent.
    #
    # Guarded as a CLASS in one place rather than as N truthiness checks each of which has to be
    # remembered: the next path-valued flag someone adds is covered by construction. Empty is
    # never a meaningful value for any of these - a real path, host or hash is always required.
    for flag, value in (("--host", args.host), ("--db", args.db), ("--dist", args.dist),
                        ("--ssl-certfile", args.ssl_certfile),
                        ("--ssl-keyfile", args.ssl_keyfile),
                        ("--redact-folder", args.redact_folder), ("--out", args.out),
                        ("--verify-manifest", args.verify_manifest),
                        ("--database-preflight", args.database_preflight),
                        ("--expect-root", args.expect_root)):
        if value is None:
            continue
        bad = _unusable_value(str(value))
        if bad:
            print(f"{APP_TITLE}: {flag} {bad} Omit the flag to take the default, or pass a real "
                  f"one - Atlas will not guess which you meant.", file=sys.stderr)
            return 2

    # ── one job per invocation ─────────────────────────────────────────────────
    # The three subcommands below are dispatched by a fixed precedence with no cross-check, so
    # asking for two silently performed the FIRST and discarded the rest: measured,
    # `--verify-manifest X --redact-folder Y --out Z` printed "manifest OK" and returned 0 while
    # the redaction - a ten-minute job producing the deliverables the operator actually wanted -
    # never ran, with nothing on either stream saying so. Same "asked for X, silently got Y, exit
    # code says success" failure as the empty-value bug above, reached by a different route.
    jobs = [name for name, wanted in (("--selftest", args.selftest),
                                      ("--verify-manifest", args.verify_manifest is not None),
                                      ("--database-preflight", args.database_preflight is not None),
                                      ("--redact-folder", args.redact_folder is not None)) if wanted]
    if len(jobs) > 1:
        print(f"{APP_TITLE}: {' and '.join(jobs)} each ask Atlas to do a different job, and it "
              f"does one per run. Re-run them one at a time, in the order you want them.",
              file=sys.stderr)
        return 2

    if args.selftest:
        return run_selftest(dist_dir=args.dist, db_path=args.db)

    if args.verify_manifest is not None:    # `is not None`: --verify-manifest "" must be REFUSED,
        # not fall through and quietly start the server instead of running the check that was asked for
        if args.metadata_only and args.verify_artifacts:
            print(f"{APP_TITLE}: --metadata-only and --verify-artifacts are mutually exclusive.",
                  file=sys.stderr)
            return 2
        return run_verify_manifest(args.verify_manifest, args.expect_root, args.metadata_only)
    if args.database_preflight is not None:
        return run_database_preflight(args.database_preflight)
    if args.expect_root is not None or args.metadata_only or args.verify_artifacts:
        print(f"{APP_TITLE}: --expect-root, --metadata-only and --verify-artifacts only apply to "
              f"--verify-manifest.",
              file=sys.stderr)                                  # must still be refused, not ignored
        return 2

    # `is not None`, not truthiness: the class guard above already rejects "", but a dispatch site
    # should not silently depend on a distant check to be correct.
    #
    # This block is the UNION of two changes that collided here (#438's --reuse-out and the
    # empty-value guard). The merge resolved it by keeping BOTH blocks stacked, which is why the
    # second pair below used to be dead: `if args.redact_folder is not None` returns for every
    # non-None value, so `if args.redact_folder` after it could never run. The dead copy was the
    # ONLY one that forwarded `reuse_out`, so `--reuse-out` was silently dropped and Atlas refused
    # an --out folder the engineer had explicitly authorised (exit 1, caught by #438's own tests).
    # Keep this as ONE pair: `is not None` from the guard, `reuse_out` + the 3-flag message
    # from #438. Re-stacking them re-breaks whichever half is listed second.
    if args.redact_folder is not None:
        return run_redaction(args.redact_folder, args.out, args.redact_collection, args.reuse_out)
    if args.out is not None or args.redact_collection or args.reuse_out:
        print(f"{APP_TITLE}: --out, --redact-collection and --reuse-out only apply to "
              f"--redact-folder.", file=sys.stderr)
        return 2

    if bool(args.ssl_certfile) != bool(args.ssl_keyfile):
        print(f"{APP_TITLE}: --ssl-certfile and --ssl-keyfile must be supplied together.",
              file=sys.stderr)
        return 2
    if args.ssl_certfile:
        missing_tls = [p for p in (args.ssl_certfile, args.ssl_keyfile)
                       if not Path(str(p)).is_file()]
        if missing_tls:
            print(f"{APP_TITLE}: TLS certificate/key file not found: {missing_tls[0]}",
                  file=sys.stderr)
            return 2
    if _frozen() and not _bind_is_numeric_loopback(args.host):
        print(f"{APP_TITLE}: the portable Release-1 profile is loopback-only and requires a numeric loopback bind; "
              "--host must be 127.0.0.1 or ::1.", file=sys.stderr)
        return 2
    if not _bind_is_loopback(args.host):
        if not os.environ.get("ASSESSHUB_TOKEN"):
            print(f"{APP_TITLE}: a non-loopback bind requires ASSESSHUB_TOKEN.",
                  file=sys.stderr)
            return 2
        if not args.ssl_certfile:
            print(f"{APP_TITLE}: a non-loopback bearer-token bind requires TLS. Supply "
                  "--ssl-certfile and --ssl-keyfile (or ASSESSHUB_TLS_CERT / "
                  "ASSESSHUB_TLS_KEY).", file=sys.stderr)
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
    scheme = "https" if args.ssl_certfile else "http"
    url_host = f"[{args.host}]" if ":" in args.host and not args.host.startswith("[") else args.host
    url = f"{scheme}://{url_host}:{args.port}/"
    note = "" if (dist / "index.html").is_file() else \
        "   [frontend dist missing — API only; run --selftest]"
    print(f"{_version_line()}\n  {url}{note}")
    if not args.no_browser:
        _schedule_browser_open(url)

    import uvicorn  # lazy for the same reason

    uvicorn_kwargs = {"host": args.host, "port": args.port, "log_level": "info"}
    if args.ssl_certfile:
        uvicorn_kwargs.update(
            ssl_certfile=str(args.ssl_certfile), ssl_keyfile=str(args.ssl_keyfile))
    uvicorn.run(app, **uvicorn_kwargs)
    return 0


if __name__ == "__main__":  # python -m webapp.backend.serve
    raise SystemExit(main())
