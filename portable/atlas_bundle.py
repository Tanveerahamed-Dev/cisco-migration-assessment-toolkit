"""Bundle manifest for the Atlas one-folder build (ADR-0004 P2) — pure and spec-independent.

`portable/atlas.spec` reads these lists; keeping them here (importable without PyInstaller) lets the
normal test gate pin the frozen bundle's contract — the exact assets whose absence `--selftest`
exists to catch, and the dynamic imports PyInstaller's static analysis cannot see:

* ``COLLECT_PARSE_V3_23_0`` — imported at runtime by ``serve._load_engine_main`` (the
  ``--run-engine`` child). Missing it re-creates the respawn-the-app trap the frozen-aware
  dispatch closed.
* ``webapp.backend.app`` — imported lazily inside ``serve.main`` (the engine child never pays
  for fastapi), so the server half of the app is invisible to static analysis.
* ``docx`` / ``pptx`` — imported inside the deliverable generators (optional-dependency design);
  ADR-0004 D2 ships the full 12-document family, so in the bundle they are REQUIRED.
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

#: Destination of the built SPA inside the bundle — MUST match serve._resolve_dist's frozen probe.
DIST_DEST = "webapp_dist"


def exe_name() -> str:
    """ADR-0004 D1: the exe is named by the ONE brand constant — a rename never touches the spec."""
    return APP_NAME


def bundle_datas(root: Path) -> List[Tuple[str, str]]:
    """(source, bundle-dest-dir) pairs for every non-code asset the frozen app needs."""
    root = Path(root)
    return [
        # The two gzipped knowledge packs (silent-degrade class: lookups go empty without them).
        (str(root / "cisco_toolkit" / "data" / "oui_registry.tsv.gz"), "cisco_toolkit/data"),
        (str(root / "cisco_toolkit" / "data" / "port_registry.tsv.gz"), "cisco_toolkit/data"),
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


def missing_data_sources(root: Path) -> List[str]:
    """Sources from :func:`bundle_datas` absent on disk — the build must refuse while any exist
    (--selftest's fail-loud doctrine applied at build time)."""
    return [src for src, _dest in bundle_datas(Path(root)) if not Path(src).exists()]


def hidden_imports() -> List[str]:
    """Dynamic imports PyInstaller cannot discover statically (see module docstring)."""
    return [
        # frozen engine-child dispatch (serve._load_engine_main)
        "COLLECT_PARSE_V3_23_0",
        # lazy server half (serve.main imports it after the sentinel check)
        "webapp.backend.app",
        # D2: the full document family ships — these are lazy optional-deps in the generators
        "docx",
        "pptx",
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
