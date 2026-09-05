"""Bundle manifest for the Atlas one-folder build (ADR-0004 P2) — pure and spec-independent.

`portable/atlas.spec` reads these lists; keeping them here (importable without PyInstaller) lets the
normal test gate pin the frozen bundle's contract — the exact assets whose absence `--selftest`
exists to catch, and the dynamic imports PyInstaller's static analysis cannot see:

* ``COLLECT_PARSE_V3_23_0`` — imported at runtime by ``serve._load_engine_main`` (the
  ``--run-engine`` child). Missing it re-creates the respawn-the-app trap the frozen-aware
  dispatch closed.
* ``webapp.backend.app`` — imported lazily inside ``serve.main`` (the engine child never pays
  for fastapi), so the server half of the app is invisible to static analysis.
* artifact renderer modules — imported inside the registry-declared generators; ADR-0004 D2 ships
  the 12-member pre-cutover family plus conditional PIR, so those dependencies are REQUIRED.
* uvicorn's loop/protocol/lifespan modules — resolved by name at runtime ("auto" selection).

The dist lands at ``_MEIPASS/webapp_dist`` — the exact directory ``serve._resolve_dist`` probes in
a frozen build (reconciled by ``tests/test_atlas_bundle.py``). ``pyproject.toml`` rides along so
``serve._release_version`` reports the real build version instead of falling back to (possibly
stale) installed-dist metadata.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from cisco_toolkit.brand_tokens import APP_NAME
from cisco_toolkit.docmeta import artifact_dependency_modules, artifact_writer_modules

#: Destination of the built SPA inside the bundle — MUST match serve._resolve_dist's frozen probe.
DIST_DEST = "webapp_dist"

#: The one-page field guide (ADR-0004 P3). It must land in the bundle ROOT beside the exe —
#: PyInstaller ≥6 puts spec `datas` under _internal\, where no field engineer would ever look —
#: so build_atlas.py copies :func:`root_files` there as a post-build step.
FIELD_README = "README-FIELD.txt"
PROJECT_LICENSE = "LICENSE"


def exe_name() -> str:
    """ADR-0004 D1: the exe is named by the ONE brand constant — a rename never touches the spec."""
    return APP_NAME


def bundle_datas(root: Path) -> List[Tuple[str, str]]:
    """(source, bundle-dest-dir) pairs for every non-code asset the frozen app needs."""
    root = Path(root)
    return [
        # The two gzipped knowledge packs and their required adjacent manifest
        # (silent-degrade class: lookups go empty without them).
        (str(root / "cisco_toolkit" / "data" / "oui_registry.tsv.gz"), "cisco_toolkit/data"),
        (str(root / "cisco_toolkit" / "data" / "port_registry.tsv.gz"), "cisco_toolkit/data"),
        (str(root / "cisco_toolkit" / "data" / "registry_manifest.json"), "cisco_toolkit/data"),
        # Compact, code-pinned Cisco EoL evidence.  Unlike the large registry source
        # inventories, this 13 KiB semantic fixture is required for runtime authority.
        (str(root / "cisco_toolkit" / "data" / "eol-bulletins.json"), "cisco_toolkit/data"),
        # The single-file explorer template every explorer render patches.
        (str(root / "cisco_toolkit" / "blast_radius_explorer.html"), "cisco_toolkit"),
        # The built SPA — the "one door" UI.
        (str(root / "webapp" / "frontend" / "dist"), DIST_DEST),
        # Demo seed fixture (POST /api/demo/seed) — zero-setup exploration in the field.
        (str(root / "webapp" / "sample_data" / "sample_fleet.snapshot.json"), "webapp/sample_data"),
        # serve._release_version prefers this over installed-dist metadata (which on a dev box can
        # be STALE — observed: pip metadata 3.26.0 vs checkout 3.31.0).
        (str(root / "pyproject.toml"), "."),
    ]


def root_files(root: Path) -> List[str]:
    """Files copied to the bundle ROOT (beside the exe) by build_atlas.py after PyInstaller runs
    — the visible-to-the-engineer tier the spec's `datas` (buried in _internal\\) cannot serve."""
    return [
        str(Path(root) / "portable" / FIELD_README),
        str(Path(root) / PROJECT_LICENSE),
    ]


def missing_data_sources(root: Path) -> List[str]:
    """Sources from :func:`bundle_datas` + :func:`root_files` absent on disk — the build must
    refuse while any exist (--selftest's fail-loud doctrine applied at build time)."""
    sources = [src for src, _dest in bundle_datas(Path(root))] + root_files(Path(root))
    return [src for src in sources if not Path(src).exists()]


def hidden_imports() -> List[str]:
    """Dynamic imports PyInstaller cannot discover statically (see module docstring)."""
    return [
        # frozen engine-child dispatch (serve._load_engine_main)
        "COLLECT_PARSE_V3_23_0",
        # lazy server half (serve.main imports it after the sentinel check)
        "webapp.backend.app",
        # serve.run_verify_manifest imports this lazily, so --verify-manifest is the one field
        # command whose module PyInstaller only sees inside a function body. README-FIELD teaches
        # that command; a ModuleNotFoundError at a client site is the failure this line prevents.
        "cisco_toolkit.manifest",
        # D2: derive lazy renderer imports from the registry that owns the artifact lifecycle.
        *artifact_dependency_modules(),
        *artifact_writer_modules(),
        # fastapi's multipart form handling resolves this at runtime
        "multipart",
        # uvicorn "auto" selection — resolved by name at runtime
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.protocols.websockets.wsproto_impl",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "uvicorn.lifespan.off",
    ]
