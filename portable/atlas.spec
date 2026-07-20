# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Atlas one-folder build (ADR-0004 P2).

Build from the repo root:  python -m PyInstaller portable/atlas.spec --noconfirm
(or just run portable/build_atlas.py, which also pre-checks assets and smoke-tests the result).

Decisions this file encodes:
* one-FOLDER (not one-file): faster start, transparent contents, and the AssessKit stick layout
  (app\\ replaced wholesale on update, data\\ the only writable dir).
* console=True (ADR-0004 D3): the live-SSH credential prompt needs a real terminal — windowed
  builds crash at sys.stdin.isatty() (COLLECT_PARSE_V3_23_0.py:1174).
* The manifest lives in portable/atlas_bundle.py so the NORMAL test gate pins it without
  PyInstaller installed; this spec stays a thin consumer.
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 — SPECPATH is injected by PyInstaller
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from portable.atlas_bundle import (  # noqa: E402
    bundle_datas,
    exe_name,
    hidden_imports,
    missing_data_sources,
)

_missing = missing_data_sources(ROOT)
if _missing:
    raise SystemExit(
        "Refusing to build an Atlas bundle with missing assets (the frozen app would only find "
        f"out via --selftest in the field): {_missing}\n"
        "Build the frontend first: cd webapp/frontend && npm ci && npm run build"
    )

a = Analysis(  # noqa: F821
    [str(ROOT / "portable" / "atlas_entry.py")],
    pathex=[str(ROOT)],
    datas=bundle_datas(ROOT),
    # netmiko resolves vendor drivers via its class map — take the whole tree; the rest of the
    # dynamic seams are pinned (with rationale) in atlas_bundle.hidden_imports.
    hiddenimports=hidden_imports() + collect_submodules("netmiko"),
    runtime_hooks=[str(ROOT / "portable" / "rthook_stdio_utf8.py")],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    exclude_binaries=True,
    name=exe_name(),
    console=True,  # D3 — never windowed
    upx=False,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name=exe_name(),  # dist/Atlas/ — the folder that goes on the stick as app\
    upx=False,
)
