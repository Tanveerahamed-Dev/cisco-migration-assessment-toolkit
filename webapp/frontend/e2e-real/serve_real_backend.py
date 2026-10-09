"""Start the REAL AssessHub backend for the real-backend browser E2E tier.

Test infrastructure for ``webapp/frontend/playwright.real.config.ts`` only. Playwright's
``webServer`` runs this after building the SPA; the browser then drives the real FastAPI
application, the real SQLite store and the real engine child process -- nothing is mocked. The
application never imports this file, and the sdist never ships it (MANIFEST.in includes only
``webapp/frontend/dist`` from the frontend tree).

In order, it:

1. Recreates ``--run-dir`` from empty. An existing directory is emptied only when it is empty or
   carries this launcher's marker, so a mistyped path can never delete unrelated data.
2. Writes the repository's synthetic offline collection (``tests/synthetic_fixtures.py``:
   hand-authored ``show`` outputs, no real network data) as ``--collection-zip``: per-device
   folders under one wrapping folder and no ``devices.json``, the archive shape the backend's own
   real-engine ingest test uses. ``--collection-manifest`` records the device folders and the
   commands each one carries, so the spec can state its fixture preconditions from the fixture
   itself instead of restating them.
3. Serves AssessHub through its production entry point (``webapp.backend.serve.main``): numeric
   loopback bind, a fresh store under ``--run-dir``, the freshly built SPA from ``--dist``, no
   browser, and no token or TLS setting inherited from the caller's environment.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
#: The synthetic collection this tier ingests (repository-relative, POSIX form). webapp CI's
#: scope classifier must treat it as relevant (tests/test_webapp_ci_scope.py pins that).
FIXTURE_MODULE = "tests/synthetic_fixtures.py"
#: Present only in a run directory this launcher created; required before one is ever emptied.
RUN_DIR_MARKER = ".assesshub-real-e2e-run"
#: Inherited settings that would change what is served: a token turns on the sign-in gate, and the
#: TLS pair is read by serve.main's own argument defaults.
SCRUBBED_ENVIRONMENT = ("ASSESSHUB_TOKEN", "ASSESSHUB_TLS_CERT", "ASSESSHUB_TLS_KEY")
MANIFEST_SCHEMA = "real_backend_e2e_collection/1"


def _fail(message: str) -> SystemExit:
    return SystemExit(f"real-backend e2e: {message}")


def fresh_run_dir(run_dir: Path) -> None:
    """Create ``run_dir`` empty, emptying it first only when this launcher provably owns it."""
    if run_dir.is_symlink():
        raise _fail(f"--run-dir is a link, refusing to use it: {run_dir}")
    if run_dir.exists():
        if not run_dir.is_dir():
            raise _fail(f"--run-dir is not a directory: {run_dir}")
        if any(run_dir.iterdir()) and not (run_dir / RUN_DIR_MARKER).is_file():
            raise _fail(f"refusing to empty a non-empty --run-dir this launcher did not create: {run_dir}")
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    (run_dir / RUN_DIR_MARKER).write_text(
        "created by webapp/frontend/e2e-real/serve_real_backend.py; emptied on every start\n",
        encoding="utf-8",
    )


def load_fixtures():
    """Load the synthetic fixture module by path; tests/ is not a package."""
    path = REPO_ROOT / FIXTURE_MODULE
    spec = importlib.util.spec_from_file_location("_real_backend_e2e_synthetic_fixtures", path)
    if spec is None or spec.loader is None:
        raise _fail(f"cannot load {FIXTURE_MODULE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_collection(fixtures, staging: Path, archive: Path, manifest: Path) -> list[str]:
    """Write the synthetic collection ZIP plus its manifest; return the device folder names."""
    collection = staging / "export" / "fleet"
    fixtures.write_collection(str(collection))
    members = sorted(path for path in staging.rglob("*") if path.is_file())
    if not members:
        raise _fail(f"{FIXTURE_MODULE} wrote no capture files")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for member in members:
            bundle.write(member, member.relative_to(staging).as_posix())
    devices = sorted(path.name for path in collection.iterdir() if path.is_dir())
    commands = {
        host: sorted(command for command in fixtures.COLLECTIONS[host][1])
        for host in devices
    }
    manifest.write_text(
        json.dumps(
            {"schema": MANIFEST_SCHEMA, "source": FIXTURE_MODULE, "archive": archive.name,
             "devices": devices, "commands": commands},
            indent=2, sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    return devices


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve AssessHub for the real-backend browser E2E tier.")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--collection-zip", type=Path, required=True)
    parser.add_argument("--collection-manifest", type=Path, required=True)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args(argv)

    run_dir = args.run_dir.resolve()
    archive = args.collection_zip.resolve()
    manifest = args.collection_manifest.resolve()
    dist = args.dist.resolve()
    if archive.parent != run_dir or manifest.parent != run_dir or archive == manifest:
        parser.error("--collection-zip and --collection-manifest must be two files directly inside --run-dir")
    if not (dist / "index.html").is_file():
        parser.error(f"--dist holds no built SPA (index.html missing): {dist}")
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535")

    fresh_run_dir(run_dir)
    staging = run_dir / "collection-staging"
    devices = write_collection(load_fixtures(), staging, archive, manifest)
    shutil.rmtree(staging)
    data_dir = run_dir / "data"
    data_dir.mkdir()

    for name in SCRUBBED_ENVIRONMENT:
        os.environ.pop(name, None)
    # Serve THIS checkout, never an installed copy or another worktree that happens to be importable.
    sys.path.insert(0, str(REPO_ROOT))
    from webapp.backend import serve

    if not Path(serve.__file__).resolve().is_relative_to(REPO_ROOT):
        raise _fail("webapp.backend.serve was imported from outside this checkout")
    print(f"real-backend e2e: serving {archive.name} ({', '.join(devices)}) on 127.0.0.1:{args.port}",
          flush=True)
    return serve.main([
        "--host", "127.0.0.1",
        "--port", str(args.port),
        "--db", str(data_dir / "assesshub.db"),
        "--dist", str(dist),
        "--no-browser",
    ])


if __name__ == "__main__":
    raise SystemExit(main())
