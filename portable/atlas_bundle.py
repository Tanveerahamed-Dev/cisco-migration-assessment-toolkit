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
a frozen build (reconciled by ``tests/test_atlas_bundle.py``). Atlas Scope's hub build (the /scope
view, atlas-scope ``npm run build:hub``) is its OWN member at ``_MEIPASS/atlas_scope_dist`` — the
directory ``serve._resolve_scope_dist`` probes — shipped file by file without sourcemaps. ``pyproject.toml`` rides along so
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

#: Atlas Scope's hub build (atlas-scope ``npm run build:hub``; base /scope/, reads every snapshot at
#: run time from AssessHub's guarded /api) — the build AssessHub serves at /scope from a checkout
#: (``webapp.backend.app._REPO_ATLAS_SCOPE_DIST``; reconciled by tests/test_atlas_bundle.py).
SCOPE_DIST_SOURCE = "atlas-scope/dist-hub"
#: Its destination inside the bundle — MUST match serve._resolve_scope_dist's frozen probe.
SCOPE_DIST_DEST = "atlas_scope_dist"

#: Sources that are BUILD OUTPUT rather than tracked files: the only sources a fresh checkout may
#: lack (the build creates them first; atlas.spec refuses while any is missing).
BUILD_OUTPUTS = ("webapp/frontend/dist", SCOPE_DIST_SOURCE)

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
        # Atlas Scope's hub build, served by the same door at /scope.
        *scope_dist_datas(root),
        # Demo seed fixture (POST /api/demo/seed) — zero-setup exploration in the field.
        (str(root / "webapp" / "sample_data" / "sample_fleet.snapshot.json"), "webapp/sample_data"),
        # serve._release_version prefers this over installed-dist metadata (which on a dev box can
        # be STALE — observed: pip metadata 3.26.0 vs checkout 3.31.0).
        (str(root / "pyproject.toml"), "."),
    ]


def _is_sourcemap(path: Path) -> bool:
    return path.name.casefold().endswith(".map")


def scope_dist_datas(root: Path) -> List[Tuple[str, str]]:
    """(source file, bundle-dest-dir) for every file of the Atlas Scope hub build EXCEPT sourcemaps,
    keeping its layout under :data:`SCOPE_DIST_DEST`. A sourcemap is never served usefully in the
    field and carries the full source text, so it is not shipped (the /scope privacy scan would also
    read it). When the build is absent, or holds no shell (``index.html``), the missing path itself is
    returned so :func:`missing_data_sources` refuses the build instead of shipping a silent gap."""
    dist = Path(root) / SCOPE_DIST_SOURCE
    if not dist.is_dir():
        return [(str(dist), SCOPE_DIST_DEST)]
    datas: List[Tuple[str, str]] = []
    for path in sorted(dist.rglob("*")):
        if not path.is_file() or _is_sourcemap(path):
            continue
        parent = path.parent.relative_to(dist).as_posix()
        datas.append((str(path), SCOPE_DIST_DEST if parent == "." else f"{SCOPE_DIST_DEST}/{parent}"))
    shell = dist / "index.html"
    if (str(shell), SCOPE_DIST_DEST) not in datas:
        datas.append((str(shell), SCOPE_DIST_DEST))
    return datas


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
        # The projection accelerator's ABI3 extension must be in the frozen runtime.
        "jsonschema_rs.jsonschema_rs",
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


def package_data_modules() -> tuple[str, ...]:
    """Installed runtime packages whose resources have no upstream PyInstaller hook.

    jsonschema imports the installed IRI format checker even when the caller does not request
    format validation. Its module reads syntax_rfc3987.lark during import; Python modules alone
    therefore cannot start the frozen API. The spec collects package data through this owner.
    """
    return ("rfc3987_syntax",)


def package_metadata_distributions() -> tuple[str, ...]:
    """Native-provider distributions whose reviewed metadata must survive freezing.

    The SBOM is retained evidence, not proof of the linked Rust component set or their
    individual license texts. The package's MIT text is a separately pinned fallback.
    """
    return ("jsonschema-rs",)


def native_runtime_files() -> dict[str, dict[str, str | int] | None]:
    """Required Windows wheel members; normal manifests bind every retained byte.

    Pin the upstream SBOM representation so omission or replacement cannot be hidden by
    reauthoring the surrounding release manifest. PE code uses the ordinary signing custody.
    """
    metadata = "_internal/jsonschema_rs-0.58.4.dist-info/"
    return {
        # The stock fallback's private legacy seam checks this distribution at runtime.
        # The upstream hook-jsonschema collects it; the actual frozen selftest checks lookup.
        "_internal/jsonschema-4.26.0.dist-info/METADATA": None,
        "_internal/jsonschema-4.26.0.dist-info/WHEEL": None,
        "_internal/jsonschema_rs/jsonschema_rs.pyd": None,
        metadata + "METADATA": None,
        metadata + "WHEEL": None,
        metadata + "sboms/jsonschema-py.cyclonedx.json": {
            "bytes": 245181,
            "sha256": "fc02e97118764c2c8e0e67bc1f0fc554cda259a4925e944677894d0792cf6a88",
        },
    }


def package_metadata_datas(copy_metadata) -> List[Tuple[str, str]]:
    """Select wheel metadata without shipping installer-added local provenance.

    PyInstaller's collector locates the distribution; this owner selects individual files.
    In particular, direct_url.json can contain a local wheel path. INSTALLER, REQUESTED and
    the installation-modified RECORD are not required for runtime version lookup or SBOM custody.
    """
    result = []
    for distribution in package_metadata_distributions():
        located = copy_metadata(distribution)
        if len(located) != 1:
            raise ValueError("native validator metadata location is ambiguous")
        source, destination = located[0]
        prefix = "_internal/" + destination + "/"
        required = [path.removeprefix(prefix) for path in native_runtime_files()
                    if path.startswith(prefix)]
        if not required:
            raise ValueError("native validator metadata version differs")
        directory = Path(source).resolve(strict=True)
        for relative in required:
            path = Path(source) / relative
            if (not path.is_file() or path.is_symlink()
                    or not path.resolve(strict=True).is_relative_to(directory)):
                raise ValueError("native validator metadata file is absent or outside its package")
            parent = Path(destination) / Path(relative).parent
            result.append((str(path), parent.as_posix()))
    return result


def reviewed_validator_metadata_toc(rows: list) -> list:
    """Remove installer provenance even when an upstream hook collected full metadata.

    Retain upstream license files and entry metadata. Only the two reviewed validator
    distributions are affected; the native SBOM and both version metadata files stay intact.
    """
    directories = {Path(path).parts[1].casefold() for path in native_runtime_files()
                   if Path(path).parts[1].endswith(".dist-info")}
    installer_files = {"direct_url.json", "installer", "requested", "record"}
    result = []
    for row in rows:
        parts = str(row[0]).replace("\\", "/").casefold().split("/")
        if len(parts) == 2 and parts[0] in directories and parts[1] in installer_files:
            continue
        result.append(row)
    return result
