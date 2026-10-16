"""Counterexamples for the hosted Python-absent desktop proof's evidence checks."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
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
                 "HTTPS_PROXY": "http://proxy.invalid", "ATLAS_PORTABLE_ALLOW_LIVE_NETWORK": "1"}
    environment = proof.runtime_environment(inherited, tmp_path)
    assert {key.casefold() for key in environment}.isdisjoint(
        {"pythonhome", "pythonpath", "virtual_env", "https_proxy", "atlas_portable_allow_live_network"}
    )
    assert [value for key, value in environment.items() if key.casefold() == "path"] == [
        str(Path("C:/Windows") / "System32")
    ]
    assert "py.exe" in proof.PYTHON_COMMANDS


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
    assert set(jobs) == {"gate", "portable", "verify_candidate", "draft"}
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
