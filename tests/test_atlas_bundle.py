"""The Atlas one-folder bundle manifest (ADR-0004 P2) — portable/atlas_bundle.py.

Pins the frozen bundle's contract WITHOUT running PyInstaller: the assets --selftest guards must
all be in datas, the dynamic imports static analysis cannot see must all be hidden-imports, and
the dist destination must be the exact directory the entry module probes when frozen."""

import io
import json
import os
import re
import subprocess
import sys
import urllib.error
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
        # An icon in the head, as the real shell carries: without one the browser asks for the
        # origin's /favicon.ico, outside /scope, and AssessHub refuses the build (RQF-V1-4).
        b'<link rel="icon" href="data:image/svg+xml,%3Csvg%3E%3C/svg%3E">'
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
    # ...one command per line: the user pastes it into Windows PowerShell 5.1, where `&&` is a
    # parser error (build_atlas.build() refuses the same way)
    assert "&&" not in spec


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


# ── R-PB: the build refuses a missing or non-runtime hub build with the exact commands ──────────
# The commands a person runs from the repository root to produce the hub build, one per line
# (they are pasted into Windows PowerShell 5.1, where `&&` is a parser error).
_SCOPE_HUB_COMMANDS = ("cd atlas-scope", "npm ci", "npm run build:hub")


def _refusal_names_the_scope_commands(message: str) -> bool:
    lines = [line.strip() for line in message.splitlines()]
    positions = [lines.index(command) if command in lines else -1 for command in _SCOPE_HUB_COMMANDS]
    return -1 not in positions and positions == sorted(positions)


def _refused_build(monkeypatch, root: Path) -> str:
    """Run build_atlas.build() against ``root`` and return its refusal. PyInstaller must never be
    reached: a refusal is the only acceptable outcome for these roots."""
    from portable import build_atlas

    def no_pyinstaller(*_args, **_kwargs):
        raise AssertionError("build() reached PyInstaller instead of refusing")

    monkeypatch.setattr(build_atlas, "ROOT", root)
    monkeypatch.setattr(build_atlas, "DIST", root / "portable" / "dist" / "Atlas")
    monkeypatch.setattr(build_atlas.subprocess, "run", no_pyinstaller)
    with pytest.raises(SystemExit) as refused:
        build_atlas.build()
    return str(refused.value)


def _tracked_sources(root: Path) -> None:
    """Every tracked bundle source present under ``root`` (stand-ins), and the built SPA, so that
    only the Atlas Scope hub build decides the outcome."""
    for source in atlas_bundle.missing_data_sources(root):
        path = Path(source)
        if path.is_relative_to(root / atlas_bundle.SCOPE_DIST_SOURCE):
            continue
        if path == root / "webapp" / "frontend" / "dist":
            (path / "assets").mkdir(parents=True, exist_ok=True)
            (path / "index.html").write_bytes(b'<!doctype html><div id="root"></div>')
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"stand-in")


def test_build_refuses_an_absent_scope_hub_build_naming_the_exact_commands(monkeypatch, tmp_path):
    """Requirement R-PB 1: no atlas-scope/dist-hub -> the refusal says exactly what to run."""
    _tracked_sources(tmp_path)
    assert atlas_bundle.missing_data_sources(tmp_path) == [
        str(tmp_path / atlas_bundle.SCOPE_DIST_SOURCE)]
    message = _refused_build(monkeypatch, tmp_path)
    assert _refusal_names_the_scope_commands(message), message
    assert atlas_bundle.SCOPE_DIST_SOURCE in message


@pytest.mark.parametrize("variant", ["standalone-root-mounted", "no-runtime-source-meta"])
def test_build_refuses_a_present_scope_build_that_is_not_a_runtime_hub_build(
        monkeypatch, tmp_path, variant):
    """Requirement R-PB 1: a dist-hub that exists but is not a runtime-source hub build (the
    standalone root-mounted shape, or a shell without the runtime-snapshot declaration) is refused
    BEFORE PyInstaller, judged by the same index AssessHub serves /scope from, and the refusal names
    the same commands. Presence alone used to pass the build's pre-check."""
    _tracked_sources(tmp_path)
    hub = tmp_path / atlas_bundle.SCOPE_DIST_SOURCE
    _write_scope_hub_build(hub, with_maps=False)
    shell = (hub / "index.html").read_bytes()
    if variant == "standalone-root-mounted":
        shell = shell.replace(b"/scope/", b"/")
    else:
        shell = shell.replace(
            b'<meta name="atlas-scope-snapshot-source" content="assesshub-api-runtime">', b"")
    (hub / "index.html").write_bytes(shell)
    assert atlas_bundle.missing_data_sources(tmp_path) == []  # present: presence is not enough
    message = _refused_build(monkeypatch, tmp_path)
    assert _refusal_names_the_scope_commands(message), message
    assert "invalid_build" in message


def test_every_bundle_build_output_has_the_commands_that_produce_it():
    """The refusal's commands are keyed by the bundle manifest's own BUILD_OUTPUTS, so a new build
    output cannot be refused without telling the person how to make it."""
    from portable import build_atlas

    assert set(build_atlas.BUILD_OUTPUT_COMMANDS) == set(atlas_bundle.BUILD_OUTPUTS)
    assert build_atlas.BUILD_OUTPUT_COMMANDS[atlas_bundle.SCOPE_DIST_SOURCE] == _SCOPE_HUB_COMMANDS
    for commands in build_atlas.BUILD_OUTPUT_COMMANDS.values():
        assert not any("&&" in command for command in commands)  # PowerShell 5.1 parser error
    # the npm script the refusal names is the one that writes the hub build
    scripts = json.loads((ROOT / "atlas-scope" / "package.json").read_text(encoding="utf-8"))["scripts"]
    assert "--mode hub" in scripts["build:hub"]


def test_build_passes_the_scope_precheck_with_a_runtime_hub_build(monkeypatch, tmp_path):
    """The counter-case: a servable hub build is not refused by the pre-check (the build then
    proceeds to PyInstaller, which the harness stops)."""
    from portable import build_atlas

    _tracked_sources(tmp_path)
    _write_scope_hub_build(tmp_path / atlas_bundle.SCOPE_DIST_SOURCE, with_maps=False)
    reached = []

    def stop_at_pyinstaller(cmd, **_kwargs):
        reached.append(cmd)
        raise SystemExit("stopped at PyInstaller")

    monkeypatch.setattr(build_atlas, "ROOT", tmp_path)
    monkeypatch.setattr(build_atlas, "DIST", tmp_path / "portable" / "dist" / "Atlas")
    monkeypatch.setattr(build_atlas.subprocess, "run", stop_at_pyinstaller)
    with pytest.raises(SystemExit, match="stopped at PyInstaller"):
        build_atlas.build()
    assert reached and "PyInstaller" in reached[0]


# ── R-PB: the frozen smoke requires the /scope shell and the atlas-scope-dist selftest line ─────
_SCOPE_SELFTEST_LINE = "  [ ok ] atlas-scope-dist"
_NETWORK_SELFTEST_LINE = "  [ ok ] network-boundary [offline-loopback-only]"


def test_the_smoke_selftest_line_is_the_line_serve_really_prints():
    """The smoke looks for the exact line serve.run_selftest prints for the /scope check; its name
    is owned by serve.py, so a rename there must fail here rather than leave the smoke looking for
    a line that can never appear (or that another check could satisfy)."""
    from portable import build_atlas

    serve_src = (ROOT / "webapp" / "backend" / "serve.py").read_text(encoding="utf-8")
    names = set(re.findall(r'check\(\s*"(atlas-scope[a-z-]*)"', serve_src))
    assert names == {"atlas-scope-dist"}, names
    assert 'print(f"  [ ok ] {name}"' in serve_src
    assert _SCOPE_SELFTEST_LINE == "  [ ok ] " + names.pop()
    assert set(build_atlas.REQUIRED_SELFTEST_LINES) == {_SCOPE_SELFTEST_LINE, _NETWORK_SELFTEST_LINE}


class _FakeResponse:
    def __init__(self, status: int, body: bytes, content_type: str):
        self.status = status
        self._body = body
        self.headers = {"Content-Type": content_type}

    def read(self, size: int = -1) -> bytes:
        chunk = self._body if size is None or size < 0 else self._body[:size]
        self._body = self._body[len(chunk):]
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _amd64_pe() -> bytes:
    value = bytearray(512)
    value[:2] = b"MZ"
    value[0x3C:0x40] = (0x80).to_bytes(4, "little")
    value[0x80:0x84] = b"PE\0\0"
    value[0x84:0x86] = (0x8664).to_bytes(2, "little")
    return bytes(value)


class _SmokeHarness:
    """Drives build_atlas.smoke() end to end against a fake one-folder bundle: every child process
    and every HTTP answer is scripted, so each test changes exactly one observable and the smoke's
    own decision is what is under test (nothing about PyInstaller or a real server)."""

    def __init__(self, tmp_path: Path, monkeypatch):
        from portable import build_atlas
        from portable.windows_version_info import version_expectations

        self.build_atlas = build_atlas
        self.selftest_lines = [
            "Atlas - selftest - release test",
            "  [ ok ] frontend-dist",
            _SCOPE_SELFTEST_LINE,
            _NETWORK_SELFTEST_LINE,
            "SELFTEST: PASS (3/3 checks ok)",
        ]
        self.scope_answer = None  # None -> 200 with the served bundle's own shell bytes
        self.requests: list[str] = []
        self.server_env: dict = {}
        self.server_cwd = None
        self.dist = tmp_path / "dist" / "Atlas"
        internal = self.dist / "_internal"
        (internal / atlas_bundle.DIST_DEST).mkdir(parents=True)
        (internal / atlas_bundle.DIST_DEST / "index.html").write_bytes(b'<div id="root"></div>')
        _write_scope_hub_build(internal / atlas_bundle.SCOPE_DIST_DEST, with_maps=False)
        (self.dist / "Atlas.exe").write_bytes(_amd64_pe())
        for src in atlas_bundle.root_files(ROOT):
            (self.dist / Path(src).name).write_bytes(Path(src).read_bytes())
        expected = build_atlas.expected_release()
        harness = self

        def fake_run(cmd, timeout, *, cwd, **_kwargs):
            data = Path(cwd) / "data"
            if cmd[1] == "--selftest":
                data.mkdir(exist_ok=True)
                return subprocess.CompletedProcess(cmd, 0, "\n".join(harness.selftest_lines), "")
            if cmd[1] == "--version":
                return subprocess.CompletedProcess(
                    cmd, 0, f"Atlas - release {expected} - engine schema test", "")
            if cmd[1] == "--run-engine":
                from cisco_toolkit import __version__ as schema

                data.mkdir(exist_ok=True)
                (data / f"cisco_migration_autofill_v{schema.replace('.', '_')}.log").write_bytes(b"")
                return subprocess.CompletedProcess(cmd, 0, "usage: cisco-assess [-h]", "")
            raise AssertionError(f"unexpected child: {cmd!r}")

        class FakeServer:
            def __init__(self, _cmd, *, env, cwd, **_kwargs):
                harness.server_env = env
                harness.server_cwd = Path(cwd)
                self.returncode = None
                self.stdout = None

            def poll(self):
                return self.returncode

            def terminate(self):
                self.returncode = 0

            def kill(self):
                self.returncode = -9

            def wait(self, timeout=None):
                return self.returncode

        def fake_urlopen(request, timeout=None):
            url = request if isinstance(request, str) else request.full_url
            path = "/" + url.split("://", 1)[1].split("/", 1)[1]
            harness.requests.append(path)
            if path == "/api/health":
                nonce = harness.server_env["ASSESSHUB_INSTANCE_NONCE"]
                return _FakeResponse(200, json.dumps({"instance_nonce": nonce}).encode(),
                                     "application/json")
            if path == "/api/meta":
                body = {"app": {"name": "Atlas", "title": "Atlas", "release": expected}}
                return _FakeResponse(200, json.dumps(body).encode(), "application/json")
            if path == "/":
                return _FakeResponse(200, b'<!doctype html><div id="root"></div><script></script>',
                                     "text/html; charset=utf-8")
            if path == "/scope/":
                if harness.scope_answer is None:
                    shell = (harness.server_cwd / "_internal" / atlas_bundle.SCOPE_DIST_DEST
                             / "index.html").read_bytes()
                    return _FakeResponse(200, shell, "text/html; charset=utf-8")
                status, body, content_type = harness.scope_answer
                if status >= 400:
                    raise urllib.error.HTTPError(url, status, "refused", {}, io.BytesIO(body))
                return _FakeResponse(status, body, content_type)
            raise urllib.error.HTTPError(url, 404, "Not found", {}, io.BytesIO(b""))

        monkeypatch.setattr(build_atlas, "_run", fake_run)
        monkeypatch.setattr(build_atlas, "_windows_version_info",
                            lambda *_a, **_k: version_expectations(ROOT))
        monkeypatch.setattr(build_atlas.subprocess, "Popen", FakeServer)
        monkeypatch.setattr(build_atlas.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(build_atlas.time, "sleep", lambda _seconds: None)

    def run(self):
        return self.build_atlas.smoke(8479, dist=self.dist, environment=dict(os.environ))


def test_the_smoke_harness_passes_a_bundle_that_serves_its_scope_view(tmp_path, monkeypatch):
    """The counter-case every refusal below is measured against: the scripted bundle passes, and
    the smoke did request /scope/ (a smoke that never asks for it cannot be what passes here)."""
    harness = _SmokeHarness(tmp_path, monkeypatch)
    result = harness.run()
    assert "/scope/" in harness.requests, harness.requests
    assert result.get("loopback_http_scope_runtime_shell") == "pass", result


def test_the_smoke_refuses_a_selftest_without_the_atlas_scope_dist_ok_line(tmp_path, monkeypatch):
    """Requirement R-PB 2: `[ ok ] atlas-scope-dist` is required. A frozen bundle whose selftest
    reports the view as not applicable (the checkout wording) exits 0 -- the smoke must not pass."""
    harness = _SmokeHarness(tmp_path, monkeypatch)
    harness.selftest_lines[2] = ("  [ -- ] atlas-scope-dist - not built in this checkout; /scope "
                                 "answers 'not built'")
    with pytest.raises(SystemExit, match="atlas-scope-dist"):
        harness.run()


def test_the_smoke_requires_the_scope_line_exactly_not_a_lookalike(tmp_path, monkeypatch):
    harness = _SmokeHarness(tmp_path, monkeypatch)
    harness.selftest_lines[2] = "  [ ok ] atlas-scope-dist-legacy"
    with pytest.raises(SystemExit, match="atlas-scope-dist"):
        harness.run()


def test_the_smoke_still_requires_the_offline_network_boundary_line(tmp_path, monkeypatch):
    harness = _SmokeHarness(tmp_path, monkeypatch)
    harness.selftest_lines[3] = "  [ ok ] network-boundary [explicit-live]"
    with pytest.raises(SystemExit, match="network"):
        harness.run()


@pytest.mark.parametrize("answer", [
    (503, b'{"detail": "Atlas Scope is not built in this installation."}', "application/json"),
    (404, b"Not found", "text/plain"),
])
def test_the_smoke_refuses_a_scope_mount_that_does_not_answer_200(tmp_path, monkeypatch, answer):
    """Requirement R-PB 2: GET /scope/ must answer 200 on the frozen bundle."""
    harness = _SmokeHarness(tmp_path, monkeypatch)
    harness.scope_answer = answer
    with pytest.raises(SystemExit, match="/scope/"):
        harness.run()


def test_the_smoke_refuses_a_scope_200_without_the_runtime_source_meta(tmp_path, monkeypatch):
    """Requirement R-PB 2: a 200 that is not the runtime-source hub shell (here AssessHub's own SPA
    shell, what a fall-through would serve) is refused."""
    harness = _SmokeHarness(tmp_path, monkeypatch)
    harness.scope_answer = (200, b'<!doctype html><html><head><script type="module" '
                                 b'src="/assets/app.js"></script></head><body><div id="root">'
                                 b'</div></body></html>', "text/html; charset=utf-8")
    with pytest.raises(SystemExit, match="runtime"):
        harness.run()


def test_the_smoke_refuses_a_scope_shell_that_is_not_the_bundled_member(tmp_path, monkeypatch):
    """A runtime-source shell that is not the byte-exact bundled atlas_scope_dist/index.html (for
    example a build served from somewhere else) is not proof that the stick serves its own view."""
    harness = _SmokeHarness(tmp_path, monkeypatch)
    other = tmp_path / "other-hub"
    _write_scope_hub_build(other, with_maps=False)
    harness.scope_answer = (200, (other / "index.html").read_bytes() + b"\n<!-- elsewhere -->",
                            "text/html; charset=utf-8")
    with pytest.raises(SystemExit, match="bundled"):
        harness.run()


def test_the_smoke_scope_proof_is_a_required_release_qualification_check():
    """The /scope proof is part of what release qualification requires, so a smoke that stops
    reporting it cannot qualify a release (release_contract validates the exact check set)."""
    from portable import release_contract

    assert "loopback_http_scope_runtime_shell" in release_contract.REQUIRED_AUTOMATED_CHECKS
