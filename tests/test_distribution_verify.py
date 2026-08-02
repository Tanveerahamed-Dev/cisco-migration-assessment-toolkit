from __future__ import annotations

import base64
import hashlib
import inspect
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

import pytest

from cisco_toolkit import distribution_verify
from cisco_toolkit.distribution_verify import (
    _BINDING_ENFORCEMENT,
    _EXIT_UNVERIFIED_BINDING,
    _EXPECTED_CONSOLE_SCRIPTS,
    _EXPECTED_TOP_LEVEL_PACKAGES,
    _INDEPENDENCE_LIMIT,
    _MAX_MEMBER_BYTES,
    _OFFICIAL_SOURCE_FILES,
    _PROVENANCE_INDEX,
    _PROVENANCE_REQUIRED,
    _PROVENANCE_WORKTREE,
    _SDIST_SOURCE_FILES,
    _SOURCE_BINDING_GIT,
    _SOURCE_BINDING_UNVERIFIED,
    _WHEEL_METADATA_FILES,
    _archive_name_errors,
    _content_privacy_errors,
    _expected_runtime_inventory,
    _frontend_reference_errors,
    _generated_setup_cfg_errors,
    _is_build_generated,
    _metadata_signature,
    _normalise_sdist,
    _privacy_violations,
    _project_metadata_contract,
    _proof_caveats,
    _requires_txt_values,
    _runtime_inventory_proof,
    _sdist_source_inventory_proof,
    _shipped_coverage_proof,
    _source_binding,
    _stable_source_authority_proof,
    _tar_preflight,
    _validated_git_oid,
    _verify_expected_proof,
    _verify_sdist_metadata,
    _verify_wheel_record,
    _write_new_proof,
    _zip_container_errors,
    _zip_preflight,
    verify_archives,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "1" * 40
SOURCE_TREE = "2" * 40


def test_pep639_license_expression_has_no_superseded_license_classifier():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'license = "LicenseRef-Proprietary"' in pyproject
    assert '"License ::' not in pyproject


def test_build_backend_uses_exact_nonvulnerable_tool_versions():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert (
        'requires = ["setuptools==83.0.0", "wheel==0.46.2"]'
        in pyproject
    )
    assert "setuptools==80.9.0" not in pyproject
    assert "wheel==0.45.1" not in pyproject


def test_privacy_boundary_rejects_tests_office_files_and_non_sample_snapshots():
    violations = _privacy_violations({
        "tests/test_x.py",
        "docs/private.md",
        "out/client.xlsx",
        "out/client.snapshot.json",
        "webapp/sample_data/sample_fleet.snapshot.json",
        "cisco_toolkit/model.py",
    })
    assert violations == [
        "docs/private.md",
        "out/client.snapshot.json",
        "out/client.xlsx",
        "tests/test_x.py",
    ]


def test_archive_verifier_requires_exactly_one_pair(tmp_path):
    with pytest.raises(ValueError, match="exactly one wheel"):
        verify_archives(
            tmp_path,
            tmp_path,
            source_commit=SOURCE_COMMIT,
            source_tree=SOURCE_TREE,
        )


def test_distribution_proof_requires_complete_lowercase_git_object_ids():
    assert _validated_git_oid(SOURCE_COMMIT, "source commit") == SOURCE_COMMIT
    assert _validated_git_oid("a" * 64, "source tree") == "a" * 64
    for invalid in ("abc", "A" * 40, "g" * 40, "1" * 39):
        with pytest.raises(ValueError, match="complete lowercase"):
            _validated_git_oid(invalid, "source commit")


def test_archive_verifier_rejects_traversal_absolute_and_duplicate_members():
    errors = _archive_name_errors([
        "safe/file.py",
        "safe/file.py",
        "safe/File.py",
        "safe//alias.py",
        "safe/./alias.py",
        "safe/NUL.txt",
        "safe/trailing.",
        "safe/stream:name",
        "Package/one.py",
        "package/two.py",
        "../escape.py",
        "/absolute.py",
        r"windows\escape.py",
        "C:/drive.py",
    ])
    assert "duplicate member: safe/file.py" in errors
    assert any("Windows-colliding members" in error for error in errors)
    assert any("safe//alias.py" in error for error in errors)
    assert any("safe/./alias.py" in error for error in errors)
    assert any("safe/NUL.txt" in error for error in errors)
    assert any("safe/trailing." in error for error in errors)
    assert any("safe/stream:name" in error for error in errors)
    assert any("Windows-colliding path components" in error for error in errors)
    assert any("unsafe member path: '../escape.py'" in error for error in errors)
    assert any("unsafe member path: '/absolute.py'" in error for error in errors)
    assert any("windows" in error for error in errors)
    assert any("C:/drive.py" in error for error in errors)


def test_frontend_index_requires_local_assets_present_in_archive():
    index = b"""
    <script type="module" src="/assets/app.js"></script>
    <link rel="stylesheet" href="/assets/app.css">
    <script src="https://cdn.example.invalid/tracker.js"></script>
    """
    errors = _frontend_reference_errors(
        index,
        {
            "webapp/frontend/dist/index.html",
            "webapp/frontend/dist/assets/app.js",
        },
    )
    assert errors == [
        "frontend index uses a non-local runtime asset: "
        "'https://cdn.example.invalid/tracker.js'",
        "frontend index references missing archive member: "
        "webapp/frontend/dist/assets/app.css",
    ]


def test_trusted_distribution_proof_rejects_archive_drift(tmp_path):
    proof = tmp_path / "dist-verification.json"
    proof.write_text('{"wheel_sha256": "old"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="differing fields"):
        _verify_expected_proof({"wheel_sha256": "new"}, proof)


def test_trusted_distribution_proof_rejects_duplicate_keys_and_oversize(
    tmp_path,
    monkeypatch,
):
    proof = tmp_path / "dist-verification.json"
    proof.write_text(
        '{"wheel_sha256":"first","wheel_sha256":"second"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        _verify_expected_proof({"wheel_sha256": "second"}, proof)

    monkeypatch.setattr(
        "cisco_toolkit.distribution_verify._MAX_PROOF_BYTES",
        8,
    )
    proof.write_text('{"long":"payload"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="exceeds 8 bytes"):
        _verify_expected_proof({"long": "payload"}, proof)


def test_distribution_proof_writer_is_exclusive_and_readback_verified(tmp_path):
    proof = tmp_path / "dist-verification.json"
    _write_new_proof(proof, '{"verified": true}')
    assert proof.read_bytes() == b'{"verified": true}\n'

    with pytest.raises(FileExistsError):
        _write_new_proof(proof, '{"verified": false}')
    assert proof.read_bytes() == b'{"verified": true}\n'


def test_archive_preflight_rejects_member_and_aggregate_bombs():
    oversized = zipfile.ZipInfo("large.bin")
    oversized.file_size = _MAX_MEMBER_BYTES + 1
    wheel_errors = _zip_preflight([oversized])
    assert any("member exceeds" in error for error in wheel_errors)

    tar_member = tarfile.TarInfo("pkg/large.bin")
    tar_member.size = _MAX_MEMBER_BYTES + 1
    tar_errors = _tar_preflight([tar_member])
    assert any("member exceeds" in error for error in tar_errors)


def test_wheel_container_preflight_rejects_declared_member_bomb(tmp_path):
    wheel = tmp_path / "probe.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("pkg/data.txt", b"data")
    payload = bytearray(wheel.read_bytes())
    end = payload.rfind(b"PK\x05\x06")
    assert end >= 0
    assert _zip_container_errors(bytes(payload)) == []

    declared = 10_001
    payload[end + 8:end + 10] = declared.to_bytes(2, "little")
    payload[end + 10:end + 12] = declared.to_bytes(2, "little")
    assert any(
        "declares 10001 members" in error
        for error in _zip_container_errors(bytes(payload))
    )


def test_metadata_contract_rejects_dependency_injection_and_singleton_spoofing():
    contract = _project_metadata_contract(ROOT)
    lines = ["Metadata-Version: 2.4"]
    for header, values in contract["headers"].items():
        lines.extend(f"{header}: {value}" for value in values)
    valid = (
        "\n".join(lines)
        + "\n\n"
        + contract["description"]
    ).encode("utf-8")
    _, errors = _metadata_signature(valid, contract, label="probe")
    assert errors == []

    injected = valid.replace(
        b"Requires-Dist: netmiko<5,>=4.1",
        b"Requires-Dist: attacker-package>=1",
        1,
    )
    _, errors = _metadata_signature(injected, contract, label="probe")
    assert any("Requires-Dist differs" in error for error in errors)

    duplicated = valid.replace(
        f"Name: {contract['name']}\n".encode(),
        (
            f"Name: {contract['name']}\n"
            f"Name: {contract['name']}\n"
        ).encode(),
        1,
    )
    _, errors = _metadata_signature(duplicated, contract, label="probe")
    assert any("repeats singleton header Name" in error for error in errors)


def test_sdist_requires_txt_supports_setuptools_marker_sections():
    values = _requires_txt_values(
        b"""
netmiko<5,>=4.1
[:python_version < "3.11"]
tomli<3,>=2
[dev]
pytest<10,>=8
[docs:python_version >= "3.12"]
sphinx<9,>=8
"""
    )

    assert values == [
        "netmiko<5,>=4.1",
        'tomli<3,>=2; python_version < "3.11"',
        'pytest<10,>=8; extra == "dev"',
        'sphinx<9,>=8; python_version >= "3.12" and extra == "docs"',
    ]


def test_sdist_generated_setup_cfg_is_exactly_setuptools_version_tags():
    assert (
        _generated_setup_cfg_errors(
            b"[egg_info]\ntag_build = \ntag_date = 0\n"
        )
        == []
    )
    assert _generated_setup_cfg_errors(
        b"[egg_info]\ntag_build = .dev\ntag_date = 0\n"
    )
    assert _generated_setup_cfg_errors(
        b"[egg_info]\ntag_build = \ntag_date = 0\n[upload]\nrepository = evil\n"
    )


def test_archive_content_scanner_checks_payload_not_only_name():
    errors, scanned = _content_privacy_errors(
        "cisco_toolkit/innocent.py",
        ("# " + "Al " + "Jazeera" + " fleet\n").encode(),
        set(),
    )
    assert errors == [
        "known client marker appears in archive content: "
        "cisco_toolkit/innocent.py"
    ]
    assert scanned is True


def test_archive_content_scanner_reports_exempt_members_as_not_scanned():
    """An exempt member's bytes are never read; it must not count as scanned.

    `archive_content_privacy_verified: true` used to cover both cases with the
    same literal, so a proof could not distinguish "every member was scanned"
    from "every member was exempt".
    """
    errors, scanned = _content_privacy_errors(
        "cisco_toolkit/data/oui_registry.tsv.gz",
        ("# " + "Al " + "Jazeera" + " fleet\n").encode(),
        set(),
    )
    assert errors == []
    assert scanned is False

    # Non-vacuity: the very same payload under a non-exempt name IS scanned and
    # does flag, so the False above reports exemption, not an inert scanner.
    flagged, flagged_scanned = _content_privacy_errors(
        "cisco_toolkit/data/other_registry.tsv.gz",
        ("# " + "Al " + "Jazeera" + " fleet\n").encode(),
        set(),
    )
    assert flagged_scanned is True
    assert flagged == [
        "known client marker appears in archive content: "
        "cisco_toolkit/data/other_registry.tsv.gz"
    ]


def test_source_authority_proof_removes_only_live_clock_age():
    stable = _stable_source_authority_proof({
        "verified": True,
        "source_age_days": 1.25,
        "source_fresh": True,
        "source_retrieved_at": "2026-07-30T12:47:53Z",
    })
    assert stable == {
        "verified": True,
        "source_fresh": True,
        "source_retrieved_at": "2026-07-30T12:47:53Z",
    }
    with pytest.raises(ValueError, match="invalid source age"):
        _stable_source_authority_proof({"source_age_days": True})


def _record_verdict(tmp_path: Path, encoded_hash: str) -> tuple[list[str], int]:
    wheel = tmp_path / "probe.whl"
    if wheel.exists():
        wheel.unlink()
    record = (
        f"pkg/data.txt,{encoded_hash},4\npkg-1.0.dist-info/RECORD,,\n"
    )
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("pkg/data.txt", b"data")
        archive.writestr("pkg-1.0.dist-info/RECORD", record)
    with zipfile.ZipFile(wheel) as archive:
        return _verify_wheel_record(
            archive,
            {
                info.filename: info
                for info in archive.infolist()
                if not info.is_dir()
            },
            {"pkg/data.txt", "pkg-1.0.dist-info/RECORD"},
            "pkg-1.0.dist-info",
        )


def test_wheel_record_hash_mismatch_is_detected(tmp_path):
    errors, measurement = _record_verdict(tmp_path, "sha256=not-the-hash")
    assert errors == ["wheel RECORD sha256 mismatch for pkg/data.txt"]
    assert measurement["members_hashed"] == 0
    # The unhashed member is reported as unhashed, not folded into the exemption.
    assert measurement["members_exempt_record_self_reference"] == 1
    assert measurement["members_neither_hashed_nor_exempt"] == 1


def test_wheel_record_reports_how_many_members_it_actually_hashed(tmp_path):
    """The count is the measurement `record_hashes_verified: true` never was.

    A wheel whose RECORD hashes nothing and a wheel whose RECORD hashes every
    member both produced the same literal `true` in the emitted proof.
    """
    import base64
    import hashlib

    digest = (
        base64.urlsafe_b64encode(hashlib.sha256(b"data").digest())
        .rstrip(b"=")
        .decode()
    )
    errors, measurement = _record_verdict(tmp_path, f"sha256={digest}")
    assert errors == []
    # Non-vacuity: the clean wheel reports a NON-ZERO count, while the mismatched
    # wheel above reports zero, so the field can differ between two clean-ish runs.
    assert measurement["members_hashed"] == 1


def test_wheel_record_measurement_names_its_own_structural_exemption(tmp_path):
    """`members_hashed` is total-1 on every accepted wheel, by construction.

    RECORD may not hash itself, so the hashed count alone can never distinguish
    one accepted wheel from another and carries no information.  The block has to
    name that exemption and report the remainder, which is the part that can
    actually be non-zero when something was skipped for a different reason.
    """
    import base64
    import hashlib

    digest = (
        base64.urlsafe_b64encode(hashlib.sha256(b"data").digest())
        .rstrip(b"=")
        .decode()
    )
    errors, measurement = _record_verdict(tmp_path, f"sha256={digest}")
    assert errors == []
    assert measurement == {
        "members_total": 2,
        "members_hashed": 1,
        "members_exempt_record_self_reference": 1,
        "members_neither_hashed_nor_exempt": 0,
    }
    # The identity the reader needs in order to read the hashed count at all.
    assert (
        measurement["members_hashed"]
        + measurement["members_exempt_record_self_reference"]
        + measurement["members_neither_hashed_nor_exempt"]
        == measurement["members_total"]
    )
    # NON-VACUITY: the remainder is not hardwired to zero -- the mismatched wheel
    # in the test above reports 1 while its exemption count stays 1.
    mismatched = _record_verdict(tmp_path, "sha256=not-the-hash")[1]
    assert mismatched["members_neither_hashed_nor_exempt"] == 1


def _lay_out_probe_project(project: Path) -> None:
    (project / "cisco_toolkit" / "data").mkdir(parents=True)
    (project / "webapp" / "backend").mkdir(parents=True)
    (project / "webapp" / "frontend" / "dist" / "assets").mkdir(parents=True)
    (project / "webapp" / "sample_data").mkdir(parents=True)
    for relative in (
        "COLLECT_PARSE_V3_23_0.py",
        "cisco_toolkit/__init__.py",
        "cisco_toolkit/data/oui_registry.tsv.gz",
        "cisco_toolkit/data/port_registry.tsv.gz",
        "cisco_toolkit/data/registry_manifest.json",
        "cisco_toolkit/blast_radius_explorer.html",
        "webapp/__init__.py",
        "webapp/backend/app.py",
        "webapp/frontend/dist/index.html",
        "webapp/frontend/dist/assets/app.js",
        "webapp/sample_data/sample_fleet.snapshot.json",
        *sorted(_SDIST_SOURCE_FILES),
        # The retained official sources ship in the SDIST and appear in no
        # runtime inventory -- the surface the coverage set used to miss.
        *sorted(_OFFICIAL_SOURCE_FILES),
    ):
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")


def _build_probe_archives(project: Path, *, leak: bool = True) -> Path:
    """Build a wheel and an sdist over whatever is on disk in the probe project.

    ``leak`` keeps the deliberate ``tests/leaked.py`` stowaway that the privacy
    test needs; the source-binding tests pass ``leak=False`` so the archives
    mirror the tree and coverage is measurable without a planted extra member.
    """
    dist = project / "dist"
    dist.mkdir(exist_ok=True)
    wheel = dist / "pkg.whl"
    runtime = [
        str(path.relative_to(project)).replace("\\", "/")
        for path in project.rglob("*")
        if path.is_file()
        and "dist/pkg.whl" not in str(path)
        and "dist/pkg.tar.gz" not in str(path)
        and ".git" not in path.relative_to(project).parts
    ]
    sdist_only = _SDIST_SOURCE_FILES | _OFFICIAL_SOURCE_FILES
    wheel_names = [name for name in runtime if name not in sdist_only]
    # A generated metadata directory: shipped, and in no commit by construction.
    wheel_names += ["pkg-1.0.dist-info/METADATA"]
    if leak:
        wheel_names += ["tests/leaked.py"]
    with zipfile.ZipFile(wheel, "w") as archive:
        for name in wheel_names:
            archive.writestr(name, b"x")

    sdist = dist / "pkg.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        for name in [*runtime, "PKG-INFO", "pkg.egg-info/SOURCES.txt"]:
            data = b"x"
            info = tarfile.TarInfo(f"pkg/{name}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return dist


def _probe_archive_members(dist: Path) -> tuple[set[str], set[str]]:
    """Read the member names back OUT of the archives the fixture really wrote.

    Nothing here restates what the builder intended: the wheel names come from
    the zip directory and the sdist names from `_normalise_sdist`, the same
    producer `verify_archives` uses, so a test cannot agree with a builder bug.
    """
    with zipfile.ZipFile(next(dist.glob("*.whl"))) as archive:
        wheel_names = {
            info.filename for info in archive.infolist() if not info.is_dir()
        }
    with tarfile.open(next(dist.glob("*.tar.gz")), "r:gz") as archive:
        sdist_names, errors = _normalise_sdist(list(archive.getmembers()))
    assert errors == [], errors
    return wheel_names, sdist_names


def _probe_binding(project: Path, dist: Path, commit: str, tree: str):
    """Run the real source-binding producer over the real archive member sets."""
    return _source_binding(
        project,
        commit,
        tree,
        _expected_runtime_inventory(project),
        _probe_archive_members(dist),
    )


def _producer_proof(project: Path, dist: Path, commit: str, tree: str) -> dict:
    """Assemble the proof shape `verify_archives` emits, from producer output.

    Every value below is returned by the module's own producers.  The predecessor
    of this helper was a hand-written dict, and it pinned a caveat count that the
    real producer can never emit -- the runtime inventory always globs at least
    one member off disk, so `self_derived_from_worktree_glob` is never 0 in
    practice and the hand-built 0 made the pin vacuous.
    """
    binding, errors, inventory_proof, shipped_proof = _probe_binding(
        project, dist, commit, tree
    )
    assert errors == [], errors
    expected_sdist_sources = (
        set(_expected_runtime_inventory(project))
        | _SDIST_SOURCE_FILES
        | _OFFICIAL_SOURCE_FILES
    )
    return {
        "source_binding": binding,
        "measurements": {
            "shipped_bytes_coverage": shipped_proof,
            "runtime_inventory": inventory_proof,
            "sdist_source_inventory": _sdist_source_inventory_proof(
                expected_sdist_sources, inventory_proof
            ),
        },
    }


def _bound_probe(tmp_path: Path) -> tuple[Path, Path, str, str]:
    """A committed probe project whose archives ship exactly what it tracks."""
    project = tmp_path / "project"
    _lay_out_probe_project(project)
    commit, tree = _init_probe_repo(project)
    dist = _build_probe_archives(project, leak=False)
    return project, dist, commit, tree


def test_archive_verifier_rejects_privacy_leak_before_install(tmp_path, monkeypatch):
    project = tmp_path / "project"
    _lay_out_probe_project(project)
    dist = _build_probe_archives(project)

    with pytest.raises(ValueError, match="tests/leaked.py"):
        verify_archives(
            dist,
            project,
            source_commit=SOURCE_COMMIT,
            source_tree=SOURCE_TREE,
        )


# --------------------------------------------------------------------------
# The proof must not assert a source binding it never performed.
# --------------------------------------------------------------------------


def _probe_git_env(project: Path) -> dict:
    env = dict(os.environ)
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(project / "absent-gitconfig"),
            "GIT_AUTHOR_NAME": "probe",
            "GIT_AUTHOR_EMAIL": "probe@example.invalid",
            "GIT_COMMITTER_NAME": "probe",
            "GIT_COMMITTER_EMAIL": "probe@example.invalid",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return env


def _run_probe_git(git: str, project: Path, env: dict, *arguments: str) -> str:
    """Run one Git command against the throwaway probe repository.

    A non-zero exit is a broken fixture and is raised, never skipped.  Skipping
    on any failure turned every one of these tests into a silent no-op the
    moment anything about the environment shifted, and a suite that stops
    running its own regression tests says nothing at all.
    """
    completed = subprocess.run(
        [git, "-C", str(project), *arguments],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "probe repository could not be prepared: git "
            f"{' '.join(arguments)} exited {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout


def _init_probe_repo(project: Path) -> tuple[str, str]:
    """Commit the probe project into its own throwaway repository.

    Only ever addressed with `git -C <tmp_path>`; nothing here can reach the
    checkout the tests are running from.  System and global config are disabled
    so a developer's hooksPath or identity cannot change the outcome.

    The only tolerated absence is Git itself; anything else fails loudly.
    """
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not available on PATH")
    env = _probe_git_env(project)

    def run(*arguments: str) -> str:
        return _run_probe_git(git, project, env, *arguments)

    run("init", "-q")
    run("config", "core.hooksPath", str(project / "absent-hooks"))
    run("add", "-A")
    run("commit", "-q", "-m", "probe")
    return (
        run("rev-parse", "HEAD^{commit}").strip(),
        run("rev-parse", "HEAD^{tree}").strip(),
    )


def _binding_errors(dist: Path, project: Path, commit: str, tree: str) -> list[str]:
    with pytest.raises(ValueError) as raised:
        verify_archives(
            dist,
            project,
            source_commit=commit,
            source_tree=tree,
        )
    return json.loads(str(raised.value))["source_binding_errors"]


def test_verify_archives_refuses_a_fabricated_source_commit_claim(tmp_path):
    """Pre-fix, --source-commit was only regex-checked and stamped verbatim.

    `_validated_git_oid` accepts any 40 lowercase hex characters and the module
    made no Git call at all, so a proof could carry a commit the archives were
    never compared against.
    """
    project = tmp_path / "project"
    _lay_out_probe_project(project)
    real_commit, real_tree = _init_probe_repo(project)
    dist = _build_probe_archives(project)

    fabricated = _binding_errors(dist, project, SOURCE_COMMIT, SOURCE_TREE)
    assert any("claimed source commit is not" in error for error in fabricated)
    assert any("claimed source tree is not" in error for error in fabricated)
    assert any(real_commit in error for error in fabricated)

    # NON-VACUITY: the truthful claim over the identical tree produces NO
    # binding error, so the guard is reacting to the claim and not to the
    # fixture's mere existence.  The run still fails on `tests/leaked.py`.
    assert _binding_errors(dist, project, real_commit, real_tree) == []


def test_verify_archives_refuses_a_commit_claim_over_a_dirty_worktree(tmp_path):
    """A clean HEAD match is not enough: the compared bytes are the WORK TREE."""
    project = tmp_path / "project"
    _lay_out_probe_project(project)
    real_commit, real_tree = _init_probe_repo(project)
    dist = _build_probe_archives(project)
    assert _binding_errors(dist, project, real_commit, real_tree) == []

    (project / "cisco_toolkit" / "__init__.py").write_bytes(b"tampered")
    dirty = _binding_errors(dist, project, real_commit, real_tree)
    assert any(
        "tracked working-tree files differ from the claimed commit" in error
        for error in dirty
    )
    assert any("cisco_toolkit/__init__.py" in error for error in dirty)


def _probe_inventory(project: Path) -> dict:
    return _expected_runtime_inventory(project)


def test_source_binding_degrades_honestly_without_a_repository(tmp_path):
    """Run against a downloaded archive there is no repository to resolve.

    The honest answer is a labelled non-measurement, not a pass: the method says
    the value is a caller label and the headline verdict is false.
    """
    binding, errors, inventory_proof, shipped_proof = _source_binding(
        tmp_path,
        SOURCE_COMMIT,
        SOURCE_TREE,
        {"cisco_toolkit/__init__.py": _PROVENANCE_WORKTREE},
        ({"cisco_toolkit/__init__.py"}, {"cisco_toolkit/__init__.py"}),
    )
    assert errors == []
    assert inventory_proof["source_binding_coverage_measured"] is False
    assert shipped_proof["source_binding_coverage_measured"] is False
    assert shipped_proof["members_outside_source_binding"] is None
    assert binding["method"] == _SOURCE_BINDING_UNVERIFIED
    assert binding["self_verified_against_this_worktree"] is False
    assert "unverified caller-supplied labels" in binding["unverified_reason"]
    assert binding["claimed_commit"] == SOURCE_COMMIT
    assert binding["observed_head_commit"] == ""
    # Nothing was resolved, so nothing is claimed to have been established.
    assert binding["establishes"] == []
    assert any(
        "anything whatever about the claimed commit" in statement
        for statement in binding["does_not_establish"]
    )
    # ... and the "checked against its own source" disclosure belongs to the Git
    # path only, so it must NOT appear here.
    assert not any(
        "own source" in statement for statement in binding["does_not_establish"]
    )


def test_source_binding_reports_the_verified_method_when_git_resolves(tmp_path):
    project, dist, real_commit, real_tree = _bound_probe(tmp_path)

    binding, errors, inventory_proof, shipped_proof = _probe_binding(
        project, dist, real_commit, real_tree
    )
    assert errors == []
    assert binding["method"] == _SOURCE_BINDING_GIT
    assert binding["self_verified_against_this_worktree"] is True
    assert binding["claim_matches_local_head"] is True
    assert binding["worktree_tracked_files_match_claimed_commit"] is True
    assert binding["observed_head_commit"] == real_commit
    assert inventory_proof["fully_bound_to_source_binding"] is True
    assert inventory_proof["members_outside_source_binding"] == 0
    assert shipped_proof["fully_bound_to_source_binding"] is True


# --------------------------------------------------------------------------
# The headline verdict must cover the bytes that ship, not only the tracked ones.
# --------------------------------------------------------------------------


def test_source_binding_is_unverified_when_a_shipped_member_is_untracked(tmp_path):
    """A true headline on a run shipping files bound to no commit is the lie.

    `git status --untracked-files=no` cannot see an untracked file, and the
    expected runtime inventory globs `webapp/frontend/dist/assets/*` off disk, so
    the members least covered by review were exactly the ones the binding could
    not see -- while the field a release reader scans still read verified.
    """
    project, dist, real_commit, real_tree = _bound_probe(tmp_path)

    bound, errors, bound_proof, bound_shipped = _probe_binding(
        project, dist, real_commit, real_tree
    )
    assert errors == []
    assert bound["self_verified_against_this_worktree"] is True

    # A freshly built SPA chunk: shipped, expected, tracked by nothing.
    (project / "webapp" / "frontend" / "dist" / "assets" / "chunk.js").write_bytes(
        b"// built after the commit"
    )
    shutil.rmtree(dist)
    dist = _build_probe_archives(project, leak=False)
    binding, errors, inventory_proof, shipped_proof = _probe_binding(
        project, dist, real_commit, real_tree
    )
    # The claim still matches HEAD and the tracked tree is still clean...
    assert errors == []
    assert binding["claim_matches_local_head"] is True
    assert binding["worktree_tracked_files_match_claimed_commit"] is True
    # ... and the headline verdict is nonetheless false, naming the uncovered set.
    assert binding["self_verified_against_this_worktree"] is False
    assert binding["shipped_archive_members_all_covered_by_claimed_commit"] is False
    assert binding["runtime_inventory_all_covered_by_claimed_commit"] is False
    assert "outside the claimed commit" in binding["unverified_reason"]
    assert inventory_proof["members_outside_source_binding"] == 1
    assert (
        "webapp/frontend/dist/assets"
        in inventory_proof["prefixes_outside_source_binding"]
    )
    assert shipped_proof["members_outside_source_binding"] == 1
    assert (
        "webapp/frontend/dist/assets"
        in shipped_proof["prefixes_outside_source_binding"]
    )
    assert any(
        "bytes actually shipped are bound to the claimed commit" in statement
        for statement in binding["does_not_establish"]
    )
    # NON-VACUITY: the same tree with that one file committed is verified again.
    _init_probe_repo(project)
    recommitted_commit, recommitted_tree = (
        _run_probe_git(
            shutil.which("git"),
            project,
            _probe_git_env(project),
            "rev-parse",
            "HEAD^{commit}",
        ).strip(),
        _run_probe_git(
            shutil.which("git"),
            project,
            _probe_git_env(project),
            "rev-parse",
            "HEAD^{tree}",
        ).strip(),
    )
    recovered, _, recovered_proof, recovered_shipped = _probe_binding(
        project, dist, recommitted_commit, recommitted_tree
    )
    assert recovered["self_verified_against_this_worktree"] is True
    assert recovered_proof["members_outside_source_binding"] == 0
    assert recovered_shipped["members_outside_source_binding"] == 0


def test_shipped_coverage_counts_the_sdist_bytes_the_inventory_never_named(
    tmp_path,
):
    """The runtime inventory is the WHEEL's members; the sdist ships more.

    Pre-fix the coverage set came from `_expected_runtime_inventory`, so the
    packaging files and the retained official sources under `reference-data/`
    were outside the denominator entirely.  Measured on this probe before the
    change: the headline read TRUE while 13 of 29 distinct shipped members were
    in no commit and NOT ONE of them was in the coverage set.
    """
    project, dist, real_commit, real_tree = _bound_probe(tmp_path)
    # Make the retained official sources untracked, exactly as they are in the
    # real checkout: shipped in the sdist, named by no runtime inventory.
    _run_probe_git(
        shutil.which("git"),
        project,
        _probe_git_env(project),
        "rm",
        "-q",
        "--cached",
        *sorted(_OFFICIAL_SOURCE_FILES),
    )
    _run_probe_git(
        shutil.which("git"),
        project,
        _probe_git_env(project),
        "commit",
        "-q",
        "-m",
        "untrack the retained sources",
    )
    commit = _run_probe_git(
        shutil.which("git"), project, _probe_git_env(project),
        "rev-parse", "HEAD^{commit}",
    ).strip()
    tree = _run_probe_git(
        shutil.which("git"), project, _probe_git_env(project),
        "rev-parse", "HEAD^{tree}",
    ).strip()

    binding, errors, inventory_proof, shipped_proof = _probe_binding(
        project, dist, commit, tree
    )
    assert errors == []
    # The old coverage set still reports a clean sheet -- it never saw them.
    assert inventory_proof["members_outside_source_binding"] == 0
    assert inventory_proof["fully_bound_to_source_binding"] is True
    # The shipped-bytes coverage does see them, and the headline follows it.
    assert shipped_proof["members_outside_source_binding"] == len(
        _OFFICIAL_SOURCE_FILES
    )
    assert "reference-data/official-sources" in (
        shipped_proof["prefixes_outside_source_binding"]
    )
    assert binding["self_verified_against_this_worktree"] is False
    assert binding["runtime_inventory_all_covered_by_claimed_commit"] is True
    assert binding["shipped_archive_members_all_covered_by_claimed_commit"] is False
    assert "shipped archive member(s) are outside" in binding["unverified_reason"]

    # NON-VACUITY: with the very same archives tracked again, the headline is
    # true and the uncovered set is empty, so the field measures the binding and
    # not merely the presence of an sdist.
    _init_probe_repo(project)
    clean_commit = _run_probe_git(
        shutil.which("git"), project, _probe_git_env(project),
        "rev-parse", "HEAD^{commit}",
    ).strip()
    clean_tree = _run_probe_git(
        shutil.which("git"), project, _probe_git_env(project),
        "rev-parse", "HEAD^{tree}",
    ).strip()
    clean, _, _, clean_shipped = _probe_binding(
        project, dist, clean_commit, clean_tree
    )
    assert clean["self_verified_against_this_worktree"] is True
    assert clean_shipped["members_outside_source_binding"] == 0
    assert clean_shipped["prefixes_outside_source_binding"] == []


def test_shipped_coverage_denominator_accounts_for_every_shipped_member(
    tmp_path,
):
    """Nothing may leave the denominator silently -- that is how it becomes a lie.

    Build-generated members (`*.dist-info/**`, `*.egg-info/**`, `PKG-INFO`,
    `setup.cfg`) belong to no commit and cannot be bound, so they are counted and
    disclosed by prefix INSIDE the total rather than dropped from it.
    """
    project, dist, commit, tree = _bound_probe(tmp_path)
    wheel_names, sdist_names = _probe_archive_members(dist)
    _, _, _, shipped_proof = _probe_binding(project, dist, commit, tree)

    assert shipped_proof["members_shipped_distinct"] == len(
        wheel_names | sdist_names
    )
    assert (
        shipped_proof["members_bound_to_source_binding"]
        + shipped_proof["members_outside_source_binding"]
        + shipped_proof["members_build_generated_unbindable"]
        == shipped_proof["members_shipped_distinct"]
    )
    # The probe really does ship generated members, so the term is not dead.
    assert shipped_proof["members_build_generated_unbindable"] == 3
    assert "pkg-1.0.dist-info" in (
        shipped_proof["prefixes_build_generated_unbindable"]
    )
    assert "pkg.egg-info" in shipped_proof["prefixes_build_generated_unbindable"]

    # The classifier is structural, not a list of this project's paths.
    assert _is_build_generated("anything-9.9.dist-info/RECORD") is True
    assert _is_build_generated("whatever.egg-info/PKG-INFO") is True
    assert _is_build_generated("PKG-INFO") is True
    assert _is_build_generated("setup.cfg") is True
    # NON-VACUITY: ordinary shipped source is NOT excused as build output, and
    # neither is a same-named file nested below the archive root.
    assert _is_build_generated("cisco_toolkit/parse.py") is False
    assert _is_build_generated("webapp/frontend/dist/index.html") is False
    assert _is_build_generated("cisco_toolkit/data/PKG-INFO") is False


def test_shipped_coverage_fails_closed_on_an_empty_shipped_set():
    """An unreadable archive leaves no members; that is a failure, not a pass."""
    empty = _shipped_coverage_proof(set(), set(), {"cisco_toolkit/parse.py"})
    assert empty["members_shipped_distinct"] == 0
    assert empty["members_outside_source_binding"] == 0
    # Zero outside because there is nothing at all: it must NOT read as bound.
    assert empty["fully_bound_to_source_binding"] is False
    # NON-VACUITY: one tracked member in the same call is bound.
    populated = _shipped_coverage_proof(
        {"cisco_toolkit/parse.py"}, set(), {"cisco_toolkit/parse.py"}
    )
    assert populated["fully_bound_to_source_binding"] is True


def test_empty_population_reason_is_not_a_zero_outside_sentence(tmp_path):
    """`verified: false` beside "0 member(s) are outside" read like a pass.

    The verdict was right and the sentence was nonsense.  An empty population
    now gets a sentence that says the population was empty.
    """
    project, dist, commit, tree = _bound_probe(tmp_path)
    binding, _, _, _ = _source_binding(project, commit, tree, {}, (set(), set()))
    assert binding["self_verified_against_this_worktree"] is False
    reason = binding["unverified_reason"]
    assert "0 shipped" not in reason
    assert "0 expected" not in reason
    assert "no archive member was classified" in reason
    assert "the expected runtime inventory is empty" in reason
    # NON-VACUITY: a populated, uncovered run still gets the counted sentence.
    counted, _, _, _ = _source_binding(
        project,
        commit,
        tree,
        {"webapp/frontend/dist/nowhere.js": _PROVENANCE_WORKTREE},
        ({"webapp/frontend/dist/nowhere.js"}, set()),
    )
    assert "1 shipped archive member(s) are outside" in (
        counted["unverified_reason"]
    )


def test_source_binding_fails_closed_when_coverage_cannot_be_measured(
    tmp_path,
    monkeypatch,
):
    """An unreadable input must leave the verdict false, not assume it was clean."""
    project, dist, real_commit, real_tree = _bound_probe(tmp_path)
    members = _probe_archive_members(dist)
    real_git_output = distribution_verify._git_output

    def blind_ls_files(root, *arguments):
        if arguments[:1] == ("ls-files",) and "--others" not in arguments:
            return None
        return real_git_output(root, *arguments)

    monkeypatch.setattr(distribution_verify, "_git_output", blind_ls_files)
    binding, errors, inventory_proof, shipped_proof = _source_binding(
        project, real_commit, real_tree, _probe_inventory(project), members
    )
    assert errors == []
    assert binding["claim_matches_local_head"] is True
    assert inventory_proof["source_binding_coverage_measured"] is False
    assert inventory_proof["members_outside_source_binding"] is None
    assert inventory_proof["fully_bound_to_source_binding"] is False
    assert shipped_proof["source_binding_coverage_measured"] is False
    assert shipped_proof["members_outside_source_binding"] is None
    assert shipped_proof["members_bound_to_source_binding"] is None
    assert shipped_proof["fully_bound_to_source_binding"] is False
    assert binding["self_verified_against_this_worktree"] is False
    assert "could not be measured" in binding["unverified_reason"]


def test_source_binding_states_the_head_comparison_is_not_independent(tmp_path):
    """Comparing --source-commit to HEAD of the same tree proves nothing alone.

    Every caller (`.github/workflows/*`, `RELEASING.md`) computes the claim with
    `git rev-parse` in the very tree being verified, so the check confirms the
    caller quoted itself.  The proof has to say so rather than let `verified`
    imply an external binding.
    """
    project, dist, real_commit, real_tree = _bound_probe(tmp_path)

    binding, _, _, _ = _probe_binding(project, dist, real_commit, real_tree)
    assert binding["self_verified_against_this_worktree"] is True
    tautology = [
        statement
        for statement in binding["does_not_establish"]
        if "own source" in statement
    ]
    assert tautology, binding["does_not_establish"]
    assert "git rev-parse HEAD" in tautology[0]
    # What it DOES establish is stated in the same currency and stops short of
    # claiming the commit came from anywhere else.
    assert any(
        "HEAD of the local repository" in statement
        for statement in binding["establishes"]
    )
    assert not any(
        "reviewed" in statement for statement in binding["establishes"]
    )


def test_binding_names_itself_a_self_check_even_on_its_best_run(tmp_path):
    """The strongest verdict reachable here is still self-verification.

    Every value the module can read comes from the checkout under test, so no
    field can be evidence about an outside authority.  The field NAME, a constant
    disclosure field, the scope statements, the stdout caveats and the module
    docstring all have to say so, because a reader who scans only the verdict
    must not come away believing otherwise.
    """
    project, dist, commit, tree = _bound_probe(tmp_path)
    binding, _, _, _ = _probe_binding(project, dist, commit, tree)

    # The best case this module can produce -- and it still is not independent.
    assert binding["self_verified_against_this_worktree"] is True
    assert "verified" not in binding, (
        "a bare `verified` field is back; the headline must name its own scope"
    )
    assert binding["independent_of_the_verified_worktree"] is False
    # Pinned to the module's own constant, not to a substring of it. A substring assertion passes
    # while the sentence around it is rewritten into something weaker -- and this sentence is the
    # ONLY thing standing between a reader and believing the binding is independent when it is not.
    assert binding["independence_limit"] == _INDEPENDENCE_LIMIT
    assert "SELF-check" in _INDEPENDENCE_LIMIT, (
        "the independence caveat no longer says the check is a SELF-check"
    )
    assert any(
        "INDEPENDENT of the checkout being verified" in statement
        for statement in binding["does_not_establish"]
    )
    assert not any(
        "independent" in statement.lower()
        for statement in binding["establishes"]
    )
    caveats = _proof_caveats(_producer_proof(project, dist, commit, tree))
    assert any("SELF-verification only" in caveat for caveat in caveats)
    doc = distribution_verify.__doc__
    assert "self_verified_against_this_worktree" in doc
    assert "SELF-check" in doc


def test_untracked_disclosure_is_scoped_to_shipped_paths_not_build_churn(
    tmp_path,
):
    """The disclosure must not move when a build or a test run leaves droppings.

    `--expected-json` compares the WHOLE proof dict, and the scan used to keep
    every untracked entry under a shipped top-level directory.  Measured on this
    probe before the change: creating `cisco_toolkit/__pycache__`, `build/lib`
    and `webapp/tests/__pycache__` moved the emitted fields from 0 entries to 2
    and added two prefixes, so an ordinary local build made a re-verification
    fail for reasons that have nothing to do with the archives.
    """
    project, dist, real_commit, real_tree = _bound_probe(tmp_path)

    clean, _, _, _ = _probe_binding(project, dist, real_commit, real_tree)
    # NON-VACUITY: a fully committed tree discloses an EMPTY uncovered set, so a
    # populated one below is a measurement and not a constant.
    assert clean["untracked_scan_measured"] is True
    assert clean["untracked_entries_covering_shipped_members"] == 0
    assert clean["untracked_prefixes_covering_shipped_members"] == []
    untracked_fields = lambda block: {  # noqa: E731
        key: value for key, value in block.items() if key.startswith("untracked_")
    }

    # NON-VACUITY first: an untracked path that really does hold a SHIPPED member
    # is disclosed, so the scoping below did not delete the disclosure.
    (project / "webapp" / "frontend" / "dist" / "assets" / "chunk.js").write_bytes(
        b"// built after the commit"
    )
    shutil.rmtree(dist)
    dist = _build_probe_archives(project, leak=False)
    binding, _, _, _ = _probe_binding(project, dist, real_commit, real_tree)
    assert binding["untracked_scan_measured"] is True
    assert binding["untracked_entries_covering_shipped_members"] == 1
    assert binding["untracked_prefixes_covering_shipped_members"] == [
        "webapp/frontend/dist/assets"
    ]
    assert any(
        "untracked paths holding shipped archive members" in statement
        for statement in binding["does_not_establish"]
    )
    baseline = untracked_fields(binding)

    # Now the CI shape: the SAME archives are re-verified after a build or a test
    # run has left droppings in the tree.  Bytecode caches, a build tree, node
    # modules and test scratch are never shipped members and never hold one, so
    # not one emitted field may move.
    for churn in (
        "cisco_toolkit/__pycache__/parse.cpython-312.pyc",
        "cisco_toolkit/data/__pycache__/x.pyc",
        "build/lib/cisco_toolkit/__init__.py",
        "webapp/tests/__pycache__/y.pyc",
        "webapp/frontend/node_modules/left-pad/index.js",
        "webapp/frontend/test-results/report.json",
    ):
        path = project / churn
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"churn")
    churned, _, _, _ = _probe_binding(project, dist, real_commit, real_tree)
    assert untracked_fields(churned) == baseline


def test_untracked_disclosure_is_not_measured_rather_than_empty(
    tmp_path,
    monkeypatch,
):
    project, dist, real_commit, real_tree = _bound_probe(tmp_path)
    members = _probe_archive_members(dist)
    real_git_output = distribution_verify._git_output

    def blind_others(root, *arguments):
        if "--others" in arguments:
            return None
        return real_git_output(root, *arguments)

    monkeypatch.setattr(distribution_verify, "_git_output", blind_others)
    binding, _, _, _ = _source_binding(
        project, real_commit, real_tree, _probe_inventory(project), members
    )
    assert binding["untracked_scan_measured"] is False
    # null, never 0: "we could not look" must not read as "there is nothing".
    assert binding["untracked_entries_covering_shipped_members"] is None
    assert binding["untracked_prefixes_covering_shipped_members"] is None
    assert binding["self_verified_against_this_worktree"] is False
    assert any(
        "NOT MEASURED, not empty" in statement
        for statement in binding["does_not_establish"]
    )


def test_probe_git_helper_fails_loudly_instead_of_skipping(tmp_path):
    """A broken fixture must not silence its own regression tests.

    `_init_probe_repo` skipped on ANY non-zero git exit, so a transient failure
    turned every source-binding test into a silent no-op and nothing said so.
    """
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not available on PATH")
    project = tmp_path / "project"
    project.mkdir()
    try:
        _run_probe_git(git, project, _probe_git_env(project), "no-such-subcommand")
    except AssertionError as exc:
        assert "no-such-subcommand" in str(exc)
    except BaseException as exc:  # pytest.skip raises a BaseException
        pytest.fail(
            "a failing git command must be raised, not swallowed: "
            f"{type(exc).__name__}: {exc}"
        )
    else:
        pytest.fail("a failing git command must raise")


def _no_repository_proof(tmp_path: Path) -> dict:
    """A producer-emitted proof for the ordinary downloaded-archive run.

    No repository is created at all -- the shape a reader gets when the module
    runs against an archive pair downloaded from PyPI.
    """
    project = tmp_path / "no-repository" / "project"
    _lay_out_probe_project(project)
    dist = _build_probe_archives(project, leak=False)
    return _producer_proof(project, dist, SOURCE_COMMIT, SOURCE_TREE)


def test_proof_caveats_state_an_unverified_binding_on_stdout(tmp_path):
    unverified = _no_repository_proof(tmp_path)
    caveats = _proof_caveats(unverified)
    assert any("source binding was NOT established" in caveat for caveat in caveats)
    assert any("advisory" in caveat for caveat in caveats)
    assert any(
        "shipped archive member set could not be compared" in caveat
        and "NOT MEASURED, not zero" in caveat
        for caveat in caveats
    )
    assert any(
        "expected runtime inventory could not be compared" in caveat
        and "NOT MEASURED, not zero" in caveat
        for caveat in caveats
    )
    assert any("NOT MEASURED, not empty" in caveat for caveat in caveats)

    # NON-VACUITY: a fully bound, fully tracked producer proof raises none of
    # these, so they cannot be always-on boilerplate.
    project, dist, commit, tree = _bound_probe(tmp_path / "bound")
    bound_caveats = _proof_caveats(_producer_proof(project, dist, commit, tree))
    assert not any("NOT established" in caveat for caveat in bound_caveats)
    assert not any("NOT MEASURED" in caveat for caveat in bound_caveats)
    assert not any("untracked path" in caveat for caveat in bound_caveats)
    assert not any("are outside the claimed commit" in caveat for caveat in bound_caveats)


def test_proof_caveats_always_disclose_the_tautology_on_the_git_path(tmp_path):
    """The comparison's limit is permanent, so it is stated on every Git run.

    Asserted as a PROPERTY over producer output.  The predecessor pinned
    `len(caveats) == 1` over a hand-written dict whose
    `self_derived_from_worktree_glob` was 0 -- a state the real producer can
    never reach, because the expected runtime inventory always globs at least one
    member off disk.  The count was therefore satisfiable only by the fixture.
    """
    project, dist, commit, tree = _bound_probe(tmp_path)
    proof = _producer_proof(project, dist, commit, tree)
    caveats = _proof_caveats(proof)

    tautology = [
        caveat
        for caveat in caveats
        if "same work tree the archives were built from" in caveat
    ]
    assert len(tautology) == 1, caveats
    assert "does NOT establish" in tautology[0]

    # Every remaining caveat on this best-case run is a PERMANENT disclosure or a
    # measurement the producer really reported -- nothing here is a defect
    # warning, and each one is present exactly when its measurement says so.
    self_derived = proof["measurements"]["runtime_inventory"][
        "self_derived_from_worktree_glob"
    ]
    generated = proof["measurements"]["shipped_bytes_coverage"][
        "members_build_generated_unbindable"
    ]
    assert self_derived > 0 and generated > 0, "the probe must exercise both"
    assert (
        len([c for c in caveats if "SELF-verification only" in c]) == 1
    )
    assert (
        len([c for c in caveats if "discovered by globbing this working tree" in c])
        == 1
    )
    assert (
        len([c for c in caveats if "generated by the build backend" in c]) == 1
    )
    assert len(caveats) == 4, caveats


# --------------------------------------------------------------------------
# The proof must not present a self-derived set as a verified inventory.
# --------------------------------------------------------------------------


def test_runtime_inventory_labels_globbed_members_as_self_derived(tmp_path):
    """webapp/frontend/dist/** is globbed off disk, so expected == actual.

    Anything dropped into the SPA asset directory becomes "expected" by being
    there.  The proof has to say which members are constrained by something
    other than this working tree.
    """
    project = tmp_path / "project"
    _lay_out_probe_project(project)
    (project / "webapp" / "frontend" / "dist" / "index.html").write_bytes(
        b'<script type="module" src="/assets/app.js"></script>'
    )
    (project / "webapp" / "frontend" / "dist" / "assets" / "stowaway.js").write_bytes(
        b"// nothing references this"
    )

    inventory = _expected_runtime_inventory(project)
    assert inventory["webapp/frontend/dist/index.html"] == _PROVENANCE_REQUIRED
    assert (
        inventory["webapp/frontend/dist/assets/app.js"] == _PROVENANCE_INDEX
    )
    # The stowaway is expected for one reason only: it was on disk.
    assert (
        inventory["webapp/frontend/dist/assets/stowaway.js"]
        == _PROVENANCE_WORKTREE
    )

    unmeasured = _runtime_inventory_proof(inventory, None)
    assert unmeasured["source_binding_coverage_measured"] is False
    # "not measured" is null, never 0 -- a 0 here would read as "nothing is
    # outside the commit", which is the opposite of what was established.
    assert unmeasured["members_outside_source_binding"] is None
    assert unmeasured["prefixes_outside_source_binding"] is None

    measured = _runtime_inventory_proof(
        inventory,
        {"COLLECT_PARSE_V3_23_0.py", "cisco_toolkit/__init__.py"},
    )
    assert measured["source_binding_coverage_measured"] is True
    assert measured["members_outside_source_binding"] == len(inventory) - 2
    assert (
        "webapp/frontend/dist/assets"
        in measured["prefixes_outside_source_binding"]
    )
    # NON-VACUITY: a tracked set covering everything reports zero outside.
    covered = _runtime_inventory_proof(inventory, set(inventory))
    assert covered["members_outside_source_binding"] == 0
    assert covered["prefixes_outside_source_binding"] == []
    assert covered["members_tracked_in_source_binding"] == len(inventory)


def test_sdist_expected_inventory_admits_how_much_of_it_is_self_derived(tmp_path):
    """`sdist_source_inventory_members` was a bare count of a mixed set.

    Most of the sdist's expected set is the runtime inventory, and most of THAT
    is built by globbing `cisco_toolkit/**/*.py` and the built SPA off disk -- so
    for those members "expected" and "actual" are the same measurement and their
    agreement proves nothing.  The proof now splits the count and says so.
    """
    project = tmp_path / "project"
    _lay_out_probe_project(project)
    inventory = _expected_runtime_inventory(project)
    inventory_proof = _runtime_inventory_proof(inventory, set(inventory))
    expected_sdist_sources = (
        set(inventory) | _SDIST_SOURCE_FILES | _OFFICIAL_SOURCE_FILES
    )
    proof = _sdist_source_inventory_proof(expected_sdist_sources, inventory_proof)

    assert proof["members_expected"] == len(expected_sdist_sources)
    # Nothing leaves this denominator either.
    assert (
        proof["self_derived_from_worktree_glob"]
        + proof["externally_named_by_this_verifier"]
        == proof["members_expected"]
    )
    assert proof["self_derived_from_worktree_glob"] > 0
    assert "found them on disk" in proof["self_derivation_note"]
    # NON-VACUITY: an inventory with nothing globbed reports nothing self-derived,
    # so the field is a measurement and not a constant.
    required_only = _runtime_inventory_proof(
        {"COLLECT_PARSE_V3_23_0.py": _PROVENANCE_REQUIRED},
        {"COLLECT_PARSE_V3_23_0.py"},
    )
    assert _sdist_source_inventory_proof(
        {"COLLECT_PARSE_V3_23_0.py"}, required_only
    )["self_derived_from_worktree_glob"] == 0


def test_runtime_inventory_counts_the_spa_bundle_of_this_repository():
    """The live tree really does ship runtime members outside its own commit."""
    inventory = _expected_runtime_inventory(ROOT)
    assert inventory["webapp/frontend/dist/index.html"] == _PROVENANCE_REQUIRED
    globbed = [
        name
        for name, provenance in inventory.items()
        if provenance == _PROVENANCE_WORKTREE
    ]
    assert globbed, "the inventory must not claim every member is externally required"
    proof = _runtime_inventory_proof(inventory, None)
    assert proof["members_expected"] == len(inventory)
    assert (
        proof["required_by_verifier"]
        + proof["required_by_frontend_index"]
        + proof["self_derived_from_worktree_glob"]
        == len(inventory)
    )


# --------------------------------------------------------------------------
# The proof fields must carry the measurement, not a literal True.
# --------------------------------------------------------------------------


def test_sdist_metadata_equivalence_counts_documents_actually_cross_checked(
    tmp_path,
):
    """`metadata_equivalence_verified: true` held even with no wheel signature.

    When the wheel METADATA check fails, `wheel_signature` is empty and the sdist
    PKG-INFO documents are compared against nothing -- yet the emitted proof said
    the equivalence was verified.
    """
    contract = _project_metadata_contract(ROOT)
    lines = ["Metadata-Version: 2.4"]
    for header, values in contract["headers"].items():
        lines.extend(f"{header}: {value}" for value in values)
    payload = (
        "\n".join(lines) + "\n\n" + contract["description"]
    ).encode("utf-8")
    signature, errors = _metadata_signature(payload, contract, label="probe")
    assert errors == []

    egg_info = "cisco_migration_assessment_toolkit.egg-info"
    archive_path = tmp_path / "probe.tar.gz"
    names = ("PKG-INFO", f"{egg_info}/PKG-INFO")
    with tarfile.open(archive_path, "w:gz") as archive:
        for name in names:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))

    def measure(wheel_signature: dict) -> dict:
        with tarfile.open(archive_path, "r:gz") as archive:
            members = {member.name: member for member in archive.getmembers()}
            _, measurement = _verify_sdist_metadata(
                archive,
                members,
                set(members),
                contract,
                wheel_signature,
            )
        return measurement

    without_wheel = measure({})
    assert without_wheel["pkg_info_documents_parsed"] == 2
    assert without_wheel["cross_checked_against_wheel_metadata"] == 0

    # NON-VACUITY: with a wheel signature present the same archive reports two
    # cross-checks, so the 0 above is the absent comparison, not a dead counter.
    with_wheel = measure(signature)
    assert with_wheel["pkg_info_documents_parsed"] == 2
    assert with_wheel["cross_checked_against_wheel_metadata"] == 2


def _main_over_binding(monkeypatch, capsys, tmp_path, verified: bool, *extra: str):
    """Drive `main` over a producer proof so only the exit rule is under test.

    The proof body comes from the real producers; only the one field the exit
    rule reads is toggled, so the test cannot pass over a shape the module never
    emits.
    """
    project, dist, commit, tree = _bound_probe(tmp_path / f"probe-{verified}")
    result = json.loads(json.dumps(_producer_proof(project, dist, commit, tree)))
    assert result["source_binding"]["self_verified_against_this_worktree"] is True
    result["source_binding"]["self_verified_against_this_worktree"] = verified
    if not verified:
        result["source_binding"]["unverified_reason"] = (
            "1 shipped archive member(s) are outside the claimed commit"
        )
    monkeypatch.setattr(
        distribution_verify,
        "verify_archives",
        lambda *arguments, **keywords: result,
    )
    code = distribution_verify.main(
        [
            "dist",
            "--source-commit",
            SOURCE_COMMIT,
            "--source-tree",
            SOURCE_TREE,
            *extra,
        ]
    )
    return code, capsys.readouterr().out


def test_unverified_binding_is_advisory_and_says_so_by_default(
    monkeypatch,
    capsys,
    tmp_path,
):
    """A warning nothing acts on must at least admit that it is not a control.

    The disclosure had no enforcing consumer at all: `main` returned 0 either
    way and no workflow read the field, so a reader could take the WARNING for a
    gate.  The exit rule is now stated on stdout, in the proof block, and in the
    module docstring.
    """
    code, out = _main_over_binding(monkeypatch, capsys, tmp_path, False)
    assert code == 0
    assert "the source binding was NOT established" in out
    assert "ADVISORY and did not affect this exit code" in out
    assert "--require-source-binding" in out
    # The proof itself carries the enforcement status, not just this stdout line.
    assert '"exit_code_enforcement"' in out
    assert _BINDING_ENFORCEMENT in out


def test_require_source_binding_turns_the_disclosure_into_an_exit_code(
    monkeypatch,
    capsys,
    tmp_path,
):
    code, out = _main_over_binding(
        monkeypatch, capsys, tmp_path, False, "--require-source-binding"
    )
    assert code == _EXIT_UNVERIFIED_BINDING
    assert _EXIT_UNVERIFIED_BINDING != 0
    assert "source binding not established" in out

    # NON-VACUITY: the same flag over an established binding exits 0, so the code
    # reports the binding and not merely the presence of the flag.
    ok_code, ok_out = _main_over_binding(
        monkeypatch, capsys, tmp_path, True, "--require-source-binding"
    )
    assert ok_code == 0
    assert "source binding not established" not in ok_out


def test_module_docstring_states_the_advisory_exit_rule():
    """The rule has to be findable where a reader looks first."""
    doc = distribution_verify.__doc__
    assert "--require-source-binding" in doc
    assert "advisory" in doc.lower()
    assert "tautology" in doc.lower()
    # ... and the coverage basis the headline is settled against, so a reader
    # cannot take it for the runtime inventory it used to be derived from.
    assert "member set of the two archives that actually ship" in doc
    assert "members_build_generated_unbindable" in doc


def test_no_proof_field_is_a_hardcoded_true_verification_flag():
    """Ratchet against the six literals returning.

    Each of these keys was emitted as `True` on the success path, which made
    --expected-json vacuous for exactly the fields a release reader scans first.
    """
    source = inspect.getsource(distribution_verify.verify_archives)
    for field in (
        "record_hashes_verified",
        "metadata_equivalence_verified",
        "source_bytes_verified",
        "unexpected_members_verified",
        "archive_content_privacy_verified",
        "privacy_boundary_verified",
    ):
        assert field not in source, (
            f"{field} is back; the proof must carry the measurement, not a "
            "boolean that is true by construction"
        )
    # NON-VACUITY: the successor measurement block IS present, so this test
    # cannot pass by the proof simply having lost the disclosure.
    for replacement in (
        "record_hashes",
        "metadata_equivalence",
        "source_bytes",
        "unexpected_members",
        "archive_content_privacy",
        "privacy_boundary",
        "runtime_inventory",
        "shipped_bytes_coverage",
        "sdist_source_inventory",
    ):
        assert f'"{replacement}": ' in source


# --------------------------------------------------------------------------
# The ACCEPT path.
#
# Every other invocation of `verify_archives` in this suite sits inside
# `pytest.raises`: the function was only ever watched to REFUSE.  The path that
# emits "this archive is safe to ship" -- the one a human reads before pushing to
# PyPI -- had never been executed, so it could have stopped verifying anything
# and every suite would still have been green.
#
# Reaching it needs a complete, valid wheel + sdist PAIR over a project root that
# satisfies the whole contract: METADATA/WHEEL/RECORD with real digests, both
# PKG-INFO documents, SOURCES.txt equal to the archive inventory, the retained
# registry and EoL source chains, and a clean Git work tree whose commit the
# claim matches.  The retained-source chains are pinned to code-level SHA-256
# constants of the REAL primary sources, so the fixture's project root is a COPY
# of this repository's shipped source set rather than invented files; the
# archives themselves are synthesised in a temp directory and no distribution of
# this project is ever built or published.
# --------------------------------------------------------------------------


_KNOWN_HOSTNAME_DENYLIST = ".github/privacy/known_client_hostname_sha256.txt"


def _shipped_source_names(root: Path) -> list[str]:
    """The exact set `verify_archives` expects an sdist to carry.

    Derived from the module's own inventory helpers, never hand-listed: a
    hardcoded member set would rot the moment a module is added to the package,
    and it would agree with a bug in the very producer under test.
    """
    return sorted(
        set(_expected_runtime_inventory(root))
        | _SDIST_SOURCE_FILES
        | _OFFICIAL_SOURCE_FILES
    )


def _copy_release_tree(project: Path) -> None:
    """Copy this repository's shipped source set into a throwaway project root.

    Other sessions edit this checkout concurrently, so the inventory is re-derived
    and the copy retried if a listed source disappears mid-pass; a vanished source
    is never silently dropped, because a short copy would silently shrink the
    fixture the assertions are measured against.
    """
    last: Exception | None = None
    for _ in range(3):
        names = [*_shipped_source_names(ROOT), _KNOWN_HOSTNAME_DENYLIST]
        try:
            for name in names:
                destination = project.joinpath(*PurePosixPath(name).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(
                    ROOT.joinpath(*PurePosixPath(name).parts), destination
                )
        except FileNotFoundError as exc:  # a concurrent session moved a file
            last = exc
            continue
        return
    raise AssertionError(f"the release source tree could not be copied: {last}")


def _metadata_document(contract: dict) -> bytes:
    lines = ["Metadata-Version: 2.4"]
    for header, values in contract["headers"].items():
        lines.extend(f"{header}: {value}" for value in values)
    return ("\n".join(lines) + "\n\n" + contract["description"]).encode("utf-8")


def _entry_points_document() -> bytes:
    body = "".join(
        f"{name} = {target}\n"
        for name, target in sorted(_EXPECTED_CONSOLE_SCRIPTS.items())
    )
    return ("[console_scripts]\n" + body).encode("utf-8")


def _top_level_document() -> bytes:
    return (
        "".join(f"{name}\n" for name in sorted(_EXPECTED_TOP_LEVEL_PACKAGES))
    ).encode("utf-8")


def _requires_document(contract: dict) -> bytes:
    """Render setuptools' requires.txt from the module's own metadata contract.

    Inverting `_canonical_requirement`'s output rather than re-reading
    pyproject.toml keeps the fixture downstream of the real producer: if the
    contract changes, this follows it instead of pinning a second copy of the
    dependency list.
    """
    sections: dict[str, list[str]] = {}
    for requirement in contract["headers"].get("Requires-Dist", []):
        base, separator, raw_marker = requirement.partition(";")
        marker = raw_marker.strip() if separator else ""
        extra = ""
        match = re.fullmatch(r'(?:(?P<rest>.+?) and )?extra == "(?P<extra>[^"]+)"', marker)
        if match:
            extra = match.group("extra")
            marker = match.group("rest") or ""
        key = f"{extra}:{marker}" if marker else extra
        sections.setdefault(key, []).append(base.strip())
    text = "".join(f"{item}\n" for item in sections.pop("", []))
    for section, requirements in sorted(sections.items()):
        text += f"\n[{section}]\n" + "".join(f"{item}\n" for item in requirements)
    return text.encode("utf-8")


def _wheel_payloads(project: Path, contract: dict, dist_info: str) -> dict[str, bytes]:
    payloads = {
        name: project.joinpath(*PurePosixPath(name).parts).read_bytes()
        for name in sorted(_expected_runtime_inventory(project))
    }
    generated = {
        "METADATA": _metadata_document(contract),
        "WHEEL": (
            "Wheel-Version: 1.0\n"
            "Generator: setuptools (83.0.0)\n"
            "Root-Is-Purelib: true\n"
            "Tag: py3-none-any\n"
        ).encode("utf-8"),
        "entry_points.txt": _entry_points_document(),
        "top_level.txt": _top_level_document(),
    }
    # Built from the module's own allowlist constant, so a new required
    # dist-info member fails this fixture LOUDLY instead of being skipped.
    for relative in sorted(_WHEEL_METADATA_FILES):
        if relative == "RECORD":  # written last, over the finished member set
            continue
        assert relative in generated, (
            f"the fixture does not know how to generate {relative!r}; "
            "_WHEEL_METADATA_FILES grew and this builder must follow it"
        )
        payloads[f"{dist_info}/{relative}"] = generated[relative]
    for declared in contract["headers"].get("License-File", []):
        payloads[f"{dist_info}/licenses/{declared}"] = (
            project.joinpath(*PurePosixPath(declared).parts).read_bytes()
        )
    return payloads


def _record_document(payloads: dict[str, bytes], record_name: str) -> bytes:
    rows = []
    for name in sorted(payloads):
        digest = (
            base64.urlsafe_b64encode(hashlib.sha256(payloads[name]).digest())
            .rstrip(b"=")
            .decode()
        )
        rows.append(f"{name},sha256={digest},{len(payloads[name])}")
    rows.append(f"{record_name},,")
    return ("\n".join(rows) + "\n").encode("utf-8")


def _normalised_project(contract: dict) -> str:
    return re.sub(r"[-.]+", "_", contract["name"])


def _write_release_wheel(
    project: Path,
    dist: Path,
    contract: dict,
    *,
    mutate=None,
    record_mutate=None,
) -> Path:
    dist_info = f"{_normalised_project(contract)}-{contract['version']}.dist-info"
    payloads = _wheel_payloads(project, contract, dist_info)
    if mutate is not None:
        payloads = mutate(payloads)
    record_name = f"{dist_info}/RECORD"
    record = _record_document(payloads, record_name)
    if record_mutate is not None:
        record = record_mutate(record)
    payloads[record_name] = record
    wheel = dist / (
        f"{_normalised_project(contract)}-{contract['version']}-py3-none-any.whl"
    )
    with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(payloads):
            archive.writestr(name, payloads[name])
    return wheel


def _write_release_sdist(project: Path, dist: Path, contract: dict) -> Path:
    egg = re.sub(r"[-_.]+", "_", contract["name"]).strip("_") + ".egg-info"
    root = f"{_normalised_project(contract)}-{contract['version']}"
    payloads = {
        name: project.joinpath(*PurePosixPath(name).parts).read_bytes()
        for name in _shipped_source_names(project)
    }
    metadata = _metadata_document(contract)
    payloads["PKG-INFO"] = metadata
    payloads["setup.cfg"] = b"[egg_info]\ntag_build = \ntag_date = 0\n"
    payloads[f"{egg}/PKG-INFO"] = metadata
    payloads[f"{egg}/dependency_links.txt"] = b"\n"
    payloads[f"{egg}/entry_points.txt"] = _entry_points_document()
    payloads[f"{egg}/requires.txt"] = _requires_document(contract)
    payloads[f"{egg}/top_level.txt"] = _top_level_document()
    payloads[f"{egg}/SOURCES.txt"] = b""
    inventory = sorted(set(payloads) - {"PKG-INFO", "setup.cfg"})
    payloads[f"{egg}/SOURCES.txt"] = ("\n".join(inventory) + "\n").encode("utf-8")
    sdist = dist / f"{root}.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        for name in sorted(payloads):
            data = payloads[name]
            info = tarfile.TarInfo(f"{root}/{name}")
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
    return sdist


class _ReleaseRig:
    """A committed project root plus a builder for archive pairs over it."""

    def __init__(self, project: Path, dist_root: Path, commit: str, tree: str):
        self.project = project
        self.dist_root = dist_root
        self.commit = commit
        self.tree = tree
        self.contract = _project_metadata_contract(project)
        self._built = 0

    def build(self, *, mutate=None, record_mutate=None) -> Path:
        self._built += 1
        dist = self.dist_root / f"dist-{self._built}"
        dist.mkdir(parents=True)
        _write_release_wheel(
            self.project,
            dist,
            self.contract,
            mutate=mutate,
            record_mutate=record_mutate,
        )
        _write_release_sdist(self.project, dist, self.contract)
        return dist

    def verify(self, dist: Path) -> dict:
        return verify_archives(
            dist,
            self.project,
            source_commit=self.commit,
            source_tree=self.tree,
        )

    def refusal(self, dist: Path) -> dict:
        with pytest.raises(ValueError) as raised:
            self.verify(dist)
        return json.loads(str(raised.value))


@pytest.fixture(scope="module")
def release_rig(tmp_path_factory) -> _ReleaseRig:
    root = tmp_path_factory.mktemp("release-rig")
    project = root / "project"
    _copy_release_tree(project)
    commit, tree = _init_probe_repo(project)
    return _ReleaseRig(project, root / "archives", commit, tree)


@pytest.fixture(scope="module")
def accepted_release(release_rig) -> tuple[Path, dict]:
    dist = release_rig.build()
    return dist, release_rig.verify(dist)


def test_verify_archives_accepts_a_complete_pair_and_the_proof_measures_it(
    release_rig,
    accepted_release,
):
    """The first execution of the accept path, and what the proof then says.

    `verify_archives` returning normally IS the assertion the suite never made.
    Everything below is then checked against the fixture's own archives, read
    back out of the files on disk rather than restated from the builder, so a
    proof that stopped measuring and started asserting constants would fail here.
    """
    dist, proof = accepted_release
    wheel_names, sdist_names = _probe_archive_members(dist)

    assert set(proof) == {
        "verification_schema",
        "project",
        "version",
        "source_binding",
        "known_client_hostname_denylist_sha256",
        "wheel",
        "wheel_bytes",
        "wheel_sha256",
        "sdist",
        "sdist_bytes",
        "sdist_sha256",
        "wheel_members",
        "sdist_members",
        "source_manifest_sha256",
        "console_scripts_verified",
        "registry_source_chains",
        "eol_source_chain",
        "measurements",
    }
    assert proof["verification_schema"] == 6
    assert proof["project"] == release_rig.contract["name"]
    assert proof["version"] == release_rig.contract["version"]
    assert proof["console_scripts_verified"] == sorted(_EXPECTED_CONSOLE_SCRIPTS)

    # The archive identity fields describe the files the fixture really wrote.
    wheel_path = next(dist.glob("*.whl"))
    sdist_path = next(dist.glob("*.tar.gz"))
    assert proof["wheel"] == wheel_path.name
    assert proof["sdist"] == sdist_path.name
    assert proof["wheel_bytes"] == wheel_path.stat().st_size
    assert proof["sdist_bytes"] == sdist_path.stat().st_size
    assert proof["wheel_sha256"] == hashlib.sha256(wheel_path.read_bytes()).hexdigest()
    assert proof["sdist_sha256"] == hashlib.sha256(sdist_path.read_bytes()).hexdigest()
    assert proof["wheel_members"] == len(wheel_names)
    assert proof["sdist_members"] == len(sdist_names)

    # The retained-source chains really ran; they are not empty placeholders.
    assert sorted(proof["registry_source_chains"]) == [
        "oui_registry.tsv.gz",
        "port_registry.tsv.gz",
    ]
    assert all(
        chain["verified"] is True
        for chain in proof["registry_source_chains"].values()
    )
    assert proof["eol_source_chain"]["verified"] is True
    # ... and the freshness proof carries no live clock value, so re-verifying the
    # same archives tomorrow still compares equal under --expected-json.
    for chain in (
        *proof["registry_source_chains"].values(),
        proof["eol_source_chain"],
    ):
        assert "source_age_days" not in chain

    measurements = proof["measurements"]
    # RECORD: every member hashed except the one row RECORD may not hash, itself.
    record = measurements["record_hashes"]
    assert record["wheel_members_total"] == len(wheel_names)
    assert record["wheel_members_exempt_record_self_reference"] == 1
    assert record["wheel_members_neither_hashed_nor_exempt"] == 0
    assert record["wheel_members_hashed_against_record"] == len(wheel_names) - 1

    # Both PKG-INFO documents were parsed AND cross-checked against the wheel.
    equivalence = measurements["metadata_equivalence"]
    assert equivalence["sdist_pkg_info_documents_parsed"] == 2
    assert equivalence["sdist_pkg_info_documents_cross_checked_against_wheel"] == 2
    assert equivalence["wheel_metadata_fields_compared"] == (
        len(release_rig.contract["headers"]) + 2  # + Metadata-Version, + description
    )

    # Byte comparisons against the working tree, counted against the real sets.
    inventory = _expected_runtime_inventory(release_rig.project)
    expected_sdist_sources = _shipped_source_names(release_rig.project)
    source_bytes = measurements["source_bytes"]
    assert source_bytes["wheel_members_byte_compared_to_worktree"] == len(inventory)
    assert source_bytes["sdist_members_byte_compared_to_worktree"] == len(
        expected_sdist_sources
    )
    assert source_bytes["worktree_sources_read"] == len(expected_sdist_sources)
    assert source_bytes["wheel_license_byte_compared_to_worktree"] == len(
        release_rig.contract["headers"]["License-File"]
    )

    # Nothing left the content-privacy denominator: scanned + exempt == members.
    privacy = measurements["archive_content_privacy"]
    assert (
        privacy["wheel_members_content_scanned"]
        + privacy["wheel_members_content_scan_exempt"]
        == len(wheel_names)
    )
    assert (
        privacy["sdist_members_content_scanned"]
        + privacy["sdist_members_content_scan_exempt"]
        == len(sdist_names)
    )
    assert privacy["wheel_members_content_scanned"] > 0
    assert privacy["known_hostname_digests_applied"] > 0
    assert measurements["privacy_boundary"]["wheel_member_names_checked"] == len(
        wheel_names
    )
    assert measurements["privacy_boundary"]["sdist_member_names_checked"] == len(
        sdist_names
    )

    # Every member classified, nothing outside the allowlist.
    unexpected = measurements["unexpected_members"]
    assert unexpected["wheel_members_classified"] == len(wheel_names)
    assert unexpected["sdist_members_classified"] == len(sdist_names)
    assert unexpected["wheel_allowlist_members"] >= len(wheel_names)
    assert unexpected["sdist_allowlist_members"] >= len(sdist_names)

    # The headline verdict, on the only kind of run that can reach it.
    coverage = measurements["shipped_bytes_coverage"]
    assert coverage["members_shipped_distinct"] == len(wheel_names | sdist_names)
    assert (
        coverage["members_bound_to_source_binding"]
        + coverage["members_outside_source_binding"]
        + coverage["members_build_generated_unbindable"]
        == coverage["members_shipped_distinct"]
    )
    assert coverage["members_outside_source_binding"] == 0
    assert coverage["members_build_generated_unbindable"] > 0
    assert coverage["fully_bound_to_source_binding"] is True
    assert measurements["runtime_inventory"]["members_expected"] == len(inventory)
    assert measurements["runtime_inventory"]["fully_bound_to_source_binding"] is True

    binding = proof["source_binding"]
    assert binding["self_verified_against_this_worktree"] is True
    assert binding["method"] == _SOURCE_BINDING_GIT
    assert binding["observed_head_commit"] == release_rig.commit
    assert binding["unverified_reason"] == ""
    assert binding["untracked_entries_covering_shipped_members"] == 0
    # Even the best run this module can produce is still a SELF-check.
    assert binding["independent_of_the_verified_worktree"] is False


def test_one_corrupted_record_digest_flips_the_accepted_pair_to_a_refusal(
    release_rig,
    accepted_release,
):
    """The mutation pair that makes the accept coverage real rather than a smoke test.

    Same project root, same builder, same everything -- one RECORD digest is
    rewritten and no payload is touched, so the wheel's bytes still match the
    working tree and only the RECORD is wrong.  A verifier that had quietly
    stopped hashing would accept this and stay green.
    """
    _, accepted = accepted_release
    assert (
        accepted["measurements"]["record_hashes"][
            "wheel_members_neither_hashed_nor_exempt"
        ]
        == 0
    )
    target = "COLLECT_PARSE_V3_23_0.py"

    def corrupt(record: bytes) -> bytes:
        rows = []
        for row in record.decode("utf-8").splitlines():
            name, digest, size = row.split(",")
            if name == target:
                assert digest.startswith("sha256=")
                digest = "sha256=" + "A" * 43
            rows.append(f"{name},{digest},{size}")
        return ("\n".join(rows) + "\n").encode("utf-8")

    errors = release_rig.refusal(release_rig.build(record_mutate=corrupt))
    assert errors["wheel_record_errors"] == [
        f"wheel RECORD sha256 mismatch for {target}"
    ]
    # Only the RECORD complained: the member's bytes are still the tree's bytes.
    assert errors["wheel_source_mismatches"] == []
    assert errors["missing_wheel"] == []


def test_dropping_one_required_member_flips_the_accepted_pair_to_a_refusal(
    release_rig,
    accepted_release,
):
    """A wheel one runtime module short must not be certified as shippable."""
    target = "COLLECT_PARSE_V3_23_0.py"
    assert (
        _expected_runtime_inventory(release_rig.project)[target]
        == _PROVENANCE_REQUIRED
    )

    def drop(payloads: dict) -> dict:
        assert target in payloads
        del payloads[target]
        return payloads

    errors = release_rig.refusal(release_rig.build(mutate=drop))
    assert errors["missing_wheel"] == [target]


def test_a_client_marker_planted_in_an_archived_member_flips_the_verdict(
    release_rig,
    accepted_release,
):
    """The content scan is what stops a client identifier reaching PyPI.

    The accepted pair scans every non-exempt member and finds nothing; the same
    pair with one marker appended to one archived member is refused by name.
    """
    _, accepted = accepted_release
    assert (
        accepted["measurements"]["archive_content_privacy"][
            "wheel_members_content_scanned"
        ]
        > 0
    )
    target = "COLLECT_PARSE_V3_23_0.py"
    marker = ("\n# " + "Al " + "Jazeera" + " core switch\n").encode("utf-8")

    def plant(payloads: dict) -> dict:
        payloads[target] = payloads[target] + marker
        return payloads

    errors = release_rig.refusal(release_rig.build(mutate=plant))
    assert errors["wheel_content_privacy_errors"] == [
        f"known client marker appears in archive content: {target}"
    ]


def test_the_wheel_must_carry_the_license_and_top_level_it_declares(
    release_rig,
    accepted_release,
):
    """Two holes the accept path exposed: both were allowlist-only.

    `licenses/LICENSE` and `top_level.txt` were named in `_WHEEL_METADATA_FILES`,
    which is the UNEXPECTED-member allowlist -- being listed there permitted them
    and required neither.  Measured before the fix, all three of these mutations
    were ACCEPTED, and the proof read clean:

    * a wheel whose METADATA declares `License-File: LICENSE` and ships no
      license document at all (the only trace was
      `wheel_license_byte_compared_to_worktree` falling from 1 to 0, a number
      nothing compares against anything);
    * a wheel with no `top_level.txt`;
    * a wheel whose `top_level.txt` names a foreign package -- while the sdist's
      identical declaration WAS checked.  The wheel is the artifact pip installs,
      so that was the wrong half of the pair to leave unenforced.
    """
    _, accepted = accepted_release
    declared = release_rig.contract["headers"]["License-File"]
    assert declared, "the fixture must exercise a declared License-File"
    assert (
        accepted["measurements"]["source_bytes"][
            "wheel_license_byte_compared_to_worktree"
        ]
        == len(declared)
    )
    dist_info = (
        f"{_normalised_project(release_rig.contract)}-"
        f"{release_rig.contract['version']}.dist-info"
    )

    def drop_license(payloads: dict) -> dict:
        del payloads[f"{dist_info}/licenses/{declared[0]}"]
        return payloads

    errors = release_rig.refusal(release_rig.build(mutate=drop_license))
    assert errors["wheel_source_mismatches"] == [
        f"{dist_info}/licenses/{declared[0]}: declared by METADATA License-File "
        "and absent from the wheel"
    ]

    def forge_top_level(payloads: dict) -> dict:
        payloads[f"{dist_info}/top_level.txt"] = b"attacker_package\n"
        return payloads

    errors = release_rig.refusal(release_rig.build(mutate=forge_top_level))
    assert errors["wheel_metadata_errors"] == [
        "wheel top_level.txt differs: ['attacker_package'] != "
        f"{sorted(_EXPECTED_TOP_LEVEL_PACKAGES)}"
    ]
    # The sdist's copy is checked by the SAME helper, so the two cannot drift.
    assert (
        distribution_verify._top_level_declaration_errors(
            ["attacker_package"], "sdist"
        )
        == [
            "sdist top_level.txt differs: ['attacker_package'] != "
            f"{sorted(_EXPECTED_TOP_LEVEL_PACKAGES)}"
        ]
    )
    # NON-VACUITY: the declaration the release really makes passes the helper.
    assert (
        distribution_verify._top_level_declaration_errors(
            sorted(_EXPECTED_TOP_LEVEL_PACKAGES), "wheel"
        )
        == []
    )


def test_dynamic_is_accepted_as_a_backend_field_but_only_for_computable_values():
    """`Dynamic` is emitted by the BUILD BACKEND, never declared in pyproject, so it can never appear
    in the contract derived from pyproject — yet it is standard and correct in a wheel.

    Core metadata spec (PEP 643, Metadata 2.2; `License-File` is 2.4): "In any context other than a
    source distribution, `Dynamic` is for information only, and indicates that the field value was
    calculated at wheel build time." setuptools 83.0.0 emits `Dynamic: license-file` for a 2.4 wheel
    whose License-File it collected — and 83.0.0 is the version THIS MODULE PINS via its Generator
    check, so rejecting the header made the verifier refuse its own pinned backend's output. Found by
    building for real: every other check passed and this alone failed the release gate.

    The name is allowed; the VALUE is still constrained. `Dynamic: Requires-Dist` is legal metadata but
    would mean the dependency set was decided at build time, which is exactly what this verifier
    exists to refuse — so widening the header allowlist alone would have been the lazy fix.
    """
    from cisco_toolkit.distribution_verify import _BACKEND_COMPUTABLE_FIELDS

    assert "license-file" in _BACKEND_COMPUTABLE_FIELDS, (
        "setuptools computes License-File; refusing it breaks the pinned backend's own output")
    # NON-VACUITY: the set must be a narrow allowlist, not a blanket pass. A backend must never be
    # the one deciding these.
    for must_not in ("requires-dist", "name", "version", "requires-python", "provides-extra"):
        assert must_not not in _BACKEND_COMPUTABLE_FIELDS, (
            f"{must_not!r} became backend-computable; that field is declared, not calculated")
