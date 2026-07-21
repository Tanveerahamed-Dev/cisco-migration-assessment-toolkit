"""The Atlas one-folder bundle manifest (ADR-0004 P2) — portable/atlas_bundle.py.

Pins the frozen bundle's contract WITHOUT running PyInstaller: the assets --selftest guards must
all be in datas, the dynamic imports static analysis cannot see must all be hidden-imports, and
the dist destination must be the exact directory the entry module probes when frozen."""

import sys
from pathlib import Path

from portable import atlas_bundle

ROOT = Path(__file__).resolve().parents[1]


def test_exe_name_is_the_brand_constant():
    from cisco_toolkit.brand_tokens import APP_NAME

    assert atlas_bundle.exe_name() == APP_NAME == "Atlas"  # ADR-0004 D1


def test_datas_cover_every_selftest_guarded_asset():
    sources = {Path(src).name: dest for src, dest in atlas_bundle.bundle_datas(ROOT)}
    assert sources["oui_registry.tsv.gz"] == "cisco_toolkit/data"
    assert sources["port_registry.tsv.gz"] == "cisco_toolkit/data"
    assert sources["blast_radius_explorer.html"] == "cisco_toolkit"
    assert sources["dist"] == atlas_bundle.DIST_DEST
    assert sources["sample_fleet.snapshot.json"] == "webapp/sample_data"
    assert sources["pyproject.toml"] == "."  # release-version source beats stale pip metadata


def test_tracked_sources_exist_on_a_checkout():
    """Everything except the built dist is tracked — it must exist on any checkout. The dist is
    build output (engine CI has no node), so it is the only tolerated absence here."""
    missing = {Path(p).name for p in atlas_bundle.missing_data_sources(ROOT)}
    assert missing <= {"dist"}, f"tracked bundle sources missing from the checkout: {missing}"


def test_missing_sources_fail_loud_on_an_empty_root(tmp_path):
    missing = atlas_bundle.missing_data_sources(tmp_path)
    assert len(missing) == (len(atlas_bundle.bundle_datas(tmp_path))
                            + len(atlas_bundle.root_files(tmp_path)))


def test_root_files_ship_the_field_guide_beside_the_exe():
    """ADR-0004 P3: the field discipline rides the stick — at the bundle ROOT, not _internal\\
    (PyInstaller ≥6 buries spec datas there). Its source is tracked, so it must exist here."""
    names = {Path(p).name for p in atlas_bundle.root_files(ROOT)}
    assert atlas_bundle.FIELD_README in names
    assert all(Path(p).is_file() for p in atlas_bundle.root_files(ROOT))


def test_hidden_imports_cover_the_dynamic_seams():
    hidden = set(atlas_bundle.hidden_imports())
    # the frozen engine-child dispatch — missing this re-creates the respawn-the-app trap
    assert "COLLECT_PARSE_V3_23_0" in hidden
    # serve.main imports the server half lazily (the engine child never pays for fastapi)
    assert "webapp.backend.app" in hidden
    # ADR-0004 D2: the full document family ships — docx/pptx are lazy optional-deps
    assert {"docx", "pptx"} <= hidden
    # uvicorn's runtime "auto" selection
    assert {"uvicorn.loops.auto", "uvicorn.protocols.http.auto", "uvicorn.lifespan.on"} <= hidden


def test_dist_dest_matches_the_entry_modules_frozen_probe(monkeypatch, tmp_path):
    """Reconcile the two owners of the 'where does the SPA live when frozen' fact: the bundle's
    DIST_DEST and serve._resolve_dist's _MEIPASS probe must name the SAME directory."""
    if str(ROOT) not in sys.path:  # webapp is a namespace package off the repo root
        sys.path.insert(0, str(ROOT))
    from webapp.backend import serve

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.delenv("ASSESSHUB_DIST", raising=False)
    assert serve._resolve_dist(None) == tmp_path / atlas_bundle.DIST_DEST
