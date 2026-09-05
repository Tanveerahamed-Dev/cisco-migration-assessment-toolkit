"""The Atlas one-folder bundle manifest (ADR-0004 P2) — portable/atlas_bundle.py.

Pins the frozen bundle's contract WITHOUT running PyInstaller: the assets --selftest guards must
all be in datas, the dynamic imports static analysis cannot see must all be hidden-imports, and
the dist destination must be the exact directory the entry module probes when frozen."""

import subprocess
import sys
from pathlib import Path

from portable import atlas_bundle

ROOT = Path(__file__).resolve().parents[1]


def test_smoke_server_is_reaped_after_forced_termination():
    from portable.build_atlas import _stop_server

    class Server:
        def __init__(self):
            self.calls = []

        def terminate(self):
            self.calls.append("terminate")

        def kill(self):
            self.calls.append("kill")

        def wait(self, *, timeout):
            self.calls.append(("wait", timeout))
            if self.calls.count(("wait", timeout)) == 1:
                raise subprocess.TimeoutExpired("Atlas.exe", timeout)
            return 0

    server = Server()
    _stop_server(server, timeout=3)
    assert server.calls == ["terminate", ("wait", 3), "kill", ("wait", 3)]


def test_exe_name_is_the_brand_constant():
    from cisco_toolkit.brand_tokens import APP_NAME

    assert atlas_bundle.exe_name() == APP_NAME == "Atlas"  # ADR-0004 D1


def test_datas_cover_every_selftest_guarded_asset():
    sources = {Path(src).name: dest for src, dest in atlas_bundle.bundle_datas(ROOT)}
    assert sources["oui_registry.tsv.gz"] == "cisco_toolkit/data"
    assert sources["port_registry.tsv.gz"] == "cisco_toolkit/data"
    assert sources["registry_manifest.json"] == "cisco_toolkit/data"
    assert sources["eol-bulletins.json"] == "cisco_toolkit/data"
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
    assert atlas_bundle.PROJECT_LICENSE in names
    assert all(Path(p).is_file() for p in atlas_bundle.root_files(ROOT))


def test_spec_installs_the_default_offline_network_runtime_hook():
    spec = (ROOT / "portable" / "atlas.spec").read_text(encoding="utf-8")
    assert "rthook_network_boundary.py" in spec
    assert "version=pyinstaller_version_info(ROOT)" in spec
    assert (ROOT / "portable" / "rthook_network_boundary.py").is_file()
    assert (ROOT / "portable" / "network_boundary.py").is_file()


def test_windows_version_info_is_derived_from_version_brand_and_license_owners():
    from cisco_toolkit.brand_tokens import APP_NAME
    from portable.windows_version_info import (
        fixed_file_version,
        project_version,
        version_expectations,
        version_strings,
    )

    version = project_version(ROOT)
    strings = version_strings(ROOT)
    assert strings == {
        "CompanyName": "Tanveerahamed-Dev",
        "FileDescription": "Atlas - by Tanveer Ahamed",
        "FileVersion": version,
        "InternalName": APP_NAME,
        "LegalCopyright": "Copyright (c) 2026 Tanveerahamed-Dev. All rights reserved.",
        "OriginalFilename": "Atlas.exe",
        "ProductName": APP_NAME,
        "ProductVersion": version,
    }
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").splitlines()[0] == strings["LegalCopyright"]
    assert fixed_file_version("3.33.0a1") < fixed_file_version("3.33.0b1")
    assert fixed_file_version("3.33.0b1") < fixed_file_version("3.33.0rc1")
    assert fixed_file_version("3.33.0rc1") < fixed_file_version("3.33.0")
    assert fixed_file_version("3.33.0") < fixed_file_version("3.33.0.post1")
    fixed = ".".join(str(item) for item in fixed_file_version(version))
    assert version_expectations(ROOT) == {
        **strings,
        "FixedFileVersion": fixed,
        "FixedProductVersion": fixed,
    }


def test_windows_version_info_gap_names_any_policy_facing_drift():
    from portable.build_atlas import windows_version_info_gap

    expected = {"ProductName": "Atlas", "ProductVersion": "3.33.0rc1"}
    assert windows_version_info_gap(dict(expected), expected) == ""
    gap = windows_version_info_gap({"ProductName": "Atlas", "ProductVersion": ""}, expected)
    assert "ProductVersion" in gap and "3.33.0rc1" in gap


def test_hidden_imports_cover_the_dynamic_seams():
    from cisco_toolkit.docmeta import artifact_dependency_modules, artifact_writer_modules

    hidden = set(atlas_bundle.hidden_imports())
    # the frozen engine-child dispatch — missing this re-creates the respawn-the-app trap
    assert "COLLECT_PARSE_V3_23_0" in hidden
    # serve.main imports the server half lazily (the engine child never pays for fastapi)
    assert "webapp.backend.app" in hidden
    # --verify-manifest's module is imported inside a function body too, and README-FIELD teaches
    # that command to an engineer with no Python and no second machine
    assert "cisco_toolkit.manifest" in hidden
    # ADR-0004 D2: every registry-owned lazy renderer must ship.
    dependencies = set(artifact_dependency_modules())
    assert dependencies and dependencies <= hidden
    writers = set(artifact_writer_modules())
    assert writers and writers <= hidden
    # uvicorn's runtime "auto" selection
    assert {"uvicorn.loops.auto", "uvicorn.protocols.http.auto", "uvicorn.lifespan.on"} <= hidden


def test_renderer_hidden_imports_are_derived_not_a_second_static_list(monkeypatch):
    """Mutate the owner seam: the bundle manifest must immediately follow it."""
    monkeypatch.setattr(atlas_bundle, "artifact_dependency_modules",
                        lambda: ("registry_probe_renderer",))
    monkeypatch.setattr(atlas_bundle, "artifact_writer_modules",
                        lambda: ("registry_probe_writer",))
    hidden = atlas_bundle.hidden_imports()
    assert "registry_probe_renderer" in hidden and "registry_probe_writer" in hidden


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


# ── the build's --version smoke step must actually prove what it claims ─────────────────────────

def test_version_gap_rejects_a_bundle_that_lost_pyproject():
    """`pyproject.toml` is bundled so serve._release_version reports the BUILD's version instead of
    (possibly stale) installed-dist metadata — test_datas_cover_every_selftest_guarded_asset pins
    that it is listed. Nothing proved it LANDED: missing_data_sources only checks the source exists
    on the build box, and --selftest never looks at it. The smoke step that claims to prove it
    asserted only `"Atlas" in stdout`, which the degraded output satisfies."""
    from portable.build_atlas import version_gap

    good = "Atlas - release 3.31.0 (checkout) - engine schema 41"
    assert version_gap(good, "3.31.0 (checkout)") == ""
    # what a frozen bundle prints when pyproject.toml is not inside it — the old check PASSED this
    degraded = "Atlas - release unpackaged - engine schema 41"
    assert "Atlas" in degraded                                  # i.e. the old predicate was happy
    assert version_gap(degraded, "3.31.0 (checkout)"), "a bundle reporting no release must FAIL"
    # and a stale pip-metadata fallback, the case the docstring names
    assert version_gap("Atlas - release 3.26.0 - engine schema 41", "3.31.0 (checkout)")
    assert version_gap("", "3.31.0 (checkout)")


def test_expected_release_reads_the_checkout_through_the_apps_own_owner():
    """One source of truth for the version: the build asks serve._release_version, the same function
    the running app answers --version with, rather than re-parsing pyproject itself."""
    import sys as _sys

    if str(ROOT) not in _sys.path:
        _sys.path.insert(0, str(ROOT))
    from portable.build_atlas import expected_release
    from webapp.backend.serve import _release_version

    assert expected_release() == _release_version() != ""
