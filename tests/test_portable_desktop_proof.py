"""Counterexamples for the hosted Python-absent desktop proof's evidence checks."""

from __future__ import annotations

import importlib.util
import json
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import zipfile

import pytest
import yaml

from test_release_supply_chain import _RunnerWorkflowLoader


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "atlas_desktop_proof", ROOT / ".github/scripts/prove_portable_no_python.py"
)
assert SPEC is not None and SPEC.loader is not None
proof = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proof)


def test_sanitization_removes_mixed_case_python_overrides_and_launcher_path(tmp_path: Path) -> None:
    inherited = {"Path": "C:/Python;C:/Windows;C:/launchers", "PythonHome": "bad",
                 "pythonpath": "bad", "SYSTEMROOT": "C:/Windows", "VIRTUAL_ENV": "bad",
                 "HTTPS_PROXY": "http://proxy.invalid", "ATLAS_PORTABLE_ALLOW_LIVE_NETWORK": "1",
                 "PYTHONBREAKPOINT": "bad", "Python_ROOT_DIR": "bad", "PYTHONUSERBASE": "bad",
                 "pythonOddFutureOption": "bad", "_PYTHON_HOST_PLATFORM": "bad",
                 "PY_PYTHON": "bad", "PYLAUNCHER_DEBUG": "bad"}
    environment = proof.runtime_environment(inherited, tmp_path)
    assert {key.casefold() for key in environment}.isdisjoint(
        {"pythonhome", "pythonpath", "virtual_env", "https_proxy", "atlas_portable_allow_live_network"}
    )
    assert [value for key, value in environment.items() if key.casefold() == "path"] == [
        str(Path("C:/Windows") / "System32")
    ]
    assert "py.exe" in proof.PYTHON_COMMANDS
    assert not any(key.casefold().lstrip("_").startswith(("python", "py_", "pylauncher_")) for key in environment)


@pytest.mark.parametrize("location", ["app", "cwd", "system32", "system16", "windows", "powershell"])
def test_python_absence_checks_every_process_search_location(tmp_path, monkeypatch, location):
    directories = {name: tmp_path / name for name in
                   ("app", "cwd", "system32", "system16", "windows", "powershell")}
    for path in directories.values():
        path.mkdir()
    (directories["system32"] / "where.exe").write_bytes(b"synthetic lookup probe")
    monkeypatch.setattr(proof.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess([], 1))
    environment = {"PATH": str(directories["system32"])}
    systems = tuple(directories[name] for name in ("system32", "system16", "windows", "powershell"))
    proof.assert_python_hidden(environment, directories["cwd"], (directories["app"],), systems)
    (directories[location] / "python3.12.exe").write_bytes(b"must be detected even outside PATH")
    with pytest.raises(RuntimeError, match="complete Windows"):
        proof.assert_python_hidden(environment, directories["cwd"], (directories["app"],), systems)


def test_hosted_launcher_quarantine_is_journaled_and_restored_on_failure(tmp_path):
    system = tmp_path / "windows"
    system.mkdir()
    launcher = system / "py.exe"
    launcher.write_bytes(b"synthetic launcher")
    journal = tmp_path / "journal.json"
    with pytest.raises(ValueError, match="synthetic proof refusal"):
        with proof.hidden_system_python_launchers(journal, (system,)):
            assert not launcher.exists()
            record = json.loads(journal.read_text(encoding="utf-8"))
            assert record["status"] == "restoration_required"
            assert len(record["originals"]) == 1
            raise ValueError("synthetic proof refusal")
    assert launcher.read_bytes() == b"synthetic launcher"
    assert json.loads(journal.read_text(encoding="utf-8"))["status"] == "restored"
    assert list(system.iterdir()) == [launcher]


def test_hosted_launcher_quarantine_refuses_hardlinks_before_moving_any_bytes(tmp_path):
    system = tmp_path / "windows"
    system.mkdir()
    launcher = system / "py.exe"
    launcher.write_bytes(b"synthetic launcher")
    try:
        os.link(launcher, tmp_path / "linked.bin")
    except OSError as error:
        pytest.skip(str(error))
    with pytest.raises(RuntimeError, match="multiply-linked"):
        with proof.hidden_system_python_launchers(tmp_path / "journal.json", (system,)):
            pytest.fail("hardlinked launcher was hidden")
    assert launcher.read_bytes() == b"synthetic launcher"


def test_unmoved_launcher_with_same_bytes_but_replaced_identity_is_not_claimed_restored(tmp_path, monkeypatch):
    system = tmp_path / "windows"
    system.mkdir()
    launcher = system / "py.exe"
    launcher.write_bytes(b"synthetic launcher")
    replacement = tmp_path / "replacement.bin"
    replacement.write_bytes(launcher.read_bytes())
    original_replace = proof.os.replace

    def raced_replace(source, destination):
        if source == launcher:
            original_replace(replacement, launcher)
            raise OSError("synthetic rename refusal after external replacement")
        return original_replace(source, destination)

    monkeypatch.setattr(proof.os, "replace", raced_replace)
    with pytest.raises(RuntimeError, match="unmoved launcher identity changed"):
        with proof.hidden_system_python_launchers(tmp_path / "journal.json", (system,)):
            pytest.fail("replaced launcher was hidden")
    assert launcher.read_bytes() == b"synthetic launcher"
    assert json.loads((tmp_path / "journal.json").read_text())["status"] == "restoration_refused"


def test_verified_reinstall_copy_retains_hidden_files_and_empty_directories(tmp_path):
    original = tmp_path / "old-data"
    (original / "retained-empty").mkdir(parents=True)
    (original / ".retained-hidden").write_bytes(b"synthetic original evidence")
    backup = tmp_path / "offline-backup"
    inventory = proof.copy_data_verified(original, backup)
    assert inventory["directories"] == ["retained-empty"]
    assert (backup / ".retained-hidden").read_bytes() == b"synthetic original evidence"
    with pytest.raises(RuntimeError, match="fresh"):
        proof.copy_data_verified(original, backup)
    assert proof.data_inventory(original) == inventory == proof.data_inventory(backup)


@pytest.mark.parametrize("contaminate_kit", [False, True])
def test_managed_fallback_extracts_selftests_external_and_adopts_preserved_data(
    tmp_path, monkeypatch, contaminate_kit,
):
    old = tmp_path / "old/Atlas"
    (old / "data/retained-empty").mkdir(parents=True)
    (old / "Atlas.exe").write_bytes(b"old synthetic executable")
    with closing(sqlite3.connect(old / "data/assesshub.db")) as connection:
        connection.execute("CREATE TABLE snapshots(id, campaign_id, label, snapshot_json)")
        connection.execute("INSERT INTO snapshots VALUES(1, 1, 'retained', '{}')")
        connection.commit()
    before = proof.data_inventory(old)
    package = tmp_path / "candidate.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("Atlas/Atlas.exe", b"new synthetic executable")
    bootstrap = proof.extract_bootstrap(package, tmp_path / "bootstrap")
    expected_sha = proof.digest(package)
    calls = []

    def run(executable, arguments, environment, cwd, **kwargs):
        calls.append(arguments[0])
        candidate = cwd / "verified-reinstall/Atlas"
        if arguments[0] == "-NoProfile":
            assert "Expand-Archive -LiteralPath" in arguments[-1]
            assert environment["ATLAS_PROOF_PACKAGE"] == str(package)
            proof.extract_bootstrap(package, Path(environment["ATLAS_PROOF_DESTINATION"]))
        elif arguments[0] == "--verify-release":
            assert arguments == ["--verify-release", "--zip", str(package), "--expected-sha256", expected_sha]
            return subprocess.CompletedProcess([], 0, '{"status":"SELF_CONSISTENCY_PASS"}', "")
        elif arguments[0] == "--selftest":
            assert arguments[1] == "--db"
            database = Path(arguments[2])
            assert database == cwd / "candidate-selftest/selftest.db"
            assert not database.is_relative_to(candidate)
            assert not (candidate / "data").exists()
            (database.parent / "backups").mkdir()
            if contaminate_kit:
                (candidate / "data/backups").mkdir(parents=True)
        elif arguments[0] == "--database-preflight":
            assert not any((candidate / "data").iterdir())
            database = Path(arguments[1])
            marker = database.parent / "atlas-db-preflight.json"
            request = json.loads(marker.read_bytes())
            receipt = {"schema": "atlas.database-preflight/1", "status": "pass", "quick_check": "ok",
                       "request_nonce": request["nonce"], "request_sha256": proof.digest(marker),
                       "input_copy_binding": {"database_name": database.name,
                                              "bytes": request["input_copy_bytes"],
                                              "sha256": request["input_copy_sha256"]},
                       "migrated_copy_sha256": proof.digest(database),
                       "migrated_copy_bytes": database.stat().st_size,
                       "logical_migration": {"status": "pass", "prior_table_preservation": [{"status": "preserved"}]}}
            return subprocess.CompletedProcess([], 0, json.dumps(receipt), "")
        else:
            pytest.fail("managed fallback invoked an unexpected command: " + arguments[0])
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(proof, "run", run)
    monkeypatch.setattr(proof, "windows_system_search_directories", lambda: (tmp_path / "system32",))
    monkeypatch.setattr(proof, "seed_database", lambda *a, **k: None)
    if contaminate_kit:
        with pytest.raises(RuntimeError, match="selftest populated"):
            proof.prove_verified_reinstall(bootstrap, package, expected_sha, old, {}, tmp_path,
                                          managed_policy=True)
        assert calls == ["-NoProfile", "--verify-release", "--selftest"]
    else:
        result = proof.prove_verified_reinstall(bootstrap, package, expected_sha, old, {}, tmp_path,
                                               managed_policy=True)
        assert result["status"] == "PASS"
        assert result["preparation"] == "expand_archive_verify_external_db_selftest_adopt"
        assert calls == ["-NoProfile", "--verify-release", "--selftest", "--database-preflight"]
        adopted = tmp_path / "managed-policy-reinstall/verified-reinstall/Atlas/data"
        assert proof.database_state(adopted / "assesshub.db")["rows"] == [(1, 1, "retained", "{}")]
        assert (adopted / "retained-empty").is_dir()
        assert not (adopted / "backups").exists()
    assert proof.data_inventory(old) == before


@pytest.mark.parametrize("mutation", [
    {"status": "scheduled"}, {"exit_code": True}, {"exit_code": 70},
    {"schema": "atlas.maintenance-result/2"}, {"verifier_origin": "repository_python"},
    {"verification_policy": "unverified"},
])
def test_dispatch_or_untrusted_receipt_cannot_claim_completion(mutation: dict) -> None:
    value = {"schema": "atlas.maintenance-result/1", "status": "complete", "exit_code": 0,
             "verifier_origin": "installed_atlas", "verification_policy": "sha256_bound_runtime_extension"}
    value.update(mutation)
    with pytest.raises(RuntimeError):
        proof.validate_result(value, 0)


def test_fault_injection_requires_refusal_and_exact_failure_code() -> None:
    value = {"schema": "atlas.maintenance-result/1", "status": "refused", "exit_code": 70,
             "verifier_origin": "installed_atlas", "verification_policy": "sha256_bound_runtime_extension"}
    assert proof.validate_result(value, 70) == value
    value["status"] = "complete"
    with pytest.raises(RuntimeError):
        proof.validate_result(value, 70)


def test_first_install_digest_comes_from_published_checksums_and_refuses_substitution(tmp_path: Path) -> None:
    package = tmp_path / "Atlas-test-windows-x64.zip"
    package.write_bytes(b"published package")
    expected = proof.digest(package)
    checksum = package.with_suffix(".SHA256SUMS")
    checksum.write_text(expected + "  " + package.name + "\n", encoding="ascii")
    assert proof.published_digest(package) == expected
    package.write_bytes(b"substituted package")
    with pytest.raises(RuntimeError, match="differs from published"):
        proof.published_digest(package)
    checksum.write_text((expected + "  " + package.name + "\n") * 2, encoding="ascii")
    with pytest.raises(RuntimeError, match="exactly one"):
        proof.published_digest(package)


@pytest.mark.parametrize("member", ["../outside.txt", "Atlas/../outside.txt", "Atlas/C:/outside.txt",
                                     "Atlas\\..\\outside.txt", "/Atlas/Atlas.exe"])
def test_bootstrap_extraction_rejects_traversal_before_writing(tmp_path: Path, member: str) -> None:
    package = tmp_path / "candidate.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("Atlas/Atlas.exe", b"synthetic executable")
        archive.writestr(member, b"escape")
    destination = tmp_path / "bootstrap"
    with pytest.raises(RuntimeError):
        proof.extract_bootstrap(package, destination)
    assert not destination.exists()


def test_preservation_allows_new_backups_but_refuses_missing_or_changed_client_data(tmp_path: Path) -> None:
    canary = tmp_path / "canary.txt"
    canary.write_bytes(b"original data")
    before = proof.files(tmp_path)
    (tmp_path / "additional-backup.db").write_bytes(b"new backup")
    proof.unchanged_data(before, tmp_path)
    canary.write_bytes(b"changed data")
    with pytest.raises(RuntimeError):
        proof.unchanged_data(before, tmp_path)
    canary.unlink()
    with pytest.raises(RuntimeError):
        proof.unchanged_data(before, tmp_path)


def test_rollback_receipt_must_bind_both_whole_application_trees(tmp_path: Path) -> None:
    active, previous = tmp_path / "Atlas", tmp_path / "Atlas.previous"
    for directory in (active, previous):
        directory.mkdir()
        (directory / "Atlas.exe").write_bytes(b"same executable")
        (directory / "dependency.dll").write_bytes(b"approved dependency")
    receipt = {"schema": "atlas.portable-rollback-slot/1"}
    for prefix, directory in (("active", active), ("previous", previous)):
        receipt[prefix + "_exe_sha256"] = proof.digest(directory / "Atlas.exe")
        receipt[prefix + "_tree_sha256"] = proof.tree_digest(directory)
    (tmp_path / "Atlas.rollback-slot.json").write_text(json.dumps(receipt), encoding="utf-8")
    proof.verify_slot(tmp_path)
    (previous / "dependency.dll").write_bytes(b"substituted dependency, executable untouched")
    with pytest.raises(RuntimeError, match="whole-application"):
        proof.verify_slot(tmp_path)


@pytest.mark.parametrize("helper", ["../outside/Atlas.exe", "Atlas/Atlas.exe",
                                    "Atlas.maintenance-" + "a" * 32 + "/../Atlas/Atlas.exe"])
def test_missing_active_recovery_refuses_unowned_helper_paths(tmp_path: Path, helper: str) -> None:
    pointer = {"schema": "atlas.maintenance-recovery/1", "helper": helper, "helper_exe_sha256": "0" * 64}
    (tmp_path / "Atlas.maintenance.json").write_text(json.dumps(pointer), encoding="utf-8")
    with pytest.raises(RuntimeError, match="safe installed-code"):
        proof.recovery_helper(tmp_path)


def test_missing_active_recovery_binds_recorded_helper_bytes(tmp_path: Path) -> None:
    relative = "Atlas.maintenance-" + "a" * 32 + "/Atlas/Atlas.exe"
    helper = tmp_path.joinpath(*relative.split("/"))
    helper.parent.mkdir(parents=True)
    helper.write_bytes(b"installed-version helper")
    pointer = {"schema": "atlas.maintenance-recovery/1", "helper": relative,
               "helper_exe_sha256": proof.digest(helper)}
    (tmp_path / "Atlas.maintenance.json").write_text(json.dumps(pointer), encoding="utf-8")
    assert proof.recovery_helper(tmp_path) == helper
    helper.write_bytes(b"substituted helper")
    with pytest.raises(RuntimeError, match="digest differs"):
        proof.recovery_helper(tmp_path)


def test_python_absent_proof_runs_in_existing_build_context_after_packaging() -> None:
    workflow = yaml.load((ROOT / ".github/workflows/portable-release.yml").read_text(encoding="utf-8"),
                         Loader=_RunnerWorkflowLoader)
    jobs = workflow["jobs"]
    assert set(jobs) == {"gate_shard", "gate", "portable", "verify_candidate", "draft"}
    portable = jobs["portable"]
    assert portable["name"] == "Build and qualify Atlas.exe"
    assert portable["timeout-minutes"] == 120
    steps = portable["steps"]
    proof_steps = [step for step in steps if "prove_portable_no_python.py" in step.get("run", "")]
    assert len(proof_steps) == 1
    selected = proof_steps[0]
    assert "continue-on-error" not in selected and "if" not in selected
    assert "atlas-portable-venv\\Scripts\\python.exe" in selected["run"]
    assert "$LASTEXITCODE -ne 0" in selected["run"]
    packaging = next(step for step in steps if "-m portable.build_release" in step.get("run", ""))
    assert steps.index(packaging) < steps.index(selected)
    artifacts = [step for step in steps if step.get("with", {}).get("name", "").startswith("atlas-desktop-no-python-")]
    assert len(artifacts) == 1
    assert artifacts[0]["with"]["if-no-files-found"] == "error"


def test_runtime_smoke_copy_preserves_package_and_excludes_only_root_metadata(tmp_path: Path) -> None:
    package = tmp_path / "package" / "Atlas"
    (package / "release-metadata").mkdir(parents=True)
    (package / "release-metadata" / "manifest.json").write_text("retained metadata", encoding="ascii")
    (package / "_internal" / "release-metadata").mkdir(parents=True)
    (package / "_internal" / "release-metadata" / "runtime.bin").write_bytes(b"nested runtime bytes")
    (package / "Atlas.exe").write_bytes(b"synthetic application bytes")
    before = proof.files(package)
    runtime = tmp_path / "runtime" / "Atlas"
    assert proof.copy_runtime_for_smoke(package, runtime) == before
    assert proof.files(package) == before
    assert not (runtime / "release-metadata").exists()
    assert (runtime / "_internal" / "release-metadata" / "runtime.bin").read_bytes() == b"nested runtime bytes"
    assert (runtime / "Atlas.exe").read_bytes() == b"synthetic application bytes"


@pytest.mark.parametrize("valid_schema", [True, False])
def test_database_observer_releases_its_handle_on_success_and_query_failure(tmp_path: Path, monkeypatch,
                                                                          valid_schema: bool) -> None:
    database = tmp_path / "synthetic.db"
    original_connect = sqlite3.connect
    with closing(original_connect(database)) as connection:
        if valid_schema:
            connection.execute("CREATE TABLE snapshots(id, campaign_id, label, snapshot_json)")
            connection.execute("INSERT INTO snapshots VALUES(1, 1, 'synthetic', '{}')")
        else:
            connection.execute("CREATE TABLE different_table(id)")
        connection.commit()
    held = []

    def observed_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        held.append(connection)  # keep it alive: garbage collection cannot mask a leaked handle
        return connection

    monkeypatch.setattr(proof.sqlite3, "connect", observed_connect)
    if valid_schema:
        assert proof.database_state(database)["rows"] == [(1, 1, "synthetic", "{}")]
    else:
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            proof.database_state(database)
    assert len(held) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        held[0].execute("SELECT 1")
