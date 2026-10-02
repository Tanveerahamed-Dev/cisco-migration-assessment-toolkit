"""The Atlas one-folder bundle manifest (ADR-0004 P2) — portable/atlas_bundle.py.

Pins the frozen bundle's contract WITHOUT running PyInstaller: the assets --selftest guards must
all be in datas, the dynamic imports static analysis cannot see must all be hidden-imports, and
the dist destination must be the exact directory the entry module probes when frozen."""

import os
import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

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


def test_smoke_directory_census_allows_only_detached_runtime_data(tmp_path):
    from cisco_toolkit import __version__ as engine_schema_version
    from portable.build_atlas import _bundle_directory_state, _detach_runtime_data, _directory_gap

    bundle = tmp_path / "Atlas"
    internal = bundle / "_internal"
    internal.mkdir(parents=True)
    (bundle / "Atlas.exe").write_bytes(b"original executable")
    (internal / "runtime.bin").write_bytes(b"runtime")
    before = _bundle_directory_state(bundle)

    data = bundle / "data"
    data.mkdir()
    (data / "assesshub.db").write_bytes(b"mutable database")
    log_name = f"cisco_migration_autofill_v{engine_schema_version.replace('.', '_')}.log"
    (data / log_name).write_bytes(b"audit")
    _detach_runtime_data(bundle, tmp_path / "runtime-data")
    assert _directory_gap(before, _bundle_directory_state(bundle)) == ""

    (bundle / "unexpected-empty-directory").mkdir()
    gap = _directory_gap(before, _bundle_directory_state(bundle))
    assert "added=" in gap and "unexpected-empty-directory" in gap


def test_smoke_detaches_only_a_real_runtime_data_directory(tmp_path):
    from portable.build_atlas import _detach_runtime_data

    bundle = tmp_path / "Atlas"
    data = bundle / "data"
    data.mkdir(parents=True)
    (data / "assesshub.db").write_bytes(b"database")
    detached = tmp_path / "runtime-data"

    _detach_runtime_data(bundle, detached)
    assert not data.exists()
    assert (detached / "assesshub.db").read_bytes() == b"database"


def test_smoke_directory_census_refuses_a_reparse_subtree(tmp_path):
    from portable.build_atlas import _bundle_directory_state

    bundle = tmp_path / "Atlas"
    outside = tmp_path / "outside"
    bundle.mkdir()
    outside.mkdir()
    link = bundle / "linked"
    if os.name == "nt":
        created = subprocess.run(
            [os.environ.get("ComSpec", "cmd.exe"), "/c", "mklink", "/J", str(link), str(outside)],
            capture_output=True,
            text=True,
            check=False,
        )
        if created.returncode:
            pytest.skip(f"directory junction unavailable: {created.stderr or created.stdout}")
    else:
        link.symlink_to(outside, target_is_directory=True)
    try:
        with pytest.raises(SystemExit, match="reparse or symbolic-link"):
            _bundle_directory_state(bundle)
    finally:
        if os.name == "nt":
            os.rmdir(link)
        else:
            link.unlink()


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


def test_spec_collects_runtime_package_resources_from_the_pure_manifest(monkeypatch):
    """The IRI checker reads its grammar at import time; importing Python code alone is insufficient."""
    assert atlas_bundle.package_data_modules() == ("rfc3987_syntax",)
    spec = ast.parse((ROOT / "portable/atlas.spec").read_text(encoding="utf-8"))
    analysis = next(node for node in ast.walk(spec)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "Analysis")
    datas = next(keyword.value for keyword in analysis.keywords if keyword.arg == "datas")
    collected = []
    def collect_data_files(module):
        collected.append(module)
        return [(f"installed/{module}/grammar.lark", module)]
    # A future manifest entry must flow through the same thin spec, without a second list.
    monkeypatch.setattr(atlas_bundle, "package_data_modules", lambda: ("first", "second"))
    result = eval(compile(ast.Expression(datas), "atlas.spec datas", "eval"), {
        "ROOT": ROOT, "bundle_datas": lambda _root: [("owned.txt", ".")],
        "package_data_modules": atlas_bundle.package_data_modules,
        "collect_data_files": collect_data_files,
        "package_metadata_datas": lambda _collector: [], "copy_metadata": object(),
    })
    assert collected == ["first", "second"]
    assert result == [("owned.txt", "."), ("installed/first/grammar.lark", "first"),
                      ("installed/second/grammar.lark", "second")]


def test_spec_retains_native_extension_and_reviewed_distribution_metadata():
    assert "jsonschema_rs.jsonschema_rs" in atlas_bundle.hidden_imports()
    assert atlas_bundle.package_metadata_distributions() == ("jsonschema-rs",)
    required = atlas_bundle.native_runtime_files()
    assert "_internal/jsonschema_rs/jsonschema_rs.pyd" in required
    assert "_internal/jsonschema_rs-0.58.4.dist-info/METADATA" in required
    assert required["_internal/jsonschema_rs-0.58.4.dist-info/sboms/jsonschema-py.cyclonedx.json"] == {
        "bytes": 245181,
        "sha256": "fc02e97118764c2c8e0e67bc1f0fc554cda259a4925e944677894d0792cf6a88",
    }
    spec = ast.parse((ROOT / "portable/atlas.spec").read_text(encoding="utf-8"))
    analysis = next(node for node in ast.walk(spec)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "Analysis")
    datas = next(keyword.value for keyword in analysis.keywords if keyword.arg == "datas")
    collector = object()
    def package_metadata_datas(observed_collector):
        assert observed_collector is collector
        return [("owned-metadata/METADATA", "native.dist-info")]
    result = eval(compile(ast.Expression(datas), "atlas.spec metadata", "eval"), {
        "ROOT": ROOT, "bundle_datas": lambda _root: [],
        "package_data_modules": lambda: (), "collect_data_files": lambda _module: [],
        "package_metadata_datas": package_metadata_datas, "copy_metadata": collector,
    })
    assert result == [("owned-metadata/METADATA", "native.dist-info")]


def test_native_metadata_selection_preserves_version_and_sbom_without_installer_provenance(tmp_path):
    import importlib.metadata

    destination = "jsonschema_rs-0.58.4.dist-info"
    metadata = tmp_path / destination
    (metadata / "sboms").mkdir(parents=True)
    (metadata / "METADATA").write_text("Metadata-Version: 2.4\nName: jsonschema-rs\nVersion: 0.58.4\n")
    (metadata / "WHEEL").write_text("Wheel-Version: 1.0\nTag: cp310-abi3-win_amd64\n")
    (metadata / "sboms/jsonschema-py.cyclonedx.json").write_text('{"bomFormat":"CycloneDX"}')
    for name in ("direct_url.json", "INSTALLER", "REQUESTED", "RECORD"):
        (metadata / name).write_text("file:///C:/synthetic-private-build/location.whl")
    selected = atlas_bundle.package_metadata_datas(lambda name: [(str(metadata), destination)])
    expected = {"METADATA", "WHEEL", "sboms/jsonschema-py.cyclonedx.json"}
    assert {Path(path).relative_to(metadata).as_posix() for path, _dest in selected} == expected
    frozen = tmp_path / "frozen"
    for path, directory in selected:
        target = frozen / directory / Path(path).name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(path).read_bytes())
    distributions = list(importlib.metadata.distributions(path=[str(frozen)]))
    assert [(item.metadata["Name"], item.version) for item in distributions] == [("jsonschema-rs", "0.58.4")]
    assert not any(b"synthetic-private-build" in path.read_bytes() for path in frozen.rglob("*") if path.is_file())
    for name in expected:
        path = metadata / name
        original = path.read_bytes()
        path.unlink()
        with pytest.raises(ValueError, match="metadata file is absent"):
            atlas_bundle.package_metadata_datas(lambda _name: [(str(metadata), destination)])
        path.write_bytes(original)
    with pytest.raises(ValueError, match="metadata version differs"):
        atlas_bundle.package_metadata_datas(lambda _name: [(str(metadata), "jsonschema_rs-0.58.3.dist-info")])


def test_validator_metadata_filter_also_closes_upstream_hook_collection():
    original = []
    kept = []
    for directory in ("jsonschema-4.26.0.dist-info", "jsonschema_rs-0.58.4.dist-info"):
        for name in ("METADATA", "WHEEL", "licenses/COPYING", "sboms/jsonschema-py.cyclonedx.json"):
            row = (directory + "/" + name, "installed/" + name, "DATA")
            original.append(row)
            kept.append(row)
        for name in ("direct_url.json", "INSTALLER", "REQUESTED", "RECORD"):
            original.append((directory + "\\" + name, "private-installation", "DATA"))
    unrelated = ("other.dist-info/direct_url.json", "unrelated-owner", "DATA")
    original.append(unrelated)
    kept.append(unrelated)
    assert atlas_bundle.reviewed_validator_metadata_toc(original) == kept
    assert len(original) == len(kept) + 8  # The source TOC itself is not mutated.
    spec = ast.parse((ROOT / "portable/atlas.spec").read_text(encoding="utf-8"))
    assignments = [node for node in ast.walk(spec) if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Attribute) and target.attr == "datas"
                           for target in node.targets)]
    assert any(isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
               and node.value.func.id == "reviewed_validator_metadata_toc" for node in assignments)


def test_tracked_sources_exist_on_a_checkout():
    """Everything except build output is tracked — it must exist on any checkout. The built SPA dist
    and the Atlas Scope hub build are build output (engine CI has no node), so they are the only
    tolerated absences here — read from the manifest's own BUILD_OUTPUTS, not a list of names."""
    outputs = [ROOT / rel for rel in atlas_bundle.BUILD_OUTPUTS]
    missing = [p for p in atlas_bundle.missing_data_sources(ROOT)
               if not any(Path(p) == out or Path(p).is_relative_to(out) for out in outputs)]
    assert not missing, f"tracked bundle sources missing from the checkout: {missing}"
    # and every declared build output really is a bundle source (the tolerance is not over-broad)
    sources = [Path(src) for src, _dest in atlas_bundle.bundle_datas(ROOT)]
    for out in outputs:
        assert any(src == out or src.is_relative_to(out) for src in sources), out


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


# ── Atlas Scope (/scope): the hub build rides the bundle as its own member ──────────────────────
def _serve():
    if str(ROOT) not in sys.path:  # webapp is a namespace package off the repo root
        sys.path.insert(0, str(ROOT))
    from webapp.backend import serve

    return serve


def _write_scope_hub_build(dist: Path, *, with_maps: bool = True) -> None:
    """A small /scope runtime build shaped like atlas-scope's `npm run build:hub` output."""
    (dist / "assets").mkdir(parents=True, exist_ok=True)
    (dist / "assets" / "index-a1.js").write_bytes(b"export const scope = 1;")
    (dist / "assets" / "index-b2.css").write_bytes(b":root{--bg:#000}")
    if with_maps:
        (dist / "assets" / "index-a1.js.map").write_bytes(b'{"version":3,"sources":[]}')
        (dist / "assets" / "vendor.JS.MAP").write_bytes(b'{"version":3}')
    (dist / "index.html").write_bytes(
        b'<!doctype html><html><head><meta charset="UTF-8">'
        b'<meta name="atlas-scope-snapshot-source" content="assesshub-api-runtime">'
        b'<script type="module" crossorigin src="/scope/assets/index-a1.js"></script>'
        b'<link rel="stylesheet" crossorigin href="/scope/assets/index-b2.css">'
        b'</head><body><div id="root"></div></body></html>')


def test_scope_dist_dest_matches_the_entry_modules_frozen_probe(monkeypatch, tmp_path):
    """The two owners of 'where does the Atlas Scope hub build live when frozen' -- the bundle's
    SCOPE_DIST_DEST and serve._resolve_scope_dist's _MEIPASS probe -- name the SAME directory."""
    serve = _serve()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert serve._resolve_scope_dist() == tmp_path / atlas_bundle.SCOPE_DIST_DEST
    assert atlas_bundle.SCOPE_DIST_DEST != atlas_bundle.DIST_DEST  # its own member, never the SPA's


def test_scope_dist_source_is_the_apps_own_default_hub_build(monkeypatch):
    """The bundle ships the build AssessHub serves from a checkout (app._REPO_ATLAS_SCOPE_DIST, the
    output of atlas-scope `npm run build:hub`), and a checkout resolves to it unfrozen."""
    serve = _serve()
    from webapp.backend import app as app_module

    assert ROOT / atlas_bundle.SCOPE_DIST_SOURCE == app_module._REPO_ATLAS_SCOPE_DIST
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert serve._resolve_scope_dist() == app_module.ATLAS_SCOPE_DIST


def test_the_scope_member_ships_every_build_file_except_sourcemaps(tmp_path):
    hub = tmp_path / atlas_bundle.SCOPE_DIST_SOURCE
    _write_scope_hub_build(hub)
    datas = atlas_bundle.bundle_datas(tmp_path)
    shipped = sorted((Path(src).relative_to(hub).as_posix(), dest) for src, dest in datas
                     if Path(src).is_relative_to(hub))
    assert shipped == [
        ("assets/index-a1.js", f"{atlas_bundle.SCOPE_DIST_DEST}/assets"),
        ("assets/index-b2.css", f"{atlas_bundle.SCOPE_DIST_DEST}/assets"),
        ("index.html", atlas_bundle.SCOPE_DIST_DEST),
    ]
    assert not [src for src, _dest in datas if src.casefold().endswith(".map")]
    assert not [m for m in atlas_bundle.missing_data_sources(tmp_path) if Path(m).is_relative_to(hub)]


def test_the_build_refuses_a_bundle_without_the_scope_hub_build(tmp_path):
    """Refuse-on-missing: no hub build (or one without its shell) is a missing source, so
    atlas.spec refuses to build instead of shipping an Atlas whose /scope is silently absent."""
    hub = tmp_path / atlas_bundle.SCOPE_DIST_SOURCE
    assert str(hub) in atlas_bundle.missing_data_sources(tmp_path)
    _write_scope_hub_build(hub)
    (hub / "index.html").unlink()
    assert str(hub / "index.html") in atlas_bundle.missing_data_sources(tmp_path)
    # a build of sourcemaps alone is not a build either
    for path in (hub / "assets").iterdir():
        if not path.name.casefold().endswith(".map"):
            path.unlink()
    assert str(hub / "index.html") in atlas_bundle.missing_data_sources(tmp_path)
    spec = (ROOT / "portable" / "atlas.spec").read_text(encoding="utf-8")
    assert "npm run build:hub" in spec  # the refusal names the command that fixes it


def _selftest(serve, capsys, tmp_path, *, scope_dist):
    pytest.importorskip("docx")
    pytest.importorskip("pptx")
    spa = tmp_path / "spa"
    (spa / "assets").mkdir(parents=True)
    (spa / "assets" / "app.js").write_bytes(b"export const ready = true;")
    (spa / "index.html").write_bytes(b'<!doctype html><html><head><script type="module" '
                                     b'src="/assets/app.js"></script></head><body>'
                                     b'<div id="root"></div></body></html>')
    rc = serve.run_selftest(dist_dir=spa, db_path=str(tmp_path / "data" / "hub.db"),
                            scope_dist_dir=scope_dist)
    out = capsys.readouterr().out
    return rc, [line for line in out.splitlines() if "atlas-scope" in line], out


def test_selftest_requires_a_ready_scope_build_in_a_frozen_bundle(monkeypatch, tmp_path, capsys):
    serve = _serve()
    monkeypatch.setattr(serve, "_scope_build_required", lambda: True)
    _rc, lines, out = _selftest(serve, capsys, tmp_path / "a", scope_dist=tmp_path / "no-scope")
    assert len(lines) == 1 and lines[0].lstrip().startswith("[FAIL]"), out
    assert "not_built" in lines[0]
    hub = tmp_path / "hub"
    _write_scope_hub_build(hub)
    _rc, lines, out = _selftest(serve, capsys, tmp_path / "b", scope_dist=hub)
    assert len(lines) == 1 and lines[0].lstrip().startswith("[ ok ]"), out
    # the frozen predicate is the requirement's owner
    monkeypatch.undo()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert serve._scope_build_required() is True
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert serve._scope_build_required() is False


@pytest.mark.parametrize("available", [True, False])
def test_frozen_selftest_exercises_reviewed_jsonschema_loader(monkeypatch, tmp_path, capsys, available):
    from webapp.backend import ui_projection_api
    from portable import network_boundary

    serve = _serve()
    monkeypatch.setattr(serve, "_frozen", lambda: True)
    monkeypatch.setattr(network_boundary, "installed", lambda: True)
    monkeypatch.setattr(network_boundary, "live_network_allowed", lambda: False)
    monkeypatch.setattr(network_boundary, "offline_probe", lambda: True)
    calls = []
    def load():
        calls.append("actual guarded loader")
        if not available:
            raise RuntimeError("reviewed metadata or interface unavailable")
        return object
    monkeypatch.setattr(ui_projection_api, "_reviewed_legacy_resolver_type", load)
    hub = tmp_path / "hub"
    _write_scope_hub_build(hub)
    rc, _lines, output = _selftest(serve, capsys, tmp_path / "run", scope_dist=hub)
    assert calls == ["actual guarded loader"]
    marker = "[ ok ]" if available else "[FAIL]"
    assert f"{marker} ui-projection-legacy-resolver" in output
    if not available:
        assert rc == 1


def test_selftest_refuses_a_present_scope_build_it_would_not_serve(tmp_path, capsys):
    """A checkout with a scope build that AssessHub refuses (here: a root-mounted build, the
    standalone sample shape) fails loud -- present-but-refused is never rendered as fine."""
    serve = _serve()
    bad = tmp_path / "bad"
    _write_scope_hub_build(bad)
    (bad / "index.html").write_bytes((bad / "index.html").read_bytes().replace(b"/scope/", b"/"))
    rc, lines, out = _selftest(serve, capsys, tmp_path, scope_dist=bad)
    assert rc == 1 and len(lines) == 1 and lines[0].lstrip().startswith("[FAIL]"), out
    assert "invalid_build" in lines[0]


def test_selftest_in_a_checkout_reports_an_absent_scope_build_as_not_applicable(tmp_path, capsys):
    """In a checkout the hub build is optional build output (/scope then answers 'not built' and
    AssessHub shows no link): the line says so, is NOT counted as a passing check, and does not by
    itself fail the run. It is never printed as '[ ok ]'."""
    serve = _serve()
    rc, lines, out = _selftest(serve, capsys, tmp_path, scope_dist=tmp_path / "none")
    assert len(lines) == 1 and lines[0].lstrip().startswith("[ -- ]"), out
    assert "not built" in lines[0]
    assert "[ ok ] atlas-scope" not in out
    assert "1 not applicable" in out
    verdict = re.search(r"SELFTEST: (PASS|FAIL) \((\d+)/(\d+) checks ok", out)
    assert verdict, out
    assert (rc == 0) == (verdict.group(1) == "PASS")
    assert int(verdict.group(2)) <= int(verdict.group(3))


def test_serve_passes_the_resolved_scope_build_to_the_app(monkeypatch, tmp_path):
    """The production entry serves the resolved scope build (the frozen bundle's member), not
    whatever create_app's checkout default would resolve to inside _MEIPASS."""
    serve = _serve()
    from webapp.backend import app as app_module

    seen = {}

    def fake_create_app(**kwargs):
        seen.update(kwargs)
        import sqlite3

        raise sqlite3.DatabaseError("stop after construction arguments were captured")
    monkeypatch.setattr(app_module, "create_app", fake_create_app)
    monkeypatch.setattr(serve, "_resolve_scope_dist", lambda: tmp_path / "bundled-scope")
    rc = serve.main(["--db", str(tmp_path / "data" / "a.db"), "--no-browser",
                     "--dist", str(tmp_path / "spa")])
    assert rc == 1
    assert seen["scope_dist_dir"] == str(tmp_path / "bundled-scope")
