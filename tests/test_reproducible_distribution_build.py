import io
import os
from pathlib import Path
import sys
import tarfile
from types import SimpleNamespace

import pytest

from tools import build_reproducible_distributions as subject


COMMIT = "a" * 40
TREE = "b" * 40
EPOCH = 1_700_000_000


def test_clean_environment_removes_every_ambient_git_control(monkeypatch):
    monkeypatch.setenv("GIT_DIR", "attacker")
    monkeypatch.setenv("git_index_file", "attacker-index")
    monkeypatch.setenv("GIT_NO_REPLACE_OBJECTS", "0")
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "999")

    environment = subject._clean_environment(epoch=EPOCH)

    assert environment["SOURCE_DATE_EPOCH"] == str(EPOCH)
    assert {
        key: environment[key]
        for key in environment
        if key.upper().startswith("GIT_")
    } == {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }


def test_git_queries_disable_replacements_and_use_only_clean_environment(monkeypatch, tmp_path):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout=b"a" * 40 + b"\n")

    monkeypatch.setattr(subject.subprocess, "run", fake_run)
    monkeypatch.setenv("GIT_DIR", "attacker")
    monkeypatch.setenv("PATH", str(tmp_path / "fake-git-directory"))
    assert subject._git_text(tmp_path, "rev-parse", "HEAD^{commit}") == "a" * 40
    assert captured["command"][:2] == [
        subject._GIT_EXECUTABLE,
        "--no-replace-objects",
    ]
    assert Path(captured["command"][0]).is_absolute()
    assert "GIT_DIR" not in captured["kwargs"]["env"]
    assert captured["kwargs"]["env"]["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert captured["kwargs"]["env"]["PATH"].split(os.pathsep)[0] == str(
        Path(subject._GIT_EXECUTABLE).parent
    )


def test_source_date_epoch_is_bound_to_the_exact_head(monkeypatch, tmp_path):
    observed = []

    def fake_git(_repository, *arguments):
        observed.append(arguments)
        if arguments[-1] == "HEAD^{commit}":
            return COMMIT
        if arguments[-1].endswith("^{tree}"):
            return TREE
        return str(EPOCH)

    monkeypatch.setattr(subject, "_git_text", fake_git)
    assert subject.source_date_epoch(
        tmp_path,
        expected_commit=COMMIT,
        expected_tree=TREE,
    ) == EPOCH
    assert observed == [
        ("rev-parse", "--verify", "HEAD^{commit}"),
        ("rev-parse", "--verify", f"{COMMIT}^{{tree}}"),
        ("show", "-s", "--no-show-signature", "--format=%ct", COMMIT),
    ]


@pytest.mark.parametrize(
    ("commit", "tree", "error"),
    (
        ("HEAD", TREE, "SOURCE_IDENTITY_INVALID"),
        (COMMIT.upper(), TREE, "SOURCE_IDENTITY_INVALID"),
        (COMMIT, "2" * 39, "SOURCE_IDENTITY_INVALID"),
    ),
)
def test_source_date_epoch_rejects_unresolved_or_noncanonical_ids(
    monkeypatch, tmp_path, commit, tree, error,
):
    monkeypatch.setattr(
        subject,
        "_git_text",
        lambda *_args: (_ for _ in ()).throw(AssertionError("invalid id reached git")),
    )
    with pytest.raises(subject.ReproducibleBuildError, match=error):
        subject.source_date_epoch(
            tmp_path,
            expected_commit=commit,
            expected_tree=tree,
        )


def test_source_date_epoch_rejects_head_drift_and_zip_incompatible_time(monkeypatch, tmp_path):
    monkeypatch.setattr(
        subject,
        "_git_text",
        lambda _repository, *arguments: "3" * 40
        if arguments[-1] == "HEAD^{commit}"
        else TREE,
    )
    with pytest.raises(subject.ReproducibleBuildError, match="SOURCE_IDENTITY_INVALID"):
        subject.source_date_epoch(tmp_path, expected_commit="not-a-sha", expected_tree=TREE)
    with pytest.raises(subject.ReproducibleBuildError, match="SOURCE_IDENTITY_MISMATCH"):
        subject.source_date_epoch(tmp_path, expected_commit=COMMIT, expected_tree=TREE)

    def old_source(_repository, *arguments):
        if arguments[-1] == "HEAD^{commit}":
            return COMMIT
        if arguments[-1].endswith("^{tree}"):
            return TREE
        return "1"

    monkeypatch.setattr(subject, "_git_text", old_source)
    with pytest.raises(subject.ReproducibleBuildError, match="SOURCE_DATE_EPOCH_OUT_OF_RANGE"):
        subject.source_date_epoch(tmp_path, expected_commit=COMMIT, expected_tree=TREE)


def test_build_subprocess_receives_only_the_commit_bound_epoch(monkeypatch, tmp_path):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subject.subprocess, "run", fake_run)
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "999")
    monkeypatch.setenv("GIT_DIR", "attacker")
    lane_root = tmp_path / "lane"
    subject._run_build(
        tmp_path,
        tmp_path / "dist",
        EPOCH,
        kind="wheel",
        lane_root=lane_root,
    )
    assert captured["command"] == [
        sys.executable,
        "-m",
        "build",
        "--wheel",
        "--outdir",
        str(tmp_path / "dist"),
    ]
    assert captured["kwargs"]["cwd"] == tmp_path
    assert captured["kwargs"]["env"]["SOURCE_DATE_EPOCH"] == str(EPOCH)
    assert "GIT_DIR" not in captured["kwargs"]["env"]
    assert captured["kwargs"]["env"]["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert captured["kwargs"]["env"]["HOME"] == str(lane_root / "home")
    assert captured["kwargs"]["env"]["PIP_CACHE_DIR"] == str(lane_root / "pip-cache")
    assert captured["kwargs"]["env"]["TMP"] == str(lane_root / "temp")


def test_build_lanes_do_not_share_mutable_home_cache_or_temp(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", "shared-home-sentinel")
    monkeypatch.setenv("PIP_CACHE_DIR", "shared-cache-sentinel")
    monkeypatch.setenv("XDG_CACHE_HOME", "shared-xdg-sentinel")
    first = subject._build_environment(EPOCH, tmp_path / "lane-a")
    second = subject._build_environment(EPOCH, tmp_path / "lane-b")
    for key in (
        "APPDATA",
        "HOME",
        "LOCALAPPDATA",
        "PIP_CACHE_DIR",
        "PYTHONPYCACHEPREFIX",
        "TEMP",
        "TMP",
        "TMPDIR",
        "USERPROFILE",
        "UV_CACHE_DIR",
        "XDG_CACHE_HOME",
    ):
        assert first[key] != second[key]
        assert "shared-" not in first[key] and "shared-" not in second[key]
    assert first["SOURCE_DATE_EPOCH"] == second["SOURCE_DATE_EPOCH"] == str(EPOCH)


def test_source_verifier_wraps_both_builds_with_exact_identity(monkeypatch, tmp_path):
    commands = []

    def fake_run(command, **kwargs):
        commands.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subject.subprocess, "run", fake_run)
    subject._verify_source(
        tmp_path,
        expected_commit=COMMIT,
        expected_tree=TREE,
    )
    subject._verify_source(
        tmp_path,
        expected_commit=COMMIT,
        expected_tree=TREE,
        allow_build_outputs=True,
    )
    first, second = commands
    assert first[0][0:3] == [sys.executable, "-I", "-B"]
    assert first[0][first[0].index("--expected-commit") + 1] == COMMIT
    assert first[0][first[0].index("--expected-tree") + 1] == TREE
    assert first[0].count("--allow-untracked-prefix") == 0
    assert second[0].count("--allow-untracked-prefix") == 2
    assert second[0][-1] == "cisco_migration_assessment_toolkit.egg-info"
    assert first[1]["cwd"] == tmp_path and second[1]["cwd"] == tmp_path


def _archives(root: Path, wheel: bytes = b"wheel", sdist: bytes = b"sdist"):
    root.mkdir()
    (root / "example-1-py3-none-any.whl").write_bytes(wheel)
    (root / "example-1.tar.gz").write_bytes(sdist)
    return subject._archives(root)


def test_archive_comparison_requires_exact_names_and_bytes(tmp_path):
    primary = _archives(tmp_path / "primary")
    same = _archives(tmp_path / "same")
    result = subject._compare_archives(primary, same)
    assert [item["name"] for item in result] == [
        "example-1-py3-none-any.whl",
        "example-1.tar.gz",
    ]
    changed = _archives(tmp_path / "changed", wheel=b"different")
    with pytest.raises(subject.ReproducibleBuildError, match="ARCHIVE_BYTES_MISMATCH"):
        subject._compare_archives(primary, changed)


@pytest.mark.parametrize("debris_kind", ["file", "directory"])
def test_archive_set_rejects_every_extra_output_entry(tmp_path, debris_kind):
    root = tmp_path / "dist"
    _archives(root)
    debris = root / "unexpected"
    if debris_kind == "file":
        debris.write_bytes(b"debris")
    else:
        debris.mkdir()
    with pytest.raises(subject.ReproducibleBuildError, match="ARCHIVE_SET_INVALID"):
        subject._archives(root)


def _timestamped_sdist(
    path: Path,
    timestamp: int,
    *,
    member_mode: int | None = None,
    member_name: str = "example-1/data.txt",
    member_pax: dict[str, str] | None = None,
) -> None:
    payload = b"same member bytes"
    with tarfile.open(path, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        directory = tarfile.TarInfo("example-1")
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o777
        directory.uid = 123
        directory.gid = 456
        directory.uname = "builder"
        directory.gname = "builder"
        directory.mtime = timestamp
        directory.pax_headers = {"mtime": f"{timestamp}.25"}
        archive.addfile(directory)

        member = tarfile.TarInfo(member_name)
        member.mode = member_mode if member_mode is not None else 0o666
        member.uid = 123
        member.gid = 456
        member.uname = "builder"
        member.gname = "builder"
        member.mtime = timestamp
        member.pax_headers = (
            {"mtime": f"{timestamp}.75"}
            if member_pax is None
            else member_pax
        )
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))


def test_sdist_canonicalization_normalizes_container_metadata_not_payload(tmp_path):
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"
    _timestamped_sdist(first, EPOCH + 10)
    _timestamped_sdist(second, EPOCH + 20)
    subject._canonicalize_sdist(first, EPOCH)
    subject._canonicalize_sdist(second, EPOCH)
    assert first.read_bytes() == second.read_bytes()
    assert int.from_bytes(first.read_bytes()[4:8], "little") == EPOCH

    with tarfile.open(first, mode="r:gz") as archive:
        directory, member = archive.getmembers()
        assert (directory.uid, directory.gid, directory.uname, directory.gname) == (0, 0, "", "")
        assert (directory.mode, directory.mtime, directory.pax_headers) == (0o755, EPOCH, {})
        assert (member.uid, member.gid, member.uname, member.gname) == (0, 0, "", "")
        assert (member.mode, member.mtime, member.pax_headers) == (0o644, EPOCH, {})
        assert archive.extractfile(member).read() == b"same member bytes"


@pytest.mark.parametrize("member_mode", (0o100, 0o010, 0o001, 0o711))
def test_sdist_canonicalization_preserves_any_executable_semantics(tmp_path, member_mode):
    archive_path = tmp_path / "executable.tar.gz"
    _timestamped_sdist(archive_path, EPOCH + 1, member_mode=member_mode)

    subject._canonicalize_sdist(archive_path, EPOCH)

    with tarfile.open(archive_path, mode="r:gz") as archive:
        _directory, member = archive.getmembers()
        assert member.mode == 0o755
        assert member.mtime == EPOCH
        assert archive.extractfile(member).read() == b"same member bytes"


def test_sdist_canonicalization_supports_required_long_utf8_pax_path(tmp_path):
    archive_path = tmp_path / "unicode.tar.gz"
    long_name = "example-1/" + ("network-" * 20) + "café.txt"
    _timestamped_sdist(
        archive_path,
        EPOCH + 1,
        member_name=long_name,
        member_pax={"path": long_name, "mtime": f"{EPOCH + 1}.5"},
    )

    subject._canonicalize_sdist(archive_path, EPOCH)

    with tarfile.open(archive_path, mode="r:gz") as archive:
        _directory, member = archive.getmembers()
        assert member.name == long_name
        assert set(member.pax_headers) == {"path"}
        assert archive.extractfile(member).read() == b"same member bytes"


@pytest.mark.parametrize(
    "name",
    [
        "",
        "/absolute",
        "C:/drive-qualified",
        "example-1\\backslash",
        "example-1/../escape",
        "example-1/./dot",
        "example-1//empty",
        "example-1/con",
        "example-1/name. ",
        "example-1/control\x1f",
    ],
)
def test_sdist_member_guard_rejects_nonportable_names(name):
    member = tarfile.TarInfo(name)
    with pytest.raises(subject.ReproducibleBuildError, match="SDIST_MEMBER_INVALID"):
        subject._safe_sdist_member(member, set())


@pytest.mark.parametrize(
    "member_type",
    [
        tarfile.SYMTYPE,
        tarfile.LNKTYPE,
        tarfile.FIFOTYPE,
        tarfile.CHRTYPE,
        tarfile.BLKTYPE,
    ],
)
def test_sdist_member_guard_rejects_links_and_special_members(member_type):
    member = tarfile.TarInfo("example-1/special")
    member.type = member_type
    with pytest.raises(subject.ReproducibleBuildError, match="SDIST_MEMBER_INVALID"):
        subject._safe_sdist_member(member, set())


def test_sdist_member_guard_rejects_unknown_pax_and_portable_collisions():
    unknown = tarfile.TarInfo("example-1/data.txt")
    unknown.pax_headers = {"SCHILY.xattr.user.probe": "value"}
    with pytest.raises(subject.ReproducibleBuildError, match="SDIST_MEMBER_INVALID"):
        subject._safe_sdist_member(unknown, set())

    seen: set[str] = set()
    subject._safe_sdist_member(tarfile.TarInfo("example-1/Café.txt"), seen)
    for collision in ("example-1/CAFÉ.TXT", "example-1/Café.txt"):
        with pytest.raises(subject.ReproducibleBuildError, match="SDIST_MEMBER_INVALID"):
            subject._safe_sdist_member(tarfile.TarInfo(collision), seen)


def _buildable_sdist(path: Path) -> None:
    members = {
        "example-1/pyproject.toml": b"[build-system]\nrequires=[]\n",
        "example-1/PKG-INFO": b"Metadata-Version: 2.4\nName: example\nVersion: 1\n",
        "example-1/bin/probe": b"#!/bin/sh\nexit 0\n",
    }
    with tarfile.open(path, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        root = tarfile.TarInfo("example-1")
        root.type = tarfile.DIRTYPE
        root.mode = 0o755
        archive.addfile(root)
        for name, payload in members.items():
            member = tarfile.TarInfo(name)
            member.mode = 0o755 if name.endswith("/probe") else 0o644
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))


def test_safe_extraction_retains_build_root_and_executable_mode(tmp_path):
    archive_path = tmp_path / "example-1.tar.gz"
    _buildable_sdist(archive_path)

    root = subject._extract_sdist(archive_path, tmp_path / "extracted")

    assert root == tmp_path / "extracted" / "example-1"
    assert (root / "pyproject.toml").is_file()
    assert (root / "PKG-INFO").is_file()
    if os.name != "nt":
        assert (root / "bin" / "probe").stat().st_mode & 0o777 == 0o755


def test_payload_copy_is_streamed_in_bounded_chunks():
    class RecordingReader(io.BytesIO):
        def __init__(self, payload):
            super().__init__(payload)
            self.requests = []

        def read(self, size=-1):
            self.requests.append(size)
            return super().read(size)

    payload = b"x" * (2 * 1024 * 1024 + 17)
    source = RecordingReader(payload)
    destination = io.BytesIO()

    subject._stream_payload(source, len(payload), destination=destination)

    assert destination.getvalue() == payload
    assert max(source.requests) <= 1024 * 1024
    assert source.requests[-1] == 1


def test_materialization_uses_a_no_local_no_checkout_lf_exact_clone(monkeypatch, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    destination = tmp_path / "clone"
    git_calls = []
    verified = []

    def fake_run_git(cwd, *arguments):
        git_calls.append((cwd, arguments))
        if arguments[0] == "clone":
            destination.mkdir()

    def fake_git_text(_repository, *arguments):
        return TREE if arguments[-1].endswith("^{tree}") else COMMIT

    monkeypatch.setattr(subject, "_run_git", fake_run_git)
    monkeypatch.setattr(subject, "_git_text", fake_git_text)
    monkeypatch.setattr(
        subject,
        "_verify_source",
        lambda repository, **kwargs: verified.append((repository, kwargs)),
    )

    subject._materialize_source(
        source,
        destination,
        expected_commit=COMMIT,
        expected_tree=TREE,
    )

    assert git_calls[0] == (
        destination.parent,
        (
            "clone",
            "--no-local",
            "--no-checkout",
            "--quiet",
            str(source),
            str(destination),
        ),
    )
    assert [call[1] for call in git_calls[1:4]] == [
        ("config", "core.autocrlf", "false"),
        ("config", "core.eol", "lf"),
        ("config", "core.safecrlf", "true"),
    ]
    assert git_calls[4][1] == ("checkout", "--detach", "--quiet", COMMIT)
    assert verified == [
        (destination, {"expected_commit": COMMIT, "expected_tree": TREE})
    ]


def test_candidate_builds_sdist_then_wheel_from_the_canonical_sdist(monkeypatch, tmp_path):
    source = tmp_path / "clone"
    source.mkdir()
    workspace = tmp_path / "candidate"
    calls = []
    verified = []

    def fake_build(repository, output, epoch, *, kind, lane_root):
        calls.append((repository, output, epoch, kind, lane_root))
        output.mkdir()
        if kind == "sdist":
            _buildable_sdist(output / "example-1.tar.gz")
        else:
            (output / "example-1-py3-none-any.whl").write_bytes(b"wheel")

    monkeypatch.setattr(subject, "_run_build", fake_build)
    monkeypatch.setattr(
        subject,
        "_verify_source",
        lambda repository, **kwargs: verified.append((repository, kwargs)),
    )

    artifacts = subject._build_candidate(
        source,
        workspace,
        epoch=EPOCH,
        expected_commit=COMMIT,
        expected_tree=TREE,
    )

    extracted_root = workspace / "extracted" / "example-1"
    assert calls == [
        (
            source,
            workspace / "raw-sdist",
            EPOCH,
            "sdist",
            workspace / "environment-sdist",
        ),
        (
            extracted_root,
            workspace / "raw-wheel",
            EPOCH,
            "wheel",
            workspace / "environment-wheel",
        ),
    ]
    assert set(artifacts) == {
        "example-1.tar.gz",
        "example-1-py3-none-any.whl",
    }
    assert verified == [
        (
            source,
            {
                "expected_commit": COMMIT,
                "expected_tree": TREE,
                "allow_build_outputs": True,
            },
        )
    ]


def _install_orchestration_fakes(monkeypatch, events):
    records = [
        {"bytes": 5, "name": "example-1-py3-none-any.whl", "sha256": "1" * 64},
        {"bytes": 5, "name": "example-1.tar.gz", "sha256": "2" * 64},
    ]
    epoch_calls = 0

    def fake_epoch(*_args, **_kwargs):
        nonlocal epoch_calls
        epoch_calls += 1
        events.append(f"epoch-{epoch_calls}")
        return EPOCH

    def fake_verify(repository, **kwargs):
        events.append(("verify", repository, kwargs.get("staged_output")))

    def fake_materialize(_repository, destination, **_kwargs):
        destination.mkdir()
        events.append(("materialize", destination.name))

    def fake_candidate(source, workspace, **_kwargs):
        workspace.mkdir()
        final = workspace / "final"
        _archives(final, wheel=b"bytes", sdist=b"bytes")
        events.append(("candidate", source.name, workspace.name))
        return subject._archives(final)

    def fake_compare(_primary, _replay):
        events.append("compare")
        return records

    def fake_stage(primary, output):
        staged = output.parent / ".dist.publishing-test"
        staged.mkdir()
        for name, path in primary.items():
            (staged / name).write_bytes(path.read_bytes())
        events.append("stage")
        return staged

    def fake_measure(_archives):
        events.append("remeasure")
        return records

    def fake_publish(staged, output, expected):
        assert expected == records
        events.append("publish")
        staged.rename(output)

    monkeypatch.setattr(subject, "source_date_epoch", fake_epoch)
    monkeypatch.setattr(subject, "_verify_source", fake_verify)
    monkeypatch.setattr(subject, "_materialize_source", fake_materialize)
    monkeypatch.setattr(subject, "_build_candidate", fake_candidate)
    monkeypatch.setattr(subject, "_compare_archives", fake_compare)
    monkeypatch.setattr(subject, "_stage_archives", fake_stage)
    monkeypatch.setattr(subject, "_measure_archives", fake_measure)
    monkeypatch.setattr(subject, "_publish_staged_archives", fake_publish)
    return records


def test_two_cold_clones_compare_before_final_verification_and_atomic_publish(
    monkeypatch, tmp_path,
):
    events = []
    records = _install_orchestration_fakes(monkeypatch, events)
    output = tmp_path / "dist"

    result = subject.build_reproducible_distributions(
        tmp_path,
        output,
        expected_commit=COMMIT,
        expected_tree=TREE,
    )

    assert events[0:4] == [
        "epoch-1",
        ("verify", tmp_path, None),
        ("materialize", "source-primary"),
        ("materialize", "source-replay"),
    ]
    assert events[4][0:2] == ("candidate", "source-primary")
    assert events[5][0:2] == ("candidate", "source-replay")
    assert events[4][2] != events[5][2]
    assert events[6:] == [
        "compare",
        "stage",
        "epoch-2",
        ("verify", tmp_path, tmp_path / ".dist.publishing-test"),
        "remeasure",
        "publish",
    ]
    assert output.is_dir()
    assert result == {
        "artifacts": records,
        "reproducible": True,
        "source_commit": COMMIT,
        "source_date_epoch": EPOCH,
        "source_tree": TREE,
    }


def test_staged_output_is_removed_if_final_source_verification_fails(monkeypatch, tmp_path):
    events = []
    _install_orchestration_fakes(monkeypatch, events)

    def fail_final_verification(repository, **kwargs):
        events.append(("verify", repository, kwargs.get("staged_output")))
        if kwargs.get("staged_output") is not None:
            raise subject.ReproducibleBuildError("SOURCE_WORKTREE_MISMATCH")

    monkeypatch.setattr(subject, "_verify_source", fail_final_verification)
    output = tmp_path / "dist"

    with pytest.raises(subject.ReproducibleBuildError, match="SOURCE_WORKTREE_MISMATCH"):
        subject.build_reproducible_distributions(
            tmp_path,
            output,
            expected_commit=COMMIT,
            expected_tree=TREE,
        )

    assert not output.exists()
    assert not (tmp_path / ".dist.publishing-test").exists()
    assert "publish" not in events


def test_source_verifier_allows_only_the_exact_staged_directory(monkeypatch, tmp_path):
    staged = tmp_path / ".dist.publishing-exact"
    staged.mkdir()
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subject.subprocess, "run", fake_run)
    subject._verify_source(
        tmp_path,
        expected_commit=COMMIT,
        expected_tree=TREE,
        staged_output=staged,
    )

    command = captured["command"]
    assert command.count("--allow-untracked-prefix") == 1
    assert command[-1] == ".dist.publishing-exact"


def test_post_publish_remeasurement_quarantines_changed_staged_bytes(tmp_path):
    staged = tmp_path / ".dist.publishing-mutated"
    archives = _archives(staged, wheel=b"original", sdist=b"original")
    expected = subject._measure_archives(archives)
    archives["example-1-py3-none-any.whl"].write_bytes(b"changed")
    output = tmp_path / "dist"

    with pytest.raises(
        subject.ReproducibleBuildError,
        match="PUBLISHED_ARCHIVE_BYTES_MISMATCH",
    ):
        subject._publish_staged_archives(staged, output, expected)

    assert not output.exists()
    rejected = list(tmp_path.glob(".dist.rejected-*"))
    assert len(rejected) == 1 and rejected[0].is_dir()


def test_post_publish_measurement_rejects_entry_added_after_first_census(
    monkeypatch, tmp_path,
):
    staged = tmp_path / ".dist.publishing-member-race"
    archives = _archives(staged, wheel=b"original", sdist=b"original")
    expected = subject._measure_archives(archives)
    output = tmp_path / "dist"
    observe = subject._archive_set_observation
    attempts = 0

    def inject_after_first_census(directory):
        nonlocal attempts
        attempts += 1
        result = observe(directory)
        if attempts == 1:
            (directory / "unmeasured-entry").write_bytes(b"not in receipt")
        return result

    monkeypatch.setattr(subject, "_archive_set_observation", inject_after_first_census)

    with pytest.raises(subject.ReproducibleBuildError, match="ARCHIVE_SET_INVALID"):
        subject._publish_staged_archives(staged, output, expected)

    assert attempts == 2
    assert not output.exists()
    rejected = list(tmp_path.glob(".dist.rejected-*"))
    assert len(rejected) == 1 and rejected[0].is_dir()


def test_build_refuses_any_existing_output_directory_before_source_resolution(
    monkeypatch, tmp_path,
):
    output = tmp_path / "dist"
    output.mkdir()
    monkeypatch.setattr(
        subject,
        "source_date_epoch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("existing output reached source resolution")
        ),
    )
    with pytest.raises(subject.ReproducibleBuildError, match="OUTPUT_DIRECTORY_EXISTS"):
        subject.build_reproducible_distributions(
            tmp_path,
            output,
            expected_commit=COMMIT,
            expected_tree=TREE,
        )
