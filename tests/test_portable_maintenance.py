"""Installed-code trust, data exclusion and fail-closed maintenance boundaries."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

import pytest

from portable import atlas_entry, maintenance, release_contract, verify_release
from webapp.backend import serve


ROOT = Path(__file__).resolve().parents[1]


def test_frozen_verifier_dispatch_never_loads_the_engine(monkeypatch):
    seen = []
    monkeypatch.setattr(serve, "_frozen", lambda: True)
    monkeypatch.setattr(verify_release, "main", lambda argv: seen.append(argv) or 23)
    monkeypatch.setattr(serve, "_load_engine_main", lambda: pytest.fail("engine loaded"))
    assert atlas_entry.main(["--verify-release", "--installed", "example"]) == 23
    assert seen == [["--installed", "example"]]


def test_unfrozen_wheel_cli_never_imports_the_portable_build_package(monkeypatch):
    import builtins

    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert not (name == "portable" or name.startswith("portable.")), "wheel imported portable build-only code"
        return original(name, *args, **kwargs)

    monkeypatch.setattr(serve, "_frozen", lambda: False)
    monkeypatch.setattr(builtins, "__import__", guarded)
    with pytest.raises(SystemExit) as exited:
        serve._main_scoped(["--version"])
    assert exited.value.code == 0


def test_maintenance_command_keeps_engine_argv_opaque(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(serve, "_run_engine", lambda argv: seen.append(argv) or 9)
    monkeypatch.setattr(serve, "_frozen", lambda: True)
    monkeypatch.setattr(serve, "_exe_dir", lambda: tmp_path / "Atlas")
    monkeypatch.setattr(serve, "engine_log_path", lambda **kw: "synthetic-engine.log")
    monkeypatch.setattr(maintenance, "main", lambda argv: pytest.fail("engine argv entered maintenance"))
    assert atlas_entry.main(["--run-engine", "--update", "opaque"]) == 9
    assert seen == [["--update", "opaque"]]


def test_pending_maintenance_refuses_server_before_creating_an_empty_store(tmp_path, monkeypatch, capsys):
    bundle = tmp_path / "Atlas"
    bundle.mkdir()
    (tmp_path / "Atlas.update-state.json").write_text("interrupted transaction", encoding="ascii")
    monkeypatch.setattr(serve, "_frozen", lambda: True)
    monkeypatch.setattr(serve, "_exe_dir", lambda: bundle)
    monkeypatch.setattr(serve, "_writable_failure", lambda path: pytest.fail("store path was touched"))
    assert atlas_entry.main(["--no-browser"]) == 1
    assert "portable maintenance is incomplete" in capsys.readouterr().err
    assert not (bundle / "data").exists()


@pytest.mark.parametrize("helper", [None, "Atlas.maintenance-", "aTlAs.MaInTeNaNcE-"])
@pytest.mark.parametrize("argv", [
    ["--no-browser"],
    ["--selftest"],
    ["--run-engine", "--help"],
    ["--redact-folder", "synthetic-collection", "--out", "synthetic-output"],
])
def test_pending_journal_fences_every_writable_door_in_active_and_helper_apps(
    tmp_path, monkeypatch, capsys, helper, argv,
):
    application = (tmp_path / (helper + "c" * 32) / "Atlas"
                   if helper else tmp_path / "Atlas")
    application.mkdir(parents=True)
    (tmp_path / "Atlas.update-state.json").write_text("malformed or valid both fence writes", encoding="ascii")
    monkeypatch.setattr(serve, "_frozen", lambda: True)
    monkeypatch.setattr(serve, "_exe_dir", lambda: application)
    monkeypatch.setattr(serve, "_run_engine", lambda argv: pytest.fail("engine started"))
    monkeypatch.setattr(serve, "run_redaction", lambda *a: pytest.fail("redaction started"))
    monkeypatch.setattr(serve, "_writable_failure", lambda path: pytest.fail("store path touched"))
    assert atlas_entry.main(argv) == 1
    assert "portable maintenance is incomplete" in capsys.readouterr().err
    assert not (application / "data").exists()


@pytest.mark.parametrize("argv", [["--no-browser"], ["--selftest"], ["--run-engine", "--help"],
                                   ["--redact-folder", "synthetic-input", "--out", "synthetic-output"]])
def test_completed_private_helpers_are_never_writable_application_doors(tmp_path, monkeypatch, capsys, argv):
    helper = tmp_path / ("ATLAS.MAINTENANCE-" + "a" * 32) / "Atlas"
    helper.mkdir(parents=True)
    monkeypatch.setattr(serve, "_frozen", lambda: True)
    monkeypatch.setattr(serve, "_exe_dir", lambda: helper)
    monkeypatch.setattr(serve, "_run_engine", lambda argv: pytest.fail("helper engine started"))
    monkeypatch.setattr(serve, "run_redaction", lambda *a: pytest.fail("helper redaction started"))
    monkeypatch.setattr(serve, "_writable_failure", lambda path: pytest.fail("helper store touched"))
    assert atlas_entry.main(argv) == 1
    assert "code-only" in capsys.readouterr().err
    assert not (helper / "data").exists()


@pytest.mark.parametrize("helper", [False, True])
@pytest.mark.parametrize("selection", ["default", "local", "relative", "env_external", "active_from_helper",
                                       "reserved_preflight"])
def test_selftest_fences_default_and_kit_local_db_before_any_asset_or_write(
    tmp_path, monkeypatch, capsys, helper, selection,
):
    installation = tmp_path / "installed"
    application = installation / (("Atlas.maintenance-" + "a" * 32 + "/Atlas") if helper else "Atlas")
    application.mkdir(parents=True)
    (installation / "Atlas.update-state.json").write_text("interrupted", encoding="ascii")
    monkeypatch.setattr(serve, "_frozen", lambda: True)
    monkeypatch.setattr(serve, "_exe_dir", lambda: application)
    monkeypatch.setattr(serve, "_explorer_template_path", lambda: pytest.fail("selftest reached assets before fence"))
    monkeypatch.setattr(serve, "_writable_failure", lambda path: pytest.fail("selftest reached a write probe"))
    monkeypatch.chdir(application)
    database = None
    if selection == "local":
        database = str(application / "data/assesshub.db")
    elif selection == "relative":
        database = "../Atlas/data/assesshub.db"
    elif selection == "env_external":
        monkeypatch.setenv("ASSESSHUB_DB", str(tmp_path / "external/env.db"))
    elif selection == "active_from_helper":
        database = str(installation / "Atlas/data/assesshub.db")
    elif selection == "reserved_preflight":
        database = str(installation / ".Atlas.database-preflight/assesshub.db")
    assert atlas_entry.run_selftest(db_path=database) == 1
    assert "portable maintenance is incomplete" in capsys.readouterr().err
    assert not (application / "data").exists()
    assert not (installation / "Atlas/data").exists()
    assert not (tmp_path / "external").exists()


@pytest.mark.parametrize("helper", [False, True])
@pytest.mark.parametrize("location", ["outside_destination", "temp_beneath_destination"])
def test_journaled_selftest_allows_explicit_external_db_only(tmp_path, monkeypatch, helper, location):
    installation = tmp_path / "installed"
    application = installation / (("Atlas.maintenance-" + "b" * 32 + "/Atlas") if helper else "Atlas")
    application.mkdir(parents=True)
    (installation / "Atlas.update-state.json").write_text("interrupted", encoding="ascii")
    monkeypatch.setattr(serve, "_frozen", lambda: True)
    monkeypatch.setattr(serve, "_exe_dir", lambda: application)

    class AssetsReached(Exception):
        pass

    def assets():
        raise AssetsReached

    monkeypatch.setattr(serve, "_explorer_template_path", assets)
    temporary = installation if location == "temp_beneath_destination" else tmp_path
    with pytest.raises(AssetsReached):
        atlas_entry.run_selftest(db_path=str(temporary / "disposable/selftest.db"))
    assert not (application / "data").exists()


def test_journaled_selftest_refuses_external_db_with_backups_redirected_into_kit(tmp_path, monkeypatch):
    application = tmp_path / "Atlas"
    (application / "data").mkdir(parents=True)
    disposable = tmp_path / "disposable"
    disposable.mkdir()
    try:
        (disposable / "backups").symlink_to(application / "data", target_is_directory=True)
    except OSError as error:
        pytest.skip(str(error))
    (tmp_path / "Atlas.update-state.json").write_text("interrupted", encoding="ascii")
    monkeypatch.setattr(serve, "_frozen", lambda: True)
    monkeypatch.setattr(serve, "_exe_dir", lambda: application)
    monkeypatch.setattr(serve, "_writable_failure", lambda path: pytest.fail("redirected write probe reached"))
    assert atlas_entry.run_selftest(db_path=str(disposable / "selftest.db")) == 1
    assert list((application / "data").iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows namespace semantics")
@pytest.mark.parametrize("helper_caller", [False, True])
@pytest.mark.parametrize("owner", ["active", "helper", "custody"])
@pytest.mark.parametrize("backup", [False, True])
@pytest.mark.parametrize("namespace", ["ordinary", "extended", "unc", "extended_unc", "device", "nt_device"])
def test_windows_selftest_namespaces_cannot_recreate_kit_or_custody_data(
    tmp_path, monkeypatch, capsys, helper_caller, owner, backup, namespace,
):
    installation = tmp_path / "installed"
    active = installation / "Atlas"
    helper = installation / ("Atlas.maintenance-" + "c" * 32) / "Atlas"
    active.mkdir(parents=True)
    helper.mkdir(parents=True)
    (installation / "Atlas.update-state.json").write_text("data_moved", encoding="ascii")
    application = helper if helper_caller else active
    selected_owner = {"active": active, "helper": helper,
                      "custody": installation / ".Atlas.database-preflight"}[owner]
    database = selected_owner / ("data/backups/selftest.db" if backup else "data/selftest.db")
    ordinary = str(database)
    unc = "\\\\localhost\\" + database.drive[0] + "$" + ordinary[2:]
    spelling = {"ordinary": ordinary, "extended": "\\\\?\\" + ordinary,
                "unc": unc, "extended_unc": "\\\\?\\UNC\\" + unc[2:],
                "device": "\\\\.\\" + ordinary, "nt_device": "\\??\\" + ordinary}[namespace]
    monkeypatch.setattr(serve, "_frozen", lambda: True)
    monkeypatch.setattr(serve, "_exe_dir", lambda: application)
    monkeypatch.setattr(serve, "_explorer_template_path", lambda: pytest.fail("namespace reached selftest assets"))
    monkeypatch.setattr(serve, "_writable_failure", lambda path: pytest.fail("namespace reached a write probe"))
    assert atlas_entry.main(["--selftest", "--db", spelling]) == 1
    assert "refusing to write" in capsys.readouterr().err
    assert not (active / "data").exists()
    assert not (helper / "data").exists()
    assert not (installation / ".Atlas.database-preflight").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows namespace semantics")
@pytest.mark.parametrize("namespace", ["extended", "unc", "device", "nt_device"])
def test_namespace_spelling_is_refused_before_resolution_or_journal_lookup(tmp_path, monkeypatch, capsys, namespace):
    ordinary = str(tmp_path / "Atlas")
    unc = "\\\\localhost\\" + tmp_path.drive[0] + "$" + ordinary[2:]
    application = Path({"extended": "\\\\?\\" + ordinary, "unc": unc,
                        "device": "\\\\.\\" + ordinary, "nt_device": "\\??\\" + ordinary}[namespace])
    monkeypatch.setattr(serve, "_frozen", lambda: True)
    monkeypatch.setattr(serve, "_exe_dir", lambda: application)
    monkeypatch.setattr(Path, "resolve", lambda *a, **k: pytest.fail("unsupported namespace was resolved"))
    monkeypatch.setattr(serve.os.path, "lexists", lambda *a: pytest.fail("unsupported root reached journal lookup"))
    assert atlas_entry._maintenance_write_refused(external_db=str(tmp_path / "external/selftest.db"))
    assert "namespace" in capsys.readouterr().err


@pytest.mark.skipif(os.name != "nt", reason="Windows namespace semantics")
@pytest.mark.parametrize("namespace", ["extended", "unc", "device", "nt_device"])
def test_executable_namespace_is_refused_before_production_exe_dir_resolves(tmp_path, monkeypatch, capsys, namespace):
    ordinary = str(tmp_path / "Atlas/Atlas.exe")
    unc = "\\\\localhost\\" + tmp_path.drive[0] + "$" + ordinary[2:]
    executable = {"extended": "\\\\?\\" + ordinary, "unc": unc,
                  "device": "\\\\.\\" + ordinary, "nt_device": "\\??\\" + ordinary}[namespace]
    monkeypatch.setattr(serve, "_frozen", lambda: True)
    monkeypatch.setattr(serve.sys, "executable", executable)
    monkeypatch.setattr(Path, "resolve", lambda *a, **k: pytest.fail("executable namespace reached resolution"))
    assert atlas_entry._maintenance_write_refused(external_db=str(tmp_path / "external/selftest.db"))
    assert "namespace" in capsys.readouterr().err


@pytest.mark.skipif(os.name != "nt", reason="Windows namespace semantics")
def test_resolved_namespace_alias_is_not_treated_as_external(tmp_path, monkeypatch, capsys):
    application = tmp_path / "Atlas"
    application.mkdir()
    (tmp_path / "Atlas.update-state.json").write_text("data_moved", encoding="ascii")
    database = tmp_path / "external/selftest.db"
    original = Path.resolve

    def resolved(path, *args, **kwargs):
        if path == database:
            return Path("\\\\?\\" + str(application / "data/selftest.db"))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(serve, "_frozen", lambda: True)
    monkeypatch.setattr(serve, "_exe_dir", lambda: application)
    monkeypatch.setattr(Path, "resolve", resolved)
    monkeypatch.setattr(serve, "_writable_failure", lambda path: pytest.fail("resolved alias reached a probe"))
    assert atlas_entry.run_selftest(db_path=str(database)) == 1
    assert "namespace" in capsys.readouterr().err
    assert not (application / "data").exists()


def test_helper_copies_only_application_code_and_never_opens_data(tmp_path, monkeypatch):
    source = tmp_path / "installed"
    (source / "_internal").mkdir(parents=True)
    (source / "Atlas.exe").write_bytes(b"application")
    (source / "_internal" / "payload.bin").write_bytes(b"runtime")
    (source / "data" / "nested").mkdir(parents=True)
    (source / "data" / "nested" / "evidence.bin").write_bytes(b"DO NOT COPY")
    original = release_contract._read_installed_regular
    reads = []

    def read(path, metadata, maximum, what):
        assert "data" not in path.relative_to(source).parts
        reads.append(path)
        return original(path, metadata, maximum, what)

    verified = []
    censused = []

    def census(root):
        assert root == source
        if not censused:
            assert not target.exists(), "helper bytes were copied before source census"
        censused.append(root)
        return [(name, path, metadata, None if stat.S_ISDIR(metadata.st_mode)
                 else hashlib.sha256(path.read_bytes()).hexdigest())
                for name, path, metadata in release_contract._installed_tree_entries(
                    root, _skip_root_data=True)[0]]

    monkeypatch.setattr(release_contract, "verified_application_entries", census)
    monkeypatch.setattr(release_contract, "_read_installed_regular", read)
    monkeypatch.setattr(release_contract, "verify_installed_bundle", lambda root: verified.append(root))
    target = tmp_path / "helper"
    maintenance._copy_installed_application(source, target)
    assert set(path.relative_to(source).as_posix() for path in reads) == {
        "Atlas.exe", "_internal/payload.bin"}
    assert not (target / "data").exists()
    assert verified == [target]
    assert censused == [source, source]
    assert (target / "_internal" / "payload.bin").read_bytes() == b"runtime"


def test_helper_refuses_a_redirected_application_member(tmp_path, monkeypatch):
    source = tmp_path / "installed"
    source.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    alias = source / "Atlas.exe"
    try:
        alias.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink privilege unavailable: {exc}")
    with pytest.raises(release_contract.PortableReleaseError, match="link/reparse"):
        maintenance._copy_installed_application(source, tmp_path / "helper")
    assert not (tmp_path / "helper").exists()


def test_transaction_uses_the_selected_executable_and_bundled_script(monkeypatch, tmp_path):
    exe = tmp_path / "Atlas" / "Atlas.exe"
    (exe.parent / "_internal" / "portable").mkdir(parents=True)
    script = exe.parent / "_internal" / "portable" / "update_transaction.ps1"
    script.write_text("# fixture\n", encoding="ascii")
    seen = []
    monkeypatch.setattr(maintenance.subprocess, "run", lambda argv, **kw: (
        seen.append((argv, kw)) or subprocess.CompletedProcess(argv, 70)))
    assert maintenance._transaction(exe, ["-Dest", str(tmp_path / "dest")]) == 70
    argv, options = seen[0]
    assert argv[argv.index("-VerifierExe") + 1] == str(exe)
    assert argv[argv.index("-File") + 1] == str(script)
    assert options["cwd"] == str(tmp_path)
    assert options["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert "py" not in argv and "python" not in argv


def test_compatibility_door_cannot_omit_the_operator_digest_or_schema_validation(capsys):
    for argv in (
        ["--zip", "unused.zip", "--allow-runtime-extensions"],
        ["--installed", "unused", "--allow-runtime-extensions", "--expected-sha256", "0" * 64],
        ["--zip", "unused.zip", "--allow-runtime-extensions", "--expected-sha256", "0" * 64,
         "--stdlib-only"],
    ):
        assert verify_release.main(argv) == 1
        assert "updater compatibility requires" in capsys.readouterr().err
    with pytest.raises(release_contract.PortableReleaseError, match="operator-selected"):
        release_contract.verify_portable_release("unused.zip", _allow_runtime_extensions=True)


def test_updater_receipt_discloses_its_policy_without_altering_default_verifier(monkeypatch, capsys):
    seen = []
    result = {"schema": "atlas.portable-verification/1", "status": "SELF_CONSISTENCY_PASS"}
    monkeypatch.setattr(verify_release, "verify_portable_release", lambda path, **kw: (
        seen.append(kw) or result))
    assert verify_release.main(["--zip", "unused.zip"]) == 0
    assert json.loads(capsys.readouterr().out) == result
    assert seen[-1]["_allow_runtime_extensions"] is False
    assert verify_release.main(["--zip", "unused.zip", "--expected-sha256", "0" * 64,
                                "--allow-runtime-extensions"]) == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["schema"] == "atlas.portable-update-verification/1"
    assert envelope["verification"] == result
    assert envelope["authentication"] == "operator_selected_digest_not_publisher_authentication"
    assert seen[-1]["validate_sbom_schema"] is True
    assert seen[-1]["_allow_runtime_extensions"] is True


def test_wrapper_and_transaction_have_no_interpreter_or_repository_fallback():
    wrapper = (ROOT / "portable/make_stick.ps1").read_text(encoding="ascii")
    transaction = (ROOT / "portable/update_transaction.ps1").read_text(encoding="ascii")
    assert len(wrapper.splitlines()) < 100
    assert "--install" in wrapper and "--update" in wrapper and "--rollback" in wrapper
    for text in (wrapper, transaction):
        assert 'Invoke-BoundedProcess "py"' not in text
        assert "-m portable.verify_release" not in text
        assert "$repoRoot" not in text
    assert '@("--verify-release") + $VerifierArgs' in transaction
    assert "-SkipSelftest is forbidden for a release package" in transaction
    assert "-VerifierExe" not in wrapper


def test_published_digest_is_checked_before_any_candidate_receipt_is_parsed(tmp_path, monkeypatch):
    path = tmp_path / "not-even-a-zip.zip"
    path.write_bytes(b"unapproved bytes")
    monkeypatch.setattr(release_contract.zipfile, "ZipFile", lambda *a, **k: pytest.fail("parsed candidate"))
    with pytest.raises(release_contract.PortableReleaseError, match="expected digest"):
        release_contract.verify_portable_release(
            path, expected_zip_sha256="0" * 64, _allow_runtime_extensions=True)


def test_successor_inventory_cannot_remove_or_replace_installed_dependencies():
    current = dict(release_contract.EXPECTED_BUNDLED_PYTHON)
    successor = {**current, "synthetic-new-window-runtime": "6.0"}
    assert release_contract._runtime_inventory_matches(current, allow_extensions=False)
    assert not release_contract._runtime_inventory_matches(successor, allow_extensions=False)
    assert release_contract._runtime_inventory_matches(successor, allow_extensions=True)
    for name in current:
        missing = dict(successor)
        del missing[name]
        assert not release_contract._runtime_inventory_matches(missing, allow_extensions=True)
        changed = {**successor, name: "0.0.0"}
        assert not release_contract._runtime_inventory_matches(changed, allow_extensions=True)
    for forbidden in release_contract._FORBIDDEN_PACKAGE_PARTS:
        assert not release_contract._runtime_inventory_matches(
            {**successor, forbidden: "1.0"}, allow_extensions=True)
        assert not release_contract._runtime_inventory_matches(
            {**successor, forbidden.upper(): "1.0"}, allow_extensions=True)
    for noncanonical in ("Window_Runtime", "window.runtime", "window--runtime", "openai ", "\u200bopenai", "\uff4f\uff50\uff45\uff4e\uff41\uff49"):
        assert not release_contract._runtime_inventory_matches(
            {**successor, noncanonical: "1.0"}, allow_extensions=True)


@pytest.mark.parametrize("relative", [
    "Atlas.update-state.json", ".Atlas.update.lock", "Atlas.rollback-slot.json",
    "Atlas/Atlas.maintenance-result." + "a" * 32 + ".json",
    "Atlas.previous/Atlas.maintenance-result." + "a" * 32 + ".json",
])
def test_result_cannot_overwrite_transaction_journals_locks_or_application_slots(tmp_path, relative):
    with pytest.raises(ValueError, match="fresh Atlas.maintenance-result"):
        maintenance._result_path(tmp_path, str(tmp_path / relative), "a" * 32)
    assert not (tmp_path / relative).exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows OS-owned handle semantics")
def test_handoff_lock_releases_after_abrupt_exit_even_though_its_file_remains(tmp_path):
    ready = tmp_path / "ready"
    code = (
        "import sys,time; from pathlib import Path; from portable.maintenance import _handoff_lock; "
        "root=Path(sys.argv[1]); "
        "context=_handoff_lock(root); context.__enter__(); "
        "(root/'ready').write_text('held'); time.sleep(300)"
    )
    child = subprocess.Popen([sys.executable, "-B", "-c", code, str(tmp_path)], cwd=ROOT)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            assert child.poll() is None, "lock owner exited before acquiring its handle"
            time.sleep(0.05)
        assert ready.exists(), "lock owner did not acquire its handle"
        with pytest.raises(OSError, match="handoff lock"):
            with maintenance._handoff_lock(tmp_path):
                pytest.fail("second maintenance process acquired an already-held handle")
        child.kill()
        child.wait(timeout=10)
        assert (tmp_path / ".Atlas.maintenance.lock").is_file()
        with maintenance._handoff_lock(tmp_path):
            pass
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=10)
